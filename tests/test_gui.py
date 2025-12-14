
import sys
import os
import json
# add cwd to sys.path
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)
from src.live2d import live2d
from src.gui import MainWindow, ui_init

if __name__ == "__main__":
    config_path = os.path.join("config", "live2d", "live2d_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        live2d_config = json.load(f)

    app = ui_init()
    win = MainWindow(live2d_config)
    win.show()
    ret = app.exec()
    live2d.dispose()
    sys.exit(ret)
