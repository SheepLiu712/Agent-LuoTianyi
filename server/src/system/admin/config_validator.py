from __future__ import annotations

import os
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.system.admin.secret_store import SecretStore
from src.system.database.utils import (
    DEFAULT_MESSAGE_TOKEN_TTL_SECONDS,
    MAX_MESSAGE_TOKEN_TTL_SECONDS,
    MIN_MESSAGE_TOKEN_TTL_SECONDS,
)


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
        "capability.singing.song_emotion_tagger": "capabilities.sing.song_emotion_tagger",
        "capability.diary": "capabilities.diary.diary_llm.llm_module",
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
        items.extend(self._validate_security_config(config))
        items.extend(self._validate_llm_interfaces(config))
        items.extend(self._validate_client_model_types(config))
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

    def _validate_security_config(self, config: dict[str, Any]) -> list[ValidationItem]:
        name = "config.database.message_token_ttl_seconds"
        database_config = config.get("database")
        if (
            not isinstance(database_config, dict)
            or "message_token_ttl_seconds" not in database_config
        ):
            return [
                ValidationItem(
                    "core",
                    name,
                    "warning",
                    (
                        "未配置 message_token_ttl_seconds，使用安全默认值 "
                        f"{DEFAULT_MESSAGE_TOKEN_TTL_SECONDS} 秒"
                    ),
                    severity="warning",
                )
            ]
        value = database_config["message_token_ttl_seconds"]
        if type(value) is not int:
            return [
                ValidationItem(
                    "core",
                    name,
                    "error",
                    "message_token_ttl_seconds 必须是整数秒数",
                )
            ]
        if not MIN_MESSAGE_TOKEN_TTL_SECONDS <= value <= MAX_MESSAGE_TOKEN_TTL_SECONDS:
            return [
                ValidationItem(
                    "core",
                    name,
                    "error",
                    (
                        "message_token_ttl_seconds 必须在 "
                        f"{MIN_MESSAGE_TOKEN_TTL_SECONDS} 至 "
                        f"{MAX_MESSAGE_TOKEN_TTL_SECONDS} 秒之间"
                    ),
                )
            ]
        return [ValidationItem("core", name, "ok", f"消息令牌有效期为 {value} 秒")]

    def _validate_llm_interfaces(self, config: dict[str, Any]) -> list[ValidationItem]:
        result: list[ValidationItem] = []
        llm_service = config.get("llm_service", {})
        for kind, key in (("llm", "available_llms"), ("vlm", "available_vlms")):
            interfaces = llm_service.get(key, {})
            if not interfaces:
                result.append(ValidationItem("core", f"{kind}.interfaces", "error", f"未配置任何 {kind.upper()} interface"))
                continue
            for name, item in interfaces.items():
                missing = [field for field in ("api_type", "model", "base_url") if not item.get(field)]
                unresolved = str(item.get("api_key", "")).startswith("$")
                if missing or unresolved:
                    msg = f"{name} 配置不完整"
                    if missing:
                        msg += f"，缺少: {', '.join(missing)}"
                    if unresolved:
                        msg += "，api_key 环境变量未解析"
                    result.append(ValidationItem("core", f"{kind}.{name}", "error", msg))
                else:
                    api_key = item.get("api_key")
                    if not api_key or str(api_key).strip() == "":
                        msg = "配置完整，当前接口已启用客户端模式"
                    else:
                        msg = "配置完整，当前接口已启用兼容模式（客户端可回退使用服务端api_key）"
                    result.append(ValidationItem("core", f"{kind}.{name}", "ok", msg))
        return result

    def _validate_client_model_types(self, config: dict[str, Any]) -> list[ValidationItem]:
        """校验客户端委托需求及其模块绑定。"""
        result: list[ValidationItem] = []
        llm_service = config.get("llm_service", {})
        raw = llm_service.get("client_model_types")
        if not isinstance(raw, list) or not raw:
            result.append(
                ValidationItem(
                    "core",
                    "client_model_types",
                    "error",
                    "未配置任何客户端模型类型（至少需要一个需求类型）",
                )
            )

        seen_ids: set[str] = set()
        type_requirements: dict[str, dict[str, Any]] = {}
        valid_type_count = 0
        for index, item in enumerate(raw or []):
            if not isinstance(item, dict):
                continue
            label = f"client_model_types[{index}]"
            type_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            model_kind = str(item.get("model_kind") or "").strip().lower()
            if not type_id:
                result.append(
                    ValidationItem("core", label, "error", "类型 ID 不能为空")
                )
                continue
            if type_id in seen_ids:
                result.append(
                    ValidationItem("core", label, "error", f"类型 ID 重复: {type_id}")
                )
                continue
            seen_ids.add(type_id)
            if not name:
                result.append(ValidationItem("core", label, "error", "显示名称不能为空"))
                continue
            if model_kind not in {"llm", "vlm"}:
                result.append(
                    ValidationItem("core", label, "error", "模型类型必须是 llm 或 vlm")
                )
                continue
            type_requirements[type_id] = {
                "model_kind": model_kind,
                "requires_json": bool(item.get("requires_json", False)),
                "requires_thinking": bool(item.get("requires_thinking", False)),
            }
            valid_type_count += 1
            result.append(
                ValidationItem(
                    "core",
                    f"client_model_types.{type_id}",
                    "ok",
                    f"{model_kind.upper()} / JSON={'是' if item.get('requires_json') else '否'} / thinking={'是' if item.get('requires_thinking') else '否'}",
                )
            )

        if valid_type_count:
            result.append(
                ValidationItem(
                    "core",
                    "client_model_types",
                    "ok",
                    f"已配置 {valid_type_count} 个客户端模型类型",
                )
            )

        for binding in self._collect_client_model_bindings(config):
            path = binding["path"]
            model_type = binding["model_type"]
            requirement = type_requirements.get(model_type)
            if model_type and requirement is None:
                result.append(
                    ValidationItem(
                        "core",
                        f"binding.{path}",
                        "error",
                        f"客户端委托绑定引用不存在的类型: {model_type}",
                    )
                )
                continue
            if not requirement:
                continue
            if requirement["model_kind"] != binding["kind"]:
                result.append(
                    ValidationItem(
                        "core",
                        f"binding.{path}",
                        "error",
                        f"客户端类型 {model_type} 是 {requirement['model_kind']}，不能绑定到 {binding['kind']} 模块",
                    )
                )
            if binding["use_json"] and not requirement["requires_json"]:
                result.append(
                    ValidationItem(
                        "core",
                        f"binding.{path}",
                        "error",
                        f"模块要求 JSON，但客户端类型 {model_type} 未声明 requires_json",
                    )
                )
            if binding["enable_thinking"] and not requirement["requires_thinking"]:
                result.append(
                    ValidationItem(
                        "core",
                        f"binding.{path}",
                        "error",
                        f"模块要求 thinking，但客户端类型 {model_type} 未声明 requires_thinking",
                    )
                )
        return result

    def _collect_client_model_bindings(
        self, config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """收集所有 llm/vlm 配置中声明的 client_model_type（路径, 类型名）。"""
        bindings: list[dict[str, Any]] = []

        def walk(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for kind in ("llm", "vlm"):
                    cfg = value.get(kind)
                    if isinstance(cfg, dict):
                        model_type = str(cfg.get("client_model_type") or "").strip()
                        if model_type:
                            bindings.append(
                                {
                                    "path": f"{path}.{kind}",
                                    "model_type": model_type,
                                    "kind": kind,
                                    "enable_thinking": bool(
                                        value.get("enable_thinking", cfg.get("enable_thinking", False))
                                    ),
                                    "use_json": bool(
                                        value.get("use_json", cfg.get("use_json", False))
                                    ),
                                }
                            )
                for key, item in value.items():
                    walk(item, f"{path}.{key}" if path else str(key))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, f"{path}.{index}" if path else str(index))

        walk(config, "")
        return bindings

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
        characters_cfg = sing_cfg.get("characters")
        if not isinstance(characters_cfg, dict) or not characters_cfg:
            result.append(ValidationItem("core", "resource.sing.characters", "error", "未配置任何角色歌曲资源"))
        else:
            for character, item in characters_cfg.items():
                result.append(
                    self._path_item(
                        "core",
                        f"resource.sing.characters.{character}.resource_path",
                        item.get("resource_path"),
                    )
                )
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
