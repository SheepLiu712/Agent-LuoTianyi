from .main_ui import MainWindow
from ..live2d import live2d
import sys
import os
from PySide6.QtGui import QSurfaceFormat, QIcon
from PySide6.QtWidgets import QApplication
def ui_init() -> QApplication:
    live2d.init()
    app = QApplication(sys.argv)
    
    # Set application icon
    icon_path = os.path.join("res", "gui", "icon.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # Set default surface format for transparency
    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    return app