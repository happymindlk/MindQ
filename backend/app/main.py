from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.router import api_router
from app.api.v1.beta_access import router as beta_access_router
from app.api.v1.invites import router as invites_router
from app.database import engine
from app.config import settings
from app.security import SecurityHeadersMiddleware, assert_production_ready
from app.observability import configure_logging
import contextlib
import logging

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
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
    expose_headers=["X-Request-Id", "X-Report-Type"],
)

app.include_router(api_router, prefix="/api/v1")
# Gated beta waitlist (exact path requested by product): POST /api/request-beta-access
app.include_router(beta_access_router, prefix="/api")
# HR candidate invite (exact path): POST /api/candidates/invite
app.include_router(invites_router, prefix="/api/candidates", tags=["invites"])


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return a generic 500 body; log internals with the request id.

    HTTPException / RequestValidationError keep their dedicated FastAPI handlers
    (MRO lookup prefers the more specific registration).
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
    )


@app.get("/", tags=["health"])
async def root():
    """Visiting :8000 in a browser is not the app. Point people at the UI."""
    return {
        "service": settings.PROJECT_NAME,
        "health": "/health",
        "docs": "/docs",
        "app": "http://localhost:5173",
        "hint": "This is the API only. Open the website at http://localhost:5173/",
    }


@app.get("/health", tags=["health"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "debug": settings.DEBUG,
    }
