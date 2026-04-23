from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar,
    QPushButton, QHBoxLayout, QFrame
)
from PySide6.QtCore import Qt, QTimer, Signal

from gui.theme_manager import get_dialog_stylesheet, ThemeColors


class LoadingProgressDialog(QDialog):
    """
    Professional loading dialog for file import operations.
    """

    cancel_requested = Signal()

    def __init__(self, parent=None, show_cancel=False):
        super().__init__(parent)
        self.setProperty("themeStyledDialog", True)
        self.setWindowTitle("Loading LiDAR File")
        self.setModal(True)
        self.setFixedWidth(520)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)

        self._setup_ui(show_cancel)
        self._canceled = False

    def _setup_ui(self, show_cancel):
        self.setStyleSheet(
            get_dialog_stylesheet()
            + f"""
            QFrame#progressHero {{
                background-color: {ThemeColors.get('bg_secondary')};
                border: 1px solid {ThemeColors.get('border_light')};
                border-radius: 12px;
            }}
            QLabel#progressStatus {{
                color: {ThemeColors.get('text_secondary')};
                font-size: 9pt;
            }}
            QLabel#progressMetric {{
                color: {ThemeColors.get('accent')};
                font-size: 9.5pt;
                font-weight: 700;
            }}
            QProgressBar#loadingProgressBar {{
                border: 1px solid {ThemeColors.get('border_light')};
                border-radius: 11px;
                background-color: {ThemeColors.get('bg_input')};
                color: {ThemeColors.get('text_primary')};
                min-height: 22px;
                text-align: center;
                font-weight: 700;
            }}
            QProgressBar#loadingProgressBar::chunk {{
                border-radius: 10px;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {ThemeColors.get('accent')},
                    stop:1 {ThemeColors.get('accent_hover')}
                );
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(18, 18, 18, 18)

        hero = QFrame()
        hero.setObjectName("progressHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(16, 14, 16, 14)
        hero_layout.setSpacing(6)

        self.title_label = QLabel("Import In Progress")
        self.title_label.setObjectName("dialogTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        hero_layout.addWidget(self.title_label)

        self.status_label = QLabel("Preparing source data and validating file contents.")
        self.status_label.setObjectName("progressStatus")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        hero_layout.addWidget(self.status_label)

        layout.addWidget(hero)

        self.file_label = QLabel("Loading file...")
        self.file_label.setObjectName("dialogSectionLabel")
        self.file_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.file_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("loadingProgressBar")
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(24)
        layout.addWidget(self.progress_bar)

        self.points_label = QLabel("")
        self.points_label.setObjectName("progressMetric")
        self.points_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.points_label)

        if show_cancel:
            button_layout = QHBoxLayout()
            button_layout.addStretch()

            self.cancel_button = QPushButton("Cancel")
            self.cancel_button.setObjectName("dangerBtn")
            self.cancel_button.setFixedWidth(100)
            self.cancel_button.clicked.connect(self._on_cancel)

            button_layout.addWidget(self.cancel_button)
            button_layout.addStretch()
            layout.addLayout(button_layout)

    def set_filename(self, filename):
        import os

        self.file_label.setText(os.path.basename(filename))

    def set_progress(self, value, status_text=None):
        self.progress_bar.setValue(int(value))
        if status_text is not None:
            self.status_label.setText(status_text)

    def set_status(self, status_text):
        self.status_label.setText(status_text)

    def set_points_count(self, count):
        if count > 0:
            self.points_label.setText(f"{count:,} points processed")
        else:
            self.points_label.setText("")

    def _on_cancel(self):
        self._canceled = True
        self.cancel_requested.emit()
        self.close()

    def is_canceled(self):
        return self._canceled

    def finish_success(self, message="Loading complete"):
        self.set_status(message)
        self.set_progress(100)
        QTimer.singleShot(500, self.accept)

    def finish_error(self, error_message):
        self.set_status(error_message)
        QTimer.singleShot(2000, self.reject)


def load_lidar_file_with_progress(filename, parent=None, progress_callback=None):
    """
    Modified version of load_lidar_file that reports progress.
    """
    import laspy
    import numpy as np

    def report_progress(percent, status):
        if progress_callback:
            progress_callback(percent, status)

    try:
        report_progress(10, "Opening file...")

        las = laspy.read(filename)
        total_points = len(las.points)

        report_progress(20, f"Reading {total_points:,} points...")

        xyz = np.vstack([las.x, las.y, las.z]).T
        report_progress(40, "Processing coordinates...")

        rgb = None
        if hasattr(las, "red") and hasattr(las, "green") and hasattr(las, "blue"):
            rgb = np.vstack([las.red, las.green, las.blue]).T
            rgb = (rgb / 256).astype(np.uint8)
        report_progress(60, "Processing colors...")

        intensity = las.intensity if hasattr(las, "intensity") else None
        report_progress(70, "Processing intensity...")

        classification = las.classification if hasattr(las, "classification") else None
        report_progress(80, "Processing classification...")

        crs_epsg = None
        crs_wkt = None
        if las.header.parse_crs():
            crs = las.header.parse_crs()
            crs_epsg = crs.to_epsg()
            crs_wkt = crs.to_wkt()
        report_progress(90, "Reading CRS information...")

        lidar_data = {
            "xyz": xyz,
            "rgb": rgb,
            "intensity": intensity,
            "classification": classification,
            "crs_epsg": crs_epsg,
            "crs_wkt": crs_wkt,
        }

        report_progress(100, f"Loaded {total_points:,} points")
        return lidar_data

    except Exception as e:
        report_progress(0, f"Error: {str(e)}")
        return None
