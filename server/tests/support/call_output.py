"""将既有输出探针接到类型化输出函数，保留故障注入与业务断言。"""

from src.domain.call.terminal import CallTerminated
from src.stage.call.call_stage import CallPCM, CallPlaybackStop, CallStreamStarted


def output_sink(probe):
    """为测试探针提供与真实 Adapter 相同的输出契约。"""

    async def emit(call_id, output):
        if isinstance(output, CallTerminated):
            if output.kind == "ENDED":
                await probe.send_ended(output)
            else:
                await probe.send_failed(output.end_reason)
        elif isinstance(output, CallStreamStarted):
            await probe.start_stream(output.response_id, output.stream_id, output.audio_format)
        elif isinstance(output, CallPCM):
            await probe.send_pcm(output.response_id, output.stream_id, output.payload, final=output.final)
        elif isinstance(output, CallPlaybackStop):
            await probe.stop_response(output.response_id, output.stream_ids)
        else:
            await probe.send_state(output)

    return emit
