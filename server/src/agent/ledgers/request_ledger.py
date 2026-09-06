"""由数据库唯一键仲裁处理权；不明占用一律保留，不自动接管。"""
from collections.abc import Callable
import re

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ._request_codec import decode_report, encode_report
from .plan_outbox import PlanOutbox


_requests = Table(
    "agent_handle_requests", MetaData(),
    Column("character_id", String, primary_key=True),
    Column("request_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("fingerprint", String, nullable=False),
    Column("report_json", Text, nullable=True),
)


class RequestLedger:
    """使用装配注入的会话工厂，在现有数据库内保存角色请求占用和完整终态。"""

    def __init__(self, character_id: str, sql_session_factory: Callable[[], Session]):
        self._character_id = character_id
        self._sessions = sql_session_factory
        with self._sessions() as session:
            _requests.create(session.get_bind(), checkfirst=True)
        self.outbox = PlanOutbox(character_id, sql_session_factory)

    def _key(self, request_id):
        return (_requests.c.character_id == self._character_id) & (_requests.c.request_id == request_id)

    def claim(self, request_id, fingerprint):
        """原子登记；返回 owner、recovery、occupied、conflict 或已有终态，存储异常向上抛出。"""
        with self._sessions() as session:
            row = session.execute(select(_requests).where(self._key(request_id))).mappings().first()
            if row is None:
                try:
                    session.execute(insert(_requests).values(character_id=self._character_id,
                                    request_id=request_id, version=1, fingerprint=fingerprint))
                    session.commit()
                    return "owner", None
                except IntegrityError:
                    session.rollback()
                    row = session.execute(select(_requests).where(self._key(request_id))).mappings().one()
            if row["version"] != 1 or not re.fullmatch(r"v1:[0-9a-f]{64}", row["fingerprint"]):
                raise ValueError("unknown request record")
            report = decode_report(row["report_json"]) if row["report_json"] is not None else None
            if report is not None and report.request_id != request_id:
                raise ValueError("report identity mismatch")
            if row["fingerprint"] != fingerprint:
                return "conflict", None
        return ("terminal", report) if report is not None else self.outbox.claim(request_id)

    def settle(self, request_id, fingerprint, report, confirmed_ids=()):
        """原子保存真实回执与报告；有未确认计划则释放恢复权，否则结算终态。"""
        with self._sessions() as session:
            pending = self.outbox.reconcile(session, request_id, confirmed_ids)
            result = session.execute(update(_requests).where(
                self._key(request_id), _requests.c.version == 1,
                _requests.c.fingerprint == fingerprint, _requests.c.report_json.is_(None),
            ).values(report_json=None if pending else encode_report(report)))
            if result.rowcount != 1:
                raise ValueError("request claim no longer matches")
            self.outbox.save_recovery(session, request_id, report if pending else None)
            session.commit()
