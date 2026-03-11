#!/usr/bin/env python3
"""
Stage 12 — Consolidated Remediation Action Plan
=================================================
Reads:
  audit_trace_CT-2026-001.json      (obligations, SR matches, pages)
  contract_negotiation_brief.json   (topics, findings, regulatory context)
  risk_scoring.json                 (per-clause scores, priorities)
  stage8_remediation_proposals.json (problem summaries, suggested clauses)

Merging rule:
  Clauses sharing the same finding_type receive one merged action.
  Priority of a merged action = highest priority among its clauses.
  VALID clauses are excluded.

Outputs:
  action_plan.json  – structured action records
  action_plan.md    – narrative Markdown with all required sections
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

# ── Lookup tables ─────────────────────────────────────────────────────────────

# Owner role by topic (first topic wins for merged multi-topic actions)
OWNER_ROLE: dict[str, str] = {
    "REGULATORY_COMPLIANCE": "Legal / Compliance Officer",
    "DATA_PROTECTION":       "Data Protection Officer (DPO)",
    "SECURITY_CONTROLS":     "CISO / Security Officer",
    "AUDIT_RIGHTS":          "Legal / Compliance Officer",
    "INCIDENT_MANAGEMENT":   "CISO / Security Officer",
    "SERVICE_LEVELS":        "Service Delivery Manager",
}

# Effort estimate by action priority
EFFORT: dict[str, str] = {
    "HIGH":   "3–5 business days",
    "MEDIUM": "1–2 business days",
    "LOW":    "< 1 business day",
}

# Priority order for sorting / comparison
PRI_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

# Human-readable label for finding types
FINDING_LABEL: dict[str, str] = {
    "NON_TRANSFERABLE_REGULATION": "Non-transferable regulatory obligation",
    "SCOPE_UNDEFINED":             "Undefined regulatory scope",
    "OPERATIONAL_RISK":            "Operationally unrealistic obligation",
    "CUSTOMER_RESPONSIBILITY":     "Misassigned controller responsibility",
    "AMBIGUOUS_REQUIREMENT":       "Vague / unmeasurable requirement",
}

# Expected risk reduction narrative per priority
RISK_REDUCTION: dict[str, str] = {
    "HIGH":   "Eliminates direct regulatory exposure; expected clause score ≤ 3.0 post-remediation.",
    "MEDIUM": "Removes ambiguity and scope gaps; expected clause score ≤ 2.5 post-remediation.",
    "LOW":    "Clarificatory change; negligible score impact.",
}

# ── I/O helpers ───────────────────────────────────────────────────────────────

def _load(path: str, label: str) -> object:
    p = Path(path)
    if not p.exists():
        print(f"  [ERROR] {label} not found: {path}", file=sys.stderr)
        sys.exit(1)
    with p.open() as f:
        return json.load(f)


def _max_priority(*priorities: str) -> str:
    return min(priorities, key=lambda p: PRI_ORDER.get(p, 99))


# ── Core builder ──────────────────────────────────────────────────────────────

def build_action_plan(
    trace:  dict,
    brief:  dict,
    scores: dict,
    rem_list: list[dict],
) -> dict:
    contract_id = trace.get("contract_id", "UNKNOWN")

    # ── Index inputs ──────────────────────────────────────────────────────────
    trace_idx: dict[str, dict] = {r["clause_id"]: r for r in trace["trace_records"]}
    score_idx: dict[str, dict] = {c["clause_id"]: c for c in scores["clause_scores"]}
    rem_idx:   dict[str, dict] = {r["clause_id"]: r for r in rem_list}

    # Build SR evidence index from brief findings
    brief_sr: dict[str, list[dict]] = defaultdict(list)
    for topic_sec in brief.get("topics", []):
        for fi in topic_sec.get("findings", []):
            cid = fi.get("clause_id") or fi.get("matched_clause_id")
            if cid:
                brief_sr[cid].append({
                    "topic":    topic_sec["topic"],
                    "finding":  fi,
                })

    # ── Group non-VALID clauses by finding_type ───────────────────────────────
    groups: dict[str, list[str]] = defaultdict(list)    # finding_type → [clause_id]
    for clause_id, rec in trace_idx.items():
        obligation = rec.get("obligation_assessment", "VALID")
        if obligation == "VALID":
            continue
        groups[obligation].append(clause_id)

    # ── Build one action per group ────────────────────────────────────────────
    actions: list[dict] = []

    # Sort groups: HIGH-containing groups first
    def _group_priority(finding_type: str) -> tuple:
        clause_ids = groups[finding_type]
        priorities = [score_idx[c]["priority"] for c in clause_ids if c in score_idx]
        best = _max_priority(*priorities) if priorities else "LOW"
        return (PRI_ORDER.get(best, 99), finding_type)

    for finding_type in sorted(groups, key=_group_priority):
        clause_ids = sorted(groups[finding_type])   # stable ordering

        # ── Gather per-clause data ─────────────────────────────────────────
        scored_clauses = [score_idx[c] for c in clause_ids if c in score_idx]
        topics_seen:  list[str] = []
        seen_set:     set[str]  = set()
        for sc in scored_clauses:
            t = sc.get("topic")
            if t and t not in seen_set:
                topics_seen.append(t)
                seen_set.add(t)

        action_priority = _max_priority(*(sc["priority"] for sc in scored_clauses))

        risk_ref: dict[str, float] = {
            sc["clause_id"]: sc["risk_score"] for sc in scored_clauses
        }
        max_score   = max(risk_ref.values(), default=0.0)
        total_score = round(sum(risk_ref.values()), 2)

        # ── SR evidence ───────────────────────────────────────────────────
        sr_evidence: list[dict] = []
        seen_sr: set[str] = set()
        for cid in clause_ids:
            for m in trace_idx[cid].get("regulatory_matches", []):
                key = m["sr_id"]
                if key not in seen_sr:
                    sr_evidence.append({
                        "sr_id":       m["sr_id"],
                        "framework":   m["framework"],
                        "match_type":  m["match_type"],
                        "confidence":  round(m.get("match_confidence", 0.0) * 100),
                        "source_clause": cid,
                    })
                    seen_sr.add(key)

        # ── Remediation content (merge text from proposals) ───────────────
        # Prefer the highest-severity proposal for the main texts
        rem_records = [rem_idx[c] for c in clause_ids if c in rem_idx]
        rem_records.sort(
            key=lambda r: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(r.get("severity", "LOW"), 99)
        )
        primary_rem = rem_records[0] if rem_records else {}

        problem_parts:  list[str] = []
        guidance_parts: list[str] = []
        seen_probs: set[str] = set()
        for r in rem_records:
            prob = r.get("problem_summary", "").strip()
            guid = r.get("negotiation_guidance", "").strip()
            if prob and prob not in seen_probs:
                problem_parts.append(prob)
                seen_probs.add(prob)
            if guid and guid not in seen_probs:
                guidance_parts.append(guid)
                seen_probs.add(guid)

        problem_summary    = " | ".join(problem_parts) if problem_parts else "See finding type."
        negotiation_guidance = " | ".join(guidance_parts) if guidance_parts else ""
        suggested_clause   = primary_rem.get("suggested_clause", "")

        # ── Owner role ────────────────────────────────────────────────────
        primary_topic = topics_seen[0] if topics_seen else "OTHER"
        owner = OWNER_ROLE.get(primary_topic, "Legal / Compliance Officer")

        # Secondary owner if multi-topic spans different domains
        secondary_topics = topics_seen[1:] if len(topics_seen) > 1 else []
        secondary_owners = list(dict.fromkeys(
            OWNER_ROLE.get(t, "") for t in secondary_topics
            if OWNER_ROLE.get(t, "") and OWNER_ROLE.get(t, "") != owner
        ))

        actions.append({
            "action_id":               None,   # assigned after sort
            "finding_type":            finding_type,
            "finding_label":           FINDING_LABEL.get(finding_type, finding_type),
            "topic":                   topics_seen,
            "priority":                action_priority,
            "affected_clauses":        clause_ids,
            "affected_pages":          sorted({
                trace_idx[c].get("page") for c in clause_ids
                if trace_idx[c].get("page") is not None
            }),
            "risk_score_reference":    {
                "per_clause":   risk_ref,
                "max_score":    round(max_score, 2),
                "total_score":  total_score,
                "scoring_run":  scores.get("generated_at"),
            },
            "remediation_summary":     problem_summary,
            "negotiation_guidance":    negotiation_guidance,
            "suggested_contract_change": suggested_clause,
            "regulatory_evidence":     sr_evidence,
            "owner_role":              owner,
            "secondary_owners":        secondary_owners,
            "estimated_effort":        EFFORT.get(action_priority, "TBD"),
            "expected_risk_reduction": RISK_REDUCTION.get(action_priority, ""),
            "merged_from_count":       len(clause_ids),
        })

    # Sort: HIGH first, then by max_score desc, then clause_id for stability
    actions.sort(key=lambda a: (
        PRI_ORDER.get(a["priority"], 99),
        -a["risk_score_reference"]["max_score"],
        a["finding_type"],
    ))

    # Assign sequential IDs now that order is final
    year = date.today().year
    for i, a in enumerate(actions, start=1):
        a["action_id"] = f"ACT-{year}-{i:03d}"

    high   = sum(1 for a in actions if a["priority"] == "HIGH")
    medium = sum(1 for a in actions if a["priority"] == "MEDIUM")
    low    = sum(1 for a in actions if a["priority"] == "LOW")

    return {
        "contract_id":     contract_id,
        "generated_at":    date.today().isoformat(),
        "pipeline_stage":  "Stage 12 — Remediation Action Plan",
        "total_actions":   len(actions),
        "high_priority":   high,
        "medium_priority": medium,
        "low_priority":    low,
        "excluded_valid_clauses": [
            c for c, r in trace_idx.items()
            if r.get("obligation_assessment") == "VALID"
        ],
        "actions": actions,
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
    "SERVICE_LEVELS":        "Service Levels",
}


def _fmt_topic(t: str) -> str:
    return _TOPIC_FMT.get(t, t)


def generate_markdown(plan: dict) -> str:
    ln: list[str] = []
    cid   = plan["contract_id"]
    today = plan["generated_at"]

    # ── Header ────────────────────────────────────────────────────────────────
    ln += [
        f"# Remediation Action Plan — {cid}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| **Contract** | `{cid}` |",
        f"| **Generated** | {today} |",
        f"| **Pipeline Stage** | {plan['pipeline_stage']} |",
        f"| **Total Actions** | {plan['total_actions']} |",
        f"| 🔴 HIGH Priority | **{plan['high_priority']}** |",
        f"| 🟡 MEDIUM Priority | **{plan['medium_priority']}** |",
        f"| 🟢 LOW Priority | **{plan['low_priority']}** |",
        f"| Excluded (VALID) | {', '.join(f'`{c}`' for c in plan['excluded_valid_clauses'])} |",
        "",
        "---",
        "",
    ]

    # ── Executive summary table ───────────────────────────────────────────────
    ln += [
        "## Executive Summary",
        "",
        "| Action | Priority | Topic(s) | Clauses | Max Score | Owner |",
        "|---|:---:|---|---|:---:|---|",
    ]
    for a in plan["actions"]:
        icon    = _PRI_ICON.get(a["priority"], "")
        topics  = " / ".join(_fmt_topic(t) for t in a["topic"])
        clauses = ", ".join(f"`{c}`" for c in a["affected_clauses"])
        ln.append(
            f"| [{a['action_id']}](#{a['action_id'].lower().replace('-','')}) "
            f"| {icon} **{a['priority']}** "
            f"| {topics} "
            f"| {clauses} "
            f"| **{a['risk_score_reference']['max_score']:.1f}** "
            f"| {a['owner_role']} |"
        )

    ln += ["", "---", ""]

    # ── Per-action detail cards ───────────────────────────────────────────────
    ln += ["## Action Detail Cards", ""]

    for a in plan["actions"]:
        icon    = _PRI_ICON.get(a["priority"], "")
        topics  = " · ".join(f"`{_fmt_topic(t)}`" for t in a["topic"])
        clauses = ", ".join(f"`{c}`" for c in a["affected_clauses"])
        pages   = ", ".join(str(p) for p in a["affected_pages"])

        ln += [
            f"---",
            f"",
            f"### {a['action_id']} — {a['finding_label']}",
            f"",
            f"| Field | Value |",
            f"|---|---|",
            f"| **Action ID** | `{a['action_id']}` |",
            f"| **Priority** | {icon} **{a['priority']}** |",
            f"| **Topic(s)** | {topics} |",
            f"| **Affected Clauses** | {clauses} |",
            f"| **Contract Pages** | {pages} |",
            f"| **Finding Type** | `{a['finding_type']}` |",
            f"| **Max Risk Score** | **{a['risk_score_reference']['max_score']:.1f}** / 10 |",
            f"| **Responsible Owner** | {a['owner_role']} |",
        ]
        if a["secondary_owners"]:
            ln.append(f"| **Secondary Owner(s)** | {' · '.join(a['secondary_owners'])} |")
        ln += [
            f"| **Estimated Effort** | {a['estimated_effort']} |",
            f"| **Expected Risk Reduction** | {a['expected_risk_reduction']} |",
            f"| **Merged Clauses** | {a['merged_from_count']} |",
            "",
        ]

        # Risk scores per clause
        ln += ["**Risk scores by clause:**", ""]
        for cid_k, sc in a["risk_score_reference"]["per_clause"].items():
            ln.append(f"> `{cid_k}` → **{sc:.1f}** / 10")
        ln.append("")

        # Problem description
        ln += [
            "#### Problem Description",
            "",
            a["remediation_summary"],
            "",
        ]

        # Regulatory evidence
        if a["regulatory_evidence"]:
            ln += ["#### Regulatory Evidence", ""]
            ln += [
                "| SR ID | Framework | Match Type | Confidence | Source Clause |",
                "|---|---|---|:---:|---|",
            ]
            for ev in a["regulatory_evidence"]:
                icon_ev = _MT_ICON.get(ev["match_type"], "?")
                ln.append(
                    f"| `{ev['sr_id']}` | **{ev['framework']}** "
                    f"| {icon_ev} {ev['match_type']} "
                    f"| {ev['confidence']}% "
                    f"| `{ev['source_clause']}` |"
                )
            ln.append("")
        else:
            ln += [
                "#### Regulatory Evidence",
                "",
                "> ⚪ No direct SR match on record — clause flagged as unknown-gap "
                "(NO_MATCH floor applied in risk scoring).",
                "",
            ]

        # Negotiation guidance
        if a["negotiation_guidance"]:
            ln += [
                "#### Negotiation Guidance",
                "",
                a["negotiation_guidance"],
                "",
            ]

        # Recommended clause change
        if a["suggested_contract_change"]:
            ln += [
                "#### Recommended Clause Change",
                "",
                "```",
                a["suggested_contract_change"],
                "```",
                "",
            ]
        else:
            ln += [
                "#### Recommended Clause Change",
                "",
                "> No proposed clause text available — manual drafting required.",
                "",
            ]

    ln += ["---", "", "## Appendix: Excluded Clauses (VALID)", ""]
    for c in plan["excluded_valid_clauses"]:
        ln.append(f"- `{c}` — obligation assessment: **VALID** · no remediation required")
    ln += [""]

    return "\n".join(ln)


# ── Terminal summary ──────────────────────────────────────────────────────────

def _print_summary(plan: dict) -> None:
    SEP = "-" * 80
    print("=" * 80)
    print(f"  STAGE 12 — ACTION PLAN  |  {plan['contract_id']}")
    print("=" * 80)
    print(f"  Total actions   : {plan['total_actions']}")
    print(f"  🔴 HIGH          : {plan['high_priority']}")
    print(f"  🟡 MEDIUM        : {plan['medium_priority']}")
    print(f"  🟢 LOW           : {plan['low_priority']}")
    print(f"  Excluded (VALID) : {', '.join(plan['excluded_valid_clauses'])}")
    print(SEP)
    print(f"  {'ACTION':<18} {'PRI':<10} {'CLAUSES':<22} {'SCORE':>6}  OWNER")
    print(SEP)
    for a in plan["actions"]:
        icon    = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(a["priority"], " ")
        clauses = " ".join(a["affected_clauses"])
        print(
            f"  {a['action_id']:<18} {icon} {a['priority']:<8} "
            f"{clauses:<22} {a['risk_score_reference']['max_score']:>6.1f}  "
            f"{a['owner_role']}"
        )
    print("=" * 80)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Stage 12: Generate consolidated remediation action plan."
    )
    ap.add_argument("--trace",       "-t", default="audit_trace_CT-2026-001.json")
    ap.add_argument("--brief",       "-b", default="contract_negotiation_brief.json")
    ap.add_argument("--scores",      "-s", default="risk_scoring.json")
    ap.add_argument("--remediation", "-r", default="stage8_remediation_proposals.json")
    ap.add_argument("--output",      "-o", default="action_plan.json")
    ap.add_argument("--markdown",    "-m", default="action_plan.md")
    ap.add_argument("--quiet",       "-q", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = _args()

    trace   = _load(args.trace,       "Stage 10 audit trace")
    brief   = _load(args.brief,       "Stage 9 negotiation brief")
    scores  = _load(args.scores,      "Stage 11 risk scoring")
    rem_raw = _load(args.remediation, "Stage 8 remediation proposals")

    plan = build_action_plan(trace, brief, scores, rem_raw)

    with open(args.output, "w") as f:
        json.dump(plan, f, indent=2)
    print(f"  JSON saved  -> {args.output}", file=sys.stderr)

    md = generate_markdown(plan)
    with open(args.markdown, "w") as f:
        f.write(md)
    print(f"  MD   saved  -> {args.markdown}", file=sys.stderr)

    if not args.quiet:
        _print_summary(plan)

    sys.exit(0 if plan["high_priority"] == 0 else 1)


if __name__ == "__main__":
    main()
