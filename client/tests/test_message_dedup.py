"""历史消息去重工具测试：批次内重复、缺 uuid 兜底 ID、已有列表 + 批次内重复、顺序保持。"""

from src.types import ConversationItem
from src.utils.message_dedup import build_fallback_uuid, deduplicate_by_uuid


def _item(uuid_: str, content: str = "x"):
    return ConversationItem(
        timestamp="2026-01-01 00:00:00",
        source="agent",
        type="text",
        content=content,
        uuid=uuid_,
    )


def test_dedup_same_batch_duplicate_uuid_keeps_first():
    items = [_item("a", "1"), _item("a", "2"), _item("b", "3")]
    result = deduplicate_by_uuid([], items)
    assert [i.uuid for i in result] == ["a", "b"]


def test_dedup_filters_existing_and_in_batch_duplicates():
    items = [_item("new-id", "1"), _item("new-id", "2"), _item("old-id", "3")]
    result = deduplicate_by_uuid(["old-id"], items)
    assert [i.uuid for i in result] == ["new-id"]


def test_dedup_keeps_incoming_order():
    items = [_item("b"), _item("a"), _item("c"), _item("a")]
    result = deduplicate_by_uuid([], items)
    assert [i.uuid for i in result] == ["b", "a", "c"]


def test_fallback_uuid_is_deterministic_and_distinct():
    first = build_fallback_uuid("user", "text", "2026-01-01 00:00:00", "第一条")
    second = build_fallback_uuid("user", "text", "2026-01-01 00:00:00", "第二条")
    assert first != second
    assert build_fallback_uuid("user", "text", "2026-01-01 00:00:00", "第一条") == first


def test_fallback_uuid_uses_safe_filename_characters():
    result = build_fallback_uuid("user", "image", "2026-01-01 00:00:00", "路径/内容")
    assert result == result.lower()
    assert all(c.isalnum() or c == "-" for c in result)


def test_conversation_item_fills_missing_uuid_deterministically():
    item = ConversationItem(
        timestamp="2026-01-01 00:00:00",
        source="agent",
        type="text",
        content="你好",
        uuid=None,
    )
    assert item.uuid
    assert item.uuid.startswith("history-")
    again = ConversationItem(
        timestamp="2026-01-01 00:00:00",
        source="agent",
        type="text",
        content="你好",
        uuid=None,
    )
    assert again.uuid == item.uuid
