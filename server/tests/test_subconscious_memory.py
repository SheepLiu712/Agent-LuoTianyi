import json
import os
import sys
from pathlib import Path

import pytest

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.domain.memory_record import MemoryRecord, MemoryType, MemoryVisibility
from src.subconscious.memory import SubconsciousMemory
from src.system.database.database_service import DatabaseManager
from src.system.database.vector_store import Document
from src.utils.helpers import load_config
from src.utils.llm_service import LLMService


USER_ID = "memory-test-user"
CHARACTER_ID = "luotianyi"


class FakeLLMModule:
    """按测试输入返回固定响应的 LLMModule 替身。"""

    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responder(kwargs) if callable(self.responder) else self.responder
        if isinstance(response, (dict, list)):
            return json.dumps(response, ensure_ascii=False)
        return str(response)


class InMemoryVectorStore:
    """测试用向量库，记录写入文档并按关键字返回候选。"""

    def __init__(self):
        self.documents = []
        self.next_id = 1

    def add_seed_document(self, content, metadata, doc_id):
        self.documents.append(Document(content, metadata, id=doc_id))

    def add_documents(self, documents):
        ids = []
        for doc in documents:
            doc_id = f"vec-{self.next_id}"
            self.next_id += 1
            stored = Document(doc.get_content(), dict(doc.get_metadata()), id=doc_id)
            self.documents.append(stored)
            ids.append(doc_id)
        return ids

    async def search(self, user_id, query, k=5, **kwargs):
        hits = []
        normalized_query = (query or "").strip()
        for doc in self.documents:
            metadata = doc.get_metadata()
            if metadata.get("user_id") != user_id:
                continue
            content = doc.get_content()
            score = 0.95 if normalized_query and normalized_query in content else 0.2
            hits.append((doc, score))
        hits.sort(key=lambda item: item[1], reverse=True)
        return hits[:k]

    def delete_documents(self, doc_ids):
        self.documents = [doc for doc in self.documents if doc.id not in set(doc_ids)]
        return True

    def update_document(self, doc_id, document):
        for index, doc in enumerate(self.documents):
            if doc.id == doc_id:
                self.documents[index] = Document(document.get_content(), dict(document.get_metadata()), id=doc_id)
                return True
        return False

    def get_document_by_id(self, doc_ids):
        wanted = set(doc_ids)
        return [doc for doc in self.documents if doc.id in wanted]

    def delete_user_records(self, user_id):
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.get_metadata().get("user_id") != user_id]
        return before - len(self.documents)


class FakeMemoryStore:
    """测试用 MemoryStore，记录记忆更新和规范记忆正本。"""

    def __init__(self):
        self.updates = []
        self.records = []
        self.embedding_to_record = {}

    def write_memory_update(self, user_id, memory_update, commit=True):
        self.updates.append((user_id, memory_update, commit))

    def write_agent_memory_record(self, memory_record, *, chunk_texts=None, embedding_ids=None, commit=True):
        self.records.append((memory_record, list(embedding_ids or []), commit))
        for embedding_id in embedding_ids or []:
            self.embedding_to_record[embedding_id] = memory_record
        return memory_record.id

    def get_agent_memory_records_by_embedding_ids(self, embedding_ids):
        return {
            embedding_id: self.embedding_to_record[embedding_id]
            for embedding_id in embedding_ids
            if embedding_id in self.embedding_to_record
        }


class FakeDatabaseManager:
    """测试用 DatabaseManager，只暴露 SubconsciousMemory 需要的接口。"""

    def __init__(self):
        self.memory_store = FakeMemoryStore()
        self.descriptions = {}
        self.description_updates = []

    def get_user_description(self, user_id):
        return self.descriptions.get(user_id, "")

    def update_user_description(self, user_id, new_description, commit=True):
        self.descriptions[user_id] = new_description
        self.description_updates.append((user_id, new_description, commit))


@pytest.fixture(scope="module", autouse=True)
def server_cwd():
    old_cwd = os.getcwd()
    os.chdir(server_root)
    try:
        yield
    finally:
        os.chdir(old_cwd)


@pytest.fixture
def memory_config():
    return {
        "memory_writer": {
            "user_memory_dedup_threshold": 0.72,
        },
        "user_profile": {},
    }


