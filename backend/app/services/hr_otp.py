"""HR/client email OTP: inbox proof, one-time code, then a backend client JWT.

Mirrors the candidate OTP discipline for the HR & Client Portal: the code
is never stored (HMAC-SHA256 keyed by SECRET_KEY and bound to the
challenge), three wrong codes lock the sign-in for 15 minutes, and a new
request supersedes any open code subject to a per-user send cap. No
Supabase Auth email or session is involved; the email -> ``hr_users``
mapping is resolved server-side and the session minted at verify is the
backend ``client_hr`` JWT (``issue_client_token``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

import jwt
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth import is_ops_role, issue_client_token
from app.config import settings
from app.models.corporate import Corporate
from app.models.hr_login_challenge import HrLoginChallenge
from app.models.hr_user import HRUser
from app.schemas.client_package import ClientCorporate
from app.schemas.hr_auth import HrOtpChallengeResponse, HrProfile, HrTokenResponse
from app.services.admin_otp import (
    OTP_TTL,
    SEND_WINDOW,
    apply_otp_attempt,
    generate_otp,
    hash_otp,
    send_block_reason,
)
from app.services.email import clean_recipient_email, send_hr_otp_email
from app.services.supabase_admin import SupabaseAdminError, find_auth_user_id_by_email

logger = logging.getLogger("app.hr_otp")

HR_OTP_AUDIENCE = "mindq-hr-otp"
HR_OTP_TYPE = "hr_otp"

_INVALID_TARGET = "This email is not registered for the client portal"
_NOT_HR = "Operations accounts must use the admin portal"
_NO_COMPANY = "Company not found"
_INVALID_CODE = "Invalid or expired verification code"
_INVALID_SESSION = "Invalid or expired verification session"
_LOCKED = "Too many invalid codes. This sign-in is locked for 15 minutes."
_SEND_COOLDOWN = "A verification code was just sent. Wait a minute before requesting another."
_SEND_WINDOW_BLOCK = "Too many verification codes were requested. Try again later."
_MAIL_FAILED = "Could not send the verification email. Try again."
_AUTH_DOWN = "Authentication service is unavailable"


class HrOtpError(Exception):
    """Mapped to an HTTP error by the HR auth routes. Detail is client-safe."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def issue_hr_otp_token(challenge_id: UUID, user_id: UUID, email: str) -> str:
    """Sign a five-minute token that only the HR verify route accepts.

    Args:
        challenge_id: Row that holds the HMAC.
        user_id: HR user the code was issued for.
        email: Normalized email the code was sent to.

    Returns:
        HS256 JWT. Audience and type are not those of a client session.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "challenge_id": str(challenge_id),
        "email": email,
        "typ": HR_OTP_TYPE,
        "aud": HR_OTP_AUDIENCE,
        "iat": now,
        "exp": now + OTP_TTL,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_hr_otp_token(token: str) -> tuple[UUID, UUID, str]:
    """Verify a temp token and return its challenge, user, and email.

    Args:
        token: ``temp_token`` from the request-code response.

    Returns:
        ``(challenge_id, user_id, email)``.

    Raises:
        jwt.PyJWTError: Missing, expired, mistyped, or bad signature.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
        audience=HR_OTP_AUDIENCE,
        options={"require": ["exp", "sub", "challenge_id"]},
    )
    if payload.get("typ") != HR_OTP_TYPE:
        raise jwt.InvalidTokenError("wrong token type")
    return (
        UUID(str(payload["challenge_id"])),
        UUID(str(payload["sub"])),
        str(payload.get("email") or ""),
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _assert_company_access(corporate: Corporate, email: str) -> None:
    """Require an active company whose HR whitelist contains ``email``.

    Accepts the login email when it matches ``contact_email`` or appears in
    ``allowed_hr_emails`` (both compared case-insensitively after strip).

    Args:
        corporate: Tenant the membership points at.
        email: Normalized login email.

    Raises:
        HrOtpError: 403 with the generic unregistered detail (no tenant leak).
    """
    if corporate.is_active is False:
        raise HrOtpError(403, _INVALID_TARGET)
    contact = (corporate.contact_email or "").strip().lower()
    allowed = {str(entry).strip().lower() for entry in (corporate.allowed_hr_emails or [])}
    if email != contact and email not in allowed:
        raise HrOtpError(403, _INVALID_TARGET)


async def _resolve_membership(
    db: AsyncSession, email: str
) -> tuple[HRUser, Corporate]:
    """Map a login email to its non-ops ``hr_users`` row and tenant.

    Args:
        db: Async database session.
        email: Cleaned, normalized login email.

    Returns:
        ``(membership, corporate)`` for a user who can complete HR login.

    Raises:
        HrOtpError: 403 unregistered / ops account / missing tenant,
            503 when the Auth Admin resolver is unavailable.
    """
    try:
        user_id = await run_in_threadpool(find_auth_user_id_by_email, email)
    except SupabaseAdminError as exc:
        raise HrOtpError(503, _AUTH_DOWN) from exc
    if user_id is None:
        raise HrOtpError(403, _INVALID_TARGET)

    membership = (
        await db.execute(select(HRUser).where(HRUser.user_id == user_id))
    ).scalar_one_or_none()
    if membership is None:
        raise HrOtpError(403, _INVALID_TARGET)
    if is_ops_role(membership.role):
        raise HrOtpError(403, _NOT_HR)

    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == membership.corporate_id))
    ).scalar_one_or_none()
    if corporate is None:
        raise HrOtpError(403, _NO_COMPANY)
    _assert_company_access(corporate, email)
    return membership, corporate


