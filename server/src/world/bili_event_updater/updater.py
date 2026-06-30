from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

from src.system.database.event_models import UnifiedEventType
from src.utils.logger import get_logger
from src.world.bili_event_updater.event_parser import EventParser
from src.world.bili_event_updater.official_feed_fetcher import OfficialFeedFetcher


if TYPE_CHECKING:
    from src.system.database.event_store import EventStore

class BiliEventUpdater:
    """Fetch Bilibili dynamics, parse them, and upsert schedule events."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        event_store: "EventStore | None" = None,
        llm_module: Any | None = None,
        vlm_module: Any | None = None,
    ) -> None:
        self.config = config or {}
        self.logger = get_logger(__name__)
        self.event_store = event_store
        self.fetcher = OfficialFeedFetcher(config=self.config)
        self.parser = EventParser(
            llm_module=llm_module,
            vlm_module=vlm_module,
        )

    @property
    def llm_client(self):
        return self.parser.llm_module

    def set_event_store(self, event_store: "EventStore") -> None:
        self.event_store = event_store

    async def fetch_and_update_events(self) -> Dict[str, int]:
        """Pull latest dynamics and update EventStore.

        Returns simple counters useful for logs/tests:
        ``{"raw": n, "parsed": n, "updated": n}``.
        """
        if self.event_store is None:
            raise RuntimeError("BiliEventUpdater requires an event_store before updating events.")
        
        if not await self.fetcher.check_and_update_cookie_validity():
            raise RuntimeError("Bilibili cookie is invalid or missing; dynamics cannot be fetched. Please provide a valid cookie.")

        self.logger.info("BiliEventUpdater: fetching new dynamics...")
        try:
            raw_items = self.fetcher.fetch_all_new()
            if not raw_items:
                self.logger.info("No new Bilibili dynamics fetched")
                return {"raw": 0, "parsed": 0, "updated": 0}

            self.logger.info(f"Fetched {len(raw_items)} new dynamics, parsing...")
            parsed_events = await self.parser.parse_dynamics(raw_items)

            updated = 0
            for event in parsed_events:
                event["event_type"] = self._map_old_event_type(event.get("event_type", "general"))
                event.setdefault("source", "bilibili")
                event.setdefault("is_recurring", False)
                event.setdefault("is_personal", False)
                if await self.event_store.add_event(event) is not None:
                    updated += 1

            self.logger.info(f"Updated {updated} event(s) from {len(parsed_events)} parsed dynamic event(s)")
            return {"raw": len(raw_items), "parsed": len(parsed_events), "updated": updated}
        except Exception as e:
            self.logger.error(f"Error in fetch_and_update_events: {e}")
            return {"raw": 0, "parsed": 0, "updated": 0}


    @staticmethod
    def _map_old_event_type(old_type: str) -> str:
        mapping = {
            "concert": UnifiedEventType.CONCERT.value,
            "collaboration": UnifiedEventType.GENERAL.value,
            "livestream": UnifiedEventType.LIVESTREAM.value,
            "release": UnifiedEventType.GENERAL.value,
            "anniversary": UnifiedEventType.ANNIVERSARY.value,
            "general": UnifiedEventType.GENERAL.value,
        }
        return mapping.get(old_type, UnifiedEventType.GENERAL.value)
