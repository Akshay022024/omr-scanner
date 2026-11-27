import pymupdf, sys
doc = pymupdf.open(sys.argv[1])
p = doc[0]
print("pages", len(doc), "size pt", p.rect)
pix = p.get_pixmap(dpi=200)
pix.save(sys.argv[2])
print("px", pix.width, pix.height)
