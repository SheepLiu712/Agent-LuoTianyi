"""召回内部耗时：只记录阶段、次数与耗时，不记录查询或记忆内容。"""

import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from src.infrastructure.observability.call_reply_timing import record_retrieval_details
from src.utils.logger import get_logger

_current = ContextVar("retrieval_timing", default=None)
logger = get_logger(__name__)


def record_retrieval_phase(name, started, status="success"):
    details = _current.get()
    if details is None:
        return
    row = details.setdefault(name, {"duration_ms": 0.0, "count": 0, "status": "success"})
    row["duration_ms"] += (time.perf_counter() - started) * 1000
    row["count"] += 1
    if status != "success":
        row["status"] = status


@contextmanager
def retrieval_phase(name):
    started = time.perf_counter()
    status = "success"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        record_retrieval_phase(name, started, status)


def measure_retrieval(function):
    @wraps(function)
    async def measured(*args, **kwargs):
        details = {}
        token = _current.set(details)
        started = time.perf_counter()
        status = "success"
        try:
            return await function(*args, **kwargs)
        except BaseException:
            status = "error"
            logger.exception("记忆检索失败，阶段统计=%s", details)
            raise
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            record_retrieval_details(details)
            logger.info("记忆检索耗时 status=%s total_ms=%.3f phases=%s", status, elapsed, details)
            _current.reset(token)

    return measured
