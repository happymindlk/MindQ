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

2. Redis (durable ARQ job queue for scoring, Gemini, PDF prewarm, SES):
   ```bash
   REDIS_PASSWORD=<strong-random> docker compose up -d redis
   ```
   Redis requires a password and listens on `127.0.0.1` only. Set the same
   value in `backend/.env`: `REDIS_URL=redis://:<strong-random>@localhost:6379/0`
   (see `backend/.env.example`). You can also put `REDIS_PASSWORD=` in a
   repo-root `.env` (git-ignored) so `docker compose` picks it up.

3. Backend (thin FastAPI service + ARQ worker):
   ```bash
   cd backend
   cp .env.example .env    # fill in SUPABASE_* values from `supabase start`
   pip install -r requirements.txt
   python -m uvicorn app.main:app --reload --port 8000
   # Separate process — consumes durable jobs (do not skip in staging/prod):
   arq app.jobs.worker.WorkerSettings
   ```
   Key vars: `DATABASE_URL` (Supabase Postgres, port 54322 locally),
   `SUPABASE_JWT_SECRET` (verifies HR tokens), `SUPABASE_SERVICE_ROLE_KEY`
   (reports/storage), `SECRET_KEY` (signs candidate tokens), `REDIS_URL`.
   Without Redis in local/dev the API falls back to inline job execution so
   unit tests keep working; production refuses to boot if Redis is unreachable.

4. Frontend:
   ```bash
   cd frontend
   cp .env.example .env.local   # VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
   npm install --legacy-peer-deps
   npm run dev
   ```

