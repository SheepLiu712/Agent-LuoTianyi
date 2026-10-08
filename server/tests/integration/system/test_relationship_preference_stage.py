"""偏好保存经 Stage 和 Agent 更新当前交互上下文。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import src.domain.agent as d
from src.adapter.websocket import WebSocketAdapter
from src.agent import Agent
from src.agent.context import ContextFactory
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.relationship import NewRelationshipProposeHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive.response_generation import CharacterReplyGenerator
from src.infrastructure.media import create_media_resolver
from src.stage import StageManager
from src.web.http import UserInterface
from src.web.http.types import PreferenceOverwriteRequest


class ConversationService:
    def __init__(self) -> None:
        self.preferences = {"relationship": "旧关系", "speaking_style": "温柔"}

    def get_user_description(self, user_id: str) -> str:
        assert user_id == "user-1"
        return "用户画像"

    def get_user_preferences(self, user_id: str) -> dict:
        assert user_id == "user-1"
        return dict(self.preferences)

    def save_user_preferences(self, user_id: str, preferences: dict) -> bool:
        assert user_id == "user-1"
        self.preferences = dict(preferences)
        return True

    def get_conversation_context_state(self, user_id: str, *, character_id: str) -> dict:
        assert user_id == "user-1"
        assert character_id in {"luotianyi", "miku"}
        return {"conversations": [], "summary": "", "context_count": 0}


class Connection:
    user_uuid = "user-1"

    def __init__(self) -> None:
        self.is_closed = False

    def mark_disconnected(self) -> None:
        self.is_closed = True


def make_runtime():
    conversation = ConversationService()

    def get_agent(character_id: str) -> Agent:
        return Agent(
            character_id=character_id,
            stimulus_router=StimulusRouter(
                (
                    (d.StimulusKind.NEW_RELATIONSHIP_PROPOSE, NewRelationshipProposeHandler()),
                    (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
                )
            ),
        )

    manager = StageManager(
        get_agent=get_agent,
        adapter=WebSocketAdapter(),
        get_context_factory=lambda character_id: ContextFactory(character_id=character_id, database=conversation),
        config={"offline_timeout": 10},
    )
    database = SimpleNamespace(
        conversation_service=conversation,
        credential_service=SimpleNamespace(check_message_token=lambda username, token: (True, "user-1")),
    )
    return SimpleNamespace(
        database_manager=database,
        stage_manager=manager,
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
    )


@pytest.mark.asyncio
async def test_overwrite_updates_online_and_retained_stage_before_returning() -> None:
    runtime = make_runtime()
    user_interface = UserInterface(runtime.database_manager, create_media_resolver())
    first_connection = Connection()
    stage = await runtime.stage_manager.connect(first_connection, "luotianyi")
    other_stage = await runtime.stage_manager.connect(Connection(), "miku")
    try:
        assert stage.context.user.read().preferences.relationship == "旧关系"

        result = await user_interface.overwrite_preference(
            PreferenceOverwriteRequest(
                username="user", token="token", preferences={"relationship": "星际图书馆搭档", "speaking_style": "活泼"}
            ),
            runtime,
        )

        assert result["status"] == "success"
        assert stage.context.user.read().preferences.relationship == "星际图书馆搭档"
        assert other_stage.context.user.read().preferences.relationship == "星际图书馆搭档"
        assert stage.context.user.read().preferences.speaking_style == "活泼"
        assert "用户希望你是他的：星际图书馆搭档" in CharacterReplyGenerator._build_preference_context(
            stage.context.user.read()
        )

        await runtime.stage_manager.disconnect(first_connection)
        await user_interface.overwrite_preference(
            PreferenceOverwriteRequest(username="user", token="token", preferences={"relationship": "朋友"}),
            runtime,
        )
        assert stage.context.user.read().preferences.relationship == "朋友"
        assert other_stage.context.user.read().preferences.relationship == "朋友"
        await stage.propose_relationship("过时的提议")
        assert stage.context.user.read().preferences.relationship == "朋友"

        restored = await runtime.stage_manager.connect(Connection(), "luotianyi")
        assert restored is stage
        assert restored.context.user.read().preferences.relationship == "朋友"
    finally:
        await runtime.stage_manager.close()


@pytest.mark.asyncio
async def test_overwrite_without_stage_is_loaded_by_next_interaction() -> None:
    runtime = make_runtime()
    user_interface = UserInterface(runtime.database_manager, create_media_resolver())
    try:
        await user_interface.overwrite_preference(
            PreferenceOverwriteRequest(username="user", token="token", preferences={"relationship": "朋友"}),
            runtime,
        )
        stage = await runtime.stage_manager.connect(Connection(), "luotianyi")
        assert stage.context.user.read().preferences.relationship == "朋友"
    finally:
        await runtime.stage_manager.close()


@pytest.mark.asyncio
async def test_refresh_preferences_reads_database_without_writing_stale_snapshot(monkeypatch) -> None:
    runtime = make_runtime()
    stage = await runtime.stage_manager.connect(Connection(), "luotianyi")
    conversation = runtime.database_manager.conversation_service
    conversation.preferences = {"relationship": "伙伴", "speaking_style": "轻松", "future_field": "保留"}
    monkeypatch.setattr(conversation, "save_user_preferences", lambda *args: pytest.fail("refresh wrote preferences"))
    try:
        refreshed = await stage.context.user.refresh_preferences()
        assert refreshed.relationship == "伙伴"
        assert refreshed.speaking_style == "轻松"
        assert stage.context.user.read().preferences == refreshed
        assert stage.context.user.read().profile.description == "用户画像"
    finally:
        await runtime.stage_manager.close()


@pytest.mark.asyncio
async def test_failed_preference_save_does_not_dispatch_proposal(monkeypatch) -> None:
    runtime = make_runtime()
    stage = await runtime.stage_manager.connect(Connection(), "luotianyi")
    conversation = runtime.database_manager.conversation_service
    monkeypatch.setattr(conversation, "save_user_preferences", lambda *args: False)
    try:
        with pytest.raises(HTTPException) as error:
            await UserInterface(runtime.database_manager, create_media_resolver()).overwrite_preference(
                PreferenceOverwriteRequest(username="user", token="token", preferences={"relationship": "新关系"}),
                runtime,
            )
        assert error.value.status_code == 404
        assert stage.context.user.read().preferences.relationship == "旧关系"
    finally:
        await runtime.stage_manager.close()


@pytest.mark.asyncio
async def test_invalid_relationship_is_rejected_before_persistence() -> None:
    runtime = make_runtime()
    try:
        with pytest.raises(HTTPException) as error:
            await UserInterface(runtime.database_manager, create_media_resolver()).overwrite_preference(
                PreferenceOverwriteRequest(username="user", token="token", preferences={"relationship": None}),
                runtime,
            )
        assert error.value.status_code == 422
        assert runtime.database_manager.conversation_service.preferences["relationship"] == "旧关系"
    finally:
        await runtime.stage_manager.close()
