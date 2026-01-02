# Daisy (no-UI) — DAC review agent

This repository contains a **CLI-only** implementation of the Daisy DAC review agent.

It:
- Reads a **DAC PDF**
- Detects **referenced XLSX exports**
- Validates key **user-story checks** (currently implemented mainly for **Section 4.1 / 4.2** and some basics)
- Emits:
  - `review_result.json`
  - `review_result.md`

## Install

```bash
python -m venv .venv
source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
```

## Run

```bash
daisy validate \
  --dac path/to/Report_DAC.pdf \
  --evidence-dir path/to/evidence_dir \
  --out out \
  --print
```

Outputs:
- `out/review_result.json`
- `out/review_result.md`

## What is implemented (MVP)

- **1.1 General Information**: CMS Product ID, IT Asset ID, IT Asset Name (presence)
- **4.1 Entitlements**:
  - SoD relevancy (yes/no)
  - Functional Area relevancy (yes/no)
  - Upload entitlement composition decision (yes/no)
  - Exports present: `Entitlement Services.xlsx`, `All Entitlements.xlsx`
  - Excel checks (Entitlement Services):
    - Required columns non-empty
    - Meaningful descriptions
- **4.2 IT Roles**:
  - CIF question (yes/no) (best-effort)
  - Exports present: `IT Role Services.xlsx`, `All my Roles.xlsx`, `All my Application Roles.xlsx`, `All my IT Roles without Application Role.xlsx`
  - Excel checks (IT Role Services):
    - Required columns non-empty
    - Meaningful descriptions
- **4.3 Special Accounts**:
  - Export present: `Special Accounts Services.xlsx` (best-effort)
- **4.4 Segregation of Duties**:
  - If SoD relevancy == yes: requires `Functional Area Matrix.xlsx`

## Notes

- This MVP intentionally **does not rely on APMS screenshots** (OCR) and will mark those checks as skipped/not implemented.
- PDF templates vary; extraction is **best-effort** and designed to degrade gracefully with clear messages in the report.

