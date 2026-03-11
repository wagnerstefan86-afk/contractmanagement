#!/usr/bin/env python3
"""
Stage 11 — Clause-Level Risk Scoring
=====================================
Calculates a numeric risk score (1–10) per clause based on:
  • Severity            (HIGH / MEDIUM / LOW)
  • SR-Match quality    (DIRECT / PARTIAL / NO_MATCH)
  • Topic criticality   (REGULATORY_COMPLIANCE, DATA_PROTECTION, …)

Special rules
  • HIGH severity        → score ≥ 7 (floor)
  • No SR match          → score ≥ 6 (unknown-gap penalty, non-VALID only)
  • AMBIGUOUS_REQUIREMENT → score = max(severity + topic, best_conf × 10)
  • DIRECT_MATCH bonus   > PARTIAL_MATCH bonus (1.5 vs 0.75 per match, cap 2.0)

Outputs
  risk_scoring.json  – per-clause scores, breakdowns, topic aggregation
  risk_scoring.md    – Markdown table + per-clause breakdown
  risk_scoring.mmd   – Mermaid graph (optional, --mermaid flag)

CLI
  python stage11_risk_scoring.py \\
      --trace       audit_trace_CT-2026-001.json \\
      --brief       contract_negotiation_brief.json \\
      --remediation stage8_remediation_proposals.json \\
      --output      risk_scoring.json \\
      --markdown    risk_scoring.md \\
      --mermaid
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# ── Scoring tables ────────────────────────────────────────────────────────────

SEVERITY_BASE: dict[str, float] = {
    "HIGH":   7.0,
    "MEDIUM": 4.0,
    "LOW":    1.5,
}

# Added to base for non-VALID findings
TOPIC_BONUS: dict[str, float] = {
    "REGULATORY_COMPLIANCE": 1.5,
    "DATA_PROTECTION":       1.5,
    "SECURITY_CONTROLS":     1.0,
    "AUDIT_RIGHTS":          1.0,
    "INCIDENT_MANAGEMENT":   0.5,
    "SERVICE_LEVELS":        0.3,
    "OTHER":                 0.0,
}

# Per SR-match, summed and capped at SR_BONUS_CAP
MATCH_WEIGHT: dict[str, float] = {
    "DIRECT_MATCH":  1.5,
    "PARTIAL_MATCH": 0.75,
}
SR_BONUS_CAP = 2.0

# Score → priority label
PRIORITY_THRESHOLDS: list[tuple[float, str]] = [
    (7.0, "HIGH"),
    (4.0, "MEDIUM"),
    (0.0, "LOW"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_json(path: str, label: str) -> object:
    p = Path(path)
    if not p.exists():
        print(f"  [ERROR] {label} not found: {path}", file=sys.stderr)
        sys.exit(1)
    with p.open() as f:
        return json.load(f)


def _clamp(v: float, lo: float = 1.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, v))


def _priority(score: float) -> str:
    for threshold, label in PRIORITY_THRESHOLDS:
        if score >= threshold:
            return label
    return "LOW"


# ── Core scoring per clause ───────────────────────────────────────────────────

def _score_clause(
    obligation: str,
    severity: str,
    topic: str | None,
    sr_matches: list[dict],
) -> tuple[float, dict]:
    """
    Return (final_score, breakdown_dict).

    Scoring formula:
      raw = base(severity) + topic_bonus + sr_bonus
      rules: HIGH floor, NO_MATCH floor, AMBIGUOUS override
      final = clamp(raw, 1, 10)
    """
    base      = SEVERITY_BASE.get(severity, 2.0)
    topic_key = topic or "OTHER"
    topic_add = TOPIC_BONUS.get(topic_key, 0.0)

    # SR-match bonus — each DIRECT adds 1.5, each PARTIAL adds 0.75, cap 2.0
    sr_bonus = _clamp(
        sum(MATCH_WEIGHT.get(m.get("match_type", ""), 0.0) for m in sr_matches),
        lo=0.0, hi=SR_BONUS_CAP,
    )

    has_match = bool(sr_matches)
    raw       = base + topic_add + sr_bonus

    floor_applied: list[str] = []

    # Rule 1 — AMBIGUOUS_REQUIREMENT: score = max(clause-based, best_confidence × 10)
    if obligation == "AMBIGUOUS_REQUIREMENT":
        best_conf  = max((m.get("match_confidence", 0.0) for m in sr_matches), default=0.0)
        sr_conf_sc = best_conf * 10.0
        clause_sc  = base + topic_add          # SR bonus excluded from AMBIGUOUS base
        raw = max(clause_sc, sr_conf_sc)
        floor_applied.append("AMBIGUOUS_OVERRIDE")

    # Rule 2 — HIGH severity floor
    if severity == "HIGH" and raw < 7.0:
        raw = 7.0
        floor_applied.append("HIGH_SEVERITY_FLOOR")

    # Rule 3 — NO_MATCH floor (non-VALID clauses with no SR link = unknown gap)
    if not has_match and obligation not in ("VALID",) and raw < 6.0:
        raw = 6.0
        floor_applied.append("NO_MATCH_FLOOR")

    final = _clamp(raw)

    breakdown = {
        "base_severity":   round(base, 2),
        "topic_bonus":     round(topic_add, 2),
        "sr_match_bonus":  round(sr_bonus, 2),
        "raw_score":       round(raw, 2),
        "final_score":     round(final, 2),
        "has_sr_match":    has_match,
        "floors_applied":  floor_applied,
    }
    return final, breakdown


# ── Build full scoring output ─────────────────────────────────────────────────

def build_scoring(
    trace: dict,
    brief: dict,
    remediation: list[dict] | None,
) -> dict:
    # Remediation index
    rem_idx: dict[str, dict] = {}
    if remediation:
        for r in remediation:
            rem_idx[r["clause_id"]] = r

    clause_scores: list[dict] = []

    for rec in trace.get("trace_records", []):
        clause_id  = rec["clause_id"]
        obligation = rec.get("obligation_assessment", "VALID")
        severity   = rec.get("obligation_severity", "LOW")
        topic      = rec.get("negotiation_topic")
        sr_matches = rec.get("regulatory_matches", [])
        preview    = rec.get("original_text_preview", "")
        page       = rec.get("page")

        if obligation == "VALID":
            final_score = 1.5
            breakdown = {
                "base_severity":  1.5,
                "topic_bonus":    0.0,
                "sr_match_bonus": 0.0,
                "raw_score":      1.5,
                "final_score":    1.5,
                "has_sr_match":   False,
                "floors_applied": [],
            }
        else:
            final_score, breakdown = _score_clause(obligation, severity, topic, sr_matches)

        priority = _priority(final_score)

        sr_details = [
            {
                "sr_id":      m.get("sr_id"),
                "framework":  m.get("framework"),
                "match_type": m.get("match_type"),
                "confidence": round(m.get("match_confidence", 0.0) * 100),
            }
            for m in sr_matches
        ]

        rem = rem_idx.get(clause_id)
        snip = rem.get("suggested_clause", "")[:140] + "…" if rem else None

        clause_scores.append({
            "clause_id":          clause_id,
            "page":               page,
            "obligation":         obligation,
            "severity":           severity,
            "topic":              topic,
            "risk_score":         round(final_score, 2),
            "priority":           priority,
            "sr_matches":         sr_details,
            "score_breakdown":    breakdown,
            "text_preview":       (preview[:160] + "…") if len(preview) > 160 else preview,
            "remediation_available": rem is not None,
            "suggested_clause_snippet": snip,
        })

    # Sort descending by score, then clause_id for stable ties
    clause_scores.sort(key=lambda x: (-x["risk_score"], x["clause_id"]))

    # Topic aggregation
    topic_agg: dict[str, list[float]] = {}
    for cs in clause_scores:
        key = cs["topic"] or "VALID"
        topic_agg.setdefault(key, []).append(cs["risk_score"])

    topic_summary = []
    for t, scores in sorted(topic_agg.items(), key=lambda x: -max(x[1])):
        topic_summary.append({
            "topic":        t,
            "clause_count": len(scores),
            "max_score":    round(max(scores), 2),
            "avg_score":    round(sum(scores) / len(scores), 2),
            "total_score":  round(sum(scores), 2),
            "priority":     _priority(max(scores)),
        })

    high   = sum(1 for c in clause_scores if c["priority"] == "HIGH")
    medium = sum(1 for c in clause_scores if c["priority"] == "MEDIUM")
    low    = sum(1 for c in clause_scores if c["priority"] == "LOW")

    return {
        "contract_id":    trace.get("contract_id", "UNKNOWN"),
        "generated_at":   date.today().isoformat(),
        "scoring_version": "1.0",
        "scoring_rules": {
            "severity_base":  SEVERITY_BASE,
            "topic_bonus":    TOPIC_BONUS,
            "match_weight":   MATCH_WEIGHT,
            "sr_bonus_cap":   SR_BONUS_CAP,
            "floors": {
                "HIGH_severity_min": 7.0,
                "no_match_min":      6.0,
            },
        },
        "total_clauses":   len(clause_scores),
        "high_priority":   high,
        "medium_priority": medium,
        "low_priority":    low,
        "topic_summary":   topic_summary,
        "clause_scores":   clause_scores,
    }


# ── Markdown output ───────────────────────────────────────────────────────────

_SEV_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
_PRI_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
_MATCH_ICON = {"DIRECT_MATCH": "✅", "PARTIAL_MATCH": "⚠️"}
_TOPIC_LABEL = {
    "REGULATORY_COMPLIANCE": "Regulatory Compliance",
    "DATA_PROTECTION":       "Data Protection",
    "SECURITY_CONTROLS":     "Security Controls",
    "AUDIT_RIGHTS":          "Audit Rights",
    "INCIDENT_MANAGEMENT":   "Incident Management",
    "SERVICE_LEVELS":        "Service Levels",
    "OTHER":                 "Other",
    "VALID":                 "—",
}


def generate_markdown(scoring: dict) -> str:
    lines: list[str] = []
    cid   = scoring["contract_id"]
    today = scoring["generated_at"]

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        f"# Risk Scoring Report — {cid}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| **Contract** | `{cid}` |",
        f"| **Generated** | {today} |",
        f"| **Scoring Version** | {scoring['scoring_version']} |",
        f"| **Total Clauses** | {scoring['total_clauses']} |",
        f"| 🔴 HIGH Priority | **{scoring['high_priority']}** |",
        f"| 🟡 MEDIUM Priority | **{scoring['medium_priority']}** |",
        f"| 🟢 LOW Priority | **{scoring['low_priority']}** |",
        "",
        "---",
        "",
    ]

    # ── Clause table ──────────────────────────────────────────────────────────
    lines += [
        "## Clause Risk Scores",
        "",
        "| Clause | Score | Priority | Severity | Topic | SR-Matches | Obligation |",
        "|---|:---:|:---:|:---:|---|---|---|",
    ]
    for cs in scoring["clause_scores"]:
        pri_icon = _PRI_ICON.get(cs["priority"], "")
        sev_icon = _SEV_ICON.get(cs["severity"], "")
        srs = " ".join(
            f"{_MATCH_ICON.get(m['match_type'], '?')}`{m['sr_id']}`({m['confidence']}%)"
            for m in cs["sr_matches"]
        ) or "—"
        topic = f"`{cs['topic']}`" if cs["topic"] else "—"
        lines.append(
            f"| `{cs['clause_id']}` | **{cs['risk_score']:.1f}** "
            f"| {pri_icon} {cs['priority']} "
            f"| {sev_icon} {cs['severity']} "
            f"| {topic} | {srs} | {cs['obligation']} |"
        )

    # ── Topic summary ─────────────────────────────────────────────────────────
    lines += [
        "",
        "---",
        "",
        "## Topic Risk Summary",
        "",
        "| Topic | Clauses | Max Score | Avg Score | Total | Priority |",
        "|---|:---:|:---:|:---:|:---:|:---:|",
    ]
    for ts in scoring["topic_summary"]:
        pri_icon = _PRI_ICON.get(ts["priority"], "")
        label    = _TOPIC_LABEL.get(ts["topic"], ts["topic"])
        lines.append(
            f"| **{label}** | {ts['clause_count']} "
            f"| **{ts['max_score']:.1f}** | {ts['avg_score']:.1f} "
            f"| {ts['total_score']:.1f} | {pri_icon} {ts['priority']} |"
        )

    # ── Scoring rules reference ───────────────────────────────────────────────
    rules = scoring["scoring_rules"]
    lines += [
        "",
        "---",
        "",
        "## Scoring Rules",
        "",
        "| Component | Weight |",
        "|---|---|",
        "| Severity HIGH | base 7.0 (floor 7.0) |",
        "| Severity MEDIUM | base 4.0 |",
        "| Severity LOW / VALID | base 1.5 |",
        "| Topic: REGULATORY_COMPLIANCE / DATA_PROTECTION | +1.5 |",
        "| Topic: SECURITY_CONTROLS / AUDIT_RIGHTS | +1.0 |",
        "| Topic: INCIDENT_MANAGEMENT | +0.5 |",
        f"| SR DIRECT_MATCH | +{rules['match_weight']['DIRECT_MATCH']} per match (cap {rules['sr_bonus_cap']}) |",
        f"| SR PARTIAL_MATCH | +{rules['match_weight']['PARTIAL_MATCH']} per match (cap {rules['sr_bonus_cap']}) |",
        "| NO_MATCH (non-VALID) | floor 6.0 |",
        "| AMBIGUOUS_REQUIREMENT | score = max(severity+topic, best_confidence×10) |",
        "",
        "---",
        "",
    ]

    # ── Per-clause breakdowns ─────────────────────────────────────────────────
    lines += ["## Score Breakdown per Clause", ""]

    for cs in scoring["clause_scores"]:
        bd       = cs["score_breakdown"]
        pri_icon = _PRI_ICON.get(cs["priority"], "")
        sev_icon = _SEV_ICON.get(cs["severity"], "")
        floors   = ", ".join(bd["floors_applied"]) or "None"
        topic_lbl = _TOPIC_LABEL.get(cs["topic"] or "", "—")

        lines += [
            f"### `{cs['clause_id']}` — Score **{cs['risk_score']:.1f}** · {pri_icon} {cs['priority']}",
            "",
            f"> *{cs['text_preview']}*",
            "",
            f"| | |",
            f"|---|---|",
            f"| **Obligation** | `{cs['obligation']}` |",
            f"| **Severity** | {sev_icon} {cs['severity']} |",
            f"| **Topic** | {topic_lbl} |",
            f"| **Page** | {cs['page']} |",
            "",
            "**Score components:**",
            "",
            f"| Component | Value |",
            f"|---|---|",
            f"| Base (Severity) | {bd['base_severity']} |",
            f"| + Topic Bonus | +{bd['topic_bonus']} |",
            f"| + SR-Match Bonus | +{bd['sr_match_bonus']} |",
            f"| Raw | {bd['raw_score']} |",
            f"| **Final (clamped 1–10)** | **{bd['final_score']}** |",
            f"| Floors applied | `{floors}` |",
        ]

        if cs["sr_matches"]:
            lines += ["", "**SR Evidence:**", ""]
            for m in cs["sr_matches"]:
                icon  = _MATCH_ICON.get(m["match_type"], "?")
                arrow = "solid `-->`" if m["match_type"] == "DIRECT_MATCH" else "dashed `-.->` "
                lines.append(
                    f"> {icon} `{m['sr_id']}` — {m['framework']} "
                    f"· **{m['match_type']}** {m['confidence']}% · {arrow}"
                )
        else:
            lines += ["", "> ⚪ No direct SR-match — unknown-gap floor applied."]

        if cs["remediation_available"] and cs["suggested_clause_snippet"]:
            lines += [
                "",
                "**Suggested Replacement (excerpt):**",
                "",
                "```",
                cs["suggested_clause_snippet"],
                "```",
            ]

        lines.append("")

    return "\n".join(lines)


# ── Mermaid output ────────────────────────────────────────────────────────────

_MMD_FILL = {
    "HIGH":   ("#ff4444", "#fff"),
    "MEDIUM": ("#ffaa00", "#222"),
    "LOW":    ("#44cc44", "#222"),
    "SR_DIR": ("#00b894", "#fff"),
    "SR_PAR": ("#fdcb6e", "#222"),
}


def generate_mermaid(scoring: dict) -> str:
    lines = [
        "%%{ init: { 'flowchart': { 'curve': 'basis' } } }%%",
        "flowchart LR",
        "",
        "%% ── Styles ─────────────────────────────────────────────────────────",
    ]
    for cls, (fill, txt) in _MMD_FILL.items():
        stroke = fill
        lines.append(f"    classDef {cls} fill:{fill},color:{txt},stroke:{stroke}")

    # ── Clause nodes ──────────────────────────────────────────────────────────
    lines += ["", "    %% Clause nodes (score · priority)"]
    for cs in scoring["clause_scores"]:
        nid   = cs["clause_id"].replace("-", "_")
        label = f"{cs['clause_id']}\\n{cs['risk_score']:.1f} · {cs['priority']}"
        lines.append(f'    {nid}["{label}"]')
        lines.append(f"    class {nid} {cs['priority']}")

    # ── SR nodes (only those referenced by clause SR-matches) ─────────────────
    lines += ["", "    %% SR regulatory nodes"]
    seen_sr: set[str] = set()
    for cs in scoring["clause_scores"]:
        for m in cs["sr_matches"]:
            sr_id = m["sr_id"]
            if sr_id not in seen_sr:
                nid    = sr_id.replace("-", "_")
                cls    = "SR_DIR" if m["match_type"] == "DIRECT_MATCH" else "SR_PAR"
                label  = f"{sr_id}\\n{m['framework']}"
                lines.append(f'    {nid}["{label}"]')
                lines.append(f"    class {nid} {cls}")
                seen_sr.add(sr_id)

    # ── Edges ─────────────────────────────────────────────────────────────────
    lines += ["", "    %% Clause → SR edges"]
    for cs in scoring["clause_scores"]:
        cid = cs["clause_id"].replace("-", "_")
        for m in cs["sr_matches"]:
            sr_nid = m["sr_id"].replace("-", "_")
            conf   = m["confidence"]
            if m["match_type"] == "DIRECT_MATCH":
                lines.append(f'    {cid} -->|"direct {conf}%"| {sr_nid}')
            else:
                lines.append(f'    {cid} -.->|"partial {conf}%"| {sr_nid}')

    return "\n".join(lines)


# ── Terminal summary ──────────────────────────────────────────────────────────

_T_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}


def _print_summary(scoring: dict) -> None:
    sep = "-" * 78
    print("=" * 78)
    print(f"  STAGE 11 — RISK SCORING  |  {scoring['contract_id']}")
    print("=" * 78)
    print(f"  Total clauses   : {scoring['total_clauses']}")
    print(f"  🔴 HIGH          : {scoring['high_priority']}")
    print(f"  🟡 MEDIUM        : {scoring['medium_priority']}")
    print(f"  🟢 LOW           : {scoring['low_priority']}")
    print(sep)
    hdr = f"  {'CLAUSE':<10} {'SCORE':>6}  {'PRI':<10}  {'OBLIGATION':<30}  {'TOPIC'}"
    print(hdr)
    print(sep)
    for cs in scoring["clause_scores"]:
        icon  = _T_ICON.get(cs["priority"], " ")
        srs_s = " ".join(
            ("●" if m["match_type"] == "DIRECT_MATCH" else "○")
            + f"{m['sr_id']}({m['confidence']}%)"
            for m in cs["sr_matches"]
        ) or "—"
        print(
            f"  {cs['clause_id']:<10} {cs['risk_score']:>6.1f}"
            f"  {icon} {cs['priority']:<8}  {cs['obligation']:<30}  "
            f"{str(cs['topic'] or '—')}"
        )
        if cs["sr_matches"]:
            print(f"  {'':>10}   {'':>6}  {'':10}  SR: {srs_s}")
    print(sep)
    print("\n  Topic Summary (sorted by max score):")
    for ts in scoring["topic_summary"]:
        icon = _T_ICON.get(ts["priority"], " ")
        print(
            f"  {icon} {ts['topic']:<30}  max={ts['max_score']:.1f}"
            f"  avg={ts['avg_score']:.1f}  n={ts['clause_count']}"
        )
    print("=" * 78)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Stage 11: Clause-level risk scoring (score 1–10)."
    )
    ap.add_argument("--trace",       "-t",
                    default="audit_trace_CT-2026-001.json",
                    help="Stage 10 audit trace JSON")
    ap.add_argument("--brief",       "-b",
                    default="contract_negotiation_brief.json",
                    help="Stage 9 negotiation brief JSON")
    ap.add_argument("--remediation", "-r",
                    default="stage8_remediation_proposals.json",
                    help="Stage 8 remediation proposals (optional)")
    ap.add_argument("--output",      "-o",
                    default="risk_scoring.json",
                    help="JSON output path")
    ap.add_argument("--markdown",    "-m",
                    default="risk_scoring.md",
                    help="Markdown output path")
    ap.add_argument("--mermaid",     action="store_true",
                    help="Also write Mermaid graph (.mmd)")
    ap.add_argument("--quiet",       "-q", action="store_true",
                    help="Suppress terminal summary")
    return ap.parse_args()


def main() -> None:
    args = _parse_args()

    trace = _load_json(args.trace, "Stage 10 audit trace")
    brief = _load_json(args.brief, "Stage 9 negotiation brief")

    remediation: list | None = None
    rem_path = Path(args.remediation)
    if rem_path.exists():
        with rem_path.open() as f:
            remediation = json.load(f)
    else:
        print(
            f"  [INFO] Remediation not found at '{args.remediation}' — "
            "proceeding without.",
            file=sys.stderr,
        )

    scoring = build_scoring(trace, brief, remediation)

    # JSON
    with open(args.output, "w") as f:
        json.dump(scoring, f, indent=2)
    print(f"  JSON  saved -> {args.output}", file=sys.stderr)

    # Markdown
    md = generate_markdown(scoring)
    with open(args.markdown, "w") as f:
        f.write(md)
    print(f"  MD    saved -> {args.markdown}", file=sys.stderr)

    # Mermaid (optional)
    if args.mermaid:
        mmd_path = Path(args.output).with_suffix(".mmd")
        mmd = generate_mermaid(scoring)
        with open(mmd_path, "w") as f:
            f.write(mmd)
        print(f"  MMD   saved -> {mmd_path}", file=sys.stderr)

    if not args.quiet:
        _print_summary(scoring)

    # Exit 1 if any HIGH-priority clause found
    sys.exit(0 if scoring["high_priority"] == 0 else 1)


if __name__ == "__main__":
    main()
