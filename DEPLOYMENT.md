# Assess Pulse — Deployment & Local Development (Hybrid Supabase Stack)

Architecture (Option C, hybrid):

- HR admin UI talks to Supabase directly via `supabase-js`; Row Level Security
  (RLS) enforces multi-tenant isolation by `corporate_id`.
- A thin FastAPI service handles the candidate access-code flow, scoring, and PDF
  report generation using the `service_role` key (which bypasses RLS by design,
  so it enforces `corporate_id` in code).

```
frontend (React/Vite) ──supabase-js + HR JWT──► Supabase (Auth, Postgres+RLS, Storage)
        │                                             ▲
        └── candidate flow / report download ──► FastAPI service (service_role)
```

## Prerequisites

- Docker (for the local Supabase stack)
- Supabase CLI (`supabase`)
- Python 3.12, Node 20+

## Local development

1. Start the local Supabase stack and apply all migrations:
   ```bash
   supabase start
   supabase db reset      # applies supabase/migrations + enables the auth hook
   ```
   **Windows / Docker Desktop:** a plain `supabase db reset` often fails with
   `failed to connect to postgres ... Connection timed out`. The CLI tries TLS
   against local Postgres; the Docker host proxy can take several seconds to
   return the first byte, and the connect attempt then times out. Disable SSL
   for the local reset (local Postgres does not use TLS):

   ```powershell
   $env:PGSSLMODE = "disable"
   supabase db reset
   ```

   `supabase start` prints the API URL, anon key, service_role key, and JWT
   secret. The custom access token hook is enabled in `supabase/config.toml`.

2. Backend (thin FastAPI service):
   ```bash
   cd backend
   cp .env.example .env    # fill in SUPABASE_* values from `supabase start`
   pip install -r requirements.txt
   python -m uvicorn app.main:app --reload --port 8000
   ```
   Key vars: `DATABASE_URL` (Supabase Postgres, port 54322 locally),
   `SUPABASE_JWT_SECRET` (verifies HR tokens), `SUPABASE_SERVICE_ROLE_KEY`
   (reports/storage), `SECRET_KEY` (signs candidate tokens).

3. Frontend:
   ```bash
   cd frontend
   cp .env.example .env.local   # VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
   npm install --legacy-peer-deps
   npm run dev
   ```

4. Create an HR user and map them to a corporate (so their JWT carries
   `corporate_id`). Locally you can do this in the SQL editor / psql:
   ```sql
   -- 1. Create the auth user (or use the Studio Auth UI / supabase CLI).
   --    Example via Studio: Authentication > Add user (email + password).
   -- 2. Create a corporate and link the user:
   insert into public.corporates (name, slug) values ('Acme', 'acme')
     returning id;  -- note the id

   insert into public.hr_users (user_id, corporate_id, full_name, role)
   values ('<auth-user-id>', '<corporate-id>', 'HR Admin', 'admin');
   ```
   The corporate_id lands in `app_metadata` on the user's next token issuance
   (sign in again if already signed in).

## Testing

- Backend unit tests: `cd backend && python -m pytest tests/ -v`
- Frontend: `cd frontend && npm run lint && npm run build`
- Migrations + RLS isolation (no Docker needed, uses a Postgres shim):
  ```bash
  PGHOST=127.0.0.1 PGUSER=postgres PGPASSWORD=postgres bash scripts/verify_rls.sh
  ```
- Schema drift check (run after pulling new migrations). Exits 1 and prints the
  missing columns if the database behind `DATABASE_URL` lags the SQLAlchemy models;
  fix with `supabase migration up --local`:
  ```bash
  python scripts/check_schema_drift.py
  ```
- API E2E loop (stack must be running):
  ```bash
  # from repo root, backend venv active
  python scripts/e2e_candidate_loop.py
  ```
- Full RLS suite against the real stack: `supabase test db` (add pgTAP tests
  under `supabase/tests/`).

CI runs backend + frontend + RLS (`.github/workflows/ci.yml`).

## Gemini JD fit and technical item grading

- Set `GEMINI_API_KEY` in `backend/.env`. Use `GEMINI_MODEL=gemini-3.6-flash`
  (new keys cannot call `gemini-2.5-*`).
- Client: `google-genai` (`genai.Client(api_key=GEMINI_API_KEY)`).
- Free-tier 429s: `GEMINI_MAX_RETRIES` (default 3) with exponential backoff
  (`GEMINI_RETRY_BASE_SECONDS`). Custom technical items are graded **sequentially**
  with `GEMINI_INTER_REQUEST_SECONDS` between calls.