5. Create an HR user and map them to a corporate (so their JWT carries
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

### Staging Multi-AZ topology (live — `ap-southeast-2` / Sydney)

High availability replaces the former single-instance Cloudflare Tunnel path.
Traffic reaches FastAPI through:

```
Client → Cloudflare (proxied DNS) → Lightsail Load Balancer → Nginx → Uvicorn
```

| Resource | Role |
|----------|------|
| `mindq-backend-staging` | Lightsail instance, **Availability Zone A** — FastAPI/Uvicorn behind Nginx |
| `mindq-backend-staging-2` | Lightsail instance, **Availability Zone B** — same stack as Zone A |
| `mindq-backend-lb` | Lightsail load balancer; health check **`GET /health/ready`** → HTTP 200 (Postgres `SELECT 1` + Redis `PING`, 1s each; 503 takes the node out of rotation). `GET /health` stays as a dependency-free liveness probe. |
| `api-qa.mindqtalent.com` | Cloudflare **proxied CNAME** → Lightsail LB DNS name (not a Tunnel) |
| Shared Redis | `REDIS_URL` over private VPC IP **`:6379`**, **password required** (`requirepass`); bound to the private IP only; Lightsail firewall allows only the backend nodes |

**Proxy hops:** set `TRUSTED_PROXY_HOPS=2` and prefer `CLIENT_IP_HEADER=CF-Connecting-IP`
so rate limiting keys on the real client IP (Cloudflare + Lightsail LB both append
to the forwarded chain). With `TRUSTED_PROXY_HOPS=0`, `X-Forwarded-For` is ignored.

**Shared Redis:** both nodes use the same `REDIS_URL` for cross-node
`RateLimiter` / `AuthFailureLimiter` budgets (and ARQ when the worker is enabled).
Without Redis, limits multiply by replica count.

**Background work caveat:** FastAPI `BackgroundTasks` (including some PDF / report
paths) remain **node-local**. Ungraceful termination of the instance that accepted
the request can drop in-flight work unless that job is backed by the durable ARQ
queue on Redis. Prefer ARQ for scoring and other long-running jobs in staging/prod.

**Connection pool math (Supavisor Transaction Mode, port `6543`):** every
process has its own bounded SQLAlchemy pool, sized by role (`app/database.py`):

| Process | Setting | Default | Max sockets |
|---|---|---|---|
| Each Uvicorn worker | `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` | 10 + 10 | 20 |
| Each ARQ worker (`arq ...`) | `DB_WORKER_POOL_SIZE` + `DB_WORKER_MAX_OVERFLOW` | 5 + 5 | 10 |

Total ≈ `nodes × WEB_CONCURRENCY × 20 + arq_workers × 10`. Current staging:
`2 × 2 × 20 + 1 × 10 = 90` pooler clients. Keep the total **at or below ~70% of
the Supavisor client limit** for your compute tier (Nano/Micro: 200 → ≤ 140).
The ARQ role is auto-detected from the `arq` command; set `DB_PROCESS_ROLE=worker`
if the worker is launched some other way. Each process logs
`db_engine_configured role=… pool_size=… max_overflow=…` at boot. Lightsail does
**not** auto-scale; provision nodes manually and re-check the formula.

1. Create a Supabase project (dashboard), then link and push the schema:
   ```bash
   supabase link --project-ref <your-project-ref>
   supabase db push
   ```
2. Enable the custom access token hook (Dashboard: Authentication > Hooks, or via
   `supabase config push`) pointing at `public.custom_access_token_hook`.
3. Deploy FastAPI on **both** Lightsail nodes (Nginx → Uvicorn) **and** a dedicated
   ARQ worker where durable jobs are required:
   `arq app.jobs.worker.WorkerSettings`. Attach both instances to `mindq-backend-lb`.
   Set the same env on every node:
   - `DATABASE_URL` = Supabase Supavisor **Transaction Mode** pooler on port
     **`6543`** (not session mode `5432`). Example:
     `postgresql+asyncpg://postgres.<project-ref>:<password>@aws-0-ap-southeast-2.pooler.supabase.com:6543/postgres`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`
   - `SECRET_KEY` (strong random), `DEBUG=false`, `CORS_ORIGINS` = your frontend origin(s)
   - `ENVIRONMENT` = `production` (prod) or `qa` / `staging`. `DEBUG` now
     defaults to **false**; with `DEBUG=false` and `ENVIRONMENT` left unset the
     API boots but logs an `unsafe_config_warning`.
   - `FRONTEND_URL` = the public app origin (e.g. `https://qa.app.mindqtalent.com`).
     Invite / OTP links use it. In production request `Origin`/`Referer`
     headers are never used for links; a missing value logs a boot warning.
   - `REDIS_URL=redis://:<redis-password>@<private-vpc-ip>:6379/0` (shared;
     firewall-restricted). The Redis host **must** run with
     `requirepass <redis-password>`, `bind <private-vpc-ip>` (never `0.0.0.0`
     or a public IP), `maxmemory <size>` and `maxmemory-policy noeviction`.
     ARQ deserializes job payloads with pickle, so unauthenticated Redis means
     remote code execution on the worker. The API logs a
     `redis_unauthenticated` warning at boot when `REDIS_URL` has no password.
     Rotation: set `requirepass` on Redis, update `REDIS_URL` on every node and
     the ARQ worker, then restart them (`CONFIG SET requirepass` applies
     immediately, so update the nodes right after).
   - `TRUSTED_PROXY_HOPS=2`, `CLIENT_IP_HEADER=CF-Connecting-IP`
   - `WEB_CONCURRENCY` (default **2** in `backend/Dockerfile`) — see pool math above
4. Deploy the frontend to Cloudflare Pages with root directory `frontend/`
   (build `npm run build`, output `dist`). Set env:
   - `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
     **MindQ project (active):** `https://djshmrkerssvpvcxqkqo.supabase.co`
     (note the `svpvc` segment — a typo like `svpc` yields `ERR_NAME_NOT_RESOLVED`).
     Copy the exact URL + anon key from Supabase → Project Settings → API, then
     **redeploy** Pages so Vite bakes the new values into the bundle.
   - Backend host must use the same `SUPABASE_URL` / service-role key for that project.
   - SES (backend): set `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
     `EMAIL_FROM`. While the account is in SES Sandbox, verify the From identity
     and every recipient (e.g. `ADMIN_NOTIFICATION_EMAIL`) under SES → Identities.
     Failures surface in API logs as `SES send FAILED` with a full traceback.
   - `VITE_API_URL` = `https://api-qa.mindqtalent.com` (Cloudflare proxied CNAME →
     Lightsail LB `mindq-backend-lb`). `frontend/.env.production` ships this default;
     a value set in the Pages dashboard overrides it. HTTP values are ignored in
     production builds, which then fall back to the same-origin `/api/*` proxy.
   - Any new API origin must also be added to `connect-src` (and `img-src` if it
     serves assets) in the `<meta>` CSP in `frontend/index.html`.
   - `frame-ancestors` / `X-Frame-Options` ship as real headers via
     `frontend/public/_headers` (browsers ignore `frame-ancestors` in `<meta>`).
   - The browser calls the API cross-origin, so backend `CORS_ORIGINS` must list
     every frontend origin, e.g. `https://mindq.pages.dev` plus any custom domain
     and preview URLs you test from.
   - Optional fallback: with `VITE_API_URL` empty, `frontend/functions/api/[[catchall]].js`
     proxies `/api/*` to `BACKEND_ORIGIN` (default `https://api-qa.mindqtalent.com`).
     Pages Functions cannot fetch raw IP addresses (error 1003); use a hostname.
