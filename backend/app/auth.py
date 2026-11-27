"""Authentication helpers for the thin FastAPI service.

Two independent token types:
- Candidate tokens: signed by THIS service with SECRET_KEY after the candidate
  verifies a one-time email code issued by THIS service (SES-delivered OTP
  challenge in ``candidate_login_challenges``). The challenge temp token is a
  one-shot proof, never a candidate session.
- HR tokens: access tokens minted by Supabase Auth, verified with
  SUPABASE_JWT_SECRET. The tenant (`corporate_id`) is read from app_metadata.
- Client-portal tokens: minted by THIS service after an email OTP verified by
  THIS service (SES-delivered challenge in ``hr_login_challenges``), signed
  with SECRET_KEY under a dedicated audience so they can never satisfy
  ops/HR dependencies (and Supabase tokens never satisfy client dependencies).
"""
import asyncio
from uuid import UUID
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import func, or_, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.config import settings
from app.database import get_db
from app.models.candidate import Candidate
from app.services.candidate_service import CandidateService

CANDIDATE_AUDIENCE = "happy-mind-candidate"
CLIENT_AUDIENCE = "mindq-client"
CLIENT_ROLE = "client_hr"


def issue_candidate_token(candidate: Candidate) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(candidate.id),
        "corporate_id": str(candidate.corporate_id),
        "package_id": str(candidate.package_id),
        "typ": "candidate",
        "aud": CANDIDATE_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.CANDIDATE_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.split(" ", 1)[1].strip()


def candidate_id_from_authorization(authorization: str | None) -> UUID | None:
    """Verified candidate id from an optional ``Authorization`` header.

    For endpoints where auth is optional (support form): never raises, and
    returns None for a missing, malformed, expired or non-candidate token.

    Args:
        authorization: Raw ``Authorization`` header value.

    Returns:
        The token's candidate id, or None.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=["HS256"], audience=CANDIDATE_AUDIENCE
        )
        if payload.get("typ") != "candidate":
            return None
        return UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        return None


async def get_current_candidate(
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Candidate:
    token = _bearer(authorization)
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=["HS256"], audience=CANDIDATE_AUDIENCE
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("typ") != "candidate":
        raise HTTPException(status_code=401, detail="Invalid token type")
    try:
        candidate_id = UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")
    candidate = await CandidateService.get_candidate(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=401, detail="Candidate not found")
    await touch_last_seen_throttled(db, candidate)
    return candidate


# P2-06: autosave fires many authenticated requests per minute; stamping
# ``session_last_seen_at`` on each one made ``candidates`` a hot row (UPDATE +
# COMMIT + refresh per request). The device lock window is 3 minutes, so a
# 60 s resolution is plenty.
LAST_SEEN_THROTTLE_SECONDS = 60


async def touch_last_seen_throttled(db: AsyncSession, candidate: Candidate) -> bool:
    """Refresh ``session_last_seen_at`` at most once per throttle window.

    One conditional ``UPDATE ... WHERE session_last_seen_at < now() - 60s``
    on the database clock: inside the window it matches no row, so nothing is
    written and no commit is issued.

    Args:
        db: Request session.
        candidate: Authenticated candidate (in-memory copy updated on write).

    Returns:
        True when the row was written.
    """
    stale_before = func.now() - text(f"interval '{LAST_SEEN_THROTTLE_SECONDS} seconds'")
    result = await db.execute(
        update(Candidate)
        .where(
            Candidate.id == candidate.id,
            or_(
                Candidate.session_last_seen_at.is_(None),
                Candidate.session_last_seen_at < stale_before,
            ),
        )
        .values(session_last_seen_at=func.now())
        .returning(Candidate.session_last_seen_at)
        .execution_options(synchronize_session=False)
    )
    stamp = result.scalar_one_or_none()
    if stamp is None:
        return False
    await db.commit()
    # Keep the loaded instance in step without a refresh round trip.
    set_committed_value(candidate, "session_last_seen_at", stamp)
    return True


class SupabaseUserContext:
    """Authenticated Supabase Auth user (corporate_id optional / gated beta)."""

    def __init__(
        self,
        user_id: UUID,
        email: str | None = None,
        corporate_id: UUID | None = None,
        role: str | None = None,
    ):
        self.user_id = user_id
        self.email = email
        self.corporate_id = corporate_id
        self.role = role


class HRUserContext:
    """Resolved identity of an authenticated HR user from a Supabase JWT."""

    def __init__(self, user_id: UUID, corporate_id: UUID, email: str | None = None, role: str | None = None):
        self.user_id = user_id
        self.corporate_id = corporate_id
        self.email = email
        self.role = role

# Cached JWKS client for asymmetric tokens (local `supabase start` uses ES256).
# PyJWKClient fetches via synchronous urllib; never call that on the event loop.
_jwks_client: jwt.PyJWKClient | None = None
_jwks_lock = asyncio.Lock()
# kid → public key material. Survives PyJWKClient's 5-minute set refresh so hot
# paths stay local after the first successful resolve.
_signing_keys_by_kid: dict[str, Any] = {}
_ASYMMETRIC_ALGS = frozenset({"ES256", "RS256"})


def _jwks() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
        _jwks_client = jwt.PyJWKClient(url)
    return _jwks_client


def _resolve_signing_key_sync(token: str) -> Any:
    """Blocking JWKS lookup (urllib). Must run off the event loop via to_thread."""
    return _jwks().get_signing_key_from_jwt(token).key


async def _signing_key_for_token(token: str) -> Any:
    """Return the asymmetric public key for ``token``, caching by ``kid``.

    Cache hits are pure memory. Cache misses run ``PyJWKClient`` in a worker
    thread so a JWKS HTTP round-trip cannot freeze FastAPI's event loop when many
    authenticated requests arrive together (the frontend waterfall case).
    """
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    if isinstance(kid, str) and kid in _signing_keys_by_kid:
        return _signing_keys_by_kid[kid]

    async with _jwks_lock:
        if isinstance(kid, str) and kid in _signing_keys_by_kid:
            return _signing_keys_by_kid[kid]
        key = await asyncio.to_thread(_resolve_signing_key_sync, token)
        if isinstance(kid, str) and kid:
            _signing_keys_by_kid[kid] = key
        return key


async def decode_hr_token(token: str) -> dict:
    """Verify an HR access token.

    Hosted projects and older local stacks mint HS256 tokens with JWT_SECRET.
    Current local `supabase start` mints ES256 tokens; those are verified via JWKS.
    """
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    decode_kwargs = {"audience": "authenticated", "options": {"require": ["exp", "sub"]}}
    if alg == "HS256":
        return jwt.decode(token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"], **decode_kwargs)
    if alg not in _ASYMMETRIC_ALGS:
        # Never let the token pick its own verification scheme (alg=none / HS-with-public-key confusion).
        raise jwt.InvalidAlgorithmError(f"Unsupported token algorithm: {alg!r}")
    key = await _signing_key_for_token(token)
    return jwt.decode(token, key, algorithms=[alg], **decode_kwargs)


async def get_current_supabase_user(
    authorization: str | None = Header(None),
) -> SupabaseUserContext:
    """Verify a Supabase access token without requiring tenant provisioning."""
    token = _bearer(authorization)
    try:
        payload = await decode_hr_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    app_meta = payload.get("app_metadata") or {}
    corporate_raw = app_meta.get("corporate_id")
    corporate_id: UUID | None = None
    if corporate_raw:
        try:
            corporate_id = UUID(str(corporate_raw))
        except ValueError:
            corporate_id = None

    role_raw = app_meta.get("corporate_role") or app_meta.get("role")
    role = str(role_raw).strip() if role_raw else None

    try:
        return SupabaseUserContext(
            user_id=UUID(sub),
            email=payload.get("email"),
            corporate_id=corporate_id,
            role=role,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token subject")


async def get_current_hr_user(authorization: str | None = Header(None)) -> HRUserContext:
    user = await get_current_supabase_user(authorization=authorization)
    if not user.corporate_id:
        raise HTTPException(status_code=403, detail="No corporate context in token")
    return HRUserContext(
        user_id=user.user_id,
        corporate_id=user.corporate_id,
        email=user.email,
        role=user.role,
    )


def is_ops_role(role: str | None) -> bool:
    """True when the JWT corporate_role is an internal operator."""
    return (role or "").strip().lower() in {"admin", "owner"}


async def get_current_ops_user(
    authorization: str | None = Header(None),
) -> HRUserContext:
    """Require an ops (admin/owner) JWT. Tenant id is the operator's home corp."""
    user = await get_current_hr_user(authorization=authorization)
    if not is_ops_role(user.role):
        raise HTTPException(status_code=403, detail="Operations role required")
    return user


