"""独立连接实时供应商，用合成 WAV 对比取消时序；不启动业务服务或写入通话数据库。"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
import wave
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from websockets.asyncio.client import connect  # noqa: E402
from websockets.exceptions import ConnectionClosed  # noqa: E402

from src.infrastructure.config.secrets import SecretStore  # noqa: E402
from src.infrastructure.config.store import ConfigStore  # noqa: E402
from src.infrastructure.models.realtime_speech import (  # noqa: E402
    AliyunRealtimeSpeechConfig,
    RealtimeSpeechConfig,
)
from src.infrastructure.models.realtime_speech.aliyun import AliyunRealtimeSpeechSession  # noqa: E402


def event_fields(event):
    fields = {key: event[key] for key in ("event_id", "response_id", "item_id") if key in event}
    response, item = event.get("response") or {}, event.get("item") or {}
    if event.get("session"):
        fields["voice"] = event["session"].get("voice")
    if response:
        fields.update(
            response_id=response.get("id"),
            status=response.get("status"),
            status_reason=(response.get("status_details") or {}).get("reason"),
        )
    if item:
        fields.update(item_id=item.get("id"), role=item.get("role"))
    if event["type"] == "error":
        error = event.get("error") or {}
        fields["error"] = {key: error.get(key) for key in ("type", "code", "param", "event_id", "message")}
    return fields


async def react(event, mode, delete_items, ready, tasks, cancel, deleted, send):
    kind = event["type"]
    response, item = event.get("response") or {}, event.get("item") or {}
    if kind == "session.updated":
        ready.set()
    if kind == "response.created" and mode not in {"after_done", "none"}:
        tasks.append(asyncio.create_task(cancel(response["id"], float(mode))))
    if kind == "response.done" and mode == "after_done":
        tasks.append(asyncio.create_task(cancel(response["id"], 0)))
    if (
        delete_items
        and kind in {"response.output_item.added", "response.output_item.done"}
        and item.get("role") == "assistant"
        and item.get("id") not in deleted
    ):
        deleted.add(item["id"])
        await send("conversation.item.delete", item_id=item["id"])


async def finish_tasks(tasks):
    for task in tasks:
        if not task.done():
            task.cancel()
    for result in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(result, Exception) and not isinstance(result, ConnectionClosed):
            raise result


async def feed_audio(pcm, ready, record, send):
    await ready.wait()
    record("action", "audio_begin", samples=len(pcm) // 2)
    audio = pcm + bytes(16000 * 2 * 6)
    for offset in range(0, len(audio), 3200):
        await send("input_audio_buffer.append", audio=base64.b64encode(audio[offset : offset + 3200]).decode())
        await asyncio.sleep(0.1)
    record("action", "audio_end")


async def cancel_once(response_id, delay, cancelled, record, send):
    if response_id in cancelled:
        return
    cancelled.add(response_id)
    await asyncio.sleep(delay)
    record("action", "cancel_trigger", response_id=response_id)
    await send("response.cancel")


async def run_case(config, pcm, mode, delete_items, voice):
    began = time.monotonic()
    timeline = []
    tasks = []
    deleted = set()
    cancelled = set()
    ready = asyncio.Event()

    def record(direction, kind, **fields):
        timeline.append(
            {"ms": round((time.monotonic() - began) * 1000, 1), "direction": direction, "type": kind, **fields}
        )

    async with connect(
        config.websocket_url,
        additional_headers={"Authorization": f"Bearer {config.api_key}"},
        open_timeout=10,
        close_timeout=3,
        max_size=1024 * 1024,
    ) as socket:

        async def send(kind, **fields):
            event_id = uuid4().hex
            await socket.send(json.dumps({"type": kind, "event_id": event_id, **fields}))
            if kind != "input_audio_buffer.append":
                record("send", kind, event_id=event_id, item_id=fields.get("item_id"))

        async def cancel(response_id, delay):
            await cancel_once(response_id, delay, cancelled, record, send)

        update = AliyunRealtimeSpeechSession(config)._session_update(RealtimeSpeechConfig())
        if voice:
            update["session"]["voice"] = voice
        await send("session.update", session=update["session"])
        tasks.append(asyncio.create_task(feed_audio(pcm, ready, record, send)))
        deadline = time.monotonic() + 18
        try:
            while time.monotonic() < deadline:
                try:
                    event = json.loads(await asyncio.wait_for(socket.recv(), deadline - time.monotonic()))
                except asyncio.TimeoutError:
                    break
                kind = event["type"]
                if not kind.endswith(".delta"):
                    record("receive", kind, **event_fields(event))
                await react(event, mode, delete_items, ready, tasks, cancel, deleted, send)
        except ConnectionClosed as error:
            record(
                "receive",
                "connection_closed",
                received_code=error.rcvd.code if error.rcvd else None,
                sent_code=error.sent.code if error.sent else None,
            )
        finally:
            await finish_tasks(tasks)
    return {"cancel_delay": mode, "delete_items": delete_items, "voice": voice, "timeline": timeline}


async def main(args):
    root = args.config_root.resolve()
    SecretStore(root / "config/secrets.local.env").load_into_environment()
    config = AliyunRealtimeSpeechConfig.from_mapping(
        ConfigStore(root / "config/config.json", root_dir=root).read_resolved()["call_transport"]["realtime_speech"]
    )
    with wave.open(str(args.wav), "rb") as source:
        if (source.getframerate(), source.getsampwidth(), source.getnchannels()) != (16000, 2, 1):
            raise ValueError("测试 WAV 必须是 16 kHz 单声道 PCM16")
        pcm = source.readframes(source.getnframes())
    results = []
    for mode in args.modes:
        result = await run_case(config, pcm, mode, not args.no_delete, args.voice)
        results.append(result)
        args.output.write_text(
            json.dumps({"model": config.model, "cases": results}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["0", "0.1", "0.5", "after_done", "none"],
        default=["0", "0.1", "0.5", "after_done"],
    )
    parser.add_argument("--no-delete", action="store_true")
    parser.add_argument("--voice", help="仅覆盖本次诊断会话的音色")
    asyncio.run(main(parser.parse_args()))
