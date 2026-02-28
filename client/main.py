import sys
import os
import multiprocessing

# Determine execution path and set up environment
if getattr(sys, "frozen", False):
    # Running in a bundle (likely PyInstaller)
    # For OneDir: sys.executable is in the bundle dir.
    # Resources are strictly relative to the executable location (or we expect them there).
    cwd = os.path.dirname(os.path.abspath(sys.executable))
else:
    # Running in a normal python environment
    cwd = os.path.dirname(os.path.abspath(__file__))

# Change working directory to ensure relative paths work (crucial for config/res)
os.chdir(cwd)

# Ensure src is in path
if cwd not in sys.path:
    sys.path.append(cwd)

# Fix for QDialog import if needed or just use PySide6 direct
from PySide6.QtWidgets import QDialog

from src.utils.helpers import load_config
from src.gui import ui_init, MainWindow
from src.gui.binder import AgentBinder
from src.live2d import live2d
from src.network_client import NetworkClient
from src.gui.login_dialog import LoginDialog

if __name__ == "__main__":
    # Windows multiprocessing support for PyInstaller
    multiprocessing.freeze_support()
    main_config_path = os.path.join(cwd, "config", "config.json")
    if not os.path.exists(main_config_path):
        print(f"Config not found at {main_config_path}")

    config = load_config(main_config_path)

    app = ui_init()

    # Login Flow
    network_client = NetworkClient(base_url=config.get("base_url"))
    login_dialog = LoginDialog(network_client)

    # Try auto login
    if not login_dialog.try_auto_login():
        if login_dialog.exec() != QDialog.DialogCode.Accepted:
            live2d.dispose()
            sys.exit(0)

    print(f"Logged in as {network_client.user_id}")

    binder = AgentBinder(
        hear_callback=network_client.network_hear_callback,
        hear_picture_callback=network_client.network_hear_picture_callback,
        history_callback=network_client.network_history_callback,
    )

    try:
        window = MainWindow(config["gui"], config["live2d"], binder)
        window.show()
    except Exception as e:
        print(f"Error creating MainWindow: {e}")
        import traceback

        traceback.print_exc()
        live2d.dispose()
        sys.exit(1)

    ret = app.exec()
    live2d.dispose()
    sys.exit(ret)
