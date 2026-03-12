#!/usr/bin/env python3
"""
Stage 4.5 — Obligation Analysis Engine

Analyses extracted contract clauses from the perspective of an IT SERVICE PROVIDER
reviewing obligations imposed ON THEM by customer contracts.

Runs after clause extraction (Stage 4) and before regulatory matching (Stage 5).

Two-pass architecture:
  1. Rule-based classifier  — zero dependencies, always runs
  2. LLM refinement         — optional, uses LLM provider abstraction
                              supports Anthropic (claude-opus-4-6) and OpenAI (gpt-4o)
                              system prompt cached across all clause calls

Assessment categories:
  VALID                     Clear, specific obligation that can be fulfilled
  AMBIGUOUS_REQUIREMENT     Vague obligations without measurable criteria
  NON_TRANSFERABLE_REGULATION  Customer attempts to shift their own regulatory duties
  OPERATIONAL_RISK          Unrealistic deadlines, unlimited scope, impossible obligations
  SCOPE_UNDEFINED           References to laws/standards without naming them
  CUSTOMER_RESPONSIBILITY   Obligations that normally belong to the customer

Usage:
    python stage4_5_obligation_analysis.py stage4_clauses.json [options]

Options:
    --output   <path>   Output file (default: stage4_5_obligation_analysis.json)
    --no-llm            Skip LLM pass (rule-based only)
    --include-valid     Include VALID clauses in output (default: omitted)
"""

import json
import re
import os
import sys
import argparse
import logging
from typing import Optional

# Bootstrap project root so 'llm.*' is importable regardless of CWD
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("stage4_5")

# ---------------------------------------------------------------------------
# LLM module imports (graceful degradation if not available)
# ---------------------------------------------------------------------------

try:
    from llm.base import BaseLLMProvider, LLMAuditMetadata, DETERMINISTIC_AI_META
    from llm.prompts import (
        OBLIGATION_SYSTEM_PROMPT,
        OBLIGATION_OUTPUT_SCHEMA,
        PROMPT_VERSION_OBLIGATION,
        build_obligation_user_message,
    )
    from llm.tracing import (
        confidence_bucket,
        decision_delta_assessment,
        review_priority_obligation,
        build_obligation_trace,
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

    def decision_delta_assessment(ba, bs, fa, fs, ai):  # type: ignore[misc]
        if not ai: return None
        if ba == fa and bs == fs: return "no_change"
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        if order.get(fs, 0) > order.get(bs, 0): return "ai_upgrade"
        if order.get(fs, 0) < order.get(bs, 0): return "ai_downgrade"
        return "ai_override"

    def review_priority_obligation(assessment, severity, conf_bkt):  # type: ignore[misc]
        if (conf_bkt == "low" or severity == "HIGH"
                or assessment in ("NON_TRANSFERABLE_REGULATION", "OPERATIONAL_RISK")):
            return "HIGH"
        if conf_bkt == "medium" or assessment in ("AMBIGUOUS_REQUIREMENT", "SCOPE_UNDEFINED"):
            return "MEDIUM"
        return "LOW"

    def build_obligation_trace(llm_content, source):  # type: ignore[misc]
        return None

# ---------------------------------------------------------------------------
# Assessment model
# ---------------------------------------------------------------------------

ASSESSMENTS = [
    "VALID",
    "AMBIGUOUS_REQUIREMENT",
    "NON_TRANSFERABLE_REGULATION",
    "OPERATIONAL_RISK",
    "SCOPE_UNDEFINED",
    "CUSTOMER_RESPONSIBILITY",
]

# Default severity per assessment type
ASSESSMENT_SEVERITY: dict[str, str] = {
    "NON_TRANSFERABLE_REGULATION": "HIGH",
    "OPERATIONAL_RISK":            "HIGH",
    "CUSTOMER_RESPONSIBILITY":     "MEDIUM",
    "SCOPE_UNDEFINED":             "MEDIUM",
    "AMBIGUOUS_REQUIREMENT":       "MEDIUM",
    "VALID":                       "LOW",
}

# Boilerplate recommended action per type (rule-based fallback — German)
ASSESSMENT_ACTIONS: dict[str, str] = {
    "NON_TRANSFERABLE_REGULATION": (
        "Klausel ablehnen oder neu verhandeln. Der Auftraggeber kann eigene Regulierungspflichten "
        "nicht vertraglich auf den Dienstleister übertragen. Vor Annahme die Rechtsabteilung "
        "einschalten."
    ),
    "OPERATIONAL_RISK": (
        "Realistische, messbare Verpflichtungen aushandeln. Unrealistische Fristen, unbegrenzte "
        "Zugriffsrechte oder undefinierte Frequenzanforderungen durch spezifische, operativ "
        "umsetzbare Verpflichtungen mit klaren Obergrenzen ersetzen."
    ),
    "CUSTOMER_RESPONSIBILITY": (
        "Diese Verpflichtung als fehlerhaft zugewiesen ablehnen. Datenklassifizierung, "
        "DSFA-Durchführung und Bestimmung der Rechtsgrundlage sind Controller-Pflichten nach DSGVO. "
        "Streichung aus dem Pflichtenset des Anbieters beantragen."
    ),
    "SCOPE_UNDEFINED": (
        "Den Auftraggeber auffordern, alle referenzierten Gesetze, Standards und Rahmenwerke "
        "namentlich zu benennen. Allgemeine Begriffe wie 'anwendbares Recht' oder 'einschlägige "
        "Standards' durch abschließende, spezifische Aufzählungen ersetzen."
    ),
    "AMBIGUOUS_REQUIREMENT": (
        "Konkrete, messbare Kriterien anfordern. Vage Begriffe wie 'Best Efforts', "
        "'angemessene Maßnahmen' oder 'Stand der Technik' durch definierte Metriken, "
        "benannte Standards oder objektiv prüfbare Kriterien ersetzen."
    ),
    "VALID": "Kein Handlungsbedarf. Klausel ist klar und operativ umsetzbar.",
}

# ---------------------------------------------------------------------------
# Rule-based detection patterns
# Priority order: first matching category wins.
# ---------------------------------------------------------------------------

RULE_PATTERNS: list[tuple[str, list[re.Pattern], Optional[str]]] = []

# Pre-compiled at module load — used inside _rule_classify() for the
# OPERATIONAL_RISK severity sub-check.
_UNLIMITED_PAT = re.compile(
    r"unlimited|unrestricted|at\s+any\s+time\s+without|source\s+code\s+repositor",
    re.IGNORECASE,
)


def _compile(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE | re.DOTALL) for p in patterns]


