from __future__ import annotations

from dataclasses import dataclass

from src.domain.character import CharacterProfile


DEFAULT_CHARACTER_ID = "luotianyi"


@dataclass(frozen=True)
class CharacterRegistry:
    """Small registry for first-class character lookup.

    The first phase only registers Luo Tianyi. Keeping this lookup explicit
    prevents new code from hardcoding one character throughout the runtime.
    """

    characters: dict[str, CharacterProfile]
    default_character_id: str = DEFAULT_CHARACTER_ID

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
