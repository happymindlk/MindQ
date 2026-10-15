# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are internal operations staff assembling and dispatching assessment packages for client companies. Secondary users are HR clients who approve technical items via a tokenized review link and view a read-only, OTP-gated pipeline of candidate results. Candidates still complete assessments via access codes (portal).

## Product Purpose

Assess Pulse is a managed-service assessment platform: ops builds client packages from global psychometric modules plus custom technical questions; FastAPI scores and runs Gemini JD-fit; HR never sees psychometric item content. Success means ops can publish a locked package with sharing links, and HR can review technical items and completion/scorecards without recovering test keys.

## Positioning

Internal admin portal that dispatches tenant-isolated psychometric packages. Not a self-serve HR package builder.

## Key Workflows

- Ops signs in (password), picks a company, carts global modules + custom technical items, autosaves drafts, publishes (locks + mints review/access links).
- HR opens `/client/review/{token}` — technical questions only.
- HR signs in with email OTP (6-digit pin) to a read-only pipeline (Pending / Scoring / Completed) and Gemini scorecards.
- Ops Assessment History drills Companies → Packages → Candidates.
- Candidates enter with `?code=`; FastAPI issues candidate JWTs.

## Constraints

- Psychometric modules are never returned on HR review or client scorecard APIs.
- RLS: ops (`hr_users.role` admin/owner) is cross-tenant; HR is tenant-scoped and SELECT-only on technical assessments.
- FastAPI holds Gemini keys and publish/review writes (service_role).
- Candidate portal contracts stay intact.

## Brand Commitments

- Product name: Assess Pulse.
- Visual direction: enterprise Operate surface — Linear / Stripe / Datadog / Vercel register; high-contrast dark theme; dense information UI. Tabular nums, 1px `border-neutral-800`, muted uppercase labels. See DESIGN.md.
