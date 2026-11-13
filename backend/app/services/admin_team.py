"""Super Admin Team management over ``public.hr_users`` (ops roles).

``hr_users.role IN ('admin', 'owner')`` remains the single source of truth so
the Supabase custom access token hook keeps injecting ``corporate_role``.
``OPS_ADMIN_EMAILS`` is an emergency read-only bootstrap list shown in the UI
as System / Env Managed (cannot be revoked via the API).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth import is_ops_role
from app.config import settings
from app.models.corporate import Corporate
from app.models.hr_user import HRUser
from app.schemas.admin_team import AdminTeamMember
from app.services.audit_log import log_admin_granted, log_admin_revoked
from app.services.hr_membership import (
    OPS_ROLES,
    find_ops_role_for_email,
    hr_display_name,
    upsert_ops_membership,
)
from app.services.supabase_admin import SupabaseAdminError, ensure_auth_user

OPS_HOME_SLUG = "happy-mind"


class AdminTeamError(Exception):
    """Mapped to an HTTP error by the admin team routes. Detail is client-safe."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class _OpsRow:
    user_id: UUID
    email: str
    full_name: str | None
    role: str
    created_at: datetime | None


def normalize_ops_email(email: str) -> str:
    """Lowercase and trim an ops email.

    Args:
        email: Raw email input.

    Returns:
        Normalized email string.
    """
    return (email or "").strip().lower()


def is_env_managed_email(email: str) -> bool:
    """True when ``email`` is listed in ``OPS_ADMIN_EMAILS``.

    Args:
        email: Candidate email (any case).

    Returns:
        Whether the address is env-bootstrap managed.
    """
    return normalize_ops_email(email) in settings.ops_admin_email_set


