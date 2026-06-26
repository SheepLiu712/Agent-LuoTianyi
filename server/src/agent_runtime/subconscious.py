from __future__ import annotations

from typing import Any, Mapping

from src.agent_runtime.agent_registry import AgentRegistry
from src.subconscious.character_mind import CharacterSubconscious
from src.subconscious.preprocessing import ChatPreprocessor


class Subconscious:
    """Facade for character memory, recall, attention, and post-processing.

    During this migration it delegates to the legacy methods still living on
    LuoTianyiAgent. New chat-session code should depend on this facade so those
    methods can move here without changing session orchestration again.
    """

    def __init__(
        self,
        config: Mapping[str, Any],
        agent_registry: AgentRegistry,
        character_minds: Mapping[str, CharacterSubconscious],
    ) -> None:
        self.config = dict(config)
        self.agent_registry = agent_registry
        self.character_minds = dict(character_minds)
        self.preprocessor = ChatPreprocessor(self.config.get("preprocessing", {}))

    def get_mind(self, character_id: str | None = None) -> CharacterSubconscious:
        profile = self.agent_registry.character_registry.get(character_id)
        try:
            return self.character_minds[profile.character_id]
        except KeyError as exc:
            raise KeyError(f"No subconscious registered for {profile.character_id}") from exc

    def get_state(self, character_id: str | None = None):
        return self.get_mind(character_id).get_state()

    async def preprocess_chat_event(self, *, system_runtime: Any, user_id: str, event: Any):
        return await self.preprocessor.preprocess_chat_event(system_runtime, user_id, event)

    async def extract_topic(
        self,
        *,
        character_id: str | None,
        user_id: str,
        unread_snapshot: Any,
        force_complete: bool = False,
        conversation_history: str | None = None,
    ):
        mind = self.get_mind(character_id)
        return await mind.extract_topics(
            user_id=user_id,
            unread_snapshot=unread_snapshot,
            force_complete=force_complete,
            conversation_history=conversation_history,
        )

    async def plan_topic_turn(
        self,
        *,
        character_id: str | None,
        user_id: str,
        topic: Any,
        conversation_history: str,
        external_context: str | None = None,
    ):
        mind = self.get_mind(character_id)
        return await mind.plan_topic_turn(
            user_id=user_id,
            topic=topic,
            conversation_history=conversation_history,
            external_context=external_context,
        )

    async def realize_topic_plan(self, *, character_id: str | None, user_id: str, plan: Any):
        agent = self.agent_registry.get(character_id)
        return await agent.realize_topic_plan_for_pipeline(user_id=user_id, plan=plan)

    async def write_topic_memories(
        self,
        *,
        character_id: str | None,
        user_id: str,
        current_dialogue: str,
        related_memories: list[str] | None = None,
        conversation_history: str | None = None,
    ) -> None:
        mind = self.get_mind(character_id)
        await mind.write_topic_memories(
            user_id=user_id,
            current_dialogue=current_dialogue,
            related_memories=related_memories,
            conversation_history=conversation_history,
        )

    async def detect_dates_for_topic(
        self,
        *,
        character_id: str | None,
        user_id: str,
        topic: Any,
        conversation_history: str | None,
        reply_topic_callback,
    ):
        mind = self.get_mind(character_id)
        return await mind.detect_dates_for_topic(
            user_id=user_id,
            topic=topic,
            conversation_history=conversation_history,
            reply_topic_callback=reply_topic_callback,
        )

    async def update_user_profile_by_context(
        self,
        *,
        character_id: str | None,
        user_id: str,
        context: dict[str, Any],
    ) -> str | None:
        mind = self.get_mind(character_id)
        return await mind.update_user_profile_by_context(user_id=user_id, context=context)
