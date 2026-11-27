import cv2, json
t = json.load(open("templates/sheet80_v2/template.json"))
img = cv2.imread("templates/sheet80_v2/template_200dpi.png")
for f in t["fields"]:
    col = {"roll_no": (255,0,0), "paper_set": (0,160,0), "answers": (0,0,255)}[f["group"]]
    for b in f["bubbles"]:
        cv2.circle(img, (int(b["x"]), int(b["y"])), int(b["r"]), col, 2)
for k, (x,y,w,h) in t["anchors"].items():
    cv2.rectangle(img, (x,y), (x+w,y+h), (0,200,200), 2)
cv2.imwrite("scratch/overlay.png", cv2.resize(img, (850, 1100)))
crop = img[860:1100, 90:860]
cv2.imwrite("scratch/overlay_crop.png", crop)
