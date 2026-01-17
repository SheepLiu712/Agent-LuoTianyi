import requests
from bs4 import BeautifulSoup
import json
import os
from typing import Dict, Any, Optional, List
from pathlib import Path
from ..utils.logger import get_logger

class VCPediaFetcher:
    def __init__(self, config: Dict[str, Any]):
        self.logger = get_logger(__name__)
        self.config = config
        self.activated = config.get("activated", False)
        crawler_config = config.get("vcpedia", {})
        self.base_url = crawler_config.get("base_url", "https://vcpedia.cn")
        
        # Define directories to search
        self.data_dir = Path(config.get("data_dir", "data/crawled_data"))
        # Default save directory
        self.default_save_dir = Path(crawler_config.get("output_dir", "data/crawled_data"))
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        })

    def fetch_entity_description(self, entity_name: str, short_summary: bool = True) -> Dict[str, Any]:
        """
        Fetch entity description from cache or VCPedia.
        Returns a JSON string of the entity data or empty string if not found.
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
        html = self._fetch_page(entity_name)
        if html:
            try:
                data = self._parse_page(html, entity_name)
                if data:
                    self._save_data(data)
                    return data
            except Exception as e:
                self.logger.error(f"Error parsing {entity_name}: {e}")
        
        return None

    def _check_cache(self, entity_name: str) -> Optional[Dict[str, Any]]:
        # Normalize name for filename
        safe_name = "".join([c for c in entity_name if c.isalnum() or c in (' ', '-', '_')]).strip()
        
        file_path = self.data_dir / f"{safe_name}.json"
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Error reading cache {file_path}: {e}")
        return None

    def _fetch_page(self, page_name: str) -> Optional[str]:
        url = f"{self.base_url}/{page_name}"
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return response.text
            return None
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return None

    def _get_data_from_infobox(self, infobox_table, single_col = False) -> Dict[str, str]:
        infobox_data = {}
        rows = infobox_table.find_all('tr')
        preserved_title = None

        def get_title(text: str) -> str | None:
            text = text.strip()
            keywords = ["演唱", "作词", "作曲", "编曲", "作编曲", "PV", "UP主", "曲绘"]
            for kw in keywords:
                if kw in text:
                    return kw
            return None

        for row in rows:
            if 'display:none' in row.get('style', ''):
                continue
                
            cols = row.find_all(['th', 'td'])
            
            if len(cols) == 2:
                key = cols[0].get_text(strip=True)
                val_col = cols[1]
                for br in val_col.find_all('br'):
                    br.replace_with(',')
                value = val_col.get_text(strip=True)
                infobox_data[key] = value

            elif len(cols) == 1 and single_col:
                col = cols[0]
                if 'infobox-image-container' in col.get('class', []):
                    continue
                    
                text = col.get_text(strip=True)
                if not text:
                    continue
                if preserved_title is None:
                    preserved_title = get_title(text)
                else:
                    key = preserved_title
                    value = text
                    preserved_title = None
                    infobox_data[key] = value
                
        return infobox_data

    def _parse_page(self, html: str, title: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, 'html.parser')
        
        infobox_data = {}
        infobox_table = soup.find('table', class_='moe-infobox infobox')
        
        if infobox_table:
            new_infobox_data = self._get_data_from_infobox(infobox_table, single_col=True)
            infobox_data.update(new_infobox_data)

        summary_parts = []
        summary: List[str] = []
        short_summary: List[str] = []
        intro_header = []
        lyc_header = None
        for h2 in soup.find_all('h2'):
            text = h2.get_text()
            if '简介' in text or "VOCALOID原创作者" in text:
                intro_header.append(h2) # 可能有重制版，因此会有多个简介
            elif "歌词" in text:
                lyc_header = h2
        if not intro_header:
            intro_header = soup.find('h2')
        
        if intro_header:
            def process_text(name: str, text: str, summary_parts: List[str], last_was_a: bool) -> bool:
                if not text:
                    return last_was_a
                # 截至现在已有--次观看，--人收藏 这句话是没有意义的，尝试删除
                text = text.replace("截至现在已有--次观看，--人收藏", "").strip()
                text = text.replace("截至目前已有--次观看，--人收藏", "").strip()
                text = text.replace("截至现在bilibili已有--次观看，--次收藏", "").strip()
                if summary_parts and (last_was_a or name == 'a'):
                    summary_parts[-1] += text
                else:
                    summary_parts.append(text)
                return name == 'a'
            for header in intro_header:
                summary_parts = []
                last_was_a = False
                for sibling in header.next_siblings:
                    if sibling.name == 'h2' or sibling.name == 'h3':
                        break
                    if sibling.name in ['p', None, 'a']:
                        text = sibling.get_text(strip=True)
                        last_was_a = process_text(sibling.name, text, summary_parts, last_was_a)

                    elif sibling.name in ['ul', 'ol']:
                        for li in sibling.find_all('li'):
                            text = li.get_text(strip=True)
                            last_was_a = process_text('li', text, summary_parts, last_was_a)

                    elif sibling.name == 'div':
                        table = sibling.find('table')
                        if table:
                            new_infobox_data = self._get_data_from_infobox(table, single_col=True)
                            infobox_data.update(new_infobox_data)

                summary.append("\n".join(summary_parts))
                short_summary.append("\n".join(summary[-1].split("\n")[:3])) # 取前100字作为简短摘要

        if lyc_header :
            type = "Song"
        else:
            type = "Person"
        
        lyrics = ""
        if lyc_header:
            poem = None
            new_table = None
            for sibling in lyc_header.next_siblings:
                if sibling.name == 'table':
                    if sibling.get('class', []) == ['navbox']:
                        break
                    new_table = sibling
                    break
                if sibling.name ==  "div":
                    nt = sibling.find('table')
                    if nt and nt.get('class', []) != ['navbox']:
                        new_table = nt
                        break
            for sibling in lyc_header.next_siblings:
                if sibling.name == 'div' and 'poem' in sibling.get('class', []):
                    poem = sibling
                    break

                if sibling.name ==  "div" and sibling.get('class', []) in [['Tabs'], ['tabLabelTop']]:
                    poem = sibling.find('div', class_='poem')
                    break
            if poem:
                p_tag = poem.find('p')
                if p_tag:
                    span_tags = p_tag.find_all('span')
                    if span_tags:
                        for span in span_tags:
                            if span is None:
                                continue
                            lyrics += span.get_text() + " "
                        # lyrics = "".join([span.get_text() for span in span_tags])
                        lyrics = lyrics.replace('\u3000', ' ').strip()
            if new_table:
                print("find lyrics table")
                new_infobox_data = self._get_data_from_infobox(new_table, single_col=False)
                infobox_data.update(new_infobox_data)

        return {
            "name": title,
            "type": type,
            "infobox": infobox_data,
            "summary": summary,
            "short_summary": short_summary,
            "lyrics": lyrics
        }

    def _save_data(self, data: Dict[str, Any]):
        save_dir = self.default_save_dir
        
        save_dir.mkdir(parents=True, exist_ok=True)
        
        safe_title = "".join([c for c in data['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()
        file_path = save_dir / f"{safe_title}.json"
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"Saved {data['name']} to {file_path}")
        except Exception as e:
            self.logger.error(f"Error saving data to {file_path}: {e}")

    def _format_data(self, data: Dict[str, Any], short_summary:bool = True) -> str:
        if short_summary:
            data.pop("summary", None)
        else:
            data.pop("short_summary", None)
        return json.dumps(data, ensure_ascii=False)
