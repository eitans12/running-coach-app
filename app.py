import streamlit as st
import pandas as pd
from supabase import create_client, Client
from google import genai
from google.genai import types
from google.genai.errors import ClientError
from garminconnect import Garmin, GarminConnectTooManyRequestsError
import time
import datetime
import json
import re
import html

# --- עיצוב אפליקציית ספורט: פונט, פלטת צבעים וכרטיסים ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;600;700;800&display=swap');

    :root {
        color-scheme: light;
        --background: #FAF8F5;
        --foreground: #1F1A14;
        --card: #FFFFFF;
        --card-foreground: #1F1A14;
        --popover: #FFFFFF;
        --popover-foreground: #1F1A14;
        --primary: #8F5024;
        --primary-foreground: #FAF8F5;
        --secondary: #F0ECE6;
        --secondary-foreground: #3D3329;
        --muted: #F3F1ED;
        --muted-foreground: #8C8073;
        --accent: #DDB43C;
        --accent-foreground: #1F1A14;
        --border-soft: rgba(31,26,20,0.08);
        --border-strong: rgba(31,26,20,0.18);
        --shadow-sm: 0 1px 2px rgba(31,26,20,0.06), 0 1px 1px rgba(31,26,20,0.04);
        --shadow-md: 0 4px 14px rgba(31,26,20,0.08);
        --success: #3F7D4F;
        --warning: #C97A2B;
        --danger: #B94A3C;
    }

    @media (prefers-color-scheme: dark) {
        :root {
            color-scheme: dark;
            --background: #17130F;
            --foreground: #F3EDE3;
            --card: #221C16;
            --card-foreground: #F3EDE3;
            --popover: #221C16;
            --popover-foreground: #F3EDE3;
            --primary: #E1A868;
            --primary-foreground: #1F1A14;
            --secondary: #2C241C;
            --secondary-foreground: #EAE1D4;
            --muted: #26201A;
            --muted-foreground: #A99C8B;
            --accent: #E8C566;
            --accent-foreground: #1F1A14;
            --border-soft: rgba(255,247,235,0.08);
            --border-strong: rgba(255,247,235,0.16);
            --shadow-sm: 0 1px 2px rgba(0,0,0,0.35), 0 1px 1px rgba(0,0,0,0.25);
            --shadow-md: 0 6px 20px rgba(0,0,0,0.4);
            --success: #6FCB86;
            --warning: #E3A458;
            --danger: #E38070;
        }
    }

    html, body, [class*="css"], .stApp, .stMarkdown, p, span, div, button, input, textarea, label {
        font-family: 'Rubik', 'Segoe UI', Arial, sans-serif !important;
    }

    [data-testid="stIconMaterial"], [data-testid="stIconEmoji"], .material-symbols-outlined, .material-symbols-rounded {
        font-family: 'Material Symbols Rounded', 'Material Icons' !important;
    }

    .stApp {
        background: radial-gradient(1200px 600px at 15% -10%, rgba(221,180,60,0.08), transparent 60%),
                    radial-gradient(1000px 500px at 100% 0%, rgba(143,80,36,0.06), transparent 55%),
                    var(--background) !important;
    }

    h1, h2, h3 {
        color: var(--foreground) !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em;
    }

    /* מכולת תוכן ראשית - קריאות טובה יותר במסכים רחבים */
    .block-container {
        max-width: 900px !important;
        padding-top: 2rem !important;
    }

    /* כרטיס בסיס לשימוש כללי */
    .app-card {
        background-color: var(--card);
        border: 1px solid var(--border-soft);
        border-radius: 16px;
        padding: 18px 20px;
        box-shadow: var(--shadow-sm);
        margin-bottom: 12px;
        transition: box-shadow 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
    }
    .app-card:hover { box-shadow: var(--shadow-md); border-color: var(--border-strong); }

    /* כותרת מאמן */
    .coach-header {
        display: flex; align-items: center; gap: 12px;
        padding: 14px 18px; margin-bottom: 18px;
        background: linear-gradient(135deg, rgba(143,80,36,0.10), rgba(221,180,60,0.10));
        border: 1px solid var(--border-soft);
        border-radius: 16px;
    }
    .coach-avatar {
        width: 48px; height: 48px; border-radius: 50%;
        background: var(--secondary); border: 2px solid var(--primary);
        box-shadow: var(--shadow-sm);
    }
    .coach-name { font-weight: 700; font-size: 17px; color: var(--foreground); }
    .coach-status { font-size: 12px; color: var(--primary); font-weight: 600; display: flex; align-items: center; gap: 5px; }
    .coach-status::before {
        content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
        background: var(--success); box-shadow: 0 0 0 3px rgba(63,125,79,0.18);
    }

    /* בועות שיחה */
    .user-msg {
        background: linear-gradient(135deg, var(--primary), var(--accent)) !important;
        color: var(--primary-foreground) !important;
        padding: 11px 17px; border-radius: 18px 18px 4px 18px;
        max-width: 75%; font-size: 15px; line-height: 1.55;
        box-shadow: 0 3px 10px rgba(143,80,36,0.28);
        margin-bottom: 4px;
    }
    .ai-msg {
        background-color: var(--card) !important;
        color: var(--card-foreground) !important;
        border: 1px solid var(--border-soft) !important;
        padding: 11px 17px; border-radius: 18px 18px 18px 4px;
        max-width: 75%; font-size: 15px; line-height: 1.55;
        box-shadow: var(--shadow-sm);
        margin-bottom: 4px;
    }

    /* כרטיסי יומן/אימונים */
    .calendar-card {
        background-color: var(--card);
        border: 1px solid var(--border-soft);
        border-radius: 14px;
        padding: 14px 18px;
        margin-bottom: 10px;
        display: flex; align-items: center; gap: 14px;
        box-shadow: var(--shadow-sm);
        transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
    }
    .calendar-card:hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); transform: translateY(-1px); }
    .card-badge {
        width: 42px; height: 42px; min-width: 42px;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 19px;
    }
    .calendar-card.card-run .card-badge { background: rgba(143,80,36,0.15); }
    .calendar-card.card-cross .card-badge { background: rgba(221,180,60,0.25); }
    .calendar-card.card-rest .card-badge { background: var(--muted); }

    /* הדגשת אימון היום */
    .calendar-card.card-today {
        border: 2px solid var(--primary);
        box-shadow: 0 0 0 3px rgba(143,80,36,0.14), var(--shadow-md);
    }
    .today-badge {
        display: inline-block;
        background: linear-gradient(135deg, var(--primary), var(--accent));
        color: var(--primary-foreground);
        font-size: 10px; font-weight: 700;
        padding: 2px 9px;
        border-radius: 999px;
        letter-spacing: 0.02em;
    }

    .day-title { color: var(--muted-foreground) !important; font-size: 13px; font-weight: 500; }
    .workout-type { color: var(--foreground) !important; font-size: 15.5px; font-weight: 600; }

    /* טאבים */
    [data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--border-soft); }
    [data-baseweb="tab"] { font-weight: 600; border-radius: 10px 10px 0 0 !important; padding: 8px 4px !important; }
    [data-baseweb="tab-highlight"] { background-color: var(--primary) !important; height: 3px !important; border-radius: 3px; }
    [aria-selected="true"] { color: var(--primary) !important; }

    /* כפתורים */
    .stButton > button, .stFormSubmitButton > button {
        border-radius: 12px !important;
        font-weight: 600 !important;
        padding: 0.65rem 1.6rem !important;
        font-size: 16px !important;
        transition: transform 0.12s ease, box-shadow 0.12s ease, filter 0.12s ease, background 0.12s ease;
    }
    /* Primary CTA buttons: st.button(..., type="primary") */
    .stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primaryFormSubmit"], .stFormSubmitButton > button[kind="primary"] {
        background: linear-gradient(135deg, var(--primary), #A6642F) !important;
        color: var(--primary-foreground) !important;
        border: 1px solid var(--primary) !important;
        box-shadow: var(--shadow-sm);
        padding: 0.7rem 1.75rem !important;
    }
    .stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primaryFormSubmit"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
        filter: brightness(1.06);
        box-shadow: var(--shadow-md);
        transform: translateY(-1px);
    }
    .stButton > button[kind="primary"]:active, .stFormSubmitButton > button[kind="primaryFormSubmit"]:active, .stFormSubmitButton > button[kind="primary"]:active { transform: translateY(0); }
    /* Secondary / utility buttons: default type, lighter outline style */
    .stButton > button[kind="secondary"], .stFormSubmitButton > button[kind="secondaryFormSubmit"], .stFormSubmitButton > button[kind="secondary"] {
        background: var(--secondary) !important;
        color: var(--secondary-foreground) !important;
        border: 1px solid var(--border-soft, var(--secondary)) !important;
        box-shadow: none !important;
        font-weight: 500 !important;
    }
    .stButton > button[kind="secondary"]:hover, .stFormSubmitButton > button[kind="secondaryFormSubmit"]:hover, .stFormSubmitButton > button[kind="secondary"]:hover {
        filter: brightness(0.97);
        box-shadow: var(--shadow-sm);
        transform: translateY(-1px);
    }
    .stButton > button[kind="secondary"]:active, .stFormSubmitButton > button[kind="secondaryFormSubmit"]:active, .stFormSubmitButton > button[kind="secondary"]:active { transform: translateY(0); }

    /* שדות קלט */
    .stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input {
        border-radius: 10px !important;
        border: 1px solid var(--border-soft) !important;
        background-color: var(--card) !important;
        color: var(--foreground) !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
        border-color: var(--primary) !important;
        box-shadow: 0 0 0 3px rgba(143,80,36,0.15) !important;
    }
    [data-baseweb="select"] > div {
        border-radius: 10px !important;
        border-color: var(--border-soft) !important;
        background-color: var(--card) !important;
    }

    /* מדדים (st.metric) */
    [data-testid="stMetric"] {
        background-color: var(--card);
        border: 1px solid var(--border-soft);
        border-radius: 14px;
        padding: 12px 16px;
        box-shadow: var(--shadow-sm);
    }
    [data-testid="stMetricValue"] { color: var(--primary) !important; font-weight: 700 !important; }
    [data-testid="stMetricLabel"] { color: var(--muted-foreground) !important; }

    /* פרוגרס בר */
    .stProgress > div > div > div { background: linear-gradient(90deg, var(--primary), var(--accent)) !important; }
    .stProgress > div > div { background-color: var(--muted) !important; border-radius: 999px; }

    /* סרגל צד */
    section[data-testid="stSidebar"] {
        background-color: var(--secondary) !important;
        border-inline-end: 1px solid var(--border-soft);
    }
    section[data-testid="stSidebar"] .stButton > button {
        background: var(--card) !important;
        color: var(--foreground) !important;
        border: 1px solid var(--border-soft) !important;
    }

    /* אקספנדר */
    [data-testid="stExpander"] {
        border: 1px solid var(--border-soft) !important;
        border-radius: 12px !important;
        background-color: var(--card) !important;
        box-shadow: var(--shadow-sm);
    }

    /* גלילה עדינה */
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 999px; }
    ::-webkit-scrollbar-track { background: transparent; }
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

