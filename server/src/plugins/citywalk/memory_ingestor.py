import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ...database.vector_store import Document, VectorStore
from ...utils.logger import get_logger
from .types import CitywalkSessionResult


class CitywalkMemoryIngestor:
    def __init__(
        self,
        citywalk_config: Dict[str, Any],
        vector_store: VectorStore,
        llm_client: Optional[Any] = None,
    ):
        self.logger = get_logger(__name__)
        self.vector_store = vector_store

        decision_cfg = citywalk_config.get("decision", {})
        llm_cfg = decision_cfg.get("llm", {})
        self.model = str(llm_cfg.get("model", "qwen3.5-plus"))
        self.base_url = str(llm_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
        self.temperature = float(llm_cfg.get("temperature", 0.2))
        self.max_tokens = int(llm_cfg.get("max_tokens", 512))
        self.request_timeout = float(llm_cfg.get("request_timeout_seconds", 45))
        self.memory_user_id = str(citywalk_config.get("memory_user_id", "__citywalk__"))

        self.client = llm_client
        api_key = str(llm_cfg.get("api_key", "")).strip()
        if self.client is None and api_key:
            self.client = OpenAI(base_url=self.base_url, api_key=api_key)

    def _parse_json_response(self, raw_response: str) -> Dict[str, Any]:
        text = (raw_response or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text or "{}")

    def _fallback_timeline(self, result: CitywalkSessionResult) -> List[str]:
        lines: List[str] = []
        for event in result.events:
            t = event.timestamp.strftime("%H:%M") if isinstance(event.timestamp, datetime) else "未知时间"
            place = event.poi.name if event.poi else "未知地点"
            summary = (event.poi_activity or event.environment_feedback or event.activity or "有新的见闻").strip()
            lines.append(f"{t} {place} {summary}")
        return lines

    def split_diary_to_timeline(self, result: CitywalkSessionResult) -> List[str]:
        fallback = self._fallback_timeline(result)
        if self.client is None:
            return fallback

        event_lines = []
        for event in result.events:
            event_lines.append(
                f"{event.poi.name} | {event.poi_activity or event.activity or event.environment_feedback}"
            )

        prompt = (
            "请把下面的城市漫步流水账和事件素材拆成短句。\n"
            "每条短句必须仅包含: 地点+事件，不要加入主观分析。\n"
            "只输出JSON对象，格式如下:\n"
            "{\"timeline\":[\"南锣鼓巷 看到街头艺人演奏\",\"某店 吃了某食物\"]}\n"
            f"城市: {result.city}\n"
            f"流水账: {result.diary_text or '无'}\n"
            f"事件素材:\n{chr(10).join(event_lines) or '无'}"
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是信息抽取助手，只输出JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format={"type": "json_object"},
                timeout=self.request_timeout,
                extra_body={"enable_thinking": False},
            )
            data = self._parse_json_response(resp.choices[0].message.content or "{}")
            timeline = data.get("timeline", [])
            if not isinstance(timeline, list):
                return fallback
            cleaned = [str(x).strip() for x in timeline if str(x).strip()]
            return cleaned or fallback
        except Exception as exc:
            self.logger.warning("城市漫步记忆拆分失败，使用事件回退: %s", exc)
            return fallback

    def ingest_session(self, result: CitywalkSessionResult) -> int:
        lines = self.split_diary_to_timeline(result)
        if not lines:
            return 0

        event_date = result.created_at.strftime("%Y-%m-%d") if isinstance(result.created_at, datetime) else datetime.now().strftime("%Y-%m-%d")
        docs: List[Document] = []
        for line in lines:
            docs.append(
                Document(
                    content=line,
                    metadata={
                        "user_id": self.memory_user_id,
                        "source": "citywalk",
                        "is_citywalk_data": True,
                        "memory_type": "citywalk_memory",
                        "citywalk_date": event_date,
                        "city": result.city,
                    },
                )
            )

        self.vector_store.add_documents(docs)
        return len(docs)
