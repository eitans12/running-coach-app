import streamlit as st
import pandas as pd
from supabase import create_client, Client
import google.generativeai as genai
from garminconnect import Garmin
import datetime
import json
import re

# --- הגדרות תצוגה מימין לשמאל ---
st.markdown("""
    <style>
    /* הגדרות גלובליות למצב כהה */
    .stApp {
        background-color: #121212 !important;
        color: #E0E0E0 !important;
    }
    
    /* עיצוב כרטיסים למצב כהה */
    .calendar-card {
        background-color: #1E1E1E !important;
        color: #FFFFFF !important;
        border-radius: 16px;
        padding: 16px;
        margin-bottom: 12px;
        border-right: 8px solid #007AFF;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    
    /* טקסטים בתוך כרטיסים */
    .day-title, .workout-type { color: #FFFFFF !important; }
    
    /* צ'אט במצב כהה */
    .user-msg { 
        background: linear-gradient(135deg, #007AFF, #5856D6) !important; 
        color: white !important; 
    }
    .ai-msg { 
        background-color: #2C2C2E !important; 
        color: #E0E0E0 !important; 
        border: 1px solid #444 !important;
    }
    
    /* תיקון צבעי טקסט בטפסים ובפלטפורמה */
    .stTextInput > div > div > input, .stNumberInput > div > div > input {
        background-color: #2C2C2E !important;
        color: white !important;
        border: 1px solid #444 !important;
    }
    
    /* כותרות */
    h1, h2, h3 { color: #FFFFFF !important; }
    
    /* לשוניות */
    [data-baseweb="tab-list"] { background-color: #121212 !important; }
    </style>
""", unsafe_allow_html=True)
# --- התחברות למסד הנתונים ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(url, key)
import streamlit as st

# ... כאן מופיע קוד האתחול של supabase (create_client וכו') ...

st.title("מאמן הריצה האישי שלך")

# יצירת לשוניות
# יצירת לשוניות
tab1, tab2 = st.tabs(["התחברות", "הרשמה"])

with tab1:
    email_in = st.text_input("אימייל", key="login_email")
    password_in = st.text_input("סיסמה", type="password", key="login_pass")
    if st.button("התחבר"):
        try:
            response = supabase.auth.sign_in_with_password({"email": email_in, "password": password_in})
            st.session_state.user = response.user
            st.success("התחברת בהצלחה! מרענן את הדף...")
            st.rerun()
        except Exception as e:
            st.error(f"שגיאה בהתחברות: {e}")

with tab2:
    email_up = st.text_input("אימייל", key="signup_email")
    password_up = st.text_input("סיסמה", type="password", key="signup_pass")
    if st.button("הירשם"):
        try:
            response = supabase.auth.sign_up({"email": email_up, "password": password_up})
            st.success("נרשמת בהצלחה! בדוק את המייל שלך לאישור.")
        except Exception as e:
            st.error(f"שגיאה בהרשמה: {e}")

# --- ניהול מצב ---
if "user" not in st.session_state: st.session_state.user = None
if "profile_data" not in st.session_state: st.session_state.profile_data = {}
if "latest_log" not in st.session_state: st.session_state.latest_log = {}
if "messages" not in st.session_state: st.session_state.messages = []
if "chat_session" not in st.session_state: st.session_state.chat_session = None

hebrew_days = ['יום ראשון', 'יום שני', 'יום שלישי', 'יום רביעי', 'יום חמישי', 'יום שישי', 'יום שבת']

# --- פונקציות עזר ---
def load_user_profile(user_id):
    res = supabase.table("profiles").select("*").eq("id", user_id).execute()
    st.session_state.profile_data = res.data[0] if res.data else {}

def load_latest_coach_log(user_id):
    try:
        res = supabase.table("coach_logs").select("*").eq("user_id", user_id).order("id", desc=True).limit(1).execute()
        st.session_state.latest_log = res.data[0] if res.data else {}
    except:
        st.session_state.latest_log = {}

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
        except:
            return response_text
    return response_text

