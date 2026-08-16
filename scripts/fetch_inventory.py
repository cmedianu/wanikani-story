#!/usr/bin/env python3
"""Fetch a WaniKani learner's known-item inventory (kanji, vocabulary, kana vocabulary).

Stdlib only — no dependencies. Assignments are fetched fresh every run (the known
set changes daily); subject details are cached by id since they are effectively
immutable.

Usage:
  python3 fetch_inventory.py [--config PATH] [--refresh-subjects] [--quiet]

Output: <data_dir>/inventory.json plus a stats summary on stdout.
Exit codes: 0 ok, 1 config/token problem, 2 API problem.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.wanikani.com/v2"
DEFAULT_CONFIG = os.environ.get("WANIKANI_STORY_CONFIG",
                                "~/.config/wanikani-story/config.json")
SRS_NAMES = {
    0: "lesson", 1: "apprentice1", 2: "apprentice2", 3: "apprentice3",
    4: "apprentice4", 5: "guru1", 6: "guru2", 7: "master",
    8: "enlightened", 9: "burned",
}


def die(code, msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_config(path):
    p = Path(path).expanduser()
    if not p.exists():
        die(1, f"config not found at {p} — copy config.example.json there and edit it")
    with open(p) as f:
        return json.load(f)


def resolve_token(cfg):
    tok = os.environ.get("WANIKANI_TOKEN")
    if tok:
        return tok.strip()
    tp = Path(cfg.get("token_path", "~/.config/wanikani-story/token")).expanduser()
    if not tp.exists():
        die(1, f"no WANIKANI_TOKEN env var and no token file at {tp}")
    return tp.read_text().strip()


def api_get(url, token, retries=3):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Wanikani-Revision": "20170710",
    })
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                die(1, "WaniKani rejected the token (401) — check your API token")
            if e.code == 429 and attempt < retries - 1:
                time.sleep(10)  # rate limited: 60 req/min, wait and retry
                continue
            die(2, f"WaniKani API error {e.code} on {url}")
        except urllib.error.URLError as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            die(2, f"network error: {e.reason}")


def api_get_all(url, token):
    data = []
    while url:
        page = api_get(url, token)
        data.extend(page["data"])
        url = page["pages"]["next_url"]
    return data


def slim_subject(s):
    d = s["data"]
    out = {
        "object": s["object"],
        "characters": d.get("characters"),
        "level": d["level"],
        "meaning": next(m["meaning"] for m in d["meanings"] if m["primary"]),
    }
    if s["object"] in ("kanji", "vocabulary"):
        readings = d.get("readings", [])
        primary = next((r["reading"] for r in readings if r["primary"]), None)
        out["reading"] = primary
        if s["object"] == "kanji":
            out["accepted_readings"] = [r["reading"] for r in readings
                                        if r.get("accepted_answer")]
    if "parts_of_speech" in d:
        out["pos"] = d["parts_of_speech"]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--refresh-subjects", action="store_true",
                    help="ignore the subject cache and refetch everything")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    token = resolve_token(cfg)
    data_dir = Path(cfg.get("data_dir", "~/.config/wanikani-story")).expanduser()
    cache_dir = data_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # --- user level (1 request) ---
    user = api_get(f"{API}/user", token)["data"]
    level = user["level"]

    # --- assignments: always fresh (this is the part that changes daily) ---
    assignments = api_get_all(
        f"{API}/assignments?subject_types=kanji,vocabulary,kana_vocabulary&started=true",
        token)
    srs_by_id = {a["data"]["subject_id"]: a["data"]["srs_stage"] for a in assignments}

    # --- subjects: cached by id, immutable enough ---
    cache_path = cache_dir / "subjects.json"
    cache = {}
    if cache_path.exists() and not args.refresh_subjects:
        cache = json.loads(cache_path.read_text())
    missing = [str(i) for i in srs_by_id if str(i) not in cache]
    for i in range(0, len(missing), 300):
        batch = ",".join(missing[i:i + 300])
        for s in api_get_all(f"{API}/subjects?ids={batch}", token):
            cache[str(s["id"])] = slim_subject(s)
    if missing:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False))

    # --- build inventory ---
    inv = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "wanikani_level": level,
        "kanji": {},        # char -> {srs, srs_name, level, meaning, readings}
        "vocab": {},        # word -> {srs, srs_name, level, reading, meaning, pos}
        "kana_vocab": {},   # word -> {srs, srs_name, level, meaning, pos}
        "featured": [],     # recently learned (apprentice/guru), for deliberate reuse
    }
    for sid, srs in srs_by_id.items():
        s = cache.get(str(sid))
        if not s or s.get("characters") is None:
            continue
        chars = s["characters"]
        base = {"srs": srs, "srs_name": SRS_NAMES[srs], "level": s["level"],
                "meaning": s["meaning"]}
        if s["object"] == "kanji":
            inv["kanji"][chars] = {**base, "readings": s.get("accepted_readings", [])}
        elif s["object"] == "vocabulary":
            inv["vocab"][chars] = {**base, "reading": s.get("reading"),
                                   "pos": s.get("pos", [])}
        else:
            inv["kana_vocab"][chars] = {**base, "pos": s.get("pos", [])}
        if 1 <= srs <= 6:  # apprentice + guru = learned recently, still fragile
            inv["featured"].append({
                "characters": chars, "type": s["object"], "srs": srs,
                "meaning": s["meaning"],
                "reading": s.get("reading") or ",".join(s.get("accepted_readings", [])),
            })
    inv["featured"].sort(key=lambda x: x["srs"])

    out_path = data_dir / "inventory.json"
    out_path.write_text(json.dumps(inv, ensure_ascii=False, indent=1))

    if not args.quiet:
        nf = len(inv["featured"])
        print(f"level {level} | kanji {len(inv['kanji'])} | vocab {len(inv['vocab'])} "
              f"| kana vocab {len(inv['kana_vocab'])} | featured (apprentice/guru) {nf}")
        print(f"wrote {out_path}")
        if nf:
            feats = "  ".join(f"{f['characters']}({f['meaning']})"
                              for f in inv["featured"][:15])
            print(f"featured sample: {feats}")


if __name__ == "__main__":
    main()
