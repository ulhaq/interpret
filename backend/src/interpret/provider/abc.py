"""What the interpret service needs from speech and translation providers.

Live implementations call Azure Speech and Claude (`live.py`); `fake.py`
answers without any network calls for local development and tests.
"""

from abc import ABC, abstractmethod

from src.interpret.enums import Language


class ProviderError(Exception):
    """A provider could not be reached or returned an unusable answer."""


class SpeechProviderABC(ABC):
    @abstractmethod
    async def transcribe(self, wav: bytes, language: Language) -> str:
        """The words spoken in ``wav`` (16 kHz, 16-bit mono PCM); an empty
        string when no speech was recognised."""

    @abstractmethod
    async def synthesize(self, text: str, language: Language) -> bytes | None:
        """``text`` read aloud as MP3, or None when no voice is available."""


class TranslatorABC(ABC):
    @abstractmethod
    async def translate(self, text: str, source: Language, target: Language) -> str:
        """``text`` translated from ``source`` to ``target``."""