def push_to_garmin(workout_name, day_ai_plan):
    try:
        # התחברות לגרמין
        client = Garmin(p.get("garmin_email"), p.get("garmin_password"))
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
    p = st.session_state.profile_data
    physio = json.loads(p.get("physiology_data") or "{}")
    
    # חישוב מגמה מהירה מתוך ה-coach_logs (ה-7 האחרונים)
    logs = supabase.table("coach_logs").select("*").eq("user_id", st.session_state.user.id).order("id", desc=True).limit(7).execute().data
    trend_msg = "אין מספיק נתונים לניתוח מגמה."
    if len(logs) >= 3:
        avg_feeling = sum(l['feeling'] for l in logs) / len(logs)
        trend_msg = f"מגמת תחושה ב-7 ימים אחרונים: {avg_feeling:.1f}/10."

    # כאן נכנס הניתוח החכם
    system_instruction = f"""
    אתה מאמן ריצה עילית בעל ניסיון של 20 שנה. 
    פרוטוקול עבודה: {TRAINING_PROTOCOL}
    מגמות מתאמן: {trend_msg}
    נתוני היום: {st.session_state.latest_log}
    
    חוקי עבודה:
    1. לפני כל המלצה, בצע 'ניתוח מצב': השווה את הנתונים של היום למגמה (Trend).
    2. אם אתה מזהה שחיקה לפי הנתונים, תהיה קשוח - עצור אימונים עצימים!
    3. תמיד נמק את ה-JSON שאתה בונה לפי חוקי הברזל.
    """
    model = genai.GenerativeModel(model_name='gemini-flash-latest', system_instruction=system_instruction)
    st.session_state.chat_session = model.start_chat(history=[])
# --- כניסה ---
if st.session_state.user is None:
    st.title("🏃‍♂️ AI Running Coach")
    email = st.text_input("אימייל")
    password = st.text_input("סיסמה", type="password")
    if st.button("התחבר"):
        try:
            res = supabase.auth.sign_in_with_password({"email": email, "password": password})
            st.session_state.user = res.user
            load_user_profile(res.user.id)
            load_latest_coach_log(res.user.id)
            init_chat_session()
            st.rerun()
        except: st.error("שגיאה בהתחברות")
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

