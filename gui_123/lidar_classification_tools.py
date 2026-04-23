import numpy as np
import os
from scipy.spatial import cKDTree, Delaunay
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox,
    QPushButton, QProgressDialog, QMessageBox, QApplication,
    QListWidget, QListWidgetItem, QAbstractItemView, QFrame,
    QSizePolicy, QWidget
)
from PySide6.QtCore import Qt, QThread, Signal, QRect, QTimer, QEvent
from PySide6.QtGui import QColor, QPixmap, QIcon, QPainter, QBrush


def _apply_dialog_icon(dialog, app=None):
    """Apply main app icon/logo to classification dialogs."""
    try:
        icon = None
        if app is not None and hasattr(app, "windowIcon"):
            app_icon = app.windowIcon()
            if app_icon is not None and not app_icon.isNull():
                icon = app_icon
        if icon is None:
            logo_path = os.path.join(os.path.dirname(__file__), "icons", "logo.png")
            if os.path.exists(logo_path):
                icon = QIcon(logo_path)
        if icon is not None and not icon.isNull():
            dialog.setWindowIcon(icon)
    except Exception:
        pass


def _get_class_colors(app) -> dict:
    """
    Build {class_code: QColor} from available display/palette sources.
    Falls back to deterministic LAS default colors when runtime colors
    are not exposed yet.
    """
    colors = {}
    if not app:
        return colors

    # Source 1: table backgrounds in display dialogs
    for dlg_attr in ("display_mode_dialog", "display_dialog",
                     "class_display_dialog", "classification_dialog"):
        dlg = getattr(app, dlg_attr, None)
        table = getattr(dlg, "table", None) if dlg is not None else None
        if table is None:
            continue
        for row in range(table.rowCount()):
            code = None
            for col in (1, 0, 2):
                item = table.item(row, col)
                if item is None:
                    continue
                try:
                    code = int(item.text())
                    break
                except Exception:
                    continue
            if code is None:
                continue
            # Prefer dedicated color column background, then any background.
            color = None
            for col in (5, 4, 3, 2, 1, 0):
                item = table.item(row, col)
                if item is None:
                    continue
                bg = item.background()
                if isinstance(bg, QBrush) and bg.style() != 0:
                    c = bg.color()
                    if c.isValid() and c.alpha() > 0:
                        color = c
                        break
            if color is not None and code not in colors:
                colors[code] = color
        if colors:
            break

    # Source 2: palette dicts
    for palette_attr in ("class_palette", "classification_palette",
                         "las_class_palette", "point_classes"):
        palette = getattr(app, palette_attr, None)
        if not isinstance(palette, dict):
            continue
        for code_key, info in palette.items():
            try:
                code = int(code_key)
            except Exception:
                continue
            if code in colors or not isinstance(info, dict):
                continue
            val = (info.get("color") or info.get("colour") or info.get("rgb")
                   or info.get("swatch") or info.get("background"))
            c = None
            if isinstance(val, QColor):
                c = val
            elif isinstance(val, (tuple, list)) and len(val) >= 3:
                try:
                    r, g, b = [float(x) for x in val[:3]]
                    if all(v <= 1.0 for v in (r, g, b)):
                        c = QColor.fromRgbF(r, g, b)
                    else:
                        c = QColor(int(r), int(g), int(b))
                except Exception:
                    pass
            elif isinstance(val, str):
                qc = QColor(val)
                if qc.isValid():
                    c = qc
            if c is None:
                r = info.get("r", info.get("red"))
                g = info.get("g", info.get("green"))
                b = info.get("b", info.get("blue"))
                if r is not None and g is not None and b is not None:
                    try:
                        rf, gf, bf = float(r), float(g), float(b)
                        if all(v <= 1.0 for v in (rf, gf, bf)):
                            c = QColor.fromRgbF(rf, gf, bf)
                        else:
                            c = QColor(int(rf), int(gf), int(bf))
                    except Exception:
                        pass
            if c is not None and c.isValid():
                colors[code] = c

    # Final fallback: deterministic LAS colors for any known class codes
    fallback_map = _default_las_colors()
    for code in _get_las_classes(app).keys():
        try:
            code = int(code)
        except Exception:
            continue
        if code not in colors and code in fallback_map:
            colors[code] = fallback_map[code]

    return colors

def _debug_color_sources(app):
    """Print diagnostic info about where colors might be stored."""
    print("   === DEBUG: Searching for color data ===")
    
    # Check display dialog table structure
    for dlg_attr in ('display_mode_dialog', 'display_dialog'):
        dlg = getattr(app, dlg_attr, None)
        if dlg is None:
            print(f"   {dlg_attr}: None")
            continue
        print(f"   {dlg_attr}: EXISTS ({type(dlg).__name__})")
        table = getattr(dlg, 'table', None)
        if table is None:
            print(f"      table: None")
            # Check other widget names
            for child_name in dir(dlg):
                child = getattr(dlg, child_name, None)
                if hasattr(child, 'rowCount'):
                    print(f"      Found table-like: {child_name} ({type(child).__name__})")
            continue
        
        print(f"      table: {table.rowCount()} rows × {table.columnCount()} cols")
        
        # Inspect first row in detail
        if table.rowCount() > 0:
            for col in range(table.columnCount()):
                item = table.item(0, col)
                widget = table.cellWidget(0, col)
                
                item_info = "None"
                if item:
                    bg = item.background()
                    item_info = (f"text='{item.text()}' "
                                f"bg_style={bg.style() if isinstance(bg, QBrush) else 'N/A'} "
                                f"bg_color={bg.color().name() if isinstance(bg, QBrush) and bg.style() != 0 else 'none'}")
                
                widget_info = "None"
                if widget:
                    ss = widget.styleSheet()
                    widget_info = (f"{type(widget).__name__} "
                                  f"ss_len={len(ss)} "
                                  f"autoFill={widget.autoFillBackground()} "
                                  f"ss_preview='{ss[:80]}'" if ss else
                                  f"{type(widget).__name__} no_stylesheet")
                
                print(f"      Row0 Col{col}: item=[{item_info}]  widget=[{widget_info}]")
    
    # Check palette dicts
    for attr in ('class_palette', 'class_colors', 'classification_colors'):
        val = getattr(app, attr, None)
        if val is None:
            continue
        if isinstance(val, dict) and val:
            first_key = next(iter(val))
            first_val = val[first_key]
            print(f"   {attr}: dict with {len(val)} entries, "
                  f"first: {first_key} → {type(first_val).__name__}: {first_val}")


def _make_color_icon(color: QColor, size: int = 14) -> QIcon:
    """Create a small square color swatch icon."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor(100, 100, 100))
    painter.setBrush(color)
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 2, 2)
    painter.end()
    return QIcon(pixmap)


def _make_color_pixmap(color: QColor, w: int = 16, h: int = 16) -> QPixmap:
    """Create a small square color swatch pixmap."""
    pixmap = QPixmap(w, h)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QColor(100, 100, 100))
    painter.setBrush(color)
    painter.drawRoundedRect(1, 1, w - 2, h - 2, 2, 2)
    painter.end()
    return pixmap


def _make_multi_class_icon(codes, colors_dict, size=14, max_swatches=5):
    """
    Create a combined icon showing up to max_swatches color patches
    side by side for a multi-class selection.
    """
    if not codes or not colors_dict:
        return None

    available = []
    for code in sorted(codes):
        if code in colors_dict:
            available.append(colors_dict[code])

    if not available:
        return None

    show = available[:max_swatches]
    n = len(show)
    swatch_w = size
    gap = 2
    total_w = n * swatch_w + (n - 1) * gap

    pixmap = QPixmap(total_w, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    for i, color in enumerate(show):
        x = i * (swatch_w + gap)
        painter.setPen(QColor(100, 100, 100))
        painter.setBrush(color)
        painter.drawRoundedRect(x + 1, 1, swatch_w - 2, size - 2, 2, 2)

    painter.end()
    return QIcon(pixmap)

# ═══════════════════════════════════════════════════════════════════════
# PERSISTENT CLASS SETTINGS
# ═══════════════════════════════════════════════════════════════════════
class PersistentClassSettings:
    """
    Singleton store that remembers the last-used class codes and parameter
    values for each classification dialog.

    Keys use the pattern:
        "low_points.from_class"   → [1]
        "low_points.to_class"     → [7]
        "isolated.from_class"     → [2, 3, 4, 5]
        "ground.terrain_angle"    → 88.0
        ...
    """
    _store: dict = {}

    @classmethod
    def get(cls, key: str, default=None):
        return cls._store.get(key, default)

    @classmethod
    def set(cls, key: str, value):
        cls._store[key] = value

    @classmethod
    def get_codes(cls, key: str, default_codes: list) -> list:
        val = cls._store.get(key)
        if val is not None and isinstance(val, list):
            return list(val)
        return list(default_codes)

    @classmethod
    def set_codes(cls, key: str, codes: list):
        cls._store[key] = list(codes)

    @classmethod
    def get_value(cls, key: str, default):
        val = cls._store.get(key)
        return val if val is not None else default

    @classmethod
    def set_value(cls, key: str, value):
        cls._store[key] = value


# ═══════════════════════════════════════════════════════════════════════
# DYNAMIC PTC CLASSES HELPER
# ═══════════════════════════════════════════════════════════════════════
def _get_las_classes(app):
    """
    Build {code: "code - Name"} from every possible source on app.
    Tries multiple attribute names so it works regardless of which
    dialog/palette structure the host application uses.
    """
    classes = {}

    if not app:
        return _default_las_classes()

    # ── SOURCE 1: display_mode_dialog / display_dialog table ─────────
    for dlg_attr in ('display_mode_dialog', 'display_dialog',
                     'class_display_dialog', 'classification_dialog'):
        dlg = getattr(app, dlg_attr, None)
        if dlg is None:
            continue
        # Try table widget (various column layouts)
        table = getattr(dlg, 'table', None)
        if table is not None:
            for row in range(table.rowCount()):
                try:
                    # Try columns 0,1 for code; columns 1,2,3,4,5 for name
                    code = None
                    for col in (1, 0, 2):
                        item = table.item(row, col)
                        if item:
                            try:
                                code = int(item.text())
                                break
                            except (ValueError, TypeError):
                                continue
                    if code is None:
                        continue
                    # Try columns 4,3,2,5,1 for the human-readable name
                    name = ""
                    for col in (4, 3, 2, 5, 1):
                        item = table.item(row, col)
                        if item:
                            txt = item.text().strip()
                            if txt and not txt.isdigit():
                                name = txt
                                break
                    if code not in classes:
                        classes[code] = f"{code} - {name}" if name else str(code)
                except Exception:
                    continue
        if classes:
            break

    # ── SOURCE 2: class_palette dict ─────────────────────────────────
    for palette_attr in ('class_palette', 'classification_palette',
                         'las_class_palette', 'point_classes'):
        palette = getattr(app, palette_attr, None)
        if not palette or not isinstance(palette, dict):
            continue
        for code, info in palette.items():
            try:
                code = int(code)
            except (ValueError, TypeError):
                continue
            if code in classes:
                continue
            if isinstance(info, dict):
                name = (info.get('name', '') or info.get('lvl', '') or
                        info.get('label', '') or info.get('description', '') or
                        info.get('title', '') or '')
            elif isinstance(info, str):
                name = info
            else:
                name = ''
            classes[code] = f"{code} - {name}" if name.strip() else str(code)
        if classes:
            break

    # ── SOURCE 3: class_names / class_labels dict ─────────────────────
    for names_attr in ('class_names', 'class_labels', 'las_classes',
                       'classification_names', 'point_class_names'):
        names = getattr(app, names_attr, None)
        if not names or not isinstance(names, dict):
            continue
        for code, name in names.items():
            try:
                code = int(code)
            except (ValueError, TypeError):
                continue
            if code not in classes:
                classes[code] = f"{code} - {name}" if str(name).strip() else str(code)
        if classes:
            break

    # ── SOURCE 4: scan data classification array for unique codes ─────
    if not classes:
        data = getattr(app, 'data', None)
        if data is not None:
            cls_arr = data.get('classification') if isinstance(data, dict) else getattr(data, 'classification', None)
            if cls_arr is not None:
                import numpy as np
                for code in np.unique(cls_arr):
                    try:
                        code = int(code)
                        if code not in classes:
                            classes[code] = str(code)
                    except Exception:
                        continue

    # ── FALLBACK: standard LAS class names ───────────────────────────
    if not classes:
        return _default_las_classes()

    # Fill in standard names for any codes that only have a bare number
    _std = _standard_las_names()
    for code, label in classes.items():
        if label == str(code) and code in _std:
            classes[code] = f"{code} - {_std[code]}"

    return classes


def _standard_las_names():
    """Standard ASPRS LAS point class names."""
    return {
        0:  "Never Classified",
        1:  "Unclassified",
        2:  "Ground",
        3:  "Low Vegetation",
        4:  "Medium Vegetation",
        5:  "High Vegetation",
        6:  "Building",
        7:  "Low Point (Noise)",
        8:  "Reserved",
        9:  "Water",
        10: "Rail",
        11: "Road Surface",
        12: "Reserved",
        13: "Wire – Guard",
        14: "Wire – Conductor",
        15: "Transmission Tower",
        16: "Wire – Connector",
        17: "Bridge Deck",
        18: "High Noise",
        19: "Overhead Structure",
        20: "Ignored Ground",
        21: "Snow",
        22: "Temporal Exclusion",
    }


def _default_las_classes():
    """Return standard LAS classes when no app data is available."""
    return {code: f"{code} - {name}"
            for code, name in _standard_las_names().items()}


def _default_las_colors():
    """Deterministic fallback class colors (QColor) keyed by LAS class code."""
    rgb = {
        0: (160, 160, 160), 1: (235, 235, 235), 2: (166, 124, 82),
        3: (141, 211, 99), 4: (88, 180, 66), 5: (40, 124, 46),
        6: (232, 179, 86), 7: (216, 69, 69), 8: (120, 120, 120),
        9: (65, 143, 222), 10: (234, 172, 74), 11: (120, 120, 120),
        12: (120, 120, 120), 13: (255, 220, 88), 14: (255, 201, 40),
        15: (176, 112, 255), 16: (204, 160, 255), 17: (115, 189, 255),
        18: (255, 64, 129), 19: (255, 133, 0), 20: (115, 115, 115),
        21: (245, 250, 255), 22: (255, 105, 180),
    }
    return {code: QColor(r, g, b) for code, (r, g, b) in rgb.items()}


# ═══════════════════════════════════════════════════════════════════════
# DIALOG STYLE
# ═══════════════════════════════════════════════════════════════════════
def _get_dialog_style():
    from gui.theme_manager import ThemeColors as _TC
    return f"""
