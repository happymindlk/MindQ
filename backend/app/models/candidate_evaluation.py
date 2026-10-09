import uuid
from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, String, DateTime, ForeignKey, Numeric, UniqueConstraint, Uuid, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CandidateEvaluation(Base):
    """Cached Gemini JD-fit payload. Written by FastAPI; HR is SELECT-only."""

    __tablename__ = "candidate_evaluations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    corporate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("corporates.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("packages.id", ondelete="CASCADE"), nullable=False
    )
    jd_hash: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    overall_fit: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 'ok' rows carry a JD-fit payload; 'failed' rows carry last_error and an empty payload.
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ok", server_default="ok")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_evaluation_candidate"),
        CheckConstraint("status in ('ok', 'failed')", name="candidate_evaluations_status_check"),
    )
