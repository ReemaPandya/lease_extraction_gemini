
"""Mistral chat completion provider using Python's standard library.

Shares the project's JSONProvider interface.
Only retrieved plaintext excerpts are sent to the model, not PDF files.

For Ministral 8B, the key_dates stage uses JSON mode as a workaround
for generation failures observed with strict JSON Schema mode.

The pipeline remains responsible for validating all generated JSON
against the original document schema.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .provider import (
    ModelAnswer,
    ModelOutputError,
    prepare_strict_schema,
)


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
                "MISTRAL_API_KEY is missing. "
                "Set it in your PowerShell session, "
                "or use --dry-run without an API key."
            )

        if not re.fullmatch(r"[a-zA-Z0-9_.-]+", model):
            raise ValueError("Invalid Mistral model name")

        if max_output_tokens < 1:
            raise ValueError(
                "max_output_tokens must be positive"
            )

        if max_retries < 0 or request_delay < 0:
            raise ValueError(
                "Retries and request delay must be nonnegative"
            )

        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_delay = request_delay

        self.opener = opener or urlopen
        self.sleeper = sleeper or time.sleep

        self._has_sent_request = False

    def _post(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a completion request to Mistral with bounded retries."""

        request = Request(
            MISTRAL_ENDPOINT,
            data=json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.key}",
            },
        )

        for attempt in range(self.max_retries + 1):

            # Delay between requests, including retry requests.
            if self._has_sent_request and self.request_delay:
                self.sleeper(self.request_delay)

            self._has_sent_request = True

            try:
                with self.opener(
                    request,
                    timeout=self.timeout,
                ) as response:

                    return json.loads(
                        response.read().decode("utf-8")
                    )

            except HTTPError as exc:

                message = str(
                    exc.reason or "Request rejected"
                )

                try:
                    error = json.loads(
                        exc.read().decode("utf-8")
                    )

                    if isinstance(error, dict):
                        nested_error = error.get("error")

                        if isinstance(nested_error, dict):
                            message = str(
                                error.get("message")
                                or nested_error.get("message")
                                or message
                            )
                        else:
                            message = str(
                                error.get("message")
                                or message
                            )

                except (
                    ValueError,
                    UnicodeDecodeError,
                    AttributeError,
                ):
                    pass

                retry_after = 0.0

                try:
                    if exc.headers:
                        retry_after = float(
                            exc.headers.get(
                                "Retry-After",
                                "0",
                            )
                        )
                except (ValueError, TypeError):
                    pass

                if (
                    exc.code in (429, 500, 502, 503, 504)
                    and attempt < self.max_retries
                ):

                    delay = min(
                        max(
                            retry_after,
                            2 ** (attempt + 1),
                        ),
                        30.0,
                    )

                    self.sleeper(delay)
                    continue

                hint = ""

                if exc.code == 429:
                    hint = (
                        " Check rate limits at "
                        "https://admin.mistral.ai/plateforme/limits. "
                        "Monthly credits do not override "
                        "per-minute rate limits."
                    )

                raise RuntimeError(
                    f"Mistral API HTTP {exc.code}: "
                    f"{message}.{hint}"
                ) from exc

            except URLError as exc:

                if attempt < self.max_retries:
                    self.sleeper(
                        min(
                            2 ** (attempt + 1),
                            16.0,
                        )
                    )
                    continue

                raise RuntimeError(
                    "Network error calling Mistral API: "
                    f"{exc.reason}"
                ) from exc

            except (
                ValueError,
                UnicodeDecodeError,
            ) as exc:

                raise ModelOutputError(
                    "Mistral returned invalid HTTP JSON"
                ) from exc

        raise AssertionError("Unreachable")

    def extract(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        name: str,
    ) -> ModelAnswer:
        """Generate one extraction-stage result.

        Strict JSON Schema is used by default.

        For the Ministral 8B key_dates stage, JSON mode is used
        because that stage previously failed during constrained
        generation with finish_reason='error'.

        The calling pipeline still validates the returned data
        against the original schema.
        """

        print(
            f"[Mistral] Starting stage: {name} | "
            f"model: {self.model} | "
            f"schema size: {len(json.dumps(schema))} characters",
            flush=True,
        )

        # -----------------------------------------------------
        # 1. Select response format
        # -----------------------------------------------------

        use_json_mode = (
            self.model == "ministral-8b-2512"
            and name == "lease_key_dates"
        )

        if use_json_mode:

            # JSON mode avoids strict schema-constrained
            # generation for the problematic key_dates stage.
            #
            # The schema remains part of the prompt.
            # Validation remains mandatory in the pipeline.

            response_format = {
                "type": "json_object",
            }

            user_message = (
                user
                + "\n\n"
                + "REQUIRED OUTPUT JSON SCHEMA:\n"
                + json.dumps(
                    schema,
                    ensure_ascii=False,
                )
                + "\n\n"
                + "Return exactly one JSON object that satisfies "
                  "the schema above. "
                + "Include every required property, including "
                  "all required nested properties. "
                + "Use the exact property names and JSON types. "
                + "Do not add unexpected properties. "
                + "Do not invent dates, terms, or facts that "
                  "are absent from the source document. "
                + "Use empty values only where permitted "
                  "by the supplied schema."
            )

        else:

            # Strict JSON Schema mode for all other stages.

            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": re.sub(
                        r"[^a-zA-Z0-9_-]",
                        "_",
                        name,
                    )[:64],
                    "schema": prepare_strict_schema(
                        schema
                    ),
                    "strict": True,
                },
            }

            user_message = user

        mode_name = (
            "json_object"
            if use_json_mode
            else "json_schema"
        )

        print(
            f"[Mistral] Stage: {name} | "
            f"output mode: {mode_name}",
            flush=True,
        )

        # -----------------------------------------------------
        # 2. Send API request
        # -----------------------------------------------------

        result = self._post(
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            system
                            + "\nReturn a JSON object."
                        ),
                    },
                    {
                        "role": "user",
                        "content": user_message,
                    },
                ],
                "response_format": response_format,
                "temperature": 0,
                "random_seed": 42,
                "max_tokens": self.max_output_tokens,
            }
        )

        # -----------------------------------------------------
        # 3. Check response
        # -----------------------------------------------------

        choices = result.get("choices") or []

        if not choices:
            raise ModelOutputError(
                "Mistral returned no choices"
            )

        choice = choices[0]

        finish_reason = choice.get(
            "finish_reason"
        )

        usage = result.get("usage") or {}

        response_id = str(
            result.get("id") or ""
        )

        print(
            f"[Mistral] Stage: {name} | "
            f"finish_reason: {finish_reason} | "
            f"usage: {usage} | "
            f"response_id: {response_id}",
            flush=True,
        )

        if finish_reason != "stop":

            if finish_reason == "length":
                guidance = (
                    "The output reached a generation limit. "
                    "Consider a larger --max-output-tokens "
                    "value or a simpler extraction stage."
                )

            elif finish_reason == "error":
                guidance = (
                    "Mistral reported a generation error. "
                    "This is not necessarily a token-limit "
                    "problem. Inspect the failing stage and "
                    "its response format."
                )

            else:
                guidance = (
                    "Inspect the model response and "
                    "the failing extraction stage."
                )

            raise ModelOutputError(
                "Mistral stopped without a complete answer: "
                f"{finish_reason}. {guidance}"
            )

        # -----------------------------------------------------
        # 4. Parse returned JSON
        # -----------------------------------------------------

        content = (
            choice.get("message") or {}
        ).get("content")

        if not isinstance(content, str):
            raise ModelOutputError(
                "Mistral returned no textual JSON content"
            )

        try:
            data = json.loads(content)

        except ValueError as exc:
            raise ModelOutputError(
                "Mistral did not return parseable JSON"
            ) from exc

        if not isinstance(data, dict):
            raise ModelOutputError(
                "Mistral JSON response was not an object"
            )

        # -----------------------------------------------------
        # 5. Return result and token accounting
        # -----------------------------------------------------

        return ModelAnswer(
            data=data,
            input_tokens=int(
                usage.get("prompt_tokens") or 0
            ),
            output_tokens=int(
                usage.get("completion_tokens") or 0
            ),
            response_id=response_id,
        )
