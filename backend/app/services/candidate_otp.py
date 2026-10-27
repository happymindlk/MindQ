"""Candidate email OTP: access-code proof, one-time code, then candidate login.

Mirrors the admin OTP discipline without a withheld session: the code is
never stored (HMAC-SHA256 keyed by SECRET_KEY and bound to the challenge),
three wrong codes lock the sign-in for a configurable window, and a new request
supersedes any open code subject to a per-email send cap.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

import jwt
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.candidate import Candidate
from app.models.candidate_login_challenge import CandidateLoginChallenge
from app.models.package import Package
from app.schemas.candidate import CandidateOtpChallengeResponse
from app.services.admin_otp import (
    OTP_TTL,
    SEND_WINDOW,
    apply_otp_attempt,
    generate_otp,
    hash_otp,
    locked_message,
    send_block_reason,
)
from app.services.candidate_service import CandidateService
from app.services.email import send_candidate_otp_email

logger = logging.getLogger("app.candidate_otp")

CANDIDATE_OTP_AUDIENCE = "mindq-candidate-otp"
CANDIDATE_OTP_TYPE = "candidate_otp"

_INVALID_TARGET = "Invalid access code or email"
_INVALID_CODE = "Invalid or expired verification code"
_INVALID_SESSION = "Invalid or expired verification session"
_LOCKED = locked_message()
_SEND_COOLDOWN = "A verification code was just sent. Wait a minute before requesting another."
_SEND_WINDOW_BLOCK = "Too many verification codes were requested. Try again later."
_MAIL_FAILED = "Could not send the verification email. Try again."


class CandidateOtpError(Exception):
    """Mapped to an HTTP error by the candidate routes. Detail is client-safe."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def issue_candidate_otp_token(challenge_id: UUID, email: str, access_code: str) -> str:
    """Sign a five-minute token that only the login route accepts.

    Args:
        challenge_id: Row that holds the HMAC.
        email: Normalized candidate email the code was sent to.
        access_code: Access code submitted with the request.

    Returns:
        HS256 JWT. Audience and type are not those of a candidate session.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "challenge_id": str(challenge_id),
        "email": email,
        "access_code": access_code,
        "typ": CANDIDATE_OTP_TYPE,
        "aud": CANDIDATE_OTP_AUDIENCE,
        "iat": now,
        "exp": now + OTP_TTL,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_candidate_otp_token(token: str) -> tuple[UUID, str, str]:
    """Verify a temp token and return its challenge, email, and access code.

    Args:
        token: ``temp_token`` from the request-code response.

    Returns:
        ``(challenge_id, email, access_code)``.

    Raises:
        jwt.PyJWTError: Missing, expired, mistyped, or bad signature.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
        audience=CANDIDATE_OTP_AUDIENCE,
        options={"require": ["exp", "sub", "challenge_id"]},
    )
    if payload.get("typ") != CANDIDATE_OTP_TYPE:
        raise jwt.InvalidTokenError("wrong token type")
    return (
        UUID(str(payload["challenge_id"])),
        str(payload.get("email") or payload["sub"]),
        str(payload.get("access_code") or ""),
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _validate_login_target(
    db: AsyncSession, access_code: str, email: str
) -> None:
    """Ensure the access code + email pair could complete a candidate login.

    Mirrors the read-only half of ``CandidateService.login`` so codes are
    only emailed for pairs that can actually sign in, failing generically
    to avoid leaking which half was wrong.

    Args:
        db: Async database session.
        access_code: Submitted package or per-candidate access code.
        email: Normalized candidate email.

    Raises:
        CandidateOtpError: 400 when the pair cannot sign in.
        PackageNotOpenError / PackageClosedError: Outside the login window.
    """
    package = (
        await db.execute(
            select(Package).where(
                Package.access_code.in_((access_code, access_code.upper())),
                Package.is_active.is_(True),
            )
        )
    ).scalars().first()

    if package is None:
        invited = (
            await db.execute(
                select(Candidate).where(
                    func.lower(Candidate.access_code) == access_code.lower()
                )
            )
        ).scalars().first()
        if invited is None or invited.email.lower() != email:
            raise CandidateOtpError(400, _INVALID_TARGET)
        invited_package = (
            await db.execute(select(Package).where(Package.id == invited.package_id))
        ).scalars().first()
        await CandidateService._ensure_login_window(db, invited_package, invited)
        return

    candidate = (
        await db.execute(
            select(Candidate).where(
                func.lower(Candidate.email) == email,
                Candidate.package_id == package.id,
            )
        )
    ).scalars().first()
    if candidate is None and not getattr(package, "allow_open_enrollment", False):
        raise CandidateOtpError(400, _INVALID_TARGET)
    await CandidateService._ensure_login_window(db, package, candidate)


async def _is_locked(db: AsyncSession, email: str, now: datetime) -> bool:
    found = (
        await db.execute(
            select(CandidateLoginChallenge.id)
            .where(
                CandidateLoginChallenge.email == email,
                CandidateLoginChallenge.locked_until.is_not(None),
                CandidateLoginChallenge.locked_until > now,
            )
            .limit(1)
        )
    ).first()
    return found is not None


async def _recent_sends(db: AsyncSession, email: str, now: datetime) -> list[datetime]:
    window_start = now - SEND_WINDOW
    return list(
        (
            await db.execute(
                select(CandidateLoginChallenge.created_at).where(
                    CandidateLoginChallenge.email == email,
                    CandidateLoginChallenge.created_at >= window_start,
                )
            )
        ).scalars().all()
    )


async def _supersede_open(db: AsyncSession, email: str, now: datetime) -> None:
    rows = (
        await db.execute(
            select(CandidateLoginChallenge).where(
                CandidateLoginChallenge.email == email,
                CandidateLoginChallenge.consumed_at.is_(None),
            )
        )
    ).scalars().all()
    for row in rows:
        if row.locked_until is not None and _aware(row.locked_until) > now:
            continue
        row.consumed_at = now
        row.otp_hash = ""


async def request_candidate_otp(
    db: AsyncSession, access_code: str, email: str
) -> CandidateOtpChallengeResponse:
    """Validate the target, store a code challenge, and email the code.

    Args:
        db: Async database session.
        access_code: Package or per-candidate access code.
        email: Candidate email (normalized here).

    Returns:
        ``otp_required`` plus a signed temp token.

    Raises:
        CandidateOtpError: 400 bad target, 429 lock or send cap, 503 mail down.
    """
    normalized_email = email.strip().lower()
    code_value = access_code.strip()
    await _validate_login_target(db, code_value, normalized_email)

    now = datetime.now(timezone.utc)
    # Serialize the send-cap check + insert per email, as in admin OTP.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(871424, hashtext(:key))"),
        {"key": normalized_email},
    )
    if await _is_locked(db, normalized_email, now):
        raise CandidateOtpError(429, _LOCKED)

    block = send_block_reason(await _recent_sends(db, normalized_email, now), now)
    if block is not None:
        detail = _SEND_COOLDOWN if block == "cooldown" else _SEND_WINDOW_BLOCK
        raise CandidateOtpError(429, detail)

    await _supersede_open(db, normalized_email, now)
    challenge_id = uuid4()
    otp = generate_otp()
    row = CandidateLoginChallenge(
        id=challenge_id,
        email=normalized_email,
        access_code=code_value,
        otp_hash=hash_otp(challenge_id, otp),
        expires_at=now + OTP_TTL,
        attempt_count=0,
        created_at=now,
    )
    db.add(row)
    try:
        await db.flush()
        await send_candidate_otp_email(normalized_email, otp)
        await db.commit()
    except ProgrammingError:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error(
            "candidate_otp_delivery_failed",
            extra={"event": "candidate_otp_delivery_failed", "error_type": type(exc).__name__},
        )
        raise CandidateOtpError(503, _MAIL_FAILED) from exc

    logger.info(
        "candidate_otp_issued",
        extra={"event": "candidate_otp_issued", "email": normalized_email},
    )
    return CandidateOtpChallengeResponse(
        status="otp_required",
        temp_token=issue_candidate_otp_token(challenge_id, normalized_email, code_value),
    )


