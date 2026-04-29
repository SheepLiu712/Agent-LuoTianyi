import json
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ...utils.logger import get_logger
from .errors import LLMEnvironmentError
from .types import POI, POIDetail, CitywalkSessionData, POIFeedBack


@dataclass
class EnvironmentResult:
    activity: str
    event: str
    feeling_update: str
    delta_energy: int
    delta_minutes: int
    delta_fullness: int
    next_actions: List[str]
    raw_response: str = ""


class CitywalkEnvironmentEngine:
    def __init__(self, config: Dict[str, Any], llm_client: Optional[Any] = None):
        self.logger = get_logger(__name__)
        decision_cfg = config.get("decision", {})
        env_cfg = decision_cfg.get("environment", {})
        llm_cfg = env_cfg.get("llm", {})

        self.enabled = bool(env_cfg.get("enabled", True))
        self.fail_on_error = bool(env_cfg.get("fail_on_error", True))
        self.model = llm_cfg.get("model", "qwen3.5-plus")
        self.base_url = llm_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.temperature = float(llm_cfg.get("temperature", 0.7))
        self.max_tokens = int(llm_cfg.get("max_tokens", 512))
        self.max_retries = int(llm_cfg.get("max_retries", 2))
        self.request_timeout = float(llm_cfg.get("request_timeout_seconds", 45))
        self.vlm_model = str(llm_cfg.get("vlm_model", "qwen3-vl-plus"))

        api_key = str(llm_cfg.get("api_key", "")).strip()
        self.client = llm_client
        if self.client is None and self.enabled and api_key and not api_key.startswith("$"):
            self.client = OpenAI(base_url=self.base_url, api_key=api_key)
        if self.enabled and self.client is None and self.fail_on_error:
            raise LLMEnvironmentError(
                "CitywalkEnvironmentEngine未初始化LLM客户端，请检查decision.environment.llm.api_key是否已由load_config替换。"
            )

    def _sample_food(self) -> str:
        return random.choice(["小笼包", "豆汁焦圈", "炸酱面", "糖葫芦", "铜锅涮肉"])

    def _sample_handcraft(self) -> str:
        return random.choice(["手作香薰蜡烛", "皮具钥匙扣", "拼豆挂件", "珐琅胸针"])

    def _sample_clothes(self) -> str:
        return random.choice(["浅蓝百褶裙", "白色针织开衫", "牛仔外套", "帆布鞋"])

    def _rule_generate(
        self,
        poi: POI,
        action_text: str,
        state_text: str,
        poi_detail: Optional[POIDetail],
    ) -> EnvironmentResult:
        detail_hint = ""
        if poi_detail:
            if poi_detail.rating is not None:
                detail_hint = f"，店铺评分约{poi_detail.rating:.1f}"
            elif poi_detail.intro:
                detail_hint = f"，特色是{poi_detail.intro[:20]}"

        if "吃" in action_text:
            dish = self._sample_food()
            activity = f"在{poi.name}点了{dish}，边吃边记录味道层次{detail_hint}。"
            event = random.choice(["店员推荐了隐藏菜单", "隔壁桌分享了本地吃法", "刚好赶上热腾腾新出锅"])
            return EnvironmentResult(activity, event, f"吃得很满足。当前状态：{state_text}", -6, 18, 20, ["search", "goto", "home"])

        if "看" in action_text or "逛" in action_text:
            craft = self._sample_handcraft()
            activity = f"在{poi.name}边逛边体验了{craft}，过程意外解压{detail_hint}。"
            event = random.choice(["材料一度不够，临场改了方案", "旁边游客夸成品很可爱", "店主教了一个小技巧"])
            return EnvironmentResult(activity, event, f"灵感有所增加。当前状态：{state_text}", -5, 24, -6, ["act_here", "search", "goto", "home"])

        custom = action_text or "随便看看"
        activity = f"在{poi.name}执行了行动：{custom}{detail_hint}。"
        event = random.choice(["过程有点曲折但结果不错", "中途遇到有趣路人交流", "意外发现隐藏角落"])
        return EnvironmentResult(activity, event, f"这次尝试很新鲜。当前状态：{state_text}", -5, 22, -3, ["act_here", "search", "goto", "home"])

    def _call_llm(self, prompt: str) -> str:
        if self.client is None:
            raise LLMEnvironmentError("environment llm client unavailable")

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是城市漫步环境模拟器，请输出JSON对象。"},
                {"role": "user", "content": prompt},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format={"type": "json_object"},
            timeout=self.request_timeout,
            extra_body={"enable_thinking": False},
        )
        return resp.choices[0].message.content or "{}"

    def _parse_json_response(self, raw_response: str) -> Dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)

    def generate_for_action(
        self,
        city: str,
        poi: POI,
        action_text: str,
        state_text: str,
        poi_detail: Optional[POIDetail],
    ) -> EnvironmentResult:
        if not self.enabled:
            return self._rule_generate(poi, action_text, state_text, poi_detail)
        if self.client is None:
            raise LLMEnvironmentError("环境LLM未就绪: client is None")

        detail_text = "无"
        if poi_detail:
            detail_text = (
                f"电话:{poi_detail.tel or '未知'}; 评分:{poi_detail.rating if poi_detail.rating is not None else '未知'}; "
                f"营业时间:{poi_detail.business_hours or '未知'}; 简介:{poi_detail.intro or '未知'}"
            )

        prompt = (
            "场景: 你在模拟洛天依的逛街环境反馈。\n"
            f"城市:{city}; 地点:{poi.name}; 地点类型:{poi.type_name or '未知'}\n"
            f"Agent动作:{action_text}\n"
            f"POI详细信息:{detail_text}\n"
            f"当前状态: {state_text}\n"
            "请仅输出JSON，字段说明:\n"
            "activity: 具体活动描述(含菜名/商品/观察细节)\n"
            "event: 随机事件描述(有趣且合理)\n"
            "feeling_update: 角色当下情绪一句话\n"
            "delta_energy: 该活动额外体力变化，负数为消耗，范围[-10,3]\n"
            "delta_minutes: 该活动额外时间变化，范围[5,30]\n"
            "delta_fullness: 饱腹度变化，范围[-20,30]\n"
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = self._call_llm(prompt)
                data = self._parse_json_response(raw)
                activity = str(data.get("activity", "")).strip()
                event = str(data.get("event", "")).strip()
                feeling = str(data.get("feeling_update", "")).strip()
                delta_energy = int(data.get("delta_energy", -5))
                delta_minutes = int(data.get("delta_minutes", 20))
                delta_fullness = int(data.get("delta_fullness", 0))

                if not activity or not event or not feeling:
                    raise ValueError("missing required textual fields")

                delta_energy = max(-10, min(3, delta_energy))
                delta_minutes = max(5, min(30, delta_minutes))
                delta_fullness = max(-20, min(30, delta_fullness))
                next_actions = ["act_here", "search", "goto", "home"]

                return EnvironmentResult(activity, event, feeling, delta_energy, delta_minutes, delta_fullness, next_actions, raw_response=raw)
            except Exception as exc:
                last_error = exc
                self.logger.warning("环境LLM第%s次失败: %s", attempt + 1, exc)

        detail = (
            f"环境LLM多次失败 model={self.model}, base_url={self.base_url}, "
            f"retries={self.max_retries}, reason={last_error}"
        )
        raise LLMEnvironmentError(detail)

    # Backward-compatible wrapper for legacy call sites/tests.
    def generate(
        self,
        city: str,
        poi: POI,
        action_category: str,
        custom_action: str,
        keyword: str,
        state_energy: int,
        state_minutes: int,
        poi_detail: Optional[POIDetail],
    ) -> EnvironmentResult:
        action_text = custom_action.strip() if custom_action and custom_action.strip() else (keyword or action_category or "继续探索")
        state_text = f"体力:{state_energy}/100; 已逛:{state_minutes}分钟"
        return self.generate_for_action(
            city=city,
            poi=poi,
            action_text=action_text,
            state_text=state_text,
            poi_detail=poi_detail,
        )

    def describe_image_with_vlm(self, image_url: str) -> str:
        if self.client is None:
            raise LLMEnvironmentError("环境LLM未就绪: client is None")

        resp = self.client.chat.completions.create(
            model=self.vlm_model,
            messages=[
                {
                    "role": "system",
                    "content": "你是景点观察助手，用一句到两句中文描述画面核心内容和氛围。",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请描述这张图片，突出环境与氛围。"},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            temperature=0.3,
            max_tokens=220,
            timeout=self.request_timeout,
        )
        return (resp.choices[0].message.content or "").strip()

    def build_arrival_feedback(
        self,
        city_walk_data: "CitywalkSessionData",
        poi: POI,
        poi_content: Dict[str, Any],
        reason: str,
        state_text: str,
    ) -> POIFeedBack:
        rating = poi_content.get("rating", "未知")
        lucky_value = city_walk_data.lucky_number
        poi_name = poi.name
        poi_type = poi.type_name or poi_content.get("type_name", "未知")
        event_lucky_type = self._get_event_lucky_type(rating, lucky_value)
        poi_tags = poi_content.get("signature_or_tags", [])
        image_description = str(poi_content.get("image_description", "")).strip()

        if isinstance(poi_tags, str):
            tags_text = poi_tags
        elif isinstance(poi_tags, list):
            tags_text = "、".join([str(x).strip() for x in poi_tags if str(x).strip()]) or "无"
        else:
            tags_text = "无"

        mood_map = {
            "大幅上升": (16, 24),
            "小幅上升": (4, 10),
            "基本不变": (-2, 2),
            "小幅下降": (-10, -4),
            "大幅下降": (-24, -16),
        }
        energy_map = {
            "大幅恢复": (10, 18),
            "小幅恢复": (3, 9),
            "基本不变": (-7, 0),
            "小幅消耗": (-16, -7),
            "大幅消耗": (-24, -20),
        }
        fullness_map = {
            "大幅上升": (10, 20),
            "小幅上升": (4, 10),
            "基本不变": (-2, 2),
            "小幅下降": (-10, -4),
            "大幅下降": (-20, -10),
        }
        stay_map = {
            "匆匆离开": (15, 25),
            "普通用时": (40, 55),
            "花了很多时间": (80, 110),
        }

        def _pick_delta(mapping: Dict[str, tuple[int, int]], trend: str, default_key: str) -> int:
            low, high = mapping.get(trend, mapping[default_key])
            if low > high:
                low, high = high, low
            return random.randint(low, high)

        def _rule_fallback() -> POIFeedBack:
            is_food = any(k in (poi_type or "") for k in ["餐", "小吃", "咖啡", "甜品", "奶茶"])
            is_bad_lucky = event_lucky_type in {"会发生倒霉的事情", "会发生非常倒霉的事情"}
            is_good_lucky = event_lucky_type in {"会发生幸运的事情", "会发生非常幸运的事情"}

            if is_food:
                mood_trend = "小幅上升" if not is_bad_lucky else "小幅下降"
                energy_trend = "小幅恢复" if is_good_lucky else "小幅消耗"
                fullness_trend = "大幅上升" if is_good_lucky else "小幅上升"
            else:
                mood_trend = "小幅上升" if is_good_lucky else "基本不变"
                energy_trend = "小幅消耗"
                fullness_trend = "小幅下降" if not is_food else "基本不变"

            stay_trend = "普通用时"
            if is_good_lucky:
                stay_trend = random.choice(["普通用时", "花了很多时间"])
            elif is_bad_lucky:
                stay_trend = random.choice(["匆匆离开", "普通用时"])

            feedback = (
                f"到达{poi_name}后，{event_lucky_type}。"
                f"洛天依围绕{poi_type or '未知类型'}体验了现场内容"
                f"（标签: {tags_text}；图片观察: {image_description or '暂无'}）。"
            )
            mood_change = _pick_delta(mood_map, mood_trend, "基本不变")
            energy_change = _pick_delta(energy_map, energy_trend, "小幅消耗")
            fullness_change = _pick_delta(fullness_map, fullness_trend, "基本不变")
            stay_minutes = _pick_delta(stay_map, stay_trend, "普通用时")
            return POIFeedBack(
                environment_feedback=feedback,
                mood_change=mood_change,
                energy_change=energy_change,
                fullness_change=fullness_change,
                stay_minutes=stay_minutes,
            )

        if not self.enabled or self.client is None:
            return _rule_fallback()

        prompt = (
            "你是洛天依的城市漫步环境事件生成器。请只输出JSON对象，不要输出任何额外文本。\n"
            f"城市: {city_walk_data.city or '未知'}\n"
            f"地点: {poi_name}\n"
            f"地点类型: {poi_type or '未知'}\n"
            f"来到这里的理由：{reason}"
            f"评分: {rating}\n"
            f"幸运判定: {event_lucky_type}\n"
            f"招牌或标签: {tags_text or '暂无'}\n"
            f"图片观察: {image_description or '暂无'}\n"
            f"当前状态文本: {state_text}\n"
            f"当前已经去过的地点有: {', '.join(city_walk_data.visited_names) if city_walk_data.visited_names else '无'}\n"
            "输出字段:\n"
            "environment_feedback: 一句到两句自然中文，描述到达后发生的事件\n"
            "mood_trend: 只能是[大幅上升, 小幅上升, 基本不变, 小幅下降, 大幅下降]\n"
            "energy_trend: 只能是[基本不变, 小幅消耗, 大幅消耗]\n"
            "fullness_trend: 只能是[大幅上升, 小幅上升, 基本不变, 小幅下降, 大幅下降]\n"
            "stay_time_trend: 只能是[匆匆离开, 普通用时, 花了很多时间]"
        )

        try:
            raw = self._call_llm(prompt)
            data = self._parse_json_response(raw)
            feedback_text = str(data.get("environment_feedback", "")).strip()
            mood_trend = str(data.get("mood_trend", "基本不变")).strip()
            energy_trend = str(data.get("energy_trend", "小幅消耗")).strip()
            fullness_trend = str(data.get("fullness_trend", "基本不变")).strip()
            stay_trend = str(data.get("stay_time_trend", "普通用时")).strip()

            if not feedback_text:
                raise ValueError("environment_feedback is empty")

            mood_change = _pick_delta(mood_map, mood_trend, "基本不变")
            energy_change = _pick_delta(energy_map, energy_trend, "小幅消耗")
            fullness_change = _pick_delta(fullness_map, fullness_trend, "基本不变")
            stay_minutes = _pick_delta(stay_map, stay_trend, "普通用时")

            return POIFeedBack(
                environment_feedback=feedback_text,
                mood_change=mood_change,
                energy_change=energy_change,
                fullness_change=fullness_change,
                stay_minutes=stay_minutes,
            )
        except Exception as exc:
            self.logger.warning("arrival feedback LLM失败，使用规则回退: %s", exc)
            return _rule_fallback()
    
    def _get_event_lucky_type(self, rating: Any, lucky_value: float) -> str:
        try:
            rating_value = float(rating)
        except Exception:
            rating_value = None

        _lucky_value = lucky_value
        if rating_value is not None and rating_value > 4.7:
            _lucky_value *= 1.2
        elif rating_value is not None and rating_value > 4.5:
            _lucky_value *= 1.1
        elif rating_value is not None and rating_value < 2.6:
            _lucky_value *= 0.5
        elif rating_value is not None and rating_value < 3.0:
            _lucky_value *= 0.7
        elif rating_value is not None and rating_value < 3.6:
            _lucky_value *= 0.9

        event_lucky_value = random.gauss(_lucky_value, 10)
        if event_lucky_value > 90:
            return "会发生非常幸运的事情"
        elif event_lucky_value > 80:
            return "会发生幸运的事情"
        elif event_lucky_value < 20:
            return "会发生非常倒霉的事情"
        elif event_lucky_value < 40:
            return "会发生倒霉的事情"
        return "运气普通，不会发生特别的事情"


    
    def build_photo_observation(self, poi_detail: Optional[POIDetail],) -> List[str]:
        lines = []
        if poi_detail and poi_detail.photos:
            try:
                desc = self.describe_image_with_vlm(poi_detail.photos[0])
                if desc:
                    lines.append(f"现场图片观察: {desc}")
            except Exception as exc:
                raise LLMEnvironmentError(f"景点图片VLM描述失败: {exc}")
        return lines