@pytest.fixture
def fake_llm_modules():
    return {
        "memory_writer": FakeLLMModule({"user_memory": [], "event_memory": []}),
        "user_profile_updater": FakeLLMModule("no_update"),
    }


@pytest.fixture
def fake_database_manager():
    return FakeDatabaseManager()


@pytest.fixture
def fake_vector_store():
    return InMemoryVectorStore()


@pytest.fixture
def fake_memory(memory_config, fake_llm_modules, fake_database_manager, fake_vector_store):
    return SubconsciousMemory(
        memory_config,
        fake_llm_modules,
        database_manager=fake_database_manager,
        vector_store=fake_vector_store,
        owner_character_id=CHARACTER_ID,
    )


@pytest.fixture
def real_database_manager(tmp_path):
    return DatabaseManager(
        {
            "sql_db_folder": str(tmp_path / "db"),
            "sql_db_file": "memory.db",
            "memory_store": {},
        }
    )


@pytest.fixture
def real_llm_modules(request):
    if not (request.config.getoption("--run-real-llm") or os.getenv("RUN_REAL_LLM_TESTS") == "1"):
        pytest.skip("真实 LLM 测试默认跳过")

    config = load_config("config/config.json")
    llm_service = LLMService(config["llm_service"])
    memory_cfg = config["agent_runtime"]["agent"]["memory"]
    return {
        "memory_writer": llm_service.register_llm_module(
            "test_memory_writer",
            memory_cfg["memory_writer"]["llm_module"],
        ),
        "user_profile_updater": llm_service.register_llm_module(
            "test_user_profile_updater",
            memory_cfg["user_profile"]["llm_module"],
        ),
    }


@pytest.mark.asyncio
async def test_search_memory_context_reads_canonical_record_from_real_database(
    memory_config,
    fake_llm_modules,
    real_database_manager,
):
    """从真实 MemoryStore/SQLite 正本中回查向量命中的规范记忆。"""
    vector_store = InMemoryVectorStore()
    embedding_id = "embedding-real-db-1"
    vector_store.add_seed_document(
        "用户喜欢薄荷巧克力",
        {"user_id": USER_ID, "timestamp": "2026-06-27", "memory_type": "user_memory"},
        embedding_id,
    )
    real_database_manager.memory_store.write_agent_memory_record(
        MemoryRecord(
            owner_character_id=CHARACTER_ID,
            subject_user_id=USER_ID,
            memory_type=MemoryType.USER_FACT,
            visibility=MemoryVisibility.PRIVATE,
            source="chat",
            content="用户喜欢薄荷巧克力",
            summary="用户喜欢薄荷巧克力。",
        ),
        embedding_ids=[embedding_id],
    )
    memory = SubconsciousMemory(
        memory_config,
        fake_llm_modules,
        database_manager=real_database_manager,
        vector_store=vector_store,
        owner_character_id=CHARACTER_ID,
    )

    context = await memory.search_memory_context_for_topic(
        USER_ID,
        ["薄荷巧克力"],
        similarity_threshold=0.8,
        k=3,
    )

    assert len(context.hits) == 1
    hit = context.hits[0]
    assert hit.source == "canonical_vector"
    assert hit.vector_id == embedding_id
    assert hit.record is not None
    assert hit.record.memory_type == MemoryType.USER_FACT
    assert hit.record.content == "用户喜欢薄荷巧克力"
    assert "薄荷巧克力" in hit.rendered_text
    assert context.render_for_prompt() == [hit.rendered_text]


@pytest.mark.asyncio
async def test_write_user_and_event_memory_records_vector_and_canonical_rows(fake_memory, fake_database_manager, fake_vector_store):
    """直接写入用户记忆和事件记忆，并验证向量与正本都被写入。"""
    user_written = await fake_memory.write_user_memory(USER_ID, "用户喜欢喝乌龙茶")
    event_written = await fake_memory.write_event_memory(USER_ID, "今天一起聊了演唱会")

    assert user_written is True
    assert event_written is True
    assert [doc.get_metadata()["memory_type"] for doc in fake_vector_store.documents] == [
        "user_memory",
        "event_memory",
    ]

    records = [item[0] for item in fake_database_manager.memory_store.records]
    assert [record.memory_type for record in records] == [
        MemoryType.USER_FACT,
        MemoryType.INTERACTION_EVENT,
    ]
    assert records[0].content == "用户喜欢喝乌龙茶"
    assert records[1].content == "今天一起聊了演唱会"
    assert len(fake_database_manager.memory_store.updates) == 2
    assert fake_database_manager.memory_store.updates[0][1].type == "write_user_memory"
    assert fake_database_manager.memory_store.updates[1][1].type == "write_event_memory"


