#!/usr/bin/env python3
"""Snapshot a WaniKani learner's study activity and accumulate a daily history.

Why snapshots: /v2/reviews (the per-review log) is empty for read-only tokens on
some accounts, so daily review volume cannot be recovered after the fact. What
*is* available is /v2/review_statistics — per-subject cumulative answer counters.
Diffing consecutive snapshots turns those counters into exact per-window answer
and error counts, and each record's data_updated_at (the timestamp of that
subject's most recent review) pins the window down to a day. Run this often —
daily or better — and the history becomes a true per-day record. Skip a month and
that month collapses into one unattributed window, permanently.

Lessons, passes and burns need no diffing: assignments carry absolute
started_at / passed_at / burned_at, so that part of the history is always exact
and is recomputed from scratch every run.

Usage:
  python3 fetch_activity.py [--config PATH] [--keep N] [--no-snapshot] [--quiet]

Output: <data_dir>/activity/history.json  (append-only, NOT recoverable if lost)
        <data_dir>/activity/latest.json   (current derived state, disposable)
        <data_dir>/activity/snapshots/*.json  (raw counters, disposable)
Exit codes: 0 ok, 1 config/token problem, 2 API problem.
"""

import argparse
import calendar
import json
import time
from datetime import datetime
from pathlib import Path

from fetch_inventory import (API, SRS_NAMES, api_get, api_get_all, load_config,
                             resolve_token, slim_subject)

# A window this long or shorter cannot straddle more than one local day boundary
# by more than a sliver, so day attribution inside it is treated as exact.
EXACT_WINDOW_SECS = 26 * 3600
LEECH_MIN_ANSWERS = 6   # below this, one bad day looks like a leech


