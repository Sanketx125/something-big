"""
gui/icon_provider.py
────────────────────
Centralized SVG icon provider for NakshaAI-Lidar ribbon toolbar.
All icons are embedded as SVG strings for zero-dependency, theme-aware rendering.
"""

from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtCore import QByteArray, QSize, Qt, QRectF
from PySide6.QtSvg import QSvgRenderer
from pathlib import Path
import re


_ICON_DIR = Path(__file__).resolve().parent / "icons"
_BUILTIN_SVG_SCALE = 0.92
_EXTERNAL_SVG_SCALE = 1.12
_LARGE_CANVAS_EXTERNAL_SVGS = {
    "dwg.svg",
    "dxf.svg",
    "snt.svg",
    "prj.svg",
}


def _normalize_lookup_text(value: str | None) -> str:
    """Normalize ribbon labels for robust icon lookup."""
    if value is None:
        return ""

    value = value.replace("\n", " ").replace("…", "...").replace("â€¦", "...")
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()


def _resolve_icon_color(color: str | None) -> str:
    """Resolve the theme-aware icon color when none is provided."""
    if color:
        return color

    from gui.theme_manager import ThemeColors
    return ThemeColors.get("icon_primary")


def _apply_svg_current_color(svg_data: bytes, color: str) -> bytes:
    """Replace SVG currentColor tokens with a concrete theme color."""
    try:
        svg_text = svg_data.decode("utf-8")
    except UnicodeDecodeError:
        return svg_data

    if "currentColor" not in svg_text and "currentcolor" not in svg_text:
        return svg_data

    svg_text = re.sub(r"currentColor", color, svg_text, flags=re.IGNORECASE)
    return svg_text.encode("utf-8")


# ═══════════════════════════════════════════════════════════════════════════
#  SVG ICON DEFINITIONS  (24x24 viewBox, stroke-based)
# ═══════════════════════════════════════════════════════════════════════════

_SVG_HEADER = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
_SVG_FOOTER = '</svg>'

