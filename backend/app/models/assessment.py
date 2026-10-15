import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, String, Text, DateTime, ForeignKey, Integer, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Assessment(Base):
    """A single test within a package (normalized from the old JSON `tests` blob)."""

    __tablename__ = "assessments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    corporate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("corporates.id", ondelete="CASCADE"), nullable=False
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("packages.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    time_limit_minutes: Mapped[int] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    questions: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    module_kind: Mapped[str] = mapped_column(String(32), default="technical", nullable=False)
    global_module_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("global_modules.id", ondelete="SET NULL"), nullable=True
    )
    timer_mode: Mapped[str] = mapped_column(String(16), default="flexible", nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scoring_profile: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
