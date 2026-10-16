"""签署门禁：前台累计阅读时长与"到过底部"两个条件，及按钮文案/可用性。

刻意不依赖 Qt：计时与底部判定是本功能最容易出错的部分，单独成模块后可以直接用
单元测试覆盖（含后台暂停、时钟回拨、内容一屏放得下、重开重置等边界）。
Qt 层只负责把事件（计时 tick、滚动、加载结果）喂进来，并把文案画到界面上。
"""

from __future__ import annotations

import math
from typing import Optional

READING_SECONDS = 5
# 滚动容器可视范围距末尾的容差（布局单位），契约允许不超过 2 个布局单位的舍入误差。
BOTTOM_TOLERANCE = 2

STATUS_LOADING = "loading"
STATUS_LOAD_FAILED = "load_failed"
STATUS_READING = "reading"
STATUS_READY = "ready"
STATUS_SUBMITTING = "submitting"

TEXT_CONFIRM_WAITING = "我已阅读并同意（剩余 {seconds} 秒）"
TEXT_CONFIRM = "我已阅读并同意用户协议"
TEXT_SUBMITTING = "正在提交…"
TEXT_BOTTOM_HINT = "请阅读至协议底部"
TEXT_LOAD_FAILED = "用户协议加载失败，请重试"


class SigningGate:
    """新用户签署前的阅读门禁；只保存状态，不碰界面。"""

    def __init__(self, required_seconds: int = READING_SECONDS, bottom_tolerance: int = BOTTOM_TOLERANCE) -> None:
        self.required_seconds = required_seconds
        self.bottom_tolerance = bottom_tolerance
        self._elapsed = 0.0
        self._status = STATUS_LOADING
        self._reached_bottom = False
        self._last_tick: Optional[float] = None
        self._active = False

    # ── 生命周期 ─────────────────────────────────────────────────
    def begin_loading(self) -> None:
        """重新加载正文（首次打开、重试、协议换版、重新打开窗口）：计时与底部条件全部重置。"""
        self._elapsed = 0.0
        self._status = STATUS_LOADING
        self._reached_bottom = False
        self._last_tick = None
        self._active = False

    def mark_loaded(self) -> None:
        """正文渲染成功：此刻才开始允许计时与底部判定。"""
        if self._status in (STATUS_LOADING, STATUS_LOAD_FAILED, STATUS_READING, STATUS_READY):
            self._status = STATUS_READY if self._conditions_met() else STATUS_READING
            self._last_tick = None

    def mark_load_failed(self) -> None:
        self._status = STATUS_LOAD_FAILED
        self._last_tick = None
        self._active = False

    def resume(self, now: float) -> None:
        """窗口/应用回到前台：从此刻开始累计，不补算离开期间的时间。"""
        self._active = True
        self._last_tick = now

    def pause(self) -> None:
        """失去前台（最小化、切后台、弹窗遮挡）：停止累计。"""
        self._active = False
        self._last_tick = None

    def tick(self, now: float) -> None:
        """前台有效时间内周期调用；只累计单调时钟的真实前进量，忽略回拨。"""
        if not self._active or self._status in (STATUS_LOADING, STATUS_LOAD_FAILED, STATUS_SUBMITTING):
            return
        last = self._last_tick
        self._last_tick = now
        if last is None:
            return
        delta = now - last
        if delta <= 0:
            return
        self._elapsed += delta
        self._refresh_status()

    def observe_scroll(self, value: int, maximum: int) -> None:
        """滚动容器的当前位置与最大值；"到过底部"在同一次打开内保持。"""
        if self._status in (STATUS_LOADING, STATUS_LOAD_FAILED):
            return
        if self._reached_bottom:
            return
        if maximum <= self.bottom_tolerance:
            # 正文一屏完整显示：没有可滚动区间，视为已到过底部。
            self._reached_bottom = True
        elif value >= maximum - self.bottom_tolerance:
            self._reached_bottom = True
        self._refresh_status()

    # ── 提交 ────────────────────────────────────────────────────
    def begin_submit(self) -> None:
        self._status = STATUS_SUBMITTING
        self.pause()

    def end_submit(self) -> None:
        """提交结束（失败或超时）：恢复可操作状态，并保留本窗口的阅读状态。"""
        self._status = STATUS_READY if self._conditions_met() else STATUS_READING

    # ── 只读状态 ────────────────────────────────────────────────
    @property
    def status(self) -> str:
        return self._status

    @property
    def elapsed_seconds(self) -> float:
        return self._elapsed

    @property
    def remaining_seconds(self) -> int:
        return max(0, math.ceil(self.required_seconds - self._elapsed))

    @property
    def reached_bottom(self) -> bool:
        return self._reached_bottom

    @property
    def can_confirm(self) -> bool:
        return self._status == STATUS_READY

    @property
    def confirm_text(self) -> str:
        if self._status == STATUS_SUBMITTING:
            return TEXT_SUBMITTING
        if self._status in (STATUS_LOADING, STATUS_LOAD_FAILED):
            return TEXT_CONFIRM
        remaining = self.remaining_seconds
        return TEXT_CONFIRM_WAITING.format(seconds=remaining) if remaining > 0 else TEXT_CONFIRM

    @property
    def hint_text(self) -> str:
        if self._status in (STATUS_LOADING, STATUS_LOAD_FAILED, STATUS_SUBMITTING):
            return ""
        return "" if self._reached_bottom else TEXT_BOTTOM_HINT

    @property
    def load_failed_text(self) -> str:
        return TEXT_LOAD_FAILED if self._status == STATUS_LOAD_FAILED else ""

    def _conditions_met(self) -> bool:
        return self._elapsed >= self.required_seconds and self._reached_bottom

    def _refresh_status(self) -> None:
        if self._status in (STATUS_LOADING, STATUS_LOAD_FAILED, STATUS_SUBMITTING):
            return
        self._status = STATUS_READY if self._conditions_met() else STATUS_READING
