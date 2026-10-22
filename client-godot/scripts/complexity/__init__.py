from collections import Counter
from functools import lru_cache
from importlib.metadata import version


def unit(path, name, kind, line, end_line, decisions, language):
    return {
        "path": str(path), "name": name, "kind": kind, "line": line,
        "end_line": end_line, "cc": 1 + sum(decisions.values()),
        "decisions": dict(decisions), "language": language,
    }


def count_body(body, visitor):
    counts = Counter()
    for statement in body:
        visitor(statement, counts)
    return counts

@lru_cache(maxsize=None)
def require_version(distribution, expected):
    actual = version(distribution)
    if actual != expected:
        raise RuntimeError(f"{distribution} must be {expected}, found {actual}; install tests/requirements-complexity.txt")
