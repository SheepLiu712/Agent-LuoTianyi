"""旧对话展示兼容秒级与带微秒的 ISO 时间。"""

from src.domain.conversation_type import timestamp_to_date, timestamp_to_elapsed_time


def test_timestamp_to_date_accepts_old_and_microsecond_formats():
    assert timestamp_to_date("2026-09-14 12:34:56") == "2026-09-14"
    assert timestamp_to_date("2026-09-14 12:34:56.123456") == "2026-09-14"


def test_invalid_timestamp_preserves_original_value():
    assert timestamp_to_date("not-a-time") == "not-a-time"
    assert timestamp_to_elapsed_time("not-a-time") == "not-a-time"
