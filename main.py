import sys, os
import open3d as o3d
from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from gui.app_window import NakshaApp


_previous_qt_message_handler = None


def install_qt_message_filter():
    """Filter a narrow set of noisy Qt/Windows lifecycle debug messages."""
    global _previous_qt_message_handler
    if _previous_qt_message_handler is not None:
        return

    noisy_prefixes = (
        "External WM_DESTROY received",
    )

    def message_handler(msg_type, context, message):
        if any(message.startswith(prefix) for prefix in noisy_prefixes):
            return

        if _previous_qt_message_handler is not None:
            _previous_qt_message_handler(msg_type, context, message)
        else:
            stream = sys.stderr
            stream.write(f"{message}\n")
            stream.flush()

    _previous_qt_message_handler = qInstallMessageHandler(message_handler)

if __name__ == "__main__":
    # Initialize Open3D GUI (required before using O3DVisualizer)
    o3d.visualization.gui.Application.instance.initialize()
    install_qt_message_filter()

    app = QApplication(sys.argv)
    win = NakshaApp()
    win.show()
    sys.exit(app.exec())