async def _is_locked(db: AsyncSession, user_id: UUID, now: datetime) -> bool:
    found = (
        await db.execute(
            select(HrLoginChallenge.id)
            .where(
                HrLoginChallenge.user_id == user_id,
                HrLoginChallenge.locked_until.is_not(None),
                HrLoginChallenge.locked_until > now,
            )
            .limit(1)
        )
    ).first()
    return found is not None


async def _recent_sends(db: AsyncSession, user_id: UUID, now: datetime) -> list[datetime]:
    window_start = now - SEND_WINDOW
    return list(
        (
            await db.execute(
                select(HrLoginChallenge.created_at).where(
                    HrLoginChallenge.user_id == user_id,
                    HrLoginChallenge.created_at >= window_start,
                )
            )
        ).scalars().all()
    )


async def _supersede_open(db: AsyncSession, user_id: UUID, now: datetime) -> None:
    rows = (
        await db.execute(
            select(HrLoginChallenge).where(
                HrLoginChallenge.user_id == user_id,
                HrLoginChallenge.consumed_at.is_(None),
            )
        )
    ).scalars().all()
    for row in rows:
        if row.locked_until is not None and _aware(row.locked_until) > now:
            continue
        row.consumed_at = now
        row.otp_hash = ""


async def request_hr_otp(db: AsyncSession, email: str) -> HrOtpChallengeResponse:
    """Validate the HR user, store a code challenge, and email the code via SES.

    Args:
        db: Async database session.
        email: Corporate email (cleaned and normalized here).

    Returns:
        ``otp_required`` plus a signed temp token.

    Raises:
        HrOtpError: 400 unusable email, 403 unregistered/ops, 429 lock or
            send cap, 503 mail or identity resolver down.
    """
    normalized_email = clean_recipient_email(email).lower()
    if not normalized_email or "@" not in normalized_email:
        raise HrOtpError(400, _INVALID_TARGET)
    membership, _corporate = await _resolve_membership(db, normalized_email)

    now = datetime.now(timezone.utc)
    # Serialize the send-cap check + insert per user, as in admin/candidate OTP.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(871425, hashtext(:key))"),
        {"key": str(membership.user_id)},
    )
    if await _is_locked(db, membership.user_id, now):
        raise HrOtpError(429, _LOCKED)

    block = send_block_reason(await _recent_sends(db, membership.user_id, now), now)
    if block is not None:
        detail = _SEND_COOLDOWN if block == "cooldown" else _SEND_WINDOW_BLOCK
        raise HrOtpError(429, detail)

    await _supersede_open(db, membership.user_id, now)
    challenge_id = uuid4()
    otp = generate_otp()
    row = HrLoginChallenge(
        id=challenge_id,
        user_id=membership.user_id,
        email=normalized_email,
        otp_hash=hash_otp(challenge_id, otp),
        expires_at=now + OTP_TTL,
        attempt_count=0,
        created_at=now,
    )
    db.add(row)
    try:
        await db.flush()
        await send_hr_otp_email(normalized_email, otp)
        await db.commit()
    except ProgrammingError:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        logger.error(
            "hr_otp_delivery_failed",
            extra={"event": "hr_otp_delivery_failed", "error_type": type(exc).__name__},
        )
        raise HrOtpError(503, _MAIL_FAILED) from exc

    logger.info(
        "hr_otp_issued",
        extra={"event": "hr_otp_issued", "user_id": str(membership.user_id)},
    )
    return HrOtpChallengeResponse(
        status="otp_required",
        temp_token=issue_hr_otp_token(challenge_id, membership.user_id, normalized_email),
    )


