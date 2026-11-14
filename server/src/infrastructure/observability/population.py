"""Runtime-owned five-minute sampling; missing samples are never fabricated."""

import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4

from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned


class PopulationSampler:
    def __init__(self, manager, store):
        self.manager, self.store = manager, store
        self.runtime_id = uuid4().hex
        self.task = None

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self._run(), name="population-sampler")

    async def sample(self):
        counts = self.manager.snapshot_population()
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        await complete_owned(asyncio.to_thread(self.store.record_population, stamp, self.runtime_id, counts))

    async def _run(self):
        while True:
            await asyncio.sleep(300 - time.time() % 300)
            try:
                await self.sample()
            except Exception as error:
                get_logger(__name__).warning("Population sample failed type=%s", type(error).__name__)

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
