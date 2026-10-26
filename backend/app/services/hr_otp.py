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

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
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
from app.services.hr_membership import hr_display_name, upsert_hr_membership
from app.services.supabase_admin import (
    SupabaseAdminError,
    ensure_auth_user,
    find_auth_user_id_by_email,
)

logger = logging.getLogger("app.hr_otp")

# #region agent log
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEBUG_LOG_PATH = _REPO_ROOT / "debug-410e50.log"
_DEBUG_RUN_ID = "pre-fix"


def _agent_dbg(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    """Append one NDJSON debug line for HR OTP gate diagnosis."""
    payload = {
        "sessionId": "410e50",
        "runId": _DEBUG_RUN_ID,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    try:
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str) + "\n")
    except Exception:
        pass


# #endregion

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
        # #region agent log
        _agent_dbg(
            "E",
            "hr_otp.py:_assert_company_access",
            "reject_inactive_company",
            {"corporate_id": str(corporate.id)},
        )
        # #endregion
        raise HrOtpError(403, _INVALID_TARGET)
    contact = (corporate.contact_email or "").strip().lower()
    allowed = {str(entry).strip().lower() for entry in (corporate.allowed_hr_emails or [])}
    if email != contact and email not in allowed:
        # #region agent log
        _agent_dbg(
            "D",
            "hr_otp.py:_assert_company_access",
            "reject_whitelist_miss",
            {
                "email_domain": email.split("@")[-1] if "@" in email else "",
                "email_len": len(email),
                "contact_match": email == contact,
                "allowed_count": len(allowed),
                "in_allowed": email in allowed,
                "corporate_id": str(corporate.id),
            },
        )
        # #endregion
        raise HrOtpError(403, _INVALID_TARGET)
    # #region agent log
    _agent_dbg(
        "D",
        "hr_otp.py:_assert_company_access",
        "whitelist_ok",
        {
            "via_contact": email == contact,
            "via_allowed": email in allowed,
            "corporate_id": str(corporate.id),
        },
    )
    # #endregion


async def _find_corporate_by_hr_email(
    db: AsyncSession, email: str
) -> Corporate | None:
    """Return the active company that lists ``email`` as contact or allowed HR.

    Args:
        db: Async database session.
        email: Normalized login email.

    Returns:
        Matching ``Corporate``, or None when no active tenant whitelists the email.
    """
    corporates = (
        await db.execute(select(Corporate).where(Corporate.is_active.is_(True)))
    ).scalars().all()
    for corporate in corporates:
        contact = (corporate.contact_email or "").strip().lower()
        allowed = {
            str(entry).strip().lower() for entry in (corporate.allowed_hr_emails or [])
        }
        if email == contact or email in allowed:
            return corporate
    return None


async def _provision_whitelisted_hr(
    db: AsyncSession,
    email: str,
    *,
    existing_user_id: UUID | None = None,
) -> tuple[HRUser, Corporate] | None:
    """Create Auth + ``hr_users`` for a whitelist-only email (admin-added, not invited).

    Args:
        db: Async database session.
        email: Normalized login email.
        existing_user_id: Auth user id when the account already exists.

    Returns:
        ``(membership, corporate)`` when the email is on an active company whitelist;
        None when it is not registered to any company.

    Raises:
        HrOtpError: 503 when Auth Admin cannot create/resolve the user.
    """
    corporate = await _find_corporate_by_hr_email(db, email)
    if corporate is None:
        # #region agent log
        _agent_dbg(
            "A",
            "hr_otp.py:_provision_whitelisted_hr",
            "provision_no_company",
            {"email_domain": email.split("@")[-1] if "@" in email else ""},
        )
        # #endregion
        return None
    try:
        user_id = existing_user_id or await run_in_threadpool(ensure_auth_user, email)
    except SupabaseAdminError as exc:
        # #region agent log
        _agent_dbg(
            "A",
            "hr_otp.py:_provision_whitelisted_hr",
            "provision_auth_failed",
            {"error_type": type(exc).__name__, "corporate_id": str(corporate.id)},
        )
        # #endregion
        raise HrOtpError(503, _AUTH_DOWN) from exc

    await upsert_hr_membership(
        db,
        user_id=user_id,
        corporate_id=corporate.id,
        full_name=hr_display_name(email),
    )
    await db.flush()
    membership = (
        await db.execute(select(HRUser).where(HRUser.user_id == user_id))
    ).scalar_one_or_none()
    if membership is None:
        # #region agent log
        _agent_dbg(
            "B",
            "hr_otp.py:_provision_whitelisted_hr",
            "provision_membership_missing",
            {"user_id": str(user_id), "corporate_id": str(corporate.id)},
        )
        # #endregion
        return None
    # #region agent log
    _agent_dbg(
        "A",
        "hr_otp.py:_provision_whitelisted_hr",
        "provision_ok",
        {
            "user_id": str(user_id),
            "corporate_id": str(corporate.id),
            "had_existing_auth": existing_user_id is not None,
        },
    )
    # #endregion
    return membership, corporate


