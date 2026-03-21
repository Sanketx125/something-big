from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QFileDialog, QComboBox, QHeaderView, QMessageBox, QDialog,
    QListWidget, QListWidgetItem, QLabel,QCheckBox,QDoubleSpinBox  # ✅ Add these three
)
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect
from PySide6.QtCore import Signal, Qt, QSettings,QEvent
from PySide6.QtGui import QColor
from torch import layout  #✅ Add QColor

 
from .class_picker import ClassPicker

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
    "DrawSettings"
]

 
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
        # New structure: views contain their own class configs
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
            "__type__": "display_mode_preset_v2",  # New version
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
        
        # Handle new multi-view format
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
        
        # Legacy single-view format (backwards compatibility)
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
            
            # Convert to new format
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
/* Main window background */
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: "Segoe UI", "SF Pro Display", Roboto, sans-serif;
    font-size: 12px;
}

/* Table styling */
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

QTableWidget::item:hover {
    background-color: #2a2d3e;
}

QTableCornerButton::section {
    background-color: #252526;
    border: 1px solid #3e3e42;
    border-right: 1px solid #3e3e42;
}

/* Header styling */
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

/* ComboBox styling - CRITICAL for table cells */
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

/* Button styling */
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

/* Scroll bars */
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

/* SpinBox styling */
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
    """Encode shading parameters + class visibility into JSON"""
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
    """Decode shading preset from JSON"""
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
    """Encode draw tool styles into JSON"""
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
    """Decode draw settings preset from JSON"""
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
    """Lightweight dialog to configure draw tool styles for a shortcut preset."""

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

        # Working copy
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

        # ── Tool selector ──────────────────────────────────────────────
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
        """Return the configured draw styles as a preset dict."""
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
        """Load an existing preset into the UI."""
        # Active tool
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
            # Update color button
            qc = self._vtk_to_q(style.get("color", (1, 0, 0)))
            self._color_buttons[key].setStyleSheet(
                f"background-color: {qc.name()}; border: 2px solid #fff; border-radius: 4px;"
            )
            # Update width
            self._width_combos[key].setCurrentText(str(style.get("width", 2)))
            # Update style
            self._style_combos[key].setCurrentText(style.get("style", "solid"))

