import json
from datetime import datetime

import pytest

from src.world.bili_event_updater.event_parser import EventParser
from src.world.bili_event_updater.types import OfficialDynamic


def dynamic(content: str, published: str = "2026-09-26T18:55:35") -> OfficialDynamic:
    return OfficialDynamic(
        uid="36081646",
        account_name="洛天依",
        character="luotianyi",
        platform="bilibili",
        dynamic_id="one",
        dynamic_type="DYNAMIC_TYPE_WORD",
        content=content,
        raw_content=content,
        pics=[],
        publish_time=published,
        source_url="https://www.bilibili.com/opus/one",
    )


class FakeLLM:
    def __init__(self, result):
        self.result = result

    async def generate_response(self, **kwargs):
        return json.dumps(self.result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_missing_model_date_uses_explicit_activity_date_not_publish_time():
    item = dynamic("Vsinger创作激励计划：活动时间 2026年9月25日0点-11月30日24点。")
    parser = EventParser(llm_module=FakeLLM([{"title": "创作激励计划", "event_type": "general", "start_time": ""}]))

    events = await parser.parse_one(item)

    assert len(events) == 1
    assert events[0]["start_datetime"] == datetime(2026, 9, 25, 0)
    assert events[0]["start_datetime"] != datetime.fromisoformat(item.publish_time)


@pytest.mark.asyncio
async def test_undated_model_event_is_not_persisted_with_publish_time():
    item = dynamic("未来会有活动，敬请期待")
    parser = EventParser(llm_module=FakeLLM([{"title": "未知活动", "event_type": "general", "start_time": ""}]))

    assert await parser.parse_one(item) == []


@pytest.mark.asyncio
async def test_invalid_model_json_aborts_batch_for_retry():
    class InvalidLLM:
        async def generate_response(self, **kwargs):
            return "The event is tomorrow"

    parser = EventParser(llm_module=InvalidLLM())
    with pytest.raises(ValueError, match="no JSON array"):
        await parser.parse_dynamics([dynamic("明天有活动")])


@pytest.mark.asyncio
async def test_empty_model_response_aborts_batch_for_retry():
    class EmptyLLM:
        async def generate_response(self, **kwargs):
            return ""

    parser = EventParser(llm_module=EmptyLLM())
    with pytest.raises(ValueError, match="empty response"):
        await parser.parse_dynamics([dynamic("10月1日有直播")])


@pytest.mark.asyncio
@pytest.mark.parametrize("with_model", [False, True])
async def test_ticket_sale_date_is_not_used_as_concert_date(with_model):
    item = dynamic("洛天依巡回演唱会武汉站将于9月25日19点开票，购票请见详情。")
    llm = FakeLLM([{"title": "武汉站演唱会", "event_type": "concert", "start_time": "2026-09-25T19:00:00"}])
    parser = EventParser(llm_module=llm if with_model else None)

    assert await parser.parse_one(item) == []


@pytest.mark.asyncio
async def test_concert_date_survives_when_post_also_mentions_ticket_sale():
    item = dynamic("洛天依演唱会9月25日19点开票。演出时间：10月31日19:12，武汉见！")
    llm = FakeLLM([{"title": "武汉站演唱会", "event_type": "concert", "start_time": "2026-10-31T19:12:00"}])

    events = await EventParser(llm_module=llm).parse_one(item)

    assert events[0]["start_datetime"] == datetime(2026, 10, 31, 19, 12)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_model", [False, True])
async def test_explicit_performance_date_wins_over_ticket_date(with_model):
    item = dynamic("洛天依演唱会9月25日19点开票。演出时间：10月31日19:12，武汉见！")
    llm = FakeLLM([{"title": "武汉站演唱会", "event_type": "concert", "start_time": "2026-09-25T19:00:00"}])
    events = await EventParser(llm_module=llm if with_model else None).parse_one(item)

    assert events[0]["start_datetime"] == datetime(2026, 10, 31, 19, 12)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_model", [False, True])
async def test_merchandise_sale_is_not_treated_as_concert(with_model):
    item = dynamic("仅为商品销售广告：洛天依演唱会周边将于9月28日19点开售，没有演出活动。")
    llm = FakeLLM([{"title": "洛天依演唱会", "event_type": "concert", "start_time": "2026-09-28T19:00:00"}])
    parser = EventParser(llm_module=llm if with_model else None)

    assert await parser.parse_one(item) == []


@pytest.mark.asyncio
async def test_parser_failure_aborts_batch_for_retry():
    class BrokenLLM:
        async def generate_response(self, **kwargs):
            raise RuntimeError("model unavailable")

    parser = EventParser(llm_module=BrokenLLM())
    with pytest.raises(RuntimeError, match="model unavailable"):
        await parser.parse_dynamics([dynamic("10月1日19点直播")])


@pytest.mark.asyncio
async def test_rule_fallback_uses_chinese_hour_and_publication_year():
    parser = EventParser()
    events = await parser.parse_one(dynamic("10月1日19点直播见！", "2026-09-26T18:55:35"))

    assert events[0]["start_datetime"] == datetime(2026, 10, 1, 19)
