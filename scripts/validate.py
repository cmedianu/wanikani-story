#!/usr/bin/env python3
"""Validate a generated story against a WaniKani learner's inventory.

Hard rule:   every kanji character must be in the learner's known set (exit 1 if not).
Soft rules:  content words should be in the learner's vocabulary, the gloss list,
             or the grammar-glue allowlist; sentences should be short; featured
             (recently learned) items should appear. These are reported for the
             generation loop to judge, not hard failures.

Word-level checking needs a tokenizer. Run with:
  uv run --with fugashi --with unidic-lite scripts/validate.py CHAPTER.md [options]
Without fugashi it degrades to kanji-check only (still authoritative for the hard rule).

The kanji hard check runs on the WHOLE file — title, gloss tables, and the
kanji-count badge reach the learner too, so they obey the same constraint
(write meta text in kana when its kanji are unknown). Word/grammar checks run
on the story body only: the text between <!-- story --> and <!-- /story -->
markers (without markers the whole file is scanned and gloss/translation
sections trigger false positives — use the markers).

Options:
  --config PATH      default $WANIKANI_STORY_CONFIG or ~/.config/wanikani-story/
                     config.json; supplies allowlist_extra and the story.* knobs
  --inventory PATH   default ~/.config/wanikani-story/inventory.json
  --gloss w1,w2      words declared in the chapter's gloss box (allowed as new words)
  --max-new N        new-word budget (default: config story.max_new_words, else 5)
  --json             machine-readable output
Exit: 0 clean, 1 kanji violations present, 2 usage/input error.
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

# Grammar glue + ultra-basic words a kana-reading learner handles without study.
# Content words are checked against the learner's vocabulary; these are exempt.
ALLOWLIST = {
    # copula / light verbs / existence
    "ある", "いる", "する", "なる", "やる", "できる", "だ", "です", "ない", "無い",
    # demonstratives & interrogatives (kana forms)
    "これ", "それ", "あれ", "ここ", "そこ", "あそこ", "この", "その", "あの",
    "どこ", "だれ", "なに", "どう", "どんな", "いつ", "こう", "そう",
    # pronouns / people
    "ぼく", "きみ", "みんな", "ひとつ", "ふたつ",
    # common adverbs & connectives
    "でも", "だから", "そして", "それから", "すると", "まだ", "もう", "また",
    "とても", "すこし", "ちょっと", "いっしょ", "ゆっくり", "たくさん", "ずっと",
    "やっと", "すぐ", "もっと", "いちばん", "ほんとう", "だめ", "いい", "よい",
    "つぎ", "まえ", "うしろ", "みんな", "いっぱい",
    # frequent yes/no & interjections
    "はい", "いいえ", "うん", "ええ", "あっ", "えっ", "わあ", "おい", "ほら", "ね", "よ",
    # ultra-common verbs kids meet in kana constantly (Duolingo/anime staples)
    "たべる", "のむ", "ねる", "おきる", "まつ", "もつ", "とる", "つく", "あく",
    "しまう", "くれる", "あげる", "もらう", "おもう", "しる", "わかる", "きく", "よぶ",
}

KANJI_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
JA_RE = re.compile(r"[぀-ヿ㐀-鿿]")


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def kata_to_hira(s):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def extract_story(text):
    m = re.search(r"<!--\s*story\s*-->(.*?)<!--\s*/story\s*-->", text, re.S)
    return (m.group(1), True) if m else (text, False)


def check_kanji(story, known_kanji):
    violations = {}
    for i, ch in enumerate(story):
        if KANJI_RE.match(ch) and ch not in known_kanji:
            ctx = story[max(0, i - 8):i + 9].replace("\n", " ")
            violations.setdefault(ch, []).append(ctx)
    return violations


def check_words(story, inv, gloss, extra_allow):
    """Tokenize and diff content words against known vocabulary. Returns
    (unknown_words, glue_used, checked) — checked False when no tokenizer
    available. glue_used lists particles/conjunctions/copulae and allowlisted
    glue words actually present, so the chapter's つなぎことば decoder table
    can be built (and checked) mechanically. seen_forms carries every token's
    surface/lemma/orthBase so featured items can be matched even conjugated."""
    try:
        import fugashi  # noqa
    except ImportError:
        return {}, [], set(), False
    tagger = fugashi.Tagger()

    known = set(inv["vocab"]) | set(inv["kana_vocab"]) | set(inv["kanji"])
    # readings of known vocab let kana-spelled known words match (e.g. known 犬 read いぬ)
    known_readings = {v["reading"] for v in inv["vocab"].values() if v.get("reading")}
    allow = ALLOWLIST | set(extra_allow) | set(gloss)
    content_pos = {"名詞", "動詞", "形容詞", "形状詞", "副詞", "接尾辞", "連体詞"}

    unknown = {}
    glue = set()
    seen_forms = set()
    for word in tagger(story):
        pos1 = word.feature.pos1
        seen_forms.update(x for x in (word.surface, word.feature.lemma,
                                      word.feature.orthBase) if x)
        if (pos1 in ("助詞", "接続詞", "助動詞", "代名詞")
                and JA_RE.search(word.surface)):
            glue.add(word.surface)
            continue
        if pos1 not in content_pos:
            continue
        if pos1 == "名詞" and word.feature.pos2 in ("固有名詞", "数詞"):
            continue  # proper nouns (character names) and numerals are free
        surface = word.surface
        if not JA_RE.search(surface):
            continue
        lemma = word.feature.lemma or surface
        orth_base = word.feature.orthBase or surface
        hira = kata_to_hira(surface)
        candidates = {surface, lemma, orth_base, hira, kata_to_hira(orth_base),
                      unicodedata.normalize("NFKC", lemma).split("-")[0]}
        if candidates & ALLOWLIST:
            glue.add(min(candidates & ALLOWLIST))  # dictionary form, not stem
            continue
        if candidates & (known | allow):
            continue
        if hira in known_readings or kata_to_hira(orth_base) in known_readings:
            continue
        # katakana-only tokens: loanwords/SFX/names — free flavor, skip
        if re.fullmatch(r"[゠-ヿー]+", surface):
            continue
        # multi-token gloss phrases (e.g. ひさしぶり → ひさし+ぶり): a token that
        # only occurs inside a declared gloss phrase is covered by that gloss
        if any(surface in g for g in gloss):
            continue
        unknown.setdefault(orth_base if JA_RE.search(orth_base) else surface,
                           []).append(surface)
    return unknown, sorted(glue), seen_forms, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter")
    ap.add_argument("--config",
                    default=os.environ.get("WANIKANI_STORY_CONFIG",
                                           "~/.config/wanikani-story/config.json"))
    ap.add_argument("--inventory",
                    default="~/.config/wanikani-story/inventory.json")
    ap.add_argument("--gloss", default="")
    ap.add_argument("--max-new", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    chap_path = Path(args.chapter)
    if not chap_path.exists():
        die(f"chapter file not found: {chap_path}")
    inv_path = Path(args.inventory).expanduser()
    if not inv_path.exists():
        die(f"inventory not found: {inv_path} — run fetch_inventory.py first")
    inv = json.loads(inv_path.read_text())
    gloss = [g.strip() for g in args.gloss.split(",") if g.strip()]

    cfg_path = Path(args.config).expanduser()
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    story_cfg = cfg.get("story", {})
    extra_allow = cfg.get("allowlist_extra", [])
    max_new = args.max_new if args.max_new is not None \
        else story_cfg.get("max_new_words", 5)
    max_sentence = story_cfg.get("max_sentence_chars", 20)
    featured_min = story_cfg.get("featured_min", 3)

    full_text = chap_path.read_text()
    story, had_markers = extract_story(full_text)

    # hard kanji rule covers the WHOLE page (title, tables, badge line),
    # not just the story body — everything printed reaches the learner
    kanji_violations = check_kanji(full_text, set(inv["kanji"]))
    unknown_words, glue_used, seen_forms, words_checked = \
        check_words(story, inv, gloss, extra_allow)

    # stats
    ja_chars = JA_RE.findall(story)
    sentences = [s.strip() for s in re.split(r"[。！？\n]", story)
                 if JA_RE.search(s or "")]
    long_sentences = [s for s in sentences
                      if len(JA_RE.findall(s)) > max_sentence]
    # substring match catches nouns; seen_forms catches conjugated verbs
    # (featured 走る appearing only as 走った still counts)
    featured_used = sorted({f["characters"] for f in inv.get("featured", [])
                            if f["characters"] in story
                            or f["characters"] in seen_forms})

    result = {
        "ok": not kanji_violations,
        "markers_found": had_markers,
        "kanji_violations": {k: v[:3] for k, v in kanji_violations.items()},
        "words_checked": words_checked,
        "unknown_words": {k: v[:3] for k, v in unknown_words.items()},
        "unknown_word_count": len(unknown_words),
        "glue_used": glue_used,
        "new_word_budget": max_new,
        "gloss_declared": gloss,
        "japanese_chars": len(ja_chars),
        "sentences": len(sentences),
        "long_sentences": long_sentences,
        "featured_used": featured_used,
        "featured_used_count": len(featured_used),
        "featured_min": featured_min,
        "featured_ok": len(featured_used) >= featured_min,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"story region: {'markers' if had_markers else 'WHOLE FILE (no markers!)'}"
              f" | {len(ja_chars)} ja chars | {len(sentences)} sentences")
        if kanji_violations:
            print(f"\nHARD FAIL — {len(kanji_violations)} unknown kanji:")
            for k, ctxs in kanji_violations.items():
                print(f"  {k}  e.g. …{ctxs[0]}…")
        else:
            print("kanji: all known ✓")
        if not words_checked:
            print("words: NOT CHECKED (fugashi unavailable — run under "
                  "`uv run --with fugashi --with unidic-lite`)")
        elif unknown_words:
            over = "OVER BUDGET" if len(unknown_words) > max_new else "within budget"
            print(f"words: {len(unknown_words)} outside inventory+gloss ({over}):")
            for w, surfaces in unknown_words.items():
                print(f"  {w}  (as: {', '.join(dict.fromkeys(surfaces))})")
        else:
            print("words: all in inventory/gloss/allowlist ✓")
        if glue_used:
            print(f"glue used ({len(glue_used)} — decoder table should cover "
                  f"these): {'、'.join(glue_used)}")
        if long_sentences:
            print(f"long sentences (>{max_sentence} ja chars): {len(long_sentences)}")
            for s in long_sentences[:3]:
                print(f"  {s[:40]}")
        mark = "✓" if len(featured_used) >= featured_min else "BELOW MINIMUM"
        print(f"featured items used: {len(featured_used)}/{featured_min} {mark}"
              + (f" ({'、'.join(featured_used[:10])}…)" if featured_used else ""))

    sys.exit(1 if kanji_violations else 0)


if __name__ == "__main__":
    main()
