from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import requests

from src.infrastructure.persistence.database.event_models import UnifiedEventType
from .types import OfficialDynamic
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.infrastructure.models.llm.module import LLMModule
    from src.infrastructure.models.vlm.module import VLMModule


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
        """
        下载图片并转换为 base64 编码的 JPEG 格式，返回 base64 字符串。
        如果下载或转换失败，返回 None。

        :param url: 图片的 URL
        :return: base64 编码的 JPEG 图片字符串，或 None
        """
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
            events.extend(await self.parse_one(item))
        return events

    async def parse_one(self, raw_item: OfficialDynamic) -> List[Dict[str, Any]]:
        content = (raw_item.content or "").strip()
        raw_content = raw_item.raw_content or content
        platform = getattr(raw_item, "platform", "bilibili")
        source_url = getattr(raw_item, "source_url", "")
        images = getattr(raw_item, "pics", []) or []

        if not content and not images:
            return []
        if self._is_merchandise_only(content):
            return []

        prompt_vars = {
            "today": datetime.now().strftime("%Y-%m-%d"),
            "publish_time": raw_item.publish_time,
            "content": content[:1500],
        }
        result: Optional[str] = None
        attempted_model = False

        if images and self.vlm_module is not None:
            image_b64 = await asyncio.to_thread(self._download_image_to_base64, images[0])
            if image_b64:
                attempted_model = True
                resp = await self.vlm_module.generate_response(image_b64, **prompt_vars)
                result = (resp or {}).get("content", "") if isinstance(resp, dict) else str(resp)
        if not result and self.llm_module is not None:
            attempted_model = True
            result = await self.llm_module.generate_response(**prompt_vars)

        if not result:
            if attempted_model:
                raise ValueError(f"Model returned an empty response for dynamic {raw_item.dynamic_id}")
            return self._rule_based_parse(raw_item, content, raw_content, platform, source_url)

        extracted = self._extract_json_array(result.strip())
        if not extracted:
            raise ValueError(f"Model returned no JSON array for dynamic {raw_item.dynamic_id}")

        try:
            parsed_list = json.loads(extracted)
        except json.JSONDecodeError:
            raise ValueError(f"Model returned invalid JSON for dynamic {raw_item.dynamic_id}: {extracted[:200]}")
        if not isinstance(parsed_list, list):
            raise ValueError(f"Model returned a non-list response for dynamic {raw_item.dynamic_id}")

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
            default_hour = 0 if event["event_type"] == UnifiedEventType.GENERAL.value else 19
            source_dates = self._extract_datetimes(
                content, self._parse_iso_datetime(raw_item.publish_time), default_hour=default_hour
            )
            performance_date = self._explicit_performance_date(content, self._parse_iso_datetime(raw_item.publish_time))
            if performance_date is not None and event["event_type"] == UnifiedEventType.CONCERT.value:
                if event["start_datetime"] is None or (
                    source_dates and event["start_datetime"].date() == source_dates[0].date()
                ):
                    event["start_datetime"] = performance_date
            if event["start_datetime"] is None:
                if not source_dates:
                    self.logger.warning(f"Skipping undated event in dynamic {raw_item.dynamic_id}")
                    continue
                event["start_datetime"] = source_dates[0]
            if self._is_ticket_date_mistaken_for_concert(content, event, source_dates):
                self.logger.warning(f"Skipping ticket sale date mistaken for concert in dynamic {raw_item.dynamic_id}")
                continue
            if event["end_datetime"] is None or event["end_datetime"].date() < event["start_datetime"].date():
                duration = timedelta(days=1, minutes=-1) if default_hour == 0 else timedelta(hours=2)
                event["end_datetime"] = event["start_datetime"] + duration
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
        text = content + raw_content
        if self._is_merchandise_only(text):
            return []
        concert_kws = ["演唱会", "演出", "专场", "live", "巡演"]
        livestream_kws = ["直播", "线上", "b站直播", "直播预告"]

        event_type = UnifiedEventType.GENERAL.value
        if any(kw in text for kw in concert_kws):
            event_type = UnifiedEventType.CONCERT.value
        elif any(kw in text for kw in livestream_kws):
            event_type = UnifiedEventType.LIVESTREAM.value

        source_dates = self._extract_datetimes(text, self._parse_iso_datetime(raw_item.publish_time))
        performance_date = self._explicit_performance_date(text, self._parse_iso_datetime(raw_item.publish_time))
        start_time = performance_date if event_type == UnifiedEventType.CONCERT.value and performance_date else None
        start_time = start_time or (source_dates[0] if source_dates else None)
        if event_type == UnifiedEventType.GENERAL.value or not start_time:
            return []
        if self._is_ticket_date_mistaken_for_concert(
            text, {"event_type": event_type, "start_datetime": start_time}, source_dates
        ):
            return []

        return [
            {
                "title": self._extract_title(text, event_type),
                "description": text[:200],
                "event_type": event_type,
                "start_datetime": start_time,
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
    def _is_merchandise_only(text: str) -> bool:
        selling_goods = re.search(r"(?:周边|商品|收藏集|装扮|手办).{0,30}(?:开售|发售|售卖|上架|销售)", text)
        actual_activity = re.search(r"演出时间|开演时间|直播时间|活动时间|参与方式|征稿|投稿", text)
        return bool(selling_goods and not actual_activity)

    @staticmethod
    def _is_ticket_date_mistaken_for_concert(text: str, event: Dict[str, Any], source_dates: List[datetime]) -> bool:
        if event["event_type"] != UnifiedEventType.CONCERT.value or not source_dates:
            return False
        if not re.search(r"开票|售票|购票|门票|票务", text):
            return False
        if re.search(r"演出时间|演出日期|开演|举行时间", text):
            return False
        return event["start_datetime"].date() == source_dates[0].date()

    @classmethod
    def _explicit_performance_date(cls, text: str, published_at: Optional[datetime]) -> Optional[datetime]:
        marker = re.search(r"演出时间|演出日期|开演时间|举行时间", text)
        if marker is None:
            return None
        dates = cls._extract_datetimes(text[marker.end() :], published_at)
        return dates[0] if dates else None

    @staticmethod
    def _extract_datetimes(text: str, published_at: Optional[datetime], default_hour: int = 19) -> List[datetime]:
        reference = published_at or datetime.now()
        pattern = re.compile(
            r"(?:(?P<year>\d{4})[年/-])?(?P<month>\d{1,2})[月/-](?P<day>\d{1,2})(?:日)?"
            r"(?:[T\s]*(?P<hour>\d{1,2})(?:[:：点时](?P<minute>\d{1,2})?)?(?:分)?)?"
        )
        found: List[datetime] = []
        for match in pattern.finditer(text):
            try:
                year = int(match.group("year")) if match.group("year") else reference.year
                month, day = int(match.group("month")), int(match.group("day"))
                hour = int(match.group("hour")) if match.group("hour") else default_hour
                minute = int(match.group("minute")) if match.group("minute") else 0
                value = datetime(year, month, day, 0 if hour == 24 else hour, minute)
                if hour == 24:
                    value += timedelta(days=1)
                if not match.group("year") and value.date() < reference.date() - timedelta(days=30):
                    value = value.replace(year=year + 1)
                found.append(value)
            except ValueError:
                continue
        return found

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
