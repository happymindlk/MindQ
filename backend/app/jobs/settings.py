"""Redis / ARQ connection helpers shared by the web process and the worker."""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import settings

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None


def redis_settings_from_url(url: str | None = None) -> RedisSettings:
    """Parse ``REDIS_URL`` into ARQ ``RedisSettings``.

    Args:
        url: Optional override; defaults to ``settings.REDIS_URL``.

    Returns:
        Connection settings for ``create_pool`` / ``WorkerSettings``.
    """
    raw = (url or settings.REDIS_URL or "").strip() or "redis://localhost:6379/0"
    try:
        return RedisSettings.from_dsn(raw)
    except Exception:
        # Older / odd DSNs: fall back to manual host/port/db parsing.
        parsed = urlparse(raw)
        db = 0
        if parsed.path and parsed.path.strip("/"):
            try:
                db = int(parsed.path.strip("/").split("/")[0])
            except ValueError:
                db = 0
        return RedisSettings(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            database=db,
            password=parsed.password,
            username=parsed.username,
            ssl=parsed.scheme == "rediss",
        )


def get_arq_pool() -> ArqRedis | None:
    """Return the process-wide ARQ pool, or ``None`` when unavailable."""
    return _pool


async def open_arq_pool() -> ArqRedis | None:
    """Create the shared ARQ Redis pool for the FastAPI process.

    Production fails closed when Redis is unreachable so jobs are never silently
    inlined on a web worker. Non-production falls back to inline execution via
    ``enqueue`` helpers so local/CI can run without Redis.

    Returns:
        The open pool, or ``None`` when falling back outside production.

    Raises:
        Exception: Propagated in production when the pool cannot be created.
    """
    global _pool
    if _pool is not None:
        return _pool
    try:
        _pool = await create_pool(redis_settings_from_url())
        logger.info("arq_pool_opened", extra={"event": "arq_pool_opened"})
        return _pool
    except Exception:
        _pool = None
        if settings.is_production:
            logger.exception(
                "arq_pool_open_failed",
                extra={"event": "arq_pool_open_failed"},
            )
            raise
        logger.warning(
            "arq_pool_unavailable_inline_fallback",
            exc_info=True,
            extra={"event": "arq_pool_unavailable_inline_fallback"},
        )
        return None


async def close_arq_pool() -> None:
    """Close the shared ARQ pool if it was opened."""
    global _pool
    if _pool is None:
        return
    try:
        await _pool.aclose()
    except Exception:
        logger.warning("arq_pool_close_failed", exc_info=True)
    finally:
        _pool = None
        logger.info("arq_pool_closed", extra={"event": "arq_pool_closed"})


def set_arq_pool_for_tests(pool: ArqRedis | None) -> None:
    """Replace the process pool (unit tests / fakes only).

    Args:
        pool: Fake or real ``ArqRedis``, or ``None`` to force inline fallback.
    """
    global _pool
    _pool = pool
