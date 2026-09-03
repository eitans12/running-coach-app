"""
Supabase -> Google Sheets sync for the ai-running-coach project.

Pipeline stage 2: Supabase (source of truth) -> Google Sheets (the read
layer that Gemini Spark's running-coach skill consumes).

Mirrors the two real Supabase tables into the two existing sheets:
    run_history  ->  "מאגר אימוני עבר ויומן ביצועים"   (workouts)
    coach_logs   ->  "מעקב התאוששות ומדדים יומיים"      (recovery)

Design choices
--------------
* Source of truth is Supabase. This script REWRITES the data rows in each
  sheet on every run (a mirror), so the sheet never drifts from the DB and
  we don't need a `synced_to_sheets` flag.
* It writes data BELOW the styled header row, so Spark's header formatting
  is preserved.
* Column order + header row are config constants below. Once Spark locks the
  exact sheet layout, set WORKOUT_COLUMNS / RECOVERY_COLUMNS to match and the
  1:1 mapping is done — no other change needed.

Install:
    pip install supabase gspread google-auth

Environment / files:
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    APP_USER_ID                         # uuid of the profile to sync
    google_credentials.json             # a Google service account with edit
                                        # access shared to BOTH sheets
"""

import os
from supabase import create_client, Client
import gspread
from google.oauth2.service_account import Credentials

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
USER_ID = os.environ["APP_USER_ID"]

WORKOUTS_SHEET_ID = "1_u5tOrkLwZTlwcK-I8ubLQ_2QgkOAvVbhBkvCw4jOOQ"
RECOVERY_SHEET_ID = "11_OsZV31ijfZdNWFLhM2oLmoV38zRathk7xZLGhFjBE"

# --- LAYOUT CONFIG (set these to Spark's locked spec) ---------------------
# The row number of the styled header in each sheet; data starts on the next row.
WORKOUTS_HEADER_ROW = 7
RECOVERY_HEADER_ROW = 8

# Column order = the order the values are written, left to right.
# Each entry maps a sheet column to how its value is produced from a DB row.
# --------------------------------------------------------------------------

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
_scopes = ["https://www.googleapis.com/auth/spreadsheets"]
_creds = Credentials.from_service_account_file("google_credentials.json", scopes=_scopes)
gc = gspread.authorize(_creds)


# ---- formatters (human-readable values for the coach) --------------------
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
    return f"{m}:{s:02d}/ק\"מ"


# ---- row builders: DB row -> ordered list of sheet cells -----------------
def _workout_row(r):
    return [
        r.get("activity_date", ""),
        r.get("title", "") or "",
        r.get("activity_type", "") or "",
        r.get("distance_km", "") if r.get("distance_km") is not None else "",
        _fmt_duration(r.get("duration_sec")),
        _fmt_pace(r.get("avg_pace_sec_per_km")),
        r.get("avg_hr", "") if r.get("avg_hr") is not None else "",
        r.get("max_hr", "") if r.get("max_hr") is not None else "",
        r.get("elevation_gain_m", "") if r.get("elevation_gain_m") is not None else "",
    ]


def _recovery_row(r):
    ts = (r.get("created_at") or "")[:10]
    return [
        ts,
        r.get("feeling", "") if r.get("feeling") is not None else "",
        r.get("rhr", "") or "",
        r.get("hrv", "") if r.get("hrv") is not None else "",
        r.get("body_battery", "") or "",
        r.get("sleep_score", "") or "",
        r.get("last_run_summary", "") or "",
        r.get("ai_analysis", "") or "",
    ]


# ---- generic mirror writer ----------------------------------------------
def _mirror(sheet_id, header_row, rows):
    ws = gc.open_by_key(sheet_id).sheet1
    first_data_row = header_row + 1

    # clear old data region (everything below the header) then write fresh
    n_cols = max((len(r) for r in rows), default=1)
    last_col = chr(ord("A") + n_cols - 1)
    existing = len(ws.get_all_values())
    if existing >= first_data_row:
        ws.batch_clear([f"A{first_data_row}:{last_col}{existing}"])

    if rows:
        ws.update(
            f"A{first_data_row}",
            rows,
            value_input_option="USER_ENTERED",
        )
    return len(rows)


def sync_workouts():
    data = (sb.table("run_history")
            .select("*")
            .eq("user_id", USER_ID)
            .order("activity_date")
            .execute().data)
    n = _mirror(WORKOUTS_SHEET_ID, WORKOUTS_HEADER_ROW, [_workout_row(r) for r in data])
    print(f"workouts sheet: wrote {n} rows.")


def sync_recovery():
    data = (sb.table("coach_logs")
            .select("*")
            .eq("user_id", USER_ID)
            .order("created_at")
            .execute().data)
    n = _mirror(RECOVERY_SHEET_ID, RECOVERY_HEADER_ROW, [_recovery_row(r) for r in data])
    print(f"recovery sheet: wrote {n} rows.")


def main():
    sync_workouts()
    sync_recovery()
    print("Supabase -> Sheets sync complete.")


if __name__ == "__main__":
    main()
