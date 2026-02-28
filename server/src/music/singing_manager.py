from ..utils.logger import get_logger
import pathlib
import os
import json
import io
import base64
import traceback
from ..types.music_type import SongSegment, SongMetadata, OneLyricLine
from ..types.tool_type import  MyTool, ToolFunction, ToolOneParameter
from typing import List, Tuple, Dict, Any


class SingingManager:
    def __init__(self, config):
        self.logger = get_logger(__name__)
        self.config = config
        self.resource_path = config.get("resource_path", "res/music")
        self.all_songs: dict[str, SongMetadata] = {}
        self.tools: Dict[str, MyTool] = {}
        self.get_music_data()
        self.init_llm_tools()

    def get_music_data(self):
        self.logger.info(f"Loading music data from {self.resource_path}")
        music_lib = pathlib.Path(self.resource_path) / "songs"
        if not music_lib.exists():
            self.logger.warning(f"Music library path does not exist: {music_lib}")
            return

        for song in os.listdir(music_lib):
            song_dir = music_lib / song
            if not song_dir.is_dir():  # 安全名字即歌夹名称
                continue
            # 一首歌的文件包括：歌词文件 .lrc，音频文件 .mp3 或 .wav 以及配置文件 .json
            lyrics_file = song_dir / f"{song}.lrc"
            audio_file_wav = song_dir / f"{song}.mp3"
            config_file = song_dir / f"{song}.json"
            if not lyrics_file.exists():
                self.logger.warning(f"Lyrics file missing for song {song}")
                continue
            if not audio_file_wav.exists():
                self.logger.warning(f"Audio file missing for song {song}")
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
                    title=title,
                    description=description,
                    song_path=str(audio_file_wav),
                    lrc_path=str(lyrics_file),
                    lrc_offset=lrc_offset,
                    segments=segment_objs,
                )
                self.all_songs[song] = song_metadata

            except Exception as e:
                import traceback

                self.logger.error(f"Failed to load song {song} config: {e}\n{traceback.format_exc()}")
        self.logger.info(f"Loaded {len(self.all_songs)} songs into music manager.")

    def get_song_metadata(self, song_name: str) -> SongMetadata | None:
        if not song_name:
            return None
        return self.all_songs.get(song_name, None)

    def can_i_sing_song(self, song_name: str) -> List[str]:
        """
        检查是否可以演唱指定歌曲，如果可以，返回能够唱的唱段列表，否则返回空列表
        """
        if not song_name:
            return []
        safe_song_name = song_name.strip("").strip("《》")
        if not safe_song_name in self.all_songs:
            return []
        song_metadata: SongMetadata = self.all_songs[safe_song_name]
        return [segment.description for segment in song_metadata.segments]

    def get_songs_can_sing(self, max_song_num: int = 5) -> Dict[str, Any]:
        song_and_desc = {}
        # shuffle and get max_song_num songs
        import random
        selected_songs = random.sample(list(self.all_songs.items()), min(max_song_num, len(self.all_songs)))
        for song_name, metadata in selected_songs:
            song_and_desc[song_name] = metadata.description

        # to json string
        return song_and_desc
    
    async def get_songs_can_sing_llm(self, max_song_num: int = 5) -> str:
        song_and_desc = self.get_songs_can_sing(max_song_num)
        return json.dumps(song_and_desc, ensure_ascii=False)
    
    async def can_i_sing_song_llm(self, song_name: str) -> str:
        if not song_name:
            return "没有指定歌曲名称。"
        segments = self.can_i_sing_song(song_name)
        if not segments:
            return f"洛天依目前无法演唱{song_name}。"
        return f"洛天依可以演唱{song_name}，可以唱的唱段有：{', '.join(segments)}。"
    
    def get_segment_lyrics(self, song_name: str, segment_description: str) -> str:
        lyrics, _ = self.get_song_segment(song_name, segment_description, require_audio=False)
        if not lyrics:
            return ""
        # 拼接歌词内容
        lyrics_content = " ".join([line.content for line in lyrics])
        return lyrics_content

    def get_song_segment(self, song_name: str, segment_description: str, require_audio: bool = True) -> Tuple[List[OneLyricLine], str]:
        """
        根据歌曲名称和唱段描述，获取对应唱段的歌词对象列表，并返回音频数据的base64编码
        """
        if not song_name or not segment_description:
            return None, None

        # 移除书名号等干扰字符
        safe_song_name = song_name.strip().strip("《》")
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
            first_elem = target_segment.lyrics[0]
            if isinstance(first_elem, dict):
                for l in target_segment.lyrics:
                    real_lyrics.append(OneLyricLine(duration=float(l.get("duration", 0.0)), content=str(l.get("content", ""))))
            elif isinstance(first_elem, OneLyricLine):
                real_lyrics = target_segment.lyrics

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

            # Base64 编码
            b64_encoded = base64.b64encode(wav_bytes).decode("utf-8")

            return real_lyrics, b64_encoded

        except Exception as e:
            self.logger.error(f"Failed to process audio for {song_name}: {e}\n{traceback.format_exc()}")
            return None, None

    def init_llm_tools(self) -> None:
        get_songs_can_sing = MyTool(
            name="get_songs_can_sing",
            description="获取现在的洛天依可以演唱的几首歌曲名称和描述。",
            tool_func=self.get_songs_can_sing_llm,
            tool_interface= ToolFunction(
                name="get_songs_can_sing",
                description="获取现在的洛天依可以演唱的几首歌曲名称和描述。",
                parameters=[
                    ToolOneParameter(
                        name="max_song_num",
                        type="int",
                        description="最多返回的歌曲数量",
                    ),
                ],
            ),
        )

        can_i_sing_tool = MyTool(
            name="can_i_sing_song",
            description="检查洛天依是否可以演唱指定的歌曲，如果可以，返回能够唱的唱段列表，否则返回空列表。",
            tool_func=self.can_i_sing_song_llm,
            tool_interface=ToolFunction(
                name="can_i_sing_song",
                description="检查洛天依是否可以演唱指定的歌曲，如果可以，返回能够唱的唱段列表，否则返回空列表。",
                parameters=[
                    ToolOneParameter(
                        name="song_name",
                        type="string",
                        description="歌曲名称",
                    ),
                ],
            ),
        )
        self.tools[get_songs_can_sing.name] = get_songs_can_sing
        self.tools[can_i_sing_tool.name] = can_i_sing_tool

    def get_tool_names(self) -> List[str]:
        return list(self.tools.keys())
    
    def get_tools(self) -> Dict[str, MyTool]:
        return self.tools