"""授权范围内的排序去重与当前歌曲资源查询。"""

import logging
import wave
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from support.skill_support import invocation

from src.agent.skills.expression.singing import SingingSkill
from src.agent.skills.knowledge.song_acceptance import SongKnowledgeStore
from src.agent.skills.memory_retrieval import MemoryQuery, MemoryRetrievalSkill, RetrievalScope
from src.domain.music_type import OneLyricLine, SongMetadata, SongSegment
from src.infrastructure.persistence.database.vector_store import ChromaVectorStore
from src.infrastructure.persistence.song_knowledge import Song, get_song_session
from tests.integration.persistence import test_memory_write_skill as memory_write_tests
from tests.integration.persistence.test_memory_write_skill import fact

setup = memory_write_tests.setup


def skill(setup, tmp_path):
    singing = SingingSkill({"characters": {"luotianyi": {"resource_path": str(tmp_path / "songs")}}})
    knowledge = SongKnowledgeStore({"song_database": {"db_folder": str(tmp_path), "db_file": "knowledge.sqlite"}})
    return (
        MemoryRetrievalSkill(
            {},
            memories={"luotianyi": setup.reader(), "miku": setup.reader("miku")},
            singing=singing,
            knowledge=knowledge,
        ),
        singing,
    )


async def test_current_character_is_not_crowded_out_and_multiple_queries_deduplicate(setup, tmp_path):
    async def search(user_id, query, k=5, **kwargs):
        values = list(setup.vectors.documents.items())
        if "ids" in kwargs:
            values = [(key, doc) for key, doc in values if key in kwargs["ids"]]
        else:
            values = [(key, doc) for key, doc in values if doc.get_metadata()["user_id"] == user_id]
        return [(doc, 0.99) for key, doc in values[:k]]

    setup.vectors.search = search
    for index in range(3):
        await setup.skill.commit_fact(invocation(), fact=fact(str(index), content=f"天依事实{index}"))
    own = await setup.skill.commit_fact(invocation("miku"), fact=fact("miku-1", content="miku事实"))
    retrieval, _ = skill(setup, tmp_path)
    result = await retrieval.search(invocation("miku"), query=MemoryQuery(("事实", "另一个线索"), limit=2))
    assert [hit.memory_record_id for hit in result.hits] == list(own.memory_ids)
    assert result.hits[0].source == "canonical_vector"
    with pytest.raises(ValueError, match="作用域"):
        MemoryQuery(("事实",), scopes=frozenset(("其他用户",)))


async def test_empty_memory_and_backend_failure_are_distinct(setup, tmp_path):
    retrieval, _ = skill(setup, tmp_path)
    assert (await retrieval.search(invocation(), query=MemoryQuery(("没有事实",)))).hits == ()

    async def unavailable(*args, **kwargs):
        raise RuntimeError("记忆后端不可用")

    setup.vectors.search = unavailable
    with pytest.raises(RuntimeError, match="记忆后端不可用"):
        await retrieval.search(invocation(), query=MemoryQuery(("事实",)))
    with pytest.raises(RuntimeError):
        await retrieval.search(invocation(user_id=None), query=MemoryQuery(("用户事实",)))


async def test_song_catalog_and_segments_reflect_actual_resources_without_submitting_tasks(setup, tmp_path):
    retrieval, singing = skill(setup, tmp_path)
    manager = singing._singing._get_manager("luotianyi")
    audio = tmp_path / "song.wav"
    with wave.open(str(audio), "wb") as output:
        output.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * 16000)
    metadata = SongMetadata(
        "歌甲", "歌甲", "介绍", str(audio), "", 0, [SongSegment("副歌", 0, 1, [OneLyricLine(1, "正确歌词")])]
    )
    manager.all_songs[manager.get_unified_song_name("歌甲")] = metadata
    manager.song_aliases[manager.get_unified_song_name("歌甲别名")] = manager.get_unified_song_name("歌甲")
    await retrieval.get_song(invocation(), song_id="歌甲")
    with get_song_session() as session:
        session.add(Song(uuid="alias-knowledge", name="歌甲别名", safe_name="歌甲", introduction="介绍", lyrics="歌词"))
        session.commit()
    page = await retrieval.list_songs(invocation(), limit=1)
    assert page.songs[0].can_sing
    assert page.next_cursor is None
    assert (await retrieval.get_song(invocation(), song_id="歌甲", segment_id="副歌")).lyrics == "正确歌词"
    assert not (await retrieval.get_song(invocation(), song_id="歌甲", segment_id="缺失唱段")).found
    assert not (await retrieval.get_song(invocation(), song_id="完全不同的歌")).found
    assert manager.wishlist.get_all() == {}
    tasks = singing.learning_tasks()
    assert tasks.request(invocation(), song_id="想学的歌")
    assert not tasks.request(invocation(), song_id="想学的歌")
    assert len(manager.wishlist.get_all()) == 1
    audio.unlink()
    assert not (await retrieval.get_song(invocation(), song_id="歌甲")).can_sing


