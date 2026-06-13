"""
事件解析器：使用 VLM（视觉语言模型）从原始动态文本+图片中提取结构化事件信息。
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from src.utils.llm.llm_api_interface import LLMAPIFactory, LLMAPIInterface
from src.utils.vision.vlm_api_interface import VLMAPIFactory, VLMAPIInterface
from src.utils.logger import get_logger
from .event_models import UnifiedEventType, OfficialDynamic

logger = get_logger(__name__)

# VLM image handling limits.
VLM_MAX_IMAGE_PIXELS = 6_000_000  # e.g. 3000x2000

# 构建 LLM prompt 的模板
EVENT_PARSE_PROMPT = """\
你是一个专业的信息提取助手。我会给你一段洛天依官方账号发布的动态内容，请你判断其中是否包含值得提醒的官方活动信息。

【活动类型定义】
- concert: 演唱会、线下演出、专场演出
- livestream: 直播、线上演出、线上发布会
- general: 日常动态，包括图片分享、歌曲发布等

【提取规则】
1. 如果动态中含有明确的**未来活动**，归类为对应类型，并将时间提取出来。
2. 如果动态是日常闲聊、感谢，或者歌曲分享，认为不是活动，输出 []。
3. 时间尽量精确到分钟；如果直播、演唱会只有开始时间没有结束时间，结束时间默认为开始时间后两小时；如果有明确结束时间则按实际提取。
5. 如果有多场活动（如巡回演唱会），则每个单独成一个事件输出；
6. general类型的开始和结束时间可以留空（""），因为它们不需要提醒。

【输出格式】
如果动态中包含可提醒的活动事件，输出一个 JSON 数组，每个元素包含：
- "event_type": 上述类型之一
- "title": 活动标题（简洁，20字以内）
- "description": 活动描述（40字以内）
- "start_time": 开始时间（ISO 8601，如 2025-05-20T19:00:00）
- "end_time": 结束时间（ISO 8601，无则留 ""）
- "location": 地点（无则留 ""）

如果没有任何可提醒的活动（纯闲聊/日常），输出 []。

【当前日期参考】today={today}

【动态内容】
{content}

