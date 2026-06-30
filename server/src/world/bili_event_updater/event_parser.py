from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import requests

from src.system.database.event_models import UnifiedEventType
from .types import OfficialDynamic
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.utils.llm.llm_module import LLMModule
    from src.utils.vision.vlm_module import VLMModule



VLM_MAX_IMAGE_PIXELS = 6_000_000


class EventParser:
    """Parse official dynamics into structured world events."""

    def __init__(
        self,
        llm_module: "LLMModule | None" = None,
        vlm_module: "VLMModule | None" = None,
    ) -> None:
        self.logger = get_logger(__name__)
        self.llm_module = llm_module
        self.vlm_module = vlm_module

    def _download_image_to_base64(self, url: str) -> Optional[str]:
        '''
        下载图片并转换为 base64 编码的 JPEG 格式，返回 base64 字符串。
        如果下载或转换失败，返回 None。

        :param url: 图片的 URL
        :return: base64 编码的 JPEG 图片字符串，或 None
        '''
        try:
            if url.startswith("//"):
                url = "https:" + url
            elif not url.startswith(("http://", "https://")):
                url = "https://" + url

            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            if not resp.content:
                return None

            from PIL import Image, ImageOps
            import io

            original_max_pixels = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = None
            try:
                img = Image.open(io.BytesIO(resp.content))
            finally:
                Image.MAX_IMAGE_PIXELS = original_max_pixels

            img = ImageOps.exif_transpose(img)
            width, height = img.size
            if width > 0 and height > 0:
                scale_by_pixels = (VLM_MAX_IMAGE_PIXELS / float(width * height)) ** 0.5
                scale = min(1.0, scale_by_pixels)
                if scale < 1.0:
                    img = img.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            output = io.BytesIO()
            img.save(output, format="JPEG", quality=85)
            b64 = base64.b64encode(output.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"
        except Exception as exc:
            self.logger.warning(f"Failed to download/convert image {url[:60]}: {exc}")
            return None

    async def parse_dynamics(self, raw_items: List[OfficialDynamic]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        for item in raw_items:
            try:
                events.extend(await self.parse_one(item))
            except Exception as exc:
                self.logger.error(f"Error parsing dynamic {item.dynamic_id}: {exc}")
        return events

    async def parse_one(self, raw_item: OfficialDynamic) -> List[Dict[str, Any]]:
        content = (raw_item.content or "").strip()
        raw_content = raw_item.raw_content or content
        platform = getattr(raw_item, "platform", "bilibili")
        source_url = getattr(raw_item, "source_url", "")
        images = getattr(raw_item, "pics", []) or []

        if not content and not images:
            return []

        prompt_vars = {
            "today": datetime.now().strftime("%Y-%m-%d"),
            "content": content[:1500],
        }
        result: Optional[str] = None

        if images and self.vlm_module is not None:
            image_b64 = self._download_image_to_base64(images[0])
            if image_b64:
                resp = await self.vlm_module.generate_response(image_b64, **prompt_vars)
                result = (resp or {}).get("content", "") if isinstance(resp, dict) else str(resp)
        elif self.llm_module is not None:
            result = await self.llm_module.generate_response(**prompt_vars)

        if not result:
            return self._rule_based_parse(raw_item, content, raw_content, platform, source_url)

        extracted = self._extract_json_array(result.strip())
        if not extracted:
            return []

        try:
            parsed_list = json.loads(extracted)
        except json.JSONDecodeError:
            self.logger.warning(f"Model returned invalid JSON: {extracted[:200]}")
            return []
        if not isinstance(parsed_list, list):
            return []

        events: List[Dict[str, Any]] = []
        for item in parsed_list:
            if not isinstance(item, dict):
                continue
            event = {
                    "title": str(item.get("title", ""))[:100],
                    "character": raw_item.character or "luotianyi",
                    "description": str(item.get("description", ""))[:500],
                    "event_type": self._normalize_event_type(str(item.get("event_type", "general"))),
                    "start_datetime": self._parse_iso_datetime(item.get("start_time")),
                    "end_datetime": self._parse_iso_datetime(item.get("end_time")),
                    "source_url": source_url,
                    "source_platform": platform,
                }
            if event["start_datetime"] is None:
                event["start_datetime"] = self._parse_iso_datetime(raw_item.publish_time)
                event["end_datetime"] = event["start_datetime"] + timedelta(hours=2)
            if event["end_datetime"] is None:
                event["end_datetime"] = event["start_datetime"] + timedelta(days=1)
            events.append(event)
        return events

    def _rule_based_parse(
        self,
        raw_item: OfficialDynamic,
        content: str,
        raw_content: str,
        platform: str,
        source_url: str,
    ) -> List[Dict[str, Any]]:
        _ = raw_item
        text = content + raw_content
        concert_kws = ["演唱会", "演出", "专场", "live", "巡演"]
        livestream_kws = ["直播", "线上", "b站直播", "直播预告"]

        event_type = UnifiedEventType.GENERAL.value
        if any(kw in text for kw in concert_kws):
            event_type = UnifiedEventType.CONCERT.value
        elif any(kw in text for kw in livestream_kws):
            event_type = UnifiedEventType.LIVESTREAM.value

        start_time = self._extract_time(text)
        if event_type == UnifiedEventType.GENERAL.value or not start_time:
            return []

        return [
            {
                "title": self._extract_title(text, event_type),
                "description": text[:200],
                "event_type": event_type,
                "start_datetime": self._parse_iso_datetime(start_time),
                "end_datetime": None,
                "source_url": source_url,
                "source_platform": platform,
                "character": raw_item.character or "luotianyi",
            }
        ]

    @staticmethod
    def _normalize_event_type(value: str) -> str:
        try:
            return UnifiedEventType(value).value
        except ValueError:
            return UnifiedEventType.GENERAL.value

    @staticmethod
    def _parse_iso_datetime(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    @staticmethod
    def _extract_json_array(text: str) -> str:
        text = re.sub(r"```[a-zA-Z]*\n?", "", text).strip()
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return ""

    @staticmethod
    def _extract_time(text: str) -> str:
        now = datetime.now()
        patterns = [
            r"(\d{4})-(\d{1,2})-(\d{1,2})\s*(\d{1,2}):(\d{2})",
            r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})",
            r"(\d{4})-(\d{1,2})-(\d{1,2})",
            r"(\d{1,2})月(\d{1,2})日",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            groups = match.groups()
            try:
                if len(groups) == 5:
                    return f"{groups[0]}-{groups[1].zfill(2)}-{groups[2].zfill(2)}T{groups[3].zfill(2)}:{groups[4]}:00"
                if len(groups) == 4:
                    year = now.year + (1 if int(groups[0]) < now.month else 0)
                    return f"{year}-{int(groups[0]):02d}-{int(groups[1]):02d}T{int(groups[2]):02d}:{groups[3]}:00"
                if len(groups) == 3:
                    return f"{groups[0]}-{groups[1].zfill(2)}-{groups[2].zfill(2)}T19:00:00"
                if len(groups) == 2:
                    year = now.year + (1 if int(groups[0]) < now.month else 0)
                    return f"{year}-{int(groups[0]):02d}-{int(groups[1]):02d}T19:00:00"
            except Exception:
                continue
        return ""

    @staticmethod
    def _extract_title(text: str, event_type: str) -> str:
        prefix = {
            UnifiedEventType.CONCERT.value: "演唱会",
            UnifiedEventType.LIVESTREAM.value: "直播",
        }.get(event_type, "活动")
        first = re.split(r"[。！？!?]", text.strip())[0].strip() if text.strip() else ""
        if len(first) > 30:
            first = first[:30] + "..."
        return f"{prefix}: {first}"
