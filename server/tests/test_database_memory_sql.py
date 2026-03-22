import os
import sys
import threading
import time
import unittest
from datetime import datetime


current_dir = os.getcwd()
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.database.memory_storage import MemoryStorage
from src.database.redis_buffer import init_redis_buffer, get_redis_buffer
from src.database.sql_database import init_sql_db, get_sql_session, Base, User, Conversation
from src.database.database_service import add_conversations
from src.database.sql_writer import run_sql_write
from src.types import ConversationItem


class TestMemoryStorage(unittest.TestCase):
    def setUp(self):
        self.storage = MemoryStorage()

    def test_memory_storage_basic(self):
        self.storage.setex("user_context:u1", 3600, "ctx")
        self.assertEqual(self.storage.get("user_context:u1"), "ctx")

        self.storage.delete("user_context:u1")
        self.assertIsNone(self.storage.get("user_context:u1"))

    def test_same_user_lock_blocks_concurrent_access(self):
        started = threading.Event()
        reader_finished = threading.Event()
        elapsed = {"value": 0.0}

        def holder():
            with self.storage.user_guard("u1"):
                started.set()
                time.sleep(0.25)

        def reader():
            started.wait(timeout=2)
            begin = time.perf_counter()
            _ = self.storage.get("user_context:u1")
            elapsed["value"] = time.perf_counter() - begin
            reader_finished.set()

        t1 = threading.Thread(target=holder)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=2)
        t2.join(timeout=2)

        self.assertTrue(reader_finished.is_set())
        # 同一用户锁应导致 reader 至少等待大部分持锁时间。
        self.assertGreater(elapsed["value"], 0.18)

    def test_different_users_can_run_in_parallel(self):
        barrier = threading.Barrier(2)

        def hold_user(uid: str):
            with self.storage.user_guard(uid):
                barrier.wait(timeout=2)
                time.sleep(0.2)

        start = time.perf_counter()
        t1 = threading.Thread(target=hold_user, args=("u1",))
        t2 = threading.Thread(target=hold_user, args=("u2",))
        t1.start()
        t2.start()
        t1.join(timeout=2)
        t2.join(timeout=2)
        duration = time.perf_counter() - start

        # 如果是串行，耗时会接近 0.4s；并行应显著小于该值。
        self.assertLess(duration, 0.33)


class TestSqlWriter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_folder = os.path.join(current_dir, "data", "database")
        os.makedirs(db_folder, exist_ok=True)
        init_sql_db(db_folder=db_folder, db_file="test_memory_sql_writer.db")
        init_redis_buffer({})

    def setUp(self):
        session = get_sql_session()
        Base.metadata.drop_all(bind=session.get_bind())
        Base.metadata.create_all(bind=session.get_bind())
        session.close()

        s = get_sql_session()
        user = User(username="writer_user", password="pwd")
        s.add(user)
        s.commit()
        self.user_id = user.uuid
        s.close()

    def test_sql_writer_basic(self):
        result = run_sql_write(lambda: "ok")
        self.assertEqual(result, "ok")

    def test_multithread_add_conversations_no_conflict(self):
        storage = get_redis_buffer()
        errors = []

        def worker(i: int):
            try:
                session = get_sql_session()
                item = ConversationItem(
                    uuid="",
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    source="user",
                    type="text",
                    content=f"msg-{i}",
                    data=None,
                )
                ids = add_conversations(session, storage, self.user_id, [item], commit=True)
                if not ids:
                    errors.append(f"empty ids for {i}")
                session.close()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertEqual(errors, [])

        check = get_sql_session()
        count = check.query(Conversation).filter(Conversation.user_id == self.user_id).count()
        check.close()
        self.assertEqual(count, 20)


if __name__ == "__main__":
    unittest.main()
