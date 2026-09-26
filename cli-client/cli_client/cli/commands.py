"""Human-facing slash commands mapped to the existing client action seam."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class CommandInfo:
    usage: str
    summary: str


COMMANDS: dict[str, CommandInfo] = {
    "/help": CommandInfo("/help [命令]", "查看命令与用法"),
    "/exit": CommandInfo("/exit", "退出客户端"),
    "/register": CommandInfo("/register [用户名] [邀请码]", "使用环境变量中的密码注册"),
    "/login": CommandInfo("/login [用户名] [--remember]", "手动登录受测服务"),
    "/auto-login": CommandInfo("/auto-login", "使用 CLI 保存的令牌登录"),
    "/logout": CommandInfo("/logout", "断开当前会话"),
    "/status": CommandInfo("/status", "显示连接状态"),
    "/text": CommandInfo('/text "你好"', "发送文字消息并确认 ACK"),
    "/image": CommandInfo("/image [路径或 URI]", "发送图片或当前已选图片并确认 ACK"),
    "/select-image": CommandInfo("/select-image <路径或 URI>", "开始选择图片"),
    "/cancel-image": CommandInfo("/cancel-image", "取消选择图片"),
    "/typing": CommandInfo("/typing <文字长度>", "发送打字状态"),
    "/touch": CommandInfo("/touch [触摸区域]", "触摸洛天依，默认区域为头"),
    "/reply": CommandInfo("/reply [回复 UUID] [--timeout 秒]", "等待下一条完整回复"),
    "/read-reply": CommandInfo("/read-reply <回复 UUID>", "读取已完成的回复"),
    "/audio": CommandInfo("/audio <回复 UUID>", "重放本地回复音频"),
    "/history": CommandInfo("/history [数量]", "加载聊天记录"),
    "/initial-history": CommandInfo("/initial-history", "读取登录时自动加载的历史"),
    "/events": CommandInfo("/events [事件类型]", "读取已观察到的事件"),
    "/wait": CommandInfo("/wait <事件类型> [值]", "等待指定事件"),
    "/dynamics": CommandInfo("/dynamics [数量]", "打开最近动态"),
    "/dynamic": CommandInfo("/dynamic <动态 ID>", "阅读动态与评论"),
    "/more": CommandInfo("/more [数量]", "加载下一页动态"),
    "/post": CommandInfo('/post "动态内容"', "发布动态"),
    "/preferences": CommandInfo("/preferences", "从服务端打开偏好设置"),
    "/preference": CommandInfo("/preference", "读取当前偏好快照"),
    "/set-preference": CommandInfo("/set-preference <键=值> [键=值 ...]", "保存聊天偏好"),
    "/clear-preferences": CommandInfo("/clear-preferences", "清空聊天偏好"),
}


def command_candidates(prefix: str) -> list[tuple[str, str]]:
    """Return command names and summaries for completion menus."""
    if not prefix.startswith("/") or " " in prefix:
        return []
    return [(name, info.summary) for name, info in COMMANDS.items() if name.startswith(prefix)]


class CommandError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedCommand:
    actions: tuple[dict, ...] = ()
    help_text: str | None = None
    exit_requested: bool = False


def help_text(command: str | None = None) -> str:
    if command:
        key = command if command.startswith("/") else f"/{command}"
        info = COMMANDS.get(key)
        if info is None:
            raise CommandError(f"未知命令：{key}。输入 /help 查看可用命令。")
        return f"{info.usage}\n  {info.summary}"
    return "可用命令（输入 /help <命令> 查看用法；TAB 可补全）：\n" + "\n".join(
        f"  {info.usage}\n      {info.summary}" for info in COMMANDS.values()
    )


def _tokens(line: str) -> list[str]:
    try:
        lexer = shlex.shlex(line, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        lexer.escape = ""
        parts = list(lexer)
    except ValueError as exc:
        raise CommandError(f"引号未闭合：{exc}") from exc
    return parts


_FLAGS = {"remember", "non-empty", "replace"}
_VALUES = {
    "url",
    "password-env",
    "confirm-env",
    "invite",
    "timeout",
    "ack-timeout",
    "credential-file",
    "end-index",
    "after",
    "contains",
    "regex",
    "count10",
    "count30",
    "client-msg-id",
}
_ALLOWED_OPTIONS: dict[str, set[str]] = {
    "/register": {"url", "password-env", "confirm-env", "invite", "timeout"},
    "/login": {"url", "password-env", "remember", "timeout"},
    "/auto-login": {"credential-file", "timeout"},
    "/text": {"ack-timeout", "client-msg-id"},
    "/post": set(),
    "/image": {"ack-timeout", "client-msg-id"},
    "/select-image": {"ack-timeout"},
    "/cancel-image": {"ack-timeout"},
    "/typing": {"ack-timeout", "client-msg-id"},
    "/touch": {"ack-timeout", "client-msg-id", "count10", "count30"},
    "/reply": {"timeout", "non-empty", "contains", "regex"},
    "/read-reply": {"non-empty", "contains", "regex"},
    "/history": {"end-index"},
    "/events": {"after"},
    "/wait": {"after", "contains", "timeout"},
    "/set-preference": {"replace"},
}


def _arguments(parts: list[str]) -> tuple[list[str], dict[str, str | bool]]:
    words: list[str] = []
    options: dict[str, str | bool] = {}
    index = 0
    while index < len(parts):
        part = parts[index]
        if not part.startswith("--"):
            words.append(part)
            index += 1
            continue
        name, separator, value = part[2:].partition("=")
        if name in options:
            raise CommandError(f"重复选项：--{name}")
        if name in _FLAGS:
            if separator:
                raise CommandError(f"--{name} 不接受参数")
            options[name] = True
        elif name in _VALUES:
            if not separator:
                index += 1
                if index >= len(parts) or parts[index].startswith("--"):
                    raise CommandError(f"--{name} 缺少参数")
                value = parts[index]
            options[name] = value
        else:
            raise CommandError(f"未知选项：--{name}")
        index += 1
    return words, options


def _expect(words: list[str], count: int, usage: str) -> None:
    if len(words) != count:
        raise CommandError(f"用法：{usage}")


def _number(value: str, name: str, *, integer: bool = False, signed: bool = False) -> int | float:
    try:
        number = int(value) if integer else float(value)
    except ValueError as exc:
        raise CommandError(f"{name} 必须是数字") from exc
    if number < 0 and not signed:
        raise CommandError(f"{name} 不能为负数")
    return number


def _option_number(options: dict, key: str, params: dict, target: str, *, integer: bool = False) -> None:
    if key in options:
        params[target] = _number(str(options[key]), f"--{key}", integer=integer)


def _action(name: str, **params) -> ParsedCommand:
    return ParsedCommand(actions=({"action": name, "params": params},))


# This dispatcher keeps the full public command grammar and its argument checks together.
def parse_command(line: str, *, environ: Mapping[str, str] | None = None) -> ParsedCommand:  # noqa: C901
    environ = os.environ if environ is None else environ
    parts = _tokens(line.strip())
    if not parts:
        return ParsedCommand()
    name = parts[0].lower()
    if name == "/quit":
        name = "/exit"
    if name not in COMMANDS:
        raise CommandError(f"未知命令：{parts[0]}。输入 /help 查看可用命令。")
    words, options = _arguments(parts[1:])
    usage = COMMANDS[name].usage
    disallowed = set(options) - _ALLOWED_OPTIONS.get(name, set())
    if disallowed:
        raise CommandError(f"{name} 不支持选项 --{sorted(disallowed)[0]}")

    if name == "/help":
        if len(words) > 1:
            raise CommandError(f"用法：{usage}")
        return ParsedCommand(help_text=help_text(words[0] if words else None))
    if name == "/exit":
        _expect(words, 0, usage)
        return ParsedCommand(exit_requested=True)
    if name in ("/login", "/register"):
        if len(words) > (2 if name == "/register" else 1):
            raise CommandError(f"用法：{usage}")
        username = words[0] if words else environ.get("CLI_E2E_USER")
        base_url = options.get("url") or environ.get("CLI_E2E_BASE_URL")
        password_env = str(options.get("password-env") or "CLI_E2E_PASSWORD")
        if not username or not base_url or not environ.get(password_env):
            raise CommandError("请设置 CLI_E2E_BASE_URL、CLI_E2E_USER、CLI_E2E_PASSWORD，或提供相应参数")
        params = {"base_url": str(base_url), "username": str(username), "password_env": password_env}
        _option_number(options, "timeout", params, "timeout")
        if name == "/login":
            params["remember_login"] = bool(options.get("remember"))
            return _action("session.connect", **params)
        invite = words[1] if len(words) > 1 else options.get("invite") or environ.get("CLI_E2E_INVITE")
        if not invite:
            raise CommandError("注册需要邀请码：/register <用户名> <邀请码>，或设置 CLI_E2E_INVITE")
        params.update(invite_code=str(invite), password_confirm_env=str(options.get("confirm-env") or password_env))
        return _action("account.register", **params)
    if name == "/auto-login":
        _expect(words, 0, usage)
        params: dict = {}
        if "credential-file" in options:
            params["credential_file"] = options["credential-file"]
        _option_number(options, "timeout", params, "timeout")
        return _action("session.auto_connect", **params)
    if name in ("/logout", "/status", "/cancel-image", "/initial-history", "/preferences", "/preference"):
        _expect(words, 0, usage)
        target = {
            "/logout": "session.close",
            "/status": "session.status",
            "/cancel-image": "image.cancel",
            "/initial-history": "history.initial",
            "/preferences": "preferences.open",
            "/preference": "preferences.read",
        }[name]
        params = {}
        _option_number(options, "ack-timeout", params, "ack_timeout")
        return _action(target, **params)
    if name in ("/text", "/post"):
        if not words or not " ".join(words).strip():
            raise CommandError(f"用法：{usage}")
        params = {"text" if name == "/text" else "content": " ".join(words)}
        _option_number(options, "ack-timeout", params, "ack_timeout")
        if "client-msg-id" in options:
            params["client_msg_id"] = options["client-msg-id"]
        return _action("chat.send_text" if name == "/text" else "dynamics.post", **params)
    if name in ("/image", "/select-image"):
        if len(words) > 1 or (name == "/select-image" and not words):
            raise CommandError(f"用法：{usage}")
        params = {"path": os.path.expandvars(words[0])} if words else {}
        _option_number(options, "ack-timeout", params, "ack_timeout")
        if name == "/image" and "client-msg-id" in options:
            params["client_msg_id"] = options["client-msg-id"]
        return _action("image.send" if name == "/image" else "image.select", **params)
    if name == "/typing":
        _expect(words, 1, usage)
        params = {"text_length": _number(words[0], "文字长度", integer=True)}
        _option_number(options, "ack-timeout", params, "ack_timeout")
        if "client-msg-id" in options:
            params["client_msg_id"] = options["client-msg-id"]
        return _action("chat.send_typing", **params)
    if name == "/touch":
        area: str | list[str] = words if len(words) > 1 else (words[0] if words else "头")
        params: dict = {"touch_area": area}
        frequency = {}
        for option, field in (("count10", "count_10s"), ("count30", "count_30s")):
            if option in options:
                frequency[field] = _number(str(options[option]), option, integer=True)
        if frequency:
            params["click_frequency"] = frequency
        _option_number(options, "ack-timeout", params, "ack_timeout")
        if "client-msg-id" in options:
            params["client_msg_id"] = options["client-msg-id"]
        return _action("touch.send", **params)
    if name in ("/reply", "/read-reply", "/audio"):
        if name != "/reply":
            _expect(words, 1, usage)
        elif len(words) > 1:
            raise CommandError(f"用法：{usage}")
        params = {"reply_uuid": words[0]} if words else {}
        _option_number(options, "timeout", params, "timeout")
        if options.get("non-empty"):
            params["non_empty"] = True
        for key in ("contains", "regex"):
            if key in options:
                params[key] = options[key]
        return _action({"/reply": "reply.wait", "/read-reply": "reply.read", "/audio": "audio.replay"}[name], **params)
    if name in ("/history", "/dynamics", "/more"):
        if len(words) > 1:
            raise CommandError(f"用法：{usage}")
        params: dict = {}
        if words:
            params["count" if name == "/history" else "limit"] = _number(words[0], "数量", integer=True)
        if name == "/history" and "end-index" in options:
            params["end_index"] = _number(str(options["end-index"]), "--end-index", integer=True, signed=True)
        action = {"/history": "history.load", "/dynamics": "dynamics.open", "/more": "dynamics.load"}[name]
        return _action(action, **params)
    if name == "/dynamic":
        _expect(words, 1, usage)
        return _action("dynamics.read", dynamic_id=words[0])
    if name in ("/events", "/wait"):
        if (name == "/wait" and not words) or len(words) > (2 if name == "/wait" else 1):
            raise CommandError(f"用法：{usage}")
        params = {"kind": words[0]} if words else {}
        if name == "/wait" and len(words) == 2:
            params["value"] = words[1]
        if "after" in options:
            params["after_seq"] = _number(str(options["after"]), "--after", integer=True)
        if "contains" in options:
            params["contains"] = options["contains"]
        _option_number(options, "timeout", params, "timeout")
        return _action("events.wait" if name == "/wait" else "events.read", **params)
    if name == "/set-preference":
        if not words:
            raise CommandError(f"用法：{usage}")
        values = {}
        for word in words:
            key, separator, value = word.partition("=")
            if not separator or not key:
                raise CommandError(f"偏好需使用 键=值：{word}")
            values[key] = value
        return _action("preferences.update", values=values, replace=bool(options.get("replace")))
    if name == "/clear-preferences":
        _expect(words, 0, usage)
        return _action("preferences.update", values={}, replace=True)
    raise CommandError(f"未实现的命令：{name}")
