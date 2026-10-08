"""High-level transactional email helpers (invite, nudge, HR completion)."""
from __future__ import annotations

import logging

from app.services.email import (
    render_candidate_invite_html,
    render_candidate_nudge_html,
    render_hr_completion_html,
    send_transactional_email_async,
)

logger = logging.getLogger("app.email_service")


class EmailService:
    @staticmethod
    async def send_nudge_email(
        email: str,
        name: str,
        access_code: str,
        package_title: str,
    ) -> bool:
        """Send a transactional reminder to complete an assessment.

        Args:
            email: Candidate email.
            name: Candidate display name.
            access_code: Package access code.
            package_title: Assessment package title.

        Returns:
            True when Resend accepted the message; False when unconfigured or failed.
        """
        subject = f"Friendly Reminder: Complete your {package_title} assessment"
        html_body = render_candidate_nudge_html(
            candidate_name=name,
            package_title=package_title,
            access_code=access_code,
        )
        result = await send_transactional_email_async(email, subject, html_body)
        return result is not None

    @staticmethod
    async def send_candidate_invite_email(
        email: str,
        name: str,
        access_code: str,
        package_title: str,
        corporate_name: str | None = None,
        *,
        raise_on_error: bool = False,
    ) -> bool:
        """Send assessment invite with portal magic link and guidelines.

        Args:
            email: Candidate email.
            name: Candidate display name.
            access_code: Unique candidate (or package) access code.
            package_title: Assessment package title.
            corporate_name: Hiring company shown in the email body.
            raise_on_error: When True, propagate Resend failures.

        Returns:
            True when Resend accepted the message; False when unconfigured or failed.
        """
        company = (corporate_name or "").strip() or "Assess Pulse"
        subject = f"{company} invited you: {package_title}"
        html_body = render_candidate_invite_html(
            candidate_name=name,
            package_title=package_title,
            access_code=access_code,
            corporate_name=company,
        )
        result = await send_transactional_email_async(
            email, subject, html_body, raise_on_error=raise_on_error
        )
        return result is not None

    @staticmethod
    async def send_hr_completion_email(
        hr_email: str,
        *,
        candidate_name: str,
        candidate_email: str,
        package_title: str,
        hr_name: str | None = None,
    ) -> bool:
        """Notify HR that a candidate finished and the report is ready.

        Args:
            hr_email: Corporate contact email.
            candidate_name: Completed candidate name.
            candidate_email: Completed candidate email.
            package_title: Package title.
            hr_name: Optional greeting name.

        Returns:
            True when Resend accepted the message; False when unconfigured or failed.
        """
        subject = f"Report ready: {candidate_name} completed {package_title}"
        html_body = render_hr_completion_html(
            hr_name=hr_name,
            candidate_name=candidate_name,
            package_title=package_title,
            candidate_email=candidate_email,
        )
        result = await send_transactional_email_async(hr_email, subject, html_body)
        return result is not None
