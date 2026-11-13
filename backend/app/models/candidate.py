import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    corporate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("corporates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    access_code: Mapped[str] = mapped_column(String(36), nullable=False)
    logged_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Active uniqueness: partial unique index uq_candidates_package_email_active
    # (package_id, email) WHERE deleted_at IS NULL — see migration.
