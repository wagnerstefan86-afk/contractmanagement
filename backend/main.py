"""
Contract Analysis Platform — FastAPI backend (v2 with auth + RBAC).

Auth endpoints (public)
-----------------------
POST   /auth/register        Self-register; first user per tenant becomes ADMIN
POST   /auth/login           Exchange credentials for a JWT Bearer token
GET    /auth/me              Return the calling user's profile

Customer endpoints (ADMIN only, tenant-scoped)
----------------------------------------------
POST   /customers            Create a customer org (or bootstrap if DB is empty)
GET    /customers/me         Return the calling user's own customer
GET    /customers/me/profile Return the tenant's org profile (all roles)
PUT    /customers/me/profile Update the tenant's org profile (ADMIN only)

User management (ADMIN only, tenant-scoped)
-------------------------------------------
POST   /users                Create a user in the ADMIN's tenant
GET    /users                List users in the ADMIN's tenant

Contract endpoints (tenant-scoped)
------------------------------------
POST   /contracts/upload     ADMIN | ANALYST — upload + queue ingestion (creates case + v1)
GET    /contracts            ALL roles       — list tenant's contracts
GET    /contracts/{id}       ALL roles       — single contract
POST   /contracts/{id}/analyze  ADMIN | ANALYST — queue audit pipeline (uses current version)
GET    /contracts/{id}/analyses ALL roles    — list analysis runs
GET    /contracts/{id}/analyses/{aid}  ALL roles — single analysis status
GET    /contracts/{id}/status   ALL roles    — latest analysis status
GET    /contracts/{id}/report   ALL roles    — risk report JSON (latest completed analysis)
GET    /contracts/{id}/negotiation ALL roles — negotiation package JSON (latest)

Version endpoints (tenant-scoped)
------------------------------------
POST   /contracts/{id}/versions/upload         ADMIN | ANALYST — upload a new version
GET    /contracts/{id}/versions                ALL roles       — list versions
GET    /contracts/{id}/versions/{vid}          ALL roles       — single version
POST   /contracts/{id}/versions/{vid}/analyze  ADMIN | ANALYST — run pipeline on version
GET    /contracts/{id}/versions/{vid}/report   ALL roles       — risk report for version
GET    /contracts/{id}/versions/{vid}/negotiation ALL roles    — negotiation pkg for version
PATCH  /contracts/{id}/versions/{vid}/review-status ADMIN|ANALYST — update version workflow
GET    /contracts/{id}/versions/{vid}/workflow ALL roles       — workflow state for version
GET    /contracts/{id}/versions/{vid}/history  ALL roles       — history for version
GET    /contracts/{id}/compare                 ALL roles       — compare two versions

Finding review endpoints (tenant-scoped)
------------------------------------
GET    /contracts/{id}/versions/{vid}/findings/summary        ALL roles — counts by status/severity + readiness
GET    /contracts/{id}/versions/{vid}/findings                ALL roles — list finding reviews
PATCH  /contracts/{id}/versions/{vid}/findings/{key}          ADMIN|ANALYST — update a finding review
GET    /contracts/{id}/versions/{vid}/approval-readiness      ALL roles — approval readiness evaluation
GET    /contracts/{id}/versions/{vid}/closure-bundle          ALL roles — closure bundle manifest
GET    /contracts/{id}/versions/{vid}/closure-bundle/download ALL roles — download ZIP archive

Unauthenticated access → 401
Wrong role            → 403
Cross-tenant access   → 404  (prevents resource enumeration)
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("infosec.backend")

import aiofiles
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from .auth import create_access_token, hash_password, verify_password
from .config import (
    ALLOWED_EXTENSIONS,
    ANALYSES_DIR,
    CONTRACTS_DIR,
    JWT_EXPIRY_HOURS,
    MAX_FILE_BYTES,
    LLM_ENABLED,
    LLM_PROVIDER,
    LLM_MODEL,
    LLM_TIMEOUT_SECONDS,
)
from .database import Base, engine, get_db
from .deps import (
    get_current_user,
    get_tenant_contract,
    require_admin,
    require_analyst_above,
    require_any_role,
)
from .models import Analysis, AppSetting, Contract, ContractVersion, ContractWorkflowEvent, Customer, FindingReview, User, UserRole
from .pipeline import analyze_contract, ingest_contract, validate_org_profile
from .schemas import (
    ADMIN_ONLY_STATUSES,
    ANALYST_FINDING_STATUSES,
    ANALYST_SETTABLE_STATUSES,
    AnalysisOut,
    AnalysisStatusOut,
    ApprovalReadinessOut,
    BlockingFinding,
    ClauseDetailOut,
    ClauseFindingOut,
    ClauseListItem,
    ClauseListOut,
    ClauseRiskScoreOut,
    ClosureBundleManifestOut,
    ClosureBundleOut,
    CompareVersionOut,
    ContractListOut,
    ContractOut,
    ContractSummaryOut,
    ContractVersionOut,
    CustomerCreate,
    CustomerOut,
    FindingReviewOut,
    FindingReviewUpdate,
    FindingsListOut,
    FindingsSummaryOut,
    FindingsSummaryWithReadinessOut,
    FindingTypeItem,
    HistoryOut,
    LLMAppSettingUpdate,
    LLMConfigOut,
    LLMConfigUpdate,
    LLMTestResult,
    LoginIn,
    NegotiationItemOut,
    NegotiationOut,
    ObligationAssessmentOut,
    OrgProfileIn,
    OrgProfileOut,
    READINESS_ORDER,
    ReadinessCounts,
    RegisterIn,
    RegulatoryFrameworkItem,
    ReportOut,
    ReviewStatusUpdate,
    RiskSummaryOut,
    RiskTopicItem,
    SRMatchOut,
    TokenOut,
    UserCreate,
    UserOut,
    VersionListOut,
    WorkflowEventOut,
    WorkflowOut,
)

# ── App bootstrap ─────────────────────────────────────────────────────────────

app = FastAPI(
    title       = "Contract Analysis Platform",
    description = (
        "Multi-tenant contract ingestion and audit pipeline. "
        "All data is tenant-isolated; JWT Bearer authentication is required "
        "on all endpoints except /auth/register, /auth/login, and /health."
    ),
    version     = "2.0.0",
)

# ── CORS — allow browser-based frontends to reach the API ─────────────────────
# CORS_ORIGINS is a comma-separated list of allowed origins.
# Default "*" is intentionally permissive for test deployments only.
# Override with e.g. CORS_ORIGINS=http://myserver:3000 for a tighter setup.
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "*")
_cors_origins = (
    ["*"]
    if _cors_origins_raw.strip() == "*"
    else [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins     = _cors_origins,
    allow_credentials = _cors_origins_raw.strip() != "*",   # credentials require explicit origins
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


@app.on_event("startup")
def _startup() -> None:
    Base.metadata.create_all(bind=engine)
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    ANALYSES_DIR.mkdir(parents=True, exist_ok=True)
    # Migrate: add columns/tables introduced in v2.1+ if they don't exist yet
    _migrate_tables()
    # Mark any analysis runs that are still "running" or "pending" from a
    # previous server process as "failed" — they cannot be resumed, and
    # leaving them in a non-terminal state would cause the UI to poll forever.
    _recover_stale_runs()


def _migrate_tables() -> None:
    """Idempotently add new columns and tables (SQLite-safe)."""
    from sqlalchemy import text
    with engine.connect() as conn:
        # ── analyses: columns added in v2.1 ──────────────────────────────────
        analyses_cols = {
            "current_stage":             "VARCHAR(50)",
            "outputs_ready":             "BOOLEAN NOT NULL DEFAULT 0",
            "org_profile_snapshot_path": "VARCHAR(1024)",
            "org_profile_version_hash":  "VARCHAR(64)",
        }
        existing_an = {row[1] for row in conn.execute(text("PRAGMA table_info(analyses)"))}
        for col, col_def in analyses_cols.items():
            if col not in existing_an:
                conn.execute(text(f"ALTER TABLE analyses ADD COLUMN {col} {col_def}"))

        # ── contracts: workflow columns added in v2.2 ─────────────────────────
        contract_cols = {
            "review_status":        "VARCHAR(30) NOT NULL DEFAULT 'uploaded'",
            "review_decision":      "VARCHAR(30) NOT NULL DEFAULT 'none'",
            "review_owner_user_id": "INTEGER REFERENCES users(id) ON DELETE SET NULL",
            "reviewed_at":          "DATETIME",
            "internal_notes":       "TEXT",
        }
        existing_ct = {row[1] for row in conn.execute(text("PRAGMA table_info(contracts)"))}
        for col, col_def in contract_cols.items():
            if col not in existing_ct:
                conn.execute(text(f"ALTER TABLE contracts ADD COLUMN {col} {col_def}"))

        # ── contract_workflow_events: new in v2.2 ─────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contract_workflow_events (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id         VARCHAR(50) NOT NULL,
                changed_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
                old_status          VARCHAR(30),
                new_status          VARCHAR(30) NOT NULL,
                old_decision        VARCHAR(30),
                new_decision        VARCHAR(30),
                notes               TEXT,
                created_at          DATETIME NOT NULL
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_workflow_events_contract_id "
            "ON contract_workflow_events (contract_id)"
        ))

        # ── contract_versions: new in v2.3 ────────────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contract_versions (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_db_id        INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
                contract_id           VARCHAR(50) NOT NULL,
                version_number        INTEGER NOT NULL,
                file_path             VARCHAR(1024) NOT NULL,
                original_filename     VARCHAR(512) NOT NULL,
                status                VARCHAR(20) NOT NULL DEFAULT 'uploaded',
                clauses_extracted     INTEGER,
                error_message         TEXT,
                uploaded_by_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                review_status         VARCHAR(30) NOT NULL DEFAULT 'uploaded',
                review_decision       VARCHAR(30) NOT NULL DEFAULT 'none',
                review_owner_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
                reviewed_at           DATETIME,
                internal_notes        TEXT,
                uploaded_at           DATETIME NOT NULL
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_contract_versions_contract_id "
            "ON contract_versions (contract_id)"
        ))

        # contracts: add current_version_id column (v2.3)
        if "current_version_id" not in existing_ct:
            conn.execute(text("ALTER TABLE contracts ADD COLUMN current_version_id INTEGER"))

        # analyses: add version_id column (v2.3)
        if "version_id" not in existing_an:
            conn.execute(text("ALTER TABLE analyses ADD COLUMN version_id INTEGER"))

        # ── Data migration: create v1 version row for each existing contract ──
        contracts_rows = conn.execute(text(
            "SELECT id, contract_id, file_path, filename, status, clauses_extracted, "
            "error_message, uploaded_by, review_status, review_decision, "
            "review_owner_user_id, reviewed_at, internal_notes, created_at "
            "FROM contracts"
        )).fetchall()
        for row in contracts_rows:
            existing_v1 = conn.execute(text(
                "SELECT id FROM contract_versions "
                "WHERE contract_id = :cid AND version_number = 1"
            ), {"cid": row[1]}).fetchone()
            if existing_v1 is None:
                conn.execute(text("""
                    INSERT INTO contract_versions
                        (contract_db_id, contract_id, version_number, file_path,
                         original_filename, status, clauses_extracted, error_message,
                         uploaded_by_user_id, review_status, review_decision,
                         review_owner_user_id, reviewed_at, internal_notes, uploaded_at)
                    VALUES
                        (:db_id, :cid, 1, :fp, :fn, :st, :ce, :em, :by,
                         :rs, :rd, :ro, :ra, :notes, :ua)
                """), {
                    "db_id": row[0],
                    "cid":   row[1],
                    "fp":    row[2],
                    "fn":    row[3],
                    "st":    row[4],
                    "ce":    row[5],
                    "em":    row[6],
                    "by":    row[7],
                    "rs":    row[8] or "uploaded",
                    "rd":    row[9] or "none",
                    "ro":    row[10],
                    "ra":    row[11],
                    "notes": row[12],
                    "ua":    row[13],
                })
                v1_id = conn.execute(text(
                    "SELECT id FROM contract_versions "
                    "WHERE contract_id = :cid AND version_number = 1"
                ), {"cid": row[1]}).fetchone()[0]
                conn.execute(text(
                    "UPDATE contracts SET current_version_id = :vid WHERE id = :id"
                ), {"vid": v1_id, "id": row[0]})

        # Link existing analyses to their v1 version (where version_id is NULL)
        conn.execute(text("""
            UPDATE analyses
            SET version_id = (
                SELECT cv.id FROM contract_versions cv
                WHERE cv.contract_id = analyses.contract_id
                  AND cv.version_number = 1
            )
            WHERE version_id IS NULL
        """))

        # ── finding_reviews: new in v2.4 ──────────────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS finding_reviews (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_id         VARCHAR(50) NOT NULL,
                version_id          INTEGER NOT NULL REFERENCES contract_versions(id) ON DELETE CASCADE,
                analysis_id         INTEGER REFERENCES analyses(id) ON DELETE SET NULL,
                finding_key         VARCHAR(512) NOT NULL,
                finding_type        VARCHAR(50) NOT NULL,
                topic               VARCHAR(255),
                severity            VARCHAR(20),
                clause_id           VARCHAR(50),
                text_preview        TEXT,
                status              VARCHAR(30) NOT NULL DEFAULT 'open',
                reviewer_user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
                assigned_user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
                review_comment      TEXT,
                disposition_reason  TEXT,
                created_at          DATETIME NOT NULL,
                updated_at          DATETIME NOT NULL
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_finding_reviews_contract_id "
            "ON finding_reviews (contract_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_finding_reviews_version_id "
            "ON finding_reviews (version_id)"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_finding_reviews_version_key "
            "ON finding_reviews (version_id, finding_key)"
        ))

        # ── finding_reviews: add enrichment columns (v2.5) ────────────────────
        for col_sql in [
            "ALTER TABLE finding_reviews ADD COLUMN recommended_action  TEXT",
            "ALTER TABLE finding_reviews ADD COLUMN assigned_owner_role VARCHAR(100)",
            "ALTER TABLE finding_reviews ADD COLUMN confidence_bucket   VARCHAR(50)",
            "ALTER TABLE finding_reviews ADD COLUMN ai_used             BOOLEAN",
            "ALTER TABLE finding_reviews ADD COLUMN review_priority     VARCHAR(20)",
        ]:
            try:
                conn.execute(text(col_sql))
            except Exception:
                pass  # column already exists — SQLite has no IF NOT EXISTS for ADD COLUMN

        # ── app_settings: new in v2.5 ─────────────────────────────────────────
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_settings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
                key         VARCHAR(100) NOT NULL,
                value       TEXT,
                updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_app_settings_customer_key "
            "ON app_settings (customer_id, key)"
        ))

        conn.commit()


def _recover_stale_runs() -> None:
    """
    On server startup, mark any analysis run that is still in a non-terminal
    state ("pending" or "running") as "failed".

    These runs were orphaned by a previous server crash or clean shutdown while
    a background task was in progress.  They cannot be resumed, and leaving them
    in a non-terminal state causes the frontend to poll indefinitely.

    Called once from the startup handler — safe to run even with an empty DB.
    """
    from .database import SessionLocal
    db = SessionLocal()
    try:
        stale = (
            db.query(Analysis)
            .filter(Analysis.status.in_(["pending", "running"]))
            .all()
        )
        if not stale:
            return
        now = _utcnow()
        for row in stale:
            log.warning(
                "analysis.stale_recovered analysis_id=%d contract_id=%s "
                "was_status=%s – marking failed on startup",
                row.id, row.contract_id, row.status,
            )
            row.status        = "failed"
            row.current_stage = None
            row.error_message = (
                "Analysis was interrupted by a server restart and cannot be resumed. "
                "Please re-run the analysis."
            )
            row.completed_at  = now
        db.commit()
        log.info("analysis.stale_recovery_done count=%d", len(stale))
    except Exception as exc:
        log.error("analysis.stale_recovery_error error=%s", exc)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


# ── Shared helpers ────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_contract_id(db: Session) -> str:
    """CT-{YEAR}-{N:03d} — sequential within each calendar year."""
    year  = _utcnow().year
    count = db.query(Contract).filter(
        Contract.contract_id.like(f"CT-{year}-%")
    ).count()
    return f"CT-{year}-{count + 1:03d}"


def _emit_workflow_event(
    db:             Session,
    contract_id:    str,
    new_status:     str,
    old_status:     str | None      = None,
    new_decision:   str | None      = None,
    old_decision:   str | None      = None,
    changed_by_id:  int | None      = None,
    notes:          str | None      = None,
) -> None:
    """Write one immutable audit-log entry to contract_workflow_events."""
    ev = ContractWorkflowEvent(
        contract_id        = contract_id,
        changed_by_user_id = changed_by_id,
        old_status         = old_status,
        new_status         = new_status,
        old_decision       = old_decision,
        new_decision       = new_decision,
        notes              = notes,
        created_at         = _utcnow(),
    )
    db.add(ev)
    # caller is responsible for commit


def _latest_completed_analysis(contract_id: str, db: Session) -> Analysis | None:
    return (
        db.query(Analysis)
        .filter(Analysis.contract_id == contract_id, Analysis.status == "completed")
        .order_by(Analysis.completed_at.desc())
        .first()
    )


def _read_analysis_file(analysis: Analysis, filename: str) -> dict:
    path = Path(analysis.output_dir) / filename
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output file '{filename}' not found. "
                   "The analysis may still be running or may have failed.",
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not parse '{filename}': {exc}",
        ) from exc


# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND TASKS
# ═══════════════════════════════════════════════════════════════════════════════

def _bg_ingest(
    contract_db_id: int,
    contract_file: Path,
    output_dir: Path,
    version_id: int | None = None,
) -> None:
    from .database import SessionLocal
    db = SessionLocal()
    try:
        contract = db.query(Contract).filter(Contract.id == contract_db_id).first()
        if contract is None:
            return
        result = ingest_contract(contract_file, output_dir)
        if result.ok:
            old_rs             = contract.review_status
            contract.status            = "ingested"
            contract.clauses_extracted = len(result.clauses)
            contract.error_message     = None
            # Auto-advance review_status only if still at initial value
            if contract.review_status == "uploaded":
                contract.review_status = "ingested"
                _emit_workflow_event(
                    db, contract.contract_id,
                    new_status=contract.review_status, old_status=old_rs,
                    notes="Auto-advanced after successful ingestion",
                )
            # Also update the version record
            if version_id:
                ver = db.query(ContractVersion).filter(ContractVersion.id == version_id).first()
                if ver:
                    ver.status            = "ingested"
                    ver.clauses_extracted = len(result.clauses)
                    ver.error_message     = None
                    if ver.review_status == "uploaded":
                        ver.review_status = "ingested"
        else:
            contract.status        = "failed"
            contract.error_message = result.error
            if version_id:
                ver = db.query(ContractVersion).filter(ContractVersion.id == version_id).first()
                if ver:
                    ver.status        = "failed"
                    ver.error_message = result.error
        contract.updated_at = _utcnow()
        db.commit()
    finally:
        db.close()


def _bg_ingest_version(version_id: int, contract_file: Path, output_dir: Path) -> None:
    """Ingest a newly uploaded revision (does NOT touch Contract-level status)."""
    from .database import SessionLocal
    db = SessionLocal()
    try:
        ver = db.query(ContractVersion).filter(ContractVersion.id == version_id).first()
        if ver is None:
            return
        result = ingest_contract(contract_file, output_dir)
        if result.ok:
            ver.status            = "ingested"
            ver.clauses_extracted = len(result.clauses)
            ver.error_message     = None
            if ver.review_status == "uploaded":
                ver.review_status = "ingested"
        else:
            ver.status        = "failed"
            ver.error_message = result.error
        db.commit()
    finally:
        db.close()


def _bg_analyze(
    analysis_id:   int,
    contract_file: Path,
    output_dir:    Path,
    contract_id:   str,
    org_profile:   dict | None = None,
    version_id:    int | None  = None,
    customer_id:   int | None  = None,
) -> None:
    """
    Background task: run the full analysis pipeline and persist the terminal state.

    Lifecycle guarantees
    --------------------
    Every code path commits one of exactly two terminal states to the DB:
      - status = "completed", current_stage = "done"
      - status = "failed",    current_stage = None

    The outer except-all clause ensures that even an unhandled exception
    (e.g. OOM, unexpected RuntimeError) results in a "failed" commit rather
    than leaving the row stuck in "running" indefinitely.

    Post-processing steps (contract/version status update, finding-review
    generation) are isolated in their own try/except blocks so they cannot
    prevent the terminal-state commit from reaching the DB.
    """
    from .database import SessionLocal
    db = SessionLocal()
    try:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis is None:
            log.warning(
                "analysis.lifecycle analysis_id=%d not found – aborting background task",
                analysis_id,
            )
            return

        analysis.status     = "running"
        analysis.started_at = _utcnow()
        if version_id:
            analysis.version_id = version_id

        # ── Record org_profile snapshot hash ──────────────────────────────────
        if org_profile:
            snapshot_json = json.dumps(org_profile, sort_keys=True, ensure_ascii=False)
            analysis.org_profile_snapshot_path = str(output_dir / "org_profile.json")
            analysis.org_profile_version_hash  = hashlib.sha256(
                snapshot_json.encode()
            ).hexdigest()[:16]

        db.commit()
        log.info(
            "analysis.started analysis_id=%d contract_id=%s version_id=%s",
            analysis_id, contract_id, version_id,
        )

        # ── Stage-progress callback ────────────────────────────────────────────
        def _stage_cb(stage: str) -> None:
            """Persist current_stage to DB so the polling endpoint reflects it."""
            try:
                db.query(Analysis).filter(Analysis.id == analysis_id).update(
                    {"current_stage": stage}
                )
                db.commit()
                log.debug(
                    "analysis.stage_changed analysis_id=%d contract_id=%s stage=%s",
                    analysis_id, contract_id, stage,
                )
            except Exception as _e:
                log.warning(
                    "analysis.stage_cb_failed analysis_id=%d stage=%s error=%s",
                    analysis_id, stage, _e,
                )

        # ── Build LLM overrides from DB-backed admin config ───────────────────
        llm_overrides: dict = {}
        if customer_id is not None:
            try:
                cfg = _build_llm_config_out(customer_id, db)
                db_api_key = _get_app_setting(customer_id, "llm.api_key", db)
                env_key = (
                    os.environ.get("LLM_API_KEY")
                    or (os.environ.get("ANTHROPIC_API_KEY") if cfg.provider == "anthropic" else None)
                    or (os.environ.get("OPENAI_API_KEY")    if cfg.provider == "openai"    else None)
                    or ""
                )
                llm_overrides = {
                    "provider":    cfg.provider,
                    "model":       cfg.effective_model,
                    "api_key":     db_api_key or env_key,
                    "timeout":     cfg.timeout_seconds,
                    "app_enabled": cfg.app_llm_enabled,
                }
                log.info(
                    "analysis.llm_config analysis_id=%d provider=%s model=%s ai_enabled=%s",
                    analysis_id, cfg.provider, cfg.effective_model, cfg.app_llm_enabled,
                )
            except Exception as _e:
                log.warning(
                    "analysis.llm_config_read_failed analysis_id=%d error=%s – using env defaults",
                    analysis_id, _e,
                )

        # ── Run the analysis pipeline ──────────────────────────────────────────
        result = analyze_contract(
            contract_file=contract_file,
            output_dir=output_dir,
            contract_id=contract_id,
            org_profile=org_profile,
            stage_callback=_stage_cb,
            llm_overrides=llm_overrides,
        )

        # ── Persist terminal state ─────────────────────────────────────────────
        # IMPORTANT: set analysis.status / current_stage and call db.commit()
        # unconditionally here, BEFORE any post-processing steps.  Post-processing
        # steps (contract status, version status, finding reviews) run afterwards
        # in isolated try/except blocks so they cannot interfere with this commit.

        now = _utcnow()
        analysis.completed_at = now

        if result.ok:
            m = result.report.get("metadata", {}) if result.report else {}
            analysis.status              = "completed"
            analysis.current_stage       = "done"
            analysis.overall_risk        = m.get("overall_risk")
            analysis.total_clauses       = m.get("total_clauses")
            analysis.total_findings      = m.get("total_findings")
            analysis.high_risk_clauses   = m.get("high_risk_clauses")
            analysis.medium_risk_clauses = m.get("medium_risk_clauses")
            analysis.low_risk_clauses    = m.get("low_risk_clauses")
            analysis.outputs_ready       = True
            analysis.error_message       = None
        else:
            analysis.status        = "failed"
            analysis.current_stage = None
            analysis.error_message = result.error

        # ── Commit terminal state — this MUST succeed ──────────────────────────
        db.commit()

        if result.ok:
            log.info(
                "analysis.completed analysis_id=%d contract_id=%s version_id=%s "
                "risk=%s clauses=%s findings=%s",
                analysis_id, contract_id, version_id,
                analysis.overall_risk, analysis.total_clauses, analysis.total_findings,
            )
        else:
            log.warning(
                "analysis.failed analysis_id=%d contract_id=%s version_id=%s error=%s",
                analysis_id, contract_id, version_id, result.error,
            )

        # ── Post-processing (isolated — failures here must NOT change terminal state) ──

        if result.ok:
            # Update contract-level status
            try:
                contract = db.query(Contract).filter(
                    Contract.contract_id == contract_id
                ).first()
                if contract:
                    contract.status     = "analyzed"
                    contract.updated_at = now
                    if contract.review_status in ("uploaded", "ingested"):
                        old_rs = contract.review_status
                        contract.review_status = "analysis_completed"
                        _emit_workflow_event(
                            db, contract_id,
                            new_status="analysis_completed", old_status=old_rs,
                            notes="Auto-advanced after successful analysis",
                        )
                db.commit()
            except Exception as _e:
                log.warning(
                    "analysis.post_contract_status_failed analysis_id=%d error=%s",
                    analysis_id, _e,
                )
                try:
                    db.rollback()
                except Exception:
                    pass

            # Update version-level status
            try:
                if version_id:
                    ver = db.query(ContractVersion).filter(
                        ContractVersion.id == version_id
                    ).first()
                    if ver and ver.review_status in ("uploaded", "ingested"):
                        ver.review_status = "analysis_completed"
                    db.commit()
            except Exception as _e:
                log.warning(
                    "analysis.post_version_status_failed analysis_id=%d version_id=%s error=%s",
                    analysis_id, version_id, _e,
                )
                try:
                    db.rollback()
                except Exception:
                    pass

            # Generate finding-review rows
            try:
                if version_id:
                    _generate_finding_reviews(
                        db=db,
                        contract_id=contract_id,
                        version_id=version_id,
                        analysis_id=analysis_id,
                        output_dir=output_dir,
                    )
            except Exception as _e:
                log.warning(
                    "analysis.post_finding_reviews_failed analysis_id=%d version_id=%s error=%s",
                    analysis_id, version_id, _e,
                )
                try:
                    db.rollback()
                except Exception:
                    pass

    except Exception as exc:
        # ── Safety net: catch any unhandled exception and mark run as failed ───
        # This block should normally never be reached because analyze_contract()
        # is documented as never-raises.  It handles programmer errors, OOM, etc.
        log.error(
            "analysis.unhandled_exception analysis_id=%d contract_id=%s error=%s",
            analysis_id, contract_id, exc,
            exc_info=True,
        )
        try:
            db.rollback()
            row = db.query(Analysis).filter(Analysis.id == analysis_id).first()
            if row and row.status not in ("completed", "failed"):
                row.status        = "failed"
                row.current_stage = None
                row.error_message = f"Unexpected internal error: {exc}"
                row.completed_at  = _utcnow()
                db.commit()
                log.info(
                    "analysis.emergency_failed analysis_id=%d contract_id=%s",
                    analysis_id, contract_id,
                )
        except Exception as _inner:
            log.error(
                "analysis.emergency_commit_failed analysis_id=%d error=%s",
                analysis_id, _inner,
            )
    finally:
        db.close()


def _derive_assigned_owner(finding_type: str, topic: str | None) -> str:
    """Deterministic owner role assignment from finding type and topic keywords."""
    t  = (topic        or "").lower()
    ft = (finding_type or "").lower()
    if any(k in t for k in ("privacy", "gdpr", "personal data", "subprocessor", "data protection", "dpa", "ccpa", "special category")):
        return "Privacy / Legal"
    if any(k in t for k in ("regulation", "regulatory", "compliance", "dora", "nis2", "pci", "hipaa", "sanction", "penalty", "obligation")):
        return "Legal / Compliance"
    if any(k in t for k in ("security", "access control", "encryption", "authentication", "incident", "backup", "vulnerability", "audit log", "monitoring")):
        return "InfoSec / Service Owner"
    if any(k in t for k in ("liability", "indemnif", "intellectual property", "ip", "confidential", "non-disclosure", "termination")):
        return "Legal / Compliance"
    if ft == "negotiation":
        return "InfoSec / Service Owner"
    if ft == "risk":
        return "InfoSec / Service Owner"
    return "InfoSec / Service Owner"


def _make_finding_key(clause_id: str | None, finding_type: str, topic: str | None) -> str:
    """Deterministic key: '{clause_id}__{finding_type}__{topic}' (lowercased, stripped)."""
    parts = [
        (clause_id or "").strip().lower(),
        (finding_type or "risk").strip().lower(),
        (topic or "").strip().lower(),
    ]
    return "__".join(parts)


def _generate_finding_reviews(
    db:          "Session",
    contract_id: str,
    version_id:  int,
    analysis_id: int,
    output_dir:  Path,
) -> None:
    """
    Parse contract_risk_report.json (and negotiation_package.json) produced by
    the pipeline and upsert FindingReview rows for the given version.
    Skips rows where (version_id, finding_key) already exists.
    """
    now = _utcnow()

    # Collect findings from risk report
    report    = _safe_read_json(output_dir / "contract_risk_report.json") or {}
    risk_items = report.get("risk_distribution", [])

    # Build recommended_action lookup from action_plan (clause_id+topic → action)
    action_plan_raw = (
        _safe_read_json(output_dir / "action_plan.json")
        or report.get("action_plan_overview")
        or {}
    )
    # action_plan may be a dict with an "actions" list, or a list directly
    action_list: list[dict] = []
    if isinstance(action_plan_raw, list):
        action_list = action_plan_raw
    elif isinstance(action_plan_raw, dict):
        action_list = (
            action_plan_raw.get("actions")
            or action_plan_raw.get("action_items")
            or action_plan_raw.get("items")
            or []
        )
    # Also check top-level report action_plan_overview
    if not action_list and isinstance(report.get("action_plan_overview"), dict):
        apo = report["action_plan_overview"]
        action_list = apo.get("actions") or apo.get("action_items") or apo.get("items") or []
    elif not action_list and isinstance(report.get("action_plan_overview"), list):
        action_list = report["action_plan_overview"]

    # Map (clause_id, topic) → recommended_action
    action_map: dict[tuple[str, str], str] = {}
    for a in action_list:
        if not isinstance(a, dict):
            continue
        cid   = (a.get("affected_clause") or a.get("clause_id") or "").lower().strip()
        topic = (a.get("topic") or "").lower().strip()
        rec   = a.get("recommended_action") or a.get("action") or ""
        if rec:
            action_map[(cid, topic)] = rec
            if cid:
                action_map[(cid, "")] = rec  # fallback: clause only

    def _lookup_action(clause_id: str | None, topic: str | None) -> str | None:
        cid = (clause_id or "").lower().strip()
        top = (topic     or "").lower().strip()
        return (
            action_map.get((cid, top))
            or action_map.get((cid, ""))
            or action_map.get(("", top))
            or None
        )

    rows_to_add: list[dict] = []
    seen_keys: set[str] = set()

    for item in risk_items:
        clause_id = item.get("clause_id") or item.get("clause") or None
        topic     = item.get("topic") or None
        severity  = (item.get("severity") or "").upper() or None
        key = _make_finding_key(clause_id, "risk", topic)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        recommended_action = (
            item.get("linked_action")
            or _lookup_action(clause_id, topic)
        )
        rows_to_add.append({
            "finding_key":       key,
            "finding_type":      "risk",
            "topic":             topic,
            "severity":          severity,
            "clause_id":         clause_id,
            "text_preview":      (item.get("text_preview") or "")[:500] or None,
            "recommended_action": (recommended_action or "")[:1000] or None,
            "assigned_owner_role": _derive_assigned_owner("risk", topic),
            "review_priority":   severity,
        })

    # Also collect negotiation items (finding_type = "negotiation")
    neg_pkg = _safe_read_json(output_dir / "negotiation_package.json") or {}
    neg_items = neg_pkg.get("negotiation_items", [])
    for item in neg_items:
        clause_id = None
        affected  = item.get("affected_clauses") or []
        if affected:
            clause_id = affected[0] if isinstance(affected[0], str) else None
        topic     = item.get("topic") or None
        if isinstance(topic, list):
            topic = ", ".join(topic)
        severity  = (item.get("priority") or "").upper() or None
        key = _make_finding_key(
            item.get("negotiation_id") or item.get("action_id") or clause_id,
            "negotiation",
            topic,
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        recommended_action = (
            item.get("recommended_clause_text")
            or item.get("negotiation_argument")
            or _lookup_action(clause_id, topic)
        )
        rows_to_add.append({
            "finding_key":        key,
            "finding_type":       "negotiation",
            "topic":              topic,
            "severity":           severity,
            "clause_id":          clause_id,
            "text_preview":       (item.get("problem_summary") or "")[:500] or None,
            "recommended_action": (recommended_action or "")[:1000] or None,
            "assigned_owner_role": _derive_assigned_owner("negotiation", topic),
            "review_priority":    severity,
        })

    for row in rows_to_add:
        existing = db.query(FindingReview).filter(
            FindingReview.version_id  == version_id,
            FindingReview.finding_key == row["finding_key"],
        ).first()
        if existing is not None:
            # Back-fill enrichment fields if they are still empty
            changed = False
            for field in ("recommended_action", "assigned_owner_role", "review_priority"):
                if not getattr(existing, field) and row.get(field):
                    setattr(existing, field, row[field])
                    changed = True
            if changed:
                existing.updated_at = now
            continue
        fr = FindingReview(
            contract_id         = contract_id,
            version_id          = version_id,
            analysis_id         = analysis_id,
            finding_key         = row["finding_key"],
            finding_type        = row["finding_type"],
            topic               = row["topic"],
            severity            = row["severity"],
            clause_id           = row["clause_id"],
            text_preview        = row["text_preview"],
            recommended_action  = row.get("recommended_action"),
            assigned_owner_role = row.get("assigned_owner_role"),
            review_priority     = row.get("review_priority"),
            status              = "open",
            created_at          = now,
            updated_at          = now,
        )
        db.add(fr)


# ── Approval readiness ────────────────────────────────────────────────────────

# Finding statuses that count as "unresolved" for each severity
_HIGH_BLOCKING_STATUSES   = frozenset({"open", "in_review", "in_negotiation", "deferred"})
_MEDIUM_BLOCKING_STATUSES = frozenset({"open", "in_review", "in_negotiation", "deferred"})
# Statuses that are OK for conditional approval of medium findings
_MEDIUM_COND_OK_STATUSES  = frozenset({"accepted_risk", "deferred", "in_negotiation", "resolved", "not_applicable"})
# Statuses considered fully closed
_CLOSED_STATUSES          = frozenset({"resolved", "not_applicable", "accepted_risk"})


def _compute_approval_readiness(version_id: int, db: "Session") -> dict:
    """
    Compute the approval_readiness for a contract version from its finding_reviews.

    Returns a dict matching ApprovalReadinessOut (without contract_id / version_id).
    """
    findings = (
        db.query(FindingReview)
        .filter(FindingReview.version_id == version_id)
        .all()
    )

    high_blocking:   list[FindingReview] = []
    medium_blocking: list[FindingReview] = []
    resolved_count   = 0
    accepted_count   = 0
    low_open_count   = 0
    total_count      = len(findings)

    for f in findings:
        sev    = (f.severity or "").upper()
        st     = f.status or "open"
        if sev == "HIGH":
            if st in _HIGH_BLOCKING_STATUSES:
                high_blocking.append(f)
            elif st in _CLOSED_STATUSES:
                if st == "resolved":
                    resolved_count += 1
                else:
                    accepted_count += 1
        elif sev == "MEDIUM":
            if st in _MEDIUM_BLOCKING_STATUSES:
                medium_blocking.append(f)
            elif st == "resolved":
                resolved_count += 1
            elif st in _CLOSED_STATUSES:
                accepted_count += 1
        else:  # LOW or unknown
            if st not in _CLOSED_STATUSES:
                low_open_count += 1
            elif st == "resolved":
                resolved_count += 1
            elif st in _CLOSED_STATUSES:
                accepted_count += 1

    # Determine readiness level
    if high_blocking:
        readiness = "blocked"
    elif medium_blocking:
        readiness = "review_required"
    elif any(
        (f.status or "open") not in _MEDIUM_COND_OK_STATUSES
        for f in findings
        if (f.severity or "").upper() == "MEDIUM"
    ):
        # Shouldn't reach here, but defensive
        readiness = "review_required"
    else:
        # Check if any HIGH findings are not fully closed
        high_not_closed = any(
            (f.status or "open") not in _CLOSED_STATUSES
            for f in findings
            if (f.severity or "").upper() == "HIGH"
        )
        medium_not_closed = any(
            (f.status or "open") not in _CLOSED_STATUSES
            for f in findings
            if (f.severity or "").upper() == "MEDIUM"
        )
        if high_not_closed or medium_not_closed:
            readiness = "ready_for_conditional_approval"
        else:
            readiness = "ready_for_approval"

    blocking_reasons = [
        BlockingFinding(
            finding_key=f.finding_key,
            severity=f.severity,
            status=f.status or "open",
            topic=f.topic,
            clause_id=f.clause_id,
        )
        for f in (high_blocking + medium_blocking)[:20]  # cap at 20
    ]

    counts = ReadinessCounts(
        high_open=len(high_blocking),
        medium_open=len(medium_blocking),
        low_open=low_open_count,
        resolved=resolved_count,
        accepted_risk=accepted_count,
        total=total_count,
    )

    return {
        "approval_readiness": readiness,
        "blocking_reasons":   blocking_reasons,
        "counts":             counts,
    }


# ── Closure bundle ────────────────────────────────────────────────────────────

# Analysis-output filenames to copy into the bundle (src → dst)
_BUNDLE_ANALYSIS_FILES: list[tuple[str, str]] = [
    ("contract_risk_report.json",   "contract_risk_report.json"),
    ("negotiation_package.json",    "negotiation_package.json"),
    ("action_plan.json",            "action_plan.json"),
    ("org_profile.json",            "org_profile.json"),
    # Markdown variants (optional — included only when present)
    ("contract_risk_report.md",     "contract_risk_report.md"),
    ("negotiation_package.md",      "negotiation_package.md"),
]


def _bundle_dir(analysis: "Analysis") -> Path:
    """Return the closure_bundle sub-directory for a given analysis."""
    return Path(analysis.output_dir) / "closure_bundle"


def _generate_closure_bundle(
    contract:  "Contract",
    ver:       "ContractVersion",
    analysis:  "Analysis",
    db:        "Session",
) -> Path:
    """
    Build a frozen, audit-ready closure bundle for an approved / rejected version.

    Layout::

        {output_dir}/closure_bundle/
          manifest.json
          original.<ext>
          contract_risk_report.json
          negotiation_package.json
          action_plan.json
          org_profile.json
          findings_summary.json
          approval_readiness.json
          workflow_history.json
          [optional .md files]
          closure_bundle.zip

    Idempotent: if ``manifest.json`` already exists the function returns
    the bundle directory immediately without regenerating.
    """
    bundle_dir = _bundle_dir(analysis)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = bundle_dir / "manifest.json"
    if manifest_path.exists():
        # Already generated — immutability preserved
        return bundle_dir

    now_iso = _utcnow().isoformat()
    bundle_contents: list[str] = []

    # ── 1. Copy analysis output files ─────────────────────────────────────────
    analysis_dir = Path(analysis.output_dir)
    for src_name, dst_name in _BUNDLE_ANALYSIS_FILES:
        src = analysis_dir / src_name
        if src.exists():
            shutil.copy2(src, bundle_dir / dst_name)
            bundle_contents.append(dst_name)

    # ── 2. Copy original contract file ────────────────────────────────────────
    original_src = Path(ver.file_path)
    if original_src.exists():
        ext      = original_src.suffix or ".pdf"
        dst_name = f"original{ext}"
        shutil.copy2(original_src, bundle_dir / dst_name)
        bundle_contents.append(dst_name)

    # ── 3. Write findings_summary.json from DB ────────────────────────────────
    findings = (
        db.query(FindingReview)
        .filter(FindingReview.version_id == ver.id)
        .all()
    )
    by_sev: dict[str, int] = {}
    status_counts: dict[str, int] = {
        "open": 0, "in_review": 0, "in_negotiation": 0, "resolved": 0,
        "accepted_risk": 0, "not_applicable": 0, "deferred": 0,
    }
    findings_list = []
    for f in findings:
        st = f.status or "open"
        if st in status_counts:
            status_counts[st] += 1
        sv = (f.severity or "UNKNOWN").upper()
        by_sev[sv] = by_sev.get(sv, 0) + 1
        findings_list.append({
            "finding_key":        f.finding_key,
            "finding_type":       f.finding_type,
            "clause_id":          f.clause_id,
            "severity":           f.severity,
            "topic":              f.topic,
            "status":             st,
            "review_comment":     f.review_comment,
            "disposition_reason": f.disposition_reason,
        })
    findings_summary = {
        "total":      len(findings),
        "by_status":  status_counts,
        "by_severity": by_sev,
        "findings":   findings_list,
    }
    _fname = "findings_summary.json"
    (bundle_dir / _fname).write_text(
        json.dumps(findings_summary, indent=2, default=str), encoding="utf-8"
    )
    bundle_contents.append(_fname)

    # ── 4. Write approval_readiness.json from DB ──────────────────────────────
    readiness_data = _compute_approval_readiness(ver.id, db)
    readiness_out = {
        "contract_id":       contract.contract_id,
        "version_id":        ver.id,
        "approval_readiness": readiness_data["approval_readiness"],
        "blocking_reasons":  [
            {
                "finding_key": b.finding_key,
                "severity":    b.severity,
                "status":      b.status,
                "topic":       b.topic,
                "clause_id":   b.clause_id,
            }
            for b in readiness_data["blocking_reasons"]
        ],
        "counts": {
            "high_open":     readiness_data["counts"].high_open,
            "medium_open":   readiness_data["counts"].medium_open,
            "low_open":      readiness_data["counts"].low_open,
            "resolved":      readiness_data["counts"].resolved,
            "accepted_risk": readiness_data["counts"].accepted_risk,
            "total":         readiness_data["counts"].total,
        },
    }
    _fname = "approval_readiness.json"
    (bundle_dir / _fname).write_text(
        json.dumps(readiness_out, indent=2), encoding="utf-8"
    )
    bundle_contents.append(_fname)

    # ── 5. Write workflow_history.json from DB ────────────────────────────────
    events = (
        db.query(ContractWorkflowEvent)
        .filter(ContractWorkflowEvent.contract_id == contract.contract_id)
        .order_by(ContractWorkflowEvent.created_at.asc())
        .all()
    )
    history = [
        {
            "id":           ev.id,
            "old_status":   ev.old_status,
            "new_status":   ev.new_status,
            "old_decision": ev.old_decision,
            "new_decision": ev.new_decision,
            "notes":        ev.notes,
            "created_at":   ev.created_at.isoformat() if ev.created_at else None,
        }
        for ev in events
    ]
    _fname = "workflow_history.json"
    (bundle_dir / _fname).write_text(
        json.dumps(history, indent=2, default=str), encoding="utf-8"
    )
    bundle_contents.append(_fname)

    # ── 6. Build manifest.json ────────────────────────────────────────────────
    manifest: dict = {
        "contract_id":              contract.contract_id,
        "case_id":                  contract.id,
        "version_id":               ver.id,
        "version_number":           ver.version_number,
        "analysis_id":              analysis.id,
        "customer_id":              contract.customer_id,
        "review_status":            ver.review_status,
        "review_decision":          ver.review_decision,
        "approved_or_rejected_at":  (
            ver.reviewed_at.isoformat() if ver.reviewed_at else now_iso
        ),
        "org_profile_version_hash": analysis.org_profile_version_hash,
        "overall_risk":             analysis.overall_risk,
        "bundle_contents":          bundle_contents + ["manifest.json"],
        "bundle_hash":              None,   # filled after ZIP creation
        "generated_at":             now_iso,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    bundle_contents.append("manifest.json")

    # ── 7. Create ZIP archive ─────────────────────────────────────────────────
    zip_path = bundle_dir / "closure_bundle.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in bundle_contents:
            fpath = bundle_dir / fname
            if fpath.exists():
                zf.write(fpath, fname)

    # ── 8. Compute ZIP hash and patch manifest ────────────────────────────────
    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    manifest["bundle_hash"]     = f"sha256:{sha256}"
    manifest["bundle_contents"] = bundle_contents  # already includes manifest.json
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return bundle_dir


def _read_bundle_manifest(bundle_dir: Path) -> dict | None:
    """Return parsed manifest.json or None when the bundle doesn't exist yet."""
    mp = bundle_dir / "manifest.json"
    if not mp.exists():
        return None
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Clause explorer helpers ───────────────────────────────────────────────────

