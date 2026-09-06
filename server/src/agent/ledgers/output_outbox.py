"""完整输出槽位与执行内序号；事务在调用外部接收器前结束。"""
from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select, update

import src.domain.agent as d
from src.agent.planning.identity import plan_fingerprint
from ._output_codec import decode, encode


class OutputStorageError(RuntimeError):
    """输出或执行事实无法持久提交。"""

_metadata = MetaData()
_heads = Table("agent_output_sequences", _metadata,
    Column("character_id", String, primary_key=True), Column("execution_id", String, primary_key=True),
    Column("next_sequence", Integer, nullable=False))
_outputs = Table("agent_output_outbox", _metadata,
    Column("character_id", String, primary_key=True), Column("execution_id", String, primary_key=True),
    Column("sequence_no", Integer, primary_key=True), Column("version", Integer, nullable=False),
    Column("payload_json", Text, nullable=False), Column("fingerprint", String, nullable=False),
    Column("state", String, nullable=False))


@dataclass
class Slot:
    """原输出及持久接收状态。"""
    output: d.AgentOutput
    state: str


class OutputOutbox:
    """为一个角色保存执行的连续完整输出，拒绝损坏历史。"""

    def __init__(self, character_id, sessions):
        self.character_id, self.sessions = character_id, sessions
        with sessions() as session:
            _metadata.create_all(session.get_bind())

    def key(self, table, execution_id):
        return (table.c.character_id == self.character_id) & (table.c.execution_id == execution_id)

    def initialize(self, session, execution_id):
        """与执行首次占用或旧无输出历史升级一起建立序列。"""
        session.execute(insert(_heads).values(character_id=self.character_id,
                                              execution_id=execution_id, next_sequence=0))

    def read(self, session, execution_id, plan, facts):
        """验证完整槽位及逐行动接收标记的一致性，损坏时抛异常。"""
        count = session.execute(select(_heads.c.next_sequence).where(self.key(_heads, execution_id))).scalar_one()
        rows = session.execute(select(_outputs).where(self.key(_outputs, execution_id))
                               .order_by(_outputs.c.sequence_no)).mappings().all()
        if type(count) is not int or count != len(rows):
            raise ValueError("invalid output sequence")
        slots, previous = [], 0
        action_ids = [action.action_id for action in plan.actions]
        for sequence, row in enumerate(rows):
            output = decode(row["payload_json"])
            index = action_ids.index(output.action_id)
            if (row["version"] != 1 or row["sequence_no"] != sequence or output.sequence_no != sequence
                    or output.execution_id != execution_id or output.interaction_id != plan.interaction_id
                    or row["fingerprint"] != plan_fingerprint(row["payload_json"])
                    or row["state"] not in {"PREPARED", "REJECTED", "UNKNOWN", "ACCEPTED"}
                    or index < previous or not facts[index].started
                    or (slots and slots[-1].state != "ACCEPTED")):
                raise ValueError("invalid output history")
            slots.append(Slot(output, row["state"]))
            previous = index
        for action, fact in zip(plan.actions, facts):
            states = {slot.state for slot in slots if slot.output.action_id == action.action_id}
            if fact.confirmed != ("ACCEPTED" in states) or fact.unknown != ("UNKNOWN" in states):
                raise ValueError("inconsistent output facts")
        return slots

    def prepare(self, execution_id, output):
        """原子分配下一槽位并保存完整 payload，失败不消耗序号。"""
        payload = encode(output)
        with self.sessions() as session:
            result = session.execute(update(_heads).where(self.key(_heads, execution_id),
                _heads.c.next_sequence == output.sequence_no).values(next_sequence=output.sequence_no + 1))
            if result.rowcount != 1:
                raise ValueError("output sequence changed")
            session.execute(insert(_outputs).values(character_id=self.character_id, execution_id=execution_id,
                sequence_no=output.sequence_no, version=1, payload_json=payload,
                fingerprint=plan_fingerprint(payload), state="PREPARED"))
            session.commit()
        return Slot(output, "PREPARED")

    def save(self, session, execution_id, slots):
        """在执行事实的同一事务中保存输出接收状态。"""
        for slot in slots:
            result = session.execute(update(_outputs).where(self.key(_outputs, execution_id),
                _outputs.c.sequence_no == slot.output.sequence_no).values(state=slot.state))
            if result.rowcount != 1:
                raise ValueError("output slot missing")
