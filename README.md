# Assess Pulse

Hybrid stack: **Supabase** (Auth, Postgres + RLS, Storage) + thin **FastAPI**
(candidate access-code flow, scoring, reports, Gemini JD fit).

> Source of truth for local run and deploy: **[DEPLOYMENT.md](DEPLOYMENT.md)**.
> Do not use the legacy SQLite `docker-compose.yml` path for day-to-day work.

## What it does

- HR builds assessment packages (MCQ / Likert / open-ended, max 6) via supabase-js + RLS
- Candidates enter with `?code=` (not Auth users); FastAPI issues candidate JWTs
- Autosave, completed-test lock, server-side MCQ scoring (keys never sent to the client)
- HR downloads reports; Gemini scores JD fit when a key is configured
- Public shareable tracker: `/public/track/{secret}`

## Quick start

```powershell
# 1. Supabase
supabase start
$env:PGSSLMODE = "disable"
supabase db reset

# 2. Backend
cd backend
cp .env.example .env   # fill SUPABASE_* + optional GEMINI_API_KEY
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

# 3. Frontend
cd ../frontend
cp .env.example .env.local
npm install --legacy-peer-deps
npm run dev            # http://127.0.0.1:5173
```

Create an HR user in Studio, insert `hr_users` + `corporates` (see DEPLOYMENT.md), then sign in again.

### Client portal test login

`hr_users.user_id` references `auth.users(id)` (there is no `public.users`), so a raw
`INSERT INTO hr_users` fails until a Supabase Auth user exists. Use the seed script instead —
it goes through the same services as the ops "Invite HR" action:

```powershell
cd backend
python -m scripts.seed_test_client --email you+hr@example.com --candidates 3
# staging (DEBUG=false): add --allow-non-debug
```

It idempotently creates a confirmed Auth user (no email sent), a `corporates` row, an
`hr_users` membership with role `hr`, a published package, and sample candidates
(Invited / In Progress / Completed). Then sign in at `/client/login`:

- **Use a separate email from your ops account.** One Auth user maps to one `hr_users` row;
  `admin`/`owner` accounts are rejected by the client portal and refused by the script.
- **OTP code:** locally it lands in Mailpit at http://127.0.0.1:54324; on staging it is sent
  to the real inbox by the project's mailer.
- The script prints the candidate link and PIN for the seeded package.

## Testing

```bash
cd backend && python -m pytest tests/ -v
cd frontend && npm run lint && npm run build
# RLS (needs Postgres): bash scripts/verify_rls.sh
# API loop (needs local stack + .env): python scripts/e2e_candidate_loop.py
```

## Architecture

```
frontend ──supabase-js + HR JWT──► Supabase (RLS by corporate_id)
   │
   └── candidate / reports / support / public track ──► FastAPI (service_role)
```

Schema lives in `supabase/migrations/`. FastAPI never owns DDL.

Production hardening notes: [DEPLOYMENT.md](DEPLOYMENT.md) (fail-closed secrets,
invite-only enrollment, rate limits), [CONSTRAINTS.md](CONSTRAINTS.md),
[docs/SECURITY_ADVISORS.md](docs/SECURITY_ADVISORS.md).
