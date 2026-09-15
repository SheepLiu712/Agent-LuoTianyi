"""文本输入的语义预处理技能。"""

from __future__ import annotations

from typing import Any

from src.subconscious.music_knowledge.jargon import SongEntityLinker


class TextPreprocessingSkill:
    """从用户文本中提取歌曲实体等可用于对话与检索的语义线索。"""

    def __init__(self, preprocessing_config: dict[str, Any] | None = None) -> None:
        """按 agent.preprocessing 配置建立歌曲实体链接器。"""
        self._song_entity_linker = SongEntityLinker((preprocessing_config or {}).get("song_entity_linker", {}))

    def extract_terms(self, text: str) -> tuple[str, ...]:
        """返回文本中已验证的歌曲实体等关键词；输入非字符串抛 TypeError。"""
        if not isinstance(text, str):
            raise TypeError("text 应为字符串")
        return tuple(self._song_entity_linker.extract_and_verify(text) or ())
