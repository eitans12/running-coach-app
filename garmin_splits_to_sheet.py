"""
Garmin per-kilometer SPLITS -> Google Sheet (for the coach / Gemini Spark).

Pipeline add-on: the main sync writes per-RUN summaries (avg pace, avg HR).
This script writes the *shape* of each run — the per-kilometer splits (pace,
avg HR, max HR) — which is the numeric form of Garmin's pace/HR graphs. Spark
reads it to reason about how a run actually unfolded (fade, HR drift, negative
split, surges), not just its averages.

It writes to a dedicated tab ("פיצולים") in the same Workouts spreadsheet Spark
already reads, rewriting the tab each run so it always holds the latest runs.

Garmin exposes this via GET /activity-service/activity/{id}/splits, whose
`lapDTOs` are the laps. Most runners use 1 km auto-lap, so each lap ≈ 1 km; the
final (partial) lap shows its real distance.

Install:  pip install garminconnect gspread google-auth
Env:      GARMIN_EMAIL, GARMIN_PASSWORD
          SPLITS_DAYS   (optional, default 21)  — how far back to look
          SPLITS_MAX_RUNS (optional, default 12) — cap on runs pulled
File:     google_credentials.json (same service account used by the sync)
"""

import os
import re
import time
from datetime import date, timedelta

from garminconnect import Garmin
import gspread
from gspread.exceptions import APIError, WorksheetNotFound
from google.oauth2.service_account import Credentials

# Same spreadsheet Spark already reads ("מאגר אימוני עבר ויומן ביצועים").
WORKOUTS_SHEET_ID = "1_u5tOrkLwZTlwcK-I8ubLQ_2QgkOAvVbhBkvCw4jOOQ"
SPLITS_TAB = "פיצולים"
SPLITS_DAYS = int(os.environ.get("SPLITS_DAYS", "21"))
SPLITS_MAX_RUNS = int(os.environ.get("SPLITS_MAX_RUNS", "12"))

HEADER = ['תאריך', 'ריצה', 'ק"מ #', 'מרחק (ק"מ)', 'קצב (לק"מ)',
          'דופק ממוצע', 'דופק מקס']

_TRANSIENT = {429, 500, 502, 503, 504}


def _status_of(err):
    try:
        return err.response.status_code
    except Exception:
        m = re.search(r"\[(\d{3})\]", str(err))
        return int(m.group(1)) if m else None


def _retry(fn, *args, _tries=5, _base=2.0, **kwargs):
    for attempt in range(_tries):
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            if _status_of(e) in _TRANSIENT and attempt < _tries - 1:
                wait = _base * (2 ** attempt)
                print(f"  … Sheets API transient error ({_status_of(e)}); "
                      f"retry {attempt + 1} in {wait:.0f}s")
                time.sleep(wait)
                continue
            raise


def _fmt_pace(sec_per_km):
    if not sec_per_km or sec_per_km <= 0:
        return ""
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}"


def _is_run(type_key):
    tk = (type_key or "").lower()
    return "running" in tk or "treadmill" in tk


def _lap_rows(start_date, title, laps):
    rows = []
    for i, lap in enumerate(laps, 1):
        dist_m = lap.get("distance") or 0
        dur = lap.get("duration") or lap.get("movingDuration") or 0
        avg_hr = lap.get("averageHR")
        max_hr = lap.get("maxHR")
        pace = _fmt_pace(dur / (dist_m / 1000.0)) if dist_m else ""
        rows.append([
            start_date, title, i, round(dist_m / 1000.0, 2), pace,
            int(avg_hr) if avg_hr is not None else "",
            int(max_hr) if max_hr is not None else "",
        ])
    return rows


def main():
    # Reuse the session saved by the earlier Garmin->Supabase step (same runner,
    # same tokenstore path). login(tokenstore) restores those tokens and skips a
    # second SSO login, so this step no longer adds Garmin 429 rate-limit risk.
    # If no saved session exists it falls back to a normal credential login.
    tokenstore = os.environ.get("GARMINTOKENS") or os.path.expanduser("~/.garminconnect")
    client = Garmin(os.environ.get("GARMIN_EMAIL", ""), os.environ.get("GARMIN_PASSWORD", ""))
    client.login(tokenstore)

    creds = Credentials.from_service_account_file(
        "google_credentials.json",
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    gc = gspread.authorize(creds)
    ss = _retry(gc.open_by_key, WORKOUTS_SHEET_ID)
    try:
        ws = ss.worksheet(SPLITS_TAB)
    except WorksheetNotFound:
        ws = _retry(ss.add_worksheet, title=SPLITS_TAB, rows=400, cols=8)

    cutoff = (date.today() - timedelta(days=SPLITS_DAYS)).isoformat()
    activities = client.get_activities(0, 40) or []

    out = [HEADER]
    runs = 0
    for a in activities:
        if runs >= SPLITS_MAX_RUNS:
            break
        if not _is_run((a.get("activityType") or {}).get("typeKey")):
            continue
        start = (a.get("startTimeLocal") or "")[:10]
        if not start or start < cutoff:
            continue
        aid = a.get("activityId")
        if not aid:
            continue
        title = a.get("activityName") or (a.get("activityType") or {}).get("typeKey") or "ריצה"
        try:
            splits = client.get_activity_splits(aid) or {}
        except Exception as e:
            print(f"  … could not fetch splits for {aid}: {e}")
            continue
        laps = splits.get("lapDTOs") or []
        if not laps:
            continue
        # --- TEMP DEBUG: what does Garmin actually give per lap? ---
        try:
            print(f"DEBUG run '{title}' {start}: {len(laps)} laps; "
                  f"first-lap keys = {sorted(laps[0].keys())}")
            itypes = [lap.get("intensityType") for lap in laps]
            print(f"DEBUG intensityType values = {itypes}")
        except Exception as _e:
            print(f"DEBUG could not introspect laps: {_e}")
        # --- END TEMP DEBUG ---
        out.extend(_lap_rows(start, title, laps))
        out.append(["", "", "", "", "", "", ""])   # blank line between runs
        runs += 1

    _retry(ws.clear)
    _retry(ws.update, range_name="A1", values=out, value_input_option="USER_ENTERED")
    print(f"splits: wrote {len(out) - 1} rows covering {runs} runs to tab '{SPLITS_TAB}'.")


if __name__ == "__main__":
    main()
