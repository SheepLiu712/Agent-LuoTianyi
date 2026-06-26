from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple, Dict
from .singing_manager import SingingManager
from src.domain.character import CharacterName


class SingingCapability:
    """Action capability for choosing and rendering sing actions."""

    def __init__(self, config: Dict[str, Any]) -> None:
        self._config: Dict[str, Any] = config
        self.singing_manager : Dict[str, SingingManager] = {}
        if "characters" in config:
            raise ValueError("capabilities.sing no longer supports a 'characters' layer; use sing.<character_id> directly.")
        for character_id, character_config in config.items():
            self.singing_manager[character_id] = SingingManager(character_config)
        self.default_character_id = CharacterName.LUOTIANYI.value if CharacterName.LUOTIANYI.value in self.singing_manager else next(
            iter(self.singing_manager),
            None,
        )
        self.music_manager = self.singing_manager.get(CharacterName.LUOTIANYI.value) or next(
            iter(self.singing_manager.values()),
            None,
        )

    def _get_manager(self, character_id: Optional[str] = None) -> SingingManager:
        resolved_id = character_id or self.default_character_id
        if resolved_id not in self.singing_manager:
            raise ValueError(f"Character ID '{resolved_id}' not found in singing manager.")
        return self.singing_manager[resolved_id]

    def build_sing_plan(
        self,
        character_id: str | List[str],
        sing_attempts: Optional[List[str]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        根据用户的唱歌尝试，构建一个唱歌计划。

        :param character_id: 角色ID
        :param sing_attempts: 用户的唱歌尝试列表
        :return: 一个元组，包含选定的歌曲名称和段落，如果没有选定的歌曲，则返回(None, None)
        """
        if sing_attempts is None:
            sing_attempts = character_id if isinstance(character_id, list) else []
            character_id = self.default_character_id

        manager = self._get_manager(character_id if isinstance(character_id, str) else None)

        if not sing_attempts:
            return None, None

        song_name = None
        for attempt in sing_attempts:
            candidate = (attempt or "").strip()
            if not candidate:
                continue
            if candidate == "random_song":
                pair = manager.pick_random_song_and_segment()
                return pair if pair else (None, None)

            song_name = self._extract_song_name(candidate)
            if not song_name:
                continue

            correct_song_name, segment = manager.pick_segment_for_song(song_name)
            if segment:
                return correct_song_name, segment
        if song_name:
            manager.add_wished_song(song_name)
        return song_name, None
    
    def can_i_sing_song(self, character_id: str, song_name: str) -> Tuple[str, List[str]]:
        '''
        检查某个角色是否可以演唱指定的歌曲。

        :param character_id: 角色ID
        :param song_name: 歌曲名称
        :return: 一个元组，第一个元素是歌曲的正确名称，第二个元素是该歌曲的可演唱段落列表。如果不能唱，则返回空歌名和空列表。
        '''
        return self._get_manager(character_id).can_i_sing_song(song_name)
    
    def get_songs_can_sing(self, character_id: str) -> Dict[str, str]:
        '''
        获取某个角色可以演唱的歌曲列表。

        :param character_id: 角色ID
        :return: 一个字典，键为歌曲名称，值为歌曲的描述
        '''
        return self._get_manager(character_id).get_songs_can_sing()
    
    async def get_songs_can_sing_llm(self, character_id: str, max_song_num: int = 5) -> str:
        '''
        获取某个角色可以演唱的歌曲列表（用于llm上下文的返回值）。

        :param character_id: 角色ID
        :param max_song_num: 最大返回歌曲数量
        :return: 一个字符串，包含角色可以演唱的歌曲列表以及其描述，格式化为适合llm上下文的文本。
        '''
        return await self._get_manager(character_id).get_songs_can_sing_llm(max_song_num)
    
    async def can_i_sing_song_llm(self, character_id: str, song_name: str) -> str:
        '''
        获取某个角色是否可以演唱指定歌曲的结果（用于llm上下文的返回值）。

        :param character_id: 角色ID
        :param song_name: 歌曲名称
        :return: 一个字符串，包含角色是否可以演唱指定歌曲的结果，格式化为适合llm上下文的文本。
        '''
        return await self._get_manager(character_id).can_i_sing_song_llm(song_name)

    def sing(
        self,
        character_id: str,
        song_name: Optional[str] = None,
        segment: Optional[str] = None,
    ) -> Optional[bytes]:
        '''
        演唱指定歌曲的指定段落。

        :param character_id: 角色ID
        :param song_name: 歌曲名称
        :param segment: 歌曲段落
        :return: 音频数据的字节流，如果无法演唱，则返回None
        '''
        if segment is None:
            segment = song_name
            song_name = character_id
            character_id = self.default_character_id
        if not song_name or not segment:
            return None
        _, audio_bytes = self._get_manager(character_id).get_song_segment(song_name, segment)
        return audio_bytes

    def get_segment_lyrics(
        self,
        character_id: str,
        song_name: Optional[str] = None,
        segment: Optional[str] = None,
    ) -> str:
        '''
        获取指定歌曲的指定段落的歌词。

        :param character_id: 角色ID
        :param song_name: 歌曲名称
        :param segment: 歌曲段落
        :return: 歌词文本，如果无法获取，则返回空字符串
        '''
        if segment is None:
            segment = song_name
            song_name = character_id
            character_id = self.default_character_id
        if not song_name or not segment:
            return ""
        return self._get_manager(character_id).get_segment_lyrics(song_name, segment)

    def _extract_song_name(self, text: str) -> str:
        content = (text or "").strip()
        if not content:
            return ""

        match = re.search(r"《([^》]+)》", content)
        if match:
            return match.group(1).strip()

        if "是一首歌" in content:
            return content.split("是一首歌", 1)[0].strip().strip("《》")

        return content.strip("\"'“”‘’《》")
