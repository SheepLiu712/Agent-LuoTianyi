"""交互上下文测试共用的 SQLite fixture 与领域样例。"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent.context import ContextFactory, ConversationEntry, TextContent
from src.system.database.redis_buffer import RedisBuffer
from src.system.database.services.conversation_service import ConversationService
from src.system.database.services.user_store import UserStore
from src.system.database.sql_database import Base, User


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'context.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add(User(uuid="u", username="user", password="unused", description="画像"))
        session.commit()
    cache = RedisBuffer()
    store = UserStore({}, sessions, cache)
    service = ConversationService(sql_session_factory=sessions, redis_buffer=cache, user_store=store)
    yield service
    engine.dispose()


def factory(database, **kwargs):
    return ContextFactory(character_id="luotianyi", database=database, **kwargs)


def entry(number, content=None):
    return ConversationEntry(
        str(number),
        datetime(2026, 9, 7) + timedelta(seconds=number),
        "user",
        content or TextContent(f"消息{number}", ("关键词",)),
    )
