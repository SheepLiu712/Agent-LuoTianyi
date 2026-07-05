from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.agent.reflex import CharacterReflex
from src.domain import CharacterProfile
from src.subconscious.character_mind import CharacterSubconscious

if TYPE_CHECKING:
    from src.capabilities import CapabilityManager


@dataclass(frozen=True)
class CharacterRuntime:
    """Runtime pair for one character."""

    profile: CharacterProfile
    conscious: LuoTianyiAgent
    mind: CharacterSubconscious
    reflex: CharacterReflex
    capability_manager: "CapabilityManager"

    def ensure_dependencies(self) -> None:
        """检查角色运行时的意识、潜意识和角色档案已经初始化。"""
        required = {
            "profile": self.profile,
            "conscious": self.conscious,
            "mind": self.mind,
            "reflex": self.reflex,
            "capability_manager": self.capability_manager,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"CharacterRuntime dependencies are missing: {', '.join(missing)}")
        if hasattr(self.conscious, "ensure_dependencies"):
            self.conscious.ensure_dependencies()
        if hasattr(self.mind, "ensure_dependencies"):
            self.mind.ensure_dependencies()
        self.reflex.ensure_dependencies()

    def dynamic_context(self) -> dict[str, str]:
        main_chat = self.conscious.main_chat
        return {
            "character_name": main_chat.character_name,
            "character_persona": main_chat.character_persona,
            "speaking_style": main_chat.speaking_style,
        }

    async def publish_citywalk_dynamic(self, *, report: dict[str, Any], source_id: str | None = None) -> dict[str, Any]:
        return await self.capability_manager.dynamics.publish_citywalk_dynamic(
            character_id=self.profile.character_id,
            report=report,
            source_id=source_id,
            **self.dynamic_context(),
        )

    async def publish_learned_song_dynamic(
        self,
        *,
        song_name: str,
        segment_description: str = "",
        lyrics: str = "",
    ) -> dict[str, Any]:
        return await self.capability_manager.dynamics.publish_learned_song_dynamic(
            character_id=self.profile.character_id,
            song_name=song_name,
            segment_description=segment_description,
            lyrics=lyrics,
            **self.dynamic_context(),
        )

    async def generate_dynamic_reply_for_post(self, item: dict[str, Any]) -> str:
        return await self.capability_manager.dynamics.replier.generate_reply_for_post(
            item,
            character_name=self.dynamic_context()["character_name"],
        )

    async def generate_dynamic_reply_for_comment(self, item: dict[str, Any]) -> dict[str, Any]:
        return await self.capability_manager.dynamics.replier.generate_reply_for_comment(
            item,
            character_name=self.dynamic_context()["character_name"],
        )

    def publish_dynamic_comment(
        self,
        *,
        dynamic_id: str,
        owner_user_id: str,
        content: str,
        parent_comment_id: str | None = None,
    ) -> tuple[bool, str, dict[str, Any] | None]:
        return self.capability_manager.dynamics.publish_agent_comment(
            dynamic_id=dynamic_id,
            owner_user_id=owner_user_id,
            content=content,
            character_id=self.profile.character_id,
            parent_comment_id=parent_comment_id,
        )
