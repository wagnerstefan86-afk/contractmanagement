#!/usr/bin/env python3
"""
Stage 5 — Requirement Matching Engine  (v3 — clause-level matching + LLM refinement)

Loads the organization's regulatory profile from org_profile.json to determine
which frameworks apply, then matches each extracted clause directly against the
corresponding sub-requirement catalog.

Data flow:
    org_profile.json          ← authoritative source for regulatory_frameworks
          │
    contract_metadata.json    ← contract_type, vendor_risk_tier, data_sensitivity
          │
    stage4_clauses.json       ← extracted clauses with clause_id, page, text
          │
    [SR catalog selection]    ← filter catalog by org frameworks + contract context
          │
    [deterministic matching]  ← regex-based candidate narrowing (unchanged)
          │
    [LLM refinement]          ← optional: LLM validates non-NO_MATCH candidates
                                supports Anthropic and OpenAI via provider abstraction
          │
    clause_sr_matches.json    ← per-(clause, SR) match records with _ai_metadata

Architecture (v3):
    OLD: deterministic only
    NEW: deterministic candidate filtering → LLM validation of non-NO_MATCH pairs
         LLM is never called for NO_MATCH (saves ~70% of calls)
         LLM can upgrade PARTIAL to DIRECT or downgrade DIRECT to PARTIAL/NO_MATCH

Usage:
    python stage5_matching.py \\
        --org-profile   org_profile.json \\
        --metadata      contract_metadata.json \\
        --clauses       stage4_clauses.json \\
        --output        clause_sr_matches.json
"""

import json
import re
import sys
import argparse
import datetime
import logging
import os
from pathlib import Path
from typing import Optional

# Bootstrap project root so 'llm.*' is importable regardless of CWD
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("stage5")

# ---------------------------------------------------------------------------
# LLM module imports (graceful degradation)
# ---------------------------------------------------------------------------

try:
    from llm.base import BaseLLMProvider, LLMAuditMetadata, DETERMINISTIC_AI_META
    from llm.prompts import (
        SR_MATCHING_SYSTEM_PROMPT,
        SR_MATCHING_OUTPUT_SCHEMA,
        PROMPT_VERSION_SR_MATCHING,
        build_sr_matching_user_message,
    )
    from llm.tracing import (
        confidence_bucket,
        decision_delta_match,
        review_priority_match,
        build_sr_match_trace,
    )
    LLM_MODULE_AVAILABLE = True
except ImportError:
    LLM_MODULE_AVAILABLE = False
    BaseLLMProvider = None  # type: ignore[assignment, misc]
    DETERMINISTIC_AI_META: dict = {
        "llm_used": False, "provider": None, "model": None,
        "prompt_version": None, "confidence": None,
    }

    # Inline fallbacks — no external deps required
    def confidence_bucket(c):  # type: ignore[misc]
        if c is None: return None
        return "high" if c >= 0.85 else "medium" if c >= 0.60 else "low"

    def decision_delta_match(base_mt, final_mt, ai):  # type: ignore[misc]
        if not ai: return None
        if base_mt == final_mt: return "no_change"
        order = {"NO_MATCH": 0, "PARTIAL_MATCH": 1, "DIRECT_MATCH": 2}
        return "ai_upgrade" if order.get(final_mt, 0) > order.get(base_mt, 0) else "ai_downgrade"

    def review_priority_match(match_type, conf_bkt, delta):  # type: ignore[misc]
        if conf_bkt == "low" or delta in ("ai_upgrade", "ai_downgrade"):
            return "HIGH"
        if conf_bkt == "medium" or match_type == "PARTIAL_MATCH":
            return "MEDIUM"
        return "LOW"

    def build_sr_match_trace(baseline_mt, llm_content, source):  # type: ignore[misc]
        return None

# ---------------------------------------------------------------------------
# Sub-requirement catalog
# ---------------------------------------------------------------------------

RISK_TIER_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

