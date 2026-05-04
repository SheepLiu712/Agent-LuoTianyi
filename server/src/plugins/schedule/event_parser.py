"""
事件解析器：使用 LLM 从原始动态文本中提取结构化事件信息。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.utils.llm.llm_api_interface import LLMAPIFactory, LLMAPIInterface
from src.utils.logger import get_logger
from .event_models import EventType, ScheduleEvent

logger = get_logger(__name__)

# 构建 LLM prompt 的模板
EVENT_PARSE_PROMPT = """\
你是一个专业的信息提取助手。我会给你一段洛天依官方账号发布的动态内容，请你判断其中是否包含值得提醒的官方活动信息。

【活动类型定义】
- collaboration: 品牌联动、商业合作、跨界联动
- concert: 演唱会、线下演出、专场演出
- livestream: 直播、线上演出、线上发布会
- release: 新歌发布、专辑发布、MV发布
- anniversary: 周年庆、纪念日、生日相关
- general: 一般公告、日常动态（不属于上述类型，或没有明确的未来活动时间）

【提取规则】
1. 如果动态中含有明确的**未来活动时间**（如演唱会日期、直播时间、联动开始时间），归类为对应类型，并将时间提取出来。
2. 如果动态是日常闲聊、感谢、无明确活动时间的公告，归类为 "general"，且不需要设置活动时间。
3. 时间尽量精确到分钟；如果只有日期，默认设为当天 19:00。
4. 如果提到结束时间，同样提取；否则留空。

【输出格式】
如果动态中包含可提醒的活动事件，输出一个 JSON 数组，每个元素包含：
- "event_type": 上述类型之一
- "title": 活动标题（简洁，20字以内）
- "description": 活动描述（100字以内）
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
    """使用 LLM 从原始动态文本中解析出结构化事件。"""

    def __init__(self, llm_config: Optional[Dict[str, Any]] = None):
        self.llm_client: Optional[LLMAPIInterface] = None
        if llm_config:
            try:
                self.llm_client = LLMAPIFactory.create_interface(llm_config)
                logger.info("EventParser LLM client initialized")
            except Exception as e:
                logger.warning(f"Failed to init EventParser LLM client: {e}")

    async def parse_dynamics(
        self, raw_items: List[Dict[str, Any]]
    ) -> List[ScheduleEvent]:
        """
        批量解析多条原始动态，返回结构化事件列表。
        每条动态可能产生 0～N 个事件。
        """
        events: List[ScheduleEvent] = []
        for item in raw_items:
            try:
                parsed = await self.parse_one(item)
                events.extend(parsed)
            except Exception as e:
                logger.error(f"Error parsing dynamic {item.get('dynamic_id', '')}: {e}")
        return events

    async def parse_one(
        self, raw_item: Dict[str, Any]
    ) -> List[ScheduleEvent]:
        """解析单条动态，返回事件列表。"""
        content = raw_item.get("content", "").strip()
        raw_content = raw_item.get("raw_content", content)
        platform = raw_item.get("platform", "bilibili")
        source_url = raw_item.get("source_url", "")

        if not content:
            return []

        # 先做简单规则过滤：标题党/日常关键词 → 直接跳过（减少 LLM 调用）
        if self._is_likely_daily_chat(content):
            logger.debug(f"Skipping daily chat: {content[:50]}...")
            return []

        if self.llm_client is None:
            # 无 LLM 时退化为规则解析
            return self._rule_based_parse(raw_item, content, raw_content, platform, source_url)

        # 调用 LLM
        prompt = EVENT_PARSE_PROMPT.format(
            today=datetime.now().strftime("%Y-%m-%d"),
            content=content[:1500],  # 控制长度
        )
        try:
            result = await self.llm_client.generate_response(prompt, use_json=False)
            result = (result or "").strip()

            # 提取 JSON 数组（容错处理）
            result = self._extract_json_array(result)
            if not result:
                return []

            parsed_list = json.loads(result)
            if not isinstance(parsed_list, list):
                return []

            events: List[ScheduleEvent] = []
            for p in parsed_list:
                if not isinstance(p, dict):
                    continue
                evt_type_str = p.get("event_type", "general")
                try:
                    evt_type = EventType(evt_type_str)
                except ValueError:
                    evt_type = EventType.GENERAL

                event = ScheduleEvent(
                    id="",
                    event_type=evt_type,
                    title=p.get("title", "")[:100],
                    description=p.get("description", "")[:500],
                    start_time=p.get("start_time", ""),
                    end_time=p.get("end_time", "") or None,
                    location=p.get("location", "")[:200],
                    source_url=source_url,
                    source_platform=platform,
                    raw_content=raw_content[:2000],
                    status=ScheduleEvent.__dataclass_fields__["status"].default,
                )
                events.append(event)

            logger.info(f"LLM parsed {len(events)} event(s) from dynamic {raw_item.get('dynamic_id', '')}")
            return events

        except json.JSONDecodeError as e:
            logger.warning(f"LLM returned invalid JSON: {result[:200]}")
            return []
        except Exception as e:
            logger.error(f"LLM parse error: {e}")
            return self._rule_based_parse(raw_item, content, raw_content, platform, source_url)

    def _rule_based_parse(
        self,
        raw_item: Dict[str, Any],
        content: str,
        raw_content: str,
        platform: str,
        source_url: str,
    ) -> List[ScheduleEvent]:
        """
        规则降级解析：从文本中匹配关键词提取简单事件。
        仅处理明显包含时间词的活动公告。
        """
        # 演唱会/演出关键词
        concert_kws = ["演唱会", "演出", "专场", "live", "巡演"]
        release_kws = ["新歌", "新曲", "发布", "上线", "首发", "专辑"]
        collab_kws = ["联动", "合作", "联名", "x", "×", "×"]
        livestream_kws = ["直播", "线上", "b 站直播", "直播预告"]

        text = content + raw_content
        evt_type = EventType.GENERAL

        if any(kw in text for kw in concert_kws):
            evt_type = EventType.CONCERT
        elif any(kw in text for kw in release_kws):
            evt_type = EventType.RELEASE
        elif any(kw in text for kw in collab_kws):
            evt_type = EventType.COLLABORATION
        elif any(kw in text for kw in livestream_kws):
            evt_type = EventType.LIVESTREAM

        # 尝试提取时间
        start_time = self._extract_time(text)

        if evt_type == EventType.GENERAL or not start_time:
            return []

        title = self._extract_title(text, evt_type)
        return [
            ScheduleEvent(
                id="",
                event_type=evt_type,
                title=title,
                description=text[:200],
                start_time=start_time,
                end_time=None,
                location="",
                source_url=source_url,
                source_platform=platform,
                raw_content=raw_content[:2000],
                status=ScheduleEvent.__dataclass_fields__["status"].default,
            )
        ]

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

    def _extract_title(self, text: str, evt_type: EventType) -> str:
        """从文本中提取标题。"""
        type_prefix = {
            EventType.CONCERT: "演唱会",
            EventType.LIVESTREAM: "直播",
            EventType.COLLABORATION: "联动",
            EventType.RELEASE: "新歌发布",
            EventType.ANNIVERSARY: "纪念日",
            EventType.GENERAL: "活动",
        }.get(evt_type, "活动")

        # 取第一句话作为标题
        sentences = re.split(r"[。！？!?]", text.strip())
        first = sentences[0].strip() if sentences else text[:30]
        if len(first) > 30:
            first = first[:30] + "..."
        return f"{type_prefix}: {first}"
