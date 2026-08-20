#!/usr/bin/env python3
"""Install a kana word pack: pre-taught words the story generator may use freely.

Why this exists: WaniKani's low levels are noun-heavy. A level-6 learner knows
hundreds of nouns but only ~60 verbs and ~35 adjectives — none of them
run/hide/find/shout/grab — so serial chapters start repeating themselves after
two or three instalments. The shortage is verbs, not kanji.

A learner who reads kana can read any word written in kana, whether or not
WaniKani has taught it; that is exactly how Japanese children's books work
(hard limits on kanji, none on kana vocabulary). This script pre-teaches a pack
of such words on one printed sheet, then adds them to `allowlist_extra` so the
generator can use them without spending gloss budget. The kanji rule is never
relaxed — only the word rule.

Words the learner already knows are dropped from the sheet automatically (they
need no teaching and already validate).

Usage:
  python3 wordpack.py [--pack 01-kana-core] [--config PATH] [--list] [--render]

Output: <data_dir>/wordpack-<id>.md  (+ PDF with --render)
        config.allowlist_extra updated in place (union — packs stack)
Exit codes: 0 ok, 1 config/pack problem.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from fetch_inventory import DEFAULT_CONFIG, die, load_config

PACK_DIR = Path(__file__).resolve().parent.parent / "wordpacks"


def load_known(data_dir):
    """Everything the learner can already read without teaching."""
    inv_path = data_dir / "inventory.json"
    if not inv_path.exists():
        die(1, f"no inventory at {inv_path} — run fetch_inventory.py first")
    inv = json.loads(inv_path.read_text())
    known = set(inv["vocab"]) | set(inv["kana_vocab"])
    known |= {v["reading"] for v in inv["vocab"].values() if v.get("reading")}
    try:  # the validator's built-in glue list needs no teaching either
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from validate import ALLOWLIST
        known |= ALLOWLIST
    except Exception:
        pass
    return known


def render_sheet(pack, groups):
    L = [f"# {pack['title']}\n", f"*{pack['subtitle']}*\n", pack["intro"] + "\n"]
    for title, words in groups:
        L += [f"\n## {title}\n", "| ことば | English |", "| --- | --- |"]
        L += [f"| {w} | {m} |" for w, m in words]
        L.append("")
    L += ["\n---\n", pack["outro"] + "\n"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pack", default="01-kana-core")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--list", action="store_true", help="list available packs and exit")
    ap.add_argument("--render", action="store_true", help="also render a PDF via render_cmd")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.list:
        for p in sorted(PACK_DIR.glob("*.json")):
            d = json.loads(p.read_text())
            n = sum(len(g["words"]) for g in d["groups"])
            print(f"{d['id']:16s} {n:3d} words  {d['subtitle']}")
        return

    pack_path = PACK_DIR / f"{args.pack}.json"
    if not pack_path.exists():
        die(1, f"no pack '{args.pack}' in {PACK_DIR} (try --list)")
    pack = json.loads(pack_path.read_text())

    cfg_path = Path(args.config).expanduser()
    cfg = load_config(args.config)
    data_dir = Path(cfg.get("data_dir", "~/.config/wanikani-story")).expanduser()
    known = load_known(data_dir)

    groups, new, skipped = [], [], []
    for g in pack["groups"]:
        keep = [(w, m) for w, m in g["words"] if w not in known]
        skipped += [w for w, _ in g["words"] if w in known]
        if keep:
            groups.append((g["title"], keep))
            new += [w for w, _ in keep]

    if not new:
        print(f"nothing to teach — the learner already knows every word in '{args.pack}'")
        return

    sheet = data_dir / f"wordpack-{pack['id']}.md"
    sheet.write_text(render_sheet(pack, groups))

    # union, so packs stack and re-running is idempotent
    before = list(cfg.get("allowlist_extra", []))
    cfg["allowlist_extra"] = sorted(set(before) | set(new))
    cfg.setdefault("story", {}).setdefault("wordpack_min", 4)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))

    pdf = None
    if args.render and cfg.get("render_cmd"):
        cmd = cfg["render_cmd"].replace("{file}", str(sheet))
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        pdf = sheet.with_suffix(".pdf") if r.returncode == 0 else None
        if pdf is None:
            print(f"warning: render failed: {r.stderr.strip()[:200]}", file=sys.stderr)

    if not args.quiet:
        print(f"pack '{pack['id']}': {len(new)} words added, "
              f"{len(skipped)} already known and skipped")
        print(f"allowlist_extra: {len(before)} -> {len(cfg['allowlist_extra'])}")
        print(f"wrote {sheet}" + (f" and {pdf}" if pdf else ""))
        print("print the sheet and give it to the learner BEFORE the next chapter — "
              "the words must be seen once for the payoff")


if __name__ == "__main__":
    main()
