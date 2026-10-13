"""Interpret product enums.

The product's additions to the foundation enums (`src.foundation.enums`), merged
into the seeded permission/role sets by the composition root (`src.bootstrap`).
"""

from enum import StrEnum

from src.foundation.enums import ErrorCodeEnum


class InterpretPermission(StrEnum):
    USE_INTERPRET = "use:interpret"
    READ_INTERPRET_USAGE = "read:interpret_usage"


class InterpretAuditAction(StrEnum):
    CONVERSATION_START = "interpret.conversation_start"


class InterpretUsageMetric(StrEnum):
    # Plan setting key capping how many translated turns an organization may
    # use per billing period.
    TURNS = "interpret_turns"


class Language(StrEnum):
    DANISH = "da"
    ENGLISH = "en"
    ARABIC = "ar"
    UKRAINIAN = "uk"


class Speaker(StrEnum):
    STAFF = "staff"
    CITIZEN = "citizen"


class InterpretErrorCode(ErrorCodeEnum):
    SAME_LANGUAGE = (
        "interpret_same_language",
        "The staff member and the citizen must speak different languages",
    )
    CONVERSATION_ENDED = (
        "interpret_conversation_ended",
        "This conversation has ended",
    )
    INVALID_AUDIO = (
        "interpret_invalid_audio",
        "The recording must be 16 kHz, 16-bit mono WAV",
    )
    AUDIO_TOO_LONG = (
        "interpret_audio_too_long",
        "The recording is too long",
    )
    NOTHING_HEARD = (
        "interpret_nothing_heard",
        "No speech was recognised in the recording",
    )
    PROVIDER_FAILED = (
        "interpret_provider_failed",
        "The translation service is unavailable",
    )


INTERPRET_PERMISSION_DESCRIPTIONS: dict[InterpretPermission, str] = {
    InterpretPermission.USE_INTERPRET: (
        "Allows the user to hold interpreted conversations."
    ),
    InterpretPermission.READ_INTERPRET_USAGE: (
        "Allows the user to see the organization's conversation history and usage."
    ),
}

# New organizations are seeded with only the Owner role (which holds every
# permission), so there are no non-owner default roles to extend.
INTERPRET_DEFAULT_ROLE_DESCRIPTIONS: dict[str, str] = {}
INTERPRET_DEFAULT_ROLE_PERMISSIONS: dict[str, list[InterpretPermission]] = {}
