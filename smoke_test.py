#!/usr/bin/env python3
"""
Contract Analysis Platform — End-to-End Smoke Test

Exercises the full CLI pipeline from contract ingestion (Stage 16)
through audit reporting (Stages 9-14) using the bundled smoke contract.

Runs deterministic-only by default (LLM_ENABLED=false).
Set LLM_ENABLED=true and provide API credentials to include LLM passes.

Usage
-----
  python smoke_test.py                  # deterministic, all stages
  LLM_ENABLED=true python smoke_test.py # include LLM passes

Exit codes
----------
  0  All checks passed
  1  One or more stages failed

Output
------
  All stage artifacts are written to a temporary directory under /tmp.
  The path is printed at the top and preserved on failure for inspection.
  On success, the directory is cleaned up automatically.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────

_HERE          = Path(__file__).resolve().parent
_FIXTURE_DIR   = _HERE / "tests" / "fixtures"
_SMOKE_CONTRACT = _FIXTURE_DIR / "smoke_contract.txt"

_LLM_ENABLED = os.environ.get("LLM_ENABLED", "false").strip().lower() not in (
    "false", "0", "no", "off"
)

# Contract fixture metadata written into the temp workspace
_ORG_PROFILE = {
    "organization_name":    "Smoke Test Org",
    "industry":             "Financial Services",
    "regulatory_frameworks": ["ISO27001", "GDPR", "DORA", "NIS2"],
}

_CONTRACT_METADATA = {
    "contract_id":      "CT-SMOKE-001",
    "contract_type":    "SAAS",
    "vendor_risk_tier": "HIGH",
    "data_sensitivity": "PERSONAL_DATA",
}

# ── Helpers ────────────────────────────────────────────────────────────────────

_results: list[tuple[str, bool, str]] = []   # (label, passed, detail)


def _run(label: str, cmd: list[str], *, cwd: Path, env: dict | None = None) -> bool:
    """Run a subprocess, record pass/fail, return True on success."""
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    passed = result.returncode == 0
    detail = ""
    if not passed:
        stderr = result.stderr.strip()[-600:] if result.stderr else ""
        stdout = result.stdout.strip()[-200:] if result.stdout else ""
        detail = f"exit={result.returncode}"
        if stderr:
            detail += f"\nSTDERR: {stderr}"
        if stdout:
            detail += f"\nSTDOUT: {stdout}"
    _results.append((label, passed, detail))
    return passed


def _check(label: str, condition: bool, detail: str = "") -> bool:
    """Record a boolean assertion."""
    _results.append((label, condition, detail))
    return condition


def _load_json(path: Path) -> dict | list | None:
    """Load JSON or return None on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _field_check(label: str, path: Path, *keys: str) -> bool:
    """Verify a JSON file exists and contains the given top-level keys."""
    data = _load_json(path)
    if data is None:
        _check(label, False, f"{path.name} missing or invalid JSON")
        return False
    if isinstance(data, list):
        ok = len(data) > 0
        _check(label, ok, f"{path.name}: expected non-empty list, got {len(data)} items")
        return ok
    missing = [k for k in keys if k not in data]
    ok = len(missing) == 0
    _check(label, ok, f"{path.name}: missing keys {missing}" if not ok else "")
    return ok


