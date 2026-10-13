from typing import Annotated

from fastapi import Depends

from src.interpret.config import settings
from src.interpret.provider.abc import SpeechProviderABC, TranslatorABC
from src.interpret.provider.fake import FakeSpeech, FakeTranslator
from src.interpret.provider.live import AzureSpeech, ClaudeTranslator


def get_speech_provider() -> SpeechProviderABC:
    if settings.provider == "fake":
        return FakeSpeech()
    return AzureSpeech(
        key=settings.azure_speech_key.get_secret_value(),
        region=settings.azure_speech_region,
        timeout=settings.provider_timeout_seconds,
    )


def get_translator() -> TranslatorABC:
    if settings.provider == "fake":
        return FakeTranslator()
    return ClaudeTranslator(
        api_key=settings.anthropic_api_key.get_secret_value(),
        base_url=settings.anthropic_base_url,
        model=settings.anthropic_model,
        timeout=settings.provider_timeout_seconds,
    )


SpeechProviderDep = Annotated[SpeechProviderABC, Depends(get_speech_provider)]
TranslatorDep = Annotated[TranslatorABC, Depends(get_translator)]
