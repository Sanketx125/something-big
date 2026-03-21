"""
gui/theme_manager.py
─────────────────────
Centralized theme manager for NakshaAI-Lidar.
Supports Dark and Light themes with runtime switching.
Inspired by the Ring app's dual-theme system (themes.py).
"""

import os
from PySide6.QtCore import QEvent, QObject, QSettings


# ═══════════════════════════════════════════════════════════════════════════
#  THEME COLOR PALETTES
# ═══════════════════════════════════════════════════════════════════════════

class ThemeColors:
    """Theme-aware color palette for inline style usage."""

    # ── Dark palette ────────────────────────────────────────────────
    DARK = {
        # Base
        "bg_primary":       "#121212",
        "bg_secondary":     "#1a1a1a",
        "bg_tertiary":      "#202020",
        "bg_input":         "#1e1e1e",
        "bg_button":        "#2a2a2a",
        "bg_button_hover":  "#3c3c3c",
        "bg_active":        "#004d40",
        "bg_active_border": "#1b5e20",

        # Text
        "text_primary":     "#e0e0e0",
        "text_secondary":   "#aaaaaa",
        "text_muted":       "#888888",
        "text_on_active":   "#ffffff",
        "icon_primary":     "#d3d1c7",

        # Accent
        "accent":           "#007acc",
        "accent_hover":     "#0098ff",
        "accent_alt":       "#ffaa00",
        "dialog_primary_bg": "#30363c",
        "dialog_primary_hover": "#394148",
        "dialog_primary_border": "#505c66",
        "dialog_primary_text": "#f5f7fa",
        "dialog_selection": "#2b3138",

        # Borders
        "border":           "#2a2a2a",
        "border_light":     "#3a3a3a",
        "border_active":    "#007acc",

        # Status
        "danger":           "#d32f2f",
        "danger_hover":     "#f44336",
        "danger_dark":      "#b71c1c",
        "warning":          "#ff6f00",
        "warning_bg":       "#e65100",
        "success":          "#41613d",

        # Ribbon
        "ribbon_bg":        "#1e1e1c",
        "ribbon_section":   "#171715",
        "ribbon_button":    "#222220",
        "ribbon_btn_hover": "#2a2a28",
        "ribbon_btn_pressed":"#31312e",
        "ribbon_btn_border":"#2e2e2b",
        "ribbon_btn_checked":"#2b3540",
        "ribbon_btn_checked_border":"#556675",
        "ribbon_title":     "#4a4a47",

        # Misc
        "shadow":           "#000000",
    }

    # ── Light palette (Ring app inspired) ───────────────────────────
    LIGHT = {
        # Base
        "bg_primary":       "#f0f2f5",
        "bg_secondary":     "#ffffff",
        "bg_tertiary":      "#e8ecf0",
        "bg_input":         "#f7f8fa",
        "bg_button":        "#eef0f4",
        "bg_button_hover":  "#e0e4ea",
        "bg_active":        "#0077b6",
        "bg_active_border": "#005f8a",

        # Text
        "text_primary":     "#1b2838",
        "text_secondary":   "#607d8b",
        "text_muted":       "#90a4ae",
        "text_on_active":   "#1c1c1a",
        "icon_primary":     "#1c1c1a",

        # Accent
        "accent":           "#0077b6",
        "accent_hover":     "#00b4d8",
        "accent_alt":       "#0096c7",
        "dialog_primary_bg": "#e7ebef",
        "dialog_primary_hover": "#dde3e9",
        "dialog_primary_border": "#c3ccd5",
        "dialog_primary_text": "#26313a",
        "dialog_selection": "#edf1f4",

        # Borders
        "border":           "#d0d5dd",
        "border_light":     "#e0e4ea",
        "border_active":    "#00b4d8",

        # Status
        "danger":           "#d32f2f",
        "danger_hover":     "#f44336",
        "danger_dark":      "#b71c1c",
        "warning":          "#ff6f00",
        "warning_bg":       "#fff3e0",
        "success":          "#2e7d32",

        # Ribbon
        "ribbon_bg":        "#f4f2ec",
        "ribbon_section":   "#f0efea",
        "ribbon_button":    "#ffffff",
        "ribbon_btn_hover": "#fbfaf7",
        "ribbon_btn_pressed":"#ece8df",
        "ribbon_btn_border":"#d6d1c7",
        "ribbon_btn_checked":"#e6edf3",
        "ribbon_btn_checked_border":"#c0cdda",
        "ribbon_title":     "#a09f99",

        # Misc
        "shadow":           "#b0bec5",
    }

    _current = "dark"

    @classmethod
    def set_theme(cls, name: str):
        cls._current = name.lower()

    @classmethod
    def get(cls, key: str) -> str:
        palette = cls.LIGHT if cls._current == "light" else cls.DARK
        return palette.get(key, "#ff00ff")  # magenta = missing key

    @classmethod
    def current_theme(cls) -> str:
        return cls._current

    @classmethod
    def is_light(cls) -> bool:
        return cls._current == "light"


