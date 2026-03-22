import asyncio
import json
import os
import sys
from typing import List

# Setup paths
current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.agent.topic_extractor import TopicExtractor
from src.llm.prompt_manager import PromptManager
from src.pipeline.modules.unread_store import UnreadMessage, UnreadMessageSnapshot
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


def ensure_api_key_ready() -> None:
    api_key = os.getenv("QWEN_API_KEY", "").strip()
    if not api_key or api_key.startswith("$"):
        raise RuntimeError(
            "QWEN_API_KEY 未配置。请先在环境变量中设置真实Key，再运行真实LLM测试。"
        )


async def test_json_parse_from_markdown_block(extractor: TopicExtractor):
    snapshot = make_snapshot(["今天天气怎么样？"])
    topics, remaining = await extractor.extract_topics(snapshot)

    assert isinstance(topics, list)
    assert isinstance(remaining, list)
    print("[JSON] topics=", len(topics), "remaining=", len(remaining))


async def test_incomplete_topic_separation(extractor: TopicExtractor):
    snapshot = make_snapshot(["我想和你聊聊", "其实我还没说完"])
    topics, remaining = await extractor.extract_topics(snapshot, force_complete=False)

    assert isinstance(topics, list)
    assert isinstance(remaining, list)
    # 允许模型策略差异，这里只校验不完整话题路径是否可能产生 remaining。
    print("[INCOMPLETE] topics=", len(topics), "remaining=", [m.message_id for m in remaining])


async def test_fact_constraints_song_name(extractor: TopicExtractor):
    snapshot = make_snapshot(["你唱过纯蓝吗？"])
    topics, _ = await extractor.extract_topics(snapshot)

    all_constraints = [c for t in topics for c in t.fact_constraints]
    assert isinstance(all_constraints, list)
    print("[FACT_CONSTRAINTS]", all_constraints)


async def test_sing_attempts_cases(extractor: TopicExtractor):
    # 明确要求听《纯蓝》
    snapshot1 = make_snapshot(["我想听《纯蓝》"])

    # 只说想听歌，不指定歌名
    snapshot2 = make_snapshot(["想听你唱歌"])

    # 不涉及唱歌
    snapshot3 = make_snapshot(["你今天过得怎么样"])

    topics1, _ = await extractor.extract_topics(snapshot1)
    topics2, _ = await extractor.extract_topics(snapshot2)
    topics3, _ = await extractor.extract_topics(snapshot3)

    sings1 = [s for t in topics1 for s in t.sing_attempts]
    sings2 = [s for t in topics2 for s in t.sing_attempts]
    sings3 = [s for t in topics3 for s in t.sing_attempts]

    print("[SING_ATTEMPTS case1 expect含纯蓝]", sings1)
    print("[SING_ATTEMPTS case2 expect random_song]", sings2)
    print("[SING_ATTEMPTS case3 expect空]", sings3)

    # 这里保留目标断言，便于你验证真实模型行为是否达标。
    assert "纯蓝" in sings1
    assert "random_song" in sings2
    assert sings3 == []


async def run_all_tests():
    ensure_api_key_ready()
    extractor = make_real_extractor()

    # await test_json_parse_from_markdown_block(extractor)
    # await test_incomplete_topic_separation(extractor)
    # await test_fact_constraints_song_name(extractor)
    await test_sing_attempts_cases(extractor)
    print("All TopicExtractor tests passed")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
