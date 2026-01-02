from pathlib import Path

from daisy.agent import validate


def _flatten_checks(result_dict):
    for sec in result_dict["sections"]:
        for chk in sec["checks"]:
            yield sec, chk


def test_validate_mvp_lenient_no_not_met():
    dac = Path("daisy_test_data") / "2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365.pdf"
    evidence = Path("daisy_test_data")
    rules = Path("config/rules.yaml")

    res = validate(dac, evidence, out_dir=None, lenient=True, mvp=True, rules_path=rules)
    d = res.to_dict()

    # MVP expectation: nothing should be NOT_MET
    not_met = [(sec["section_id"], chk["check_id"]) for sec, chk in _flatten_checks(d) if chk["status"] == "NOT_MET"]
    assert not not_met, f"Found NOT_MET checks: {not_met}"

    # OCR-required detection should appear for scanned chapter PDFs (in this dataset)
    # (We don't require it to be true for all environments, but if present, it must be boolean.)
    for sec, chk in _flatten_checks(d):
        ev = chk.get("evidence") or {}
        if "ocr_required" in ev:
            assert isinstance(ev["ocr_required"], bool)
