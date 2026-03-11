#!/usr/bin/env python3
"""
Stage 15 — Contract Audit CLI
==============================
Orchestrates pipeline stages 9-14 from raw clause inputs to final
Contract Risk Report.

Usage
-----
  contract_audit run \\
      --clauses          stage4_clauses.json \\
      --clause-matches   clause_sr_matches.json \\
      --compliance       stage6_compliance_CT-2026-001.json \\
      --remediation      stage8_remediation_proposals.json \\
      [--obligations     stage4_5_obligation_analysis.json] \\
      [--output-dir      /outputs]

Exit codes
----------
  0  Pipeline completed — no HIGH risks detected
  1  Pipeline completed — HIGH risks detected
  2  Pipeline failure   — stage error or invalid inputs
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Bootstrap: resolve stage scripts relative to this file ───────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent

EXIT_OK              = 0
EXIT_HIGH_RISK       = 1
EXIT_PIPELINE_FAILURE = 2


def _import_stage(filename: str) -> Any:
    """Load a stage module from _SCRIPT_DIR by filename."""
    path = _SCRIPT_DIR / filename
    if not path.exists():
        _fatal(f"Stage module not found: {path}")
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    mod  = importlib.util.module_from_spec(spec)          # type: ignore[arg-type]
    spec.loader.exec_module(mod)                           # type: ignore[union-attr]
    return mod


# ── Lazy stage-module imports (loaded once at pipeline start) ─────────────────
_s9 = _s10 = _s11 = _s12 = _s13 = _s14 = None


def _load_stage_modules() -> None:
    global _s9, _s10, _s11, _s12, _s13, _s14
    _s9  = _import_stage("stage9_negotiation_brief.py")
    _s10 = _import_stage("stage10_audit_trace.py")
    _s11 = _import_stage("stage11_risk_scoring.py")
    _s12 = _import_stage("stage12_action_plan.py")
    _s13 = _import_stage("stage13_negotiation_package.py")
    _s14 = _import_stage("stage14_contract_risk_report.py")


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _read_json(path: str | Path, label: str = "") -> Any:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{label or p.name}: file not found: {p}"
        )
    try:
        with p.open() as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"{label or p.name}: invalid JSON — {e}") from e


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write(text)


def _fatal(msg: str, code: int = EXIT_PIPELINE_FAILURE) -> None:
    print(f"\n  [FATAL] {msg}", file=sys.stderr)
    sys.exit(code)


# ── Input validation ──────────────────────────────────────────────────────────

def _validate_inputs(args: argparse.Namespace) -> list[str]:
    """
    Returns a list of validation error strings.
    Empty list = all good.
    """
    errors: list[str] = []

    required = {
        "--clauses":        args.clauses,
        "--clause-matches": args.clause_matches,
        "--compliance":     args.compliance,
        "--remediation":    args.remediation,
    }
    for flag, path in required.items():
        p = Path(path)
        if not p.exists():
            errors.append(f"{flag}: file not found: {path}")
            continue
        if not p.is_file():
            errors.append(f"{flag}: path is not a regular file: {path}")
            continue
        try:
            with p.open() as f:
                json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"{flag}: invalid JSON — {e}")

    # Obligations is optional; only validate if explicitly provided
    if args.obligations:
        p = Path(args.obligations)
        if not p.exists():
            errors.append(f"--obligations: file not found: {args.obligations}")
        elif not p.is_file():
            errors.append(f"--obligations: not a regular file: {args.obligations}")

    # clause-matches must be a JSON array
    cm_path = Path(args.clause_matches)
    if cm_path.exists() and cm_path.is_file():
        try:
            data = json.loads(cm_path.read_text())
            if not isinstance(data, list):
                errors.append("--clause-matches: JSON must be an array/list")
        except json.JSONDecodeError:
            pass  # already caught above

    return errors


# ── Per-stage runner functions ────────────────────────────────────────────────

def run_stage9(
    clauses_path:       str | Path,
    clause_matches_path: str | Path,
    compliance_path:    str | Path,
    remediation_path:   str | Path,
    obligations_path:   str | Path | None,
    output_dir:         Path,
) -> dict:
    """
    Stage 9 — Negotiation Brief
    Calls: stage9_negotiation_brief.build_brief()
    Outputs: contract_negotiation_brief.json + .md
    Returns: full (unstripped) brief dict for downstream stages
    """
    proposals  = _s9._load_json(str(remediation_path), "Stage 8 remediation proposals")
    compliance = _s9._load_json(str(compliance_path),  "Stage 6 compliance report")

    obligations: list | None = None
    if obligations_path and Path(obligations_path).exists():
        with Path(obligations_path).open() as f:
            obligations = json.load(f)

    clauses: list | None = None
    if Path(clauses_path).exists():
        with Path(clauses_path).open() as f:
            clauses = json.load(f)

    clause_sr_matches: list | None = None
    cm = Path(clause_matches_path)
    if cm.exists():
        data = json.loads(cm.read_text())
        if isinstance(data, list):
            clause_sr_matches = data

    brief = _s9.build_brief(proposals, compliance, obligations, clause_sr_matches, clauses)

    _write_json(output_dir / "contract_negotiation_brief.json", _s9.strip_internal(brief))
    _write_text(output_dir / "contract_negotiation_brief.md",   _s9.generate_markdown(brief, proposals))

    return brief  # full, unstripped — needed by downstream stages


def run_stage10(
    clauses_path:       str | Path,
    obligations_path:   str | Path | None,
    clause_matches_path: str | Path,
    compliance_path:    str | Path,
    remediation_path:   str | Path,
    brief:              dict,
    output_dir:         Path,
    contract_id:        str,
) -> dict:
    """
    Stage 10 — Audit Trace
    Calls: stage10_audit_trace internal builders directly
    Outputs: audit_trace_{contract_id}.json
    Returns: trace payload dict
    """
    clauses    = _read_json(clauses_path,    "Stage 4 clauses")
    compliance = _read_json(compliance_path, "Stage 6 compliance report")
    remediation = _read_json(remediation_path, "Stage 8 remediation proposals")

    obligations: list = []
    if obligations_path and Path(obligations_path).exists():
        obligations = _read_json(obligations_path, "Stage 4.5 obligations") or []

    clause_matches_raw = _read_json(clause_matches_path, "Stage 5 clause-SR matches")
    clause_matches = clause_matches_raw if isinstance(clause_matches_raw, list) else []

    ob_idx       = _s10._index_by(obligations, "clause_id")
    sr_by_clause = _s10._build_clause_sr_index(clause_matches)
    ob6_idx      = _s10._index_by(
        compliance.get("obligation_analysis", {}).get("findings", []), "clause_id"
    )
    rem_idx      = _s10._index_by(remediation, "clause_id")
    topic_idx    = _s10._build_topic_index(brief)
    brief_topics = {t["topic"]: t for t in brief.get("topics", [])}

    traces: list[dict] = []
    for seq, clause in enumerate(clauses, start=1):
        record = _s10._build_trace_record(
            seq, clause, ob_idx, sr_by_clause, ob6_idx,
            rem_idx, topic_idx, {}, brief_topics,
        )
        traces.append(record)

    output_path = output_dir / f"audit_trace_{contract_id}.json"
    payload = {
        "contract_id":    contract_id,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "total_clauses":  len(traces),
        "linkage_method": "clause_direct",
        "pipeline_stages": [
            {"stage": 4,   "source_file": str(clauses_path),       "description": "Clause extraction"},
            {"stage": 4.5, "source_file": str(obligations_path or ""), "description": "Obligation analysis"},
            {"stage": 5,   "source_file": str(clause_matches_path), "description": "SR matching"},
            {"stage": 6,   "source_file": str(compliance_path),    "description": "Compliance check"},
            {"stage": 8,   "source_file": str(remediation_path),   "description": "Remediation proposals"},
            {"stage": 9,   "source_file": str(output_dir / "contract_negotiation_brief.json"), "description": "Negotiation brief"},
        ],
        "trace_records": traces,
    }

    _write_json(output_path, payload)
    return payload


def run_stage11(
    trace:            dict,
    brief:            dict,
    remediation_path: str | Path,
    output_dir:       Path,
) -> dict:
    """
    Stage 11 — Risk Scoring
    Calls: stage11_risk_scoring.build_scoring()
    Outputs: risk_scoring.json + .md
    Returns: scoring dict
    """
    remediation = _read_json(remediation_path, "Stage 8 remediation proposals")
    scoring     = _s11.build_scoring(trace, brief, remediation)

    _write_json(output_dir / "risk_scoring.json", scoring)
    _write_text(output_dir / "risk_scoring.md",   _s11.generate_markdown(scoring))

    return scoring


def run_stage12(
    trace:            dict,
    brief:            dict,
    scores:           dict,
    remediation_path: str | Path,
    output_dir:       Path,
) -> dict:
    """
    Stage 12 — Action Plan
    Calls: stage12_action_plan.build_action_plan()
    Outputs: action_plan.json + .md
    Returns: plan dict
    """
    rem_list = _read_json(remediation_path, "Stage 8 remediation proposals")
    plan     = _s12.build_action_plan(trace, brief, scores, rem_list)

    _write_json(output_dir / "action_plan.json", plan)
    _write_text(output_dir / "action_plan.md",   _s12.generate_markdown(plan))

    return plan


def run_stage13(
    plan:             dict,
    brief:            dict,
    trace:            dict,
    scores:           dict,
    remediation_path: str | Path,
    output_dir:       Path,
) -> dict:
    """
    Stage 13 — Negotiation Package
    Calls: stage13_negotiation_package.build_package()
    Outputs: negotiation_package.json + .md
    Returns: package dict
    """
    rem_list = _read_json(remediation_path, "Stage 8 remediation proposals")
    pkg      = _s13.build_package(plan, brief, trace, scores, rem_list)

    _write_json(output_dir / "negotiation_package.json", pkg)
    _write_text(output_dir / "negotiation_package.md",   _s13.generate_markdown(pkg))

    return pkg


def run_stage14(
    scores:     dict,
    plan:       dict,
    pkg:        dict,
    trace:      dict,
    brief:      dict,
    output_dir: Path,
) -> dict:
    """
    Stage 14 — Contract Risk Report
    Calls: stage14_contract_risk_report.build_report()
    Outputs: contract_risk_report.json + .md
    Returns: report dict
    """
    report = _s14.build_report(scores, plan, pkg, trace, brief)

    _write_json(output_dir / "contract_risk_report.json", report)
    _write_text(output_dir / "contract_risk_report.md",   _s14.generate_markdown(report))

    return report


# ── Pipeline logging ──────────────────────────────────────────────────────────

_PRI_ICON = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}

_STAGE_DEFS = [
    ("Stage  9", "Negotiation Brief",     "contract_negotiation_brief.json"),
    ("Stage 10", "Audit Trace",           None),   # filename is dynamic (contract_id)
    ("Stage 11", "Risk Scoring",          "risk_scoring.json"),
    ("Stage 12", "Action Plan",           "action_plan.json"),
    ("Stage 13", "Negotiation Package",   "negotiation_package.json"),
    ("Stage 14", "Contract Risk Report",  "contract_risk_report.json"),
]


def _log_start(tag: str, name: str) -> None:
    print(f"\n  ┌─ {tag}: {name}")
    print(f"  │  Running...", end="", flush=True)


def _log_done(path: Path) -> None:
    size = path.stat().st_size if path.exists() else 0
    print(f"\r  │  ✓  {path.name}  ({size:,} bytes)")
    print(f"  └─ Done")


def _print_final_summary(report: dict, output_dir: Path, elapsed: float) -> None:
    m    = report["metadata"]
    icon = _PRI_ICON.get(m["overall_risk"], "")
    cid  = report["contract_id"]

    print(f"\n{'='*72}")
    print(f"  PIPELINE COMPLETE  ({elapsed:.1f}s)")
    print(f"{'='*72}")
    print(f"  Contract  : {cid}  |  {m['organization']}")
    print(f"  Risk      : {icon} {m['overall_risk']}")
    print(f"  Clauses   : {m['total_clauses']} total  "
          f"| {m['total_findings']} findings  "
          f"| {m['valid_clauses']} valid")
    print(f"  🔴 HIGH   : {m['high_risk_clauses']}  "
          f"🟡 MEDIUM: {m['medium_risk_clauses']}  "
          f"🟢 LOW (non-valid): {m['low_risk_clauses']}")
    print(f"  Actions   : {m['total_actions']} "
          f"(HIGH={m['high_priority_actions']}, "
          f"MEDIUM={m['medium_priority_actions']})")
    print(f"  NEG Items : {m['total_negotiation_items']} "
          f"(HIGH={m['high_priority_negotiation']}, "
          f"MEDIUM={m['medium_priority_negotiation']})")
    print(f"  SR IDs    : {m['unique_sr_ids']}")
    print(f"\n  Output directory → {output_dir.resolve()}")
    print(f"  {'File':<48} {'Bytes':>8}")
    print(f"  {'─'*48} {'─'*8}")

    expected = [
        "contract_negotiation_brief.json",
        "contract_negotiation_brief.md",
        f"audit_trace_{cid}.json",
        "risk_scoring.json",
        "risk_scoring.md",
        "action_plan.json",
        "action_plan.md",
        "negotiation_package.json",
        "negotiation_package.md",
        "contract_risk_report.json",
        "contract_risk_report.md",
    ]
    for fname in expected:
        p    = output_dir / fname
        ok   = "✓" if p.exists() else "✗"
        size = p.stat().st_size if p.exists() else 0
        print(f"  {ok}  {fname:<46} {size:>8,}")
    print(f"{'='*72}")


# ── `run` subcommand ──────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    t_start = datetime.now()
    output_dir = Path(args.output_dir)

    print(f"\n{'='*72}")
    print(f"  CONTRACT AUDIT PIPELINE — Stage 15 Orchestrator")
    print(f"  {t_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*72}")

    # ── 1. Load stage modules ─────────────────────────────────────────────────
    print("\n  [INIT] Loading stage modules...")
    try:
        _load_stage_modules()
    except Exception as exc:
        _fatal(f"Failed to load stage module: {exc}")
    print("  ✓  Stages 9–14 loaded.")

    # ── 2. Validate inputs ────────────────────────────────────────────────────
    print("\n  [VALIDATE] Checking input files...")
    errors = _validate_inputs(args)
    if errors:
        print("  Input validation failed:", file=sys.stderr)
        for e in errors:
            print(f"    ✗  {e}", file=sys.stderr)
        sys.exit(EXIT_PIPELINE_FAILURE)
    print("  ✓  All required inputs present and valid.")

    # ── 3. Bootstrap metadata ─────────────────────────────────────────────────
    compliance_data = _read_json(args.compliance, "--compliance")
    contract_id = compliance_data.get("contract_id", "UNKNOWN")
    print(f"\n  Contract ID : {contract_id}")
    print(f"  Output dir  : {output_dir.resolve()}")

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 4. Execute stages ─────────────────────────────────────────────────────
    try:
        # Stage 9 — Negotiation Brief
        _log_start("Stage  9", "Negotiation Brief")
        brief = run_stage9(
            clauses_path        = args.clauses,
            clause_matches_path = args.clause_matches,
            compliance_path     = args.compliance,
            remediation_path    = args.remediation,
            obligations_path    = args.obligations,
            output_dir          = output_dir,
        )
        _log_done(output_dir / "contract_negotiation_brief.json")

        # Stage 10 — Audit Trace
        _log_start("Stage 10", "Audit Trace")
        trace = run_stage10(
            clauses_path        = args.clauses,
            obligations_path    = args.obligations,
            clause_matches_path = args.clause_matches,
            compliance_path     = args.compliance,
            remediation_path    = args.remediation,
            brief               = brief,
            output_dir          = output_dir,
            contract_id         = contract_id,
        )
        _log_done(output_dir / f"audit_trace_{contract_id}.json")

        # Stage 11 — Risk Scoring
        _log_start("Stage 11", "Risk Scoring")
        scoring = run_stage11(
            trace            = trace,
            brief            = brief,
            remediation_path = args.remediation,
            output_dir       = output_dir,
        )
        _log_done(output_dir / "risk_scoring.json")

        # Stage 12 — Action Plan
        _log_start("Stage 12", "Action Plan")
        plan = run_stage12(
            trace            = trace,
            brief            = brief,
            scores           = scoring,
            remediation_path = args.remediation,
            output_dir       = output_dir,
        )
        _log_done(output_dir / "action_plan.json")

        # Stage 13 — Negotiation Package
        _log_start("Stage 13", "Negotiation Package")
        pkg = run_stage13(
            plan             = plan,
            brief            = brief,
            trace            = trace,
            scores           = scoring,
            remediation_path = args.remediation,
            output_dir       = output_dir,
        )
        _log_done(output_dir / "negotiation_package.json")

        # Stage 14 — Contract Risk Report
        _log_start("Stage 14", "Contract Risk Report")
        report = run_stage14(
            scores     = scoring,
            plan       = plan,
            pkg        = pkg,
            trace      = trace,
            brief      = brief,
            output_dir = output_dir,
        )
        _log_done(output_dir / "contract_risk_report.json")

    except (FileNotFoundError, ValueError) as exc:
        print(f"\n\n  [ERROR] {exc}", file=sys.stderr)
        sys.exit(EXIT_PIPELINE_FAILURE)
    except Exception as exc:
        print(f"\n\n  [FATAL] Unexpected pipeline failure: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(EXIT_PIPELINE_FAILURE)

    # ── 5. Summary + exit ─────────────────────────────────────────────────────
    elapsed = (datetime.now() - t_start).total_seconds()
    _print_final_summary(report, output_dir, elapsed)

    overall_risk = report["metadata"]["overall_risk"]
    if overall_risk == "HIGH":
        sys.exit(EXIT_HIGH_RISK)
    else:
        sys.exit(EXIT_OK)


# ── Argument parser ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog        = "contract_audit",
        description = "Contract analysis pipeline orchestrator (Stage 15).",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Exit codes:\n"
            "  0  Pipeline complete — no HIGH risks\n"
            "  1  Pipeline complete — HIGH risks detected\n"
            "  2  Pipeline failure  — invalid inputs or stage error\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # ── `run` subcommand ──────────────────────────────────────────────────────
    run_p = sub.add_parser(
        "run",
        help        = "Run the full analysis pipeline (stages 9–14).",
        description = "Executes stages 9–14 sequentially. Stops on first failure.",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "Examples:\n"
            "  contract_audit run \\\n"
            "      --clauses         stage4_clauses.json \\\n"
            "      --clause-matches  clause_sr_matches.json \\\n"
            "      --compliance      stage6_compliance_CT-2026-001.json \\\n"
            "      --remediation     stage8_remediation_proposals.json\n"
        ),
    )

    # ── Required inputs ───────────────────────────────────────────────────────
    req = run_p.add_argument_group("required inputs")
    req.add_argument(
        "--clauses", "-c",
        required = True,
        metavar  = "FILE",
        help     = "Stage 4 clause extraction JSON (list of clause objects).",
    )
    req.add_argument(
        "--clause-matches", "-m",
        required = True,
        metavar  = "FILE",
        help     = "Stage 5 clause-SR match JSON (list of match objects).",
    )
    req.add_argument(
        "--compliance", "-C",
        required = True,
        metavar  = "FILE",
        help     = "Stage 6 compliance report JSON.",
    )
    req.add_argument(
        "--remediation", "-r",
        required = True,
        metavar  = "FILE",
        help     = "Stage 8 remediation proposals JSON (list).",
    )

    # ── Optional inputs ───────────────────────────────────────────────────────
    opt = run_p.add_argument_group("optional inputs")
    opt.add_argument(
        "--obligations", "-b",
        default  = "stage4_5_obligation_analysis.json",
        metavar  = "FILE",
        help     = "Stage 4.5 obligation analysis JSON "
                   "(default: stage4_5_obligation_analysis.json).",
    )

    # ── Output control ────────────────────────────────────────────────────────
    out = run_p.add_argument_group("output control")
    out.add_argument(
        "--output-dir", "-o",
        default  = "/outputs",
        metavar  = "DIR",
        help     = "Directory to write all pipeline outputs (default: /outputs).",
    )

    run_p.set_defaults(func=cmd_run)
    return parser


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