# Each entry: icon_name -> SVG body (paths/shapes between header and footer)
_ICON_DATA = {
    # ── File Operations ──────────────────────────────────────────
    "folder_open": '<path d="M3 18V6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v2"/><path d="M3 18l2.4-7.2A2 2 0 0 1 7.3 9.5H21l-2.4 7.2a2 2 0 0 1-1.9 1.3H3z"/>',

    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',

    "save_as": '<path d="M17 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9l5 5v5"/><polyline points="14 21 14 13 7 13 7 21"/><polyline points="7 3 7 8 13 8"/><path d="M18.5 15.5l3 3-3 3"/><line x1="16" y1="18.5" x2="21.5" y2="18.5"/>',

    "export": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',

    "import": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',

    "attach": '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',

    "clipboard_list": '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="8" y1="16" x2="13" y2="16"/>',

    "search": '<circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/>',

    "file_dwg": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><text x="12" y="16" text-anchor="middle" font-size="6" font-weight="bold" fill="{color}" stroke="none">DWG</text>',

    "file_snt": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><text x="12" y="16" text-anchor="middle" font-size="6" font-weight="bold" fill="{color}" stroke="none">SNT</text>',

    "broom": '<path d="M12 3v9"/><path d="M8 12c0 4 1.5 9 4 9s4-5 4-9"/><line x1="7" y1="12" x2="17" y2="12"/>',

    # ── Edit Operations ──────────────────────────────────────────
    "undo": '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',

    "redo": '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.13-9.36L23 10"/>',

    "cut": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/>',

    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',

    "paste": '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>',

    "trash": '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>',

    # ── View Operations ──────────────────────────────────────────
    "view_top": '<rect x="4" y="8" width="16" height="12" rx="1"/><path d="M12 3v5"/><polyline points="9 5 12 8 15 5"/>',

    "view_front": '<rect x="4" y="4" width="16" height="16" rx="1"/><path d="M4 12h16"/><circle cx="12" cy="12" r="2"/>',

    "view_side": '<path d="M4 4h16v16H4z"/><path d="M4 4l6 6"/><path d="M20 4l-6 6"/><path d="M10 10h4v4h-4z"/>',

    "view_3d": '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>',

    "depth": '<rect x="3" y="3" width="14" height="10" rx="1"/><rect x="7" y="7" width="14" height="10" rx="1"/><rect x="5" y="5" width="14" height="10" rx="1" opacity="0.5"/>',

    "rgb": '<circle cx="9" cy="9" r="5" opacity="0.7"/><circle cx="15" cy="9" r="5" opacity="0.7"/><circle cx="12" cy="14" r="5" opacity="0.7"/>',

    "intensity": '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="6.34" y2="6.34"/><line x1="17.66" y1="17.66" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="6.34" y2="17.66"/><line x1="17.66" y1="6.34" x2="19.78" y2="4.22"/>',

    "elevation": '<rect x="4" y="14" width="4" height="7"/><rect x="10" y="8" width="4" height="13"/><rect x="16" y="3" width="4" height="18"/>',

    "class_tag": '<path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1.5" fill="{color}"/>',

    "shading": '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="{color}"/>',

    "fit_view": '<path d="M3 3h6v2H5v4H3V3z"/><path d="M21 3h-6v2h4v4h2V3z"/><path d="M3 21h6v-2H5v-4H3v6z"/><path d="M21 21h-6v-2h4v-4h2v6z"/><circle cx="12" cy="12" r="3"/>',

    "reset": '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.13-9.36L23 10"/>',

    # ── Tools Operations ─────────────────────────────────────────
    "cross_section": '<line x1="3" y1="12" x2="21" y2="12"/><line x1="12" y1="3" x2="12" y2="21"/><circle cx="12" cy="12" r="2"/>',

    "cut_section": '<path d="M3 12h7"/><path d="M14 12h7"/><path d="M10 6l4 12"/><polyline points="8 4 10 6 8 8"/><polyline points="16 16 14 18 16 20"/>',

    "ruler": '<path d="M3 21L21 3"/><path d="M6 18l1-1"/><path d="M9 15l2-2"/><path d="M12 12l1-1"/><path d="M15 9l2-2"/><path d="M18 6l1-1"/>',

    "sync": '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',

    "keyboard": '<rect x="2" y="5" width="20" height="14" rx="2"/><line x1="6" y1="9" x2="6.01" y2="9"/><line x1="10" y1="9" x2="10.01" y2="9"/><line x1="14" y1="9" x2="14.01" y2="9"/><line x1="18" y1="9" x2="18.01" y2="9"/><line x1="7" y1="15" x2="17" y2="15"/>',

    "backup": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/>',

    "preferences": '<line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/><circle cx="8" cy="6" r="2" fill="{color}"/><circle cx="16" cy="12" r="2" fill="{color}"/><circle cx="10" cy="18" r="2" fill="{color}"/>',

    # ── Classify Operations ──────────────────────────────────────
    "arrow_up": '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',

    "arrow_down": '<line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>',

    "rectangle": '<rect x="4" y="4" width="16" height="16" rx="2"/>',

    "circle": '<circle cx="12" cy="12" r="9"/>',

    "freehand": '<path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',

    "brush": '<path d="M20 4L8.5 15.5"/><path d="M7 17c-2 2-4 2-5 1s-1-3 1-5"/><path d="M8.5 15.5l-1.5 1.5c-1 1-1 2.5 0 3.5s2.5 1 3.5 0l1.5-1.5"/><path d="M15 7l2-2"/>',

    "point_marker": '<path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/><circle cx="12" cy="9" r="2.5" fill="{color}"/>',

    # ── Measurement Operations ───────────────────────────────────
    "measure_line": '<line x1="4" y1="20" x2="20" y2="4"/><polyline points="4 16 4 20 8 20"/><polyline points="20 8 20 4 16 4"/><line x1="10" y1="10" x2="14" y2="14" stroke-dasharray="2,2"/>',

    "measure_path": '<polyline points="4 18 8 10 14 14 20 6"/><circle cx="4" cy="18" r="1.5" fill="{color}"/><circle cx="8" cy="10" r="1.5" fill="{color}"/><circle cx="14" cy="14" r="1.5" fill="{color}"/><circle cx="20" cy="6" r="1.5" fill="{color}"/>',

    # ── Identify Operations ──────────────────────────────────────
    "identify": '<circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',

    "zoom_rect": '<circle cx="10" cy="10" r="6"/><line x1="14.5" y1="14.5" x2="20" y2="20"/><rect x="7" y="7" width="6" height="6" rx="0.5" stroke-dasharray="2,1"/>',

    "select_check": '<rect x="3" y="3" width="18" height="18" rx="2"/><polyline points="9 12 11 14 16 9"/>',

    # ── ByClass Operations ───────────────────────────────────────
    "convert": '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',

    "pin_close": '<path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/><circle cx="12" cy="9" r="2" fill="{color}"/>',

    "height_ruler": '<line x1="12" y1="2" x2="12" y2="22"/><polyline points="8 6 12 2 16 6"/><polyline points="8 18 12 22 16 18"/><line x1="8" y1="8" x2="12" y2="8"/><line x1="8" y1="12" x2="12" y2="12"/><line x1="8" y1="16" x2="12" y2="16"/>',

    "fence": '<path d="M12 2l8 5v10l-8 5-8-5V7z"/>',

    "isolated": '<circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="8" stroke-dasharray="3,2"/>',

    "mountain": '<path d="M3 20L8 10l3 4 5-10 5 16H3z"/>',

    "surface": '<path d="M3 16h18"/><path d="M6 16V8"/><path d="M18 16V8"/><path d="M12 16V10"/><polyline points="9 12 12 10 15 12"/>',

    # ── Draw Operations ──────────────────────────────────────────
    "smartline": '<path d="M15 4V2a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v2"/><path d="M3 10l3-6h12l3 6"/><line x1="12" y1="10" x2="12" y2="22"/><line x1="8" y1="10" x2="16" y2="10"/><path d="M9 22h6"/>',

    "line": '<line x1="5" y1="19" x2="19" y2="5"/><circle cx="5" cy="19" r="1.5" fill="{color}"/><circle cx="19" cy="5" r="1.5" fill="{color}"/>',

    "polyline": '<polyline points="4 18 8 8 14 14 20 6"/><circle cx="4" cy="18" r="1.5" fill="{color}"/><circle cx="8" cy="8" r="1.5" fill="{color}"/><circle cx="14" cy="14" r="1.5" fill="{color}"/><circle cx="20" cy="6" r="1.5" fill="{color}"/>',

    "text": '<polyline points="4 7 12 7 20 7"/><line x1="12" y1="7" x2="12" y2="21"/>',

    "move_vertex": '<polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="19 9 22 12 19 15"/><polyline points="9 19 12 22 15 19"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/>',

    "vertex": '<circle cx="12" cy="12" r="3" fill="{color}"/><line x1="4" y1="18" x2="12" y2="12"/><line x1="12" y1="12" x2="20" y2="6"/>',

    "grid": '<line x1="3" y1="3" x2="3" y2="21"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/><line x1="21" y1="3" x2="21" y2="21"/><line x1="3" y1="3" x2="21" y2="3"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="3" y1="21" x2="21" y2="21"/>',

    "select_target": '<circle cx="12" cy="12" r="9"/><line x1="12" y1="3" x2="12" y2="7"/><line x1="12" y1="17" x2="12" y2="21"/><line x1="3" y1="12" x2="7" y2="12"/><line x1="17" y1="12" x2="21" y2="12"/><circle cx="12" cy="12" r="2" fill="{color}"/>',

    "deselect": '<circle cx="12" cy="12" r="9"/><line x1="8" y1="8" x2="16" y2="16"/><line x1="16" y1="8" x2="8" y2="16"/>',

    "settings_gear": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',

    # ── Curve Operations ─────────────────────────────────────────
    "curve_point": '<path d="M4 20C4 20 8 4 12 4s8 16 8 16"/><circle cx="4" cy="20" r="1.5" fill="{color}"/><circle cx="12" cy="4" r="1.5" fill="{color}"/><circle cx="20" cy="20" r="1.5" fill="{color}"/>',

    # ── AI Operations ────────────────────────────────────────────
    "ai_brain": '<path d="M12 2a7 7 0 0 0-7 7c0 2.5 1.3 4.7 3.3 5.9"/><path d="M12 2a7 7 0 0 1 7 7c0 2.5-1.3 4.7-3.3 5.9"/><path d="M8.7 14.9A5.5 5.5 0 0 0 12 22a5.5 5.5 0 0 0 3.3-7.1"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>',

    "rocket": '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',

    # ── Display Config ───────────────────────────────────────────
    "config_display": '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/><circle cx="12" cy="10" r="2"/><path d="M9.5 7.5l-1-1"/><path d="M14.5 7.5l1-1"/><path d="M14.5 12.5l1 1"/>',

    # ── Section Width ────────────────────────────────────────────
    "section_width": '<path d="M4 4v16"/><path d="M20 4v16"/><line x1="4" y1="12" x2="20" y2="12"/><polyline points="7 9 4 12 7 15"/><polyline points="17 9 20 12 17 15"/>',
}


