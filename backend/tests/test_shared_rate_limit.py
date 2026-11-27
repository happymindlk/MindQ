"""P1-08: limiters share budgets through Redis, with a per-process fallback.

The Lua script itself runs only against a real Redis; these tests stub the
registered script to cover the Python glue: key namespacing, 429 mapping,
Retry-After from Redis' clock, the circuit breaker, and the local fallback.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app import security
from app.security import AuthFailureLimiter, RateLimiter


class _FakeScript:
    """Stands in for ``client.register_script(...)``; records calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, *, keys, args):
        self.calls.append((keys, args))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def shared_store(monkeypatch):
    def _install(responses):
        script = _FakeScript(responses)
        client = MagicMock()
        client.register_script.return_value = script
        security._store.configure(client)
        return script, client

    yield _install
    security._store.configure(None)


def test_allowed_hit_goes_to_redis_with_namespaced_key(shared_store):
    script, _ = shared_store([[1, 1, 0, 1_000_000]])
    limiter = RateLimiter(5, 60, name="candidate_otp_limiter")
    limiter.check("candidate_otp_send:1.2.3.4")
    keys, args = script.calls[0]
    assert keys == ["mindq:rl:candidate_otp_limiter:candidate_otp_send:1.2.3.4"]
    assert args[:3] == [60_000, 5, "hit"]
    # Nothing recorded locally: the budget lives in Redis.
    assert limiter._hits == {}


def test_redis_refusal_maps_to_429_with_retry_after(shared_store):
    now_ms = 1_000_000
    oldest_ms = now_ms - 45_000  # 15s left in a 60s window
    shared_store([[0, 5, oldest_ms, now_ms]])
    limiter = RateLimiter(5, 60, name="hr_otp_limiter")
    with pytest.raises(HTTPException) as exc:
        limiter.check("hr_otp_send:9.9.9.9")
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"] == "16"


def test_redis_error_opens_breaker_and_falls_back_locally(shared_store, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: clock[0])
    script, _ = shared_store([ConnectionError("redis down")])
    limiter = RateLimiter(2, 60, name="invite_limiter")

    limiter.check("candidate_invite:user:u1")  # Redis fails -> local
    limiter.check("candidate_invite:user:u1")  # breaker open -> local, no Redis call
    assert len(script.calls) == 1
    with pytest.raises(HTTPException):
        limiter.check("candidate_invite:user:u1")  # local budget of 2 enforced

    # After 30s the breaker closes and Redis is tried again.
    clock[0] += 31
    script.responses.append([1, 1, 0, 0])
    limiter.check("candidate_invite:user:u2")
    assert len(script.calls) == 2


def test_auth_failure_limiter_peek_and_add_modes(shared_store):
    script, _ = shared_store([[1, 3, 0, 0], [1, 4, 0, 0], [0, 5, 0, 60_000]])
    limiter = AuthFailureLimiter(5, 60, name="hr_login_failure_limiter")
    limiter.assert_allowed("hr_login:1.1.1.1")
    limiter.record_failure("hr_login:1.1.1.1")
    with pytest.raises(HTTPException) as exc:
        limiter.assert_allowed("hr_login:1.1.1.1")
    assert exc.value.status_code == 429
    assert [c[1][2] for c in script.calls] == ["peek", "add", "peek"]


def test_without_store_limits_stay_per_process():
    security._store.configure(None)
    limiter = RateLimiter(1, 60, name="t")
    limiter.check("k")
    with pytest.raises(HTTPException):
        limiter.check("k")


def test_local_fallback_evicts_idle_keys(monkeypatch):
    security._store.configure(None)
    monkeypatch.setattr(security, "_LOCAL_PRUNE_THRESHOLD", 3)
    clock = [0.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: clock[0])
    limiter = RateLimiter(10, 60, name="t")
    for i in range(3):
        limiter.check(f"k{i}")
    clock[0] = 120.0  # all three idle past the window
    limiter.check("fresh")
    assert set(limiter._hits) == {"fresh"}


def test_hr_success_does_not_clear_failures():
    import inspect

    from app.api.v1 import hr_auth

    assert "hr_login_failure_limiter.clear" not in inspect.getsource(hr_auth.verify_hr_otp)


def test_every_named_limiter_has_a_unique_namespace():
    names = [
        obj.name
        for obj in vars(security).values()
        if isinstance(obj, (RateLimiter, AuthFailureLimiter))
    ]
    assert len(names) == len(set(names))
    assert all(not n.startswith(("rl", "af")) or n.endswith("_limiter") for n in names)
