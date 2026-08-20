import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.system.database.services.memory_store import MemoryStore
from src.system.database.redis_buffer import RedisBuffer
from src.system.database.sql_database import Base, MemoryUpdateRecord


def test_recent_memory_updates_are_loaded_from_sql_on_cold_cache():
    engine = create_engine("sqlite:///:memory:")
    session_factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    started_at = datetime(2026, 8, 1, 12, 0, 0)
    db = session_factory()
    try:
        for index in range(12):
            db.add(
                MemoryUpdateRecord(
                    update_cmd_uuid=f"command-{index:02d}",
                    user_id="user-1",
                    update_command=json.dumps(
                        {
                            "uuid": f"memory-{index}",
                            "content": f"content-{index}",
                            "type": "write_user_memory",
                        }
                    ),
                    created_at=started_at + timedelta(seconds=index),
                )
            )
        db.commit()
    finally:
        db.close()

    redis = RedisBuffer()
    store = MemoryStore({}, session_factory, redis)

    updates = store.get_recent_memory_update_from_buffer("user-1")

    assert [update.uuid for update in updates] == [
        f"memory-{index}" for index in range(2, 12)
    ]
    cached = json.loads(redis.get("user_recent_memory_update:user-1"))
    assert [item["uuid"] for item in cached] == [
        f"memory-{index}" for index in range(2, 12)
    ]