# ═══════════════════════════════════════════════════════════════════════════
#  RIBBON BUTTON STYLE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def get_active_button_style() -> str:
    """Return inline style for an ACTIVE (toggled-on) ribbon button."""
    c = ThemeColors
    return f"""
    QPushButton {{
        background-color: {c.get('ribbon_btn_checked')};
        color: {c.get('icon_primary')};
        font-weight: 600;
        border: 1px solid {c.get('ribbon_btn_checked_border')};
        border-radius: 10px;
    }}
    QPushButton:hover {{
        background-color: {c.get('ribbon_btn_checked')};
    }}
    """


def get_inactive_button_style() -> str:
    """Return inline style for an INACTIVE ribbon button."""
    c = ThemeColors
    return f"""
    QPushButton {{
        background-color: {c.get('ribbon_button')};
        color: {c.get('icon_primary')};
        border: 1px solid {c.get('ribbon_btn_border')};
        border-radius: 10px;
    }}
    QPushButton:hover {{
        background-color: {c.get('ribbon_btn_hover')};
        border: 1px solid {c.get('ribbon_btn_border')};
    }}
    """


def get_status_label_style() -> str:
    """Return style for identification / info status labels."""
    c = ThemeColors
    return f"""
    QLabel {{
        color: {c.get('text_secondary')};
        font-size: 9px;
        padding: 4px;
        background-color: {c.get('ribbon_button')};
        border-radius: 3px;
    }}
    """


def get_status_label_active_style(color_key="warning") -> str:
    """Return style for an active status label (e.g. select mode)."""
    c = ThemeColors
    if color_key == "warning":
        return f"""
        QLabel {{
            color: #ffb74d;
            font-size: 9px;
            font-weight: bold;
            padding: 4px;
            background-color: {c.get('warning_bg')};
            border-radius: 3px;
        }}
        """
    return get_status_label_style()


def get_sharpness_btn_style(variant="minus") -> str:
    """Return style for sharpness +/- buttons."""
    c = ThemeColors
    if variant == "minus":
        return f"""
        QPushButton {{
            background-color: {c.get('bg_input')};
            color: {c.get('text_primary')};
            border: 2px solid {c.get('border_light')};
            border-radius: 4px;
            font-size: 20px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {c.get('bg_button_hover')};
            border: 2px solid {c.get('accent')};
        }}
        QPushButton:pressed {{
            background-color: {c.get('accent')};
            color: {c.get('text_on_active')};
            border: 2px solid {c.get('accent')};
        }}
        """
    else:  # plus
        return f"""
        QPushButton {{
            background-color: {c.get('bg_button')};
            color: {c.get('accent')};
            border: 2px solid {c.get('border_light')};
            border-radius: 5px;
            font-size: 18px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {c.get('bg_button_hover')};
            border: 2px solid {c.get('accent')};
        }}
        QPushButton:pressed {{
            background-color: {c.get('accent')};
            color: {c.get('text_on_active')};
        }}
        """


def get_sharpness_value_style() -> str:
    """Return style for the sharpness value display label."""
    c = ThemeColors
    return f"""
    QLabel {{
        color: {c.get('text_primary')};
        font-size: 10px;
        font-weight: 700;
        background-color: {c.get('bg_input')};
        border: 1px solid {c.get('border_light')};
        border-radius: 12px;
        padding: 0px 10px;
    }}
    """