QDialog {{
    background-color: {_TC.get('bg_primary')};
    color: {_TC.get('text_primary')};
}}
QGroupBox {{
    background-color: transparent;
    border: none;
    margin-top: 6px;
    padding-top: 6px;
    font-weight: normal;
    color: {_TC.get('text_primary')};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 0px;
    padding: 0 0px;
    font-size: 10pt;
    font-weight: 600;
    color: {_TC.get('text_primary')};
}}
QLabel {{ color: {_TC.get('text_primary')}; font-size: 11px; }}
QComboBox, QDoubleSpinBox, QSpinBox {{
    background-color: {_TC.get('bg_input')}; color: {_TC.get('text_primary')};
    border: 1px solid {_TC.get('border_light')}; border-radius: 4px;
    padding: 3px 6px; min-height: 22px;
}}
QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover {{ border: 1px solid {_TC.get('accent')}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QCheckBox {{ color: {_TC.get('text_primary')}; spacing: 6px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {_TC.get('border_light')}; border-radius: 3px;
    background-color: {_TC.get('bg_input')};
}}
QCheckBox::indicator:checked {{ background-color: {_TC.get('accent')}; border-color: {_TC.get('accent')}; }}
QPushButton {{
    background-color: {_TC.get('bg_button')}; color: {_TC.get('text_primary')};
    border: 1px solid {_TC.get('border_light')}; border-radius: 5px;
    padding: 6px 20px; font-weight: bold; min-width: 70px;
}}
QPushButton:hover {{ background-color: {_TC.get('bg_button_hover')}; border-color: {_TC.get('accent')}; }}
QPushButton:pressed {{ background-color: {_TC.get('accent')}; color: {_TC.get('text_on_active')}; }}
QPushButton#okButton {{ background-color: {_TC.get('bg_button')}; border-color: {_TC.get('border_light')}; color: {_TC.get('text_primary')}; }}
QPushButton#okButton:hover {{ background-color: {_TC.get('bg_button_hover')}; border-color: {_TC.get('accent')}; }}
QPushButton#arrowBtn {{
    background-color: {_TC.get('bg_button')}; border: 1px solid {_TC.get('border_light')}; border-radius: 3px;
    padding: 2px 6px; min-width: 28px; max-width: 28px;
    font-weight: normal; font-size: 10px;
}}
QPushButton#arrowBtn:hover {{ border-color: {_TC.get('accent')}; background-color: {_TC.get('bg_button_hover')}; }}
QPushButton#fenceBtn {{
    background-color: {_TC.get('bg_button')}; border: 1px solid {_TC.get('border_light')};
    border-radius: 4px; padding: 4px 10px;
    font-weight: bold; font-size: 10px; min-width: 130px;
    color: {_TC.get('text_primary')};
}}
QPushButton#fenceBtn:hover {{ background-color: {_TC.get('bg_button_hover')}; border-color: {_TC.get('accent')}; }}
QPushButton#fenceClearBtn {{
    background-color: {_TC.get('bg_button')}; border: 1px solid {_TC.get('border_light')};
    border-radius: 4px; padding: 4px 8px;
    font-size: 10px; min-width: 50px;
}}
QPushButton#fenceClearBtn:hover {{ background-color: {_TC.get('danger_hover')}; border-color: {_TC.get('danger_hover')}; color: {_TC.get('text_on_active')}; }}
QPushButton#minimizeBtn {{
    background-color: {_TC.get('bg_button')}; border: 1px solid {_TC.get('border_light')};
    border-radius: 4px; padding: 3px 10px;
    font-size: 11px; font-weight: bold; min-width: 28px; max-width: 36px;
    color: {_TC.get('text_primary')};
}}
QPushButton#minimizeBtn:hover {{ background-color: {_TC.get('bg_button_hover')}; border-color: {_TC.get('accent')}; }}
QListWidget {{
    background-color: {_TC.get('bg_input')}; color: {_TC.get('text_primary')};
    border: 1px solid {_TC.get('border_light')}; border-radius: 4px;
}}
QListWidget::item:selected {{ background-color: {_TC.get('bg_button_hover')}; color: {_TC.get('text_primary')}; }}
QListWidget::item:hover {{ background-color: {_TC.get('bg_button_hover')}; }}
QFrame[frameShape="4"] {{ color: {_TC.get('border_light')}; }}
"""


def _note_text_style():
    from gui.theme_manager import ThemeColors as _TC
    return (
        f"color:{_TC.get('text_secondary')}; "
        "font-size:9px; font-style:italic; padding:2px 4px;"
    )


def _get_inline_multiselect_style():
    from gui.theme_manager import ThemeColors as _TC
    return f"""
QListWidget {{
    background-color: {_TC.get('bg_input')};
    border: 1px solid {_TC.get('border_light')};
    border-radius: 4px;
    min-height: 90px;
    max-height: 120px;
}}
QListWidget::item {{ padding: 2px 6px; }}
QListWidget::item:selected {{ background-color: {_TC.get('accent')}; color: {_TC.get('text_on_active')}; }}
QListWidget::item:hover:!selected {{ background-color: {_TC.get('bg_button_hover')}; }}
"""

def _get_fence_picker_style():
    from gui.theme_manager import ThemeColors as _TC
    return f"""
QDialog {{ background-color: {_TC.get('bg_primary')}; color: {_TC.get('text_primary')}; }}
QLabel {{ color: {_TC.get('text_primary')}; font-size: 11px; }}
QListWidget {{
    background-color: {_TC.get('bg_input')}; border: 1px solid {_TC.get('border_light')};
    border-radius: 4px; padding: 4px;
}}
QListWidget::item {{ background: transparent; border: none; padding: 2px; }}
QCheckBox {{ color: {_TC.get('text_primary')}; font-size: 11px; padding: 8px; font-weight: bold; }}
QCheckBox::indicator {{ width: 18px; height: 18px; }}
QCheckBox::indicator:unchecked {{
    background-color: {_TC.get('bg_button')}; border: 1px solid {_TC.get('border_light')}; border-radius: 3px;
}}
QCheckBox::indicator:checked {{
    background-color: {_TC.get('accent')}; border: 1px solid {_TC.get('accent')}; border-radius: 3px;
}}
QPushButton {{
    background-color: {_TC.get('bg_button')}; color: {_TC.get('text_primary')};
    border: 1px solid {_TC.get('border_light')}; border-radius: 4px;
    padding: 5px 14px; font-size: 10px; font-weight: bold;
}}
QPushButton:hover {{ background-color: {_TC.get('bg_button_hover')}; border-color: {_TC.get('accent')}; }}
"""

# Style for the minimized chip widget
def _get_chip_style():
    from gui.theme_manager import ThemeColors as _TC
    return f"""
QWidget#minimizedChip {{
    background-color: {_TC.get('bg_secondary')};
    border: 1px solid {_TC.get('accent')};
    border-radius: 6px;
}}
QLabel#chipLabel {{
    color: {_TC.get('accent')};
    font-size: 10px;
    font-weight: bold;
    padding: 2px 6px;
}}
QPushButton#chipRestoreBtn {{
    background-color: {_TC.get('bg_button')};
    border: none;
    border-radius: 4px;
    color: {_TC.get('accent')};
    font-size: 10px;
    font-weight: bold;
    padding: 2px 8px;
    min-width: 0;
}}
QPushButton#chipRestoreBtn:hover {{
    background-color: {_TC.get('bg_button_hover')};
    color: {_TC.get('accent_hover')};
}}
"""


# ═══════════════════════════════════════════════════════════════════════
# MINIMIZED CHIP WIDGET
# ═══════════════════════════════════════════════════════════════════════
class _MinimizedChip(QWidget):
    """
    A small floating chip shown at the bottom-left of the screen
    when a classification dialog is minimized.

    Clicking anywhere on it restores the parent dialog.
    """
    restore_requested = Signal()

    def __init__(self, title: str):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint |
                         Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)  # don't steal focus
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("minimizedChip")
        self.setStyleSheet(_get_chip_style())
        self.setCursor(Qt.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(6)

        icon_lbl = QLabel("◼")
        icon_lbl.setObjectName("chipLabel")
        icon_lbl.setFixedWidth(14)
        lay.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("chipLabel")
        lay.addWidget(title_lbl)

        restore_btn = QPushButton("▲ Restore")
        restore_btn.setObjectName("chipRestoreBtn")
        restore_btn.clicked.connect(self.restore_requested.emit)
        lay.addWidget(restore_btn)

        self.adjustSize()

    def mousePressEvent(self, event):
        self.restore_requested.emit()

    def place_bottom_left(self):
        """Position chip at bottom-left of the primary screen."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geom: QRect = screen.availableGeometry()
        margin = 12
        x = geom.left() + margin
        y = geom.bottom() - self.height() - margin
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self.place_bottom_left()


# ═══════════════════════════════════════════════════════════════════════
# WIDGET HELPER
# ═══════════════════════════════════════════════════════════════════════
def _w(layout):
    w = QWidget()
    w.setLayout(layout)
    return w

# ═══════════════════════════════════════════════════════════════════════
# CLASS SELECTOR POPUP
# ═══════════════════════════════════════════════════════════════════════
class ClassSelectorDialog(QDialog):
    def __init__(self, current_codes, app, multi=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Classes")
        self.setStyleSheet(_get_dialog_style())
        _apply_dialog_icon(self, app)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(260)
        self.app = app
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select class(es):"))
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QAbstractItemView.MultiSelection if multi
            else QAbstractItemView.SingleSelection)
        
        las_classes = _get_las_classes(self.app)
        colors = _get_class_colors(self.app)
        
        for code, name in sorted(las_classes.items()):
            color = colors.get(code)
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, code)
            # Add color swatch icon
            if color is not None:
                item.setIcon(_make_color_icon(color, 14))
            self.list_widget.addItem(item)
            if code in current_codes:
                item.setSelected(True)
        layout.addWidget(self.list_widget)
        btn_row = QHBoxLayout()
        ok = QPushButton("OK"); ok.setObjectName("okButton")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel"); cancel.clicked.connect(self.reject)
        btn_row.addStretch(); btn_row.addWidget(ok); btn_row.addWidget(cancel)
        layout.addLayout(btn_row)

    def selected_codes(self):
        return [it.data(Qt.UserRole) for it in self.list_widget.selectedItems()]


# ═══════════════════════════════════════════════════════════════════════
# CLASS ROW BUILDER (with persistence)
# ═══════════════════════════════════════════════════════════════════════
def _class_combo(app, selected=1):
    cb = QComboBox(); cb.setMinimumWidth(185)
    colors = _get_class_colors(app)
    for code, name in sorted(_get_las_classes(app).items()):
        color = colors.get(code)
        label = name
        if color is not None:
            icon = _make_color_icon(color, 14)
            cb.addItem(icon, label, code)
        else:
            cb.addItem(label, code)
    idx = cb.findData(selected)
    if idx >= 0: cb.setCurrentIndex(idx)
    return cb

def _multi_class_label(codes):
    codes = sorted(codes)
    if not codes: return "None"
    if len(codes) > 1 and codes == list(range(codes[0], codes[-1] + 1)):
        return f"Classes {codes[0]}-{codes[-1]}"
    return ", ".join(str(c) for c in codes)


def _make_class_row(app, default_codes, multi=True, single_default=None,
                    persist_key=None):
    """
    Build a class-selector row with color patches from loaded PTC.
    If persist_key is given, the selection is loaded from / saved to
    PersistentClassSettings automatically.
    """
    if persist_key:
        initial_codes = PersistentClassSettings.get_codes(persist_key, default_codes)
    else:
        initial_codes = list(default_codes)

    row = QHBoxLayout(); row.setSpacing(4)
    arrow = QPushButton(">>"); arrow.setObjectName("arrowBtn")
    arrow.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    if not multi:
        sd = single_default if single_default is not None else (
            initial_codes[0] if initial_codes else 1)
        if persist_key:
            persisted = PersistentClassSettings.get_codes(persist_key, [sd])
            sd = persisted[0] if persisted else sd

        combo = _class_combo(app, sd)
        row.addWidget(combo); row.addWidget(arrow)

        def _open():
            dlg = ClassSelectorDialog([combo.currentData()], app,
                                      multi=False, parent=combo.window())
            if dlg.exec():
                codes = dlg.selected_codes()
                if codes:
                    idx = combo.findData(codes[0])
                    if idx >= 0: combo.setCurrentIndex(idx)
                    if persist_key:
                        PersistentClassSettings.set_codes(persist_key, codes)
        arrow.clicked.connect(_open)

        if persist_key:
            combo.currentIndexChanged.connect(
                lambda _: PersistentClassSettings.set_codes(
                    persist_key, [combo.currentData()]))

        return row, lambda: [combo.currentData()]
    else:
        display = QComboBox(); display.setMinimumWidth(185)
        
        # Build a combined color icon for multi-class display
        colors = _get_class_colors(app)
        icon = _make_multi_class_icon(initial_codes, colors)
        if icon:
            display.addItem(icon, _multi_class_label(initial_codes),
                            list(initial_codes))
        else:
            display.addItem(_multi_class_label(initial_codes),
                            list(initial_codes))
        display.setEnabled(False)
        holder = [list(initial_codes)]

        def _open():
            dlg = ClassSelectorDialog(holder[0], app, multi=True,
                                      parent=display.window())
            if dlg.exec():
                holder[0] = dlg.selected_codes()
                # Refresh icon with new selection
                fresh_colors = _get_class_colors(app)
                new_icon = _make_multi_class_icon(holder[0], fresh_colors)
                if new_icon:
                    display.setItemIcon(0, new_icon)
                display.setItemText(0, _multi_class_label(holder[0]))
                display.setItemData(0, holder[0])
                if persist_key:
                    PersistentClassSettings.set_codes(persist_key, holder[0])
        arrow.clicked.connect(_open)
        row.addWidget(display); row.addWidget(arrow)
        return row, lambda: list(holder[0])


def _make_multi_class_icon(codes, colors_dict, size=14, max_swatches=5):
    """
    Create a combined icon showing up to max_swatches color patches
    side by side for a multi-class selection.
    Returns QIcon or None if no colors available.
    """
    if not codes or not colors_dict:
        return None

    # Collect available colors for the selected codes
    available = []
    for code in sorted(codes):
        if code in colors_dict:
            available.append(colors_dict[code])
    
    if not available:
        return None

    # Limit swatches shown
    show = available[:max_swatches]
    n = len(show)
    swatch_w = size
    gap = 2
    total_w = n * swatch_w + (n - 1) * gap
    
    pixmap = QPixmap(total_w, size)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    
    for i, color in enumerate(show):
        x = i * (swatch_w + gap)
        painter.setPen(QColor(80, 80, 80))
        painter.setBrush(color)
        painter.drawRoundedRect(x + 1, 1, swatch_w - 2, size - 2, 2, 2)
    
    painter.end()
    return QIcon(pixmap)
