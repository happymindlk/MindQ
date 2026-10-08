"""Tenant membership (``public.hr_users``) provisioning shared by ops invites and seeds."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_user import HRUser

OPS_ROLES: tuple[str, ...] = ("admin", "owner")


def hr_display_name(email: str) -> str:
    """Derive a display name from an email local-part, or fall back.

    Args:
        email: Normalized work email.

    Returns:
        Human-readable name for ``hr_users.full_name``.
    """
    local = (email or "").split("@", 1)[0].strip()
    if not local:
        return "HR Admin"
    cleaned = local.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned else "HR Admin"


async def find_ops_role_for_email(db: AsyncSession, email: str) -> str | None:
    """Return the ops role (admin/owner) already held by ``email``, if any.

    Args:
        db: Async database session.
        email: Email to look up in ``auth.users``.

    Returns:
        ``"admin"`` / ``"owner"`` when the account is an internal operator,
        otherwise ``None`` (no account, no membership, or a plain ``hr`` role).
    """
    role = (
        await db.execute(
            text(
                "select h.role from public.hr_users h "
                "join auth.users u on u.id = h.user_id "
                "where lower(u.email) = lower(:email)"
            ),
            {"email": email},
        )
    ).scalar_one_or_none()
    return role if role in OPS_ROLES else None


async def upsert_hr_membership(
    db: AsyncSession,
    *,
    user_id: UUID,
    corporate_id: UUID,
    full_name: str,
) -> None:
    """Map an Auth user to a corporate with role ``hr``. Caller commits.

    The conflict update is filtered on ``role NOT IN OPS_ROLES`` so this can
    never demote an internal operator, even if a caller skips the pre-check.

    Args:
        db: Async database session.
        user_id: ``auth.users.id`` of the HR user.
        corporate_id: Tenant to attach the user to.
        full_name: Display name stored on the membership row.
    """
    stmt = (
        pg_insert(HRUser)
        .values(
            user_id=user_id,
            corporate_id=corporate_id,
            full_name=full_name,
            role="hr",
        )
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "corporate_id": corporate_id,
                "full_name": full_name,
                "role": "hr",
            },
            where=HRUser.role.notin_(OPS_ROLES),
        )
    )
    await db.execute(stmt)
