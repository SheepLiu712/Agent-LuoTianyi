import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.capabilities.dynamic import DynamicCapability
from src.system.database.database_service import DatabaseManager
from src.system.database.sql_database import InviteCode
from src.system.user_interface.types import (
    DynamicCommentCreateRequest,
    DynamicCommentListRequest,
    DynamicCreateRequest,
    DynamicListRequest,
    DynamicReadMarkRequest,
    DynamicUnreadRequest,
)
from src.system.user_interface.user_interface import UserInterface
from src.world.dynamic_interaction.task import DynamicInteractionTask
from src.world.citywalk.task import CitywalkTask
from src.world.learn_sing_songs.task import LearnSingSongsTask


@pytest.fixture(scope="function")
def db_manager(tmp_path):
    os.environ["JWT_SECRET"] = "test-secret"
    manager = DatabaseManager(
        {
            "sql_db_folder": str(tmp_path / "db"),
            "sql_db_file": "test.db",
        }
    )
    yield manager
    del os.environ["JWT_SECRET"]


def _add_invite_code(db_manager: DatabaseManager, code: str) -> None:
    session = db_manager.open_sql_session()
    session.add(InviteCode(code=code, is_used=False))
    session.commit()
    session.close()


def _register_and_login(db_manager: DatabaseManager, username: str, invite_code: str) -> dict:
    ok, message = db_manager.register_user(username, "password123", invite_code)
    assert ok is True, message
    result = db_manager.authenticate_password_login(username, "password123")
    assert result is not None
    return result


def test_dynamic_visibility_and_comment_isolation(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE1")
    _add_invite_code(db_manager, "INVITE2")
    user1 = _register_and_login(db_manager, "user1", "INVITE1")
    user2 = _register_and_login(db_manager, "user2", "INVITE2")

    ok, _, private_dynamic = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=user1["user_uuid"],
        owner_user_id=user1["user_uuid"],
        visibility="private",
        content="今天过得很充实",
        source_type="user_post",
    )
    assert ok is True
    assert private_dynamic is not None

    user1_feed = db_manager.dynamic_store.list_dynamics_for_user(user1["user_uuid"])
    user2_feed = db_manager.dynamic_store.list_dynamics_for_user(user2["user_uuid"])
    assert [item["id"] for item in user1_feed["items"]] == [private_dynamic["id"]]
    assert user2_feed["items"] == []

    ok, _, public_dynamic = db_manager.dynamic_store.create_dynamic(
        author_type="agent",
        author_id="luotianyi",
        owner_user_id=None,
        visibility="global",
        content="今天去城市里散步啦",
        source_type="citywalk",
        memory_policy="disabled",
        memory_status="disabled",
        reply_status="not_applicable",
    )
    assert ok is True
    assert public_dynamic is not None

    user1_public = db_manager.dynamic_store.list_dynamics_for_user(user1["user_uuid"])
    user2_public = db_manager.dynamic_store.list_dynamics_for_user(user2["user_uuid"])
    assert user1_public["items"][0]["id"] == public_dynamic["id"]
    assert user2_public["items"][0]["id"] == public_dynamic["id"]

    ok, _, comment1 = db_manager.dynamic_store.create_dynamic_comment(
        dynamic_id=public_dynamic["id"],
        author_type="user",
        author_id=user1["user_uuid"],
        owner_user_id=user1["user_uuid"],
        content="我也想去这里",
    )
    assert ok is True
    assert comment1 is not None

    ok, _, user1_comments = db_manager.dynamic_store.list_dynamic_comments_for_user(
        user1["user_uuid"],
        public_dynamic["id"],
    )
    ok2, _, user2_comments = db_manager.dynamic_store.list_dynamic_comments_for_user(
        user2["user_uuid"],
        public_dynamic["id"],
    )
    assert ok is True and ok2 is True
    assert [item["id"] for item in user1_comments["items"]] == [comment1["id"]]
    assert user2_comments["items"] == []


