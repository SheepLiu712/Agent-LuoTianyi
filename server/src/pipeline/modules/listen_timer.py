from typing import Optional
import asyncio
import time

class ListenTimer:
    def __init__(self, username: str, user_id: str, timeout: float = 2.5):
        self.listening_timeout_seconds: float = timeout
        self.listening_deadline: Optional[float] = None
        self._timer_lock = asyncio.Lock()

    async def set_deadline(self, timeout: Optional[float] = None):
        async with self._timer_lock:
            if timeout is not None:
                this_time_timeout = timeout
            else:
                this_time_timeout = self.listening_timeout_seconds
            self.listening_deadline = time.monotonic() + this_time_timeout

    async def remove_deadline(self):
        async with self._timer_lock:
            self.listening_deadline = None

    @property
    async def deadline(self) -> Optional[float]:
        async with self._timer_lock:
            return self.listening_deadline