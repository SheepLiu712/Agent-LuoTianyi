from __future__ import annotations

from typing import Any, Dict

from src.domain.character import CharacterName, CharacterProfile

DEFAULT_CHARACTER_ID = CharacterName.LUOTIANYI.value


class CharacterRegistry:
    """Small registry for first-class character lookup."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.characters: dict[str, CharacterProfile] = {}
        self.default_character_id: str = DEFAULT_CHARACTER_ID
        self._build_character_profiles()

    def _build_character_profiles(self) -> None:
        characters_cfg = self.config.get("characters", self.config)
        for character_id, profile_cfg in characters_cfg.items():
            profile = CharacterProfile(
                character_id=character_id,
                display_name=profile_cfg.get("display_name", character_id),
                memory_namespace=profile_cfg.get("memory_namespace", character_id),
                static_variables_file=profile_cfg.get("static_variables_file"),
                llm_tone_mapping_file=profile_cfg.get("llm_tone_mapping_file"),
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
        if not self.characters:
            profile = self._default_profile()
            self.characters[profile.character_id] = profile
            self.default_character_id = profile.character_id

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

    @staticmethod
    def _default_profile() -> CharacterProfile:
        return CharacterProfile(
            character_id=DEFAULT_CHARACTER_ID,
            display_name="Luo Tianyi",
            memory_namespace=DEFAULT_CHARACTER_ID,
            static_variables_file="res/agent/persona/persona.json",
            llm_tone_mapping_file="res/agent/persona/llm_tones_mapping.json",
            persona_ref="main_chat.static_variables.character_persona",
            speaking_style_ref="main_chat.static_variables.speaking_style",
            voice_profile=DEFAULT_CHARACTER_ID,
            live2d_profile=DEFAULT_CHARACTER_ID,
            default_target=True,
        )


def get_default_character_registry() -> CharacterRegistry:
    return CharacterRegistry(
        {
            "characters": {
                DEFAULT_CHARACTER_ID: {
                    "display_name": "Luo Tianyi",
                    "memory_namespace": DEFAULT_CHARACTER_ID,
                    "static_variables_file": "res/agent/persona/persona.json",
                    "llm_tone_mapping_file": "res/agent/persona/llm_tones_mapping.json",
                    "persona_ref": "main_chat.static_variables.character_persona",
                    "speaking_style_ref": "main_chat.static_variables.speaking_style",
                    "voice_profile": DEFAULT_CHARACTER_ID,
                    "live2d_profile": DEFAULT_CHARACTER_ID,
                    "default_target": True,
                }
            }
        }
    )
