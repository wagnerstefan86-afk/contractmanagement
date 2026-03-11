#!/usr/bin/env python3
"""
Stage 14 — Contract Risk Report
=================================
Consolidates risk_scoring, action_plan, negotiation_package,
audit_trace, and negotiation_brief into a standalone management
and audit report.

Outputs
  contract_risk_report.json  — structured, machine-readable
  contract_risk_report.md    — human-readable, standalone document

Markdown sections
  1. Executive Summary
  2. Risk Distribution       (non-VALID clauses only)
  3. Top Risk Areas          (topic-level aggregation)
  4. Regulatory Exposure     (SR ID → clauses → NEG items)
  5. Action Plan Overview    (all actions)
  6. Negotiation Priorities  (HIGH NEG items only)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

# ── Lookup tables ─────────────────────────────────────────────────────────────

TOPIC_LABEL: dict[str, str] = {
    "REGULATORY_COMPLIANCE": "Regulatory Compliance",
    "DATA_PROTECTION":       "Data Protection",
    "SECURITY_CONTROLS":     "Security Controls",
    "AUDIT_RIGHTS":          "Audit Rights",
    "INCIDENT_MANAGEMENT":   "Incident Management",
    "SERVICE_LEVELS":        "Service Levels",
    "VALID":                 "—",
}

FRAMEWORK_FULL: dict[str, str] = {
    "NIS2":     "Directive (EU) 2022/2555 (NIS2)",
    "DORA":     "Regulation (EU) 2022/2554 (DORA)",
    "GDPR":     "Regulation (EU) 2016/679 (GDPR)",
    "ISO27001": "ISO/IEC 27001:2022",
}

SR_ARTICLE: dict[str, str] = {
    "SR-NIS2-01":     "Art. 23 — Reporting obligations",
    "SR-DORA-02":     "Art. 19 — Major ICT incident reporting",
    "SR-DORA-01":     "Art. 28 — ICT third-party risk management",
    "SR-ISO27001-03": "Annex A Control 5.26 — Incident response",
    "SR-GDPR-02":     "Art. 4(7)/24/28/35 — Controller/processor duties",
}

PRI_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
PRI_ICON  = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}

# ── I/O ───────────────────────────────────────────────────────────────────────

def _load(path: str, label: str) -> object:
    p = Path(path)
    if not p.exists():
        print(f"  [ERROR] {label} not found: {path}", file=sys.stderr)
        sys.exit(1)
    with p.open() as f:
        return json.load(f)

# ── Cross-index builder ───────────────────────────────────────────────────────

def _build_indexes(
    scores:  dict,
    plan:    dict,
    pkg:     dict,
) -> tuple[dict, dict, dict]:
    """
    Returns:
      clause_to_action  dict[clause_id → action_id]
      clause_to_neg     dict[clause_id → neg_id]
      sr_index          dict[sr_id → {regulation, article, clauses, neg_ids}]
    """
    clause_to_action: dict[str, str] = {}
    for a in plan["actions"]:
        for cid in a["affected_clauses"]:
            clause_to_action[cid] = a["action_id"]

    clause_to_neg: dict[str, str] = {}
    for ni in pkg["negotiation_items"]:
        for cid in ni["affected_clauses"]:
            clause_to_neg[cid] = ni["negotiation_id"]

    # SR index — seed from score sr_matches, then enrich from NEG regulatory_basis
    sr_index: dict[str, dict] = {}

    for cs in scores["clause_scores"]:
        for m in cs["sr_matches"]:
            sid = m["sr_id"]
            if sid not in sr_index:
                sr_index[sid] = {
                    "sr_id":      sid,
                    "framework":  m["framework"],
                    "regulation": FRAMEWORK_FULL.get(m["framework"], m["framework"]),
                    "article":    SR_ARTICLE.get(sid, ""),
                    "match_type": m["match_type"],
                    "confidence": m["confidence"],
                    "clauses":    [],
                    "neg_ids":    [],
                }
            if cs["clause_id"] not in sr_index[sid]["clauses"]:
                sr_index[sid]["clauses"].append(cs["clause_id"])

    for ni in pkg["negotiation_items"]:
        for rb in ni["regulatory_basis"]:
            sid = rb["sr_id"]
            if sid not in sr_index:
                sr_index[sid] = {
                    "sr_id":      sid,
                    "framework":  rb["framework"],
                    "regulation": FRAMEWORK_FULL.get(rb["framework"], rb["framework"]),
                    "article":    SR_ARTICLE.get(sid, rb.get("article", "")),
                    "match_type": rb["match_type"],
                    "confidence": rb["confidence"],
                    "clauses":    [],
                    "neg_ids":    [],
                }
            if ni["negotiation_id"] not in sr_index[sid]["neg_ids"]:
                sr_index[sid]["neg_ids"].append(ni["negotiation_id"])
            for cid in ni["affected_clauses"]:
                if cid not in sr_index[sid]["clauses"]:
                    sr_index[sid]["clauses"].append(cid)

    return clause_to_action, clause_to_neg, sr_index

# ── Core builder ──────────────────────────────────────────────────────────────

def build_report(
    scores: dict,
    plan:   dict,
    pkg:    dict,
    trace:  dict,
    brief:  dict,
) -> dict:
    contract_id = scores["contract_id"]

    clause_to_action, clause_to_neg, sr_index = _build_indexes(scores, plan, pkg)

    # Brief topic index
    brief_topics: dict[str, dict] = {t["topic"]: t for t in brief["topics"]}

    # ── 1. Metadata / Executive Summary ──────────────────────────────────────
    trace_recs  = trace["trace_records"]
    total_cls   = len(trace_recs)
    valid_cls   = [r for r in trace_recs if r["obligation_assessment"] == "VALID"]
    finding_cls = [r for r in trace_recs if r["obligation_assessment"] != "VALID"]

    high_cls    = sum(1 for c in scores["clause_scores"] if c["priority"] == "HIGH")
    medium_cls  = sum(1 for c in scores["clause_scores"] if c["priority"] == "MEDIUM")
    low_cls     = sum(1 for c in scores["clause_scores"] if c["priority"] == "LOW")

    # Overall risk: highest priority present
    overall_risk = (
        "HIGH"   if high_cls > 0 else
        "MEDIUM" if medium_cls > 0 else
        "LOW"
    )

    metadata = {
        "contract_id":                   contract_id,
        "organization":                  brief.get("organization", ""),
        "generated_at":                  date.today().isoformat(),
        "overall_risk":                  overall_risk,
        "frameworks_in_scope":           brief.get("frameworks", []),
        "total_clauses":                 total_cls,
        "valid_clauses":                 len(valid_cls),
        "total_findings":                len(finding_cls),
        "high_risk_clauses":             high_cls,
        "medium_risk_clauses":           medium_cls,
        "low_risk_clauses":              low_cls - len(valid_cls),   # LOW non-VALID
        "total_actions":                 plan["total_actions"],
        "high_priority_actions":         plan["high_priority"],
        "medium_priority_actions":       plan["medium_priority"],
        "total_negotiation_items":       pkg["total_items"],
        "high_priority_negotiation":     pkg["high_priority"],
        "medium_priority_negotiation":   pkg["medium_priority"],
        "unique_sr_ids":                 len(sr_index),
    }

    # ── 2. Risk Distribution — non-VALID only ─────────────────────────────────
    risk_distribution = []
    for cs in scores["clause_scores"]:
        if cs["obligation"] == "VALID":
            continue
        risk_distribution.append({
            "clause_id":        cs["clause_id"],
            "page":             cs["page"],
            "topic":            cs["topic"],
            "obligation":       cs["obligation"],
            "severity":         cs["severity"],
            "risk_score":       cs["risk_score"],
            "priority":         cs["priority"],
            "sr_match_count":   len(cs["sr_matches"]),
            "linked_action":    clause_to_action.get(cs["clause_id"], "—"),
            "linked_neg_item":  clause_to_neg.get(cs["clause_id"], "—"),
            "text_preview":     cs["text_preview"][:120] + "…"
                                if len(cs.get("text_preview", "")) > 120
                                else cs.get("text_preview", ""),
        })

    # ── 3. Top Risk Areas — from topic_summary (exclude VALID bucket) ─────────
    top_risk_areas = []
    for ts in scores["topic_summary"]:
        if ts["topic"] == "VALID":
            continue
        related_actions = sorted({
            clause_to_action[cid]
            for cs in scores["clause_scores"]
            if cs["topic"] == ts["topic"]
            and cs["obligation"] != "VALID"
            for cid in [cs["clause_id"]]
            if cid in clause_to_action
        })
        bt = brief_topics.get(ts["topic"], {})
        top_risk_areas.append({
            "topic":           ts["topic"],
            "topic_label":     TOPIC_LABEL.get(ts["topic"], ts["topic"]),
            "clause_count":    ts["clause_count"],
            "max_score":       ts["max_score"],
            "avg_score":       ts["avg_score"],
            "priority":        ts["priority"],
            "related_actions": related_actions,
            "risk_summary":    bt.get("risk_summary", ""),
        })

    # ── 4. Regulatory Exposure ────────────────────────────────────────────────
    regulatory_exposure = sorted(
        sr_index.values(),
        key=lambda x: (-len(x["clauses"]), x["sr_id"]),
    )

    # ── 5. Action Plan Overview ───────────────────────────────────────────────
    action_overview = []
    for a in plan["actions"]:
        action_overview.append({
            "action_id":              a["action_id"],
            "priority":               a["priority"],
            "finding_type":           a["finding_type"],
            "finding_label":          a.get("finding_label", a["finding_type"]),
            "topic":                  a["topic"],
            "affected_clauses":       a["affected_clauses"],
            "owner_role":             a["owner_role"],
            "estimated_effort":       a["estimated_effort"],
            "expected_risk_reduction": a["expected_risk_reduction"],
            "linked_neg_item":        next(
                (ni["negotiation_id"]
                 for ni in pkg["negotiation_items"]
                 if ni["action_id"] == a["action_id"]),
                "—",
            ),
        })

    # ── 6. Negotiation Priorities — HIGH items only ───────────────────────────
    neg_priorities = []
    for ni in pkg["negotiation_items"]:
        if ni["priority"] != "HIGH":
            continue
        sr_summary = [
            {
                "sr_id":      rb["sr_id"],
                "framework":  rb["framework"],
                "regulation": FRAMEWORK_FULL.get(rb["framework"], rb["framework"]),
                "article":    SR_ARTICLE.get(rb["sr_id"], rb.get("article", "")),
                "match_type": rb["match_type"],
                "confidence": rb["confidence"],
            }
            for rb in ni["regulatory_basis"]
        ]
        rec_text = ni["recommended_clause_text"]
        rec_summary = (rec_text[:180] + "…") if len(rec_text) > 180 else rec_text
        neg_priorities.append({
            "negotiation_id":        ni["negotiation_id"],
            "action_id":             ni["action_id"],
            "priority":              ni["priority"],
            "topic":                 ni["topic"],
            "affected_clauses":      ni["affected_clauses"],
            "finding_label":         ni.get("finding_label", ni["finding_type"]),
            "problem_summary":       ni["problem_summary"][:200] + "…"
                                     if len(ni["problem_summary"]) > 200
                                     else ni["problem_summary"],
            "regulatory_basis":      sr_summary,
            "recommended_clause_summary": rec_summary,
            "fallback_option":       ni["fallback_option"][:200] + "…"
                                     if len(ni["fallback_option"]) > 200
                                     else ni["fallback_option"],
            "max_risk_score":        ni["risk_score_reference"]["max_score"],
            "owner_role":            ni["owner_role"],
        })

    return {
        "contract_id":          contract_id,
        "generated_at":         date.today().isoformat(),
        "pipeline_stage":       "Stage 14 — Contract Risk Report",
        "metadata":             metadata,
        "risk_distribution":    risk_distribution,
        "top_risk_areas":       top_risk_areas,
        "regulatory_exposure":  regulatory_exposure,
        "action_plan_overview": action_overview,
        "negotiation_priorities": neg_priorities,
    }

# ── Markdown renderer ─────────────────────────────────────────────────────────

def generate_markdown(report: dict) -> str:
    ln: list[str] = []
    m   = report["metadata"]
    cid = report["contract_id"]

    # ── Header ────────────────────────────────────────────────────────────────
    overall_icon = PRI_ICON.get(m["overall_risk"], "")
    ln += [
        f"# Contract Risk Report",
        f"## {cid} — {m['organization']}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| **Contract ID** | `{cid}` |",
        f"| **Organization** | {m['organization']} |",
        f"| **Report Date** | {m['generated_at']} |",
        f"| **Pipeline Stage** | {report['pipeline_stage']} |",
        f"| **Overall Risk** | {overall_icon} **{m['overall_risk']}** |",
        f"| **Frameworks in Scope** | "
            + " · ".join(f"`{f}`" for f in m["frameworks_in_scope"]) + " |",
        "",
        "---",
        "",
    ]

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 1 — EXECUTIVE SUMMARY
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        "## 1. Executive Summary",
        "",
        "This report consolidates the findings of the full contract analysis "
        f"pipeline (Stages 1–13) for contract `{cid}`. "
        "It is intended as a standalone reference document for management, "
        "legal counsel, and auditors.",
        "",
        "### 1.1 Clause Statistics",
        "",
        "| Metric | Count |",
        "|---|:---:|",
        f"| Total clauses analysed | **{m['total_clauses']}** |",
        f"| VALID clauses (no action required) | {m['valid_clauses']} |",
        f"| Clauses with findings | **{m['total_findings']}** |",
        f"| 🔴 HIGH risk clauses | **{m['high_risk_clauses']}** |",
        f"| 🟡 MEDIUM risk clauses | **{m['medium_risk_clauses']}** |",
        f"| 🟢 LOW risk clauses (non-VALID) | {m['low_risk_clauses']} |",
        "",
        "### 1.2 Actions & Negotiations",
        "",
        "| Metric | Count |",
        "|---|:---:|",
        f"| Total remediation actions | **{m['total_actions']}** |",
        f"| 🔴 HIGH priority actions | **{m['high_priority_actions']}** |",
        f"| 🟡 MEDIUM priority actions | {m['medium_priority_actions']} |",
        f"| Total negotiation items | **{m['total_negotiation_items']}** |",
        f"| 🔴 HIGH priority negotiations | **{m['high_priority_negotiation']}** |",
        f"| 🟡 MEDIUM priority negotiations | {m['medium_priority_negotiation']} |",
        f"| Unique regulatory SR IDs referenced | {m['unique_sr_ids']} |",
        "",
        "### 1.3 Key Findings",
        "",
    ]

    # Bullet-point findings for each HIGH risk area
    for area in report["top_risk_areas"]:
        if area["priority"] == "HIGH":
            icon = PRI_ICON["HIGH"]
            acts = ", ".join(f"`{a}`" for a in area["related_actions"])
            ln.append(
                f"- {icon} **{area['topic_label']}** "
                f"(max score **{area['max_score']:.1f}/10**, "
                f"{area['clause_count']} clause(s)) — "
                f"{area['risk_summary'][:120]}… "
                f"→ {acts}"
            )
    for area in report["top_risk_areas"]:
        if area["priority"] == "MEDIUM":
            icon = PRI_ICON["MEDIUM"]
            ln.append(
                f"- {icon} **{area['topic_label']}** "
                f"(max score **{area['max_score']:.1f}/10**, "
                f"{area['clause_count']} clause(s)) — "
                f"{area['risk_summary'][:100]}…"
            )

    ln += ["", "---", ""]

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 2 — RISK DISTRIBUTION
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        "## 2. Risk Distribution",
        "",
        "> VALID clauses are excluded from this table and appear only in "
        "the statistics above.",
        "",
        "| Clause | Page | Topic | Score | Priority | Obligation | Action | NEG Item |",
        "|---|:---:|---|:---:|:---:|---|---|---|",
    ]
    for rd in report["risk_distribution"]:
        icon   = PRI_ICON.get(rd["priority"], "")
        topic  = TOPIC_LABEL.get(rd["topic"], rd["topic"] or "—")
        action = f"`{rd['linked_action']}`" if rd["linked_action"] != "—" else "—"
        neg    = f"`{rd['linked_neg_item']}`" if rd["linked_neg_item"] != "—" else "—"
        ln.append(
            f"| `{rd['clause_id']}` "
            f"| {rd['page']} "
            f"| {topic} "
            f"| **{rd['risk_score']:.1f}** "
            f"| {icon} {rd['priority']} "
            f"| `{rd['obligation']}` "
            f"| {action} "
            f"| {neg} |"
        )

    ln += [
        "",
        "### 2.1 Clause Summaries",
        "",
    ]
    for rd in report["risk_distribution"]:
        icon  = PRI_ICON.get(rd["priority"], "")
        topic = TOPIC_LABEL.get(rd["topic"], rd["topic"] or "—")
        ln += [
            f"**`{rd['clause_id']}`** — {icon} {rd['priority']} · "
            f"Score {rd['risk_score']:.1f} · {topic} (p. {rd['page']})",
            f"> {rd['text_preview']}",
            "",
        ]

    ln += ["---", ""]

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 3 — TOP RISK AREAS
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        "## 3. Top Risk Areas",
        "",
        "| Topic | Clauses | Max Score | Avg Score | Priority | Related Actions |",
        "|---|:---:|:---:|:---:|:---:|---|",
    ]
    for area in report["top_risk_areas"]:
        icon  = PRI_ICON.get(area["priority"], "")
        topic = TOPIC_LABEL.get(area["topic"], area["topic"])
        acts  = " ".join(f"`{a}`" for a in area["related_actions"]) or "—"
        ln.append(
            f"| **{topic}** "
            f"| {area['clause_count']} "
            f"| **{area['max_score']:.1f}** "
            f"| {area['avg_score']:.1f} "
            f"| {icon} {area['priority']} "
            f"| {acts} |"
        )

    ln += ["", "### 3.1 Topic Risk Summaries", ""]
    for area in report["top_risk_areas"]:
        icon  = PRI_ICON.get(area["priority"], "")
        topic = TOPIC_LABEL.get(area["topic"], area["topic"])
        acts  = ", ".join(f"`{a}`" for a in area["related_actions"]) or "—"
        ln += [
            f"#### {icon} {topic}",
            "",
            area["risk_summary"],
            "",
            f"**Related actions**: {acts}",
            "",
        ]

    ln += ["---", ""]

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 4 — REGULATORY EXPOSURE
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        "## 4. Regulatory Exposure",
        "",
        "| SR ID | Framework | Regulation | Article | Clauses Impacted | NEG Items |",
        "|---|---|---|---|---|---|",
    ]
    for sr in report["regulatory_exposure"]:
        clauses = " ".join(f"`{c}`" for c in sr["clauses"]) or "—"
        negs    = " ".join(f"`{n}`" for n in sr["neg_ids"]) or "—"
        reg_short = sr["regulation"][:38] + "…" if len(sr["regulation"]) > 40 else sr["regulation"]
        ln.append(
            f"| `{sr['sr_id']}` "
            f"| **{sr['framework']}** "
            f"| {reg_short} "
            f"| {sr['article']} "
            f"| {clauses} "
            f"| {negs} |"
        )

    ln += ["", "### 4.1 SR Detail", ""]
    for sr in report["regulatory_exposure"]:
        mt_icon = "✅" if sr["match_type"] == "DIRECT_MATCH" else "⚠️"
        clauses = ", ".join(f"`{c}`" for c in sr["clauses"]) or "—"
        negs    = ", ".join(f"`{n}`" for n in sr["neg_ids"]) or "—"
        ln += [
            f"#### `{sr['sr_id']}` — {sr['framework']}",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| **Regulation** | {sr['regulation']} |",
            f"| **Article / Control** | {sr['article']} |",
            f"| **Best Match Type** | {mt_icon} {sr['match_type']} · {sr['confidence']}% |",
            f"| **Clauses Impacted** | {clauses} |",
            f"| **Negotiation Items** | {negs} |",
            "",
        ]

    ln += ["---", ""]

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 5 — ACTION PLAN OVERVIEW
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        "## 5. Action Plan Overview",
        "",
        "| Action ID | Priority | Finding | Clauses | Owner | NEG Item | Effort |",
        "|---|:---:|---|---|---|---|---|",
    ]
    for a in report["action_plan_overview"]:
        icon    = PRI_ICON.get(a["priority"], "")
        clauses = " ".join(f"`{c}`" for c in a["affected_clauses"])
        neg     = f"`{a['linked_neg_item']}`" if a["linked_neg_item"] != "—" else "—"
        ln.append(
            f"| `{a['action_id']}` "
            f"| {icon} {a['priority']} "
            f"| {a['finding_label']} "
            f"| {clauses} "
            f"| {a['owner_role']} "
            f"| {neg} "
            f"| {a['estimated_effort']} |"
        )

    ln += ["", "### 5.1 Expected Risk Reduction", ""]
    for a in report["action_plan_overview"]:
        icon   = PRI_ICON.get(a["priority"], "")
        topics = " / ".join(TOPIC_LABEL.get(t, t) for t in a["topic"])
        ln.append(
            f"- {icon} **`{a['action_id']}`** ({topics}): "
            f"{a['expected_risk_reduction']}"
        )

    ln += ["", "---", ""]

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 6 — NEGOTIATION PRIORITIES
    # ═══════════════════════════════════════════════════════════════════════
    ln += [
        "## 6. Negotiation Priorities",
        "",
        "> This section lists HIGH-priority negotiation items only. "
        "For the complete negotiation package see `negotiation_package.md`.",
        "",
    ]

    if not report["negotiation_priorities"]:
        ln.append("> No HIGH-priority negotiation items.\n")
    else:
        for np_item in report["negotiation_priorities"]:
            icon    = PRI_ICON["HIGH"]
            clauses = " · ".join(f"`{c}`" for c in np_item["affected_clauses"])
            topics  = " / ".join(TOPIC_LABEL.get(t, t) for t in np_item["topic"])

            ln += [
                "---",
                "",
                f"### {np_item['negotiation_id']} — {np_item['finding_label']}",
                "",
                "| Field | Value |",
                "|---|---|",
                f"| **NEG ID** | `{np_item['negotiation_id']}` |",
                f"| **Action ID** | `{np_item['action_id']}` |",
                f"| **Priority** | {icon} HIGH |",
                f"| **Topic(s)** | {topics} |",
                f"| **Clauses** | {clauses} |",
                f"| **Max Risk Score** | **{np_item['max_risk_score']:.1f}** / 10 |",
                f"| **Owner** | {np_item['owner_role']} |",
                "",
                "**Problem:**",
                "",
                f"> {np_item['problem_summary'][:180]}{'…' if len(np_item['problem_summary']) > 180 else ''}",
                "",
            ]

            # Regulatory basis
            if np_item["regulatory_basis"]:
                ln += [
                    "**Regulatory Basis:**",
                    "",
                    "| SR ID | Framework | Article | Match |",
                    "|---|---|---|:---:|",
                ]
                for rb in np_item["regulatory_basis"]:
                    mt_icon = "✅" if rb["match_type"] == "DIRECT_MATCH" else "⚠️"
                    ln.append(
                        f"| `{rb['sr_id']}` "
                        f"| **{rb['framework']}** "
                        f"| {rb['article']} "
                        f"| {mt_icon} {rb['confidence']}% |"
                    )
                ln.append("")
            else:
                ln += ["> ⚪ No direct SR match — unknown-gap finding.", ""]

            # Recommended clause summary
            ln += [
                "**Recommended Clause (summary):**",
                "",
                f"> {np_item['recommended_clause_summary']}",
                "",
                "**Fallback Position:**",
                "",
                f"> {np_item['fallback_option'][:200]}{'…' if len(np_item['fallback_option']) > 200 else ''}",
                "",
            ]

    ln += [
        "---",
        "",
        "## Appendix — Pipeline Traceability",
        "",
        "| Stage | Output | Role in this report |",
        "|---|---|---|",
        "| Stage 8 | `stage8_remediation_proposals.json` | Source for recommended clause texts |",
        "| Stage 9 | `contract_negotiation_brief.json` | Topic risk summaries and negotiation positions |",
        "| Stage 10 | `audit_trace_CT-2026-001.json` | Original clause texts and SR linkage |",
        "| Stage 11 | `risk_scoring.json` | Numeric risk scores, priorities, SR match details |",
        "| Stage 12 | `action_plan.json` | Consolidated remediation actions with owner assignments |",
        "| Stage 13 | `negotiation_package.json` | Negotiation arguments, fallback positions, clause comparisons |",
        "| Stage 14 | `contract_risk_report.json/.md` | **This report** |",
        "",
    ]

    return "\n".join(ln)

# ── Terminal summary ──────────────────────────────────────────────────────────

def _print_summary(report: dict) -> None:
    m   = report["metadata"]
    SEP = "-" * 76
    print("=" * 76)
    print(f"  STAGE 14 — CONTRACT RISK REPORT  |  {report['contract_id']}")
    print("=" * 76)
    print(f"  Organization    : {m['organization']}")
    print(f"  Overall Risk    : {PRI_ICON.get(m['overall_risk'],'')} {m['overall_risk']}")
    print(f"  Frameworks      : {', '.join(m['frameworks_in_scope'])}")
    print(SEP)
    print(f"  Total clauses   : {m['total_clauses']}  "
          f"(findings={m['total_findings']}  valid={m['valid_clauses']})")
    print(f"  🔴 HIGH clauses : {m['high_risk_clauses']}")
    print(f"  🟡 MEDIUM clauses: {m['medium_risk_clauses']}")
    print(f"  Actions         : {m['total_actions']}  "
          f"(HIGH={m['high_priority_actions']})")
    print(f"  NEG items       : {m['total_negotiation_items']}  "
          f"(HIGH={m['high_priority_negotiation']})")
    print(f"  SR IDs          : {m['unique_sr_ids']}")
    print(SEP)
    print("  Top Risk Areas:")
    for area in report["top_risk_areas"]:
        icon  = PRI_ICON.get(area["priority"], "")
        topic = TOPIC_LABEL.get(area["topic"], area["topic"])
        acts  = " ".join(area["related_actions"])
        print(f"    {icon} {topic:<28}  max={area['max_score']:.1f}  "
              f"avg={area['avg_score']:.1f}  n={area['clause_count']}  {acts}")
    print("=" * 76)

# ── CLI ───────────────────────────────────────────────────────────────────────

def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Stage 14: Generate consolidated Contract Risk Report."
    )
    ap.add_argument("--scores",  "-s", default="risk_scoring.json")
    ap.add_argument("--plan",    "-p", default="action_plan.json")
    ap.add_argument("--package", "-n", default="negotiation_package.json")
    ap.add_argument("--trace",   "-t", default="audit_trace_CT-2026-001.json")
    ap.add_argument("--brief",   "-b", default="contract_negotiation_brief.json")
    ap.add_argument("--output",  "-o", default="contract_risk_report.json")
    ap.add_argument("--markdown","-m", default="contract_risk_report.md")
    ap.add_argument("--quiet",   "-q", action="store_true")
    return ap.parse_args()


def main() -> None:
    args = _args()

    scores  = _load(args.scores,  "Stage 11 risk scoring")
    plan    = _load(args.plan,    "Stage 12 action plan")
    pkg     = _load(args.package, "Stage 13 negotiation package")
    trace   = _load(args.trace,   "Stage 10 audit trace")
    brief   = _load(args.brief,   "Stage 9 negotiation brief")

    report = build_report(scores, plan, pkg, trace, brief)

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)
    print(f"  JSON saved  -> {args.output}", file=sys.stderr)

    md = generate_markdown(report)
    with open(args.markdown, "w") as f:
        f.write(md)
    print(f"  MD   saved  -> {args.markdown}", file=sys.stderr)

    if not args.quiet:
        _print_summary(report)

    sys.exit(0 if report["metadata"]["overall_risk"] != "HIGH" else 1)


if __name__ == "__main__":
    main()
