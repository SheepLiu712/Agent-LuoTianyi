"""在服务端目录运行，测量真实通话语音流的首包延迟和实时率。"""

import argparse
import json
import time
import wave
from importlib.metadata import version
from pathlib import Path

from src.agent.skills.expression.speaking.tts_server import TTSServer


def measure(server, text, reference, lyrics):
    audio = bytearray()
    start = time.perf_counter()
    for chunk in server.stream_synthesize_call_pcm(text, reference, reference, lyrics):
        if chunk and not audio:
            first = time.perf_counter()
        audio.extend(chunk)
    elapsed = time.perf_counter() - start
    if not audio or len(audio) % 2 or not any(audio):
        raise ValueError("服务端返回空音频、全零音频或不完整的 PCM16 样本")
    seconds = len(audio) / (24000 * 2)
    return audio, {"first_ms": (first - start) * 1000, "audio_s": seconds, "rtf": elapsed / seconds}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="生产使用的 TTS 模型 YAML 路径")
    parser.add_argument("reference", help="同一段参考音频的路径")
    parser.add_argument("lyrics", type=Path, help="参考音频的对应文字，UTF-8 文件")
    parser.add_argument("output", type=Path, help="本轮结果目录，使用新目录")
    args = parser.parse_args()
    lyrics = args.lyrics.read_text(encoding="utf-8").strip()
    if not lyrics:
        raise ValueError("请提供参考音频的对应文字")
    texts = (
        "你好，今天过得怎么样？",
        "刚才练习的那首歌，我想再唱一遍给你听。",
        "等我们走到河边，就找一个安静的地方坐下来，听听风声，再聊聊你最近喜欢的音乐。",
    )
    args.output.mkdir(parents=True, exist_ok=False)
    env = {name: version(name) for name in ("torch", "torchaudio", "torchvision", "gsv-tts-lite")}
    (args.output / "versions.json").write_text(json.dumps(env, indent=2), encoding="utf-8")
    server = TTSServer(args.config, suppress_worker_output=False)
    try:
        server.start()
        for text in texts:
            measure(server, text, args.reference, lyrics)
        with (args.output / "samples.jsonl").open("w", encoding="utf-8") as out:
            for repeat in range(5):
                for index, text in enumerate(texts):
                    audio, row = measure(server, text, args.reference, lyrics)
                    print(json.dumps(dict(row, repeat=repeat, text=index)), file=out, flush=True)
                    if repeat == 0:
                        with wave.open(str(args.output / f"sample-{index}.wav"), "wb") as wav:
                            wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                            wav.writeframes(audio)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