@pytest.mark.asyncio
async def test_direct_memory_write_skips_empty_and_duplicate_content(fake_memory, fake_database_manager):
    """直接写入会跳过空文本、相似用户记忆和同日重复事件。"""
    assert await fake_memory.write_user_memory(USER_ID, "") is False
    assert await fake_memory.write_user_memory(USER_ID, "用户喜欢蓝莓蛋糕") is True
    assert await fake_memory.write_user_memory(USER_ID, "用户喜欢蓝莓蛋糕") is False

    assert await fake_memory.write_event_memory(USER_ID, "今天讨论了星空摄影") is True
    assert await fake_memory.write_event_memory(USER_ID, "今天讨论了星空摄影") is False

    records = [item[0] for item in fake_database_manager.memory_store.records]
    assert [record.content for record in records] == [
        "用户喜欢蓝莓蛋糕",
        "今天讨论了星空摄影",
    ]


@pytest.mark.asyncio
async def test_write_topic_memories_with_fake_llm_writes_when_context_has_memory(
    memory_config,
    fake_database_manager,
    fake_vector_store,
):
    """伪装 LLM：上下文包含可记忆信息时，应生成并写入记忆请求。"""

    def memory_responder(kwargs):
        dialogue = kwargs["current_dialogue"]
        if "喜欢观星" in dialogue:
            return {
                "user_memory": ["用户喜欢观星"],
                "event_memory": ["用户和天依聊了夏夜观星计划"],
            }
        return {"user_memory": [], "event_memory": []}

    llm_modules = {
        "memory_writer": FakeLLMModule(memory_responder),
        "user_profile_updater": FakeLLMModule("no_update"),
    }
    memory = SubconsciousMemory(
        memory_config,
        llm_modules,
        database_manager=fake_database_manager,
        vector_store=fake_vector_store,
        owner_character_id=CHARACTER_ID,
    )

    await memory.write_topic_memories(
        USER_ID,
        history="用户：我喜欢观星\n天依：那下次一起看星星吧",
        current_dialogue="用户说自己喜欢观星",
        related_memories=["用户以前提到喜欢夜晚散步"],
    )

    assert llm_modules["memory_writer"].calls[0]["related_memories"] == ["用户以前提到喜欢夜晚散步"]
    records = [item[0] for item in fake_database_manager.memory_store.records]
    assert [record.content for record in records] == [
        "用户喜欢观星",
        "用户和天依聊了夏夜观星计划",
    ]
    assert [record.memory_type for record in records] == [
        MemoryType.USER_FACT,
        MemoryType.INTERACTION_EVENT,
    ]


@pytest.mark.asyncio
async def test_write_topic_memories_with_fake_llm_does_not_write_without_memory(
    memory_config,
    fake_database_manager,
    fake_vector_store,
):
    """伪装 LLM：上下文没有可记忆信息时，不应产生向量或正本写入。"""
    llm_modules = {
        "memory_writer": FakeLLMModule({"user_memory": [], "event_memory": []}),
        "user_profile_updater": FakeLLMModule("no_update"),
    }
    memory = SubconsciousMemory(
        memory_config,
        llm_modules,
        database_manager=fake_database_manager,
        vector_store=fake_vector_store,
        owner_character_id=CHARACTER_ID,
    )

    await memory.write_topic_memories(
        USER_ID,
        history="用户：你好\n天依：你好呀",
        current_dialogue="普通寒暄，没有稳定事实",
    )

    assert llm_modules["memory_writer"].calls
    assert fake_vector_store.documents == []
    assert fake_database_manager.memory_store.records == []


