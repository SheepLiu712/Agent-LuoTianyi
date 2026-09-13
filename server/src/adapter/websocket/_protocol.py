"""现有聊天包的内部字段映射，仅由共享 adapter 的投递流程使用。"""
import base64
from collections.abc import Iterator

import src.domain.agent as d


def payloads(output: d.AgentOutput) -> Iterator[dict[str, object]]:
    """将 output 转成一个或多个包的内容字段；连接身份和包序号由投递流程补齐。"""
    if isinstance(output, d.TextFinalOutput):
        yield {"text": output.text if output.delivery is d.OutputDelivery.CONVERSATION else ""}
    elif isinstance(output, d.ExpressionOutput):
        yield {"expression": output.expression.expression_id}
    elif isinstance(output, d.AudioChunkOutput):
        for offset in range(0, len(output.data), 48 * 1024):
            yield {"audio": base64.b64encode(output.data[offset:offset + 48 * 1024]).decode("ascii")}
    elif isinstance(output, d.MessageEndOutput):
        error = None
        if output.status is d.MessageEndStatus.CANCELLED:
            error = "TTS_CANCELLED"
        elif output.status is d.MessageEndStatus.FAILED:
            error = "TTS_EMPTY" if output.error_code is d.AudioErrorCode.EMPTY_AUDIO else "TTS_STREAM_ERROR"
        yield {"is_final_package": True, "audio_error": error is not None, "error_code": error}
    else:
        raise TypeError("unsupported output")
