"""Error responses must stay readable cross-origin (no browser "CORS error" masking)."""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import ProgrammingError

from app.auth import HRUserContext, get_current_ops_user
from app.database import engine, get_db
from app.main import allowed_origins, app, is_origin_allowed

ORIGIN = "https://mindq.pages.dev"


@pytest.mark.parametrize(
    "origin",
    [
        "https://qa.app.mindqtalent.com",
        "https://mindq.pages.dev",
        "http://localhost:5173",
        "http://localhost:3000",
        # Subdomains matched by allow_origin_regex, not the explicit list.
        "https://preview-123.mindq.pages.dev",
        "https://feature-x.app.mindqtalent.com",
    ],
)
def test_allowed_origins_cover_qa_pages_and_localhost(origin):
    assert is_origin_allowed(origin)


@pytest.mark.parametrize(
    "origin",
    [None, "", "https://evil.example", "http://qa.app.mindqtalent.com"],
)
def test_disallowed_origins_are_rejected(origin):
    assert not is_origin_allowed(origin)


def test_explicit_allowlist_contains_required_origins():
    for origin in (
        "https://qa.app.mindqtalent.com",
        "https://mindq.pages.dev",
        "http://localhost:5173",
        "http://localhost:3000",
    ):
        assert origin in allowed_origins
PATH = "/api/v1/packages/corporates"


class _PreparedStatementDropped(Exception):
    """Stand-in for asyncpg InvalidSQLStatementNameError (SQLSTATE 26000)."""


class _FailingSession:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def execute(self, *_args, **_kwargs):
        raise self._exc


def _ops_user() -> HRUserContext:
    return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")


@pytest.fixture
def override_deps():
    def _apply(exc: BaseException) -> None:
        async def _db():
            yield _FailingSession(exc)

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_ops_user] = _ops_user

    yield _apply
    app.dependency_overrides.clear()


async def _get(origin: str | None = ORIGIN):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    headers = {"Origin": origin} if origin else {}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(PATH, headers=headers)


@pytest.mark.asyncio
async def test_dropped_prepared_statement_returns_503_with_cors(override_deps):
    override_deps(
        ProgrammingError(
            "SELECT 1",
            {},
            _PreparedStatementDropped('prepared statement "__asyncpg_stmt_3e__" does not exist'),
        )
    )
    res = await _get()
    assert res.status_code == 503
    assert res.headers["access-control-allow-origin"] == ORIGIN
    assert "retry" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_unhandled_error_returns_500_with_cors(override_deps):
    override_deps(RuntimeError("boom"))
    res = await _get()
    assert res.status_code == 500
    assert res.headers["access-control-allow-origin"] == ORIGIN
    assert res.headers["access-control-allow-credentials"] == "true"
    assert res.json()["detail"] == "Internal server error"


@pytest.mark.asyncio
async def test_unhandled_error_does_not_reflect_unknown_origin(override_deps):
    override_deps(RuntimeError("boom"))
    res = await _get(origin="https://evil.example")
    assert res.status_code == 500
    assert "access-control-allow-origin" not in res.headers


@pytest.mark.asyncio
async def test_expired_token_returns_401_with_cors():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            PATH, headers={"Origin": ORIGIN, "Authorization": "Bearer abc.def.ghi"}
        )
    assert res.status_code == 401
    assert res.headers["access-control-allow-origin"] == ORIGIN


@pytest.mark.asyncio
async def test_engine_disables_asyncpg_statement_cache(monkeypatch):
    import asyncpg

    captured: dict = {}

    async def _fake_connect(*_args, **kwargs):
        captured.update(kwargs)
        raise ConnectionRefusedError("captured")

    monkeypatch.setattr(asyncpg, "connect", _fake_connect)
    await engine.dispose()
    with pytest.raises(Exception):
        async with engine.connect():
            pass
    await engine.dispose()
    assert captured.get("statement_cache_size") == 0
