# ai-running-coach — אוטומציית סנכרון (Garmin → Supabase → Google Sheets)

הפייפליין:

```
Garmin  →  Supabase (מקור האמת)  →  Google Sheets (שכבת קריאה ל-Gemini Spark)  →  Skill running-coach
```

## הקבצים
| קובץ | לאן הוא הולך בריפו | מה הוא עושה |
|------|-------------------|-------------|
| `garmin_to_supabase.py` | שורש הריפו | מושך אימונים → `run_history` ומדדי התאוששות → `coach_logs` |
| `supabase_to_sheets.py` | שורש הריפו | משקף את שתי הטבלאות אל שני הגיליונות |
| `requirements-sync.txt` | שורש הריפו | תלויות Python |
| `sync.yml` | `.github/workflows/sync.yml` | מריץ הכול אוטומטית כל בוקר (03:00 UTC ≈ 06:00) |
| `calendar_to_supabase.py` | שורש הריפו | קורא מ-Google Calendar את התוכניות שספארק תכנן, ומכניס אותן ל-`planned_workouts` (status='pending') כדי ש-`push-workouts.yml` יעלה אותן לגרמין אוטומטית — בלי SQL ידני |

## סודות שצריך להזין ב-GitHub
`Settings → Secrets and variables → Actions → New repository secret`. הזן **אתה** — אני לא נוגע בסודות.

| שם הסוד | ערך |
|---------|-----|
| `SUPABASE_URL` | `https://xkfshaidsfzgroybzmtw.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | מ-Supabase: `Project Settings → API → service_role` (סוד!) |
| `APP_USER_ID` | `a6c0130e-1214-474f-9377-8a3594cdea43` |
| `GARMIN_EMAIL` | האימייל של חשבון הגרמין שלך |
| `GARMIN_PASSWORD` | הסיסמה של חשבון הגרמין שלך |
| `GOOGLE_CREDENTIALS` | כל תוכן קובץ ה-JSON של service account (ראה למטה) |

## הרשאת Google לגיליונות (חד-פעמי)
1. ב-Google Cloud Console: צור **Service Account**, הפעל את **Google Sheets API**, והורד מפתח **JSON**.
2. העתק את כל תוכן ה-JSON לתוך הסוד `GOOGLE_CREDENTIALS`.
3. פתח כל אחד משני הגיליונות → **שיתוף** → הוסף את כתובת האימייל של ה-service account (מסתיימת ב-`@...iam.gserviceaccount.com`) כ**עורך**:
   - מאגר אימוני עבר ויומן ביצועים
   - מעקב התאוששות ומדדים יומיים

## גשר ספארק → Calendar → Supabase (חד-פעמי)
מטרה: ספארק (Gemini) מתכנן אימונים ורושם אותם ל-Google Calendar שלך; `calendar_to_supabase.py`
קורא משם ומכניס ל-`planned_workouts` לבד, כך שאף פעם לא צריך להריץ SQL ביד.

1. בהנחיות הקבועות של ספארק (gemini-spark-instructions / running-coach skill) כבר הוטמע כלל
   שמחייב אותו לכלול בתיאור (description) של כל אירוע אימון ביומן בלוק כזה:
   ```
   ###GARMIN_SPEC###
   {"name": "...", "sport": "running", "steps": [...]}
   ###END_SPEC###
   ```
2. **הפעלת Calendar API** ב-Google Cloud Console (באותו פרויקט של ה-service account הקיים):
   `APIs & Services → Library → Google Calendar API → Enable`.
3. **שיתוף היומן** עם ה-service account: ב-Google Calendar שלך (לא היומן של ה-service account) →
   הגדרות → היומן הרלוונטי (בדרך כלל "אירועים") → **שיתוף עם אנשים מסוימים** → הוסף את כתובת
   ה-service account (מסתיימת ב-`@...iam.gserviceaccount.com`, אותה כתובת שכבר שיתפת בגיליונות)
   עם הרשאת **"לראות את כל פרטי האירוע"** (See all event details) — קריאה בלבד, זה כל מה שצריך.
4. אם ספארק כותב ליומן אחר (לא היומן הראשי שלך) — צריך למצוא את ה-Calendar ID שלו (הגדרות היומן →
   גלול למטה ל"שילוב היומן" → Calendar ID) ולהוסיף אותו כסוד `CALENDAR_ID` ב-GitHub (ברירת המחדל
   היא `primary`, כלומר היומן הראשי של החשבון).
5. זהו — `calendar_to_supabase.py` רץ אוטומטית כצעד הראשון בכל הרצה של `push-workouts.yml`
   (07:00 ו-19:00, ועוד בכל פעם ש-cron-job.org מפעיל אותו), קורא 21 יום קדימה, ומכניס/מעדכן
   שורות `pending` — ומשאיר בלי לגעת אימונים שכבר הועלו לגרמין (status scheduled/uploaded).

## הפעלה ובדיקה
- ידני: לשונית **Actions → running-coach-sync → Run workflow**.
- אוטומטי: רץ מדי יום. לשינוי השעה — ערוך את שורת ה-`cron` ב-`sync.yml` (זמן UTC).

## הערות
- **דדופ:** אימונים נכתבים ב-upsert על `garmin_activity_id` (עמודה + אינדקס ייחודי שכבר נוספו ל-`run_history`), כך שהרצה חוזרת לא משכפלת.
- **אבטחה:** ב-GitHub Actions הסודות מוצפנים. **המלצה:** להסיר את `garmin_password` מטבלת `profiles` (שם הוא שמור כטקסט גלוי) ולהסתמך רק על סוד ה-Actions, או להצפין ב-Supabase Vault.
- **ביטול עמודת הדדופ (אם אי פעם תרצה):**
  ```sql
  DROP INDEX IF EXISTS public.run_history_garmin_activity_id_key;
  ALTER TABLE public.run_history DROP COLUMN IF EXISTS garmin_activity_id;
  ```
- **פריסת גיליונות:** אם Spark ינעל סדר עמודות אחר, עדכן את `WORKOUTS_HEADER_ROW` / `RECOVERY_HEADER_ROW` ואת בוני השורות בראש `supabase_to_sheets.py`.
