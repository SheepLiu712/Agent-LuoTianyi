from .main_ui import MainWindow
from ..live2d import live2d
import sys
import os
import ctypes
from PySide6.QtGui import QSurfaceFormat, QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
def ui_init() -> QApplication:
    # Set AppUserModelID for Windows taskbar icon
    if os.name == 'nt':
        myappid = 'LuoTianyi.Agent.Client.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    live2d.init()
    app = QApplication(sys.argv)
    
    # Set application icon
    icon_path = os.path.join("res", "gui", "icon.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
        tray_icon = QSystemTrayIcon(QIcon(icon_path), app)
        tray_menu = QMenu()
        exit_action = tray_menu.addAction("Exit")
        tray_icon.setContextMenu(tray_menu)
    
    # Set default surface format for transparency
    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    return app