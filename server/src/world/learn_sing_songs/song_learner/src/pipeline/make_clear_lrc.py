#!/usr/bin/env python
# coding: utf-8

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


TIMESTAMP_LINE_RE = re.compile(r"^\[(\d{1,2}:\d{1,2}(?:\.\d{1,6})?)\](.*)$")
SPEAKER_LINE_RE = re.compile(r"^([^:：]+)\s*[：:]\s*(.+)$")
HEADER_KEYWORDS = ("ti", "ar", "al", "by", "offset")


@dataclass
class LyricLine:
    time_seconds: float
    text: str


def read_text_auto(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="根据原始 lrc 与 boundary_inst.txt 生成 <歌名>.clear.lrc。"
    )
    parser.add_argument(
        "--song_dir",
        required=True,
        help="歌曲目录路径（目录中应包含 <歌名>.lrc 与 boundary_inst.txt）。",
    )
    return parser.parse_args()


def mmss_to_seconds(value: str) -> float:
    minute_str, sec_str = value.split(":", 1)
    return int(minute_str) * 60 + float(sec_str)


def should_skip_speaker_credit(text: str) -> bool:
    match = SPEAKER_LINE_RE.match(text.strip())
    if not match:
        return False
    speaker = match.group(1)
    return any(char in speaker for char in ("词", "曲", "调", "混", "和声"))


def should_skip_title_artist_line(text: str, song_name: str) -> bool:
    match = re.match(r"^(.+?)\s*-\s*(.+)$", text.strip())
    if not match:
        return False
    left = match.group(1).strip()
    return bool(song_name) and song_name in left


def parse_lrc_keep_timestamps(lrc_path: Path) -> List[LyricLine]:
    lines: List[LyricLine] = []
    song_name = lrc_path.stem.strip()
    for raw in read_text_auto(lrc_path).splitlines():
        raw = raw.strip()
        if not raw:
            continue

        match = TIMESTAMP_LINE_RE.match(raw)
        if not match:
            # 文件头如 [ti:xxx] 不匹配时间戳格式，直接忽略。
            continue

        ts_raw = match.group(1)
        text = match.group(2).strip()

        # 再保险：忽略可能伪装成时间戳的头字段。
        if any(ts_raw.lower().startswith(k) for k in HEADER_KEYWORDS):
            continue

        # if not text:
        #     continue

        if should_skip_speaker_credit(text):
            continue

        if should_skip_title_artist_line(text, song_name):
            continue

        lines.append(LyricLine(time_seconds=mmss_to_seconds(ts_raw), text=text))

    return lines


def parse_boundary_file(boundary_path: Path) -> List[float]:
    values: List[float] = []
    for raw in read_text_auto(boundary_path).splitlines():
        raw = raw.strip()
        if not raw:
            continue
        values.append(mmss_to_seconds(raw))
    return values


def find_first_ge_index(lyrics: List[LyricLine], boundary: float) -> Optional[int]:
    for idx, item in enumerate(lyrics):
        if item.time_seconds >= boundary:
            return idx
    return None


def render_clear_lrc(lyrics: List[LyricLine], boundaries: List[float]) -> List[str]:
    # 使用字典记录每个位置应该插入的标记
    # key: 行索引，value: 标记类型（"---" 表示边界，"===" 表示伴奏间隙）
    insert_positions = {}

    # 检查相邻歌词的时间差（超过10秒认为是伴奏）
    for idx in range(len(lyrics) - 1):
        current_time = lyrics[idx].time_seconds
        next_time = lyrics[idx + 1].time_seconds
        time_diff = next_time - current_time
        
        if time_diff > 10:
            # 在下一行之前插入 "===" 标记（除非该位置已有 "---" 标记）
            if idx + 1 not in insert_positions:
                insert_positions[idx + 1] = "==="
    
    # 处理 boundary 标记（优先级低）
    for boundary in boundaries:
        idx = find_first_ge_index(lyrics, boundary)
        if idx is None:
            continue
        pos = max(0, idx)
        if pos not in insert_positions:
            insert_positions[pos] = "---"
    


    rendered: List[str] = []
    for idx, item in enumerate(lyrics):
        if idx in insert_positions:
            rendered.append(insert_positions[idx])
        rendered.append(item.text)
    return rendered


def ensure_exists(path: Path, desc: str) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{desc}不存在: {path}")


def generate_clear_lrc(song_dir: Path) -> Path:
    song_dir = Path(song_dir).expanduser().resolve()
    if not song_dir.exists() or not song_dir.is_dir():
        raise NotADirectoryError(f"歌曲目录不存在或不是目录: {song_dir}")

    song_name = song_dir.name
    lrc_path = song_dir / f"{song_name}.lrc"
    boundary_path = song_dir / "boundary_inst.txt"
    out_path = song_dir / f"{song_name}.clear.lrc"

    ensure_exists(lrc_path, "原始歌词")
    ensure_exists(boundary_path, "伴奏边界文件")

    lyrics = parse_lrc_keep_timestamps(lrc_path)
    boundaries = parse_boundary_file(boundary_path)

    result_lines = render_clear_lrc(lyrics, boundaries)
    out_path.write_text("\n".join(result_lines) + "\n", encoding="utf-8")

    print(f"[INFO] 有效歌词行数: {len(lyrics)}")
    print(f"[INFO] 边界行数: {len(boundaries)}")
    print(f"[SUCCESS] 已生成: {out_path}")
    return out_path


def main() -> None:
    args = parse_args()
    song_dir = Path(args.song_dir).expanduser().resolve()
    if not song_dir.exists() or not song_dir.is_dir():
        raise NotADirectoryError(f"歌曲目录不存在或不是目录: {song_dir}")

    generate_clear_lrc(song_dir)


if __name__ == "__main__":
    main()
