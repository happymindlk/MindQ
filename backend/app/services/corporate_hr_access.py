"""Keep ``hr_users`` membership aligned with a corporate's HR email whitelist.

Admin create/update of a company grants ``/client/login`` OTP access for every
listed email immediately (Auth user + ``hr_users`` row) without sending an
invite/welcome email. Removing an email revokes that corporate's portal access.
"""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.corporate import Corporate
from app.models.hr_user import HRUser
from app.services.hr_membership import OPS_ROLES, hr_display_name, upsert_hr_membership
from app.services.supabase_admin import (
    SupabaseAdminError,
    ensure_auth_user,
    find_auth_user_id_by_email,
)

logger = logging.getLogger("app.corporate_hr_access")


def normalize_hr_email_list(emails: list[str] | None) -> list[str]:
    """Lowercase, strip, and de-dupe HR emails while preserving order.

    Args:
        emails: Raw email list from the admin payload.

    Returns:
        Normalized unique emails.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in emails or []:
        normalized = str(raw or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def sync_contact_email(corporate: Corporate, emails: list[str]) -> None:
    """Keep legacy ``contact_email`` aligned with the first whitelist entry.

    Args:
        corporate: Corporate row being updated.
        emails: Normalized ``allowed_hr_emails`` list.
    """
    corporate.contact_email = emails[0] if emails else None


async def _emails_with_hr_membership(
    session: AsyncSession, corporate_id: UUID
) -> dict[str, UUID]:
    """Map login emails → Auth user ids for non-ops HR members of a company.

    Args:
        session: Async database session.
        corporate_id: Tenant to inspect.

    Returns:
        ``{email_lower: user_id}`` for current HR memberships.
    """
    rows = (
        await session.execute(
            text(
                "select lower(u.email) as email, h.user_id "
                "from public.hr_users h "
                "join auth.users u on u.id = h.user_id "
                "where h.corporate_id = :corporate_id "
                "and h.role not in ('admin', 'owner')"
            ),
            {"corporate_id": str(corporate_id)},
        )
    ).all()
    return {str(email): user_id for email, user_id in rows if email}


async def provision_hr_emails(
    session: AsyncSession,
    *,
    corporate_id: UUID,
    emails: list[str],
) -> None:
    """Ensure Auth + ``hr_users`` exist for each email (no invite email sent).

    Args:
        session: Async database session.
        corporate_id: Tenant to attach memberships to.
        emails: Normalized emails that should have portal access.

    Raises:
        SupabaseAdminError: Auth Admin cannot create/resolve a user.
    """
    for email in emails:
        user_id = await run_in_threadpool(ensure_auth_user, email)
        await upsert_hr_membership(
            session,
            user_id=user_id,
            corporate_id=corporate_id,
            full_name=hr_display_name(email),
        )
        logger.info(
            "hr_access_provisioned corporate_id=%s email=%s",
            corporate_id,
            email,
        )


async def revoke_hr_emails(
    session: AsyncSession,
    *,
    corporate_id: UUID,
    emails: list[str],
) -> None:
    """Remove non-ops ``hr_users`` rows for emails no longer on the whitelist.

    Args:
        session: Async database session.
        corporate_id: Tenant whose access is being revoked.
        emails: Normalized emails that should lose portal access.
    """
    if not emails:
        return
    current = await _emails_with_hr_membership(session, corporate_id)
    for email in emails:
        user_id = current.get(email)
        if user_id is None:
            # Membership may not exist yet; still try Auth lookup for orphans.
            try:
                user_id = await run_in_threadpool(find_auth_user_id_by_email, email)
            except SupabaseAdminError:
                logger.warning(
                    "hr_access_revoke_lookup_failed corporate_id=%s email=%s",
                    corporate_id,
                    email,
                    exc_info=True,
                )
                continue
        if user_id is None:
            continue
        await session.execute(
            delete(HRUser).where(
                HRUser.user_id == user_id,
                HRUser.corporate_id == corporate_id,
                HRUser.role.notin_(OPS_ROLES),
            )
        )
        logger.info(
            "hr_access_revoked corporate_id=%s email=%s",
            corporate_id,
            email,
        )


async def sync_corporate_hr_access(
    session: AsyncSession,
    corporate: Corporate,
    emails: list[str],
) -> None:
    """Apply whitelist, sync ``contact_email``, provision adds, revoke removals.

    Does **not** send invite or welcome emails. Caller commits.

    Args:
        session: Async database session.
        corporate: Corporate row (must already have an id for updates; for
            creates, flush first so ``corporate.id`` is available).
        emails: Desired ``allowed_hr_emails`` (will be normalized in place).

    Raises:
        SupabaseAdminError: Auth provisioning failed for an added email.
    """
    desired = normalize_hr_email_list(emails)
    previous = normalize_hr_email_list(list(corporate.allowed_hr_emails or []))
    corporate.allowed_hr_emails = desired
    sync_contact_email(corporate, desired)

    added = [email for email in desired if email not in set(previous)]
    removed = [email for email in previous if email not in set(desired)]

    if corporate.id is None:
        await session.flush()

    if added:
        await provision_hr_emails(session, corporate_id=corporate.id, emails=added)
    if removed:
        await revoke_hr_emails(session, corporate_id=corporate.id, emails=removed)