# -- 1: צ'אט --
# -- 1: צ'אט מעוצב --
# -- 1: צ'אט מעוצב ואישי --
# -- 1: צ'אט מעוצב ואישי --
with tab_chat:
    # Header של המאמן
    st.markdown("""
        <div style="display: flex; align-items: center; padding-bottom: 15px; border-bottom: 1px solid #444; margin-bottom: 15px;">
            <img src="https://api.dicebear.com/7.x/adventurer/svg?seed=Coach" style="width: 45px; height: 45px; border-radius: 50%; margin-left: 12px; background: #333;">
            <div>
                <div style="font-weight: bold; font-size: 17px; color: white;">Coach Leo 🏃‍♂️</div>
                <div style="font-size: 12px; color: #4CAF50;">● מאמן פעיל</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # אזור ההודעות
    chat_container = st.container(height=400)
    
    with chat_container:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                st.markdown(f'<div style="display:flex; justify-content:flex-end; margin-bottom: 10px;"><div class="user-msg">{msg["content"]}</div></div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="display:flex; justify-content:flex-start; margin-bottom: 10px;"><div class="ai-msg">{msg["content"]}</div></div>', unsafe_allow_html=True)

    # שורת קלט יחידה
    if prompt := st.chat_input("הקלד הודעה ל-Coach Leo...", key="final_unique_chat_input"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with chat_container:
            st.markdown(f'<div style="display:flex; justify-content:flex-end; margin-bottom: 10px;"><div class="user-msg">{prompt}</div></div>', unsafe_allow_html=True)
            with st.spinner("Coach Leo חושב..."):
                resp = st.session_state.chat_session.send_message(prompt)
                clean_text = process_ai_response_for_plan(resp.text)
                st.session_state.messages.append({"role": "assistant", "content": clean_text})
        st.rerun()
# -- 2: בוקר --
with tab_morning:
    with st.form("daily_form"):
        c1, c2, c3, c4 = st.columns(4)
        rhr = c1.number_input("דופק מנוחה", 30, 100, 50)
        hrv = c2.number_input("HRV", 10, 200, 50)
        sleep = c3.number_input("שינה (ציון)", 0, 100, 80)
        battery = c4.number_input("סוללת גוף", 0, 100, 75)
        feeling = st.number_input("תחושה כללית (1-10)", 1, 10, 7)
        notes = st.text_input("הערות הבוקר")
        
        if st.form_submit_button("שגר נתונים 🔄"):
            with st.spinner("מסנכרן היסטוריה מגרמין ומנתח..."):
                history = fetch_recent_garmin_activities(p.get("garmin_email"), p.get("garmin_password"))
                msg = f"מדדי בוקר: דופק {rhr}, HRV {hrv}, שינה {sleep}, תחושה {feeling}/10. הערות: {notes}. היסטוריה:\n{history}\nהאם צריך לעדכן את התוכנית להמשך השבוע? אם כן, החזר תוכנית JSON מעודכנת."
                st.session_state.messages.append({"role": "user", "content": f"עדכנתי מדדי בוקר (תחושה: {feeling}/10)."})
                response = st.session_state.chat_session.send_message(msg)
                clean_text = process_ai_response_for_plan(response.text)
                st.session_state.messages.append({"role": "assistant", "content": clean_text})
                st.success("הנתונים נותחו והלוח עודכן במידת הצורך!")

# -- 3: לוח אימונים דינמי --
# -- 3: לוח אימונים דינמי --
with tab_calendar:
    if st.button("🤖 בקש מהמאמן תוכנית חדשה לשבוע הקרוב"):
        with st.spinner("המאמן מנתח שיאים וקצבים ובונה תוכנית..."):
            resp = st.session_state.chat_session.send_message("בנה לי תוכנית מפורטת לשבוע הקרוב מבוססת על המבדקים שלי. החזר רק JSON כמוסכם.")
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
            <div><div class="day-title">{day_name}</div><div class="workout-type">{icon} {title}</div></div>
        </div>
        """, unsafe_allow_html=True)
        
        # פרטי אימון ב-Popover נקי ללא כפתורי שליחה מיותרים
        # פרטי אימון ב-Popover נקי ללא כפתורי שליחה מיותרים
        with st.popover(f"🔍 פרטי אימון"):
            if isinstance(day_ai_plan, dict) and title != "מנוחה":
                st.markdown(f"**🎯 מטרה:** {day_ai_plan.get('goal', 'לא הוגדרה')}")
                st.markdown("**⏱️ שלבים:**")
                steps = day_ai_plan.get("steps", [])
                if isinstance(steps, list):
                    for step in steps: st.write(f"- {step}")
                else: st.write(f"- {steps}")
                st.markdown(f"**🏃‍♂️ קצבים:** {day_ai_plan.get('paces', 'לפי תחושה')}")
                # כאן מחקנו את הכפתור!
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
        max_hr = col1.number_input("דופק מקסימלי", 100, 220, int(physio_json.get("max_hr", 190)))
        lthr = col2.number_input("סף לקטט (LTHR)", 100, 220, int(physio_json.get("lthr", 170)))
        cooper = col3.number_input("מבחן קופר (ק״מ)", 0.0, 5.0, float(physio_json.get("cooper", 2.5)), step=0.1)
        
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
        g_pass_edit = st.text_input("סיסמה גרמין", p.get("garmin_password", ""), type="password")
        
        if st.form_submit_button("שמור פרופיל"):
            supabase.table("profiles").upsert({
                "id": st.session_state.user.id, "weight": weight, "height": height, 
                "goals": goals, "garmin_email": g_email_edit, "garmin_password": g_pass_edit
            }).execute()
            st.session_state.profile_data.update({"weight": weight, "height": height, "goals": goals, "garmin_email": g_email_edit, "garmin_password": g_pass_edit})
            st.success("הפרופיל עודכן!")