SR_CATALOG: list[dict] = [
    # ── ISO 27001 ──────────────────────────────────────────────────────────
    {
        "id":         "SR-ISO27001-01",
        "control_id": "ISO27001:2022 A.5.1",
        "framework":  "ISO27001",
        "title":      "Information Security Policy",
        "applicable_contract_types": None,
        "min_risk_tier": "LOW",
        "severity":   "HIGH",
        "match_patterns": [
            r"information security policy",
            r"iso.{0,5}27001",
            r"\bisms\b",
            r"information security management system",
        ],
        "retrieval_synonyms": [
            "information security",
            "security policy",
            "ISMS",
            "ISO 27001",
            "security management",
            "security controls",
            "security framework",
        ],
    },
    {
        "id":         "SR-ISO27001-02",
        "control_id": "ISO27001:2022 A.17.1",
        "framework":  "ISO27001",
        "title":      "Business Continuity & Disaster Recovery",
        "applicable_contract_types": None,
        "min_risk_tier": "MEDIUM",
        "severity":   "HIGH",
        "match_patterns": [
            r"business continuity",
            r"disaster recovery",
            r"recovery time objective|\brto\b",
            r"recovery point objective|\brpo\b",
            r"\bbcp\b|\bdrp\b",
        ],
        "retrieval_synonyms": [
            "business continuity plan",
            "disaster recovery plan",
            "RTO",
            "RPO",
            "BCP",
            "DRP",
            "service restoration",
            "resilience planning",
            "availability recovery",
        ],
    },
    {
        "id":         "SR-ISO27001-03",
        "control_id": "ISO27001:2022 A.18.2",
        "framework":  "ISO27001",
        "title":      "Audit Rights",
        "applicable_contract_types": None,
        "min_risk_tier": "MEDIUM",
        "severity":   "MEDIUM",
        "match_patterns": [
            r"audit right",
            r"right to audit",
            r"third.party audit",
            r"\bsoc 2\b",
            r"penetration test",
        ],
        "retrieval_synonyms": [
            "audit access",
            "inspection rights",
            "security assessment",
            "SOC 2",
            "penetration testing",
            "compliance audit",
            "vendor audit",
            "audit report",
        ],
    },
    # ── DORA ──────────────────────────────────────────────────────────────
    {
        "id":         "SR-DORA-01",
        "control_id": "DORA Art. 6-10",
        "framework":  "DORA",
        "title":      "ICT Risk Management Framework",
        "applicable_contract_types": ["ICT_OUTSOURCING", "CLOUD_HOSTING", "SAAS"],
        "min_risk_tier": "HIGH",
        "severity":   "HIGH",
        "match_patterns": [
            r"ict risk management",
            r"dora art\. ?[6-9]|dora art\. ?10",
            r"digital operational resilience",
            r"third.party ict",
            r"tlpt|threat.led penetration",
        ],
        "retrieval_synonyms": [
            "ICT risk",
            "digital resilience",
            "operational resilience",
            "technology risk management",
            "cyber resilience",
            "DORA compliance",
            "financial entity ICT",
            "third-party ICT risk",
        ],
    },
    {
        "id":         "SR-DORA-02",
        "control_id": "DORA Art. 17, 19",
        "framework":  "DORA",
        "title":      "ICT Incident Reporting to Authorities",
        "applicable_contract_types": ["ICT_OUTSOURCING", "CLOUD_HOSTING", "SAAS"],
        "min_risk_tier": "HIGH",
        "severity":   "HIGH",
        "match_patterns": [
            r"ict.related incident",
            r"major incident",
            r"report.{0,20}authorit",
            r"dora art\. ?17|dora art\. ?19",
            r"competent authorit",
        ],
        "retrieval_synonyms": [
            # Regulatory authority synonyms: TF-IDF cannot bridge "supervisory bodies"
            # to "competent authorities" without these explicit vocabulary additions.
            # See: docs/tfidf_limitations.md for design rationale.
            "supervisory authority",
            "supervisory body",
            "supervisory bodies",
            "regulatory body",
            "regulatory authority",
            "regulatory notification",
            "supervisory authority reporting",
            "incident reporting",
            "notify authorities",
            "financial regulator",
            "operational disruption",
        ],
    },
    {
        "id":         "SR-DORA-03",
        "control_id": "DORA Art. 30",
        "framework":  "DORA",
        "title":      "Third-Party Contractual Requirements (DORA Art. 30)",
        "applicable_contract_types": ["ICT_OUTSOURCING", "CLOUD_HOSTING"],
        "min_risk_tier": "CRITICAL",
        "severity":   "HIGH",
        "match_patterns": [
            r"dora art\. ?30",
            r"contractual arrangement",
            r"exit strategy",
            r"sub.outsourc",
            r"concentration risk",
        ],
        "retrieval_synonyms": [
            "DORA article 30",
            "contractual requirements",
            "exit plan",
            "outsourcing arrangement",
            "concentration risk",
            "sub-outsourcing",
            "termination assistance",
        ],
    },
    # ── NIS2 ──────────────────────────────────────────────────────────────
    {
        "id":         "SR-NIS2-01",
        "control_id": "NIS2 Art. 23",
        "framework":  "NIS2",
        "title":      "Cybersecurity Incident Reporting Timelines",
        "applicable_contract_types": None,
        "min_risk_tier": "MEDIUM",
        "severity":   "HIGH",
        "match_patterns": [
            r"24.hour|24h.{0,10}notif",
            r"72.hour|72h.{0,10}report",
            r"early warning",
            r"nis2|directive.{0,10}2022.{0,5}2555",
            r"significant.{0,20}incident",
        ],
        "retrieval_synonyms": [
            "incident notification",
            "cybersecurity incident",
            "breach notification",
            "early warning notification",
            "NIS2 reporting",
            "significant incident",
            "reporting timelines",
            "72 hour",
            "24 hour notification",
        ],
    },
    {
        "id":         "SR-NIS2-02",
        "control_id": "NIS2 Art. 21(d)",
        "framework":  "NIS2",
        "title":      "Supply Chain Security",
        "applicable_contract_types": None,
        "min_risk_tier": "HIGH",
        "severity":   "MEDIUM",
        "match_patterns": [
            r"supply chain security",
            r"\bsubcontract",
            # Narrowed: require supply-chain context to avoid collision with SR-GDPR-04
            # (Subprocessor Management).  Standalone "subprocessor" in a GDPR/DPA
            # clause should match GDPR-04, not NIS2 supply-chain security.
            # INTENTIONAL OVERLAP with SR-GDPR-04: a clause that discusses
            # subprocessors *in a supply-chain security context* legitimately belongs
            # to both SRs.  Document this here so reviewers understand the design.
            r"supply.chain.{0,60}sub.?processor|sub.?processor.{0,60}supply.chain",
            r"fourth.party|4th.party",
            r"vendor security assessment",
        ],
        "retrieval_synonyms": [
            "supply chain",
            "third-party security",
            "vendor assessment",
            "subcontractor security",
            "fourth party risk",
            "ICT supply chain",
            "NIS2 article 21",
        ],
    },
    # ── GDPR ──────────────────────────────────────────────────────────────
    {
        "id":         "SR-GDPR-01",
        "control_id": "GDPR Art. 12-22",
        "framework":  "GDPR",
        "title":      "Data Subject Rights Handling",
        "applicable_contract_types": ["DATA_PROCESSING", "SAAS", "CLOUD_HOSTING"],
        "min_risk_tier": "LOW",
        "severity":   "HIGH",
        "match_patterns": [
            r"data subject right",
            r"right of access|art\. ?15",
            # Anchored to GDPR context to avoid false positives on DORA Art. 17.
            # Bare "art. 17" matches cross-framework (e.g. DORA Art. 17 incident reporting);
            # require "gdpr" prefix OR co-occurrence with erasure/forgotten keywords.
            r"right to erasure|right to be forgotten|gdpr.{0,10}art\.?\s*17",
            r"data portabilit|art\. ?20",
            r"right to object|art\. ?21",
        ],
        "retrieval_synonyms": [
            "data subject rights",
            "right of erasure",
            "right of access",
            "right to be forgotten",
            "data portability",
            "right to object",
            "GDPR article 15",
            "GDPR article 17",
            "GDPR article 20",
        ],
    },
    {
        "id":         "SR-GDPR-02",
        "control_id": "GDPR Art. 28",
        "framework":  "GDPR",
        "title":      "Data Processing Agreement (Art. 28)",
        "applicable_contract_types": ["DATA_PROCESSING"],
        "min_risk_tier": "LOW",
        "severity":   "HIGH",
        "match_patterns": [
            r"data processing agreement|\bdpa\b",
            r"gdpr art\. ?28|article 28",
            r"data processor",
            r"data controller",
            r"processing.{0,20}instruction",
        ],
        "retrieval_synonyms": [
            "DPA",
            "data processing agreement",
            "data processor obligations",
            "controller processor relationship",
            "processing instructions",
            "GDPR article 28",
            "processor agreement",
        ],
    },
    {
        "id":         "SR-GDPR-03",
        "control_id": "GDPR Art. 44-49",
        "framework":  "GDPR",
        "title":      "International Data Transfers",
        "applicable_contract_types": ["DATA_PROCESSING", "SAAS"],
        "min_risk_tier": "MEDIUM",
        "severity":   "MEDIUM",
        "match_patterns": [
            r"standard contractual clause|\bscc\b",
            r"third country transfer",
            r"adequacy decision",
            r"gdpr chapter v",
            r"binding corporate rule",
        ],
        "retrieval_synonyms": [
            # Domain language variants for cross-border transfer clauses that use
            # paraphrased language (e.g. "countries outside the EEA") rather than
            # the canonical GDPR terminology ("third country transfer", "SCC").
            "international data transfer",
            "cross-border data transfer",
            "transfer outside EEA",
            "European Economic Area",
            "data transfer safeguards",
            "transfer mechanism",
            "data export",
            "equivalent protection",
            "transfer to third country",
            "SCC",
            "standard contractual clauses",
        ],
    },
    {
        "id":         "SR-GDPR-04",
        "control_id": "GDPR Art. 28(4)",
        "framework":  "GDPR",
        "title":      "Subprocessor Management",
        "applicable_contract_types": ["DATA_PROCESSING", "SAAS"],
        "min_risk_tier": "MEDIUM",
        "severity":   "MEDIUM",
        "match_patterns": [
            r"subprocessor|sub.processor",
            r"list of.{0,20}subprocessor",
            r"subprocessor.{0,30}notif",
            r"gdpr art\. ?28.{0,5}4",
        ],
        "retrieval_synonyms": [
            "subprocessor list",
            "sub-processor notification",
            "GDPR article 28",
            "processor registry",
            "subprocessor approval",
            "subprocessor changes",
            "data processor",
        ],
    },
]

