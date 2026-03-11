#!/usr/bin/env python3
"""
Stage 6: Contract Compliance Report Generator

Aggregates:
  • Stage 5  → clause_sr_matches.json    (clause-level SR matches, one record per clause×SR)
  • Stage 4.5 → stage4_5_obligation_analysis.json (clause-level obligation flags)
  • org_profile.json                     (organisational regulatory context)
  • contract_metadata.json (optional)   (contract classification)

Produces a unified compliance report (JSON + terminal summary).
Exit codes: 0 = no HIGH findings, 1 = HIGH findings present.

Architecture change (v2):
  OLD: read stage5_matches.json  — one SR record with page-level evidence
       SR result determined by single best-chunk match
  NEW: read clause_sr_matches.json — one record per (clause_id, sr_id) pair
       SR result aggregated from all clause-level matches:
         COMPLIANT   ← any clause has DIRECT_MATCH for this SR
         WEAK_MATCH  ← any clause has PARTIAL_MATCH, none DIRECT_MATCH
         MISSING     ← all clauses returned NO_MATCH for this SR
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Constants ─────────────────────────────────────────────────────────────────

SEVERITY_RANK: dict[str, int] = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

SR_RESULT_SEVERITY: dict[str, str] = {
    "COMPLIANT":  "LOW",
    "WEAK_MATCH": "MEDIUM",
    "MISSING":    "HIGH",
}

# Obligation assessment types that warrant a finding entry
FLAGGED_ASSESSMENTS = {
    "NON_TRANSFERABLE_REGULATION",
    "OPERATIONAL_RISK",
    "AMBIGUOUS_REQUIREMENT",
    "SCOPE_UNDEFINED",
    "CUSTOMER_RESPONSIBILITY",
}


# ── 1. Loaders ────────────────────────────────────────────────────────────────

def _load_json(path: str, label: str) -> Any:
    p = Path(path)
    if not p.exists():
        print(f"  [ERROR] {label} not found: {path}", file=sys.stderr)
        sys.exit(1)
    with p.open() as fh:
        return json.load(fh)


def load_inputs(
    clause_matches_path: str,
    stage45_path: str,
    org_profile_path: str,
    metadata_path: str | None,
) -> tuple[list, list, dict, dict | None]:
    clause_matches = _load_json(clause_matches_path, "clause_sr_matches.json")
    if not isinstance(clause_matches, list):
        print("  [ERROR] clause_sr_matches.json must be a JSON array", file=sys.stderr)
        sys.exit(1)
    stage45  = _load_json(stage45_path, "stage4_5_obligation_analysis.json")
    org      = _load_json(org_profile_path, "org_profile.json")
    metadata = None
    if metadata_path:
        p = Path(metadata_path)
        if p.exists():
            with p.open() as fh:
                metadata = json.load(fh)
    return clause_matches, stage45, org, metadata


# ── 2. SR Compliance Section (aggregated from clause_sr_matches) ──────────────

def build_sr_compliance(clause_matches: list[dict]) -> dict:
    """
    Aggregate clause-level SR match records into SR-level compliance findings.

    For each unique (framework, sr_id):
      - Collect all clause-level match records
      - COMPLIANT   → at least one DIRECT_MATCH exists across clauses
      - WEAK_MATCH  → at least one PARTIAL_MATCH exists, no DIRECT_MATCH
      - MISSING     → all records are NO_MATCH
    """
    # Group records by (framework, sr_id)
    sr_groups: dict[tuple[str, str], dict] = {}
    for record in clause_matches:
        key = (record["framework"], record["sr_id"])
        if key not in sr_groups:
            sr_groups[key] = {
                "framework":  record["framework"],
                "control_id": record.get("control_id", ""),
                "sr_id":      record["sr_id"],
                "sr_title":   record.get("sr_title", record["sr_id"]),
                "records":    [],
            }
        sr_groups[key]["records"].append(record)

    frameworks: dict[str, dict] = {}
    sr_findings: list[dict] = []

    for (fw, sr_id), group in sorted(sr_groups.items()):
        records = group["records"]
        direct  = [r for r in records if r["match_type"] == "DIRECT_MATCH"]
        partial = [r for r in records if r["match_type"] == "PARTIAL_MATCH"]

        if direct:
            result = "COMPLIANT"
            best   = max(direct, key=lambda r: r["match_confidence"])
        elif partial:
            result = "WEAK_MATCH"
            best   = max(partial, key=lambda r: r["match_confidence"])
        else:
            result = "MISSING"
            best   = None

        severity = SR_RESULT_SEVERITY.get(result, "MEDIUM")

        if fw not in frameworks:
            frameworks[fw] = {
                "total": 0, "compliant": 0, "weak_match": 0,
                "missing": 0, "coverage_percent": 0.0,
            }
        frameworks[fw]["total"] += 1
        if result == "COMPLIANT":
            frameworks[fw]["compliant"] += 1
        elif result == "WEAK_MATCH":
            frameworks[fw]["weak_match"] += 1
        elif result == "MISSING":
            frameworks[fw]["missing"] += 1

        if result in ("WEAK_MATCH", "MISSING"):
            finding: dict[str, Any] = {
                "source":            "SR_COMPLIANCE",
                "finding_type":      result,
                "severity":          severity,
                "framework":         fw,
                "sub_requirement_id": sr_id,
                "control_id":        group["control_id"],
                "title":             group["sr_title"],
                "confidence":        best["match_confidence"] if best else None,
                "matched_clause_id": best["clause_id"] if best else None,
                "direct_matches":    len(direct),
                "partial_matches":   len(partial),
                "clause_count":      len(records),
            }
            if result == "WEAK_MATCH":
                finding["description"] = (
                    f"Partial coverage of '{group['sr_title']}' "
                    f"(best confidence {best['match_confidence']:.0%} in clause {best['clause_id']}). "
                    "Clause may be insufficiently specific."
                )
                finding["extracted_evidence"] = best.get("extracted_evidence", "")
            else:
                finding["description"] = (
                    f"No clause found covering '{group['sr_title']}' ({fw} {group['control_id']}). "
                    "This sub-requirement is entirely absent from the contract."
                )
                finding["extracted_evidence"] = ""
            sr_findings.append(finding)

    for fw, data in frameworks.items():
        covered = data["compliant"] + data["weak_match"]
        data["coverage_percent"] = round(covered / data["total"] * 100, 1) if data["total"] else 0.0

    unique_srs   = len(sr_groups)
    frameworks_seen = sorted({fw for fw, _ in sr_groups})
    summary = {
        "COMPLIANT":  sum(1 for (fw, _), g in sr_groups.items()
                          if any(r["match_type"] == "DIRECT_MATCH"  for r in g["records"])),
        "WEAK_MATCH": sum(1 for (fw, _), g in sr_groups.items()
                          if not any(r["match_type"] == "DIRECT_MATCH"  for r in g["records"])
                          and any(r["match_type"] == "PARTIAL_MATCH" for r in g["records"])),
        "MISSING":    sum(1 for (fw, _), g in sr_groups.items()
                          if all(r["match_type"] == "NO_MATCH" for r in g["records"])),
    }

    return {
        "source_file":          "clause_sr_matches.json",
        "linkage_method":       "clause_direct",
        "frameworks_checked":   frameworks_seen,
        "total_srs_evaluated":  unique_srs,
        "frameworks":           frameworks,
        "summary":              summary,
        "findings":             sr_findings,
    }


# ── 3. Obligation Analysis Section (from Stage 4.5) ───────────────────────────

def build_obligation_section(stage45: list[dict]) -> dict:
    """Summarise Stage 4.5 clause-level obligation flags."""
    by_assessment: dict[str, int] = {}
    obligation_findings: list[dict] = []

    for clause in stage45:
        assessment = clause.get("assessment", "VALID")
        by_assessment[assessment] = by_assessment.get(assessment, 0) + 1

        if assessment in FLAGGED_ASSESSMENTS:
            obligation_findings.append({
                "source":             "OBLIGATION_ANALYSIS",
                "finding_type":       assessment,
                "severity":           clause.get("severity", "MEDIUM"),
                "clause_id":          clause["clause_id"],
                "page":               clause.get("page"),
                "layout_type":        clause.get("layout_type"),
                "reason":             clause.get("reason", ""),
                "recommended_action": clause.get("recommended_action", ""),
                "confidence":         clause.get("_confidence"),
                "analysis_source":    clause.get("_source", "RULES"),
            })

    total   = len(stage45)
    flagged = len(obligation_findings)
    high_risk = [f for f in obligation_findings if f["severity"] == "HIGH"]

    return {
        "source_file":            "stage4_5_obligation_analysis.json",
        "total_clauses_analysed": total,
        "flagged_clauses":        flagged,
        "valid_clauses":          total - flagged,
        "by_assessment":          by_assessment,
        "high_risk_count":        len(high_risk),
        "findings":               obligation_findings,
    }


# ── 4. Overall Risk Aggregation ───────────────────────────────────────────────

def _overall_status(all_findings: list[dict]) -> str:
    if not all_findings:
        return "COMPLIANT"
    max_sev = max(SEVERITY_RANK.get(f["severity"], 0) for f in all_findings)
    if max_sev >= SEVERITY_RANK["HIGH"]:
        return "HIGH_RISK"
    if max_sev >= SEVERITY_RANK["MEDIUM"]:
        return "MEDIUM_RISK"
    return "LOW_RISK"


def build_overall(sr_section: dict, obligation_section: dict) -> dict:
    all_findings = sr_section["findings"] + obligation_section["findings"]

    by_severity: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in all_findings:
        sev = f.get("severity", "MEDIUM")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    blocking = [f for f in all_findings if f["severity"] == "HIGH"]

    return {
        "overall_status":          _overall_status(all_findings),
        "total_findings":          len(all_findings),
        "findings_by_severity":    by_severity,
        "blocking_findings_count": len(blocking),
        "blocking_findings":       blocking,
    }


# ── 5. Report Assembly ────────────────────────────────────────────────────────

def generate_report(
    clause_matches: list[dict],
    stage45: list[dict],
    org: dict,
    metadata: dict | None,
) -> dict:
    sr_section         = build_sr_compliance(clause_matches)
    obligation_section = build_obligation_section(stage45)
    overall            = build_overall(sr_section, obligation_section)

    # Derive contract_id from metadata or first match record
    contract_id = "UNKNOWN"
    if metadata:
        contract_id = metadata.get("contract_id", "UNKNOWN")

    org_summary = {
        "organization_name":            org.get("organization_name", ""),
        "industry":                     org.get("industry", ""),
        "regulatory_frameworks":        org.get("regulatory_frameworks", []),
        "nis2_entity_type":             org.get("nis2_entity_type"),
        "is_regulated_financial_entity": org.get("is_regulated_financial_entity"),
    }

    contract_summary: dict[str, Any] = {
        "contract_id":     contract_id,
        "contract_type":   metadata.get("contract_type")   if metadata else None,
        "vendor_risk_tier": metadata.get("vendor_risk_tier") if metadata else None,
        "data_sensitivity": metadata.get("data_sensitivity") if metadata else None,
    }
    if metadata:
        contract_summary["classification_confidence"] = metadata.get("confidence")

    return {
        "report_id":          f"RPT-{contract_id}-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
        "contract_id":        contract_id,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "stage":              6,
        "org_profile":        org_summary,
        "contract_metadata":  contract_summary,
        "sr_compliance":      sr_section,
        "obligation_analysis": obligation_section,
        "overall_compliance": overall,
    }


# ── 6. Terminal Report ────────────────────────────────────────────────────────

_SEV_ICON = {"HIGH": "[HIGH]", "MEDIUM": "[MED]", "LOW": "[LOW]"}
_STATUS_ICON = {
    "COMPLIANT":    "[OK]",
    "HIGH_RISK":    "[HIGH RISK]",
    "MEDIUM_RISK":  "[MED RISK]",
    "LOW_RISK":     "[LOW RISK]",
}
_W = 72


def print_report(report: dict) -> None:
    sep = "-" * _W
    ov     = report["overall_compliance"]
    status = ov["overall_status"]
    icon   = _STATUS_ICON.get(status, "?")

    print(f"\n{'=' * _W}")
    print(f"  CONTRACT COMPLIANCE REPORT  |  {report['report_id']}")
    print(f"{'=' * _W}")

    org = report["org_profile"]
    ct  = report["contract_metadata"]
    print(f"  Organisation : {org['organization_name']}  ({org['industry']})")
    print(f"  Contract     : {ct['contract_id']}  |  "
          f"Type={ct.get('contract_type', 'N/A')}  "
          f"Risk={ct.get('vendor_risk_tier', 'N/A')}  "
          f"Data={ct.get('data_sensitivity', 'N/A')}")
    print(f"  Frameworks   : {', '.join(org['regulatory_frameworks'])}")
    print(f"  Generated    : {report['generated_at']}")
    print(sep)

    # ── Overall status ──────────────────────────────────────────────────────
    print(f"\n  OVERALL STATUS: {icon}  {status}")
    print(f"  Findings : {ov['total_findings']} total  |  "
          f"HIGH={ov['findings_by_severity'].get('HIGH', 0)}  "
          f"MEDIUM={ov['findings_by_severity'].get('MEDIUM', 0)}  "
          f"LOW={ov['findings_by_severity'].get('LOW', 0)}")

    # ── SR Compliance (from clause_sr_matches) ──────────────────────────────
    sr = report["sr_compliance"]
    print(f"\n{sep}")
    print("  SR COMPLIANCE  (Stage 5 — clause-level regulatory sub-requirement matching)")
    print(f"  Linkage method: {sr['linkage_method']}")
    print(sep)
    print(f"  Sub-requirements evaluated: {sr['total_srs_evaluated']}")
    print(f"  {'FRAMEWORK':<12} {'COMPLIANT':>10} {'WEAK':>6} {'MISSING':>8} {'COVERAGE':>10}")
    print(f"  {'-'*12} {'-'*10} {'-'*6} {'-'*8} {'-'*10}")
    for fw, data in sr["frameworks"].items():
        cov_pct  = data["coverage_percent"]
        fw_icon  = "OK " if data["missing"] == 0 and data["weak_match"] == 0 else "!! "
        print(
            f"  {fw_icon} {fw:<10} "
            f"{data['compliant']:>10} "
            f"{data['weak_match']:>6} "
            f"{data['missing']:>8} "
            f"{cov_pct:>9.1f}%"
        )

    if sr["findings"]:
        print()
        for f in sr["findings"]:
            sev_icon = _SEV_ICON.get(f["severity"], "?")
            ctrl     = f.get("control_id", "")
            print(f"  {sev_icon} [{f['finding_type']}] {f['framework']} {ctrl} | "
                  f"{f['sub_requirement_id']} — {f['title']}")
            print(f"     {f['description']}")
            if f.get("matched_clause_id"):
                print(f"     best clause={f['matched_clause_id']}  "
                      f"confidence={f['confidence']:.0%}")
    else:
        print("\n  All sub-requirements satisfied")

    # ── Obligation Analysis (Stage 4.5) ─────────────────────────────────────
    ob = report["obligation_analysis"]
    print(f"\n{sep}")
    print("  OBLIGATION ANALYSIS  (Stage 4.5 — clause-level risk flags)")
    print(sep)
    print(f"  Clauses analysed : {ob['total_clauses_analysed']}  |  "
          f"Flagged: {ob['flagged_clauses']}  Valid: {ob['valid_clauses']}")
    if ob["by_assessment"]:
        print(f"  By type  : " +
              "  ".join(f"{k}={v}" for k, v in sorted(ob["by_assessment"].items())))

    if ob["findings"]:
        print()
        for f in ob["findings"]:
            sev_icon = _SEV_ICON.get(f["severity"], "?")
            print(f"  {sev_icon} [{f['finding_type']}]  {f['clause_id']}  "
                  f"(page {f.get('page', '?')}  {f.get('layout_type', '')})")
            reason = f.get("reason", "")
            if len(reason) > 90:
                reason = reason[:87] + "..."
            print(f"     Reason : {reason}")
            action = f.get("recommended_action", "")
            if len(action) > 90:
                action = action[:87] + "..."
            print(f"     Action : {action}")
    else:
        print("\n  No obligation risk flags detected")

    # ── Blocking findings ───────────────────────────────────────────────────
    if ov["blocking_findings"]:
        print(f"\n{sep}")
        print(f"  BLOCKING FINDINGS ({ov['blocking_findings_count']} HIGH-severity issues require resolution)")
        print(sep)
        for i, f in enumerate(ov["blocking_findings"], 1):
            src_label = f.get("sub_requirement_id") or f.get("clause_id") or "-"
            print(f"  {i:>2}. [HIGH] [{f['finding_type']}]  {src_label}")
            if f.get("recommended_action"):
                action = f["recommended_action"]
                if len(action) > 88:
                    action = action[:85] + "..."
                print(f"      -> {action}")

    print(f"\n{'=' * _W}\n")


# ── 7. CLI ────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Stage 6: Generate unified contract compliance report."
    )
    p.add_argument("--clause-matches", default="clause_sr_matches.json",
                   help="Path to Stage 5 output (default: clause_sr_matches.json)")
    p.add_argument("--stage45",        default="stage4_5_obligation_analysis.json",
                   help="Path to Stage 4.5 output")
    p.add_argument("--org-profile",    default="org_profile.json",
                   help="Path to org_profile.json")
    p.add_argument("--metadata",       default="contract_metadata.json",
                   help="Path to contract_metadata.json (optional)")
    p.add_argument("--output", "-o",   default=None,
                   help="Output JSON path (default: stage6_compliance_<contract_id>.json)")
    p.add_argument("--quiet", "-q",    action="store_true",
                   help="Suppress terminal report, only write JSON")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    clause_matches, stage45, org, metadata = load_inputs(
        clause_matches_path=args.clause_matches,
        stage45_path=args.stage45,
        org_profile_path=args.org_profile,
        metadata_path=args.metadata,
    )

    report = generate_report(clause_matches, stage45, org, metadata)

    if not args.quiet:
        print_report(report)

    contract_id = report["contract_id"]
    output_path = args.output or f"stage6_compliance_{contract_id}.json"
    with open(output_path, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"  JSON report saved -> {output_path}\n")

    has_high = report["overall_compliance"]["findings_by_severity"].get("HIGH", 0) > 0
    sys.exit(1 if has_high else 0)


if __name__ == "__main__":
    main()
