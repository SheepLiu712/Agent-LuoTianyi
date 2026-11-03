"""统一动态与日记接口的真实存储、权限及生成提交分离。"""

import asyncio
import json
import threading
from datetime import date, datetime

import pytest
from support.skill_support import invocation

import src.domain.agent as d
from src.agent.skills.contracts import CharacterNarrative
from src.agent.skills.expression.diary import DiarySkill
from src.agent.skills.expression.dynamic import (
    DynamicDraft, DynamicGenerationError, DynamicPublication, DynamicSkill, DynamicTarget,
    DynamicWritingRequest, ReplyPublication,
)
from src.infrastructure.persistence.database import DatabaseManager
from src.infrastructure.persistence.database.sql_database import Conversation, DynamicComment, DynamicPost, User


class Models:
    def __init__(self):
        self.calls = []
        self.error = None
        self.reply = {"should_reply": True, "reply": "角色回复"}

    def register_llm_module(self, name, config):
        models = self
        class Module:
            async def generate_response(self, **kwargs):
                models.calls.append((name, kwargs))
                if models.error:
                    raise models.error
                if name.endswith("generate_reply"):
                    return json.dumps(models.reply, ensure_ascii=False)
                if name.endswith("diary"):
                    return "心情：开心\n\n正文：今天一起聊了音乐。"
                return "今天的见闻让我很开心。"
        return Module()


@pytest.fixture
def setup(tmp_path):
    database = DatabaseManager({"sql_db_folder": str(tmp_path), "sql_db_file": "dynamic.sqlite"})
    with database.open_sql_session() as session:
        session.add_all([User(uuid="user-1", username="甲", password="hash"), User(uuid="user-2", username="乙", password="hash")])
        session.commit()
    models = Models()
    config = {key: {"llm_module": {"llm": {"name": "test"}}}
              for key in ("dynamic_composer", "dynamic_replier", "diary_composer")}
    dynamic = DynamicSkill(config, llm_service=models, database=database, narratives={
        key: CharacterNarrative(name=key, persona=f"{key}的人设", speaking_style="自然")
        for key in ("luotianyi", "miku")
    })
    yield database, models, dynamic, DiarySkill({}, dynamic=dynamic, database=database)
    asyncio.run(database.shutdown())


def user_post(database, *, private=False):
    ok, _, item = database.dynamic_store.create_dynamic(
        author_type="user", author_id="user-1", owner_user_id="user-1", content="原帖正文",
        visibility="private" if private else "global",
    )
    assert ok
    return item["id"]


async def test_generate_is_read_only_and_publishing_same_source_does_not_regenerate(setup):
    database, models, dynamic, _ = setup
    caller = invocation(user_id=None)
    draft = await dynamic.generate(caller, request=DynamicWritingRequest("citywalk", "表达见闻", "公园散步"))
    with database.open_sql_session() as session:
        assert session.query(DynamicPost).count() == session.query(DynamicComment).count() == 0
    publication = DynamicPublication(d.DynamicSource(source_type="citywalk", source_id="walk-1"), d.Visibility.GLOBAL, None)
    first = await dynamic.publish(caller, draft=draft, publication=publication)
    second = await dynamic.publish(caller, draft=DynamicDraft("同一来源的新草稿"), publication=publication)
    assert first.identifier == second.identifier
    assert first.created and not second.created
    assert len(models.calls) == 1


async def test_cancelled_publication_finishes_owned_write_and_retry_uses_same_record(setup):
    database, _, dynamic, _ = setup
    started, release = threading.Event(), threading.Event()
    original = database.dynamic_store.create_dynamic
    def blocked(**kwargs):
        started.set()
        assert release.wait(2)
        return original(**kwargs)
    database.dynamic_store.create_dynamic = blocked
    caller = invocation(user_id=None)
    publication = DynamicPublication(d.DynamicSource(source_type="citywalk", source_id="cancelled-write"), d.Visibility.GLOBAL, None)
    writing = asyncio.create_task(dynamic.publish(caller, draft=DynamicDraft("见闻"), publication=publication))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        writing.cancel()
        await asyncio.sleep(0)
        assert not writing.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await writing
    retry = await dynamic.publish(caller, draft=DynamicDraft("见闻"), publication=publication)
    assert not retry.created
    with database.open_sql_session() as session:
        assert session.query(DynamicPost).count() == 1


