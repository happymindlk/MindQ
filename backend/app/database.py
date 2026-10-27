import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar
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

# Async Postgres engine. Schema is owned by Supabase migrations (supabase/migrations),
# NOT by SQLAlchemy metadata.create_all.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    # Recycle before typical Supabase/PgBouncer idle cuts (~5m) so the pool
    # does not hand out sockets the remote already closed.
    pool_recycle=280,
    pool_size=10,
    max_overflow=20,
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
            if not is_transient_db_error(exc) or attempt >= _DB_OP_ATTEMPTS:
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
    async with SessionLocal() as session:
        yield session