# Pre-compile all SR match patterns once at module load.
# _deterministic_match() uses sr["_compiled"] to avoid recompiling per call.
for _sr in SR_CATALOG:
    _sr["_compiled"] = [re.compile(p, re.IGNORECASE) for p in _sr["match_patterns"]]

# O(1) SR lookup by id — used by _print_summary().
SR_CATALOG_BY_ID: dict[str, dict] = {sr["id"]: sr for sr in SR_CATALOG}

# ---------------------------------------------------------------------------
# Semantic retrieval configuration (env-based)
# ---------------------------------------------------------------------------

STAGE5_SEMANTIC_ENABLED   = os.environ.get(
    "STAGE5_SEMANTIC_RETRIEVAL_ENABLED", "true"
).lower() in ("true", "1", "yes")
STAGE5_MAX_CANDIDATES     = int(os.environ.get("STAGE5_MAX_CANDIDATES",    "8"))
STAGE5_SEMANTIC_TOP_K     = int(os.environ.get("STAGE5_SEMANTIC_TOP_K",    "5"))
STAGE5_MIN_SEMANTIC_SCORE = float(os.environ.get("STAGE5_MIN_SEMANTIC_SCORE", "0.15"))

# Evaluation / benchmark mode (offline quality measurement — never affects matching)
CONTRACT_EVAL_MODE    = os.environ.get("CONTRACT_EVAL_MODE",   "false").lower() in ("true", "1", "yes")
STAGE5_BENCHMARK_PATH = os.environ.get("STAGE5_BENCHMARK_PATH", None)

# Build TF-IDF retrieval corpus once at module load.
# Read-only after construction; safe for concurrent/multi-tenant use.
_SR_CORPUS = None
if STAGE5_SEMANTIC_ENABLED:
    try:
        from llm.retrieval import SRCorpus as _SRCorpus
        _SR_CORPUS = _SRCorpus(SR_CATALOG)
        log.info(
            f"Semantic retrieval: corpus built "
            f"({_SR_CORPUS.corpus_size} SRs, {_SR_CORPUS.vocab_size} terms)"
        )
    except Exception as _corpus_exc:
        log.warning(
            f"Semantic retrieval corpus build failed: {_corpus_exc}; "
            "falling back to deterministic-only candidate selection."
        )


# ---------------------------------------------------------------------------
# Semantic candidate helpers
# ---------------------------------------------------------------------------

def _get_semantic_candidates(
    clause_text:    str,
    applicable_srs: list[dict],
    clause_id:      str,
) -> dict[str, dict]:
    """
    Query the module-level TF-IDF corpus and return a {sr_id → result_dict}
    map limited to SRs that are applicable for this run.

    Returns an empty dict if semantic retrieval is disabled, the corpus was
    not built, or the query raises an unexpected exception (safe fallback).
    """
    if _SR_CORPUS is None:
        return {}
    applicable_ids = [sr["id"] for sr in applicable_srs]
    try:
        results = _SR_CORPUS.query(
            clause_text   = clause_text,
            top_k         = STAGE5_SEMANTIC_TOP_K,
            min_score     = STAGE5_MIN_SEMANTIC_SCORE,
            filter_sr_ids = applicable_ids,
        )
        return {r["sr_id"]: r for r in results}
    except Exception as exc:
        log.warning(f"Semantic retrieval failed for {clause_id}: {exc}")
        return {}


def _build_merged_shortlist(
    det_candidate_ids: set[str],
    semantic_map:      dict[str, dict],
    max_candidates:    int,
) -> set[str]:
    """
    Merge deterministic and semantic candidates into a capped shortlist.

    Deterministic candidates are always kept.
    Semantic-only candidates are added in descending score order until
    the shortlist reaches *max_candidates*.
    """
    shortlist: set[str] = set(det_candidate_ids)
    remaining  = max(0, max_candidates - len(shortlist))
    sem_sorted = sorted(
        (r for r in semantic_map.values() if r["sr_id"] not in shortlist),
        key=lambda r: r["score"],
        reverse=True,
    )
    for r in sem_sorted[:remaining]:
        shortlist.add(r["sr_id"])
    return shortlist


def _semantic_score_bucket(score: Optional[float]) -> Optional[str]:
    """
    Bucket a semantic similarity score for human-readable evaluation.

    high   : score >= 0.70  (strong lexical overlap with SR)
    medium : score >= 0.35  (moderate overlap)
    low    : score <  0.35  (weak overlap — higher false-positive risk)
    None   : no semantic score (SR came from deterministic only, or excluded)
    """
    if score is None:
        return None
    if score >= 0.70:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"


