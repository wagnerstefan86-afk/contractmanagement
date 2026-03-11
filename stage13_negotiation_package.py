#!/usr/bin/env python3
"""
Stage 13 — Negotiation Package
================================
Reads:
  action_plan.json                  (Stage 12 — one action per finding group)
  contract_negotiation_brief.json   (Stage 9 — topic-level negotiation positions)
  audit_trace_CT-2026-001.json      (Stage 10 — original clause texts)
  risk_scoring.json                 (Stage 11 — SR match details per clause)
  stage8_remediation_proposals.json (Stage 8 — full suggested replacement clauses)

Produces one negotiation_item per action:
  negotiation_id              NEG-YYYY-NNN
  action_id                   reference to ACT-YYYY-NNN
  topic / priority
  affected_clauses            all clause IDs merged into this action
  problem_summary             from remediation proposal
  regulatory_basis            SR IDs + full regulation references
  risk_score_reference        per-clause scores from Stage 11
  current_clause_excerpt      original text(s) from audit trace
  recommended_clause_text     highest-severity stage8 proposal
  negotiation_argument        detailed (HIGH) or standard (MEDIUM)
  fallback_option             practical compromise position

Outputs:
  negotiation_package.json
  negotiation_package.md  (Executive Summary / Negotiation Items /
                           Clause Comparison / Regulatory References)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

# ── Regulatory reference catalogue ───────────────────────────────────────────

SR_CATALOGUE: dict[str, dict] = {
    "SR-NIS2-01": {
        "framework":   "NIS2",
        "regulation":  "Directive (EU) 2022/2555 (NIS2 Directive)",
        "article":     "Art. 23 — Reporting obligations for significant incidents",
        "obligation":  "Essential and important entities must notify the competent authority "
                       "of significant incidents without undue delay. This obligation is "
                       "personal to the regulated entity and cannot be contractually delegated.",
        "penalty":     "Administrative fines up to €10 M or 2 % of global annual turnover "
                       "(essential entities); up to €7 M / 1.4 % (important entities).",
    },
    "SR-DORA-02": {
        "framework":   "DORA",
        "regulation":  "Regulation (EU) 2022/2554 (DORA)",
        "article":     "Art. 19 — Reporting of major ICT-related incidents",
        "obligation":  "Financial entities must submit initial, intermediate, and final "
                       "reports on major ICT incidents directly to the competent authority. "
                       "Contractual assignment of this reporting obligation to an ICT "
                       "third-party provider is not permissible.",
        "penalty":     "Fines set by national competent authority; EBA / ESMA / EIOPA "
                       "may issue additional supervisory measures including temporary "
                       "prohibition of services.",
    },
    "SR-DORA-01": {
        "framework":   "DORA",
        "regulation":  "Regulation (EU) 2022/2554 (DORA)",
        "article":     "Art. 28 — General principles on sound management of ICT third-party risk",
        "obligation":  "ICT third-party service providers must support financial entities in "
                       "meeting DORA obligations. The financial entity (Customer) remains the "
                       "primary obligor and cannot transfer regulatory accountability.",
        "penalty":     "Non-compliance may trigger mandatory contractual termination clauses "
                       "under Art. 28(7) and enhanced supervisory scrutiny.",
    },
    "SR-ISO27001-03": {
        "framework":   "ISO27001",
        "regulation":  "ISO/IEC 27001:2022",
        "article":     "Annex A — Control 5.26: Response to information security incidents",
        "obligation":  "Organisations must establish, document, and implement a procedure "
                       "for responding to information security incidents, including defined "
                       "notification timelines proportionate to incident severity.",
        "penalty":     "Loss of ISO/IEC 27001 certification; contractual SLA breach exposure.",
    },
    "SR-GDPR-02": {
        "framework":   "GDPR",
        "regulation":  "Regulation (EU) 2016/679 (GDPR)",
        "article":     "Art. 4(7) controller definition · Art. 24 controller obligations · "
                       "Art. 28 processor obligations · Art. 35 DPIA",
        "obligation":  "The data controller (Customer) bears sole responsibility for "
                       "determining lawful bases for processing, conducting DPIAs, and "
                       "defining data retention periods. These cannot be assigned to the "
                       "data processor (Provider) by contract.",
        "penalty":     "Administrative fines up to €20 M or 4 % of global annual turnover "
                       "for Art. 5/6/9 violations; up to €10 M / 2 % for Art. 24/28.",
    },
}

# ── Negotiation argument templates ───────────────────────────────────────────
# Per (finding_type, priority) → callable(action, brief_positions, sr_refs) → str

def _arg_non_transferable_high(a: dict, pos: str, sr_refs: list[str]) -> str:
    clause_ids = ", ".join(a["affected_clauses"])
    sr_str     = " · ".join(sr_refs) if sr_refs else "no direct SR match"
    return (
        f"**Position: Reject transfer of regulatory reporting obligations. Replace with "
        f"Assistance Model.**\n\n"
        f"Clauses {clause_ids} purport to make the Provider the primary obligor toward "
        f"supervisory authorities for obligations that arise from the Customer's own "
        f"regulated status. This is legally untenable on three grounds:\n\n"
        f"1. **Regulatory non-transferability ({sr_str})**: The cited instruments "
        f"(NIS2 Art. 23, DORA Art. 19) impose incident-reporting duties directly on "
        f"essential entities and financial entities respectively. These obligations are "
        f"personal to the licensed / designated entity and cannot be reassigned by "
        f"private contract. Any contractual clause purporting to do so is unenforceable "
        f"as against the supervisory authority.\n\n"
        f"2. **Direct supervisory liability for the Provider**: Accepting primary obligor "
        f"status means the Provider faces direct regulatory fines — up to €10 M or 2 % "
        f"of global turnover under NIS2, and additional DORA sanctions — for reporting "
        f"failures that may originate from Customer-side operational decisions, access "
        f"restrictions, or delayed internal escalation, none of which the Provider "
        f"controls.\n\n"
        f"3. **Operational impossibility**: Meeting supervisory notification deadlines "
        f"(NIS2: 24 h initial / 72 h intermediate; DORA: 4 h initial / 24 h detailed) "
        f"requires full access to Customer-side incident triage, regulatory correspondence, "
        f"and decision-making chains. None of these are contractually guaranteed to the "
        f"Provider, making the obligation structurally unfulfillable.\n\n"
        f"{pos}\n\n"
        f"**Non-negotiable floor**: The Provider will not sign any clause that designates "
        f"it as direct reporting entity to BaFin, BSI, EBA, or any other supervisory "
        f"authority absent a separately executed, notarised power of attorney."
    )


def _arg_operational_risk_high(a: dict, pos: str, sr_refs: list[str]) -> str:
    clause_ids = ", ".join(a["affected_clauses"])
    sr_str     = " · ".join(sr_refs) if sr_refs else "no direct SR match"
    return (
        f"**Position: Replace infeasible obligations with a tiered SLA model aligned to "
        f"{sr_str}.**\n\n"
        f"Clauses {clause_ids} impose notification obligations (e.g. 'within 15 minutes', "
        f"'immediately') that are operationally unachievable and create automatic, "
        f"uncapped breach exposure:\n\n"
        f"1. **Technical impossibility**: A 15-minute wall-clock notification obligation "
        f"from first detection requires automated triaging, human escalation, and "
        f"customer notification to complete within a single human operational cycle. "
        f"Security operations centres operate on tiered alerting, with P1 (critical) "
        f"incidents typically declared after 15–30 minutes of investigation. Any earlier "
        f"notification would convey unverified noise rather than actionable intelligence.\n\n"
        f"2. **Severity-blind scope**: Applying the same '15 minutes' or 'immediate' "
        f"obligation to all incidents regardless of severity — from a failed login attempt "
        f"to a full data exfiltration — creates an undifferentiated, unmanageable "
        f"notification burden and renders the contractual SLA permanently in breach.\n\n"
        f"3. **Undefined notification recipients**: 'Immediately notify all affected "
        f"parties, relevant regulatory authorities, and any other stakeholders' is "
        f"unbounded. Combined with an immediate obligation, this exposes the Provider "
        f"to liability for every recipient and every timeline, including direct regulatory "
        f"authority notification (see ACT-2026-001 for separate treatment).\n\n"
        f"4. **ISO/IEC 27001:2022 Annex A Control 5.26** establishes a tiered incident "
        f"response model as best practice. The recommended clause adopts: "
        f"preliminary notification within 4 business hours, full report within 48 hours.\n\n"
        f"{pos}\n\n"
        f"**Non-negotiable floor**: Any numerical obligation of less than 4 business hours "
        f"for preliminary notification, or less than 48 hours for a full incident report, "
        f"is not commercially acceptable."
    )


def _arg_standard(a: dict, pos: str, sr_refs: list[str]) -> str:
    sr_str = " · ".join(sr_refs) if sr_refs else "no direct regulatory SR match on record"
    return (
        f"**Position**: {a['negotiation_guidance']}\n\n"
        f"Regulatory basis: {sr_str}.\n\n"
        f"{pos}"
    )


# finding_type × priority → argument factory
_ARG_FACTORY: dict[tuple[str, str], callable] = {
    ("NON_TRANSFERABLE_REGULATION", "HIGH"): _arg_non_transferable_high,
    ("OPERATIONAL_RISK",            "HIGH"): _arg_operational_risk_high,
}


def _negotiation_argument(action: dict, brief_positions: dict[str, str]) -> str:
    key      = (action["finding_type"], action["priority"])
    factory  = _ARG_FACTORY.get(key)
    sr_refs  = [
        f"{e['sr_id']} ({e['framework']})"
        for e in action.get("regulatory_evidence", [])
    ]
    topics   = action.get("topic", [])
    pos      = " | ".join(
        brief_positions.get(t, "") for t in topics if brief_positions.get(t)
    )
    if factory:
        return factory(action, pos, sr_refs)
    return _arg_standard(action, pos, sr_refs)


# ── Fallback options ──────────────────────────────────────────────────────────

FALLBACK: dict[str, str] = {
    "NON_TRANSFERABLE_REGULATION": (
        "If the Customer insists on some form of Provider involvement, accept an "
        "**Assistance and Notification Model** only: the Provider commits to "
        "(i) notifying the Customer within 4 business hours of incident declaration, "
        "(ii) delivering a full incident report within 48 hours, and "
        "(iii) supplying evidence and logs needed for the Customer to prepare its own "
        "regulatory filings. "
        "The Provider explicitly does NOT submit reports or make representations to "
        "any supervisory authority unless acting under a separately executed, duly "
        "notarised power of attorney."
    ),
    "OPERATIONAL_RISK": (
        "If 4 business hours is commercially rejected, accept a maximum fallback of "
        "**8 business hours** for preliminary notification, **24 hours** for a "
        "detailed incident summary, and **72 hours** for a full root-cause report — "
        "provided the obligation is tied to 'confirmed security incidents materially "
        "affecting Customer data' (not all alerts) and severity classification is "
        "mutually defined in an Incident Severity Schedule annexed to the contract."
    ),
    "CUSTOMER_RESPONSIBILITY": (
        "If the Customer insists the Provider 'assists' with classification, accept "
        "language under which the Provider provides a **technical data inventory** "
        "within 15 business days of a written request, describing processing operations "
        "and data categories. The Customer retains all classification decisions, lawful "
        "basis determinations, and DPIA obligations as data controller. The Provider's "
        "input is advisory only and does not constitute assumption of controller duties."
    ),
    "SCOPE_UNDEFINED": (
        "If the Customer refuses a Schedule [A], accept a clause that enumerates the "
        "four currently applicable frameworks directly in the body of the clause: "
        "GDPR (EU) 2016/679, DORA (EU) 2022/2554, NIS2 Directive 2022/2555, and "
        "ISO/IEC 27001:2022. Any future additions require 90 days' written notice and, "
        "if they impose material cost, trigger a fee-adjustment negotiation within 30 days."
    ),
    "AMBIGUOUS_REQUIREMENT": (
        "If the Customer refuses to name ISO/IEC 27001:2022 explicitly, accept "
        "'appropriate technical and organisational measures' **provided** the clause "
        "also states: 'For the purposes of this Agreement, compliance with ISO/IEC "
        "27001:2022, as evidenced by a valid third-party certification or a current "
        "Statement of Applicability signed by the Provider\\'s CISO, shall constitute "
        "fulfilment of this obligation.' This binds the standard by reference while "
        "preserving the Customer's preferred softer language."
    ),
}


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _load(path: str, label: str) -> object:
    p = Path(path)
    if not p.exists():
        print(f"  [ERROR] {label} not found: {path}", file=sys.stderr)
        sys.exit(1)
    with p.open() as f:
        return json.load(f)


# ── Core builder ──────────────────────────────────────────────────────────────

def build_package(
    action_plan: dict,
    brief:       dict,
    trace:       dict,
    scores:      dict,
    rem_list:    list[dict],
) -> dict:
    contract_id = action_plan["contract_id"]
    year        = date.today().year

    # ── Indexes ───────────────────────────────────────────────────────────────
    trace_idx: dict[str, dict] = {r["clause_id"]: r for r in trace["trace_records"]}
    score_idx: dict[str, dict] = {c["clause_id"]: c for c in scores["clause_scores"]}
    rem_idx:   dict[str, dict] = {r["clause_id"]: r for r in rem_list}

    # Brief: topic → negotiation_position
    brief_positions: dict[str, str] = {}
    brief_risk_summary: dict[str, str] = {}
    for t in brief.get("topics", []):
        brief_positions[t["topic"]]    = t.get("negotiation_position", "")
        brief_risk_summary[t["topic"]] = t.get("risk_summary", "")

    # ── Build items ───────────────────────────────────────────────────────────
    items: list[dict] = []

    for idx, action in enumerate(action_plan["actions"], start=1):
        neg_id     = f"NEG-{year}-{idx:03d}"
        action_id  = action["action_id"]
        clause_ids = action["affected_clauses"]
        finding    = action["finding_type"]
        priority   = action["priority"]
        topics     = action["topic"]

        # ── Current clause excerpts ──────────────────────────────────────────
        current_excerpts: list[dict] = []
        for cid in clause_ids:
            rec  = trace_idx.get(cid, {})
            text = rec.get("original_text_preview", "")
            current_excerpts.append({
                "clause_id": cid,
                "page":      rec.get("page"),
                "text":      text,
            })

        # ── Recommended clause (highest-severity stage8 proposal) ────────────
        # Action already picked the highest-severity one in stage12;
        # use suggested_contract_change directly (full text from rem_idx).
        # Choose the proposal whose severity is highest among affected clauses.
        rem_candidates = [rem_idx[c] for c in clause_ids if c in rem_idx]
        rem_candidates.sort(
            key=lambda r: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(r.get("severity", "LOW"), 99)
        )
        primary_rem = rem_candidates[0] if rem_candidates else {}
        recommended_text = primary_rem.get("suggested_clause", "")

        # ── Regulatory basis (full references) ───────────────────────────────
        reg_basis: list[dict] = []
        seen_sr: set[str] = set()
        for ev in action.get("regulatory_evidence", []):
            sr_id = ev["sr_id"]
            if sr_id not in seen_sr:
                cat = SR_CATALOGUE.get(sr_id, {})
                reg_basis.append({
                    "sr_id":        sr_id,
                    "framework":    ev["framework"],
                    "match_type":   ev["match_type"],
                    "confidence":   ev["confidence"],
                    "source_clause": ev.get("source_clause"),
                    "regulation":   cat.get("regulation", ""),
                    "article":      cat.get("article", ""),
                    "obligation":   cat.get("obligation", ""),
                    "penalty":      cat.get("penalty", ""),
                })
                seen_sr.add(sr_id)

        # ── Risk score reference ─────────────────────────────────────────────
        risk_ref: dict[str, float] = {
            cid: score_idx[cid]["risk_score"]
            for cid in clause_ids
            if cid in score_idx
        }

        # ── Argument + fallback ───────────────────────────────────────────────
        argument = _negotiation_argument(action, brief_positions)
        fallback = FALLBACK.get(finding, action.get("negotiation_guidance", ""))

        # ── Problem summary ───────────────────────────────────────────────────
        # Enrich with brief risk summary for the primary topic
        brief_ctx = brief_risk_summary.get(topics[0], "") if topics else ""
        problem   = action["remediation_summary"]
        if brief_ctx and brief_ctx not in problem:
            problem = f"{brief_ctx}\n\n**Finding detail**: {problem}"

        items.append({
            "negotiation_id":         neg_id,
            "action_id":              action_id,
            "topic":                  topics,
            "priority":               priority,
            "affected_clauses":       clause_ids,
            "finding_type":           finding,
            "finding_label":          action.get("finding_label", finding),
            "problem_summary":        problem,
            "regulatory_basis":       reg_basis,
            "risk_score_reference":   {
                "per_clause": risk_ref,
                "max_score":  round(max(risk_ref.values(), default=0.0), 2),
            },
            "current_clause_excerpts": current_excerpts,
            "recommended_clause_text": recommended_text,
            "negotiation_argument":   argument,
            "fallback_option":        fallback,
            "owner_role":             action.get("owner_role", ""),
            "estimated_effort":       action.get("estimated_effort", ""),
            "expected_risk_reduction": action.get("expected_risk_reduction", ""),
        })

    return {
        "contract_id":     contract_id,
        "generated_at":    date.today().isoformat(),
        "pipeline_stage":  "Stage 13 — Negotiation Package",
        "source_action_plan": action_plan.get("pipeline_stage", ""),
        "total_items":     len(items),
        "high_priority":   sum(1 for i in items if i["priority"] == "HIGH"),
        "medium_priority": sum(1 for i in items if i["priority"] == "MEDIUM"),
        "low_priority":    sum(1 for i in items if i["priority"] == "LOW"),
        "frameworks_referenced": sorted({
            rb["framework"] for item in items for rb in item["regulatory_basis"]
        }),
        "negotiation_items": items,
    }


# ── Markdown renderer ─────────────────────────────────────────────────────────

_PRI_ICON  = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
_MT_ICON   = {"DIRECT_MATCH": "✅", "PARTIAL_MATCH": "⚠️"}
_TOPIC_FMT = {
    "REGULATORY_COMPLIANCE": "Regulatory Compliance",
    "DATA_PROTECTION":       "Data Protection",
    "SECURITY_CONTROLS":     "Security Controls",
    "AUDIT_RIGHTS":          "Audit Rights",
    "INCIDENT_MANAGEMENT":   "Incident Management",
}


def _ft(t: str) -> str:
    return _TOPIC_FMT.get(t, t)


def generate_markdown(pkg: dict) -> str:
    ln: list[str] = []
    cid   = pkg["contract_id"]
    today = pkg["generated_at"]
    items = pkg["negotiation_items"]

    # ═══════════════════════════════════════════════════════════════════════
    # 1. HEADER
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        f"# Negotiation Package — {cid}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| **Contract** | `{cid}` |",
        f"| **Generated** | {today} |",
        f"| **Pipeline Stage** | {pkg['pipeline_stage']} |",
        f"| **Total Items** | {pkg['total_items']} |",
        f"| 🔴 HIGH | **{pkg['high_priority']}** |",
        f"| 🟡 MEDIUM | **{pkg['medium_priority']}** |",
        f"| 🟢 LOW | **{pkg['low_priority']}** |",
        f"| **Frameworks** | {' · '.join(f'`{f}`' for f in pkg['frameworks_referenced'])} |",
        "",
        "---",
        "",
    ]

    # ═══════════════════════════════════════════════════════════════════════
    # 2. EXECUTIVE SUMMARY
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        "## Executive Summary",
        "",
        "This negotiation package contains **all actionable remediation items** "
        f"derived from the Stage 11 risk scoring and Stage 12 action plan for contract "
        f"`{cid}`. Each item maps one-to-one to an action from `action_plan.json` and "
        "provides the legal team with:\n"
        "- the verbatim original clause text,\n"
        "- a ready-to-use replacement clause,\n"
        "- a structured negotiation argument (detailed for HIGH-priority items),\n"
        "- a fallback / compromise position, and\n"
        "- the full regulatory basis with article-level references.\n",
        "",
        "### Priority Overview",
        "",
        "| NEG ID | Action | Priority | Topic(s) | Clauses | Max Score | Owner |",
        "|---|---|:---:|---|---|:---:|---|",
    ]
    for it in items:
        icon    = _PRI_ICON.get(it["priority"], "")
        topics  = " / ".join(_ft(t) for t in it["topic"])
        clauses = " · ".join(f"`{c}`" for c in it["affected_clauses"])
        anchor  = it["negotiation_id"].lower().replace("-", "")
        ln.append(
            f"| [{it['negotiation_id']}](#{anchor}) "
            f"| `{it['action_id']}` "
            f"| {icon} **{it['priority']}** "
            f"| {topics} "
            f"| {clauses} "
            f"| **{it['risk_score_reference']['max_score']:.1f}** "
            f"| {it['owner_role']} |"
        )

    ln += [
        "",
        "### Key Risks",
        "",
    ]
    for it in items:
        if it["priority"] == "HIGH":
            icon   = _PRI_ICON["HIGH"]
            topics = " / ".join(_ft(t) for t in it["topic"])
            ln.append(
                f"- {icon} **{it['negotiation_id']}** ({topics}): "
                f"{it['finding_label']} — max risk score "
                f"**{it['risk_score_reference']['max_score']:.1f} / 10**."
            )

    ln += ["", "---", ""]

    # ═══════════════════════════════════════════════════════════════════════
    # 3. NEGOTIATION ITEMS
    # ═══════════════════════════════════════════════════════════════════════
    ln += ["## Negotiation Items", ""]

    for it in items:
        icon    = _PRI_ICON.get(it["priority"], "")
        topics  = " · ".join(f"`{_ft(t)}`" for t in it["topic"])
        clauses = " · ".join(f"`{c}`" for c in it["affected_clauses"])
        sr_ids  = " · ".join(
            f"`{rb['sr_id']}`" for rb in it["regulatory_basis"]
        ) or "—"
        anchor  = it["negotiation_id"].lower().replace("-", "")

        ln += [
            "---",
            "",
            f"### {it['negotiation_id']} — {it['finding_label']}",
            f"<a name=\"{anchor}\"></a>",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| **Negotiation ID** | `{it['negotiation_id']}` |",
            f"| **Action ID** | `{it['action_id']}` |",
            f"| **Priority** | {icon} **{it['priority']}** |",
            f"| **Topic(s)** | {topics} |",
            f"| **Affected Clauses** | {clauses} |",
            f"| **Finding Type** | `{it['finding_type']}` |",
            f"| **Regulatory Basis** | {sr_ids} |",
            f"| **Max Risk Score** | **{it['risk_score_reference']['max_score']:.1f}** / 10 |",
            f"| **Owner** | {it['owner_role']} |",
            f"| **Estimated Effort** | {it['estimated_effort']} |",
            f"| **Expected Reduction** | {it['expected_risk_reduction']} |",
            "",
        ]

        # Risk scores per clause
        ln += ["**Risk scores:**  ", ""]
        for cid_k, sc in it["risk_score_reference"]["per_clause"].items():
            ln.append(f"> `{cid_k}` → **{sc:.1f}** / 10")
        ln.append("")

        # Problem summary
        ln += [
            "#### Problem Summary",
            "",
            it["problem_summary"],
            "",
        ]

        # Negotiation argument
        ln += [
            "#### Negotiation Argument",
            "",
            it["negotiation_argument"],
            "",
        ]

        # Fallback option
        ln += [
            "#### Fallback / Compromise Position",
            "",
            it["fallback_option"],
            "",
        ]

    ln += ["", "---", ""]

    # ═══════════════════════════════════════════════════════════════════════
    # 4. CLAUSE COMPARISON
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        "## Clause Comparison — Original vs Proposed",
        "",
        "> Each section shows the verbatim original clause excerpt(s) "
        "followed by the recommended replacement clause.",
        "",
    ]

    for it in items:
        icon    = _PRI_ICON.get(it["priority"], "")
        clauses = " · ".join(f"`{c}`" for c in it["affected_clauses"])
        ln += [
            "---",
            "",
            f"### {it['negotiation_id']} · {icon} {it['priority']} · {clauses}",
            "",
        ]

        for exc in it["current_clause_excerpts"]:
            ln += [
                f"#### Current — `{exc['clause_id']}` (p. {exc['page']})",
                "",
                "```",
                exc["text"].strip() if exc["text"] else "[text not available]",
                "```",
                "",
            ]

        ln += [
            "#### Proposed Replacement Clause",
            "",
            "```",
            it["recommended_clause_text"].strip() if it["recommended_clause_text"]
            else "[no replacement clause available — manual drafting required]",
            "```",
            "",
        ]

    ln += ["", "---", ""]

    # ═══════════════════════════════════════════════════════════════════════
    # 5. REGULATORY REFERENCES
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        "## Regulatory References",
        "",
        "All SR identifiers referenced in this package with their full "
        "regulation citations and key obligations.",
        "",
    ]

    # Collect all unique SR IDs across all items, in appearance order
    seen_sr: set[str] = set()
    ordered_sr: list[dict] = []
    for it in items:
        for rb in it["regulatory_basis"]:
            if rb["sr_id"] not in seen_sr:
                ordered_sr.append(rb)
                seen_sr.add(rb["sr_id"])

    if not ordered_sr:
        ln.append(
            "> ⚪ No regulatory SR matches on record for any item in this package.\n"
        )
    else:
        for rb in ordered_sr:
            cat = SR_CATALOGUE.get(rb["sr_id"], {})
            icon_m = _MT_ICON.get(rb["match_type"], "?")
            ln += [
                f"### `{rb['sr_id']}` — {rb['framework']}",
                "",
                "| Field | Value |",
                "|---|---|",
                f"| **SR ID** | `{rb['sr_id']}` |",
                f"| **Regulation** | {cat.get('regulation', rb['framework'])} |",
                f"| **Article / Control** | {cat.get('article', '—')} |",
                f"| **Match Type** | {icon_m} {rb['match_type']} · {rb['confidence']}% confidence |",
                f"| **Source Clause** | `{rb.get('source_clause', '—')}` |",
                "",
                f"**Key obligation**: {cat.get('obligation', '—')}",
                "",
                f"**Enforcement / Penalties**: {cat.get('penalty', '—')}",
                "",
            ]

    # Summary table
    ln += [
        "---",
        "",
        "### SR Reference Summary",
        "",
        "| SR ID | Framework | Regulation | Article | Match | Used in |",
        "|---|---|---|---|:---:|---|",
    ]
    for rb in ordered_sr:
        cat   = SR_CATALOGUE.get(rb["sr_id"], {})
        icon_m = _MT_ICON.get(rb["match_type"], "?")
        # Which NEG IDs reference this SR?
        used_in = [
            it["negotiation_id"]
            for it in items
            if any(e["sr_id"] == rb["sr_id"] for e in it["regulatory_basis"])
        ]
        ln.append(
            f"| `{rb['sr_id']}` | **{rb['framework']}** "
            f"| {cat.get('regulation', '—')[:45]}… "
            f"| {cat.get('article', '—')[:40]}… "
            f"| {icon_m} {rb['confidence']}% "
            f"| {' · '.join(f'`{n}`' for n in used_in)} |"
        )

    ln += [""]
    return "\n".join(ln)


# ── Terminal summary ──────────────────────────────────────────────────────────

def _print_summary(pkg: dict) -> None:
    SEP = "-" * 82
    print("=" * 82)
    print(f"  STAGE 13 — NEGOTIATION PACKAGE  |  {pkg['contract_id']}")
    print("=" * 82)
    print(f"  Total items      : {pkg['total_items']}")
    print(f"  🔴 HIGH           : {pkg['high_priority']}")
    print(f"  🟡 MEDIUM         : {pkg['medium_priority']}")
    print(f"  Frameworks        : {', '.join(pkg['frameworks_referenced'])}")
    print(SEP)
    print(f"  {'NEG ID':<15} {'ACTION':<15} {'PRI':<10} {'CLAUSES':<22}  SCORE")
    print(SEP)
    for it in pkg["negotiation_items"]:
        icon    = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(it["priority"], " ")
        clauses = " ".join(it["affected_clauses"])
        score   = it["risk_score_reference"]["max_score"]
        print(
            f"  {it['negotiation_id']:<15} {it['action_id']:<15} "
            f"{icon} {it['priority']:<8} {clauses:<22}  {score:.1f}"
        )
        sr_ids = [rb["sr_id"] for rb in it["regulatory_basis"]]
        if sr_ids:
            print(f"  {'':>15}  {'':>15}  SR: {', '.join(sr_ids)}")
    print("=" * 82)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Stage 13: Generate negotiation package."
    )
    ap.add_argument("--plan",        "-p", default="action_plan.json")
    ap.add_argument("--brief",       "-b", default="contract_negotiation_brief.json")
    ap.add_argument("--trace",       "-t", default="audit_trace_CT-2026-001.json")
    ap.add_argument("--scores",      "-s", default="risk_scoring.json")
    ap.add_argument("--remediation", "-r", default="stage8_remediation_proposals.json")
    ap.add_argument("--output",      "-o", default="negotiation_package.json")
    ap.add_argument("--markdown",    "-m", default="negotiation_package.md")
    ap.add_argument("--quiet",       "-q", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = _args()

    plan    = _load(args.plan,        "Stage 12 action plan")
    brief   = _load(args.brief,       "Stage 9 negotiation brief")
    trace   = _load(args.trace,       "Stage 10 audit trace")
    scores  = _load(args.scores,      "Stage 11 risk scoring")
    rem_raw = _load(args.remediation, "Stage 8 remediation proposals")

    pkg = build_package(plan, brief, trace, scores, rem_raw)

    with open(args.output, "w") as f:
        json.dump(pkg, f, indent=2)
    print(f"  JSON saved  -> {args.output}", file=sys.stderr)

    md = generate_markdown(pkg)
    with open(args.markdown, "w") as f:
        f.write(md)
    print(f"  MD   saved  -> {args.markdown}", file=sys.stderr)

    if not args.quiet:
        _print_summary(pkg)

    sys.exit(0 if pkg["high_priority"] == 0 else 1)


if __name__ == "__main__":
    main()
