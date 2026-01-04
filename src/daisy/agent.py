# src/daisy/agent.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any, Union

import pandas as pd
import re

from .models import CheckResult, SectionResult, ReviewResult
from .pdf_reader import PdfDoc, find_referenced_xlsx_filenames
from .util import find_first_value_after_labels, extract_yes_no, list_existing_files
from .excel_checks import (
    read_excel_first_sheet,
    check_required_columns_non_empty,
    check_meaningful_descriptions,
)
from .rules import load_rules, Rules
from .ocr import ocr_pdf_pages_best_effort


class _PdfOverlayView:
    """
    Overlay OCR text for specific pages when base PDF text is empty/weak.
    Preserves PdfDoc interface used by validate().
    """

    def __init__(self, base: PdfDoc, ocr_pages: Dict[int, str]):
        self._base = base
        self._ocr_pages = {int(k): (v or "") for k, v in (ocr_pages or {}).items()}

    def page_count(self) -> int:
        return self._base.page_count()

    def page_lines(self, i: int) -> List[str]:
        base_lines = self._base.page_lines(i)
        base_text = "\n".join(base_lines).strip()

        ocr_text = (self._ocr_pages.get(i) or "").strip()
        if not base_text and ocr_text:
            return [ln for ln in ocr_text.splitlines() if ln.strip()]

        return base_lines

    def all_text(self) -> str:
        chunks: List[str] = []
        for i in range(self.page_count()):
            chunks.append("\n".join(self.page_lines(i)))
        return "\n".join(chunks)

    def find_pages_containing(self, needle: str, case_insensitive: bool = True) -> List[int]:
        if not needle:
            return []
        n = needle.lower() if case_insensitive else needle
        out: List[int] = []
        for i in range(self.page_count()):
            t = "\n".join(self.page_lines(i))
            hay = t.lower() if case_insensitive else t
            if n in hay:
                out.append(i)
        return out


# =============================================================================
# Public API (CLI + backward compatible test API)
# =============================================================================

