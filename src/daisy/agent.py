from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import pandas as pd

from .models import CheckResult, SectionResult, ReviewResult
from .pdf_reader import PdfDoc, find_referenced_xlsx_filenames
from .util import (
    find_first_value_after_labels,
    extract_yes_no,
    list_existing_files,
    sanitize_json,
)
from .excel_checks import (
    read_excel_first_sheet,
    check_required_columns_non_empty,
    check_meaningful_descriptions,
)
from .rules import load_rules, Rules, PdfContentRule


def validate(
    dac_pdf: Path,
    evidence_dir: Path,
    out_dir: Optional[Path] = None,
    lenient: bool = False,
    mvp: bool = False,
    rules_path: Optional[Path] = None,
    # OCR options (driven by CLI)
    ocr: bool = False,
    ocr_lang: str = "eng",
    ocr_dpi: int = 200,
    ocr_max_pages: Optional[int] = 2,
    tesseract_cmd: Optional[str] = None,
) -> ReviewResult:
    dac_pdf = Path(dac_pdf)
    evidence_dir = Path(evidence_dir)

    rules: Rules = load_rules(rules_path)

    pdf = PdfDoc(dac_pdf)
    all_text = pdf.all_text()

    referenced_xlsx = find_referenced_xlsx_filenames(all_text)

    # Simple per-run cache so we don't re-OCR the same PDF multiple times
    pdf_text_cache: Dict[str, Tuple[str, bool, Dict[str, Any]]] = {}

    def get_pdf_text_meta(p: Path) -> Tuple[str, bool, Dict[str, Any]]:
        k = str(p.resolve())
        if k in pdf_text_cache:
            return pdf_text_cache[k]
        used_text, ok_text, meta = _pdf_text_and_ocr_meta(
            pdf_path=p,
            out_dir=out_dir,
            min_chars=rules.pdf_evidence.min_text_chars,
            ocr_image_threshold=rules.pdf_evidence.ocr_image_threshold,
            ocr_enabled=bool(ocr),
            ocr_lang=str(ocr_lang or "eng"),
            ocr_dpi=int(ocr_dpi or 200),
            ocr_max_pages=ocr_max_pages,
            tesseract_cmd=tesseract_cmd,
        )
        pdf_text_cache[k] = (used_text, ok_text, meta)
        return used_text, ok_text, meta

    # -------------------------------------------------------------------------
    # Section 1.1 General Information
    # -------------------------------------------------------------------------
    sec11_checks: List[CheckResult] = []
    cms_id = _extract_value_global(pdf, ["CMS Product ID"])
    it_asset_id = _extract_value_global(pdf, ["IT Asset ID", "IT Asset ID:"])
    it_asset_name = _extract_value_global(pdf, ["IT Asset Name", "IT Asset Name:"])

    sec11_checks += [
        _presence_check("S1.1-01", "CMS Product ID present", cms_id, severity="major"),
        _presence_check("S1.1-02", "IT Asset ID present", it_asset_id, severity="major"),
        _presence_check("S1.1-03", "IT Asset Name present", it_asset_name, severity="major"),
    ]
    sec11 = _aggregate_section("1.1", "General Information", sec11_checks)

    # -------------------------------------------------------------------------
    # Section 2.0 Process Evidence (PDFs)
    # - presence checks
    # - extractable text / OCR checks
    # - content_rules checks (regex/contains)
    # -------------------------------------------------------------------------
    sec20_checks: List[CheckResult] = []
    expected_pdfs = rules.pdf_evidence.required_files

    # Presence
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

    # Text / OCR meta check per PDF
    for idx, fname in enumerate(expected_pdfs, start=1):
        base_id = f"S2.0-{idx:02d}"
        p = evidence_dir / fname
        if not p.exists():
            continue

        _txt, ok_text, meta = get_pdf_text_meta(p)

        if ok_text:
            sec20_checks.append(
                CheckResult(
                    check_id=f"{base_id}-TXT",
                    name=f"Evidence PDF has extractable text: {fname}",
                    status="MET",
                    severity="major",
                    message="",
                    evidence={"file": str(p), **meta},
                )
            )
        else:
            if meta.get("ocr_required") is True:
                msg = "OCR required: PDF appears scanned/image-based (no/low extractable text)."
            else:
                msg = "PDF has very little/no extractable text."

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

    # Content rules (regex / contains) driven by rules.yaml
    content_rules = getattr(rules.pdf_evidence, "content_rules", {}) or {}
    if isinstance(content_rules, dict) and content_rules:
        for fname, rules_list in content_rules.items():
            p = evidence_dir / fname
            if not p.exists():
                # Don't duplicate the "missing file" error; presence check already covers it.
                continue

            used_text, _ok_text, meta = get_pdf_text_meta(p)

            if not isinstance(rules_list, list):
                continue

            for rule in rules_list:
                if not isinstance(rule, PdfContentRule):
                    # Defensive (should not happen if rules.py parses correctly)
                    continue

                rid = rule.id
                rname = rule.name or rid
                rtype = (rule.type or "regex").strip().lower()
                severity = rule.severity or "major"

                matched = False
                snippet = ""
                err = None

                try:
                    if rtype == "contains":
                        needle = (rule.contains or "").strip()
                        matched = bool(needle) and (needle.lower() in (used_text or "").lower())
                        snippet = needle if matched else ""
                    else:
                        pat = rule.pattern or ""
                        if pat:
                            m = re.search(pat, used_text or "")
                            matched = m is not None
                            if m is not None:
                                s = (used_text or "")[max(0, m.start() - 60) : m.end() + 60]
                                snippet = re.sub(r"\s+", " ", s).strip()[:200]
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"

                if err is not None:
                    status = "NOT_MET" if not mvp else "MET"
                    msg = f"Rule evaluation error: {err}" if not mvp else f"MVP warning: rule error ({rid}): {err}"
                else:
                    if matched:
                        status = "MET"
                        msg = ""
                    else:
                        status = "NOT_MET" if not mvp else "MET"
                        msg = "Content rule not met." if not mvp else f"MVP warning: content rule not met ({rid})."

                sec20_checks.append(
                    CheckResult(
                        check_id=f"S2.0-CONTENT-{rid}",
                        name=f"{fname}: {rname}",
                        status=status,
                        severity=severity,
                        message=msg,
                        evidence={
                            "file": str(p),
                            "rule_id": rid,
                            "rule_type": rtype,
                            "matched": bool(matched),
                            "snippet": snippet,
                            **meta,
                        },
                    )
                )

    sec20 = _aggregate_section("2.0", "Process Evidence (PDFs)", sec20_checks)

    # -------------------------------------------------------------------------
    # Section 4.1 Entitlements
    # -------------------------------------------------------------------------
    sec41_checks: List[CheckResult] = []

    p_idxs = pdf.find_pages_containing("Application is", True)
    sod_value = None
    fa_value = None
    upload_value = None

    if p_idxs:
        lines = pdf.page_lines(p_idxs[0])

        sod_value = extract_yes_no(
            find_first_value_after_labels(lines, ["SoD relevant?", "Application is", "Application is SoD relevant?"])
        )
        sod_value = sod_value or extract_yes_no(_extract_stack_label_value(lines, ["Application is", "SoD relevant?"]))

        fa_value = extract_yes_no(_extract_stack_label_value(lines, ["Functional Area", "relevant?"]))

        upload_value = extract_yes_no(
            _extract_stack_label_value(lines, ["Do you want to", "upload the", "entitlement", "composition?"])
        )

    sec41_checks += [
        _yn_check("S4.1-01", "SoD relevancy recorded (yes/no)", sod_value, severity="critical", lenient=lenient),
        _yn_check("S4.1-02", "Functional Area relevancy recorded (yes/no)", fa_value, severity="major", lenient=lenient),
        _yn_check(
            "S4.1-03",
            "Entitlement composition upload decision recorded (yes/no)",
            upload_value,
            severity="major",
            lenient=lenient,
        ),
    ]

    expected_41 = [
        "Entitlement Services.xlsx",
        "All Entitlements.xlsx",
    ]
    for i, exp in enumerate(expected_41, start=1):
        sec41_checks.append(
            _export_exists_check(f"S4.1-F{i:02d}", f"Export present: {exp}", referenced_xlsx, evidence_dir, exp)
        )

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
                severity=(rules.entitlements_required.mvp_severity or "major")
                if mvp
                else (rules.entitlements_required.non_mvp_severity or "critical"),
                message="Skipped because Entitlement Services export was not found.",
            )
        )

    if fa_value == "yes":
        fa_ok = False
        fa_evidence = {}

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
                message=""
                if fa_ok
                else (
                    "MVP: Treating as warning."
                    if mvp
                    else "FA relevancy is yes, but Functional Area is empty in both Entitlement Services and All Entitlements."
                ),
                evidence=fa_evidence,
            )
        )

    sec41 = _aggregate_section("4.1", "Entitlements", sec41_checks)

    # -------------------------------------------------------------------------
    # Section 4.2 IT Roles
    # -------------------------------------------------------------------------
    sec42_checks: List[CheckResult] = []

    p_idxs = pdf.find_pages_containing("Is Application a", True)
    cif_value = None
    if p_idxs:
        lines = pdf.page_lines(p_idxs[0])
        cif_value = extract_yes_no(find_first_value_after_labels(lines, ["Is Application a", "critical and", "important"]))
        cif_value = cif_value or extract_yes_no(_extract_stack_label_value(lines, ["Is Application a", "critical and", "important"]))

    sec42_checks.append(
        _yn_check("S4.2-01", "CIF (critical & important function) recorded (yes/no)", cif_value, severity="major", lenient=lenient)
    )

    expected_42 = [
        "IT Role Services.xlsx",
        "All my Roles.xlsx",
        "All my Application Roles.xlsx",
        "All my IT Roles without Application Role.xlsx",
    ]
    for i, exp in enumerate(expected_42, start=1):
        sec42_checks.append(
            _export_exists_check(f"S4.2-F{i:02d}", f"Export present: {exp}", referenced_xlsx, evidence_dir, exp)
        )

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
    # Section 4.3 Special Accounts (MVP skip remains)
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

    result = ReviewResult(
        dac_file=str(dac_pdf),
        generated_at=ReviewResult.now_iso(),
        overall_status=overall,
        sections=sections,
        recommendations=recommendations,
        stats={
            "referenced_xlsx": referenced_xlsx,
            "evidence_dir_files": list_existing_files(evidence_dir),
        },
    )

    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # IMPORTANT: sanitize JSON (NaN/inf -> null) and enforce strict JSON
        result_dict = sanitize_json(result.to_dict())
        (out_dir / "review_result.json").write_text(json.dumps(result_dict, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        (out_dir / "review_result.md").write_text(_to_markdown(result), encoding="utf-8")

    return result


# -------------------------------------------------------------------------
# PDF: extractable text + OCR-required detection + OCR attempt w/ cache
# -------------------------------------------------------------------------
def _pdf_text_and_ocr_meta(
    pdf_path: Path,
    out_dir: Optional[Path],
    min_chars: int,
    ocr_image_threshold: int,
    ocr_enabled: bool,
    ocr_lang: str,
    ocr_dpi: int,
    ocr_max_pages: Optional[int],
    tesseract_cmd: Optional[str],
) -> Tuple[str, bool, Dict[str, Any]]:
    """
    Returns (used_text, text_ok, meta).
    If text_ok is False and ocr_required=True in meta => scanned/image-based PDF likely.
    If OCR is enabled and ocr_required=True => attempt OCR (cached under out/ocr_cache).
    """
    used_text = ""
    text_chars = 0
    page_count = 0
    image_count = 0
    err: Optional[str] = None

    try:
        d = PdfDoc(pdf_path)
        page_count = d.page_count()
        used_text = (d.all_text() or "").strip()
        text_chars = len(used_text)
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
    }
    if err:
        meta["error"] = err

    text_ok = text_chars >= max(0, int(min_chars))
    ocr_required = (not text_ok) and (image_count >= max(0, int(ocr_image_threshold)))
    meta["ocr_required"] = bool(ocr_required)

    # OCR fields (always present once OCR is supported)
    meta["ocr_enabled"] = bool(ocr_enabled)
    meta["ocr_available"] = False
    meta["ocr_attempted"] = False

    if ocr_enabled and ocr_required:
        ocr_text, ocr_meta = _ocr_pdf_cached(
            pdf_path=pdf_path,
            out_dir=out_dir,
            lang=ocr_lang,
            dpi=ocr_dpi,
            max_pages=ocr_max_pages,
            tesseract_cmd=tesseract_cmd,
        )
        meta.update(ocr_meta)

        if ocr_text and ocr_text.strip():
            used_text = ocr_text.strip()
            meta["text_chars_after_ocr"] = len(used_text)
            text_ok = len(used_text) >= max(0, int(min_chars))

    return used_text, bool(text_ok), meta


def _ocr_pdf_cached(
    pdf_path: Path,
    out_dir: Optional[Path],
    lang: str,
    dpi: int,
    max_pages: Optional[int],
    tesseract_cmd: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    """
    OCR with on-disk cache:
      <out_dir>/ocr_cache/<basename>.<key8>.txt

    Cache key includes:
      - pdf sha256
      - lang/dpi/max_pages/tesseract_cmd
    """
    meta: Dict[str, Any] = {
        "ocr_available": False,
        "ocr_attempted": False,
        "ocr_lang": lang,
        "ocr_dpi": int(dpi),
        "ocr_pages": (None if max_pages is None else int(max_pages)),
    }

    cache_dir: Optional[Path] = None
    if out_dir:
        cache_dir = Path(out_dir) / "ocr_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

    # Check deps
    try:
        import pytesseract  # type: ignore
        from pdf2image import convert_from_path  # type: ignore

        meta["ocr_available"] = True
    except Exception as e:
        meta["ocr_attempted"] = True
        meta["ocr_succeeded"] = False
        meta["ocr_error"] = f"ocr_deps_missing: {type(e).__name__}: {e}"
        return "", meta

    # cache key (best-effort)
    key8 = "nocache"
    try:
        import hashlib
        from .util import sha256_file

        pdf_sha = sha256_file(pdf_path)
        key_payload = json.dumps(
            {
                "pdf_sha256": pdf_sha,
                "lang": lang,
                "dpi": int(dpi),
                "max_pages": max_pages,
                "tesseract_cmd": tesseract_cmd or "",
            },
            sort_keys=True,
        ).encode("utf-8")
        key8 = hashlib.sha256(key_payload).hexdigest()[:8]
    except Exception:
        pass

    base = pdf_path.stem
    txt_path = (cache_dir / f"{base}.{key8}.txt") if cache_dir else None

    if txt_path and txt_path.exists():
        cached = txt_path.read_text(encoding="utf-8", errors="ignore")
        meta["ocr_attempted"] = True
        meta["ocr_cache_hit"] = True
        meta["ocr_text_chars"] = len(cached)
        meta["ocr_succeeded"] = len(cached.strip()) > 0
        logging.info("OCR cache hit: %s", txt_path.name)
        return cached, meta

    # cache miss
    meta["ocr_attempted"] = True
    meta["ocr_cache_hit"] = False

    try:
        import pytesseract  # type: ignore
        from pdf2image import convert_from_path  # type: ignore

        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        images = convert_from_path(str(pdf_path), dpi=int(dpi))
        if max_pages is not None:
            images = images[: int(max_pages)]

        parts: List[str] = []
        for img in images:
            parts.append(pytesseract.image_to_string(img, lang=lang))
        text = "\n".join(parts)

        meta["ocr_text_chars"] = len(text)
        meta["ocr_succeeded"] = len(text.strip()) > 0

        if txt_path:
            txt_path.write_text(text, encoding="utf-8")
            logging.info("OCR cache write: %s", txt_path.name)

        return text, meta
    except Exception as e:
        meta["ocr_succeeded"] = False
        meta["ocr_error"] = f"{type(e).__name__}: {e}"
        return "", meta


# -------------------------------------------------------------------------
# Existing helpers (unchanged)
# -------------------------------------------------------------------------
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


def _extract_value_global(pdf: PdfDoc, label_variants: List[str]) -> Optional[str]:
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
                ev = json.dumps(sanitize_json(c.evidence), ensure_ascii=False, allow_nan=False)
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
