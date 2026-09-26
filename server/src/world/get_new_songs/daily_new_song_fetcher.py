import datetime
import re
import time
import zlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlsplit

import requests

from src.infrastructure.persistence import Song, get_song_session, init_song_db
from src.utils.logger import get_logger
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher
from src.world.get_new_songs.wiki_api import fetch_wikitext
from src.world.get_new_songs.wikitext_parser import parse_song_titles

CURRENT_YEAR = datetime.datetime.now().year
TEMPLATE_URL = f"https://vcpedia.cn/Template:%E6%B4%9B%E5%A4%A9%E4%BE%9D/{CURRENT_YEAR}"
logger = get_logger("DailyNewSongFetcher")


def fetch_song_list_from_template(url: str, timeout: int = 20) -> List[str]:
    """取模板页 wikitext 并按页面顺序返回歌曲显示名；API 失败向上抛出。"""
    parsed = urlsplit(url)
    title = parse_qs(parsed.query).get("title", [unquote(parsed.path.lstrip("/"))])[0]
    source = fetch_wikitext(f"{parsed.scheme}://{parsed.netloc}", title, requests.get, timeout)
    titles = parse_song_titles(source)
    logger.info(f"从模板页提取到 {len(titles)} 个条目（含歌曲/可能少量非歌曲，后续抓取失败会记录）。")
    return titles


def _safe_song_name(name: str) -> str:
    return "".join([c for c in name if c.isalnum() or c in (" ", "-", "_")]).strip()


def _song_exists(db, song_name: str) -> bool:
    safe_name = _safe_song_name(song_name)
    song = db.query(Song).filter((Song.name == song_name) | (Song.safe_name == safe_name)).first()
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
        "spaced_lyrics": spaced_lyrics,
    }


def _split_spaced_lyrics(spaced_lyrics: str) -> List[str]:
    parts = re.split(r"[\n\r\s]+", spaced_lyrics or "")
    ret = []
    for part in parts:
        cleaned = part.strip()
        if len(cleaned) >= 6 and len(cleaned) <= 50:
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
    text = "\x00".join(
        (
            candidate.song_name,
            candidate.uploader,
            ",".join(candidate.singers),
            candidate.introduction,
            candidate.lyrics,
            ",".join(candidate.lyric_keywords),
        )
    )
    return zlib.crc32(text.encode("utf-8"))


def collect_new_song_candidates(
    song_knowledge_config: Dict[str, Any],
    llm_module: Any | None = None,
    *,
    extraction_llm_module: Any | None = None,
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
        fetcher = VCPediaFetcher(crawler_cfg, llm_module=llm_module,
                                 extraction_llm_module=extraction_llm_module)

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
