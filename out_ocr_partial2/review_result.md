# Daisy DAC Review Result

- DAC: `out\dac_partially_scanned.pdf`
- Generated at: `2026-01-02T04:18:13.598891+00:00`
- Overall: **PARTIALLY_MET**

## Sections

### 1.1 General Information — **MET**

- `S1.1-01` **MET** (major) — CMS Product ID present
  - evidence: `{"value": "1513344"}`
- `S1.1-02` **MET** (major) — IT Asset ID present
  - evidence: `{"value": "AID551"}`
- `S1.1-03` **MET** (major) — IT Asset Name present
  - evidence: `{"value": "MICROSOFT OFFICE 365"}`

### 2.0 Process Evidence (PDFs) — **MET**

- `S2.0-01` **MET** (major) — Evidence PDF present: Chapter1.pdf
  - evidence: `{"file": "daisy_test_data\\Chapter1.pdf"}`
- `S2.0-02` **MET** (major) — Evidence PDF present: Chapter2-3.pdf
  - evidence: `{"file": "daisy_test_data\\Chapter2-3.pdf"}`
- `S2.0-03` **MET** (major) — Evidence PDF present: Provisioning & Assignment of Access.pdf
  - evidence: `{"file": "daisy_test_data\\Provisioning & Assignment of Access.pdf"}`
- `S2.0-04` **MET** (major) — Evidence PDF present: Review and Approval of Access.pdf
  - evidence: `{"file": "daisy_test_data\\Review and Approval of Access.pdf"}`
- `S2.0-05` **MET** (major) — Evidence PDF present: Recertification.pdf
  - evidence: `{"file": "daisy_test_data\\Recertification.pdf"}`
- `S2.0-01-TXT` **MET** (major) — Evidence PDF has extractable text: Chapter1.pdf
  - evidence: `{"file": "daisy_test_data\\Chapter1.pdf", "page_count": 10, "text_chars": 0, "image_count": 20, "ocr_enabled": true, "ocr_required": true, "ocr_available": true, "ocr_attempted": true, "ocr_lang": "eng", "ocr_dpi": 200, "ocr_pages": 2, "ocr_text_chars": 1731, "ocr_cache_hit": false, "ocr_succeeded": true, "ocr_pages_requested": [0, 1], "ocr_pages_used": [0, 1], "text_chars_after_ocr": 1731}`
- `S2.0-02-TXT` **MET** (major) — Evidence PDF has extractable text: Chapter2-3.pdf
  - evidence: `{"file": "daisy_test_data\\Chapter2-3.pdf", "page_count": 11, "text_chars": 0, "image_count": 22, "ocr_enabled": true, "ocr_required": true, "ocr_available": true, "ocr_attempted": true, "ocr_lang": "eng", "ocr_dpi": 200, "ocr_pages": 2, "ocr_text_chars": 2272, "ocr_cache_hit": false, "ocr_succeeded": true, "ocr_pages_requested": [0, 1], "ocr_pages_used": [0, 1], "text_chars_after_ocr": 2272}`
- `S2.0-03-TXT` **MET** (major) — Evidence PDF has extractable text: Provisioning & Assignment of Access.pdf
  - evidence: `{"file": "daisy_test_data\\Provisioning & Assignment of Access.pdf", "page_count": 3, "text_chars": 4460, "image_count": 3, "ocr_enabled": true, "ocr_required": false, "ocr_available": false, "ocr_attempted": false}`
- `S2.0-04-TXT` **MET** (major) — Evidence PDF has extractable text: Review and Approval of Access.pdf
  - evidence: `{"file": "daisy_test_data\\Review and Approval of Access.pdf", "page_count": 3, "text_chars": 2633, "image_count": 3, "ocr_enabled": true, "ocr_required": false, "ocr_available": false, "ocr_attempted": false}`
- `S2.0-05-TXT` **MET** (major) — Evidence PDF has extractable text: Recertification.pdf
  - evidence: `{"file": "daisy_test_data\\Recertification.pdf", "page_count": 2, "text_chars": 2668, "image_count": 2, "ocr_enabled": true, "ocr_required": false, "ocr_available": false, "ocr_attempted": false}`

### 4.1 Entitlements — **PARTIALLY_MET**

- `S4.1-01` **MET** (critical) — SoD relevancy recorded (yes/no)
  - evidence: `{"value": "no"}`
- `S4.1-02` **SKIPPED** (major) — Functional Area relevancy recorded (yes/no)
  - Missing/unparseable yes/no in DAC PDF (lenient mode).
- `S4.1-03` **SKIPPED** (major) — Entitlement composition upload decision recorded (yes/no)
  - Missing/unparseable yes/no in DAC PDF (lenient mode).
