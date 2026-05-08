#!/usr/bin/env python
# coding: utf-8

import argparse
from pathlib import Path
from typing import Iterable, List

import msaf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="对歌曲目录中的原始音频和伴奏音频执行 MSAF 分段，并导出 boundary 文本。"
    )
    parser.add_argument(
        "--song_dir",
        type=str,
        required=True,
        help="歌曲目录路径（目录内应包含 <歌名>.mp3 和 <歌名>.inst.mp3）。",
    )
    return parser.parse_args()


def seconds_to_mm_ss_us(seconds_value: float) -> str:
    total_microseconds = int(round(seconds_value * 1_000_000))
    if total_microseconds < 0:
        total_microseconds = 0

    total_seconds, microseconds = divmod(total_microseconds, 1_000_000)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}.{microseconds:06d}"


def format_boundaries(boundaries: Iterable[float]) -> List[str]:
    return [seconds_to_mm_ss_us(float(item)) for item in boundaries]


def run_msaf_boundaries(audio_file: Path) -> List[str]:
    boundaries, _labels = msaf.process(str(audio_file))
    return format_boundaries(boundaries)


def write_lines(lines: List[str], out_file: Path) -> None:
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_required_file(path: Path, desc: str) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{desc}不存在: {path}")


def generate_boundary_inst(song_dir: Path) -> Path:
    song_dir = Path(song_dir).expanduser().resolve()
    if not song_dir.exists() or not song_dir.is_dir():
        raise NotADirectoryError(f"歌曲目录不存在或不是目录: {song_dir}")

    song_name = song_dir.name
    inst_mp3 = song_dir / f"{song_name}.inst.mp3"
    ensure_required_file(inst_mp3, "伴奏音频")

    print(f"[INFO] 开始分段伴奏音频: {inst_mp3}")
    inst_lines = run_msaf_boundaries(inst_mp3)
    inst_out = song_dir / "boundary_inst.txt"
    write_lines(inst_lines, inst_out)
    print(f"[INFO] 已写入: {inst_out} (共 {len(inst_lines)} 行)")
    return inst_out


def main() -> None:
    args = parse_args()
    song_dir = Path(args.song_dir).expanduser().resolve()

    if not song_dir.exists() or not song_dir.is_dir():
        raise NotADirectoryError(f"歌曲目录不存在或不是目录: {song_dir}")

    generate_boundary_inst(song_dir)

    print("[SUCCESS] MSAF 分段完成")


if __name__ == "__main__":
    main()