class ClientUserContext:
    """Authenticated HR client-portal user resolved from a client JWT."""

    def __init__(
        self,
        user_id: UUID,
        corporate_id: UUID,
        email: str | None = None,
        role: str = CLIENT_ROLE,
    ):
        self.user_id = user_id
        self.corporate_id = corporate_id
        self.email = email
        self.role = role


def issue_client_token(
    user_id: UUID, corporate_id: UUID, email: str | None
) -> tuple[str, int]:
    """Mint a client-portal JWT scoped to a single corporate tenant.

    Args:
        user_id: Supabase Auth user id (``hr_users.user_id``).
        corporate_id: Tenant the token is locked to.
        email: Verified email for display / audit.

    Returns:
        Tuple of (encoded JWT, lifetime in seconds).
    """
    now = datetime.now(timezone.utc)
    ttl_seconds = settings.CLIENT_TOKEN_TTL_MINUTES * 60
    payload = {
        "sub": str(user_id),
        "corporate_id": str(corporate_id),
        "email": email,
        "role": CLIENT_ROLE,
        "typ": "client",
        "aud": CLIENT_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256"), ttl_seconds


async def get_current_client_user(
    authorization: str | None = Header(None),
) -> ClientUserContext:
    """Verify a client-portal JWT and return the tenant-locked identity.

    Args:
        authorization: ``Bearer <client JWT>`` header.

    Returns:
        Client context whose ``corporate_id`` must scope every query.

    Raises:
        HTTPException: 401 for missing, expired, foreign, or malformed tokens.
    """
    token = _bearer(authorization)
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=["HS256"], audience=CLIENT_AUDIENCE
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired client session")
    if payload.get("typ") != "client" or payload.get("role") != CLIENT_ROLE:
        raise HTTPException(status_code=401, detail="Invalid token type")
    try:
        user_id = UUID(str(payload["sub"]))
        corporate_id = UUID(str(payload["corporate_id"]))
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")
    return ClientUserContext(
        user_id=user_id,
        corporate_id=corporate_id,
        email=payload.get("email"),
    )