import asyncio
from types import SimpleNamespace

import pytest

from app.services import gemini_client
from app.services.gemini_client import (
    background_retry_profile,
    call_with_fallback_async,
    call_with_fallback_sync,
    fallback_models,
    is_capacity_error,
    is_retryable,
    max_attempts,
    overall_deadline_seconds,
    retry_delay_seconds,
    retry_sync,
    served_model,
)


class RateLimitError(Exception):
    def __init__(self, code: int = 429, status: str = "RESOURCE_EXHAUSTED"):
        self.code = code
        self.status = status
        super().__init__(f"{code} {status}")


@pytest.fixture(autouse=True)
def _gemini_settings(monkeypatch):
    s = gemini_client.settings
    monkeypatch.setattr(s, "GEMINI_MODEL", "primary-model")
    monkeypatch.setattr(s, "GEMINI_FALLBACK_MODELS", "fallback-model")
    monkeypatch.setattr(s, "GEMINI_MAX_RETRIES", 3)
    monkeypatch.setattr(s, "GEMINI_BACKGROUND_MAX_RETRIES", 5)
    monkeypatch.setattr(s, "GEMINI_RETRY_BASE_SECONDS", 2.0)
    monkeypatch.setattr(s, "GEMINI_RETRY_MAX_DELAY_SECONDS", 30.0)
    monkeypatch.setattr(s, "GEMINI_TIMEOUT_SECONDS", 45.0)


def test_google_client_error_429_is_retryable():
    from google.genai.errors import ClientError

    exc = ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}})
    assert is_retryable(exc)
    assert is_capacity_error(exc)


def test_google_server_error_503_is_capacity_error():
    from google.genai.errors import ServerError

    exc = ServerError(503, {"error": {"status": "UNAVAILABLE", "message": "high demand"}})
    assert is_capacity_error(exc)


@pytest.mark.parametrize(
    "exc",
    [
        RateLimitError(code=404, status="NOT_FOUND"),
        RateLimitError(code=400, status="INVALID_ARGUMENT"),
        RateLimitError(code=500, status="INTERNAL"),
        ValueError("schema mismatch"),
    ],
)
def test_non_capacity_errors_do_not_trigger_fallback(exc):
    assert not is_capacity_error(exc)


def test_retry_sync_recovers_after_rate_limit():
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError()
        return "ok"

    delays: list[float] = []
    assert retry_sync(fn, sleep=delays.append) == "ok"
    assert calls["n"] == 3
    assert delays == [retry_delay_seconds(1), retry_delay_seconds(2)]


def test_retry_sync_does_not_retry_client_errors():
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        raise RateLimitError(code=404, status="NOT_FOUND")

    with pytest.raises(RateLimitError) as info:
        retry_sync(fn, sleep=lambda _s: None)
    assert info.value.code == 404
    assert calls["n"] == 1


DAILY_QUOTA_429 = RateLimitError(code=429, status="RESOURCE_EXHAUSTED")
DAILY_QUOTA_429.args = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '36854s'}]}}",
)


def test_provider_retry_delay_is_parsed():
    assert gemini_client.provider_retry_delay_seconds(DAILY_QUOTA_429) == 36854.0
    short = RateLimitError()
    short.args = ("429 ... \"retryDelay\": \"7.5s\"",)
    assert gemini_client.provider_retry_delay_seconds(short) == 7.5
    assert gemini_client.provider_retry_delay_seconds(RateLimitError()) is None


def test_daily_quota_429_is_not_retried_but_falls_back():
    models: list[str] = []
    sleeps: list[float] = []

    def call(model: str) -> str:
        def once() -> str:
            models.append(model)
            if model == "primary-model":
                raise DAILY_QUOTA_429
            return model

        return retry_sync(once, sleep=sleeps.append)

    assert call_with_fallback_sync(call) == "fallback-model"
    assert models == ["primary-model", "fallback-model"]
    assert sleeps == []


def test_short_advised_delay_is_still_retried():
    burst = RateLimitError()
    burst.args = ("429 RESOURCE_EXHAUSTED 'retryDelay': '3s'",)
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise burst
        return "ok"

    assert retry_sync(fn, sleep=lambda _s: None) == "ok"
    assert calls["n"] == 2


def test_retry_delay_is_capped():
    assert retry_delay_seconds(1) == 2.0
    assert retry_delay_seconds(4) == 16.0
    assert retry_delay_seconds(10) == 30.0


@pytest.mark.parametrize("attempt, full", [(1, 2.0), (3, 8.0), (9, 30.0)])
def test_jitter_stays_within_half_to_full_delay(attempt, full):
    low = retry_delay_seconds(attempt, jitter=True, rand=lambda: 0.0)
    high = retry_delay_seconds(attempt, jitter=True, rand=lambda: 0.999999)
    assert low == pytest.approx(full / 2)
    assert full / 2 <= high <= full


