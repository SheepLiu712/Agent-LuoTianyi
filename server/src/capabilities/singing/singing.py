from __future__ import annotations

import re
from typing import Any, Collection, List, Optional, Tuple, Dict
from .singing_manager import SingingManager
from .song_emotion_tagger import SongEmotionTagger
from src.domain.character import CharacterName


class SingingCapability:
    """Action capability for choosing and rendering sing actions."""

    def __init__(self, config: Dict[str, Any], llm_service=None) -> None:
        self._config: Dict[str, Any] = config
        self.singing_manager : Dict[str, SingingManager] = {}
        if "characters" in config:
            raise ValueError("capabilities.sing no longer supports a 'characters' layer; use sing.<character_id> directly.")
        self.song_emotion_tagger = SongEmotionTagger()
        tagger_config = config.get("song_emotion_tagger")
        if llm_service is not None and isinstance(tagger_config, dict):
            self.song_emotion_tagger.register(llm_service, tagger_config)
        for character_id, character_config in config.items():
            if character_id == "song_emotion_tagger":
                continue
            self.singing_manager[character_id] = SingingManager(character_config)
        self.default_character_id = CharacterName.LUOTIANYI.value if CharacterName.LUOTIANYI.value in self.singing_manager else next(
            iter(self.singing_manager),
            None,
        )
        self.music_manager = self.singing_manager.get(CharacterName.LUOTIANYI.value) or next(
            iter(self.singing_manager.values()),
            None,
        )

    def ensure_dependencies(self) -> None:
        """检查歌唱能力依赖已经初始化。"""
        required = {
            "singing_manager": self.singing_manager,
            "default_character_id": self.default_character_id,
            "music_manager": self.music_manager,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"SingingCapability dependencies are missing: {', '.join(missing)}")

    def _get_manager(self, character_id: Optional[str] = None) -> SingingManager:
        resolved_id = character_id or self.default_character_id
        if resolved_id not in self.singing_manager:
            raise ValueError(f"Character ID '{resolved_id}' not found in singing manager.")
        return self.singing_manager[resolved_id]

    def reload_songs(self, character_id: Optional[str] = None) -> None:
        """Reload one character's song library, or all libraries when no character is specified."""
        if character_id:
            self._get_manager(character_id).reload_songs()
            return
        for manager in self.singing_manager.values():
            manager.reload_songs()

    async def build_sing_plan(
        self,
        character_id: str | List[str],
        sing_attempts: Optional[List[str]] = None,
        excluded_segments: Collection[tuple[str, str]] | None = None,
        emotion_context: str = "",
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
        excluded = set(excluded_segments or ())

        if not sing_attempts:
            return None, None

        song_name = None
        for attempt in sing_attempts:
            candidate = (attempt or "").strip()
            if not candidate:
                continue
            if candidate == "random_song":
                target_tags = []
                if emotion_context.strip():
                    target_tags = await self.song_emotion_tagger.infer_target_tags(emotion_context)
                pair = manager.pick_random_song_and_segment(
                    target_emotion_tags=target_tags,
                    excluded_segments=excluded,
                )
                return pair if pair else (None, None)

            song_name = self._extract_song_name(candidate)
            if not song_name:
                continue

            correct_song_name, segment = manager.pick_segment_for_song(
                song_name,
                excluded_segments=excluded,
            )
            if segment:
                return correct_song_name, segment
        if song_name:
            manager.add_wished_song(song_name)
        return song_name, None

    async def tag_song_emotions(self, character_id: str, song_name: str) -> list[str]:
        """Classify a song's full lyrics and persist its tags in the song JSON."""
        manager = self._get_manager(character_id)
        metadata = manager.get_song_metadata(song_name)
        if metadata is None:
            return []
        tags = await self.song_emotion_tagger.tag_song(
            metadata.song_name,
            manager.get_full_lyrics(metadata.song_name),
        )
        if tags:
            manager.update_song_emotion_tags(metadata.song_name, tags)
        return tags

    def resolve_sing_plan(
        self,
        character_id: str,
        song_name: str,
        preferred_segment: str | None = None,
        excluded_segments: Collection[tuple[str, str]] | None = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """校验最终唱歌意图，并按会话历史重新选择可唱段落。"""
        manager = self._get_manager(character_id)
        correct_song_name, segments = manager.can_i_sing_song(song_name)
        if not correct_song_name or not segments:
            return None, None

        excluded = set(excluded_segments or ())
        available = [
            segment
            for segment in segments
            if (correct_song_name, segment) not in excluded
        ]
        candidates = available or segments
        if preferred_segment and preferred_segment in candidates:
            return correct_song_name, preferred_segment
        return correct_song_name, candidates[0]
    
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

    def get_full_lyrics(
        self,
        character_id: str,
        song_name: Optional[str] = None,
    ) -> str:
        '''
        获取指定歌曲的完整歌词。

        :param character_id: 角色ID
        :param song_name: 歌曲名称
        :return: 歌词文本，如果无法获取，则返回空字符串
        '''
        if song_name is None:
            song_name = character_id
            character_id = self.default_character_id
        if not song_name:
            return ""
        return self._get_manager(character_id).get_full_lyrics(song_name)

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
