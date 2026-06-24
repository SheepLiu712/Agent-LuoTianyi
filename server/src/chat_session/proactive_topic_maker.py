"""
Agent 主动发言活动的创建器。
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

from src.utils.llm.llm_api_interface import LLMAPIFactory, LLMAPIInterface
from src.utils.logger import get_logger
from src.agent.chat.topic_planner import ExtractedTopic
from src.system.user_interface.types import ChatResponse
from src.agent.main_chat import OneSentenceChat

if TYPE_CHECKING:
    from src.chat_session.chat_stream import ChatStream
    from src.system.system_runtime import SystemRuntime
    from src.agent.luotianyi_agent import LuoTianyiAgent


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
        trigger_threshold: int,  # 当前活跃度分数达到多少可以触发主动发言
        silence_threshold_seconds: float,  # 当前用户沉默了多久可以触发主动发言
        cooldown_seconds: float,  # 上次触发主动发言到现在过了多久，超过这个时间才可以再次触发
        decay_interval_seconds: float,  # 活跃度衰减间隔
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
        """被触发后，也就是Agent将要主动发言，重置计量器。"""
        self.score = 0
        self.last_user_activity_ts = now_ts
        self.last_decay_ts = now_ts
        self.last_trigger_ts = now_ts

    def _decay(self, now_ts: float, decay_interval_seconds: float) -> None:
        """衰减活跃度分数，过了 decay_interval_seconds 就 -1 分，直到衰减到0。"""
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


class ProactiveTopicMaker:
    """根据用户行为创建 Agent 主动发言动作，并派发到 chat_stream。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = get_logger("ProactiveTopicMaker")
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
        self.system_runtime: Optional["SystemRuntime"] = None

    def set_agent(self, agent: "LuoTianyiAgent") -> None:
        self.agent = agent

    def set_system_runtime(self, system_runtime: "SystemRuntime") -> None:
        self.system_runtime = system_runtime

    async def dispatch_action(
        self,
        action: ActionActivity,
        user_uuid: str,
        chat_stream: "ChatStream",
        system_runtime: "SystemRuntime",
    ) -> None:
        # 演唱会静默期间跳过主动发言（保留首次登录欢迎）
        if action.activity_type != ActivityType.FIRST_LOGIN:
            world = self._get_world(system_runtime)
            if world and world.is_silence_period():
                self.logger.info(f"Silence period active, skipping action {action.activity_type}")
                return
        if action.activity_type == ActivityType.FIRST_LOGIN:
            if not self.first_login_res:
                self.logger.warning("No first-login resources configured, skipping activity dispatch")
                return
            await asyncio.sleep(1)  # 错开用户拉取历史消息的时机。等用户拉完历史消息后再派发登录活动，避免登录活动消息和历史消息混在一起导致展示异常。
            uuid_list = await system_runtime.conversation_service.persist_agent_replies(
                user_id=user_uuid, reply_items=[item["response_line"] for item in self.first_login_res]
            )
            for item, item_uuid in zip(self.first_login_res, uuid_list or []):
                # Lazy-load audio at dispatch time
                audio = self._load_audio_b64(item.get("audio_path", ""))
                await chat_stream.feed_response(
                    ChatResponse(
                        uuid=item_uuid,
                        text=item["text"],
                        audio=audio,
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
            topics_to_add: List[ExtractedTopic] = []

            # 1-4) 统一通过 schedule 模块检索：节日 / citywalk / new_song / 用户重要日期
            #      如果已在 schedule 中提醒过，则 login 时不再重复提示
            try:
                world = self._get_world(self.system_runtime)
                if world is None or world.event_store is None:
                    return
                store = world.event_store
                due = store.get_events_due_for_trigger()
                for event_dict, trigger_key in due:
                    evt_type = event_dict.get("event_type", "")

                    if evt_type == "holiday":
                        holiday_name = event_dict.get("title", "节日")
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

                    elif evt_type == "travel":
                        dest_name = event_dict.get("title", "某个地方")
                        topic_content = f"洛天依昨天独自前往{dest_name}游玩了，和用户分享一下。"
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

                    elif evt_type == "new_song":
                        song_title = event_dict.get("title", "洛天依学了一首新歌")
                        topic_content = f"{song_title}！"
                        topics_to_add.append(
                            ExtractedTopic(
                                topic_id=str(uuid4()),
                                source_messages=[],
                                topic_content=topic_content,
                                memory_attempts=[],
                                fact_constraints=[],
                                sing_attempts=[],
                                is_forced_from_incomplete=True,
                            )
                        )

                    elif evt_type in ("birthday", "anniversary"):
                        # 个人事件：仅当 target_user_id 匹配当前用户时才派发
                        is_personal = event_dict.get("is_personal", False)
                        target = event_dict.get("target_user_id", "")
                        if is_personal and target and target != user_uuid:
                            continue  # 不是当前用户的，跳过
                        name = event_dict.get("title", "重要日子")
                        topic_content = f"今天是{name}！问用户有没有什么安排或计划，并送上祝福。"
                        topics_to_add.append(
                            ExtractedTopic(
                                topic_id=str(uuid4()),
                                source_messages=[],
                                topic_content=topic_content,
                                memory_attempts=[],
                                fact_constraints=[],
                                sing_attempts=[],
                                is_forced_from_incomplete=True,
                            )
                        )

                    # Mark notified so the periodic reminder loop does not repeat it.
                    if not store.is_notified(event_dict["id"], user_uuid, trigger_key):
                        store.mark_notified(event_dict["id"], user_uuid, trigger_key)
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.logger.warning(f"Failed to query schedule events for login: {e}")

            # 合并所有话题为单一 ExtractedTopic
            merged = self._merge_topics(topics_to_add)
            if merged:
                await chat_stream.topic_replier.add_topic(merged)
            return

        self.logger.warning(f"Unsupported action type: {action.activity_type}")

    async def run_periodic_checks(self, system_runtime: "SystemRuntime") -> int:
        return await self.dispatch_due_reminders(system_runtime)

    async def dispatch_due_reminders(self, system_runtime: "SystemRuntime") -> int:
        world = self._get_world(system_runtime)
        if world is None or world.event_store is None:
            return 0

        store = world.event_store
        try:
            due_events = store.get_events_due_for_trigger()
        except Exception as e:
            self.logger.warning(f"Failed to query due reminders: {e}")
            return 0

        sent = 0
        for event_dict, trigger_key in due_events:
            for user_id, chat_stream in self._iter_target_streams(system_runtime, event_dict):
                event_id = event_dict.get("id")
                if not event_id:
                    continue
                if store.is_notified(event_id, user_id, trigger_key):
                    continue
                topic = self._build_reminder_topic(event_dict, trigger_key)
                await chat_stream.topic_replier.add_topic(topic)
                store.mark_notified(event_id, user_id, trigger_key)
                sent += 1

        if sent:
            self.logger.info(f"Dispatched {sent} proactive reminder topic(s)")
        return sent

    def _iter_target_streams(self, system_runtime: "SystemRuntime", event_dict: Dict[str, Any]):
        gcsm = getattr(system_runtime, "gcsm", None)
        if gcsm is None:
            return

        is_personal = event_dict.get("is_personal", False)
        target_user_id = event_dict.get("target_user_id")
        for user_id, chat_stream in list(getattr(gcsm, "user_streams", {}).items()):
            if chat_stream is None or chat_stream.is_connection_lost():
                continue
            if is_personal and target_user_id and target_user_id != user_id:
                continue
            yield user_id, chat_stream

    def _build_reminder_topic(self, event_dict: Dict[str, Any], trigger_key: str) -> ExtractedTopic:
        event_type = event_dict.get("event_type", "event")
        title = event_dict.get("title", "")
        description = event_dict.get("description", "")
        trigger_desc = {
            "7_days_before": "in seven days",
            "3_days_before": "in three days",
            "1_day_before": "tomorrow",
            "day_of_event": "today",
            "1_day_after": "yesterday",
            "1_hour_before": "in about one hour",
        }.get(trigger_key, "soon")

        content = f"Proactively remind the user that a {event_type} event, {title}, is {trigger_desc}."
        if description:
            content += f" Event details: {description}."

        return ExtractedTopic(
            topic_id=str(uuid4()),
            source_messages=[],
            topic_content=content,
            memory_attempts=[],
            fact_constraints=[],
            sing_attempts=[],
            is_forced_from_incomplete=True,
        )

    @staticmethod
    def _get_world(system_runtime: Optional["SystemRuntime"]):
        if system_runtime is None:
            return None
        return getattr(system_runtime, "world", None)

    def _merge_topics(self, topics: List[ExtractedTopic]) -> Optional[ExtractedTopic]:
        """将多个 ExtractedTopic 合并为一个。"""
        if not topics:
            return None
        if len(topics) == 1:
            return topics[0]

        combined_content_parts = []
        combined_memory_attempts = []
        combined_fact_constraints = []
        combined_sing_attempts = []
        combined_source_messages = []

        for t in topics:
            if t.topic_content:
                combined_content_parts.append(t.topic_content)
            combined_memory_attempts.extend(t.memory_attempts or [])
            combined_fact_constraints.extend(t.fact_constraints or [])
            combined_sing_attempts.extend(t.sing_attempts or [])
            combined_source_messages.extend(t.source_messages or [])

        # 去重
        combined_memory_attempts = list(dict.fromkeys(combined_memory_attempts))
        combined_fact_constraints = list(dict.fromkeys(combined_fact_constraints))
        combined_sing_attempts = list(dict.fromkeys(combined_sing_attempts))

        return ExtractedTopic(
            topic_id=str(uuid4()),
            source_messages=combined_source_messages,
            topic_content="\n另外，".join(combined_content_parts),
            memory_attempts=combined_memory_attempts,
            fact_constraints=combined_fact_constraints,
            sing_attempts=combined_sing_attempts,
            is_forced_from_incomplete=True,
        )

    async def add_user(self, user_uuid: str, chat_stream: "ChatStream", system_runtime: "SystemRuntime") -> None:
        async with self._lock:
            state = self.user_states.get(user_uuid)
            if state is None:
                state = _UserActivityState()
                self.user_states[user_uuid] = state

            # 主动发言控制器，当前版本不实装
            # if state.monitor_task is None or state.monitor_task.done():
            #     state.monitor_task = asyncio.create_task(self._silence_monitor_loop(user_uuid, chat_stream, system_runtime))

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

    async def flush_login_activities(self, user_uuid: str, chat_stream: "ChatStream", system_runtime: "SystemRuntime") -> None:
        """
        登录和对话创建之间间隔了一段时间，这时候才派发登录相关的活动。这样可以避免在用户刚登录但还没有建立WebSocket连接时就派发活动，导致活动无法正确发送给用户。
        """
        state = self.user_states.get(user_uuid)
        if state is None or not state.pending_actions:
            return

        to_dispatch = list(state.pending_actions)
        state.pending_actions.clear()
        for action in to_dispatch:
            await self.dispatch_action(action, user_uuid, chat_stream, system_runtime)

    async def on_user_message(self, user_uuid: str) -> None:
        state = self.user_states.get(user_uuid)
        if state is None:
            state = _UserActivityState()
            self.user_states[user_uuid] = state

        now_ts = time.monotonic()
        state.meter.on_user_activity(now_ts, self.inactivity_decay_interval_seconds)

    def _load_first_login_res(self) -> None:
        """加载首次登录欢迎资源配置（懒加载音频）。"""
        self.first_login_res: List[Dict[str, Any]] = []

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
            audio_path = audio_paths[idx] if idx < len(audio_paths) else ""
            # Store path only; read file lazily when dispatched
            self.first_login_res.append(
                {
                    "text": text,
                    "audio_path": audio_path,
                    "response_line": OneSentenceChat(content=text, tone="neutral", expression="normal"),
                }
            )

    def _load_audio_b64(self, audio_path: str) -> str:
        """Lazy-load audio file as base64."""
        if not audio_path:
            return ""
        try:
            p = Path(audio_path)
            if not p.is_absolute():
                p = Path.cwd() / p
            return base64.b64encode(p.read_bytes()).decode("utf-8")
        except Exception as e:
            self.logger.warning(f"Failed to load audio: {audio_path}: {e}")
            return ""

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

            # 检查是否有新学会的歌曲可以告知用户
            learned_announcement = self._get_learned_song_announcement()

            fallback_topic.topic_content = (
                f"用户已{days}天未登录，请你先热情欢迎TA回来，"
                f"再询问他的近况或追问上次没聊完的话题。"
                f"{learned_announcement}"
            )
            return fallback_topic

    @staticmethod
    def _get_learned_song_announcement() -> str:
        """Read newly_learned_songs.json and build an announcement string."""
        notify_path = Path("data/plugin_scheduler/newly_learned_songs.json")
        if not notify_path.exists():
            return ""
        try:
            learned = json.loads(notify_path.read_text("utf-8"))
            if not learned:
                return ""
            song_names = "、".join(f"《{s}》" for s in learned[:5])
            notify_path.unlink(missing_ok=True)
            return f"，用户不在的时候洛天依学会了{song_names}！"
        except Exception as e:
            get_logger("ProactiveTopicMaker").warning(f"Failed to read learned songs notification: {e}")
            try:
                notify_path.unlink(missing_ok=True)
            except Exception:
                pass
            return ""

