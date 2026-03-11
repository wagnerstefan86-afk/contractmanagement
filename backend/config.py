"""
Backend configuration — paths, limits, defaults.
All paths are absolute so the server can be launched from any directory.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

# ── Project root (the directory that contains contract_audit.py) ──────────────
PROJECT_DIR = Path(__file__).resolve().parent.parent   # /home/user

# ── Storage roots ─────────────────────────────────────────────────────────────
CONTRACTS_DIR = PROJECT_DIR / "contracts"   # uploaded contract files
ANALYSES_DIR  = PROJECT_DIR / "analyses"   # pipeline output per contract

# ── SQLite database ───────────────────────────────────────────────────────────
# Override DATABASE_URL to move the database file (e.g. to a persistent volume).
# Default: contracts.db alongside the project root.
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", f"sqlite:///{PROJECT_DIR}/contracts.db"
)

# ── Upload constraints ────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".txt"})
MAX_FILE_BYTES: int = 50 * 1024 * 1024   # 50 MB

# ── JWT settings ──────────────────────────────────────────────────────────────
# Override JWT_SECRET via environment variable in production.
# The default auto-generates a random secret per process, so tokens are
# invalidated on every server restart — acceptable for dev; set a stable
# secret for production.
JWT_SECRET:    str = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRY_HOURS: int = int(os.environ.get("JWT_EXPIRY_HOURS", "8"))

# ── LLM settings ──────────────────────────────────────────────────────────────
# LLM_ENABLED          true | false           — master on/off switch (default: true)
# LLM_PROVIDER         anthropic | openai     — provider selection (default: anthropic)
# LLM_MODEL            model name string      — overrides per-provider default
#                        Anthropic default: claude-opus-4-6
#                        OpenAI default:    gpt-4o
# LLM_API_KEY          unified key override   — falls back to provider-specific vars:
#                        Anthropic: ANTHROPIC_API_KEY
#                        OpenAI:    OPENAI_API_KEY
# LLM_TIMEOUT_SECONDS  integer seconds        — per-request timeout (default: 60)
#
# When LLM_ENABLED=false the pipeline runs fully deterministic (rule-based).
# When enabled, Stages 4.5, 5, and 8 use LLM-augmented analysis with
# deterministic fallback if the LLM call fails or times out.
#
# All LLM-produced outputs include _ai_metadata with:
#   llm_used, provider, model, prompt_version, confidence
# so audits can determine exactly which model and prompt version produced each result.
LLM_ENABLED:         bool = os.environ.get("LLM_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")
LLM_PROVIDER:        str  = os.environ.get("LLM_PROVIDER", "anthropic")
LLM_MODEL:           str  = os.environ.get("LLM_MODEL", "")
LLM_TIMEOUT_SECONDS: int  = int(os.environ.get("LLM_TIMEOUT_SECONDS", "60"))
