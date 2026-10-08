"""Ops-only package preview renders the candidate payload without answer keys."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.schemas.client_package import PackagePreviewRequest
from app.services.client_package import ClientPackageError, ClientPackageService


def _module(**overrides):
    base = dict(
        id=uuid4(),
        title="CogniCheck",
        description=None,
        time_limit_minutes=None,
        duration_seconds=900,
        timer_mode="strict",
        shuffle_questions=False,
        is_active=True,
        questions=[
            {
                "id": "q1",
                "text": "Pick the odd one",
                "type": "sjt",
                "options": ["a", "b", "c", "d"],
                "option_weights": [3, 2, 1, 0],
                "sme_rationale": "secret",
            }
        ],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _session(rows):
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_preview_keeps_composer_order_and_strips_keys():
    first, second = _module(title="First"), _module(title="Second", timer_mode="flexible", duration_seconds=0)
    body = PackagePreviewRequest(module_ids=[second.id, first.id])

    out = await ClientPackageService.preview(_session([first, second]), body)

    assert [t.title for t in out] == ["Second", "First"]
    dumped = out[1].model_dump()
    assert dumped["timer_mode"] == "strict"
    assert dumped["duration_seconds"] == 900
    question = dumped["questions"][0]
    assert "option_weights" not in question
    assert "sme_rationale" not in question
    assert out[0].model_dump()["duration_seconds"] is None


@pytest.mark.asyncio
async def test_preview_uses_question_overrides():
    module = _module()
    body = PackagePreviewRequest(
        module_ids=[module.id],
        module_question_overrides={str(module.id): [{"id": "o1", "text": "Override", "type": "likert"}]},
    )

    out = await ClientPackageService.preview(_session([module]), body)

    assert out[0].questions[0].text == "Override"


@pytest.mark.asyncio
async def test_preview_rejects_missing_or_archived_modules():
    module = _module()
    body = PackagePreviewRequest(module_ids=[module.id, uuid4()])

    with pytest.raises(ClientPackageError, match="missing or archived"):
        await ClientPackageService.preview(_session([module]), body)


def test_preview_request_requires_at_least_one_module():
    with pytest.raises(ValueError):
        PackagePreviewRequest(module_ids=[])
