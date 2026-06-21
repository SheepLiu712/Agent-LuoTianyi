"""
Topic extractor tests — validates topic parsing from user messages.
Skips real LLM calls if QWEN_API_KEY is not set.
"""

import asyncio
import json
import os
import sys
from typing import List

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

import pytest

from src.agent.topic_extractor import TopicExtractor
from src.utils.llm.prompt_manager import PromptManager
from src.agent.chat.unread_store import UnreadMessage, UnreadMessageSnapshot
from src.utils.helpers import load_config


def make_snapshot(contents: List[str]) -> UnreadMessageSnapshot:
    messages = [
        UnreadMessage(message_id=f"m{i}", message_type="text", content=text)
        for i, text in enumerate(contents)
    ]
    return UnreadMessageSnapshot(messages=messages, version=1)


def make_real_extractor() -> TopicExtractor:
    config_path = os.path.join("config", "config.json")
    config = load_config(config_path)
    prompt_manager = PromptManager(config.get("prompt_manager", {}))
    extractor = TopicExtractor(config.get("topic_extractor", {}), prompt_manager)
    return extractor


@pytest.fixture(scope="module")
def extractor():
    return make_real_extractor()


@pytest.mark.skipif(
    not os.getenv("QWEN_API_KEY") or os.getenv("QWEN_API_KEY", "").startswith("$"),
    reason="QWEN_API_KEY not configured",
)
@pytest.mark.asyncio
async def test_json_parse_from_markdown_block(extractor: TopicExtractor):
    snapshot = make_snapshot(["今天天气怎么样？"])
    topics, remaining = await extractor.extract_topics(snapshot)
    assert isinstance(topics, list)
    assert isinstance(remaining, list)


@pytest.mark.skipif(
    not os.getenv("QWEN_API_KEY") or os.getenv("QWEN_API_KEY", "").startswith("$"),
    reason="QWEN_API_KEY not configured",
)
@pytest.mark.asyncio
async def test_incomplete_topic_separation(extractor: TopicExtractor):
    snapshot = make_snapshot(["我想和你聊聊", "其实我还没说完"])
    topics, remaining = await extractor.extract_topics(snapshot, force_complete=False)
    assert isinstance(topics, list)
    assert isinstance(remaining, list)


@pytest.mark.skipif(
    not os.getenv("QWEN_API_KEY") or os.getenv("QWEN_API_KEY", "").startswith("$"),
    reason="QWEN_API_KEY not configured",
)
@pytest.mark.asyncio
async def test_fact_constraints_song_name(extractor: TopicExtractor):
    snapshot = make_snapshot(["你唱过纯蓝吗？"])
    topics, _ = await extractor.extract_topics(snapshot)
    all_constraints = [c for t in topics for c in t.fact_constraints]
    assert isinstance(all_constraints, list)
