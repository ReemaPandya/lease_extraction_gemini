# Lease Extraction Pipeline

A local-first, schema-driven Python pipeline for extracting structured facts from property PDFs. It is designed to reduce repeated LLM calls and document transmission while retaining the original field definitions, evidence provenance, validation, and a reproducible audit trail.

**Repository:** [ReemaPandya/lease_extraction_gemini](https://github.com/ReemaPandya/lease_extraction_gemini)  
**Python:** 3.10+  
**Document types:** `Notice: Rent Change`, `Lease: Residential (AST)`, `Lease: Commercial`

> **Branch guide:** `main` contains the original **Gemini-only** implementation. The Mistral provider and the `--provider` CLI option are developed on **[`feature/mistral-integration`](https://github.com/ReemaPandya/lease_extraction_gemini/tree/feature/mistral-integration)**. To run Mistral, check out that branch first. The successful JSON-mode workaround and rent-condition prompt refinement were tested locally; ensure those latest local changes have been committed and pushed to the feature branch before expecting a fresh clone to reproduce that result.
>
> **Verification scope:** Live end-to-end extraction and a three-run consistency experiment were completed for the **one-page rent-change notice** with `ministral-8b-2512`. Larger lease documents have been exercised by local planning/mocked tests, but comparable live accuracy tests are still outstanding.

## Project status at a glance

| Area | Accomplished | Remaining / not yet verified |
| --- | --- | --- |
| PDF processing | Local searchable-PDF text extraction with 1-based page IDs | Selective OCR for scanned/image-only pages |
| Extraction | Grouped simple fields, separate specialist stages, bounded evidence retrieval | Full live runs and factual review for 9-page AST and 70-page commercial lease |
| Output quality | Supplied JSON Schemas preserved; local validation; page-evidence checks | Human-reviewed ground truth, field-level precision/recall, stronger semantic checks |
| Cost controls | Fewer planned API calls, no PDF image upload, prompt-aware stage cache | Measured cost/latency comparisons against the original image-based baseline |
| Providers | Gemini on `main`; Gemini + Mistral on the feature branch | Cross-provider benchmarking on identical configurations and all document types |
| Testing | Offline tests, keyless dry-run, successful live notice extraction, three uncached Mistral runs | Clean-environment verification and broader error/consistency testing |

### Why Mistral was added

The project began with the Gemini Developer API, and Gemini successfully extracted the rent notice. During iterative testing, however, the tested Gemini project/model reached a **20-request-per-day quota**, while attempts on the commercial lease also encountered a `MAX_TOKENS` response. HTTP 429 quota errors prevented further tests that day.

Mistral was added **to continue development within the available free-tier limits**, **not** because it had been proven more accurate. The tested Mistral account showed a monthly included API allowance and higher token-throughput limits for `ministral-8b-2512` than for the initially attempted Mistral Small model. Mistral also encountered rate limits and strict-schema generation errors; a targeted JSON-mode workaround was used for the Ministral key-dates stage. **Both providers remain available on the feature branch.** Quotas and allowances depend on the provider, model, and account and can change.

## Quick start: clone and install

Clone the repository and enter its root:

```powershell
# Windows PowerShell
git clone https://github.com/ReemaPandya/lease_extraction_gemini.git
cd lease_extraction_gemini

py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

Or on macOS/Linux:

```bash
git clone https://github.com/ReemaPandya/lease_extraction_gemini.git
cd lease_extraction_gemini
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
python -m pytest -q
```

The runtime needs **PyMuPDF** and **jsonschema** (installed from `pyproject.toml`); **pytest** is installed by the `[test]` extra. **Gemini and Mistral are hosted API models, not models downloaded or installed locally.** The production provider adapters use Python's **standard-library HTTP client**; neither provider requires the vendor SDK for pipeline execution.

### Required input files

`sample_inputs/document_types.json` is tracked in Git. The original PDFs are **not tracked** (`*.pdf` is ignored to avoid publishing potentially sensitive legal documents). To run the supplied examples, obtain the PDFs from the assignment package and place them locally at these paths:

```text
sample_inputs/
  document_types.json
  rent increase 2025-2026 NT2.pdf
  AST nt 2.pdf
  2025.08.22 - 4th Fl, RSH - Lease - Signed by Landlord.pdf
```

You may instead supply any local **searchable** PDF with `--input`, paired with an appropriate type in the JSON definitions. Do **not** commit confidential PDFs or API credentials. The live API receives selected **plaintext excerpts** from the PDFs; it does not receive the PDF binary or rendered images.

## Run with Gemini (`main` or feature branch)

1. Create an API key at [Google AI Studio](https://aistudio.google.com/api-keys).
2. Check model availability and your actual free-tier limits at [AI Studio rate limits](https://aistudio.google.com/rate-limit). The repository's configured default is `gemini-3.8-flash`; model access is account-dependent.
3. Set the key **in your current terminal session** (never in a committed file):

```powershell
$env:GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"
```

4. Check the connection (one small API call, **no document uploaded**):

```powershell
.\.venv\Scripts\python.exe scripts\check_gemini_key.py
```

5. Run an extraction:

```powershell
# Works on the default main branch; --provider is NOT supported on main.
.\.venv\Scripts\python.exe -m lease_extract `
  --model gemini-3.8-flash `
  --type "Notice: Rent Change" `
  --input "sample_inputs\rent increase 2025-2026 NT2.pdf" `
  --output "output\notice_gemini.json" `
  --thinking-level low `
  --request-delay 5
```

On `feature/mistral-integration`, the same command works; you can also include `--provider gemini`. If you do not set `--provider` on that branch, Gemini remains the default.

**macOS/Linux:** Set `export GEMINI_API_KEY='YOUR_GEMINI_API_KEY'`, and use the equivalent command with `/` paths and `\` shell line continuations rather than PowerShell backticks.

## Run with Mistral (`feature/mistral-integration` only)

**Important:** The `main` branch does **not** recognize `--provider mistral`. Switch to the Mistral branch first:

```powershell
git fetch origin
git switch feature/mistral-integration
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

1. Create an API key in [Mistral Studio](https://console.mistral.ai/).
2. Inspect your organization-specific usage and model limits in [Mistral Admin](https://admin.mistral.ai/).
3. Set the key in the current PowerShell session:

```powershell
$env:MISTRAL_API_KEY = "YOUR_MISTRAL_API_KEY"
```

4. Run the **successfully tested Ministral 8B model**:

```powershell
.\.venv\Scripts\python.exe -m lease_extract `
  --provider mistral `
  --model ministral-8b-2512 `
  --type "Notice: Rent Change" `
  --input "sample_inputs\rent increase 2025-2026 NT2.pdf" `
  --output "output\notice_ministral.json" `
  --max-output-tokens 4000 `
  --request-delay 10
```

`mistral-small-2603` is the Mistral adapter's configured default, but attempts with that model hit HTTP 429 limits in the tested account. Therefore the live evaluation reported here used **`ministral-8b-2512` explicitly**. This does **not** imply that Ministral 8B is more accurate than Mistral Small.

For a fresh end-to-end run without response-cache reuse, add `--no-cache` and write to a separate output path. The tested Ministral version uses **strict JSON Schema mode** for `general` and `Consideration`, and **JSON mode** for `key_dates` because that stage previously returned `finish_reason="error"` under constrained generation. The original JSON Schema is still validated locally. **Ensure the latest tested version of `src/lease_extract/mistral_provider.py` has been pushed**; an older feature-branch revision may still use strict mode for every stage.

### Optional Mistral SDK connection smoke test

The separate `test_mistral.py` on the feature branch uses the *vendor SDK* and therefore needs an additional, **optional** install. It is **not** required by the production pipeline:

```powershell
.\.venv\Scripts\python.exe -m pip install mistralai
.\.venv\Scripts\python.exe test_mistral.py
```

The smoke-test model is set inside `test_mistral.py` and can differ from `--model` passed to the extraction CLI. Never commit or print the API key.

## Keyless commands, validation, and outputs

The following operations do **not** contact either provider:

```powershell
# List configured document types
.\.venv\Scripts\python.exe -m lease_extract --list-types

# Inspect planned calls, selected pages, and approximate input size
.\.venv\Scripts\python.exe -m lease_extract `
  --type "Notice: Rent Change" `
  --input "sample_inputs\rent increase 2025-2026 NT2.pdf" `
  --dry-run

# Check a previously produced JSON file against the supplied schema
.\.venv\Scripts\python.exe -m lease_extract `
  --type "Notice: Rent Change" `
  --validate "output\notice_ministral.json"

# Print the combined output schema
.\.venv\Scripts\python.exe -m lease_extract `
  --type "Notice: Rent Change" --emit-schema
```

A successful extraction creates two files:

- `output/<name>.json`: complete assembled extraction, validated against the supplied JSON Schema.
- `output/<name>.manifest.json`: source hash, selected pages, per-stage cache hits, call counts, reported token usage, and evidence warnings.

The supplied `document_types.json` is an **array of document-type definitions**, not one global JSON Schema. Each specialist field supplies its own nested schema; the pipeline assembles these into a single output envelope without renaming fields. For the notice, the outer name **`Consideration` is case-sensitive** and contains the lowercase `consideration`, `rent_model_terms`, and `contingent_consideration` arrays. The outer `key_dates` object contains `key_dates` records plus a `term` object. Simple fields are assembled as strings. Missing information must use schema-permitted representations; the pipeline should not invent facts.

## Pipeline design

```text
Input: searchable PDF + document_types.json + selected document type
  |
  +-- SHA-256 of original PDF bytes
  |
  +-- Local PyMuPDF text extraction with physical 1-based page numbers
  |
  +-- Deterministic evidence retrieval and bounded source chunks
  |
  +-- Extraction plan
  |     +-- One grouped request for simple fields
  |     +-- One request per complex field/schema
  |
  +-- Provider adapter: Gemini (main) or Gemini/Mistral (feature branch)
  |     +-- Structured JSON output request
  |     +-- Selected plaintext evidence, not full PDF page images
  |
  +-- Validate against original JSON Schema
  |     +-- Optional strict page-level evidence verification
  |     +-- Bounded correction retry for locally invalid JSON
  |
  +-- Content-addressed, stage-level result cache
  |
  +-- Final validated JSON + per-stage audit manifest
```

**Why group only simple fields?** The supplied specialist descriptions and schemas are long and enforce distinct legal-data rules. Combining all complex fields into one model response could increase output pressure, reduce reliability, and make failures harder to isolate. The pipeline batches inexpensive string fields but processes intricate consideration, review, and key-date schemas separately.

**What retrieval does:** For short documents it can send all extracted text; for larger ones it selects ranked excerpts using deterministic lexical matching, domain anchors, and character budgets. The field-specific descriptions are retained rather than silently summarized. For the 70-page commercial lease, retrieval is a cost/recall tradeoff and may miss relevant clauses; it is not guaranteed to be exhaustive. The dry-run estimates prompt tokens by character count and does not measure actual API billing.

**Caching:** Each stage's cache key depends on the source PDF hash, prompt, schema, provider/model settings identifier, and pipeline version. A valid cache hit makes zero model calls; cached records are revalidated. After the notice `Consideration` prompt was refined locally, the measured run reused `general` and `key_dates` and invoked only `Consideration` once.

**Evidence:** Model-provided quotations are checked against the cited physical PDF page. By default, mismatches are recorded as warnings; `--strict-evidence` makes them validation failures. Zero evidence warnings **does not prove** that every legal interpretation is correct.

## Cost and call-count rationale

The baseline described in the task renders pages to images and makes **one model request per field**, retransmitting all pages each time. The proposed first-pass call counts below come from local planning and **exclude retries**:

| Document | Pages | Fields / baseline calls | Optimized planned calls | Baseline page-image transmissions | Pipeline page-image transmissions |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rent-change notice | 1 | 7 | **3** | 7 | **0** |
| Residential AST | 9 | 8 | **4** | 72 | **0** |
| Commercial lease | 70 | 8 | **4** | 560 | **0** |

The notice call reduction is **4/7, approximately 57%**. The residential/commercial numbers are plans, **not completed live comparisons**. Avoided image transmissions and call reductions indicate reduced overhead, but **dollar savings have not been measured against a faithful image-based baseline**.

## Actual experiments and consistency

### Live Ministral 8B: one-page rent notice

One successful full extraction was run with `--no-cache`:

| Metric | Observed |
| --- | ---: |
| PDF pages | 1 |
| Document fields | 7 |
| Model calls | 3 |
| Input tokens | 5,135 |
| Output tokens | 858 |
| Total reported tokens | 5,993 |
| Evidence warnings | 0 |

The extracted notice described monthly rent changing **from £2,300 to £2,415 effective 1 October 2025**. Local review identified that a 5% annual-adjustment rationale is **not a condition precedent**; the notice-specific `Consideration` prompt was refined so `condition` remains empty unless the source expressly states a prerequisite. The original field schema was **not** modified.

### Three uncached Ministral 8B runs

```powershell
# Feature branch; consumes real API usage
.\.venv\Scripts\python.exe scripts\measure_consistency.py `
  --provider mistral `
  --model ministral-8b-2512 `
  --input "sample_inputs\rent increase 2025-2026 NT2.pdf" `
  --type "Notice: Rent Change" `
  --runs 3 `
  --output-dir "output\consistency_ministral_refined" `
  --max-output-tokens 4000 `
  --request-delay 10
```

| Metric | Observed |
| --- | ---: |
| Independent uncached runs | 3 |
| Actual API calls | 9 |
| Total input tokens | 15,819 |
| Total output tokens | 2,464 |
| Exact document-level JSON match | No |
| Exactly stable top-level fields | 3 of 7 (**42.9%**) |

The exactly stable top-level fields were `effective_date`, `landlord_name`, and `tenant_name`. Other differences included punctuation in `property_address`, phrasing in `description`, text of `targets_consideration_description`, and the number/choice of evidence quotations. The reviewed runs had matching core rent amounts and effective dates; all three refined `condition` fields were empty. **Exact JSON stability is not factual accuracy.** Agreement on a wrong value would still produce a stable result.

Earlier **Gemini** three-run notice testing produced **4/7 exactly stable fields (57.1%)**, with 9 calls, 12,225 input tokens, and 19,660 reported output tokens (including reasoning tokens as reported by the Gemini client). These are **small, non-identical provider/model/prompt experiments**; they do **not** establish that either provider is more accurate or cheaper per correct extraction.

To repeat this experiment with Gemini on either branch, use the same `scripts/measure_consistency.py` on the feature branch with `--provider gemini --model gemini-3.8-flash`, a distinct output directory, and account-appropriate rate limits. The main-branch script does not have the Mistral-specific CLI options.

The tracked `evaluation/dry_run/` files are **planning snapshots**, and `evaluation/retrieval_spot_checks.json` contains small hand-picked evidence checks. Neither is a manually labeled factual-accuracy benchmark. The offline tests use mocked providers to verify control flow and schema behavior; they are not evidence of live extraction accuracy.

## Troubleshooting

| Problem | Action |
| --- | --- |
| `unrecognized arguments: --provider mistral` | You are on `main` or running an outdated installation. Switch to `feature/mistral-integration`, reinstall with `pip install -e ".[test]"`, and rerun. |
| `GEMINI_API_KEY` or `MISTRAL_API_KEY` missing | Set the matching environment variable in the same terminal session; do not commit it. |
| HTTP 401 / 403 | Verify the key, project, and account permissions. |
| HTTP 404 / unknown model | Confirm model ID and access in the provider console. |
| HTTP 429 | Check requests-per-second, tokens-per-minute, daily/monthly quotas and organization spending limits; a monthly allowance does not override throughput limits. Retrying immediately may not help. |
| `finish_reason="error"` on Ministral `key_dates` | Ensure the feature branch includes the tested JSON-mode workaround; strict-schema generation failed for that stage in the earlier revision. |
| `MAX_TOKENS` or `finish_reason="length"` | Adjust completion-token budget and/or split large specialty stages; higher token caps can increase quota demand. |
| Schema validation failure | Inspect stage diagnostics; retain the source schema and correct prompt/provider behavior rather than filling missing facts automatically. |
| `fitz` deprecation warning | The tracked PDF reader imports `fitz`; a future cleanup can replace it with `import pymupdf` and update uses accordingly. The warning is unrelated to API failures. |
| PDF missing | Copy the assignment PDFs locally to `sample_inputs/`; they are deliberately not in Git. |
| Image-only/scanned PDF | The current implementation intentionally fails rather than silently using OCR or inventing text. |

## Controls and reproducibility

- `--type`: exact document type name from `document_types.json`.
- `--document-types`: alternate definitions file.
- `--model`: explicit provider model ID.
- `--provider {gemini,mistral}`: **feature branch only**; Gemini is the default.
- `--thinking-level low|medium|high`: Gemini reasoning setting.
- `--request-delay`: pause between API requests from the same provider instance (does not delay the first request).
- `--max-output-tokens`: generation-token budget.
- `--general-budget` / `--specialty-budget`: retrieved source text character budgets; reducing them may hurt recall.
- `--no-cache`: bypass result caching for a genuine live test.
- `--refresh`: recompute stages even if valid cache entries exist.
- `--strict-evidence`: retry/fail on unverifiable evidence quotes.
- `--dry-run`: no API call; prints planned stages and approximate token sizes.
- `--emit-schema`: print the assembled schema; `--validate`: verify an existing JSON file without API calls.

Each live run saves validated JSON and a manifest for reproducibility. Cached requests do not prove repeatability of new model generations; use the uncached consistency script for that purpose. Python requirements and CLI entry point are defined in `pyproject.toml`.

## Security, privacy, and known limitations

- **Never put API keys in code, README examples, screenshots, logs, or Git.** Rotate a key if it has been exposed. `.env`, virtual environments, caches, outputs and PDFs are Git-ignored.
- **The repository is public.** The lease PDFs are excluded for confidentiality; original documents should be provided through a separately approved channel.
- API calls transmit selected **document text** to a third party. Confirm consent, data-processing terms, and eligibility for the chosen free or paid plan before processing sensitive tenant or landlord information. Free-tier terms may allow provider training/data use.
- Scanned PDFs do not currently have an OCR fallback. Encryption, production access controls, redaction, and retention/deletion policies for cached personal data remain future work.
- Schema validity and verbatim page quotes cannot verify legal interpretation. A human should review material dates, amounts, rights, and parties.
- Large-document retrieval may miss important clauses. No full human-labeled precision/recall, end-to-end commercial/AST live benchmark, or measured wall-clock/dollar-cost baseline is available yet.
- A temperature-zero request and fixed seed do **not** guarantee identical output; the consistency experiment demonstrates observable variability.

## Repository layout

```text
src/lease_extract/
  cli.py               CLI, dry run, JSON validation, output/manifest
  spec.py              Document-type loading and schema-envelope construction
  pdf.py               Local PyMuPDF PDF text reading, source page numbers
  retrieval.py         Deterministic evidence chunk selection
  pipeline.py          Stages, prompts, retries, cache, final assembly
  provider.py          Gemini REST provider
  mistral_provider.py  Mistral REST provider (feature branch only)
  validation.py        JSON Schema and source-evidence checks
  cache.py             Content-addressed stage cache
scripts/
  check_gemini_key.py  Gemini connectivity smoke test
  measure_consistency.py  Independent uncached repeated-run evaluation
  run_samples.ps1 / run_samples.sh  Gemini sample batch helpers
sample_inputs/
  document_types.json  Tracked extraction definitions
  *.pdf                Local-only: obtain from assignment package
assessment output is written under output/ (not committed)
evaluation/              Planning snapshots and retrieval spot checks
tests/                   Offline provider and pipeline tests
pyproject.toml           Dependencies, console entry point, pytest config
test_mistral.py          Optional SDK smoke test (feature branch)
```

## Future work

1. Complete live, human-reviewed AST and commercial lease extractions; compare with a labeled reference set.
2. Compare extraction factual correctness, cost, and latency across providers on the **same** document, schema, prompts, and evaluation protocol.
3. Add selective OCR for scanned pages and higher-recall retrieval/section discovery for long contracts.
4. Add deterministic formatting for non-substantive variations while preserving source quotations and surfacing conflicting facts for human review.
5. Split oversized specialist requests when needed; strengthen source-to-output semantic validation and error recovery.
6. Verify a clean clone with all required local inputs and the final committed feature-branch fixes.

---

**Submission note:** The evaluator should use `main` for the original Gemini implementation and [`feature/mistral-integration`](https://github.com/ReemaPandya/lease_extraction_gemini/tree/feature/mistral-integration) for Mistral support. The feature branch is experimental and must include the latest tested local fixes before it can reproduce the reported successful Ministral extraction.