def validate(
    dac_pdf: Optional[Union[Path, str]] = None,
    evidence_dir: Optional[Union[Path, str]] = None,
    out_dir: Optional[Union[Path, str]] = None,
    lenient: bool = False,
    mvp: bool = False,
    rules_path: Optional[Union[Path, str]] = None,
    # OCR options
    ocr: bool = False,
    tesseract_cmd: Optional[str] = None,
    ocr_lang: str = "eng",
    ocr_dpi: int = 200,
    ocr_max_pages: int = 2,
    ocr_pages: Optional[List[int]] = None,
    # Debug
    debug_extract: bool = False,
    # --- Backward compatible args used by tests in this repo ---
    dac_paths: Optional[List[str]] = None,
    evidence_dirs: Optional[List[str]] = None,
    print_report: Optional[bool] = None,  # accepted but unused (CLI handles printing)
) -> ReviewResult:
    """
    Backward compatible validate():
    - New CLI calls validate(dac_pdf=..., evidence_dir=..., ...)
    - Old tests call validate(dac_paths=[...], evidence_dirs=[...], ...)
    """
    if dac_pdf is None and dac_paths:
        dac_pdf = dac_paths[0]
    if evidence_dir is None and evidence_dirs:
        evidence_dir = evidence_dirs[0]

    if dac_pdf is None or evidence_dir is None:
        raise ValueError("validate(): dac_pdf and evidence_dir are required")

    dac_pdf = Path(dac_pdf)
    evidence_dir = Path(evidence_dir)
    out_dir_final = Path(out_dir) if out_dir else None
    rules_path_p = Path(rules_path) if rules_path else None

    rules: Rules = load_rules(rules_path_p)

    debug_log: List[Dict[str, Any]] = []

    def dbg(event: str, **kv: Any) -> None:
        if not debug_extract:
            return
        debug_log.append({"event": event, **kv})

    # -------------------------------------------------------------------------
    # DAC PDF load + OPTIONAL OCR OVERLAY
    # -------------------------------------------------------------------------
    pdf_base = PdfDoc(dac_pdf)
    base_text = (pdf_base.all_text() or "").strip()
    base_chars = len(base_text)

    dac_ocr_meta: Dict[str, Any] = {
        "ocr_enabled": bool(ocr),
        "ocr_attempted": False,
        "ocr_succeeded": False,
        "base_text_chars": int(base_chars),
        "text_chars_after_ocr": int(base_chars),
        "ocr_pages_requested": ocr_pages,
    }

    pdf = pdf_base
    min_chars = int(getattr(rules.pdf_evidence, "min_text_chars", 200))

    # IMPORTANT CHANGE:
    # If user explicitly provided --ocr-pages, we OCR those pages even if base text is already above min_chars.
    user_forced_pages = bool(ocr_pages and len(ocr_pages) > 0)
    should_ocr_dac = bool(ocr) and (base_chars < min_chars or user_forced_pages)

    if should_ocr_dac:
        try:
            cache_dir = (out_dir_final if out_dir_final else Path("out")) / "ocr_cache"

            # Targeted DAC OCR selection
            pages_to_ocr: Optional[List[int]] = None
            if user_forced_pages:
                pages_to_ocr = sorted(set(int(x) for x in ocr_pages or [] if isinstance(x, int) and x >= 0))
                dbg("dac_ocr_pages_source", source="user", pages=pages_to_ocr)
            else:
                if base_chars > 0:
                    needles = [
                        "CMS Product ID",
                        "IT Asset ID",
                        "IT Asset Name",
                        "Application is",
                        "SoD relevant",
                        "Functional Area",
                        "upload the entitlement",
                        "Is Application a",
                        "critical and",
                        "important function",
                    ]
                    cand: List[int] = []
                    for n in needles:
                        cand.extend(pdf_base.find_pages_containing(n, True))
                    cand = sorted(set(cand))
                    if cand:
                        pages_to_ocr = cand[: max(1, int(ocr_max_pages))]
                        dbg("dac_ocr_pages_source", source="auto_from_text", candidates=cand, chosen=pages_to_ocr)

                if not pages_to_ocr:
                    pages_to_ocr = list(range(0, min(int(ocr_max_pages), pdf_base.page_count())))
                    dbg("dac_ocr_pages_source", source="fallback_first_pages", chosen=pages_to_ocr)

            ocr_page_map, meta = ocr_pdf_pages_best_effort(
                dac_pdf,
                cache_dir,
                tesseract_cmd=tesseract_cmd,
                lang=ocr_lang,
                dpi=ocr_dpi,
                max_pages=ocr_max_pages,
                pages=pages_to_ocr,
            )

            dac_ocr_meta.update(meta)
            dac_ocr_meta["ocr_attempted"] = True

            ocr_text_total = int(sum(len(v or "") for v in ocr_page_map.values()))
            text_after = base_chars + ocr_text_total
            dac_ocr_meta["text_chars_after_ocr"] = int(text_after)
            dac_ocr_meta["ocr_succeeded"] = bool(ocr_text_total > 0 and meta.get("ocr_succeeded") is True)
            dac_ocr_meta["ocr_pages_used"] = sorted(list(ocr_page_map.keys()))

            dbg("dac_ocr_result", base_chars=base_chars, ocr_text_chars=ocr_text_total, pages_used=dac_ocr_meta.get("ocr_pages_used"))

            if ocr_page_map and ocr_text_total > 0:
                pdf = _PdfOverlayView(pdf_base, ocr_page_map)

        except Exception as e:
            dac_ocr_meta["error"] = f"{type(e).__name__}: {e}"
            dbg("dac_ocr_error", error=dac_ocr_meta["error"])

    all_text = pdf.all_text()
    referenced_xlsx = find_referenced_xlsx_filenames(all_text)

    # -------------------------------------------------------------------------
    # Section 1.1 General Information
    # -------------------------------------------------------------------------
    sec11_checks: List[CheckResult] = []

    cms_id = _extract_value_global(pdf, ["CMS Product ID"])
    it_asset_id = _extract_value_global(pdf, ["IT Asset ID", "IT Asset ID:"])
    it_asset_name = _extract_value_global(pdf, ["IT Asset Name", "IT Asset Name:"])

    # typed regex first, then generic fallback
    if not cms_id:
        cms_id = _extract_cms_product_id(all_text) or _extract_value_from_text(all_text, ["CMS Product ID"])
        dbg("extract_fallback_value", field="cms_id", value=cms_id, method="cms_numeric_regex_then_generic")
    if not it_asset_id:
        it_asset_id = _extract_it_asset_id(all_text) or _extract_value_from_text(all_text, ["IT Asset ID", "IT Asset ID:"])
        dbg("extract_fallback_value", field="it_asset_id", value=it_asset_id, method="asset_id_regex_then_generic")
    if not it_asset_name:
        it_asset_name = _extract_it_asset_name(all_text) or _extract_value_from_text(all_text, ["IT Asset Name", "IT Asset Name:"])
        dbg("extract_fallback_value", field="it_asset_name", value=it_asset_name, method="asset_name_regex_then_generic")

    dbg("extract_1.1_values", cms_id=cms_id, it_asset_id=it_asset_id, it_asset_name=it_asset_name)

    sec11_checks += [
        _presence_check("S1.1-01", "CMS Product ID present", cms_id, severity="major"),
        _presence_check("S1.1-02", "IT Asset ID present", it_asset_id, severity="major"),
        _presence_check("S1.1-03", "IT Asset Name present", it_asset_name, severity="major"),
    ]
    sec11 = _aggregate_section("1.1", "General Information", sec11_checks)

    # -------------------------------------------------------------------------
    # Section 2.0 Process Evidence (PDFs)
    # -------------------------------------------------------------------------
    sec20_checks: List[CheckResult] = []
    expected_pdfs = rules.pdf_evidence.required_files

    for idx, fname in enumerate(expected_pdfs, start=1):
        check_id = f"S2.0-{idx:02d}"
        p = evidence_dir / fname
        if p.exists():
            sec20_checks.append(
                CheckResult(
                    check_id=check_id,
                    name=f"Evidence PDF present: {fname}",
                    status="MET",
                    severity="major",
                    evidence={"file": str(p)},
                )
            )
        else:
            if mvp:
                sec20_checks.append(
                    CheckResult(
                        check_id=check_id,
                        name=f"Evidence PDF present: {fname}",
                        status="SKIPPED",
                        severity="major",
                        message="MVP: evidence PDF missing; skipping.",
                        evidence={"expected": fname},
                    )
                )
            else:
                sec20_checks.append(
                    CheckResult(
                        check_id=check_id,
                        name=f"Evidence PDF present: {fname}",
                        status="NOT_MET",
                        severity="major",
                        message="Evidence PDF not found in evidence directory.",
                        evidence={"expected": fname},
                    )
                )

    for idx, fname in enumerate(expected_pdfs, start=1):
        base_id = f"S2.0-{idx:02d}"
        p = evidence_dir / fname
        if not p.exists():
            continue

        ok_text, meta = _pdf_text_and_ocr_meta(
            p,
            min_chars=rules.pdf_evidence.min_text_chars,
            ocr_image_threshold=rules.pdf_evidence.ocr_image_threshold,
            ocr=ocr,
            out_dir=(out_dir_final if out_dir_final else Path("out")),
            tesseract_cmd=tesseract_cmd,
            ocr_lang=ocr_lang,
            ocr_dpi=ocr_dpi,
            ocr_max_pages=ocr_max_pages,
        )

        if ok_text:
            sec20_checks.append(
                CheckResult(
                    check_id=f"{base_id}-TXT",
                    name=f"Evidence PDF has extractable text: {fname}",
                    status="MET",
                    severity="major",
                    evidence={"file": str(p), **meta},
                )
            )
        else:
            msg = "PDF has very little/no extractable text."
            if meta.get("ocr_required") is True:
                msg = "OCR required: PDF appears scanned/image-based (no/low extractable text)."

            if mvp:
                sec20_checks.append(
                    CheckResult(
                        check_id=f"{base_id}-TXT",
                        name=f"Evidence PDF has extractable text: {fname}",
                        status="MET",
                        severity="major",
                        message=f"MVP warning: {msg}",
                        evidence={"file": str(p), **meta},
                    )
                )
            else:
                sec20_checks.append(
                    CheckResult(
                        check_id=f"{base_id}-TXT",
                        name=f"Evidence PDF has extractable text: {fname}",
                        status="NOT_MET",
                        severity="major",
                        message=msg,
                        evidence={"file": str(p), **meta},
                    )
                )

    sec20 = _aggregate_section("2.0", "Process Evidence (PDFs)", sec20_checks)

    # -------------------------------------------------------------------------
    # Section 4.1 Entitlements
    # -------------------------------------------------------------------------
    sec41_checks: List[CheckResult] = []

    cand_pages = set()
    cand_pages.update(pdf.find_pages_containing("Application is", True))
    cand_pages.update(pdf.find_pages_containing("SoD relevant", True))
    cand_pages.update(pdf.find_pages_containing("Functional Area", True))
    cand_pages.update(pdf.find_pages_containing("upload the", True))
    cand_pages = set(int(x) for x in cand_pages if isinstance(x, int) and x >= 0)
    cand_list = sorted(cand_pages)

    dbg("sec4.1_candidate_pages", pages=cand_list)

    sod_value: Optional[str] = None
    fa_value: Optional[str] = None
    upload_value: Optional[str] = None

    for pi in cand_list:
        lines = pdf.page_lines(pi)

        if sod_value is None:
            v = extract_yes_no(find_first_value_after_labels(lines, ["SoD relevant?", "Application is", "Application is SoD relevant?"]))
            v = v or extract_yes_no(_extract_stack_label_value(lines, ["Application is", "SoD relevant?"]))
            if v:
                sod_value = v
                dbg("sec4.1_extract", field="sod", page=pi, value=sod_value, method="page_lines")

        if fa_value is None:
            v = extract_yes_no(_extract_stack_label_value(lines, ["Functional Area", "relevant?"]))
            v = v or extract_yes_no(find_first_value_after_labels(lines, ["Functional Area relevant?"]))
            if v:
                fa_value = v
                dbg("sec4.1_extract", field="fa", page=pi, value=fa_value, method="page_lines")

        if upload_value is None:
            v = extract_yes_no(_extract_stack_label_value(lines, ["Do you want to", "upload the", "entitlement", "composition?"]))
            v = v or extract_yes_no(find_first_value_after_labels(lines, ["upload the entitlement composition"]))
            if v:
                upload_value = v
                dbg("sec4.1_extract", field="upload", page=pi, value=upload_value, method="page_lines")

        if sod_value and fa_value and upload_value:
            break

    if sod_value is None:
        sod_value = _extract_yes_no_near(all_text, [r"SoD\s+relevant\??", r"Application\s+is.*SoD\s+relevant"])
        dbg("sec4.1_extract", field="sod", value=sod_value, method="text_near")
    if fa_value is None:
        fa_value = _extract_yes_no_near(all_text, [r"Functional\s+Area.*relevant\??"])
        dbg("sec4.1_extract", field="fa", value=fa_value, method="text_near")
    if upload_value is None:
        upload_value = _extract_yes_no_near(all_text, [r"upload\s+the\s+entitlement\s+composition"])
        dbg("sec4.1_extract", field="upload", value=upload_value, method="text_near")

    sec41_checks += [
        _yn_check("S4.1-01", "SoD relevancy recorded (yes/no)", sod_value, severity="critical", lenient=lenient),
        _yn_check("S4.1-02", "Functional Area relevancy recorded (yes/no)", fa_value, severity="major", lenient=lenient),
        _yn_check("S4.1-03", "Entitlement composition upload decision recorded (yes/no)", upload_value, severity="major", lenient=lenient),
    ]

    expected_41 = ["Entitlement Services.xlsx", "All Entitlements.xlsx"]
    for i, exp in enumerate(expected_41, start=1):
        sec41_checks.append(_export_exists_check(f"S4.1-F{i:02d}", f"Export present: {exp}", referenced_xlsx, evidence_dir, exp))

    es_path = _find_export_file(evidence_dir, referenced_xlsx, "Entitlement Services.xlsx")
    if es_path:
        df_es = read_excel_first_sheet(es_path)

        f1 = check_required_columns_non_empty(
            df_es,
            required_cols=["Display name", "Description", "SoD Area", "Tier Level"],
            id_col="Display name",
        )

        sev_41_req = rules.entitlements_required.mvp_severity if mvp else rules.entitlements_required.non_mvp_severity
        sev_41_req = sev_41_req or rules.entitlements_required.severity

        sec41_checks.append(
            _excel_finding_check_threshold(
                "S4.1-EX-01",
                "Entitlement Services: required master data filled",
                f1,
                severity=sev_41_req,
                mvp=mvp,
                ratio_tol=rules.entitlements_required.ratio_tol,
                abs_tol=rules.entitlements_required.abs_tol,
            )
        )

        f2 = check_meaningful_descriptions(df_es, "Display name", "Description")
        sec41_checks.append(
            _excel_finding_check_threshold(
                "S4.1-EX-02",
                "Entitlement Services: descriptions are meaningful",
                f2,
                severity=rules.entitlements_descriptions.severity,
                mvp=mvp,
                ratio_tol=rules.entitlements_descriptions.ratio_tol,
                abs_tol=rules.entitlements_descriptions.abs_tol,
            )
        )
    else:
        sec41_checks.append(
            CheckResult(
                check_id="S4.1-EX-01",
                name="Entitlement Services: required master data filled",
                status="SKIPPED",
                severity=(rules.entitlements_required.mvp_severity or "major") if mvp else (rules.entitlements_required.non_mvp_severity or "critical"),
                message="Skipped because Entitlement Services export was not found.",
            )
        )

    if fa_value == "yes":
        fa_ok = False
        fa_evidence: Dict[str, Any] = {}

        if es_path:
            df_es2 = read_excel_first_sheet(es_path)
            if "Functional Area" in df_es2.columns:
                non_empty = df_es2["Functional Area"].fillna("").astype(str).str.strip().ne("").sum()
                fa_evidence["entitlement_services_fa_non_empty_rows"] = int(non_empty)
                fa_ok = fa_ok or (non_empty > 0)

        ae_path = _find_export_file(evidence_dir, referenced_xlsx, "All Entitlements.xlsx")
        if ae_path:
            df_ae = read_excel_first_sheet(ae_path)
            if "DBG Functional Area" in df_ae.columns:
                non_empty = df_ae["DBG Functional Area"].fillna("").astype(str).str.strip().ne("").sum()
                fa_evidence["all_entitlements_dbg_fa_non_empty_rows"] = int(non_empty)
                fa_ok = fa_ok or (non_empty > 0)

        sec41_checks.append(
            CheckResult(
                check_id="S4.1-EX-FA",
                name="Functional Area populated when FA relevancy = yes (Entitlement Services OR All Entitlements)",
                status="MET" if fa_ok else ("MET" if mvp else "NOT_MET"),
                severity="major" if mvp else "critical",
                message="" if fa_ok else ("MVP: Treating as warning." if mvp else "FA relevancy is yes, but Functional Area is empty in both Entitlement Services and All Entitlements."),
                evidence=fa_evidence,
            )
        )

    sec41 = _aggregate_section("4.1", "Entitlements", sec41_checks)

    # -------------------------------------------------------------------------
    # Section 4.2 IT Roles
    # -------------------------------------------------------------------------
    sec42_checks: List[CheckResult] = []

    cand_pages2 = set()
    cand_pages2.update(pdf.find_pages_containing("Is Application a", True))
    cand_pages2.update(pdf.find_pages_containing("critical and", True))
    cand_pages2.update(pdf.find_pages_containing("important", True))
    cand2 = sorted(set(int(x) for x in cand_pages2 if isinstance(x, int) and x >= 0))
    dbg("sec4.2_candidate_pages", pages=cand2)

    cif_value: Optional[str] = None

    for pi in cand2:
        lines = pdf.page_lines(pi)
        v = extract_yes_no(find_first_value_after_labels(lines, ["Is Application a", "critical and", "important"]))
        v = v or extract_yes_no(_extract_stack_label_value(lines, ["Is Application a", "critical and", "important"]))
        if v:
            cif_value = v
            dbg("sec4.2_extract", field="cif", page=pi, value=cif_value, method="page_lines")
            break

    if cif_value is None:
        cif_value = _extract_yes_no_near(all_text, [r"Is\s+Application\s+a.*critical.*important"])
        dbg("sec4.2_extract", field="cif", value=cif_value, method="text_near")

    sec42_checks.append(_yn_check("S4.2-01", "CIF (critical & important function) recorded (yes/no)", cif_value, severity="major", lenient=lenient))

    expected_42 = [
        "IT Role Services.xlsx",
        "All my Roles.xlsx",
        "All my Application Roles.xlsx",
        "All my IT Roles without Application Role.xlsx",
    ]
    for i, exp in enumerate(expected_42, start=1):
        sec42_checks.append(_export_exists_check(f"S4.2-F{i:02d}", f"Export present: {exp}", referenced_xlsx, evidence_dir, exp))

    itrs_path = _find_export_file(evidence_dir, referenced_xlsx, "IT Role Services.xlsx")
    if itrs_path:
        df = read_excel_first_sheet(itrs_path)

        base_required = ["Display name", "Description", "Tier Level"]
        missing_base = [c for c in base_required if c not in df.columns]
        if missing_base:
            sec42_checks.append(
                CheckResult(
                    check_id="S4.2-EX-01",
                    name="IT Role Services: required master data filled",
                    status=("MET" if mvp else "NOT_MET"),
                    severity="major" if mvp else "critical",
                    message=("MVP: missing columns but not blocking." if mvp else f"Missing required columns: {missing_base}"),
                    evidence={"missing_columns": missing_base},
                )
            )
        else:
            owner_cols = [c for c in ["IT Role Owner", "cust_owner", "Application Owner"] if c in df.columns]

            base_ok = (
                df["Display name"].fillna("").astype(str).str.strip().ne("")
                & df["Description"].fillna("").astype(str).str.strip().ne("")
                & df["Tier Level"].notna()
            )

            if owner_cols:
                owner_ok = df[owner_cols].fillna("").astype(str).apply(lambda r: any(v.strip() for v in r), axis=1)
            else:
                owner_ok = pd.Series(True, index=df.index)

            ok = base_ok & owner_ok

            failing_count = int((~ok).sum())
            failing = df.loc[~ok].head(5)
            sample_cols = [c for c in (base_required + owner_cols) if c in df.columns]

            sev_42_req = rules.itroles_required.mvp_severity if mvp else rules.itroles_required.non_mvp_severity
            sev_42_req = sev_42_req or rules.itroles_required.severity

            sec42_checks.append(
                _simple_threshold_check(
                    check_id="S4.2-EX-01",
                    name="IT Role Services: required master data filled (base + owner fallback)",
                    failing_count=failing_count,
                    total=len(df),
                    severity=sev_42_req,
                    mvp=mvp,
                    ratio_tol=rules.itroles_required.ratio_tol,
                    abs_tol=rules.itroles_required.abs_tol,
                    evidence={
                        "total_rows": int(len(df)),
                        "failing_rows": failing_count,
                        "owner_cols_used": owner_cols,
                        "samples": failing[sample_cols].to_dict(orient="records"),
                    },
                )
            )

        f2 = check_meaningful_descriptions(df, "Display name", "Description")
        sec42_checks.append(
            _excel_finding_check_threshold(
                "S4.2-EX-02",
                "IT Role Services: descriptions are meaningful",
                f2,
                severity=rules.itroles_descriptions.severity,
                mvp=mvp,
                ratio_tol=rules.itroles_descriptions.ratio_tol,
                abs_tol=rules.itroles_descriptions.abs_tol,
            )
        )
    else:
        sec42_checks.append(
            CheckResult(
                check_id="S4.2-EX-01",
                name="IT Role Services: required master data filled",
                status="SKIPPED",
                severity="major" if mvp else "critical",
                message="Skipped because IT Role Services export was not found.",
            )
        )

    sec42 = _aggregate_section("4.2", "IT Roles", sec42_checks)

    # -------------------------------------------------------------------------
    # Section 4.3 Special Accounts
    # -------------------------------------------------------------------------
    sec43_checks: List[CheckResult] = []
    if mvp:
        sa_path = _find_export_file(evidence_dir, referenced_xlsx, "Special Accounts Services.xlsx")
        referenced = any(r.lower().endswith("special accounts services.xlsx") for r in referenced_xlsx)
        if sa_path:
            sec43_checks.append(
                CheckResult(
                    check_id="S4.3-01",
                    name="Export present: Special Accounts Services.xlsx",
                    status="MET",
                    severity="major",
                    evidence={"file": str(sa_path)},
                )
            )
        else:
            sec43_checks.append(
                CheckResult(
                    check_id="S4.3-01",
                    name="Export present: Special Accounts Services.xlsx",
                    status="SKIPPED",
                    severity="major",
                    message="MVP: Special Accounts export not provided; skipping (still recommended to include for full validation).",
                    evidence={"expected": "Special Accounts Services.xlsx", "referenced_by_pdf": referenced},
                )
            )
    else:
        sec43_checks.append(
            _export_exists_check(
                "S4.3-01",
                "Export present: Special Accounts Services.xlsx",
                referenced_xlsx,
                evidence_dir,
                "Special Accounts Services.xlsx",
                severity="major",
            )
        )
    sec43 = _aggregate_section("4.3", "Special Accounts", sec43_checks)

    # -------------------------------------------------------------------------
    # Section 4.4 SoD
    # -------------------------------------------------------------------------
    sec44_checks: List[CheckResult] = []
    fam_path = _find_export_file(evidence_dir, referenced_xlsx, "Functional Area Matrix.xlsx")
    if sod_value == "yes":
        sec44_checks.append(_file_exists("S4.4-01", "Functional Area Matrix.xlsx present when SoD relevant", fam_path, severity="major"))
    else:
        sec44_checks.append(
            CheckResult(
                check_id="S4.4-01",
                name="Functional Area Matrix.xlsx present when SoD relevant",
                status="SKIPPED",
                severity="major",
                message="Skipped because SoD relevancy is not 'yes' (or could not be extracted).",
            )
        )
    sec44 = _aggregate_section("4.4", "Segregation of Duties", sec44_checks)

    # -------------------------------------------------------------------------
    # Assemble
    # -------------------------------------------------------------------------
    sections = [sec11, sec20, sec41, sec42, sec43, sec44]
    overall = _aggregate_overall(sections)
    recommendations = _recommendations_from_sections(sections)

    stats: Dict[str, Any] = {
        "referenced_xlsx": referenced_xlsx,
        "evidence_dir_files": list_existing_files(evidence_dir),
        "dac_ocr": dac_ocr_meta,
    }

    if debug_extract:
        stats["extract_debug_events"] = debug_log

    result = ReviewResult(
        dac_file=str(dac_pdf),
        generated_at=ReviewResult.now_iso(),
        overall_status=overall,
        sections=sections,
        recommendations=recommendations,
        stats=stats,
    )

    if out_dir_final:
        out_dir_final.mkdir(parents=True, exist_ok=True)
        (out_dir_final / "review_result.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        (out_dir_final / "review_result.md").write_text(_to_markdown(result), encoding="utf-8")
        if debug_extract:
            (out_dir_final / "extract_debug.json").write_text(json.dumps(debug_log, indent=2), encoding="utf-8")

    return result


# =============================================================================
# Evidence PDF: extractable text + OCR-required detection + OPTIONAL OCR
# =============================================================================

def _pdf_text_and_ocr_meta(
    pdf_path: Path,
    min_chars: int,
    ocr_image_threshold: int,
    *,
    ocr: bool,
    out_dir: Path,
    tesseract_cmd: Optional[str],
    ocr_lang: str,
    ocr_dpi: int,
    ocr_max_pages: int,
) -> Tuple[bool, dict]:
    """
    Returns (text_ok, meta).
    If OCR is enabled and required, attempt OCR (best-effort) on up to ocr_max_pages.
    """
    text_chars = 0
    page_count = 0
    image_count = 0
    err: Optional[str] = None

    try:
        d = PdfDoc(pdf_path)
        page_count = d.page_count()
        t = (d.all_text() or "").strip()
        text_chars = len(t)
    except Exception as e:
        err = f"text_extract_error: {e}"

    # Image count via PyMuPDF directly (best-effort)
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        for i in range(len(doc)):
            try:
                page = doc.load_page(i)
                imgs = page.get_images(full=True)
                image_count += len(imgs)
            except Exception:
                continue
        doc.close()
    except Exception as e:
        if err is None:
            err = f"image_detect_error: {e}"

    meta: Dict[str, Any] = {
        "page_count": page_count,
        "text_chars": text_chars,
        "image_count": image_count,
        "ocr_enabled": bool(ocr),
    }
    if err:
        meta["error"] = err

    text_ok = text_chars >= max(0, int(min_chars))
    ocr_required = (not text_ok) and (image_count >= max(0, int(ocr_image_threshold)))
    meta["ocr_required"] = bool(ocr_required)

    if ocr and ocr_required:
        cache_dir = Path(out_dir) / "ocr_cache"
        pages_to_ocr = list(range(0, min(int(ocr_max_pages), int(page_count or 0))))
        ocr_pages_map, ocr_meta = ocr_pdf_pages_best_effort(
            pdf_path,
            cache_dir,
            tesseract_cmd=tesseract_cmd,
            lang=ocr_lang,
            dpi=ocr_dpi,
            max_pages=ocr_max_pages,
            pages=pages_to_ocr,
        )
        meta.update(ocr_meta)

        ocr_chars = int(sum(len(v or "") for v in ocr_pages_map.values()))
        meta["text_chars_after_ocr"] = int(ocr_chars)
        meta["ocr_succeeded"] = bool(ocr_chars > 0 and ocr_meta.get("ocr_succeeded") is True)
        if ocr_chars >= max(0, int(min_chars)):
            text_ok = True

    else:
        meta["ocr_available"] = False
        meta["ocr_attempted"] = False

    return text_ok, meta


# =============================================================================
# Helpers
# =============================================================================

def _extract_stack_label_value(lines: List[str], label_stack: List[str]) -> Optional[str]:
    low = [l.strip() for l in lines]
    for i in range(len(low)):
        ok = True
        for k, lab in enumerate(label_stack):
            if i + k >= len(low) or lab.lower() not in low[i + k].lower():
                ok = False
                break
        if ok:
            for j in range(i + len(label_stack), min(i + len(label_stack) + 6, len(low))):
                v = low[j].strip()
                if v:
                    return v
    return None


def _extract_value_global(pdf, label_variants: List[str]) -> Optional[str]:
    for i in range(pdf.page_count()):
        lines = pdf.page_lines(i)
        v = find_first_value_after_labels(lines, label_variants)
        if v:
            if any(v.lower().startswith(lab.lower()) for lab in label_variants):
                continue
            return v
    return None


def _presence_check(check_id: str, name: str, value: Optional[str], severity: str = "major") -> CheckResult:
    if value and str(value).strip():
        return CheckResult(check_id=check_id, name=name, status="MET", severity=severity, evidence={"value": value})
    return CheckResult(check_id=check_id, name=name, status="NOT_MET", severity=severity, message="Value missing or empty.")


def _yn_check(check_id: str, name: str, yn: Optional[str], severity: str = "major", lenient: bool = False) -> CheckResult:
    if yn in {"yes", "no"}:
        return CheckResult(check_id=check_id, name=name, status="MET", severity=severity, evidence={"value": yn})
    if lenient:
        return CheckResult(
            check_id=check_id,
            name=name,
            status="SKIPPED",
            severity=severity,
            message="Missing/unparseable yes/no in DAC PDF (lenient mode).",
        )
    return CheckResult(check_id=check_id, name=name, status="NOT_MET", severity=severity, message="Expected yes/no but value is missing or not parseable.")


def _file_exists(check_id: str, name: str, file_path: Optional[Path], severity: str = "major") -> CheckResult:
    if file_path and file_path.exists():
        return CheckResult(check_id=check_id, name=name, status="MET", severity=severity, evidence={"file": str(file_path)})
    return CheckResult(check_id=check_id, name=name, status="NOT_MET", severity=severity, message="Required file not found.")


def _export_exists_check(
    check_id: str,
    name: str,
    referenced_xlsx: List[str],
    evidence_dir: Path,
    expected_suffix: str,
    severity: str = "major",
) -> CheckResult:
    path = _find_export_file(evidence_dir, referenced_xlsx, expected_suffix)
    if path:
        return CheckResult(check_id=check_id, name=name, status="MET", severity=severity, evidence={"file": str(path)})

    referenced = any(r.lower().endswith(expected_suffix.lower()) for r in referenced_xlsx)
    msg = "Export file not found in evidence directory."
    if referenced:
        msg += " (Referenced by DAC PDF.)"
    return CheckResult(check_id=check_id, name=name, status="NOT_MET", severity=severity, message=msg, evidence={"expected": expected_suffix, "referenced_by_pdf": referenced})


def _find_export_file(evidence_dir: Path, referenced_xlsx: List[str], expected_suffix: str) -> Optional[Path]:
    for r in referenced_xlsx:
        if r.lower().endswith(expected_suffix.lower()):
            p = evidence_dir / r
            if p.exists():
                return p

    if evidence_dir.exists():
        for p in evidence_dir.glob("*.xlsx"):
            if p.name.lower().endswith(expected_suffix.lower()):
                return p
    return None


def _excel_finding_check_threshold(
    check_id: str,
    name: str,
    finding,
    severity: str,
    mvp: bool,
    ratio_tol: float,
    abs_tol: int,
) -> CheckResult:
    total = int(finding.total_rows)
    failing = int(finding.failing_rows)

    if failing == 0:
        return CheckResult(check_id=check_id, name=name, status="MET", severity=severity, evidence={"total_rows": total})

    tol = max(int(abs_tol), int(total * float(ratio_tol)))
    if mvp and failing <= tol:
        return CheckResult(
            check_id=check_id,
            name=name,
            status="MET",
            severity=severity,
            message=f"MVP warning: {failing} of {total} rows failed (tolerance={tol}).",
            evidence={"total_rows": total, "failing_rows": failing, "samples": finding.sample_rows},
        )

    return CheckResult(
        check_id=check_id,
        name=name,
        status="NOT_MET",
        severity=severity,
        message=f"{failing} of {total} rows failed.",
        evidence={"total_rows": total, "failing_rows": failing, "samples": finding.sample_rows},
    )


def _simple_threshold_check(
    check_id: str,
    name: str,
    failing_count: int,
    total: int,
    severity: str,
    mvp: bool,
    ratio_tol: float,
    abs_tol: int,
    evidence: dict,
) -> CheckResult:
    if failing_count == 0:
        return CheckResult(check_id=check_id, name=name, status="MET", severity=severity, evidence=evidence)

    tol = max(int(abs_tol), int(total * float(ratio_tol)))
    if mvp and failing_count <= tol:
        return CheckResult(
            check_id=check_id,
            name=name,
            status="MET",
            severity=severity,
            message=f"MVP warning: {failing_count} of {total} rows failed (tolerance={tol}).",
            evidence=evidence,
        )

    return CheckResult(
        check_id=check_id,
        name=name,
        status="NOT_MET",
        severity=severity,
        message=f"{failing_count} of {total} rows failed.",
        evidence=evidence,
    )


def _aggregate_section(section_id: str, name: str, checks: List[CheckResult]) -> SectionResult:
    crit_not = any(c.status == "NOT_MET" and c.severity == "critical" for c in checks)
    any_not = any(c.status == "NOT_MET" for c in checks)
    any_met = any(c.status == "MET" for c in checks)
    any_unknown = any(c.status == "UNKNOWN" for c in checks)
    any_skipped = any(c.status == "SKIPPED" for c in checks)

    if crit_not:
        status = "NOT_MET"
    elif any_not and any_met:
        status = "PARTIALLY_MET"
    elif any_not and not any_met:
        status = "NOT_MET"
    elif any_met and (any_skipped or any_unknown):
        status = "PARTIALLY_MET"
    elif any_met:
        status = "MET"
    else:
        status = "UNKNOWN"

    return SectionResult(section_id=section_id, name=name, status=status, checks=checks)


def _aggregate_overall(sections: List[SectionResult]) -> str:
    if any(s.status == "NOT_MET" for s in sections):
        if all(s.status == "NOT_MET" for s in sections):
            return "NOT_MET"
        return "PARTIALLY_MET"
    if any(s.status == "PARTIALLY_MET" for s in sections):
        return "PARTIALLY_MET"
    if all(s.status == "MET" for s in sections):
        return "MET"
    return "UNKNOWN"


def _recommendations_from_sections(sections: List[SectionResult]) -> List[str]:
    recs: List[str] = []
    for s in sections:
        for c in s.checks:
            if c.status == "NOT_MET":
                recs.append(f"[{s.section_id}] {c.name}: {c.message or 'Fix missing/invalid evidence.'}")
    return recs


def _to_markdown(result: ReviewResult) -> str:
    lines: List[str] = []
    lines.append("# Daisy DAC Review Result\n")
    lines.append(f"- DAC: `{result.dac_file}`")
    lines.append(f"- Generated at: `{result.generated_at}`")
    lines.append(f"- Overall: **{result.overall_status}**\n")
    lines.append("## Sections\n")
    for s in result.sections:
        lines.append(f"### {s.section_id} {s.name} — **{s.status}**\n")
        for c in s.checks:
            lines.append(f"- `{c.check_id}` **{c.status}** ({c.severity}) — {c.name}")
            if c.message:
                lines.append(f"  - {c.message}")
            if c.evidence:
                ev = json.dumps(c.evidence, ensure_ascii=False)
                if len(ev) > 600:
                    ev = ev[:600] + "…"
                lines.append(f"  - evidence: `{ev}`")
        lines.append("")
    if result.recommendations:
        lines.append("## Recommendations\n")
        for r in result.recommendations[:200]:
            lines.append(f"- {r}")
        lines.append("")
    return "\n".join(lines)


# =============================================================================
# OCR-friendly extraction helpers
# =============================================================================

def _normalize_text(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    return s


def _extract_cms_product_id(text: str) -> Optional[str]:
    if not text:
        return None
    t = _normalize_text(text)
    m = re.search(r"(?i)\bCMS\s*Product\s*ID\b[^0-9]{0,40}(\d{4,})", t)
    return m.group(1) if m else None


def _extract_it_asset_id(text: str) -> Optional[str]:
    if not text:
        return None
    t = _normalize_text(text)
    m = re.search(r"(?i)\bIT\s*Asset\s*ID\b[^A-Za-z0-9]{0,40}([A-Za-z0-9_-]{2,})", t)
    return m.group(1) if m else None


def _extract_it_asset_name(text: str) -> Optional[str]:
    if not text:
        return None
    t = _normalize_text(text)
    m = re.search(r"(?im)^\s*IT\s*Asset\s*Name\b\s*:?\s*(.+?)\s*$", t)
    if m:
        v = (m.group(1) or "").strip()
        if v and not re.search(r"(?i)\bCMS\s*Product\s*ID\b|\bIT\s*Asset\s*ID\b", v):
            return v[:200]
    m2 = re.search(r"(?i)\bIT\s*Asset\s*Name\b\s*:?\s*([A-Za-z0-9 _\-/().]{3,200})", t)
    if m2:
        v = (m2.group(1) or "").strip()
        if v and not re.search(r"(?i)\bCMS\s*Product\s*ID\b|\bIT\s*Asset\s*ID\b", v):
            return v[:200]
    return None


def _extract_value_from_text(text: str, label_variants: List[str]) -> Optional[str]:
    if not text:
        return None

    t = _normalize_text(text)
    lines = [ln.strip() for ln in t.split("\n")]

    for lab in label_variants:
        pat = re.compile(rf"(?i)\b{re.escape(lab).rstrip(':')}\b\s*:?\s*(.+)$")
        for ln in lines:
            m = pat.search(ln)
            if m:
                v = (m.group(1) or "").strip()
                if v and not any(v.lower().startswith(x.lower().rstrip(":")) for x in label_variants):
                    return v[:200]

    lows = [ln.lower() for ln in lines]
    labs_low = [lv.lower().rstrip(":") for lv in label_variants]
    for i, ln in enumerate(lows):
        for lab in labs_low:
            if lab in ln:
                for j in range(i + 1, min(i + 6, len(lines))):
                    v = lines[j].strip()
                    if v and not any(v.lower().startswith(x.lower()) for x in labs_low):
                        return v[:200]
    return None


def _extract_yes_no_near(text: str, label_patterns: List[str], window: int = 250) -> Optional[str]:
    """
    IMPORTANT FIX:
    Only scan AFTER the label match, so earlier 'y' tokens don't contaminate later questions.
    """
    if not text:
        return None
    t = _normalize_text(text)

    for pat in label_patterns:
        for m in re.finditer(pat, t, flags=re.IGNORECASE):
            start = m.end()
            end = min(len(t), m.end() + window)
            chunk = t[start:end]
            yn = extract_yes_no(chunk)
            if yn in {"yes", "no"}:
                return yn

    return None
