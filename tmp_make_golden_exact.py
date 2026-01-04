import json
from pathlib import Path

from daisy.agent import validate

GOLDEN = Path("tests/golden/review_result.golden.json")

rep = validate(
    dac_paths=[r"daisy_test_data/2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365.pdf"],
    evidence_dirs=[r"daisy_test_data"],
    rules_path=r"config/rules.yaml",
    out_dir=r"out_golden_build",
    mvp=True,
    print_report=False,
)

# rep must be a plain JSON-able dict for the golden file
if hasattr(rep, "to_dict"):
    rep = rep.to_dict()

GOLDEN.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
print("WROTE", GOLDEN.resolve())
