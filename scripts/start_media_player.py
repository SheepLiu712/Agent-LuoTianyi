import sys
import os
import json

cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.agent.media_player import MediaPlayer
from src.utils.helpers import load_config
from src.gui import ui_init
from src.live2d import live2d
import time


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    main_config_path = os.path.join("config", "config.json")

    app = ui_init()
    agent = MediaPlayer(main_config_path)
    agent.window.show()


    input("请按回车键开始播放媒体文件...")
  # wait for window shown
    agent.set_init_expression("微笑脸")
    media_list = [
        (r"data\tts_output\mid_1.wav", "微笑脸"),
        (r"data\tts_output\mid_2.wav", "温柔脸"),
        (r"data\tts_output\mid_3.wav", "微笑脸"),
        (r"data\tts_output\mid_4.wav", "卖萌"),
    ]
    agent.start_play_media(media_list)

    ret = app.exec()
    live2d.dispose()
    sys.exit(ret)