# ── Main smoke test ────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 68)
    print("  Contract Analysis Platform — End-to-End Smoke Test")
    print("=" * 68)
    print(f"  Contract:  {_SMOKE_CONTRACT.name}")
    print(f"  LLM mode:  {'enabled (live calls)' if _LLM_ENABLED else 'disabled (deterministic)'}")

    if not _SMOKE_CONTRACT.exists():
        print(f"\n  [ERROR] Smoke contract not found: {_SMOKE_CONTRACT}")
        print("  Run from the project root: python smoke_test.py")
        return 1

    # Create temp workspace
    tmp = Path(tempfile.mkdtemp(prefix="cap_smoke_"))
    print(f"  Workspace: {tmp}")
    print()

    # Determine LLM flags for stages that accept --no-llm
    no_llm_flag = [] if _LLM_ENABLED else ["--no-llm"]
    stage_env   = {"LLM_ENABLED": "true" if _LLM_ENABLED else "false"}

    # Write fixture files into workspace
    (tmp / "org_profile.json").write_text(json.dumps(_ORG_PROFILE, indent=2))
    (tmp / "contract_metadata.json").write_text(json.dumps(_CONTRACT_METADATA, indent=2))

    # ── Startup check ──────────────────────────────────────────────────────────
    print("  ── Startup Check ──────────────────────────────────────────────")
    _run(
        "Config validation",
        [sys.executable, "-m", "backend.startup_check"],
        cwd=_HERE,
        env=stage_env,
    )

    # ── Stage 16: Contract Ingestion ───────────────────────────────────────────
    print("  ── Stage 16: Contract Ingestion ───────────────────────────────")
    clauses_path = tmp / "stage4_clauses.json"
    ok16 = _run(
        "Stage 16 exit 0",
        [
            sys.executable, str(_HERE / "stage16_contract_ingestion.py"),
            "--contract", str(_SMOKE_CONTRACT),
            "--output",   str(clauses_path),
            "--quiet",
        ],
        cwd=tmp,
    )
    if ok16:
        clauses = _load_json(clauses_path)
        clause_count = len(clauses) if isinstance(clauses, list) else 0
        _check("Stage 16 produces clauses", clause_count > 0,
               f"got {clause_count} clauses")
        _check("Stage 16 clause schema", clause_count > 0 and all(
            "clause_id" in c and "text" in c for c in (clauses or [])
        ), "missing clause_id or text")

    # ── Stage 4.5: Obligation Analysis ────────────────────────────────────────
    print("  ── Stage 4.5: Obligation Analysis ─────────────────────────────")
    obligations_path = tmp / "stage4_5_obligation_analysis.json"
    ok45 = _run(
        "Stage 4.5 exit 0",
        [
            sys.executable, str(_HERE / "stage4_5_obligation_analysis.py"),
            str(clauses_path),
            "--output", str(obligations_path),
        ] + no_llm_flag,
        cwd=tmp,
        env=stage_env,
    )
    if ok45:
        _check("Stage 4.5 output file created", obligations_path.exists())
        obs = _load_json(obligations_path)
        _check("Stage 4.5 output is a list", isinstance(obs, list),
               f"got type {type(obs).__name__}")

    # ── Stage 5: Clause-to-SR Matching ────────────────────────────────────────
    print("  ── Stage 5: Clause-to-SR Matching ─────────────────────────────")
    matches_path = tmp / "clause_sr_matches.json"
    ok5 = _run(
        "Stage 5 exit 0",
        [
            sys.executable, str(_HERE / "stage5_matching.py"),
            "--org-profile", str(tmp / "org_profile.json"),
            "--metadata",    str(tmp / "contract_metadata.json"),
            "--clauses",     str(clauses_path),
            "--output",      str(matches_path),
        ] + no_llm_flag,
        cwd=tmp,
        env=stage_env,
    )
    if ok5:
        matches = _load_json(matches_path)
        _check("Stage 5 output is a list", isinstance(matches, list))
        if isinstance(matches, list) and matches:
            sample = matches[0]
            _check("Stage 5 match schema: sr_id present",    "sr_id"    in sample)
            _check("Stage 5 match schema: match_type present", "match_type" in sample)
            _check("Stage 5 match schema: _ai_metadata present", "_ai_metadata" in sample)
            # Verify deterministic metadata when LLM is off
            if not _LLM_ENABLED:
                ai_meta = sample.get("_ai_metadata", {})
                _check(
                    "Stage 5 _ai_metadata.llm_used=false (deterministic mode)",
                    ai_meta.get("llm_used") is False,
                    f"got {ai_meta.get('llm_used')!r}",
                )
            direct_matches = [m for m in matches if m.get("match_type") == "DIRECT_MATCH"]
            _check("Stage 5 produces at least 5 DIRECT_MATCHes",
                   len(direct_matches) >= 5,
                   f"got {len(direct_matches)}")

    # ── Stage 6: Compliance Report ────────────────────────────────────────────
    print("  ── Stage 6: Compliance Report ─────────────────────────────────")
    compliance_path = tmp / "stage6_compliance.json"
    ok6 = _run(
        "Stage 6 exit 0 or 1",    # exit 1 = HIGH findings present (expected)
        [
            sys.executable, str(_HERE / "stage6_compliance.py"),
            "--clause-matches", str(matches_path),
            "--stage45",        str(obligations_path),
            "--org-profile",    str(tmp / "org_profile.json"),
            "--metadata",       str(tmp / "contract_metadata.json"),
            "--output",         str(compliance_path),
            "--quiet",
        ],
        cwd=tmp,
        env=stage_env,
    )
    # Stage 6 exits 1 when HIGH findings exist — that is valid behavior
    if not ok6:
        # Re-check: did it create the output file despite exit 1?
        if compliance_path.exists():
            _results[-1] = ("Stage 6 exit 0 or 1", True, "exit 1 (HIGH findings found — expected)")
            ok6 = True
    if ok6:
        _field_check("Stage 6 output schema", compliance_path,
                     "contract_id", "generated_at", "sr_compliance")

    # ── Stage 8: Remediation Proposals ───────────────────────────────────────
    print("  ── Stage 8: Remediation Proposals ─────────────────────────────")
    remediation_path = tmp / "stage8_remediation_proposals.json"
    ok8 = _run(
        "Stage 8 exit 0",
        [
            sys.executable, str(_HERE / "stage8_remediation_generator.py"),
            "--compliance",   str(compliance_path),
            "--obligations",  str(obligations_path),
            "--clauses",      str(clauses_path),
            "--output",       str(remediation_path),
            "--quiet",
        ] + no_llm_flag,
        cwd=tmp,
        env=stage_env,
    )
    if ok8:
        rems = _load_json(remediation_path)
        _check("Stage 8 output is a list", isinstance(rems, list))
        if isinstance(rems, list) and rems:
            r = rems[0]
            for field in ("finding_type", "problem_summary", "suggested_clause"):
                _check(f"Stage 8 record has '{field}'", field in r)
            ai_meta = r.get("_ai_metadata", {})
            _check("Stage 8 _ai_metadata present", bool(ai_meta))
            if not _LLM_ENABLED:
                _check(
                    "Stage 8 _ai_metadata.llm_used=false (deterministic mode)",
                    ai_meta.get("llm_used") is False,
                    f"got {ai_meta.get('llm_used')!r}",
                )

    # ── Stages 9-14: Audit Pipeline ──────────────────────────────────────────
    print("  ── Stages 9-14: Audit Pipeline ────────────────────────────────")
    audit_dir = tmp / "audit_output"
    ok_audit = _run(
        "Stages 9-14 exit 0 or 1",    # exit 1 = HIGH risks (expected)
        [
            sys.executable, str(_HERE / "contract_audit.py"), "run",
            "--clauses",        str(clauses_path),
            "--clause-matches", str(matches_path),
            "--compliance",     str(compliance_path),
            "--remediation",    str(remediation_path),
            "--obligations",    str(obligations_path),
            "--output-dir",     str(audit_dir),
        ],
        cwd=tmp,
    )
    if not ok_audit:
        if audit_dir.exists():
            _results[-1] = ("Stages 9-14 exit 0 or 1", True, "exit 1 (HIGH risks — expected)")
            ok_audit = True

    if ok_audit:
        expected_artifacts = {
            "contract_negotiation_brief.json": ("contract_id", "topics"),
            "audit_trace_*.json":              None,
            "risk_scoring.json":               ("contract_id", "clause_scores"),
            "action_plan.json":                ("actions",),
            "negotiation_package.json":        ("contract_id", "negotiation_items"),
            "contract_risk_report.json":       ("contract_id", "risk_distribution"),
        }
        for pattern, req_keys in expected_artifacts.items():
            matches_glob = list(audit_dir.glob(pattern))
            if matches_glob:
                artifact = matches_glob[0]
                _check(f"Artifact exists: {pattern}", True)
                if req_keys:
                    _field_check(f"Artifact schema: {pattern}", artifact, *req_keys)
            else:
                _check(f"Artifact exists: {pattern}", False, f"not found in {audit_dir}")

    # ── Eval artifacts NOT written (eval mode disabled) ───────────────────────
    print("  ── Eval Mode Guard ────────────────────────────────────────────")
    eval_artifacts = list(tmp.rglob("benchmark_*.json"))
    _check(
        "Eval artifacts not written (CONTRACT_EVAL_MODE=false)",
        len(eval_artifacts) == 0,
        f"unexpected files: {[f.name for f in eval_artifacts]}",
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 68)
    print("  Results")
    print("=" * 68)
    passed = sum(1 for _, ok, _ in _results if ok)
    total  = len(_results)
    for label, ok, detail in _results:
        icon = "PASS" if ok else "FAIL"
        print(f"  [{icon}] {label}")
        if detail and not ok:
            for line in detail.splitlines():
                print(f"         {line}")

    print()
    print(f"  {passed}/{total} checks passed")
    if passed == total:
        print("  Smoke test PASSED — platform is ready for testing.")
        shutil.rmtree(tmp, ignore_errors=True)
        return 0
    else:
        print(f"  Smoke test FAILED — {total - passed} check(s) failed.")
        print(f"  Artifacts preserved for inspection: {tmp}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
