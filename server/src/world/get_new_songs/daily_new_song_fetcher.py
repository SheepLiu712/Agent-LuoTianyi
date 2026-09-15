import os
import sys

cwd = os.getcwd()
sys.path.insert(0, str(cwd))

import datetime
from dataclasses import dataclass
from src.utils.logger import get_logger
import requests
from bs4 import BeautifulSoup
import re
import time
import subprocess
import shutil
import zlib
from typing import Dict, Any, Optional, List, Set
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher
from src.subconscious.music_knowledge.song_database import init_song_db, get_song_session, Song

logger = get_logger("DailyNewSongFetcher")
CURRENT_YEAR = datetime.datetime.now().year
TEMPLATE_URL = f"https://vcpedia.cn/Template:%E6%B4%9B%E5%A4%A9%E4%BE%9D/{CURRENT_YEAR}"


def _is_bot_challenge(status_code: int, html: str) -> bool:
    if status_code == 403:
        return True
    text = (html or "").lower()
    markers = [
        "making sure you're not a bot",
        "正在确认你是不是机器",
        "within.website",
        "xess.min.css",
        "anubis",
        "techaro",
    ]
    return any(m in text for m in markers)


def _fetch_html(url: str, headers: Dict[str, str], timeout: int) -> str:
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if not _is_bot_challenge(r.status_code, r.text):
        r.raise_for_status()
        return r.text

    curl_path = shutil.which("curl") or shutil.which("curl.exe")
    if not curl_path:
        r.raise_for_status()

    logger.warning("requests 命中站点反爬挑战，改用 curl 兜底抓取。")
    result = subprocess.run(
        [curl_path, "-sS", "-L", "--max-time", str(timeout), url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl fallback failed: {result.stderr.strip()}")
    html = result.stdout or ""
    if not html.strip():
        raise RuntimeError("curl fallback returned empty response")
    if _is_bot_challenge(200, html):
        raise RuntimeError("curl fallback still got anti-bot challenge page")
    return html

def fetch_song_list_from_template(url: str, timeout: int = 20) -> List[str]:
    """
    从模板页提取歌曲名（按页面出现顺序）。
    逻辑：抓取 mw-content-text 区域内所有链接文本，过滤掉分类/模板/分组标题等。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0 Safari/537.36"
        )
    }
    html = _fetch_html(url, headers=headers, timeout=timeout)

    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="mw-content-text") or soup

    # 过滤关键词（模板结构词，不是歌曲）
    bad_exact: Set[str] = {
        "原创曲", "非原创曲", "传说曲", "殿堂曲", "部分", "25万以上", "25万以下",
        "模板文档", "查看", "编辑", "历史", "刷新",
        "简体", "繁體", "大陆简体", "香港繁體", "臺灣正體", "不转换",
        "跳转到导航", "跳转到搜索", "洛天依",
        "2012", "2013", "2014", "2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "2026",
        "bilibili", "ACE Studio", "X studio", "VOCALOID中文殿堂曲", "ACE殿堂曲", "文档", "嵌入"
    }
    bad_contains = ["Template:", "模板:", "分类:", "Category:", "帮助", "首页", "随机页面", "最近更改", "殿堂曲", "传说曲"]

    # 只取内容区里的链接文本
    seen: Set[str] = set()
    songs: List[str] = []

    for a in content.find_all("a"):
        text = a.get_text(strip=True)
        if not text:
            continue

        # 过滤：明显不是歌曲名的
        if text in bad_exact:
            continue
        if any(x in text for x in bad_contains):
            continue
        # 过滤：纯数字/日期类
        if text.isdigit():
            continue
        # 过滤：站内功能链接
        href = a.get("href", "") or ""
        if not href or href.startswith("#"):
            continue
        if "action=" in href:
            continue
        if "Template:" in href or "Category:" in href or "分类:" in href:
            continue

        # 去掉末尾星号标注（模板里翻唱曲可能带 *）
        text = text.rstrip("*").strip()
        if not text:
            continue

        if text not in seen:
            seen.add(text)
            songs.append(text)

    logger.info(f"从模板页提取到 {len(songs)} 个条目（含歌曲/可能少量非歌曲，后续抓取失败会记录）。")
    return songs


def _safe_song_name(name: str) -> str:
    return "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip()


def _song_exists(db, song_name: str) -> bool:
    safe_name = _safe_song_name(song_name)
    song = db.query(Song).filter(
        (Song.name == song_name) |
        (Song.safe_name == safe_name)
    ).first()
    return song is not None


def _extract_song_fields(data: Dict[str, Any]) -> Dict[str, str]:
    infobox = data.get("infobox") or {}
    uploader = infobox.get("UP主") or infobox.get("投稿者") or infobox.get("发布者") or ""
    singers = infobox.get("演唱") or infobox.get("歌手") or infobox.get("演唱者") or ""

    short_summary = data.get("short_summary") or ""
    if isinstance(short_summary, list):
        short_summary = "\n".join([str(x) for x in short_summary if x])
    short_summary = str(short_summary).strip()

    if not short_summary:
        summary = data.get("summary") or []
        if isinstance(summary, list):
            short_summary = "\n".join([str(x) for x in summary if x])[:200].strip()
        else:
            short_summary = str(summary).strip()[:200]

    lyrics = str(data.get("lyrics") or "").strip()
    spaced_lyrics = str(data.get("spaced_lyrics") or "")

    return {
        "uploader": uploader,
        "singers": singers,
        "introduction": short_summary,
        "lyrics": lyrics,
        "spaced_lyrics": spaced_lyrics
    }


def _split_spaced_lyrics(spaced_lyrics: str) -> List[str]:
    parts = re.split(r"[\n\r\s]+", spaced_lyrics or "")
    ret = []
    for part in parts:
        cleaned = part.strip()
        if len(cleaned) >=6 and len(cleaned) <= 50:
            ret.append(cleaned)
    return ret


@dataclass(frozen=True)
class NewSongCandidate:
    """已规范化并通过来源检查的歌曲候选；不含任何写入结果。"""

    song_name: str
    safe_name: str
    uploader: str
    singers: tuple[str, ...]
    introduction: str
    lyrics: str
    lyric_keywords: tuple[str, ...]


def _split_singers(raw: str) -> tuple[str, ...]:
    """把演唱者字段规范化为名字元组。"""
    parts = re.split(r"[,，、/;；]+", raw or "")
    return tuple(part.strip() for part in parts if part.strip())


def _fetch_candidate(fetcher: VCPediaFetcher, song_name: str) -> Optional[NewSongCandidate]:
    """抓取并规范化单首歌；缺介绍视为不可接纳的候选。"""
    data = fetcher.fetch_entity_description(song_name)
    if not data:
        return None
    fields = _extract_song_fields(data)
    if not fields["introduction"]:
        return None
    return NewSongCandidate(
        song_name=song_name,
        safe_name=_safe_song_name(song_name),
        uploader=fields["uploader"],
        singers=_split_singers(fields["singers"]),
        introduction=fields["introduction"],
        lyrics=fields["lyrics"],
        lyric_keywords=tuple(_split_spaced_lyrics(fields["spaced_lyrics"])),
    )


def content_revision(candidate: NewSongCandidate) -> int:
    """由规范化内容派生出稳定的非负修订号；内容不变则修订号不变。"""
    text = "\x00".join((
        candidate.song_name,
        candidate.uploader,
        ",".join(candidate.singers),
        candidate.introduction,
        candidate.lyrics,
        ",".join(candidate.lyric_keywords),
    ))
    return zlib.crc32(text.encode("utf-8"))


def collect_new_song_candidates(
    song_knowledge_config: Dict[str, Any], llm_module: Any | None = None,
) -> Dict[str, Any]:
    """抓取、规范化并做来源检查；本函数不写入任何知识。

    返回 `discovered`（待接纳候选）、`skipped_existing`（已有知识，跳过）与
    `fetch_failed`（抓取或规范化失败），每首歌之间保持既有节流。
    """
    song_db_cfg = song_knowledge_config.get("song_database", {})
    if not song_db_cfg:
        raise ValueError("缺少 knowledge.song_database 配置")

    crawler_cfg = song_knowledge_config.get("crawler", {})
    if not crawler_cfg:
        raise ValueError("缺少 knowledge.crawler 配置")

    init_song_db(song_db_cfg)
    db = get_song_session()

    discovered: List[NewSongCandidate] = []
    skipped_existing: List[str] = []
    fetch_failed: List[str] = []
    try:
        songs = fetch_song_list_from_template(TEMPLATE_URL)
        fetcher = VCPediaFetcher(crawler_cfg, llm_module=llm_module)

        for song_name in songs:
            if _song_exists(db, song_name):
                logger.info(f"已有知识，跳过: {song_name}")
                skipped_existing.append(song_name)
            else:
                candidate = _fetch_candidate(fetcher, song_name)
                if candidate is None:
                    logger.info(f"抓取或规范化失败: {song_name}")
                    fetch_failed.append(song_name)
                else:
                    discovered.append(candidate)

            time.sleep(0.8)

        return {
            "discovered": discovered,
            "skipped_existing": skipped_existing,
            "fetch_failed": fetch_failed,
        }
    finally:
        db.close()