# ═══════════════════════════════════════════════════════════════════════
# FENCE SELECTOR WIDGET  (FIXED: cleans up when digitizer clears)
# ═══════════════════════════════════════════════════════════════════════
class FenceSelectorWidget(QWidget):
    """
    Self-contained fence selection component for classification dialogs.
    
    Supports both digitizer drawings AND curve tool curves as fences.
    
    FIX: Watches the digitizer's drawings list AND curve tool's finalized_actors.
    When either is cleared, this widget automatically removes its
    selection-highlight actors from the VTK renderer.
    """

    _SHAPE_ICONS = {
        'rectangle': '▭', 'circle': '○', 'polygon': '⬟',
        'polyline': '⬡', 'line': '─', 'smartline': '⚡',
        'smart_line': '⚡', 'freehand': '✏️',
        'curve': '〰️',  # ✅ NEW: Curve tool icon
    }

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app                  = app
        self.selected_fences      = []
        self.permanent_fence_mode = False
        self._hover_actor         = [None]
        self._sel_actors          = {}
        self._check_timer         = None
        self._build_ui()
        self._start_fence_watch()

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(4)

        btn_row = QHBoxLayout(); btn_row.setSpacing(6)
        self.select_btn = QPushButton("📐 Select Fence(s)")
        self.select_btn.setObjectName("fenceBtn")
        self.select_btn.clicked.connect(self.open_fence_picker)

        self.clear_btn = QPushButton("✕ Clear")
        self.clear_btn.setObjectName("fenceClearBtn")
        self.clear_btn.clicked.connect(self.clear_fences)

        btn_row.addWidget(self.select_btn, 1)
        btn_row.addWidget(self.clear_btn)
        main.addLayout(btn_row)

        self.status_lbl = QLabel("No fence — runs on all points")
        self.status_lbl.setStyleSheet("color:#888; font-size:10px; padding:2px 0;")
        self.status_lbl.setWordWrap(True)
        main.addWidget(self.status_lbl)

    # ──────────────────────────────────────────────────────────────
    # FIX: Watch for digitizer drawings AND curve tool changes
    # ──────────────────────────────────────────────────────────────
    def _start_fence_watch(self):
        """
        Start a lightweight timer that checks whether the digitizer's
        drawings list or curve tool's finalized_actors have been cleared.
        """
        self._check_timer = QTimer(self)
        self._check_timer.setInterval(500)
        self._check_timer.timeout.connect(self._check_fences_still_valid)
        self._check_timer.start()

    def _check_fences_still_valid(self):
        """
        Check if our selected fences still exist.
        Handles both digitizer drawings and curve tool curves.
        """
        if not self.selected_fences:
            return

        # Build sets of valid IDs for both sources
        digitizer = getattr(self.app, 'digitizer', None)
        drawing_ids = set()
        if digitizer:
            drawings = getattr(digitizer, 'drawings', [])
            if drawings is not None:
                drawing_ids = {id(d) for d in drawings}

        curve_tool = getattr(self.app, 'curve_tool', None)
        curve_ids = set()
        if curve_tool:
            for curve_data in curve_tool.finalized_actors:
                if isinstance(curve_data, dict):
                    curve_ids.add(id(curve_data))

        # Filter valid fences
        still_valid = []
        removed_actor_ids = set()

        for fence in self.selected_fences:
            is_valid = False
            
            if fence.get('source') == 'curve_tool':
                # Check if curve still exists
                curve_ref = fence.get('curve_data')
                if curve_ref and id(curve_ref) in curve_ids:
                    is_valid = True
                else:
                    # Curve was removed - get actor ID for cleanup
                    removed_actor_ids.add(id(fence))
            else:
                # Digitizer drawing
                if id(fence) in drawing_ids:
                    is_valid = True
                else:
                    removed_actor_ids.add(id(fence))

            if is_valid:
                still_valid.append(fence)

        # Clean up actors for removed fences
        for rid in removed_actor_ids:
            if rid in self._sel_actors:
                try:
                    self.app.vtk_widget.renderer.RemoveActor(self._sel_actors[rid])
                except Exception:
                    pass
                del self._sel_actors[rid]

        # Update if anything changed
        if len(still_valid) < len(self.selected_fences):
            self.selected_fences = still_valid
            self._update_status()

            if not self.selected_fences:
                try:
                    self.app.vtk_widget.render()
                except Exception:
                    pass

    def get_fence_mask(self, xyz: np.ndarray):
        if not self.selected_fences:
            return None
        combined = np.zeros(len(xyz), dtype=bool)
        for fence in self.selected_fences:
            coords = fence.get('coords', [])
            if coords:
                combined |= self._poly_mask(xyz, coords)
        return combined

    def _poly_mask(self, xyz: np.ndarray, coords) -> np.ndarray:
        """
        Point-in-polygon test using ray casting algorithm.
        
        Args:
            xyz: Nx3 array of point coordinates
            coords: Polygon coordinates (list of [x,y,z] or Nx3 array)
        
        Returns:
            Boolean mask of points inside the polygon
        """
        if len(coords) < 3:
            return np.zeros(len(xyz), dtype=bool)
        
        try:
            from matplotlib.path import Path
        except ImportError:
            # Fallback to manual ray casting
            return self._ray_cast_mask(xyz, coords)
        
        # Extract XY coordinates only (ignore Z)
        if isinstance(coords, list):
            poly_xy = np.array([[c[0], c[1]] for c in coords])
        else:
            poly_xy = coords[:, :2]
        
        points_xy = xyz[:, :2]
        
        # 1. AABB Pre-filter (O(N) - Ultra Fast)
        min_x, min_y = np.min(poly_xy, axis=0)
        max_x, max_y = np.max(poly_xy, axis=0)
        
        bbox_mask = (
            (points_xy[:, 0] >= min_x) & 
            (points_xy[:, 0] <= max_x) & 
            (points_xy[:, 1] >= min_y) & 
            (points_xy[:, 1] <= max_y)
        )
        
        inside = np.zeros(len(xyz), dtype=bool)
        
        # 2. Exact Polygon Check ONLY on points inside the bounding box
        if np.any(bbox_mask):
            # Close polygon if not already closed
            if not np.allclose(poly_xy[0], poly_xy[-1]):
                poly_xy = np.vstack([poly_xy, poly_xy[0]])
            
            poly_path = Path(poly_xy)
            inside[bbox_mask] = poly_path.contains_points(points_xy[bbox_mask])
        
        return inside

    def _ray_cast_mask(self, xyz: np.ndarray, coords) -> np.ndarray:
        """
        Manual ray casting fallback for point-in-polygon test.
        Used when matplotlib is not available.
        """
        if isinstance(coords, list):
            poly_xy = np.array([[c[0], c[1]] for c in coords])
        else:
            poly_xy = coords[:, :2]
        
        # Close polygon if not already closed
        if not np.allclose(poly_xy[0], poly_xy[-1]):
            poly_xy = np.vstack([poly_xy, poly_xy[0]])
        
        n_poly = len(poly_xy)
        mask = np.zeros(len(xyz), dtype=bool)
        points_xy = xyz[:, :2]
        
        for i, pt in enumerate(points_xy):
            inside = False
            j = n_poly - 1
            for k in range(n_poly):
                xi, yi = poly_xy[k]
                xj, yj = poly_xy[j]
                if ((yi > pt[1]) != (yj > pt[1])) and \
                   (pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi + 1e-10) + xi):
                    inside = not inside
                j = k
            mask[i] = inside
        
        return mask

    def cleanup_actors(self):
        """Remove all VTK actors and stop the watch timer."""
        self._remove_hover()
        self._remove_sel_actors()
        if self._check_timer is not None:
            self._check_timer.stop()

    def _remove_hover(self):
        """Remove hover highlight actor."""
        if self._hover_actor[0]:
            try:
                self.app.vtk_widget.renderer.RemoveActor(self._hover_actor[0])
            except Exception:
                pass
            self._hover_actor[0] = None

    def _remove_sel_actors(self):
        """Remove all selection highlight actors."""
        for actor in self._sel_actors.values():
            try:
                self.app.vtk_widget.renderer.RemoveActor(actor)
            except Exception:
                pass
        self._sel_actors.clear()

    def open_fence_picker(self):
        """Open fence picker dialog showing both digitizer drawings and curves."""
        digitize = getattr(self.app, 'digitizer', None)
        curve_tool = getattr(self.app, 'curve_tool', None)
        
        # ── Collect digitizer drawings ────────────────────────────
        valid = []
        if digitize:
            drawings = getattr(digitize, 'drawings', [])
            valid.extend([d for d in drawings if d.get('type') in
                         ['rectangle', 'circle', 'polygon', 'freehand',
                          'line', 'smart_line', 'polyline', 'smartline']])
        
        # ── Collect curve tool curves ✅ NEW ─────────────────────
        curve_fences = []
        if curve_tool and hasattr(curve_tool, 'get_curves_as_fences'):
            curve_fences = curve_tool.get_curves_as_fences()
            valid.extend(curve_fences)
        
        if not valid:
            QMessageBox.warning(self.window(), "No Shapes Found",
                "No shapes or curves found.\n\n"
                "Draw a shape using Digitize tools or Curve tool first.")
            return

        dlg = QDialog(self.window(), Qt.Window)
        dlg.setWindowTitle("Select Fence(s)")
        dlg.setWindowModality(Qt.NonModal)
        dlg.setStyleSheet(_get_fence_picker_style())
        dlg.resize(420, 500)
        layout = QVBoxLayout(dlg)

        info = QLabel("Select one or more fences to use for conversion")
        from gui.theme_manager import ThemeColors
        info.setStyleSheet(f"color:{ThemeColors.get('accent')}; font-weight:bold; padding:8px;")
        layout.addWidget(info)
        
        # Show source counts
        digitizer_count = len(valid) - len(curve_fences)
        curve_count = len(curve_fences)
        source_info = QLabel(f"📐 Digitizer: {digitizer_count} | 〰️ Curves: {curve_count}")
        source_info.setStyleSheet(f"color:{ThemeColors.get('text_muted')}; font-size:10px; padding:2px 8px;")
        layout.addWidget(source_info)

        perm_chk = QCheckBox("🔄 Permanent Fence Mode (keep all fences selected)")
        perm_chk.setChecked(self.permanent_fence_mode)
        layout.addWidget(perm_chk)

        fence_list = QListWidget()
        fence_list.setStyleSheet("""
            QListWidget { background:#1e1e1e; border:1px solid #3a3a3a;
                          border-radius:4px; padding:4px; }
            QListWidget::item { background:transparent; border:none; padding:2px; }
        """)
        fence_list.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(fence_list)

        hover_actor  = [None]
        picker_sel   = {}

        def _make_actor(coords, color, width):
            """Create a polyline actor for highlighting."""
            # ✅ For curve tool, use Actor2D like the curve tool does
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
                
                # Use Mapper2D for consistent rendering with curve tool
                mapper = vtk.vtkPolyDataMapper2D()
                mapper.SetInputData(pd)
                
                coord = vtk.vtkCoordinate()
                coord.SetCoordinateSystemToWorld()
                mapper.SetTransformCoordinate(coord)
                
                ac = vtk.vtkActor2D()
                ac.SetMapper(mapper)
                ac.GetProperty().SetColor(*color)
                ac.GetProperty().SetLineWidth(width)
                ac.GetProperty().SetDisplayLocationToForeground()
                
                return ac
            except Exception:
                # Fallback to 3D actor
                try:
                    import vtk
                    pts = vtk.vtkPoints()
                    for c in coords:
                        pts.InsertNextPoint(float(c[0]), float(c[1]),
                                            float(c[2]) if len(c) > 2 else 0.0)
                    pl = vtk.vtkPolyLine()
                    pl.GetPointIds().SetNumberOfIds(len(coords))
                    for i in range(len(coords)):
                        pl.GetPointIds().SetId(i, i)
                    ca = vtk.vtkCellArray(); ca.InsertNextCell(pl)
                    pd = vtk.vtkPolyData(); pd.SetPoints(pts); pd.SetLines(ca)
                    mp = vtk.vtkPolyDataMapper(); mp.SetInputData(pd)
                    ac = vtk.vtkActor(); ac.SetMapper(mp)
                    ac.GetProperty().SetColor(*color)
                    ac.GetProperty().SetLineWidth(width)
                    return ac
                except Exception:
                    return None

        def _add(actor):
            """Add actor to renderer."""
            try:
                if actor:
                    if hasattr(actor, 'IsA') and actor.IsA('vtkActor2D'):
                        self.app.vtk_widget.renderer.AddViewProp(actor)
                    else:
                        self.app.vtk_widget.renderer.AddActor(actor)
                    self.app.vtk_widget.render()
            except Exception:
                pass

        def _rem(actor):
            """Remove actor from renderer."""
            try:
                if actor:
                    if hasattr(actor, 'IsA') and actor.IsA('vtkActor2D'):
                        self.app.vtk_widget.renderer.RemoveViewProp(actor)
                    else:
                        self.app.vtk_widget.renderer.RemoveActor(actor)
            except Exception:
                pass

        def on_hover(shape):
            if hover_actor[0]: _rem(hover_actor[0]); hover_actor[0] = None
            if shape is None:
                try: self.app.vtk_widget.render()
                except: pass
                return
            coords = shape.get('coords', [])
            if len(coords) == 0: return
            # Use yellow for hover
            ac = _make_actor(coords, (1, 1, 0), 6)
            if ac: hover_actor[0] = ac; _add(ac)

        def on_toggle(shape, checked):
            # Use unique ID based on source type
            if shape.get('source') == 'curve_tool':
                sid = id(shape.get('curve_data', shape))
            else:
                sid = id(shape)
            
            if not checked:
                if sid in picker_sel: _rem(picker_sel.pop(sid))
                try: self.app.vtk_widget.render()
                except: pass
                return
            if sid not in picker_sel:
                coords = shape.get('coords', [])
                if len(coords) == 0: return
                # Use blue for selection
                ac = _make_actor(coords, (0, 0.5, 1), 5)
                if ac: picker_sel[sid] = ac; _add(ac)

        # Build current selection IDs
        current_ids = set()
        for f in self.selected_fences:
            if f.get('source') == 'curve_tool':
                current_ids.add(id(f.get('curve_data', f)))
            else:
                current_ids.add(id(f))

        custom_rows   = []

        for idx, shape in enumerate(valid):
            stype  = shape.get('type', 'unknown')
            coords = shape.get('coords', [])
            is_curve = shape.get('source') == 'curve_tool'
            icon   = self._SHAPE_ICONS.get(stype, '◆')
            
            # ✅ Different label for curves
            if is_curve:
                curve_idx = shape.get('curve_index', idx)
                title_text = f"〰️ Curve #{curve_idx + 1}"
                source_tag = "Curve Tool"
            else:
                title_text = f"{icon} #{idx + 1}: {stype.capitalize()}"
                source_tag = "Digitizer"
            
            try:
                arr  = np.array(coords)
                w    = arr[:, 0].max() - arr[:, 0].min()
                h    = arr[:, 1].max() - arr[:, 1].min()
                size = f"{w:.1f}×{h:.1f}m"
            except Exception:
                size = ""

            item_widget = QWidget()
            
            # ✅ Different background color for curves
            if is_curve:
                bg_color = ThemeColors.get('bg_secondary')
            else:
                bg_color = ThemeColors.get('bg_button')
            
            item_widget.setStyleSheet(f"background:{bg_color}; border-radius:5px;")
            ilay = QHBoxLayout(item_widget); ilay.setContentsMargins(6, 4, 6, 4)

            # Icon swatch
            swatch = QLabel(icon)
            swatch.setFixedSize(28, 28); swatch.setAlignment(Qt.AlignCenter)
            
            # ✅ Different swatch color for curves
            if is_curve:
                curve_color = shape.get('color', (0, 1, 0))
                swatch_color = f"rgb({int(curve_color[0]*255)}, {int(curve_color[1]*255)}, {int(curve_color[2]*255)})"
                swatch.setStyleSheet(
                    f"background:{swatch_color}; border-radius:4px; color:white;"
                    " font-size:14px; font-weight:bold;")
            else:
                swatch.setStyleSheet(
                    f"background:{ThemeColors.get('accent')}; border-radius:4px; color:{ThemeColors.get('text_on_active')};"
                    " font-size:14px; font-weight:bold;")
            ilay.addWidget(swatch)

            # Info column
            info_col = QVBoxLayout(); info_col.setSpacing(1)
            title_l = QLabel(title_text)
            title_l.setStyleSheet(f"color:{ThemeColors.get('text_primary')}; font-weight:bold; font-size:11px;")
            sub_l   = QLabel(f"{len(coords)} pts | {size} | {source_tag}")
            sub_l.setStyleSheet(f"color:{ThemeColors.get('text_muted')}; font-size:10px;")
            info_col.addWidget(title_l); info_col.addWidget(sub_l)
            ilay.addLayout(info_col, 1)

            # Selected badge
            badge = QLabel("Selected")
            badge.setStyleSheet(
                f"background:{ThemeColors.get('accent')}; color:{ThemeColors.get('text_on_active')}; font-weight:bold;"
                " font-size:10px; border-radius:4px; padding:3px 8px;")
            
            # Check if currently selected
            if is_curve:
                is_current = id(shape.get('curve_data', shape)) in current_ids
            else:
                is_current = id(shape) in current_ids
            badge.setVisible(is_current)

            cb = QCheckBox()
            cb.setChecked(is_current)
            cb.setStyleSheet(f"""
                QCheckBox::indicator {{ width:20px; height:20px; }}
                QCheckBox::indicator:unchecked {{
                    background:{ThemeColors.get('bg_button')}; border:2px solid {ThemeColors.get('border_light')}; border-radius:3px; }}
                QCheckBox::indicator:checked {{
                    background:{ThemeColors.get('accent')}; border:2px solid {ThemeColors.get('accent')}; border-radius:3px; }}
            """)

            def _connect(shp, bdg, checkbox, is_crv):
                def _changed(state):
                    chk = bool(state)
                    bdg.setVisible(chk)
                    on_toggle(shp, chk)
                    bg = ThemeColors.get('bg_active') if chk else (
                        ThemeColors.get('bg_secondary') if is_crv else ThemeColors.get('bg_button'))
                    checkbox.parentWidget().setStyleSheet(
                        f"background:{bg}; border-radius:5px;")
                checkbox.stateChanged.connect(_changed)
            _connect(shape, badge, cb, is_curve)

            if is_current:
                item_widget.setStyleSheet(f"background:{ThemeColors.get('bg_active')}; border-radius:5px;")
                on_toggle(shape, True)

            ilay.addWidget(badge); ilay.addWidget(cb)

            def _hover_bind(shp, wgt):
                def _e(ev): on_hover(shp)
                def _l(ev): on_hover(None)
                wgt.enterEvent = _e; wgt.leaveEvent = _l
            _hover_bind(shape, item_widget)

            li = QListWidgetItem(fence_list)
            li.setSizeHint(item_widget.sizeHint())
            fence_list.setItemWidget(li, item_widget)
            custom_rows.append((cb, shape, is_curve))

        brow = QHBoxLayout()

        def do_sel_all():
            for cb_, _, _ in custom_rows: cb_.setChecked(True)
        sel_all_btn = QPushButton("Select All")
        sel_all_btn.clicked.connect(do_sel_all)

        def do_clr_all():
            for sid_, ac_ in list(picker_sel.items()): _rem(ac_)
            picker_sel.clear()
            for cb_, _, _ in custom_rows: cb_.setChecked(False)
            try: self.app.vtk_widget.render()
            except: pass
        clr_all_btn = QPushButton("Clear All")
        clr_all_btn.clicked.connect(do_clr_all)

        apply_btn = QPushButton("Apply Selection")
        apply_btn.setStyleSheet(
            "background:#2e7d32; color:white; font-weight:bold;"
            " border-radius:3px; padding:5px 16px;")

        def do_apply():
            on_hover(None)
            chosen = [shp for cb_, shp, _ in custom_rows if cb_.isChecked()]
            if not chosen:
                QMessageBox.warning(dlg, "No Selection", "Select at least one fence.")
                return
            self.permanent_fence_mode = perm_chk.isChecked()
            if not self.permanent_fence_mode:
                self._remove_sel_actors()
                self.selected_fences = []
            
            # Build existing IDs set
            existing_ids = set()
            for f in self.selected_fences:
                if f.get('source') == 'curve_tool':
                    existing_ids.add(id(f.get('curve_data', f)))
                else:
                    existing_ids.add(id(f))
            
            for shp in chosen:
                # Determine unique ID
                if shp.get('source') == 'curve_tool':
                    fence_id = id(shp.get('curve_data', shp))
                else:
                    fence_id = id(shp)
                
                if fence_id not in existing_ids:
                    self.selected_fences.append(shp)
                    existing_ids.add(fence_id)
                
                # Close open shapes for polygon-based masking
                if shp['type'] in ['line', 'smart_line', 'polyline', 'smartline', 'curve']:
                    coords = shp.get('coords', [])
                    if len(coords) > 1:
                        arr = np.array(coords)
                        if not np.allclose(arr[0], arr[-1]):
                            shp['coords'] = list(arr) + [list(arr[0])]
            
            # Store picker selection actors
            for sid_, ac_ in picker_sel.items():
                self._sel_actors[sid_] = ac_
            picker_sel.clear()
            self._update_status()
            try: self.app.vtk_widget.render()
            except: pass
            dlg.close()

        apply_btn.clicked.connect(do_apply)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            "background:#555; color:white; border-radius:3px; padding:5px 16px;")

        def do_close():
            on_hover(None)
            for ac_ in picker_sel.values(): _rem(ac_)
            picker_sel.clear()
            try: self.app.vtk_widget.render()
            except: pass
            dlg.close()
        close_btn.clicked.connect(do_close)

        brow.addWidget(sel_all_btn); brow.addWidget(clr_all_btn)
        brow.addStretch()
        brow.addWidget(apply_btn); brow.addWidget(close_btn)
        layout.addLayout(brow)
        dlg.exec()

    def _update_status(self):
        """Update status label with fence counts."""
        if not self.selected_fences:
            self.status_lbl.setText("No fence — runs on all points")
            self.status_lbl.setStyleSheet("color:#888; font-size:10px; padding:2px 0;")
            return
        
        digitizer_count = sum(1 for f in self.selected_fences 
                             if f.get('source') != 'curve_tool')
        curve_count = sum(1 for f in self.selected_fences 
                         if f.get('source') == 'curve_tool')
        
        parts = []
        if digitizer_count:
            parts.append(f"📐 {digitizer_count} shape(s)")
        if curve_count:
            parts.append(f"〰️ {curve_count} curve(s)")
        
        text = " + ".join(parts) + " selected"
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet("color:#4fc3f7; font-size:10px; padding:2px 0; font-weight:bold;")

    def clear_fences(self):
        """Clear all fence selections and actors."""
        self._remove_hover()
        self._remove_sel_actors()
        self.selected_fences = []
        self._update_status()
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass

    def _remove_hover(self):
        if self._hover_actor[0]:
            try:
                self.app.vtk_widget.renderer.RemoveActor(self._hover_actor[0])
                self.app.vtk_widget.render()
            except:
                pass
            self._hover_actor[0] = None

    def _remove_sel_actors(self):
        for ac in self._sel_actors.values():
            try:
                self.app.vtk_widget.renderer.RemoveActor(ac)
            except:
                pass
        self._sel_actors.clear()
        try:
            self.app.vtk_widget.render()
        except:
            pass


