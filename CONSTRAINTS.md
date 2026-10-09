# Project constraints (production bar)

Assess Pulse quality floor for agent and human changes. Do not lower these
without an explicit ADR.

## Security

- Fail-closed when `DEBUG=false`: no default/example `SECRET_KEY` or
  `SUPABASE_JWT_SECRET`; production `CORS_ORIGINS` required.
- Authorization on every FastAPI path that returns tenant data; RLS remains
  the supabase-js boundary.
- Psychometric item banks and psychometric `candidate_responses` are ops-only
  for HR JWT roles.
- Package access codes are invite-only unless `allow_open_enrollment` is true.
- Rate-limit candidate login and unauthenticated public surfaces.
- Never commit secrets; never log tokens, passwords, or full PII.

## Testing

- Backend: `pytest` must pass on every PR.
- RLS: `scripts/verify_rls.sh` (CI `rls` job) must pass; new policies need
  assertions in `supabase/tests/rls_assertions.sql`.
- Frontend: `npm run lint` and `npm run build` must pass.

## Observability

- Every HTTP response carries `X-Request-Id`.
- Significant auth / public capability events emit structured logs with an
  `event` field (no emails/tokens in log fields).

## Dependencies

- CI runs `pip-audit` and `npm audit --audit-level=high` against lockfiles /
  requirements. Deferral of a critical/high finding requires a dated note in
  the PR.
