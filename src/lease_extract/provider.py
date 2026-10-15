"""Gemini Developer API provider: free-tier compatible, no Google SDK required.

The Gemini API free tier is quota-limited and the provider never switches to a
paid model/tier. Confirm that your Google AI Studio project is on the Free tier.
"""
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote
import json
import os
import time

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/"
DEFAULT_MODEL = "gemini-3.8-flash"


@dataclass(frozen=True)
class ModelAnswer:
    data: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    response_id: str = ""


class JSONProvider(Protocol):
    def extract(self, *, system: str, user: str, schema: dict[str, Any],
                name: str) -> ModelAnswer: ...


class ModelOutputError(RuntimeError):
    pass


class GeminiProvider:
    """Gemini generateContent API with structured JSON and bounded retries.

    Google AI Studio key: https://aistudio.google.com/api-keys
    This REST client uses Python's standard library. It never uploads PDF files
    or page images; the orchestration layer sends selected plaintext excerpts.
    An injectable opener/sleeper makes HTTP handling testable offline.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_output_tokens: int = 14000,
        *,
        key: str | None = None,
        timeout: float = 180.0,
        max_retries: int = 2,
        request_delay: float = 0.0,
        thinking_level: str = "medium",
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ):
        self.key = key or os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise RuntimeError(
                "GEMINI_API_KEY is missing. Create a Free-tier key at "
                "https://aistudio.google.com/api-keys, then set the environment "
                "variable; or run --dry-run without a key."
            )
        if not model or "/" in model or "?" in model:
            raise ValueError("Invalid Gemini model name")
        if max_output_tokens < 1 or max_retries < 0 or request_delay < 0:
            raise ValueError("max_output_tokens must be positive, and retries/delay nonnegative")
        if thinking_level not in ("low", "medium", "high"):
            raise ValueError("thinking_level must be low, medium, or high")
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.request_delay = request_delay
        self.thinking_level = thinking_level
        self.opener = opener or urlopen
        self.sleeper = sleeper or time.sleep
        self._has_sent_request = False

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{GEMINI_ENDPOINT}{quote(self.model, safe='-_.')}:generateContent"
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": self.key},
        )
        for attempt in range(self.max_retries + 1):
            if self._has_sent_request and self.request_delay:
                self.sleeper(self.request_delay)
            self._has_sent_request = True
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                # Never print request headers, which contain the secret key.
                msg = exc.reason or "API request rejected"
                try:
                    error_data = json.loads(exc.read().decode("utf-8"))
                    msg = error_data.get("error", {}).get("message", msg)
                except (ValueError, UnicodeDecodeError, AttributeError):
                    pass
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    # Google imposes both minute and daily free-tier limits;
                    # do not assume a daily exhausted quota can be retried away.
                    self.sleeper(min(2 ** (attempt + 1), 16))
                    continue
                guidance = (
                    " Check quota/model access at https://aistudio.google.com/rate-limit "
                    "and ensure the project is on the Free tier."
                    if exc.code in (403, 404, 429) else ""
                )
                raise RuntimeError(
                    f"Gemini API returned HTTP {exc.code}: {msg}.{guidance}"
                ) from exc
            except URLError as exc:
                if attempt < self.max_retries:
                    self.sleeper(min(2 ** (attempt + 1), 16))
                    continue
                raise RuntimeError(f"Network error calling Gemini API: {exc.reason}") from exc
            except (ValueError, UnicodeDecodeError) as exc:
                raise ModelOutputError("Gemini returned an invalid HTTP JSON response") from exc
        raise AssertionError("Unreachable")

    def extract(self, *, system: str, user: str, schema: dict[str, Any],
                name: str) -> ModelAnswer:
        # Gemini accepts standard JSON Schema via responseJsonSchema, rather
        # than OpenAI's response_format JSON schema wrapper.
        response = self._post({
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": prepare_strict_schema(schema),
                "maxOutputTokens": self.max_output_tokens,
                "thinkingConfig": {"thinkingLevel": self.thinking_level},
            },
        })
        candidates = response.get("candidates") or []
        if not candidates:
            feedback = response.get("promptFeedback", {})
            raise ModelOutputError(f"Gemini returned no candidates: {feedback}")
        candidate = candidates[0]
        finish_reason = str(candidate.get("finishReason", "STOP"))
        if finish_reason != "STOP":
            raise ModelOutputError(f"Gemini stopped without a complete answer: {finish_reason}")
        pieces = candidate.get("content", {}).get("parts", [])
        result_text = "".join(p.get("text", "") for p in pieces if isinstance(p, dict))
        try:
            result_data = json.loads(result_text)
        except (ValueError, TypeError) as exc:
            raise ModelOutputError("Gemini did not return parseable structured JSON") from exc
        if not isinstance(result_data, dict):
            raise ModelOutputError("Gemini JSON output was not an object")
        usage = response.get("usageMetadata") or {}
        return ModelAnswer(
            data=result_data,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            # Google's thoughtsTokenCount is separate from candidatesTokenCount.
            # Keep track of generated tokens including reasoning for reporting.
            output_tokens=int(usage.get("candidatesTokenCount", 0))
                          + int(usage.get("thoughtsTokenCount", 0)),
            response_id=str(response.get("responseId", "")),
        )


def prepare_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Retain the supplied task's semantic constraints for Gemini JSON schema.

    The original field-level schemas are closed and fully required. The local
    pipeline separately validates against each unmodified source schema.
    """
    supported = {
        "type", "properties", "required", "additionalProperties", "items",
        "enum", "anyOf", "oneOf", "$defs", "$ref", "description", "title",
        "format", "minimum", "maximum", "minItems", "maxItems",
    }

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        out = {
            k: ({field: walk(sub) for field, sub in value.items()}
                if k in ("properties", "$defs") and isinstance(value, dict)
                else walk(value))
            for k, value in node.items() if k in supported
        }
        if out.get("type") == "object":
            if set(out.get("required", [])) != set(out.get("properties", {})):
                raise ValueError(
                    "Source schema has optional object properties; explicit nullable normalization needed"
                )
            out["additionalProperties"] = False
        return out

    return walk(schema)
