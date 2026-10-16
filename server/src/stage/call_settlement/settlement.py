"""Bounded execution of one call settlement; StageManager owns its task."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

from src.domain.call import CallFinalSnapshot
from src.utils.logger import get_logger


class CallSettlementConsumer(Protocol):
    async def settle(self, snapshot: CallFinalSnapshot, *, context=None, deadline=None) -> None: ...


@dataclass(frozen=True, slots=True)
class CallSettlementDeadline:
    maintenance: float
    summary: float
    persistence: float

    def remaining(self, phase: str) -> float:
        return max(0.0, getattr(self, phase) - time.monotonic())


class CallSettlement:
    def __init__(self, *, consumer: CallSettlementConsumer, timeout_seconds: float = 15.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._consumer = consumer
        self._timeout = timeout_seconds

    @property
    def is_ready(self) -> bool:
        return bool(getattr(self._consumer, "is_ready", False))

    async def settle(self, snapshot: CallFinalSnapshot, *, context=None) -> None:
        call_id = snapshot.terminal.call_id
        started = time.monotonic()
        deadline = CallSettlementDeadline(
            maintenance=started + self._timeout * (8 / 15),
            summary=started + self._timeout * (12 / 15),
            persistence=started + self._timeout,
        )
        operation = asyncio.create_task(
            self._consumer.settle(snapshot, context=context, deadline=deadline),
            name=f"call-settlement-consumer-{call_id}",
        )
        try:
            done, _ = await asyncio.wait((operation,), timeout=deadline.remaining("persistence"))
            if done:
                operation.result()
                return
            get_logger(__name__).warning("Call settlement timed out call_id=%s", call_id)
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        except Exception as error:  # noqa: BLE001 - terminal cleanup must run after any consumer failure
            get_logger(__name__).error(
                "Call settlement failed call_id=%s type=%s error=%s", call_id, type(error).__name__, error
            )
