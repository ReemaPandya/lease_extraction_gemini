"""Load the supplied real-world document_types.json document definitions.

Each `fields[]` entry has an independent response schema; the supplied file
has NO single document-wide schema. We preserve those independent schemas in
an envelope indexed by the ORIGINAL field name (including `Consideration`).
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json


@dataclass(frozen=True)
class Field:
    name: str
    description: str
    schema: dict[str, Any]
    field_type: str
    item_type: str = "string"

    @property
    def is_complex(self) -> bool:
        return bool(self.schema)

    @property
    def category(self) -> str:
        name = self.name.lower()
        if name.startswith("consideration_review"):
            return "review"
        if name.startswith("consideration"):
            return "rent"
        if name == "key_dates":
            return "dates"
        return "general"


@dataclass(frozen=True)
class DocumentType:
    name: str
    fields: tuple[Field, ...]

    @property
    def envelope_schema(self) -> dict[str, Any]:
        # Schema for the final assembled output, not present in the input JSON.
        properties = {
            f.name: f.schema if f.is_complex else {"type": f_schema_type(f)}
            for f in self.fields
        }
        return {
            "type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False,
        }


def f_schema_type(field: Field) -> str:
    # Supplied general fields have item_type: "string" and schema: {}.
    # Other primitive types are supported for portability.
    allowed = {"string", "number", "integer", "boolean", "array", "object"}
    return field.item_type if field.item_type in allowed else "string"


def load_document_type(path: str | Path, name: str) -> DocumentType:
    document_types = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(document_types, dict):
        document_types = document_types.get("document_types", [document_types])
    if not isinstance(document_types, list):
        raise ValueError("Expected a list of document types")
    matches = [t for t in document_types if t.get("name", "").casefold() == name.casefold()]
    if len(matches) != 1:
        available = ", ".join(str(t.get("name")) for t in document_types)
        raise ValueError(f"Document type {name!r} not found; choose one of: {available}")
    t = matches[0]
    fields = tuple(
        Field(name=f["name"], description=f.get("description", ""),
              schema=f.get("schema") or {}, field_type=f.get("field_type", "general"),
              item_type=f.get("item_type", "string"))
        for f in t["fields"]
    )
    if len({f.name for f in fields}) != len(fields):
        raise ValueError(f"Duplicate field names in {name!r}")
    return DocumentType(t["name"], fields)
