import base64
import io
import wave
from collections.abc import Generator
from typing import override

import pytest
from fastapi.testclient import TestClient

from src.interpret.enums import InterpretUsageMetric, Language
from src.interpret.provider.abc import ProviderError, SpeechProviderABC
from src.interpret.provider.dependencies import get_speech_provider, get_translator
from src.interpret.provider.fake import FAKE_TRANSCRIPTS, FakeSpeech, FakeTranslator
from src.main import app
from tests.conftest import TestSessionLocal

_FREE_PLAN_ID = 1  # seeded by the billing test plugin


def _wav(seconds: float = 1.0, rate: int = 16_000, channels: int = 1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * channels * int(rate * seconds))
    return buffer.getvalue()


class _FailingSpeech(FakeSpeech):
    @override
    async def transcribe(self, wav: bytes, language: Language) -> str:
        raise ProviderError("down")


class _SilentSpeech(FakeSpeech):
    @override
    async def transcribe(self, wav: bytes, language: Language) -> str:
        return ""


class _VoicedSpeech(FakeSpeech):
    @override
    async def synthesize(self, text: str, language: Language) -> bytes | None:
        return b"mp3"


class _MuteSpeech(FakeSpeech):
    @override
    async def synthesize(self, text: str, language: Language) -> bytes | None:
        raise ProviderError("no voice")


@pytest.fixture(autouse=True)
def fake_providers() -> Generator[None]:
    """Never reach real providers, whatever INTERPRET_PROVIDER says."""
    app.dependency_overrides[get_speech_provider] = FakeSpeech
    app.dependency_overrides[get_translator] = FakeTranslator
    yield
    app.dependency_overrides.pop(get_speech_provider, None)
    app.dependency_overrides.pop(get_translator, None)


def _use_speech(speech: type[SpeechProviderABC]) -> None:
    app.dependency_overrides[get_speech_provider] = speech


