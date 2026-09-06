"""
Garmin Connect -> Supabase ingestion for the ai-running-coach project.

Pipeline stage 1 (the real missing link): Garmin -> Supabase.
Populates the ACTUAL tables that exist in project `ai-running-coach`:
    - public.run_history   (running/activity records)
    - public.coach_logs    (daily recovery/physiology metrics)

Garmin's official developer API is paused, so this uses the community
`garminconnect` library (Garth-based login). It logs in with the user's
own Garmin credentials — supplied via environment variables at runtime,
never hardcoded here.

Run this in the Codespace where the app lives (it already has the
Supabase connection). It is idempotent: activities are de-duplicated
before insert.

Install:
    pip install garminconnect supabase python-dateutil

Environment variables expected:
    GARMIN_EMAIL, GARMIN_PASSWORD          # the runner's Garmin login
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    APP_USER_ID                            # uuid of the row in public.profiles
    SYNC_DAYS (optional, default 30)       # how many days back to pull
"""

import os
from datetime import date, timedelta

from garminconnect import Garmin
from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
USER_ID = os.environ["APP_USER_ID"]
SYNC_DAYS = int(os.environ.get("SYNC_DAYS", "30"))

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _pace_sec_per_km(distance_m, duration_s):
    """Average pace in seconds per km, or None when distance is missing."""
    if not distance_m or distance_m <= 0 or not duration_s:
        return None
    return round(duration_s / (distance_m / 1000.0), 1)


# --------------------------------------------------------------------------
# activities -> run_history
# --------------------------------------------------------------------------
def _activity_row(a):
    start = (a.get("startTimeLocal") or "")[:10]              # YYYY-MM-DD
    if not start:
        return None
    return {
            "user_id": USER_ID,
            "garmin_activity_id": str(a.get("activityId")) if a.get("activityId") else None,
            "activity_date": start,
            "activity_type": (a.get("activityType") or {}).get("typeKey"),
            "title": a.get("activityName"),
            "distance_km": round((a.get("distance") or 0) / 1000.0, 3) or None,
            "duration_sec": int(a.get("duration") or 0) or None,
            "avg_hr": int(a["averageHR"]) if a.get("averageHR") else None,
            "max_hr": int(a["maxHR"]) if a.get("maxHR") else None,
            "avg_pace_sec_per_km": _pace_sec_per_km(a.get("distance"), a.get("duration")),
            "elevation_gain_m": a.get("elevationGain"),
            "avg_cadence": a.get("averageRunningCadenceInStepsPerMinute"),
            "aerobic_te": a.get("aerobicTrainingEffect"),
            "anaerobic_te": a.get("anaerobicTrainingEffect"),
        }


# --------------------------------------------------------------------------
# activities -> run_history  (FULL history via pagination)
# --------------------------------------------------------------------------
def sync_activities(client: Garmin):
    """Pull the entire activity history (paged), not just a recent window.

    get_activities(start, limit) returns activities newest-first in pages;
    we walk pages until exhausted. Upsert on garmin_activity_id keeps re-runs
    idempotent, so this is safe to run daily even over the whole history.
    """
    start, batch, total, MAX = 0, 100, 0, 5000
    while start < MAX:
        activities = client.get_activities(start, batch)
        if not activities:
            break
        for a in activities:
            row = _activity_row(a)
            if not row:
                continue
            sb.table("run_history").upsert(row, on_conflict="garmin_activity_id").execute()
            total += 1
        if len(activities) < batch:
            break
        start += batch
    print(f"run_history: upserted {total} activities (full history).")


# --------------------------------------------------------------------------
# daily wellness -> coach_logs
# --------------------------------------------------------------------------
def sync_daily_metrics(client: Garmin):
    """One coach_logs row per DAY with the recovery metrics Garmin exposes.

    The row is keyed by `metric_date` (the day the metrics belong to) — NOT by
    created_at (the insert time). This is what lets the sheet match each day's
    recovery to the right date. Upsert on (user_id, metric_date) makes re-runs
    idempotent: the same day is updated, never duplicated.
    """
    upserted = 0
    for i in range(SYNC_DAYS):
        d = (date.today() - timedelta(days=i)).isoformat()

        stats = client.get_stats(d) or {}
        try:
            hrv = (client.get_hrv_data(d) or {}).get("hrvSummary", {}).get("lastNightAvg")
        except Exception:
            hrv = None
        try:
            sleep = ((client.get_sleep_data(d) or {})
                     .get("dailySleepDTO", {}) or {}).get("sleepScores", {}) \
                     .get("overall", {}).get("value")
        except Exception:
            sleep = None

        rhr = stats.get("restingHeartRate")
        body_battery = stats.get("bodyBatteryMostRecentValue")

        if not any([rhr, hrv, body_battery, sleep]):
            continue

        sb.table("coach_logs").upsert({
            "user_id": USER_ID,
            "metric_date": d,                       # the day the reading is FOR
            "rhr": str(rhr) if rhr is not None else None,
            "hrv": int(hrv) if hrv is not None else None,
            "body_battery": str(body_battery) if body_battery is not None else None,
            "sleep_score": str(sleep) if sleep is not None else None,
        }, on_conflict="user_id,metric_date").execute()
        upserted += 1
    print(f"coach_logs: upserted {upserted} daily-metric rows (by metric_date).")


def main():
    client = Garmin(os.environ["GARMIN_EMAIL"], os.environ["GARMIN_PASSWORD"])
    client.login()
    sync_activities(client)
    sync_daily_metrics(client)
    print("Garmin -> Supabase sync complete.")


if __name__ == "__main__":
    main()
