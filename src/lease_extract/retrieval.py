"""Deterministic high-recall page/section evidence selection without embeddings.

Page/chunk retrieval is a recall optimization, NOT a claim of semantic coverage.
The recorded manifest exposes which pages were and were not sent to the LLM.
"""
from dataclasses import dataclass
from collections import Counter
import math
import re
from .pdf import PDFDocument

TOKENS = re.compile(r"[a-z][a-z0-9_]{2,}|\d+(?:\.\d+)?", re.I)
ANCHORS = {
    "general": [
        "dated", "parties", "between", "landlord", "tenant", "property",
        "demised", "premises", "address", "effective", "agreement", "lease",
    ],
    "rent": [
        "rent", "rental", "basic rent", "initial rent", "yearly rent",
        "annual rent", "monthly rent", "payment", "payable", "per annum",
        "per month", "consideration", "quarterly", "premium", "peppercorn",
        "fee", "reviewed rent", "contribution", "reduction", "new rent",
        "licence fee", "turnover", "indexation", "rent commencement",
    ],
    "review": [
        "rent review", "review date", "reviewed rent", "market rent",
        "review", "rpi", "cpi", "indexation", "upward only",
        "higher of", "greater of", "anniversary", "retail price",
        "open market", "surveyors", "rent increases", "rent adjustment",
    ],
    "dates": [
        "commencement", "term", "expiry", "expir", "break date",
        "termination", "review date", "effective date", "dated",
        "lease term", "starting", "start date", "expiry date", "end date",
        "term of years", "duration", "expires", "initial period",
        "tenancy period", "possession", "notice", "surrender",
    ],
}


@dataclass(frozen=True)
class Chunk:
    page: int
    offset: int
    text: str


@dataclass(frozen=True)
class Selection:
    text: str
    pages: tuple[int, ...]
    chunks: int
    total_chunks: int
    characters: int
    budget: int


def chunk_pages(doc: PDFDocument, size: int = 1550, overlap: int = 170) -> list[Chunk]:
    chunks: list[Chunk] = []
    for page in doc.pages:
        text = page.text
        if not text:
            continue
        pos = 0
        while pos < len(text):
            end = min(pos + size, len(text))
            if end < len(text):
                # Split near a line boundary without discarding material.
                cut = text.rfind("\n", pos + size // 2, end)
                if cut > pos:
                    end = cut + 1
            chunks.append(Chunk(page.number, pos, text[pos:end].strip()))
            if end == len(text):
                break
            pos = max(pos + 1, end - overlap)
    return chunks


def _rank(chunks: list[Chunk], category: str) -> list[tuple[float, Chunk]]:
    # Anchored BM25, intentionally independent of 80k-character bespoke prompts.
    query = ANCHORS.get(category, ANCHORS["general"])
    q_words = set(TOKENS.findall(" ".join(query).lower()))
    tokens = [Counter(TOKENS.findall(c.text.lower())) for c in chunks]
    df = Counter(word for t in tokens for word in t)
    N = len(chunks)
    avgdl = sum(sum(t.values()) for t in tokens) / max(N, 1)
    ranked = []
    for i, (c, tf) in enumerate(zip(chunks, tokens)):
        n = sum(tf.values())
        score = 0.0
        for w in q_words:
            freq = tf[w]
            if freq:
                idf = math.log(1 + (N - df[w] + .5) / (df[w] + .5))
                score += idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * n / max(avgdl, 1)))
        lower = c.text.lower()
        score += 1.6 * sum(lower.count(p) for p in query if " " in p)
        if category == "rent":
            score += 3 * min(3, len(re.findall(r"[£$€]\s*[\d,]+", c.text)))
        if category == "dates":
            score += 1.6 * min(3, len(re.findall(r"\b\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+20\d\d\b", lower)))
        # Introduction/parties are usually near the beginning. Never rely on this alone.
        if c.page <= 2: score += (12 if category == "general" else 3)
        if category == "general" and c.page >= chunks[-1].page - 1: score += 1
        ranked.append((score, c))
    # Stable tie breaking is necessary for reproducible prompt content.
    return sorted(ranked, key=lambda item: (-item[0], item[1].page, item[1].offset))


def select_evidence(doc: PDFDocument, category: str, char_budget: int = 42000) -> Selection:
    if char_budget < 1000:
        raise ValueError("Evidence budget must be at least 1,000 characters")
    chunks = chunk_pages(doc)
    if not chunks:
        raise ValueError("PDF has no extractable text")
    # A tiny document always goes in full. No retrieval-induced false negatives.
    full = doc.all_text
    if len(full) <= char_budget:
        return Selection(full, tuple(p.number for p in doc.pages), len(chunks), len(chunks), len(full), char_budget)
    ranked = _rank(chunks, category)
    # Always include the title/parties/date page, including when keyword density
    # elsewhere is greater. Preserve enough context to identify the parties.
    intro = [c for c in chunks if c.page == 1]
    chosen: list[Chunk] = []
    remaining = char_budget
    for chunk in intro:
        entry_length = len(chunk.text) + 32
        if entry_length <= remaining:
            chosen.append(chunk)
            remaining -= entry_length
    for _, chunk in ranked:
        if chunk in chosen:
            continue
        # Reserve markup characters. Avoid truncated extracts that poison evidence.
        entry_length = len(chunk.text) + 32
        if entry_length <= remaining:
            chosen.append(chunk)
            remaining -= entry_length
    chosen.sort(key=lambda c: (c.page, c.offset))
    rendered = "\n\n".join(
        f"[PAGE {c.page}, SOURCE OFFSET {c.offset}]\n{c.text}" for c in chosen
    )
    assert len(rendered) <= char_budget
    return Selection(rendered, tuple(sorted({c.page for c in chosen})),
                     len(chosen), len(chunks), len(rendered), char_budget)
