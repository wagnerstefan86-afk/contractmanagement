"""
Startup configuration validator for the Contract Analysis Platform backend.

Run this before starting the server to catch misconfiguration early:

    python -m backend.startup_check          # from /home/user
    python backend/startup_check.py          # from /home/user

Checks performed
----------------
1. Python version >= 3.10
2. Required Python packages installed
3. LLM configuration consistency:
   - Known provider name (anthropic | openai)
   - API key present when LLM_ENABLED=true
   - LLM_TIMEOUT_SECONDS is a valid positive integer
4. Filesystem: project directories are writable

Exit codes
----------
0  All checks passed — safe to start
1  One or more checks failed — fix errors before starting
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

# Resolve project root regardless of working directory
_HERE = Path(__file__).resolve().parent.parent   # /home/user


def _check_python_version() -> list[str]:
    errors = []
    major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) < (3, 10):
        errors.append(
            f"Python 3.10+ required; running {major}.{minor}. "
            "Upgrade Python before continuing."
        )
    return errors


def _check_packages() -> list[str]:
    """Verify all required packages can be imported."""
    required = [
        # Web framework
        ("fastapi",          "pip install fastapi"),
        ("uvicorn",          "pip install uvicorn[standard]"),
        ("aiofiles",         "pip install aiofiles"),
        ("multipart",        "pip install python-multipart"),
        # Database
        ("sqlalchemy",       "pip install sqlalchemy"),
        # Auth
        ("passlib",          "pip install passlib"),
        ("jose",             "pip install python-jose[cryptography]"),
        ("bcrypt",           "pip install bcrypt"),
        # Contract ingestion
        ("pdfminer",         "pip install pdfminer.six"),
        ("docx",             "pip install python-docx"),
        ("regex",            "pip install regex"),
    ]
    errors = []
    for module, install_hint in required:
        try:
            importlib.import_module(module)
        except ImportError:
            errors.append(f"Missing package '{module}'. Fix: {install_hint}")
    return errors


def _check_llm_config() -> list[str]:
    """Validate LLM environment variables for internal consistency."""
    errors = []
    warnings = []

    enabled_raw = os.getenv("LLM_ENABLED", "true").strip().lower()
    enabled = enabled_raw not in ("false", "0", "no", "off")

    if not enabled:
        # Nothing further to check — deterministic mode is always safe.
        return []

    # ── Provider name ───────────────────────────────────────────────────────
    provider = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    known_providers = {"anthropic", "openai"}
    if provider not in known_providers:
        errors.append(
            f"LLM_PROVIDER='{provider}' is not a supported provider. "
            f"Valid values: {', '.join(sorted(known_providers))}."
        )

    # ── API key ─────────────────────────────────────────────────────────────
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        if provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        provider_key = (
            "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
        )
        errors.append(
            f"LLM_ENABLED=true but no API key found. "
            f"Set LLM_API_KEY or {provider_key}. "
            f"To disable LLM, set LLM_ENABLED=false."
        )

    # ── Timeout ─────────────────────────────────────────────────────────────
    timeout_raw = os.getenv("LLM_TIMEOUT_SECONDS", "60").strip()
    try:
        timeout = int(timeout_raw)
        if timeout <= 0:
            errors.append(
                f"LLM_TIMEOUT_SECONDS must be a positive integer; got '{timeout_raw}'."
            )
    except ValueError:
        errors.append(
            f"LLM_TIMEOUT_SECONDS must be an integer; got '{timeout_raw}'."
        )

    # ── Provider library ────────────────────────────────────────────────────
    if provider == "anthropic":
        try:
            importlib.import_module("anthropic")
        except ImportError:
            errors.append(
                "LLM_PROVIDER=anthropic but 'anthropic' package is not installed. "
                "Fix: pip install anthropic"
            )
    elif provider == "openai":
        try:
            importlib.import_module("openai")
        except ImportError:
            errors.append(
                "LLM_PROVIDER=openai but 'openai' package is not installed. "
                "Fix: pip install openai"
            )

    return errors


def _check_filesystem() -> list[str]:
    """Verify that key directories exist or can be created and are writable."""
    errors = []
    dirs_to_check = [
        _HERE / "contracts",
        _HERE / "analyses",
    ]
    for d in dirs_to_check:
        try:
            d.mkdir(parents=True, exist_ok=True)
            # Write probe
            probe = d / ".write_probe"
            probe.write_text("ok")
            probe.unlink()
        except OSError as exc:
            errors.append(f"Directory '{d}' is not writable: {exc}")
    return errors


def _check_jwt_config() -> list[str]:
    """Warn when JWT_EXPIRY_HOURS is misconfigured."""
    errors = []
    expiry_raw = os.getenv("JWT_EXPIRY_HOURS", "8").strip()
    try:
        expiry = int(expiry_raw)
        if expiry <= 0:
            errors.append(
                f"JWT_EXPIRY_HOURS must be a positive integer; got '{expiry_raw}'."
            )
    except ValueError:
        errors.append(
            f"JWT_EXPIRY_HOURS must be an integer; got '{expiry_raw}'."
        )
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_checks(*, silent: bool = False) -> bool:
    """
    Execute all startup checks.

    Parameters
    ----------
    silent : bool
        If True, suppress all printed output (useful when called from tests).

    Returns
    -------
    bool
        True if all checks passed, False if any errors were found.
    """
    def _print(*args, **kwargs):
        if not silent:
            print(*args, **kwargs)

    all_errors: list[str] = []

    checks = [
        ("Python version",    _check_python_version),
        ("Required packages", _check_packages),
        ("LLM configuration", _check_llm_config),
        ("JWT configuration", _check_jwt_config),
        ("Filesystem access", _check_filesystem),
    ]

    _print("=" * 60)
    _print("  Contract Analysis Platform — Startup Check")
    _print("=" * 60)

    for label, fn in checks:
        errors = fn()
        if errors:
            _print(f"\n  [FAIL] {label}")
            for e in errors:
                _print(f"         ERROR: {e}")
            all_errors.extend(errors)
        else:
            _print(f"  [PASS] {label}")

    _print()
    if all_errors:
        _print(f"  {len(all_errors)} error(s) found. Fix before starting the server.")
        _print("=" * 60)
        return False
    else:
        _print("  All checks passed. Ready to start.")
        _print("=" * 60)
        return True


if __name__ == "__main__":
    ok = run_checks()
    sys.exit(0 if ok else 1)
