import json
import os
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from openai import OpenAI

from .amap_client import AMapClient
from .environment_engine import CitywalkEnvironmentEngine
from .state_manager import CitywalkStateManager
from .types import  CitywalkSessionResult, POI, POIDetail, CitywalkSessionData, POIFeedBack, CitywalkEvent, RouteResult


class CitywalkSessionRunner:
    def __init__(
        self,
        config: Dict[str, Any],
        client: AMapClient,
        decision_engine: Optional[Any] = None,
        environment_engine: Optional[CitywalkEnvironmentEngine] = None,
    ):
        self.config = config
        self.client = client
        sess_cfg = config.get("session", {})
        self.state_manager = CitywalkStateManager(
            initial_energy=int(sess_cfg.get("initial_energy", 100)),
            initial_fullness=int(sess_cfg.get("initial_fullness", 70)),
            initial_mood=int(sess_cfg.get("initial_mood", 70)),
            max_minutes=int(sess_cfg.get("max_minutes", 240)),
            move_energy_per_km=int(sess_cfg.get("move_energy_per_km", 5)),
            activity_energy_per_30min=int(sess_cfg.get("activity_energy_per_30min", 8)),
        )
        self.max_stops = int(sess_cfg.get("max_stops", 4))
        duration_range = sess_cfg.get("activity_duration_min", [20, 60])
        self.activity_min = int(duration_range[0])
        self.activity_max = int(duration_range[1])
        self.environment_engine = environment_engine or CitywalkEnvironmentEngine(config)
        self.decision_engine = decision_engine

        decision_cfg = config.get("decision", {})
        llm_cfg = decision_cfg.get("llm", {})
        self.model = str(llm_cfg.get("model", "qwen3.5-plus"))
        self.base_url = str(llm_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
        self.temperature = float(llm_cfg.get("temperature", 0.4))
        self.max_tokens = int(llm_cfg.get("max_tokens", 1024))
        self.max_retries = int(llm_cfg.get("max_retries", 2))
        self.request_timeout = float(llm_cfg.get("request_timeout_seconds", 45))
        self.persona = "你是洛天依。语气灵动、温柔、可爱，但要具体、有生活细节。"

        self.search_cfg = config.get("search", {})
        self.allowed_types = str(self.search_cfg.get("types", "050000|060000|110000|120000"))
        self.radius_m = int(self.search_cfg.get("radius_m", 2000))
        self.offset = int(self.search_cfg.get("offset", 10))

        api_key = self._resolve_api_key(str(llm_cfg.get("api_key", "")).strip())
        self.llm_client = OpenAI(base_url=self.base_url, api_key=api_key) if api_key else None

    def run(
        self,
        destination: Optional[str] = None,
        city: Optional[str] = None,
        district_code: str = "",
        start_location: str = "",
    ) -> CitywalkSessionResult:
        city_walk_data = CitywalkSessionData()
        

        # 1. 选定目的地和起点
        preferred_destination = destination or city or ""
        destination_data: Dict[str, str] = self._select_initial_destination(preferred_destination=preferred_destination)
        selected_destination = destination_data["destination_name"]
        city_walk_data.city = destination_data["destination_city"]
        destination_reason = destination_data["reason"]

        if start_location:
            city_walk_data.current_location = start_location
        else:
            city_walk_data.current_location = self._resolve_start_location(selected_destination, city_walk_data.city, district_code)
        city_walk_data.session_start_location = city_walk_data.current_location
        city_walk_data.current_location_name = selected_destination

        reason = destination_reason
        target = self._resolve_init_destination_as_POI(city_walk_data,selected_destination)


        # 选定目的地后，开始游走阶段
        hop_count = random.randint(3, 5)
        print(f"[citywalk][阶段2] 启动POI游走，总轮次={hop_count}")
        for step in range(1, hop_count + 1):

            print(f"[citywalk][阶段2] 第{step}轮，当前位置={city_walk_data.current_location_name}，虚拟时间={city_walk_data.current_time.strftime('%H:%M')}")
            

            # 执行走过去下一站的状态变更
            time_before = city_walk_data.current_time
            energy_before = self.state_manager.state.energy
            mood_before = self.state_manager.state.mood
            fullness_before = self.state_manager.state.fullness
            route = self._walk_to_next_poi(city_walk_data, target)
            if not route:
                continue
            travel_min = int((city_walk_data.current_time - time_before).total_seconds() // 60)

            # 到达下一站后模拟发生的事情
            poi_content = {
                "name": target.name,
                "type_name": target.type_name,
                "address": target.address,
                "rating": "未知",
                "signature_or_tags": [],
                "image_description": "",
            }
            try:
                detail = self.client.get_poi_detail(target.poi_id)
                # 生成 POI 内容
                poi_content = self._generate_poi_content(detail)
                city_walk_data.poi_details.append(poi_content)
            except Exception as exc:
                print(f"[citywalk][阶段3] 获取POI详情失败 {target.name}: {exc}")
            
            # 随机生成事件
            poi_activity_text = ""
            try:
                feedback = self.environment_engine.build_arrival_feedback(
                    city_walk_data=city_walk_data,
                    poi=target,
                    poi_content=poi_content,
                    reason=reason,
                    state_text=self.state_manager.render_state_for_llm(),
                )
                poi_activity_text = f"停留{feedback.stay_minutes}分钟，{feedback.environment_feedback}"
                
            except Exception as exc:
                feedback = POIFeedBack(environment_feedback="反馈生成失败")
                poi_activity_text = feedback.environment_feedback
                print(f"[citywalk][阶段3] {feedback.environment_feedback}")

            if not poi_activity_text:
                poi_activity_text = f"停留{feedback.stay_minutes}分钟，{feedback.environment_feedback}"

            self.state_manager.change_state_by_feedback(feedback)
            self.state_manager.apply_activity(feedback.stay_minutes)
            city_walk_data.current_time += timedelta(minutes=feedback.stay_minutes)

            event = CitywalkEvent(
                timestamp=city_walk_data.current_time,
                poi=target,
                poi_content = poi_content,
                route = route,
                moving_activity = f"步行约{travel_min}分钟到达{target.name}",
                poi_activity = poi_activity_text,
                energy_before=energy_before,
                energy_after=self.state_manager.state.energy,
                mood_before=mood_before,
                mood_after=self.state_manager.state.mood,
                fullness_before=fullness_before,
                fullness_after=self.state_manager.state.fullness,
                travel_min=travel_min,
                activity_min=feedback.stay_minutes,
                activity=poi_activity_text,
                environment_feedback=feedback.environment_feedback,
                llm_action="relax_walk@poi:auto",
                llm_reason=reason,
            )
            city_walk_data.events.append(event)

            next_pick = self._pick_next_destination(city_walk_data)
            if not next_pick:
                print("[citywalk][阶段2] 没有合适的下一站，结束游走")
                break
            target, reason = next_pick


            if self.state_manager.should_end():
                print("[citywalk][阶段2] 状态触发结束，提前停止游走")
                break



        # 结束游走后，生成流水账文本
        print("[citywalk][阶段3] 生成洛天依流水账与总结")
        diary_text = self._generate_diary_text(
            city=city_walk_data.city,
            destination_name=selected_destination,
            destination_reason=destination_reason,
            events=city_walk_data.events,
        )

        print("[citywalk][阶段4] 行程结束，准备输出结果")
        return CitywalkSessionResult(
            city=city_walk_data.city,
            start_location=city_walk_data.session_start_location,
            end_location=city_walk_data.current_location,
            total_distance_m=city_walk_data.total_distance,
            total_duration_minutes=self.state_manager.state.elapsed_minutes,
            energy_left=self.state_manager.state.energy,
            events=city_walk_data.events,
            selected_destination=selected_destination,
            destination_reason=destination_reason,
            poi_details=city_walk_data.poi_details,
            diary_text=diary_text,
        )
    
    def _resolve_start_location(self, selected_destination: str, selected_city: str, district_code: str) -> str:
        try:
            geocode = self.client.geocode_place(selected_destination, city=selected_city)
            location = geocode["location"]
            print(
                "[citywalk][阶段1] 高德地理编码成功: "
                f"{selected_destination} -> {location} ({geocode.get('formatted_address', '')})"
            )
            return location
        except Exception as exc:
            print(f"[citywalk][阶段1] 地理编码失败，尝试district/start回退: {exc}")
            if district_code:
                return self.client.resolve_random_start_by_district_code(district_code=district_code)
        return ""
            
    def _pick_next_destination(self, city_walk_data: CitywalkSessionData) -> Optional[Tuple[POI, str]]:
        nearby = self.client.search_nearby_pois(
                location=city_walk_data.current_location,
                city=city_walk_data.city,
                keywords="",
                types=self.allowed_types,
                radius_m=self.radius_m,
                offset=self.offset,
            )
        candidates: List[POI] = [p for p in nearby if (p.poi_id not in city_walk_data.visited_ids and p.name not in city_walk_data.visited_names)]
        candidates = candidates[: min(8, len(candidates))]
        print(f"[citywalk][阶段2] 候选POI数={len(candidates)}")
        if not candidates:
            print("[citywalk][阶段2] 无可用新POI，结束游走")
            return None

        decision = self._pick_next_poi_with_llm(
            city=city_walk_data.city,
            current_time_text=city_walk_data.current_time.strftime("%H:%M"),
            current_location=city_walk_data.current_location_name,
            events=city_walk_data.events,
            candidates=candidates,
            food_count=city_walk_data.food_count,
            play_count=city_walk_data.play_count,
        )
        target: POI = candidates[decision["selected_index"] - 1]
        print(f"[citywalk][阶段2] LLM选择下一站: {target.name} | 理由: {decision['reason']}")
        return target, decision["reason"]
    
    def _resolve_init_destination_as_POI(self, city_walk_data: CitywalkSessionData, selected_destination: str) -> POI:
        nearby = self.client.search_nearby_pois(
                location=city_walk_data.current_location,
                city=city_walk_data.city,
                keywords=selected_destination,
                radius_m=self.radius_m,
                types=self.allowed_types,
                offset=25,
            )
        candidates: List[POI] = [p for p in nearby if (p.poi_id not in city_walk_data.visited_ids and p.name not in city_walk_data.visited_names)]
        if candidates:
            return candidates[0]
        return POI(
            poi_id=f"init::{selected_destination or 'destination'}",
            name=selected_destination or city_walk_data.current_location_name or "初始地点",
            location=city_walk_data.current_location,
            address=selected_destination or "",
            distance_m=0,
            type_name="景点",
        )

    def _walk_to_next_poi(self, city_walk_data: CitywalkSessionData, target: POI) -> Optional[RouteResult]:
        route = self.client.plan_walking_route(city_walk_data.current_location, target.location)
        if not route.reachable:
            print(f"[citywalk][阶段2] 步行路径不可达，跳过: {target.name}")
            return None

        # 执行前往下一站的状态变更

        self.state_manager.apply_move(route.distance_m, route.duration_s)
        travel_min = max(int(round(route.duration_s / 60)), 1)
        city_walk_data.current_time += timedelta(minutes=travel_min)
        city_walk_data.total_distance += route.distance_m

        if self._is_food_poi(target.type_name):
            city_walk_data.food_count += 1
        elif self._is_play_poi(target.type_name):
            city_walk_data.play_count += 1

        city_walk_data.current_location = target.location
        city_walk_data.current_location_name = target.name
        city_walk_data.visited_ids.add(target.poi_id)
        city_walk_data.visited_names.append(target.name)
        return route
    
    def _generate_poi_content(self, detail: POIDetail) -> Dict[str, Any]:
        photo_lines: List[str] = []
        if hasattr(self.environment_engine, "build_photo_observation"):
            photo_lines = self.environment_engine.build_photo_observation(detail)
        image_desc = ""
        for line in photo_lines:
            if line.startswith("现场图片观察:"):
                image_desc = line.replace("现场图片观察:", "", 1).strip()
                break

        signature_or_tags: List[str] = []
        if detail and detail.tags:
            signature_or_tags = detail.tags[:6]

        return  {
                "name": detail.poi.name,
                "type_name": detail.poi.type_name,
                "address": detail.poi.address,
                "rating": (detail.rating if detail and detail.rating is not None else "未知"),
                "signature_or_tags": signature_or_tags,
                "image_description": image_desc,
            }
        

    def _resolve_api_key(self, raw: str) -> str:
        if not raw:
            return ""
        if raw.startswith("$"):
            env_name = raw[1:]
            if env_name.startswith("{") and env_name.endswith("}"):
                env_name = env_name[1:-1]
            return str(os.environ.get(env_name, "")).strip()
        return raw

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        content = (text or "").strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        return json.loads(content or "{}")

    def _call_llm_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if self.llm_client is None:
            raise RuntimeError("LLM client unavailable")
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                    timeout=self.request_timeout,
                    extra_body={"enable_thinking": False},
                )
                raw = resp.choices[0].message.content or "{}"
                return self._parse_json_response(raw)
            except Exception as exc:
                print(f"[citywalk][llm-json] 第{attempt + 1}次失败: {exc}")
                last_error = exc
        raise RuntimeError(f"LLM JSON 调用失败: {last_error}")

    def _call_llm_text(self, system_prompt: str, user_prompt: str) -> str:
        if self.llm_client is None:
            raise RuntimeError("LLM client unavailable")
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=min(self.temperature + 0.2, 0.9),
                    max_tokens=max(self.max_tokens, 1500),
                    timeout=self.request_timeout,
                    extra_body={"enable_thinking": False},
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                print(f"[citywalk][llm-text] 第{attempt + 1}次失败: {exc}")
                last_error = exc
        raise RuntimeError(f"LLM 文本调用失败: {last_error}")

    @staticmethod
    def _is_food_poi(type_name: str) -> bool:
        text = type_name or ""
        return any(x in text for x in ["餐", "美食", "小吃", "咖啡", "茶饮"])

    @staticmethod
    def _is_play_poi(type_name: str) -> bool:
        text = type_name or ""
        return any(x in text for x in ["公园", "景区", "商场", "广场", "博物馆", "乐园", "步行街"])


    def _select_initial_destination(self, preferred_destination: Optional[str] = None) -> Dict[str, str]:
        print("[citywalk][阶段1] 让LLM在全国范围挑选今日目的地")
        if self.llm_client is None:
            fallback_name = (preferred_destination or "北京").strip() or "北京"
            return {
                "destination_name": fallback_name,
                "destination_city": fallback_name,
                "category": "城市",
                "reason": "先从这个目的地开始慢慢逛。",
            }

        prompt = (
            f"角色设定: {self.persona}\n"
            "任务: 在中国范围挑选一个今天要去玩的目的地。"
            "目的地可以是城市、景点、商圈、美食地标。如“成都”“九寨沟”“上海外滩”\n"
            "只输出JSON，字段:\n"
            "- destination_name: 目的地名称\n"
            "- city: 所在城市(不知道则为空字符串)\n"
            "- category: 城市|景点|美食|商圈\n"
            "- reason: 50字内理由，像洛天依会说的话\n"
            f"用户偏好目的地提示: {preferred_destination or '无'}"
        )

        data = self._call_llm_json("你是城市出行规划助手，只输出JSON。", prompt)
        destination_name = str(data.get("destination_name", "")).strip()
        destination_city = str(data.get("city", "")).strip()
        category = str(data.get("category", "")).strip() or "景点"
        reason = str(data.get("reason", "")).strip() or "今天想换个地方寻找新鲜感。"
        if not destination_name:
            destination_name = destination_city
        print(f"[citywalk][阶段1] 目的地={destination_name} | 城市={destination_city} | 类别={category}")
        print(f"[citywalk][阶段1] 选择理由: {reason}")
        return {
            "destination_name": destination_name,
            "destination_city": destination_city,
            "category": category,
            "reason": reason,
        }

    def _pick_next_poi_with_llm(
        self,
        city: str,
        current_time_text: str,
        current_location: str,
        events: List[CitywalkEvent],
        candidates: List[POI],
        food_count: int,
        play_count: int,
    ) -> Dict[str, Any]:
        if self.llm_client is None:
            return {
                "selected_index": 1,
                "reason": "按距离和可达性优先，先去最近一站。",
                "expected_activity": "继续探索",
            }

        candidate_lines = []
        for idx, poi in enumerate(candidates, start=1):
            candidate_lines.append(
                f"{idx}. {poi.name} | 类型:{poi.type_name or '未知'} | 距离:{poi.distance_m}米 | 地址:{poi.address or '未知'}"
            )
        visited_text = []
        for event in events:
            event_poi = event.poi.name
            event_activity = event.poi_activity
            visited_text.append(f"在{event_poi}：{event_activity}")
        if visited_text:
            visited_text = "".join(visited_text)
        else:
            visited_text = "无"
        ratio_tip = (
            f"当前已完成: 吃饭点{food_count}个, 游玩点{play_count}个。"
            "请兼顾吃饭与游玩，不要长期偏向单一类型。"
        )

        prompt = (
            f"角色设定: {self.persona}\n"
            f"城市: {city}\n"
            f"当前时间: {current_time_text}\n"
            f"当前位置: {current_location}\n"
            f"已去过地点: {visited_text}\n"
            f"{ratio_tip}\n"
            "你要从候选POI中选一个作为下一站。\n"
            "限制:\n"
            "1) 优先类型应为公园/景区/美食/商圈相关。\n"
            "2) 不能选择已去过地点。\n"
            "3) 行程应自然流动，考虑时间推进。\n"
            "候选列表:\n"
            + "\n".join(candidate_lines)
            + "\n只输出JSON: selected_index(1-based), reason, expected_activity"
        )
        data = self._call_llm_json("你是城市漫步决策助手，只输出JSON。", prompt)
        idx = int(data.get("selected_index", 1))
        idx = max(1, min(idx, len(candidates)))
        reason = str(data.get("reason", "")).strip() or "下一站看起来更顺路，也更符合当前状态。"
        activity = str(data.get("expected_activity", "")).strip() or "继续探索"
        return {
            "selected_index": idx,
            "reason": reason,
            "expected_activity": activity,
        }

    def _generate_diary_text(
        self,
        city: str,
        destination_name: str,
        destination_reason: str,
        events: List[CitywalkEvent],
    ) -> str:
        if self.llm_client is None:
            if not events:
                return "今天路线比较短，下一次要去更多有意思的地方。\n\n总结感想：慢慢逛也有收获。"
            lines = [f"今天在{city}围绕{destination_name}逛了{len(events)}站。"]
            for idx, item in enumerate(events, start=1):
                lines.append(f"第{idx}站去了{item.poi.name}，{item.poi_activity}")
            lines.append("\n总结感想：这次节奏刚好，既看见了风景，也留住了心情。")
            return "\n".join(lines)

        details_text = []
        for idx, item in enumerate(events, start=1):
            poi = item.poi
            poi_content = item.poi_content
            details_text.append(
                f"第{idx}站: {poi.name} | 类型:{poi.type_name}"
                f"招牌/标签:{'、'.join(poi_content.get('signature_or_tags', [])) or '无'} | "
                f"图片描述:{poi_content.get('image_description', '无')}"
                f"发生的事情：{item.poi_activity}"
            )
        prompt = (
            f"角色设定: {self.persona}\n"
            f"今天起点动机: {destination_name}，原因: {destination_reason}\n"
            "你要写一段今天的流水账，像讲故事一样，描述见闻并穿插个人感受。最后必须有一段总结。\n"
            "不得使用Emoji和颜文字。不得提到在各个地点准确的逗留时间。\n"
            "素材如下:\n"
            + "\n".join(details_text)
        )
        return self._call_llm_text("你是洛天依，擅长写有画面感的一日见闻。", prompt)

    