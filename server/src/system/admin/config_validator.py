from __future__ import annotations

import os
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.system.admin.secret_store import SecretStore


@dataclass
class ValidationItem:
    scope: str
    name: str
    status: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "scope": self.scope,
            "name": self.name,
            "status": self.status,
            "severity": self.severity,
            "message": self.message,
        }


class RuntimeConfigValidator:
    """Validate core runtime config and report optional world disablements."""

    REQUIRED_SECRET_KEYS = ["JWT_SECRET", "AMAP_KEY"]

    CORE_LLM_MODULE_PATHS = {
        "database.event_store": "database.event_store.llm_module",
        "database.memory_store": "database.memory_store.llm_module",
        "conversation.summary": "chat_session_manager.conversation_service.llm_module",
        "agent.topic_extractor": "agent_runtime.agent.topic_extractor.llm_module",
        "agent.main_chat": "agent_runtime.agent.main_chat.llm_module",
        "agent.memory_writer": "agent_runtime.agent.memory.memory_writer.llm_module",
        "agent.user_profile": "agent_runtime.agent.memory.user_profile.llm_module",
        "agent.date_detector": "agent_runtime.agent.date_detector.llm_module",
    }

    CORE_VLM_MODULE_PATHS = {
        "capability.image_understanding": "capabilities.image_understanding.vlm_module",
    }

    CORE_RESOURCE_PATHS = {
        "prompt templates": "llm_service.prompt_manager.template_dir",
        "persona": "agent_runtime.character_registry.characters.luotianyi.static_variables_file",
        "tone mapping": "agent_runtime.character_registry.characters.luotianyi.llm_tone_mapping_file",
        "knowledge graph": "agent_runtime.agent.memory.knowledge_graph.graph_data_dir",
    }

    TTS_RESOURCE_KEYS = [
        "reference_audio_dir",
        "reference_audio_lyrics",
        "server_config_path",
        "interface_config_path",
    ]

    def __init__(self, *, root_dir: str | Path, secret_store: SecretStore) -> None:
        self.root_dir = Path(root_dir)
        self.secret_store = secret_store

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        items: list[ValidationItem] = []
        items.extend(self._validate_secrets())
        items.extend(self._validate_llm_interfaces(config))
        items.extend(self._validate_core_modules(config))
        items.extend(self._validate_core_resources(config))
        items.extend(self._validate_world_optionals(config))
        has_core_error = any(item.scope != "world" and item.status == "error" for item in items)
        return {
            "ok": not has_core_error,
            "core_ok": not has_core_error,
            "items": [item.to_dict() for item in items],
            "world_disabled": [
                item.to_dict()
                for item in items
                if item.scope == "world" and item.status in {"disabled", "warning"}
            ],
        }

    def apply_world_disablements(self, config: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
        next_config = copy.deepcopy(config)
        world = next_config.setdefault("world", {})
        for item in validation.get("world_disabled", []):
            if item.get("status") != "disabled":
                continue
            name = item.get("name")
            if name == "citywalk":
                world.setdefault("citywalk", {})["enabled"] = False
            elif name == "bili_dynamic_fetcher":
                world.setdefault("bili_dynamic_fetcher", {})["enabled"] = False
            elif name == "auto_song_learner.qq_music":
                world.setdefault("auto_song_learner", {})["enabled"] = False
        return next_config

    def _validate_secrets(self) -> list[ValidationItem]:
        result = []
        secrets = self.secret_store.read()
        for key in self.REQUIRED_SECRET_KEYS:
            configured = bool(secrets.get(key) or os.environ.get(key))
            result.append(
                ValidationItem(
                    scope="core",
                    name=f"secret.{key}",
                    status="ok" if configured else "error",
                    message="已配置" if configured else f"缺少必需环境变量 {key}",
                )
            )
        return result

    def _validate_llm_interfaces(self, config: dict[str, Any]) -> list[ValidationItem]:
        result: list[ValidationItem] = []
        llm_service = config.get("llm_service", {})
        for kind, key in (("llm", "available_llms"), ("vlm", "available_vlms")):
            interfaces = llm_service.get(key, {})
            if not interfaces:
                result.append(ValidationItem("core", f"{kind}.interfaces", "error", f"未配置任何 {kind.upper()} interface"))
                continue
            for name, item in interfaces.items():
                missing = [field for field in ("api_type", "model", "api_key", "base_url") if not item.get(field)]
                unresolved = str(item.get("api_key", "")).startswith("$")
                if missing or unresolved:
                    msg = f"{name} 配置不完整"
                    if missing:
                        msg += f"，缺少: {', '.join(missing)}"
                    if unresolved:
                        msg += "，api_key 环境变量未解析"
                    result.append(ValidationItem("core", f"{kind}.{name}", "error", msg))
                else:
                    result.append(ValidationItem("core", f"{kind}.{name}", "ok", "配置完整"))
        return result

    def _validate_core_modules(self, config: dict[str, Any]) -> list[ValidationItem]:
        result: list[ValidationItem] = []
        llms = set((config.get("llm_service", {}).get("available_llms") or {}).keys())
        vlms = set((config.get("llm_service", {}).get("available_vlms") or {}).keys())
        for name, path in self.CORE_LLM_MODULE_PATHS.items():
            module = self._get(config, path) or {}
            llm_name = ((module.get("llm") or {}).get("name") or "").strip()
            result.append(self._module_item("llm", name, llm_name, llms))
        for name, path in self.CORE_VLM_MODULE_PATHS.items():
            module = self._get(config, path) or {}
            vlm_name = ((module.get("vlm") or {}).get("name") or "").strip()
            result.append(self._module_item("vlm", name, vlm_name, vlms))
        return result

    def _validate_core_resources(self, config: dict[str, Any]) -> list[ValidationItem]:
        result = []
        for name, path in self.CORE_RESOURCE_PATHS.items():
            raw = self._get(config, path)
            result.append(self._path_item("core", f"resource.{name}", raw))
        result.extend(self._validate_song_knowledge_resources(config))

        tts_cfg = config.get("capabilities", {}).get("tts", {})
        if not tts_cfg:
            result.append(ValidationItem("core", "resource.tts", "error", "未配置 TTS"))
        for character, item in tts_cfg.items():
            for key in self.TTS_RESOURCE_KEYS:
                result.append(self._path_item("core", f"resource.tts.{character}.{key}", item.get(key)))

        sing_cfg = config.get("capabilities", {}).get("sing", {})
        for character, item in sing_cfg.items():
            result.append(self._path_item("core", f"resource.sing.{character}.resource_path", item.get("resource_path")))
        return result

    def _validate_song_knowledge_resources(self, config: dict[str, Any]) -> list[ValidationItem]:
        linker_cfg = self._get(config, "agent_runtime.agent.preprocessing.song_entity_linker") or {}
        songname_file = linker_cfg.get("songname_file") or "res/knowledge/song_name_keywords.txt"
        lyric_file = linker_cfg.get("lyric_file") or linker_cfg.get("lyrics_file") or "res/knowledge/song_lyric_keywords.txt"

        song_db_cfg = self._get(config, "agent_runtime.agent.song_knowledge.song_database") or {}
        db_folder = song_db_cfg.get("db_folder") or "res/knowledge"
        db_file = song_db_cfg.get("db_file") or "knowledge_db.db"
        raw_db_file = Path(str(db_file))
        db_path = raw_db_file if raw_db_file.is_absolute() else Path(str(db_folder)) / raw_db_file

        return [
            self._path_item("core", "resource.song knowledge db", db_path),
            self._path_item("core", "resource.song name keywords", songname_file),
            self._path_item("core", "resource.song lyric keywords", lyric_file),
        ]

    def _validate_world_optionals(self, config: dict[str, Any]) -> list[ValidationItem]:
        result = []
        world = config.get("world", {})
        citywalk_key = self._get(world, "citywalk.amap.api_key")
        result.append(
            ValidationItem(
                "world",
                "citywalk",
                "ok" if citywalk_key and not str(citywalk_key).startswith("$") else "disabled",
                "高德地图 key 已配置" if citywalk_key and not str(citywalk_key).startswith("$") else "缺少 AMAP_KEY，将禁用 citywalk",
                severity="warning",
            )
        )

        bili_cookie = self._get(world, "bili_dynamic_fetcher.bili_cookie_file")
        bili_cookie_path = self._resolve_path(bili_cookie) if bili_cookie else None
        result.append(
            ValidationItem(
                "world",
                "bili_dynamic_fetcher",
                "ok" if bili_cookie_path and bili_cookie_path.exists() and bili_cookie_path.read_text(encoding="utf-8-sig").strip() else "disabled",
                "B站 cookie 已配置" if bili_cookie_path and bili_cookie_path.exists() and bili_cookie_path.read_text(encoding="utf-8-sig").strip() else "缺少 B站 cookie，将禁用 B站动态任务",
                severity="warning",
            )
        )

        qq_credential = self._get(world, "auto_song_learner.qq_credential_file") or "config/qq_music_credential.json"
        qq_path = self._resolve_path(qq_credential)
        legacy_qq_path = self._resolve_path(
            self._get(world, "auto_song_learner.songlearner_resource_dir") or "res/song_learner"
        ) / ".qq_music_credential.json"
        qq_ok = qq_path.exists() and qq_path.stat().st_size > 0
        legacy_qq_ok = legacy_qq_path.exists() and legacy_qq_path.stat().st_size > 0
        qq_message = "QQ音乐 credential 已配置"
        if not qq_ok and legacy_qq_ok:
            qq_message = f"QQ音乐 credential 位于旧路径，启动自动学歌时会迁移到: {qq_path}"
        elif not qq_ok:
            qq_message = "缺少 QQ音乐 credential，自动学歌下载将不可用"
        result.append(
            ValidationItem(
                "world",
                "auto_song_learner.qq_music",
                "ok" if qq_ok or legacy_qq_ok else "disabled",
                qq_message,
                severity="warning",
            )
        )
        return result

    def _module_item(self, kind: str, name: str, interface_name: str, available: set[str]) -> ValidationItem:
        if not interface_name:
            return ValidationItem("core", f"{kind}_module.{name}", "error", "模块未绑定 interface")
        if interface_name not in available:
            return ValidationItem("core", f"{kind}_module.{name}", "error", f"绑定的 interface 不存在: {interface_name}")
        return ValidationItem("core", f"{kind}_module.{name}", "ok", f"已绑定 {interface_name}")

    def _path_item(self, scope: str, name: str, raw: Any) -> ValidationItem:
        if not raw:
            return ValidationItem(scope, name, "error", "路径未配置")
        path = self._resolve_path(raw)
        return ValidationItem(
            scope,
            name,
            "ok" if path.exists() else "error",
            f"存在: {path}" if path.exists() else f"文件或目录不存在: {path}",
        )

    def _resolve_path(self, raw: Any) -> Path:
        path = Path(str(raw))
        if path.is_absolute():
            return path
        return self.root_dir / path

    @staticmethod
    def _get(data: dict[str, Any], path: str) -> Any:
        current: Any = data
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current
