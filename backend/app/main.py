import asyncio
import contextlib
import json
import logging
import re
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from starlette.datastructures import MutableHeaders
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1.beta_access import router as beta_access_router
from app.api.v1.invites import router as invites_router
from app.api.v1.router import api_router
from app.config import settings
from app.database import engine
from app.exceptions import (
    is_deadlock_error,
    is_schema_drift_error,
    is_transient_db_error,
    schema_drift_detail,
)
from app.jobs.settings import close_arq_pool, get_arq_pool, open_arq_pool
from app.observability import configure_logging
from app.sentry_init import init_sentry
from app.services.gemini_client import shutdown_gemini_executor
from app.security import (
    SecurityHeadersMiddleware,
    assert_production_ready,
    configure_rate_limit_store,
    disable_rate_limit_store,
)
from app.services.assessment_expiry import run_expiry_sweep_loop

configure_logging(debug=settings.DEBUG)
# Sentry was defined but never initialized; no-op unless SENTRY_DSN is set.
init_sentry(settings)
logger = logging.getLogger("app.main")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate production config, warm DB + ARQ pools, then dispose on shutdown.

    The database schema is managed by Supabase migrations (supabase/migrations),
    applied via `supabase db reset` / `supabase migration up` - never by
    metadata.create_all.
    """
    assert_production_ready(settings)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("db_pool_warmed", extra={"event": "db_pool_warmed"})
    except Exception:
        # Do not block process boot if Postgres is briefly unreachable; the first
        # request path still uses pool_pre_ping + retry helpers.
        logger.warning("db_pool_warmup_failed", exc_info=True, extra={"event": "db_pool_warmup_failed"})
    arq_pool = await open_arq_pool()
    if arq_pool is not None:
        # Same Redis as ARQ: share rate-limit budgets across workers and nodes.
        configure_rate_limit_store(settings.REDIS_URL)
    stop_expiry = asyncio.Event()
    expiry_task: asyncio.Task | None = None
    if arq_pool is None:
        # Dev/CI without Redis only (production refuses to boot without it):
        # nothing else would finalize abandoned timed attempts. With Redis the
        # ARQ worker cron is the single sweeper.
        expiry_task = asyncio.create_task(
            run_expiry_sweep_loop(stop_event=stop_expiry),
            name="assessment-expiry-sweep",
        )
    logger.info(
        "app_started",
        extra={"event": "app_started", "debug": settings.DEBUG},
    )
    try:
        yield
    finally:
        stop_expiry.set()
        if expiry_task is not None:
            expiry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await expiry_task
        disable_rate_limit_store()
        shutdown_gemini_executor()
        await close_arq_pool()
        await engine.dispose()
        logger.info("app_stopped", extra={"event": "app_stopped"})


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="MindQ Psychometric Assessment Platform API — Create, administer, and analyze psychological assessments.",
    version="1.0.0",
    lifespan=lifespan,
    # The schema maps every route and payload; only expose it on dev stacks.
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# ---------------------------------------------------------------------------
# CORS / origin resolution (single source of truth for middleware + errors)
# ---------------------------------------------------------------------------

#: Hosted origins that must always work, in every environment.
DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = (
    "https://qa.app.mindqtalent.com",
    "https://mindq.pages.dev",
)

#: Local dev servers. Never allowed when ``ENVIRONMENT=production``: with
#: ``allow_credentials=True`` any page on the user's machine could otherwise
#: call the API as them.
LOCAL_DEV_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
)

#: https subdomains of our own zones only, e.g. ``https://qa.app.mindqtalent.com``
#: and ``https://feat-x.mindq.pages.dev`` (Cloudflare Pages preview builds).
#: Pinned to the ``mindq`` Pages project: anyone can deploy to *.pages.dev,
#: and these origins receive credentialed CORS.
MINDQTALENT_ORIGIN_REGEX = r"^https://([a-z0-9-]+\.)+mindqtalent\.com$"
PAGES_DEV_ORIGIN_REGEX = r"^https://([a-z0-9-]+\.)?mindq\.pages\.dev$"
ALLOW_ORIGIN_REGEX = f"{MINDQTALENT_ORIGIN_REGEX}|{PAGES_DEV_ORIGIN_REGEX}"

_allow_origin_pattern = re.compile(ALLOW_ORIGIN_REGEX)


def _normalize_origin(value: object) -> str:
    """Normalize one origin entry (strip whitespace / trailing slash)."""
    return str(value).strip().rstrip("/")


def _coerce_origins(value: object) -> list[str]:
    """Coerce a list, CSV string, or JSON-list string into origin strings.

    Args:
        value: Raw ``CORS_ORIGINS`` / ``FRONTEND_URL`` value in any shape.

    Returns:
        Normalized, non-empty origins (not yet deduplicated).
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        origins: list[str] = []
        for item in value:
            origin = _normalize_origin(item)
            if origin:
                origins.append(origin)
        return origins
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return _coerce_origins(parsed)
        return [
            origin
            for part in text.split(",")
            if (origin := _normalize_origin(part))
        ]
    origin = _normalize_origin(value)
    return [origin] if origin else []


