"""Builds templates/sheet80_v2/template.json from detected circles on the 200dpi render."""
import json, numpy as np

c = json.load(open("scratch/circles.json"))
W, H = 1700, 2200


def rows(pts, tol=8):
    pts = sorted(pts, key=lambda p: p[1])
    out = []
    for p in pts:
        if out and abs(out[-1][-1][1] - p[1]) < tol:
            out[-1].append(p)
        else:
            out.append([p])
    return [sorted(r) for r in out]


roll = [p for p in c if p[0] < 640 and 150 < p[1] < 640]
sett = [p for p in c if 640 < p[0] < 800 and p[1] < 640]
ans = [p for p in c if p[1] > 860 and p[0] < 1600 and not (p[0] > 840 and p[1] < 400)]

fields = []
# Roll number: 10 columns (digits positions), rows labelled 1..9,0
roll_rows = rows(roll)
assert len(roll_rows) == 10 and all(len(r) == 10 for r in roll_rows)
row_labels = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
for col in range(10):
    bubbles = []
    for ri, r in enumerate(roll_rows):
        x, y, w, h = r[col]
        bubbles.append({"value": row_labels[ri], "x": round(x, 1), "y": round(y, 1), "r": 13.5})
    fields.append({"id": f"roll_{col + 1}", "group": "roll_no", "type": "digit", "bubbles": bubbles})

set_sorted = sorted(sett, key=lambda p: p[1])
assert len(set_sorted) == 3
fields.append({"id": "paper_set", "group": "paper_set", "type": "choice",
               "bubbles": [{"value": v, "x": round(p[0], 1), "y": round(p[1], 1), "r": 13.5}
                           for v, p in zip("ABC", set_sorted)]})

for colidx in range(4):
    a = [p for p in ans if 94 + colidx * 380 < p[0] < 94 + (colidx + 1) * 380]
    rr = rows(a)
    assert len(rr) == 20 and all(len(r) == 4 for r in rr), (colidx, len(rr), [len(r) for r in rr])
    for ri, r in enumerate(rr):
        q = colidx * 20 + ri + 1
        fields.append({"id": f"q{q}", "group": "answers", "type": "choice", "question": q,
                       "bubbles": [{"value": v, "x": round(p[0], 1), "y": round(p[1], 1), "r": 14.5}
                                   for v, p in zip("ABCD", r)]})

tpl = {
    "id": "sheet80_v2",
    "name": "80-question OMR sheet (v2)",
    "version": 1,
    "page": {"width_px": W, "height_px": H, "dpi": 200, "paper": "letter"},
    "print_color": "magenta",
    "reference_image": "template_200dpi.png",
    # Panel boxes (x, y, w, h) in template px, used as registration anchors
    "anchors": {
        "roll_box": [94, 46, 745, 529],
        "details_box": [94, 581, 744, 203],
        "instructions_box": [850, 203, 744, 581],
        "answers_col_1": [94, 821, 367, 1107],
        "answers_col_2": [474, 821, 367, 1107],
        "answers_col_3": [854, 821, 367, 1107],
        "answers_col_4": [1234, 821, 361, 1107],
    },
    "num_questions": 80,
    "options": ["A", "B", "C", "D"],
    "fields": fields,
}
json.dump(tpl, open("templates/sheet80_v2/template.json", "w"), indent=1)
print("fields", len(fields), "bubbles", sum(len(f["bubbles"]) for f in fields))
