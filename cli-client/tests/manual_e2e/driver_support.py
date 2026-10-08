"""Translate manual driver actions to the public slash-command input."""

from __future__ import annotations


def _quote(value) -> str:
    text = str(value)
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"
    raise ValueError("manual driver value contains both quote styles")


# Keep the manual drivers' action mapping in one adapter during the input migration.
def slash_command(action: str, params: dict | None = None) -> str:  # noqa: C901
    params = dict(params or {})
    command = {
        "session.connect": "/login",
        "session.auto_connect": "/auto-login",
        "session.close": "/logout",
        "session.status": "/status",
        "chat.send_text": "/text",
        "chat.send_typing": "/typing",
        "image.select": "/select-image",
        "image.send": "/image",
        "image.cancel": "/cancel-image",
        "touch.send": "/touch",
        "reply.wait": "/reply",
        "reply.read": "/read-reply",
        "audio.replay": "/audio",
        "events.read": "/events",
        "events.wait": "/wait",
        "history.initial": "/initial-history",
        "history.load": "/history",
        "preferences.open": "/preferences",
        "preferences.read": "/preference",
        "preferences.update": "/set-preference",
        "dynamics.open": "/dynamics",
        "dynamics.read": "/dynamic",
        "dynamics.load": "/more",
        "dynamics.post": "/post",
    }.get(action)
    if command is None:
        raise ValueError(f"driver action has no slash command: {action}")
    if action == "preferences.update":
        values = params.pop("values", {})
        replace = params.pop("replace", False)
        if not values and replace:
            return "/clear-preferences"
        words = [command, *(_quote(f"{key}={value}") for key, value in values.items())]
        if replace:
            words.append("--replace")
        return " ".join(words)
    words = [command]
    positional = {
        "session.connect": ("username",),
        "chat.send_text": ("text",),
        "chat.send_typing": ("text_length",),
        "image.select": ("path",),
        "image.send": ("path",),
        "touch.send": ("touch_area",),
        "reply.wait": ("reply_uuid",),
        "reply.read": ("reply_uuid",),
        "audio.replay": ("reply_uuid",),
        "events.read": ("kind",),
        "events.wait": ("kind", "value"),
        "history.load": ("count",),
        "dynamics.open": ("limit",),
        "dynamics.load": ("limit",),
        "dynamics.read": ("dynamic_id",),
        "dynamics.post": ("content",),
    }.get(action, ())
    for key in positional:
        if key in params:
            value = params.pop(key)
            if key == "touch_area" and isinstance(value, list):
                words.extend(_quote(item) for item in value)
            else:
                words.append(_quote(value))
    renamed = {
        "base_url": "url",
        "password_env": "password-env",
        "credential_file": "credential-file",
        "ack_timeout": "ack-timeout",
        "after_seq": "after",
        "client_msg_id": "client-msg-id",
    }
    for key, value in params.items():
        if key == "non_empty" and value:
            words.append("--non-empty")
        elif key == "remember_login" and value:
            words.append("--remember")
        elif key in ("count_10s", "count_30s"):
            words.extend(["--count10" if key == "count_10s" else "--count30", str(value)])
        elif key == "click_frequency":
            for count_key, count in value.items():
                words.extend(["--count10" if count_key == "count_10s" else "--count30", str(count)])
        elif key not in ("non_empty", "remember_login"):
            words.extend([f"--{renamed.get(key, key.replace('_', '-'))}", _quote(value)])
    return " ".join(words)
