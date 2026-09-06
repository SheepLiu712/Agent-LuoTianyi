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
    """编码音频字节及文件分片方式。"""
    delivery: d.OutputDelivery
    data: bytes
    framing: d.AudioFraming


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
