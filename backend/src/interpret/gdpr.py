"""The interpret product's share of a user's data export (GDPR)."""

from typing import Any

from src.foundation.repositories.repository_manager import RepositoryManager
from src.interpret.repositories.manager import InterpretRepositoryManager


async def export_user_data(
    *,
    repos: RepositoryManager,
    user_id: int,
    email: str,  # noqa: ARG001 - part of the exporter signature
) -> dict[str, Any]:
    """The conversations the user held. What was said is never stored."""
    conversations = await InterpretRepositoryManager(
        repos.db
    ).conversation.unscoped.list_for_user(user_id)
    return {
        "conversations": [
            {
                "organization_id": c.organization_id,
                "staff_language": c.staff_language,
                "citizen_language": c.citizen_language,
                "turn_count": c.turn_count,
                "audio_ms": c.audio_ms,
                "started_at": c.created_at.isoformat(),
                "ended_at": c.ended_at.isoformat() if c.ended_at else None,
            }
            for c in conversations
        ],
    }
