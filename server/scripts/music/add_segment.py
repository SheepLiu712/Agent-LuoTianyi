import argparse
import sys
import pathlib
import json
from contextlib import ExitStack

server_root = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(server_root))

try:
    from src.domain.music_type import SongSegment, OneLyricLine
except ImportError:
    # Fallback/Mock for standalone testing if src not found
    from dataclasses import dataclass
    from typing import List
    @dataclass
    class OneLyricLine:
        duration: float
        content: str
    @dataclass
    class SongSegment:
        description: str
        start_time: float
        end_time: float
        lyrics: List[OneLyricLine]

work_dir = server_root / "res/sing_song/luotianyi/songs"  # 当前角色歌曲库
song_dir_name = "ILOVEU" # 歌曲文件夹的名称，不一定是歌曲标题
title = "I Love U" # 歌曲标题
description = "" # 歌曲描述，留空即可
lrc_offset = -0.5 # 歌词时间偏移，单位秒

# 这里是唱段对应的歌词文本，前面的时间戳格式为 [mm:ss.xx]，用来定义片段的起止时间和歌词的开始时间。
desired_segment = ''' 
[03:39.68]所以我决定不再掩饰着我自己
[03:43.43]所以我就在这里唱出我的旋律
[03:47.30]就算你会拒绝我也没什么关系
[03:51.18]至少你在我心里是永远的记忆
[03:55.32]希望你可以回应我的那条讯息
[03:58.88]希望你可以肯定我告白的勇气
[04:02.75]期待着你会愿意走出朋友关系
[04:06.64]期待着你能决定
[04:08.63]这一分这一秒这一刻走到一起
[04:17.26]
'''
segment_description = "段落5" # 片段描述，用于保存时标识片段

song_dir_path = pathlib.Path(work_dir) / song_dir_name

json_config_path = song_dir_path / f"{song_dir_name}.json"

if not json_config_path.exists():
    print(f"配置文件不存在：{json_config_path}")
    config = {
        "title": title,
        "description": description,
        "lrc_offset": lrc_offset,
        "segments": []
    }
    # create new config file
    
    with open(json_config_path, "w", encoding="utf-8") as f:
        import json
        json.dump(config, f, ensure_ascii=False, indent=4)
        print(f"已创建新配置文件：{json_config_path}")
else:
    with open(json_config_path, "r", encoding="utf-8") as f:
        import json
        config = json.load(f)
        config["title"] = title
        config["description"] = description
        config["lrc_offset"] = lrc_offset

song_path = song_dir_path / f"{song_dir_name}.mp3"

import re

def parse_time_str(time_str):
    """解析 [mm:ss.xx] 为秒数 (float)"""
    match = re.match(r"\[(\d{2}):(\d{2}\.\d{2})\]", time_str)
    if match:
        minutes = int(match.group(1))
        seconds = float(match.group(2))
        return minutes * 60 + seconds
    return 0.0

def process_segment_text(text: str):
    """解析文本，返回 (start_time, end_time, lyric_lines)"""
    lines = text.strip().split('\n')
    parsed_lines = []
    
    # 1. Extract (timestamp_str, content, seconds) for each line
    for line in lines:
        line = line.strip()
        if not line: continue
        match = re.match(r"(\[\d{2}:\d{2}\.\d{2}\])(.*)", line)
        if match:
            time_str = match.group(1)
            content = match.group(2).strip()
            seconds = parse_time_str(time_str)
            parsed_lines.append({"time": seconds, "content": content, "raw": line})
            
    if len(parsed_lines) < 2:
        print("错误：至少需要两行时间戳（最后一行作为结束时间）")
        return None, None, None

    start_time = parsed_lines[0]["time"]
    end_time = parsed_lines[-1]["time"]
    
    lyric_objects = []
    # Loop until the second to last, because the last keyframe is just end time
    for i in range(len(parsed_lines) - 1):
        curr = parsed_lines[i]
        next_line = parsed_lines[i+1]
        
        duration = next_line["time"] - curr["time"]
        lyric_objects.append(OneLyricLine(duration=round(duration, 3), content=curr["content"]))
        
    return start_time, end_time, lyric_objects

