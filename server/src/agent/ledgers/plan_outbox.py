"""持久计划与恢复领取状态；数据库事务只覆盖本地事实。"""
from dataclasses import dataclass
from contextlib import nullcontext

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, delete, insert, select, update

from src.agent.planning.identity import decode_plan, encode_plan, plan_fingerprint, plan_id
from ._request_codec import decode_report, encode_report

_metadata = MetaData()
_plans = Table("agent_plan_outbox", _metadata,
    Column("character_id", String, primary_key=True), Column("request_id", String, primary_key=True),
    Column("ordinal", Integer, primary_key=True), Column("payload", Text, nullable=False),
    Column("fingerprint", String, nullable=False), Column("state", String, nullable=False),
    Column("outcome", String, nullable=False))
_recoveries = Table("agent_plan_recoveries", _metadata,
    Column("character_id", String, primary_key=True), Column("request_id", String, primary_key=True),
    Column("available", Integer, nullable=False), Column("report_json", Text, nullable=False))


@dataclass
class PlanSlot:
    """本次调用的计划状态副本；confirmed 只来自有效回执或已持久确认。"""
    plan: object
    state: str = "pending"
    outcome: str = "ready"
    confirmed: bool = False


class PlanOutbox:
    """在注入数据库内保存完整计划、接收事实及可恢复报告。"""

    def __init__(self, character_id, sessions):
        self.character_id, self.sessions = character_id, sessions
        with sessions() as session:
            _metadata.create_all(session.get_bind())

    def _key(self, table, request_id):
        return (table.c.character_id == self.character_id) & (table.c.request_id == request_id)

    def load(self, request_id, session=None):
        """读取连续槽位并校验完整值、身份、fingerprint 和状态，损坏时拒绝恢复。"""
        with (self.sessions() if session is None else nullcontext(session)) as session:
            rows = session.execute(select(_plans).where(self._key(_plans, request_id))
                                   .order_by(_plans.c.ordinal)).mappings().all()
        slots = []
        for ordinal, row in enumerate(rows):
            plan = decode_plan(row["payload"])
            if (row["ordinal"] != ordinal or plan.plan_ordinal != ordinal
                    or plan.origin_request_id != request_id or plan.target_character_id != self.character_id
                    or plan.plan_id != plan_id(self.character_id, request_id, ordinal)
                    or plan_fingerprint(row["payload"]) != row["fingerprint"]
                    or row["state"] not in {"pending", "accepted", "rejected"}
                    or row["outcome"] not in {"ready", "unknown", "rejected", "accepted"}
                    or (row["state"] == "accepted") != (row["outcome"] == "accepted")):
                raise ValueError("invalid outbox record")
            slots.append(PlanSlot(plan, row["state"], row["outcome"], row["state"] == "accepted"))
        return slots

    def save(self, slot):
        """先提交完整计划，提交失败不得向接收器交付。"""
        plan = slot.plan
        payload = encode_plan(plan)
        with self.sessions() as session:
            session.execute(insert(_plans).values(character_id=self.character_id,
                request_id=plan.origin_request_id, ordinal=plan.plan_ordinal, payload=payload,
                fingerprint=plan_fingerprint(payload), state=slot.state, outcome=slot.outcome))
            session.commit()

    def mark(self, slot, state, outcome):
        """提交投递状态后才更新内存副本；外部有效回执另由 confirmed 保留。"""
        with self.sessions() as session:
            result = session.execute(update(_plans).where(
                self._key(_plans, slot.plan.origin_request_id), _plans.c.ordinal == slot.plan.plan_ordinal,
                _plans.c.fingerprint == plan_fingerprint(encode_plan(slot.plan)),
            ).values(state=state, outcome=outcome))
            if result.rowcount != 1:
                raise ValueError("missing outbox slot")
            session.commit()
        slot.state, slot.outcome = state, outcome

    def claim(self, request_id):
        """以条件更新领取可信 provisional；其他实例不能并发恢复。"""
        with self.sessions() as session:
            row = session.execute(select(_recoveries).where(self._key(_recoveries, request_id))).mappings().first()
            if row is None:
                return "occupied", None
            report = decode_report(row["report_json"])
            if report.request_id != request_id or row["available"] not in (0, 1):
                raise ValueError("invalid recovery record")
            result = session.execute(update(_recoveries).where(self._key(_recoveries, request_id),
                _recoveries.c.available == 1).values(available=0))
            session.commit()
            return ("recovery", report) if result.rowcount == 1 else ("occupied", None)

    def reconcile(self, session, request_id, confirmed_ids):
        """在报告结算事务中补齐真实回执，返回仍待恢复的计划数。"""
        for slot in self.load(request_id, session):
            if slot.plan.plan_id in confirmed_ids:
                session.execute(update(_plans).where(self._key(_plans, request_id),
                    _plans.c.ordinal == slot.plan.plan_ordinal).values(state="accepted", outcome="accepted"))
        return bool(session.execute(select(_plans.c.ordinal).where(self._key(_plans, request_id),
                    _plans.c.state == "pending")).first())

    def save_recovery(self, session, request_id, report):
        """与报告/确认同事务保存可领取恢复状态，不接管没有报告的认知。"""
        session.execute(delete(_recoveries).where(self._key(_recoveries, request_id)))
        if report is not None:
            session.execute(insert(_recoveries).values(character_id=self.character_id,
                request_id=request_id, available=1, report_json=encode_report(report)))
