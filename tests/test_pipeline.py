from pathlib import Path
import json
import pytest
from jsonschema import Draft202012Validator
from lease_extract.spec import load_document_type
from lease_extract.pdf import read_pdf
from lease_extract.retrieval import select_evidence
from lease_extract.pipeline import execute_pipeline, plan_stages
from lease_extract.cache import Cache
from lease_extract.provider import ModelAnswer, prepare_strict_schema
from lease_extract.validation import canonical_json, validate_result, evidence_warnings, SchemaValidationError

SAMPLES = Path(__file__).resolve().parents[1] / "sample_inputs"
TYPES = SAMPLES / "document_types.json"
FILES = [
 ("Notice: Rent Change", "rent increase 2025-2026 NT2.pdf", 3),
 ("Lease: Residential (AST)", "AST nt 2.pdf", 4),
 ("Lease: Commercial", "2025.08.22 - 4th Fl, RSH - Lease - Signed by Landlord.pdf", 4),
]


def empty_shape(schema):
    if "enum" in schema:
        return schema["enum"][0]
    typ = schema.get("type")
    if typ == "object":
        return {name: empty_shape(sub) for name, sub in schema["properties"].items()}
    if typ == "array": return []
    if typ == "boolean": return False
    if typ in ("number", "integer"): return 0
    if typ == "string": return ""
    raise ValueError(f"Unexpected test schema: {schema}")


class StubProvider:
    """Exercise orchestration and schemas only; NOT factual extraction quality."""
    def __init__(self): self.calls = 0
    def extract(self, **kwargs):
        self.calls += 1
        return ModelAnswer(empty_shape(kwargs["schema"]), 100, 10, f"stub-{self.calls}")


@pytest.mark.parametrize("type_name,pdf_filename,n_stages", FILES)
def test_end_to_end_cache_and_schema(tmp_path, type_name, pdf_filename, n_stages):
    spec = load_document_type(TYPES, type_name)
    pdf = read_pdf(SAMPLES / pdf_filename)
    client = StubProvider()
    cache = Cache(tmp_path / "stage_cache")
    first = execute_pipeline(pdf, spec, client, cache, model_identifier="stub-v1")
    assert client.calls == n_stages
    assert first.manifest["actual_model_calls"] == n_stages
    assert first.manifest["actual_input_tokens_billed"] == 100 * n_stages
    validate_result(first.data, spec.envelope_schema)
    assert list(first.data) == [f.name for f in spec.fields]
    second = execute_pipeline(pdf, spec, client, cache, model_identifier="stub-v1")
    assert client.calls == n_stages  # no more requests
    assert second.manifest["actual_model_calls"] == 0
    assert canonical_json(first.data).encode() == canonical_json(second.data).encode()


@pytest.mark.parametrize("type_name,pdf_filename,n_stages", FILES)
def test_strict_api_schema_keeps_field_semantics(type_name, pdf_filename, n_stages):
    spec = load_document_type(TYPES, type_name)
    for field in spec.fields:
        if not field.is_complex: continue
        strict = prepare_strict_schema(field.schema)
        data = empty_shape(strict)
        validate_result(data, strict)
        validate_result(data, field.schema)
        assert set(strict["required"]) == set(field.schema["required"])


def test_retrieval_budget_determinism_and_page_references():
    pdf = read_pdf(SAMPLES / FILES[2][1])
    a = select_evidence(pdf, "rent", char_budget=25000)
    b = select_evidence(pdf, "rent", char_budget=25000)
    assert a == b
    assert a.characters <= 25000
    assert 1 in a.pages
    assert len(a.pages) < len(pdf.pages)
    assert all(1 <= p <= 70 for p in a.pages)


def test_missing_and_wrong_type_validation():
    spec = load_document_type(TYPES, "Notice: Rent Change")
    with pytest.raises(SchemaValidationError):
        validate_result({"effective_date": "2025-10-01"}, spec.envelope_schema)
    bad = empty_shape(spec.envelope_schema)
    bad["landlord_name"] = ["not a string"]
    with pytest.raises(SchemaValidationError):
        validate_result(bad, spec.envelope_schema)


def test_evidence_cannot_claim_another_page():
    pdf = read_pdf(SAMPLES / FILES[0][1])
    exact = "Rent Review Date: 1st October 2025"
    assert evidence_warnings({"internal_evidence": [{"page": 1, "clause": "", "text": exact}]}, pdf) == []
    assert evidence_warnings({"internal_evidence": [{"page": 2, "clause": "", "text": exact}]}, pdf)
    assert evidence_warnings({"internal_evidence": [{"page": 1, "clause": "", "text": "Fictional clause"}]}, pdf)


def test_notice_case_preserved():
    spec = load_document_type(TYPES, "Notice: Rent Change")
    assert "Consideration" in spec.envelope_schema["properties"]
    assert "consideration" not in spec.envelope_schema["properties"]
    assert "consideration" in spec.envelope_schema["properties"]["Consideration"]["properties"]

@pytest.mark.parametrize("entry", json.loads((SAMPLES.parent / "evaluation" / "retrieval_spot_checks.json").read_text()))
def test_known_fact_evidence_is_retrieved(entry):
    """Measured retrieval recall on a small manually identified anchor set.

    This does not measure LLM extraction precision/recall or correctness of its
    final nested JSON; API experiments are still required for that.
    """
    pdf = read_pdf(SAMPLES / entry["pdf"])
    for category, phrases in entry["checks"].items():
        budget = 12000 if category == "general" else 42000
        source = select_evidence(pdf, category, budget).text.casefold()
        assert all(phrase.casefold() in source for phrase in phrases), (category, phrases)


def test_invalid_model_response_is_retried_then_cached(tmp_path):
    class Flaky(StubProvider):
        def extract(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return ModelAnswer({"made_up_key": "bad"}, 15, 3)
            return ModelAnswer(empty_shape(kwargs["schema"]), 20, 6)

    spec = load_document_type(TYPES, "Notice: Rent Change")
    pdf = read_pdf(SAMPLES / FILES[0][1])
    fake = Flaky()
    res = execute_pipeline(pdf, spec, fake, Cache(tmp_path / "cache"), model_identifier="flaky")
    assert fake.calls == 4  # invalid general response + retry + 2 specialist calls
    assert res.manifest["actual_model_calls"] == 4
    validate_result(res.data, spec.envelope_schema)


def test_altered_pdf_bytes_invalidate_cache(tmp_path):
    src = SAMPLES / FILES[0][1]
    changed = tmp_path / src.name
    changed.write_bytes(src.read_bytes())
    spec = load_document_type(TYPES, "Notice: Rent Change")
    client = StubProvider()
    cache = Cache(tmp_path / "cache")
    a = execute_pipeline(read_pdf(changed), spec, client, cache, model_identifier="stub")
    assert client.calls == 3
    changed.write_bytes(changed.read_bytes() + b"\n% harmless updated PDF trailer comment\n")
    b = execute_pipeline(read_pdf(changed), spec, client, cache, model_identifier="stub")
    assert client.calls == 6  # same text but different source file bytes
    assert a.manifest["pdf_sha256"] != b.manifest["pdf_sha256"]


def test_populated_record_without_evidence_is_flagged():
    pdf = read_pdf(SAMPLES / FILES[0][1])
    record = {"key_dates": [{"date_value": "2025-10-01", "internal_evidence": []}]}
    assert any("no evidence" in w for w in evidence_warnings(record, pdf))
    assert evidence_warnings({"term": {"term_start_date": "", "term_end_date": "", "is_fixed_term": False, "internal_evidence": []}}, pdf) == []
