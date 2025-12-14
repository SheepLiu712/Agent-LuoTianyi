import sys
import os
import json

cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.utils.helpers import load_config
from src.gui import ui_init
from src.live2d import live2d

if __name__ == "__main__":
    main_config_path = os.path.join("config", "test_config.json")
    # main_config = load_config(main_config_path)

    app = ui_init()
    agent = LuoTianyiAgent(main_config_path)
    agent.window.show()

    ret = app.exec()
    live2d.dispose()
    sys.exit(ret)