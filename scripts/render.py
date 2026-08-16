#!/usr/bin/env python3
"""Render a chapter markdown file to PDF with WeasyPrint — a Python
alternative to the pandoc+tectonic `md2pdf` path, so the skill has a
render fallback with no LaTeX toolchain. Run with deps available:

  uv run --with weasyprint --with markdown-it-py scripts/render.py CHAPTER.md

Understands the chapter conventions this skill emits:
  - YAML front matter (fontsize and pagefooter are honored; LaTeX-only keys
    are ignored). pagefooter puts "<text> · p.N" on every page bottom so
    mixed-up printed pages can be re-sorted.
  - \\newpage on its own line -> page break
  - \\ruby{kanji}{kana} (from furigana.py) -> HTML <ruby>, CSS-stacked
  - pandoc-style image attrs: ![](p.png){width=65%}
  - GFM tables

Writes CHAPTER.pdf next to the input (override with -o).
"""

import argparse
import re
import sys
from pathlib import Path

CSS = """
@page { size: letter; margin: 1in; }
body {
  font-family: "DejaVu Serif", "IPAPGothic", serif;
  font-size: FONTSIZE;
  line-height: LINEHEIGHT;
}
h1 { font-size: 1.45em; line-height: 1.4; margin: 0 0 0.8em 0; }
/* chapters set toc:false — keep the PDF outline empty (WeasyPrint otherwise
   builds bookmarks from every heading; CJK renders as tofu in some viewers) */
h1, h2, h3, h4 { bookmark-level: none; }
p { margin: 0.5em 0; }
/* CSS-emulated ruby (WeasyPrint has no native ruby layout). The inline-table
   bottom-aligns to the line box, which drops the base text below its
   neighbors' baseline by roughly the descender —  nudge it back up. */
ruby { display: inline-table; text-align: center; vertical-align: bottom;
       position: relative; top: -0.12em; }
rt   { display: table-header-group; font-size: 0.55em; line-height: 1; }
rb   { display: table-row-group; line-height: 1.15; }
table { border-collapse: collapse; margin: 0.8em auto; line-height: 1.3; }
th { border-top: 1.5px solid #222; border-bottom: 1px solid #222; }
td { border: none; }
th, td { padding: 3px 14px 3px 0; text-align: left; vertical-align: top; }
tbody tr:last-child td { border-bottom: 1.5px solid #222; }
hr { border: none; border-top: 1px solid #444; width: 40%; margin: 1.2em auto; }
img { margin: 0.3em 0; }
.pagebreak { page-break-after: always; }
"""


def preprocess(text):
    """Strip front matter (keeping fontsize + pagefooter), translate the
    LaTeX-isms the chapter files use into HTML the markdown parser passes
    through."""
    fontsize = "12pt"
    pagefooter = None
    # front matter may sit below leading HTML comments (e.g. the repo example)
    m = re.match(r"\A(\s*(?:<!--.*?-->\s*)*)---\n(.*?)\n---\n", text, re.S)
    if m:
        fm = m.group(2)
        fs = re.search(r"^fontsize:\s*(\S+)", fm, re.M)
        if fs:
            fontsize = fs.group(1)
        pf = re.search(r"^pagefooter:\s*(.+)$", fm, re.M)
        if pf:
            pagefooter = pf.group(1).strip().strip("\"'")
        text = m.group(1) + text[m.end():]
    text = re.sub(r"\\ruby\{([^}]*)\}\{([^}]*)\}",
                  r"<ruby><rb>\1</rb><rt>\2</rt></ruby>", text)
    text = re.sub(r"^\\newpage\s*$", '<div class="pagebreak"></div>',
                  text, flags=re.M)
    def img(m):
        path = re.search(r"\((.*?)\)", m.group(1)).group(1)
        return f'<img src="{path}" style="width:{m.group(2)}">'
    text = re.sub(r"(!\[[^\]]*\]\([^)]+\))\{width=([0-9.]+%?)\}", img, text)
    # CommonMark's emphasis flanking rules reject **…** butted against CJK
    # punctuation (e.g. **ことば**（…）); resolve bold before parsing
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", text)
    return text, fontsize, pagefooter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    try:
        from markdown_it import MarkdownIt
        from weasyprint import HTML
    except ImportError:
        print("error: deps missing — run under "
              "`uv run --with weasyprint --with markdown-it-py`",
              file=sys.stderr)
        sys.exit(2)

    src = Path(args.chapter)
    text, fontsize, pagefooter = preprocess(src.read_text())
    # ruby stacking needs taller lines; plain pages read better tighter
    lineheight = "2.1" if "<ruby>" in text else "1.6"

    md = MarkdownIt("commonmark", {"html": True}).enable("table")
    body = md.render(text)
    css = CSS.replace("FONTSIZE", fontsize).replace("LINEHEIGHT", lineheight)
    if pagefooter:
        safe = pagefooter.replace("\\", "\\\\").replace('"', '\\"')
        css += (f'@page {{ @bottom-center {{ content: "{safe} · p." '
                f'counter(page); font-size: 9pt; color: #444; '
                f'font-family: "DejaVu Serif", "IPAPGothic", serif; }} }}\n')
    html = f"<html><head><style>{css}</style></head><body>{body}</body></html>"

    out = Path(args.output) if args.output else src.with_suffix(".pdf")
    HTML(string=html, base_url=str(src.parent)).write_pdf(str(out))
    print(out)


if __name__ == "__main__":
    main()
