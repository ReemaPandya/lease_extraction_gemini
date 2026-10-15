"""Local-first PDF text extraction. Never upload page images by default."""
from dataclasses import dataclass
from pathlib import Path
import re
import fitz


class UnreadablePDFError(ValueError):
    pass


@dataclass(frozen=True)
class Page:
    number: int  # 1-based PDF page number
    text: str


@dataclass(frozen=True)
class PDFDocument:
    path: Path
    pages: tuple[Page, ...]

    @property
    def title(self) -> str:
        return self.path.name

    @property
    def all_text(self) -> str:
        return "\n".join(f"[PAGE {p.number}]\n{p.text}" for p in self.pages)


def normalize_text(s: str) -> str:
    # Keep original source line breaks for evidence, normalize only repeated spaces.
    s = s.replace("\x00", "").replace("\u00ad", "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[\t ]+", " ", s)
    s = re.sub(r"\n{4,}", "\n\n\n", s)
    return s.strip()


def read_pdf(path: str | Path, minimum_text_chars: int = 80) -> PDFDocument:
    path = Path(path).resolve()
    with fitz.open(path) as pdf:
        if pdf.is_encrypted and not pdf.authenticate(""):
            raise UnreadablePDFError("Encrypted PDF; password required")
        pages = tuple(Page(i + 1, normalize_text(p.get_text("text", sort=True)))
                      for i, p in enumerate(pdf))
    if not pages:
        raise UnreadablePDFError("PDF has no pages")
    if sum(len(p.text) for p in pages) < minimum_text_chars:
        raise UnreadablePDFError(
            "PDF appears image-only or empty. OCR is intentionally not performed "
            "silently: use a searchable PDF or add an explicit OCR adapter."
        )
    # A mixed PDF can have blank/signature pages: keep their original page indices.
    return PDFDocument(path, pages)
