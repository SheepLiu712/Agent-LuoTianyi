from __future__ import annotations

from typing import Any, Dict, Optional

from src.system.database.event_models import UnifiedEventType
from src.utils.logger import get_logger
from src.world.bili_event_updater.event_parser import EventParser
from src.world.bili_event_updater.official_feed_fetcher import OfficialFeedFetcher


class BiliEventUpdater:
    """Fetch Bilibili dynamics, parse them, and upsert schedule events."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        event_store: Any | None = None,
        fetcher: OfficialFeedFetcher | None = None,
        parser: EventParser | None = None,
    ) -> None:
        self.config = config or {}
        self.logger = get_logger(__name__)
        self.event_store = event_store
        self.fetcher = fetcher or OfficialFeedFetcher(config=self.config)
        self.parser = parser or EventParser(**self._build_parser_config(self.config))
        self.fetch_interval_seconds = float(self.config.get("fetch_interval_hours", 6)) * 3600

    @property
    def llm_client(self):
        return self.parser.llm_client

    def set_event_store(self, event_store: Any) -> None:
        self.event_store = event_store

    async def fetch_and_update_events(self) -> Dict[str, int]:
        """Pull latest dynamics and update EventStore.

        Returns simple counters useful for logs/tests:
        ``{"raw": n, "parsed": n, "updated": n}``.
        """
        if self.event_store is None:
            raise RuntimeError("BiliEventUpdater requires an event_store before updating events.")

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
                if await self.event_store.add_event(event):
                    updated += 1

            self.logger.info(f"Updated {updated} event(s) from {len(parsed_events)} parsed dynamic event(s)")
            return {"raw": len(raw_items), "parsed": len(parsed_events), "updated": updated}
        except Exception as e:
            self.logger.error(f"Error in fetch_and_update_events: {e}")
            return {"raw": 0, "parsed": 0, "updated": 0}

    @staticmethod
    def _build_parser_config(config: Dict[str, Any]) -> Dict[str, Any]:
        llm_cfg = config.get("llm") or config.get("llm_module", {}).get("llm", {})
        vlm_cfg = config.get("vlm") or config.get("vlm_module", {}).get("vlm", {})
        if not llm_cfg or not vlm_cfg:
            try:
                from src.utils.helpers import load_config

                root_cfg = load_config("config/config.json", default_config={})
                if not llm_cfg:
                    llm_cfg = root_cfg.get("knowledge", {}).get("llm", {})
                if not vlm_cfg:
                    vlm_cfg = root_cfg.get("vision_module", {}).get("vlm_module", {}).get("vlm", {})
            except Exception:
                pass
        return {"llm_config": llm_cfg, "vlm_config": vlm_cfg}

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
