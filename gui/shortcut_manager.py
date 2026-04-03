from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QFileDialog, QComboBox, QHeaderView, QMessageBox, QDialog,
    QListWidget, QListWidgetItem, QLabel,QCheckBox,QDoubleSpinBox
)
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect
from PySide6.QtWidgets import QFrame, QAbstractItemView
from PySide6.QtCore import Signal, Qt, QSettings,QEvent
from PySide6.QtGui import QColor
from torch import layout

 
from .class_picker import ClassPicker
from .theme_manager import get_dialog_stylesheet

TOOLS = [
    "AboveLine", "BelowLine", "Rectangle", "Circle",
    "Freehand", "Brush", "Point",
    "CrossSectionRect","CutSectionRect",
    "CutFromCross", "CutFromCut",
    "TopView",
    "DisplayMode",
    "ShadingMode", "Depth",
    "RGB",
    "Intensity",
    "Elevation",
    "Class",
    "DrawSettings",
    "MeasureLine", "MeasurePath", "ClearMeasurements"
]

SIMPLE_SHORTCUT_TOOLS = (
    "CrossSectionRect", "CutSectionRect", "CutFromCross", "CutFromCut",
    "TopView", "Depth", "RGB", "Intensity", "Elevation", "Class",
    "MeasureLine", "MeasurePath", "ClearMeasurements",
)

 
import json
 
def encode_classes(from_cls, to_cls):
    return json.dumps({"from": from_cls, "to": to_cls})
 
def decode_classes(text):
    try:
        data = json.loads(text)
        return data.get("from"), data.get("to")
    except:
        return None, None

def encode_display_preset(payload: dict) -> str:
    try:
        views = payload.get("views", {})
        views_json = {}
        
        for view_idx, classes in views.items():
            view_key = str(int(view_idx))
            classes_json = {}
            
            for k, v in classes.items():
                code = str(int(k))
                classes_json[code] = {
                    "show": bool(v.get("show", False)),
                    "description": str(v.get("description", "")),
                    "color": list(v.get("color", (128, 128, 128))),
                    "weight": float(v.get("weight", 1.0)),
                    "draw": v.get("draw", ""),
                    "lvl": v.get("lvl", ""),
                }
            
            views_json[view_key] = classes_json

        preset = {
            "__type__": "display_mode_preset_v2",
            "border_percent": float(payload.get("border_percent", 0)),
            "force_refresh": bool(payload.get("force_refresh", True)),
            "views": views_json,
        }
        return json.dumps(preset)
    except Exception as e:
        print(f"❌ encode_display_preset error: {e}")
        return json.dumps({"__type__": "display_mode_preset_v2", "views": {}})


def decode_display_preset(text: str):
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        
        preset_type = data.get("__type__")
        
        if preset_type == "display_mode_preset_v2":
            views = {}
            for view_idx_str, classes in (data.get("views", {}) or {}).items():
                view_idx = int(view_idx_str)
                classes_dict = {}
                
                for code_str, v in classes.items():
                    code = int(code_str)
                    classes_dict[code] = {
                        "show": bool(v.get("show", False)),
                        "description": str(v.get("description", "")),
                        "color": tuple(v.get("color", (128, 128, 128))),
                        "weight": float(v.get("weight", 1.0)),
                        "draw": v.get("draw", ""),
                        "lvl": v.get("lvl", ""),
                    }
                
                views[view_idx] = classes_dict
            
            return {
                "border_percent": float(data.get("border_percent", 0)),
                "force_refresh": bool(data.get("force_refresh", True)),
                "views": views,
            }
        
        elif preset_type == "display_mode_preset":
            classes = {}
            for code_str, v in (data.get("classes", {}) or {}).items():
                code = int(code_str)
                classes[code] = {
                    "show": bool(v.get("show", False)),
                    "description": str(v.get("description", "")),
                    "color": tuple(v.get("color", (128, 128, 128))),
                    "weight": float(v.get("weight", 1.0)),
                    "draw": v.get("draw", ""),
                    "lvl": v.get("lvl", ""),
                }
            
            target_view = data.get("target_view", data.get("slot", 0))
            return {
                "border_percent": float(data.get("border_percent", 0)),
                "force_refresh": bool(data.get("force_refresh", True)),
                "views": {target_view: classes},
            }
        
        return None
    except Exception as e:
        print(f"❌ decode_display_preset error: {e}")
        return None


DARK_STYLESHEET = """
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Segoe UI", "SF Pro Display", Roboto, sans-serif;
    font-size: 12px;
}

QTableWidget {
    background-color: #252526;
    gridline-color: #3e3e42;
    border: 1px solid #3e3e42;
    selection-background-color: #0e639c;
    alternate-background-color: #2d2d30;
}

QTableWidget::item {
    padding: 8px;
    border-bottom: 1px solid #3e3e42;
}

QTableWidget::item:selected {
    background-color: #0e639c;
    color: white;
}

QTableCornerButton::section {
    background-color: #252526;
    border: 1px solid #3e3e42;
    border-right: 1px solid #3e3e42;
}

QHeaderView::section {
    background-color: #2d2d30;
    border: none;
    padding: 8px;
    border-bottom: 1px solid #3e3e42;
    border-right: 1px solid #3e3e42;
    font-weight: bold;
    color: #cccccc;
}

QHeaderView::section:hover {
    background-color: #3e3e42;
}

QComboBox {
    background-color: #3c3c3c;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 4px 8px;
    color: #e0e0e0;
    min-height: 24px;
}

QComboBox:hover {
    background-color: #454545;
    border-color: #569cd6;
}

QComboBox:focus {
    background-color: #454545;
    border-color: #007acc;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 5px solid #cccccc;
}

QComboBox::down-arrow:on {
    border-top: none;
    border-bottom: 5px solid #cccccc;
}

QComboBox QAbstractItemView {
    background-color: #3c3c3c;
    border: 1px solid #404040;
    selection-background-color: #0e639c;
    color: #e0e0e0;
    selection-color: white;
}

QPushButton {
    background-color: #3c3c3c;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 8px 16px;
    color: #e0e0e0;
    font-weight: 500;
    min-height: 32px;
}

QPushButton:hover {
    background-color: #454545;
    border-color: #569cd6;
}

QPushButton:pressed {
    background-color: #2d2d30;
}

QPushButton#add_btn, QPushButton#del_btn {
    background-color: #0e639c;
    border-color: #007acc;
    min-width: 40px;
    padding: 8px;
}

QPushButton#add_btn:hover, QPushButton#del_btn:hover {
    background-color: #1177bb;
}

QPushButton#apply_btn {
    background-color: #0b851c;
    border-color: #0e9f26;
}

QPushButton#apply_btn:hover {
    background-color: #149928;
}

QPushButton#save_btn {
    background-color: #cd7f32;
    border-color: #d18e4f;
}

QPushButton#save_btn:hover {
    background-color: #e6a757;
}

QScrollBar:vertical {
    background: #2d2d30;
    width: 12px;
    border-radius: 6px;
}

QScrollBar::handle:vertical {
    background: #404040;
    border-radius: 6px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background: #569cd6;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: #2d2d30;
    height: 12px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal {
    background: #404040;
    border-radius: 6px;
    min-width: 20px;
}

QSpinBox, QDoubleSpinBox {
    background-color: #3c3c3c;
    border: 1px solid #404040;
    border-radius: 4px;
    padding: 4px;
    color: #e0e0e0;
    selection-background-color: #0e639c;
    selection-color: white;
}

QSpinBox:focus, QDoubleSpinBox:focus {
    background-color: #3c3c3c;
    border-color: #007acc;
}

QSpinBox::up-button, QDoubleSpinBox::up-button {
    background-color: #0e639c;
    border-left: 1px solid #007acc;
    width: 16px;
}

QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {
    background-color: #1177bb;
}

QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: #0e639c;
    border-left: 1px solid #007acc;
    width: 16px;
}

QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #1177bb;
}

QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 4px solid white;
}

QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 4px solid white;
}
"""

def encode_shading_preset(payload: dict) -> str:
    try:
        classes = payload.get("classes", {}) or {}
        classes_json = {}
        for k, v in classes.items():
            code = str(int(k))
            classes_json[code] = {
                "show": bool(v.get("show", False)),
                "color": list(v.get("color", (128, 128, 128))),
            }

        preset = {
            "__type__": "shading_mode_preset",
            "azimuth": float(payload.get("azimuth", 45.0)),
            "angle": float(payload.get("angle", 45.0)),
            "ambient": float(payload.get("ambient", 0.1)),
            "quality": float(payload.get("quality", 100.0)),
            "speed": int(payload.get("speed", 1)),
            "classes": classes_json,
        }
        return json.dumps(preset)
    except Exception:
        return json.dumps({"__type__": "shading_mode_preset", "classes": {}})


def decode_shading_preset(text: str):
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("__type__") != "shading_mode_preset":
            return None

        classes = {}
        for code_str, v in (data.get("classes", {}) or {}).items():
            code = int(code_str)
            classes[code] = {
                "show": bool(v.get("show", False)),
                "color": tuple(v.get("color", (128, 128, 128))),
            }

        return {
            "azimuth": float(data.get("azimuth", 45.0)),
            "angle": float(data.get("angle", 45.0)),
            "ambient": float(data.get("ambient", 0.1)),
            "quality": float(data.get("quality", 100.0)),
            "speed": int(data.get("speed", 1)),
            "classes": classes,
        }
    except Exception:
        return None

def encode_draw_preset(payload: dict) -> str:
    try:
        tools = payload.get("tools", {}) or {}
        tools_json = {}
        for tool_key, style in tools.items():
            tools_json[str(tool_key)] = {
                "color": list(style.get("color", (1.0, 0.0, 0.0))),
                "width": int(style.get("width", 2)),
                "style": str(style.get("style", "solid")),
            }
        preset = {
            "__type__": "draw_settings_preset",
            "active_tool": str(payload.get("active_tool", "smartline")),
            "tools": tools_json,
        }
        return json.dumps(preset)
    except Exception as e:
        print(f"❌ encode_draw_preset error: {e}")
        return json.dumps({"__type__": "draw_settings_preset", "tools": {}})


def decode_draw_preset(text: str):
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("__type__") != "draw_settings_preset":
            return None
        tools = {}
        for tool_key, style in (data.get("tools", {}) or {}).items():
            tools[str(tool_key)] = {
                "color": tuple(style.get("color", (1.0, 0.0, 0.0))),
                "width": int(style.get("width", 2)),
                "style": str(style.get("style", "solid")),
            }
        return {"active_tool": str(data.get("active_tool", "smartline")), "tools": tools}
    except Exception as e:
        print(f"❌ decode_draw_preset error: {e}")
        return None