def get_reset_btn_style() -> str:
    """Return style for the amplifier reset button."""
    c = ThemeColors
    return f"""
    QPushButton {{
        background-color: {c.get('success')};
        color: #f0f0f0;
        border: 1px solid {c.get('border')};
        border-radius: 3px;
        font-size: 9px;
        font-weight: bold;
        padding: 2px;
    }}
    QPushButton:hover {{
        background-color: {c.get('bg_button_hover')};
        border: 1px solid {c.get('accent_alt')};
    }}
    QPushButton:pressed {{
        background-color: {c.get('accent_alt')};
        color: black;
    }}
    """


def get_delete_btn_style() -> str:
    """Return style for the delete selected points button."""
    c = ThemeColors
    return f"""
    QPushButton {{
        background-color: {c.get('danger')};
        color: white;
        font-size: 9px;
        font-weight: bold;
        border: 1px solid {c.get('danger_dark')};
        border-radius: 4px;
        padding: 4px;
    }}
    QPushButton:hover {{
        background-color: {c.get('danger_hover')};
        border: 1px solid {c.get('danger')};
    }}
    QPushButton:pressed {{
        background-color: {c.get('danger_dark')};
    }}
    """


def get_select_active_btn_style() -> str:
    """Return style for active select/tool buttons."""
    c = ThemeColors
    return f"""
    QPushButton {{
        background-color: {c.get('warning')};
        color: white;
        font-weight: bold;
        border: 1px solid {c.get('warning_bg')};
        border-radius: 6px;
    }}
    """


def get_sharp_label_style() -> str:
    """Style for the 'Sharp:' label in ViewRibbon."""
    c = ThemeColors
    return f"color: {c.get('text_primary')}; font-size: 10px; font-weight: bold;"


