
"""Mistral chat completion provider using Python's standard library.

Shares the project's JSONProvider interface; never uploads PDFs or page images.
Only retrieved plaintext excerpts are sent to the model. API keys remain local.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .provider import ModelAnswer, ModelOutputError, prepare_strict_schema

MISTRAL_ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MISTRAL_MODEL = "mistral-small-2603"


class MistralProvider:
    def __init__(
        self,
        model: str = DEFAULT_MISTRAL_MODEL,
        max_output_tokens: int = 6000,
        *,
        key: str | None = None,
        timeout: float = 180.0,
        max_retries: int = 2,
        request_delay: float = 0.0,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.key = key or os.environ.get("MISTRAL_API_KEY")
        if not self.key:
            raise RuntimeError(
                "MISTRAL_API_KEY is missing. Set it in your PowerShell session "
                "or use --dry-run without an API key."
            )
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", model):
            raise ValueError("Invalid Mistral model name")
        if max_output_tokens < 1 or max_retries < 0 or request_delay < 0:
            raise ValueError("Output tokens must be positive; retries/delay nonnegative")
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_delay = request_delay
        self.opener = opener or urlopen
        self.sleeper = sleeper or time.sleep
        self._has_sent_request = False

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            MISTRAL_ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.key}",
            },
        )
        for attempt in range(self.max_retries + 1):
            if self._has_sent_request and self.request_delay:
                self.sleeper(self.request_delay)
            self._has_sent_request = True
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                message = str(exc.reason or "Request rejected")
                try:
                    error = json.loads(exc.read().decode("utf-8"))
                    if isinstance(error, dict):
                        message = str(error.get("message") or error.get("error", {}).get("message") or message)
                except (ValueError, UnicodeDecodeError, AttributeError):
                    pass
                # Respect Retry-After if available, but bound total retry delay.
                retry_after = 0.0
                try:
                    retry_after = float(exc.headers.get("Retry-After", "0")) if exc.headers else 0.0
                except (ValueError, TypeError):
                    pass
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    self.sleeper(min(max(retry_after, 2 ** (attempt + 1)), 30.0))
                    continue
                hint = (
                    " Verify model access and rate limits at https://admin.mistral.ai/plateforme/limits. "
                    "The monthly allowance does not override per-minute throttling."
                    if exc.code == 429 else ""
                )
                raise RuntimeError(f"Mistral API HTTP {exc.code}: {message}.{hint}") from exc
            except URLError as exc:
                if attempt < self.max_retries:
                    self.sleeper(min(2 ** (attempt + 1), 16.0))
                    continue
                raise RuntimeError(f"Network error calling Mistral API: {exc.reason}") from exc
            except (ValueError, UnicodeDecodeError) as exc:
                raise ModelOutputError("Mistral returned invalid HTTP JSON") from exc
        raise AssertionError("unreachable")

    def extract(self, *, system: str, user: str, schema: dict[str, Any], name: str) -> ModelAnswer:
        # Strict schemas are sent in the API's wire format, where the schema
        # property is called `schema` (Python SDK v2 uses `schema_definition`).
        print(
            f"[Mistral] Starting stage: {name} | "
            f"schema size: {len(json.dumps(schema))} characters",
            flush=True,
        )
        result = self._post({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system + "\nReturn a JSON object."},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64],
                    "schema": prepare_strict_schema(schema),
                    "strict": True,
                },
            },
            "temperature": 0,
            "random_seed": 42,
            "max_tokens": self.max_output_tokens,
        })
        choices = result.get("choices") or []
        if not choices:
            raise ModelOutputError("Mistral returned no choices")
        choice = choices[0]
        print(
            f"[Mistral] Stage: {name} | "
            f"finish_reason: {choice.get('finish_reason')} | "
            f"usage: {result.get('usage', {})} | "
            f"response_id: {result.get('id', '')}",
            flush=True,
        )
        if choice.get("finish_reason") != "stop":
            raise ModelOutputError(
                f"Mistral stopped without a complete answer: {choice.get('finish_reason')}. "
                "Try a smaller --specialty-budget or a higher --max-output-tokens "
                "within your model's output and tokens-per-minute limits."
            )
        content = (choice.get("message") or {}).get("content")
        if not isinstance(content, str):
            raise ModelOutputError("Mistral returned no textual JSON content")
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise ModelOutputError("Mistral did not return parseable JSON") from exc
        if not isinstance(data, dict):
            raise ModelOutputError("Mistral JSON response was not an object")
        usage = result.get("usage") or {}
        return ModelAnswer(
            data=data,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            response_id=str(result.get("id") or ""),
        )
