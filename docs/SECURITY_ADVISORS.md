# Supabase security advisors (Assesspulse)

Captured via Supabase MCP `get_advisors` on project `djshmrkerssvpvcxqkqo`
(2026-09-26). Re-run after `supabase db push`.

## ERROR — RLS disabled on public tables

Advisor reported RLS **disabled** on:

- `public.corporates`
- `public.packages`
- `public.assessments`
- `public.candidates`
- `public.candidate_progress`
- `public.candidate_responses`

Local migrations enable RLS; the hosted project appears out of sync.

**Remediation:** [RLS disabled in public](https://supabase.com/docs/guides/database/database-linter?lint=0013_rls_disabled_in_public)

1. `supabase link --project-ref djshmrkerssvpvcxqkqo`
2. `supabase db push` (includes `20260926120000_harden_psychometric_responses_enrollment.sql`
   which re-asserts `ENABLE ROW LEVEL SECURITY` on these tables)
3. Re-run advisors until the ERROR count is zero

## WARN — Leaked password protection disabled

Enable HaveIBeenPwned checks in Dashboard → Authentication → Providers /
Password security.

**Remediation:** [Password strength and leaked password protection](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection)
