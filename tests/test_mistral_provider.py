
"""Mistral HTTP and CLI contract tests; run without a network or an API key."""
import io
import json
from urllib.error import HTTPError

import pytest

from lease_extract.mistral_provider import MistralProvider
from lease_extract.provider import ModelOutputError
from lease_extract.cli import make_parser
from lease_extract.spec import load_document_type
from lease_extract.pdf import read_pdf
from lease_extract.pipeline import plan_stages
from pathlib import Path


class Response(io.BytesIO):
    def __init__(self, obj):
        super().__init__(json.dumps(obj).encode("utf-8"))


SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}


def reply(finish_reason="stop"):
    return {"id": "chat-123", "choices": [{
        "finish_reason": finish_reason,
        "message": {"content": '{"answer":"ok"}'},
    }], "usage": {"prompt_tokens": 120, "completion_tokens": 40}}


def test_mistral_wire_schema_auth_and_usage():
    got = {}

    def opener(request, timeout):
        got["headers"] = request.headers
        got["body"] = json.loads(request.data)
        return Response(reply())

    provider = MistralProvider(key="fake-key", opener=opener)
    answer = provider.extract(system="sys", user="hello", schema=SCHEMA, name="general")
    assert answer.data == {"answer": "ok"}
    assert answer.input_tokens == 120 and answer.output_tokens == 40
    assert answer.response_id == "chat-123"
    assert got["headers"]["Authorization"] == "Bearer fake-key"
    assert got["body"]["model"] == "mistral-small-2603"
    assert got["body"]["temperature"] == 0
    assert got["body"]["random_seed"] == 42
    assert got["body"]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert got["body"]["response_format"]["json_schema"]["strict"] is True


def test_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        MistralProvider()


def test_retries_429_without_leaking_key():
    calls = []
    sleeps = []

    def opener(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError("https://api.mistral.ai", 429, "Too Many Requests", {},
                            io.BytesIO(b'{"message":"Rate limit exceeded"}'))
        return Response(reply())

    result = MistralProvider(key="fake-secret", opener=opener, sleeper=sleeps.append)
    assert result.extract(system="s", user="u", schema=SCHEMA, name="test").data == {"answer": "ok"}
    assert len(calls) == 2 and sleeps == [2]


def test_fails_cleanly_after_429():
    def opener(*_args, **_kwargs):
        raise HTTPError("https://api.mistral.ai", 429, "throttled", {},
                        io.BytesIO(b'{"message":"Rate limit exceeded"}'))

    result = MistralProvider(key="fake-secret", opener=opener, sleeper=lambda *_: None, max_retries=0)
    with pytest.raises(RuntimeError, match="Mistral API HTTP 429") as err:
        result.extract(system="s", user="u", schema=SCHEMA, name="test")
    assert "fake-secret" not in str(err.value)


def test_nonstop_is_an_error():
    provider = MistralProvider(key="fake", opener=lambda *_a, **_k: Response(reply("length")))
    with pytest.raises(ModelOutputError, match="complete answer"):
        provider.extract(system="s", user="u", schema=SCHEMA, name="test")


def test_cli_accepts_provider_and_defaults():
    args = make_parser().parse_args(["--provider", "mistral", "--model", "mistral-small-2603"])
    assert args.provider == "mistral"
    assert args.model == "mistral-small-2603"
    assert make_parser().parse_args([]).provider == "gemini"


@pytest.mark.parametrize("typ,pdf_name", [
    ("Notice: Rent Change", "rent increase 2025-2026 NT2.pdf"),
    ("Lease: Residential (AST)", "AST nt 2.pdf"),
    ("Lease: Commercial", "2025.08.22 - 4th Fl, RSH - Lease - Signed by Landlord.pdf"),
])
def test_all_stage_schemas_convert_to_strict_schema(typ, pdf_name):
    from lease_extract.provider import prepare_strict_schema
    root = Path(__file__).resolve().parents[1] / "sample_inputs"
    pdf = read_pdf(root / pdf_name)
    doc_type = load_document_type(root / "document_types.json", typ)
    for stage in plan_stages(pdf, doc_type):
        structured = prepare_strict_schema(stage.schema)
        assert structured["type"] == "object"
        assert structured["additionalProperties"] is False
