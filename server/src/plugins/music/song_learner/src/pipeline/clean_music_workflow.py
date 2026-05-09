#!/usr/bin/env python
# coding: utf-8

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

CURRENT_DIR = Path(__file__).resolve().parent
SRC_DIR = CURRENT_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from msst_core.inference import proc_folder
try:
    from .download_qq_song import download_song_and_lyric
except ImportError:
    from pipeline.download_qq_song import download_song_and_lyric


DEFAULT_STAGE1_MODEL_TYPE = "bs_roformer"
DEFAULT_STAGE1_CONFIG = "res/song_learner/msst/configs/model_bs_roformer_ep_317_sdr_12.9755.yaml"
DEFAULT_STAGE1_CKPT = "res/song_learner/msst/pretrain/model_bs_roformer_ep_317_sdr_12.9755.ckpt"

DEFAULT_STAGE2_MODEL_TYPE = "mel_band_roformer"
DEFAULT_STAGE2_CONFIG = "res/song_learner/msst/configs/model_mel_band_roformer_denoise.yaml"
DEFAULT_STAGE2_CKPT = "res/song_learner/msst/pretrain/dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt"

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="单文件音乐清洗工作流：可直接清洗本地音频，或按歌名下载 QQ 音乐后清洗。"
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--input_file", type=str, help="本地输入音频文件路径（mp3/wav/flac）。")
    source_group.add_argument("--song_name", type=str, help="歌曲名。会先尝试从 QQ 音乐下载 mp3 + 歌词。")

    parser.add_argument("--output_dir", type=str, default="res/music/songs", help="输出目录。")
    parser.add_argument("--ffmpeg_bin", type=str, default="ffmpeg", help="ffmpeg 可执行文件路径。")
    parser.add_argument("--max_mp3_size_mb", type=float, default=8.0, help="目标 mp3 最大大小（MB）。")
    parser.add_argument("--keep_intermediate", action="store_true", help="保留中间文件目录。")

    parser.add_argument("--stage1_model_type", type=str, default=DEFAULT_STAGE1_MODEL_TYPE)
    parser.add_argument("--stage1_config", type=str, default=DEFAULT_STAGE1_CONFIG)
    parser.add_argument("--stage1_ckpt", type=str, default=DEFAULT_STAGE1_CKPT)

    parser.add_argument("--stage2_model_type", type=str, default=DEFAULT_STAGE2_MODEL_TYPE)
    parser.add_argument("--stage2_config", type=str, default=DEFAULT_STAGE2_CONFIG)
    parser.add_argument("--stage2_ckpt", type=str, default=DEFAULT_STAGE2_CKPT)

    return parser.parse_args()


def safe_name(name: str) -> str:
    bad_chars = '<>:"/\\|?*\n\r\t'
    cleaned = "".join("_" if c in bad_chars else c for c in name).strip(" .")
    return cleaned or f"song_{int(time.time())}"


def run_cmd(cmd: list[str], cwd: Path) -> None:
    print("[RUN]", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(cwd), check=False)
    if result.returncode != 0:
        raise RuntimeError(f"命令执行失败，退出码={result.returncode}: {' '.join(cmd)}")


def find_audio_file(folder: Path, preferred_names: Optional[list[str]] = None) -> Path:
    if preferred_names:
        for name in preferred_names:
            candidate = folder / name
            if candidate.exists() and candidate.is_file():
                return candidate

    all_audio = []
    for ext in ("*.wav", "*.flac", "*.mp3"):
        all_audio.extend(folder.rglob(ext))

    if not all_audio:
        raise FileNotFoundError(f"在目录中未找到音频文件: {folder}")

    return sorted(all_audio)[0]


def encode_mp3_under_size(
    ffmpeg_bin: str,
    input_wav: Path,
    output_mp3: Path,
    max_size_mb: float,
) -> None:
    bitrates = ["192k", "160k", "128k", "112k", "96k", "80k", "64k"]
    encoders = ["libmp3lame", "mp3"]
    max_size_bytes = int(max_size_mb * 1024 * 1024)

    output_mp3.parent.mkdir(parents=True, exist_ok=True)

    for bitrate in bitrates:
        encoded = False
        for encoder in encoders:
            cmd = [
                ffmpeg_bin,
                "-y",
                "-i",
                str(input_wav),
                "-vn",
                "-codec:a",
                encoder,
                "-b:a",
                bitrate,
                str(output_mp3),
            ]
            try:
                run_cmd(cmd, cwd=Path.cwd())
            except RuntimeError as exc:
                print(f"[WARN] 编码器 {encoder} 不可用，尝试下一个。原因: {exc}")
                continue

            encoded = True
            size = output_mp3.stat().st_size
            print(
                f"[INFO] 已编码 {bitrate} ({encoder})，文件大小 {size / 1024 / 1024:.2f} MB"
            )
            if size <= max_size_bytes:
                return
            break

        if not encoded:
            continue

    for encoder in encoders:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(input_wav),
            "-vn",
            "-codec:a",
            encoder,
            "-q:a",
            "9",
            str(output_mp3),
        ]
        try:
            run_cmd(cmd, cwd=Path.cwd())
        except RuntimeError as exc:
            print(f"[WARN] 编码器 {encoder} 不可用，尝试下一个。原因: {exc}")
            continue

        size = output_mp3.stat().st_size
        print(f"[INFO] 已使用极限压缩 ({encoder})，文件大小 {size / 1024 / 1024:.2f} MB")
        return

    raise RuntimeError(
        "无法使用当前 ffmpeg 进行 MP3 编码。请安装支持 MP3 编码的 ffmpeg，"
        "或传入 --ffmpeg_bin 指向可用版本。"
    )