def test_background_profile_uses_more_attempts_and_jitter():
    assert max_attempts() == 3
    calls = {"n": 0}
    delays: list[float] = []

    def fn() -> str:
        calls["n"] += 1
        raise RateLimitError(code=503, status="UNAVAILABLE")

    with background_retry_profile():
        assert max_attempts() == 5
        with pytest.raises(RateLimitError):
            retry_sync(fn, sleep=delays.append)
    assert max_attempts() == 3
    assert calls["n"] == 5
    assert len(delays) == 4
    for attempt, delay in enumerate(delays, start=1):
        full = retry_delay_seconds(attempt)
        assert full / 2 <= delay <= full


def test_background_profile_propagates_into_worker_threads():
    async def run() -> int:
        with background_retry_profile():
            return await asyncio.to_thread(max_attempts)

    assert asyncio.run(run()) == 5


def test_fallback_runs_after_primary_exhausts_capacity_errors():
    models: list[str] = []

    def call(model: str) -> str:
        models.append(model)
        if model == "primary-model":
            raise RateLimitError(code=503, status="UNAVAILABLE")
        return f"served-by-{model}"

    assert call_with_fallback_sync(call) == "served-by-fallback-model"
    assert models == ["primary-model", "fallback-model"]


def test_fallback_skipped_for_non_capacity_error():
    models: list[str] = []

    def call(model: str) -> str:
        models.append(model)
        raise RateLimitError(code=404, status="NOT_FOUND")

    with pytest.raises(RateLimitError) as info:
        call_with_fallback_sync(call)
    assert info.value.code == 404
    assert models == ["primary-model"]


@pytest.mark.parametrize("configured", ["", "  ", "primary-model", " , primary-model ,"])
def test_fallback_disabled_when_blank_or_same_as_primary(monkeypatch, configured):
    monkeypatch.setattr(gemini_client.settings, "GEMINI_FALLBACK_MODELS", configured)
    assert fallback_models() == []
    models: list[str] = []

    def call(model: str) -> str:
        models.append(model)
        raise RateLimitError(code=429)

    with pytest.raises(RateLimitError):
        call_with_fallback_sync(call)
    assert models == ["primary-model"]


def test_fallback_failure_raises_fallback_error_chained_to_primary():
    primary_exc = RateLimitError(code=503, status="UNAVAILABLE")
    fallback_exc = RateLimitError(code=429, status="RESOURCE_EXHAUSTED")

    def call(model: str) -> str:
        raise primary_exc if model == "primary-model" else fallback_exc

    with pytest.raises(RateLimitError) as info:
        call_with_fallback_sync(call)
    assert info.value is fallback_exc
    assert info.value.__cause__ is primary_exc


def test_fallback_chain_parses_in_order_without_duplicates(monkeypatch):
    monkeypatch.setattr(
        gemini_client.settings, "GEMINI_FALLBACK_MODELS", " second , primary-model, third,second "
    )
    assert fallback_models() == ["second", "third"]


def test_fallback_chain_walks_until_a_model_serves(monkeypatch):
    monkeypatch.setattr(gemini_client.settings, "GEMINI_FALLBACK_MODELS", "second,third")
    models: list[str] = []

    def call(model: str) -> str:
        models.append(model)
        if model == "primary-model":
            raise RateLimitError(code=429)
        if model == "second":
            raise RateLimitError(code=503, status="UNAVAILABLE")
        return model

    assert call_with_fallback_sync(call) == "third"
    assert models == ["primary-model", "second", "third"]


def test_fallback_chain_stops_on_non_capacity_error_midway(monkeypatch):
    monkeypatch.setattr(gemini_client.settings, "GEMINI_FALLBACK_MODELS", "second,third")
    models: list[str] = []

    def call(model: str) -> str:
        models.append(model)
        if model == "primary-model":
            raise RateLimitError(code=503, status="UNAVAILABLE")
        raise RateLimitError(code=404, status="NOT_FOUND")

    with pytest.raises(RateLimitError) as info:
        call_with_fallback_sync(call)
    assert info.value.code == 404
    assert info.value.__cause__.code == 503
    assert models == ["primary-model", "second"]


def test_deadline_scales_with_chain_length(monkeypatch):
    monkeypatch.setattr(gemini_client.settings, "GEMINI_FALLBACK_MODELS", "second,third")
    single = 45.0 * 3 + (2.0 + 4.0)
    assert overall_deadline_seconds() == pytest.approx(single * 3 + 1.0)


def test_async_fallback_runs_after_capacity_error():
    models: list[str] = []

    async def call(model: str) -> str:
        models.append(model)
        if model == "primary-model":
            raise RateLimitError(code=429)
        return model

    assert asyncio.run(call_with_fallback_async(call)) == "fallback-model"
    assert models == ["primary-model", "fallback-model"]


def test_deadline_covers_fallback_model():
    single = 45.0 * 3 + (2.0 + 4.0)
    assert overall_deadline_seconds() == pytest.approx(single * 2 + 1.0)


def test_served_model_prefers_reported_version():
    assert served_model(SimpleNamespace(model_version="fallback-model"), "primary-model") == "fallback-model"
    assert served_model(SimpleNamespace(model_version=None), "primary-model") == "primary-model"
