from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .actions import ActionExecutor, ExitCode
from .output import serialize_record
from .scenario import run_scenario
from ..utils.logger import set_console_stream


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AgentLuo headless JSONL client")
    parser.add_argument("--action", help="execute one JSON action")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="read JSON actions interactively from stdin",
    )
    parser.add_argument("--scenario", help="run a JSON scenario file")
    parser.add_argument("--report", help="write a redacted scenario report to PATH")
    parser.add_argument(
        "--report-include-content",
        action="store_true",
        help="include redacted content values in the scenario report",
    )
    return parser


def main(argv=None, *, stdin=None, stdout=None, stderr=None) -> int:
    args = build_parser().parse_args(argv)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    set_console_stream(stderr)
    executor = ActionExecutor()
    final_exit = ExitCode.SUCCESS
    lines = [args.action] if args.action is not None else stdin
    try:
        if args.scenario is not None:
            try:
                scenario_text = Path(args.scenario).read_text(encoding="utf-8-sig")
            except OSError:
                scenario_text = None
            return run_scenario(
                executor,
                scenario_text,
                emit=lambda record: print(serialize_record(record, executor.redactor), file=stdout, flush=True),
                report_path=args.report,
                include_content=args.report_include_content,
            )
        if args.interactive:
            print("Enter one JSON action per line; EOF exits.", file=stderr)
        for raw_line in lines:
            if args.interactive:
                print("> ", end="", file=stderr, flush=True)
            if not raw_line or not raw_line.strip():
                continue
            try:
                raw_action = json.loads(raw_line)
                record, exit_code = executor.execute(raw_action)
            except json.JSONDecodeError as exc:
                record, exit_code = executor.execute({})
                record["error"] = {
                    "code": "INVALID_INPUT",
                    "message": f"invalid JSON at column {exc.colno}",
                    "category": "input",
                }
            print(serialize_record(record, executor.redactor), file=stdout, flush=True)
            final_exit = max(final_exit, exit_code)
    finally:
        executor.close()
    return int(final_exit)
