"""处理器提交的不可变内容；路由身份和序号由 Agent 绑定。"""

from dataclasses import dataclass

import src.domain.agent as d


@dataclass(frozen=True, slots=True, kw_only=True)
class TextFinalDraft:
    """最终显示文字及呈现方式。"""

    delivery: d.OutputDelivery
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioChunkDraft:
    """音频字节、分片方式及可选原始音频格式。"""

    delivery: d.OutputDelivery
    data: bytes
    framing: d.AudioFraming
    audio_format: d.AudioFormat | None = None
    final: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("audio data must be nonempty bytes")
        raw_pcm = self.framing is d.AudioFraming.RAW_PCM
        if raw_pcm != (self.audio_format is not None):
            raise ValueError("RAW PCM and audio format must be declared together")
        if not raw_pcm:
            if self.final:
                raise ValueError("file audio cannot be final-framed")
            return
        if self.audio_format != d.CALL_PCM_FORMAT:
            raise ValueError("RAW PCM must use canonical CALL format")
        if len(self.data) % 2:
            raise ValueError("RAW PCM must contain complete PCM16 samples")
        if len(self.data) > d.MAX_CALL_PCM_CHUNK_BYTES:
            raise ValueError("RAW PCM chunk exceeds maximum size")


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageEndDraft:
    """消息终止状态；失败时携带音频错误码。"""

    delivery: d.OutputDelivery
    status: d.MessageEndStatus
    error_code: d.AudioErrorCode | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpressionDraft:
    """同一行动的表情及呈现方式。"""

    delivery: d.OutputDelivery
    expression: d.ChangeExpression


OutputDraft = TextFinalDraft | AudioChunkDraft | MessageEndDraft | ExpressionDraft
