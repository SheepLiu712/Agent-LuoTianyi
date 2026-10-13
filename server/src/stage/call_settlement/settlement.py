"""Bounded execution of one call settlement; StageManager owns its task."""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from src.domain.call import CallFinalSnapshot
from src.utils.logger import get_logger


class CallSettlementConsumer(Protocol):
    async def settle(self, snapshot: CallFinalSnapshot) -> None: ...


class CallResourceReleasePort(Protocol):
    def release_call_maintenance(self, call_id: UUID) -> None: ...


class CallSettlement:
    def __init__(
        self, *, consumer: CallSettlementConsumer, resources: CallResourceReleasePort, timeout_seconds: float = 15.0
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._consumer = consumer
        self._resources = resources
        self._timeout = timeout_seconds

    @property
    def is_ready(self) -> bool:
        return bool(getattr(self._consumer, "is_ready", False) and self._resources is not None)

    async def settle(self, snapshot: CallFinalSnapshot) -> None:
        call_id = snapshot.terminal.call_id
        operation = asyncio.create_task(self._consumer.settle(snapshot), name=f"call-settlement-consumer-{call_id}")
        try:
            await asyncio.wait_for(asyncio.shield(operation), timeout=self._timeout)
        except TimeoutError:
            get_logger(__name__).warning("Call settlement timed out call_id=%s", call_id)
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        except Exception as error:  # noqa: BLE001 - terminal cleanup must run after any consumer failure
            get_logger(__name__).error("Call settlement failed call_id=%s type=%s", call_id, type(error).__name__)
        finally:
            if not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
            self._resources.release_call_maintenance(call_id)
