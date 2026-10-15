"""Admin email OTP: password proof, one-time code, then the withheld Supabase session.

The code is never stored. The database holds HMAC-SHA256(secret, challenge_id || code).
Three wrong codes lock that sign-in for 15 minutes. A new login supersedes any
open code. Retrying login is not idempotent: it invalidates the previous code,
subject to a per-account send cap so a stolen password cannot flood the inbox.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import jwt
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import or_, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import is_ops_role
from app.config import settings
from app.models.admin_login_challenge import AdminLoginChallenge
from app.models.hr_user import HRUser
from app.schemas.admin_auth import (
    AdminLoginChallengeResponse,
    AdminProfile,
    AdminTokenResponse,
)
from app.services.email import send_admin_otp_email
from app.services.supabase_password import (
    SupabaseAuthUnavailable,
    SupabasePasswordSession,
    revoke_supabase_session,
    verify_supabase_password,
)

logger = logging.getLogger("app.admin_auth")

OTP_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 3
LOCKOUT = timedelta(minutes=15)
MAX_SENDS_PER_WINDOW = 3
SEND_WINDOW = timedelta(minutes=15)
SEND_COOLDOWN = timedelta(seconds=60)
ADMIN_OTP_AUDIENCE = "mindq-admin-otp"
ADMIN_OTP_TYPE = "admin_otp"

_INVALID_CREDENTIALS = "Invalid email or password"
_INVALID_CODE = "Invalid or expired verification code"
_INVALID_SESSION = "Invalid or expired verification session"
_LOCKED = "Too many invalid codes. This sign-in is locked for 15 minutes."
_SEND_COOLDOWN = "A verification code was just sent. Wait a minute before requesting another."
_SEND_WINDOW_BLOCK = "Too many verification codes were requested. Try again later."
_NOT_ADMIN = "This account cannot access the admin portal"
_MAIL_FAILED = "Could not send the verification email. Try again."
_AUTH_DOWN = "Authentication service is unavailable"


class AdminLoginError(Exception):
    """Mapped to an HTTP error by the admin auth routes. Detail is client-safe."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def generate_otp() -> str:
    """Return a cryptographic six-digit code, including leading zeros.

    Returns:
        A string of exactly six digits.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(challenge_id: UUID, otp: str) -> str:
    """Keyed hash of a code bound to one challenge.

    Args:
        challenge_id: Challenge the code was issued for.
        otp: Six-digit code.

    Returns:
        Hex HMAC-SHA256. A database read without SECRET_KEY does not reveal the code.
    """
    mac = hmac.new(
        settings.SECRET_KEY.encode(),
        f"{challenge_id}:{otp}".encode(),
        hashlib.sha256,
    )
    return mac.hexdigest()


def otp_matches(challenge_id: UUID, otp: str, stored_hash: str) -> bool:
    """Constant-time check of a submitted code against the stored HMAC.

    Args:
        challenge_id: Challenge the temp token names.
        otp: Submitted code.
        stored_hash: HMAC saved at issue time. Empty after consume or lock.

    Returns:
        True only when the HMAC matches.
    """
    if not stored_hash or not otp:
        return False
    expected = hash_otp(challenge_id, otp)
    if len(expected) != len(stored_hash):
        return False
    return hmac.compare_digest(expected, stored_hash)


def issue_admin_otp_token(challenge_id: UUID, user_id: UUID) -> str:
    """Sign a five-minute token that only ``verify-otp`` accepts.

    Args:
        challenge_id: Row that holds the HMAC and the withheld session.
        user_id: Ops user the password grant authenticated.

    Returns:
        HS256 JWT. Audience and type are not those of an admin session.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "challenge_id": str(challenge_id),
        "typ": ADMIN_OTP_TYPE,
        "aud": ADMIN_OTP_AUDIENCE,
        "iat": now,
        "exp": now + OTP_TTL,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_admin_otp_token(token: str) -> tuple[UUID, UUID]:
    """Verify a temp token and return its challenge and user ids.

    Args:
        token: ``temp_token`` from the login response.

    Returns:
        ``(challenge_id, user_id)``.

    Raises:
        jwt.PyJWTError: Missing, expired, mistyped, or bad signature.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
        audience=ADMIN_OTP_AUDIENCE,
        options={"require": ["exp", "sub", "challenge_id"]},
    )
    if payload.get("typ") != ADMIN_OTP_TYPE:
        raise jwt.InvalidTokenError("wrong token type")
    return UUID(str(payload["challenge_id"])), UUID(str(payload["sub"]))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def send_block_reason(created_ats: list[datetime], now: datetime) -> str | None:
    """Decide whether another code email is allowed for this account.

    Args:
        created_ats: Challenge timestamps already inside the send window.
        now: Current UTC time.

    Returns:
        ``"cooldown"`` or ``"window"`` when a send must be refused, else None.
    """
    if not created_ats:
        return None
    latest = max(_aware(ts) for ts in created_ats)
    if now - latest < SEND_COOLDOWN:
        return "cooldown"
    recent = [ts for ts in created_ats if now - _aware(ts) < SEND_WINDOW]
    if len(recent) >= MAX_SENDS_PER_WINDOW:
        return "window"
    return None


def apply_otp_attempt(row: Any, otp: str, now: datetime) -> str:
    """Apply one code submission to a locked challenge row.

    Callers must hold a row lock. On lock, the code is burned and ``consumed_at``
    is set so a replay after the 15-minute window cannot start a new lock.

    Args:
        row: Challenge with ``id``, ``otp_hash``, ``expires_at``, ``attempt_count``,
            ``locked_until``, and ``consumed_at``.
        otp: Submitted code.
        now: Current UTC time.

    Returns:
        ``accepted``, ``rejected``, ``locked``, ``expired``, or ``consumed``.
    """
    locked_until = _aware(row.locked_until) if row.locked_until is not None else None
    if locked_until is not None and locked_until > now:
        return "locked"
    if row.consumed_at is not None:
        return "consumed"
    if _aware(row.expires_at) <= now:
        row.consumed_at = now
        row.otp_hash = ""
        return "expired"
    if not otp_matches(row.id, otp, row.otp_hash or ""):
        row.attempt_count = int(row.attempt_count) + 1
        if row.attempt_count >= MAX_ATTEMPTS:
            row.locked_until = now + LOCKOUT
            row.otp_hash = ""
            row.consumed_at = now
            return "locked"
        return "rejected"
    row.consumed_at = now
    row.otp_hash = ""
    return "accepted"


def _fernet() -> Fernet:
    """Fernet key derived from SECRET_KEY so a database backup is not a session store.

    Returns:
        Fernet instance for sealing withheld Supabase tokens.
    """
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal_secret(value: str) -> str:
    """Encrypt a session token before it is written.

    Args:
        value: Access or refresh token.

    Returns:
        Fernet token. The plaintext is not recoverable from the database alone.
    """
    return _fernet().encrypt(value.encode()).decode()


def unseal_secret(value: str | None) -> str | None:
    """Decrypt a session token, or return None when it is missing or corrupt.

    Args:
        value: Stored Fernet token.

    Returns:
        The original token, or None.
    """
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def _wipe_held_session(row: AdminLoginChallenge) -> None:
    row.access_token = None
    row.refresh_token = None


def _held_access_token(row: AdminLoginChallenge) -> str | None:
    return unseal_secret(row.access_token)


async def _ops_membership(db: AsyncSession, user_id: UUID) -> HRUser | None:
    row = (
        await db.execute(select(HRUser).where(HRUser.user_id == user_id))
    ).scalar_one_or_none()
    if row is None or not is_ops_role(row.role):
        return None
    return row


async def _is_locked(db: AsyncSession, user_id: UUID, now: datetime) -> bool:
    found = (
        await db.execute(
            select(AdminLoginChallenge.id)
            .where(
                AdminLoginChallenge.user_id == user_id,
                AdminLoginChallenge.locked_until.is_not(None),
                AdminLoginChallenge.locked_until > now,
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
                select(AdminLoginChallenge.created_at).where(
                    AdminLoginChallenge.user_id == user_id,
                    AdminLoginChallenge.created_at >= window_start,
                )
            )
        ).scalars().all()
    )


async def _supersede_open(db: AsyncSession, user_id: UUID, now: datetime) -> list[str]:
    """Burn every open, unlocked challenge and return session tokens to revoke.

    Args:
        db: Async database session.
        user_id: Admin whose previous codes must die.
        now: Current UTC time.

    Returns:
        Access tokens that were held for those challenges.
    """
    rows = (
        await db.execute(
            select(AdminLoginChallenge).where(
                AdminLoginChallenge.user_id == user_id,
                AdminLoginChallenge.consumed_at.is_(None),
            )
        )
    ).scalars().all()
    tokens: list[str] = []
    for row in rows:
        if row.locked_until is not None and _aware(row.locked_until) > now:
            continue
        raw = _held_access_token(row)
        if raw:
            tokens.append(raw)
        row.consumed_at = now
        row.otp_hash = ""
        _wipe_held_session(row)
    return tokens


def _send_block_error(reason: str) -> AdminLoginError:
    detail = _SEND_COOLDOWN if reason == "cooldown" else _SEND_WINDOW_BLOCK
    return AdminLoginError(429, detail)


async def _retire_expired(db: AsyncSession, now: datetime) -> None:
    """Revoke sessions whose codes have already expired.

    Called after a password succeeds so an abandoned login does not keep a
    refresh token until that same admin signs in again.

    Args:
        db: Async database session.
        now: Current UTC time.
    """
    rows = (
        await db.execute(
            select(AdminLoginChallenge)
            .where(
                AdminLoginChallenge.consumed_at.is_(None),
                AdminLoginChallenge.expires_at <= now,
                or_(
                    AdminLoginChallenge.locked_until.is_(None),
                    AdminLoginChallenge.locked_until <= now,
                ),
            )
            .limit(50)
        )
    ).scalars().all()
    if not rows:
        return
    tokens: list[str] = []
    for row in rows:
        raw = _held_access_token(row)
        if raw:
            tokens.append(raw)
        row.consumed_at = now
        row.otp_hash = ""
        _wipe_held_session(row)
    await db.commit()
    for token in tokens:
        await revoke_supabase_session(token)


async def _discard_password_session(session: SupabasePasswordSession) -> None:
    await revoke_supabase_session(session.access_token)


async def start_admin_login(
    db: AsyncSession, email: str, password: str
) -> AdminLoginChallengeResponse:
    """Validate the password, store a code, and email it.

    The Supabase access token is not returned. Callers retrying this route
    invalidate the previous code once the send cap and cooldown allow it.

    Args:
        db: Async database session.
        email: Admin email.
        password: Admin password.

    Returns:
        ``otp_required`` plus a signed temp token.

    Raises:
        AdminLoginError: 401 bad credentials, 403 non-admin, 429 lock or
            send cap, 503 when auth or mail is down.
    """
    normalized = email.strip().lower()
    try:
        session = await verify_supabase_password(normalized, password)
    except SupabaseAuthUnavailable as exc:
        raise AdminLoginError(503, _AUTH_DOWN) from exc
    if session is None or session.email != normalized:
        if session is not None:
            await _discard_password_session(session)
        raise AdminLoginError(401, _INVALID_CREDENTIALS)

    membership = await _ops_membership(db, session.user_id)
    if membership is None:
        await _discard_password_session(session)
        raise AdminLoginError(403, _NOT_ADMIN)

    now = datetime.now(timezone.utc)
    try:
        await _retire_expired(db, now)
        # Serializes the send-cap check and insert for this admin. Without it,
        # two parallel logins can both observe an empty window and send two codes.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(871423, hashtext(:key))"),
            {"key": str(session.user_id)},
        )
    except Exception:
        await _discard_password_session(session)
        raise
    if await _is_locked(db, session.user_id, now):
        await _discard_password_session(session)
        raise AdminLoginError(429, _LOCKED)

    block = send_block_reason(await _recent_sends(db, session.user_id, now), now)
    if block is not None:
        await _discard_password_session(session)
        raise _send_block_error(block)

    stale_tokens = await _supersede_open(db, session.user_id, now)
    challenge_id = uuid4()
    otp = generate_otp()
    row = AdminLoginChallenge(
        id=challenge_id,
        user_id=session.user_id,
        email=normalized,
        otp_hash=hash_otp(challenge_id, otp),
        expires_at=now + OTP_TTL,
        attempt_count=0,
        access_token=seal_secret(session.access_token),
        refresh_token=seal_secret(session.refresh_token),
        expires_in=session.expires_in,
        created_at=now,
    )
    db.add(row)
    try:
        await db.flush()
        await send_admin_otp_email(normalized, otp)
        await db.commit()
    except ProgrammingError:
        await db.rollback()
        await _discard_password_session(session)
        raise
    except Exception as exc:
        await db.rollback()
        await _discard_password_session(session)
        logger.error(
            "admin_otp_delivery_failed",
            extra={"event": "admin_otp_delivery_failed", "error_type": type(exc).__name__},
        )
        raise AdminLoginError(503, _MAIL_FAILED) from exc

    for token in stale_tokens:
        await revoke_supabase_session(token)

    logger.info(
        "admin_otp_issued",
        extra={"event": "admin_otp_issued", "user_id": str(session.user_id)},
    )
    return AdminLoginChallengeResponse(
        status="otp_required",
        temp_token=issue_admin_otp_token(challenge_id, session.user_id),
    )


async def verify_admin_otp(
    db: AsyncSession, temp_token: str, otp_code: str
) -> AdminTokenResponse:
    """Accept a one-time code and return the admin session withheld at login.

    Args:
        db: Async database session.
        temp_token: Signed token from ``start_admin_login``.
        otp_code: Six-digit code from the email.

    Returns:
        Supabase access and refresh tokens plus the ops profile.

    Raises:
        AdminLoginError: 401 bad session or code, 403 demoted user, 429 lock.
    """
    try:
        challenge_id, user_id = decode_admin_otp_token(temp_token)
    except jwt.PyJWTError as exc:
        raise AdminLoginError(401, _INVALID_SESSION) from exc

    row = (
        await db.execute(
            select(AdminLoginChallenge)
            .where(AdminLoginChallenge.id == challenge_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.user_id != user_id:
        raise AdminLoginError(401, _INVALID_SESSION)

    now = datetime.now(timezone.utc)
    access_token = _held_access_token(row)
    refresh_token = unseal_secret(row.refresh_token)
    expires_in = row.expires_in
    membership = await _ops_membership(db, user_id)
    if membership is None:
        row.consumed_at = now
        row.otp_hash = ""
        _wipe_held_session(row)
        await db.commit()
        if access_token:
            await revoke_supabase_session(access_token)
        raise AdminLoginError(403, _NOT_ADMIN)

    verdict = apply_otp_attempt(row, otp_code, now)
    if verdict in {"accepted", "locked", "expired"}:
        _wipe_held_session(row)
    await db.commit()

    if verdict == "accepted":
        if not access_token or not refresh_token:
            raise AdminLoginError(401, _INVALID_SESSION)
        logger.info(
            "admin_otp_verified",
            extra={"event": "admin_otp_verified", "user_id": str(user_id)},
        )
        return AdminTokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            user=AdminProfile(
                id=membership.user_id,
                email=row.email,
                full_name=membership.full_name,
                role=membership.role,
                corporate_id=membership.corporate_id,
            ),
        )

    if verdict == "locked":
        if access_token:
            await revoke_supabase_session(access_token)
        logger.info(
            "admin_otp_locked",
            extra={"event": "admin_otp_locked", "user_id": str(user_id)},
        )
        raise AdminLoginError(429, _LOCKED)

    if access_token and verdict == "expired":
        await revoke_supabase_session(access_token)
    logger.info(
        "admin_otp_rejected",
        extra={"event": "admin_otp_rejected", "user_id": str(user_id), "verdict": verdict},
    )
    raise AdminLoginError(401, _INVALID_CODE)
