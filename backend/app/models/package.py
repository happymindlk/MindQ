import uuid
import secrets
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _track_secret() -> str:
    return secrets.token_hex(24)


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    corporate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("corporates.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    target_role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    passing_threshold: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    access_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    track_secret: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, default=_track_secret
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    review_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # When False, package access codes only admit candidates already invited.
    allow_open_enrollment: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Candidate availability window; None on either side means unbounded.
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
