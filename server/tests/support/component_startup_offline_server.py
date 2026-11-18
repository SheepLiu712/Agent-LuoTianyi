"""隔离生产入口宿主：只替外部模型接口，不替 runtime/TTS/vector/SQL/Stage。"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import secrets
import shutil
import socket
import sqlite3
import sys
import wave
import weakref
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
WORLD_KEYS = (
    "citywalk",
    "auto_song_learner",
    "qq_music_credential_refresh",
    "song_knowledge",
    "bili_dynamic_fetcher",
    "dynamic_interaction",
    "diary",
    "proactive_topic_check",
    "expired_event_cleanup",
)


def _copy_locked_bundle(resource_dir: Path) -> None:
    """只复制锁列三个代码构建产物；源与副本均核字节指纹。"""
    locked = json.loads((SERVER_ROOT / "scripts/deploy/release/resources.lock.json").read_text(encoding="utf-8"))
    rows = [row for row in locked["files"] if row["path"].startswith("res/admin_ui/admin_static/")]
    assert len(rows) == 3
    for row in rows:
        source = SERVER_ROOT / row["path"]
        target = resource_dir / Path(row["path"]).relative_to("res")
        target.parent.mkdir(parents=True, exist_ok=True)
        before = source.read_bytes()
        assert len(before) == row["size"] and hashlib.sha256(before).hexdigest() == row["sha256"]
        shutil.copyfile(source, target)
        assert target.read_bytes() == before and source.read_bytes() == before


def _rewrite_models(node, prompts: Path) -> None:
    if isinstance(node, dict):
        for name, value in node.items():
            if name == "api_key":
                node[name] = "offline-interface-placeholder"
            elif name == "client_model_type":
                node[name] = ""
            elif name == "base_url":
                node[name] = "http://127.0.0.1:1/never-called"
            elif name == "prompt_name" and isinstance(value, str):
                template = value
                if "reply" in value:
                    template += " {{ reply_topic }}"
                (prompts / f"{value}.json").write_text(
                    json.dumps({"name": value, "template": template}), encoding="utf-8"
                )
            else:
                _rewrite_models(value, prompts)
    elif isinstance(node, list):
        for value in node:
            _rewrite_models(value, prompts)


def prepare_instance(root: Path) -> None:
    """所有路径在导入 server_main 前确定；仅生成测试实例的合法静态材料。"""
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        name: root / directory
        for name, directory in (
            ("CONFIG", "config"),
            ("DATA", "data"),
            ("RUNTIME", "runtime"),
            ("RESOURCE", "resources"),
            ("ASSET", "assets"),
        )
    }
    for name, path in paths.items():
        path.mkdir(exist_ok=True)
        os.environ[f"AGENTLUO_{name}_DIR"] = str(path)
    for name in ("AMAP_KEY", "QWEN_API_KEY", "SILICONFLOW_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(name, None)
    os.environ["JWT_SECRET"] = secrets.token_urlsafe(32)
    config = json.loads((SERVER_ROOT / "config/config.json.template").read_text(encoding="utf-8"))
    config["call_transport"] = {"enabled": False, "realtime_speech": {"enabled": False}}
    config["database"].update(sql_db_folder=str(paths["DATA"] / "database"), sql_db_file="isolated.sqlite")
    config["infrastructure"]["media_resolution"]["root"] = str(paths["DATA"] / "media")
    config["observability"] = {"db_path": str(paths["RUNTIME"] / "observability.sqlite")}
    _copy_locked_bundle(paths["RESOURCE"])
    prompts = paths["RESOURCE"] / "prompts"
    prompts.mkdir()

    _rewrite_models(config, prompts)
    config["llm_service"]["prompt_manager"]["template_dir"] = str(prompts)
    agent = config["agent_runtime"]
    agent["omni_prompt_file"] = None
    agent["skills"]["speaking"] = {"enabled": False}
    agent["vector_store"] = {"enabled": False, "vector_store_path": str(paths["DATA"] / "not-created-vectors")}
    for key in WORLD_KEYS:
        config["world"][key] = {"enabled": False}
    persona = paths["RESOURCE"] / "persona.json"
    persona.write_text(
        json.dumps(
            {
                "character_name": "隔离测试角色",
                "character_persona": "用于验证文字链路",
                "speaking_style": "准确简短",
            }
        ),
        encoding="utf-8",
    )
    tones = paths["RESOURCE"] / "tones.json"
    tones.write_text(
        json.dumps({"llm_tone_to_tts_tone": {"中性": "normal"}, "llm_tone_to_l2d_expression": {"中性": "normal"}}),
        encoding="utf-8",
    )
    character = agent["character_registry"]["characters"]["luotianyi"]
    character.update(static_variables_file=str(persona), llm_tone_mapping_file=str(tones))
    knowledge = paths["DATA"] / "knowledge"
    knowledge.mkdir()
    with sqlite3.connect(knowledge / "knowledge.sqlite") as connection:
        connection.execute(
            "CREATE TABLE songs (uuid VARCHAR PRIMARY KEY, name VARCHAR NOT NULL, safe_name VARCHAR NOT NULL, "
            "uploader VARCHAR, singers VARCHAR, introduction TEXT NOT NULL, lyrics TEXT NOT NULL)"
        )
    for filename in ("names.txt", "lyrics.txt"):
        (knowledge / filename).write_text("", encoding="utf-8")
    agent["skills"]["knowledge"]["song_database"] = {"db_folder": str(knowledge), "db_file": "knowledge.sqlite"}
    agent["skills"]["jargon_recognition"]["song_entity_linker"] = {
        "songname_file": str(knowledge / "names.txt"),
        "lyric_file": str(knowledge / "lyrics.txt"),
    }
    songs = paths["DATA"] / "singing"
    (songs / "songs").mkdir(parents=True)
    agent["skills"]["singing"]["characters"]["luotianyi"]["resource_path"] = str(songs)
    audio = paths["RESOURCE"] / "prepared.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\0\0" * 24)
    manifest = paths["RESOURCE"] / "prepared.json"
    manifest.write_text(
        json.dumps(
            [
                {"name": name, "audio_path": audio.name, "text": "欢迎来到隔离实例", "expression": "normal"}
                for name in ("first_greet_1", "first_greet_2")
            ]
        ),
        encoding="utf-8",
    )
    agent["skills"]["prepared_speech"] = {"characters": {"luotianyi": {"manifest": str(manifest)}}}
    agent["skills"]["touch_reaction"] = {}
    config["chat_session_manager"]["proactive_topic_maker"]["silence_threshold_seconds"] = 3600
    (paths["CONFIG"] / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")


class OfflineInterface:
    """真实 LLMModule 所调用的唯一外部端口；不发 HTTP 请求。"""

    default_parameters = {}
    calls: list[str] = []

    def get_interface_info(self):
        return {"type": "offline-test-interface", "model": "deterministic"}

    def set_parameters(self, **params):
        self.default_parameters = params

    def answer(self, prompt: str) -> str:
        name = prompt.split(" ", 1)[0]
        self.calls.append(name)
        if "topic_extraction" in prompt:
            return '{"memory_attempts":[],"sing_attempts":[]}'
        if "audio" in prompt:
            return '{"transcript":"离线语音测试","emotion":null,"sound_description":null}'
        if "user_profile" in prompt or "profile" in prompt:
            return "NO_UPDATE"
        if "memory" in prompt or "reflect" in prompt:
            return '{"user_memory":[],"event_memory":[]}'
        if "summary" in prompt or "compaction" in prompt:
            return "隔离测试摘要"
        if "reply" in prompt:
            return "[中性]第二条回复" if "第二条" in prompt else "[中性]核心链路412"
        return "{}"

    async def generate_response(self, prompt: str, **kwargs):
        return {"content": self.answer(prompt), "usage": {}, "response_time_s": 0.0}

    async def stream_response(self, prompt: str, **kwargs):
        yield {"content": self.answer(prompt), "usage": {}}


def install_external_interfaces() -> dict[str, int]:
    from src.agent.skills.expression.speaking import backend as speech_backend
    from src.infrastructure.models.audio.interface import AudioModelAPIFactory
    from src.infrastructure.models.llm.interface import LLMAPIFactory
    from src.infrastructure.models.vlm.interface import VLMAPIFactory
    from src.infrastructure.persistence.database import vector_store

    for factory in (LLMAPIFactory, VLMAPIFactory, AudioModelAPIFactory):
        factory.create_interface = staticmethod(lambda config: OfflineInterface())
    forbidden = {"tts": 0, "chroma": 0, "embedding": 0, "vector_executor": 0}

    def trap(name):
        def fail(*args, **kwargs):
            forbidden[name] += 1
            raise AssertionError(f"disabled resource constructed: {name}")

        return fail

    speech_backend.init_tts_module = trap("tts")
    vector_store.chromadb.PersistentClient = trap("chroma")
    vector_store.SiliconFlowEmbeddings = trap("embedding")
    vector_store.ThreadPoolExecutor = trap("vector_executor")
    return forbidden


class RuntimeObserver:
    """只记代号/生命周期事件；弱引用不改变真实运行时的所有权。"""

    def __init__(self):
        self.handles = []
        self.events = []
        self.next_id = 1

    def runtime_id(self, runtime):
        return next((name for name, reference in self.handles if reference() is runtime), None)

    def install(self):
        from src.server_runtime import ServerRuntime

        initialize = ServerRuntime.initialize.__func__
        shutdown = ServerRuntime.shutdown
        observer = self

        async def observed_initialize(cls, *args, **kwargs):
            runtime_id = f"runtime-{observer.next_id}"
            observer.next_id += 1
            observer.events.append({"event": "initialize.begin", "runtime_id": runtime_id})
            runtime = await initialize(cls, *args, **kwargs)
            observer.handles.append((runtime_id, weakref.ref(runtime)))
            observer.events.append({"event": "initialize.complete", "runtime_id": runtime_id})
            return runtime

        async def observed_shutdown(runtime):
            runtime_id = observer.runtime_id(runtime)
            observer.events.append({"event": "shutdown.begin", "runtime_id": runtime_id})
            await shutdown(runtime)
            observer.events.append({"event": "shutdown.complete", "runtime_id": runtime_id})

        ServerRuntime.initialize = classmethod(observed_initialize)
        ServerRuntime.shutdown = observed_shutdown


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    prepare_instance(root)
    forbidden = install_external_interfaces()
    observer = RuntimeObserver()
    observer.install()
    import server_main
    from src.application.server_lifecycle import ServerLifecycle

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    lifecycle = ServerLifecycle(root_dir=SERVER_ROOT, config_path=root / "config/config.json")

    @server_main.app.get("/test/evidence")
    async def evidence():
        shell = lifecycle.admin_shell
        runtime = shell.runtime_supervisor.runtime if shell else None
        if runtime is None:
            return {"running": False}
        world = runtime.world
        return {
            "running": True,
            "runtime_type": type(runtime).__name__,
            "runtime_id": observer.runtime_id(runtime),
            "lifecycle_events": list(observer.events),
            "runtime_source": inspect.getfile(type(runtime)),
            "world_task_count": len(world.tasks),
            "world_interval_count": len(world.world_clock._interval_actions),
            "world_daily_count": len(world.world_clock._daily_actions),
            "world_execution_count": len(world.world_clock.last_results),
            "speaking_enabled": runtime.agent_runtime.skills.speaking.enabled,
            "vector_enabled": runtime.agent_runtime.vector_store.enabled,
            "resource_attempts": forbidden,
            "llm_module_names": sorted(runtime.llm_service.llm_modules),
            "prompt_count": len(runtime.llm_service.prompt_manager.templates),
            "generated_templates": sorted(set(OfflineInterface.calls)),
        }

    @server_main.app.post("/test/stop")
    async def stop():
        server_main.app.state.server.should_exit = True
        return {"ok": True}

    original_server = server_main.uvicorn.Server
    original_config = server_main.uvicorn.Config

    class RecordingServer(original_server):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            server_main.app.state.server = self

    def websocket_config(*args, **kwargs):
        kwargs.setdefault("ws", "websockets")
        return original_config(*args, **kwargs)

    server_main.uvicorn.Server = RecordingServer
    server_main.uvicorn.Config = websocket_config
    (root / "address.json").write_text(json.dumps({"url": url}), encoding="utf-8")
    try:
        asyncio.run(server_main.run_server("127.0.0.1", port, lifecycle=lifecycle))
    finally:
        (root / "closed.json").write_text(json.dumps({"closed": lifecycle.admin_shell is None}), encoding="utf-8")


if __name__ == "__main__":
    main()