KNOWLEDGE_BASE = """
מאגר ידע מקצועי - אתה מאמן ריצה בעל ידע רחב ומעודכן, מבוסס על מדע האימונים והספרות המקצועית העדכנית בעולם הריצה. השתמש בידע הזה כדי לתת עצות מבוססות ומדויקות, לא רק תגובות גנריות.

### פיזיולוגיה ומדעי האימון
- VO2max: הקיבולת האירובית המקסימלית. משתפר ע"י אינטרוולים בעצימות גבוהה (Z4/Z5), אך גם דורש בסיס אירובי רחב לפני כן.
- סף אנאירובי (Lactate Threshold): הקצב הגבוה ביותר שניתן לשמר לאורך זמן בלי הצטברות חומצת חלב מוגזמת. אימוני טמפו (20-40 דקות בקצב סף) משפרים אותו.
- כלכלת ריצה (Running Economy): כמות החמצן הנדרשת בקצב נתון. משתפרת ע"י ריצות בקצב מרוץ, עבודת עוצמה (plyometrics), ותדירות צעד (cadence) גבוהה יחסית (בד"כ 170-185 צעד/דקה).
- אימון מקוטב (Polarized / 80-20): כ-80% מנפח האימונים בעצימות נמוכה (Z1-Z2, קצב שיחה נוחה), וכ-20% בעצימות גבוהה (סף ומעלה). מונע שחיקה ותורם להתקדמות ארוכת טווח.
- פריודיזציה: חלוקת התוכנית לשלבים - בסיס (נפח, אירובי) - בנייה (איכות, סף/VO2max) - שיא (ספציפי למרוץ) - הפחתה/טייפר (ירידת נפח, שמירת עצימות, לפני התחרות).
- אזורי דופק: Z1 החלמה (כ-50-60% מהדופק המקסימלי), Z2 אירובי בסיס (60-70%), Z3 סף אירובי (70-80%), Z4 סף אנאירובי (80-90%), Z5 VO2max/אנאירובי (90-100%).
- כלל ה-10%: לא להעלות נפח שבועי ביותר מ-10% משבוע לשבוע, כדי למנוע פציעות עומס-יתר.

### מניעת פציעות וביומכניקה
- פציעות נפוצות: תסמונת ה-IT Band (כאב חיצוני בברך), "ברך הרץ" (Runner's Knee / PFPS), דלקת גיד אכילס, פאשיטיס פלנטרי (כאב בעקב/כף הרגל בבוקר), שברי מאמץ (stress fractures), דלקת פריאוסט (shin splints).
- יחס עומס חריף-כרוני (ACWR): היחס בין העומס בשבוע האחרון לממוצע 4 השבועות האחרונים. יחס מעל כ-1.5 מעלה משמעותית סיכון לפציעה.
- אימוני כוח: חיזוק ישבן (glutes), core, ויציבות חד-רגלית מפחיתים פציעות ברכיים וירכיים. מומלץ כ-2 פעמים בשבוע.
- טכניקת ריצה: נחיתה קרובה למרכז הכובד (לא overstriding), תדירות צעד גבוהה יחסית, יציבה זקופה עם נטייה קלה קדימה מהקרסוליים.
- החלמה: שינה איכותית (7-9 שעות), ימי מנוחה/החלמה אקטיבית, לא להתעלם מכאב חד שמחמיר תוך כדי ריצה - זה סימן אזהרה לעצור.

### תזונה ותדלוק
- תדלוק למרוץ ארוך (חצי/מרתון): כ-30-60 גרם פחמימות לשעה במהלך המרוץ, ותמיד לתרגל את התדלוק באימונים מראש ולא ביום המרוץ עצמו.
- טעינת פחמימות (carb loading): 2-3 ימים לפני מרתון, הגברת צריכת פחמימות לכ-8-10 גרם/ק"ג משקל גוף ליום.
- הידרציה: לשתות לפי צמא ולשים לב לנתרן במיוחד במרחקים ארוכים ובחום. שתייה עודפת (hyponatremia) מסוכנת לא פחות מהתייבשות.
- תזונת יומיום לרץ: פחמימות מספקות לתדלוק אימונים, חלבון לשיקום שריר (כ-1.2-1.6 גרם/ק"ג), ותשומת לב לברזל וויטמין D שנפוצים בחוסר אצל ספורטאי סיבולת.

### שיטות אימון מוכרות בעולם
- ג'ק דניאלס (Jack Daniels / VDOT): שיטה מבוססת על מדד VDOT (מחושב מתוצאת מרוץ) לחישוב קצבי אימון מדויקים (Easy, Marathon, Threshold, Interval, Repetition).
- פיצינגר (Pfitzinger): תוכניות מרתון עם דגש כבד על ריצות בקצב סף (LT runs) ונפח גבוה יחסית.
- Hanson's Marathon Method: מבוסס על "עייפות מצטברת" - ריצות איכות תכופות, וריצה ארוכה מוגבלת לכ-25-26 ק"מ כדי לדמות עייפות סוף מרתון בלי צורך בהחלמה ארוכה.
- ליידיארד (Lydiard): בניית בסיס אירובי רחב לפני מעבר לעבודת מהירות/אנאירובית - מקסימום נפח אירובי בר-קיימא.
- רנאטו קנובה (Renato Canova): שיטות ספציפיות לרמת עילית, כולל "בלוקים מיוחדים" שמדמים בדיוק את דרישות המרוץ.

השתמש בידע הזה כבסיס המקצועי שלך, אך תמיד התאם אותו למידע האישי, לרמת הכושר ולמטרות של המשתמש הספציפי - אל תיתן עצות גנריות שמתעלמות מהנתונים שכבר יש לך עליו.

### עדכונים ממחקר עדכני ומאמני ריצה מובילים (כולל תוכן מיוטיוב ומחקרים חדשים)
- אימון Zone 2 בפועל: החישוב המדויק הוא לפי HRR (Heart Rate Reserve) - (דופק מקסימלי פחות דופק מנוחה) * 60%-70% ועוד דופק מנוחה. קצב השיחה בד"כ איטי ב-1.5-3 דקות לק"מ מקצב 5 ק"מ. רצים עילית מבלים כ-60-75% מהנפח השבועי שלהם ב-Zone 2 - זו לא "ריצה מבוזבזת" אלא הבסיס שמאפשר את האימונים הקשים.
- טעות נפוצה (מגמת "Zone 2 בלבד"): להתמקד רק ב-Zone 2 ולהתעלם מאימוני איכות (Zone 3-5) מוביל לקיפאון בביצועים - שיפור שיא אישי דורש שילוב של שני הקצוות (אימון מקוטב), לא רק בסיס איטי.
- פרוטוקול נורווגי 4x4 (שיטה מוכחת לשיפור VO2max): 4 חזרות של 4 דקות ב-90-95% מהדופק המקסימלי, עם 3 דקות החלמה פעילה ב-60-70% מהדופק המקסימלי בין החזרות, לאחר חימום של כ-10 דקות. מומלץ 2-3 פעמים בשבוע עם לפחות 48 שעות מנוחה בין אימונים. מחקרים (NTNU) מראים שיפור של כ-7-10% ב-VO2max תוך 8 שבועות.
- נעליים עם פלטת קרבון: מחקרים וסקירות שיטתיות (2025-2026) מראים שיפור ממוצע של כ-2-3% בכלכלת הריצה (טווח כ-1% עד 4.5% בהתאם למדידה), במיוחד ככל שהקצב עולה והמרחק מתארך. זה יתרון משמעותי אך לא קסם - טכניקה, נפח אימונים והתאמה אישית עדיין המרכיבים הכי חשובים.

השתמש בעדכונים האלו כדי לתת תשובות עדכניות ומדויקות, אבל תמיד תוך שילוב עם הבסיס המקצועי הקבוע שלך ועם הנתונים האישיים של המשתמש.

### בחירת נעלי ריצה
- ה"מסנן הנוחות" (Comfort Filter - מחקר של Nigg ואחרים, BJSM 2015): הגישה המסורתית שממליצה על נעל לפי סוג כף רגל/פרונציה (שטוחה מול קשת גבוהה) לא הוכחה כמפחיתה פציעות בפועל. הפרדיגמה העדכנית: לכל רץ יש "נתיב תנועה מועדף" טבעי, והנעל הכי נוחה מיידית לרץ הספציפי היא לרוב הבחירה הבטוחה ביותר - יותר מאבחון פרונציה חד-פעמי בחנות.
- סוגי נעליים: ניטרליות (מתאימות לרוב הרצים), יציבות/סטביליטי (עבור רצים שחווים אי-נוחות הקשורה לתנועה מוגזמת של כף הרגל פנימה), ומוטו-קונטרול (למקרים קיצוניים בלבד). ההמלצה המודרנית - לבחור בעיקר לפי תחושת נוחות אישית בזמן ניסוי, ולא רק לפי "אבחון" תיאורטי.
- כרית (cushioning): רצים מנוסים ומהירים נוטים להעדיף כרית מתונה יותר לתחושת קרקע וקצב תגובה טוב יותר; מתחילים ורצים כבדים יותר לרוב נהנים מכרית גבוהה יותר לספיגת זעזועים. יותר כרית לא תמיד עדיף - זה תלוי בסגנון ריצה ובמטרות.
- מדד ה-Drop (הפרש גובה בין עקב לכף): נע בד"כ בין 0 מ"מ (זירו-דרופ/מינימליסטי) ל-12 מ"מ. דרופ נמוך מעודד נחיתה על אמצע/קדמת כף הרגל; דרופ גבוה יותר נוח יותר לנחיתת עקב. מעבר לדרופ שונה מהרגיל צריך להיעשות בהדרגה כדי למנוע פציעות עומס על גיד אכילס ושריר השוק.
- התאמה (fit): רווח של כרוחב אגודל בין האצבע הארוכה לקצה הנעל, עקב יציב שלא מחליק, בלי לחץ באמצע כף הרגל, ומספיק מקום לאצבעות. נעל טובה אמורה להרגיש נוחה כבר בניסיון הראשון - בלי צורך ב"תקופת הרגלה" ארוכה.
- החלפת נעליים: בד"כ כל 300-500 מייל (כ-480-800 ק"מ), בהתאם למשקל הרץ, נפח האימונים וסוג הנעל. סימנים להחלפה: כאבים חדשים שמופיעים בריצות מוכרות, שחיקה לא אחידה בסוליה, או קריסה/שיטוח של המידסול.
- רוטציית נעליים: מחקר (Malisoux ואחרים, 2015, כתב עת סקנדינבי לרפואת ספורט, 264 רצים למשך 22 שבועות) מצא סיכון פציעה נמוך ב-39% אצל רצים שהחליפו בין כמה זוגות נעליים לעומת שימוש בזוג יחיד קבוע. הסיבה: כל נעל יוצרת עומס ביומכני מעט שונה על השרירים והרקמות, וגם לקצף (foam) יש צורך בכ-24-48 שעות "התאוששות" בין ריצות. מומלץ במיוחד לרצים שמתאמנים 4 פעמים בשבוע ומעלה - למשל נעל יומיומית רכה יותר לצד נעל קלה למרוץ/אימוני איכות.
- התאמה לסביבה: נעלי כביש שונות מנעלי שטח (טרייל) - נעלי טרייל מציעות אחיזה טובה יותר על קרקע לא אחידה והגנה מפני אבנים, אך פחות מתאימות לריצה ממושכת על אספלט.
- מסקנה מעשית לרץ: אל תבחר נעל רק לפי מותג או "אבחון פרונציה" חד-פעמי בחנות - תן משקל רב לתחושת הנוחות המיידית בניסיון, למטרת השימוש (אימון יומיומי מול מרוץ מהיר), ולשילוב של כמה זוגות שונים בשגרה השבועית.
"""