请只输出 JSON 数组，不要输出其他说明文字。\
"""


class EventParser:
    """使用 VLM 从原始动态文本+图片中解析出结构化事件。"""

    def __init__(
        self,
        llm_config: Optional[Dict[str, Any]] = None,
        vlm_config: Optional[Dict[str, Any]] = None,
    ):
        self.llm_client: Optional[LLMAPIInterface] = None
        self.vlm_client: Optional[VLMAPIInterface] = None
        if llm_config:
            try:
                self.llm_client = LLMAPIFactory.create_interface(llm_config)
                logger.info("EventParser LLM client initialized")
            except Exception as e:
                logger.warning(f"Failed to init EventParser LLM client: {e}")
        if vlm_config:
            try:
                self.vlm_client = VLMAPIFactory.create_interface(vlm_config)
                logger.info("EventParser VLM client initialized")
            except Exception as e:
                logger.warning(f"Failed to init EventParser VLM client: {e}")

    def _download_image_to_base64(self, url: str) -> Optional[str]:
        """
        下载图片并转换为 base64 data URI（支持 VLM 调用）。
        B站图片通常是 http:// 协议，VLM API 可能无法直接访问，需要本地下载转码。
        """
        try:
            # 确保 URL 有 scheme；B站可能返回无 scheme 的协议相对 URL
            if url.startswith("//"):
                url = "https:" + url
            elif not url.startswith(("http://", "https://")):
                url = "https://" + url
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            img_bytes = resp.content
            if not img_bytes:
                logger.warning(f"Empty image content from {url[:60]}")
                return None
            # 用 PIL 统一转 JPEG
            from PIL import Image, ImageOps
            import io
            # Allow large images, then downscale for VLM to avoid huge payloads.
            original_max_pixels = Image.MAX_IMAGE_PIXELS
            Image.MAX_IMAGE_PIXELS = None
            try:
                img = Image.open(io.BytesIO(img_bytes))
            finally:
                Image.MAX_IMAGE_PIXELS = original_max_pixels
            img = ImageOps.exif_transpose(img)
            width, height = img.size
            if width > 0 and height > 0:
                pixel_count = width * height
                scale_by_pixels = (VLM_MAX_IMAGE_PIXELS / float(pixel_count)) ** 0.5
                scale = min(1.0, scale_by_pixels)
                if scale < 1.0:
                    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
                    img = img.resize(new_size, Image.LANCZOS)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            output = io.BytesIO()
            img.save(output, format="JPEG", quality=85)
            processed_bytes = output.getvalue()
            b64 = base64.b64encode(processed_bytes).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"
        except Exception as e:
            logger.warning(f"Failed to download/convert image {url[:60]}: {e}")
            return None

    async def _call_vlm(
        self, prompt: str, image_base64: Optional[str] = None
    ) -> Optional[str]:
        """
        调用 VLM 做图文理解。
        - 有 image_base64: 正常多模态调用
        - 无 image_base64: 降级为纯文本 VLM 调用（直接使用底层 OpenAI client）
        """
        if self.vlm_client is None:
            return None
        try:
            if image_base64:
                return await self.vlm_client.generate_response(prompt, image_base64)
            else:
                # VLM 无图片时的纯文本调用
                vlm = self.vlm_client
                if hasattr(vlm, "client") and hasattr(vlm, "model"):
                    def _do_text_only():
                        return vlm.client.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model=vlm.model,
                            max_tokens=getattr(vlm, "max_tokens", 4096),
                            temperature=getattr(vlm, "temperature", 0.7),
                            top_p=getattr(vlm, "top_p", 0.9),
                            response_format={"type": "json_object"},
                        )
                    ret = await asyncio.to_thread(_do_text_only)
                    if ret.choices:
                        return ret.choices[0].message.content or ""
                logger.warning("VLM client has no underlying client for text-only call")
                return None
        except Exception as e:
            logger.warning(f"VLM call failed: {e}")
            return None

    async def parse_dynamics(
        self, raw_items: List[OfficialDynamic]
    ) -> List[Dict[str, Any]]:
        """
        批量解析多条原始动态，返回结构化事件 dict 列表。
        每条动态可能产生 0～N 个事件。
        返回的 dict 包含 title, description, event_type, start_datetime, end_datetime, source_url, source_platform。
        """
        events: List[Dict[str, Any]] = []
        for item in raw_items:
            try:
                parsed = await self.parse_one(item)
                events.extend(parsed)
            except Exception as e:
                logger.error(f"Error parsing dynamic {item.dynamic_id}: {e}")
        return events

    async def parse_one(
        self, raw_item: OfficialDynamic
    ) -> List[Dict[str, Any]]:
        """解析单条动态，返回事件 dict 列表。"""
        print(f"Parsing dynamic {raw_item.dynamic_id} with content: {raw_item.content[:50]}...")
        content = raw_item.content.strip()
        raw_content = raw_item.raw_content if raw_item.raw_content else content
        platform = raw_item.platform if hasattr(raw_item, 'platform') else "bilibili"
        source_url = raw_item.source_url if hasattr(raw_item, 'source_url') else ""

        if not content and not raw_item.pics:
            return []

        # # 先做简单规则过滤：标题党/日常关键词 → 直接跳过（减少模型调用）
        # if self._is_likely_daily_chat(content):
        #     logger.debug(f"Skipping daily chat: {content[:50]}...")
        #     return []

        # 优先使用 VLM（图文理解），特别是当有图片时
        prefer_vlm = self.vlm_client is not None
        images = getattr(raw_item, "pics", [])

        # 构建 prompt
        prompt = EVENT_PARSE_PROMPT.format(
            today=datetime.now().strftime("%Y-%m-%d"),
            content=content[:1500],
        )

        if prefer_vlm:
            # --- VLM 调用 ---
            if images:
                # 有图片：下载第一张图并转 base64
                logger.info(f"Using VLM with image for dynamic {raw_item.dynamic_id}")
                image_b64 = self._download_image_to_base64(images[0])
                result = await self._call_vlm(prompt, image_b64)
            else:
                # 无图片：文本方式调用 VLM
                logger.info(f"Using VLM text-only for dynamic {raw_item.dynamic_id}")
                result = await self._call_vlm(prompt)
        elif self.llm_client is not None:
            # --- LLM 降级 ---
            logger.info(f"Using LLM for dynamic {raw_item.dynamic_id}")
            try:
                result = await self.llm_client.generate_response(prompt, use_json=True)
            except Exception as e:
                logger.warning(f"LLM call failed for {raw_item.dynamic_id}: {e}")
                result = None
        else:
            # 无任何模型可用时退化为规则解析
            return self._rule_based_parse(raw_item, content, raw_content, platform, source_url)

        # --- 解析 VLM/LLM 返回 ---
        if not result:
            logger.warning(f"Empty result from model for dynamic {raw_item.dynamic_id}, fallback to rule-based")
            return self._rule_based_parse(raw_item, content, raw_content, platform, source_url)

        result = result.strip()
        # 提取 JSON 数组（容错处理）
        result = self._extract_json_array(result)
        if not result:
            return []

        try:
            parsed_list = json.loads(result)
            if not isinstance(parsed_list, list):
                return []

            events: List[Dict[str, Any]] = []
            for p in parsed_list:
                if not isinstance(p, dict):
                    continue
                evt_type_str = p.get("event_type", "general")
                try:
                    evt_type = UnifiedEventType(evt_type_str)
                except ValueError:
                    evt_type = UnifiedEventType.GENERAL

                start_time_str = p.get("start_time", "")
                end_time_str = p.get("end_time", "")
                start_dt = None
                end_dt = None
                try:
                    if start_time_str:
                        start_dt = datetime.fromisoformat(start_time_str)
                except Exception:
                    pass
                try:
                    if end_time_str:
                        end_dt = datetime.fromisoformat(end_time_str)
                except Exception:
                    pass

                events.append({
                    "title": p.get("title", "")[:100],
                    "description": p.get("description", "")[:500],
                    "event_type": evt_type.value,
                    "start_datetime": start_dt,
                    "end_datetime": end_dt,
                    "source_url": source_url,
                    "source_platform": platform,
                })

            logger.info(f"VLM/LLM parsed {len(events)} event(s) from dynamic {raw_item.dynamic_id}")
            return events

        except json.JSONDecodeError as e:
            logger.warning(f"Model returned invalid JSON: {result[:200]}")
            return []
        except Exception as e:
            logger.error(f"Model parse error: {e}")
            return self._rule_based_parse(raw_item, content, raw_content, platform, source_url)

    def _rule_based_parse(
        self,
        raw_item: OfficialDynamic,
        content: str,
        raw_content: str,
        platform: str,
        source_url: str,
    ) -> List[Dict[str, Any]]:
        """
        规则降级解析：从文本中匹配关键词提取简单事件。
        仅处理明显包含时间词的活动公告。
        """
        concert_kws = ["演唱会", "演出", "专场", "live", "巡演"]
        release_kws = ["新歌", "新曲", "发布", "上线", "首发", "专辑"]
        collab_kws = ["联动", "合作", "联名", "x", "×", "×"]
        livestream_kws = ["直播", "线上", "b 站直播", "直播预告"]

        text = content + raw_content
        evt_type_str = UnifiedEventType.GENERAL.value

        if any(kw in text for kw in concert_kws):
            evt_type_str = UnifiedEventType.CONCERT.value
        elif any(kw in text for kw in release_kws):
            evt_type_str = UnifiedEventType.GENERAL.value
        elif any(kw in text for kw in collab_kws):
            evt_type_str = UnifiedEventType.GENERAL.value
        elif any(kw in text for kw in livestream_kws):
            evt_type_str = UnifiedEventType.LIVESTREAM.value

        start_time = self._extract_time(text)

        if evt_type_str == UnifiedEventType.GENERAL.value or not start_time:
            return []

        try:
            start_dt = datetime.fromisoformat(start_time)
        except Exception:
            start_dt = None

        title = self._extract_title(text, evt_type_str)
        return [{
            "title": title,
            "description": text[:200],
            "event_type": evt_type_str,
            "start_datetime": start_dt,
            "end_datetime": None,
            "source_url": source_url,
            "source_platform": platform,
        }]

    def _is_likely_daily_chat(self, text: str) -> bool:
        """快速判断是否为日常闲聊动态（不需要 LLM 解析）。"""
        daily_kws = [
            "谢谢大家", "感谢", "好开心", "好喜欢", "今天",
            "分享了", "转发", "生日快乐", "早点睡", "晚安",
        ]
        # 如果同时不包含任何活动关键词，认为是日常
        event_kws = [
            "演唱会", "直播", "联动", "合作", "发布", "上线",
            "活动", "专场", "巡演", "发布会",
        ]
        has_event_kw = any(kw in text for kw in event_kws)
        return (not has_event_kw) and any(kw in text for kw in daily_kws)

    def _extract_json_array(self, text: str) -> str:
        """从 LLM 输出中提取 JSON 数组部分。"""
        # 去掉 ```json ... ``` 包裹
        text = re.sub(r"```[a-z]*\n?", "", text)
        text = text.strip()
        # 找到第一个 [ 和最后一个 ]
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            return text[start : end + 1]
        return ""

    def _extract_time(self, text: str) -> str:
        """尝试从文本中提取时间，返回 ISO 8601 字符串。"""
        now = datetime.now()
        # 匹配 yyyy-mm-dd HH:MM 或 mm-dd HH:MM
        patterns = [
            r"(\d{4})-(\d{1,2})-(\d{1,2})\s*(\d{1,2}):(\d{2})",
            r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})",
            r"(\d{4})-(\d{1,2})-(\d{1,2})",
            r"(\d{1,2})月(\d{1,2})日",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                try:
                    groups = m.groups()
                    if len(groups) >= 5:  # yyyy-mm-dd HH:MM
                        return f"{groups[0]}-{groups[1].zfill(2)}-{groups[2].zfill(2)}T{groups[3].zfill(2)}:{groups[4]}:00"
                    elif len(groups) == 4:  # mm-dd HH:MM 或 mm月dd日 HH:MM
                        year = now.year
                        month = int(groups[0])
                        day = int(groups[1])
                        hour = int(groups[2])
                        minute = int(groups[3])
                        # 跨年处理
                        if month < now.month:
                            year += 1
                        return f"{year}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00"
                    elif len(groups) == 3:  # yyyy-mm-dd
                        return f"{groups[0]}-{groups[1].zfill(2)}-{groups[2].zfill(2)}T19:00:00"
                    elif len(groups) == 2:  # mm月dd日
                        year = now.year
                        month = int(groups[0])
                        day = int(groups[1])
                        if month < now.month:
                            year += 1
                        return f"{year}-{month:02d}-{day:02d}T19:00:00"
                except Exception:
                    pass
        return ""

    def _extract_title(self, text: str, evt_type_str: str) -> str:
        """从文本中提取标题。"""
        type_prefix = {
            UnifiedEventType.CONCERT.value: "演唱会",
            UnifiedEventType.LIVESTREAM.value: "直播",
            UnifiedEventType.GENERAL.value: "活动",
        }.get(evt_type_str, "活动")

        # 取第一句话作为标题
        sentences = re.split(r"[。！？!?]", text.strip())
        first = sentences[0].strip() if sentences else text[:30]
        if len(first) > 30:
            first = first[:30] + "..."
        return f"{type_prefix}: {first}"
