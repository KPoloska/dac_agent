from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

def read_excel_first_sheet(path: Path) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=0, engine="openpyxl")

def col_exists(df: pd.DataFrame, col: str) -> bool:
    return col in df.columns

def non_empty_series(s: pd.Series) -> pd.Series:
    # treat NaN, None, empty string as empty
    return s.fillna("").astype(str).str.strip().ne("")

def meaningful_description(desc: str, display_name: str = "") -> bool:
    d = (desc or "").strip()
    if not d:
        return False
    if len(d) < 8:
        return False
    # If it's literally the display name, it's not a description
    if display_name and d.strip().lower() == str(display_name).strip().lower():
        return False
    # Common placeholders
    if d.strip() in {"...", "tbd", "n/a", "na"}:
        return False
    return True

@dataclass
class ExcelCheckFinding:
    total_rows: int
    failing_rows: int
    sample_rows: List[Dict[str, Any]]

def check_required_columns_non_empty(
    df: pd.DataFrame,
    required_cols: Sequence[str],
    id_col: Optional[str] = None,
    max_samples: int = 5,
) -> ExcelCheckFinding:
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        return ExcelCheckFinding(
            total_rows=len(df),
            failing_rows=len(df),
            sample_rows=[{"error": f"Missing columns: {missing}"}],
        )

    mask = pd.Series(True, index=df.index)
    for c in required_cols:
        mask &= non_empty_series(df[c])

    failing = df.loc[~mask]
    samples = []
    if not failing.empty:
        cols = list(dict.fromkeys(([id_col] if id_col else []) + list(required_cols)))
        cols = [c for c in cols if c in failing.columns]
        samples = failing[cols].head(max_samples).to_dict(orient="records")
    return ExcelCheckFinding(
        total_rows=len(df),
        failing_rows=int((~mask).sum()),
        sample_rows=samples,
    )

def check_meaningful_descriptions(
    df: pd.DataFrame,
    display_col: str,
    desc_col: str,
    max_samples: int = 5,
) -> ExcelCheckFinding:
    if display_col not in df.columns or desc_col not in df.columns:
        return ExcelCheckFinding(
            total_rows=len(df),
            failing_rows=len(df),
            sample_rows=[{"error": f"Missing columns: {[c for c in [display_col, desc_col] if c not in df.columns]}"}],
        )

    ok = []
    for dn, desc in zip(df[display_col].fillna(""), df[desc_col].fillna("")):
        ok.append(meaningful_description(str(desc), str(dn)))
    ok = pd.Series(ok, index=df.index)
    failing = df.loc[~ok]
    samples = failing[[display_col, desc_col]].head(max_samples).to_dict(orient="records") if not failing.empty else []
    return ExcelCheckFinding(
        total_rows=len(df),
        failing_rows=int((~ok).sum()),
        sample_rows=samples,
    )
