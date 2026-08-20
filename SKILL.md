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

**Word pack (once per learner).** If `allowlist_extra` is empty, install one after
the first inventory sync — `python3 <skill_dir>/scripts/wordpack.py --render` —
and tell the user to print the sheet it writes. Without it the generator has only
WaniKani's vocabulary to work with, which at low levels is overwhelmingly nouns,
and chapters start repeating themselves around chapter 3. See §3.

## 1. Sync inventory (every run)

```bash
python3 <skill_dir>/scripts/fetch_inventory.py
python3 <skill_dir>/scripts/fetch_activity.py --quiet
```

The second call snapshots study activity. It is not needed to write a chapter, but
per-day review volume cannot be recovered from the API after the fact — only
diffed between snapshots — so taking one on every run is what keeps the
`wanikani-progress` history dense. Never block a chapter on it.

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
- **Ask for the markup.** The highest-value signal is the learner's own pen: hand
  back the printed chapter and ask them to underline every word or ending they
  didn't understand. That markup (a photo of the page is enough) drives the decoder
  guide in §8 — and a chapter is not "done" until its marks are answered. Do not
  generate the next chapter while an unanswered markup is outstanding.
- **New series:** offer a genre menu built from `learner.interests` (5–6 vivid
  premises, one line each). The learner picks genre and protagonist name (their own
  name/handle in katakana works well). Create the state file. If `image.enabled`,
  also create the **cast pack** now (format: `characters/FORMAT.md` in this skill's
  directory): write `<series>/character/cast.md` (1–3 locked characters and the
  `Style:` line), render a cast model sheet with `scripts/illustrate.py` (all cast,
  neutral standing, white background, the pack's style block, the NO-TEXT block),
  get the user's approval, save as `<series>/character/reference.<style>.png`. It is
  the permanent image ref for every panel — never regenerate it casually.
  For a **color** style, run the grayscale check in `characters/FORMAT.md` on the
  sheet *before* asking for approval — chapters print on a B&W printer by default,
  and touching areas of equal lightness merge into one shape there. Record the
  measured values in the pack's **Colors** bullet; re-roll if two touching areas
  are too close.
- Every 4–5 chapters, offer the optional "boss level": the learner writes a full
  translation (in any configured `translations` language — see §6), reviewed
  together against that language's answer key, ideally attached to a reward. Never make
  it routine or required. Diff it sentence-by-sentence; record misses in
  `comprehension` with `mode: "translation"`.

## 3. Generation contract

Write the chapter in Japanese under ALL of these constraints:

**Hard (validator-enforced):**
- Every kanji character ∈ `inventory.kanji`. No exceptions, no furigana workaround —
  a word whose kanji is unknown is written in kana or avoided.
- Every content word ∈ `vocab` ∪ `kana_vocab` ∪ `allowlist_extra` (the kana word
  pack) ∪ gloss list. Gloss list ≤ `story.max_new_words`, each entry kana-only or
  composed of known kanji.
- Chapter titles/headers obey the same constraints (e.g. 「その3」, not 第三話 —
  第/話 are typically unknown at low levels).

**Grammar tier** (`grammar_tier` + `grammar_notes` in config):
- **T0** — です/だ, 〜ます/〜ました, particles は が を に で と の へ も, questions
  with か. No て-form, no relative clauses, no plain past.
- **T1** — + plain form incl. past (manga register), negatives, simple て-form
  (sequence/requests), から/でも. Still no relative clauses.
- **T2** — + 〜ている, 〜たい, simple relative clauses.

**Shape:**
- 300–450 Japanese characters (`story.length_chars`). Sentences ≤
  `story.max_sentence_chars`.
- Dialogue-heavy manga register: 「…」lines, katakana SFX (ドキドキ、ガタガタ —
  free flavor, no gloss needed if obvious).
- Names in katakana (free). Numerals free.
- Feature ≥ `story.featured_min` recently-learned items naturally.
- Use ≥ `story.wordpack_min` distinct words from `allowlist_extra` (skip this rule
  if the pack is not installed — offer to install one instead, §0). **This is the
  main lever against repetitive chapters.** WaniKani's low levels are noun-heavy —
  a level-6 learner has hundreds of nouns but only ~60 verbs and ~35 adjectives,
  none of which are run/hide/find/shout/grab. The kana word pack supplies those.
  A word written in kana is readable whether or not WaniKani has taught it, which
  is exactly how Japanese children's books work: hard limits on kanji, none on kana
  vocabulary. Pack words are pre-taught on a printed sheet, so they cost no gloss
  budget — reach for them freely rather than rewriting the same scene with 入る and
  見る. The kanji rule above is never relaxed; only the word rule is.
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

- The kanji hard check covers the WHOLE file — title, gloss tables, badge line —
  not just the story region; anything printed reaches the learner. Word checks
  stay inside the story markers. The validator reads `allowlist_extra` and the
  `story.*` knobs from config automatically (`--config` / `WANIKANI_STORY_CONFIG`
  to override).
- Exit 1 (unknown kanji) → rewrite the offending words in kana or rephrase; rerun.
- Unknown words over budget → replace with known vocabulary or cut; rerun.
- Long sentences → split; rerun.
- `featured_used_count` < minimum → work more featured items in; rerun.
- Repeat until exit 0 and the unknown-word list ⊆ declared gloss. Only then deliver.
- Cross-check `glue_used` against the chapter's つなぎことば decoder table (see §5) —
  every reported item must be covered by a row. The tokenizer splits fused
  connectives (でも → で+も, だから → だ+から, すると → する+と); one row for the
  fused word as the reader meets it covers its pieces.
- fugashi unavailable (no `uv`)? The kanji check still ran — deliver only if exit 0,
  and note that word-level checking was skipped.

## 5. Illustrate (optional — only when config `image.enabled`)

One manga panel per chapter, cast kept consistent via the series cast pack
(`<series>/character/` — see `characters/FORMAT.md`). Skip entirely when disabled;
the chapter must never block on image failures — deliver text-only and say so.

- **Scene choice:** the chapter's *setup or mood*, or the visible consequence of
  the learner's last A/B pick (a reward for choosing). NEVER the cliffhanger or
  its resolution — an image that summarizes the plot lets a reluctant reader skip
  the text.
- **Style:** read the `Style:` line in `cast.md` — it names the live style and so
  the files to use: `character/reference.<style>.png` and `<series>/style-anchor.<style>.png`.
  Never mix refs across styles (a B&W anchor pulls a color prompt back to ink).
- **Prompt:** one paragraph scene description (who, where, doing what, mood) +
  the verbatim **Prompt spec (<style>)** block of each cast member in the scene +
  that style's STYLE block + the NO-TEXT block from `characters/FORMAT.md` + an
  aspect note (16:9 wide panel). Incidental characters are described inline.
- **Generate** (backend auto-resolves: Codex CLI → Grok CLI → OpenRouter key):

```bash
python3 <skill_dir>/scripts/illustrate.py --prompt-file /tmp/panel.txt \
  --ref <series>/character/reference.<style>.png [--ref <series>/style-anchor.<style>.png] \
  --out <series>/NNN-<slug>.png
```

- **QA — reject and re-roll if:** any text/writing/pseudo-kanji appears anywhere
  (hard rule — garbled kanji breaks the "every character is known" contract);
  a cast member is off-model; the scene spoils the cliffhanger; or — color styles —
  the panel's palette drifts off the pack's recorded value ladder, so the figure
  loses its silhouette in grayscale.
- The first accepted panel *in the live style* is copied to
  `<series>/style-anchor.<style>.png` and passed as a second `--ref` on all later
  chapters, so the serial reads as one artist. A style switch starts a fresh
  anchor; earlier chapters keep the art they shipped with.
- **Embed** in the learner page AND (via regeneration) the furigana page —
  between the title heading and `<!-- story -->`, absolute path (pandoc resolves
  relative to CWD, not the file):

```markdown
![](/abs/path/to/NNN-<slug>.png){width=65%}
```

## 6. Render — the chapter file set, printed separately

A translation only works as an answer key if it can be physically withheld, and a
furigana edition lets the learner self-check readings without the answer key. Write
the learner's page and one answer key per configured language into
`<data_dir>/series/<slug>/`; the furigana edition is generated from the validated
learner file.

**`NNN-<slug>.md` — the learner's page (Japanese only, larger type):**

```markdown
---
toc: false
fontsize: 14pt
documentclass: extarticle
pagefooter: <series title> その<N>
hyperrefoptions:
  - bookmarks=false
---

# <Series title> — その<N>「<chapter title>」

<!-- story -->
<story text>

つづく

**Q:** つぎは？ A: <choice A in Japanese, one short line> / B: <choice B>
<!-- /story -->

---
*このはなしは、きみがしっているかんじ<N>じだけでかかれている。*

\newpage

**ことば**（あたらしいことば）

| ことば | よみ | いみ |
|---|---|---|
| … | … | … |

**つなぎことば**（ちいさいことば）

| ことば | いみ |
|---|---|
| 〜は | "as for …" (points at the topic) |
| 〜が | marks who/what does it |
| でも | but |
| … | … |
```

The **つなぎことば** decoder table lists EVERY particle, conjunction, copula, and
kana glue word that actually appears in the story (the validator reports them as
`glue_used`) — one row each, particles written 〜は style, meanings short and
kid-friendly. A learner who reads "nouns + verbs only" uses this table to decode
sentence structure; it is a recurring reference, not new vocabulary — it costs
nothing against the gloss budget and repeats every chapter. The `\newpage` keeps
the story (with its kanji-count badge) on page 1 and the whole word sheet on
page 2, so they print cleanly — keep the sheet to one page (merge related rows
like ここ・この if it runs long).

**`NNN-<slug>.<code>.md` — the answer keys, one per configured language:**

Config `translations` maps a file-suffix code to a language name; when the key is
absent, default to `{"en": "English"}`. Write ONE file per entry, all from the same
Japanese source — never translate a translation.

```json
"translations": {"en": "English", "ro": "Romanian"}
```

```markdown
---
toc: false
fontsize: 12pt
pagefooter: <series title> その<N> · <CODE>
hyperrefoptions:
  - bookmarks=false
---

# <Series title> — Chapter <N> "<chapter title>" — <language name>

<translation, line-for-line so misparses are easy to pinpoint during the retell>

**Next time:** A: <choice A> / B: <choice B>
```

- Line-for-line means line-for-line **in every language** — the whole point is
  pointing at a line during the retell, so the keys must stay row-aligned with each
  other and with the Japanese. End every body line with **two trailing spaces**
  (markdown hard break) or the renderer reflows the whole key into one prose blob
  and the alignment is lost.
- Translate the *register*, not the words: manga narration, a 13-year-old's voice,
  natural in the target language. Sound effects stay as they'd read in that
  language's comics (ワン → "Woof!" / "Ham!").
- Non-English keys often exist for a second household adult, so they must stand
  alone — never leave English fragments in them.

**`NNN-<slug>.furigana.md` — generated from the FINAL validated learner file:**

```bash
uv run --with fugashi --with unidic-lite <skill_dir>/scripts/furigana.py \
  <data_dir>/series/<slug>/NNN-<slug>.md
```

It writes its own front matter (ruby macro, wide line spacing) — never hand-edit it;
regenerate after any change to the learner file.

- **One sentence per printed line.** End every story line with two trailing spaces
  (markdown hard break) — without them pandoc reflows the chapter into a prose blob and
  the sentence boundaries vanish, which is exactly what a learner who "reads nouns and
  verbs only" cannot recover on their own. It costs about one page; pay it.
- The A/B question is *in Japanese inside the story region* — it must pass validation
  too. The gloss box may include English meanings; it sits outside the story markers.
- Badge count = `len(inventory.kanji)`; it grows with the learner — leave it in. The
  badge line (and every other line on the page — title, tables) must obey the kanji
  constraint like the story does; the validator checks the whole file. Write meta
  text in kana unless its kanji are known.
- **Print single-sided.** The learner page exists to be read slowly and marked up (§8),
  and the word sheet is meant to sit *beside* the story while reading — both jobs a
  duplexed sheet makes worse. Ask for `simplex` when handing these to `cm-print`, and
  note that colour panels want the colour printer.
- **`pagefooter`** goes in every file's front matter: `<series title> その<N>` plus an
  edition tag (`· EN` / `· RO` / `· guide`; the furigana edition tags itself; the
  learner page carries no tag). Both renderers print it with a page number at every
  page bottom, so a pile of mixed-up printed pages can be re-sorted by hand. Keep it
  plain text — no LaTeX special characters.
- Render EVERY file in the set to PDF so each prints separately (learner page,
  furigana edition, and each language's answer key):
  - If `render_cmd` is set in config, run it per file ({file} substituted). Blank
    line before any markdown list (pandoc quirk). The PDF engine must handle CJK
    fonts (for pandoc/LaTeX: a `CJKmainfont` the system has).
  - Otherwise use the built-in renderer (WeasyPrint; needs system Pango, no LaTeX):

    ```bash
    uv run --with weasyprint --with markdown-it-py <skill_dir>/scripts/render.py <file.md>
    ```

## 7. Update state

Bump `chapter`, append the new choice options, merge gloss words into
`gloss_history` (increment `uses`), update `threads`/`world` if the plot moved.

**Checkpoint:** if `data_dir` is a git repository, commit everything after each
delivered chapter, guide, or state change (`git add -A && git commit -m
"chapter N: <slug>"` or similar) and push if a remote is configured. Best-effort —
never block delivery on git. These commits are what make a state rollback (wrong
chapter baked in, comprehension model disproved) a one-command revert instead of
hand surgery, and the committed `inventory.json` history doubles as a record of the
learner's growth over time.

Confirm to the user: chapter path, validation summary (kanji ✓, N gloss words,
featured items used), whether a panel was generated, and the PDF path if rendered.

## 8. Decoder guide — when the learner marks up a chapter

WaniKani teaches zero grammar, so at some point the grammar has to be taught outright.
Do it **against a chapter they have already read and liked**, never as an abstract
lesson — the story supplies the motivation and every example sentence.

Trigger: the learner hands back a marked-up chapter (see §2). Write
`<data_dir>/series/<slug>/NNN-<slug>.guide.md` and render it like any other file
(front matter: `pagefooter: <series title> その<N> · guide`).

- **Answer every single mark, in reading order, and nothing else.** The marks are the
  syllabus. Do not "round out" the grammar with unmarked points — an underline is a
  question actually asked, and a guide that answers questions nobody asked reads as
  homework.
- **Lead with the one rule that collapses the most marks.** Cluster first: a page of
  underlines is usually two or three patterns, not twelve unrelated facts. Teach that
  rule up front, then let each mark be an instance of it.
- **Every example comes from their chapter**, quoted exactly as printed.
- Useful sections, in this order: the big rule; a cheat-sheet table of the shapes;
  each mark one at a time (sentence, breakdown, translation); a full verb table for
  the chapter (story form → dictionary form → meaning, self-quizzable by covering a
  column); the glue-word table; and 4–6 self-check questions with answers.
- Written in the learner's native language, not Japanese — this is the one artifact
  that is allowed to be, and must be, entirely in a language they read fluently.

**Then the next chapter reinforces it.** Record the taught points in `comprehension`,
raise `grammar_tier` if they landed, and set `grammar_notes` to reinforcement mode:
re-use exactly those patterns, one conjugation per sentence, recurring verbs, at least
one clear instance of each taught shape. Add a third table to that chapter's word
sheet — **おぼえて！** — mapping each shape from the guide to the line it appears on in
the new chapter, so guide and chapter cross-reference each other. If the next markup
shows the same shapes failing again, drop the tier back rather than re-teaching.
