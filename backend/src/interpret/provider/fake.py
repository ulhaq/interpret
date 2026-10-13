"""Providers that answer without network calls: local development and tests.

Speech-to-text returns a fixed sentence in the spoken language, translation
marks the text with its target language, and there is no voice - so the whole
flow can be clicked through without provider accounts.
"""

from typing import override

from src.interpret.enums import Language
from src.interpret.provider.abc import SpeechProviderABC, TranslatorABC

FAKE_TRANSCRIPTS: dict[Language, str] = {
    Language.DANISH: "Hvornår tog du sidst din medicin?",
    Language.ENGLISH: "I took two tablets this morning.",
    Language.ARABIC: "أخذت حبتين هذا الصباح.",
    Language.UKRAINIAN: "Я прийняв дві таблетки сьогодні вранці.",
}


class FakeSpeech(SpeechProviderABC):
    @override
    async def transcribe(self, wav: bytes, language: Language) -> str:
        return FAKE_TRANSCRIPTS[language]

    @override
    async def synthesize(self, text: str, language: Language) -> bytes | None:
        return None


class FakeTranslator(TranslatorABC):
    @override
    async def translate(self, text: str, source: Language, target: Language) -> str:
        return f"[{target}] {text}"
