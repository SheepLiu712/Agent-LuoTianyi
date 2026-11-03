"""统一技能配置的解析与旧配置迁移检查。"""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillsConfig:
    """配置加载阶段校验后的技能节点；不包含连接与角色注册配置。"""

    values: dict[str, Any]

    @staticmethod
    def reject_legacy_summary(config: dict[str, Any]) -> None:
        if "conversation_service" in config.get("chat_session_manager", {}):
            raise ValueError(
                "chat_session_manager.conversation_service 已停用，请迁移到 "
                "agent_runtime.skills.cognitive_maintenance.conversation_compaction"
            )

    @classmethod
    def from_runtime(cls, runtime: dict[str, Any]) -> "SkillsConfig":
        obsolete = ("agent", "prepared_speech", "reply_composition")
        for key in obsolete:
            if key in runtime:
                raise ValueError(f"agent_runtime.{key} 已停用，请迁移到 agent_runtime.skills")
        for character_id, profile in runtime.get("character_registry", {}).get("characters", {}).items():
            if "touch" in profile.get("reflex", {}):
                raise ValueError(
                    f"agent_runtime.character_registry.characters.{character_id}.reflex.touch 已停用，"
                    "请迁移到 agent_runtime.skills.touch_reaction.characters"
                )
        values = runtime.get("skills")
        if not isinstance(values, dict):
            raise TypeError("agent_runtime.skills 必须是字典")
        if "conversation_compaction" in values:
            raise ValueError("agent_runtime.skills.conversation_compaction 请迁移到 skills.cognitive_maintenance")
        for key, value in values.items():
            if not isinstance(value, dict):
                raise TypeError(f"agent_runtime.skills.{key} 必须是字典")
        for key in ("reply", "memory_write"):
            cls.require_model(values.get(key, {}), f"agent_runtime.skills.{key}")
        maintenance = values.get("cognitive_maintenance", {})
        cls.require_model(
            maintenance.get("user_profile", {}), "agent_runtime.skills.cognitive_maintenance.user_profile"
        )
        for skill, operation in (
            ("dynamic", "dynamic_composer"),
            ("dynamic", "dynamic_replier"),
            ("diary", "diary_llm"),
        ):
            if operation in values.get(skill, {}):
                cls.require_model(values[skill][operation], f"agent_runtime.skills.{skill}.{operation}")
        return cls(deepcopy(values))

    @staticmethod
    def require_model(config: dict[str, Any], path: str) -> dict[str, Any]:
        module = config.get("llm_module") if isinstance(config, dict) else None
        reference = module.get("llm") if isinstance(module, dict) else None
        if (
            not isinstance(reference, dict)
            or not isinstance(reference.get("name"), str)
            or not reference["name"].strip()
        ):
            raise ValueError(f"{path}.llm_module.llm.name 缺失，请配置模型引用")
        return module

    def get(self, key: str) -> dict[str, Any]:
        return self.values.get(key, {})
