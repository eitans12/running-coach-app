"""
garmin_workout_builder.py
-------------------------
Two-way sync for ai-running-coach: PUSH structured workouts that the coach
plans INTO the athlete's Garmin Connect account, so they download to the watch
as guided workouts with pace / HR targets and interval alerts.

This is the "push" counterpart to garmin_to_supabase.py (the "pull"). It logs
in with the same Garmin credentials (env vars) and talks to Garmin's
workout-service endpoints through the authenticated garth session that
`garminconnect` already manages.

    pip install garminconnect
    env: GARMIN_EMAIL, GARMIN_PASSWORD

--------------------------------------------------------------------------
DATA SOURCE (recommended)
--------------------------------------------------------------------------
Do NOT try to parse free-text sheet cells like "5x400 @5:25" into a workout —
that is brittle. Instead the coach (Spark) authors a STRUCTURED spec, either:
  * a dedicated Supabase table `planned_workouts` (one row per workout with a
    JSONB `spec` column + a `scheduled_date`), or
  * a JSON block it writes next to the plan.
This module consumes that structured spec (the `WorkoutSpec` dict below).
A concrete example spec for Eitan's next interval session is at the bottom.
--------------------------------------------------------------------------
"""

import os
from datetime import datetime, timezone

from garminconnect import Garmin

try:
    from supabase import create_client, Client
except ImportError:          # supabase only needed for the DB-driven flow
    create_client = None

# ==========================================================================
# Garmin workout enums (from Garmin Connect's workout-service model)
# ==========================================================================
SPORT = {
    "running": {"sportTypeId": 1, "sportTypeKey": "running"},
    "cycling": {"sportTypeId": 2, "sportTypeKey": "cycling"},
}

STEP_TYPES = {                       # stepTypeId, stepTypeKey
    "warmup":   (1, "warmup"),
    "cooldown": (2, "cooldown"),
    "interval": (3, "interval"),
    "recovery": (4, "recovery"),
    "rest":     (5, "rest"),
    "repeat":   (6, "repeat"),
}

END_CONDITIONS = {                   # conditionTypeId, conditionTypeKey
    "lap":        (1, "lap.button"),
    "time":       (2, "time"),        # value in SECONDS
    "distance":   (3, "distance"),    # value in METERS
    "iterations": (7, "iterations"),
}

TARGET_TYPES = {                     # workoutTargetTypeId, workoutTargetTypeKey
    "none": (1, "no.target"),
    "hr":   (4, "heart.rate.zone"),  # custom bpm min/max
    "pace": (6, "pace.zone"),        # min/max SPEED in m/s
}


# ==========================================================================
# helpers
# ==========================================================================
def pace_to_mps(pace):
    """'5:30' (min:sec per km) -> speed in m/s."""
    if isinstance(pace, (int, float)):
        return float(pace)
    m, s = pace.split(":")
    sec_per_km = int(m) * 60 + int(s)
    return 1000.0 / sec_per_km


def _apply_target(step, target):
    """target = ('pace', slow, fast) | ('hr', low_bpm, high_bpm) | None."""
    if not target:
        tid, tkey = TARGET_TYPES["none"]
        step["targetType"] = {"workoutTargetTypeId": tid, "workoutTargetTypeKey": tkey}
        return step

    kind = target[0]
    if kind == "pace":
        # Garmin wants a min/max SPEED (m/s); faster pace = higher m/s.
        v1, v2 = pace_to_mps(target[1]), pace_to_mps(target[2])
        lo, hi = sorted((v1, v2))
        tid, tkey = TARGET_TYPES["pace"]
        step["targetType"] = {"workoutTargetTypeId": tid, "workoutTargetTypeKey": tkey}
        step["targetValueOne"] = round(lo, 4)   # slower bound
        step["targetValueTwo"] = round(hi, 4)   # faster bound
    elif kind == "hr":
        lo, hi = sorted((float(target[1]), float(target[2])))
        tid, tkey = TARGET_TYPES["hr"]
        step["targetType"] = {"workoutTargetTypeId": tid, "workoutTargetTypeKey": tkey}
        step["targetValueOne"] = lo             # low bpm
        step["targetValueTwo"] = hi             # high bpm
    return step


class _Order:
    """Sequential stepOrder counter (group first, then its children)."""
    def __init__(self):
        self.n = 0

    def next(self):
        self.n += 1
        return self.n


def _exec_step(order, kind, end, target=None):
    st_id, st_key = STEP_TYPES[kind]
    ec_id, ec_key = END_CONDITIONS[end[0]]
    step = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": st_id, "stepTypeKey": st_key},
        "endCondition": {"conditionTypeId": ec_id, "conditionTypeKey": ec_key},
        "endConditionValue": float(end[1]),
    }
    return _apply_target(step, target)


def _build_steps(spec_steps, order):
    out = []
    for s in spec_steps:
        if s["kind"] == "repeat":
            group_order = order.next()
            children = _build_steps(s["steps"], order)
            out.append({
                "type": "RepeatGroupDTO",
                "stepOrder": group_order,
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
                "numberOfIterations": int(s["iterations"]),
                "smartRepeat": False,
                "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
                "endConditionValue": float(s["iterations"]),
                "workoutSteps": children,
            })
        else:
            out.append(_exec_step(order.next(), s["kind"], s["end"], s.get("target")))
    return out


def build_payload(spec):
    """Turn a WorkoutSpec dict into Garmin's workout-service JSON payload."""
    sport = SPORT[spec.get("sport", "running")]
    steps = _build_steps(spec["steps"], _Order())
    return {
        "sportType": sport,
        "workoutName": spec["name"],
        "workoutSegments": [{
            "segmentOrder": 1,
            "sportType": sport,
            "workoutSteps": steps,
        }],
    }


