import os
import pathlib

cwd = os.getcwd()
genie_data_path = pathlib.Path(cwd) / "res" / "tts" / "GenieData"
if genie_data_path.exists():
    os.environ["GENIE_DATA_DIR"] = str(genie_data_path)
else:
    raise FileNotFoundError(f"GenieData directory not found at {genie_data_path}")

import genie_tts as genie

genie.load_character(
    character_name='LuoTianyi',  # Replace with your character name
    onnx_model_dir=r"res\tts\lty_custom_onnx_model",  # Folder containing ONNX model
    language='zh',  # Replace with language code, e.g., 'en', 'zh', 'jp'
)

genie.set_reference_audio(
    character_name='LuoTianyi',  # Must match loaded character name
    audio_path=r"res/tts/reference_audio/可爱的参考音频2.wav",  # Path to reference audio
    audio_text="前段时间的拜师学艺、埋头苦学，今天看起来，好像是颇见成效啦！",  # Corresponding text
)

genie.tts(
    character_name='LuoTianyi',  # Must match loaded character
    text="你好呀！今天过得怎么样呀？",  # Text to synthesize
    play=True,  # Play audio directly
    save_path=None,  # Output audio file path
)

genie.wait_for_playback_done()