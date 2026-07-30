#!/usr/bin/env python
# coding: utf-8

import argparse
import os
import asyncio
import base64
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

def load_qq_sdk() -> Dict[str, Any]:
    try:
        qqmusic_api = importlib.import_module("qqmusic_api")
        qqmusic_login_models = importlib.import_module("qqmusic_api.models.login")
        qqmusic_login_utils = importlib.import_module("qqmusic_api.modules.login_utils")
        qqmusic_song_module = importlib.import_module("qqmusic_api.modules.song")
        return {
            "ok": True,
            "error": "",
            "Client": qqmusic_api.Client,
            "Credential": qqmusic_api.Credential,
            "QRLoginType": qqmusic_login_models.QRLoginType,
            "QRCodeLoginSession": qqmusic_login_utils.QRCodeLoginSession,
            "SongFileInfo": qqmusic_song_module.SongFileInfo,
            "SongFileType": qqmusic_song_module.SongFileType,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


QQ_SDK = load_qq_sdk()
QQ_SDK_AVAILABLE = bool(QQ_SDK.get("ok"))
QQ_SDK_IMPORT_ERROR = str(QQ_SDK.get("error", ""))

QQ_LYRIC_URL = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
QQ_MUSICU_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
VIRTUAL_SINGERS = frozenset(("洛天依", "乐正绫", "言和", "星尘", "诗岸"))


class QQMusicCredentialError(RuntimeError):
    """Raised when QQ Music credential is missing, invalid, or rejected by SDK."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "按歌曲名从 QQ 音乐搜索并下载歌曲和歌词。"
            "会在输出目录下创建与歌名同名的子目录。"
        )
    )
    parser.add_argument("--song_name", required=True, help="歌曲名（必填）。")
    parser.add_argument("--singer", default="洛天依", help="歌手名（默认：洛天依）。")
    parser.add_argument(
        "--output_dir",
        default=os.environ.get("TEST_SONGS_DIR", "outputs/songs"),
        help="输出根目录（默认：TEST_SONGS_DIR 或 outputs/songs）。",
    )
    parser.add_argument("--timeout", type=int, default=20, help="网络请求超时秒数（默认：20）。")
    parser.add_argument(
        "--credential_file",
        default="config/qq_music_credential.json",
        help="QQ 音乐登录凭证保存路径（默认：config/qq_music_credential.json）。",
    )
    parser.add_argument(
        "--login_timeout",
        type=int,
        default=180,
        help="扫码登录最长等待秒数（默认：180）。",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="执行一次扫码登录并保存凭证，然后继续下载。",
    )
    parser.add_argument(
        "--no_auto_login",
        action="store_true",
        help="当下载链接受限时不自动触发扫码登录。",
    )
    return parser.parse_args()


def safe_name(name: str) -> str:
    bad_chars = '<>:"/\\|?*\n\r\t'
    cleaned = "".join("_" if c in bad_chars else c for c in name)
    import re
    bracket_patterns = [
        r"\([^()]*\)",
        r"（[^（）]*）",
    ]
    
    for pattern in bracket_patterns:
        while True:
            updated = re.sub(pattern, "", cleaned)
            if updated == cleaned:
                break
            cleaned = updated

    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip().rstrip(".").strip()
    return cleaned or f"song_{int(time.time())}"


def qq_headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Referer": "https://y.qq.com/",
        "Origin": "https://y.qq.com",
    }


def normalize_text(text: str) -> str:
    return "".join(text.strip().lower().split())


def get_song_singer_names(song: Dict[str, Any]) -> List[str]:
    """Return the structured singer names supplied by QQ Music."""
    names: List[str] = []
    for singer in song.get("singer") or []:
        if isinstance(singer, dict):
            name = singer.get("name", "")
        else:
            name = singer
        name = str(name or "").strip()
        if name:
            names.append(name)
    return names


def validate_song_singers(song: Dict[str, Any], target_singer: str = "洛天依") -> Tuple[bool, str]:
    """Allow only songs whose complete structured singer list is the target singer."""
    singer_names = get_song_singer_names(song)
    target = normalize_text(target_singer)
    normalized_names = [normalize_text(name) for name in singer_names]

    if not singer_names:
        return False, "歌手信息为空"
    if target not in normalized_names:
        return False, f"歌手列表不包含目标歌手 {target_singer}"

    other_names = [name for name, normalized in zip(singer_names, normalized_names) if normalized != target]
    if other_names:
        known_other_names = [name for name in other_names if name in VIRTUAL_SINGERS]
        unknown_other_names = [name for name in other_names if name not in VIRTUAL_SINGERS]
        details = []
        if known_other_names:
            details.append(f"其他虚拟歌手: {'、'.join(known_other_names)}")
        if unknown_other_names:
            details.append(f"未知歌手: {'、'.join(unknown_other_names)}")
        return False, "歌曲包含其他歌手（" + "；".join(details) + "）"

    return True, ""


def load_saved_credential(credential_file: Path) -> Optional[Dict[str, Any]]:
    if not credential_file.exists():
        return None
    try:
        data = json.loads(credential_file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("musicid") is not None:
            return data
    except Exception:
        return None
    return None


def save_credential(credential_file: Path, credential_dict: Dict[str, Any]) -> None:
    credential_file.parent.mkdir(parents=True, exist_ok=True)
    credential_file.write_text(
        json.dumps(credential_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def validate_credential(credential_dict: Dict[str, Any]) -> bool:
    if not QQ_SDK_AVAILABLE:
        return False
    try:
        QQ_SDK["Credential"].model_validate(credential_dict)
        return True
    except Exception:
        return False


async def generate_qr_only(qr_image_path: Path) -> bool:
    """生成 QQ 登录二维码并保存到文件，不等待扫码。返回是否成功。"""
    if not QQ_SDK_AVAILABLE:
        return False
    try:
        async with QQ_SDK["Client"](verify=False) as client:
            session = QQ_SDK["QRCodeLoginSession"](
                api=client.login,
                login_type=QQ_SDK["QRLoginType"].QQ,
                timeout_seconds=1.0,  # 不关心超时，只为获取二维码
            )
            qr = await session.get_qrcode()
            qr_image_path.parent.mkdir(parents=True, exist_ok=True)
            qr_image_path.write_bytes(qr.data)
            print(f"[INFO] 登录二维码已保存: {qr_image_path}")
            return True
    except Exception as exc:
        print(f"[WARN] 生成 QQ 登录二维码失败: {exc}")
        return False


def try_load_and_inject_credential(credential_file: Path) -> bool:
    saved = load_saved_credential(credential_file)
    if not saved:
        return False
    if not validate_credential(saved):
        return False
    print(f"[INFO] 已加载本地登录凭证: {credential_file}")
    return True


async def qr_login_async(login_timeout: int, qr_image_path: Path):
    async with QQ_SDK["Client"](verify=False) as client:
        session = QQ_SDK["QRCodeLoginSession"](
            api=client.login,
            login_type=QQ_SDK["QRLoginType"].QQ,
            timeout_seconds=float(login_timeout),
        )
        qr = await session.get_qrcode()

        qr_image_path.parent.mkdir(parents=True, exist_ok=True)
        qr_image_path.write_bytes(qr.data)
        print(f"[INFO] 登录二维码已保存: {qr_image_path}")
        try:
            os.startfile(str(qr_image_path))  # type: ignore[attr-defined]
        except Exception:
            print("[INFO] 无法自动打开二维码图片，请手动打开后扫码。")

        credential = await session.wait_qrcode_login()
        print("[LOGIN] 登录成功。")
        return credential


def ensure_qr_login(credential_file: Path, login_timeout: int, force_login: bool = False) -> Dict[str, Any]:
    if not QQ_SDK_AVAILABLE:
        raise RuntimeError(
            "当前环境未安装 qqmusic-api-python，无法扫码登录。"
            f"导入错误: {QQ_SDK_IMPORT_ERROR}"
        )

    if not force_login:
        saved = load_saved_credential(credential_file)
        if saved and validate_credential(saved):
            print(f"[INFO] 已加载本地登录凭证: {credential_file}")
            return saved

    print("[INFO] 开始 QQ 扫码登录流程。")
    qr_image_path = credential_file.parent / "qq_login_qr.png"
    credential = asyncio.run(qr_login_async(login_timeout, qr_image_path))
    credential_dict = credential.model_dump(by_alias=False)
    save_credential(credential_file, credential_dict)
    print(f"[INFO] 登录凭证已保存，下次会自动复用: {credential_file}")
    return credential_dict


def qq_fetch_mp3_url_by_sdk(songmid: str, credential_dict: Dict[str, Any]) -> str:
    if not QQ_SDK_AVAILABLE:
        raise QQMusicCredentialError(
            "qqmusic-api-python 不可用，无法使用 credential 下载 VIP/受限歌曲。"
            f"导入错误: {QQ_SDK_IMPORT_ERROR}"
        )

    async def _inner() -> str:
        credential = QQ_SDK["Credential"].model_validate(credential_dict)
        async with QQ_SDK["Client"](credential=credential, verify=False) as client:
            cdn_dispatch = await client.song.get_cdn_dispatch()
            cdn = cdn_dispatch.sip[0] if cdn_dispatch.sip else "https://isure.stream.qqmusic.qq.com/"
            song_urls = await client.song.get_song_urls(
                [QQ_SDK["SongFileInfo"](mid=songmid)],
                file_type=QQ_SDK["SongFileType"].MP3_128,
            )
            if not song_urls.data:
                return ""
            purl = song_urls.data[0].purl or ""
            if not purl:
                return ""
            if purl.startswith("http://") or purl.startswith("https://"):
                return purl
            return cdn + purl
        return ""

    try:
        return asyncio.run(_inner())
    except Exception as exc:
        raise QQMusicCredentialError(f"QQ 音乐 credential 不可用或已过期: {exc}") from exc


def qq_search_songs(song_name: str, timeout: int = 20) -> List[Dict]:
    payload = {
        "comm": {"ct": 19, "cv": 1859, "uin": 0},
        "request": {
            "method": "DoSearchForQQMusicDesktop",
            "module": "music.search.SearchCgiService",
            "param": {
                "query": song_name,
                "num_per_page": 30,
                "page_num": 1,
                "search_type": 0,
                "grp": 1,
            },
        },
    }
    resp = requests.post(
        QQ_MUSICU_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**qq_headers(), "Content-Type": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    songs = data.get("request", {}).get("data", {}).get("body", {}).get("song", {}).get("list", [])
    if not songs:
        raise RuntimeError(f"未在 QQ 音乐搜索到歌曲: {song_name}")
    return songs


def pick_song_by_singer(songs: List[Dict], singer_name: str) -> List[Dict]:
    singer_songs = []
    target = normalize_text(singer_name)
    for song in songs:
        singers = song.get("singer") or []
        for singer in singers:
            name = singer.get("name", "")
            if normalize_text(name) == target:
                singer_songs.append(song)
                
    if singer_songs:
        return singer_songs
    raise RuntimeError(
        f"搜索到歌曲，但没有匹配到指定歌手: {singer_name}。"
        "请检查歌手名或更换歌曲关键字。"
    )


def longest_common_subsequence_length(left: str, right: str) -> int:
    """Return the length of the longest not-necessarily-contiguous common subsequence."""
    if not left or not right:
        return 0
    if len(left) > len(right):
        left, right = right, left

    previous = [0] * (len(left) + 1)
    for right_char in right:
        current = [0]
        for index, left_char in enumerate(left, start=1):
            if left_char == right_char:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[index - 1]))
        previous = current
    return previous[-1]


def _normalized_song_title(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return normalize_text(safe_name(raw))


def _title_match_kind(song: Dict, requested_name: str) -> str:
    requested = _normalized_song_title(requested_name)
    title = _normalized_song_title(str(song.get("title") or ""))
    if not requested or not title:
        return ""
    if title == requested:
        return "exact"
    if requested in title or title in requested:
        return "contains"

    common_length = longest_common_subsequence_length(requested, title)
    threshold = max(2, max(len(requested), len(title)) / 2)
    if common_length >= threshold:
        return "subsequence"
    return ""


def rank_songs_by_title(songs: List[Dict], requested_name: str) -> List[Dict]:
    exact: List[Dict] = []
    partial: List[Dict] = []
    subsequence: List[Dict] = []
    for song in songs:
        match_kind = _title_match_kind(song, requested_name)
        if match_kind == "exact":
            exact.append(song)
        elif match_kind == "contains":
            partial.append(song)
        elif match_kind == "subsequence":
            subsequence.append(song)
    return exact + partial + subsequence


def title_matches(song: Dict, requested_name: str) -> bool:
    return bool(_title_match_kind(song, requested_name))


def qq_fetch_lyric(songmid: str, timeout: int = 20) -> str:
    params = {
        "songmid": songmid,
        "pcachetime": str(int(time.time() * 1000)),
        "g_tk": "5381",
        "loginUin": "0",
        "hostUin": "0",
        "format": "json",
        "inCharset": "utf8",
        "outCharset": "utf-8",
        "notice": "0",
        "platform": "yqq.json",
        "needNewCode": "0",
    }
    resp = requests.get(QQ_LYRIC_URL, params=params, headers=qq_headers(), timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    lyric_b64 = data.get("lyric", "")
    if not lyric_b64:
        return ""
    try:
        return base64.b64decode(lyric_b64).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def qq_fetch_mp3_url(songmid: str, timeout: int = 20) -> str:
    guid = "7332953645"
    filename = f"M500{songmid}.mp3"
    payload = {
        "comm": {"ct": 24, "cv": 0, "uin": 0, "format": "json"},
        "req": {
            "module": "vkey.GetVkeyServer",
            "method": "CgiGetVkey",
            "param": {
                "guid": guid,
                "songmid": [songmid],
                "songtype": [0],
                "uin": "0",
                "loginflag": 1,
                "platform": "20",
                "filename": [filename],
            },
        },
    }
    resp = requests.post(
        QQ_MUSICU_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**qq_headers(), "Content-Type": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    req_data = data.get("req", {}).get("data", {})
    purl_list = req_data.get("midurlinfo", [])
    sip_list = req_data.get("sip", [])
    if not purl_list or not sip_list:
        return ""
    purl = purl_list[0].get("purl", "")
    if not purl:
        return ""
    return sip_list[0] + purl


def download_song_file(url: str, target: Path, timeout: int = 60) -> None:
    with requests.get(url, headers=qq_headers(), stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with target.open("wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def download_song_and_lyric(
    song_name: str,
    singer_name: str = "洛天依",
    output_dir: Path = Path("outputs"),
    timeout: int = 20,
    credential_file: Optional[Path] = None,
    login_timeout: int = 180,
    force_login: bool = False,
    no_auto_login: bool = False,
) -> Tuple[str, Path, Path]:
    if credential_file is None:
        credential_file = Path("res/song_learner/.qq_music_credential.json")

    output_dir = Path(output_dir).expanduser().resolve()
    credential_file = Path(credential_file).expanduser().resolve()

    songs = qq_search_songs(song_name + " " + singer_name, timeout=timeout)
    singer_songs = rank_songs_by_title(pick_song_by_singer(songs, singer_name), song_name)
    if not singer_songs:
        raise RuntimeError(
            f"搜索到 {singer_name} 的歌曲，但没有标题匹配请求: {song_name}"
        )
    matched_failures: List[str] = []

    validated_singer_songs: List[Dict[str, Any]] = []
    for song in singer_songs:
        title = song.get("title") or song_name
        singers_valid, reason = validate_song_singers(song, singer_name)
        if not singers_valid:
            matched_failures.append(f"{title}: {reason}")
            print(f"[WARN] {reason}，跳过: {title}")
            continue
        validated_singer_songs.append(song)
    singer_songs = validated_singer_songs

    for song in singer_songs:
        title = song.get("title") or song_name
        songmid = song.get("mid")
        if not songmid:
            reason = "歌曲信息不完整，缺少 songmid"
            matched_failures.append(f"{title}: {reason}")
            print(f"[WARN] {reason}，跳过: {title}")
            continue

        singer = "、".join(get_song_singer_names(song)) or singer_name

        song_folder = output_dir / safe_name(title)
        song_folder.mkdir(parents=True, exist_ok=True)

        file_stem = safe_name(f"{title}")
        mp3_path = song_folder / f"{file_stem}.mp3"
        lrc_path = song_folder / f"{file_stem}.lrc"

        active_credential: Optional[Dict[str, Any]] = None
        if force_login:
            active_credential = ensure_qr_login(
                credential_file=credential_file,
                login_timeout=login_timeout,
                force_login=True,
            )
        else:
            saved = load_saved_credential(credential_file)
            if saved:
                if not validate_credential(saved):
                    raise QQMusicCredentialError(f"QQ 音乐 credential 格式无效: {credential_file}")
                active_credential = saved
                print(f"[INFO] 已加载本地登录凭证: {credential_file}")

        mp3_url = qq_fetch_mp3_url(songmid, timeout=timeout)
        if active_credential and not mp3_url:
            mp3_url = qq_fetch_mp3_url_by_sdk(songmid, active_credential)

        if not mp3_url:
            print("[WARN] 普通下载链接不可用，可能是版权或 VIP 限制。")
            if no_auto_login:
                raise QQMusicCredentialError(
                    f"VIP/受限歌曲需要有效 QQ 音乐 credential，但未能获取下载链接: {credential_file}"
                )
            active_credential = ensure_qr_login(
                credential_file=credential_file,
                login_timeout=login_timeout,
                force_login=False,
            )
            mp3_url = qq_fetch_mp3_url_by_sdk(songmid, active_credential)

        if not mp3_url:
            reason = "登录后仍未获取到可下载链接，可能歌曲不可用或权限受限"
            matched_failures.append(f"{title}: {reason}")
            print(f"[WARN] {reason}。")
            continue

        print(f"[INFO] 已匹配歌曲: {title} - {singer} (songmid={songmid})")
        print(f"[INFO] 开始下载歌曲到: {mp3_path}")
        download_song_file(mp3_url, mp3_path, timeout=max(60, timeout))

        lyric = qq_fetch_lyric(songmid, timeout=timeout)
        if not lyric.strip():
            matched_failures.append(f"{title}: 歌曲下载成功，但未获取到歌词内容")
            print("[WARN] 歌曲下载成功，但未获取到歌词内容。")
            continue

        lrc_path.write_text(lyric, encoding="utf-8")
        return file_stem, mp3_path, lrc_path

    if matched_failures:
        raise RuntimeError(
            f"匹配到 {song_name} - {singer_name}，但匹配候选均不可下载或不可用: "
            f"{'; '.join(matched_failures)}"
        )
    raise RuntimeError(f"未能下载到可用的歌曲音频: {song_name} - {singer_name}")


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    credential_file = Path(args.credential_file).expanduser().resolve()

    try:
        file_stem, mp3_path, lrc_path = download_song_and_lyric(
            song_name=args.song_name,
            singer_name=args.singer,
            output_dir=output_dir,
            timeout=args.timeout,
            credential_file=credential_file,
            login_timeout=args.login_timeout,
            force_login=args.login,
            no_auto_login=args.no_auto_login,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    print("\n[SUCCESS] 下载完成")
    print(f"[RESULT] 歌曲文件: {mp3_path}")
    print(f"[RESULT] 歌词文件: {lrc_path}")


if __name__ == "__main__":
    main()
