from __future__ import annotations
from typing import Any, Dict
from src.domain.character import CharacterProfile, CharacterName

DEFAULT_CHARACTER_ID = CharacterName.LUOTIANYI.value


class CharacterRegistry:
    """Small registry for first-class character lookup.

    The first phase only registers Luo Tianyi. Keeping this lookup explicit
    prevents new code from hardcoding one character throughout the runtime.
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.characters: dict[str, CharacterProfile] = {}
        self.default_character_id: str = DEFAULT_CHARACTER_ID
        self._build_character_profiles()

    def _build_character_profiles(self) -> None:
        """Build character profiles from config."""
        for character_id, profile_cfg in self.config.get("characters", {}).items():
            profile = CharacterProfile(
                character_id=character_id,
                display_name=profile_cfg.get("display_name", character_id),
                memory_namespace=profile_cfg.get("memory_namespace", character_id),
                persona_ref=profile_cfg.get("persona_ref"),
                speaking_style_ref=profile_cfg.get("speaking_style_ref"),
                voice_profile=profile_cfg.get("voice_profile"),
                live2d_profile=profile_cfg.get("live2d_profile"),
                default_target=profile_cfg.get("default_target", False),
                enabled=profile_cfg.get("enabled", True),
                metadata=profile_cfg.get("metadata", {}),
            )
            self.characters[character_id] = profile
            if profile.default_target:
                self.default_character_id = character_id

    def get(self, character_id: str | None = None) -> CharacterProfile:
        resolved_id = character_id or self.default_character_id
        try:
            return self.characters[resolved_id]
        except KeyError as exc:
            raise KeyError(f"Unknown character_id: {resolved_id}") from exc

    def resolve_targets(self, target_character_ids: tuple[str, ...] | None = None) -> tuple[str, ...]:
        if target_character_ids:
            for character_id in target_character_ids:
                self.get(character_id)
            return target_character_ids
        return (self.default_character_id,)


def get_default_character_registry() -> CharacterRegistry:
    default_profile = CharacterProfile(
        character_id=DEFAULT_CHARACTER_ID,
        display_name="Luo Tianyi",
        memory_namespace=DEFAULT_CHARACTER_ID,
        persona_ref="main_chat.static_variables.character_persona",
        speaking_style_ref="main_chat.static_variables.speaking_style",
        voice_profile=DEFAULT_CHARACTER_ID,
        live2d_profile=DEFAULT_CHARACTER_ID,
        default_target=True,
    )
    return CharacterRegistry(characters={DEFAULT_CHARACTER_ID: default_profile})
