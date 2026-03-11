#!/usr/bin/env python3
"""
Stage 8: Remediation Proposal Generator

For every HIGH or MEDIUM finding in the compliance pipeline, proposes:
  - problem_summary      — concise description of the legal/operational issue
  - negotiation_guidance — how the provider should address this with the customer
  - suggested_clause     — concrete replacement contractual wording
  - fallback_option      — minimum acceptable compromise if suggested_clause is rejected

Two-pass architecture:
  Pass 1 — Rule-based templates (per finding_type, always runs)
  Pass 2 — LLM refinement via provider abstraction (optional, --no-llm to skip)
             Supports Anthropic (claude-opus-4-6) and OpenAI (gpt-4o).
             LLM result replaces rule result when confidence >= 0.80.

Input files:
  --compliance   stage6_compliance_CT-2026-001.json  (Stage 6 output)
  --obligations  stage4_5_obligation_analysis.json   (Stage 4.5 output)
  --clauses      stage4_clauses.json                 (optional, supplies original text)

Output:
  stage8_remediation_proposals.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Bootstrap project root so 'llm.*' is importable regardless of CWD
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ---------------------------------------------------------------------------
# LLM module imports (graceful degradation)
# ---------------------------------------------------------------------------

try:
    from llm.base import BaseLLMProvider, LLMAuditMetadata, DETERMINISTIC_AI_META
    from llm.prompts import (
        REMEDIATION_SYSTEM_PROMPT,
        REMEDIATION_OUTPUT_SCHEMA,
        PROMPT_VERSION_REMEDIATION,
        build_remediation_user_message,
    )
    from llm.tracing import (
        confidence_bucket,
        decision_delta_proposal,
        review_priority_proposal,
        build_remediation_trace,
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

    def decision_delta_proposal(src):  # type: ignore[misc]
        if src == "rule_based": return None
        if src == "hybrid": return "no_change"
        if src == "llm": return "ai_override"
        return None

    def review_priority_proposal(finding_type, conf_bkt, suggested_clause):  # type: ignore[misc]
        if (conf_bkt == "low" or not suggested_clause.strip()
                or finding_type in ("NON_TRANSFERABLE_REGULATION", "OPERATIONAL_RISK")):
            return "HIGH"
        if conf_bkt == "medium":
            return "MEDIUM"
        return "LOW"

    def build_remediation_trace(finding_type, llm_content, source):  # type: ignore[misc]
        return None


# ── 1. Rule-based proposal templates ─────────────────────────────────────────

RULE_TEMPLATES: dict[str, dict[str, str]] = {
    "AMBIGUOUS_REQUIREMENT": {
        "problem_summary": (
            "The clause uses vague, unmeasurable language (e.g. 'industry best practices', "
            "'state of the art', 'appropriate measures') that creates an indeterminate obligation. "
            "Without objective criteria, compliance cannot be verified and disputes cannot be resolved."
        ),
        "negotiation_guidance": (
            "Request that the customer replace all vague performance terms with objectively verifiable "
            "criteria, named standards, or defined metrics. Any security or compliance obligation must "
            "be measurable to be enforceable. Propose a named-standard model (e.g. ISO/IEC 27001:2022) "
            "with certification as evidence of compliance. Reject open-ended language that could expand "
            "scope without mutual agreement."
        ),
        "suggested_clause": (
            "The Provider shall implement and maintain information security controls in accordance with "
            "ISO/IEC 27001:2022. Compliance shall be evidenced by a valid certification issued by an "
            "accredited third-party certification body, or, where certification is not yet obtained, a "
            "current Statement of Applicability signed by the Provider's Chief Information Security "
            "Officer. Any additional security requirements proposed by the Customer shall be documented "
            "in a mutually executed Security Requirements Schedule prior to taking effect and shall not "
            "impose obligations on the Provider materially beyond the referenced standard without "
            "corresponding adjustment to fees and timelines."
        ),
        "fallback_option": (
            "Accept ISO/IEC 27001:2022 compliance as the baseline, with a defined review cycle "
            "for adding named standards by mutual written agreement."
        ),
    },

    "NON_TRANSFERABLE_REGULATION": {
        "problem_summary": (
            "The clause purports to transfer the Customer's own statutory or regulatory reporting "
            "obligations directly to the Provider. Regulatory obligations arising from the Customer's "
            "status as a regulated entity (e.g. under DORA, NIS2, GDPR) are non-delegable: the "
            "regulated entity remains solely responsible to the competent authority. Such a transfer "
            "is legally ineffective and exposes the Provider to undefined regulatory liability."
        ),
        "negotiation_guidance": (
            "Reject any clause that makes the Provider the primary obligor toward a regulatory authority "
            "on the Customer's behalf. The Provider may agree to support the Customer operationally "
            "(e.g. timely incident notifications, supplying audit evidence, providing SIEM-compatible "
            "logs), but must not file reports to BaFin, BSI, EBA or any other authority in the "
            "Customer's name. Propose an Assistance Model: the Customer retains the obligation; the "
            "Provider commits to specific, scoped assistance actions within agreed timeframes."
        ),
        "suggested_clause": (
            "The Customer acknowledges that all reporting and notification obligations owed to any "
            "competent supervisory authority (including but not limited to BaFin, BSI, and EBA) arising "
            "from the Customer's status as a regulated entity are borne exclusively by the Customer. "
            "The Provider shall support the Customer in discharging such obligations by: "
            "(i) notifying the Customer of any confirmed security incident materially affecting Customer "
            "data within four (4) hours of the Provider's internal incident declaration; "
            "(ii) providing a detailed incident report within forty-eight (48) hours of such declaration; "
            "(iii) supplying evidence, logs, and documentation reasonably required by the Customer to "
            "prepare and submit its own regulatory reports; and "
            "(iv) making available a designated point of contact during any regulatory investigation. "
            "The Provider shall have no obligation to submit reports directly to any regulatory authority "
            "on behalf of the Customer unless acting under a separately executed, duly notarised power "
            "of attorney that specifically authorises such action."
        ),
        "fallback_option": (
            "Accept a provider support obligation (notification, logs, named contact) with an explicit "
            "disclaimer that the Customer bears all primary regulatory reporting obligations."
        ),
    },

    "OPERATIONAL_RISK": {
        "problem_summary": (
            "The clause imposes operationally unrealistic obligations — such as notification within "
            "minutes, unlimited or unscheduled audit access to all systems, or continuous real-time "
            "data feeds — that cannot be delivered reliably, create disproportionate security risk, "
            "and may be technically infeasible at scale."
        ),
        "negotiation_guidance": (
            "Replace all undefined or unrealistic time obligations with specific, tiered SLAs. "
            "Scope all audit rights to Customer-relevant systems only, with scheduled windows and "
            "advance notice. Replace real-time or continuous log feed requirements with periodic "
            "delivery or on-demand access within a defined SLA. Ensure all obligations are capped: "
            "unlimited access to internal infrastructure or source code is a security risk."
        ),
        "suggested_clause": (
            "Incident Notification: The Provider shall notify the Customer of any confirmed security "
            "incident materially affecting Customer data within four (4) business hours of the "
            "Provider's internal incident declaration. A full incident report shall be delivered within "
            "forty-eight (48) hours. "
            "Audit Rights: The Customer or its appointed independent auditor may conduct one (1) "
            "compliance audit per calendar year upon thirty (30) calendar days' prior written notice, "
            "during normal business hours, subject to the Provider's information security requirements. "
            "The scope shall be limited to systems directly related to the services under this Agreement. "
            "Log Access: The Provider shall make available, within twenty-four (24) hours of a written "
            "request, aggregated security event logs relating to Customer data environments. Continuous "
            "or real-time streaming of internal security data is not included in the standard scope."
        ),
        "fallback_option": (
            "Accept a 4-hour initial notification SLA with 48-hour full report, and annual audit "
            "rights with 30 days' notice and defined scope limitations."
        ),
    },

    "SCOPE_UNDEFINED": {
        "problem_summary": (
            "The clause references 'applicable laws', 'relevant regulations', or 'industry standards' "
            "without naming specific legal instruments, frameworks, or supervisory authorities. This "
            "creates an open-ended, indeterminate obligation that may expand without mutual agreement."
        ),
        "negotiation_guidance": (
            "Require the customer to enumerate all referenced legal instruments, standards, and "
            "frameworks in a contractual annex. Any future changes to the applicable set must require "
            "written agreement by both parties, with a minimum 90-day implementation notice period and "
            "a right to renegotiate fees where changes impose material additional cost."
        ),
        "suggested_clause": (
            "The Provider shall comply with the data protection, security, and operational resilience "
            "standards enumerated in Schedule [A] (Applicable Regulatory Frameworks), as agreed by "
            "the parties in writing and attached hereto. "
            "Where a change in applicable law or regulation requires amendment of Schedule [A], the "
            "Customer shall notify the Provider in writing no later than ninety (90) days prior to the "
            "effective date of such change. If the required amendment imposes material additional cost "
            "or operational burden on the Provider, the parties shall negotiate in good faith a "
            "corresponding adjustment to fees and timelines within thirty (30) days of such notification. "
            "No amendment to Schedule [A] shall take effect without the written countersignature of "
            "both parties."
        ),
        "fallback_option": (
            "Accept a defined list of named frameworks in the agreement body with a change management "
            "clause requiring 90-day notice and mutual written consent for additions."
        ),
    },

    "CUSTOMER_RESPONSIBILITY": {
        "problem_summary": (
            "The clause assigns to the Provider obligations that are legally the Customer's own "
            "controller responsibilities under GDPR — specifically, determining data classification, "
            "defining retention periods, establishing lawful bases for processing, and conducting "
            "Data Protection Impact Assessments (DPIA). These are non-delegable controller duties."
        ),
        "negotiation_guidance": (
            "Reject all clauses that purport to transfer controller responsibilities to the Provider. "
            "Data classification, DPIA execution, lawful-basis determination, and retention policy "
            "definition must remain with the Customer. The Provider may offer supporting information "
            "(e.g. a description of technical processing operations to assist a DPIA), but cannot "
            "carry out the legal assessment."
        ),
        "suggested_clause": (
            "The Customer, acting as data controller within the meaning of GDPR Art. 4(7), shall "
            "remain solely responsible for: "
            "(i) determining and documenting the sensitivity classification of all personal data "
            "processed under this Agreement; "
            "(ii) establishing the lawful basis for each category of processing under GDPR Art. 6 "
            "and documenting such basis in the Customer's Records of Processing Activities; "
            "(iii) defining data retention periods for each category of Customer data, which the "
            "Provider shall implement on receipt of written instruction; and "
            "(iv) conducting any Data Protection Impact Assessment required under GDPR Art. 35. "
            "The Provider shall, upon written request and within fifteen (15) business days, supply "
            "a description of the Provider's technical and organisational processing operations to "
            "assist the Customer in completing a DPIA. The Provider shall not be required to conduct, "
            "sign, or submit any DPIA on behalf of the Customer."
        ),
        "fallback_option": (
            "Accept a DPIA cooperation clause under which the Provider supplies processing details "
            "within 15 business days of request, while the Customer remains the DPIA author."
        ),
    },
}

INCLUDED_SEVERITIES = {"HIGH", "MEDIUM"}


# ── 2. Loaders ────────────────────────────────────────────────────────────────

def _load_json(path: str, label: str) -> Any:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] {label} not found: {path}", file=sys.stderr)
        sys.exit(1)
    with p.open() as fh:
        return json.load(fh)


def _build_clause_index(clauses_path: str) -> dict[str, str]:
    """Returns {clause_id -> original_text} if clauses file is available."""
    if not clauses_path:
        return {}
    p = Path(clauses_path)
    if not p.exists():
        print(f"[WARN] clauses file not found: {clauses_path}", file=sys.stderr)
        return {}
    with p.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return {c["clause_id"]: c["text"] for c in data if "clause_id" in c and "text" in c}


# ── 3. Rule-based pass ────────────────────────────────────────────────────────

def _rule_proposal(finding: dict) -> dict:
    ftype = finding.get("finding_type", "")
    tmpl  = RULE_TEMPLATES.get(ftype)
    if not tmpl:
        return {
            "problem_summary":      finding.get("reason", "No rule template available."),
            "negotiation_guidance": finding.get("recommended_action", "Review with legal counsel."),
            "suggested_clause": (
                "The parties shall negotiate specific, measurable obligations to replace this clause. "
                "Any obligation must be: (i) precisely scoped; (ii) time-bounded; (iii) operationally "
                "feasible for the Provider; and (iv) verifiable by objective criteria."
            ),
            "fallback_option": (
                "Agree in writing on a defined scope and timeline before this clause takes effect."
            ),
        }
    return {
        "problem_summary":      tmpl["problem_summary"],
        "negotiation_guidance": tmpl["negotiation_guidance"],
        "suggested_clause":     tmpl["suggested_clause"],
        "fallback_option":      tmpl["fallback_option"],
    }


# ── 4. LLM pass ──────────────────────────────────────────────────────────────

LLM_CONFIDENCE_THRESHOLD = 0.80


def _llm_proposal(
    finding:       dict,
    original_text: str,
    rule_proposal: dict,
    provider:      "BaseLLMProvider",
) -> Optional[dict]:
    """
    Call LLM to produce a clause-specific remediation proposal.
    Returns the LLM response dict, or None if the call failed.
    """
    user_msg = build_remediation_user_message(finding, original_text, rule_proposal)

    try:
        response = provider.complete_structured(
            system_prompt  = REMEDIATION_SYSTEM_PROMPT,
            user_message   = user_msg,
            json_schema    = REMEDIATION_OUTPUT_SCHEMA,
            prompt_version = PROMPT_VERSION_REMEDIATION,
            max_tokens     = 1024,
        )
    except RuntimeError as exc:
        print(f"  [LLM WARN] Unrecoverable error for {finding.get('clause_id')}: {exc}",
              file=sys.stderr)
        return None

    return response


# ── 5. Main pipeline ──────────────────────────────────────────────────────────

def extract_findings(compliance_report: dict, obligations: list[dict]) -> list[dict]:
    """
    Merge Stage 6 obligation findings with Stage 4.5 detail.
    Only HIGH and MEDIUM severities pass through.
    """
    ob_index: dict[str, dict] = {c["clause_id"]: c for c in obligations}
    findings: list[dict] = []

    for f in compliance_report.get("obligation_analysis", {}).get("findings", []):
        if f.get("severity") not in INCLUDED_SEVERITIES:
            continue
        ob_detail = ob_index.get(f.get("clause_id", ""), {})
        merged = {**f}
        for key in ("reason", "recommended_action", "_confidence", "_source", "_ai_metadata"):
            if key not in merged and key in ob_detail:
                merged[key] = ob_detail[key]
        findings.append(merged)

    return findings


def generate_proposals(
    findings:     list[dict],
    clause_index: dict[str, str],
    llm_provider: Optional["BaseLLMProvider"] = None,
    verbose:      bool = True,
) -> list[dict]:
    """
    Generate remediation proposals for a list of findings.

    Parameters
    ----------
    findings:     List of compliance findings (HIGH/MEDIUM severity)
    clause_index: {clause_id -> original_text} for LLM context
    llm_provider: Pre-initialised LLM provider (from llm.config.get_llm_provider)
    verbose:      Print per-finding progress
    """
    provider = llm_provider
    proposals: list[dict] = []

    for finding in findings:
        clause_id     = finding.get("clause_id", "unknown")
        ftype         = finding.get("finding_type", "UNKNOWN")
        severity      = finding.get("severity", "MEDIUM")
        original_text = clause_index.get(clause_id, "")

        if verbose:
            print(f"  Processing {clause_id}  [{severity}] {ftype} …", end=" ", flush=True)

        # Pass 1: rule-based
        rule           = _rule_proposal(finding)
        proposal_src   = "rule_based"
        final_proposal = rule
        ai_meta        = DETERMINISTIC_AI_META
        llm_content_raw: Optional[dict] = None

        # Pass 2: LLM (optional)
        if provider is not None and LLM_MODULE_AVAILABLE:
            llm_resp = _llm_proposal(finding, original_text, rule, provider)
            if llm_resp is not None:
                llm_content_raw = llm_resp.content
                llm_conf        = llm_content_raw.get("confidence", 0.0)
                if llm_conf >= LLM_CONFIDENCE_THRESHOLD:
                    final_proposal = {
                        "problem_summary":      llm_content_raw["problem_summary"],
                        "negotiation_guidance": llm_content_raw["negotiation_guidance"],
                        "suggested_clause":     llm_content_raw["suggested_clause"],
                        "fallback_option":      llm_content_raw.get("fallback_option", rule["fallback_option"]),
                    }
                    proposal_src = "llm"
                    ai_meta      = llm_resp.metadata.to_dict()
                else:
                    # LLM low confidence — keep rule base but record hybrid attempt
                    proposal_src = "hybrid"
                    ai_meta      = llm_resp.metadata.to_dict()

        if verbose:
            print(proposal_src)

        # ── Explainability fields ──────────────────────────────────────────
        ai_attempted  = (proposal_src != "rule_based")
        ai_conf       = ai_meta.get("confidence") if ai_attempted else None
        conf_bkt      = confidence_bucket(ai_conf)
        baseline      = {
            "problem_summary_preview":  rule["problem_summary"][:120],
            "suggested_clause_preview": rule["suggested_clause"][:120],
        } if ai_attempted else None
        delta         = decision_delta_proposal(proposal_src)
        priority      = review_priority_proposal(
            ftype, conf_bkt, final_proposal.get("suggested_clause", "")
        )
        trace         = build_remediation_trace(ftype, llm_content_raw, proposal_src)

        proposals.append({
            "clause_id":              clause_id,
            "finding_type":           ftype,
            "severity":               severity,
            "page":                   finding.get("page"),
            "layout_type":            finding.get("layout_type"),
            "original_text_preview":  (original_text[:200] + "…") if len(original_text) > 200 else original_text,
            "problem_summary":        final_proposal["problem_summary"],
            "negotiation_guidance":   final_proposal["negotiation_guidance"],
            "suggested_clause":       final_proposal["suggested_clause"],
            "fallback_option":        final_proposal.get("fallback_option", ""),
            "_proposal_source":       proposal_src,
            "_ai_metadata":           ai_meta,
            "_baseline_result":       baseline,
            "_decision_delta":        delta,
            "_confidence_bucket":     conf_bkt,
            "_review_priority":       priority,
            "_ai_trace":              trace,
        })

    return proposals


# ── 6. Terminal summary ───────────────────────────────────────────────────────

_SEV_ICON = {"HIGH": "🔴", "MEDIUM": "🟡"}
_W = 72


def print_summary(proposals: list[dict], output_path: str) -> None:
    sep  = "─" * _W
    high = [p for p in proposals if p["severity"] == "HIGH"]
    med  = [p for p in proposals if p["severity"] == "MEDIUM"]
    llm_used = sum(1 for p in proposals
                   if p.get("_ai_metadata", {}).get("llm_used", False))

    print(f"\n{'═' * _W}")
    print(f"  STAGE 8 — REMEDIATION PROPOSALS")
    print(f"{'═' * _W}")
    print(f"  Generated : {len(proposals)} proposals  "
          f"│  HIGH={len(high)}  MEDIUM={len(med)}")
    print(f"  LLM-enhanced: {llm_used} / {len(proposals)}")
    print(sep)

    for p in proposals:
        icon = _SEV_ICON.get(p["severity"], "❓")
        src  = "🤖" if p.get("_proposal_source") in ("llm", "hybrid") else "📋"
        print(f"\n  {icon} {p['clause_id']}  [{p['finding_type']}]  "
              f"{src} {p.get('_proposal_source', 'rule_based')}")
        if p.get("page"):
            print(f"     page={p['page']}  layout={p.get('layout_type', 'n/a')}")

        summary = p["problem_summary"]
        print(f"     Problem  : {summary[:66]}")
        if len(summary) > 66:
            for chunk in [summary[i:i+66] for i in range(66, len(summary), 66)]:
                print(f"               {chunk}")

        clause_preview = p["suggested_clause"][:120].replace("\n", " ") + "…"
        print(f"     Clause   : {clause_preview}")

    print(f"\n{sep}")
    print(f"  Output saved → {output_path}")
    print(f"{'═' * _W}\n")


# ── 7. CLI ────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Stage 8: Generate remediation proposals for flagged contract clauses."
    )
    ap.add_argument("--compliance", "-c", default="stage6_compliance_CT-2026-001.json")
    ap.add_argument("--obligations", "-b", default="stage4_5_obligation_analysis.json")
    ap.add_argument("--clauses", default="stage4_clauses.json")
    ap.add_argument("--output", "-o", default="stage8_remediation_proposals.json")
    ap.add_argument("--no-llm", dest="no_llm", action="store_true",
                    help="Skip LLM pass; use rule-based templates only")
    ap.add_argument("--quiet", "-q", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = _parse_args()

    compliance   = _load_json(args.compliance,  "compliance report")
    obligations  = _load_json(args.obligations, "obligation analysis")
    clause_index = _build_clause_index(args.clauses)

    provider = None
    if not args.no_llm and LLM_MODULE_AVAILABLE:
        try:
            from llm.config import get_llm_provider
            provider = get_llm_provider()
        except Exception as exc:
            print(f"[WARN] LLM unavailable ({exc}); falling back to rule-based.", file=sys.stderr)

    findings = extract_findings(compliance, obligations)
    if not args.quiet:
        print(f"\n  Stage 8 — processing {len(findings)} findings "
              f"(HIGH={sum(1 for f in findings if f['severity']=='HIGH')}, "
              f"MEDIUM={sum(1 for f in findings if f['severity']=='MEDIUM')}) …")

    proposals = generate_proposals(
        findings      = findings,
        clause_index  = clause_index,
        llm_provider  = provider,
        verbose       = not args.quiet,
    )

    with open(args.output, "w") as fh:
        json.dump(proposals, fh, indent=2)

    if not args.quiet:
        print_summary(proposals, args.output)


if __name__ == "__main__":
    main()
