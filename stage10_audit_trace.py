#!/usr/bin/env python3
"""
Stage 10: Audit Trace Generator

Builds a complete decision-trace record for every clause, linking each step of
the pipeline:

  Stage 4  (clause extraction)
    └─ Stage 4.5 (obligation analysis)
         └─ Stage 5  (SR regulatory matching)        ← linked by clause_id  [v2]
              └─ Stage 6  (compliance findings)
                   └─ Stage 8  (remediation proposal)
                        └─ Stage 9  (negotiation topic)

Outputs:
  audit_trace_<contract_id>.json   — full trace records (one per clause)
  audit_trace_<contract_id>.mmd    — Mermaid flowchart (--mermaid to enable)

Clause-direct linkage (v2):
  Stage 5 SR matches are indexed by clause_id. A clause is linked only to SR
  matches whose clause_id == this clause's clause_id. This is deterministic and
  avoids the page-proximity ambiguity where one page could host multiple
  unrelated clauses.

  Replaces: page_proximity (clause.page == sr_match.page)
  With:     clause_direct  (clause.clause_id == sr_match.clause_id)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ── 1. Loaders ────────────────────────────────────────────────────────────────

def _load(path: str, label: str) -> Any:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] {label} not found: {path}", file=sys.stderr)
        sys.exit(1)
    with p.open() as fh:
        return json.load(fh)


# ── 2. Index builders ─────────────────────────────────────────────────────────

def _index_by(records: list[dict], key: str) -> dict[str, dict]:
    return {r[key]: r for r in records if key in r}


def _build_clause_sr_index(
    clause_sr_matches: list[dict],
) -> dict[str, list[dict]]:
    """
    Build a clause_id → [SR match records] index from clause_sr_matches.json.

    Only includes records with match_type DIRECT_MATCH or PARTIAL_MATCH.
    NO_MATCH records are excluded from the trace (they carry no positive
    evidence and would inflate the regulatory_matches list with noise).
    """
    idx: dict[str, list[dict]] = {}
    for record in clause_sr_matches:
        if record.get("match_type") == "NO_MATCH":
            continue
        cid = record.get("clause_id")
        if cid:
            idx.setdefault(cid, []).append(record)
    return idx


def _build_topic_index(brief: dict) -> dict[str, str]:
    """Return {clause_or_sr_id → topic_name} from the Stage 9 brief."""
    idx: dict[str, str] = {}
    for section in brief.get("topics", []):
        topic = section["topic"]
        for ref in section.get("affected_clauses", []):
            idx[ref] = topic
    return idx


# ── 3. Trace record builder ───────────────────────────────────────────────────

_STAGE_NAMES = {
    4:   "Clause Extraction",
    4.5: "Obligation Analysis",
    5:   "SR Regulatory Matching",
    6:   "Compliance Report",
    8:   "Remediation Proposal",
    9:   "Negotiation Brief",
}


def _build_trace_record(
    seq: int,
    clause: dict,
    ob_idx:        dict[str, dict],
    sr_by_clause:  dict[str, list[dict]],
    ob6_idx:       dict[str, dict],
    rem_idx:       dict[str, dict],
    topic_idx:     dict[str, str],
    sr_topic_idx:  dict[str, str],
    brief_topics:  dict[str, dict],
) -> dict:
    cid     = clause["clause_id"]
    page    = clause.get("page")
    text    = clause.get("text", "")
    preview = (text[:200] + "…") if len(text) > 200 else text

    # ── Stage 4 ───────────────────────────────────────────────────────────────
    s4 = {
        "stage":       4,
        "stage_name":  _STAGE_NAMES[4],
        "source_file": "stage4_clauses.json",
        "clause_id":   cid,
        "page":        page,
        "layout_type": clause.get("layout_type"),
    }

    # ── Stage 4.5 ─────────────────────────────────────────────────────────────
    ob = ob_idx.get(cid, {})
    s45: dict[str, Any] = {
        "stage":       4.5,
        "stage_name":  _STAGE_NAMES[4.5],
        "source_file": "stage4_5_obligation_analysis.json",
        "found":       bool(ob),
    }
    if ob:
        s45.update({
            "assessment":         ob.get("assessment"),
            "severity":           ob.get("severity"),
            "reason":             ob.get("reason"),
            "recommended_action": ob.get("recommended_action"),
            "confidence":         ob.get("_confidence"),
            "analysis_source":    ob.get("_source"),
        })

    # ── Stage 5 (clause-direct linkage) ───────────────────────────────────────
    sr_matches_raw = sr_by_clause.get(cid, [])
    regulatory_matches = [
        {
            "sr_id":              m["sr_id"],
            "framework":          m["framework"],
            "control_id":         m.get("control_id", ""),
            "sr_title":           m.get("sr_title", m["sr_id"]),
            "match_type":         m["match_type"],
            "match_confidence":   m["match_confidence"],
            "extracted_evidence": m.get("extracted_evidence", ""),
            "linkage_method":     "clause_direct",
        }
        for m in sr_matches_raw
    ]
    s5: dict[str, Any] = {
        "stage":              5,
        "stage_name":         _STAGE_NAMES[5],
        "source_file":        "clause_sr_matches.json",
        "linkage_method":     "clause_direct",
        "regulatory_matches": regulatory_matches,
    }

    # ── Stage 6 ───────────────────────────────────────────────────────────────
    ob6 = ob6_idx.get(cid, {})
    compliance_findings: list[dict] = []
    if ob6:
        compliance_findings.append({
            "source":       "OBLIGATION_ANALYSIS",
            "finding_type": ob6.get("finding_type"),
            "severity":     ob6.get("severity"),
            "description":  ob6.get("reason"),
        })
    s6: dict[str, Any] = {
        "stage":               6,
        "stage_name":          _STAGE_NAMES[6],
        "source_file":         "stage6_compliance_CT-2026-001.json",
        "compliance_findings": compliance_findings,
    }

    # ── Stage 8 ───────────────────────────────────────────────────────────────
    rem = rem_idx.get(cid, {})
    s8: dict[str, Any] = {
        "stage":       8,
        "stage_name":  _STAGE_NAMES[8],
        "source_file": "stage8_remediation_proposals.json",
        "found":       bool(rem),
    }
    if rem:
        sc = rem.get("suggested_clause", "")
        s8.update({
            "finding_type":             rem.get("finding_type"),
            "severity":                 rem.get("severity"),
            "problem_summary":          rem.get("problem_summary"),
            "negotiation_guidance":     rem.get("negotiation_guidance"),
            "suggested_clause_preview": (sc[:300] + "…") if len(sc) > 300 else sc,
            "proposal_source":          rem.get("_proposal_source"),
        })

    # ── Stage 9 ───────────────────────────────────────────────────────────────
    topic      = topic_idx.get(cid)
    topic_data = brief_topics.get(topic, {}) if topic else {}
    s9: dict[str, Any] = {
        "stage":       9,
        "stage_name":  _STAGE_NAMES[9],
        "source_file": "contract_negotiation_brief.json",
        "found":       bool(topic),
    }
    if topic:
        s9.update({
            "negotiation_topic":       topic,
            "negotiation_topic_label": topic_data.get("topic_label", topic),
            "topic_highest_severity":  topic_data.get("highest_severity"),
            "topic_issue_count":       topic_data.get("issue_count"),
        })

    # ── Assemble ──────────────────────────────────────────────────────────────
    return {
        "trace_id":              f"TRACE-{seq:03d}",
        "clause_id":             cid,
        "page":                  page,
        "layout_type":           clause.get("layout_type"),
        "original_text_preview": preview,

        # Required flat fields
        "obligation_assessment": ob.get("assessment") if ob else None,
        "obligation_severity":   ob.get("severity")   if ob else None,
        "obligation_reason":     ob.get("reason")     if ob else None,
        "regulatory_matches": [
            {
                "framework":        m["framework"],
                "sr_id":            m["sr_id"],
                "match_type":       m["match_type"],
                "match_confidence": m["match_confidence"],
            }
            for m in regulatory_matches
        ],
        "compliance_findings": [
            {"severity": f["severity"], "finding_type": f["finding_type"]}
            for f in compliance_findings
        ],
        "remediation": {
            "suggested_clause":     rem.get("suggested_clause"),
            "negotiation_guidance": rem.get("negotiation_guidance"),
        } if rem else None,
        "negotiation_topic": topic,

        # Full pipeline step detail
        "pipeline_steps": {
            "stage_4":   s4,
            "stage_4_5": s45,
            "stage_5":   s5,
            "stage_6":   s6,
            "stage_8":   s8,
            "stage_9":   s9,
        },
    }


# ── 4. Mermaid generator ──────────────────────────────────────────────────────

_SEV_COLOR = {"HIGH": "#ff4444", "MEDIUM": "#ffaa00", "LOW": "#44cc44", None: "#aaaaaa"}
_TOPIC_COLOR = {
    "REGULATORY_COMPLIANCE": "#d63031",
    "INCIDENT_MANAGEMENT":   "#e17055",
    "DATA_PROTECTION":       "#0984e3",
    "SECURITY_CONTROLS":     "#6c5ce7",
    "AUDIT_RIGHTS":          "#00b894",
    "SERVICE_LEVELS":        "#00cec9",
    "OTHER":                 "#b2bec3",
}
_MATCH_STYLE = {"DIRECT_MATCH": "-->", "PARTIAL_MATCH": "-.->"}


def _mmd_id(s: str) -> str:
    return s.replace("-", "_").replace(".", "_").replace(" ", "_")


def _mmd_label(lines: list[str]) -> str:
    return '["' + "\\n".join(lines) + '"]'


def generate_mermaid(
    traces: list[dict],
    brief: dict,
    contract_id: str,
) -> str:
    """
    Generate Mermaid flowchart for the full clause-level pipeline.

    Subgraphs:
      S4  — Clause Extraction      (Stage 4)
      S45 — Obligation Analysis    (Stage 4.5)   flagged clauses only
      S5  — Clause-SR Matches      (Stage 5)     DIRECT + PARTIAL only
      S8  — Remediation            (Stage 8)     clauses with proposals
      S9  — Negotiation Topics     (Stage 9)

    Scope: ALL clauses that have either SR matches (DIRECT/PARTIAL) or a
    non-VALID obligation assessment. This covers the full interesting pipeline
    without noise from clean clauses.

    Edge styles:
      clause → SR   solid arrow  (DIRECT_MATCH)
      clause → SR   dashed arrow (PARTIAL_MATCH)
      all others    solid arrows

    Colour coding:
      HIGH severity      → #ff4444 (red)
      MEDIUM severity    → #ffaa00 (amber)
      LOW severity       → #44cc44 (green)
      PARTIAL/WEAK match → #fdcb6e (yellow)
      DIRECT match       → #00b894 (teal)
      VALID / clean      → #dfe6e9 (grey)
    """
    # Relevant traces: non-VALID obligation OR has SR matches
    relevant = [
        t for t in traces
        if (t.get("obligation_assessment") and t["obligation_assessment"] != "VALID")
        or t.get("regulatory_matches")
    ]
    # Flagged subset (non-VALID obligation assessment)
    flagged = [t for t in relevant
               if t.get("obligation_assessment") and t["obligation_assessment"] != "VALID"]

    lines: list[str] = [
        "%%{ init: { 'flowchart': { 'curve': 'basis' } } }%%",
        "flowchart LR",
        "",
        "%% ── Styles ──────────────────────────────────────────────────────────",
        "    classDef HIGH    fill:#ff4444,color:#fff,stroke:#cc0000",
        "    classDef MEDIUM  fill:#ffaa00,color:#222,stroke:#cc8800",
        "    classDef LOW     fill:#44cc44,color:#222,stroke:#229922",
        "    classDef VALID   fill:#dfe6e9,color:#636e72,stroke:#b2bec3",
        "    classDef TOPIC_H fill:#d63031,color:#fff,stroke:#a00",
        "    classDef TOPIC_M fill:#0984e3,color:#fff,stroke:#0660a8",
        "    classDef TOPIC_L fill:#00b894,color:#fff,stroke:#007a62",
        "    classDef SR_DIR  fill:#00b894,color:#fff,stroke:#007a62",
        "    classDef SR_PAR  fill:#fdcb6e,color:#222,stroke:#e0a800",
        "",
        "%% ── Stage 4 — Clause Extraction ────────────────────────────────────",
        '    subgraph S4["📄 Stage 4 — Clause Extraction"]',
    ]

    for t in relevant:
        cid = t["clause_id"]
        nid = _mmd_id(cid)
        pg  = t.get("page", "?")
        lt  = t.get("layout_type", "")
        sev = t.get("obligation_severity", "")
        css = sev if sev else "VALID"
        lines.append(f'        {nid}["{cid}\\np.{pg} | {lt}"]')
        lines.append(f'        class {nid} {css}')
    lines += ["    end", ""]

    # Stage 4.5 — flagged clauses only (only they have obligation assessments)
    if flagged:
        lines += [
            "%% ── Stage 4.5 — Obligation Analysis ────────────────────────────────",
            '    subgraph S45["🔍 Stage 4.5 — Obligation Analysis"]',
        ]
        for t in flagged:
            cid = t["clause_id"]
            nid = _mmd_id(cid)
            oa  = t.get("obligation_assessment", "")
            sev = t.get("obligation_severity", "")
            lines.append(f'        OA_{nid}["{oa}\\n{sev}"]')
            lines.append(f'        class OA_{nid} {sev}')
        lines += ["    end", ""]

    # Stage 5 — deduplicated SR nodes from all relevant clauses
    sr_seen:  set[str]   = set()
    sr_nodes: list[tuple] = []
    for t in relevant:
        for m in t.get("regulatory_matches", []):
            sr_id = m["sr_id"]
            nid   = _mmd_id(sr_id)
            if nid not in sr_seen:
                sr_seen.add(nid)
                full_m = next(
                    (x for x in t["pipeline_steps"]["stage_5"]["regulatory_matches"]
                     if x["sr_id"] == sr_id),
                    m,
                )
                mt   = full_m.get("match_type", "?")
                conf = full_m.get("match_confidence", 0)
                ctrl = full_m.get("control_id", "")
                fw   = m["framework"]
                sr_nodes.append((nid, sr_id, fw, ctrl, mt, f"{conf:.0%}"))

    if sr_nodes:
        lines += [
            "%% ── Stage 5 — Clause-SR Matches (clause-direct) ───────────────────",
            '    subgraph S5["📋 Stage 5 — Clause-SR Matches"]',
        ]
        for nid, sr_id, fw, ctrl, mt, conf_str in sr_nodes:
            css_cls = "SR_DIR" if mt == "DIRECT_MATCH" else "SR_PAR"
            mt_short = "DIRECT" if mt == "DIRECT_MATCH" else "PARTIAL"
            lines.append(
                f'        {nid}["{sr_id}\\n{fw} {ctrl}\\n{mt_short} {conf_str}"]'
            )
            lines.append(f'        class {nid} {css_cls}')
        lines += ["    end", ""]

    # Stage 8 — remediation nodes for all relevant clauses that have proposals
    rem_relevant = [t for t in relevant if t.get("remediation")]
    if rem_relevant:
        lines += [
            "%% ── Stage 8 — Remediation Proposals ───────────────────────────────",
            '    subgraph S8["🔧 Stage 8 — Remediation"]',
        ]
        for t in rem_relevant:
            cid   = t["clause_id"]
            nid   = _mmd_id(cid)
            ftype = t["pipeline_steps"]["stage_8"].get("finding_type", "")
            sev   = t.get("obligation_severity") or t["pipeline_steps"]["stage_8"].get(
                "severity", "MEDIUM"
            )
            lines.append(f'        REM_{nid}["{cid}\\n{ftype}"]')
            lines.append(f'        class REM_{nid} {sev}')
        lines += ["    end", ""]

    # Stage 9 — topic nodes (from all relevant traces)
    topics_seen: dict[str, dict] = {}
    for t in relevant:
        topic = t.get("negotiation_topic")
        if topic and topic not in topics_seen:
            topics_seen[topic] = t["pipeline_steps"]["stage_9"]

    if topics_seen:
        lines += [
            "%% ── Stage 9 — Negotiation Topics ──────────────────────────────────",
            '    subgraph S9["📝 Stage 9 — Negotiation Brief"]',
        ]
        for topic, step9 in topics_seen.items():
            tnid    = _mmd_id(topic)
            label   = step9.get("negotiation_topic_label", topic)
            top_sev = step9.get("topic_highest_severity", "")
            count   = step9.get("topic_issue_count", "?")
            if top_sev == "HIGH":
                css_cls = "TOPIC_H"
            elif top_sev == "MEDIUM":
                css_cls = "TOPIC_M"
            else:
                css_cls = "TOPIC_L"
            lines.append(f'        T_{tnid}["{label}\\n{top_sev} · {count} issues"]')
            lines.append(f'        class T_{tnid} {css_cls}')
        lines += ["    end", ""]

    # ── Edges ─────────────────────────────────────────────────────────────────
    lines.append("%% ── Edges ───────────────────────────────────────────────────────────")

    for t in relevant:
        cid   = t["clause_id"]
        nid   = _mmd_id(cid)
        topic = t.get("negotiation_topic")
        is_flagged = bool(t.get("obligation_assessment") and
                          t["obligation_assessment"] != "VALID")

        # Clause → Obligation (only flagged clauses have obligation nodes)
        if is_flagged:
            lines.append(f"    {nid} -->|Stage 4.5| OA_{nid}")

        # Clause → SR matches
        #   solid  -->  DIRECT_MATCH
        #   dashed -.-> PARTIAL_MATCH
        for m in t.get("regulatory_matches", []):
            sr_nid = _mmd_id(m["sr_id"])
            mt     = m.get("match_type", "DIRECT_MATCH")
            if mt == "DIRECT_MATCH":
                lines.append(f"    {nid} -->|direct {m['match_confidence']:.0%}| {sr_nid}")
            else:
                lines.append(f"    {nid} -.->|partial {m['match_confidence']:.0%}| {sr_nid}")

        # Obligation → Remediation
        if is_flagged and t.get("remediation"):
            lines.append(f"    OA_{nid} -->|Stage 8| REM_{nid}")
        elif not is_flagged and t.get("remediation"):
            # SR-only finding with no obligation flag but with remediation
            lines.append(f"    {nid} -->|Stage 8| REM_{nid}")

        # Remediation / Obligation / Clause → Topic
        if topic:
            tnid = _mmd_id(topic)
            if t.get("remediation"):
                lines.append(f"    REM_{nid} -->|Stage 9| T_{tnid}")
            elif is_flagged:
                lines.append(f"    OA_{nid} -->|Stage 9| T_{tnid}")
            else:
                lines.append(f"    {nid} -->|Stage 9| T_{tnid}")

    lines.append("")
    return "\n".join(lines)


# ── 5. Terminal summary ───────────────────────────────────────────────────────

_SEV_ICON = {"HIGH": "[H]", "MEDIUM": "[M]", "LOW": "[L]", None: "[ ]"}
_W = 72


def _print_summary(
    traces: list[dict],
    contract_id: str,
    output_path: str,
    mmd_path: str | None,
) -> None:
    flagged = [t for t in traces
               if t.get("obligation_assessment") and t["obligation_assessment"] != "VALID"]
    valid   = [t for t in traces
               if not t.get("obligation_assessment") or t["obligation_assessment"] == "VALID"]

    print(f"\n{'=' * _W}")
    print(f"  STAGE 10 — AUDIT TRACE  |  {contract_id}")
    print(f"{'=' * _W}")
    print(f"  Total clauses traced : {len(traces)}")
    print(f"  Flagged clauses      : {len(flagged)}")
    print(f"  Valid clauses        : {len(valid)}")
    sep = "-" * _W
    print(sep)
    print(f"  {'TRACE-ID':<10} {'CLAUSE':<8} {'PG':>3}  "
          f"{'OBLIGATION':<28} {'SEV':>5}  TOPIC")
    print(f"  {'-'*10} {'-'*8} {'-'*3}  {'-'*28} {'-'*5}  -----")
    for t in traces:
        icon  = _SEV_ICON.get(t.get("obligation_severity"))
        oa    = t.get("obligation_assessment") or "VALID"
        sev   = t.get("obligation_severity") or "-"
        topic = t.get("negotiation_topic") or "-"
        pg    = str(t.get("page", "?"))
        print(
            f"  {t['trace_id']:<10} {t['clause_id']:<8} {pg:>3}  "
            f"{oa:<28} {icon} {sev:<3}  {topic}"
        )
    print(sep)
    print(f"\n  SR regulatory matches (clause-direct linkage):")
    for t in traces:
        if t.get("regulatory_matches"):
            refs = ", ".join(
                f"{m['sr_id']} ({m['match_type']} {m['match_confidence']:.0%})"
                for m in t["regulatory_matches"]
            )
            mt_icon = "●" if any(
                m.get("match_type") == "DIRECT_MATCH" for m in t["regulatory_matches"]
            ) else "○"
            print(f"  {mt_icon} {t['clause_id']:>6} --> {refs}")
    print(f"\n  JSON  saved -> {output_path}")
    if mmd_path:
        print(f"  MMD   saved -> {mmd_path}")
    print(f"{'=' * _W}\n")


# ── 6. CLI ────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Stage 10: Build full decision audit trace across all pipeline stages."
    )
    ap.add_argument("--clauses",        default="stage4_clauses.json")
    ap.add_argument("--obligations",    default="stage4_5_obligation_analysis.json")
    ap.add_argument("--clause-matches", default="clause_sr_matches.json",
                    help="Stage 5 output (clause_sr_matches.json, replaces stage5_matches.json)")
    ap.add_argument("--compliance",     default="stage6_compliance_CT-2026-001.json")
    ap.add_argument("--remediation",    default="stage8_remediation_proposals.json")
    ap.add_argument("--brief",          default="contract_negotiation_brief.json")
    ap.add_argument("--output", "-o",   default=None,
                    help="JSON output path (default: audit_trace_<contract_id>.json)")
    ap.add_argument("--mermaid", "-m",  action="store_true",
                    help="Also write a Mermaid flowchart (.mmd)")
    ap.add_argument("--quiet", "-q",    action="store_true",
                    help="Suppress terminal summary")
    return ap.parse_args()


def main() -> None:
    args = _parse_args()

    # Load all inputs
    clauses         = _load(args.clauses,         "Stage 4 clauses")
    obligations     = _load(args.obligations,     "Stage 4.5 obligation analysis")
    clause_matches  = _load(args.clause_matches,  "Stage 5 clause-SR matches")
    compliance      = _load(args.compliance,      "Stage 6 compliance report")
    remediation     = _load(args.remediation,     "Stage 8 remediation proposals")
    brief           = _load(args.brief,           "Stage 9 negotiation brief")

    if not isinstance(clause_matches, list):
        print("[ERROR] clause_sr_matches.json must be a JSON array", file=sys.stderr)
        sys.exit(1)

    # Derive contract_id from compliance report
    contract_id = compliance.get("contract_id", "UNKNOWN")

    # Build indices
    ob_idx:       dict[str, dict]        = _index_by(obligations, "clause_id")
    sr_by_clause: dict[str, list[dict]]  = _build_clause_sr_index(clause_matches)
    ob6_idx:      dict[str, dict]        = _index_by(
        compliance.get("obligation_analysis", {}).get("findings", []),
        "clause_id",
    )
    rem_idx:      dict[str, dict] = _index_by(remediation, "clause_id")
    topic_idx:    dict[str, str]  = _build_topic_index(brief)
    brief_topics: dict[str, dict] = {
        t["topic"]: t for t in brief.get("topics", [])
    }

    # Build one trace record per clause (in original document order)
    traces: list[dict] = []
    for seq, clause in enumerate(clauses, start=1):
        record = _build_trace_record(
            seq, clause,
            ob_idx, sr_by_clause, ob6_idx,
            rem_idx, topic_idx, {}, brief_topics,
        )
        traces.append(record)

    # Output JSON
    output_path = args.output or f"audit_trace_{contract_id}.json"
    payload = {
        "contract_id":   contract_id,
        "generated_at":  __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "total_clauses": len(traces),
        "linkage_method": "clause_direct",
        "pipeline_stages": [
            {"stage": 4,   "source_file": args.clauses,        "description": _STAGE_NAMES[4]},
            {"stage": 4.5, "source_file": args.obligations,    "description": _STAGE_NAMES[4.5]},
            {"stage": 5,   "source_file": args.clause_matches, "description": _STAGE_NAMES[5]},
            {"stage": 6,   "source_file": args.compliance,     "description": _STAGE_NAMES[6]},
            {"stage": 8,   "source_file": args.remediation,    "description": _STAGE_NAMES[8]},
            {"stage": 9,   "source_file": args.brief,          "description": _STAGE_NAMES[9]},
        ],
        "trace_records": traces,
    }
    with open(output_path, "w") as fh:
        json.dump(payload, fh, indent=2)

    # Optional Mermaid output
    mmd_path = None
    if args.mermaid:
        mmd_path    = output_path.replace(".json", ".mmd")
        mmd_content = generate_mermaid(traces, brief, contract_id)
        with open(mmd_path, "w") as fh:
            fh.write(mmd_content)

    if not args.quiet:
        _print_summary(traces, contract_id, output_path, mmd_path)


if __name__ == "__main__":
    main()
