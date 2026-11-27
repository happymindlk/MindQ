"""Regression lock for the Supavisor-tuned async engine pools (P0-05)."""

from app import database
from app.config import settings
from app.database import detect_process_role, engine, pool_limits


def test_web_engine_pool_is_bounded():
    """Web workers: 10 + 10 per uvicorn worker, recycle before the ~5m idle cut.

    Total pooler clients = nodes x WEB_CONCURRENCY x 20 + ARQ workers x 10;
    2 x 2 x 20 + 10 = 90 on staging/prod.
    """
    assert database.PROCESS_ROLE == "web"
    pool = engine.sync_engine.pool
    assert pool.size() == 10
    assert pool._max_overflow == 10
    assert pool._recycle == 280
    assert pool._pre_ping is True


def test_worker_role_uses_smaller_pool():
    assert pool_limits("worker") == (5, 5)
    assert pool_limits("web") == (10, 10)


def test_detects_arq_cli_as_worker(monkeypatch):
    monkeypatch.setattr(settings, "DB_PROCESS_ROLE", "")
    assert detect_process_role(["/usr/local/bin/arq", "app.jobs.worker.WorkerSettings"]) == "worker"
    assert detect_process_role(["C:/venv/Scripts/arq.exe"]) == "worker"
    assert detect_process_role(["/venv/lib/python3.12/site-packages/arq/__main__.py"]) == "worker"
    assert detect_process_role(["/usr/local/bin/uvicorn", "app.main:app"]) == "web"
    assert detect_process_role([]) == "web"


def test_explicit_role_overrides_detection(monkeypatch):
    monkeypatch.setattr(settings, "DB_PROCESS_ROLE", "worker")
    assert detect_process_role(["/usr/local/bin/uvicorn"]) == "worker"
