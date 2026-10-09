#!/usr/bin/env python3
"""API-level E2E: package → candidate login → autosave → submit → score → report.

Requires local Supabase Postgres + running FastAPI (port 8000) with DATABASE_URL
pointing at it and CANDIDATE_OTP_REQUIRED=false (this script cannot read OTP emails).
Optional GEMINI_API_KEY for JD fit (otherwise status=skipped/failed).

Usage (from repo root, with backend venv activated):
  python scripts/e2e_candidate_loop.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

API = os.getenv("E2E_API_URL", "http://127.0.0.1:8000")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@127.0.0.1:54322/postgres",
)


async def seed_package(engine) -> tuple[str, uuid.UUID, uuid.UUID]:
    corp_id = uuid.uuid4()
    pkg_id = uuid.uuid4()
    assessment_id = uuid.uuid4()
    access_code = f"HM-E2E{uuid.uuid4().hex[:4].upper()}-Z"
    track_secret = uuid.uuid4().hex + uuid.uuid4().hex[:16]
    questions = [
        {
            "id": "q1",
            "text": "2+2?",
            "type": "mcq",
            "options": ["3", "4"],
            "correct_answer": "4",
        },
        {
            "id": "q2",
            "text": "Describe a production incident.",
            "type": "open",
            "options": [],
        },
    ]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "insert into corporates (id, name, slug) values (:id, :name, :slug)"
            ),
            {"id": corp_id, "name": "E2E Corp", "slug": f"e2e-{corp_id.hex[:8]}"},
        )
        await conn.execute(
            text(
                "insert into packages (id, corporate_id, title, description, access_code, track_secret, allow_open_enrollment) "
                "values (:id, :corp, :title, :desc, :code, :secret, true)"
            ),
            {
                "id": pkg_id,
                "corp": corp_id,
                "title": "E2E Package",
                "desc": "Backend engineer. Python, Postgres, APIs.",
                "code": access_code,
                "secret": track_secret,
            },
        )
        await conn.execute(
            text(
                "insert into assessments (id, corporate_id, package_id, title, position, questions) "
                "values (:id, :corp, :pkg, :title, 0, cast(:questions as jsonb))"
            ),
            {
                "id": assessment_id,
                "corp": corp_id,
                "pkg": pkg_id,
                "title": "Core",
                "questions": __import__("json").dumps(questions),
            },
        )
    return access_code, assessment_id, track_secret


async def main() -> int:
    engine = create_async_engine(DATABASE_URL)
    try:
        access_code, assessment_id, track_secret = await seed_package(engine)
    except Exception as exc:  # noqa: BLE001
        print("SEED FAILED (is Postgres up and migrations applied?):", exc)
        return 1

    async with httpx.AsyncClient(base_url=API, timeout=60.0) as client:
        health = await client.get("/health")
        health.raise_for_status()

        login = await client.post(
            "/api/v1/candidate/login",
            json={
                "first_name": "E2E",
                "full_name": "E2E Candidate",
                "email": f"e2e-{uuid.uuid4().hex[:8]}@example.com",
                "access_code": access_code,
            },
        )
        login.raise_for_status()
        body = login.json()
        token = body["token"]
        headers = {"Authorization": f"Bearer {token}"}

        test = await client.get(f"/api/v1/candidate/test/{assessment_id}", headers=headers)
        test.raise_for_status()
        questions = test.json()["questions"]
        assert all("correct_answer" not in q for q in questions), "MCQ keys leaked to client"

        r1 = await client.post(
            "/api/v1/candidate/autosave",
            headers=headers,
            json={
                "assessment_id": str(assessment_id),
                "question_id": "q1",
                "response": {"answer": "4"},
            },
        )
        r1.raise_for_status()
        r2 = await client.post(
            "/api/v1/candidate/autosave",
            headers=headers,
            json={
                "assessment_id": str(assessment_id),
                "question_id": "q2",
                "response": {"answer": "We rolled back a bad deploy within 10 minutes."},
            },
        )
        r2.raise_for_status()

        submit = await client.post(
            f"/api/v1/candidate/test/{assessment_id}/submit", headers=headers
        )
        submit.raise_for_status()
        submit_body = submit.json()
        assert submit_body["score"] == 100.0, submit_body
        assert submit_body.get("jd_scoring_queued") is True

        # Second submit must lock.
        locked = await client.post(
            f"/api/v1/candidate/test/{assessment_id}/submit", headers=headers
        )
        assert locked.status_code == 409, locked.text

        track = await client.get(f"/api/v1/track/{track_secret}")
        track.raise_for_status()
        track_body = track.json()
        assert track_body["package_title"] == "E2E Package"
        assert len(track_body["candidates"]) >= 1

        support = await client.post(
            "/api/v1/support/submit",
            json={"details": "E2E support ticket", "path": "/portal/test"},
        )
        support.raise_for_status()

    print("E2E PASS")
    print(f"  access_code={access_code}")
    print(f"  score={submit_body['score']}")
    print(f"  public_track=/public/track/{track_secret}")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
