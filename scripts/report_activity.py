#!/usr/bin/env python3
"""Report on a WaniKani learner's study activity over a period. No network.

Reads what fetch_activity.py accumulated in <data_dir>/activity/ and answers
"how much did they study, and how did it go?" for a window. Two grades of
evidence are kept apart on purpose:

  measured  - answer counts diffed from consecutive snapshots. Exact, but only
              exists for days after fetch_activity.py started running.
  observed  - items whose most recent review landed on that day, from the live
              API. Always available for the whole history, but only ever counts
              a subject once (on its latest review), so older days read low.

Lessons, passes and burns are exact for all time either way.

Usage:
  python3 report_activity.py [--period last-week] [--format text|md|json]
                             [--config PATH] [--no-compare]

Periods: last-week, last-30d, this-level, all, YYYY-MM-DD, YYYY-MM-DD:YYYY-MM-DD
Exit codes: 0 ok, 1 config/state problem.
"""

import argparse
import json
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from fetch_inventory import DEFAULT_CONFIG, die, load_config

SRS_GROUPS = [("apprentice", range(1, 5)), ("guru", range(5, 7)),
              ("master", range(7, 8)), ("enlightened", range(8, 9)),
              ("burned", range(9, 10)), ("not started", range(0, 1))]


def parse_period(spec, latest):
    today = date.today()
    if spec in ("last-week", "week"):
        return today - timedelta(days=6), today, "the last 7 days"
    if spec in ("last-30d", "month"):
        return today - timedelta(days=29), today, "the last 30 days"
    if spec == "this-level":
        cur = max(latest["levels"], key=lambda l: l["level"])
        start = date.fromisoformat(cur["unlocked_at"][:10]) if cur.get("unlocked_at") else today
        return start, today, f"level {cur['level']} so far"
    if spec == "all":
        seen = [k for src in ("lesson_days", "passed_days", "last_touch_days")
                for k in latest[src]] + [latest["started_at"][:10]]
        return date.fromisoformat(min(seen)), today, "all time"
    if ":" in spec:
        a, b = spec.split(":", 1)
        return date.fromisoformat(a), date.fromisoformat(b), f"{a} to {b}"
    d = date.fromisoformat(spec)
    return d, d, spec


def days_in(a, b):
    out, d = [], a
    while d <= b:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def gather(latest, hist, a, b):
    """Everything the report needs about one window, in one pass."""
    keys = days_in(a, b)
    rd, lt = hist.get("review_days", {}), latest["last_touch_days"]
    g = {"days": keys, "answers": 0, "wrong": 0, "items": 0, "observed_items": 0,
         "lessons": 0, "passed": 0, "burned": 0, "active": 0, "measured_days": 0,
         "attributed": False, "rows": []}
    for k in keys:
        r = rd.get(k, {})
        obs = lt.get(k, 0)
        les = latest["lesson_days"].get(k, 0)
        pas = latest["passed_days"].get(k, 0)
        bur = latest["burned_days"].get(k, 0)
        g["answers"] += r.get("answers", 0)
        g["wrong"] += r.get("wrong", 0)
        g["items"] += r.get("items", 0)
        g["observed_items"] += obs
        g["lessons"] += les
        g["passed"] += pas
        g["burned"] += bur
        if r:
            g["measured_days"] += 1
            if r.get("confidence") == "attributed":
                g["attributed"] = True
        if r.get("answers") or obs or les or pas:
            g["active"] += 1
        g["rows"].append({"day": k, "answers": r.get("answers", 0),
                          "wrong": r.get("wrong", 0),
                          "items": r.get("items", 0) or obs,
                          "measured": bool(r), "lessons": les, "passed": pas,
                          "burned": bur})
    g["accuracy"] = (100 * (g["answers"] - g["wrong"]) / g["answers"]
                     if g["answers"] else None)
    return g


def studied_on(latest, hist, k):
    return bool(hist.get("review_days", {}).get(k, {}).get("answers")
                or latest["last_touch_days"].get(k)
                or latest["lesson_days"].get(k) or latest["passed_days"].get(k))


def streak(latest, hist, upto):
    """Consecutive days with any sign of study, counting back from `upto`.

    Today is skipped rather than counted as a break: a day still in progress has
    not ended the streak yet."""
    rd = hist.get("review_days", {})
    if not studied_on(latest, hist, upto.isoformat()):
        upto -= timedelta(days=1)
    n, d = 0, upto
    while True:
        k = d.isoformat()
        if not (rd.get(k, {}).get("answers") or latest["last_touch_days"].get(k)
                or latest["lesson_days"].get(k) or latest["passed_days"].get(k)):
            return n
        n += 1
        d -= timedelta(days=1)


