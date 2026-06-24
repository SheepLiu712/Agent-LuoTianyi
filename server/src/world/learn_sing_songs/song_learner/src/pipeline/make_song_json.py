#!/usr/bin/env python
# coding: utf-8

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

TIMESTAMP_LINE_RE = re.compile(r"^\[(\d{1,2}:\d{1,2}(?:\.\d{1,6})?)\](.*)$")
OFFSET_LINE_RE = re.compile(r"^\[offset:([^\]]+)\]$", re.IGNORECASE)
SPEAKER_LINE_RE = re.compile(r"^([^:：]+)\s*[：:]\s*(.+)$")


@dataclass
class TimedLine:
    index: int
    time_seconds: float
    text: str


@dataclass
class MatchedLyric:
    all_index: int
    time_seconds: float
    next_time_seconds: float
    content: str


def read_text_auto(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "cp936"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="结合 <歌名>.llm.lrc 与原始 lrc，生成 <歌名>.json"
    )
    parser.add_argument(
        "--song_dir",
        required=True,
        help="歌曲目录，目录中应包含 <歌名>.lrc 与 <歌名>.llm.lrc",
    )
    return parser.parse_args()


def ensure_exists(path: Path, desc: str) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{desc}不存在: {path}")


def mmss_to_seconds(value: str) -> float:
    minute_str, sec_str = value.split(":", 1)
    return int(minute_str) * 60 + float(sec_str)


def try_parse_number(value: str):
    value = value.strip()
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def should_skip_speaker_credit(text: str) -> bool:
    match = SPEAKER_LINE_RE.match(text.strip())
    if not match:
        return False
    speaker = match.group(1)
    return any(char in speaker for char in ("词", "曲", "调", "混"))


def parse_original_lrc(lrc_path: Path):
    raw_lines = read_text_auto(lrc_path).splitlines()

    lrc_offset = 0
    all_timed_lines: List[TimedLine] = []

    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue

        offset_match = OFFSET_LINE_RE.match(line)
        if offset_match:
            lrc_offset = try_parse_number(offset_match.group(1))
            continue

        ts_match = TIMESTAMP_LINE_RE.match(line)
        if not ts_match:
            continue

        ts_raw = ts_match.group(1)
        text = ts_match.group(2).strip()
        all_timed_lines.append(
            TimedLine(
                index=len(all_timed_lines),
                time_seconds=mmss_to_seconds(ts_raw),
                text=text,
            )
        )

    if not all_timed_lines:
        raise ValueError(f"未在原始lrc中解析到时间戳行: {lrc_path}")

    # 可用于和 llm 分段歌词对齐的候选行：必须是非空、非词曲调混署名。
    lyric_candidates: List[TimedLine] = []
    for item in all_timed_lines:
        if not item.text:
            continue
        if should_skip_speaker_credit(item.text):
            continue
        lyric_candidates.append(item)

    if not lyric_candidates:
        raise ValueError(f"原始lrc中没有可用歌词行: {lrc_path}")

    return lrc_offset, all_timed_lines, lyric_candidates


def parse_llm_segments(llm_path: Path) -> List[List[str]]:
    segments: List[List[str]] = []
    current: List[str] = []

    for raw in read_text_auto(llm_path).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "---":
            if current:
                segments.append(current)
                current = []
            continue
        current.append(line)

    if current:
        segments.append(current)

    if not segments:
        raise ValueError(f"llm歌词分段为空: {llm_path}")

    return segments


def find_next_match(candidates: List[TimedLine], text: str, start_idx: int) -> int:
    for idx in range(start_idx, len(candidates)):
        if candidates[idx].text.strip().replace(" ", "") == text.strip().replace(" ", "").replace(" ", ""):
            return idx
    return -1


def round2(value: float) -> float:
    return round(value + 1e-8, 2)


def build_segment_json(
    song_name: str,
    lrc_offset,
    all_timed_lines: List[TimedLine],
    candidates: List[TimedLine],
    llm_segments: List[List[str]],
):
    all_times = [item.time_seconds for item in all_timed_lines]

    cursor = 0
    out_segments = []

    for seg_idx, seg_lines in enumerate(llm_segments, start=1):
        matched: List[MatchedLyric] = []

        for line in seg_lines:
            pos = find_next_match(candidates, line, cursor)
            if pos < 0:
                raise ValueError(
                    f"在原始lrc中未找到llm歌词（从第{cursor + 1}候选行开始搜索）: {line}"
                )

            candidate = candidates[pos]
            all_index = candidate.index
            next_time = (
                all_times[all_index + 1]
                if all_index + 1 < len(all_times)
                else all_times[all_index]
            )
            matched.append(
                MatchedLyric(
                    all_index=all_index,
                    time_seconds=candidate.time_seconds,
                    next_time_seconds=next_time,
                    content=candidate.text,
                )
            )
            cursor = pos + 1

        if not matched:
            continue

        lyric_objects = []
        for item in matched:
            content = item.content.strip()
            if not content:
                continue
            duration = max(0.0, item.next_time_seconds - item.time_seconds)
            lyric_objects.append(
                {
                    "duration": round2(duration),
                    "content": content,
                }
            )

        if not lyric_objects:
            continue

        out_segments.append(
            {
                "description": f"段落{seg_idx}",
                "start_time": round2(matched[0].time_seconds),
                "end_time": round2(matched[-1].next_time_seconds),
                "lyrics": lyric_objects,
            }
        )

    return {
        "title": song_name,
        "lrc_offset": lrc_offset,
        "segments": out_segments,
    }


def generate_song_json(song_dir: Path) -> Path:
    song_dir = Path(song_dir).expanduser().resolve()
    if not song_dir.exists() or not song_dir.is_dir():
        raise NotADirectoryError(f"歌曲目录不存在或不是目录: {song_dir}")

    song_name = song_dir.name
    lrc_path = song_dir / f"{song_name}.lrc"
    llm_lrc_path = song_dir / f"{song_name}.llm.lrc"
    out_json_path = song_dir / f"{song_name}.json"

    ensure_exists(lrc_path, "原始lrc")
    ensure_exists(llm_lrc_path, "llm分段歌词")

    lrc_offset, all_timed_lines, candidates = parse_original_lrc(lrc_path)
    llm_segments = parse_llm_segments(llm_lrc_path)
    for llm_segment in llm_segments:
        for line in llm_segment:
            print(line)
    payload = build_segment_json(
        song_name=song_name,
        lrc_offset=lrc_offset,
        all_timed_lines=all_timed_lines,
        candidates=candidates,
        llm_segments=llm_segments,
    )

    out_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )

    print(f"[INFO] LLM 段落数: {len(llm_segments)}")
    print(f"[INFO] 生成段落数: {len(payload['segments'])}")
    print(f"[SUCCESS] 已生成: {out_json_path}")
    return out_json_path


def main() -> None:
    args = parse_args()
    song_dir = Path(args.song_dir).expanduser().resolve()
    if not song_dir.exists() or not song_dir.is_dir():
        raise NotADirectoryError(f"歌曲目录不存在或不是目录: {song_dir}")

    generate_song_json(song_dir)


if __name__ == "__main__":
    main()