async def resolve_ops_home_corporate_id(
    db: AsyncSession, preferred: UUID | None = None
) -> UUID:
    """Resolve the corporate used for new Super Admin memberships.

    Prefers the caller's home corporate, then the ``happy-mind`` slug, then
    any active corporate.

    Args:
        db: Async database session.
        preferred: Caller's ``corporate_id`` when known.

    Returns:
        Corporate UUID to attach the ops membership to.

    Raises:
        AdminTeamError: No usable corporate exists.
    """
    if preferred is not None:
        row = (
            await db.execute(
                select(Corporate.id).where(
                    Corporate.id == preferred, Corporate.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return row

    by_slug = (
        await db.execute(
            select(Corporate.id).where(
                Corporate.slug == OPS_HOME_SLUG, Corporate.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if by_slug is not None:
        return by_slug

    any_active = (
        await db.execute(
            select(Corporate.id)
            .where(Corporate.is_active.is_(True))
            .order_by(Corporate.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if any_active is not None:
        return any_active

    raise AdminTeamError(503, "No active corporate is available for Super Admin membership")


async def _list_ops_rows(db: AsyncSession) -> list[_OpsRow]:
    rows = (
        await db.execute(
            text(
                "select h.user_id, lower(u.email) as email, h.full_name, h.role, h.created_at "
                "from public.hr_users h "
                "join auth.users u on u.id = h.user_id "
                "where h.role in ('admin', 'owner') "
                "order by h.created_at asc nulls last, lower(u.email) asc"
            )
        )
    ).all()
    out: list[_OpsRow] = []
    for user_id, email, full_name, role, created_at in rows:
        if not email:
            continue
        out.append(
            _OpsRow(
                user_id=user_id,
                email=str(email).strip().lower(),
                full_name=full_name,
                role=str(role),
                created_at=created_at,
            )
        )
    return out


def _member_from_row(
    row: _OpsRow, *, caller_user_id: UUID | None, caller_email: str | None
) -> AdminTeamMember:
    env_managed = is_env_managed_email(row.email)
    self_row = False
    if caller_user_id is not None and row.user_id == caller_user_id:
        self_row = True
    if caller_email and row.email == normalize_ops_email(caller_email):
        self_row = True
    return AdminTeamMember(
        user_id=row.user_id,
        email=row.email,
        name=row.full_name,
        role=row.role,
        source="env" if env_managed else "database",
        is_active=True,
        created_at=row.created_at,
        can_revoke=not env_managed and not self_row,
    )


async def list_admin_team(
    db: AsyncSession,
    *,
    caller_user_id: UUID,
    caller_email: str | None,
) -> list[AdminTeamMember]:
    """List database Super Admins plus any env-bootstrap emails not yet provisioned.

    Args:
        db: Async database session.
        caller_user_id: Authenticated ops user id (self-revoke disabled).
        caller_email: Authenticated ops email when known.

    Returns:
        Deduplicated team members with ``source`` and ``can_revoke`` flags.
    """
    rows = await _list_ops_rows(db)
    by_email = {row.email: row for row in rows}
    members = [
        _member_from_row(row, caller_user_id=caller_user_id, caller_email=caller_email)
        for row in rows
    ]

    for bootstrap in sorted(settings.ops_admin_email_set):
        if bootstrap in by_email:
            continue
        members.append(
            AdminTeamMember(
                user_id=None,
                email=bootstrap,
                name=None,
                role="admin",
                source="env",
                is_active=True,
                created_at=None,
                can_revoke=False,
            )
        )
    return members


async def ensure_ops_bootstrap_membership(
    db: AsyncSession,
    *,
    user_id: UUID,
    email: str,
    preferred_corporate_id: UUID | None = None,
) -> HRUser | None:
    """Ensure an env-bootstrap Super Admin has an ``hr_users`` ops row.

    Used by admin OTP login so ``OPS_ADMIN_EMAILS`` cannot lock operators out
    when their membership row is missing. No-ops when the email is not
    env-managed.

    Args:
        db: Async database session.
        user_id: Authenticated Auth user id from the password grant.
        email: Normalized login email.
        preferred_corporate_id: Optional corporate hint.

    Returns:
        The ops ``HRUser`` row when the email is env-managed (created or
        existing), otherwise ``None``.
    """
    normalized = normalize_ops_email(email)
    if normalized not in settings.ops_admin_email_set:
        return None

    existing = (
        await db.execute(select(HRUser).where(HRUser.user_id == user_id))
    ).scalar_one_or_none()
    if existing is not None and is_ops_role(existing.role):
        return existing

    corporate_id = preferred_corporate_id
    if corporate_id is None and existing is not None:
        corporate_id = existing.corporate_id
    corporate_id = await resolve_ops_home_corporate_id(db, corporate_id)

    await upsert_ops_membership(
        db,
        user_id=user_id,
        corporate_id=corporate_id,
        full_name=(existing.full_name if existing else None) or hr_display_name(normalized),
        role="admin",
    )
    await db.commit()
    return (
        await db.execute(select(HRUser).where(HRUser.user_id == user_id))
    ).scalar_one_or_none()


async def grant_admin(
    db: AsyncSession,
    *,
    actor_id: UUID,
    actor_corporate_id: UUID,
    email: str,
    name: str | None = None,
) -> AdminTeamMember:
    """Provision Auth (no invite email) and upsert ``hr_users`` with ``role='admin'``.

    Args:
        db: Async database session.
        actor_id: Ops user granting access.
        actor_corporate_id: Caller's home corporate (preferred attachment).
        email: Email to grant (normalized internally).
        name: Optional display name override.

    Returns:
        The granted team member representation.

    Raises:
        AdminTeamError: Duplicate ops admin, Auth failure, or missing corporate.
        SupabaseAdminError: Propagated as 502 by the route layer when raised.
    """
    normalized = normalize_ops_email(email)
    if "@" not in normalized or "." not in normalized.split("@", 1)[-1]:
        raise AdminTeamError(400, "A valid email address is required")

    if await find_ops_role_for_email(db, normalized):
        raise AdminTeamError(409, "This email already has Super Admin access")

    try:
        user_id = await run_in_threadpool(ensure_auth_user, normalized)
    except SupabaseAdminError:
        raise

    corporate_id = await resolve_ops_home_corporate_id(db, actor_corporate_id)
    display = name or hr_display_name(normalized)
    await upsert_ops_membership(
        db,
        user_id=user_id,
        corporate_id=corporate_id,
        full_name=display,
        role="admin",
    )
    await db.commit()

    membership = (
        await db.execute(select(HRUser).where(HRUser.user_id == user_id))
    ).scalar_one()
    log_admin_granted(
        actor_id=actor_id,
        target_user_id=user_id,
        target_email=normalized,
        corporate_id=corporate_id,
    )
    env_managed = is_env_managed_email(normalized)
    return AdminTeamMember(
        user_id=user_id,
        email=normalized,
        name=membership.full_name,
        role=membership.role,
        source="env" if env_managed else "database",
        is_active=True,
        created_at=membership.created_at,
        can_revoke=not env_managed and user_id != actor_id,
    )


async def revoke_admin(
    db: AsyncSession,
    *,
    actor_id: UUID,
    actor_email: str | None,
    target_user_id: UUID,
) -> None:
    """Delete an ops ``hr_users`` row so portal access ends immediately.

    Args:
        db: Async database session.
        actor_id: Ops user performing the revoke.
        actor_email: Actor email when known (blocks self-revoke by email).
        target_user_id: ``hr_users.user_id`` to remove.

    Raises:
        AdminTeamError: Self-revoke, env-managed target, missing or non-ops user.
    """
    if target_user_id == actor_id:
        raise AdminTeamError(400, "You cannot revoke your own Super Admin access")

    email_row = (
        await db.execute(
            text(
                "select lower(u.email) as email, h.role "
                "from public.hr_users h "
                "join auth.users u on u.id = h.user_id "
                "where h.user_id = :user_id"
            ),
            {"user_id": str(target_user_id)},
        )
    ).first()
    if email_row is None:
        raise AdminTeamError(404, "Super Admin not found")

    target_email = str(email_row.email or "").strip().lower()
    target_role = str(email_row.role or "")
    if target_role not in OPS_ROLES:
        raise AdminTeamError(404, "Super Admin not found")

    if actor_email and target_email == normalize_ops_email(actor_email):
        raise AdminTeamError(400, "You cannot revoke your own Super Admin access")

    if is_env_managed_email(target_email):
        raise AdminTeamError(
            400,
            "This Super Admin is System / Env Managed and cannot be revoked from the UI",
        )

    result = await db.execute(
        delete(HRUser).where(
            HRUser.user_id == target_user_id,
            HRUser.role.in_(OPS_ROLES),
        )
    )
    if result.rowcount == 0:
        raise AdminTeamError(404, "Super Admin not found")
    await db.commit()
    log_admin_revoked(
        actor_id=actor_id,
        target_user_id=target_user_id,
        target_email=target_email,
    )
