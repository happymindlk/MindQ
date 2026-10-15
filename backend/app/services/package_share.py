"""Ops corporate package history and the "share package" email workflow."""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import Assessment
from app.models.candidate import Candidate
from app.models.candidate_progress import CandidateProgress
from app.models.corporate import Corporate
from app.models.package import Package
from app.schemas.client_package import (
    CorporatePackageItem,
    PackageDisplayStatus,
    SharePackageResponse,
)
from app.services.email import (
    candidate_portal_link,
    hr_portal_login_link,
    render_package_share_html,
    send_transactional_email_async,
)

logger = logging.getLogger(__name__)


class PackageShareError(Exception):
    """Share request cannot be fulfilled; ``code`` identifies the reason.

    Codes: ``not_published``, ``no_recipient``, ``delivery_failed``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def display_status(package: Package) -> PackageDisplayStatus:
    """Collapse ``status`` + ``is_active`` into the ops-facing lifecycle label.

    Args:
        package: Loaded package row.

    Returns:
        ``archived`` when deactivated, ``published`` when published, else ``draft``.
    """
    if package.is_active is False:
        return "archived"
    if (package.status or "").lower() == "published":
        return "published"
    return "draft"


async def list_corporate_packages(
    session: AsyncSession, corporate_id: UUID
) -> list[CorporatePackageItem]:
    """List a corporate's packages with invited / completed candidate counts.

    A candidate counts as completed once their COMPLETED progress rows cover every
    assessment in the package (matching the admin UI's ``candidateStatus``).

    Args:
        session: Async database session.
        corporate_id: Target corporate UUID.

    Returns:
        Packages newest first.

    Raises:
        LookupError: No corporate exists with ``corporate_id``.
    """
    exists = (
        await session.execute(select(Corporate.id).where(Corporate.id == corporate_id))
    ).scalar_one_or_none()
    if exists is None:
        raise LookupError("Corporate not found")

    assessment_totals = (
        select(Assessment.package_id, func.count(Assessment.id).label("total"))
        .group_by(Assessment.package_id)
        .subquery()
    )
    completed_per_candidate = (
        select(CandidateProgress.candidate_id, func.count(CandidateProgress.id).label("done"))
        .where(CandidateProgress.status == "COMPLETED")
        .group_by(CandidateProgress.candidate_id)
        .subquery()
    )
    total = func.coalesce(assessment_totals.c.total, 0)
    done = func.coalesce(completed_per_candidate.c.done, 0)
    candidate_stats = (
        select(
            Candidate.package_id,
            func.count(Candidate.id).label("invited"),
            func.sum(case((and_(total > 0, done >= total), 1), else_=0)).label("completed"),
        )
        .outerjoin(
            completed_per_candidate,
            completed_per_candidate.c.candidate_id == Candidate.id,
        )
        .outerjoin(assessment_totals, assessment_totals.c.package_id == Candidate.package_id)
        .where(Candidate.corporate_id == corporate_id)
        .group_by(Candidate.package_id)
        .subquery()
    )

    rows = (
        await session.execute(
            select(
                Package,
                func.coalesce(candidate_stats.c.invited, 0),
                func.coalesce(candidate_stats.c.completed, 0),
            )
            .outerjoin(candidate_stats, candidate_stats.c.package_id == Package.id)
            .where(Package.corporate_id == corporate_id)
            .order_by(Package.created_at.desc())
        )
    ).all()

    hr_link = hr_portal_login_link()
    items: list[CorporatePackageItem] = []
    for package, invited, completed in rows:
        status = display_status(package)
        published = status == "published"
        items.append(
            CorporatePackageItem(
                id=package.id,
                title=package.title,
                target_role=package.target_role,
                status=status,
                access_code=package.access_code,
                invited_count=int(invited or 0),
                completed_count=int(completed or 0),
                published_at=package.published_at,
                created_at=package.created_at,
                open_time=package.open_time,
                close_time=package.close_time,
                candidate_link=candidate_portal_link(package.access_code) if published else None,
                hr_login_link=hr_link if published else None,
            )
        )
    return items


async def share_package(
    session: AsyncSession, package_id: UUID, recipient_email: str | None
) -> SharePackageResponse:
    """Email candidate + HR access for a published package and open its enrollment.

    Open enrollment is enabled only after Resend accepts the message, so a failed
    delivery never widens access to a link nobody received.

    Args:
        session: Async database session.
        package_id: Target package UUID.
        recipient_email: Normalized override; None falls back to the corporate HR email.

    Returns:
        Delivery acknowledgement plus the links that were sent.

    Raises:
        LookupError: The package does not exist.
        PackageShareError: Not published, no recipient, or delivery failed.
    """
    row = (
        await session.execute(
            select(Package, Corporate)
            .join(Corporate, Corporate.id == Package.corporate_id)
            .where(Package.id == package_id)
        )
    ).first()
    if row is None:
        raise LookupError("Package not found")
    package, corporate = row

    if display_status(package) != "published":
        raise PackageShareError(
            "not_published", "Only published, active packages can be shared."
        )

    recipient = recipient_email or (corporate.contact_email or "").strip().lower() or None
    if not recipient:
        raise PackageShareError(
            "no_recipient",
            "No recipient email and the corporate has no HR contact email.",
        )

    html_content = render_package_share_html(
        corporate_name=corporate.name,
        package_title=package.title,
        access_code=package.access_code,
    )
    try:
        await send_transactional_email_async(
            recipient,
            f"Assessment access: {package.title}",
            html_content,
            raise_on_error=True,
        )
    except RuntimeError as exc:
        logger.warning("Package share delivery failed package=%s to=%s: %s", package_id, recipient, exc)
        raise PackageShareError("delivery_failed", str(exc)) from exc

    if not package.allow_open_enrollment:
        package.allow_open_enrollment = True
        await session.commit()
    logger.info("Package shared package=%s to=%s", package_id, recipient)

    return SharePackageResponse(
        success=True,
        sent_to=recipient,
        candidate_link=candidate_portal_link(package.access_code),
        access_code=package.access_code,
        hr_login_link=hr_portal_login_link(),
    )
