import json
from typing import Annotated

from pydantic import field_validator
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

    # Supabase settings (server-side). Auth/DB only — report archives use R2.
    SUPABASE_URL: str = "http://127.0.0.1:54321"
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    # Verifies HR access tokens minted by Supabase Auth (HS256).
    SUPABASE_JWT_SECRET: str = "super-secret-jwt-token-with-at-least-32-characters-long"

    # Cloudflare R2 (S3-compatible). ENDPOINT is the S3 API host; PUBLIC_URL is the
    # public bucket/CDN base used for logos (and other publicly readable objects).
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_ENDPOINT_URL: str = ""
    R2_BUCKET_NAME: str = "assess-pulse"
    R2_PUBLIC_URL: str = ""
    # Candidate reports contain PII + psychometric results, so they must never share
    # the publicly readable logo bucket. Blank disables report archiving entirely.
    R2_REPORTS_BUCKET_NAME: str = ""
    REPORT_URL_TTL_SECONDS: int = 900

    # AWS SES transactional email (boto3). Credentials may come from env keys
    # or the default AWS credential chain (IAM role, shared config, …).
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    EMAIL_FROM: str = "MindQ <noreply@mindqtalent.com>"
    # Inbox for gated beta / waitlist access requests (and other admin alerts).
    ADMIN_NOTIFICATION_EMAIL: str = "muhamadnas44@gmail.com"
    # Legacy alias — prefer ADMIN_NOTIFICATION_EMAIL.
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
    # New Gemini API keys cannot call gemini-2.5-*; Google returns 404 NOT_FOUND.
    GEMINI_MODEL: str = "gemini-3.5-flash"
    # Comma-separated chain tried in order once a model exhausts retries on 429/503.
    # Each has its own capacity pool and free-tier daily quota; all must be callable
    # by this key (gemini-2.5-* returns 404). Blank disables fallback.
    GEMINI_FALLBACK_MODELS: str = "gemini-3.6-flash,gemini-3.5-flash-lite"
    # Soft timeout so submit/report never hang forever on a slow Gemini call.
    GEMINI_TIMEOUT_SECONDS: float = 45.0
    # Total generate_content attempts per model (free-tier 429 / transient errors).
    GEMINI_MAX_RETRIES: int = 3
    # Background jobs have no user waiting, so they ride out capacity spikes longer.
    GEMINI_BACKGROUND_MAX_RETRIES: int = 5
    GEMINI_RETRY_BASE_SECONDS: float = 2.0
    GEMINI_RETRY_MAX_DELAY_SECONDS: float = 30.0
    # Pause between sequential custom-technical item grades (RPM throttle).
    GEMINI_INTER_REQUEST_SECONDS: float = 2.0
    # Incomplete candidates older than this many hours are nudged by the job.
    NUDGE_AFTER_HOURS: int = 24

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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

    @property
    def r2_configured(self) -> bool:
        """True when all R2 credentials needed for object storage are present."""
        return bool(
            self.R2_ACCESS_KEY_ID
            and self.R2_SECRET_ACCESS_KEY
            and self.R2_ENDPOINT_URL
            and self.R2_BUCKET_NAME
        )

    @property
    def r2_reports_configured(self) -> bool:
        """True when a dedicated private bucket for candidate reports is configured."""
        return bool(self.r2_configured and self.R2_REPORTS_BUCKET_NAME.strip())

    @property
    def r2_public_base(self) -> str:
        """Public base URL for objects (no trailing slash)."""
        return (self.R2_PUBLIC_URL or "").rstrip("/")

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