# 1 — NON_TRANSFERABLE_REGULATION
RULE_PATTERNS.append((
    "NON_TRANSFERABLE_REGULATION",
    _compile([
        r"provider\s+shall\s+(?:assume|take\s+over|fulfil|submit|file|report\s+to)\s+"
        r"(?:all\s+)?(?:the\s+customer[''']?s?\s+)?(?:ict.related\s+)?regulatory",
        r"provider\s+shall\s+(?:comply\s+with|adhere\s+to|observe)\s+"
        r"(?:its\s+obligations\s+(?:as|under)\s+)?(?:an?\s+)?essential\s+entity\s+under\s+(?:the\s+)?nis2",
        r"provider\s+shall\s+submit\s+(?:major\s+)?incident\s+reports\s+(?:directly\s+)?to\s+"
        r"(?:the\s+)?(?:competent\s+(?:national\s+)?authority|bafin|eba|bsi)",
        r"provider\s+shall\s+assume\s+all\s+ict.related\s+regulatory",
        r"provider\s+shall\s+(?:manage|handle|address)\s+(?:the\s+customer[''']?s?\s+)?"
        r"concentration\s+risk\s+exposure",
        r"provider\s+shall\s+represent\s+the\s+customer\s+in\s+(?:all\s+)?supervisory",
        r"(?:mifid|crd\s*iv?|crr\b|emir|solvency\s+ii)\s+(?:obligation|requirement|report)",
        r"provider\s+shall\s+(?:file|submit|make)\s+(?:regulatory|supervisory)\s+(?:report|filing|return)",
        r"notification\s+to\s+(?:the\s+)?(?:bafin|eba|bsi|esma|supervisory\s+authorit)",
    ]),
    "HIGH",
))

