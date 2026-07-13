from src.utils.logger import get_logger
import pathlib
import os
import json
import io
import re
import traceback
from src.domain.music_type import SongSegment, SongMetadata, OneLyricLine, WishEntry
from src.domain.tool_type import  MyTool, ToolFunction, ToolOneParameter
from typing import List, Tuple, Dict, Any, Optional
import random
from src.world.learn_sing_songs.auto_song_learner import WishlistManager
from src.utils.helpers import get_unified_song_name


class SingingManager:
    def __init__(self, config: Dict[str, Any]):
        self.logger = get_logger(__name__)
        self.config = config
        self.character_name = config.get("character_name", "洛天依")
        self.resource_path = config.get("resource_path")
        if not self.resource_path:
            raise ValueError("SingingManager requires capabilities.sing.<character_id>.resource_path")
        self.all_songs: dict[str, SongMetadata] = {}
        self.song_aliases: dict[str, str] = {}
        self.tools: Dict[str, MyTool] = {}
        self.wishlist = WishlistManager(
            str(pathlib.Path(self.resource_path) / "metadata.json"),
            self.logger,
        )
        self.get_music_data()
        self.wishlist.sync_existing_songs(set(self.all_songs.keys()) | set(self.song_aliases.keys()))

    @staticmethod
    def get_unified_song_name(song_name: str) -> str:
        return get_unified_song_name(song_name)

    # —————初始化获得所有歌曲数据————

    def get_music_data(self):
        self.logger.info(f"Loading music data from {self.resource_path}")
        self.all_songs = {}
        self.song_aliases = {}
        music_lib = pathlib.Path(self.resource_path) / "songs"
        if not music_lib.exists():
            self.logger.warning(f"Music library path does not exist: {music_lib}")
            return

        for song in os.listdir(music_lib):
            song_dir = music_lib / song
            if not song_dir.is_dir():  # 安全名字即歌夹名称
                continue
            # 一首歌的文件包括：歌词文件 .lrc，音频文件 .mp3 以及配置文件 .json
            lyrics_file = song_dir / f"{song}.lrc"
            audio_file_mp3 = song_dir / f"{song}.cleaned.mp3"
            config_file = song_dir / f"{song}.json"
            if not lyrics_file.exists():
                self.logger.warning(f"Lyrics file missing for song {song}")
                continue
            if not audio_file_mp3.exists():
                audio_file_mp3 = song_dir / f"{song}.mp3"
                if not audio_file_mp3.exists():
                    self.logger.warning(f"Old audio file also missing for song {song}")
                    continue
            if not config_file.exists():
                self.logger.warning(f"Config file missing for song {song}")
                continue

            # 读取配置文件
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    song_config = json.load(f)
                title = song_config.get("title", song)
                description = song_config.get("description", "")
                lrc_offset = song_config.get("lrc_offset", 0)
                segments = song_config.get("segments", [])
                emotion_tags = song_config.get("emotion_tags", [])
                if isinstance(emotion_tags, str):
                    emotion_tags = [emotion_tags]
                if not isinstance(emotion_tags, list):
                    emotion_tags = []
                segment_objs = []
                for seg in segments:
                    segment_objs.append(
                        SongSegment(
                            description=seg.get("description", ""),
                            start_time=seg.get("start_time", 0),
                            end_time=seg.get("end_time", 0),
                            lyrics=seg.get("lyrics", ""),
                        )
                    )
                song_metadata = SongMetadata(
                    song_name=song,
                    title=title,
                    description=description,
                    song_path=str(audio_file_mp3),
                    lrc_path=str(lyrics_file),
                    lrc_offset=lrc_offset,
                    segments=segment_objs,
                    emotion_tags=[str(tag).strip() for tag in emotion_tags if str(tag).strip()],
                )
                unified_song_name = SingingManager.get_unified_song_name(title)
                self.all_songs[unified_song_name] = song_metadata
                self._index_song_aliases(
                    canonical_key=unified_song_name,
                    aliases=[title, song, config_file.stem],
                )

            except Exception as e:
                import traceback

                self.logger.error(f"Failed to load song {song} config: {e}\n{traceback.format_exc()}")
        self.logger.info(f"Loaded {len(self.all_songs)} songs into music manager.")

    def _index_song_aliases(self, canonical_key: str, aliases: List[str]) -> None:
        for alias in aliases:
            unified_alias = SingingManager.get_unified_song_name(alias)
            if unified_alias:
                self.song_aliases[unified_alias] = canonical_key

    def reload_songs(self) -> None:
        """Re-scan songs/ directory to pick up newly learned songs."""
        old_count = len(self.all_songs)
        self.get_music_data()
        self.wishlist.sync_existing_songs(set(self.all_songs.keys()) | set(self.song_aliases.keys()))

    def update_song_emotion_tags(self, song_name: str, emotion_tags: list[str]) -> bool:
        metadata = self.get_song_metadata(song_name)
        if metadata is None:
            return False
        config_path = pathlib.Path(metadata.song_path).parent / f"{metadata.song_name}.json"
        if not config_path.exists():
            return False
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            normalized = []
            for tag in emotion_tags:
                value = str(tag).strip()
                if value and value not in normalized:
                    normalized.append(value)
            data["emotion_tags"] = normalized
            tmp_path = config_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(config_path)
            metadata.emotion_tags = normalized
            return True
        except Exception as exc:
            self.logger.warning(f"Failed to persist emotion tags for {song_name}: {exc}")
            return False
        self.logger.info(f"Reloaded songs: {old_count} → {len(self.all_songs)}")

    # ————歌曲选择相关————

    def pick_segment_for_song(
        self,
        song_name: str,
        excluded_segments: set[tuple[str, str]] | None = None,
    ) -> Tuple[str, str]:
        """为指定歌曲随机选择一个可唱唱段描述。"""
        correct_song_name, segments = self.can_i_sing_song(song_name)
        if not segments:
            return "", ""
        excluded = excluded_segments or set()
        available = [
            segment
            for segment in segments
            if (correct_song_name, segment) not in excluded
        ]
        return correct_song_name, random.choice(available or segments)

    def pick_random_song_and_segment(
        self,
        target_emotion_tags: list[str] | None = None,
        excluded_segments: set[tuple[str, str]] | None = None,
    ) -> Optional[Tuple[str, str]]:
        """从可唱曲库中随机选择一首歌及其可唱唱段。"""
        if not self.all_songs:
            return None, None

        target_tags = {str(tag).strip() for tag in (target_emotion_tags or []) if str(tag).strip()}
        candidates = list(self.all_songs.items())
        if target_tags:
            tagged_candidates = [
                item for item in candidates
                if target_tags.intersection(item[1].emotion_tags)
            ]
            if tagged_candidates:
                candidates = tagged_candidates

        unified_song_names = [song_name for song_name, _ in candidates]
        random.shuffle(unified_song_names)
        for unified_song_name in unified_song_names:
            correct_song_name, segment = self.pick_segment_for_song(
                unified_song_name,
                excluded_segments=excluded_segments,
            )
            if segment:
                return correct_song_name, segment
        return None, None

    def can_i_sing_song(self, song_name: str) -> Tuple[str, List[str]]:
        """
        检查是否可以演唱指定歌曲，如果可以，返回能够唱的唱段列表，否则返回空列表
        """
        if not song_name:
            return "", []
        safe_song_name = SingingManager.get_unified_song_name(song_name)
        song_metadata = self.get_song_metadata(safe_song_name)
        if not song_metadata:
            return "", []
        if not song_metadata.segments:
            self.add_wished_song(safe_song_name)
            return "", []
        return song_metadata.song_name, [segment.description for segment in song_metadata.segments]

    def get_songs_can_sing(self, max_song_num: int = 5) -> Dict[str, Any]:
        song_and_desc = {}
        # shuffle and get max_song_num songs
        selected_songs = random.sample(list(self.all_songs.items()), min(max_song_num, len(self.all_songs)))
        for song_name, metadata in selected_songs:
            song_and_desc[metadata.song_name] = metadata.description

        # to json string
        return song_and_desc
    
    async def get_songs_can_sing_llm(self, max_song_num: int = 5) -> str:
        song_and_desc = self.get_songs_can_sing(max_song_num)
        return json.dumps(song_and_desc, ensure_ascii=False)

    async def can_i_sing_song_llm(self, song_name: str) -> str:
        if not song_name:
            return "没有指定歌曲名称。"
        correct_song_name, segments = self.can_i_sing_song(song_name)
        if not segments:
            return f"{self.character_name}目前无法演唱{song_name}。"
        return f"{self.character_name}可以演唱{correct_song_name}，可以唱的唱段有：{', '.join(segments)}。"

    # ————愿望清单相关————

    def add_wished_song(self, song_name: str) -> bool:
        return self.wishlist.add(song_name)

    def get_wished_songs(self) -> Dict[str, WishEntry]:
        """Return all wished songs with their status."""
        return self.wishlist.get_all()

    def get_recently_learned(self) -> List[str]:
        """Return and clear the recently-learned notification list."""
        return self.wishlist.get_recently_learned()
    
    # ————获取唱段歌词和音频数据————

    def get_segment_lyrics(self, song_name: str, segment_description: str) -> str:
        lyrics, _ = self.get_song_segment(song_name, segment_description, require_audio=False)
        if not lyrics:
            return ""
        # 拼接歌词内容
        lyrics_content = "\n".join([line.content for line in lyrics])
        return lyrics_content

    def get_full_lyrics(self, song_name: str) -> str:
        """获取整首歌歌词。

        优先使用歌曲 JSON 中所有唱段的歌词，避免依赖 LRC 解析；如果唱段歌词不存在，
        则回退读取 lrc 文件并去掉时间戳。
        """
        song_metadata = self.get_song_metadata(song_name)
        if not song_metadata:
            self.logger.warning(f"Song not found: {song_name}")
            return ""

        segment_lines: List[str] = []
        for segment in song_metadata.segments or []:
            for line in self._normalize_lyric_lines(segment.lyrics):
                content = line.content.strip()
                if content:
                    segment_lines.append(content)
        if segment_lines:
            return "\n".join(self._dedupe_adjacent_lines(segment_lines))

        return self._read_lrc_lyrics(song_metadata.lrc_path)

    def get_song_segment(self, song_name: str, segment_description: str, require_audio: bool = True) -> Tuple[List[OneLyricLine], bytes | None]:
        """
        根据歌曲名称和唱段描述，获取对应唱段的歌词对象列表，并返回音频数据的base64编码
        """
        if not song_name or not segment_description:
            return None, None

        safe_song_name = SingingManager.get_unified_song_name(song_name)
        song_metadata = self.get_song_metadata(safe_song_name)

        if not song_metadata:
            self.logger.warning(f"Song not found: {song_name}")
            return None, None

        target_segment = None
        for seg in song_metadata.segments:
            if seg.description == segment_description:
                target_segment = seg
                break

        if not target_segment:
            self.logger.warning(f"Segment '{segment_description}' not found in song '{song_name}'")
            return None, None


        # 转换 lyrics (如果是 dict 则转换为 OneLyricLine)
        real_lyrics = []
        if target_segment.lyrics:
            real_lyrics = self._normalize_lyric_lines(target_segment.lyrics)

        if not require_audio:
            return real_lyrics, None

        # 处理音频
        try:
            from pydub import AudioSegment
        except ImportError:
            self.logger.error("pydub module not found. Please install it using 'pip install pydub'.")
            return None, None

        audio_path = song_metadata.song_path
        if not os.path.exists(audio_path):
            self.logger.error(f"Audio file does not exist: {audio_path}")
            return None, None

        try:
            # 加载并切片
            audio: AudioSegment = AudioSegment.from_file(audio_path)

            # 时间单位转换 (秒 -> 毫秒)
            start_ms = int(target_segment.start_time * 1000)
            end_ms = int(target_segment.end_time * 1000)

            segment_audio = audio[start_ms:end_ms]

            # 调整音量至目标 dBFS
            target_dbfs = -26.48
            change_in_dbfs = target_dbfs - segment_audio.dBFS
            segment_audio = segment_audio.apply_gain(change_in_dbfs)

            # 导出为 WAV 格式的 bytes
            wav_io = io.BytesIO()
            segment_audio.export(wav_io, format="wav")
            wav_bytes = wav_io.getvalue()


            return real_lyrics, wav_bytes

        except Exception as e:
            self.logger.error(f"Failed to process audio for {song_name}: {e}\n{traceback.format_exc()}")
            return None, None
        
    def get_song_metadata(self, song_name: str) -> SongMetadata | None:
        if not song_name:
            return None
        safe_song_name = SingingManager.get_unified_song_name(song_name)
        song_metadata = self.all_songs.get(safe_song_name)
        if song_metadata is not None:
            return song_metadata
        canonical_key = self.song_aliases.get(safe_song_name)
        if canonical_key:
            return self.all_songs.get(canonical_key, None)
        return None

    @staticmethod
    def _normalize_lyric_lines(raw_lines: Any) -> List[OneLyricLine]:
        real_lyrics: List[OneLyricLine] = []
        if not raw_lines:
            return real_lyrics
        for item in raw_lines:
            if isinstance(item, dict):
                real_lyrics.append(
                    OneLyricLine(
                        duration=float(item.get("duration", 0.0)),
                        content=str(item.get("content", "")),
                    )
                )
            elif isinstance(item, OneLyricLine):
                real_lyrics.append(item)
            elif isinstance(item, str):
                real_lyrics.append(OneLyricLine(duration=0.0, content=item))
        return real_lyrics

    @staticmethod
    def _dedupe_adjacent_lines(lines: List[str]) -> List[str]:
        deduped: List[str] = []
        for line in lines:
            if not deduped or deduped[-1] != line:
                deduped.append(line)
        return deduped

    def _read_lrc_lyrics(self, lrc_path: str) -> str:
        path = pathlib.Path(lrc_path)
        if not path.exists():
            return ""
        lines: List[str] = []
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = re.sub(r"\[[^\]]*\]", "", raw_line).strip()
                if line:
                    lines.append(line)
        except Exception as exc:
            self.logger.warning(f"Failed to read lrc lyrics for {lrc_path}: {exc}")
            return ""
        return "\n".join(self._dedupe_adjacent_lines(lines))

