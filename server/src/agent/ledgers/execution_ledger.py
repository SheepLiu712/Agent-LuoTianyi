"""保存行动计划的执行权、各行动的处理结果及输出接收状态。"""
from collections.abc import Callable, Sequence

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.agent.processing.plan_identity import decode_plan, plan_fingerprint
from ._execution_codec import ActionFact, decode_facts, encode_facts
from .output_outbox import OutputOutbox, Slot


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
    """按角色和执行标识保存完整计划，并协调同一次执行的重复调用。

    数据库记录包括执行是否被占用、各行动是否开始、处理结果以及输出是否
    已被接收。调用者据此判断能否继续执行，数据库事务不包含外部业务调用。

    属性：
        outbox (OutputOutbox)：使用同一角色和数据库的输出存储对象，保存
            完整输出内容、输出序号及接收状态。
    """

    def __init__(self, character_id: str, sessions: Callable[[], Session]) -> None:
        """绑定角色和数据库会话工厂，并创建尚不存在的数据表。

        参数：
            character_id (str)：执行记录所属角色的唯一标识。
            sessions (Callable[[], Session])：无参数的数据库会话工厂，每次
                调用返回可用于 with 语句的 SQLAlchemy Session。

        返回：
            None。

        异常：
            连接数据库或创建数据表时发生的异常直接传给调用者。
        """
        self._character_id, self._sessions = character_id, sessions
        with sessions() as session:
            _executions.create(session.get_bind(), checkfirst=True)
        self.outbox = OutputOutbox(character_id, sessions)

    def _key(self, execution_id):
        return (_executions.c.character_id == self._character_id) & (_executions.c.execution_id == execution_id)

    def read(
        self, execution_id: str, payload: str,
    ) -> tuple[str, list[ActionFact] | None, list[Slot] | None]:
        """读取已有执行，校验保存内容，并判断是否与本次计划一致。

        参数：
            execution_id (str)：当前角色中一次计划执行的唯一标识。
            payload (str)：由计划编码函数 encode_plan 生成的完整计划 JSON
                字符串。本方法将其与数据库保存的字符串直接比较。

        返回：
            tuple[str, list[ActionFact] | None, list[Slot] | None]：依次表示
                查询状态、按计划行动顺序排列的执行记录、按序号排列的输出记录。
                ActionFact 保存行动开始标志、处理结果和累计输出接收情况；
                Slot 保存一份完整输出及其接收状态。具体返回组合如下：
                ("missing", None, [])：不存在该执行记录。
                ("conflict", None, [])：已有记录的计划内容与 payload 不同。
                ("occupied", facts, [])：执行被占用；facts 只是查询时的记录，
                    不代表执行已结束，此时不会读取输出记录。
                ("available", facts, slots)：执行未被占用，返回已校验的记录。
                    旧版执行记录没有完整输出历史时，slots 为 None；新版执行
                    没有输出时，slots 为空列表。

        异常：
            ValueError：记录版本、角色、内容校验摘要或执行状态不合法。
                计划、行动记录和输出记录的解码或校验异常，以及数据库异常，
                直接传给调用者。发现损坏记录时不会自动重建。
        """
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

    def claim(
        self, execution_id: str, payload: str, facts: Sequence[ActionFact], *,
        new: bool, legacy: bool = False,
    ) -> bool:
        """尝试登记新执行，或占用内容未变化的已有执行。

        参数：
            execution_id (str)：当前角色中的执行标识。
            payload (str)：encode_plan 生成的完整计划 JSON 字符串。
            facts (Sequence[ActionFact])：按计划行动顺序排列的执行记录。
                新建时用于保存初始状态；恢复已有执行时必须与数据库内容一致。
            new (bool)：True 表示新增执行记录并初始化从零开始的输出序号；
                False 表示仅在已有执行未被占用且计划和行动记录均未变化时占用。
            legacy (bool)：恢复已有执行时，是否需要为没有完整输出历史的旧版
                记录初始化输出序号，默认 False。仅在 new 为 False 且成功
                占用时使用；调用者应先确认旧记录符合升级条件。

        返回：
            bool：成功占用并提交事务时返回 True。新建发生数据库完整性冲突，
                或已有记录不满足占用条件时返回 False，不接管其他调用的执行。

        异常：
            行动记录编码异常及其他数据库异常直接传给调用者。新建分支中的
            IntegrityError 会回滚并返回 False；其他分支的此类异常直接传播。
        """
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

    def save(self, execution_id: str, facts: Sequence[ActionFact], slots: Sequence[Slot]) -> None:
        """在同一事务中提交行动执行记录和已有输出的接收状态。

        参数：
            execution_id (str)：当前角色中已被占用的执行标识。调用者必须是
                持有执行权的调用；本方法检查占用标志，不验证调用者身份。
            facts (Sequence[ActionFact])：按计划行动顺序排列的完整执行记录，
                包含开始标志、已经验证的处理结果及累计输出接收情况。
            slots (Sequence[Slot])：需要更新接收状态的输出记录。完整输出必须
                已通过 OutputOutbox.prepare 保存，本方法不会新增输出内容。

        返回：
            None。成功返回表示行动记录和输出状态已一起提交。

        异常：
            ValueError：执行记录不存在、未被占用或需要更新的输出记录不存在。
                编码和数据库异常直接传给调用者；提交前失败会回滚本次事务。
        """
        with self._sessions() as session:
            result = session.execute(update(_executions).where(
                self._key(execution_id), _executions.c.occupied == 1,
            ).values(facts_json=encode_facts(facts)))
            if result.rowcount != 1:
                raise ValueError("execution ownership lost")
            self.outbox.save(session, execution_id, slots)
            session.commit()

    def release(self, execution_id: str) -> None:
        """清除执行占用标志，保留已有行动和输出记录。

        参数：
            execution_id (str)：当前角色中需要释放的执行标识。应由持有执行权
                的调用在退出时使用；本方法不验证调用者身份。

        返回：
            None。修改在本方法内提交；记录不存在时不报错。释放占用不表示
                所有行动都能重新执行，调用者仍需依据保存的行动和输出状态判断。

        异常：
            数据库异常直接传给调用者。
        """
        with self._sessions() as session:
            session.execute(update(_executions).where(self._key(execution_id)).values(occupied=0))
            session.commit()