# 2 — CUSTOMER_RESPONSIBILITY
RULE_PATTERNS.append((
    "CUSTOMER_RESPONSIBILITY",
    _compile([
        r"provider\s+shall\s+(?:determine|decide|classify|assess)\s+"
        r"(?:the\s+)?(?:sensitivity\s+)?classification\s+of\s+(?:all\s+)?(?:customer\s+)?data",
        r"provider\s+shall\s+decide\s+which\s+data\s+qualif(?:ies|y)\s+as\s+personal\s+data",
        r"provider\s+shall\s+define\s+(?:the\s+)?(?:appropriate\s+)?(?:customer[''']?s?\s+)?"
        r"(?:data\s+)?retention\s+polic(?:y|ies)",
        r"provider\s+shall\s+perform\s+(?:the\s+)?(?:customer[''']?s?\s+)?(?:data\s+protection\s+)?"
        r"impact\s+assessment",
        r"provider\s+shall\s+determine\s+(?:the\s+)?legal\s+basis\s+for\s+(?:the\s+)?processing",
        r"provider\s+shall\s+identify\s+(?:the\s+)?(?:applicable\s+)?data\s+subjects",
    ]),
    "MEDIUM",
))

# 3 — OPERATIONAL_RISK
RULE_PATTERNS.append((
    "OPERATIONAL_RISK",
    _compile([
        r"within\s+(?:1[0-9]?|2[0-9]?)\s*minutes?\s+of\s+(?:detection|discovery|becoming\s+aware)",
        r"within\s+(?:fifteen|ten|five|one)\s+minutes?\s+of",
        r"immediately\s+notif(?:y|ication)(?:\s+all)?(?:\s+affected)?\s+parties",
        r"notify\s+(?:all\s+)?(?:affected\s+)?parties\s+immediately",
        r"real.?time\s+(?:security\s+)?(?:event\s+)?(?:log\s+)?(?:feed|stream|access|notif)",
        r"within\s+30\s+seconds?\s+of\s+(?:event|generation|detection)",
        r"unlimited[,\s]+unrestricted\s+audit\s+access",
        r"audit\s+access\s+to\s+all\s+provider\s+systems",
        r"at\s+any\s+time\s+(?:and\s+)?without\s+(?:prior\s+)?notice",
        r"without\s+(?:prior\s+)?notice\s+(?:or\s+)?(?:at\s+any\s+time)",
        r"unrestricted\s+access\s+to\s+all",
        r"access\s+to\s+(?:all\s+)?(?:provider\s+)?source\s+code\s+repositor",
        r"(?:determined|specified|defined)\s+solely\s+by\s+the\s+customer",
        r"as\s+(?:the\s+)?customer\s+may\s+(?:specify|require|determine)\s+from\s+time\s+to\s+time",
        r"report\s+(?:regularly|periodically)\s+(?:as\s+(?:required|determined)\s+by\s+the\s+customer)",
    ]),
    None,
))

# 4 — SCOPE_UNDEFINED
RULE_PATTERNS.append((
    "SCOPE_UNDEFINED",
    _compile([
        r"applicable\s+(?:data\s+protection\s+)?law[s]?"
        r"(?!\s*(?:of|,\s*(?:namely|including|such\s+as|i\.e\.|e\.g\.)|\s*\((?:eu|gdpr|dsgvo)))",
        r"(?:relevant|applicable)\s+(?:security\s+)?(?:standards?|frameworks?|requirements?)"
        r"(?!\s*(?:,\s*(?:including|such\s+as|namely)|:\s*|\s+(?:iso|nist|soc|dora|nis2|gdpr)))",
        r"applicable\s+requirements?\s+as\s+(?:determined|specified)\s+by\s+the\s+relevant\s+supervisory",
        r"regulatory\s+requirements?\s+(?:that\s+may\s+apply|applicable\s+to\s+the\s+customer[''']?s?\s+business\s+sector)",
        r"shall\s+periodically\s+review\s+and\s+update\s+its\s+practices\s+accordingly\s*\.?\s*$",
    ]),
    "MEDIUM",
))

# 5 — AMBIGUOUS_REQUIREMENT
RULE_PATTERNS.append((
    "AMBIGUOUS_REQUIREMENT",
    _compile([
        r"\ball\s+(?:applicable\s+)?(?:legal\s+)?requirements?\b",
        r"\ball\s+relevant\s+regulations?\b",
        r"\bindustry\s+best\s+practices?\b",
        r"\bbest\s+efforts?\b",
        r"\bstate[\s-]of[\s-]the[\s-]art\b",
        r"\bcommonly\s+accepted\s+(?:information\s+security\s+)?standards?\b",
        r"\bappropriate\s+(?:technical\s+and\s+organizational\s+)?measures?\b"
        r"(?!\s+(?:pursuant|in\s+accordance|as\s+required|under\s+(?:gdpr|article|art\.)))",
        r"\breasonable\s+(?:security\s+)?(?:measures?|efforts?)\b",
        r"\bany\s+reasonable\s+(?:security\s+)?requirements?\s+the\s+customer\s+may\s+specify",
        r"\bas\s+they\s+evolve\s+over\s+time\b",
        r"\bcurrent\s+and\s+future\s+regulatory\s+requirements\b",
    ]),
    "MEDIUM",
))