class _ThemeWindowEventFilter(QObject):
    """Applies the active theme when top-level widgets are shown."""

    def eventFilter(self, obj, event):
        try:
            if event.type() in (QEvent.Show, QEvent.WinIdChange):
                ThemeManager._refresh_widget_theme(obj)
        except Exception:
            pass
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  THEME MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class ThemeManager:
    """Manages loading and switching themes."""

    _current_theme = "dark"
    _window_event_filter = None

    @classmethod
    def apply_theme(cls, app_window, theme_name: str = "dark"):
        """Apply a theme to the main application window."""
        theme_name = theme_name.lower()
        cls._current_theme = theme_name
        ThemeColors.set_theme(theme_name)
        cls._ensure_window_event_filter()

        gui_dir = os.path.dirname(__file__)

        if theme_name == "light":
            qss_path = os.path.join(gui_dir, "theme_light.qss")
        else:
            qss_path = os.path.join(gui_dir, "theme.qss")

        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                qss = f.read()
            
            # Apply to app_window locally
            app_window.setStyleSheet(qss)
            
            # Apply to application globally so dialogs and popups inherit it
            try:
                from PySide6.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    app.setStyleSheet(qss)
            except Exception as e:
                print(f"⚠️ Could not apply theme to QApplication globally: {e}")

            print(f"🎨 {theme_name.capitalize()} theme loaded successfully")
        except Exception as e:
            print(f"⚠️ Failed to apply {theme_name} theme: {e}")

        # Refresh any open dialogs that opt into the shared dialog stylesheet
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                for widget in app.topLevelWidgets():
                    cls._refresh_widget_theme(widget)
        except Exception as e:
            print(f"⚠️ Failed to refresh themed dialogs: {e}")

        # Refresh floating docks and VTK surfaces that do not restyle from QSS alone.
        cls._refresh_open_windows()
        cls.refresh_runtime_surfaces(app_window)

        # Re-apply inline styles on ribbon system
        cls._refresh_ribbon_styles(app_window)

        # Save preference
        settings = QSettings("NakshaAI", "LidarApp")
        settings.setValue("ui_theme", theme_name)

    @classmethod
    def toggle_theme(cls, app_window):
        """Toggle between light and dark themes."""
        new_theme = "light" if cls._current_theme == "dark" else "dark"
        cls.apply_theme(app_window, new_theme)

    @classmethod
    def current(cls) -> str:
        return cls._current_theme

    @classmethod
    def load_saved_theme(cls) -> str:
        """Load the saved theme preference, default to dark."""
        settings = QSettings("NakshaAI", "LidarApp")
        return settings.value("ui_theme", "dark")

    @classmethod
    def _ensure_window_event_filter(cls):
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is None or cls._window_event_filter is not None:
                return

            cls._window_event_filter = _ThemeWindowEventFilter()
            app.installEventFilter(cls._window_event_filter)
        except Exception as e:
            print(f"⚠️ Failed to install theme window filter: {e}")

    @classmethod
    def _refresh_open_windows(cls):
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if not app:
                return

            for widget in app.topLevelWidgets():
                cls._refresh_widget_theme(widget)
        except Exception as e:
            print(f"⚠️ Failed to refresh themed windows: {e}")

    @classmethod
    def _refresh_widget_theme(cls, widget):
        try:
            from PySide6.QtWidgets import QDialog, QDockWidget, QProgressDialog, QWidget

            if not isinstance(widget, QWidget):
                return

            if widget.isWindow():
                cls.apply_native_window_theme(widget)

            if isinstance(widget, QProgressDialog):
                widget.setStyleSheet(get_progress_dialog_stylesheet())
            elif isinstance(widget, QDialog) and widget.property("themeStyledDialog"):
                refresh_theme = getattr(widget, "refresh_theme", None)
                if callable(refresh_theme):
                    refresh_theme()
                else:
                    widget.setStyleSheet(get_dialog_stylesheet())
            elif widget.property("themeStyledWindow"):
                refresh_theme = getattr(widget, "refresh_theme", None)
                if callable(refresh_theme):
                    refresh_theme()
                else:
                    widget.setStyleSheet(get_dialog_stylesheet())
            elif isinstance(widget, QDockWidget):
                style = widget.style()
                if style is not None:
                    style.unpolish(widget)
                    style.polish(widget)
                widget.update()
        except Exception as e:
            print(f"⚠️ Failed to refresh widget theme: {e}")

    @classmethod
    def apply_native_window_theme(cls, widget):
        """Use Windows immersive dark mode for native title bars when available."""
        if os.name != "nt" or widget is None:
            return

        try:
            import ctypes

            hwnd = int(widget.winId())
            if not hwnd:
                return

            value = ctypes.c_int(1 if cls.current() == "dark" else 0)
            dwmapi = ctypes.windll.dwmapi

            for attribute in (20, 19):
                result = dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd),
                    ctypes.c_uint(attribute),
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
                if result == 0:
                    break
        except Exception:
            pass

    @classmethod
    def refresh_runtime_surfaces(cls, app_window):
        """Refresh all currently open VTK canvases to match the active theme."""
        if app_window is None:
            return

        for vtk_widget in cls._iter_vtk_widgets(app_window):
            cls._apply_vtk_widget_theme(vtk_widget)

    @classmethod
    def _iter_vtk_widgets(cls, app_window):
        candidates = []

        for attr_name in ("vtk_widget", "sec_vtk"):
            widget = getattr(app_window, attr_name, None)
            if widget is not None:
                candidates.append(widget)

        section_vtks = getattr(app_window, "section_vtks", None)
        if isinstance(section_vtks, dict):
            candidates.extend(section_vtks.values())

        cut_controller = getattr(app_window, "cut_section_controller", None)
        if cut_controller is not None:
            cut_vtk = getattr(cut_controller, "cut_vtk", None)
            if cut_vtk is not None:
                candidates.append(cut_vtk)

        seen = set()
        for widget in candidates:
            if widget is None or id(widget) in seen:
                continue
            seen.add(id(widget))
            yield widget

    @classmethod
    def _apply_vtk_widget_theme(cls, vtk_widget):
        bg_color = "white" if cls.current() == "light" else "black"
        rgb = (1.0, 1.0, 1.0) if cls.current() == "light" else (0.0, 0.0, 0.0)

        try:
            vtk_widget.set_background(bg_color)
        except Exception:
            pass

        renderer = getattr(vtk_widget, "renderer", None)
        if renderer is not None:
            try:
                renderer.SetBackground(*rgb)
                renderer.SetBackground2(*rgb)
                renderer.GradientBackgroundOff()
            except Exception:
                pass

        try:
            vtk_widget.render()
        except Exception:
            pass

    @classmethod
    def _refresh_ribbon_styles(cls, app_window):
        """Re-apply theme-aware inline styles and icon colors on ribbon sections & buttons."""
        try:
            if not hasattr(app_window, 'ribbon_manager'):
                return

            from gui.menu_sidebar_system import RibbonSection
            from gui.icon_provider import get_button_icon
            from PySide6.QtWidgets import QPushButton
            from PySide6.QtCore import QSize

            icon_color = ThemeColors.get("icon_primary")

            for name, ribbon in app_window.ribbon_manager.ribbons.items():
                # Update all ribbon sections
                for section in ribbon.findChildren(RibbonSection):
                    # Reset active button style
                    if section.active_button:
                        section.active_button.setStyleSheet(get_active_button_style())

                    # Refresh icons on all buttons with new theme color
                    for btn in section.findChildren(QPushButton):
                        btn_text = btn.property("ribbonText")
                        section_title = btn.property("ribbonSection") or getattr(section, "section_title", None)
                        ribbon_scope = btn.property("ribbonScope") or getattr(section, "ribbon_scope", None)

                        if not btn_text:
                            tooltip = btn.toolTip()
                            if tooltip.startswith("<b>") and tooltip.endswith("</b>"):
                                btn_text = tooltip[3:-4]

                        if btn_text:
                            icon = get_button_icon(btn_text, section_title=section_title,
                                                   ribbon_scope=ribbon_scope,
                                                   color=icon_color, size=24)
                            if not icon.isNull():
                                btn.setIcon(icon)
                                btn.setIconSize(QSize(24, 24))

                # Special: ViewRibbon sharpness controls
                if name == "view":
                    _refresh_view_ribbon_styles(ribbon)

                # Special: IdentificationRibbon
                if name == "identify":
                    _refresh_identify_ribbon_styles(ribbon)

        except Exception as e:
            print(f"Failed to refresh ribbon styles: {e}")


