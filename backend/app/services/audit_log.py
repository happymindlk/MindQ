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
