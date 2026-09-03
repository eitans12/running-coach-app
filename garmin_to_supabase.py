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
def sync_activities(client: Garmin):
    activities = client.get_activities_by_date(
        (date.today() - timedelta(days=SYNC_DAYS)).isoformat(),
        date.today().isoformat(),
    )
    upserted = 0
    for a in activities:
        start = (a.get("startTimeLocal") or "")[:10]          # YYYY-MM-DD
        if not start:
            continue

        row = {
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
        }
        # Idempotent: the unique index on garmin_activity_id turns a re-run into
        # a harmless update of the same row instead of a duplicate insert.
        sb.table("run_history").upsert(row, on_conflict="garmin_activity_id").execute()
        upserted += 1
    print(f"run_history: upserted {upserted} activities.")


# --------------------------------------------------------------------------
# daily wellness -> coach_logs
# --------------------------------------------------------------------------
def sync_daily_metrics(client: Garmin):
    """One coach_logs row per day with the recovery metrics Garmin exposes."""
    inserted = 0
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

        # one row per day: skip if we already logged today's metrics
        existing = (sb.table("coach_logs")
                    .select("id")
                    .eq("user_id", USER_ID)
                    .gte("created_at", d + "T00:00:00")
                    .lte("created_at", d + "T23:59:59")
                    .execute().data)
        if existing:
            continue

        sb.table("coach_logs").insert({
            "user_id": USER_ID,
            "rhr": str(rhr) if rhr is not None else None,
            "hrv": int(hrv) if hrv is not None else None,
            "body_battery": str(body_battery) if body_battery is not None else None,
            "sleep_score": str(sleep) if sleep is not None else None,
        }).execute()
        inserted += 1
    print(f"coach_logs: inserted {inserted} new daily-metric rows.")


def main():
    client = Garmin(os.environ["GARMIN_EMAIL"], os.environ["GARMIN_PASSWORD"])
    client.login()
    sync_activities(client)
    sync_daily_metrics(client)
    print("Garmin -> Supabase sync complete.")


if __name__ == "__main__":
    main()