def get_dialog_stylesheet() -> str:
    """
    Return a comprehensive theme-aware stylesheet for QDialog and its child widgets.
    Use this in all popup dialogs to ensure consistent theming.
    """
    c = ThemeColors
    primary_bg = c.get("dialog_primary_bg")
    primary_hover = c.get("dialog_primary_hover")
    primary_border = c.get("dialog_primary_border")
    primary_text = c.get("dialog_primary_text")
    selection_bg = c.get("dialog_selection")
    selection_text = c.get("text_primary") if c.is_light() else c.get("text_on_active")
    return f"""
    QDialog, QMessageBox {{
        background-color: {c.get('bg_primary')};
        color: {c.get('text_primary')};
        font-family: "SF Pro Text", "Helvetica Neue", "Segoe UI", Arial;
    }}
    QLabel {{
        color: {c.get('text_primary')};
        background: transparent;
    }}
    QLabel#dialogSectionLabel {{
        color: {c.get('text_primary')};
        font-weight: 600;
    }}
    QLabel#dialogTitle {{
        color: {c.get('text_primary')};
        font-size: 16pt;
        font-weight: 700;
    }}
    QLabel#dialogSubtitle {{
        color: {c.get('text_secondary')};
        font-size: 9.5pt;
    }}
    QLabel#dialogCaption {{
        color: {c.get('text_secondary')};
        font-size: 8.5pt;
    }}
    QLabel#dialogHintLabel {{
        color: {c.get('text_secondary')};
        font-size: 9pt;
        padding: 8px;
    }}
    QLabel#dialogInlineNote {{
        color: {c.get('text_secondary')};
        font-size: 9pt;
    }}
    QLabel#displayBorderLabel {{
        color: {c.get('text_primary')};
        font-weight: 600;
    }}
    QLabel#valuePill {{
        background-color: {c.get('bg_input')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border_light')};
        border-radius: 8px;
        padding: 5px 10px;
        font-weight: 600;
    }}
    QWidget#dialogHero, QFrame#dialogHero,
    QWidget#dialogCard, QFrame#dialogCard,
    QWidget#dialogInfoStrip, QFrame#dialogInfoStrip {{
        background-color: {c.get('bg_secondary')};
        border: 1px solid {c.get('border_light')};
        border-radius: 10px;
    }}
    QFrame#displayControlsCard, QFrame#displayTableCard {{
        background-color: {c.get('bg_secondary')};
        border: 1px solid {c.get('border_light')};
        border-radius: 12px;
    }}
    QFrame#displayBorderStrip {{
        background-color: {c.get('bg_input')};
        border: 1px solid {c.get('border_light')};
        border-radius: 10px;
    }}
    QFrame#progressHero {{
        background-color: {c.get('bg_secondary')};
        border: 1px solid {c.get('border_light')};
        border-radius: 12px;
    }}
    QWidget#dialogInfoStrip, QFrame#dialogInfoStrip {{
        background-color: {c.get('bg_input')};
    }}
    QLabel#progressStatus {{
        color: {c.get('text_secondary')};
        font-size: 9pt;
    }}
    QLabel#progressMetric {{
        color: {c.get('accent')};
        font-size: 9.5pt;
        font-weight: 700;
    }}
    QProgressBar#loadingProgressBar {{
        border: 1px solid {c.get('border_light')};
        border-radius: 11px;
        background-color: {c.get('bg_input')};
        color: {c.get('text_primary')};
        min-height: 22px;
        text-align: center;
        font-weight: 700;
    }}
    QProgressBar#loadingProgressBar::chunk {{
        border-radius: 10px;
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {primary_border},
            stop:1 {c.get('accent')}
        );
    }}
    QGroupBox {{
        border: 1px solid {c.get('border_light')};
        border-radius: 8px;
        margin-top: 12px;
        padding: 12px 10px 10px 10px;
        color: {c.get('text_primary')};
        font-weight: 700;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
    }}
    QPushButton {{
        background-color: {c.get('bg_button')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border')};
        border-radius: 8px;
        padding: 7px 16px;
        font-weight: 600;
        min-height: 32px;
        outline: none;
    }}
    QPushButton:hover {{
        background-color: {c.get('bg_button_hover')};
        border: 1px solid {primary_border};
    }}
    QPushButton:pressed {{
        background-color: {c.get('bg_button_hover')};
        color: {c.get('text_primary')};
        border: 1px solid {primary_border};
    }}
    QPushButton:focus, QToolButton:focus {{
        outline: none;
        border: 1px solid {primary_border};
    }}
    QToolButton {{
        background-color: {c.get('bg_button')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border')};
        border-radius: 8px;
        padding: 6px 10px;
        outline: none;
    }}
    QToolButton:hover {{
        background-color: {c.get('bg_button_hover')};
        border: 1px solid {primary_border};
    }}
    QToolButton:pressed {{
        background-color: {c.get('bg_button_hover')};
        border: 1px solid {primary_border};
    }}
    QPushButton#primaryBtn {{
        background-color: {primary_bg};
        color: {primary_text};
        border: 1px solid {primary_border};
    }}
    QPushButton#primaryBtn:hover {{
        background-color: {primary_hover};
        border: 1px solid {primary_border};
    }}
    QPushButton#apply_btn {{
        background-color: {primary_bg};
        color: {primary_text};
        border: 1px solid {primary_border};
    }}
    QPushButton#apply_btn:hover {{
        background-color: {primary_hover};
        border: 1px solid {primary_border};
    }}
    QPushButton#secondaryBtn {{
        background-color: {c.get('bg_secondary')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border_light')};
    }}
    QPushButton#secondaryBtn:hover {{
        background-color: {c.get('bg_button')};
        border: 1px solid {primary_border};
    }}
    QPushButton#dangerBtn {{
        background-color: {c.get('danger')};
        color: white;
        border: 1px solid {c.get('danger_dark')};
    }}
    QPushButton#dangerBtn:hover {{
        background-color: {c.get('danger_hover')};
    }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
        background-color: {c.get('bg_input')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border_light')};
        border-radius: 6px;
        padding: 4px 8px;
        outline: none;
    }}
    QLineEdit[readOnly="true"], QTextEdit[readOnly="true"], QPlainTextEdit[readOnly="true"] {{
        background-color: {c.get('bg_secondary')};
        color: {c.get('text_secondary')};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {primary_border};
    }}
    QComboBox {{
        background-color: {c.get('bg_input')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border_light')};
        border-radius: 6px;
        padding: 4px 10px;
        outline: none;
    }}
    QComboBox:hover, QComboBox:focus {{
        border: 1px solid {primary_border};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c.get('bg_secondary')};
        color: {c.get('text_primary')};
        selection-background-color: {selection_bg};
        selection-color: {selection_text};
        border: 1px solid {c.get('border')};
        outline: none;
    }}
    QMenuBar {{
        background-color: {c.get('bg_secondary')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border')};
        border-radius: 6px;
        padding: 3px 4px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 6px 10px;
        margin: 1px;
        border-radius: 4px;
    }}
    QMenuBar::item:selected {{
        background-color: {c.get('bg_button_hover')};
    }}
    QMenu {{
        background-color: {c.get('bg_secondary')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border')};
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background-color: {selection_bg};
        color: {selection_text};
    }}
    QListWidget, QTreeWidget, QTableWidget, QTableView {{
        background-color: {c.get('bg_secondary')};
        alternate-background-color: {c.get('bg_input')};
        color: {c.get('text_primary')};
        gridline-color: {c.get('border')};
        border: 1px solid {c.get('border')};
        border-radius: 6px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 6px;
        border-bottom: 1px solid {c.get('border')};
    }}
    QListWidget::item:selected,
    QTreeWidget::item:selected,
    QTableWidget::item:selected,
    QTableView::item:selected {{
        background-color: {selection_bg};
        color: {selection_text};
    }}
    QListWidget::item:hover,
    QTreeWidget::item:hover,
    QTableWidget::item:hover,
    QTableView::item:hover {{
        background-color: {c.get('bg_button_hover')};
    }}
    QHeaderView::section {{
        background-color: {c.get('bg_button')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border')};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{
        background-color: {c.get('bg_button')};
        border: 1px solid {c.get('border')};
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {c.get('border_light')};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {primary_border};
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
    }}
    QCheckBox {{
        color: {c.get('text_primary')};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 3px;
        border: 1px solid {c.get('border_light')};
        background-color: {c.get('bg_input')};
    }}
    QCheckBox::indicator:checked {{
        background-color: {primary_border};
        border: 1px solid {primary_border};
    }}
    QRadioButton {{
        color: {c.get('text_primary')};
        spacing: 8px;
        padding: 4px;
    }}
    QRadioButton::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 7px;
        border: 2px solid {c.get('border_light')};
        background-color: {c.get('bg_input')};
    }}
    QRadioButton::indicator:checked {{
        background-color: {primary_border};
        border: 2px solid {primary_border};
    }}
    QScrollArea {{
        border: 1px solid {c.get('border')};
        border-radius: 6px;
        background: {c.get('bg_primary')};
    }}
    QScrollBar:vertical {{
        width: 10px;
        background: {c.get('bg_primary')};
    }}
    QScrollBar::handle:vertical {{
        background: {c.get('border_light')};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {c.get('accent')};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        height: 10px;
        background: {c.get('bg_primary')};
    }}
    QScrollBar::handle:horizontal {{
        background: {c.get('border_light')};
        border-radius: 4px;
        min-width: 20px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {c.get('accent')};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QTabWidget::pane {{
        border: 1px solid {c.get('border')};
        border-radius: 6px;
        background: {c.get('bg_secondary')};
    }}
    QTabBar::tab {{
        background: {c.get('bg_button')};
        color: {c.get('text_secondary')};
        padding: 7px 14px;
        margin-right: 2px;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
    }}
    QTabBar::tab:selected {{
        background: {primary_bg};
        color: {primary_text};
    }}
    QTabBar::tab:hover:!selected {{
        background: {c.get('bg_button_hover')};
        color: {c.get('text_primary')};
    }}
    """


