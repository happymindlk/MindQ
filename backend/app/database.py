import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings
from app.exceptions import is_transient_db_error

logger = logging.getLogger("app.database")

T = TypeVar("T")

# Retries for transient pooler/disconnect errors around a single DB coroutine.
_DB_OP_ATTEMPTS = 3
_DB_OP_BASE_DELAY_S = 0.05

# #region agent log
_DEBUG_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "debug-f4446e.log",  # repo root (local)
    Path("/app/data/debug-f4446e.log"),  # Docker WORKDIR layout
    Path("/tmp/debug-f4446e.log"),
)


def _agent_dbg(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    """Append one NDJSON debug line for session f4446e (no secrets)."""
    import json

    payload = {
        "sessionId": "f4446e",
        "runId": "post-fix",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(payload, default=str) + "\n"
    for path in _DEBUG_CANDIDATES:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line)
            return
        except OSError:
            continue


def _db_url_fingerprint(url: str) -> dict:
    """Host/port/scheme only — never userinfo — for pooler vs direct diagnosis."""
    normalized = url.replace("postgresql+asyncpg", "postgresql", 1)
    parsed = urlparse(normalized)
    port = parsed.port
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": port,
        "db": (parsed.path or "").lstrip("/") or None,
        "likely_pooler": port == 6543,
        "likely_direct": port in (5432, 54322),
    }


_URL_FP = _db_url_fingerprint(settings.DATABASE_URL)
_agent_dbg(
    "D",
    "database.py:engine_init",
    "engine_created",
    {
        **_URL_FP,
        "pool_size": 5,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "statement_cache_size": 0,
    },
)
# #endregion

# Async Postgres engine. Schema is owned by Supabase migrations (supabase/migrations),
# NOT by SQLAlchemy metadata.create_all.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    # Recycle before typical Supabase/PgBouncer idle cuts (~5m) so the pool
    # does not hand out sockets the remote already closed.
    pool_recycle=280,
    pool_size=5,
    max_overflow=10,
    # Production connects through Supavisor in transaction mode, which may hand any
    # query a different Postgres backend. Cached / reused prepared-statement names
    # then fail with "prepared statement __asyncpg_stmt_N__ does not exist" (26000).
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        "timeout": 10,
        "command_timeout": 60,
    },
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


async def run_db_op_with_retry(
    op: Callable[[], Awaitable[T]],
    *,
    session: AsyncSession | None = None,
) -> T:
    """Run a DB coroutine, retrying transient disconnect / pooler failures.

    Args:
        op: Zero-arg async callable (typically a lambda closing over a session).
        session: Optional session to ``rollback`` after an invalidated connection
            so the next attempt can check out a fresh pooled socket.

    Returns:
        The awaited result of ``op``.

    Raises:
        The last error when retries are exhausted or the failure is not transient
        (schema drift is never retried).
    """
    last_exc: BaseException | None = None
    for attempt in range(1, _DB_OP_ATTEMPTS + 1):
        try:
            return await op()
        except (DBAPIError, SQLAlchemyError, OSError) as exc:
            last_exc = exc
            transient = is_transient_db_error(exc)
            # #region agent log
            orig = getattr(exc, "orig", None)
            _agent_dbg(
                "A",
                "database.py:run_db_op_with_retry",
                "db_op_error",
                {
                    "attempt": attempt,
                    "transient": transient,
                    "will_retry": transient and attempt < _DB_OP_ATTEMPTS,
                    "exc_type": type(exc).__name__,
                    "exc": str(exc)[:500],
                    "driver_type": type(orig).__name__ if orig else None,
                    "driver": str(orig)[:500] if orig else None,
                    "sqlstate": getattr(orig, "sqlstate", None),
                    "connection_invalidated": getattr(exc, "connection_invalidated", None),
                },
            )
            # #endregion
            if not transient or attempt >= _DB_OP_ATTEMPTS:
                raise
            delay = _DB_OP_BASE_DELAY_S * (2 ** (attempt - 1))
            logger.warning(
                "db_op_retry attempt=%s/%s delay_s=%.3f error=%s",
                attempt,
                _DB_OP_ATTEMPTS,
                delay,
                type(exc).__name__,
                extra={
                    "event": "db_op_retry",
                    "attempt": attempt,
                    "delay_s": delay,
                    "driver_error": type(getattr(exc, "orig", None)).__name__
                    if getattr(exc, "orig", None)
                    else type(exc).__name__,
                    "driver_error_message": str(getattr(exc, "orig", None) or exc)[:300],
                },
            )
            if session is not None:
                try:
                    await session.rollback()
                except SQLAlchemyError:
                    logger.warning("db_op_retry_rollback_failed", exc_info=True)
            if getattr(exc, "connection_invalidated", False):
                await engine.dispose()
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


async def get_db():
    """Yield a request-scoped session; always closed via ``async with``.

    Connection checkout stays lazy so auth can reject bad tokens with 401
    without requiring a live DB. Transient query failures should use
    :func:`run_db_op_with_retry` (wired on the candidate dashboard path).
    """
    # #region agent log
    pool = engine.pool
    t0 = time.perf_counter()
    _agent_dbg(
        "D",
        "database.py:get_db:acquire",
        "session_acquire_start",
        {
            "pool_size": getattr(pool, "size", lambda: None)(),
            "checked_in": getattr(pool, "checkedin", lambda: None)(),
            "checked_out": getattr(pool, "checkedout", lambda: None)(),
            "overflow": getattr(pool, "overflow", lambda: None)(),
            **_URL_FP,
        },
    )
    # #endregion
    try:
        async with SessionLocal() as session:
            # #region agent log
            _agent_dbg(
                "D",
                "database.py:get_db:yield",
                "session_acquired",
                {
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "checked_out": getattr(pool, "checkedout", lambda: None)(),
                },
            )
            # #endregion
            try:
                yield session
            finally:
                # #region agent log
                _agent_dbg(
                    "D",
                    "database.py:get_db:release",
                    "session_releasing",
                    {
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                        "checked_out": getattr(pool, "checkedout", lambda: None)(),
                    },
                )
                # #endregion
    except Exception as exc:
        # #region agent log
        orig = getattr(exc, "orig", None)
        _agent_dbg(
            "A",
            "database.py:get_db:error",
            "session_lifecycle_error",
            {
                "exc_type": type(exc).__name__,
                "exc": str(exc)[:500],
                "driver_type": type(orig).__name__ if orig else None,
                "driver": str(orig)[:500] if orig else None,
                "sqlstate": getattr(orig, "sqlstate", None),
                "connection_invalidated": getattr(exc, "connection_invalidated", None),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                "checked_out": getattr(pool, "checkedout", lambda: None)(),
            },
        )
        # #endregion
        raise