5. Onboard HR users: create the auth user, then insert their `hr_users` row.
6. Failover check: stop one Lightsail instance while hitting
   `https://api-qa.mindqtalent.com/health` continuously — expect continued HTTP 200
   from the surviving AZ (Lightsail does not auto-replace the stopped node).

## Security notes

- `service_role` key and `SUPABASE_JWT_SECRET` are server-side only. Never ship
  them to the browser (the frontend uses only the anon/publishable key).
- Tenancy is enforced by RLS on the supabase-js path and by explicit
  `corporate_id` checks on the FastAPI/service_role path.
- **Fail-closed boot:** with `DEBUG=false`, FastAPI refuses to start if
  `SECRET_KEY` / `SUPABASE_JWT_SECRET` are still the `.env.example` defaults
  or shorter than 32 characters, or if `CORS_ORIGINS` is empty / localhost-only.
  (`DEBUG` defaults to **false**. Local dev sets `DEBUG=true` in `backend/.env`;
  tests pin it in `tests/conftest.py` and CI, so example secrets work there.)
- **No secrets in logs:** OTP codes are never logged (even when SES fails, in
  any environment), and invite logs mask the access PIN (`Code=***-1`) and
  strip the `?code=` query from links. QA testers need verified SES inboxes
  (or SES out of sandbox) to receive codes.
- **Shared rate limits:** every limiter uses the same Redis as ARQ (sliding
  window, TTL-evicted keys), so budgets hold across workers and both nodes.
  If Redis errors, limits fall back to per-process for 30s, then retry.
- **Hosted Supabase:** after `supabase db push`, confirm Dashboard → Advisors
  shows RLS enabled on `corporates`, `packages`, `assessments`, `candidates`,
  `candidate_progress`, and `candidate_responses`. Enable Auth leaked-password
  protection (HaveIBeenPwned) in the Auth settings.
- **Invite-only enrollment:** package access codes do **not** auto-register
  strangers. Pre-invite candidates (or set `packages.allow_open_enrollment = true`
  intentionally). Invite codes still match email.
- **Rate limits:** candidate login ≈ 10 / 15 min / IP; public track, blind review,
  support, and chat ≈ 60 / min / IP; report/scorecard endpoints (Gemini + PDF)
  20 / 10 min / user; nudges 30 / h / user; invites 200 / h / user. Staging Multi-AZ
  shares counters via `REDIS_URL` so `RateLimiter` / `AuthFailureLimiter` stay
  correct across both Lightsail nodes. Without Redis, budgets multiply by replica
  count. Proxy chain is Cloudflare → Lightsail LB → Nginx: set
  `TRUSTED_PROXY_HOPS=2` and `CLIENT_IP_HEADER=CF-Connecting-IP`. Local/direct
  access keeps `TRUSTED_PROXY_HOPS=0` so forged `X-Forwarded-For` is ignored.
- **Exam content isolation:** non-ops HR has no direct PostgREST read on
  `assessments`, `custom_technical_questions`, `candidate_responses`, or
  `candidate_progress`, and no write on `candidates` / `corporates`
  (migration `20261009100000_security_hardening`). Candidate APIs strip answer-key
  aliases including `correct_answer_or_rubric`, and a DB trigger locks answers once
  a module is `COMPLETED`.
- **Reports:** archived only to the private `R2_REPORTS_BUCKET_NAME` bucket (never the
  public logo bucket) and served via presigned URLs capped at 30 minutes.
