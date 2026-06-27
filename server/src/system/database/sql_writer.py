"""
SQLite WAL mode handles concurrent reads + serialized writes internally.
The Python-level serialization via RLock was redundant and caused
unnecessary contention between users. Removed.
"""

from typing import Callable, TypeVar


T = TypeVar("T")


class SQLWriter:
    """No-op coordinator. SQLite's own WAL locking is sufficient."""

    def run(self, fn: Callable[[], T]) -> T:
        return fn()


_sql_writer = SQLWriter()


def get_sql_writer() -> SQLWriter:
    return _sql_writer


def run_sql_write(fn: Callable[[], T]) -> T:
    return _sql_writer.run(fn)
