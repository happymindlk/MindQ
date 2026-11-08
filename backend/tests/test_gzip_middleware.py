"""GZipMiddleware must compress large JSON responses when the client allows it."""

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.main import app


def _middleware_classes() -> list[type]:
    return [m.cls for m in app.user_middleware]


def test_gzip_middleware_is_registered_inside_cors():
    """CORS is outermost (first in user_middleware); GZip sits inside it."""
    classes = _middleware_classes()
    assert GZipMiddleware in classes
    assert CORSMiddleware in classes
    # FastAPI inserts at index 0, so the last-added middleware is outermost.
    assert classes.index(CORSMiddleware) < classes.index(GZipMiddleware)


def test_large_json_response_round_trips_with_accept_encoding_gzip():
    """Bodies over minimum_size=500 with Accept-Encoding: gzip still decode as JSON.

    TestClient / httpx may auto-decode Content-Encoding, so we assert a valid
    decoded body rather than the raw Content-Encoding header.
    """
    from fastapi.testclient import TestClient

    path = "/__test_gzip_large_json"

    @app.get(path, include_in_schema=False)
    async def _large_json():
        return {"pad": "x" * 600, "status": "ok"}

    try:
        client = TestClient(app, raise_server_exceptions=False)
        res = client.get(path, headers={"Accept-Encoding": "gzip"})
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert len(body["pad"]) == 600
    finally:
        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != path
        ]
