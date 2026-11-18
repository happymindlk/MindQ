import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    corporate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("corporates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    submitter_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    access_code_entered: Mapped[str | None] = mapped_column(String(36), nullable=True)
    entered_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_category: Mapped[str] = mapped_column(String(64), nullable=False, default="TECHNICAL")
    # `details` retained for erasure / older readers; `description` is the Issue 02 field.
    details: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    device_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    browser: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