# ==========================================================================
# Garmin API (via the authenticated garth session inside garminconnect)
# ==========================================================================
def _get(client, path, params=None):
    """Authenticated GET against Garmin's connect API (returns parsed JSON).

    Query args must go through `params`, not embedded in the path — garth
    rejects a path that contains a '?' as an "Invalid API path".
    """
    if params:
        return client.connectapi(path, params=params)
    return client.connectapi(path)


def _post(client, path, payload):
    """Authenticated POST against Garmin's connect API.

    garminconnect exposes the garth-based HTTP client as `client.client`, and
    POSTs are made with client.client.post("connectapi", <path>, json=...).
    """
    resp = client.client.post("connectapi", path, json=payload)
    try:
        return resp.json()
    except Exception:
        return resp


def find_workout_id(client, name):
    """Return the Garmin workoutId of an existing workout with this exact name,
    or None. Lets us SCHEDULE an already-uploaded workout without recreating it."""
    existing = _get(client, "/workout-service/workouts",
                    params={"start": 0, "limit": 200}) or []
    for w in existing:
        if (w or {}).get("workoutName") == name:
            return w.get("workoutId")
    return None


def create_workout(client, payload):
    resp = _post(client, "/workout-service/workout", payload)
    return (resp or {}).get("workoutId") if isinstance(resp, dict) else None


def schedule_workout(client, workout_id, date_iso):
    """Attach the workout to a calendar date so it appears on the watch that day."""
    return _post(client, f"/workout-service/schedule/{workout_id}", {"date": date_iso})


def push_workout(client, spec, date_iso=None):
    """Ensure the workout exists in Garmin (create once), then — if a date is
    given — schedule THAT workout onto the calendar. Re-runnable without
    creating duplicates: an existing workout is reused and just (re)scheduled."""
    wid = find_workout_id(client, spec["name"])
    if wid:
        print(f"· exists: {spec['name']} (id {wid})")
    else:
        wid = create_workout(client, build_payload(spec))
        print(f"· created workout {wid}: {spec['name']}")
    if wid and date_iso:
        schedule_workout(client, wid, date_iso)
        print(f"  scheduled → {date_iso}")
    return wid


# ==========================================================================
# CONCRETE EXAMPLE — Eitan's next interval session
# ==========================================================================
# "אימון הפוגות: 5x400m (קצב 5:28)"
#   warm-up  : 1.5 km easy
#   main set : 5 × [ 400 m @ 5:25–5:30 , 90 s walk recovery ]
#   cool-down: 1.0 km easy
INTERVALS_5x400 = {
    "name": "אימון הפוגות: 5x400m (קצב 5:28)",
    "sport": "running",
    "steps": [
        {"kind": "warmup",   "end": ("distance", 1500)},                  # 1.5 km
        {"kind": "repeat", "iterations": 5, "steps": [
            {"kind": "interval", "end": ("distance", 400),
             "target": ("pace", "5:30", "5:25")},                         # 5:25–5:30 /km
            {"kind": "recovery", "end": ("time", 90)},                    # 90 s walk
        ]},
        {"kind": "cooldown", "end": ("distance", 1000)},                  # 1.0 km
    ],
}

# Example of a volume/long run using a custom HR band (145–152 bpm):
LONG_RUN_HR_EXAMPLE = {
    "name": "ריצת נפח Zone 2 (145–152)",
    "sport": "running",
    "steps": [
        {"kind": "warmup",   "end": ("time", 600)},                       # 10 min
        {"kind": "interval", "end": ("distance", 12000),
         "target": ("hr", 145, 152)},                                     # 12 km @ 145–152 bpm
        {"kind": "cooldown", "end": ("time", 300)},                       # 5 min
    ],
}


# ==========================================================================
# Supabase-driven flow: read planned_workouts -> push -> mark status
# ==========================================================================
def _sb():
    if create_client is None:
        raise RuntimeError("supabase package not installed (pip install supabase)")
    return create_client(os.environ["SUPABASE_URL"],
                         os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def read_actionable(sb, user_id):
    """Rows that still need work: not yet created (pending), or created but
    not yet scheduled (uploaded). 'scheduled' rows are done."""
    return (sb.table("planned_workouts").select("*")
            .eq("user_id", user_id)
            .in_("status", ["pending", "uploaded"])
            .order("scheduled_date").execute().data)


def _mark(sb, row_id, **fields):
    sb.table("planned_workouts").update(fields).eq("id", row_id).execute()


def sync_planned_to_garmin(client, sb, user_id):
    rows = read_actionable(sb, user_id)
    print(f"{len(rows)} actionable workout(s).")
    for r in rows:
        date = r.get("scheduled_date")
        # An already-uploaded workout with no date has nothing left to do.
        if r["status"] == "uploaded" and not date:
            continue
        try:
            wid = push_workout(client, r["spec"], date)
            _mark(sb, r["id"],
                  status="scheduled" if date else "uploaded",   # date => on the calendar
                  garmin_workout_id=str(wid) if wid else r.get("garmin_workout_id"),
                  error_message=None,
                  uploaded_at=datetime.now(timezone.utc).isoformat())
        except Exception as e:                       # keep going on the rest
            print(f"  ! error on {r.get('name')}: {e}")
            _mark(sb, r["id"], status="error", error_message=str(e))


def main():
    client = Garmin(os.environ["GARMIN_EMAIL"], os.environ["GARMIN_PASSWORD"])
    client.login()
    sb = _sb()
    sync_planned_to_garmin(client, sb, os.environ["APP_USER_ID"])
    print("Done.")


if __name__ == "__main__":
    main()
