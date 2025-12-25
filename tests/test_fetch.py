import sys
import os
import json

# add cwd to sys.path
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.utils.logger import get_logger
from src.utils.helpers import load_config
from src.utils.vcpedia_fetcher import VCPediaFetcher

config = load_config("config/config.json")
crawler_config = config.get("crawler", {})

fetcher = VCPediaFetcher(crawler_config)

ret = fetcher.fetch_entity_description("三月雨")
print(ret)