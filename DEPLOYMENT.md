# Happy Mind — Deployment & Local Development (Hybrid Supabase Stack)

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
- Full RLS suite against the real stack: `supabase test db` (add pgTAP tests
  under `supabase/tests/`).

CI runs all three (`.github/workflows/ci.yml`).

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
