import base64
import io
import logging
import wave
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, status

from src.foundation.core import composition
from src.foundation.core.exceptions import (
    ClientException,
    LimitExceededException,
    NotFoundException,
    ValidationException,
)
from src.foundation.core.security import Auth
from src.foundation.services.access import authenticate
from src.foundation.services.base import ResourceService
from src.interpret.config import settings
from src.interpret.enums import (
    InterpretAuditAction,
    InterpretErrorCode,
    InterpretUsageMetric,
    Language,
    Speaker,
)
from src.interpret.models.conversation import Conversation
from src.interpret.provider.abc import ProviderError
from src.interpret.provider.dependencies import SpeechProviderDep, TranslatorDep
from src.interpret.repositories.conversation import ConversationRepository
from src.interpret.repositories.manager import InterpretRepositoryManager
from src.interpret.schemas.conversation import ConversationIn, ConversationOut, TurnOut

log = logging.getLogger(__name__)

# What the app records and Azure's short-audio recognition expects.
_SAMPLE_RATE = 16_000
_SAMPLE_WIDTH = 2
# Shorter than this is a slipped finger, not speech.
_MIN_AUDIO_MS = 300


def wav_duration_ms(audio: bytes) -> int:
    """The length of a 16 kHz, 16-bit mono PCM WAV recording."""
    try:
        with wave.open(io.BytesIO(audio)) as wav:
            if (
                wav.getnchannels() != 1
                or wav.getframerate() != _SAMPLE_RATE
                or wav.getsampwidth() != _SAMPLE_WIDTH
            ):
                raise ValidationException(error_code=InterpretErrorCode.INVALID_AUDIO)
            return wav.getnframes() * 1000 // _SAMPLE_RATE
    except (wave.Error, EOFError) as exc:
        raise ValidationException(error_code=InterpretErrorCode.INVALID_AUDIO) from exc


def max_turn_bytes() -> int:
    """Upload cap matching `max_turn_seconds`, plus room for the WAV header."""
    return settings.max_turn_seconds * _SAMPLE_RATE * _SAMPLE_WIDTH + 1024


class ConversationService(
    ResourceService[
        ConversationRepository,
        Conversation,
        ConversationIn,
        ConversationOut,
    ],
):
    current_user: Auth

    def __init__(
        self,
        repos: Annotated[InterpretRepositoryManager, Depends()],
        current_user: Annotated[Auth, Depends(authenticate)],
        speech: SpeechProviderDep,
        translator: TranslatorDep,
    ) -> None:
        self.repo = repos.conversation
        self.repo.set_organization_scope(current_user.organization_id)
        self.current_user = current_user
        self.speech = speech
        self.translator = translator
        super().__init__(repos)

    async def start(self, schema_in: ConversationIn) -> ConversationOut:
        if schema_in.staff_language == schema_in.citizen_language:
            raise ValidationException(error_code=InterpretErrorCode.SAME_LANGUAGE)
        conversation = await self.repo.create(
            organization_id=self.current_user.organization_id,
            user_id=self.current_user.id,
            staff_language=schema_in.staff_language,
            citizen_language=schema_in.citizen_language,
        )
        await self.log_audit(
            InterpretAuditAction.CONVERSATION_START,
            organization_id=self.current_user.organization_id,
            user_id=self.current_user.id,
            resource_type="interpret_conversation",
            resource_id=conversation.id,
            details={
                "staff_language": schema_in.staff_language,
                "citizen_language": schema_in.citizen_language,
            },
        )
        return ConversationOut.model_validate(conversation)

    async def _get_own(self, conversation_id: int) -> Conversation:
        """A conversation is held on one person's device: only its starter may
        speak in it or end it."""
        conversation = await self.repo.get(conversation_id)
        if conversation is None or conversation.user_id != self.current_user.id:
            raise NotFoundException(
                f"Conversation not found. [{conversation_id=}]",
            )
        return conversation

    async def end(self, conversation_id: int) -> ConversationOut:
        conversation = await self._get_own(conversation_id)
        if conversation.ended_at is None:
            conversation = await self.repo.update(
                conversation,
                ended_at=datetime.now(UTC),
            )
        return ConversationOut.model_validate(conversation)

    async def take_turn(
        self,
        conversation_id: int,
        speaker: Speaker,
        audio: bytes,
    ) -> TurnOut:
        """Transcribe, translate and voice one turn.

        Nothing said is stored: the audio, transcript and translation exist
        only in this request and its response.
        """
        conversation = await self._get_own(conversation_id)
        if conversation.ended_at is not None:
            raise ClientException(
                status.HTTP_409_CONFLICT,
                "Conversation has ended",
                error_code=InterpretErrorCode.CONVERSATION_ENDED,
            )
        duration_ms = wav_duration_ms(audio)
        if duration_ms > settings.max_turn_seconds * 1000:
            raise ValidationException(error_code=InterpretErrorCode.AUDIO_TOO_LONG)
        if duration_ms < _MIN_AUDIO_MS:
            raise ValidationException(error_code=InterpretErrorCode.NOTHING_HEARD)

        staff = Language(conversation.staff_language)
        citizen = Language(conversation.citizen_language)
        source, target = (
            (staff, citizen) if speaker == Speaker.STAFF else (citizen, staff)
        )

        try:
            transcript = await self.speech.transcribe(audio, source)
            if not transcript:
                raise ValidationException(error_code=InterpretErrorCode.NOTHING_HEARD)
            translation = await self.translator.translate(transcript, source, target)
        except ProviderError as exc:
            log.warning("Interpret provider failed: %s", exc)
            raise ClientException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Translation service unavailable",
                error_code=InterpretErrorCode.PROVIDER_FAILED,
            ) from exc

        # The text is what matters; without a voice the app shows it only.
        try:
            voice = await self.speech.synthesize(translation, target)
        except ProviderError as exc:
            log.warning("Interpret text-to-speech failed: %s", exc)
            voice = None

        # Counted after the provider calls, not before: the count takes a row
        # lock until commit, which must not be held across external calls.
        if not await composition.current().entitlements.consume(
            self.repos.db,
            self.current_user.organization_id,
            InterpretUsageMetric.TURNS,
        ):
            raise LimitExceededException
        await self.repo.record_turn(conversation.id, duration_ms)

        return TurnOut(
            speaker=speaker,
            source_language=source,
            target_language=target,
            transcript=transcript,
            translation=translation,
            audio_base64=base64.b64encode(voice).decode() if voice else None,
            audio_mime_type="audio/mpeg",
        )
