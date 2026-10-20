"""Production security helpers: fail-closed config, rate limits, response headers."""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings, settings as app_settings

logger = logging.getLogger("app.security")

# Known weak defaults shipped in .env.example / local stacks. Production must not use these.
_INSECURE_SECRET_KEYS = frozenset(
    {
        "dev-secret-key-change-in-production",
        "changeme",
        "secret",
        "password",
    }
)
_INSECURE_JWT_SECRETS = frozenset(
    {
        "super-secret-jwt-token-with-at-least-32-characters-long",
        "your-super-secret-jwt-token-with-at-least-32-characters-long",
    }
)


def assert_production_ready(settings: Settings) -> None:
    """Refuse to boot when DEBUG is off and secrets / CORS look like local defaults.

    Args:
        settings: Loaded application settings.

    Raises:
        RuntimeError: When production configuration is unsafe.
    """
    if settings.DEBUG:
        return

    errors: list[str] = []
    secret = (settings.SECRET_KEY or "").strip()
    if secret in _INSECURE_SECRET_KEYS or len(secret) < 32:
        errors.append(
            "SECRET_KEY must be a unique value of at least 32 characters "
            "(not the .env.example default) when DEBUG=false"
        )

    jwt_secret = (settings.SUPABASE_JWT_SECRET or "").strip()
    if jwt_secret in _INSECURE_JWT_SECRETS or len(jwt_secret) < 32:
        errors.append(
            "SUPABASE_JWT_SECRET must be a unique value of at least 32 characters "
            "(not the local supabase default) when DEBUG=false"
        )

    origins = settings.cors_origins_list
    if not origins:
        errors.append("CORS_ORIGINS must list at least one allowed origin when DEBUG=false")
    elif any(o == "*" or "*" in o for o in origins):
        # Starlette reflects the caller's Origin for "*" when credentials are allowed.
        errors.append("CORS_ORIGINS must not contain wildcards when DEBUG=false")
    elif any(o.startswith("http://") and "localhost" not in o and "127.0.0.1" not in o for o in origins):
        errors.append("CORS_ORIGINS must use https:// for non-local origins when DEBUG=false")
    else:
        localhost_only = all(
            o.startswith("http://localhost") or o.startswith("http://127.0.0.1")
            for o in origins
        )
        if localhost_only:
            errors.append(
                "CORS_ORIGINS must include the production frontend origin "
                "(not localhost-only) when DEBUG=false"
            )

    reports_bucket = settings.R2_REPORTS_BUCKET_NAME.strip()
    if reports_bucket and reports_bucket == settings.R2_BUCKET_NAME.strip() and settings.r2_public_base:
        errors.append(
            "R2_REPORTS_BUCKET_NAME must be a private bucket distinct from the public "
            "logo bucket (R2_BUCKET_NAME) when DEBUG=false"
        )

    if errors:
        raise RuntimeError("Unsafe production configuration:\n- " + "\n- ".join(errors))