def level_pace(latest):
    out = []
    for l in sorted(latest["levels"], key=lambda x: x["level"]):
        if not l.get("unlocked_at"):
            continue
        start = date.fromisoformat(l["unlocked_at"][:10])
        end = date.fromisoformat(l["passed_at"][:10]) if l.get("passed_at") else date.today()
        out.append({"level": l["level"], "start": start.isoformat(),
                    "days": (end - start).days, "done": bool(l.get("passed_at"))})
    return out


def srs_summary(latest):
    counts = {int(k): v for k, v in latest["srs"].items()}
    return [(name, sum(counts.get(i, 0) for i in rng)) for name, rng in SRS_GROUPS]


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def wpad(s, width):
    """Left-pad to a display width. CJK glyphs occupy two terminal columns, so
    len() would misalign every row that contains one."""
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
    return s + " " * max(1, width - w)


def bar(n, scale, width=32):
    return "#" * max(0, min(width, round(n * width / scale))) if scale else ""


def delta_phrase(cur, prev, unit):
    if not prev:
        return f"{cur} {unit} (no prior period to compare)"
    pct = 100 * (cur - prev) / prev
    arrow = "up" if pct > 0 else "down" if pct < 0 else "level"
    return f"{cur} {unit} vs {prev} the period before ({arrow} {abs(pct):.0f}%)"


def render_text(g, prev, latest, hist, label, a, b, compare):
    L = []
    who = latest.get("learner_name") or latest["username"]
    span = label if label.startswith(str(a)) else f"{label} ({a} to {b})"
    L.append(f"{who} — WaniKani level {latest['level']} — {span}")
    L.append("=" * 72)

    if g["answers"]:
        L.append(f"Reviews:  {g['answers']} answers over {g['items']} items, "
                 f"{g['accuracy']:.1f}% correct ({g['wrong']} wrong)")
        if compare and prev:
            L.append(f"          {delta_phrase(g['answers'], prev['answers'], 'answers')}")
    else:
        L.append(f"Reviews:  no measured answer counts in this window "
                 f"(snapshots started later); {g['observed_items']} items show a "
                 f"most-recent review here")
    L.append(f"Lessons:  {delta_phrase(g['lessons'], prev['lessons'], 'new items started')}"
             if compare and prev and prev["lessons"]
             else f"Lessons:  {g['lessons']} new items started")
    L.append(f"Progress: {g['passed']} items reached Guru, {g['burned']} burned")
    L.append(f"Rhythm:   active on {g['active']} of {len(g['days'])} days"
             f"  |  current streak {plural(streak(latest, hist, date.today()), 'day')}")
    L.append("")

    scale = max([r["answers"] or r["items"] for r in g["rows"]] + [1])
    L.append("day          answers  items  lessons  passed")
    for r in g["rows"]:
        mark = " " if r["measured"] else "~"
        ans = str(r["answers"]) if r["measured"] else "-"
        L.append(f"{r['day']} {mark} {ans:>7}  {r['items']:>5}  {r['lessons']:>7}  "
                 f"{r['passed']:>6}  {bar(r['answers'] or r['items'], scale)}")
    L.append("  ~ = no snapshot data for that day; item count is a floor, not a total")
    L.append("")

    L.append("Right now")
    L.append("  " + ", ".join(f"{n} {c}" for n, c in srs_summary(latest) if c))
    q = latest["queue"]
    L.append(f"  {q['lessons_available']} lessons waiting, {q['reviews_now']} reviews due, "
             f"{q['reviews_next_24h']} coming in the next 24h")
    pace = level_pace(latest)
    if pace:
        recent = pace[-6:]
        L.append("  level pace: " + ", ".join(
            f"L{p['level']} {p['days']}d" + ("" if p["done"] else " (current)")
            for p in recent))
    L.append("")

    if latest["leeches"]:
        L.append("Struggling items (lifetime accuracy, worst first)")
        for l in latest["leeches"][:12]:
            ch = l.get("characters") or "?"
            L.append(f"  {wpad(ch, 6)}{l['pct']:>5.1f}%  {l['wrong']} wrong / {l['answers']} "
                     f"answers  {l.get('meaning') or ''} [{l['type']}, {l.get('srs_name')}]")
        L.append("")

    notes = []
    if g["measured_days"] < len(g["days"]):
        notes.append(f"{len(g['days']) - g['measured_days']} of {len(g['days'])} days "
                     "have no snapshot coverage — run fetch_activity.py daily to close the gap")
    if g["attributed"]:
        notes.append("some days were reconstructed from a long snapshot gap; "
                     "totals are right but the split across those days is approximate")
    if latest.get("vacation_since"):
        notes.append(f"vacation mode is ON since {latest['vacation_since'][:10]}")
    if notes:
        L.append("Data quality")
        for n in notes:
            L.append(f"  - {n}")
    return "\n".join(L)


