"""Agent 内部 Skill 之间传递的强类型值。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from src.domain.agent import CancellationToken
from src.domain.memory_context import MemoryHit


@dataclass(frozen=True, slots=True)
class SkillInvocation:
    """一次 Skill 调用的身份与取消上下文。

    Skill 实例在所有角色之间共享；角色、用户和交互身份只能通过这个不可变值
    进入调用，禁止写入 Skill 的实例字段。user_id 为 None 表示不属于特定用户的
    世界事实或公开效果。
    """

    character_id: str
    user_id: str | None
    interaction_id: str
    cancellation: CancellationToken

    def __post_init__(self) -> None:
        for name, value in (
            ("character_id", self.character_id),
            ("interaction_id", self.interaction_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} 不能为空")
        if self.user_id is not None and (not isinstance(self.user_id, str) or not self.user_id.strip()):
            raise ValueError("user_id 不能为空字符串")
        if not isinstance(self.cancellation, CancellationToken):
            raise TypeError("cancellation 必须是 CancellationToken")

    def require_user_id(self) -> str:
        """返回已认证用户身份；本次调用无用户时明确失败。"""
        if self.user_id is None:
            raise RuntimeError("该 Skill 调用需要已认证用户")
        return self.user_id


@dataclass(frozen=True, slots=True)
class CharacterNarrative:
    """共享 Skill 生成角色化内容时使用的只读角色叙事资料。"""

    name: str
    persona: str
    speaking_style: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("角色名称不能为空")
        if not isinstance(self.persona, str) or not isinstance(self.speaking_style, str):
            raise TypeError("角色人设与表达风格必须是字符串")


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
