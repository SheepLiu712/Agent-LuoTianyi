"""可由脚本关联的通话时序事件；仅保存身份、时钟和数值，不记录对话内容。"""

import json
import time
from datetime import datetime, timezone
from uuid import uuid4

from src.utils.logger import get_logger

logger = get_logger(__name__)
_PROCESS_RUN = uuid4().hex


def call_latency(event, call_id, **fields):
    logger.info(
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
