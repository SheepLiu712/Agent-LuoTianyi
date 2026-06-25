from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.world.types.events import WorldEvent


@dataclass(frozen=True)
class PublicDiaryEntry:
    """Public diary/space entry visible to all users."""

    entry_id: str
    owner_character_id: str
    title: str
    body: str
    source: str
    created_at: datetime
    visibility: str = "public"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_world_event(self) -> WorldEvent:
        return WorldEvent(
            event_id=self.entry_id,
            event_type="public_diary",
            title=self.title,
            description=self.body,
            source=self.source,
            start_datetime=self.created_at,
            is_personal=False,
            target_user_id=None,
            metadata={
                "owner_character_id": self.owner_character_id,
                "visibility": self.visibility,
                **dict(self.metadata or {}),
            },
        )


class CitywalkDiaryProvider:
    """Reads citywalk report files as public diary entries.

    This is a world facade over existing report artifacts. It does not own
    citywalk execution or memory ingestion.
    """

    def __init__(
        self,
        reports_dir: str | Path = "data/citywalk_reports",
        owner_character_id: str = "luotianyi",
    ) -> None:
        self.reports_dir = Path(reports_dir)
        self.owner_character_id = owner_character_id

    def list_public_diaries(self, limit: int | None = None) -> list[PublicDiaryEntry]:
        if not self.reports_dir.exists():
            return []

        entries: list[PublicDiaryEntry] = []
        for path in sorted(self.reports_dir.glob("citywalk_*.json"), reverse=True):
            entry = self._load_entry(path)
            if entry is not None:
                entries.append(entry)
                if limit is not None and len(entries) >= limit:
                    break
        return entries

    def list_active_events(self, user_id: str | None = None) -> list[WorldEvent]:
        return [entry.to_world_event() for entry in self.list_public_diaries()]

    def get_context_for_runtime(self, user_id: str | None = None) -> str:
        entries = self.list_public_diaries(limit=3)
        if not entries:
            return ""
        return "\n".join(f"{entry.created_at:%Y-%m-%d} {entry.title}: {entry.body}" for entry in entries)

    def _load_entry(self, path: Path) -> PublicDiaryEntry | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

        body = str(data.get("diary_text") or data.get("diary") or "").strip()
        if not body:
            return None

        created_at = self._parse_created_at(data.get("created_at"))
        overview = data.get("overview") if isinstance(data.get("overview"), dict) else {}
        city = str(overview.get("city") or "").strip()
        destination = str(overview.get("selected_destination") or "").strip()
        title = str(data.get("title") or "城市漫步日记").strip()
        if city or destination:
            title = f"{title} · {city or destination}"

        return PublicDiaryEntry(
            entry_id=path.stem,
            owner_character_id=self.owner_character_id,
            title=title,
            body=body,
            source="citywalk",
            created_at=created_at,
            metadata={
                "report_path": str(path),
                "city": city,
                "selected_destination": destination,
                "source_kind": "diary_source",
            },
        )

    def _parse_created_at(self, raw: Any) -> datetime:
        if isinstance(raw, datetime):
            return raw
        if raw:
            try:
                return datetime.fromisoformat(str(raw))
            except Exception:
                pass
        return datetime.fromtimestamp(0)
