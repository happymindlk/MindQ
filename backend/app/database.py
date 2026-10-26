import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.config import settings

# #region agent log
_DEBUG_LOG_PATH = Path(__file__).resolve().parents[2] / "debug-f4446e.log"


def _agent_dbg(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    """Append one NDJSON debug line for session f4446e (no secrets)."""
    import json

    try:
        payload = {
            "sessionId": "f4446e",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass


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
    pool_size=5,
    max_overflow=10,
    # Production connects through Supavisor in transaction mode, which may hand any
    # query a different Postgres backend. Cached / reused prepared-statement names
    # then fail with "prepared statement __asyncpg_stmt_N__ does not exist" (26000).
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
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


async def get_db():
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