class ClassVisibilityPicker(QDialog):
    """Lightweight dialog to pick visible classes + view target for Display Mode"""
    
    settings_changed = Signal(dict)
    
    def __init__(self, app_window, mode="display", parent=None):
        super().__init__(parent)
        self.app_window = app_window
        self.mode = mode
        
        # ✅ Import all widgets at the start
        from PySide6.QtWidgets import QGroupBox, QSpinBox, QDoubleSpinBox, QGridLayout, QScrollArea
        
        self.setWindowTitle(f"Configure {mode.title()} Mode Preset")
        
        # ✅ Make it non-modal and keep on top of parent
        self.setModal(False)
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        
        self.resize(600, 650)  # ✅ Increased height for view selector
        
        layout = QVBoxLayout(self)
        
        # ============================================================================
        # ✅ NEW: VIEW/SLOT SELECTION (ONLY for Display Mode)
        # ============================================================================
        # ============================================================================
        # ✅ SINGLE VIEW SELECTION (ONLY for Display Mode)
        # ============================================================================
        if mode == "display":
            view_group = QGroupBox("🎯 Target View")
            view_layout = QVBoxLayout()
            
            info_label = QLabel("Select ONE view for this shortcut:")
            info_label.setStyleSheet("color: #cccccc; font-style: italic;")
            view_layout.addWidget(info_label)
            
            self.view_selector = QComboBox()
            self.view_selector.addItems([
                "Main View",
                "View 1",
                "View 2", 
                "View 3",
                "View 4",
                "Cut Section View"
            ])
            self.view_selector.setCurrentIndex(0)
            self.view_selector.setStyleSheet("""
                QComboBox {
                    padding: 6px;
                    font-size: 13px;
                    font-weight: 500;
                }
            """)
            self.view_selector.currentIndexChanged.connect(self._on_view_selector_changed)
            view_layout.addWidget(self.view_selector)
            view_group.setLayout(view_layout)
            layout.addWidget(view_group)
            
            # ✅ Store SINGLE view configuration
            self.selected_view_idx = 0  # Default to Main View
        
            # ✅ Border control (no sync button)
            settings_group = QGroupBox("⚙️ Display Settings")
            settings_layout = QGridLayout()

            settings_layout.addWidget(QLabel("Border %:"), 0, 0)
            self.border_spin = QDoubleSpinBox()
            self.border_spin.setRange(0, 100)
            self.border_spin.setValue(0)
            self.border_spin.setSingleStep(5.0)
            self.border_spin.setToolTip("Border percentage for selected view")
            settings_layout.addWidget(self.border_spin, 0, 1)

            settings_group.setLayout(settings_layout)
            layout.addWidget(settings_group)
        # ============================================================================
        
        # ✅ Add shading parameters if mode is "shading"
        if mode == "shading":
            shading_group = QGroupBox("Shading Parameters")
            shading_layout = QGridLayout()
            
            # Azimuth
            shading_layout.addWidget(QLabel("Azimuth (°):"), 0, 0)
            self.az_spin = QDoubleSpinBox()
            self.az_spin.setRange(0, 360)
            self.az_spin.setValue(45.0)
            self.az_spin.setSingleStep(1.0)
            shading_layout.addWidget(self.az_spin, 0, 1)
            
            # Angle
            shading_layout.addWidget(QLabel("Angle (°):"), 1, 0)
            self.angle_spin = QDoubleSpinBox()
            self.angle_spin.setRange(0, 90)
            self.angle_spin.setValue(45.0)
            self.angle_spin.setSingleStep(1.0)
            shading_layout.addWidget(self.angle_spin, 1, 1)
            
            # Ambient
            shading_layout.addWidget(QLabel("Ambient:"), 2, 0)
            self.ambient_spin = QDoubleSpinBox()
            self.ambient_spin.setRange(0, 1)
            self.ambient_spin.setValue(0.1)
            self.ambient_spin.setSingleStep(0.1)
            shading_layout.addWidget(self.ambient_spin, 2, 1)
            
            # Quality
            shading_layout.addWidget(QLabel("Quality (%):"), 3, 0)
            self.quality_spin = QDoubleSpinBox()
            self.quality_spin.setRange(0, 100)
            self.quality_spin.setValue(100.0)
            self.quality_spin.setSingleStep(10.0)
            shading_layout.addWidget(self.quality_spin, 3, 1)
            
            # Speed
            shading_layout.addWidget(QLabel("Speed:"), 4, 0)
            self.speed_spin = QSpinBox()
            self.speed_spin.setRange(1, 10)
            self.speed_spin.setValue(1)
            shading_layout.addWidget(self.speed_spin, 4, 1)
            
            shading_group.setLayout(shading_layout)
            layout.addWidget(shading_group)
        
        # ✅ Class visibility section
        class_group = QGroupBox("Class Visibility")
        class_layout = QVBoxLayout()
        
        # Refresh button to reload classes
        refresh_layout = QHBoxLayout()
        refresh_layout.addWidget(QLabel("Select which classes to display:"))
        refresh_layout.addStretch()
        self.refresh_btn = QPushButton("🔄 Refresh Classes")
        self.refresh_btn.clicked.connect(self._refresh_classes)
        refresh_layout.addWidget(self.refresh_btn)
        class_layout.addLayout(refresh_layout)
        
        # Scroll area for class dropdowns
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        
        scroll_widget = QWidget()
        self.class_grid = QGridLayout(scroll_widget)
        self.class_grid.setColumnStretch(1, 1)
        scroll.setWidget(scroll_widget)
        
        class_layout.addWidget(scroll)
        class_group.setLayout(class_layout)
        layout.addWidget(class_group, stretch=1)
        
        # Quick selection buttons
        quick_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("Select All")
        self.clear_all_btn = QPushButton("Clear All")
        quick_layout.addWidget(self.select_all_btn)
        quick_layout.addWidget(self.clear_all_btn)
        quick_layout.addStretch()
        layout.addLayout(quick_layout)
        
        # OK/Cancel buttons
        # OK/Apply/Cancel buttons
        # OK/Cancel buttons (NO APPLY BUTTON)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.ok_btn = QPushButton("OK")
        self.cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

        # Connections
        self.select_all_btn.clicked.connect(self._select_all)
        self.clear_all_btn.clicked.connect(self._clear_all)
        self.ok_btn.clicked.connect(self._on_ok_clicked)
        self.cancel_btn.clicked.connect(self.reject)
                
        # Store checkbox references
        self.class_checkboxes = {}
        
        # Populate classes
        self._populate_classes()
    
    def showEvent(self, event):
        super().showEvent(event)
        self.setStyleSheet(DARK_STYLESHEET)
        
        # ✅ Position next to parent window
        if self.parent():
            parent_geo = self.parent().geometry()
            self.move(parent_geo.x() + parent_geo.width() + 10, parent_geo.y())
    
    def _refresh_classes(self):
        """Reload classes from app_window.class_palette"""
        print(f"\n🔄 REFRESH CLASSES CALLED")
        
        # ✅ CRITICAL: Get current selections from BOTH checkboxes AND view_configs
        current_selections = {}
        current_weights = {}
        
        # First, check if we have view_configs (preset data)
        if self.mode == "display" and hasattr(self, 'view_configs') and hasattr(self, 'view_selector'):
            current_view_idx = self.view_selector.currentIndex()
            print(f"   📍 Current view: {current_view_idx}")
            
            # If we have preset data for this view, use that
            if current_view_idx in self.view_configs:
                print(f"   ✅ Found preset data for view {current_view_idx}")
                for code, config in self.view_configs[current_view_idx].items():
                    current_selections[code] = config.get("show", True)
                    current_weights[code] = config.get("weight", 1.0)
                    print(f"      Class {code}: show={current_selections[code]}, weight={current_weights[code]}")
            else:
                print(f"   ⚠️ No preset data for view {current_view_idx}, using checkbox states")
                # Fall back to current checkbox states
                for code, checkbox in self.class_checkboxes.items():
                    current_selections[code] = checkbox.isChecked()
                    if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                        current_weights[code] = self.weight_spinboxes[code].value()
        else:
            # Not display mode, just preserve current checkbox states
            for code, checkbox in self.class_checkboxes.items():
                current_selections[code] = checkbox.isChecked()
                if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                    current_weights[code] = self.weight_spinboxes[code].value()
        
        # Repopulate the UI
        self._populate_classes()
        
        # ✅ Restore selections AND weights
        for code, is_checked in current_selections.items():
            if code in self.class_checkboxes:
                self.class_checkboxes[code].setChecked(is_checked)
                print(f"   ✅ Restored class {code}: checked={is_checked}")
        
        for code, weight in current_weights.items():
            if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                self.weight_spinboxes[code].setValue(weight)
                print(f"   ✅ Restored weight for class {code}: {weight}")
        
        print(f"✅ Refreshed {len(self.class_checkboxes)} classes from Display Mode with preserved states")
    
    def _populate_classes(self):
        """Load classes from app_window.class_palette and create checkboxes"""
        # Clear existing
        for i in reversed(range(self.class_grid.count())):
            widget = self.class_grid.itemAt(i).widget()
            if widget:
                widget.deleteLater()
        
        self.class_checkboxes.clear()
        
        if not hasattr(self.app_window, 'class_palette'):
            no_data = QLabel("⚠️ No class data available. Please load a point cloud first.")
            self.class_grid.addWidget(no_data, 0, 0, 1, 5)
            return
        
        # ✅ Set column stretch for better layout
        self.class_grid.setColumnStretch(0, 0)   # Checkbox
        self.class_grid.setColumnStretch(1, 0)   # Color
        self.class_grid.setColumnStretch(2, 0)   # Code
        self.class_grid.setColumnStretch(3, 2)   # Description
        self.class_grid.setColumnStretch(4, 1)   # Weight
        
        # Add header row
        header_row = 0

        checkbox_header = QLabel("")
        self.class_grid.addWidget(checkbox_header, header_row, 0)

        color_header = QLabel("█")
        color_header.setStyleSheet("font-weight: bold; color: #cccccc;")
        self.class_grid.addWidget(color_header, header_row, 1)

        code_header = QLabel("Code")
        code_header.setStyleSheet("font-weight: bold; color: #cccccc;")
        self.class_grid.addWidget(code_header, header_row, 2)

        desc_header = QLabel("Description")
        desc_header.setStyleSheet("font-weight: bold; color: #cccccc;")
        self.class_grid.addWidget(desc_header, header_row, 3)

        weight_header = QLabel("Weight")
        weight_header.setStyleSheet("font-weight: bold; color: #cccccc;")
        self.class_grid.addWidget(weight_header, header_row, 4)

        lvl_header = QLabel("Level")
        lvl_header.setStyleSheet("font-weight: bold; color: #cccccc;")
        self.class_grid.addWidget(lvl_header, header_row, 5)
        
        row = 1
        self.weight_spinboxes = {}
        
        for code, entry in sorted(self.app_window.class_palette.items()):
            desc = entry.get("description", f"Class {code}")
            color = entry.get("color", (128, 128, 128))
            lvl = entry.get("lvl", "")
            draw = entry.get("draw", "")
            
            # Checkbox
            # Checkbox
            checkbox = QCheckBox()

            # ✅ CRITICAL: Check if we have preset data for this view
            default_checked = True  # Default to checked
            if self.mode == "display" and hasattr(self, 'view_configs') and hasattr(self, 'view_selector'):
                current_view_idx = self.view_selector.currentIndex()
                if current_view_idx in self.view_configs:
                    if code in self.view_configs[current_view_idx]:
                        default_checked = self.view_configs[current_view_idx][code].get("show", True)
                        print(f"   📋 Class {code}: preset visibility = {default_checked}")

            checkbox.setChecked(default_checked)
            checkbox.setStyleSheet("""
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    border-radius: 4px;
                    border: 2px solid #569cd6;
                }
                QCheckBox::indicator:unchecked {
                    background-color: #2d2d30;
                    border-color: #666666;
                }
                QCheckBox::indicator:checked {
                    background-color: #0e639c;
                    border-color: #007acc;
                }
            """)
            self.class_checkboxes[code] = checkbox
            self.class_grid.addWidget(checkbox, row, 0)
            
            # Color
            color_label = QLabel("█")
            r, g, b = color
            color_label.setStyleSheet(f"color: rgb({r}, {g}, {b}); font-size: 20px;")
            self.class_grid.addWidget(color_label, row, 1)
            
            # Code
            code_label = QLabel(str(code))
            code_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
            self.class_grid.addWidget(code_label, row, 2)
            
            # Description
            desc_label = QLabel(desc)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: #cccccc;")
            self.class_grid.addWidget(desc_label, row, 3)
            
            # ✅ CRITICAL: Weight spinbox with value from view_configs
            # ✅ Weight spinbox - load from view_configs if available
            weight_spin = QDoubleSpinBox()
            weight_spin.setRange(0.1, 10.0)
            weight_spin.setSingleStep(0.1)
            weight_spin.setMinimumWidth(70)

            # ✅ CRITICAL: Load weight from view_configs if exists, otherwise use defaults
            default_weight = 1.0
            if self.mode == "display" and hasattr(self, 'view_selector'):
                current_view_idx = self.view_selector.currentIndex()
                
                # Check if we have saved weight in view_configs
                if (hasattr(self, 'view_configs') and 
                    current_view_idx in self.view_configs and 
                    code in self.view_configs[current_view_idx]):
                    # Use saved weight from preset
                    default_weight = self.view_configs[current_view_idx][code].get("weight", 1.0)
                    print(f"      📋 Loaded weight for class {code}: {default_weight} (from preset)")
                else:
                    # Use default weight based on view type
                    if current_view_idx == 0:
                        default_weight = 1.0  # Main View
                    else:
                        default_weight = 0.5  # Cross-section views
                    print(f"      🆕 Using default weight for class {code}: {default_weight}")
            else:
                default_weight = 1.0  # Fallback

            weight_spin.setValue(default_weight)
            weight_spin.valueChanged.connect(lambda val, c=code: self._on_weight_changed(c, val))
            self.class_grid.addWidget(weight_spin, row, 4)

            self.weight_spinboxes[code] = weight_spin

            # Level
            lvl_text = str(lvl) if lvl else "-"
            lvl_label = QLabel(lvl_text)
            lvl_label.setStyleSheet("color: #999999; font-style: italic; padding: 4px;")
            lvl_label.setAlignment(Qt.AlignCenter)
            lvl_label.setMinimumWidth(60)
            self.class_grid.addWidget(lvl_label, row, 5)
            
            self.class_grid.setColumnMinimumWidth(0, 30)
            self.class_grid.setColumnMinimumWidth(1, 30)
            self.class_grid.setColumnMinimumWidth(2, 50)
            self.class_grid.setColumnMinimumWidth(3, 150)
            self.class_grid.setColumnMinimumWidth(4, 80)
            self.class_grid.setColumnMinimumWidth(5, 80)
            row += 1
        
        print(f"✅ Loaded {len(self.class_checkboxes)} classes with weights from view_configs")
        
        if self.mode == "display":
            if not hasattr(self, 'view_configs'):
                self.view_configs = {}
            self._last_view_idx = 0
        
    
    def _select_all(self):
        """Check all class checkboxes"""
        for checkbox in self.class_checkboxes.values():
            checkbox.setChecked(True)
    
    def _clear_all(self):
        """Uncheck all class checkboxes"""
        for checkbox in self.class_checkboxes.values():
            checkbox.setChecked(False)
    
    def get_selected_classes(self):
        """Return dict of selected classes with their info + updated weights"""
        result = {}
        
        for code, checkbox in self.class_checkboxes.items():
            if code in self.app_window.class_palette:
                entry = self.app_window.class_palette[code]
                
                # Get weight from spinbox (user may have edited it)
                weight = 1.0
                if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                    weight = self.weight_spinboxes[code].value()
                
                result[code] = {
                    "show": checkbox.isChecked(),
                    "description": entry.get("description", ""),
                    "color": entry.get("color", (128, 128, 128)),
                    "weight": weight,  # Use edited weight
                    "draw": entry.get("draw", ""),
                    "lvl": entry.get("lvl", "")
                }
        
        return result
    
    def get_shading_parameters(self):
        """Return shading parameters (only for shading mode)"""
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
        """Pre-select classes from existing preset"""
        for code, checkbox in self.class_checkboxes.items():
            if code in classes_dict:
                is_visible = classes_dict[code].get("show", True)
                checkbox.setChecked(is_visible)
    
    def set_shading_parameters(self, params):
        """Load existing shading parameters"""
        if self.mode != "shading":
            return
        
        self.az_spin.setValue(params.get("azimuth", 45.0))
        self.angle_spin.setValue(params.get("angle", 45.0))
        self.ambient_spin.setValue(params.get("ambient", 0.1))
        self.quality_spin.setValue(params.get("quality", 100.0))
        self.speed_spin.setValue(params.get("speed", 1))
    
    def get_target_view(self):
        """
        ✅ NEW: Return selected target view index
        Only valid for display mode
        """
        if self.mode == "display" and hasattr(self, 'view_selector'):
            return self.view_selector.currentIndex()
        return 0  # Default to Main View
    
    def set_target_view(self, view_idx):
        """
        ✅ NEW: Set target view from existing preset
        """
        if self.mode == "display" and hasattr(self, 'view_selector'):
            if 0 <= view_idx < self.view_selector.count():
                self.view_selector.setCurrentIndex(view_idx)
                
    def _animate_row_state(self, row, is_checked):
        """Animate row when checkbox state changes"""
        # Get all widgets in this row
        checkbox = self.class_grid.itemAtPosition(row, 0).widget()
        color_label = self.class_grid.itemAtPosition(row, 1).widget()
        code_label = self.class_grid.itemAtPosition(row, 2).widget()
        desc_label = self.class_grid.itemAtPosition(row, 3).widget()
        lvl_label = self.class_grid.itemAtPosition(row, 4).widget()
        
        if is_checked:
            # Green glow animation on check
            self._apply_glow(color_label, "#00ff00", duration=300)
            # Full opacity
            for widget in [color_label, code_label, desc_label, lvl_label]:
                widget.setStyleSheet(widget.styleSheet().replace("opacity: 0.4;", ""))
        else:
            # Red fade animation on uncheck
            self._apply_glow(color_label, "#ff0000", duration=300)
            # Dim to 40% opacity
            QTimer.singleShot(300, lambda: self._dim_row(row))                
                
    def _apply_glow(self, widget, color, duration=300):
        """Apply temporary glow effect"""
        original_style = widget.styleSheet()
        
        # Apply glow
        widget.setStyleSheet(f"{original_style}; background-color: {color}; border-radius: 4px;")
        
        # Remove glow after duration
        QTimer.singleShot(duration, lambda: widget.setStyleSheet(original_style))

    def _dim_row(self, row):
        """Dim unchecked rows to 40% opacity"""
        widgets = [
            self.class_grid.itemAtPosition(row, 1).widget(),  # color
            self.class_grid.itemAtPosition(row, 2).widget(),  # code
            self.class_grid.itemAtPosition(row, 3).widget(),  # desc
            self.class_grid.itemAtPosition(row, 4).widget()   # lvl
        ]
        
        for widget in widgets:
            if widget:
                current_style = widget.styleSheet()
                widget.setStyleSheet(f"{current_style}; opacity: 0.4;")
                
    def _on_weight_changed(self, code, value):
        """Called when user changes weight - persist to app_window"""
        if code in self.app_window.class_palette:
            self.app_window.class_palette[code]["weight"] = value
            print(f"✅ Updated weight for class {code}: {value}")

    def _sync_from_display_mode(self):
        """Sync border and weights from current Display Mode state"""
        # Sync border from display mode
        if hasattr(self.app_window, 'display_border_percent'):
            self.border_spin.setValue(self.app_window.display_border_percent)
            print(f"✅ Synced border: {self.app_window.display_border_percent}%")
        
        # Sync weights from class_palette
        for code, entry in self.app_window.class_palette.items():
            if code in self.weight_spinboxes:
                weight = entry.get("weight", 1.0)
                self.weight_spinboxes[code].setValue(weight)
        
        print("✅ Synced all weights from Display Mode")
    def _sync_border(self):
        """Sync border from current Display Mode state"""
        if hasattr(self.app_window, 'display_border_percent'):
            self.border_spin.setValue(self.app_window.display_border_percent)
            print(f"✅ Synced border: {self.app_window.display_border_percent}%")
        else:
            print("⚠️ No display_border_percent found in app_window")
          
                
                

        
    def get_all_view_configs(self):
        """Return configuration for SINGLE selected view"""
        if not hasattr(self, 'view_configs'):
            self.view_configs = {}
        
        # Get selected view index
        selected_view_idx = 0
        if hasattr(self, 'view_selector'):
            selected_view_idx = self.view_selector.currentIndex()
        
        # Build final config for SINGLE view
        result = {
            "border_percent": self.border_spin.value() if hasattr(self, 'border_spin') else 0,
            "views": {}
        }
        
        # Only include the SINGLE selected view
        if selected_view_idx in self.view_configs:
            result["views"][selected_view_idx] = self.view_configs[selected_view_idx]
            print(f"🔍 Returning config for SINGLE view {selected_view_idx} with user-edited weights")
        
        return result
    
        
        
    def _on_ok_clicked(self):
        """Save configuration for SINGLE selected view and close dialog"""
        if self.mode == "display" and hasattr(self, 'view_selector'):
            # Get selected view index
            selected_view_idx = self.view_selector.currentIndex()
            
            print(f"\n{'='*60}")
            print(f"💾 SAVING SINGLE VIEW CONFIGURATION")
            print(f"{'='*60}")
            print(f"   Selected View: {selected_view_idx} ({self.view_selector.currentText()})")
            
            # Build configuration for SINGLE view
            config = {}
            for code, checkbox in self.class_checkboxes.items():
                if code in self.app_window.class_palette:
                    entry = self.app_window.class_palette[code]
                    
                    # ✅ GET ACTUAL WEIGHT FROM SPINBOX (user-edited value)
                    actual_weight = 1.0
                    if hasattr(self, 'weight_spinboxes') and code in self.weight_spinboxes:
                        actual_weight = self.weight_spinboxes[code].value()
                    
                    config[code] = {
                        "show": checkbox.isChecked(),
                        "weight": actual_weight,  # ✅ USE ACTUAL EDITED WEIGHT
                        "description": entry.get("description", ""),
                        "color": entry.get("color", (128, 128, 128)),
                        "draw": entry.get("draw", ""),
                        "lvl": entry.get("lvl", "")
                    }
            
            # Store SINGLE view configuration
            if not hasattr(self, 'view_configs'):
                self.view_configs = {}
            
            self.view_configs[selected_view_idx] = config
            
            visible_count = sum(1 for c in config.values() if c['show'])
            print(f"   ✅ Saved {visible_count} visible classes with user-edited weights")
            print(f"{'='*60}\n")
        
        # Store border in app_window
        if self.mode == "display" and hasattr(self, 'border_spin'):
            border_val = self.border_spin.value()
            self.app_window.display_border_percent = border_val
            print(f"✅ Stored border: {border_val}%")
        
        self.accept()
        
    def _on_view_selector_changed(self, new_index):
        """When user changes view selection, update all weights"""
        print(f"\n📍 View selector changed to index {new_index}")
        
        # Repopulate classes with correct weights for new view
        self._populate_classes()
        
        # Determine correct weight for this view
        if new_index == 0:
            weight = 1.0
            view_name = "Main View"
        else:
            weight = 0.5
            view_name = ["View 1", "View 2", "View 3", "View 4", "Cut Section View"][new_index - 1]
        
        print(f"   ✅ Repopulated classes for {view_name} with weight={weight}")
            
        

               