# ═══════════════════════════════════════════════════════════════════════
# BACKGROUND WORKER
# ═══════════════════════════════════════════════════════════════════════
class _ClassificationWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(object)
    error    = Signal(str)

    def __init__(self, func, kwargs):
        super().__init__()
        self.func = func; self.kwargs = kwargs; self._abort = False

    def abort(self): self._abort = True

    def run(self):
        try:
            result = self.func(progress_cb=self.progress.emit,
                               abort_check=lambda: self._abort,
                               **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            import traceback; traceback.print_exc(); self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════════════════
# ALGORITHM 1 — CLASSIFY LOW POINTS (ground-surface based)
# ═══════════════════════════════════════════════════════════════════════

def classify_low_points(xyz, classification, from_classes, to_class,
                        ground_classes=None,
                        fence_mask=None, search_mode="groups",
                        max_count=6, more_than=0.50, within=5.0,
                        progress_cb=None, abort_check=None):
    """
    Classify Low (or High) Points.

    KEY FIX: ground_classes explicitly defines which classes are used as
    the ground reference surface.  Defaults to [2] (standard ground).
    Previously used ALL non-from-classes which included vegetation/wires
    and produced a falsely elevated "ground" level.

    more_than > 0 : flag points MORE THAN X metres BELOW ground  (low noise)
    more_than < 0 : flag points MORE THAN |X| metres ABOVE ground (high noise)
    more_than = 0 : flag any deviation from ground level

    ground_classes : list[int]
        Classes that define the ground surface for comparison.
        MUST be actual ground/bare-earth classes (e.g. [2]).
        Default: [2]
    """
    import time as _t

    if ground_classes is None:
        ground_classes = [2]

    direction = "below" if more_than >= 0 else "above"
    abs_mt    = abs(more_than)

    def _log(pct, msg):
        print(f"[LowPts {pct:3d}%] {msg}", flush=True)
        if progress_cb:
            progress_cb(pct, msg)

    _log(0, f"mode={search_mode}  {direction}_ground_by>{abs_mt}m  "
            f"radius={within}m  ground_ref={ground_classes}  "
            f"fence={'yes' if fence_mask is not None else 'no'}")

    cand_mask = np.isin(classification, from_classes)
    if fence_mask is not None:
        cand_mask &= fence_mask
    candidate_idx = np.where(cand_mask)[0]
    _log(2, f"Candidates to check: {len(candidate_idx):,}")
    if not len(candidate_idx):
        _log(100, "No candidates — nothing to do")
        return {"changed": 0, "indices": np.array([], dtype=np.intp)}

    ref_mask = np.isin(classification, ground_classes)
    ref_idx  = np.where(ref_mask)[0]
    _log(4, f"Ground reference pts (classes {ground_classes}): {len(ref_idx):,}")

    if not len(ref_idx):
        _log(4, "⚠️  WARNING: No ground reference pts in specified classes! "
                "Falling back to all non-from-classes (may be inaccurate).")
        ref_mask = ~np.isin(classification, from_classes)
        ref_idx  = np.where(ref_mask)[0]
        _log(4, f"Fallback ground reference pts: {len(ref_idx):,}")
        if not len(ref_idx):
            _log(100, "No ground reference pts — cannot determine ground level")
            return {"changed": 0, "indices": np.array([], dtype=np.intp)}

    z_all = xyz[:, 2]

    _log(5, f"Building ground KD-Tree ({len(ref_idx):,} pts) …")
    t0 = _t.time()
    tree_ref = cKDTree(xyz[ref_idx, :2])
    _log(20, f"Ground tree ready ({_t.time()-t0:.2f}s)")

    _log(22, f"Computing local ground level for {len(candidate_idx):,} pts …")
    t0 = _t.time()
    k = min(20, len(ref_idx))
    dists, inds = tree_ref.query(xyz[candidate_idx, :2], k=k, workers=-1)
    if k == 1:
        dists = dists[:, np.newaxis]
        inds  = inds[:, np.newaxis]

    ref_z_near   = np.where(dists <= within, z_all[ref_idx[inds]], np.nan)
    n_valid      = np.sum(np.isfinite(ref_z_near), axis=1)
    local_ground = np.nanmin(ref_z_near, axis=1)

    _log(60, f"Ground levels computed ({_t.time()-t0:.2f}s)")

    has_ref = np.isfinite(local_ground) & (n_valid >= 3)
    z_cand  = z_all[candidate_idx]

    signed_offset = local_ground - z_cand
    is_flagged    = has_ref & (signed_offset > more_than)

    n_flagged = int(is_flagged.sum())
    _log(65, f"Points {direction}-ground > {abs_mt}m found: {n_flagged:,}  "
             f"(skipped — insufficient nearby ground: {int((~has_ref).sum()):,})")

    if n_flagged == 0:
        _log(100, f"No {direction}-ground points found")
        return {"changed": 0, "indices": np.array([], dtype=np.intp)}

    if search_mode == "single":
        flagged = candidate_idx[is_flagged]
    else:
        _log(68, f"Groups mode — clustering {n_flagged:,} flagged pts …")
        low_global = candidate_idx[is_flagged]
        t0 = _t.time()
        tree_low = cKDTree(xyz[low_global, :2])
        kc = min(max_count + 4, len(low_global))
        cd, ci = tree_low.query(xyz[low_global, :2], k=kc, workers=-1)
        if kc == 1:
            cd = cd[:, np.newaxis]
            ci = ci[:, np.newaxis]
        _log(82, f"Cluster queries done ({_t.time()-t0:.2f}s)")

        processed    = set()
        flagged_list = []
        for i in range(len(low_global)):
            gi = low_global[i]
            if gi in processed:
                continue
            nearby_local = ci[i][cd[i] <= within]
            nearby_glob  = low_global[nearby_local]
            sort_key     = z_all[nearby_glob]
            if more_than < 0:
                cluster = nearby_glob[np.argsort(-sort_key)][:max_count]
            else:
                cluster = nearby_glob[np.argsort(sort_key)][:max_count]
            for g in cluster:
                flagged_list.append(g)
                processed.add(g)
        flagged = np.unique(np.array(flagged_list, dtype=np.intp))

    flagged = np.asarray(flagged, dtype=np.intp)
    classification[flagged] = to_class
    _log(100, f"Done — {len(flagged):,} {direction}-ground pts → class {to_class}")
    return {"changed": len(flagged), "indices": flagged}


# ═══════════════════════════════════════════════════════════════════════
# ALGORITHM 2 — CLASSIFY ISOLATED POINTS
# MicroStation-equivalent: 3D sphere, self-excluded, From≠In class
# ═══════════════════════════════════════════════════════════════════════
def classify_isolated_points(xyz, classification, from_classes, to_class,
                             in_classes, if_fewer_than=1, within=5.0,
                             fence_mask=None, iterative=False,
                             max_iterations=10,
                             height_from_ground=None,
                             ground_classes=None,
                             progress_cb=None, abort_check=None):
    """MicroStation Classify Isolated Points — exact equivalent."""
    import time as _t

    if ground_classes is None:
        ground_classes = [2]

    total_changed = 0
    all_flagged = []

    height_mask = None
    if height_from_ground is not None and height_from_ground > 0:
        if progress_cb:
            progress_cb(0, f"Computing height above ground (threshold={height_from_ground}m) …")

        ground_mask = np.isin(classification, ground_classes)
        ground_idx = np.where(ground_mask)[0]

        if len(ground_idx) < 3:
            if progress_cb:
                progress_cb(5, f"⚠️ Too few ground pts ({len(ground_idx)}), "
                               f"skipping height filter — using all candidates")
            height_mask = None
        else:
            t0 = _t.time()
            ground_tree = cKDTree(xyz[ground_idx, :2])
            k_ground = min(10, len(ground_idx))
            g_dists, g_inds = ground_tree.query(xyz[:, :2], k=k_ground, workers=-1)
            if k_ground == 1:
                g_dists = g_dists[:, np.newaxis]
                g_inds = g_inds[:, np.newaxis]

            search_r = max(50.0, 3.0 * within)
            ground_z_near = np.where(
                g_dists <= search_r,
                xyz[ground_idx[g_inds], 2],
                np.nan
            )
            local_ground_z = np.nanmin(ground_z_near, axis=1)
            n_valid_ground = np.sum(np.isfinite(ground_z_near), axis=1)
            height_above = xyz[:, 2] - local_ground_z
            height_mask = (
                np.isfinite(local_ground_z) &
                (n_valid_ground >= 2) &
                (height_above > height_from_ground)
            )
            n_above = int(height_mask.sum())
            if progress_cb:
                progress_cb(5, f"Height filter: {n_above:,} pts > {height_from_ground}m "
                               f"above ground ({_t.time()-t0:.2f}s)")
            if n_above == 0:
                if progress_cb:
                    progress_cb(100, f"No points above {height_from_ground}m from ground — nothing to classify")
                return {"changed": 0, "indices": np.array([], dtype=np.intp)}

    for iteration in range(max_iterations if iterative else 1):
        if abort_check and abort_check():
            break

        iter_label = f" (iter {iteration+1})" if iterative else ""

        cand_mask = np.isin(classification, from_classes)
        if fence_mask is not None:
            cand_mask &= fence_mask
        if height_mask is not None:
            cand_mask &= height_mask
        candidate_idx = np.where(cand_mask)[0]

        in_mask = np.isin(classification, in_classes)
        # Apply fence to the neighbor tree so only points inside the
        # fence are counted as neighbors — this is what makes the
        # operation truly fence-local and fast
        if fence_mask is not None:
            in_mask_for_tree = in_mask & fence_mask
        else:
            in_mask_for_tree = in_mask
        if height_mask is not None:
            in_mask_for_tree = in_mask_for_tree & height_mask

        in_idx = np.where(in_mask_for_tree)[0]

        if not len(candidate_idx) or not len(in_idx):
            if progress_cb:
                progress_cb(100, f"No candidates/neighbors{iter_label}")
            break

        if progress_cb:
            progress_cb(
                int(iteration / max(1, max_iterations if iterative else 1) * 80),
                f"Building 3D KD-Tree{iter_label} ({len(in_idx):,} in-class pts) …")

        tree3d = cKDTree(xyz[in_idx])

        if progress_cb:
            progress_cb(
                int(iteration / max(1, max_iterations if iterative else 1) * 80) + 5,
                f"Batch sphere query{iter_label} ({len(candidate_idx):,} candidates) …")

        counts = tree3d.query_ball_point(
            xyz[candidate_idx], within,
            return_length=True, workers=-1)

        self_in = in_mask_for_tree[candidate_idx].astype(np.intp)
        counts = counts - self_in
        isolated = counts < if_fewer_than
        flagged = candidate_idx[isolated]

        if progress_cb:
            progress_cb(
                int((iteration + 0.9) / max(1, max_iterations if iterative else 1) * 95),
                f"Found {len(flagged):,} isolated{iter_label}")

        if len(flagged) == 0:
            if progress_cb:
                progress_cb(100, f"Stable after {iteration+1} iteration(s) — "
                                 f"total {total_changed:,} pts reclassified")
            break

        classification[flagged] = to_class
        total_changed += len(flagged)
        all_flagged.append(flagged)

        if not iterative:
            break

    all_indices = np.unique(np.concatenate(all_flagged)) if all_flagged \
                  else np.array([], dtype=np.intp)

    if progress_cb:
        progress_cb(100, f"Done — {total_changed:,} pts → class {to_class}")

    return {"changed": total_changed, "indices": all_indices}


# ═══════════════════════════════════════════════════════════════════════
# ALGORITHM 3 — CLASSIFY GROUND (PTD — Axelsson 2000, vectorized)
# ═══════════════════════════════════════════════════════════════════════
def classify_ground_ptd(xyz, classification, from_classes, to_class,
                        current_ground=2, seed_method="aerial_low_ground",
                        max_building_size=60.0, terrain_angle=88.0,
                        iteration_angle=6.0, iteration_distance=1.40,
                        reduce_angle_edge=True, edge_length_threshold=5.0,
                        stop_triangulation=False, stop_edge_length=2.0,
                        use_distance_as_rating=False, distance_weight=50.0,
                        add_only_upward=False, fence_mask=None,
                        progress_cb=None, abort_check=None):
    from_mask = np.isin(classification, from_classes)
    cg_mask = (classification == current_ground)
    if fence_mask is not None:
        from_mask &= fence_mask
        cg_mask   &= fence_mask
    work_idx = np.where(from_mask | cg_mask)[0]
    if not len(work_idx):
        return {"changed": 0, "indices": np.array([], dtype=np.intp)}
    pts = xyz[work_idx]; n = len(pts)
    is_from_local = from_mask[work_idx]; is_cg_local = cg_mask[work_idx]

    if progress_cb: progress_cb(2, "Phase 1 — Seeds …")
    seed_local = set()

    def _cell_seeds():
        xmn,ymn = pts[:,0].min(),pts[:,1].min()
        xmx,ymx = pts[:,0].max(),pts[:,1].max()
        cell=max_building_size
        nx=max(1,int(np.ceil((xmx-xmn)/cell))); ny=max(1,int(np.ceil((ymx-ymn)/cell)))
        cx=np.clip(((pts[:,0]-xmn)/cell).astype(int),0,nx-1)
        cy=np.clip(((pts[:,1]-ymn)/cell).astype(int),0,ny-1)
        cid=cx*ny+cy
        for c in np.unique(cid):
            m=np.where(cid==c)[0]; seed_local.add(int(m[np.argmin(pts[m,2])]))

    if seed_method in ("aerial_low_ground","lowest_only"): _cell_seeds()
    if seed_method in ("aerial_low_ground","ground_only"): seed_local.update(np.where(is_cg_local)[0].tolist())
    if len(seed_local) < 3 and seed_method == "ground_only": _cell_seeds()
    if len(seed_local) < 3:
        rc=work_idx[is_from_local]; classification[rc]=to_class
        return {"changed": len(rc), "indices": rc}

    if progress_cb: progress_cb(10, f"Phase 2 — TIN from {len(seed_local)} seeds …")
    ground_set=set(seed_local); terrain_rad=np.radians(terrain_angle); in_ground=np.zeros(n,dtype=bool)

    for iteration in range(100):
        if abort_check and abort_check(): break
        ga=np.array(sorted(ground_set),dtype=np.intp); gp=pts[ga]
        if len(ga)<3: break
        if progress_cb: progress_cb(12+int(iteration/100*80),f"Iter {iteration+1}: {len(ga):,} …")
        try: tri=Delaunay(gp[:,:2])
        except: break
        in_ground[:]=False; in_ground[ga]=True
        ng=np.where(~in_ground)[0]
        if not len(ng): break
        sids=tri.find_simplex(pts[ng,:2]); valid=sids!=-1
        if not valid.any(): break
        vng=ng[valid]; vsids=sids[valid]
        usids,inv=np.unique(vsids,return_inverse=True)
        sv=tri.simplices[usids]
        A3=gp[sv[:,0]]; B3=gp[sv[:,1]]; C3=gp[sv[:,2]]
        me=np.maximum(np.maximum(np.linalg.norm(B3-A3,axis=1),np.linalg.norm(C3-B3,axis=1)),np.linalg.norm(A3-C3,axis=1))
        nor=np.cross(B3-A3,C3-A3); nl=np.linalg.norm(nor,axis=1,keepdims=True)
        good=nl[:,0]>1e-12; nor=nor/np.where(nl>0,nl,1.0); nor[nor[:,2]<0]*=-1
        sl=np.arccos(np.clip(nor[:,2],-1,1)); tok=good&(sl<=terrain_rad)
        pn=nor[inv]; pme=me[inv]; pto=tok[inv]; pA=A3[inv]; pa=pts[vng]
        act=pto.copy()
        if stop_triangulation: act&=pme>=stop_edge_length
        d=np.einsum('ij,ij->i',pn,pa-pA); pd=np.abs(d)
        act&=pd<=iteration_distance
        if add_only_upward: act&=d>=0
        pp=pa-d[:,np.newaxis]*pn; psv=sv[inv]
        nr=np.minimum(np.minimum(np.linalg.norm(gp[psv[:,0]]-pp,axis=1),np.linalg.norm(gp[psv[:,1]]-pp,axis=1)),np.linalg.norm(gp[psv[:,2]]-pp,axis=1))
        alpha=np.where(nr<1e-12,90.0,np.degrees(np.arctan2(pd,nr)))
        ea=np.full(len(vng),iteration_angle,dtype=float)
        if reduce_angle_edge:
            sm=pme<edge_length_threshold; ea[sm]=iteration_angle*pme[sm]/edge_length_threshold
        if use_distance_as_rating:
            w=distance_weight/100.0
            act&=(1-w)*np.where(ea>0,alpha/ea,1.0)+w*(pd/iteration_distance if iteration_distance>0 else np.ones_like(pd))<=1.0
        else:
            act&=alpha<=ea
        np_=vng[act]
        if not len(np_): break
        ground_set.update(np_.tolist())

    gl=np.array(sorted(ground_set),dtype=np.intp)
    rl=gl[is_from_local[gl]]; rg=work_idx[rl]
    classification[rg]=to_class
    if progress_cb: progress_cb(100,f"Done — {len(rg):,} pts → class {to_class}")
    return {"changed": len(rg), "indices": rg}


# ═══════════════════════════════════════════════════════════════════════
# ALGORITHM 4 — CLASSIFY BELOW SURFACE
# MicroStation-equivalent: planar/curved, limit × AVE MAGNITUDE
# ═══════════════════════════════════════════════════════════════════════
def classify_below_surface(xyz, classification, from_classes, to_class,
                           surface_type="planar", limit=4.0,
                           z_tolerance=0.10, num_neighbors=25,
                           fence_mask=None, iterative=False,
                           max_iterations=5,
                           progress_cb=None, abort_check=None):
    """MicroStation Classify Below Surface — exact equivalent."""
    total_changed = 0
    all_flagged = []

    for iteration in range(max_iterations if iterative else 1):
        if abort_check and abort_check():
            break

        iter_label = f" (iter {iteration+1})" if iterative else ""

        src_mask = np.isin(classification, from_classes)
        if fence_mask is not None:
            src_mask &= fence_mask
        src_idx = np.where(src_mask)[0]

        if len(src_idx) < num_neighbors + 1:
            if progress_cb:
                progress_cb(100, f"Too few source pts{iter_label}")
            break

        if progress_cb:
            base_pct = int(iteration / max(1, max_iterations if iterative else 1) * 80)
            progress_cb(base_pct, f"Building KD-Tree{iter_label} …")

        src_pts = xyz[src_idx]
        tree = cKDTree(src_pts)
        total = len(src_idx)
        k = min(num_neighbors + 1, total)

        if progress_cb:
            progress_cb(base_pct + 3,
                        f"Batch KNN{iter_label} ({total:,} × {k}) …")

        _, all_nbr = tree.query(src_pts, k=k, workers=-1)
        use_curved = (surface_type == "curved")
        flagged = []

        if not use_curved:
            if progress_cb:
                progress_cb(base_pct + 8,
                            f"Vectorized planar fitting{iter_label} …")

            nbr_idx = all_nbr[:, 1:]
            nbr_pts = src_pts[nbr_idx]
            K1 = nbr_pts.shape[1]
            ones = np.ones((total, K1, 1))
            A = np.concatenate([nbr_pts[:, :, :2], ones], axis=2)
            b = nbr_pts[:, :, 2]
            AtA = np.einsum('nki,nkj->nij', A, A)
            Atb = np.einsum('nki,nk->ni', A, b)

            try:
                coeffs = np.linalg.solve(AtA, Atb)
                bad = ~np.all(np.isfinite(coeffs), axis=1)
                if np.any(bad):
                    bad_idx = np.where(bad)[0]
                    for i in bad_idx:
                        try:
                            coeffs[i], _, _, _ = np.linalg.lstsq(
                                AtA[i], Atb[i], rcond=None)
                        except Exception:
                            coeffs[i] = np.nan
            except Exception:
                coeffs = np.full((total, 3), np.nan)
                for i in range(total):
                    try:
                        coeffs[i], _, _, _ = np.linalg.lstsq(
                            AtA[i], Atb[i], rcond=None)
                    except Exception:
                        pass

            if progress_cb:
                progress_cb(base_pct + 15, f"Computing residuals{iter_label} …")

            fitted  = np.einsum('nki,ni->nk', A, coeffs)
            ave_mag = np.mean(np.abs(nbr_pts[:, :, 2] - fitted), axis=1)
            px = src_pts[:, 0]; py = src_pts[:, 1]
            pz = coeffs[:, 0] * px + coeffs[:, 1] * py + coeffs[:, 2]
            offset = pz - src_pts[:, 2]
            valid = np.all(np.isfinite(coeffs), axis=1)
            mask = (valid
                    & (offset > 0)
                    & (offset >= z_tolerance)
                    & ((ave_mag < 1e-9) | (offset > limit * ave_mag)))
            flagged = src_idx[mask]

        else:
            if progress_cb:
                progress_cb(base_pct + 5,
                            f"Curved surface fitting{iter_label} …")

            for i in range(total):
                if abort_check and abort_check():
                    break
                if progress_cb and i % max(1, total // 50) == 0:
                    progress_cb(
                        base_pct + 5 + int(i / total * 14),
                        f"Fitting{iter_label} {i:,}/{total:,}")

                nl = all_nbr[i, 1:]
                nl = nl[nl != i]
                if len(nl) < 6:
                    continue

                np_ = src_pts[nl]; p = src_pts[i]
                cx, cy = np_[:, 0].mean(), np_[:, 1].mean()
                xn, yn = np_[:, 0] - cx, np_[:, 1] - cy
                Am = np.column_stack([xn**2, yn**2, xn*yn, xn, yn, np.ones(len(np_))])
                try:
                    cfs, _, _, _ = np.linalg.lstsq(Am, np_[:, 2], rcond=None)
                except:
                    continue

                fitted_c = Am @ cfs
                ave_c = np.mean(np.abs(np_[:, 2] - fitted_c))
                px_c, py_c = p[0] - cx, p[1] - cy
                pz_c = np.dot([px_c**2, py_c**2, px_c*py_c, px_c, py_c, 1.0], cfs)
                offset_c = pz_c - p[2]

                if offset_c <= 0 or offset_c < z_tolerance:
                    continue
                if ave_c < 1e-9 or offset_c > limit * ave_c:
                    flagged.append(src_idx[i])

            flagged = np.array(flagged, dtype=np.intp)

        flagged = np.asarray(flagged, dtype=np.intp)

        if len(flagged) == 0:
            if progress_cb:
                progress_cb(100, f"Stable after {iteration+1} iteration(s) — "
                                 f"total {total_changed:,} pts reclassified")
            break

        classification[flagged] = to_class
        total_changed += len(flagged)
        all_flagged.append(flagged)

        if progress_cb:
            progress_cb(
                int((iteration + 1) / max(1, max_iterations if iterative else 1) * 95),
                f"Iter {iteration+1}: {len(flagged):,} pts flagged{iter_label}")

        if not iterative:
            break

    all_indices = np.unique(np.concatenate(all_flagged)) if all_flagged \
                  else np.array([], dtype=np.intp)

    if progress_cb:
        progress_cb(100, f"Done — {total_changed:,} pts → class {to_class}")

    return {"changed": total_changed, "indices": all_indices}


# ═══════════════════════════════════════════════════════════════════════
# BASE DIALOG  ← MINIMIZE FEATURE LIVES HERE
# ═══════════════════════════════════════════════════════════════════════
class _BaseClassifyDialog(QDialog):
    """
    Base class for all classification dialogs.

    MINIMIZE BEHAVIOUR
    ──────────────────
    • A "─" button is added to the top of every dialog (above the main
      content).  Clicking it hides the dialog and shows a small chip
      anchored to the bottom-left of the screen.
    • When the chip's "▲ Restore" button (or anywhere on the chip) is
      clicked, the dialog re-appears at exactly the position and size it
      had before minimization.
    • Calling the public-API open_* function while the dialog is already
      open and minimized will restore it rather than create a duplicate.
    """

    _persist_prefix = ""

    def __init__(self, app, title, parent=None):
        super().__init__(parent or app)
        self.app = app
        self.setWindowTitle(title)
        self.setStyleSheet(_get_dialog_style())
        _apply_dialog_icon(self, app)

        self.setWindowFlags(
            Qt.Dialog |
            Qt.WindowCloseButtonHint |
            Qt.WindowMinimizeButtonHint
        )
        self.setMinimumWidth(370)

        self._worker = None
        self._focus_conn = None
        self._connect_focus_watcher()

        # ── Minimize state ────────────────────────────────────────
        self._chip: _MinimizedChip | None = None
        self._saved_geometry: QRect | None = None

    def _connect_focus_watcher(self):
        pass

    def _disconnect_focus_watcher(self):
        pass

    def _on_focus_window_changed(self, focused_window):
        pass

    def refresh_theme(self):
        """Re-apply current theme styles to this dialog."""
        try:
            self.setStyleSheet(_get_dialog_style())
            if self._chip is not None:
                self._chip.setStyleSheet(_get_chip_style())
        except Exception:
            pass

    # ──────────────────────────────────────────────────────────────
    # MINIMIZE / RESTORE  — driven by native OS title-bar button
    # ──────────────────────────────────────────────────────────────
    def changeEvent(self, event):
        """Intercept native minimize → replace with bottom-left chip."""
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            self.setWindowState(Qt.WindowNoState)
            QTimer.singleShot(0, self._do_minimize_to_chip)

    def showEvent(self, event):
        self.refresh_theme()
        super().showEvent(event)

    def _do_minimize_to_chip(self):
        if self._chip is not None:
            self._chip.show()
            self._chip.place_bottom_left()
            self.hide()
            return

        self._saved_geometry = self.geometry()
        self._chip = _MinimizedChip(self.windowTitle())
        self._chip.restore_requested.connect(self._do_restore_from_chip)
        self._chip.show()
        self._chip.place_bottom_left()
        self.hide()

    def _do_restore_from_chip(self):
        chip, self._chip = self._chip, None
        if chip is not None:
            try:
                chip.restore_requested.disconnect()
            except Exception:
                pass
            chip.hide()
            chip.deleteLater()

        if self._saved_geometry is not None:
            self.setGeometry(self._saved_geometry)

        self.setWindowState(Qt.WindowNoState)
        self.show()
        self.raise_()
        self.activateWindow()

    def minimize_to_chip(self):
        self._do_minimize_to_chip()

    def restore_from_chip(self):
        self._do_restore_from_chip()

    @property
    def _is_minimized_to_chip(self):
        return self._chip is not None and not self.isVisible()

    # ──────────────────────────────────────────────────────────────
    # PERSISTENCE HELPERS
    # ──────────────────────────────────────────────────────────────
    def _pk(self, suffix: str) -> str:
        return f"{self._persist_prefix}.{suffix}" if self._persist_prefix else suffix

    def _persist_spin(self, spin, key_suffix, default):
        val = PersistentClassSettings.get_value(self._pk(key_suffix), default)
        spin.setValue(val)
        spin.valueChanged.connect(
            lambda v: PersistentClassSettings.set_value(self._pk(key_suffix), v)
        )

    def _persist_combo_index(self, combo, key_suffix, default_index):
        idx = PersistentClassSettings.get_value(self._pk(key_suffix), default_index)
        if 0 <= idx < combo.count():
            combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(
            lambda i: PersistentClassSettings.set_value(self._pk(key_suffix), i)
        )

    def _persist_checkbox(self, chk, key_suffix, default_checked):
        val = PersistentClassSettings.get_value(self._pk(key_suffix), default_checked)
        chk.setChecked(bool(val))
        chk.stateChanged.connect(
            lambda s: PersistentClassSettings.set_value(self._pk(key_suffix), bool(s))
        )

    def _get_fence_mask(self, fence_widget: FenceSelectorWidget):
        if not fence_widget.selected_fences or self.app.data is None:
            return None
        return fence_widget.get_fence_mask(self.app.data["xyz"])

    # ──────────────────────────────────────────────────────────────
    # RUN ALGORITHM
    # ──────────────────────────────────────────────────────────────
    def _run_algorithm(self, func, kwargs, name):
        self.hide()
        if self.app.data is None:
            QMessageBox.warning(self.app, "No Data", "Load a point cloud first.")
            self.close()
            return

        old_cls = self.app.data["classification"].copy()
        kwargs["xyz"] = self.app.data["xyz"]
        kwargs["classification"] = self.app.data["classification"]

        self._prog = QProgressDialog(f"Running {name}…", "Cancel", 0, 100, self.app)
        self._prog.setWindowModality(Qt.NonModal)
        self._prog.setWindowTitle(name)
        self._prog.setMinimumDuration(0)
        self._prog.setValue(0)
        self._prog.setAttribute(Qt.WA_DeleteOnClose)
        self._prog.show()

        self._worker = _ClassificationWorker(func, kwargs)
        self._worker.progress.connect(self._on_prog)
        self._worker.finished.connect(lambda r: self._on_done(r, old_cls, name))
        self._worker.error.connect(self._on_err)
        self._prog.canceled.connect(self._worker.abort)
        self._worker.start()

    def _on_prog(self, pct, msg):
        if hasattr(self, "_prog") and self._prog:
            self._prog.setValue(pct)
            self._prog.setLabelText(msg)

    # ──────────────────────────────────────────────────────────────
    # SECTION SYNC
    # ──────────────────────────────────────────────────────────────
    def _sync_section_classifications(self, changed_indices):
        sc = getattr(self.app, "section_controller", None)
        if sc is None or self.app.data is None:
            return

        new_cls = self.app.data["classification"]
        ch_idx = np.asarray(changed_indices)
        synced = False

        for attr_name in (
            "_section_data", "section_data", "_sections",
            "sections", "_view_data", "view_data",
            "_stored_sections"
        ):
            storage = getattr(sc, attr_name, None)
            if not isinstance(storage, dict) or not storage:
                continue
            for view_id, sd in storage.items():
                if sd is not None:
                    self._sync_one_section(sd, new_cls, ch_idx, view_id)
            synced = True
            break

        if synced:
            return

        for gi_attr, cls_attr in [
            ("global_indices", "classification"),
            ("_global_indices", "_classification"),
            ("section_indices", "section_cls"),
        ]:
            gi = getattr(sc, gi_attr, None)
            cl = getattr(sc, cls_attr, None)
            if gi is not None and cl is not None and isinstance(cl, np.ndarray):
                gi_arr = np.asarray(gi)
                mask = np.isin(gi_arr, ch_idx)
                if mask.any():
                    cl[mask] = new_cls[gi_arr[mask]]
                    print(f"   📋 Synced {int(mask.sum())} section cls values")
                return

    def _sync_one_section(self, section_data, new_cls, changed_indices, view_id):
        GI_KEYS = ("global_indices", "indices", "point_indices", "idx", "core_indices", "all_indices")
        CLS_KEYS = ("classification", "cls", "classes", "point_classes")

        def _get(obj, keys):
            for k in keys:
                v = obj.get(k) if isinstance(obj, dict) else getattr(obj, k, None)
                if v is not None:
                    return v
            return None

        gi = _get(section_data, GI_KEYS)
        cl = _get(section_data, CLS_KEYS)

        if gi is None or cl is None or not isinstance(cl, np.ndarray):
            return

        gi_arr = np.asarray(gi)
        if len(gi_arr) == 0:
            return

        mask = np.isin(gi_arr, changed_indices)
        n = int(mask.sum())
        if n > 0:
            cl[mask] = new_cls[gi_arr[mask]]
            print(f"   📋 Synced {n} classification values in section view {view_id}")

    # ──────────────────────────────────────────────────────────────
    # ON DONE
    # ──────────────────────────────────────────────────────────────
    def _on_done(self, result, old_cls, name):
        if hasattr(self, "_prog") and self._prog:
            try:
                self._prog.close()
            except Exception:
                pass
            self._prog = None

        changed = result.get("changed", 0)
        indices = result.get("indices", np.array([]))

        to_class = None
        from_classes = None
        mask = None

        if changed > 0 and len(indices) > 0:
            mask = np.zeros(len(self.app.data["xyz"]), dtype=bool)
            mask[indices] = True
            old_c = old_cls[indices]
            new_c = self.app.data["classification"][indices].copy()

            to_class_arr = np.unique(new_c)
            to_class = int(to_class_arr[0]) if len(to_class_arr) == 1 else None
            from_classes = list(set(int(c) for c in np.unique(old_c)))
            if to_class is not None and to_class not in from_classes:
                from_classes.append(to_class)

            self.app._last_changed_mask = mask
            self._sync_section_classifications(indices)

            _stack = getattr(self.app, "undo_stack", getattr(self.app, "undostack", None))
            if _stack is not None:
                try:
                    _stack.append({
                        "mask": mask,
                        "old_classes": old_c,
                        "new_classes": new_c,
                        "is_cut_locked": False,
                    })
                    _redo = getattr(self.app, "redo_stack", getattr(self.app, "redostack", None))
                    if _redo is not None:
                        _redo.clear()

                    max_steps = getattr(self.app, "_max_undo_steps", 30)
                    while len(_stack) > max_steps:
                        from gui.memory_manager import _free_undo_entry
                        _free_undo_entry(_stack.pop(0))
                except Exception as e:
                    print(f"⚠️ Undo stack push failed: {e}")

        print(f"🔄 Classification done — refreshing view ({changed:,} pts changed)…")
        self._refresh(to_class=to_class, from_classes=from_classes)
        print("✅ View refresh complete")

        self._worker = None
        QTimer.singleShot(200, self._clear_changed_mask)

        mb = QMessageBox(self.app)
        mb.setIcon(QMessageBox.Information)
        mb.setWindowTitle(name)
        mb.setText(f"{name} complete.\nPoints reclassified: {changed:,}")
        mb.setWindowModality(Qt.NonModal)
        mb.setAttribute(Qt.WA_DeleteOnClose)
        mb.show()

    def _clear_changed_mask(self):
        if hasattr(self.app, "_last_changed_mask"):
            self.app._last_changed_mask = None

    def _on_err(self, msg):
        if hasattr(self, "_prog") and self._prog:
            try:
                self._prog.close()
            except Exception:
                pass
            self._prog = None

        self._worker = None
        eb = QMessageBox(self.app)
        eb.setIcon(QMessageBox.Critical)
        eb.setWindowTitle("Error")
        eb.setText(f"Classification failed:\n{msg}")
        eb.setWindowModality(Qt.NonModal)
        eb.setAttribute(Qt.WA_DeleteOnClose)
        eb.show()

    # ──────────────────────────────────────────────────────────────
    # REFRESH
    # ──────────────────────────────────────────────────────────────
    def _refresh(self, to_class=None, from_classes=None):
        try:
            display_mode = getattr(self.app, "display_mode", "class")

            if display_mode == "class" and to_class is not None:
                try:
                    from gui.optimized_refresh import get_optimizer
                    optimizer = get_optimizer(self.app)

                    def _fallback(tc):
                        from gui.class_display import update_class_mode
                        update_class_mode(self.app, force_refresh=True)

                    optimizer.refresh_after_classification(
                        to_class=to_class,
                        from_classes=from_classes,
                        fallback_func=_fallback,
                    )
                    print("   ⚡ Used optimized refresh pipeline")
                    return
                except ImportError:
                    print("   ℹ️ optimized_refresh not available, using fallback")
                except Exception as e:
                    print(f"   ⚠️ Optimized refresh failed: {e}, using fallback")
                    import traceback
                    traceback.print_exc()

            if display_mode == "class":
                from gui.class_display import update_class_mode
                update_class_mode(self.app, force_refresh=True)

            elif display_mode == "shaded_class":
                try:
                    from gui.shading_display import clear_shading_cache, update_shaded_class
                    clear_shading_cache("classification changed")
                    update_shaded_class(
                        self.app,
                        getattr(self.app, "last_shade_azimuth", 45.0),
                        getattr(self.app, "last_shade_angle", 45.0),
                        getattr(self.app, "shade_ambient", 0.2),
                        force_rebuild=True,
                    )
                except Exception:
                    if hasattr(self.app, "apply_display_mode"):
                        self.app.apply_display_mode()

            elif hasattr(self.app, "apply_display_mode"):
                self.app.apply_display_mode()
            else:
                try:
                    self.app.vtk_widget.render()
                except Exception:
                    pass

            if hasattr(self.app, "section_controller"):
                try:
                    self.app.section_controller._refresh_all_section_colors()
                except Exception as e:
                    print(f"⚠️ Section refresh: {e}")

        except Exception as e:
            print(f"⚠️ View refresh failed: {e}")
            import traceback
            traceback.print_exc()
            try:
                self.app.vtk_widget.render()
            except Exception:
                pass

    # ──────────────────────────────────────────────────────────────
    # BUTTON ROW
    # ──────────────────────────────────────────────────────────────
    def _make_buttons(self, layout):
        row = QHBoxLayout()
        row.addStretch()
        ok = QPushButton("OK")
        ok.setObjectName("okButton")
        ok.clicked.connect(self._on_ok)
        ok.setDefault(True)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def _on_ok(self):
        pass

    # ──────────────────────────────────────────────────────────────
    # CLOSE / REJECT
    # ──────────────────────────────────────────────────────────────
    def _cleanup_chip(self):
        if self._chip is not None:
            try:
                self._chip.restore_requested.disconnect()
            except Exception:
                pass
            self._chip.hide()
            self._chip.deleteLater()
            self._chip = None

    def closeEvent(self, event):
        self._disconnect_focus_watcher()
        if hasattr(self, "_fence_sel"):
            self._fence_sel.cleanup_actors()
        self._cleanup_chip()
        super().closeEvent(event)

    def reject(self):
        self._disconnect_focus_watcher()
        if hasattr(self, "_fence_sel"):
            self._fence_sel.cleanup_actors()
        self._cleanup_chip()
        super().reject()

# ═══════════════════════════════════════════════════════════════════════
# FENCE GROUP FACTORY
# ═══════════════════════════════════════════════════════════════════════
def _fence_group(dialog) -> tuple:
    g = QGroupBox("Fence / Spatial Filter")
    lay = QVBoxLayout(g); lay.setContentsMargins(8, 6, 8, 6)
    sel = FenceSelectorWidget(dialog.app, parent=g)
    lay.addWidget(sel)
    dialog._fence_sel = sel
    return g, sel


# ═══════════════════════════════════════════════════════════════════════
# DIALOG 1 — CLASSIFY LOW POINTS
# ═══════════════════════════════════════════════════════════════════════
class ClassifyLowPointsDialog(_BaseClassifyDialog):
    _persist_prefix = "low_points"

    def __init__(self, app, parent=None):
        super().__init__(app, "Classify Low Points", parent)
        self._build_ui()
        self.resize(390, 510)

    def _build_ui(self):
        L = QVBoxLayout(self)
        L.setSpacing(8)

        # ── Classes ──────────────────────────────────────────────────
        g = QGroupBox("Classes")
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight)

        r1, self._get_from = _make_class_row(
            self.app, [1], multi=False, single_default=1,
            persist_key=self._pk("from_class"))
        r2, self._get_to = _make_class_row(
            self.app, [7], multi=False, single_default=7,
            persist_key=self._pk("to_class"))
        r3, self._get_ground_ref = _make_class_row(
            self.app, [2], multi=True,
            persist_key=self._pk("ground_ref_class"))

        f.addRow("From class:",     _w(r1))
        f.addRow("To class:",       _w(r2))

        sep = QFrame(); sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(_note_text_style())
        f.addRow(sep)

        f.addRow("Ground ref class:", _w(r3))

        ref_note = QLabel(
            "⚠️  Ground ref must be TRUE GROUND only (e.g. class 2).\n"
            "    Including vegetation/buildings gives wrong results.")
        ref_note.setStyleSheet(_note_text_style())
        ref_note.setWordWrap(True)
        f.addRow("", ref_note)

        L.addWidget(g)

        # ── Search ───────────────────────────────────────────────────
        g2 = QGroupBox("Search")
        f2 = QFormLayout(g2)
        f2.setLabelAlignment(Qt.AlignRight)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Single point", "Groups of points"])
        self._persist_combo_index(self.mode_combo, "search_mode", 1)
        f2.addRow("Search:", self.mode_combo)

        self._max_count_lbl = QLabel("Max count:")
        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 1000)
        self._persist_spin(self.max_spin, "max_count", 6)
        mc_row = QHBoxLayout()
        mc_row.addWidget(self.max_spin)
        mc_row.addWidget(QLabel("points per group"))
        self._max_count_widget = _w(mc_row)
        f2.addRow(self._max_count_lbl, self._max_count_widget)

        def _update_max_count_visibility(index):
            is_groups = (index == 1)
            self._max_count_lbl.setVisible(is_groups)
            self._max_count_widget.setVisible(is_groups)

        self.mode_combo.currentIndexChanged.connect(_update_max_count_visibility)
        _update_max_count_visibility(self.mode_combo.currentIndex())

        L.addWidget(g2)

        # ── Classify if ──────────────────────────────────────────────
        g3 = QGroupBox("Classify if")
        f3 = QFormLayout(g3)
        f3.setLabelAlignment(Qt.AlignRight)

        self.mt_spin = QDoubleSpinBox()
        self.mt_spin.setRange(-999.0, 999.0)
        self.mt_spin.setDecimals(2)
        self._persist_spin(self.mt_spin, "more_than", 0.50)

        self._direction_lbl = QLabel()
        self._direction_lbl.setStyleSheet(_note_text_style())

        def _update_direction_label(val):
            if val > 0:
                self._direction_lbl.setText("m  lower than ground  (below surface)")
            elif val < 0:
                self._direction_lbl.setText("m  higher than ground  (above surface)")
            else:
                self._direction_lbl.setText("m  at ground level")
            self._direction_lbl.setStyleSheet(_note_text_style())

        self.mt_spin.valueChanged.connect(_update_direction_label)
        _update_direction_label(self.mt_spin.value())

        mr = QHBoxLayout()
        mr.addWidget(self.mt_spin)
        mr.addWidget(self._direction_lbl)
        mr.addStretch()
        f3.addRow("More than:", _w(mr))

        hint = QLabel(
            "  + = classify BELOW ground surface  |  − = classify ABOVE ground")
        hint.setStyleSheet(_note_text_style())
        f3.addRow("", hint)

        self.within_spin = QDoubleSpinBox()
        self.within_spin.setRange(0.1, 9999.0)
        self.within_spin.setDecimals(2)
        self._persist_spin(self.within_spin, "within", 5.00)
        wr = QHBoxLayout()
        wr.addWidget(self.within_spin)
        wr.addWidget(QLabel("m  (search radius)"))
        f3.addRow("Within:", _w(wr))
        L.addWidget(g3)

        # ── Fence ────────────────────────────────────────────────────
        fg, self._fence_sel = _fence_group(self)
        L.addWidget(fg)

        L.addStretch()
        self._make_buttons(L)

    def _on_ok(self):
        self._run_algorithm(classify_low_points, {
            "from_classes":   self._get_from(),
            "to_class":       self._get_to()[0],
            "ground_classes": self._get_ground_ref(),
            "fence_mask":     self._get_fence_mask(self._fence_sel),
            "search_mode":    "single" if self.mode_combo.currentIndex() == 0
                              else "groups",
            "max_count":      self.max_spin.value(),
            "more_than":      self.mt_spin.value(),
            "within":         self.within_spin.value(),
        }, "Classify Low Points")


