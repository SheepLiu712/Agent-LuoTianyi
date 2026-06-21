import asyncio
import os
import sys

import pytest

current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.system.database.database_service import write_agent_memory_record
from src.system.database.sql_database import Base, get_sql_session, init_sql_db
from src.domain import MemoryRecord, MemoryType, MemoryVisibility
from src.subconscious.music_knowledge.jargon import SongEntityLinker
from src.subconscious.memory import SubconsciousMemory
from src.subconscious.memory_update import MemoryUpdateService


class FakeVectorDoc:
    def __init__(self, content, metadata=None, id=None):
        self.content = content
        self.metadata = metadata or {"user_id": "user-1"}
        self.id = id

    def get_content(self):
        return self.content

    def get_metadata(self):
        return self.metadata


class FakeVectorStore:
    async def search(self, user_id, query, k=5):
        return [(FakeVectorDoc("legacy chunk", id="vec-1"), 0.94)]


@pytest.fixture()
def temp_memory_db(tmp_path):
    init_sql_db(db_folder=str(tmp_path), db_file="subconscious_memory.db")
    session = get_sql_session()
    Base.metadata.drop_all(bind=session.get_bind())
    Base.metadata.create_all(bind=session.get_bind())
    yield session
    session.close()


def test_song_entity_linker_lives_in_subconscious_and_extracts_triggered_song(tmp_path):
    song_file = tmp_path / "songs.txt"
    lyric_file = tmp_path / "lyrics.txt"
    song_file.write_text("纯蓝\n", encoding="utf-8")
    lyric_file.write_text("为了你唱下去\n", encoding="utf-8")

    linker = SongEntityLinker(str(song_file), str(lyric_file))

    assert linker.extract_and_verify("可以唱纯蓝吗") == ["《纯蓝》是一首歌"]
    assert linker.extract_and_verify("我想起纯蓝") == []
    assert linker.extract_and_verify("为了你唱下去") == ["为了你唱下去"]


class FakeSubconsciousMemory:
    def __init__(self):
        self.calls = []

    async def write_user_memory(self, **kwargs):
        self.calls.append(("write_user_memory", kwargs))
        return True

    async def write_event_memory(self, **kwargs):
        self.calls.append(("write_event_memory", kwargs))
        return True

    async def post_process_interaction(self, **kwargs):
        self.calls.append(("post_process_interaction", kwargs))

    async def update_user_profile_by_context(self, **kwargs):
        self.calls.append(("update_user_profile_by_context", kwargs))
        return "updated"


def test_memory_update_service_is_single_mutation_entrypoint():
    memory = FakeSubconsciousMemory()
    service = MemoryUpdateService(memory)

    async def run():
        assert await service.write_user_memory(
            db="db",
            redis="redis",
            vector_store="vector",
            user_id="u1",
            content="用户喜欢蓝色。",
        )
        assert await service.write_event_memory(
            db="db",
            redis="redis",
            vector_store="vector",
            user_id="u1",
            content="今天聊了音乐。",
        )
        await service.post_process_interaction(
            db="db",
            redis="redis",
            vector_store="vector",
            user_id="u1",
            history="history",
        )
        result = await service.update_user_profile_by_context(
            db="db",
            redis="redis",
            user_id="u1",
            context={"summary": "hello"},
        )
        assert result == "updated"

    asyncio.run(run())
    assert [name for name, _ in memory.calls] == [
        "write_user_memory",
        "write_event_memory",
        "post_process_interaction",
        "update_user_profile_by_context",
    ]


def test_subconscious_memory_returns_typed_context_from_canonical_record(temp_memory_db):
    record = MemoryRecord(
        owner_character_id="luotianyi",
        subject_user_id="user-1",
        memory_type=MemoryType.USER_FACT,
        visibility=MemoryVisibility.PRIVATE,
        source="chat",
        content="user likes blue",
    )
    write_agent_memory_record(
        temp_memory_db,
        record,
        embedding_ids=["vec-1"],
        commit=True,
    )

    memory = SubconsciousMemory.__new__(SubconsciousMemory)

    async def run():
        return await memory.search_memory_context_for_topic(
            db=temp_memory_db,
            vector_store=FakeVectorStore(),
            user_id="user-1",
            queries=["blue"],
            similarity_threshold=0.8,
            k=3,
        )

    context = asyncio.run(run())
    assert len(context.hits) == 1
    assert context.hits[0].record is not None
    assert context.hits[0].memory_record_id == record.id
    assert context.hits[0].memory_type == MemoryType.USER_FACT
    assert context.render_for_prompt() == [context.hits[0].rendered_text]