class ShortcutManager(QWidget):
    applied = Signal(dict)
    instance = None
   
    def __init__(self, app_window, parent=None):
        # ✅ FIX 1: Robust Parent Finding (Production Pattern)
        # Ensures we attach to the actual window widget to link minimize behavior
        from PySide6.QtWidgets import QWidget
        target_parent = None
       
        # Priority: Passed Parent -> App Window -> App.window
        if parent and isinstance(parent, QWidget):
            target_parent = parent
        elif isinstance(app_window, QWidget):
            target_parent = app_window
        elif hasattr(app_window, 'window') and isinstance(app_window.window, QWidget):
            target_parent = app_window.window
 
        # Initialize with correct parent
        super().__init__(target_parent)
       
        self.setWindowTitle("Configure Shortcuts")
       
        # ✅ FIX 2: Use Qt.Window instead of Qt.Tool
        # - Qt.Tool = No minimize button (Floating Palette)
        # - Qt.Window = Has Minimize/Maximize/Close buttons
        # Because target_parent is set, it will automatically minimize when the main app minimizes.
        self.setWindowFlags(Qt.Window)
       
        self.resize(900, 500)
 
        self.app_window = app_window
        self.current_mnu_path = None
        self.settings = QSettings("NakshaAI", "LidarApp")
       
        self.setStyleSheet(DARK_STYLESHEET)
 
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
 
        # Table - now expands to fill space
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Modifier", "Key", "Tool", "Classes"])
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        # Add bottom padding inside the scrollable table area
        self.table.setStyleSheet("""
            QTableWidget {
                padding-bottom: 0px;
            }
            QTableWidget::item {
                padding: 3px;
            }
        """)
        # Add margin to the viewport to create space at bottom when scrolling
        self.table.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                margin-bottom: 80px;
            }
        """)
        self.table.setStyleSheet(self.table.styleSheet() + "QTableWidget { padding-bottom: 5px; }")
        layout.addWidget(self.table, stretch=1)
        layout.addSpacing(25)
        # Make table columns stretch to fill width
        # Make table columns stretch to fill width
       # Make table columns stretch to fill width
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        # Classes column gets remaining space automatically
 
        # Buttons
        btns = QHBoxLayout()
        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("add_btn")
        self.del_btn = QPushButton("-")
        self.del_btn.setObjectName("del_btn")
        self.load_btn = QPushButton("Load")
        self.save_btn = QPushButton("Save As...")
        self.save_btn.setObjectName("save_btn")
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("apply_btn")
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.clicked.connect(self.close)
       
        for b in [self.add_btn, self.del_btn, self.load_btn, self.save_btn, self.apply_btn, self.cancel_btn]:
            btns.addWidget(b)
        layout.addLayout(btns)
 
        # Connections
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
 
    def on_item_clicked(self, item):
        """Prevent Classes column from being edited with single click"""
        if item.column() == 3:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
 
    # ✅ NEW: Check for duplicate key combinations
    def _is_key_duplicate(self, mod, key, current_row):
        """Check if this modifier+key combo already exists (excluding current row)"""
        for row in range(self.table.rowCount()):
            if row == current_row:
                continue
           
            mod_combo = self.table.cellWidget(row, 0)
            key_combo = self.table.cellWidget(row, 1)
           
            if mod_combo and key_combo:
                existing_mod = mod_combo.currentText().lower()
                existing_key = key_combo.currentText().upper()
               
                if existing_mod == mod.lower() and existing_key == key.upper():
                    return True, row
        return False, -1
 
    # ✅ NEW: Validate on combo box change
    def _on_key_changed(self, row):
        """Called when modifier or key changes - check for duplicates"""
        mod_combo = self.table.cellWidget(row, 0)
        key_combo = self.table.cellWidget(row, 1)
       
        if not mod_combo or not key_combo:
            return
       
        mod = mod_combo.currentText()
        key = key_combo.currentText()
       
        is_dup, dup_row = self._is_key_duplicate(mod, key, row)
       
        if is_dup:
            QMessageBox.warning(
                self,
                "Duplicate Shortcut",
                f"⚠️ {mod}+{key} is already assigned to row {dup_row + 1}!\n\n"
                "Each shortcut key can only be used once.\n"
                "Please choose a different key or modifier."
            )
            # Reset to F1 to avoid conflict
            key_combo.setCurrentText("F1")
 
    def on_add(self):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Modifier dropdown
        mod_combo = QComboBox()
        mod_combo.addItems([
            "alt", "ctrl", "shift",
            "alt+shift", "ctrl+alt",
            "ctrl+shift", "ctrl+alt+shift", "none"
        ])
        mod_combo.setFocusPolicy(Qt.StrongFocus)
        mod_combo.installEventFilter(self)
        # mod_combo.currentTextChanged.connect(lambda: self._on_key_changed(row))
        mod_combo.currentTextChanged.connect(lambda _, r=row: self._on_key_changed(r))

        self.table.setCellWidget(row, 0, mod_combo)

        # Key dropdown (F1–F12 + 0–9 + A–Z + Space)
        key_combo = QComboBox()
        keys = [f"F{i}" for i in range(1, 13)]  # F1-F12
        # keys += [str(i) for i in range(0, 10)]   # 0-9
        keys += [chr(i) for i in range(65, 91)]  # A-Z
        keys.append("Space")                      # Space
        key_combo.addItems(keys)
        key_combo.setCurrentText("F1")
        key_combo.setFocusPolicy(Qt.StrongFocus)
        key_combo.installEventFilter(self)
        key_combo.currentTextChanged.connect(lambda _, r=row: self._on_key_changed(r))
        self.table.setCellWidget(row, 1, key_combo)

        # Tool dropdown
        tool_combo = QComboBox()
        tool_combo.addItems(TOOLS)
        tool_combo.setFocusPolicy(Qt.StrongFocus)
        tool_combo.installEventFilter(self)
        tool_combo.currentTextChanged.connect(lambda t, r=row: self._toggle_class_cell(r, t))
        self.table.setCellWidget(row, 2, tool_combo)

        # Classes placeholder
        item = QTableWidgetItem("Any → Any")
        item.setData(Qt.UserRole, encode_classes(None, None))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, 3, item)

    #Added by bala
    @staticmethod
    def apply_shortcuts_from_settings(app_window):
        """
        ✅ NEW: Apply shortcuts from QSettings without opening dialog
        Called by Ctrl+Shift+S shortcut
        
        This is like Ctrl+Shift+D for Display Mode - applies saved settings instantly!
        """
        print(f"\n{'='*60}")
        print(f"⚡ APPLYING SHORTCUTS FROM SETTINGS (Ctrl+Shift+S)")
        print(f"{'='*60}")
        
        try:
            # Read from QSettings (same as auto_load_shortcuts)
            settings = QSettings("NakshaAI", "LidarApp")
            shortcuts_data = settings.value("shortcuts", None)
            
            if shortcuts_data is None:
                print("   ⚠️ No saved shortcuts found in QSettings")
                if hasattr(app_window, 'statusBar'):
                    app_window.statusBar().showMessage(
                        "⚠️ No shortcuts configured - Open Shortcut Manager first",
                        3000
                    )
                print(f"{'='*60}\n")
                return
            
            # Parse saved shortcuts
            if isinstance(shortcuts_data, str):
                shortcuts_list = json.loads(shortcuts_data)
            else:
                shortcuts_list = shortcuts_data
            
            print(f"   📋 Found {len(shortcuts_list)} shortcuts in storage")
            
            # Build shortcuts dictionary (same logic as on_apply)
            shortcuts = {}
            simple_tools = (
                "CrossSectionRect", "CutSectionRect", "CutFromCross", "CutFromCut",
                "TopView", "Depth", "RGB", "Intensity", "Elevation", "Class"
            )
            
            for entry in shortcuts_list:
                modifier = entry.get("modifier", "alt")
                key = entry.get("key", "F1")
                tool = entry.get("tool", "AboveLine")
                
                # Build shortcut key tuple
                mod = modifier.lower()
                key_upper = key.upper()
                
                # Handle DisplayMode presets
                if tool == "DisplayMode":
                    preset_payload = entry.get("display_preset")
                    if preset_payload:
                        shortcuts[(mod, key_upper)] = {
                            "tool": "DisplayMode",
                            "preset": preset_payload
                        }
                        print(f"      ✅ {mod}+{key_upper} → DisplayMode preset")
                    continue
                
                # Handle ShadingMode presets
                if tool == "ShadingMode":
                    preset_payload = entry.get("shading_preset")
                    if preset_payload:
                        shortcuts[(mod, key_upper)] = {
                            "tool": "ShadingMode",
                            "preset": preset_payload
                        }
                        print(f"      ✅ {mod}+{key_upper} → ShadingMode preset")
                    continue
                
                # Handle DrawSettings presets
                if tool == "DrawSettings":
                    preset_payload = entry.get("draw_preset")
                    if preset_payload:
                        shortcuts[(mod, key_upper)] = {
                            "tool": "DrawSettings",
                            "preset": preset_payload
                        }
                        print(f"      ✅ {mod}+{key_upper} → DrawSettings preset")
                    continue

                # Handle simple tools
                if tool in simple_tools:
                    shortcuts[(mod, key_upper)] = {
                        "tool": tool,
                        "from": None,
                        "to": None
                    }
                    print(f"      ✅ {mod}+{key_upper} → {tool}")
                else:
                    # Tools with class mapping
                    from_cls = entry.get("from_classes")
                    to_cls = entry.get("to_class")
                    
                    shortcuts[(mod, key_upper)] = {
                        "tool": tool,
                        "from": from_cls,
                        "to": to_cls
                    }
                    print(f"      ✅ {mod}+{key_upper} → {tool} [{from_cls} → {to_cls}]")
            
            # Apply to app_window
            app_window.shortcuts = shortcuts
            
            # ✅ CRITICAL: Sync to view_palettes (same as on_apply)
            if not hasattr(app_window, 'view_palettes'):
                app_window.view_palettes = {}
            
            # Sync DisplayMode presets to view_palettes
            saved_weights = {}
            if hasattr(app_window, 'display_mode_dialog') and app_window.display_mode_dialog:
                dlg = app_window.display_mode_dialog
                
                # Save current weights
                if hasattr(dlg, 'view_palettes'):
                    for view_idx, palette in dlg.view_palettes.items():
                        saved_weights[view_idx] = {}
                        for code, info in palette.items():
                            saved_weights[view_idx][code] = info.get('weight', 1.0)
            
            for (mod, key), shortcut_info in shortcuts.items():
                if shortcut_info.get("tool") != "DisplayMode":
                    continue
                
                preset = shortcut_info.get("preset")
                if not preset or not preset.get("views"):
                    continue
                
                for view_idx_raw, class_configs in preset.get("views", {}).items():
                    view_idx = int(view_idx_raw)
                    slot_palette = {}
                    
                    for code_raw, info in class_configs.items():
                        code = int(code_raw)
                        
                        # Preserve user-edited weights
                        weight = info.get("weight", 1.0)
                        if view_idx in saved_weights and code in saved_weights[view_idx]:
                            weight = saved_weights[view_idx][code]
                        
                        slot_palette[code] = {
                            "show": bool(info.get("show", True)),
                            "color": tuple(info.get("color", (128, 128, 128))),
                            "weight": float(weight),
                        }
                    
                    app_window.view_palettes[view_idx] = slot_palette
            
            # Sync to Display Mode dialog if open
            if hasattr(app_window, 'display_mode_dialog') and app_window.display_mode_dialog:
                dlg = app_window.display_mode_dialog
                
                for (mod, key), shortcut_info in shortcuts.items():
                    if shortcut_info.get("tool") != "DisplayMode":
                        continue
                    
                    preset = shortcut_info.get("preset")
                    if not preset or not preset.get("views"):
                        continue
                    
                    for view_idx_raw, class_configs in preset.get("views", {}).items():
                        view_idx = int(view_idx_raw)
                        
                        if view_idx not in dlg.view_palettes:
                            dlg.view_palettes[view_idx] = {}
                        
                        for code_raw, info in class_configs.items():
                            code = int(code_raw)
                            
                            preserved_weight = info.get("weight", 1.0)
                            if view_idx in saved_weights and code in saved_weights[view_idx]:
                                preserved_weight = saved_weights[view_idx][code]
                            
                            dlg.view_palettes[view_idx][code] = {
                                "show": bool(info.get("show", True)),
                                "color": tuple(info.get("color", (128, 128, 128))),
                                "weight": float(preserved_weight),
                                "description": str(info.get("description", "")),
                                "lvl": str(info.get("lvl", "")),
                                "draw": info.get("draw", "")
                            }
                        
                        if view_idx not in dlg.slot_shows:
                            dlg.slot_shows[view_idx] = {}
                        
                        for code_raw, info in class_configs.items():
                            code = int(code_raw)
                            dlg.slot_shows[view_idx][code] = bool(info.get("show", True))
                
                print("   ✅ Synced shortcuts to Display Mode dialog")
            
            # Status message
            if hasattr(app_window, 'statusBar'):
                app_window.statusBar().showMessage(
                    f"✅ {len(shortcuts)} shortcuts applied from settings (Ctrl+Shift+S)",
                    2500
                )
            
            print(f"   ✅ Applied {len(shortcuts)} shortcuts to app_window")
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"❌ Failed to apply shortcuts from settings: {e}")
            import traceback
            traceback.print_exc()
            
            if hasattr(app_window, 'statusBar'):
                app_window.statusBar().showMessage(
                    f"❌ Failed to apply shortcuts: {e}",
                    3000
                )
            print(f"{'='*60}\n")

            ####

    def on_delete(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            
    def eventFilter(self, obj, event):
        """Block mouse wheel scrolling on combo boxes"""
        if isinstance(obj, QComboBox):
            if event.type() == QEvent.Wheel:
                event.ignore()
                return True  # Block the wheel event
        return super().eventFilter(obj, event)        
 
    def _toggle_class_cell(self, row, tool_text):
        """Disable class selection for some tools. DisplayMode and ShadingMode open their respective dialogs to store presets."""
        
        # ✅ Tools that don't need ANY configuration - just "N/A"
        no_config_tools = (
            "CrossSectionRect", "CutSectionRect", "CutFromCross", "CutFromCut", 
            "TopView", 
            "Depth", "RGB", "Intensity", "Elevation", "Class"  # ✅ Display modes - no config needed
        )
        
        if tool_text in no_config_tools:
            item = QTableWidgetItem("N/A")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_classes(None, None))
            self.table.setItem(row, 3, item)
            return  # ✅ RETURN HERE - don't open any dialog

        if tool_text == "DisplayMode":
            item = QTableWidgetItem("Click/Double-click to configure display preset")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_display_preset({
                "classes": {},
                "slot": 0,
                "target_view": 0,
                "color_mode": 0,
                "border_percent": 0,
                "force_refresh": True
            }))
            self.table.setItem(row, 3, item)
            
            # Open Display Mode dialog when user selects this tool
            if not self._is_loading_shortcuts:
                self._open_display_mode_for_row(row)
            return
        
        if tool_text == "ShadingMode":
            item = QTableWidgetItem("Preset: Not configured yet")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_shading_preset({
                "azimuth": 45.0,
                "angle": 45.0,
                "ambient": 0.1,
                "quality": 100.0,
                "speed": 1,
                "classes": {}
            }))
            self.table.setItem(row, 3, item)
            
            # Open shading dialog when user selects this tool
            if not self._is_loading_shortcuts:
                self._open_shading_mode_for_row(row)
            return
        
        if tool_text == "DrawSettings":
            item = QTableWidgetItem("Click/Double-click to configure draw preset")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_draw_preset({"tools": {}}))
            self.table.setItem(row, 3, item)

            if not self._is_loading_shortcuts:
                self._open_draw_settings_for_row(row)
            return

        # Default tools: keep existing class mapping behavior
        item = QTableWidgetItem("Any → Any")
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        item.setData(Qt.UserRole, encode_classes(None, None))
        self.table.setItem(row, 3, item)
    




    def on_class_edit(self, row, col):
        """
        Only opens on DOUBLE-CLICK
        ✅ FIXED: Always reconnects signals (works on all systems)
        """
        if col != 3:
            return

        tool_combo = self.table.cellWidget(row, 2)
        tool = tool_combo.currentText() if tool_combo else ""
        
        # ✅ NEW: Display modes and view tools don't need configuration
        if tool in ("Depth", "RGB", "Intensity", "Elevation", "Class", 
                    "CrossSectionRect", "CutSectionRect", "CutFromCross", "CutFromCut", "TopView"):
            print(f"ℹ️ {tool} has no class configuration - N/A")
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

        # ✅ CRITICAL FIX: Ensure ClassPicker exists
        if not hasattr(self.app_window, "class_picker") or self.app_window.class_picker is None:
            from .class_picker import ClassPicker
            self.app_window.class_picker = ClassPicker(self.app_window, parent=self)
        
        picker = self.app_window.class_picker
        
        # ✅ CRITICAL FIX: ALWAYS disconnect old connections first (prevents duplicates)
        try:
            picker.from_list.itemSelectionChanged.disconnect(self.update_classes_from_picker)
        except:
            pass  # No existing connection
        
        try:
            picker.to_combo.currentIndexChanged.disconnect(self.update_classes_from_picker)
        except:
            pass  # No existing connection
        
        # ✅ CRITICAL FIX: ALWAYS reconnect signals (ensures it works on all systems)
        picker.from_list.itemSelectionChanged.connect(self.update_classes_from_picker)
        picker.to_combo.currentIndexChanged.connect(self.update_classes_from_picker)
        
        print(f"✅ Signals reconnected for row {row}")
        
        # Show the picker
        picker.show()
        picker.raise_()
        picker.activateWindow()

        # ✅ Load existing values from the table cell
        cell = self.table.item(row, 3)
        if cell and cell.data(Qt.UserRole):
            from_cls, to_cls = decode_classes(cell.data(Qt.UserRole))
            
            # Set FROM classes (multi-select)
            if from_cls is not None:
                picker.from_list.clearSelection()
                from_list = from_cls if isinstance(from_cls, list) else [from_cls]
                for i in range(picker.from_list.count()):
                    item = picker.from_list.item(i)
                    if item.data(Qt.UserRole) in from_list:
                        item.setSelected(True)
                print(f"   📋 Loaded FROM classes: {from_list}")
            else:
                # Select "Any" option if no specific classes
                for i in range(picker.from_list.count()):
                    item = picker.from_list.item(i)
                    if item.data(Qt.UserRole) is None:  # "Any" option
                        item.setSelected(True)
                        break
                print(f"   📋 Loaded FROM: Any")
            
            # Set TO class
            if to_cls is not None:
                idx = picker.to_combo.findData(to_cls)
                if idx >= 0:
                    picker.to_combo.setCurrentIndex(idx)
                    print(f"   📋 Loaded TO class: {to_cls}")
            else:
                # Set to "Any" option
                idx = picker.to_combo.findData(None)
                if idx >= 0:
                    picker.to_combo.setCurrentIndex(idx)
                    print(f"   📋 Loaded TO: Any")

    def _get_or_create_display_mode_dialog(self):
        dlg = getattr(self.app_window, "display_mode_dialog", None)
        if dlg is None:
            from gui.display_mode import DisplayModeDialog
            dlg = DisplayModeDialog(self.app_window)
            self.app_window.display_mode_dialog = dlg
        return dlg


    def _open_display_mode_for_row(self, row: int):
        """Open lightweight class picker for Display Mode - Single view selection"""
        self._pending_display_mode_row = row
        
        # ── Source of truth: TABLE CELL (only ever written by on_accepted, so
        #    it holds exactly what the user configured in the picker).
        #    app.shortcuts may have been mutated by _sync_to_displaymode_shortcuts
        #    (Display Mode Apply → shortcut) and must NOT override the user's
        #    explicitly saved picker state.
        existing_preset = None
        mod_combo = self.table.cellWidget(row, 0)
        key_combo = self.table.cellWidget(row, 1)
        if mod_combo and key_combo:
            mod = mod_combo.currentText().lower()
            key = key_combo.currentText().upper()

        # 1️⃣  Table cell first — this is the canonical user-configured preset
        cell = self.table.item(row, 3)
        if cell:
            existing_preset = decode_display_preset(cell.data(Qt.UserRole))
            if existing_preset:
                print(f"   ✅ Loaded preset from table cell (user-configured state)")

        # 2️⃣  Fall back to app.shortcuts only when the table cell has no data
        #     (e.g. a newly-added row before the first OK)
        if existing_preset is None and mod_combo and key_combo:
            shortcut_info = getattr(self.app_window, 'shortcuts', {}).get((mod, key))
            if shortcut_info and shortcut_info.get("tool") == "DisplayMode":
                existing_preset = shortcut_info.get("preset")
                if existing_preset:
                    print(f"   ⚠️  Loaded preset from app.shortcuts (table cell empty)")

        # ✅ CRITICAL: Always create a FRESH picker (don't reuse)
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

            # ── Preset border is authoritative — do NOT let the live Display
            #    Mode dialog override it here. The preset was saved by the user
            #    and must be shown exactly as configured. ──
            picker.border_spin.setValue(border_percent)

            if views:
                views = {int(k): v for k, v in views.items()}
                first_view_idx = min(views.keys())
                view_classes = views[first_view_idx]

                picker.view_selector.blockSignals(True)
                picker.view_selector.setCurrentIndex(first_view_idx)
                picker.view_selector.blockSignals(False)

                if not hasattr(picker, 'view_configs'):
                    picker.view_configs = {}
                picker.view_configs[first_view_idx] = {int(k): v for k, v in view_classes.items()}

                # ── No live-overlay here: view_configs is loaded from the table
                #    cell (user-configured), not from app.view_palettes / the
                #    Display Mode dialog. This prevents Display Mode Apply from
                #    silently clobbering the user's custom weights in the picker. ──

                picker._populate_classes()

                for code, checkbox in picker.class_checkboxes.items():
                    if code in view_classes:
                        checkbox.setChecked(view_classes[code].get("show", True))
                    else:
                        checkbox.setChecked(True)

                print(f"📂 Loaded existing preset for view {first_view_idx}: "
                      f"{sum(1 for c in view_classes.values() if c.get('show'))} visible")

        else:
            # FRESH PRESET: no saved data yet — start with defaults
            print(f"📋 Creating fresh preset - defaulting to Main View")

            picker.view_selector.blockSignals(True)
            picker.view_selector.setCurrentIndex(0)
            picker.view_selector.blockSignals(False)

            # No seeding from live view_palettes: a fresh preset should start
            # clean so the user explicitly chooses what they want.
            picker._populate_classes()
            print(f"✅ Fresh preset initialized for Main View")
        
        # ✅ Connect to handle OK button (no need to disconnect, fresh instance)
        def on_accepted():
            # Get condef on_accepted():
            # Get configuration for SINGLE view
            all_configs = picker.get_all_view_configs()
            border_percent = all_configs.get("border_percent", 0)
            view_configs = all_configs.get("views", {})
            
            if not view_configs:
                print("⚠️ No view configured")
                return
            
            # Get the SINGLE view (should only be one)
            view_idx = list(view_configs.keys())[0]
            view_classes = view_configs[view_idx]
            
            # Build preset for SINGLE view
            preset = {
                "border_percent": border_percent,
                "views": {view_idx: view_classes},
                "force_refresh": True
            }
            
            # ✅ Create summary WITH WEIGHT INFO
            visible = sum(1 for c in view_classes.values() if c.get("show"))
            view_name = ["Main", "View 1", "View 2", "View 3", "View 4", "Cut"][view_idx]
            
            # ✅ Get weight information
            weights = [c.get("weight", 1.0) for c in view_classes.values()]
            unique_weights = sorted(set(weights))
            
            # Build compact summary
            if len(unique_weights) == 1:
                weight_info = f"W={unique_weights[0]:.1f}"
            else:
                weight_info = f"W={min(weights):.1f}-{max(weights):.1f}"
            
            # summary = f"{view_name}: {visible}vis, B={border_percent}%, {weight_info}"
            summary = f"{view_name}: {visible}vis, B={border_percent:.1f}%, W={weight_info}"
            
            item = QTableWidgetItem(summary)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_display_preset(preset))
            self.table.setItem(row, 3, item)

            # ── PATCH: keep app.shortcuts in sync so the NEXT open of this
            #          picker reads fresh weights, not stale ones ──
            _mod_w = self.table.cellWidget(row, 0)
            _key_w = self.table.cellWidget(row, 1)
            if _mod_w and _key_w:
                _m = _mod_w.currentText().lower()
                _k = _key_w.currentText().upper()
                _sh = getattr(self.app_window, 'shortcuts', {})
                if (_m, _k) in _sh and _sh[(_m, _k)].get('tool') == 'DisplayMode':
                    _sh[(_m, _k)]['preset'] = preset
                    print(f"   🔗 app.shortcuts[{_m}+{_k}] preset updated with fresh weights")

            print(f"✅ Saved: {summary}")

            # ── Persist immediately to QSettings so weights survive restart ──
            # (auto_save_shortcuts is normally only called on ShortcutManager Apply;
            #  call it here too so picker OK alone is enough to make changes durable)
            try:
                self.auto_save_shortcuts()
                print(f"   💾 QSettings updated — preset will survive restart")
            except Exception as _e:
                print(f"   ⚠️ auto_save_shortcuts failed: {_e}")

            # ✅ CRITICAL: Close and cleanup the picker
            picker.close()
            picker.deleteLater()
            self._display_picker = None

        picker.accepted.connect(on_accepted)
        
        # ✅ Also handle rejection (Cancel button)
        def on_rejected():
            print("❌ Display mode configuration cancelled")
            picker.close()
            picker.deleteLater()
            self._display_picker = None
        
        picker.rejected.connect(on_rejected)
        
        # ✅ Show as non-modal child window
        picker.show()
        picker.raise_()
        picker.activateWindow()
    
    
    def _open_shading_mode_for_row(self, row: int):
        """Open lightweight class picker for shading mode"""
        self._pending_shading_mode_row = row
        
        # Get existing preset if any
        cell = self.table.item(row, 3)
        existing_preset = decode_shading_preset(cell.data(Qt.UserRole)) if cell else None
        existing_classes = existing_preset.get("classes", {}) if existing_preset else {}
        
        # ✅ Create or reuse picker
        if not hasattr(self, '_shading_picker') or self._shading_picker is None:
            self._shading_picker = ClassVisibilityPicker(self.app_window, mode="shading", parent=self)
        
        picker = self._shading_picker
        
        # Load existing selections
        if existing_classes:
            picker.set_selected_classes(existing_classes)
        
        # Load existing shading parameters
        if existing_preset:
            picker.set_shading_parameters(existing_preset)
        
        # ✅ Disconnect old signal if exists
        try:
            picker.accepted.disconnect()
        except:
            pass
        
        # ✅ Connect to handle OK button
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
            azimuth = preset["azimuth"]
            angle = preset["angle"]
            speed = preset["speed"]
            summary = f"Shading: {azimuth}°/{angle}°, {visible_count} visible, Speed={speed}"
            
            item = QTableWidgetItem(summary)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_shading_preset(preset))
            self.table.setItem(row, 3, item)
            
            print(f"✅ Saved ShadingMode preset: {visible_count} classes visible")
            picker.hide()  # ✅ Hide after saving
        
        picker.accepted.connect(on_accepted)
        
        # ✅ Show as non-modal child window
        picker.show()
        picker.raise_()
        picker.activateWindow()

    def _open_draw_settings_for_row(self, row: int):
            """Open draw settings picker for a shortcut row."""
            cell = self.table.item(row, 3)
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
                # Highlight active tool first if present
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
                self.table.setItem(row, 3, item)

                print(f"✅ Saved DrawSettings preset into row {row + 1}: {summary}")
                picker.close()
                picker.deleteLater()
                self._draw_picker = None

            def on_rejected():
                print("❌ Draw settings configuration cancelled")
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

            view_name = "Main View" if slot == 0 else (f"View {slot}" if slot <= 4 else ("Cut Section View" if slot == 5 else f"View {slot}"))
            summary = f"Preset: {len(visible)} visible ({view_name})"

            item = QTableWidgetItem(summary)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_display_preset(payload))
            self.table.setItem(row, 3, item)

            print(f"✅ Saved DisplayMode preset into row {row + 1}: {summary}")

        finally:
            self._pending_display_mode_row = None
            dlg = getattr(self.app_window, "display_mode_dialog", None)
            if dlg is not None:
                try:
                    dlg.applied.disconnect(self._capture_display_mode_preset)
                except Exception:
                    pass
    
 

    def update_classes_from_picker(self):
        """
        Update shortcut table from ClassPicker
        ✅ FIXED: More robust with better logging
        """
        if not self.is_editing_shortcuts:
            print("⏭️ update_classes_from_picker: Not in editing mode")
            return

        if self._active_row is None:
            print("⏭️ update_classes_from_picker: No active row")
            return
        
        if not hasattr(self.app_window, 'class_picker') or self.app_window.class_picker is None:
            print("❌ update_classes_from_picker: ClassPicker doesn't exist!")
            return
        
        picker = self.app_window.class_picker
        selected_items = picker.from_list.selectedItems()
        
        print(f"\n{'='*60}")
        print(f"📝 UPDATE_CLASSES_FROM_PICKER (Row {self._active_row})")
        print(f"{'='*60}")
        print(f"   Selected items count: {len(selected_items)}")
        
        # ✅ Build FROM classes
        if not selected_items:
            from_cls = None
            from_txt = "Any"
            print(f"   FROM: None (Any)")
        else:
            # Check if "Any" is selected
            any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
            if any_selected:
                from_cls = None
                from_txt = "Any"
                print(f"   FROM: 'Any' option selected")
            else:
                from_cls = [item.data(Qt.UserRole) for item in selected_items]
                from_txt = ", ".join(str(c) for c in from_cls)
                print(f"   FROM: {from_cls}")
        
        # ✅ Build TO class
        to_cls = picker.to_combo.currentData()
        to_txt = picker.to_combo.currentText().split(" - ")[0] if to_cls is not None else "Any"
        print(f"   TO: {to_cls} ({to_txt})")
        
        # ✅ Update table cell
        display_text = f"{from_txt} → {to_txt}"
        item = QTableWidgetItem(display_text)
        item.setData(Qt.UserRole, encode_classes(from_cls, to_cls))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(self._active_row, 3, item)
        
        print(f"   ✅ Updated cell: '{display_text}'")
        print(f"{'='*60}\n")    

    def save_mnu_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Shortcut File", "", "Menu Files (*.mnu)")
        if not path:
            return

        simple_tools = (
            "CrossSectionRect", "CutSectionRect", "CutFromCross", "CutFromCut", 
            "TopView", "Depth", "RGB", "Intensity", "Elevation", "Class"
        )

        with open(path, "w") as f:
            for row in range(self.table.rowCount()):
                mod_combo = self.table.cellWidget(row, 0)
                key_combo = self.table.cellWidget(row, 1)
                tool_combo = self.table.cellWidget(row, 2)
                mod = mod_combo.currentText().lower() if mod_combo else "alt"
                key = key_combo.currentText().upper() if key_combo else "F1"
                tool = tool_combo.currentText() if tool_combo else "AboveLine"
                
                cell = self.table.item(row, 3)
                
                # Handle DisplayMode presets
                if tool == "DisplayMode":
                    preset_json = cell.data(Qt.UserRole) if cell else ""
                    display_text = cell.text() if cell else ""  # ✅ GET THE TEXT
                    f.write(f"{mod}\t{key}\t{tool}\t{preset_json}\t{display_text}\n")  # ✅ SAVE TEXT AS 5TH COLUMN
                    continue
                    
                if tool == "ShadingMode":
                    preset_json = cell.data(Qt.UserRole) if cell else ""
                    shading_text = cell.text() if cell else ""  # ✅ GET THE TEXT
                    f.write(f"{mod}\t{key}\t{tool}\t{preset_json}\t{shading_text}\n")  # ✅ SAVE TEXT AS 5TH COLUMN
                    continue
                
                if tool == "DrawSettings":
                    preset_json = cell.data(Qt.UserRole) if cell else ""
                    draw_text = cell.text() if cell else ""
                    f.write(f"{mod}\t{key}\t{tool}\t{preset_json}\t{draw_text}\n")
                    continue

                # ✅ Handle simple tools (including display modes)        
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

        self._is_loading_shortcuts = True  # ✅ Set flag BEFORE clearing table
        
        try:
            self.table.setRowCount(0)

            with open(path, "r") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) < 3:
                        continue

                    row = self.table.rowCount()
                    self.table.insertRow(row)

                    # Modifier combo
                    mod_combo = QComboBox()
                    mod_combo.addItems([
                        "alt", "ctrl", "shift",
                        "alt+shift", "ctrl+alt",
                        "ctrl+shift", "ctrl+alt+shift", "none"
                    ])
                    mod_combo.setCurrentText(parts[0])
                    mod_combo.currentTextChanged.connect(lambda _, r=row: self._on_key_changed(r))
                    mod_combo.setFocusPolicy(Qt.StrongFocus)
                    mod_combo.installEventFilter(self)
                    self.table.setCellWidget(row, 0, mod_combo)

                    # Key combo (F1–F12 + 0–9 + A–Z + Space)
                    key_combo = QComboBox()
                    keys = [f"F{i}" for i in range(1, 13)]  # F1-F12
                    keys += [chr(i) for i in range(65, 91)]  # A-Z
                    keys.append("Space")                      # Space
                    key_combo.addItems(keys)
                    key_combo.setCurrentText(parts[1])
                    key_combo.currentTextChanged.connect(lambda _, r=row: self._on_key_changed(r))
                    key_combo.setFocusPolicy(Qt.StrongFocus)
                    key_combo.installEventFilter(self)
                    self.table.setCellWidget(row, 1, key_combo)

                    # Tool combo - ✅ Block signal temporarily during loading
                    tool_combo = QComboBox()
                    tool_combo.addItems(TOOLS)
                    tool_combo.blockSignals(True)  # ✅ Block signals while setting value
                    tool_combo.setCurrentText(parts[2])
                    tool_combo.blockSignals(False)  # ✅ Re-enable signals
                    tool_combo.currentTextChanged.connect(lambda t, r=row: self._toggle_class_cell(r, t))
                    tool_combo.setFocusPolicy(Qt.StrongFocus)
                    tool_combo.installEventFilter(self)
                    self.table.setCellWidget(row, 2, tool_combo)

                    if parts[2] == "DisplayMode":
                        # For DisplayMode, parts[3] = JSON preset, parts[4] = display text
                        if len(parts) > 3 and parts[3].strip():
                            preset_payload = decode_display_preset(parts[3])
                            saved_text = parts[4] if len(parts) > 4 else ""  # ✅ GET SAVED TEXT FROM FILE
                        
                            # ✅ USE SAVED TEXT IF EXISTS
                            if saved_text:
                                item = QTableWidgetItem(saved_text)
                                item.setData(Qt.UserRole, parts[3])  # Store the original JSON string
                            # ✅ Otherwise regenerate (backward compatibility)
                            elif preset_payload and preset_payload.get("views"):
                                views = preset_payload.get("views", {})
                                border_percent = preset_payload.get("border_percent", 0)
                            
                                # Build summary
                                view_count = len(views)
                                view_names = []
                                total_visible = 0
                            
                                for view_idx in sorted(views.keys()):
                                    visible = sum(1 for c in views[view_idx].values() if c.get("show"))
                                    total_visible += visible
                                    if view_idx == 0:
                                        view_names.append("Main")
                                    elif view_idx == 5:
                                        view_names.append("Cut")
                                    else:
                                        view_names.append(f"V{view_idx}")
                            
                                view_summaries = []
                                for view_idx in sorted(views.keys()):
                                    visible = sum(1 for c in views[view_idx].values() if c.get("show"))
                                    weights = [c.get("weight", 1.0) for c in views[view_idx].values()]
                                    unique_weights = sorted(set(weights))
                                    if len(unique_weights) == 1:
                                        weight_info = f"{unique_weights[0]:.1f}"
                                    else:
                                        weight_info = f"{min(weights):.1f}-{max(weights):.1f}"
                                    if view_idx == 0:
                                        view_name = "Main"
                                    elif view_idx == 5:
                                        view_name = "Cut"
                                    else:
                                        view_name = f"View {view_idx}"
                                    view_summaries.append(f"{view_name}: {visible}vis, B={border_percent:.1f}%, W={weight_info}")
                                
                                summary = "; ".join(view_summaries)
                        
                            # ✅ LEGACY: Handle old single-view format (backwards compatibility)
                            elif preset_payload and preset_payload.get("classes"):
                                visible = [
                                    c for c, info in preset_payload["classes"].items()
                                    if info.get("show")
                                ]
                                slot = preset_payload.get("target_view", preset_payload.get("slot", 0))
                                view_name = (
                                    "Main View" if slot == 0 else
                                    (f"View {slot}" if slot <= 4 else
                                    ("Cut Section View" if slot == 5 else f"View {slot}"))
                                )
                                item = QTableWidgetItem(f"Preset: {len(visible)} visible ({view_name})")
                                item.setData(Qt.UserRole, parts[3])  # Store the original JSON string  

                            else:
                                item = QTableWidgetItem("Click/Double-click to configure display preset")
                                item.setData(Qt.UserRole, encode_display_preset({
                                    "classes": {},
                                    "slot": 0,
                                    "target_view": 0,
                                    "color_mode": 0,
                                    "border_percent": 0,
                                    "force_refresh": True
                                }))
                        else:
                            item = QTableWidgetItem("Click/Double-click to configure display preset")
                            item.setData(Qt.UserRole, encode_display_preset({
                                "classes": {},
                                "slot": 0,
                                "target_view": 0,
                                "color_mode": 0,
                                "border_percent": 0,
                                "force_refresh": True
                            }))
                        
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, 3, item)
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
                        self.table.setItem(row, 3, item)
                        continue                    
                    
                    if parts[2] == "ShadingMode":
                        if len(parts) > 3 and parts[3].strip():
                            preset_payload = decode_shading_preset(parts[3])
                            saved_text = parts[4] if len(parts) > 4 else ""  # ✅ GET SAVED TEXT FROM FILE
                            
                            # ✅ USE SAVED TEXT IF EXISTS
                            if saved_text:
                                item = QTableWidgetItem(saved_text)
                                item.setData(Qt.UserRole, parts[3])
                            # ✅ Otherwise regenerate
                            elif preset_payload and preset_payload.get("classes"):
                                visible = [
                                    c for c, info in preset_payload["classes"].items()
                                    if info.get("show")
                                ]
                                azimuth = preset_payload.get("azimuth", 45.0)
                                angle = preset_payload.get("angle", 45.0)
                                speed = preset_payload.get("speed", 1)
                                item = QTableWidgetItem(f"Shading: {azimuth}°/{angle}°, {len(visible)} visible, Speed={speed}")
                                item.setData(Qt.UserRole, parts[3])  # Store the original JSON string
                            else:
                                item = QTableWidgetItem("Preset: Not configured yet")
                                item.setData(Qt.UserRole, encode_shading_preset({
                                    "azimuth": 45.0,
                                    "angle": 45.0,
                                    "ambient": 0.1,
                                    "quality": 100.0,
                                    "speed": 1,
                                    "classes": {}
                                }))
                        else:
                            item = QTableWidgetItem("Preset: Not configured yet")
                            item.setData(Qt.UserRole, encode_shading_preset({
                                "azimuth": 45.0,
                                "angle": 45.0,
                                "ambient": 0.1,
                                "quality": 100.0,
                                "speed": 1,
                                "classes": {}
                            }))
                        
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, 3, item)
                        continue

                    # Classes cell for other tools
                    if parts[2] in ("CrossSectionRect", "CutSectionRect", "CutFromCross", "CutFromCut", "TopView",  "Depth", "RGB", "Intensity", "Elevation", "Class"):
                        item = QTableWidgetItem("N/A")
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setData(Qt.UserRole, encode_classes(None, None))
                        self.table.setItem(row, 3, item)
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

                    if isinstance(from_cls, list):
                        from_txt = ", ".join(str(c) for c in from_cls)
                    else:
                        from_txt = "Any"

                    to_txt = str(to_cls) if to_cls is not None else "Any"

                    item = QTableWidgetItem(f"{from_txt} → {to_txt}")
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setData(Qt.UserRole, encode_classes(from_cls, to_cls))
                    self.table.setItem(row, 3, item)

            self.current_mnu_path = path
            print(f"✅ Shortcuts loaded from: {path}")
            
        finally:
            self._is_loading_shortcuts = False  # ✅ Always reset flag

    def on_apply(self):
        # ✅ Set flag to preserve user-edited weights during shortcut sync
        self._applying_shortcuts = True
    
        try:
            # ✅ Final duplicate check before applying
            seen_keys = {}
            for row in range(self.table.rowCount()):
                mod_combo = self.table.cellWidget(row, 0)
                key_combo = self.table.cellWidget(row, 1)
    
                if mod_combo and key_combo:
                    mod = mod_combo.currentText().lower()
                    key = key_combo.currentText().upper()
                    combo = (mod, key)
        
                    if combo in seen_keys:
                        QMessageBox.critical(
                            self,
                            "Cannot Apply",
                            f"❌ Duplicate shortcut detected!\n\n"
                            f"{mod}+{key} is used in both:\n"
                            f"  • Row {seen_keys[combo] + 1}\n"
                            f"  • Row {row + 1}\n\n"
                            f"Please fix duplicates before applying."
                        )
                        return
                    seen_keys[combo] = row

            # Build shortcuts dictionary
            shortcuts = {}
    
            # ✅ Tools that don't need class mapping
            simple_tools = (
                "CrossSectionRect", "CutSectionRect", "CutFromCross", "CutFromCut",
                "TopView", "Depth", "RGB", "Intensity", "Elevation", "Class"
            )
    
            for row in range(self.table.rowCount()):
                mod_combo = self.table.cellWidget(row, 0)
                key_combo = self.table.cellWidget(row, 1)
                tool_combo = self.table.cellWidget(row, 2)
                mod = mod_combo.currentText().lower() if mod_combo else "alt"
                key = key_combo.currentText().upper() if key_combo else "F1"
                tool = tool_combo.currentText() if tool_combo else None

                if tool == "DisplayMode":
                    cell = self.table.item(row, 3)
                    preset_payload = decode_display_preset(cell.data(Qt.UserRole)) if cell else None

                    # ✅ AUTO-FIX: create default preset if missing
                    if not preset_payload or not preset_payload.get("views"):
                        print(f"⚠️ DisplayMode preset missing at row {row + 1}, auto-creating default")

                        preset_payload = {
                            "border_percent": getattr(self.app_window, "display_border_percent", 0),
                            "views": {
                                0: {
                                    code: {
                                        "show": entry.get("show", True),
                                        "weight": entry.get("weight", 1.0)
                                    }
                                    for code, entry in self.app_window.class_palette.items()
                                }
                            },
                            "force_refresh": True
                        }

                    shortcuts[(mod, key)] = {"tool": "DisplayMode", "preset": preset_payload}
                    continue

        
                if tool == "ShadingMode":
                    cell = self.table.item(row, 3)
                    preset_payload = decode_shading_preset(cell.data(Qt.UserRole)) if cell else None

                    if not preset_payload or not preset_payload.get("classes"):
                        QMessageBox.warning(
                            self,
                            "ShadingMode preset missing",
                            f"Row {row + 1} uses ShadingMode but has no preset.\n"
                            "Click the Classes cell, configure shading, then click Apply."
                        )
                        return

                    shortcuts[(mod, key)] = {"tool": "ShadingMode", "preset": preset_payload}
                    print(f"   Row {row}: {mod}+{key} → ShadingMode preset saved")
                    continue

                if tool == "DrawSettings":
                    cell = self.table.item(row, 3)
                    preset_payload = decode_draw_preset(cell.data(Qt.UserRole)) if cell else None
                    shortcuts[(mod, key)] = {"tool": "DrawSettings", "preset": preset_payload}
                    print(f"   Row {row}: {mod}+{key} → DrawSettings preset saved")
                    continue

                # ✅ Handle simple tools (including display modes)
                if tool in simple_tools:
                    shortcuts[(mod, key)] = {"tool": tool, "from": None, "to": None}
                    print(f"   Row {row}: {mod}+{key} → {tool}")
                else:
                    # Tools with class mapping
                    cell = self.table.item(row, 3)
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
                    print(f"   Row {row}: {mod}+{key} → {tool}, from={from_cls}, to={to_cls}")

            self.app_window.shortcuts = shortcuts
        
            # Sync shortcut presets into view_palettes
            if not hasattr(self.app_window, 'view_palettes'):
                self.app_window.view_palettes = {}
            if hasattr(self.app_window, 'display_mode_dialog') and self.app_window.display_mode_dialog:
                dlg = self.app_window.display_mode_dialog
                
                # Save current weights from dialog
                saved_weights = {}
                if hasattr(dlg, 'view_palettes'):
                    for view_idx, palette in dlg.view_palettes.items():
                        saved_weights[view_idx] = {}
                        for code, info in palette.items():
                            saved_weights[view_idx][code] = info.get('weight', 1.0)
                
                # Inject preserved weights INTO the shortcut presets (not the other way)
                for (mod, key), shortcut_info in shortcuts.items():
                    if shortcut_info.get("tool") != "DisplayMode":
                        continue
                    preset = shortcut_info.get("preset")
                    if not preset or not preset.get("views"):
                        continue
                    for view_idx_raw, class_configs in preset.get("views", {}).items():
                        view_idx = int(view_idx_raw)
                        for code_raw, info in class_configs.items():
                            code = int(code_raw)
                            if view_idx in saved_weights and code in saved_weights[view_idx]:
                                info["weight"] = saved_weights[view_idx][code]
                
                print("✅ Preserved dialog weights into shortcut presets")

            print(f"   ℹ️ Shortcut presets stored (applied on keypress, not now)")
                    #
                            
            print("✅ Shortcuts applied to app_window:", self.app_window.shortcuts)
            self.applied.emit(shortcuts)

            self.auto_save_shortcuts()
            self.is_editing_shortcuts = False
        
            if hasattr(self.app_window, 'class_picker') and self.app_window.class_picker:
                self.app_window.class_picker.hide()

            self.close()
            QTimer.singleShot(0, self._sort_table_by_modifier) ##Addedd by bala
    
        finally:
            # ✅ Always clear the flag
            self._applying_shortcuts = False
 
    def on_cancel(self):
        self.is_editing_shortcuts = False
        self.close()
 
    def closeEvent(self, event):
        """
        ✅ FIXED: Clean disconnect when closing
        """
        self.is_editing_shortcuts = False
        
        # Disconnect signals to prevent memory leaks
        if hasattr(self.app_window, 'class_picker') and self.app_window.class_picker:
            try:
                self.app_window.class_picker.from_list.itemSelectionChanged.disconnect(
                    self.update_classes_from_picker
                )
            except:
                pass
            
            try:
                self.app_window.class_picker.to_combo.currentIndexChanged.disconnect(
                    self.update_classes_from_picker
                )
            except:
                pass
        
        super().closeEvent(event) 
    
    @staticmethod
    def open_manager(app_window):
        if ShortcutManager.instance is None:
            ShortcutManager.instance = ShortcutManager(app_window, parent=app_window)  # ✅ Explicit parent
        if not ShortcutManager.instance.isVisible():
            ShortcutManager.instance.show()
            ShortcutManager.instance.raise_()
            ShortcutManager.instance.activateWindow()
        else:
            ShortcutManager.instance.raise_()
            ShortcutManager.instance.activateWindow()
        return ShortcutManager.instance
 
    def auto_load_shortcuts(self):
        """
        ✅ Load shortcuts automatically when ShortcutManager opens
        Uses QSettings for cross-platform persistence
        """
        self._is_loading_shortcuts = True
        try:
            shortcuts_data = self.settings.value("shortcuts", None)

            if shortcuts_data is None:
                print("ℹ️ No saved shortcuts found")
                return

            try:
                # Parse saved shortcuts
                if isinstance(shortcuts_data, str):
                    shortcuts_list = json.loads(shortcuts_data)
                else:
                    shortcuts_list = shortcuts_data

                self.table.setRowCount(0)

                for entry in shortcuts_list:
                    row = self.table.rowCount()
                    self.table.insertRow(row)

                    # Modifier
                    mod_combo = QComboBox()
                    mod_combo.addItems([
                        "alt", "ctrl", "shift", "alt+shift",
                        "ctrl+alt", "ctrl+shift", "ctrl+alt+shift", "none"
                    ])
                    mod_combo.setCurrentText(entry.get("modifier", "alt"))
                    mod_combo.currentTextChanged.connect(lambda _, r=row: self._on_key_changed(r))
                    mod_combo.setFocusPolicy(Qt.StrongFocus)
                    mod_combo.installEventFilter(self)
                    self.table.setCellWidget(row, 0, mod_combo)

                    # Key (F1-F12 + 0-9 + A-Z + Space)
                    key_combo = QComboBox()
                    keys = [f"F{i}" for i in range(1, 13)]   # F1-F12
                    keys += [chr(i) for i in range(65, 91)]  # A-Z
                    keys.append("Space")                     # Space
                    key_combo.addItems(keys)
                    key_combo.setCurrentText(entry.get("key", "F1"))
                    key_combo.currentTextChanged.connect(lambda _, r=row: self._on_key_changed(r))
                    key_combo.setFocusPolicy(Qt.StrongFocus)
                    key_combo.installEventFilter(self)
                    self.table.setCellWidget(row, 1, key_combo)

                    # Tool
                    tool_combo = QComboBox()
                    tool_combo.addItems(TOOLS)
                    tool_combo.setCurrentText(entry.get("tool", "AboveLine"))
                    tool_combo.currentTextChanged.connect(lambda t, r=row: self._toggle_class_cell(r, t))
                    tool_combo.setFocusPolicy(Qt.StrongFocus)
                    tool_combo.installEventFilter(self)
                    self.table.setCellWidget(row, 2, tool_combo)

                    # Classes / Preset (DisplayMode support)
                    tool = entry.get("tool")
                    if tool == "DisplayMode":
                        preset_payload = entry.get("display_preset")

                        if preset_payload and preset_payload.get("views"):
                            views = preset_payload.get("views", {})
                            border_percent = preset_payload.get("border_percent", 0)

                            view_summaries = []
                            for view_idx in sorted(views.keys()):
                                view_classes = views[view_idx]
                                visible = sum(1 for c in view_classes.values() if c.get("show"))
                                weights = [c.get("weight", 1.0) for c in view_classes.values()]
                                if not weights:
                                    continue
                                unique_weights = sorted(set(round(w, 2) for w in weights))
                                if len(unique_weights) == 1:
                                    weight_info = f"W={unique_weights[0]:.1f}"
                                else:
                                    weight_info = f"W={min(weights):.1f}-{max(weights):.1f}"
                                if view_idx == 0:
                                    view_name = "Main"
                                elif view_idx == 5:
                                    view_name = "Cut"
                                else:
                                    view_name = f"View {view_idx}"
                                view_summaries.append(
                                    f"{view_name}: {visible}vis, B={border_percent:.1f}%, {weight_info}"
                                )
                            summary = "; ".join(view_summaries) if view_summaries else "DisplayMode preset"
                            item = QTableWidgetItem(summary)
                            item.setData(Qt.UserRole, encode_display_preset(preset_payload))

                        elif preset_payload:
                            # Legacy single-view format (no views key)
                            item = QTableWidgetItem("Click/Double-click to configure display preset")
                            item.setData(Qt.UserRole, encode_display_preset(preset_payload))
                        else:
                            item = QTableWidgetItem("Click/Double-click to configure display preset")
                            item.setData(
                                Qt.UserRole,
                                encode_display_preset({
                                    "views": {},
                                    "border_percent": 0,
                                    "force_refresh": True,
                                })
                            )

                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, 3, item)
                        continue
 
                    if tool == "DrawSettings":
                        preset_payload = entry.get("draw_preset")
                        saved_text = entry.get("draw_text", "")

                        if preset_payload and saved_text:
                            item = QTableWidgetItem(saved_text)
                            item.setData(Qt.UserRole, encode_draw_preset(preset_payload))
                        elif preset_payload:
                            item = QTableWidgetItem("Draw preset")
                            item.setData(Qt.UserRole, encode_draw_preset(preset_payload))
                        else:
                            item = QTableWidgetItem("Click/Double-click to configure draw preset")
                            item.setData(Qt.UserRole, encode_draw_preset({"tools": {}}))

                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, 3, item)
                        continue


                    # ✅ Handle ShadingMode presets
                    if tool == "ShadingMode":
                        preset_payload = entry.get("shading_preset")
                        saved_text = entry.get("shading_text", "")  # ✅ GET SAVED TEXT
                        
                        if preset_payload and saved_text:
                            item = QTableWidgetItem(saved_text)  # ✅ USE EXACT SAVED TEXT
                            item.setData(Qt.UserRole, encode_shading_preset(preset_payload))
                        elif preset_payload and preset_payload.get("classes"):
                            # Fallback - regenerate
                            visible = [
                                c for c, info in preset_payload["classes"].items()
                                if info.get("show")
                            ]
                            azimuth = preset_payload.get("azimuth", 45.0)
                            angle = preset_payload.get("angle", 45.0)
                            speed = preset_payload.get("speed", 1)
                            item = QTableWidgetItem(f"Shading: {azimuth}°/{angle}°, {len(visible)} visible, Speed={speed}")
                            item.setData(Qt.UserRole, encode_shading_preset(preset_payload))
                        else:
                            item = QTableWidgetItem("Click/Double-click to configure shading preset")
                            item.setData(Qt.UserRole, encode_shading_preset({
                                "azimuth": 45.0,
                                "angle": 45.0,
                                "ambient": 0.1,
                                "quality": 100.0,
                                "speed": 1,
                                "classes": {}
                            }))
                        
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        self.table.setItem(row, 3, item)
                        continue  
                        
                    if tool in ("CrossSectionRect", "CutSectionRect", "CutFromCross", "CutFromCut", 
                                                                "TopView", "Depth", "RGB", "Intensity", "Elevation", "Class"):
                        item = QTableWidgetItem("N/A")
                        item.setData(Qt.UserRole, encode_classes(None, None))
                    else:
                        from_cls = entry.get("from_classes")
                        to_cls = entry.get("to_class")

                        from_txt = ", ".join(str(c) for c in from_cls) if from_cls else "Any"
                        to_txt = str(to_cls) if to_cls is not None else "Any"

                        item = QTableWidgetItem(f"{from_txt} → {to_txt}")
                        item.setData(Qt.UserRole, encode_classes(from_cls, to_cls))

                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, 3, item)
                    ###

                print(f"✅ Loaded {len(shortcuts_list)} shortcuts from persistent storage")
                QTimer.singleShot(0, self._sort_table_by_modifier) # ✅ Sort by modifier after loading

            except Exception as e:
                print(f"❌ Error loading shortcuts: {e}")

        finally:
            self._is_loading_shortcuts = False ##

    def auto_save_shortcuts(self):    ######
        """
        ✅ Save current shortcuts to persistent storage
        Called automatically when shortcuts are applied
        """
        shortcuts_list = []

        for row in range(self.table.rowCount()):
            mod_combo = self.table.cellWidget(row, 0)
            key_combo = self.table.cellWidget(row, 1)
            tool_combo = self.table.cellWidget(row, 2)

            modifier = mod_combo.currentText() if mod_combo else "alt"
            key = key_combo.currentText() if key_combo else "F1"
            tool = tool_combo.currentText() if tool_combo else "AboveLine"

            entry = {
                "modifier": modifier,
                "key": key,
                "tool": tool
            }

            if tool == "DisplayMode":
                cell = self.table.item(row, 3)
                preset_payload = decode_display_preset(cell.data(Qt.UserRole)) if cell else None
                entry["display_preset"] = preset_payload
                entry["display_text"] = cell.text() if cell else ""  # ✅ SAVE THE EXACT TEXT
                entry["from_classes"] = None
                entry["to_class"] = None
                shortcuts_list.append(entry)
                continue
                
            if tool == "ShadingMode":
                cell = self.table.item(row, 3)
                preset_payload = decode_shading_preset(cell.data(Qt.UserRole)) if cell else None
                entry["shading_preset"] = preset_payload
                entry["shading_text"] = cell.text() if cell else ""  # ✅ SAVE SHADING TEXT TOO
                entry["from_classes"] = None
                entry["to_class"] = None
                shortcuts_list.append(entry)
                continue

            if tool == "DrawSettings":
                cell = self.table.item(row, 3)
                preset_payload = decode_draw_preset(cell.data(Qt.UserRole)) if cell else None
                entry["draw_preset"] = preset_payload
                entry["draw_text"] = cell.text() if cell else ""
                entry["from_classes"] = None
                entry["to_class"] = None
                shortcuts_list.append(entry)
                continue            
            # ----------------------------------------

            if tool not in ("CrossSectionRect", "CutSectionRect", "CutFromCross", "CutFromCut", "TopView"):
                cell = self.table.item(row, 3)
                from_cls, to_cls = decode_classes(cell.data(Qt.UserRole)) if cell else (None, None)
                entry["from_classes"] = from_cls
                entry["to_class"] = to_cls
            else:
                entry["from_classes"] = None
                entry["to_class"] = None

            shortcuts_list.append(entry)

        # Save to QSettings
        self.settings.setValue("shortcuts", json.dumps(shortcuts_list))
        print(f"✅ Saved {len(shortcuts_list)} shortcuts to persistent storage")

    def _sort_table_by_modifier(self):   #Added by bala
        """
        Sort all rows alphabetically by Modifier column.

        Fixed modifier order (alphabetical):
            alt → alt+shift → ctrl → ctrl+alt → ctrl+alt+shift
            → ctrl+shift → none → shift

        Within the same modifier group, keys are ordered:
            F1 → F2 → ... → F12  (numeric, not string)
            → A → B → ... → Z    (alphabetical)
            → Space

        Always called via QTimer.singleShot(0, ...) so it runs AFTER
        the current event loop tick. This prevents wglMakeCurrent errors:
        setRowCount(0) destroys ~36 QComboBox widgets; if called
        synchronously during Apply/Load, pending Qt events cause VTK to
        attempt renders on dead Win32 window handles (code 6 errors).
        Deferring until the event loop is idle eliminates this entirely.
        """
        row_count = self.table.rowCount()
        if row_count < 2:
            return

        MODIFIER_ORDER = {
            "alt":             0,
            "alt+shift":       1,
            "ctrl":            2,
            "ctrl+alt":        3,
            "ctrl+alt+shift":  4,
            "ctrl+shift":      5,
            "none":            6,
            "shift":           7,
        }

        def _key_rank(key):
            """
            Sortable tuple for a key string.
            F-keys numeric (F1 < F2 < ... < F12), then A-Z, then Space.
            Plain string sort would give F1 < F10 < F11 < F12 < F2 — wrong.
            """
            k = key.upper()
            if len(k) >= 2 and k[0] == "F" and k[1:].isdigit():
                return (0, int(k[1:]), "")   # F-keys: numeric order
            if k == "SPACE":
                return (2, 0, "SPACE")        # Space last
            return (1, 0, k)                  # A-Z: alphabetical

        def sort_key(r):
            mod_rank = MODIFIER_ORDER.get(r["mod"].lower(), 99)
            return (mod_rank, _key_rank(r["key"]))

        # ── Snapshot every row into a plain dict before touching the table ──
        rows_data = []
        for row in range(row_count):
            mod_combo  = self.table.cellWidget(row, 0)
            key_combo  = self.table.cellWidget(row, 1)
            tool_combo = self.table.cellWidget(row, 2)
            cell3      = self.table.item(row, 3)

            rows_data.append({
                "mod":         mod_combo.currentText()  if mod_combo  else "none",
                "key":         key_combo.currentText()  if key_combo  else "F1",
                "tool":        tool_combo.currentText() if tool_combo else "AboveLine",
                "cell3_text":  cell3.text()             if cell3      else "",
                "cell3_data":  cell3.data(Qt.UserRole)  if cell3      else None,
                "cell3_flags": cell3.flags()            if cell3      else Qt.ItemIsEnabled,
            })

        rows_data.sort(key=sort_key)

        # ── Rebuild table from sorted snapshot ──
        # Preserve caller's _is_loading_shortcuts state (don't unconditionally
        # reset to False — the outer auto_load_shortcuts finally block owns it).
        prev_loading = self._is_loading_shortcuts
        self._is_loading_shortcuts = True
        try:
            self.table.setRowCount(0)

            for row, rd in enumerate(rows_data):
                self.table.insertRow(row)

                # Modifier combo
                mod_combo = QComboBox()
                mod_combo.addItems([
                    "alt", "ctrl", "shift",
                    "alt+shift", "ctrl+alt",
                    "ctrl+shift", "ctrl+alt+shift", "none"
                ])
                mod_combo.setCurrentText(rd["mod"])
                mod_combo.setFocusPolicy(Qt.StrongFocus)
                mod_combo.installEventFilter(self)
                mod_combo.currentTextChanged.connect(
                    lambda _, r=row: self._on_key_changed(r)
                )
                self.table.setCellWidget(row, 0, mod_combo)

                # Key combo
                key_combo = QComboBox()
                keys = [f"F{i}" for i in range(1, 13)]  # F1-F12
                keys += [chr(i) for i in range(65, 91)] # A-Z
                keys.append("Space")
                key_combo.addItems(keys)
                key_combo.setCurrentText(rd["key"])
                key_combo.setFocusPolicy(Qt.StrongFocus)
                key_combo.installEventFilter(self)
                key_combo.currentTextChanged.connect(
                    lambda _, r=row: self._on_key_changed(r)
                )
                self.table.setCellWidget(row, 1, key_combo)

                # Tool combo — block signals to avoid dialog popups during rebuild
                tool_combo = QComboBox()
                tool_combo.addItems(TOOLS)
                tool_combo.blockSignals(True)
                tool_combo.setCurrentText(rd["tool"])
                tool_combo.blockSignals(False)
                tool_combo.setFocusPolicy(Qt.StrongFocus)
                tool_combo.installEventFilter(self)
                tool_combo.currentTextChanged.connect(
                    lambda t, r=row: self._toggle_class_cell(r, t)
                )
                self.table.setCellWidget(row, 2, tool_combo)

                # Classes cell — restore text + UserRole data + flags exactly
                item = QTableWidgetItem(rd["cell3_text"])
                item.setData(Qt.UserRole, rd["cell3_data"])
                item.setFlags(rd["cell3_flags"])
                self.table.setItem(row, 3, item)

        finally:
            self._is_loading_shortcuts = prev_loading  # restore, don't unconditionally clear

        print(f"✅ Table sorted by Modifier: {row_count} rows in alphabetical order")
          ###

    def _open_shading_mode_for_row(self, row: int):
        """Open lightweight class picker for shading mode"""
        self._pending_shading_mode_row = row
        
        # Get existing preset if any
        cell = self.table.item(row, 3)
        existing_preset = decode_shading_preset(cell.data(Qt.UserRole)) if cell else None
        existing_classes = existing_preset.get("classes", {}) if existing_preset else {}
        
        # Open class visibility picker with shading controls
        picker = ClassVisibilityPicker(self.app_window, mode="shading", parent=self)
        
        # Load existing selections
        if existing_classes:
            picker.set_selected_classes(existing_classes)
        
        # Load existing shading parameters
        if existing_preset:
            picker.set_shading_parameters(existing_preset)
        
        # Show dialog
        if picker.exec() == QDialog.Accepted:
            selected_classes = picker.get_selected_classes()
            shading_params = picker.get_shading_parameters()  # ✅ Get shading settings
            
            # Build preset with shading values + selected classes
            preset = {
                "azimuth": shading_params.get("azimuth", 45.0),
                "angle": shading_params.get("angle", 45.0),
                "ambient": shading_params.get("ambient", 0.1),
                "quality": shading_params.get("quality", 100.0),
                "speed": shading_params.get("speed", 1),
                "classes": selected_classes
            }
            
            # Update table cell
            visible_count = sum(1 for c in selected_classes.values() if c.get("show"))
            azimuth = preset["azimuth"]
            angle = preset["angle"]
            speed = preset["speed"]
            summary = f"Shading: {azimuth}°/{angle}°, {visible_count} visible, Speed={speed}"
            
            item = QTableWidgetItem(summary)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_shading_preset(preset))
            self.table.setItem(row, 3, item)
            
            print(f"✅ Saved ShadingMode preset: {visible_count} classes visible")


    def _capture_shading_preset(self):
        """Capture shading settings from control panel"""
        row = self._pending_shading_mode_row
        if row is None:
            return
        
        try:
            panel = self.app_window.shading_panel
            
            # Get shading parameters
            azimuth = panel.az_spin.value()
            angle = panel.el_spin.value()
            quality = panel.quality_spin.value()
            speed = panel.speed_spin.value()
            ambient = getattr(self.app_window, 'shade_ambient', 0.1)
            
            # Get current class visibility
            classes = {}
            for code, entry in self.app_window.class_palette.items():
                classes[int(code)] = {
                    "show": entry.get("show", True),
                    "color": entry.get("color", (128, 128, 128))
                }
            
            # Build preset
            preset = {
                "azimuth": azimuth,
                "angle": angle,
                "ambient": ambient,
                "quality": quality,
                "speed": speed,
                "classes": classes
            }
            
            # Create summary
            visible = [c for c, info in classes.items() if info.get("show")]
            summary = f"Shading: {azimuth}°/{angle}°, {len(visible)} visible, Speed={speed}"
            
            # Update table cell
            item = QTableWidgetItem(summary)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(Qt.UserRole, encode_shading_preset(preset))
            self.table.setItem(row, 3, item)
            
            print(f"✅ Saved ShadingMode preset into row {row + 1}: {summary}")
            
        finally:
            self._pending_shading_mode_row = None
            try:
                panel.apply_btn.clicked.disconnect(self._capture_shading_preset)
            except:
                pass