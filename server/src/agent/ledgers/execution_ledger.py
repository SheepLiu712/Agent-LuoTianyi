"""执行唯一键仲裁与逐行动持久事实；会话事务不跨越业务 await。"""
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.exc import IntegrityError

from src.agent.planning.identity import decode_plan, plan_fingerprint
from ._execution_codec import decode_facts, encode_facts
from .output_outbox import OutputOutbox


_executions = Table(
    "agent_executions", MetaData(),
    Column("character_id", String, primary_key=True),
    Column("execution_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("fingerprint", String, nullable=False),
    Column("plan_json", Text, nullable=False),
    Column("facts_json", Text, nullable=False),
    Column("occupied", Integer, nullable=False),
)


class ExecutionLedger:
    """使用注入 SQL 会话保存执行权、完整计划身份及行动恢复事实。"""

    def __init__(self, character_id, sessions):
        self._character_id, self._sessions = character_id, sessions
        with sessions() as session:
            _executions.create(session.get_bind(), checkfirst=True)
        self.outbox = OutputOutbox(character_id, sessions)

    def _key(self, execution_id):
        return (_executions.c.character_id == self._character_id) & (_executions.c.execution_id == execution_id)

    def read(self, execution_id, payload):
        """读取并验证已有执行；返回 missing、conflict 或 occupied/available 及事实。"""
        with self._sessions() as session:
            row = session.execute(select(_executions).where(self._key(execution_id))).mappings().first()
        if row is None:
            return "missing", None, []
        plan = decode_plan(row["plan_json"])
        if (row["version"] not in (1, 2) or row["occupied"] not in (0, 1)
                or plan.target_character_id != self._character_id
                or plan_fingerprint(row["plan_json"]) != row["fingerprint"]):
            raise ValueError("invalid execution record")
        facts = decode_facts(row["facts_json"], plan)
        if row["plan_json"] != payload:
            return "conflict", None, []
        if row["occupied"]:
            # 在途快照用于加入拥有者，不能拿两次查询之间变化的输出作终态验证。
            return "occupied", facts, []
        with self._sessions() as session:
            slots = self.outbox.read(session, execution_id, plan, facts) if row["version"] == 2 else None
        return "occupied" if row["occupied"] else "available", facts, slots

    def claim(self, execution_id, payload, facts, *, new, legacy=False):
        """仅原子占用未变化且空闲的执行；并发争用失败不接管已有拥有者。"""
        with self._sessions() as session:
            if new:
                try:
                    session.execute(insert(_executions).values(
                        character_id=self._character_id, execution_id=execution_id, version=2,
                        fingerprint=plan_fingerprint(payload), plan_json=payload,
                        facts_json=encode_facts(facts), occupied=1))
                    self.outbox.initialize(session, execution_id)
                    session.commit()
                    return True
                except IntegrityError:
                    session.rollback()
                    return False
            result = session.execute(update(_executions).where(
                self._key(execution_id), _executions.c.occupied == 0,
                _executions.c.plan_json == payload, _executions.c.facts_json == encode_facts(facts),
            ).values(occupied=1, version=2))
            if result.rowcount == 1 and legacy:
                self.outbox.initialize(session, execution_id)
            session.commit()
            return result.rowcount == 1

    def save(self, execution_id, facts, slots):
        """提交开始、输出或可信结算事实；失败向上传播，不降级为内存账本。"""
        with self._sessions() as session:
            result = session.execute(update(_executions).where(
                self._key(execution_id), _executions.c.occupied == 1,
            ).values(facts_json=encode_facts(facts)))
            if result.rowcount != 1:
                raise ValueError("execution ownership lost")
            self.outbox.save(session, execution_id, slots)
            session.commit()

    def release(self, execution_id):
        """拥有者退出时释放运行占用；未知行动仍由持久事实阻止重新执行。"""
        with self._sessions() as session:
            session.execute(update(_executions).where(self._key(execution_id)).values(occupied=0))
            session.commit()
