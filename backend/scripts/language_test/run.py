"""Compare speech-to-text, translation and text-to-speech providers on realistic
Danish clinic and kommune sentences. See README.md in this directory.

    uv run python scripts/language_test/run.py [--synth-missing] [--only d01 a02]
"""

import argparse
import asyncio
import csv
import html
import os
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

HERE = Path(__file__).parent
SAMPLES = HERE / "samples"
AUDIO_EXTS = (".wav", ".m4a", ".mp3", ".ogg", ".webm", ".aac", ".flac", ".opus")

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "gpt-4o-transcribe")
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "alloy")


@dataclass(frozen=True)
class Lang:
    name: str
    azure_locale: str
    azure_voice: str


LANGS = {
    "da": Lang("Danish", "da-DK", "da-DK-ChristelNeural"),
    "en": Lang("English", "en-GB", "en-GB-SoniaNeural"),
    # Most Arabic speakers in Denmark speak a Levantine or Iraqi dialect; try
    # ar-SY / ar-IQ here once the Modern Standard baseline is measured.
    "ar": Lang("Arabic", "ar-SA", "ar-SA-ZariyahNeural"),
    "uk": Lang("Ukrainian", "uk-UA", "uk-UA-PolinaNeural"),
}

TRANSLATE_PROMPT = """\
You interpret between staff and citizens or patients in Danish hospitals, clinics \
and municipalities. Translate the user's message from {src} to {dst}.
Translate faithfully: keep numbers, doses, times, names and negations exact, keep \
the register polite and plain, and do not add, explain or omit anything. Danish \
terms such as CPR-nummer, e-Boks or jobcenter may be kept and briefly glossed.
Reply with the translation only."""


def targets_for(lang: str) -> list[str]:
    """Staff speak Danish to the citizen; the citizen answers into Danish."""
    return ["en", "ar", "uk"] if lang == "da" else ["da"]


@dataclass
class Sentence:
    id: str
    lang: str
    text: str


@dataclass
class Translation:
    target: str
    text: str
    seconds: float
    audio: dict[str, str] = field(default_factory=dict)  # tts provider -> file


@dataclass
class Transcript:
    provider: str
    text: str
    cer: float | None
    seconds: float
    translations: list[Translation] = field(default_factory=list)


@dataclass
class Result:
    sentence: Sentence
    input_audio: str | None
    synthetic: bool
    transcripts: list[Transcript] = field(default_factory=list)


class Providers:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.azure_key = os.environ.get("AZURE_SPEECH_KEY")
        self.azure_region = os.environ.get("AZURE_SPEECH_REGION", "swedencentral")
        self.openai_key = os.environ.get("OPENAI_API_KEY")
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    @property
    def speech(self) -> list[str]:
        return [
            name
            for name, key in (("azure", self.azure_key), ("openai", self.openai_key))
            if key
        ]

    async def transcribe(self, provider: str, wav: bytes, lang: str) -> str:
        if provider == "azure":
            res = await self.client.post(
                f"https://{self.azure_region}.stt.speech.microsoft.com/speech/"
                "recognition/conversation/cognitiveservices/v1",
                params={"language": LANGS[lang].azure_locale, "format": "simple"},
                headers={
                    "Ocp-Apim-Subscription-Key": self.azure_key or "",
                    "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                },
                content=wav,
            )
            res.raise_for_status()
            body = res.json()
            if body.get("RecognitionStatus") != "Success":
                return f"(no result: {body.get('RecognitionStatus')})"
            return body["DisplayText"]
        res = await self.client.post(
            f"{OPENAI_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.openai_key}"},
            data={"model": OPENAI_STT_MODEL, "language": lang},
            files={"file": ("audio.wav", wav, "audio/wav")},
        )
        res.raise_for_status()
        return res.json()["text"]

    async def translate(self, text: str, src: str, dst: str) -> str:
        res = await self.client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.anthropic_key or "",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 600,
                "system": TRANSLATE_PROMPT.format(
                    src=LANGS[src].name, dst=LANGS[dst].name
                ),
                "messages": [{"role": "user", "content": text}],
            },
        )
        res.raise_for_status()
        return res.json()["content"][0]["text"].strip()

    async def synthesize(self, provider: str, text: str, lang: str) -> bytes:
        if provider == "azure":
            voice = LANGS[lang]
            ssml = (
                f"<speak version='1.0' xml:lang='{voice.azure_locale}'>"
                f"<voice name='{voice.azure_voice}'>{escape(text)}</voice></speak>"
            )
            res = await self.client.post(
                f"https://{self.azure_region}.tts.speech.microsoft.com/"
                "cognitiveservices/v1",
                headers={
                    "Ocp-Apim-Subscription-Key": self.azure_key or "",
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                    "User-Agent": "interpret-language-test",
                },
                content=ssml.encode(),
            )
        else:
            res = await self.client.post(
                f"{OPENAI_BASE_URL}/audio/speech",
                headers={"Authorization": f"Bearer {self.openai_key}"},
                json={
                    "model": OPENAI_TTS_MODEL,
                    "voice": OPENAI_TTS_VOICE,
                    "input": text,
                    "response_format": "mp3",
                },
            )
        res.raise_for_status()
        return res.content


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(c for c in text if not unicodedata.category(c).startswith("P"))
    return " ".join(text.split())


