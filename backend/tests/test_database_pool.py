"""Regression lock for the Supavisor-tuned async engine pool."""

from app.database import engine


def test_async_engine_pool_matches_production_sizing():
    """Keep capacity at 15+35 with recycle before the ~5m idle cut.

    Shrinking to 10/20/300 would cut concurrent checkouts and race Supavisor
    idle disconnects; this test prevents accidental drift.
    """
    pool = engine.sync_engine.pool
    assert pool.size() == 15
    assert pool._max_overflow == 35
    assert pool._recycle == 280
    assert pool._pre_ping is True