TRAINING_PROTOCOL = """
עקרונות מדעיים לבניית תוכנית ריצה - השתמש בהם בפועל בכל תוכנית, לא רק כרקע כללי:

1. פריודיזציה ועומס: הגדל נפח שבועי בהדרגה (לא יותר מ-10% בין שבוע לשבוע), עם שבוע התאוששות (ירידה של 20-30% בנפח) כל 3-4 שבועות. אל תתכנן שני אימונים עצימים (סף/VO2max/אינטרוולים) ברצף - תמיד לפחות יום קל או מנוחה ביניהם.

2. חלוקת עצימות 80/20 (אימון מקוטב / polarized training): כ-80% מהזמן השבועי צריך להיות באזור קל-מאוד (Z1-Z2, מתחת ל-85-89% מדופק הסף LTHR, קצב שאפשר לדבר בו במשפטים שלמים) וכ-20% באזור סף ומעלה (Z4-Z5). הימנע מ"אזור אפור" (Z3, טמפו בעצימות בינונית) - זה לא מספיק קל כדי לבנות בסיס ולא מספיק קשה כדי לשפר סף/VO2max, וזו הטעות הנפוצה ביותר של רצים חובבים.

3. בסיס אירובי (Aerobic Base / Zone 2): ריצות קלות וארוכות ב-Z2 בונות רשת נימיות ומיטוכונדריה בשריר ומשפרות שריפת שומן כדלק, מה שדוחה את הצטברות חומצת החלב לקצב גבוה יותר. התהליך לוקח כ-8-12 שבועות של עקביות ולא ניתן "לקצר" עם אימונים קשים - שלב בסיס תמיד קודם לשלב עצימות אצל רץ שחוזר מהפסקה או בונה יכולת חדשה.

4. אימוני סף (Threshold/Tempo): מטרתם להעלות את דופק/קצב הסף עצמו (LT2) כדי לאפשר לרוץ מהר יותר לפני שחומצת החלב מצטברת. מבנה טיפוסי: 20-40 דק' רצף ב-Z4 (כ-95-99% מדופק הסף), או אינטרוולים ארוכים (למשל 3x10 דק' ב-Z4 עם 2-3 דק' מנוחה קלה). לא יותר מפעם-פעמיים בשבוע, ולא בסמוך לאימון VO2max.

5. אימוני VO2max (אינטרוולים): מטרתם למקסם את קצב צריכת החמצן המרבי. מבנה: חזרות של 3-5 דק' בעצימות Z5 (כ-103-115% מדופק הסף, קרוב לקצב 3-5 ק"מ), עם מנוחה פעילה (ריצה קלה) בזמן דומה או מעט קצר מזמן העבודה, סה"כ 15-25 דק' עבודה איכותית. חימום ארוך (15-20 דק') חשוב - לוקח כ-2 דקות מאמץ עד שצריכת החמצן מגיעה לשיא, אז חזרות קצרות מדי לא מספיקות לגירוי אפקטיבי.

6. פארטלק (Fartlek): ריצה רציפה עם שינויי קצב לא-מובנים (למשל "מהר עד העץ הבא, ואז חזרה לקצב קל") - משלבת גירוי אירובי ואנאירובי בלי ההפסקות המלאות של אינטרוולים קלאסיים. שימושי לגיוון, לפיתוח תחושת קצב ולעבודה על מעברי עצימות, בעיקר בעונת בסיס/טרום-תחרות.

7. חזרות/ספרינטים (Strides): ריצות קצרות של 15-20 שניות (כ-80-120 מ') כמעט במאמץ מרבי, עם התאוששות מלאה (60-90 שניות) בין חזרה לחזרה, בד"כ 4-8 חזרות בסוף ריצה קלה. המטרה היא מכניקת ריצה וקצב צעד - לא כושר אירובי - ולכן אינן "מתחרות" על משאבי ההתאוששות כמו VO2max, ואפשר לשלב אותן גם בשבועות בסיס.

8. שילוב שבועי מומלץ (רץ חובב, 5-6 ימי אימון): 3-4 ריצות קלות/Z2 (כולל ריצה ארוכה אחת), אימון סף אחד, אימון VO2max/אינטרוולים אחד (לא באותו שבוע עם שני אימוני סף), ואופציונלית ספרינטים בסוף ריצה קלה פעם-פעמיים בשבוע. לפחות יום מנוחה מלא אחד.

9. ריצה ארוכה (Long Run): מפתחת סיבולת שריר-שלד, ניצול שומן כדלק ועמידות מנטלית - חשוב שתהיה נוחה ולא תסכן את שאר השבוע. קצב: כ-30-90 שניות/ק"מ איטי מקצב המרוץ (Z2, כ-65-75% מדופק מקס'). הארכה הדרגתית - לא יותר מ-10-15 דק' (או כ-10%) לשבוע, עם שבוע נחיתה כל 3-4 שבועות. בשבועות ספציפיים-מרוץ אפשר "ריצה ארוכה מתקדמת" (מתחילה קלה ומסיימת בקצב מרוץ) או "סיום מהיר" (20-30% אחרונים בקצב טמפו) כדי לתרגל את קצב המרוץ בעייפות.

10. אימוני עליות (Hill Training): שני סוגים שונים, לא ניתנים להחלפה. (א) חזרות עליה קצרות/ספרינטים: עליה תלולה (4-7%), 8-15 שניות מאמץ כמעט מקסימלי, ירידה כהתאוששות מלאה, 6-10 חזרות - בונות כוח נפיצי ועוצמה בסיכון נמוך יותר מספרינט במישור. (ב) חזרות עליה ארוכות: עליה מתונה, 60 שנ'-4 דק' בעצימות סף/VO2max, ירידה כהתאוששות - בונות כוח-סיבולת ו-VO2max עם פחות עומס-אימפקט מריצה במישור, ולכן משמשות גשר טוב בין שלב בסיס לשלב עצימות.

11. אימוני כוח לרצים: אימון כוח 2 פעמים בשבוע מפחית פציעות-שחיקה משמעותית ומשפר יעילות ריצה. תרגילי ליבה: סקוואט, לאנג', דדליפט (או וריאציה), step-up, ותרגילי core/פלייומטריה - 3 סטים של 10-15 חזרות, 20-30 דק' לאימון. תזמן ביום קל או לפחות 24-48 שעות לפני אימון איכות/עצימות גבוהה - לא צמוד לפני VO2max או ריצה ארוכה.

12. הפחתת עומס לקראת מרוץ (Taper): 2-3 שבועות לפני מרתון/חצי מרתון - הפחתה הדרגתית של נפח (לא של עצימות): כ-10-15% פחות 3 שבועות לפני, 30-40% פחות שבועיים לפני, 40-60% פחות בשבוע המרוץ. שומרים על תדירות הריצה ומעט עצימות (סטריידס, קטעים קצרים בקצב מרוץ) כדי לא לאבד תחושת קצב - עיקר הקיצוץ בריצה הארוכה ובנפח אימוני האיכות, לא בריצות הקלות.

13. מניעת פציעות וסימני אזהרה: כלל 10% - אל תגדיל נפח שבועי (או ריצה ארוכה) ביותר מ-10% משבוע לשבוע. סימנים שדורשים עצירה/הפחתה מיידית של האימונים המתוכננים: כאב שלא נעלם ב-10 הדקות הראשונות של ריצה, כאב שמחמיר במהלך הריצה, כאב בהליכה/במנוחה, נפיחות נראית לעין, שינוי בתבנית הריצה בגלל כאב, או כאב מעל 4/10. פציעות שכיחות: shin splints, דלקת גיד אכילס, כאב פיקת הברך/IT Band, פאשיטיס פלנטרי, שברי מאמץ. אם המשתמש מדווח על כאב כזה - אל תמשיך לתכנן עצימות/ריצה ארוכה כרגיל; המלץ על מנוחה/הפחתה ופנייה לאיש מקצוע במידת הצורך.

14. אסטרטגיית קצב ביום מרוץ: העדף קצב אחיד או "negative split" - להתחיל בנוח ולא מהר מדי (טעות נפוצה שגורמת לקריסה בשליש האחרון) ולסיים באותו קצב או מהר יותר. בשבועות הספציפיים-מרוץ, שלב קטעים בקצב מרוץ ממש בתוך ריצות ארוכות/אימוני איכות כדי לתרגל אותו פיזית ומנטלית מראש.
"""

