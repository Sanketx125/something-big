"""
gui/theme_manager.py
─────────────────────
Centralized theme manager for NakshaAI-Lidar.
Supports Dark and Light themes with runtime switching.
Inspired by the Ring app's dual-theme system (themes.py).
"""

import os
from PySide6.QtCore import QSettings


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

        # Accent
        "accent":           "#007acc",
        "accent_hover":     "#0098ff",
        "accent_alt":       "#ffaa00",

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
        "ribbon_bg":        "#1a1a1a",
        "ribbon_section":   "#202020",
        "ribbon_button":    "#2c2c2c",
        "ribbon_btn_hover": "#3c3c3c",
        "ribbon_title":     "#888888",

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
        "text_on_active":   "#ffffff",

        # Accent
        "accent":           "#0077b6",
        "accent_hover":     "#00b4d8",
        "accent_alt":       "#0096c7",

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
        "ribbon_bg":        "#ffffff",
        "ribbon_section":   "#ffffff",
        "ribbon_button":    "#eef0f4",
        "ribbon_btn_hover": "#e0e8f0",
        "ribbon_title":     "#666666",

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
        background-color: {c.get('bg_active')};
        color: {c.get('text_on_active')};
        font-weight: bold;
        border: 1px solid {c.get('bg_active_border')};
        border-radius: 6px;
    }}
    """


def get_inactive_button_style() -> str:
    """Return inline style for an INACTIVE ribbon button."""
    c = ThemeColors
    return f"""
    QPushButton {{
        background-color: {c.get('ribbon_button')};
        color: {c.get('text_primary')};
        border-radius: 6px;
    }}
    QPushButton:hover {{
        background-color: {c.get('ribbon_btn_hover')};
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


# ═══════════════════════════════════════════════════════════════════════════
#  THEME MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class ThemeManager:
    """Manages loading and switching themes."""

    _current_theme = "dark"

    @classmethod
    def apply_theme(cls, app_window, theme_name: str = "dark"):
        """Apply a theme to the main application window."""
        theme_name = theme_name.lower()
        cls._current_theme = theme_name
        ThemeColors.set_theme(theme_name)

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
    def _refresh_ribbon_styles(cls, app_window):
        """Re-apply theme-aware inline styles and icon colors on ribbon sections & buttons."""
        try:
            if not hasattr(app_window, 'ribbon_manager'):
                return

            from gui.menu_sidebar_system import RibbonSection
            from gui.icon_provider import get_button_icon
            from PySide6.QtWidgets import QPushButton
            from PySide6.QtCore import QSize

            icon_color = ThemeColors.get("text_primary")

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
                                                   color=icon_color, size=28)
                            if not icon.isNull():
                                btn.setIcon(icon)
                                btn.setIconSize(QSize(28, 28))

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
    return f"""
    QDialog {{
        background-color: {c.get('bg_primary')};
        color: {c.get('text_primary')};
        font-family: "Segoe UI", Arial;
    }}
    QLabel {{
        color: {c.get('text_primary')};
        background: transparent;
    }}
    QGroupBox {{
        border: 1px solid {c.get('border_light')};
        border-radius: 5px;
        margin-top: 10px;
        padding-top: 10px;
        color: {c.get('text_primary')};
        font-weight: bold;
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
        border-radius: 4px;
        padding: 6px 16px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: {c.get('bg_button_hover')};
        border: 1px solid {c.get('accent')};
    }}
    QPushButton:pressed {{
        background-color: {c.get('accent')};
        color: {c.get('text_on_active')};
    }}
    QPushButton#primaryBtn {{
        background-color: {c.get('accent')};
        color: {c.get('text_on_active')};
        border: 1px solid {c.get('accent')};
    }}
    QPushButton#primaryBtn:hover {{
        background-color: {c.get('accent_hover')};
    }}
    QPushButton#dangerBtn {{
        background-color: {c.get('danger')};
        color: white;
        border: 1px solid {c.get('danger_dark')};
    }}
    QPushButton#dangerBtn:hover {{
        background-color: {c.get('danger_hover')};
    }}
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {c.get('bg_input')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border_light')};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {c.get('accent')};
    }}
    QComboBox {{
        background-color: {c.get('bg_input')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border_light')};
        border-radius: 4px;
        padding: 4px 8px;
    }}
    QComboBox:hover {{
        border: 1px solid {c.get('accent')};
    }}
    QComboBox QAbstractItemView {{
        background-color: {c.get('bg_secondary')};
        color: {c.get('text_primary')};
        selection-background-color: {c.get('accent')};
        selection-color: {c.get('text_on_active')};
        border: 1px solid {c.get('border')};
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {c.get('border_light')};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {c.get('accent')};
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
        background-color: {c.get('accent')};
        border: 1px solid {c.get('accent')};
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
        background-color: {c.get('accent')};
        border: 2px solid {c.get('accent')};
    }}
    QListWidget {{
        background-color: {c.get('bg_secondary')};
        color: {c.get('text_primary')};
        border: 1px solid {c.get('border')};
        border-radius: 4px;
    }}
    QListWidget::item {{
        padding: 6px;
        border-bottom: 1px solid {c.get('border')};
    }}
    QListWidget::item:selected {{
        background-color: {c.get('accent')};
        color: {c.get('text_on_active')};
    }}
    QListWidget::item:hover {{
        background-color: {c.get('bg_button_hover')};
    }}
    QScrollArea {{
        border: 1px solid {c.get('border')};
        border-radius: 4px;
        background: {c.get('bg_primary')};
    }}
    QScrollBar:vertical {{
        width: 8px;
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
    """


def get_progress_dialog_stylesheet() -> str:
    """Theme-aware stylesheet for QProgressDialog widgets."""
    c = ThemeColors
    return f"""
    QProgressDialog {{
        background: {c.get('bg_primary')};
        color: {c.get('text_primary')};
        min-width: 400px;
    }}
    QLabel {{
        color: {c.get('accent')};
        font-size: 11pt;
        padding: 10px;
    }}
    QProgressBar {{
        border: 2px solid {c.get('border')};
        border-radius: 5px;
        text-align: center;
        background: {c.get('bg_input')};
        color: {c.get('text_primary')};
        min-height: 24px;
    }}
    QProgressBar::chunk {{
        background: {c.get('accent')};
        border-radius: 3px;
    }}
    QPushButton {{
        background: {c.get('bg_button')};
        color: {c.get('text_primary')};
        padding: 7px 14px;
        border-radius: 4px;
        border: 1px solid {c.get('border')};
    }}
    QPushButton:hover {{
        background: {c.get('bg_button_hover')};
        border-color: {c.get('accent')};
    }}
    """


def get_title_banner_style() -> str:
    """Theme-aware style for dialog title banners."""
    c = ThemeColors
    return (
        f"font-size:16px; font-weight:bold; color:{c.get('text_on_active')}; "
        f"padding:10px; background:{c.get('accent')}; border-radius:6px;"
    )


def get_file_item_row_style() -> str:
    """Theme-aware style for file list item widget rows."""
    c = ThemeColors
    return (
        f"QWidget{{background:{c.get('bg_input')}; "
        f"border:1px solid {c.get('border')}; border-radius:4px;}}"
    )


def get_badge_style(variant: str = "success") -> str:
    """Theme-aware badge style. Variants: 'success', 'warning', 'info'."""
    c = ThemeColors
    if variant == "success":
        return (
            f"color:{c.get('text_on_active')}; background:{c.get('success')}; "
            f"padding:2px 6px; border-radius:3px; font-size:9px; font-weight:bold;"
        )
    elif variant == "warning":
        return (
            f"color:{c.get('text_on_active')}; background:{c.get('warning')}; "
            f"padding:2px 6px; border-radius:3px; font-size:9px; font-weight:bold;"
        )
    else:
        return (
            f"color:{c.get('text_on_active')}; background:{c.get('accent')}; "
            f"padding:2px 6px; border-radius:3px; font-size:9px; font-weight:bold;"
        )


def get_icon_button_style(role: str = "default") -> str:
    """Theme-aware style for small round icon buttons. Roles: default, danger, settings."""
    c = ThemeColors
    if role == "danger":
        bg = c.get('danger')
        hover = c.get('danger_hover')
    elif role == "settings":
        bg = c.get('bg_button')
        hover = c.get('bg_button_hover')
    else:
        bg = c.get('bg_button')
        hover = c.get('accent')
    return (
        f"QPushButton{{background:{bg}; color:{c.get('text_on_active')}; "
        f"border:none; border-radius:13px; font-size:13px;}}"
        f"QPushButton:hover{{background:{hover};}}"
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
