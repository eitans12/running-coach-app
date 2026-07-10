import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from garminconnect import Garmin
import datetime
import json
import re
import html

# --- עיצוב אפליקציית ספורט: פונט, פלטת צבעים וכרטיסים ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"], .stApp, .stMarkdown, p, span, div, button, input, textarea, label {
        font-family: 'Rubik', 'Segoe UI', Arial, sans-serif !important;
    }

    h1, h2, h3 {
        color: #F8F9FA !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em;
    }
    p, span, label, .stMarkdown, .stCaption { color: #E8EAED; }

    /* כותרת מאמן */
    .coach-header {
        display: flex; align-items: center; gap: 12px;
        padding-bottom: 16px; margin-bottom: 16px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .coach-avatar {
        width: 46px; height: 46px; border-radius: 50%;
        background: #24272C; border: 2px solid #FF5A3C;
    }
    .coach-name { font-weight: 700; font-size: 17px; color: #F8F9FA; }
    .coach-status { font-size: 12px; color: #3DDC97; font-weight: 500; }

    /* בועות צ'אט */
    .user-msg {
        background: linear-gradient(135deg, #FF5A3C, #FF8A3C) !important;
        color: #ffffff !important;
        padding: 10px 16px; border-radius: 18px 18px 4px 18px;
        max-width: 75%; font-size: 15px; line-height: 1.5;
        box-shadow: 0 2px 8px rgba(255,90,60,0.25);
    }
    .ai-msg {
        background-color: #1A1D22 !important;
        color: #F2F3F5 !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        padding: 10px 16px; border-radius: 18px 18px 18px 4px;
        max-width: 75%; font-size: 15px; line-height: 1.5;
    }

    /* כרטיסי לוח אימונים */
    .calendar-card {
        background-color: #16181C;
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 14px;
        padding: 14px 18px;
        margin-bottom: 10px;
        display: flex; align-items: center; gap: 14px;
        transition: border-color 0.15s ease;
    }
    .calendar-card:hover { border-color: rgba(255,255,255,0.16); }
    .card-badge {
        width: 42px; height: 42px; min-width: 42px;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 19px;
    }
    .calendar-card.card-run .card-badge { background: rgba(255,90,60,0.15); }
    .calendar-card.card-cross .card-badge { background: rgba(61,220,151,0.15); }
    .calendar-card.card-rest .card-badge { background: rgba(255,255,255,0.06); }

    .day-title { color: #9AA0A8 !important; font-size: 13px; font-weight: 500; }
    .workout-type { color: #F8F9FA !important; font-size: 15.5px; font-weight: 600; }

    /* טאבים */
    [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid rgba(255,255,255,0.08); }
    [data-baseweb="tab"] { font-weight: 600; }
    [data-baseweb="tab-highlight"] { background-color: #FF5A3C !important; }

    /* כפתורים */
    .stButton > button, .stFormSubmitButton > button {
        border-radius: 10px !important;
        font-weight: 600 !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- התחברות למסד הנתונים ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)

# Streamlit יוצר מחדש את ה-client הזה בכל ריצה, אז צריך לשחזר את סשן המשתמש
# (אחרת הבקשות רצות עם מפתח ה-anon בלבד, ו-RLS חוסם אותן כי auth.uid() ריק)
if st.session_state.get("sb_access_token") and st.session_state.get("sb_refresh_token"):
    try:
        supabase.auth.set_session(st.session_state.sb_access_token, st.session_state.sb_refresh_token)
    except Exception:
        st.session_state.clear()

# --- ניהול מצב ---
if "user" not in st.session_state: st.session_state.user = None
if "profile_data" not in st.session_state: st.session_state.profile_data = {}
if "latest_log" not in st.session_state: st.session_state.latest_log = {}
if "messages" not in st.session_state: st.session_state.messages = []
if "chat_session" not in st.session_state: st.session_state.chat_session = None

hebrew_days = ['יום ראשון', 'יום שני', 'יום שלישי', 'יום רביעי', 'יום חמישי', 'יום שישי', 'יום שבת']

TRAINING_PROTOCOL = """
- פריודיזציה: בנה עומס בהדרגה (לא יותר מ-10% נפח שבועי בין שבוע לשבוע), עם שבוע התאוששות כל 3-4 שבועות.
- עצימות: רוב האימונים (כ-80%) צריכים להיות בקצב קל/שיחה, והשאר באזורי סף/אינטרוולים.
- התאוששות: אל תתכנן שני אימונים עצימים ברצף. תמיד יום מנוחה או אימון קל אחרי אימון קשה.
- חוקי אזהרה: HRV נמוך משמעותית מהממוצע, דופק מנוחה גבוה, או תחושה מתחת ל-4/10 - הפוך את האימון המתוכנן לקל או למנוחה.
"""

# --- פונקציות עזר ---
def load_user_profile(user_id):
    try:
        res = supabase.table("profiles").select("*").eq("id", user_id).execute()
        st.session_state.profile_data = res.data[0] if res.data else {}
    except Exception as e:
        st.session_state.profile_data = {}
        st.warning(f"לא ניתן היה לטעון את הפרופיל: {e}")

def load_latest_coach_log(user_id):
    try:
        res = supabase.table("coach_logs").select("*").eq("user_id", user_id).order("id", desc=True).limit(1).execute()
        st.session_state.latest_log = res.data[0] if res.data else {}
    except Exception as e:
        st.session_state.latest_log = {}
        st.warning(f"לא ניתן היה לטעון את יומן האימון האחרון: {e}")

def build_daily_status():
    # תמיד נשלף מחדש מה-DB (ולא מ-session_state המקומי) כדי שריענון דף / התנתקות מחדש
    # לא "ישכחו" עדכון בוקר שכבר בוצע היום.
    load_latest_coach_log(st.session_state.user.id)
    log = st.session_state.latest_log
    today = datetime.datetime.utcnow().date().isoformat()
    if not log or str(log.get("created_at", ""))[:10] != today:
        return "המשתמש עדיין לא מילא עדכון בוקר היום."
    fields = [("דופק מנוחה", "rhr"), ("HRV", "hrv"), ("שינה", "sleep_score"),
              ("סוללת גוף", "body_battery"), ("תחושה", "feeling")]
    parts = [f"{label}: {log.get(key) if log.get(key) is not None else 'לא סופק'}" for label, key in fields]
    return "עדכון בוקר בוצע היום. " + ", ".join(parts)

def coach_send(message_text):
    full_message = f"[מצב יומי: {build_daily_status()}]\n{message_text}"
    return st.session_state.chat_session.send_message(full_message)

# --- ייבוא היסטוריית ריצות מקובץ CSV של גרמין ---
# הכותרות בקובץ ה-Export של Garmin Connect משתנות בין גרסאות/שפות/סוגי אימון,
# לכן מזהים עמודות לפי שמות נפוצים ולא לפי מבנה קשיח.
GARMIN_COLUMN_ALIASES = {
    "date": ["date", "תאריך"],
    "activity_type": ["activity type", "type", "סוג פעילות"],
    "title": ["title", "activity name", "name", "כותרת"],
    "distance": ["distance", "מרחק"],
    "duration": ["time", "moving time", "elapsed time", "זמן"],
    "avg_hr": ["avg hr", "average heart rate", "avg heart rate", "דופק ממוצע"],
    "max_hr": ["max hr", "max heart rate", "דופק מקסימלי"],
    "avg_pace": ["avg pace", "average pace", "קצב ממוצע"],
    "elevation_gain": ["total ascent", "elev gain", "elevation gain", "עלייה מצטברת"],
}

def _find_garmin_column(columns, aliases):
    lowered = {c: c.strip().lower() for c in columns}
    for alias in aliases:
        for col, low in lowered.items():
            if low == alias:
                return col
    for alias in aliases:
        for col, low in lowered.items():
            if alias in low:
                return col
    return None

def _parse_duration_to_sec(val):
    if pd.isna(val): return None
    try:
        parts = [float(p) for p in str(val).strip().split(":")]
    except ValueError:
        return None
    if len(parts) == 3: h, m, s = parts
    elif len(parts) == 2: h, (m, s) = 0, parts
    else: return None
    return int(h * 3600 + m * 60 + s)

def _parse_distance_km(val):
    if pd.isna(val): return None
    cleaned = re.sub(r"[^\d.]", "", str(val).replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None

def _parse_int(val):
    if pd.isna(val): return None
    cleaned = re.sub(r"[^\d]", "", str(val))
    return int(cleaned) if cleaned else None

def _parse_pace_sec_per_km(val):
    if pd.isna(val): return None
    s = str(val).strip()
    if s in ("--", "", "0:00"): return None
    try:
        parts = [float(p) for p in s.split(":")]
    except ValueError:
        return None
    if len(parts) == 2: return parts[0] * 60 + parts[1]
    if len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None

def parse_garmin_csv(uploaded_file):
    """מחזיר (rows, mapping) - rows לייבוא ל-run_history, mapping לתצוגת אימות למשתמש."""
    df = pd.read_csv(uploaded_file)
    mapping = {field: _find_garmin_column(df.columns, aliases) for field, aliases in GARMIN_COLUMN_ALIASES.items()}
    if not mapping["date"] or not mapping["distance"]:
        raise ValueError("לא זוהו עמודות תאריך/מרחק בקובץ. ודא שזה קובץ 'Export CSV' של הפעילויות מ-Garmin Connect.")

    rows = []
    for _, row in df.iterrows():
        activity_date = pd.to_datetime(row.get(mapping["date"]), errors="coerce")
        if pd.isna(activity_date):
            continue
        rows.append({
            "user_id": st.session_state.user.id,
            "activity_date": activity_date.date().isoformat(),
            "activity_type": str(row.get(mapping["activity_type"], "") or "") if mapping["activity_type"] else None,
            "title": str(row.get(mapping["title"], "") or "") if mapping["title"] else None,
            "distance_km": _parse_distance_km(row.get(mapping["distance"])),
            "duration_sec": _parse_duration_to_sec(row.get(mapping["duration"])) if mapping["duration"] else None,
            "avg_hr": _parse_int(row.get(mapping["avg_hr"])) if mapping["avg_hr"] else None,
            "max_hr": _parse_int(row.get(mapping["max_hr"])) if mapping["max_hr"] else None,
            "avg_pace_sec_per_km": _parse_pace_sec_per_km(row.get(mapping["avg_pace"])) if mapping["avg_pace"] else None,
            "elevation_gain_m": _parse_distance_km(row.get(mapping["elevation_gain"])) if mapping["elevation_gain"] else None,
        })
    return rows, mapping

def build_run_history_summary():
    try:
        res = supabase.table("run_history").select("*").eq("user_id", st.session_state.user.id).order("activity_date", desc=True).execute()
        rows = res.data or []
    except Exception:
        rows = []
    if not rows:
        return "המשתמש עדיין לא העלה קובץ היסטוריית ריצות - אין מידע על ריצות עבר מלבד עדכוני הבוקר."

    runs = [r for r in rows if "run" in (r.get("activity_type") or "").lower() or "ריצ" in (r.get("activity_type") or "")]
    if not runs:
        runs = rows
    total_km = sum(r.get("distance_km") or 0 for r in runs)
    paces = [r["avg_pace_sec_per_km"] for r in runs if r.get("avg_pace_sec_per_km")]
    avg_pace = sum(paces) / len(paces) if paces else None
    longest = max((r.get("distance_km") or 0 for r in runs), default=0)
    cutoff = (datetime.date.today() - datetime.timedelta(days=28)).isoformat()
    recent_km = sum(r.get("distance_km") or 0 for r in runs if (r.get("activity_date") or "") >= cutoff)

    def fmt_pace(p):
        if not p: return "לא זמין"
        m, s = divmod(int(p), 60)
        return f"{m}:{s:02d} דק'/ק״מ"

    return (f"מתוך קובץ שהועלה: {len(runs)} ריצות מתועדות, סה״כ {total_km:.0f} ק״מ, "
            f"קצב ממוצע {fmt_pace(avg_pace)}, ריצה הכי ארוכה {longest:.1f} ק״מ, "
            f"נפח ריצה ב-28 הימים האחרונים: {recent_km:.0f} ק״מ.")

def fetch_recent_garmin_activities(garmin_email, garmin_password):
    if not garmin_email or not garmin_password:
        return "לא מחובר לגרמין."
    try:
        client = Garmin(garmin_email, garmin_password)
        client.login()
        activities = client.get_activities(0, 3)
        if activities:
            history = []
            for act in activities:
                name = act.get('activityName', 'אימון')
                dist = act.get('distance', 0) / 1000
                dur = act.get('duration', 0) / 60
                hr = act.get('averageHeartRateInBeatsPerMinute', 'N/A')
                history.append(f"{name}: {dist:.2f} ק״מ ב-{dur:.1f} דק' | דופק ממוצע: {hr}")
            return "\n".join(history)
        return "לא נמצאו אימונים לאחרונה."
    except Exception as e:
        return f"שגיאת סנכרון: {e}"

# פונקציה שמחלצת JSON מהתשובה של ה-AI ומעדכנת את הלוח
def process_ai_response_for_plan(response_text):
    json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
    if json_match:
        try:
            new_plan = json.loads(json_match.group(1))
            user_prefs = json.loads(st.session_state.profile_data.get("workout_preferences", "{}"))
            user_prefs["weekly_plan"] = new_plan
            supabase.table("profiles").update({"workout_preferences": json.dumps(user_prefs)}).eq("id", st.session_state.user.id).execute()
            st.session_state.profile_data["workout_preferences"] = json.dumps(user_prefs)

            clean_text = re.sub(r'```json\n.*?\n```', '', response_text, flags=re.DOTALL).strip()
            st.toast("📅 המאמן עדכן את לוח האימונים בהצלחה!")
            return clean_text
        except Exception as e:
            st.warning(f"לא ניתן היה לעדכן את לוח האימונים: {e}")
            return response_text
    return response_text

def push_to_garmin(workout_name, day_ai_plan, profile):
    try:
        # התחברות לגרמין
        client = Garmin(profile.get("garmin_email"), profile.get("garmin_password"))
        client.login()

        # בניית מבנה האימון (פשטני, אפשר להרחיב לפי ה-steps ב-JSON)
        workout = {
            "name": workout_name,
            "description": day_ai_plan.get('goal', ''),
            "type": "RUNNING",
            # כאן צריך להגדיר את ה-steps של גרמין (מורכב, נתחיל בבסיס)
        }

        # שליחה לגרמין
        client.save_workout(workout)
        return True
    except Exception as e:
        st.error(f"שגיאה בשליחה לגרמין: {e}")
        return False

# --- הגדרת המאמן ---
genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

def init_chat_session():
    # חישוב מגמה מהירה מתוך ה-coach_logs (ה-7 האחרונים)
    logs = supabase.table("coach_logs").select("*").eq("user_id", st.session_state.user.id).order("id", desc=True).limit(7).execute().data
    trend_msg = "אין מספיק נתונים לניתוח מגמה."
    if len(logs) >= 3:
        avg_feeling = sum(l['feeling'] for l in logs) / len(logs)
        trend_msg = f"מגמת תחושה ב-7 ימים אחרונים: {avg_feeling:.1f}/10."

    # כאן נכנס הניתוח החכם
    run_history_summary = build_run_history_summary()
    system_instruction = f"""
    אתה מאמן ריצה עילית בעל ניסיון של 20 שנה.
    פרוטוקול עבודה: {TRAINING_PROTOCOL}
    מגמות מתאמן: {trend_msg}
    נתוני היום: {st.session_state.latest_log}
    היסטוריית ריצות: {run_history_summary}

    חוקי עבודה:
    1. לפני כל המלצה, בצע 'ניתוח מצב': השווה את הנתונים של היום למגמה (Trend).
    2. אם אתה מזהה שחיקה לפי הנתונים, תהיה קשוח - עצור אימונים עצימים!
    3. תמיד נמק את ה-JSON שאתה בונה לפי חוקי הברזל.
    4. כברירת מחדל ענה בקצרה ותכל'ס - כמה משפטים ישירים, בלי הרחבות מיותרות (למעט כשאתה בונה תוכנית אימונים מפורטת).
    5. אם המשתמש מבקש ממך מפורשות אורך תשובה אחר (למשל "תענה לי קצר יותר" או "תרחיב בבקשה") - זכור את ההעדפה הזו לכל אורך השיחה ופעל לפיה, עד שתקבל הנחיה חדשה.
    """
    model = genai.GenerativeModel(model_name='gemini-flash-latest', system_instruction=system_instruction)
    st.session_state.chat_session = model.start_chat(history=[])

# --- כניסה ---
if st.session_state.user is None:
    st.title("🏃‍♂️ AI Running Coach")
    tab1, tab2 = st.tabs(["התחברות", "הרשמה"])

    with tab1:
        email_in = st.text_input("אימייל", key="login_email")
        password_in = st.text_input("סיסמה", type="password", key="login_pass")
        if st.button("התחבר", key="btn_login"):
            try:
                res = supabase.auth.sign_in_with_password({"email": email_in, "password": password_in})
                st.session_state.user = res.user
                st.session_state.sb_access_token = res.session.access_token
                st.session_state.sb_refresh_token = res.session.refresh_token
                load_user_profile(res.user.id)
                load_latest_coach_log(res.user.id)
                init_chat_session()
                st.rerun()
            except Exception as e:
                st.error(f"שגיאה בהתחברות: {e}")

    with tab2:
        email_up = st.text_input("אימייל", key="signup_email")
        password_up = st.text_input("סיסמה", type="password", key="signup_pass")
        if st.button("הירשם", key="btn_signup"):
            try:
                supabase.auth.sign_up({"email": email_up, "password": password_up})
                st.success("נרשמת! בדוק את המייל שלך לאישור.")
            except Exception as e:
                st.error(f"שגיאה בהרשמה: {e}")

    st.stop()

if st.session_state.chat_session is None: init_chat_session()
p = st.session_state.profile_data
user_prefs = json.loads(p.get("workout_preferences", "{}")) if p.get("workout_preferences") else {}
physio_json = json.loads(p.get("physiology_data") or "{}")

# --- סרגל צד ---
st.sidebar.title("אזור אישי")
st.sidebar.write(f"מחובר:\n {st.session_state.user.email}")
if st.sidebar.button("התנתק"):
    supabase.auth.sign_out()
    st.session_state.clear()
    st.rerun()

# --- האפליקציה המרכזית ---
tab_chat, tab_morning, tab_calendar, tab_records, tab_profile = st.tabs(["צ'אט 💬", "בוקר 📝", "לוח 📅", "שיאים ומבדקים 🥇", "פרופיל ⚙️"])

# -- 1: צ'אט מעוצב ואישי --
with tab_chat:
    # Header של המאמן
    st.markdown("""
        <div class="coach-header">
            <img src="https://api.dicebear.com/7.x/adventurer/svg?seed=Coach" class="coach-avatar">
            <div>
                <div class="coach-name">Coach Leo 🏃‍♂️</div>
                <div class="coach-status">● מאמן פעיל</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # אזור ההודעות
    chat_container = st.container(height=400)

    with chat_container:
        for msg in st.session_state.messages:
            safe_content = html.escape(msg["content"]).replace("\n", "<br>")
            if msg["role"] == "user":
                st.markdown(f'<div style="display:flex; justify-content:flex-end; margin-bottom: 10px;"><div class="user-msg">{safe_content}</div></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="display:flex; justify-content:flex-start; margin-bottom: 10px;"><div class="ai-msg">{safe_content}</div></div>', unsafe_allow_html=True)

    # שורת קלט יחידה
    if prompt := st.chat_input("הקלד הודעה ל-Coach Leo...", key="final_unique_chat_input"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_container:
            st.markdown(f'<div style="display:flex; justify-content:flex-end; margin-bottom: 10px;"><div class="user-msg">{html.escape(prompt)}</div></div>', unsafe_allow_html=True)
            with st.spinner("Coach Leo חושב..."):
                resp = coach_send(prompt)
                clean_text = process_ai_response_for_plan(resp.text)
                st.session_state.messages.append({"role": "assistant", "content": clean_text})
        st.rerun()

# -- 2: בוקר --
with tab_morning:
    with st.form("daily_form"):
        c1, c2, c3, c4 = st.columns(4)
        rhr = c1.number_input("דופק מנוחה", min_value=30, max_value=100, value=None, placeholder="לא סופק")
        hrv = c2.number_input("HRV", min_value=10, max_value=200, value=None, placeholder="לא סופק")
        sleep = c3.number_input("שינה (ציון)", min_value=0, max_value=100, value=None, placeholder="לא סופק")
        battery = c4.number_input("סוללת גוף", min_value=0, max_value=100, value=None, placeholder="לא סופק")
        feeling = st.number_input("תחושה כללית (1-10)", min_value=1, max_value=10, value=None, placeholder="לא סופק")
        notes = st.text_input("הערות הבוקר")

        if st.form_submit_button("שגר נתונים 🔄"):
            with st.spinner("מסנכרן היסטוריה מגרמין ומנתח..."):
                history = fetch_recent_garmin_activities(p.get("garmin_email"), p.get("garmin_password"))
                supabase.table("coach_logs").insert({
                    "user_id": st.session_state.user.id,
                    "rhr": rhr, "hrv": hrv, "sleep_score": sleep, "body_battery": battery,
                    "feeling": feeling, "user_notes": notes, "last_run_summary": history,
                }).execute()
                load_latest_coach_log(st.session_state.user.id)

                msg = f"עדכנתי את נתוני הבוקר. היסטוריית ריצות אחרונה מגרמין:\n{history}\nהאם צריך לעדכן את התוכנית להמשך השבוע? אם כן, החזר תוכנית JSON מעודכנת."
                feeling_display = feeling if feeling is not None else "לא סופק"
                st.session_state.messages.append({"role": "user", "content": f"עדכנתי מדדי בוקר (תחושה: {feeling_display}/10)."})
                response = coach_send(msg)
                clean_text = process_ai_response_for_plan(response.text)
                st.session_state.messages.append({"role": "assistant", "content": clean_text})
                st.success("הנתונים נותחו והלוח עודכן במידת הצורך!")

# -- 3: לוח אימונים דינמי --
with tab_calendar:
    if st.button("🤖 בקש מהמאמן תוכנית חדשה לשבוע הקרוב"):
        with st.spinner("המאמן מנתח שיאים וקצבים ובונה תוכנית..."):
            resp = coach_send("בנה לי תוכנית מפורטת לשבוע הקרוב מבוססת על המבדקים שלי. החזר רק JSON כמוסכם.")
            process_ai_response_for_plan(resp.text)
            st.rerun()

    weekly_plan = user_prefs.get("weekly_plan", {})
    if not isinstance(weekly_plan, dict): weekly_plan = {}

    for day_name in hebrew_days:
        day_ai_plan = weekly_plan.get(day_name, {})

        # חילוץ כותרת
        title = day_ai_plan.get("title", "מנוחה") if isinstance(day_ai_plan, dict) else "מנוחה"

        card_class, icon = "card-rest", "🛑"
        if "ריצה" in title or "אינטרוולים" in title: card_class, icon = "card-run", "🏃‍♂️"
        elif "כוח" in title or "אופניים" in title: card_class, icon = "card-cross", "💪"

        st.markdown(f"""
        <div class="calendar-card {card_class}">
            <div class="card-badge">{icon}</div>
            <div><div class="day-title">{html.escape(day_name)}</div><div class="workout-type">{html.escape(title)}</div></div>
        </div>
        """, unsafe_allow_html=True)

        # פרטי אימון ב-Expander - נפתח בתוך הזרימה (ולא כחלון צף) כדי שכמה
        # ימים פתוחים במקביל לא יתנגשו/יוצגו אחד מעל השני כמו שקורה עם popover
        with st.expander("🔍 פרטי אימון", key=f"expander_{day_name}"):
            if isinstance(day_ai_plan, dict) and title != "מנוחה":
                st.markdown(f"**🎯 מטרה:** {day_ai_plan.get('goal', 'לא הוגדרה')}")
                st.markdown("**⏱️ שלבים:**")
                steps = day_ai_plan.get("steps", [])
                if isinstance(steps, list):
                    for step in steps: st.write(f"- {step}")
                else: st.write(f"- {steps}")
                st.markdown(f"**🏃‍♂️ קצבים:** {day_ai_plan.get('paces', 'לפי תחושה')}")
            else:
                st.write("יום מנוחה מתוכנן. תן לגוף להתאושש! 🧘‍♂️")

# -- 4: שיאים ומבדקים פיזיולוגיים --
with tab_records:
    st.subheader("🥇 שיאים אישיים (PRs)")
    with st.form("prs_form"):
        c1, c2 = st.columns(2)
        pr_5k = c1.text_input("5 ק״מ", physio_json.get("pr_5k", ""), placeholder="למשל 22:30")
        pr_10k = c2.text_input("10 ק״מ", physio_json.get("pr_10k", ""), placeholder="למשל 48:00")
        pr_hm = c1.text_input("חצי מרתון", physio_json.get("pr_hm", ""))
        pr_m = c2.text_input("מרתון", physio_json.get("pr_m", ""))
        if st.form_submit_button("שמור שיאים"):
            physio_json.update({"pr_5k": pr_5k, "pr_10k": pr_10k, "pr_hm": pr_hm, "pr_m": pr_m})
            supabase.table("profiles").update({"physiology_data": json.dumps(physio_json)}).eq("id", st.session_state.user.id).execute()
            st.session_state.profile_data["physiology_data"] = json.dumps(physio_json)
            st.success("השיאים עודכנו!")

    st.divider()
    st.subheader("🔬 מבדקי דופק וכושר")
    c_max, c_lthr, c_cooper = st.columns(3)

    with c_max:
        with st.popover("איך מבצעים מבדק דופק מקסימלי?"):
            st.write("חימום 10-15 דקות. לאחר מכן, העלאת קצב הדרגתית בכל דקה (רצוי על הליכון) עד למאמץ מקסימלי שבו לא ניתן להמשיך לרוץ יותר. הדופק בנקודת השיא הוא התוצאה.")

    with c_lthr:
        with st.popover("איך מבצעים מבדק סף לקטט (LTHR)?"):
            st.write("חימום טוב. ריצה של 30 דקות במאמץ מקסימלי אך קבוע (קשה אך נשלט). בסיום האימון, בודקים מה היה ממוצע הדופק של ה-20 דקות האחרונות בלבד. זו התוצאה.")

    with c_cooper:
        with st.popover("איך מבצעים מבחן קופר?"):
            st.write("חימום. לאחר מכן, ריצה של בדיוק 12 דקות בקצב המהיר ביותר האפשרי. מודדים את המרחק הכללי (בקילומטרים) שעברת בפרק זמן זה.")

    with st.form("tests_form"):
        col1, col2, col3 = st.columns(3)
        max_hr = col1.number_input("דופק מקסימלי", min_value=100, max_value=220, value=physio_json.get("max_hr"), placeholder="לא נבדק")
        lthr = col2.number_input("סף לקטט (LTHR)", min_value=100, max_value=220, value=physio_json.get("lthr"), placeholder="לא נבדק")
        cooper = col3.number_input("מבחן קופר (ק״מ)", min_value=0.0, max_value=5.0, value=physio_json.get("cooper"), step=0.1, placeholder="לא נבדק")

        if st.form_submit_button("שמור תוצאות מבדקים"):
            physio_json.update({"max_hr": max_hr, "lthr": lthr, "cooper": cooper})
            supabase.table("profiles").update({"physiology_data": json.dumps(physio_json)}).eq("id", st.session_state.user.id).execute()
            st.session_state.profile_data["physiology_data"] = json.dumps(physio_json)
            st.success("הבדיקות נשמרו וישמשו לבניית התוכנית!")

# -- 5: פרופיל --
with tab_profile:
    st.subheader("📋 עריכת פרופיל והגדרות בסיס")
    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        weight = col1.number_input("משקל (ק״ג)", 30.0, 200.0, float(p.get("weight") or 70.0), 0.5)
        height = col2.number_input("גובה (ס״מ)", 100.0, 220.0, float(p.get("height") or 175.0), 1.0)

        goals = st.text_input("מטרות ויעדים (למשל: סיום מרתון)", p.get("goals", ""))
        g_email_edit = st.text_input("אימייל גרמין", p.get("garmin_email", ""))
        g_pass_edit = st.text_input("סיסמה גרמין (השאר ריק כדי לא לשנות)", "", type="password", placeholder="••••••••" if p.get("garmin_password") else "")

        if st.form_submit_button("שמור פרופיל"):
            update_data = {
                "id": st.session_state.user.id, "weight": weight, "height": height,
                "goals": goals, "garmin_email": g_email_edit,
            }
            if g_pass_edit:
                update_data["garmin_password"] = g_pass_edit
            supabase.table("profiles").upsert(update_data).execute()
            st.session_state.profile_data.update(update_data)
            st.success("הפרופיל עודכן!")

    st.divider()
    st.subheader("🏃 ייבוא היסטוריית ריצות מגרמין")
    st.caption("ב-Garmin Connect: Activities → סמל הייצוא → Export CSV. העלה כאן את הקובץ כדי שהמאמן ידע על הריצות והיכולת שלך בפועל, לא רק על הנתונים שהזנת ידנית.")
    garmin_csv = st.file_uploader("קובץ CSV מגרמין", type=["csv"], key="garmin_csv_uploader")

    if garmin_csv is not None and st.button("ייבא היסטוריית ריצות"):
        try:
            rows, mapping = parse_garmin_csv(garmin_csv)
            supabase.table("run_history").delete().eq("user_id", st.session_state.user.id).execute()
            if rows:
                supabase.table("run_history").insert(rows).execute()
            st.success(f"יובאו {len(rows)} פעילויות מהקובץ!")
            st.caption("עמודות שזוהו: " + ", ".join(f"{field}→{col}" for field, col in mapping.items() if col))
            init_chat_session()
        except Exception as e:
            st.error(f"שגיאה בייבוא הקובץ: {e}")
