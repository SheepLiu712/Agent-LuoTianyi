"""
Auto Song Learner
-----------------
Bridges the gap between "user wants a song we can't sing" and "we can sing it now".

Flow:
  1. User requests a song the system can't sing → add_wished_song() → metadata.json
  2. DailyScheduler triggers try_learn_pending() at 4AM
  3. AutoSongLearner checks res/music/staging/<safe_name>/ for .mp3 + .lrc
  4. If found: auto-generates segment config, moves to res/music/songs/<safe_name>/
  5. If not found: marks awaiting_audio, retries up to MAX_ATTEMPTS times
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...types.music_type import WishEntry, OneLyricLine
from ...utils.logger import get_logger


@dataclass
class LearnResult:
    """Result from one learning pass."""
    learned: List[str] = field(default_factory=list)
    abandoned: List[str] = field(default_factory=list)
    awaiting: List[str] = field(default_factory=list)


class WishlistManager:
    """Manages the enhanced metadata.json wishlist with v1→v2 migration."""

    def __init__(self, metadata_path: str, logger: Any):
        self.metadata_path = Path(metadata_path)
        self.logger = logger
        self.wished_songs: Dict[str, WishEntry] = {}
        self.recently_learned: List[str] = []
        self._load()

    # ── persistence ──────────────────────────────────────────────

    def _load(self) -> None:
        if not self.metadata_path.exists():
            self.logger.info("metadata.json not found, starting fresh wishlist")
            return
        try:
            raw = json.loads(self.metadata_path.read_text("utf-8"))
        except Exception as e:
            self.logger.warning(f"Failed to parse metadata.json: {e}, starting fresh")
            return

        # v1 → v2 migration: flat list → dict of entries
        wished_raw = raw.get("wished_songs", {})
        if isinstance(wished_raw, list):
            self.logger.info("Migrating v1 wishlist (flat list) to v2 (dict)")
            for name in wished_raw:
                self.wished_songs[name] = WishEntry(safe_name=name)
            raw["wished_songs"] = {
                name: self._entry_to_dict(e)
                for name, e in self.wished_songs.items()
            }
            raw.setdefault("recently_learned", [])
            self._atomic_write(raw)
        elif isinstance(wished_raw, dict):
            for name, entry_dict in wished_raw.items():
                self.wished_songs[name] = WishEntry(**entry_dict)

        self.recently_learned = raw.get("recently_learned", [])

    def _save(self) -> None:
        data = {
            "wished_songs": {
                name: self._entry_to_dict(e)
                for name, e in self.wished_songs.items()
            },
            "recently_learned": self.recently_learned,
        }
        self._atomic_write(data)

    def _atomic_write(self, data: dict) -> None:
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.metadata_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.metadata_path)

    @staticmethod
    def _entry_to_dict(e: WishEntry) -> dict:
        d = asdict(e)
        return {k: v for k, v in d.items() if v}

    # ── public API ──────────────────────────────────────────────

    def add(self, safe_name: str) -> bool:
        """Record or increment a wished song. Returns True if entry was created."""
        safe_name = safe_name.strip().strip("《》")
        if not safe_name:
            return False
        if safe_name in self.wished_songs:
            self.wished_songs[safe_name].request_count += 1
            self._save()
            return False
        self.wished_songs[safe_name] = WishEntry(
            safe_name=safe_name,
            first_requested=time.strftime("%Y-%m-%d"),
        )
        self._save()
        return True

    def get_pending(self) -> List[WishEntry]:
        """Return entries that need a learning attempt."""
        return [
            e for e in self.wished_songs.values()
            if e.status in ("pending", "awaiting_audio")
            and e.attempt_count < 3
        ]

    def mark_learned(self, safe_name: str) -> None:
        entry = self.wished_songs.get(safe_name)
        if entry is None:
            return
        entry.status = "learned"
        entry.learned_date = time.strftime("%Y-%m-%d")
        self.recently_learned.append(safe_name)
        self._save()

    def mark_awaiting_audio(self, safe_name: str, reason: str = "") -> None:
        entry = self.wished_songs.get(safe_name)
        if entry is None:
            return
        entry.status = "awaiting_audio"
        entry.last_attempt = time.strftime("%Y-%m-%d")
        entry.attempt_count += 1
        entry.failure_reason = reason
        self._save()

    def mark_abandoned(self, safe_name: str, reason: str = "") -> None:
        entry = self.wished_songs.get(safe_name)
        if entry is None:
            return
        entry.status = "abandoned"
        entry.last_attempt = time.strftime("%Y-%m-%d")
        entry.attempt_count += 1
        entry.failure_reason = reason
        self._save()

    def get_recently_learned(self) -> List[str]:
        """Return and clear the recently-learned notification list."""
        result = list(self.recently_learned)
        if result:
            self.recently_learned = []
            self._save()
        return result

    def get_all(self) -> Dict[str, WishEntry]:
        return dict(self.wished_songs)

    def sync_existing_songs(self, all_safe_names: set) -> None:
        """Mark any wished songs that now exist in the library as learned."""
        changed = False
        for safe_name in all_safe_names:
            entry = self.wished_songs.get(safe_name)
            if entry and entry.status not in ("learned", "abandoned"):
                entry.status = "learned"
                entry.learned_date = time.strftime("%Y-%m-%d")
                changed = True
        if changed:
            self._save()


class AutoSongLearner:
    """Orchestrates the learning process: checks staging, auto-segments, moves to songs."""

    MAX_ATTEMPTS = 3

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.logger = get_logger("AutoSongLearner")
        config = config or {}
        self.resource_path = Path(config.get("resource_path", "res/music"))
        self.songs_dir = self.resource_path / "songs"
        self.staging_dir = self.resource_path / "staging"
        self.metadata_path = self.resource_path / "metadata.json"
        self.wishlist = WishlistManager(str(self.metadata_path), self.logger)
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        self.songs_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    # ── main entry ──────────────────────────────────────────────

    def try_learn_pending(self) -> LearnResult:
        """Try to learn all pending wished songs. Called by DailyScheduler."""
        result = LearnResult()
        pending = self.wishlist.get_pending()
        if not pending:
            self.logger.info("No pending songs to learn")
            return result

        self.logger.info(f"Attempting to learn {len(pending)} pending song(s)")

        # Check pydub availability once
        try:
            from pydub import AudioSegment
        except ImportError:
            self.logger.error("pydub not installed, skipping song learning")
            return result

        for entry in pending:
            safe_name = entry.safe_name
            self.logger.info(f"Trying to learn: {safe_name}")
            if self._try_learn_one(safe_name):
                result.learned.append(safe_name)
                self.logger.info(f"  ✓ Learned: {safe_name}")
            else:
                entry_after = self.wishlist.wished_songs.get(safe_name)
                if entry_after and entry_after.status == "abandoned":
                    result.abandoned.append(safe_name)
                    self.logger.info(f"  ✗ Abandoned: {safe_name}")
                else:
                    result.awaiting.append(safe_name)
                    self.logger.info(f"  … Still awaiting: {safe_name}")

        # If any songs were learned, replay the song loader
        if result.learned:
            self._notify_new_songs(result.learned)

        return result

    # ── single song learning ────────────────────────────────────

    def _try_learn_one(self, safe_name: str) -> bool:
        staging_song_dir = self.staging_dir / safe_name
        if not staging_song_dir.is_dir():
            self._handle_failure(safe_name, f"Staging directory not found: {staging_song_dir}")
            return False

        mp3_path = staging_song_dir / f"{safe_name}.mp3"
        lrc_path = staging_song_dir / f"{safe_name}.lrc"

        missing = []
        if not mp3_path.exists():
            missing.append("MP3")
        if not lrc_path.exists():
            missing.append("LRC")
        if missing:
            self._handle_failure(safe_name, f"Missing files: {', '.join(missing)} in staging")
            return False

        # Try to get duration
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(str(mp3_path))
            duration_seconds = audio.duration_seconds
        except Exception as e:
            self._handle_failure(safe_name, f"Failed to read MP3 duration: {e}")
            return False

        # Parse LRC
        lrc_lines = self._parse_lrc_file(lrc_path)
        if not lrc_lines and lrc_path.read_bytes().strip():
            # LRC file exists but parsing returned empty — could be instrumental
            self.logger.warning(f"LRC file for {safe_name} yielded no timestamped lines, treating as instrumental")

        # Auto-segment
        segments = self._auto_segment(safe_name, lrc_lines, duration_seconds)
        if not segments:
            self._handle_failure(safe_name, "Auto-segmentation produced no segments")
            return False

        # Write JSON config
        title = safe_name  # safe_name is the best default title we have
        config_data = {
            "title": title,
            "description": f"自动学习歌曲：{safe_name}",
            "lrc_offset": 0,
            "segments": segments,
        }
        config_path = staging_song_dir / f"{safe_name}.json"
        try:
            config_path.write_text(
                json.dumps(config_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            self._handle_failure(safe_name, f"Failed to write config JSON: {e}")
            return False

        # Move from staging to songs
        target_dir = self.songs_dir / safe_name
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.move(str(staging_song_dir), str(target_dir))
        except Exception as e:
            self._handle_failure(safe_name, f"Failed to move to songs/: {e}")
            return False

        self.wishlist.mark_learned(safe_name)
        return True

    # ── LRC parsing ─────────────────────────────────────────────

    @staticmethod
    def _parse_lrc_file(lrc_path: Path) -> List[Tuple[float, str]]:
        """Parse LRC format: [mm:ss.xx]Lyrics text. Returns sorted list of (time_seconds, text)."""
        pattern = re.compile(r'\[(\d{2}):(\d{2})[\.:](\d{2,3})\](.*)')
        entries = []
        try:
            text = lrc_path.read_text("utf-8")
        except Exception:
            return []

        for line in text.splitlines():
            m = pattern.match(line.strip())
            if not m:
                continue
            minutes, seconds, centi, lyric = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
            ms = int(centi) / (1000 if len(centi) == 3 else 100)
            ts = minutes * 60 + seconds + ms
            lyric = lyric.strip()
            if lyric:
                entries.append((ts, lyric))

        entries.sort(key=lambda x: x[0])
        return entries

    # ── auto-segmentation ───────────────────────────────────────

    @staticmethod
    def _auto_segment(
        safe_name: str,
        lrc_lines: List[Tuple[float, str]],
        total_duration: float,
        max_segments: int = 5,
    ) -> List[dict]:
        """Divide song into segments based on LRC timestamps and total duration.

        Returns a list of segment dicts compatible with SongSegment:
            {description, start_time, end_time, lyrics: [{duration, content}, ...]}
        """
        if total_duration <= 0:
            return []

        if not lrc_lines or len(lrc_lines) < 3:
            # Instrumental or very sparse lyrics → single segment
            return [{
                "description": "完整版",
                "start_time": 0.0,
                "end_time": total_duration,
                "lyrics": [
                    {"duration": 0.0, "content": line[1]}
                    for line in lrc_lines
                ],
            }]

        # Determine segment boundaries
        num_segments = min(max_segments, max(3, len(lrc_lines) // 3))
        seg_duration = total_duration / num_segments

        # Label segments
        labels = _segment_labels(num_segments)

        segments = []
        for i in range(num_segments):
            seg_start = seg_duration * i
            seg_end = seg_duration * (i + 1) if i < num_segments - 1 else total_duration

            # Collect LRC lines that fall within this segment
            seg_lyrics = []
            for ts, text in lrc_lines:
                if seg_start <= ts < seg_end:
                    # Find duration: gap to next LRC line
                    next_ts = seg_end
                    for ts2, _ in lrc_lines:
                        if ts2 > ts:
                            next_ts = min(next_ts, ts2)
                            break
                    seg_lyrics.append({
                        "duration": round(next_ts - ts, 2),
                        "content": text,
                    })

            segments.append({
                "description": labels[i],
                "start_time": round(seg_start, 2),
                "end_time": round(seg_end, 2),
                "lyrics": seg_lyrics,
            })

        return segments

    # ── failure handling ────────────────────────────────────────

    def _handle_failure(self, safe_name: str, reason: str) -> None:
        entry = self.wishlist.wished_songs.get(safe_name)
        if entry is None:
            return
        entry.last_attempt = time.strftime("%Y-%m-%d")
        entry.attempt_count += 1
        entry.failure_reason = reason
        if entry.attempt_count >= self.MAX_ATTEMPTS:
            entry.status = "abandoned"
            self.logger.warning(f"Abandoned learning {safe_name} after {self.MAX_ATTEMPTS} attempts: {reason}")
        else:
            entry.status = "awaiting_audio"
            self.logger.info(f"Learning {safe_name} awaits audio (attempt {entry.attempt_count}/{self.MAX_ATTEMPTS}): {reason}")
        self.wishlist._save()

    # ── notification ────────────────────────────────────────────

    def _notify_new_songs(self, learned: List[str]) -> None:
        """Write learned songs so ActivityMaker can announce them on next login."""
        notify_dir = Path("data/plugin_scheduler")
        notify_dir.mkdir(parents=True, exist_ok=True)
        notify_path = notify_dir / "newly_learned_songs.json"
        existing: List[str] = []
        if notify_path.exists():
            try:
                existing = json.loads(notify_path.read_text("utf-8"))
            except Exception:
                pass
        notify_path.write_text(
            json.dumps(existing + learned, ensure_ascii=False), encoding="utf-8"
        )
        self.logger.info(f"Notification written: {learned}")

    @property
    def recently_learned(self) -> List[str]:
        return self.wishlist.get_recently_learned()


def _segment_labels(count: int) -> List[str]:
    """Generate human-readable labels for N segments."""
    if count <= 1:
        return ["完整版"]
    if count == 2:
        return ["前段", "后段"]
    if count == 3:
        return ["前段", "中段", "后段"]
    if count == 4:
        return ["前奏", "主歌", "副歌", "尾声"]
    # 5+
    return [f"第{i+1}段" for i in range(count - 1)] + ["尾声"]
