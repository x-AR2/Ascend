# GPA Planner — Backend

A real multi-user backend: signup/login with hashed passwords and JWT
sessions, SQLite storage scoped per user, and the exact same calculation
engine (`models.py`, `cgpa.py`) the CLI uses — wrapped as JSON endpoints
instead of terminal prompts.

## Running it locally

```
cd backend
pip install -r requirements.txt
python3 app.py
```

Serves on `http://localhost:5000`. First run creates `gpa.db` (SQLite)
automatically — nothing else to set up.

Run `python3 test_backend.py` to sanity-check the whole flow (signup,
login, auth rejection, course registration, marks entry with warnings,
report, what-if, dashboard, CGPA) end to end.

## Auth

- `POST /api/auth/signup` — `{username, email, password}` → `{token, user}`
- `POST /api/auth/login` — `{username_or_email, password}` → `{token, user}`
- `GET /api/auth/me` — requires `Authorization: Bearer <token>` → current user

Passwords are hashed with Werkzeug's scrypt-based hasher (salted,
never stored in plain text). Tokens are signed JWTs, valid 7 days.

**Before deploying**, set a real `JWT_SECRET_KEY` environment variable —
the code falls back to an insecure dev default, and if that's still
active in production, anyone can forge a valid token for any user.

## Everything else requires a token

Every other route needs `Authorization: Bearer <token>` and only ever
touches that user's own data — a course or semester belonging to someone
else returns 404, not their data.

- `POST/GET /api/semesters`, `GET /api/semesters/<id>`
- `POST /api/semesters/<id>/apply-uniform-target`
- `GET /api/semesters/<id>/dashboard`
- `POST /api/semesters/<id>/courses` — register a course
- `PATCH /api/courses/<id>/target`
- `GET /api/courses/<id>/report`
- `POST /api/courses/<id>/marks`
- `POST /api/courses/<id>/what-if`
- `GET/POST/DELETE /api/cgpa`

These mirror the CLI's menu options exactly — same math, same pace
warnings — just as JSON. See `app.py` for exact request/response shapes.

## Deploying

The Flask dev server (`python3 app.py`) is explicitly not meant for
production — it says so in its own startup log. For a real deployment:

1. **Host**: Render, Railway, or Fly.io all run a Python web service
   directly from this `backend/` folder. Start command:
   `gunicorn -w 2 -b 0.0.0.0:$PORT app:app` (gunicorn is in requirements.txt).
2. **Environment variables to set on the host**:
   - `JWT_SECRET_KEY` — a long random string (e.g. `python3 -c "import secrets; print(secrets.token_hex(32))"`)
   - `ALLOWED_ORIGIN` — your deployed frontend's exact URL (e.g.
     `https://your-app.netlify.app`), not `*`, once you're live.
3. **Database**: `gpa.db` is a single SQLite file. Render/Railway both
   support attaching a small persistent disk so it survives redeploys —
   without one, the database resets every deploy. Fine for early testing,
   not for real users. If you outgrow SQLite (lots of concurrent users),
   swapping to Postgres only touches `database.py` — nothing in `app.py`
   or the calculation engine changes.
4. **Frontend**: deployed separately on Netlify, calling this API over
   HTTPS with the token stored in the browser (e.g. `localStorage` or an
   in-memory store) and sent as `Authorization: Bearer <token>` on every
   request.

## A note on the local CLI

`../cli.py` (the terminal version) still works exactly as before, storing
everything in a local JSON file for single-user, offline use — that path
is untouched. This backend is the separate, multi-user path for once
you're ready to actually deploy and share it.
