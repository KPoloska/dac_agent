from pathlib import Path
import fitz

src = Path(r".\daisy_test_data\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365.pdf")
out = Path(r".\out\dac_partially_scanned.pdf")
out.parent.mkdir(parents=True, exist_ok=True)

SCAN_PAGES = {14, 38, 43, 53}  # 0-based pages
DPI = 200

doc = fitz.open(str(src))
new = fitz.open()

for i in range(len(doc)):
    if i in SCAN_PAGES:
        p = doc.load_page(i)
        pix = p.get_pixmap(dpi=DPI, alpha=False)
        rect = fitz.Rect(0, 0, pix.width, pix.height)
        np = new.new_page(width=pix.width, height=pix.height)
        np.insert_image(rect, pixmap=pix)
    else:
        new.insert_pdf(doc, from_page=i, to_page=i)

new.save(str(out))
new.close()
doc.close()

print("Wrote:", out)
