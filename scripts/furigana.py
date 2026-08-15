#!/usr/bin/env python3
"""Produce a furigana edition of a chapter: kana readings stacked over every
kanji word, rendered via a small LaTeX ruby macro (works with pandoc + tectonic,
no CJK LaTeX packages needed).

Run with the tokenizer available:
  uv run --with fugashi --with unidic-lite scripts/furigana.py CHAPTER.md

Writes CHAPTER.furigana.md next to the input (override with -o). Markdown
structure lines (headers, tables, separators, comments) pass through untouched;
prose and dialogue get \\ruby{kanji}{kana} annotations with okurigana split off,
e.g. 走った -> \\ruby{走}{はし}った.
"""

import argparse
import re
import sys
from pathlib import Path

KANJI_RE = re.compile(r"[㐀-䶿一-鿿]")

FRONT_MATTER = """\
---
toc: false
fontsize: 14pt
documentclass: extarticle
hyperrefoptions:
  - bookmarks=false
header-includes: |
  \\usepackage{stackengine}
  \\usepackage{setspace}
  \\setstretch{1.9}
  \\newcommand{\\ruby}[2]{\\stackon[2.5pt]{#1}{\\footnotesize #2}}
---

"""


def kata_to_hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def ruby_word(surface, reading):
    """Split shared kana prefix/suffix (okurigana) so ruby covers only kanji."""
    i = 0
    while (i < len(surface) and i < len(reading) and surface[i] == reading[i]):
        i += 1
    j = 0
    while (j < len(surface) - i and j < len(reading) - i
           and surface[len(surface) - 1 - j] == reading[len(reading) - 1 - j]):
        j += 1
    core = surface[i:len(surface) - j]
    core_read = reading[i:len(reading) - j]
    if not core or not core_read or not KANJI_RE.search(core):
        return surface
    return f"{surface[:i]}\\ruby{{{core}}}{{{core_read}}}{surface[len(surface) - j:]}"


def annotate_line(line, tagger):
    if not KANJI_RE.search(line):
        return line
    out, ptr = [], 0
    for tok in tagger(line):
        surface = tok.surface
        idx = line.find(surface, ptr)
        if idx < 0:
            continue
        out.append(line[ptr:idx])
        kana = tok.feature.kana
        # UniDic reads bare 何 as ナン; that's only right fused with だ/で/と.
        # Standalone (before ？、。」 or end of line) it's なに.
        if surface == "何" and kana == "ナン":
            nxt = line[idx + 1:idx + 2]
            if nxt in ("", "？", "?", "。", "、", "」"):
                kana = "ナニ"
        # UniDic reads 言う/言え as spoken ユウ/ユエ; written furigana is イウ/イエ
        if surface.startswith("言") and kana and kana.startswith("ユ"):
            kana = "イ" + kana[1:]
        if KANJI_RE.search(surface) and kana and kana != "*":
            out.append(ruby_word(surface, kata_to_hira(kana)))
        else:
            out.append(surface)
        ptr = idx + len(surface)
    out.append(line[ptr:])
    return "".join(out)


def skip_line(line):
    s = line.lstrip()
    return (s.startswith("#") or s.startswith("|") or s.startswith("<!--")
            or s.startswith("---") or s.startswith("<div"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    try:
        import fugashi
    except ImportError:
        print("error: fugashi not available — run under "
              "`uv run --with fugashi --with unidic-lite`", file=sys.stderr)
        sys.exit(2)
    tagger = fugashi.Tagger()

    src = Path(args.chapter)
    text = src.read_text()
    # drop an existing front matter block (even below leading HTML comments,
    # e.g. the repo example's header note); we write our own
    text = re.sub(r"\A(\s*(?:<!--.*?-->\s*)*)---\n.*?\n---\n", r"\1", text,
                  flags=re.S)

    lines = []
    broke_page = False
    story_ended = False
    for l in text.splitlines():
        s = l.strip()
        # ruby line-spacing inflates the page: give the story (+ panel + A/B
        # choice) page 1 to itself, and start a fresh page at the first rule
        # after the story so the footer and the word tables travel together.
        # Literal \newpage lines after that are dropped (they'd re-split them).
        if s == "<!-- /story -->":
            story_ended = True
        if story_ended and not broke_page and s == "---":
            lines.append("\\newpage")
            lines.append("")
            broke_page = True
        if broke_page and s == "\\newpage":
            continue
        if not broke_page and s.startswith("**ことば**"):
            lines.append("\\newpage")
            lines.append("")
            broke_page = True
        # shrink the embedded chapter panel so the taller ruby lines still
        # leave the whole story on page 1
        if s.startswith("!["):
            lines.append(re.sub(r"\{width=[^}]+\}", "{width=50%}", l))
            continue
        lines.append(l if skip_line(l) else annotate_line(l, tagger))
    out = Path(args.output) if args.output else src.with_suffix("").with_suffix("")
    if not args.output:
        out = src.parent / (src.name[:-3] + ".furigana.md")
    out.write_text(FRONT_MATTER + "\n".join(lines) + "\n")
    print(out)


if __name__ == "__main__":
    main()
