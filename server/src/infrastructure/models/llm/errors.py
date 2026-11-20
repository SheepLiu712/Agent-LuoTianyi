"""Provider error diagnostics without prompts, credentials or response content."""

import json
import re


def provider_error_details(error):
    if getattr(error, "__cause__", None) is not None:
        error = error.__cause__
    response = getattr(error, "response", None)
    payload = getattr(error, "body", None)
    if payload is None and response is not None:
        try:
            payload = response.json()
        except (ValueError, RuntimeError):
            pass
    if not isinstance(payload, dict):
        payload = {}
    detail = payload.get("error", payload)
    if not isinstance(detail, dict):
        detail = {}
    headers = getattr(response, "headers", {})
    fields = {
        "status": getattr(response, "status_code", getattr(error, "status_code", None)),
        "code": detail.get("code", getattr(error, "code", None)),
        "type": detail.get("type"),
        "param": detail.get("param"),
        "request_id": payload.get("request_id") or headers.get("x-request-id") or headers.get("x-dashscope-request-id"),
    }
    # These identifiers explain rejection categories and allow provider-side lookup.
    # Arbitrary error messages can echo the input; never log the raw body/message.
    return json.dumps(
        {
            key: str(value)[:160]
            for key, value in fields.items()
            if value is not None and re.fullmatch(r"[\w.:/-]{1,160}", str(value))
        },
        ensure_ascii=False,
    )


class ProviderStreamError(RuntimeError):
    def __init__(self, payload):
        self.body = payload
        super().__init__("Provider stream error " + provider_error_details(self))
