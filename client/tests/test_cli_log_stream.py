import io
import json

import src.cli.main as cli_main
from src.cli.actions import ExitCode
from src.cli.output import Redactor
from src.utils import logger as logger_module
from src.utils.logger import get_logger


def test_set_console_stream_redirects_existing_and_new_loggers():
    """已创建与新建的日志处理器都应跟随 set_console_stream 改道。"""
    existing = get_logger("test-log-redirect-existing")
    sink = io.StringIO()
    saved_default = logger_module._CONSOLE_STREAM
    logger_module.set_console_stream(sink)
    try:
        existing.error("probe-existing")
        get_logger("test-log-redirect-fresh").error("probe-fresh")
    finally:
        # 只复位模块默认值，不把处理器重新指回 pytest 的捕获流。
        logger_module._CONSOLE_STREAM = saved_default
    text = sink.getvalue()
    assert "probe-existing" in text
    assert "probe-fresh" in text


class _LoggingExecutor:
    def __init__(self, *args, **kwargs):
        self.redactor = Redactor()

    def execute(self, raw):
        get_logger("test-cli-log-probe").error("probe-log-line")
        return {
            "schema_version": "1.0",
            "session_id": "s-test",
            "action_id": "a-test",
            "action": "session.status",
            "event": "action_result",
            "status": "passed",
            "duration_ms": 0,
            "correlation_id": None,
            "data": {},
            "error": None,
        }, ExitCode.SUCCESS

    def close(self):
        pass


def test_main_keeps_stdout_jsonl_only(monkeypatch):
    """动作执行期间产生的客户端日志不得污染 stdout 的 JSONL。"""
    monkeypatch.setattr(cli_main, "ActionExecutor", _LoggingExecutor)
    out = io.StringIO()
    err = io.StringIO()
    saved_default = logger_module._CONSOLE_STREAM
    try:
        code = cli_main.main(
            ["--action", '{"action":"session.status"}'],
            stdout=out,
            stderr=err,
        )
    finally:
        logger_module._CONSOLE_STREAM = saved_default
    assert code == 0
    stdout_lines = [line for line in out.getvalue().splitlines() if line.strip()]
    assert len(stdout_lines) == 1
    record = json.loads(stdout_lines[0])
    assert record["schema_version"] == "1.0"
    assert "probe-log-line" in err.getvalue()
    assert "probe-log-line" not in out.getvalue()
