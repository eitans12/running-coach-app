"""
Google Calendar -> Supabase bridge for the ai-running-coach project.

Problem this solves: Gemini "Spark" (the coach) plans workouts and writes
them reliably to Google Calendar, but push-workouts.yml / garmin_workout_builder.py
only reads from the Supabase `planned_workouts` table. Without this bridge,
every new plan needs a human to copy/paste SQL by hand.

This script reads Eitan's primary Google Calendar, finds upcoming events
whose description contains an embedded workout spec (Spark is instructed to
always include this block — see gemini-spark-instructions), and upserts them
into `planned_workouts` with status='pending' so the existing Garmin-push
pipeline picks them up automatically on its next run.

Expected event description format (anywhere in the description):

    ###GARMIN_SPEC###
    {"name": "...", "sport": "running", "steps": [...]}
    ###END_SPEC###

Only the JSON between the two markers is parsed; everything else in the
description (human-readable notes) is ignored.

Second problem this solves: Spark has no working, authenticated way to write
directly into the Google Sheets (the "Google Workspace" connector Gemini
exposes does not support Sheets at all), so subjective post-run feedback the
athlete gives Spark in chat (RPE, shoes, notes) had nowhere durable to land.
Spark CAN reliably write to Calendar, so it is instructed (see
gemini-spark-instructions) to attach a second block to the description of the
Calendar event for the day of the run:

    ###POST_RUN###
    {"rpe": 7, "shoes": "Nike Pegasus 41", "notes": "felt strong on the hills"}
    ###END_POST_RUN###

This script looks for that block on events in a short lookback window and
upserts the fields straight into `run_history` (matched by activity_date),
from where supabase_to_sheets.py carries them into the sheet's P/Q columns.
All three fields are optional; only the keys present are written.

Install:  pip install google-api-python-client google-auth supabase python-dateutil
Env:      SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, APP_USER_ID
          CALENDAR_ID (optional, default "primary")
          CALENDAR_LOOKAHEAD_DAYS (optional, default 21)
          CALENDAR_POST_RUN_LOOKBACK_DAYS (optional, default 10)
File:     google_credentials.json (service account; must be shared as a
          "guest" with read access on the target calendar - see README_sync.md)
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
USER_ID = os.environ["APP_USER_ID"]
CALENDAR_ID = os.environ.get("CALENDAR_ID", "primary")
LOOKAHEAD_DAYS = int(os.environ.get("CALENDAR_LOOKAHEAD_DAYS", "21"))
POST_RUN_LOOKBACK_DAYS = int(os.environ.get("CALENDAR_POST_RUN_LOOKBACK_DAYS", "10"))

SPEC_RE = re.compile(r"###GARMIN_SPEC###\s*(\{.*?\})\s*###END_SPEC###", re.DOTALL)
POST_RUN_RE = re.compile(r"###POST_RUN###\s*(\{.*?\})\s*###END_POST_RUN###", re.DOTALL)

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
_creds = Credentials.from_service_account_file(
    "google_credentials.json",
    scopes=["https://www.googleapis.com/auth/calendar.readonly"],
)
cal = build("calendar", "v3", credentials=_creds, cache_discovery=False)


def _extract_block(description, pattern, label):
    if not description:
        return None
    m = pattern.search(description)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"  ! could not parse embedded {label} JSON: {e}")
        return None


def _extract_spec(description):
    return _extract_block(description, SPEC_RE, "spec")


def _extract_post_run(description):
    return _extract_block(description, POST_RUN_RE, "post-run")


def _event_date(event):
    start = event.get("start", {})
    d = start.get("date") or (start.get("dateTime") or "")[:10]
    return d or None


def fetch_calendar_workouts():
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=LOOKAHEAD_DAYS)).isoformat()

    events, page_token = [], None
    while True:
        resp = cal.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        ).execute()
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    workouts = []
    for ev in events:
        spec = _extract_spec(ev.get("description"))
        if not spec:
            continue
        d = _event_date(ev)
        if not d:
            continue
        name = spec.get("name") or ev.get("summary") or "אימון"
        workouts.append((d, name, spec))
    return workouts


def fetch_post_run_feedback():
    """Scan a short window of recent (and today's) events for a ###POST_RUN###
    block — subjective feedback Spark took down in chat and wrote to the
    Calendar event for that day, since it cannot write to the Sheets directly.
    """
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=POST_RUN_LOOKBACK_DAYS)).isoformat()
    time_max = (now + timedelta(days=1)).isoformat()

    events, page_token = [], None
    while True:
        resp = cal.events().list(
            calendarId=CALENDAR_ID,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        ).execute()
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    feedback = []
    for ev in events:
        post_run = _extract_post_run(ev.get("description"))
        if not post_run:
            continue
        d = _event_date(ev)
        if not d:
            continue
        feedback.append((d, post_run))
    return feedback


def sync_post_run_feedback(feedback):
    updated, skipped = 0, 0
    for scheduled_date, post_run in feedback:
        fields = {}
        if post_run.get("rpe") is not None:
            fields["rpe"] = post_run["rpe"]
        if post_run.get("shoes"):
            fields["shoes"] = post_run["shoes"]
        if post_run.get("notes"):
            fields["athlete_notes"] = post_run["notes"]
        if not fields:
            continue

        existing = (
            sb.table("run_history")
            .select("id")
            .eq("user_id", USER_ID)
            .eq("activity_date", scheduled_date)
            .execute()
            .data
        )
        if not existing:
            # The run hasn't synced from Garmin yet (sync.yml runs on its own
            # schedule) - skip for now, the next run of this script will
            # pick the same block up again once run_history has the row.
            skipped += 1
            continue

        for row in existing:
            sb.table("run_history").update(fields).eq("id", row["id"]).execute()
        updated += 1
        print(f"  ~ post-run feedback: {scheduled_date} - {fields}")

    print(f"calendar -> run_history: {updated} days updated with athlete feedback, "
          f"{skipped} skipped (no matching run synced yet).")


def sync_to_supabase(workouts):
    inserted, updated, skipped = 0, 0, 0
    for scheduled_date, name, spec in workouts:
        existing = (
            sb.table("planned_workouts")
            .select("id, status")
            .eq("user_id", USER_ID)
            .eq("scheduled_date", scheduled_date)
            .execute()
            .data
        )

        if not existing:
            sb.table("planned_workouts").insert({
                "user_id": USER_ID,
                "name": name,
                "scheduled_date": scheduled_date,
                "spec": spec,
                "status": "pending",
            }).execute()
            inserted += 1
            print(f"  + inserted: {scheduled_date} - {name}")
            continue

        row = existing[0]
        if row["status"] in ("scheduled", "uploaded"):
            # Already pushed to Garmin for this date - don't touch it.
            skipped += 1
            continue

        sb.table("planned_workouts").update({
            "name": name,
            "spec": spec,
            "status": "pending",
            "error_message": None,
        }).eq("id", row["id"]).execute()
        updated += 1
        print(f"  ~ updated:   {scheduled_date} - {name}")

    print(f"calendar -> planned_workouts: {inserted} inserted, {updated} updated, "
          f"{skipped} already on Garmin (left alone).")


def main():
    workouts = fetch_calendar_workouts()
    print(f"Found {len(workouts)} calendar events with an embedded Garmin spec "
          f"in the next {LOOKAHEAD_DAYS} days.")
    sync_to_supabase(workouts)

    feedback = fetch_post_run_feedback()
    print(f"Found {len(feedback)} calendar events with an embedded post-run "
          f"feedback block in the last {POST_RUN_LOOKBACK_DAYS} days.")
    sync_post_run_feedback(feedback)


if __name__ == "__main__":
    main()