def _build_allowed_origins() -> list[str]:
    """Unified allowlist: settings (list or CSV) + FRONTEND_URL + defaults.

    Localhost origins are added only outside production, and stripped in
    production even when ``CORS_ORIGINS`` lists them.
    """
    candidates: list[str] = []
    # `cors_origins_list` already normalizes list/CSV; reading the raw value
    # too keeps this correct if settings are monkeypatched with either shape.
    candidates.extend(_coerce_origins(getattr(settings, "CORS_ORIGINS", None)))
    if hasattr(settings, "cors_origins_list"):
        candidates.extend(_coerce_origins(settings.cors_origins_list))
    candidates.extend(_coerce_origins(getattr(settings, "FRONTEND_URL", None)))
    candidates.extend(DEFAULT_ALLOWED_ORIGINS)
    production = bool(getattr(settings, "is_production", False))
    if not production:
        candidates.extend(LOCAL_DEV_ORIGINS)

    seen: set[str] = set()
    origins: list[str] = []
    for origin in candidates:
        if production and _is_local_origin(origin):
            continue  # even if CORS_ORIGINS lists it
        if origin not in seen:
            seen.add(origin)
            origins.append(origin)
    return origins


def _is_local_origin(origin: str) -> bool:
    """True for http(s)://localhost / 127.0.0.1 origins on any port."""
    host = origin.split("://", 1)[-1].split(":", 1)[0].split("/", 1)[0].lower()
    return host in {"localhost", "127.0.0.1", "[::1]", "0.0.0.0"}


allowed_origins: list[str] = _build_allowed_origins()


def is_origin_allowed(origin: str | None) -> bool:
    """Unified origin check used by CORSMiddleware config and error handlers.

    Args:
        origin: Raw ``Origin`` header value, if present.

    Returns:
        True for an exact allowlist match or a ``mindqtalent.com`` /
        ``pages.dev`` https-subdomain regex match.
    """
    if not origin:
        return False
    normalized = _normalize_origin(origin)
    # Rebuild from live settings so env / test overrides are honoured, not
    # only the import-time snapshot used to configure CORSMiddleware.
    if normalized in allowed_origins or normalized in _build_allowed_origins():
        return True
    return _allow_origin_pattern.fullmatch(normalized) is not None


