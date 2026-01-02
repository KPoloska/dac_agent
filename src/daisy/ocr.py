from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import subprocess


@dataclass
class OcrResult:
    text: str
    meta: Dict[str, Any]


def tesseract_available(tesseract_cmd: Optional[str] = None) -> bool:
    cmd = tesseract_cmd or "tesseract"
    try:
        p = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
        return p.returncode == 0
    except Exception:
        return False


def ocr_pdf_text(
    pdf_path: Path,
    *,
    lang: str = "eng",
    tesseract_cmd: Optional[str] = None,
    max_pages: Optional[int] = None,
    dpi: int = 200,
) -> OcrResult:
    """
    Best-effort OCR for image-based PDFs.
    Renders pages with PyMuPDF and runs pytesseract.
    """
    # Lazy imports so the rest of the app works without OCR deps
    try:
        import fitz  # type: ignore
    except Exception as e:
        raise RuntimeError(f"PyMuPDF (fitz) not available for OCR: {e}") from e

    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception as e:
        raise RuntimeError(f"OCR deps missing (pytesseract/Pillow): {e}") from e

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    doc = fitz.open(str(pdf_path))

    pages = len(doc)
    limit = pages if max_pages is None else max(0, min(pages, int(max_pages)))

    # Scale to approximate DPI from 72 default: scale = dpi/72
    scale = float(dpi) / 72.0
    mat = fitz.Matrix(scale, scale)

    out_text_parts = []
    ocr_pages = 0
    errors = []

    for i in range(limit):
        try:
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            txt = pytesseract.image_to_string(img, lang=lang) or ""
            out_text_parts.append(txt)
            ocr_pages += 1
        except Exception as e:
            errors.append(f"page {i}: {e}")

    doc.close()

    text = "\n".join(out_text_parts).strip()
    meta: Dict[str, Any] = {
        "ocr_attempted": True,
        "ocr_lang": lang,
        "ocr_dpi": dpi,
        "ocr_pages": int(ocr_pages),
        "ocr_text_chars": int(len(text)),
    }
    if errors:
        meta["ocr_errors"] = errors[:10]  # cap noise

    return OcrResult(text=text, meta=meta)
