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


def test_dynamic_capability_accepts_nested_module_config_and_degrades_on_invalid_llm():
    registered = []

    class FakeLLMService:
        llm_interfaces = {}

        def register_llm_module(self, name, config):
            registered.append((name, config))
            if name == "dynamic_composer":
                return SimpleNamespace(module_name=name)
            raise ValueError("reply llm unavailable")

    capability = DynamicCapability(
        {
            "dynamic_composer": {
                "llm_module": {
                    "llm": {"name": "qwen3.5-plus"},
                    "prompt_name": "dynamic_post_prompt",
                }
            },
            "dynamic_replier": {
                "llm_module": {
                    "llm": {"name": "qwen3.6-flash"},
                    "prompt_name": "dynamic_reply_prompt",
                }
            },
        }
    )

    capability.create_llm_module(FakeLLMService())

    assert registered[0] == (
        "dynamic_composer",
        {
            "llm": {"name": "qwen3.5-plus"},
            "prompt_name": "dynamic_post_prompt",
        },
    )
    assert registered[1][0] == "dynamic_reply"

    bad_capability = DynamicCapability(
        {
            "dynamic_composer": {
                "llm_module": {
                    "llm": {"name": ""},
                    "prompt_name": "dynamic_post_prompt",
                }
            }
        }
    )

    class RejectingLLMService:
        llm_interfaces = {}

        def register_llm_module(self, name, config):
            raise ValueError("LLM接口未找到")

    bad_capability.create_llm_module(RejectingLLMService())
    assert bad_capability._dynamic_composer is None


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
    ok, message = db_manager.credential_service.register_user(username, "password123", invite_code)
    assert ok is True, message
    result = db_manager.credential_service.authenticate_password_login(username, "password123")
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


def test_admin_create_system_dynamic_endpoint(db_manager: DatabaseManager, monkeypatch):
    from src.system.admin import admin_interface

    shell = SimpleNamespace(
        runtime_supervisor=SimpleNamespace(
            runtime=SimpleNamespace(database_manager=db_manager),
        )
    )
    monkeypatch.setattr(admin_interface, "get_admin_shell", lambda: shell)

    result = asyncio.run(
        admin_interface.admin_create_system_dynamic(
            {
                "content": "系统通知：动态功能已更新。",
                "source_type": "system_notice",
                "source_id": "notice-001",
            }
        )
    )

    assert result["ok"] is True
    item = result["item"]
    assert item["author_type"] == "system"
    assert item["author_id"] == "system"
    assert item["visibility"] == "global"
    assert item["source_type"] == "system_notice"
    assert item["source_id"] == "notice-001"
    assert item["allow_comment"] is False
    assert item["memory_policy"] == "disabled"
    assert item["reply_status"] == "not_applicable"


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


def test_admin_dynamic_list_filters_diary_source_type(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE_DIARY_FILTER")
    auth = _register_and_login(db_manager, "diaryfilteruser", "INVITE_DIARY_FILTER")

    ok, _, diary = db_manager.dynamic_store.create_dynamic(
        author_type="agent",
        author_id="luotianyi",
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content="2026-08-20\n今天和你聊了很多。",
        source_type="diary",
        source_id="diary:luotianyi:test-user:2026-08-20",
        memory_policy="disabled",
        memory_status="disabled",
        reply_status="not_applicable",
    )
    assert ok is True
    assert diary is not None

    ok, _, _ = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content="普通动态",
        source_type="user_post",
    )
    assert ok is True

    feed = db_manager.dynamic_store.admin_list_dynamics(source_type="diary")

    assert [item["id"] for item in feed["items"]] == [diary["id"]]
    assert feed["items"][0]["source_type"] == "diary"
    assert feed["items"][0]["content"] == "2026-08-20\n今天和你聊了很多。"


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










