"""
DiaryOperations / DiaryTask 单元测试。
"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

server_root = str(Path(__file__).resolve().parents[3])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.skills.expression._diary_materials import DiaryMaterials
from src.infrastructure.persistence.database.sql_database import (
    Base,
    DynamicPost,
    User,
    _migrate_sqlite_schema,
)


# ────────────────────── _parse_diary_result ──────────────────────


def test_parse_diary_result_standard_format():
    capability = DiaryMaterials({}, database=None)
    raw = (
        "心情：开心\n"
        "\n"
        "今天和主人聊了很多关于音乐的话题。\n"
        "\n"
        "晚上还一起听了新歌。"
    )
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert result == (
        "2026-07-16 · 心情: 开心\n"
        "\n"
        "今天和主人聊了很多关于音乐的话题。\n"
        "\n"
        "晚上还一起听了新歌。"
    )


def test_parse_diary_result_english_colon():
    capability = DiaryMaterials({}, database=None)
    raw = "心情: 温暖\n\n今天天气很好。"
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert result.startswith("2026-07-16 · 心情: 温暖")


def test_parse_diary_result_no_mood():
    capability = DiaryMaterials({}, database=None)
    raw = "今天只是平平淡淡的一天。"
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert result.startswith("2026-07-16")
    assert "心情" not in result.split("\n")[0]


def test_parse_diary_result_skips_title_and_summary():
    capability = DiaryMaterials({}, database=None)
    raw = (
        "标题：日记\n"
        "摘要：今天很好\n"
        "心情：平静\n"
        "\n"
        "正文内容。"
    )
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert "标题" not in result
    assert "摘要" not in result
    assert result.startswith("2026-07-16 · 心情: 平静")


def test_parse_diary_result_empty_input():
    capability = DiaryMaterials({}, database=None)
    assert capability._parse_diary_result("", target_date="2026-07-16") is None
    assert capability._parse_diary_result("   \n ", target_date="2026-07-16") is None


def test_parse_diary_result_think_only_is_empty():
    capability = DiaryMaterials({}, database=None)
    assert capability._parse_diary_result("<think>只返回思考</think>", target_date="2026-07-16") is None


def test_parse_diary_result_compresses_excess_blank_lines():
    capability = DiaryMaterials({}, database=None)
    raw = "心情：开心\n\n正文第一段。\n\n\n\n\n正文第二段。"
    result = capability._parse_diary_result(raw, target_date="2026-07-16")
    assert "\n\n\n" not in result


def test_parse_diary_result_accepts_inline_body_label():
    capability = DiaryMaterials({}, database=None)
    raw = "心情：平静\n正文：第一段。\n\n第二段。"

    result = capability._parse_diary_result(raw, target_date="2026-07-16")

    assert result.endswith("第一段。\n\n第二段。")


# ────────────────────── _strip_think_block ──────────────────────


def test_strip_think_block():
    capability = DiaryMaterials({}, database=None)
    raw = (
        "<think>用户今天提到了音乐，我应该围绕音乐写。</think>\n"
        "心情：感动\n\n今天主人教我唱新歌了。"
    )
    stripped = capability._strip_think_block(raw)
    assert "think" not in stripped
    assert stripped.startswith("心情：感动")


def test_strip_think_block_absent():
    capability = DiaryMaterials({}, database=None)
    raw = "心情：开心\n\n普通内容。"
    assert capability._strip_think_block(raw) == raw
