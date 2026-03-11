"""
Anthropic Claude provider.

Uses the Messages API with:
  - Prompt caching (cache_control: ephemeral on system prompt)
  - Extended thinking (adaptive mode)
  - Native JSON schema structured output (output_config.format.json_schema)

Environment variables (resolved by llm.config, passed in as api_key):
  ANTHROPIC_API_KEY  or  LLM_API_KEY

Default model: claude-opus-4-6
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from llm.base import BaseLLMProvider

log = logging.getLogger("llm.anthropic")


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude provider using the Messages API."""

    def __init__(
        self,
        api_key: str,
        model:   str = "claude-opus-4-6",
        timeout: int = 60,
    ) -> None:
        try:
            import anthropic as _anthropic
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package not installed. pip install anthropic"
            ) from exc

        self._model   = model
        self._timeout = timeout
        self._client  = _anthropic.Anthropic(api_key=api_key, timeout=float(timeout))
        self._anthropic = _anthropic

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    def _call_once(
        self,
        system_prompt: str,
        user_message:  str,
        json_schema:   dict,
        max_tokens:    int = 1024,
    ) -> dict:
        """
        Single Messages API call with prompt caching + structured JSON output.

        Raises RuntimeError for auth errors (unrecoverable).
        Raises any other exception for transient errors (triggers retry).
        """
        try:
            with self._client.messages.stream(
                model      = self._model,
                max_tokens = max_tokens,
                thinking   = {"type": "adaptive"},
                system = [
                    {
                        "type":          "text",
                        "text":          system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                output_config = {
                    "format": {
                        "type":   "json_schema",
                        "schema": json_schema,
                    }
                },
                messages = [{"role": "user", "content": user_message}],
            ) as stream:
                final = stream.get_final_message()

        except self._anthropic.AuthenticationError as exc:
            raise RuntimeError(f"Anthropic authentication failed: {exc}") from exc

        except self._anthropic.PermissionDeniedError as exc:
            raise RuntimeError(f"Anthropic permission denied: {exc}") from exc

        # All other exceptions (RateLimitError, APIConnectionError, etc.)
        # bubble up to BaseLLMProvider.complete_structured for retry.

        text_block: Optional[str] = next(
            (b.text for b in final.content
             if hasattr(b, "text") and getattr(b, "type", None) == "text"),
            None,
        )
        if not text_block:
            raise ValueError("Anthropic response contained no text block.")

        return json.loads(text_block)
