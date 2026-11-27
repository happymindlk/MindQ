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


def production_config_warnings(settings: Settings) -> list[str]:
    """Risky-but-bootable settings, logged as warnings at startup (P1-14/15).

    These are warnings, not boot refusals, so servers deployed before the
    variables were documented keep serving. Set them, then they go quiet.

    Args:
        settings: Loaded application settings.

    Returns:
        Human-readable warning messages (empty when the config is clean).
    """
    from urllib.parse import urlparse

    from app.config import KNOWN_ENVIRONMENTS

    warnings: list[str] = []
    env = (settings.ENVIRONMENT or "").strip().lower()
    if env not in KNOWN_ENVIRONMENTS:
        warnings.append(
            f"ENVIRONMENT={settings.ENVIRONMENT!r} is not one of "
            f"{sorted(KNOWN_ENVIRONMENTS)}; it is treated as non-production"
        )
    if settings.is_production and settings.DEBUG:
        warnings.append(
            "ENVIRONMENT=production with DEBUG=true: API docs are public and "
            "weak-secret checks are skipped; set DEBUG=false"
        )
    if not settings.DEBUG:
        if env == "development":
            warnings.append(
                "DEBUG=false but ENVIRONMENT is unset ('development'); set "
                "ENVIRONMENT=production (or qa/staging) explicitly"
            )
        frontend = (settings.FRONTEND_URL or "").strip()
        host = (urlparse(frontend).hostname or "").lower()
        if not frontend:
            warnings.append(
                "FRONTEND_URL is not set; invite links fall back to the default "
                "Pages URL in production. Set FRONTEND_URL to the public app origin"
            )
        elif host in {"localhost", "127.0.0.1", "0.0.0.0"}:
            warnings.append(f"FRONTEND_URL={frontend!r} points at localhost with DEBUG=false")
    return warnings


def assert_production_ready(settings: Settings) -> None:
    """Refuse to boot when DEBUG is off and secrets / CORS look like local defaults.

    Args:
        settings: Loaded application settings.

    Raises:
        RuntimeError: When production configuration is unsafe.
    """
    for message in production_config_warnings(settings):
        logger.warning(message, extra={"event": "unsafe_config_warning"})
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
    public_logo_buckets = {
        name
        for name in (
            (settings.R2_BUCKET_NAME or "").strip(),
            (settings.SUPABASE_LOGO_BUCKET or "").strip(),
        )
        if name
    }
    if reports_bucket and reports_bucket in public_logo_buckets and (
        settings.r2_public_base or settings.supabase_logo_public_base
    ):
        errors.append(
            "R2_REPORTS_BUCKET_NAME must be a private bucket distinct from the public "
            "logo bucket (SUPABASE_LOGO_BUCKET / R2_BUCKET_NAME) when DEBUG=false"
        )

    if errors:
        raise RuntimeError("Unsafe production configuration:\n- " + "\n- ".join(errors))

    if not settings.redis_url_has_password:
        # Warning, not a boot refusal, so a deploy that predates Redis auth
        # keeps serving. Rotate REDIS_URL to redis://:<password>@host ASAP.
        logger.warning(
            "REDIS_URL has no password; Redis must require auth because ARQ "
            "unpickles job payloads (see docker-compose.yml / DEPLOYMENT.md)",
            extra={"event": "redis_unauthenticated"},
        )


def _retry_after_seconds(oldest: float, window_seconds: float, now: float) -> int:
    """Seconds until the oldest hit falls out of the window (at least 1)."""
    return max(1, int(window_seconds - (now - oldest)) + 1)


def _raise_too_many_requests(
    *,
    detail: str,
    retry_after: int,
    bucket: str,
    identity: str,
) -> None:
    """Log a blocked auth attempt and raise HTTP 429 with Retry-After."""
    logger.warning(
        "auth_rate_limited",
        extra={
            "event": "auth_rate_limited",
            "bucket": bucket,
            "identity": identity,
            "retry_after": retry_after,
            "detail": detail,
        },
    )
    raise HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )


# ---------------------------------------------------------------------------
# Shared rate-limit store (Redis)
# ---------------------------------------------------------------------------
#
# Limiters keep a synchronous API (``check`` / ``assert_allowed`` / ...) so
# every route call site stays unchanged. When a Redis store is configured
# (``configure_rate_limit_store`` at app startup) budgets are shared across
# every worker and node; otherwise, and for 30s after any Redis error, they
# fall back to a per-process window. Redis calls use 250ms timeouts, so a
# Redis problem costs at most one short stall before the breaker opens.

# Sliding-window log in a sorted set. Atomic, uses Redis' clock (immune to
# app-node skew), and sets a TTL so idle keys evict themselves.
#   mode "hit":   count, refuse at max, else record this hit
#   mode "peek":  count only (AuthFailureLimiter.assert_allowed)
#   mode "add":   record without checking (AuthFailureLimiter.record_failure)
# Returns {allowed (1/0), count, oldest_score_ms, now_ms}.
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local window_ms = tonumber(ARGV[1])
local max_hits = tonumber(ARGV[2])
local mode = ARGV[3]
local member = ARGV[4]
local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', key, '-inf', now_ms - window_ms)
local count = redis.call('ZCARD', key)
if mode ~= 'add' and count >= max_hits then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  return {0, count, tonumber(oldest[2]) or now_ms, now_ms}
end
if mode ~= 'peek' then
  redis.call('ZADD', key, now_ms, member)
  redis.call('PEXPIRE', key, window_ms)
  count = count + 1