# --- Argument Parsing & Main Logic ---
parser = argparse.ArgumentParser(description="Process music segments.")
parser.add_argument("--listen", action="store_true", help="Play the defined segment")
parser.add_argument("--save", action="store_true", help="Save the segment to config file")

if __name__ == "__main__":
    args = parser.parse_args()
    
    # Check if any action is selected, default to help or listen? Let's force selection or default to listen if no args?
    # User said: "给出--listen时... 给出--save时..."
    
    start_time, end_time, lyric_objects = process_segment_text(desired_segment)
    
    if start_time is None:
        exit(1)

    # Apply offset
    start_time += lrc_offset
    end_time += lrc_offset
        
    print(f"解析结果: {len(lyric_objects)} 行歌词")
    print(f"总时长: {start_time}s -> {end_time}s")

    if args.save:
        new_segment = SongSegment(
            description=segment_description,
            start_time=start_time,
            end_time=end_time,
            lyrics=lyric_objects
        )
        
        # Convert to dict for JSON serialization
        # SongSegment is likely not a Pydantic model but a dataclass or normal class based on previous check
        # Assuming dataclass from my mock or imports.
        # But if it is a class from src.domain, it might not have asdict.
        # Let's check if it has __dict__ or is a dataclass.
        # From previous read, it WAS a dataclass in `music_type.py` wrapper but `SongSegment` itself didn't have @dataclass decorator?
        # Wait, looked at `music_type.py`:
        # @dataclass
        # class OneLyricLine...
        # class SongSegment...  <-- MISSING @dataclass decorator in previous read!
        
        # Let's verify `music_type.py` again.
        pass

    if args.listen:
        try:
            from pydub import AudioSegment
        except ImportError:
            print("请先安装 pydub: pip install pydub")
            exit(1)
        try:
            import pyaudio
        except ImportError:
            print("请先安装 PyAudio: pip install pyaudio")
            exit(1)
            
        if not song_path.exists():
            print(f"文件不存在: {song_path}")
        else:
            print("正在加载音频文件...")
            song = AudioSegment.from_mp3(song_path)
            start_ms = int(start_time * 1000)
            end_ms = int(end_time * 1000)
            segment = song[start_ms:end_ms]
            
            print("正在播放...")
            with ExitStack() as resources:
                player = pyaudio.PyAudio()
                resources.callback(player.terminate)
                # pydub stores signed PCM; PyAudio maps width=4 to FLOAT by default.
                audio_format = (
                    pyaudio.paInt32 if segment.sample_width == 4
                    else player.get_format_from_width(segment.sample_width, unsigned=False)
                )
                stream = player.open(
                    format=audio_format,
                    channels=segment.channels,
                    rate=segment.frame_rate,
                    output=True,
                )
                # LIFO: stop, close, terminate; cleanup continues if a step fails.
                resources.callback(stream.close)
                resources.callback(stream.stop_stream)
                chunk_bytes = 1024 * segment.frame_width
                for offset in range(0, len(segment.raw_data), chunk_bytes):
                    stream.write(segment.raw_data[offset:offset + chunk_bytes])
            print("播放完毕")

    if args.save:
        # Create dict structure
        seg_dict = {
            "description": segment_description,
            "start_time": start_time,
            "end_time": end_time,
            "lyrics": [
                {"duration": l.duration, "content": l.content} for l in lyric_objects
            ]
        }
        
        # Check if already exists? (Maybe by description or start time)
        # For now, just append.
        config["segments"].append(seg_dict)
        
        with open(json_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        print(f"已保存片段 '{segment_description}' 到 {json_config_path}")


