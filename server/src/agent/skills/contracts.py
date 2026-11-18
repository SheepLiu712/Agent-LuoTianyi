"""Agent 内部 Skill 之间传递的强类型值。"""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.agent import CancellationToken


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
class TopicExtraction:
    """同一次 topic_extract 决策产生的记忆检索 key 与演唱尝试。"""

    memory_queries: tuple[str, ...] = ()
    sing_attempts: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplyDraft:
    """一条已生成的回复草稿；sing 非空表示演唱，否则为说话。"""

    content: str
    sound_content: str
    tone: str
    expression: str | None
    sing: tuple[str, str] | None = None
    lyrics: str = ""