end
return {1, count, 0, now_ms}
"""

_KEY_PREFIX = "mindq:rl:"
_BREAKER_SECONDS = 30.0


class _RateLimitStore:
    """Process-wide handle to the shared Redis store with a circuit breaker."""

    def __init__(self) -> None:
        self.client = None
        self._script = None
        self._down_until = 0.0

    def configure(self, client) -> None:
        self.client = client
        self._script = client.register_script(_SLIDING_WINDOW_LUA) if client else None
        self._down_until = 0.0

    def run(self, key: str, window_seconds: float, max_hits: int, mode: str):
        """Run the window script; ``None`` means "use the local fallback"."""
        if self._script is None or time.monotonic() < self._down_until:
            return None
        try:
            allowed, count, oldest_ms, now_ms = self._script(
                keys=[_KEY_PREFIX + key],
                args=[int(window_seconds * 1000), int(max_hits), mode, uuid.uuid4().hex],
            )
            return int(allowed), int(count), float(oldest_ms), float(now_ms)
        except Exception as exc:  # redis.RedisError, timeouts, script errors
            self._down_until = time.monotonic() + _BREAKER_SECONDS
            logger.warning(
                "rate_limit_store_unavailable",
                extra={
                    "event": "rate_limit_store_unavailable",
                    "error_type": type(exc).__name__,
                    "fallback_seconds": _BREAKER_SECONDS,
                },
            )
            return None

    def delete(self, key: str) -> None:
        if self.client is None or time.monotonic() < self._down_until:
            return
        try:
            self.client.delete(_KEY_PREFIX + key)
        except Exception:
            self._down_until = time.monotonic() + _BREAKER_SECONDS


_store = _RateLimitStore()


def configure_rate_limit_store(redis_url: str | None) -> bool:
    """Point every limiter at a shared Redis (call once at app startup).

    Args:
        redis_url: ``REDIS_URL``; ``None`` / empty keeps per-process limits.

    Returns:
        True when the shared store is active.
    """
    if not redis_url:
        _store.configure(None)
        return False
    import redis

    client = redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
        health_check_interval=30,
    )
    _store.configure(client)
    logger.info("rate_limit_store_configured", extra={"event": "rate_limit_store_configured"})
    return True


def disable_rate_limit_store() -> None:
    """Return to per-process limits (shutdown / tests)."""
    client = _store.client
    _store.configure(None)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def _retry_after_ms(oldest_ms: float, window_seconds: float, now_ms: float) -> int:
    return max(1, int((window_seconds * 1000 - (now_ms - oldest_ms)) / 1000) + 1)


# Local fallback: drop idle keys once a dict grows past this many entries.
_LOCAL_PRUNE_THRESHOLD = 5000


def _prune_local(hits: dict[str, list[float]], now: float, window_seconds: float) -> None:
    """Evict keys whose newest hit is outside the window (caller holds lock)."""
    if len(hits) < _LOCAL_PRUNE_THRESHOLD:
        return
    cutoff = now - window_seconds
    for key in [k for k, v in hits.items() if not v or v[-1] <= cutoff]:
        hits.pop(key, None)


class RateLimiter:
    """Sliding-window rate limiter shared across workers/nodes via Redis.

    Falls back to a per-process window when no Redis store is configured or
    Redis is failing (see ``configure_rate_limit_store``).
    """

    def __init__(self, max_requests: int, window_seconds: float, *, name: str = "") -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.name = name or f"rl{id(self)}"
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def reset(self) -> None:
        """Clear all local buckets (tests only)."""
        with self._lock:
            self._hits.clear()

    def check(self, key: str) -> None:
        """Raise HTTP 429 when ``key`` exceeds the window budget.

        Args:
            key: Client identity (usually route bucket + IP or user id).

        Raises:
            HTTPException: Status 429 when the limit is exceeded.
        """
        bucket = key.split(":", 1)[0] if ":" in key else key
        shared = _store.run(f"{self.name}:{key}", self.window_seconds, self.max_requests, "hit")
        if shared is not None:
            allowed, _count, oldest_ms, now_ms = shared
            if not allowed:
                _raise_too_many_requests(
                    detail="Too many requests. Try again later.",
                    retry_after=_retry_after_ms(oldest_ms, self.window_seconds, now_ms),
                    bucket=bucket,
                    identity=key,
                )
            return

        now = time.monotonic()
        with self._lock:
            _prune_local(self._hits, now, self.window_seconds)
            cutoff = now - self.window_seconds
            kept = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(kept) >= self.max_requests:
                self._hits[key] = kept
                oldest = min(kept) if kept else now
                _raise_too_many_requests(
                    detail="Too many requests. Try again later.",
                    retry_after=_retry_after_seconds(oldest, self.window_seconds, now),
                    bucket=bucket,
                    identity=key,
                )
            kept.append(now)
            self._hits[key] = kept


class AuthFailureLimiter:
    """Sliding-window counter for failed auth attempts (wrong password/OTP).

    Call :meth:`assert_allowed` before processing a request so identities that
    already burned the budget get 429, and :meth:`record_failure` on each
    failure. Failures expire with the window; a success does not wipe them,
    so one valid account cannot reset the budget for a shared IP.
    """

    def __init__(self, max_failures: int, window_seconds: float, *, name: str = "") -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.name = name or f"af{id(self)}"
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def reset(self) -> None:
        """Clear all local buckets (tests only)."""
        with self._lock:
            self._hits.clear()

    def clear(self, key: str) -> None:
        """Drop recorded failures for ``key`` (admin unlock / tests)."""
        _store.delete(f"{self.name}:{key}")
        with self._lock:
            self._hits.pop(key, None)

    def assert_allowed(self, key: str) -> None:
        """Raise HTTP 429 when ``key`` already has too many recent failures.

        Args:
            key: Client identity (usually ``bucket:ip``).

        Raises:
            HTTPException: Status 429 when the failure budget is exhausted.
        """
        bucket = key.split(":", 1)[0] if ":" in key else key
        shared = _store.run(f"{self.name}:{key}", self.window_seconds, self.max_failures, "peek")
        if shared is not None:
            allowed, _count, oldest_ms, now_ms = shared
            if not allowed:
                _raise_too_many_requests(
                    detail="Too many failed login attempts. Try again later.",
                    retry_after=_retry_after_ms(oldest_ms, self.window_seconds, now_ms),
                    bucket=bucket,
                    identity=key,
                )
            return

        now = time.monotonic()
        with self._lock:
            kept = [t for t in self._hits.get(key, []) if t > now - self.window_seconds]
            self._hits[key] = kept
            if len(kept) >= self.max_failures:
                oldest = min(kept)
                _raise_too_many_requests(
                    detail="Too many failed login attempts. Try again later.",
                    retry_after=_retry_after_seconds(oldest, self.window_seconds, now),
                    bucket=bucket,
                    identity=key,
                )

    def record_failure(self, key: str) -> None:
        """Append a failed attempt for ``key`` inside the sliding window.

        Args:
            key: Client identity (usually ``bucket:ip``).
        """
        shared = _store.run(f"{self.name}:{key}", self.window_seconds, self.max_failures, "add")
        if shared is not None:
            count = shared[1]
        else:
            now = time.monotonic()
            with self._lock:
                _prune_local(self._hits, now, self.window_seconds)
                kept = [t for t in self._hits.get(key, []) if t > now - self.window_seconds]
                kept.append(now)
                self._hits[key] = kept
                count = len(kept)
        logger.info(
            "auth_failure_recorded",
            extra={
                "event": "auth_failure_recorded",
                "identity": key,
                "failure_count": count,
                "max_failures": self.max_failures,
            },
        )


# Candidate/HR verify IP shield: 5 attempts / minute (OWASP-style auth surface).
login_limiter = RateLimiter(max_requests=5, window_seconds=60, name="login_limiter")
# Public capability URLs / spam surfaces: 60 / minute per IP.
public_limiter = RateLimiter(max_requests=60, window_seconds=60, name="public_limiter")
# Endpoints that can trigger paid Gemini calls or PDF rendering (denial-of-wallet).
report_limiter = RateLimiter(max_requests=20, window_seconds=10 * 60, name="report_limiter")
# Bulk ZIP export packages many PDFs in one request; keep the budget tight so
# a single HR user cannot queue unbounded WeasyPrint work.
reports_zip_limiter = RateLimiter(max_requests=5, window_seconds=10 * 60, name="reports_zip_limiter")
# Report JSON views are database-only (Gemini runs in background tasks with
# its own cooldown), so they get a budget that covers narrative polling.
report_view_limiter = RateLimiter(max_requests=120, window_seconds=10 * 60, name="report_view_limiter")
# Outbound email triggers (nudges, invites): stop HR accounts being used as a spam relay.
email_limiter = RateLimiter(max_requests=30, window_seconds=60 * 60, name="email_limiter")
# Admin password step. Each accepted attempt can send mail, so this is separate
# from candidate/client login. Per-address send caps live in Postgres.
admin_otp_limiter = RateLimiter(max_requests=10, window_seconds=15 * 60, name="admin_otp_limiter")
# OTP guesses. The challenge-row lock is the primary control; this only
# slows a single IP that is cycling stolen temp tokens.
admin_otp_verify_limiter = RateLimiter(max_requests=20, window_seconds=15 * 60, name="admin_otp_verify_limiter")
# Forgot-password emails — keep tight to limit SES abuse / inbox flooding.
admin_forgot_password_limiter = RateLimiter(max_requests=5, window_seconds=15 * 60, name="admin_forgot_password_limiter")
# Candidate OTP request: 5 / minute per IP; email key uses the same budget.
candidate_otp_limiter = RateLimiter(max_requests=5, window_seconds=60, name="candidate_otp_limiter")
candidate_otp_email_limiter = RateLimiter(max_requests=5, window_seconds=60, name="candidate_otp_email_limiter")
# Candidate OTP verify IP burst shield; consecutive wrong codes lock on the row.
candidate_otp_verify_limiter = RateLimiter(max_requests=20, window_seconds=60, name="candidate_otp_verify_limiter")
# HR/client OTP send: 5 / minute per IP (inbox flooding / bot spam).
hr_otp_limiter = RateLimiter(max_requests=5, window_seconds=60, name="hr_otp_limiter")
hr_otp_verify_limiter = RateLimiter(max_requests=20, window_seconds=60, name="hr_otp_verify_limiter")
# HR login failures: 5 wrong OTP submits / minute / IP before 429.
hr_login_failure_limiter = AuthFailureLimiter(max_failures=5, window_seconds=60, name="hr_login_failure_limiter")
# Invites are legitimately bulk (a hiring round), so the budget is higher than nudges.
invite_limiter = RateLimiter(max_requests=200, window_seconds=60 * 60, name="invite_limiter")


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
