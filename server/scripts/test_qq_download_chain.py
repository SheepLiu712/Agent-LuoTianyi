# coding: utf-8

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from src.world.learn_sing_songs.song_learner.src.pipeline import download_qq_song


def read_config() -> dict[str, Any]:
    config_path = SERVER_ROOT / "config" / "config.json"
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_server_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return SERVER_ROOT / path


def get_nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def credential_message(credential_file: Path) -> str:
    saved = download_qq_song.load_saved_credential(credential_file)
    if not saved:
        return f"credential 不存在或不可读取: {credential_file}"
    if not download_qq_song.QQ_SDK_AVAILABLE:
        return f"credential 文件存在，但 qqmusic-api-python 不可用: {download_qq_song.QQ_SDK_IMPORT_ERROR}"
    if not download_qq_song.validate_credential(saved):
        return f"credential 格式校验失败: {credential_file}"
    return f"credential 格式校验通过: {credential_file}"


def run(args: argparse.Namespace) -> int:
    config = read_config()
    learner_cfg = get_nested(config, "world", "auto_song_learner", default={}) or {}
    sing_cfg = get_nested(config, "capabilities", "sing", args.character_id, default={}) or {}

    credential_file = resolve_server_path(
        args.credential_file
        or learner_cfg.get("qq_credential_file")
        or "config/qq_music_credential.json"
    )
    singer_name = args.singer or sing_cfg.get("character_name") or "洛天依"
    output_root = resolve_server_path(args.output_dir) if args.output_dir else (
        SERVER_ROOT
        / "data"
        / "diagnostics"
        / "qq_download_chain"
        / time.strftime("%Y%m%d-%H%M%S")
    )

    print(f"[TEST] song={args.song}")
    print(f"[TEST] singer={singer_name}")
    print(f"[TEST] credential_file={credential_file}")
    print(f"[TEST] output_root={output_root}")
    print(f"[TEST] {credential_message(credential_file)}")

    try:
        safe_name, mp3_path, lrc_path = download_qq_song.download_song_and_lyric(
            song_name=args.song,
            singer_name=singer_name,
            output_dir=output_root,
            timeout=args.timeout,
            credential_file=credential_file,
            no_auto_login=True,
        )
    except download_qq_song.QQMusicCredentialError as exc:
        print(f"[FAIL] QQ credential 不可用: {exc}")
        return 21
    except Exception as exc:
        print(f"[FAIL] 下载链路失败: {exc.__class__.__name__}: {exc}")
        return 1

    mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
    lrc_size = lrc_path.stat().st_size if lrc_path.exists() else 0
    print(f"[PASS] 下载链路可用: {safe_name}")
    print(f"[PASS] mp3={mp3_path} ({mp3_size} bytes)")
    print(f"[PASS] lrc={lrc_path} ({lrc_size} bytes)")
    if mp3_size <= 0 or lrc_size <= 0:
        print("[FAIL] 下载文件为空")
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按当前 AutoSongLearner 配置真实测试 QQ 音乐下载链路。")
    parser.add_argument("--song", default="告死鸟", help="歌曲名，默认：告死鸟")
    parser.add_argument("--singer", default="", help="歌手名，默认读取 capabilities.sing.<character_id>.character_name")
    parser.add_argument("--character-id", default="luotianyi", help="角色 ID，默认 luotianyi")
    parser.add_argument("--credential-file", default="", help="覆盖 QQ 音乐 credential 文件路径")
    parser.add_argument("--output-dir", default="", help="覆盖测试下载输出目录")
    parser.add_argument("--timeout", type=int, default=20, help="接口超时时间，默认 20 秒")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
