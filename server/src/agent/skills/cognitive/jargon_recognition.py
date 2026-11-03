"""文本中的规范术语识别能力。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.agent.skills.cognitive.song_entity_linker import SongEntityLinker


class JargonRecognitionSkill:
    """从用户文本中提取歌曲实体等可用于对话与检索的语义线索。"""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        song_names: Iterable[str] = (),
    ) -> None:
        """按 skills.jargon_recognition 配置建立歌曲实体链接器。"""
        self._song_entity_linker = SongEntityLinker(
            (config or {}).get("song_entity_linker", {}),
            song_names=song_names,
        )

    def recognize(self, text: str) -> tuple[str, ...]:
        """返回文本中已验证的歌曲实体等关键词；输入非字符串抛 TypeError。"""
        if not isinstance(text, str):
            raise TypeError("text 应为字符串")
        return tuple(self._song_entity_linker.extract_and_verify(text) or ())