def get_progress_dialog_stylesheet() -> str:
    """Theme-aware stylesheet for QProgressDialog widgets."""
    c = ThemeColors
    primary_bg = c.get("dialog_primary_bg")
    primary_border = c.get("dialog_primary_border")
    return f"""
    QProgressDialog {{
        background: {c.get('bg_secondary')};
        color: {c.get('text_primary')};
        min-width: 430px;
        border: 1px solid {c.get('border_light')};
        border-radius: 12px;
    }}
    QLabel {{
        color: {c.get('text_primary')};
        font-size: 10pt;
        font-weight: 600;
        padding: 10px 12px 6px 12px;
    }}
    QProgressBar {{
        border: 1px solid {c.get('border_light')};
        border-radius: 10px;
        text-align: center;
        background: {c.get('bg_input')};
        color: {c.get('text_primary')};
        min-height: 20px;
        font-weight: 600;
    }}
    QProgressBar::chunk {{
        background: qlineargradient(
            x1:0, y1:0, x2:1, y2:0,
            stop:0 {primary_border},
            stop:1 {primary_bg}
        );
        border-radius: 9px;
    }}
    QPushButton {{
        background: {c.get('bg_button')};
        color: {c.get('text_primary')};
        padding: 7px 14px;
        border-radius: 6px;
        border: 1px solid {c.get('border')};
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: {c.get('bg_button_hover')};
        border-color: {primary_border};
    }}
    """


