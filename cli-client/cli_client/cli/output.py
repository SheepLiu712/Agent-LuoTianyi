from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

_SENSITIVE_KEY_PARTS = ("password", "token", "authorization", "audio_base64")


class Redactor:
    def __init__(self, secrets=()):
        self.secrets: set[str] = {str(value) for value in secrets if value}

    def add_secret(self, value: object) -> None:
        if value:
            self.secrets.add(str(value))

    def redact(self, value: object, *, key: str = "") -> object:
        normalized_key = key.lower().replace("-", "_")
        if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
            return "***"
        if isinstance(value, dict):
            return {str(item_key): self.redact(item_value, key=str(item_key)) for item_key, item_value in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact(item) for item in value]
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return value.name
        if isinstance(value, str):
            redacted = value
            for secret in sorted(self.secrets, key=len, reverse=True):
                redacted = redacted.replace(secret, "***")
            return redacted
        return value


def serialize_record(record: object, redactor: Redactor) -> str:
    return json.dumps(redactor.redact(record), ensure_ascii=False, separators=(",", ":"))
