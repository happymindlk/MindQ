"""Send markers for queued transactional emails (P2-01 idempotency)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SentEmail(Base):
    """One row per queued email the worker has claimed for delivery.

    The primary key is the ARQ job idempotency key, inserted before SES is
    called so an interrupted-and-re-run job never sends twice.
    """

    __tablename__ = "sent_emails"

    idempotency_key: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
