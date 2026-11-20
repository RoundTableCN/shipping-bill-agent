"""Evidence grounding: every extracted field must point to source text."""

from __future__ import annotations

import re
import unicodedata

from ..candidates.columns import table_rows
from ..models.bundle import DocumentBundle


def normalize_evidence(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def evidence_corpus(bundle: DocumentBundle) -> str:
    parts: list[str] = [bundle.raw_text, bundle.norm_text]
    parts.extend(block.text for block in bundle.blocks)
    for table in bundle.tables:
        for cell in table.cells:
            parts.append(cell.text)
        for row in table_rows(table):
            parts.append(" ".join(cell.text for cell in row if cell is not None))
    return normalize_evidence("\n".join(parts))


def evidence_in_text(quote: str | None, bundle: DocumentBundle) -> bool:
    needle = normalize_evidence(quote)
    if not needle:
        return False
    return needle in evidence_corpus(bundle)
