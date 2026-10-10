"""执行上下文与通道无关输出的不可变值。"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Protocol, runtime_checkable

from src.domain.call.contracts import CallSpeechDelivery

from ._realization_contract import RealizationContractErrorCode as _Code
from ._realization_contract import _Value
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
    interaction_context: object | None = None
    call_output_permit: CallOutputPermit | None = None


@runtime_checkable
class CallOutputPermit(Protocol):
    """Stage 提供的 CALL response 投递许可，只暴露当前授权状态。"""

    def allows(self, response_id: str) -> bool:
        """返回该 response 当前是否仍可产生新输出。"""


class AudioEncoding(str, Enum):
    """Agent 可证明的原始音频编码。"""

    PCM_S16LE = "pcm_s16le"


@dataclass(frozen=True, slots=True)
class AudioFormat(_Value):
    """原始音频字节的编码、采样率和声道数。"""

    encoding: AudioEncoding
    sample_rate: int
    channels: int

    def __post_init__(self):
        _Value.__post_init__(self)
        self._require(self.sample_rate > 0 and self.channels > 0, "Audio dimensions must be positive")


CALL_PCM_FORMAT = AudioFormat(encoding=AudioEncoding.PCM_S16LE, sample_rate=24000, channels=1)
MAX_CALL_PCM_CHUNK_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentOutput(_Value):
    """输出抽象基类，包含路由身份、稳定消息身份、执行内序号及呈现方式。"""

    _code = _Code.CONTRACT_INVALID_OUTPUT
    interaction_id: str
    execution_id: str
    action_id: str
    sequence_no: int
    delivery: OutputDelivery
    message_id: str | None = None
    call_delivery: CallSpeechDelivery = CallSpeechDelivery()

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
    """非空音频块；原始 PCM 必须声明格式，文件输出不得伪装格式或 final。"""

    kind: ClassVar[AgentOutputKind] = AgentOutputKind.AUDIO_CHUNK
    data: bytes
    framing: AudioFraming
    audio_format: AudioFormat | None = None
    final: bool = False

    def __post_init__(self):
        _Value.__post_init__(self)
        raw_pcm = self.framing is AudioFraming.RAW_PCM
        self._require(raw_pcm == (self.audio_format is not None), "Invalid audio format")
        self._require(raw_pcm or not self.final, "File audio cannot be final-framed")
        if raw_pcm:
            self._require(self.audio_format == CALL_PCM_FORMAT, "RAW PCM must use canonical CALL format")
            self._require(len(self.data) % 2 == 0, "RAW PCM must contain complete PCM16 samples")
            self._require(len(self.data) <= MAX_CALL_PCM_CHUNK_BYTES, "RAW PCM chunk exceeds maximum size")


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
    """同一说话或演唱行动附带的表情输出。"""

    kind: ClassVar[AgentOutputKind] = AgentOutputKind.EXPRESSION
    expression: ChangeExpression
