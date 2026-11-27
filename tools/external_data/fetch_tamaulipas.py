"""Download a stratified sample of the Tamaulipas MCQ exam image dataset (CC BY 4.0).

Dataset: Tamaulipas Multiple-Choice-Question Exam Image Dataset for Optical Mark Recognition Research,
Universidad Politecnica de Victoria, Mendeley Data, v2, DOI 10.17632/djmynjwjpy.2.

Each file is verified against the SHA-256 published by Mendeley. Only .jpg/.txt files are written,
under generated names inside --out; remote filenames are never used as paths beyond a strict pattern check.

Usage: python -I tools/external_data/fetch_tamaulipas.py --out benchmarks/data/external/tamaulipas
                 --grades Grade10,Grade12 --schools 8 --per-folder 12
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

API = "https://data.mendeley.com/public-api/datasets/djmynjwjpy"
VERSION = 2
NAME_RE = re.compile(r"^File\d{4}\.(jpg|txt)$")
UA = {"User-Agent": "omr-benchmark-fetcher/1.0"}


def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def download(url: str, sha256: str, dest: Path, attempts: int = 4) -> bool:
    data = b""
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if hashlib.sha256(data).hexdigest() == sha256:
                break
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(2 * (attempt + 1))
    else:
        return False
    if dest.suffix == ".jpg" and not data.startswith(b"\xff\xd8\xff"):
        return False
    dest.write_bytes(data)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--grades", default="Grade10,Grade12")
    ap.add_argument("--schools", type=int, default=8)
    ap.add_argument("--per-folder", type=int, default=12)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    grades = set(a.grades.split(","))

    folders = get_json(f"{API}/folders/{VERSION}")
    by_id = {f["id"]: f for f in folders}
    leaves = [f for f in folders if f["name"] in grades and f.get("parent_id") in by_id]
    # one leaf per (school, grade); deterministic order; spread across schools
    leaves.sort(key=lambda f: (by_id[f["parent_id"]]["name"], f["name"]))
    schools = sorted({by_id[f["parent_id"]]["name"] for f in leaves})
    step = max(1, len(schools) // a.schools)
    chosen_schools = set(schools[::step][: a.schools])
    manifest = []
    for leaf in leaves:
        school = by_id[leaf["parent_id"]]["name"]
        if school not in chosen_schools:
            continue
        files = get_json(f"{API}/files?folder_id={leaf['id']}&version={VERSION}")
        stems = sorted({f["filename"][:-4] for f in files if NAME_RE.match(f["filename"])})[: a.per_folder]
        idx = {f["filename"]: f for f in files}
        for stem in stems:
            if f"{stem}.jpg" not in idx or f"{stem}.txt" not in idx:
                continue
            local = f"{school}_{leaf['name']}_{stem}"
            ok = True
            for ext in ("jpg", "txt"):
                meta = idx[f"{stem}.{ext}"]
                dest = out / f"{local}.{ext}"
                if dest.exists():
                    continue
                ok &= download(meta["content_details"]["download_url"], meta["content_details"]["sha256_hash"], dest)
            manifest.append({"local": local, "school": school, "grade": leaf["name"], "remote": stem, "verified": ok})
            print(local, "ok" if ok else "HASH/FORMAT FAIL", flush=True)
            time.sleep(0.2)  # be polite to the host
    (out / "manifest.json").write_text(json.dumps({
        "source": "Mendeley Data djmynjwjpy v2 (CC BY 4.0), Universidad Politecnica de Victoria",
        "doi": "10.17632/djmynjwjpy.2", "items": manifest}, indent=1))
    print("schools:", sorted(chosen_schools), "sheets:", len(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