@pytest.mark.asyncio
async def test_update_user_profile_with_fake_llm_updates_when_context_has_memory(memory_config, fake_database_manager, fake_vector_store):
    """伪装 LLM：长期上下文包含画像变化时，应更新用户画像。"""

    def profile_responder(kwargs):
        history = kwargs["history"]
        if "观星" in history:
            return "用户喜欢观星，也喜欢安静的夜晚活动。"
        return "no_update"

    llm_modules = {
        "memory_writer": FakeLLMModule({"user_memory": [], "event_memory": []}),
        "user_profile_updater": FakeLLMModule(profile_responder),
    }
    memory = SubconsciousMemory(
        memory_config,
        llm_modules,
        database_manager=fake_database_manager,
        vector_store=fake_vector_store,
        owner_character_id=CHARACTER_ID,
    )

    new_profile = await memory.update_user_profile_by_context(
        USER_ID,
        {"summary": "用户多次提到观星。", "recent_conversation": ["用户：今晚适合看星星"]},
    )

    assert new_profile == "用户喜欢观星，也喜欢安静的夜晚活动。"
    assert fake_database_manager.get_user_description(USER_ID) == new_profile
    assert fake_database_manager.description_updates == [(USER_ID, new_profile, True)]


@pytest.mark.asyncio
async def test_update_user_profile_with_fake_llm_keeps_profile_without_memory(memory_config, fake_database_manager, fake_vector_store):
    """伪装 LLM：长期上下文没有画像变化时，不应写入用户画像。"""
    fake_database_manager.descriptions[USER_ID] = "用户喜欢音乐。"
    llm_modules = {
        "memory_writer": FakeLLMModule({"user_memory": [], "event_memory": []}),
        "user_profile_updater": FakeLLMModule("no_update"),
    }
    memory = SubconsciousMemory(
        memory_config,
        llm_modules,
        database_manager=fake_database_manager,
        vector_store=fake_vector_store,
        owner_character_id=CHARACTER_ID,
    )

    new_profile = await memory.update_user_profile_by_context(
        USER_ID,
        {"summary": "普通寒暄。", "recent_conversation": ["用户：你好"]},
    )

    assert new_profile is None
    assert fake_database_manager.get_user_description(USER_ID) == "用户喜欢音乐。"
    assert fake_database_manager.description_updates == []


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_write_topic_memories_with_real_llm_optional(memory_config, real_llm_modules, fake_database_manager, fake_vector_store):
    """真实 LLM：明显事实应能触发记忆写入；默认跳过。"""
    memory = SubconsciousMemory(
        memory_config,
        real_llm_modules,
        database_manager=fake_database_manager,
        vector_store=fake_vector_store,
        owner_character_id=CHARACTER_ID,
    )

    await memory.write_topic_memories(
        USER_ID,
        history="用户：我最喜欢薄荷巧克力，也喜欢周末去天文馆。\n天依：我记住啦。",
        current_dialogue="用户明确表达了长期偏好：喜欢薄荷巧克力和天文馆。",
    )
    written_count = len(fake_database_manager.memory_store.records)

    await memory.write_topic_memories(
        USER_ID,
        history="用户：你好\n天依：你好呀",
        current_dialogue="普通寒暄，没有稳定偏好或事件。",
    )

    assert written_count >= 1
    assert len(fake_database_manager.memory_store.records) == written_count


@pytest.mark.real_llm
@pytest.mark.asyncio
async def test_update_user_profile_with_real_llm_optional(memory_config, real_llm_modules, fake_database_manager, fake_vector_store):
    """真实 LLM：明显长期上下文应能更新画像；默认跳过。"""
    memory = SubconsciousMemory(
        memory_config,
        real_llm_modules,
        database_manager=fake_database_manager,
        vector_store=fake_vector_store,
        owner_character_id=CHARACTER_ID,
    )

    new_profile = await memory.update_user_profile_by_context(
        USER_ID,
        {
            "summary": "用户反复提到喜欢薄荷巧克力和天文馆。",
            "recent_conversation": ["用户：我周末又去了天文馆，顺便买了薄荷巧克力。"],
        },
    )
    assert new_profile
    assert fake_database_manager.get_user_description(USER_ID) == new_profile

    fake_database_manager.description_updates.clear()
    no_update = await memory.update_user_profile_by_context(
        USER_ID,
        {"summary": "普通寒暄。", "recent_conversation": ["用户：你好"]},
    )
    assert no_update is None
    assert fake_database_manager.description_updates == []