# ═══════════════════════════════════════════════════════════════════════
# DIALOG 2 — CLASSIFY ISOLATED POINTS
# ═══════════════════════════════════════════════════════════════════════
class ClassifyIsolatedPointsDialog(_BaseClassifyDialog):
    _persist_prefix = "isolated"

    def __init__(self, app, parent=None):
        super().__init__(app, "Classify Isolated Points", parent)
        self._build_ui()
        self.resize(420, 560)

    def _build_ui(self):
        L = QVBoxLayout(self); L.setSpacing(8)

        # ── Classes group ─────────────────────────────────────────────
        g = QGroupBox("Classes"); f = QFormLayout(g); f.setLabelAlignment(Qt.AlignRight)

        # ── FROM CLASS — inline multi-select list (no popup) ──────────
        from_initial = PersistentClassSettings.get_codes(
            self._pk("from_class"), [2, 3, 4, 5])

        self._from_list = QListWidget()
        self._from_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._from_list.setStyleSheet(_get_inline_multiselect_style())
        las_classes = _get_las_classes(self.app)
        colors = _get_class_colors(self.app)
        for code, name in sorted(las_classes.items()):
            color = colors.get(code)
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, code)
            # Add color swatch from loaded PTC
            if color is not None:
                item.setIcon(_make_color_icon(color, 14))
            self._from_list.addItem(item)
            if code in from_initial:
                item.setSelected(True)

        hint = QLabel("Ctrl+click = multi-select  •  Shift+click = range")
        hint.setStyleSheet(_note_text_style())

        from_col = QVBoxLayout(); from_col.setSpacing(2)
        from_col.addWidget(self._from_list)
        from_col.addWidget(hint)
        from_widget = QWidget(); from_widget.setLayout(from_col)

        # Persist on every selection change
        def _save_from_selection():
            codes = [self._from_list.item(i).data(Qt.UserRole)
                    for i in range(self._from_list.count())
                    if self._from_list.item(i).isSelected()]
            PersistentClassSettings.set_codes(self._pk("from_class"), codes)
        self._from_list.itemSelectionChanged.connect(_save_from_selection)

        f.addRow("From class:", from_widget)

        # ── TO CLASS ──────────────────────────────────────────────────
        r2, self._get_to = _make_class_row(
            self.app, [9], multi=False, single_default=9,
            persist_key=self._pk("to_class"))
        f.addRow("To class:", _w(r2))
        L.addWidget(g)

        # ── Isolation criteria group ──────────────────────────────────
        g2 = QGroupBox("Isolation Criteria")
        f2 = QFormLayout(g2); f2.setLabelAlignment(Qt.AlignRight)

        self.fewer_spin = QSpinBox(); self.fewer_spin.setRange(0, 9999)
        self._persist_spin(self.fewer_spin, "if_fewer_than", 1)
        fr = QHBoxLayout(); fr.addWidget(self.fewer_spin)
        fr.addWidget(QLabel("other points (in 3D sphere)"))
        f2.addRow("If fewer than:", _w(fr))

        r3, self._get_in = _make_class_row(
            self.app, [3, 4, 5], multi=True,
            persist_key=self._pk("in_class"))
        f2.addRow("In class:", _w(r3))

        self.within_spin = QDoubleSpinBox()
        self.within_spin.setRange(0.1, 9999.0); self.within_spin.setDecimals(2)
        self._persist_spin(self.within_spin, "within", 5.00)
        wr = QHBoxLayout(); wr.addWidget(self.within_spin)
        wr.addWidget(QLabel("m  (3D radius)"))
        f2.addRow("Within:", _w(wr))

        L.addWidget(g2)

        # ── Height Filter group ───────────────────────────────────────
        g_hf = QGroupBox("Height Filter (above ground)")
        hf_lay = QVBoxLayout(g_hf); hf_lay.setSpacing(4)

        self.height_filter_chk = QCheckBox(
            "🔺 Only classify points above height threshold from ground")
        self._persist_checkbox(self.height_filter_chk, "use_height_filter", False)
        hf_lay.addWidget(self.height_filter_chk)

        hf_form = QFormLayout(); hf_form.setLabelAlignment(Qt.AlignRight)

        self.height_spin = QDoubleSpinBox()
        self.height_spin.setRange(0.1, 9999.0); self.height_spin.setDecimals(2)
        self._persist_spin(self.height_spin, "height_from_ground", 5.0)
        hr = QHBoxLayout(); hr.addWidget(self.height_spin)
        hr.addWidget(QLabel("m  above ground surface"))
        self._height_label = QLabel("Height threshold:")
        hf_form.addRow(self._height_label, _w(hr))

        r_gref, self._get_ground_ref = _make_class_row(
            self.app, [2], multi=True,
            persist_key=self._pk("ground_ref_class"))
        self._ground_ref_label = QLabel("Ground ref class:")
        hf_form.addRow(self._ground_ref_label, _w(r_gref))

        hf_lay.addLayout(hf_form)

        hf_info = QLabel(
            "⚠️  When enabled, ONLY points above this height from ground\n"
            "     are evaluated. Clustered high-altitude noise (birds,\n"
            "     wires) will be caught even if they have nearby neighbors\n"
            "     at the same height — because ground-level neighbors\n"
            "     don't count as 'in-class' for the sphere check.")
        hf_info.setStyleSheet(_note_text_style())
        hf_info.setWordWrap(True)
        hf_lay.addWidget(hf_info)

        def _toggle_height_filter(state):
            enabled = bool(state)
            self.height_spin.setEnabled(enabled)
            self._height_label.setEnabled(enabled)
            self._ground_ref_label.setEnabled(enabled)

        self.height_filter_chk.stateChanged.connect(_toggle_height_filter)
        _toggle_height_filter(self.height_filter_chk.isChecked())

        L.addWidget(g_hf)

        # ── Iteration options group ───────────────────────────────────
        g3 = QGroupBox("Options"); ol = QVBoxLayout(g3); ol.setSpacing(4)

        self.iter_chk = QCheckBox("🔄 Iterate until stable (MicroStation repeat mode)")
        self._persist_checkbox(self.iter_chk, "iterative", False)
        ol.addWidget(self.iter_chk)

        ir = QHBoxLayout(); ir.addSpacing(24); ir.addWidget(QLabel("Max iterations:"))
        self.max_iter_spin = QSpinBox(); self.max_iter_spin.setRange(1, 100)
        self._persist_spin(self.max_iter_spin, "max_iterations", 10)
        self.max_iter_spin.setEnabled(self.iter_chk.isChecked())
        ir.addWidget(self.max_iter_spin); ir.addStretch(); ol.addLayout(ir)
        self.iter_chk.stateChanged.connect(
            lambda s: self.max_iter_spin.setEnabled(bool(s)))

        info = QLabel(
            "ℹ️ Counts neighbors of 'In class' within 3D sphere.\n"
            "   Self-excluded. From class ≠ In class is allowed.\n"
            "   MicroStation equivalent: 3D outlier filter.")
        info.setStyleSheet(_note_text_style())
        info.setWordWrap(True)
        ol.addWidget(info)

        L.addWidget(g3)

        # ── Fence ─────────────────────────────────────────────────────
        fg, self._fence_sel = _fence_group(self); L.addWidget(fg)
        L.addStretch(); self._make_buttons(L)

    def _on_ok(self):
        from_codes = [self._from_list.item(i).data(Qt.UserRole)
                    for i in range(self._from_list.count())
                    if self._from_list.item(i).isSelected()]
        if not from_codes:
            QMessageBox.warning(self, "No Selection",
                                "Please select at least one 'From class'.")
            return

        kwargs = {
            "from_classes":    from_codes,
            "to_class":        self._get_to()[0],
            "in_classes":      self._get_in(),
            "if_fewer_than":   self.fewer_spin.value(),
            "within":          self.within_spin.value(),
            "fence_mask":      self._get_fence_mask(self._fence_sel),
            "iterative":       self.iter_chk.isChecked(),
            "max_iterations":  self.max_iter_spin.value(),
        }

        if self.height_filter_chk.isChecked():
            kwargs["height_from_ground"] = self.height_spin.value()
            kwargs["ground_classes"] = self._get_ground_ref()
        else:
            kwargs["height_from_ground"] = None
            kwargs["ground_classes"] = None

        self._run_algorithm(classify_isolated_points, kwargs,
                            "Classify Isolated Points")

