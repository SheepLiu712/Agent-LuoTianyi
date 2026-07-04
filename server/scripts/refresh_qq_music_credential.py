# coding: utf-8

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from src.world.learn_sing_songs.song_learner.src.pipeline import download_qq_song as qq_song


def read_config() -> dict[str, Any]:
    config_path = SERVER_ROOT / "config" / "config.json"
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] 读取 config/config.json 失败，将使用默认路径: {exc}")
        return {}


def resolve_server_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return SERVER_ROOT / path


def default_paths(config: dict[str, Any]) -> tuple[Path, Path]:
    learner_cfg = (config.get("world") or {}).get("auto_song_learner") or {}
    credential_file = resolve_server_path(learner_cfg.get("qq_credential_file") or "config/qq_music_credential.json")
    resource_dir = resolve_server_path(learner_cfg.get("songlearner_resource_dir") or "res/song_learner")
    legacy_file = resource_dir / ".qq_music_credential.json"
    return credential_file, legacy_file


def sync_legacy_credential(credential_file: Path, legacy_file: Path) -> None:
    if credential_file.resolve() == legacy_file.resolve():
        return
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(credential_file, legacy_file)
    print(f"[INFO] 已同步兼容路径 credential: {legacy_file}")


def validate_saved_credential(credential_file: Path) -> bool:
    saved = qq_song.load_saved_credential(credential_file)
    if not saved:
        print(f"[FAIL] 登录后未能读取 credential: {credential_file}")
        return False
    if not qq_song.validate_credential(saved):
        print(f"[FAIL] credential 文件写入了，但格式校验失败: {credential_file}")
        return False
    print(f"[OK] credential 已写入并通过格式校验: {credential_file}")
    return True


def probe_song_with_credential(song_name: str, credential_file: Path, timeout: int) -> None:
    saved = qq_song.load_saved_credential(credential_file)
    if not saved or not qq_song.validate_credential(saved):
        print("[WARN] 跳过探测：credential 不可用。")
        return
    try:
        songs = qq_song.qq_search_songs(f"{song_name} 洛天依", timeout=timeout)
        singer_songs = qq_song.rank_songs_by_title(qq_song.pick_song_by_singer(songs, "洛天依"), song_name)
        matches = [song for song in singer_songs if qq_song.title_matches(song, song_name)]
    except Exception as exc:
        print(f"[WARN] 探测歌曲搜索失败: {exc}")
        return
    if not matches:
        print(f"[WARN] 探测歌曲没有标题匹配候选: {song_name}")
        return
    song = matches[0]
    songmid = str(song.get("mid") or "")
    if not songmid:
        print(f"[WARN] 探测歌曲缺少 songmid: {song.get('title')!r}")
        return
    url = qq_song.qq_fetch_mp3_url_by_sdk(songmid, saved)
    if url:
        print(f"[OK] credential SDK 探测成功，{song.get('title')!r} 可拿到 mp3 URL。")
    else:
        print(f"[WARN] credential 格式有效，但探测歌曲 {song.get('title')!r} 仍未拿到 mp3 URL。")


def refresh_credential(args: argparse.Namespace) -> int:
    if not qq_song.QQ_SDK_AVAILABLE:
        print("[FAIL] 当前环境无法导入 qqmusic-api-python，不能扫码登录。")
        print(f"[FAIL] 导入错误: {qq_song.QQ_SDK_IMPORT_ERROR}")
        return 2

    config = read_config()
    default_credential_file, default_legacy_file = default_paths(config)
    credential_file = resolve_server_path(args.credential_file) if args.credential_file else default_credential_file
    legacy_file = resolve_server_path(args.legacy_file) if args.legacy_file else default_legacy_file

    print(f"[INFO] 主 credential 路径: {credential_file}")
    if not args.no_legacy_sync:
        print(f"[INFO] 兼容 credential 路径: {legacy_file}")
    print("[INFO] 即将生成 QQ 登录二维码，请用 QQ 扫码并确认登录。")

    try:
        qq_song.ensure_qr_login(
            credential_file=credential_file,
            login_timeout=args.login_timeout,
            force_login=True,
        )
    except Exception as exc:
        print(f"[FAIL] QQ 扫码登录失败: {exc.__class__.__name__}: {exc}")
        return 3

    if not validate_saved_credential(credential_file):
        return 4

    if not args.no_legacy_sync:
        try:
            sync_legacy_credential(credential_file, legacy_file)
        except Exception as exc:
            print(f"[FAIL] 同步兼容 credential 失败: {exc.__class__.__name__}: {exc}")
            return 5

    if args.probe_song:
        probe_song_with_credential(args.probe_song, credential_file, args.timeout)

    print("[DONE] QQ 音乐 credential 已刷新。运行中的 AutoSongLearner 下次检查或下次启动子流程时会读取新文件。")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="刷新 QQ 音乐 credential：生成二维码，等待扫码，写回 credential 文件。")
    parser.add_argument("--credential-file", default="", help="主 credential 输出路径，默认读取 config.json")
    parser.add_argument("--legacy-file", default="", help="兼容 credential 输出路径，默认 songlearner_resource_dir/.qq_music_credential.json")
    parser.add_argument("--no-legacy-sync", action="store_true", help="不再同步兼容旧路径")
    parser.add_argument("--login-timeout", type=int, default=180, help="等待扫码登录秒数，默认 180")
    parser.add_argument("--timeout", type=int, default=20, help="探测接口超时秒数，默认 20")
    parser.add_argument("--probe-song", default="下等马", help="登录后用该歌曲探测 SDK URL；留空则不探测")
    return parser.parse_args()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(refresh_credential(parse_args()))
