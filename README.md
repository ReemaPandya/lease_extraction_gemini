# Lease Extraction Pipeline — Gemini Free-Tier Edition

A reproducible, cost-aware Python pipeline that extracts lease-document facts into **the exact supplied per-field JSON Schemas**. Tested locally on the three PDFs and three document definitions in `sample_inputs/`.

> **Verification status:** All local tests pass, including mocked Gemini REST requests, schema validation, PDF retrieval, caching, retries, and three complete mocked end-to-end flows. **No live Gemini requests were possible without a user-provided API key.** Mocked JSON is intentionally empty and does **not** establish factual extraction accuracy. The CLI fails clearly without a key rather than fabricating extraction results.

> **Free-tier privacy warning:** Under Google’s unpaid Gemini API terms, submitted content may be used to improve Google products and may be reviewed by humans. Never send confidential leases, tenant data, or other personal information to the free tier. Use appropriately redacted/synthetic PDFs, or use an approved paid/private service. Your selected PDF text excerpts **are** sent to the API during live extraction.

## Get a free API key (recommended model: `gemini-3.8-flash`)

1. Sign in at **https://aistudio.google.com/api-keys**.
2. Accept the terms. Create or choose a Google Cloud project, and select **Create API key** if no default key exists.
3. Copy the secret key. New AI Studio keys are authorization keys; do not use an old unrestricted standard key.
4. **Keep the project on the Free billing tier**. Do not click Upgrade / Set up billing merely to use the free tier. Check your model's live quota and rate limits at **https://aistudio.google.com/rate-limit**.
5. Configure your shell with the key, keeping it **out of source files, screenshots, Git, and chats**.

**Windows PowerShell:**

```powershell
$env:GEMINI_API_KEY="paste-your-real-key-here"
python scripts/check_gemini_key.py
```

**macOS / Linux (bash or zsh):**

```bash
export GEMINI_API_KEY='paste-your-real-key-here'
python scripts/check_gemini_key.py
```

The script makes **one tiny authenticated request** without uploading any PDFs and should print `Gemini key is working`. Environment variables set in a terminal persist only for that terminal session. The script never echoes the key. Checking a key consumes a small amount of free API quota.

Google's free tier is rate- and model-limited. If your account can't access `gemini-3.8-flash`, check the supported models/rate limits in AI Studio; a possible alternative is `gemini-3.5-flash-lite` (confirm model availability in your project before selecting it). The CLI accepts `--model` to choose an accessible free-tier model; it never silently switches models. `gemini-2.5-flash` is legacy and may not be accessible to new projects.

## Install and run

Requires Python 3.10 or higher. Gemini requests use the Python standard library; **no `openai` or Google AI SDK dependency** is required. Run from the unzipped project's root directory.

**macOS / Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
python scripts/check_gemini_key.py

# Keyless request plan; no document content leaves your computer:
lease-extract --type 'Lease: Residential (AST)' \
  --input 'sample_inputs/AST nt 2.pdf' --dry-run

# Live extraction: inspect/redact the sample PDF before using the free API.
lease-extract --type 'Lease: Residential (AST)' \
  --input 'sample_inputs/AST nt 2.pdf' \
  --output 'output/residential.json' --request-delay 5

# Run all three samples if their contents are safe to send:
bash scripts/run_samples.sh --request-delay 5
```

**Windows PowerShell:**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[test]'
pytest -q
python scripts/check_gemini_key.py

lease-extract --type 'Notice: Rent Change' --input 'sample_inputs/rent increase 2025-2026 NT2.pdf' --output 'output/notice.json' --request-delay 5
# Or, to process all three samples:
.\scripts\run_samples.ps1 -RequestDelay 5
```

If PowerShell blocks virtual-environment activation, use `.\.venv\Scripts\python.exe` instead of activating it (e.g. `.\.venv\Scripts\python.exe -m pip install -e ".[test]"`).

The live extraction writes `output/residential.json` and `output/residential.manifest.json` (or the paths chosen with `--output`). The first is validated JSON data; the second logs page selection, cache hits, token usage, validation warnings, and file hashes. For a simple keyless command you can run `lease-extract --list-types`, `lease-extract --dry-run ...` or `pytest -q` without any API key.

**Useful controls:** `--model gemini-3.8-flash` (default), `--thinking-level low|medium|high` (default medium), `--request-delay 5` (seconds between Gemini calls), `--max-output-tokens 14000`, `--refresh` (ignore cache), `--strict-evidence` (fail on unverifiable quotations). Input and output filenames can contain spaces when quoted.

**Troubleshooting:**

