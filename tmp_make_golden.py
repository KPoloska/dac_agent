import json
from pathlib import Path

from daisy.agent import validate

ROOT = Path(__file__).resolve().parents[0]
GOLDEN = ROOT / "tests" / "golden" / "review_result.golden.json"

rep = validate(
    dac_pdf=Path(r"daisy_test_data/2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365.pdf"),
    evidence_dir=Path(r"daisy_test_data"),
    out_dir=None,
    mvp=True,
    lenient=True,
    rules_path=Path(r"config/rules.yaml"),
    ocr=False,
)

# Prefer the same representation the schema expects: a plain dict
data = rep.to_dict() if hasattr(rep, "to_dict") else dict(rep)

GOLDEN.parent.mkdir(parents=True, exist_ok=True)
GOLDEN.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
print("WROTE", GOLDEN)