class ProcessTimeMiddleware:
    """Pure ASGI middleware: attach ``X-Process-Time`` and log slow requests.

    Implemented as pure ASGI (not ``@app.middleware("http")`` /
    ``BaseHTTPMiddleware``) so BackgroundTasks and StreamingResponse keep
    working — same rationale as ``SecurityHeadersMiddleware``.
    """

    #: Log when server-side handling exceeds this budget (ms).
    SLOW_MS = 1000.0

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                process_time_ms = (time.perf_counter() - start) * 1000
                headers = MutableHeaders(scope=message)
                headers["X-Process-Time"] = f"{process_time_ms:.2f}ms"
                if process_time_ms > self.SLOW_MS:
                    path = scope.get("path", "")
                    method = scope.get("method", "")
                    logger.warning(
                        f"[SLOW ENDPOINT] {method} {path} took {process_time_ms:.2f}ms",
                        extra={
                            "event": "slow_endpoint",
                            "path": path,
                            "method": method,
                            "process_time_ms": round(process_time_ms, 2),
                        },
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Security headers innermost, then process-time, then GZip, CORS last (outermost):
# Starlette runs the last-added middleware outermost, so preflight (OPTIONS) is
# answered by CORSMiddleware before any inner middleware can reject or reroute it.
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(ProcessTimeMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Browsers cache successful preflights; Chrome may clamp to ~2h but 86400 is
    # the correct server-side value for Authorization + Content-Type CORS.
    max_age=86400,
    expose_headers=[
        "Retry-After",
        "X-Request-Id",
        "X-Process-Time",
        "X-Report-Type",
        "X-Report-Synthesis-Status",
        "X-Report-Cache",
        "X-Report-Zip-Count",
        "X-Report-Zip-Failed",
        "Content-Disposition",
    ],
)

app.include_router(api_router, prefix="/api/v1")
# Gated beta waitlist (exact path requested by product): POST /api/request-beta-access
app.include_router(beta_access_router, prefix="/api")
# HR candidate invite (exact path): POST /api/candidates/invite
app.include_router(invites_router, prefix="/api/candidates", tags=["invites"])


def _cors_error_headers(request: Request) -> dict[str, str]:
    """Build CORS headers for responses produced outside ``CORSMiddleware``.

    Args:
        request: Incoming request whose ``Origin`` is checked against the allowlist.

    Returns:
        CORS headers when the origin is allowed, otherwise an empty dict.
    """
    origin = request.headers.get("origin")
    if not origin or not is_origin_allowed(origin):
        return {}
    return {
        "Access-Control-Allow-Origin": _normalize_origin(origin),
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


@app.exception_handler(DBAPIError)
@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    """Map driver / pooler / schema failures to a 503 with a useful detail.

    Registered for both ``DBAPIError`` (the usual driver wrap) and its
    ``SQLAlchemyError`` base so non-DBAPI SQLAlchemy failures (pool,
    interface) also surface as 503 with the raw error in the logs rather
    than falling through to the generic 500 handler. FastAPI's MRO lookup
    still prefers this handler for ``DBAPIError`` subclasses such as
    ``ProgrammingError`` (e.g. an undefined column from a stale schema).

    Schema drift returns an actionable migration hint. Transient pooler /
    disconnect errors keep the retry wording (dashboard/auth paths retry via
    ``run_db_op_with_retry`` before reaching this handler).

    Args:
        request: Incoming request.
        exc: SQLAlchemy error, usually wrapping a DBAPI/driver error.

    Returns:
        JSON 503 response; CORS headers are applied by ``CORSMiddleware``.
    """
    request_id = getattr(request.state, "request_id", None)
    orig = getattr(exc, "orig", None)
    if isinstance(exc, IntegrityError):
        # A constraint said no: retrying the same request cannot succeed, so
        # this is a 409, not "temporarily unavailable" (P1-20). Generic body:
        # constraint / column names stay in the logs.
        logger.warning(
            "db_integrity_conflict path=%s sqlstate=%s",
            request.url.path,
            getattr(orig, "sqlstate", None),
            extra={
                "event": "db_integrity_conflict",
                "request_id": request_id,
                "path": request.url.path,
                "pg_sqlstate": getattr(orig, "sqlstate", None),
            },
        )
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "CONFLICT",
                    "message": "This change conflicts with existing data.",
                },
                "request_id": request_id,
            },
        )
    schema_drift = is_schema_drift_error(exc)
    transient = is_transient_db_error(exc)
    error_class = (
        "schema_drift" if schema_drift else ("transient" if transient else "other")
    )
    detail = (
        schema_drift_detail(exc)
        if schema_drift
        else "Database temporarily unavailable. Please retry."
    )
    # The type names and raw driver text go in the message itself, not only
    # `extra`: the DEBUG text formatter ignores `extra`, so schema mismatches
    # must be diagnosable from a plain uvicorn.log line. Statement parameters
    # are deliberately excluded.
    logger.error(
        f"[DB ERROR] class={error_class} {type(exc).__name__}: {exc} "
        f"| driver={type(orig).__name__ if orig else None}: {orig}",
        exc_info=exc,
        extra={
            "event": "database_error",
            "error_class": error_class,
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "connection_invalidated": getattr(exc, "connection_invalidated", None),
            "driver_error": type(orig).__name__ if orig else None,
            "driver_error_message": str(orig) if orig else None,
            "sqlalchemy_error": str(exc),
            "pg_sqlstate": getattr(orig, "sqlstate", None),
            "pg_detail": getattr(orig, "detail", None),
            "pg_hint": getattr(orig, "hint", None),
            "statement": getattr(exc, "statement", None),
        },
    )
    headers = {"Retry-After": "1"} if is_deadlock_error(exc) else None
    return JSONResponse(
        status_code=503,
        content={"detail": detail, "request_id": request_id},
        headers=headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return a generic 500 body; log internals with the request id.

    HTTPException / RequestValidationError keep their dedicated FastAPI handlers
    (MRO lookup prefers the more specific registration). This handler runs in
    Starlette's ServerErrorMiddleware, outside CORSMiddleware, so CORS headers
    are attached here or browsers report the 500 as a CORS failure.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "unhandled_error",
        extra={
            "event": "unhandled_error",
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
        },
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers=_cors_error_headers(request),
    )