def _build_svg(icon_name: str, color: str = "#cccccc") -> bytes:
    """Build a complete SVG string for the given icon name and color."""
    body = _ICON_DATA.get(icon_name, "")
    header = _SVG_HEADER.replace("{color}", color)
    body = body.replace("{color}", color)
    return (header + body + _SVG_FOOTER).encode("utf-8")


def _render_svg_bytes(svg_data: bytes, size: int, scale: float = 1.0) -> QIcon:
    """Render SVG bytes into a QIcon at the requested size."""
    renderer = QSvgRenderer(QByteArray(svg_data))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    render_size = float(size) * float(scale)
    offset = (float(size) - render_size) / 2.0
    renderer.render(painter, QRectF(offset, offset, render_size, render_size))
    painter.end()

    return QIcon(pixmap)


def _load_icon_from_file(icon_path: Path, size: int, color: str = None) -> QIcon:
    """Load a disk-backed icon, rendering SVGs to a consistent size."""
    if not icon_path.exists():
        return QIcon()

    if icon_path.suffix.lower() == ".svg":
        try:
            scale = _EXTERNAL_SVG_SCALE
            if icon_path.name in _LARGE_CANVAS_EXTERNAL_SVGS:
                scale = 1.18
            svg_data = _apply_svg_current_color(
                icon_path.read_bytes(),
                _resolve_icon_color(color),
            )
            return _render_svg_bytes(svg_data, size, scale=scale)
        except Exception:
            return QIcon(str(icon_path))

    return QIcon(str(icon_path))


