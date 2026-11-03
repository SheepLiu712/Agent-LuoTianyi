"""使用合成 WAV 独立验证 Fun-ASR 多轮识别、静音保活和结束任务尾句。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from websockets.asyncio.client import connect  # noqa: E402

from src.infrastructure.config.secrets import SecretStore  # noqa: E402
from src.infrastructure.config.store import ConfigStore  # noqa: E402
from src.infrastructure.models.realtime_speech import (  # noqa: E402
    AliyunRealtimeSpeechSessionFactory,
    AudioFrame,
    RealtimeSpeechConfig,
    SpeechStarted,
    SpeechStopped,
    TurnCompleted,
)


async def push_pcm(session, audio):
    for offset in range(0, len(audio), 3200):
        await session.push_audio(AudioFrame(audio[offset : offset + 3200], "pcm_s16le", 16000, 1))
        await asyncio.sleep(0.1)


async def run_adapter(config, pcm, args, record):
    session = await AliyunRealtimeSpeechSessionFactory.from_mapping(config).create(uuid4())
    results = []

    async def consume():
        async for event in session.events():
            results.append(event)
            record("receive", {"event": type(event).__name__, **asdict(event)})

    await session.start(RealtimeSpeechConfig(language="zh"))
    consumer = asyncio.create_task(consume())
    try:
        record("send", {"action": "initial_silence", "seconds": args.initial_silence_seconds})
        await push_pcm(session, bytes(32000 * args.initial_silence_seconds))
        assert not results, "纯静音不应产生通话事件"
        rounds = () if args.silence_only else (args.silence_seconds, 2, 0)
        for index, silence in enumerate(rounds, 1):
            record("send", {"action": "audio_begin", "round": index})
            audio = pcm + bytes(32000 * silence)
            await push_pcm(session, audio)
        await session.close()
        await asyncio.wait_for(consumer, 5)
        assert await session.wait_failure() is None
        assert [type(e) for e in results] == [SpeechStarted, SpeechStopped, TurnCompleted] * len(rounds)
        record("assert", {"action": "passed", "completed_turns": len(rounds), "event_count": len(results)})
    finally:
        await session.close()
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)


async def feed(socket, pcm, silence_seconds, task_id, record):
    # 第一轮后长静音，第二轮正常断句，第三轮发送完立刻结束以验证尾句。
    for index, silence in enumerate((silence_seconds, 2, 0), 1):
        record("send", {"action": "audio_begin", "round": index})
        audio = pcm + bytes(32000 * silence)
        for offset in range(0, len(audio), 3200):
            await socket.send(audio[offset : offset + 3200])
            await asyncio.sleep(0.1)
    await socket.send(
        json.dumps(
            {
                "header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
                "payload": {"input": {}},
            }
        )
    )
    record("send", {"action": "finish-task"})


async def main(args):
    root = args.config_root.resolve()
    SecretStore(root / "config/secrets.local.env").load_into_environment()
    config = ConfigStore(root / "config/config.json", root_dir=root).read_resolved()
    key = config["call_transport"]["realtime_speech"]["api_key"]
    with wave.open(str(args.wav), "rb") as source:
        if (source.getframerate(), source.getsampwidth(), source.getnchannels()) != (16000, 2, 1):
            raise ValueError("测试 WAV 必须是 16 kHz 单声道 PCM16")
        pcm = source.readframes(source.getnframes())
    task_id = uuid4().hex
    timeline = []
    began = time.perf_counter()

    def record(direction, event):
        entry = {"ms": round((time.perf_counter() - began) * 1000, 1), "direction": direction, **event}
        timeline.append(entry)
        args.output.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    if args.adapter:
        await run_adapter(config["call_transport"]["realtime_speech"], pcm, args, record)
        return

    async with connect(
        "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
        additional_headers={"Authorization": f"Bearer {key}"},
        open_timeout=10,
        close_timeout=5,
    ) as socket:
        await socket.send(
            json.dumps(
                {
                    "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
                    "payload": {
                        "task_group": "audio",
                        "task": "asr",
                        "function": "recognition",
                        "model": "fun-asr-realtime",
                        "input": {},
                        "parameters": {
                            "format": "pcm",
                            "sample_rate": 16000,
                            "max_sentence_silence": 800,
                            "heartbeat": True,
                        },
                    },
                }
            )
        )
        event = json.loads(await asyncio.wait_for(socket.recv(), 10))
        record("receive", event)
        if event["header"]["event"] != "task-started":
            raise RuntimeError("Fun-ASR 任务启动失败，查看诊断结果")

        feeder = asyncio.create_task(feed(socket, pcm, args.silence_seconds, task_id, record))
        try:
            while True:
                event = json.loads(await asyncio.wait_for(socket.recv(), args.silence_seconds + 20))
                record("receive", event)
                kind = event["header"]["event"]
                if kind == "task-failed":
                    raise RuntimeError("Fun-ASR 任务失败，查看诊断结果")
                if kind == "task-finished":
                    break
            await feeder
        finally:
            if not feeder.done():
                feeder.cancel()
            await asyncio.gather(feeder, return_exceptions=True)
    finals = [e for e in timeline if e.get("payload", {}).get("output", {}).get("sentence", {}).get("sentence_end")]
    if len(finals) != 3:
        raise AssertionError(f"预期三轮最终识别结果，实际 {len(finals)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--wav", type=Path, required=True, help="仅使用公开合成语音；结果会记录识别文本")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--silence-seconds", type=int, default=35)
    parser.add_argument("--adapter", action="store_true", help="通过系统实际使用的供应商工厂验证领域事件")
    parser.add_argument("--initial-silence-seconds", type=int, default=6)
    parser.add_argument("--silence-only", action="store_true", help="适配器测试只发送初始静音并关闭")
    asyncio.run(main(parser.parse_args()))