class DrawSettingsPicker(QDialog):
    def __init__(self, app_window, parent=None):
        super().__init__(parent)
        self.app_window = app_window
        self.setWindowTitle("Configure Draw Settings Preset")
        self.setModal(False)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.resize(560, 480)

        from gui.draw_settings_dialog import (
            DEFAULT_DRAW_STYLES, TOOL_ORDER, TOOL_DISPLAY_NAMES,
            vtk_color_to_qcolor, qcolor_to_vtk, load_draw_settings,
        )
        self._TOOL_ORDER = TOOL_ORDER
        self._TOOL_DISPLAY_NAMES = TOOL_DISPLAY_NAMES
        self._vtk_to_q = vtk_color_to_qcolor
        self._q_to_vtk = qcolor_to_vtk

        if (hasattr(app_window, 'digitizer') and
                hasattr(app_window.digitizer, 'draw_tool_styles')):
            self._styles = {k: dict(v) for k, v in app_window.digitizer.draw_tool_styles.items()}
        else:
            try:
                self._styles = load_draw_settings()
            except Exception:
                self._styles = {k: dict(v) for k, v in DEFAULT_DRAW_STYLES.items()}

        self._build_ui()
        self.setStyleSheet(DARK_STYLESHEET)

    def _build_ui(self):
        from PySide6.QtWidgets import QGridLayout, QScrollArea, QGroupBox
        layout = QVBoxLayout(self)

        info = QLabel("Configure draw tool styles for this shortcut:")
        info.setStyleSheet("color: #cccccc; font-style: italic;")
        layout.addWidget(info)

        tool_row = QHBoxLayout()
        tool_row.addWidget(QLabel("Activate Tool:"))
        self._active_tool_combo = QComboBox()
        for key in self._TOOL_ORDER:
            self._active_tool_combo.addItem(
                self._TOOL_DISPLAY_NAMES.get(key, key), key
            )
        self._active_tool_combo.setCurrentIndex(0)
        self._active_tool_combo.setStyleSheet(
            "QComboBox { padding: 4px; font-weight: bold; }"
        )
        tool_row.addWidget(self._active_tool_combo, stretch=1)
        layout.addLayout(tool_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_w = QWidget()
        grid = QGridLayout(scroll_w)

        for col, header in enumerate(["Tool", "Color", "Width", "Style"]):
            lbl = QLabel(header)
            lbl.setStyleSheet("font-weight: bold; color: #cccccc;")
            grid.addWidget(lbl, 0, col)

        self._color_buttons = {}
        self._width_combos = {}
        self._style_combos = {}

        for idx, key in enumerate(self._TOOL_ORDER):
            row = idx + 1
            style = self._styles.get(key, {"color": (1, 0, 0), "width": 2, "style": "solid"})

            grid.addWidget(QLabel(self._TOOL_DISPLAY_NAMES.get(key, key)), row, 0)

            color_btn = QPushButton()
            color_btn.setFixedSize(40, 24)
            qc = self._vtk_to_q(style["color"])
            color_btn.setStyleSheet(
                f"background-color: {qc.name()}; border: 2px solid #fff; border-radius: 4px;"
            )
            color_btn.setCursor(Qt.PointingHandCursor)
            color_btn.clicked.connect(lambda checked=False, k=key: self._pick_color(k))
            self._color_buttons[key] = color_btn
            grid.addWidget(color_btn, row, 1)

            w_combo = QComboBox()
            w_combo.addItems([str(i) for i in range(1, 11)])
            w_combo.setCurrentText(str(style.get("width", 2)))
            self._width_combos[key] = w_combo
            grid.addWidget(w_combo, row, 2)

            s_combo = QComboBox()
            s_combo.addItems(["solid", "dashed", "dotted", "dash-dot", "dash-dot-dot"])
            s_combo.setCurrentText(style.get("style", "solid"))
            self._style_combos[key] = s_combo
            grid.addWidget(s_combo, row, 3)

        scroll.setWidget(scroll_w)
        layout.addWidget(scroll, stretch=1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _pick_color(self, tool_key):
        from PySide6.QtWidgets import QColorDialog
        cur = self._vtk_to_q(self._styles.get(tool_key, {}).get("color", (1, 0, 0)))
        color = QColorDialog.getColor(cur, self, f"Choose color for {tool_key}")
        if color.isValid():
            self._styles[tool_key]["color"] = self._q_to_vtk(color)
            self._color_buttons[tool_key].setStyleSheet(
                f"background-color: {color.name()}; border: 2px solid #fff; border-radius: 4px;"
            )

    def get_preset(self) -> dict:
        tools = {}
        for key in self._TOOL_ORDER:
            tools[key] = {
                "color": self._styles.get(key, {}).get("color", (1, 0, 0)),
                "width": int(self._width_combos[key].currentText()),
                "style": self._style_combos[key].currentText(),
            }
        active_tool = self._active_tool_combo.currentData() or self._TOOL_ORDER[0]
        return {"active_tool": active_tool, "tools": tools}

    def set_preset(self, preset: dict):
        active = preset.get("active_tool", self._TOOL_ORDER[0])
        idx = self._active_tool_combo.findData(active)
        if idx >= 0:
            self._active_tool_combo.setCurrentIndex(idx)

        tools = preset.get("tools", {})
        for key in self._TOOL_ORDER:
            if key not in tools:
                continue
            style = tools[key]
            self._styles[key] = dict(style)
            qc = self._vtk_to_q(style.get("color", (1, 0, 0)))
            self._color_buttons[key].setStyleSheet(
                f"background-color: {qc.name()}; border: 2px solid #fff; border-radius: 4px;"
            )
            self._width_combos[key].setCurrentText(str(style.get("width", 2)))
            self._style_combos[key].setCurrentText(style.get("style", "solid"))


_COL_WIDTHS_KEY  = "display_preset_picker/column_widths"
_GEOMETRY_KEY    = "display_preset_picker/geometry"
_DEFAULT_WIDTHS = [57, 79, 122, 147, 112, 213]


class ClassVisibilityPicker(QDialog):
    settings_changed = Signal(dict)

    @staticmethod
    def _load_col_widths():
        s = QSettings("NakshaAI", "LidarApp")
        raw = s.value(_COL_WIDTHS_KEY, None)
        if raw and isinstance(raw, list) and len(raw) == 6:
            try:
                widths = [int(w) for w in raw]
                if all(w >= 20 for w in widths):
                    return widths
            except (ValueError, TypeError):
                pass
        return list(_DEFAULT_WIDTHS)

    @staticmethod
    def _save_col_widths(widths):
        QSettings("NakshaAI", "LidarApp").setValue(_COL_WIDTHS_KEY, widths)

    def __init__(self, app_window, mode="display", parent=None):
        super().__init__(parent)
        self.app_window  = app_window
        self.mode        = mode
        self._col_resize_blocked = False

        from PySide6.QtWidgets import (
            QGroupBox, QSpinBox, QDoubleSpinBox, QGridLayout, QScrollArea
        )
        self.setProperty("themeStyledDialog", True)
        self.setWindowTitle(f"Configure {mode.title()} Mode Preset")
        self.setModal(False)
        self.setWindowFlags(Qt.Window)

        s = QSettings("NakshaAI", "LidarApp")
        saved_geo = s.value(_GEOMETRY_KEY)
        if saved_geo:
            self.restoreGeometry(saved_geo)
        else:
            self.resize(820, 620)
            self.setMinimumSize(720, 500)

        from PySide6.QtWidgets import QApplication
        QApplication.instance().installEventFilter(self)

        layout = QVBoxLayout(self)

        if mode == "shading":
            shading_group = QGroupBox("Shading Parameters")
            shading_layout = QGridLayout()

            shading_layout.addWidget(QLabel("Azimuth (°):"), 0, 0)
            self.az_spin = QDoubleSpinBox()
            self.az_spin.setRange(0, 360); self.az_spin.setValue(45.0)
            shading_layout.addWidget(self.az_spin, 0, 1)

            shading_layout.addWidget(QLabel("Angle (°):"), 1, 0)
            self.angle_spin = QDoubleSpinBox()
            self.angle_spin.setRange(0, 90); self.angle_spin.setValue(45.0)
            shading_layout.addWidget(self.angle_spin, 1, 1)

            shading_layout.addWidget(QLabel("Ambient:"), 2, 0)
            self.ambient_spin = QDoubleSpinBox()
            self.ambient_spin.setRange(0, 1); self.ambient_spin.setValue(0.1)
            shading_layout.addWidget(self.ambient_spin, 2, 1)

            shading_layout.addWidget(QLabel("Quality (%):"), 3, 0)
            self.quality_spin = QDoubleSpinBox()
            self.quality_spin.setRange(0, 100); self.quality_spin.setValue(100.0)
            shading_layout.addWidget(self.quality_spin, 3, 1)

            shading_layout.addWidget(QLabel("Speed:"), 4, 0)
            self.speed_spin = QSpinBox()
            self.speed_spin.setRange(1, 10); self.speed_spin.setValue(1)
            shading_layout.addWidget(self.speed_spin, 4, 1)

            shading_group.setLayout(shading_layout)
            layout.addWidget(shading_group)

        self.class_checkboxes  = {}
        self.weight_spinboxes  = {}

        if mode != "display":
            scroll_widget = QWidget()
            self.class_grid = QGridLayout(scroll_widget)
            self.class_grid.setColumnStretch(1, 1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(scroll_widget)
            layout.addWidget(scroll, stretch=1)

            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            self.ok_btn     = QPushButton("OK")
            self.cancel_btn = QPushButton("Cancel")
            btn_layout.addWidget(self.ok_btn)
            btn_layout.addWidget(self.cancel_btn)
            layout.addLayout(btn_layout)

            self.ok_btn.clicked.connect(self._on_ok_clicked)
            self.cancel_btn.clicked.connect(self.reject)
            self._populate_classes()
        else:
            self._rebuild_display_mode_ui(layout)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.WindowActivate and self.isVisible():
            activated = obj
            is_self   = (activated is self)
            is_parent = (self.parent() and activated is self.parent())
            if not is_self and not is_parent:
                if hasattr(activated, 'isWindow') and activated.isWindow():
                    self.hide()
        return super().eventFilter(obj, event)
    
    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                event.ignore()
                self.setWindowState(Qt.WindowNoState)
                self.hide()
                return
        super().changeEvent(event)

    def closeEvent(self, event):
        QSettings("NakshaAI", "LidarApp").setValue(
            _GEOMETRY_KEY, self.saveGeometry()
        )
        self._persist_col_widths()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.setStyleSheet(get_dialog_stylesheet())
        s = QSettings("NakshaAI", "LidarApp")
        saved_geo = s.value(_GEOMETRY_KEY)
        if saved_geo:
            self.restoreGeometry(saved_geo)
        if self.parent():
            parent_geo = self.parent().geometry()
            self.move(parent_geo.x() + parent_geo.width() + 10, parent_geo.y())

    def _on_column_resized(self, logical_index, old_size, new_size):
        if self._col_resize_blocked:
            return
        if not hasattr(self, '_col_save_timer'):
            from PySide6.QtCore import QTimer
            self._col_save_timer = QTimer(self)
            self._col_save_timer.setSingleShot(True)
            self._col_save_timer.timeout.connect(self._persist_col_widths)
        self._col_save_timer.start(800)

    def _persist_col_widths(self):
        if not hasattr(self, 'class_table') or self.class_table is None:
            return
        widths = [self.class_table.columnWidth(c)
                for c in range(self.class_table.columnCount())]
        QSettings("NakshaAI", "LidarApp").setValue(_COL_WIDTHS_KEY, widths)
        print(f"💾 Column widths saved: {widths}")

    def _rebuild_display_mode_ui(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            cl = item.layout()
            if w:
                w.deleteLater()
            elif cl:
                while cl.count():
                    ci = cl.takeAt(0)
                    cw = ci.widget()
                    if cw:
                        cw.deleteLater()

        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        intro = QLabel(
            "Save a Display Mode preset: target view, class visibility, weights, and border."
        )
        intro.setObjectName("dialogInlineNote")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(10)

        controls_row.addWidget(QLabel("Target View:"))
        self.view_selector = QComboBox()
        self.view_selector.setMinimumWidth(130)
        self.view_selector.addItems([
            "Main View", "View 1", "View 2",
            "View 3", "View 4", "Cut Section View"
        ])
        self.view_selector.setCurrentIndex(0)
        self.view_selector.currentIndexChanged.connect(self._on_view_selector_changed)
        controls_row.addWidget(self.view_selector)

        controls_row.addSpacing(12)
        controls_row.addWidget(QLabel("Border %:"))

        self.border_spin = QDoubleSpinBox()
        self.border_spin.setRange(0, 100)
        self.border_spin.setDecimals(2)
        self.border_spin.setValue(0)
        self.border_spin.setSingleStep(5.0)
        self.border_spin.setFixedWidth(85)
        controls_row.addWidget(self.border_spin)
        controls_row.addStretch()
        layout.addLayout(controls_row)

        table_note = QLabel("Choose which classes this preset should display:")
        table_note.setObjectName("dialogInlineNote")
        layout.addWidget(table_note)

        table_and_btns = QHBoxLayout()
        table_and_btns.setSpacing(8)

        self.class_table = QTableWidget(0, 6)
        self.class_table.setObjectName("displayClassTable")
        self.class_table.setHorizontalHeaderLabels(
            ["Show", "Code", "Description", "Lvl", "Color", "Weight"]
        )
        self.class_table.setAlternatingRowColors(True)
        self.class_table.verticalHeader().setVisible(False)
        self.class_table.verticalHeader().setDefaultSectionSize(34)
        self.class_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.class_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.class_table.setFocusPolicy(Qt.NoFocus)
        self.class_table.setWordWrap(False)
        self.class_table.setShowGrid(False)

        hdr = self.class_table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignCenter)
        hdr.setHighlightSections(False)
        hdr.setStretchLastSection(True)

        for col in range(6):
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)

        widths = self._load_col_widths()
        self._col_resize_blocked = True
        for col, w in enumerate(widths):
            self.class_table.setColumnWidth(col, w)
        self._col_resize_blocked = False
        print(f"✅ Column widths restored: {widths}")

        hdr.sectionResized.connect(self._on_column_resized)

        table_and_btns.addWidget(self.class_table, stretch=1)

        action_col = QVBoxLayout()
        action_col.setContentsMargins(0, 0, 0, 0)
        action_col.setSpacing(6)

        self.refresh_btn    = QPushButton("Refresh")
        self.select_all_btn = QPushButton("Select All")
        self.clear_all_btn  = QPushButton("Clear All")
        for btn in (self.refresh_btn, self.select_all_btn, self.clear_all_btn):
            btn.setObjectName("displayActionButton")
            btn.setMinimumHeight(30)
            btn.setFixedWidth(80)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setFocusPolicy(Qt.NoFocus)
            action_col.addWidget(btn)
        action_col.addStretch()
        table_and_btns.addLayout(action_col)

        layout.addLayout(table_and_btns, stretch=1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.ok_btn     = QPushButton("OK")
        self.ok_btn.setObjectName("primaryBtn")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("secondaryBtn")
        for btn in (self.ok_btn, self.cancel_btn):
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setFocusPolicy(Qt.NoFocus)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        self.refresh_btn.clicked.connect(self._refresh_classes)
        self.select_all_btn.clicked.connect(self._select_all)
        self.clear_all_btn.clicked.connect(self._clear_all)
        self.ok_btn.clicked.connect(self._on_ok_clicked)
        self.cancel_btn.clicked.connect(self.reject)

        self.class_checkboxes = {}
        self.weight_spinboxes = {}
        self._populate_classes()

    def _refresh_classes(self):
        print(f"\n🔄 REFRESH CLASSES CALLED")
        current_selections = {}
        current_weights = {}
        
        if self.mode == "display" and hasattr(self, 'view_configs') and hasattr(self, 'view_selector'):
            current_view_idx = self.view_selector.currentIndex()
            if current_view_idx in self.view_configs:
                for code, config in self.view_configs[current_view_idx].items():
                    current_selections[code] = config.get("show", True)
                    current_weights[code] = config.get("weight", 1.0)
            else:
                for code, checkbox in self.class_checkboxes.items():
                    current_selections[code] = checkbox.isChecked()
                    if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                        current_weights[code] = self.weight_spinboxes[code].value()
        else:
            for code, checkbox in self.class_checkboxes.items():
                current_selections[code] = checkbox.isChecked()
                if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                    current_weights[code] = self.weight_spinboxes[code].value()
        
        self._populate_classes()
        
        for code, is_checked in current_selections.items():
            if code in self.class_checkboxes:
                self.class_checkboxes[code].setChecked(is_checked)
        
        for code, weight in current_weights.items():
            if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                self.weight_spinboxes[code].setValue(weight)
        
        print(f"✅ Refreshed {len(self.class_checkboxes)} classes from Display Mode with preserved states")
        
    def _populate_classes(self):
        if hasattr(self, 'class_table') and self.class_table is not None:
            self.class_table.setRowCount(0)
            self.class_checkboxes.clear()
            self.weight_spinboxes = {}

            if not hasattr(self.app_window, 'class_palette') or not self.app_window.class_palette:
                return

            current_view_idx = 0
            has_preset_data  = False
            preset_data      = {}

            if self.mode == "display" and hasattr(self, 'view_selector'):
                current_view_idx = self.view_selector.currentIndex()

            if (self.mode == "display"
                    and hasattr(self, 'view_configs')
                    and current_view_idx in self.view_configs):
                has_preset_data = True
                preset_data     = self.view_configs[current_view_idx]

            for code, entry in sorted(self.app_window.class_palette.items()):
                row = self.class_table.rowCount()
                self.class_table.insertRow(row)

                default_checked = True
                if has_preset_data and code in preset_data:
                    default_checked = preset_data[code].get("show", True)

                checkbox = QCheckBox()
                checkbox.setChecked(default_checked)
                checkbox.setFocusPolicy(Qt.NoFocus)
                checkbox.setCursor(Qt.PointingHandCursor)
                checkbox.setStyleSheet("QCheckBox { background: transparent; }")

                cb_holder = QWidget()
                cb_holder.setAttribute(Qt.WA_TranslucentBackground, True)
                cb_holder.setStyleSheet("background: transparent;")
                cb_layout = QHBoxLayout(cb_holder)
                cb_layout.setContentsMargins(0, 0, 0, 0)
                cb_layout.setAlignment(Qt.AlignCenter)
                cb_layout.addWidget(checkbox)
                self.class_table.setCellWidget(row, 0, cb_holder)
                self.class_checkboxes[code] = checkbox

                code_item = QTableWidgetItem(str(code))
                code_item.setTextAlignment(Qt.AlignCenter)
                self.class_table.setItem(row, 1, code_item)

                desc_item = QTableWidgetItem(entry.get("description", f"Class {code}"))
                desc_item.setToolTip(desc_item.text())
                self.class_table.setItem(row, 2, desc_item)

                lvl_item = QTableWidgetItem(str(entry.get("lvl", "") or "-"))
                lvl_item.setTextAlignment(Qt.AlignCenter)
                lvl_item.setToolTip(lvl_item.text())
                self.class_table.setItem(row, 3, lvl_item)

                color = entry.get("color", (128, 128, 128))
                self._set_class_color_cell(row, color)

                default_weight = 1.0
                if has_preset_data and code in preset_data:
                    default_weight = preset_data[code].get("weight", 1.0)

                weight_spin = QDoubleSpinBox()
                weight_spin.setRange(0.1, 10.0)
                weight_spin.setDecimals(2)
                weight_spin.setSingleStep(0.1)
                weight_spin.setAlignment(Qt.AlignCenter)
                weight_spin.setFixedWidth(72)
                weight_spin.setValue(default_weight)
                weight_spin.setStyleSheet(
                    "QDoubleSpinBox { background: transparent; border: none; }"
                    "QDoubleSpinBox:focus { border: 1px solid #007acc; border-radius:3px; }"
                )
                weight_spin.valueChanged.connect(
                    lambda val, c=code: self._on_weight_changed(c, val)
                )

                w_holder = QWidget()
                w_holder.setAttribute(Qt.WA_TranslucentBackground, True) 
                w_holder.setStyleSheet("background: transparent;")
                w_layout = QHBoxLayout(w_holder)
                w_layout.setContentsMargins(0, 0, 0, 0)
                w_layout.setAlignment(Qt.AlignCenter)
                w_layout.addWidget(weight_spin)
                self.class_table.setCellWidget(row, 5, w_holder)
                self.weight_spinboxes[code] = weight_spin

            if self.mode == "display":
                if not hasattr(self, 'view_configs'):
                    self.view_configs = {}
                self._last_view_idx = (
                    self.view_selector.currentIndex()
                    if hasattr(self, 'view_selector') else 0
                )

            print(f"✅ Populated {len(self.class_checkboxes)} classes"
                f"{' from preset' if has_preset_data else ' (defaults)'}")
            return

        for i in reversed(range(self.class_grid.count())):
            w = self.class_grid.itemAt(i).widget()
            if w:
                w.deleteLater()
        self.class_checkboxes.clear()

        if not hasattr(self.app_window, 'class_palette'):
            self.class_grid.addWidget(
                QLabel("⚠️ No class data. Load a point cloud first."), 0, 0, 1, 5
            )
            return

        row = 0
        self.weight_spinboxes = {}
        current_view_idx = 0
        has_preset_data  = False
        preset_data      = {}

        if self.mode == "display" and hasattr(self, 'view_selector'):
            current_view_idx = self.view_selector.currentIndex()
        if (self.mode == "display"
                and hasattr(self, 'view_configs')
                and current_view_idx in self.view_configs):
            has_preset_data = True
            preset_data     = self.view_configs[current_view_idx]

        for code, entry in sorted(self.app_window.class_palette.items()):
            desc  = entry.get("description", f"Class {code}")
            color = entry.get("color", (128, 128, 128))

            checkbox = QCheckBox()
            default_checked = True
            if has_preset_data and code in preset_data:
                default_checked = preset_data[code].get("show", True)
            checkbox.setChecked(default_checked)
            checkbox.setStyleSheet("background: transparent;")
            self.class_checkboxes[code] = checkbox
            self.class_grid.addWidget(checkbox, row, 0)

            r, g, b = color
            color_label = QLabel("█")
            color_label.setStyleSheet(f"color: rgb({r},{g},{b}); font-size:20px;")
            self.class_grid.addWidget(color_label, row, 1)

            self.class_grid.addWidget(QLabel(str(code)), row, 2)
            self.class_grid.addWidget(QLabel(desc), row, 3)

            weight_spin = QDoubleSpinBox()
            weight_spin.setRange(0.1, 10.0); weight_spin.setSingleStep(0.1)
            weight_spin.setMinimumWidth(70)
            default_weight = 1.0
            if has_preset_data and code in preset_data:
                default_weight = preset_data[code].get("weight", 1.0)
            weight_spin.setValue(default_weight)
            weight_spin.valueChanged.connect(
                lambda val, c=code: self._on_weight_changed(c, val))
            self.class_grid.addWidget(weight_spin, row, 4)
            self.weight_spinboxes[code] = weight_spin

            row += 1

        print(f"✅ Populated {len(self.class_checkboxes)} classes (grid mode)")

        if self.mode == "display":
            if not hasattr(self, 'view_configs'):
                self.view_configs = {}
            self._last_view_idx = (
                self.view_selector.currentIndex()
                if hasattr(self, 'view_selector') else 0
            )
        
    def _set_class_color_cell(self, row, color):
        if not hasattr(self, 'class_table') or self.class_table is None:
            return

        qcolor = QColor(*color) if isinstance(color, tuple) else QColor(color)
        border_color = qcolor.darker(145)

        swatch = QFrame()
        swatch.setFixedSize(52, 18)
        swatch.setStyleSheet(
            f"background-color: rgb({qcolor.red()},{qcolor.green()},{qcolor.blue()});"
            f"border: 1px solid {border_color.name()};"
            "border-radius: 5px;"
        )
        swatch.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setAlignment(Qt.AlignCenter)
        holder_layout.addWidget(swatch)
        self.class_table.setCellWidget(row, 4, holder)

    def _select_all(self):
        for checkbox in self.class_checkboxes.values():
            checkbox.setChecked(True)
    
    def _clear_all(self):
        for checkbox in self.class_checkboxes.values():
            checkbox.setChecked(False)
    
    def get_selected_classes(self):
        result = {}
        for code, checkbox in self.class_checkboxes.items():
            if code in self.app_window.class_palette:
                entry = self.app_window.class_palette[code]
                weight = 1.0
                if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                    weight = self.weight_spinboxes[code].value()
                result[code] = {
                    "show": checkbox.isChecked(),
                    "description": entry.get("description", ""),
                    "color": entry.get("color", (128, 128, 128)),
                    "weight": weight,
                    "draw": entry.get("draw", ""),
                    "lvl": entry.get("lvl", "")
                }
        return result
    
    def get_shading_parameters(self):
        if self.mode != "shading":
            return {}
        return {
            "azimuth": self.az_spin.value(),
            "angle": self.angle_spin.value(),
            "ambient": self.ambient_spin.value(),
            "quality": self.quality_spin.value(),
            "speed": self.speed_spin.value()
        }
    
    def set_selected_classes(self, classes_dict):
        for code, checkbox in self.class_checkboxes.items():
            if code in classes_dict:
                is_visible = classes_dict[code].get("show", True)
                checkbox.setChecked(is_visible)
    
    def set_shading_parameters(self, params):
        if self.mode != "shading":
            return
        self.az_spin.setValue(params.get("azimuth", 45.0))
        self.angle_spin.setValue(params.get("angle", 45.0))
        self.ambient_spin.setValue(params.get("ambient", 0.1))
        self.quality_spin.setValue(params.get("quality", 100.0))
        self.speed_spin.setValue(params.get("speed", 1))
    
    def get_target_view(self):
        if self.mode == "display" and hasattr(self, 'view_selector'):
            return self.view_selector.currentIndex()
        return 0
    
    def set_target_view(self, view_idx):
        if self.mode == "display" and hasattr(self, 'view_selector'):
            if 0 <= view_idx < self.view_selector.count():
                self.view_selector.setCurrentIndex(view_idx)
                
    def _on_weight_changed(self, code, value):
        if self.mode == "display" and hasattr(self, 'view_selector'):
            current_view_idx = self.view_selector.currentIndex()
            if not hasattr(self, 'view_configs'):
                self.view_configs = {}
            if current_view_idx not in self.view_configs:
                self.view_configs[current_view_idx] = {}
            if code in self.view_configs[current_view_idx]:
                self.view_configs[current_view_idx][code]["weight"] = value
            else:
                self.view_configs[current_view_idx][code] = {"weight": value}

    def _sync_from_display_mode(self):
        if hasattr(self.app_window, 'display_border_percent'):
            self.border_spin.setValue(self.app_window.display_border_percent)
        for code, entry in self.app_window.class_palette.items():
            if code in self.weight_spinboxes:
                weight = entry.get("weight", 1.0)
                self.weight_spinboxes[code].setValue(weight)

    def _sync_border(self):
        if hasattr(self.app_window, 'display_border_percent'):
            self.border_spin.setValue(self.app_window.display_border_percent)
        
    def get_all_view_configs(self):
        if not hasattr(self, 'view_configs'):
            self.view_configs = {}
        
        selected_view_idx = 0
        if hasattr(self, 'view_selector'):
            selected_view_idx = self.view_selector.currentIndex()
        
        result = {
            "border_percent": self.border_spin.value() if hasattr(self, 'border_spin') else 0,
            "views": {}
        }
        
        if selected_view_idx in self.view_configs:
            result["views"][selected_view_idx] = self.view_configs[selected_view_idx]
        
        return result
    
    def _on_ok_clicked(self):
        if self.mode == "display" and hasattr(self, 'view_selector'):
            selected_view_idx = self.view_selector.currentIndex()
            
            config = {}
            for code, checkbox in self.class_checkboxes.items():
                if code in self.app_window.class_palette:
                    entry = self.app_window.class_palette[code]
                    actual_weight = 1.0
                    if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                        actual_weight = self.weight_spinboxes[code].value()
                    config[code] = {
                        "show": checkbox.isChecked(),
                        "weight": actual_weight,
                        "description": entry.get("description", ""),
                        "color": entry.get("color", (128, 128, 128)),
                        "draw": entry.get("draw", ""),
                        "lvl": entry.get("lvl", "")
                    }
            
            if not hasattr(self, 'view_configs'):
                self.view_configs = {}
            self.view_configs[selected_view_idx] = config
        
        if self.mode == "display" and hasattr(self, 'border_spin'):
            border_val = self.border_spin.value()
            self.app_window.display_border_percent = border_val
        
        self.accept()
        
    def _on_view_selector_changed(self, new_index):
        print(f"\n📍 View selector changed to index {new_index}")

        if hasattr(self, '_last_view_idx') and hasattr(self, 'view_configs'):
            old_idx = self._last_view_idx
            config = {}
            for code, checkbox in self.class_checkboxes.items():
                if code in self.app_window.class_palette:
                    entry = self.app_window.class_palette[code]
                    weight = 1.0
                    if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                        weight = self.weight_spinboxes[code].value()
                    config[code] = {
                        "show": checkbox.isChecked(),
                        "weight": weight,
                        "description": entry.get("description", ""),
                        "color": entry.get("color", (128, 128, 128)),
                        "draw": entry.get("draw", ""),
                        "lvl": entry.get("lvl", ""),
                    }
            self.view_configs[old_idx] = config

        self._last_view_idx = new_index

        if not hasattr(self, 'view_configs'):
            self.view_configs = {}

        if new_index in self.view_configs:
            print(f"   ✅ Using cached config for view {new_index}")
        else:
            parent_sm = self.parent()
            live_classes = None
            live_border = 0
            if parent_sm and hasattr(parent_sm, '_get_live_display_state_for_view'):
                live_classes, live_border = parent_sm._get_live_display_state_for_view(new_index)

            if live_classes:
                self.view_configs[new_index] = live_classes
                if hasattr(self, 'border_spin'):
                    self.border_spin.setValue(live_border)
            
        self._populate_classes()

        if new_index in self.view_configs:
            for code, checkbox in self.class_checkboxes.items():
                if code in self.view_configs[new_index]:
                    checkbox.setChecked(self.view_configs[new_index][code].get("show", True))
            if hasattr(self, 'weight_spinboxes'):
                for code, spin in self.weight_spinboxes.items():
                    if code in self.view_configs[new_index]:
                        spin.setValue(self.view_configs[new_index][code].get("weight", 1.0))

    def sync_from_app(self):
        if self.mode != "shading":
            return
        try:
            self.az_spin.setValue(getattr(self.app_window, 'last_shade_azimuth', 45.0))
            self.angle_spin.setValue(getattr(self.app_window, 'last_shade_angle', 45.0))
            self.ambient_spin.setValue(getattr(self.app_window, 'shade_ambient', 0.25))
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# ShortcutManager — Select column REMOVED, row-header right-click added
# ═══════════════════════════════════════════════════════════════════
class ShortcutManager(QWidget):
    applied = Signal(dict)
    instance = None

    # ── Column indices (NO Select column) ──────────────────────────
    # COL_CHECK is hidden by default; shown only when select mode is active
    COL_CHECK    = 0
    COL_MODIFIER = 1
    COL_KEY      = 2
    COL_TOOL     = 3
    COL_CLASSES  = 4
   
    def __init__(self, app_window, parent=None):
        from PySide6.QtWidgets import QWidget
        target_parent = None
       
        if parent and isinstance(parent, QWidget):
            target_parent = parent
        elif isinstance(app_window, QWidget):
            target_parent = app_window
        elif hasattr(app_window, 'window') and isinstance(app_window.window, QWidget):
            target_parent = app_window.window
 
        super().__init__(target_parent)
        self.setProperty("themeStyledDialog", True)
        self.setWindowTitle("Configure Shortcuts")
        self.setWindowFlags(Qt.Window)
        self.resize(900, 560)
 
        self.app_window = app_window
        self.app_window.shortcut_manager = self

        self.current_mnu_path = None
        self.settings = QSettings("NakshaAI", "LidarApp")

        # ── Tracks select mode and which rows are checked ────────────
        self._selected_rows: set = set()
        self._select_mode: bool  = False
       
        self.setStyleSheet(get_dialog_stylesheet())
 
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        intro = QLabel(
            "Configure shortcut keys and attach saved Display Mode, Shading Mode, Draw Settings, or class presets."
        )
        intro.setObjectName("dialogInlineNote")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        selection_hint = QLabel(
            "Right-click a row number to select/delete rows. Double-click the Classes cell to configure a preset."
        )
        selection_hint.setObjectName("dialogInlineNote")
        selection_hint.setWordWrap(True)
        layout.addWidget(selection_hint)
 
        # ── Table: 5 columns (col 0 = checkbox, hidden until select mode) ──
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("displayClassTable")
        self.table.setHorizontalHeaderLabels(["", "Modifier", "Key", "Tool", "Classes"])
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)

        # Vertical header — row numbers that turn into checkboxes when selected
        vhdr = self.table.verticalHeader()
        vhdr.setVisible(True)
        vhdr.setDefaultSectionSize(38)
        vhdr.setFixedWidth(36)
        vhdr.setDefaultAlignment(Qt.AlignCenter)
        vhdr.setStyleSheet("QHeaderView::section { font-weight: normal; font-size: 11px; }")
        vhdr.setContextMenuPolicy(Qt.CustomContextMenu)
        vhdr.customContextMenuRequested.connect(self._show_row_header_context_menu)

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        # ── No hover highlight; scroll only via wheel/scrollbar ───────
        self.table.setStyleSheet("""
            QTableWidget {
                padding-bottom: 0px;
            }
            QTableWidget::item {
                padding: 3px;
            }
            QTableWidget::item:hover {
                background: transparent;
            }
        """)

        layout.addWidget(self.table, stretch=1)
        layout.addSpacing(25)

        header = self.table.horizontalHeader()
        # Col 0: checkbox column — fixed, hidden until select mode activates
        header.setSectionResizeMode(self.COL_CHECK,    QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_CHECK, 32)
        self.table.setColumnHidden(self.COL_CHECK, True)
        header.setSectionResizeMode(self.COL_MODIFIER, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_KEY,      QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_TOOL,     QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_CLASSES,  QHeaderView.ResizeMode.Stretch)
 
        # ── Buttons ───────────────────────────────────────────────────
        btns = QHBoxLayout()
        self.add_btn    = QPushButton("Add");         self.add_btn.setObjectName("displayActionButton")
        self.del_btn    = QPushButton("Delete Selected"); self.del_btn.setObjectName("displayActionButton")
        self.del_btn.setToolTip("Deletes selected rows (right-click row number to select).")
        self.load_btn   = QPushButton("Load");        self.load_btn.setObjectName("displayActionButton")
        self.save_btn   = QPushButton("Save As...");  self.save_btn.setObjectName("displayActionButton")
        self.apply_btn  = QPushButton("Apply");       self.apply_btn.setObjectName("primaryBtn")
        self.cancel_btn = QPushButton("Close");       self.cancel_btn.setObjectName("secondaryBtn")
        self.cancel_btn.clicked.connect(self.close)
        
        for b in [self.add_btn, self.del_btn, self.load_btn, self.save_btn, self.apply_btn, self.cancel_btn]:
            b.setMinimumHeight(36)
            b.setAutoDefault(False)
            b.setDefault(False)
            b.setFocusPolicy(Qt.NoFocus)
            btns.addWidget(b)
        layout.addLayout(btns)
 
        self.add_btn.clicked.connect(self.on_add)
        self.del_btn.clicked.connect(self.on_delete)
        self.load_btn.clicked.connect(self.load_mnu)
        self.save_btn.clicked.connect(self.save_mnu_as)
        self.apply_btn.clicked.connect(self.on_apply)
 
        self.table.cellDoubleClicked.connect(self.on_class_edit)
        self.table.itemClicked.connect(self.on_item_clicked)
 
        self._active_row = None
        self.is_editing_shortcuts = False
        self._pending_display_mode_row = None
        self._is_loading_shortcuts = False
        self.auto_load_shortcuts()

    # ── Modifier / Key options ────────────────────────────────────────
    def _modifier_options(self):
        return [
            "alt", "ctrl", "shift",
            "alt+shift", "ctrl+alt",
            "ctrl+shift", "ctrl+alt+shift", "none"
        ]

    def _key_options(self):
        keys = [f"F{i}" for i in range(1, 13)]
        keys += [chr(i) for i in range(65, 91)]
        keys.append("Space")
        return keys

    # ─────────────────────────────────────────────────────────────────
    # ROW SELECTION helpers (replaces the old Select-column checkboxes)
    # ─────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────
    # CHECKBOX COLUMN helpers
    # ─────────────────────────────────────────────────────────────────
    def _get_row_checkbox(self, row):
        """Return the QCheckBox widget in col 0 for the given row, or None."""
        holder = self.table.cellWidget(row, self.COL_CHECK)
        return getattr(holder, '_cb', None) if holder else None

    def _install_row_checkbox(self, row, checked=False):
        """Put a real QCheckBox into col 0.  Only visible when select mode is on."""
        cb = QCheckBox()
        cb.setChecked(checked)
        cb.setFocusPolicy(Qt.NoFocus)
        cb.setCursor(Qt.PointingHandCursor)

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(cb)
        holder._cb = cb

        cb.toggled.connect(lambda state, r=row: self._on_checkbox_toggled(r, state))
        self.table.setCellWidget(row, self.COL_CHECK, holder)

    def _on_checkbox_toggled(self, row, checked):
        if checked:
            self._selected_rows.add(row)
        else:
            self._selected_rows.discard(row)

    def _checked_rows(self) -> list:
        """Return rows whose checkbox is checked."""
        rows = []
        for r in range(self.table.rowCount()):
            cb = self._get_row_checkbox(r)
            if cb and cb.isChecked():
                rows.append(r)
        return sorted(rows)

    # ─────────────────────────────────────────────────────────────────
    # SELECT MODE  on / off
    # ─────────────────────────────────────────────────────────────────
    def _activate_select_mode(self):
        """Show the checkbox column — all rows get empty boxes ready to check."""
        self._select_mode = True
        # Make sure every existing row has a checkbox widget
        for r in range(self.table.rowCount()):
            if self._get_row_checkbox(r) is None:
                self._install_row_checkbox(r, checked=False)
            else:
                cb = self._get_row_checkbox(r)
                if cb:
                    cb.setChecked(False)   # reset to unchecked when mode opens
        self._selected_rows.clear()
        self.table.setColumnHidden(self.COL_CHECK, False)

    def _deactivate_select_mode(self):
        """Hide checkbox column and clear all selections."""
        self._select_mode = False
        self._selected_rows.clear()
        # Uncheck all
        for r in range(self.table.rowCount()):
            cb = self._get_row_checkbox(r)
            if cb:
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
        self.table.setColumnHidden(self.COL_CHECK, True)

    def _check_all_rows(self, state: bool):
        for r in range(self.table.rowCount()):
            cb = self._get_row_checkbox(r)
            if cb:
                cb.setChecked(state)

    # ─────────────────────────────────────────────────────────────────
    # VERTICAL HEADER right-click context menu
    # ─────────────────────────────────────────────────────────────────
    def _show_row_header_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        header = self.table.verticalHeader()
        row = header.logicalIndexAt(pos)

        menu = QMenu(self)

        if row >= 0:
            mod_combo  = self.table.cellWidget(row, self.COL_MODIFIER)
            key_combo  = self.table.cellWidget(row, self.COL_KEY)
            tool_combo = self.table.cellWidget(row, self.COL_TOOL)

            # Delete is always available
            act_delete = menu.addAction("Delete")
            act_delete.triggered.connect(lambda _=False, r=row: self._delete_selected_rows([r]))
            menu.addSeparator()

        if self._select_mode:
            # Select mode ON — show checkbox management options
            act_all   = menu.addAction("Select All")
            act_none  = menu.addAction("Deselect All")
            menu.addSeparator()
            act_deact = menu.addAction("Deactivate select mode")
            act_all.triggered.connect(lambda: self._check_all_rows(True))
            act_none.triggered.connect(lambda: self._check_all_rows(False))
            act_deact.triggered.connect(self._deactivate_select_mode)
        else:
            # Select mode OFF — offer to turn it on
            act_act = menu.addAction("Activate select mode")
            act_act.triggered.connect(self._activate_select_mode)

        menu.exec(header.viewport().mapToGlobal(pos))

    def _update_row_header(self, row: int):
        """Plain row number always — selection is shown via the checkbox column."""
        item = QTableWidgetItem(str(row + 1))
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(Qt.ItemIsEnabled)
        self.table.setVerticalHeaderItem(row, item)

    def _refresh_all_row_headers(self):
        for r in range(self.table.rowCount()):
            self._update_row_header(r)

    def _clear_selection(self):
        self._deactivate_select_mode()

    # ─────────────────────────────────────────────────────────────────
    def _get_selected_rows(self) -> list:
        checked = self._checked_rows()
        if checked:
            return checked
        current_row = self.table.currentRow()
        return [current_row] if current_row >= 0 else []

    def _set_current_row(self, row: int):
        if row >= 0:
            self.table.setCurrentCell(row, self.COL_CLASSES)

    def _install_row_widgets(self, row, modifier="alt", key="F1", tool="AboveLine"):
        """Install all widgets for a row, including the (hidden) checkbox in col 0."""
        self._install_row_checkbox(row)  # always create; shown only when select mode on
        mod_combo = QComboBox()
        mod_combo.addItems(self._modifier_options())
        mod_combo.setCurrentText(modifier)
        mod_combo.setFocusPolicy(Qt.StrongFocus)
        mod_combo.installEventFilter(self)
        mod_combo.currentTextChanged.connect(lambda _, r=row: self._on_key_changed(r))
        self.table.setCellWidget(row, self.COL_MODIFIER, mod_combo)

        key_combo = QComboBox()
        key_combo.addItems(self._key_options())
        key_combo.setCurrentText(key)
        key_combo.setFocusPolicy(Qt.StrongFocus)
        key_combo.installEventFilter(self)
        key_combo.currentTextChanged.connect(lambda _, r=row: self._on_key_changed(r))
        self.table.setCellWidget(row, self.COL_KEY, key_combo)

        tool_combo = QComboBox()
        tool_combo.addItems(TOOLS)
        tool_combo.blockSignals(True)
        tool_combo.setCurrentText(tool)
        tool_combo.blockSignals(False)
        tool_combo.setFocusPolicy(Qt.StrongFocus)
        tool_combo.installEventFilter(self)
        tool_combo.currentTextChanged.connect(lambda t, r=row: self._toggle_class_cell(r, t))
        self.table.setCellWidget(row, self.COL_TOOL, tool_combo)

        # Keep row header in sync
        self._update_row_header(row)

    # ─────────────────────────────────────────────────────────────────
    # TABLE BODY right-click (simplified — no checkbox column to toggle)
    # ─────────────────────────────────────────────────────────────────
    def _show_context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        clicked_item = self.table.itemAt(pos)
        clicked_row  = clicked_item.row() if clicked_item else -1

        menu = QMenu(self)

        sel_rows = self._get_selected_rows()
        if not sel_rows and clicked_row >= 0:
            sel_rows = [clicked_row]

        if sel_rows:
            if len(sel_rows) == 1:
                row = sel_rows[0]
                mc = self.table.cellWidget(row, self.COL_MODIFIER)
                kc = self.table.cellWidget(row, self.COL_KEY)
                tc = self.table.cellWidget(row, self.COL_TOOL)
                label = (f"Delete  {mc.currentText() if mc else '?'}+"
                         f"{kc.currentText() if kc else '?'} → "
                         f"{tc.currentText() if tc else '?'}")
            else:
                label = f"Delete {len(sel_rows)} selected shortcuts"

            act_delete = menu.addAction(label)
            act_delete.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_TrashIcon
            ))
            act_delete.triggered.connect(lambda: self._delete_selected_rows(sel_rows))
            menu.addSeparator()

        if self._select_mode:
            act_all  = menu.addAction("Select All")
            act_none = menu.addAction("Deselect All")
            menu.addSeparator()
            act_deact = menu.addAction("Deactivate select mode")
            act_all.triggered.connect(lambda: self._check_all_rows(True))
            act_none.triggered.connect(lambda: self._check_all_rows(False))
            act_deact.triggered.connect(self._deactivate_select_mode)
        else:
            act_act = menu.addAction("Activate select mode")
            act_act.triggered.connect(self._activate_select_mode)

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _delete_selected_rows(self, rows=None):
        sel_rows = sorted(set(rows if rows is not None else self._get_selected_rows()))
        if not sel_rows:
            return

        if len(sel_rows) == 1:
            row = sel_rows[0]
            mc = self.table.cellWidget(row, self.COL_MODIFIER)
            kc = self.table.cellWidget(row, self.COL_KEY)
            tc = self.table.cellWidget(row, self.COL_TOOL)
            msg = (f"Delete  {mc.currentText() if mc else '?'} + "
                   f"{kc.currentText() if kc else '?'}  →  "
                   f"{tc.currentText() if tc else '?'}?")
        else:
            lines = []
            for row in sel_rows:
                mc = self.table.cellWidget(row, self.COL_MODIFIER)
                kc = self.table.cellWidget(row, self.COL_KEY)
                tc = self.table.cellWidget(row, self.COL_TOOL)
                lines.append(
                    f"  • Row {row + 1}:  "
                    f"{mc.currentText() if mc else '?'}+"
                    f"{kc.currentText() if kc else '?'} → "
                    f"{tc.currentText() if tc else '?'}"
                )
            msg = f"Delete {len(sel_rows)} shortcuts?\n\n" + "\n".join(lines)

        reply = QMessageBox.question(
            self, "Delete shortcuts", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        for row in sorted(sel_rows, reverse=True):
            self.table.removeRow(row)

        # _selected_rows is synced via checkbox signals; just clear it and rebuild
        self._selected_rows.clear()
        for r in range(self.table.rowCount()):
            cb = self._get_row_checkbox(r)
            if cb and cb.isChecked():
                self._selected_rows.add(r)
        self._refresh_all_row_headers()

        new_row = min(min(sel_rows), self.table.rowCount() - 1)
        if new_row >= 0:
            self._set_current_row(new_row)

    def on_item_clicked(self, item):
        if item.column() == self.COL_CLASSES:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
 
    def _is_key_duplicate(self, mod, key, current_row):
        for row in range(self.table.rowCount()):
            if row == current_row:
                continue
            mod_combo = self.table.cellWidget(row, self.COL_MODIFIER)
            key_combo = self.table.cellWidget(row, self.COL_KEY)
            if mod_combo and key_combo:
                if (mod_combo.currentText().lower() == mod.lower() and
                        key_combo.currentText().upper() == key.upper()):
                    return True, row
        return False, -1
 
    def _on_key_changed(self, row):
        if self._is_loading_shortcuts:
            return
        mod_combo = self.table.cellWidget(row, self.COL_MODIFIER)
        key_combo = self.table.cellWidget(row, self.COL_KEY)
        if not mod_combo or not key_combo:
            return
        mod = mod_combo.currentText()
        key = key_combo.currentText()
        is_dup, dup_row = self._is_key_duplicate(mod, key, row)
        if is_dup:
            QMessageBox.warning(
                self, "Duplicate Shortcut",
                f"⚠️ {mod}+{key} is already assigned to row {dup_row + 1}!\n\n"
                "Each shortcut key can only be used once.\n"
                "Please choose a different key or modifier."
            )
            key_combo.setCurrentText("F1") 
 
    def on_add(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._install_row_widgets(row)
        # If select mode is already on, the new row's checkbox is already installed
        # and the column is visible — nothing extra needed.
        # If select mode is off, column stays hidden automatically.

        item = QTableWidgetItem("Any → Any")
        item.setData(Qt.UserRole, encode_classes(None, None))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, self.COL_CLASSES, item)
        self._set_current_row(row)

    @staticmethod
    def apply_shortcuts_from_settings(app_window):
        print(f"\n{'='*60}")
        print(f"⚡ RELOADING SHORTCUTS FROM SETTINGS (Ctrl+Shift+S)")
        print(f"{'='*60}")

        try:
            settings = QSettings("NakshaAI", "LidarApp")
            shortcuts_data = settings.value("shortcuts", None)

            if shortcuts_data is None:
                if hasattr(app_window, 'statusBar'):
                    app_window.statusBar().showMessage(
                        "⚠️ No shortcuts configured — open Shortcut Manager first", 3000
                    )
                return

            if isinstance(shortcuts_data, str):
                shortcuts_list = json.loads(shortcuts_data)
            else:
                shortcuts_list = shortcuts_data

            shortcuts = {}
            simple_tools = SIMPLE_SHORTCUT_TOOLS

            for entry in shortcuts_list:
                modifier  = entry.get("modifier", "alt")
                key       = entry.get("key", "F1")
                tool      = entry.get("tool", "AboveLine")
                mod       = modifier.lower()
                key_upper = key.upper()

                if tool == "DisplayMode":
                    preset_payload = entry.get("display_preset")
                    if preset_payload:
                        shortcuts[(mod, key_upper)] = {"tool": "DisplayMode", "preset": preset_payload}
                    continue

                if tool == "ShadingMode":
                    preset_payload = entry.get("shading_preset")
                    if preset_payload:
                        shortcuts[(mod, key_upper)] = {"tool": "ShadingMode", "preset": preset_payload}
                    continue

                if tool == "DrawSettings":
                    preset_payload = entry.get("draw_preset")
                    if preset_payload:
                        shortcuts[(mod, key_upper)] = {"tool": "DrawSettings", "preset": preset_payload}
                    continue

                if tool in simple_tools:
                    shortcuts[(mod, key_upper)] = {"tool": tool, "from": None, "to": None}
                else:
                    from_cls = entry.get("from_classes")
                    to_cls   = entry.get("to_class")
                    shortcuts[(mod, key_upper)] = {"tool": tool, "from": from_cls, "to": to_cls}

            app_window.shortcuts = shortcuts

            if hasattr(app_window, 'statusBar'):
                app_window.statusBar().showMessage(
                    f"✅ {len(shortcuts)} shortcuts reloaded (press key to apply)", 2500
                )

        except Exception as e:
            print(f"❌ apply_shortcuts_from_settings failed: {e}")
            import traceback
            traceback.print_exc()

    def on_delete(self):
        sel_rows = self._get_selected_rows()
        if not sel_rows:
            last = self.table.rowCount() - 1
            if last >= 0:
                self._set_current_row(last)
                sel_rows = [last]
            else:
                return
        self._delete_selected_rows(sel_rows)
            
    def eventFilter(self, obj, event):
        if isinstance(obj, QComboBox):
            if event.type() == QEvent.Wheel:
                event.ignore()
                return True
            if event.type() == QEvent.MouseButtonPress:
                for row in range(self.table.rowCount()):
                    for col in range(self.COL_MODIFIER, self.COL_TOOL + 1):
                        if self.table.cellWidget(row, col) is obj:
                            self._set_current_row(row)
                            break
        return super().eventFilter(obj, event)
    
    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                event.ignore()
                self.setWindowState(Qt.WindowNoState)
                self.hide()
                return
        super().changeEvent(event)       
 
    def _toggle_class_cell(self, row, tool_text):
        no_config_tools = SIMPLE_SHORTCUT_TOOLS
        
        if tool_text in no_config_tools:
            item = QTableWidgetItem("N/A")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_classes(None, None))
            self.table.setItem(row, self.COL_CLASSES, item)
            return

        if tool_text == "DisplayMode":
            item = QTableWidgetItem("Click/Double-click to configure display preset")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_display_preset({
                "classes": {}, "slot": 0, "target_view": 0,
                "color_mode": 0, "border_percent": 0, "force_refresh": True
            }))
            self.table.setItem(row, self.COL_CLASSES, item)
            if not self._is_loading_shortcuts:
                self._open_display_mode_for_row(row)
            return
        
        if tool_text == "ShadingMode":
            item = QTableWidgetItem("Preset: Not configured yet")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_shading_preset({
                "azimuth": 45.0, "angle": 45.0, "ambient": 0.1,
                "quality": 100.0, "speed": 1, "classes": {}
            }))
            self.table.setItem(row, self.COL_CLASSES, item)
            if not self._is_loading_shortcuts:
                self._open_shading_mode_for_row(row)
            return
        
        if tool_text == "DrawSettings":
            item = QTableWidgetItem("Click/Double-click to configure draw preset")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_draw_preset({"tools": {}}))
            self.table.setItem(row, self.COL_CLASSES, item)
            if not self._is_loading_shortcuts:
                self._open_draw_settings_for_row(row)
            return

        item = QTableWidgetItem("Any → Any")
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setData(Qt.UserRole, encode_classes(None, None))
        self.table.setItem(row, self.COL_CLASSES, item)

    def on_class_edit(self, row, col):
        if col != self.COL_CLASSES:
            return

        tool_combo = self.table.cellWidget(row, self.COL_TOOL)
        tool = tool_combo.currentText() if tool_combo else ""
        
        if tool in SIMPLE_SHORTCUT_TOOLS:
            return

        if tool == "DisplayMode":
            self._open_display_mode_for_row(row)
            return
        
        if tool == "ShadingMode":
            self._open_shading_mode_for_row(row)
            return
        
        if tool == "DrawSettings":
            self._open_draw_settings_for_row(row)
            return

        self._active_row = row
        self.is_editing_shortcuts = True

        if not hasattr(self.app_window, "class_picker") or self.app_window.class_picker is None:
            from .class_picker import ClassPicker
            self.app_window.class_picker = ClassPicker(self.app_window, parent=self)
        
        picker = self.app_window.class_picker
        
        try:
            picker.from_list.itemSelectionChanged.disconnect(self.update_classes_from_picker)
        except:
            pass
        try:
            picker.to_combo.currentIndexChanged.disconnect(self.update_classes_from_picker)
        except:
            pass
        
        picker.from_list.itemSelectionChanged.connect(self.update_classes_from_picker)
        picker.to_combo.currentIndexChanged.connect(self.update_classes_from_picker)
        
        picker.show()
        picker.raise_()
        picker.activateWindow()

        cell = self.table.item(row, self.COL_CLASSES)
        if cell and cell.data(Qt.UserRole):
            from_cls, to_cls = decode_classes(cell.data(Qt.UserRole))
            if from_cls is not None:
                picker.from_list.clearSelection()
                from_list = from_cls if isinstance(from_cls, list) else [from_cls]
                for i in range(picker.from_list.count()):
                    item = picker.from_list.item(i)
                    if item.data(Qt.UserRole) in from_list:
                        item.setSelected(True)
            else:
                for i in range(picker.from_list.count()):
                    item = picker.from_list.item(i)
                    if item.data(Qt.UserRole) is None:
                        item.setSelected(True)
                        break
            
            if to_cls is not None:
                idx = picker.to_combo.findData(to_cls)
                if idx >= 0:
                    picker.to_combo.setCurrentIndex(idx)
            else:
                idx = picker.to_combo.findData(None)
                if idx >= 0:
                    picker.to_combo.setCurrentIndex(idx)

    def _get_or_create_display_mode_dialog(self):
        if hasattr(self.app_window, "ensure_display_mode_dialog"):
            if self.app_window.ensure_display_mode_dialog():
                return getattr(self.app_window, "display_mode_dialog", None)
            return None
        dlg = getattr(self.app_window, "display_mode_dialog", None)
        if dlg is None:
            from gui.display_mode import DisplayModeDialog
            dlg = DisplayModeDialog(self.app_window)
            self.app_window.display_mode_dialog = dlg
        return dlg

    def _open_display_mode_for_row(self, row: int):
        self._pending_display_mode_row = row

        existing_preset = None
        mod_combo = self.table.cellWidget(row, self.COL_MODIFIER)
        key_combo = self.table.cellWidget(row, self.COL_KEY)

        cell = self.table.item(row, self.COL_CLASSES)
        if cell:
            existing_preset = decode_display_preset(cell.data(Qt.UserRole))

        if existing_preset is None and mod_combo and key_combo:
            mod = mod_combo.currentText().lower()
            key = key_combo.currentText().upper()
            shortcut_info = getattr(self.app_window, 'shortcuts', {}).get((mod, key))
            if shortcut_info and shortcut_info.get("tool") == "DisplayMode":
                existing_preset = shortcut_info.get("preset")

        if hasattr(self, '_display_picker') and self._display_picker is not None:
            try:
                self._display_picker.close()
                self._display_picker.deleteLater()
            except:
                pass

        self._display_picker = ClassVisibilityPicker(self.app_window, mode="display", parent=self)
        picker = self._display_picker

        if existing_preset:
            views = existing_preset.get("views", {})
            border_percent = existing_preset.get("border_percent", 0)

            if views:
                views = {int(k): v for k, v in views.items()}
                first_view_idx = min(views.keys())
                view_classes = {int(k): dict(v) for k, v in views[first_view_idx].items()}

                picker.border_spin.setValue(border_percent)
                picker.view_selector.blockSignals(True)
                picker.view_selector.setCurrentIndex(first_view_idx)
                picker.view_selector.blockSignals(False)

                if not hasattr(picker, 'view_configs'):
                    picker.view_configs = {}
                picker.view_configs[first_view_idx] = view_classes

                picker._populate_classes()

                for code, checkbox in picker.class_checkboxes.items():
                    checkbox.setChecked(view_classes.get(code, {}).get("show", True))
                if hasattr(picker, 'weight_spinboxes'):
                    for code, spin in picker.weight_spinboxes.items():
                        spin.setValue(view_classes.get(code, {}).get("weight", 1.0))
            else:
                picker.border_spin.setValue(border_percent)
                picker._populate_classes()
        else:
            picker.view_selector.blockSignals(True)
            picker.view_selector.setCurrentIndex(0)
            picker.view_selector.blockSignals(False)

            fresh_classes, fresh_border = self._get_live_display_state_for_view(0)
            if fresh_classes:
                if not hasattr(picker, 'view_configs'):
                    picker.view_configs = {}
                picker.view_configs[0] = fresh_classes
                picker.border_spin.setValue(fresh_border)

            picker._populate_classes()

            if fresh_classes:
                for code, checkbox in picker.class_checkboxes.items():
                    checkbox.setChecked(fresh_classes.get(code, {}).get("show", True))
                if hasattr(picker, 'weight_spinboxes'):
                    for code, spin in picker.weight_spinboxes.items():
                        spin.setValue(fresh_classes.get(code, {}).get("weight", 1.0))

        def on_accepted():
            all_configs = picker.get_all_view_configs()
            border_percent = all_configs.get("border_percent", 0)
            view_configs = all_configs.get("views", {})

            if not view_configs:
                return

            view_idx = list(view_configs.keys())[0]
            view_classes = view_configs[view_idx]

            preset = {
                "border_percent": border_percent,
                "views": {view_idx: view_classes},
                "force_refresh": True
            }

            visible = sum(1 for c in view_classes.values() if c.get("show"))
            view_name = (["Main", "View 1", "View 2", "View 3", "View 4", "Cut"][view_idx]
                         if view_idx < 6 else f"View {view_idx}")

            weights = [c.get("weight", 1.0) for c in view_classes.values()]
            unique_weights = sorted(set(weights))
            weight_info = (f"W={unique_weights[0]:.1f}" if len(unique_weights) == 1
                           else f"W={min(weights):.1f}-{max(weights):.1f}")

            summary = f"{view_name}: {visible}vis, B={border_percent:.1f}%, {weight_info}"

            item = QTableWidgetItem(summary)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_display_preset(preset))
            self.table.setItem(row, self.COL_CLASSES, item)

            _mod_w = self.table.cellWidget(row, self.COL_MODIFIER)
            _key_w = self.table.cellWidget(row, self.COL_KEY)
            if _mod_w and _key_w:
                _m = _mod_w.currentText().lower()
                _k = _key_w.currentText().upper()
                _sh = getattr(self.app_window, 'shortcuts', {})
                if (_m, _k) in _sh and _sh[(_m, _k)].get('tool') == 'DisplayMode':
                    _sh[(_m, _k)]['preset'] = preset

            try:
                self.auto_save_shortcuts()
            except Exception as _e:
                print(f"   ⚠️ auto_save_shortcuts failed: {_e}")

            picker.close()
            picker.deleteLater()
            self._display_picker = None

        picker.accepted.connect(on_accepted)

        def on_rejected():
            picker.close()
            picker.deleteLater()
            self._display_picker = None

        picker.rejected.connect(on_rejected)
        picker.show()
        picker.raise_()
        picker.activateWindow()

    def _get_live_display_state_for_view(self, view_idx):
        try:
            dlg = getattr(self.app_window, 'display_mode_dialog', None)
            
            if dlg is not None and hasattr(dlg, 'view_palettes') and view_idx in dlg.view_palettes:
                live_palette = dlg.view_palettes[view_idx]
                if live_palette:
                    classes = {}
                    for code, info in live_palette.items():
                        code_int = int(code)
                        classes[code_int] = {
                            'show': info.get('show', True),
                            'weight': float(info.get('weight', 1.0)),
                            'description': info.get('description', ''),
                            'color': tuple(info.get('color', (128, 128, 128))),
                            'draw': info.get('draw', ''),
                            'lvl': info.get('lvl', ''),
                        }
                    border = 0
                    if hasattr(dlg, 'view_borders') and view_idx in dlg.view_borders:
                        border = float(dlg.view_borders[view_idx])
                    return classes, border
            
            app_palettes = getattr(self.app_window, 'view_palettes', {})
            if view_idx in app_palettes and app_palettes[view_idx]:
                classes = {}
                for code, info in app_palettes[view_idx].items():
                    code_int = int(code)
                    classes[code_int] = {
                        'show': info.get('show', True),
                        'weight': float(info.get('weight', 1.0)),
                        'description': info.get('description', ''),
                        'color': tuple(info.get('color', (128, 128, 128))),
                        'draw': info.get('draw', ''),
                        'lvl': info.get('lvl', ''),
                    }
                return classes, 0
            
            if view_idx == 0 and hasattr(self.app_window, 'class_palette'):
                classes = {}
                for code, info in self.app_window.class_palette.items():
                    classes[int(code)] = {
                        'show': info.get('show', True),
                        'weight': float(info.get('weight', 1.0)),
                        'description': info.get('description', ''),
                        'color': tuple(info.get('color', (128, 128, 128))),
                        'draw': info.get('draw', ''),
                        'lvl': info.get('lvl', ''),
                    }
                return classes, 0
            
            return None, 0
        except Exception as e:
            print(f"   ⚠️ _get_live_display_state_for_view failed: {e}")
            return None, 0
    
    def _open_shading_mode_for_row(self, row: int):
        self._pending_shading_mode_row = row
        
        cell = self.table.item(row, self.COL_CLASSES)
        existing_preset = decode_shading_preset(cell.data(Qt.UserRole)) if cell else None
        existing_classes = existing_preset.get("classes", {}) if existing_preset else {}
        
        if not hasattr(self, '_shading_picker') or self._shading_picker is None:
            self._shading_picker = ClassVisibilityPicker(self.app_window, mode="shading", parent=self)
        
        picker = self._shading_picker
        
        if existing_classes:
            picker.set_selected_classes(existing_classes)
        if existing_preset:
            picker.set_shading_parameters(existing_preset)
        
        try:
            picker.accepted.disconnect()
        except:
            pass
        
        def on_accepted():
            selected_classes = picker.get_selected_classes()
            shading_params = picker.get_shading_parameters()
            preset = {
                "azimuth": shading_params.get("azimuth", 45.0),
                "angle": shading_params.get("angle", 45.0),
                "ambient": shading_params.get("ambient", 0.1),
                "quality": shading_params.get("quality", 100.0),
                "speed": shading_params.get("speed", 1),
                "classes": selected_classes
            }
            visible_count = sum(1 for c in selected_classes.values() if c.get("show"))
            summary = f"Shading: {preset['azimuth']}°/{preset['angle']}°, {visible_count} visible, Speed={preset['speed']}"
            item = QTableWidgetItem(summary)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_shading_preset(preset))
            self.table.setItem(row, self.COL_CLASSES, item)
            picker.hide()
        
        picker.accepted.connect(on_accepted)
        picker.show()
        picker.raise_()
        picker.activateWindow()

    def _open_draw_settings_for_row(self, row: int):
        cell = self.table.item(row, self.COL_CLASSES)
        existing_preset = decode_draw_preset(cell.data(Qt.UserRole)) if cell else None

        if hasattr(self, '_draw_picker') and self._draw_picker is not None:
            try:
                self._draw_picker.close()
                self._draw_picker.deleteLater()
            except Exception:
                pass

        self._draw_picker = DrawSettingsPicker(self.app_window, parent=self)
        picker = self._draw_picker

        if existing_preset:
            picker.set_preset(existing_preset)

        def on_accepted():
            preset = picker.get_preset()
            active_tool = preset.get("active_tool", "smartline")
            tools = preset.get("tools", {})
            from gui.draw_settings_dialog import vtk_color_to_qcolor
            parts = []
            if active_tool in tools:
                st = tools[active_tool]
                qc = vtk_color_to_qcolor(st.get("color", (1, 0, 0)))
                parts.append(f"[{active_tool.upper()}] {qc.name()}, {st.get('width', 2)}px")
            for tk, st in tools.items():
                if tk == active_tool: continue
                qc = vtk_color_to_qcolor(st.get("color", (1, 0, 0)))
                parts.append(f"{tk}: {qc.name()}")
            summary = "; ".join(parts) if parts else "Draw preset"
            if len(summary) > 80:
                summary = summary[:77] + "..."
            item = QTableWidgetItem(summary)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_draw_preset(preset))
            self.table.setItem(row, self.COL_CLASSES, item)
            picker.close()
            picker.deleteLater()
            self._draw_picker = None

        def on_rejected():
            picker.close()
            picker.deleteLater()
            self._draw_picker = None

        picker.accepted.connect(on_accepted)
        picker.rejected.connect(on_rejected)
        picker.show()
        picker.raise_()
        picker.activateWindow()

    def _capture_display_mode_preset(self, payload: dict):
        row = self._pending_display_mode_row
        if row is None:
            return
        try:
            classes = payload.get("classes", {}) or {}
            visible = [c for c, info in classes.items() if info.get("show")]
            slot = payload.get("target_view", payload.get("slot", 0))
            view_name = ("Main View" if slot == 0 else
                         (f"View {slot}" if slot <= 4 else
                          ("Cut Section View" if slot == 5 else f"View {slot}")))
            summary = f"Preset: {len(visible)} visible ({view_name})"
            item = QTableWidgetItem(summary)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_display_preset(payload))
            self.table.setItem(row, self.COL_CLASSES, item)
        finally:
            self._pending_display_mode_row = None
            dlg = getattr(self.app_window, "display_mode_dialog", None)
            if dlg is not None:
                try:
                    dlg.applied.disconnect(self._capture_display_mode_preset)
                except Exception:
                    pass

    def update_classes_from_picker(self):
        if not self.is_editing_shortcuts or self._active_row is None:
            return
        if not hasattr(self.app_window, 'class_picker') or self.app_window.class_picker is None:
            return
        
        picker = self.app_window.class_picker
        selected_items = picker.from_list.selectedItems()
        
        if not selected_items:
            from_cls = None
            from_txt = "Any"
        else:
            any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
            if any_selected:
                from_cls = None
                from_txt = "Any"
            else:
                from_cls = [item.data(Qt.UserRole) for item in selected_items]
                from_txt = ", ".join(str(c) for c in from_cls)
        
        to_cls = picker.to_combo.currentData()
        to_txt = picker.to_combo.currentText().split(" - ")[0] if to_cls is not None else "Any"
        
        display_text = f"{from_txt} → {to_txt}"
        item = QTableWidgetItem(display_text)
        item.setData(Qt.UserRole, encode_classes(from_cls, to_cls))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(self._active_row, self.COL_CLASSES, item)

    def save_mnu_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Shortcut File", "", "Menu Files (*.mnu)")
        if not path:
            return

        simple_tools = SIMPLE_SHORTCUT_TOOLS

        with open(path, "w") as f:
            for row in range(self.table.rowCount()):
                mod_combo  = self.table.cellWidget(row, self.COL_MODIFIER)
                key_combo  = self.table.cellWidget(row, self.COL_KEY)
                tool_combo = self.table.cellWidget(row, self.COL_TOOL)
                mod  = mod_combo.currentText().lower() if mod_combo else "alt"
                key  = key_combo.currentText().upper() if key_combo else "F1"
                tool = tool_combo.currentText() if tool_combo else "AboveLine"
                cell = self.table.item(row, self.COL_CLASSES)
                
                if tool == "DisplayMode":
                    preset_json = cell.data(Qt.UserRole) if cell else ""
                    display_text = cell.text() if cell else ""
                    f.write(f"{mod}\t{key}\t{tool}\t{preset_json}\t{display_text}\n")
                    continue
                if tool == "ShadingMode":
                    preset_json = cell.data(Qt.UserRole) if cell else ""
                    shading_text = cell.text() if cell else ""
                    f.write(f"{mod}\t{key}\t{tool}\t{preset_json}\t{shading_text}\n")
                    continue
                if tool == "DrawSettings":
                    preset_json = cell.data(Qt.UserRole) if cell else ""
                    draw_text = cell.text() if cell else ""
                    f.write(f"{mod}\t{key}\t{tool}\t{preset_json}\t{draw_text}\n")
                    continue
                if tool in simple_tools:
                    f.write(f"{mod}\t{key}\t{tool}\t\t\n")
                else:
                    from_cls, to_cls = decode_classes(cell.data(Qt.UserRole)) if cell else (None, None)
                    if isinstance(from_cls, list):
                        from_str = ",".join(str(c) for c in from_cls)
                    elif from_cls is None:
                        from_str = ""
                    else:
                        from_str = str(from_cls)
                    to_str = "" if to_cls is None else str(to_cls)
                    f.write(f"{mod}\t{key}\t{tool}\t{from_str}\t{to_str}\n")

        self.current_mnu_path = path
        print(f"✅ Shortcuts saved to: {path}")

    def load_mnu(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Shortcut File", "", "Menu Files (*.mnu)")
        if not path:
            return

        self._is_loading_shortcuts = True
        self._selected_rows.clear()
        
        try:
            self.table.setRowCount(0)

            with open(path, "r") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) < 3:
                        continue

                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    self._install_row_widgets(row, modifier=parts[0], key=parts[1], tool=parts[2])

                    if parts[2] == "DisplayMode":
                        if len(parts) > 3 and parts[3].strip():
                            preset_payload = decode_display_preset(parts[3])
                            saved_text = parts[4] if len(parts) > 4 else ""
                            if saved_text:
                                item = QTableWidgetItem(saved_text)
                                item.setData(Qt.UserRole, parts[3])
                            elif preset_payload and preset_payload.get("views"):
                                views = preset_payload.get("views", {})
                                border_pct = preset_payload.get("border_percent", 0)
                                view_summaries = []
                                for view_idx in sorted(views.keys()):
                                    visible = sum(1 for c in views[view_idx].values() if c.get("show"))
                                    view_name = (["Main","V1","V2","V3","V4","Cut"][view_idx]
                                                 if view_idx < 6 else f"V{view_idx}")
                                    view_summaries.append(f"{view_name}: {visible}vis, B={border_pct:.1f}%")
                                item = QTableWidgetItem("; ".join(view_summaries))
                                item.setData(Qt.UserRole, parts[3])
                            else:
                                item = QTableWidgetItem("Click/Double-click to configure display preset")
                                item.setData(Qt.UserRole, encode_display_preset({
                                    "classes": {}, "slot": 0, "target_view": 0,
                                    "color_mode": 0, "border_percent": 0, "force_refresh": True
                                }))
                        else:
                            item = QTableWidgetItem("Click/Double-click to configure display preset")
                            item.setData(Qt.UserRole, encode_display_preset({
                                "classes": {}, "slot": 0, "target_view": 0,
                                "color_mode": 0, "border_percent": 0, "force_refresh": True
                            }))
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, self.COL_CLASSES, item)
                        continue

                    if parts[2] == "DrawSettings":
                        if len(parts) > 3 and parts[3].strip():
                            preset_payload = decode_draw_preset(parts[3])
                            saved_text = parts[4] if len(parts) > 4 else ""
                            if saved_text:
                                item = QTableWidgetItem(saved_text)
                                item.setData(Qt.UserRole, parts[3])
                            elif preset_payload:
                                item = QTableWidgetItem("Draw preset")
                                item.setData(Qt.UserRole, parts[3])
                            else:
                                item = QTableWidgetItem("Click/Double-click to configure draw preset")
                                item.setData(Qt.UserRole, encode_draw_preset({"tools": {}}))
                        else:
                            item = QTableWidgetItem("Click/Double-click to configure draw preset")
                            item.setData(Qt.UserRole, encode_draw_preset({"tools": {}}))
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, self.COL_CLASSES, item)
                        continue                    
                    
                    if parts[2] == "ShadingMode":
                        if len(parts) > 3 and parts[3].strip():
                            preset_payload = decode_shading_preset(parts[3])
                            saved_text = parts[4] if len(parts) > 4 else ""
                            if saved_text:
                                item = QTableWidgetItem(saved_text)
                                item.setData(Qt.UserRole, parts[3])
                            elif preset_payload and preset_payload.get("classes"):
                                visible = [c for c, info in preset_payload["classes"].items() if info.get("show")]
                                az = preset_payload.get("azimuth", 45.0)
                                ang = preset_payload.get("angle", 45.0)
                                speed = preset_payload.get("speed", 1)
                                item = QTableWidgetItem(f"Shading: {az}°/{ang}°, {len(visible)} visible, Speed={speed}")
                                item.setData(Qt.UserRole, parts[3])
                            else:
                                item = QTableWidgetItem("Preset: Not configured yet")
                                item.setData(Qt.UserRole, encode_shading_preset({
                                    "azimuth": 45.0, "angle": 45.0, "ambient": 0.1,
                                    "quality": 100.0, "speed": 1, "classes": {}
                                }))
                        else:
                            item = QTableWidgetItem("Preset: Not configured yet")
                            item.setData(Qt.UserRole, encode_shading_preset({
                                "azimuth": 45.0, "angle": 45.0, "ambient": 0.1,
                                "quality": 100.0, "speed": 1, "classes": {}
                            }))
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, self.COL_CLASSES, item)
                        continue

                    if parts[2] in SIMPLE_SHORTCUT_TOOLS:
                        item = QTableWidgetItem("N/A")
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setData(Qt.UserRole, encode_classes(None, None))
                        self.table.setItem(row, self.COL_CLASSES, item)
                        continue

                    from_cls = None
                    if len(parts) > 3 and parts[3].strip():
                        s = parts[3].strip()
                        if "," in s:
                            from_cls = [int(x) for x in s.split(",")]
                        else:
                            from_cls = [int(s)]

                    to_cls = None
                    if len(parts) > 4 and parts[4].strip():
                        to_cls = int(parts[4].strip())

                    from_txt = ", ".join(str(c) for c in from_cls) if from_cls else "Any"
                    to_txt = str(to_cls) if to_cls is not None else "Any"

                    item = QTableWidgetItem(f"{from_txt} → {to_txt}")
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setData(Qt.UserRole, encode_classes(from_cls, to_cls))
                    self.table.setItem(row, self.COL_CLASSES, item)

            self.current_mnu_path = path
            if self.table.rowCount() > 0:
                self._set_current_row(0)
            print(f"✅ Shortcuts loaded from: {path}")
            
        finally:
            self._is_loading_shortcuts = False

    def on_apply(self):
        self._applying_shortcuts = True
    
        try:
            seen_keys = {}
            for row in range(self.table.rowCount()):
                mod_combo = self.table.cellWidget(row, self.COL_MODIFIER)
                key_combo = self.table.cellWidget(row, self.COL_KEY)
                if mod_combo and key_combo:
                    mod = mod_combo.currentText().lower()
                    key = key_combo.currentText().upper()
                    combo = (mod, key)
                    if combo in seen_keys:
                        QMessageBox.critical(
                            self, "Cannot Apply",
                            f"❌ Duplicate shortcut detected!\n\n"
                            f"{mod}+{key} is used in both:\n"
                            f"  • Row {seen_keys[combo] + 1}\n"
                            f"  • Row {row + 1}\n\n"
                            f"Please fix duplicates before applying."
                        )
                        return
                    seen_keys[combo] = row

            shortcuts = {}
            simple_tools = SIMPLE_SHORTCUT_TOOLS
    
            for row in range(self.table.rowCount()):
                mod_combo  = self.table.cellWidget(row, self.COL_MODIFIER)
                key_combo  = self.table.cellWidget(row, self.COL_KEY)
                tool_combo = self.table.cellWidget(row, self.COL_TOOL)
                mod  = mod_combo.currentText().lower() if mod_combo else "alt"
                key  = key_combo.currentText().upper() if key_combo else "F1"
                tool = tool_combo.currentText() if tool_combo else None

                if tool == "DisplayMode":
                    cell = self.table.item(row, self.COL_CLASSES)
                    preset_payload = decode_display_preset(cell.data(Qt.UserRole)) if cell else None
                    if not preset_payload or not preset_payload.get("views"):
                        preset_payload = {
                            "border_percent": getattr(self.app_window, "display_border_percent", 0),
                            "views": {
                                0: {
                                    code: {"show": entry.get("show", True), "weight": entry.get("weight", 1.0)}
                                    for code, entry in self.app_window.class_palette.items()
                                }
                            },
                            "force_refresh": True
                        }
                    shortcuts[(mod, key)] = {"tool": "DisplayMode", "preset": preset_payload}
                    continue

                if tool == "ShadingMode":
                    cell = self.table.item(row, self.COL_CLASSES)
                    preset_payload = decode_shading_preset(cell.data(Qt.UserRole)) if cell else None
                    if not preset_payload or not preset_payload.get("classes"):
                        QMessageBox.warning(
                            self, "ShadingMode preset missing",
                            f"Row {row + 1} uses ShadingMode but has no preset.\n"
                            "Configure it first, then click Apply."
                        )
                        return
                    shortcuts[(mod, key)] = {"tool": "ShadingMode", "preset": preset_payload}
                    continue

                if tool == "DrawSettings":
                    cell = self.table.item(row, self.COL_CLASSES)
                    preset_payload = decode_draw_preset(cell.data(Qt.UserRole)) if cell else None
                    shortcuts[(mod, key)] = {"tool": "DrawSettings", "preset": preset_payload}
                    continue

                if tool in simple_tools:
                    shortcuts[(mod, key)] = {"tool": tool, "from": None, "to": None}
                else:
                    cell = self.table.item(row, self.COL_CLASSES)
                    from_cls, to_cls = decode_classes(cell.data(Qt.UserRole)) if cell else (None, None)
                    if isinstance(from_cls, str):
                        if not from_cls or from_cls in ("None", "Any"):
                            from_cls = None
                        elif "," in from_cls:
                            from_cls = [int(c) for c in from_cls.split(",")]
                        else:
                            from_cls = [int(from_cls)]
                    if isinstance(to_cls, str):
                        to_cls = None if to_cls in ("", "None", "Any") else int(to_cls)
                    shortcuts[(mod, key)] = {"tool": tool, "from": from_cls, "to": to_cls}

            self.app_window.shortcuts = shortcuts
        
            if not hasattr(self.app_window, 'view_palettes'):
                self.app_window.view_palettes = {}
                    
            self.applied.emit(shortcuts)
            self.auto_save_shortcuts()
            self.is_editing_shortcuts = False
        
            if hasattr(self.app_window, 'class_picker') and self.app_window.class_picker:
                self.app_window.class_picker.hide()

            self.close()
            QTimer.singleShot(0, self._sort_table_by_modifier)
    
        finally:
            self._applying_shortcuts = False

    def on_cancel(self):
        self.is_editing_shortcuts = False
        self.close()
 
    def closeEvent(self, event):
        self.is_editing_shortcuts = False
        if hasattr(self.app_window, 'class_picker') and self.app_window.class_picker:
            try:
                self.app_window.class_picker.from_list.itemSelectionChanged.disconnect(
                    self.update_classes_from_picker)
            except:
                pass
            try:
                self.app_window.class_picker.to_combo.currentIndexChanged.disconnect(
                    self.update_classes_from_picker)
            except:
                pass
        super().closeEvent(event) 
    
    @staticmethod
    def open_manager(app_window):
        if ShortcutManager.instance is None:
            ShortcutManager.instance = ShortcutManager(app_window, parent=app_window)
        if not ShortcutManager.instance.isVisible():
            ShortcutManager.instance.show()
            ShortcutManager.instance.raise_()
            ShortcutManager.instance.activateWindow()
        else:
            ShortcutManager.instance.raise_()
            ShortcutManager.instance.activateWindow()
        return ShortcutManager.instance
 
    def auto_load_shortcuts(self):
        try:
            shortcuts_data = self.settings.value("shortcuts", None)
            if shortcuts_data is None:
                return

            if isinstance(shortcuts_data, str):
                shortcuts_list = json.loads(shortcuts_data)
            else:
                shortcuts_list = shortcuts_data

            shortcuts = {}
            simple_tools = SIMPLE_SHORTCUT_TOOLS

            self._is_loading_shortcuts = True
            try:
                for entry in shortcuts_list:
                    modifier  = entry.get("modifier", "alt")
                    key       = entry.get("key", "F1")
                    tool      = entry.get("tool", "AboveLine")
                    mod       = modifier.lower()
                    key_upper = key.upper()

                    if tool == "DisplayMode":
                        preset_payload = entry.get("display_preset")
                        if preset_payload:
                            shortcuts[(mod, key_upper)] = {"tool": "DisplayMode", "preset": preset_payload}
                        continue
                    if tool == "ShadingMode":
                        preset_payload = entry.get("shading_preset")
                        if preset_payload:
                            shortcuts[(mod, key_upper)] = {"tool": "ShadingMode", "preset": preset_payload}
                        continue
                    if tool == "DrawSettings":
                        preset_payload = entry.get("draw_preset")
                        if preset_payload:
                            shortcuts[(mod, key_upper)] = {"tool": "DrawSettings", "preset": preset_payload}
                        continue
                    if tool in simple_tools:
                        shortcuts[(mod, key_upper)] = {"tool": tool, "from": None, "to": None}
                    else:
                        from_cls = entry.get("from_classes")
                        to_cls   = entry.get("to_class")
                        shortcuts[(mod, key_upper)] = {"tool": tool, "from": from_cls, "to": to_cls}
            finally:
                self._is_loading_shortcuts = False

            self.app_window.shortcuts = shortcuts

            # ── Rebuild table UI ──────────────────────────────────────
            self._is_loading_shortcuts = True
            self._selected_rows.clear()
            try:
                self.table.setRowCount(0)
                for entry in shortcuts_list:
                    row = self.table.rowCount()
                    self.table.insertRow(row)
                    self._install_row_widgets(
                        row,
                        modifier=entry.get("modifier", "alt"),
                        key=entry.get("key", "F1"),
                        tool=entry.get("tool", "AboveLine")
                    )
                    tool = entry.get("tool", "AboveLine")

                    if tool == "DisplayMode":
                        preset_payload = entry.get("display_preset")
                        if preset_payload:
                            views = preset_payload.get("views", {})
                            border_pct = preset_payload.get("border_percent", 0)
                            first_view = int(list(views.keys())[0]) if views else 0
                            view_name = (["Main","V1","V2","V3","V4","Cut"][first_view]
                                         if first_view < 6 else f"V{first_view}")
                            vis_cnt = sum(sum(1 for c in cls.values() if c.get("show"))
                                          for cls in views.values())
                            summary = f"{view_name}: {vis_cnt}vis, B={border_pct:.1f}%"
                            item = QTableWidgetItem(summary)
                            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                            item.setData(Qt.UserRole, encode_display_preset(preset_payload))
                        else:
                            item = QTableWidgetItem("Click to configure")
                            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, self.COL_CLASSES, item)

                    elif tool == "ShadingMode":
                        preset_payload = entry.get("shading_preset")
                        if preset_payload:
                            az  = preset_payload.get("azimuth", 45)
                            ang = preset_payload.get("angle",   45)
                            item = QTableWidgetItem(f"Shading: az={az}° ang={ang}°")
                        else:
                            item = QTableWidgetItem("Preset: Not configured yet")
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setData(Qt.UserRole, encode_shading_preset(preset_payload or {}))
                        self.table.setItem(row, self.COL_CLASSES, item)

                    elif tool == "DrawSettings":
                        preset_payload = entry.get("draw_preset")
                        item = QTableWidgetItem(
                            f"Draw: {len((preset_payload or {}).get('tools', {}))} tools"
                        )
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setData(Qt.UserRole, encode_draw_preset(preset_payload or {}))
                        self.table.setItem(row, self.COL_CLASSES, item)

                    elif tool in SIMPLE_SHORTCUT_TOOLS:
                        item = QTableWidgetItem("N/A")
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setData(Qt.UserRole, encode_classes(None, None))
                        self.table.setItem(row, self.COL_CLASSES, item)

                    else:
                        from_cls = entry.get("from_classes")
                        to_cls   = entry.get("to_class")
                        label = f"{from_cls} → {to_cls}" if from_cls or to_cls else "Any → Any"
                        item = QTableWidgetItem(label)
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setData(Qt.UserRole, encode_classes(from_cls, to_cls))
                        self.table.setItem(row, self.COL_CLASSES, item)

            finally:
                self._is_loading_shortcuts = False

            if self.table.rowCount() > 0:
                self._set_current_row(0)

        except Exception as e:
            print(f"❌ auto_load_shortcuts failed: {e}")
            import traceback
            traceback.print_exc()

    def auto_save_shortcuts(self):
        try:
            shortcuts_list = []
            for row in range(self.table.rowCount()):
                mod_combo  = self.table.cellWidget(row, self.COL_MODIFIER)
                key_combo  = self.table.cellWidget(row, self.COL_KEY)
                tool_combo = self.table.cellWidget(row, self.COL_TOOL)
                cell       = self.table.item(row, self.COL_CLASSES)

                if not (mod_combo and key_combo and tool_combo):
                    continue

                modifier = mod_combo.currentText()
                key      = key_combo.currentText()
                tool     = tool_combo.currentText()
                entry = {"modifier": modifier, "key": key, "tool": tool}

                if tool == "DisplayMode" and cell:
                    preset = decode_display_preset(cell.data(Qt.UserRole))
                    if preset:
                        entry["display_preset"] = preset
                elif tool == "ShadingMode" and cell:
                    preset = decode_shading_preset(cell.data(Qt.UserRole))
                    if preset:
                        entry["shading_preset"] = preset
                elif tool == "DrawSettings" and cell:
                    preset = decode_draw_preset(cell.data(Qt.UserRole))
                    if preset:
                        entry["draw_preset"] = preset
                else:
                    if cell:
                        from_cls, to_cls = decode_classes(cell.data(Qt.UserRole))
                        entry["from_classes"] = from_cls
                        entry["to_class"]     = to_cls

                shortcuts_list.append(entry)

            self.settings.setValue("shortcuts", json.dumps(shortcuts_list))
            print(f"💾 Saved {len(shortcuts_list)} shortcuts to QSettings")

        except Exception as e:
            print(f"❌ auto_save_shortcuts failed: {e}")
            import traceback
            traceback.print_exc()

    def _sort_table_by_modifier(self):
        row_count = self.table.rowCount()
        if row_count < 2:
            return

        MODIFIER_ORDER = {
            "alt": 0, "alt+shift": 1, "ctrl": 2, "ctrl+alt": 3,
            "ctrl+alt+shift": 4, "ctrl+shift": 5, "none": 6, "shift": 7,
        }

        def _key_rank(key):
            k = key.upper()
            if len(k) >= 2 and k[0] == "F" and k[1:].isdigit():
                return (0, int(k[1:]), "")
            if k == "SPACE":
                return (2, 0, "SPACE")
            return (1, 0, k)

        def sort_key(r):
            return (MODIFIER_ORDER.get(r["mod"].lower(), 99), _key_rank(r["key"]))

        rows_data = []
        for row in range(row_count):
            mod_combo  = self.table.cellWidget(row, self.COL_MODIFIER)
            key_combo  = self.table.cellWidget(row, self.COL_KEY)
            tool_combo = self.table.cellWidget(row, self.COL_TOOL)
            cell3      = self.table.item(row, self.COL_CLASSES)
            cb         = self._get_row_checkbox(row)

            rows_data.append({
                "mod":         mod_combo.currentText()  if mod_combo  else "none",
                "key":         key_combo.currentText()  if key_combo  else "F1",
                "tool":        tool_combo.currentText() if tool_combo else "AboveLine",
                "cell3_text":  cell3.text()             if cell3      else "",
                "cell3_data":  cell3.data(Qt.UserRole)  if cell3      else None,
                "cell3_flags": cell3.flags()            if cell3      else Qt.ItemIsEnabled,
                "checked":     cb.isChecked()           if cb         else False,
            })

        rows_data.sort(key=sort_key)

        prev_loading = self._is_loading_shortcuts
        self._is_loading_shortcuts = True
        self._selected_rows.clear()
        try:
            self.table.setRowCount(0)
            for row, rd in enumerate(rows_data):
                self.table.insertRow(row)
                self._install_row_widgets(row, modifier=rd["mod"], key=rd["key"], tool=rd["tool"])
                # Restore checkbox state
                cb = self._get_row_checkbox(row)
                if cb and rd["checked"]:
                    cb.blockSignals(True)
                    cb.setChecked(True)
                    cb.blockSignals(False)
                    self._selected_rows.add(row)
                item = QTableWidgetItem(rd["cell3_text"])
                item.setData(Qt.UserRole, rd["cell3_data"])
                item.setFlags(rd["cell3_flags"])
                self.table.setItem(row, self.COL_CLASSES, item)
        finally:
            self._is_loading_shortcuts = prev_loading

        self._refresh_all_row_headers()
        print(f"✅ Table sorted by Modifier: {row_count} rows")