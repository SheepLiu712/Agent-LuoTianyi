import datetime
from src.utils.logger import get_logger
import requests
import re
import time
from typing import Dict, Any, List
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from .wiki_api import fetch_wikitext
from .wikitext_parser import parse_song_titles
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher
from src.subconscious.music_knowledge.song_database import init_song_db, get_song_session, Song

logger = get_logger("DailyNewSongFetcher")
CURRENT_YEAR = datetime.datetime.now().year
TEMPLATE_URL = f"https://vcpedia.cn/Template:%E6%B4%9B%E5%A4%A9%E4%BE%9D/{CURRENT_YEAR}"
KNOWLEDGE_DIR = Path("res/knowledge")
SONG_NAME_KEYWORDS_FILE = KNOWLEDGE_DIR / "song_name_keywords.txt"
SONG_LYRIC_KEYWORDS_FILE = KNOWLEDGE_DIR / "song_lyric_keywords.txt"


def fetch_song_list_from_template(url: str, timeout: int = 20) -> List[str]:
    """Return ordered link display names as before; API failures propagate."""
    parsed = urlsplit(url)
    title = parse_qs(parsed.query).get('title', [unquote(parsed.path.lstrip('/'))])[0]
    source = fetch_wikitext(f'{parsed.scheme}://{parsed.netloc}', title, requests.get, timeout)
    return parse_song_titles(source)


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


def _append_keywords_to_files(song_name: str, spaced_lyrics: str) -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    lyric_lines = _split_spaced_lyrics(spaced_lyrics)
    lyric_keywords = [f"{lyric}=>{lyric}是《{song_name}》的歌词" for lyric in lyric_lines]

    with open(SONG_NAME_KEYWORDS_FILE, "a", encoding="utf-8") as name_file:
        name_file.write(f"{song_name}\n")

    if lyric_keywords:
        with open(SONG_LYRIC_KEYWORDS_FILE, "a", encoding="utf-8") as lyric_file:
            for line in lyric_keywords:
                lyric_file.write(f"{line}\n")

def do_one_song(db, fetcher: VCPediaFetcher, song_name, update = False) -> bool:
    if db and _song_exists(db, song_name) and not update:
        logger.info(f"已存在，跳过: {song_name}")
        return False

    logger.info(f"开始抓取并入库: {song_name}")
    data = fetcher.fetch_entity_description(song_name)
    if not data:
        return False

    fields = _extract_song_fields(data)
    if not fields["introduction"]:
        return False

    if db is not None:
        try:
            if _song_exists(db, song_name):
                logger.info(f"已存在（更新模式），先删除: {song_name}")
                db.query(Song).filter(
                    (Song.name == song_name) |
                    (Song.safe_name == _safe_song_name(song_name))
                ).delete()
                db.commit()
            db_song = Song(
                name=song_name,
                safe_name=_safe_song_name(song_name),
                uploader=fields["uploader"],
                singers=fields["singers"],
                introduction=fields["introduction"],
                lyrics=fields["lyrics"],
            )
            db.add(db_song)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"入库失败 {song_name}: {e}")
            return False

    try:
        _append_keywords_to_files(song_name, fields["spaced_lyrics"])
    except Exception as e:
        logger.error(f"写入失败 {song_name}: {e}")

    return True

def sync_daily_new_songs(song_knowledge_config: Dict[str, Any], llm_module: Any | None = None) -> Dict[str, List[str]]:
    song_db_cfg = song_knowledge_config.get("song_database", {})
    if not song_db_cfg:
        raise ValueError("缺少 knowledge.song_database 配置")

    crawler_cfg = song_knowledge_config.get("crawler", {})
    if not crawler_cfg:
        raise ValueError("缺少 knowledge.crawler 配置")

    init_song_db(song_db_cfg)
    db = get_song_session()

    added: List[str] = []
    failed: List[str] = []
    try:
        songs = fetch_song_list_from_template(TEMPLATE_URL)
        fetcher = VCPediaFetcher(crawler_cfg, llm_module=llm_module)

        for i, song_name in enumerate(songs, start=1):
            if do_one_song(db, fetcher, song_name):
                added.append(song_name)
            else:
                failed.append(song_name)

            time.sleep(0.8)

        return {"added": added, "failed": failed}
    finally:
        db.close()

# if __name__ == "__main__":
    
#     cfg = load_config("config/config.json", default_config={})
#     init_song_db(cfg.get("knowledge", {}).get("song_database", {}))
#     db = get_song_session()
#     do_one_song(db, VCPediaFetcher(cfg.get("crawler", {})), "告死鸟", update=True)
#     db.close()

if __name__ == "__main__":
    # This would typically be called with the actual song knowledge config
    result = sync_daily_new_songs(song_knowledge_config={})
    added = result.get("added", [])
    failed = result.get("failed", [])

    print("\n===== 本次同步结果 =====")
    print(f"新增歌曲数: {len(added)}")
    for name in added:
        print(f"  + {name}")

    print(f"抓取/入库失败数: {len(failed)}")
    for item in failed:
        print(f"  - {item}")
