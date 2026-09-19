"""Agent 内部 Skill 之间传递的强类型值。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from src.domain.memory_context import MemoryHit


@dataclass(frozen=True)
class ReplyDraft:
    """一条已生成的回复草稿；sing 非空表示演唱，否则为说话。"""

    content: str
    sound_content: str
    tone: str
    expression: str | None
    sing: tuple[str, str] | None = None
    lyrics: str = ""


@dataclass(frozen=True)
class ComposedReply:
    """一次生成的完整回复草稿及其所依据的召回命中。"""

    drafts: tuple[ReplyDraft, ...] = ()
    memory_hits: tuple[MemoryHit, ...] = ()


@dataclass
class ComposedResponse:
    """两阶段生成的内部结果；可选临时草稿之后取得正式回复。"""

    provisional: tuple[ReplyDraft, ...] | None = None
    pending: Callable[[], Awaitable[ComposedReply]] | None = None
    _settled: ComposedReply | None = field(default=None, init=False, repr=False)

    @property
    def awaits_formal(self) -> bool:
        """返回是否还有尚未取得的正式结果。"""
        return self.pending is not None

    async def formal(self) -> ComposedReply:
        """取得正式结果；已取得时返回同一结果，不重复生成。"""
        if self._settled is None:
            if self.pending is None:
                self._settled = ComposedReply()
            else:
                pending, self.pending = self.pending, None
                self._settled = await pending()
        return self._settled
