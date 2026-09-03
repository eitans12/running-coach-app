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