async def test_public_knowledge_has_a_stable_source_and_needs_no_private_user_scope(setup, tmp_path):
    retrieval, _ = skill(setup, tmp_path)
    await retrieval.get_song(invocation(), song_id="歌乙")
    with get_song_session() as session:
        session.add(Song(uuid="knowledge-1", name="歌乙", safe_name="歌乙", introduction="旅行主题", lyrics="歌词"))
        session.commit()
    result = await retrieval.search(
        invocation(user_id=None),
        query=MemoryQuery(("旅行", "歌乙"), scopes=frozenset((RetrievalScope.PUBLIC_KNOWLEDGE,))),
    )
    assert [(hit.memory_record_id, hit.source) for hit in result.hits] == [("knowledge-1", "song_knowledge")]


async def test_production_vector_adapter_does_not_turn_backend_failure_into_empty_memory():
    store = object.__new__(ChromaVectorStore)
    store._closed = False
    store.logger = logging.getLogger(__name__)
    store._embedding_function = SimpleNamespace(embed_query=lambda query: [1.0])
    with ThreadPoolExecutor(max_workers=1) as executor:
        store._executor = executor
        store.collection = SimpleNamespace(query=lambda **kwargs: {"ids": []})
        assert await store.search("u", "空库") == []

        def fail(**kwargs):
            raise RuntimeError("向量服务不可用")

        store.collection = SimpleNamespace(query=fail)
        with pytest.raises(RuntimeError, match="向量服务不可用"):
            await store.search("u", "查询")