def _make_candidate_metadata(
    is_det:    bool,
    is_sem:    bool,
    sem_score: Optional[float],
) -> dict:
    """Build the _candidate_metadata dict for a single (clause, SR) record."""
    bkt = _semantic_score_bucket(sem_score)
    if is_det and is_sem:
        return {
            "deterministic_candidate": True,
            "semantic_candidate":      True,
            "semantic_score":          sem_score,
            "semantic_score_bucket":   bkt,
            "candidate_source":        "merged",
        }
    if is_det:
        return {
            "deterministic_candidate": True,
            "semantic_candidate":      False,
            "semantic_score":          None,
            "semantic_score_bucket":   None,
            "candidate_source":        "deterministic",
        }
    if is_sem:
        return {
            "deterministic_candidate": False,
            "semantic_candidate":      True,
            "semantic_score":          sem_score,
            "semantic_score_bucket":   bkt,
            "candidate_source":        "semantic",
        }
    return {
        "deterministic_candidate": False,
        "semantic_candidate":      False,
        "semantic_score":          None,
        "semantic_score_bucket":   None,
        "candidate_source":        "excluded",
    }


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_org_profile(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        profile = json.load(f)
    frameworks = profile.get("regulatory_frameworks")
    if not frameworks or not isinstance(frameworks, list):
        raise ValueError("org_profile.json must contain a non-empty 'regulatory_frameworks' list.")
    log.info(f"Org profile loaded: {profile.get('organization_name')}  frameworks={frameworks}")
    return profile


def load_contract_metadata(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        meta = json.load(f)
    required = {"contract_id", "contract_type", "vendor_risk_tier", "data_sensitivity"}
    missing = required - meta.keys()
    if missing:
        raise ValueError(f"contract_metadata.json missing fields: {missing}")
    if "regulatory_scope" in meta:
        log.warning(
            "contract_metadata.json contains 'regulatory_scope' — this field is deprecated "
            "and will be ignored. Use org_profile.json instead."
        )
    log.info(
        f"Contract metadata: id={meta['contract_id']}  type={meta['contract_type']}  "
        f"risk={meta['vendor_risk_tier']}  sensitivity={meta['data_sensitivity']}"
    )
    return meta


def load_clauses(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    raise ValueError("stage4_clauses.json must be a JSON array of clause objects")


# ---------------------------------------------------------------------------
# SR catalog filtering (unchanged from v2)
# ---------------------------------------------------------------------------

def select_applicable_srs(
    catalog:          list[dict],
    frameworks_to_check: list[str],
    contract_type:    str,
    vendor_risk_tier: str,
) -> list[dict]:
    """Filter the SR catalog to SRs applicable to this contract review run."""
    applicable = []
    skipped    = []
    contract_risk_level = RISK_TIER_ORDER.get(vendor_risk_tier, 0)

    for sr in catalog:
        if sr["framework"] not in frameworks_to_check:
            skipped.append(f"{sr['id']} (framework {sr['framework']} not in org profile)")
            continue
        if sr["applicable_contract_types"] is not None:
            if contract_type not in sr["applicable_contract_types"]:
                skipped.append(f"{sr['id']} (contract type {contract_type} not applicable)")
                continue
        sr_min_level = RISK_TIER_ORDER.get(sr["min_risk_tier"], 0)
        if contract_risk_level < sr_min_level:
            skipped.append(f"{sr['id']} (risk {vendor_risk_tier} below minimum {sr['min_risk_tier']})")
            continue
        applicable.append(sr)

    log.info(f"SR selection: {len(applicable)} applicable, {len(skipped)} skipped")
    for s in skipped:
        log.debug(f"  Skipped: {s}")
    return applicable


# ---------------------------------------------------------------------------
# Deterministic clause-level matching (unchanged from v2)
# ---------------------------------------------------------------------------

def _deterministic_match(clause: dict, sr: dict) -> dict:
    """
    Match a single clause's text against a single SR's pattern set.
    Returns match_type, match_confidence, extracted_evidence, match_reasoning.
    """
    text     = clause.get("text", "")
    compiled = sr["_compiled"]  # pre-compiled at module load
    total    = len(compiled)

    matched_snippets: list[str] = []
    for pat in compiled:
        m = pat.search(text)
        if m:
            start   = max(0, m.start() - 50)
            end     = min(len(text), m.end() + 100)
            snippet = text[start:end].replace("\n", " ").strip()
            matched_snippets.append(snippet)

    hit_count = len(matched_snippets)

    if hit_count == 0:
        return {
            "match_type":         "NO_MATCH",
            "match_confidence":   0.0,
            "extracted_evidence": "",
            "match_reasoning": (
                f"0/{total} patterns matched. "
                f"Clause does not address '{sr['title']}' "
                f"({sr['framework']} {sr['control_id']})."
            ),
        }

    hit_ratio = hit_count / total
    if hit_count >= 2:
        match_type  = "DIRECT_MATCH"
        confidence  = round(0.82 + min(hit_ratio * 0.13, 0.13), 2)
        reasoning   = (
            f"{hit_count}/{total} patterns matched. "
            f"Clause directly addresses '{sr['title']}' "
            f"({sr['framework']} {sr['control_id']}) with strong coverage."
        )
    else:
        match_type  = "PARTIAL_MATCH"
        confidence  = round(0.62 + hit_ratio * 0.16, 2)
        reasoning   = (
            f"{hit_count}/{total} patterns matched. "
            f"Clause partially addresses '{sr['title']}' "
            f"({sr['framework']} {sr['control_id']}) — "
            "insufficient specificity for full compliance."
        )

    seen: set[str] = set()
    unique_snippets: list[str] = []
    for s in matched_snippets:
        if s not in seen:
            seen.add(s)
            unique_snippets.append(s)
    extracted_evidence = " … ".join(unique_snippets)
    if len(extracted_evidence) > 500:
        extracted_evidence = extracted_evidence[:497] + "…"

    return {
        "match_type":         match_type,
        "match_confidence":   confidence,
        "extracted_evidence": extracted_evidence,
        "match_reasoning":    reasoning,
    }


# ---------------------------------------------------------------------------
# LLM refinement (new in v3)
# ---------------------------------------------------------------------------

def _llm_refine_match(
    clause:               dict,
    sr:                   dict,
    deterministic_result: dict,
    provider:             "BaseLLMProvider",
) -> Optional[dict]:
    """
    Call LLM to validate/refine a non-NO_MATCH deterministic result.
    Returns the LLM response dict, or None if the call failed.
    """
    user_msg = build_sr_matching_user_message(clause, sr, deterministic_result)

    try:
        response = provider.complete_structured(
            system_prompt  = SR_MATCHING_SYSTEM_PROMPT,
            user_message   = user_msg,
            json_schema    = SR_MATCHING_OUTPUT_SCHEMA,
            prompt_version = PROMPT_VERSION_SR_MATCHING,
            max_tokens     = 512,
        )
    except RuntimeError as exc:
        log.error(f"Unrecoverable LLM error for {clause['clause_id']}/{sr['id']}: {exc}")
        return None

    return response


def _merge_match(
    deterministic: dict,
    llm_response:  Optional["LLMResponse"],  # type: ignore[name-defined]
) -> tuple[dict, str]:
    """
    Merge deterministic and LLM match results.
    LLM result dominates when confidence >= 0.70.
    Returns (merged_result, source_label).
    """
    if llm_response is None:
        return deterministic, "rule_based"

    llm = llm_response.content
    llm_conf = llm.get("match_confidence", 0.0)

    if llm_conf >= 0.70:
        # LLM result takes precedence
        evidence = llm.get("extracted_evidence", [])
        if isinstance(evidence, list):
            evidence_str = " … ".join(evidence[:4])
        else:
            evidence_str = str(evidence)
        if len(evidence_str) > 500:
            evidence_str = evidence_str[:497] + "…"

        return {
            "match_type":         llm["match_type"],
            "match_confidence":   round(llm_conf, 3),
            "extracted_evidence": evidence_str,
            "match_reasoning":    llm["match_reasoning"],
        }, "llm"

    # LLM low confidence — blend: keep deterministic classification, use LLM evidence if richer
    log.debug(
        f"LLM match confidence {llm_conf:.2f} < 0.70 — "
        f"deterministic match_type takes precedence."
    )
    return deterministic, "hybrid"


# ---------------------------------------------------------------------------
# Retrieval evaluation helpers
# ---------------------------------------------------------------------------

def _compute_stage5_metrics(
    clause_eval_list: list[dict],
    contract_id:      str,
    run_config:       dict,
    output_path:      str,
) -> dict:
    """
    Aggregate per-clause evaluation data into run-level retrieval quality metrics.

    Answers the key question: is semantic retrieval improving recall or just noise?

    Parameters
    ----------
    clause_eval_list : collected during run() — one entry per clause
    contract_id      : from contract metadata, for artifact provenance
    run_config       : retrieval threshold config captured at run time
    output_path      : path of the primary Stage 5 output (for traceability)
    """
    total_clauses    = len(clause_eval_list)
    clauses_with_det = sum(1 for c in clause_eval_list if c["deterministic_candidate_count"] > 0)
    clauses_with_sem = sum(1 for c in clause_eval_list if c["semantic_candidate_count"] > 0)

    # Clauses where at least one semantic-only candidate entered the merged shortlist
    clauses_with_sem_only_uplift = sum(
        1 for c in clause_eval_list
        if any(
            not d["is_det_candidate"] and d["in_shortlist"]
            for d in c["semantic_candidate_details"]
        )
    )

    total_llm        = sum(c["llm_validated_candidate_count"] for c in clause_eval_list)

    sem_only_validated = 0    # sem-only candidates that went through LLM
    sem_only_promoted  = 0    # sem-only + LLM → DIRECT_MATCH or PARTIAL_MATCH
    sem_validated_scores: list[float] = []   # scores of all sem candidates LLM-validated
    sem_match_scores:     list[float] = []   # scores of sem candidates that ended as a match
    false_positives:      list[dict]  = []   # sem-only + LLM → NO_MATCH

    for c in clause_eval_list:
        clause_id = c["clause_id"]
        for d in c["semantic_candidate_details"]:
            if not d["llm_validated"]:
                continue
            sem_validated_scores.append(d["score"])
            if d["final_match_type"] in ("DIRECT_MATCH", "PARTIAL_MATCH"):
                sem_match_scores.append(d["score"])
            if not d["is_det_candidate"]:          # semantic-only
                sem_only_validated += 1
                if d["final_match_type"] in ("DIRECT_MATCH", "PARTIAL_MATCH"):
                    sem_only_promoted += 1
                elif d["final_match_type"] == "NO_MATCH":
                    false_positives.append({
                        "clause_id":      clause_id,
                        "sr_id":          d["sr_id"],
                        "semantic_score": d["score"],
                        "score_bucket":   _semantic_score_bucket(d["score"]),
                        "final_match_type": "NO_MATCH",
                    })

    def _avg(scores: list[float]) -> Optional[float]:
        return round(sum(scores) / len(scores), 4) if scores else None

    return {
        "run_config":    run_config,
        "contract_id":   contract_id,
        "output_path":   output_path,
        "total_clauses": total_clauses,
        "clauses_with_deterministic_candidates":  clauses_with_det,
        "clauses_with_semantic_candidates":       clauses_with_sem,
        "clauses_with_semantic_only_candidates":  clauses_with_sem_only_uplift,
        "total_llm_validations":                  total_llm,
        "semantic_only_candidates_validated":            sem_only_validated,
        "semantic_only_candidates_promoted_to_match":    sem_only_promoted,
        "average_semantic_score_of_validated_candidates": _avg(sem_validated_scores),
        "average_semantic_score_of_confirmed_matches":    _avg(sem_match_scores),
        "false_positive_semantic_candidates":             false_positives,
    }


def _write_stage5_eval_artifacts(
    metrics:            dict,
    shortlist_outcomes: list[dict],
    metrics_dir:        str,
) -> None:
    """
    Write run-level evaluation artifacts to *metrics_dir*.

    Files written
    -------------
    stage5_metrics.json          — aggregated retrieval quality metrics
    stage5_shortlist_outcomes.json — per-clause shortlist audit trail
    """
    p = Path(metrics_dir)
    p.mkdir(parents=True, exist_ok=True)

    metrics_path  = p / "stage5_metrics.json"
    outcomes_path = p / "stage5_shortlist_outcomes.json"

    with metrics_path.open("w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, ensure_ascii=False)
    with outcomes_path.open("w", encoding="utf-8") as fh:
        json.dump(shortlist_outcomes, fh, indent=2, ensure_ascii=False)

    log.info(f"Stage 5 eval artifacts → {metrics_dir}/")
    log.info(f"  stage5_metrics.json          ({len(metrics['false_positive_semantic_candidates'])} false-positive candidates)")
    log.info(f"  stage5_shortlist_outcomes.json ({len(shortlist_outcomes)} clause entries)")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    org_profile_path: str,
    metadata_path:    str,
    clauses_path:     str,
    output_path:      str,
    llm_provider:     Optional["BaseLLMProvider"] = None,
    metrics_dir:      Optional[str] = None,
    benchmark_path:   Optional[str] = None,
    eval_dir:         Optional[str] = None,
) -> list[dict]:
    """
    Run Stage 5 clause-to-SR matching.

    Matching pipeline per clause:
      1. Deterministic pass  — regex matching against all applicable SRs.
      2. Semantic retrieval  — TF-IDF top-k candidates from applicable SRs.
      3. Candidate merge     — union of det non-NO_MATCH + semantic top-k,
                               capped at STAGE5_MAX_CANDIDATES.
      4. LLM validation      — only on the merged shortlist (never all SRs).
      5. Output              — one record per (clause, SR) with full metadata.

    Parameters
    ----------
    org_profile_path: Path to org_profile.json
    metadata_path:    Path to contract_metadata.json
    clauses_path:     Path to stage4_clauses.json
    output_path:      Where to write clause_sr_matches.json
    llm_provider:     Pre-initialised LLM provider for match refinement.
                      If None, LLM refinement is skipped.
    metrics_dir:      Directory for retrieval evaluation artifacts
                      (stage5_metrics.json + stage5_shortlist_outcomes.json).
                      If None, artifacts are not written.
    benchmark_path:   Path to a golden-set benchmark JSON file.  Used only when
                      CONTRACT_EVAL_MODE=true (or the env var STAGE5_BENCHMARK_PATH
                      is set).  Missing file is a safe no-op.
    eval_dir:         Directory for benchmark evaluation artifacts
                      (benchmark_comparison_stage5.json, benchmark_metrics_stage5.json).
                      Defaults to {metrics_dir}/evaluation/ when metrics_dir is set.
                      If neither is set, eval artifacts are not written even in eval mode.
    """
    # 1. Load inputs
    org_profile = load_org_profile(org_profile_path)
    contract    = load_contract_metadata(metadata_path)
    clauses     = load_clauses(clauses_path)

    # 2. Resolve frameworks — ALWAYS from org_profile
    frameworks_to_check: list[str] = org_profile["regulatory_frameworks"]
    log.info(f"Frameworks to check (from org_profile): {frameworks_to_check}")

    # 3. Select applicable SRs
    applicable_srs = select_applicable_srs(
        catalog          = SR_CATALOG,
        frameworks_to_check = frameworks_to_check,
        contract_type    = contract["contract_type"],
        vendor_risk_tier = contract["vendor_risk_tier"],
    )

    # 3a. Load benchmark for evaluation mode (optional — never affects matching)
    _eval_benchmark = None
    _clause_comparisons: list[dict] = []
    if CONTRACT_EVAL_MODE:
        _bpath = benchmark_path or STAGE5_BENCHMARK_PATH
        if _bpath:
            try:
                from llm.evaluation import load_benchmark as _lb, BenchmarkIndex as _BI
                _raw = _lb(_bpath)
                if _raw is not None:
                    _eval_benchmark = _BI(_raw)
                    log.info(
                        f"Eval mode: benchmark loaded ({_bpath})  "
                        f"— {len(_eval_benchmark.clause_ids)} labeled clauses"
                    )
            except Exception as _bm_exc:
                log.warning(f"Eval mode: benchmark load failed: {_bm_exc}")
        else:
            log.info(
                "Eval mode enabled — no benchmark file specified; "
                "running without labels (comparison artifacts will record unlabeled clauses)"
            )

    # 4. Resolve LLM provider (caller-supplied; no auto-init here)
    provider = llm_provider
    if provider:
        log.info(
            f"LLM refinement enabled: {provider.provider_name}/{provider.model_name} "
            f"(applied to merged shortlist, max {STAGE5_MAX_CANDIDATES} candidates/clause)"
        )
    else:
        log.info("LLM refinement disabled — deterministic matching only.")

    if _SR_CORPUS:
        log.info(
            f"Semantic retrieval enabled: top_k={STAGE5_SEMANTIC_TOP_K} "
            f"min_score={STAGE5_MIN_SEMANTIC_SCORE}"
        )

    # 5. Match clauses against applicable SRs
    clause_sr_matches: list[dict] = []
    clause_eval_list:  list[dict] = []   # per-clause eval data (for metrics)
    llm_calls        = 0
    sem_uplift_total = 0  # clauses where semantic added at least 1 new candidate

    for clause in clauses:
        clause_id    = clause["clause_id"]
        text         = clause.get("text", "")
        text_preview = (text[:200] + "…") if len(text) > 200 else text

        # ── Pass 1: deterministic match on all applicable SRs ─────────────
        det_results: dict[str, dict] = {
            sr["id"]: _deterministic_match(clause, sr) for sr in applicable_srs
        }
        det_candidate_ids: set[str] = {
            sr_id for sr_id, det in det_results.items()
            if det["match_type"] != "NO_MATCH"
        }

        # ── Pass 2: semantic candidate retrieval ──────────────────────────
        semantic_map = _get_semantic_candidates(text, applicable_srs, clause_id)

        # ── Pass 3: merge into shortlist ──────────────────────────────────
        shortlist = _build_merged_shortlist(
            det_candidate_ids, semantic_map, STAGE5_MAX_CANDIDATES
        )
        sem_added = shortlist - det_candidate_ids
        if sem_added:
            sem_uplift_total += 1
            log.debug(
                f"  {clause_id}: semantic added {len(sem_added)} candidate(s) "
                f"to shortlist → {sorted(sem_added)}"
            )

        # ── Eval mode: capture deterministic state before LLM pass ───────
        _eval_det_types:   dict[str, str] = {}
        _eval_final_types: dict[str, str] = {}
        if CONTRACT_EVAL_MODE:
            _eval_det_types = {sid: d["match_type"] for sid, d in det_results.items()}

        # ── Clause-level evaluation data (built before inner loop) ────────
        _sem_details: list[dict] = [
            {
                "sr_id":           r["sr_id"],
                "score":           r["score"],
                "rank":            r["rank"],
                "in_shortlist":    r["sr_id"] in shortlist,
                "is_det_candidate": r["sr_id"] in det_candidate_ids,
                "final_match_type": None,    # filled in inner loop
                "llm_validated":    False,   # filled in inner loop
            }
            for r in sorted(semantic_map.values(), key=lambda x: x["rank"])
        ]
        clause_eval: dict = {
            "clause_id":                     clause_id,
            "deterministic_candidate_count": len(det_candidate_ids),
            "semantic_candidate_count":      len(semantic_map),
            "merged_candidate_count":        len(shortlist),
            "llm_validated_candidate_count": 0,
            "shortlist_outcome": {
                "clause_id":                        clause_id,
                "deterministic_candidates":         sorted(det_candidate_ids),
                "semantic_candidates":              sorted(semantic_map.keys()),
                "merged_shortlist":                 sorted(shortlist),
                "semantic_candidates_excluded_by_cap": sorted(
                    sr_id for sr_id in semantic_map if sr_id not in shortlist
                ),
            },
            "semantic_candidate_details": _sem_details,
        }
        # O(1) lookup for inner-loop updates
        _sem_detail_idx: dict[str, dict] = {d["sr_id"]: d for d in _sem_details}

        # ── Pass 4: produce one record per (clause, SR) ───────────────────
        for sr in applicable_srs:
            sr_id      = sr["id"]
            det_result = det_results[sr_id]
            sem_entry  = semantic_map.get(sr_id)

            cand_meta = _make_candidate_metadata(
                is_det    = sr_id in det_candidate_ids,
                is_sem    = sem_entry is not None,
                sem_score = sem_entry["score"] if sem_entry else None,
            )

            # LLM validation: only for shortlist members
            llm_content_raw: Optional[dict] = None
            if provider and sr_id in shortlist and LLM_MODULE_AVAILABLE:
                log.debug(
                    f"  LLM refining {clause_id} × {sr_id} "
                    f"(src={cand_meta['candidate_source']}) …"
                )
                llm_response = _llm_refine_match(clause, sr, det_result, provider)
                merged, source = _merge_match(det_result, llm_response)
                llm_calls += 1
                clause_eval["llm_validated_candidate_count"] += 1
                if sr_id in _sem_detail_idx:
                    _sem_detail_idx[sr_id]["llm_validated"] = True

                if llm_response is not None:
                    ai_meta = llm_response.metadata.to_dict()
                    llm_content_raw = llm_response.content
                else:
                    ai_meta = DETERMINISTIC_AI_META
            else:
                merged = det_result
                source = "rule_based"
                ai_meta = DETERMINISTIC_AI_META

            # ── Explainability fields ──────────────────────────────────────
            ai_attempted = (source != "rule_based")
            ai_conf      = ai_meta.get("confidence") if ai_attempted else None
            conf_bkt     = confidence_bucket(ai_conf)
            baseline     = {
                "match_type":       det_result["match_type"],
                "match_confidence": det_result["match_confidence"],
            } if ai_attempted else None
            delta        = decision_delta_match(
                det_result["match_type"], merged["match_type"], ai_attempted
            )
            priority     = review_priority_match(merged["match_type"], conf_bkt, delta)
            trace        = build_sr_match_trace(
                det_result["match_type"], llm_content_raw, source
            )

            clause_sr_matches.append({
                "clause_id":           clause_id,
                "clause_text_preview": text_preview,
                "framework":           sr["framework"],
                "control_id":          sr["control_id"],
                "sr_id":               sr_id,
                "sr_title":            sr["title"],
                "match_type":          merged["match_type"],
                "match_confidence":    merged["match_confidence"],
                "extracted_evidence":  merged["extracted_evidence"],
                "match_reasoning":     merged["match_reasoning"],
                "_match_source":       source,
                "_ai_metadata":        ai_meta,
                "_baseline_result":    baseline,
                "_decision_delta":     delta,
                "_confidence_bucket":  conf_bkt,
                "_review_priority":    priority,
                "_ai_trace":           trace,
                "_candidate_metadata": cand_meta,
            })

            # Record final outcome for semantic eval data and benchmark evaluation
            if sr_id in _sem_detail_idx:
                _sem_detail_idx[sr_id]["final_match_type"] = merged["match_type"]
            if CONTRACT_EVAL_MODE:
                _eval_final_types[sr_id] = merged["match_type"]

        # End of inner SR loop — commit clause eval entry
        clause_eval_list.append(clause_eval)

        # ── Eval mode: build per-clause benchmark comparison ──────────────
        if CONTRACT_EVAL_MODE:
            _expected = (
                _eval_benchmark.get_expected(clause_id) if _eval_benchmark else []
            )
            try:
                from llm.evaluation import compute_clause_comparison as _ccc
                _clause_comparisons.append(
                    _ccc(clause_id, _expected,
                         _eval_det_types, shortlist, _eval_final_types)
                )
            except Exception as _ccc_exc:
                log.warning(f"Clause comparison failed for {clause_id}: {_ccc_exc}")

    # 6. Write output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(clause_sr_matches, f, indent=2, ensure_ascii=False)
    log.info(f"Stage 5 output written to: {output_path}")
    log.info(
        f"  {len(clauses)} clauses × {len(applicable_srs)} SRs "
        f"= {len(clause_sr_matches)} match records"
    )
    if llm_calls:
        log.info(
            f"  LLM validation calls: {llm_calls} "
            f"(shortlist-only; max {STAGE5_MAX_CANDIDATES} per clause)"
        )
    if _SR_CORPUS and sem_uplift_total:
        log.info(
            f"  Semantic uplift: {sem_uplift_total}/{len(clauses)} clauses "
            "gained additional candidates from semantic retrieval"
        )

    # 7. Compute and write retrieval evaluation artifacts (if requested)
    _run_config = {
        "semantic_enabled":   STAGE5_SEMANTIC_ENABLED,
        "max_candidates":     STAGE5_MAX_CANDIDATES,
        "semantic_top_k":     STAGE5_SEMANTIC_TOP_K,
        "min_semantic_score": STAGE5_MIN_SEMANTIC_SCORE,
    }
    if metrics_dir is not None:
        metrics = _compute_stage5_metrics(
            clause_eval_list = clause_eval_list,
            contract_id      = contract.get("contract_id", "unknown"),
            run_config       = _run_config,
            output_path      = output_path,
        )
        shortlist_outcomes = [c["shortlist_outcome"] for c in clause_eval_list]
        _write_stage5_eval_artifacts(metrics, shortlist_outcomes, metrics_dir)

    # 8. Compute and write benchmark evaluation artifacts (eval mode only)
    if CONTRACT_EVAL_MODE and _clause_comparisons:
        _contract_id = contract.get("contract_id", "unknown")
        _ts          = datetime.datetime.now(tz=datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        _eval_run_meta = {
            "run_id":                  f"{_contract_id}_{_ts.replace(':', '').replace('-', '')}",
            "contract_id":             _contract_id,
            "timestamp":               _ts,
            "llm_enabled":             provider is not None,
            "llm_provider":            provider.provider_name if provider else None,
            "llm_model":               provider.model_name    if provider else None,
            "retrieval_config":        _run_config,
            "benchmark_contract_id":   (
                _eval_benchmark.contract_id if _eval_benchmark else None
            ),
            "benchmark_labeled_clauses": (
                len(_eval_benchmark.clause_ids) if _eval_benchmark else 0
            ),
        }
        try:
            from llm.evaluation import (
                compute_benchmark_metrics as _cbm,
                write_eval_artifacts      as _wea,
            )
            _eval_metrics = _cbm(_clause_comparisons, _eval_run_meta)
            # Resolve eval_dir: explicit > {metrics_dir}/evaluation > skip
            _edir = (
                eval_dir
                or (os.path.join(metrics_dir, "evaluation") if metrics_dir else None)
            )
            if _edir:
                _wea(_clause_comparisons, _eval_metrics, _edir)
            else:
                log.warning(
                    "Eval mode: benchmark comparison computed but no eval_dir set; "
                    "pass eval_dir or metrics_dir to persist artifacts."
                )
        except Exception as _eval_exc:
            log.warning(f"Eval mode: benchmark metrics failed: {_eval_exc}")

    return clause_sr_matches


def _print_summary(clause_sr_matches: list[dict], clauses_count: int, srs_count: int) -> None:
    direct   = sum(1 for r in clause_sr_matches if r["match_type"] == "DIRECT_MATCH")
    partial  = sum(1 for r in clause_sr_matches if r["match_type"] == "PARTIAL_MATCH")
    no_match = sum(1 for r in clause_sr_matches if r["match_type"] == "NO_MATCH")
    llm_used = sum(1 for r in clause_sr_matches
                   if r.get("_ai_metadata", {}).get("llm_used", False))

    # Candidate source breakdown
    cand_sources: dict[str, int] = {}
    for r in clause_sr_matches:
        src = r.get("_candidate_metadata", {}).get("candidate_source", "unknown")
        cand_sources[src] = cand_sources.get(src, 0) + 1

    sr_best: dict[str, str] = {}
    for r in clause_sr_matches:
        sr_id   = r["sr_id"]
        mt      = r["match_type"]
        current = sr_best.get(sr_id, "NO_MATCH")
        if mt == "DIRECT_MATCH" or (mt == "PARTIAL_MATCH" and current == "NO_MATCH"):
            sr_best[sr_id] = mt

    print(f"\n{'='*70}")
    print(f"  Requirement Matching Engine — Stage 5  (semantic + deterministic + LLM)")
    print(f"{'='*70}")
    print(f"  Clauses evaluated  : {clauses_count}")
    print(f"  SRs evaluated      : {srs_count}")
    print(f"  Total match records: {len(clause_sr_matches)}")
    print(f"  LLM-validated      : {llm_used}")
    print(f"  Semantic corpus    : {'enabled' if _SR_CORPUS else 'disabled'}")
    if cand_sources:
        print(f"  Candidate sources  : "
              + "  ".join(f"{k}={v}" for k, v in sorted(cand_sources.items())))
    print(f"{'='*70}")
    print(f"  Clause-level counts:")
    print(f"    DIRECT_MATCH   : {direct}")
    print(f"    PARTIAL_MATCH  : {partial}")
    print(f"    NO_MATCH       : {no_match}")
    print(f"{'='*70}")
    print(f"  SR-level aggregated view (best match per SR across all clauses):")
    print(f"  {'SR-ID':<20} {'FW':<10} {'Best Match'}")
    print(f"  {'-'*50}")
    for sr_id, best in sorted(sr_best.items()):
        sr_entry = SR_CATALOG_BY_ID.get(sr_id, {})
        fw   = sr_entry.get("framework", "?")
        icon = "✓" if best == "DIRECT_MATCH" else "~" if best == "PARTIAL_MATCH" else "✗"
        print(f"  {sr_id:<20} {fw:<10} {icon} {best}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 5 — Requirement Matching Engine (clause-level + LLM)"
    )
    parser.add_argument("--org-profile",  default="org_profile.json")
    parser.add_argument("--metadata",     default="contract_metadata.json")
    parser.add_argument("--clauses",      default="stage4_clauses.json")
    parser.add_argument("--output",       default="clause_sr_matches.json")
    parser.add_argument("--no-llm",       action="store_true", help="Deterministic only")
    parser.add_argument(
        "--metrics-dir",
        default=None,
        metavar="DIR",
        help=(
            "Write retrieval evaluation artifacts to DIR "
            "(stage5_metrics.json, stage5_shortlist_outcomes.json). "
            "Example: analysis_runs/CT-2026-001"
        ),
    )
    parser.add_argument(
        "--benchmark",
        default=None,
        metavar="FILE",
        help=(
            "Golden-set benchmark JSON for evaluation mode (CONTRACT_EVAL_MODE=true). "
            "Expected format: {contract_id, clauses: [{clause_id, expected_matches: "
            "[{sr_id, expected_match_type}]}]}. "
            "Overrides the STAGE5_BENCHMARK_PATH env var."
        ),
    )
    parser.add_argument(
        "--eval-dir",
        default=None,
        metavar="DIR",
        help=(
            "Directory for benchmark evaluation artifacts "
            "(benchmark_comparison_stage5.json, benchmark_metrics_stage5.json). "
            "Defaults to {metrics-dir}/evaluation when --metrics-dir is set."
        ),
    )
    args = parser.parse_args()

    provider = None
    if not args.no_llm and LLM_MODULE_AVAILABLE:
        try:
            from llm.config import get_llm_provider
            provider = get_llm_provider()
        except Exception:
            pass

    matches = run(
        org_profile_path = args.org_profile,
        metadata_path    = args.metadata,
        clauses_path     = args.clauses,
        output_path      = args.output,
        llm_provider     = provider,
        metrics_dir      = args.metrics_dir,
        benchmark_path   = args.benchmark,
        eval_dir         = args.eval_dir,
    )
    # Derive clause count from matches (all clauses appear, even as NO_MATCH)
    clause_count = len({r["clause_id"] for r in matches})
    _print_summary(matches, clause_count, len(set(r["sr_id"] for r in matches)))


if __name__ == "__main__":
    main()
