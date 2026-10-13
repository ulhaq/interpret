from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation.models.mixins import ResourceModel


class Conversation(ResourceModel):
    """One interpreted conversation between a staff member and a citizen.

    Holds metadata only - who, when, which languages, how much was said. What
    was said (audio, transcripts, translations) is never stored.
    """

    __tablename__ = "interpret_conversation"

    organization_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organization.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    staff_language: Mapped[str] = mapped_column(String(8), nullable=False)
    citizen_language: Mapped[str] = mapped_column(String(8), nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
