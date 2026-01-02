from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union


# -----------------------------------------------------------------------------
# Existing helpers used by agent.py
# -----------------------------------------------------------------------------
def find_first_value_after_labels(lines: List[str], labels: List[str]) -> Optional[str]:
    """
    Best-effort: find any line containing one of `labels` (case-insensitive),
    then return the next non-empty line that doesn't look like the label itself.
    """
    if not lines:
        return None

    labels_l = [l.lower() for l in labels if l]
    for i, raw in enumerate(lines):
        s = (raw or "").strip()
        if not s:
            continue
        s_l = s.lower()

        if any(lbl in s_l for lbl in labels_l):
            # try: same line "Label: value"
            parts = re.split(r":\s*", s, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()

            # otherwise, next non-empty line
            for j in range(i + 1, min(i + 8, len(lines))):
                v = (lines[j] or "").strip()
                if not v:
                    continue
                # skip if next line is just another label-ish thing
                v_l = v.lower()
                if any(lbl in v_l for lbl in labels_l):
                    continue
                return v
    return None


def extract_yes_no(text: Optional[str]) -> Optional[str]:
    """
    Normalize yes/no from arbitrary text.
    Returns "yes", "no" or None.
    """
    if not text:
        return None
    t = str(text).strip().lower()
    # common variants
    if re.search(r"\byes\b", t):
        return "yes"
    if re.search(r"\bno\b", t):
        return "no"
    return None


def list_existing_files(dir_path: Path) -> List[str]:
    """
    Return sorted list of *file names* inside dir (non-recursive).
    """
    p = Path(dir_path)
    if not p.exists() or not p.is_dir():
        return []
    return sorted([x.name for x in p.iterdir() if x.is_file()])


# -----------------------------------------------------------------------------
# New: deterministic run reproducibility helpers
# -----------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str, encoding: str = "utf-8") -> str:
    return hashlib.sha256(text.encode(encoding)).hexdigest()


def evidence_file_list(evidence_dir: Path, recursive: bool = False) -> List[str]:
    """
    Deterministic file listing for hashing.
    Returns *relative* paths (POSIX style), sorted.
    """
    base = Path(evidence_dir)
    if not base.exists() or not base.is_dir():
        return []

    files: List[Path] = []
    if recursive:
        files = [p for p in base.rglob("*") if p.is_file()]
    else:
        files = [p for p in base.iterdir() if p.is_file()]

    rels = [p.relative_to(base).as_posix() for p in files]
    return sorted(rels)


def evidence_file_list_hash(evidence_dir: Path, recursive: bool = False) -> Tuple[List[str], str]:
    """
    Hash of the evidence dir file list (not file contents).
    """
    rels = evidence_file_list(evidence_dir, recursive=recursive)
    joined = "\n".join(rels)
    return rels, sha256_text(joined)


# -----------------------------------------------------------------------------
# New: strict JSON sanitization (NaN/Infinity -> None)
# -----------------------------------------------------------------------------
def _is_nan_like(x: Any) -> bool:
    # float nan/inf
    if isinstance(x, float):
        return not math.isfinite(x)

    # numpy floats/ints if numpy exists
    try:
        import numpy as np  # type: ignore

        if isinstance(x, (np.floating,)):
            xv = float(x)
            return not math.isfinite(xv)
    except Exception:
        pass

    # pandas NA / NaT / numpy.nan etc via pandas.isna if pandas exists
    try:
        import pandas as pd  # type: ignore

        # pd.isna(True) is False; pd.isna("x") is False; pd.isna(pd.NA) is True
        return bool(pd.isna(x))
    except Exception:
        return False


def sanitize_json(obj: Any) -> Any:
    """
    Recursively convert objects into JSON-safe structures:
    - NaN/Inf/pd.NA -> None
    - Path -> str
    - tuples/sets -> lists
    - dict keys -> str if not already basic JSON key
    """
    if obj is None:
        return None

    # NaN / Inf / pd.NA
    if _is_nan_like(obj):
        return None

    # primitives
    if isinstance(obj, (str, int, bool)):
        return obj

    # floats (finite)
    if isinstance(obj, float):
        return obj

    # Path
    if isinstance(obj, Path):
        return str(obj)

    # bytes
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8", errors="replace")
        except Exception:
            return str(obj)

    # list/tuple/set
    if isinstance(obj, (list, tuple, set)):
        return [sanitize_json(x) for x in obj]

    # dict
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(k, (str, int, float, bool)) and not _is_nan_like(k):
                kk = str(k) if not isinstance(k, str) else k
            else:
                kk = str(k)
            out[kk] = sanitize_json(v)
        return out

    # fallback: try to stringify (safe for weird objects like Timestamps)
    return str(obj)
