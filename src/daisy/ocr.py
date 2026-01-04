# src/daisy/ocr.py
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import fitz  # PyMuPDF


def _sha8(s: bytes) -> str:
    return hashlib.sha256(s).hexdigest()[:8]


def _cache_key(pdf_path: Path, *, lang: str, dpi: int, max_pages: int, pages: Optional[List[int]]) -> str:
    try:
        b = pdf_path.read_bytes()
    except Exception:
        b = (str(pdf_path).encode("utf-8"))

    pages_spec = ""
    if pages:
        pages_spec = "pages=" + ",".join(str(int(p)) for p in pages)
    else:
        pages_spec = f"first={int(max_pages)}"

    payload = b + f"|lang={lang}|dpi={dpi}|{pages_spec}".encode("utf-8")
    return _sha8(payload)


def _write_cache_txt(path: Path, ocr_pages: Dict[int, str]) -> None:
    # Simple text cache with page markers
    parts: List[str] = []
    for i in sorted(ocr_pages.keys()):
        parts.append(f"===PAGE {i}===\n")
        parts.append((ocr_pages[i] or "").rstrip() + "\n")
    path.write_text("".join(parts), encoding="utf-8")


def _read_cache_txt(path: Path) -> Dict[int, str]:
    txt = path.read_text(encoding="utf-8", errors="ignore")
    out: Dict[int, str] = {}
    cur_page: Optional[int] = None
    buf: List[str] = []

    def flush() -> None:
        nonlocal buf, cur_page
        if cur_page is not None:
            out[cur_page] = "".join(buf).strip()
        buf = []

    for line in txt.splitlines(True):
        if line.startswith("===PAGE ") and line.rstrip().endswith("==="):
            flush()
            mid = line.strip().removeprefix("===PAGE ").removesuffix("===")
            try:
                cur_page = int(mid.strip())
            except Exception:
                cur_page = None
            continue
        buf.append(line)

    flush()
    return out


def ocr_pdf_pages_best_effort(
    pdf_path: Path,
    cache_dir: Path,
    *,
    tesseract_cmd: Optional[str] = None,
    lang: str = "eng",
    dpi: int = 200,
    max_pages: int = 2,
    pages: Optional[List[int]] = None,  # explicit 0-based page indices
) -> Tuple[Dict[int, str], dict]:
    """
    Returns (ocr_pages, meta).

    - If pages is None: OCR first max_pages pages (0..max_pages-1)
    - If pages is provided: OCR exactly those 0-based page indices (bounded to doc)
    - Writes/reads cache file: <stem>.<hash>.txt
    """
    meta = {
        "ocr_enabled": True,
        "ocr_available": False,
        "ocr_attempted": False,
        "ocr_lang": lang,
        "ocr_dpi": int(dpi),
        "ocr_pages": 0,
        "ocr_text_chars": 0,
        "ocr_cache_hit": False,
        "ocr_succeeded": False,
        "ocr_pages_requested": pages,
    }

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = Path(pdf_path)
    key = _cache_key(pdf_path, lang=lang, dpi=int(dpi), max_pages=int(max_pages), pages=pages)
    cache_file = cache_dir / f"{pdf_path.stem}.{key}.txt"

    # Try cache
    if cache_file.exists():
        try:
            ocr_pages_map = _read_cache_txt(cache_file)
            meta["ocr_cache_hit"] = True
            meta["ocr_available"] = True
            meta["ocr_attempted"] = True
            meta["ocr_pages"] = int(len(ocr_pages_map))
            meta["ocr_text_chars"] = int(sum(len(v or "") for v in ocr_pages_map.values()))
            meta["ocr_succeeded"] = bool(meta["ocr_text_chars"] > 0)
            meta["ocr_pages_used"] = sorted(list(ocr_pages_map.keys()))
            logging.info("OCR cache hit: %s", cache_file.name)
            return ocr_pages_map, meta
        except Exception:
            pass

    # Determine tesseract availability
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        meta["ocr_available"] = True
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    except Exception as e:
        meta["ocr_attempted"] = True
        meta["error"] = f"ocr_unavailable: {type(e).__name__}: {e}"
        return {}, meta

    meta["ocr_attempted"] = True

    # OCR render + tesseract
    ocr_pages_map: Dict[int, str] = {}
    try:
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)

        if pages is not None and len(pages) > 0:
            target_pages = [int(p) for p in pages if 0 <= int(p) < total_pages]
        else:
            target_pages = list(range(min(int(max_pages), total_pages)))

        meta["ocr_pages"] = int(len(target_pages))
        meta["ocr_pages_used"] = target_pages

        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        for i in target_pages:
            try:
                page = doc.load_page(int(i))
                pix = page.get_pixmap(dpi=int(dpi), alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text = pytesseract.image_to_string(img, lang=lang) or ""
                ocr_pages_map[int(i)] = text
            except Exception:
                ocr_pages_map[int(i)] = ""

        doc.close()

        meta["ocr_text_chars"] = int(sum(len(v or "") for v in ocr_pages_map.values()))
        meta["ocr_succeeded"] = bool(meta["ocr_text_chars"] > 0)

        # Write cache
        try:
            _write_cache_txt(cache_file, ocr_pages_map)
            logging.info("OCR cache write: %s", cache_file.name)
        except Exception:
            pass

        return ocr_pages_map, meta

    except Exception as e:
        meta["error"] = f"ocr_error: {type(e).__name__}: {e}"
        return {}, meta
