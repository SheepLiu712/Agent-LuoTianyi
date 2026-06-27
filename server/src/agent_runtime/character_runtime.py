from __future__ import annotations

from dataclasses import dataclass

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.domain import CharacterProfile
from src.subconscious.character_mind import CharacterSubconscious


@dataclass(frozen=True)
class CharacterRuntime:
    """Runtime pair for one character."""

    profile: CharacterProfile
    conscious: LuoTianyiAgent
    mind: CharacterSubconscious

    def ensure_dependencies(self) -> None:
        """检查角色运行时的意识、潜意识和角色档案已经初始化。"""
        required = {
            "profile": self.profile,
            "conscious": self.conscious,
            "mind": self.mind,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"CharacterRuntime dependencies are missing: {', '.join(missing)}")
        if hasattr(self.conscious, "ensure_dependencies"):
            self.conscious.ensure_dependencies()
        if hasattr(self.mind, "ensure_dependencies"):
            self.mind.ensure_dependencies()
