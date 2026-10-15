"""Offline REST contract tests: no network access, key or payment required."""
import io
import json
from urllib.error import HTTPError
import pytest
from lease_extract.provider import GeminiProvider, ModelOutputError, DEFAULT_MODEL
from lease_extract.pipeline import execute_pipeline
from lease_extract.pdf import read_pdf
from lease_extract.spec import load_document_type
from lease_extract.cache import Cache
from lease_extract.validation import validate_result


def empty_shape(schema):
    if 'enum' in schema:
        return schema['enum'][0]
    kind = schema.get('type')
    if kind == 'object':
        return {k: empty_shape(v) for k, v in schema['properties'].items()}
    if kind == 'array':
        return []
    if kind == 'boolean':
        return False
    if kind in ('number', 'integer'):
        return 0
    if kind == 'string':
        return ''
    raise AssertionError(f'Unexpected schema: {schema}')


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode('utf-8'))


def answer(data=None, *, finish='STOP'):
    return {
        'candidates': [{
            'content': {'parts': [{'text': json.dumps(data if data is not None else {'ok': 'yes'})}]},
            'finishReason': finish,
        }],
        'responseId': 'some-response',
        'usageMetadata': {'promptTokenCount': 43, 'candidatesTokenCount': 12, 'thoughtsTokenCount': 5},
    }


SCHEMA = {
    'type': 'object',
    'properties': {'ok': {'type': 'string'}},
    'required': ['ok'],
    'additionalProperties': False,
}


def test_request_contract_is_gemini_and_no_pdfs_or_other_data():
    seen = []

    def capture(req, timeout):
        seen.append((req, timeout))
        return Response(answer())

    provider = GeminiProvider(key='synthetic-test-key', opener=capture, thinking_level='low')
    result = provider.extract(system='system', user='source excerpts', schema=SCHEMA, name='test')
    assert provider.model == DEFAULT_MODEL == 'gemini-3.8-flash'
    req, timeout = seen[0]
    assert req.full_url == 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent'
    assert req.get_header('X-goog-api-key') == 'synthetic-test-key'
    assert req.get_method() == 'POST'
    data = json.loads(req.data)
    assert data['contents'][0]['parts'][0]['text'] == 'source excerpts'
    assert data['systemInstruction']['parts'][0]['text'] == 'system'
    assert data['generationConfig']['responseMimeType'] == 'application/json'
    assert data['generationConfig']['responseJsonSchema'] == SCHEMA
    assert data['generationConfig']['thinkingConfig'] == {'thinkingLevel': 'low'}
    assert 'temperature' not in data['generationConfig']
    assert result.data == {'ok': 'yes'}
    assert (result.input_tokens, result.output_tokens, result.response_id) == (43, 17, 'some-response')


def test_environment_key_and_missing_key(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='GEMINI_API_KEY is missing'):
        GeminiProvider()
    monkeypatch.setenv('GEMINI_API_KEY', 'mock-env-key')
    assert GeminiProvider(opener=lambda *a, **kw: None).key == 'mock-env-key'


def test_http_429_retries_then_succeeds_without_exposing_key():
    calls = []
    sleeps = []

    def flaky(req, timeout):
        calls.append(req)
        if len(calls) == 1:
            raise HTTPError(req.full_url, 429, 'too many requests', {}, Response({'error': {'message': 'quota reached'}}))
        return Response(answer())

    provider = GeminiProvider(key='never-show-this', opener=flaky, sleeper=sleeps.append,
                              max_retries=1, request_delay=0)
    provider.extract(system='s', user='u', schema=SCHEMA, name='test')
    assert len(calls) == 2
    assert sleeps == [2]


def test_429_quota_failure_is_actionable_and_hides_secret():
    def limited(req, timeout):
        raise HTTPError(req.full_url, 429, 'quota exceeded', {}, Response({'error': {'message': 'Rate limit'}}))

    provider = GeminiProvider(key='SECRET', opener=limited, sleeper=lambda s: None, max_retries=0)
    with pytest.raises(RuntimeError) as exc:
        provider.extract(system='s', user='u', schema=SCHEMA, name='test')
    assert '429' in str(exc.value) and 'rate-limit' in str(exc.value)
    assert 'SECRET' not in str(exc.value)


def test_finish_reason_max_tokens_fails_not_fake_json():
    provider = GeminiProvider(key='test', opener=lambda *_a, **_kw: Response(answer(finish='MAX_TOKENS')))
    with pytest.raises(ModelOutputError, match='MAX_TOKENS'):
        provider.extract(system='s', user='u', schema=SCHEMA, name='test')


@pytest.mark.parametrize('document_type,pdf_filename,stages', [
    ('Lease: Commercial', '2025.08.22 - 4th Fl, RSH - Lease - Signed by Landlord.pdf', 4),
    ('Lease: Residential (AST)', 'AST nt 2.pdf', 4),
    ('Notice: Rent Change', 'rent increase 2025-2026 NT2.pdf', 3),
])
def test_all_sample_documents_run_through_mocked_gemini_http(tmp_path, document_type, pdf_filename, stages):
    samples = tmp_path.parents[0]  # all outputs isolated in temp directory
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / 'sample_inputs'
    spec = load_document_type(root / 'document_types.json', document_type)
    pdf = read_pdf(root / pdf_filename)
    calls = []

    def fake_api(req, timeout):
        body = json.loads(req.data)
        schema = body['generationConfig']['responseJsonSchema']
        calls.append(body)
        return Response(answer(empty_shape(schema)))

    provider = GeminiProvider(key='mock-test-only', opener=fake_api)
    cache = Cache(tmp_path / 'cache')
    first = execute_pipeline(pdf, spec, provider, cache, model_identifier='gemini-test')
    validate_result(first.data, spec.envelope_schema)
    assert len(calls) == stages
    assert first.manifest['actual_model_calls'] == stages
    second = execute_pipeline(pdf, spec, provider, cache, model_identifier='gemini-test')
    assert second.data == first.data
    assert len(calls) == stages
    assert second.manifest['actual_model_calls'] == 0
