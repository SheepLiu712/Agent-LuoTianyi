"""Content-free stage durations persisted through the existing metrics store."""

import asyncio
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from src.infrastructure.observability import get_observability_service
from src.utils.logger import get_logger


@contextmanager
def stage_timing(interaction_id, name, **metadata):
    service = get_observability_service()
    started = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    clock = time.perf_counter()
    result = {"status": "success"}
    try:
        yield result
    except BaseException as error:
        result["status"] = "cancelled" if isinstance(error, asyncio.CancelledError) else "error"
        metadata["error_type"] = type(error).__name__
        raise
    finally:
        duration_ms = (time.perf_counter() - clock) * 1000
        ended = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        if service is not None:
            try:
                service.record_pipeline_span(
                    trace_id=f"stage:{interaction_id}",
                    span_name=name,
                    start_ts=started,
                    end_ts=ended,
                    duration_ms=duration_ms,
                    status=result["status"],
                    metadata={**metadata, **{key: value for key, value in result.items() if key != "status"}},
                )
            except Exception as error:
                get_logger(__name__).warning("Stage timing persistence failed type=%s", type(error).__name__)
