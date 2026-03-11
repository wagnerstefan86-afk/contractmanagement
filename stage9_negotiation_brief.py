#!/usr/bin/env python3
"""
Stage 9: Negotiation Brief Generator  (v2 — clause-level routing)

Transforms Stage 8 remediation proposals, Stage 6 SR compliance findings,
and (new) Stage 5 clause_sr_matches into a structured negotiation brief.

Produces:
  • <output>.json               — machine-readable brief
  • contract_negotiation_brief.md — human-readable Markdown report

Three-layer input:
  1. Obligation findings (clause-level)  — stage8_remediation_proposals.json
  2. SR compliance findings (SR-level)   — stage6_compliance_<id>.json
  3. Clause-SR matches (clause × SR)     — clause_sr_matches.json  [NEW v2]

Architecture change (v2):
  OLD: SR findings routed by title/framework keywords only
       affected_clauses showed sub_requirement_id for SR findings
  NEW: SR findings enriched with matched_clause_id from Stage 6 v2
       affected_clauses always shows clause_id references
       clause findings enriched with their SR match evidence for Markdown
       SR match signal used as tiebreaker for AMBIGUOUS_REQUIREMENT routing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── 1. Topic taxonomy ─────────────────────────────────────────────────────────

TOPICS = [
    "REGULATORY_COMPLIANCE",
    "INCIDENT_MANAGEMENT",
    "DATA_PROTECTION",
    "SECURITY_CONTROLS",
    "AUDIT_RIGHTS",
    "SERVICE_LEVELS",
    "OTHER",
]

TOPIC_LABELS = {
    "REGULATORY_COMPLIANCE": "Regulatory Compliance",
    "INCIDENT_MANAGEMENT":   "Incident Management",
    "DATA_PROTECTION":       "Data Protection",
    "SECURITY_CONTROLS":     "Security Controls",
    "AUDIT_RIGHTS":          "Audit Rights",
    "SERVICE_LEVELS":        "Service Levels",
    "OTHER":                 "Other",
}

_POSITION_TEMPLATES: dict[str, str] = {
    "REGULATORY_COMPLIANCE": (
        "All clauses that transfer regulatory reporting obligations directly to the Provider "
        "must be removed or replaced with an Assistance Model: the Provider supports the "
        "Customer's compliance but cannot act as primary obligor to supervisory authorities. "
        "All open-ended references to 'applicable law' must be replaced with enumerated "
        "instruments in a mutually agreed contractual schedule, subject to a 90-day change "
        "notice and fee-adjustment mechanism."
    ),
    "INCIDENT_MANAGEMENT": (
        "Replace all undefined notification timeframes ('immediately', 'without delay') with "
        "a tiered SLA model: preliminary notification to the Customer within four (4) business "
        "hours of incident declaration; full report within forty-eight (48) hours. Direct "
        "regulatory authority reporting remains the Customer's obligation. Any obligation to "
        "notify 'all affected parties' or 'all stakeholders' must be scoped to named "
        "recipients with agreed timelines."
    ),
    "DATA_PROTECTION": (
        "All GDPR controller obligations — data classification, DPIA execution, lawful-basis "
        "determination, and retention-period definition — must be reassigned to the Customer "
        "as data controller. The Provider's role is limited to processor obligations under "
        "GDPR Art. 28. International data transfer mechanisms must be explicitly named "
        "(e.g. Standard Contractual Clauses). Subprocessor provisions must reference a "
        "maintained register with minimum 30-day advance notification of changes."
    ),
    "SECURITY_CONTROLS": (
        "All security obligation clauses must reference named, verifiable standards "
        "(e.g. ISO/IEC 27001:2022) with defined evidence requirements such as valid "
        "third-party certification or a current Statement of Applicability. Terms such as "
        "'state of the art', 'industry best practices', or 'appropriate measures' must be "
        "replaced with objective, measurable criteria or a named standard. Supply chain "
        "security obligations must enumerate specific controls rather than reference generic "
        "frameworks."
    ),
    "AUDIT_RIGHTS": (
        "Unlimited, unscheduled, or unrestricted audit access to all Provider systems, "
        "infrastructure, and source code must be replaced with scoped, scheduled rights: "
        "one (1) annual compliance audit with thirty (30) calendar days' prior notice, "
        "limited to systems directly serving Customer data, conducted during normal business "
        "hours by a mutually agreed independent auditor. Emergency audits following a "
        "declared breach shall be scoped and scheduled within five (5) business days. "
        "Access to source code repositories is not included in standard audit scope."
    ),
    "SERVICE_LEVELS": (
        "All SLA obligations must specify the measurement methodology, the measurement period, "
        "the monitoring service, and the credit calculation. SLA credits must be limited to "
        "a defined percentage of the affected month's invoice. Uptime commitments must "
        "reference the agreed third-party monitoring service defined in Annex B."
    ),
    "OTHER": (
        "These findings require individual review by Legal and Security. Each clause should "
        "be assessed for operational feasibility and legal enforceability before acceptance."
    ),
}

SEVERITY_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# SR title keywords → topic (used as tiebreaker signal)
_SR_TITLE_TOPIC: list[tuple[list[str], str]] = [
    (["incident", "reporting timeline", "notification"],    "INCIDENT_MANAGEMENT"),
    (["transfer", "subprocessor", "data subject", "dpa",
      "processing agreement"],                             "DATA_PROTECTION"),
    (["audit"],                                            "AUDIT_RIGHTS"),
    (["supply chain"],                                     "SECURITY_CONTROLS"),
    (["ict risk", "ict incident", "third-party"],          "REGULATORY_COMPLIANCE"),
]


# ── 2. Topic assignment (deterministic) ───────────────────────────────────────

def _topic_from_sr_matches(sr_matches: list[dict]) -> str | None:
    """
    Derive a topic from a clause's SR match records.
    Uses the DIRECT_MATCH with highest confidence; falls back to PARTIAL_MATCH.
    Returns None if no signal found.
    """
    if not sr_matches:
        return None
    ranked = sorted(
        sr_matches,
        key=lambda m: (1 if m.get("match_type") == "DIRECT_MATCH" else 0,
                       m.get("match_confidence", 0)),
        reverse=True,
    )
    for m in ranked:
        title = m.get("sr_title", "").lower()
        fw    = m.get("framework", "")
        for keywords, topic in _SR_TITLE_TOPIC:
            if any(kw in title for kw in keywords):
                return topic
        if fw == "DORA":
            return "REGULATORY_COMPLIANCE"
        if fw == "GDPR":
            return "DATA_PROTECTION"
    return None


def _assign_topic(finding: dict) -> str:
    """Map a single finding to one of the canonical topic clusters."""
    source = finding.get("source", "OBLIGATION_ANALYSIS")
    ftype  = finding.get("finding_type", "")

    # ── SR-level findings (Stage 6) ────────────────────────────────────────
    if source == "SR_COMPLIANCE":
        title     = finding.get("title", "").lower()
        framework = finding.get("framework", "")
        if any(kw in title for kw in ("incident", "reporting timeline", "notification")):
            return "INCIDENT_MANAGEMENT"
        if any(kw in title for kw in ("transfer", "subprocessor", "data subject", "dpa",
                                      "processing agreement")):
            return "DATA_PROTECTION"
        if "audit" in title:
            return "AUDIT_RIGHTS"
        if "supply chain" in title:
            return "SECURITY_CONTROLS"
        if framework == "DORA":
            return "REGULATORY_COMPLIANCE"
        if framework == "GDPR":
            return "DATA_PROTECTION"
        return "SECURITY_CONTROLS"

    # ── Obligation-level findings (Stage 8) ────────────────────────────────
    if ftype == "NON_TRANSFERABLE_REGULATION":
        return "REGULATORY_COMPLIANCE"

    if ftype == "CUSTOMER_RESPONSIBILITY":
        return "DATA_PROTECTION"

    if ftype == "SCOPE_UNDEFINED":
        ctx = (finding.get("reason", "") + " " + finding.get("problem_summary", "")).lower()
        if any(kw in ctx for kw in ("law", "regulation", "directive", "statutory",
                                    "supervisory")):
            return "REGULATORY_COMPLIANCE"
        return "SECURITY_CONTROLS"

    if ftype == "OPERATIONAL_RISK":
        # Prefer full clause text (avoids 200-char preview truncation)
        ctx = (
            finding.get("clause_full_text", "")
            or finding.get("original_text_preview", "")
            + " " + finding.get("reason", "")
        ).lower()
        if any(kw in ctx for kw in ("audit", "source code", "unrestricted access",
                                    "access to all", "unlimited")):
            return "AUDIT_RIGHTS"
        if any(kw in ctx for kw in ("sla", "uptime", "availability", "service credit")):
            return "SERVICE_LEVELS"
        return "INCIDENT_MANAGEMENT"

    if ftype == "AMBIGUOUS_REQUIREMENT":
        # Use SR match signal as tiebreaker (v2 enhancement)
        sr_topic = _topic_from_sr_matches(finding.get("sr_matches", []))
        if sr_topic:
            return sr_topic
        return "SECURITY_CONTROLS"

    return "OTHER"


# ── 3. Group findings into topics ─────────────────────────────────────────────

def _highest_severity(findings: list[dict]) -> str:
    if not findings:
        return "LOW"
    return max(
        (f.get("severity", "LOW") for f in findings),
        key=lambda s: SEVERITY_RANK.get(s, 0),
    )


def _overall_risk(topic_groups: dict[str, list[dict]]) -> str:
    all_findings = [f for grp in topic_groups.values() for f in grp]
    return _highest_severity(all_findings)


def _clause_ref(finding: dict) -> str:
    """
    Return the clause_id reference for a finding.
    v2: SR compliance findings now carry matched_clause_id — prefer that so
    affected_clauses lists are clause-centric rather than SR-centric.
    """
    if finding.get("source") == "SR_COMPLIANCE":
        return (finding.get("matched_clause_id")
                or finding.get("sub_requirement_id", "?"))
    return finding.get("clause_id", "?")


def _risk_summary(topic: str, findings: list[dict]) -> str:
    count  = len(findings)
    high_n = sum(1 for f in findings if f.get("severity") == "HIGH")
    med_n  = sum(1 for f in findings if f.get("severity") == "MEDIUM")
    types  = sorted({f.get("finding_type", "") for f in findings})

    sev_desc = (
        f"{high_n} HIGH and {med_n} MEDIUM-severity" if high_n and med_n else
        f"{high_n} HIGH-severity"  if high_n else
        f"{med_n} MEDIUM-severity" if med_n else
        f"{count}"
    )

    topic_intros: dict[str, str] = {
        "REGULATORY_COMPLIANCE": (
            f"The contract contains {sev_desc} regulatory compliance issues "
            f"involving {', '.join(types)}. "
            "These clauses attempt to assign the Customer's non-transferable statutory "
            "obligations to the Provider and include undefined references to 'applicable law' "
            "that create open-ended liability."
        ),
        "INCIDENT_MANAGEMENT": (
            f"Incident management obligations contain {sev_desc} issues "
            f"across {count} clause(s). "
            "Notification timeframes are operationally infeasible (sub-hour or 'immediate' "
            "obligations) and notification scope is undefined ('all stakeholders'). "
            "These obligations expose the Provider to unquantifiable breach-of-contract risk."
        ),
        "DATA_PROTECTION": (
            f"Data protection provisions contain {sev_desc} issues "
            f"({', '.join(types)}). "
            "Controller-level GDPR duties (data classification, DPIA, lawful-basis "
            "determination) have been misallocated to the Provider as processor. "
            "International data transfer clauses lack explicit transfer mechanisms."
        ),
        "SECURITY_CONTROLS": (
            f"Security control obligations contain {sev_desc} issues "
            f"({', '.join(types)}). "
            "Multiple clauses use unmeasurable language ('state of the art', 'industry best "
            "practices') or reference frameworks without naming them. "
            "Supply chain security provisions are insufficiently specific for NIS2 compliance."
        ),
        "AUDIT_RIGHTS": (
            f"Audit rights clauses contain {sev_desc} issues. "
            "The contract demands unlimited, unscheduled access to all Provider systems, "
            "networks, and source code repositories without prior notice — a scope that "
            "creates critical security and operational risk for the Provider."
        ),
        "SERVICE_LEVELS": (
            f"Service level provisions contain {sev_desc} issues. "
            "SLA obligations lack measurable baselines, defined monitoring methodology, "
            "and capped credit calculations."
        ),
        "OTHER": (
            f"The contract contains {sev_desc} issues that do not fit a standard category "
            "and require individual legal review."
        ),
    }
    return topic_intros.get(topic, f"{sev_desc} issues detected ({', '.join(types)}).")


def group_findings(
    proposals: list[dict],
    sr_findings: list[dict],
    ob_reason_index: dict[str, str] | None,
    clause_sr_idx: dict[str, list[dict]] | None,
    clause_text_idx: dict[str, str] | None,
) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {t: [] for t in TOPICS}

    for p in proposals:
        clause_id    = p.get("clause_id", "")
        precise_reason = (
            ob_reason_index.get(clause_id, "") if ob_reason_index else ""
        ) or p.get("original_text_preview", "")
        sr_matches   = (clause_sr_idx or {}).get(clause_id, [])
        full_text    = (clause_text_idx or {}).get(clause_id, "")

        finding = {
            "source":               "OBLIGATION_ANALYSIS",
            "finding_type":         p.get("finding_type", ""),
            "severity":             p.get("severity", "MEDIUM"),
            "clause_id":            clause_id,
            "reason":               precise_reason,
            "problem_summary":      p.get("problem_summary", ""),
            "suggested_clause":     p.get("suggested_clause", ""),
            "original_text_preview": p.get("original_text_preview", ""),
            "clause_full_text":     full_text,   # untruncated clause text for routing
            "sr_matches":           sr_matches,  # v2: SR match records for this clause
        }
        topic = _assign_topic(finding)
        finding["_topic"] = topic
        groups[topic].append(finding)

    for f in sr_findings:
        topic = _assign_topic(f)
        f = {**f, "_topic": topic}
        groups[topic].append(f)

    return groups


# ── 4. Build structured brief ─────────────────────────────────────────────────

def build_brief(
    proposals: list[dict],
    compliance: dict,
    obligations: list[dict] | None,
    clause_sr_matches: list[dict] | None,
    clauses: list[dict] | None,
) -> dict:
    sr_findings = compliance.get("sr_compliance", {}).get("findings", [])
    contract_id = compliance.get("contract_id", "UNKNOWN")
    org         = compliance.get("org_profile", {})

    # Index of precise Stage 4.5 detection reasons for accurate topic routing
    ob_reason_index: dict[str, str] | None = None
    if obligations:
        ob_reason_index = {
            c["clause_id"]: c.get("reason", "")
            for c in obligations
            if "clause_id" in c
        }

    # Full clause text index — prevents routing errors from 200-char preview truncation
    clause_text_idx: dict[str, str] | None = None
    if clauses:
        clause_text_idx = {c["clause_id"]: c.get("text", "") for c in clauses}

    # Build clause-SR match index {clause_id: [DIRECT+PARTIAL records]}  [v2]
    clause_sr_idx: dict[str, list[dict]] | None = None
    if clause_sr_matches:
        clause_sr_idx = {}
        for r in clause_sr_matches:
            if r.get("match_type") in ("DIRECT_MATCH", "PARTIAL_MATCH"):
                clause_sr_idx.setdefault(r["clause_id"], []).append(r)

    groups  = group_findings(proposals, sr_findings, ob_reason_index, clause_sr_idx,
                              clause_text_idx)
    overall = _overall_risk(groups)

    topic_sections: list[dict] = []
    for topic in TOPICS:
        findings = groups[topic]
        if not findings:
            continue

        affected  = sorted({_clause_ref(f) for f in findings})
        highest   = _highest_severity(findings)

        topic_sections.append({
            "topic":                topic,
            "topic_label":          TOPIC_LABELS[topic],
            "issue_count":          len(findings),
            "highest_severity":     highest,
            "risk_summary":         _risk_summary(topic, findings),
            "affected_clauses":     affected,
            "negotiation_position": _POSITION_TEMPLATES[topic],
            "_findings":            findings,
        })

    topic_sections.sort(
        key=lambda s: (-SEVERITY_RANK.get(s["highest_severity"], 0),
                       TOPICS.index(s["topic"]))
    )

    return {
        "contract_id":    contract_id,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "organization":   org.get("organization_name", ""),
        "frameworks":     org.get("regulatory_frameworks", []),
        "overall_risk":   overall,
        "topic_count":    len(topic_sections),
        "topics":         topic_sections,
        "_total_findings": sum(s["issue_count"] for s in topic_sections),
    }


def strip_internal(brief: dict) -> dict:
    result = {k: v for k, v in brief.items() if not k.startswith("_")}
    result["topics"] = [
        {k: v for k, v in t.items() if not k.startswith("_")}
        for t in brief.get("topics", [])
    ]
    return result


# ── 5. Markdown generator ─────────────────────────────────────────────────────

_MD_ICON  = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
_MT_ICON  = {"DIRECT_MATCH": "✅", "PARTIAL_MATCH": "⚠️"}
_MD_RISK_DESC = {
    "HIGH":   "Contract **cannot be accepted** in its current form. "
              "Mandatory amendments required before signature.",
    "MEDIUM": "Contract requires **targeted amendments** before acceptance. "
              "Several clauses need clarification or strengthening.",
    "LOW":    "Contract is broadly acceptable with **minor improvements** recommended.",
}


def _md_severity_badge(severity: str) -> str:
    return f"{_MD_ICON.get(severity, '?')} **{severity}**"


def _md_sr_evidence_block(sr_matches: list[dict]) -> list[str]:
    """Render compact SR match evidence lines for a clause finding."""
    if not sr_matches:
        return []
    lines = ["", "> **Regulatory matches for this clause:**", ">"]
    for m in sorted(sr_matches, key=lambda r: r.get("match_confidence", 0), reverse=True):
        mt_icon = _MT_ICON.get(m.get("match_type", ""), "")
        conf    = m.get("match_confidence", 0)
        sr_id   = m.get("sr_id", "")
        fw      = m.get("framework", "")
        ctrl    = m.get("control_id", "")
        title   = m.get("sr_title", "")
        ev      = m.get("extracted_evidence", "")
        ev_short = (ev[:120] + "…") if len(ev) > 120 else ev
        lines.append(f"> {mt_icon} `{sr_id}` — {fw} {ctrl} **{title}** ({conf:.0%})")
        if ev_short:
            lines.append(f">   *\"{ev_short}\"*")
    lines.append("")
    return lines


def generate_markdown(brief: dict, proposals: list[dict]) -> str:
    contract_id = brief["contract_id"]
    org         = brief["organization"]
    frameworks  = ", ".join(brief.get("frameworks", []))
    overall     = brief["overall_risk"]
    gen_date    = brief["generated_at"][:10]

    prop_index: dict[str, dict] = {p["clause_id"]: p for p in proposals}

    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────
    lines += [
        f"# Contract Security Review — {contract_id}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| **Customer** | {org} |",
        f"| **Contract ID** | `{contract_id}` |",
        f"| **Applicable Frameworks** | {frameworks} |",
        f"| **Review Date** | {gen_date} |",
        f"| **Total Findings** | {brief['_total_findings']} |",
        "",
        "---",
        "",
    ]

    # ── Overall Risk ──────────────────────────────────────────────────────
    lines += [
        "## Overall Risk",
        "",
        f"### {_MD_ICON[overall]} {overall}",
        "",
        _MD_RISK_DESC.get(overall, ""),
        "",
    ]

    lines += [
        "| Topic | Issues | Severity | Affected Clauses |",
        "|---|---|---|---|",
    ]
    for t in brief["topics"]:
        sev_badge = _md_severity_badge(t["highest_severity"])
        clauses   = ", ".join(f"`{c}`" for c in t["affected_clauses"])
        lines.append(
            f"| {t['topic_label']} | {t['issue_count']} | {sev_badge} | {clauses} |"
        )
    lines += ["", "---", ""]

    # ── Topic sections ────────────────────────────────────────────────────
    lines.append("## Key Negotiation Topics")
    lines.append("")

    for i, section in enumerate(brief["topics"], 1):
        topic_label = section["topic_label"]
        sev         = section["highest_severity"]
        icon        = _MD_ICON[sev]
        count       = section["issue_count"]

        lines += [
            f"### {i}. {icon} {topic_label}",
            "",
            f"**Issues:** {count}  |  "
            f"**Highest Severity:** {_md_severity_badge(sev)}  |  "
            f"**Affected:** {', '.join(f'`{c}`' for c in section['affected_clauses'])}",
            "",
        ]

        lines += [
            "#### Risk Summary",
            "",
            section["risk_summary"],
            "",
        ]

        clause_findings = [
            f for f in section.get("_findings", [])
            if f.get("source") == "OBLIGATION_ANALYSIS"
        ]
        sr_findings_local = [
            f for f in section.get("_findings", [])
            if f.get("source") == "SR_COMPLIANCE"
        ]

        if clause_findings:
            lines += ["#### Clause-Level Findings", ""]
            for f in clause_findings:
                cid    = f.get("clause_id", "?")
                ftype  = f.get("finding_type", "")
                sev_f  = f.get("severity", "MEDIUM")
                lines.append(
                    f"**`{cid}`** — {_MD_ICON[sev_f]} {sev_f} `{ftype}`  "
                )
                prop = prop_index.get(cid)
                if prop:
                    lines.append(f"> {prop['problem_summary'][:300]}")
                # v2: show SR match evidence inline
                lines += _md_sr_evidence_block(f.get("sr_matches", []))
                if not f.get("sr_matches"):
                    lines.append("")

        if sr_findings_local:
            lines += ["#### Sub-Requirement Gaps", ""]
            for f in sr_findings_local:
                sr_id  = f.get("sub_requirement_id", "?")
                fw     = f.get("framework", "")
                ctrl   = f.get("control_id", "")
                title  = f.get("title", "")
                sev_f  = f.get("severity", "MEDIUM")
                mcid   = f.get("matched_clause_id")
                clause_ref = f" — via `{mcid}`" if mcid else ""
                lines.append(
                    f"- {_MD_ICON[sev_f]} `{sr_id}` ({fw} {ctrl}){clause_ref} — "
                    f"**{title}**: {f.get('description', '')}"
                )
            lines.append("")

        lines += [
            "#### Proposed Negotiation Position",
            "",
            section["negotiation_position"],
            "",
        ]

        # Best suggested clause (highest-severity proposal in this topic)
        best_prop = None
        for sev_prio in ("HIGH", "MEDIUM"):
            for f in clause_findings:
                if f.get("severity") == sev_prio:
                    p = prop_index.get(f.get("clause_id", ""))
                    if p and p.get("suggested_clause"):
                        best_prop = p
                        break
            if best_prop:
                break

        if best_prop:
            lines += [
                "#### Suggested Replacement Wording",
                f"> *Example clause for `{best_prop['clause_id']}` "
                f"({best_prop['finding_type']}):*",
                "",
                "```",
                best_prop["suggested_clause"],
                "```",
                "",
            ]

        lines += ["---", ""]

    # ── Footer ────────────────────────────────────────────────────────────
    lines += [
        "> *Generated by the Contract Compliance Pipeline — Stage 9 (clause-level). "
        "This document is a technical review aid. "
        "Final legal decisions must be made by qualified legal counsel.*",
        "",
    ]

    return "\n".join(lines)


# ── 6. Loaders & CLI ──────────────────────────────────────────────────────────

def _load_json(path: str, label: str) -> Any:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] {label} not found: {path}", file=sys.stderr)
        sys.exit(1)
    with p.open() as fh:
        return json.load(fh)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Stage 9: Generate negotiation brief (clause-level routing)."
    )
    ap.add_argument("--remediation", "-r",
                    default="stage8_remediation_proposals.json",
                    help="Stage 8 output")
    ap.add_argument("--compliance", "-c",
                    default="stage6_compliance_CT-2026-001.json",
                    help="Stage 6 compliance report")
    ap.add_argument("--clause-matches",
                    default="clause_sr_matches.json",
                    help="Stage 5 clause-SR matches (default: clause_sr_matches.json)")
    ap.add_argument("--clauses",
                    default="stage4_clauses.json",
                    help="Stage 4 clauses (full text — avoids preview truncation in routing)")
    ap.add_argument("--obligations",
                    default="stage4_5_obligation_analysis.json",
                    help="Stage 4.5 output for precise routing context (optional)")
    ap.add_argument("--output", "-o",
                    default="contract_negotiation_brief.json",
                    help="JSON output path")
    ap.add_argument("--markdown", "-m",
                    default="contract_negotiation_brief.md",
                    help="Markdown output path")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="Suppress terminal summary")
    return ap.parse_args()


def _print_summary(brief: dict) -> None:
    sep  = "-" * 72
    icon = _MD_ICON.get(brief["overall_risk"], "?")
    print(f"\n{'=' * 72}")
    print(f"  STAGE 9 — CONTRACT NEGOTIATION BRIEF  (clause-level routing)")
    print(f"{'=' * 72}")
    print(f"  Contract     : {brief['contract_id']}")
    print(f"  Organisation : {brief['organization']}")
    print(f"  Overall Risk : {icon}  {brief['overall_risk']}")
    print(f"  Topics       : {brief['topic_count']}  |  "
          f"Total findings: {brief['_total_findings']}")
    print(sep)
    print(f"  {'TOPIC':<24} {'ISSUES':>6} {'SEVERITY':>10}  AFFECTED")
    print(f"  {'-'*24} {'-'*6} {'-'*10}  -------")
    for t in brief["topics"]:
        sev_icon = _MD_ICON.get(t["highest_severity"], "?")
        clauses  = ", ".join(t["affected_clauses"])
        print(
            f"  {t['topic_label']:<24} {t['issue_count']:>6} "
            f"{sev_icon} {t['highest_severity']:<8}  {clauses}"
        )
    print(f"{'=' * 72}\n")


def main() -> None:
    args = _parse_args()

    proposals  = _load_json(args.remediation, "Stage 8 remediation proposals")
    compliance = _load_json(args.compliance,  "Stage 6 compliance report")

    obligations: list | None = None
    if args.obligations and Path(args.obligations).exists():
        with Path(args.obligations).open() as fh:
            obligations = json.load(fh)

    clauses: list | None = None
    if args.clauses and Path(args.clauses).exists():
        with Path(args.clauses).open() as fh:
            clauses = json.load(fh)

    clause_sr_matches: list | None = None
    p = Path(args.clause_matches)
    if p.exists():
        with p.open() as fh:
            data = json.load(fh)
        if isinstance(data, list):
            clause_sr_matches = data
    else:
        print(f"  [WARN] clause_sr_matches not found at {args.clause_matches} — "
              "SR evidence will not appear in Markdown.", file=sys.stderr)

    brief = build_brief(proposals, compliance, obligations, clause_sr_matches, clauses)

    with open(args.output, "w") as fh:
        json.dump(strip_internal(brief), fh, indent=2)

    md_content = generate_markdown(brief, proposals)
    with open(args.markdown, "w") as fh:
        fh.write(md_content)

    if not args.quiet:
        _print_summary(brief)

    print(f"  JSON  saved -> {args.output}")
    print(f"  MD    saved -> {args.markdown}\n")


if __name__ == "__main__":
    main()
