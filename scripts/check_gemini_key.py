"""Safe, minimal test of a Gemini API key (sends no PDF or lease content)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lease_extract.provider import GeminiProvider


def main() -> int:
    try:
        client = GeminiProvider(max_output_tokens=100, thinking_level="low")
        result = client.extract(
            system="Respond to a simple API connectivity check only.",
            user="Return a JSON object with status equal to OK. No other content.",
            schema={"type": "object", "properties": {"status": {
                "type": "string", "enum": ["OK"]}}, "required": ["status"],
                "additionalProperties": False},
            name="connectivity_check",
        )
        if result.data.get("status") != "OK":
            raise RuntimeError(f"Unexpected response: {result.data}")
        print(f"Gemini key is working. Model: {client.model}. No documents sent.")
        return 0
    except RuntimeError as exc:
        print(f"Key test failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
