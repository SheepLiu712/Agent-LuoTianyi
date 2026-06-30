"""
Agent 主动发言活动的创建器。
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional
from uuid import uuid4

from src.utils.logger import get_logger
from src.domain.chat import ExtractedTopic
from src.agent.main_chat import OneSentenceChat

if TYPE_CHECKING:
    from src.chat_session.chat_pipeline.chat_stream import ChatStream
    from src.chat_session.chat_stream_manager import ChatStreamManager
    from src.chat_session.dependency.conversation_service import ConversationService
    from src.system.database import DatabaseManager


class ActivityType(str, Enum):
    FIRST_LOGIN = "first_login"
    RETURN_LOGIN = "return_login"
    REGULAR_LOGIN = "regular_login"


@dataclass
class ActionActivity:
    activity_type: ActivityType
    time_since_last_login: Optional[float] = None


class ProactiveTopicMaker:
    """根据用户行为创建 Agent 主动发言动作，并派发到 chat_stream。"""

    def __init__(self, config: Dict[str, Any]):
        self.logger = get_logger("ProactiveTopicMaker")
        self.config = config

        self.return_user_threshold_seconds = float(self.config.get("return_user_threshold_seconds", 5 * 24 * 3600))
        self.proactive_idle_seconds = float(self.config.get("proactive_idle_seconds", 30))
        self._load_first_login_res()

        self.pending_login_times: Dict[str, Optional[float]] = {}
        self._lock = asyncio.Lock()
        self.conversation_service: Optional["ConversationService"] = None
        self.database_manager: Optional["DatabaseManager"] = None
        self.chat_stream_manager: Optional["ChatStreamManager"] = None

    def configure(
        self,
        *,
        conversation_service: "ConversationService",
        database_manager: "DatabaseManager",
        chat_stream_manager: "ChatStreamManager",
    ) -> None:
        """注入主动发言所需的会话、数据库和聊天流访问接口。"""
        self.conversation_service = conversation_service
        self.database_manager = database_manager
        self.chat_stream_manager = chat_stream_manager
        self.ensure_dependencies()

    def ensure_dependencies(self) -> None:
        """检查主动话题模块依赖已经初始化。"""
        required = {
            "conversation_service": self.conversation_service,
            "database_manager": self.database_manager,
            "chat_stream_manager": self.chat_stream_manager,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"ProactiveTopicMaker dependencies are missing: {', '.join(missing)}")
        if self.database_manager.event_store is None:
            raise RuntimeError("ProactiveTopicMaker dependency is missing: event_store")

    async def dispatch_action(
        self,
        action: ActionActivity,
        user_uuid: str,
        chat_stream: "ChatStream",
    ) -> None:
        if action.activity_type == ActivityType.FIRST_LOGIN:
            if not self.first_login_res:
                self.logger.warning("No first-login resources configured, skipping activity dispatch")
                return
            await asyncio.sleep(1)  # 错开用户拉取历史消息的时机。等用户拉完历史消息后再派发登录活动，避免登录活动消息和历史消息混在一起导致展示异常。
            if self.conversation_service is None:
                self.logger.warning("ConversationService is unavailable, skipping first-login dispatch")
                return
            uuid_list = await self.conversation_service.persist_agent_replies(
                user_id=user_uuid,
                reply_items=[item["response_line"] for item in self.first_login_res],
                character_id=getattr(chat_stream, "character_id", "luotianyi"),
            )
            for item, item_uuid in zip(self.first_login_res, uuid_list or []):
                from src.system.user_interface.types import ChatResponse

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
                store = self._get_event_store()
                character_id = getattr(chat_stream, "character_id", "luotianyi")
                due = store.get_events_due_for_trigger(character=character_id)
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
                    if not store.is_notified(event_dict["id"], user_uuid, trigger_key, character_id):
                        store.mark_notified(event_dict["id"], user_uuid, trigger_key, character_id)
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

    async def run_periodic_checks(self) -> int:
        if self.chat_stream_manager is None:
            self.logger.warning("ChatStreamManager is unavailable, skip proactive reminders")
            return 0

        store = self._get_event_store()
        sent = 0
        for user_id, character_id, chat_stream in self.chat_stream_manager.iter_active_streams():
            if not chat_stream.can_dispatch_proactive(self.proactive_idle_seconds):
                continue
            try:
                due_events = store.get_events_due_for_trigger(character=character_id)
            except Exception as e:
                self.logger.warning(f"Failed to query due reminders: {e}")
                continue

            for event_dict, trigger_key in self._filter_events_for_stream(due_events, user_id):
                event_id = event_dict.get("id")
                if not event_id:
                    continue
                if store.is_notified(event_id, user_id, trigger_key, character_id):
                    continue
                topic = self._build_reminder_topic(event_dict, trigger_key)
                await chat_stream.topic_replier.add_topic(topic)
                store.mark_notified(event_id, user_id, trigger_key, character_id)
                sent += 1

        if sent:
            self.logger.info(f"Dispatched {sent} proactive reminder topic(s)")
        return sent

    def _filter_events_for_stream(
        self,
        due_events: Iterable[tuple[Dict[str, Any], str]],
        user_id: str,
    ) -> Iterable[tuple[Dict[str, Any], str]]:
        for event_dict, trigger_key in due_events:
            is_personal = event_dict.get("is_personal", False)
            target_user_id = event_dict.get("target_user_id")
            if is_personal and target_user_id and target_user_id != user_id:
                continue
            yield event_dict, trigger_key

    def _build_reminder_topic(self, event_dict: Dict[str, Any], trigger_key: str) -> ExtractedTopic:
        event_type = event_dict.get("event_type", "event")
        title = event_dict.get("title", "")
        description = event_dict.get("description", "")
        trigger_desc = {
            "7_days_before": "还有七天",
            "3_days_before": "还有三天",
            "1_day_before": "明天",
            "day_of_event": "今天",
            "1_day_after": "昨天",
            "1_hour_before": "大约一小时后",
        }.get(trigger_key, "快到了")

        content = f"主动提醒用户有一个 {event_type}——{title}，时间是{trigger_desc}。"
        if description:
            content += f" 事件细节：{description}。"

        return ExtractedTopic(
            topic_id=str(uuid4()),
            source_messages=[],
            topic_content=content,
            memory_attempts=[],
            fact_constraints=[],
            sing_attempts=[],
            is_forced_from_incomplete=True,
        )


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

    async def on_user_login(
        self,
        user_uuid: str,
        time_since_last_login: Optional[float] = None,
        chat_stream: "ChatStream | None" = None,
    ) -> None:
        """
        记录登录状态，或在 chat_stream 可用时派发并释放登录主动话题。
        当chat_stream为空，则time_since_last_login不为空，表示用户登录但还未建立聊天流，记录登录时间以便后续派发。
        当chat_stream不为空，则time_since_last_login为空，已经记录在了pending_login_times中，表示用户登录且已建立聊天流，派发登录主动话题。
        """
        if chat_stream is None:
            async with self._lock:
                self.pending_login_times[user_uuid] = time_since_last_login
            if time_since_last_login is not None:
                self.logger.debug(f"user {user_uuid} 登录，距离上次登录 {time_since_last_login/86400:.2f} 天")
            else:
                self.logger.debug(f"user {user_uuid} 初次登录")
            return

        missing = object()
        async with self._lock:
            pending = self.pending_login_times.pop(user_uuid, missing)
        if pending is missing:
            return

        action = self._make_login_action(user_uuid, pending)
        if action is not None:
            await self.dispatch_action(action, user_uuid, chat_stream)

    def _make_login_action(
        self,
        user_uuid: str,
        time_since_last_login: Optional[float],
    ) -> Optional[ActionActivity]:
        """根据上次登录间隔判断应该派发哪一种登录主动话题。"""
        _ = user_uuid
        if time_since_last_login is None:
            return ActionActivity(ActivityType.FIRST_LOGIN)

        if time_since_last_login >= self.return_user_threshold_seconds:
            self.logger.debug(f"超过距离上次登录阈值 {self.return_user_threshold_seconds/86400:.2f} 天")
            return ActionActivity(
                ActivityType.RETURN_LOGIN,
                time_since_last_login=time_since_last_login,
            )

        now = datetime.now()
        seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
        if time_since_last_login >= seconds_since_midnight:
            return ActionActivity(ActivityType.REGULAR_LOGIN)
        return None

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
            seconds = float(action.time_since_last_login or 0)
            days = max(1, int(seconds // 86400))

            # 检查是否有新学会的歌曲可以告知用户
            learned_announcement = self._get_learned_song_announcement()

            fallback_topic.topic_content = (
                f"用户已{days}天未登录，请你先热情欢迎TA回来，"
                f"再询问他的近况或追问上次没聊完的话题。"
                f"{learned_announcement}"
            )
            return fallback_topic

        return fallback_topic

    def _get_event_store(self):
        if self.database_manager is None or self.database_manager.event_store is None:
            raise RuntimeError("EventStore is unavailable for proactive topic maker")
        return self.database_manager.event_store

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