READINESS_PROTOCOL = """
פענוח נתוני עדכון הבוקר (RHR / HRV / שינה / סוללת גוף / תחושה) מול המגמה של המתאמן - זה חייב להשפיע בפועל על ההמלצה של היום, לא רק להיאמר כללית:

- דופק מנוחה (RHR): עלייה של כ-5+ פעימות (או כ-7-10%) מעל הבייסליין האישי, יומיים ברצף ומעלה, מעידה על עומס/מחלה/התייבשות שלא התאוששו ממנו. חריגה חד-פעמית וקלה פחות משמעותית.
- HRV: ירידה ברורה ועקבית (לא תנודה טבעית של יום אחד) מתחת לבייסליין מעידה על דומיננטיות סימפתטית/עומס לא מעובד - זה האינדיקטור הרגיש ביותר לאובר-ריצינג. HRV גבוה מהרגיל הוא בד"כ סימן חיובי.
- ציון שינה (0-100): מתחת ל-60 = שינה גרועה, להימנע מעצימות גבוהה גם אם שאר המדדים תקינים. 60-80 = בינוני. מעל 80 = טוב.
- סוללת גוף (0-100): מתחת ל-30 בבוקר = רזרבות אנרגיה נמוכות, אימון קל/מנוחה בלבד. 30-60 = בינוני, אימון קל-בינוני. מעל 60 = אור ירוק לאימון איכות.
- תחושה subjective (1-10): הכי פחות "טכני" אבל לרוב הכי אמין - מתחת ל-4 זה דגל אדום גם אם כל שאר המדדים תקינים; תמיד תן למשקל למדד הזה.
- כלל שילוב: אם 2 מדדים או יותר "באדום" (RHR גבוה, HRV נמוך, שינה<60, סוללה<30, תחושה<4) - הפוך את אימון היום לקל/מנוחה ותסביר בקצרה למה, גם אם התוכנית המקורית תכננה סף/VO2max. אם רק מדד אחד חורג - אפשר להקל (למשל לקצר/להוריד חזרות) בלי לבטל לגמרי.
- מגמה על פני כמה ימים חשובה יותר מנקודת נתון בודדת: ירידה עקבית בתחושה/שינה או עלייה עקבית ב-RHR לאורך 3+ ימים = אות אזהרה לאובר-ריצינג גם אם אף יום בודד לא קיצוני - זה מה ש"מגמת תחושה" בהודעת המערכת אמורה לתפוס.
"""

