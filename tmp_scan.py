from pathlib import Path
import fitz

src = Path(r".\daisy_test_data\2025_11_11_Report_DAC_Template_Resource_MICROSOFT_OFFICE_365.pdf")
out = Path(r".\out\dac_scanned.pdf")
out.parent.mkdir(parents=True, exist_ok=True)

doc = fitz.open(str(src))
new = fitz.open()

# make first 2 pages image-only
n = min(2, len(doc))
for i in range(n):
    p = doc.load_page(i)
    pix = p.get_pixmap(dpi=200, alpha=False)
    rect = fitz.Rect(0, 0, pix.width, pix.height)
    np = new.new_page(width=pix.width, height=pix.height)
    np.insert_image(rect, pixmap=pix)

new.save(str(out))
new.close()
doc.close()

print("Wrote:", out)