# ---------------------------------------------------------------------------
# Rule-based classifier
# ---------------------------------------------------------------------------

def _rule_classify(text: str) -> dict:
    """
    Return the first matching assessment, its severity, and a short rule label.
    Falls back to VALID if no pattern matches.
    """
    for assessment, patterns, sev_override in RULE_PATTERNS:
        for pat in patterns:
            if pat.search(text):
                severity = sev_override or ASSESSMENT_SEVERITY[assessment]
                if assessment == "OPERATIONAL_RISK":
                    severity = "HIGH" if _UNLIMITED_PAT.search(text) else "MEDIUM"
                return {
                    "assessment":          assessment,
                    "severity":            severity,
                    "reason":              f"[RULE] Pattern match: '{pat.pattern[:80]}'",
                    "recommended_action":  ASSESSMENT_ACTIONS[assessment],
                    "evidence_phrases":    [],
                    "confidence":          0.70,
                }
    return {
        "assessment":          "VALID",
        "severity":            "LOW",
        "reason":              "[RULE] No obligation risk patterns detected.",
        "recommended_action":  ASSESSMENT_ACTIONS["VALID"],
        "evidence_phrases":    [],
        "confidence":          0.75,
    }


# ---------------------------------------------------------------------------
# LLM classifier
# ---------------------------------------------------------------------------

LLM_CONFIDENCE_THRESHOLD     = 0.75   # LLM overrides rule when confidence >= this
AI_NEW_DETECTION_THRESHOLD   = 0.60   # AI may create NEW finding on VALID clause >= this


def _llm_classify_batch(
    clauses:  list[dict],
    provider: "BaseLLMProvider",
) -> list[Optional[dict]]:
    """
    Classify clauses via LLM provider, one call per clause.
    Returns a list aligned with input; None entries mean the call failed.
    """
    if not LLM_MODULE_AVAILABLE:
        log.warning("llm module not available — skipping LLM pass.")
        return [None] * len(clauses)

    results: list[Optional[dict]] = []

    for i, clause in enumerate(clauses):
        clause_id = clause["clause_id"]
        log.info(f"  LLM [{i+1}/{len(clauses)}] classifying {clause_id}…")

        user_msg = build_obligation_user_message(clause, OBLIGATION_OUTPUT_SCHEMA)

        try:
            response = provider.complete_structured(
                system_prompt  = OBLIGATION_SYSTEM_PROMPT,
                user_message   = user_msg,
                json_schema    = OBLIGATION_OUTPUT_SCHEMA,
                prompt_version = PROMPT_VERSION_OBLIGATION,
                max_tokens     = 512,
            )
        except RuntimeError as exc:
            log.error(f"Unrecoverable LLM error — aborting LLM pass: {exc}")
            return [None] * len(clauses)

        if response is None:
            log.warning(f"    {clause_id}: LLM call failed after retries — using rule-based.")
            results.append(None)
            continue

        result = response.content
        log.info(
            f"    {clause_id}: {result.get('assessment')} "
            f"[{result.get('severity')}] conf={result.get('confidence', 0):.2f}"
        )
        results.append(result)

    return results


