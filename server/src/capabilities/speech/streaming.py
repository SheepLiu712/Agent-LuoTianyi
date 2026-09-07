"""将同步 TTS 字节流适配为可取消的异步流。"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Generator
from typing import TYPE_CHECKING

from src.domain.agent import CancellationToken
from .stream_errors import TTSStreamCancelled

if TYPE_CHECKING:
    from .speech import SpeechCapability

_END = object()


def _next_chunk(stream: Generator[bytes, None, None]) -> bytes | object:
    return next(stream, _END)


async def _settle(task: asyncio.Task) -> bool:
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
            continue
        except Exception:
            break
    if not task.cancelled():
        task.exception()
    return cancelled


class AsyncTTS:
    """复用已初始化的角色 TTS 模块，每次最多读取一个待交付片段。"""

    def __init__(self, speech: SpeechCapability) -> None:
        """绑定 speech 持有的引擎，不创建或关闭共享模型。"""
        self._speech = speech

    async def stream(self, *, character_id: str, text: str, tone: str,
                     cancellation: CancellationToken) -> AsyncIterator[bytes]:
        """按角色、文本和语调生成字节片段；取消或关闭时释放本次生成器。"""
        if cancellation.is_cancelled:
            raise TTSStreamCancelled()
        module = self._speech.tts_module.get(character_id)
        if module is None:
            raise RuntimeError(f"角色 {character_id} 未配置 TTS")
        stop = threading.Event()
        # 创建和推进同步生成器都在工作线程执行。
        def generate() -> Generator[bytes, None, None]:
            yield from module.stream_synthesize_speech_with_tone(text, tone, cancel_event=stop)
        stream = generate()
        pending: asyncio.Task | None = None
        try:
            while True:
                if cancellation.is_cancelled:
                    raise TTSStreamCancelled()
                pending = asyncio.create_task(asyncio.to_thread(_next_chunk, stream))
                while not pending.done():
                    await asyncio.wait({pending}, timeout=0.05)
                    if cancellation.is_cancelled:
                        raise TTSStreamCancelled()
                chunk = pending.result()
                pending = None
                if chunk is _END:
                    return
                if not isinstance(chunk, bytes):
                    raise TypeError("TTS 音频片段必须为 bytes")
                if chunk:
                    yield chunk
        finally:
            stop.set()
            cancelled = False
            if pending is not None:
                cancelled = await _settle(pending)
            cleanup = asyncio.create_task(asyncio.to_thread(stream.close))
            cancelled = await _settle(cleanup) or cancelled
            cleanup.result()
            if cancelled:
                raise asyncio.CancelledError