class RateLimiter:
    """In-process fixed-window rate limiter.

    Suitable for a single FastAPI worker. When running multiple instances, back
    this with a shared store (Redis) — counters otherwise multiply by instance count.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def reset(self) -> None:
        """Clear all buckets (tests only)."""
        with self._lock:
            self._hits.clear()

    def check(self, key: str) -> None:
        """Raise HTTP 429 when ``key`` exceeds the window budget.

        Args:
            key: Client identity (usually IP + route bucket).

        Raises:
            HTTPException: Status 429 when the limit is exceeded.
        """
        now = time.monotonic()
        with self._lock:
            bucket = list(self._hits.get(key, []))
            cutoff = now - self.window_seconds
            kept = [t for t in bucket if t > cutoff]
            if len(kept) >= self.max_requests:
                self._hits[key] = kept
                raise HTTPException(status_code=429, detail="Too many requests. Try again later.")
            kept.append(now)
            self._hits[key] = kept


# Auth-adjacent: ~10 attempts / 15 minutes (OWASP-style).
login_limiter = RateLimiter(max_requests=10, window_seconds=15 * 60)
# Public capability URLs / spam surfaces: 60 / minute per IP.
public_limiter = RateLimiter(max_requests=60, window_seconds=60)
# Endpoints that can trigger paid Gemini calls or PDF rendering (denial-of-wallet).
report_limiter = RateLimiter(max_requests=20, window_seconds=10 * 60)
# Outbound email triggers (nudges, invites): stop HR accounts being used as a spam relay.
email_limiter = RateLimiter(max_requests=30, window_seconds=60 * 60)
# Admin password step. Each accepted attempt can send mail, so this is separate
# from candidate/client login. Per-address send caps live in Postgres.
admin_otp_limiter = RateLimiter(max_requests=10, window_seconds=15 * 60)
# OTP guesses. The 3-strike lock is stored on the challenge row; this only
# slows a single IP that is cycling stolen temp tokens.
admin_otp_verify_limiter = RateLimiter(max_requests=20, window_seconds=15 * 60)
# Candidate OTP request/verify mirror the admin budgets; per-email send caps
# and the 3-strike lock live on the challenge row.
candidate_otp_limiter = RateLimiter(max_requests=10, window_seconds=15 * 60)
candidate_otp_verify_limiter = RateLimiter(max_requests=20, window_seconds=15 * 60)
# Invites are legitimately bulk (a hiring round), so the budget is higher than nudges.
invite_limiter = RateLimiter(max_requests=200, window_seconds=60 * 60)


def client_ip(request: Request, config: Settings | None = None) -> str:
    """Resolve the caller's IP without trusting client-forgeable headers.

    ``X-Forwarded-For`` is only read when ``TRUSTED_PROXY_HOPS`` > 0, and then
    the entry appended by the outermost trusted proxy is used (not the
    left-most, which the client controls).

    Args:
        request: Incoming request.
        config: Settings override (tests); defaults to the app settings.

    Returns:
        Client IP string, or ``"unknown"``.
    """
    cfg = config or app_settings
    peer = request.client.host if request.client and request.client.host else "unknown"
    hops = max(0, int(cfg.TRUSTED_PROXY_HOPS))
    if hops == 0:
        return peer
    header_name = (cfg.CLIENT_IP_HEADER or "").strip()
    if header_name:
        edge_ip = (request.headers.get(header_name) or "").strip()
        if edge_ip:
            return edge_ip
    forwarded = [p.strip() for p in (request.headers.get("x-forwarded-for") or "").split(",") if p.strip()]
    if len(forwarded) >= hops:
        return forwarded[-hops]
    return peer


def enforce_rate_limit(limiter: RateLimiter, request: Request, bucket: str) -> None:
    """Apply a named rate-limit bucket to the current request.

    Args:
        limiter: Limiter instance (login vs public).
        request: Incoming FastAPI request.
        bucket: Logical route group (e.g. ``candidate_login``).
    """
    limiter.check(f"{bucket}:{client_ip(request)}")


def enforce_user_rate_limit(limiter: RateLimiter, principal: object, bucket: str) -> None:
    """Apply a named rate-limit bucket keyed by an authenticated principal.

    Keying on the user id (not IP) means rotating IPs cannot multiply the
    budget for an authenticated account.

    Args:
        limiter: Limiter instance.
        principal: Authenticated identity (UUID or str).
        bucket: Logical route group (e.g. ``report_download``).
    """
    limiter.check(f"{bucket}:user:{principal}")


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class SecurityHeadersMiddleware:
    """Pure ASGI middleware: security headers + request id (no BaseHTTPMiddleware).

    BaseHTTPMiddleware breaks BackgroundTasks / StreamingResponse in Starlette;
    this implementation wraps ``send`` only.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _header_value(scope, b"x-request-id") or str(uuid.uuid4())
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id
        else:
            setattr(state, "request_id", request_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if scope.get("scheme") == "https":
                    headers.setdefault(
                        "Strict-Transport-Security",
                        "max-age=31536000; includeSubDomains",
                    )
                headers["X-Request-Id"] = request_id
            await send(message)

        await self.app(scope, receive, send_wrapper)


def _header_value(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return None
