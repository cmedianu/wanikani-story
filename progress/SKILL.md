---
name: wanikani-progress
description: Report how much a WaniKani learner is actually studying — reviews per day, accuracy, lessons, streaks, level pace, and the items they keep getting wrong. Use when asked how much someone has studied, how last week went, whether they are keeping up or falling behind, what they are struggling with, or for WaniKani stats over any period.
---

# WaniKani Progress

Answer questions about a learner's study activity from local snapshot history plus
a live API sync. Read-only — this skill never writes to WaniKani.

Scripts live in the sibling `scripts/` directory of this skill's repository
(`<skill_dir>/../scripts/`).

## 0. The one thing to understand about the data

`/v2/reviews`, the per-review log, returns **zero records** for read-only tokens on
some accounts. Check it once for your learner; where it comes back empty, daily
review volume cannot be queried retroactively. It is reconstructed instead by diffing per-subject answer
counters (`/v2/review_statistics`) between snapshots stored in
`<data_dir>/activity/`.

The practical consequence, which you must be honest about in every answer:

- **Measured** days (a snapshot exists on both sides) have exact answer and error
  counts.
- **Observed** days — anything before snapshotting began — only show how many
  items were *last* reviewed that day. That is a floor, never a total, and it
  reads lower the further back you go, because later reviews overwrite the
  timestamp.
- Lessons started, items passed to Guru, items burned, and level dates are exact
  for all of history regardless. Lean on these when review counts are thin.

Never present an observed count as if it were a review count, and never compare a
measured week against an observed one without saying so.

## 1. Sync, then report

```bash
python3 <skill_dir>/../scripts/fetch_activity.py --quiet
python3 <skill_dir>/../scripts/report_activity.py --period last-week
```

`--period` takes `last-week` (rolling 7 days), `last-30d`, `this-level`, `all`, a
single `YYYY-MM-DD`, or a `YYYY-MM-DD:YYYY-MM-DD` range. `--format` takes `text`
(default), `md`, or `json` — use `json` when you want to reason over the numbers
yourself rather than relay a table.

Every report automatically compares against the immediately preceding window of
the same length; `--no-compare` suppresses it.

## 2. Answering well

The report is raw material, not the answer. Read it, then say what happened in
prose — two or three sentences of trend, then only the numbers that carry it. Dump
the full table only if asked for it.

What actually matters when judging whether a learner is keeping up:

- **Lesson intake, not review count.** Reviews are a lagging consequence of
  lessons taken weeks earlier. A quiet review queue usually means no new lessons
  were started, not that the learner is coasting through a heavy load.
- **Level pace against their own baseline.** Compare the current level's elapsed
  days to their median of the last few. WaniKani's floor is ~7 days per level; a
  learner tracking at 3x their own earlier pace has stalled even if daily accuracy
  looks perfect.
- **The SRS shape.** A collection sitting almost entirely at Enlightened/Burned
  with an empty Apprentice band means the review load has evaporated because
  everything is on multi-month intervals — the learner will feel busy-free while
  making no progress. Lessons waiting in the queue is the number to quote.
- **Accuracy above ~97% is a signal, not a triumph.** It usually means the learner
  is looking answers up, or reviewing so little that only easy items come due.
  Say so rather than praising it.
- **Active days over volume.** Consistency predicts retention; a single 300-answer
  Sunday does not.

## 3. Struggling items

The report's leech list is lifetime accuracy per subject, worst first, filtered to
items with enough exposure to mean something. Two uses:

- Answering "what is he struggling with" directly.
- Feeding the `wanikani-story` skill: leeches are exactly the items worth weaving
  into the next chapter for free reinforcement in context. Mention this when the
  list is interesting and a chapter is due.

## 4. State

Lives in `<data_dir>/activity/` (`data_dir` from
`~/.config/wanikani-story/config.json`, override with `WANIKANI_STORY_CONFIG`):

| File | Nature |
| --- | --- |
| `history.json` | append-only per-day series — **unrecoverable if lost**, commit it |
| `latest.json` | current derived state, rewritten every run, disposable |
| `snapshots/*.json` | raw counters for the next diff, last 30 kept, disposable |

If `data_dir` is a git repo, commit `history.json` after a sync — best-effort,
never block an answer on it. If the user asks why a period has no measured data,
the honest answer is that snapshotting started later; offer to schedule a daily
`fetch_activity.py` so the gap never recurs.
