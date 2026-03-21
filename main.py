import sys, os
import open3d as o3d
from PySide6.QtWidgets import QApplication
from gui.app_window import NakshaApp

if __name__ == "__main__":
    # Initialize Open3D GUI (required before using O3DVisualizer)
    o3d.visualization.gui.Application.instance.initialize()

    app = QApplication(sys.argv)
    win = NakshaApp()
    win.show()
    sys.exit(app.exec())
