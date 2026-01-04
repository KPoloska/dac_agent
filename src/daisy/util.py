# src/daisy/util.py
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def sanitize_json(obj: Any) -> Any:
    """
    Remove non-JSON-friendly values (NaN/inf), Path objects, etc. Best-effort.
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        # JSON doesn't support NaN/inf reliably; convert to string
        if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
            return str(obj)
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_json(v) for v in obj]
    # fallback
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def list_existing_files(dir_path: Path) -> List[str]:
    if not dir_path.exists():
        return []
    out: List[str] = []
    for p in sorted(dir_path.iterdir()):
        if p.is_file():
            out.append(p.name)
    return out


def evidence_file_list_hash(evidence_dir: Path, recursive: bool = False) -> Tuple[List[str], str]:
    """
    Returns (sorted relative file list, sha256 of joined list).
    """
    files: List[str] = []
    if recursive:
        for p in evidence_dir.rglob("*"):
            if p.is_file():
                files.append(str(p.relative_to(evidence_dir)).replace("/", "\\"))
    else:
        for p in evidence_dir.iterdir():
            if p.is_file():
                files.append(p.name)

    files = sorted(files, key=lambda s: s.lower())
    joined = "\n".join(files).encode("utf-8", errors="ignore")
    return files, hashlib.sha256(joined).hexdigest()


def find_first_value_after_labels(lines: List[str], labels: List[str]) -> Optional[str]:
    """
    Scan lines and try to find a value right after any of the given labels.
    Very simple heuristic: if a line contains the label, return trailing text or next non-empty line.
    """
    if not lines:
        return None

    labels_low = [l.lower() for l in labels]
    clean = [ln.strip() for ln in lines]

    for i, ln in enumerate(clean):
        low = ln.lower()
        for lab, lab_low in zip(labels, labels_low):
            if lab_low in low:
                # same line value after label
                # e.g. "CMS Product ID 1513344" or "IT Asset ID: AID551"
                after = re.split(re.escape(lab), ln, flags=re.IGNORECASE)
                if len(after) >= 2:
                    v = after[-1].strip(" :\t")
                    if v:
                        return v
                # next non-empty line
                for j in range(i + 1, min(i + 6, len(clean))):
                    if clean[j]:
                        return clean[j]
    return None


def extract_yes_no(value: Optional[str]) -> Optional[str]:
    """
    OCR-tolerant YES/NO extraction.
    Accepts: yes/no, y/n, with punctuation and common OCR whitespace.
    Returns: "yes" or "no" or None.
    """
    if value is None:
        return None

    s = str(value).strip().lower()
    if not s:
        return None

    # Normalize common punctuation and whitespace
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = s.strip(" \t\n\r:;,.|[](){}")

    # If the whole string is exactly y/n
    if s in {"y", "yes"}:
        return "yes"
    if s in {"n", "no"}:
        return "no"

    # If string contains standalone token yes/no/y/n
    m = re.search(r"(?i)\b(yes|no|y|n)\b", s)
    if not m:
        return None

    tok = m.group(1).lower()
    if tok in {"yes", "y"}:
        return "yes"
    if tok in {"no", "n"}:
        return "no"
    return None
