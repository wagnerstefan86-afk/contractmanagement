"""
OpenAI provider.

Uses the Chat Completions API with:
  - Structured output via response_format json_schema (strict mode)
  - System message for prompt caching (server-side, automatic)
  - Configurable timeout

Environment variables (resolved by llm.config, passed in as api_key):
  OPENAI_API_KEY  or  LLM_API_KEY

Default model: gpt-4o
"""
from __future__ import annotations

import json
import logging

from llm.base import BaseLLMProvider

log = logging.getLogger("llm.openai")


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Chat Completions provider with structured JSON output."""

    def __init__(
        self,
        api_key: str,
        model:   str = "gpt-4o",
        timeout: int = 60,
    ) -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise RuntimeError(
                "openai package not installed. pip install openai"
            ) from exc

        self._model   = model
        self._timeout = timeout
        self._client  = _openai.OpenAI(api_key=api_key, timeout=float(timeout))
        self._openai  = _openai

    @property
    def provider_name(self) -> str:
        return "openai"

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
        Single Chat Completions API call with structured JSON output.

        Raises RuntimeError for auth errors (unrecoverable).
        Raises any other exception for transient errors (triggers retry).
        """
        try:
            response = self._client.chat.completions.create(
                model      = self._model,
                max_tokens = max_tokens,
                messages   = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_message},
                ],
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name":   "structured_response",
                        "strict": True,
                        "schema": json_schema,
                    },
                },
            )

        except self._openai.AuthenticationError as exc:
            raise RuntimeError(f"OpenAI authentication failed: {exc}") from exc

        except self._openai.PermissionDeniedError as exc:
            raise RuntimeError(f"OpenAI permission denied: {exc}") from exc

        # All other exceptions bubble up to BaseLLMProvider for retry.

        choice = response.choices[0]
        content_str = choice.message.content
        if not content_str:
            raise ValueError("OpenAI response contained empty content.")

        return json.loads(content_str)