# הפורמט המדויק שהאפליקציה מצפה לקבל כשהיא מבקשת "תוכנית JSON" -
# בלי הגדרה מפורשת של השדות, המודל נוטה להחזיר JSON חלקי/לא תקין,
# ואז כל הימים נופלים לברירת המחדל "מנוחה" בלוח (התצוגה לא מוצאת title).
WEEKLY_PLAN_JSON_FORMAT = f"""
כשאתה בונה או מעדכן תוכנית שבועית, החזר בלוק קוד יחיד בפורמט הבא (ואל תוסיף שום טקסט אחר בתוך הבלוק):

```json
{{
  "יום ראשון": {{"title": "...", "goal": "...", "steps": ["..."], "paces": "..."}},
  "יום שני": {{"title": "...", "goal": "...", "steps": ["..."], "paces": "..."}},
  "יום שלישי": {{"title": "...", "goal": "...", "steps": ["..."], "paces": "..."}},
  "יום רביעי": {{"title": "...", "goal": "...", "steps": ["..."], "paces": "..."}},
  "יום חמישי": {{"title": "...", "goal": "...", "steps": ["..."], "paces": "..."}},
  "יום שישי": {{"title": "...", "goal": "...", "steps": ["..."], "paces": "..."}},
  "יום שבת": {{"title": "...", "goal": "...", "steps": ["..."], "paces": "..."}}
}}
```

כללי חובה לפורמט הזה:
1. המפתחות (keys) חייבים להיות בדיוק שבעת השמות האלו, באיות זהה: {hebrew_days}. אסור להחסיר יום.
2. תכנן שבוע אימונים אמיתי לפי פרוטוקול העבודה - בדרך כלל 5-6 ימי אימון ורק 1-2 ימי מנוחה. אסור לסמן את כל השבוע (או רובו) כ"מנוחה" אלא אם המשתמש בשחיקה ברורה לפי הנתונים - ואז תסביר בטקסט למה.
3. עבור כל יום שאינו מנוחה, ה-title חייב לציין את סוג האימון בפירוש (למשל "ריצה קלה", "אינטרוולים", "ריצת סף", "כוח") - זה מה שקובע את האייקון והצבע בלוח.
4. steps חייב לכלול מרחק/זמן/חזרות קונקרטיים לכל שלב (למשל "2 ק\"מ חימום קל", "5x800 מ' בקצב סף עם 2 דק' מנוחה בין חזרות", "20 דקות שחרור"). אל תכתוב שלבים גנריים בלי מספרים.
5. לכל יום איכות (סף/VO2max/אינטרוולים/עליות/פארטלק) פרק את steps לשלבים נפרדים ומפורשים: חימום (10-20 דק' קל, כולל אם רלוונטי 3-4 סטריידס של 15-20 שנ' לפני הסט העיקרי), הסט העיקרי (מרחק/זמן/חזרות/מנוחה בין חזרות כמו בסעיף 4), וקירור (10-15 דק' ריצה קלה). אל תכתוב "אינטרוולים" כשלב יחיד בלי חימום/קירור נפרדים.
6. ביום כוח, steps חייב לפרט תרגילים קונקרטיים עם סטים/חזרות (למשל "סקוואט 3x12", "לאנג' הליכה 3x10 לכל רגל", "פלאנק 3x40 שנ'") לפי פרוטוקול העבודה - לא "אימון כוח כללי".
7. paces חייב לכלול קצב או טווח דופק קונקרטי (למשל "5:30-5:45 דק/ק\"מ" או "דופק 140-150") ולא "לפי תחושה" - אלא אם זה אכן אימון שחרור חופשי לגמרי. כשיש למתאמן אזורי דופק מחושבים (LTHR/Z1-Z5), התאם את הטווח לאזור הרלוונטי לסוג האימון של אותו יום.
8. יום מנוחה אמיתי - עדיין תחזיר עבורו אובייקט עם title: "מנוחה" (לא תשמיט את היום).
9. אסור לעטוף את שבעת הימים בתוך מפתח נוסף (כמו "weekly_plan" או כל מפתח אחר) - האובייקט ברמה העליונה בתוך הבלוק חייב להיות ישירות שבעת הימים כמפתחות, ושום דבר אחר (לא weekly_volume_target_km, לא coaching_notes וכו').
10. אסור להשתמש בשמות ימים באנגלית (Sunday/Monday/...) ואסור להוסיף תאריך למפתח (כמו "Friday_2026-07-10") - רק שמות הימים בעברית, באיות זהה בדיוק לרשימה שבסעיף 1.
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

def get_latest_garmin_summary():
    # last_run_summary נשמר רק על השורה של אותו עדכון בוקר, ולא בהכרח באחרונה
    # שבה log.get("created_at") הוא היום - לכן סורקים כמה שורות אחרונות ומוצאים
    # את הראשונה עם סיכום ריצות בפועל, בלי קשר לתאריך עדכון הבוקר האחרון.
    try:
        res = (supabase.table("coach_logs")
               .select("last_run_summary, created_at")
               .eq("user_id", st.session_state.user.id)
               .order("id", desc=True)
               .limit(10)
               .execute())
        for row in (res.data or []):
            if row.get("last_run_summary"):
                return row
    except Exception:
        pass
    return None

def build_daily_status():
    # תמיד נשלף מחדש מה-DB (ולא מ-session_state המקומי) כדי שריענון דף / התנתקות מחדש
    # לא "ישכחו" עדכון בוקר שכבר בוצע היום.
    load_latest_coach_log(st.session_state.user.id)
    log = st.session_state.latest_log
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    run_row = get_latest_garmin_summary()
    run_part = ""
    if run_row:
        run_date = str(run_row.get("created_at", ""))[:10]
        run_signature = f"{run_row.get('created_at', '')}|{str(run_row.get('last_run_summary', ''))[:80]}"
        is_repeat_pull = st.session_state.get("last_seen_run_signature") == run_signature
        st.session_state["last_seen_run_signature"] = run_signature
        try:
            days_since_run = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(run_date)).days
        except Exception:
            days_since_run = None
        if days_since_run is None:
            recency_note = ""
        elif days_since_run <= 0:
            recency_note = "(היום - שים לב: יש לך רק את התאריך, לא את השעה המדויקת. אל תניח ואל תכתוב שהאימון \"הסתיים ממש עכשיו\" או \"לפני זמן קצר\" - ייתכן שהוא התקיים מוקדם יותר היום)"
        elif days_since_run == 1:
            recency_note = "(אתמול)"
        else:
            recency_note = f"(שים לב: לפני {days_since_run} ימים - זה לא עדכני!)"
        repeat_note = " [שים לב: זהו בדיוק אותו אימון שכבר נמסר לך קודם בשיחה הזו - אין אימון חדש מאז, אל תתייחס אליו כאילו קרה עכשיו ואל תברך שוב על סיומו כאילו הוא חדש]" if is_repeat_pull else ""
        run_part = f" מידע ריצה אחרון שנרשם בתאריך {run_date} {recency_note}{repeat_note} (היום הוא {today}): {run_row['last_run_summary']}"

    if not log or str(log.get("created_at", ""))[:10] != today:
        return f"תאריך היום: {today}. המשתמש עדיין לא מילא עדכון בוקר היום ({today}).{run_part}"
    fields = [("דופק מנוחה", "rhr"), ("HRV", "hrv"), ("שינה", "sleep_score"),
              ("סוללת גוף", "body_battery"), ("תחושה", "feeling")]
    parts = [f"{label}: {log.get(key) if log.get(key) is not None else 'לא סופק'}" for label, key in fields]
    return f"תאריך היום: {today}. עדכון בוקר בוצע היום ({today}). " + ", ".join(parts) + run_part

class _CoachResponse:
    """עטיפה פשוטה כדי שגם הודעות שגיאה יתנהגו כמו תשובת AI רגילה (עם .text)."""
    def __init__(self, text):
        self.text = text

def coach_send(message_text):
    full_message = f"[מצב יומי: {build_daily_status()}]\n{message_text}"
    try:
        return st.session_state.chat_session.send_message(full_message)
    except ClientError as e:
        if getattr(e, "code", None) != 429:
            raise
        return _CoachResponse(
            "Coach Leo 😅 חרגת מהמכסה החינמית של גוגל ל-Gemini. נסה שוב בעוד דקה."
        )
    except Exception as e:
        return _CoachResponse(f"שגיאה בתקשורת עם המאמן: {e}")

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

def build_physio_zones_summary(user_id):
    # מחשבים בפייתון ולא סומכים על שהמודל "יזכור" לחשב נכון - מזריקים
    # אזורי דופק מוכנים לתוך הפרומפט, מבוססים על דופק הסף (LTHR) שנאסף בטאב "מבדקים".
    try:
        res = supabase.table("profiles").select("physiology_data").eq("id", user_id).execute()
        raw = res.data[0].get("physiology_data") if res.data else None
        physio = json.loads(raw or "{}")
    except Exception:
        physio = {}

    max_hr = physio.get("max_hr")
    lthr = physio.get("lthr")
    cooper = physio.get("cooper")
    estimated = False

    if not lthr and max_hr:
        # אין מבחן סף בפועל - הערכה גסה מקובלת לרץ מאומן: LTHR ≈ 88% מהדופק המקסימלי.
        lthr = round(max_hr * 0.88)
        estimated = True

    if not lthr:
        return ("אין נתוני דופק (מקסימלי/סף) מהמבדקים - אם רלוונטי לשאלה, בקש מהמשתמש "
                "למלא אותם בטאב 'מבדקים' כדי לתת אזורי דופק מדויקים; עד אז תן טווחי עצימות "
                "כלליים (לפי תחושה/קצב שיחה) בלי להמציא מספרי דופק.")

    zones = [
        ("Z1 התאוששות", 0, round(lthr * 0.85)),
        ("Z2 בסיס אירובי", round(lthr * 0.85), round(lthr * 0.89)),
        ("Z3 טמפו (להשתמש בזהירות)", round(lthr * 0.90), round(lthr * 0.94)),
        ("Z4 סף", round(lthr * 0.95), round(lthr * 0.99)),
        ("Z5 VO2max/אינטרוולים", round(lthr * 1.03), round(lthr * 1.15)),
    ]
    zones_text = ", ".join(f"{name}: {lo}-{hi} פעימות/דק'" for name, lo, hi in zones)

    vo2max_line = ""
    if cooper:
        vo2max = (cooper * 1000 - 504.9) / 44.73
        vo2max_line = f" VO2max משוער ממבחן קופר ({cooper} ק\"מ ב-12 דק'): כ-{vo2max:.1f} מ\"ל/ק\"ג/דקה."

    lthr_note = " (מוערך מדופק מקסימלי, לא ממבחן סף בפועל)" if estimated else ""
    return f"דופק סף (LTHR){lthr_note}: {lthr}. אזורי אימון: {zones_text}.{vo2max_line}"

def fetch_recent_garmin_activities(garmin_email, garmin_password):
    if not garmin_email or not garmin_password:
        return "לא חובר לגרמין."
    max_retries = 3
    for attempt in range(max_retries):
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
                    hr = act.get('averageHR', 'N/A')
                    history.append(f"{name}: {dist:.2f} ק\"מ ב-{dur:.1f} דק | דופק ממוצע: {hr}")
                return "\n".join(history)
            return "לא נמצאו אימונים לאחרונה."
        except GarminConnectTooManyRequestsError:
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            return "גרמין חסם זמנית בקשות מעומס (429). נסה שוב בעוד כמה דקות."
        except Exception as e:
            return f"שגיאה: {e}"


# לפעמים המודל לא מציית לפורמט המבוקש בול - עוטף את הימים במפתח "weekly_plan" נוסף,
# או משתמש בשמות ימים באנגלית (לפעמים עם תאריך בסוף, כמו "Friday_2026-07-10").
# הלוח מציג "מנוחה" לכל יום שהמפתח שלו לא תואם בדיוק ל-hebrew_days, אז זה חייב
# להיות עמיד ולא לסמוך אך ורק על ציות המודל להנחיה.
_ENGLISH_DAY_TO_HEBREW = {
    "sunday": "יום ראשון", "monday": "יום שני", "tuesday": "יום שלישי",
    "wednesday": "יום רביעי", "thursday": "יום חמישי", "friday": "יום שישי", "saturday": "יום שבת",
}

def _normalize_weekly_plan(raw_plan):
    if not isinstance(raw_plan, dict):
        return {}
    # עטיפה כמו {"weekly_plan": {...הימים...}, "weekly_volume_target_km": ...} - נפרוס אותה
    if isinstance(raw_plan.get("weekly_plan"), dict):
        raw_plan = raw_plan["weekly_plan"]

    normalized = {}
    for key, val in raw_plan.items():
        if not isinstance(val, dict):
            continue
        if key in hebrew_days:
            normalized[key] = val
            continue
        base = re.split(r"[_ ]", key, maxsplit=1)[0].strip().lower()
        hebrew_key = _ENGLISH_DAY_TO_HEBREW.get(base)
        if hebrew_key:
            normalized[hebrew_key] = val
    return normalized

# פונקציה שמחלצת JSON מהתשובה של ה-AI ומעדכנת את הלוח
def process_ai_response_for_plan(response_text):
    # regex סלחני יותר לגבי רווחים/שורות ריקות סביב הגדר - כדי שלא ניפול על
    # "כמעט תואם" ונתעלם משקט מתוכנית שלמה שהמודל כן החזיר.
    json_match = re.search(r'```json\s*(.*?)```', response_text, re.DOTALL | re.IGNORECASE)
    if json_match:
        try:
            new_plan = _normalize_weekly_plan(json.loads(json_match.group(1).strip()))
            if not new_plan:
                st.warning("לא הצלחתי לזהות ימי אימון בתוכנית שהמאמן החזיר - נסה לבקש תוכנית שוב.")
                return response_text
            missing_days = [d for d in hebrew_days if d not in new_plan]
            if missing_days:
                st.warning(f"התוכנית שהמאמן החזיר חסרה ימים: {', '.join(missing_days)}. הימים החסרים יוצגו כמנוחה.")
            user_prefs = json.loads(st.session_state.profile_data.get("workout_preferences", "{}"))
            user_prefs["weekly_plan"] = new_plan
            supabase.table("profiles").update({"workout_preferences": json.dumps(user_prefs)}).eq("id", st.session_state.user.id).execute()
            st.session_state.profile_data["workout_preferences"] = json.dumps(user_prefs)

            clean_text = re.sub(r'```json\s*.*?```', '', response_text, flags=re.DOTALL | re.IGNORECASE).strip()
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
@st.cache_resource
def _get_genai_client():
    return genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
def init_chat_session():
    # חישוב מגמה מהירה מתוך ה-coach_logs (ה-7 האחרונים)
    logs = supabase.table("coach_logs").select("*").eq("user_id", st.session_state.user.id).order("id", desc=True).limit(7).execute().data
    trend_msg = "אין מספיק נתונים לניתוח מגמה."
    if len(logs) >= 3:
        avg_feeling = sum(l['feeling'] for l in logs) / len(logs)
        trend_msg = f"מגמת תחושה ב-7 ימים אחרונים: {avg_feeling:.1f}/10."

    # כאן נכנס הניתוח החכם
    run_history_summary = build_run_history_summary()
    physio_zones_summary = build_physio_zones_summary(st.session_state.user.id)
    system_instruction = f"""
    אתה מאמן ריצה עילית בעל ניסיון של 20 שנה, בקיא בפיזיולוגיה של אימון סיבולת.
    פרוטוקול עבודה: {TRAINING_PROTOCOL}
    מאגר ידע מקצועי: {KNOWLEDGE_BASE}
    פרוטוקול פענוח נתוני בוקר (readiness): {READINESS_PROTOCOL}
    פורמט תוכנית שבועית: {WEEKLY_PLAN_JSON_FORMAT}
    מגמות מתאמן: {trend_msg}
    היסטוריית ריצות: {run_history_summary}
    נתוני פיזיולוגיה ואזורי אימון של המתאמן: {physio_zones_summary}

    חוקי עבודה:
    1. לפני כל המלצה, בצע 'ניתוח מצב': השווה את נתוני עדכון הבוקר של היום למגמה (Trend) ולפרוטוקול פענוח נתוני הבוקר, ולא רק תיאור מילולי כללי.
    2. כשאתה בונה אימון עצימות (סף/VO2max), ציין קצב/דופק קונקרטי מתוך אזורי האימון של המתאמן (Z2/Z4/Z5 וכו') ולא רק "בעצימות גבוהה". אם אין נתוני דופק - בקש מהמשתמש למלא מבדקים, ותן טווח לפי תחושה בינתיים.
    3. אם אתה מזהה סימני שחיקה/אי-התאוששות לפי פרוטוקול פענוח נתוני הבוקר, תהיה קשוח - הפוך אימוני עצימות לקלים/מנוחה, ותסביר בקצרה איזה מדד/מדדים הובילו להחלטה.
    4. תמיד נמק את ה-JSON שאתה בונה לפי חוקי הברזל.
    5. כברירת מחדל ענה בקצרה ותכל'ס - כמה משפטים ישירים, בלי הרחבות מיותרות (למעט כשאתה בונה תוכנית אימונים מפורטת).
    6. אם המשתמש מבקש ממך מפורשות אורך תשובה אחר (למשל "תענה לי קצר יותר" או "תרחיב בבקשה") - זכור את ההעדפה הזו לכל אורך השיחה ופעל לפיה, עד שתקבל הנחיה חדשה.
    7. כל הודעה שתקבל ממני תיפתח בתגית "מצב יומי" עם התאריך הנוכחי ועדכון הבוקר של אותו תאריך בלבד - זה המקור היחיד והעדכני לנתוני "היום". אם היא אומרת שלא מולא עדכון בוקר היום, זה נכון גם אם בהודעות קודמות בשיחה (אולי מיום אחר) הופיעו נתוני בוקר - אל תשתמש בהם כאילו הם של היום, ואל תניח שהיום זהה לתאריך של ההודעה הקודמת. במקרה כזה, תגיד למשתמש בפירוש שהוא צריך למלא עדכון בוקר חדש להיום לפני שתוכל לתת ניתוח מבוסס-נתונים (אפשר עדיין לשוחח כללית, אבל לא "לזייף" שיש נתוני בוקר).
    """
    # מוצמד לגרסה יציבה (לא "-latest") - כדי לא ליפול על מודל preview חדש
    # עם מכסת חינם זעירה (ראינו 5 בקשות/דקה בלבד על gemini-flash-latest)
    client = _get_genai_client()
    st.session_state.chat_session = client.chats.create(model='gemini-2.5-flash', config=types.GenerateContentConfig(system_instruction=system_instruction))

# --- כניסה ---
if st.session_state.user is None:
    st.title("🏃‍♂️ AI Running Coach")
    tab1, tab2 = st.tabs(["התחברות", "הרשמה"])

    with tab1:
        email_in = st.text_input("אימייל", key="login_email")
        password_in = st.text_input("סיסמה", type="password", key="login_pass")
        if st.button("התחבר", key="btn_login", type="primary"):
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

        if st.form_submit_button("שגר נתונים 🔄", type="primary"):
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
    if st.button("🤖 בקש מהמאמן תוכנית חדשה לשבוע הקרוב", type="primary"):
        with st.spinner("המאמן מנתח שיאים וקצבים ובונה תוכנית..."):
            resp = coach_send(
                "בנה לי תוכנית מפורטת לשבוע הקרוב מבוססת על המבדקים שלי - שבעת הימים, "
                "עם ימי אימון אמיתיים (לא רק מנוחה) לפי הפורמט שהוגדר לך. "
                "החזר את בלוק ה-JSON לפי הפורמט המדויק, עם title/goal/steps/paces קונקרטיים לכל יום."
            )
            process_ai_response_for_plan(resp.text)
            st.rerun()

    weekly_plan = user_prefs.get("weekly_plan", {})
    if not isinstance(weekly_plan, dict): weekly_plan = {}

    # python weekday(): Monday=0..Sunday=6, ואילו hebrew_days מתחיל ביום ראשון -
    # ההזחה הזו ממירה בין השניים כדי לדעת איזה יום בשבוע הוא "היום".
    today_hebrew_day = hebrew_days[(datetime.date.today().weekday() + 1) % 7]

    for day_name in hebrew_days:
        day_ai_plan = weekly_plan.get(day_name, {})

        # חילוץ כותרת
        title = day_ai_plan.get("title", "מנוחה") if isinstance(day_ai_plan, dict) else "מנוחה"

        card_class, icon = "card-rest", "🛑"
        if "ריצה" in title or "אינטרוולים" in title: card_class, icon = "card-run", "🏃‍♂️"
        elif "כוח" in title or "אופניים" in title: card_class, icon = "card-cross", "💪"

        is_today = day_name == today_hebrew_day
        today_class = " card-today" if is_today else ""
        today_badge = '<span class="today-badge">היום</span> ' if is_today else ""

        st.markdown(f"""
        <div class="calendar-card {card_class}{today_class}">
            <div class="card-badge">{icon}</div>
            <div><div class="day-title">{today_badge}{html.escape(day_name)}</div><div class="workout-type">{html.escape(title)}</div></div>
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
        if st.form_submit_button("שמור שיאים", type="primary"):
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

        if st.form_submit_button("שמור פרופיל", type="primary"):
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
    st.subheader("🏃‍♂️ 5 האימונים האחרונים")
    recent_runs = (supabase.table("run_history").select("*")
                   .eq("user_id", st.session_state.user.id)
                   .order("activity_date", desc=True).limit(5).execute().data) or []

    if not recent_runs:
        st.caption("עדיין אין אימונים רשומים - ייבא קובץ CSV מגרמין למטה כדי להתחיל.")
    else:
        runs_df = pd.DataFrame(recent_runs).set_index("id")
        runs_df["activity_date"] = pd.to_datetime(runs_df["activity_date"]).dt.date
        runs_df["duration_min"] = (runs_df["duration_sec"] / 60).round(1)
        display_cols = ["activity_date", "activity_type", "title", "distance_km",
                         "duration_min", "avg_hr", "max_hr", "avg_pace_sec_per_km", "elevation_gain_m"]
        runs_df = runs_df[display_cols]

        edited_runs_df = st.data_editor(
            runs_df,
            column_config={
                "activity_date": st.column_config.DateColumn("תאריך"),
                "activity_type": st.column_config.TextColumn("סוג פעילות"),
                "title": st.column_config.TextColumn("כותרת"),
                "distance_km": st.column_config.NumberColumn("מרחק (ק\"מ)", min_value=0.0, step=0.1),
                "duration_min": st.column_config.NumberColumn("משך (דקות)", min_value=0.0, step=1.0),
                "avg_hr": st.column_config.NumberColumn("דופק ממוצע", min_value=0, step=1),
                "max_hr": st.column_config.NumberColumn("דופק מקסימלי", min_value=0, step=1),
                "avg_pace_sec_per_km": st.column_config.NumberColumn("קצב (שנ'/ק\"מ)", min_value=0, step=1),
                "elevation_gain_m": st.column_config.NumberColumn("עלייה מצטברת (מ')", min_value=0, step=1),
            },
            num_rows="fixed",
            key="recent_runs_editor",
        )

        if st.button("💾 שמור שינויים באימונים"):
            changed = 0
            for run_id, row in edited_runs_df.iterrows():
                if not row.equals(runs_df.loc[run_id]):
                    supabase.table("run_history").update({
                        "activity_date": row["activity_date"].isoformat(),
                        "activity_type": row["activity_type"],
                        "title": row["title"],
                        "distance_km": row["distance_km"],
                        "duration_sec": int(row["duration_min"] * 60) if pd.notna(row["duration_min"]) else None,
                        "avg_hr": int(row["avg_hr"]) if pd.notna(row["avg_hr"]) else None,
                        "max_hr": int(row["max_hr"]) if pd.notna(row["max_hr"]) else None,
                        "avg_pace_sec_per_km": row["avg_pace_sec_per_km"],
                        "elevation_gain_m": row["elevation_gain_m"],
                    }).eq("id", int(run_id)).execute()
                    changed += 1
            if changed:
                st.success(f"עודכנו {changed} אימונים!")
                st.rerun()
            else:
                st.info("לא זוהו שינויים.")

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