async def test_yesterday_citywalk_reads_exact_character_and_day_without_vector_search(setup, tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from src.agent.skills import memory_retrieval as retrieval_module
    from src.infrastructure.persistence.database.sql_database import Event

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            # UTC 尚为 11 月 2 日，北京已经是 11 月 3 日。
            return cls(2026, 11, 2, 16, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(retrieval_module, "datetime", Clock)
    day = datetime(2026, 11, 2)
    with setup.database.open_sql_session() as session:
        for key, character, when, personal in (
            ("walk", "luotianyi", day + timedelta(hours=12), False),
            ("today", "luotianyi", day + timedelta(days=1), False),
            ("older", "luotianyi", day - timedelta(seconds=1), False),
            ("other-character", "miku", day, False),
            ("private", "luotianyi", day, True),
            ("removed", "luotianyi", day, False),
        ):
            session.add(
                Event(
                    id=key,
                    character=character,
                    event_type="travel",
                    source="world_citywalk",
                    title=key,
                    description=f"{key}：在武康路买了桂花糕。",
                    start_datetime=when,
                    is_personal=personal,
                    target_user_id="other" if personal else None,
                    is_active=key != "removed",
                )
            )
        session.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("昨天漫步指令不应进入向量搜索")

    setup.vectors.search = forbidden
    retrieval, _ = skill(setup, tmp_path)
    result = await retrieval.search(invocation(), query=MemoryQuery(("/YesterdayCityWalk",)))
    assert [hit.memory_record_id for hit in result.hits] == ["walk"]
    assert result.hits[0].source == "citywalk_event"
    assert "桂花糕" in result.render_for_prompt()[0]
    assert "2026-11-02" in result.render_for_prompt()[0]
    # 只有用户记忆权限时不能通过指令读取角色经历。
    result = await retrieval.search(
        invocation(), query=MemoryQuery(("/YesterdayCityWalk",), scopes=frozenset((RetrievalScope.USER,)))
    )
    assert result.hits == ()


async def test_yesterday_citywalk_empty_and_mixed_queries(setup, tmp_path):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from src.infrastructure.persistence.database.sql_database import Event

    retrieval, _ = skill(setup, tmp_path)
    assert (await retrieval.search(invocation(), query=MemoryQuery(("/YesterdayCityWalk",)))).hits == ()
    with setup.database.open_sql_session() as session:
        session.add(
            Event(
                id="walk",
                character="luotianyi",
                event_type="travel",
                source="world_citywalk",
                title="武康路",
                description="看到了梧桐落叶。",
                is_personal=False,
                start_datetime=(datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(days=1)).replace(tzinfo=None),
            )
        )
        session.commit()
    await setup.skill.commit_fact(invocation(), fact=fact(content="喜欢桂花糕"))
    calls = []
    original = setup.vectors.search

    async def search(user_id, query, **kwargs):
        calls.append(query)
        return await original(user_id, query, **kwargs)

    setup.vectors.search = search
    result = await retrieval.search(
        invocation(), query=MemoryQuery(("/YesterdayCityWalk", "桂花糕", "/YesterdayCityWalk"))
    )
    assert len(result.hits) == 2
    assert all(query == "桂花糕" for query in calls)
    assert any("梧桐落叶" in text for text in result.render_for_prompt())
    assert any("桂花糕" in text for text in result.render_for_prompt())


async def test_real_vector_search_reuses_embedding_and_reports_retrieval_details(setup, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from uuid import uuid4

    from src.infrastructure.models.llm.embedding import SiliconFlowEmbeddings
    from src.infrastructure.observability.call_reply_timing import CallReplyTiming, reply_timing_scope

    calls = []

    def embed(self, text):
        calls.append(text)
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(SiliconFlowEmbeddings, "_embed", embed)
    own = await setup.skill.commit_fact(invocation(), fact=fact("own", content="用户喜欢音乐"))
    await setup.skill.commit_fact(invocation("miku"), fact=fact("other", content="其他角色的记忆"))
    store = ChromaVectorStore({"vector_store_path": str(tmp_path / "vectors"), "embedding_model": {"api_key": "test"}})
    store.collection.add(
        ids=list(setup.vectors.documents),
        documents=[d.get_content() for d in setup.vectors.documents.values()],
        metadatas=[d.get_metadata() for d in setup.vectors.documents.values()],
    )
    reader = setup.reader()
    reader.vector_store = store
    rows = []
    timing = CallReplyTiming(
        call_id=uuid4(),
        request_id="retrieval-test",
        turn_seq=1,
        recognized_at=0,
        speech_ended_at=None,
        sink=lambda **row: rows.append(row),
        wall_clock=lambda: datetime.now(timezone.utc),
    )
    calls.clear()
    try:
        with reply_timing_scope(timing):
            result = await reader.search_memory_context_for_topic("u", ["音乐"], similarity_threshold=0)
        assert len(calls) == 1
        assert {h.memory_record_id for h in result.hits} == set(own.memory_ids)
        details = {r["phase"]: r for r in rows if r["phase"].startswith("retrieval.")}
        assert details["retrieval.embedding"]["metadata"]["operation_count"] == 1
        assert details["retrieval.vector_search"]["metadata"]["operation_count"] == 2
        assert details["retrieval.queue"]["metadata"]["operation_count"] == 3
        assert set(details) == {
            "retrieval." + p
            for p in ("authorization", "queue", "embedding", "vector_search", "hydration", "materialization")
        }

        def unavailable(*args, **kwargs):
            raise RuntimeError("向量化失败")

        monkeypatch.setattr(store._embedding_function, "embed_query", unavailable)
        rows.clear()
        with reply_timing_scope(timing), pytest.raises(RuntimeError, match="向量化失败"):
            await reader.search_memory_context_for_topic("u", ["音乐"])
        failed = next(r for r in rows if r["phase"] == "retrieval.embedding")
        assert failed["status"] == "error"
        assert not any(r["phase"] == "retrieval.vector_search" for r in rows)
    finally:
        store.close()
