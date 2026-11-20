"""可由脚本关联的通话时序事件；仅保存身份、时钟和数值，不记录对话内容。"""

import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

from src.utils.logger import get_logger

logger = get_logger(__name__)
_PROCESS_RUN = uuid4().hex
_packet_diagnostics: set[str] = set()


def call_latency(event, call_id, **fields):
    _log_event(logging.INFO, event, call_id, fields)


def set_call_packet_diagnostics(call_id: str, enabled: bool) -> None:
    if enabled:
        _packet_diagnostics.add(call_id)
    else:
        _packet_diagnostics.discard(call_id)


class CallPacketLogger:
    """保留每个回复的首个阶段事件，按通话开关输出后续包。"""

    def __init__(self, call_id):
        self._call_id = str(call_id)
        self._seen: set[tuple[str, str]] = set()

    def record(self, event: str, response_id: str, **fields) -> None:
        key = (event, response_id)
        if key not in self._seen:
            self._seen.add(key)
            level = logging.INFO
        elif self._call_id in _packet_diagnostics:
            level = logging.DEBUG
        else:
            return
        _log_event(level, event, self._call_id, {"response_id": response_id, **fields})


def _log_event(level, event, call_id, fields):
    if not logger.isEnabledFor(level):
        return
    logger.log(
        level,
        "CALL_LATENCY %s",
        json.dumps(
            {
                "schema": 1,
                "process_run": _PROCESS_RUN,
                "event": event,
                "call_id": str(call_id),
                "monotonic_ns": time.monotonic_ns(),
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                **fields,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