async def verify_candidate_challenge(
    db: AsyncSession,
    *,
    temp_token: str,
    otp_code: str,
    email: str,
    access_code: str,
) -> None:
    """Consume a challenge when the submitted code matches.

    Args:
        db: Async database session.
        temp_token: Signed token from ``request_candidate_otp``.
        otp_code: Six-digit code from the email.
        email: Email submitted in the login payload.
        access_code: Access code submitted in the login payload.

    Raises:
        CandidateOtpError: 401 bad session/code, 429 locked.
    """
    try:
        challenge_id, token_email, token_code = decode_candidate_otp_token(temp_token)
    except jwt.PyJWTError as exc:
        raise CandidateOtpError(401, _INVALID_SESSION) from exc

    if token_email.strip().lower() != email.strip().lower() or (
        token_code and token_code.strip().lower() != access_code.strip().lower()
    ):
        raise CandidateOtpError(401, _INVALID_SESSION)

    row = (
        await db.execute(
            select(CandidateLoginChallenge)
            .where(CandidateLoginChallenge.id == challenge_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.email != token_email.strip().lower():
        raise CandidateOtpError(401, _INVALID_SESSION)

    verdict = apply_otp_attempt(row, otp_code, datetime.now(timezone.utc))
    await db.commit()

    if verdict == "accepted":
        logger.info(
            "candidate_otp_verified",
            extra={"event": "candidate_otp_verified", "email": row.email},
        )
        return
    if verdict == "locked":
        raise CandidateOtpError(429, _LOCKED)
    raise CandidateOtpError(401, _INVALID_CODE)
