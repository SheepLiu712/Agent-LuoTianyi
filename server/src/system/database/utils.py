from typing import Any


DEFAULT_MESSAGE_TOKEN_TTL_SECONDS = 3600
MIN_MESSAGE_TOKEN_TTL_SECONDS = 60
MAX_MESSAGE_TOKEN_TTL_SECONDS = 86400


def normalize_message_token_ttl_seconds(value: Any) -> int:
    """Return a safe TTL when DatabaseManager is used without config validation."""
    if type(value) is not int:
        return DEFAULT_MESSAGE_TOKEN_TTL_SECONDS
    return min(
        MAX_MESSAGE_TOKEN_TTL_SECONDS,
        max(MIN_MESSAGE_TOKEN_TTL_SECONDS, value),
    )
