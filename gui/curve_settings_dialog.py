# gui/curve_settings_dialog.py
# Curve Tool Settings Dialog — style customization for curves

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSlider, QColorDialog, QWidget,
    QGroupBox
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath

DEFAULT_CURVE_STYLE = {'color': (0.0, 1.0, 0.0), 'width': 2}

def vtk_color_to_qcolor(vtk_color):
    """Convert VTK float (0-1) color tuple to QColor."""
    return QColor(
        int(vtk_color[0] * 255),
        int(vtk_color[1] * 255),
        int(vtk_color[2] * 255),
    )

def qcolor_to_vtk(qcolor):
    """Convert QColor to VTK float (0-1) tuple."""
    return (qcolor.redF(), qcolor.greenF(), qcolor.blueF())

def load_curve_settings():
    """Load persisted curve tool style from QSettings, falling back to defaults."""
    settings = QSettings("NakshaAI", "LidarApp")
    default = DEFAULT_CURVE_STYLE
    color_name = settings.value("curve_style/color", None)
    if color_name:
        qc = QColor(color_name)
        color = (qc.redF(), qc.greenF(), qc.blueF())
    else:
        color = default['color']
    
    width = int(settings.value("curve_style/width", default['width']))
    return {'color': color, 'width': width}

def save_curve_settings(style):
    """Persist curve tool style to QSettings."""
    settings = QSettings("NakshaAI", "LidarApp")
    qc = vtk_color_to_qcolor(style['color'])
    settings.setValue("curve_style/color", qc.name())
    settings.setValue("curve_style/width", style['width'])

class CurvePreviewWidget(QWidget):
    """Shows a live preview of the curve appearance."""

    def __init__(self, parent_dialog):
        super().__init__()
        self.dialog = parent_dialog
        self.setFixedHeight(100)
        self.setMinimumWidth(250)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            from gui.theme_manager import ThemeColors
            painter.fillRect(self.rect(), QColor(ThemeColors.get("bg_secondary")))
        except Exception:
            painter.fillRect(self.rect(), QColor("#1e1e1e"))
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(self.dialog.current_color)
        pen.setWidth(self.dialog.current_width)
        pen.setStyle(Qt.SolidLine)
        painter.setPen(pen)

        path = QPainterPath()
        y = self.height() // 2
        path.moveTo(20, y + 20)
        path.cubicTo(self.width() // 3, y - 40, 2 * self.width() // 3, y + 40, self.width() - 20, y - 20)
        painter.drawPath(path)


class CurveToolSettingsDialog(QDialog):
    """Settings dialog for customizing curve tool appearance."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("Curve Tool Settings")
        self.setModal(False)
        self.setMinimumSize(350, 300)

        curve_tool = getattr(app, 'curve_tool', None)
        if curve_tool and hasattr(curve_tool, 'curve_style'):
            self._working_style = dict(curve_tool.curve_style)
        else:
            self._working_style = dict(load_curve_settings())

        self.current_color = vtk_color_to_qcolor(self._working_style['color'])
        self.current_width = self._working_style['width']

        self._build_ui()
        self._apply_dark_theme()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(12)

        self.tool_title = QLabel("🔮 Curve Tool")
        self.tool_title.setStyleSheet("font-size: 15px; font-weight: bold; margin-bottom: 4px;")
        root_layout.addWidget(self.tool_title)

        settings_group = QGroupBox("Appearance")
        form = QVBoxLayout()
        form.setSpacing(10)

        # Color row
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self.color_button = QPushButton()
        self.color_button.setFixedSize(50, 30)
        self.color_button.setCursor(Qt.PointingHandCursor)
        self._update_color_button()
        self.color_button.clicked.connect(self._choose_color)
        color_row.addWidget(self.color_button)
        color_row.addStretch()
        form.addLayout(color_row)

        # Width row
        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Width:"))
        self.width_slider = QSlider(Qt.Horizontal)
        self.width_slider.setRange(1, 10)
        self.width_slider.setValue(self.current_width)
        self.width_slider.valueChanged.connect(self._on_width_changed)
        width_row.addWidget(self.width_slider)
        self.width_label = QLabel(f"{self.current_width} px")
        self.width_label.setFixedWidth(36)
        width_row.addWidget(self.width_label)
        form.addLayout(width_row)

        settings_group.setLayout(form)
        root_layout.addWidget(settings_group)

        # Preview
        root_layout.addWidget(QLabel("Preview:"))
        self.preview_widget = CurvePreviewWidget(self)
        root_layout.addWidget(self.preview_widget)

        root_layout.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_settings)
        btn_row.addWidget(apply_btn)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._reset_settings)
        btn_row.addWidget(reset_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        root_layout.addLayout(btn_row)

    def _choose_color(self):
        color = QColorDialog.getColor(self.current_color, self, "Choose Curve Color")
        if color.isValid():
            self.current_color = color
            self._update_color_button()
            self.preview_widget.update()

    def _update_color_button(self):
        self.color_button.setStyleSheet(
            f"background-color: {self.current_color.name()}; border: 2px solid #fff; border-radius: 4px;"
        )

    def _on_width_changed(self, value):
        self.current_width = value
        self.width_label.setText(f"{value} px")
        self.preview_widget.update()

    def _commit_current_to_working(self):
        self._working_style = {
            'color': qcolor_to_vtk(self.current_color),
            'width': self.current_width,
        }

    def _apply_settings(self):
        """Apply settings to the curve tool and persist."""
        self._commit_current_to_working()

        curve_tool = getattr(self.app, 'curve_tool', None)
        if not curve_tool:
            widget = self.parent()
            while widget:
                if hasattr(widget, 'curve_tool'):
                    curve_tool = widget.curve_tool
                    self.app = widget
                    break
                widget = widget.parent()

        if curve_tool:
            curve_tool.curve_style = dict(self._working_style)
            print(f"✅ Pushed styles to curve_tool.curve_style")
            try:
                # If there's an active preview, we could update it. But curve tool doesn't have an immediate hook.
                pass
            except Exception:
                pass

        # Persist to QSettings
        save_curve_settings(self._working_style)
        print(f"✅ Curve settings saved: color={self.current_color.name()}, width={self.current_width}px")

        try:
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage("✅ Curve settings saved", 2000)
        except Exception:
            pass

    def _reset_settings(self):
        """Reset curve settings to defaults."""
        self._working_style = dict(DEFAULT_CURVE_STYLE)
        self.current_color = vtk_color_to_qcolor(self._working_style['color'])
        self.current_width = self._working_style['width']

        self._update_color_button()
        self.width_slider.setValue(self.current_width)
        self.width_label.setText(f"{self.current_width} px")
        self.preview_widget.update()

        print("🔄 Curve settings reset to defaults")

    def _apply_dark_theme(self):
        from gui.theme_manager import get_dialog_stylesheet
        self.setStyleSheet(get_dialog_stylesheet())
