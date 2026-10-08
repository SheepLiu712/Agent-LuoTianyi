import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional

import requests

cwd = os.getcwd()
sys.path.insert(0, str(cwd))

from src.utils.logger import get_logger  # noqa: E402
from src.world.get_new_songs.source_extraction import (  # noqa: E402
    collect_materials,
    decode_extraction_response,
    merge_missing,
)
from src.world.get_new_songs.text_conversion import convert_text  # noqa: E402
from src.world.get_new_songs.wiki_api import fetch_wikitext, user_agent  # noqa: E402
from src.world.get_new_songs.wikitext_parser import parse_extraction  # noqa: E402


class VCPediaFetcher:
    def __init__(
        self, config: Dict[str, Any], llm_module: Any | None = None, *, extraction_llm_module: Any | None = None
    ):
        self.logger = get_logger(__name__)
        self.config = config
        self.activated = config.get("activated", False)
        crawler_config = config.get("vcpedia", {})
        self.base_url = crawler_config.get("base_url", "https://vcpedia.cn")

        self.llm_cfg = config.get("llm", {})
        self.use_llm = config.get("use_llm", True)
        self.llm_module = llm_module
        self.extraction_llm_module = extraction_llm_module
        self.llm_client = None

        # Define directories to search
        self.data_dir = Path(config.get("data_dir", "data/crawled_data"))
        # Default save directory
        self.default_save_dir = Path(crawler_config.get("output_dir", "data/crawled_data"))

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent()})

    def fetch_entity_description(
        self, entity_name: str, short_summary: bool = True, *, source_title: str | None = None
    ) -> Dict[str, Any]:
        """
        Fetch entity description from cache or VCPedia.
        Returns the complete detail dict; disabled returns empty string, failure None.
        """
        if not self.activated:
            return ""
        # 1. Check local cache
        cached_data = self._check_cache(entity_name)
        if cached_data:
            self.logger.info(f"Found {entity_name} in cache.")
            return cached_data

        # 2. Crawl
        self.logger.info(f"Trying to crawl {entity_name} from VCPedia...")
        title = source_title if source_title is not None else entity_name
        source = self._fetch_page(title)
        if source is not None:
            try:
                data, needed, candidates = parse_extraction(source, entity_name)
                self._supplement(data, needed, candidates, source, title)
                if data["type"] == "Song":
                    data["short_summary"] = self._summarize(data)
                    if needed["lyrics"]:
                        self.logger.warning(f"No complete single lyric version for {entity_name}; not submitting song")
                        return None
                return data
            except Exception as e:
                self.logger.error(f"Error parsing {entity_name}: {e}")

        return None

    def _supplement(self, data, needed, candidates, source, title):
        # 开关仅控制可选片段 POST 和模型调用，不禁止正常详情 GET。
        merge_fragments = bool(self.config.get("merge_rendered_fragments", True))
        wants_llm = self.use_llm and self.extraction_llm_module is not None
        if merge_fragments or wants_llm:
            materials = collect_materials(
                data,
                needed,
                source,
                self.base_url,
                title,
                post=self.session.post,
                merge_fragments=merge_fragments,
                candidates=candidates,
            )
            if wants_llm and any(needed.values()):
                self._extract_missing(data, needed, materials)

    @staticmethod
    def _call_model(module, **kwargs):
        def run():
            return asyncio.run(module.generate_response(**kwargs))

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run()
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(run).result()

    def _extract_missing(self, data, needed, materials):
        requested = {**needed, "lyrics": needed["lyrics"] and bool(materials.get("lyrics"))}
        if not any(requested.values()):
            return
        try:
            result = self._call_model(
                self.extraction_llm_module,
                song_data=json.dumps(data, ensure_ascii=False, default=str),
                needed=json.dumps(requested, ensure_ascii=False),
                materials=json.dumps(materials, ensure_ascii=False),
            )
            result = decode_extraction_response(result)
            if not requested["lyrics"]:
                result.pop("lyrics", None)
            merge_missing(data, result, needed)
        except Exception as exc:
            self.logger.warning(f"Optional VCPedia extraction failed: {exc}")

    def _summarize(self, data):
        if self.use_llm and self.llm_module is not None:
            try:
                result = self._call_model(self.llm_module, song_data=json.dumps(data, ensure_ascii=False, default=str))
                if isinstance(result, str) and result.strip():
                    return convert_text(result.strip())
            except Exception as exc:
                self.logger.error(f"LLM song summary failed: {exc}")
        summary_raw = "\n".join(str(x) for x in data.get("summary", []) if x)
        return summary_raw[:100].strip()

    def _check_cache(self, entity_name: str) -> Optional[Dict[str, Any]]:
        # Normalize name for filename
        safe_name = "".join([c for c in entity_name if c.isalnum() or c in (" ", "-", "_")]).strip()

        file_path = self.data_dir / f"{safe_name}.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Legacy song caches carry no single-version provenance; never certify them by shape alone.
                if isinstance(data, dict) and data.get("type") == "Person" and not data.get("lyrics"):
                    return data
                self.logger.info(f"Re-extracting {entity_name}: cached lyrics have no single-version provenance")
            except Exception as e:
                self.logger.error(f"Error reading cache {file_path}: {e}")
        return None

    def _fetch_page(self, page_name: str) -> Optional[str]:
        try:
            return fetch_wikitext(self.base_url, page_name, self.session.get, 10)
        except Exception as exc:
            self.logger.error(f"Error fetching {page_name}: {exc}")
            return None


if __name__ == "__main__":
    # Example usage
    config = {
        "activated": True,
        "vcpedia": {"base_url": "https://vcpedia.cn", "output_dir": "data/crawled_data"},
        "data_dir": "data/crawled_data",
    }
    fetcher = VCPediaFetcher(config)
    entity_name = "洛天依"  # Example entity
    description = fetcher.fetch_entity_description("煌")
    print(description)
