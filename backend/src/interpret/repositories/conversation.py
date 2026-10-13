from collections.abc import Sequence
from typing import ClassVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.foundation.repositories.base import OrganizationScopedRepository
from src.interpret.models.conversation import Conversation


class ConversationRepository(OrganizationScopedRepository[Conversation]):
    search_fields: ClassVar[list[str]] = []

    def __init__(self, db: AsyncSession) -> None:
        super().__init__(Conversation, db)

    async def record_turn(self, conversation_id: int, audio_ms: int) -> None:
        """Count one turn in one statement, so a double-tapped button can't
        lose a count."""
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                turn_count=Conversation.turn_count + 1,
                audio_ms=Conversation.audio_ms + audio_ms,
            ),
        )

    async def list_for_user(self, user_id: int) -> Sequence[Conversation]:
        """The user's conversations in every organization (GDPR export)."""
        stmt = select(Conversation).where(Conversation.user_id == user_id)
        stmt = self._include_deleted(stmt)
        rs = await self.db.execute(stmt.order_by(Conversation.id))
        return rs.scalars().all()
