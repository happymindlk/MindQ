# Data Protection & Retention Policy

Assess Pulse / MindQ candidate assessment platform. This document describes how
candidate personal data is protected in transit and at rest, how long it is
retained, how erasure works, and which sub-processors process it.

## 1. Encryption in transit and at rest

### In transit

- All production HTTP endpoints are served over **TLS 1.2/1.3** (terminating at
  Cloudflare Pages, the API load balancer / reverse proxy, and Supabase).
- The FastAPI service sets **HSTS** (`Strict-Transport-Security`) on HTTPS
  responses via `SecurityHeadersMiddleware`.
- Production CORS allows only exact `https://` frontend origins (no wildcards).
- Database connections to hosted Supabase Postgres use the project connection
  pooler over **TLS**. Local development may disable SSL (`PGSSLMODE=disable`)
  against `127.0.0.1` only.

### At rest

- **PostgreSQL (Supabase):** data volumes are encrypted with **AES-256** at rest
  under Supabase’s managed infrastructure.
- **Private report objects (Cloudflare R2 or S3-compatible storage):** candidate
  MindQ Report PDFs are stored only in the dedicated private bucket
  (`R2_REPORTS_BUCKET_NAME`), never in the public logo bucket. Objects inherit
  the provider’s **server-side AES-256** encryption at rest.
- Application secrets (JWT signing keys, Gemini API key, storage credentials)
  live in environment configuration, not in source control.

## 2. Retention and right to erasure

### Standard retention

| Data class | Retention |
|---|---|
| Candidate identity, responses, progress, scores, Gemini synthesis, report snapshots | Retained for the life of the hiring engagement with the client corporate, or until erasure is requested |
| Cached / archived report PDFs in private object storage | Same as candidate record; purged on erasure or assessment reset (cache prefix) |
| Support tickets linked to a candidate | Ticket row may remain for ops continuity; candidate link and free-text fields are scrubbed on erasure |
| Application audit logs (`report_accessed`, `candidate_erased`) | Retain IDs only (no name/email/prose) for security monitoring; follow host log retention |

Clients may agree shorter or longer contractual retention windows in a
data-processing agreement (DPA). When a shorter window applies, ops must erase
candidates via the admin pipeline below when the window ends.

Aggregated and irreversibly anonymized assessment metrics may be retained for
psychometric validation, norming, and research purposes.

### Immediate end-to-end erasure

Authorized HR (same tenant) or ops may erase a candidate via:

```http
DELETE /api/v1/admin/candidates/{candidate_id}
```

The pipeline:

1. Scrubs linked `support_tickets` (nulls `candidate_id`, redacts details).
2. Hard-deletes the `candidates` row so PostgreSQL `ON DELETE CASCADE` removes
   `candidate_responses`, `candidate_progress`, `candidate_evaluations`, and
   `candidate_reports`.
3. Purges private storage: cached keys under `{corporate_id}/{candidate_id}/`
   and legacy archive keys `{corporate_id}/{candidate_id}.pdf|.html`.
4. Emits a structured `candidate_erased` audit event (`admin_user_id`,
   `corporate_id`, `candidate_id` only — never name or email).

Assessment **reset** (`POST …/reset`) is not erasure: it clears answers for a
retake while keeping the candidate identity.

## 3. Access logging and sub-processors

### Access logging

- Every MindQ Report JSON view or PDF download emits `report_accessed` with
  `actor_id`, `actor_role`, `corporate_id`, `candidate_id`, and `format`
  (`json` | `pdf`).
- Successful erasure emits `candidate_erased` as above.
- Gemini technical-item grading logs metadata only (`candidate_id`,
  `question_id`, `score`, `latency_ms`) — never AI feedback prose or answers.
- Sentry (when enabled) redacts passwords, OTPs, tokens, and response bodies.

### Sub-processors

| Sub-processor | Role | Data terms relevant to candidates |
|---|---|---|
| **Supabase** | Auth, Postgres, optional Storage | Data hosted in the project region; RLS + service-role used by FastAPI |
| **Cloudflare R2 / AWS S3** | Private report object storage | Server-side encryption at rest; tenant-prefixed object keys |
| **AWS SES** | Transactional email (invites, OTPs, nudges) | Recipient email and message content for delivery |
| **Google Gemini Developer API (paid tier)** | Report narrative synthesis and technical open-ended grading | Must run on a **billing-enabled** Google AI Studio / Gemini API project. Under Google’s paid Gemini API terms, prompts and responses are **not used to train Google models**. Abuse-monitoring retention may still apply; workloads that require contractual zero data retention / enterprise DPA should use **Vertex AI** instead |

Ops must confirm the production `GEMINI_API_KEY` belongs to a paid (billing-enabled)
project before processing live candidate data, and must not enable Gemini features
that require long-lived provider-side storage (e.g. Search grounding) for candidate
PII workloads unless separately approved.

## 4. Client data-processing agreement

Commercial clients receive a Data Processing Agreement (DPA) that incorporates
this technical baseline: encryption, retention, erasure via
`DELETE /api/v1/admin/candidates/{id}`, access logging, and the sub-processor
list above. Legal templates live outside this repository; engineering keeps this
file aligned with the shipped deletion and audit behaviour.
