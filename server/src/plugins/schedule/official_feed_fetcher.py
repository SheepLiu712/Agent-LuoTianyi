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

logger = get_logger(__name__)

# 洛天依相关官方账号（可配置）
DEFAULT_BILI_ACCOUNTS = [
    ("387636363", "洛天依官方"),   # 官方账号
    ("1149997800", "洛天依"),        # 主账号
    ("158938658", "天依二创"),       # 二创动态
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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.6099.71 Safari/537.36"
            ),
            "Referer": "https://space.bilibili.com/",
        })
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

    def fetch_all_new(self) -> List[Dict[str, Any]]:
        """
        拉取所有配置账号的新动态（去重后）。
        返回原始动态字典列表，每个字典包含：
            - uid: 账号 UID
            - account_name: 账号名称
            - dynamic_id: 动态 ID
            - dynamic_type: 动态类型
            - content: 文本内容
            - raw: 原始 API 返回
            - fetched_at: 拉取时间
        """
        all_items: List[Dict[str, Any]] = []
        for uid in self.bili_accounts:
            try:
                items = self._fetch_bili_space(uid)
                all_items.extend(items)
                time.sleep(0.5)  # 礼貌延迟
            except Exception as e:
                self.logger.error(f"Error fetching B站 UID={uid}: {e}")

        self._save_cache()
        return all_items

    def _fetch_bili_space(self, uid: str, max_pages: int = 3) -> List[Dict[str, Any]]:
        """
        拉取 B站 用户空间动态，返回新动态列表。
        使用 offset 翻页，每次比较 dynamic_id 是否已处理过。
        """
        results: List[Dict[str, Any]] = []
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

    def _parse_bili_item(self, uid: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        从 B站 动态 item 中提取文本内容。
        支持类型：
            - 2/8: 投稿视频动态（标题 + 描述）
            - 4: 纯文字动态（快讯）
            - 1: 转发动态
            - 64: 专栏
        """
        try:
            dyn_id = str(item.get("id_str") or item.get("id", ""))
            dyn_type = item.get("type", 0)
            desc = item.get("desc", "") or ""  # 转发动态的文本

            # 获取账号名
            account_name = ""
            for u in self.bili_accounts:
                if u == uid:
                    # 从配置里找名字
                    pass  # 用 UID 代替即可

            content_parts: List[str] = []

            if dyn_type in (2, 8):  # 视频投稿
                card = item.get("card", {})
                if isinstance(card, str):
                    import json as _json
                    card = _json.loads(card)
                title = card.get("title", "")
                desc_text = card.get("desc", "")
                content_parts.append(f"[投稿视频] 标题：{title}")
                if desc_text:
                    content_parts.append(f"简介：{desc_text}")

            elif dyn_type == 4:  # 文字动态
                item_data = item.get("item", {})
                text = item_data.get("description", "") or item_data.get("content", "")
                content_parts.append(f"[文字动态] {text}")

            elif dyn_type == 1:  # 转发
                item_data = item.get("item", {})
                text = item_data.get("content", "") or desc
                content_parts.append(f"[转发动态] {text}")
                # 附带原动态信息
                origin = item.get("origin", {})
                if origin:
                    orig_desc = origin.get("desc", "") or ""
                    content_parts.append(f"原动态：{orig_desc[:200]}")

            elif dyn_type == 64:  # 专栏
                card = item.get("card", {})
                if isinstance(card, str):
                    import json as _json
                    try:
                        card = _json.loads(card)
                    except Exception:
                        card = {}
                title = card.get("title", "")
                summary = card.get("summary", "")
                content_parts.append(f"[专栏] 标题：{title} {summary}")

            else:
                # 其他类型，尝试提取 item.description
                item_data = item.get("item", {})
                text = item_data.get("description", "") if isinstance(item_data, dict) else ""
                if text:
                    content_parts.append(f"[动态类型{dyn_type}] {text}")

            # 提取图片链接（如有）
            pics = []
            item_data = item.get("item", {})
            if isinstance(item_data, dict):
                pic_list = item_data.get("pictures", []) or []
                for p in pic_list[:3]:
                    if isinstance(p, dict) and p.get("url"):
                        pics.append(p["url"])

            timestamp = item.get("timestamp", 0)
            dt_str = datetime.fromtimestamp(timestamp).isoformat() if timestamp else datetime.now().isoformat()

            return {
                "uid": uid,
                "account_name": account_name or f"bili_{uid}",
                "platform": "bilibili",
                "dynamic_id": dyn_id,
                "dynamic_type": dyn_type,
                "content": "\n".join(content_parts),
                "raw_content": "\n".join(content_parts)[:2000],
                "pics": pics,
                "publish_time": dt_str,
                "source_url": f"https://t.bilibili.com/{dyn_id}",
            }

        except Exception as e:
            self.logger.error(f"Error parsing B站 dynamic item: {e}")
            return None

    def fetch_weibo(self, uid: str) -> List[Dict[str, Any]]:
        """
        微博动态爬取（占位实现，需要配合 RSSHub 或微博 API）。
        暂时返回空列表。
        """
        self.logger.info("Weibo fetcher not yet implemented")
        return []
