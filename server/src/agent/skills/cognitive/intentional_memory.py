"""明确记忆请求的过渡期短语识别。"""
from __future__ import annotations

from typing import Any, Final

_LEGACY_PHRASES: Final = ("请记住", "记住", "记一下")


class ExplicitMemoryIntentSkill:
    """按配置 allowlist 从批次文本中提取用户要求长期记住的内容。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """读取 enabled 与 phrases；省略短语时保留旧链路默认短语。"""
        values = config or {}
        if not isinstance(values, dict):
            raise TypeError("memory.explicit_intent 必须是字典")
        self._enabled = values.get("enabled", True) is True
        configured = values.get("phrases", ())
        if not isinstance(configured, (list, tuple)) or any(
            not isinstance(item, str) for item in configured
        ):
            raise TypeError("memory.explicit_intent.phrases 必须是字符串列表")
        self._phrases = tuple(dict.fromkeys(
            phrase.strip() for phrase in (*configured, *_LEGACY_PHRASES) if phrase.strip()
        ))

    def detect(self, text: str) -> str | None:
        """命中首个短语时返回其后的非空记忆正文，否则返回 None。"""
        if not self._enabled:
            return None
        matches = (
            (text.find(phrase), phrase)
            for phrase in self._phrases
            if phrase in text
        )
        match = min(matches, default=None, key=lambda item: item[0])
        if match is None:
            return None
        content = text[match[0] + len(match[1]):].strip(" \t\r\n：:，,。！!")
        return content or None
