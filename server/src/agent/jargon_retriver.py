from pathlib import Path
from typing import List, Tuple

from flashtext import KeywordProcessor


class SongEntityLinker:
    def __init__(self, songname_file: str | None = None, lyric_file: str | None = None):
        self.songname_retriver = KeywordProcessor()
        self.lyric_retriver = KeywordProcessor()
        self.songname_file = songname_file or str(
            Path(__file__).resolve().parents[2] / "res" / "knowledge" / "song_name_keywords.txt"
        )
        self.lyric_file = lyric_file or str(
            Path(__file__).resolve().parents[2] / "res" / "knowledge" / "song_lyric_keywords.txt"
        )
        self._load_keywords_from_file()
        
        # 2. 定义触发动词（激活信号）
        self.trigger_verbs = {"听", "唱", "点", "循环", "安利", "写", "作曲", "调教", "歌"}

    def extract_and_verify(self, user_input: str) -> List[str]:
        '''
        从用户输入中提取候选实体，并根据是否包含触发动词来判断是否激活。
        返回一个元组，包含所有找到的歌名和歌词实体及其解释。
        '''
        # 步骤 A: 用 FlashText 快速抓取候选词
        songnames_found = self.songname_retriver.extract_keywords(user_input)
        lyrics_found = self.lyric_retriver.extract_keywords(user_input)

        triggered = any(verb in user_input for verb in self.trigger_verbs)
        if not triggered:
            songnames_found = []
        
        results = []
        for song in songnames_found:
            results.append(f"《{song}》是一首歌")
        for lyric in lyrics_found:
            results.append(f"{lyric}")

        return results


    def _load_keywords_from_file(self) -> None:
        """加载离线生成的关键词词典，供 FlashText 快速匹配。"""
        songname_path = Path(self.songname_file)
        lyric_path = Path(self.lyric_file)

        if not songname_path.exists() or not lyric_path.exists():
            return

        # 一行一个关键词，兼容 build_song_keywords.py 的输出格式
        self.songname_retriver.add_keyword_from_file(str(songname_path))
        self.lyric_retriver.add_keyword_from_file(str(lyric_path))

song_entity_linker = SongEntityLinker()

def extract_song_entities(user_input: str) -> List[str]:
    """对外接口：从用户输入中提取歌名和歌词实体，并返回解释文本列表。"""
    return song_entity_linker.extract_and_verify(user_input)