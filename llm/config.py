"""
LLM configuration — reads environment variables and returns a provider instance.

Environment variables:
  LLM_ENABLED          true | false              (default: true)
  LLM_PROVIDER         anthropic | openai        (default: anthropic)
  LLM_MODEL            model name string         (default: provider default)
  LLM_API_KEY          unified API key override  (falls back to provider-specific keys)
  LLM_TIMEOUT_SECONDS  request timeout           (default: 60)

Provider-specific key fallbacks:
  Anthropic: ANTHROPIC_API_KEY
  OpenAI:    OPENAI_API_KEY

Usage:
    from llm.config import get_llm_provider
    provider = get_llm_provider()   # returns BaseLLMProvider or None
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

# Ensure .env is loaded even when llm.config is imported directly (e.g. by CLI stage scripts)
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

log = logging.getLogger("llm.config")

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-opus-4-6",
    "openai":    "gpt-4o",
}


# ── Public factory ─────────────────────────────────────────────────────────────

def get_llm_provider(
    *,
    provider_override: Optional[str] = None,
    model_override:    Optional[str] = None,
    api_key_override:  Optional[str] = None,
) -> Optional["BaseLLMProvider"]:  # type: ignore[name-defined]
    """
    Read environment variables and return an initialised provider, or None.

    Returns None when:
      - LLM_ENABLED=false
      - No API key is available for the configured provider
      - The provider library is not installed
      - An unrecoverable configuration error occurs

    Optional keyword arguments allow callers to override env-var values
    (useful for testing or per-request overrides).
    """
    from llm.base import BaseLLMProvider  # late import avoids circular deps

    enabled = os.getenv("LLM_ENABLED", "true").strip().lower()
    if enabled in ("false", "0", "no", "off"):
        log.info("LLM disabled (LLM_ENABLED=%s)", enabled)
        return None

    provider_name = (
        provider_override
        or os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
    )
    model = (
        model_override
        or os.getenv("LLM_MODEL", "").strip()
        or _DEFAULT_MODELS.get(provider_name, "")
    )
    timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))

    # Resolve API key — unified LLM_API_KEY overrides provider-specific keys
    api_key = api_key_override or os.getenv("LLM_API_KEY")
    if not api_key:
        if provider_name == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
        elif provider_name == "openai":
            api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        log.warning(
            "LLM provider '%s' selected but no API key found. "
            "Set LLM_API_KEY or %s. Falling back to deterministic.",
            provider_name,
            "ANTHROPIC_API_KEY" if provider_name == "anthropic" else "OPENAI_API_KEY",
        )
        return None

    try:
        if provider_name == "anthropic":
            from llm.providers.anthropic_provider import AnthropicProvider
            return AnthropicProvider(api_key=api_key, model=model, timeout=timeout)

        if provider_name == "openai":
            from llm.providers.openai_provider import OpenAIProvider
            return OpenAIProvider(api_key=api_key, model=model, timeout=timeout)

        log.warning("Unknown LLM_PROVIDER '%s'. Falling back to deterministic.", provider_name)
        return None

    except ImportError as exc:
        log.warning(
            "LLM provider '%s' library not installed (%s). "
            "pip install %s. Falling back to deterministic.",
            provider_name,
            exc,
            provider_name,
        )
        return None
    except RuntimeError as exc:
        log.error("LLM provider init failed: %s. Falling back to deterministic.", exc)
        return None
    except Exception as exc:
        log.error("Unexpected error initialising LLM provider: %s", exc)
        return None
