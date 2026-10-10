"""Deterministic external ports for the production call component graph."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from src.infrastructure.persistence.database.vector_store import Document


class DeterministicLLMModule:
    def __init__(self, name: str) -> None:
        self.name = name
        self.prompt_template = SimpleNamespace(get_variables=lambda: [])
        self.calls: list[dict[str, object]] = []

    async def generate_response(self, **kwargs) -> str:
        self.calls.append(kwargs)
        if self.name == "call_recall":
            if "silence_ms" in kwargs:
                return json.dumps({"decision": "end_call"})
            return json.dumps(
                {
                    "mode": "recall",
                    "memory_queries": ["用户喜欢的音乐"],
                    "ack_style": "thinking",
                }
            )
        if self.name.endswith("main_chat"):
            topic = str(kwargs.get("reply_topic") or "")
            if "刚刚接通" in topic:
                return "[中性]你好，我在这里。"
            if "告别" in topic:
                return "[中性]那我们下次再聊，再见。"
            return "[中性]我记得你喜欢音乐，我们继续聊吧。"
        if self.name.endswith("user_profile_updater"):
            return "NO_UPDATE"
        return "{}"


class DeterministicLLMService:
    def __init__(self) -> None:
        self.modules: dict[str, DeterministicLLMModule] = {}

    def register_llm_module(self, name, _config):
        module = DeterministicLLMModule(name)
        self.modules[name] = module
        return module

    def register_vlm_module(self, name, _config):
        return DeterministicLLMModule(name)

    def register_audio_model_module(self, name, _config):
        return DeterministicLLMModule(name)


class DeterministicVectorStore:
    def __init__(self) -> None:
        self.searches: list[tuple[str, str, int]] = []
        self.closed = False

    async def search(self, user_id: str, query: str, k: int = 5, **_kwargs):
        self.searches.append((user_id, query, k))
        return [(Document("用户喜欢音乐", {"user_id": user_id}, id="memory-vector-1"), 0.95)]

    def add_documents(self, _documents):
        return []

    def upsert_documents(self, _documents, ids):
        return list(ids)

    def delete_documents(self, _doc_ids):
        return True

    def update_document(self, _doc_id, _document):
        return True

    def get_document_by_id(self, _doc_ids):
        return []

    def delete_user_records(self, _user_id):
        return 0

    def close(self):
        self.closed = True


class DeterministicCallTTSModule:
    """External TTS backend fake; production SpeakingSkill/AsyncTTS remain real."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.formal_started = threading.Event()
        self.formal_cancelled = threading.Event()

    def stream_synthesize_call_pcm_with_tone(self, text, _tone, *, cancel_event):
        self.calls.append(text)
        if "我记得你喜欢音乐" not in text:
            yield b"\x01\x00\x02\x00"
            return
        self.formal_started.set()
        yield b"\x03\x00\x04\x00"
        yield b"\x05\x00\x06\x00"
        cancel_event.wait()
        if cancel_event.is_set():
            self.formal_cancelled.set()

    def stream_synthesize_speech_with_tone(self, text, tone, *, cancel_event):
        yield from self.stream_synthesize_call_pcm_with_tone(text, tone, cancel_event=cancel_event)


class NoopMediaResolver:
    def resolve(self, *_args, **_kwargs):
        raise AssertionError("call component evidence must not resolve media")

    def ensure_dependencies(self):
        return None


def runtime_config(tmp_path) -> dict[str, object]:
    persona = tmp_path / "persona.json"
    persona.write_text(
        json.dumps(
            {
                "character_name": "测试角色",
                "character_persona": "温柔可靠",
                "speaking_style": "自然简短",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tones = tmp_path / "tones.json"
    tones.write_text(
        json.dumps(
            {
                "llm_tone_to_tts_tone": {"中性": "normal"},
                "llm_tone_to_l2d_expression": {"中性": "smile"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    songs = tmp_path / "songs"
    songs.mkdir()
    return {
        "skills": {
            "speaking": {"characters": {"luotianyi": {}}},
            "singing": {"characters": {"luotianyi": {"resource_path": str(songs)}}},
        },
        "prepared_speech": {"characters": {}},
        "character_registry": {
            "characters": {
                "luotianyi": {
                    "default_target": True,
                    "static_variables_file": str(persona),
                    "llm_tone_mapping_file": str(tones),
                }
            }
        },
        "agent": {
            "memory": {
                "memory_writer": {"llm_module": {}},
                "user_profile": {"llm_module": {}},
            },
            "main_chat": {"llm_module": {}},
            "call_recall": {"llm_module": {}},
        },
    }
