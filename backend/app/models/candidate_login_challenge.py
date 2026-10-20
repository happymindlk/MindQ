"""One in-progress candidate sign-in. The OTP is stored as an HMAC, never the code."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateLoginChallenge(Base):
    """Candidate sign-in waiting for a one-time email code.

    Unlike admin challenges there is no withheld session: proving inbox
    ownership is the whole challenge, after which ``CandidateService.login``
    mints the candidate token. PostgREST roles have no grants on this table.
    """

    __tablename__ = "candidate_login_challenges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    access_code: Mapped[str] = mapped_column(String(36), nullable=False)
    otp_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