def encode_mp3_128k(
    ffmpeg_bin: str,
    input_audio: Path,
    output_mp3: Path,
) -> None:
    encoders = ["libmp3lame", "mp3"]
    output_mp3.parent.mkdir(parents=True, exist_ok=True)

    for encoder in encoders:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(input_audio),
            "-vn",
            "-codec:a",
            encoder,
            "-b:a",
            "128k",
            str(output_mp3),
        ]
        try:
            run_cmd(cmd, cwd=Path.cwd())
            return
        except RuntimeError as exc:
            print(f"[WARN] 编码器 {encoder} 不可用，尝试下一个。原因: {exc}")

    raise RuntimeError(
        "无法使用当前 ffmpeg 进行 MP3 编码。请安装支持 MP3 编码的 ffmpeg，"
        "或传入 --ffmpeg_bin 指向可用版本。"
    )


def run_clean_pipeline(
    project_root: Path,
    input_file: Path,
    output_dir: Path,
    ffmpeg_bin: str,
    max_mp3_size_mb: float,
    stage1_model_type: str,
    stage1_config: str,
    stage1_ckpt: str,
    stage2_model_type: str,
    stage2_config: str,
    stage2_ckpt: str,
    final_stem_name: str,
    keep_intermediate: bool,
) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="music_clean_", dir=str(output_dir)) as temp_dir:
        temp_root = Path(temp_dir)

        step1_input = temp_root / "step1_input"
        step1_output = temp_root / "step1_output"
        step2_input = temp_root / "step2_input"
        step2_output = temp_root / "step2_output"

        step1_input.mkdir(parents=True, exist_ok=True)
        step2_input.mkdir(parents=True, exist_ok=True)

        local_input = step1_input / input_file.name
        shutil.copy2(input_file, local_input)

        proc_folder(
            {
                "model_type": stage1_model_type,
                "config_path": stage1_config,
                "start_check_point": stage1_ckpt,
                "input_folder": str(step1_input),
                "store_dir": str(step1_output),
                "filename_template": "{instr}",
                "extract_instrumental": True,
            }
        )

        vocals_file = find_audio_file(step1_output, preferred_names=["vocals.wav", "vocals.flac"])
        instrumental_file = find_audio_file(
            step1_output,
            preferred_names=["instrumental.wav", "instrumental.flac", "instrumental.mp3"],
        )
        shutil.copy2(vocals_file, step2_input / "vocals.wav")

        proc_folder(
            {
                "model_type": stage2_model_type,
                "config_path": stage2_config,
                "start_check_point": stage2_ckpt,
                "input_folder": str(step2_input),
                "store_dir": str(step2_output),
                "filename_template": "{instr}",
            }
        )

        dry_file = find_audio_file(step2_output, preferred_names=["dry.wav", "dry.flac"])
        final_mp3 = output_dir / f"{safe_name(final_stem_name)}.cleaned.mp3"
        final_inst_mp3 = output_dir / f"{safe_name(final_stem_name)}.inst.mp3"
        # encode_mp3_under_size(ffmpeg_bin, dry_file, final_mp3, max_mp3_size_mb)
        encode_mp3_128k(ffmpeg_bin, dry_file, final_mp3)
        encode_mp3_128k(ffmpeg_bin, instrumental_file, final_inst_mp3)

        if keep_intermediate:
            saved = output_dir / f"intermediate_{int(time.time())}"
            if saved.exists():
                shutil.rmtree(saved)
            shutil.copytree(temp_root, saved)
            print(f"[INFO] 已保存中间文件: {saved}")

        return final_mp3, final_inst_mp3


def ensure_file_exists(path: Path, desc: str) -> None:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{desc}不存在: {path}")


def clean_audio_file(
    project_root: Path,
    input_file: Path,
    output_dir: Path,
    final_stem_name: str,
    ffmpeg_bin: str = "ffmpeg",
    max_mp3_size_mb: float = 8.0,
    stage1_model_type: str = DEFAULT_STAGE1_MODEL_TYPE,
    stage1_config: str = DEFAULT_STAGE1_CONFIG,
    stage1_ckpt: str = DEFAULT_STAGE1_CKPT,
    stage2_model_type: str = DEFAULT_STAGE2_MODEL_TYPE,
    stage2_config: str = DEFAULT_STAGE2_CONFIG,
    stage2_ckpt: str = DEFAULT_STAGE2_CKPT,
    keep_intermediate: bool = False,
) -> Tuple[Path, Path]:
    project_root = Path(project_root).expanduser().resolve()
    input_file = Path(input_file).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()

    ensure_file_exists(input_file, "输入音频")

    stage1_config_path = (project_root / stage1_config).resolve()
    stage1_ckpt_path = (project_root / stage1_ckpt).resolve()
    stage2_config_path = (project_root / stage2_config).resolve()
    stage2_ckpt_path = (project_root / stage2_ckpt).resolve()

    ensure_file_exists(stage1_config_path, "第一阶段配置")
    ensure_file_exists(stage1_ckpt_path, "第一阶段权重")
    ensure_file_exists(stage2_config_path, "第二阶段配置")
    ensure_file_exists(stage2_ckpt_path, "第二阶段权重")

    return run_clean_pipeline(
        project_root=project_root,
        input_file=input_file,
        output_dir=output_dir,
        ffmpeg_bin=ffmpeg_bin,
        max_mp3_size_mb=max_mp3_size_mb,
        stage1_model_type=stage1_model_type,
        stage1_config=str(stage1_config_path),
        stage1_ckpt=str(stage1_ckpt_path),
        stage2_model_type=stage2_model_type,
        stage2_config=str(stage2_config_path),
        stage2_ckpt=str(stage2_ckpt_path),
        final_stem_name=final_stem_name,
        keep_intermediate=keep_intermediate,
    )
