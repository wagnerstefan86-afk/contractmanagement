"""
Abstract base class for LLM providers.

All providers must implement _call_once(system_prompt, user_message, json_schema, max_tokens)
and return a dict matching the requested json_schema.

The base class provides:
  - retry with exponential backoff (up to MAX_RETRIES attempts)
  - RuntimeError propagation for unrecoverable errors (bad auth, missing key)
  - LLMResponse wrapping with LLMAuditMetadata for audit traceability
  - None return on exhausted retries (callers use deterministic fallback)
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("llm.base")


# ── Audit metadata ────────────────────────────────────────────────────────────

@dataclass
class LLMAuditMetadata:
    """
    Attached to every pipeline output to answer audit questions:
      - Was AI used for this result?
      - Which provider/model/prompt produced it?
      - What confidence did the model report?
    """
    llm_used:       bool
    provider:       Optional[str]  = None
    model:          Optional[str]  = None
    prompt_version: Optional[str]  = None
    confidence:     Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "llm_used":       self.llm_used,
            "provider":       self.provider,
            "model":          self.model,
            "prompt_version": self.prompt_version,
            "confidence":     self.confidence,
        }

    @staticmethod
    def deterministic() -> "LLMAuditMetadata":
        """Metadata for rule-based (non-LLM) outputs."""
        return LLMAuditMetadata(llm_used=False)


# Shared constant for deterministic (rule-based) audit metadata.
# Import this in stage files instead of duplicating the dict literal.
DETERMINISTIC_AI_META: dict = {
    "llm_used":       False,
    "provider":       None,
    "model":          None,
    "prompt_version": None,
    "confidence":     None,
}


@dataclass
class LLMResponse:
    """Structured response from a successful LLM provider call."""
    content:  dict
    metadata: LLMAuditMetadata


# ── Base provider ─────────────────────────────────────────────────────────────

class BaseLLMProvider(ABC):
    """
    Abstract LLM provider.

    Subclasses implement _call_once() for provider-specific API calls.
    complete_structured() wraps it with retry/backoff and audit metadata.
    """

    MAX_RETRIES:    int   = 3
    RETRY_BASE_SEC: float = 1.0

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier, e.g. 'anthropic' or 'openai'."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier as used in API calls, e.g. 'claude-opus-4-6'."""
        ...

    @abstractmethod
    def _call_once(
        self,
        system_prompt: str,
        user_message:  str,
        json_schema:   dict,
        max_tokens:    int,
    ) -> dict:
        """
        Single attempt at the LLM call.

        Must return a dict conforming to *json_schema*.
        Must raise RuntimeError (not a subclass) for unrecoverable errors
        (e.g. invalid API key) so the base class propagates them immediately.
        May raise any other exception for transient errors; those trigger retry.
        """
        ...

    def complete_structured(
        self,
        system_prompt:  str,
        user_message:   str,
        json_schema:    dict,
        prompt_version: str,
        max_tokens:     int = 1024,
    ) -> Optional[LLMResponse]:
        """
        Call the LLM with retry/exponential backoff.

        Returns:
            LLMResponse on success.
            None on exhausted retries — callers should fall back to deterministic logic.

        Raises:
            RuntimeError for unrecoverable errors (bad auth, missing key).
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                content = self._call_once(system_prompt, user_message, json_schema, max_tokens)
                metadata = LLMAuditMetadata(
                    llm_used       = True,
                    provider       = self.provider_name,
                    model          = self.model_name,
                    prompt_version = prompt_version,
                    confidence     = content.get("confidence"),
                )
                return LLMResponse(content=content, metadata=metadata)

            except RuntimeError:
                raise  # unrecoverable — propagate immediately

            except Exception as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES:
                    wait = self.RETRY_BASE_SEC * (2 ** (attempt - 1))
                    log.warning(
                        f"[{self.provider_name}] attempt {attempt}/{self.MAX_RETRIES} failed "
                        f"({type(exc).__name__}: {exc}). Retrying in {wait:.0f}s…"
                    )
                    time.sleep(wait)
                else:
                    log.warning(
                        f"[{self.provider_name}] attempt {attempt}/{self.MAX_RETRIES} failed "
                        f"({type(exc).__name__}: {exc}). Giving up."
                    )

        log.error(
            f"[{self.provider_name}] all {self.MAX_RETRIES} retries exhausted. "
            f"Last error: {last_exc}. Falling back to deterministic."
        )
        return None

    def is_available(self) -> bool:
        """
        Quick liveness probe — subclasses may override.
        Default: always True (assumes init already validated the key).
        """
        return True
