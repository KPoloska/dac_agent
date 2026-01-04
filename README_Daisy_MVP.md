# Daisy MVP — DAC Compliance Validation Agent (CLI, no UI)

This project is a **command-line validation agent** that reviews a **DAC PDF** plus an **evidence directory** (PDFs + XLSX exports) and produces:

- `review_result.json` (machine-readable)
- `review_result.md` (human-readable report)
- `run_summary.json` (reproducibility hashes + run metadata)
- `run.log` (logs)
- optional `extract_debug.json` (extraction trace)
- optional `ocr_cache/` (cached OCR text per PDF)

It’s built to be “functional MVP”: it focuses on **extracting key DAC fields**, checking **presence of required evidence files**, and validating **basic Excel export quality** with tolerances (especially in `--mvp` mode).

---

## What the agent can do (current capabilities)

### 1) Parse DAC PDF (text extraction)
- Extracts from DAC:
  - **CMS Product ID**
  - **IT Asset ID**
  - **IT Asset Name**
  - **4.1 Entitlements** yes/no fields (best-effort):
    - SoD relevancy (yes/no)
    - Functional Area relevancy (yes/no)
    - “Upload entitlement composition?” (yes/no)
  - **4.2 IT Roles** yes/no field (best-effort):
    - “Is application a critical & important function (CIF)?” (yes/no)

### 2) OCR support for scanned / partially scanned PDFs (optional)
If enabled with `--ocr`, the agent can OCR the DAC (and can also detect scanned evidence PDFs and optionally OCR those too).

- Targeted DAC OCR supported via:
  - `--ocr-pages "14,38,43,53"` (0-based page indices)
- OCR results are cached under `out/ocr_cache/` to avoid repeated work.

### 3) Evidence PDFs presence + extractable-text checks
- Checks required evidence PDFs listed in `config/rules.yaml`:
  - Ensures required evidence PDFs exist in the evidence directory.
  - Checks each evidence PDF has extractable text (or flags that OCR is required).
  - In `--mvp` mode, scanned-text warnings are treated as “MET with warning” (so the run can proceed).

### 4) Excel export presence checks (based on DAC references + fallback search)
- Tries to detect referenced `.xlsx` filenames from DAC text and then locate them inside evidence directory.
- Also falls back to scanning the evidence directory for `*.xlsx` with matching suffix.

### 5) Excel quality checks (MVP-grade)
Currently validates:

**Entitlement Services.xlsx**
- Required master data columns filled (threshold-based):
  - `Display name`, `Description`, `SoD Area`, `Tier Level`
- “Meaningful description” heuristic (threshold-based)

**All Entitlements.xlsx**
- Used for a **Functional Area** sanity rule when “Functional Area relevancy = yes”
  - checks `DBG Functional Area` has some non-empty rows (if column exists)

**IT Role Services.xlsx**
- Required master data columns filled (threshold-based):
  - `Display name`, `Description`, `Tier Level`
  - plus best-effort owner columns if present (fallback logic)
- “Meaningful description” heuristic (threshold-based)

### 6) Output / scoring model
- Each check is `MET`, `NOT_MET`, `SKIPPED`, or `UNKNOWN`
- Each section gets aggregated to a section status.
- Overall status is aggregated across sections:
  - `MET`, `PARTIALLY_MET`, `NOT_MET`, `UNKNOWN`
- Exit codes:
  - `0` = MET
  - `2` = PARTIALLY_MET
  - `3` = NOT_MET
  - `4` = ERROR

### 7) Debug mode for extraction tracing
`--debug-extract` writes `extract_debug.json` with event-by-event extraction info.

---

## What the agent does NOT do (yet)
- No UI.
- No advanced APMS screenshot parsing (you can ignore APMS screenshots for now).
- No deep semantic validation of process PDFs (only presence + text/OCR detection).
- No full Jira coverage beyond the implemented sections/checks.

---

## Requirements

### System requirements
- Python **3.10+** (recommended: 3.11)
- Windows / macOS / Linux supported

### Python packages (installed via pip)
Core:
- `pymupdf` (PDF text + rendering for OCR)
- `pandas`
- `openpyxl`
- `pyyaml`

OCR (only if you use `--ocr`):
- `pytesseract`
- `Pillow`

Optional:
- `jsonschema` (only used by CLI schema validation; not required if `--schema-off`)

---

## Setup

### 1) Create and activate a virtual environment

**Windows PowerShell**
```powershell
cd C:\path\to\daisy_mvp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

**macOS / Linux**
```bash
cd /path/to/daisy_mvp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 2) Install dependencies
If you have a `requirements.txt`:
```bash
pip install -r requirements.txt
```

If not, install explicitly:
```bash
pip install pymupdf pandas openpyxl pyyaml
pip install pytesseract pillow   # only if you want OCR
pip install jsonschema           # optional schema validation
```

---

## Install Tesseract (only if using OCR)

### Windows
1) Install Tesseract from the official installer.
2) Confirm the binary exists, typically:
   - `C:\Program Files\Tesseract-OCR\tesseract.exe`

### macOS
```bash
brew install tesseract
```

### Linux (Debian/Ubuntu)
```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr
```

---

## Running the agent

### Important: set PYTHONPATH to `src`

**Windows PowerShell**
```powershell
$env:PYTHONPATH="src"
```

**macOS / Linux**
```bash
export PYTHONPATH=src
```