def char_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h))
            )
        previous = current
    return previous[-1] / len(ref)


def to_wav(path: Path) -> bytes:
    """16 kHz mono PCM WAV, which every speech-to-text provider accepts."""
    return subprocess.run(  # noqa: S603 - fixed argv, local file
        [  # noqa: S607 - ffmpeg is looked up on PATH on purpose
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout


def error_text(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"ERROR {exc.response.status_code}: {exc.response.text[:200]}"
    return f"ERROR: {exc}"


def load_sentences(only: list[str] | None) -> list[Sentence]:
    with (HERE / "sentences.csv").open(encoding="utf-8") as f:
        sentences = [Sentence(r["id"], r["lang"], r["text"]) for r in csv.DictReader(f)]
    return [s for s in sentences if not only or s.id in only]


def find_recording(sentence_id: str) -> Path | None:
    for ext in AUDIO_EXTS:
        path = SAMPLES / f"{sentence_id}{ext}"
        if path.exists():
            return path
    return None


# Provider failures are reported in the results instead of stopping the run.
PROVIDER_ERRORS = (httpx.HTTPError, KeyError, ValueError)


async def run_sentence(
    p: Providers, s: Sentence, out: Path, *, synth_missing: bool
) -> Result:
    audio_dir = out / "audio"
    recording = find_recording(s.id)
    if recording:
        input_name = f"{s.id}-input{recording.suffix}"
        shutil.copy(recording, audio_dir / input_name)
    elif synth_missing:
        input_name = f"{s.id}-input-synthetic.mp3"
        mp3 = await p.synthesize(p.speech[0], s.text, s.lang)
        (audio_dir / input_name).write_bytes(mp3)
    else:
        return Result(s, None, synthetic=False)
    result = Result(s, input_name, synthetic=recording is None)
    wav = to_wav(audio_dir / input_name)

    for stt in p.speech:
        start = time.perf_counter()
        try:
            text = await p.transcribe(stt, wav, s.lang)
            cer = char_error_rate(s.text, text)
        except PROVIDER_ERRORS as exc:
            text, cer = error_text(exc), None
        transcript = Transcript(stt, text, cer, time.perf_counter() - start)
        result.transcripts.append(transcript)
        if cer is None:
            continue
        for target in targets_for(s.lang):
            start = time.perf_counter()
            try:
                translated = await p.translate(text, s.lang, target)
            except PROVIDER_ERRORS as exc:
                translated = error_text(exc)
            translation = Translation(target, translated, time.perf_counter() - start)
            transcript.translations.append(translation)
            if not translated.startswith("ERROR"):
                await voice(p, translation, audio_dir, f"{s.id}-{stt}-{target}")
    return result


async def voice(
    p: Providers, translation: Translation, audio_dir: Path, prefix: str
) -> None:
    for tts in p.speech:
        name = f"{prefix}-{tts}.mp3"
        try:
            mp3 = await p.synthesize(tts, translation.text, translation.target)
            (audio_dir / name).write_bytes(mp3)
            translation.audio[tts] = name
        except PROVIDER_ERRORS as exc:
            translation.audio[tts] = error_text(exc)


def write_csv(out: Path, results: list[Result]) -> None:
    with (out / "scores.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "from",
                "reference",
                "stt_provider",
                "transcript",
                "cer",
                "stt_seconds",
                "to",
                "translation",
                "translate_seconds",
                "score_transcript_1_5",
                "score_translation_1_5",
                "score_voice_1_5",
                "notes",
            ]
        )
        for r in results:
            for t in r.transcripts:
                for tr in t.translations or [Translation("", "", 0)]:
                    writer.writerow(
                        [
                            r.sentence.id,
                            r.sentence.lang,
                            r.sentence.text,
                            t.provider,
                            t.text,
                            "" if t.cer is None else f"{t.cer:.2f}",
                            f"{t.seconds:.2f}",
                            tr.target,
                            tr.text,
                            f"{tr.seconds:.2f}",
                            "",
                            "",
                            "",
                            "",
                        ]
                    )


def audio_tag(name: str) -> str:
    if name.startswith("ERROR"):
        return f"<span class=err>{html.escape(name)}</span>"
    return f"<audio controls preload=none src='audio/{html.escape(name)}'></audio>"


def write_html(out: Path, results: list[Result]) -> None:
    parts = [
        "<!doctype html><meta charset=utf-8><title>Language test</title><style>",
        "body{font:15px system-ui;margin:2rem auto;max-width:70rem;padding:0 1rem}",
        "section{border-top:1px solid #ccc;padding:1rem 0}",
        "table{border-collapse:collapse;width:100%}td,th{text-align:left;",
        "padding:.3rem .5rem;vertical-align:top;border-bottom:1px solid #eee}",
        ".muted{color:#777}.err{color:#b00}.tag{background:#fe8;padding:0 .3rem}",
        "audio{height:2rem}</style>",
        f"<h1>Language test {out.name}</h1>",
        (
            f"<p class=muted>Translation model: {html.escape(ANTHROPIC_MODEL)}. "
            "CER = character error rate against the reference text "
            "(0 is perfect).</p>"
        ),
    ]
    for r in results:
        s = r.sentence
        parts.append(
            f"<section><h2>{s.id} · {LANGS[s.lang].name}</h2>"
            f"<p dir=auto><b>{html.escape(s.text)}</b></p>"
        )
        if not r.input_audio:
            parts.append("<p class=muted>No recording; skipped.</p></section>")
            continue
        tag = " <span class=tag>synthetic voice</span>" if r.synthetic else ""
        parts.append(f"<p>Input: {audio_tag(r.input_audio)}{tag}</p>")
        for t in r.transcripts:
            cer = "" if t.cer is None else f" · CER {t.cer:.2f}"
            parts.append(
                f"<h3>{t.provider} speech-to-text"
                f" <span class=muted>{t.seconds:.1f}s{cer}</span></h3>"
                f"<p dir=auto>{html.escape(t.text)}</p>"
            )
            if not t.translations:
                continue
            parts.append("<table><tr><th>To</th><th>Translation</th><th>Voice</th>")
            for tr in t.translations:
                voices = "<br>".join(
                    f"{name}: {audio_tag(file)}" for name, file in tr.audio.items()
                )
                parts.append(
                    f"<tr><td>{LANGS[tr.target].name}"
                    f"<br><span class=muted>{tr.seconds:.1f}s</span></td>"
                    f"<td dir=auto>{html.escape(tr.text)}</td><td>{voices}</td></tr>"
                )
            parts.append("</table>")
        parts.append("</section>")
    (out / "report.html").write_text("".join(parts), encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--synth-missing",
        action="store_true",
        help="use a generated voice for sentences without a recording",
    )
    parser.add_argument("--only", nargs="+", help="sentence ids to run")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is required to convert recordings.")
    async with httpx.AsyncClient(timeout=60) as client:
        p = Providers(client)
        if not p.anthropic_key:
            sys.exit("Set ANTHROPIC_API_KEY (translation).")
        if not p.speech:
            sys.exit("Set AZURE_SPEECH_KEY and/or OPENAI_API_KEY (speech).")

        out = HERE / "out" / datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        (out / "audio").mkdir(parents=True)
        results = []
        for s in load_sentences(args.only):
            print(f"{s.id} ({s.lang}) ...", flush=True)
            results.append(
                await run_sentence(p, s, out, synth_missing=args.synth_missing)
            )
        write_csv(out, results)
        write_html(out, results)
    print(f"\nReport: {out / 'report.html'}\nScores: {out / 'scores.csv'}")


if __name__ == "__main__":
    asyncio.run(main())
