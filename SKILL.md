---
name: wanikani-story
description: Generate a half-page Japanese story constrained to a WaniKani learner's currently-known kanji and vocabulary, fetched live from the WaniKani API. Use when the user asks for a Japanese practice story, a WaniKani story, a new chapter, to continue the learner's series, or to record how the last chapter went. Serial chapters with cliffhanger + A/B choice; every kanji and word mechanically validated against the known set before delivery.
---

# WaniKani Story

Generate one chapter of an ongoing, learner-personalized Japanese serial. The learner's
known set changes daily — always sync before generating. Never deliver a chapter that
has not passed validation.

## 0. Config

Read `~/.config/wanikani-story/config.json` (override via `WANIKANI_STORY_CONFIG` env).
If missing, walk the user through setup: copy `config.example.json` from this skill's
directory, obtain a read-only API token from wanikani.com → Settings → API Tokens,
store it at `token_path`, fill in the learner profile. `data_dir` (default
`~/.config/wanikani-story/`) holds inventory, cache, and series.

## 1. Sync inventory (every run)

```bash
python3 <skill_dir>/scripts/fetch_inventory.py
```

Read `<data_dir>/inventory.json`. Key fields: `kanji` (the hard character set),
`vocab` + `kana_vocab` (the word set), `featured` (apprentice/guru items learned
recently — weave at least `story.featured_min` of them into the chapter; skip any
that would be awkward), `wanikani_level` (for the footer).

## 2. Series state

Series live in `<data_dir>/series/<slug>/`. `state.json` schema:

```json
{
  "title": "…", "genre": "…", "protagonist": "…",
  "chapter": 3,
  "world": "2-3 sentence bible: setting, tone, running elements",
  "threads": ["open plot threads"],
  "last_choice": {"options": {"A": "…", "B": "…"}, "picked": "A"},
  "gloss_history": {"word": {"reading": "…", "meaning": "…", "uses": 2}},
  "comprehension": [
    {"chapter": 2, "mode": "retell", "notes": ["…"],
     "failed_items": ["…"], "failed_patterns": ["…"]}
  ]
}
```

- **Continuing:** ask which choice (A/B) the learner picked, and for 2–3 retell
  bullets (what did they say happened?). Record both in `comprehension`. Infer
  `failed_items`/`failed_patterns` from the retell — a misparse shows up as a wrong
  or missing plot point. If two consecutive chapters show stalls, silently drop one
  grammar tier.
- **New series:** offer a genre menu built from `learner.interests` (5–6 vivid
  premises, one line each). The learner picks genre and protagonist name (their own
  name/handle in katakana works well). Create the state file.
- Every 4–5 chapters, offer the optional "boss level": the learner writes a full
  English translation, reviewed together, ideally attached to a reward. Never make
  it routine or required. Diff it sentence-by-sentence; record misses in
  `comprehension` with `mode: "translation"`.

## 3. Generation contract

Write the chapter in Japanese under ALL of these constraints:

**Hard (validator-enforced):**
- Every kanji character ∈ `inventory.kanji`. No exceptions, no furigana workaround —
  a word whose kanji is unknown is written in kana or avoided.
- Every content word ∈ `vocab` ∪ `kana_vocab` ∪ gloss list. Gloss list ≤
  `story.max_new_words`, each entry kana-only or composed of known kanji.
- Chapter titles/headers obey the same constraints (e.g. 「その3」, not 第三話 —
  第/話 are typically unknown at low levels).

**Grammar tier** (`grammar_tier` + `grammar_notes` in config):
- **T0** — です/だ, 〜ます/〜ました, particles は が を に で と の へ も, questions
  with か. No て-form, no relative clauses, no plain past.
- **T1** — + plain form incl. past (manga register), negatives, simple て-form
  (sequence/requests), から/でも. Still no relative clauses.
- **T2** — + 〜ている, 〜たい, simple relative clauses.

**Shape:**
- 300–450 Japanese characters (`story.length_chars`). Sentences ≤ ~20 chars.
- Dialogue-heavy manga register: 「…」lines, katakana SFX (ドキドキ、ガタガタ —
  free flavor, no gloss needed if obvious).
- Names in katakana (free). Numerals free.
- Feature ≥ `story.featured_min` recently-learned items naturally.
- Recycle `gloss_history` words with `uses < 3` before introducing new gloss words.
- End on a cliffhanger + a two-option choice (A/B) that steers the next chapter.
- Adapt around `comprehension`: re-expose previously failed items in friendlier
  contexts; avoid failed patterns. Adaptation is invisible — never reference past
  mistakes in the story.

## 4. Validate — loop until clean

```bash
uv run --with fugashi --with unidic-lite <skill_dir>/scripts/validate.py \
  <chapter.md> --gloss "word1,word2" [--json]
```

- Exit 1 (unknown kanji) → rewrite the offending words in kana or rephrase; rerun.
- Unknown words over budget → replace with known vocabulary or cut; rerun.
- Long sentences → split; rerun.
- `featured_used_count` < minimum → work more featured items in; rerun.
- Repeat until exit 0 and the unknown-word list ⊆ declared gloss. Only then deliver.
- fugashi unavailable (no `uv`)? The kanji check still ran — deliver only if exit 0,
  and note that word-level checking was skipped.

## 5. Render — three files, printed separately

The translation only works as an answer key if it can be physically withheld, and a
furigana edition lets the learner self-check readings without the answer key. Write
TWO files into `<data_dir>/series/<slug>/`; the third is generated:

**`NNN-<slug>.md` — the learner's page (Japanese only, larger type):**

```markdown
---
toc: false
fontsize: 14pt
documentclass: extarticle
---

# <Series title> — その<N>「<chapter title>」

<!-- story -->
<story text>

つづく

**Q:** つぎは？ A: <choice A in Japanese, one short line> / B: <choice B>
<!-- /story -->

---

**ことば**（あたらしいことば）

| ことば | よみ | いみ |
|---|---|---|
| … | … | … |

---
*この話は、きみが知っている漢字<N>字だけで書かれている。*
```

**`NNN-<slug>.en.md` — the adult's answer key:**

```markdown
---
toc: false
fontsize: 12pt
---

# <Series title> — Chapter <N> "<chapter title>" — English

<translation, line-for-line so misparses are easy to pinpoint during the retell>

**Next time:** A: <choice A> / B: <choice B>
```

**`NNN-<slug>.furigana.md` — generated from the FINAL validated learner file:**

```bash
uv run --with fugashi --with unidic-lite <skill_dir>/scripts/furigana.py \
  <data_dir>/series/<slug>/NNN-<slug>.md
```

It writes its own front matter (ruby macro, wide line spacing) — never hand-edit it;
regenerate after any change to the learner file.

- The A/B question is *in Japanese inside the story region* — it must pass validation
  too. The gloss box may include English meanings; it sits outside the story markers.
- Footer count = `len(inventory.kanji)`; it grows with the learner — leave it in.
- If `render_cmd` is set in config, run it on ALL THREE files ({file} substituted) so
  each prints separately. Blank line before any markdown list (pandoc quirk). The
  PDF engine must handle CJK fonts (for pandoc/LaTeX: a `CJKmainfont` the system has).

## 6. Update state

Bump `chapter`, append the new choice options, merge gloss words into
`gloss_history` (increment `uses`), update `threads`/`world` if the plot moved.
Confirm to the user: chapter path, validation summary (kanji ✓, N gloss words,
featured items used), and the PDF path if rendered.