def epoch(ts):
    """UTC ISO8601 (with or without fractional seconds) -> unix epoch."""
    return calendar.timegm(datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").timetuple())


def localday(ts):
    """UTC ISO8601 -> local YYYY-MM-DD. Days are the learner's days, not UTC's."""
    return time.strftime("%Y-%m-%d", time.localtime(epoch(ts))) if ts else None


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def counters(stat):
    """review_statistic -> (total answers, wrong answers)."""
    d = stat["data"]
    return (d["meaning_correct"] + d["meaning_incorrect"]
            + d["reading_correct"] + d["reading_incorrect"],
            d["meaning_incorrect"] + d["reading_incorrect"])


def build_snapshot(stats):
    """id -> [answers, wrong, last_review_epoch]. Compact on purpose: this file
    is written every run and only ever read by the next run's diff."""
    out = {}
    for s in stats:
        a, w = counters(s)
        out[str(s["data"]["subject_id"])] = [a, w, epoch(s["data_updated_at"])]
    return out


def diff_into_history(hist, prev, prev_at, cur, cur_at):
    """Fold the change between two snapshots into the per-day review series.

    Each subject's delta is attributed to the day of its most recent review. That
    is exact when the subject was reviewed once in the window (the norm for daily
    runs) and approximate when it was reviewed on several days inside a long one —
    which is precisely why the window length is recorded alongside."""
    span = cur_at - prev_at
    confidence = "exact" if span <= EXACT_WINDOW_SECS else "attributed"
    days = hist.setdefault("review_days", {})
    total_a = total_w = items = 0
    for sid, (a, w, last) in cur.items():
        pa, pw, _ = prev.get(sid, (0, 0, 0))
        da, dw = a - pa, w - pw
        if da <= 0:
            continue
        total_a += da
        total_w += dw
        items += 1
        rec = days.setdefault(time.strftime("%Y-%m-%d", time.localtime(last)),
                              {"answers": 0, "wrong": 0, "items": 0, "confidence": confidence})
        rec["answers"] += da
        rec["wrong"] += dw
        rec["items"] += 1
        # A day touched by any long window inherits that window's uncertainty.
        if confidence == "attributed":
            rec["confidence"] = "attributed"
    return {"answers": total_a, "wrong": total_w, "items": items,
            "span_hours": round(span / 3600, 1), "confidence": confidence}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--keep", type=int, default=30,
                    help="raw snapshots to retain (default 30)")
    ap.add_argument("--no-snapshot", action="store_true",
                    help="refresh latest.json only; do not diff or extend history")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    import fetch_inventory
    cfg = load_config(args.config or fetch_inventory.DEFAULT_CONFIG)
    token = resolve_token(cfg)
    data_dir = Path(cfg.get("data_dir", "~/.config/wanikani-story")).expanduser()
    act_dir = data_dir / "activity"
    snap_dir = act_dir / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    cache_path = data_dir / "cache" / "subjects.json"

    user = api_get(f"{API}/user", token)["data"]
    stats = api_get_all(f"{API}/review_statistics", token)
    assigns = api_get_all(f"{API}/assignments", token)
    levels = api_get(f"{API}/level_progressions", token)["data"]
    summary = api_get(f"{API}/summary", token)["data"]

    # --- history: diff against the previous snapshot ---------------------------
    hist_path = act_dir / "history.json"
    hist = load_json(hist_path, {"version": 1, "review_days": {}, "unattributed": [],
                                 "snapshots": []})
    hist["username"] = user["username"]
    cur = build_snapshot(stats)
    cur_at = int(time.time())
    window = None

    if not args.no_snapshot:
        prev_name = hist.get("last_snapshot")
        prev_path = snap_dir / prev_name if prev_name else None
        if prev_path and prev_path.exists():
            prev_blob = json.loads(prev_path.read_text())
            window = diff_into_history(hist, prev_blob["subjects"], prev_blob["at"],
                                       cur, cur_at)
        else:
            # First run (or the snapshot was pruned/lost): everything answered so
            # far is real but undatable. Bank it as one window rather than
            # pretending it happened today.
            tot = sum(v[0] for v in cur.values())
            wrong = sum(v[1] for v in cur.values())
            hist["unattributed"].append(
                {"from": user["started_at"], "to": now_iso(), "answers": tot,
                 "wrong": wrong, "items": len(cur), "reason": "baseline"})
            window = {"answers": tot, "wrong": wrong, "items": len(cur),
                      "span_hours": None, "confidence": "baseline"}

        name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(cur_at)) + ".json"
        (snap_dir / name).write_text(json.dumps({"at": cur_at, "subjects": cur}))
        hist["last_snapshot"] = name
        hist["snapshots"].append({"at": now_iso(), "file": name,
                                  "total_answers": sum(v[0] for v in cur.values()),
                                  "subjects": len(cur)})
        for old in sorted(snap_dir.glob("*.json"))[:-max(1, args.keep)]:
            old.unlink()
        hist_path.write_text(json.dumps(hist, indent=1))

    # --- latest: recomputed wholesale every run, safe to delete ---------------
    lessons, passed, burned, srs = {}, {}, {}, {}
    for a in assigns:
        d = a["data"]
        srs[str(d["srs_stage"])] = srs.get(str(d["srs_stage"]), 0) + 1
        for field, bucket in (("started_at", lessons), ("passed_at", passed),
                              ("burned_at", burned)):
            day = localday(d.get(field))
            if day:
                bucket[day] = bucket.get(day, 0) + 1

    touch, hours, per_type, leeches = {}, {}, {}, []
    tot_a = tot_w = 0
    for s in stats:
        a, w = counters(s)
        tot_a += a
        tot_w += w
        t = per_type.setdefault(s["data"]["subject_type"], {"answers": 0, "wrong": 0})
        t["answers"] += a
        t["wrong"] += w
        ts = s["data_updated_at"]
        day = localday(ts)
        touch[day] = touch.get(day, 0) + 1
        hr = time.strftime("%H", time.localtime(epoch(ts)))
        hours[hr] = hours.get(hr, 0) + 1
        if a >= LEECH_MIN_ANSWERS and w:
            leeches.append({"subject_id": s["data"]["subject_id"],
                            "type": s["data"]["subject_type"], "answers": a,
                            "wrong": w, "pct": round(100 * (a - w) / a, 1)})

    # Name the leeches. The story skill's subject cache already holds most of
    # them; fill the gaps (radicals, unstarted items) and write them back.
    cache = load_json(cache_path, {})
    missing = [str(l["subject_id"]) for l in leeches if str(l["subject_id"]) not in cache]
    for i in range(0, len(missing), 300):
        for s in api_get_all(f"{API}/subjects?ids={','.join(missing[i:i + 300])}", token):
            cache[str(s["id"])] = slim_subject(s)
    if missing:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False))
    srs_by_id = {a["data"]["subject_id"]: a["data"]["srs_stage"] for a in assigns}
    for l in leeches:
        s = cache.get(str(l["subject_id"]), {})
        l["characters"] = s.get("characters")
        l["meaning"] = s.get("meaning")
        l["level"] = s.get("level")
        l["srs_name"] = SRS_NAMES.get(srs_by_id.get(l["subject_id"]))
    leeches.sort(key=lambda x: (x["pct"], -x["wrong"]))

    latest = {
        "fetched_at": now_iso(),
        "learner_name": cfg.get("learner", {}).get("name"),
        "username": user["username"], "level": user["level"],
        "started_at": user["started_at"],
        "vacation_since": user.get("current_vacation_started_at"),
        "totals": {"answers": tot_a, "wrong": tot_w, "subjects": len(stats),
                   "lessons": sum(lessons.values()), "per_type": per_type},
        "lesson_days": lessons, "passed_days": passed, "burned_days": burned,
        "last_touch_days": touch, "hour_hist": hours,
        "levels": [{"level": l["data"]["level"],
                    "unlocked_at": l["data"].get("unlocked_at"),
                    "passed_at": l["data"].get("passed_at")} for l in levels],
        "srs": srs,
        "queue": {
            "lessons_available": sum(len(x["subject_ids"]) for x in summary["lessons"]),
            "reviews_now": len(summary["reviews"][0]["subject_ids"]) if summary["reviews"] else 0,
            "reviews_next_24h": sum(len(x["subject_ids"]) for x in summary["reviews"]),
        },
        "leeches": leeches[:40],
    }
    (act_dir / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=1))

    if not args.quiet:
        print(f"level {user['level']} | lifetime {tot_a} answers, "
              f"{100 * (tot_a - tot_w) / tot_a:.1f}% correct | "
              f"{len(hist.get('review_days', {}))} days on record")
        if window:
            if window["confidence"] == "baseline":
                print(f"baseline snapshot taken ({window['answers']} answers banked as "
                      f"undatable history) — run again tomorrow to start the daily series")
            else:
                print(f"since last snapshot ({window['span_hours']}h): "
                      f"{window['answers']} answers, {window['items']} items, "
                      f"{window['wrong']} wrong [{window['confidence']}]")
        print(f"wrote {act_dir}/history.json and latest.json")


if __name__ == "__main__":
    main()
