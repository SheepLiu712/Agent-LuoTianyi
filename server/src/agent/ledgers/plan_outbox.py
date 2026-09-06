"""保存行动计划、投递状态及恢复处理所需的报告。"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from contextlib import nullcontext

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, delete, insert, select, update
from sqlalchemy.orm import Session

from src.agent.processing.plan_identity import decode_plan, encode_plan, plan_fingerprint, plan_id
from src.domain.agent import ActionPlan, HandlingReport
from ._request_codec import decode_report, encode_report

_metadata = MetaData()
_plans = Table(
    "agent_plan_outbox",
    _metadata,
    Column("character_id", String, primary_key=True),
    Column("request_id", String, primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("payload", Text, nullable=False),
    Column("fingerprint", String, nullable=False),
    Column("state", String, nullable=False),
    Column("outcome", String, nullable=False),
)
_recoveries = Table( # 保存没有完成投递的请求的处理报告，供后续恢复使用。每个请求只允许一个调用获得恢复权。
    "agent_plan_recoveries",
    _metadata,
    Column("character_id", String, primary_key=True),
    Column("request_id", String, primary_key=True),
    Column("available", Integer, nullable=False),
    Column("report_json", Text, nullable=False),
)


@dataclass
class PlanSlot:
    """表示一份行动计划及其在本次调用中的投递状态。

    属性：
        plan (ActionPlan)：需要投递的完整行动计划。
        state (str)：后续投递的处理状态。pending 表示仍可再次投递，
            accepted 表示已确认接收，rejected 表示已终止再次投递。
        outcome (str)：已知的接收结果。ready 表示尚未尝试投递，unknown
            表示无法确定是否已接收，rejected 表示明确未接收，accepted
            表示已确认接收。后一次拒绝不会消除前一次投递的未知结果。
        confirmed (bool)：是否已确认接收。确认依据是接收器返回了与计划
            标识匹配的有效 PlanReceipt（接收确认结果），或者数据库中
            已保存 accepted 状态。该字段本身不写入数据库。
    """

    plan: ActionPlan
    state: str = "pending"
    outcome: str = "ready"
    confirmed: bool = False


class PlanOutbox:
    """按角色和请求保存行动计划，使投递失败后能够继续投递原计划。

    PlanEmitter 使用本类保存完整计划以及接收器是否已接收的结果；
    RequestLedger 使用本类保存恢复所需的处理报告，并通过数据库条件更新
    保证同一请求只有一个调用获得恢复处理权。恢复时可以读取原计划，
    无需重新运行生成计划的处理器。

    本类只负责数据库记录的读写；实际投递由 PlanEmitter 完成。
    """

    def __init__(self, character_id: str, sessions: Callable[[], Session]) -> None:
        """绑定角色和数据库会话工厂，并创建尚不存在的数据表。

        参数：
            character_id (str)：记录所属角色的唯一标识，用于隔离不同角色的数据。
            sessions (Callable[[], sqlalchemy.orm.Session])：无参数的可调用对象，
                每次调用返回一个可用于 with 语句的 SQLAlchemy 数据库会话。

        异常：
            创建数据表或取得数据库连接时发生的异常会直接传给调用者。
        """
        self.character_id, self.sessions = character_id, sessions
        with sessions() as session:
            _metadata.create_all(session.get_bind())

    def _key(self, table, request_id):
        return (table.c.character_id == self.character_id) & (table.c.request_id == request_id)

    def load(self, request_id: str, session: Session | None = None) -> list[PlanSlot]:
        """按计划序号读取指定请求的全部计划，并检查记录是否完整、一致。

        参数：
            request_id (str)：当前角色的一次 handle_stimulus 请求的唯一标识。
            session (sqlalchemy.orm.Session | None)：调用者正在使用的数据库
                会话。为 None 时创建并关闭本方法自己的会话；传入会话时，
                本方法不提交或关闭它。

        返回：
            list[PlanSlot]：按从零开始的连续序号排列的计划状态副本。
                没有记录时返回空列表；已接收记录的 confirmed 为 True。

        异常：
            ValueError：计划序号不连续、身份不匹配、完整内容的校验摘要不匹配，
                或保存的状态不合法。计划解码异常和数据库异常直接传给调用者。
        """
        with self.sessions() if session is None else nullcontext(session) as session:
            rows = (
                session.execute(select(_plans).where(self._key(_plans, request_id)).order_by(_plans.c.ordinal)).mappings().all()
            )
        slots = []
        for ordinal, row in enumerate(rows):
            plan = decode_plan(row["payload"])
            if (
                row["ordinal"] != ordinal
                or plan.plan_ordinal != ordinal
                or plan.origin_request_id != request_id
                or plan.target_character_id != self.character_id
                or plan.plan_id != plan_id(self.character_id, request_id, ordinal)
                or plan_fingerprint(row["payload"]) != row["fingerprint"]
                or row["state"] not in {"pending", "accepted", "rejected"}
                or row["outcome"] not in {"ready", "unknown", "rejected", "accepted"}
                or (row["state"] == "accepted") != (row["outcome"] == "accepted")
            ):
                raise ValueError("invalid outbox record")
            slots.append(PlanSlot(plan, row["state"], row["outcome"], row["state"] == "accepted"))
        return slots

    def save(self, slot: PlanSlot) -> None:
        """在独立事务中新增并提交一份完整计划及其投递状态。

        参数：
            slot (PlanSlot)：待保存的计划状态对象。plan 提供请求标识、计划
                序号及完整内容，state 和 outcome 提供要保存的状态。

        返回：
            None。成功返回表示数据库事务已提交；调用者应在此后才开始投递。

        异常：
            计划编码异常和数据库异常直接传给调用者。同一角色、请求、计划
            序号的记录已存在时，数据库会报告唯一键冲突，不会覆盖原记录。
        """
        plan = slot.plan
        payload = encode_plan(plan)
        with self.sessions() as session:
            session.execute(
                insert(_plans).values(
                    character_id=self.character_id,
                    request_id=plan.origin_request_id,
                    ordinal=plan.plan_ordinal,
                    payload=payload,
                    fingerprint=plan_fingerprint(payload),
                    state=slot.state,
                    outcome=slot.outcome,
                )
            )
            session.commit()

    def mark(self, slot: PlanSlot, state: str, outcome: str) -> None:
        """更新指定计划的数据库状态，提交成功后再更新传入对象。

        参数：
            slot (PlanSlot)：已保存的计划状态对象。使用其请求标识、计划序号
                和完整内容的校验摘要定位记录。
            state (str)：调用者提供的后续投递状态，应为 pending、accepted
                或 rejected；各值含义见 PlanSlot 的属性说明。
            outcome (str)：调用者提供的接收结果，应为 ready、unknown、rejected
                或 accepted；各值含义见 PlanSlot。本方法不校验状态值是否合法。

        返回：
            None。成功后 slot.state 和 slot.outcome 更新为传入值；
                slot.confirmed 保持原值，由投递方单独记录有效接收确认。

        异常：
            ValueError：找不到唯一匹配的计划记录。编码或数据库异常直接传给
                调用者；提交失败时不会更新传入对象的 state 和 outcome。
        """
        with self.sessions() as session:
            result = session.execute(
                update(_plans)
                .where(
                    self._key(_plans, slot.plan.origin_request_id),
                    _plans.c.ordinal == slot.plan.plan_ordinal,
                    _plans.c.fingerprint == plan_fingerprint(encode_plan(slot.plan)),
                )
                .values(state=state, outcome=outcome)
            )
            if result.rowcount != 1:
                raise ValueError("missing outbox slot")
            session.commit()
        slot.state, slot.outcome = state, outcome

    def claim(self, request_id: str) -> tuple[str, HandlingReport | None]:
        """尝试取得指定请求的恢复处理权，防止其他调用同时恢复该请求。

        参数：
            request_id (str)：当前角色中需要恢复计划投递的请求标识。

        返回：
            tuple[str, HandlingReport | None]：取得恢复处理权时返回
                ("recovery", report)，其中 report 是先前保存的处理报告；
                没有恢复记录或恢复权已被占用时返回 ("occupied", None)。
                成功取得后，数据库中的记录会被标记为不可再次领取。

        异常：
            ValueError：保存的报告与请求标识不符，或可领取标志不是 0 或 1。
                报告解码异常和数据库异常直接传给调用者。
        """
        with self.sessions() as session:
            row = session.execute(select(_recoveries).where(self._key(_recoveries, request_id))).mappings().first()
            if row is None:
                return "occupied", None
            report = decode_report(row["report_json"])
            if report.request_id != request_id or row["available"] not in (0, 1):
                raise ValueError("invalid recovery record")
            result = session.execute(
                update(_recoveries).where(self._key(_recoveries, request_id), _recoveries.c.available == 1).values(available=0)
            )
            session.commit()
            return ("recovery", report) if result.rowcount == 1 else ("occupied", None)

    def reconcile(self, session: Session, request_id: str, confirmed_ids: Collection[str]) -> bool:
        """在调用者的事务中补记已确认接收的计划，并检查是否仍有待投递计划。

        参数：
            session (sqlalchemy.orm.Session)：用于保存处理报告的数据库会话。
                本方法不提交事务，由调用者将计划状态与报告一起提交。
            request_id (str)：当前角色中需要核对投递结果的请求标识。
            confirmed_ids (Collection[str])：已通过有效接收确认验证的计划标识
                集合，例如 list[str] 或 tuple[str, ...]。调用者必须提供真实
                确认结果，不能仅依据处理器报告中的标识推断计划已被接收。

        返回：
            bool：补记后仍存在 state 为 pending 的记录时返回 True，否则
                返回 False。该值表示是否还有待恢复计划，不是计划数量。

        异常：
            读取和校验计划时的异常，以及数据库异常，直接传给调用者。
        """
        for slot in self.load(request_id, session):
            if slot.plan.plan_id in confirmed_ids:
                session.execute(
                    update(_plans)
                    .where(self._key(_plans, request_id), _plans.c.ordinal == slot.plan.plan_ordinal)
                    .values(state="accepted", outcome="accepted")
                )
        return bool(
            session.execute(select(_plans.c.ordinal).where(self._key(_plans, request_id), _plans.c.state == "pending")).first()
        )

    def save_recovery(self, session: Session, request_id: str, report: HandlingReport | None) -> None:
        """在调用者的事务中替换恢复记录，或删除不再需要的恢复记录。

        参数：
            session (sqlalchemy.orm.Session)：用于保存计划状态和处理报告的
                数据库会话。本方法不提交事务，由调用者统一提交。
            request_id (str)：当前角色中需要更新恢复记录的请求标识。
            report (HandlingReport | None)：已验证、用于后续恢复的处理报告。
                非 None 时保存报告并将恢复权设为可领取；为 None 时只删除
                该请求的已有恢复记录。

        返回：
            None。修改仍处于调用者的事务中，提交成功后才持久生效。

        异常：
            报告编码异常和数据库异常直接传给调用者。
        """
        session.execute(delete(_recoveries).where(self._key(_recoveries, request_id)))
        if report is not None:
            session.execute(
                insert(_recoveries).values(
                    character_id=self.character_id, request_id=request_id, available=1, report_json=encode_report(report)
                )
            )