- `S4.1-F01` **MET** (major) — Export present: Entitlement Services.xlsx
  - evidence: `{"file": "daisy_test_data\\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365_Entitlement Services.xlsx"}`
- `S4.1-F02` **MET** (major) — Export present: All Entitlements.xlsx
  - evidence: `{"file": "daisy_test_data\\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365_All Entitlements.xlsx"}`
- `S4.1-EX-01` **MET** (major) — Entitlement Services: required master data filled
  - MVP warning: 33 of 572 rows failed (tolerance=57).
  - evidence: `{"total_rows": 572, "failing_rows": 33, "samples": [{"Display name": "BC_AGMQAPrepTool_EBMembers @ oa.pnrad.net", "Description": NaN, "SoD Area": "XX - Not SoD-relevant", "Tier Level": 3.0}, {"Display name": "MDO-RBAC-Full-Management @ oa.pnrad.net", "Description": NaN, "SoD Area": "XX - Not SoD-relevant", "Tier Level": 1.0}, {"Display name": "O365-LG-CopilotStudio @ oa.pnrad.net", "Description": "Owner: xa359_Benoit Krier, ha995_Martin Puaud", "SoD Area": "XX - Not SoD-relevant", "Tier Level": NaN}, {"Display name": "O365-LG-E5-SharedMBX-ConfCall @ oa.pnrad.net", "Description": "Owner: xa359_…`
- `S4.1-EX-02` **MET** (major) — Entitlement Services: descriptions are meaningful
  - MVP warning: 21 of 572 rows failed (tolerance=57).
  - evidence: `{"total_rows": 572, "failing_rows": 21, "samples": [{"Display name": "BC_AGMQAPrepTool_EBMembers @ oa.pnrad.net", "Description": NaN}, {"Display name": "DLP-Excel-Exception-CBAus-M365", "Description": "DLP-Excel-Exception-CBAus-M365"}, {"Display name": "DLP-Excel-Exception-CBDubai-M365", "Description": "DLP-Excel-Exception-CBDubai-M365"}, {"Display name": "DLP-Excel-Exception-CBF-M365", "Description": "DLP-Excel-Exception-CBF-M365"}, {"Display name": "DLP-Excel-Exception-CBHK-M365", "Description": "DLP-Excel-Exception-CBHK-M365"}]}`

### 4.2 IT Roles — **PARTIALLY_MET**

- `S4.2-01` **SKIPPED** (major) — CIF (critical & important function) recorded (yes/no)
  - Missing/unparseable yes/no in DAC PDF (lenient mode).
- `S4.2-F01` **MET** (major) — Export present: IT Role Services.xlsx
  - evidence: `{"file": "daisy_test_data\\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365_IT Role Services.xlsx"}`
- `S4.2-F02` **MET** (major) — Export present: All my Roles.xlsx
  - evidence: `{"file": "daisy_test_data\\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365_All my Roles.xlsx"}`
- `S4.2-F03` **MET** (major) — Export present: All my Application Roles.xlsx
  - evidence: `{"file": "daisy_test_data\\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365_All my Application Roles.xlsx"}`
- `S4.2-F04` **MET** (major) — Export present: All my IT Roles without Application Role.xlsx
  - evidence: `{"file": "daisy_test_data\\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365_All my IT Roles without Application Role.xlsx"}`
- `S4.2-EX-01` **MET** (major) — IT Role Services: required master data filled (base + owner fallback)
  - MVP warning: 1 of 816 rows failed (tolerance=8).
  - evidence: `{"total_rows": 816, "failing_rows": 1, "owner_cols_used": ["IT Role Owner", "cust_owner", "Application Owner"], "samples": [{"Display name": "SharePoint - Administrator-IT", "Description": NaN, "Tier Level": 1, "IT Role Owner": NaN, "cust_owner": NaN, "Application Owner": "SharePoint Admin - Role Owner | User group"}]}`
- `S4.2-EX-02` **MET** (major) — IT Role Services: descriptions are meaningful
  - MVP warning: 1 of 816 rows failed (tolerance=8).
  - evidence: `{"total_rows": 816, "failing_rows": 1, "samples": [{"Display name": "SharePoint - Administrator-IT", "Description": NaN}]}`

### 4.3 Special Accounts — **UNKNOWN**

- `S4.3-01` **SKIPPED** (major) — Export present: Special Accounts Services.xlsx
  - MVP: Special Accounts export not provided; skipping (still recommended to include for full validation).
  - evidence: `{"expected": "Special Accounts Services.xlsx", "referenced_by_pdf": true}`

### 4.4 Segregation of Duties — **UNKNOWN**

- `S4.4-01` **SKIPPED** (major) — Functional Area Matrix.xlsx present when SoD relevant
  - Skipped because SoD relevancy is not 'yes' (or could not be extracted).
