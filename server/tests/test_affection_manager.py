"""好感度管理器单元测试"""
import sys
from pathlib import Path
from datetime import date, datetime

# Add server root to path
server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import create_engine, Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base

# Create a test Base that mirrors the real ORM models
TestBase = declarative_base()


class TestUser(TestBase):
    __tablename__ = "users"
    uuid = Column(String, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.now)
    last_login = Column(DateTime, nullable=True)
    nickname = Column(String, default="你")
    description = Column(String, default="")
    context_summary = Column(String, default="")
    context_memory_count = Column(Integer, default=0)
    all_memory_count = Column(Integer, default=0)
    auth_token = Column(String, nullable=True)
    preferences = Column(String, default="{}")
    affection_score = Column(Integer, default=0)
    affection_total_gained = Column(Integer, default=0)


class TestAffectionLog(TestBase):
    __tablename__ = "affection_logs"
    uuid = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.uuid"), nullable=False)
    delta = Column(Integer, nullable=False)
    score_after = Column(Integer, nullable=False)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


# Now import the affection manager (must come after chromadb is available)
from src.agent.affection_manager import (
    AffectionManager,
    AFFECTION_LEVELS,
    DAILY_AFFECTION_CAP,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    TestBase.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = TestUser(
        uuid="test-user-001",
        username="testuser",
        affection_score=0,
        affection_total_gained=0,
    )
    session.add(user)
    session.commit()
    yield session
    session.close()


class TestAffectionLevels:
    def test_level_thresholds(self):
        """测试好感度等级阈值"""
        mgr = AffectionManager()
        assert mgr.get_level(0) == ("萍水相逢", "Stranger")
        assert mgr.get_level(50) == ("萍水相逢", "Stranger")
        assert mgr.get_level(100) == ("相识", "Acquaintance")
        assert mgr.get_level(299) == ("相识", "Acquaintance")
        assert mgr.get_level(300) == ("朋友", "Friend")
        assert mgr.get_level(600) == ("挚友", "Close Friend")
        assert mgr.get_level(1000) == ("知己", "Soulmate")
        assert mgr.get_level(1500) == ("羁绊", "Deep Bond")
        assert mgr.get_level(9999) == ("羁绊", "Deep Bond")

    def test_next_level_info(self):
        """测试下一等级信息"""
        mgr = AffectionManager()
        info = mgr.get_next_level_info(0)
        assert info is not None
        assert info[0] == "相识"
        assert info[2] == 100

        info = mgr.get_next_level_info(1500)
        assert info is None  # Max level

        info = mgr.get_next_level_info(50)
        assert info[2] == 50  # 100 - 50


class TestAffectionDB:
    def test_get_score(self, db_session):
        """获取好感度分数"""
        mgr = AffectionManager()
        score = mgr.get_score(db_session, "test-user-001")
        assert score == 0

    def test_get_score_nonexistent(self, db_session):
        """不存在的用户返回0"""
        mgr = AffectionManager()
        score = mgr.get_score(db_session, "nonexistent")
        assert score == 0

    def test_add_affection_positive(self, db_session):
        """增加好感度"""
        mgr = AffectionManager()
        delta, score_after, today = mgr.add_affection(
            db_session, "test-user-001", 3, "测试增加"
        )
        assert delta == 3
        assert score_after == 3
        assert today == 3

        score = mgr.get_score(db_session, "test-user-001")
        assert score == 3

    def test_add_affection_negative(self, db_session):
        """减少好感度（不低于0）"""
        mgr = AffectionManager()
        mgr.add_affection(db_session, "test-user-001", 3, "加好感")
        delta, score_after, today = mgr.add_affection(
            db_session, "test-user-001", -2, "减好感"
        )
        assert delta == -2
        assert score_after == 1

    def test_add_affection_not_below_zero(self, db_session):
        """好感度不会低于0"""
        mgr = AffectionManager()
        delta, score_after, today = mgr.add_affection(
            db_session, "test-user-001", -5, "大幅减少"
        )
        assert delta == -5
        assert score_after == 0

    def test_daily_cap(self, db_session):
        """每日上限"""
        mgr = AffectionManager()
        for i in range(DAILY_AFFECTION_CAP):
            delta, _, _ = mgr.add_affection(db_session, "test-user-001", 1, f"第{i+1}次")
            assert delta == 1

        delta, score_after, today = mgr.add_affection(
            db_session, "test-user-001", 1, "超出上限"
        )
        assert delta == 0
        assert score_after == DAILY_AFFECTION_CAP
        assert today == DAILY_AFFECTION_CAP

    def test_today_net_tracks_abs(self, db_session):
        """today_net 按绝对值计算"""
        mgr = AffectionManager()
        mgr.add_affection(db_session, "test-user-001", 2, "+2")
        mgr.add_affection(db_session, "test-user-001", -1, "-1")
        mgr.add_affection(db_session, "test-user-001", 2, "+2")
        today = mgr.get_today_net(db_session, "test-user-001")
        assert today == 5  # |2| + |-1| + |2|

    def test_affection_context(self, db_session):
        """好感度上下文生成"""
        mgr = AffectionManager()
        mgr.add_affection(db_session, "test-user-001", 5, "初始好感")
        context = mgr.get_affection_context(db_session, "test-user-001")
        assert "5" in context
        assert "萍水相逢" in context
        assert "相识" in context
        assert "95" in context


class TestLLMAnalysis:
    @pytest.mark.asyncio
    async def test_analyze_no_llm(self):
        """无 LLM 客户端时返回默认值"""
        mgr = AffectionManager()
        delta, reason = await mgr.analyze_affection("你好", 0)
        assert delta == 0
        assert reason == "LLM未初始化，不调整"

    @pytest.mark.asyncio
    async def test_analyze_with_mock_llm(self):
        """Mock LLM 分析结果"""
        mgr = AffectionManager()
        mock_client = MagicMock()
        mock_client.generate_response = AsyncMock(return_value='{"delta": 2, "reason": "用户很友好"}')
        mgr._llm_client = mock_client

        delta, reason = await mgr.analyze_affection("今天很开心！", 50)
        assert delta == 2
        assert reason == "用户很友好"

    @pytest.mark.asyncio
    async def test_analyze_llm_clamp_delta(self):
        """delta 被限制在 -3 到 +3"""
        mgr = AffectionManager()
        mock_client = MagicMock()
        mock_client.generate_response = AsyncMock(return_value='{"delta": 10, "reason": "测试超限"}')
        mgr._llm_client = mock_client

        delta, _ = await mgr.analyze_affection("test", 0)
        assert delta == 3

    @pytest.mark.asyncio
    async def test_analyze_llm_invalid_json(self):
        """LLM 返回非法 JSON 时回退"""
        mgr = AffectionManager()
        mock_client = MagicMock()
        mock_client.generate_response = AsyncMock(side_effect=Exception("API error"))
        mgr._llm_client = mock_client

        delta, reason = await mgr.analyze_affection("test", 0)
        assert delta == 0
        assert reason == "分析失败，不调整"