def get_icon(name: str, color: str = None, size: int = 24) -> QIcon:
    """
    Get a QIcon for the given icon name.

    Args:
        name:  Icon identifier (e.g. 'folder_open', 'save', 'trash')
        color: Hex color string. If None, uses theme-appropriate default.
        size:  Icon pixel size (default 24).

    Returns:
        QIcon with the rendered SVG icon.
    """
    if name not in _ICON_DATA:
        # Fallback: return empty icon
        return QIcon()

    if color is None:
        from gui.theme_manager import ThemeColors
        color = ThemeColors.get("icon_primary")

    return _render_svg_bytes(_build_svg(name, color), size, scale=_BUILTIN_SVG_SCALE)


def get_icon_pixmap(name: str, color: str = None, size: int = 24) -> QPixmap:
    """Get a QPixmap for the given icon name."""
    if name not in _ICON_DATA:
        return QPixmap()

    if color is None:
        from gui.theme_manager import ThemeColors
        color = ThemeColors.get("icon_primary")

    svg_data = _build_svg(name, color)

    icon = _render_svg_bytes(svg_data, size, scale=_BUILTIN_SVG_SCALE)
    return icon.pixmap(size, size)


_SCOPED_EXTERNAL_RIBBON_ICON_FILES = {
    ("measurementribbon", "actions", "clear"): "clear-measurements.svg",
    ("drawribbon", "actions", "clear"): "clear-drawing-line.svg",
    ("curveribbon", "actions", "clear"): "clear-curve.svg",
    ("drawribbon", "tools", "rect"): "rectangle-draw.svg",
    ("drawribbon", "tools", "circle"): "circle-draw.svg",
    ("drawribbon", "tools", "free"): "freehand-draw.svg",
    ("classifyribbon", "shapes", "rect"): "rectangle-select.svg",
    ("classifyribbon", "shapes", "circle"): "circle.svg",
    ("classifyribbon", "shapes", "free"): "freehand.svg",
}


