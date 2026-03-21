
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, 
    QPushButton, QHBoxLayout
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont


class LoadingProgressDialog(QDialog):
    """
    Modern progress dialog for file loading operations.
    Shows:
    - File name
    - Progress bar (0-100%)
    - Current operation status
    - Cancel button (optional)
    """
    
    cancel_requested = Signal()
    
    def __init__(self, parent=None, show_cancel=False):
        super().__init__(parent)
        self.setWindowTitle("Loading LiDAR File")
        self.setModal(True)
        self.setFixedWidth(500)
        self.setWindowFlags(Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        
        self._setup_ui(show_cancel)
        self._canceled = False
        
    def _setup_ui(self, show_cancel):
        """Setup the dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # File name label
        self.file_label = QLabel("Loading file...")
        self.file_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        self.file_label.setFont(font)
        layout.addWidget(self.file_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(30)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #555;
                border-radius: 5px;
                text-align: center;
                background-color: #2b2b2b;
                color: white;
                font-size: 12px;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Initializing...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #aaa; font-size: 10px;")
        layout.addWidget(self.status_label)
        
        # Points counter label
        self.points_label = QLabel("")
        self.points_label.setAlignment(Qt.AlignCenter)
        from gui.theme_manager import ThemeColors
        self.points_label.setStyleSheet(f"color: {ThemeColors.get('accent')}; font-size: 11px; font-weight: bold;")
        layout.addWidget(self.points_label)
        
        # Cancel button (optional)
        if show_cancel:
            button_layout = QHBoxLayout()
            button_layout.addStretch()
            
            self.cancel_button = QPushButton("Cancel")
            self.cancel_button.setFixedWidth(100)
            self.cancel_button.clicked.connect(self._on_cancel)
            self.cancel_button.setStyleSheet("""
                QPushButton {
                    background-color: #d9534f;
                    color: white;
                    border: none;
                    border-radius: 5px;
                    padding: 8px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #c9302c;
                }
            """)
            
            button_layout.addWidget(self.cancel_button)
            button_layout.addStretch()
            layout.addLayout(button_layout)
    
    def set_filename(self, filename):
        """Set the filename being loaded"""
        import os
        basename = os.path.basename(filename)
        self.file_label.setText(f"📂 {basename}")
    
    def set_progress(self, value):
        """Set progress value (0-100)"""
        self.progress_bar.setValue(int(value))
    
    def set_status(self, status_text):
        """Set status message"""
        self.status_label.setText(status_text)
    
    def set_points_count(self, count):
        """Set points counter"""
        if count > 0:
            self.points_label.setText(f"📊 {count:,} points loaded")
        else:
            self.points_label.setText("")
    
    def _on_cancel(self):
        """Handle cancel button click"""
        self._canceled = True
        self.cancel_requested.emit()
        self.close()
    
    def is_canceled(self):
        """Check if operation was canceled"""
        return self._canceled
    
    def finish_success(self, message="Loading complete!"):
        """Close dialog with success"""
        self.set_status(f"✅ {message}")
        self.set_progress(100)
        QTimer.singleShot(500, self.accept)
    
    def finish_error(self, error_message):
        """Close dialog with error"""
        self.set_status(f"❌ {error_message}")
        QTimer.singleShot(2000, self.reject)


# ============================================================
# USAGE EXAMPLE - Add to your data_loader.py
# ============================================================

def load_lidar_file_with_progress(filename, parent=None, progress_callback=None):
    """
    Modified version of load_lidar_file that reports progress.
    
    Args:
        filename: Path to LiDAR file
        parent: Parent widget (for progress dialog)
        progress_callback: Function to call with (progress_percent, status_text)
    
    Returns:
        lidar_data dict or None if failed
    """
    import laspy
    import numpy as np
    
    def report_progress(percent, status):
        """Helper to report progress"""
        if progress_callback:
            progress_callback(percent, status)
    
    try:
        report_progress(10, "Opening file...")
        
        # Open LAS/LAZ file
        las = laspy.read(filename)
        total_points = len(las.points)
        
        report_progress(20, f"Reading {total_points:,} points...")
        
        # Read XYZ coordinates
        xyz = np.vstack([las.x, las.y, las.z]).T
        report_progress(40, "Processing coordinates...")
        
        # Read RGB if available
        rgb = None
        if hasattr(las, 'red') and hasattr(las, 'green') and hasattr(las, 'blue'):
            rgb = np.vstack([las.red, las.green, las.blue]).T
            rgb = (rgb / 256).astype(np.uint8)
        report_progress(60, "Processing colors...")
        
        # Read intensity
        intensity = las.intensity if hasattr(las, 'intensity') else None
        report_progress(70, "Processing intensity...")
        
        # Read classification
        classification = las.classification if hasattr(las, 'classification') else None
        report_progress(80, "Processing classification...")
        
        # Get CRS info
        crs_epsg = None
        crs_wkt = None
        if las.header.parse_crs():
            crs = las.header.parse_crs()
            crs_epsg = crs.to_epsg()
            crs_wkt = crs.to_wkt()
        report_progress(90, "Reading CRS information...")
        
        # Build result
        lidar_data = {
            "xyz": xyz,
            "rgb": rgb,
            "intensity": intensity,
            "classification": classification,
            "crs_epsg": crs_epsg,
            "crs_wkt": crs_wkt,
        }
        
        report_progress(100, f"✅ Loaded {total_points:,} points")
        return lidar_data
        
    except Exception as e:
        report_progress(0, f"Error: {str(e)}")
        return None