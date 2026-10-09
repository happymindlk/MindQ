from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, NoDecode


class Settings(BaseSettings):
    PROJECT_NAME: str = "MindQ Psychometric Assessment Platform"
    # Default True so local/CI boots with example secrets. Production MUST set DEBUG=false
    # (assert_production_ready refuses weak secrets / localhost CORS when False).
    DEBUG: bool = True

    # Postgres (async driver). Defaults to the local Supabase stack.
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres"

    # Secret used to SIGN candidate access tokens (distinct from Supabase's JWT secret).
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    CANDIDATE_TOKEN_TTL_MINUTES: int = 240
    # Candidate login requires a Supabase email-OTP access token. Only disable for
    # local scripts without Supabase; assert_production_ready refuses False in prod.
    CANDIDATE_OTP_REQUIRED: bool = True
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

    # Resend transactional email.
    RESEND_API_KEY: str | None = None
    EMAIL_FROM: str = "Assess Pulse <onboarding@resend.dev>"
    # Inbox for gated beta / waitlist access requests (and other admin alerts).
    ADMIN_NOTIFICATION_EMAIL: str = "muhamadnas44@gmail.com"
    # Legacy alias — prefer ADMIN_NOTIFICATION_EMAIL.
    BETA_ACCESS_ADMIN_EMAIL: str = ""
    # Comma-separated emails that skip waitlist and auto-provision into the
    # local "acme" test tenant (e.g. "dev@example.com,qa@example.com").
    # NoDecode: pydantic-settings otherwise JSON-parses list env values first.
    AUTO_APPROVE_EMAILS: Annotated[list[str], NoDecode] = []
    # Public origin of the React app (no trailing slash). Invite emails link to
    # `{FRONTEND_URL}/assessment?code=…`.
    FRONTEND_URL: str = "http://localhost:5173"
    # Candidate-facing portal URL used in notification emails.
    PORTAL_URL: str = "http://localhost:5173/portal"

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

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

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
    def r2_public_base(self) -> str:
        """Public base URL for objects (no trailing slash)."""
        return (self.R2_PUBLIC_URL or "").rstrip("/")

    @property
    def admin_notification_email(self) -> str:
        """Resolved admin inbox for beta / ops notifications."""
        return (self.BETA_ACCESS_ADMIN_EMAIL or self.ADMIN_NOTIFICATION_EMAIL or "").strip()

    @property
    def resend_configured(self) -> bool:
        """True when a Resend API key is available for outbound mail."""
        return bool(self.RESEND_API_KEY)


settings = Settings()
