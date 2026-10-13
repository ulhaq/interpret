# Language test

Before building the product, this checks how well speech-to-text, translation and
text-to-speech handle Danish, English, Arabic and Ukrainian in clinic and kommune
conversations.

For each sentence in `sentences.csv`, the script:

1. transcribes the recording with each speech provider and scores the result
   against the reference text (character error rate),
2. translates the transcript with Claude: Danish into English, Arabic and
   Ukrainian, and the other languages into Danish,
3. reads the translation aloud with each speech provider.

It writes `out/<timestamp>/report.html` (text, timings and audio players) and
`scores.csv`, a sheet a native speaker fills in with 1-5 scores.

**Use only made-up sentences, never real patient conversations.**

## Accounts

| Provider  | Used for                                  | Sign up                                                                                       | Env vars                                   |
| --------- | ----------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Anthropic | translation (required)                    | console.anthropic.com, add about $5 in credit                                                 | `ANTHROPIC_API_KEY`                        |
| Azure     | speech-to-text and text-to-speech         | portal.azure.com, create a *Speech service* resource in Sweden Central, pricing tier F0 (free) | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`  |
| OpenAI    | speech-to-text and text-to-speech         | platform.openai.com, add about $5 in credit                                                   | `OPENAI_API_KEY`                           |

You need Anthropic plus at least one speech provider. Use both speech providers to
compare them. A full run costs well under $1.

## Recordings

Record each sentence on a phone, in a normal speaking voice and with some background
noise. Save each file as `samples/<id>.<ext>`, for example `samples/a01.m4a` (wav,
m4a, mp3, ogg, webm and opus all work). Arabic and Ukrainian should be recorded by
native speakers. Recordings are gitignored.

Without recordings, `--synth-missing` uses a generated voice instead. That is
enough to check translation and voices, but it makes speech-to-text look better
than it is.

## Run

```bash
cd backend
export ANTHROPIC_API_KEY=... AZURE_SPEECH_KEY=... AZURE_SPEECH_REGION=swedencentral
export OPENAI_API_KEY=...
uv run python scripts/language_test/run.py --synth-missing   # or --only d01 a01
```

Then open the report and send `scores.csv` with the `out/<timestamp>/` folder to
the native speakers for scoring.
