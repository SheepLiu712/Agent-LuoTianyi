from typing import List, Tuple, Dict, Any, Optional, Callable
import asyncio
import re

from sqlalchemy.orm import Session

from src.utils.logger import get_logger
from src.capabilities.singing import SingingManager
from src.world.learn_sing_songs.auto_song_learner import AutoSongLearner
from src.subconscious.music_knowledge.knowledge_service import get_song_introduction, get_song_lyrics
from src.subconscious.music_knowledge.song_database import get_song_session, init_song_db

class MusicManager:
    """
    MusicManager 作为 agent 的统一音乐接口，封装底层的 SingingManager 和知识库搜索。
    """
    def __init__(self, config: Dict[str, Any]):
        self.logger = get_logger(__name__)
        self.config = config
        
        # 初始化知识库连接
        song_db_config = config.get("song_knowledge", {}).get("song_database", {})
        if song_db_config:
            init_song_db(song_db_config)
        else:
            raise ValueError("MusicManager 初始化失败：缺少 song_database 配置")
            
        self.song_session_factory = get_song_session
        
        # 将配置传给 SingingManager
        self.singing_manager = SingingManager(config["singing_manager"])
        self.auto_song_learner = AutoSongLearner(
            config=config["auto_song_learner"], wishlist=self.wishlist
        )



    @property
    def wishlist(self):
        return self.singing_manager.wishlist

    def pick_random_song_and_segment(self) -> Optional[Tuple[str, str]]:
        return self.singing_manager.pick_random_song_and_segment()

    def pick_segment_for_song(self, song_name: str) -> Tuple[str, str]:
        return self.singing_manager.pick_segment_for_song(song_name)

    def add_wished_song(self, song_name: str) -> bool:
        return self.singing_manager.add_wished_song(song_name)

    def get_song_segment(self, song_name: str, segment_description: str, require_audio: bool = True) -> Tuple[List[Any], bytes | None]:
        return self.singing_manager.get_song_segment(song_name, segment_description, require_audio)

    def get_segment_lyrics(self, song_name: str, segment_description: str) -> str:
        return self.singing_manager.get_segment_lyrics(song_name, segment_description)

    async def get_songs_can_sing_llm(self, max_song_num: int = 5) -> str:
        return await self.singing_manager.get_songs_can_sing_llm(max_song_num)

    async def can_i_sing_song_llm(self, song_name: str) -> str:
        return await self.singing_manager.can_i_sing_song_llm(song_name)
        
    def get_songs_can_sing(self, max_song_num: int = 5) -> Dict[str, Any]:
        return self.singing_manager.get_songs_can_sing(max_song_num)
        
    def can_i_sing_song(self, song_name: str) -> Tuple[str, List[str]]:
        return self.singing_manager.can_i_sing_song(song_name)

    async def search_song_facts_for_topic(self, constraints: List[str]) -> List[str]:
        if not constraints:
            return []

        db = self.song_session_factory()
        try:
            dedup: List[str] = []
            seen = set()
            for raw in constraints:
                song_name = self._extract_song_name(raw)
                if not song_name:
                    continue

                intro = await asyncio.to_thread(get_song_introduction, db, song_name)
                lyrics = await asyncio.to_thread(get_song_lyrics, db, song_name)

                if intro:
                    text = f"《{song_name}》的介绍:\n{intro}"
                    if text not in seen:
                        seen.add(text)
                        dedup.append(text)

                if lyrics:
                    text = f"《{song_name}》的歌词:\n{lyrics}"
                    if text not in seen:
                        seen.add(text)
                        dedup.append(text)

            return dedup
        finally:
            db.close()

    def _extract_song_name(self, text: str) -> str:
        content = (text or "").strip()
        if not content:
            return ""

        m = re.search(r"《([^》]+)》", content)
        if m:
            return m.group(1).strip()

        if "是一首歌" in content:
            return content.split("是一首歌", 1)[0].strip().strip("《》")

        return content.strip("\"'“”‘’《》")