def _start(client: TestClient, citizen_language: str = "ar") -> dict:
    response = client.post(
        "/v1/interpret/conversations",
        json={"citizen_language": citizen_language},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _turn(
    client: TestClient,
    conversation_id: int,
    speaker: str = "staff",
    audio: bytes | None = None,
):
    return client.post(
        f"/v1/interpret/conversations/{conversation_id}/turns",
        data={"speaker": speaker},
        files={"audio": ("turn.wav", audio or _wav(), "audio/wav")},
    )


def test_start_a_conversation(admin_authenticated: TestClient) -> None:
    rs = _start(admin_authenticated, "uk")

    assert rs["staff_language"] == "da"
    assert rs["citizen_language"] == "uk"
    assert rs["organization_id"] == 1
    assert rs["user_id"] == 1
    assert rs["turn_count"] == 0
    assert rs["ended_at"] is None


def test_a_conversation_needs_two_languages(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.post(
        "/v1/interpret/conversations",
        json={"staff_language": "da", "citizen_language": "da"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "interpret_same_language"


def test_unsupported_language_is_rejected(admin_authenticated: TestClient) -> None:
    response = admin_authenticated.post(
        "/v1/interpret/conversations",
        json={"citizen_language": "xx"},
    )
    assert response.status_code == 422


def test_staff_turn_is_translated_to_the_citizens_language(
    admin_authenticated: TestClient,
) -> None:
    conversation = _start(admin_authenticated, "ar")

    response = _turn(admin_authenticated, conversation["id"], "staff")
    assert response.status_code == 200, response.text
    rs = response.json()
    assert rs["source_language"] == "da"
    assert rs["target_language"] == "ar"
    assert rs["transcript"] == FAKE_TRANSCRIPTS[Language.DANISH]
    assert rs["translation"] == f"[ar] {FAKE_TRANSCRIPTS[Language.DANISH]}"
    assert rs["audio_base64"] is None


def test_citizen_turn_is_translated_to_danish(admin_authenticated: TestClient) -> None:
    conversation = _start(admin_authenticated, "uk")

    rs = _turn(admin_authenticated, conversation["id"], "citizen").json()
    assert rs["speaker"] == "citizen"
    assert rs["source_language"] == "uk"
    assert rs["target_language"] == "da"
    assert rs["transcript"] == FAKE_TRANSCRIPTS[Language.UKRAINIAN]


def test_turns_are_counted_without_storing_what_was_said(
    admin_authenticated: TestClient,
) -> None:
    conversation = _start(admin_authenticated)
    _turn(admin_authenticated, conversation["id"], "staff", _wav(1.5))
    _turn(admin_authenticated, conversation["id"], "citizen", _wav(2.0))

    rs = admin_authenticated.get("/v1/interpret/conversations").json()
    assert rs["total"] == 1
    item = rs["items"][0]
    assert item["turn_count"] == 2
    assert item["audio_ms"] == 3500
    assert FAKE_TRANSCRIPTS[Language.DANISH] not in str(item)


def test_the_voice_is_returned_as_base64(admin_authenticated: TestClient) -> None:
    _use_speech(_VoicedSpeech)
    conversation = _start(admin_authenticated)

    rs = _turn(admin_authenticated, conversation["id"]).json()
    assert base64.b64decode(rs["audio_base64"]) == b"mp3"
    assert rs["audio_mime_type"] == "audio/mpeg"


def test_a_failed_voice_still_returns_the_text(admin_authenticated: TestClient) -> None:
    _use_speech(_MuteSpeech)
    conversation = _start(admin_authenticated)

    response = _turn(admin_authenticated, conversation["id"])
    assert response.status_code == 200
    assert response.json()["translation"]
    assert response.json()["audio_base64"] is None


def test_a_provider_failure_is_reported_and_not_counted(
    admin_authenticated: TestClient,
) -> None:
    _use_speech(_FailingSpeech)
    conversation = _start(admin_authenticated)

    response = _turn(admin_authenticated, conversation["id"])
    assert response.status_code == 503
    assert response.json()["error_code"] == "interpret_provider_failed"
    items = admin_authenticated.get("/v1/interpret/conversations").json()["items"]
    assert items[0]["turn_count"] == 0


def test_silence_is_reported(admin_authenticated: TestClient) -> None:
    _use_speech(_SilentSpeech)
    conversation = _start(admin_authenticated)

    response = _turn(admin_authenticated, conversation["id"])
    assert response.status_code == 422
    assert response.json()["error_code"] == "interpret_nothing_heard"


def test_a_too_short_recording_is_reported(admin_authenticated: TestClient) -> None:
    conversation = _start(admin_authenticated)

    response = _turn(admin_authenticated, conversation["id"], audio=_wav(0.1))
    assert response.status_code == 422
    assert response.json()["error_code"] == "interpret_nothing_heard"


@pytest.mark.parametrize(
    "audio",
    [b"not a wav file", _wav(rate=44_100), _wav(channels=2)],
    ids=["not-wav", "wrong-rate", "stereo"],
)
def test_audio_must_be_16khz_mono_wav(
    admin_authenticated: TestClient,
    audio: bytes,
) -> None:
    conversation = _start(admin_authenticated)

    response = _turn(admin_authenticated, conversation["id"], audio=audio)
    assert response.status_code == 422
    assert response.json()["error_code"] == "interpret_invalid_audio"


def test_a_too_long_recording_is_rejected(admin_authenticated: TestClient) -> None:
    conversation = _start(admin_authenticated)

    response = _turn(admin_authenticated, conversation["id"], audio=_wav(61))
    assert response.status_code == 422
    assert response.json()["error_code"] == "interpret_audio_too_long"


def test_an_ended_conversation_takes_no_turns(admin_authenticated: TestClient) -> None:
    conversation = _start(admin_authenticated)

    ended = admin_authenticated.post(
        f"/v1/interpret/conversations/{conversation['id']}/end",
    )
    assert ended.status_code == 200
    assert ended.json()["ended_at"]

    response = _turn(admin_authenticated, conversation["id"])
    assert response.status_code == 409
    assert response.json()["error_code"] == "interpret_conversation_ended"


def test_only_the_starter_can_speak_in_a_conversation(
    admin_authenticated: TestClient,
) -> None:
    conversation = _start(admin_authenticated)

    # A client of its own: the shared fixtures would sign the same client in.
    with TestClient(app) as colleague:
        token = colleague.post(
            "/v1/auth/token",
            data={"username": "standard@example.org", "password": "password"},
        ).json()["access_token"]
        colleague.headers["Authorization"] = f"Bearer {token}"

        assert _turn(colleague, conversation["id"]).status_code == 404
        response = colleague.post(
            f"/v1/interpret/conversations/{conversation['id']}/end",
        )
        assert response.status_code == 404


def test_conversations_are_scoped_to_the_organization(
    admin_authenticated: TestClient,
    organization2_admin_authenticated: TestClient,
) -> None:
    conversation = _start(admin_authenticated)

    other = organization2_admin_authenticated
    assert _turn(other, conversation["id"]).status_code == 404
    assert other.get("/v1/interpret/conversations").json()["items"] == []


def test_members_can_interpret_but_not_see_usage(
    standard_authenticated: TestClient,
) -> None:
    conversation = _start(standard_authenticated)

    assert _turn(standard_authenticated, conversation["id"]).status_code == 200
    response = standard_authenticated.get("/v1/interpret/conversations")
    assert response.status_code == 403


def test_users_without_the_permission_cannot_interpret(
    no_roles_authenticated: TestClient,
) -> None:
    response = no_roles_authenticated.post(
        "/v1/interpret/conversations",
        json={"citizen_language": "ar"},
    )
    assert response.status_code == 403


def test_conversations_are_in_the_users_data_export(
    admin_authenticated: TestClient,
) -> None:
    conversation = _start(admin_authenticated, "en")
    _turn(admin_authenticated, conversation["id"])

    export = admin_authenticated.get("/v1/users/me/export").json()
    conversations = export["modules"]["interpret"]["conversations"]
    assert len(conversations) == 1
    assert conversations[0]["citizen_language"] == "en"
    assert conversations[0]["turn_count"] == 1


@pytest.mark.billing
async def test_turns_stop_at_the_plans_limit(admin_authenticated: TestClient) -> None:
    from src.billing.models.billing import PlanSetting

    async with TestSessionLocal() as session:
        session.add(
            PlanSetting(
                plan_id=_FREE_PLAN_ID,
                key=InterpretUsageMetric.TURNS,
                value=1,
            ),
        )
        await session.commit()
    conversation = _start(admin_authenticated)

    assert _turn(admin_authenticated, conversation["id"]).status_code == 200
    response = _turn(admin_authenticated, conversation["id"])
    assert response.status_code == 429
    items = admin_authenticated.get("/v1/interpret/conversations").json()["items"]
    assert items[0]["turn_count"] == 1
