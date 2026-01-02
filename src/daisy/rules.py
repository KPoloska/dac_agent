from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml


@dataclass
class PdfContentRule:
    id: str
    name: str
    type: str = "regex"      # "regex" | "contains"
    pattern: str = ""        # used when type="regex"
    contains: str = ""       # used when type="contains"
    severity: str = "major"


@dataclass
class PdfEvidenceRules:
    required_files: List[str]
    min_text_chars: int = 200
    ocr_image_threshold: int = 1
    content_rules: Dict[str, List[PdfContentRule]] = field(default_factory=dict)


@dataclass
class ExcelThresholdRule:
    ratio_tol: float
    abs_tol: int
    severity: str = "major"
    mvp_severity: Optional[str] = None
    non_mvp_severity: Optional[str] = None


@dataclass
class Rules:
    pdf_evidence: PdfEvidenceRules

    # Flattened access used by agent.py
    entitlements_required: ExcelThresholdRule
    entitlements_descriptions: ExcelThresholdRule
    itroles_required: ExcelThresholdRule
    itroles_descriptions: ExcelThresholdRule


def _excel_rule(block: dict, *, default_ratio: float, default_abs: int, default_sev: str = "major") -> ExcelThresholdRule:
    block = block or {}
    return ExcelThresholdRule(
        ratio_tol=float(block.get("ratio_tol", default_ratio)),
        abs_tol=int(block.get("abs_tol", default_abs)),
        severity=str(block.get("severity", default_sev)),
        mvp_severity=(str(block["mvp_severity"]) if "mvp_severity" in block and block["mvp_severity"] is not None else None),
        non_mvp_severity=(str(block["non_mvp_severity"]) if "non_mvp_severity" in block and block["non_mvp_severity"] is not None else None),
    )


def load_rules(rules_path: Optional[Path]) -> Rules:
    path = Path(rules_path) if rules_path else (Path("config") / "rules.yaml")
    data: dict = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    pdf = data.get("pdf_evidence", {}) or {}
    required_files = list(pdf.get("required_files", []) or [])
    min_text_chars = int(pdf.get("min_text_chars", 200) or 200)
    ocr_image_threshold = int(pdf.get("ocr_image_threshold", 1) or 1)

    # content_rules
    raw_cr = pdf.get("content_rules", {}) or {}
    content_rules: Dict[str, List[PdfContentRule]] = {}
    if isinstance(raw_cr, dict):
        for fname, rules_list in raw_cr.items():
            if not isinstance(rules_list, list):
                continue
            parsed: List[PdfContentRule] = []
            for r in rules_list:
                if not isinstance(r, dict):
                    continue
                rid = str(r.get("id") or "").strip()
                if not rid:
                    continue
                rtype = str(r.get("type") or "regex").strip().lower()
                parsed.append(
                    PdfContentRule(
                        id=rid,
                        name=str(r.get("name") or rid).strip(),
                        type=rtype,
                        pattern=str(r.get("pattern") or ""),
                        contains=str(r.get("contains") or ""),
                        severity=str(r.get("severity") or "major"),
                    )
                )
            if parsed:
                content_rules[str(fname)] = parsed

    pdf_rules = PdfEvidenceRules(
        required_files=required_files,
        min_text_chars=min_text_chars,
        ocr_image_threshold=ocr_image_threshold,
        content_rules=content_rules,
    )

    ex = data.get("excel_thresholds", {}) or {}

    ent_req = _excel_rule(ex.get("entitlements_required", {}), default_ratio=0.10, default_abs=50)
    ent_desc = _excel_rule(ex.get("entitlements_descriptions", {}), default_ratio=0.10, default_abs=50, default_sev="major")
    it_req = _excel_rule(ex.get("itroles_required", {}), default_ratio=0.01, default_abs=5)
    it_desc = _excel_rule(ex.get("itroles_descriptions", {}), default_ratio=0.01, default_abs=5, default_sev="major")

    return Rules(
        pdf_evidence=pdf_rules,
        entitlements_required=ent_req,
        entitlements_descriptions=ent_desc,
        itroles_required=it_req,
        itroles_descriptions=it_desc,
    )
