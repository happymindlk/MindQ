import contextlib
import json
import logging
import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.api.v1.beta_access import router as beta_access_router
from app.api.v1.invites import router as invites_router
from app.api.v1.router import api_router
from app.config import settings
from app.database import engine
from app.observability import configure_logging
from app.security import SecurityHeadersMiddleware, assert_production_ready

configure_logging(debug=settings.DEBUG)
logger = logging.getLogger("app.main")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate production config, then dispose the engine on shutdown.

    The database schema is managed by Supabase migrations (supabase/migrations),
    applied via `supabase db reset` / `supabase migration up` - never by
    metadata.create_all.
    """
    assert_production_ready(settings)
    logger.info(
        "app_started",
        extra={"event": "app_started", "debug": settings.DEBUG},
    )
    yield
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

#: Origins that must always work, regardless of deployment env.
DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = (
    "https://qa.app.mindqtalent.com",
    "https://mindq.pages.dev",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
)

#: Any https subdomain of our two hosted zones, e.g.
#: ``https://qa.app.mindqtalent.com``, ``https://feat-x.mindq.pages.dev``.
MINDQTALENT_ORIGIN_REGEX = r"^https://.*\.mindqtalent\.com$"
PAGES_DEV_ORIGIN_REGEX = r"^https://.*\.pages\.dev$"
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
    """Unified allowlist: settings (list or CSV) + FRONTEND_URL + defaults."""
    candidates: list[str] = []
    # `cors_origins_list` already normalizes list/CSV; reading the raw value
    # too keeps this correct if settings are monkeypatched with either shape.
    candidates.extend(_coerce_origins(getattr(settings, "CORS_ORIGINS", None)))
    if hasattr(settings, "cors_origins_list"):
        candidates.extend(_coerce_origins(settings.cors_origins_list))
    candidates.extend(_coerce_origins(getattr(settings, "FRONTEND_URL", None)))
    candidates.extend(DEFAULT_ALLOWED_ORIGINS)

    seen: set[str] = set()
    origins: list[str] = []
    for origin in candidates:
        if origin not in seen:
            seen.add(origin)
            origins.append(origin)
    return origins


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


# Security headers first, CORS last: Starlette runs the last-added middleware
# outermost, so preflight (OPTIONS) is answered by CORSMiddleware before any
# inner middleware can reject or reroute it.
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "X-Report-Type", "X-Report-Synthesis-Status"],
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
    """Map driver / pooler failures to a retryable 503 instead of a 500.

    Registered for both ``DBAPIError`` (the usual driver wrap) and its
    ``SQLAlchemyError`` base so non-DBAPI SQLAlchemy failures (pool,
    interface) also surface as 503 with the raw error in the logs rather
    than falling through to the generic 500 handler. FastAPI's MRO lookup
    still prefers this handler for ``DBAPIError`` subclasses such as
    ``ProgrammingError`` (e.g. an undefined column from a stale schema).

    Args:
        request: Incoming request.
        exc: SQLAlchemy error, usually wrapping a DBAPI/driver error.

    Returns:
        JSON 503 response; CORS headers are applied by ``CORSMiddleware``.
    """
    request_id = getattr(request.state, "request_id", None)
    orig = getattr(exc, "orig", None)
    # The type names and raw driver text go in the message itself, not only
    # `extra`: the DEBUG text formatter ignores `extra`, so schema mismatches
    # must be diagnosable from a plain uvicorn.log line. Statement parameters
    # are deliberately excluded.
    logger.error(
        f"[DB ERROR] {type(exc).__name__}: {exc} "
        f"| driver={type(orig).__name__ if orig else None}: {orig}",
        exc_info=exc,
        extra={
            "event": "database_error",
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
    # #region agent log
    try:
        import json
        import time
        from pathlib import Path

        exc_text = str(exc).lower()
        orig_text = str(orig).lower() if orig else ""
        combined = f"{exc_text} {orig_text}"
        sqlstate = getattr(orig, "sqlstate", None)
        is_schema = (
            "does not exist" in combined
            or "undefinedcolumn" in combined
            or "undefinedtable" in combined
            or sqlstate in ("42P01", "42703")
        )
        is_prepared = (
            "prepared statement" in combined
            or sqlstate == "26000"
        )
        is_transient = (
            getattr(exc, "connection_invalidated", False)
            or sqlstate in ("57P01", "57P02", "57P03", "08006", "08001", "08003", "08004")
            or any(
                token in combined
                for token in (
                    "connection refused",
                    "connection reset",
                    "server closed the connection",
                    "timeout",
                    "too many connections",
                    "cannot connect",
                    "connection was closed",
                    "ssl connection has been closed",
                    "broken pipe",
                )
            )
        )
        Path(__file__).resolve().parents[2].joinpath("debug-f4446e.log").open(
            "a", encoding="utf-8"
        ).write(
            json.dumps(
                {
                    "sessionId": "f4446e",
                    "hypothesisId": "B" if is_schema else ("C" if is_prepared else ("A" if is_transient else "E")),
                    "location": "main.py:database_error_handler",
                    "message": "mapped_sqlalchemy_to_503",
                    "data": {
                        "path": request.url.path,
                        "method": request.method,
                        "request_id": request_id,
                        "exc_type": type(exc).__name__,
                        "driver_type": type(orig).__name__ if orig else None,
                        "driver_message": str(orig)[:500] if orig else None,
                        "sqlalchemy_message": str(exc)[:500],
                        "sqlstate": sqlstate,
                        "connection_invalidated": getattr(exc, "connection_invalidated", None),
                        "class_schema": is_schema,
                        "class_prepared": is_prepared,
                        "class_transient": is_transient,
                        "statement": (getattr(exc, "statement", None) or "")[:200] or None,
                    },
                    "timestamp": int(time.time() * 1000),
                },
                default=str,
            )
            + "\n"
        )
    except OSError:
        pass
    # #endregion
    return JSONResponse(
        status_code=503,
        content={"detail": "Database temporarily unavailable. Please retry.", "request_id": request_id},
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
    return {"status": "healthy", "service": settings.PROJECT_NAME}