def test_dynamic_pending_reply_items_include_thread_comments(db_manager: DatabaseManager):
    _add_invite_code(db_manager, "INVITE_THREAD")
    auth = _register_and_login(db_manager, "threaduser", "INVITE_THREAD")

    db_manager.conversation_service.save_user_preferences(auth["user_uuid"], {"relationship": "朋友"})
    db_manager.conversation_service.update_user_description(auth["user_uuid"], "用户最近在记录自己的日常状态。")
    ok, _, created = db_manager.dynamic_store.create_dynamic(
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        visibility="private",
        content="今天路过海边，风很大。",
        source_type="user_post",
    )
    assert ok is True
    dynamic_id = created["id"]
    db_manager.dynamic_store.create_dynamic_comment(
        dynamic_id=dynamic_id,
        author_type="agent",
        author_id="luotianyi",
        owner_user_id=auth["user_uuid"],
        content="听起来像一次很有画面的散步。",
        memory_policy="disabled",
        memory_status="disabled",
        reply_status="not_applicable",
    )
    ok, _, user_comment = db_manager.dynamic_store.create_dynamic_comment(
        dynamic_id=dynamic_id,
        author_type="user",
        author_id=auth["user_uuid"],
        owner_user_id=auth["user_uuid"],
        content="嗯，而且我想起了以前去海边的事。",
    )
    assert ok is True

    pending_posts = db_manager.dynamic_store.list_pending_dynamic_posts_for_reply()
    post_item = next(item for item in pending_posts if item["id"] == dynamic_id)
    assert post_item["user_description"] == "用户最近在记录自己的日常状态。"
    assert post_item["preferences"] == {"relationship": "朋友"}
    assert [item["content"] for item in post_item["thread_comments"]] == [
        "听起来像一次很有画面的散步。",
        "嗯，而且我想起了以前去海边的事。",
    ]

    pending_comments = db_manager.dynamic_store.list_pending_dynamic_comments_for_reply()
    comment_item = next(item for item in pending_comments if item["id"] == user_comment["id"])
    assert comment_item["dynamic"]["content"] == "今天路过海边，风很大。"
    assert [item["content"] for item in comment_item["thread_comments"]] == [
        "听起来像一次很有画面的散步。",
        "嗯，而且我想起了以前去海边的事。",
    ]


def test_dynamic_replier_passes_thread_comments_to_llm():
    captured = {}
    dynamic_capability = DynamicCapability()

    class FakeLLM:
        async def generate_response(self, **kwargs):
            captured.update(kwargs)
            return '{"should_reply": true, "reply": "我看到前面也聊到了海边的风。"}'

    dynamic_capability.replier._reply_llm = FakeLLM()
    item = {
        "author_type": "user",
        "author_name": "Dpon",
        "username": "Dpon",
        "user_description": "用户喜欢散步。",
        "preferences": {"relationship": "朋友"},
        "content": "今天去了海边。",
        "thread_comments": [
            {"author_type": "agent", "author_name": "天依", "content": "海边听起来很舒服。", "created_at": "2026-07-06 10:00:00"},
            {"author_type": "user", "author_name": "Dpon", "content": "但是风很大。", "created_at": "2026-07-06 10:01:00"},
        ],
    }

    reply = asyncio.run(dynamic_capability.replier.generate_reply_for_post(item, character_name="洛天依"))

    assert "海边的风" in reply
    assert "海边听起来很舒服" in captured["message_list"]
    assert "但是风很大" in captured["message_list"]
    assert "发布者类型：用户" in captured["message_list"]
    assert "发布者类型：角色" in captured["message_list"]
    assert "发布者：天依" in captured["message_list"]
    assert "消息 1" in captured["target_message"]


def test_dynamic_replier_targets_comment_in_sender_labeled_message_list():
    captured = {}
    dynamic_capability = DynamicCapability()

    class FakeLLM:
        async def generate_response(self, **kwargs):
            captured.update(kwargs)
            return '{"should_reply": true, "reply": "我看到你的补充啦。"}'

    dynamic_capability.replier._reply_llm = FakeLLM()
    item = {
        "id": "comment-user-2",
        "author_type": "user",
        "author_name": "Dpon",
        "username": "Dpon",
        "content": "我也想去看看。",
        "dynamic": {
            "id": "dynamic-agent-1",
            "author_type": "agent",
            "author_name": "洛天依",
            "content": "今天去海边散步啦。",
        },
        "thread_comments": [
            {
                "id": "comment-agent-1",
                "author_type": "agent",
                "author_name": "洛天依",
                "content": "海风吹起来很舒服呢。",
            },
            {
                "id": "comment-user-2",
                "author_type": "user",
                "author_name": "Dpon",
                "content": "我也想去看看。",
            },
        ],
    }

    decision = asyncio.run(dynamic_capability.replier.generate_reply_for_comment(item, character_name="洛天依"))

    assert decision == {"should_reply": True, "reply": "我看到你的补充啦。"}
    message_list = captured["message_list"]
    assert "发布者类型：角色" in message_list
    assert "发布者类型：用户" in message_list
    assert "发布者：洛天依" in message_list
    assert "发布者：Dpon" in message_list
    assert "内容：今天去海边散步啦" in message_list
    assert "内容：我也想去看看" in captured["target_message"]
    assert "消息 3" in captured["target_message"]
