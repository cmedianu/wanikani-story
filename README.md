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
  and an A/B choice at the end of each chapter that steers the next one. The English
  translation is a separate answer-key file, printed only when you choose to.
- **Adapts from comprehension feedback** — a 60-second verbal retell after each
  chapter (plus the coherence of their A/B choice) tells the generator what didn't
  land; failed words come back in friendlier contexts, silently.

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

3. Install the skill:

   ```bash
   ln -s "$(pwd)" ~/.claude/skills/wanikani-story
   ```

4. In Claude Code: *"new chapter"*, *"start a new story series"*, or *"Luca picked B
   and said the dog found a door"* — the skill handles sync → feedback → generate →
   validate → render. Each chapter yields three printable files: the learner's page,
   a furigana edition, and a separate English answer key.

Requirements: Python 3.9+ (fetcher is stdlib-only), [`uv`](https://docs.astral.sh/uv/)
for the word-level validator (`fugashi` + `unidic-lite`, fetched on demand).

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

## How the constraint actually works

Three layers, because "only kanji they know" is necessary but not sufficient:

1. **Character level (hard):** every kanji in the story ∈ the learner's started set.
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
scripts/fetch_inventory.py  # WaniKani API → inventory.json (stdlib only)
scripts/validate.py         # story vs inventory (kanji hard-check + fugashi word check)
scripts/furigana.py         # learner page → furigana edition (ruby over every kanji)
```

All learner data (token, profile, generated chapters, series state) lives under
`~/.config/wanikani-story/` — the repo contains no personal data.

## License

MIT
