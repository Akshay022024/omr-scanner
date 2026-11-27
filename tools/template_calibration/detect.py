import cv2, numpy as np, sys, json
img = cv2.imread(sys.argv[1])
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
# magenta print: hue ~140-175 (opencv 0-180), sat high
mask = cv2.inRange(hsv, (130, 60, 80), (179, 255, 255))
cv2.imwrite(sys.argv[2], mask)
cnts, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
circles = []
rects = []
for c in cnts:
    x, y, w, h = cv2.boundingRect(c)
    area = cv2.contourArea(c)
    if 18 <= w <= 45 and 18 <= h <= 45 and 0.8 < w / h < 1.25:
        per = cv2.arcLength(c, True)
        circ = 4 * np.pi * area / (per * per + 1e-6)
        if circ > 0.7:
            circles.append((x + w / 2, y + h / 2, w, h))
    if w > 300 and h > 150:
        rects.append((x, y, w, h))
# dedupe circles (outer/inner contours)
circles.sort()
ded = []
for c in circles:
    if not any(abs(c[0] - d[0]) < 6 and abs(c[1] - d[1]) < 6 for d in ded):
        ded.append(c)
print("circles", len(ded))
import collections
print("size hist", collections.Counter((round(c[2]), round(c[3])) for c in ded).most_common(8))
print("rects", sorted(rects))
json.dump(ded, open(sys.argv[3], "w"))
