"""歌曲知识接纳：幂等写入、已有项跳过、失败不留半份与处理器结算。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as d
from src.agent.handlers.stimulus.song_knowledge import SongKnowledgeHandler
from src.agent.skills.knowledge.song_acceptance import (
    SongAcceptanceStatus,
    SongKnowledgeAcceptanceSkill,
)
from src.infrastructure.song_knowledge.database import Song, get_song_session

SONG_NAME = "新歌"
LYRIC_KEYWORDS = ("一句歌词", "两句歌词")


def skill_config(tmp_path):
    knowledge = tmp_path / "knowledge"
    return {
        "song_database": {"db_folder": str(knowledge), "db_file": "knowledge_db.db"},
        "knowledge_dir": str(knowledge),
    }


def candidate(song_name=SONG_NAME, introduction="一首歌的介绍"):
    return d.SongKnowledgeCandidate(
        song_name=song_name, uploader="UP主", singers=("歌手A", "歌手B"),
        introduction=introduction, lyrics="歌词正文", lyric_keywords=LYRIC_KEYWORDS,
    )


def source_ref():
    return d.SourceRef(source_id="vcpedia")


async def accept(skill, *, song_name=SONG_NAME, revision=7):
    return await skill.accept(
        source_ref=source_ref(), external_song_id=song_name, revision=revision,
        candidate=candidate(song_name=song_name),
    )


def stored_names(session):
    return [row.name for row in session.query(Song).all()]


def test_skill_rejects_invalid_arguments(tmp_path):
    skill = SongKnowledgeAcceptanceSkill(skill_config(tmp_path))
    import asyncio

    for kwargs in (
        {"source_ref": "vcpedia", "external_song_id": SONG_NAME, "revision": 1, "candidate": candidate()},
        {"source_ref": source_ref(), "external_song_id": " ", "revision": 1, "candidate": candidate()},
        {"source_ref": source_ref(), "external_song_id": SONG_NAME, "revision": -1, "candidate": candidate()},
        {"source_ref": source_ref(), "external_song_id": SONG_NAME, "revision": 1, "candidate": {}},
    ):
        try:
            asyncio.run(skill.accept(**kwargs))
        except (TypeError, ValueError):
            continue
        raise AssertionError(f"非法参数未被拒绝：{kwargs}")


async def test_accept_writes_knowledge_and_keywords(tmp_path):
    skill = SongKnowledgeAcceptanceSkill(skill_config(tmp_path))

    result = await accept(skill)

    assert result.status is SongAcceptanceStatus.ACCEPTED
    assert result.knowledge_written is True
    assert "vcpedia" in result.detail
    session = get_song_session()
    try:
        row = session.query(Song).filter(Song.name == SONG_NAME).one()
        assert row.safe_name == SONG_NAME
        assert row.uploader == "UP主"
        assert row.singers == "歌手A,歌手B"
        assert row.introduction == "一首歌的介绍"
        assert row.lyrics == "歌词正文"
    finally:
        session.close()
    knowledge = tmp_path / "knowledge"
    assert (knowledge / "song_name_keywords.txt").read_text(encoding="utf-8").splitlines() == [SONG_NAME]
    assert (knowledge / "song_lyric_keywords.txt").read_text(encoding="utf-8").splitlines() == [
        f"{keyword}=>{keyword}是《{SONG_NAME}》的歌词" for keyword in LYRIC_KEYWORDS
    ]


async def test_second_accept_skips_existing_without_duplicate_keywords(tmp_path):
    skill = SongKnowledgeAcceptanceSkill(skill_config(tmp_path))
    await accept(skill)

    second = await accept(skill, revision=8)

    assert second.status is SongAcceptanceStatus.ALREADY_PRESENT
    assert second.knowledge_written is False
    session = get_song_session()
    try:
        assert stored_names(session) == [SONG_NAME]
    finally:
        session.close()
    knowledge = tmp_path / "knowledge"
    assert (knowledge / "song_name_keywords.txt").read_text(encoding="utf-8").splitlines() == [SONG_NAME]
    assert len((knowledge / "song_lyric_keywords.txt").read_text(encoding="utf-8").splitlines()) == 2


async def test_blank_introduction_is_rejected_by_the_domain_type():
    for blank in ("", "   "):
        with pytest.raises(d.InvalidStimulusError):
            candidate(introduction=blank)


async def test_keyword_failure_rolls_back_knowledge(tmp_path):
    skill = SongKnowledgeAcceptanceSkill(skill_config(tmp_path))

    def boom(song_name, lyric_keywords):
        raise OSError("磁盘不可写")

    skill._append_keywords = boom

    result = await accept(skill)

    assert result.status is SongAcceptanceStatus.FAILED
    assert "关键词索引写入失败" in result.detail
    session = get_song_session()
    try:
        assert stored_names(session) == []
    finally:
        session.close()


def world_request(fact):
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    snapshot = d.WorldInteractionSnapshot(
        interaction_id="wi", interaction_revision=1, user_id=None, pending_stimuli=(fact,),
        now=now, timezone=ZoneInfo("UTC"), supported_outputs=frozenset(), world_id="default",
        world_revision=0, activity_id=None, activity_revision=None,
        planning_cycle_id=None, schedule_revision=0,
    )
    return d.HandleStimulusRequest(
        request_id="wr", stimulus=fact, interaction=snapshot, cancellation=d.CancellationToken(),
    )


def discovered(song_name=SONG_NAME):
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    return d.SongKnowledgeDiscovered(
        stimulus_id="sk1", schema_version=1, occurred_at=now, source=d.StimulusSource.WORLD,
        target_character_ids=("luotianyi",), user_id=None, ephemeral=False,
        source_ref=source_ref(), external_song_id=song_name, revision=7,
        candidate=candidate(song_name=song_name), fetched_at=now,
    )


async def test_handler_accepts_and_consumes_stimulus(tmp_path):
    handler = SongKnowledgeHandler(SongKnowledgeAcceptanceSkill(skill_config(tmp_path)))

    report = await handler.handle(world_request(discovered()), None)

    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.consumed_pending_stimulus_ids == ("sk1",)
    assert report.retained_pending_stimulus_ids == ()
    assert report.emitted_plan_ids == ()
    assert report.error_code is None
    assert report.retryable is False


async def test_handler_skips_existing_without_error(tmp_path):
    handler = SongKnowledgeHandler(SongKnowledgeAcceptanceSkill(skill_config(tmp_path)))
    await handler.handle(world_request(discovered()), None)

    report = await handler.handle(world_request(discovered()), None)

    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.consumed_pending_stimulus_ids == ("sk1",)


async def test_handler_reports_store_failure_as_dependency_failure(tmp_path):
    handler = SongKnowledgeHandler(SongKnowledgeAcceptanceSkill(skill_config(tmp_path)))

    def boom(song_name, lyric_keywords):
        raise OSError("磁盘不可写")

    handler._skill._append_keywords = boom

    report = await handler.handle(world_request(discovered()), None)

    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    assert report.consumed_pending_stimulus_ids == ()
    assert report.retained_pending_stimulus_ids == ("sk1",)


async def test_handler_rejects_other_stimulus_kinds(tmp_path):
    handler = SongKnowledgeHandler(SongKnowledgeAcceptanceSkill(skill_config(tmp_path)))
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    foreign = d.WorldObservation(
        stimulus_id="wo1", schema_version=1, occurred_at=now, source=d.StimulusSource.WORLD,
        target_character_ids=("luotianyi",), user_id=None, ephemeral=False,
        observation_kind=d.WorldObservationKind(value="citywalk"), fact=d.WorldFact(fact_id="f", summary="散步"),
        evidence_refs=(), world_revision=1,
    )

    try:
        await handler.handle(world_request(foreign), None)
    except TypeError:
        return
    raise AssertionError("非歌曲知识刺激未被拒绝")
