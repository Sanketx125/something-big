import json

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from gui.draw_settings_dialog import (
    DEFAULT_DRAW_STYLES,
    TOOL_DISPLAY_NAMES,
    TOOL_ORDER,
    load_draw_settings,
    qcolor_to_vtk,
    save_draw_settings,
    vtk_color_to_qcolor,
)
from gui.shortcut_manager import ShortcutManager, TOOLS, SIMPLE_SHORTCUT_TOOLS


SHORTCUT_MODIFIERS = [
    "alt",
    "ctrl",
    "shift",
    "alt+shift",
    "ctrl+alt",
    "ctrl+shift",
    "ctrl+alt+shift",
    "none",
]

SHORTCUT_KEYS = [f"F{i}" for i in range(1, 13)] + [chr(i) for i in range(65, 91)] + ["Space"]

SHORTCUT_SIMPLE_TOOLS = set(SIMPLE_SHORTCUT_TOOLS)

class SettingsPreviewWidget(QWidget):
    """Small reusable preview for line-based settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = QColor("#ff00ff")
        self._width = 3
        self._style = "solid"
        self.setFixedHeight(64)
        self.setMinimumWidth(220)

    def set_state(self, color: QColor, width: int, style: str):
        self._color = color
        self._width = width
        self._style = style
        self.update()

    def paintEvent(self, event):
        from gui.theme_manager import ThemeColors

        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(ThemeColors.get("bg_secondary")))
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(self._color)
        pen.setWidth(max(1, int(self._width)))
        pen.setStyle(
            {
                "solid": Qt.SolidLine,
                "dashed": Qt.DashLine,
                "dotted": Qt.DotLine,
                "dash-dot": Qt.DashDotLine,
                "dash-dot-dot": Qt.DashDotDotLine,
            }.get(self._style, Qt.SolidLine)
        )
        painter.setPen(pen)

        y = self.height() // 2
        painter.drawLine(20, y, self.width() - 20, y)


class GlobalSettingsDialog(QDialog):
    """Category-based global settings window."""

    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.settings = QSettings("NakshaAI", "LidarApp")

        self._draw_styles = {}
        self._selected_draw_tool = TOOL_ORDER[0]
        self._loading_shortcuts = False

        self.setObjectName("GlobalSettingsDialog")
        self.setProperty("themeStyledDialog", True)
        self.setWindowTitle("Global Settings")
        self.setModal(False)
        self.resize(880, 640)

        self._build_ui()
        self.refresh_theme()
        self._load_values()

    def refresh_theme(self):
        from gui.theme_manager import get_dialog_stylesheet

        self.setStyleSheet(get_dialog_stylesheet())

    def showEvent(self, event):
        self.refresh_theme()
        self._load_values()
        super().showEvent(event)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QLabel("Global Settings")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Manage application settings by category in one place. "
            "This window edits the real settings directly."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        content = QHBoxLayout()
        content.setSpacing(14)

        self.category_list = QListWidget()
        self.category_list.setFixedWidth(180)
        self.category_list.addItems(["Theme", "Shortcuts", "Cross Section", "Draw", "Navigation"])
        self.category_list.currentRowChanged.connect(self._on_category_changed)
        content.addWidget(self.category_list)

        self.category_stack = QStackedWidget()
        self.category_stack.addWidget(self._build_theme_page())
        self.category_stack.addWidget(self._build_shortcuts_page())
        self.category_stack.addWidget(self._build_cross_section_page())
        self.category_stack.addWidget(self._build_draw_page())
        self.category_stack.addWidget(self._build_navigation_page())
        content.addWidget(self.category_stack, 1)

        root.addLayout(content, 1)

        footer = QHBoxLayout()
        self.footer_note = QLabel("Save All applies changes for every category.")
        self.footer_note.setObjectName("dialogCaption")
        footer.addWidget(self.footer_note)
        footer.addStretch()

        self.save_all_btn = QPushButton("Save All")
        self.save_all_btn.setObjectName("primaryBtn")
        self.save_all_btn.clicked.connect(self.save_all_settings)
        footer.addWidget(self.save_all_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        footer.addWidget(self.close_btn)

        root.addLayout(footer)

        self.category_list.setCurrentRow(0)

    def _build_theme_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        group = QGroupBox("Theme")
        form = QFormLayout(group)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")
        form.addRow("Application theme:", self.theme_combo)

        self.canvas_theme_combo = QComboBox()
        self.canvas_theme_combo.addItem("Black", "black")
        self.canvas_theme_combo.addItem("White", "white")
        form.addRow("Canvas theme:", self.canvas_theme_combo)

        self.theme_summary = QLabel()
        self.theme_summary.setObjectName("dialogCaption")
        self.theme_summary.setWordWrap(True)

        layout.addWidget(group)
        layout.addWidget(self.theme_summary)
        layout.addStretch()
        return page

    def _build_shortcuts_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)

        group = QGroupBox("Shortcuts")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        self.shortcuts_summary = QLabel()
        self.shortcuts_summary.setObjectName("dialogCaption")
        self.shortcuts_summary.setWordWrap(True)
        group_layout.addWidget(self.shortcuts_summary)

        self.shortcuts_table = QTableWidget(0, 4)
        self.shortcuts_table.setHorizontalHeaderLabels(["Modifier", "Key", "Tool", "Details"])
        self.shortcuts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.shortcuts_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.shortcuts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.shortcuts_table.verticalHeader().setVisible(False)
        header = self.shortcuts_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        group_layout.addWidget(self.shortcuts_table, 1)

        row_buttons = QHBoxLayout()
        self.shortcut_add_btn = QPushButton("Add Row")
        self.shortcut_add_btn.setObjectName("secondaryBtn")
        self.shortcut_add_btn.clicked.connect(self._add_empty_shortcut_row)
        row_buttons.addWidget(self.shortcut_add_btn)

        self.shortcut_remove_btn = QPushButton("Remove Row")
        self.shortcut_remove_btn.setObjectName("secondaryBtn")
        self.shortcut_remove_btn.clicked.connect(self._remove_selected_shortcut_row)
        row_buttons.addWidget(self.shortcut_remove_btn)

        self.shortcut_reload_btn = QPushButton("Reload Saved")
        self.shortcut_reload_btn.setObjectName("secondaryBtn")
        self.shortcut_reload_btn.clicked.connect(self._load_shortcuts)
        row_buttons.addWidget(self.shortcut_reload_btn)

        row_buttons.addStretch()
        group_layout.addLayout(row_buttons)

        layout.addWidget(group, 1)
        return page

    def _build_cross_section_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        group = QGroupBox("Cross Section")
        form = QVBoxLayout(group)
        form.setSpacing(10)

        size_form = QFormLayout()
        size_form.setHorizontalSpacing(12)
        size_form.setVerticalSpacing(10)

        self.cut_width_spin = QDoubleSpinBox()
        self.cut_width_spin.setDecimals(2)
        self.cut_width_spin.setRange(0.10, 1000.0)
        self.cut_width_spin.setSingleStep(0.25)
        self.cut_width_spin.setSuffix(" m")
        size_form.addRow("Default cut width:", self.cut_width_spin)
        form.addLayout(size_form)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Line color:"))
        self.cross_color_btn = QPushButton()
        self.cross_color_btn.setFixedSize(52, 30)
        self.cross_color_btn.clicked.connect(self._choose_cross_color)
        color_row.addWidget(self.cross_color_btn)
        color_row.addStretch()
        form.addLayout(color_row)

        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Line width:"))
        self.cross_width_slider = QSlider(Qt.Horizontal)
        self.cross_width_slider.setRange(1, 10)
        self.cross_width_slider.valueChanged.connect(self._on_cross_width_changed)
        width_row.addWidget(self.cross_width_slider)
        self.cross_width_label = QLabel("3 px")
        self.cross_width_label.setFixedWidth(42)
        width_row.addWidget(self.cross_width_label)
        form.addLayout(width_row)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Line style:"))
        self.cross_style_combo = QComboBox()
        self.cross_style_combo.addItems(["Solid", "Dashed", "Dotted", "Dash-Dot", "Dash-Dot-Dot"])
        self.cross_style_combo.currentTextChanged.connect(self._update_cross_preview)
        style_row.addWidget(self.cross_style_combo)
        style_row.addStretch()
        form.addLayout(style_row)

        form.addWidget(QLabel("Preview:"))
        self.cross_preview = SettingsPreviewWidget()
        form.addWidget(self.cross_preview)

        reset_row = QHBoxLayout()
        self.cross_reset_btn = QPushButton("Reset Cross Section")
        self.cross_reset_btn.setObjectName("secondaryBtn")
        self.cross_reset_btn.clicked.connect(self._reset_cross_section_controls)
        reset_row.addWidget(self.cross_reset_btn)
        reset_row.addStretch()
        form.addLayout(reset_row)

        self.cross_summary = QLabel()
        self.cross_summary.setObjectName("dialogCaption")
        self.cross_summary.setWordWrap(True)

        layout.addWidget(group)
        layout.addWidget(self.cross_summary)
        layout.addStretch()
        return page

    def _build_draw_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        group = QGroupBox("Draw")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(10)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.draw_tool_combo = QComboBox()
        for tool_key in TOOL_ORDER:
            self.draw_tool_combo.addItem(TOOL_DISPLAY_NAMES.get(tool_key, tool_key), tool_key)
        self.draw_tool_combo.addItem("All Tools (Global)", "__global__")
        self.draw_tool_combo.currentIndexChanged.connect(self._on_draw_tool_changed)
        form.addRow("Tool:", self.draw_tool_combo)
        group_layout.addLayout(form)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Color:"))
        self.draw_color_btn = QPushButton()
        self.draw_color_btn.setFixedSize(52, 30)
        self.draw_color_btn.clicked.connect(self._choose_draw_color)
        color_row.addWidget(self.draw_color_btn)
        color_row.addStretch()
        group_layout.addLayout(color_row)

        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Width:"))
        self.draw_width_slider = QSlider(Qt.Horizontal)
        self.draw_width_slider.setRange(1, 10)
        self.draw_width_slider.valueChanged.connect(self._on_draw_width_changed)
        width_row.addWidget(self.draw_width_slider)
        self.draw_width_label = QLabel("2 px")
        self.draw_width_label.setFixedWidth(42)
        width_row.addWidget(self.draw_width_label)
        group_layout.addLayout(width_row)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style:"))
        self.draw_style_combo = QComboBox()
        self.draw_style_combo.addItems(["Solid", "Dashed", "Dotted", "Dash-Dot", "Dash-Dot-Dot"])
        self.draw_style_combo.currentTextChanged.connect(self._update_draw_preview)
        style_row.addWidget(self.draw_style_combo)
        style_row.addStretch()
        group_layout.addLayout(style_row)

        group_layout.addWidget(QLabel("Preview:"))
        self.draw_preview = SettingsPreviewWidget()
        group_layout.addWidget(self.draw_preview)

        draw_buttons = QHBoxLayout()
        self.draw_reset_tool_btn = QPushButton("Reset Selected Tool")
        self.draw_reset_tool_btn.setObjectName("secondaryBtn")
        self.draw_reset_tool_btn.clicked.connect(self._reset_current_draw_tool)
        draw_buttons.addWidget(self.draw_reset_tool_btn)

        self.draw_reset_all_btn = QPushButton("Reset All Draw Styles")
        self.draw_reset_all_btn.setObjectName("secondaryBtn")
        self.draw_reset_all_btn.clicked.connect(self._reset_all_draw_tools)
        draw_buttons.addWidget(self.draw_reset_all_btn)

        draw_buttons.addStretch()
        group_layout.addLayout(draw_buttons)

        self.draw_summary = QLabel()
        self.draw_summary.setObjectName("dialogCaption")
        self.draw_summary.setWordWrap(True)

        layout.addWidget(group)
        layout.addWidget(self.draw_summary)
        layout.addStretch()
        return page

    def _build_navigation_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        group = QGroupBox("Navigation")
        form = QFormLayout(group)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.zoom_behavior_combo = QComboBox()
        self.zoom_behavior_combo.addItem("Zoom to Center", "center")
        self.zoom_behavior_combo.addItem("Zoom to Cursor", "cursor")
        self.zoom_behavior_combo.addItem("Zoom to Picked Point (MicroStation-like)", "picked_point")
        self.zoom_behavior_combo.currentIndexChanged.connect(self._update_navigation_summary)
        form.addRow("Mouse wheel zoom:", self.zoom_behavior_combo)

        note = QLabel(
            "Center keeps the current behavior. Cursor follows the live mouse position. "
            "Picked Point behaves closer to MicroStation zoom-and-recenter: click a model point first, then wheel zoom keeps bringing that point to the view center."
        )
        note.setObjectName("dialogCaption")
        note.setWordWrap(True)
        form.addRow("", note)

        self.navigation_summary = QLabel()
        self.navigation_summary.setObjectName("dialogCaption")
        self.navigation_summary.setWordWrap(True)

        layout.addWidget(group)
        layout.addWidget(self.navigation_summary)
        layout.addStretch()
        return page

    def _on_category_changed(self, index):
        self.category_stack.setCurrentIndex(max(0, index))

    def _load_values(self):
        self._load_theme_settings()
        self._load_shortcuts()
        self._load_cross_section_settings()
        self._load_draw_settings_page()
        self._load_navigation_settings()

    def _load_theme_settings(self):
        from gui.theme_manager import ThemeManager

        theme_name = ThemeManager.current() or ThemeManager.load_saved_theme()
        index = self.theme_combo.findData(theme_name)
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)

        canvas_theme = ThemeManager.canvas_background_for_theme()
        canvas_index = self.canvas_theme_combo.findData(canvas_theme)
        if canvas_index >= 0:
            self.canvas_theme_combo.setCurrentIndex(canvas_index)

        self.theme_summary.setText(
            f"Current theme is {self.theme_combo.currentText().lower()}. "
            f"Canvas theme: {self.canvas_theme_combo.currentText().lower()}."
        )

    def _load_shortcuts(self):
        shortcuts_data = self.settings.value("shortcuts", None)
        self._loading_shortcuts = True
        self.shortcuts_table.setRowCount(0)

        shortcuts_list = []
        if shortcuts_data is not None:
            try:
                shortcuts_list = json.loads(shortcuts_data) if isinstance(shortcuts_data, str) else shortcuts_data
            except Exception:
                shortcuts_list = []

        for entry in shortcuts_list:
            self._add_shortcut_row(dict(entry))

        self._loading_shortcuts = False
        self._update_shortcuts_summary()

    def _load_cross_section_settings(self):
        cut_width = self.settings.value(
            "cut_section_width",
            getattr(self.app, "default_cut_width", 2.0),
            type=float,
        )
        self.cut_width_spin.setValue(cut_width)

        color_name = self.settings.value("cross_line_color", "#FF00FF", type=str)
        self._cross_color = QColor(color_name)
        self._update_color_button(self.cross_color_btn, self._cross_color)

        width = self.settings.value("cross_line_width", 3, type=int)
        self.cross_width_slider.setValue(width)

        style = self.settings.value("cross_line_style", "solid", type=str)
        self.cross_style_combo.setCurrentText(self._pretty_style_name(style))

        self._update_cross_preview()

    def _load_draw_settings_page(self):
        self._draw_styles = load_draw_settings()
        if self.draw_tool_combo.currentData() is None:
            self.draw_tool_combo.setCurrentIndex(0)
        self._selected_draw_tool = self.draw_tool_combo.currentData() or TOOL_ORDER[0]
        self._load_draw_editor_for_selection()
        self._update_draw_summary()

    def _load_navigation_settings(self):
        zoom_behavior = self.settings.value(
            "view_zoom_behavior",
            getattr(self.app, "zoom_behavior", "center"),
            type=str,
        )
        index = self.zoom_behavior_combo.findData(zoom_behavior)
        if index < 0:
            index = 0
        self.zoom_behavior_combo.setCurrentIndex(index)
        self._update_navigation_summary()

    def _add_empty_shortcut_row(self):
        entry = {
            "modifier": "alt",
            "key": "F1",
            "tool": "AboveLine",
            "from_classes": None,
            "to_class": None,
        }
        self._add_shortcut_row(entry)
        self.shortcuts_table.selectRow(self.shortcuts_table.rowCount() - 1)
        self._update_shortcuts_summary()

    def _add_shortcut_row(self, entry):
        row = self.shortcuts_table.rowCount()
        self.shortcuts_table.insertRow(row)

        mod_combo = QComboBox()
        mod_combo.addItems(SHORTCUT_MODIFIERS)
        mod_combo.setCurrentText(entry.get("modifier", "alt"))
        mod_combo.currentTextChanged.connect(self._on_shortcut_editor_changed)
        self.shortcuts_table.setCellWidget(row, 0, mod_combo)

        key_combo = QComboBox()
        key_combo.addItems(SHORTCUT_KEYS)
        key_combo.setCurrentText(entry.get("key", "F1"))
        key_combo.currentTextChanged.connect(self._on_shortcut_editor_changed)
        self.shortcuts_table.setCellWidget(row, 1, key_combo)

        tool_combo = QComboBox()
        tool_combo.addItems(TOOLS)
        tool_combo.setCurrentText(entry.get("tool", "AboveLine"))
        tool_combo.currentTextChanged.connect(self._on_shortcut_editor_changed)
        self.shortcuts_table.setCellWidget(row, 2, tool_combo)

        details_item = QTableWidgetItem(self._shortcut_details_text(entry))
        details_item.setFlags(details_item.flags() & ~Qt.ItemIsEditable)
        details_item.setData(Qt.UserRole, dict(entry))
        self.shortcuts_table.setItem(row, 3, details_item)

    def _remove_selected_shortcut_row(self):
        row = self.shortcuts_table.currentRow()
        if row >= 0:
            self.shortcuts_table.removeRow(row)
            self._update_shortcuts_summary()

    def _find_shortcut_row_for_widget(self, widget):
        for row in range(self.shortcuts_table.rowCount()):
            for col in range(3):
                if self.shortcuts_table.cellWidget(row, col) is widget:
                    return row
        return -1

    def _on_shortcut_editor_changed(self):
        if self._loading_shortcuts:
            return

        widget = self.sender()
        row = self._find_shortcut_row_for_widget(widget)
        if row < 0:
            return

        details_item = self.shortcuts_table.item(row, 3)
        if details_item is None:
            details_item = QTableWidgetItem()
            details_item.setFlags(details_item.flags() & ~Qt.ItemIsEditable)
            self.shortcuts_table.setItem(row, 3, details_item)

        entry = dict(details_item.data(Qt.UserRole) or {})
        tool = self.shortcuts_table.cellWidget(row, 2).currentText()
        entry = self._sanitize_shortcut_entry(entry, tool)
        entry["modifier"] = self.shortcuts_table.cellWidget(row, 0).currentText()
        entry["key"] = self.shortcuts_table.cellWidget(row, 1).currentText()
        entry["tool"] = tool
        details_item.setData(Qt.UserRole, entry)
        details_item.setText(self._shortcut_details_text(entry))
        self._update_shortcuts_summary()

    def _shortcut_details_text(self, entry):
        tool = entry.get("tool", "")
        if tool == "DisplayMode":
            return entry.get("display_text") or "Display preset"
        if tool == "ShadingMode":
            return entry.get("shading_text") or "Shading preset"
        if tool == "DrawSettings":
            return entry.get("draw_text") or "Draw preset"

        from_classes = entry.get("from_classes")
        to_class = entry.get("to_class")
        if from_classes not in (None, "", []) or to_class not in (None, ""):
            return f"From: {self._format_class_value(from_classes)} → To: {self._format_class_value(to_class)}"

        return "Basic shortcut"

    def _format_class_value(self, value):
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return str(value)

    def _sanitize_shortcut_entry(self, entry, tool):
        entry = dict(entry)

        if tool != "DisplayMode":
            entry.pop("display_preset", None)
            entry.pop("display_text", None)
        if tool != "ShadingMode":
            entry.pop("shading_preset", None)
            entry.pop("shading_text", None)
        if tool != "DrawSettings":
            entry.pop("draw_preset", None)
            entry.pop("draw_text", None)

        if tool in SHORTCUT_SIMPLE_TOOLS:
            entry["from_classes"] = None
            entry["to_class"] = None
        else:
            entry.setdefault("from_classes", None)
            entry.setdefault("to_class", None)

        return entry

    def _update_shortcuts_summary(self):
        count = self.shortcuts_table.rowCount()
        self.shortcuts_summary.setText(
            f"{count} shortcut row(s). "
            "Binding fields are editable here and saved directly in application settings. "
            "Existing advanced shortcut payloads are preserved."
        )

    def _choose_cross_color(self):
        color = QColorDialog.getColor(self._cross_color, self, "Choose Cross-Section Color")
        if color.isValid():
            self._cross_color = color
            self._update_color_button(self.cross_color_btn, color)
            self._update_cross_preview()

    def _on_cross_width_changed(self, value):
        self.cross_width_label.setText(f"{value} px")
        self._update_cross_preview()

    def _reset_cross_section_controls(self):
        self.cut_width_spin.setValue(2.0)
        self._cross_color = QColor("#FF00FF")
        self._update_color_button(self.cross_color_btn, self._cross_color)
        self.cross_width_slider.setValue(3)
        self.cross_style_combo.setCurrentText("Solid")
        self._update_cross_preview()

    def _update_cross_preview(self):
        style = self._style_key_from_text(self.cross_style_combo.currentText())
        self.cross_preview.set_state(self._cross_color, self.cross_width_slider.value(), style)
        self.cross_summary.setText(
            f"Cut width: +/- {self.cut_width_spin.value():.2f} m | "
            f"Line: {self._cross_color.name()}, {self.cross_width_slider.value()} px, {style}"
        )

    def _on_draw_tool_changed(self):
        self._commit_draw_editor()
        self._selected_draw_tool = self.draw_tool_combo.currentData() or TOOL_ORDER[0]
        self._load_draw_editor_for_selection()
        self._update_draw_summary()

    def _load_draw_editor_for_selection(self):
        key = self._selected_draw_tool
        if key == "__global__":
            style = self._draw_styles.get(TOOL_ORDER[0], DEFAULT_DRAW_STYLES[TOOL_ORDER[0]])
        else:
            style = self._draw_styles.get(key, DEFAULT_DRAW_STYLES[TOOL_ORDER[0]])

        color = vtk_color_to_qcolor(style["color"])
        self._draw_color = color
        self._update_color_button(self.draw_color_btn, color)
        self.draw_width_slider.setValue(int(style["width"]))
        self.draw_width_label.setText(f"{int(style['width'])} px")
        self.draw_style_combo.setCurrentText(self._pretty_style_name(style["style"]))
        self._update_draw_preview()

    def _commit_draw_editor(self):
        if not self._draw_styles:
            return

        style = {
            "color": qcolor_to_vtk(getattr(self, "_draw_color", QColor("#ff0000"))),
            "width": int(self.draw_width_slider.value()),
            "style": self._style_key_from_text(self.draw_style_combo.currentText()),
        }

        if self._selected_draw_tool == "__global__":
            for tool_key in TOOL_ORDER:
                self._draw_styles[tool_key] = dict(style)
        elif self._selected_draw_tool in TOOL_ORDER:
            self._draw_styles[self._selected_draw_tool] = dict(style)

    def _choose_draw_color(self):
        color = QColorDialog.getColor(getattr(self, "_draw_color", QColor("#ff0000")), self, "Choose Draw Color")
        if color.isValid():
            self._draw_color = color
            self._update_color_button(self.draw_color_btn, color)
            self._update_draw_preview()

    def _on_draw_width_changed(self, value):
        self.draw_width_label.setText(f"{value} px")
        self._update_draw_preview()

    def _update_draw_preview(self):
        style = self._style_key_from_text(self.draw_style_combo.currentText())
        self.draw_preview.set_state(getattr(self, "_draw_color", QColor("#ff0000")), self.draw_width_slider.value(), style)
        self._update_draw_summary()

    def _update_draw_summary(self):
        key = self.draw_tool_combo.currentData() or TOOL_ORDER[0]
        if key == "__global__":
            self.draw_summary.setText("Global draw editing will apply the same style to every draw tool.")
        else:
            self.draw_summary.setText(
                f"Editing {TOOL_DISPLAY_NAMES.get(key, key)}. "
                "Save All will push these draw styles into persistent settings and the active digitizer."
            )

    def _update_navigation_summary(self):
        mode = self.zoom_behavior_combo.currentData() or "center"
        if mode == "cursor":
            self.navigation_summary.setText(
                "Mouse wheel zoom will stay anchored under the cursor in supported views."
            )
        elif mode == "picked_point":
            self.navigation_summary.setText(
                "Click a point to set the zoom target, then mouse wheel zoom will recenter and zoom around that picked point."
            )
        else:
            self.navigation_summary.setText(
                "Mouse wheel zoom will continue using the viewport center."
            )

    def _reset_current_draw_tool(self):
        key = self.draw_tool_combo.currentData() or TOOL_ORDER[0]
        if key == "__global__":
            first_default = DEFAULT_DRAW_STYLES[TOOL_ORDER[0]]
            self._draw_color = vtk_color_to_qcolor(first_default["color"])
            self._update_color_button(self.draw_color_btn, self._draw_color)
            self.draw_width_slider.setValue(first_default["width"])
            self.draw_style_combo.setCurrentText(self._pretty_style_name(first_default["style"]))
            self._update_draw_preview()
            return

        default = DEFAULT_DRAW_STYLES.get(key, DEFAULT_DRAW_STYLES[TOOL_ORDER[0]])
        self._draw_styles[key] = dict(default)
        self._load_draw_editor_for_selection()
        self._update_draw_summary()

    def _reset_all_draw_tools(self):
        self._draw_styles = {key: dict(value) for key, value in DEFAULT_DRAW_STYLES.items()}
        self._load_draw_editor_for_selection()
        self._update_draw_summary()

    def _save_theme_settings(self):
        from gui.theme_manager import ThemeManager

        theme_name = self.theme_combo.currentData()
        self.settings.setValue("ui_canvas_background", self.canvas_theme_combo.currentData())
        self.settings.sync()
        ThemeManager.apply_theme(self.app, theme_name)
        self.refresh_theme()
        if hasattr(self.app, "_update_theme_icon"):
            self.app._update_theme_icon()
        if hasattr(self.app, "_update_settings_icon"):
            self.app._update_settings_icon()

    def _save_shortcuts_settings(self):
        shortcuts_list = []
        seen = set()

        for row in range(self.shortcuts_table.rowCount()):
            modifier = self.shortcuts_table.cellWidget(row, 0).currentText()
            key = self.shortcuts_table.cellWidget(row, 1).currentText()
            tool = self.shortcuts_table.cellWidget(row, 2).currentText()
            combo_key = (modifier.lower(), key.upper())

            if combo_key in seen:
                self.category_list.setCurrentRow(1)
                raise ValueError(f"Duplicate shortcut detected for {modifier}+{key}.")
            seen.add(combo_key)

            details_item = self.shortcuts_table.item(row, 3)
            entry = dict(details_item.data(Qt.UserRole) or {})
            entry = self._sanitize_shortcut_entry(entry, tool)
            entry["modifier"] = modifier
            entry["key"] = key
            entry["tool"] = tool
            shortcuts_list.append(entry)

        self.settings.setValue("shortcuts", json.dumps(shortcuts_list))
        self.settings.sync()
        ShortcutManager.apply_shortcuts_from_settings(self.app)

    def _save_cross_section_settings(self):
        style = self._style_key_from_text(self.cross_style_combo.currentText())
        cut_width = self.cut_width_spin.value()

        self.app.default_cut_width = cut_width
        self.settings.setValue("cut_section_width", cut_width)

        self.app.cross_line_color = (
            self._cross_color.redF(),
            self._cross_color.greenF(),
            self._cross_color.blueF(),
        )
        self.app.cross_line_width = self.cross_width_slider.value()
        self.app.cross_line_style = style

        self.settings.setValue("cross_line_color", self._cross_color.name())
        self.settings.setValue("cross_line_width", self.cross_width_slider.value())
        self.settings.setValue("cross_line_style", style)

        if hasattr(self.app, "section_controller"):
            sc = self.app.section_controller
            if hasattr(sc, "rubber_actor") and sc.rubber_actor:
                try:
                    prop = sc.rubber_actor.GetProperty()
                    prop.SetColor(*self.app.cross_line_color)
                    prop.SetLineWidth(self.app.cross_line_width)
                    if hasattr(sc, "update_rectangle_style"):
                        sc.update_rectangle_style()
                    self.app.vtk_widget.render()
                except Exception:
                    pass

    def _save_draw_settings(self):
        self._commit_draw_editor()
        save_draw_settings(self._draw_styles)

        digitizer = getattr(self.app, "digitizer", None)
        if digitizer and hasattr(digitizer, "draw_tool_styles"):
            digitizer.draw_tool_styles = {k: dict(v) for k, v in self._draw_styles.items()}

    def _save_navigation_settings(self):
        zoom_behavior = self.zoom_behavior_combo.currentData() or "center"
        self.settings.setValue("view_zoom_behavior", zoom_behavior)
        self.app.zoom_behavior = zoom_behavior

    def save_all_settings(self):
        try:
            self._save_theme_settings()
            self._save_cross_section_settings()
            self._save_draw_settings()
            self._save_navigation_settings()
            self._save_shortcuts_settings()
            self.settings.sync()

            self._update_shortcuts_summary()
            self._update_cross_preview()
            self._update_draw_summary()
            self._update_navigation_summary()
            self._load_theme_settings()

            if hasattr(self.app, "statusBar") and self.app.statusBar():
                self.app.statusBar().showMessage("Global settings saved successfully.", 2500)
        except Exception as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))

    def refresh_summaries(self):
        """Compatibility hook used by the main window before showing the dialog."""
        self._load_values()

    def _update_color_button(self, button, color):
        button.setStyleSheet(
            f"background-color: {color.name()}; border: 1px solid rgba(0, 0, 0, 0.18); border-radius: 4px;"
        )

    def _pretty_style_name(self, style):
        return {
            "solid": "Solid",
            "dashed": "Dashed",
            "dotted": "Dotted",
            "dash-dot": "Dash-Dot",
            "dash-dot-dot": "Dash-Dot-Dot",
        }.get(style, "Solid")

    def _style_key_from_text(self, text):
        return text.strip().lower()
