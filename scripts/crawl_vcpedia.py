"""
VCPedia Crawler Script
----------------------
用于爬取 VCPedia (或类似的 MediaWiki 站点) 页面内容，并保存为 JSON 格式。
生成的数据可以直接被 KnowledgeBuilder 读取并构建知识图谱。

依赖库:
pip install requests beautifulsoup4
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import sys
import random
from typing import Dict, Any, List, Optional
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.llm.llm_module import LLMModule
from src.llm.prompt_manager import PromptManager
from src.utils.helpers import load_config
from src.utils.logger import get_logger

# 配置
BASE_URL = "https://vcpedia.cn/" # 示例：萌娘百科或VCPedia的地址
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
OUTPUT_DIR = "data/raw_knowledge/vcpedia"
DELAY_RANGE = (1, 3) # 请求间隔秒数，避免被封

class VCPediaCrawler:
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        self.logger = get_logger(__name__)
        self.base_url = config["vcpedia"]["base_url"]
        self.output_dir = Path(config["vcpedia"]["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.use_llm = config.get("use_llm", True)
        if self.use_llm:
            self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.logger.info(f"Initialized VCPediaCrawler with base URL: {self.base_url}, use_llm: {self.use_llm}")

    def fetch_page(self, page_name: str) -> Optional[str]:
        """获取页面HTML"""
        url = f"{self.base_url}/{page_name}"
        try:
            print(f"Fetching: {url}")
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                self.logger.info(f"Successfully fetched page: {page_name}")
                return response.text
            else:
                print(f"Failed to fetch {url}: Status {response.status_code}")
                return None
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
        
    def _get_data_from_infobox(self, infobox_table, single_col = False) -> Dict[str, str]:
            print("Extracting Infobox data")
            infobox_data = {}
            rows = infobox_table.find_all('tr')
            preserved_title = None

            def get_title(text: str) -> str | None:
                # 简单清洗标题
                text = text.strip()
                if "演唱" in text:
                    return "演唱"
                if "作词" in text:
                    return "作词"
                if "作曲" in text:
                    return "作曲"
                if "编曲" in text:
                    return "编曲"
                if "作编曲" in text:
                    return "作编曲"
                if "PV" in text:
                    return "PV"
                if "UP主" in text:
                    return "UP主"
                if "曲绘" in text:
                    return "曲绘"
                return None

            for row in rows:
                # 跳过隐藏行
                if 'display:none' in row.get('style', ''):
                    continue
                    
                cols = row.find_all(['th', 'td'])
                
                # 情况 1: 标准 th + td 或 td + td (左右结构)
                if len(cols) == 2:
                    key = cols[0].get_text(strip=True)
                    val_col = cols[1]
                    # 处理 <br>
                    for br in val_col.find_all('br'):
                        br.replace_with(',')
                    value = val_col.get_text(strip=True)
                    infobox_data[key] = value

                # 情况 2: 单列 (可能是垂直结构的 Key 或 Value，也可能是图片)
                elif len(cols) == 1 and single_col:
                    col = cols[0]
                    # 跳过图片容器
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

        
    def parse_page(self, html: str, title: str) -> Dict[str, Any]:
        """解析页面内容"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. 提取 Infobox (信息栏)
        # 注意：不同Wiki的Infobox类名可能不同，常见为 'infobox', 'infobox-v2', 'wikitable'
        infobox_data = {}
        # 优先匹配 moe-infobox (VCPedia 特有)
        infobox_table = soup.find('table', class_='moe-infobox infobox')
        
        if infobox_table:
            new_infobox_data = self._get_data_from_infobox(infobox_table, single_col=True)
            infobox_data.update(new_infobox_data)

        # 2. 提取简介 (Summary)
        summary_parts = []
        
        # 策略A: 查找 "简介" 章节 (用户推荐)
        # 查找包含"简介"文本的 h2 标签
        intro_header = None
        lyc_header = None
        for h2 in soup.find_all('h2'):
            if '简介' in h2.get_text() or "VOCALOID原创作者" in h2.get_text():
                intro_header = h2
            elif "歌词" in h2.get_text():
                lyc_header = h2
        if intro_header is None:
            # 获取第一个h2作为简介
            intro_header = soup.find('h2')
        
        if intro_header:
            # 遍历后续兄弟节点，直到遇到下一个 h2
            for sibling in intro_header.next_siblings:
                if sibling.name == 'h2' or sibling.name == 'h3':
                    break
                if sibling.name == 'p':
                    text = sibling.get_text(strip=True)
                    if text:
                        summary_parts.append(text)
                elif sibling.name == "ul" or sibling.name == "ol":
                    for li in sibling.find_all('li'):
                        text = li.get_text(strip=True)
                        if text:
                            summary_parts.append(text)
                elif sibling.name == 'div':
                    # 其中可能有一个table，继续查找p标签
                    table = sibling.find('table')
                    if table:
                        new_infobox_data = self._get_data_from_infobox(table, single_col=True)
                        infobox_data.update(new_infobox_data)

        summary = "\n".join(summary_parts)

        if lyc_header :
            type = "Song"
        else:
            type = "Person"
        
        # 3. 提取歌词 (如果有)
        poem = None
        if lyc_header:
            for sibling in lyc_header.next_siblings:
                if sibling.name == 'div' and 'poem' in sibling.get('class', []):
                    poem = sibling
                    print("Poem div found")
                    break
        if poem:
            p_tag = poem.find('p')
            
            if p_tag:
                span_tag = p_tag.find('span')
                if span_tag:
                        lyrics = span_tag.get_text()
                        lyrics = lyrics.replace('\u3000', ' ').strip()
        else:
            lyrics = ""

        return {
            "name": title,
            "type": type,
            "infobox": infobox_data,
            "summary": summary,
            "lyrics": lyrics
        }

    def save_data(self, data: Dict[str, Any]):
        """保存数据为JSON"""
        # 文件名处理，避免非法字符
        safe_title = "".join([c for c in data['name'] if c.isalnum() or c in (' ', '-', '_')]).strip()
        file_path = self.output_dir / f"{safe_title}.json"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Saved to {file_path}")
       

    def run(self, page_names: List[str]):
        """批量爬取"""
        for page in page_names:
            html = self.fetch_page(page)
            if html:
                try:
                    data = self.parse_page(html, page)
                    print(data)
                except Exception as e:
                    print(f"Failed to parse page {page}: {e}")
                    continue

                if False:
                    # data to str
                    data_str = json.dumps(data, ensure_ascii=False)
                    try:
                        structured_data = self.llm.generate_response(page_content = data_str)
                    except Exception as e:
                        print(f"LLM processing failed for {page}: {e}")
                        continue
                else:
                    structured_data_json = data
                    self.save_data(structured_data_json)
                    continue

                # str to json
                try:
                    structured_data_json = json.loads(structured_data)
                    self.save_data(structured_data_json)
                except Exception as e:
                    print(f"Failed to parse LLM output for {page}: {e}")
                    print(f"LLM Output:\n{structured_data}\n")
                    continue
            
            # 随机延时
            time.sleep(random.uniform(*DELAY_RANGE))

if __name__ == "__main__":
    config = load_config("config/config.json")
    prompt_manager = PromptManager(config["prompt_manager"])
    # 示例用法
    crawler = VCPediaCrawler(
        config["crawler"],
        prompt_manager
    )
    
    # 待爬取的词条列表
    pages_to_crawl = [
        "Ilem"
    ]
    
    crawler.run(pages_to_crawl)