@app.get("/", tags=["health"])
async def root():
    """Visiting :8000 in a browser is not the app. Point people at the UI."""
    if not settings.DEBUG:
        return {"service": settings.PROJECT_NAME, "health": "/health"}
    return {
        "service": settings.PROJECT_NAME,
        "health": "/health",
        "docs": "/docs",
        "app": "http://localhost:5173",
        "hint": "This is the API only. Open the website at http://localhost:5173/",
    }


@app.get("/health", tags=["health"])
async def health_check():
    """Liveness: the process is up. No dependencies, always fast."""
    return {"status": "healthy", "service": settings.PROJECT_NAME}


#: Per-dependency budget for /health/ready (load-balancer probes are frequent).
READINESS_TIMEOUT_SECONDS = 1.0


async def _check_database() -> str:
    async def _probe() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    # Covers pool checkout too: an exhausted pool fails the probe in 1s
    # instead of waiting out pool_timeout.
    await asyncio.wait_for(_probe(), timeout=READINESS_TIMEOUT_SECONDS)
    return "ok"


async def _check_redis() -> str:
    pool = get_arq_pool()
    if pool is None:
        # Production refuses to boot without Redis; elsewhere it is optional.
        if settings.is_production:
            raise RuntimeError("Redis pool not initialized")
        return "skipped"
    await asyncio.wait_for(pool.ping(), timeout=READINESS_TIMEOUT_SECONDS)
    return "ok"


@app.get("/health/ready", tags=["health"])
async def readiness_check():
    """Readiness: Postgres (``SELECT 1``) and Redis (``PING``), 1s each (P1-12).

    Point the load balancer here so a node that lost its database or Redis
    is taken out of rotation; keep ``/health`` for liveness.

    Returns:
        200 ``{"status": "ready", "checks": {...}}`` or 503 with the failing
        check(s) marked ``"fail"`` (error class only, no connection details).
    """
    checks: dict[str, str] = {}
    for name, probe in (("database", _check_database), ("redis", _check_redis)):
        try:
            checks[name] = await probe()
        except Exception as exc:  # noqa: BLE001 - any failure means not ready
            checks[name] = "fail"
            logger.warning(
                "readiness_check_failed check=%s error=%s",
                name,
                type(exc).__name__,
                extra={"event": "readiness_check_failed", "check": name},
            )
    ready = all(value != "fail" for value in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )
