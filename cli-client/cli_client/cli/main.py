"""Slash-command shell for the standalone CLI client."""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..utils.logger import set_console_stream
from .actions import ActionExecutor, ExitCode
from .commands import COMMANDS, CommandError, command_candidates, parse_command
from .output import serialize_record
from .scenario import run_scenario


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentLuo slash-command client")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--command", help='execute one command, e.g. /text "你好"')
    source.add_argument("--script", help="run slash commands from a UTF-8 file in one session")
    source.add_argument("--interactive", action="store_true", help="start the interactive shell")
    parser.add_argument("--jsonl", action="store_true", help="emit machine-readable JSONL results")
    parser.add_argument("--continue-on-failure", action="store_true", help="keep running a script after failed actions")
    parser.add_argument("--report", help="write a redacted script report to PATH")
    parser.add_argument("--report-include-content", action="store_true", help="include redacted content in report")
    return parser


def _human_record(record: dict, redactor) -> str:
    safe = redactor.redact(record)
    action = str(safe.get("action", "command"))
    status = safe.get("status", "unknown")
    if status not in ("passed", "suppressed"):
        error = safe.get("error") or {}
        return f"✗ {action}: {error.get('message') or status} [{error.get('code') or status}]"
    data = safe.get("data") or {}
    if action in ("session.connect", "session.auto_connect", "session.status", "session.close"):
        return f"✓ 会话状态：{data.get('state', '未知')}"
    if action in ("chat.send_text", "image.send", "touch.send", "chat.send_typing", "dynamics.post"):
        label = {
            "chat.send_text": "文字",
            "image.send": "图片",
            "touch.send": "触摸",
            "chat.send_typing": "打字状态",
            "dynamics.post": "动态",
        }[action]
        return f"✓ {label}：{'已收到 ACK' if data.get('ack') else '已完成'}"
    if action in ("reply.wait", "reply.read"):
        lines = [f"✓ 回复 {safe.get('correlation_id') or ''}".strip()]
        lines.append(f"  文字：{data.get('text') or '（无）'}")
        lines.append(f"  表情：{', '.join(data.get('expressions') or []) or '（无）'}")
        audio = data.get("audio") or {}
        lines.append(f"  音频：{audio.get('reference') or '（无可重放文件）'}")
        return "\n".join(lines)
    if action in ("history.load", "history.initial", "dynamics.open", "dynamics.load"):
        items = data.get("items", [])
        lines = [f"✓ {action}: {len(items)} 条"]
        lines.extend(f"  {item}" for item in items)
        return "\n".join(lines)
    if action in ("preferences.open", "preferences.read", "preferences.update"):
        preferences = data.get("preferences") or {}
        return "\n".join(["✓ 聊天偏好", *(f"  {key}: {value}" for key, value in preferences.items())])
    if action in ("events.wait", "events.read"):
        events = data.get("events", [data.get("event")])
        return "\n".join([f"✓ 事件：{len(events)} 条", *(f"  {item}" for item in events if item)])
    return f"✓ {action}: {data}" if data else f"✓ {action}"


def _shell_record(executor, action: str, status: str, data: dict, error: dict | None) -> dict:
    return {
        "schema_version": "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session_id": executor.session_id,
        "action_id": f"a-{uuid.uuid4().hex[:12]}",
        "action": action,
        "event": "action_result",
        "status": status,
        "duration_ms": 0,
        "correlation_id": None,
        "data": data,
        "error": error,
    }


def _error_record(executor, message: str) -> dict:
    return _shell_record(
        executor,
        "command.parse",
        "failed",
        {},
        {"code": "INVALID_COMMAND", "message": message, "category": "input"},
    )


# Prompt setup owns input, candidate display and the TAB binding in one place.
def _repl_lines(stdin, stderr):  # noqa: C901
    if stdin is not sys.stdin or not stdin.isatty():
        yield from stdin
        return
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.key_binding import KeyBindings
    except ImportError:
        print("提示：安装 requirements.txt 可使用 TAB 补全。输入 /help 查看命令。", file=stderr)
        yield from stdin
        return

    class SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            prefix = document.text_before_cursor
            if not prefix.startswith("/") or " " in prefix:
                return
            for command, summary in command_candidates(prefix):
                yield Completion(command, start_position=-len(prefix), display_meta=summary)

    def toolbar():
        current = session.app.current_buffer.text.strip().split(" ", 1)[0]
        info = COMMANDS.get(current)
        return f"{info.usage} · {info.summary}" if info else "输入 /help 查看命令，TAB 显示候选并补全"

    bindings = KeyBindings()

    @bindings.add("tab")
    def complete_command(event):
        buffer = event.current_buffer
        prefix = buffer.document.text_before_cursor
        candidates = command_candidates(prefix)
        if len(candidates) == 1:
            buffer.insert_text(candidates[0][0][len(prefix) :] + " ")
        elif candidates:
            buffer.start_completion(select_first=False)

    session = PromptSession(
        completer=SlashCompleter(),
        key_bindings=bindings,
        complete_while_typing=True,
        bottom_toolbar=toolbar,
    )
    while True:
        try:
            yield session.prompt("cli> ")
        except (EOFError, KeyboardInterrupt):
            break


# The entry point selects one of the three input sources, then shares the same executor.
def main(argv=None, *, stdin=None, stdout=None, stderr=None) -> int:  # noqa: C901
    args = build_parser().parse_args(argv)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    set_console_stream(stderr)
    executor = ActionExecutor()

    def emit(record: dict) -> None:
        value = serialize_record(record, executor.redactor) if args.jsonl else _human_record(record, executor.redactor)
        print(value, file=stdout, flush=True)

    try:
        if args.script is not None:
            try:
                lines = Path(args.script).read_text(encoding="utf-8-sig").splitlines()
                actions = []
                for line_number, line in enumerate(lines, 1):
                    if not line.strip() or line.lstrip().startswith("#"):
                        continue
                    parsed = parse_command(line)
                    if parsed.help_text or parsed.exit_requested:
                        raise CommandError(f"第 {line_number} 行：脚本只接受执行命令")
                    actions.extend(parsed.actions)
            except (OSError, UnicodeError, CommandError) as exc:
                emit(_error_record(executor, str(exc)))
                return int(ExitCode.INPUT_ERROR)
            return run_scenario(
                executor,
                {"actions": actions, "on_failure": "continue" if args.continue_on_failure else "stop_side_effects"},
                emit,
                report_path=args.report,
                include_content=args.report_include_content,
            )

        if args.command is not None:
            lines = [args.command]
        else:
            if stdin is sys.stdin and stdin.isatty():
                print("AgentLuo CLI · 输入 /help 查看命令，/exit 退出", file=stderr)
            lines = _repl_lines(stdin, stderr)

        final_exit = ExitCode.SUCCESS
        for raw_line in lines:
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            try:
                parsed = parse_command(raw_line)
            except CommandError as exc:
                emit(_error_record(executor, str(exc)))
                final_exit = max(final_exit, ExitCode.INPUT_ERROR)
                continue
            if parsed.help_text is not None:
                if args.jsonl:
                    emit(_shell_record(executor, "help", "passed", {"text": parsed.help_text}, None))
                else:
                    print(parsed.help_text, file=stdout, flush=True)
                continue
            if parsed.exit_requested:
                break
            for action in parsed.actions:
                record, exit_code = executor.execute(action)
                emit(record)
                final_exit = max(final_exit, exit_code)
        return int(final_exit)
    finally:
        executor.close()
