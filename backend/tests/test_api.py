import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_points_at_the_ui(async_client: AsyncClient):
    response = await async_client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "http://localhost:5173"
    assert body["docs"] == "/docs"


@pytest.mark.asyncio
async def test_health(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_chat_endpoint(async_client: AsyncClient):
    response = await async_client.post("/api/v1/chat/message", json={"message": "hello"})
    assert response.status_code == 200
    assert "reply" in response.json()