_EXTERNAL_RIBBON_ICON_FILES = {
    ("file", "open"): "open-file.svg",
    ("file", "save"): "save.svg",
    ("file", "save as..."): "save-as.svg",
    ("vectors", "export"): "export.svg",
    ("vectors", "import"): "import.svg",
    ("attachments", "attach dxf"): "dxf.svg",
    ("attachments", "prj loader"): "prj.svg",
    ("attachments", "verify labels"): "verify-grid-labels.svg",
    ("attachments", "attach dwg"): "dwg.svg",
    ("attachments", "attach snt"): "snt.svg",
    ("dxf", "attach"): "dxf.svg",
    ("dxf", "define"): "prj.svg",
    ("dxf", "verify labels"): "verify-grid-labels.svg",
    ("dwg", "attach"): "dwg.svg",
    ("snt", "attach"): "snt.svg",
    ("project", "clear"): "clear-project.svg",
    ("history", "undo"): "undo.svg",
    ("history", "redo"): "redo.svg",
    ("clipboard", "cut"): "cut.svg",
    ("clipboard", "copy"): "copy.svg",
    ("clipboard", "paste"): "paste.svg",
    ("delete", "delete"): "delete.svg",
    ("views", "top"): "top-view.svg",
    ("views", "front"): "front-view.svg",
    ("views", "side"): "side-view.svg",
    ("views", "3d"): "3d-view.svg",
    ("display", "rgb"): "icon-view-rgb.svg",
    ("display", "intensity"): "icon-view-intensity.svg",
    ("display", "elevation"): "icon-view-elevation.svg",
    ("display", "class"): "icon-view-class.svg",
    ("display", "shading"): "icon-view-shading.svg",
    ("navigate", "fit"): "fit-view.svg",
    ("sections", "cross"): "cross-section.svg",
    ("sections", "cut section"): "cut-section.svg",
    ("sections", "width"): "width.svg",
    ("sync", "views"): "sync-view.svg",
    ("selection", "config"): "shortcut-config.svg",
    ("settings", "backup"): "backup-settings.svg",
    ("settings", "preferences"): "cross-section-pref.svg",
    ("lines", "above"): "above.svg",
    ("lines", "below"): "below.svg",
    ("points", "brush"): "brush.svg",
    ("points", "point"): "point.svg",
    ("config", "display"): "display-mode.svg",
    ("distance", "measure line"): "measure-line.svg",
    ("distance", "measure path"): "measure-path.svg",
    ("identify", "identify"): "identify-point.svg",
    ("identify", "zoom"): "zoom-rectangle.svg",
    ("identify", "select"): "select.svg",
    ("by class", "convert"): "by-class-conversion.svg",
    ("by class", "close"): "closed-feature-conversion.svg",
    ("by class", "height"): "height-conversion.svg",
    ("by class", "fence"): "fence-conversion.svg",
    ("algorithms", "low points"): "low-points.svg",
    ("algorithms", "isolated"): "isolated-points.svg",
    ("algorithms", "ground"): "ground-classification.svg",
    ("algorithms", "surface"): "below-surface.svg",
    ("tools", "smart line"): "smart-line.svg",
    ("tools", "line"): "line.svg",
    ("tools", "polyline"): "polygon.svg",
    ("tools", "text"): "text.svg",
    ("tools", "move vertex"): "move-vertex.svg",
    ("tools", "vertex"): "vertex.svg",
    ("tools", "grid"): "grid.svg",
    ("select", "select drawing"): "select.svg",
    ("select", "deselect all"): "deselect.svg",
    ("settings", "draw settings"): "draw-settings.svg",
    ("curve tools", "curve point"): "curve.svg",
    ("File", "Save"): "icon-save.svg",
    ("File", "Save As…"): "icon-save-as.svg",
    ("Vectors", "Export"): "icon-export.svg",
    ("Vectors", "Import"): "icon-import.svg",
    ("Attachments", "Attach DXF"): "dxf-icon.svg",
    ("Attachments", "PRJ Loader"): "prj-icon.svg",
    ("Attachments", "Verify Labels"): "icon-verify-labels.svg",
    ("Attachments", "Attach DWG"): "dwg-icon.svg",
    ("Attachments", "Attach SNT"): "snt-icon.svg",
    ("DXF", "Attach"): "dxf-icon.svg",
    ("DXF", "Define"): "prj-icon.svg",
    ("DXF", "Verify Labels"): "icon-verify-labels.svg",
    ("DWG", "Attach"): "dwg-icon.svg",
    ("SNT", "Attach"): "snt-icon.svg",
    ("Project", "Clear"): "icon-clear-project.svg",
    ("Views", "Top"): "icon-view-top.svg",
    ("Views", "Front"): "icon-view-front.svg",
    ("Views", "Side"): "icon-view-side.svg",
    ("Views", "3D"): "icon-view-3d.svg",
    ("Display", "RGB"): "icon-view-rgb.svg",
    ("Display", "Intensity"): "icon-view-intensity.svg",
    ("Display", "Elevation"): "icon-view-elevation.svg",
    ("Display", "Class"): "icon-view-class.svg",
    ("Display", "Shading"): "icon-view-shading.svg",
    ("Navigate", "Fit"): "icon-fit-view.svg",
    ("Sections", "Cross"): "icon-cross-section.svg",
    ("Sections", "Cut Section"): "icon-cut-section.svg",
    ("Sections", "Width"): "icon-tools-width.svg",
    ("Sync", "Views"): "icon-sync-views.svg",
    ("Selection", "Config"): "icon-config.svg",
    ("Settings", "Backup"): "icon-backup.svg",
    ("Settings", "Preferences"): "icon-preferences.svg",
    ("Lines", "Above"): "icon-classify-above.svg",
    ("Lines", "Below"): "icon-classify-below.svg",
    ("Shapes", "Rect"): "icon-classify-rectangle.svg",
    ("Shapes", "Circle"): "icon-classify-circle.svg",
    ("Shapes", "Free"): "icon-classify-freehand.svg",
    ("Points", "Brush"): "icon-classify-brush.svg",
    ("Points", "Point"): "icon-classify-point.svg",
    ("Config", "Display"): "icon-display-mode.svg",
    ("Distance", "Measure Line"): "icon-measure-line.svg",
    ("Distance", "Measure Path"): "icon-measure-path.svg",
    ("Identify", "Identify"): "icon-identify.svg",
    ("Identify", "Zoom"): "icon-zoom.svg",
    ("Identify", "Select"): "icon-select.svg",
    ("By Class", "Convert"): "icon-convert.svg",
    ("By Class", "Close"): "icon-close.svg",
    ("By Class", "Height"): "icon-measure-height.svg",
    ("By Class", "Fence"): "icon-fence.svg",
    ("Algorithms", "Low Points"): "icon-low-points.svg",
    ("Algorithms", "Isolated"): "icon-isolated.svg",
    ("Algorithms", "Ground"): "icon-ground.svg",
    ("Algorithms", "Surface"): "icon-surface.svg",
}


