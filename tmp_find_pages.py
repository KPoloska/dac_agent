from pathlib import Path
from daisy.pdf_reader import PdfDoc

p = Path(r".\daisy_test_data\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365.pdf")
d = PdfDoc(p)

needles = ["CMS Product ID", "IT Asset ID", "IT Asset Name", "Application is", "Is Application a"]
for n in needles:
    pages = d.find_pages_containing(n, True)
    print(f"{n}: {pages} (count={len(pages)})")
