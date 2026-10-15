"""Command line interface. `--dry-run` requires no credentials."""
import argparse
import json
from pathlib import Path
import sys
from .spec import load_document_type
from .pdf import read_pdf
from .retrieval import Selection
from .pipeline import execute_pipeline, plan_stages, _build_prompt, SYSTEM_PROMPT
from .provider import GeminiProvider, DEFAULT_MODEL
from .cache import Cache
from .validation import canonical_json, validate_result

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TYPES = ROOT / "sample_inputs" / "document_types.json"


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Schema-constrained lease PDF extraction")
    p.add_argument("--input", help="Local PDF to extract")
    p.add_argument("--document-types", default=str(DEFAULT_TYPES), help="document_types.json")
    p.add_argument("--type", help="Document type name, e.g. 'Lease: Residential (AST)'")
    p.add_argument("--output", default="output/extraction.json", help="Final JSON result path")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model (default: gemini-3.8-flash)")
    p.add_argument("--thinking-level", choices=("low", "medium", "high"), default="medium", help="Gemini 3.8 reasoning level")
    p.add_argument("--request-delay", type=float, default=0.0, help="Seconds between model calls to respect free-tier RPM limits")
    p.add_argument("--max-output-tokens", type=int, default=14000)
    p.add_argument("--general-budget", type=int, default=12000, help="Max evidence characters for grouped scalars")
    p.add_argument("--specialty-budget", type=int, default=42000, help="Max evidence characters per complex field")
    p.add_argument("--cache-dir", default=".lease_extract_cache")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--refresh", action="store_true", help="Recompute stages even on cache hits")
    p.add_argument("--strict-evidence", action="store_true", help="Retry/fail when evidence quotes do not occur verbatim on their cited pages")
    p.add_argument("--dry-run", action="store_true", help="Print a call/token plan without using an API key")
    p.add_argument("--list-types", action="store_true", help="Show available document types")
    p.add_argument("--emit-schema", action="store_true", help="Print the assembled JSON Schema (without extracting)")
    p.add_argument("--validate", metavar="JSON_FILE", help="Validate an existing result, without using a model")
    return p


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        if args.list_types:
            types = json.loads(Path(args.document_types).read_text(encoding="utf-8"))
            print("\n".join(str(t["name"]) for t in types))
            return 0
        if not args.type:
            raise ValueError("--type is required unless --list-types is specified")
        spec = load_document_type(args.document_types, args.type)
        if args.emit_schema:
            print(canonical_json(spec.envelope_schema), end="")
            return 0
        if args.validate:
            obj = json.loads(Path(args.validate).read_text(encoding="utf-8"))
            validate_result(obj, spec.envelope_schema)
            print("Schema validation passed")
            return 0
        if not args.input:
            raise ValueError("--input is required for extraction or --dry-run")
        pdf = read_pdf(args.input)
        stages = plan_stages(pdf, spec, args.general_budget, args.specialty_budget)
        if args.dry_run:
            plan = {
                "document_type": spec.name,
                "pdf_pages": len(pdf.pages),
                "pdf_text_characters": sum(len(p.text) for p in pdf.pages),
                "baseline_calls": len(spec.fields),
                "planned_calls_without_retries": len(stages),
                "baseline_pdf_page_images_sent": len(pdf.pages) * len(spec.fields),
                "planned_pdf_page_images_sent": 0,
                "stages": [
                    {"name": s.name, "selected_pages": list(s.evidence.pages),
                     "selected_chunks": s.evidence.chunks,
                     "total_chunks": s.evidence.total_chunks,
                     "selected_source_characters": s.evidence.characters,
                     "instructions_plus_source_approx_tokens":
                         (len(_build_prompt(s, pdf, spec)) + len(SYSTEM_PROMPT)) // 4}
                    for s in stages
                ],
            }
            print(canonical_json(plan), end="")
            return 0
        provider = GeminiProvider(args.model, args.max_output_tokens,
                                  request_delay=args.request_delay,
                                  thinking_level=args.thinking_level)
        run = execute_pipeline(
            pdf, spec, provider,
            None if args.no_cache else Cache(args.cache_dir),
            model_identifier=f"gemini:{args.model}|max_output={args.max_output_tokens}|thinking={args.thinking_level}",
            general_budget=args.general_budget,
            specialty_budget=args.specialty_budget,
            refresh=args.refresh,
            strict_evidence=args.strict_evidence,
        )
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(canonical_json(run.data), encoding="utf-8")
        target.with_name(target.stem + ".manifest.json").write_text(
            canonical_json(run.manifest), encoding="utf-8"
        )
        print(f"Extracted result: {target}")
        print(f"Manifest: {target.with_name(target.stem + '.manifest.json')}")
        print(f"Calls: {run.manifest['actual_model_calls']}; "
              f"input tokens: {run.manifest['actual_input_tokens_billed']}; "
              f"output tokens: {run.manifest['actual_output_tokens_billed']}; "
              f"evidence warnings: {run.manifest['warning_count']}")
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
