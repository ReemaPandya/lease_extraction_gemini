
"""Measure multiple INDEPENDENT extractions, without using a response cache.

Saves each completed run before the next request. Matching runs can resume after
interruption or daily quota exhaustion. Compare semantic facts separately from
exact JSON hashes: different descriptions/notes can fail exact-match even when
facts are equal. Does not send documents unless a missing run is executed.

Example:
  python scripts/measure_consistency.py --input "sample_inputs/AST nt 2.pdf" \
      --type "Lease: Residential (AST)" --runs 3 --thinking-level low \
      --max-output-tokens 40000 --request-delay 5
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lease_extract.cli import DEFAULT_TYPES
from lease_extract.spec import load_document_type
from lease_extract.pdf import read_pdf
from lease_extract.pipeline import execute_pipeline, PIPELINE_VERSION
from lease_extract.provider import GeminiProvider, DEFAULT_MODEL
from lease_extract.mistral_provider import MistralProvider, DEFAULT_MISTRAL_MODEL
from lease_extract.validation import canonical_json, validate_result


def difference_paths(a, b, prefix="", limit=40):
    """Report JSON paths with changed values, not potentially sensitive text."""
    paths = []
    def visit(x, y, path):
        if len(paths) >= limit:
            return
        if type(x) is not type(y):
            paths.append(path or "/")
        elif isinstance(x, dict):
            for key in sorted(x.keys() | y.keys()):
                segment = str(key).replace("~", "~0").replace("/", "~1")
                if key not in x or key not in y:
                    paths.append(f"{path}/{segment}")
                else:
                    visit(x[key], y[key], f"{path}/{segment}")
                if len(paths) >= limit:
                    return
        elif isinstance(x, list):
            if len(x) != len(y):
                paths.append(f"{path}/length")
            for i, (left, right) in enumerate(zip(x, y)):
                visit(left, right, f"{path}/{i}")
                if len(paths) >= limit:
                    return
        elif x != y:
            paths.append(path or "/")
    visit(a, b, prefix)
    return paths


def summarize(runs, spec):
    if not runs:
        return {"completed_runs": 0}
    stability = {
        field.name: len({canonical_json({field.name: r["data"][field.name]}) for r in runs}) == 1
        for field in spec.fields
    }
    differences = {}
    if len(runs) > 1:
        reference = runs[0]["data"]
        for i, run in enumerate(runs[1:], 2):
            differences[f"run_1_vs_run_{i}"] = difference_paths(reference, run["data"])
    return {
        "completed_runs": len(runs),
        "exact_document_match": len({r["sha256"] for r in runs}) == 1,
        "hashes": [r["sha256"] for r in runs],
        "stable_fields": stability,
        "stable_field_fraction": sum(stability.values()) / len(stability),
        "changed_json_paths": differences,
        "total_uncached_calls": sum(r["manifest"]["actual_model_calls"] for r in runs),
        "total_input_tokens": sum(r["manifest"]["actual_input_tokens_billed"] for r in runs),
        "total_output_tokens": sum(r["manifest"]["actual_output_tokens_billed"] for r in runs),
        "no_cache_used": True,
        "note": "Exact JSON agreement measures output stability, not fact-level accuracy. "
                "Gemini output tokens include reasoning tokens where reported."
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Compare genuine, uncached extraction runs")
    p.add_argument("--input", required=True)
    p.add_argument("--type", required=True)
    p.add_argument("--document-types", default=str(DEFAULT_TYPES))
    p.add_argument("--provider", choices=("gemini", "mistral"), default="gemini")
    p.add_argument("--model", default=None)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--output-dir", default="output/consistency")
    p.add_argument("--strict-evidence", action="store_true")
    p.add_argument("--thinking-level", choices=("low", "medium", "high"), default="low")
    p.add_argument("--max-output-tokens", type=int, default=None)
    p.add_argument("--request-delay", type=float, default=5.0)
    p.add_argument("--general-budget", type=int, default=12000)
    p.add_argument("--specialty-budget", type=int, default=42000)
    args = p.parse_args(argv)
    if args.runs < 2:
        p.error("--runs must be at least 2")
    model = args.model or (DEFAULT_MISTRAL_MODEL if args.provider == "mistral" else DEFAULT_MODEL)
    max_tokens = args.max_output_tokens if args.max_output_tokens is not None else (6000 if args.provider == "mistral" else 40000)
    if max_tokens < 1 or args.request_delay < 0:
        p.error("Token budget must be positive and delay nonnegative")
    pdf = read_pdf(args.input)
    spec = load_document_type(args.document_types, args.type)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    settings = {
        "pipeline_version": PIPELINE_VERSION,
        "document_sha256": hashlib.sha256(pdf.path.read_bytes()).hexdigest(),
        "document_types_sha256": hashlib.sha256(Path(args.document_types).read_bytes()).hexdigest(),
        "document_type": spec.name,
        "provider": args.provider,
        "model": model,
        "strict_evidence": args.strict_evidence,
        "thinking_level": args.thinking_level,
        "max_output_tokens": max_tokens,
        "general_budget": args.general_budget,
        "specialty_budget": args.specialty_budget,
    }
    settings_path = output / "settings.json"
    if settings_path.exists():
        if json.loads(settings_path.read_text(encoding="utf-8")) != settings:
            p.error("The output folder contains results from a different configuration. "
                    "Use a new --output-dir or restore the previous settings.")
    elif any(output.glob("run_*.json")):
        p.error("The output folder contains older runs without settings metadata. "
                "Use a fresh --output-dir to avoid mixing experiments.")
    else:
        settings_path.write_text(canonical_json(settings), encoding="utf-8")

    runs = []
    # Construct the provider only if a fresh run is necessary. Keyless report
    # regeneration therefore works after all runs have been recorded.
    provider = None
    for i in range(args.runs):
        json_path = output / f"run_{i + 1}.json"
        manifest_path = output / f"run_{i + 1}.manifest.json"
        if json_path.exists() and manifest_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            validate_result(data, spec.envelope_schema)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if any(stage["cache_hit"] for stage in manifest["stages"]):
                p.error("Existing run was cached; cannot include it in an uncached evaluation")
            print(f"Resuming completed run {i + 1}/{args.runs} (no API call)", flush=True)
        elif json_path.exists() or manifest_path.exists():
            p.error(f"Incomplete run pair for {i+1}; investigate or delete both files")
        else:
            if provider is None:
                if args.provider == "mistral":
                    provider = MistralProvider(model, max_output_tokens=max_tokens,
                                               request_delay=args.request_delay)
                else:
                    provider = GeminiProvider(model, max_output_tokens=max_tokens,
                                              thinking_level=args.thinking_level,
                                              request_delay=args.request_delay)
            try:
                result = execute_pipeline(
                    pdf, spec, provider, cache=None,
                    model_identifier=(
                        f"mistral:{model}|max_output={max_tokens}|temp=0|seed=42"
                        if args.provider == "mistral" else
                        f"gemini:{model}|max_output={max_tokens}|thinking={args.thinking_level}"
                    ),
                    general_budget=args.general_budget,
                    specialty_budget=args.specialty_budget,
                    strict_evidence=args.strict_evidence,
                )
            except (RuntimeError, ValueError) as exc:
                # Previous runs have been saved; failed run was not counted.
                print(f"ERROR on run {i + 1}/{args.runs}: {exc}", file=sys.stderr)
                print("Completed runs remain on disk. Rerun the SAME command after the "
                      "problem is resolved to resume without repeating successful runs.", file=sys.stderr)
                if runs:
                    (output / "partial_summary.json").write_text(
                        canonical_json(summarize(runs, spec)), encoding="utf-8")
                return 2
            data, manifest = result.data, result.manifest
            json_path.write_text(canonical_json(data), encoding="utf-8")
            manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
            print(f"Completed uncached run {i+1}/{args.runs}: "
                  f"{hashlib.sha256(canonical_json(data).encode('utf-8')).hexdigest()}", flush=True)
        sha256 = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
        runs.append({"sha256": sha256, "data": data, "manifest": manifest})

    summary = summarize(runs, spec)
    summary["runs"] = args.runs
    (output / "summary.json").write_text(canonical_json(summary), encoding="utf-8")
    print(canonical_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
