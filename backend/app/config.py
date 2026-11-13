import json
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode


class Settings(BaseSettings):
    PROJECT_NAME: str = "MindQ Psychometric Assessment Platform"
    # Default True so local/CI boots with example secrets. Production MUST set DEBUG=false
    # (assert_production_ready refuses weak secrets / localhost CORS when False).
    DEBUG: bool = True
    # Deployment environment: "development" | "staging" | "qa" | "production".
    # Non-production enables QA fallbacks (e.g. logging a failed-SES admin OTP
    # to the server log). Production MUST set ENVIRONMENT=production + DEBUG=false.
    ENVIRONMENT: str = "development"

    # Postgres (async driver). Defaults to the local Supabase stack.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"

    # Secret used to SIGN candidate access tokens (distinct from Supabase's JWT secret).
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    CANDIDATE_TOKEN_TTL_MINUTES: int = 240
    # Candidate login always requires the custom email-OTP challenge
    # (candidate_login_challenges); there is no disable flag.
    # HR client-portal session tokens (also signed with SECRET_KEY, separate audience).
    CLIENT_TOKEN_TTL_MINUTES: int = 480

    # Supabase settings (server-side). Auth/DB + public logo uploads via Storage.
    SUPABASE_URL: str = "http://127.0.0.1:54321"
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    # Verifies HR access tokens minted by Supabase Auth (HS256).
    SUPABASE_JWT_SECRET: str = "super-secret-jwt-token-with-at-least-32-characters-long"
    # Public Storage bucket for corporate logos (see supabase migrations).
    # Override only if you intentionally provision a different public bucket.
    SUPABASE_LOGO_BUCKET: str = "corporate-logos"

    # Optional S3-compatible fallback for logos + private report archives.
    # Prefer native Supabase Storage above. Accepts R2_*, AWS_S3_*, and the common
    # Supabase docs names AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY when used as
    # Storage gateway credentials (those same names are also read by SES below --
    # prefer AWS_S3_* if you need both email and storage keys).
    R2_ACCESS_KEY_ID: str = Field(
        default="",
        validation_alias=AliasChoices(
            "R2_ACCESS_KEY_ID",
            "AWS_S3_ACCESS_KEY_ID",
            "AWS_ACCESS_KEY_ID",
        ),
    )
    R2_SECRET_ACCESS_KEY: str = Field(
        default="",
        validation_alias=AliasChoices(
            "R2_SECRET_ACCESS_KEY",
            "AWS_S3_SECRET_ACCESS_KEY",
            "AWS_SECRET_ACCESS_KEY",
        ),
    )
    R2_ENDPOINT_URL: str = Field(
        default="",
        validation_alias=AliasChoices("R2_ENDPOINT_URL", "AWS_S3_ENDPOINT_URL"),
    )
    R2_BUCKET_NAME: str = Field(
        default="assess-pulse",
        validation_alias=AliasChoices("R2_BUCKET_NAME", "AWS_STORAGE_BUCKET_NAME"),
    )
    R2_PUBLIC_URL: str = Field(
        default="",
        validation_alias=AliasChoices("R2_PUBLIC_URL", "STORAGE_PUBLIC_BASE_URL"),
    )
    R2_REGION: str = Field(
        default="",
        validation_alias=AliasChoices("R2_REGION", "AWS_S3_REGION_NAME"),
    )
    # Candidate reports contain PII + psychometric results, so they must never share
    # the publicly readable logo bucket. Blank disables report archiving entirely.
    R2_REPORTS_BUCKET_NAME: str = ""
    REPORT_URL_TTL_SECONDS: int = 900

    # AWS SES transactional email (boto3). Credentials may come from env keys
    # or the default AWS credential chain (IAM role, shared config, …).
    # Keep these distinct from Storage S3 gateway keys (use AWS_S3_* for storage).
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    EMAIL_FROM: str = "MindQ <noreply@mindqtalent.com>"
    # Inbox for gated beta / waitlist access requests (and other admin alerts).
    ADMIN_NOTIFICATION_EMAIL: str = "muhamadnas44@gmail.com"
    # Legacy alias -- prefer ADMIN_NOTIFICATION_EMAIL.
    BETA_ACCESS_ADMIN_EMAIL: str = ""
    # Comma-separated emails that skip waitlist and auto-provision into the
    # local "acme" test tenant (e.g. "dev@example.com,qa@example.com").
    # NoDecode: pydantic-settings otherwise JSON-parses list env values first.
    AUTO_APPROVE_EMAILS: Annotated[list[str], NoDecode] = []
    # Public origin of the React app (no trailing slash). Invite emails link to
    # `{FRONTEND_URL}/assessment?code=…`. Blank → request Origin → production.
    FRONTEND_URL: str = ""
    # Candidate-facing portal URL used in notification emails (legacy; prefer FRONTEND_URL).
    PORTAL_URL: str = ""

    GEMINI_API_KEY: str = ""
    # Stable (pinned) Gemini model ID -- never *-latest / *-preview / *-exp.
    # New Gemini API keys cannot call gemini-2.5-*; Google returns 404 NOT_FOUND.
    GEMINI_MODEL: str = "gemini-3.5-flash"
    # Comma-separated chain tried in order once a model exhausts retries on 429/503.
    # Each has its own capacity pool and free-tier daily quota; all must be callable
    # by this key (gemini-2.5-* returns 404). Blank disables fallback.
    GEMINI_FALLBACK_MODELS: str = "gemini-3.6-flash,gemini-3.5-flash-lite"
    # Per-attempt HTTP timeout so submit/report never hang forever on a slow call.
    GEMINI_TIMEOUT_SECONDS: float = 30.0
    # Total generate_content attempts per model (free-tier 429 / transient errors).
    GEMINI_MAX_RETRIES: int = 3
    # Background jobs have no user waiting, so they ride out capacity spikes longer.
    GEMINI_BACKGROUND_MAX_RETRIES: int = 5
    GEMINI_RETRY_BASE_SECONDS: float = 2.0
    GEMINI_RETRY_MAX_DELAY_SECONDS: float = 30.0
    # Pause between sequential custom-technical item grades (RPM throttle).
    GEMINI_INTER_REQUEST_SECONDS: float = 2.0
    # Paid-tier USD per 1M tokens for estimated_cost_usd on report usage rows.
    # Override when Google changes list prices; free-tier still records tokens.
    GEMINI_INPUT_USD_PER_1M: float = 1.50
    GEMINI_OUTPUT_USD_PER_1M: float = 9.00
    GEMINI_LITE_INPUT_USD_PER_1M: float = 0.25
    GEMINI_LITE_OUTPUT_USD_PER_1M: float = 1.50
    # Incomplete candidates older than this many hours are nudged by the job.
    NUDGE_AFTER_HOURS: int = 24

    # Durable ARQ job queue (Redis). Web process enqueues; a separate
    # `arq app.jobs.worker.WorkerSettings` process consumes.
    REDIS_URL: str = "redis://localhost:6379/0"
    ARQ_MAX_JOBS: int = 10
    # Gemini technical + JD synthesis + WeasyPrint prewarm can exceed a few minutes.
    ARQ_JOB_TIMEOUT: int = 300
    ARQ_MAX_TRIES: int = 3

    # Accepts a comma-separated string or a JSON / Python list in env / code.
    # NoDecode: pydantic-settings otherwise JSON-parses list env values first.
    CORS_ORIGINS: Annotated[str | list[str], NoDecode] = (
        "http://localhost:3000,http://localhost:5173"
    )
    # Number of trusted reverse proxies in front of the API (Cloudflare, Render, …).
    # 0 = ignore X-Forwarded-For entirely; any client can forge that header.
    TRUSTED_PROXY_HOPS: int = 0
    # Header set by the edge proxy with the verified client IP (e.g. CF-Connecting-IP).
    # Only honoured when TRUSTED_PROXY_HOPS > 0.
    CLIENT_IP_HEADER: str = ""
    # OTP 3-strike lockout minutes. None → resolve via auth_lockout_minutes
    # (1 in qa/staging/DEBUG, else 5). Set AUTH_LOCKOUT_MINUTES to override.
    AUTH_LOCKOUT_MINUTES: int | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> str | list[str]:
        """Accept comma-separated strings, JSON lists, or real lists."""
        if value is None or value == "":
            return ""
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    return text
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            return text
        return [str(value).strip()]

    @field_validator("AUTO_APPROVE_EMAILS", mode="before")
    @classmethod
    def _parse_auto_approve_emails(cls, value: object) -> list[str]:
        """Accept JSON lists or comma-separated env strings."""
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [part.strip().lower() for part in value.split(",") if part.strip()]
        return []

    @property
    def auto_approve_email_set(self) -> set[str]:
        """Lowercased emails eligible for local auto-provisioning."""
        return set(self.AUTO_APPROVE_EMAILS)

    @property
    def is_production(self) -> bool:
        """True only for an explicitly production deployment."""
        return (self.ENVIRONMENT or "").strip().lower() == "production"

    @property
    def auth_lockout_minutes(self) -> int:
        """Resolved OTP lockout window after too many invalid codes.

        Returns:
            Explicit ``AUTH_LOCKOUT_MINUTES`` when set; otherwise 1 minute for
            qa/staging or DEBUG, and 5 minutes everywhere else.
        """
        if self.AUTH_LOCKOUT_MINUTES is not None:
            return max(1, int(self.AUTH_LOCKOUT_MINUTES))
        env = (self.ENVIRONMENT or "").strip().lower()
        if env in {"qa", "staging"} or self.DEBUG:
            return 1
        return 5

    @property
    def cors_origins_list(self) -> list[str]:
        """Configured CORS origins, whether stored as a list or a CSV string."""
        raw = self.CORS_ORIGINS
        if isinstance(raw, (list, tuple, set)):
            return [str(origin).strip().rstrip("/") for origin in raw if str(origin).strip()]
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return []
            if text.startswith("["):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    return [
                        str(origin).strip().rstrip("/")
                        for origin in parsed
                        if str(origin).strip()
                    ]
            return [
                origin.strip().rstrip("/") for origin in text.split(",") if origin.strip()
            ]
        return [str(raw).strip().rstrip("/")] if str(raw).strip() else []

    @staticmethod
    def _usable_secret(value: object) -> str:
        """Return a stripped secret, or ``""`` for blanks/placeholders.

        Args:
            value: Raw settings value.

        Returns:
            Usable secret string, or empty when unset / still a ``<placeholder>``.
        """
        text = str(value or "").strip().strip("\"'")
        if not text:
            return ""
        lowered = text.lower()
        if lowered.startswith("<") and lowered.endswith(">"):
            return ""
        if "your-" in lowered and "key" in lowered:
            return ""
        if "paste" in lowered or "replace" in lowered:
            return ""
        return text

    @staticmethod
    def _usable_public_base(value: object) -> str:
        """Return a public object-base URL, rejecting dashboard / console links.

        Args:
            value: Raw ``R2_PUBLIC_URL`` / ``STORAGE_PUBLIC_BASE_URL`` value.

        Returns:
            Stripped base URL, or empty when missing or not an object URL.
        """
        text = str(value or "").strip().strip("\"'").rstrip("/")
        if not text:
            return ""
        lowered = text.lower()
        if "/dashboard/" in lowered or "supabase.com/dashboard" in lowered:
            return ""
        if not lowered.startswith("http://") and not lowered.startswith("https://"):
            return ""
        return text

    @property
    def supabase_logo_storage_configured(self) -> bool:
        """True when logos can upload via the Supabase Storage client."""
        return bool(
            self._usable_secret(self.SUPABASE_URL)
            and self._usable_secret(self.SUPABASE_SERVICE_ROLE_KEY)
            and str(self.SUPABASE_LOGO_BUCKET or "").strip()
        )

    @property
    def r2_configured(self) -> bool:
        """True when S3-compatible credentials for object storage are present."""
        return bool(
            self._usable_secret(self.R2_ACCESS_KEY_ID)
            and self._usable_secret(self.R2_SECRET_ACCESS_KEY)
            and self._usable_secret(self.R2_ENDPOINT_URL)
            and str(self.R2_BUCKET_NAME or "").strip()
        )

    @property
    def s3_logo_storage_configured(self) -> bool:
        """True when logos can upload via the S3/R2 client + public URL base."""
        return bool(self.r2_configured and self._usable_public_base(self.R2_PUBLIC_URL))

    @property
    def missing_logo_storage_settings(self) -> list[str]:
        """Env var names required for public logo uploads that are currently blank.

        Prefers Supabase Storage (``SUPABASE_URL`` + service role + bucket). When
        that path is incomplete, falls back to listing the S3/R2 vars so either
        backend can satisfy the guard.

        Returns:
            Ordered list of missing setting names. Empty when either Supabase or
            S3 logo storage is fully configured.
        """
        if self.supabase_logo_storage_configured or self.s3_logo_storage_configured:
            return []

        missing: list[str] = []
        if not self._usable_secret(self.SUPABASE_URL):
            missing.append("SUPABASE_URL")
        if not self._usable_secret(self.SUPABASE_SERVICE_ROLE_KEY):
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        if not str(self.SUPABASE_LOGO_BUCKET or "").strip():
            missing.append("SUPABASE_LOGO_BUCKET")
        # Surface the S3 fallback gaps so operators who prefer R2/S3 know what to set.
        if not self._usable_secret(self.R2_ACCESS_KEY_ID):
            missing.append("AWS_S3_ACCESS_KEY_ID")
        if not self._usable_secret(self.R2_SECRET_ACCESS_KEY):
            missing.append("AWS_S3_SECRET_ACCESS_KEY")
        if not self._usable_secret(self.R2_ENDPOINT_URL):
            missing.append("AWS_S3_ENDPOINT_URL")
        if not str(self.R2_BUCKET_NAME or "").strip():
            missing.append("AWS_STORAGE_BUCKET_NAME")
        if not self._usable_public_base(self.R2_PUBLIC_URL):
            missing.append("STORAGE_PUBLIC_BASE_URL")
        return missing

    @property
    def missing_r2_logo_settings(self) -> list[str]:
        """Backward-compatible alias for ``missing_logo_storage_settings``."""
        return self.missing_logo_storage_settings

    @property
    def r2_reports_configured(self) -> bool:
        """True when a dedicated private bucket for candidate reports is configured."""
        return bool(self.r2_configured and self.R2_REPORTS_BUCKET_NAME.strip())

    @property
    def r2_public_base(self) -> str:
        """Public base URL for S3/R2 objects (no trailing slash)."""
        return self._usable_public_base(self.R2_PUBLIC_URL)

    @property
    def supabase_logo_public_base(self) -> str:
        """Public Storage object base for logos (no trailing slash).

        Returns:
            ``{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_LOGO_BUCKET}``.
        """
        base = str(self.SUPABASE_URL or "").rstrip("/")
        bucket = str(self.SUPABASE_LOGO_BUCKET or "").strip()
        if not base or not bucket:
            return ""
        return f"{base}/storage/v1/object/public/{bucket}"

    @property
    def admin_notification_email(self) -> str:
        """Resolved admin inbox for beta / ops notifications."""
        return (self.BETA_ACCESS_ADMIN_EMAIL or self.ADMIN_NOTIFICATION_EMAIL or "").strip()

    @property
    def email_configured(self) -> bool:
        """True when SES credentials and a from-address are available.

        Explicit access-key credentials are required for the configured check so
        local/CI without AWS stays offline. Deployments using an IAM role can
        still set the key env vars from the instance profile export, or set
        ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` in the service env.
        """
        return bool(
            (self.AWS_REGION or "").strip()
            and (self.EMAIL_FROM or "").strip()
            and (self.AWS_ACCESS_KEY_ID or "").strip()
            and (self.AWS_SECRET_ACCESS_KEY or "").strip()
        )


settings = Settings()
