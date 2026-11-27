"""P1-08: run the sliding-window Lua script on a real Redis engine (fakeredis[lua]).

Complements tests/test_shared_rate_limit.py (which stubs the script) by
executing the actual Lua: atomic count/refuse, Redis TIME, TTL eviction,
and budgets shared by two limiter instances standing in for two nodes.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

fakeredis = pytest.importorskip("fakeredis")
pytest.importorskip("lupa")  # Lua support for EVAL / register_script

from app import security  # noqa: E402
from app.security import AuthFailureLimiter, RateLimiter  # noqa: E402


@pytest.fixture
def redis_engine():
    client = fakeredis.FakeRedis()
    security._store.configure(client)
    yield client
    security._store.configure(None)
    client.close()


def test_budget_is_enforced_inside_redis(redis_engine):
    limiter = RateLimiter(3, 60, name="candidate_otp_limiter")
    for _ in range(3):
        limiter.check("candidate_otp_send:1.2.3.4")
    with pytest.raises(HTTPException) as exc:
        limiter.check("candidate_otp_send:1.2.3.4")
    assert exc.value.status_code == 429
    retry_after = int(exc.value.headers["Retry-After"])
    assert 1 <= retry_after <= 61
    # Counted in Redis, not in process memory.
    assert limiter._hits == {}
    key = "mindq:rl:candidate_otp_limiter:candidate_otp_send:1.2.3.4"
    assert redis_engine.zcard(key) == 3


def test_two_nodes_share_one_budget(redis_engine):
    node_a = RateLimiter(2, 60, name="hr_otp_limiter")
    node_b = RateLimiter(2, 60, name="hr_otp_limiter")  # same name, other process
    node_a.check("hr_otp_send:9.9.9.9")
    node_b.check("hr_otp_send:9.9.9.9")
    with pytest.raises(HTTPException):
        node_a.check("hr_otp_send:9.9.9.9")
    with pytest.raises(HTTPException):
        node_b.check("hr_otp_send:9.9.9.9")


def test_keys_get_a_ttl_so_idle_buckets_evict(redis_engine):
    RateLimiter(5, 60, name="invite_limiter").check("candidate_invite:user:u1")
    ttl_ms = redis_engine.pttl("mindq:rl:invite_limiter:candidate_invite:user:u1")
    assert 0 < ttl_ms <= 60_000


def test_refused_hits_are_not_recorded(redis_engine):
    limiter = RateLimiter(1, 60, name="t_refused")
    limiter.check("k")
    for _ in range(5):
        with pytest.raises(HTTPException):
            limiter.check("k")
    assert redis_engine.zcard("mindq:rl:t_refused:k") == 1


def test_different_limiters_do_not_share_keys(redis_engine):
    RateLimiter(1, 60, name="a_limiter").check("same:key")
    RateLimiter(1, 60, name="b_limiter").check("same:key")  # separate budget


def test_auth_failure_limiter_on_real_engine(redis_engine):
    limiter = AuthFailureLimiter(2, 60, name="hr_login_failure_limiter")
    key = "hr_login:5.5.5.5"
    limiter.assert_allowed(key)  # peek does not count
    limiter.record_failure(key)
    limiter.assert_allowed(key)
    limiter.record_failure(key)
    with pytest.raises(HTTPException) as exc:
        limiter.assert_allowed(key)
    assert exc.value.status_code == 429
    limiter.clear(key)  # admin unlock path deletes the Redis key
    limiter.assert_allowed(key)