def get_title_banner_style() -> str:
    """Theme-aware style for dialog title banners."""
    c = ThemeColors
    return (
        f"font-size:15px; font-weight:700; color:{c.get('text_primary')}; "
        f"padding:4px 2px 8px 2px; background:transparent; border:none;"
    )


def get_file_item_row_style() -> str:
    """Theme-aware style for file list item widget rows."""
    c = ThemeColors
    return (
        f"QWidget{{background:{c.get('bg_secondary')}; "
        f"border:1px solid {c.get('border_light')}; border-radius:10px;}}"
        f"QWidget:hover{{background:{c.get('bg_input')}; "
        f"border:1px solid {c.get('dialog_primary_border')};}}"
    )


def get_badge_style(variant: str = "success") -> str:
    """Theme-aware badge style. Variants: 'success', 'warning', 'info'."""
    c = ThemeColors
    if variant == "success":
        return (
            f"color:{c.get('text_on_active')}; background:{c.get('success')}; "
            f"padding:3px 8px; border-radius:999px; font-size:9px; font-weight:700;"
        )
    elif variant == "warning":
        return (
            f"color:{c.get('text_on_active')}; background:{c.get('warning')}; "
            f"padding:3px 8px; border-radius:999px; font-size:9px; font-weight:700;"
        )
    else:
        return (
            f"color:{c.get('text_on_active')}; background:{c.get('accent')}; "
            f"padding:3px 8px; border-radius:999px; font-size:9px; font-weight:700;"
        )


