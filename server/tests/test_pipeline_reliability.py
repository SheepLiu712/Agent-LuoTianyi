import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.main_chat import OneSentenceChat
from src.chat_session.dependency.global_speaking_worker import GlobalSpeakingWorker, SpeakingJob


async def run_text_job(stream_factory):
    responses = []

    class FakeSpeech:
        def say_stream(self, _character_id, _text, _tone):
            return stream_factory()

    worker = GlobalSpeakingWorker({})
    worker.set_capabilities(SimpleNamespace(speech=FakeSpeech()))

    async def record(response):
        responses.append(response)

    await worker.enqueue(
        SpeakingJob(
            send_reply_callback=record,
            job_content=OneSentenceChat(
                uuid="reply-1",
                content="已经生成的文本",
                sound_content="需要合成的文本",
                tone="normal",
                expression="微笑脸",
            ),
        )
    )
    await asyncio.wait_for(worker.queue.join(), timeout=1)
    await worker.stop()
    return responses


@pytest.mark.asyncio
async def test_zero_tts_chunks_send_one_error_terminal_with_original_text():
    def empty_stream():
        if False:
            yield "unreachable"

    responses = await run_text_job(empty_stream)

    assert len(responses) == 1
    terminal = responses[0]
    assert terminal.is_final_package is True
    assert terminal.audio_error is True
    assert terminal.error_code == "TTS_EMPTY"
    assert terminal.text == "已经生成的文本"


@pytest.mark.asyncio
async def test_mid_stream_tts_failure_sends_exactly_one_terminal_and_keeps_text():
    def failing_stream():
        yield "YXVkaW8="
        raise RuntimeError("stream broke")

    responses = await run_text_job(failing_stream)

    terminals = [response for response in responses if response.is_final_package]
    assert len(responses) == 2
    assert len(terminals) == 1
    assert terminals[0].audio_error is True
    assert terminals[0].error_code == "TTS_STREAM_ERROR"
    assert "".join(response.text for response in responses) == "已经生成的文本"


@pytest.mark.asyncio
async def test_successful_tts_stream_still_sends_exactly_one_terminal():
    def successful_stream():
        yield "YXVkaW8tMQ=="
        yield "YXVkaW8tMg=="

    responses = await run_text_job(successful_stream)

    terminals = [response for response in responses if response.is_final_package]
    assert len(responses) == 3
    assert len(terminals) == 1
    assert terminals[0].audio_error is False
    assert terminals[0].error_code is None
    assert "".join(response.text for response in responses) == "已经生成的文本"
