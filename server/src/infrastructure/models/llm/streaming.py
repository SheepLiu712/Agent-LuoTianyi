"""消费兼容 Chat Completions 的增量事件，保持连接生命周期与调用一致。"""

import json
from collections.abc import AsyncIterator

import httpx

from .errors import ProviderStreamError


def _decode_event(data):
    event = json.loads(data)
    if "error" in event:
        raise ProviderStreamError(event)
    finished, chunks = False, []
    for choice in event.get("choices", ()):
        reason = choice.get("finish_reason")
        if reason is not None:
            if reason != "stop":
                raise RuntimeError(f"模型流未正常完成：{reason}")
            finished = True
        content = choice.get("delta", {}).get("content")
        if content:
            chunks.append({"content": content})
    if event.get("usage") is not None:
        chunks.append({"usage": event["usage"]})
    return finished, chunks


async def stream_completion(url: str, api_key: str, payload: dict, timeout: float) -> AsyncIterator[dict]:
    if not api_key:
        raise RuntimeError("流式模型调用要求配置服务端 API Key")
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers={"Authorization": f"Bearer {api_key}"}, json=payload) as response:
            if response.is_error:
                await response.aread()
            response.raise_for_status()
            finished = False
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    if not finished:
                        raise RuntimeError("模型流结束前未收到完成标记")
                    return
                if not data:
                    continue
                ended, chunks = _decode_event(data)
                finished = finished or ended
                for chunk in chunks:
                    yield chunk
            if not finished:
                raise RuntimeError("模型流意外断开")
