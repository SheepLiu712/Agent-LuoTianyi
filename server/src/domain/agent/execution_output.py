"""执行上下文与通道无关输出的不可变值。"""
from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from ._realization_contract import RealizationContractErrorCode as _Code, _Value
from .action_plan import ChangeExpression
from .handle_input import CancellationToken
from .interaction_snapshot import AgentOutputKind
from .realization_enums import AudioErrorCode, AudioFraming, MessageEndStatus, OutputDelivery


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionContext(_Value):
    """stage 在业务计划出队时传入的执行身份、当前修订和共享取消令牌。

    cancellation 保留原对象，执行取消与 handle 取消分别表达。
    """
    _code = _Code.CONTRACT_INVALID_EXECUTION_CONTEXT
    execution_id: str
    interaction_id: str
    current_interaction_revision: int
    cancellation: CancellationToken


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentOutput(_Value):
    """输出抽象基类，包含路由身份、执行内序号及呈现方式。"""
    _code = _Code.CONTRACT_INVALID_OUTPUT
    interaction_id: str
    execution_id: str
    action_id: str
    sequence_no: int
    delivery: OutputDelivery

    @property
    @abstractmethod
    def kind(self) -> AgentOutputKind:
        """返回具体输出固定的判别值。"""


@dataclass(frozen=True, slots=True, kw_only=True)
class TextFinalOutput(AgentOutput):
    """最终显示文本；文字定稿不表示消息或音频已经结束。"""
    kind: ClassVar[AgentOutputKind] = AgentOutputKind.TEXT_FINAL
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioChunkOutput(AgentOutput):
    """非空编码音频块，framing 区分独立文件与文件片段；构造不解码媒体。"""
    kind: ClassVar[AgentOutputKind] = AgentOutputKind.AUDIO_CHUNK
    data: bytes
    framing: AudioFraming


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageEndOutput(AgentOutput):
    """一条消息的终止标记，纯文字同样适用，不表示客户端已播放完成。

    FAILED 必须附音频错误码，COMPLETED/CANCELLED 的 error_code 为 None。
    """
    kind: ClassVar[AgentOutputKind] = AgentOutputKind.MESSAGE_END
    status: MessageEndStatus
    error_code: AudioErrorCode | None

    def __post_init__(self):
        _Value.__post_init__(self)
        self._require((self.status is MessageEndStatus.FAILED) == (self.error_code is not None), "Invalid end error")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpressionOutput(AgentOutput):
    """同一说话或演唱行动的表情输出，包括消息终止后的 normal 恢复。"""
    kind: ClassVar[AgentOutputKind] = AgentOutputKind.EXPRESSION
    expression: ChangeExpression
