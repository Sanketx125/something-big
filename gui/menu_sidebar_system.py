
"""
Menu-Based Ribbon System for NakshaAI
Displays all menu options horizontally in a ribbon layout
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QFrame, QScrollArea, QGroupBox, QListWidget, QListWidgetItem,
    QCheckBox, QDoubleSpinBox, QSizePolicy, QDialog, QDialogButtonBox,
    QComboBox, QMessageBox, QAbstractItemView, QApplication, QRadioButton  # ✅ ADD THIS
)
from PySide6.QtCore import Qt, Signal, QEvent, QSize, QSettings
from PySide6.QtGui import QFont, QPixmap, QIcon, QColor
from html import escape
import json
import numpy as np
from scipy.spatial import cKDTree
from gui.prj_block_identifier import show_block_identifier_dialog
from .digitize_tools import PolylineSettingsDialog
from .curve_ribbon import CurveRibbon
from .digitize_tools import LineArrowSettingsDialog, PolylineSettingsDialog
from .draw_settings_dialog import DrawToolSettingsDialog
from .icon_provider import get_button_icon
from gui.undo_context_manager import get_undo_context_manager

# from gui.menu_sidebar_system import InsideFenceDialog
RIBBON_TOOLTIP_META = {
    ("FileRibbon", "File", "Open"): {
        "title": "Open File",
        "description": "Load point-cloud or project data into the current workspace.",
    },
    ("FileRibbon", "File", "Save"): {
        "title": "Save",
        "description": "Quick-save the current project to its active file.",
    },
    ("FileRibbon", "File", "Save As…"): {
        "title": "Save As",
        "description": "Save the current project to a new file or location.",
    },
    ("FileRibbon", "Vectors", "Export"): {
        "title": "Export Drawings",
        "description": "Export drawings to supported vector formats such as DXF, GeoJSON, or Shapefile.",
    },
    ("FileRibbon", "Vectors", "Import"): {
        "title": "Import Drawings",
        "description": "Import drawings from supported vector files into the current project.",
    },
    ("FileRibbon", "Attachments", "Attach DXF"): {
        "title": "Attach DXF",
        "description": "Attach one or more DXF overlay files to the current project.",
    },
    ("FileRibbon", "Attachments", "PRJ Loader"): {
        "title": "PRJ Block Identifier",
        "description": "Load a PRJ file and identify matching DXF block labels.",
    },
    ("FileRibbon", "Attachments", "Verify Labels"): {
        "title": "Verify Grid Labels",
        "description": "Compare DXF grid labels against the loaded LAZ or LAS coverage.",
    },
    ("FileRibbon", "Attachments", "Attach DWG"): {
        "title": "Attach DWG",
        "description": "Attach one or more DWG overlay files to the current project.",
    },
    ("FileRibbon", "Attachments", "Attach SNT"): {
        "title": "Attach SNT",
        "description": "Attach one or more SNT overlay files to the current project.",
    },
    ("FileRibbon", "Project", "Clear"): {
        "title": "Clear Project",
        "description": "Remove the current data and reset the workspace to a clean state.",
    },
    ("EditRibbon", "History", "Undo"): {
        "title": "Undo",
        "description": "Undo the most recent action.",
    },
    ("EditRibbon", "History", "Redo"): {
        "title": "Redo",
        "description": "Redo the last undone action.",
    },
    ("EditRibbon", "Clipboard", "Cut"): {
        "title": "Cut",
        "description": "Cut the current selection to the clipboard.",
    },
    ("EditRibbon", "Clipboard", "Copy"): {
        "title": "Copy",
        "description": "Copy the current selection to the clipboard.",
    },
    ("EditRibbon", "Clipboard", "Paste"): {
        "title": "Paste",
        "description": "Paste clipboard content into the current context.",
    },
    ("EditRibbon", "Delete", "Delete"): {
        "title": "Delete",
        "description": "Delete the current selection.",
    },
    ("ViewRibbon", "Views", "Top"): {
        "title": "Top View",
        "description": "Switch the main canvas to a top-down orthographic view.",
        "shortcut_tools": ("TopView",),
    },
    ("ViewRibbon", "Views", "Front"): {
        "title": "Front View",
        "description": "Switch the main canvas to a front orthographic view.",
    },
    ("ViewRibbon", "Views", "Side"): {
        "title": "Side View",
        "description": "Switch the main canvas to a side orthographic view.",
    },
    ("ViewRibbon", "Views", "3D"): {
        "title": "3D View",
        "description": "Switch the main canvas to the 3D perspective view.",
    },
    ("ViewRibbon", "Display", "Depth"): {
        "title": "Depth Display",
        "description": "Color the scene using depth-based shading.",
        "shortcut_tools": ("Depth",),
    },
    ("ViewRibbon", "Display", "RGB"): {
        "title": "RGB Display",
        "description": "Show point colors using the RGB values from the source data.",
        "shortcut_tools": ("RGB",),
    },
    ("ViewRibbon", "Display", "Intensity"): {
        "title": "Intensity Display",
        "description": "Show points using grayscale intensity values.",
        "shortcut_tools": ("Intensity",),
    },
    ("ViewRibbon", "Display", "Elevation"): {
        "title": "Elevation Display",
        "description": "Color points by elevation.",
        "shortcut_tools": ("Elevation",),
    },
    ("ViewRibbon", "Display", "Class"): {
        "title": "Class Display",
        "description": "Color points using the active classification palette.",
        "shortcut_tools": ("Class",),
    },
    ("ViewRibbon", "Display", "Shading"): {
        "title": "Shading Preset",
        "description": "Apply a saved shading preset to the current project.",
        "shortcut_tools": ("ShadingMode",),
    },
    ("ViewRibbon", "Navigate", "Fit"): {
        "title": "Fit View",
        "description": "Fit the active view to all visible project content.",
    },
    ("ToolsRibbon", "Sections", "Cross"): {
        "title": "Cross Section",
        "description": "Create a cross-section from the main view.",
        "shortcut_tools": ("CrossSectionRect",),
    },
    ("ToolsRibbon", "Sections", "Cut Section"): {
        "title": "Cut Section",
        "description": "Create a cut section from the current view.",
        "shortcut_tools": ("CutSectionRect", "CutFromCross", "CutFromCut"),
    },
    ("ToolsRibbon", "Sections", "Width"): {
        "title": "Section Width",
        "description": "Set the buffer width used for cross and cut sections.",
    },
    ("ToolsRibbon", "Sync", "Views"): {
        "title": "Synchronize Views",
        "description": "Open view synchronization controls for linked navigation.",
    },
    ("ToolsRibbon", "Selection", "Config"): {
        "title": "Shortcut Configuration",
        "description": "Open the shortcut manager to create or edit custom shortcuts.",
    },
    ("ToolsRibbon", "Settings", "Backup"): {
        "title": "Backup Settings",
        "description": "Open backup settings for project safety and recovery.",
    },
    ("ToolsRibbon", "Settings", "Preferences"): {
        "title": "Cross-Section Preferences",
        "description": "Adjust cross-section display and behavior settings.",
    },
    ("ClassifyRibbon", "Lines", "Above"): {
        "title": "Classify Above Line",
        "description": "Classify points that lie above a drawn line.",
        "shortcut_tools": ("AboveLine",),
    },
    ("ClassifyRibbon", "Lines", "Below"): {
        "title": "Classify Below Line",
        "description": "Classify points that lie below a drawn line.",
        "shortcut_tools": ("BelowLine",),
    },
    ("ClassifyRibbon", "Shapes", "Rect"): {
        "title": "Rectangle Selection",
        "description": "Classify points using a rectangular selection.",
        "shortcut_tools": ("Rectangle",),
    },
    ("ClassifyRibbon", "Shapes", "Circle"): {
        "title": "Circle Selection",
        "description": "Classify points using a circular selection.",
        "shortcut_tools": ("Circle",),
    },
    ("ClassifyRibbon", "Shapes", "Free"): {
        "title": "Freehand Selection",
        "description": "Classify points using a freehand selection path.",
        "shortcut_tools": ("Freehand",),
    },
    ("ClassifyRibbon", "Points", "Brush"): {
        "title": "Brush Selection",
        "description": "Paint classifications onto points with a brush.",
        "shortcut_tools": ("Brush",),
    },
    ("ClassifyRibbon", "Points", "Point"): {
        "title": "Point Selection",
        "description": "Classify individual points directly.",
        "shortcut_tools": ("Point",),
    },
    ("DisplayRibbon", "Config", "Display"): {
        "title": "Display Mode",
        "description": "Open the display mode dialog and manage saved display presets.",
        "shortcut_tools": ("DisplayMode",),
    },
    ("MeasurementRibbon", "Distance", "Line"): {
        "title": "Measure Line",
        "description": "Measure straight-line distance between two points.",
        "shortcut_tools": ("MeasureLine",),
    },
    ("MeasurementRibbon", "Distance", "Path"): {
        "title": "Measure Path",
        "description": "Measure total distance along a multi-point path.",
        "shortcut_tools": ("MeasurePath",),
    },
    ("MeasurementRibbon", "Actions", "Clear"): {
        "title": "Clear Measurements",
        "description": "Remove all measurements from the scene.",
        "shortcut_tools": ("ClearMeasurements",),
    },
    ("IdentificationRibbon", "Identify", "Identify"): {
        "title": "Identify Point",
        "description": "Inspect the class and coordinates of a clicked point.",
    },
    ("IdentificationRibbon", "Identify", "Zoom"): {
        "title": "Zoom Rectangle",
        "description": "Zoom to a rectangle drawn on the current view.",
    },
    ("IdentificationRibbon", "Identify", "Select"): {
        "title": "Rectangle Selection",
        "description": "Select points and overlay entities inside a rectangle.",
    },
    ("ByClassRibbon", "By Class", "Convert"): {
        "title": "By Class Conversion",
        "description": "Convert one class to another using class-based rules.",
    },
    ("ByClassRibbon", "By Class", "Close"): {
        "title": "Closed Feature Conversion",
        "description": "Convert points around closed features using the closed-shape workflow.",
    },
    ("ByClassRibbon", "By Class", "Height"): {
        "title": "Height Conversion",
        "description": "Convert points based on height thresholds.",
    },
    ("ByClassRibbon", "By Class", "Fence"): {
        "title": "Fence Conversion",
        "description": "Convert points inside a selected fence or boundary.",
    },
    ("ByClassRibbon", "Algorithms", "Low Points"): {
        "title": "Low Points",
        "description": "Find and classify unusually low outlier points.",
    },
    ("ByClassRibbon", "Algorithms", "Isolated"): {
        "title": "Isolated Points",
        "description": "Detect and classify isolated outlier points.",
    },
    ("ByClassRibbon", "Algorithms", "Ground"): {
        "title": "Ground Classification",
        "description": "Run the ground classification workflow.",
    },
    ("ByClassRibbon", "Algorithms", "Surface"): {
        "title": "Below Surface",
        "description": "Classify points that fall below a derived surface.",
    },
}


def _ribbon_scope_label(ribbon_scope: str) -> str:
    if not ribbon_scope:
        return "Ribbon"
    return ribbon_scope.replace("Ribbon", "") or "Ribbon"


def _normalize_button_text(button_text: str) -> str:
    return button_text.replace("\n", " ").strip()


def _get_ribbon_tooltip_meta(ribbon_scope: str, section_title: str, button_text: str) -> dict:
    normalized = _normalize_button_text(button_text)
    meta = RIBBON_TOOLTIP_META.get((ribbon_scope, section_title, normalized))
    if meta:
        return meta
    return {
        "title": normalized,
        "description": f"{normalized} tool.",
    }


def _format_shortcut_label(modifier: str, key: str) -> str:
    key = (key or "").strip()
    modifier = (modifier or "none").strip().lower()
    labels = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "meta": "Meta"}
    parts = []
    if modifier and modifier != "none":
        for chunk in modifier.split("+"):
            chunk = chunk.strip().lower()
            if chunk:
                parts.append(labels.get(chunk, chunk.title()))
    key_label = "Space" if key == " " else key.upper()
    return "+".join(parts + [key_label]) if parts else key_label


def _collect_shortcuts_from_settings() -> list[tuple[str, str, str]]:
    settings = QSettings("NakshaAI", "LidarApp")
    shortcuts_data = settings.value("shortcuts", None)
    if shortcuts_data is None:
        return []
    try:
        entries = json.loads(shortcuts_data) if isinstance(shortcuts_data, str) else shortcuts_data
    except Exception:
        return []

    results = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool")
        key = entry.get("key", "")
        modifier = entry.get("modifier", "none")
        if tool and key:
            results.append((str(tool), str(modifier), str(key)))
    return results


def _collect_shortcuts_from_app(app_window) -> list[tuple[str, str, str]]:
    results = []
    shortcuts = getattr(app_window, "shortcuts", {}) if app_window is not None else {}
    for combo, shortcut_info in shortcuts.items():
        try:
            modifier, key = combo
        except Exception:
            continue
        if not isinstance(shortcut_info, dict):
            continue
        tool = shortcut_info.get("tool")
        if tool and key:
            results.append((str(tool), str(modifier), str(key)))
    return results


def _get_tooltip_shortcuts(app_window, shortcut_tools) -> list[str]:
    if not shortcut_tools:
        return []
    target_tools = {tool for tool in shortcut_tools if tool}
    matches = set()

    for tool, modifier, key in _collect_shortcuts_from_app(app_window):
        if tool in target_tools:
            matches.add(_format_shortcut_label(modifier, key))

    for tool, modifier, key in _collect_shortcuts_from_settings():
        if tool in target_tools:
            matches.add(_format_shortcut_label(modifier, key))

    return sorted(matches)


class RibbonSection(QWidget):
    """A single section in the ribbon with toggle-capable buttons"""

    _POINT_SYNC_EXCLUSIVE_BUTTONS = {
        "ToolsRibbon": {"Cross", "Cut", "Width"},
        "DrawRibbon": {"Smart", "Line", "Polyline", "Rect", "Circle", "Free", "Text", "Move V", "Vertex", "Grid", "Select"},
        "ClassifyRibbon": {"Above", "Below", "Rect", "Circle", "Free", "Brush", "Point"},
        "MeasurementRibbon": {"Line", "Path"},
        "IdentificationRibbon": {"Identify", "Zoom", "Select"},
        "CurveRibbon": {"Curve"},
    }

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("ribbonSection")
        self.section_title = title
        self.ribbon_scope = parent.__class__.__name__ if parent is not None else None
        from PySide6.QtCore import Qt
        self.setAttribute(Qt.WA_StyledBackground, True)  # Required to render QSS box/borders
        self.active_button = None  # track which button is active
        self._button_count = 0
        self.setup_ui(title)
    

    def setup_ui(self, title):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignTop)
        
        # FIXED: Removed setMinimumHeight(108) which was causing excessive empty space below the ribbon tools
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        title_label = QLabel(title)
        title_label.setObjectName("ribbonSectionTitle")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        self.button_box = QWidget()
        self.button_box.setObjectName("ribbonSectionBox")
        self.button_box.setAttribute(Qt.WA_StyledBackground, True)

        self.button_layout = QHBoxLayout(self.button_box)
        self.button_layout.setSpacing(8)
        self.button_layout.setContentsMargins(8, 6, 8, 6)
        self.button_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self.button_box)

    def _find_app_window(self):
        widget = self.window()
        if widget is not None and hasattr(widget, "ribbon_manager"):
            return widget

        widget = self.parentWidget()
        while widget is not None:
            if hasattr(widget, "ribbon_manager"):
                return widget
            widget = widget.parentWidget()
        return None

    def _build_button_tooltip(self, btn: QPushButton) -> str:
        from gui.theme_manager import ThemeColors

        button_text = btn.property("ribbonText") or btn.text() or ""
        section_title = btn.property("ribbonSection") or self.section_title
        ribbon_scope = btn.property("ribbonScope") or self.ribbon_scope

        meta = _get_ribbon_tooltip_meta(ribbon_scope, section_title, button_text)
        title = meta.get("title", _normalize_button_text(button_text))
        description = meta.get("description", "")
        shortcut_items = _get_tooltip_shortcuts(
            self._find_app_window(),
            meta.get("shortcut_tools", ()),
        )

        title_color = ThemeColors.get("text_primary")
        body_color = ThemeColors.get("text_primary")
        muted_color = ThemeColors.get("text_secondary")
        divider_color = ThemeColors.get("border_light")

        shortcut_html = ""
        if shortcut_items:
            shortcut_label = "Shortcut" if len(shortcut_items) == 1 else "Shortcuts"
            shortcut_html = (
                f"<div style='margin-top:5px; padding-top:4px; "
                f"border-top:1px solid {divider_color};'>"
                f"<span style='font-size:7.6pt; color:{muted_color};'>{shortcut_label}</span>"
                f"<div style='font-size:8.6pt; font-weight:600; color:{title_color}; margin-top:1px;'>"
                f"{escape(', '.join(shortcut_items))}</div></div>"
            )

        return (
            f"<div style='min-width:188px;'>"
            f"<div style='font-size:9.8pt; font-weight:700; color:{title_color};'>{escape(title)}</div>"
            f"<div style='font-size:8.6pt; color:{body_color}; margin-top:3px; line-height:1.24;'>"
            f"{escape(description)}</div>"
            f"{shortcut_html}</div>"
        )

    def _refresh_button_tooltip(self, btn: QPushButton):
        btn.setToolTip(self._build_button_tooltip(btn))

    def eventFilter(self, obj, event):
        if isinstance(obj, QPushButton) and event.type() in (QEvent.Enter, QEvent.ToolTip):
            self._refresh_button_tooltip(obj)
        return super().eventFilter(obj, event)

    def add_button(self, text, icon_text, callback=None, toggleable=True):
        """
        Add a button to this ribbon section.
        - toggleable=True: button can stay pressed green
        - toggleable=False: acts like a simple push
        Uses SVG icons from icon_provider when available, falls back to text.
        """
        icon_size = 24

        btn = QPushButton()
        btn.setObjectName("ribbonButton")
        btn.setProperty("ribbonText", text)
        btn.setProperty("ribbonSection", self.section_title)
        btn.setProperty("ribbonScope", self.ribbon_scope)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)

        icon = get_button_icon(
            text,
            section_title=self.section_title,
            ribbon_scope=self.ribbon_scope,
            size=icon_size,
        )
        if not icon.isNull():
            btn.setIcon(icon)
            btn.setIconSize(QSize(icon_size, icon_size))
        else:
            # Fallback to text (for any unmapped buttons)
            btn.setText(icon_text)
            font = btn.font()
            font.setPointSize(15)
            btn.setFont(font)

        btn.setFixedSize(44, 44)
        btn.setCheckable(toggleable)
        self._refresh_button_tooltip(btn)
        btn.installEventFilter(self)

        if callback:
            btn.clicked.connect(lambda checked, b=btn: self._on_button_click(b, callback))

        # Wrap button + label in a vertical container
        container = QWidget()
        container.setObjectName("ribbonButtonContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(3)
        container_layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        container_layout.addWidget(btn, 0, Qt.AlignHCenter)

        label = QLabel(text)
        label.setObjectName("ribbonButtonLabel")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setFixedWidth(52)
        container_layout.addWidget(label, 0, Qt.AlignHCenter)

        self.button_layout.addWidget(container)

        self._button_count += 1
        return btn

    def _on_button_click(self, btn, callback):
        """Handle button toggle states"""
        # Deactivate previously active button if it's not this one
        if self.active_button and self.active_button != btn:
            self.active_button.setChecked(False)

        # Toggle this button
        if btn.isChecked():
            self.active_button = btn
        else:
            self.active_button = None

        self._deactivate_point_sync_for_tool_button(btn)

        # Emit or call connected function
        callback()

    def _deactivate_point_sync_for_tool_button(self, btn):
        ribbon_scope = btn.property("ribbonScope") or self.ribbon_scope
        ribbon_text = btn.property("ribbonText")

        if ribbon_text not in self._POINT_SYNC_EXCLUSIVE_BUTTONS.get(ribbon_scope, set()):
            return

        main_window = self.window()
        point_sync_tool = getattr(main_window, "point_sync_tool", None)
        if point_sync_tool and getattr(point_sync_tool, "active", False):
            try:
                point_sync_tool.deactivate()
            except Exception:
                pass


class FileRibbon(QWidget):
    open_file = Signal()
    save_file = Signal()          # keep: we will use this for "Save As..."
    save_quick = Signal()         # NEW: will be "Save" (no dialog)
    export_drawings = Signal()
    import_drawings = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.build_ribbon()
        
    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        # File Operations
        file_ops = RibbonSection("File", self)

        file_ops.add_button("Open", "📂", self.open_file.emit, toggleable=False)

        # NEW: Save (no dialog)
        file_ops.add_button("Save", "💾", self.save_quick.emit, toggleable=False)

        # Existing Save renamed to Save As…
        file_ops.add_button("Save As…", "💾", self.save_file.emit, toggleable=False)

        layout.addWidget(file_ops)
        
        # Vector Export/Import Section
        vector_ops = RibbonSection("Vectors", self)
        vector_ops.add_button("Export", "📤", self._export_drawings)
        vector_ops.add_button("Import", "📥", self._import_drawings)
        layout.addWidget(vector_ops)

        # Combined attachment tools
        attachments = RibbonSection("Attachments", self)
        attachments.add_button(" DXF", "📎", self._attach_dxf)
        attachments.add_button("DWG", "📐", self._attach_dwg, toggleable=False)
        attachments.add_button("SNT", "🗂️", self._attach_snt, toggleable=False)
        attachments.add_button("PRJ", "📋", self._identify_blocks)
        attachments.add_button("Verify", "🔍", self._verify_grid_labels)

        layout.addWidget(attachments)

        # Project
        project = RibbonSection("Project", self)
        project.add_button("Clear", "🧹", self._clear_project)
        layout.addWidget(project)
        
        layout.addStretch()
    
    def _export_drawings(self):
        """Show export dialog for drawings"""
        try:
            app = self.parent().parent().parent()
            from gui.vector_export import show_export_dialog
            show_export_dialog(app)
        except Exception as e:
            print(f"⚠️ Export failed: {e}")

    def _import_drawings(self):
        """Show import dialog for drawings"""
        try:
            app = self.parent().parent().parent()
            from gui.vector_export import show_import_dialog
            show_import_dialog(app)
        except Exception as e:
            print(f"⚠️ Import failed: {e}")

    def _attach_dxf(self):
            """Attach DXF file with automatic PRJ detection"""
            try:
                app = self.parent().parent().parent()
            
                # Check if dialog exists AND is still valid (not deleted)
                if hasattr(app, 'dxf_dialog') and app.dxf_dialog is not None:
                    # Check if the dialog widget is still valid
                    try:
                        if app.dxf_dialog.isVisible():
                            # Dialog exists and is visible - restore and bring to front
                            app.dxf_dialog.setWindowState(
                                app.dxf_dialog.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
                            )
                            app.dxf_dialog.raise_()
                            app.dxf_dialog.activateWindow()
                        else:
                            # Dialog exists but is hidden - show it
                            app.dxf_dialog.show()
                            app.dxf_dialog.raise_()
                            app.dxf_dialog.activateWindow()
                    except RuntimeError:
                        # Dialog was deleted - create new one
                        app.dxf_dialog = None
                        from gui.dxf_attachment import show_multi_dxf_attachment_dialog
                        app.dxf_dialog = show_multi_dxf_attachment_dialog(app)
                else:
                    # Create new dialog
                    from gui.dxf_attachment import show_multi_dxf_attachment_dialog
                    app.dxf_dialog = show_multi_dxf_attachment_dialog(app)
            except Exception as e:
                print(f"⚠️ DXF attachment failed: {e}")
                import traceback
                traceback.print_exc()

    def _attach_dwg(self):
       
        try:
            app = self.parent().parent().parent()

            # Reuse existing dialog if still alive
            if hasattr(app, 'dwg_dialog') and app.dwg_dialog is not None:
                try:
                    if app.dwg_dialog.isVisible():
                        app.dwg_dialog.setWindowState(
                            app.dwg_dialog.windowState()
                            & ~Qt.WindowMinimized | Qt.WindowActive
                        )
                        app.dwg_dialog.raise_()
                        app.dwg_dialog.activateWindow()
                    else:
                        app.dwg_dialog.show()
                        app.dwg_dialog.raise_()
                        app.dwg_dialog.activateWindow()
                    return
                except RuntimeError:
                    app.dwg_dialog = None  # was deleted, fall through

            from gui.dwg_attachment import show_dwg_attachment_dialog
            app.dwg_dialog = show_dwg_attachment_dialog(app)

        except Exception as e:
            print(f"⚠️ DWG attachment failed: {e}")
            import traceback
            traceback.print_exc()  

    def _identify_blocks(self):
        """Load PRJ file and identify DXF blocks"""
        try:
            app = self.parent().parent().parent()
            
            # Check if dialog exists AND is still valid (not deleted)
            if hasattr(app, 'block_identifier_dialog') and app.block_identifier_dialog is not None:
                # Check if the dialog widget is still valid
                try:
                    if app.block_identifier_dialog.isVisible():
                        # Dialog exists and is visible - restore and bring to front
                        app.block_identifier_dialog.setWindowState(
                            app.block_identifier_dialog.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
                        )
                        app.block_identifier_dialog.raise_()
                        app.block_identifier_dialog.activateWindow()
                    else:
                        # Dialog exists but is hidden - show it
                        app.block_identifier_dialog.show()
                        app.block_identifier_dialog.raise_()
                        app.block_identifier_dialog.activateWindow()
                except RuntimeError:
                    # Dialog was deleted - create new one
                    app.block_identifier_dialog = None
                    from gui.prj_block_identifier import show_block_identifier_dialog
                    app.block_identifier_dialog = show_block_identifier_dialog(app)
            else:
                # Create new dialog
                from gui.prj_block_identifier import show_block_identifier_dialog
                app.block_identifier_dialog = show_block_identifier_dialog(app)
        except Exception as e:
            print(f"⚠️ Block identifier failed: {e}")
            import traceback
            traceback.print_exc()
            
    def _clear_project(self):
        """Clear project with confirmation"""
        try:
            app = self.parent().parent().parent()
            from gui.app_window import clear_project
            clear_project(app)
        except Exception as e:
            print(f"⚠️ Clear failed: {e}")
            
    
    def _verify_grid_labels(self):
        """Verify DXF grid label positions vs actual LAZ data"""
        try:
            app = self.parent().parent().parent()
            if hasattr(app, 'grid_label_manager') and app.grid_label_manager:
                app.grid_label_manager.verify_dxf_labels()
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Not Available",
                    "Grid label system not initialized.\n\n"
                    "Load a DXF file first."
                )
        except Exception as e:
            print(f"⚠️ Verify labels failed: {e}")
            import traceback
            traceback.print_exc()

    def _list_dxf_text(self):
        """List all text entities in loaded DXF"""
        try:
            app = self.parent().parent().parent()
            if hasattr(app, 'grid_label_manager') and app.grid_label_manager:
                app.grid_label_manager.list_all_text_in_dxf()
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Not Available",
                    "Grid label system not initialized.\n\n"
                    "Load a DXF file first."
                )
        except Exception as e:
            print(f"⚠️ List text failed: {e}")
            import traceback
            traceback.print_exc()

    def _attach_snt(self) -> None:
        """
        Open or restore the SNT attachment dialog.
        Mirrors _attach_dwg exactly:
        - app resolved via self.parent().parent().parent()
        - return guard after restore path prevents double-dialog creation
        - RuntimeError catch handles garbage-collected C++ Qt objects
        - No deferred Qt import (Qt already at module level)
        """
        try:
            app = self.parent().parent().parent()  # ✅ identical to _attach_dwg / _attach_dxf

            if hasattr(app, 'snt_dialog') and app.snt_dialog is not None:
                try:
                    if app.snt_dialog.isVisible():
                        # Restore from minimised state and bring to foreground
                        app.snt_dialog.setWindowState(
                            app.snt_dialog.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
                        )
                        app.snt_dialog.raise_()
                        app.snt_dialog.activateWindow()
                    else:
                        # Dialog exists but was hidden — show it
                        app.snt_dialog.show()
                        app.snt_dialog.raise_()
                        app.snt_dialog.activateWindow()
                    return  # ✅ guard: prevents fall-through to dialog re-creation below

                except RuntimeError:
                    # Qt C++ object was garbage-collected — reset and fall through to recreate
                    app.snt_dialog = None

            # First launch OR after garbage-collection: create fresh dialog
            from gui.snt_attachment import show_snt_attachment_dialog
            app.snt_dialog = show_snt_attachment_dialog(app)

        except Exception as e:
            print(f"SNT attachment failed: {e}")
            import traceback
            traceback.print_exc()


# ============================================================================
# Import dialog implementation
# ============================================================================



class EditRibbon(QWidget):
    """Ribbon for Edit menu"""
    
    edit_action = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.build_ribbon()
        
    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        
        # Undo/Redo
        history = RibbonSection("History", self)
        history.add_button("Undo", "↶", lambda: self.edit_action.emit("undo"))
        history.add_button("Redo", "↷", lambda: self.edit_action.emit("redo"))
        layout.addWidget(history)
        
        # Clipboard
        clipboard = RibbonSection("Clipboard", self)
        clipboard.add_button("Cut", "✂️", lambda: self.edit_action.emit("cut"))
        clipboard.add_button("Copy", "📋", lambda: self.edit_action.emit("copy"))
        clipboard.add_button("Paste", "📎", lambda: self.edit_action.emit("paste"))
        layout.addWidget(clipboard)
        
        # Delete
        delete_sec = RibbonSection("Delete", self)
        delete_sec.add_button("Delete", "🗑️", lambda: self.edit_action.emit("delete"))
        layout.addWidget(delete_sec)
        
        layout.addStretch()

class ViewRibbon(QWidget):
    """Ribbon for View menu with compact amplifier controls."""

    view_changed = Signal(str)
    display_changed = Signal(str)
    shadow_toggled = Signal(bool)
    depth_toggled = Signal(bool)
    saturation_changed = Signal(int)
    sharpness_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shadow_on = False
        self._depth_on = False
        self.current_saturation = 100  # Default 100%
        self.current_sharpness = 100   # Default 100%
        self.build_ribbon()

    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 📸 View Modes
        views = RibbonSection("Views", self)
        views.add_button("Top", "⬇️", lambda: self.view_changed.emit("top"))
        views.add_button("Front", "➡️", lambda: self.view_changed.emit("front"))
        views.add_button("Side", "⬅️", lambda: self.view_changed.emit("side"))
        views.add_button("3D", "🔄", lambda: self.view_changed.emit("3d"))
        layout.addWidget(views)

        # 🎨 Display Modes
        display = RibbonSection("Display", self)
        self.depth_btn = display.add_button("Depth", "🧱", self.toggle_depth)
        display.add_button("RGB", "🌈", lambda: self._switch_display_mode("rgb"))
        display.add_button("Intensity", "💡", lambda: self._switch_display_mode("intensity"))
        display.add_button("Elevation", "📊", lambda: self._switch_display_mode("elevation"))
        display.add_button("Class", "🏷️", lambda: self._switch_display_mode("class"))
        display.add_button("Shading", "🌓", lambda: self._switch_display_mode("shaded_class"))
        layout.addWidget(display)

        navigate = RibbonSection("Navigate", self)
        navigate.add_button(
            "Fit",
            "🧲",
            self._fit_view,
            toggleable=False
        )
        layout.addWidget(navigate)

        # layout.addStretch()

    def _switch_to_non_class_mode(self, mode):
        """
        Switch to non-classification mode and disable borders.
        ✅ Borders only work in Classification mode.
        """
        # Find parent app
        widget = self
        while widget:
            if hasattr(widget, 'point_border_percent'):
                # Disable borders for non-class modes
                widget._main_view_borders_active = False
                widget.point_border_percent = 0
                print(f"🔳 Borders DISABLED for {mode} mode")
                break
            widget = widget.parent()
        
        # Emit the display change
        self.display_changed.emit(mode)

    def _fit_view(self):
        widget = self
        while widget:
            if hasattr(widget, "fit_view"):
                widget.fit_view()
                return
            widget = widget.parent()

    def _on_sharpness_changed(self, value):
        """Amplifier removed — no-op. Signal is never connected."""
        pass  # Intentionally empty


    def _adjust_sharpness(self, delta):
        """Amplifier removed — no-op."""
        pass  # Intentionally empty

    def _reset_amplifiers(self):
        """Amplifier removed — no-op."""
        pass  # Intentionally empty
    # -----------------------------------------------------
    # 🧱 Depth Toggle
    # -----------------------------------------------------
    def toggle_depth(self):
        """
        Apply depth display mode (single click, like elevation/intensity).
        Shift+Click opens customization dialog.
        """
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt
        
        modifiers = QApplication.keyboardModifiers()
        
        if modifiers & Qt.ShiftModifier:
            # Shift+Click → Open depth settings dialog
            widget = self
            while widget:
                if hasattr(widget, '_open_depth_settings'):
                    widget._open_depth_settings()
                    return
                widget = widget.parent()
            print("⚠️ Depth settings dialog not available")
        else:
            # Normal click → Apply depth mode immediately
            # ✅ Disable borders when switching to Depth
            widget = self
            while widget:
                if hasattr(widget, 'point_border_percent'):
                    widget._main_view_borders_active = False
                    widget.point_border_percent = 0
                    print(f"🔳 Borders DISABLED for depth mode")
                    break
                widget = widget.parent()
            
            # Emit signal to apply depth display
            self.display_changed.emit("depth")
            print(f"📏 Depth mode applied")
        
        
    def _switch_display_mode(self, mode):
        """
        Switch display mode and manage border activation.
        ✅ Borders ONLY enabled for Classification mode.
        ✅ Borders disabled for all other modes.
        """
        # Find parent app
        widget = self
        app = None
        while widget:
            if hasattr(widget, 'point_border_percent') and hasattr(widget, 'display_mode'):
                app = widget
                break
            widget = widget.parent()
        
        if mode == "class":
            # ✅ ENABLE borders for Classification mode
            if app:
                # Restore border value from dialog if it exists
                if hasattr(app, 'display_mode_dialog') and app.display_mode_dialog:
                    dialog = app.display_mode_dialog
                    saved_border = dialog.view_borders.get(0, 0)  # Main View border
                    app.point_border_percent = float(saved_border)
                    app._main_view_borders_active = (saved_border > 0)
                    print(f"🔳 Borders ENABLED for Class mode: {saved_border}%")
                else:
                    # No dialog, enable if border value exists
                    app._main_view_borders_active = (app.point_border_percent > 0)
                    print(f"🔳 Borders ENABLED for Class mode: {app.point_border_percent}%")
        else:
            # ✅ DISABLE borders for all non-Class modes
            if app:
                app._main_view_borders_active = False
                app.point_border_percent = 0  # ✅ CRITICAL: Set to 0 to prevent rendering
                print(f"🔳 Borders DISABLED for {mode} mode (forced to 0%)")

        # Emit the display change (this triggers set_display_mode which will re-render)
        self.display_changed.emit(mode)

    def _update_button_style(self, button, active: bool):
        """Highlight button when active."""
        from gui.theme_manager import get_active_button_style, get_inactive_button_style
        if active:
            button.setStyleSheet(get_active_button_style())
        else:
            button.setStyleSheet(get_inactive_button_style())



class ToolsRibbon(QWidget):
    """Ribbon for Tools menu"""
    
    tool_activated = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.tool_buttons = {}  
        self.build_ribbon()
        
    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # ------------------------
        # ✂️ Sections: Cross / Cut / Width
        # ------------------------
        sections = RibbonSection("Sections", self)
        sections.add_button("Cross", "📐",
                            lambda: self.tool_activated.emit("cross_section"))
        sections.add_button("Cut", "🔪",
                            lambda: self.tool_activated.emit("cut_section"))
        sections.add_button("Width", "📏",
                            lambda: self.tool_activated.emit("set_cut_width"))
        layout.addWidget(sections)
        
        # ------------------------
        # 🔄 Sync: (for Sync Views dialog – single button)
        # ------------------------
        sync_sec = RibbonSection("Sync", self)
        # For now just one button that will open the Synchronize Views dialog
        sync_sec.add_button("Views", "🔄",
                            lambda: self.tool_activated.emit("sync_views"),
                            toggleable=False)
        layout.addWidget(sync_sec)
        
        # ------------------------
        # 🎯 Selection
        # ------------------------
        selection = RibbonSection("Selection", self)
        # selection.add_button("Select", "🖱️",
        #                      lambda: self.tool_activated.emit("element_selection"))
        selection.add_button("Config", "⌨️", self._configure_shortcuts)
        layout.addWidget(selection)
        
        # ------------------------
        # ⚙️ Settings
        # ------------------------
        settings = RibbonSection("Settings", self)
        settings.add_button("Backup", "💾",
                            lambda: self.tool_activated.emit("backup_settings"))
        settings.add_button("Preferences", "🎛️",
                            lambda: self.tool_activated.emit("cross_settings"))
        layout.addWidget(settings)
        
        layout.addStretch()
        
        
    def _configure_shortcuts(self):
        """Show shortcut configuration dialog"""
        try:
            app = self.parent().parent().parent()
            
            # Check if dialog exists AND is still valid (not deleted)
            if hasattr(app, 'shortcut_manager_dialog') and app.shortcut_manager_dialog is not None:
                # Check if the dialog widget is still valid
                try:
                    if app.shortcut_manager_dialog.isVisible():
                        # Dialog exists and is visible - restore and bring to front
                        app.shortcut_manager_dialog.setWindowState(
                            app.shortcut_manager_dialog.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
                        )
                        app.shortcut_manager_dialog.raise_()
                        app.shortcut_manager_dialog.activateWindow()
                    else:
                        # Dialog exists but is hidden - show it
                        app.shortcut_manager_dialog.show()
                        app.shortcut_manager_dialog.raise_()
                        app.shortcut_manager_dialog.activateWindow()
                except RuntimeError:
                    # Dialog was deleted - create new one
                    app.shortcut_manager_dialog = None
                    from gui.shortcut_manager import ShortcutManager
                    app.shortcut_manager_dialog = ShortcutManager.open_manager(app)
            else:
                # Create new dialog
                from gui.shortcut_manager import ShortcutManager
                app.shortcut_manager_dialog = ShortcutManager.open_manager(app)
        except Exception as e:
            print(f"⚠️ Shortcut config failed: {e}")
            import traceback
            traceback.print_exc()

class ClassifyRibbon(QWidget):
    """Ribbon for Classify menu"""
    
    classify_tool_selected = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.build_ribbon()
        
    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # Line Tools
        lines = RibbonSection("Lines", self)
        lines.add_button("Above", "⬆️", lambda: self.classify_tool_selected.emit("above_line"))
        lines.add_button("Below", "⬇️", lambda: self.classify_tool_selected.emit("below_line"))
        layout.addWidget(lines)
        
        # Shape Selection
        shapes = RibbonSection("Shapes", self)
        shapes.add_button("Rect", "⬜", lambda: self.classify_tool_selected.emit("rectangle"))
        shapes.add_button("Circle", "⭕", lambda: self.classify_tool_selected.emit("circle"))
        # shapes.add_button("Polygon", "⬡", lambda: self.classify_tool_selected.emit("polygon"))
        shapes.add_button("Free", "✏️", lambda: self.classify_tool_selected.emit("freehand"))
        layout.addWidget(shapes)
        
        # Point Tools
        points = RibbonSection("Points", self)
        points.add_button("Brush", "🖌️", lambda: self.classify_tool_selected.emit("brush"))
        points.add_button("Point", "📍", lambda: self.classify_tool_selected.emit("point"))
        layout.addWidget(points)

        layout.addStretch()

class DisplayRibbon(QWidget):
    """Ribbon for Display menu"""
    
    display_mode_clicked = Signal()
    border_width_changed = Signal(int)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Display Mode (Ctrl+D to Apply)")
       
        self.resize(850, 600)
        self.current_ptc_path = None
        self.current_border_value = 0
        self.build_ribbon()
        
    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # Config
        config = RibbonSection("Config", self)
        config.add_button("Display", "🎛️", self.display_mode_clicked.emit)
        layout.addWidget(config)
        layout.addStretch()
    
    def increase_border(self):
        """Increase border value by 5%"""
        self.current_border_value = min(50, self.current_border_value + 5)
        self.update_border_display()
    
    def decrease_border(self):
        """Decrease border value by 5%"""
        self.current_border_value = max(0, self.current_border_value - 5)
        self.update_border_display()
    def update_border_display(self):
        """Update the display and emit signal with immediate re-render"""
        value = self.current_border_value
        self.border_label.setText(f"Border: {value}%")
        self.value_display.setText(f"{value}%")
        
        print(f"🔵 Border changed to: {value}%")
        
        # ✅ CRITICAL: Find main window and apply border immediately
        try:
            widget = self
            while widget is not None:
                widget = widget.parent()
                if hasattr(widget, 'on_border_changed'):
                    print(f"🔵 Found main window, applying border {value}%")
                    
                    # Update the border value in app
                    widget.point_border_percent = value
                    
                    # ✅ FIXED: Trigger immediate re-render based on display mode
                    if widget.display_mode == "class":
                        from gui.class_display import update_class_mode
                        update_class_mode(widget)
                        print(f"   ✅ Re-rendered in class mode")
                        
                    elif widget.display_mode == "shaded_class":
                        from gui.shading_display import update_shaded_class
                        update_shaded_class(
                            widget,
                            getattr(widget, "last_shade_azimuth", 45.0),
                            getattr(widget, "last_shade_angle", 45.0),
                            getattr(widget, "shade_ambient", 0.2)
                        )
                        print(f"   ✅ Re-rendered in shaded_class mode")
                        
                    else:
                        from gui.pointcloud_display import update_pointcloud
                        update_pointcloud(widget, widget.display_mode)
                        print(f"   ✅ Re-rendered in {widget.display_mode} mode")
                    
                    # Also emit signal for any connected slots
                    self.border_width_changed.emit(value)
                    
                    # Update status bar
                    if hasattr(widget, 'statusBar'):
                        widget.statusBar().showMessage(f"🔳 Border: {value}% applied", 2000)
                    
                    break
            else:
                print(f"⚠️ Could not find main window with on_border_changed method")
                
        except Exception as e:
            print(f"⚠️ Failed to update border: {e}")
            import traceback
            traceback.print_exc()

class DrawRibbon(QWidget):
    """Ribbon for Draw menu"""
   
    draw_tool_selected = Signal(str)
    clear_requested = Signal()
    grid_requested = Signal()
   
    def __init__(self, parent=None):
        super().__init__(parent)
        self.build_ribbon()
       
    # def build_ribbon(self):
    #     layout = QHBoxLayout(self)
    #     layout.setContentsMargins(0, 0, 0, 0)
    #     layout.setSpacing(10)
       
    #     # Draw Tools
    #     tools = RibbonSection("🖊️ Tools", self)
       
    #     tools.add_button("Smart\nLine", "🔮", lambda: self._handle_smartline_click())
    #     tools.add_button("Line", "📏", lambda: self._handle_line_click())
    #     tools.add_button("Polyline", "⬡", lambda: self._handle_polyline_click())
    #     tools.add_button("Rect", "⬜", lambda: self.draw_tool_selected.emit("Rectangle"))
    #     tools.add_button("Circle", "⭕", lambda: self.draw_tool_selected.emit("Circle"))
    #     tools.add_button("Free", "✏️", lambda: self.draw_tool_selected.emit("Freehand"))
    #     tools.add_button("Text", "📝", lambda: self.draw_tool_selected.emit("Text"))
       
    #     # ✅ NEW: Move Vertex button
    #     tools.add_button("Move\nVertex", "🔄", lambda: self._handle_move_vertex_click())
       
    #     tools.add_button("Vertex", "🔵", lambda: self._handle_vertex_click())
    #     tools.add_button("Grid", "⊞", self.grid_requested.emit)
    #     layout.addWidget(tools)
 
    #     # Actions
    #     actions = RibbonSection("Actions", self)
    #     actions.add_button("Clear", "🗑️", self.clear_requested.emit)
    #     layout.addWidget(actions)
       
    #     layout.addStretch()

    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # Draw Tools
        tools = RibbonSection("Tools", self)
        
        tools.add_button("Smart", "🔮", lambda: self._handle_smartline_click())
        tools.add_button("Line", "📏", lambda: self._handle_line_click())
        tools.add_button("Ortho", "📐", lambda: self._handle_ortho_click())
        tools.add_button("Polyline", "⬡", lambda: self._handle_polyline_click())
        tools.add_button("Rect",  "⬜", lambda: self._handle_rect_click())
        tools.add_button("Circle","⭕", lambda: self._handle_circle_click())
        tools.add_button("Free",  "✏️", lambda: self._handle_freehand_click())
        tools.add_button("Text", "📝", lambda: self.draw_tool_selected.emit("Text"))
        
        # ✅ Move Vertex button
        tools.add_button("Move V", "🔄", lambda: self._handle_move_vertex_click())
        
        tools.add_button("Vertex", "🔵", lambda: self._handle_vertex_click())
        tools.add_button("Grid", "⊞", self.grid_requested.emit)
        layout.addWidget(tools)

        # ══════════════════════════════════════════════════════════
        # ◀◀◀ NEW SECTION: Selection Tools
        # ══════════════════════════════════════════════════════════
        select_section = RibbonSection("Select", self)
        
        select_section.add_button(
            "Select", "🎯",
            lambda: self._handle_select_drawing_click()
        )
        
        # select_section.add_button(
        #     "Deselect\nAll", "⛔",
        #     lambda: self._handle_deselect_all_click()
        # )
        
        layout.addWidget(select_section)

        # Actions
        actions = RibbonSection("Actions", self)
        actions.add_button("Clear", "🗑️", self._handle_clear_click)
        layout.addWidget(actions)

        # ══════════════════════════════════════════════════════════
        # ◀◀◀ NEW SECTION: Draw Settings
        # ══════════════════════════════════════════════════════════
        settings_section = RibbonSection("Settings", self)
        settings_section.add_button(
            "Settings", "⚙️",
            lambda: self._show_draw_settings(),
            toggleable=False
        )
        layout.addWidget(settings_section)
        
        layout.addStretch()

    def _handle_clear_click(self):
        main_window = self.window()
        if not hasattr(main_window, 'digitizer') or not main_window.digitizer:
            return

        digitizer = main_window.digitizer

        # Check if any classified fences exist
        classified_fences = [d for d in digitizer.drawings if d.get('classified_fence', False)]

        if not classified_fences:
            # No classified fences — clear everything directly
            digitizer.clear_drawings(clear_classified=True)
            print("🗑️ Clear: all drawings cleared (no classified fences)")
        else:
            # Has classified fences — first clear non-classified, then show picker
            digitizer.clear_drawings(clear_classified=False)
            print("🗑️ Clear: non-classified drawings cleared, showing fence picker...")
            self._show_clear_fence_dialog(digitizer, classified_fences)

    def _show_clear_fence_dialog(self, digitizer, classified_fences):
        """Show a popup letting user choose which classified fences to keep or delete."""
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                                        QCheckBox, QWidget, QLabel, QScrollArea, QFrame)
        from PySide6.QtCore import Qt
        import numpy as np

        SHAPE_ICONS = {
            'rectangle': '▭', 'circle': '○', 'polygon': '⬟', 'polyline': '⬡',
            'line': '─', 'smartline': '⚡', 'smart_line': '⚡', 'freehand': '✏️'
        }

        dialog = QDialog(self, Qt.Window)
        dialog.setWindowTitle("Clear Classified Fences")
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.resize(420, 400)
        from gui.theme_manager import get_dialog_stylesheet, ThemeColors
        dialog.setStyleSheet(get_dialog_stylesheet())

        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        # Title
        title = QLabel("Select classified fences to DELETE")
        title.setStyleSheet(f"color: {ThemeColors.get('danger')}; font-weight: bold; font-size: 13px; padding: 8px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Unchecked fences will be kept. Checked fences will be removed.")
        subtitle.setStyleSheet(f"color: {ThemeColors.get('text_secondary')}; font-size: 10px; padding: 0 8px 8px 8px;")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

        # Scroll area for fence list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(4)

        checkboxes = []  # (checkbox, fence_dict) pairs

        for idx, fence in enumerate(classified_fences):
            shape_type = fence.get('type', 'unknown')
            coords = np.array(fence.get('coords', []))
            icon = SHAPE_ICONS.get(shape_type, '◆')

            coord_count = len(coords)
            if coord_count > 0:
                min_pt = coords.min(axis=0)
                max_pt = coords.max(axis=0)
                width = max_pt[0] - min_pt[0]
                height = max_pt[1] - min_pt[1]
                size_text = f"{width:.1f}x{height:.1f}m"
            else:
                size_text = "?"

            # Row widget
            row = QWidget()
            row.setStyleSheet(f"""
                QWidget {{
                    background-color: {ThemeColors.get('bg_button')};
                    border: 1px solid {ThemeColors.get('border')};
                    border-radius: 6px;
                    padding: 6px;
                }}
                QWidget:hover {{
                    background-color: {ThemeColors.get('bg_button_hover')};
                    border: 1px solid {ThemeColors.get('border_light')};
                }}
            """)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 6, 8, 6)

            cb = QCheckBox()
            cb.setStyleSheet(f"""
                QCheckBox::indicator {{
                    width: 18px; height: 18px;
                    border-radius: 3px; border: 1px solid {ThemeColors.get('border_light')};
                    background-color: {ThemeColors.get('bg_input')};
                }}
                QCheckBox::indicator:checked {{
                    background-color: {ThemeColors.get('danger')}; border: 1px solid {ThemeColors.get('danger')};
                }}
            """)
            row_layout.addWidget(cb)

            # Fence indicator
            indicator = QFrame()
            indicator.setFixedSize(8, 30)
            indicator.setStyleSheet(f"background-color: {ThemeColors.get('accent')}; border-radius: 2px;")
            row_layout.addWidget(indicator)

            label = QLabel(f"{icon} #{idx+1}: {shape_type.capitalize()}\n{coord_count} pts | {size_text}")
            label.setStyleSheet(f"color: {ThemeColors.get('text_primary')}; font-size: 10px; background: transparent; padding-left: 4px;")
            row_layout.addWidget(label, 1)

            # Make row clickable to toggle checkbox
            def make_click(checkbox):
                def on_click(event):
                    checkbox.setChecked(not checkbox.isChecked())
                return on_click
            row.mousePressEvent = make_click(cb)
            row.setCursor(Qt.PointingHandCursor)

            checkboxes.append((cb, fence))
            scroll_layout.addWidget(row)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)

        # Buttons row
        btn_row = QHBoxLayout()

        select_all_btn = QPushButton("Select All")
        select_all_btn.setObjectName("dangerBtn")
        select_all_btn.clicked.connect(lambda: [cb.setChecked(True) for cb, _ in checkboxes])
        btn_row.addWidget(select_all_btn)

        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.clicked.connect(lambda: [cb.setChecked(False) for cb, _ in checkboxes])
        btn_row.addWidget(clear_all_btn)

        btn_row.addStretch()

        keep_btn = QPushButton("Keep Selected")
        keep_btn.setToolTip("Close without deleting any fences")
        keep_btn.setObjectName("primaryBtn")
        keep_btn.clicked.connect(dialog.reject)
        btn_row.addWidget(keep_btn)

        delete_btn = QPushButton("Delete Checked")
        delete_btn.setObjectName("dangerBtn")
        btn_row.addWidget(delete_btn)

        layout.addLayout(btn_row)

        def on_delete():
            fences_to_delete = [fence for cb, fence in checkboxes if cb.isChecked()]
            if not fences_to_delete:
                dialog.accept()
                return

            for fence in fences_to_delete:
                try:
                    digitizer._remove_drawing(fence)
                    print(f"🗑️ Deleted classified fence: {fence.get('type', 'unknown')}")
                except Exception as e:
                    print(f"⚠️ Failed to delete fence: {e}")

            # Clean up fence dialog references if open
            try:
                dlg = getattr(digitizer.app, 'inside_fence_dialog', None)
                if dlg:
                    for fence in fences_to_delete:
                        if fence in getattr(dlg, 'selected_fences', []):
                            dlg.selected_fences.remove(fence)
                        for actor in getattr(dlg, '_classified_fence_actors', []):
                            if actor is fence.get('actor'):
                                try: digitizer.overlay_renderer.RemoveActor(actor)
                                except Exception: pass
                    dlg._clear_fence_highlights()
            except Exception as e:
                print(f"⚠️ Fence dialog cleanup: {e}")

            # Re-render
            try:
                if hasattr(digitizer, 'overlay_renderer') and digitizer.overlay_renderer:
                    digitizer.overlay_renderer.Modified()
                digitizer.renderer.Modified()
                digitizer.interactor.GetRenderWindow().Render()
                digitizer.app.vtk_widget.render()
            except Exception: pass

            print(f"✅ Deleted {len(fences_to_delete)} classified fence(s)")
            dialog.accept()

        delete_btn.clicked.connect(on_delete)
        dialog.exec()

    def _show_draw_settings(self):
        """Open the Draw Tool Settings dialog."""
        try:
            # Walk up to find the actual NakshaApp main window with digitizer
            main_window = self.window()
            widget = self
            while widget:
                if hasattr(widget, 'digitizer'):
                    main_window = widget
                    break
                widget = widget.parent()
            
            print(f"🔧 Draw Settings: app={type(main_window).__name__}, has digitizer={hasattr(main_window, 'digitizer')}")
            dialog = DrawToolSettingsDialog(main_window, parent=main_window)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            
        except Exception as e:
            print(f"⚠️ Failed to open Draw Settings: {e}")
            import traceback
            traceback.print_exc()

    def _handle_select_drawing_click(self):
        """Enter selection mode for curves/drawings."""
        main_window = self.window()
        
        if hasattr(main_window, 'digitizer') and main_window.digitizer:
            try:
                main_window.digitizer.deactivate_all()
            except Exception:
                try:
                    main_window.digitizer.set_tool(None)
                except Exception:
                    pass
        
        # ✅ FIXED: was calling deactivate, now calls activate_select_mode
        if hasattr(main_window, 'curve_tool') and main_window.curve_tool:
            ct = main_window.curve_tool
            if ct.active:
                ct.deactivate()
            if getattr(ct, '_select_mode', False):
                ct.deactivate_select_mode()
        
        if hasattr(main_window, 'measurement_tool'):
            try:
                main_window.measurement_tool.deactivate()
            except Exception:
                pass
        
        main_window.vtk_widget.setCursor(Qt.ArrowCursor)
        print("⛔ All tools deactivated")
        
        if hasattr(main_window, 'statusBar'):
            main_window.statusBar().showMessage(
                "✅ All tools off — Right-click grid labels to load LAZ data", 3000
            )


    def _handle_deselect_all_click(self):
        """Exit ALL tool modes — drawing, selection, everything."""
        main_window = self.window()
        
        if hasattr(main_window, 'digitizer') and main_window.digitizer:
            try:
                main_window.digitizer.deactivate_all()
            except Exception:
                try:
                    main_window.digitizer.set_tool(None)
                except Exception:
                    pass
        
        # ✅ FIXED: was calling deactivate, now calls activate_select_mode
        if hasattr(main_window, 'curve_tool') and main_window.curve_tool:
            main_window.curve_tool.activate_select_mode()
            print("🎯 Select Drawing mode activated from ribbon")
        else:
            print("⚠️ Curve tool not available")

    # ========================================================================
    # MOVE VERTEX HANDLER
    # ========================================================================
    def _handle_move_vertex_click(self):
        """Handle Move Vertex button click with Shift detection for settings"""
        modifiers = QApplication.keyboardModifiers()
       
        if modifiers & Qt.ShiftModifier:
            print("🔧 Shift detected - opening Move Vertex settings")
            self._show_move_vertex_settings()
        else:
            print("🔄 Normal Move Vertex activation")
            self.draw_tool_selected.emit("Move Vertex")
   
    def _show_move_vertex_settings(self):
        """Show Move Vertex settings dialog"""
        digitizer = self.window().digitizer
        current_mode = getattr(digitizer, 'vertex_move_mode_type', 'click')
       
        dialog = VertexMoveSettingsDialog(current_mode, self)
        if dialog.exec_() == QDialog.Accepted:
            digitizer.vertex_move_mode_type = dialog.get_move_mode()
            mode_str = "Click and Drag" if digitizer.vertex_move_mode_type == 'drag' else "Click to Select/Place"
            print(f"🔧 Vertex move mode: {mode_str}")
           
            # Activate Move Vertex tool
            self.draw_tool_selected.emit("Move Vertex")
   
    # ========================================================================
    # SMARTLINE SETTINGS
    # ========================================================================
    def _handle_smartline_click(self):
        """Handle SmartLine button click with Shift detection for arrow settings"""
        modifiers = QApplication.keyboardModifiers()
       
        if modifiers & Qt.ShiftModifier:
            print("🔧 Shift detected - opening SmartLine arrow settings")
            self._show_smartline_settings()
        else:
            print("🖊️ Normal SmartLine activation")
            self.draw_tool_selected.emit("Smartline")
   
    def _show_smartline_settings(self):
        """Show SmartLine arrow settings dialog"""
        digitizer = self.window().digitizer
        current_arrow = getattr(digitizer, 'smartline_arrow_mode', False)
       
        dialog = LineArrowSettingsDialog("SmartLine", current_arrow, self)
        if dialog.exec_() == QDialog.Accepted:
            digitizer.smartline_arrow_mode = dialog.get_arrow_mode()
            print(f"🔧 SmartLine arrow mode: {'ENABLED' if digitizer.smartline_arrow_mode else 'DISABLED'}")
           
            # Activate SmartLine
            self.draw_tool_selected.emit("Smartline")
   
    # ========================================================================
    # LINE SETTINGS
    # ========================================================================
    def _handle_line_click(self):
        """Handle Line button click with Shift detection for arrow settings"""
        modifiers = QApplication.keyboardModifiers()
       
        if modifiers & Qt.ShiftModifier:
            print("🔧 Shift detected - opening Line arrow settings")
            self._show_line_settings()
        else:
            print("🖊️ Normal Line activation")
            self.draw_tool_selected.emit("Line")
   
    def _show_line_settings(self):
        """Show Line arrow settings dialog"""
        digitizer = self.window().digitizer
        current_arrow = getattr(digitizer, 'line_arrow_mode', False)
       
        dialog = LineArrowSettingsDialog("Line", current_arrow, self)
        if dialog.exec_() == QDialog.Accepted:
            digitizer.line_arrow_mode = dialog.get_arrow_mode()
            print(f"🔧 Line arrow mode: {'ENABLED' if digitizer.line_arrow_mode else 'DISABLED'}")
           
            # Activate Line
            self.draw_tool_selected.emit("Line")
   
    # ========================================================================
    # ORTHO SETTINGS
    # ========================================================================
    def _handle_ortho_click(self):
        """Handle Ortho button click with Shift detection"""
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier:
            self._show_tool_permanent_settings('orthopolygon', 'orthopolygon_permanent_mode', 'Orthopolygon')
        else:
            self.draw_tool_selected.emit("orthopolygon")

    # ========================================================================
    # POLYLINE SETTINGS (existing)
    # ========================================================================
    def _handle_polyline_click(self):
        """Handle Polyline button click with Shift detection"""
        modifiers = QApplication.keyboardModifiers()
       
        if modifiers & Qt.ShiftModifier:
            print("🔧 Shift detected - opening settings dialog")
            self._show_polyline_settings()
        else:
            print("🖊️ Normal polyline activation")
            self.draw_tool_selected.emit("Polyline")
 
    def _show_polyline_settings(self):
        """Show polyline settings dialog"""
        digitizer = self.window().digitizer
        current_permanent = getattr(digitizer, 'polyline_permanent_mode', False)
       
        dialog = PolylineSettingsDialog(current_permanent, self)
        if dialog.exec_() == QDialog.Accepted:
            digitizer.polyline_permanent_mode = dialog.get_permanent_mode()
            print(f"🔧 Polyline mode set to: {'Permanent' if digitizer.polyline_permanent_mode else 'Temporary'}")
           
            # Activate polyline with new mode
            mode = "Polyline_Permanent" if digitizer.polyline_permanent_mode else "Polyline"
            self.draw_tool_selected.emit(mode)
           
    def _handle_rect_click(self):
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier:
            self._show_tool_permanent_settings('rectangle', 'rectangle_permanent_mode', 'Rectangle')
        else:
            self.draw_tool_selected.emit("Rectangle")

    def _handle_circle_click(self):
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier:
            self._show_tool_permanent_settings('circle', 'circle_permanent_mode', 'Circle')
        else:
            self.draw_tool_selected.emit("Circle")

    def _handle_freehand_click(self):
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier:
            self._show_tool_permanent_settings('freehand', 'freehand_permanent_mode', 'Freehand')
        else:
            self.draw_tool_selected.emit("Freehand")

    def _show_tool_permanent_settings(self, flag_name, attr_name, emit_name):
        """Generic permanent mode settings dialog for any draw tool"""
        digitizer = self.window().digitizer
        current_permanent = getattr(digitizer, attr_name, False)
        dialog = PolylineSettingsDialog(current_permanent, self)  # reuse existing dialog
        if dialog.exec_() == QDialog.Accepted:
            setattr(digitizer, attr_name, dialog.get_permanent_mode())
            mode = f"{emit_name}_Permanent" if getattr(digitizer, attr_name) else emit_name
            print(f"🔧 {emit_name} mode: {'Permanent' if getattr(digitizer, attr_name) else 'Temporary'}")
            self.draw_tool_selected.emit(emit_name)  # always activate the tool after setting           
    # ========================================================================
    # VERTEX SETTINGS
    # ========================================================================
    def _handle_vertex_click(self):
        """Handle Vertex button click with Shift detection for insert mode settings"""
        modifiers = QApplication.keyboardModifiers()
       
        if modifiers & Qt.ShiftModifier:
            print("🔧 Shift detected - opening Vertex settings")
            self._show_vertex_settings()
        else:
            print("🔵 Normal Vertex tool activation")
            self.draw_tool_selected.emit("Vertex")
 
    def _show_vertex_settings(self):
        """Show Vertex tool settings dialog"""
        digitizer = self.window().digitizer
        current_auto_drag = getattr(digitizer, 'vertex_auto_drag', False)
       
        dialog = VertexInsertSettingsDialog(current_auto_drag, self)
        if dialog.exec_() == QDialog.Accepted:
            digitizer.vertex_auto_drag = dialog.get_auto_drag_mode()
            mode_str = "Insert and Drag" if digitizer.vertex_auto_drag else "Insert Only"
            print(f"🔧 Vertex mode: {mode_str}")
           
            # Activate Vertex tool
        self.draw_tool_selected.emit("Vertex")

class RibbonManager:
    """Manages all ribbon panels"""
    
    def __init__(self, parent_window):
        self.parent = parent_window
        self.ribbons = {}
        self.current_ribbon = None
        self.create_ribbons()
        
    def create_ribbons(self):
        """Create all ribbon instances"""
        self.ribbons['file'] = FileRibbon(self.parent)
        self.ribbons['edit'] = EditRibbon(self.parent)
        self.ribbons['view'] = ViewRibbon(self.parent)
        self.ribbons['tools'] = ToolsRibbon(self.parent)
        self.ribbons['classify'] = ClassifyRibbon(self.parent)
        self.ribbons['display'] = DisplayRibbon(self.parent)
       
        self.ribbons['measure'] = MeasurementRibbon(self.parent)
        self.ribbons['identify'] = IdentificationRibbon(self.parent, app=self.parent)
        self.ribbons['by_class'] = ByClassRibbon(self.parent, app=self.parent)
        self.ribbons['draw'] = DrawRibbon(self.parent)
        self.ribbons['curve'] = CurveRibbon(self.parent)
        self.ribbons['ai'] = AIRibbon(self.parent, app=self.parent)

        
        # Hide all by default
        for ribbon in self.ribbons.values():
            ribbon.hide()
            
    def show_ribbon(self, ribbon_name):
        """Show a specific ribbon"""
        if ribbon_name not in self.ribbons:
            return

        if self.current_ribbon != ribbon_name:
            point_sync_tool = getattr(self.parent, 'point_sync_tool', None)
            if point_sync_tool and getattr(point_sync_tool, 'active', False):
                try:
                    point_sync_tool.deactivate()
                except Exception:
                    pass

        # Hide current ribbon if different
        if self.current_ribbon and self.current_ribbon != ribbon_name:
            # ◀◀◀ NEW: Deactivate Curve tools when leaving 'curve' tab
            if self.current_ribbon == 'curve' and ribbon_name != 'curve':
                if hasattr(self.parent, 'curve_tool') and self.parent.curve_tool:
                    try:
                        self.parent.curve_tool.deactivate()
                        self.parent.curve_tool.deactivate_select_mode()
                    except Exception: pass
            
            # ◀◀◀ NEW: Deactivate Draw tools when leaving 'draw' tab
            elif self.current_ribbon == 'draw' and ribbon_name != 'draw':
                if hasattr(self.parent, 'digitizer') and self.parent.digitizer:
                    try: self.parent.digitizer.set_tool(None)
                    except Exception: pass
            
            # ◀◀◀ NEW: Deactivate Measure tools when leaving 'measure' tab
            elif self.current_ribbon == 'measure' and ribbon_name != 'measure':
                if hasattr(self.parent, 'measurement_tool') and self.parent.measurement_tool:
                    try: self.parent.measurement_tool.deactivate()
                    except Exception: pass
            
            # ◀◀◀ NEW: Deactivate Identify tools when leaving 'identify' tab
            elif self.current_ribbon == 'identify' and ribbon_name != 'identify':
                ribbon = self.ribbons.get('identify')
                if ribbon and hasattr(ribbon, 'deactivate_all_tools'):
                    try: ribbon.deactivate_all_tools()
                    except Exception: pass
                    
            # Deactivate Classify tools when leaving 'classify' tab
            elif self.current_ribbon == 'classify' and ribbon_name != 'classify':
                if getattr(self.parent, 'active_classify_tool', None):
                    try: self.parent.deactivate_classification_tool(preserve_cross_section=True)
                    except: pass

            # Deactivate Tools tools when leaving 'tools' tab
            elif self.current_ribbon == 'tools' and ribbon_name != 'tools':
                try: self.parent.deactivate_cross_section_tool()
                except: pass
                try:
                    if hasattr(self.parent, 'cut_section_controller') and self.parent.cut_section_controller:
                        self.parent.cut_section_controller.deactivate_tool_only()
                        self.parent.cut_section_mode_on = False
                        self.parent.set_cross_cursor_active(False)
                except: pass

            self.ribbons[self.current_ribbon].hide()
        
        # Show requested ribbon
        ribbon = self.ribbons[ribbon_name]
        ribbon.show()
        self.current_ribbon = ribbon_name
        
    def hide_current(self):
        """Hide the currently visible ribbon"""
        if self.current_ribbon:
            self.ribbons[self.current_ribbon].hide()
            self.current_ribbon = None
            
    def toggle_ribbon(self, name):
        """Toggle ribbon visibility"""
        if self.current_ribbon == name:
            self.hide_current()
        else:
            self.show_ribbon(name)

        # Deactivate all buttons in previously open ribbon
        if self.current_ribbon and self.current_ribbon != name:
            for section in self.ribbons[self.current_ribbon].findChildren(RibbonSection):
                if section.active_button:
                    section.active_button.setChecked(False)
                    section.active_button = None


class MeasurementRibbon(QWidget):
    """Ribbon for Measurement tools with live distance display"""
    
    measure_tool_selected = Signal(str)
    clear_measurements = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.build_ribbon()
        
    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # 📏 Distance Tools
        distance = RibbonSection("Distance", self)
        distance.add_button("Line", "📐", lambda: self.measure_tool_selected.emit("measure_line"))
        distance.add_button("Path", "🛤️", lambda: self.measure_tool_selected.emit("measure_path"))
        layout.addWidget(distance)
    
        
        # 🗑️ Actions
        actions = RibbonSection("Actions", self)
        actions.add_button("Clear", "🗑️", self.clear_measurements.emit)
        layout.addWidget(actions)
        
        layout.addStretch()

class IdentificationRibbon(QWidget):
    """Ribbon for Identification tool to identify point classes on click"""
   
    identify_tool_selected = Signal(str)
    identify_toggled = Signal(bool)
   
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.identify_active = False
        self.select_rectangle_active = False  
        self.build_ribbon()
        self.zoom_rectangle_active = False
       
    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
       
        # 🔍 Identification Tools
        # ✅ RibbonSection should be defined in the same file (menu_sidebar_system.py)
        # No import needed if it's in the same module
        identify = RibbonSection("Identify", self)
        self.identify_btn = identify.add_button("Identify", "🔍", self.toggle_identify, toggleable=True)
        self.zoom_rect_btn = identify.add_button("Zoom", "⬚", self.toggle_zoom_rectangle, toggleable=True) 
        self.select_rect_btn = identify.add_button("Select", "☑️", self.toggle_select_rectangle, toggleable=True)  # ✅ NEW
        layout.addWidget(identify)
            
        # ℹ️ Info Display
        info = QWidget()
        info.setObjectName("ribbonSection")
        info_outer_layout = QVBoxLayout(info)
        info_outer_layout.setContentsMargins(4, 3, 4, 3)
        info_outer_layout.setSpacing(3)
        info_outer_layout.setAlignment(Qt.AlignTop)
       
        # Title
        info_title = QLabel("Point Info")
        info_title.setObjectName("ribbonSectionTitle")
        info_title.setAlignment(Qt.AlignCenter)
        info_outer_layout.addWidget(info_title)

        info_box = QWidget()
        info_box.setObjectName("ribbonSectionBox")
        info_box.setAttribute(Qt.WA_StyledBackground, True)
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_layout.setSpacing(6)
       
        # Status label - THIS IS THE ONE WE'LL UPDATE
        self.status_label = QLabel("Click on point cloud")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)  # ✅ Allow multi-line text
        self.status_label.setObjectName("paramLabel")
        info_layout.addWidget(self.status_label)
        
        
        
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.setFixedHeight(28)
        self.delete_btn.setVisible(False)  # Hidden until points are selected
        self.delete_btn.setObjectName("sidebarButtonDanger")
        self.delete_btn.clicked.connect(self.delete_selected_points)
        info_layout.addWidget(self.delete_btn)

        info_outer_layout.addWidget(info_box)
        layout.addWidget(info)
        layout.addStretch()
        self._reset_status_label()
        
        
    def toggle_select_rectangle(self):
        """Toggle select rectangle mode on/off"""
        self.select_rectangle_active = not self.select_rectangle_active
        
        if self.select_rectangle_active:
            self._deactivate_identify()
            self._deactivate_zoom_rectangle()
            
            self.status_label.setText("Draw rectangle to select points")
            self.status_label.setStyleSheet("color: #ff9800; font-weight: bold;")
            
            # Activate select rectangle tool
            if self.app and hasattr(self.app, 'select_rectangle_tool'):
                self.app.select_rectangle_tool.activate()
            else:
                print("❌ ERROR: Cannot find select_rectangle_tool!")
                
        else:
            self._deactivate_select_rectangle()
            self._reset_status_label()

    def deactivate_all_tools(self):
        """Deactivate all identify/select tools in this ribbon."""
        self._deactivate_identify()
        self._deactivate_zoom_rectangle()
        self._deactivate_select_rectangle()
        self._reset_status_label()

    def _reset_button_style(self, button):
        """Reset button to default style"""
        button.setStyleSheet("")

    def _reset_status_label(self):
        """Reset ribbon status to the default idle state."""
        from gui.theme_manager import get_status_label_style

        self.status_label.setText("Click on point cloud")
        self.status_label.setStyleSheet(get_status_label_style())

    def _deactivate_identify(self):
        """Ensure the Identify tool is fully turned off."""
        self.identify_active = False
        self.identify_btn.setChecked(False)
        self._reset_button_style(self.identify_btn)

        if self.app and hasattr(self.app, 'identification_tool'):
            self.app.identification_tool.deactivate()

    def _deactivate_zoom_rectangle(self):
        """Ensure the Zoom tool is fully turned off."""
        self.zoom_rectangle_active = False
        self.zoom_rect_btn.setChecked(False)
        self._reset_button_style(self.zoom_rect_btn)

        if self.app and hasattr(self.app, 'zoom_rectangle_tool'):
            self.app.zoom_rectangle_tool.deactivate()

    def _deactivate_select_rectangle(self):
        """Ensure the Select tool is fully turned off."""
        self.select_rectangle_active = False
        self.select_rect_btn.setChecked(False)
        self._reset_button_style(self.select_rect_btn)
        self.delete_btn.setVisible(False)

        if self.app and hasattr(self.app, 'select_rectangle_tool'):
            self.app.select_rectangle_tool.deactivate()

    def update_selected_count(self, count):
        """Update status label with number of selected points"""
        if count > 0:
            self.status_label.setText(f"{count:,} points selected")
            self.status_label.setStyleSheet("color: #ff9800; font-weight: bold;")
            self.delete_btn.setVisible(True)
        else:
            self.status_label.setText("Draw rectangle to select points")
            self.delete_btn.setVisible(False)

    def delete_selected_points(self):
        """Delete the selected points"""
        if self.app and hasattr(self.app, 'select_rectangle_tool'):
            self.app.select_rectangle_tool.delete_selected_points()
            
    def toggle_identify(self):
        """Toggle identification mode on/off"""
        self.identify_active = not self.identify_active
        
        if self.identify_active:
            self._deactivate_zoom_rectangle()
            self._deactivate_select_rectangle()
       
        if self.identify_active:
            self.status_label.setText("Active")
            self.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
           
            # Activate the identification tool
            if self.app and hasattr(self.app, 'identification_tool'):
                self.app.identification_tool.activate()
            else:
                print("❌ ERROR: Cannot find identification_tool!")
               
        else:
            self._deactivate_identify()
            self._reset_status_label()
       
        self.identify_toggled.emit(self.identify_active)
        
        
    def toggle_zoom_rectangle(self):
        """Toggle zoom rectangle mode on/off"""
        self.zoom_rectangle_active = not self.zoom_rectangle_active
        
        if self.zoom_rectangle_active:
            self._deactivate_identify()
            self._deactivate_select_rectangle()

            self.status_label.setText("Draw rectangle & right-click")
            self.status_label.setStyleSheet("color: #2196f3; font-size: 9px; font-weight: bold; padding: 4px;")

            # Activate zoom rectangle tool
            if self.app and hasattr(self.app, 'zoom_rectangle_tool'):
                self.app.zoom_rectangle_tool.activate()

        else:
            self._deactivate_zoom_rectangle()
            self._reset_status_label()
   
    def update_info(self, class_code, class_name, xyz, color=None, lvl=None):
        """
        Update the displayed information with class color background.
        
        Args:
            class_code: Classification code (e.g., 2 for Ground)
            class_name: Human-readable name (e.g., "Ground")
            xyz: Tuple of (x, y, z) coordinates
            color: Optional RGB tuple (r, g, b) for background color
            lvl: Optional level/priority string (e.g., "5")
        """
        # ✅ NEW: Build info text with Level
        x, y, z = xyz
        info_text = f"Class {class_code}: {class_name}"
        
        # ✅ ADD: Show Level if available
        if lvl:
            info_text += f" | Lvl: {lvl}"
        
        # Add coordinates on second line
        info_text += f"\nXYZ: ({x:.2f}, {y:.2f}, {z:.2f})"
        
        self.status_label.setText(info_text)
        
        # ✅ Apply class color as background if provided
        if color:
            r, g, b = color
            
            # Calculate luminance to determine if we need dark or light text
            luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
            text_color = "#000000" if luminance > 0.5 else "#FFFFFF"
            
            # Apply colored background to status_label
            self.status_label.setStyleSheet(f"""
                QLabel {{
                    color: {text_color};
                    font-size: 9px;
                    font-weight: bold;
                    padding: 6px;
                    background-color: rgba({r}, {g}, {b}, 0.9);
                    border: 2px solid rgb({r}, {g}, {b});
                    border-radius: 3px;
                }}
            """)
        else:
            # Fallback to default blue
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #ffffff;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 6px;
                    background-color: #0d47a1;
                    border: 2px solid #1565c0;
                    border-radius: 3px;
                }
            """)
    def clear(self):
        """Clear the information display."""
        self._reset_status_label()

def make_color_icon(rgb):
    """Helper to create color icons for class picker"""
    pix = QPixmap(20, 12)
    pix.fill(QColor(*rgb))
    return QIcon(pix)


class ByClassRibbon(QWidget):
    """
    Ribbon for By Class tool - automatic class conversion
    Opens a dialog similar to ClassPicker but with Convert instead of Invert
    
    ✅ NEW: Dialogs auto-restore when hidden/minimized
    """
    conversion_applied = Signal()
    
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        
        # ✅ Store dialog references
        self.by_class_dialog = None
        self.closed_by_class_dialog = None
        self.height_convert_dialog = None 
        self.inside_fence_dialog = None
        self.low_points_dialog    = None
        self.isolated_dialog      = None
        self.ground_dialog        = None
        self.below_surface_dialog = None
        self.build_ribbon()

        # These work even when dialogs are closed
        from PySide6.QtGui import QShortcut, QKeySequence
        from PySide6.QtCore import Qt
        
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.perform_classification_undo)
        self.undo_shortcut.setContext(Qt.ApplicationShortcut)  # ✅ Works app-wide
        
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.activated.connect(self.perform_classification_redo)
        self.redo_shortcut.setContext(Qt.ApplicationShortcut)  # ✅ Works app-wide
        
        print("✅ ByClassRibbon: Application-level undo/redo shortcuts installed")
    
    def build_ribbon(self):
        """Build the ribbon UI"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # 🔄 By Class Section
        by_class_section = RibbonSection("By Class", self)
        
        self.convert_btn = by_class_section.add_button(
            "Convert", 
            "🔄", 
            self.open_convert_dialog,
            toggleable=False
        )
        self.closed_convert_btn = by_class_section.add_button(
            "Close", 
            "📍", 
            self.open_closed_convert_dialog,
            toggleable=False
        )
        self.height_convert_btn = by_class_section.add_button(
            "Height",
            "📏",
            self.open_height_convert_dialog,
            toggleable=False
        )
        self.inside_fence_btn = by_class_section.add_button(
            "Fence", 
            "🔷", 
            self.open_inside_fence_dialog,
            toggleable=False
        )
                    
        layout.addWidget(by_class_section)
        
        algo_section = RibbonSection("Algorithms", self)
        algo_section.add_button("Low Points", "⬇️", self.open_low_points_dialog,    toggleable=False)
        algo_section.add_button("Isolated",   "🔴", self.open_isolated_dialog,      toggleable=False)
        algo_section.add_button("Ground",     "🏔️", self.open_ground_dialog,        toggleable=False)
        algo_section.add_button("Surface",    "📐", self.open_below_surface_dialog,  toggleable=False)
        layout.addWidget(algo_section)

        # ℹ️ Info Display
        info = QWidget()
        info.setObjectName("infoWidget")
        info_layout = QVBoxLayout(info)
        info_layout.setContentsMargins(8, 4, 8, 4)
        info_layout.setSpacing(2)
        
        # Title
        info_title = QLabel("Conversion Info")
        info_title.setObjectName("ribbonSectionTitle")
        info_title.setFont(QFont("Segoe UI", 8))
        info_title.setAlignment(Qt.AlignCenter)
        info_layout.addWidget(info_title)
        
        # Status label
        self.status_label = QLabel("Click Convert to begin")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 9px;
                padding: 4px;
                background-color: #2c2c2c;
                border-radius: 3px;
            }
        """)
        info_layout.addWidget(self.status_label)
        
        layout.addWidget(info)
        layout.addStretch()
        
        
    def perform_classification_undo(self):
        # ✅ If digitizer tool is active, let it handle undo
        digitizer = getattr(self.app, 'digitizer', None)
        if digitizer and getattr(digitizer, 'active_tool', None):
            print("🔄 ByClassRibbon: Digitizer active — routing Ctrl+Z to digitizer")
            digitizer.undo()
            return
        print("🔄 ByClassRibbon: Classification undo triggered")
        if not hasattr(self.app, 'undo_classification'):
            print("⚠️ ByClassRibbon: undo_classification not available")
            return
        
        try:
            # ✅ FIXED: undo_classification() already handles ALL refreshes
            # No need to call update_class_mode again!
            self.app.undo_classification()
            
            # Update point count widget (if undo didn't already do it)
            if hasattr(self.app, 'point_count_widget'):
                if not hasattr(self.app, 'update_point_count_display'):
                    self.app.point_count_widget.schedule_update()
            
            # Update status
            self.update_status("↶ Undo performed", "neutral")
            
            print("✅ Classification undo complete")
            
        except Exception as e:
            print(f"❌ Undo failed: {e}")
            import traceback
            traceback.print_exc()
            self.update_status("❌ Undo failed", "error")
            
    def perform_classification_redo(self):
        """
        ✅ Application-level CLASSIFICATION redo
        Works even when dialogs are closed
        """
        print("🔄 ByClassRibbon: Classification redo triggered")
        
        if not hasattr(self.app, 'redo_classification'):
            print("⚠️ ByClassRibbon: redo_classification not available")
            return
        
        try:
            # ✅ FIXED: redo_classification() already handles ALL refreshes
            # No need to call update_class_mode again!
            self.app.redo_classification()
            
            # Update point count widget (if redo didn't already do it)
            if hasattr(self.app, 'point_count_widget'):
                if not hasattr(self.app, 'update_point_count_display'):
                    self.app.point_count_widget.schedule_update()
            
            # Update status
            self.update_status("↷ Redo performed", "neutral")
            
            print("✅ Classification redo complete")
            
        except Exception as e:
            print(f"❌ Redo failed: {e}")
            import traceback
            traceback.print_exc()
            self.update_status("❌ Redo failed", "error")
            
    def _show_or_raise_dialog(self, dialog, dialog_name):
        """
        ✅ Helper: Show/raise dialog if hidden or minimized
        
        Args:
            dialog: Dialog instance
            dialog_name: Name for logging
        """
        if dialog is None:
            return
        
        # Show if hidden
        if dialog.isHidden():
            print(f"👁️ {dialog_name} was hidden - showing...")
            dialog.show()
        
        # Restore if minimized
        if dialog.isMinimized():
            print(f"⬆️ {dialog_name} was minimized - restoring...")
            dialog.showNormal()
        
        # Raise to front and activate
        dialog.raise_()
        dialog.activateWindow()
        print(f"✅ {dialog_name} raised to front")

    def open_convert_dialog(self):
        """
        ✅ FIXED: Open/show By Class conversion dialog
        Creates new dialog or shows existing one
        """
        from gui.menu_sidebar_system import ByClassDialog
        
        # Create if doesn't exist
        if self.by_class_dialog is None:
            print("🆕 Creating new ByClassDialog...")
            self.by_class_dialog = ByClassDialog(self.app, self)
            
            # Clear reference when destroyed
            self.by_class_dialog.destroyed.connect(
                lambda: setattr(self, 'by_class_dialog', None)
            )
        
        # Show and raise
        self._show_or_raise_dialog(self.by_class_dialog, "ByClassDialog")

    def open_closed_convert_dialog(self):
        """
        ✅ FIXED: Open/show Closed By Class dialog
        """
        # Create if doesn't exist
        if self.closed_by_class_dialog is None:
            print("🆕 Creating new ClosedByClassDialog...")
            self.closed_by_class_dialog = ClosedByClassDialog(self.app, self)
            
            # Clear reference when destroyed
            self.closed_by_class_dialog.destroyed.connect(
                lambda: setattr(self, 'closed_by_class_dialog', None)
            )
        
        # Show and raise
        self._show_or_raise_dialog(self.closed_by_class_dialog, "ClosedByClassDialog")
    
    def open_height_convert_dialog(self):
        """
        ✅ FIXED: Open/show By Height dialog
        """
        # Create if doesn't exist
        if self.height_convert_dialog is None:
            print("🆕 Creating new ByClassHeightDialog...")
            self.height_convert_dialog = ByClassHeightDialog(self.app, self)
            
            # Clear reference when destroyed
            self.height_convert_dialog.destroyed.connect(
                lambda: setattr(self, 'height_convert_dialog', None)
            )
        
        # Show and raise
        self._show_or_raise_dialog(self.height_convert_dialog, "ByClassHeightDialog")
    
    def open_inside_fence_dialog(self):
        """
        ✅ FIXED: Open/show Inside Fence dialog
        """
        # Create if doesn't exist
        if self.inside_fence_dialog is None:
            print("🆕 Creating new InsideFenceDialog...")
            self.inside_fence_dialog = InsideFenceDialog(self.app, self)
            
            # Clear reference when destroyed
            self.inside_fence_dialog.destroyed.connect(
                lambda: setattr(self, 'inside_fence_dialog', None)
            )
        self._show_or_raise_dialog(self.inside_fence_dialog, "InsideFenceDialog")
    

    def open_low_points_dialog(self):
        try:
            from gui.lidar_classification_tools import ClassifyLowPointsDialog
        except ImportError:
            from lidar_classification_tools import ClassifyLowPointsDialog
        if self.low_points_dialog is None:
            self.low_points_dialog = ClassifyLowPointsDialog(self.app, parent=self.app)
            from PySide6.QtCore import Qt
            self.low_points_dialog.setAttribute(Qt.WA_DeleteOnClose)
            self.low_points_dialog.destroyed.connect(lambda: setattr(self, "low_points_dialog", None))
        self._show_or_raise_dialog(self.low_points_dialog, "ClassifyLowPointsDialog")

    def open_isolated_dialog(self):
        try:
            from gui.lidar_classification_tools import ClassifyIsolatedPointsDialog
        except ImportError:
            from lidar_classification_tools import ClassifyIsolatedPointsDialog
        if self.isolated_dialog is None:
            self.isolated_dialog = ClassifyIsolatedPointsDialog(self.app, parent=self.app)
            from PySide6.QtCore import Qt
            self.isolated_dialog.setAttribute(Qt.WA_DeleteOnClose)
            self.isolated_dialog.destroyed.connect(lambda: setattr(self, "isolated_dialog", None))
        self._show_or_raise_dialog(self.isolated_dialog, "ClassifyIsolatedPointsDialog")

    def open_ground_dialog(self):
        try:
            from gui.lidar_classification_tools import ClassifyGroundDialog
        except ImportError:
            from lidar_classification_tools import ClassifyGroundDialog
        if self.ground_dialog is None:
            self.ground_dialog = ClassifyGroundDialog(self.app, parent=self.app)
            from PySide6.QtCore import Qt
            self.ground_dialog.setAttribute(Qt.WA_DeleteOnClose)
            self.ground_dialog.destroyed.connect(lambda: setattr(self, "ground_dialog", None))
        self._show_or_raise_dialog(self.ground_dialog, "ClassifyGroundDialog")

    def open_below_surface_dialog(self):
        try:
            from gui.lidar_classification_tools import ClassifyBelowSurfaceDialog
        except ImportError:
            from lidar_classification_tools import ClassifyBelowSurfaceDialog
        if self.below_surface_dialog is None:
            self.below_surface_dialog = ClassifyBelowSurfaceDialog(self.app, parent=self.app)
            from PySide6.QtCore import Qt
            self.below_surface_dialog.setAttribute(Qt.WA_DeleteOnClose)
            self.below_surface_dialog.destroyed.connect(lambda: setattr(self, "below_surface_dialog", None))
        self._show_or_raise_dialog(self.below_surface_dialog, "ClassifyBelowSurfaceDialog")

    def update_status(self, message, color_type="neutral"):
        """Update the status label with conversion info"""
        self.status_label.setText(message)
        
        if color_type == "success":
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px;
                    background-color: #1b5e20;
                    border-radius: 3px;
                }
            """)
        elif color_type == "error":
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #f44336;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px;
                    background-color: #c62828;
                    border-radius: 3px;
                }
            """)
        else:
            self.status_label.setStyleSheet("""
                QLabel {
                    color: #aaaaaa;
                    font-size: 9px;
                    padding: 4px;
                    background-color: #2c2c2c;
                    border-radius: 3px;
                }
            """)



from PySide6.QtGui import QShortcut, QKeySequence

class ByClassDialog(QDialog):
    """
    Class Conversion Dialog - Similar to ClassPicker but with Convert button
    ✅ FIXED: Shows level and description like ClassPicker
    ✅ FIXED: Auto-updates when PTC changes in Display Mode
    ✅ FIXED: Preserves selections when classes reload
    ✅ FIXED: Proper undo/redo shortcuts that don't conflict with Digitizer
    """
   
    def __init__(self, app, ribbon_parent):
        # ✅ FIX 1: Robust Parent Finding
        from PySide6.QtWidgets import QWidget
        target_parent = None
        if isinstance(app, QWidget):
            target_parent = app
        elif hasattr(app, 'window') and isinstance(app.window, QWidget):
            target_parent = app.window

        # ✅ FIX 2: Pass Qt.Window directly to super()
        # This prevents "StaysOnTop" behavior which causes the weird stacking.
        # It will now minimize nicely to the bottom like the other dialogs.
        super().__init__(None, Qt.Window)
        self.setAttribute(Qt.WA_NativeWindow, True)  # Fix: GetDC invalid window handle  
        self.setWindowModality(Qt.NonModal)
        self.app = app
        self.ribbon_parent = ribbon_parent
        
        self.setWindowTitle("Convert Classes")
        # self.setStyleSheet(self.naksha_dark_theme()) # Inherits global theme
        self.setGeometry(200, 200, 380, 420)

        # Shortcuts
       
        
        self.init_ui()
        self.populate_classes()
        self._last_conversion_info = None
        self._connected_display_dialog = None

        self._connect_display_dialog()

    def _get_display_dialog(self):
        return getattr(self.app, 'display_mode_dialog', getattr(self.app, 'display_dialog', None))

    def _connect_display_dialog(self):
        """Keep the dialog wired to the current Display Mode instance."""
        display_dialog = self._get_display_dialog()
        if display_dialog is None or display_dialog is self._connected_display_dialog:
            return

        if self._connected_display_dialog is not None:
            try:
                self._connected_display_dialog.classes_loaded.disconnect(self.on_classes_changed)
            except Exception:
                pass

        try:
            display_dialog.classes_loaded.connect(self.on_classes_changed)
        except Exception as e:
            print(f"⚠️ ByClassDialog could not connect to Display Mode updates: {e}")
            return

        self._connected_display_dialog = display_dialog
        print("✅ ByClassDialog connected to display_mode_dialog.classes_loaded")


    def _prune_stale_fences(self):
        """
        Remove any selected_fences whose drawing no longer exists in the
        digitizer (e.g. user cleared them via the Draw toolbar).
        """
        digitizer = getattr(self.app, 'digitizer', None)
        if not digitizer:
            # No digitizer at all → can't validate → clear everything to be safe
            if self.selected_fences:
                print(f"   ⚠️ No digitizer — pruning all {len(self.selected_fences)} stale fences")
                self.selected_fences = []
                self._clear_fence_highlights()
                self._reset_fence_ui()
            return
 
        existing_drawings = getattr(digitizer, 'drawings', [])
 
        # Build a set of existing coordinate fingerprints for fast lookup
        def coords_key(coords):
            try:
                return tuple(tuple(c[:2]) for c in coords)   # XY only, ignore Z rounding
            except Exception:
                return ()
 
        existing_keys = {coords_key(d.get('coords', [])) for d in existing_drawings}
 
        before = len(self.selected_fences)
        self.selected_fences = [
            f for f in self.selected_fences
            if coords_key(f.get('coords', [])) in existing_keys
        ]
        after = len(self.selected_fences)
 
        if before != after:
            pruned = before - after
            print(f"   🧹 Pruned {pruned} stale fence reference(s) "
                  f"({after} remaining)")
            # Remove any now-orphaned highlight actors
            self._clear_fence_highlights()
            self.update_fence_display()
 
            if not self.selected_fences:
                self._reset_fence_ui()
 
 
    def _reset_fence_ui(self):
        """Reset the fence status label to 'no fence selected'."""
        self.selected_fences = []
        self.permanent_fence_mode = False
        self.fence_count_badge.setText("0")
        self.fence_status.setText("❌ No fence selected")
        self.fence_status.setStyleSheet("""
            QLabel {
                padding: 4px; background-color: #2c2c2c;
                border-radius: 3px; color: #f44336;
            }
        """)

    def showEvent(self, event):
        """Ensure dialog gets focus when shown."""
        super().showEvent(event)
        self.setFocus()
        self.activateWindow()
        # ✅ FIX: Do NOT restore blue highlights on show.
        # They are selection-preview actors created inside select_fence().
        # After classification they are cleared; we never want them restored
        # automatically — that is what caused the phantom blue box.
        print("🔵 ByClassHeightDialog activated and focused")

    def _get_selected_from_classes(self):
        return [item.data(Qt.UserRole) for item in self.from_list.selectedItems()]

    def refresh_class_lists(self, reason="classes changed", update_status=True):
        """Rebuild the class pickers while preserving current selections."""
        old_from_classes = self._get_selected_from_classes()
        old_to = self.to_combo.currentData()

        print("\n" + "=" * 60)
        print(f"🔄 BY CLASS DIALOG: Refresh requested ({reason})")
        print("=" * 60)
        print(f"   📋 Saving selections: From={old_from_classes}, To={old_to}")

        self.populate_classes()

        restored_count = 0
        if old_to is not None:
            idx = self.to_combo.findData(old_to)
            if idx >= 0:
                self.to_combo.setCurrentIndex(idx)
                restored_count += 1

        if old_from_classes:
            for code in old_from_classes:
                for i in range(self.from_list.count()):
                    item = self.from_list.item(i)
                    if item.data(Qt.UserRole) == code:
                        item.setSelected(True)
                        restored_count += 1
                        break

        print(f"✅ ByClassDialog updated ({restored_count} selections restored)")
        print("=" * 60 + "\n")

        if update_status:
            self.info_label.setText("Class definitions refreshed")
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage(
                    "✅ Convert Classes updated with latest PTC definitions",
                    2000
                )

    
    def perform_undo(self):
        """
        Perform CLASSIFICATION undo operation
        ✅ FIXED: Display-mode-aware — doesn't destroy shading with update_class_mode
        ✅ FIXED: undo_classification already handles full refresh for ALL modes
        """
        print("🔄 ByClassDialog: Performing CLASSIFICATION undo...")
        
        if hasattr(self.app, 'undo_classification'):
            try:
                # ✅ undo_classification already handles:
                #    - Reverting classification data
                #    - Display-mode-aware main view refresh (class/shaded/other)
                #    - Cross-section refresh
                #    - Cut section refresh
                #    - Point count update
                self.app.undo_classification()
                
                # ✅ FIX: Only do supplementary class refresh for CLASS mode
                # For shaded_class mode, undo_classification already rebuilt the shading
                # Calling update_class_mode would DESTROY the shading mesh!
                display_mode = getattr(self.app, 'display_mode', 'class')
                
                if display_mode == 'shaded_class':
                    print(f"   🌓 Shading mode — undo refresh already handled")
                    # ✅ Shading was already rebuilt by _force_main_view_refresh_after_undo
                    # Do NOT call update_class_mode here!
                    
                elif display_mode == 'class':
                    # ✅ Supplementary rebuild for class mode (safety net)
                    from gui.class_display import update_class_mode
                    update_class_mode(self.app, force_refresh=True) 
                    print(f"   ✅ Main view refreshed (class mode)")
                    
                else:
                    # Other modes (RGB, intensity, etc.)
                    print(f"   📊 {display_mode} mode — undo refresh already handled")

                # Refresh cross-sections (safety net — undo_classification also does this)
                if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                    for view_idx in list(self.app.section_vtks.keys()):
                        try:
                            if hasattr(self.app, '_refresh_single_section_view'):
                                self.app._refresh_single_section_view(view_idx)
                        except Exception as e:
                            print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

                # Update point count widget
                if hasattr(self.app, 'point_count_widget'):
                    self.app.point_count_widget.schedule_update()

                
                self.info_label.setText("↶ Undo performed")
                self.info_label.setStyleSheet("""
                    QLabel {
                        color: #ff9800;
                        font-size: 10px;
                        font-weight: bold;
                        padding: 6px;
                        background-color: #3e2723;
                        border-radius: 3px;
                    }
                """)
                print("✅ Classification undo performed from ByClassDialog")
            except Exception as e:
                print(f"❌ Classification undo failed: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.warning(self, "Undo Failed", f"Could not undo: {str(e)}")
        else:
            print("❌ No undo_classification method found on app")
            QMessageBox.warning(self, "Undo Not Available", 
                            "Classification undo functionality not found in application")

    def perform_redo(self):
        """
        Perform CLASSIFICATION redo operation
        ✅ FIXED: Display-mode-aware — doesn't destroy shading with update_class_mode
        """
        print("🔄 ByClassDialog: Performing CLASSIFICATION redo...")
        
        if hasattr(self.app, 'redo_classification'):
            try:
                self.app.redo_classification()
                
                # ✅ FIX: Display-mode-aware supplementary refresh
                display_mode = getattr(self.app, 'display_mode', 'class')
                
                if display_mode == 'shaded_class':
                    print(f"   🌓 Shading mode — redo refresh needs shading rebuild")
                    try:
                        # ✅ FIX: Save shading visibility BEFORE any palette restore
                        from gui.shading_display import get_cache, update_shaded_class, clear_shading_cache
                        cache = get_cache()
                        saved_vis = getattr(cache, 'visible_classes_set', None)
                        if saved_vis is not None:
                            saved_vis = saved_vis.copy()
                        else:
                            saved_vis = {
                                int(c) for c, e in self.app.class_palette.items()
                                if e.get("show", True)
                            }
                        
                        print(f"   📍 Preserved shading visibility: {sorted(saved_vis)}")
                        
                        # ✅ DON'T call _restore_main_view_palette_for_refresh() — 
                        #    it overrides single-class visibility with slot 0!
                        
                        # ✅ Force class_palette to match saved shading visibility
                        for c in self.app.class_palette:
                            self.app.class_palette[c]["show"] = (int(c) in saved_vis)
                        
                        clear_shading_cache("redo classification in shading mode")
                        update_shaded_class(
                            self.app,
                            getattr(self.app, "last_shade_azimuth", 45.0),
                            getattr(self.app, "last_shade_angle", 45.0),
                            getattr(self.app, "shade_ambient", 0.2),
                            force_rebuild=True
                        )
                        print(f"   ✅ Shading mesh rebuilt after redo "
                              f"({'single' if len(saved_vis) == 1 else 'multi'}-class preserved)")
                    except Exception as e:
                        print(f"   ⚠️ Shading rebuild failed, falling back to class mode: {e}")
                        from gui.class_display import update_class_mode
                        update_class_mode(self.app, force_refresh=True)
                        
                elif display_mode == 'class':
                    from gui.class_display import update_class_mode
                    update_class_mode(self.app, force_refresh=True)
                    print(f"   ✅ Main view refreshed (class mode)")
                    
                else:
                    print(f"   📊 {display_mode} mode — redo refresh already handled")

                # Refresh cross-sections if needed
                if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                    for view_idx in list(self.app.section_vtks.keys()):
                        try:
                            if hasattr(self.app, '_refresh_single_section_view'):
                                self.app._refresh_single_section_view(view_idx)
                        except Exception as e:
                            print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

                # Update point count widget
                if hasattr(self.app, 'point_count_widget'):
                    self.app.point_count_widget.schedule_update()

                
                self.info_label.setText("↷ Redo performed")
                self.info_label.setStyleSheet("""
                    QLabel {
                        color: #ff9800;
                        font-size: 10px;
                        font-weight: bold;
                        padding: 6px;
                        background-color: #3e2723;
                        border-radius: 3px;
                    }
                """)
                print("✅ Classification redo performed from ByClassDialog")
            except Exception as e:
                print(f"❌ Classification redo failed: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.warning(self, "Redo Failed", f"Could not redo: {str(e)}")
        else:
            print("❌ No redo_classification method found on app")
            QMessageBox.warning(self, "Redo Not Available", 
                            "Classification redo functionality not found in application")

    def init_ui(self):
        """Initialize the UI with modern spacing and styling names"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)  # Increased margins for a cleaner look
        layout.setSpacing(15)  # Increased spacing between elements
        
        # Section 1: From Class
        from_label = QLabel("From class (Ctrl+Click for multiple):")
        from_label.setObjectName("sectionLabel")
        layout.addWidget(from_label)
        
        self.from_list = QListWidget()
        self.from_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.from_list.setMinimumHeight(150)
        layout.addWidget(self.from_list)
        
        # Section 2: To Class
        to_label = QLabel("To class:")
        to_label.setObjectName("sectionLabel")
        layout.addWidget(to_label)
        
        self.to_combo = QComboBox()
        layout.addWidget(self.to_combo)
        
        # Info/Description area
        nearby_info = QLabel("Convert OTHER classes near 'From class' points")
        nearby_info.setObjectName("subText")
        nearby_info.setWordWrap(True)
        layout.addWidget(nearby_info)
                
        # Status Info label
        self.info_label = QLabel("Select classes and click Convert")
        self.info_label.setObjectName("statusLabel")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        
        # Primary Action Button
        self.convert_btn = QPushButton("🔄 Convert")
        self.convert_btn.setObjectName("primaryButton") # This matches the CSS below
        self.convert_btn.clicked.connect(self.perform_conversion)
        layout.addWidget(self.convert_btn)

    def populate_classes(self):
        """Populate with LEVEL and DESCRIPTION like ClassPicker"""
        print(f"\n🔄 Populating ByClassDialog...")
        
        self.from_list.clear()
        self.to_combo.clear()
        
        # Standard LAS classification levels
        STANDARD_LEVELS = {
            0: "Created", 1: "Ground", 2: "Low vegetation",
            3: "Medium vegetation", 4: "High vegetation", 5: "Buildings",
            6: "Water", 7: "Railways", 17: "Other Poles",
        }
        
        # Get classes from Display Mode
        class_list = []
        display_dialog = getattr(self.app, 'display_mode_dialog', 
                                 getattr(self.app, 'display_dialog', None))
        
        if display_dialog and hasattr(display_dialog, 'table'):
            table = display_dialog.table
            for row in range(table.rowCount()):
                try:
                    code_item = table.item(row, 1)
                    if not code_item:
                        continue
                    
                    code = int(code_item.text())
                    desc_item = table.item(row, 2)
                    desc = desc_item.text() if desc_item else ""
                    
                    lvl_item = table.item(row, 4)
                    lvl = lvl_item.text() if lvl_item else ""
                    
                    if not lvl or lvl.strip() == "":
                        lvl = STANDARD_LEVELS.get(code, str(code))
                    
                    color_item = table.item(row, 5)
                    if color_item:
                        qcolor = color_item.background().color()
                        color = (qcolor.red(), qcolor.green(), qcolor.blue())
                    else:
                        color = (128, 128, 128)
                    
                    class_list.append({
                        'code': code, 'desc': desc, 'lvl': lvl, 'color': color
                    })
                    
                except Exception as e:
                    continue
        
        # Fallback: Use app's class_palette
        if not class_list and hasattr(self.app, 'class_palette'):
            for code in sorted(self.app.class_palette.keys()):
                entry = self.app.class_palette[code]
                desc = entry.get("description", "")
                lvl = entry.get("lvl", "")
                
                if not lvl or lvl.strip() == "":
                    lvl = STANDARD_LEVELS.get(code, str(code))
                
                color = entry.get("color", (128, 128, 128))
                class_list.append({
                    'code': code, 'desc': desc, 'lvl': lvl, 'color': color
                })
        
        if not class_list:
            print("⚠️ No classes found")
            return
        
        class_list.sort(key=lambda x: x['code'])
        
        # Add "Any class" option
        any_item = QListWidgetItem("Any class")
        any_item.setData(Qt.UserRole, None)
        any_item.setBackground(QColor(240, 240, 240))
        self.from_list.addItem(any_item)
        
        # Populate lists
        for cls in class_list:
            code = cls['code']
            lvl = cls['lvl']
            desc = cls['desc']
            color = cls['color']
            
            text = f"{code} - {lvl}" if lvl and lvl.strip() else f"{code}"
            if desc:
                text += f" ({desc})"
            
            icon = make_color_icon(color)
            
            item = QListWidgetItem(icon, text)
            item.setData(Qt.UserRole, code)
            self.from_list.addItem(item)
            
            self.to_combo.addItem(icon, text, code)
        
        print(f"✅ Populated ByClassDialog with {len(class_list)} classes")
    
    def on_classes_changed(self):
        """Refresh class lists when Display Mode loads a different PTC."""
        self.refresh_class_lists(reason="PTC changed in Display Mode", update_status=True)
    
    def perform_conversion(self):
        """Perform the class conversion with visibility-aware refresh"""
        # Get selected From classes
        selected_items = self.from_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select at least one 'From' class")
            return
        
        # Check if "Any class" is selected
        any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
        
        if any_selected:
            from_classes = None  # Will convert ALL classes
        else:
            from_classes = [item.data(Qt.UserRole) for item in selected_items]
        
        # Get To class
        to_class = self.to_combo.currentData()
        if to_class is None:
            QMessageBox.warning(self, "No Target", "Please select a 'To' class")
            return
        
        # Confirm conversion
        if from_classes is None:
            msg = f"Convert ALL classes to class {to_class}?"
        elif len(from_classes) == 1:
            msg = f"Convert class {from_classes[0]} to class {to_class}?"
        else:
            msg = f"Convert classes {from_classes} to class {to_class}?"
        
        reply = QMessageBox.question(
            self, "Confirm Conversion", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Perform conversion
        try:
            classification = self.app.data.get("classification")
            if classification is None:
                QMessageBox.critical(self, "Error", "No classification data available")
                return
            
            # Create mask for points to convert
            if from_classes is None:
                mask = np.ones(len(classification), dtype=bool)
                converted_count = len(classification)
            else:
                mask = np.isin(classification, from_classes)
                converted_count = np.sum(mask)
            
            if converted_count == 0:
                QMessageBox.information(self, "No Points", "No points found to convert")
                return
            
            # Save undo
            old_classes = classification[mask].copy()
            new_classes = np.full(mask.sum(), to_class, dtype=classification.dtype)
            
            # ✅ FIX: Use BOTH key name variants for maximum compatibility
            undo_step = {
                "mask": mask.copy(),
                "oldclasses": old_classes,
                "old_classes": old_classes,
                "newclasses": new_classes,
                "new_classes": new_classes
            }
            
            # ✅ FIX: Correct stack attribute names (undostack, NOT undo_stack)
            if hasattr(self.app, 'undostack'):
                self.app.undostack.append(undo_step)
            elif hasattr(self.app, 'undo_stack'):
                self.app.undo_stack.append(undo_step)
            else:
                print("⚠️ No undo stack found on app!")
            
            if hasattr(self.app, 'redostack'):
                self.app.redostack.clear()
            elif hasattr(self.app, 'redo_stack'):
                self.app.redo_stack.clear()
            from gui.memory_manager import trim_undo_stack
            trim_undo_stack(self.app)

            # Apply conversion
            classification[mask] = to_class
            
            # ✅ Store conversion info for targeted refresh
            if from_classes:
                self._last_conversion_info = {
                    'from_classes': from_classes,
                    'to_class': to_class,
                    'count': converted_count
                }
            
            print(f"\n{'='*60}")
            print(f"✅ Converted {converted_count:,} points: {from_classes} → {to_class}")
            print(f"{'='*60}")

            display_mode = getattr(self.app, 'display_mode', 'class')
            print(f"   📍 Current display mode: {display_mode}")          
            
            if display_mode == "shaded_class":
                print(f"   🔺 Rebuilding SHADING mesh after classification...")
                
                # ✅ FIX: Save current shading visibility BEFORE any palette manipulation
                # This preserves single-class mode — don't let slot 0 override it!
                from gui.shading_display import get_cache, update_shaded_class, clear_shading_cache
                cache = get_cache()
                saved_shading_visibility = getattr(cache, 'visible_classes_set', None)
                
                if saved_shading_visibility is None:
                    # Fallback: use current class_palette (before any restore overwrites it)
                    saved_shading_visibility = {
                        int(c) for c, e in self.app.class_palette.items()
                        if e.get("show", True)
                    }
                
                saved_shading_visibility = saved_shading_visibility.copy()
                is_single = len(saved_shading_visibility) == 1
                print(f"   📍 Saved shading visibility: {sorted(saved_shading_visibility)} "
                      f"({'single-class' if is_single else 'multi-class'})")
                
                # ✅ DON'T call _restore_main_view_palette_for_refresh() — 
                #    it would override single-class visibility with slot 0 (all 26 classes)!
                
                # ✅ Force class_palette to match SAVED shading visibility (not slot 0!)
                for c in self.app.class_palette:
                    self.app.class_palette[c]["show"] = (int(c) in saved_shading_visibility)
                
                # Debug: show what will be visible after conversion
                visible_with_points = []
                for c, e in sorted(self.app.class_palette.items()):
                    if e.get("show", True):
                        pts = np.sum(classification == c)
                        if pts > 0:
                            visible_with_points.append(c)
                            print(f"      Class {c}: VISIBLE, {pts:,} points")
                
                if not visible_with_points:
                    print(f"   ⚠️ No visible classes have points after conversion")
                    print(f"      (All points moved to hidden class {to_class})")
                    print(f"      View will be empty — user can switch visibility")
                
                clear_shading_cache("class conversion changed visible point set")
                update_shaded_class(
                    self.app,
                    getattr(self.app, "last_shade_azimuth", 45.0),
                    getattr(self.app, "last_shade_angle", 45.0),
                    getattr(self.app, "shade_ambient", 0.2),
                    force_rebuild=True
                )
                print(f"   ✅ Shaded mesh rebuilt (visibility preserved: "
                      f"{'single' if is_single else 'multi'}-class)")
                
            elif display_mode == "class":
                # Standard class-colored point actors
                print(f"   🎨 Refreshing CLASS mode...")
                from gui.class_display import update_class_mode
                update_class_mode(self.app, force_refresh=True)
                print(f"   ✅ Class mode refreshed")
                
            else:
                # Other display modes (RGB, intensity, elevation, etc.)
                print(f"   🌈 Refreshing {display_mode.upper()} mode...")
                from gui.pointcloud_display import update_pointcloud
                update_pointcloud(self.app, display_mode)
                print(f"   ✅ {display_mode} mode refreshed")

            # Refresh cross-sections if needed
            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in list(self.app.section_vtks.keys()):
                    try:
                        if hasattr(self.app, '_refresh_single_section_view'):
                            self.app._refresh_single_section_view(view_idx)
                    except Exception as e:
                        print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

            # Refresh Cut Section view if active
            try:
                ctrl = getattr(self.app, 'cut_section_controller', None)
                if ctrl and getattr(ctrl, 'is_cut_view_active', False):
                    if hasattr(ctrl, '_refresh_cut_colors_fast'):
                            ctrl._refresh_cut_colors_fast()
            except Exception as e:
                print(f"   ⚠️ Cut Section refresh failed: {e}")

            # Update point count widget
            if hasattr(self.app, 'point_count_widget'):
                self.app.point_count_widget.schedule_update()

            
            # Update UI
            if self.ribbon_parent:
                self.ribbon_parent.update_status(
                    f"✅ Converted {converted_count:,} points to class {to_class}", 
                    "success"
                )
            
            self.info_label.setText(f"✅ Converted {converted_count:,} points")
            self.info_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 6px;
                    background-color: #1b5e20;
                    border-radius: 3px;
                }
            """)
            
            QMessageBox.information(
                self, "Conversion Complete",
                f"Successfully converted {converted_count:,} points to class {to_class}"
            )
            
        except Exception as e:
            error_msg = f"Conversion failed: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()


    # ========================================
    # ✅ VISIBILITY-AWARE REFRESH METHODS
    # ========================================
    
    def _refresh_all_views(self):
        """
        ✅ FIXED: Handle both unified and by-class actor modes
        For by-class mode: rebuild affected actors
        For unified mode: update colors only
        COPIED FROM WORKING FENCE DIALOG - NO MORE BLANK SCREENS!
        """
        print(f"\n🔄 REFRESHING VIEWS (partial + visibility-aware)...")
        
        # ✅ CRITICAL: Save camera position BEFORE any updates
        saved_camera = None
        if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget.renderer:
            try:
                camera = self.app.vtk_widget.renderer.GetActiveCamera()
                if camera:
                    saved_camera = {
                        'position': tuple(camera.GetPosition()),
                        'focal_point': tuple(camera.GetFocalPoint()),
                        'view_up': tuple(camera.GetViewUp()),
                        'parallel_scale': camera.GetParallelScale(),
                        'parallel_projection': camera.GetParallelProjection(),
                    }
                    print(f"   📷 Camera saved: pos={saved_camera['position'][:2]}, scale={saved_camera['parallel_scale']:.2f}")
            except Exception as e:
                print(f"   ⚠️ Camera save failed: {e}")
        
        # ✅ DETECT MODE: By-class actors or unified actor?
        has_by_class_actors = False
        if hasattr(self.app, 'vtk_widget') and hasattr(self.app.vtk_widget, 'actors'):
            if isinstance(self.app.vtk_widget.actors, dict):
                for key in self.app.vtk_widget.actors.keys():
                    if 'class_' in str(key).lower():
                        has_by_class_actors = True
                        break
        
        update_success = False
        
        if has_by_class_actors:
            print(f"   🔍 Detected BY-CLASS actor mode - rebuilding affected actors...")
            
            # For by-class mode, we need to rebuild the actors
            # This requires calling the display mode's refresh method
            try:
                # Try to find and call the display mode's update method
                display_dialog = getattr(self.app, 'display_mode_dialog', 
                                        getattr(self.app, 'display_dialog', None))
                
                if display_dialog:
                    # Method 1: Try update_display_mode or similar
                    if hasattr(display_dialog, 'update_display_mode'):
                        display_dialog.update_display_mode()
                        print(f"   ✅ Called display_dialog.update_display_mode()")
                        update_success = True
                    
                    # Method 2: Try refresh_actors or rebuild_actors
                    elif hasattr(display_dialog, 'refresh_actors'):
                        display_dialog.refresh_actors()
                        print(f"   ✅ Called display_dialog.refresh_actors()")
                        update_success = True
                    
                    # Method 3: Try apply_class_filter or similar
                    elif hasattr(display_dialog, 'apply_class_filter'):
                        display_dialog.apply_class_filter()
                        print(f"   ✅ Called display_dialog.apply_class_filter()")
                        update_success = True
                    
                    # Method 4: Simulate clicking the apply/update button
                    elif hasattr(display_dialog, 'apply_btn'):
                        display_dialog.apply_btn.click()
                        print(f"   ✅ Triggered display_dialog.apply_btn.click()")
                        update_success = True
            
            except Exception as e:
                print(f"   ⚠️ Display mode refresh failed: {e}")
        
        # ✅ UNIFIED ACTOR MODE: Try smart update or direct VTK update
        if not update_success:
            print(f"   🔍 Using unified actor mode - updating colors...")
            
            # Try smart_update_colors
            try:
                from gui.pointcloud_display import smart_update_colors
                smart_update_colors(self.app, None)
                print(f"   ✅ Main view updated (smart_update_colors)")
                update_success = True
            except ImportError:
                print(f"   ⚠️ smart_update_colors not found - trying direct VTK update")
            except Exception as e:
                print(f"   ⚠️ smart_update_colors failed: {e}")
            
            # Try direct VTK color update
            if not update_success:
                update_success = self._force_vtk_color_update()
                if update_success:
                    print(f"   ✅ Main view updated (direct VTK with visibility)")
        
        # ✅ FALLBACK: Old method
        if not update_success:
            print(f"   ⚠️ All methods failed - using fallback (full refresh)")
            from gui.class_display import update_class_mode
            update_class_mode(self.app, force_refresh=True)
            print(f"   ✅ Main view refreshed (forced rebuild)")
            update_success = True
        
        # ✅ CRITICAL: Restore camera position IMMEDIATELY
        if saved_camera:
            try:
                camera = self.app.vtk_widget.renderer.GetActiveCamera()
                camera.SetPosition(saved_camera['position'])
                camera.SetFocalPoint(saved_camera['focal_point'])
                camera.SetViewUp(saved_camera['view_up'])
                camera.SetParallelScale(saved_camera['parallel_scale'])
                
                if saved_camera['parallel_projection']:
                    camera.ParallelProjectionOn()
                else:
                    camera.ParallelProjectionOff()
                
                self.app.vtk_widget.renderer.ResetCameraClippingRange()
                print(f"   📷✅ Camera restored")
            except Exception as e:
                print(f"   ⚠️ Camera restore failed: {e}")
        
        # Refresh cross-sections
        if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
            for view_idx in list(self.app.section_vtks.keys()):
                try:
                    if hasattr(self.app, '_refresh_single_section_view'):
                        self.app._refresh_single_section_view(view_idx)
                except Exception as e:
                    print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")
        
        # Update point statistics
        if hasattr(self.app, 'point_count_widget'):
            try:
                self.app.point_count_widget.schedule_update()
            except Exception:
                pass
        
        # ✅ Force final render
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass
        
        mode_str = "by-class" if has_by_class_actors else "unified"
        print(f"✅ REFRESH COMPLETE ({mode_str} mode, visibility-aware: {update_success})\n")


    def _force_vtk_color_update(self):
        """
        Direct VTK color update with visibility awareness
        Called when smart_update_colors is not available
        """
        try:
            if not hasattr(self.app, 'vtk_widget'):
                return False
            
            vtk_widget = self.app.vtk_widget
            
            # Get the actor (unified mode)
            actor = None
            if hasattr(vtk_widget, 'actor') and vtk_widget.actor:
                actor = vtk_widget.actor
            elif hasattr(vtk_widget, 'actors') and isinstance(vtk_widget.actors, dict):
                # Try to find a unified actor
                for key, act in vtk_widget.actors.items():
                    if 'unified' in str(key).lower() or key == 'main':
                        actor = act
                        break
            
            if not actor:
                print(f"      ⚠️ No unified actor found for direct VTK update")
                return False
            
            # Get mapper and update colors
            mapper = actor.GetMapper()
            if not mapper:
                return False
            
            # Get classification data
            classification = self.app.data.get("classification")
            if classification is None:
                return False
            
            # Get visibility mask if available
            visible_mask = None
            if hasattr(self.app, 'get_visible_points_mask'):
                visible_mask = self.app.get_visible_points_mask()
            
            # Update colors based on classification
            from vtk import vtkUnsignedCharArray
            colors = vtkUnsignedCharArray()
            colors.SetNumberOfComponents(3)
            colors.SetName("Colors")
            
            class_palette = getattr(self.app, 'class_palette', {})
            
            for i, cls in enumerate(classification):
                # Check visibility
                if visible_mask is not None and not visible_mask[i]:
                    # Make invisible points black or very dark
                    colors.InsertNextTuple3(20, 20, 20)
                else:
                    # Use class color
                    color_entry = class_palette.get(int(cls), {'color': (128, 128, 128)})
                    color = color_entry.get('color', (128, 128, 128))
                    colors.InsertNextTuple3(int(color[0]), int(color[1]), int(color[2]))
            
            # Update the polydata
            polydata = mapper.GetInput()
            if polydata:
                polydata.GetPointData().SetScalars(colors)
                polydata.Modified()
                mapper.Modified()
                actor.Modified()
            
            print(f"      ✅ Direct VTK color update complete")
            return True
            
        except Exception as e:
            print(f"      ❌ Direct VTK update failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _save_camera_state(self):
        """Save camera state"""
        if not hasattr(self.app, 'vtk_widget'):
            return None
        if not hasattr(self.app.vtk_widget, 'renderer'):
            return None
        
        try:
            camera = self.app.vtk_widget.renderer.GetActiveCamera()
            if camera:
                return {
                    'position': tuple(camera.GetPosition()),
                    'focal_point': tuple(camera.GetFocalPoint()),
                    'view_up': tuple(camera.GetViewUp()),
                    'parallel_scale': camera.GetParallelScale(),
                    'parallel_projection': camera.GetParallelProjection(),
                }
        except Exception:
            pass
        return None
    
    def _restore_camera_state(self, saved_camera):
        """Restore camera state"""
        if not saved_camera:
            return
        
        try:
            camera = self.app.vtk_widget.renderer.GetActiveCamera()
            camera.SetPosition(saved_camera['position'])
            camera.SetFocalPoint(saved_camera['focal_point'])
            camera.SetViewUp(saved_camera['view_up'])
            camera.SetParallelScale(saved_camera['parallel_scale'])
            
            if saved_camera['parallel_projection']:
                camera.ParallelProjectionOn()
            else:
                camera.ParallelProjectionOff()
            
            self.app.vtk_widget.renderer.ResetCameraClippingRange()
        except Exception:
            pass
    
    def _detect_by_class_mode(self):
        """Detect if using by-class actors"""
        if not hasattr(self.app, 'vtk_widget'):
            return False
        if not hasattr(self.app.vtk_widget, 'actors'):
            return False
        
        actors = self.app.vtk_widget.actors
        if isinstance(actors, dict):
            for key in actors.keys():
                if 'class_' in str(key).lower():
                    return True
        return False

    def naksha_dark_theme(self):
        return """
        QWidget {
            background-color: #0a0a0a; /* Deep black background like Pic 2 */
            color: #e0e0e0;
            font-family: "Segoe UI", sans-serif;
            font-size: 10pt;
        }

        /* Section Titles (Teal color from Pic 2) */
        QLabel#sectionLabel {
            color: #1abc9c;
            font-weight: bold;
            font-size: 11pt;
            margin-bottom: 2px;
        }

        /* Smaller italic text */
        QLabel#subText {
            color: #7f8c8d;
            font-size: 9pt;
            font-style: italic;
        }

        /* Gray status label */
        QLabel#statusLabel {
            color: #bdc3c7;
            background-color: #151515;
            padding: 10px;
            border-radius: 6px;
            font-size: 9pt;
        }

        /* Lists and Boxes */
        QListWidget, QComboBox {
            background-color: #151515;
            border: 1px solid #2a2a2a;
            border-radius: 6px;
            padding: 8px;
            color: #ffffff !important;
        }

        QListWidget::item {
            padding: 5px;
            border-radius: 4px;
        }

        QListWidget::item:selected {
            background-color: #1abc9c; /* Teal selection */
            color: #000000;
        }

        /* Main Teal Button */
        QPushButton#primaryButton {
            background-color: #1abc9c;
            color: #0a0a0a;
            font-size: 11pt;
            font-weight: bold;
            padding: 12px;
            border: none;
            border-radius: 8px;
        }

        QPushButton#primaryButton:hover {
            background-color: #16a085;
        }

        QPushButton#primaryButton:pressed {
            background-color: #12876f;
        }

        /* Scrollbar styling to match dark theme */
        QScrollBar:vertical {
            border: none;
            background: #0a0a0a;
            width: 10px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #333;
            min-height: 20px;
            border-radius: 5px;
        }
        """


def make_color_icon(rgb):
    """Create a color icon from RGB tuple"""
    pix = QPixmap(20, 12)
    pix.fill(QColor(*rgb))
    return QIcon(pix)

import numpy as np
from scipy.spatial import cKDTree
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                               QListWidget, QComboBox, QPushButton, 
                               QDoubleSpinBox, QCheckBox, QMessageBox, QListWidgetItem)
from PySide6.QtCore import Qt, Signal, QEvent  # ✅ Added QEvent
from PySide6.QtGui import QPixmap, QColor, QIcon


class ClosedByClassDialog(QDialog):
    """
    Proximity-Based Class Conversion Dialog
    
    🔗 CLUSTERING MODE:
    Converts "From class" points that are near "To class" points
    
    Workflow:
    1. Load cross-section (points are automatically captured)
    2. Select "From class" (points to convert) - SUPPORTS MULTI-SELECT
    3. Select "To class" (reference points)
    4. Set radius (meters)
    5. Optional: Filter by specific class in radius
    6. Click Convert → From class points within radius of To class → become To class
    
    Example:
    - From: Ground (class 1) + Low vegetation (class 2)
    - To: Building (class 5)
    - Radius: 1m
    → Ground & Low veg points within 1m of Building points → become Building
    
    ✅ NEW: Supports undo/redo with Ctrl+Z/Ctrl+Y
    ✅ NEW: Visibility-aware refresh (respects Display Mode checkboxes)
    """
    
    selection_required = Signal()
   

    def __init__(self, app, ribbon_parent):
        # ✅ FIX 1: Robust Parent Finding
        from PySide6.QtWidgets import QWidget
        target_parent = None
        if isinstance(app, QWidget):
            target_parent = app
        elif hasattr(app, 'window') and isinstance(app.window, QWidget):
            target_parent = app.window

        super().__init__(None, Qt.Window)
        
        self.setAttribute(Qt.WA_NativeWindow, True)  # Fix: GetDC invalid window handle

        self.setWindowModality(Qt.NonModal)
        self.app = app
        self.ribbon_parent = ribbon_parent
        self.manual_selection_indices = None
        
        self.setWindowTitle("Closed By Class Conversion")
        # self.setStyleSheet(self.naksha_dark_theme()) # Inherits global theme
        self.setGeometry(200, 200, 450, 650)
        
        # Shortcuts - same approach as ByClassDialog
       
        
        self.init_ui()
        self.populate_classes()

        # Display mode connection...
        display_dialog = getattr(self.app, 'display_mode_dialog', getattr(self.app, 'display_dialog', None))
        if display_dialog:
            try:
                display_dialog.classes_loaded.connect(self.on_classes_changed)
            except Exception: pass
    
    
    def perform_undo(self):
        """Perform CLASSIFICATION undo"""
        print("🔄 ClosedByClassDialog: Performing CLASSIFICATION undo...")
        
        if hasattr(self.app, 'undo_classification'):
            try:
                self.app.undo_classification()
                
                # ✅ CRITICAL: Respect current display mode (FIXED)
                display_mode = getattr(self.app, 'display_mode', 'class')
                print(f"   📍 Current display mode: {display_mode}")
                
                if display_mode == "shaded_class":
                    # Maintain shaded mesh visualization
                    print(f"   🔺 Maintaining SHADING mode...")
                    from gui.shading_display import update_shaded_class
                    update_shaded_class(
                        self.app,
                        getattr(self.app, "last_shade_azimuth", 45.0),
                        getattr(self.app, "last_shade_angle", 45.0),
                        getattr(self.app, "shade_ambient", 0.2),
                        force_rebuild=False
                    )
                    print(f"   ✅ Shaded mesh maintained after undo")
                    
                elif display_mode == "class":
                    # Standard class-colored point actors
                    print(f"   🎨 Refreshing CLASS mode...")
                    from gui.class_display import update_class_mode
                    update_class_mode(self.app, force_refresh=True)
                    print(f"   ✅ Class mode refreshed")
                    
                else:
                    # Other display modes
                    print(f"   🌈 Refreshing {display_mode.upper()} mode...")
                    from gui.pointcloud_display import update_pointcloud
                    update_pointcloud(self.app, display_mode)
                    print(f"   ✅ {display_mode} mode refreshed")

                # Refresh cross-sections if needed
                if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                    for view_idx in list(self.app.section_vtks.keys()):
                        try:
                            if hasattr(self.app, '_refresh_single_section_view'):
                                self.app._refresh_single_section_view(view_idx)
                        except Exception as e:
                            print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

                # Refresh Cut Section view if active
                try:
                    ctrl = getattr(self.app, 'cut_section_controller', None)
                    if ctrl and getattr(ctrl, 'is_cut_view_active', False):
                        if hasattr(ctrl, '_refresh_cut_colors_fast'):
                                ctrl._refresh_cut_colors_fast()
                except Exception as e:
                    print(f"   ⚠️ Cut Section refresh failed: {e}")

                # Update point count widget
                if hasattr(self.app, 'point_count_widget'):
                    self.app.point_count_widget.schedule_update()

                
                self.preview_label.setText("↶ Undo performed")
                
                self.preview_label.setStyleSheet("""
                    QLabel {
                        color: #ff9800;
                        font-size: 10px;
                        font-weight: bold;
                        padding: 8px;
                        background-color: #3e2723;
                        border-radius: 3px;
                    }
                """)
                print("✅ Classification undo performed from ClosedByClassDialog")
            except Exception as e:
                print(f"❌ Undo failed: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.warning(self, "Undo Failed", f"Could not undo: {str(e)}")
        else:
            QMessageBox.warning(self, "Undo Not Available", 
                               "Classification undo functionality not found")
    
    def perform_redo(self):
        """Perform CLASSIFICATION redo"""
        print("🔄 ClosedByClassDialog: Performing CLASSIFICATION redo...")
        
        if hasattr(self.app, 'redo_classification'):
            try:
                self.app.redo_classification()
                
                # ✅ CRITICAL: Respect current display mode (FIXED)
                display_mode = getattr(self.app, 'display_mode', 'class')
                print(f"   📍 Current display mode: {display_mode}")
                
                if display_mode == "shaded_class":
                    # Maintain shaded mesh visualization
                    print(f"   🔺 Maintaining SHADING mode...")
                    from gui.shading_display import update_shaded_class
                    update_shaded_class(
                        self.app,
                        getattr(self.app, "last_shade_azimuth", 45.0),
                        getattr(self.app, "last_shade_angle", 45.0),
                        getattr(self.app, "shade_ambient", 0.2),
                        force_rebuild=False
                    )
                    print(f"   ✅ Shaded mesh maintained after redo")
                    
                elif display_mode == "class":
                    # Standard class-colored point actors
                    print(f"   🎨 Refreshing CLASS mode...")
                    from gui.class_display import update_class_mode
                    update_class_mode(self.app, force_refresh=True)
                    print(f"   ✅ Class mode refreshed")
                    
                else:
                    # Other display modes
                    print(f"   🌈 Refreshing {display_mode.upper()} mode...")
                    from gui.pointcloud_display import update_pointcloud
                    update_pointcloud(self.app, display_mode)
                    print(f"   ✅ {display_mode} mode refreshed")

                # Refresh cross-sections if needed
                if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                    for view_idx in list(self.app.section_vtks.keys()):
                        try:
                            if hasattr(self.app, '_refresh_single_section_view'):
                                self.app._refresh_single_section_view(view_idx)
                        except Exception as e:
                            print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

                # Refresh Cut Section view if active
                try:
                    ctrl = getattr(self.app, 'cut_section_controller', None)
                    if ctrl and getattr(ctrl, 'is_cut_view_active', False):
                        if hasattr(ctrl, '_refresh_cut_colors_fast'):
                                ctrl._refresh_cut_colors_fast()
                except Exception as e:
                    print(f"   ⚠️ Cut Section refresh failed: {e}")

                # Update point count widget
                if hasattr(self.app, 'point_count_widget'):
                    self.app.point_count_widget.schedule_update()

                
                self.preview_label.setText("↷ Redo performed")
                self.preview_label.setStyleSheet("""
                    QLabel {
                        color: #ff9800;
                        font-size: 10px;
                        font-weight: bold;
                        padding: 8px;
                        background-color: #3e2723;
                        border-radius: 3px;
                    }
                """)
                print("✅ Classification redo performed from ClosedByClassDialog")
            except Exception as e:
                print(f"❌ Redo failed: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.warning(self, "Redo Failed", f"Could not redo: {str(e)}")
        else:
            QMessageBox.warning(self, "Redo Not Available", 
                               "Classification redo functionality not found")
    
    def init_ui(self):
            """Initialize the UI"""
            layout = QVBoxLayout(self)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(10)
            
            # Info banner - Keep as is or remove to save space
            self.info_banner = QLabel("🔗 Convert From class points near To class points")
            self.info_banner.setObjectName("info_banner")
            self.info_banner.setStyleSheet("""
                QLabel {
                    font-size: 11px;
                    font-weight: bold;
                    color: #ffffff;
                    padding: 6px;
                    background-color: #333333; /* Darker to match brush UI */
                    border-radius: 4px;
                }
            """)
            self.info_banner.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.info_banner)
            
            # Step 2: Class selection
            class_label = QLabel("📋 SELECT CLASSES")
            class_label.setObjectName("header_label") # ADDED: This makes it Teal (#00c8aa)
            layout.addWidget(class_label)
            
            from_label = QLabel("From class (Ctrl+Click for multiple):")
            from_label.setStyleSheet("color: #aaaaaa; font-size: 10px;")
            layout.addWidget(from_label)

            self.from_list = QListWidget()
            self.from_list.setSelectionMode(QListWidget.ExtendedSelection)
            self.from_list.setMinimumHeight(150) # INCREASED: better visibility
            self.from_list.itemSelectionChanged.connect(self.on_from_selection_changed)
            layout.addWidget(self.from_list)

            self.from_selection_label = QLabel("No classes selected")
            self.from_selection_label.setStyleSheet("color: #888888; font-size: 9px; font-style: italic;")
            self.from_selection_label.setWordWrap(True)
            layout.addWidget(self.from_selection_label)
            
            to_label = QLabel("To class (reference points):")
            to_label.setStyleSheet("color: #aaaaaa; font-size: 10px; margin-top: 8px;")
            layout.addWidget(to_label)
            self.to_combo = QComboBox()
            self.to_combo.currentIndexChanged.connect(self.on_class_selection_changed)
            layout.addWidget(self.to_combo)
            
            separator2 = QLabel()
            separator2.setFixedHeight(1)
            separator2.setStyleSheet("background-color: #333333;")
            layout.addWidget(separator2)
            
            # Step 3: Radius
            radius_label = QLabel("📏 SET RADIUS")
            radius_label.setObjectName("header_label") # ADDED: Makes it Teal
            layout.addWidget(radius_label)
            
            analyze_btn = QPushButton("🔍 Analyze Distances")
            # Inline style updated to match the darker/subtle brush style
            analyze_btn.setStyleSheet("background-color: #333333; color: #00c8aa; font-weight: bold;")
            analyze_btn.clicked.connect(self.analyze_distances)
            layout.addWidget(analyze_btn)
            
            self.radius_combo = QComboBox()
            self.radius_combo.addItem("Select classes and click Analyze first", None)
            self.radius_combo.currentIndexChanged.connect(self.on_radius_combo_changed)
            layout.addWidget(self.radius_combo)
            
            radius_manual_row = QHBoxLayout()
            radius_manual_row.addWidget(QLabel("Manual entry:"))
            self.radius_spin = QDoubleSpinBox()
            self.radius_spin.setRange(0.1, 100.0)
            self.radius_spin.setValue(1.0)
            self.radius_spin.setSuffix(" m")
            radius_manual_row.addWidget(self.radius_spin)
            layout.addLayout(radius_manual_row)
            
            # Step 4: Optional filter
            filter_label = QLabel("🔧 OPTIONAL FILTER")
            filter_label.setObjectName("header_label") # ADDED: Makes it Teal
            layout.addWidget(filter_label)
            
            self.filter_checkbox = QCheckBox("Only convert if specific class exists in radius")
            self.filter_checkbox.toggled.connect(self.on_filter_toggled)
            layout.addWidget(self.filter_checkbox)
            
            self.filter_combo = QComboBox()
            self.filter_combo.setEnabled(False)
            layout.addWidget(self.filter_combo)
            
            # ✅ ADD MISSING LABELS
            # Distance info label (shown after analyze)
            self.distance_info_label = QLabel("")
            self.distance_info_label.setStyleSheet("color: #888888; font-size: 9px; font-style: italic;")
            self.distance_info_label.setWordWrap(True)
            layout.addWidget(self.distance_info_label)
            
            # Action buttons
            button_row = QHBoxLayout()
            
            
            convert_btn = QPushButton("🔄 Convert")
            convert_btn.setObjectName("primary_btn") # ADDED: This makes the button solid Teal
            convert_btn.clicked.connect(self.perform_conversion)
            button_row.addWidget(convert_btn)
            
            layout.addLayout(button_row)
            
            # ✅ Preview/status label (shown after conversion)
            self.preview_label = QLabel("")
            self.preview_label.setStyleSheet("color: #888888; font-size: 9px; font-style: italic;")
            self.preview_label.setWordWrap(True)
            layout.addWidget(self.preview_label)
            
            
        
    def populate_classes(self):
        """Populate class lists from Display Mode"""
        print(f"\n🔄 Populating ClosedByClassDialog...")
        
        self.from_list.clear()
        self.to_combo.clear()
        self.filter_combo.clear()
        
        # Standard class labels
        STANDARD_LEVELS = {
            0: "Created", 1: "Ground", 2: "Low vegetation",
            3: "Medium vegetation", 4: "High vegetation", 5: "Buildings",
            6: "Water", 7: "Railways", 8: "Railways (structure)",
            9: "Type 1 Street", 10: "Type 2 Street", 11: "Type 3 Street",
            12: "Type 4 Street", 13: "Bridge", 14: "Bare Conductors",
            15: "Elicord Overhead Cables", 16: "Pylons or Poles",
            17: "HV Overhead Lines", 18: "MV Overhead Lines",
            19: "LV Overhead Lines",
        }
        
        # Get classes from Display Mode
        class_list = []
        display_dialog = getattr(self.app, 'display_mode_dialog', getattr(self.app, 'display_dialog', None))
        
        if display_dialog and hasattr(display_dialog, 'table'):
            table = display_dialog.table
            for row in range(table.rowCount()):
                try:
                    code_item = table.item(row, 1)
                    if not code_item:
                        continue
                    
                    code = int(code_item.text())
                    desc_item = table.item(row, 2)
                    desc = desc_item.text() if desc_item else ""
                    
                    lvl_item = table.item(row, 4)
                    lvl = lvl_item.text() if lvl_item else ""
                    
                    if not lvl or lvl.strip() == "":
                        lvl = STANDARD_LEVELS.get(code, str(code))
                    
                    color_item = table.item(row, 5)
                    if color_item:
                        qcolor = color_item.background().color()
                        color = (qcolor.red(), qcolor.green(), qcolor.blue())
                    else:
                        color = (128, 128, 128)
                    
                    class_list.append({
                        'code': code, 'desc': desc, 'lvl': lvl, 'color': color
                    })
                except Exception as e:
                    continue
        
        # Fallback: Use app's class_palette
        if not class_list and hasattr(self.app, 'class_palette'):
            for code in sorted(self.app.class_palette.keys()):
                entry = self.app.class_palette[code]
                desc = entry.get("description", "")
                lvl = entry.get("lvl", "")
                
                if not lvl or lvl.strip() == "":
                    lvl = STANDARD_LEVELS.get(code, str(code))
                
                color = entry.get("color", (128, 128, 128))
                
                class_list.append({
                    'code': code, 'desc': desc, 'lvl': lvl, 'color': color
                })
        
        if not class_list:
            print("⚠️ No classes found")
            return
        
        class_list.sort(key=lambda x: x['code'])
        
        # ✅ ADD "Any class" option FIRST to From list
        any_item = QListWidgetItem("🌐 Any class (convert all points)")
        any_item.setData(Qt.UserRole, None)  # None = Any class
        any_item.setBackground(QColor(70, 130, 180))  # Steel blue
        any_item.setForeground(QColor(255, 255, 255))  # White text
        self.from_list.addItem(any_item)
        
        # Populate all combos with actual classes
        for cls in class_list:
            code = cls['code']
            lvl = cls['lvl']
            desc = cls['desc']
            color = cls['color']
            
            text = f"{code} - {lvl}" if lvl and lvl.strip() else f"{code}"
            if desc:
                text += f" ({desc})"
            
            icon = make_color_icon(color)
            
            # Add to From list (multi-select)
            item = QListWidgetItem(icon, text)
            item.setData(Qt.UserRole, code)
            self.from_list.addItem(item)
            
            # Add to To combo
            self.to_combo.addItem(icon, text, code)
            self.filter_combo.addItem(icon, text, code)
        
        print(f"✅ Populated ClosedByClassDialog with {len(class_list)} classes + 'Any class' option")
    
    def on_classes_changed(self):
        """Called when Display Mode loads new PTC file - preserves selections"""
        print("\n" + "="*60)
        print("🔄 CLOSED BY CLASS DIALOG: Detected PTC change from Display Mode")
        print("="*60)
        
        # Save current selections
        selected_items = self.from_list.selectedItems()
        old_from_codes = [item.data(Qt.UserRole) for item in selected_items]
        old_to = self.to_combo.currentData()
        old_filter = self.filter_combo.currentData()
        
        print(f"   📋 Saving selections:")
        print(f"      From: {old_from_codes}")
        print(f"      To: {old_to}")
        print(f"      Filter: {old_filter}")
        
        # Rebuild lists with new class definitions
        self.populate_classes()
        
        # ✅ Restore previous selections
        restored_count = 0
        
        # Restore From list selections (multi-select)
        for i in range(self.from_list.count()):
            item = self.from_list.item(i)
            code = item.data(Qt.UserRole)
            if code in old_from_codes:
                item.setSelected(True)
                restored_count += 1
                print(f"      ✅ Restored From: Class {code}")
        
        # Restore To combo
        if old_to is not None:
            idx = self.to_combo.findData(old_to)
            if idx >= 0:
                self.to_combo.setCurrentIndex(idx)
                print(f"      ✅ Restored To: Class {old_to}")
                restored_count += 1
        
        # Restore Filter combo
        if old_filter is not None:
            idx = self.filter_combo.findData(old_filter)
            if idx >= 0:
                self.filter_combo.setCurrentIndex(idx)
                print(f"      ✅ Restored Filter: Class {old_filter}")
                restored_count += 1
        
        print(f"✅ ClosedByClassDialog updated ({restored_count} selections restored)")
        print("="*60 + "\n")
        
        # Show user feedback
        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                "✅ Close By Class updated with new definitions",
                2000
            )
    
    def on_filter_toggled(self, checked):
        """Enable/disable filter class combo"""
        self.filter_combo.setEnabled(checked)
    
    def preview_conversion(self):
        """Preview which points would be converted"""
        # Get selected From classes (multi-select)
        selected_items = self.from_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select at least one From class")
            return
        
        # Check if "Any class" is selected
        any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
        
        if any_selected:
            from_classes = None  # Convert ALL classes
            from_display = "All classes"
        else:
            from_classes = [item.data(Qt.UserRole) for item in selected_items]
            from_display = ", ".join(str(c) for c in from_classes)
        
        to_class = self.to_combo.currentData()
        radius = self.radius_spin.value()
        
        if to_class is None:
            QMessageBox.warning(self, "No Selection", "Please select To class")
            return
        
        # Don't allow converting TO class to itself
        if from_classes and to_class in from_classes:
            QMessageBox.warning(self, "Invalid Selection", f"Cannot convert class {to_class} to itself")
            return
        
        # Calculate
        try:
            affected_count = self._calculate_conversion(
                from_classes, to_class, radius, preview=True
            )
            
            if affected_count is None:
                return
            
            self.preview_label.setText(
                f"📊 Preview: {affected_count:,} points would be converted\n"
                f"(From: {from_display} within {radius}m of Class {to_class})"
            )
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #2196f3;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 8px;
                    background-color: #1a237e;
                    border-radius: 3px;
                }
            """)
            
        except Exception as e:
            print(f"❌ Preview failed: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Preview Failed", str(e))
    
    def perform_conversion(self):
        """Perform the conversion"""
        
        if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
            active_sections = [k for k, v in self.app.section_vtks.items() if v is not None]
            if active_sections:
                reply = QMessageBox.question(
                    self, 
                    "Active Cross-Section", 
                    "There are active cross-section views. Converting classes will affect "
                    "the entire dataset, not just the cross-section.\n\n"
                    "Close cross-sections first?",
                    QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.Cancel:
                    return
                elif reply == QMessageBox.Yes:
                    # Close all cross-sections
                    if hasattr(self.app, 'close_all_sections'):
                        self.app.close_all_sections()
        
        # Get selected From classes (multi-select)
        selected_items = self.from_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select at least one From class")
            return
        
        # Check if "Any class" is selected
        any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
        
        if any_selected:
            from_classes = None  # Convert ALL classes
            from_display = "All classes"
        else:
            from_classes = [item.data(Qt.UserRole) for item in selected_items]
            from_display = ", ".join(str(c) for c in from_classes)
        
        to_class = self.to_combo.currentData()
        radius = self.radius_spin.value()
        
        if to_class is None:
            QMessageBox.warning(self, "No Selection", "Please select To class")
            return
        
        # Don't allow converting TO class to itself
        if from_classes and to_class in from_classes:
            QMessageBox.warning(self, "Invalid Selection", f"Cannot convert class {to_class} to itself")
            return
        
        # Confirm
        total_points = len(self.app.data.get("classification", []))
        msg = (
            f"Convert {from_display} → class {to_class}\n"
            f"within {radius}m radius?\n\n"
            f"Scope: {total_points:,} points in dataset"
        )
        
        reply = QMessageBox.question(
            self,
            "Confirm Conversion",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Perform conversion
        try:
            converted_count = self._calculate_conversion(
                from_classes, to_class, radius, preview=False
            )
            
            if converted_count is None or converted_count == 0:
                QMessageBox.information(self, "No Points", "No points found to convert")
                return
            
            # Update UI
            self.preview_label.setText(f"✅ Converted {converted_count:,} points")
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 8px;
                    background-color: #1b5e20;
                    border-radius: 3px;
                }
            """)
            
            if self.ribbon_parent:
                self.ribbon_parent.update_status(
                    f"✅ Converted {converted_count:,} points",
                    "success"
                )
            
            QMessageBox.information(
                self,
                "Conversion Complete",
                f"✅ Successfully converted {converted_count:,} points"
            )
            
        except Exception as e:
            error_msg = f"Conversion failed: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            

    def _calculate_conversion(self, from_classes, to_class, radius, preview=False):
        """
        Calculate/perform the conversion
        
        Args:
            from_classes: List of class codes to convert FROM, or None for "any class"
            to_class: Class code to convert TO
            radius: Distance radius in meters
            preview: If True, just count points; if False, perform conversion
        """
        classification = self.app.data.get("classification")
        xyz = self.app.data.get("xyz")
        
        if classification is None or xyz is None:
            print("❌ No data!")
            return None
        
        print(f"\n{'='*60}")
        print(f"🔍 CLOSED BY CLASS CONVERSION")
        print(f"{'='*60}")
        print(f"   From class: {from_classes if from_classes else 'ANY CLASS'}")
        print(f"   To class: {to_class}")
        print(f"   Radius: {radius}m")
        print(f"   Total points in dataset: {len(classification):,}")
        
        # Work with entire dataset
        section_mask = np.ones(len(classification), dtype=bool)
        
        # Get To class points (reference points)
        to_class_mask = (classification == to_class) & section_mask
        to_class_count = np.sum(to_class_mask)
        
        print(f"   To class points: {to_class_count:,}")
        
        if to_class_count == 0:
            print("⚠️ No To class points found")
            
            # MODE 2: Convert ALL From class points when To class doesn't exist
            if from_classes is None:
                # ANY CLASS - exclude the to_class itself
                from_class_mask = (classification != to_class) & section_mask
            else:
                # Specific classes
                from_class_mask = np.isin(classification, from_classes) & section_mask
            
            from_class_count = np.sum(from_class_mask)
            
            if from_class_count == 0:
                print("⚠️ No From class points to convert")
                return 0
            
            # Show warning
            from_display = "ALL classes" if from_classes is None else f"classes {from_classes}"
            msg = (
                f"⚠️ Class {to_class} doesn't exist in dataset yet.\n\n"
                f"This will convert ALL {from_class_count:,} points from {from_display} → class {to_class}\n\n"
                f"Do you want to proceed?"
            )
            
            reply = QMessageBox.question(
                self,
                "No Reference Points - Convert All?",
                msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply != QMessageBox.Yes:
                return None
            
            if preview:
                return from_class_count
            
            # Perform conversion
            final_mask = from_class_mask.copy()
            old_classes = classification[final_mask].copy()
            classification[final_mask] = to_class
            self.app._just_did_conversion = True
            
            # Save undo
            undo_step = {
                "mask": final_mask.copy(),
                "old_classes": old_classes,
                "new_classes": np.full(np.sum(final_mask), to_class, dtype=classification.dtype)
            }
            self.app.undo_stack.append(undo_step)
            self.app.redo_stack.clear()
            from gui.memory_manager import trim_undo_stack
            trim_undo_stack(self.app)

            print(f"   ✅ Converted ALL {from_class_count:,} From class points to To class")
            self.app._conversion_just_happened = True
            # ✅ CRITICAL: Direct refresh - simple and always works
            from gui.class_display import update_class_mode
            update_class_mode(self.app, force_refresh=True)
            print(f"   ✅ Main view refreshed (forced rebuild)")

            # Refresh cross-sections if needed
            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in list(self.app.section_vtks.keys()):
                    try:
                        if hasattr(self.app, '_refresh_single_section_view'):
                            self.app._refresh_single_section_view(view_idx)
                    except Exception as e:
                        print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

            # Update point count widget
            if hasattr(self.app, 'point_count_widget'):
                self.app.point_count_widget.schedule_update()

            # Refresh Cut Section view if active
            try:
                ctrl = getattr(self.app, 'cut_section_controller', None)
                if ctrl and getattr(ctrl, 'is_cut_view_active', False):
                    if hasattr(ctrl, '_refresh_cut_colors_fast'):
                        ctrl._refresh_cut_colors_fast()
            except Exception as e:
                print(f"   ⚠️ Cut Section refresh failed: {e}")

            return from_class_count
        
        # Get From class points (to convert)
        if from_classes is None:
            # ANY CLASS - convert all except the to_class itself
            from_class_mask = (classification != to_class) & section_mask
        else:
            # Specific classes
            from_class_mask = np.isin(classification, from_classes) & section_mask
        
        from_class_count = np.sum(from_class_mask)
        
        print(f"   From class points: {from_class_count:,}")
        
        if from_class_count == 0:
            print("⚠️ No From class points to convert")
            return 0
        
        # Build KDTree from To class points
        to_class_xyz = xyz[to_class_mask]
        tree = cKDTree(to_class_xyz)
        print(f"   ✅ KDTree built with {len(to_class_xyz):,} reference points")
        
        # Query From class points
        from_class_xyz = xyz[from_class_mask]
        distances, _ = tree.query(from_class_xyz, distance_upper_bound=radius)
        
        # Points within radius
        near_mask = distances < radius
        near_count = np.sum(near_mask)
        
        print(f"   From class points within {radius}m of To class: {near_count:,}")
        
        # Apply filter if enabled
        if self.filter_checkbox.isChecked():
            filter_class = self.filter_combo.currentData()
            if filter_class is not None:
                print(f"   🔍 Applying filter: class {filter_class} must exist near To class")
                
                filter_class_mask = (classification == filter_class) & section_mask
                filter_class_xyz = xyz[filter_class_mask]
                
                if len(filter_class_xyz) == 0:
                    print("   ⚠️ No filter class points found - no conversions will occur")
                    near_mask[:] = False
                    near_count = 0
                else:
                    filter_tree = cKDTree(filter_class_xyz)
                    to_distances, _ = filter_tree.query(to_class_xyz, distance_upper_bound=radius)
                    valid_to_mask = to_distances < radius
                    
                    print(f"   To class points with filter class nearby: {np.sum(valid_to_mask):,}")
                    
                    if np.sum(valid_to_mask) == 0:
                        print("   ⚠️ No To class points have filter class nearby")
                        near_mask[:] = False
                        near_count = 0
                    else:
                        valid_to_xyz = to_class_xyz[valid_to_mask]
                        filtered_tree = cKDTree(valid_to_xyz)
                        filtered_distances, _ = filtered_tree.query(from_class_xyz, distance_upper_bound=radius)
                        near_mask = filtered_distances < radius
                        near_count = np.sum(near_mask)
                    
                    print(f"   After filter: {near_count:,} From class points will be converted")
        
        if preview:
            print(f"{'='*60}\n")
            return near_count
        
        # Perform conversion
        if near_count == 0:
            print(f"{'='*60}\n")
            return 0
        
        # Build final mask for main dataset
        final_mask = np.zeros(len(classification), dtype=bool)
        from_indices = np.where(from_class_mask)[0]
        convert_indices = from_indices[near_mask]
        final_mask[convert_indices] = True
        
        # Save old classes
        old_classes = classification[final_mask].copy()
        
        # Convert
        classification[final_mask] = to_class
        self.app._just_did_conversion = True
        
        # Save undo
        undo_step = {
            "mask": final_mask.copy(),
            "old_classes": old_classes,
            "new_classes": np.full(np.sum(final_mask), to_class, dtype=classification.dtype)
        }
        self.app.undo_stack.append(undo_step)
        self.app.redo_stack.clear()
        from gui.memory_manager import trim_undo_stack
        trim_undo_stack(self.app)

        print(f"   ✅ Converted {near_count:,} points")
        print(f"{'='*60}\n")
        self.app._conversion_just_happened = True
        
        # ✅ CRITICAL: Respect current display mode (FIXED)
        display_mode = getattr(self.app, 'display_mode', 'class')
        print(f"   📍 Current display mode: {display_mode}")
        
        if display_mode == "shaded_class":
            # Maintain shaded mesh visualization
            print(f"   🔺 Maintaining SHADING mode...")
            from gui.shading_display import update_shaded_class
            update_shaded_class(
                self.app,
                getattr(self.app, "last_shade_azimuth", 45.0),
                getattr(self.app, "last_shade_angle", 45.0),
                getattr(self.app, "shade_ambient", 0.2),
                force_rebuild=False
            )
            print(f"   ✅ Shaded mesh maintained after classification")
            
        elif display_mode == "class":
            # Standard class-colored point actors
            print(f"   🎨 Refreshing CLASS mode...")
            from gui.class_display import update_class_mode
            update_class_mode(self.app, force_refresh=True)
            print(f"   ✅ Class mode refreshed")
            
        else:
            # Other display modes
            print(f"   🌈 Refreshing {display_mode.upper()} mode...")
            from gui.pointcloud_display import update_pointcloud
            update_pointcloud(self.app, display_mode)
            print(f"   ✅ {display_mode} mode refreshed")

        # Refresh cross-sections if needed
        if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
            for view_idx in list(self.app.section_vtks.keys()):
                try:
                    if hasattr(self.app, '_refresh_single_section_view'):
                        self.app._refresh_single_section_view(view_idx)
                except Exception as e:
                    print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

        # Refresh Cut Section view if active
        try:
            ctrl = getattr(self.app, 'cut_section_controller', None)
            if ctrl and getattr(ctrl, 'is_cut_view_active', False):
                if hasattr(ctrl, '_refresh_cut_colors_fast'):
                        ctrl._refresh_cut_colors_fast()
        except Exception as e:
            print(f"   ⚠️ Cut Section refresh failed: {e}")

        # Update point count widget
        if hasattr(self.app, 'point_count_widget'):
            self.app.point_count_widget.schedule_update()

        
        return near_count
    
    def _refresh_all_views(self):
        """
        ✅ ULTIMATE FIXED: Combines fence dialog smart refresh + force rebuild fallback
        - First tries smart update (like fence dialog - prevents blank screens)
        - If that fails, forces full rebuild by clearing actors
        - Guaranteed to work in all scenarios!
        """
        print(f"\n🔄 REFRESHING VIEWS (smart + visibility-aware)...")
        
        # ✅ CRITICAL: Save camera position BEFORE any updates
        saved_camera = None
        if hasattr(self.app, 'vtk_widget') and hasattr(self.app.vtk_widget, 'renderer'):
            try:
                camera = self.app.vtk_widget.renderer.GetActiveCamera()
                if camera:
                    saved_camera = {
                        'position': tuple(camera.GetPosition()),
                        'focal_point': tuple(camera.GetFocalPoint()),
                        'view_up': tuple(camera.GetViewUp()),
                        'parallel_scale': camera.GetParallelScale(),
                        'parallel_projection': camera.GetParallelProjection(),
                    }
                    print(f"   📷 Camera saved: pos={saved_camera['position'][:2]}, scale={saved_camera['parallel_scale']:.2f}")
            except Exception as e:
                print(f"   ⚠️ Camera save failed: {e}")
        
        # ✅ DETECT MODE: By-class actors or unified actor?
        has_by_class_actors = False
        if hasattr(self.app, 'vtk_widget') and hasattr(self.app.vtk_widget, 'actors'):
            if isinstance(self.app.vtk_widget.actors, dict):
                for key in self.app.vtk_widget.actors.keys():
                    if 'class_' in str(key).lower():
                        has_by_class_actors = True
                        break
        
        update_success = False
        
        # ========================================
        # METHOD 1: SMART UPDATE (FROM FENCE DIALOG)
        # ========================================
        if has_by_class_actors:
            print(f"   🔍 Detected BY-CLASS actor mode - rebuilding affected actors...")
            
            try:
                display_dialog = getattr(self.app, 'display_mode_dialog', 
                                        getattr(self.app, 'display_dialog', None))
                
                if display_dialog:
                    # Try various display dialog methods
                    if hasattr(display_dialog, 'update_display_mode'):
                        display_dialog.update_display_mode()
                        print(f"   ✅ Called display_dialog.update_display_mode()")
                        update_success = True
                    
                    elif hasattr(display_dialog, 'refresh_actors'):
                        display_dialog.refresh_actors()
                        print(f"   ✅ Called display_dialog.refresh_actors()")
                        update_success = True
                    
                    elif hasattr(display_dialog, 'apply_class_filter'):
                        display_dialog.apply_class_filter()
                        print(f"   ✅ Called display_dialog.apply_class_filter()")
                        update_success = True
                    
                    elif hasattr(display_dialog, 'apply_btn'):
                        display_dialog.apply_btn.click()
                        print(f"   ✅ Triggered display_dialog.apply_btn.click()")
                        update_success = True
            
            except Exception as e:
                print(f"   ⚠️ Display mode refresh failed: {e}")
        
        # ✅ UNIFIED ACTOR MODE: Try smart update
        if not update_success:
            print(f"   🔍 Using unified actor mode - trying smart update...")
            
            # Try smart_update_colors
            try:
                from gui.pointcloud_display import smart_update_colors
                smart_update_colors(self.app, None)
                print(f"   ✅ Main view updated (smart_update_colors)")
                update_success = True
            except ImportError:
                print(f"   ⚠️ smart_update_colors not found")
            except Exception as e:
                print(f"   ⚠️ smart_update_colors failed: {e}")
            
            # Try direct VTK color update
            if not update_success:
                try:
                    if self._force_vtk_color_update():
                        print(f"   ✅ Main view updated (direct VTK with visibility)")
                        update_success = True
                except Exception:
                    pass
        
        # ========================================
        # METHOD 2: FORCE REBUILD (FALLBACK)
        # ========================================
        if not update_success:
            print(f"   ⚠️ Smart update failed - forcing full rebuild...")
            
            if hasattr(self.app, 'vtk_widget'):
                # Remove all actors to force rebuild
                if hasattr(self.app.vtk_widget, 'actor') and self.app.vtk_widget.actor:
                    old_actor = self.app.vtk_widget.actor
                    self.app.vtk_widget.actor = None
                    if hasattr(self.app.vtk_widget, 'renderer'):
                        self.app.vtk_widget.renderer.RemoveActor(old_actor)
                    print(f"      ✅ Removed unified actor")
                
                # Clear actors dict
                if hasattr(self.app.vtk_widget, 'actors'):
                    old_actors = self.app.vtk_widget.actors
                    if isinstance(old_actors, dict):
                        for actor in old_actors.values():
                            if actor and hasattr(self.app.vtk_widget, 'renderer'):
                                self.app.vtk_widget.renderer.RemoveActor(actor)
                        old_actors.clear()
                        print(f"      ✅ Cleared {len(old_actors)} actors")
            
            # Call update_class_mode - will detect missing actors and do full rebuild
            try:
                from gui.class_display import update_class_mode
                update_class_mode(self.app, force_refresh=True)
                print(f"   ✅ Main view refreshed (forced rebuild)")
                update_success = True
            except Exception as e:
                print(f"      ❌ Full rebuild failed: {e}")
        
        # ========================================
        # RESTORE & FINALIZE
        # ========================================
        
        # ✅ CRITICAL: Restore camera position IMMEDIATELY
        if saved_camera:
            try:
                camera = self.app.vtk_widget.renderer.GetActiveCamera()
                camera.SetPosition(saved_camera['position'])
                camera.SetFocalPoint(saved_camera['focal_point'])
                camera.SetViewUp(saved_camera['view_up'])
                camera.SetParallelScale(saved_camera['parallel_scale'])
                
                if saved_camera['parallel_projection']:
                    camera.ParallelProjectionOn()
                else:
                    camera.ParallelProjectionOff()
                
                self.app.vtk_widget.renderer.ResetCameraClippingRange()
                print(f"   📷✅ Camera restored")
            except Exception as e:
                print(f"   ⚠️ Camera restore failed: {e}")
        
        # Refresh cross-sections
        if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
            for view_idx in list(self.app.section_vtks.keys()):
                try:
                    if hasattr(self.app, '_refresh_single_section_view'):
                        self.app._refresh_single_section_view(view_idx)
                except Exception as e:
                    print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")
        
        # Update point statistics
        if hasattr(self.app, 'point_count_widget'):
            try:
                self.app.point_count_widget.schedule_update()
            except Exception:
                pass
        
        # ✅ Force final render
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass
        
        mode_str = "by-class" if has_by_class_actors else "unified"
        print(f"✅ REFRESH COMPLETE ({mode_str} mode, success: {update_success})\n")


    def _force_vtk_color_update(self):
        """
        Direct VTK color update with visibility awareness
        Called when smart_update_colors is not available
        """
        try:
            if not hasattr(self.app, 'vtk_widget'):
                return False
            
            vtk_widget = self.app.vtk_widget
            
            # Get the actor (unified mode)
            actor = None
            if hasattr(vtk_widget, 'actor') and vtk_widget.actor:
                actor = vtk_widget.actor
            elif hasattr(vtk_widget, 'actors') and isinstance(vtk_widget.actors, dict):
                # Try to find a unified actor
                for key, act in vtk_widget.actors.items():
                    if 'unified' in str(key).lower() or key == 'main':
                        actor = act
                        break
            
            if not actor:
                return False
            
            # Get mapper and update colors
            mapper = actor.GetMapper()
            if not mapper:
                return False
            
            # Get classification data
            classification = self.app.data.get("classification")
            if classification is None:
                return False
            
            # Get visibility mask if available
            visible_mask = None
            if hasattr(self.app, 'get_visible_points_mask'):
                visible_mask = self.app.get_visible_points_mask()
            
            # Update colors based on classification
            from vtk import vtkUnsignedCharArray
            colors = vtkUnsignedCharArray()
            colors.SetNumberOfComponents(3)
            colors.SetName("Colors")
            
            class_palette = getattr(self.app, 'class_palette', {})
            
            for i, cls in enumerate(classification):
                # Check visibility
                if visible_mask is not None and not visible_mask[i]:
                    # Make invisible points black or very dark
                    colors.InsertNextTuple3(20, 20, 20)
                else:
                    # Use class color
                    color_entry = class_palette.get(int(cls), {'color': (128, 128, 128)})
                    color = color_entry.get('color', (128, 128, 128))
                    colors.InsertNextTuple3(int(color[0]), int(color[1]), int(color[2]))
            
            # Update the polydata
            polydata = mapper.GetInput()
            if polydata:
                polydata.GetPointData().SetScalars(colors)
                polydata.Modified()
                mapper.Modified()
                actor.Modified()
            
            return True
            
        except Exception as e:
            print(f"      ❌ Direct VTK update failed: {e}")
            return False

        
    def on_from_selection_changed(self):
        """Called when From class selection changes - update display label"""
        selected_items = self.from_list.selectedItems()
        
        if not selected_items:
            self.from_selection_label.setText("No classes selected")
            self.from_selection_label.setStyleSheet("color: #f44336; font-size: 9px; font-style: italic;")
        else:
            # Check if "Any class" is selected
            any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
            
            if any_selected:
                self.from_selection_label.setText("✅ Selected: Any class (will convert ALL points)")
                self.from_selection_label.setStyleSheet("color: #4caf50; font-size: 9px; font-weight: bold;")
            else:
                codes = [str(item.data(Qt.UserRole)) for item in selected_items]
                self.from_selection_label.setText(f"✅ Selected: Classes {', '.join(codes)} ({len(codes)} class{'es' if len(codes) > 1 else ''})")
                self.from_selection_label.setStyleSheet("color: #4caf50; font-size: 9px; font-weight: bold;")
        
        # Also trigger the radius combo reset
        self.on_class_selection_changed()

    def on_class_selection_changed(self):
        """Called when From or To class selection changes"""
        # Reset radius suggestions
        self.radius_combo.clear()
        self.radius_combo.addItem("Click 'Analyze Distances' to see options", None)
        self.distance_info_label.setText(
            "💡 Classes changed. Click 'Analyze Distances' to recalculate."
        )
        self.distance_info_label.setStyleSheet("color: #ff9800; font-size: 9px; font-style: italic;")

    def on_radius_combo_changed(self, index):
        """Update spin box when dropdown selection changes"""
        radius = self.radius_combo.currentData()
        if radius is not None:
            self.radius_spin.setValue(radius)
    
    def analyze_distances(self):
        """Analyze actual distances between From and To class points"""
        # Get selected From classes (multi-select)
        selected_items = self.from_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select at least one From class")
            return
        
        # Check if "Any class" is selected
        any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
        
        if any_selected:
            from_classes = None  # Analyze ALL classes
            from_display = "All classes"
        else:
            from_classes = [item.data(Qt.UserRole) for item in selected_items]
            from_display = ", ".join(str(c) for c in from_classes)
        
        to_class = self.to_combo.currentData()
        
        if to_class is None:
            QMessageBox.warning(self, "No Selection", "Please select To class")
            return
        
        # Don't allow analyzing TO class to itself
        if from_classes and to_class in from_classes:
            QMessageBox.warning(self, "Invalid Selection", f"Cannot analyze class {to_class} to itself")
            return
        
        classification = self.app.data.get("classification")
        xyz = self.app.data.get("xyz")
        
        if classification is None or xyz is None:
            return
        
        print(f"\n{'='*60}")
        print(f"📊 ANALYZING POINT-TO-POINT DISTANCES")
        print(f"{'='*60}")
        
        # Work with entire dataset
        section_mask = np.ones(len(classification), dtype=bool)
        
        # Get To class points (reference points)
        to_class_mask = (classification == to_class) & section_mask
        to_class_count = np.sum(to_class_mask)
        
        print(f"   To class {to_class} points: {to_class_count:,}")
        
        if to_class_count == 0:
            QMessageBox.warning(
                self,
                "No Reference Points",
                f"No points of class {to_class} found in dataset."
            )
            return
        
        # Get From class points
        if from_classes is None:
            # ANY CLASS - analyze all except the to_class itself
            from_class_mask = (classification != to_class) & section_mask
        else:
            # Specific classes
            from_class_mask = np.isin(classification, from_classes) & section_mask
        
        from_class_count = np.sum(from_class_mask)
        
        print(f"   From class ({from_display}) points: {from_class_count:,}")
        
        if from_class_count == 0:
            QMessageBox.warning(
                self,
                "No Source Points",
                f"No points from {from_display} found in dataset."
            )
            return
        
        # Build KDTree from To class points
        to_class_xyz = xyz[to_class_mask]
        tree = cKDTree(to_class_xyz)
        
        # Query From class points - find nearest To class point for each
        from_class_xyz = xyz[from_class_mask]
        distances, _ = tree.query(from_class_xyz, k=1)
        
        # Calculate statistics
        min_dist = np.min(distances)
        max_dist = np.max(distances)
        mean_dist = np.mean(distances)
        median_dist = np.median(distances)
        
        # Count points at different percentile thresholds
        percentiles = [50, 75, 90, 95, 99, 100]
        radius_options = []
        
        for p in percentiles:
            threshold = np.percentile(distances, p)
            count = np.sum(distances <= threshold)
            percentage = (count / len(distances)) * 100
            radius_options.append({
                'percentile': p,
                'radius': threshold,
                'count': count,
                'percentage': percentage
            })
        
        print(f"\n   Distance Statistics:")
        print(f"   Min: {min_dist:.3f}m")
        print(f"   Max: {max_dist:.3f}m")
        print(f"   Mean: {mean_dist:.3f}m")
        print(f"   Median: {median_dist:.3f}m")
        print(f"\n   Point Coverage at Different Radii:")
        for opt in radius_options:
            print(f"   {opt['radius']:.3f}m → {opt['count']:,} points ({opt['percentage']:.1f}%)")
        print(f"{'='*60}\n")
        
        # Populate the dropdown with results
        self.radius_combo.clear()
        
        for opt in radius_options:
            label = f"{opt['radius']:.3f}m — {opt['percentile']}% coverage ({opt['count']:,} pts / {opt['percentage']:.1f}%)"
            self.radius_combo.addItem(label, opt['radius'])
        
        # Add separator
        self.radius_combo.insertSeparator(self.radius_combo.count())
        
        # Add some common manual values
        common_radii = [0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]
        for r in common_radii:
            if r <= max_dist:
                count = np.sum(distances <= r)
                percentage = (count / len(distances)) * 100
                label = f"{r:.1f}m (manual) — {count:,} pts ({percentage:.1f}%)"
                self.radius_combo.addItem(label, r)
        
        # Select the 90% coverage option by default (usually index 2)
        self.radius_combo.setCurrentIndex(2)
        
        # Update info label
        self.distance_info_label.setText(
            f"✅ Analyzed {from_class_count:,} From points → {to_class_count:,} To points | "
            f"Min: {min_dist:.3f}m | Max: {max_dist:.3f}m | Avg: {mean_dist:.3f}m"
        )
        self.distance_info_label.setStyleSheet("color: #4caf50; font-size: 9px; font-weight: bold;")
        
        # Show detailed message box
        msg = (
            f"📊 Point-to-Point Distance Analysis\n\n"
            f"From: {from_display}\n"
            f"To: Class {to_class}\n"
            f"Total points to convert: {from_class_count:,}\n"
            f"Reference points: {to_class_count:,}\n\n"
            f"Distance Statistics:\n"
            f"• Minimum: {min_dist:.3f}m (closest point)\n"
            f"• Maximum: {max_dist:.3f}m (farthest point)\n"
            f"• Average: {mean_dist:.3f}m\n"
            f"• Median: {median_dist:.3f}m\n\n"
            f"Select a radius from the dropdown to see\n"
            f"how many points will be converted!"
        )
        
        QMessageBox.information(self, "Distance Analysis Complete", msg)
    

    
    def naksha_dark_theme(self):
        """Return 'Obsidian & Teal' theme stylesheet to match Brush Settings"""
        return """
            QDialog {
                background-color: #0a0a0a;
                color: #eeeeee;
            }
            QLabel {
                color: #eeeeee;
            }
            /* Style for the Group Labels/Headers */
            QLabel#header_label {
                color: #00c8aa;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            QListWidget {
                background-color: #121212;
                color: #ffffff;
                border: 1px solid #222222;
                border-radius: 5px;
                padding: 5px;
                font-size: 11px;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #1a1a1a;
            }
            QListWidget::item:selected {
                background-color: #00c8aa;
                color: #000000;
                border-radius: 3px;
            }
            QComboBox, QDoubleSpinBox {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #ffffff;
                selection-background-color: #00c8aa;
                selection-color: #000000;
                border: 1px solid #00c8aa;
            }
            QPushButton {
                background-color: #222222;
                color: #ffffff;
                border: 1px solid #333333;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton#primary_btn {
                background-color: #00c8aa;
                color: #000000;
                font-weight: bold;
                border: none;
            }
            QPushButton#primary_btn:hover {
                background-color: #00e6c3;
            }
            QPushButton:hover {
                background-color: #333333;
            }
            QCheckBox {
                color: #aaaaaa;
            }
        """


    def make_color_icon(color):
        """Helper function to create color icon for list items"""
        from PyQt5.QtGui import QPixmap, QIcon
        from PyQt5.QtCore import Qt
        
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        
        from PyQt5.QtGui import QPainter, QColor
        painter = QPainter(pixmap)
        painter.setBrush(QColor(*color))
        painter.setPen(QColor(80, 80, 80))
        painter.drawRect(0, 0, 15, 15)
        painter.end()
        
        return QIcon(pixmap)

class ByClassHeightDialog(QDialog):
    """Height-Based Class Conversion Dialog"""
    
    def __init__(self, app, ribbon_parent):
        # ✅ FIX 1: Robust Parent Finding
        from PySide6.QtWidgets import QWidget
        target_parent = None
        if isinstance(app, QWidget):
            target_parent = app
        elif hasattr(app, 'window') and isinstance(app.window, QWidget):
            target_parent = app.window

        super().__init__(None, Qt.Window)
        
        self.setAttribute(Qt.WA_NativeWindow, True)  # Fix: GetDC invalid window handle

        self.setWindowModality(Qt.NonModal)
        self.app = app
        self.ribbon_parent = ribbon_parent
        
        self.setWindowTitle("By Class Height - Height-Based Classification")
        # self.setStyleSheet(self.naksha_dark_theme()) # Inherits global theme
        self.setGeometry(200, 200, 450, 400)
        
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Shortcuts...
        
        self._last_conversion_info = None
        self.selected_fences = []
        self.permanent_fence_mode = False
        self._selection_highlight_actors = []
        self._hover_highlight_actor = None
        self._classified_fence_actors = []
        self._fence_selection_dialog = None
        self.init_ui()
        self.populate_classes()
        
        # Display mode connection...
        display_dialog = getattr(self.app, 'display_mode_dialog', getattr(self.app, 'display_dialog', None))
        if display_dialog:
            try:
                display_dialog.classes_loaded.connect(self.on_classes_changed)
            except Exception: pass
    
    def showEvent(self, event):
        """Ensure dialog gets focus when shown"""
        super().showEvent(event)
        self.setFocus()
        self.activateWindow()
        if hasattr(self, 'selected_fences') and self.selected_fences:
            self._restore_highlights_from_data()
        print("🔵 ByClassHeightDialog activated and focused")
    
    def focusInEvent(self, event):
        """Called when dialog gains focus"""
        super().focusInEvent(event)
        print("🔵 ByClassHeightDialog gained focus - undo/redo active")
    
    def focusOutEvent(self, event):
        """Called when dialog loses focus"""
        super().focusOutEvent(event)
        print("⚪ ByClassHeightDialog lost focus")

    def perform_undo(self):
        """
        Perform CLASSIFICATION undo operation
        ✅ FIXED: Display-mode-aware — undo_classification handles its own refresh
        """
        if not hasattr(self.app, 'undo_classification'):
            QMessageBox.warning(self, "Undo Not Available", "Classification undo not found")
            return
        try:
            print("🔄 ByClassHeightDialog: Performing CLASSIFICATION undo...")
            
            # ✅ undo_classification handles ALL refresh internally
            self.app.undo_classification()
            
            # ✅ FIX: Only do supplementary refresh for CLASS mode
            # undo_classification already handles shading rebuild
            display_mode = getattr(self.app, 'display_mode', 'class')
            
            if display_mode == 'shaded_class':
                print(f"   🌓 Shading mode — undo refresh already handled")
                # Do NOT call _refresh_after_classification — would double-refresh
                
            elif display_mode == 'class':
                # Safety net for class mode
                from gui.class_display import update_class_mode
                update_class_mode(self.app, force_refresh=True)
                print(f"   ✅ Main view refreshed (class mode)")
            else:
                print(f"   📊 {display_mode} mode — undo refresh already handled")
            
            # Update point count widget
            if hasattr(self.app, 'point_count_widget'):
                self.app.point_count_widget.schedule_update()
            
            self.preview_label.setText("↶ Undo performed")
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 6px;
                    background-color: #3e2723;
                    border-radius: 3px;
                }
            """)
            print("✅ Classification undo performed")
        except Exception as e:
            print(f"❌ Undo failed: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Undo Failed", f"Could not undo: {str(e)}")
    
    def perform_redo(self):
        """
        Perform CLASSIFICATION redo operation
        ✅ FIXED: Display-mode-aware — handles shading rebuild properly
        """
        if not hasattr(self.app, 'redo_classification'):
            QMessageBox.warning(self, "Redo Not Available", 
                            "Classification redo functionality not found")
            return
        
        print("🔄 ByClassHeightDialog: Performing CLASSIFICATION redo...")
        
        try:
            self.app.redo_classification()
            
            # ✅ FIX: Display-mode-aware supplementary refresh
            display_mode = getattr(self.app, 'display_mode', 'class')
            
            if display_mode == 'shaded_class':
                print(f"   🌓 Shading mode — redo needs explicit rebuild")
                try:
                    from gui.shading_display import get_cache, update_shaded_class, clear_shading_cache
                    cache = get_cache()
                    
                    # Save visibility from cache or app store
                    saved_vis = getattr(cache, 'visible_classes_set', None)
                    if saved_vis is None or len(saved_vis) == 0:
                        saved_vis = getattr(self.app, '_shading_visible_classes', None)
                    if saved_vis is None or len(saved_vis) == 0:
                        saved_vis = {
                            int(c) for c, e in self.app.class_palette.items()
                            if e.get("show", True)
                        }
                    saved_vis = saved_vis.copy()
                    
                    print(f"   📍 Preserved visibility: {sorted(saved_vis)}")
                    
                    # Force palette to match
                    for c in self.app.class_palette:
                        self.app.class_palette[c]["show"] = (int(c) in saved_vis)
                    
                    clear_shading_cache("redo classification in shading mode")
                    update_shaded_class(
                        self.app,
                        getattr(self.app, "last_shade_azimuth", 45.0),
                        getattr(self.app, "last_shade_angle", 45.0),
                        getattr(self.app, "shade_ambient", 0.2),
                        force_rebuild=True
                    )
                    print(f"   ✅ Shading rebuilt after redo "
                          f"({'single' if len(saved_vis) == 1 else 'multi'}-class)")
                except Exception as e:
                    print(f"   ⚠️ Shading rebuild failed: {e}")
                    from gui.class_display import update_class_mode
                    update_class_mode(self.app, force_refresh=True)
                    
            elif display_mode == 'class':
                from gui.class_display import update_class_mode
                update_class_mode(self.app, force_refresh=True)
                print(f"   ✅ Main view refreshed (class mode)")
            else:
                print(f"   📊 {display_mode} mode — redo refresh already handled")

            # Refresh cross-sections if needed
            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in list(self.app.section_vtks.keys()):
                    try:
                        if hasattr(self.app, '_refresh_single_section_view'):
                            self.app._refresh_single_section_view(view_idx)
                    except Exception as e:
                        print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

            # Update point count widget
            if hasattr(self.app, 'point_count_widget'):
                self.app.point_count_widget.schedule_update()

            
            self.preview_label.setText("↷ Redo performed")
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 6px;
                    background-color: #3e2723;
                    border-radius: 3px;
                }
            """)
            print("✅ Classification redo performed")
        except Exception as e:
            print(f"❌ Redo failed: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Redo Failed", f"Could not redo: {str(e)}")
    
    def naksha_dark_theme(self):
        """Return 'Obsidian & Teal' theme stylesheet"""
        return """
            QDialog {
                background-color: #0a0a0a;
                color: #eeeeee;
            }
            QLabel {
                color: #eeeeee;
            }
            /* Teal Section Headers */
            QLabel#header_label {
                color: #00c8aa;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            QListWidget {
                background-color: #121212;
                color: #ffffff;
                border: 1px solid #222222;
                border-radius: 5px;
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #00c8aa;
                color: #000000;
                border-radius: 3px;
            }
            QComboBox, QDoubleSpinBox {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #ffffff;
                selection-background-color: #00c8aa;
                selection-color: #000000;
            }
            QPushButton {
                background-color: #222222;
                color: #ffffff;
                border: 1px solid #333333;
                padding: 8px;
                border-radius: 4px;
            }
            /* Solid Teal Action Button */
            QPushButton#primary_btn {
                background-color: #00c8aa;
                color: #000000;
                font-weight: bold;
                border: none;
            }
            QPushButton#primary_btn:hover {
                background-color: #00e6c3;
            }
        """
        
    def init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Info banner - Styled darker to match the obsidian vibe
        self.info_banner = QLabel("📏 Convert points based on height above ground (Class 1)")
        self.info_banner.setStyleSheet("""
            QLabel {
                font-size: 11px;
                font-weight: bold;
                color: #ffffff;
                padding: 8px;
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 4px;
            }
        """)
        self.info_banner.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_banner)
        
        # ===================== FENCE FILTER SECTION (NEW!) =====================
        fence_header = QHBoxLayout()
        fence_label = QLabel("🔷 FENCE FILTER (OPTIONAL)")
        fence_label.setObjectName("header_label")
        self.fence_count_badge = QLabel("0")
        self.fence_count_badge.setStyleSheet("""
            QLabel {
                background-color: #9c27b0; color: white; border-radius: 10px;
                padding: 2px 8px; font-size: 9px; font-weight: bold;
            }
        """)
        self.fence_count_badge.setAlignment(Qt.AlignCenter)
        fence_header.addWidget(fence_label)
        fence_header.addStretch()
        fence_header.addWidget(self.fence_count_badge)
        layout.addLayout(fence_header)
        
        self.fence_filter_enabled = QCheckBox("Enable Fence Filter (classify only inside fence)")
        self.fence_filter_enabled.toggled.connect(self.on_fence_filter_toggled)
        layout.addWidget(self.fence_filter_enabled)
        
        self.fence_container = QWidget()
        fence_layout = QVBoxLayout(self.fence_container)
        fence_layout.setContentsMargins(5, 0, 5, 0)
        fence_layout.setSpacing(4)
        
        fence_btn_row = QHBoxLayout()
        self.select_fence_btn = QPushButton("📐 Select Fence(s)")
        self.select_fence_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976d2; color: white; font-size: 10px;
                font-weight: bold; padding: 8px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #1565c0; }
        """)
        self.select_fence_btn.clicked.connect(self.select_fence)
        fence_btn_row.addWidget(self.select_fence_btn, 2)
        
        self.clear_fence_btn = QPushButton("🗑️ Clear")
        self.clear_fence_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555; color: white; font-size: 10px;
                padding: 8px; border-radius: 4px;
            }
            QPushButton:hover { background-color: #d32f2f; }
        """)
        self.clear_fence_btn.clicked.connect(self.clear_fence_selection)
        fence_btn_row.addWidget(self.clear_fence_btn, 1)
        fence_layout.addLayout(fence_btn_row)
        
        self.fence_status = QLabel("❌ No fence selected")
        self.fence_status.setStyleSheet("""
            QLabel {
                padding: 4px; background-color: #2c2c2c; border-radius: 3px;
                color: #f44336; font-size: 9px;
            }
        """)
        self.fence_status.setWordWrap(True)
        fence_layout.addWidget(self.fence_status)
        
        layout.addWidget(self.fence_container)
        self.fence_container.setVisible(False)
        
        # Step 1: Class selection
        class_label = QLabel("📋 SELECT CLASSES")
        class_label.setObjectName("header_label") # Applies Teal color
        layout.addWidget(class_label)
        
        from_label = QLabel("From class (Ctrl+Click for multiple):")
        from_label.setStyleSheet("color: #888888; font-size: 10px;")
        layout.addWidget(from_label)

        self.from_list = QListWidget()
        self.from_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.from_list.setMinimumHeight(120)
        self.from_list.itemSelectionChanged.connect(self.on_from_selection_changed)
        layout.addWidget(self.from_list)

        self.from_selection_label = QLabel("No classes selected")
        self.from_selection_label.setStyleSheet("color: #666666; font-size: 9px; font-style: italic;")
        layout.addWidget(self.from_selection_label)
        
        # To class
        to_label = QLabel("To class (convert to):")
        to_label.setStyleSheet("color: #888888; font-size: 10px; margin-top: 4px;")
        layout.addWidget(to_label)
        self.to_combo = QComboBox()
        layout.addWidget(self.to_combo)
        
        # Step 2: Height range
        height_label = QLabel("📐 SET HEIGHT RANGE")
        height_label.setObjectName("header_label") # Applies Teal color
        layout.addWidget(height_label)

        # ── Reference Class ──────────────────────────────────────────────────
        ref_row = QHBoxLayout()
        ref_label = QLabel("Reference class (heights measured from):")
        ref_label.setStyleSheet("color: #888888; font-size: 10px;")
        layout.addWidget(ref_label)

        self.ref_class_combo = QComboBox()
        self.ref_class_combo.setToolTip(
            "Heights are measured from the nearest point of this class.\n"
            "Default: Class 1 (Ground). Change to use a different class\n"
            "as the zero-height baseline (e.g. Low Vegetation)."
        )
        # When reference class changes, force re-analysis before convert
        self.ref_class_combo.currentIndexChanged.connect(self.on_ref_class_changed)
        layout.addWidget(self.ref_class_combo)

        ref_info = QLabel("ℹ️ Min = 0 m means 'at reference class level'. "
                          "Heights are relative to nearest reference-class point.")
        ref_info.setStyleSheet("color: #607d8b; font-size: 9px; font-style: italic;")
        ref_info.setWordWrap(True)
        layout.addWidget(ref_info)
        # ────────────────────────────────────────────────────────────────────

        # Analysis button - uses a muted purple or keep standard dark
        analyze_btn = QPushButton("🔍 Analyze Heights")
        analyze_btn.setStyleSheet("color: #00c8aa; font-weight: bold; background-color: #1a1a1a;")
        analyze_btn.clicked.connect(self.analyze_heights)
        layout.addWidget(analyze_btn)
        
        self.height_combo = QComboBox()
        self.height_combo.addItem("Select class and click Analyze first", None)
        self.height_combo.currentIndexChanged.connect(self.on_height_combo_changed)
        layout.addWidget(self.height_combo)
        
        # Min/Max height row
        min_height_row = QHBoxLayout()
        min_height_row.addWidget(QLabel("Min:"))
        self.min_height_spin = QDoubleSpinBox()
        self.min_height_spin.setRange(-999999.0, 999999.0)
        self.min_height_spin.setSuffix(" m")
        min_height_row.addWidget(self.min_height_spin)
        
        min_height_row.addWidget(QLabel("Max:"))
        self.max_height_spin = QDoubleSpinBox()
        self.max_height_spin.setRange(-999999.0, 999999.0)
        self.max_height_spin.setSuffix(" m")
        min_height_row.addWidget(self.max_height_spin)
        layout.addLayout(min_height_row)
        
        # Action buttons
# AFTER
        # ✅ FIX: height_info_label — referenced in on_class_selection_changed & analyze_heights
        self.height_info_label = QLabel("💡 Select a class and click 'Analyze Heights' to begin.")
        self.height_info_label.setStyleSheet("color: #888888; font-size: 9px; font-style: italic;")
        self.height_info_label.setWordWrap(True)
        layout.addWidget(self.height_info_label)

        # Action buttons
        button_row = QHBoxLayout()
        
        convert_btn = QPushButton("🔄 Convert")
        convert_btn.setObjectName("primary_btn")
        convert_btn.clicked.connect(self.perform_conversion)
        button_row.addWidget(convert_btn)
        
        layout.addLayout(button_row)

        # ✅ FIX: preview_label — referenced in perform_conversion, perform_undo, perform_redo
        self.preview_label = QLabel("")
        self.preview_label.setStyleSheet("color: #888888; font-size: 9px; font-style: italic;")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

    # ==================== FENCE METHODS ====================
    
    def on_fence_filter_toggled(self, checked):
        """Toggle fence filter UI visibility"""
        is_checked = bool(checked)
        self.fence_container.setVisible(is_checked)
        if is_checked:
            self.info_banner.setText("📏🔷 Height classification INSIDE FENCE only")
        else:
            self.info_banner.setText("📏 Convert points based on height above ground (Class 1)")

    def select_fence(self):
        """Select fences from digitize manager AND curve tool"""
        if hasattr(self, '_fence_selection_dialog') and self._fence_selection_dialog is not None:
            try:
                self._fence_selection_dialog.close()
            except RuntimeError:
                pass
            self._fence_selection_dialog = None
        
        digitize = getattr(self.app, 'digitizer', None)
        curve_tool = getattr(self.app, 'curve_tool', None)
        
        # ── Collect digitizer drawings ────────────────────────────
        valid_shapes = []
        if digitize:
            drawings = getattr(digitize, 'drawings', [])
            if drawings:
                valid_shapes = [d for d in drawings if d.get('type') in 
                            ['rectangle', 'circle', 'polygon', 'freehand', 'line',
                             'smart_line', 'polyline', 'smartline']]
        
        # ── Collect curve tool curves ✅ NEW ─────────────────────
        curve_fences = []
        if curve_tool and hasattr(curve_tool, 'get_curves_as_fences'):
            curve_fences = curve_tool.get_curves_as_fences()
        
        # Combine all
        all_fences = valid_shapes + curve_fences
        
        if not valid_shapes and not curve_fences:
            QMessageBox.warning(self, "No Shapes Found",
                "No shapes or curves found.\n\n"
                "• Draw shapes using Digitize tools, OR\n"
                "• Draw curves using the Curve tool")
            return
        
        if not digitize and not curve_tool:
            QMessageBox.warning(self, "No Tools Available",
                "Digitize manager and Curve tool not found.")
            return
        
        from PySide6.QtWidgets import (QListWidget, QAbstractItemView, QVBoxLayout,
                                        QHBoxLayout, QPushButton, QCheckBox, QWidget,
                                        QLabel as QLabel2, QListWidgetItem)
        from PySide6.QtCore import QEvent
        
        try:
            dialog = QDialog(self, Qt.Window)
            self._fence_selection_dialog = dialog
            dialog.setWindowTitle("Select Fence(s) for Height Classification")
            dialog.setWindowModality(Qt.NonModal)
            dialog.resize(420, 500)
            
            dlayout = QVBoxLayout(dialog)
            
            # Header with source counts
            shape_count = len(valid_shapes)
            curve_count = len(curve_fences)
            info_text = f"Select fence(s) to restrict height classification area"
            info_label = QLabel(info_text)
            info_label.setStyleSheet("color: #9c27b0; font-weight: bold; padding: 8px;")
            dlayout.addWidget(info_label)
            
            count_label = QLabel(f"📐 Digitizer: {shape_count}  |  〰️ Curves: {curve_count}")
            count_label.setStyleSheet("color: #888888; font-size: 10px; padding: 0 8px;")
            dlayout.addWidget(count_label)
            
            permanent_check = QCheckBox("🔄 Permanent Fence Mode")
            permanent_check.setChecked(True)
            self.permanent_fence_mode = True
            permanent_check.setStyleSheet("""
                QCheckBox { color: #eeeeee; font-size: 11px; padding: 8px; font-weight: bold; }
                QCheckBox::indicator { width: 18px; height: 18px; }
                QCheckBox::indicator:unchecked { background-color: #2c2c2c; border: 1px solid #555555; border-radius: 3px; }
                QCheckBox::indicator:checked { background-color: #9c27b0; border: 1px solid #9c27b0; border-radius: 3px; }
            """)
            dlayout.addWidget(permanent_check)
            
            fence_list = QListWidget()
            fence_list.setStyleSheet("""
                QListWidget { background-color: #1e1e1e; border: 1px solid #3a3a3a; border-radius: 4px; padding: 4px; }
                QListWidget::item { background: transparent; border: none; padding: 2px; }
            """)
            fence_list.setSelectionMode(QAbstractItemView.NoSelection)
            
            # ✅ UPDATED: Shape icons including curve
            SHAPE_ICONS = {
                'rectangle': '▭', 'circle': '○', 'polygon': '⬟', 'polyline': '⬡',
                'line': '─', 'smartline': '⚡', 'freehand': '✏️', 'curve': '〰️'
            }
            
            custom_widgets = []
            current_hover_actor = [None]
            selection_highlight_actors = {}
            
            def _add_actor_to_renderer(actor):
                """Add actor handling both Actor and Actor2D"""
                if actor is None:
                    return
                try:
                    if hasattr(actor, 'IsA') and actor.IsA('vtkActor2D'):
                        self.app.vtk_widget.renderer.AddViewProp(actor)
                    else:
                        self.app.vtk_widget.renderer.AddActor(actor)
                except Exception:
                    pass
            
            def _rem_actor_from_renderer(actor):
                """Remove actor handling both Actor and Actor2D"""
                if actor is None:
                    return
                try:
                    if hasattr(actor, 'IsA') and actor.IsA('vtkActor2D'):
                        self.app.vtk_widget.renderer.RemoveViewProp(actor)
                    else:
                        self.app.vtk_widget.renderer.RemoveActor(actor)
                except Exception:
                    pass
            
            def _make_highlight_actor(coords, color, width):
                """Create highlight actor (Actor2D for curves, Actor for digitizer)"""
                try:
                    import vtk
                    pts = vtk.vtkPoints()
                    pts.SetDataTypeToDouble()
                    for c in coords:
                        z = float(c[2]) if len(c) > 2 else 0.0
                        pts.InsertNextPoint(float(c[0]), float(c[1]), z)
                    
                    pl = vtk.vtkPolyLine()
                    pl.GetPointIds().SetNumberOfIds(len(coords))
                    for i in range(len(coords)):
                        pl.GetPointIds().SetId(i, i)
                    
                    ca = vtk.vtkCellArray()
                    ca.InsertNextCell(pl)
                    
                    pd = vtk.vtkPolyData()
                    pd.SetPoints(pts)
                    pd.SetLines(ca)
                    
                    # Use Actor2D for consistent overlay rendering
                    mapper = vtk.vtkPolyDataMapper2D()
                    mapper.SetInputData(pd)
                    
                    coord = vtk.vtkCoordinate()
                    coord.SetCoordinateSystemToWorld()
                    mapper.SetTransformCoordinate(coord)
                    
                    actor = vtk.vtkActor2D()
                    actor.SetMapper(mapper)
                    actor.GetProperty().SetColor(*color)
                    actor.GetProperty().SetLineWidth(width)
                    actor.GetProperty().SetDisplayLocationToForeground()
                    
                    return actor
                except Exception:
                    # Fallback to 3D actor
                    try:
                        if hasattr(self.app, 'digitizer'):
                            return self.app.digitizer._make_polyline_actor(coords, color=color, width=width)
                    except Exception:
                        pass
                    return None
            
            def highlight_fence_in_3d(shape):
                if current_hover_actor[0]:
                    _rem_actor_from_renderer(current_hover_actor[0])
                    current_hover_actor[0] = None
                if not shape:
                    try: self.app.vtk_widget.render()
                    except Exception: pass
                    return
                coords = shape.get('coords', [])
                if not coords: return
                try:
                    ha = _make_highlight_actor(coords, (1, 1, 0), 6)  # Yellow
                    if ha:
                        _add_actor_to_renderer(ha)
                        current_hover_actor[0] = ha
                        self.app.vtk_widget.render()
                except Exception as e:
                    print(f"⚠️ Hover highlight failed: {e}")
            
            def add_selection_highlight(shp):
                coords = shp.get('coords', [])
                if not coords: return
                try:
                    act = _make_highlight_actor(coords, (0, 0.5, 1), 5)  # Blue
                    if act:
                        _add_actor_to_renderer(act)
                        # Use stable ID based on source
                        if shp.get('source') == 'curve_tool':
                            selection_highlight_actors[id(shp.get('curve_data', shp))] = act
                        else:
                            selection_highlight_actors[id(shp)] = act
                        self.app.vtk_widget.render()
                except Exception as e:
                    print(f"⚠️ Selection highlight failed: {e}")

            def remove_selection_highlight(shp):
                # Get stable ID based on source
                if shp.get('source') == 'curve_tool':
                    sid = id(shp.get('curve_data', shp))
                else:
                    sid = id(shp)
                act = selection_highlight_actors.pop(sid, None)
                if act:
                    _rem_actor_from_renderer(act)
                    try: self.app.vtk_widget.render()
                    except Exception: pass
            
            # ── Build current selection IDs ───────────────────────
            current_ids = set()
            for f in self.selected_fences:
                if f.get('source') == 'curve_tool':
                    current_ids.add(id(f.get('curve_data', f)))
                else:
                    current_ids.add(id(f))
            
            # ── Build list items ──────────────────────────────────
            for idx, fence in enumerate(all_fences):
                stype = fence.get('type', 'unknown')
                coords = fence.get('coords', [])
                is_curve = fence.get('source') == 'curve_tool'
                icon = SHAPE_ICONS.get(stype, '◆')
                
                # Title and source
                if is_curve:
                    curve_idx = fence.get('curve_index', idx)
                    title_text = f"〰️ Curve #{curve_idx + 1}"
                    source_tag = "Curve Tool"
                else:
                    title_text = f"{icon} #{idx+1}: {stype.capitalize()}"
                    source_tag = "Digitizer"
                
                try:
                    arr = np.array(coords)
                    w = arr[:, 0].max() - arr[:, 0].min()
                    h = arr[:, 1].max() - arr[:, 1].min()
                    size_str = f"{w:.1f}×{h:.1f}m"
                except Exception:
                    size_str = ""
                
                # Check if currently selected
                if is_curve:
                    is_current = id(fence.get('curve_data', fence)) in current_ids
                else:
                    is_current = id(fence) in current_ids
                
                # Build item widget
                item_widget = QWidget()
                bg = "#1a2a1a" if is_curve else "#2a2a2a"
                item_widget.setStyleSheet(f"QWidget {{ background-color: {bg}; border: 1px solid #3a3a3a; border-radius: 6px; padding: 8px; margin: 2px; }} QWidget:hover {{ background-color: #3c3c3c; border: 1px solid #555555; }}")
                il = QHBoxLayout(item_widget); il.setContentsMargins(8, 8, 8, 8)
                
                cb = QCheckBox()
                cb.setStyleSheet("QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 3px; border: 1px solid #555555; background-color: #1e1e1e; }} QCheckBox::indicator:checked {{ background-color: #9c27b0; border: 1px solid #9c27b0; }}")
                il.addWidget(cb)
                
                tl = QLabel2(f"{title_text}\n{len(coords)} pts | {size_str} | {source_tag}")
                tl.setStyleSheet("color: #eeeeee; font-size: 10px; background: transparent;")
                il.addWidget(tl, 1)
                
                sb = QLabel2("Selected")
                sb.setStyleSheet("QLabel { background-color: #6a1b9a; color: white; font-size: 9px; font-weight: bold; padding: 4px 8px; border-radius: 3px; }")
                sb.setVisible(is_current)
                il.addWidget(sb)
                
                li = QListWidgetItem(fence_list)
                
                # No delete button for curves (managed by curve tool)
                if not is_curve:
                    db = QPushButton("🗑️")
                    db.setStyleSheet("QPushButton { background-color: transparent; color: #f44336; font-size: 14px; border: none; padding: 4px; } QPushButton:hover { background-color: #4a1414; border-radius: 4px; }")
                    il.addWidget(db)
                else:
                    # Placeholder for layout alignment
                    spacer = QWidget()
                    spacer.setFixedSize(28, 28)
                    il.addWidget(spacer)
                
                def make_toggle(badge, widget, shp, ic):
                    def toggle(checked):
                        badge.setVisible(checked)
                        if checked:
                            bg_c = "#2a3a2a" if ic else "#3a2a4a"
                            widget.setStyleSheet(f"background-color: {bg_c}; border: 1px solid #6a1b9a; border-radius: 6px; padding: 8px; margin: 2px;")
                            add_selection_highlight(shp)
                        else:
                            widget.setStyleSheet("QWidget { background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 6px; padding: 8px; margin: 2px; } QWidget:hover { background-color: #3c3c3c; border: 1px solid #555555; }")
                            remove_selection_highlight(shp)
                    return toggle
                cb.toggled.connect(make_toggle(sb, item_widget, fence, is_curve))
                
                if is_current:
                    item_widget.setStyleSheet("background-color: #3a2a4a; border: 1px solid #6a1b9a; border-radius: 6px; padding: 8px; margin: 2px;")
                    add_selection_highlight(fence)
                
                # Click to toggle (but not on delete button)
                if not is_curve:
                    def make_click(checkbox, delbtn):
                        def on_press(event):
                            if not delbtn.underMouse():
                                checkbox.setChecked(not checkbox.isChecked())
                        return on_press
                    item_widget.mousePressEvent = make_click(cb, db)
                    
                    def make_del(shp, lst_item, tidx):
                        def do_del():
                            remove_selection_highlight(shp)
                            highlight_fence_in_3d(None)
                            if hasattr(self.app, 'digitizer'):
                                self.app.digitizer.clear_coordinate_labels()
                                self.app.digitizer._remove_drawing(shp)
                            if shp in self.selected_fences:
                                self.selected_fences.remove(shp)
                            for i, cw in enumerate(custom_widgets):
                                if cw[3] is shp: custom_widgets.pop(i); break
                            fence_list.takeItem(fence_list.row(lst_item))
                            update_stats(); self.update_fence_display()
                            try: self.app.vtk_widget.render()
                            except Exception: pass
                        return do_del
                    db.clicked.connect(make_del(fence, li, idx))
                else:
                    def make_click_curve(checkbox):
                        def on_press(event):
                            checkbox.setChecked(not checkbox.isChecked())
                        return on_press
                    item_widget.mousePressEvent = make_click_curve(cb)
                
                item_widget.setCursor(Qt.PointingHandCursor)
                
                class HoverFilter(QWidget):
                    def __init__(self, parent, sd):
                        super().__init__(parent); self.sd = sd
                    def eventFilter(self, obj, event):
                        if event.type() == QEvent.Enter: highlight_fence_in_3d(self.sd)
                        elif event.type() == QEvent.Leave: highlight_fence_in_3d(None)
                        return super().eventFilter(obj, event)
                item_widget.installEventFilter(HoverFilter(item_widget, fence))
                
                li.setSizeHint(item_widget.sizeHint())
                fence_list.setItemWidget(li, item_widget)
                custom_widgets.append((cb, item_widget, sb, fence))
            
            dlayout.addWidget(fence_list)
            
            stats_label = QLabel("Select one or more fences")
            stats_label.setStyleSheet("color: #aaaaaa; font-size: 9px; padding: 4px;")
            dlayout.addWidget(stats_label)
            
            def update_stats():
                c = sum(1 for cb, _, _, _ in custom_widgets if cb.isChecked())
                stats_label.setText(f"✅ {c} fence(s) selected" if c else "⚠️ No fences selected")
            for cb, _, _, _ in custom_widgets:
                cb.toggled.connect(update_stats)
            
            bl = QHBoxLayout()
            sa = QPushButton("Select All")
            sa.setStyleSheet("QPushButton { background-color: #1976d2; color: white; font-size: 10px; padding: 6px 12px; border-radius: 3px; }")
            sa.clicked.connect(lambda: [cb.setChecked(True) for cb, _, _, _ in custom_widgets])
            bl.addWidget(sa)
            
            ca = QPushButton("Clear All")
            ca.setStyleSheet("QPushButton { background-color: #555555; color: white; font-size: 10px; padding: 6px 12px; border-radius: 3px; }")
            def clear_all():
                for cb, _, _, _ in custom_widgets: cb.setChecked(False)
                for act in selection_highlight_actors.values():
                    _rem_actor_from_renderer(act)
                selection_highlight_actors.clear()
                self.selected_fences = []; self._clear_fence_highlights()
                self.fence_status.setText("❌ No fence selected")
                self.fence_status.setStyleSheet("QLabel { padding: 4px; background-color: #2c2c2c; border-radius: 3px; color: #f44336; }")
                self.fence_count_badge.setText("0"); update_stats()
            ca.clicked.connect(clear_all)
            bl.addWidget(ca); bl.addStretch()
            
            ap = QPushButton("Apply Selection")
            ap.setStyleSheet("QPushButton { background-color: #2e7d32; color: white; font-size: 10px; font-weight: bold; padding: 6px 16px; border-radius: 3px; }")

            def apply_sel():
                highlight_fence_in_3d(None)
                sel = [shp for cb, _, _, shp in custom_widgets if cb.isChecked()]
                if not sel:
                    QMessageBox.warning(dialog, "No Selection", "Select at least one fence")
                    return
                self.permanent_fence_mode = permanent_check.isChecked()
                if not self.permanent_fence_mode: self.selected_fences = []
                
                # Build existing IDs
                existing_ids = set()
                for f in self.selected_fences:
                    if f.get('source') == 'curve_tool':
                        existing_ids.add(id(f.get('curve_data', f)))
                    else:
                        existing_ids.add(id(f))
                
                for s in sel:
                    if s.get('source') == 'curve_tool':
                        fence_id = id(s.get('curve_data', s))
                    else:
                        fence_id = id(s)
                    
                    if fence_id not in existing_ids:
                        self.selected_fences.append(s)
                        existing_ids.add(fence_id)
                    
                    # Close open shapes for polygon masking
                    if s['type'] in ['line', 'smart_line', 'polyline', 'smartline', 'curve']:
                        coords = s.get('coords', [])
                        if isinstance(coords, list): coords = np.array(coords)
                        if len(coords) > 0 and not np.array_equal(coords[0], coords[-1]):
                            s['coords'] = np.vstack([coords, coords[0]]) if isinstance(coords, np.ndarray) else coords + [coords[0]]
                
                # Store picker actors as selection actors
                for sid, act in selection_highlight_actors.items():
                    if sid not in {id(f.get('curve_data', f)) if f.get('source') == 'curve_tool' else id(f) for f in self.selected_fences}:
                        pass  # Skip actors for unselected
                self._selection_highlight_actors = list(selection_highlight_actors.values())
                
                self.update_fence_display()
                fc = len(self.selected_fences)
                shape_fc = sum(1 for f in self.selected_fences if f.get('source') != 'curve_tool')
                curve_fc = sum(1 for f in self.selected_fences if f.get('source') == 'curve_tool')
                tp = sum(len(f.get('coords', [])) for f in self.selected_fences)
                mt = "🔄 PERMANENT" if self.permanent_fence_mode else "TEMP"
                parts = []
                if shape_fc: parts.append(f"{shape_fc} shape(s)")
                if curve_fc: parts.append(f"{curve_fc} curve(s)")
                self.fence_status.setText(f"✅ {' + '.join(parts)} ({tp} pts) - {mt}")
                self.fence_status.setStyleSheet("QLabel { padding: 4px; background-color: #1b5e20; border-radius: 3px; color: #4caf50; font-weight: bold; }")
                
                try: self.app.vtk_widget.render()
                except Exception: pass
                self._fence_selection_dialog = None
                dialog.close(); dialog.deleteLater()

            ap.clicked.connect(apply_sel)
            bl.addWidget(ap)
            
            cl = QPushButton("Close")
            cl.setStyleSheet("QPushButton { background-color: #555555; color: white; font-size: 10px; padding: 6px 16px; border-radius: 3px; }")
            def on_cl():
                highlight_fence_in_3d(None)
                for act in selection_highlight_actors.values():
                    _rem_actor_from_renderer(act)
                selection_highlight_actors.clear()
                self._fence_selection_dialog = None; dialog.close()
            cl.clicked.connect(on_cl)
            bl.addWidget(cl)
            dlayout.addLayout(bl)
            dialog.show()
        except Exception as e:
            import traceback; traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Fence dialog failed:\n{str(e)}")

    def clear_fence_selection(self):
        """Clear fence selection AND remove the drawn shapes from the digitizer."""
        # ✅ Remove actual drawn shapes from digitizer (mirrors InsideFenceDialog temp-mode cleanup)
        if hasattr(self.app, 'digitizer') and self.app.digitizer and self.selected_fences:
            digitizer = self.app.digitizer
            for fence in list(self.selected_fences):
                fence_coords = fence.get('coords', [])
                for drawing in list(digitizer.drawings):
                    drawing_coords = drawing.get('coords', [])
                    if len(fence_coords) == len(drawing_coords) and all(
                            tuple(a) == tuple(b)
                            for a, b in zip(fence_coords, drawing_coords)):
                        digitizer._remove_drawing(drawing)
                        print(f"   🗑️ Removed drawn fence ({fence.get('type', 'unknown')})")
                        break
    
        self.selected_fences = []
        self.permanent_fence_mode = False
    
        self.fence_status.setText("❌ No fence selected")
        self.fence_status.setStyleSheet("""
            QLabel {
                padding: 4px; background-color: #2c2c2c;
                border-radius: 3px; color: #f44336;
            }
        """)
    
        self._clear_fence_highlights()  # removes blue + cyan VTK actors
        self.update_fence_display()
    
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass
    
        print("🗑️ Height fence: cleared selection + removed drawn shapes")

    def _clear_fence_highlights(self):
        # Remove hover highlight (yellow)
        if hasattr(self, '_hover_highlight_actor') and self._hover_highlight_actor:
            try:
                self.app.vtk_widget.renderer.RemoveViewProp(self._hover_highlight_actor)
                self._hover_highlight_actor = None
            except Exception:
                pass
    
        # Remove selection highlights (blue)
        if hasattr(self, '_selection_highlight_actors'):
            for actor in self._selection_highlight_actors:
                try:
                    self.app.vtk_widget.renderer.RemoveViewProp(actor)
                except Exception:
                    pass
            self._selection_highlight_actors = []
    
        # ✅ FIX BUG 3: at same indent level (was wrongly nested inside block above)
        if hasattr(self, '_classified_fence_actors'):
            for actor in self._classified_fence_actors:
                try:
                    if hasattr(self.app, 'digitizer') and \
                            hasattr(self.app.digitizer, 'overlay_renderer'):
                        self.app.digitizer.overlay_renderer.RemoveActor(actor)
                    else:
                        self.app.vtk_widget.renderer.RemoveViewProp(actor)
                except Exception:
                    pass
            self._classified_fence_actors = []
    
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass

    def update_fence_display(self):
        self.fence_count_badge.setText(str(len(self.selected_fences)) if self.selected_fences else "0")

    def _restore_highlights_from_data(self):
        try:
            if hasattr(self, '_selection_highlight_actors'):
                for actor in self._selection_highlight_actors:
                    try: self.app.vtk_widget.renderer.RemoveViewProp(actor)
                    except Exception: pass
            self._selection_highlight_actors = []
            if not self.selected_fences: return
            for shape in self.selected_fences:
                coords = shape.get('coords', [])
                if not coords: continue
                if hasattr(self.app, 'digitizer'):
                    ha = self.app.digitizer._make_polyline_actor(coords, color=(0, 0.5, 1), width=5)
                else:
                    import vtk
                    pts = vtk.vtkPoints()
                    for c in coords: pts.InsertNextPoint(c)
                    ln = vtk.vtkPolyLine(); ln.GetPointIds().SetNumberOfIds(len(coords))
                    for i in range(len(coords)): ln.GetPointIds().SetId(i, i)
                    cls = vtk.vtkCellArray(); cls.InsertNextCell(ln)
                    pd = vtk.vtkPolyData(); pd.SetPoints(pts); pd.SetLines(cls)
                    mp = vtk.vtkPolyDataMapper(); mp.SetInputData(pd)
                    ha = vtk.vtkActor(); ha.SetMapper(mp)
                    ha.GetProperty().SetColor(0, 0.5, 1); ha.GetProperty().SetLineWidth(5)
                self.app.vtk_widget.renderer.AddActor(ha)
                self._selection_highlight_actors.append(ha)
            self.app.vtk_widget.render()
        except Exception as e:
            print(f"⚠️ Restore highlights failed: {e}")

    def _points_inside_polygon(self, points, polygon_coords):
        from matplotlib.path import Path
        if isinstance(polygon_coords, list):
            poly_xy = np.array([(c[0], c[1]) for c in polygon_coords])
        else:
            poly_xy = polygon_coords[:, :2]
        points_xy = points[:, :2]
        min_x, min_y = np.min(poly_xy, axis=0)
        max_x, max_y = np.max(poly_xy, axis=0)
        bbox_mask = (points_xy[:, 0] >= min_x) & (points_xy[:, 0] <= max_x) & \
                    (points_xy[:, 1] >= min_y) & (points_xy[:, 1] <= max_y)
        inside = np.zeros(len(points), dtype=bool)
        if np.any(bbox_mask):
            poly_path = Path(poly_xy)
            inside[bbox_mask] = poly_path.contains_points(points_xy[bbox_mask])
        return inside

    def _highlight_classified_fences(self):
        if not self.selected_fences: return
        self._classified_fence_actors = []
        for fence in self.selected_fences:
            actor = fence.get('actor')
            if actor:
                try:
                    actor.GetProperty().SetColor(0, 1, 1)
                    actor.GetProperty().SetLineWidth(4)
                    fence['classified_fence'] = True
                    self._classified_fence_actors.append(actor)
                except Exception: pass
        try: self.app.vtk_widget.render()
        except Exception: pass 
    
    def populate_classes(self):
        """Populate class lists from Display Mode"""
        print(f"\n🔄 Populating ByClassHeightDialog...")
        
        self.from_list.clear()
        self.to_combo.clear()
        
        # Standard class labels
        STANDARD_LEVELS = {
            0: "Created", 1: "Ground", 2: "Low vegetation",
            3: "Medium vegetation", 4: "High vegetation", 5: "Buildings",
            6: "Water", 7: "Railways", 17: "Other Poles",
        }
        
        # Get classes from Display Mode
        class_list = []
        display_dialog = getattr(self.app, 'display_mode_dialog', 
                                 getattr(self.app, 'display_dialog', None))
        
        if display_dialog and hasattr(display_dialog, 'table'):
            table = display_dialog.table
            for row in range(table.rowCount()):
                try:
                    code_item = table.item(row, 1)
                    if not code_item:
                        continue
                    
                    code = int(code_item.text())
                    desc_item = table.item(row, 2)
                    desc = desc_item.text() if desc_item else ""
                    
                    lvl_item = table.item(row, 4)
                    lvl = lvl_item.text() if lvl_item else ""
                    
                    if not lvl or lvl.strip() == "":
                        lvl = STANDARD_LEVELS.get(code, str(code))
                    
                    color_item = table.item(row, 5)
                    if color_item:
                        qcolor = color_item.background().color()
                        color = (qcolor.red(), qcolor.green(), qcolor.blue())
                    else:
                        color = (128, 128, 128)
                    
                    class_list.append({
                        'code': code, 'desc': desc, 'lvl': lvl, 'color': color
                    })
                except Exception as e:
                    continue
        
        # Fallback: Use app's class_palette
        if not class_list and hasattr(self.app, 'class_palette'):
            for code in sorted(self.app.class_palette.keys()):
                entry = self.app.class_palette[code]
                desc = entry.get("description", "")
                lvl = entry.get("lvl", "")
                
                if not lvl or lvl.strip() == "":
                    lvl = STANDARD_LEVELS.get(code, str(code))
                
                color = entry.get("color", (128, 128, 128))
                
                class_list.append({
                    'code': code, 'desc': desc, 'lvl': lvl, 'color': color
                })
        
        if not class_list:
            print("⚠️ No classes found")
            return
        
        class_list.sort(key=lambda x: x['code'])
        
        # Add "Any class" option
        any_item = QListWidgetItem("🌐 Any class (convert all points)")
        any_item.setData(Qt.UserRole, None)
        any_item.setBackground(QColor(50, 50, 50))  # Dark gray like other items
        any_item.setForeground(QColor(255, 255, 255))
        self.from_list.addItem(any_item)

        # Populate with actual classes
        for cls in class_list:
            code = cls['code']
            lvl = cls['lvl']
            desc = cls['desc']
            color = cls['color']
            
            text = f"{code} - {lvl}" if lvl and lvl.strip() else f"{code}"
            if desc:
                text += f" ({desc})"
            
            icon = make_color_icon(color)
            
            item = QListWidgetItem(icon, text)
            item.setData(Qt.UserRole, code)
            self.from_list.addItem(item)
            
            self.to_combo.addItem(icon, text, code)

        # ── Populate Reference Class combo ───────────────────────────────────
        # Keep current selection if possible
        old_ref = self.ref_class_combo.currentData() if self.ref_class_combo.count() > 0 else 1
        self.ref_class_combo.clear()
        for cls in class_list:
            code = cls['code']
            lvl  = cls['lvl']
            desc = cls['desc']
            color = cls['color']
            text = f"{code} - {lvl}" if lvl and lvl.strip() else f"{code}"
            if desc:
                text += f" ({desc})"
            icon = make_color_icon(color)
            self.ref_class_combo.addItem(icon, text, code)

        # Default to Class 1 (Ground) if available, else restore old selection
        restore_idx = self.ref_class_combo.findData(old_ref if old_ref is not None else 1)
        if restore_idx < 0:
            restore_idx = self.ref_class_combo.findData(1)   # fallback: Ground
        if restore_idx >= 0:
            self.ref_class_combo.setCurrentIndex(restore_idx)
        # ─────────────────────────────────────────────────────────────────────

        print(f"✅ Populated ByClassHeightDialog with {len(class_list)} classes")
    
    def on_classes_changed(self):
        """Called when Display Mode loads new PTC file"""
        print("\n" + "="*60)
        print("🔄 BY CLASS HEIGHT DIALOG: Detected PTC change")
        print("="*60)
        
        # Save current selections
        selected_items = self.from_list.selectedItems()
        old_from_codes = [item.data(Qt.UserRole) for item in selected_items]
        old_to = self.to_combo.currentData()
        old_ref = self.ref_class_combo.currentData()
        old_min_height = self.min_height_spin.value()
        old_max_height = self.max_height_spin.value()
        
        # Rebuild lists
        self.populate_classes()
        
        # Restore selections
        for i in range(self.from_list.count()):
            item = self.from_list.item(i)
            if item.data(Qt.UserRole) in old_from_codes:
                item.setSelected(True)
        
        if old_to is not None:
            idx = self.to_combo.findData(old_to)
            if idx >= 0:
                self.to_combo.setCurrentIndex(idx)

        # Restore reference class selection
        if old_ref is not None:
            ref_idx = self.ref_class_combo.findData(old_ref)
            if ref_idx >= 0:
                self.ref_class_combo.setCurrentIndex(ref_idx)
        
        self.min_height_spin.setValue(old_min_height)
        self.max_height_spin.setValue(old_max_height)
        
        print("✅ ByClassHeightDialog updated")
        print("="*60 + "\n")
            
    def on_from_selection_changed(self):
        """Called when From class selection changes"""
        selected_items = self.from_list.selectedItems()
        
        if not selected_items:
            self.from_selection_label.setText("No classes selected")
            self.from_selection_label.setStyleSheet("color: #f44336; font-size: 9px; font-style: italic;")
        else:
            any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
            
            if any_selected:
                self.from_selection_label.setText("✅ Selected: Any class (will convert ALL points)")
                self.from_selection_label.setStyleSheet("color: #4caf50; font-size: 9px; font-weight: bold;")
            else:
                codes = [str(item.data(Qt.UserRole)) for item in selected_items]
                self.from_selection_label.setText(f"✅ Selected: Classes {', '.join(codes)}")
                self.from_selection_label.setStyleSheet("color: #4caf50; font-size: 9px; font-weight: bold;")
        
        self.on_class_selection_changed()

    def on_class_selection_changed(self):
        """Called when From class selection changes"""
        self.height_combo.clear()
        self.height_combo.addItem("Click 'Analyze Heights' to see options", None)
        self.height_info_label.setText("💡 Class changed. Click 'Analyze Heights' to recalculate.")
        self.height_info_label.setStyleSheet("color: #ff9800; font-size: 9px; font-style: italic;")

    def on_ref_class_changed(self, index):
        """Called when the Reference Class combo changes — force re-analysis."""
        self.height_combo.clear()
        self.height_combo.addItem("Click 'Analyze Heights' to see options", None)
        ref_text = self.ref_class_combo.currentText() if self.ref_class_combo.count() > 0 else "?"
        self.height_info_label.setText(
            f"⚠️ Reference class changed to [{ref_text}]. "
            "Click 'Analyze Heights' to recalculate heights."
        )
        self.height_info_label.setStyleSheet("color: #ff9800; font-size: 9px; font-style: italic;")
    
    def on_height_combo_changed(self, index):
        """Update spin boxes when dropdown selection changes"""
        data = self.height_combo.currentData()
        if data is not None and isinstance(data, dict):
            self.min_height_spin.setValue(data['min'])
            self.max_height_spin.setValue(data['max'])
    
    def analyze_heights(self):
        """Analyze actual height distribution — optionally restricted to fence"""
        selected_items = self.from_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select at least one From class")
            return
        
        any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
        if any_selected:
            QMessageBox.warning(self, "Invalid Selection", "Cannot analyze 'Any class' - select specific classes")
            return
        
        from_class = selected_items[0].data(Qt.UserRole)

        # ── Reference class (replaces the hardcoded ground_class = 1) ────────
        ground_class = self.ref_class_combo.currentData()
        if ground_class is None:
            ground_class = 1   # safety fallback
        ref_class_text = self.ref_class_combo.currentText()
        print(f"   📐 Reference class: {ground_class} ({ref_class_text})")
        # ─────────────────────────────────────────────────────────────────────

        classification = self.app.data.get("classification")
        xyz = self.app.data.get("xyz")
        if classification is None or xyz is None:
            return

        # Validate: reference class must differ from the From class
        if ground_class == from_class:
            QMessageBox.warning(
                self, "Invalid Reference Class",
                f"Reference class ({ground_class}) cannot be the same as the From class.\n"
                "Please choose a different reference class."
            )
            return

        # ✅ CHECK FENCE FILTER
        use_fence = self.fence_filter_enabled.isChecked() and len(self.selected_fences) > 0
        if self.fence_filter_enabled.isChecked() and not self.selected_fences:
            QMessageBox.warning(self, "No Fence", 
                "Fence filter is enabled but no fence selected.\n"
                "Please select a fence or disable the fence filter.")
            return
        
        print(f"\n{'='*60}")
        print(f"📊 ANALYZING HEIGHT DISTRIBUTION {'(FENCE-RESTRICTED)' if use_fence else ''}")
        print(f"{'='*60}")
        
        # Get reference-class points (user-selected, no longer hardcoded to Class 1)
        ground_mask = (classification == ground_class)
        ground_count = np.sum(ground_mask)
        if ground_count == 0:
            QMessageBox.warning(
                self, "No Reference Points",
                f"No points found for reference class {ground_class} ({ref_class_text}).\n"
                "Please choose a different reference class."
            )
            return
        
        # Get From class points
        from_class_mask = (classification == from_class)
        from_class_count = np.sum(from_class_mask)
        if from_class_count == 0:
            QMessageBox.warning(self, "No Source Points", f"No points of class {from_class} found")
            return
        
        # ✅ FENCE FILTER: restrict to points inside fence(s)
        if use_fence:
            from_class_xyz_all = xyz[from_class_mask]
            
            combined_inside = np.zeros(len(from_class_xyz_all), dtype=bool)
            for fence in self.selected_fences:
                fence_coords = fence['coords']
                if isinstance(fence_coords, list):
                    fence_coords = np.array(fence_coords)
                inside = self._points_inside_polygon(from_class_xyz_all, fence_coords)
                combined_inside |= inside
            
            from_class_xyz = from_class_xyz_all[combined_inside]
            fence_label_text = f" (inside {len(self.selected_fences)} fence(s))"
            
            if len(from_class_xyz) == 0:
                QMessageBox.warning(self, "No Points", 
                    f"No class {from_class} points found inside fence")
                return
            
            # Also filter ground to fence area for better local reference
            ground_xyz_all = xyz[ground_mask]
            ground_inside = np.zeros(len(ground_xyz_all), dtype=bool)
            for fence in self.selected_fences:
                fence_coords = fence['coords']
                if isinstance(fence_coords, list):
                    fence_coords = np.array(fence_coords)
                inside = self._points_inside_polygon(ground_xyz_all, fence_coords)
                ground_inside |= inside
            
            ground_xyz = ground_xyz_all[ground_inside] if np.sum(ground_inside) > 0 else ground_xyz_all
            print(f"   Ground points in fence: {np.sum(ground_inside):,}")
        else:
            from_class_xyz = xyz[from_class_mask]
            ground_xyz = xyz[ground_mask]
            fence_label_text = ""
        
        # Build KDTree
        ground_xy = ground_xyz[:, :2]
        tree = cKDTree(ground_xy)
        
        # Query From class points
        from_class_xy = from_class_xyz[:, :2]
        distances, indices = tree.query(from_class_xy, k=1)
        
        # Calculate heights
        from_class_z = from_class_xyz[:, 2]
        nearest_ground_z = ground_xyz[indices, 2]
        heights = from_class_z - nearest_ground_z
        
        min_h = np.min(heights)
        max_h = np.max(heights)
        mean_h = np.mean(heights)
        median_h = np.median(heights)
        
        # Create height options — use actual min_h so ranges reflect real data
        percentiles = [25, 50, 75, 90, 95, 99]
        height_options = []
        for p in percentiles:
            threshold = np.percentile(heights, p)
            lower     = np.percentile(heights, 100 - p)   # symmetric lower bound
            actual_min = float(min_h)
            count = np.sum((heights >= actual_min) & (heights <= threshold))
            percentage = (count / len(heights)) * 100
            height_options.append({
                'percentile': p,
                'min': round(actual_min, 3),
                'max': round(float(threshold), 3),
                'count': count, 'percentage': percentage
            })
        
        print(f"   Points analyzed: {len(from_class_xyz):,}{fence_label_text}")
        print(f"   Min: {min_h:.3f}m, Max: {max_h:.3f}m, Mean: {mean_h:.3f}m")
        print(f"{'='*60}\n")
        
        # Populate dropdown — labels now show the real min, not a hardcoded 0
        self.height_combo.clear()
        for opt in height_options:
            label = (f"{opt['min']:.2f}m → {opt['max']:.2f}m  "
                     f"— {opt['percentile']}th pct  ({opt['count']:,} pts, {opt['percentage']:.0f}%)")
            self.height_combo.addItem(label, opt)
        
        self.height_combo.insertSeparator(self.height_combo.count())
        
        # Common relative ranges — only add if they fall within actual data range
        common_ranges = [
            (min_h, max_h),          # full range
            (min_h, np.percentile(heights, 50)),   # lower half
            (0.0, 0.5), (0.0, 1.0), (0.0, 2.0),
            (0.0, 5.0), (0.0, 10.0),
            (0.2, 2.0), (2.0, 10.0),
        ]
        seen_ranges = set()
        for min_r, max_r in common_ranges:
            min_r = round(float(min_r), 3)
            max_r = round(float(max_r), 3)
            key = (min_r, max_r)
            if key in seen_ranges:
                continue
            seen_ranges.add(key)
            if min_r >= max_r:
                continue
            if max_r > max_h + 0.01:   # skip ranges beyond actual data
                continue
            count = np.sum((heights >= min_r) & (heights <= max_r))
            percentage = (count / len(heights)) * 100
            label = f"{min_r:.2f}m → {max_r:.2f}m  — {count:,} pts ({percentage:.0f}%)"
            self.height_combo.addItem(label, {'min': min_r, 'max': max_r})
        
        # Default selection: 75th percentile (index 2)
        if len(height_options) > 2:
            self.height_combo.setCurrentIndex(2)
        
        # ✅ Auto-fill spinboxes with the actual analyzed min/max
        self.min_height_spin.setValue(round(float(min_h), 3))
        self.max_height_spin.setValue(round(float(max_h), 3))
        
        self.height_info_label.setText(
            f"✅ Analyzed {len(from_class_xyz):,} points{fence_label_text} | "
            f"Ref: [{ref_class_text}] | Min: {min_h:.3f}m | Max: {max_h:.3f}m"
        )
        self.height_info_label.setStyleSheet("color: #4caf50; font-size: 9px; font-weight: bold;")
        
        QMessageBox.information(self, "Height Analysis Complete", 
            f"Analyzed {len(from_class_xyz):,} points{fence_label_text}\n"
            f"Reference class: {ref_class_text}\n"
            f"Min: {min_h:.3f}m, Max: {max_h:.3f}m above reference\n"
            f"Select a height range from dropdown")
        
    def preview_conversion(self):
        """Preview conversion"""
        selected_items = self.from_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select at least one From class")
            return

        any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)

        if any_selected:
            from_classes = None
            from_display = "All classes"
        else:
            from_classes = [item.data(Qt.UserRole) for item in selected_items]
            from_display = ", ".join(str(c) for c in from_classes)

        to_class = self.to_combo.currentData()
        ground_class = self.ref_class_combo.currentData() or 1
        ref_class_text = self.ref_class_combo.currentText()
        min_height = self.min_height_spin.value()
        max_height = self.max_height_spin.value()
        
        if to_class is None:
            QMessageBox.warning(self, "No Selection", "Please select a To class")
            return
        
        if from_classes and to_class in from_classes:
            QMessageBox.warning(self, "Invalid Selection", f"Cannot convert class {to_class} to itself")
            return
                
        try:
            affected_count = self._calculate_conversion(
                from_classes, to_class, ground_class, min_height, max_height, preview=True
            )
            
            if affected_count is None:
                return
            
            self.preview_label.setText(
                f"📊 Preview: {affected_count:,} points would be converted\n"
                f"From: {from_display} → To: Class {to_class}\n"
                f"Height: {min_height}m - {max_height}m above [{ref_class_text}]"
            )
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #2196f3;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 8px;
                    background-color: #1a237e;
                    border-radius: 3px;
                }
            """)
            
        except Exception as e:
            QMessageBox.critical(self, "Preview Failed", str(e))
    
    def perform_conversion(self):
        """Perform conversion"""
        selected_items = self.from_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "No Selection", "Please select at least one From class")
            return

        any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)

        if any_selected:
            from_classes = None
            from_display = "All classes"
        else:
            from_classes = [item.data(Qt.UserRole) for item in selected_items]
            from_display = ", ".join(str(c) for c in from_classes)

        to_class = self.to_combo.currentData()
        ground_class = self.ref_class_combo.currentData() or 1
        ref_class_text = self.ref_class_combo.currentText()
        min_height = self.min_height_spin.value()
        max_height = self.max_height_spin.value()
        
        if to_class is None:
            QMessageBox.warning(self, "No Selection", "Please select a To class")
            return
        
        if from_classes and to_class in from_classes:
            QMessageBox.warning(self, "Invalid Selection", f"Cannot convert class {to_class} to itself")
            return

        # Guard: reference class must not be the same as a From class
        if from_classes and ground_class in from_classes:
            QMessageBox.warning(
                self, "Invalid Reference Class",
                f"Reference class ({ground_class}) cannot be one of the From classes.\n"
                "Please select a different reference class."
            )
            return
        
        # ✅ CHECK FENCE
        use_fence = self.fence_filter_enabled.isChecked() and len(self.selected_fences) > 0
        if self.fence_filter_enabled.isChecked() and not self.selected_fences:
            QMessageBox.warning(self, "No Fence", 
                "Fence filter is enabled but no fence selected.")
            return
        
        fence_text = ""
        if use_fence:
            fence_text = f"\nInside {len(self.selected_fences)} fence(s)"
        
        msg = (
            f"Convert {from_display} → class {to_class}\n"
            f"Height: {min_height}m - {max_height}m above [{ref_class_text}]{fence_text}"
        )
        
        reply = QMessageBox.question(self, "Confirm Conversion", msg,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            converted_count = self._calculate_conversion(
                from_classes, to_class, ground_class, min_height, max_height, preview=False
            )
            
            if converted_count is None or converted_count == 0:
                QMessageBox.information(self, "No Points", "No points found to convert")
                return
            
            # ✅ Store conversion info
            if from_classes:
                self._last_conversion_info = {
                    'from_classes': from_classes,
                    'to_class': to_class,
                    'count': converted_count
                }
            
            self.preview_label.setText(f"✅ Converted {converted_count:,} points")
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 8px;
                    background-color: #1b5e20;
                    border-radius: 3px;
                }
            """)
            
            if self.ribbon_parent:
                self.ribbon_parent.update_status(f"✅ Converted {converted_count:,} points", "success")
            
            # ✅ FENCE CLEANUP after successful conversion
            if use_fence:
                self._clear_fence_highlights()          # remove blue actors
                self._highlight_classified_fences()     # recolour drawn rect → cyan
 
                if hasattr(self.app, 'digitizer') and self.app.digitizer:
                    try:
                        self.app.digitizer.rebind_drawings()
                        print("   🖊️ Drawing actors rebound to overlay after fence conversion")
                    except Exception as _rb_err:
                        print(f"   ⚠️ rebind_drawings failed: {_rb_err}")
 
                # ✅ FIX: ALWAYS clear selected_fences after classification.
                # This mirrors InsideFenceDialog behaviour ("dialog can't remember
                # selected fence after classification"). Without this, showEvent
                # calls _restore_highlights_from_data() when the QMessageBox
                # closes and the blue box immediately reappears.
                #
                # The drawn rectangle (orange/cyan outline) stays visible.
                # If temp mode, also delete the drawing from the digitizer.
                if not self.permanent_fence_mode:
                    if hasattr(self.app, 'digitizer'):
                        for fence in list(self.selected_fences):
                            for drawing in list(self.app.digitizer.drawings):
                                fc = fence.get('coords', [])
                                dc = drawing.get('coords', [])
                                if len(fc) == len(dc) and all(
                                        tuple(a) == tuple(b) for a, b in zip(fc, dc)):
                                    self.app.digitizer._remove_drawing(drawing)
                                    break
 
                self.selected_fences = []           # ← KEY LINE (both modes)
                self.update_fence_display()
                self.fence_status.setText(
                    "✅ Classified — select a fence again for next run"
                )
                self.fence_status.setStyleSheet("""
                    QLabel {
                        padding: 4px; background-color: #1b3a20;
                        border-radius: 3px; color: #81c784; font-size: 9px;
                    }
                """)
            
            QMessageBox.information(self, "Conversion Complete",
                                   f"✅ Successfully converted {converted_count:,} points")
            
        except Exception as e:
            error_msg = f"Conversion failed: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            
    def _calculate_conversion(self, from_classes, to_class, ground_class, 
                         min_height, max_height, preview=False):
        """Calculate/perform height-based conversion"""
        classification = self.app.data.get("classification")
        xyz = self.app.data.get("xyz")
        
        if classification is None or xyz is None:
            return None
        
        print(f"\n{'='*60}")
        print(f"📏 HEIGHT-BASED CONVERSION")
        print(f"   Reference class (baseline): {ground_class}")
        print(f"{'='*60}")
        
        # Get reference-class points (previously always Class 1 / Ground)
        ground_mask = (classification == ground_class)
        ground_count = np.sum(ground_mask)
        
        if ground_count == 0:
            QMessageBox.warning(
                self, "No Reference Points",
                f"No points found for reference class {ground_class}.\n"
                "Please select a different reference class or load more data."
            )
            return None
        
        # Get From class points
        if from_classes is None:
            from_class_mask = (classification != to_class)
        else:
            from_class_mask = np.isin(classification, from_classes)

        from_class_count = np.sum(from_class_mask)
        
        if from_class_count == 0:
            return 0
        
        # Build KDTree
        # ✅ Get indices for tracking
        from_class_indices = np.where(from_class_mask)[0]
        from_class_xyz = xyz[from_class_mask]
        
        # ✅ FENCE FILTER: restrict to points inside fence(s)
        use_fence = self.fence_filter_enabled.isChecked() and len(self.selected_fences) > 0
        if use_fence:
            combined_inside = np.zeros(len(from_class_xyz), dtype=bool)
            for fence in self.selected_fences:
                fence_coords = fence['coords']
                if isinstance(fence_coords, list):
                    fence_coords = np.array(fence_coords)
                inside = self._points_inside_polygon(from_class_xyz, fence_coords)
                combined_inside |= inside
            
            from_class_xyz = from_class_xyz[combined_inside]
            from_class_indices = from_class_indices[combined_inside]
            
            print(f"   Fence filter: {np.sum(combined_inside):,} of {from_class_count:,} pts inside fence")
            
            if len(from_class_xyz) == 0:
                print("   ⚠️ No points inside fence")
                if preview:
                    return 0
                return 0
            
            # Use fence-local ground for better height reference
            ground_xyz_all = xyz[ground_mask]
            ground_inside_mask = np.zeros(len(ground_xyz_all), dtype=bool)
            for fence in self.selected_fences:
                fence_coords = fence['coords']
                if isinstance(fence_coords, list):
                    fence_coords = np.array(fence_coords)
                inside = self._points_inside_polygon(ground_xyz_all, fence_coords)
                ground_inside_mask |= inside
            ground_xyz = ground_xyz_all[ground_inside_mask] if np.sum(ground_inside_mask) > 0 else ground_xyz_all
        else:
            ground_xyz = xyz[ground_mask]
        
        # Build KDTree
        ground_xy = ground_xyz[:, :2]
        tree = cKDTree(ground_xy)
        
        # Query From class points
        from_class_xy = from_class_xyz[:, :2]
        
        distances, indices = tree.query(from_class_xy, k=1)
        
        # Calculate heights
        from_class_z = from_class_xyz[:, 2]
        nearest_ground_z = ground_xyz[indices, 2]
        heights = from_class_z - nearest_ground_z
        
        # Points within height range
        # Points within height range
        height_mask = (heights >= min_height) & (heights <= max_height)
        in_range_count = np.sum(height_mask)
        
        print(f"   Points in range: {in_range_count:,}")
        
        if preview:
            print(f"{'='*60}\n")
            return in_range_count
        
        if in_range_count == 0:
            print(f"{'='*60}\n")
            return 0
        
        # Build final mask for main dataset
        # ✅ FIXED: Use from_class_indices (already fence-filtered if applicable)
        final_mask = np.zeros(len(classification), dtype=bool)
        convert_indices = from_class_indices[height_mask]
        final_mask[convert_indices] = True
        
        # Save undo
        old_classes = classification[final_mask].copy()
        
        # Convert
        classification[final_mask] = to_class
        
        
        new_classes_arr = np.full(np.sum(final_mask), to_class, dtype=classification.dtype)
        undo_step = {
            "mask": final_mask.copy(),
            "oldclasses": old_classes,
            "old_classes": old_classes,
            "newclasses": new_classes_arr,
            "new_classes": new_classes_arr
        }
        
        # ✅ FIX: Correct stack attribute names
        if hasattr(self.app, 'undostack'):
            self.app.undostack.append(undo_step)
        elif hasattr(self.app, 'undo_stack'):
            self.app.undo_stack.append(undo_step)
        else:
            print("⚠️ No undo stack found on app!")
        
        if hasattr(self.app, 'redostack'):
            self.app.redostack.clear()
        elif hasattr(self.app, 'redo_stack'):
            self.app.redo_stack.clear()
        from gui.memory_manager import trim_undo_stack
        trim_undo_stack(self.app)

        print(f"   ✅ Converted {in_range_count:,} points")
        print(f"{'='*60}\n")
        
        # ✅ Store conversion info for TARGETED refresh
        self._last_conversion_info = {
            'from_classes': from_classes if from_classes else list(np.unique(old_classes)),
            'to_class': to_class,
            'converted_indices': convert_indices,  # ✅ NEW: Store exact indices
            'count': in_range_count
        }
        
        # AFTER
        current_display_mode = getattr(self.app, 'display_mode', 'class')
        print(f"   🔄 Post-conversion refresh (display_mode='{current_display_mode}')...")

        # ⚡ For class mode, keep the existing actor alive so _fast_classification_inject
        #    can patch it in-place (O(changed) instead of O(all)).
        #    Only wipe for shaded_class/other modes where a full rebuild is needed anyway.
        if current_display_mode not in ("shaded_class", "class"):
            if hasattr(self.app, 'vtk_widget'):
                if hasattr(self.app.vtk_widget, 'actors'):
                    old_actors = self.app.vtk_widget.actors
                    if isinstance(old_actors, dict):
                        for actor in old_actors.values():
                            try:
                                self.app.vtk_widget.renderer.RemoveActor(actor)
                            except Exception:
                                pass
                        old_actors.clear()
                        print("      ✅ Cleared actor cache")
                if hasattr(self.app.vtk_widget, 'actor'):
                    self.app.vtk_widget.actor = None

        # Step 2: Now call Display Mode to rebuild from scratch
        display_dialog = getattr(self.app, 'display_mode_dialog', 
                                getattr(self.app, 'display_dialog', None))
        # if display_dialog and hasattr(display_dialog, 'on_apply'):
        #     display_dialog.on_apply()
        #     print("   ✅ Display Mode rebuilt actors (forced full rebuild)")
        # else:
            
        self.app._conversion_just_happened = True
        # Fallback
        self._refresh_after_classification() 

        # Refresh cross-sections if needed
        if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
            for view_idx in list(self.app.section_vtks.keys()):
                try:
                    if hasattr(self.app, '_refresh_single_section_view'):
                        self.app._refresh_single_section_view(view_idx)
                except Exception as e:
                    print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

        # Update point count widget
        if hasattr(self.app, 'point_count_widget'):
            self.app.point_count_widget.schedule_update()
     
        return in_range_count

    def _fast_classification_inject(self):
        """
        Fast classification refresh using the same pipeline as interactive classify.
        This avoids stale actor-array indexing after undo/redo.
        """
        import time
        import numpy as np

        t0 = time.perf_counter()

        info = getattr(self, '_last_conversion_info', None)
        convert_indices = info.get('converted_indices') if info else None
        to_class = info.get('to_class') if info else None

        try:
            if convert_indices is None or to_class is None:
                return False
            if not hasattr(self.app, 'data') or self.app.data is None:
                return False

            classification = self.app.data.get('classification')
            if classification is None:
                return False

            total_pts = len(classification)
            if total_pts == 0:
                return False

            convert_indices = np.asarray(convert_indices, dtype=np.int64)
            valid = (convert_indices >= 0) & (convert_indices < total_pts)
            if not np.any(valid):
                return False

            changed_mask = np.zeros(total_pts, dtype=bool)
            changed_mask[convert_indices[valid]] = True

            from gui.unified_actor_manager import fast_classify_update
            ok = fast_classify_update(self.app, changed_mask, int(to_class))
            if not ok:
                return False

            # Keep section mirrors and statistics in sync through app signal bus.
            try:
                self.app.classification_finished.emit(changed_mask)
            except Exception:
                pass

            elapsed = (time.perf_counter() - t0) * 1000
            print(f"   fast_inject unified update: {int(np.count_nonzero(changed_mask)):,} pts [{elapsed:.1f} ms]")
            return True

        except Exception as e:
            print(f"   _fast_classification_inject failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _refresh_after_classification(self):
        """
        Refresh the view respecting the CURRENT display_mode.
        ✅ FIXED: Forces mesh REBUILD if points are converted to a HIDDEN class.
        """
        display_mode = getattr(self.app, 'display_mode', 'class')
        print(f"   📍 Refreshing after classification: display_mode='{display_mode}'")
        try:
            if display_mode == "shaded_class":
                from gui.shading_display import (
                    get_cache, refresh_shaded_after_classification_fast,
                    clear_shading_cache, update_shaded_class
                )
                
                cache = get_cache()
                
                # 1. Get current visibility set
                saved_vis = getattr(cache, 'visible_classes_set', None)
                if saved_vis is None or len(saved_vis) == 0:
                    saved_vis = getattr(self.app, '_shading_visible_classes', None)
                if saved_vis is None or len(saved_vis) == 0:
                    saved_vis = {
                        int(c) for c, e in self.app.class_palette.items()
                        if e.get("show", True)
                    }
                saved_vis = saved_vis.copy()
                
                print(f"   📍 Shading visibility: {sorted(saved_vis)}")
                
                # Force palette to match saved visibility
                for c in self.app.class_palette:
                    self.app.class_palette[c]["show"] = (int(c) in saved_vis)
                
                # 2. ✅ CRITICAL FIX: Check if we converted points INTO a hidden class
                target_is_hidden = False
                if hasattr(self, '_last_conversion_info') and self._last_conversion_info:
                    to_class = self._last_conversion_info.get('to_class')
                    if to_class is not None:
                        if int(to_class) not in saved_vis:
                            target_is_hidden = True
                            print(f"   🙈 Target Class {to_class} is UNCHECKED/HIDDEN")
                
                # 3. Check if any visible points remain at all
                classification = self.app.data.get("classification")
                has_visible_points = False
                if classification is not None:
                    for vc in saved_vis:
                        if np.sum(classification == vc) > 0:
                            has_visible_points = True
                            break
                
                # 4. DECISION LOGIC
                if not has_visible_points:
                    # Case A: Everything is gone
                    print(f"   🖤 No visible points remain — clearing mesh")
                    clear_shading_cache("all visible points converted away")
                    update_shaded_class(
                        self.app,
                        getattr(self.app, "last_shade_azimuth", 45.0),
                        getattr(self.app, "last_shade_angle", 45.0),
                        getattr(self.app, "shade_ambient", 0.2),
                        force_rebuild=True
                    )

                elif target_is_hidden:
                    # Case B: ✅ Converted to hidden class -> MUST REBUILD GEOMETRY
                    # Fast color swap is NOT enough because geometry must be removed
                    print(f"   ♻️ Converted to hidden class — FORCING MESH REBUILD to hide geometry")
                    clear_shading_cache("converted to hidden class")
                    update_shaded_class(
                        self.app,
                        getattr(self.app, "last_shade_azimuth", 45.0),
                        getattr(self.app, "last_shade_angle", 45.0),
                        getattr(self.app, "shade_ambient", 0.2),
                        force_rebuild=True
                    )
                    
                else:
                    # Case C: Converted to visible class -> FAST COLOR SWAP (GPU)
                    print(f"   ⚡ Target class is visible — using fast color injection")
                    
                    # Pull the changed point indices
                    info = getattr(self, '_last_conversion_info', None)
                    changed_mask = None
                    if info and 'converted_indices' in info:
                        changed_mask = np.zeros(len(self.app.data["xyz"]), dtype=bool)
                        changed_mask[info['converted_indices']] = True
                    
                    refresh_shaded_after_classification_fast(self.app, changed_mask=changed_mask)
                
                print(f"   ✅ Refreshed in shaded_class mode")
                
            elif display_mode == "class":
                # ⚡ FAST PATH — patch only the converted points, same strategy as undo's fast_undo_update
                fast_ok = self._fast_classification_inject()
                if not fast_ok:
                    # Fallback: full rebuild (slow, only if fast path is unavailable)
                    from gui.class_display import update_class_mode
                    update_class_mode(self.app, force_refresh=True)
                print("   ✅ Refreshed in class mode")
            else:
                from gui.pointcloud_display import update_pointcloud
                update_pointcloud(self.app, display_mode)
                print(f"   ✅ Refreshed in {display_mode} mode")
                
        except Exception as e:
            print(f"   ⚠️ Refresh failed ({e}), falling back to class mode")
            import traceback
            traceback.print_exc()
            try:
                from gui.class_display import update_class_mode
                update_class_mode(self.app, force_refresh=True)
            except Exception as e2:
                print(f"   ❌ Fallback also failed: {e2}")
        
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass
    
    def _refresh_all_views(self):
        """
        ✅ ULTIMATE FIXED: Combines fence dialog smart refresh + force rebuild fallback
        - First tries smart update (like fence dialog - prevents blank screens)
        - If that fails, forces full rebuild by clearing actors
        - Guaranteed to work in all scenarios!
        """
        print(f"\n🔄 REFRESHING VIEWS (smart + visibility-aware)...")
        
        # ✅ CRITICAL: Save camera position BEFORE any updates
        saved_camera = None
        if hasattr(self.app, 'vtk_widget') and hasattr(self.app.vtk_widget, 'renderer'):
            try:
                camera = self.app.vtk_widget.renderer.GetActiveCamera()
                if camera:
                    saved_camera = {
                        'position': tuple(camera.GetPosition()),
                        'focal_point': tuple(camera.GetFocalPoint()),
                        'view_up': tuple(camera.GetViewUp()),
                        'parallel_scale': camera.GetParallelScale(),
                        'parallel_projection': camera.GetParallelProjection(),
                    }
                    print(f"   📷 Camera saved: pos={saved_camera['position'][:2]}, scale={saved_camera['parallel_scale']:.2f}")
            except Exception as e:
                print(f"   ⚠️ Camera save failed: {e}")
        
        # ✅ DETECT MODE: By-class actors or unified actor?
        has_by_class_actors = False
        if hasattr(self.app, 'vtk_widget') and hasattr(self.app.vtk_widget, 'actors'):
            if isinstance(self.app.vtk_widget.actors, dict):
                for key in self.app.vtk_widget.actors.keys():
                    if 'class_' in str(key).lower():
                        has_by_class_actors = True
                        break
        
        update_success = False
        
        # ========================================
        # METHOD 1: SMART UPDATE (FROM FENCE DIALOG)
        # ========================================
        if has_by_class_actors:
            print(f"   🔍 Detected BY-CLASS actor mode - rebuilding affected actors...")
            
            try:
                display_dialog = getattr(self.app, 'display_mode_dialog', 
                                        getattr(self.app, 'display_dialog', None))
                
                if display_dialog:
                    # Try various display dialog methods
                    if hasattr(display_dialog, 'update_display_mode'):
                        display_dialog.update_display_mode()
                        print(f"   ✅ Called display_dialog.update_display_mode()")
                        update_success = True
                    
                    elif hasattr(display_dialog, 'refresh_actors'):
                        display_dialog.refresh_actors()
                        print(f"   ✅ Called display_dialog.refresh_actors()")
                        update_success = True
                    
                    elif hasattr(display_dialog, 'apply_class_filter'):
                        display_dialog.apply_class_filter()
                        print(f"   ✅ Called display_dialog.apply_class_filter()")
                        update_success = True
                    
                    elif hasattr(display_dialog, 'apply_btn'):
                        display_dialog.apply_btn.click()
                        print(f"   ✅ Triggered display_dialog.apply_btn.click()")
                        update_success = True
            
            except Exception as e:
                print(f"   ⚠️ Display mode refresh failed: {e}")
        
        # ✅ UNIFIED ACTOR MODE: Try smart update
        if not update_success:
            print(f"   🔍 Using unified actor mode - trying smart update...")
            
            # Try smart_update_colors
            try:
                from gui.pointcloud_display import smart_update_colors
                smart_update_colors(self.app, None)
                print(f"   ✅ Main view updated (smart_update_colors)")
                update_success = True
            except ImportError:
                print(f"   ⚠️ smart_update_colors not found")
            except Exception as e:
                print(f"   ⚠️ smart_update_colors failed: {e}")
            
            # Try direct VTK color update
            if not update_success:
                try:
                    if self._force_vtk_color_update():
                        print(f"   ✅ Main view updated (direct VTK with visibility)")
                        update_success = True
                except Exception:
                    pass
        
        # ========================================
        # METHOD 2: FORCE REBUILD (FALLBACK)
        # ========================================
        if not update_success:
            print(f"   ⚠️ Smart update failed - forcing full rebuild...")
            
            if hasattr(self.app, 'vtk_widget'):
                # Remove all actors to force rebuild
                if hasattr(self.app.vtk_widget, 'actor') and self.app.vtk_widget.actor:
                    old_actor = self.app.vtk_widget.actor
                    self.app.vtk_widget.actor = None
                    if hasattr(self.app.vtk_widget, 'renderer'):
                        self.app.vtk_widget.renderer.RemoveActor(old_actor)
                    print(f"      ✅ Removed unified actor")
                
                # Clear actors dict
                if hasattr(self.app.vtk_widget, 'actors'):
                    old_actors = self.app.vtk_widget.actors
                    if isinstance(old_actors, dict):
                        for actor in old_actors.values():
                            if actor and hasattr(self.app.vtk_widget, 'renderer'):
                                self.app.vtk_widget.renderer.RemoveActor(actor)
                        old_actors.clear()
                        print(f"      ✅ Cleared {len(old_actors)} actors")
            
            # Call update_class_mode - will detect missing actors and do full rebuild
            try:
                from gui.class_display import update_class_mode
                update_class_mode(self.app, force_refresh=True)
                print(f"   ✅ Main view refreshed (forced rebuild)")
                update_success = True
            except Exception as e:
                print(f"      ❌ Full rebuild failed: {e}")
        
        # ========================================
        # RESTORE & FINALIZE
        # ========================================
        
        # ✅ CRITICAL: Restore camera position IMMEDIATELY
        if saved_camera:
            try:
                camera = self.app.vtk_widget.renderer.GetActiveCamera()
                camera.SetPosition(saved_camera['position'])
                camera.SetFocalPoint(saved_camera['focal_point'])
                camera.SetViewUp(saved_camera['view_up'])
                camera.SetParallelScale(saved_camera['parallel_scale'])
                
                if saved_camera['parallel_projection']:
                    camera.ParallelProjectionOn()
                else:
                    camera.ParallelProjectionOff()
                
                self.app.vtk_widget.renderer.ResetCameraClippingRange()
                print(f"   📷✅ Camera restored")
            except Exception as e:
                print(f"   ⚠️ Camera restore failed: {e}")
        
        # Refresh cross-sections
        if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
            for view_idx in list(self.app.section_vtks.keys()):
                try:
                    if hasattr(self.app, '_refresh_single_section_view'):
                        self.app._refresh_single_section_view(view_idx)
                except Exception as e:
                    print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")
        
        # Update point statistics
        if hasattr(self.app, 'point_count_widget'):
            try:
                self.app.point_count_widget.schedule_update()
            except Exception:
                pass
        
        # ✅ Force final render
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass
        
        mode_str = "by-class" if has_by_class_actors else "unified"
        print(f"✅ REFRESH COMPLETE ({mode_str} mode, success: {update_success})\n")


    def _force_vtk_color_update(self):
        """
        Direct VTK color update with visibility awareness
        Called when smart_update_colors is not available
        """
        try:
            if not hasattr(self.app, 'vtk_widget'):
                return False
            
            vtk_widget = self.app.vtk_widget
            
            # Get the actor (unified mode)
            actor = None
            if hasattr(vtk_widget, 'actor') and vtk_widget.actor:
                actor = vtk_widget.actor
            elif hasattr(vtk_widget, 'actors') and isinstance(vtk_widget.actors, dict):
                # Try to find a unified actor
                for key, act in vtk_widget.actors.items():
                    if 'unified' in str(key).lower() or key == 'main':
                        actor = act
                        break
            
            if not actor:
                return False
            
            # Get mapper and update colors
            mapper = actor.GetMapper()
            if not mapper:
                return False
            
            # Get classification data
            classification = self.app.data.get("classification")
            if classification is None:
                return False
            
            # Get visibility mask if available
            visible_mask = None
            if hasattr(self.app, 'get_visible_points_mask'):
                visible_mask = self.app.get_visible_points_mask()
            
            # Update colors based on classification
            from vtk import vtkUnsignedCharArray
            colors = vtkUnsignedCharArray()
            colors.SetNumberOfComponents(3)
            colors.SetName("Colors")
            
            class_palette = getattr(self.app, 'class_palette', {})
            
            for i, cls in enumerate(classification):
                # Check visibility
                if visible_mask is not None and not visible_mask[i]:
                    # Make invisible points black or very dark
                    colors.InsertNextTuple3(20, 20, 20)
                else:
                    # Use class color
                    color_entry = class_palette.get(int(cls), {'color': (128, 128, 128)})
                    color = color_entry.get('color', (128, 128, 128))
                    colors.InsertNextTuple3(int(color[0]), int(color[1]), int(color[2]))
            
            # Update the polydata
            polydata = mapper.GetInput()
            if polydata:
                polydata.GetPointData().SetScalars(colors)
                polydata.Modified()
                mapper.Modified()
                actor.Modified()
            
            return True
            
        except Exception as e:
            print(f"      ❌ Direct VTK update failed: {e}")
            return False


    def _save_camera_state(self):
        """Save camera state"""
        if not hasattr(self.app, 'vtk_widget'):
            return None
        if not hasattr(self.app.vtk_widget, 'renderer'):
            return None
        
        try:
            camera = self.app.vtk_widget.renderer.GetActiveCamera()
            if camera:
                return {
                    'position': tuple(camera.GetPosition()),
                    'focal_point': tuple(camera.GetFocalPoint()),
                    'view_up': tuple(camera.GetViewUp()),
                    'parallel_scale': camera.GetParallelScale(),
                    'parallel_projection': camera.GetParallelProjection(),
                }
        except Exception:
            pass
        return None


    def _restore_camera_state(self, saved_camera):
        """Restore camera state"""
        if not saved_camera:
            return
        
        try:
            camera = self.app.vtk_widget.renderer.GetActiveCamera()
            camera.SetPosition(saved_camera['position'])
            camera.SetFocalPoint(saved_camera['focal_point'])
            camera.SetViewUp(saved_camera['view_up'])
            camera.SetParallelScale(saved_camera['parallel_scale'])
            
            if saved_camera['parallel_projection']:
                camera.ParallelProjectionOn()
            else:
                camera.ParallelProjectionOff()
            
            self.app.vtk_widget.renderer.ResetCameraClippingRange()
        except Exception:
            pass



    def _debug_vtk_structure(self):
        """Debug: Show VTK structure"""
        print("\n" + "="*60)
        print("🔍 DEBUGGING VTK STRUCTURE")
        print("="*60)
        
        if not hasattr(self.app, 'vtk_widget'):
            print("❌ No vtk_widget found")
            return
        
        vtk_widget = self.app.vtk_widget
        print(f"✅ vtk_widget exists: {type(vtk_widget)}")
        
        # Check all attributes
        print("\n📋 vtk_widget attributes containing 'actor':")
        for attr in dir(vtk_widget):
            if 'actor' in attr.lower():
                try:
                    value = getattr(vtk_widget, attr)
                    print(f"   - {attr}: {type(value)}")
                    
                    if attr == 'actors' and isinstance(value, dict):
                        print(f"     → actors dict keys: {list(value.keys())}")
                        for key, actor in value.items():
                            if actor:
                                try:
                                    mapper = actor.GetMapper()
                                    if mapper:
                                        input_data = mapper.GetInput()
                                        if input_data:
                                            pts = input_data.GetNumberOfPoints()
                                            print(f"        '{key}': {pts:,} points")
                                except Exception:
                                    pass
                except Exception:
                    pass
        
        # Check renderer
        if hasattr(vtk_widget, 'renderer'):
            renderer = vtk_widget.renderer
            print(f"\n✅ renderer exists")
            
            actor_collection = renderer.GetActors()
            actor_count = actor_collection.GetNumberOfItems()
            print(f"   → {actor_count} actors in renderer")
            
            actor_collection.InitTraversal()
            for i in range(actor_count):
                actor = actor_collection.GetNextActor()
                if actor:
                    try:
                        mapper = actor.GetMapper()
                        if mapper:
                            input_data = mapper.GetInput()
                            if input_data:
                                pts = input_data.GetNumberOfPoints()
                                print(f"      Actor #{i}: {pts:,} points")
                    except Exception:
                        pass
        
        print("="*60 + "\n")


    def _update_specific_points_colors(self, converted_indices, to_class):
        """
        ✅ NEW: Update colors for ONLY the specific converted points
        Respects visibility - only shows color if to_class is checked
        """
        print(f"   🎯 Targeted color update for {len(converted_indices):,} points...")
        
        try:
            import vtk
            from vtk.util import numpy_support
            import numpy as np
            
            classification = self.app.data.get("classification")
            if classification is None:
                return False
            
            # ✅ Check if target class is VISIBLE
            visible_classes = self._get_visible_classes()
            
            is_visible = to_class in visible_classes
            
            if is_visible:
                print(f"   ✅ Class {to_class} is VISIBLE (checked)")
            else:
                print(f"   ❌ Class {to_class} is HIDDEN (unchecked) - points will be blank")
            
            # Get target color
            if is_visible:
                if hasattr(self.app, 'class_palette') and to_class in self.app.class_palette:
                    target_color = self.app.class_palette[to_class].get('color', (128, 128, 128))
                else:
                    target_color = (128, 128, 128)
                print(f"   → Target color: RGB{target_color}")
            else:
                target_color = (0, 0, 0)  # Black/blank
                print(f"   → Target color: BLANK (class hidden)")
            
            # ✅ Find VTK actor
            actor = self._find_main_vtk_actor()
            
            if not actor:
                print("   ❌ No VTK actor found")
                return False
            
            mapper = actor.GetMapper()
            input_data = mapper.GetInput()
            point_count = input_data.GetNumberOfPoints()
            
            # ✅ Get downsample indices
            downsample_indices = self._find_downsample_indices(len(classification), point_count)
            
            if downsample_indices is None:
                return False
            
            # ✅ Find which VTK points correspond to converted points
            # This creates a reverse mapping: full_index -> vtk_index
            reverse_map = {}
            for vtk_idx, full_idx in enumerate(downsample_indices):
                reverse_map[full_idx] = vtk_idx
            
            # Get VTK indices for converted points
            vtk_indices_to_update = []
            for full_idx in converted_indices:
                if full_idx in reverse_map:
                    vtk_indices_to_update.append(reverse_map[full_idx])
            
            print(f"   → Converting {len(converted_indices):,} full indices to {len(vtk_indices_to_update):,} VTK indices")
            
            if len(vtk_indices_to_update) == 0:
                print("   ⚠️ No VTK points found for converted indices")
                return False
            
            # ✅ Get existing colors array
            existing_colors_vtk = input_data.GetPointData().GetScalars()
            
            if existing_colors_vtk:
                existing_colors = numpy_support.vtk_to_numpy(existing_colors_vtk)
            else:
                # No existing colors - create default
                existing_colors = np.zeros((point_count, 3), dtype=np.uint8)
            
            # ✅ Update ONLY the converted points' colors
            for vtk_idx in vtk_indices_to_update:
                existing_colors[vtk_idx] = target_color
            
            print(f"   ✅ Updated {len(vtk_indices_to_update):,} VTK points to RGB{target_color}")
            
            # ✅ Update VTK actor
            vtk_colors = numpy_support.numpy_to_vtk(existing_colors, deep=True, 
                                                    array_type=vtk.VTK_UNSIGNED_CHAR)
            vtk_colors.SetName("Colors")
            
            input_data.GetPointData().SetScalars(vtk_colors)
            input_data.Modified()
            mapper.Modified()
            actor.Modified()
            
            # Force renderer update
            if hasattr(self.app, 'vtk_widget') and hasattr(self.app.vtk_widget, 'renderer'):
                self.app.vtk_widget.renderer.Modified()
            
            print(f"   ✅ Targeted color update complete")
            
            return True
            
        except Exception as e:
            print(f"   ❌ Targeted update failed: {e}")
            import traceback
            traceback.print_exc()
            return False


    def _find_main_vtk_actor(self):
        """Helper to find main VTK actor"""
        actor = None
        point_count = 0
        
        if hasattr(self.app, 'vtk_widget'):
            vtk_widget = self.app.vtk_widget
            
            # Method 1: Direct actor attribute
            if hasattr(vtk_widget, 'actor') and vtk_widget.actor:
                return vtk_widget.actor
            
            # Method 2: actors dictionary
            elif hasattr(vtk_widget, 'actors'):
                actors = vtk_widget.actors
                
                if isinstance(actors, dict):
                    # Find largest actor
                    for key, a in actors.items():
                        if a:
                            try:
                                mapper = a.GetMapper()
                                if mapper:
                                    input_data = mapper.GetInput()
                                    if input_data:
                                        pts = input_data.GetNumberOfPoints()
                                        if pts > point_count:
                                            actor = a
                                            point_count = pts
                            except Exception:
                                continue
                elif actors:
                    return actors
            
            # Method 3: Renderer's actors
            if not actor and hasattr(vtk_widget, 'renderer'):
                renderer = vtk_widget.renderer
                actor_collection = renderer.GetActors()
                actor_collection.InitTraversal()
                
                for i in range(actor_collection.GetNumberOfItems()):
                    a = actor_collection.GetNextActor()
                    if a:
                        try:
                            mapper = a.GetMapper()
                            if mapper:
                                input_data = mapper.GetInput()
                                if input_data:
                                    pts = input_data.GetNumberOfPoints()
                                    if pts > 1000:
                                        if pts > point_count:
                                            actor = a
                                            point_count = pts
                        except Exception:
                            continue
        
        return actor


    def _force_vtk_color_update_with_visibility(self):
        """
        ✅ CRITICAL: Update VTK colors with VISIBILITY FILTERING
        Only colors points whose class is CHECKED in Display Mode
        """
        print("   🎨 Direct VTK color update (visibility-aware)...")
        self._debug_vtk_structure()
        try:
            import vtk
            try:
                from vtk.util import numpy_support
            except ImportError:
                from vtkmodules.util import numpy_support
            import numpy as np
           
            classification = self.app.data.get("classification")
            if classification is None:
                print("   ❌ No classification data")
                return False
            
            # ✅ STEP 1: Get visible (checked) classes from Display Mode
            visible_classes = self._get_visible_classes()
            
            if not visible_classes:
                print("   ⚠️ No visible classes found - showing ALL")
                visible_classes = set(np.unique(classification))
            else:
                print(f"   ✅ Visible classes (checked): {sorted(visible_classes)}")
            
            # ✅ STEP 2: Find main VTK actor (IMPROVED LOGIC)
            actor = None
            point_count = 0
            
            if hasattr(self.app, 'vtk_widget'):
                vtk_widget = self.app.vtk_widget
                
                # Method 1: Direct actor attribute
                if hasattr(vtk_widget, 'actor') and vtk_widget.actor:
                    actor = vtk_widget.actor
                    print(f"   ✅ Found vtk_widget.actor")
                
                # Method 2: actors dictionary
                elif hasattr(vtk_widget, 'actors'):
                    actors = vtk_widget.actors
                    
                    if isinstance(actors, dict):
                        print(f"   🔍 Searching in actors dict ({len(actors)} entries)...")
                        
                        # First try: Find actor NOT starting with 'class_'
                        for key, a in actors.items():
                            if a:
                                key_str = str(key).lower()
                                if 'class_' not in key_str:
                                    try:
                                        mapper = a.GetMapper()
                                        if mapper:
                                            input_data = mapper.GetInput()
                                            if input_data:
                                                pts = input_data.GetNumberOfPoints()
                                                if pts > point_count:
                                                    actor = a
                                                    point_count = pts
                                                    print(f"   ✅ Found actor '{key}' with {pts:,} points")
                                    except Exception:
                                        continue
                        
                        # Second try: If no actor found, use ANY actor with points
                        if not actor:
                            print(f"   🔍 No unified actor found, trying any actor...")
                            for key, a in actors.items():
                                if a:
                                    try:
                                        mapper = a.GetMapper()
                                        if mapper:
                                            input_data = mapper.GetInput()
                                            if input_data:
                                                pts = input_data.GetNumberOfPoints()
                                                if pts > point_count:
                                                    actor = a
                                                    point_count = pts
                                                    print(f"   ✅ Found actor '{key}' with {pts:,} points")
                                    except Exception:
                                        continue
                    
                    elif actors:  # Single actor, not dict
                        actor = actors
                        print(f"   ✅ Found vtk_widget.actors (single actor)")
                
                # Method 3: Renderer's actors
                if not actor and hasattr(vtk_widget, 'renderer'):
                    renderer = vtk_widget.renderer
                    actor_collection = renderer.GetActors()
                    actor_collection.InitTraversal()
                    
                    print(f"   🔍 Searching in renderer actors...")
                    
                    for i in range(actor_collection.GetNumberOfItems()):
                        a = actor_collection.GetNextActor()
                        if a:
                            try:
                                mapper = a.GetMapper()
                                if mapper:
                                    input_data = mapper.GetInput()
                                    if input_data:
                                        pts = input_data.GetNumberOfPoints()
                                        if pts > 1000:  # Ignore small actors
                                            if pts > point_count:
                                                actor = a
                                                point_count = pts
                                                print(f"   ✅ Found actor #{i} with {pts:,} points")
                            except Exception:
                                continue
            
            if not actor:
                print("   ❌ No VTK actor found")
                print("   💡 Available attributes:")
                if hasattr(self.app, 'vtk_widget'):
                    for attr in dir(self.app.vtk_widget):
                        if 'actor' in attr.lower():
                            print(f"      - vtk_widget.{attr}")
                return False
            
            # Get point count if not already set
            if point_count == 0:
                mapper = actor.GetMapper()
                input_data = mapper.GetInput()
                point_count = input_data.GetNumberOfPoints()
            
            print(f"   ✅ Using actor with {point_count:,} points")
            
            # ✅ STEP 3: Get downsample indices
            downsample_indices = self._find_downsample_indices(len(classification), point_count)
            
            if downsample_indices is None:
                print("   ❌ Could not find downsample indices")
                return False
            
            # Validate indices
            if len(downsample_indices) != point_count:
                print(f"   ❌ Index count mismatch: {len(downsample_indices)} vs {point_count}")
                return False
            
            if np.max(downsample_indices) >= len(classification):
                print(f"   ❌ Invalid indices: max={np.max(downsample_indices)}, dataset={len(classification)}")
                return False
            
            # ✅ STEP 4: Get downsampled classification
            downsampled_classification = classification[downsample_indices]
            
            # ✅ STEP 5: Create colors with VISIBILITY FILTER
            colors = np.zeros((point_count, 3), dtype=np.uint8)
            
            visible_count = 0
            hidden_count = 0
            
            for class_code in np.unique(downsampled_classification):
                mask = (downsampled_classification == class_code)
                count = np.sum(mask)
                
                # ✅ Only color if class is VISIBLE (checked)
                if class_code in visible_classes:
                    if hasattr(self.app, 'class_palette') and class_code in self.app.class_palette:
                        color = self.app.class_palette[class_code].get('color', (128, 128, 128))
                        colors[mask] = color
                        visible_count += count
                        print(f"      ✅ Class {class_code}: {count:,} points → RGB{color} (VISIBLE)")
                    else:
                        colors[mask] = (128, 128, 128)
                        visible_count += count
                        print(f"      ✅ Class {class_code}: {count:,} points → Gray (VISIBLE)")
                else:
                    # Leave as (0,0,0) = blank/black
                    hidden_count += count
                    print(f"      ❌ Class {class_code}: {count:,} points → BLANK (HIDDEN)")
            
            print(f"   📊 Summary: {visible_count:,} visible, {hidden_count:,} hidden")
            
            # ✅ STEP 6: Update VTK actor
            mapper = actor.GetMapper()
            input_data = mapper.GetInput()
            
            vtk_colors = numpy_support.numpy_to_vtk(colors, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
            vtk_colors.SetName("Colors")
            
            input_data.GetPointData().SetScalars(vtk_colors)
            input_data.Modified()
            mapper.Modified()
            actor.Modified()
            
            # Force renderer update
            if hasattr(self.app, 'vtk_widget') and hasattr(self.app.vtk_widget, 'renderer'):
                self.app.vtk_widget.renderer.Modified()
            
            print(f"   ✅ VTK colors updated with visibility filter")
            
            return True
            
        except Exception as e:
            print(f"   ❌ VTK color update failed: {e}")
            import traceback
            traceback.print_exc()
            return False



    def _get_visible_classes(self):
        """Get set of visible (checked) classes from Display Mode dialog"""
        visible_classes = set()
        
        display_dialog = getattr(self.app, 'display_mode_dialog',
                                getattr(self.app, 'display_dialog', None))
        
        if not display_dialog or not hasattr(display_dialog, 'table'):
            return visible_classes
        
        table = display_dialog.table
        
        for row in range(table.rowCount()):
            try:
                # Get checkbox widget in column 0
                checkbox_item = table.cellWidget(row, 0)
                code_item = table.item(row, 1)
                
                if not code_item:
                    continue
                
                class_code = int(code_item.text())
                
                # Check if checkbox is checked
                if checkbox_item:
                    if hasattr(checkbox_item, 'isChecked'):
                        if checkbox_item.isChecked():
                            visible_classes.add(class_code)
                    elif hasattr(checkbox_item, 'checkState'):
                        from PySide6.QtCore import Qt
                        if checkbox_item.checkState() == Qt.CheckState.Checked:
                            visible_classes.add(class_code)
                else:
                    # No checkbox widget - check item itself
                    if hasattr(code_item, 'checkState'):
                        from PySide6.QtCore import Qt
                        if code_item.checkState() == Qt.CheckState.Checked:
                            visible_classes.add(class_code)
            except Exception as e:
                continue
        
        return visible_classes


    def _find_downsample_indices(self, full_count, target_count):
        """Find downsample indices from various sources"""
        
        # Try common attribute names
        for attr_name in ['downsample_indices', 'displayed_indices', 'visible_indices',
                        'current_indices', 'vtk_indices', 'display_mask', 'shown_indices']:
            if hasattr(self.app, attr_name):
                indices = getattr(self.app, attr_name)
                if indices is not None and isinstance(indices, np.ndarray):
                    # Direct index array
                    if len(indices) == target_count:
                        print(f"   ✅ Found: app.{attr_name}")
                        return indices
                    # Boolean mask
                    elif indices.dtype == bool and len(indices) == full_count:
                        import numpy as np
                        idx_array = np.where(indices)[0]
                        if len(idx_array) == target_count:
                            print(f"   ✅ Found: app.{attr_name} (boolean mask)")
                            return idx_array
        
        # Try data object
        if hasattr(self.app, 'data'):
            for attr_name in ['downsample_indices', 'displayed_indices', 'vtk_indices']:
                if hasattr(self.app.data, attr_name):
                    indices = getattr(self.app.data, attr_name)
                    if indices is not None and isinstance(indices, np.ndarray):
                        if len(indices) == target_count:
                            print(f"   ✅ Found: app.data.{attr_name}")
                            return indices
        
        # Last resort: uniform sampling
        print(f"   ⚠️ No stored indices - using UNIFORM sampling")
        import numpy as np
        step = max(1, full_count // target_count)
        return np.arange(0, full_count, step)[:target_count]


    def _save_camera_state(self):
        """Save camera state"""
        if not hasattr(self.app, 'vtk_widget'):
            return None
        if not hasattr(self.app.vtk_widget, 'renderer'):
            return None
        
        try:
            camera = self.app.vtk_widget.renderer.GetActiveCamera()
            if camera:
                return {
                    'position': tuple(camera.GetPosition()),
                    'focal_point': tuple(camera.GetFocalPoint()),
                    'view_up': tuple(camera.GetViewUp()),
                    'parallel_scale': camera.GetParallelScale(),
                    'parallel_projection': camera.GetParallelProjection(),
                }
        except Exception:
            pass
        return None


    def _restore_camera_state(self, saved_camera):
        """Restore camera state"""
        if not saved_camera:
            return
        
        try:
            camera = self.app.vtk_widget.renderer.GetActiveCamera()
            camera.SetPosition(saved_camera['position'])
            camera.SetFocalPoint(saved_camera['focal_point'])
            camera.SetViewUp(saved_camera['view_up'])
            camera.SetParallelScale(saved_camera['parallel_scale'])
            
            if saved_camera['parallel_projection']:
                camera.ParallelProjectionOn()
            else:
                camera.ParallelProjectionOff()
            
            self.app.vtk_widget.renderer.ResetCameraClippingRange()
        except Exception:
            pass


def make_color_icon(rgb):
    """Create a color icon from RGB tuple"""
    pix = QPixmap(20, 12)
    pix.fill(QColor(*rgb))
    return QIcon(pix)

class InsideFenceDialog(QDialog):
    """
    Inside Fence Conversion Dialog with Height Filtering
    
    🔷 FENCE MODE:
    Converts points inside digitized shapes (fence) from one/multiple classes to another
    Now includes optional height-based filtering!
    
    Workflow:
    1. Draw a shape using Digitize tools (line, rectangle, circle, polygon, freehand)
    2. Select the drawn shape
    3. (Optional) Enable height filter and set height threshold/range
    4. Select multiple "From classes" (points to convert) using Ctrl+Click
    5. Select "To class" (target class)
    6. Click Convert → Points inside fence (and matching height criteria) become To class
    """

    def __init__(self, app, ribbon_parent):
        # ✅ FIX 1: Ensure we have a valid QWidget parent (the Main Window)
        # If 'app' is the main window (NakshaApp), use it directly.
        from PySide6.QtWidgets import QWidget
        
        target_parent = None
        if isinstance(app, QWidget):
            target_parent = app
        elif hasattr(app, 'window') and isinstance(app.window, QWidget):
            target_parent = app.window
            
        # Initialize with the correct parent
        super().__init__(None, Qt.Window)
        self.setAttribute(Qt.WA_NativeWindow, True)  # Fix: GetDC invalid window handle
        flags = self.windowFlags()
        print(f"\n🔍 ByClassDialog Window Flags Debug:")
        print(f"   Raw flags value: {flags}")
        print(f"   Qt.Window: {Qt.Window}")
        print(f"   Qt.Tool: {Qt.Tool}")
        print(f"   Flags & Qt.Window: {flags & Qt.Window}")
        print(f"   Flags & Qt.Tool: {flags & Qt.Tool}")
        print(f"   Flags & Qt.FramelessWindowHint: {flags & Qt.FramelessWindowHint}")
        print(f"   Target parent type: {type(target_parent)}")
        if target_parent:
            print(f"   Parent window flags: {target_parent.windowFlags()}\n")
        
        # self.setWindowFlags(Qt.Window)
        
        self.setWindowModality(Qt.NonModal)
        
        # Store references
        self.app = app
        self.ribbon_parent = ribbon_parent
        self.selected_fence = None
        self.selected_fences = []
        self.permanent_fence_mode = False
        
        self.setWindowTitle("Inside Fence - Convert Points Within Shape")
        # self.setStyleSheet(self.naksha_dark_theme()) # Inherits global theme
        self.setGeometry(200, 200, 500, 700)
        
        # ... (rest of your init code: shortcuts, init_ui, connections) ...
        
        # ✅ Keyboard shortcuts
    
        
        self.init_ui()
        self.populate_classes()
        
        from PySide6.QtWidgets import QApplication
        QApplication.instance().installEventFilter(self)
        
        # Set strong focus policy
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Connect to Display Mode
        display_dialog = getattr(self.app, 'display_mode_dialog', getattr(self.app, 'display_dialog', None))
        if display_dialog:
            try:
                display_dialog.classes_loaded.connect(self.on_classes_changed)
                print("✅ InsideFenceDialog connected to display_mode_dialog.classes_loaded")
            except Exception as e:
                print(f"⚠️ Could not connect to display_dialog: {e}")   ####
        else:
            print("⚠️ Display Mode dialog not found (yet)")
            
            
    def eventFilter(self, obj, event):
        """
        ✅ CRITICAL: Intercept keyboard events BEFORE they reach Digitizer
        Installed on QApplication for global capture when dialog is visible
        
        ✅ FIXED: Now respects undo context priority - classification gets
        priority when active, draw tool only gets undo when classification is NOT active.
        """
        from PySide6.QtCore import QEvent
        
        if event.type() == QEvent.KeyPress:
            key = event.key()
            modifiers = event.modifiers()
            
            # Check for Ctrl+Z (Undo)
            if key == Qt.Key_Z and modifiers == Qt.ControlModifier:
                # ✅ CRITICAL FIX: Check undo context BEFORE passing to digitizer
                # Classification tool should ALWAYS get priority when active
                try:
                    ctx_mgr = get_undo_context_manager(self.app)
                    
                    if ctx_mgr.is_classification_active():
                        print("🔵 InsideFenceDialog: Classification active — NOT intercepting Ctrl+Z")
                        # Let event propagate to classification undo handler
                        return False
                except Exception as e:
                    print(f"⚠️ Undo context check failed: {e}")
                
                # Only pass to digitizer if draw tool OWNS the undo context
                digitizer = getattr(self.app, 'digitizer', None)
                if digitizer and getattr(digitizer, 'enabled', False):
                    undo_stack = getattr(digitizer, 'undo_stack', None)
                    if undo_stack and len(undo_stack) > 0:
                        # Double-check that draw tool owns the context
                        try:
                            ctx_mgr = get_undo_context_manager(self.app)
                            if ctx_mgr._current_context == ctx_mgr.DRAW:
                                print("🔵 InsideFenceDialog: Draw tool owns undo — passing Ctrl+Z to digitizer")
                                digitizer.undo()
                                event.accept()
                                return True
                        except Exception:
                            pass
                
                # Don't intercept - let classification or global shortcut handle it
                return False

            # Check for Ctrl+Y (Redo)
            elif key == Qt.Key_Y and modifiers == Qt.ControlModifier:
                # ✅ CRITICAL FIX: Check undo context BEFORE passing to digitizer
                try:
                    ctx_mgr = get_undo_context_manager(self.app)
                    
                    if ctx_mgr.is_classification_active():
                        print("🔵 InsideFenceDialog: Classification active — NOT intercepting Ctrl+Y")
                        return False
                except Exception as e:
                    print(f"⚠️ Undo context check failed: {e}")
                
                # Only pass to digitizer if draw tool OWNS the undo context
                digitizer = getattr(self.app, 'digitizer', None)
                if digitizer and getattr(digitizer, 'enabled', False):
                    redo_stack = getattr(digitizer, 'redo_stack', None)
                    if redo_stack and len(redo_stack) > 0:
                        try:
                            ctx_mgr = get_undo_context_manager(self.app)
                            if ctx_mgr._current_context == ctx_mgr.DRAW:
                                print("🔵 InsideFenceDialog: Draw tool owns redo — passing Ctrl+Y to digitizer")
                                digitizer.redo()
                                event.accept()
                                return True
                        except Exception:
                            pass
                
                return False
        
        # Pass other events through
        return super().eventFilter(obj, event)


    def keyPressEvent(self, event):
        """Fallback: Handle keyboard shortcuts directly on dialog
        
        ✅ FIXED: Now respects undo context priority - classification gets
        priority when active, draw tool only gets undo when classification is NOT active.
        """
        if event.modifiers() == Qt.ControlModifier:
            if event.key() == Qt.Key_Z:
                # ✅ CRITICAL FIX: Check undo context BEFORE handling
                try:
                    ctx_mgr = get_undo_context_manager(self.app)
                    
                    if ctx_mgr.is_classification_active():
                        print("🔵 InsideFenceDialog: Classification active — ignoring Ctrl+Z (fallback)")
                        event.ignore()  # Let it propagate
                        return
                except Exception:
                    pass
                
                # Only handle if draw tool owns undo context
                digitizer = getattr(self.app, 'digitizer', None)
                if digitizer and getattr(digitizer, 'enabled', False):
                    undo_stack = getattr(digitizer, 'undo_stack', None)
                    if undo_stack and len(undo_stack) > 0:
                        try:
                            ctx_mgr = get_undo_context_manager(self.app)
                            if ctx_mgr._current_context == ctx_mgr.DRAW:
                                print("🔵 InsideFenceDialog: Draw tool owns undo — Ctrl+Z (fallback)")
                                digitizer.undo()
                                event.accept()
                                return
                        except Exception:
                            pass
                
                event.ignore()
                return
                
            elif event.key() == Qt.Key_Y:
                # ✅ CRITICAL FIX: Check undo context BEFORE handling
                try:
                    ctx_mgr = get_undo_context_manager(self.app)
                    
                    if ctx_mgr.is_classification_active():
                        print("🔵 InsideFenceDialog: Classification active — ignoring Ctrl+Y (fallback)")
                        event.ignore()
                        return
                except Exception:
                    pass
                
                # Only handle if draw tool owns undo context
                digitizer = getattr(self.app, 'digitizer', None)
                if digitizer and getattr(digitizer, 'enabled', False):
                    redo_stack = getattr(digitizer, 'redo_stack', None)
                    if redo_stack and len(redo_stack) > 0:
                        try:
                            ctx_mgr = get_undo_context_manager(self.app)
                            if ctx_mgr._current_context == ctx_mgr.DRAW:
                                print("🔵 InsideFenceDialog: Draw tool owns redo — Ctrl+Y (fallback)")
                                digitizer.redo()
                                event.accept()
                                return
                        except Exception:
                            pass
                
                event.ignore()
                return
        
        super().keyPressEvent(event)
        
        
    def _restore_highlights_from_data(self):
        """Rebuilds blue highlight actors directly from the selected_fences array"""
        try:
            # Clear old garbage
            if hasattr(self, '_selection_highlight_actors'):
                for actor in self._selection_highlight_actors:
                    try: self.app.vtk_widget.renderer.RemoveViewProp(actor)
                    except Exception: pass
            self._selection_highlight_actors = []

            if not hasattr(self, 'selected_fences') or not self.selected_fences:
                return

            import vtk
            for shape in self.selected_fences:
                coords = shape.get('coords', [])
                if not coords: continue

                # Build the blue highlight actor
                if hasattr(self.app, 'digitizer'):
                    highlight_actor = self.app.digitizer._make_polyline_actor(
                        coords, color=(0, 0.5, 1), width=5
                    )
                else:
                    # Fallback
                    points = vtk.vtkPoints()
                    for c in coords: points.InsertNextPoint(c)
                    line = vtk.vtkPolyLine()
                    line.GetPointIds().SetNumberOfIds(len(coords))
                    for i in range(len(coords)): line.GetPointIds().SetId(i, i)
                    cells = vtk.vtkCellArray()
                    cells.InsertNextCell(line)
                    polydata = vtk.vtkPolyData()
                    polydata.SetPoints(points)
                    polydata.SetLines(cells)
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(polydata)
                    highlight_actor = vtk.vtkActor()
                    highlight_actor.SetMapper(mapper)
                    highlight_actor.GetProperty().SetColor(0, 0.5, 1) 
                    highlight_actor.GetProperty().SetLineWidth(5)

                self.app.vtk_widget.renderer.AddActor(highlight_actor)
                self._selection_highlight_actors.append(highlight_actor)

            self.app.vtk_widget.render()
            print(f"🔵 Restored {len(self._selection_highlight_actors)} fence highlights")
            
        except Exception as e:
            print(f"⚠️ Failed to restore highlights: {e}")


    def showEvent(self, event):
        """Grab keyboard when dialog becomes visible and restore visuals"""
        super().showEvent(event)
        # self.grabKeyboard()
        print("⌨️ InsideFenceDialog: Grabbed keyboard")
        
        # ✅ BULLETPROOF: Restore visual highlights if data exists
        if hasattr(self, 'selected_fences') and self.selected_fences:
            print(f"🔄 Restoring {len(self.selected_fences)} existing fence highlights...")
            # We must trick the list widget into redrawing them
            if hasattr(self, '_highlight_selected_fences_in_3d'):
                # We don't have the QListWidget items here, so we manually call the core logic
                self._restore_highlights_from_data()


    def hideEvent(self, event):
        """Release keyboard when dialog is hidden"""
        # self.releaseKeyboard()
        super().hideEvent(event)
        print("⌨️ InsideFenceDialog: Released keyboard")


    def closeEvent(self, event):
        """Clean up event filter, highlights, and keyboard grab when dialog closes"""
        print("🧹 InsideFenceDialog closing - cleaning up...")
        
        # ✅ BULLETPROOF: Actually remove the event filter so we don't hijack keys
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.instance().removeEventFilter(self)
            print("   ✅ Global event filter removed")
        except Exception as e:
            print(f"   ⚠️ Event filter removal failed: {e}")

        # Release keyboard grab
        # try:
        #     self.releaseKeyboard()
        #     print("   ✅ Keyboard released")
        # except Exception as e:
        #     print(f"   ⚠️ Keyboard release failed: {e}")
        
        # ✅ BULLETPROOF: Use RemoveViewProp for hover highlight
        if hasattr(self, '_hover_highlight_actor') and self._hover_highlight_actor:
            try:
                self.app.vtk_widget.renderer.RemoveViewProp(self._hover_highlight_actor)
                self._hover_highlight_actor = None
                print("   ✅ Hover highlight removed")
            except Exception as e:
                print(f"   ⚠️ Hover highlight removal failed: {e}")
        
        # ✅ BULLETPROOF: Use RemoveViewProp for selection highlights
        if hasattr(self, '_selection_highlight_actors'):
            try:
                for actor in self._selection_highlight_actors:
                    self.app.vtk_widget.renderer.RemoveViewProp(actor) 
                self._selection_highlight_actors = []
                print("   ✅ Selection highlights removed")
            except Exception as e:
                print(f"   ⚠️ Selection highlights removal failed: {e}")
        
        # Refresh view
        try:
            self.app.vtk_widget.render()
            print("   ✅ View refreshed")
        except Exception as e:
            print(f"   ⚠️ View refresh failed: {e}")
        
        print("✅ InsideFenceDialog cleanup complete")
        
        # Call parent closeEvent
        super().closeEvent(event)

    def init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Info banner (Subtle dark style)
        self.info_banner = QLabel("🔷 Convert points inside digitized shapes (fence)")
        self.info_banner.setStyleSheet("background-color: #1a1a1a; color: #00c8aa; padding: 8px; border-radius: 4px; font-weight: bold;")
        self.info_banner.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_banner)
        
        # === STEP 1: FENCE SELECTION ===
        # === STEP 1: FENCE SELECTION ===
        # Header with count badge
        fence_header = QHBoxLayout()
        fence_label = QLabel("1️⃣ DRAW OR SELECT FENCE")
        fence_label.setObjectName("header_label")

        self.fence_count_badge = QLabel("0")
        self.fence_count_badge.setStyleSheet("""
            QLabel {
                background-color: #9c27b0;
                color: white;
                border-radius: 10px;
                padding: 2px 8px;
                font-size: 9px;
                font-weight: bold;
            }
        """)
        self.fence_count_badge.setAlignment(Qt.AlignCenter)

        fence_header.addWidget(fence_label)
        fence_header.addStretch()
        fence_header.addWidget(self.fence_count_badge)
        layout.addLayout(fence_header)

        # Action buttons
        button_row = QHBoxLayout()

        self.select_fence_btn = QPushButton("📐 Select Fence(s)")
        self.select_fence_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976d2;
                color: white;
                font-size: 10px;
                font-weight: bold;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #1565c0; }
        """)
        self.select_fence_btn.clicked.connect(self.select_fence)
        button_row.addWidget(self.select_fence_btn, 2)

        self.clear_fence_btn = QPushButton("🗑️ Clear All")
        self.clear_fence_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                font-size: 10px;
                padding: 8px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #d32f2f; }
        """)
        self.clear_fence_btn.clicked.connect(self.clear_fence_selection)
        button_row.addWidget(self.clear_fence_btn, 1)

        layout.addLayout(button_row)

        # # Fence list display
        # self.fence_list_widget = QListWidget()
        # self.fence_list_widget.setMaximumHeight(120)
        # self.fence_list_widget.setStyleSheet("""
        #     QListWidget {
        #         background-color: #1a1a1a;
        #         border: 1px solid #333333;
        #         border-radius: 4px;
        #         color: #eeeeee;
        #         font-size: 10px;
        #     }
        #     QListWidget::item {
        #         padding: 6px;
        #         border-bottom: 1px solid #2a2a2a;
        #     }
        #     QListWidget::item:hover {
        #         background-color: #2a2a2a;
        #     }
        # """)
        # layout.addWidget(self.fence_list_widget)
        
        # === STEP 2: HEIGHT FILTER ===
        height_label = QLabel("2️⃣ HEIGHT FILTER (OPTIONAL)")
        height_label.setObjectName("header_label")
        layout.addWidget(height_label)
        
        self.height_filter_enabled = QCheckBox("Enable Height Filter")
        self.height_filter_enabled.toggled.connect(self.on_height_filter_toggled)
        layout.addWidget(self.height_filter_enabled)
        
        # Height Container
        self.height_filter_container = QWidget()
        h_layout = QVBoxLayout(self.height_filter_container)
        h_layout.setContentsMargins(5, 0, 5, 0)

        self.height_mode_combo = QComboBox()
        # ✅ FIX: Add data to combo items
        self.height_mode_combo.addItem("📐 Within Range", "within")
        self.height_mode_combo.addItem("⬆️ Above Height", "above")
        self.height_mode_combo.addItem("⬇️ Below Height", "below")
        self.height_mode_combo.currentIndexChanged.connect(self.on_height_mode_changed)
        h_layout.addWidget(self.height_mode_combo)

        # ✅ FIX: Add labels for spinboxes
        spin_container = QWidget()
        spin_layout = QVBoxLayout(spin_container)
        spin_layout.setContentsMargins(0, 0, 0, 0)
        spin_layout.setSpacing(5)
        
        # Min height row
        min_row = QHBoxLayout()
        self.min_height_label = QLabel("Min:")
        self.min_height_label.setStyleSheet("color: #aaaaaa; font-size: 9px;")
        self.min_height_spin = QDoubleSpinBox()
        self.min_height_spin.setRange(-1000, 10000)
        self.min_height_spin.setDecimals(2)
        self.min_height_spin.setSingleStep(1.0)
        self.min_height_spin.setValue(0.0)
        self.min_height_spin.setSuffix(" m")

        min_row.addWidget(self.min_height_label)
        min_row.addWidget(self.min_height_spin)
        spin_layout.addLayout(min_row)
        
        # Max height row
        max_row = QHBoxLayout()
        self.max_height_label = QLabel("Max:")
        self.max_height_label.setStyleSheet("color: #aaaaaa; font-size: 9px;")
        self.max_height_spin = QDoubleSpinBox()
        self.max_height_spin.setRange(-1000, 10000)
        self.max_height_spin.setDecimals(2)
        self.max_height_spin.setSingleStep(1.0)
        self.max_height_spin.setValue(100.0)
        self.max_height_spin.setSuffix(" m")

        max_row.addWidget(self.max_height_label)
        max_row.addWidget(self.max_height_spin)
        spin_layout.addLayout(max_row)
        
        h_layout.addWidget(spin_container)
        
        # ✅ ADD: Height stats label
        self.height_stats_label = QLabel("ℹ️ Enable height filter and select classes to analyze")
        self.height_stats_label.setStyleSheet("color: #666666; font-size: 8px; padding: 4px;")
        self.height_stats_label.setWordWrap(True)
        h_layout.addWidget(self.height_stats_label)
        
        # ✅ ADD: Auto-analyze button
        analyze_btn = QPushButton("📊 Auto-Analyze Heights")
        analyze_btn.clicked.connect(self.auto_analyze_heights)
        analyze_btn.setStyleSheet("""
            QPushButton {
                background-color: #1976d2;
                color: white;
                font-size: 9px;
                padding: 4px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1565c0;
            }
        """)
        h_layout.addWidget(analyze_btn)

        layout.addWidget(self.height_filter_container)
        self.height_filter_container.setVisible(False) 

        # === STEP 3: CLASS SELECTION ===
        class_label = QLabel("3️⃣ SELECT CLASSES")
        class_label.setObjectName("header_label")
        layout.addWidget(class_label)
        
        # ✅ ADD: Selected classes status label
        self.selected_classes_label = QLabel("Selected: None")
        self.selected_classes_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 9px;
                padding: 4px;
                background-color: #2c2c2c;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.selected_classes_label)
        
        # From classes label
        layout.addWidget(QLabel("Convert from classes (Ctrl+Click for multiple):"))
        
        self.from_list = QListWidget()
        self.from_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.from_list.setMinimumHeight(100)
        self.from_list.itemSelectionChanged.connect(self.on_from_selection_changed)  # ✅ ADD: Connect signal
        layout.addWidget(self.from_list)
        
        # ✅ ADD: Clear selection button
        clear_selection_btn = QPushButton("🗑️ Clear From Selection")
        clear_selection_btn.clicked.connect(self.clear_from_selection)
        clear_selection_btn.setStyleSheet("""
            QPushButton {
                background-color: #555555;
                color: white;
                font-size: 9px;
                padding: 4px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #666666;
            }
        """)
        layout.addWidget(clear_selection_btn)
        
        # To class combo
        # To class combo
        to_label = QLabel("Convert to class:")
        to_label.setStyleSheet("color: #888888; font-size: 10px; margin-top: 4px;")
        layout.addWidget(to_label)

        self.to_combo = QComboBox()
        self.to_combo.setStyleSheet("""
            QComboBox {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px;
                font-size: 10px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #888888;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #ffffff;
                selection-background-color: #00c8aa;
                selection-color: #000000;
                border: 1px solid #333333;
            }
        """)
        layout.addWidget(self.to_combo)
        
        # ✅ ADD: Preview label (shows results of preview/conversion)
        self.preview_label = QLabel("💡 Configure settings above, then preview or convert")
        self.preview_label.setStyleSheet("""
            QLabel {
                color: #9c27b0;
                font-size: 9px;
                padding: 6px;
                background-color: #1a1a1a;
                border-radius: 3px;
                font-style: italic;
            }
        """)
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        
        # Action buttons
        button_row = QHBoxLayout()
        
        preview_btn = QPushButton("👁️ Preview")
        preview_btn.clicked.connect(self.preview_conversion)
        button_row.addWidget(preview_btn)
        
        convert_btn = QPushButton("🔄 Convert")
        convert_btn.setObjectName("primary_btn") # Bright Teal Apply Style
        convert_btn.clicked.connect(self.perform_conversion)
        button_row.addWidget(convert_btn)
        
        layout.addLayout(button_row)
        
        # ✅ ADD: Fence status label (MISSING WIDGET)
        self.fence_status = QLabel("❌ No fence selected")
        self.fence_status.setStyleSheet("""
            QLabel {
                padding: 6px;
                background-color: #2c2c2c;
                border-radius: 3px;
                color: #f44336;
                font-size: 9px;
            }
        """)
        self.fence_status.setWordWrap(True)
        layout.addWidget(self.fence_status)


    # ==================== HEIGHT FILTER METHODS (NEW!) ====================
    
    def on_height_filter_toggled(self, checked):
        """
        ✅ BULLETPROOF UI TOGGLE: 
        .toggled emits a boolean, not an int. Do not compare it to Qt.CheckState.
        """
        is_checked = bool(checked)
        
        print(f"🔍 DEBUG: Height filter toggled! State = {is_checked}")
        
        if hasattr(self, 'height_filter_container'):
            self.height_filter_container.setVisible(is_checked)
            print(f"🔍 DEBUG: Container visibility set to: {is_checked}")
            
            if is_checked:
                self.on_height_mode_changed(0)  # Initialize visibility
        
    def on_height_mode_changed(self, index):
        """Update visibility of height inputs based on mode"""
        mode = self.height_mode_combo.currentData()  # ✅ Now this will work
        
        if mode == "within":
            # Show both min and max
            self.min_height_label.setText("Min:")
            self.min_height_label.setVisible(True)
            self.min_height_spin.setVisible(True)
            self.max_height_label.setVisible(True)
            self.max_height_spin.setVisible(True)
        elif mode == "above":
            # Show only min (as threshold)
            self.min_height_label.setText("Threshold:")
            self.min_height_label.setVisible(True)
            self.min_height_spin.setVisible(True)
            self.max_height_label.setVisible(False)
            self.max_height_spin.setVisible(False)
        elif mode == "below":
            # Show only max (as threshold)
            self.min_height_label.setVisible(False)
            self.min_height_spin.setVisible(False)
            self.max_height_label.setText("Threshold:")
            self.max_height_label.setVisible(True)
            self.max_height_spin.setVisible(True)
    
    def auto_analyze_heights(self):
        """Analyze height distribution of selected classes within fence"""
        if not self.selected_fences:  # ← CHANGED: plural
            QMessageBox.warning(self, "No Fence", "Please select at least one fence first")
            return
        
        # Use first fence for height analysis
        fence_coords = self.selected_fences[0]['coords']  # ← ADD THIS LINE
        
        from_classes = self._get_selected_from_classes()
        if not from_classes:
            QMessageBox.warning(self, "No Selection", "Please select at least one From class")
            return
        
        classification = self.app.data.get("classification")
        xyz = self.app.data.get("xyz")
        
        if classification is None or xyz is None:
            QMessageBox.warning(self, "No Data", "No point cloud data available")
            return
        
        try:
            # Get fence coordinates
          
            if isinstance(fence_coords, list):
                fence_coords = np.array(fence_coords)
            
            # Get From class points
            from_class_mask = np.isin(classification, from_classes)
            from_class_xyz = xyz[from_class_mask]
            
            if len(from_class_xyz) == 0:
                self.height_stats_label.setText("❌ No points found in selected classes")
                return
            
            # Check which points are inside fence
            inside_mask = self._points_inside_polygon(from_class_xyz, fence_coords)
            inside_points = from_class_xyz[inside_mask]
            
            if len(inside_points) == 0:
                self.height_stats_label.setText("❌ No points found inside fence")
                return
            
            # Calculate height statistics
            heights = inside_points[:, 2]
            min_h = np.min(heights)
            max_h = np.max(heights)
            mean_h = np.mean(heights)
            median_h = np.median(heights)
            
            # Update spinboxes with reasonable defaults
            self.min_height_spin.setValue(float(min_h))
            self.max_height_spin.setValue(float(max_h))
            
            # Display statistics
            stats_text = (
                f"📊 Height Analysis ({len(inside_points):,} points inside fence):\n"
                f"Min: {min_h:.2f}m | Max: {max_h:.2f}m\n"
                f"Mean: {mean_h:.2f}m | Median: {median_h:.2f}m"
            )
            
            self.height_stats_label.setText(stats_text)
            self.height_stats_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px;
                    background-color: #1b5e20;
                    border-radius: 3px;
                }
            """)
            
            print(f"✅ Height analysis complete: {len(inside_points):,} points")
            print(f"   Min: {min_h:.2f}m, Max: {max_h:.2f}m, Mean: {mean_h:.2f}m")
            
        except Exception as e:
            print(f"❌ Height analysis failed: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Analysis Failed", str(e))


    def perform_redo(self):
        if not hasattr(self.app, 'redo_classification'):
            return
        
        print("🔄 InsideFenceDialog: Performing CLASSIFICATION redo...")
        
        try:
            # ✅ redo_classification handles ALL refresh internally
            self.app.redo_classification()
            
            # ✅ Only update cross-sections and stats — NO main view refresh
            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in list(self.app.section_vtks.keys()):
                    try:
                        if hasattr(self.app, '_refresh_single_section_view'):
                            self.app._refresh_single_section_view(view_idx)
                    except Exception:
                        pass

            if hasattr(self.app, 'point_count_widget'):
                self.app.point_count_widget.schedule_update()
            
            self.preview_label.setText("↷ Redo performed")
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 6px;
                    background-color: #3e2723;
                    border-radius: 3px;
                }
            """)
            print("✅ Classification redo performed")
        except Exception as e:
            print(f"❌ Redo failed: {e}")
            QMessageBox.warning(self, "Redo Failed", f"Could not redo: {str(e)}")  
        
    def _clear_fence_highlights(self):
        """Remove all fence highlight actors from the 3D view"""
        print("   🧹 Clearing fence highlights...")
        
        # Remove hover highlight (yellow)
        if hasattr(self, '_hover_highlight_actor') and self._hover_highlight_actor:
            try:
                self.app.vtk_widget.renderer.RemoveViewProp(self._hover_highlight_actor) # FIXED
                self._hover_highlight_actor = None
            except Exception: pass
        
        # Remove selection highlights (blue)
        if hasattr(self, '_selection_highlight_actors'):
            for actor in self._selection_highlight_actors:
                try:
                    self.app.vtk_widget.renderer.RemoveViewProp(actor) # FIXED
                except Exception: pass
            self._selection_highlight_actors = []
            if hasattr(self, '_classified_fence_actors'):
                for actor in self._classified_fence_actors:
                    try:
                        self.app.digitizer.overlay_renderer.RemoveActor(actor)
                    except Exception:
                        pass
                self._classified_fence_actors = []
        # Render to update view
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass
        
        print("   ✅ Fence highlights cleared")
    
    
    def select_fence(self):
        """Allow user to select fences from digitize manager AND curve tool"""
        
        print("\n" + "="*60)
        print("🔷 SELECT_FENCE() called")
        print("="*60)

        # ✅ FIX: Reuse existing dialog instead of creating multiple instances
        if hasattr(self, '_fence_selection_dialog') and self._fence_selection_dialog is not None:
            try:
                self._fence_selection_dialog.close()
            except RuntimeError:
                pass
            self._fence_selection_dialog = None
        
        digitize = getattr(self.app, 'digitizer', None)
        curve_tool = getattr(self.app, 'curve_tool', None)
        
        print(f"   Digitizer found: {digitize is not None}")
        print(f"   Curve tool found: {curve_tool is not None}")
        
        # ── Collect digitizer drawings ────────────────────────────
        valid_shapes = []
        if digitize:
            drawings = getattr(digitize, 'drawings', [])
            print(f"   Total drawings: {len(drawings)}")
            if drawings:
                valid_shapes = [d for d in drawings if d.get('type') in 
                            ['rectangle', 'circle', 'polygon', 'freehand', 'line', 
                             'smart_line', 'polyline', 'smartline']]
        
        # ── Collect curve tool curves ✅ NEW ─────────────────────
        curve_fences = []
        if curve_tool and hasattr(curve_tool, 'get_curves_as_fences'):
            curve_fences = curve_tool.get_curves_as_fences()
            print(f"   Curve fences: {len(curve_fences)}")
        
        # Combine all
        all_fences = valid_shapes + curve_fences
        shape_count = len(valid_shapes)
        curve_count = len(curve_fences)
        
        print(f"   Valid shapes: {shape_count}")
        print(f"   Curve fences: {curve_count}")
        print(f"   Total: {len(all_fences)}")
        
        if not all_fences:
            QMessageBox.warning(
                self,
                "No Shapes Found",
                "No shapes or curves found.\n\n"
                "• Draw shapes using Digitize tools, OR\n"
                "• Draw curves using the Curve tool"
            )
            return
        
        print("   ✅ Creating dialog...")
        
        from PySide6.QtWidgets import QListWidget, QAbstractItemView, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QWidget, QLabel as QLabel2
        from PySide6.QtCore import Qt, QEvent
        
        try:
            dialog = QDialog(self, Qt.Window)
            self._fence_selection_dialog = dialog
            dialog.setWindowTitle("Select Fence(s)")
            dialog.setWindowModality(Qt.NonModal)
            dialog.resize(420, 500)
            
            print("   ✅ Dialog created successfully")
            
            layout = QVBoxLayout(dialog)
            
            # Info label with counts
            info_label = QLabel("Select one or more fences to use for conversion")
            info_label.setStyleSheet("color: #9c27b0; font-weight: bold; padding: 8px;")
            layout.addWidget(info_label)
            
            count_label = QLabel(f"📐 Digitizer: {shape_count}  |  〰️ Curves: {curve_count}")
            count_label.setStyleSheet("color: #888888; font-size: 10px; padding: 0 8px;")
            layout.addWidget(count_label)
            
            # Permanent mode checkbox
            permanent_check = QCheckBox("🔄 Permanent Fence Mode (keep all fences selected)")
            permanent_check.setChecked(True)
            self.permanent_fence_mode = True
            permanent_check.setStyleSheet("""
                QCheckBox { color: #eeeeee; font-size: 11px; padding: 8px; font-weight: bold; }
                QCheckBox::indicator { width: 18px; height: 18px; }
                QCheckBox::indicator:unchecked { background-color: #2c2c2c; border: 1px solid #555555; border-radius: 3px; }
                QCheckBox::indicator:checked { background-color: #9c27b0; border: 1px solid #9c27b0; border-radius: 3px; }
            """)
            layout.addWidget(permanent_check)
            
            fence_list = QListWidget()
            fence_list.setStyleSheet("""
                QListWidget { background-color: #1e1e1e; border: 1px solid #3a3a3a; border-radius: 4px; padding: 4px; }
                QListWidget::item { background: transparent; border: none; padding: 2px; }
            """)
            fence_list.setSelectionMode(QAbstractItemView.NoSelection)
            
            # ✅ UPDATED: Shape icons including curve
            SHAPE_ICONS = {
                'rectangle': '▭', 'circle': '○', 'polygon': '⬟', 'polyline': '⬡',
                'line': '─', 'smartline': '⚡', 'freehand': '✏️', 'curve': '〰️'
            }
            
            custom_widgets = []
            current_hover_actor = [None]
            selection_highlight_actors = {}
            
            def _add_actor_to_renderer(actor):
                if actor is None: return
                try:
                    if hasattr(actor, 'IsA') and actor.IsA('vtkActor2D'):
                        self.app.vtk_widget.renderer.AddViewProp(actor)
                    else:
                        self.app.vtk_widget.renderer.AddActor(actor)
                except Exception: pass
            
            def _rem_actor_from_renderer(actor):
                if actor is None: return
                try:
                    if hasattr(actor, 'IsA') and actor.IsA('vtkActor2D'):
                        self.app.vtk_widget.renderer.RemoveViewProp(actor)
                    else:
                        self.app.vtk_widget.renderer.RemoveActor(actor)
                except Exception: pass
            
            def _make_highlight_actor(coords, color, width):
                try:
                    import vtk
                    pts = vtk.vtkPoints()
                    pts.SetDataTypeToDouble()
                    for c in coords:
                        z = float(c[2]) if len(c) > 2 else 0.0
                        pts.InsertNextPoint(float(c[0]), float(c[1]), z)
                    
                    pl = vtk.vtkPolyLine()
                    pl.GetPointIds().SetNumberOfIds(len(coords))
                    for i in range(len(coords)):
                        pl.GetPointIds().SetId(i, i)
                    
                    ca = vtk.vtkCellArray()
                    ca.InsertNextCell(pl)
                    
                    pd = vtk.vtkPolyData()
                    pd.SetPoints(pts)
                    pd.SetLines(ca)
                    
                    mapper = vtk.vtkPolyDataMapper2D()
                    mapper.SetInputData(pd)
                    
                    coord = vtk.vtkCoordinate()
                    coord.SetCoordinateSystemToWorld()
                    mapper.SetTransformCoordinate(coord)
                    
                    actor = vtk.vtkActor2D()
                    actor.SetMapper(mapper)
                    actor.GetProperty().SetColor(*color)
                    actor.GetProperty().SetLineWidth(width)
                    actor.GetProperty().SetDisplayLocationToForeground()
                    
                    return actor
                except Exception:
                    try:
                        if hasattr(self.app, 'digitizer'):
                            return self.app.digitizer._make_polyline_actor(coords, color=color, width=width)
                    except Exception: pass
                    return None
            
            def highlight_fence_in_3d(shape):
                if current_hover_actor[0]:
                    _rem_actor_from_renderer(current_hover_actor[0])
                    current_hover_actor[0] = None
                if not shape:
                    try: self.app.vtk_widget.render()
                    except Exception: pass
                    return
                coords = shape.get('coords', [])
                if not coords: return
                try:
                    ha = _make_highlight_actor(coords, (1, 1, 0), 6)
                    if ha:
                        _add_actor_to_renderer(ha)
                        current_hover_actor[0] = ha
                        self.app.vtk_widget.render()
                except Exception as e:
                    print(f"⚠️ Hover highlight failed: {e}")
            
            def add_selection_highlight(shp):
                coords = shp.get('coords', [])
                if not coords: return
                try:
                    act = _make_highlight_actor(coords, (0, 0.5, 1), 5)
                    if act:
                        _add_actor_to_renderer(act)
                        if shp.get('source') == 'curve_tool':
                            selection_highlight_actors[id(shp.get('curve_data', shp))] = act
                        else:
                            selection_highlight_actors[id(shp)] = act
                        self.app.vtk_widget.render()
                except Exception as e:
                    print(f"⚠️ Selection highlight failed: {e}")

            def remove_selection_highlight(shp):
                if shp.get('source') == 'curve_tool':
                    sid = id(shp.get('curve_data', shp))
                else:
                    sid = id(shp)
                act = selection_highlight_actors.pop(sid, None)
                if act:
                    _rem_actor_from_renderer(act)
                    try: self.app.vtk_widget.render()
                    except Exception: pass
            
            # ── Build current selection IDs ───────────────────────
            current_ids = set()
            for f in self.selected_fences:
                if f.get('source') == 'curve_tool':
                    current_ids.add(id(f.get('curve_data', f)))
                else:
                    current_ids.add(id(f))
            
            # ── Build list items ──────────────────────────────────
            for idx, fence in enumerate(all_fences):
                stype = fence.get('type', 'unknown')
                coords = fence.get('coords', [])
                is_curve = fence.get('source') == 'curve_tool'
                icon = SHAPE_ICONS.get(stype, '◆')
                
                if is_curve:
                    curve_idx = fence.get('curve_index', idx)
                    title_text = f"〰️ Curve #{curve_idx + 1}"
                    source_tag = "Curve Tool"
                else:
                    title_text = f"{icon} #{idx+1}: {stype.capitalize()}"
                    source_tag = "Digitizer"
                
                try:
                    arr = np.array(coords)
                    w = arr[:, 0].max() - arr[:, 0].min()
                    h = arr[:, 1].max() - arr[:, 1].min()
                    size_str = f"{w:.1f}×{h:.1f}m"
                except Exception:
                    size_str = ""
                
                if is_curve:
                    is_current = id(fence.get('curve_data', fence)) in current_ids
                else:
                    is_current = id(fence) in current_ids
                
                item_widget = QWidget()
                bg = "#1a2a1a" if is_curve else "#2a2a2a"
                item_widget.setStyleSheet(f"QWidget {{ background-color: {bg}; border: 1px solid #3a3a3a; border-radius: 6px; padding: 8px; margin: 2px; }} QWidget:hover {{ background-color: #3c3c3c; border: 1px solid #555555; }}")
                item_layout = QHBoxLayout(item_widget)
                item_layout.setContentsMargins(8, 8, 8, 8)
                
                checkbox = QCheckBox()
                checkbox.setStyleSheet("QCheckBox::indicator { width: 18px; height: 18px; border-radius: 3px; border: 1px solid #555555; background-color: #1e1e1e; } QCheckBox::indicator:checked { background-color: #9c27b0; border: 1px solid #9c27b0; }")
                item_layout.addWidget(checkbox)
                
                text_label = QLabel2(f"{title_text}\n{len(coords)} pts | {size_str} | {source_tag}")
                text_label.setStyleSheet("color: #eeeeee; font-size: 10px; background: transparent;")
                item_layout.addWidget(text_label, 1)
                
                selected_badge = QLabel2("Selected")
                selected_badge.setStyleSheet("QLabel { background-color: #6a1b9a; color: white; font-size: 9px; font-weight: bold; padding: 4px 8px; border-radius: 3px; }")
                selected_badge.setVisible(is_current)
                item_layout.addWidget(selected_badge)

                list_item = QListWidgetItem(fence_list)
                
                # No delete button for curves
                if not is_curve:
                    delete_btn = QPushButton("🗑️")
                    delete_btn.setToolTip("Delete this fence permanently")
                    delete_btn.setStyleSheet("QPushButton { background-color: transparent; color: #f44336; font-size: 14px; border: none; padding: 4px; } QPushButton:hover { background-color: #4a1414; border-radius: 4px; }")
                    item_layout.addWidget(delete_btn)
                else:
                    spacer = QWidget()
                    spacer.setFixedSize(28, 28)
                    item_layout.addWidget(spacer)

                def make_toggle_func(badge, widget, shp, ic):
                    def toggle(checked):
                        badge.setVisible(checked)
                        if checked:
                            bg_c = "#2a3a2a" if ic else "#3a2a4a"
                            widget.setStyleSheet(f"background-color: {bg_c}; border: 1px solid #6a1b9a; border-radius: 6px; padding: 8px; margin: 2px;")
                            add_selection_highlight(shp)
                        else:
                            widget.setStyleSheet("QWidget { background-color: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 6px; padding: 8px; margin: 2px; } QWidget:hover { background-color: #3c3c3c; border: 1px solid #555555; }")
                            remove_selection_highlight(shp)
                    return toggle
                
                checkbox.toggled.connect(make_toggle_func(selected_badge, item_widget, fence, is_curve))
                
                if is_current:
                    item_widget.setStyleSheet("background-color: #3a2a4a; border: 1px solid #6a1b9a; border-radius: 6px; padding: 8px; margin: 2px;")
                    add_selection_highlight(fence)
                
                if not is_curve:
                    def make_row_click_func(cb, btn):
                        def on_mouse_press(event):
                            if not btn.underMouse():
                                cb.setChecked(not cb.isChecked())
                        return on_mouse_press
                    item_widget.mousePressEvent = make_row_click_func(checkbox, delete_btn)
                    
                    def make_delete_func(shp, lst_item, target_idx):
                        def delete_action():
                            remove_selection_highlight(shp)
                            highlight_fence_in_3d(None)
                            if hasattr(self.app, 'digitizer'):
                                self.app.digitizer.clear_coordinate_labels()
                                self.app.digitizer._remove_drawing(shp)
                            if shp in self.selected_fences:
                                self.selected_fences.remove(shp)
                            for i, cw in enumerate(custom_widgets):
                                if cw[3] is shp: custom_widgets.pop(i); break
                            fence_list.takeItem(fence_list.row(lst_item))
                            update_stats(); self.update_fence_display()
                            try: self.app.vtk_widget.render()
                            except Exception: pass
                        return delete_action
                    delete_btn.clicked.connect(make_delete_func(fence, list_item, idx))
                else:
                    def make_click_curve(cb):
                        def on_mouse_press(event):
                            cb.setChecked(not cb.isChecked())
                        return on_mouse_press
                    item_widget.mousePressEvent = make_click_curve(checkbox)
                
                item_widget.setCursor(Qt.PointingHandCursor)

                class HoverEventFilter(QWidget):
                    def __init__(self, parent, shape_data):
                        super().__init__(parent)
                        self.shape_data = shape_data
                    def eventFilter(self, obj, event):
                        if event.type() == QEvent.Enter: highlight_fence_in_3d(self.shape_data)
                        elif event.type() == QEvent.Leave: highlight_fence_in_3d(None)
                        return super().eventFilter(obj, event)
                
                item_widget.installEventFilter(HoverEventFilter(item_widget, fence))
                
                list_item.setSizeHint(item_widget.sizeHint())
                fence_list.addItem(list_item)
                fence_list.setItemWidget(list_item, item_widget)
                
                custom_widgets.append((checkbox, item_widget, selected_badge, fence))
            
            layout.addWidget(fence_list)
            
            stats_label = QLabel("Select one or more fences")
            stats_label.setStyleSheet("color: #aaaaaa; font-size: 9px; padding: 4px;")
            layout.addWidget(stats_label)
            
            def update_stats():
                count = sum(1 for cb, _, _, _ in custom_widgets if cb.isChecked())
                if count == 0: stats_label.setText("⚠️ No fences selected")
                elif count == 1: stats_label.setText("✅ 1 fence selected")
                else: stats_label.setText(f"✅ {count} fences selected")
            
            for checkbox, _, _, _ in custom_widgets:
                checkbox.toggled.connect(update_stats)
            
            button_layout = QHBoxLayout()
            
            select_all_btn = QPushButton("Select All")
            select_all_btn.setStyleSheet("QPushButton { background-color: #1976d2; color: white; font-size: 10px; padding: 6px 12px; border-radius: 3px; }")
            select_all_btn.clicked.connect(lambda: [cb.setChecked(True) for cb, _, _, _ in custom_widgets])
            button_layout.addWidget(select_all_btn)
            
            clear_btn = QPushButton("Clear All")
            clear_btn.setStyleSheet("QPushButton { background-color: #555555; color: white; font-size: 10px; padding: 6px 12px; border-radius: 3px; }")
            def clear_all_fences():
                for cb, _, _, _ in custom_widgets: cb.setChecked(False)
                for actor in selection_highlight_actors.values():
                    _rem_actor_from_renderer(actor)
                selection_highlight_actors.clear()
                self.selected_fences = []
                self._clear_fence_highlights()
                self.fence_status.setText("❌ No fence selected")
                self.fence_status.setStyleSheet("QLabel { padding: 6px; background-color: #2c2c2c; border-radius: 3px; color: #f44336; }")
                self.fence_count_badge.setText("0")
                stats_label.setText("⚠️ All fences cleared")
            clear_btn.clicked.connect(clear_all_fences)
            button_layout.addWidget(clear_btn)
            
            button_layout.addStretch()
            
            apply_btn = QPushButton("Apply Selection")
            apply_btn.setStyleSheet("QPushButton { background-color: #2e7d32; color: white; font-size: 10px; font-weight: bold; padding: 6px 16px; border-radius: 3px; }")
            
            def apply_selection():
                highlight_fence_in_3d(None)
                selected_shapes = [shp for cb, _, _, shp in custom_widgets if cb.isChecked()]
                
                if not selected_shapes:
                    QMessageBox.warning(dialog, "No Selection", "Please select at least one fence")
                    return
                
                self.permanent_fence_mode = permanent_check.isChecked()
                
                if not self.permanent_fence_mode:
                    self.selected_fences = []
                
                # Build existing IDs
                existing_ids = set()
                for f in self.selected_fences:
                    if f.get('source') == 'curve_tool':
                        existing_ids.add(id(f.get('curve_data', f)))
                    else:
                        existing_ids.add(id(f))
                
                for shape in selected_shapes:
                    if shape.get('source') == 'curve_tool':
                        fence_id = id(shape.get('curve_data', shape))
                    else:
                        fence_id = id(shape)
                    
                    if fence_id not in existing_ids:
                        self.selected_fences.append(shape)
                        existing_ids.add(fence_id)
                    
                    # Close open shapes
                    if shape['type'] in ['line', 'smart_line', 'polyline', 'smartline', 'curve']:
                        coords = shape.get('coords', [])
                        if isinstance(coords, list): coords = np.array(coords)
                        if len(coords) > 0 and not np.array_equal(coords[0], coords[-1]):
                            shape['coords'] = np.vstack([coords, coords[0]]) if isinstance(coords, np.ndarray) else coords + [coords[0]]
                
                self._selection_highlight_actors = list(selection_highlight_actors.values())
                self.update_fence_display()
                
                fence_count = len(self.selected_fences)
                shape_fc = sum(1 for f in self.selected_fences if f.get('source') != 'curve_tool')
                curve_fc = sum(1 for f in self.selected_fences if f.get('source') == 'curve_tool')
                total_pts = sum(len(f.get('coords', [])) for f in self.selected_fences)
                mode_text = "🔄 PERMANENT" if self.permanent_fence_mode else "TEMP"
                
                parts = []
                if shape_fc: parts.append(f"{shape_fc} shape(s)")
                if curve_fc: parts.append(f"{curve_fc} curve(s)")
                
                self.fence_status.setText(f"✅ {' + '.join(parts)} selected ({total_pts} pts) - {mode_text}")
                self.fence_status.setStyleSheet("QLabel { padding: 6px; background-color: #1b5e20; border-radius: 3px; color: #4caf50; font-weight: bold; }")
                
                try: self.app.vtk_widget.render()
                except Exception: pass
                
                self._fence_selection_dialog = None
                dialog.close()
                dialog.deleteLater()
            
            apply_btn.clicked.connect(apply_selection)
            button_layout.addWidget(apply_btn)
            
            close_btn = QPushButton("Close")
            close_btn.setStyleSheet("QPushButton { background-color: #555555; color: white; font-size: 10px; padding: 6px 16px; border-radius: 3px; }")
            def on_close():
                highlight_fence_in_3d(None)
                for actor in selection_highlight_actors.values():
                    _rem_actor_from_renderer(actor)
                selection_highlight_actors.clear()
                self._fence_selection_dialog = None
                dialog.close()
            close_btn.clicked.connect(on_close)
            button_layout.addWidget(close_btn)
            
            layout.addLayout(button_layout)
            
            dialog.show()
            print("   ✅ Dialog shown successfully!")
            print("="*60 + "\n")
            
        except Exception as e:
            print(f"   ❌ ERROR creating dialog: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to create fence selection dialog:\n{str(e)}")

    # ==================== CONVERSION LOGIC ====================

    def _calculate_conversion(self, from_classes, to_class, preview=False):
        """
        ✅ BULLETPROOF: Pure Data Logic.
        Calculates masks, applies classes, handles undo queue, and cleans up digitizer.
        Does NOT touch the VTK renderers.
        """
        classification = self.app.data.get("classification")
        xyz = self.app.data.get("xyz")
        
        if classification is None or xyz is None:
            print("❌ No data!")
            return None
        
        if not self.selected_fences:
            QMessageBox.warning(self, "No Fences", "Please select at least one fence first")
            return None
        
        print(f"\n{'='*60}")
        print(f"🔷 INSIDE FENCE CONVERSION (MULTI-FENCE MODE)")
        print(f"{'='*60}")
        print(f"   Number of fences: {len(self.selected_fences)}")
        print(f"   Permanent mode: {self.permanent_fence_mode}")
        print(f"   From classes: {from_classes}")
        print(f"   To class: {to_class}")
        print(f"   Total points: {len(classification):,}")
        
        # Get From class points
        if isinstance(from_classes, list):
            from_class_mask = np.isin(classification, from_classes)
        else:
            from_class_mask = (classification == from_classes)
        
        from_class_count = np.sum(from_class_mask)
        print(f"   From class points: {from_class_count:,}")
        
        if from_class_count == 0:
            print("⚠️ No From class points to convert")
            return 0
        
        # Get XYZ coordinates of From class points
        from_class_indices = np.where(from_class_mask)[0]
        from_class_xyz = xyz[from_class_mask]
        
        # ==================== HEIGHT FILTERING ====================
        if self.height_filter_enabled.isChecked():
            mode = self.height_mode_combo.currentData()
            heights = from_class_xyz[:, 2]
            
            if mode == "within":
                min_h = self.min_height_spin.value()
                max_h = self.max_height_spin.value()
                height_mask = (heights >= min_h) & (heights <= max_h)
                print(f"   Height filter: WITHIN [{min_h:.2f}m, {max_h:.2f}m]")
            elif mode == "above":
                threshold = self.min_height_spin.value()
                height_mask = heights >= threshold
                print(f"   Height filter: ABOVE {threshold:.2f}m")
            elif mode == "below":
                threshold = self.max_height_spin.value()
                height_mask = heights <= threshold
                print(f"   Height filter: BELOW {threshold:.2f}m")
            
            from_class_xyz = from_class_xyz[height_mask]
            from_class_indices = from_class_indices[height_mask]
            
            print(f"   After height filter: {len(from_class_xyz):,} points")
            
            if len(from_class_xyz) == 0:
                print("⚠️ No points match height criteria")
                return 0
        
        # ==================== MULTI-FENCE POINT SELECTION ====================
        combined_inside_mask = np.zeros(len(from_class_xyz), dtype=bool)
        
        for fence_idx, fence in enumerate(self.selected_fences):
            fence_coords = fence['coords']
            if isinstance(fence_coords, list):
                fence_coords = np.array(fence_coords)
            
            inside_mask = self._points_inside_polygon(from_class_xyz, fence_coords)
            combined_inside_mask |= inside_mask
            
            fence_count = np.sum(inside_mask)
            print(f"   Fence #{fence_idx+1} ({fence['type']}): {fence_count:,} points")
        
        inside_indices = from_class_indices[combined_inside_mask]
        inside_count = len(inside_indices)
        
        print(f"   TOTAL points inside all fences: {inside_count:,}")
        
        if preview:
            print(f"{'='*60}\n")
            return inside_count
        
        if inside_count == 0:
            print(f"{'='*60}\n")
            return 0
        
        # Build final mask for main dataset
        final_mask = np.zeros(len(classification), dtype=bool)
        final_mask[inside_indices] = True
        
        # Save old classes for undo
        old_classes = classification[final_mask].copy()
        
        # Convert
        classification[final_mask] = to_class
        
        # Save undo
        undo_step = {
            "mask": final_mask.copy(),
            "old_classes": old_classes,
            "new_classes": np.full(np.sum(final_mask), to_class, dtype=classification.dtype)
        }
        self.app.undo_stack.append(undo_step)
        self.app.redo_stack.clear()
        from gui.memory_manager import trim_undo_stack
        trim_undo_stack(self.app)
        self.app._conversion_just_happened = True
        
        print(f"   ✅ Converted {inside_count:,} points to class {to_class}")
        
        # ==================== CLEANUP FENCES ====================
        if not self.permanent_fence_mode:
            print("   🔄 Temporary mode - clearing fence selection AND deleting drawn fences")
            
            if hasattr(self.app, 'digitizer') and self.selected_fences:
                digitizer = self.app.digitizer
                fences_to_delete = list(self.selected_fences)
                
                for fence in fences_to_delete:
                    fence_coords = fence.get('coords', [])
                    for drawing in list(digitizer.drawings):
                        drawing_coords = drawing.get('coords', [])
                        if len(fence_coords) == len(drawing_coords):
                            coords_match = all(
                                tuple(fc) == tuple(dc) 
                                for fc, dc in zip(fence_coords, drawing_coords)
                            )
                            if coords_match:
                                digitizer._remove_drawing(drawing)
                                print(f"   🗑️ Deleted drawn fence ({fence.get('type', 'unknown')})")
                                break
            
            self.selected_fences = []
            
            # Note: Removal of UI blue highlights moved to perform_conversion
            self.fence_status.setText("❌ No fence selected (temporary mode - select again)")
            self.fence_status.setStyleSheet("""
                QLabel {
                    padding: 6px;
                    background-color: #2c2c2c;
                    border-radius: 3px;
                    color: #f44336;
                }
            """)
        else:
            print("   🔄 Permanent mode - keeping fence selection AND drawn fences")
            
        print(f"{'='*60}\n")
        
        # 🛑 RETURN THE MASK FOR GPU INJECTION
        return inside_count, final_mask
        
    def _points_inside_polygon(self, points, polygon_coords):
        """
        ✅ HIGH-PERFORMANCE RAY CASTING: 
        Uses an Axis-Aligned Bounding Box (AABB) pre-filter to prevent UI thread lockups.
        """
        from matplotlib.path import Path
        import numpy as np
        
        # Extract XY coordinates only (ignore Z)
        if isinstance(polygon_coords, list):
            poly_xy = np.array([(c[0], c[1]) for c in polygon_coords])
        else:
            poly_xy = polygon_coords[:, :2]
        
        points_xy = points[:, :2]
        
        # 1. AABB Pre-filter (O(N) - Ultra Fast)
        min_x, min_y = np.min(poly_xy, axis=0)
        max_x, max_y = np.max(poly_xy, axis=0)
        
        bbox_mask = (points_xy[:, 0] >= min_x) & (points_xy[:, 0] <= max_x) & \
                    (points_xy[:, 1] >= min_y) & (points_xy[:, 1] <= max_y)
        
        inside = np.zeros(len(points), dtype=bool)
        
        # 2. Exact Polygon Check ONLY on points inside the bounding box
        if np.any(bbox_mask):
            poly_path = Path(poly_xy)
            inside[bbox_mask] = poly_path.contains_points(points_xy[bbox_mask])
            
        return inside
    

    def _refresh_all_views(self):
        """
        ✅ FIXED: Handle both unified and by-class actor modes
        For by-class mode: rebuild affected actors
        For unified mode: update colors only
        """
        print(f"\n🔄 REFRESHING VIEWS (partial + visibility-aware)...")
        
        # ✅ CRITICAL: Save camera position BEFORE any updates
        saved_camera = None
        if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget.renderer:
            try:
                camera = self.app.vtk_widget.renderer.GetActiveCamera()
                if camera:
                    saved_camera = {
                        'position': tuple(camera.GetPosition()),
                        'focal_point': tuple(camera.GetFocalPoint()),
                        'view_up': tuple(camera.GetViewUp()),
                        'parallel_scale': camera.GetParallelScale(),
                        'parallel_projection': camera.GetParallelProjection(),
                    }
                    print(f"   📷 Camera saved: pos={saved_camera['position'][:2]}, scale={saved_camera['parallel_scale']:.2f}")
            except Exception as e:
                print(f"   ⚠️ Camera save failed: {e}")
        
        # ✅ DETECT MODE: By-class actors or unified actor?
        has_by_class_actors = False
        if hasattr(self.app.vtk_widget, 'actors') and isinstance(self.app.vtk_widget.actors, dict):
            for key in self.app.vtk_widget.actors.keys():
                if 'class_' in str(key).lower():
                    has_by_class_actors = True
                    break
        
        update_success = False
        
        if has_by_class_actors:
            print(f"   🔍 Detected BY-CLASS actor mode - rebuilding affected actors...")
            
            # ✅ FIXED: Use on_apply() method that actually exists
            try:
                display_dialog = getattr(self.app, 'display_mode_dialog', 
                                        getattr(self.app, 'display_dialog', None))
                
                if display_dialog and hasattr(display_dialog, 'on_apply'):
                    display_dialog.on_apply()
                    print(f"   ✅ Called display_dialog.on_apply()")
                    update_success = True
                else:
                    print(f"   ⚠️ Display dialog or on_apply() not found")
            
            except Exception as e:
                print(f"   ⚠️ Display mode refresh failed: {e}")
        
        # ✅ UNIFIED ACTOR MODE: Try smart update or direct VTK update
        if not update_success:
            print(f"   🔍 Using unified actor mode - updating colors...")
            
            # Try smart_update_colors
            try:
                from gui.pointcloud_display import smart_update_colors
                smart_update_colors(self.app, None)
                print(f"   ✅ Main view updated (smart_update_colors)")
                update_success = True
            except ImportError:
                print(f"   ⚠️ smart_update_colors not found - trying direct VTK update")
            
            # Try direct VTK color update
            if not update_success:
                update_success = self._force_vtk_color_update()
                if update_success:
                    print(f"   ✅ Main view updated (direct VTK with visibility)")
        
        # ✅ FALLBACK: Old method
        if not update_success:
            from gui.class_display import update_class_mode
            update_class_mode(self.app, force_refresh=True)
            print(f"   ✅ Main view refreshed (forced rebuild)")
            update_success = True
        
        # ✅ CRITICAL: Restore camera position IMMEDIATELY
        if saved_camera:
            try:
                camera = self.app.vtk_widget.renderer.GetActiveCamera()
                camera.SetPosition(saved_camera['position'])
                camera.SetFocalPoint(saved_camera['focal_point'])
                camera.SetViewUp(saved_camera['view_up'])
                camera.SetParallelScale(saved_camera['parallel_scale'])
                
                if saved_camera['parallel_projection']:
                    camera.ParallelProjectionOn()
                else:
                    camera.ParallelProjectionOff()
                
                self.app.vtk_widget.renderer.ResetCameraClippingRange()
                print(f"   📷✅ Camera restored")
            except Exception as e:
                print(f"   ⚠️ Camera restore failed: {e}")
        
        # Refresh cross-sections
        if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
            for view_idx in list(self.app.section_vtks.keys()):
                try:
                    if hasattr(self.app, '_refresh_single_section_view'):
                        self.app._refresh_single_section_view(view_idx)
                except Exception as e:
                    print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")
        
        # Update point statistics
        if hasattr(self.app, 'point_count_widget'):
            self.app.point_count_widget.schedule_update()
        
        # ✅ Force final render
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass
        
        mode_str = "by-class" if has_by_class_actors else "unified"
        print(f"✅ REFRESH COMPLETE ({mode_str} mode, visibility-aware: {update_success})\n")




    def _force_vtk_color_update(self):
        """
        ✅ ENHANCED: Direct VTK color update with VISIBLE CLASS FILTERING
        Only colors points whose class is checked in Display Mode dialog
        """
        print("   🎨 Direct VTK color update (visibility-aware)...")
        
        if not hasattr(self.app, 'vtk_widget'):
            print("   ❌ VTK widget not found")
            return False
        
        if not hasattr(self.app, 'class_palette'):
            print("   ❌ class_palette not found")
            return False
        
        try:
            import vtk
            from vtk.util import numpy_support
            import numpy as np
            
            classification = self.app.data.get("classification")
            if classification is None:
                print("   ❌ No classification data")
                return False
            
            # ✅ NEW: Get visible classes from Display Mode dialog
            visible_classes = set()
            display_dialog = getattr(self.app, 'display_mode_dialog', 
                                    getattr(self.app, 'display_dialog', None))
            
            if display_dialog and hasattr(display_dialog, 'table'):
                table = display_dialog.table
                print(f"   📋 Scanning Display Mode table ({table.rowCount()} rows)...")
                
                for row in range(table.rowCount()):
                    try:
                        # Method 1: Check if there's a checkbox widget in column 0
                        checkbox_item = table.cellWidget(row, 0)
                        code_item = table.item(row, 1)
                        
                        if code_item:
                            class_code = int(code_item.text())
                            
                            # Check if checkbox exists and is checked
                            if checkbox_item:
                                if hasattr(checkbox_item, 'isChecked'):
                                    if checkbox_item.isChecked():
                                        visible_classes.add(class_code)
                                elif hasattr(checkbox_item, 'checkState'):
                                    from PySide6.QtCore import Qt
                                    if checkbox_item.checkState() == Qt.CheckState.Checked:
                                        visible_classes.add(class_code)
                            else:
                                # No checkbox widget - check if item itself has checkState
                                if hasattr(code_item, 'checkState'):
                                    from PySide6.QtCore import Qt
                                    if code_item.checkState() == Qt.CheckState.Checked:
                                        visible_classes.add(class_code)
                                
                    except Exception as e:
                        print(f"      ⚠️ Row {row} parse error: {e}")
                        continue
            
            # If no Display Mode dialog or no visible classes found, show all
            if not visible_classes:
                print("   ⚠️ No visible classes found in Display Mode - showing ALL classes")
                visible_classes = set(np.unique(classification))
            else:
                print(f"   ✅ Visible classes (checked): {sorted(visible_classes)}")
            
            # Get unique classes in dataset
            unique_classes = np.unique(classification)
            print(f"   → Full dataset: {len(classification):,} points, {len(unique_classes)} classes")
            
            # ✅ Find the main point cloud actor
            target_actor = None
            target_point_count = None
            
            # Try to find actor in vtk_widget
            if hasattr(self.app.vtk_widget, 'actor'):
                # Single actor
                target_actor = self.app.vtk_widget.actor
                mapper = target_actor.GetMapper()
                if mapper:
                    input_data = mapper.GetInput()
                    if input_data:
                        target_point_count = input_data.GetNumberOfPoints()
                        print(f"   ✅ Found vtk_widget.actor: {target_point_count:,} points")
            
            # Try actors dictionary
            if not target_actor and hasattr(self.app.vtk_widget, 'actors'):
                actors = self.app.vtk_widget.actors
                
                if isinstance(actors, dict):
                    for key, actor in actors.items():
                        if actor:
                            try:
                                mapper = actor.GetMapper()
                                if mapper:
                                    input_data = mapper.GetInput()
                                    if input_data:
                                        pts = input_data.GetNumberOfPoints()
                                        if pts > 1000:
                                            if target_point_count is None or pts > target_point_count:
                                                target_actor = actor
                                                target_point_count = pts
                                                print(f"   ✅ Found actor '{key}': {pts:,} points")
                            except Exception:
                                pass
            
            if not target_actor:
                print("   ❌ No valid VTK actor found")
                return False
            
            print(f"   ✅ Using actor with {target_point_count:,} points")
            
            # ✅ Get downsample indices
            downsample_indices = self._find_downsample_indices(len(classification), target_point_count)
            
            if downsample_indices is None:
                print("   ❌ Could not find downsample indices")
                return False
            
            # Verify indices are valid
            if np.max(downsample_indices) >= len(classification):
                print(f"   ❌ Invalid indices! Max: {np.max(downsample_indices)}, Dataset: {len(classification)}")
                return False
            
            # ✅ Get classification for downsampled points
            downsampled_classification = classification[downsample_indices]
            print(f"   → Downsampled classes: {np.unique(downsampled_classification)}")
            
            # ✅ Create colors with VISIBILITY FILTERING
            colors = np.zeros((len(downsampled_classification), 3), dtype=np.uint8)
            
            visible_count = 0
            hidden_count = 0
            
            for cls in np.unique(downsampled_classification):
                mask = (downsampled_classification == cls)
                count = np.sum(mask)
                
                # ✅ Only color if class is VISIBLE (checked)
                if cls in visible_classes:
                    if cls in self.app.class_palette:
                        color = self.app.class_palette[cls].get('color', (128, 128, 128))
                        colors[mask] = color
                        visible_count += count
                        print(f"      ✅ Class {cls}: {count:,} points → RGB{color} (VISIBLE)")
                    else:
                        colors[mask] = (128, 128, 128)
                        visible_count += count
                        print(f"      ✅ Class {cls}: {count:,} points → RGB(128,128,128) (VISIBLE, no palette)")
                else:
                    # Class unchecked - leave as (0,0,0) = blank
                    hidden_count += count
                    print(f"      ❌ Class {cls}: {count:,} points → BLANK (HIDDEN)")
            
            print(f"   📊 Summary: {visible_count:,} visible, {hidden_count:,} hidden")
            
            # ✅ Update VTK actor colors
            vtk_colors = numpy_support.numpy_to_vtk(colors, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
            vtk_colors.SetName("Colors")
            
            mapper = target_actor.GetMapper()
            input_data = mapper.GetInput()
            input_data.GetPointData().SetScalars(vtk_colors)
            input_data.Modified()
            mapper.Modified()
            target_actor.Modified()
            
            print(f"   ✅ VTK colors updated ({target_point_count:,} points)")
            
            # Force render
            if hasattr(self.app.vtk_widget, 'renderer'):
                self.app.vtk_widget.renderer.Modified()
            
            if hasattr(self.app.vtk_widget, 'Render'):
                self.app.vtk_widget.Render()
            
            if hasattr(self.app.vtk_widget, 'render'):
                self.app.vtk_widget.render()
            
            self.app.vtk_widget.update()
            
            return True
            
        except Exception as e:
            print(f"   ❌ VTK color update failed: {e}")
            import traceback
            traceback.print_exc()
            return False


    def _find_downsample_indices(self, full_count, target_count):
        """Helper to find downsample indices from various sources"""
        
        # Try common attribute names
        for attr_name in ['downsample_indices', 'displayed_indices', 'visible_indices',
                        'current_indices', 'vtk_indices', 'display_mask', 'shown_indices']:
            if hasattr(self.app, attr_name):
                indices = getattr(self.app, attr_name)
                if indices is not None:
                    if isinstance(indices, np.ndarray):
                        # Direct index array
                        if len(indices) == target_count:
                            print(f"   ✅ Found: app.{attr_name}")
                            return indices
                        # Boolean mask
                        elif indices.dtype == bool and len(indices) == full_count:
                            idx_array = np.where(indices)[0]
                            if len(idx_array) == target_count:
                                print(f"   ✅ Found: app.{attr_name} (boolean mask)")
                                return idx_array
        
        # Try data object
        if hasattr(self.app, 'data'):
            for attr_name in ['downsample_indices', 'displayed_indices', 'vtk_indices']:
                if hasattr(self.app.data, attr_name):
                    indices = getattr(self.app.data, attr_name)
                    if indices is not None and isinstance(indices, np.ndarray):
                        if len(indices) == target_count:
                            print(f"   ✅ Found: app.data.{attr_name}")
                            return indices
        
        # Last resort: uniform sampling
        print(f"   ⚠️ No stored indices - using UNIFORM sampling (may cause misalignment)")
        step = max(1, full_count // target_count)
        return np.arange(0, full_count, step)[:target_count]



        
    def clear_fence_selection(self):
        """Clear all selected fences"""
        self.selected_fences = []
        self.permanent_fence_mode = False
        
        self.fence_status.setText("❌ No fence selected")
        self.fence_status.setStyleSheet("""
            QLabel {
                padding: 6px;
                background-color: #2c2c2c;
                border-radius: 3px;
                color: #f44336;
            }
        """)
        
        # ✅ ADDED: Clear visual highlights too
        self._clear_fence_highlights()
        self.update_fence_display() 
        print("🗑️ Cleared all fence selections and highlights")
        
    def _highlight_fence_on_hover(self, item):
        """Temporarily highlight fence in 3D view when hovering over it in list"""
        if not item:
            return
        
        try:
            shape = item.data(Qt.UserRole)
            coords = shape.get('coords', [])
            
            # Remove previous hover highlight
            if hasattr(self, '_hover_highlight_actor') and self._hover_highlight_actor:
                try:
                    self.app.vtk_widget.renderer.RemoveActor(self._hover_highlight_actor)
                except Exception:
                    pass
            
            # Create temporary yellow highlight
            
            # Use digitizer's method if available, otherwise create inline
            if hasattr(self.app, 'digitizer'):
                self._hover_highlight_actor = self.app.digitizer._make_polyline_actor(
                    coords,
                    color=(1, 1, 0),  # Yellow
                    width=6
                )
            else:
                # Fallback: create basic actor
                import vtk
                points = vtk.vtkPoints()
                for c in coords:
                    points.InsertNextPoint(c)
                
                line = vtk.vtkPolyLine()
                line.GetPointIds().SetNumberOfIds(len(coords))
                for i in range(len(coords)):
                    line.GetPointIds().SetId(i, i)
                
                cells = vtk.vtkCellArray()
                cells.InsertNextCell(line)
                
                polydata = vtk.vtkPolyData()
                polydata.SetPoints(points)
                polydata.SetLines(cells)
                
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputData(polydata)
                
                self._hover_highlight_actor = vtk.vtkActor()
                self._hover_highlight_actor.SetMapper(mapper)
                self._hover_highlight_actor.GetProperty().SetColor(1, 1, 0)
                self._hover_highlight_actor.GetProperty().SetLineWidth(6)
            
            self.app.vtk_widget.renderer.AddActor(self._hover_highlight_actor)
            self.app.vtk_widget.render()
            
        except Exception as e:
            print(f"⚠️ Hover highlight failed: {e}")  
            
            
    def update_fence_display(self):
        """Update the fence status display (no longer uses fence_list_widget)"""
        # ✅ SIMPLIFIED: Only update badge (fence_list_widget is removed)
        
        if not self.selected_fences:
            self.fence_count_badge.setText("0")
            return
        
        # Update badge with count
        self.fence_count_badge.setText(str(len(self.selected_fences)))
            
            
    def _highlight_selected_fences_in_3d(self, fence_list):
        """Highlight selected fences in blue in the 3D view"""
        try:
            # Remove old selection highlights
            if hasattr(self, '_selection_highlight_actors'):
                for actor in self._selection_highlight_actors:
                    try:
                        self.app.vtk_widget.renderer.RemoveActor(actor)
                    except Exception:
                        pass
            
            self._selection_highlight_actors = []
            
            # Get selected items
            selected_items = fence_list.selectedItems()
            
            if not selected_items:
                self.app.vtk_widget.render()
                return
            
            # Create blue highlight for each selected fence
            for item in selected_items:
                shape = item.data(Qt.UserRole)
                coords = shape.get('coords', [])
                
                # Create blue highlight actor
                if hasattr(self.app, 'digitizer'):
                    highlight_actor = self.app.digitizer._make_polyline_actor(
                        coords,
                        color=(0, 0.5, 1),  # Blue
                        width=5
                    )
                else:
                    # Fallback: create basic actor
                    import vtk
                    points = vtk.vtkPoints()
                    for c in coords:
                        points.InsertNextPoint(c)
                    
                    line = vtk.vtkPolyLine()
                    line.GetPointIds().SetNumberOfIds(len(coords))
                    for i in range(len(coords)):
                        line.GetPointIds().SetId(i, i)
                    
                    cells = vtk.vtkCellArray()
                    cells.InsertNextCell(line)
                    
                    polydata = vtk.vtkPolyData()
                    polydata.SetPoints(points)
                    polydata.SetLines(cells)
                    
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(polydata)
                    
                    highlight_actor = vtk.vtkActor()
                    highlight_actor.SetMapper(mapper)
                    highlight_actor.GetProperty().SetColor(0, 0.5, 1)  # Blue
                    highlight_actor.GetProperty().SetLineWidth(5)
                
                self.app.vtk_widget.renderer.AddActor(highlight_actor)
                self._selection_highlight_actors.append(highlight_actor)
            
            self.app.vtk_widget.render()
            print(f"🔵 Highlighted {len(selected_items)} selected fence(s) in blue")
            
        except Exception as e:
            print(f"⚠️ Selection highlight failed: {e}")

    # ==================== UNDO/REDO ====================
    def perform_undo(self):
        if getattr(self, '_undo_in_progress', False):
            print("⚪ InsideFenceDialog: Undo already in progress, ignoring")
            return
        
        self._undo_in_progress = True
        try:
            print("🔄 InsideFenceDialog: Performing CLASSIFICATION undo...")
            
            if not hasattr(self.app, 'undo_classification'):
                print("⚪ InsideFenceDialog: undo_classification not available")
                return
            
            display_mode = getattr(self.app, 'display_mode', None)
            print(f"🔍 DEBUG perform_undo: display_mode = '{display_mode}'")  # ← ADD HERE
            
            if display_mode == "shaded_class":
                self.app._skip_post_undo_refresh = True  # ← SET before call
            
            try:
                self.app.undo_classification()
            finally:
                self.app._skip_post_undo_refresh = False  # ← ALWAYS clear after call
                
                
            print(f"🔍 DEBUG after undo: display_mode = '{getattr(self.app, 'display_mode', None)}'")  # ← ADD HER
            
            # ✅ Now do post-undo work based on display mode
            if display_mode != "shaded_class":
                from gui.class_display import update_class_mode
                update_class_mode(self.app, force_refresh=True)
                print("   ✅ Main view refreshed (forced rebuild)")
            else:
                print("   ✅ Shading handled undo internally - skipping class_display rebuild")

            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in list(self.app.section_vtks.keys()):
                    try:
                        if hasattr(self.app, '_refresh_single_section_view'):
                            self.app._refresh_single_section_view(view_idx)
                    except Exception as e:
                        print(f"   ⚠️ Section {view_idx+1} refresh failed: {e}")

            if hasattr(self.app, 'point_count_widget'):
                self.app.point_count_widget.schedule_update()
            
            self.preview_label.setText("↶ Undo performed")
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 6px;
                    background-color: #3e2723;
                    border-radius: 3px;
                }
            """)
            print("✅ Classification undo performed")
        except Exception as e:
            self.app._skip_post_undo_refresh = False  # ← safety net
            print(f"❌ Undo failed: {e}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Undo Failed", f"Could not undo: {str(e)}")
        finally:
            self._undo_in_progress = False

    def perform_undo(self):
        if getattr(self, '_undo_in_progress', False):
            return
        
        self._undo_in_progress = True
        try:
            if not hasattr(self.app, 'undo_classification'):
                return
            
            print("🔄 InsideFenceDialog: Performing CLASSIFICATION undo...")
            
            # ✅ undo_classification handles ALL refresh internally
            # Do NOT trigger any additional refresh after this call
            self.app.undo_classification()
            
            # ✅ Only update cross-sections and stats — NO main view refresh
            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in list(self.app.section_vtks.keys()):
                    try:
                        if hasattr(self.app, '_refresh_single_section_view'):
                            self.app._refresh_single_section_view(view_idx)
                    except Exception:
                        pass

            if hasattr(self.app, 'point_count_widget'):
                self.app.point_count_widget.schedule_update()
            
            self.preview_label.setText("↶ Undo performed")
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #ff9800;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 6px;
                    background-color: #3e2723;
                    border-radius: 3px;
                }
            """)
            print("✅ Classification undo performed")
        except Exception as e:
            print(f"❌ Undo failed: {e}")
            QMessageBox.warning(self, "Undo Failed", f"Could not undo: {str(e)}")
        finally:
            self._undo_in_progress = False

    # ==================== CLASS MANAGEMENT ====================

    def populate_classes(self):
        """Populate class lists from Display Mode"""
        print(f"\n🔄 Populating InsideFenceDialog classes...")
        
        self.from_list.clear()
        self.to_combo.clear()
        
        # Standard class labels
        STANDARD_LEVELS = {
            0: "Created", 1: "Ground", 2: "Low vegetation",
            3: "Medium vegetation", 4: "High vegetation", 5: "Buildings",
            6: "Water", 7: "Railways", 8: "Railways (structure)",
            9: "Type 1 Street", 10: "Type 2 Street", 11: "Type 3 Street",
            12: "Type 4 Street", 13: "Bridge", 14: "Bare Conductors",
            15: "Elicord Overhead Cables", 16: "Pylons or Poles",
            17: "HV Overhead Lines", 18: "MV Overhead Lines",
            19: "LV Overhead Lines",
        }
        
        # Get classes from Display Mode
        class_list = []
        display_dialog = getattr(self.app, 'display_mode_dialog', getattr(self.app, 'display_dialog', None))
        
        if display_dialog and hasattr(display_dialog, 'table'):
            table = display_dialog.table
            for row in range(table.rowCount()):
                try:
                    code_item = table.item(row, 1)
                    if not code_item:
                        continue
                    
                    code = int(code_item.text())
                    desc_item = table.item(row, 2)
                    desc = desc_item.text() if desc_item else ""
                    
                    lvl_item = table.item(row, 4)
                    lvl = lvl_item.text() if lvl_item else ""
                    
                    if not lvl or lvl.strip() == "":
                        lvl = STANDARD_LEVELS.get(code, str(code))
                    
                    color_item = table.item(row, 5)
                    if color_item:
                        qcolor = color_item.background().color()
                        color = (qcolor.red(), qcolor.green(), qcolor.blue())
                    else:
                        color = (128, 128, 128)
                    
                    class_list.append({
                        'code': code, 'desc': desc, 'lvl': lvl, 'color': color
                    })
                except Exception:
                    continue
        
        # Fallback: Use app's class_palette
        if not class_list and hasattr(self.app, 'class_palette'):
            for code in sorted(self.app.class_palette.keys()):
                entry = self.app.class_palette[code]
                desc = entry.get("description", "")
                lvl = entry.get("lvl", "")
                
                if not lvl or lvl.strip() == "":
                    lvl = STANDARD_LEVELS.get(code, str(code))
                
                color = entry.get("color", (128, 128, 128))
                
                class_list.append({
                    'code': code, 'desc': desc, 'lvl': lvl, 'color': color
                })
        
        if not class_list:
            print("⚠️ No classes found")
            return
        
        class_list.sort(key=lambda x: x['code'])
        
        # Populate From list
        for cls in class_list:
            code = cls['code']
            lvl = cls['lvl']
            desc = cls['desc']
            color = cls['color']
            
            text = f"{code} - {lvl}" if lvl and lvl.strip() else f"{code}"
            if desc:
                text += f" ({desc})"
            
            icon = self.make_color_icon(color)
            
            item = QListWidgetItem(icon, text)
            item.setData(Qt.UserRole, code)
            self.from_list.addItem(item)
        
        # Populate To combo
        for cls in class_list:
            code = cls['code']
            lvl = cls['lvl']
            desc = cls['desc']
            color = cls['color']
            
            text = f"{code} - {lvl}" if lvl and lvl.strip() else f"{code}"
            if desc:
                text += f" ({desc})"
            
            icon = self.make_color_icon(color)
            self.to_combo.addItem(icon, text, code)
        
        print(f"✅ Populated InsideFenceDialog with {len(class_list)} classes")

    def on_from_selection_changed(self):
        """Update preview when From selection changes"""
        selected_items = self.from_list.selectedItems()
        if selected_items:
            codes = [item.data(Qt.UserRole) for item in selected_items]
            self.selected_classes_label.setText(f"✅ Selected From: {', '.join(map(str, codes))}")
            self.selected_classes_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 4px;
                    background-color: #1b5e20;
                    border-radius: 3px;
                }
            """)
        else:
            self.selected_classes_label.setText("Selected: None")
            self.selected_classes_label.setStyleSheet("""
                QLabel {
                    color: #aaaaaa;
                    font-size: 9px;
                    padding: 4px;
                    background-color: #2c2c2c;
                    border-radius: 3px;
                }
            """)

    def clear_from_selection(self):
        """Clear all From class selections"""
        self.from_list.clearSelection()
        self.on_from_selection_changed()

    def _get_selected_from_classes(self):
        """Get list of selected From class codes"""
        selected_items = self.from_list.selectedItems()
        return [item.data(Qt.UserRole) for item in selected_items]

    def on_classes_changed(self):
        """Preserve selections when classes change"""
        print("\n" + "="*60)
        print("🔄 INSIDE FENCE DIALOG: Detected PTC change from Display Mode")
        print("="*60)
        
        # Save current selections
        old_from_classes = self._get_selected_from_classes()
        old_to = self.to_combo.currentData()
        
        # ✅ BUG FIX: You were using the deprecated single-fence variable!
        has_fences = len(getattr(self, 'selected_fences', [])) > 0 
        
        print(f"   📋 Saving selections:")
        print(f"     From: {old_from_classes}")
        print(f"     To: {old_to}")
        print(f"     Fence: {'Selected' if has_fences else 'None'}")
        
        # Rebuild lists
        self.populate_classes()
        
        # Restore To selection
        restored_count = 0
        if old_to is not None:
            idx = self.to_combo.findData(old_to)
            if idx >= 0:
                self.to_combo.setCurrentIndex(idx)
                print(f"     ✅ Restored To: Class {old_to}")
                restored_count += 1
        
        # Restore From selections
        if old_from_classes:
            for code in old_from_classes:
                for i in range(self.from_list.count()):
                    item = self.from_list.item(i)
                    if item.data(Qt.UserRole) == code:
                        self.from_list.setItemSelected(item, True)
                        restored_count += 1
                        break
            print(f"     ✅ Restored {len(old_from_classes)} From classes")
        
        if has_fences:
            print(f"     ✅ Fence state preserved")
            restored_count += 1

        # ✅ BULLETPROOF FIX: The Display Mode wiped the VTK Renderer. 
        # We MUST force the Digitizer to push the shapes back to the GPU!
        if hasattr(self.app, 'digitizer'):
            print("   🛠️ Restoring physical fences to VTK view...")
            self.app.digitizer.rebind_drawings()
            
        # ✅ Restore the blue selection highlights on top of the fences
        if hasattr(self, '_restore_highlights_from_data'):
            print("   🛠️ Restoring blue selection highlights...")
            self._restore_highlights_from_data()
            
        print(f"✅ InsideFenceDialog updated ({restored_count} settings restored)")
        print("="*60 + "\n")
        
        self.on_from_selection_changed()
        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                "✅ Fences and classes restored after display update",
                2000
            )
    # ==================== PREVIEW & CONVERSION ====================

    def preview_conversion(self):
        """Preview how many points would be converted"""
        # ✅ CHANGED: Check plural fences
        if not self.selected_fences:
            QMessageBox.warning(self, "No Fence", "Please select at least one fence first")
            return
        
        from_classes = self._get_selected_from_classes()
        to_class = self.to_combo.currentData()
        
        if not from_classes:
            QMessageBox.warning(self, "No Selection", "Please select at least one From class")
            return
        
        if to_class is None:
            QMessageBox.warning(self, "No Selection", "Please select To class")
            return
        
        if to_class in from_classes:
            QMessageBox.warning(self, "Invalid Selection", 
                            "To class cannot be one of the selected From classes")
            return
        
        try:
            affected_count = self._calculate_conversion(
                from_classes, to_class, preview=True
            )
            
            if affected_count is None:
                return
            
            # ✅ CHANGED: Build message for multiple fences
            fence_count = len(self.selected_fences)
            fence_types = [f['type'] for f in self.selected_fences]
            fence_desc = f"{fence_count} fence(s)" if fence_count > 1 else self.selected_fences[0]['type']
            
            classes_str = ", ".join(map(str, from_classes))
            
            preview_msg = f"📊 Preview: {affected_count:,} points would be converted\n"
            preview_msg += f"(Classes {classes_str} inside {fence_desc}"
            
            if self.height_filter_enabled.isChecked():
                mode = self.height_mode_combo.currentData()
                if mode == "within":
                    preview_msg += f", heights {self.min_height_spin.value():.2f}m - {self.max_height_spin.value():.2f}m"
                elif mode == "above":
                    preview_msg += f", heights > {self.min_height_spin.value():.2f}m"
                elif mode == "below":
                    preview_msg += f", heights < {self.max_height_spin.value():.2f}m"
            
            preview_msg += ")"
            
            self.preview_label.setText(preview_msg)
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #2196f3;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 8px;
                    background-color: #1a237e;
                    border-radius: 3px;
                }
            """)
            
        except Exception as e:
            print(f"❌ Preview failed: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Preview Failed", str(e))

    def perform_conversion(self):
        """
        ✅ FIXED: Fast GPU injection when target class is visible (~100ms)
        Only rebuilds mesh when target class is HIDDEN from shading.
        """
        if not self.selected_fences:
            QMessageBox.warning(self, "No Fence", "Please select at least one fence first")
            return
        
        from_classes = self._get_selected_from_classes()
        to_class = self.to_combo.currentData()
        
        if not from_classes or to_class is None:
            QMessageBox.warning(self, "No Selection", "Please select both From and To classes")
            return
        
        if to_class in from_classes:
            QMessageBox.warning(self, "Invalid Selection", "To class cannot be in From classes")
            return

        fence_desc = f"{len(self.selected_fences)} fence(s)" if len(self.selected_fences) > 1 else self.selected_fences[0]['type']
        msg = f"Convert points inside {fence_desc} to class {to_class}?"
        
        if QMessageBox.question(self, "Confirm", msg, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return

        try:
            result = self._calculate_conversion(from_classes, to_class, preview=False)
            
            if not result:
                QMessageBox.information(self, "No Points", "No points found inside the fence criteria.")
                return

            if isinstance(result, tuple):
                converted_count, final_mask = result
            else:
                converted_count = result
                final_mask = None

            if not converted_count:
                return

            # ════════════════════════════════════════════════════════════
            # REFRESH LOGIC
            # ════════════════════════════════════════════════════════════
            display_mode = getattr(self.app, 'display_mode', None)
            
            if display_mode == "shaded_class" and final_mask is not None:
                import time
                t0 = time.perf_counter()
                
                # ✅ Get ACTUAL shading visibility (what the mesh was built with)
                shading_vis = None
                try:
                    from gui.shading_display import get_cache
                    cache = get_cache()
                    shading_vis = getattr(cache, 'visible_classes_set', None)
                    if shading_vis is not None and len(shading_vis) > 0:
                        shading_vis = shading_vis.copy()
                except Exception:
                    pass
                
                if shading_vis is None or len(shading_vis) == 0:
                    shading_vis = getattr(self.app, '_shading_visible_classes', None)
                    if shading_vis is not None and len(shading_vis) > 0:
                        shading_vis = shading_vis.copy()
                
                if shading_vis is None or len(shading_vis) == 0:
                    shading_vis = {
                        int(c) for c, e in self.app.class_palette.items()
                        if e.get("show", True)
                    }
                
                target_visible = int(to_class) in shading_vis
                source_visible = any(int(fc) in shading_vis for fc in from_classes)
                
                print(f"⚡ SHADING MODE: target={to_class} visible={target_visible}, "
                    f"source visible={source_visible}")
                
                if target_visible and source_visible:
                    # ══════════════════════════════════════════════════
                    # FAST PATH: Both source and target in mesh → color swap only
                    # ══════════════════════════════════════════════════
                    try:
                        from gui.shading_display import refresh_shaded_after_classification_fast
                        refresh_shaded_after_classification_fast(self.app, changed_mask=final_mask)
                        elapsed = (time.perf_counter() - t0) * 1000
                        print(f"⚡ Fast GPU injection: {elapsed:.0f}ms")
                    except Exception as e:
                        print(f"⚠️ Fast injection failed ({e}), rebuilding...")
                        self._shading_force_rebuild(shading_vis)
                
                elif not target_visible and source_visible:
                    # ══════════════════════════════════════════════════
                    # REBUILD: Source was visible, target is hidden
                    # Points must be REMOVED from mesh geometry
                    # ══════════════════════════════════════════════════
                    print(f"🙈 Target class {to_class} HIDDEN — must rebuild to remove geometry")
                    self._shading_force_rebuild(shading_vis)
                
                elif target_visible and not source_visible:
                    # ══════════════════════════════════════════════════
                    # REBUILD: Source was hidden, target is visible
                    # Points must be ADDED to mesh geometry
                    # ══════════════════════════════════════════════════
                    print(f"🙈 Source classes hidden, target visible — must rebuild to add geometry")
                    self._shading_force_rebuild(shading_vis)
                
                else:
                    # ══════════════════════════════════════════════════
                    # SKIP: Both hidden — mesh unchanged visually
                    # ══════════════════════════════════════════════════
                    print(f"⏭️ Both source and target hidden — no visual change needed")
            
            elif display_mode == "shaded_class" and final_mask is None:
                print("⚠️ No change mask — forcing rebuild")
                self._shading_force_rebuild(None)
            
            else:
                # Standard Point Cloud Refresh
                from gui.class_display import update_class_mode
                update_class_mode(self.app, force_refresh=True)

            # ════════════════════════════════════════════════════════════
            # CLEANUP
            # ════════════════════════════════════════════════════════════
            self.preview_label.setText(f"✅ Converted {converted_count:,} points")
            self.preview_label.setStyleSheet("""
                QLabel {
                    color: #4caf50;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 8px;
                    background-color: #1b5e20;
                    border-radius: 3px;
                }
            """)
            self._clear_fence_highlights()
            # ✅ Re-highlight fences in a distinct color (cyan) to show classified area
            self._highlight_classified_fences()

            if hasattr(self.app, 'digitizer') and self.app.digitizer:
                try:
                    self.app.digitizer.rebind_drawings()
                    print("   🖊️ Drawing actors rebound to overlay after shading rebuild")
                except Exception as _rb_err:
                    print(f"   ⚠️ rebind_drawings failed: {_rb_err}")

            if self.ribbon_parent:
                self.ribbon_parent.update_status(f"Converted {converted_count:,} points", "success")

            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in list(self.app.section_vtks.keys()):
                    try:
                        if hasattr(self.app, '_refresh_single_section_view'):
                            self.app._refresh_single_section_view(view_idx)
                    except Exception:
                        pass

            if hasattr(self.app, 'point_count_widget'):
                self.app.point_count_widget.schedule_update()

            QMessageBox.information(self, "Success", f"Converted {converted_count:,} points.")

        except Exception as e:
            print(f"❌ Conversion Error: {e}")
            import traceback
            traceback.print_exc()


    def _shading_force_rebuild(self, shading_vis):
        """Helper: Force full shading mesh rebuild preserving visibility"""
        try:
            from gui.shading_display import clear_shading_cache, update_shaded_class
            
            if shading_vis:
                for c in self.app.class_palette:
                    self.app.class_palette[c]["show"] = (int(c) in shading_vis)
            
            clear_shading_cache("fence conversion requires geometry change")
            update_shaded_class(
                self.app,
                getattr(self.app, "last_shade_azimuth", 45.0),
                getattr(self.app, "last_shade_angle", 45.0),
                getattr(self.app, "shade_ambient", 0.2),
                force_rebuild=True
            )
        except Exception as e:
            print(f"❌ Rebuild failed: {e}")
            from gui.class_display import update_class_mode
            update_class_mode(self.app, force_refresh=True)

    def _highlight_classified_fences(self):
        """Recolor the existing fence drawing actors to cyan — keeps them pickable/deletable"""
        if not self.selected_fences:
            return

        self._classified_fence_actors = []  # track which drawing actors we recolored

        for fence in self.selected_fences:
            actor = fence.get('actor')
            if actor:
                try:
                    actor.GetProperty().SetColor(0, 1, 1)
                    actor.GetProperty().SetLineWidth(4)
                    fence['classified_fence'] = True  # ✅ tag it
                    self._classified_fence_actors.append(actor)

                except Exception as e:
                    print(f"⚠️ Recolor failed: {e}")

        try:
            self.app.vtk_widget.render()
        except Exception:
            pass
        print(f"✅ Highlighted {len(self._classified_fence_actors)} classified fence(s) in cyan")

    # ==================== HELPER METHODS ====================

    @staticmethod
    def make_color_icon(rgb):
        """Create a color icon from RGB tuple"""
        pix = QPixmap(20, 12)
        pix.fill(QColor(*rgb))
        return QIcon(pix)

    def naksha_dark_theme(self):
        """Return 'Obsidian & Teal' theme stylesheet"""
        return """
            QDialog, QWidget {
                background-color: #0a0a0a;
                color: #eeeeee;
                font-family: "Segoe UI";
            }
            /* Teal Section Headers */
            QLabel#header_label {
                color: #00c8aa;
                font-weight: bold;
                text-transform: uppercase;
                letter-spacing: 1px;
                font-size: 10px;
            }
            QListWidget, QComboBox, QDoubleSpinBox {
                background-color: #121212;
                color: #ffffff;
                border: 1px solid #222222;
                border-radius: 4px;
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #00c8aa;
                color: #000000;
                border-radius: 3px;
            }
            /* ✅ ADD: Proper QComboBox dropdown styling */
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid #888888;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #ffffff;
                selection-background-color: #00c8aa;
                selection-color: #000000;
                border: 1px solid #333333;
            }
            QCheckBox {
                color: #aaaaaa;
                font-size: 10px;
            }
            QPushButton {
                background-color: #222222;
                color: #ffffff;
                border: 1px solid #333333;
                padding: 8px;
                border-radius: 4px;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #333333;
            }
            /* Bright Teal Action Button */
            QPushButton#primary_btn {
                background-color: #00c8aa;
                color: #000000;
                font-weight: bold;
                border: none;
            }
            QPushButton#primary_btn:hover {
                background-color: #00e6c3;
            }
        """
class SyncViewsDialog(QDialog):
    """
    Synchronize Views dialog like MicroStation.
    Rows:
      View N: [No synch | Match]  [View 1..View 5]
    """
    def __init__(self, app, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setWindowTitle("Synchronize Views")
        self.setModal(False)
        self.setMinimumWidth(280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self.rows = []
        self.num_views = 5  # You currently support View 1..View 5

        for v in range(1, self.num_views + 1):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)

            label = QLabel(f"View {v}:")
            label.setFixedWidth(50)

            mode_combo = QComboBox()
            mode_combo.addItems(["No synch", "Match"])

            source_combo = QComboBox()
            for s in range(1, self.num_views + 1):
                source_combo.addItem(f"View {s}", s)

            row_layout.addWidget(label)
            row_layout.addWidget(mode_combo)
            row_layout.addWidget(source_combo)
            layout.addLayout(row_layout)

            row = {"view_num": v, "mode": mode_combo, "source": source_combo}
            self.rows.append(row)

            mode_combo.currentIndexChanged.connect(lambda idx, r=row: self._update_row_enabled(r))

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._apply_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_from_app_state()
        for r in self.rows:
            self._update_row_enabled(r)

    def _update_row_enabled(self, row):
        is_match = (row["mode"].currentIndex() == 1)
        row["source"].setEnabled(is_match)

    def _load_from_app_state(self):
        """
        Load current settings from app.view_sync_map with semantics:

        view_sync_map[target_idx] = source_idx

        But in the UI, each row is:

        "View A : [mode] [View B]"

        and represents:

        View B = Match View A

        i.e. A = source, B = target.
        """
        match_map = getattr(self.app, "view_sync_map", {})

        for row in self.rows:
            source_view_num = row["view_num"]   # left "View A"
            source_idx = source_view_num - 1

            # Find any target that is set to match this source
            target_view_num = None
            for target_idx, src_idx in match_map.items():
                if src_idx == source_idx:
                    target_view_num = target_idx + 1
                    break

            if target_view_num is not None:
                # This source has at least one target; show "Match target_view_num"
                row["mode"].setCurrentIndex(1)  # Match
                i = row["source"].findData(target_view_num)
                if i >= 0:
                    row["source"].setCurrentIndex(i)
            else:
                # No target currently matches this source
                row["mode"].setCurrentIndex(0)  # No synch
                # (we leave source combo as-is; it doesn't matter when mode=No synch)
    def _apply_to_app(self):
        """
        Apply mappings using app.set_view_sync() with your dialog semantics:

        Row: "View A : Match View B"
        Means: View B = Match View A

        Fix:
        - Do NOT clear a target just because mode is "No synch" and the combo happens
        to be sitting on View 1 by default.
        - Only clear mappings that are actually affected.
        """
        existing = dict(getattr(self.app, "view_sync_map", {}) or {})

        desired = {}            # target_idx -> source_idx
        sources_no_sync = set() # source_idx that user set to "No synch" explicitly (in UI)

        # 1) Read UI into desired mapping
        for row in self.rows:
            source_view_num = int(row["view_num"])          # A (1-based)
            source_idx = source_view_num - 1                # A (0-based)
            mode = row["mode"].currentIndex()               # 0=No synch, 1=Match

            if mode == 0:
                sources_no_sync.add(source_idx)
                continue

            target_view_num = row["source"].currentData()   # B (1-based)
            if target_view_num is None:
                continue

            target_idx = int(target_view_num) - 1

            # Ignore self-sync (treat as no mapping)
            if target_idx == source_idx:
                continue

            desired[target_idx] = source_idx

        # 2) Decide what to clear (unique targets only)
        to_clear = set()

        for target_idx, src_idx in existing.items():
            # If this target is being re-mapped to a different source, clear it first
            if target_idx in desired and desired[target_idx] != src_idx:
                to_clear.add(target_idx)
                continue

            if (target_idx not in desired) and (src_idx in sources_no_sync):
                to_clear.add(target_idx)

        # 3) Apply clears
        for target_idx in sorted(to_clear):
            self.app.set_view_sync(target_idx + 1, None)

        # 4) Apply new mappings
        for target_idx, source_idx in desired.items():
            self.app.set_view_sync(target_idx + 1, source_idx + 1)

    def _apply_and_close(self):
        self._apply_to_app()
        self.accept()


class AIRibbon(QWidget):
    """Ribbon for AI Classification"""
    
    ai_classify_requested = Signal()
    
    def __init__(self, parent=None, app=None):
        super().__init__(parent)
        self.app = app
        self.build_ribbon()
        
    def build_ribbon(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # AI Classification
        ai_section = RibbonSection("AI", self)
        ai_section.add_button(
            "Start",
            "🚀",
            self._start_classification,
            toggleable=False
        )
        layout.addWidget(ai_section)
        
        layout.addStretch()
    
    def _start_classification(self):
        """Trigger AI classification workflow"""
        try:
            app = getattr(self, 'app', None)
            if app is None:
                # Fallback if self.app is somehow missing
                app = getattr(self.parent(), 'app', None)
            if app is None:
                app = self.parent().parent().parent()
            
            # Check if LAZ file is loaded
            if not hasattr(app, 'data') or app.data is None:
                QMessageBox.warning(
                    self,
                    "No Data Loaded",
                    "Please load a LAZ file before running AI classification."
                )
                return
            
            # Import and show AI dialog
            from gui.ai_dialog import show_ai_classification_dialog
            show_ai_classification_dialog(app)
            
        except Exception as e:
            print(f"⚠️ AI classification failed: {e}")
            import traceback
            traceback.print_exc()

class VertexInsertSettingsDialog(QDialog):
    """Settings dialog for Vertex insertion tool"""

    def __init__(self, current_auto_drag=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vertex Tool Settings")
        self.setModal(True)
        self.resize(350, 180)

        from gui.theme_manager import get_dialog_stylesheet
        self.setStyleSheet(get_dialog_stylesheet())
       
        layout = QVBoxLayout()
        mode_group = QGroupBox("Insertion Mode")
        mode_layout = QVBoxLayout()
        self.insert_only_radio = QRadioButton("Insert only (click to place vertex)")
        self.insert_drag_radio = QRadioButton("Insert and drag (click, then move to position)")
       
        if current_auto_drag:
            self.insert_drag_radio.setChecked(True)
        else:
            self.insert_only_radio.setChecked(True)

        mode_layout.addWidget(self.insert_only_radio)
        mode_layout.addWidget(self.insert_drag_radio)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)

        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout) 
        self.setLayout(layout)
   
    def get_auto_drag_mode(self):
        """Return True if insert-and-drag mode is selected"""
        return self.insert_drag_radio.isChecked()

class VertexMoveSettingsDialog(QDialog):
    """Settings dialog for Vertex Move tool"""

    def __init__(self, current_mode='click', parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vertex Move Settings")
        self.setModal(True)
        self.resize(350, 200)

        from gui.theme_manager import get_dialog_stylesheet
        self.setStyleSheet(get_dialog_stylesheet())
       
        layout = QVBoxLayout()
        mode_group = QGroupBox("Move Mode")
        mode_layout = QVBoxLayout()
        self.click_mode_radio = QRadioButton("Click to select, click again to place")
        self.drag_mode_radio = QRadioButton("Click and drag (hold mouse button)")
        if current_mode == 'drag':
            self.drag_mode_radio.setChecked(True)
        else:
            self.click_mode_radio.setChecked(True)
        mode_layout.addWidget(self.click_mode_radio)
        mode_layout.addWidget(self.drag_mode_radio)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
       
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        self.setLayout(layout)
   
    def get_move_mode(self):
        """Return 'click' or 'drag' based on selection"""
        return 'drag' if self.drag_mode_radio.isChecked() else 'click'