def get_notice_banner_style(variant: str = "info") -> str:
    """Theme-aware notice/callout style for helper messages inside dialogs."""
    c = ThemeColors
    if variant == "warning":
        bg = c.get('warning_bg')
        fg = c.get('warning')
        border = c.get('warning')
    elif variant == "danger":
        bg = c.get('danger_dark') if not ThemeColors.is_light() else "#fdecea"
        fg = "#ffffff" if not ThemeColors.is_light() else c.get('danger')
        border = c.get('danger')
    elif variant == "success":
        bg = c.get('success')
        fg = c.get('text_on_active')
        border = c.get('success')
    else:
        bg = c.get('bg_input')
        fg = c.get('text_secondary')
        border = c.get('border_light')

    return (
        f"background:{bg}; color:{fg}; border:1px solid {border}; "
        f"border-radius:8px; padding:8px 10px; font-size:9px;"
    )


def get_icon_button_style(role: str = "default") -> str:
    """Theme-aware style for small round icon buttons. Roles: default, danger, settings."""
    c = ThemeColors
    if role == "danger":
        bg = c.get('danger')
        hover = c.get('danger_hover')
        border = c.get('danger_dark')
    elif role == "settings":
        bg = c.get('bg_button')
        hover = c.get('bg_button_hover')
        border = c.get('border_light')
    else:
        bg = c.get('bg_button')
        hover = c.get('bg_button_hover')
        border = c.get('border_light')
    return (
        f"QPushButton{{background:{bg}; color:{c.get('text_on_active')}; "
        f"border:1px solid {border}; border-radius:13px; font-size:13px; outline:none;}}"
        f"QPushButton:hover{{background:{hover}; border:1px solid {border};}}"
    )


def _refresh_view_ribbon_styles(ribbon):
    """Re-apply theme styles to ViewRibbon sharpness/amplifier controls."""
    try:
        if hasattr(ribbon, 'sharp_value_label'):
            ribbon.sharp_value_label.setStyleSheet("")
    except Exception:
        pass


def _refresh_identify_ribbon_styles(ribbon):
    """Re-apply theme styles to IdentificationRibbon."""
    try:
        if hasattr(ribbon, 'status_label'):
            ribbon.status_label.setStyleSheet(get_status_label_style())
        if hasattr(ribbon, 'delete_btn'):
            ribbon.delete_btn.setStyleSheet(get_delete_btn_style())
    except Exception:
        pass