# ═══════════════════════════════════════════════════════════════════════
# DIALOG 3 — CLASSIFY GROUND
# ═══════════════════════════════════════════════════════════════════════
class ClassifyGroundDialog(_BaseClassifyDialog):
    _persist_prefix = "ground"

    def __init__(self, app, parent=None):
        super().__init__(app, "Classify Ground", parent)
        self._build_ui()
        self.resize(430, 670)

    def _build_ui(self):
        L = QVBoxLayout(self); L.setSpacing(6)


        g1 = QGroupBox("Classes"); f1 = QFormLayout(g1); f1.setLabelAlignment(Qt.AlignRight)
        r1, self._get_from = _make_class_row(
            self.app, [1], multi=False, single_default=1,
            persist_key=self._pk("from_class"))
        r2, self._get_to = _make_class_row(
            self.app, [2], multi=False, single_default=2,
            persist_key=self._pk("to_class"))
        r3, self._get_cur = _make_class_row(
            self.app, [2], multi=False, single_default=2,
            persist_key=self._pk("current_ground"))
        f1.addRow("From class:", _w(r1)); f1.addRow("To class:", _w(r2))
        f1.addRow("Current ground:", _w(r3))
        L.addWidget(g1)

        g2 = QGroupBox("Initial points"); f2 = QFormLayout(g2); f2.setLabelAlignment(Qt.AlignRight)
        self.select_combo = QComboBox()
        self.select_combo.addItems([
            "Aerial low + Ground points", "Lowest point only", "Ground points only"])
        self._persist_combo_index(self.select_combo, "seed_method", 0)
        f2.addRow("Select:", self.select_combo)
        self.max_bldg_spin = QDoubleSpinBox()
        self.max_bldg_spin.setRange(1, 9999); self.max_bldg_spin.setDecimals(1)
        self._persist_spin(self.max_bldg_spin, "max_building_size", 60.0)
        f2.addRow("Max building size:", self.max_bldg_spin); L.addWidget(g2)

        g3 = QGroupBox("Classification maximums")
        f3 = QFormLayout(g3); f3.setLabelAlignment(Qt.AlignRight)
        self.terrain_spin = QDoubleSpinBox()
        self.terrain_spin.setRange(0.1, 90); self.terrain_spin.setDecimals(2)
        self._persist_spin(self.terrain_spin, "terrain_angle", 88.00)
        ta = QHBoxLayout(); ta.addWidget(self.terrain_spin); ta.addWidget(QLabel("degrees"))
        f3.addRow("Terrain angle:", _w(ta))
        self.ia_spin = QDoubleSpinBox()
        self.ia_spin.setRange(0.1, 90); self.ia_spin.setDecimals(2)
        self._persist_spin(self.ia_spin, "iteration_angle", 6.00)
        ia = QHBoxLayout(); ia.addWidget(self.ia_spin); ia.addWidget(QLabel("degrees to plane"))
        f3.addRow("Iteration angle:", _w(ia))
        self.id_spin = QDoubleSpinBox()
        self.id_spin.setRange(0.01, 999); self.id_spin.setDecimals(2)
        self._persist_spin(self.id_spin, "iteration_distance", 1.40)
        idr = QHBoxLayout(); idr.addWidget(self.id_spin); idr.addWidget(QLabel("to plane"))
        f3.addRow("Iteration distance:", _w(idr))
        L.addWidget(g3)

        g4 = QGroupBox("Classification options"); ol = QVBoxLayout(g4); ol.setSpacing(4)
        self.reduce_chk = QCheckBox("Reduce iteration angle when")
        self._persist_checkbox(self.reduce_chk, "reduce_angle_edge", True)
        ol.addWidget(self.reduce_chk)
        er = QHBoxLayout(); er.addSpacing(24); er.addWidget(QLabel("Edge length <"))
        self.edge_spin = QDoubleSpinBox()
        self.edge_spin.setRange(0.1, 999); self.edge_spin.setDecimals(1)
        self._persist_spin(self.edge_spin, "edge_length_threshold", 5.0)
        er.addWidget(self.edge_spin); er.addStretch(); ol.addLayout(er)
        self.reduce_chk.stateChanged.connect(lambda s: self.edge_spin.setEnabled(bool(s)))
        self.edge_spin.setEnabled(self.reduce_chk.isChecked())

        sep1 = QFrame(); sep1.setFrameShape(QFrame.HLine); sep1.setFrameShadow(QFrame.Sunken)
        ol.addWidget(sep1)
        self.stop_chk = QCheckBox("Stop triangulation when")
        self._persist_checkbox(self.stop_chk, "stop_triangulation", False)
        ol.addWidget(self.stop_chk)
        sr = QHBoxLayout(); sr.addSpacing(24); sr.addWidget(QLabel("Edge length <"))
        self.stop_edge_spin = QDoubleSpinBox()
        self.stop_edge_spin.setRange(0.01, 999); self.stop_edge_spin.setDecimals(2)
        self._persist_spin(self.stop_edge_spin, "stop_edge_length", 2.00)
        self.stop_edge_spin.setEnabled(self.stop_chk.isChecked())
        sr.addWidget(self.stop_edge_spin); sr.addStretch(); ol.addLayout(sr)
        self.stop_chk.stateChanged.connect(lambda s: self.stop_edge_spin.setEnabled(bool(s)))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.HLine); sep2.setFrameShadow(QFrame.Sunken)
        ol.addWidget(sep2)
        self.dist_rating_chk = QCheckBox("Use Distance as rating")
        self._persist_checkbox(self.dist_rating_chk, "use_distance_as_rating", False)
        ol.addWidget(self.dist_rating_chk)
        wr = QHBoxLayout(); wr.addSpacing(24); wr.addWidget(QLabel("Weight:"))
        self.weight_spin = QSpinBox()
        self.weight_spin.setRange(0, 100); self.weight_spin.setSuffix("  %")
        self._persist_spin(self.weight_spin, "distance_weight", 50)
        self.weight_spin.setEnabled(self.dist_rating_chk.isChecked())
        wr.addWidget(self.weight_spin); wr.addStretch(); ol.addLayout(wr)
        self.dist_rating_chk.stateChanged.connect(
            lambda s: self.weight_spin.setEnabled(bool(s)))

        sep3 = QFrame(); sep3.setFrameShape(QFrame.HLine); sep3.setFrameShadow(QFrame.Sunken)
        ol.addWidget(sep3)
        self.upward_chk = QCheckBox("Add only upward points")
        self._persist_checkbox(self.upward_chk, "add_only_upward", False)
        ol.addWidget(self.upward_chk)
        L.addWidget(g4)

        fg, self._fence_sel = _fence_group(self); L.addWidget(fg)
        L.addStretch(); self._make_buttons(L)

    def _on_ok(self):
        sm = {0: "aerial_low_ground", 1: "lowest_only", 2: "ground_only"}
        self._run_algorithm(classify_ground_ptd, {
            "from_classes":          self._get_from(),
            "to_class":              self._get_to()[0],
            "current_ground":        self._get_cur()[0],
            "seed_method":           sm.get(self.select_combo.currentIndex(),
                                            "aerial_low_ground"),
            "max_building_size":     self.max_bldg_spin.value(),
            "terrain_angle":         self.terrain_spin.value(),
            "iteration_angle":       self.ia_spin.value(),
            "iteration_distance":    self.id_spin.value(),
            "reduce_angle_edge":     self.reduce_chk.isChecked(),
            "edge_length_threshold": self.edge_spin.value(),
            "stop_triangulation":    self.stop_chk.isChecked(),
            "stop_edge_length":      self.stop_edge_spin.value(),
            "use_distance_as_rating":self.dist_rating_chk.isChecked(),
            "distance_weight":       float(self.weight_spin.value()),
            "add_only_upward":       self.upward_chk.isChecked(),
            "fence_mask":            self._get_fence_mask(self._fence_sel),
        }, "Classify Ground")


