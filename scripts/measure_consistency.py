"""Live, quota-using, uncached repeatability measurement (not a mocked test).

Usage:
  python scripts/measure_consistency.py --input sample_inputs/"AST nt 2.pdf" \
      --type "Lease: Residential (AST)" --runs 3
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
from lease_extract.pipeline import execute_pipeline
from lease_extract.provider import GeminiProvider, DEFAULT_MODEL
from lease_extract.validation import canonical_json


def main():
    p = argparse.ArgumentParser(description="Repeat N genuine uncached API extractions")
    p.add_argument("--input", required=True)
    p.add_argument("--type", required=True)
    p.add_argument("--document-types", default=str(DEFAULT_TYPES))
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--max-output-tokens", type=int, default=14000)
    p.add_argument("--thinking-level", choices=("low", "medium", "high"), default="medium")
    p.add_argument("--request-delay", type=float, default=0.0,
                   help="Seconds between Gemini requests to stay within RPM limits")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--output-dir", default="output/consistency")
    p.add_argument("--strict-evidence", action="store_true")
    args = p.parse_args()
    if args.runs < 2:
        p.error("--runs must be at least 2")
    pdf = read_pdf(args.input)
    spec = load_document_type(args.document_types, args.type)
    provider = GeminiProvider(
        args.model,
        max_output_tokens=args.max_output_tokens,
        request_delay=args.request_delay,
        thinking_level=args.thinking_level,
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    runs = []
    for i in range(args.runs):
        res = execute_pipeline(
            pdf, spec, provider, cache=None, model_identifier=args.model,
            strict_evidence=args.strict_evidence,
        )
        payload = canonical_json(res.data)
        hash_ = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        (output / f"run_{i+1}.json").write_text(payload, encoding="utf-8")
        (output / f"run_{i+1}.manifest.json").write_text(
            canonical_json(res.manifest), encoding="utf-8"
        )
        runs.append({"sha256": hash_, "data": res.data, "manifest": res.manifest})
        print(f"Completed live run {i+1}/{args.runs}: {hash_}", flush=True)
    stability = {
        field.name: len({canonical_json({field.name: r["data"][field.name]}) for r in runs}) == 1
        for field in spec.fields
    }
    summary = {
        "runs": args.runs,
        "model": args.model,
        "max_output_tokens": args.max_output_tokens,
        "thinking_level": args.thinking_level,
        "request_delay_seconds": args.request_delay,
        "exact_document_match": len({r["sha256"] for r in runs}) == 1,
        "stable_fields": stability,
        "stable_field_fraction": sum(stability.values()) / len(stability),
        "total_uncached_calls": sum(r["manifest"]["actual_model_calls"] for r in runs),
        "total_input_tokens": sum(r["manifest"]["actual_input_tokens_billed"] for r in runs),
        "total_output_tokens": sum(r["manifest"]["actual_output_tokens_billed"] for r in runs),
        "hashes": [r["sha256"] for r in runs],
        "no_cache_used": True,
    }
    (output / "summary.json").write_text(canonical_json(summary), encoding="utf-8")
    print(canonical_json(summary))


if __name__ == "__main__":
    main()