def get_external_ribbon_icon_path(button_text: str, section_title: str = None,
                                  ribbon_scope: str = None) -> Path | None:
    """Return a user-provided ribbon icon path when one exists."""
    filename = _SCOPED_EXTERNAL_RIBBON_ICON_FILES.get((
        _normalize_lookup_text(ribbon_scope),
        _normalize_lookup_text(section_title),
        _normalize_lookup_text(button_text),
    ))
    if not filename:
        filename = _EXTERNAL_RIBBON_ICON_FILES.get((
            _normalize_lookup_text(section_title),
            _normalize_lookup_text(button_text),
        ))
    if not filename:
        return None

    icon_path = _ICON_DIR / filename
    if icon_path.exists():
        return icon_path
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  ICON NAME MAPPING (tool label -> icon name)
# ═══════════════════════════════════════════════════════════════════════════

# Maps the ribbon button label/tooltip to the icon name
RIBBON_ICONS = {
    # File
    "Open": "folder_open",
    "Save": "save",
    "Save As…": "save_as",
    "Export": "export",
    "Import": "import",
    "Attach": "attach",
    "Attach DXF": "attach",
    "Attach DWG": "file_dwg",
    "Attach SNT": "file_snt",
    "PRJ Loader": "clipboard_list",
    "Define": "clipboard_list",
    "Verify Labels": "search",
    "Clear": "broom",

    # Edit
    "Undo": "undo",
    "Redo": "redo",
    "Cut": "cut",
    "Copy": "copy",
    "Paste": "paste",
    "Delete": "trash",

    # View
    "Top": "view_top",
    "Front": "view_front",
    "Side": "view_side",
    "3D": "view_3d",
    "Depth": "depth",
    "RGB": "rgb",
    "Intensity": "intensity",
    "Elevation": "elevation",
    "Class": "class_tag",
    "Shading": "shading",
    "Fit": "fit_view",

    # Tools
    "Cross": "cross_section",
    "Cut Section": "cut_section",
    "Width": "section_width",
    "Views": "sync",
    "Config": "keyboard",
    "Backup": "backup",
    "Preferences": "preferences",

    # Classify
    "Above": "arrow_up",
    "Below": "arrow_down",
    "Rect": "rectangle",
    "Circle": "circle",
    "Free": "freehand",
    "Brush": "brush",
    "Point": "point_marker",

    # Measure
    "Line": "line",
    "Measure Line": "measure_line",
    "Path": "measure_path",
    "Measure Path": "measure_path",

    # Identify
    "Identify": "identify",
    "Zoom": "zoom_rect",
    "Select": "select_check",

    # ByClass
    "Convert": "convert",
    "Close": "pin_close",
    "Height": "height_ruler",
    "Fence": "fence",
    "Low Points": "arrow_down",
    "Isolated": "isolated",
    "Ground": "mountain",
    "Surface": "surface",

    # Draw
    "Smart\nLine": "smartline",
    "Polyline": "polyline",
    "Text": "text",
    "Move\nVertex": "move_vertex",
    "Vertex": "vertex",
    "Grid": "grid",
    "Select\nDrawing": "select_target",
    "Deselect\nAll": "deselect",
    "Draw\nSettings": "settings_gear",

    # Curve
    "Curve\nPoint": "curve_point",

    # AI
    "Start": "rocket",

    # Display
    "Display": "config_display",
}

