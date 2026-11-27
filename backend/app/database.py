import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import PurePath
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings
from app.exceptions import is_deadlock_error, is_transient_db_error

logger = logging.getLogger("app.database")

T = TypeVar("T")

# Retries for transient pooler/disconnect errors around a single DB coroutine.
_DB_OP_ATTEMPTS = 3
_DB_OP_BASE_DELAY_S = 0.05

def detect_process_role(argv: list[str] | None = None) -> str:
    """Return ``"worker"`` for the ARQ worker process, else ``"web"``.

    ``DB_PROCESS_ROLE`` wins when set. Otherwise the ``arq`` CLI is detected
    from ``sys.argv[0]`` (``/usr/local/bin/arq`` or ``python -m arq``). The
    role must be known at import time: the worker imports this module via
    ``app.jobs`` before ``app.jobs.worker`` runs.

    Args:
        argv: Override for ``sys.argv`` (tests).

    Returns:
        ``"web"`` or ``"worker"``.
    """
    explicit = (settings.DB_PROCESS_ROLE or "").strip().lower()
    if explicit in {"web", "worker"}:
        return explicit
    args = sys.argv if argv is None else argv
    if not args:
        return "web"
    entry = PurePath(args[0])
    name = entry.name.lower()
    if name in {"arq", "arq.exe"} or entry.parent.name.lower() == "arq":
        return "worker"
    return "web"


def pool_limits(role: str) -> tuple[int, int]:
    """``(pool_size, max_overflow)`` for a process role, from settings.

    Args:
        role: ``"web"`` or ``"worker"``.

    Returns:
        Pool size and overflow for this process's engine.
    """
    if role == "worker":
        return settings.DB_WORKER_POOL_SIZE, settings.DB_WORKER_MAX_OVERFLOW
    return settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW


PROCESS_ROLE = detect_process_role()
POOL_SIZE, MAX_OVERFLOW = pool_limits(PROCESS_ROLE)

# Async Postgres engine, one per process. Schema is owned by Supabase
# migrations (supabase/migrations), NOT by SQLAlchemy metadata.create_all.
#
# Sizing (Supavisor transaction mode counts every client socket):
#   web    = DB_POOL_SIZE + DB_MAX_OVERFLOW               (default 10 + 10 = 20)
#   worker = DB_WORKER_POOL_SIZE + DB_WORKER_MAX_OVERFLOW (default  5 +  5 = 10)
#   total  = nodes x WEB_CONCURRENCY x 20 + workers x 10
# Staging/prod today: 2 x 2 x 20 + 1 x 10 = 90. Keep the total at or below
# ~70% of the pooler client limit (see DEPLOYMENT.md). Concurrent HTTP
# requests share these sockets; they do not need 1:1 DB connections.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=15,
    # Recycle before typical Supabase/PgBouncer idle cuts (~5m) so the pool
    # does not hand out sockets the remote already closed. Do not raise this to
    # 30m while fronting Supavisor — stale sockets surface as intermittent 57P01.
    pool_recycle=280,
    pool_pre_ping=True,
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
logger.info(
    "db_engine_configured role=%s pool_size=%s max_overflow=%s",
    PROCESS_ROLE,
    POOL_SIZE,
    MAX_OVERFLOW,
)



@event.listens_for(engine.sync_engine, "handle_error")
def _invalidate_only_broken_connection(context) -> None:
    """On a disconnect, drop only the failing connection (P1-20).

    SQLAlchemy's default also soft-invalidates every other pooled connection,
    so one pooler blip made each worker reconnect its whole pool at once (a
    reconnect stampede). ``pool_pre_ping`` already catches any other stale
    socket individually at checkout.
    """
    if context.is_disconnect:
        context.invalidate_pool_on_disconnect = False


# expire_on_commit=False keeps loaded column values after commit so async
# code can read scalars across transaction boundaries without implicit lazy
# reloads (which raise MissingGreenlet outside an await greenlet).
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
                # Returns the (already invalidated, if broken) connection; the
                # next attempt checks out a fresh one. No engine.dispose():
                # that dropped every pooled socket in the worker (P1-20).
                try:
                    await session.rollback()
                except SQLAlchemyError:
                    logger.warning("db_op_retry_rollback_failed", exc_info=True)
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


#: Extra attempts for a transaction Postgres aborted as a deadlock victim.
DEADLOCK_RETRY_ATTEMPTS = 2


async def retry_on_deadlock(
    op: Callable[[], Awaitable[T]],
    *,
    session: AsyncSession,
    attempts: int = DEADLOCK_RETRY_ATTEMPTS,
) -> T:
    """Re-run a whole unit of work when Postgres aborts it as a deadlock victim.

    For short write transactions on hot rows (autosave, submit, HR reset).
    40P01 / 40001 mean Postgres rolled the transaction back, so running it
    again from the start is safe. Anything else propagates unchanged.

    Args:
        op: Zero-arg async callable performing the complete transaction.
        session: Session to roll back between attempts.
        attempts: Total attempts (default 2 = one retry).

    Returns:
        The awaited result of ``op``.
    """
    for attempt in range(1, attempts + 1):
        try:
            return await op()
        except DBAPIError as exc:
            if attempt >= attempts or not is_deadlock_error(exc):
                raise
            logger.warning(
                "db_deadlock_retry attempt=%s/%s",
                attempt,
                attempts,
                extra={"event": "db_deadlock_retry", "attempt": attempt},
            )
            try:
                await session.rollback()
            except SQLAlchemyError:
                logger.warning("db_deadlock_rollback_failed", exc_info=True)
            await asyncio.sleep(0.02 * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


async def get_db():
    """Yield a request-scoped session; always closed via ``async with``.

    Connection checkout stays lazy so auth can reject bad tokens with 401
    without requiring a live DB. Transient query failures should use
    :func:`run_db_op_with_retry` (wired on the candidate dashboard path).
    """
    async with SessionLocal() as session:
        yield session
