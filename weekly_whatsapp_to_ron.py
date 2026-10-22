"""
Weekly training-plan WhatsApp message for the ai-running-coach project.

Every Sunday, Spark (the Gemini coach) plans the upcoming week and writes it
to Google Calendar (with embedded ###GARMIN_SPEC### blocks). calendar_to_supabase.py
pulls that into the `planned_workouts` Supabase table. THIS script then reads
that week's rows and sends a WhatsApp message to Ron summarizing the plan -
no nutrition, no fluff, just the week day-by-day plus an estimated weekly
kilometrage.

Message format (fixed, do not change without checking with Eitan):

    היי רון! הנה תוכנית האימון של איתן לשבוע הקרוב:

    יום ראשון: יום מנוחה
    יום שני: <workout name>
       • חימום: ...
       • חלק מרכזי: ...
       • קירור: ...
    ...
    יום שבת: <workout name>

    קילומטראז' שבועי משוער: X ק"מ

Every non-rest day includes a one-line-per-segment breakdown (warmup, main
set, cooldown) built from the workout's ###GARMIN_SPEC### `steps`, each line
stating the segment's distance/time AND its target pace or heart rate. A
`repeat` segment ("N x work+rest") states the rep count, the work pace/HR,
and the rest between reps. This detail requirement comes directly from
Eitan - do not collapse it back to a bare workout name.

Sending is via Green API (green-api.com) - it sends FROM Eitan's own linked
WhatsApp number, so Ron does not need to opt in to anything.

Install:  pip install supabase requests python-dateutil
Env:      SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, APP_USER_ID
          GREEN_API_ID_INSTANCE, GREEN_API_TOKEN_INSTANCE
          RON_WHATSAPP_NUMBER   # digits only, international format, e.g. 9725XXXXXXXX
          WEEK_START_OVERRIDE (optional, YYYY-MM-DD) - mainly for manual testing
"""

import os
from datetime import date, timedelta

import requests
from supabase import create_client, Client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
USER_ID = os.environ["APP_USER_ID"]

GREEN_API_ID = os.environ["GREEN_API_ID_INSTANCE"]
GREEN_API_TOKEN = os.environ["GREEN_API_TOKEN_INSTANCE"]
RON_NUMBER = os.environ["RON_WHATSAPP_NUMBER"].strip()

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

HEBREW_DAY_NAMES = [
    "יום ראשון", "יום שני", "יום שלישי", "יום רביעי",
    "יום חמישי", "יום שישי", "יום שבת",
]


def _week_start():
    """The Sunday that starts 'this' week (Python weekday(): Mon=0 ... Sun=6)."""
    override = os.environ.get("WEEK_START_OVERRIDE")
    if override:
        return date.fromisoformat(override)
    today = date.today()
    days_since_sunday = (today.weekday() + 1) % 7   # Sun -> 0, Mon -> 1, ...
    return today - timedelta(days=days_since_sunday)


def _step_distance_m(step):
    """Distance (meters) this step contributes, recursing into 'repeat' steps."""
    kind = step.get("kind")
    if kind == "repeat":
        iterations = step.get("iterations", 1)
        inner = sum(_step_distance_m(s) for s in step.get("steps", []))
        return iterations * inner
    end = step.get("end") or []
    if len(end) == 2 and end[0] == "distance":
        try:
            return float(end[1])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _spec_distance_km(spec):
    if not spec or not isinstance(spec, dict):
        return 0.0
    total_m = sum(_step_distance_m(s) for s in spec.get("steps", []))
    return total_m / 1000.0


_KIND_LABELS = {
    "warmup": "חימום",
    "cooldown": "קירור",
    "interval": "חלק מרכזי",
    "recovery": "מנוחה",
    "easy": "ריצה קלה",
}


def _fmt_amount(end):
    """Format an ['distance', meters] or ['time', seconds] end condition."""
    if not end or len(end) != 2:
        return ""
    kind, value = end
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    if kind == "distance":
        if value >= 1000:
            km = value / 1000
            km_str = f"{km:g}"
            return f'{km_str} ק"מ'
        return f"{int(value)} מ'"
    if kind == "time":
        seconds = int(value)
        minutes, secs = divmod(seconds, 60)
        return f"{minutes}:{secs:02d} דק'" if secs else f"{minutes} דק'"
    return ""


