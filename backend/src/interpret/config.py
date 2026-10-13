"""Interpret product settings.

Read from the environment with an `INTERPRET_` prefix (e.g. `provider` <-
`INTERPRET_PROVIDER`).
"""

from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import SettingsConfigDict

from src.foundation.core.config import EnvSettings
from src.foundation.core.config import settings as app_settings


class InterpretSettings(EnvSettings):
    model_config = SettingsConfigDict(env_prefix="interpret_")

    # `fake` answers with canned text and no audio, for local development and
    # tests; `live` uses Azure Speech and Claude.
    provider: Literal["fake", "live"] = "fake"

    # Azure Speech (speech-to-text and text-to-speech). Use an EU region:
    # audio is personal data, often health data.
    azure_speech_key: SecretStr = SecretStr("")
    azure_speech_region: str = "swedencentral"

    # Claude (translation).
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-haiku-5-5"

    # Bounds each call to a speech or translation provider.
    provider_timeout_seconds: float = 20.0

    # One recorded turn; Azure's short-audio recognition takes up to 60 s.
    max_turn_seconds: int = 60

    @model_validator(mode="after")
    def validate_live_provider(self) -> Self:
        if app_settings.app_env == "production" and self.provider != "live":
            raise ValueError("INTERPRET_PROVIDER must be 'live' in production")
        if self.provider == "live" and not (
            self.azure_speech_key.get_secret_value()
            and self.anthropic_api_key.get_secret_value()
        ):
            raise ValueError(
                "INTERPRET_AZURE_SPEECH_KEY and INTERPRET_ANTHROPIC_API_KEY must be "
                "set when INTERPRET_PROVIDER is 'live'",
            )
        return self


settings = InterpretSettings()
