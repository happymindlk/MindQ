"""Structured audit events for candidate data access and erasure.

Events intentionally omit names, emails, answers, and model prose so log
drains never become a second copy of candidate PII.
"""
from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger("app.audit")


def log_candidate_erased(
    *,
    admin_user_id: UUID,
    corporate_id: UUID,
    candidate_id: UUID,
) -> None:
    """Emit ``candidate_erased`` after a successful hard delete.

    Args:
        admin_user_id: Authenticated admin/HR user who approved the erasure.
        corporate_id: Tenant that owned the candidate.
        candidate_id: Erased ``candidates.id`` (no longer present in the DB).
    """
    logger.info(
        "candidate_erased",
        extra={
            "event": "candidate_erased",
            "admin_user_id": str(admin_user_id),
            "corporate_id": str(corporate_id),
            "candidate_id": str(candidate_id),
        },
    )


def log_admin_granted(
    *,
    actor_id: UUID,
    target_user_id: UUID,
    target_email: str,
    corporate_id: UUID,
) -> None:
    """Emit ``admin_granted`` after a Super Admin is added via Team management.

    Args:
        actor_id: Authenticated ops user who granted access.
        target_user_id: Auth user id that received ``role='admin'``.
        target_email: Normalized email of the new Super Admin.
        corporate_id: Ops corporate the membership was attached to.
    """
    logger.info(
        "admin_granted",
        extra={
            "event": "admin_granted",
            "actor_id": str(actor_id),
            "target_user_id": str(target_user_id),
            "target_email": (target_email or "").strip().lower(),
            "corporate_id": str(corporate_id),
        },
    )


def log_admin_revoked(
    *,
    actor_id: UUID,
    target_user_id: UUID,
    target_email: str | None,
) -> None:
    """Emit ``admin_revoked`` after a Super Admin membership is removed.

    Args:
        actor_id: Authenticated ops user who revoked access.
        target_user_id: Auth user id whose ``hr_users`` row was deleted.
        target_email: Normalized email when known.
    """
    logger.info(
        "admin_revoked",
        extra={
            "event": "admin_revoked",
            "actor_id": str(actor_id),
            "target_user_id": str(target_user_id),
            "target_email": (target_email or "").strip().lower() or None,
        },
    )


def log_report_accessed(
    *,
    actor_id: UUID,
    actor_role: str | None,
    corporate_id: UUID,
    candidate_id: UUID,
    format: str,
) -> None:
    """Emit ``report_accessed`` when a MindQ Report is viewed or downloaded.

    Args:
        actor_id: Authenticated user id (HR, ops, or client portal).
        actor_role: JWT role string when known.
        corporate_id: Tenant scope of the candidate.
        candidate_id: Candidate whose report was accessed.
        format: Delivery format (``json`` or ``pdf``).
    """
    logger.info(
        "report_accessed",
        extra={
            "event": "report_accessed",
            "actor_id": str(actor_id),
            "actor_role": (actor_role or "").strip(),
            "corporate_id": str(corporate_id),
            "candidate_id": str(candidate_id),
            "format": format,
        },
    )
