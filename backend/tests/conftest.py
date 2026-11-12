import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.jobs.settings import set_arq_pool_for_tests
from app.main import app


@pytest.fixture(autouse=True)
def _arq_pool_isolated():
    """Keep unit tests off a live Redis pool unless a test opts in."""
    set_arq_pool_for_tests(None)
    yield
    set_arq_pool_for_tests(None)


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
