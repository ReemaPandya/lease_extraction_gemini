# START HERE — Free Gemini API key and lease extraction

## 1) Create a free-tier key

Open https://aistudio.google.com/api-keys, sign in, create/select your project, and click **Create API key**. Copy it privately. Confirm that your **project remains on the Free billing tier**; don't enable billing for this demonstration. The default model in this project is `gemini-3.8-flash`. Free API access is quota-limited and differs by model/project; check https://aistudio.google.com/rate-limit.

**Privacy:** On the unpaid Gemini tier Google may use submitted prompts and outputs to improve products and human reviewers may see them. Do not submit confidential legal documents or personal tenant data. Redact or use synthetic PDFs first.

## 2) Extract ZIP and open a terminal in this directory

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
$env:GEMINI_API_KEY="paste-your-key-here"
.\.venv\Scripts\python.exe scripts/check_gemini_key.py
.\.venv\Scripts\python.exe -m lease_extract --type "Notice: Rent Change" --input "sample_inputs/rent increase 2025-2026 NT2.pdf" --output "output/notice.json" --request-delay 5
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
export GEMINI_API_KEY='paste-your-key-here'
python scripts/check_gemini_key.py
python -m lease_extract --type 'Notice: Rent Change' --input 'sample_inputs/rent increase 2025-2026 NT2.pdf' --output 'output/notice.json' --request-delay 5
```

On success, the final command creates `output/notice.json` (extracted structured data) and `output/notice.manifest.json` (page evidence, usage, warnings).

## 3) Run locally without any key

```bash
pytest -q
lease-extract --list-types
lease-extract --type 'Notice: Rent Change' --input 'sample_inputs/rent increase 2025-2026 NT2.pdf' --dry-run
```

These commands **never call the Gemini API**. `pytest` uses mocked providers. If you don't have a key yet, you can still run all tests.

## 4) Typical errors

- `GEMINI_API_KEY is missing`: Set the variable in the same terminal, exactly as shown above.
- `HTTP 403`: Wrong/project-incompatible API key, permissions, or region.
- `HTTP 404`: The model isn't available for your project; check AI Studio's models and pass `--model` for an available free-tier model.
- `HTTP 429`: Free quota/rate limits reached. Retry after quota refresh or add `--request-delay 10`.
- `MAX_TOKENS`: Increase `--max-output-tokens` or simplify the input and retry.

For architecture details, benchmarks, limitations, and evaluation, read `README.md`.
