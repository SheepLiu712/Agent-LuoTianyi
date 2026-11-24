"""Bounded, read-only coroutine locations; never serialize frames or local values."""

import asyncio
from pathlib import Path


def task_snapshot(task: asyncio.Task | None) -> dict | None:
    if task is None:
        return None
    state = "cancelled" if task.cancelled() else "done" if task.done() else "pending"
    frames = []
    coroutine = task.get_coro()
    seen = set()
    while coroutine is not None and id(coroutine) not in seen and len(seen) < 24:
        seen.add(id(coroutine))
        frame = getattr(coroutine, "cr_frame", None) or getattr(coroutine, "gi_frame", None)
        if frame is not None:
            frames.append(
                {"file": Path(frame.f_code.co_filename).name, "function": frame.f_code.co_name, "line": frame.f_lineno}
            )
        coroutine = getattr(coroutine, "cr_await", None) or getattr(coroutine, "gi_yieldfrom", None)
    return {"state": state, "frames": frames}
