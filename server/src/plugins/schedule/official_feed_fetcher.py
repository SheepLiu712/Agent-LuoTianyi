"""
官方动态爬取器：从 B站/微博等平台拉取洛天依官方账号的最新动态。
支持多账号配置，JSON 持久化最近已处理的动态 ID 用于去重。
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from src.utils.logger import get_logger
from src.plugins.schedule.event_models import OfficialDynamic

logger = get_logger(__name__)

# 洛天依相关官方账号（可配置）
DEFAULT_BILI_ACCOUNTS = [
    ("36081646", "洛天依"),          # 官方主账号
]

DEFAULT_WEIBO_ACCOUNTS: List[str] = []


class OfficialFeedFetcher:
    """
    从 B站 拉取官方账号动态。
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
        self.bili_accounts: List[str] = [str(a) for a in bili_accounts] if bili_accounts else [uid for uid, _ in DEFAULT_BILI_ACCOUNTS]
        self.weibo_accounts: List[str] = [str(a) for a in weibo_accounts] if weibo_accounts else DEFAULT_WEIBO_ACCOUNTS

        self.data_file = Path(data_file)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0",
            "Referer": "https://space.bilibili.com/36081646/dynamic",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ja;q=0.5",
            "Sec-Ch-Ua": '"Microsoft Edge";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        })
        

        cookie_file = Path("config/bili_cookie.txt")
        bili_cookie = ""
        if cookie_file.exists():
            try:
                raw = cookie_file.read_text(encoding="utf-8-sig").strip()
                # 去除 BOM (\\ufeff) 和其他不可见控制字符，防止 HTTP 头 latin-1 编码失败
                bili_cookie = raw.encode("utf-8", errors="ignore").decode("utf-8")
                self.logger.info(f"Loaded B站 cookie from {cookie_file}")
            except Exception as e:
                self.logger.warning(f"Failed to read {cookie_file}: {e}")

        if bili_cookie:
            self.session.headers.update({"Cookie": bili_cookie})
            
        # 缓存最近处理过的动态 ID，避免重复处理
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
            # 只保留最近 200 条记录
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
        返回原始动态 OfficialDynamic 列表
        """
        all_items: List[OfficialDynamic] = []
        for uid in self.bili_accounts:
            try:
                items = self._fetch_bili_space(uid)
                all_items.extend(items)
                time.sleep(0.5)  # 礼貌延迟
            except Exception as e:
                self.logger.error(f"Error fetching B站 UID={uid}: {e}")

        self._save_cache()
        return all_items

    def _fetch_bili_space(self, uid: str, max_pages: int = 3) -> List[OfficialDynamic]:
        """
        拉取 B站 用户空间动态，返回新动态列表。
        使用 offset 翻页，每次比较 dynamic_id 是否已处理过。
        """
        results: List[OfficialDynamic] = []
        seen = set(self.seen_ids.get(uid, []))
        offset: Optional[str] = None

        for page in range(max_pages):
            url = f"https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space?host_mid={uid}&type=all"
            if offset:
                url += f"&offset={offset}"

            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code != 200:
                    self.logger.warning(f"B站 API 返回 {resp.status_code} for UID={uid}")
                    break
                data = resp.json()
                if data.get("code", 0) != 0:
                    self.logger.warning(f"B站 API 错误: {data.get('message')} for UID={uid}")
                    break

                items = data.get("data", {}).get("items", [])
                if not items:
                    break
                print(len(items))
                for item in items:
                    dyn_id = str(item.get("id_str") or item.get("id", ""))
                    if not dyn_id:
                        continue
                    if dyn_id in seen:
                        # 已经处理过，因为是按时间倒序，后面的都是旧的
                        break

                    seen.add(dyn_id)
                    parsed = self._parse_bili_item(uid, item)
                    if parsed:
                        results.append(parsed)

                # 更新 offset 用于翻页
                offset = data.get("data", {}).get("offset")
                if not offset:
                    break

            except Exception as e:
                self.logger.error(f"Error fetching page {page} for UID={uid}: {e}")
                break

        # 更新缓存
        self.seen_ids[uid] = list(seen)
        self.logger.info(f"Fetched {len(results)} new dynamics from B站 UID={uid}")
        return results

    def _parse_bili_item(self, uid: str, item: Dict[str, Any]) -> Optional[OfficialDynamic]:
        """
        从 B站 Web V1 Feed/Space 动态 item 中提取文本内容。
        """
        try:
            dyn_id = str(item.get("id_str") or "")
            dyn_type = item.get("type", "")
            
            modules = item.get("modules", {})
            if not modules:
                return None

            # ①跳过置顶动态
            module_tag = modules.get("module_tag")
            if module_tag and isinstance(module_tag, dict):
                tag_text = module_tag.get("text", "")
                if "置顶" in tag_text:
                    return None

            account_name = ""
            author_module = modules.get("module_author", {})
            if author_module:
                account_name = author_module.get("name", "")
            
            if not account_name:
                for u, name in self.bili_accounts:
                    if u == uid:
                        account_name = name
                        break

            # 内部辅助函数，用来提取动态本身或者原动态（orig）的内容
            def extract_from_dynamic(dyn: Dict[str, Any], is_orig: bool = False) -> Dict[str, Any]:
                content_parts = []
                pics = []
                dyn_modules = dyn.get("modules", {})
                name = dyn_modules.get("module_author", {}).get("name", "") or account_name
                if is_orig:
                    name = f"(转发自 {name}的动态)"
                module_dynamic = dyn_modules.get("module_dynamic", {})
                if not module_dynamic:
                    return {"text": "", "pics": [], "name": name}
                
                # ③ modules/module_dynamic/desc 可能包含 text
                desc_obj = module_dynamic.get("desc", {})
                if desc_obj and isinstance(desc_obj, dict) and desc_obj.get("text"):
                    text = desc_obj.get("text", "")
                    if is_orig:
                        content_parts.append(f"【原动态】动态文本：{text}")
                    else:
                        content_parts.append(f"动态文本：{text}")
                
                # ② modules/module_dynamic/major 包含核心信息
                major_obj = module_dynamic.get("major", {})
                if major_obj and isinstance(major_obj, dict):
                    major_type = major_obj.get("type", "")
                    
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
                            items = draw.get("items", [])
                            for p in items:
                                src = p.get("src")
                                if src:
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
            
            # ④ orig 表示转发的原始来源
            orig = item.get("orig")
            if orig and isinstance(orig, dict):
                extracted_orig = extract_from_dynamic(orig, is_orig=True)
                if extracted_orig["text"]:
                    content_parts.append(extracted_orig["text"])
                pics.extend(extracted_orig["pics"])

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
                source_url=f"https://t.bilibili.com/{dyn_id}",
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