async def test_post_and_comment_targets_and_repeated_reply_keep_stable_identity(setup):
    database, models, dynamic, _ = setup
    caller = invocation(user_id="user-1")
    post = user_post(database)
    thread = await dynamic.read_thread(caller, target=DynamicTarget(post))
    decision = await dynamic.generate_reply(caller, thread=thread, target_id=post)
    assert decision.draft.parent_comment_id is None
    with database.open_sql_session() as session:
        assert session.query(DynamicComment).count() == 0
    publication = ReplyPublication(f"reply:{post}")
    first = await dynamic.publish_reply(caller, draft=decision.draft, publication=publication)
    repeated = await dynamic.publish_reply(caller, draft=decision.draft, publication=publication)
    assert first.identifier == repeated.identifier
    assert not repeated.created
    thread = await dynamic.read_thread(caller, target=DynamicTarget(post))
    assert (await dynamic.generate_reply(caller, thread=thread, target_id=post)).reason == "already_replied"
    ok, _, comment = database.dynamic_store.create_dynamic_comment(
        dynamic_id=post, author_type="user", author_id="user-1", owner_user_id="user-1", content="评论补充",
    )
    assert ok
    thread = await dynamic.read_thread(caller, target=DynamicTarget(post))
    decision = await dynamic.generate_reply(caller, thread=thread, target_id=comment["id"])
    assert decision.draft.parent_comment_id == comment["id"]
    models.reply = {"should_reply": False, "reply": ""}
    assert (await dynamic.generate_reply(caller, thread=thread, target_id=comment["id"])).reason == "no_reply_intent"
    models.error = RuntimeError("模型不可用")
    with pytest.raises(DynamicGenerationError):
        await dynamic.generate_reply(caller, thread=thread, target_id=comment["id"])


async def test_current_user_can_publish_role_reply_on_another_users_public_post(setup):
    database, _, dynamic, _ = setup
    post = user_post(database)
    caller = invocation(user_id="user-2")
    thread = await dynamic.read_thread(caller, target=DynamicTarget(post))
    decision = await dynamic.generate_reply(caller, thread=thread, target_id=post)
    assert decision.draft.owner_user_id == "user-2"
    receipt = await dynamic.publish_reply(caller, draft=decision.draft, publication=ReplyPublication("public-reply"))
    with database.open_sql_session() as session:
        assert session.get(DynamicComment, receipt.identifier).owner_user_id == "user-2"


async def test_private_thread_and_diary_materials_are_scoped_by_user_role_and_date(setup):
    database, models, dynamic, diary = setup
    private = user_post(database, private=True)
    with pytest.raises(PermissionError):
        await dynamic.read_thread(invocation(user_id="user-2"), target=DynamicTarget(private))
    with database.open_sql_session() as session:
        for user, role, day, text in (("user-1", "luotianyi", 3, "应当使用的材料"),
                                      ("user-1", "miku", 3, "其他角色材料"),
                                      ("user-2", "luotianyi", 3, "其他用户材料"),
                                      ("user-1", "luotianyi", 2, "其他日期材料")):
            session.add(Conversation(user_id=user, character_id=role, timestamp=datetime(2026, 11, day, 12),
                                     source="user", type="text", content=text))
        session.commit()
    caller = invocation(user_id="user-1")
    draft = await diary.generate(caller, local_date=date(2026, 11, 3))
    material = models.calls[-1][1]["conversation_materials"]
    assert "应当使用的材料" in material
    assert not any(text in material for text in ("其他角色材料", "其他用户材料", "其他日期材料"))
    calls = len(models.calls)
    first = await diary.publish(caller, draft=draft)
    second = await diary.publish(caller, draft=draft)
    assert first.identifier == second.identifier and not second.created
    assert len(models.calls) == calls
    with database.open_sql_session() as session:
        post = session.get(DynamicPost, first.identifier)
        assert post.visibility == "private" and not post.allow_comment
        assert post.source_id == "diary:luotianyi:user-1:2026-11-03"
    with pytest.raises(PermissionError):
        await dynamic.read_thread(invocation(user_id="user-2"), target=DynamicTarget(first.identifier))
    with pytest.raises(PermissionError):
        await dynamic.read_thread(invocation("miku", user_id="user-1"), target=DynamicTarget(first.identifier))
