import sys
import os
import json
# add cwd to sys.path
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.tts import TTSModule
from src.utils.helpers import load_config

main_config_path = os.path.join("config", "test_config.json")
main_config = load_config(main_config_path)

tts_config = main_config.get("tts_module", {})
tts_module = TTSModule(tts_config)

tts_module.synthesize_speech(
    text="我是洛天依！很高兴认识你！",
    ref_audio= "可爱的参考音频"
    )