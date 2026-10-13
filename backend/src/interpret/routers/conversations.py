from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, UploadFile, status

from src.foundation.core.exceptions import ValidationException
from src.foundation.core.security import Auth
from src.foundation.routers.query_options import (
    PageNumberQuery,
    PageSizeQuery,
    filters_query,
    sort_query,
)
from src.foundation.schemas.common import FilterItem, PageQueryParams, PaginatedResponse
from src.foundation.services.access import require_permission
from src.interpret.enums import InterpretErrorCode, InterpretPermission, Speaker
from src.interpret.schemas.conversation import ConversationIn, ConversationOut, TurnOut
from src.interpret.services.conversation import ConversationService, max_turn_bytes

router = APIRouter(prefix="/interpret/conversations")

_USE = require_permission(InterpretPermission.USE_INTERPRET)
_READ_USAGE = require_permission(InterpretPermission.READ_INTERPRET_USAGE)
_FIELDS = ["user_id", "staff_language", "citizen_language", "turn_count"]


@router.get("", status_code=status.HTTP_200_OK)
async def list_conversations(
    *,
    service: Annotated[ConversationService, Depends()],
    _: Annotated[Auth, Depends(_READ_USAGE)],
    sort: Annotated[list[str], Depends(sort_query(_FIELDS))],
    filters: Annotated[list[FilterItem], Depends(filters_query(_FIELDS))],
    page_size: PageSizeQuery = 20,
    page_number: PageNumberQuery = 1,
) -> PaginatedResponse[ConversationOut]:
    return await service.paginate(
        ConversationOut,
        PageQueryParams(
            sort=sort,
            filters=filters,
            page_size=page_size,
            page_number=page_number,
        ),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def start_a_conversation(
    service: Annotated[ConversationService, Depends()],
    _: Annotated[Auth, Depends(_USE)],
    conversation_in: ConversationIn,
) -> ConversationOut:
    return await service.start(conversation_in)


@router.post("/{conversation_id}/turns", status_code=status.HTTP_200_OK)
async def take_a_turn(
    service: Annotated[ConversationService, Depends()],
    _: Annotated[Auth, Depends(_USE)],
    conversation_id: Annotated[int, Path()],
    speaker: Annotated[Speaker, Form()],
    audio: Annotated[UploadFile, File(description="16 kHz, 16-bit mono WAV")],
) -> TurnOut:
    limit = max_turn_bytes()
    data = await audio.read(limit + 1)
    if len(data) > limit:
        raise ValidationException(error_code=InterpretErrorCode.AUDIO_TOO_LONG)
    return await service.take_turn(conversation_id, speaker, data)


@router.post("/{conversation_id}/end", status_code=status.HTTP_200_OK)
async def end_a_conversation(
    service: Annotated[ConversationService, Depends()],
    _: Annotated[Auth, Depends(_USE)],
    conversation_id: Annotated[int, Path()],
) -> ConversationOut:
    return await service.end(conversation_id)
