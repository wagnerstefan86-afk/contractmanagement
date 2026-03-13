"""
Pipeline integration layer.

Responsibilities
----------------
1. Run stage16 ingestion on an uploaded contract file.
2. Run the full real pipeline: stage3 → stage4_5 → stage5 → stage6 → stage8
3. Run contract_audit stages 9-14 programmatically.
4. Return structured results that the API layer stores in the database.

Thread safety
-------------
All functions here are synchronous and designed to run in a worker thread
(via FastAPI BackgroundTasks or asyncio.to_thread).  Each call uses its own
filesystem paths and database session — no shared mutable state.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from .config import PROJECT_DIR

# Ensure the project root is in sys.path so stage modules can import llm.*
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# ── Stage-module loader ───────────────────────────────────────────────────────

def _load_module(name: str, path: Path) -> Any:
    """Load a Python source file as a module by absolute path.

    The module is registered in sys.modules under *name* before exec so that
    decorators like @dataclass can resolve cls.__module__ correctly.
    """
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod  = importlib.util.module_from_spec(spec)          # type: ignore[arg-type]
    sys.modules[name] = mod                               # must precede exec_module
    spec.loader.exec_module(mod)                           # type: ignore[union-attr]
    return mod


# Load all stage modules once at import time so that sub-module references are
# initialised before any request arrives.  Trades a few seconds of startup
# time for fast responses.

_ingestion = _load_module("stage16_contract_ingestion", PROJECT_DIR / "stage16_contract_ingestion.py")
_stage3    = _load_module("stage3_contract_classification", PROJECT_DIR / "stage3_contract_classification.py")
_stage4_5  = _load_module("stage4_5_obligation_analysis",   PROJECT_DIR / "stage4_5_obligation_analysis.py")
_stage5    = _load_module("stage5_matching",                PROJECT_DIR / "stage5_matching.py")
_stage6    = _load_module("stage6_compliance",              PROJECT_DIR / "stage6_compliance.py")
_stage8    = _load_module("stage8_remediation_generator",   PROJECT_DIR / "stage8_remediation_generator.py")
_audit     = _load_module("contract_audit",                 PROJECT_DIR / "contract_audit.py")
_audit._load_stage_modules()


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 16 — INGESTION
# ═══════════════════════════════════════════════════════════════════════════════

class IngestionError(RuntimeError):
    """Raised when stage16 fails for any reason."""


def run_ingestion(contract_file: Path, output_dir: Path, llm_provider: Any = None) -> list[dict]:
    """
    Run stage16 on *contract_file* and write stage4_clauses.json into
    *output_dir*.

    Returns
    -------
    list[dict]
        The extracted clauses list (also written to disk).

    Raises
    ------
    IngestionError
        On any extraction or I/O failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    clauses_path = output_dir / "stage4_clauses.json"

    try:
        clauses = _ingestion.ingest(contract_file, llm_provider=llm_provider)
    except Exception as exc:
        raise IngestionError(f"Stage16 ingestion failed: {exc}") from exc

    if not clauses:
        raise IngestionError(
            f"Stage16 produced 0 clauses from {contract_file.name}. "
            "The file may be empty, encrypted, or have no parseable text."
        )

    clauses_path.write_text(
        json.dumps(clauses, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return clauses


# ═══════════════════════════════════════════════════════════════════════════════
# STAGES 9-14 — AUDIT PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

class PipelineError(RuntimeError):
    """Raised when any stage 9-14 fails."""


def run_audit_pipeline(
    paths:          dict[str, Path | None],
    contract_id:    str,
    output_dir:     Path,
    stage_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Execute stages 9-14 sequentially using contract_audit's per-stage
    functions.

    Parameters
    ----------
    paths
        Mapping containing keys:
        ``clauses``, ``clause_matches``, ``compliance``, ``remediation``,
        ``obligations`` (may be None).
    contract_id
        The canonical contract identifier (used for audit trace filename).
    output_dir
        Where all stage outputs will be written.
    stage_callback
        Optional callable invoked with the stage name string immediately
        before each stage executes.  Used to persist progress to the DB.

    Returns
    -------
    dict
        The Stage 14 report payload (``contract_risk_report.json`` contents).

    Raises
    ------
    PipelineError
        On any stage failure.
    """
    def _cb(stage: str) -> None:
        if stage_callback:
            try:
                stage_callback(stage)
            except Exception:
                pass  # never let a callback failure abort the pipeline

    try:
        # Stage 9 — Negotiation Brief
        _cb("stage9_brief")
        brief = _audit.run_stage9(
            clauses_path        = paths["clauses"],
            clause_matches_path = paths["clause_matches"],
            compliance_path     = paths["compliance"],
            remediation_path    = paths["remediation"],
            obligations_path    = paths.get("obligations"),
            output_dir          = output_dir,
        )

        # Stage 10 — Audit Trace
        _cb("stage10_trace")
        trace = _audit.run_stage10(
            clauses_path        = paths["clauses"],
            obligations_path    = paths.get("obligations"),
            clause_matches_path = paths["clause_matches"],
            compliance_path     = paths["compliance"],
            remediation_path    = paths["remediation"],
            brief               = brief,
            output_dir          = output_dir,
            contract_id         = contract_id,
        )

        # Stage 11 — Risk Scoring
        _cb("stage11_risk")
        scoring = _audit.run_stage11(
            trace            = trace,
            brief            = brief,
            remediation_path = paths["remediation"],
            output_dir       = output_dir,
        )

        # Stage 12 — Action Plan
        _cb("stage12_action_plan")
        plan = _audit.run_stage12(
            trace            = trace,
            brief            = brief,
            scores           = scoring,
            remediation_path = paths["remediation"],
            output_dir       = output_dir,
        )

        # Stage 13 — Negotiation Package
        _cb("stage13_negotiation")
        pkg = _audit.run_stage13(
            plan             = plan,
            brief            = brief,
            trace            = trace,
            scores           = scoring,
            remediation_path = paths["remediation"],
            output_dir       = output_dir,
        )

        # Stage 14 — Contract Risk Report
        _cb("stage14_report")
        report = _audit.run_stage14(
            scores     = scoring,
            plan       = plan,
            pkg        = pkg,
            trace      = trace,
            brief      = brief,
            output_dir = output_dir,
        )

    except SystemExit as exc:
        # contract_audit calls sys.exit() only in _fatal(); catching here
        # prevents the worker thread from killing the whole process.
        raise PipelineError(f"Pipeline aborted (exit code {exc.code})") from exc
    except (FileNotFoundError, ValueError) as exc:
        raise PipelineError(str(exc)) from exc
    except Exception as exc:
        raise PipelineError(
            f"Unexpected pipeline error in stage: {exc}\n"
            + traceback.format_exc()
        ) from exc

    return report


# ═══════════════════════════════════════════════════════════════════════════════
# HIGH-LEVEL ORCHESTRATORS (called from background tasks)
# ═══════════════════════════════════════════════════════════════════════════════

class IngestionResult:
    __slots__ = ("clauses", "error")

    def __init__(self, clauses: list[dict] | None, error: str | None):
        self.clauses = clauses
        self.error   = error

    @property
    def ok(self) -> bool:
        return self.error is None


class AnalysisResult:
    __slots__ = ("report", "error")

    def __init__(self, report: dict | None, error: str | None):
        self.report = report
        self.error  = error

    @property
    def ok(self) -> bool:
        return self.error is None


def ingest_contract(contract_file: Path, output_dir: Path, llm_provider: Any = None) -> IngestionResult:
    """
    Top-level ingestion wrapper — safe to call from a background task.
    Never raises; returns an IngestionResult with error set on failure.
    """
    try:
        clauses = run_ingestion(contract_file, output_dir, llm_provider=llm_provider)
        return IngestionResult(clauses=clauses, error=None)
    except IngestionError as exc:
        return IngestionResult(clauses=None, error=str(exc))
    except Exception as exc:
        return IngestionResult(
            clauses=None,
            error=f"Unexpected ingestion error: {exc}\n" + traceback.format_exc(),
        )


def validate_org_profile(profile: dict | None) -> str | None:
    """
    Return a human-readable error string if *profile* is absent or incomplete,
    or ``None`` if it is valid and ready for use by the pipeline.

    Checks performed:
    - Profile must be present (not None).
    - ``organization_name`` must be a non-empty string.
    - ``regulatory_frameworks`` must be a non-empty list.
    - ``data_classification_levels`` must be a non-empty list.
    """
    if profile is None:
        return (
            "Customer compliance profile is not configured. "
            "Please complete /settings/customer-profile before running analysis."
        )
    if not str(profile.get("organization_name", "")).strip():
        return (
            "Compliance profile is missing organization_name. "
            "Please update /settings/customer-profile."
        )
    if not profile.get("regulatory_frameworks"):
        return (
            "Compliance profile must have at least one regulatory framework. "
            "Please update /settings/customer-profile."
        )
    if not profile.get("data_classification_levels"):
        return (
            "Compliance profile must have at least one data classification level. "
            "Please update /settings/customer-profile."
        )
    return None


def analyze_contract(
    contract_file:  Path,
    output_dir:     Path,
    contract_id:    str,
    org_profile:    dict,
    stage_callback: Callable[[str], None] | None = None,
    llm_overrides:  dict | None = None,
) -> AnalysisResult:
    """
    Full pipeline orchestrator:
      1. Stage 16 — contract ingestion
      2. Stage 3  — contract classification (type, risk tier, data sensitivity)
      3. Stage 4.5 — obligation analysis
      4. Stage 5  — clause-to-SR matching (uses org_profile)
      5. Stage 6  — compliance report generation
      6. Stage 8  — remediation proposal generation
      7. Stages 9-14 — audit pipeline (brief → trace → scoring → plan → pkg → report)

    ``org_profile`` is mandatory — callers must validate with
    :func:`validate_org_profile` before calling this function.

    ``stage_callback`` is called with the stage name string before each
    stage so the caller can persist progress to the database.

    Safe to call from a background task; never raises.
    Returns an AnalysisResult with error set on failure.
    """
    def _cb(stage: str) -> None:
        if stage_callback:
            try:
                stage_callback(stage)
            except Exception:
                pass

    # Guard: should have been validated by the caller, but defend in depth
    profile_err = validate_org_profile(org_profile)
    if profile_err:
        return AnalysisResult(report=None, error=profile_err)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Canonical file paths used throughout the pipeline
    clauses_path     = output_dir / "stage4_clauses.json"
    metadata_path    = output_dir / "contract_metadata.json"
    obligations_path = output_dir / "stage4_5_obligation_analysis.json"
    org_profile_path = output_dir / "org_profile.json"
    matches_path     = output_dir / "clause_sr_matches.json"
    compliance_path  = output_dir / f"stage6_compliance_{contract_id}.json"
    remediation_path = output_dir / "stage8_remediation_proposals.json"

    try:
        # ── Initialise LLM provider (shared across all LLM stages incl. 16) ──
        # llm_overrides carries DB-backed admin config (provider, model, api_key,
        # timeout, app_enabled).  Falls back to env-var defaults when not supplied.
        _overrides = llm_overrides or {}
        llm_provider: Optional[Any] = None
        try:
            from llm.config import get_llm_provider as _get_llm
            if _overrides.get("app_enabled", True):
                llm_provider = _get_llm(
                    provider_override = _overrides.get("provider") or None,
                    model_override    = _overrides.get("model")    or None,
                    api_key_override  = _overrides.get("api_key")  or None,
                )
            # else: app_enabled=False → stay None → deterministic fallback
        except Exception:
            pass  # LLM unavailable — all stages fall back to deterministic

        # ── Stage 16: Ingestion (LLM-assisted segmentation when available) ───
        _cb("stage16_ingestion")
        ing = ingest_contract(contract_file, output_dir, llm_provider=llm_provider)
        if not ing.ok:
            return AnalysisResult(report=None, error=ing.error)

        # ── Stage 3: Contract Classification ─────────────────────────────────
        _cb("stage3_classification")
        _stage3.run(
            input_path   = str(clauses_path),
            contract_id  = contract_id,
            output_path  = str(metadata_path),
            skip_llm     = False,
            api_key      = _overrides.get("api_key") or None,
        )

        # ── Stage 4.5: Obligation Analysis ────────────────────────────────────
        _cb("stage4_5_obligation_analysis")
        _stage4_5.run(
            input_path    = str(clauses_path),
            output_path   = str(obligations_path),
            include_valid = False,
            llm_provider  = llm_provider,
        )

        # ── Write org_profile.json for use by stage 5 & 6 ────────────────────
        org_profile_path.write_text(
            json.dumps(org_profile, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # ── Stage 5: Clause-to-SR Matching ────────────────────────────────────
        _cb("stage5_clause_matching")
        _stage5.run(
            org_profile_path = str(org_profile_path),
            metadata_path    = str(metadata_path),
            clauses_path     = str(clauses_path),
            output_path      = str(matches_path),
            llm_provider     = llm_provider,
        )

        # ── Stage 6: Compliance Report ────────────────────────────────────────
        _cb("stage6_compliance")
        clause_matches, stage45, org, metadata = _stage6.load_inputs(
            clause_matches_path = str(matches_path),
            stage45_path        = str(obligations_path),
            org_profile_path    = str(org_profile_path),
            metadata_path       = str(metadata_path),
        )
        compliance_report = _stage6.generate_report(clause_matches, stage45, org, metadata)
        compliance_path.write_text(
            json.dumps(compliance_report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # ── Stage 8: Remediation Proposals ───────────────────────────────────
        _cb("stage8_remediation")
        clause_index     = _stage8._build_clause_index(str(clauses_path))
        obligations_data = json.loads(obligations_path.read_text(encoding="utf-8"))
        findings         = _stage8.extract_findings(compliance_report, obligations_data)

        proposals = _stage8.generate_proposals(
            findings     = findings,
            clause_index = clause_index,
            llm_provider = llm_provider,
            verbose      = False,
        )
        remediation_path.write_text(
            json.dumps(proposals, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    except (IngestionError, PipelineError):
        raise
    except SystemExit as exc:
        return AnalysisResult(
            report=None,
            error=f"Stage aborted (exit code {exc.code})",
        )
    except Exception as exc:
        return AnalysisResult(
            report=None,
            error=f"Pipeline preparation failed: {exc}\n" + traceback.format_exc(),
        )

    # ── Stages 9-14: Audit Pipeline ──────────────────────────────────────────
    paths = {
        "clauses":        clauses_path,
        "clause_matches": matches_path,
        "compliance":     compliance_path,
        "remediation":    remediation_path,
        "obligations":    obligations_path,
    }
    try:
        report = run_audit_pipeline(paths, contract_id, output_dir,
                                    stage_callback=stage_callback)
        _cb("done")
        return AnalysisResult(report=report, error=None)
    except PipelineError as exc:
        return AnalysisResult(report=None, error=str(exc))