def test_dynamic_unread_status_and_mark_read(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE3")
    user = _register_and_login(db_manager, "reader", "INVITE3")
    user_id = user["user_uuid"]

    initial = db_manager.dynamic_store.get_dynamic_unread_status(user_id)
    assert initial["has_unread"] is False
    assert initial["unread_count"] == 0

    mark_result = db_manager.dynamic_store.mark_dynamic_read(user_id)
    assert mark_result["ok"] is True

    ok, _, public_dynamic = db_manager.dynamic_store.create_dynamic(
        author_type="agent",
        author_id="luotianyi",
        owner_user_id=None,
        visibility="global",
        content="我刚学会一首新歌",
        source_type="song_learned",
        memory_policy="disabled",
        memory_status="disabled",
        reply_status="not_applicable",
    )
    assert ok is True
    unread_after_dynamic = db_manager.dynamic_store.get_dynamic_unread_status(user_id)
    assert unread_after_dynamic["has_unread"] is True
    assert unread_after_dynamic["unread_dynamic_count"] == 1

    mark_result = db_manager.dynamic_store.mark_dynamic_read(user_id)
    assert mark_result["ok"] is True
    unread_after_read = db_manager.dynamic_store.get_dynamic_unread_status(user_id)
    assert unread_after_read["unread_count"] == 0

    ok, _, _ = db_manager.dynamic_store.create_dynamic_comment(
        dynamic_id=public_dynamic["id"],
        author_type="agent",
        author_id="luotianyi",
        owner_user_id=user_id,
        content="这首歌的副歌很抓耳呢",
        memory_policy="disabled",
        memory_status="disabled",
        reply_status="not_applicable",
    )
    assert ok is True
    unread_after_comment = db_manager.dynamic_store.get_dynamic_unread_status(user_id)
    assert unread_after_comment["has_unread"] is True
    assert unread_after_comment["unread_comment_count"] == 1


def test_system_dynamic_skips_memory_and_reply_and_disallows_comments(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE_SYSTEM")
    auth = _register_and_login(db_manager, "systemuser", "INVITE_SYSTEM")

    from src.system.admin.system_dynamic_publisher import publish_system_dynamic

    ok, _, dynamic = publish_system_dynamic(
        database_manager=db_manager,
        content="系统通知：今晚进行一次例行维护。",
        source_type="system_notice",
    )
    assert ok is True
    assert dynamic is not None
    assert dynamic["allow_comment"] is False
    assert dynamic["memory_policy"] == "disabled"
    assert dynamic["memory_status"] == "disabled"
    assert dynamic["reply_status"] == "not_applicable"

    ok, message, comment = db_manager.dynamic_store.create_dynamic_comment(
        dynamic_id=dynamic["id"],
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        content="为什么不能评论？",
    )
    assert ok is False
    assert message == "评论创建失败"
    assert comment is None

    pending_reply = db_manager.dynamic_store.list_pending_dynamic_posts_for_reply()
    pending_memory = db_manager.dynamic_store.list_pending_dynamic_posts_for_memory()
    assert all(item["id"] != dynamic["id"] for item in pending_reply)
    assert all(item["id"] != dynamic["id"] for item in pending_memory)


def test_admin_dynamic_time_filters(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE_TIME")
    auth = _register_and_login(db_manager, "timeuser", "INVITE_TIME")

    ok, _, dynamic = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content="一条需要时间过滤的动态",
        source_type="user_post",
    )
    assert ok is True
    assert dynamic is not None

    ok, _, _ = db_manager.dynamic_store.create_dynamic_comment(
        dynamic_id=dynamic["id"],
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        content="一条需要时间过滤的评论",
    )
    assert ok is True

    session = db_manager.open_sql_session()
    try:
        from src.system.database.sql_database import DynamicComment, DynamicPost

        post_row = session.query(DynamicPost).filter(DynamicPost.id == dynamic["id"]).first()
        comment_row = session.query(DynamicComment).filter(DynamicComment.dynamic_id == dynamic["id"]).first()
        assert post_row is not None
        assert comment_row is not None

        old_post_time = datetime.now() - timedelta(days=3)
        old_comment_time = datetime.now() - timedelta(days=2)
        post_row.created_at = old_post_time
        comment_row.created_at = old_comment_time
        session.commit()
    finally:
        session.close()

    recent_cutoff = datetime.now() - timedelta(hours=12)
    feed = db_manager.dynamic_store.admin_list_dynamics(created_after=recent_cutoff)
    assert feed["items"] == []

    older_cutoff = datetime.now() - timedelta(days=5)
    feed = db_manager.dynamic_store.admin_list_dynamics(created_after=older_cutoff, created_before=datetime.now() - timedelta(days=1))
    assert [item["id"] for item in feed["items"]] == [dynamic["id"]]

    comments = db_manager.dynamic_store.admin_list_dynamic_comments(
        dynamic["id"],
        created_after=datetime.now() - timedelta(days=5),
        created_before=datetime.now() - timedelta(days=1),
    )
    assert len(comments["items"]) == 1


def test_admin_dynamic_list_includes_comment_count(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE_COUNT")
    auth = _register_and_login(db_manager, "countuser", "INVITE_COUNT")

    ok, _, dynamic = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content="评论统计动态",
        source_type="user_post",
    )
    assert ok is True
    assert dynamic is not None

    ok, _, _ = db_manager.dynamic_store.create_dynamic_comment(
        dynamic_id=dynamic["id"],
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        content="第一条评论",
    )
    assert ok is True

    ok, _, _ = db_manager.dynamic_store.create_dynamic_comment(
        dynamic_id=dynamic["id"],
        author_type="agent",
        author_id="luotianyi",
        owner_user_id=auth["user_uuid"],
        content="第二条评论",
        memory_policy="disabled",
        memory_status="disabled",
        reply_status="not_applicable",
    )
    assert ok is True

    feed = db_manager.dynamic_store.admin_list_dynamics(owner_user_id=auth["user_uuid"])
    matched = next(item for item in feed["items"] if item["id"] == dynamic["id"])
    assert matched["comment_count"] == 2


def test_user_interface_dynamic_flow(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE4")
    auth = _register_and_login(db_manager, "uiuser", "INVITE4")
    ui = UserInterface(db_manager)
    runtime = SimpleNamespace(database_manager=db_manager)

    created = asyncio.run(
        ui.create_dynamic(
            DynamicCreateRequest(
                username="uiuser",
                token=auth["message_token"],
                content="这是一条给天依看的动态",
            ),
            runtime,
        )
    )
    dynamic_id = created["item"]["id"]

    listed = asyncio.run(
        ui.list_dynamics(
            DynamicListRequest(
                username="uiuser",
                token=auth["message_token"],
                limit=20,
            ),
            runtime,
        )
    )
    assert listed["items"][0]["id"] == dynamic_id

    commented = asyncio.run(
        ui.create_dynamic_comment(
            dynamic_id,
            DynamicCommentCreateRequest(
                username="uiuser",
                token=auth["message_token"],
                content="补充一句",
            ),
            runtime,
        )
    )
    comment_id = commented["item"]["id"]

    comments = asyncio.run(
        ui.list_dynamic_comments(
            dynamic_id,
            DynamicCommentListRequest(
                username="uiuser",
                token=auth["message_token"],
                limit=50,
            ),
            runtime,
        )
    )
    assert comments["items"][0]["id"] == comment_id

    unread = asyncio.run(
        ui.get_dynamic_unread(
            DynamicUnreadRequest(username="uiuser", token=auth["message_token"]),
            runtime,
        )
    )
    assert unread["has_unread"] is False

    marked = asyncio.run(
        ui.mark_dynamic_read(
            DynamicReadMarkRequest(username="uiuser", token=auth["message_token"]),
            runtime,
        )
    )
    assert marked["ok"] is True


def test_user_interface_dynamic_rejects_bad_token(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE_BAD_TOKEN")
    _register_and_login(db_manager, "badtokenuser", "INVITE_BAD_TOKEN")
    ui = UserInterface(db_manager)
    runtime = SimpleNamespace(database_manager=db_manager)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            ui.list_dynamics(
                DynamicListRequest(
                    username="badtokenuser",
                    token="bad-token",
                    limit=20,
                ),
                runtime,
            )
        )
    assert exc_info.value.status_code == 401


def test_citywalk_task_publishes_global_dynamic(db_manager: DatabaseManager, tmp_path: Path):
    _add_invite_code(db_manager, "INVITE5")
    user = _register_and_login(db_manager, "cityuser", "INVITE5")

    dynamic_capability = DynamicCapability()
    dynamic_capability.wire_dependencies(database_manager=db_manager)

    report_path = tmp_path / "citywalk_20260704_120000.json"
    report_path.write_text(
        '{"overview": {"city": "上海", "selected_destination": "武康路"}, "diary_text": "今天慢慢走了很多路，也看了不少风景。"}',
        encoding="utf-8",
    )

    class FakeCitywalkService:
        def run_once(self) -> str:
            return str(report_path)

    class FakeEventStore:
        async def add_event(self, payload):
            return payload

    class FakeDynamicComposer:
        """只 mock generate_world_dynamic_content，保留 publish_agent_dynamic 的真实写入。"""
        async def generate_world_dynamic_content(self, **kwargs):
            return "今天在上海的武康路散步，风很舒服。"

    task = CitywalkTask({"daily_run_probability": 1.0})
    task.system_runtime = SimpleNamespace(
        capability_manager=SimpleNamespace(dynamics=FakeDynamicComposer()),
    )
    task.database_manager = db_manager
    task.event_store = FakeEventStore()
    task.dynamic_capability = dynamic_capability  # 用真实的 DynamicCapability 来写 DB
    task.citywalk_service = FakeCitywalkService()

    result = task.run_once()
    assert result.ok is True
    assert result.data["dynamic_id"]

    feed = db_manager.dynamic_store.list_dynamics_for_user(user["user_uuid"])
    assert feed["items"][0]["source_type"] == "citywalk"
    assert feed["items"][0]["content"]  # 内容不为空


def test_learn_song_task_publishes_global_dynamic(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE6")
    user = _register_and_login(db_manager, "songuser", "INVITE6")

    dynamic_capability = DynamicCapability()
    dynamic_capability.wire_dependencies(database_manager=db_manager)

    class FakeLearner:
        def check_qq_credential(self):
            return True

        def try_learn_pending(self):
            return SimpleNamespace(learned=["告死鸟"], abandoned=[], awaiting=[])

    class FakeEventStore:
        async def add_event(self, payload):
            return payload

    class FakeSinging:
        def reload_songs(self, character_id: str):
            return character_id

    class FakeDynamicComposer:
        """只 mock generate_world_dynamic_content，保留 publish_agent_dynamic 的真实写入。"""
        async def generate_world_dynamic_content(self, **kwargs):
            return "今天学会了《告死鸟》，下次可以唱给你听。"

    task = LearnSingSongsTask({}, character_id="luotianyi", singing_manager=None)
    task.system_runtime = SimpleNamespace(
        capability_manager=SimpleNamespace(
            dynamics=FakeDynamicComposer(),
            singing=FakeSinging(),
        ),
    )
    task.event_store = FakeEventStore()
    task.dynamic_capability = dynamic_capability  # 用真实的 DynamicCapability 来写 DB
    task.auto_song_learner = FakeLearner()

    result = task.run_once()
    assert result.ok is True
    assert result.data["dynamic_ids"]

    feed = db_manager.dynamic_store.list_dynamics_for_user(user["user_uuid"])
    assert feed["items"][0]["source_type"] == "song_learned"
    assert feed["items"][0]["content"]  # 内容不为空


def test_dynamic_interaction_task_replies_and_updates_status(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE7")
    auth = _register_and_login(db_manager, "replyuser", "INVITE7")

    ok, _, created = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content="今天其实有点紧张，不过也算坚持下来了。",
        source_type="user_post",
    )
    assert ok is True
    dynamic_id = created["id"]

    dynamic_capability = DynamicCapability()
    dynamic_capability.wire_dependencies(database_manager=db_manager)

    class FakeReplier:
        def ensure_llm(self) -> bool:
            return True

        async def generate_reply_for_post(self, item):
            return "我看到你很努力地撑过来了，辛苦啦。"

        async def generate_reply_for_comment(self, item):
            return {"should_reply": False, "reply": ""}

    class FakeAgentRuntime:
        async def write_topic_memories(self, **kwargs):
            return {"payload": {"user_memory": [], "event_memory": []}, "items": []}

    task = DynamicInteractionTask({})
    task.system_runtime = SimpleNamespace()
    task.database_manager = db_manager
    task.dynamic_capability = dynamic_capability
    task.dynamic_capability.replier = FakeReplier()
    task.agent_runtime = FakeAgentRuntime()

    result = asyncio.run(task.run_once())
    assert result.ok is True
    assert result.data["reply_replied"] == 1

    feed = db_manager.dynamic_store.list_dynamics_for_user(auth["user_uuid"])
    target = next(item for item in feed["items"] if item["id"] == dynamic_id)
    assert target["reply_status"] == "replied"
    ok, _, comments = db_manager.dynamic_store.list_dynamic_comments_for_user(auth["user_uuid"], dynamic_id)
    assert ok is True
    assert comments["items"][0]["author_type"] == "agent"
    assert "辛苦" in comments["items"][0]["content"]


def test_dynamic_interaction_task_processes_memory_status(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE8")
    auth = _register_and_login(db_manager, "memoryuser", "INVITE8")

    ok, _, created = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content="我最近开始重新练吉他了。",
        source_type="user_post",
    )
    assert ok is True
    dynamic_id = created["id"]

    dynamic_capability = DynamicCapability()
    dynamic_capability.wire_dependencies(database_manager=db_manager)

    class FakeReplier:
        def ensure_llm(self) -> bool:
            return True

        async def generate_reply_for_post(self, item):
            return "我看到你很努力地撑过来了，辛苦啦。"

        async def generate_reply_for_comment(self, item):
            return {"should_reply": False, "reply": ""}

    class FakeAgentRuntime:
        async def write_topic_memories(self, **kwargs):
            return {
                "payload": {"user_memory": ["用户最近重新开始练吉他"], "event_memory": []},
                "items": [
                    {
                        "memory_type": "user_memory",
                        "content": "用户最近重新开始练吉他",
                        "status": "written",
                    }
                ],
            }

    task = DynamicInteractionTask({})
    task.system_runtime = SimpleNamespace()
    task.database_manager = db_manager
    task.dynamic_capability = dynamic_capability
    task.dynamic_capability.replier = FakeReplier()
    task.agent_runtime = FakeAgentRuntime()

    result = asyncio.run(task.run_once())
    assert result.ok is True
    assert result.data["memory_written"] == 1

    feed = db_manager.dynamic_store.list_dynamics_for_user(auth["user_uuid"])
    target = next(item for item in feed["items"] if item["id"] == dynamic_id)
    assert target["memory_status"] == "written"
