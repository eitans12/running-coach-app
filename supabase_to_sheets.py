"""
Supabase -> Google Sheets sync for the ai-running-coach project.

Pipeline stage 2: Supabase (source of truth for ACTUALS) -> the two Google
Sheets that Gemini Spark's running-coach skill reads.

The sheets are PLAN-vs-ACTUAL logs that Spark (the coach) authors:
Spark writes the planning columns; this script fills ONLY the "actual"
(measured-from-Garmin) columns, matched to the right row BY DATE, and never
touches Spark's plan or the athlete's subjective columns.

Workouts sheet ("מאגר אימוני עבר ...") — header row 7:
    A date | B time | C name/type | D goal | E planned-km   <- Spark (leave)
    F actual-km | G duration | H pace | I avg-hr | J max-hr <- Garmin (fill)
    K target-hr-zone                                        <- Spark (leave)
    L cadence | M elevation | N aerobic-TE | O anaerobic-TE <- Garmin (fill)
    P RPE | Q shoes                                         <- athlete (leave)

Recovery sheet ("מעקב התאוששות ...") — header row 8:
    A date                                                  <- key
    B sleep-hours                                           <- athlete (leave)
    C sleep-quality | D RHR | E HRV | F readiness           <- Garmin (fill)
    G soreness/body-feel                                    <- athlete (leave)

Install:  pip install supabase gspread google-auth
Env:      SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, APP_USER_ID
File:     google_credentials.json (service account with edit access to both)
"""

import os
from datetime import datetime, date

from supabase import create_client, Client
import gspread
from google.oauth2.service_account import Credentials

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
USER_ID = os.environ["APP_USER_ID"]

WORKOUTS_SHEET_ID = "1_u5tOrkLwZTlwcK-I8ubLQ_2QgkOAvVbhBkvCw4jOOQ"
RECOVERY_SHEET_ID = "11_OsZV31ijfZdNWFLhM2oLmoV38zRathk7xZLGhFjBE"
WORKOUTS_HEADER_ROW = 7
RECOVERY_HEADER_ROW = 8

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
_creds = Credentials.from_service_account_file(
    "google_credentials.json",
    scopes=["https://www.googleapis.com/auth/spreadsheets"],
)
gc = gspread.authorize(_creds)


# ---- formatters ----------------------------------------------------------
def _fmt_duration(sec):
    if not sec:
        return ""
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_pace(sec_per_km):
    if not sec_per_km:
        return ""
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}"


def _parse_date(s):
    """Parse whatever date string the sheet holds into a date, or None."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _col_letter(n):
    """1 -> A, 2 -> B, ..."""
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


# ---- generic date-matched merge -----------------------------------------
def _merge(sheet_id, header_row, records, actual_cols, key_col=1, type_col=None):
    """
    records: list of (date_obj, {col_index: value}) — actual values to write.
    actual_cols: the set of 1-based column indexes this sync owns (for width).
    Existing row with the same date -> update only the given cells.
    No match -> append a new row (date + type + actuals), planning cells blank.
    """
    ws = gc.open_by_key(sheet_id).sheet1
    grid = ws.get_all_values()

    # map date -> list of row numbers (1-based) among data rows
    date_rows = {}
    for idx in range(header_row, len(grid)):        # 0-based; skips header
        d = _parse_date(grid[idx][key_col - 1] if len(grid[idx]) >= key_col else "")
        if d:
            date_rows.setdefault(d, []).append(idx + 1)

    used = set()
    batch = []                       # {"range": "F9", "values": [[v]]}
    appends = []                     # full-width rows to add at the bottom
    max_col = max(actual_cols + ([type_col] if type_col else []) + [key_col])
    next_row = len(grid) + 1

    for d, cells in records:
        row = next((r for r in date_rows.get(d, []) if r not in used), None)
        if row:                                     # matched a planned row
            used.add(row)
            for col, val in cells.items():
                if val is None or val == "":
                    continue
                batch.append({"range": f"{_col_letter(col)}{row}", "values": [[val]]})
        else:                                       # unplanned -> append
            new = [""] * max_col
            new[key_col - 1] = d.isoformat()
            if type_col and cells.get(type_col):
                new[type_col - 1] = cells[type_col]
            for col, val in cells.items():
                if col == type_col:
                    continue
                if 1 <= col <= max_col and val not in (None, ""):
                    new[col - 1] = val
            appends.append(new)

    if batch:
        ws.batch_update(batch, value_input_option="USER_ENTERED")
    if appends:
        ws.update(
            range_name=f"A{next_row}",
            values=appends,
            value_input_option="USER_ENTERED",
        )
    return len(batch), len(appends)


# ---- workouts: run_history -> workouts sheet -----------------------------
def sync_workouts():
    rows = (sb.table("run_history").select("*")
            .eq("user_id", USER_ID).order("activity_date").execute().data)
    records = []
    for r in rows:
        d = _parse_date(r.get("activity_date"))
        if not d:
            continue
        cells = {
            3:  r.get("activity_type") or r.get("title") or "",   # C (only if appended)
            6:  r.get("distance_km"),                             # F actual km
            7:  _fmt_duration(r.get("duration_sec")),             # G duration
            8:  _fmt_pace(r.get("avg_pace_sec_per_km")),          # H pace
            9:  r.get("avg_hr"),                                  # I avg hr
            10: r.get("max_hr"),                                  # J max hr
            12: r.get("avg_cadence"),                             # L cadence
            13: r.get("elevation_gain_m"),                        # M elevation
            14: r.get("aerobic_te"),                              # N aerobic TE
            15: r.get("anaerobic_te"),                            # O anaerobic TE
        }
        records.append((d, cells))
    upd, app = _merge(WORKOUTS_SHEET_ID, WORKOUTS_HEADER_ROW, records,
                      actual_cols=[6, 7, 8, 9, 10, 12, 13, 14, 15], type_col=3)
    print(f"workouts: {upd} cells updated in planned rows, {app} unplanned rows appended.")


# ---- recovery: coach_logs -> recovery sheet ------------------------------
def sync_recovery():
    rows = (sb.table("coach_logs").select("*")
            .eq("user_id", USER_ID).order("created_at").execute().data)
    # keep one record per day (latest wins)
    by_day = {}
    for r in rows:
        d = _parse_date((r.get("created_at") or "")[:10])
        if d:
            by_day[d] = r
    records = []
    for d, r in sorted(by_day.items()):
        cells = {
            3: r.get("sleep_score"),   # C sleep quality
            4: r.get("rhr"),           # D RHR
            5: r.get("hrv"),           # E HRV
            6: r.get("body_battery"),  # F readiness / recovery
        }
        records.append((d, cells))
    upd, app = _merge(RECOVERY_SHEET_ID, RECOVERY_HEADER_ROW, records,
                      actual_cols=[3, 4, 5, 6])
    print(f"recovery: {upd} cells updated, {app} new days appended.")


def main():
    sync_workouts()
    sync_recovery()
    print("Supabase -> Sheets merge complete.")


if __name__ == "__main__":
    main()
