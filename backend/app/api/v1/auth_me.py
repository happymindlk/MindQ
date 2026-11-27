"""Current Supabase user's tenant membership, resolved server-side."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import SupabaseUserContext, get_current_supabase_user
from app.database import get_db
from app.models.hr_user import HRUser

router = APIRouter()


class HrMembershipResponse(BaseModel):
    """``public.hr_users`` row for the signed-in user."""

    user_id: UUID
    corporate_id: UUID
    role: str
    full_name: str | None = None


@router.get("/me", response_model=HrMembershipResponse | None)
async def get_my_membership(
    db: AsyncSession = Depends(get_db),
    user: SupabaseUserContext = Depends(get_current_supabase_user),
):
    """Return the caller's ``hr_users`` membership, or ``null`` if unprovisioned.

    Reads the table, not JWT ``app_metadata``: claims are a cache minted by the
    access-token hook and can be stale right after provisioning or a role
    change. Only a verified Supabase access token is required, so a user whose
    token has no tenant claims yet can still discover their membership.

    Args:
        db: Async database session.
        user: Verified Supabase Auth user (subject taken from the token).

    Returns:
        The membership row, or None when the user has none.
    """
    row = (
        await db.execute(select(HRUser).where(HRUser.user_id == user.user_id))
    ).scalar_one_or_none()
    if row is None:
        return None
    return HrMembershipResponse(
        user_id=row.user_id,
        corporate_id=row.corporate_id,
        role=row.role,
        full_name=row.full_name,
    )
