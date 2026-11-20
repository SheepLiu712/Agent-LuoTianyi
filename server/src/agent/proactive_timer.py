"""每次交互独立的主动发言计时器；热度与发言机会由角色管理。"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import src.domain.agent as d


@dataclass(frozen=True)
class ProactivePolicy:
    silence_seconds: float = 30.0
    half_life_seconds: float = 60.0
    threshold: float = 0.5

    def __post_init__(self):
        for name in ("silence_seconds", "half_life_seconds", "threshold"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if value < 0 or (name != "threshold" and value == 0):
                raise ValueError(f"invalid {name}")


class ProactiveTimer:
    """单次计时、半衰期热度和不累积的发言机会；回调同步交给交互队列。"""

    def __init__(
        self,
        *,
        character_id: str,
        user_id: str,
        policy: ProactivePolicy,
        on_due: Callable[[d.ProactiveSpeechDue], None],
        initial_opportunity: bool = False,
        monotonic: Callable[[], float] = time.monotonic,
        schedule=None,
    ):
        self._character_id = character_id
        self._user_id = user_id
        self._policy = policy
        self._on_due = on_due
        self._monotonic = monotonic
        self._schedule = schedule or asyncio.get_running_loop().call_later
        self._heat = float(initial_opportunity)
        self._had_heat = initial_opportunity
        self._opportunity = initial_opportunity
        self._updated_at = monotonic()
        self._generation = 0
        self._timer = None
        self._issued_id = None

    @property
    def running(self) -> bool:
        return self._timer is not None

    def start_timer(self) -> None:
        """重新计完整时长；不创造新的发言机会。"""
        self.stop_timer()
        if self._opportunity:
            self._timer = self._schedule(self._policy.silence_seconds, self._expire, self._generation)

    def stop_timer(self) -> None:
        """停止倒计时并使尚未处理的到期刺激失效；保留机会和衰减基准。"""
        self._generation += 1
        self._issued_id = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def get_user_stimulus(self) -> None:
        """接纳一条已去重的有效用户输入：增加热度、恢复一次机会并暂停。"""
        self.stop_timer()
        self._decay()
        self._heat += 1.0
        self._had_heat = True
        self._opportunity = True

    def is_current(self, stimulus: d.ProactiveSpeechDue) -> bool:
        return stimulus.stimulus_id == self._issued_id and stimulus.generation == self._generation

    def _decay(self) -> None:
        now = self._monotonic()
        self._heat *= 2.0 ** (-(now - self._updated_at) / self._policy.half_life_seconds)
        self._updated_at = now

    def _expire(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._timer = None
        self._decay()
        hot = self._had_heat if self._policy.threshold == 0 else self._heat > self._policy.threshold
        if not self._opportunity or not hot:
            return
        self._opportunity = False
        self._issued_id = str(uuid4())
        self._on_due(
            d.ProactiveSpeechDue(
                stimulus_id=self._issued_id,
                schema_version=1,
                occurred_at=datetime.now(timezone.utc),
                source=d.StimulusSource.AGENT,
                target_character_ids=(self._character_id,),
                user_id=self._user_id,
                ephemeral=True,
                generation=self._generation,
            )
        )
