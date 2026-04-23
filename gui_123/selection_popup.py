from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt

class SelectionModeDialog(QDialog):
    """Popup dialog to select element selection mode (Line, Rectangle, Circle, Polygon)."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.setWindowTitle("Element Selection Mode")
        self.setFixedSize(250, 130)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select Vector Selection Mode:", self))

        # --- Dropdown ---
        self.combo = QComboBox()
        self.combo.addItems(["Line", "Rectangle", "Circle", "Polygon"])
        current = getattr(app, "selection_mode", "line").capitalize()
        self.combo.setCurrentText(current)
        layout.addWidget(self.combo)

        # --- Buttons ---
        hbox = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        close_btn = QPushButton("Close")
        hbox.addWidget(apply_btn)
        hbox.addWidget(close_btn)
        layout.addLayout(hbox)

        # --- Events ---
        apply_btn.clicked.connect(self.apply)
        close_btn.clicked.connect(self.close)

    def apply(self):
        """Apply the selected element mode and sync with digitizer."""
        new_mode = self.combo.currentText().lower()
        self.app.selection_mode = new_mode

        # ✅ Sync active DigitizeManager instance
        if hasattr(self.app, "digitizer") and self.app.digitizer:
            self.app.digitizer.selection_shape_mode = new_mode
            if hasattr(self.app.digitizer, "_clear_selection"):
                self.app.digitizer._clear_selection()

            print(f"🎯 Selection mode synced to Digitizer: {new_mode}")

        print(f"✅ Element selection mode set to: {new_mode}")
        self.close()
