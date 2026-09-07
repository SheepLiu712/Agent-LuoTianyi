"""根据对话窗口生成压缩结果。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TYPE_CHECKING

from src.agent.context import ConversationCompaction, ConversationContext, ConversationSummary

if TYPE_CHECKING:
    from src.utils.llm_service import LLMService


@dataclass(frozen=True)
class _CompactionConfig:
    """压缩模块自身使用的配置，不解析下传给模型的配置。"""

    raw_conversation_context_limit: int
    not_zip_conversation_count: int
    forget_conversation_days: int

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> _CompactionConfig:
        """校验并提取压缩参数，忽略不属于当前模块的字段。"""
        if not isinstance(config, dict):
            raise TypeError("conversation_compaction 必须是字典")
        values = {}
        for name, default in (
            ("raw_conversation_context_limit", 60),
            ("not_zip_conversation_count", 30),
            ("forget_conversation_days", 10),
        ):
            value = config.get(name, default)
            if type(value) is not int:
                raise TypeError(f"conversation_compaction.{name} 必须是整数")
            if value < 0:
                raise ValueError(f"conversation_compaction.{name} 不能小于 0")
            values[name] = value
        result = cls(**values)
        if result.not_zip_conversation_count > result.raw_conversation_context_limit:
            raise ValueError("conversation_compaction.not_zip_conversation_count 不能超过 raw_conversation_context_limit")
        return result


class ConversationCompactionSkill:
    """角色共享的对话压缩技能；每次调用只使用输入上下文的快照。"""

    def __init__(self, config: dict[str, Any], llm_service: LLMService) -> None:
        """从 config 读取压缩阈值与保留条数，通过 llm_service 注册总结模型。"""
        self._config = _CompactionConfig.from_dict(config)
        module_config = config.get("llm_module")
        self._llm = (llm_service.register_llm_module("conversation_context_summary", module_config)
                     if module_config is not None else None)

    async def compact(self, conversation_context: ConversationContext) -> ConversationCompaction | None:
        """读取 conversation_context 并生成压缩结果；未超过阈值返回 None。

        不修改输入上下文。模型未配置、调用失败或结果为空时抛出异常。
        """
        snapshot = conversation_context.read()
        if len(snapshot.entries) <= self._config.raw_conversation_context_limit:
            return None
        if self._llm is None:
            raise RuntimeError("未配置对话总结模型")
        covered = snapshot.entries[:-self._config.not_zip_conversation_count] if self._config.not_zip_conversation_count else snapshot.entries
        recent = "\n".join(f"[{entry.timestamp:%Y-%m-%d}]{entry.source}: {entry.content.text}"
                           for entry in covered)
        summary = await self._llm.generate_response(
            forget_conversation_days=self._config.forget_conversation_days,
            current_date=datetime.now().strftime("%Y-%m-%d"),
            current_summary=snapshot.summary.text,
            recent_conversation=recent,
        )
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("总结模型返回了空或非文字结果")
        return ConversationCompaction(snapshot.summary, tuple(entry.entry_id for entry in covered),
                                     ConversationSummary(summary.strip()))
