"""冻结事件提取结果，使部分提交后的重试复用同一组候选。"""

import json

from sqlalchemy.exc import IntegrityError

from src.infrastructure.persistence.database.sql_database import MemoryEventBatch
from src.infrastructure.persistence.database.sql_writer import run_sql_write


class MemoryEventStore:
    def __init__(self, sessions):
        self._sessions = sessions

    def load(self, identity: str, envelope: str) -> tuple[list, str] | None:
        with self._sessions() as session:
            row = session.get(MemoryEventBatch, identity)
            if row is None:
                return None
            expected, persisted = json.loads(envelope), json.loads(row.envelope)
            expected.pop("occurred_at")
            timestamp = persisted.pop("occurred_at")
            if expected != persisted:
                raise ValueError("记忆事件身份与已冻结正文冲突")
            return json.loads(row.candidates), timestamp

    def freeze(self, identity: str, envelope: str, candidates: list, subject_user_id: str | None) -> tuple[list, str]:
        with self._sessions() as session:
            try:

                def write():
                    session.add(
                        MemoryEventBatch(
                            identity=identity,
                            subject_user_id=subject_user_id,
                            envelope=envelope,
                            candidates=json.dumps(candidates, ensure_ascii=False),
                        )
                    )
                    session.commit()

                run_sql_write(write)
            except IntegrityError:
                session.rollback()
        return self.load(identity, envelope)