- Security headers: FastAPI sets `X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, and HSTS on HTTPS. The Vite app
  ships a CSP meta tag (tighten `connect-src` for production API hosts).

## Pre-launch checklist (shipping)

- [ ] `DEBUG=false`, strong `SECRET_KEY`, hosted `SUPABASE_JWT_SECRET`, production `CORS_ORIGINS` (exact https origins, no `*`)
- [ ] Private R2 bucket created and set as `R2_REPORTS_BUCKET_NAME`; existing report objects moved out of the public logo bucket
- [x] Multi-AZ staging: 2× Lightsail instances (`mindq-backend-staging`, `mindq-backend-staging-2`) behind `mindq-backend-lb` in `ap-southeast-2`
- [x] `TRUSTED_PROXY_HOPS=2` / `CLIENT_IP_HEADER=CF-Connecting-IP` match Cloudflare → Lightsail LB → Nginx
- [x] Shared Redis (`REDIS_URL` on private `:6379`) for cross-node rate limiting
- [ ] Migrations applied (`supabase db push`), including psychometric response RLS
- [ ] `pip-audit` / `npm audit` clean of reachable critical/high findings
- [x] Health check `GET /health` returns 200 behind the load balancer
- [ ] Switch the load-balancer health check to `GET /health/ready`
- [x] Zero-downtime failover verified (stop one instance; public `/health` stays 200)
- [ ] Rollback: previous container image + prior migration down path documented
- [ ] Structured JSON logs flowing (request_id on responses via `X-Request-Id`)
- [ ] Confirm package open-enrollment flags match product intent per tenant

## Operations notes (P1 hardening)

- **Docker images.** `backend/Dockerfile` runs uvicorn as PID 1 (exec form),
  as a non-root user, with `--timeout-graceful-shutdown 30` and
  `--proxy-headers` (`FORWARDED_ALLOW_IPS`, default `127.0.0.1` = Nginx on the
  same host). `backend/.dockerignore` keeps `.env`, local DBs, report HTML and
  tests out of the image. `frontend/Dockerfile` builds a static bundle
  (`npm ci && npm run build`, `VITE_*` as `--build-arg`) and serves it with
  nginx on port 3000 (`frontend/nginx.conf`, SPA fallback).
- **Sentry.** Now actually initialized in the API and the ARQ worker when
  `SENTRY_DSN` is set. ERROR logs become events; swallowed storage failures
  are sent with a `silent_failure` tag (alert on it, e.g.
  `erasure_purge_failed`, `report_cache_upload_failed`).
- **Erasure.** After the DB delete, report PDFs are purged by the
  `task_purge_candidate_report_files` ARQ job (6 tries, 60s/120s/... backoff).
  A final failure logs `erasure_purge_failed` and goes to Sentry; finish that
  purge by hand.
- **Bulk report ZIP.** Each response holds at most 100 PDFs in memory. Bigger
  packages download as several parts (`X-Report-Zip-Next-Offset`); each part
  counts against the 5-per-10-minutes ZIP limit.
- **Gemini.** Blocking SDK calls run on a dedicated pool of
  `GEMINI_MAX_CONCURRENCY` threads (default 4) per process, each request
  capped by `GEMINI_TIMEOUT_SECONDS`.
- **Database errors.** Constraint violations return `409 CONFLICT`. Deadlocks
  on autosave / submit / HR reset are retried once server-side; otherwise
  `503` with `Retry-After: 1`. A dropped connection invalidates only that
  connection (no pool-wide reconnect).

## Host configuration (`infra/`)

Sanitized Nginx, systemd and logrotate templates for the API nodes live in
[`infra/`](infra/README.md). The values that must stay aligned:

| Setting | Value | Why |
|---------|-------|-----|
| Nginx `proxy_read_timeout` / `proxy_send_timeout` | `90s` | Above asyncpg `command_timeout` (60s) and PDF rendering |
| Nginx `client_max_body_size` | `15m` | Above the 10 MiB JD PDF upload cap |
| systemd `TimeoutStopSec` (API + worker) | `40` | Above Uvicorn `--timeout-graceful-shutdown 30` |
| systemd `Restart` / `KillSignal` | `always` / `SIGTERM` | Crash recovery and graceful drain |

Change a template in the repo first, then apply it to both nodes.
