"""CLI diagnostics stay on stderr so stdout remains valid JSONL."""

from __future__ import annotations

import logging
import sys
from typing import TextIO

_LOGGER_INSTANCES: dict[str, logging.Logger] = {}
_CONSOLE_STREAM: TextIO | None = None


def get_logger(name: str) -> logging.Logger:
    if name in _LOGGER_INSTANCES:
        return _LOGGER_INSTANCES[name]
    logger = logging.getLogger(f"cli_client.{name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler(_CONSOLE_STREAM or sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s - %(message)s"))
    logger.addHandler(handler)
    _LOGGER_INSTANCES[name] = logger
    return logger


def set_console_stream(stream: TextIO | None = None) -> None:
    global _CONSOLE_STREAM
    _CONSOLE_STREAM = stream
    target = stream or sys.stderr
    for logger in _LOGGER_INSTANCES.values():
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setStream(target)
