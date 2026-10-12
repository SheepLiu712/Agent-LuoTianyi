"""Offline loopback host for the successful call.v1 E2E acceptance flow."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import wave
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

import server_main
import src.agent.skills.expression.speaking.backend as speaking_backend
import src.agent_runtime.agent_runtime as agent_runtime_module
import src.server_runtime as server_runtime_module
from src.application.server_lifecycle import ServerLifecycle
from support.call_coherent_runtime import DeterministicCallTTSModule, DeterministicLLMService, DeterministicVectorStore
from support.realtime_speech import FakeRealtimeSpeechSessionFactory


class _DeterministicSpeechFactory:
    """Factory seam installed before ServerRuntime initializes its provider."""

    instance: FakeRealtimeSpeechSessionFactory | None = None

    @classmethod
    def from_mapping(cls, _config: object, **_kwargs) -> FakeRealtimeSpeechSessionFactory:
        cls.instance = FakeRealtimeSpeechSessionFactory()
        return cls.instance


class _AddressPublishingLifecycle(ServerLifecycle):
    def __init__(self, *, root_dir: Path, config_path: Path, address_path: Path, url: str) -> None:
        super().__init__(root_dir=root_dir, config_path=config_path)
        self._address_path = address_path
        self._url = url

    async def start(self, **kwargs) -> dict:
        status = await super().start(**kwargs)
        if not status["running"]:
            raise RuntimeError(f"production runtime did not become ready: {status}")
        from src.infrastructure.persistence.database import InviteCode

        runtime = self.admin_shell.runtime_supervisor.runtime  # type: ignore[union-attr]
        with runtime.database_manager.open_sql_session() as session:
            if session.query(InviteCode).filter_by(code="invite").one_or_none() is None:
                session.add(InviteCode(code="invite", is_used=False))
                session.commit()
        self._address_path.write_text(json.dumps({"url": self._url}), encoding="utf-8")
        return status


def _runtime_config(root: Path) -> Path:
    source = Path(server_main.current_dir) / "config" / "config.json"
    config = json.loads(source.read_text(encoding="utf-8"))
    config["call_transport"] = {
        "enabled": True,
        "realtime_speech": {
            "enabled": True,
            "api_key": "offline-provider-key",
            "model": "offline-realtime",
            "endpoint": "wss://offline.invalid/realtime",
        },
    }
    config["database"]["sql_db_folder"] = str(root / "db")
    config["database"]["sql_db_file"] = "calls.sqlite"
    config["infrastructure"]["media_resolution"]["root"] = str(root / "media")
    resources = root / "resources"
    resources.mkdir(exist_ok=True)
    for name in ("knowledge.db", "song_names.txt", "song_lyrics.txt", "lyrics.json", "tts.yaml", "interface.json"):
        path = resources / name
        if not path.exists():
            path.write_text("{}" if name.endswith(".json") else "", encoding="utf-8")
    for name in ("reference_audio", "songs"):
        (resources / name).mkdir(exist_ok=True)
    (resources / "songs" / "songs").mkdir(exist_ok=True)
    agent = config["agent_runtime"]
    agent["agent"]["song_knowledge"]["song_database"] = {
        "db_folder": str(resources),
        "db_file": "knowledge.db",
    }
    agent["agent"]["preprocessing"]["song_entity_linker"] = {
        "songname_file": str(resources / "song_names.txt"),
        "lyric_file": str(resources / "song_lyrics.txt"),
    }
    speaking = agent["skills"]["speaking"]["characters"]["luotianyi"]
    speaking.update(
        {
            "reference_audio_dir": str(resources / "reference_audio"),
            "reference_audio_lyrics": str(resources / "lyrics.json"),
            "server_config_path": str(resources / "tts.yaml"),
            "interface_config_path": str(resources / "interface.json"),
        }
    )
    agent["skills"]["singing"]["characters"]["luotianyi"]["resource_path"] = str(resources / "songs")
    agent["character_registry"]["characters"]["luotianyi"]["reflex"] = {}
    apology = resources / "call-apology.wav"
    with wave.open(str(apology), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 480)
    manifest = resources / "prepared.json"
    manifest.write_text(
        json.dumps([{"name": "call_apology", "audio_path": apology.name, "text": "Sorry", "expression": "normal"}]),
        encoding="utf8",
    )
    agent["prepared_speech"] = {"characters": {"luotianyi": {"manifest": str(manifest)}}}
    _resolve_test_environment(config)
    path = root / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def _resolve_test_environment(value: object) -> None:
    if isinstance(value, dict):
        for key, child in tuple(value.items()):
            if isinstance(child, str) and child.startswith("$"):
                value[key] = "offline-config-value"
            else:
                _resolve_test_environment(child)
    elif isinstance(value, list):
        for child in value:
            _resolve_test_environment(child)


def _install_external_seams() -> None:
    vector = DeterministicVectorStore()
    agent_runtime_module.init_vector_store = lambda _config: vector
    agent_runtime_module.get_vector_store = lambda: vector
    agent_runtime_module.clear_vector_store = lambda expected: expected is vector
    speaking_backend.init_tts_module = lambda _config: DeterministicCallTTSModule()
    server_runtime_module.LLMService = DeterministicLLMService
    server_runtime_module.AliyunRealtimeSpeechSessionFactory = _DeterministicSpeechFactory


def main() -> None:  # noqa: C901 - production-loopback support exposes bounded evidence routes
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["JWT_SECRET"] = "call-network-success-isolated-secret"
    os.environ["AMAP_KEY"] = "offline-amap-key"
    os.environ["QWEN_API_KEY"] = "offline-qwen-key"
    _install_external_seams()
    config_path = _runtime_config(root)

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    lifecycle = _AddressPublishingLifecycle(
        root_dir=Path(server_main.current_dir),
        config_path=config_path,
        address_path=root / "address.json",
        url=url,
    )

    @server_main.app.get("/test/evidence")
    async def evidence():
        runtime = lifecycle.admin_shell.runtime_supervisor.runtime if lifecycle.admin_shell is not None else None
        provider = _DeterministicSpeechFactory.instance
        return {
            "call_transport_available": runtime.call_transport_available if runtime is not None else False,
            "provider_audio": provider.evidence() if provider is not None else [],
        }

    @server_main.app.get("/test/reset_counts")
    async def reset_counts():
        from src.infrastructure.persistence.database.sql_database import (
            AgentMemoryRecord,
            CallMaintenanceBatch,
            CallSession,
            Conversation,
            User,
        )

        runtime = lifecycle.admin_shell.runtime_supervisor.runtime
        with runtime.database_manager.open_sql_session() as session:
            user = session.query(User).filter_by(username="alice").one_or_none()
            user_id = None if user is None else user.uuid
            return {
                "call_sessions": (
                    0 if user_id is None else session.query(CallSession).filter_by(user_id=user_id).count()
                ),
                "conversations": (
                    0 if user_id is None else session.query(Conversation).filter_by(user_id=user_id).count()
                ),
                "maintenance_batches": (
                    0 if user_id is None else session.query(CallMaintenanceBatch).filter_by(user_id=user_id).count()
                ),
                "memories": (
                    0
                    if user_id is None
                    else session.query(AgentMemoryRecord).filter_by(subject_user_id=user_id).count()
                ),
                "profile": None if user is None else user.description,
            }

    @server_main.app.post("/test/seed_stale_calls")
    async def seed_stale_calls():
        from src.domain.call import CallState
        from src.infrastructure.persistence.call_sessions import CallSessionRecord
        from src.infrastructure.persistence.database.sql_database import User

        runtime = lifecycle.admin_shell.runtime_supervisor.runtime
        with runtime.database_manager.open_sql_session() as session:
            user = session.query(User).filter_by(username="alice").one()
            user_id = user.uuid
        now = datetime.now(timezone.utc)
        preparing = CallSessionRecord(
            call_id=uuid4(),
            client_request_id=f"restart-preparing-{uuid4()}",
            user_id=user_id,
            character_id="luotianyi",
            state=CallState.PREPARING,
            requested_at=now - timedelta(minutes=4),
            created_at=now - timedelta(minutes=4),
            updated_at=now,
        )
        active = CallSessionRecord(
            call_id=uuid4(),
            client_request_id=f"restart-active-{uuid4()}",
            user_id=user_id,
            character_id="luotianyi",
            state=CallState.ACTIVE,
            requested_at=now - timedelta(minutes=4),
            created_at=now - timedelta(minutes=4),
            updated_at=now,
            connected_at=now - timedelta(seconds=90),
            disconnected_at=now - timedelta(seconds=45),
            active_duration_ms=20_000,
        )
        runtime.database_manager.call_sessions.create_if_absent(preparing)
        runtime.database_manager.call_sessions.create_if_absent(active)
        return {"preparing_call_id": str(preparing.call_id), "active_call_id": str(active.call_id)}

    @server_main.app.post("/test/seed_recovery_conflict")
    async def seed_recovery_conflict():
        from src.domain.call import CallEndReason, CallOutcome, CallState, derive_call_conversation_id
        from src.domain.conversation_type import ConversationItem
        from src.infrastructure.persistence.call_sessions import CallSessionRecord
        from src.infrastructure.persistence.database.sql_database import User

        runtime = lifecycle.admin_shell.runtime_supervisor.runtime
        with runtime.database_manager.open_sql_session() as session:
            user = session.query(User).filter_by(username="alice").one()
            user_id = user.uuid
        now = datetime.now(timezone.utc)
        call_id = uuid4()
        record = CallSessionRecord(
            call_id=call_id,
            client_request_id=f"restart-conflict-{uuid4()}",
            user_id=user_id,
            character_id="luotianyi",
            state=CallState.ENDED,
            requested_at=now - timedelta(minutes=4),
            created_at=now - timedelta(minutes=4),
            updated_at=now - timedelta(minutes=3),
            connected_at=now - timedelta(seconds=90),
            ended_at=now - timedelta(seconds=45),
            outcome=CallOutcome.CONNECTED,
            end_reason=CallEndReason.SYSTEM_FAILURE,
            active_duration_ms=20_000,
        )
        runtime.database_manager.call_sessions.create_if_absent(record)
        conversation_id = derive_call_conversation_id(user_id=user_id, character_id="luotianyi", call_id=call_id)
        runtime.database_manager.conversation_service.add_call_conversation(
            user_id,
            "luotianyi",
            ConversationItem(
                uuid=str(conversation_id),
                timestamp=record.requested_at.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds"),
                source="user",
                type="call",
                content="[语音通话]冲突投影",
                data={
                    "call_id": str(call_id),
                    "outcome": "connected",
                    "active_duration_ms": 20_000,
                    "summary": "冲突投影",
                    "end_reason": "user_hangup",
                },
            ),
        )
        return {"call_id": str(call_id)}

    @server_main.app.get("/test/recovery_counts")
    async def recovery_counts():
        from src.infrastructure.persistence.database.sql_database import (
            CallMaintenanceBatch,
            CallSession,
            Conversation,
            User,
        )

        runtime = lifecycle.admin_shell.runtime_supervisor.runtime
        with runtime.database_manager.open_sql_session() as session:
            user = session.query(User).filter_by(username="alice").one()
            calls = session.query(CallSession).filter_by(user_id=user.uuid).all()
            return {
                "calls": [
                    {
                        "call_id": row.call_id,
                        "state": row.state,
                        "summary_status": row.summary_status,
                        "maintenance_status": row.maintenance_status,
                        "conversation_id": row.conversation_id,
                    }
                    for row in calls
                ],
                "call_conversations": session.query(Conversation).filter_by(user_id=user.uuid, type="call").count(),
                "maintenance_batches": session.query(CallMaintenanceBatch).filter_by(user_id=user.uuid).count(),
            }

    @server_main.app.post("/test/stop")
    async def stop():
        server_main.app.state.server.should_exit = True
        return {"ok": True}

    @server_main.app.post("/test/provider/{call_id}/turn")
    async def emit_turn(call_id: str):
        from src.domain.call import CallAudioSemantic
        from src.infrastructure.models.realtime_speech import TurnCompleted

        provider = _provider(call_id)
        await provider.emit(TurnCompleted(CallAudioSemantic(transcript="你还记得我喜欢什么吗")))
        return {"ok": True}

    @server_main.app.post("/test/provider/{call_id}/interrupt")
    async def interrupt(call_id: str):
        from src.infrastructure.models.realtime_speech import SpeechStarted, SpeechStopped

        provider = _provider(call_id)
        await provider.emit(SpeechStarted())
        await asyncio.sleep(0)
        await provider.emit(SpeechStopped())
        return {"ok": True}

    def _provider(call_id: str):
        from uuid import UUID

        provider = _DeterministicSpeechFactory.instance
        try:
            return provider.sessions[UUID(call_id)]  # type: ignore[union-attr]
        except (KeyError, ValueError) as error:
            raise HTTPException(status_code=404, detail="unknown call") from error

    server_main.uvicorn.Config = _server_config_with_websockets(server_main.uvicorn.Config)
    original_server = server_main.uvicorn.Server

    class RecordingServer(original_server):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            server_main.app.state.server = self

    server_main.uvicorn.Server = RecordingServer
    asyncio.run(server_main.run_server("127.0.0.1", port, lifecycle=lifecycle))


def _server_config_with_websockets(config_type):
    def make_config(*args, **kwargs):
        kwargs.setdefault("ws", "websockets")
        return config_type(*args, **kwargs)

    return make_config


if __name__ == "__main__":
    main()