### Basic validation (no OCR)
```powershell
python -m daisy validate `
  --dac ".\daisy_test_data\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365.pdf" `
  --evidence-dir ".\daisy_test_data" `
  --out out_basic `
  --rules ".\config\rules.yaml" `
  --mvp --lenient
```

### Validation with OCR (target specific DAC pages)
Use **0-based page indices**.
```powershell
python -m daisy validate `
  --dac ".\out\dac_partially_scanned.pdf" `
  --evidence-dir ".\daisy_test_data" `
  --out out_ocr `
  --rules ".\config\rules.yaml" `
  --mvp --lenient `
  --ocr `
  --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe" `
  --ocr-pages "14,38,43,53"
```

### Print the markdown report to stdout
```powershell
python -m daisy validate `
  --dac ".\out\dac_partially_scanned.pdf" `
  --evidence-dir ".\daisy_test_data" `
  --out out_print `
  --mvp --lenient `
  --print
```

### Debug extraction trace
```powershell
python -m daisy validate `
  --dac ".\out\dac_partially_scanned.pdf" `
  --evidence-dir ".\daisy_test_data" `
  --out out_debug `
  --mvp --lenient `
  --ocr `
  --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe" `
  --ocr-pages "14,38,43,53" `
  --debug-extract
```

Outputs:
- `out_debug/review_result.json`
- `out_debug/review_result.md`
- `out_debug/run_summary.json`
- `out_debug/run.log`
- `out_debug/extract_debug.json`
- `out_debug/ocr_cache/*` (if OCR was used)

---

## Understanding CLI flags

- `--dac <path>`: DAC PDF path (required)
- `--evidence-dir <dir>`: directory containing evidence PDFs + XLSX exports (required)
- `--out <dir>`: output directory (default `out`)
- `--rules <file>`: rules YAML file (default `config/rules.yaml`)
- `--lenient`: missing/unparseable yes/no becomes `SKIPPED` instead of `NOT_MET`
- `--mvp`: enable MVP tolerances and some skips
- `--print`: print `review_result.md` after run
- `--schema-off`: skip JSON schema validation in the CLI

OCR flags:
- `--ocr`: enable OCR
- `--tesseract-cmd`: path to `tesseract.exe` on Windows
- `--ocr-lang`: tesseract language (default `eng`)
- `--ocr-dpi`: render DPI for OCR (default `200`)
- `--ocr-max-pages`: max pages to OCR when auto-picking (default `2`)
- `--ocr-pages`: explicit pages to OCR for the DAC (0-based). Example: `14,38,43` or `10-15,40`

Debug:
- `--debug-extract`: write extraction trace JSON

---

## Rules configuration (`config/rules.yaml`)

The rules file controls:
- Which evidence PDFs are required (`pdf_evidence.required_files`)
- Minimum extractable text (`pdf_evidence.min_text_chars`)
- OCR “image-based PDF” threshold (`pdf_evidence.ocr_image_threshold`)
- Excel tolerance thresholds (`excel_thresholds.*`)

If `rules.yaml` is missing/unreadable, the loader falls back to defaults.

---

## Typical workflow

1) Put all evidence files (PDF + XLSX) into one folder, e.g. `daisy_test_data/`
2) Run validate without OCR
3) If DAC fields are `NOT_MET` due to scanning, re-run with OCR and targeted `--ocr-pages`
4) Read the markdown report and fix missing evidence files / broken exports

---

## Troubleshooting

### 1) PowerShell line continuation
Use backticks ( ` ) in PowerShell, not `\`.

### 2) `ModuleNotFoundError: daisy`
You forgot PYTHONPATH:
```powershell
$env:PYTHONPATH="src"
```

### 3) OCR not working
- Confirm tesseract path is correct:
  - `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Confirm you installed:
  - `pip install pytesseract pillow`

### 4) OCR page numbering confusion
`--ocr-pages` uses **0-based** indexing (page 0 = first page).

### 5) `openpyxl` default style warnings
This warning is harmless and comes from some exported XLSX files.

---

## Quick “smoke tests”

### Find which pages contain key labels (PDF text only)
```powershell
$env:PYTHONPATH="src"

@'
from pathlib import Path
from daisy.pdf_reader import PdfDoc

p = Path(r".\daisy_test_data\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365.pdf")
d = PdfDoc(p)

needles = ["CMS Product ID", "IT Asset ID", "IT Asset Name", "Application is", "Is Application a"]
for n in needles:
    pages = d.find_pages_containing(n, True)
    print(f"{n}: {pages} (count={len(pages)})")
'@ | Set-Content -Encoding UTF8 .\tmp_find_pages.py

python .\tmp_find_pages.py
```

---

## Deliverables you should look at after each run

- `review_result.md` → easiest human review
- `review_result.json` → structured output for automation
- `run_summary.json` → hashes + flags + metadata
- `run.log` → debug logs
- `extract_debug.json` → why extraction succeeded/failed (if enabled)

---

## Project status summary (current)
✅ Working CLI validation pipeline  
✅ OCR targeted pages for DAC  
✅ Evidence PDF presence + scanned detection  
✅ Excel master-data & description heuristics with MVP tolerances  
✅ JSON + Markdown output + reproducibility hashes  
✅ Debug extraction trace support  

Next improvements usually include:
- stronger yes/no extraction on tricky OCR layouts
- content validation rules per evidence PDF
- APMS screenshot parsing (if required later)

