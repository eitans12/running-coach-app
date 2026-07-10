---
name: running-coach
description: Launch and smoke-test the AI Running Coach Streamlit app (app.py) in this repo.
---

# Running Coach — launch guide

This is a Streamlit app: Hebrew-language AI running coach backed by Supabase
(auth + data), Gemini (chat coach), and optional Garmin Connect sync.

## Launch

The `streamlit` binary is often not on `PATH` in this environment — use the
module form instead:

```bash
nohup python3 -m streamlit run app.py --server.headless true > /tmp/streamlit.log 2>&1 &
```

Wait for the port instead of a fixed sleep:

```bash
timeout 30 bash -c 'until curl -sf http://localhost:8501/_stcore/health >/dev/null; do sleep 1; done'
```

Stop with `pkill -f "streamlit run app.py"`.

## Required secrets

`.streamlit/secrets.toml` (gitignored, not in repo) must define:

- `SUPABASE_URL`, `SUPABASE_KEY` — project is `ai-running-coach`
  (`xkfshaidsfzgroybzmtw`), reachable via the Supabase MCP connection if you
  need to inspect tables/policies.
- `GOOGLE_API_KEY` — Gemini API key for the coach chat. The model is pinned
  to `gemini-2.5-flash` in `app.py` (not a `-latest` alias) because preview
  aliases can carry a much smaller free-tier quota (observed: 5 req/min on
  `gemini-flash-latest` → `gemini-3.5-flash`, vs. the standard free quota on
  GA models).
- `garmin_email` / `garmin_password` are stored per-user in the `profiles`
  table via the app UI, not in secrets.

If secrets.toml is missing entirely, the app fails at import time
(`st.secrets[...]` raises) — check for the file before debugging further.

## Verifying it's actually running

`curl localhost:8501` only confirms the Streamlit JS shell loads — the
Python script (`app.py`) only executes once a browser opens a WebSocket
session against it. A green `/_stcore/health` plus no traceback in the log
after a minute is a reasonable signal; to actually drive the UI (login,
send a chat message, check the calendar tab) you need a real browser
(Playwright/`chromium-cli`) since this environment had neither installed at
last check — flag that gap if you need a full click-through verification.

## Known gotchas

- `streamlit run` (no `python3 -m`) fails with "command not found" — the
  package is installed but the console-script entrypoint isn't on `PATH`.
- The Gemini free tier is shared per Google account/project across *all*
  requests — hitting it shows as `google.api_core.exceptions.ResourceExhausted`
  in the server log. `coach_send()` in `app.py` catches this and shows a
  friendly Hebrew message instead of crashing the page.
- `run_history` (Garmin CSV import) and `coach_logs` / `profiles` tables
  already exist in Supabase with RLS scoped to `auth.uid() = user_id` — no
  migration needed for those.
