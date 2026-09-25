import io
import json
import os
import pathlib
import random
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

from src.domain.music_type import OneLyricLine, SongMetadata, SongSegment, WishEntry
from src.domain.tool_type import MyTool
from src.utils.helpers import get_unified_song_name
from src.utils.logger import get_logger

from .wishlist import WishlistManager


class SingingManager:
    def __init__(self, config: Dict[str, Any]):
        self.logger = get_logger(__name__)
        self.config = config
        self.character_name = config.get("character_name", "洛天依")
        self.resource_path = config.get("resource_path")
        if not self.resource_path:
            raise ValueError("SingingManager requires skills.singing.characters.<character_id>.resource_path")
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
            if not song_dir.is_dir():
                continue
            try:
                loaded = self._load_song(song_dir, song)
            except Exception as e:
                self.logger.error(f"Failed to load song {song} config: {e}\n{traceback.format_exc()}")
                continue
            if loaded is None:
                continue
            metadata, aliases = loaded
            canonical = self.get_unified_song_name(metadata.title)
            self.all_songs[canonical] = metadata
            self._index_song_aliases(canonical_key=canonical, aliases=aliases)
        self.logger.info(f"Loaded {len(self.all_songs)} songs into music manager.")

    def _load_song(self, song_dir: pathlib.Path, song: str) -> tuple[SongMetadata, list[str]] | None:
        """校验并读取一首歌的歌词、音频和元数据文件。"""
        lyrics_file = song_dir / f"{song}.lrc"
        audio_file = song_dir / f"{song}.cleaned.mp3"
        config_file = song_dir / f"{song}.json"
        if not lyrics_file.exists():
            self.logger.warning(f"Lyrics file missing for song {song}")
            return None
        if not audio_file.exists():
            audio_file = song_dir / f"{song}.mp3"
            if not audio_file.exists():
                self.logger.warning(f"Old audio file also missing for song {song}")
                return None
        if not config_file.exists():
            self.logger.warning(f"Config file missing for song {song}")
            return None
        song_config = json.loads(config_file.read_text(encoding="utf-8"))
        title = song_config.get("title", song)
        emotion_tags = song_config.get("emotion_tags", [])
        if isinstance(emotion_tags, str):
            emotion_tags = [emotion_tags]
        if not isinstance(emotion_tags, list):
            emotion_tags = []
        segments = [
            SongSegment(
                description=item.get("description", ""),
                start_time=item.get("start_time", 0),
                end_time=item.get("end_time", 0),
                lyrics=item.get("lyrics", ""),
            )
            for item in song_config.get("segments", [])
        ]
        metadata = SongMetadata(
            song_name=song,
            title=title,
            description=song_config.get("description", ""),
            song_path=str(audio_file),
            lrc_path=str(lyrics_file),
            lrc_offset=song_config.get("lrc_offset", 0),
            segments=segments,
            emotion_tags=[str(tag).strip() for tag in emotion_tags if str(tag).strip()],
        )
        return metadata, [title, song, config_file.stem]

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
        self.logger.info(f"Reloaded songs: {old_count} → {len(self.all_songs)}")

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
        available = [segment for segment in segments if (correct_song_name, segment) not in excluded]
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
            tagged_candidates = [item for item in candidates if target_tags.intersection(item[1].emotion_tags)]
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

    def get_song_segment(
        self, song_name: str, segment_description: str, require_audio: bool = True
    ) -> Tuple[List[OneLyricLine], bytes | None]:
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

        target_segment = self._find_segment(song_metadata, segment_description)
        if not target_segment:
            self.logger.warning(f"Segment '{segment_description}' not found in song '{song_name}'")
            return None, None

        real_lyrics = self._normalize_lyric_lines(target_segment.lyrics) if target_segment.lyrics else []
        if not require_audio:
            return real_lyrics, None

        audio = self._render_segment_audio(song_metadata, target_segment)
        if audio is None:
            return None, None
        return real_lyrics, audio

    @staticmethod
    def _find_segment(song_metadata: SongMetadata, description: str) -> SongSegment | None:
        return next(
            (segment for segment in song_metadata.segments if segment.description == description),
            None,
        )

    def _render_segment_audio(
        self,
        song_metadata: SongMetadata,
        target_segment: SongSegment,
    ) -> bytes | None:
        """Load, normalize, and encode one configured song segment."""

        try:
            from pydub import AudioSegment
        except ImportError:
            self.logger.error("pydub module not found. Please install it using 'pip install pydub'.")
            return None

        audio_path = song_metadata.song_path
        if not os.path.exists(audio_path):
            self.logger.error(f"Audio file does not exist: {audio_path}")
            return None

        try:
            audio: AudioSegment = AudioSegment.from_file(audio_path)
            start_ms = int(target_segment.start_time * 1000)
            end_ms = int(target_segment.end_time * 1000)
            segment_audio = audio[start_ms:end_ms]
            target_dbfs = -26.48
            change_in_dbfs = target_dbfs - segment_audio.dBFS
            segment_audio = segment_audio.apply_gain(change_in_dbfs)
            wav_io = io.BytesIO()
            segment_audio.export(wav_io, format="wav")
            return wav_io.getvalue()
        except Exception as e:
            self.logger.error(f"Failed to process audio for {song_metadata.song_name}: {e}\n{traceback.format_exc()}")
            return None

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