# ═══════════════════════════════════════════════════════════════════════
# DIALOG 4 — CLASSIFY BELOW SURFACE
# ═══════════════════════════════════════════════════════════════════════
class ClassifyBelowSurfaceDialog(_BaseClassifyDialog):
    _persist_prefix = "below_surface"

    def __init__(self, app, parent=None):
        super().__init__(app, "Classify Below Surface", parent)
        self._build_ui()
        self.resize(400, 470)

    def _build_ui(self):
        L = QVBoxLayout(self); L.setSpacing(8)


        # ── Classes group ─────────────────────────────────────────────
        g1 = QGroupBox("Classes"); f1 = QFormLayout(g1); f1.setLabelAlignment(Qt.AlignRight)
        r1, self._get_from = _make_class_row(
            self.app, [2], multi=False, single_default=2,
            persist_key=self._pk("from_class"))
        r2, self._get_to = _make_class_row(
            self.app, [7], multi=False, single_default=7,
            persist_key=self._pk("to_class"))
        f1.addRow("From class:", _w(r1)); f1.addRow("To class:", _w(r2))
        L.addWidget(g1)

        # ── Surface fitting group ─────────────────────────────────────
        g2 = QGroupBox("Surface Fitting")
        f2 = QFormLayout(g2); f2.setLabelAlignment(Qt.AlignRight)

        self.surface_combo = QComboBox()
        self.surface_combo.addItems(["Planar  (z = ax + by + c)",
                                     "Curved  (z = ax² + by² + cxy + dx + ey + f)"])
        self._persist_combo_index(self.surface_combo, "surface_type", 0)
        f2.addRow("Surface:", self.surface_combo)

        self.limit_spin = QDoubleSpinBox()
        self.limit_spin.setRange(0.1, 999); self.limit_spin.setDecimals(1)
        self._persist_spin(self.limit_spin, "limit", 4.0)
        lr = QHBoxLayout(); lr.addWidget(self.limit_spin)
        lr.addWidget(QLabel("× ave magnitude"))
        f2.addRow("Limit:", _w(lr))

        self.ztol_spin = QDoubleSpinBox()
        self.ztol_spin.setRange(0.001, 99); self.ztol_spin.setDecimals(2)
        self._persist_spin(self.ztol_spin, "z_tolerance", 0.10)
        zr = QHBoxLayout(); zr.addWidget(self.ztol_spin); zr.addWidget(QLabel("m"))
        f2.addRow("Z tolerance:", _w(zr))

        self.nn_spin = QSpinBox(); self.nn_spin.setRange(3, 200)
        self._persist_spin(self.nn_spin, "num_neighbors", 25)
        nr = QHBoxLayout(); nr.addWidget(self.nn_spin)
        nr.addWidget(QLabel("nearest neighbors for surface fit"))
        f2.addRow("K neighbors:", _w(nr))

        L.addWidget(g2)

        # ── Options group ─────────────────────────────────────────────
        g3 = QGroupBox("Options"); ol = QVBoxLayout(g3); ol.setSpacing(4)

        self.iter_chk = QCheckBox("🔄 Iterate until stable (progressive cleanup)")
        self._persist_checkbox(self.iter_chk, "iterative", False)
        ol.addWidget(self.iter_chk)

        ir = QHBoxLayout(); ir.addSpacing(24); ir.addWidget(QLabel("Max iterations:"))
        self.max_iter_spin = QSpinBox(); self.max_iter_spin.setRange(1, 50)
        self._persist_spin(self.max_iter_spin, "max_iterations", 5)
        self.max_iter_spin.setEnabled(self.iter_chk.isChecked())
        ir.addWidget(self.max_iter_spin); ir.addStretch(); ol.addLayout(ir)
        self.iter_chk.stateChanged.connect(
            lambda s: self.max_iter_spin.setEnabled(bool(s)))

        info = QLabel(
            "ℹ️ Fits local surface through K neighbors.\n"
            "   Flags points below surface by > limit × ave|residual|.\n"
            "   MicroStation equivalent: post-ground cleanup.")
        info.setStyleSheet(_note_text_style())
        info.setWordWrap(True)
        ol.addWidget(info)

        L.addWidget(g3)

        # ── Fence ─────────────────────────────────────────────────────
        fg, self._fence_sel = _fence_group(self); L.addWidget(fg)
        L.addStretch(); self._make_buttons(L)

    def _on_ok(self):
        self._run_algorithm(classify_below_surface, {
            "from_classes":   self._get_from(),
            "to_class":       self._get_to()[0],
            "surface_type":   "planar" if self.surface_combo.currentIndex() == 0
                              else "curved",
            "limit":          self.limit_spin.value(),
            "z_tolerance":    self.ztol_spin.value(),
            "num_neighbors":  self.nn_spin.value(),
            "fence_mask":     self._get_fence_mask(self._fence_sel),
            "iterative":      self.iter_chk.isChecked(),
            "max_iterations": self.max_iter_spin.value(),
        }, "Classify Below Surface")


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC API  — restore-aware open helpers
# ═══════════════════════════════════════════════════════════════════════
def _open_or_restore(app, attr: str, cls):
    """
    If the dialog exists and is chip-minimized → restore it.
    If it exists and is visible               → just raise it.
    Otherwise create a fresh instance.
    """
    existing = getattr(app, attr, None)
    if existing is not None:
        try:
            if existing._is_minimized_to_chip:
                existing._do_restore_from_chip()
            else:
                existing.show()
                existing.raise_()
                existing.activateWindow()
            return
        except RuntimeError:
            # C++ object already deleted — create fresh
            setattr(app, attr, None)

    dlg = cls(app, parent=app)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    setattr(app, attr, dlg)
    dlg.show()


def open_classify_low_points(app):
    _open_or_restore(app, '_classify_low_points_dlg', ClassifyLowPointsDialog)

def open_classify_isolated_points(app):
    _open_or_restore(app, '_classify_isolated_points_dlg', ClassifyIsolatedPointsDialog)

def open_classify_ground(app):
    _open_or_restore(app, '_classify_ground_dlg', ClassifyGroundDialog)

def open_classify_below_surface(app):
    _open_or_restore(app, '_classify_below_surface_dlg', ClassifyBelowSurfaceDialog)