async def verify_hr_challenge(
    db: AsyncSession,
    *,
    temp_token: str,
    otp_code: str,
    email: str,
) -> HrTokenResponse:
    """Consume a challenge when the submitted code matches and mint the session.

    Args:
        db: Async database session.
        temp_token: Signed token from ``request_hr_otp``.
        otp_code: Six-digit code from the email.
        email: Email submitted in the login payload.

    Returns:
        Backend ``client_hr`` JWT, tenant branding, and the HR profile.

    Raises:
        HrOtpError: 401 bad session/code, 403 membership revoked or ops,
            429 locked.
    """
    try:
        challenge_id, user_id, token_email = decode_hr_otp_token(temp_token)
    except jwt.PyJWTError as exc:
        raise HrOtpError(401, _INVALID_SESSION) from exc

    normalized_email = clean_recipient_email(email).lower()
    if token_email.strip().lower() != normalized_email:
        raise HrOtpError(401, _INVALID_SESSION)

    row = (
        await db.execute(
            select(HrLoginChallenge)
            .where(HrLoginChallenge.id == challenge_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.user_id != user_id or row.email != token_email.strip().lower():
        raise HrOtpError(401, _INVALID_SESSION)

    now = datetime.now(timezone.utc)
    membership = (
        await db.execute(select(HRUser).where(HRUser.user_id == user_id))
    ).scalar_one_or_none()
    if membership is None or is_ops_role(membership.role):
        row.consumed_at = now
        row.otp_hash = ""
        await db.commit()
        raise HrOtpError(403, _NOT_HR if membership is not None else _INVALID_TARGET)

    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == membership.corporate_id))
    ).scalar_one_or_none()
    if corporate is None:
        row.consumed_at = now
        row.otp_hash = ""
        await db.commit()
        raise HrOtpError(403, _NO_COMPANY)
    try:
        _assert_company_access(corporate, normalized_email)
    except HrOtpError:
        row.consumed_at = now
        row.otp_hash = ""
        await db.commit()
        raise

    verdict = apply_otp_attempt(row, otp_code, now)
    await db.commit()

    if verdict == "accepted":
        token, expires_in = issue_client_token(user_id, corporate.id, row.email)
        logger.info(
            "hr_otp_verified",
            extra={"event": "hr_otp_verified", "user_id": str(user_id)},
        )
        return HrTokenResponse(
            access_token=token,
            expires_in=expires_in,
            corporate=ClientCorporate(
                id=corporate.id, name=corporate.name, logo_url=corporate.logo_url
            ),
            user=HrProfile(
                id=membership.user_id,
                email=row.email,
                full_name=membership.full_name,
                role=membership.role,
                corporate_id=membership.corporate_id,
            ),
        )
    if verdict == "locked":
        raise HrOtpError(429, _LOCKED)
    raise HrOtpError(401, _INVALID_CODE)
