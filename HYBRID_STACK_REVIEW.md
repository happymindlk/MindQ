# Happy Mind — Hybrid Stack Review

**Branch:** `cursor/supabase-hybrid-migration-cc7a` (PR #4, against `main`)
**Status:** Architecture is in place and was demoed end-to-end on a local `supabase start` stack. It is **not** production-ready. Review the files in §3 before starting the next slice of work.
**Audience:** Anyone picking this up after a rushed local run (Windows or cloud).

---

## 1. What we were solving

The original app (`main`) was a **SQLite demo**:

- FastAPI owned all admin CRUD with **no authentication**.
- Organizations lived in a single SQLite file.
- The React UI called `/api/v1/admin/...` openly.

The agreed target is **Option C (hybrid)**:

```
HR browser  ── supabase-js + HR JWT + RLS ──►  Supabase (Auth, Postgres, Storage)
     │
     └── candidate login / scoring / PDF / nudge ──►  FastAPI (service_role)
```

- **HR users** are real Supabase Auth users. `corporate_id` is injected into JWT `app_metadata` by a custom access-token hook, then enforced by Postgres RLS.
- **Candidates are not** Supabase users. They log in with a package access code + email and get a FastAPI-signed JWT.

---

## 2. What we actually shipped (by phase)

| Phase | What landed | Main files |
|---|---|---|
| **0 — Scaffold** | `supabase init`, Postgres/Supabase Python deps, `@supabase/supabase-js`, env templates | `supabase/config.toml`, `backend/requirements.txt`, `backend/.env.example`, `frontend/.env.example` |
| **1 — Schema** | Normalized Postgres: `corporates`, `hr_users`, `packages`, `assessments`, `candidates`, `candidate_progress`, `candidate_responses`. Denormalized `corporate_id` on every business table. SQLAlchemy rewritten; **no** `metadata.create_all` | `supabase/migrations/20260823150227_initial_schema.sql`, `backend/app/models/*`, `backend/app/database.py` |
| **2 — Auth** | Custom access-token hook writes `corporate_id` / `corporate_role` into JWT `app_metadata`. FastAPI verifies HR tokens and **issues** candidate tokens | `supabase/migrations/20260823151159_auth_custom_access_token_hook.sql`, `backend/app/auth.py` |
| **3 — RLS** | Tenant isolation via `private.user_corporate_id()`. SELECT/INSERT/UPDATE policies with `WITH CHECK`. `service_role` still bypasses RLS | `supabase/migrations/20260823151337_rls_policies.sql`, `scripts/verify_rls.sh` |
| **4 — Frontend rewire** | HR login via Supabase Auth. Admin data via `supabase-js` + `create_package` RPC + `package_overview` / `candidate_overview` views. Open FastAPI admin CRUD **removed** | `frontend/src/lib/supabaseClient.js`, `frontend/src/lib/adminApi.js`, `frontend/src/context/AuthContext.jsx`, `frontend/src/pages/admin/Login.jsx`, `backend/app/api/v1/router.py` |
| **5 — Reports / codes / CORS** | Reports require HR JWT + tenant match, stream bytes, archive to private Storage bucket `reports`. Access codes generated in SQL (`gen_access_code()`). CORS tightened | `backend/app/api/v1/reports.py`, `backend/app/services/storage_service.py`, `supabase/migrations/20260823151701_admin_rpc_and_views.sql`, `supabase/migrations/20260823152455_storage_reports.sql` |
| **6 — Scoring** | Replaced random scores with real MCQ scoring when `correct_answer` is present | `backend/app/services/scoring.py` |
| **7 — Tests / CI / docs** | Auth + scoring tests, portable RLS script, GitHub Actions, `DEPLOYMENT.md` | `backend/tests/*`, `.github/workflows/ci.yml`, `DEPLOYMENT.md` |
| **Reconcile** | Email nudges + CSV export + technical-report PDFs, ported onto this foundation | `backend/app/services/email_service.py`, `backend/app/api/v1/notifications.py`, `frontend/src/pages/admin/CandidateTracker.jsx` |
| **Run-time fixes** | Blank admin page when Vite env missing; ES256 JWKS verify for current `supabase start`; `GET /` no longer 404s | `frontend/src/lib/supabaseClient.js`, `frontend/src/main.jsx`, `backend/app/auth.py`, `backend/app/main.py` |

### What was verified (cloud agent, local Docker Supabase)

Happy path, not a security audit:

1. HR `hr@acme.test` signed in (JWT contained `corporate_id`).
2. Created package **Onboarding Assessment** → code `HM-JCHMYH-T`.
3. Candidate `alex@example.com` completed a Likert question.
4. Tracker showed **Completed 1/1**.
5. PDF report downloaded with the HR token (~27 KB).

That demo lived on the **cloud VM**. It is **not** on your Windows laptop unless you recreate the stack there.

### What was *not* verified on your PC

The rushed local run hit expected API 404s (`GET /` and `GET /favicon.ico` on port **8000**). `/docs` and `/health` were 200. The website is port **5173**, not 8000. A full click-through on Windows (HR login → package → candidate → report) still needs to be done after env is correct.

---

## 3. Files to review very carefully before the next part

These are the files where a mistake becomes a **tenant leak**, a **broken login**, or a **false sense of scoring**. Read them with a skeptical pass, not a skim.

### 3.1 Security-critical (do not skip)

| File | Why review it |
|---|---|
| `supabase/migrations/20260823151337_rls_policies.sql` | Entire tenancy model. Confirm every table has RLS **on**, `USING` + `WITH CHECK`, and that `anon` has **no** grants. There are **no DELETE policies** (HR cannot delete rows via the client — decide if that is intended). `authenticated` can INSERT/UPDATE business tables. |
| `supabase/migrations/20260823151159_auth_custom_access_token_hook.sql` | Authorization source of truth. Must stay on **`app_metadata`**, never `user_metadata`. Hook is in `public`; execute is revoked from `anon`/`authenticated` — still confirm that before cloud deploy. |
| `supabase/config.toml` | Hook must stay enabled. Local `enable_signup = true` and `enable_confirmations = false` are **dev-only**. Production must not ship those defaults. Current CLI mints **ES256** JWTs. |
| `backend/app/auth.py` | Two token worlds: candidate HS256 (`SECRET_KEY`) vs HR (HS256 **or** JWKS ES256). `service_role` is never verified here; reports/nudges depend on this file being correct. |
| `backend/app/api/v1/reports.py` | `service_role` **bypasses RLS**. Tenant check is a single `if candidate.corporate_id != hr.corporate_id`. Same pattern in `notifications.py`. Miss that check → cross-tenant PDF/email. |
| `backend/app/api/v1/notifications.py` | Same tenant check. Nudge emails include access codes. |
| `backend/app/config.py` | `SECRET_KEY` must **not** be the Supabase `sb_secret_…` key. `SUPABASE_SERVICE_ROLE_KEY` is server-only. |
| `frontend/src/lib/supabaseClient.js` | Browser must only ever get the **anon / publishable** key. Placeholders exist so a missing env does not white-screen the app. |
| `supabase/migrations/20260823151701_admin_rpc_and_views.sql` | `create_package` is `security invoker` (good). Views use `security_invoker = on` (required — views otherwise bypass RLS). `gen_access_code()` is `security definer`. |
| `supabase/migrations/20260823152455_storage_reports.sql` | Bucket is private. HR SELECT policy keys off first path segment = `corporate_id`. No authenticated INSERT (only `service_role` writes). |

### 3.2 Product / correctness (easy to ship a lie)

| File | Why review it |
|---|---|
| `backend/app/services/scoring.py` | Scores **only** MCQs that have `correct_answer`. Likert/open return `None`. |
| `frontend/src/pages/admin/PackageBuilder.jsx` | Does **not** send `correct_answer`. So today’s builder produces packages that **cannot be auto-scored**. Tracker “Avg Score” will stay `-`. |
| `backend/app/services/candidate_service.py` | Login: any email + valid **package** access code creates a candidate. There is no invite list, no rate limit, no CAPTCHA. Shared package code, not per-person codes. |
| `frontend/src/lib/adminApi.js` | HR data path. Report/nudge still go to FastAPI with the HR access token. |
| `frontend/src/pages/admin/CandidateTracker.jsx` | CSV is client-side from RLS-scoped rows (good). Nudge button hits FastAPI. |
| `backend/app/services/email_service.py` | Without SendGrid/SES it **logs the full email (PII + access code)** and returns success. Fine for demo, dangerous if `DEBUG` logs leak. |
| `backend/app/database.py` | Schema is migrations-only. Never reintroduce `create_all`. |

### 3.3 Stale / misleading (fix or you will confuse the next intern)

| File | Problem |
|---|---|
| `docker-compose.yml` | Still the **old SQLite** stack. Do not use it for this branch. |
| `README.md` | Still describes SQLite in places; points at `DEPLOYMENT.md` in a banner. Needs a rewrite after this review. |
| `backend/.env.example` | Comment still says JWT secret is HS256-only. Code now also accepts ES256 via JWKS. |
| Competing git branches | Do **not** merge `wip/local-main-work` or the old `cursor/*-112f` branches on top of this one. They are a different architecture (`organizations` + SQLite + unauthenticated admin). |

### 3.4 Tests you should re-run after any review edit

| Command | What it covers |
|---|---|
| `cd backend && python -m pytest tests/ -v` | Candidate JWT, HR JWT (HS256 + live ES256 if local supabase is up), scoring, email stub, `GET /` |
| `cd frontend && npm run lint && npm run build` | Admin UI compiles with supabase-js |
| `bash scripts/verify_rls.sh` | Migrations apply on a shimmed Postgres; tenant isolation assertions |
| Manual: HR login → create package → `/portal` → tracker → Download report | The only test that proves the three processes talk to each other |

---

## 4. Known gaps and risks (read before “next part”)

### Must-fix before real users or a hosted project

1. **Hosted Assesspulse project (`djshmrkerssvpvcxqkqo`)** already has Happy Mind-shaped tables with **RLS disabled**. Do not point this app at it until migrations + RLS are applied. Anyone with the anon key can read/write those tables today.
2. **Public Auth signup** is enabled locally. A random person can create a Supabase user. Without an `hr_users` row they should see no tenant data, but production should **disable open signup** and invite HR users only.
3. **Package access codes are shared.** Anyone who knows `HM-XXXXXX-C` can sit the assessment as any email. Decide: keep shareable codes, or issue per-candidate codes.
4. **No `correct_answer` in the builder** → scoring is effectively off for UI-created tests.
5. **HR JWT is stale** until the next sign-in after you insert `hr_users`. If you add the mapping while they are already logged in, RLS will look empty until they sign out/in.
6. **`docker-compose.yml` / README** still teach the SQLite world.

### Should-fix soon (quality, not a stop-ship for a private demo)

- No DELETE (or archive) flow for packages, tests, or candidates.
- No HR “invite teammate” UI (`hr_users` insert is SQL-only; authenticated role cannot insert `hr_users`).
- No rate limit / lockout on candidate login.
- Chatbot (`backend/app/api/v1/chat.py`) is still a stub.
- Vite 8 plugin warnings (`@vitejs/plugin-react` vs oxc) — noisy, not fatal. Your Windows log using `plugin-react-oxc` means **local files may not match this branch**; run `git status`.
- Email from-address `no-reply@happymind.com` is a placeholder.
- Password policy locally is weak (`minimum_password_length = 6`).

### Explicitly deferred from the other local branch

These existed on `wip/local-main-work` and were **not** ported on purpose (they targeted the old unauthenticated admin):

- `AssessmentsManager.tsx` / `CorporatesManager.tsx` (TypeScript admin UIs)
- Shareable PII-masked public tracking link (`tracking_service.py`)

Do not copy them until they sit on supabase-js + RLS (or FastAPI + HR JWT), never on open REST.

---

## 5. How the running system is supposed to look

Three processes, always:

| Process | Command | URL | What it is |
|---|---|---|---|
| Supabase | `supabase start` then `supabase db reset` once | Studio `http://127.0.0.1:54323` API `http://127.0.0.1:54321` Postgres `127.0.0.1:54322` | Auth + DB + RLS + Storage |
| FastAPI | `cd backend && python -m uvicorn app.main:app --reload --port 8000` | `http://127.0.0.1:8000/docs` `http://127.0.0.1:8000/health` | Candidate + PDF + nudge. **Not the website.** |
| Vite | `cd frontend && npm run dev` | **`http://localhost:5173/`** | The product UI |

### Env files (gitignored — create locally)

**`frontend/.env.local`** (Vite only reads this at **startup**):

```env
VITE_SUPABASE_URL=http://127.0.0.1:54321
VITE_SUPABASE_ANON_KEY=<anon or publishable key from `supabase status`>
VITE_API_URL=
```

**`backend/.env`:**

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres
SUPABASE_URL=http://127.0.0.1:54321
SUPABASE_SERVICE_ROLE_KEY=<service_role / secret key>
SUPABASE_JWT_SECRET=<jwt secret from supabase status>
SECRET_KEY=<your own signing secret, NOT the sb_secret key>
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

### One-time HR bootstrap

Studio → Authentication → Add user (email + password), then:

```sql
insert into public.corporates (name, slug) values ('Acme', 'acme')
  returning id;

insert into public.hr_users (user_id, corporate_id, full_name, role)
values ('<auth-user-uuid>', '<corporate-id>', 'HR Admin', 'admin');
```

Sign in **after** the `hr_users` row exists.

### Local 404s that are not bugs

| Log | Meaning |
|---|---|
| `GET /` or `GET /favicon.ico` 404 on **:8000** | Browser opened the API. After `git pull`, `GET /` returns JSON pointing at :5173. |
| `GET /docs` 200, `GET /health` 200 | Backend is fine. |
| `GET /api/v1/admin/packages` 404 | **Old frontend.** You are not on this branch, or Vite is serving stale files. `git pull` + restart `npm run dev`. |

White screen on :5173 → missing `frontend/.env.local`, or Vite not restarted, or not on this branch (blank-page guard lives in `supabaseClient.js` + `main.jsx`).

---

## 6. Suggested review checklist (half-day, in order)

Use this as the “we were in a hurry, now we slow down” pass.

1. **Git hygiene**
   - `git checkout cursor/supabase-hybrid-migration-cc7a && git pull`
   - `git status` — no surprise leftover `.tsx` / SQLite files
   - Confirm you are **not** merging `wip/local-main-work` or `*-112f` branches
2. **Read the security files in §3.1** (RLS, hook, auth.py, reports.py, notifications.py, env examples)
3. **Run automated tests** (pytest, frontend lint/build, `scripts/verify_rls.sh`)
4. **Local three-process run** on Windows with the env files above
5. **Manual script**
   - HR login at `http://localhost:5173/admin/login`
   - Create a package (note the access code)
   - `/portal` as a candidate, complete a test
   - Tracker shows the candidate
   - Download report (proves HR JWT → FastAPI, including ES256)
6. **Decide product questions** (block next feature work until answered)
   - Shared package code vs per-candidate codes?
   - Who is allowed to create corporates / invite HR?
   - Must MCQs have a marked correct answer in the builder?
   - Hosted Supabase project: new empty project vs repairing Assesspulse (RLS currently off there)?

Only after 1–6 should the next slice start.

---

## 7. What to do next (recommended order)

Do **not** start a new architecture. Finish this one.

### Next slice A — Make the demo honest (small, high value)

- Package builder: add `correct_answer` for MCQ; persist it in the questions JSONB.
- Confirm scoring shows a real % on tracker + PDF.
- Optional: per-candidate access codes if the product wants invites, not a shared classroom code.

### Next slice B — HR operations that RLS already allows

- Candidate invite / list management in the admin UI (insert into `candidates` via supabase-js — policies already allow tenant INSERT).
- Package archive / deactivate (`is_active` already exists).
- HR teammate invite (needs a **new** SQL policy or a `service_role` RPC — authenticated cannot insert `hr_users` today).

### Next slice C — Production hardening

- New Supabase cloud project (or repair Assesspulse): `supabase link` + `supabase db push` + enable the access-token hook in the dashboard.
- Disable public signup; enable email confirmations.
- Rotate `SECRET_KEY`; never put `service_role` in Vite.
- Rewrite `README.md`; replace or clearly mark `docker-compose.yml` as legacy.
- Real email provider (SendGrid/SES) and a real from-address.
- Candidate login rate limiting.

### Next slice D — Deferred UI (only after A–C)

- Port Assessments / Corporates managers onto **this** stack (supabase-js + RLS), not the old REST admin.
- PII-masked shareable tracking link, if still required, as a **FastAPI** endpoint that does not expose emails.

### Explicitly not next

- Merging SQLite/`organizations` branches.
- Using `docker-compose.yml` as-is.
- Pointing production at Assesspulse while RLS is off.
- Teaching people to “open localhost:8000” as the app.

---

## 8. Architecture cheat-sheet

**Tenant key:** `corporate_id` (UUID), denormalized onto every business table.

**HR request path**

1. Email/password → Supabase Auth.
2. Hook reads `hr_users` → JWT `app_metadata.corporate_id`.
3. Browser `supabase-js` with anon key + user JWT.
4. RLS: `corporate_id = private.user_corporate_id()`.
5. Package create: RPC `create_package(...)` (invoker, so RLS applies).
6. Report / nudge: `Authorization: Bearer <HR access token>` → FastAPI verifies JWT → extra `corporate_id` check because DB uses `service_role`.

**Candidate request path**

1. `POST /api/v1/candidate/login` `{ access_code, email }`.
2. FastAPI looks up **package** by code, creates/finds candidate, signs HS256 token (`SECRET_KEY`, audience `happy-mind-candidate`).
3. Autosave / submit / dashboard use that token. Scoring on submit.

**Two secrets (easy to mix up)**

| Env | Used for |
|---|---|
| `SUPABASE_JWT_SECRET` / JWKS | Verify **HR** tokens from GoTrue |
| `SECRET_KEY` | Sign/verify **candidate** tokens |
| `SUPABASE_SERVICE_ROLE_KEY` | FastAPI → Postgres/Storage, **bypasses RLS** |

---

## 9. Commit map (this branch vs `main`)

```
3c2fbf4  Phase 0: scaffold, deps, env templates
6d5f6fb  Phase 1: schema, models, async engine
0e646e4  Phase 2: access-token hook + HR JWT
cda5086  Phase 3: RLS
09aac1a  Phase 4: frontend supabase-js; retire admin REST
5cc1352  Phase 5: reports, storage, codes, CORS
ef1693e  Phase 7: tests, CI, DEPLOYMENT.md
187ca4d  Reconcile: nudges + CSV export
7e0a6f4  Blank-page guard for missing Vite env
fe9dfd2  Verify HR JWTs via JWKS (local ES256)
187dbc0  GET / returns a pointer to the Vite app
```

How to run day-to-day: **[DEPLOYMENT.md](DEPLOYMENT.md)**.
This document is the **review + next-steps** companion. Update both if the next slice changes auth, RLS, or env vars.
