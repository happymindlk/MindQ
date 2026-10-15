import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PackageModule(Base):
    """Join: a client package includes a global module at a cart position."""

    __tablename__ = "package_modules"

    package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("packages.id", ondelete="CASCADE"), primary_key=True
    )
    global_module_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("global_modules.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Eager JSONB snapshot of master questions for this cart row.
    # Null only for legacy rows; new attaches always write a copy.
    questions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("package_id", "global_module_id", name="uq_package_module"),
    )
