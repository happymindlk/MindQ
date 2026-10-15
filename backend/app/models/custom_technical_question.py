import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CustomTechnicalQuestion(Base):
    """Ops-authored technical item bound to a specific client package."""

    __tablename__ = "custom_technical_questions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("packages.id", ondelete="CASCADE"), nullable=False
    )
    corporate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("corporates.id", ondelete="CASCADE"), nullable=False
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), default="mcq", nullable=False)
    options: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    correct_answer_or_rubric: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evaluated_competency: Mapped[str] = mapped_column(String(255), default="Technical")
    weight: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    likert_label_1: Mapped[str | None] = mapped_column(String(128), nullable=True)
    likert_label_5: Mapped[str | None] = mapped_column(String(128), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
