"""保存完整输出及其接收状态，并维护同一次执行内连续的输出序号。"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, insert, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

import src.domain.agent as d
from src.agent.processing.plan_identity import plan_fingerprint
from ._execution_codec import ActionFact
from ._output_codec import decode, encode


class OutputStorageError(RuntimeError):
    """表示输出内容、接收状态或行动执行记录无法保存到数据库。

    上层执行和输出代码使用此异常表示存储失败；OutputOutbox 的方法本身
    直接传播编码、校验或数据库异常，不会统一将它们转换为此类型。
    """

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
    """表示一份完整输出及其接收状态。

    属性：
        output (AgentOutput)：包含执行标识、行动标识、交互标识、输出序号
            和具体内容的输出对象。
        state (str)：PREPARED 表示内容已保存、尚未开始投递；REJECTED 表示
            接收器已明确拒绝；UNKNOWN 表示无法确定是否已接收；ACCEPTED
            表示接收器已经确认接收。接收确认不表示客户端已经播放或展示完毕。
    """
    output: d.AgentOutput
    state: str


class OutputOutbox:
    """按角色和执行标识保存完整输出、连续序号及接收状态。

    同一次执行的输出序号从零开始，跨行动连续增长。输出内容在投递前保存，
    供后续核对和恢复使用；实际投递由上层代码执行。读取时校验输出顺序、
    内容和行动执行记录的一致性，损坏记录不会被自动替换。
    """

    def __init__(self, character_id: str, sessions: Callable[[], Session]) -> None:
        """绑定角色和数据库会话工厂，并创建尚不存在的数据表。

        参数：
            character_id (str)：输出记录所属角色的唯一标识。
            sessions (Callable[[], Session])：无参数的数据库会话工厂，每次
                调用返回可用于 with 语句的 SQLAlchemy Session。

        返回：
            None。

        异常：
            连接数据库或创建数据表时发生的异常直接传给调用者。
        """
        self.character_id, self.sessions = character_id, sessions
        with sessions() as session:
            _metadata.create_all(session.get_bind())

    def key(self, table: Table, execution_id: str) -> ColumnElement[bool]:
        """构造同时限定当前角色和指定执行的数据库筛选条件。

        参数：
            table (Table)：具有 character_id 和 execution_id 列的 SQLAlchemy 表。
            execution_id (str)：需要筛选的执行标识。

        返回：
            ColumnElement[bool]：可传给 SQLAlchemy where 方法的布尔表达式。
                本方法只构造表达式，不查询或修改数据库。

        异常：
            AttributeError：传入表缺少所需列。
        """
        return (table.c.character_id == self.character_id) & (table.c.execution_id == execution_id)

    def initialize(self, session: Session, execution_id: str) -> None:
        """在调用者的事务中为一次执行建立从零开始的输出序号记录。

        参数：
            session (Session)：登记执行权时使用的 SQLAlchemy 数据库会话。
                本方法不提交或关闭该会话，由调用者统一提交。
            execution_id (str)：当前角色中尚未建立输出序号记录的执行标识。
                用于首次登记执行，或符合升级条件的旧版无完整输出历史记录。

        返回：
            None。新增记录中的下一个输出序号为 0。

        异常：
            数据库异常直接传给调用者；已有相同角色和执行的序号记录时，
            数据库会报告唯一键冲突，不会重置已有序号。
        """
        session.execute(insert(_heads).values(character_id=self.character_id,
                                              execution_id=execution_id, next_sequence=0))

    def read(
        self, session: Session, execution_id: str, plan: d.ActionPlan,
        facts: Sequence[ActionFact],
    ) -> list[Slot]:
        """按序号读取全部输出，并核对完整内容和行动执行记录。

        参数：
            session (Session)：调用者提供的 SQLAlchemy 数据库会话；本方法
                不提交或关闭它。
            execution_id (str)：当前角色中已经初始化输出序号记录的执行标识。
            plan (ActionPlan)：该执行对应的完整行动计划，用于核对行动归属、
                行动顺序及交互标识。
            facts (Sequence[ActionFact])：与 plan.actions 一一对应且已经校验
                的行动执行记录，包含开始标志、处理结果和累计输出接收情况。

        返回：
            list[Slot]：按从零开始的连续序号排列的输出记录，没有输出时为空
                列表。每项包含重建的完整输出对象和保存的接收状态。

        异常：
            ValueError：输出数量、序号、身份、内容校验摘要、状态或行动顺序
                不合法，或输出状态与行动记录不一致。解码异常和数据库异常
                直接传给调用者；缺少输出序号记录时不会自动初始化。
        """
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

    def prepare(self, execution_id: str, output: d.AgentOutput) -> Slot:
        """在独立事务中保存下一份完整输出，并推进输出序号。

        参数：
            execution_id (str)：当前角色中已初始化输出序号记录的执行标识。
            output (AgentOutput)：调用者已校验、属于该执行的完整输出。
                sequence_no 必须等于数据库记录的下一个可用序号；本方法
                不替调用者生成或修改输出对象中的序号。

        返回：
            Slot：包含原 output 对象及 PREPARED 状态的记录。成功返回表示
                完整内容和递增后的序号已一起提交，此后调用者才可以开始投递。

        异常：
            ValueError：输出序号记录不存在或下一个可用序号已经改变。
                编码和数据库异常直接传给调用者；提交前失败时，本次新增输出
                和序号递增一起回滚，不消耗序号。
        """
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

    def save(self, session: Session, execution_id: str, slots: Sequence[Slot]) -> None:
        """在调用者的事务中更新已有输出的接收状态。

        参数：
            session (Session)：保存行动执行记录时使用的 SQLAlchemy 会话。
                本方法不提交或关闭它，由调用者将两类记录一起提交。
            execution_id (str)：当前角色中需要更新输出状态的执行标识。
            slots (Sequence[Slot])：需要更新的输出记录，使用 output.sequence_no
                定位已有记录，将其状态改为 state。调用者必须保证输出归属和
                状态合法；本方法不重新校验完整内容或状态值。

        返回：
            None。只更新状态，不新增或替换输出内容；空序列不产生修改。

        异常：
            ValueError：找不到唯一匹配的输出记录。数据库异常直接传给调用者。
                调用者负责在失败时回滚事务，避免提交部分更新。
        """
        for slot in slots:
            result = session.execute(update(_outputs).where(self.key(_outputs, execution_id),
                _outputs.c.sequence_no == slot.output.sequence_no).values(state=slot.state))
            if result.rowcount != 1:
                raise ValueError("output slot missing")
