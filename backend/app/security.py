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

from app.config import Settings

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

    if not settings.CANDIDATE_OTP_REQUIRED:
        errors.append("CANDIDATE_OTP_REQUIRED must be true when DEBUG=false")

    origins = settings.cors_origins_list
    if not origins:
        errors.append("CORS_ORIGINS must list at least one allowed origin when DEBUG=false")
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


def client_ip(request: Request) -> str:
    """Best-effort client IP (honors first X-Forwarded-For hop when present)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_rate_limit(limiter: RateLimiter, request: Request, bucket: str) -> None:
    """Apply a named rate-limit bucket to the current request.

    Args:
        limiter: Limiter instance (login vs public).
        request: Incoming FastAPI request.
        bucket: Logical route group (e.g. ``candidate_login``).
    """
    limiter.check(f"{bucket}:{client_ip(request)}")


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
