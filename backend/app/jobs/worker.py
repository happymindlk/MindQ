"""ARQ worker process entrypoint: ``arq app.jobs.worker.WorkerSettings``."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.jobs.settings import redis_settings_from_url
from app.jobs.tasks import TASK_FUNCTIONS
from app.observability import configure_logging

configure_logging(debug=settings.DEBUG)
logger = logging.getLogger(__name__)


async def on_startup(ctx: dict[str, Any]) -> None:
    """Warm the worker's DB pool before jobs start.

    Args:
        ctx: ARQ worker context dict (mutable).
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("arq_worker_db_warmed", extra={"event": "arq_worker_db_warmed"})
    except Exception:
        logger.warning(
            "arq_worker_db_warmup_failed",
            exc_info=True,
            extra={"event": "arq_worker_db_warmup_failed"},
        )
    ctx["worker_started"] = True


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Dispose the SQLAlchemy engine when the worker exits.

    Args:
        ctx: ARQ worker context dict.
    """
    del ctx
    await engine.dispose()
    logger.info("arq_worker_stopped", extra={"event": "arq_worker_stopped"})


class WorkerSettings:
    """ARQ worker configuration consumed by the ``arq`` CLI."""

    functions = list(TASK_FUNCTIONS)
    redis_settings = redis_settings_from_url()
    max_jobs = settings.ARQ_MAX_JOBS
    job_timeout = settings.ARQ_JOB_TIMEOUT
    max_tries = settings.ARQ_MAX_TRIES
    # Allow the same deterministic job_id to be reused soon after success
    # (e.g. a later report refresh once scores change).
    keep_result = 60
    on_startup = on_startup
    on_shutdown = on_shutdown