def _fmt_target(target):
    """Format a ['pace', slow, fast] or ['hr', low, high] target."""
    if not target or len(target) != 3:
        return ""
    kind, a, b = target
    if kind == "pace":
        return f'בקצב {a}-{b} דק\'/ק"מ'
    if kind == "hr":
        return f"בדופק {a}-{b} פעימות/דק'"
    return ""


def _describe_plain_step(step):
    label = _KIND_LABELS.get(step.get("kind"), step.get("kind") or "")
    parts = [p for p in [_fmt_amount(step.get("end")), _fmt_target(step.get("target"))] if p]
    return f"{label}: {' '.join(parts)}" if parts else (label or None)


def _describe_repeat_step(step):
    iterations = step.get("iterations", 1)
    inner = step.get("steps", []) or []
    rest = next((s for s in inner if s.get("kind") == "recovery"), None)
    work = next((s for s in inner if s is not rest), None)

    work_parts = []
    if work:
        work_parts = [p for p in [_fmt_amount(work.get("end")), _fmt_target(work.get("target"))] if p]
    work_desc = " ".join(work_parts) or "חזרה"

    rest_desc = ""
    if rest:
        rest_amount = _fmt_amount(rest.get("end"))
        rest_desc = f", מנוחה {rest_amount} בין חזרות" if rest_amount else ", עם מנוחה בין חזרות"

    return f"חלק מרכזי: {iterations} × {work_desc}{rest_desc}"


def _describe_workout(spec):
    """Multi-line Hebrew breakdown (warmup / main set / cooldown) of a workout."""
    if not spec or not isinstance(spec, dict):
        return ""
    lines = []
    for step in spec.get("steps", []):
        if step.get("kind") == "repeat":
            lines.append(_describe_repeat_step(step))
        else:
            desc = _describe_plain_step(step)
            if desc:
                lines.append(desc)
    return "\n".join(f"   • {line}" for line in lines)


def fetch_week_rows(week_start):
    week_end = week_start + timedelta(days=6)
    rows = (
        sb.table("planned_workouts")
        .select("name, scheduled_date, spec")
        .eq("user_id", USER_ID)
        .gte("scheduled_date", week_start.isoformat())
        .lte("scheduled_date", week_end.isoformat())
        .execute()
        .data
    )
    by_date = {r["scheduled_date"]: r for r in rows}
    return by_date


def build_message(week_start):
    by_date = fetch_week_rows(week_start)
    lines = ["היי רון! הנה תוכנית האימון של איתן לשבוע הקרוב:", ""]
    total_km = 0.0

    for i in range(7):
        d = week_start + timedelta(days=i)
        row = by_date.get(d.isoformat())
        day_label = HEBREW_DAY_NAMES[i]
        if row:
            lines.append(f"{day_label}: {row['name']}")
            detail = _describe_workout(row.get("spec"))
            if detail:
                lines.append(detail)
            total_km += _spec_distance_km(row.get("spec"))
        else:
            lines.append(f"{day_label}: יום מנוחה")

    lines.append("")
    # round to nearest half-km, drop trailing .0
    km_rounded = round(total_km * 2) / 2
    km_str = str(int(km_rounded)) if km_rounded == int(km_rounded) else str(km_rounded)
    lines.append(f"קילומטראז' שבועי משוער: {km_str} ק\"מ")

    return "\n".join(lines), len(by_date)


def send_whatsapp(message):
    url = (
        f"https://api.green-api.com/waInstance{GREEN_API_ID}"
        f"/sendMessage/{GREEN_API_TOKEN}"
    )
    chat_id = f"{RON_NUMBER}@c.us"
    resp = requests.post(url, json={"chatId": chat_id, "message": message}, timeout=30)
    resp.raise_for_status()
    print(f"WhatsApp send response: {resp.status_code} {resp.text}")


def main():
    week_start = _week_start()
    message, rows_found = build_message(week_start)
    print(f"Week of {week_start.isoformat()} - {rows_found} planned_workouts rows found.")
    print("---- message ----")
    print(message)
    print("------------------")
    if rows_found == 0:
        print("No planned workouts found for this week yet - not sending "
              "(Spark may not have finished planning / calendar sync hasn't run).")
        return
    send_whatsapp(message)
    print("Sent to Ron.")


if __name__ == "__main__":
    main()
