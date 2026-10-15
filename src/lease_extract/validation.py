"""Schema and evidence checks. Never silently coerce or invent missing values."""
import json
import re
import unicodedata
from typing import Any
from jsonschema import Draft202012Validator
from .pdf import PDFDocument


class SchemaValidationError(ValueError):
    pass


class EvidenceValidationError(ValueError):
    pass


def validate_result(data: dict, schema: dict) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: (list(map(str,e.absolute_path)),e.message))
    if errors:
        messages = []
        for e in errors[:6]:
            path = "/".join(map(str, e.absolute_path)) or "<root>"
            messages.append(f"/{path}: {e.message}")
        raise SchemaValidationError("; ".join(messages))


def _canonical(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold()
    s = s.replace("\u2019", "'").replace("\u00ad", "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _walk_evidence(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "internal_evidence" and isinstance(child, list):
                for i, item in enumerate(child):
                    if isinstance(item, dict):
                        yield f"{prefix}/{key}/{i}", item
            else:
                yield from _walk_evidence(child, f"{prefix}/{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from _walk_evidence(child, f"{prefix}/{i}")


def evidence_warnings(data: dict, pdf: PDFDocument) -> list[str]:
    warnings: list[str] = []
    pages = {p.number: _canonical(p.text) for p in pdf.pages}
    # Schemas permit empty evidence lists, but substantive extracted records
    # without support should be flagged rather than silently accepted as proven.
    def check_missing(value: Any, prefix: str = ""):
        if isinstance(value, dict):
            if "internal_evidence" in value and value["internal_evidence"] == []:
                substantive = any(
                    k not in {"internal_evidence", "internal_source", "notes", "is_fixed_term"}
                    and v not in ("", [], {}, None, False)
                    for k, v in value.items()
                ) or value.get("is_fixed_term") is True
                if substantive:
                    warnings.append(f"{prefix}/internal_evidence: no evidence for a populated record")
            for key, child in value.items():
                check_missing(child, f"{prefix}/{key}")
        elif isinstance(value, list):
            for i, child in enumerate(value):
                check_missing(child, f"{prefix}/{i}")
    check_missing(data)
    for path, item in _walk_evidence(data):
        n = item.get("page")
        quote = item.get("text", "")
        if not isinstance(n, int) or isinstance(n, bool) or n not in pages:
            warnings.append(f"{path}: invalid source page {n!r}")
        elif quote and _canonical(quote) not in pages[n]:
            # A citation cannot be considered verified just because the words
            # are in a different page; preserve precise page provenance.
            warnings.append(f"{path}: quotation not found verbatim on page {n}")
        elif not quote:
            warnings.append(f"{path}: empty evidence quotation")
    return warnings


def canonical_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
