import asyncio
import io
import json
import os
import sys

import soundfile as sf

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.tts import tts_module as tts_module_runtime


async def main() -> None:
    root_dir = ROOT_DIR
    config_path = os.path.join(root_dir, "config", "config.json")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    tts_config = config["tts"]

    # Ensure relative paths resolve correctly for config entries.
    old_cwd = os.getcwd()
    os.chdir(root_dir)

    try:
        module = tts_module_runtime.init_tts_module(tts_config)
        print("[OK] TTSModule started with gsv_tts worker")

        audio_data = await module.synthesize_speech_with_tone(
            text="大家好！我是虚拟歌手，洛天依！",
            tone="happy",
        )

        # Validate WAV header can be parsed by soundfile from bytes.
        with sf.SoundFile(io.BytesIO(audio_data)) as f:
            print(f"[OK] WAV bytes validated: sr={f.samplerate}, frames={len(f)}")

        output_path = os.path.join(root_dir, "tts_happy_test.wav")
        with open(output_path, "wb") as wf:
            wf.write(audio_data)

        print(f"[OK] Saved synthesized audio to: {output_path}")
    finally:
        if tts_module_runtime.tts_server is not None:
            tts_module_runtime.tts_server.stop()
        os.chdir(old_cwd)


if __name__ == "__main__":
    asyncio.run(main())
