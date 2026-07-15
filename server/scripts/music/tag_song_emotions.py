"""Batch-generate emotion_tags for the existing singing library."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from src.capabilities.singing import SingingCapability
from src.utils.helpers import load_config
from src.utils.llm_service import LLMService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Server config path, relative to server/ by default.",
    )
    parser.add_argument("--character-id", default="luotianyi")
    parser.add_argument("--song", help="Only tag one song; default tags every song.")
    parser.add_argument("--force", action="store_true", help="Retag songs that already have labels.")
    return parser.parse_args()


async def tag_songs(
    singing: SingingCapability,
    character_id: str,
    song_name: str | None = None,
    force: bool = False,
) -> int:
    manager = singing.singing_manager[character_id]
    names = [song_name] if song_name else [metadata.song_name for metadata in manager.all_songs.values()]
    updated = 0
    for name in names:
        metadata = manager.get_song_metadata(name)
        if metadata is None:
            print(f"[WARN] song not found: {name}")
            continue
        if metadata.emotion_tags and not force:
            print(f"[SKIP] {metadata.song_name}: {metadata.emotion_tags}")
            continue
        tags = await singing.tag_song_emotions(character_id, metadata.song_name)
        if tags:
            updated += 1
            print(f"[OK] {metadata.song_name}: {tags}")
        else:
            print(f"[WARN] no tags generated: {metadata.song_name}")
    return updated


def main() -> None:
    args = parse_args()
    os.chdir(SERVER_ROOT)
    config = load_config(args.config)
    llm_service = LLMService(config.get("llm_service", {}))
    singing = SingingCapability(config.get("capabilities", {}).get("sing", {}), llm_service=llm_service)
    updated = asyncio.run(
        tag_songs(
            singing,
            args.character_id,
            song_name=args.song,
            force=args.force,
        )
    )
    print(f"[DONE] updated {updated} song(s)")


if __name__ == "__main__":
    main()
