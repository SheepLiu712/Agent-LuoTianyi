
import sys
import os
import json
# add cwd to sys.path
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.live2d import live2d
from src.gui import MainWindow, ui_init
from src.utils.helpers import load_config
from src.gui.binder import AgentBinder
from threading import Thread
def play_audio(file_path: str):
    import winsound
    try:
        winsound.PlaySound(audio_path, winsound.SND_FILENAME)
    except Exception as e:
        print(f"Failed to play audio: {e}")

def hear_callback(text: str):
    print(f"User said: {text}")
    # Here you would integrate with your LLM and memory searcher to get a response
    response = f"Echo: {text}"
    binder.response_signal.emit(response)

if __name__ == "__main__":
    config_path = os.path.join("config", "config.json")
    config = load_config(config_path)
    live2d_config = config.get("live2d", {})
    gui_config = config.get("gui", {})
    app = ui_init()
    binder = AgentBinder(hear_callback=hear_callback)
    win = MainWindow(gui_config, live2d_config, binder)
    win.show()
    import time
    time.sleep(1)  # 等待窗口完全加载
    binder.model.set_expression_by_cmd("呆呆脸")
    time.sleep(1)
    audio_path = r"data\tts_output\20251224223856.wav"  # Example WAV file path
    binder.start_mouth_move(audio_path)  # Example WAV file path
    thread = Thread(target=play_audio, args=(audio_path,))
    thread.start()
    ret = app.exec()
    live2d.dispose()
    sys.exit(ret)
