import os
import sys

cwd = os.getcwd()
sys.path.insert(0, str(cwd))

import datetime
from src.utils.logger import get_logger
import requests
from bs4 import BeautifulSoup
import json
import logging
import time
import subprocess
import shutil
from typing import Dict, Any, Optional, List, Set
from pathlib import Path
from urllib.parse import quote
from src.utils.helpers import load_config
from src.plugins.music.vcpedia_fetcher import VCPediaFetcher
from src.plugins.music.song_database import init_song_db, get_song_session, Song

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

    return {
        "uploader": uploader,
        "singers": singers,
        "introduction": short_summary,
        "lyrics": lyrics,
    }


def sync_daily_new_songs(config_path: str = "config/config.json") -> Dict[str, List[str]]:
    cfg = load_config(config_path, default_config={})

    song_db_cfg = cfg.get("knowledge", {}).get("song_database", {})
    if not song_db_cfg:
        raise ValueError("缺少 knowledge.song_database 配置")

    crawler_cfg = cfg.get("crawler", {})
    crawler_cfg["activated"] = True

    init_song_db(song_db_cfg)
    db = get_song_session()

    added: List[str] = []
    failed: List[str] = []
    try:
        songs = fetch_song_list_from_template(TEMPLATE_URL)
        fetcher = VCPediaFetcher(crawler_cfg)

        for i, song_name in enumerate(songs, start=1):
            if _song_exists(db, song_name):
                logger.info(f"[{i}/{len(songs)}] 已存在，跳过: {song_name}")
                continue

            logger.info(f"[{i}/{len(songs)}] 开始抓取并入库: {song_name}")
            data = fetcher.fetch_entity_description(song_name)
            if not data:
                failed.append(f"{song_name}（抓取失败）")
                continue

            fields = _extract_song_fields(data)
            if not fields["introduction"]:
                failed.append(f"{song_name}（缺少 short_summary）")
                continue

            try:
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
                added.append(song_name)
            except Exception as e:
                db.rollback()
                logger.error(f"入库失败 {song_name}: {e}")
                failed.append(f"{song_name}（入库失败）")

            time.sleep(0.8)

        return {"added": added, "failed": failed}
    finally:
        db.close()

if __name__ == "__main__":
    result = sync_daily_new_songs()
    added = result.get("added", [])
    failed = result.get("failed", [])

    print("\n===== 本次同步结果 =====")
    print(f"新增歌曲数: {len(added)}")
    for name in added:
        print(f"  + {name}")

    print(f"抓取/入库失败数: {len(failed)}")
    for item in failed:
        print(f"  - {item}")