- **`GEMINI_API_KEY is missing`**: Set the environment variable in the same terminal in which you run the command. Make sure it is `GEMINI_API_KEY`.
- **HTTP 401/403**: The key is invalid, restricted incorrectly, or lacks access to the project/model. Create a new authorization key in AI Studio. Check your region/project permissions.
- **HTTP 404**: Your chosen model ID isn't accessible; review the currently available free-tier models and use `--model <accessible-model>`.
- **HTTP 429**: You reached an RPM/RPD/token limit. Try `--request-delay 10`, or return after your free quota refreshes. **Do not upgrade to a paid tier unless you want to pay.** The provider retries transient errors twice, then fails clearly.
- **HTTP 400**: Usually a request size/schema/model configuration issue. Try a smaller `--specialty-budget`, or check that the model supports JSON Schema. The full original schema is still validated locally.
- **Output incomplete / MAX_TOKENS**: Try a higher `--max-output-tokens` within your model's limits. Thinking tokens count toward output; larger settings can consume quota faster.
- **Sensitive sample data**: Free tiers are not suitable for confidential tenant information. Remove/redact sensitive personal data _before_ extracting, or use an approved privacy-protecting service instead.

The free tier is **free within quota**, not unlimited, and its request limits may change. See [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [API key guide](https://ai.google.dev/gemini-api/docs/api-key), and [Gemini API terms](https://ai.google.dev/gemini-api/terms).

## Inputs and output shape

The included `document_types.json` is **not** a single output schema. It is an array of document types, each with fields. Five scalar fields have `schema: {}`, and each specialist field supplies a separate JSON schema for the response _inside that field's slot_. We construct and enforce the logical combined schema:

```json
{
  "effective_date": "2025-10-01",
  "property_address": "...",
  "description": "...",
  "landlord_name": "...",
  "tenant_name": "...",
  "Consideration": {
    "consideration": [],
    "rent_model_terms": [],
    "contingent_consideration": []
  },
  "key_dates": {
    "key_dates": [],
    "term": {
      "term_period": "...",
      "term_start_date": "...",
      "term_end_date": "...",
      "is_fixed_term": false,
      "internal_source": "...",
      "internal_evidence": []
    }
  }
}
```

**This JSON fragment illustrates the envelope only; it is not a real extraction result.** The notice uses capitalized `Consideration` in the _outer_ field name while its inner schema uses lowercase `consideration`; the implementation preserves this distinction. Lease document types additionally have a `consideration_review` slot. To print the _complete_ combined schema, use:

```bash
lease-extract --type 'Notice: Rent Change' --emit-schema > output_schema.json
```

General (schema-less) fields are strings because the supplied definitions have `item_type: string`. Specialist values are stored as the exact objects required by their supplied JSON schemas, not flattened into root fields. No required field is discarded or renamed. Missing values use only schema-permitted representations. The pipeline never silently repairs malformed output by substituting empty arrays/strings.

## Architecture

```text
PDF bytes + document_types.json
    |
    +-- SHA-256 of the actual source PDF (cache invalidation)
    |
    +-- PyMuPDF extract each page's searchable text once (1-based page ids)
    |
    +-- Deterministic source selection: small PDFs full; large PDFs chunked,
    |   lexical/BM25 retrieval, curated lease-domain anchors, fixed character budgets
    |
    +-- Planning: ONE grouped request for all simple fields
    |             ONE request per independent complex schema
    |       (commercial/AST: 4 requests; rent-change notice: 3)
    |
    +-- Gemini 3.8 Flash via REST, responseJsonSchema structured outputs
    |       - complete field-specific extraction description is retained
    |       - document text explicitly treated as untrusted data
    |       - no page images or repeated full-document image transmission
    |
    +-- jsonschema validation (original, authoritative source schema)
    |       + optional strict verbatim evidence verification by cited PDF page
    |       + max 1 corrective regeneration if invalid; otherwise fail loudly
    |
    +-- content-addressed, atomic, independently validated per-stage cache
    |
    +-- validated document envelope, stable canonical JSON + audit manifest
```

**Why not put every specialist schema in one response?** The real prompts are very large (~6k–87k _characters per field_). Their domain rules and nested schemas differ markedly; merging them risks context overload, smaller output headroom, competing instructions, and harder validation. Batching the five simple fields but isolating the intricate `consideration`, `consideration_review`, and `key_dates` schemas is a pragmatic accuracy/cost tradeoff.

**Why not summarize the field descriptions?** The supplied descriptions impose domain-specific gate rules, exclusions, and evidence requirements. Dropping them could change the meaning of the task. Instead, the full descriptions are retained, while only the **source document** is selectively retrieved for the long lease. We keep the original schema for validation and pass a strict-output-compatible copy to the provider (the supplied schemas are already fully required and closed). No model call is needed to read pages or retrieve text.

**Text and page provenance:** Digital PDF text is read locally. Page markers refer to _physical, 1-based PDF pages_, not printed page numbers. Each chunk retains a source offset. For single-page and shorter documents, selection sends all extractable text: the 1-page notice and all 9 pages of the AST are fully supplied to their specialist calls. The 70-page commercial lease uses keyword-ranked chunks, includes the first page, and reports its per-stage selected pages. Blank or image-only PDFs fail loudly rather than inventing OCR output. Production OCR is an explicit future extension.

## Cost rationale and measured dry-run proxies

Run `--dry-run` to see the exact planned selection/character counts locally. On the supplied documents with default budgets:

| Input              | Pages | Current baseline calls | Proposed first-pass calls | Baseline sent page-images | Proposed sent page-images |
| ------------------ | ----: | ---------------------: | ------------------------: | ------------------------: | ------------------------: |
| Rent-change notice |     1 |                      7 |                     **3** |                         7 |                     **0** |
| Residential AST    |     9 |                      8 |                     **4** |                        72 |                     **0** |
| Commercial lease   |    70 |                      8 |                     **4** |                       560 |                     **0** |

The baseline transmits all page images for **every** field. Our pipeline never transmits PDF images. The savings are in avoided image encoding/tokens, eliminating duplicate full-document visual context, grouping general fields, and bounded source retrieval for long documents. Cache hits require **zero model calls**. The `--dry-run` output uses `characters / 4` only as an **explicitly approximate** input-token proxy, including descriptions and source text. It is not a measured token bill. The number of calls above excludes validation retries, and neither image-token pricing nor a real baseline run has been measured; therefore **we do not claim a dollar or percentage savings**.

For example, the commercial lease's local text is approximately 135k characters. Each complex-field request selects no more than 42k characters of source evidence by default. That bound does not apply to the (unchanged) specialist extraction description or its response schema. `--specialty-budget 140000` retains the full document for higher-recall experiments, at higher token cost.

## Consistency and validation

1. **Repeatability of source processing:** sorted, deterministic lexical retrieval; stable tie-breaking; source page numbers; stable prompt construction. Modern Gemini sampling/"thinking" can vary between calls; caching provides exact repeated bytes on identical inputs.
2. **Stable outputs on identical inputs:** content-addressed cache includes the full PDF SHA-256, source excerpts, complete prompts, model settings identifier, stage schema, strict-evidence option, and pipeline version. A cache hit does not invoke the provider. Cache writes are atomic, and cached data is validated again on use. `--refresh` bypasses cache for a genuine repeat measurement.
3. **Output contracts:** Gemini JSON Schema at generation and `jsonschema` validation against **the supplied source schema** afterward. Validation errors lead to bounded corrective retry (one) rather than silent filling. Final output validates against the constructed envelope schema. Failures do not generate fake partial results.
4. **Evidence checking:** `internal_evidence` source `page` and literal `text` are checked against locally extracted page text. By default, mismatches appear in the manifest as warnings (the PDF's line layout can cause legitimate excerpts to mismatch). `--strict-evidence` retries and then rejects unverified quotations.
5. **Deterministic serialization:** JSON properties have sorted keys and stable UTF-8 indentation. All outputs can be compared by SHA-256.

To assess **true LLM-run stability, independent of caching**, run the included live-API harness (consumes API quota; could be charged if you enable billing):

```bash
python scripts/measure_consistency.py \
  --input 'sample_inputs/AST nt 2.pdf' \
  --type 'Lease: Residential (AST)' \
  --runs 3 --output-dir 'output/ast_consistency'
```

It uses **no cache**, writes individual JSON and manifests, and reports exact-document match, field-level match fraction, and actual tokens. For large nested outputs, increase the output cap if Gemini returns `MAX_TOKENS`, for example:

```bash
python scripts/measure_consistency.py \
  --input 'sample_inputs/2025.08.22 - 4th Fl, RSH - Lease - Signed by Landlord.pdf' \
  --type 'Lease: Commercial' \
  --runs 3 --max-output-tokens 24000 --thinking-level low --request-delay 15 \
  --output-dir 'output/commercial_consistency'
```

The measurement script records the model, output-token cap, thinking level, and request delay in its summary. Use `--request-delay` to stay below the project's requests-per-minute quota; 15 seconds leaves a conservative margin for a 5 RPM limit. Increasing the cap can increase quota use; lower thinking leaves more of the output budget for the structured response. For benchmarking accuracy, hand-label the relevant values _and literal sources_ per PDF, then compare field-level exact matches and numeric/date normalization, measure false positives, and review any page-evidence warning. For a cost baseline, measure input/output tokens and billed image input from a faithful implementation of the previous per-key image approach using the same model and documents.

## Tests and evidence coverage

```bash
pytest -q
```

24 local tests cover: three end-to-end sample document/schema combinations with a stubbed provider, schema fidelity for all specialist field types, the notice's case-sensitive slot, duplicate/missing/wrong-type detection, retrieval determinism and budget, source page verification, automatic validation retries, source-byte cache invalidation, and 26 manually selected phrases present in the expected retrieved evidence for all three PDFs.

This **26/26 coverage is only a small retrieval sanity check**, not extraction-level precision/recall or verification of the model output. The fake model returns valid empty values purely to exercise orchestration. It makes no claims about lease interpretation. Real quality measurement requires an API key and reviewed ground truth. Input PDFs and the document definitions are included for reproducibility.

## Operational choices and tradeoffs

- **Model:** `gemini-3.8-flash` is the default; change with `--model` to another accessible free-tier Gemini model. The project uses the Gemini `generateContent` REST endpoint with `responseJsonSchema` and local JSON Schema validation. New Gemini models deprecate arbitrary sampling-temperature adjustments, so the client does not send `temperature`. See [Google structured outputs](https://ai.google.dev/gemini-api/docs/structured-output) and [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash/).
- **Recall vs cost:** Chunk selection is transparent, simple, and reproducible, but cannot guarantee all relevant clauses of a complex 70-page lease are chosen. Use a larger `--specialty-budget` or a two-pass high-recall section discovery + extraction on long documents. The default budget is a _cost/recall hypothesis_, not an empirically optimal threshold.
- **No unrequested OCR:** The supplied PDFs are text-searchable. For scanned pages, a production version would extract images selectively and OCR only unreadable pages, with confidence checks and the original PDF coordinates preserved. This is a deliberate gap, not an invisible fallback.
- **No silent semantic modifications:** JSON schema guarantees shape and enum legality, not correctness of `payment_amount`, parties, dates, or clause interpretation. Numeric reconciliation and date comparison against cited evidence are valuable additional domain checks.
- **External service failure:** The standard-library REST client retries transient HTTP 429/5xx/network failures with bounded exponential backoff; schema validation can retry once; rejected or truncated outputs cause explicit errors. Atomic cache writes prevent half-written cached stages. Per-stage cache survives failures in later stages.
- **Privacy/security:** No input PDF is sent as a binary file; selected plaintext excerpts are sent to the configured model API. Do not process sensitive tenant information without suitable consent, contractual terms, retention controls, and secure cache storage. The `.gitignore` excludes output, cache, and `.env`, but production needs encryption, redaction and access controls. **The free Gemini tier explicitly permits data use for improving Google products; do not submit sensitive or confidential information.** Source PDFs are for test/demo and should be managed appropriately.
- **Auditability:** The manifest exposes which PDF pages were presented to the model; it does not assert that unselected pages were irrelevant or that output is legally authoritative.

## Next improvements with more time / a live API key

1. Create a manually reviewed **ground-truth set**, including multi-clause commercial consideration and rent-review rules, with adjudicated evidence pages and difficult negative cases (service charges, deposits, inferred dates).
2. Run full, 42k, and intermediate retrieval budgets, score recall/precision and wall-clock/billed token cost, and pick thresholds based on measured error rather than intuition.
3. Split long specialty extraction by _discovered clause families_ using an evidence inventory and deduplicated reducer where the model's output limits are a bottleneck, instead of increasing context indefinitely.
4. Implement selective OCR of pages with very little text, and hybrid semantic/BM25 retrieval with regression tests.
5. Add domain validators (ISO dates, money reconciliation, source-to-output consistency), human-review flags for unresolved conflicts, and encryption/deletion policies for cached excerpts and PII.

## Files

```text
src/lease_extract/
    cli.py          CLI, dry-run, output schema and validation commands
    spec.py         Real-world document-type loading + envelope construction
    pdf.py          Local PDF parsing with physical PDF page IDs
    retrieval.py    Deterministic ranked, bounded high-recall evidence selection
    pipeline.py     Grouping, prompting, validation, cache orchestration, manifest
    provider.py     Free-tier Gemini REST client, JSON Schema conversion, retries, usage capture
    validation.py   Schema + page-evidence checks, canonical JSON
    cache.py        SHA-256 keyed atomic cache
scripts/
    run_samples.sh          Full sample batch invocation (bash)
    run_samples.ps1         Full sample batch invocation (PowerShell)
    check_gemini_key.py     Minimal API-key smoke test (sends no PDF)
    measure_consistency.py  Billed, genuinely uncached repeated-run test
sample_inputs/             Exact source PDFs and document_types.json
evaluation/                Hand-picked source evidence recall checkpoints
tests/                     Offline pytest suite; fake provider clearly scoped
```
