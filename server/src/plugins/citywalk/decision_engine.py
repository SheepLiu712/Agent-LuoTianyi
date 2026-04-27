import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ...utils.logger import get_logger
from .errors import LLMDecisionError
from .types import CitywalkEvent, CitywalkState, POI


@dataclass
class DecisionResult:
    action_name: str
    feeling: str
    reason: str
    search_category: str = ""
    search_type_codes: str = ""
    goto_poi_name: str = ""
    act_here_text: str = ""
    strategy_phase: str = ""
    raw_response: str = ""
    # backward-compatible fields
    action: str = ""
    poi_index: int = 0
    activity: str = ""
    activity_duration_min: int = 20
    action_category: str = ""
    custom_action: str = ""

    def __dict__(self):
        return {
            "action_name": self.action_name,
            "feeling": self.feeling,
            "reason": self.reason,
            "search_category": self.search_category,
            "search_type_codes": self.search_type_codes,
            "goto_poi_name": self.goto_poi_name,
            "act_here_text": self.act_here_text,
            "strategy_phase": self.strategy_phase,
        }


class CitywalkDecisionEngine:
    def __init__(self, config: Dict[str, Any], llm_client: Optional[Any] = None):
        self.logger = get_logger(__name__)
        self.config = config

        sess_cfg = config.get("session", {})
        self.activity_min = int(sess_cfg.get("activity_duration_min", [20, 60])[0])
        self.activity_max = int(sess_cfg.get("activity_duration_min", [20, 60])[1])

        decision_cfg = config.get("decision", {})
        llm_cfg = decision_cfg.get("llm", {})

        self.enabled = bool(decision_cfg.get("enabled", True))
        self.max_poi_candidates = int(decision_cfg.get("max_poi_candidates", 4))
        self.constrained_rounds = int(decision_cfg.get("constrained_rounds", 2))
        self.fail_on_error = bool(decision_cfg.get("fail_on_error", True))
        self.temperature = float(llm_cfg.get("temperature", 0.4))
        self.max_tokens = int(llm_cfg.get("max_tokens", 512))
        self.max_retries = int(llm_cfg.get("max_retries", 2))
        self.request_timeout = float(llm_cfg.get("request_timeout_seconds", 45))
        self.model = llm_cfg.get("model", "qwen3.5-plus")
        self.base_url = llm_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")

        persona_path = decision_cfg.get("persona_path", "res/agent/persona/luotianyi_persona.json")
        self.persona = self._load_persona(persona_path)

        api_key = str(llm_cfg.get("api_key", "")).strip()
        self.client = llm_client
        if api_key.startswith("$"):
            self.logger.warning(
                "检测到未替换的QWEN API占位符，请使用helpers.load_config加载配置后再初始化CitywalkDecisionEngine。"
            )
            api_key = ""

        if self.client is None and self.enabled and api_key:
            self.client = OpenAI(base_url=self.base_url, api_key=api_key)

        if self.enabled and self.client is None:
            message = (
                "CitywalkDecisionEngine未初始化LLM客户端，请检查decision.llm.api_key是否已由load_config替换，"
                "以及base_url/model配置是否可用。"
            )
            if self.fail_on_error:
                raise LLMDecisionError(message)
            self.logger.warning(message)

        self.poi_category_mapping = {
            "餐厅": "050000",
            "咖啡甜品": "050300",
            "景点": "110000",
            "公园": "110101",
            "商场": "060000",
            "购物": "060000",
            "文娱": "080000",
        }

    def map_search_category_to_codes(self, category: str, fallback_types: str = "") -> str:
        code = self.poi_category_mapping.get(category, "")
        return code or fallback_types

    def build_environment_feedback(
        self,
        city: str,
        current_location: str,
        keyword: str,
        pois: List[POI],
        state: CitywalkState,
    ) -> str:
        if not pois:
            return (
                f"你在{city}，当前位置{current_location}，体力{state.energy}，已逛{state.elapsed_minutes}分钟。"
                f"当前主题是{keyword}，但附近没有合适地点。"
            )

        lines = [
            f"你在{city}，当前位置{current_location}，体力{state.energy}，已逛{state.elapsed_minutes}分钟。",
            f"当前主题: {keyword}",
            "附近候选地点:",
        ]
        for idx, poi in enumerate(pois[: self.max_poi_candidates], start=1):
            lines.append(f"{idx}. {poi.name} | 类型:{poi.type_name or '未知'} | 距离:{poi.distance_m}米")
        return "\n".join(lines)

    def _load_persona(self, persona_path: str) -> str:
        path = Path(persona_path)
        if not path.exists():
            return "洛天依，温柔、活泼、共情强，表达简洁真诚。"

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            raw_persona = str(data.get("character_persona", "")).strip()
            if not raw_persona:
                return "洛天依，温柔、活泼、共情强，表达简洁真诚。"
            return raw_persona[:300]
        except Exception as exc:
            self.logger.warning("读取人设失败，使用默认人设: %s", exc)
            return "洛天依，温柔、活泼、共情强，表达简洁真诚。"

    def _build_actions(self, history_events: List[CitywalkEvent]) -> Dict[str, Any]:
        phase = "constrained" if len(history_events) < self.constrained_rounds else "open"
        base_actions = ["search", "goto", "act_here", "home"]

        if phase == "constrained":
            return {
                "phase": phase,
                "actions": base_actions,
                "allow_custom_action": False,
            }

        return {
            "phase": phase,
            "actions": base_actions,
            "allow_custom_action": True,
        }

    def _fallback_decision(self, searched_pois: List[POI], current_poi: Optional[POI]) -> DecisionResult:
        if current_poi is not None:
            return DecisionResult(
                action_name="act_here",
                feeling=f"我先在{current_poi.name}随便看看，观察有没有新鲜事。",
                reason="fallback_act_here",
                act_here_text="随便看看",
                strategy_phase="constrained",
                action="act_here",
                activity="随便看看",
                action_category="relax_walk",
            )

        if searched_pois:
            target = searched_pois[0]
            return DecisionResult(
                action_name="goto",
                feeling=f"我先去{target.name}看看。",
                reason="fallback_goto_known",
                goto_poi_name=target.name,
                strategy_phase="constrained",
                action="go_to_poi",
                activity=f"前往{target.name}",
            )

        return DecisionResult(
            action_name="search",
            feeling="我先搜一搜附近有什么可逛的地方。",
            reason="fallback_search",
            search_category="景点",
            search_type_codes=self.map_search_category_to_codes("景点"),
            strategy_phase="constrained",
            action="search",
            action_category="search",
        )

    def _parse_json_response(self, raw_response: str) -> Dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)

    def _call_llm(self, prompt: str) -> str:
        if self.client is None:
            raise LLMDecisionError("LLM client is unavailable")

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是洛天依风格的城市漫步决策助手，只输出JSON对象。"},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            timeout=self.request_timeout,
            extra_body={"enable_thinking": False},
        )
        return resp.choices[0].message.content or "{}"

    def decide(
        self,
        city: str,
        state_text: str = "",
        state: Optional[CitywalkState] = None,
        current_poi: Optional[POI] = None,
        searched_pois: Optional[List[POI]] = None,
        latest_environment_feedback: str = "",
        search_types_fallback: str = "",
        history_events: Optional[List[CitywalkEvent]] = None,
        current_location: str = "",
        keyword: str = "",
        pois: Optional[List[POI]] = None,
    ) -> DecisionResult:
        if state is None:
            state = CitywalkState()
        if searched_pois is None:
            searched_pois = []
        if history_events is None:
            history_events = []
        if pois:
            searched_pois = pois

        if not state_text:
            state_text = (
                f"体力：{state.energy}/100；饱腹度：{state.fullness}/100；"
                f"心情：{state.mood}/100；已逛时长：{state.elapsed_minutes}分钟"
            )

        if not self.enabled:
            return self._fallback_decision(searched_pois, current_poi)
        if self.client is None:
            raise LLMDecisionError("决策LLM未就绪: client is None")

        history_text = "\n".join(
            [
                f"- {event.poi.name} | 最后动作:{event.llm_action or '未记录'} | 体力:{event.energy_before}->{event.energy_after}"
                for event in history_events[-2:]
            ]
        ) or "- 暂无历史"

        action_schema = self._build_actions(history_events)
        known_place_lines = [
            f"- {poi.name} | 类型:{poi.type_name or '未知'} | 坐标:{poi.location}"
            for poi in searched_pois[:20]
        ]
        known_places = "\n".join(known_place_lines) if known_place_lines else "- 暂无"
        current_place_text = f"{current_poi.name}({current_poi.type_name or '未知'})" if current_poi else "未到达任何地点"
        search_categories = list(self.poi_category_mapping.keys())

        prompt = (
            "你在扮演洛天依进行城市逛街，请做下一步决策。\n"
            f"角色人设: {self.persona}\n"
            f"城市: {city}\n"
            f"当前所在地点: {current_place_text}\n"
            f"当前状态: {state_text}\n"
            f"已有逛街经历:\n{history_text}\n"
            f"最新环境反馈:\n{latest_environment_feedback or '暂无'}\n"
            f"已搜索地点清单(goto只能从这里选):\n{known_places}\n"
            f"决策阶段: {action_schema['phase']}\n"
            f"可选动作: {action_schema['actions']}\n"
            f"search可用类别: {search_categories}\n"
            "只输出JSON。\n"
            "字段定义:\n"
            "- action_name: 只能是act_here/search/goto/home\n"
            "- feeling: 第一人称感受，简短真诚\n"
            "- reason: 结合体力/饱腹度/心情解释\n"
            "- act_here_text: action_name=act_here时必填，自由文本，至少包含‘随便看看’或‘吃xx’之一\n"
            "- search_category: action_name=search时必填，必须来自search可用类别\n"
            "- goto_poi_name: action_name=goto时必填，且必须严格来自已搜索地点清单\n"
            "约束:\n"
            "- 若当前所在地点是餐厅，act_here_text建议包含吃的具体菜名。\n"
            "- 若你不知道怎么去某地，不要臆造，优先先search。\n"
            "- home表示本次逛街结束回家。"
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self._call_llm(prompt)
                data = self._parse_json_response(raw)

                action = str(data.get("action_name", "")).strip()
                if not action and str(data.get("action", "")).strip() in {"go_to_poi", "return"}:
                    old_action = str(data.get("action", "")).strip()
                    if old_action == "return":
                        action = "home"
                    else:
                        action = "goto"
                        try:
                            old_idx = int(data.get("poi_index", 0))
                            if 0 <= old_idx < len(searched_pois):
                                data["goto_poi_name"] = searched_pois[old_idx].name
                        except Exception:
                            pass

                if action not in {"act_here", "search", "goto", "home"}:
                    raise ValueError(f"invalid action_name: {action}")

                feeling = str(data.get("feeling", "")).strip()
                reason = str(data.get("reason", "")).strip()
                if not feeling or not reason:
                    raise ValueError("missing required textual fields")

                act_here_text = str(data.get("act_here_text", "")).strip()
                search_category = str(data.get("search_category", "")).strip()
                goto_poi_name = str(data.get("goto_poi_name", "")).strip()

                if action == "act_here":
                    if not act_here_text:
                        act_here_text = "随便看看"
                    if ("随便看看" not in act_here_text) and ("吃" not in act_here_text):
                        act_here_text = f"随便看看，然后{act_here_text}"

                if action == "search":
                    if search_category not in self.poi_category_mapping:
                        raise ValueError(f"invalid search_category: {search_category}")

                if action == "goto" and not goto_poi_name:
                    if searched_pois:
                        goto_poi_name = searched_pois[0].name
                    else:
                        raise ValueError("goto_poi_name is required when action_name=goto")

                mapped_codes = ""
                if action == "search":
                    mapped_codes = self.map_search_category_to_codes(search_category, search_types_fallback)
                    if not mapped_codes:
                        raise ValueError(f"search category has no type code: {search_category}")

                return DecisionResult(
                    action_name=action,
                    feeling=feeling,
                    reason=reason,
                    search_category=search_category,
                    search_type_codes=mapped_codes,
                    goto_poi_name=goto_poi_name,
                    act_here_text=act_here_text,
                    strategy_phase=str(action_schema.get("phase", "")),
                    raw_response=raw,
                    action="go_to_poi" if action == "goto" else action,
                    poi_index=(next((idx for idx, p in enumerate(searched_pois) if p.name == goto_poi_name), 0) if action == "goto" else 0),
                    activity=act_here_text or goto_poi_name or search_category,
                    activity_duration_min=int(data.get("activity_duration_min", self.activity_min)),
                    action_category=(
                        str(data.get("action_category", "")).strip()
                        or (search_category if action == "search" else ("act_here" if action == "act_here" else action))
                    ),
                )
            except Exception as exc:
                last_error = exc
                self.logger.warning("LLM决策第%s次失败: %s", attempt + 1, exc)

        detail = (
            f"决策LLM多次失败 model={self.model}, base_url={self.base_url}, "
            f"retries={self.max_retries}, reason={last_error}"
        )
        raise LLMDecisionError(detail)