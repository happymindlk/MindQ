import contextlib
import json
import logging
import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

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

#: Dev/QA origins merged only while DEBUG is on. DEBUG=false keeps the
#: allowlist env-scoped (CORS_ORIGINS + FRONTEND_URL) plus the zone regex.
DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = (
    "https://qa.app.mindqtalent.com",
    "https://mindq.pages.dev",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
)

#: Hosts we control. Cloudflare Pages is shared, so this is ``*.mindq.pages.dev``
#: (and the apex project), not every ``*.pages.dev`` site. Examples:
#: ``https://qa.app.mindqtalent.com``, ``https://feat-x.mindq.pages.dev``.
ALLOW_ORIGIN_REGEX = (
    r"^https://.*\.mindqtalent\.com$"
    r"|^https://([a-z0-9-]+\.)*mindq\.pages\.dev$"
)

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
    """Unified allowlist: settings (list or CSV) + FRONTEND_URL.

    Dev defaults (QA host, Pages apex, localhost) are merged only when
    ``DEBUG`` is true so a production boot stays env-scoped.
    """
    candidates: list[str] = []
    # `cors_origins_list` already normalizes list/CSV; reading the raw value
    # too keeps this correct if settings are monkeypatched with either shape.
    candidates.extend(_coerce_origins(getattr(settings, "CORS_ORIGINS", None)))
    if hasattr(settings, "cors_origins_list"):
        candidates.extend(_coerce_origins(settings.cors_origins_list))
    candidates.extend(_coerce_origins(getattr(settings, "FRONTEND_URL", None)))
    # DEBUG=false is the production contract. Always merging QA and localhost
    # would credential those origins on every deploy and bypass the check that
    # rejects localhost-only / wildcard CORS_ORIGINS.
    if settings.DEBUG:
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
        ``mindq.pages.dev`` https-host regex match.
    """
    if not origin:
        return False
    normalized = _normalize_origin(origin)
    # Live settings, not the import-time snapshot. A DEBUG=false process must
    # be able to drop the dev defaults that snapshot was built with.
    if normalized in _build_allowed_origins():
        return True
    return _allow_origin_pattern.fullmatch(normalized) is not None


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=ALLOW_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "X-Report-Type", "X-Report-Synthesis-Status"],
)

app.add_middleware(SecurityHeadersMiddleware)

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
async def database_error_handler(request: Request, exc: DBAPIError):
    """Map driver / pooler failures to a retryable 503 instead of a 500.

    Args:
        request: Incoming request.
        exc: SQLAlchemy-wrapped DBAPI error.

    Returns:
        JSON 503 response; CORS headers are applied by ``CORSMiddleware``.
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "database_error",
        extra={
            "event": "database_error",
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "connection_invalidated": exc.connection_invalidated,
            "driver_error": type(exc.orig).__name__ if exc.orig else None,
        },
    )
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
