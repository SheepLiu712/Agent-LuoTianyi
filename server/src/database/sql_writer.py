import threading
from contextlib import contextmanager
from typing import Callable, TypeVar


T = TypeVar("T")


class SQLWriter:
    """Single-writer coordinator for SQL writes inside process."""

    def __init__(self):
        self._lock = threading.RLock()

    @contextmanager
    def guard(self):
        with self._lock:
            yield

    def run(self, fn: Callable[[], T]) -> T:
        with self._lock:
            return fn()


_sql_writer = SQLWriter()


def get_sql_writer() -> SQLWriter:
    return _sql_writer


def run_sql_write(fn: Callable[[], T]) -> T:
    return _sql_writer.run(fn)