def _merge(rule: dict, llm: Optional[dict]) -> tuple[dict, str]:
    """
    Merge rule-based and LLM results into a single classification.

    Priority rules:
    1. LLM confidence >= LLM_CONFIDENCE_THRESHOLD (0.75)  → LLM overrides rule.
    2. Rule said VALID + LLM says non-VALID + LLM confidence >= AI_NEW_DETECTION_THRESHOLD (0.60)
       → AI new detection: the LLM identified a risk the rules missed.
       This is the key mechanism for expanding AI coverage beyond rule-flagged clauses.
    3. Otherwise → rule-based result.

    Returns (merged_result, source_label).
    source_label: "llm" | "ai_new_detection" | "rule_based"
    """
    llm_conf = llm.get("confidence", 0.0) if llm else 0.0

    # Case 1: high-confidence LLM override (agrees or refines rule result)
    if llm and llm_conf >= LLM_CONFIDENCE_THRESHOLD:
        return {
            "assessment":         llm["assessment"],
            "severity":           llm["severity"],
            "reason":             llm["reason"],
            "recommended_action": llm["recommended_action"],
            "evidence_phrases":   llm.get("evidence_phrases", []),
            "confidence":         round(llm_conf, 3),
        }, "llm"

    # Case 2: AI detects a NEW issue in a clause the rules cleared as VALID
    if (llm is not None
            and rule["assessment"] == "VALID"
            and llm.get("assessment", "VALID") != "VALID"
            and llm_conf >= AI_NEW_DETECTION_THRESHOLD):
        log.info(
            f"  AI new detection: {llm['assessment']} [{llm.get('severity')}] "
            f"conf={llm_conf:.2f} on rule-VALID clause"
        )
        return {
            "assessment":         llm["assessment"],
            "severity":           llm["severity"],
            "reason":             llm["reason"],
            "recommended_action": llm["recommended_action"],
            "evidence_phrases":   llm.get("evidence_phrases", []),
            "confidence":         round(llm_conf, 3),
        }, "ai_new_detection"

    # Fallback: sub-threshold LLM result — rule wins
    if llm and llm_conf > 0:
        log.debug(
            f"LLM confidence {llm_conf:.2f} < {LLM_CONFIDENCE_THRESHOLD} "
            f"— rule-based takes precedence."
        )
    return {
        "assessment":         rule["assessment"],
        "severity":           rule["severity"],
        "reason":             rule["reason"].replace("[RULE] ", ""),
        "recommended_action": rule["recommended_action"],
        "evidence_phrases":   rule.get("evidence_phrases", []),
        "confidence":         rule["confidence"],
    }, "rule_based"


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_clauses(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "clauses" in data:
        return data["clauses"]
    raise ValueError("Input must be a JSON array of clause objects or {clauses: [...]}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    input_path:    str,
    output_path:   str,
    include_valid: bool,
    skip_llm:      bool = False,
    llm_provider:  Optional["BaseLLMProvider"] = None,
) -> list[dict]:
    """
    Run Stage 4.5 obligation analysis.

    Parameters
    ----------
    input_path:    Path to stage4_clauses.json
    output_path:   Where to write stage4_5_obligation_analysis.json
    include_valid: Whether to include VALID clauses in output
    skip_llm:      If True, skip LLM pass entirely (rule-based only)
    llm_provider:  Pre-initialised LLM provider (from llm.config.get_llm_provider).
                   If None and skip_llm is False, attempts to auto-init from env.
    """
    log.info(f"Loading clauses from: {input_path}")
    clauses = _load_clauses(input_path)
    log.info(f"Loaded {len(clauses)} clauses")

    # ── Pass 1: rule-based ────────────────────────────────────────────────
    log.info("Pass 1: rule-based classification…")
    rule_results = [_rule_classify(c["text"]) for c in clauses]

    # ── Pass 2: LLM ──────────────────────────────────────────────────────
    llm_results: list[Optional[dict]] = [None] * len(clauses)
    provider = None

    if not skip_llm:
        if llm_provider is not None:
            provider = llm_provider
        elif LLM_MODULE_AVAILABLE:
            # Auto-init from environment when called standalone (CLI)
            try:
                from llm.config import get_llm_provider
                provider = get_llm_provider()
            except Exception as exc:
                log.warning(f"Could not auto-init LLM provider: {exc}")

        if provider is not None:
            log.info(
                f"Pass 2: LLM classification via {provider.provider_name}/{provider.model_name} "
                f"(system prompt cached after first call)…"
            )
            llm_results = _llm_classify_batch(clauses, provider)
        else:
            log.info("Pass 2: LLM skipped (no provider available).")
    else:
        log.info("Pass 2: LLM skipped (--no-llm).")

    # ── Merge & build output ──────────────────────────────────────────────
    output: list[dict] = []
    stats: dict[str, int] = {}

    for clause, rule_r, llm_r in zip(clauses, rule_results, llm_results):
        merged, source = _merge(rule_r, llm_r)
        stats[merged["assessment"]] = stats.get(merged["assessment"], 0) + 1

        if not include_valid and merged["assessment"] == "VALID":
            continue

        # Build _ai_metadata
        if source in ("llm", "ai_new_detection") and provider is not None:
            ai_meta = {
                "llm_used":       True,
                "provider":       provider.provider_name,
                "model":          provider.model_name,
                "prompt_version": PROMPT_VERSION_OBLIGATION if LLM_MODULE_AVAILABLE else None,
                "confidence":     merged["confidence"],
                "detection_type": "new_detection" if source == "ai_new_detection" else "refinement",
            }
        else:
            ai_meta = DETERMINISTIC_AI_META

        # ── Explainability fields ──────────────────────────────────────────
        ai_attempted = source in ("llm", "ai_new_detection")
        conf_bkt     = confidence_bucket(merged["confidence"]) if ai_attempted else None
        baseline     = {
            "assessment": rule_r["assessment"],
            "severity":   rule_r["severity"],
            "confidence": rule_r["confidence"],
        } if ai_attempted else None
        delta        = decision_delta_assessment(
            rule_r["assessment"], rule_r["severity"],
            merged["assessment"], merged["severity"],
            ai_attempted,
        )
        priority     = review_priority_obligation(
            merged["assessment"], merged["severity"], conf_bkt
        )
        trace        = build_obligation_trace(llm_r, source)

        output.append({
            "clause_id":          clause["clause_id"],
            "page":               clause.get("page"),
            "layout_type":        clause.get("layout_type"),
            "assessment":         merged["assessment"],
            "severity":           merged["severity"],
            "reason":             merged["reason"],
            "recommended_action": merged["recommended_action"],
            "evidence_phrases":   merged["evidence_phrases"],
            "_confidence":        merged["confidence"],
            "_source":            source,
            "_ai_metadata":       ai_meta,
            "_baseline_result":   baseline,
            "_decision_delta":    delta,
            "_confidence_bucket": conf_bkt,
            "_review_priority":   priority,
            "_ai_trace":          trace,
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log.info(f"Output written to: {output_path}")

    # ── Summary ───────────────────────────────────────────────────────────
    ICONS = {
        "NON_TRANSFERABLE_REGULATION": "🚫",
        "CUSTOMER_RESPONSIBILITY":     "⚠️ ",
        "OPERATIONAL_RISK":            "🔴",
        "SCOPE_UNDEFINED":             "🔵",
        "AMBIGUOUS_REQUIREMENT":       "🟡",
        "VALID":                       "✅",
    }
    SEV_ICON = {"HIGH": "HIGH", "MEDIUM": "MED ", "LOW": "LOW "}

    print(f"\n{'='*62}")
    print(f"  Obligation Analysis Engine — Stage 4.5")
    print(f"{'='*62}")
    print(f"  Clauses analysed : {len(clauses)}")
    print(f"  Flagged          : {len(output)} "
          f"({'including' if include_valid else 'excluding'} VALID)")
    llm_used_count = sum(1 for r in output if r.get("_ai_metadata", {}).get("llm_used"))
    print(f"  LLM-enhanced     : {llm_used_count} / {len(output)}")
    if provider:
        print(f"  Provider         : {provider.provider_name} / {provider.model_name}")
    print(f"{'='*62}")
    for assessment in [
        "NON_TRANSFERABLE_REGULATION", "CUSTOMER_RESPONSIBILITY",
        "OPERATIONAL_RISK", "SCOPE_UNDEFINED", "AMBIGUOUS_REQUIREMENT", "VALID",
    ]:
        count = stats.get(assessment, 0)
        if count:
            icon = ICONS.get(assessment, "  ")
            print(f"  {icon} {assessment:<32} {count}")
    print(f"{'='*62}\n")

    if output:
        print(f"  {'Clause':<10} {'Assessment':<30} {'Sev':<6} {'Src':<10} p.")
        print(f"  {'-'*64}")
        for r in output:
            sev  = SEV_ICON.get(r["severity"], r["severity"])
            page = str(r["page"]) if r["page"] else "—"
            src  = r["_source"]
            print(
                f"  {r['clause_id']:<10} {r['assessment']:<30} "
                f"{sev:<6} {src:<10} {page}"
            )
        print()

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 4.5 — Obligation Analysis Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("input_file",       help="Path to stage4_clauses.json")
    parser.add_argument("--output",         default="stage4_5_obligation_analysis.json")
    parser.add_argument("--no-llm",         action="store_true", help="Rule-based only")
    parser.add_argument("--include-valid",  action="store_true",
                        help="Include VALID clauses in output (default: omit)")
    args = parser.parse_args()

    run(
        input_path    = args.input_file,
        output_path   = args.output,
        skip_llm      = args.no_llm,
        include_valid = args.include_valid,
    )


if __name__ == "__main__":
    main()