- Item scores land on `candidate_responses.response` (`ai_score`, `ai_evaluation`,
  `scorecard`) and are returned by `GET /api/v1/candidates/{id}/report-data`.
- Package-level JD fit still runs after the last test submit, and again on HR
  report download (cached by JD hash). Soft timeout: `GEMINI_TIMEOUT_SECONDS`
  per attempt.

## Reports (PDF vs HTML)

- Linux/Docker images install WeasyPrint system libs (`backend/Dockerfile`).
- On Windows without Pango/Cairo, downloads fall back to HTML. The tracker
  surfaces this via `X-Report-Type: HTML`.

## Public tracker & support

- Each package has a `track_secret`. Share `/public/track/{secret}` (no auth).
- `POST /api/v1/support/submit` stores tickets; HR of that corporate can SELECT.
- T-24h nudges: schedule `POST /api/v1/admin/jobs/nudge-due` with an HR JWT
  (Task Scheduler / cron). Uses `NUDGE_AFTER_HOURS` (default 24).

## Cloud deployment

1. Create a Supabase project (dashboard), then link and push the schema:
   ```bash
   supabase link --project-ref <your-project-ref>
   supabase db push
   ```
2. Enable the custom access token hook (Dashboard: Authentication > Hooks, or via
   `supabase config push`) pointing at `public.custom_access_token_hook`.
3. Deploy the FastAPI service (any container host). Set env:
   - `DATABASE_URL` = the project's Postgres connection (use the pooler)
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`
   - `SECRET_KEY` (strong random), `DEBUG=false`, `CORS_ORIGINS` = your frontend origin(s)
4. Deploy the frontend (static host). Set build env:
   - `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
   - `VITE_API_URL` = the deployed FastAPI base URL
5. Onboard HR users: create the auth user, then insert their `hr_users` row.

## Security notes

- `service_role` key and `SUPABASE_JWT_SECRET` are server-side only. Never ship
  them to the browser (the frontend uses only the anon/publishable key).
- Tenancy is enforced by RLS on the supabase-js path and by explicit
  `corporate_id` checks on the FastAPI/service_role path.
- **Fail-closed boot:** with `DEBUG=false`, FastAPI refuses to start if
  `SECRET_KEY` / `SUPABASE_JWT_SECRET` are still the `.env.example` defaults
  or shorter than 32 characters, or if `CORS_ORIGINS` is empty / localhost-only.
  (Local/CI keep `DEBUG=true` — the Settings default — so example secrets work.)
- **Hosted Supabase:** after `supabase db push`, confirm Dashboard → Advisors
  shows RLS enabled on `corporates`, `packages`, `assessments`, `candidates`,
  `candidate_progress`, and `candidate_responses`. Enable Auth leaked-password
  protection (HaveIBeenPwned) in the Auth settings.
- **Invite-only enrollment:** package access codes do **not** auto-register
  strangers. Pre-invite candidates (or set `packages.allow_open_enrollment = true`
  intentionally). Invite codes still match email.
- **Rate limits (in-process):** candidate login ≈ 10 / 15 min / IP; public track,
  blind review, support, and chat ≈ 60 / min / IP. Multi-instance deploys need a
  shared store (Redis) or limits multiply by replica count.
- **Psychometric isolation:** HR RLS may SELECT technical `candidate_responses`
  only; psychometric answers stay ops-only. Candidate APIs strip answer-key
  aliases including `correct_answer_or_rubric`.
- Security headers: FastAPI sets `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, and HSTS on HTTPS. The Vite app
  ships a CSP meta tag (tighten `connect-src` for production API hosts).

## Pre-launch checklist (shipping)

- [ ] `DEBUG=false`, strong `SECRET_KEY`, hosted `SUPABASE_JWT_SECRET`, production `CORS_ORIGINS`
- [ ] Migrations applied (`supabase db push`), including psychometric response RLS
- [ ] `pip-audit` / `npm audit` clean of reachable critical/high findings
- [ ] Health check `GET /health` returns 200 behind the load balancer
- [ ] Rollback: previous container image + prior migration down path documented
- [ ] Structured JSON logs flowing (request_id on responses via `X-Request-Id`)
- [ ] Confirm package open-enrollment flags match product intent per tenant
