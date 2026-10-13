from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.foundation.core.schema import ResponseSchema
from src.foundation.schemas.common import Timestamp
from src.interpret.enums import Language, Speaker


class ConversationIn(BaseModel):
    staff_language: Language = Language.DANISH
    citizen_language: Language


class ConversationOut(Timestamp, ResponseSchema):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    user_id: int | None
    staff_language: Language
    citizen_language: Language
    turn_count: int
    audio_ms: int
    ended_at: datetime | None


class TurnOut(ResponseSchema):
    """One translated turn. Returned once and never stored."""

    speaker: Speaker
    source_language: Language
    target_language: Language
    transcript: str
    translation: str
    # The translation read aloud (MP3, base64); None when no voice is available,
    # in which case the app shows the text only.
    audio_base64: str | None
    audio_mime_type: str