def _safe_read_json(path: Path) -> list | dict | None:
    """Read JSON from *path*; return None if missing or unparseable."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_clause_indexes(
    analysis: "Analysis",
) -> tuple[
    dict[str, dict],   # clause_id → clause row (stage4_clauses.json)
    dict[str, dict],   # clause_id → obligation (stage4_5_obligation_analysis.json)
    dict[str, list],   # clause_id → SR matches (clause_sr_matches.json)
    dict[str, dict],   # clause_id → risk score (risk_scoring.json clause_scores[])
    dict[str, list],   # clause_id → negotiation items (negotiation_package.json)
]:
    """
    Load all clause-related JSON files from an analysis output directory and
    return five look-up indexes keyed by clause_id.

    Missing files produce empty indexes — callers must handle absent data
    gracefully (e.g. no SR matches, no risk score).
    """
    out = Path(analysis.output_dir)

    # ── stage4_clauses.json ──────────────────────────────────────────────────
    raw_clauses = _safe_read_json(out / "stage4_clauses.json") or []
    clause_idx: dict[str, dict] = {}
    for c in (raw_clauses if isinstance(raw_clauses, list) else []):
        cid = c.get("clause_id")
        if cid:
            clause_idx[cid] = c

    # ── stage4_5_obligation_analysis.json ────────────────────────────────────
    obligation_idx: dict[str, dict] = {}
    raw_oblig = _safe_read_json(out / "stage4_5_obligation_analysis.json") or []
    for ob in (raw_oblig if isinstance(raw_oblig, list) else []):
        cid = ob.get("clause_id")
        if cid:
            obligation_idx[cid] = ob

    # ── clause_sr_matches.json ───────────────────────────────────────────────
    sr_idx: dict[str, list] = {}
    raw_sr = _safe_read_json(out / "clause_sr_matches.json") or []
    for m in (raw_sr if isinstance(raw_sr, list) else []):
        cid = m.get("clause_id")
        if cid:
            sr_idx.setdefault(cid, []).append(m)

    # ── risk_scoring.json → clause_scores[] ─────────────────────────────────
    risk_idx: dict[str, dict] = {}
    raw_risk = _safe_read_json(out / "risk_scoring.json") or {}
    for cs in (raw_risk.get("clause_scores", []) if isinstance(raw_risk, dict) else []):
        cid = cs.get("clause_id")
        if cid:
            risk_idx[cid] = cs

    # ── negotiation_package.json → items[] ──────────────────────────────────
    neg_idx: dict[str, list] = {}
    raw_neg = _safe_read_json(out / "negotiation_package.json") or {}
    for item in (raw_neg.get("items", []) if isinstance(raw_neg, dict) else []):
        for cid in item.get("affected_clauses", []):
            neg_idx.setdefault(cid, []).append(item)

    return clause_idx, obligation_idx, sr_idx, risk_idx, neg_idx


def _sr_match_out(m: dict) -> "SRMatchOut":
    return SRMatchOut(
        sr_id=m.get("sr_id", ""),
        sr_title=m.get("sr_title"),
        framework=m.get("framework", ""),
        control_id=m.get("control_id"),
        match_type=m.get("match_type", "NO_MATCH"),
        match_confidence=float(m.get("match_confidence", 0.0)),
        extracted_evidence=m.get("extracted_evidence"),
        match_reasoning=m.get("match_reasoning"),
        # Additive pipeline metadata (pipeline stores with leading underscore in dict key)
        ai_metadata=m.get("_ai_metadata"),
        baseline_result=m.get("_baseline_result"),
        decision_delta=m.get("_decision_delta"),
        confidence_bucket=m.get("_confidence_bucket"),
        review_priority=m.get("_review_priority"),
        ai_trace=m.get("_ai_trace"),
        candidate_metadata=m.get("_candidate_metadata"),
    )


def _clause_list_item(
    c:           dict,
    obligation_idx: dict[str, dict],
    sr_idx:      dict[str, list],
    risk_idx:    dict[str, dict],
    findings:    list["FindingReview"],
) -> "ClauseListItem":
    """Build one ClauseListItem row from assembled indexes."""
    cid  = c["clause_id"]
    text = c.get("text", "")
    ob   = obligation_idx.get(cid, {})
    rs   = risk_idx.get(cid, {})
    srs  = sr_idx.get(cid, [])

    # Derive severity — prefer obligation analysis, fall back to risk score priority
    severity = ob.get("severity") or rs.get("severity")

    # SR match summary
    direct_match = any(
        m.get("match_type") == "DIRECT_MATCH" and m.get("match_confidence", 0) >= 0.5
        for m in srs
    )

    # Finding summary
    f_statuses = [f.status for f in findings]

    return ClauseListItem(
        clause_id=cid,
        page=c.get("page"),
        layout_type=c.get("layout_type"),
        text_preview=(text[:200] + "…") if len(text) > 200 else text or None,
        topic=ob.get("negotiation_topic") or rs.get("topic"),
        severity=severity,
        risk_score=rs.get("risk_score"),
        finding_count=len(findings),
        finding_statuses=f_statuses,
        sr_match_count=len(srs),
        has_direct_match=direct_match,
    )


def _clause_detail_out(
    cid:            str,
    clause_idx:     dict[str, dict],
    obligation_idx: dict[str, dict],
    sr_idx:         dict[str, list],
    risk_idx:       dict[str, dict],
    neg_idx:        dict[str, list],
    findings:       list["FindingReview"],
    ver:            "ContractVersion",
    db:             "Session",
) -> "ClauseDetailOut":
    """Assemble the full clause detail response."""
    c  = clause_idx.get(cid, {})
    ob = obligation_idx.get(cid)
    rs = risk_idx.get(cid)
    srs = sr_idx.get(cid, [])
    neg_items = neg_idx.get(cid, [])

    # Obligation assessment
    oblig_out = None
    if ob:
        oblig_out = ObligationAssessmentOut(
            assessment=ob.get("assessment", ""),
            severity=ob.get("severity"),
            reason=ob.get("reason"),
            recommended_action=ob.get("recommended_action"),
        )

    # Risk score
    risk_out = None
    if rs:
        risk_out = ClauseRiskScoreOut(
            risk_score=float(rs.get("risk_score", 0.0)),
            priority=rs.get("priority"),
            topic=rs.get("topic"),
            obligation=rs.get("obligation"),
            score_breakdown=rs.get("score_breakdown"),
            text_preview=rs.get("text_preview"),
        )

    # SR matches — skip pure NO_MATCH with zero confidence
    sr_outs = [
        _sr_match_out(m) for m in srs
        if m.get("match_type") != "NO_MATCH" or m.get("match_confidence", 0) > 0
    ]

    # Findings
    finding_outs = [
        ClauseFindingOut(
            id=f.id,
            finding_key=f.finding_key,
            finding_type=f.finding_type,
            topic=f.topic,
            severity=f.severity,
            status=f.status,
            review_comment=f.review_comment,
            text_preview=f.text_preview,
        )
        for f in findings
    ]

    # Negotiation items
    neg_outs = [
        NegotiationItemOut(
            neg_id=n.get("neg_id"),
            action_id=n.get("action_id"),
            finding_type=n.get("finding_type"),
            priority=n.get("priority"),
            topic=n.get("topic") or (n.get("topics", [None])[0] if n.get("topics") else None),
            position_summary=n.get("position_summary"),
            recommended_text=(n.get("recommended_clause_text") or "")[:400] or None,
        )
        for n in neg_items
    ]

    # Workflow context
    readiness = _compute_approval_readiness(ver.id, db)
    workflow_ctx = {
        "review_status":      ver.review_status,
        "review_decision":    ver.review_decision,
        "approval_readiness": readiness["approval_readiness"],
    }

    return ClauseDetailOut(
        clause_id=cid,
        page=c.get("page"),
        layout_type=c.get("layout_type"),
        text=c.get("text"),
        obligation_assessment=oblig_out,
        sr_matches=sr_outs,
        findings=finding_outs,
        risk_score=risk_out,
        negotiation_items=neg_outs,
        workflow_context=workflow_ctx,
    )


# ── Risk-summary helpers ──────────────────────────────────────────────────────

def _safe_read_json(path: Path) -> dict | None:
    """Read and parse a JSON file; return None on any error."""
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _empty_risk_summary() -> dict:
    return {
        "total_contracts":           0,
        "analyses_completed":        0,
        "average_risk_score":        0.0,
        "high_risk_contracts":       0,
        "medium_risk_contracts":     0,
        "low_risk_contracts":        0,
        "top_risk_topics":           [],
        "top_regulatory_frameworks": [],
        "most_common_finding_types": [],
        "contracts_by_risk":         [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD  (tenant-scoped, all roles)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get(
    "/dashboard/risk-summary",
    response_model=RiskSummaryOut,
    tags=["dashboard"],
    summary="Aggregated risk intelligence across all tenant contract analyses",
    description=(
        "Reads the `contract_risk_report.json` from every completed analysis "
        "belonging to the calling user's tenant and aggregates topics, "
        "regulatory frameworks, finding types, and clause-level risk scores.  "
        "Only the **latest** completed analysis per contract is used for "
        "deduplication; `analyses_completed` counts all runs."
    ),
)
def get_risk_summary(
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> dict:
    # ── All contracts for this tenant ─────────────────────────────────────────
    tenant_contracts: list[Contract] = (
        db.query(Contract)
        .filter(Contract.customer_id == current_user.customer_id)
        .all()
    )
    if not tenant_contracts:
        return _empty_risk_summary()

    contract_map = {c.contract_id: c for c in tenant_contracts}
    cids = list(contract_map.keys())

    # ── All completed analyses (ordered newest first within each contract) ────
    all_completed: list[Analysis] = (
        db.query(Analysis)
        .filter(
            Analysis.contract_id.in_(cids),
            Analysis.status == "completed",
        )
        .order_by(Analysis.contract_id, Analysis.completed_at.desc())
        .all()
    )

    if not all_completed:
        return {**_empty_risk_summary(), "total_contracts": len(cids)}

    # ── Latest completed analysis per contract (deduplicated) ─────────────────
    seen: set[str] = set()
    latest_per_contract: list[Analysis] = []
    for a in all_completed:
        if a.contract_id not in seen:
            seen.add(a.contract_id)
            latest_per_contract.append(a)

    # ── Aggregate across latest analyses ──────────────────────────────────────
    RISK_TO_SCORE: dict[str, float] = {"HIGH": 8.0, "MEDIUM": 5.0, "LOW": 2.0}
    RISK_ORDER:    dict[str, int]   = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

    topic_counts:     dict[str, int] = {}
    framework_issues: dict[str, int] = {}
    finding_counts:   dict[str, int] = {}
    clause_scores:    list[float]    = []
    contracts_by_risk: list[dict]   = []

    for analysis in latest_per_contract:
        report = _safe_read_json(
            Path(analysis.output_dir) / "contract_risk_report.json"
        )
        meta         = (report.get("metadata", {}) if report else {})
        overall_risk = (
            meta.get("overall_risk")
            or analysis.overall_risk
            or ""
        ).upper()

        if report:
            # topic counts + clause scores from risk_distribution
            for item in report.get("risk_distribution", []):
                score = item.get("risk_score")
                if score is not None:
                    clause_scores.append(float(score))
                topic = item.get("topic")
                if topic:
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1

            # regulatory frameworks from regulatory_exposure
            for exp in report.get("regulatory_exposure", []):
                fw = exp.get("framework")
                if fw:
                    n = len(exp.get("clauses", [])) or 1
                    framework_issues[fw] = framework_issues.get(fw, 0) + n

            # finding types from action_plan_overview (count affected clauses)
            for action in report.get("action_plan_overview", []):
                ft = action.get("finding_type")
                if ft:
                    n = len(action.get("affected_clauses", [])) or 1
                    finding_counts[ft] = finding_counts.get(ft, 0) + n

        # per-contract summary row
        contract = contract_map.get(analysis.contract_id)
        contracts_by_risk.append({
            "contract_id":      analysis.contract_id,
            "filename":         contract.filename if contract else analysis.contract_id,
            "overall_risk":     overall_risk or "UNKNOWN",
            "risk_score":       RISK_TO_SCORE.get(overall_risk, 5.0),
            "total_findings":   (
                meta.get("total_findings")
                or analysis.total_findings
                or 0
            ),
            "high_risk_clauses": (
                meta.get("high_risk_clauses")
                or analysis.high_risk_clauses
                or 0
            ),
            "completed_at": (
                analysis.completed_at.isoformat()
                if analysis.completed_at else None
            ),
        })

    # Sort by risk level then findings count descending
    contracts_by_risk.sort(
        key=lambda x: (RISK_ORDER.get(x["overall_risk"], 0), x["total_findings"]),
        reverse=True,
    )

    avg_score = (
        round(sum(clause_scores) / len(clause_scores), 1)
        if clause_scores else 0.0
    )

    top_topics     = sorted(topic_counts.items(),    key=lambda x: x[1], reverse=True)[:8]
    top_frameworks = sorted(framework_issues.items(), key=lambda x: x[1], reverse=True)[:8]
    top_findings   = sorted(finding_counts.items(),  key=lambda x: x[1], reverse=True)[:8]

    return {
        "total_contracts":           len(cids),
        "analyses_completed":        len(all_completed),
        "average_risk_score":        avg_score,
        "high_risk_contracts":       sum(
            1 for a in latest_per_contract
            if (a.overall_risk or "").upper() == "HIGH"
        ),
        "medium_risk_contracts":     sum(
            1 for a in latest_per_contract
            if (a.overall_risk or "").upper() == "MEDIUM"
        ),
        "low_risk_contracts":        sum(
            1 for a in latest_per_contract
            if (a.overall_risk or "").upper() == "LOW"
        ),
        "top_risk_topics":           [{"topic": t, "count": c} for t, c in top_topics],
        "top_regulatory_frameworks": [{"framework": f, "issues": c} for f, c in top_frameworks],
        "most_common_finding_types": [{"finding_type": ft, "count": c} for ft, c in top_findings],
        "contracts_by_risk":         contracts_by_risk[:10],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH  (public)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["meta"])
def health_check() -> dict:
    return {"status": "ok", "timestamp": _utcnow().isoformat()}


def _build_llm_config_out(customer_id: int, db: "Session") -> LLMConfigOut:
    """
    Assemble the full LLMConfigOut for a customer.

    Priority:
      provider / model / timeout — DB setting overrides env var
      api_key                    — DB key overrides env var; never returned in response
      app_enabled                — DB setting only (defaults True)
    """
    _DEFAULT_MODELS = {"anthropic": "claude-opus-4-6", "openai": "gpt-4o"}

    db_provider = _get_app_setting(customer_id, "llm.provider", db) or LLM_PROVIDER
    db_model    = _get_app_setting(customer_id, "llm.model",    db) or (LLM_MODEL or None)
    db_timeout_raw = _get_app_setting(customer_id, "llm.timeout_seconds", db)
    db_timeout  = int(db_timeout_raw) if db_timeout_raw else LLM_TIMEOUT_SECONDS

    # Key: DB-stored key takes priority; env vars are fallback
    db_api_key   = _get_app_setting(customer_id, "llm.api_key", db)
    env_key_present = bool(
        os.environ.get("LLM_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    key_configured = bool(db_api_key) or env_key_present

    effective_model = db_model or _DEFAULT_MODELS.get(db_provider, "gpt-4o")

    app_setting_raw = _get_app_setting(customer_id, "llm.app_enabled", db)
    app_llm_enabled = (app_setting_raw != "false") if app_setting_raw is not None else True

    provider_configured = key_configured
    effective_enabled   = LLM_ENABLED and provider_configured and app_llm_enabled

    return LLMConfigOut(
        system_llm_enabled  = LLM_ENABLED,
        provider            = db_provider,
        model               = db_model,
        effective_model     = effective_model,
        timeout_seconds     = db_timeout,
        app_llm_enabled     = app_llm_enabled,
        key_configured      = key_configured,
        provider_configured = provider_configured,
        effective_enabled   = effective_enabled,
    )


@app.get(
    "/admin/llm-config",
    response_model=LLMConfigOut,
    tags=["admin"],
    summary="Get full LLM configuration (ADMIN only)",
)
def get_llm_config(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LLMConfigOut:
    """
    Returns the three-level LLM configuration:
    - Level A (system): env-var capability (LLM_ENABLED)
    - Level B (DB): provider, model, API key presence, timeout, app toggle
    - Effective: computed from levels A + B
    API key is never included in the response — only key_configured (bool).
    """
    return _build_llm_config_out(current_user.customer_id, db)


@app.patch(
    "/admin/llm-config",
    response_model=LLMConfigOut,
    tags=["admin"],
    summary="Update LLM configuration (ADMIN only)",
)
def update_llm_config(
    body: LLMConfigUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LLMConfigOut:
    """
    Persist one or more LLM config fields.  Only supplied (non-None) fields are
    written.  Pass api_key="" to explicitly clear a stored key.

    api_key is write-only: it is stored encrypted-at-rest in the DB setting
    and is never echoed back in this or any other response.
    """
    cid = current_user.customer_id

    if body.app_llm_enabled is not None:
        _set_app_setting(cid, "llm.app_enabled",
                         "true" if body.app_llm_enabled else "false", db)

    if body.provider is not None:
        allowed = {"openai", "anthropic"}
        if body.provider not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"provider must be one of {sorted(allowed)}",
            )
        _set_app_setting(cid, "llm.provider", body.provider, db)

    if body.model is not None:
        # Empty string means "use default"
        _set_app_setting(cid, "llm.model", body.model.strip() or "", db)

    if body.api_key is not None:
        # Empty string clears the stored key
        _set_app_setting(cid, "llm.api_key", body.api_key.strip(), db)

    if body.timeout_seconds is not None:
        if body.timeout_seconds < 5 or body.timeout_seconds > 300:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="timeout_seconds must be between 5 and 300",
            )
        _set_app_setting(cid, "llm.timeout_seconds", str(body.timeout_seconds), db)

    return _build_llm_config_out(cid, db)


@app.post(
    "/admin/llm-config/test",
    response_model=LLMTestResult,
    tags=["admin"],
    summary="Test the configured LLM provider connection (ADMIN only)",
)
def test_llm_config(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LLMTestResult:
    """
    Validates the active LLM provider by sending a minimal test prompt.
    Does not run a full analysis.

    Returns one of: ok | auth_failed | provider_unavailable | missing_key | unknown_error
    """
    cid = current_user.customer_id
    cfg = _build_llm_config_out(cid, db)

    if not LLM_ENABLED:
        return LLMTestResult(
            success=False,
            status="provider_unavailable",
            message="LLM_ENABLED=false — the LLM feature is disabled at the system level.",
        )

    if not cfg.key_configured:
        return LLMTestResult(
            success=False,
            status="missing_key",
            message=f"No API key configured for provider '{cfg.provider}'. "
                    "Save a key via the LLM Config page first.",
            provider=cfg.provider,
        )

    # Resolve the effective API key (DB key takes priority over env vars)
    api_key = _get_app_setting(cid, "llm.api_key", db)
    if not api_key:
        api_key = (
            os.environ.get("LLM_API_KEY")
            or (os.environ.get("ANTHROPIC_API_KEY") if cfg.provider == "anthropic" else None)
            or (os.environ.get("OPENAI_API_KEY")    if cfg.provider == "openai"    else None)
            or ""
        )

    try:
        from llm.config import get_llm_provider as _get_llm
        provider_inst = _get_llm(
            provider_override = cfg.provider,
            model_override    = cfg.effective_model,
            api_key_override  = api_key,
        )
    except Exception as exc:
        return LLMTestResult(
            success=False,
            status="provider_unavailable",
            message=f"Provider initialisation failed: {exc}",
            provider=cfg.provider,
            model=cfg.effective_model,
        )

    if provider_inst is None:
        return LLMTestResult(
            success=False,
            status="provider_unavailable",
            message="Provider could not be initialised (library not installed or key missing).",
            provider=cfg.provider,
            model=cfg.effective_model,
        )

    # Send a minimal structured prompt as a connectivity/auth probe
    _TEST_SCHEMA = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    try:
        response = provider_inst.complete_structured(
            system_prompt  = "You are a connectivity test assistant.",
            user_message   = "Reply with JSON: {\"ok\": true}",
            json_schema    = _TEST_SCHEMA,
            prompt_version = "test-v1",
            max_tokens     = 64,
        )
    except RuntimeError as exc:
        err = str(exc).lower()
        if "auth" in err or "authentication" in err or "api key" in err or "invalid_api_key" in err:
            return LLMTestResult(
                success=False,
                status="auth_failed",
                message=f"Authentication failed: {exc}",
                provider=cfg.provider,
                model=cfg.effective_model,
            )
        return LLMTestResult(
            success=False,
            status="provider_unavailable",
            message=str(exc),
            provider=cfg.provider,
            model=cfg.effective_model,
        )
    except Exception as exc:
        return LLMTestResult(
            success=False,
            status="unknown_error",
            message=f"Unexpected error: {exc}",
            provider=cfg.provider,
            model=cfg.effective_model,
        )

    if response is None:
        return LLMTestResult(
            success=False,
            status="provider_unavailable",
            message="Provider returned no response after retries.",
            provider=cfg.provider,
            model=cfg.effective_model,
        )

    return LLMTestResult(
        success=True,
        status="ok",
        message=f"Connection successful — {cfg.provider} / {cfg.effective_model} responded.",
        provider=cfg.provider,
        model=cfg.effective_model,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH  (public endpoints)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post(
    "/auth/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    tags=["auth"],
    summary="Self-register a new user account",
    description=(
        "Open endpoint — no token required.\n\n"
        "The provided `customer_id` must reference an existing customer. "
        "If this is the **first user** registered for that customer, they "
        "are automatically granted the **ADMIN** role. Subsequent registrations "
        "receive **ANALYST** by default.\n\n"
        "Use `POST /users` (ADMIN-only) to create users with a specific role."
    ),
)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> User:
    # Customer must exist
    customer = db.query(Customer).filter(Customer.id == body.customer_id).first()
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer id={body.customer_id} not found.",
        )

    # Email must be unique globally
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{body.email}' is already registered.",
        )

    # First user in this tenant becomes ADMIN (bootstrap)
    tenant_users = db.query(User).filter(User.customer_id == body.customer_id).count()
    role = UserRole.ADMIN.value if tenant_users == 0 else UserRole.ANALYST.value

    user = User(
        email         = body.email,
        name          = body.name,
        password_hash = hash_password(body.password),
        role          = role,
        customer_id   = body.customer_id,
        is_active     = True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post(
    "/auth/login",
    response_model=TokenOut,
    tags=["auth"],
    summary="Exchange credentials for a JWT Bearer token",
)
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.email == body.email).first()

    # Use constant-time comparison even when user is None to resist timing attacks
    dummy_hash = "$2b$12$invalidhashfortimingprotectiononly000000000000000000000000"
    candidate_hash = user.password_hash if user else dummy_hash
    password_ok = verify_password(body.password, candidate_hash)

    if not user or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact your administrator.",
        )

    token = create_access_token(
        user_id     = user.id,
        email       = user.email,
        customer_id = user.customer_id,
        role        = user.role,
    )
    return {
        "access_token": token,
        "token_type":   "bearer",
        "expires_in":   JWT_EXPIRY_HOURS * 3600,
    }


@app.get(
    "/auth/me",
    response_model=UserOut,
    tags=["auth"],
    summary="Return the currently authenticated user's profile",
)
def me(current_user: User = Depends(require_any_role)) -> User:
    return current_user


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMERS  (ADMIN-only, tenant-scoped)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post(
    "/customers",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
    tags=["customers"],
    summary="Create a customer organisation",
    description=(
        "**ADMIN role required**, *or* the database is completely empty "
        "(bootstrap mode — allows creating the very first customer without auth)."
    ),
)
def create_customer(
    body: CustomerCreate,
    db:   Session = Depends(get_db),
    # Optional auth — not enforced when DB is empty (bootstrap)
    credentials: Any = Depends(
        # We re-use the HTTPBearer scheme but handle None ourselves below
        __import__("fastapi.security", fromlist=["HTTPBearer"]).HTTPBearer(auto_error=False)
    ),
) -> Customer:
    # Bootstrap: allow unauthenticated creation if no customers exist yet
    is_bootstrap = db.query(Customer).count() == 0

    if not is_bootstrap:
        # Require a valid ADMIN token
        from .deps import _bearer, get_current_user as _gcu
        from .auth import decode_token, TokenError

        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            payload = decode_token(credentials.credentials)
        except TokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token is invalid or has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = db.query(User).filter(
            User.id == payload.get("uid"), User.is_active.is_(True)
        ).first()
        if user is None or UserRole(user.role) is not UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin role required to create a customer.",
            )

    # Validate org_profile if provided (raises 422 on schema error)
    org_profile_json: str | None = None
    if body.org_profile:
        org_profile_json = body.org_profile.model_dump_json()

    customer = Customer(
        name        = body.name,
        industry    = body.industry,
        org_profile = org_profile_json,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@app.get(
    "/customers/me",
    response_model=CustomerOut,
    tags=["customers"],
    summary="Return the calling user's own customer (tenant)",
)
def get_my_customer(
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> Customer:
    customer = db.query(Customer).filter(Customer.id == current_user.customer_id).first()
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer record not found.",
        )
    return customer


def _load_customer_profile(customer: Customer) -> dict | None:
    """Parse the stored org_profile JSON; return None when absent."""
    if not customer.org_profile:
        return None
    try:
        return json.loads(customer.org_profile)
    except (json.JSONDecodeError, ValueError):
        return None


@app.get(
    "/customers/me/profile",
    response_model=OrgProfileOut,
    tags=["customers"],
    summary="Return the tenant's compliance org profile (all roles)",
    description=(
        "All authenticated users of the tenant may read the compliance profile.  "
        "Returns 404 when no profile has been configured yet."
    ),
)
def get_org_profile(
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> dict:
    customer = db.query(Customer).filter(Customer.id == current_user.customer_id).first()
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Customer record not found.")
    profile = _load_customer_profile(customer)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No compliance profile configured for this tenant. "
                   "An ADMIN must set one via PUT /customers/me/profile.",
        )
    return profile


@app.put(
    "/customers/me/profile",
    response_model=OrgProfileOut,
    tags=["customers"],
    summary="Update the tenant's compliance org profile (ADMIN only)",
    description=(
        "**ADMIN role required.**  "
        "Replaces the entire org profile.  "
        "The profile is validated against the allowed values for each field."
    ),
)
def update_org_profile(
    body:         OrgProfileIn,
    current_user: User    = Depends(require_admin),
    db:           Session = Depends(get_db),
) -> dict:
    customer = db.query(Customer).filter(Customer.id == current_user.customer_id).first()
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Customer record not found.")
    customer.org_profile = body.model_dump_json()
    customer.updated_at  = _utcnow()
    db.commit()
    return body.model_dump()


# ═══════════════════════════════════════════════════════════════════════════════
# USERS  (ADMIN-only, tenant-scoped)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    tags=["users"],
    summary="Create a user within the ADMIN's tenant",
    description=(
        "**ADMIN role required.**  The new user is automatically assigned "
        "to the same customer as the calling ADMIN.  "
        "Roles: `ADMIN` | `ANALYST` | `VIEWER`."
    ),
)
def create_user(
    body:         UserCreate,
    current_user: User    = Depends(require_admin),
    db:           Session = Depends(get_db),
) -> User:
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{body.email}' is already registered.",
        )
    user = User(
        email         = body.email,
        name          = body.name,
        password_hash = hash_password(body.password),
        role          = body.role,
        customer_id   = current_user.customer_id,  # forced to admin's tenant
        is_active     = True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get(
    "/users",
    response_model=list[UserOut],
    tags=["users"],
    summary="List users within the ADMIN's tenant",
)
def list_users(
    current_user: User    = Depends(require_admin),
    db:           Session = Depends(get_db),
) -> list[User]:
    return (
        db.query(User)
        .filter(User.customer_id == current_user.customer_id)
        .order_by(User.id)
        .all()
    )


@app.patch(
    "/users/{user_id}/deactivate",
    response_model=UserOut,
    tags=["users"],
    summary="Deactivate a user account (ADMIN only, same tenant)",
)
def deactivate_user(
    user_id:      int,
    current_user: User    = Depends(require_admin),
    db:           Session = Depends(get_db),
) -> User:
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins cannot deactivate their own account.",
        )
    user = db.query(User).filter(
        User.id == user_id,
        User.customer_id == current_user.customer_id,
    ).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User id={user_id} not found in your tenant.",
        )
    user.is_active  = False
    user.updated_at = _utcnow()
    db.commit()
    db.refresh(user)
    return user


# ═══════════════════════════════════════════════════════════════════════════════
# CONTRACTS  (tenant-scoped)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post(
    "/contracts/upload",
    response_model=ContractOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["contracts"],
    summary="Upload a contract file (PDF, DOCX, TXT)",
    description=(
        "**ADMIN or ANALYST role required.**\n\n"
        "The file is stored under `/contracts/{contract_id}/` and stage16 "
        "ingestion is queued as a background task.  Poll "
        "`GET /contracts/{id}` to track status."
    ),
)
async def upload_contract(
    background_tasks: BackgroundTasks,
    file:         UploadFile = File(..., description="Contract file (.pdf/.docx/.txt)"),
    current_user: User       = Depends(require_analyst_above),
    db:           Session    = Depends(get_db),
) -> Contract:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported file type '{suffix}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    contract_id  = _next_contract_id(db)
    contract_dir = CONTRACTS_DIR / contract_id
    analysis_dir = ANALYSES_DIR  / contract_id
    contract_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    dest = contract_dir / f"original{suffix}"

    total = 0
    async with aiofiles.open(dest, "wb") as out:
        while chunk := await file.read(256 * 1024):
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                await out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds the {MAX_FILE_BYTES // (1024**2)} MB limit.",
                )
            await out.write(chunk)

    contract = Contract(
        contract_id  = contract_id,
        filename     = file.filename or dest.name,
        file_path    = str(dest),
        file_format  = suffix.lstrip("."),
        status       = "uploaded",
        customer_id  = current_user.customer_id,
        uploaded_by  = current_user.id,
    )
    db.add(contract)
    db.flush()  # get contract.id without committing

    version = ContractVersion(
        contract_db_id    = contract.id,
        contract_id       = contract_id,
        version_number    = 1,
        file_path         = str(dest),
        original_filename = file.filename or dest.name,
        status            = "uploaded",
        uploaded_by_user_id = current_user.id,
        uploaded_at       = _utcnow(),
    )
    db.add(version)
    db.flush()  # get version.id

    contract.current_version_id = version.id
    db.commit()
    db.refresh(contract)

    background_tasks.add_task(
        _bg_ingest,
        contract_db_id=contract.id,
        version_id=version.id,
        contract_file=dest,
        output_dir=analysis_dir,
    )
    return contract


@app.get(
    "/contracts",
    response_model=ContractListOut,
    tags=["contracts"],
    summary="List contracts for the calling user's tenant",
)
def list_contracts(
    status_filter:          str | None = Query(None, alias="status",
                                               description="uploaded|ingested|analyzed|failed"),
    review_status_filter:   str | None = Query(None, alias="review_status"),
    review_decision_filter: str | None = Query(None, alias="review_decision"),
    skip:                   int        = Query(0, ge=0),
    limit:                  int        = Query(50, ge=1, le=500),
    current_user:           User       = Depends(require_any_role),
    db:                     Session    = Depends(get_db),
) -> dict:
    q = db.query(Contract).filter(Contract.customer_id == current_user.customer_id)
    if status_filter:
        q = q.filter(Contract.status == status_filter)
    if review_status_filter:
        q = q.filter(Contract.review_status == review_status_filter)
    if review_decision_filter:
        q = q.filter(Contract.review_decision == review_decision_filter)
    total     = q.count()
    contracts = q.order_by(Contract.created_at.desc()).offset(skip).limit(limit).all()

    # Enrich with latest completed analysis data (single query, no N+1)
    cids = [c.contract_id for c in contracts]
    latest_map: dict[str, Analysis] = {}
    if cids:
        latest_analyses = (
            db.query(Analysis)
            .filter(Analysis.contract_id.in_(cids), Analysis.status == "completed")
            .order_by(Analysis.contract_id, Analysis.completed_at.desc())
            .all()
        )
        for a in latest_analyses:
            if a.contract_id not in latest_map:
                latest_map[a.contract_id] = a

    # Enrich with version counts (single query, no N+1)
    from sqlalchemy import func
    ver_counts: dict[str, int] = {}
    cur_ver_nums: dict[str, int] = {}
    if cids:
        ver_rows = (
            db.query(ContractVersion.contract_id, func.count(ContractVersion.id))
            .filter(ContractVersion.contract_id.in_(cids))
            .group_by(ContractVersion.contract_id)
            .all()
        )
        for cid, cnt in ver_rows:
            ver_counts[cid] = cnt
        # Current version numbers
        cur_ver_rows = (
            db.query(ContractVersion)
            .filter(ContractVersion.id.in_(
                [c.current_version_id for c in contracts if c.current_version_id]
            ))
            .all()
        ) if any(c.current_version_id for c in contracts) else []
        for ver in cur_ver_rows:
            cur_ver_nums[ver.contract_id] = ver.version_number

    items = []
    for c in contracts:
        la = latest_map.get(c.contract_id)
        d = ContractSummaryOut.model_validate(c).model_dump()
        d["latest_overall_risk"]       = la.overall_risk if la else None
        d["latest_analysis_at"]        = la.completed_at if la else None
        d["version_count"]             = ver_counts.get(c.contract_id, 1)
        d["current_version_number"]    = cur_ver_nums.get(c.contract_id)
        items.append(d)

    return {"total": total, "contracts": items}


@app.get(
    "/contracts/{contract_id}",
    response_model=ContractOut,
    tags=["contracts"],
    summary="Get a single contract (tenant-scoped)",
)
def get_contract(
    contract: Contract = Depends(get_tenant_contract),
) -> Contract:
    return contract


# ═══════════════════════════════════════════════════════════════════════════════
# WORKFLOW  (tenant-scoped)
# ═══════════════════════════════════════════════════════════════════════════════

def _workflow_event_dict(ev: ContractWorkflowEvent) -> dict:
    return {
        "id":                  ev.id,
        "contract_id":         ev.contract_id,
        "changed_by_user_id":  ev.changed_by_user_id,
        "changed_by_name":     ev.changed_by.name if ev.changed_by else None,
        "old_status":          ev.old_status,
        "new_status":          ev.new_status,
        "old_decision":        ev.old_decision,
        "new_decision":        ev.new_decision,
        "notes":               ev.notes,
        "created_at":          ev.created_at,
    }


@app.patch(
    "/contracts/{contract_id}/review-status",
    response_model=ContractOut,
    tags=["workflow"],
    summary="Update the review workflow state of a contract",
    description=(
        "**ADMIN or ANALYST role required** (with role-based restrictions).\n\n"
        "ANALYST may set `review_status` to: `analysis_completed`, `under_review`, `in_negotiation`.\n\n"
        "ADMIN may set any `review_status` including `approved`, `rejected`, `archived`.\n\n"
        "Only ADMIN may set `review_decision` to a value other than `none`.\n\n"
        "Archived contracts cannot be updated further."
    ),
)
def update_review_status(
    body:         ReviewStatusUpdate,
    current_user: User     = Depends(require_analyst_above),
    contract:     Contract = Depends(get_tenant_contract),
    db:           Session  = Depends(get_db),
) -> Contract:
    role = UserRole(current_user.role)

    # Archived contracts are read-only
    if contract.review_status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived contracts cannot be modified. Un-archive via ADMIN first.",
        )

    old_status   = contract.review_status
    old_decision = contract.review_decision
    changed      = False

    # ── review_status ─────────────────────────────────────────────────────────
    if body.review_status is not None and body.review_status != contract.review_status:
        if body.review_status in ADMIN_ONLY_STATUSES and role is not UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Setting review_status='{body.review_status}' requires ADMIN role.",
            )
        # Business rules
        if body.review_status == "approved":
            has_analysis = _latest_completed_analysis(contract.contract_id, db)
            if not has_analysis:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot approve a contract with no completed analysis.",
                )
        contract.review_status = body.review_status
        changed = True

    # ── review_decision ───────────────────────────────────────────────────────
    if body.review_decision is not None and body.review_decision != contract.review_decision:
        if body.review_decision != "none" and role is not UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Setting a review_decision other than 'none' requires ADMIN role.",
            )
        contract.review_decision = body.review_decision
        changed = True

    # ── review_owner_user_id ──────────────────────────────────────────────────
    if body.review_owner_user_id is not None:
        # Must be a user in the same tenant
        owner = db.query(User).filter(
            User.id == body.review_owner_user_id,
            User.customer_id == current_user.customer_id,
        ).first()
        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User id={body.review_owner_user_id} not found in your tenant.",
            )
        contract.review_owner_user_id = body.review_owner_user_id
        changed = True

    # ── internal_notes ────────────────────────────────────────────────────────
    if body.internal_notes is not None:
        contract.internal_notes = body.internal_notes
        changed = True

    if changed:
        contract.updated_at = _utcnow()
        # Set reviewed_at when a terminal decision is made
        if contract.review_status in ("approved", "rejected"):
            contract.reviewed_at = _utcnow()
        _emit_workflow_event(
            db,
            contract_id  = contract.contract_id,
            new_status   = contract.review_status,
            old_status   = old_status,
            new_decision = contract.review_decision if contract.review_decision != old_decision else None,
            old_decision = old_decision if contract.review_decision != old_decision else None,
            changed_by_id= current_user.id,
            notes        = body.internal_notes,
        )
        db.commit()

    db.refresh(contract)
    return contract


@app.get(
    "/contracts/{contract_id}/workflow",
    response_model=WorkflowOut,
    tags=["workflow"],
    summary="Get full workflow state for a contract",
)
def get_workflow(
    contract:     Contract = Depends(get_tenant_contract),
    current_user: User     = Depends(require_any_role),
    db:           Session  = Depends(get_db),
) -> dict:
    la = _latest_completed_analysis(contract.contract_id, db)
    events = (
        db.query(ContractWorkflowEvent)
        .filter(ContractWorkflowEvent.contract_id == contract.contract_id)
        .order_by(ContractWorkflowEvent.created_at.asc())
        .all()
    )
    owner_name: str | None = None
    if contract.review_owner_user_id:
        owner = db.query(User).filter(User.id == contract.review_owner_user_id).first()
        owner_name = owner.name if owner else None

    return {
        "contract_id":            contract.contract_id,
        "review_status":          contract.review_status,
        "review_decision":        contract.review_decision,
        "review_owner_user_id":   contract.review_owner_user_id,
        "review_owner_name":      owner_name,
        "reviewed_at":            contract.reviewed_at,
        "internal_notes":         contract.internal_notes,
        "has_completed_analysis": la is not None,
        "latest_overall_risk":    la.overall_risk if la else None,
        "events":                 [_workflow_event_dict(e) for e in events],
    }


@app.get(
    "/contracts/{contract_id}/history",
    response_model=HistoryOut,
    tags=["workflow"],
    summary="Full timeline: upload, analyses, and workflow events",
)
def get_contract_history(
    contract:     Contract = Depends(get_tenant_contract),
    current_user: User     = Depends(require_any_role),
    db:           Session  = Depends(get_db),
) -> dict:
    analyses = (
        db.query(Analysis)
        .filter(Analysis.contract_id == contract.contract_id)
        .order_by(Analysis.created_at.asc())
        .all()
    )
    events = (
        db.query(ContractWorkflowEvent)
        .filter(ContractWorkflowEvent.contract_id == contract.contract_id)
        .order_by(ContractWorkflowEvent.created_at.asc())
        .all()
    )
    return {
        "contract_id":     contract.contract_id,
        "uploaded_at":     contract.created_at,
        "analyses":        [AnalysisOut.model_validate(a).model_dump() for a in analyses],
        "workflow_events": [_workflow_event_dict(e) for e in events],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYSIS  (tenant-scoped)
# ═══════════════════════════════════════════════════════════════════════════════

@app.post(
    "/contracts/{contract_id}/analyze",
    response_model=AnalysisOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["analysis"],
    summary="Queue the full audit pipeline (stages 9-14)",
    description=(
        "**ADMIN or ANALYST role required.**\n\n"
        "Returns `202 Accepted` immediately.  "
        "Poll `GET /contracts/{id}/report` once status is `completed`."
    ),
)
def analyze(
    background_tasks: BackgroundTasks,
    current_user:     User     = Depends(require_analyst_above),
    contract:         Contract = Depends(get_tenant_contract),
    db:               Session  = Depends(get_db),
) -> Analysis:
    if contract.status == "uploaded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ingestion is still in progress. Retry shortly.",
        )
    if contract.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ingestion failed and cannot be analyzed. Error: {contract.error_message}",
        )

    running = (
        db.query(Analysis)
        .filter(
            Analysis.contract_id == contract.contract_id,
            Analysis.status.in_(["pending", "running"]),
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Analysis id={running.id} is already running for this contract.",
        )

    # Load and validate tenant's org_profile — mandatory for analysis
    customer    = db.query(Customer).filter(Customer.id == contract.customer_id).first()
    org_profile = _load_customer_profile(customer) if customer else None
    profile_err = validate_org_profile(org_profile)
    if profile_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=profile_err)

    # Create analysis record first to obtain the auto-generated ID
    analysis = Analysis(
        contract_id    = contract.contract_id,
        contract_db_id = contract.id,
        status         = "pending",
        output_dir     = "",  # updated below once we have the ID
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    # Each analysis run gets its own isolated output directory
    output_dir = ANALYSES_DIR / contract.contract_id / str(analysis.id)
    analysis.output_dir = str(output_dir)
    db.commit()

    background_tasks.add_task(
        _bg_analyze,
        analysis_id=analysis.id,
        contract_file=Path(contract.file_path),
        output_dir=output_dir,
        contract_id=contract.contract_id,
        org_profile=org_profile,
        version_id=contract.current_version_id,
        customer_id=current_user.customer_id,
    )
    return analysis


@app.get(
    "/contracts/{contract_id}/analyses",
    response_model=list[AnalysisOut],
    tags=["analysis"],
    summary="List all analysis runs for a contract",
)
def list_analyses(
    contract: Contract = Depends(get_tenant_contract),
    db:       Session  = Depends(get_db),
) -> list[Analysis]:
    return (
        db.query(Analysis)
        .filter(Analysis.contract_id == contract.contract_id)
        .order_by(Analysis.created_at.desc())
        .all()
    )


@app.get(
    "/contracts/{contract_id}/analyses/{analysis_id}",
    response_model=AnalysisStatusOut,
    tags=["analysis"],
    summary="Get a single analysis run status (tenant-scoped)",
    description=(
        "Returns the current status, stage, and output-readiness of one "
        "analysis run.  Suitable for polling — lightweight response."
    ),
)
def get_analysis_status(
    analysis_id: int,
    contract:    Contract = Depends(get_tenant_contract),
    db:          Session  = Depends(get_db),
) -> dict:
    analysis = (
        db.query(Analysis)
        .filter(
            Analysis.id          == analysis_id,
            Analysis.contract_id == contract.contract_id,
        )
        .first()
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis id={analysis_id} not found for contract '{contract.contract_id}'.",
        )
    return {
        "analysis_id":              analysis.id,
        "contract_id":              analysis.contract_id,
        "status":                   analysis.status,
        "current_stage":            analysis.current_stage,
        "started_at":               analysis.started_at,
        "completed_at":             analysis.completed_at,
        "error_message":            analysis.error_message,
        "outputs_ready":            analysis.outputs_ready,
        "org_profile_version_hash": analysis.org_profile_version_hash,
    }


@app.get(
    "/contracts/{contract_id}/status",
    response_model=AnalysisStatusOut,
    tags=["analysis"],
    summary="Latest analysis status for a contract (tenant-scoped)",
    description=(
        "Returns the most-recent analysis run for the contract.  "
        "Returns 404 if no analysis has ever been started."
    ),
)
def get_contract_analysis_status(
    contract: Contract = Depends(get_tenant_contract),
    db:       Session  = Depends(get_db),
) -> dict:
    analysis = (
        db.query(Analysis)
        .filter(Analysis.contract_id == contract.contract_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No analysis runs found for contract '{contract.contract_id}'.",
        )
    return {
        "analysis_id":              analysis.id,
        "contract_id":              analysis.contract_id,
        "status":                   analysis.status,
        "current_stage":            analysis.current_stage,
        "started_at":               analysis.started_at,
        "completed_at":             analysis.completed_at,
        "error_message":            analysis.error_message,
        "outputs_ready":            analysis.outputs_ready,
        "org_profile_version_hash": analysis.org_profile_version_hash,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTS  (tenant-scoped, all roles)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get(
    "/contracts/{contract_id}/report",
    response_model=ReportOut,
    tags=["reports"],
    summary="Return the contract risk report (stage14 output)",
)
def get_report(
    contract: Contract = Depends(get_tenant_contract),
    db:       Session  = Depends(get_db),
) -> dict:
    analysis = _latest_completed_analysis(contract.contract_id, db)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed analysis found. Run POST /contracts/{id}/analyze first.",
        )
    report = _read_analysis_file(analysis, "contract_risk_report.json")
    return {"contract_id": contract.contract_id, "analysis_id": analysis.id, "report": report}


@app.get(
    "/contracts/{contract_id}/negotiation",
    response_model=NegotiationOut,
    tags=["reports"],
    summary="Return the negotiation package (stage13 output)",
)
def get_negotiation(
    contract: Contract = Depends(get_tenant_contract),
    db:       Session  = Depends(get_db),
) -> dict:
    analysis = _latest_completed_analysis(contract.contract_id, db)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed analysis found. Run POST /contracts/{id}/analyze first.",
        )
    package = _read_analysis_file(analysis, "negotiation_package.json")
    return {"contract_id": contract.contract_id, "analysis_id": analysis.id, "package": package}


# ═══════════════════════════════════════════════════════════════════════════════
# CONTRACT VERSIONING  (tenant-scoped)
# ═══════════════════════════════════════════════════════════════════════════════

def _get_tenant_version(
    contract_id: str,
    version_id: int,
    current_user: User,
    db: Session,
) -> tuple[Contract, ContractVersion]:
    """Return (contract, version) guarding tenant isolation; 404 on miss."""
    contract = (
        db.query(Contract)
        .filter(
            Contract.contract_id == contract_id,
            Contract.customer_id == current_user.customer_id,
        )
        .first()
    )
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")
    ver = (
        db.query(ContractVersion)
        .filter(
            ContractVersion.id          == version_id,
            ContractVersion.contract_id == contract_id,
        )
        .first()
    )
    if ver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version id={version_id} not found for contract '{contract_id}'.",
        )
    return contract, ver


def _latest_completed_analysis_for_version(version_id: int, db: Session) -> Analysis | None:
    return (
        db.query(Analysis)
        .filter(Analysis.version_id == version_id, Analysis.status == "completed")
        .order_by(Analysis.completed_at.desc())
        .first()
    )


def _version_out(ver: ContractVersion, db: Session) -> dict:
    """Build ContractVersionOut dict, enriching with latest analysis data."""
    la = _latest_completed_analysis_for_version(ver.id, db)
    d = ContractVersionOut.model_validate(ver).model_dump()
    d["latest_overall_risk"] = la.overall_risk if la else None
    d["latest_analysis_at"]  = la.completed_at  if la else None
    return d


@app.post(
    "/contracts/{contract_id}/versions/upload",
    response_model=ContractVersionOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["versions"],
    summary="Upload a revised version of a contract",
)
async def upload_version(
    contract_id:      str,
    background_tasks: BackgroundTasks,
    file:         UploadFile = File(...),
    current_user: User       = Depends(require_analyst_above),
    db:           Session    = Depends(get_db),
) -> dict:
    contract = (
        db.query(Contract)
        .filter(
            Contract.contract_id == contract_id,
            Contract.customer_id == current_user.customer_id,
        )
        .first()
    )
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Determine next version number
    max_ver = (
        db.query(ContractVersion)
        .filter(ContractVersion.contract_id == contract_id)
        .order_by(ContractVersion.version_number.desc())
        .first()
    )
    version_number = (max_ver.version_number + 1) if max_ver else 2

    # Store under /contracts/{contract_id}/v{n}/original.{ext}
    version_dir = CONTRACTS_DIR / contract_id / f"v{version_number}"
    version_dir.mkdir(parents=True, exist_ok=True)
    dest = version_dir / f"original{suffix}"

    total = 0
    async with aiofiles.open(dest, "wb") as out:
        while chunk := await file.read(256 * 1024):
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                await out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds the {MAX_FILE_BYTES // (1024**2)} MB limit.",
                )
            await out.write(chunk)

    version = ContractVersion(
        contract_db_id    = contract.id,
        contract_id       = contract_id,
        version_number    = version_number,
        file_path         = str(dest),
        original_filename = file.filename or dest.name,
        status            = "uploaded",
        uploaded_by_user_id = current_user.id,
        uploaded_at       = _utcnow(),
    )
    db.add(version)
    db.flush()

    # Advance the contract's current version pointer
    contract.current_version_id = version.id
    # Reset case-level status so new version must go through workflow again
    if contract.review_status not in ("archived",):
        old_rs = contract.review_status
        contract.review_status  = "uploaded"
        contract.review_decision = "none"
        _emit_workflow_event(
            db, contract_id,
            new_status="uploaded", old_status=old_rs,
            notes=f"Reset for v{version_number} upload",
        )
    contract.updated_at = _utcnow()
    db.commit()
    db.refresh(version)

    analysis_dir = ANALYSES_DIR / contract_id / f"version_{version.id}"
    background_tasks.add_task(
        _bg_ingest_version,
        version_id=version.id,
        contract_file=dest,
        output_dir=analysis_dir,
    )
    return _version_out(version, db)


@app.get(
    "/contracts/{contract_id}/versions",
    response_model=VersionListOut,
    tags=["versions"],
    summary="List all versions of a contract",
)
def list_versions(
    contract_id:  str,
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> dict:
    contract = (
        db.query(Contract)
        .filter(
            Contract.contract_id == contract_id,
            Contract.customer_id == current_user.customer_id,
        )
        .first()
    )
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")
    versions = (
        db.query(ContractVersion)
        .filter(ContractVersion.contract_id == contract_id)
        .order_by(ContractVersion.version_number.asc())
        .all()
    )
    items = [_version_out(v, db) for v in versions]
    return {"total": len(items), "versions": items}


@app.get(
    "/contracts/{contract_id}/versions/{version_id}",
    response_model=ContractVersionOut,
    tags=["versions"],
    summary="Get a single version",
)
def get_version(
    contract_id:  str,
    version_id:   int,
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> dict:
    _, ver = _get_tenant_version(contract_id, version_id, current_user, db)
    return _version_out(ver, db)


@app.post(
    "/contracts/{contract_id}/versions/{version_id}/analyze",
    response_model=AnalysisOut,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["versions"],
    summary="Queue analysis for a specific version",
)
def analyze_version(
    contract_id:      str,
    version_id:       int,
    background_tasks: BackgroundTasks,
    current_user:     User    = Depends(require_analyst_above),
    db:               Session = Depends(get_db),
) -> Analysis:
    contract, ver = _get_tenant_version(contract_id, version_id, current_user, db)

    if ver.status == "uploaded":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Version ingestion is still in progress. Retry shortly.",
        )
    if ver.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version ingestion failed: {ver.error_message}",
        )

    running = (
        db.query(Analysis)
        .filter(
            Analysis.version_id == version_id,
            Analysis.status.in_(["pending", "running"]),
        )
        .first()
    )
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Analysis id={running.id} is already running for this version.",
        )

    customer    = db.query(Customer).filter(Customer.id == contract.customer_id).first()
    org_profile = _load_customer_profile(customer) if customer else None
    profile_err = validate_org_profile(org_profile)
    if profile_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=profile_err)

    analysis = Analysis(
        contract_id    = contract_id,
        contract_db_id = contract.id,
        version_id     = version_id,
        status         = "pending",
        output_dir     = "",
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    output_dir = ANALYSES_DIR / contract_id / str(analysis.id)
    analysis.output_dir = str(output_dir)
    db.commit()

    background_tasks.add_task(
        _bg_analyze,
        analysis_id=analysis.id,
        contract_file=Path(ver.file_path),
        output_dir=output_dir,
        contract_id=contract_id,
        org_profile=org_profile,
        version_id=version_id,
        customer_id=current_user.customer_id,
    )
    return analysis


@app.get(
    "/contracts/{contract_id}/versions/{version_id}/report",
    response_model=ReportOut,
    tags=["versions"],
    summary="Risk report for a specific version",
)
def get_version_report(
    contract_id:  str,
    version_id:   int,
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> dict:
    _, ver = _get_tenant_version(contract_id, version_id, current_user, db)
    analysis = _latest_completed_analysis_for_version(version_id, db)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed analysis for this version.",
        )
    report = _read_analysis_file(analysis, "contract_risk_report.json")
    return {"contract_id": contract_id, "analysis_id": analysis.id, "report": report}


@app.get(
    "/contracts/{contract_id}/versions/{version_id}/negotiation",
    response_model=NegotiationOut,
    tags=["versions"],
    summary="Negotiation package for a specific version",
)
def get_version_negotiation(
    contract_id:  str,
    version_id:   int,
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> dict:
    _, ver = _get_tenant_version(contract_id, version_id, current_user, db)
    analysis = _latest_completed_analysis_for_version(version_id, db)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed analysis for this version.",
        )
    package = _read_analysis_file(analysis, "negotiation_package.json")
    return {"contract_id": contract_id, "analysis_id": analysis.id, "package": package}


@app.patch(
    "/contracts/{contract_id}/versions/{version_id}/review-status",
    response_model=ContractVersionOut,
    tags=["versions"],
    summary="Update workflow state for a specific version",
)
def update_version_review_status(
    contract_id:  str,
    version_id:   int,
    body:         ReviewStatusUpdate,
    current_user: User    = Depends(require_analyst_above),
    db:           Session = Depends(get_db),
) -> dict:
    _, ver = _get_tenant_version(contract_id, version_id, current_user, db)
    role = UserRole(current_user.role)

    if ver.review_status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived versions cannot be modified.",
        )

    changed = False

    if body.review_status is not None and body.review_status != ver.review_status:
        if body.review_status in ADMIN_ONLY_STATUSES and role is not UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Setting review_status='{body.review_status}' requires ADMIN role.",
            )

        # ── archived: only from approved or rejected ───────────────────────
        if body.review_status == "archived":
            if ver.review_status not in ("approved", "rejected"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot archive: version must be in 'approved' or 'rejected' state "
                        f"(currently '{ver.review_status}')."
                    ),
                )

        # ── approved / conditional_approve: require readiness ──────────────
        if body.review_status == "approved" or (
            body.review_decision == "conditional_approve"
        ):
            if not _latest_completed_analysis_for_version(version_id, db):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot approve a version with no completed analysis.",
                )
            readiness_data = _compute_approval_readiness(version_id, db)
            readiness = readiness_data["approval_readiness"]
            if body.review_status == "approved":
                if readiness != "ready_for_approval":
                    counts = readiness_data["counts"]
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Cannot approve: approval_readiness is '{readiness}'. "
                            f"Unresolved HIGH: {counts.high_open}, MEDIUM: {counts.medium_open}. "
                            "All HIGH and MEDIUM findings must be resolved, accepted, or marked not_applicable."
                        ),
                    )
            elif body.review_decision == "conditional_approve":
                min_readiness = "ready_for_conditional_approval"
                if READINESS_ORDER.index(readiness) < READINESS_ORDER.index(min_readiness):
                    counts = readiness_data["counts"]
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Cannot conditionally approve: approval_readiness is '{readiness}'. "
                            f"Unresolved HIGH: {counts.high_open}, MEDIUM: {counts.medium_open}. "
                            "All HIGH findings must be resolved, accepted, or marked not_applicable."
                        ),
                    )

        # ── rejected: require a decision ──────────────────────────────────
        if body.review_status == "rejected":
            incoming_decision = body.review_decision or ver.review_decision
            if incoming_decision == "none":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot reject without setting review_decision to 'reject'.",
                )

        ver.review_status = body.review_status
        changed = True

    if body.review_decision is not None and body.review_decision != ver.review_decision:
        if body.review_decision != "none" and role is not UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Setting a review_decision other than 'none' requires ADMIN role.",
            )
        ver.review_decision = body.review_decision
        changed = True

    if body.review_owner_user_id is not None:
        owner = db.query(User).filter(
            User.id == body.review_owner_user_id,
            User.customer_id == current_user.customer_id,
        ).first()
        if owner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User id={body.review_owner_user_id} not found in your tenant.",
            )
        ver.review_owner_user_id = body.review_owner_user_id
        changed = True

    if body.internal_notes is not None:
        ver.internal_notes = body.internal_notes
        changed = True

    if changed:
        if ver.review_status in ("approved", "rejected"):
            ver.reviewed_at = _utcnow()
        # ── Approval audit event ───────────────────────────────────────────
        # When transitioning to approved / rejected / archived, snapshot
        # the current readiness counts into the workflow event notes.
        if body.review_status in ("approved", "rejected", "archived"):
            readiness_snap = _compute_approval_readiness(version_id, db)
            snap_counts = readiness_snap["counts"]
            audit_notes = json.dumps({
                "readiness":        readiness_snap["approval_readiness"],
                "high_open":        snap_counts.high_open,
                "medium_open":      snap_counts.medium_open,
                "resolved":         snap_counts.resolved,
                "accepted_risk":    snap_counts.accepted_risk,
                "review_decision":  ver.review_decision,
            })
            _emit_workflow_event(
                db,
                contract_id=contract_id,
                new_status=body.review_status,
                new_decision=ver.review_decision,
                notes=audit_notes,
                changed_by_id=current_user.id,
            )
        db.commit()

    # ── Closure bundle generation ──────────────────────────────────────────────
    # Trigger on approved / rejected only (archived versions keep the bundle from
    # when they were approved/rejected; it remains immutable).
    if changed and body.review_status in ("approved", "rejected"):
        la = _latest_completed_analysis_for_version(version_id, db)
        if la:
            # Fetch the parent contract for bundle metadata
            contract_obj = (
                db.query(Contract)
                .filter(Contract.contract_id == contract_id)
                .first()
            )
            if contract_obj:
                try:
                    _generate_closure_bundle(contract_obj, ver, la, db)
                except Exception:
                    # Bundle failure must not block the workflow save
                    pass

    return _version_out(ver, db)


@app.get(
    "/contracts/{contract_id}/versions/{version_id}/workflow",
    response_model=WorkflowOut,
    tags=["versions"],
    summary="Workflow state for a specific version",
)
def get_version_workflow(
    contract_id:  str,
    version_id:   int,
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> dict:
    _, ver = _get_tenant_version(contract_id, version_id, current_user, db)
    la = _latest_completed_analysis_for_version(version_id, db)
    owner_name: str | None = None
    if ver.review_owner_user_id:
        owner = db.query(User).filter(User.id == ver.review_owner_user_id).first()
        owner_name = owner.name if owner else None
    return {
        "contract_id":            contract_id,
        "review_status":          ver.review_status,
        "review_decision":        ver.review_decision,
        "review_owner_user_id":   ver.review_owner_user_id,
        "review_owner_name":      owner_name,
        "reviewed_at":            ver.reviewed_at,
        "internal_notes":         ver.internal_notes,
        "has_completed_analysis": la is not None,
        "latest_overall_risk":    la.overall_risk if la else None,
        "events":                 [],  # version-level events not tracked separately
    }


@app.get(
    "/contracts/{contract_id}/versions/{version_id}/history",
    response_model=HistoryOut,
    tags=["versions"],
    summary="Analysis history for a specific version",
)
def get_version_history(
    contract_id:  str,
    version_id:   int,
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> dict:
    contract, ver = _get_tenant_version(contract_id, version_id, current_user, db)
    analyses = (
        db.query(Analysis)
        .filter(Analysis.version_id == version_id)
        .order_by(Analysis.created_at.asc())
        .all()
    )
    return {
        "contract_id":     contract_id,
        "uploaded_at":     ver.uploaded_at,
        "analyses":        [AnalysisOut.model_validate(a).model_dump() for a in analyses],
        "workflow_events": [],
    }


@app.get(
    "/contracts/{contract_id}/compare",
    response_model=CompareVersionOut,
    tags=["versions"],
    summary="Compare two versions' risk profiles side-by-side",
)
def compare_versions(
    contract_id:  str,
    from_version: int = Query(..., description="Version number to compare from"),
    to_version:   int = Query(..., description="Version number to compare to"),
    current_user: User    = Depends(require_any_role),
    db:           Session = Depends(get_db),
) -> dict:
    contract = (
        db.query(Contract)
        .filter(
            Contract.contract_id == contract_id,
            Contract.customer_id == current_user.customer_id,
        )
        .first()
    )
    if contract is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found.")

    ver_from = (
        db.query(ContractVersion)
        .filter(
            ContractVersion.contract_id == contract_id,
            ContractVersion.version_number == from_version,
        )
        .first()
    )
    ver_to = (
        db.query(ContractVersion)
        .filter(
            ContractVersion.contract_id == contract_id,
            ContractVersion.version_number == to_version,
        )
        .first()
    )
    if ver_from is None or ver_to is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version(s) not found: from={from_version}, to={to_version}.",
        )

    def _ver_summary(ver: ContractVersion) -> dict:
        la = _latest_completed_analysis_for_version(ver.id, db)
        report: dict = {}
        if la:
            report = _safe_read_json(
                Path(la.output_dir) / "contract_risk_report.json"
            ) or {}
        meta = report.get("metadata", {}) if report else {}
        topics = {
            item.get("topic")
            for item in report.get("risk_distribution", [])
            if item.get("topic")
        }
        return {
            "version_number":   ver.version_number,
            "original_filename": ver.original_filename,
            "review_status":    ver.review_status,
            "overall_risk":     (la.overall_risk if la else None),
            "total_findings":   (la.total_findings or meta.get("total_findings") or 0) if la else 0,
            "high_risk_clauses":   (la.high_risk_clauses   or 0) if la else 0,
            "medium_risk_clauses": (la.medium_risk_clauses or 0) if la else 0,
            "low_risk_clauses":    (la.low_risk_clauses    or 0) if la else 0,
            "risk_topics":      list(topics),
            "has_analysis":     la is not None,
        }

    from_s = _ver_summary(ver_from)
    to_s   = _ver_summary(ver_to)

    from_topics = set(from_s["risk_topics"])
    to_topics   = set(to_s["risk_topics"])

    return {
        "contract_id":    contract_id,
        "from_version":   from_version,
        "to_version":     to_version,
        "from_summary":   from_s,
        "to_summary":     to_s,
        "risk_changed":   from_s["overall_risk"] != to_s["overall_risk"],
        "findings_delta": to_s["total_findings"]   - from_s["total_findings"],
        "high_delta":     to_s["high_risk_clauses"] - from_s["high_risk_clauses"],
        "medium_delta":   to_s["medium_risk_clauses"] - from_s["medium_risk_clauses"],
        "low_delta":      to_s["low_risk_clauses"]  - from_s["low_risk_clauses"],
        "new_topics":     sorted(to_topics - from_topics),
        "resolved_topics": sorted(from_topics - to_topics),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FINDING REVIEWS  (Phase 8)
# ═══════════════════════════════════════════════════════════════════════════════

def _finding_review_out(fr: "FindingReview") -> FindingReviewOut:
    d = FindingReviewOut.model_validate(fr)
    d.reviewer_name = fr.reviewer.name if fr.reviewer else None
    d.assignee_name = fr.assignee.name if fr.assignee else None
    return d


def _get_app_setting(customer_id: int, key: str, db: "Session") -> str | None:
    """Return the value of an app_setting row, or None if not set."""
    row = db.query(AppSetting).filter(
        AppSetting.customer_id == customer_id,
        AppSetting.key         == key,
    ).first()
    return row.value if row else None


def _set_app_setting(customer_id: int, key: str, value: str, db: "Session") -> None:
    """Upsert an app_setting row."""
    row = db.query(AppSetting).filter(
        AppSetting.customer_id == customer_id,
        AppSetting.key         == key,
    ).first()
    if row:
        row.value      = value
        row.updated_at = _utcnow()
    else:
        db.add(AppSetting(
            customer_id = customer_id,
            key         = key,
            value       = value,
            updated_at  = _utcnow(),
        ))
    db.commit()


@app.get(
    "/contracts/{case_id}/versions/{version_id}/findings/summary",
    response_model=FindingsSummaryWithReadinessOut,
    tags=["findings"],
    summary="Finding counts by status/severity + approval readiness for a contract version",
)
def get_findings_summary(
    case_id:    str,
    version_id: int,
    user:       User = Depends(require_any_role),
    db:         Session = Depends(get_db),
) -> FindingsSummaryWithReadinessOut:
    _get_tenant_version(case_id, version_id, user, db)  # auth + existence check
    rows = (
        db.query(FindingReview)
        .filter(
            FindingReview.contract_id == case_id,
            FindingReview.version_id  == version_id,
        )
        .all()
    )
    by_sev: dict[str, int] = {}
    counts: dict[str, int] = {
        "open": 0, "in_review": 0, "in_negotiation": 0, "resolved": 0,
        "accepted_risk": 0, "not_applicable": 0, "deferred": 0,
    }
    for r in rows:
        st = r.status or "open"
        if st in counts:
            counts[st] += 1
        sv = (r.severity or "UNKNOWN").upper()
        by_sev[sv] = by_sev.get(sv, 0) + 1
    readiness_data = _compute_approval_readiness(version_id, db)
    rc = readiness_data["counts"]
    return FindingsSummaryWithReadinessOut(
        total=len(rows),
        **counts,
        by_severity=by_sev,
        approval_readiness=readiness_data["approval_readiness"],
        unresolved_high_count=rc.high_open,
        unresolved_medium_count=rc.medium_open,
    )


@app.get(
    "/contracts/{case_id}/versions/{version_id}/approval-readiness",
    response_model=ApprovalReadinessOut,
    tags=["findings"],
    summary="Approval readiness evaluation for a contract version",
    description=(
        "Evaluates whether a version's findings disposition allows approval.\n\n"
        "Readiness levels (least → most ready):\n"
        "- **blocked**: HIGH findings are still open/in_review/deferred\n"
        "- **review_required**: MEDIUM findings still need attention\n"
        "- **ready_for_conditional_approval**: HIGH all closed; MEDIUM may be in_negotiation/deferred\n"
        "- **ready_for_approval**: All HIGH and MEDIUM findings closed\n"
    ),
)
def get_approval_readiness(
    case_id:    str,
    version_id: int,
    user:       User    = Depends(require_any_role),
    db:         Session = Depends(get_db),
) -> ApprovalReadinessOut:
    _get_tenant_version(case_id, version_id, user, db)
    data = _compute_approval_readiness(version_id, db)
    return ApprovalReadinessOut(
        contract_id=case_id,
        version_id=version_id,
        **data,
    )


# ── Clause explorer endpoints ─────────────────────────────────────────────────

@app.get(
    "/contracts/{case_id}/versions/{version_id}/clauses",
    response_model=ClauseListOut,
    tags=["clauses"],
    summary="List all extracted clauses for a version with enrichment",
    description=(
        "Returns all clauses from stage4_clauses.json enriched with obligation "
        "assessments, SR match counts, finding status summaries, and risk scores.\n\n"
        "**Filter params**\n"
        "- `severity`: HIGH | MEDIUM | LOW (from obligation analysis)\n"
        "- `topic`: partial case-insensitive match against obligation topic\n"
        "- `finding_status`: filter to clauses that have ≥1 finding with this status\n"
        "- `layout_type`: paragraph | bullet_list | table | heading\n"
        "- `min_risk_score`: numeric threshold (inclusive)\n"
        "- `q`: full-text search over clause text (LIKE contains)\n"
    ),
)
def list_clauses(
    case_id:        str,
    version_id:     int,
    severity:       str | None = Query(None, description="Filter by severity (HIGH/MEDIUM/LOW)"),
    topic:          str | None = Query(None, description="Partial topic filter (case-insensitive)"),
    finding_status: str | None = Query(None, description="Only clauses with a finding in this status"),
    layout_type:    str | None = Query(None, description="Filter by layout_type"),
    min_risk_score: float | None = Query(None, description="Minimum risk score (inclusive)"),
    q:              str | None = Query(None, description="Full-text search over clause text"),
    user:           User    = Depends(require_any_role),
    db:             Session = Depends(get_db),
) -> ClauseListOut:
    contract, ver = _get_tenant_version(case_id, version_id, user, db)
    analysis = _latest_completed_analysis_for_version(version_id, db)
    if analysis is None:
        # Return empty list if no analysis yet — don't 404
        return ClauseListOut(version_id=version_id, total=0, clauses=[])

    clause_idx, obligation_idx, sr_idx, risk_idx, neg_idx = _build_clause_indexes(analysis)

    # Load all finding_reviews for this version, grouped by clause_id
    all_findings = (
        db.query(FindingReview)
        .filter(FindingReview.version_id == version_id)
        .all()
    )
    findings_by_clause: dict[str, list[FindingReview]] = {}
    for f in all_findings:
        cid = f.clause_id or ""
        findings_by_clause.setdefault(cid, []).append(f)

    items: list[ClauseListItem] = []
    for cid, c in clause_idx.items():
        clause_findings = findings_by_clause.get(cid, [])
        ob = obligation_idx.get(cid, {})
        rs = risk_idx.get(cid, {})

        # ── Apply filters ──────────────────────────────────────────────────
        sev = ob.get("severity") or rs.get("severity")
        if severity and (sev or "").upper() != severity.upper():
            continue

        clause_topic = ob.get("negotiation_topic") or rs.get("topic") or ""
        if topic and topic.lower() not in clause_topic.lower():
            continue

        if layout_type and c.get("layout_type", "") != layout_type:
            continue

        if min_risk_score is not None:
            score = rs.get("risk_score", 0.0)
            if score < min_risk_score:
                continue

        if finding_status:
            if not any(f.status == finding_status for f in clause_findings):
                continue

        text = c.get("text", "")
        if q and q.lower() not in text.lower():
            continue

        items.append(_clause_list_item(c, obligation_idx, sr_idx, risk_idx, clause_findings))

    # Sort: HIGH severity first, then by risk_score desc, then clause_id
    _sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda x: (
        _sev_order.get((x.severity or "").upper(), 3),
        -(x.risk_score or 0.0),
        x.clause_id,
    ))

    return ClauseListOut(version_id=version_id, total=len(items), clauses=items)


@app.get(
    "/contracts/{case_id}/versions/{version_id}/clauses/{clause_id}",
    response_model=ClauseDetailOut,
    tags=["clauses"],
    summary="Full clause-centric detail view",
)
def get_clause_detail(
    case_id:    str,
    version_id: int,
    clause_id:  str,
    user:       User    = Depends(require_any_role),
    db:         Session = Depends(get_db),
) -> ClauseDetailOut:
    contract, ver = _get_tenant_version(case_id, version_id, user, db)
    analysis = _latest_completed_analysis_for_version(version_id, db)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed analysis found for this version.",
        )

    clause_idx, obligation_idx, sr_idx, risk_idx, neg_idx = _build_clause_indexes(analysis)

    if clause_id not in clause_idx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clause '{clause_id}' not found in this version's analysis.",
        )

    findings = (
        db.query(FindingReview)
        .filter(
            FindingReview.version_id == version_id,
            FindingReview.clause_id  == clause_id,
        )
        .all()
    )

    return _clause_detail_out(
        clause_id, clause_idx, obligation_idx, sr_idx, risk_idx, neg_idx,
        findings, ver, db,
    )


# ── Closure bundle endpoints ───────────────────────────────────────────────────

@app.get(
    "/contracts/{case_id}/versions/{version_id}/closure-bundle",
    response_model=ClosureBundleOut,
    tags=["versions"],
    summary="Closure bundle manifest for an approved / rejected version",
    description=(
        "Returns the manifest of the frozen audit-ready closure bundle "
        "generated when the version was approved or rejected.\n\n"
        "Returns 404 if the version has not been approved or rejected yet, "
        "or if the bundle has not been generated yet."
    ),
)
def get_closure_bundle(
    case_id:    str,
    version_id: int,
    user:       User    = Depends(require_any_role),
    db:         Session = Depends(get_db),
) -> ClosureBundleOut:
    contract, ver = _get_tenant_version(case_id, version_id, user, db)
    if ver.review_status not in ("approved", "rejected", "archived"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Closure bundle is only available for approved or rejected versions "
                f"(current status: '{ver.review_status}')."
            ),
        )
    analysis = _latest_completed_analysis_for_version(version_id, db)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed analysis found for this version.",
        )
    bd = _bundle_dir(analysis)
    manifest = _read_bundle_manifest(bd)
    if manifest is None:
        # Generate on-demand if not yet created (e.g. legacy records or retry)
        try:
            _generate_closure_bundle(contract, ver, analysis, db)
            manifest = _read_bundle_manifest(bd)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate closure bundle: {exc}",
            ) from exc
    if manifest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Closure bundle not yet available.",
        )
    manifest_obj = ClosureBundleManifestOut(**manifest)
    zip_path = bd / "closure_bundle.zip"
    return ClosureBundleOut(
        contract_id=case_id,
        version_id=version_id,
        manifest=manifest_obj,
        has_zip=zip_path.exists(),
    )


@app.get(
    "/contracts/{case_id}/versions/{version_id}/closure-bundle/download",
    tags=["versions"],
    summary="Download the closure bundle as a ZIP archive",
)
def download_closure_bundle(
    case_id:    str,
    version_id: int,
    user:       User    = Depends(require_any_role),
    db:         Session = Depends(get_db),
) -> StreamingResponse:
    contract, ver = _get_tenant_version(case_id, version_id, user, db)
    if ver.review_status not in ("approved", "rejected", "archived"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Closure bundle is only available for approved or rejected versions "
                f"(current status: '{ver.review_status}')."
            ),
        )
    analysis = _latest_completed_analysis_for_version(version_id, db)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed analysis found for this version.",
        )
    bd = _bundle_dir(analysis)
    zip_path = bd / "closure_bundle.zip"
    if not zip_path.exists():
        # Generate on-demand
        try:
            _generate_closure_bundle(contract, ver, analysis, db)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate closure bundle: {exc}",
            ) from exc
    if not zip_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ZIP archive not available.",
        )
    filename = f"closure_{case_id}_v{ver.version_number}_{ver.review_status}.zip"
    data = zip_path.read_bytes()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get(
    "/contracts/{case_id}/versions/{version_id}/findings",
    response_model=FindingsListOut,
    tags=["findings"],
    summary="List finding reviews for a contract version",
)
def list_findings(
    case_id:    str,
    version_id: int,
    severity:   str | None = Query(None, description="Filter by severity (HIGH/MEDIUM/LOW)"),
    status:     str | None = Query(None, description="Filter by status"),
    topic:      str | None = Query(None, description="Partial topic filter (case-insensitive)"),
    user:       User = Depends(require_any_role),
    db:         Session = Depends(get_db),
) -> FindingsListOut:
    _get_tenant_version(case_id, version_id, user, db)
    q = db.query(FindingReview).filter(
        FindingReview.contract_id == case_id,
        FindingReview.version_id  == version_id,
    )
    if severity:
        q = q.filter(FindingReview.severity == severity.upper())
    if status:
        q = q.filter(FindingReview.status == status.lower())
    if topic:
        q = q.filter(FindingReview.topic.ilike(f"%{topic}%"))
    rows = q.order_by(FindingReview.id).all()
    return FindingsListOut(
        total=len(rows),
        findings=[_finding_review_out(r) for r in rows],
    )


@app.patch(
    "/contracts/{case_id}/versions/{version_id}/findings/{finding_key:path}",
    response_model=FindingReviewOut,
    tags=["findings"],
    summary="Update a finding review's status, assignment, or comments",
)
def update_finding(
    case_id:     str,
    version_id:  int,
    finding_key: str,
    body:        FindingReviewUpdate,
    user:        User = Depends(require_any_role),
    db:          Session = Depends(get_db),
) -> FindingReviewOut:
    _get_tenant_version(case_id, version_id, user, db)
    fr = db.query(FindingReview).filter(
        FindingReview.contract_id == case_id,
        FindingReview.version_id  == version_id,
        FindingReview.finding_key == finding_key,
    ).first()
    if fr is None:
        raise HTTPException(status_code=404, detail="Finding not found.")
    # VIEWER cannot mutate
    if user.role == UserRole.VIEWER.value:
        raise HTTPException(status_code=403, detail="Viewers cannot update findings.")
    # ANALYST cannot set accepted_risk
    if (
        user.role == UserRole.ANALYST.value
        and body.status is not None
        and body.status not in ANALYST_FINDING_STATUSES
    ):
        raise HTTPException(
            status_code=403,
            detail=f"ANALYST role cannot set status '{body.status}'.",
        )
    if body.status is not None:
        fr.status = body.status
        fr.reviewer_user_id = user.id
    if body.assigned_user_id is not None:
        fr.assigned_user_id = body.assigned_user_id
    if body.review_comment is not None:
        fr.review_comment = body.review_comment
    if body.disposition_reason is not None:
        fr.disposition_reason = body.disposition_reason
    fr.updated_at = _utcnow()
    db.commit()
    db.refresh(fr)
    return _finding_review_out(fr)