async def _resolve_membership(
    db: AsyncSession, email: str
) -> tuple[HRUser, Corporate]:
    """Map a login email to its non-ops ``hr_users`` row and tenant.

    Whitelisted emails added from admin (``contact_email`` / ``allowed_hr_emails``)
    but not yet invited are auto-provisioned into Auth + ``hr_users`` on first OTP
    request so portal login matches the admin whitelist.

    Args:
        db: Async database session.
        email: Cleaned, normalized login email.

    Returns:
        ``(membership, corporate)`` for a user who can complete HR login.

    Raises:
        HrOtpError: 403 unregistered / ops account / missing tenant,
            503 when the Auth Admin resolver is unavailable.
    """
    # #region agent log
    _agent_dbg(
        "A",
        "hr_otp.py:_resolve_membership",
        "resolve_start",
        {"email_domain": email.split("@")[-1] if "@" in email else "", "email_len": len(email)},
    )
    # #endregion
    try:
        user_id = await run_in_threadpool(find_auth_user_id_by_email, email)
    except SupabaseAdminError as exc:
        # #region agent log
        _agent_dbg(
            "A",
            "hr_otp.py:_resolve_membership",
            "auth_admin_unavailable",
            {"error_type": type(exc).__name__},
        )
        # #endregion
        raise HrOtpError(503, _AUTH_DOWN) from exc
    if user_id is None:
        # #region agent log
        _agent_dbg(
            "A",
            "hr_otp.py:_resolve_membership",
            "no_auth_user_try_provision",
            {"email_domain": email.split("@")[-1] if "@" in email else ""},
        )
        # #endregion
        provisioned = await _provision_whitelisted_hr(db, email)
        if provisioned is None:
            raise HrOtpError(403, _INVALID_TARGET)
        membership, corporate = provisioned
        if is_ops_role(membership.role):
            raise HrOtpError(403, _NOT_HR)
        _assert_company_access(corporate, email)
        return membership, corporate

    membership = (
        await db.execute(select(HRUser).where(HRUser.user_id == user_id))
    ).scalar_one_or_none()
    if membership is None:
        # #region agent log
        _agent_dbg(
            "B",
            "hr_otp.py:_resolve_membership",
            "no_hr_membership_try_provision",
            {"user_id": str(user_id)},
        )
        # #endregion
        provisioned = await _provision_whitelisted_hr(
            db, email, existing_user_id=user_id
        )
        if provisioned is None:
            raise HrOtpError(403, _INVALID_TARGET)
        membership, corporate = provisioned
        if is_ops_role(membership.role):
            raise HrOtpError(403, _NOT_HR)
        _assert_company_access(corporate, email)
        return membership, corporate
    if is_ops_role(membership.role):
        # #region agent log
        _agent_dbg(
            "C",
            "hr_otp.py:_resolve_membership",
            "reject_ops_role",
            {"role": membership.role},
        )
        # #endregion
        raise HrOtpError(403, _NOT_HR)

    corporate = (
        await db.execute(select(Corporate).where(Corporate.id == membership.corporate_id))
    ).scalar_one_or_none()
    if corporate is None:
        # #region agent log
        _agent_dbg(
            "E",
            "hr_otp.py:_resolve_membership",
            "reject_no_corporate",
            {"corporate_id": str(membership.corporate_id)},
        )
        # #endregion
        raise HrOtpError(403, _NO_COMPANY)
    _assert_company_access(corporate, email)
    # #region agent log
    _agent_dbg(
        "A",
        "hr_otp.py:_resolve_membership",
        "resolve_ok",
        {"user_id": str(user_id), "corporate_id": str(corporate.id), "role": membership.role},
    )
    # #endregion
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
    # #region agent log
    _agent_dbg(
        "A",
        "hr_otp.py:request_hr_otp",
        "send_start",
        {
            "email_domain": normalized_email.split("@")[-1] if "@" in normalized_email else "",
            "email_len": len(normalized_email),
            "raw_len": len(str(email or "")),
            "normalized_ok": bool(normalized_email and "@" in normalized_email),
        },
    )
    # #endregion
    if not normalized_email or "@" not in normalized_email:
        # #region agent log
        _agent_dbg(
            "A",
            "hr_otp.py:request_hr_otp",
            "reject_bad_email",
            {"reason": "unusable_email"},
        )
        # #endregion
        raise HrOtpError(400, _INVALID_TARGET)
    try:
        membership, _corporate = await _resolve_membership(db, normalized_email)
    except HrOtpError as exc:
        # #region agent log
        _agent_dbg(
            "A",
            "hr_otp.py:request_hr_otp",
            "reject_resolve",
            {
                "status_code": exc.status_code,
                "detail_code": (
                    "invalid_target"
                    if exc.detail == _INVALID_TARGET
                    else "not_hr"
                    if exc.detail == _NOT_HR
                    else "no_company"
                    if exc.detail == _NO_COMPANY
                    else "other"
                ),
            },
        )
        # #endregion
        raise

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
