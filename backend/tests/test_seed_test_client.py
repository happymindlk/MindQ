"""Seed script for the HR client portal: guards, idempotency, membership wiring."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.services.hr_membership import upsert_hr_membership
from scripts import seed_test_client as seed_mod
from scripts.seed_test_client import SeedError, SeedOptions, check_environment, seed


def _result(scalar: object = None, scalars: list | None = None, one: object = None):
    res = MagicMock()
    res.scalar_one_or_none.return_value = scalar
    res.scalar_one.return_value = one
    res.scalars.return_value.all.return_value = scalars or []
    return res


# ---------------------------------------------------------------------------
# Environment guard
# ---------------------------------------------------------------------------


def test_guard_blocks_non_debug_without_flag():
    with patch.object(seed_mod.settings, "DEBUG", False):
        with pytest.raises(SeedError, match="allow-non-debug"):
            check_environment(allow_non_debug=False)


def test_guard_allows_staging_opt_in_and_debug():
    with patch.object(seed_mod.settings, "DEBUG", False):
        check_environment(allow_non_debug=True)
    with patch.object(seed_mod.settings, "DEBUG", True):
        check_environment(allow_non_debug=False)


def test_main_returns_2_and_never_touches_db_when_guarded(capsys):
    with (
        patch.object(seed_mod.settings, "DEBUG", False),
        patch.object(seed_mod, "_run") as run,
    ):
        code = seed_mod.main(["--email", "hr@acme.test"])
    assert code == 2
    run.assert_not_called()
    assert "REFUSED" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# seed()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ops_email_refused_before_any_write():
    db = AsyncMock()
    ensure_user = MagicMock()
    upsert = AsyncMock()
    with (
        patch.object(seed_mod, "find_ops_role_for_email", AsyncMock(return_value="admin")),
        patch.object(seed_mod, "upsert_hr_membership", upsert),
    ):
        with pytest.raises(SeedError, match="ops"):
            await seed(db, SeedOptions(email="ops@happymind.test"), ensure_user=ensure_user)

    ensure_user.assert_not_called()
    upsert.assert_not_awaited()
    db.commit.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_links_auth_user_to_seeded_corporate():
    corp_id, user_id, pkg_id = uuid4(), uuid4(), uuid4()
    db = AsyncMock()
    upsert = AsyncMock()
    ensure_user = MagicMock(return_value=user_id)

    with (
        patch.object(seed_mod, "find_ops_role_for_email", AsyncMock(return_value=None)),
        patch.object(
            seed_mod, "_upsert_corporate", AsyncMock(return_value=SimpleNamespace(id=corp_id))
        ) as upsert_corp,
        patch.object(seed_mod, "upsert_hr_membership", upsert),
        patch.object(
            seed_mod,
            "_ensure_published_package",
            AsyncMock(return_value=(pkg_id, "ABC123", True)),
        ),
        patch.object(seed_mod, "_seed_candidates", AsyncMock(return_value=[uuid4()])),
    ):
        result = await seed(
            db,
            SeedOptions(email="  HR.Test+acme@Example.com ", company="Acme Test Co"),
            ensure_user=ensure_user,
        )

    ensure_user.assert_called_once_with("hr.test+acme@example.com")
    assert upsert_corp.await_args.kwargs["slug"] == "acme-test-co"
    upsert.assert_awaited_once()
    assert upsert.await_args.kwargs["user_id"] == user_id
    assert upsert.await_args.kwargs["corporate_id"] == corp_id
    db.commit.assert_awaited()
    assert result.package_id == pkg_id
    assert result.access_code == "ABC123"
    assert len(result.candidate_ids) == 1


def test_membership_upsert_is_hr_only_and_ops_guarded():
    db = AsyncMock()
    asyncio.run(
        upsert_hr_membership(db, user_id=uuid4(), corporate_id=uuid4(), full_name="Hr Test")
    )
    stmt = db.execute.await_args.args[0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    params = stmt.compile(dialect=postgresql.dialect()).params

    assert "ON CONFLICT (user_id) DO UPDATE" in sql
    assert "hr_users.role NOT IN" in sql
    assert params["role"] == "hr"


# ---------------------------------------------------------------------------
# Package + candidate idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_published_package_is_reused_not_republished():
    pkg_id = uuid4()
    db = AsyncMock()
    db.execute.return_value = _result(scalar=SimpleNamespace(id=pkg_id, access_code="XYZ789"))

    with (
        patch.object(seed_mod.ClientPackageService, "save_draft", AsyncMock()) as save,
        patch.object(seed_mod.ClientPackageService, "publish", AsyncMock()) as publish,
    ):
        out = await seed_mod._ensure_published_package(
            db, corporate_id=uuid4(), title="Backend Engineer Screen", target_role=None
        )

    assert out == (pkg_id, "XYZ789", False)
    save.assert_not_awaited()
    publish.assert_not_awaited()
    sql = str(db.execute.await_args.args[0])
    assert "packages.corporate_id" in sql and "packages.status" in sql


@pytest.mark.asyncio
async def test_missing_package_is_drafted_then_published():
    draft_id = uuid4()
    db = AsyncMock()
    db.execute.return_value = _result(scalar=None)

    with (
        patch.object(
            seed_mod.ClientPackageService,
            "save_draft",
            AsyncMock(return_value=SimpleNamespace(id=draft_id)),
        ) as save,
        patch.object(
            seed_mod.ClientPackageService,
            "publish",
            AsyncMock(return_value=SimpleNamespace(id=draft_id, access_code="NEW001")),
        ) as publish,
    ):
        out = await seed_mod._ensure_published_package(
            db, corporate_id=uuid4(), title="T", target_role="Engineer"
        )

    assert out == (draft_id, "NEW001", True)
    request = save.await_args.args[1]
    assert len(request.custom_questions) == 2
    publish.assert_awaited_once_with(db, draft_id)


@pytest.mark.asyncio
async def test_sample_candidates_cover_each_status():
    a1, a2 = uuid4(), uuid4()
    cand_ids = [uuid4(), uuid4(), uuid4()]
    db = AsyncMock()
    db.execute.side_effect = [
        _result(scalars=[a1, a2]),
        _result(one=cand_ids[0]),
        _result(one=cand_ids[1]),
        MagicMock(),
        _result(one=cand_ids[2]),
        MagicMock(),
        MagicMock(),
    ]

    ids = await seed_mod._seed_candidates(
        db, corporate_id=uuid4(), package_id=uuid4(), access_code="ABC123", count=3
    )

    assert ids == cand_ids
    statements = [call.args[0] for call in db.execute.await_args_list]
    progress = [s for s in statements if getattr(s, "table", None) is not None and s.table.name == "candidate_progress"]
    # invited: 0 rows, in_progress: 1 of 2, completed: 2 of 2
    assert len(progress) == 3
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_zero_candidates_skips_queries():
    db = AsyncMock()
    assert await seed_mod._seed_candidates(
        db, corporate_id=uuid4(), package_id=uuid4(), access_code="X", count=0
    ) == []
    db.execute.assert_not_awaited()