_NORMALIZED_RIBBON_ICONS = {
    _normalize_lookup_text(label): icon_name
    for label, icon_name in RIBBON_ICONS.items()
}


def get_button_icon(button_text: str, section_title: str = None,
                    ribbon_scope: str = None,
                    color: str = None, size: int = 24) -> QIcon:
    """
    Resolve a ribbon button icon.
    Prefers user-provided files from gui/icons, then falls back to embedded SVGs.
    """
    external_icon_path = get_external_ribbon_icon_path(
        button_text,
        section_title=section_title,
        ribbon_scope=ribbon_scope,
    )
    if external_icon_path is not None:
        return _load_icon_from_file(external_icon_path, size, color=color)

    icon_name = RIBBON_ICONS.get(button_text)
    if not icon_name:
        icon_name = _NORMALIZED_RIBBON_ICONS.get(_normalize_lookup_text(button_text))
    if icon_name:
        return get_icon(icon_name, color, size)
    return QIcon()


def get_ribbon_icon(tooltip_text: str, color: str = None, size: int = 24,
                    section_title: str = None, ribbon_scope: str = None) -> QIcon:
    """
    Get a QIcon by ribbon button tooltip/label text.
    Falls back to empty icon if not found.
    """
    return get_button_icon(
        tooltip_text,
        section_title=section_title,
        ribbon_scope=ribbon_scope,
        color=color,
        size=size,
    )


def list_available_icons():
    """Return list of all available icon names."""
    return list(_ICON_DATA.keys())
