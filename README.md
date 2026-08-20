# wanikani-story

A [Claude Code](https://claude.com/claude-code) skill that writes half-page Japanese
stories your learner can *actually read* — constrained, live, to the kanji and
vocabulary they currently know on [WaniKani](https://www.wanikani.com).

## Why

WaniKani teaches thousands of kanji but famously never shows them to you *in the
wild*. Graded readers exist, but they're matched to a standard, not to your learner —
and for a reluctant reader (say, a 13-year-old who'd rather be gaming), a bland
reader about buying stamps doesn't stand a chance against a serial dungeon-crawl
where **they** pick what happens next.

This skill:

- **Syncs the known set on every run** — the WaniKani API says exactly which kanji
  and words the learner knows *today*, and the story grows with them.
- **Features what they learned this week** — items at Apprentice/Guru SRS stages are
  deliberately woven in. Free spaced reinforcement, right where memory is weakest.
- **Mechanically validates every character** — LLMs leak out-of-set kanji; a
  tokenizer-backed validator (`fugashi`) loops generation until the story is provably
  readable. One unreadable character breaks a learner's trust; zero ship.
- **Makes it a serial, not a worksheet** — manga-register chapters, cliffhangers,
  and an A/B choice at the end of each chapter that steers the next one. The
  translation is a separate answer-key file, printed only when you choose to — and
  `translations` in the config takes as many languages as your household needs, so a
  second adult can follow along in theirs.
- **Includes a decoder ring, not just a gloss** — every chapter's word sheet has a
  つなぎことば table listing each particle, conjunction, and glue word the story
  actually uses, with kid-friendly meanings. A learner who parses "nouns + verbs
  only" can look up what the は・が・を between them are doing.
- **Adapts from comprehension feedback** — a 60-second verbal retell after each
  chapter (plus the coherence of their A/B choice) tells the generator what didn't
  land; failed words come back in friendlier contexts, silently.
- **Optionally illustrates each chapter** — one manga panel with a *consistent
  recurring cast* (locked character specs + a reference model sheet on every
  render), in B&W ink or full color — the series picks one in its cast pack and
  can switch back without losing the old sheets — generated free through a
  logged-in Codex/Grok CLI or via OpenRouter. Panels show the chapter's setup, never the cliffhanger — the image
  is the hook to start reading, not a substitute for it. Hard rule: no text in
  images (AI pseudo-kanji would break the "every character is known" promise).

## Setup

1. Get a **read-only API token**: wanikani.com → Settings → API Tokens.
2. Create your local config (never committed — it holds your learner's profile):

   ```bash
   mkdir -p ~/.config/wanikani-story
   cp config.example.json ~/.config/wanikani-story/config.json
   # edit: learner name/age/interests, grammar tier, story knobs
   echo "YOUR_TOKEN" > ~/.config/wanikani-story/token
   chmod 600 ~/.config/wanikani-story/token
   ```

   Recommended: make the data dir a **private** git repo (`git init`, and
   gitignore `token` and `cache/`). The skill then auto-commits after every
   chapter — a botched state update becomes a one-command revert, and the
   committed `inventory.json` history doubles as a record of your learner's
   growth. Keep it private: everything in it is personal.

3. Install the skill:

   ```bash
   ln -s "$(pwd)" ~/.claude/skills/wanikani-story
   ```

4. In Claude Code: *"new chapter"*, *"start a new story series"*, or *"Kenta picked B
   and said the dog found a door"* — the skill handles sync → feedback → generate →
   validate → render. Each chapter yields the learner's page, a furigana edition, and
   one answer key per language in `translations` — each a separate PDF, so the key
   can be withheld until the retell is done.

Requirements: Python 3.9+ (fetcher is stdlib-only), [`uv`](https://docs.astral.sh/uv/)
for the word-level validator (`fugashi` + `unidic-lite`, fetched on demand). PDF
rendering works out of the box via WeasyPrint (`scripts/render.py`, pulled by `uv`;
needs the system Pango library — preinstalled on desktop Linux, `brew install pango`
on macOS). Prefer LaTeX output? A sample pandoc+tectonic wrapper ships in
`bin/md2pdf` — point `render_cmd` at it ("`/path/to/bin/md2pdf {file}`") and it's
used instead; LaTeX typesets long tables slightly tighter.

On Windows, run the skill under WSL: `bin/md2pdf` is a bash script, and WeasyPrint
on native Windows needs a separately installed GTK/Pango runtime. Everything works
out of the box in a WSL Ubuntu shell.

## Tracking how much they actually study

A second skill, **`wanikani-progress`**, answers "how much has she studied this
week?", "is he keeping up?", and "what does she keep getting wrong?".

```bash
ln -s "$(pwd)/progress" ~/.claude/skills/wanikani-progress
python3 scripts/fetch_activity.py          # sync + snapshot
python3 scripts/report_activity.py --period last-week
```

There's a catch worth knowing before you rely on it. WaniKani's per-review log
(`/v2/reviews`) returns **zero records** for read-only tokens on some accounts, so
daily review volume can't be queried after the fact. What the API does expose is
per-subject cumulative answer counters — so `fetch_activity.py` snapshots those and
diffs consecutive snapshots to recover exact answer and error counts per window,
pinned to a day by each item's most recent review timestamp.

The practical upshot: **history only starts accumulating once you start
snapshotting.** Days before that show only how many items were *last* reviewed
then — a floor, not a total — and the report labels them as such rather than
quietly conflating the two. Lessons, Guru passes, burns and level dates are exact
for all of history either way, so a report is useful from day one.

`SKILL.md` step 1 takes a snapshot on every chapter run, which keeps the history
dense for free. For a learner you generate chapters for irregularly, a daily cron
entry is the more reliable option.

Snapshots and derived state are disposable and gitignored; `activity/history.json`
is the one file that cannot be rebuilt from the API, so it's committed with the
rest of your learner data.

## The one important knob: grammar tier

WaniKani teaches **zero grammar** — kanji knowledge is not reading ability. Set
`grammar_tier` honestly:

| Tier | Assumes | Story grammar |
|---|---|---|
| `T0` | no grammar at all | です/ます, basic particles, no conjugation games |
| `T1` | Duolingo-level implicit grammar | plain form + past + negatives, simple て-form |
| `T2` | solid N5 | 〜ている, 〜たい, simple relative clauses |

When in doubt start low: a too-easy story is mildly boring; a too-hard story teaches
a reluctant reader that reading isn't for them.

## Why chapter 3 gets boring — and the fix

Run this for a few chapters and you'll hit a wall that looks like "we've used every
sentence the kanji allow." That diagnosis is wrong, and the real one matters.

WaniKani's low levels are **noun-heavy**. A level-6 learner in our testing knew 173
kanji and 403 words — but **282 of those words were nouns**, leaving ~60 verbs and
~35 adjectives. None of the 60 were *run, hide, find, shout, grab, escape, protect*.
You cannot write an adventure serial with the verb set of a filing cabinet, no matter
how many nouns you have.

The fix rests on an asymmetry the constraint had accidentally collapsed: **a learner
who reads kana can read any word written in kana**, whether or not WaniKani has
taught it. That's how Japanese children's books work — hard limits on kanji, none on
kana vocabulary. So the kanji rule stays absolute; the *word* rule loosens.

```bash
python3 scripts/wordpack.py --render    # after your first inventory sync
```

This installs a pack of high-frequency kana verbs and adjectives, **drops the ones
your learner already knows**, writes a one-page printable sheet, and adds the rest to
`allowlist_extra` so the generator can use them without spending gloss budget. Print
the sheet and hand it over before the next chapter — pre-teaching is what makes the
words free rather than confusing.

Why a pack rather than simply raising `max_new_words`: a 350-character chapter holds
only ~70 content words, so 20 unfamiliar ones inside the story would be ~25% unknown
and unreadable. Graded readers hold ~95% known coverage. Teach outside the story, use
freely inside it.

## How the constraint actually works

Three layers, because "only kanji they know" is necessary but not sufficient:

1. **Character level (hard):** every kanji on the page — story, title, word tables,
   even the kanji-count badge — ∈ the learner's started set.
   Words whose kanji are unknown are written in kana — no furigana crutches
   in the story itself (the separate furigana edition is a self-check aid, not a
   license to use unknown kanji).
2. **Word level:** content words must be in the learner's WaniKani vocabulary, a
   ≤5-word glossed budget of new words, or a small allowlist of grammar glue
   (ある、いる、でも…). Knowing 火 and 山 doesn't mean knowing 火山.
3. **Grammar level:** patterns capped by the tier above.

`scripts/validate.py` enforces layer 1 as a hard failure and reports layers 2–3;
generation loops until clean.

## Repo layout

```
SKILL.md                  # the workflow Claude follows
config.example.json       # copy to ~/.config/wanikani-story/config.json
bin/md2pdf                  # sample pandoc+tectonic render_cmd (CJK auto-detect)
characters/FORMAT.md        # cast-pack format for consistent chapter illustrations
scripts/fetch_inventory.py  # WaniKani API → inventory.json (stdlib only)
scripts/validate.py         # story vs inventory (kanji hard-check + fugashi word check)
scripts/furigana.py         # learner page → furigana edition (ruby over every kanji)
scripts/illustrate.py       # prompt + reference sheet → one panel (codex/grok/openrouter)
scripts/render.py           # chapter markdown → PDF (WeasyPrint; no LaTeX needed)
scripts/wordpack.py         # install a kana word pack (see "Why chapter 3 gets boring")
wordpacks/*.json            # shipped word packs, filtered per learner on install
progress/SKILL.md           # second skill: study-activity reporting
scripts/fetch_activity.py   # WaniKani API → activity snapshots + daily history
scripts/report_activity.py  # activity history → report for any period (no network)
```

All learner data (token, profile, generated chapters, series state, character
sheets) lives under `~/.config/wanikani-story/` — the repo contains no personal
data.

## Credits

The character-consistency pattern (locked prose spec + reference model sheet
passed as an image ref on every render) and the technique for generating images
through a logged-in Codex or Grok CLI are adapted from Trevin Chow's
[illo-skill](https://github.com/tmchow/illo-skill) (MIT).

## License

[MIT](LICENSE)
