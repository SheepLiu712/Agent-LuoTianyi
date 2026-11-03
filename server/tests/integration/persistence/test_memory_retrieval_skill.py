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
    with ThreadPoolExecutor(max_workers=1) as executor:
        store._executor = executor
        store.collection = SimpleNamespace(query=lambda **kwargs: {"ids": []})
        assert await store.search("u", "空库") == []

        def fail(**kwargs):
            raise RuntimeError("向量服务不可用")

        store.collection = SimpleNamespace(query=fail)
        with pytest.raises(RuntimeError, match="向量服务不可用"):
            await store.search("u", "查询")
