"""
官方动态抓取器：从 B 站、微博等平台拉取洛天依官方账号的最新动态。
支持多账号配置，并持久化最近处理过的动态 ID 用于去重。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from src.system.database.event_models import OfficialDynamic
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_BILI_ACCOUNTS: List[str] = [
    "36081646",  # 洛天依官方主账号
]

DEFAULT_WEIBO_ACCOUNTS: List[str] = []

BILI_DYNAMIC_FEATURES = "itemOpusStyle"
BILI_DYNAMIC_WEB_LOCATION = "333.1365"


class OfficialFeedFetcher:
    """
    从 B 站拉取官方账号动态。
    使用 Web 端 API，无需登录即可获取最新动态。
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        data_file: str = "data/schedule/feed_cache.json",
    ):
        self.logger = get_logger(__name__)
        self.config = config or {}
        bili_accounts = self.config.get("official_accounts", {}).get("bilibili", [])
        weibo_accounts = self.config.get("official_accounts", {}).get("weibo", [])
        self.bili_accounts: List[str] = (
            [str(a) for a in bili_accounts] if bili_accounts else list(DEFAULT_BILI_ACCOUNTS)
        )
        self.weibo_accounts: List[str] = (
            [str(a) for a in weibo_accounts] if weibo_accounts else DEFAULT_WEIBO_ACCOUNTS
        )

        self.data_file = Path(data_file)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
                ),
                "Referer": "https://space.bilibili.com/36081646/dynamic",
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                    "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
                "Sec-Ch-Ua": '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )

        cookie_file = Path("config/bili_cookie.txt")
        bili_cookie = ""
        if cookie_file.exists():
            try:
                raw = cookie_file.read_text(encoding="utf-8-sig").strip()
                bili_cookie = raw.encode("utf-8", errors="ignore").decode("utf-8")
                bili_cookie = bili_cookie.replace("\ufeff", "").strip()
                self.logger.info(f"Loaded B站 cookie from {cookie_file}")
            except Exception as e:
                self.logger.warning(f"Failed to read {cookie_file}: {e}")

        if bili_cookie:
            self.session.headers.update({"Cookie": bili_cookie})

        self.seen_ids: Dict[str, List[str]] = self._load_cache()

    def _load_cache(self) -> Dict[str, List[str]]:
        if not self.data_file.exists():
            return {}
        try:
            return json.loads(self.data_file.read_text(encoding="utf-8"))
        except Exception as e:
            self.logger.warning(f"Failed to load feed cache: {e}")
            return {}

    def _save_cache(self) -> None:
        try:
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            for uid in self.seen_ids:
                self.seen_ids[uid] = self.seen_ids[uid][-200:]
            self.data_file.write_text(
                json.dumps(self.seen_ids, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            self.logger.warning(f"Failed to save feed cache: {e}")

    def fetch_all_new(self) -> List[OfficialDynamic]:
        """
        拉取所有配置账号的新动态（去重后）。
        返回原始动态 OfficialDynamic 列表。
        """
        all_items: List[OfficialDynamic] = []
        for uid in self.bili_accounts:
            try:
                items = self._fetch_bili_space(uid)
                all_items.extend(items)
                time.sleep(0.5)
            except Exception as e:
                self.logger.error(f"Error fetching B站 UID={uid}: {e}")

        self._save_cache()
        return all_items

    def _build_bili_space_url(self, uid: str, offset: Optional[str] = None) -> str:
        params = [
            f"host_mid={uid}",
            "type=all",
            "platform=web",
            f"features={BILI_DYNAMIC_FEATURES}",
            f"web_location={BILI_DYNAMIC_WEB_LOCATION}",
        ]
        if offset:
            params.append(f"offset={offset}")
        return "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?" + "&".join(params)

    def _fetch_bili_space(self, uid: str, max_pages: int = 1) -> List[OfficialDynamic]:
        """
        拉取 B 站用户空间动态，返回新动态列表。
        使用新版参数请求 opus 风格动态，避免图文正文缺失。
        """
        results: List[OfficialDynamic] = []
        seen = set(self.seen_ids.get(uid, []))
        offset: Optional[str] = None

        for page in range(max_pages):
            url = self._build_bili_space_url(uid=uid, offset=offset)

            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200:
                    self.logger.warning(f"B站 API returned {resp.status_code} for UID={uid}")
                    break

                data = resp.json()
                if data.get("code", 0) != 0:
                    self.logger.warning(f"B站 API error: {data.get('message')} for UID={uid}")
                    break

                items = data.get("data", {}).get("items", [])
                if not items:
                    break

                for item in items:
                    dyn_id = str(item.get("id_str") or item.get("id", ""))
                    if not dyn_id:
                        continue
                    if dyn_id in seen:
                        break

                    seen.add(dyn_id)
                    parsed = self._parse_bili_item(uid, item)
                    if parsed:
                        results.append(parsed)

                offset = data.get("data", {}).get("offset")
                if not offset:
                    break

            except Exception as e:
                self.logger.error(f"Error fetching page {page} for UID={uid}: {e}")
                break

        self.seen_ids[uid] = list(seen)
        self.logger.info(f"Fetched {len(results)} new dynamics from B站 UID={uid}")
        return results

    @staticmethod
    def _extract_desc_text(desc_obj: Any) -> str:
        if not isinstance(desc_obj, dict):
            return ""
        return str(desc_obj.get("text") or "").strip()

    @staticmethod
    def _join_rich_text_nodes(nodes: Any) -> str:
        if not isinstance(nodes, list):
            return ""
        parts: List[str] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            text = node.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text)
        return "".join(parts).strip()

    def _extract_opus_text(self, opus_obj: Any) -> str:
        if not isinstance(opus_obj, dict):
            return ""

        summary = opus_obj.get("summary")
        if isinstance(summary, dict):
            text = str(summary.get("text") or "").strip()
            if text:
                return text
            rich_text = self._join_rich_text_nodes(summary.get("rich_text_nodes"))
            if rich_text:
                return rich_text

        for key in ("title", "desc", "content"):
            value = opus_obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return ""

    def _extract_opus_pics(self, opus_obj: Any) -> List[str]:
        if not isinstance(opus_obj, dict):
            return []

        urls: List[str] = []
        for pic in opus_obj.get("pics", []):
            if not isinstance(pic, dict):
                continue
            for key in ("url", "src"):
                value = pic.get(key)
                if isinstance(value, str) and value:
                    urls.append(value)
                    break
        return urls

    @staticmethod
    def _extend_unique(dst: List[str], values: Iterable[str]) -> None:
        seen = set(dst)
        for value in values:
            if value and value not in seen:
                dst.append(value)
                seen.add(value)

    def _parse_bili_item(self, uid: str, item: Dict[str, Any]) -> Optional[OfficialDynamic]:
        """
        从 B 站 Web v1 feed/space item 中提取文本内容。
        """
        try:
            dyn_id = str(item.get("id_str") or "")
            dyn_type = item.get("type", "")

            modules = item.get("modules", {})
            if not modules:
                return None

            author_module = modules.get("module_author", {})
            account_name = author_module.get("name", "")
            if not account_name:
                account_name = {"36081646": "洛天依"}.get(uid, f"bili_{uid}")

            def extract_from_dynamic(dyn: Dict[str, Any], is_orig: bool = False) -> Dict[str, Any]:
                content_parts: List[str] = []
                pics: List[str] = []
                dyn_modules = dyn.get("modules", {})
                name = dyn_modules.get("module_author", {}).get("name", "") or account_name
                if is_orig:
                    name = f"(转发自{name}的动态)"

                module_dynamic = dyn_modules.get("module_dynamic", {})
                if not module_dynamic:
                    return {"text": "", "pics": [], "name": name}

                desc_text = self._extract_desc_text(module_dynamic.get("desc"))
                major_obj = module_dynamic.get("major", {})
                major_type = major_obj.get("type", "") if isinstance(major_obj, dict) else ""

                opus_text = ""
                if isinstance(major_obj, dict):
                    opus_text = self._extract_opus_text(major_obj.get("opus"))
                    self._extend_unique(pics, self._extract_opus_pics(major_obj.get("opus")))

                text = desc_text or opus_text
                if text:
                    prefix = "【原动态】动态文本：" if is_orig else "动态文本："
                    content_parts.append(f"{prefix}{text}")

                if major_obj and isinstance(major_obj, dict):
                    if major_type == "MAJOR_TYPE_ARCHIVE":
                        archive = major_obj.get("archive", {})
                        if archive and isinstance(archive, dict):
                            title = archive.get("title", "")
                            desc = archive.get("desc", "")
                            content_parts.append(f"[视频] 标题：{title}")
                            if desc:
                                content_parts.append(f"简介：{desc}")

                    elif major_type == "MAJOR_TYPE_DRAW":
                        draw = major_obj.get("draw", {})
                        if draw and isinstance(draw, dict):
                            for pic in draw.get("items", []):
                                if not isinstance(pic, dict):
                                    continue
                                src = pic.get("src")
                                if isinstance(src, str) and src:
                                    pics.append(src)

                    elif major_type == "MAJOR_TYPE_ARTICLE":
                        article = major_obj.get("article", {})
                        if article and isinstance(article, dict):
                            title = article.get("title", "")
                            desc = article.get("desc", "")
                            content_parts.append(f"[专栏] 标题：{title}")
                            if desc:
                                content_parts.append(f"简介：{desc}")

                return {"text": "\n".join(content_parts), "pics": pics, "name": name}

            extracted = extract_from_dynamic(item, is_orig=False)
            content_parts = [extracted["text"]]
            pics = extracted["pics"]

            orig = item.get("orig")
            if orig and isinstance(orig, dict):
                extracted_orig = extract_from_dynamic(orig, is_orig=True)
                if extracted_orig["text"]:
                    content_parts.append(extracted_orig["text"])
                self._extend_unique(pics, extracted_orig["pics"])

            content = "\n".join(filter(None, content_parts))
            pub_ts = author_module.get("pub_ts", 0)
            if pub_ts:
                dt_str = datetime.fromtimestamp(int(pub_ts)).isoformat()
            else:
                dt_str = datetime.now().isoformat()

            return OfficialDynamic(
                uid=uid,
                account_name=account_name or f"bili_{uid}",
                platform="bilibili",
                dynamic_id=dyn_id,
                dynamic_type=dyn_type,
                content=content,
                raw_content=content[:2000],
                pics=pics,
                publish_time=dt_str,
                source_url=f"https://www.bilibili.com/opus/{dyn_id}",
            )
        except Exception as e:
            self.logger.error(f"Error parsing B站 dynamic item: {e}", exc_info=True)
            return None

    def fetch_weibo(self, uid: str) -> List[OfficialDynamic]:
        """
        微博动态爬取（占位实现，需要配合 RSSHub 或微博 API）。
        暂时返回空列表。
        """
        self.logger.info("Weibo fetcher not yet implemented")
        return []
