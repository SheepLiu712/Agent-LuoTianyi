"""Isolated loopback server for AC-27. Only models and long-term memory are fakes."""

import io
import json
import os
import socket
import sys
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI

import src.domain.agent as d
from src.adapter.websocket.chat import WebSocketAdapter
from src.agent import Agent
from src.agent.context import ContextFactory
from src.agent.handlers.action.cognitive_maintenance import CognitiveMaintenanceActionHandler
from src.agent.handlers.action.router import ActionRouter
from src.agent.handlers.action.say import SayHandler
from src.agent.handlers.reply_skills import ReplySkills
from src.agent.handlers.stimulus.chat import ChatPreprocessingHandler, ChatReplyHandler
from src.agent.handlers.stimulus.interaction import InteractionEndingHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive import AudioUnderstandingSkill, JargonRecognitionSkill, TopicExtractionSkill
from src.agent.skills.cognitive._reply_resources import ReplyResources
from src.agent.skills.cognitive_maintenance import CognitiveMaintenanceSkill
from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog
from src.agent.skills.expression.speaking import SpeakingSkill
from src.domain import CharacterProfile
from src.infrastructure.media import PermanentMediaStore, create_media_resolver
from src.infrastructure.persistence.database import DatabaseManager, InviteCode
from src.web.http import routes
from src.web.http.user_interface import UserInterface
from src.web.websocket import endpoint
from src.web.websocket.service import WebSocketService
from support.reply_skill import make_reply_skill
from support.retrieval import stub_retrieval, stub_singing
from support.stage_manager import make_stage_manager


class OfflineModels:
    def __init__(self):
        self.audio_calls = 0
        self.reply_calls = 0
        self.prompt_template = SimpleNamespace(get_variables=lambda: [])

    async def generate_response(self, **kwargs):
        if "audio_base64" in kwargs:
            self.audio_calls += 1
            assert kwargs["audio_base64"].startswith("data:audio/mp4;base64,")
            return {"content": json.dumps({"transcript": "测试语音请求", "emotion": "平静", "sound_description": None})}
        self.reply_calls += 1
        assert "测试语音请求" in kwargs["reply_topic"]
        return "[中性]收到你的测试语音了。"

    async def stream(self, **kwargs):
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 2400)
        yield output.getvalue()


class OfflineMemory:
    async def extract_maintenance_candidates(self, **kwargs):
        return ()

    async def propose_user_profile(self, **kwargs):
        return None

    async def write_maintenance_candidates(self, **kwargs):
        return None


def make_agent(root, resolver, models):
    persona = root / "persona.json"
    persona.write_text(
        json.dumps({"character_name": "天依", "character_persona": "离线测试", "speaking_style": "自然"}),
        encoding="utf-8",
    )
    tones = root / "tones.json"
    tones.write_text("{}", encoding="utf-8")
    profile = CharacterProfile(
        "luotianyi", "天依", "offline", static_variables_file=str(persona), llm_tone_mapping_file=str(tones)
    )
    text = JargonRecognitionSkill()
    memory = {"luotianyi": OfflineMemory()}
    # TTS 的 stream 方法与文本模型的 stream 布尔配置属于不同接口。
    reply_model = SimpleNamespace(
        stream=False, prompt_template=models.prompt_template, generate_response=models.generate_response
    )
    composition = ReplySkills(
        retrieval=stub_retrieval(memory),
        singing=stub_singing(None),
        reply=make_reply_skill({"luotianyi": ReplyResources({}, reply_model, profile)}),
        topic_extraction=TopicExtractionSkill({}, None, understanding=text),
    )
    preprocessing = ChatPreprocessingHandler(
        text,
        audio_understanding=AudioUnderstandingSkill(
            {}, resolver, llm_service=SimpleNamespace(register_audio_model_module=lambda *args: models)
        ),
    )
    return Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            (
                (d.StimulusKind.VOICE_MESSAGE, preprocessing),
                (d.StimulusKind.INTERACTION_DEADLINE, ChatReplyHandler(composition)),
                (d.StimulusKind.INTERACTION_ENDING, InteractionEndingHandler()),
            )
        ),
        action_router=ActionRouter(
            (
                (
                    d.ActionKind.SAY,
                    SayHandler("luotianyi", SpeakingSkill({}, tts_engine=models), PreparedSpeechCatalog({})),
                ),
                (
                    d.ActionKind.COGNITIVE_MAINTENANCE,
                    CognitiveMaintenanceActionHandler(
                        "luotianyi",
                        CognitiveMaintenanceSkill({}, llm_service=None, memories=memory),
                    ),
                ),
            )
        ),
    )


def make_runtime(root):
    os.environ["JWT_SECRET"] = "offline-e2e-isolated-secret-not-for-production"
    database = DatabaseManager({"sql_db_folder": str(root / "db"), "sql_db_file": "voice.sqlite"})
    users = {}
    for name in ("alice", "bob"):
        with database.open_sql_session() as session:
            session.add(InviteCode(code=name, is_used=False))
            session.commit()
        ok, message = database.credential_service.register_user(name, "offline-password", name)
        assert ok, message
        # Existing-user scenario avoids unrelated welcome/reminder plans.
        users[name] = database.credential_service.authenticate_password_login(name, "offline-password")["user_uuid"]
    config = {"media_store": {"root": str(root / "media")}}
    resolver = create_media_resolver(config["media_store"])
    models = OfflineModels()
    agent = make_agent(root, resolver, models)
    adapter = WebSocketAdapter(config)
    factory = ContextFactory(character_id="luotianyi", database=database.conversation_service)
    manager = make_stage_manager(get_agent=lambda _: agent, adapter=adapter, get_context_factory=lambda _: factory)
    interface = UserInterface(database, resolver)
    interface.generate_rsa_keys()
    return SimpleNamespace(
        database_manager=database,
        user_interface=interface,
        stage_manager=manager,
        agent_runtime=SimpleNamespace(default_character_id="luotianyi"),
        chat_adapter=adapter,
        websocket_service=WebSocketService(),
        client_llm_executor=SimpleNamespace(clear_user=lambda *_: None),
        users=users,
        models=models,
        store=PermanentMediaStore(config["media_store"]),
    )


def main():
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    runtime = make_runtime(root)
    endpoint.get_admin_shell = lambda: SimpleNamespace(runtime_supervisor=SimpleNamespace(runtime=runtime))

    @asynccontextmanager
    async def lifespan(app):
        yield
        await runtime.stage_manager.close()
        await runtime.database_manager.shutdown()

    app = FastAPI(lifespan=lifespan)
    app.dependency_overrides[routes.get_runtime] = lambda: runtime
    app.include_router(routes.router)
    app.include_router(endpoint.router)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", ws="websockets"))

    @app.get("/test/evidence")
    async def evidence():
        return {"audio_calls": runtime.models.audio_calls, "reply_calls": runtime.models.reply_calls}

    @app.post("/test/delete-media/{username}")
    async def delete_media(username: str):
        runtime.store.delete_owned_by(owner_user_id=runtime.users[username])
        return {"ok": True}

    @app.post("/test/stop")
    async def stop():
        server.should_exit = True
        return {"ok": True}

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        (root / "address.json").write_text(
            json.dumps({"url": f"http://127.0.0.1:{listener.getsockname()[1]}"}), encoding="utf-8"
        )
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
