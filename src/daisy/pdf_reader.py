from __future__ import annotations

import re
from pathlib import Path
from typing import List

import fitz  # PyMuPDF

# Matches ("some file.xlsx")
XLSX_IN_QUOTES_RE = re.compile(r'\(\s*"([^"]+?\.xlsx)"\s*\)', re.IGNORECASE)

# Fallback: any token that looks like an .xlsx filename
XLSX_ANY_RE = re.compile(r"([A-Za-z0-9_\-\. ]{3,240}\.xlsx)", re.IGNORECASE)


class PdfDoc:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.doc = fitz.open(self.path)

    def page_count(self) -> int:
        return len(self.doc)

    def page_text(self, index0: int) -> str:
        return self.doc[index0].get_text("text") or ""

    def page_lines(self, index0: int) -> List[str]:
        return [l.rstrip() for l in self.page_text(index0).splitlines()]

    def all_text(self) -> str:
        out = []
        for p in self.doc:
            out.append(p.get_text("text") or "")
        return "\n".join(out)

    def find_pages_containing(self, needle: str, case_insensitive: bool = True) -> List[int]:
        n = needle.lower() if case_insensitive else needle
        hits = []
        for i in range(len(self.doc)):
            t = self.page_text(i)
            if (t.lower() if case_insensitive else t).find(n) != -1:
                hits.append(i)
        return hits


def find_referenced_xlsx_filenames(text: str) -> List[str]:
    """
    Best-effort extraction of referenced XLSX filenames from PDF text.

    IMPORTANT:
    DAC PDFs often wrap long filenames across lines.
    We normalize whitespace first so we don't get junk matches like "Services.xlsx".
    """
    if not text:
        return []

    # Normalize whitespace (fixes line-wrapped names)
    text = re.sub(r"\s+", " ", text)

    out: List[str] = []
    seen = set()

    # Prefer quoted ones: ("file.xlsx")
    for m in XLSX_IN_QUOTES_RE.finditer(text):
        name = Path(m.group(1)).name
        name = re.sub(r"\s+", " ", name).strip()
        low = name.lower()
        if low not in seen:
            seen.add(low)
            out.append(name)

    # Fallback: any .xlsx-like token
    for m in XLSX_ANY_RE.finditer(text):
        name = Path(m.group(1)).name
        name = re.sub(r"\s+", " ", name).strip()
        if not name.lower().endswith(".xlsx"):
            continue
        low = name.lower()
        if low not in seen:
            seen.add(low)
            out.append(name)

    return out