def render_md(g, prev, latest, hist, label, a, b, compare):
    who = latest.get("learner_name") or latest["username"]
    L = [f"# {who} — WaniKani {label}", "",
         f"Level {latest['level']}  ·  {a} to {b}  ·  generated from "
         f"{latest['fetched_at'][:10]} data", ""]
    L += ["## Summary", ""]
    if g["answers"]:
        L.append(f"- **{g['answers']} answers** over {g['items']} items, "
                 f"**{g['accuracy']:.1f}% correct**")
    else:
        L.append(f"- No measured answer counts yet for this window "
                 f"({g['observed_items']} items last reviewed here)")
    L += [f"- **{g['lessons']} lessons** started",
          f"- {g['passed']} items reached Guru, {g['burned']} burned",
          f"- Active on **{g['active']} of {len(g['days'])} days**; current streak "
          f"{plural(streak(latest, hist, date.today()), 'day')}", ""]
    if compare and prev and prev["answers"]:
        L += [f"Compared with the previous {len(g['days'])} days: "
              f"{delta_phrase(g['answers'], prev['answers'], 'answers')}, "
              f"{delta_phrase(g['lessons'], prev['lessons'], 'lessons')}.", ""]

    L += ["## Day by day", "", "| Day | Answers | Items | Lessons | Passed |",
          "| --- | ---: | ---: | ---: | ---: |"]
    for r in g["rows"]:
        ans = str(r["answers"]) if r["measured"] else "—"
        L.append(f"| {r['day']} | {ans} | {r['items']} | {r['lessons']} | {r['passed']} |")
    L += ["", "## Right now", "",
          "- " + ", ".join(f"{n} {c}" for n, c in srs_summary(latest) if c),
          f"- {latest['queue']['lessons_available']} lessons waiting, "
          f"{latest['queue']['reviews_now']} reviews due now, "
          f"{latest['queue']['reviews_next_24h']} in the next 24h", ""]
    if latest["leeches"]:
        L += ["## Struggling items", "",
              "| Item | Meaning | Accuracy | Wrong | Stage |",
              "| --- | --- | ---: | ---: | --- |"]
        for l in latest["leeches"][:12]:
            L.append(f"| {l.get('characters') or '?'} | {l.get('meaning') or ''} | "
                     f"{l['pct']:.1f}% | {l['wrong']} | {l.get('srs_name')} |")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--period", default="last-week")
    ap.add_argument("--format", default="text", choices=["text", "md", "json"])
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--no-compare", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    act = Path(cfg.get("data_dir", "~/.config/wanikani-story")).expanduser() / "activity"
    if not (act / "latest.json").exists():
        die(1, f"no activity data at {act} — run fetch_activity.py first")
    latest = json.loads((act / "latest.json").read_text())
    hist = json.loads((act / "history.json").read_text()) if (act / "history.json").exists() else {}

    a, b, label = parse_period(args.period, latest)
    g = gather(latest, hist, a, b)
    span = (b - a).days + 1
    prev = gather(latest, hist, a - timedelta(days=span), a - timedelta(days=1))
    compare = not args.no_compare

    if args.format == "json":
        print(json.dumps({"period": {"from": a.isoformat(), "to": b.isoformat(),
                                     "label": label},
                          "current": g, "previous": prev,
                          "queue": latest["queue"], "srs": dict(srs_summary(latest)),
                          "leeches": latest["leeches"][:12],
                          "level": latest["level"],
                          "streak": streak(latest, hist, date.today())},
                         ensure_ascii=False, indent=1))
    elif args.format == "md":
        print(render_md(g, prev, latest, hist, label, a, b, compare))
    else:
        print(render_text(g, prev, latest, hist, label, a, b, compare))


if __name__ == "__main__":
    main()
