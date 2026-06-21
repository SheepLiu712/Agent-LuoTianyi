import json
import os
import sys

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.world.public_diary import CitywalkDiaryProvider


def test_citywalk_diary_provider_maps_reports_to_public_diaries(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    report_path = report_dir / "citywalk_20260620_120000.json"
    report_path.write_text(
        json.dumps(
            {
                "title": "逛街小洛",
                "created_at": "2026-06-20T12:00:00",
                "overview": {
                    "city": "上海",
                    "selected_destination": "人民广场",
                },
                "diary_text": "今天在人民广场散步，听到了很热闹的声音。",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    provider = CitywalkDiaryProvider(report_dir, owner_character_id="luotianyi")

    entries = provider.list_public_diaries()
    assert len(entries) == 1
    assert entries[0].entry_id == "citywalk_20260620_120000"
    assert entries[0].visibility == "public"
    assert entries[0].source == "citywalk"
    assert entries[0].owner_character_id == "luotianyi"
    assert entries[0].title == "逛街小洛 · 上海"
    assert entries[0].metadata["selected_destination"] == "人民广场"

    world_event = entries[0].to_world_event()
    assert world_event.event_type == "public_diary"
    assert world_event.is_personal is False
    assert world_event.target_user_id is None
    assert world_event.metadata["owner_character_id"] == "luotianyi"


def test_citywalk_diary_provider_exposes_context_and_handles_empty_dir(tmp_path):
    provider = CitywalkDiaryProvider(tmp_path / "missing")
    assert provider.list_public_diaries() == []
    assert provider.list_active_events() == []
    assert provider.get_context_for_runtime("user-1") == ""

    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    for index in range(4):
        (report_dir / f"citywalk_2026062{index}_120000.json").write_text(
            json.dumps(
                {
                    "created_at": f"2026-06-2{index}T12:00:00",
                    "diary_text": f"第 {index} 天的散步记录",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    provider = CitywalkDiaryProvider(report_dir)
    context = provider.get_context_for_runtime("user-1")

    assert "第 3 天的散步记录" in context
    assert "第 0 天的散步记录" not in context
