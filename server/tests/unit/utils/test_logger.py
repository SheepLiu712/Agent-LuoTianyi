import logging
from pathlib import Path

from src.utils import logger as logger_module


def test_project_loggers_share_one_file_handler(tmp_path: Path):
    log_file = tmp_path / "server.log"
    logger_module.setup_logging(
        {
            "file": str(log_file),
            "console_output": False,
            "file_output": True,
            "rotation": "1 MB",
        }
    )

    first = logger_module.get_logger("test.logger.one")
    second = logger_module.get_logger("test.logger.two")

    first_handlers = [
        item
        for item in first.handlers
        if isinstance(item, logger_module.WindowsSafeRotatingFileHandler)
    ]
    second_handlers = [
        item
        for item in second.handlers
        if isinstance(item, logger_module.WindowsSafeRotatingFileHandler)
    ]

    assert len(first_handlers) == 1
    assert second_handlers == first_handlers


def test_windows_safe_rotating_handler_keeps_logging_when_rollover_file_is_locked(tmp_path: Path):
    log_file = tmp_path / "locked.log"
    handler = logger_module.WindowsSafeRotatingFileHandler(
        filename=str(log_file),
        maxBytes=1,
        backupCount=1,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    def locked_rotate(source, dest):
        raise PermissionError("file is locked")

    handler.rotate = locked_rotate
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)

    handler.emit(record)
    handler.close()

    assert "hello" in log_file.read_text(encoding="utf-8")
