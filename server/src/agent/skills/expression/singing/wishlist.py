"""Persistent wishlist for songs requested by users."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.domain.music_type import WishEntry
from src.utils.helpers import get_unified_song_name


class WishlistManager:
    """Manage metadata.json wishlist state with v1-to-v2 migration."""

    def __init__(self, metadata_path: str, logger: Any):
        self.metadata_path = Path(metadata_path)
        self.logger = logger
        self.wished_songs: dict[str, WishEntry] = {}
        self.recently_learned: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self.metadata_path.exists():
            self.logger.info("metadata.json not found, starting fresh wishlist")
            return
        try:
            raw = json.loads(self.metadata_path.read_text("utf-8"))
        except Exception as error:
            self.logger.warning(f"Failed to parse metadata.json: {error}, starting fresh")
            return

        self.recently_learned = raw.get("recently_learned", [])
        wished_raw = raw.get("wished_songs", {})
        migrated_learned = False
        if isinstance(wished_raw, list):
            self.logger.info("Migrating v1 wishlist (flat list) to v2 (dict)")
            for name in wished_raw:
                self.wished_songs[name] = WishEntry(safe_name=name)
            raw["wished_songs"] = {name: self._entry_to_dict(entry) for name, entry in self.wished_songs.items()}
            raw.setdefault("recently_learned", [])
            self._atomic_write(raw)
        elif isinstance(wished_raw, dict):
            for name, entry_dict in wished_raw.items():
                entry = WishEntry(**entry_dict)
                if entry.status == "learned":
                    unified_name = entry.unified_name or get_unified_song_name(entry.safe_name or name)
                    if unified_name and unified_name not in self.recently_learned:
                        self.recently_learned.append(unified_name)
                    migrated_learned = True
                    continue
                self.wished_songs[name] = entry

        if migrated_learned:
            self._save()
        self._prune_learned_entries()

    def _save(self) -> None:
        data = {
            "wished_songs": {name: self._entry_to_dict(entry) for name, entry in self.wished_songs.items()},
            "recently_learned": self.recently_learned,
        }
        self._atomic_write(data)

    def _atomic_write(self, data: dict) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.metadata_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.metadata_path)

    @staticmethod
    def _entry_to_dict(entry: WishEntry) -> dict:
        return {key: value for key, value in asdict(entry).items() if value}

    def add(self, safe_name: str) -> bool:
        """Record or increment a wished song. Return whether it was created."""
        safe_name = safe_name.strip().strip("《》")
        unified_name = get_unified_song_name(safe_name)
        if not safe_name:
            return False
        if unified_name in self.wished_songs:
            self.wished_songs[unified_name].request_count += 1
            self._save()
            return False
        self.wished_songs[unified_name] = WishEntry(
            safe_name=safe_name,
            unified_name=unified_name,
            first_requested=time.strftime("%Y-%m-%d"),
        )
        self._save()
        return True

    def get_pending(self) -> list[WishEntry]:
        """Return entries that need a learning attempt."""
        return [
            entry
            for entry in self.wished_songs.values()
            if entry.status in ("pending", "awaiting_audio") and entry.attempt_count < 3
        ]

    def mark_learned(self, safe_name: str) -> None:
        unified_name = get_unified_song_name(safe_name)
        if unified_name in self.wished_songs:
            self.wished_songs.pop(unified_name)
        if unified_name and unified_name not in self.recently_learned:
            self.recently_learned.append(unified_name)
        self._save()

    def mark_redirected(
        self,
        requested_name: str,
        redirected_to: str,
        *,
        redirected_status: str = "",
        reason: str = "",
    ) -> None:
        requested_unified = get_unified_song_name(requested_name)
        redirected_unified = get_unified_song_name(redirected_to)
        entry = self.wished_songs.get(requested_unified)
        if entry is None:
            entry = WishEntry(
                safe_name=requested_name,
                unified_name=requested_unified,
                first_requested=time.strftime("%Y-%m-%d"),
            )
            self.wished_songs[requested_unified] = entry
        entry.status = "redirected"
        entry.last_attempt = time.strftime("%Y-%m-%d")
        entry.failure_reason = reason
        entry.redirected_to = redirected_to
        entry.redirected_unified_name = redirected_unified
        entry.redirected_status = redirected_status
        self._save()

    def update_redirect_status(self, requested_name: str, redirected_status: str, reason: str = "") -> None:
        requested_unified = get_unified_song_name(requested_name)
        entry = self.wished_songs.get(requested_unified)
        if entry is None or entry.status != "redirected":
            return
        entry.redirected_status = redirected_status
        if reason:
            entry.failure_reason = reason
        self._save()

    def mark_awaiting_audio(self, safe_name: str, reason: str = "") -> None:
        unified_name = get_unified_song_name(safe_name)
        entry = self.wished_songs.get(unified_name)
        if entry is None:
            return
        entry.status = "awaiting_audio"
        entry.last_attempt = time.strftime("%Y-%m-%d")
        entry.attempt_count += 1
        entry.failure_reason = reason
        self._save()

    def mark_abandoned(self, safe_name: str, reason: str = "") -> None:
        unified_name = get_unified_song_name(safe_name)
        entry = self.wished_songs.get(unified_name)
        if entry is None:
            return
        entry.status = "abandoned"
        entry.last_attempt = time.strftime("%Y-%m-%d")
        entry.attempt_count += 1
        entry.failure_reason = reason
        self._save()

    def get_recently_learned(self) -> list[str]:
        """Return and clear the recently learned notification list."""
        result = list(self.recently_learned)
        if result:
            self.recently_learned = []
            self._save()
        return result

    def get_all(self) -> dict[str, WishEntry]:
        return dict(self.wished_songs)

    def sync_existing_songs(self, all_safe_names: set[str]) -> None:
        """Remove wished songs that now exist in the library."""
        changed = False
        for safe_name in all_safe_names:
            unified_name = get_unified_song_name(safe_name)
            entry = self.wished_songs.pop(unified_name, None)
            if entry:
                if unified_name and unified_name not in self.recently_learned:
                    self.recently_learned.append(unified_name)
                changed = True
        if changed:
            self._save()

    def _prune_learned_entries(self) -> None:
        learned_names = [name for name, entry in self.wished_songs.items() if entry.status == "learned"]
        if not learned_names:
            return
        for name in learned_names:
            entry = self.wished_songs.pop(name)
            unified_name = entry.unified_name or get_unified_song_name(entry.safe_name or name)
            if unified_name and unified_name not in self.recently_learned:
                self.recently_learned.append(unified_name)
        self._save()
