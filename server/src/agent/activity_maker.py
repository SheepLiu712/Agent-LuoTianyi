"""
Agent 主动发言活动的创建器。
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from ..utils.llm.llm_api_interface import LLMAPIFactory, LLMAPIInterface
from ..utils.logger import get_logger
from ..pipeline.topic_planner import ExtractedTopic
from ..interface.types import ChatResponse
from .main_chat import OneSentenceChat

if TYPE_CHECKING:
    from ..pipeline.chat_stream import ChatStream
    from ..interface.service_hub import ServiceHub
    from sqlalchemy.orm import Session
    from .luotianyi_agent import LuoTianyiAgent


class ActivityType(str, Enum):
    FIRST_LOGIN = "first_login"
    RETURN_LOGIN = "return_login"
    USER_SILENCE = "user_silence"
    REGULAR_LOGIN = "regular_login"

@dataclass
class ActionActivity:
    activity_type: ActivityType
    payload: Dict[str, Any]


@dataclass
class ChatIntenseMeter:
    """
    活跃度计量器。
    - 每条用户消息 +1
    - 每 inactivity_decay_interval_seconds 下降 1
    """

    score: int = 0
    last_user_activity_ts: float = field(default_factory=time.monotonic)
    last_decay_ts: float = field(default_factory=time.monotonic)
    last_trigger_ts: float = 0.0

    def on_user_activity(self, now_ts: float, decay_interval_seconds: float) -> None:
        self._decay(now_ts, decay_interval_seconds)
        self.score += 1
        self.last_user_activity_ts = now_ts

    def should_trigger(
        self,
        now_ts: float,
        trigger_threshold: int, # 当前活跃度分数达到多少可以触发主动发言
        silence_threshold_seconds: float, # 当前用户沉默了多久可以触发主动发言
        cooldown_seconds: float, # 上次触发主动发言到现在过了多久，超过这个时间才可以再次触发
        decay_interval_seconds: float, # 活跃度衰减间隔
    ) -> bool:
        self._decay(now_ts, decay_interval_seconds)
        if self.score <= trigger_threshold:
            return False
        if now_ts - self.last_user_activity_ts < silence_threshold_seconds:
            return False
        if self.last_trigger_ts > 0 and now_ts - self.last_trigger_ts < cooldown_seconds:
            return False
        return True

    def on_triggered(self, now_ts: float) -> None:
        '''被触发后，也就是Agent将要主动发言，重置计量器。'''
        self.score = 0
        self.last_user_activity_ts = now_ts
        self.last_decay_ts = now_ts
        self.last_trigger_ts = now_ts

    def _decay(self, now_ts: float, decay_interval_seconds: float) -> None:
        '''衰减活跃度分数，过了 decay_interval_seconds 就 -1 分，直到衰减到0。'''
        if decay_interval_seconds <= 0:
            return
        elapsed = now_ts - self.last_decay_ts
        if elapsed < decay_interval_seconds:
            return
        drops = int(elapsed // decay_interval_seconds)
        self.score = max(0, self.score - drops)
        self.last_decay_ts += drops * decay_interval_seconds


@dataclass
class _UserActivityState:
    meter: ChatIntenseMeter = field(default_factory=ChatIntenseMeter)
    pending_actions: List[ActionActivity] = field(default_factory=list)
    monitor_task: Optional[asyncio.Task] = None


class ActivityMaker:
    """根据用户行为创建 Agent 主动发言动作，并派发到 chat_stream。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = get_logger("ActivityMaker")
        self.config = config or {}

        self.return_user_threshold_seconds = float(self.config.get("return_user_threshold_seconds", 5 * 24 * 3600))
        self.silence_threshold_seconds = float(self.config.get("silence_threshold_seconds", 180))
        self.activity_trigger_threshold = int(self.config.get("activity_trigger_threshold", 5))
        self.inactivity_decay_interval_seconds = float(self.config.get("inactivity_decay_interval_seconds", 180))
        self.silence_check_interval_seconds = float(self.config.get("silence_check_interval_seconds", 5))
        self.silence_trigger_cooldown_seconds = float(
            self.config.get("silence_trigger_cooldown_seconds", self.silence_threshold_seconds)
        )

        self._load_first_login_res()
        self.agent: Optional["LuoTianyiAgent"] = None

        llm_cfg = self.config.get("llm", {})
        self.llm_client: Optional[LLMAPIInterface] = None
        if llm_cfg:
            try:
                self.llm_client = LLMAPIFactory.create_interface(llm_cfg)
            except Exception as e:
                self.logger.warning(f"Failed to init activity maker llm client, fallback to template topics: {e}")

        self.user_states: Dict[str, _UserActivityState] = {}
        self._lock = asyncio.Lock()

    def set_agent(self, agent: "LuoTianyiAgent") -> None:
        self.agent = agent
        # self._check_other_activity_res()

    async def dispatch_action(
        self,
        action: ActionActivity,
        user_uuid: str,
        chat_stream: "ChatStream",
        service_hub: "ServiceHub",
    ) -> None:
        if action.activity_type == ActivityType.FIRST_LOGIN:
            if not self.first_login_res:
                self.logger.warning("No first-login resources configured, skipping activity dispatch")
                return
            await asyncio.sleep(1)  # 错开用户拉取历史消息的时机。等用户拉完历史消息后再派发登录活动，避免登录活动消息和历史消息混在一起导致展示异常。
            uuid_list = await service_hub.agent.persist_topic_replies_for_pipeline(
                user_id=user_uuid, reply_items=[item["response_line"] for item in self.first_login_res])
            for item, item_uuid in zip(self.first_login_res, uuid_list or []):
                await chat_stream.feed_response(
                    ChatResponse(
                        uuid=item_uuid,
                        text=item["text"],
                        audio=item["audio"],
                        expression="normal",
                        is_final_package=True,
                    )
                )
            return 

        if action.activity_type in {ActivityType.RETURN_LOGIN}:
            topic = await self._build_topic(action, user_uuid)
            await chat_stream.topic_replier.add_topic(topic)
            return

        if action.activity_type == ActivityType.REGULAR_LOGIN:
            # 当天第一次登录（非首次安装/首次登录，也不是长时未登录）触发
            topics_to_add = []
            # 1) 检查今天是否为常见中国节日（简单判断固定公历节日）
            def _is_chinese_holiday(dt:datetime):
                # 仅判断若干常见公历节日：元旦、劳动节、国庆节、圣诞等
                mmdd = dt.strftime("%m-%d")
                fixed = {"01-01": "元旦", "05-01": "劳动节", "10-01": "国庆节", "12-25": "圣诞节", "10-31":"万圣节", "02-14":"情人节", "04-01":"愚人节"}
                holiday_name = fixed.get(mmdd)
                if holiday_name:
                    return holiday_name
            
                # 判断农历节日
                from lunardate import LunarDate
                fixed = {"08-15": "中秋节", "01-01": "春节", "05-05": "端午节", "07-07": "七夕节", "01-15": "元宵节"}
                lunar_dt = LunarDate.fromSolarDate(dt.year, dt.month, dt.day)
                lunar_mmdd = f"{lunar_dt.month:02d}-{lunar_dt.day:02d}"
                holiday_name = fixed.get(lunar_mmdd)
                if holiday_name:
                    return holiday_name
                
                # 特判除夕夜
                lunar_dt = lunar_dt + timedelta(days=1)
                if lunar_dt.month == 1 and lunar_dt.day == 1:
                    return "除夕夜"
                return None

            from datetime import datetime, timedelta
            today = datetime.now()
            holiday_name = _is_chinese_holiday(today)
            if holiday_name:
                topics_to_add.append(
                    ExtractedTopic(
                        topic_id=str(uuid4()),
                        source_messages=[],
                        topic_content=f"今天是{holiday_name}，闲聊几句并询问用户今天是否有安排。",
                        memory_attempts=[],
                        fact_constraints=[],
                        sing_attempts=[],
                        is_forced_from_incomplete=True,
                    )
                )

            # 2) 检查昨天是否有 citywalk，如果有，生成话题并在 memory_attempts 中调用 /YesterdayCityWalk
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            try:
                if self.agent:
                    overview = await self.agent.get_citywalk_overview_by_date(yesterday)
                    if overview:
                        dest = overview.get("selected_destination") or overview.get("selected_destination_name") or overview.get("selected_destination", "昨天的目的地")
                        topic_content = f"分享你昨天前往{dest}游玩的经历"
                        topics_to_add.append(
                            ExtractedTopic(
                                topic_id=str(uuid4()),
                                source_messages=[],
                                topic_content=topic_content,
                                memory_attempts=["/YesterdayCityWalk"],
                                fact_constraints=[],
                                sing_attempts=[],
                                is_forced_from_incomplete=True,
                            )
                        )
            except Exception as e:
                self.logger.warning(f"Failed to check yesterday citywalk: {e}")

            for t in topics_to_add:
                await chat_stream.topic_replier.add_topic(t)
            return

        self.logger.warning(f"Unsupported action type: {action.activity_type}")

    async def add_user(self, user_uuid: str, chat_stream: "ChatStream", service_hub: "ServiceHub") -> None:
        async with self._lock:
            state = self.user_states.get(user_uuid)
            if state is None:
                state = _UserActivityState()
                self.user_states[user_uuid] = state

            # 主动发言控制器，当前版本不实装
            # if state.monitor_task is None or state.monitor_task.done():
            #     state.monitor_task = asyncio.create_task(self._silence_monitor_loop(user_uuid, chat_stream, service_hub))

    async def remove_user(self, user_uuid: str) -> None:
        async with self._lock:
            state = self.user_states.pop(user_uuid, None)
        if state and state.monitor_task and not state.monitor_task.done():
            state.monitor_task.cancel()
            try:
                await state.monitor_task
            except asyncio.CancelledError:
                pass

    async def add_user_login_activity(self, user_uuid: str, time_since_last_login: Optional[float]) -> None:
        
        state = self.user_states.get(user_uuid)
        if state is None:
            state = _UserActivityState()
            self.user_states[user_uuid] = state

        if time_since_last_login is not None:
            self.logger.debug(f"user {user_uuid} 登录，距离上次登录 {time_since_last_login/86400:.2f} 天")
        else:
            self.logger.debug(f"user {user_uuid} 初次登录")

        if time_since_last_login is None:
            state.pending_actions.append(
                ActionActivity(
                    activity_type=ActivityType.FIRST_LOGIN,
                    payload={"user_uuid": user_uuid},
                )
            )
            return

        if time_since_last_login >= self.return_user_threshold_seconds:
            self.logger.debug(f"超过距离上次登录阈值 {self.return_user_threshold_seconds/86400:.2f} 天")
            state.pending_actions.append(
                ActionActivity(
                    activity_type=ActivityType.RETURN_LOGIN,
                    payload={"user_uuid": user_uuid, "time_since_last_login": time_since_last_login},
                )
            )
            return

        # 如果既不是首次登录也不是长时未登录（RETURN_LOGIN），但上一登录时间在今天0点之前，视为今天的首次登录 -> REGULAR_LOGIN
        from datetime import datetime
        now = datetime.now()
        seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
        if time_since_last_login >= seconds_since_midnight:
            state.pending_actions.append(
                ActionActivity(
                    activity_type=ActivityType.REGULAR_LOGIN,
                    payload={"user_uuid": user_uuid},
                )
            )
            return


    async def flush_login_activities(self, user_uuid: str, chat_stream: "ChatStream", service_hub: "ServiceHub") -> None:
        '''
        登录和对话创建之间间隔了一段时间，这时候才派发登录相关的活动。这样可以避免在用户刚登录但还没有建立WebSocket连接时就派发活动，导致活动无法正确发送给用户。
        '''
        state = self.user_states.get(user_uuid)
        if state is None or not state.pending_actions:
            return

        to_dispatch = list(state.pending_actions)
        state.pending_actions.clear()
        for action in to_dispatch:
            await self.dispatch_action(action, user_uuid, chat_stream, service_hub)

    async def on_user_message(self, user_uuid: str) -> None:
        state = self.user_states.get(user_uuid)
        if state is None:
            state = _UserActivityState()
            self.user_states[user_uuid] = state

        now_ts = time.monotonic()
        state.meter.on_user_activity(now_ts, self.inactivity_decay_interval_seconds)

    def _load_first_login_res(self) -> None:
        """加载首次登录欢迎资源（文本 + 音频 base64）。"""
        self.first_login_res: List[Dict[str, str]] = []

        activity_res = self.config.get("activity_res", {})
        first_login_cfg = activity_res.get(ActivityType.FIRST_LOGIN.value, {})

        raw_texts = first_login_cfg.get("text", [])
        if isinstance(raw_texts, str):
            texts = [raw_texts]
        elif isinstance(raw_texts, list):
            texts = [str(t) for t in raw_texts]
        else:
            texts = []

        raw_audio_paths = first_login_cfg.get("audio_path", [])
        if isinstance(raw_audio_paths, str):
            audio_paths = [raw_audio_paths]
        elif isinstance(raw_audio_paths, list):
            audio_paths = [str(p) for p in raw_audio_paths]
        else:
            audio_paths = []

        if not texts and not audio_paths:
            return

        for idx in range(max(len(texts), len(audio_paths))):
            text = texts[idx] if idx < len(texts) else ""
            audio_b64 = ""

            if idx < len(audio_paths) and audio_paths[idx]:
                audio_path = Path(audio_paths[idx])
                try:
                    if not audio_path.is_absolute():
                        audio_path = Path.cwd() / audio_path
                    audio_b64 = base64.b64encode(audio_path.read_bytes()).decode("utf-8")
                except Exception as e:
                    self.logger.warning(
                        f"Failed to load first-login audio at index={idx}, path={audio_paths[idx]}: {e}"
                    )

            self.first_login_res.append({"text": text, "audio": audio_b64, "response_line": OneSentenceChat(content=text, tone="neutral", expression="normal")})

    def _check_other_activity_res(self) -> None:
        '''通过agent的prompt manager获得其他活动类型的资源文本模板。'''
        prompt_manager = self.agent.prompt_manager if self.agent else None
        if prompt_manager is None:
            self.logger.warning("Agent or its prompt manager not available, cannot load other activity resources")
            return
        self.activity_llm_prompts: Dict[ActivityType, str] = {}
        activity_res: Dict[str, Any] = self.config.get("activity_res", {})
        for activity_type in ActivityType:
            prompt_name = activity_res.get(activity_type.value, {}).get("prompt")
            if not prompt_name: # 这个活动类型没有配置prompt资源，不用调用llm
                continue
            if prompt_manager.get_template(prompt_name) is None:
                self.logger.warning(f"Prompt '{prompt_name}' for activity type '{activity_type}' not found in prompt manager, skipping")
                continue

    async def _silence_monitor_loop(self, user_uuid: str, chat_stream: "ChatStream") -> None:
        self.logger.info(f"Activity monitor started for user_uuid={user_uuid}")
        try:
            while True:
                await asyncio.sleep(self.silence_check_interval_seconds)
                state = self.user_states.get(user_uuid)
                if state is None:
                    return

                now_ts = time.monotonic()
                if not state.meter.should_trigger(
                    now_ts=now_ts,
                    trigger_threshold=self.activity_trigger_threshold,
                    silence_threshold_seconds=self.silence_threshold_seconds,
                    cooldown_seconds=self.silence_trigger_cooldown_seconds,
                    decay_interval_seconds=self.inactivity_decay_interval_seconds,
                ):
                    continue

                state.meter.on_triggered(now_ts)
                action = ActionActivity(
                    activity_type=ActivityType.USER_SILENCE,
                    payload={"user_uuid": user_uuid, "silence_seconds": self.silence_threshold_seconds},
                )
                await self.dispatch_action(action, user_uuid, chat_stream)
        except asyncio.CancelledError:
            self.logger.info(f"Activity monitor cancelled for user_uuid={user_uuid}")
            raise
        except Exception as e:
            self.logger.error(f"Activity monitor loop failed for user_uuid={user_uuid}: {e}")


    async def _build_topic(self, action: ActionActivity, user_uuid: str) -> ExtractedTopic:
        fallback_topic = ExtractedTopic(
                topic_id=str(uuid4()),
                source_messages=[],
                topic_content="",
                memory_attempts=[],
                fact_constraints=[],
                sing_attempts=[],
                is_forced_from_incomplete=True,
        )
        if action.activity_type == ActivityType.RETURN_LOGIN:
            seconds = float(action.payload.get("time_since_last_login", 0))
            days = max(1, int(seconds // 86400))
            fallback_topic.topic_content = f"用户已{days}天未登录，请你先热情欢迎TA回来，再询问他的近况或追问上次没聊完的话题。"
            return fallback_topic



_activity_maker = None
def init_activity_maker(config) -> ActivityMaker:
    global _activity_maker
    if _activity_maker is None:
        _activity_maker = ActivityMaker(config=config)
    return _activity_maker

def get_activity_maker() -> ActivityMaker:
    global _activity_maker
    if _activity_maker is None:
        raise ValueError("ActivityMaker has not been initialized")
    return _activity_maker