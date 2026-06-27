"""DatabaseManager 单元测试(不包含Event Store和Memory Store)"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目根目录
server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import pytest

from src.system.database.sql_database import (
    init_sql_db, Base, User, InviteCode
)
from src.system.database.redis_buffer import init_redis_buffer
from src.system.database.database_service import DatabaseManager, _hash_password
from src.domain import ConversationItem


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="function")
def db_manager(tmp_path):
    """为每个测试创建一个完全隔离的 DatabaseManager"""
    # 1. 设置 JWT_SECRET（message token 需要）
    os.environ["JWT_SECRET"] = "test-secret"


    # 2. 创建 DatabaseManager 实例
    manager = DatabaseManager({
        "sql_db_folder": str(tmp_path / "db"),
        "sql_db_file": "test.db",
    })
    yield manager

    # teardown：清理环境变量
    del os.environ["JWT_SECRET"]


@pytest.fixture
def sample_user(db_manager: "DatabaseManager") -> str:
    """预置一个测试用户"""
    session = db_manager.open_sql_session()
    user = User(
        uuid="test-uuid-001",
        username="testuser",
        password=_hash_password("password123")  # 需要暴露或直接调模块函数
    )
    session.add(user)
    session.commit()
    session.close()
    return "testuser"

@pytest.fixture
def sample_invite_code(db_manager: "DatabaseManager") -> str:
    """预置一个测试邀请码"""
    session = db_manager.open_sql_session()
    code = InviteCode(code="TESTCODE123", is_used=False)
    session.add(code)
    session.commit()
    session.close()
    return "TESTCODE123"

@pytest.fixture
def sample_invite_code_2(db_manager: "DatabaseManager") -> str:
    """预置另一个测试邀请码"""
    session = db_manager.open_sql_session()
    code = InviteCode(code="TESTCODE456", is_used=False)
    session.add(code)
    session.commit()
    session.close()
    return "TESTCODE456"


# ═══════════════════════════════════════════════════════════════
# 测试注册 & 登录
# ═══════════════════════════════════════════════════════════════

class TestRegistration:
    def test_register_success(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """正常注册"""
        ok, msg = db_manager.register_user("newuser", "pass123", sample_invite_code)
        assert ok is True
        assert msg == "注册成功"

    def test_register_duplicate_username(self, db_manager: "DatabaseManager", sample_invite_code: str, sample_invite_code_2: str):
        """重复用户名"""

        ok1, _ = db_manager.register_user("dupe", "pass1", sample_invite_code)
        assert ok1 is True
        ok2, msg2 = db_manager.register_user("dupe", "pass2", sample_invite_code_2)
        assert ok2 is False

    def test_register_bad_invite_code(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """无效邀请码"""
        ok, msg = db_manager.register_user("someone", "pass", "NOEXIST")
        assert ok is False

    def test_used_invite_code(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """邀请码已被使用"""
        ok1, _ = db_manager.register_user("user1", "pass1", sample_invite_code)
        assert ok1 is True
        ok2, msg2 = db_manager.register_user("user2", "pass2", sample_invite_code)
        assert ok2 is False

    def test_used_username(self, db_manager: "DatabaseManager", sample_invite_code: str, sample_invite_code_2: str):
        """用户名已被使用"""
        ok1, _ = db_manager.register_user("unique_user", "pass1", sample_invite_code)
        assert ok1 is True
        ok2, msg2 = db_manager.register_user("unique_user", "pass2", sample_invite_code_2)
        assert ok2 is False


class TestAuthentication:
    def test_verify_user(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """验证用户成功"""
        db_manager.register_user("authuser", "mypassword", sample_invite_code)
        success = db_manager.verify_user("authuser", "mypassword")
        assert success is True

        success = db_manager.verify_user("authuser", "wrongpassword")
        assert success is False

    def test_authenticate_password_login_success(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """密码登录成功"""
        db_manager.register_user("authuser", "mypassword", sample_invite_code)
        result = db_manager.authenticate_password_login("authuser", "mypassword")
        assert result is not None
        assert result["user_uuid"] is not None
        assert result["login_token"] is not None
        assert result["message_token"] is not None
        assert "elapsed_from_last_login" in result

    def test_authenticate_password_login_wrong_password(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """密码登录失败"""
        db_manager.register_user("authuser", "mypassword", sample_invite_code)
        result = db_manager.authenticate_password_login("authuser", "wrongpassword")
        assert result is None
        """密码错误"""
        result = db_manager.authenticate_password_login("user1", "wrongpass")
        assert result is None

    def test_auto_login(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """自动登录成功"""
        db_manager.register_user("autouser", "pass123", sample_invite_code)
        auth_result = db_manager.authenticate_password_login("autouser", "pass123")
        assert auth_result is not None
        login_token = auth_result["login_token"]
        auto_login_result = db_manager.authenticate_auto_login("autouser", login_token)
        assert auto_login_result is not None
        assert auto_login_result["user_uuid"] is not None
        assert auto_login_result["message_token"] is not None

        auto_login_result_invalid = db_manager.authenticate_auto_login("autouser", "invalidtoken")
        assert auto_login_result_invalid is None

    def test_reset_account(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """重置账号"""
        db_manager.register_user("resetuser", "pass123", sample_invite_code)
        auth_result = db_manager.authenticate_password_login("resetuser", "pass123")
        assert auth_result is not None

        reset_result, result_str = db_manager.reset_account(sample_invite_code, "resetuser", "newpass456")
        assert reset_result is True
        assert result_str == "重置成功"

        # 重置后，登录应该失败
        auth_result_after_reset = db_manager.authenticate_password_login("resetuser", "pass123")
        assert auth_result_after_reset is None

        auth_result_new_pass = db_manager.authenticate_password_login("resetuser", "newpass456")
        assert auth_result_new_pass is not None

    def test_reset_account_invalid_invite_code(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """重置账号失败 - 无效邀请码"""
        db_manager.register_user("resetuser", "pass123", sample_invite_code)
        reset_result, result_str = db_manager.reset_account("INVALIDCODE", "resetuser", "newpass456")
        assert reset_result is False
        assert result_str == "邀请码无效"

    def test_update_login_time(self, db_manager: "DatabaseManager", sample_invite_code: str):
        """更新登录时间"""
        db_manager.register_user("timeuser", "pass123", sample_invite_code)
        auth_result = db_manager.authenticate_password_login("timeuser", "pass123")
        assert auth_result is not None
        login_time = auth_result["elapsed_from_last_login"]
        assert login_time is None # 首次登录，应该为 None

        import time
        time.sleep(1)  # 等待一秒钟
        auth_result2 = db_manager.authenticate_password_login("timeuser", "pass123")
        assert auth_result2 is not None
        login_time2 = auth_result2["elapsed_from_last_login"]
        assert login_time2 > 0.7 and login_time2 < 2.0  # 应该大约为 1 秒


# ═══════════════════════════════════════════════════════════════
# 测试对话
# ═══════════════════════════════════════════════════════════════

class TestConversations:
    def test_add_and_retrieve(self, db_manager: "DatabaseManager", sample_user: str):
        """添加对话并检索"""
        user_uuid = db_manager.get_user_uuid_by_username(sample_user)
        items = [
            ConversationItem(
                timestamp="2026-06-22 10:00:00",
                source="user",
                content="你好",
                type="text",
                uuid="conv-001",
            ),
            ConversationItem(
                timestamp="2026-06-22 10:01:00",
                source="agent",
                content="你好呀！",
                type="text",
                uuid="conv-002",
            ),
        ]
        uuids = db_manager.add_conversations(user_uuid, items)
        assert len(uuids) == 2

        # 从 DB 检索
        history = db_manager.get_history_from_db(user_uuid, 0, 10)
        assert len(history) == 2
        assert history[0].content == "你好"
        assert history[1].content == "你好呀！"

    def test_context_state_and_compaction(self, db_manager: "DatabaseManager", sample_user: str):
        """运行时上下文状态和压缩接口"""
        user_uuid = db_manager.get_user_uuid_by_username(sample_user)
        items = [
            ConversationItem(
                timestamp="2026-06-22 10:00:00",
                source="user",
                content="第一句",
                type="text",
                uuid="conv-context-001",
            ),
            ConversationItem(
                timestamp="2026-06-22 10:01:00",
                source="agent",
                content="第二句",
                type="text",
                uuid="conv-context-002",
            ),
            ConversationItem(
                timestamp="2026-06-22 10:02:00",
                source="agent",
                content="（唱了《测试歌》）",
                type="sing",
                uuid="conv-context-003",
                data={"song": "测试歌", "segment": "hook"},
            ),
        ]
        db_manager.add_conversations(user_uuid, items)

        state = db_manager.get_conversation_context_state(user_uuid)
        assert state["summary"] == ""
        assert state["context_count"] == 3
        assert len(state["conversations"]) == 3

        ok = db_manager.compact_conversation_context(
            user_uuid,
            "较早内容摘要",
            keep_recent_count=1,
            expected_context_count=3,
        )
        assert ok is True

        compacted_state = db_manager.get_conversation_context_state(user_uuid)
        assert compacted_state["summary"] == "较早内容摘要"
        assert compacted_state["context_count"] == 1
        assert len(compacted_state["conversations"]) == 1
        assert compacted_state["conversations"][0]["content"] == "（唱了《测试歌》）"

        stale_ok = db_manager.compact_conversation_context(
            user_uuid,
            "不应写入",
            keep_recent_count=1,
            expected_context_count=3,
        )
        assert stale_ok is False

        history = db_manager.get_history_from_db(user_uuid, 0, 10)
        assert history[2].data == {"song": "测试歌", "segment": "hook"}

    def test_context_is_scoped_by_character(self, db_manager: "DatabaseManager", sample_user: str):
        """同一用户的不同角色聊天流应使用独立上下文。"""
        user_uuid = db_manager.get_user_uuid_by_username(sample_user)
        db_manager.add_conversations(
            user_uuid,
            [
                ConversationItem(
                    timestamp="2026-06-22 11:00:00",
                    source="user",
                    content="给天依的消息",
                    type="text",
                    uuid="conv-lty-001",
                )
            ],
            character_id="luotianyi",
        )
        db_manager.add_conversations(
            user_uuid,
            [
                ConversationItem(
                    timestamp="2026-06-22 11:01:00",
                    source="user",
                    content="给另一个角色的消息",
                    type="text",
                    uuid="conv-other-001",
                )
            ],
            character_id="other_character",
        )

        lty_state = db_manager.get_conversation_context_state(user_uuid, character_id="luotianyi")
        other_state = db_manager.get_conversation_context_state(user_uuid, character_id="other_character")

        assert lty_state["context_count"] == 1
        assert other_state["context_count"] == 1
        assert lty_state["conversations"][0]["content"] == "给天依的消息"
        assert other_state["conversations"][0]["content"] == "给另一个角色的消息"

        ok = db_manager.compact_conversation_context(
            user_uuid,
            "另一个角色的摘要",
            keep_recent_count=0,
            expected_context_count=1,
            character_id="other_character",
        )
        assert ok is True

        lty_state_after = db_manager.get_conversation_context_state(user_uuid, character_id="luotianyi")
        other_state_after = db_manager.get_conversation_context_state(user_uuid, character_id="other_character")

        assert lty_state_after["summary"] == ""
        assert lty_state_after["context_count"] == 1
        assert other_state_after["summary"] == "另一个角色的摘要"
        assert other_state_after["context_count"] == 0

    def test_stale_context_returns_empty_context(self, db_manager: "DatabaseManager", sample_user: str):
        """最近一条消息超过阈值时，运行上下文应清空但历史记录保留。"""
        user_uuid = db_manager.get_user_uuid_by_username(sample_user)
        old_timestamp = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d %H:%M:%S")
        db_manager.add_conversations(
            user_uuid,
            [
                ConversationItem(
                    timestamp=old_timestamp,
                    source="user",
                    content="六天前的对话",
                    type="text",
                    uuid="conv-stale-001",
                )
            ],
            character_id="luotianyi",
        )

        fresh_without_threshold = db_manager.get_conversation_context_state(user_uuid, character_id="luotianyi")
        assert fresh_without_threshold["context_count"] == 1
        assert fresh_without_threshold["conversations"][0]["content"] == "六天前的对话"

        cleared = db_manager.reset_conversation_context_if_stale(
            user_uuid,
            character_id="luotianyi",
            max_context_age_days=5,
        )
        assert cleared is True

        stale_state = db_manager.get_conversation_context_state(user_uuid, character_id="luotianyi")
        assert stale_state["summary"] == ""
        assert stale_state["context_count"] == 0
        assert stale_state["conversations"] == []

        history = db_manager.get_history_from_db(user_uuid, 0, 10, character_id="luotianyi")
        assert len(history) == 1
        assert history[0].content == "六天前的对话"


# # ═══════════════════════════════════════════════════════════════
# # 测试 Redis 缓存
# # ═══════════════════════════════════════════════════════════════

# class TestRedisCache:
#     def test_nickname_cache(self, db_manager):
#         """昵称缓存写入和读取"""
#         from src.system.database.sql_database import get_sql_session
#         session = get_sql_session()
#         user = User(uuid="cache-user", username="cacheuser",
#                      password="hash", nickname="小明")
#         session.add(user)
#         session.commit()
#         session.close()

#         # 从 DB prefill 到 Redis
#         ok = db_manager.prefill_buffer("cache-user", types=["nickname"])
#         assert ok is True

#         nickname = db_manager.get_user_nickname("cache-user")
#         assert nickname == "小明"

#     def test_prefill_buffer_full(self, db_manager):
#         """完整 prefill"""
#         from src.system.database.sql_database import get_sql_session
#         session = get_sql_session()
#         user = User(
#             uuid="full-user", username="fulluser",
#             password="hash", nickname="小红",
#             context_summary="之前的对话摘要",
#             context_memory_count=2,
#         )
#         session.add(user)
#         session.add(Conversation(
#             user_id="full-user", timestamp=datetime.now(),
#             source="user", type="text", content="历史消息1"
#         ))
#         session.add(Conversation(
#             user_id="full-user", timestamp=datetime.now(),
#             source="agent", type="text", content="历史回复1"
#         ))
#         session.commit()
#         session.close()

#         ok = db_manager.prefill_buffer("full-user")
#         assert ok is True

#         context = db_manager.get_context_from_buffer("full-user")
#         assert "之前的对话摘要" in context["summary"]
#         assert len(context["conversations"]) == 2
