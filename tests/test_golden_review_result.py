from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from daisy.schema_validate import validate_review_result

# If your validate() function lives somewhere else, adjust this import:
from daisy.agent import validate


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests" / "golden" / "review_result.golden.json"


def _normalize(d: Dict[str, Any]) -> Dict[str, Any]:
    # Make comparisons stable across runs
    d = dict(d)
    d.pop("generated_at", None)
    d.pop("result_version", None)

    # Some runs may include extra keys under stats; keep stats but normalize ordering
    # (JSON dump with sort_keys handles ordering differences)

    return d


@pytest.mark.e2e
def test_golden_review_result(tmp_path: Path):
    # Adjust these 3 arguments if your validate() signature differs.
    # Based on your earlier tests, validate(dac_paths, evidence_dirs, rules_path) is likely correct.
    rep = validate(
        dac_paths=[r"daisy_test_data/2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365.pdf"],
        evidence_dirs=[r"daisy_test_data"],
        rules_path=r"config/rules.yaml",
        out_dir=str(tmp_path),
        mvp=True,
        print_report=False,
    )

    # Validate output schema
    validate_review_result(rep)

    got = _normalize(rep)
    exp = _normalize(json.loads(GOLDEN.read_text(encoding="utf-8")))

    got_s = json.dumps(got, indent=2, sort_keys=True, ensure_ascii=False)
    exp_s = json.dumps(exp, indent=2, sort_keys=True, ensure_ascii=False)

    assert got_s == exp_s
