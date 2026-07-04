# coding: utf-8

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import requests


SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from src.world.learn_sing_songs.song_learner.src.pipeline import download_qq_song as qq_song


def singer_names(song: dict[str, Any]) -> str:
    singers = song.get("singer") or []
    names = [str(item.get("name") or "") for item in singers if isinstance(item, dict)]
    return "/".join(name for name in names if name) or "-"


def probe_audio_url(url: str, timeout: int) -> tuple[bool, str]:
    try:
        with requests.get(url, headers=qq_song.qq_headers(), stream=True, timeout=timeout) as resp:
            status = resp.status_code
            content_type = resp.headers.get("Content-Type", "-")
            if status >= 400:
                return False, f"HTTP {status}, Content-Type={content_type}"
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    return True, f"HTTP {status}, Content-Type={content_type}, first_chunk={len(chunk)} bytes"
            return False, f"HTTP {status}, Content-Type={content_type}, 但没有读到音频数据"
    except Exception as exc:
        return False, f"{exc.__class__.__name__}: {exc}"


def credential_status(credential_file: Path) -> tuple[dict[str, Any] | None, str]:
    saved = qq_song.load_saved_credential(credential_file)
    if not saved:
        return None, f"未找到可读取的 QQ 音乐 credential: {credential_file}"
    if not qq_song.QQ_SDK_AVAILABLE:
        return saved, f"credential 文件存在，但 qqmusic-api-python 不可用: {qq_song.QQ_SDK_IMPORT_ERROR}"
    if not qq_song.validate_credential(saved):
        return saved, f"credential 文件存在，但格式校验失败: {credential_file}"
    return saved, f"credential 文件格式可用: {credential_file}"


def diagnose(args: argparse.Namespace) -> int:
    credential_file = Path(args.credential_file).expanduser().resolve()
    print(f"[INFO] song={args.song!r}, singer={args.singer!r}")
    print(f"[INFO] credential_file={credential_file}")

    try:
        songs = qq_song.qq_search_songs(f"{args.song} {args.singer}", timeout=args.timeout)
    except Exception as exc:
        print(f"[FAIL] QQ 搜索接口失败: {exc.__class__.__name__}: {exc}")
        return 2

    print(f"[INFO] 搜索返回 {len(songs)} 条。前 10 条:")
    for index, song in enumerate(songs[:10], start=1):
        print(
            f"  {index:02d}. title={song.get('title')!r}, "
            f"singers={singer_names(song)}, mid={song.get('mid') or '-'}"
        )

    try:
        singer_songs = qq_song.pick_song_by_singer(songs, args.singer)
    except Exception as exc:
        print(f"[FAIL] 歌手筛选失败: {exc}")
        return 3

    ranked = qq_song.rank_songs_by_title(singer_songs, args.song)
    title_matches = [song for song in ranked if qq_song.title_matches(song, args.song)]
    print(f"[INFO] 匹配歌手 {args.singer!r} 后 {len(singer_songs)} 条；标题匹配 {len(title_matches)} 条。")
    print("[INFO] 标题排序后前 10 条:")
    for index, song in enumerate(ranked[:10], start=1):
        marker = "MATCH" if qq_song.title_matches(song, args.song) else "skip"
        print(
            f"  {index:02d}. [{marker}] title={song.get('title')!r}, "
            f"singers={singer_names(song)}, mid={song.get('mid') or '-'}"
        )

    if not title_matches:
        print("[FAIL] 搜索结果中没有标题匹配请求歌曲的候选。")
        return 4

    credential, credential_message = credential_status(credential_file)
    print(f"[INFO] {credential_message}")

    any_audio_ok = False
    any_full_ok = False
    failure_reasons: list[str] = []
    for song in title_matches:
        title = str(song.get("title") or args.song)
        songmid = str(song.get("mid") or "")
        print(f"\n[CHECK] title={title!r}, mid={songmid or '-'}")
        if not songmid:
            reason = f"{title}: 缺少 songmid"
            failure_reasons.append(reason)
            print(f"[FAIL] {reason}")
            continue

        normal_url = ""
        try:
            normal_url = qq_song.qq_fetch_mp3_url(songmid, timeout=args.timeout)
        except Exception as exc:
            failure_reasons.append(f"{title}: 普通下载 URL 接口异常: {exc}")
            print(f"[WARN] 普通下载 URL 接口异常: {exc.__class__.__name__}: {exc}")

        sdk_url = ""
        if normal_url:
            print("[OK] 普通下载接口返回 mp3 URL。")
        else:
            print("[WARN] 普通下载接口没有返回 mp3 URL，常见原因是版权、VIP 或平台限制。")
            if credential and qq_song.QQ_SDK_AVAILABLE and qq_song.validate_credential(credential):
                sdk_url = qq_song.qq_fetch_mp3_url_by_sdk(songmid, credential)
                if sdk_url:
                    print("[OK] SDK + credential 返回 mp3 URL。")
                else:
                    print("[WARN] SDK + credential 也没有返回 mp3 URL，可能是凭证已失效、账号无权限或歌曲受下载限制。")
            else:
                print("[WARN] 未尝试 SDK 下载 URL：credential 不可用或 SDK 不可用。")

        audio_url = normal_url or sdk_url
        audio_ok = False
        if audio_url:
            audio_ok, audio_message = probe_audio_url(audio_url, timeout=max(args.timeout, 20))
            print(("[OK] " if audio_ok else "[FAIL] ") + f"音频 URL 读取测试: {audio_message}")
            any_audio_ok = any_audio_ok or audio_ok
        else:
            failure_reasons.append(f"{title}: 没有拿到可下载 mp3 URL")

        lyric = ""
        try:
            lyric = qq_song.qq_fetch_lyric(songmid, timeout=args.timeout)
        except Exception as exc:
            failure_reasons.append(f"{title}: 歌词接口异常: {exc}")
            print(f"[WARN] 歌词接口异常: {exc.__class__.__name__}: {exc}")
        lyric_ok = bool(lyric.strip())
        print(("[OK] " if lyric_ok else "[FAIL] ") + f"歌词接口: {'有歌词' if lyric_ok else '未拿到歌词'}")

        if audio_ok and lyric_ok:
            any_full_ok = True
            print(f"[RESULT] 当前接口可以下载并处理候选: {title}")
        else:
            parts = []
            if not audio_ok:
                parts.append("音频不可下载")
            if not lyric_ok:
                parts.append("歌词不可用")
            failure_reasons.append(f"{title}: {', '.join(parts)}")

    print("\n[SUMMARY]")
    if any_full_ok:
        print("[PASS] 当前接口可以下载《{}》并拿到歌词。".format(args.song))
        return 0
    if any_audio_ok:
        print("[FAIL] 当前接口能读到音频，但没有同时拿到歌词，完整 SongLearner 仍会失败。")
    else:
        print("[FAIL] 当前接口不能下载《{}》的可用音频。".format(args.song))
    for reason in failure_reasons:
        print(f"  - {reason}")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="诊断 QQ 音乐歌曲下载接口是否可用。")
    parser.add_argument("--song", default="告死鸟", help="歌曲名，默认：告死鸟")
    parser.add_argument("--singer", default="洛天依", help="歌手名，默认：洛天依")
    parser.add_argument("--timeout", type=int, default=20, help="接口超时时间，默认 20 秒")
    parser.add_argument(
        "--credential-file",
        default=str(SERVER_ROOT / "config" / "qq_music_credential.json"),
        help="QQ 音乐 credential 文件，默认 server/config/qq_music_credential.json",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(diagnose(parse_args()))
