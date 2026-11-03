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
        cls._reject_runtime_legacy(runtime)
        values = runtime.get("skills")
        if not isinstance(values, dict):
            raise TypeError("agent_runtime.skills 必须是字典")
        cls._reject_skill_legacy(values)
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
            ("dynamic", "diary_composer"),
        ):
            if operation in values.get(skill, {}):
                cls.require_model(values[skill][operation], f"agent_runtime.skills.{skill}.{operation}")
        if "diary_llm" in values.get("diary", {}):
            raise ValueError("agent_runtime.skills.diary.diary_llm 请迁移到 skills.dynamic.diary_composer")
        return cls(deepcopy(values))

    @staticmethod
    def _reject_skill_legacy(values):
        if "text_preprocessing" in values:
            raise ValueError("agent_runtime.skills.text_preprocessing 请迁移到 skills.jargon_recognition")
        if "call_recall" in values:
            raise ValueError("agent_runtime.skills.call_recall 已删除，通话每轮使用通用记忆检索")
        if "conversation_compaction" in values:
            raise ValueError("agent_runtime.skills.conversation_compaction 请迁移到 skills.cognitive_maintenance")

    @staticmethod
    def _reject_runtime_legacy(runtime):
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
