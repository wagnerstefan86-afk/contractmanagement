#!/usr/bin/env python3
"""
Stage 7 — Contract Decision Engine
Converts Stage-6 risk findings into a deterministic contract approval decision.
Usage: python stage7_contract_decision.py <stage6_risk_analysis.json> [--contract-id <id>]
"""

import json
import sys
import argparse
from pathlib import Path


# ---------------------------------------------------------------------------
# Decision logic constants
# ---------------------------------------------------------------------------

REJECT_CONDITION       = {"severity": "HIGH",   "finding_type": "MISSING"}
CONDITIONAL_CONDITIONS = [
    {"severity": "HIGH",   "finding_type": "WEAK_MATCH"},
    {"severity": "MEDIUM"},
]

# Maps (framework, finding_type, severity) → preferred owner role
OWNER_MAP = {
    "DORA":     {"MISSING": "Legal",    "WEAK_MATCH": "Security"},
    "NIS2":     {"MISSING": "Security", "WEAK_MATCH": "Security"},
    "GDPR":     {"MISSING": "DPO",      "WEAK_MATCH": "DPO"},
    "ISO27001": {"MISSING": "Security", "WEAK_MATCH": "Security"},
}

DEFAULT_OWNER = "Legal"


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def load_findings(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Input must be a JSON array of SR findings.")
    return data


def classify_finding(sr: dict) -> str:
    """Return REJECT | CONDITIONAL | APPROVE for a single SR."""
    sev = sr.get("severity")
    ftype = sr.get("finding_type")

    if sev == REJECT_CONDITION["severity"] and ftype == REJECT_CONDITION["finding_type"]:
        return "REJECT"

    for cond in CONDITIONAL_CONDITIONS:
        if sev == cond.get("severity"):
            if "finding_type" not in cond or ftype == cond["finding_type"]:
                return "CONDITIONAL"

    return "APPROVE"


def determine_contract_decision(findings: list[dict]) -> str:
    classes = [classify_finding(sr) for sr in findings]
    if "REJECT" in classes:
        return "REJECT"
    if "CONDITIONAL" in classes:
        return "CONDITIONAL_APPROVAL"
    return "APPROVE"


def build_blocking_findings(findings: list[dict]) -> list[dict]:
    blocking = []
    for sr in findings:
        c = classify_finding(sr)
        if c in ("REJECT", "CONDITIONAL"):
            blocking.append({
                "sr_id":              sr["sr_id"],
                "framework":          sr["framework"],
                "severity":           sr["severity"],
                "finding_type":       sr["finding_type"],
                "recommended_action": sr["recommended_action"],
            })
    return blocking


def resolve_owner(sr: dict) -> str:
    framework = sr.get("framework", "")
    ftype     = sr.get("finding_type", "")
    return OWNER_MAP.get(framework, {}).get(ftype, DEFAULT_OWNER)


def build_remediation_tasks(findings: list[dict]) -> list[dict]:
    tasks = []
    task_counter = 1

    for sr in findings:
        c = classify_finding(sr)
        if c not in ("REJECT", "CONDITIONAL"):
            continue

        task_id = f"TASK-{task_counter:03d}"
        task_counter += 1

        tasks.append({
            "task_id":          task_id,
            "description":      sr["recommended_action"],
            "owner_role":       resolve_owner(sr),
            "priority":         sr["severity"],
            "related_sr":       sr["sr_id"],
        })

    return tasks


def build_summary(findings: list[dict]) -> dict:
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for sr in findings:
        sev = sr.get("severity", "LOW")
        counts[sev] = counts.get(sev, 0) + 1
    return {
        "total_srs":       len(findings),
        "high_findings":   counts["HIGH"],
        "medium_findings": counts["MEDIUM"],
        "low_findings":    counts["LOW"],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Stage 7 — Contract Decision Engine"
    )
    parser.add_argument(
        "input_file",
        help="Path to stage6_risk_analysis.json"
    )
    parser.add_argument(
        "--contract-id",
        default="CT-2026-001",
        help="Contract identifier (default: CT-2026-001)"
    )
    args = parser.parse_args()

    # Load
    findings = load_findings(args.input_file)

    # Evaluate
    decision           = determine_contract_decision(findings)
    blocking_findings  = build_blocking_findings(findings)
    remediation_tasks  = build_remediation_tasks(findings)
    summary            = build_summary(findings)

    output = {
        "contract_id":        args.contract_id,
        "decision":           decision,
        "blocking_findings":  blocking_findings,
        "remediation_tasks":  remediation_tasks,
        "summary":            summary,
    }

    # Write
    output_path = f"contract_decision_{args.contract_id}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Console summary
    ICONS = {"APPROVE": "✅", "CONDITIONAL_APPROVAL": "⚠️ ", "REJECT": "❌"}
    print(f"\n{'='*55}")
    print(f"  Contract Decision Engine — Stage 7")
    print(f"{'='*55}")
    print(f"  Contract ID : {args.contract_id}")
    print(f"  Decision    : {ICONS.get(decision,'')} {decision}")
    print(f"  SRs total   : {summary['total_srs']}  "
          f"(HIGH={summary['high_findings']}  "
          f"MED={summary['medium_findings']}  "
          f"LOW={summary['low_findings']})")
    print(f"  Blocking    : {len(blocking_findings)} finding(s)")
    print(f"  Tasks       : {len(remediation_tasks)} remediation task(s)")
    print(f"  Output      : {output_path}")
    print(f"{'='*55}\n")

    if blocking_findings:
        print("  Blocking findings:")
        for bf in blocking_findings:
            print(f"    [{bf['severity']}] {bf['sr_id']} ({bf['framework']}) — {bf['finding_type']}")
        print()

    if remediation_tasks:
        print("  Remediation tasks:")
        for t in remediation_tasks:
            print(f"    {t['task_id']}  [{t['priority']}]  owner={t['owner_role']}  sr={t['related_sr']}")
        print()

    # Exit code reflects decision for CI/CD gating
    exit_codes = {"APPROVE": 0, "CONDITIONAL_APPROVAL": 2, "REJECT": 1}
    sys.exit(exit_codes.get(decision, 1))


if __name__ == "__main__":
    main()
