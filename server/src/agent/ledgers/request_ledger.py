"""保存请求的处理权和处理结果，支持重复请求查询及原计划投递恢复。"""

from collections.abc import Callable, Collection
import re

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.domain.agent import HandlingReport

from ._request_codec import decode_report, encode_report
from .plan_outbox import PlanOutbox

_requests = Table(
    "agent_handle_requests",
    MetaData(),
    Column("character_id", String, primary_key=True),
    Column("request_id", String, primary_key=True),
    Column("version", Integer, nullable=False),
    Column("fingerprint", String, nullable=False),
    Column("report_json", Text, nullable=True),
)


class RequestLedger:
    """按角色和请求标识记录处理权，避免同一请求重复运行处理器。

    首次登记成功的调用获得处理权；相同请求再次到来时，可以读取已保存的
    最终报告，或取得原计划的恢复投递权。已经登记但没有最终报告、也没有
    可领取恢复记录的请求仍视为被占用，不会自动交给新的调用重新处理。

    属性：
        outbox (PlanOutbox)：与本对象使用同一角色和数据库会话工厂的计划
            存储对象，保存完整行动计划、投递状态及恢复所需的报告。
    """

    def __init__(self, character_id: str, sql_session_factory: Callable[[], Session]) -> None:
        """绑定角色和数据库会话工厂，并创建尚不存在的数据表。

        参数：
            character_id (str)：请求所属角色的唯一标识，用于隔离不同角色的数据。
            sql_session_factory (Callable[[], Session])：无参数的可调用对象，
                每次调用返回一个可用于 with 语句的 SQLAlchemy 数据库会话。
                请求记录和计划记录均使用此工厂访问数据库。

        返回：
            None。

        异常：
            取得数据库连接或创建数据表时发生的异常直接传给调用者。
        """
        self._character_id = character_id
        self._sessions = sql_session_factory
        with self._sessions() as session:
            _requests.create(session.get_bind(), checkfirst=True)
        self.outbox = PlanOutbox(character_id, sql_session_factory)

    def _key(self, request_id):
        return (_requests.c.character_id == self._character_id) & (_requests.c.request_id == request_id)

    def claim(self, request_id: str, fingerprint: str) -> tuple[str, HandlingReport | None]:
        """登记新请求，或查询已有请求的结果并尝试取得恢复投递权。

        参数：
            request_id (str)：当前角色的一次 handle_stimulus 请求的唯一标识。
                同一逻辑请求再次提交时必须使用相同标识。
            fingerprint (str)：调用者根据绑定角色、刺激及交互快照计算的内容
                校验摘要，格式为 v1: 后接 64 位小写十六进制字符。摘要不包含
                请求标识和可变的取消令牌，用于识别相同请求标识下的内容冲突。
                本方法不会重新计算摘要，也不会在首次写入时校验其格式。

        返回：
            tuple[str, HandlingReport | None]：第一个元素说明本次登记结果，
                第二个元素在有可用报告时提供该报告。具体组合如下：
                ("owner", None)：新请求已提交到数据库，本次调用获得首次处理权。
                ("terminal", report)：请求已有最终报告，直接返回保存的结果。
                ("recovery", report)：本次调用取得原计划的恢复投递权，report
                    是先前保存的处理报告；此状态不授权重新运行处理器。
                ("occupied", None)：请求已登记，但当前没有可领取的恢复记录。
                ("conflict", None)：相同请求标识已保存了不同的内容校验摘要。

        异常：
            ValueError：已有记录的版本或摘要格式不受支持，或已有报告的请求
                标识不匹配。报告解码、恢复记录校验及数据库异常直接传给调用者。
                并发新增造成的唯一键冲突会先回滚，再读取另一调用保存的记录。
        """
        with self._sessions() as session:
            row = session.execute(select(_requests).where(self._key(request_id))).mappings().first()
            if row is None:
                try:
                    session.execute(
                        insert(_requests).values(
                            character_id=self._character_id, request_id=request_id, version=1, fingerprint=fingerprint
                        )
                    )
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
        if report is not None:
            return "terminal", report # 已有最终报告，直接返回保存的结果
        return self.outbox.claim(request_id) # 取得原计划的恢复投递权，或说明请求已登记但没有可领取的恢复记录

    def settle(
        self,
        request_id: str,
        fingerprint: str,
        report: HandlingReport,
        confirmed_ids: Collection[str] = (),
    ) -> None:
        """在同一个事务中保存计划接收结果、请求报告和恢复处理状态。

        参数：
            request_id (str)：当前角色中已经登记、需要保存处理结果的请求标识。
            fingerprint (str)：登记该请求时使用的内容校验摘要，必须与数据库
                中的记录一致；其格式和计算范围见 claim 的参数说明。
            report (HandlingReport)：调用者已验证且属于该请求的处理报告。
                仍有待投递计划时作为恢复依据保存，否则作为最终报告保存。
            confirmed_ids (Collection[str])：已通过接收器返回的有效接收确认
                验证的计划标识集合，可以传入列表、元组或集合，默认空元组。
                这些标识用于补记已接收状态，不能仅从处理器报告中推断得出。

        返回：
            None。成功返回表示全部修改已经一起提交。补记接收结果后，如果
                仍有 pending 状态的计划，则保存恢复报告并允许后续调用取得
                恢复投递权；否则保存最终报告，并删除该请求的恢复记录。

        异常：
            ValueError：没有唯一匹配的、尚未保存最终报告的请求记录，或计划
                记录校验失败。报告编码及数据库异常直接传给调用者。
                提交前任一步骤失败时，本次事务中的修改一起回滚。
        """
        with self._sessions() as session:
            pending = self.outbox.reconcile(session, request_id, confirmed_ids)
            result = session.execute(
                update(_requests)
                .where(
                    self._key(request_id),
                    _requests.c.version == 1,
                    _requests.c.fingerprint == fingerprint,
                    _requests.c.report_json.is_(None),
                )
                .values(report_json=None if pending else encode_report(report))
            )
            if result.rowcount != 1:
                raise ValueError("request claim no longer matches")
            self.outbox.save_recovery(session, request_id, report if pending else None)
            session.commit()
