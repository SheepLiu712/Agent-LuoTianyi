from .main_ui import MainWindow
from ..live2d import live2d
from ..utils.theme import VoiceTheme
import sys
import os
import ctypes
from PySide6.QtGui import QSurfaceFormat, QIcon, QFont
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu


def ui_init() -> QApplication:
    # Set AppUserModelID for Windows taskbar icon
    if os.name == 'nt':
        myappid = 'LuoTianyi.Agent.Client.1.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    live2d.init()
    app = QApplication(sys.argv)

    # Set application icon
    icon_path = os.path.join("res", "gui", "icon.svg")  # res/gui/icon.svg 保存了图标文件
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

    # ── 加载主题（Voice Theme） ──
    theme_qss = VoiceTheme.load_full_qss()
    if theme_qss.strip():
        app.setStyleSheet(theme_qss)

    # 设置全局默认字体
    font = QFont()
    font.setFamilies(["PingFang SC", "Microsoft YaHei UI", "Noto Sans CJK SC", "Segoe UI", "sans-serif"])
    font.setPointSize(10)
    app.setFont(font)

    return app