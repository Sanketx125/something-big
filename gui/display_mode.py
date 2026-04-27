
import importlib as _importlib
import sys as _sys
import os as _os

from PySide6.QtGui import QColor, QFont, QIcon, QAction, QActionGroup
from PySide6.QtCore import Qt, Signal, QSettings, QMutex, QMutexLocker
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QCheckBox, QColorDialog, QLabel, QLineEdit,
    QFileDialog, QComboBox, QWidget, QFrame, QAbstractItemView, QToolButton, QMenu
)
from gui.class_display import update_class_mode
from gui.theme_manager import get_dialog_stylesheet


# ─────────────────────────────────────────────────────────────────────────────
# unified_actor_manager import resolver
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# unified_actor_manager import resolver
# ─────────────────────────────────────────────────────────────────────────────
def _register_uam_aliases(module):
    """Keep legacy and package import paths pointing at the same module."""
    _sys.modules.setdefault('gui.unified_actor_manager', module)
    _sys.modules.setdefault('unified_actor_manager', module)
    return module
 
 
def _resolve_uam():
    for _module_name in ('gui.unified_actor_manager', 'unified_actor_manager'):
        try:
            return _register_uam_aliases(
                _importlib.import_module(_module_name)
            )
        except ModuleNotFoundError:
            pass
    _this_dir = _os.path.dirname(_os.path.abspath(__file__))
    _candidates = [
        _this_dir,
        _os.path.dirname(_this_dir),
        _os.path.join(_this_dir, '..', 'core'),
        _os.path.join(_this_dir, 'core'),
    ]
    for _path in _candidates:
        _path = _os.path.normpath(_path)
        _target = _os.path.join(_path, 'unified_actor_manager.py')
        if _os.path.exists(_target):
            if _path not in _sys.path:
                _sys.path.insert(0, _path)
            return _register_uam_aliases(
                _importlib.import_module('unified_actor_manager')
            )
    raise ModuleNotFoundError(
        "unified_actor_manager.py not found. "
        "Expected gui/unified_actor_manager.py or a legacy top-level copy."
    )
 
 
# ═══════════════════════════════════════════════════════════════════════════
# ACTUALLY RESOLVE AND CACHE THE MODULE  ← ADD THIS LINE
# ═══════════════════════════════════════════════════════════════════════════
_uam = _resolve_uam()

# --- Helper Aliases at the top of display_mode.py ---

def _uam_sync(app, slot_idx, palette=None, border=None, render=True):
    """General sync for any slot."""
    return _uam.sync_palette_to_gpu(app, slot_idx, palette, border, render)

def _uam_refresh_section(app, view_idx, palette=None, border=0.0):
    """Used for Cross-Sections (Slots 1-4)."""
    return _uam.refresh_section_after_weight_change(app, view_idx, palette, border)

def _uam_fast_refresh(app, palette=None, border=0.0):
    """Used for Main View (Slot 0)."""
    # 🚀 This must call sync_palette_to_gpu to trigger the new weight logic
    return _uam.sync_palette_to_gpu(app, 0, palette, border, True)

def _uam_connect(app):
    """Wires the palette_changed signal to the GPU sync function."""
    return _uam.connect_palette_signal(app)


# ─────────────────────────────────────────────────────────────────────────────
# restore_display_settings_for_file
# ─────────────────────────────────────────────────────────────────────────────
def restore_display_settings_for_file(app, filepath):
    """Restore display settings for a file (uses global settings for all files)."""
    try:
        from PySide6.QtCore import QSettings
        import os

        file_key = os.path.abspath(filepath)
        settings = QSettings("NakshaAI", "LidarApp")

        print("=" * 60)
        print(f"🔄 RESTORING GLOBAL DISPLAY SETTINGS FOR {os.path.basename(filepath)}")
        print("=" * 60)

        dialog = None
        if hasattr(app, 'display_mode_dialog') and app.display_mode_dialog:
            dialog = app.display_mode_dialog
        elif hasattr(app, 'display_dialog') and app.display_dialog:
            dialog = app.display_dialog

        temp_palettes = None
        temp_shows    = None

        saved_palettes = settings.value("global_view_palettes")
        if saved_palettes and isinstance(saved_palettes, dict):
            temp_palettes = {}
            for view_idx_str, palette_dict in saved_palettes.items():
                view_idx = int(view_idx_str)
                temp_palettes[view_idx] = {}
                for code_str, info in palette_dict.items():
                    code = int(code_str)
                    temp_palettes[view_idx][code] = {
                        'show':        info.get('show', True),
                        'description': info.get('description', ''),
                        'color':       tuple(info.get('color', (128, 128, 128))),
                        'weight':      info.get('weight', 1.0)
                    }
            print(f"💾 Loaded {len(temp_palettes)} GLOBAL view palettes")

        saved_shows = settings.value("global_slot_shows")
        if saved_shows and isinstance(saved_shows, dict):
            temp_shows = {}
            for slot_idx_str, show_dict in saved_shows.items():
                slot_idx = int(slot_idx_str)
                temp_shows[slot_idx] = {
                    int(code): checked
                    for code, checked in show_dict.items()
                }
            print(f"💾 Loaded {len(temp_shows)} GLOBAL checkbox states")

        saved_ptc = settings.value("global_last_ptc_path")

        if saved_ptc and os.path.exists(saved_ptc):
            print(f"📁 Loading GLOBAL PTC: {os.path.basename(saved_ptc)}")
            if dialog:
                try:
                    dialog.load_classes_from_path(saved_ptc)
                    print("✅ GLOBAL PTC loaded to dialog")
                except Exception as e:
                    print(f"⚠️ PTC load failed: {e}")
            else:
                app.pending_ptc_restore = saved_ptc
                print("💤 Stored GLOBAL PTC for later")

        if temp_palettes:
            app.class_palette = dict(temp_palettes.get(0, {}))
            app.view_visibility_filters = {}
            for view_idx, palette in temp_palettes.items():
                visible_classes = {
                    cls for cls, info in palette.items()
                    if info.get('show', True)
                }
                app.view_visibility_filters[view_idx] = visible_classes

            # ── FIX 1: push restored palettes into app.view_palettes for ALL slots ──
            # Without this, app.view_palettes[1..4] stays empty after a file clear,
            # so the cross-section actor builder falls back to class_palette and
            # ignores any per-slot visibility/weight the user had set.
            if not hasattr(app, 'view_palettes') or app.view_palettes is None:
                app.view_palettes = {}
            for _vi, _pal in temp_palettes.items():
                app.view_palettes[_vi] = {
                    code: dict(info) for code, info in _pal.items()
                }
            # ────────────────────────────────────────────────────────────────────────

            if dialog:
                dialog.view_palettes = {0: app.class_palette}

            if 0 in app.view_palettes:
                app.class_palette = dict(app.view_palettes[0])

            if dialog:
                dialog.view_palettes = dict(temp_palettes)
                if 0 in temp_palettes:
                    print(f"🔄 Syncing saved weights to display table...")
                    for row in range(dialog.table.rowCount()):
                        try:
                            code = int(dialog.table.item(row, 1).text())
                            if code in temp_palettes[0]:
                                saved_weight = temp_palettes[0][code].get('weight', 1.0)
                                weight_item  = dialog.table.item(row, 6)
                                if weight_item:
                                    weight_item.setText(f"{saved_weight:.2f}")
                        except Exception:
                            pass
                    print(f"✅ Table weights synced with saved palette")

            print(f"✅ Applied {len(temp_palettes)} GLOBAL palettes to app state")

            if temp_shows:
                app.slot_shows = temp_shows
                if dialog:
                    dialog.slot_shows = temp_shows
                    if hasattr(dialog, '_load_slot_checkboxes'):
                        try:
                            dialog._load_slot_checkboxes(dialog.current_slot)
                        except Exception:
                            pass
                else:
                    app.pending_checkbox_states = temp_shows

        if temp_shows and dialog:
            dialog.slot_shows = temp_shows
            if hasattr(dialog, '_load_slot_checkboxes'):
                try:
                    dialog._load_slot_checkboxes(dialog.current_slot)
                    print("✅ Applied GLOBAL checkbox states to UI")
                except Exception as e:
                    print(f"⚠️ Checkbox UI update failed: {e}")
        elif temp_shows:
            app.pending_checkbox_states = temp_shows
            print("💤 Stored GLOBAL checkbox states for later")

        saved_mode = settings.value("global_display_mode")
        if saved_mode:
            app.display_mode = saved_mode
            print(f"✅ Restored GLOBAL display mode: {saved_mode}")

        saved_color_mode = settings.value("global_color_mode")
        if saved_color_mode is not None and dialog:
            try:
                # dialog.color_mode.setCurrentIndex(int(saved_color_mode))
                idx_to_restore = int(saved_color_mode)
                if idx_to_restore < dialog.color_mode.count():
                    dialog.color_mode.setCurrentIndex(idx_to_restore)
                print(f"✅ Restored GLOBAL color mode: {saved_color_mode}")
            except Exception:
                pass

        saved_borders = settings.value("global_view_borders")
        if saved_borders and isinstance(saved_borders, dict):
            parsed_borders = {int(k): v for k, v in saved_borders.items()}
            if 0 in parsed_borders:
                app.point_border_percent = float(parsed_borders[0])
                is_class_mode = (app.display_mode == "class")
                app._main_view_borders_active = (app.point_border_percent > 0) and is_class_mode

            # ── FIX 2: always write app.view_borders for ALL slots ───────────────
            # The old code wrote app.view_borders only in the `else` branch (no dialog).
            # Because a dialog is always present at load time, app.view_borders was
            # never updated, so every new cross-section built after a file-open
            # received border=0.0% instead of the saved value.
            if not hasattr(app, 'view_borders') or app.view_borders is None:
                app.view_borders = {}
            app.view_borders.update(parsed_borders)
            # ────────────────────────────────────────────────────────────────────

            if dialog:
                dialog.view_borders = parsed_borders
                if hasattr(dialog, 'load_view_border'):
                    try:
                        dialog.load_view_border(dialog.current_slot)
                    except Exception:
                        pass
            # (no else needed — app.view_borders is already updated above)

            print(f"✅ Restored GLOBAL border values (Main View: {app.point_border_percent}%)")

        print("=" * 60)
        print(f"✅ GLOBAL SETTINGS APPLIED TO {os.path.basename(filepath)}")
        print("=" * 60 + "\n")

        print("\n" + "=" * 60)
        print("🔄 SYNCING WEIGHTS TO app.class_palette...")
        print("=" * 60)

        if hasattr(app, 'view_palettes') and 0 in app.view_palettes:
            main_palette = app.view_palettes[0]
            app.class_palette = {}
            for code, info in main_palette.items():
                app.class_palette[code] = {
                    'show':        info.get('show', True),
                    'description': info.get('description', ''),
                    'color':       tuple(info.get('color', (128, 128, 128))),
                    'weight':      float(info.get('weight', 1.0))
                }
                print(f"      Class {code}: weight={info.get('weight', 1.0):.1f}x")
            print(f"   ✅ Synced {len(app.class_palette)} classes from view_palettes[0]")
        else:
            print("   ⚠️ No view_palettes[0] available - skipping weight sync")

        if hasattr(app, 'data') and app.data is not None:
            print(f"\n   🔄 FORCING CLASSIFICATION REFRESH with restored weights...")
            try:
                from gui.class_display import update_class_mode
                update_class_mode(app, force_refresh=True)
                print("   ✅ Classification refresh complete - weights are now visible!")
            except Exception as e:
                print(f"   ⚠️ Classification refresh failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("   ℹ️ No data loaded yet - weights will apply when classification starts")
        print("=" * 60 + "\n")

        if hasattr(app, 'statusBar'):
            app.statusBar().showMessage(
                f"✨ Global display settings applied & refreshed", 3000
            )

        return True

    except Exception as e:
        print(f"❌ Failed to restore display settings: {e}")
        import traceback
        traceback.print_exc()
        return False


def restore_global_display_settings(app):
    """Restore global display settings that apply to ANY file."""
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("NakshaAI", "LidarApp")

        print("=" * 60)
        print(f"🌍 RESTORING GLOBAL DISPLAY SETTINGS")
        print("=" * 60)

        restored_anything = False

        dialog = None
        if hasattr(app, 'display_mode_dialog') and app.display_mode_dialog:
            dialog = app.display_mode_dialog
        elif hasattr(app, 'display_dialog') and app.display_dialog:
            dialog = app.display_dialog

        if not dialog:
            print("⚠️ No display dialog found - will restore when dialog opens")
            return False

        saved_palettes = settings.value("global_view_palettes")
        if saved_palettes and isinstance(saved_palettes, dict):
            if not hasattr(app, 'view_palettes'):
                app.view_palettes = {}
            for view_idx_str, palette_dict in saved_palettes.items():
                view_idx = int(view_idx_str)
                app.view_palettes[view_idx] = {}
                for code_str, info in palette_dict.items():
                    code = int(code_str)
                    app.view_palettes[view_idx][code] = {
                        'show':        info.get('show', True),
                        'description': info.get('description', ''),
                        'color':       tuple(info.get('color', (128, 128, 128))),
                        'weight':      info.get('weight', 1.0)
                    }
            if hasattr(dialog, 'view_palettes'):
                dialog.view_palettes = dict(app.view_palettes)
            if 0 in app.view_palettes:
                app.class_palette = dict(app.view_palettes[0])
            print(f"✅ Restored {len(saved_palettes)} GLOBAL view palettes")
            restored_anything = True

        saved_shows = settings.value("global_slot_shows")
        if saved_shows and isinstance(saved_shows, dict):
            if hasattr(dialog, 'slot_shows'):
                dialog.slot_shows = {}
                for slot_idx_str, show_dict in saved_shows.items():
                    slot_idx = int(slot_idx_str)
                    dialog.slot_shows[slot_idx] = {
                        int(code): checked
                        for code, checked in show_dict.items()
                    }
                print(f"✅ Restored GLOBAL checkbox states for {len(saved_shows)} views")
                restored_anything = True

        saved_mode = settings.value("global_display_mode")
        if saved_mode:
            app.display_mode = saved_mode
            print(f"✅ Restored GLOBAL display mode: {saved_mode}")
            restored_anything = True

        saved_color_mode = settings.value("global_color_mode")
        if saved_color_mode is not None:
            try:
                # dialog.color_mode.setCurrentIndex(int(saved_color_mode))
                idx_to_restore = int(saved_color_mode)
                if idx_to_restore < dialog.color_mode.count():
                    dialog.color_mode.setCurrentIndex(idx_to_restore)
                print(f"✅ Restored GLOBAL color mode: {saved_color_mode}")
                restored_anything = True
            except Exception:
                pass

        saved_borders = settings.value("global_view_borders")
        if saved_borders and isinstance(saved_borders, dict):
            dialog.view_borders = {int(k): v for k, v in saved_borders.items()}
            print(f"✅ Restored GLOBAL border values: {dialog.view_borders}")
            restored_anything = True

        saved_structured_border = settings.value("global_structured_border")
        saved_logic_mode = settings.value("global_border_logic_mode")
        
        if saved_logic_mode is not None:
            mode_val = int(saved_logic_mode)
            if hasattr(dialog, 'border_logic_hybrid') and hasattr(dialog, 'border_logic_object') and hasattr(dialog, 'border_logic_point'):
                if mode_val == 2:
                    dialog.border_logic_hybrid.setChecked(True)
                elif mode_val == 1:
                    dialog.border_logic_object.setChecked(True)
                else:
                    dialog.border_logic_point.setChecked(True)
            print(f"✅ Restored GLOBAL border logic mode: {mode_val}")
            restored_anything = True
        elif saved_structured_border is not None:
            is_structured = str(saved_structured_border).lower() == 'true'
            if hasattr(dialog, 'border_logic_object') and hasattr(dialog, 'border_logic_point'):
                if is_structured:
                    dialog.border_logic_object.setChecked(True)
                else:
                    dialog.border_logic_point.setChecked(True)
            print(f"✅ Restored GLOBAL structured border mode: {is_structured}")
            restored_anything = True

        if restored_anything:
            if hasattr(dialog, '_load_slot_checkboxes'):
                dialog._load_slot_checkboxes(dialog.current_slot)
            if hasattr(dialog, 'load_view_border'):
                dialog.load_view_border(dialog.current_slot)
            # Do NOT call on_apply here — restoring settings only populates
            # the dialog UI. GPU push happens only when user clicks Apply.
            print("=" * 60)
            print("✅ GLOBAL DISPLAY SETTINGS RESTORED (click Apply to apply to view)")
            print("=" * 60 + "\n")
            if hasattr(app, 'statusBar'):
                app.statusBar().showMessage(f"✨ Display settings restored — click Apply", 3000)

        return restored_anything

    except Exception as e:
        print(f"❌ Failed to restore global display settings: {e}")
        import traceback
        traceback.print_exc()
        return False


def apply_global_settings_on_dialog_open(dialog, app):
    """Apply pending global settings when Display Mode dialog is first opened."""
    if not hasattr(app, 'pending_global_restore') or not app.pending_global_restore:
        return

    print("\n" + "=" * 60)
    print("🔄 APPLYING PENDING GLOBAL SETTINGS TO NEW DIALOG")
    print("=" * 60)

    try:
        restore_global_display_settings(app)
        app.pending_global_restore = False
        print("✅ Pending global settings applied")
        print("=" * 60 + "\n")
    except Exception as e:
        print(f"⚠️ Failed to apply pending settings: {e}")
        import traceback
        traceback.print_exc()


# ─────────────────────────────────────────────────────────────────────────────
# DisplayModeDialog
# ─────────────────────────────────────────────────────────────────────────────
class DisplayModeDialog(QDialog):
    applied         = Signal(dict)
    view_switched   = Signal(int)
    classes_loaded  = Signal()
    palette_changed = Signal(int)   # emits slot_idx for GPU uniform sync

    def __init__(self, parent):
        super().__init__(parent)
        self.setProperty("themeStyledDialog", True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        from PySide6.QtCore import QSettings
        settings = QSettings("NakshaAI", "LidarApp")

        saved_palettes = settings.value("global_view_palettes")
        if saved_palettes:
            self.view_palettes = {}
            for view_idx_str, palette_dict in saved_palettes.items():
                view_idx = int(view_idx_str)
                self.view_palettes[view_idx] = {}
                for code_str, info in palette_dict.items():
                    code = int(code_str)
                    self.view_palettes[view_idx][code] = {
                        'show':        info.get('show', True),
                        'description': info.get('description', ''),
                        'color':       tuple(info.get('color', (128, 128, 128))),
                        'weight':      info.get('weight', 1.0)
                    }

        saved_shows = settings.value("global_slot_shows")
        if saved_shows:
            self.slot_shows = {}
            for slot_idx_str, show_dict in saved_shows.items():
                slot_idx = int(slot_idx_str)
                self.slot_shows[slot_idx] = {
                    int(code): checked
                    for code, checked in show_dict.items()
                }
            self.setWindowTitle("Display Mode")
            self.resize(850, 600)
            self.setMinimumSize(560, 380)
            self.current_ptc_path = None
            self.setWindowFlags(
                Qt.Window |
                Qt.WindowMinimizeButtonHint |
                Qt.WindowMaximizeButtonHint |
                Qt.WindowCloseButtonHint
            )

        # Stash border logic mode to restore after UI widgets are built
        self._pending_border_logic_mode = None
        saved_logic_mode = settings.value("global_border_logic_mode")
        if saved_logic_mode is not None:
            try:
                self._pending_border_logic_mode = int(saved_logic_mode)
            except (ValueError, TypeError):
                pass

        # Bug-8 fix: single-shot debounce timer for QSettings registry flush.
        # Fires 2 s after the last Apply/border click; harmlessly restarts on each
        # new click so rapid interactions never block the main thread.
        from PySide6.QtCore import QTimer
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_global_settings)

        main_layout = QVBoxLayout(self)

        self.setStyleSheet(get_dialog_stylesheet())

        self.file_menu = QMenu(self)
        file_menu = self.file_menu
        load_action  = file_menu.addAction("Open...")
        save_action  = file_menu.addAction("Save...")
        save_as_action = file_menu.addAction("Save As...")
        file_menu.addSeparator()
        exit_action  = file_menu.addAction("Close")
        load_action.triggered.connect(self.load_classes)
        save_action.triggered.connect(self.save_classes)
        save_as_action.triggered.connect(lambda: self.save_classes_as(update_active=False))
        exit_action.triggered.connect(self.close)

        intro = QLabel(
            "Manage view-specific class visibility, colors, weights, and point-border settings "
            "for the active scene."
        )
        intro.setObjectName("dialogInlineNote")
        intro.setWordWrap(True)
        main_layout.addWidget(intro)

        controls_card = QFrame()
        controls_card.setObjectName("displayControlsCard")
        controls_layout = QHBoxLayout(controls_card)
        controls_layout.setContentsMargins(12, 10, 12, 10)
        controls_layout.setSpacing(8)

        self.slot_box = QComboBox()
        self.slot_box.setMinimumWidth(170)
        self.slot_box.addItems([
            "Main View",
            "View 1", "View 2", "View 3", "View 4",
            "Cut Section View"
        ])
        self.slot_box.currentIndexChanged.connect(self.on_slot_changed)
        self.slot_box.currentIndexChanged.connect(self.on_view_selection_changed)
        controls_layout.addWidget(self.slot_box)

        self.color_mode = QComboBox()
        self.color_mode.setMinimumWidth(190)
        self.color_mode.addItems([
            "By Classification",      # idx 0
            "Shaded Classification",  # idx 1
            "Depth",                  # idx 2
            "Intensity",              # idx 3
            "RGB",                    # idx 4
            "Elevation",              # idx 5
        ])
        controls_layout.addWidget(self.color_mode)

        self.file_button = QToolButton()
        self.file_button.setObjectName("displayFileButton")
        self.file_button.setText("File")
        self.file_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.file_button.setPopupMode(QToolButton.InstantPopup)
        self.file_button.setMenu(self.file_menu)
        self.file_button.setFocusPolicy(Qt.NoFocus)
        self.file_button.setMinimumWidth(96)
        controls_layout.addWidget(self.file_button)

        border_container = QFrame()
        border_container.setObjectName("displayBorderStrip")
        border_container.setFixedWidth(190)
        border_layout    = QHBoxLayout(border_container)
        border_layout.setContentsMargins(8, 5, 8, 5)
        border_layout.setSpacing(5)

        self.border_label = QLabel("Border")
        self.border_label.setObjectName("displayBorderLabel")
        self.border_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        border_layout.addWidget(self.border_label)
        border_layout.addStretch(1)

        self.border_minus_btn = QPushButton("-")
        self.border_minus_btn.setObjectName("displayBorderButton")
        self.border_minus_btn.setFixedSize(22, 22)
        self.border_minus_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.border_minus_btn.setAutoDefault(False)
        self.border_minus_btn.setDefault(False)
        self.border_minus_btn.setFocusPolicy(Qt.NoFocus)
        self.border_minus_btn.clicked.connect(self.decrease_border)
        border_layout.addWidget(self.border_minus_btn)

        self.border_value_display = QLabel("0%")
        self.border_value_display.setObjectName("displayBorderValuePill")
        self.border_value_display.setFixedWidth(42)
        self.border_value_display.setFixedHeight(22)
        self.border_value_display.setAlignment(Qt.AlignCenter)
        self.border_value_display.setFont(QFont("Segoe UI", 9))
        border_layout.addWidget(self.border_value_display)

        self.border_plus_btn = QPushButton("+")
        self.border_plus_btn.setObjectName("displayBorderButton")
        self.border_plus_btn.setFixedSize(22, 22)
        self.border_plus_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.border_plus_btn.setAutoDefault(False)
        self.border_plus_btn.setDefault(False)
        self.border_plus_btn.setFocusPolicy(Qt.NoFocus)
        self.border_plus_btn.clicked.connect(self.increase_border)
        border_layout.addWidget(self.border_plus_btn)

        self.border_setting_btn = QPushButton()
        self.border_setting_btn.setObjectName("displayBorderButton")
        
        from gui.icon_provider import get_icon
        self.border_setting_btn.setIcon(get_icon("settings_gear", size=14))
        from PySide6.QtCore import QSize
        self.border_setting_btn.setIconSize(QSize(14, 14))
        self.border_setting_btn.setFixedSize(22, 22)
        self.border_setting_btn.setFocusPolicy(Qt.NoFocus)

        self.border_setting_menu = QMenu(self)
        self.border_logic_point = QAction("Per-Point", self.border_setting_menu)
        self.border_logic_point.setCheckable(True)
        self.border_logic_point.setChecked(True)
        
        self.border_logic_object = QAction("Structured", self.border_setting_menu)
        self.border_logic_object.setCheckable(True)

        self.border_logic_hybrid = QAction("Hybrid", self.border_setting_menu)
        self.border_logic_hybrid.setCheckable(True)
        
        self.border_action_group = QActionGroup(self)
        self.border_action_group.addAction(self.border_logic_point)
        self.border_action_group.addAction(self.border_logic_object)
        self.border_action_group.addAction(self.border_logic_hybrid)
        self.border_action_group.setExclusive(True)
        
        self.border_setting_menu.addAction(self.border_logic_point)
        self.border_setting_menu.addAction(self.border_logic_object)
        self.border_setting_menu.addAction(self.border_logic_hybrid)
        
        self.border_logic_point.triggered.connect(self._on_border_mode_changed)
        self.border_logic_object.triggered.connect(self._on_border_mode_changed)
        self.border_logic_hybrid.triggered.connect(self._on_border_mode_changed)
        
        # Show menu on click to avoid the auto-indicator arrow from setMenu
        self.border_setting_btn.clicked.connect(
            lambda: self.border_setting_menu.exec(
                self.border_setting_btn.mapToGlobal(
                    self.border_setting_btn.rect().bottomLeft()
                )
            )
        )
        border_layout.addWidget(self.border_setting_btn)

        controls_layout.addWidget(border_container)
        controls_layout.addStretch(1)
        main_layout.addWidget(controls_card)

        table_card = QFrame()
        table_card.setObjectName("displayTableCard")
        table_layout = QHBoxLayout(table_card)
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.setSpacing(12)
        self.table   = QTableWidget(0, 7)
        self.table.setObjectName("displayClassTable")
        self.table.setHorizontalHeaderLabels(
            ["Show", "Code", "Description", "Draw", "Lvl", "Color", "Weight"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 56)
        self.table.setColumnWidth(1, 68)
        self.table.setColumnWidth(4, 88)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 82)
        self.table.setShowGrid(False)
        table_layout.addWidget(self.table)

        action_rail = QFrame()
        action_rail.setObjectName("displayActionRail")
        side = QVBoxLayout(action_rail)
        side.setContentsMargins(10, 10, 10, 10)
        side.setSpacing(10)
        self.add_btn    = QPushButton("Add")
        self.edit_btn   = QPushButton("Edit")
        self.del_btn    = QPushButton("Delete")
        self.select_btn = QPushButton("Select All")
        self.clear_btn  = QPushButton("Clear All")
        for b in [self.add_btn, self.edit_btn, self.del_btn,
                  self.select_btn, self.clear_btn]:
            b.setObjectName("displayActionButton")
            b.setMinimumHeight(36)
            b.setMinimumWidth(100)
            b.setAutoDefault(False)
            b.setDefault(False)
            b.setFocusPolicy(Qt.NoFocus)
            side.addWidget(b)
        side.addStretch()
        table_layout.addWidget(action_rail)
        main_layout.addWidget(table_card)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primaryBtn")
        self.close_btn = QPushButton("Close")
        self.close_btn.setObjectName("secondaryBtn")
        self.apply_btn.setAutoDefault(False)
        self.apply_btn.setDefault(False)
        self.apply_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.setAutoDefault(False)
        self.close_btn.setDefault(False)
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        bottom.addWidget(self.apply_btn)
        bottom.addWidget(self.close_btn)
        main_layout.addLayout(bottom)

        self.close_btn.clicked.connect(self._handle_close)
        self.apply_btn.clicked.connect(self.on_apply)
        self.add_btn.clicked.connect(self.on_add)
        self.edit_btn.clicked.connect(self.on_edit)
        self.del_btn.clicked.connect(self.on_delete)
        self.select_btn.clicked.connect(self.on_select_all)
        self.clear_btn.clicked.connect(self.on_clear_all)

        self.current_slot      = 0
        self.slot_shows        = {i: {} for i in range(6)}
        self.view_borders      = {i: 0 for i in range(6)}
        self.point_border_percent = 0
        self.view_palettes     = {i: {} for i in range(6)}

        if parent and hasattr(parent, 'view_palettes'):
            print(f"📥 Syncing view_palettes from app to dialog...")
            for view_idx, palette in parent.view_palettes.items():
                if view_idx not in self.view_palettes:
                    self.view_palettes[view_idx] = {}
                for code, info in palette.items():
                    self.view_palettes[view_idx][code] = {
                        "show":        bool(info.get("show", True)),
                        "color":       tuple(info.get("color", (128, 128, 128))),
                        "weight":      float(info.get("weight", 1.0)),
                        "description": str(info.get("description", "")),
                        "lvl":         str(info.get("lvl", "")),
                        "draw":        info.get("draw", "")
                    }
            print(f"✅ Synced {len(parent.view_palettes)} view palettes from app")

        ptc_loaded = False
        settings   = QSettings("NakshaAI", "LidarApp")

        if parent and hasattr(parent, '_pending_ptc_restore'):
            ptc_path = parent._pending_ptc_restore
            if ptc_path and os.path.exists(ptc_path):
                print(f"\n{'=' * 60}")
                print(f"📂 RESTORING PTC FILE (Pending): {os.path.basename(ptc_path)}")
                self.load_classes_from_path(ptc_path)
                ptc_loaded = True
                del parent._pending_ptc_restore

        if not ptc_loaded and parent and hasattr(parent, 'loaded_file') and parent.loaded_file:
            if getattr(parent, '_block_ptc_autoload', False):
                print("   ⏭️ PTC auto-load blocked (shortcut in progress)")
            else:
                file_key  = os.path.abspath(parent.loaded_file)
                saved_ptc = settings.value(f"file_ptc/{file_key}")
                if saved_ptc and os.path.exists(saved_ptc):
                    print(f"📂 Auto-loading saved PTC for this file: {saved_ptc}")
                    self.load_classes_from_path(saved_ptc)
                    ptc_loaded = True

        if not ptc_loaded:
            if getattr(parent, '_block_ptc_autoload', False):
                print("   ⏭️ Global PTC auto-load blocked (shortcut in progress)")
            else:
                global_last_ptc = settings.value("global_last_ptc_path")
                if global_last_ptc and os.path.exists(global_last_ptc):
                    print(f"📂 Restoring LAST USED PTC (Global): {global_last_ptc}")
                    self.load_classes_from_path(global_last_ptc)
                    ptc_loaded = True

        if not ptc_loaded:
            print(f"\n{'=' * 60}")
            print(f"🔧 INITIALIZING DISPLAY MODE WITH DEFAULT CLASSES")
            existing_weights = {}
            if parent and hasattr(parent, 'view_palettes') and 0 in parent.view_palettes:
                for code, info in parent.view_palettes[0].items():
                    existing_weights[code] = info.get('weight', 1.0)
            print(f"   ✅ Added {self.table.rowCount()} default classes")

        default_palette_template = {}
        for row in range(self.table.rowCount()):
            code        = int(self.table.item(row, 1).text())
            desc        = self.table.item(row, 2).text()
            color       = self.table.item(row, 5).background().color().getRgb()[:3]
            weight_item = self.table.item(row, 6)
            weight      = float(weight_item.text()) if weight_item else 1.0
            chk         = self.table.cellWidget(row, 0)
            is_visible  = chk.isChecked() if chk else True
            default_palette_template[code] = {
                "show":        is_visible,
                "description": desc,
                "color":       color,
                "weight":      weight
            }

        for view_idx in range(6):
            if view_idx not in self.view_palettes:
                self.view_palettes[view_idx] = {}
            if view_idx not in self.slot_shows:
                self.slot_shows[view_idx] = {}
            for code, info in default_palette_template.items():
                if code not in self.view_palettes[view_idx]:
                    self.view_palettes[view_idx][code] = {
                        "show":        info["show"],
                        "description": str(info["description"]),
                        "lvl":         str(info.get("lvl", "")),
                        "color":       tuple(info["color"]),
                        "weight":      info.get("weight", 1.0)
                    }
                self.slot_shows[view_idx][code] = self.view_palettes[view_idx][code].get("show", info["show"])

        self._check_pending_restores()

        print(f"\n{'=' * 60}")
        print(f"🔍 VERIFYING DISPLAY MODE SETUP")
        print(f"{'=' * 60}")

        has_signal = hasattr(self, 'applied')
        print(f"   Applied signal exists: {has_signal}")
        has_button = hasattr(self, 'apply_btn') and self.apply_btn is not None
        print(f"   Apply button exists: {has_button}")

        if parent:
            has_handler = hasattr(parent, 'apply_class_map')
            print(f"   Parent has apply_class_map: {has_handler}")
            if has_handler:
                try:
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        try:
                            self.applied.disconnect(parent.apply_class_map)
                        except (TypeError, RuntimeError):
                            pass
                    self.applied.connect(parent.apply_class_map)
                    print(f"   ✅ Connected 'applied' signal to parent.apply_class_map")
                except Exception as e:
                    print(f"   ❌ Connection failed: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"   ❌ ERROR: Parent does not have apply_class_map method!")
        else:
            print(f"   ⚠️ No parent provided - signal not connected")

        print(f"{'=' * 60}\n")
        self.connect_existing_checkboxes()
        if parent:
            try:
                self.wire_palette_signal(parent)
                print("   ✅ palette_changed signal auto-wired to GPU sync")
            except Exception as _wire_err:
                print(f"   ⚠️ palette_changed wirezfailed: {_wire_err}")
        print(f"🎯 DisplayModeDialog initializatioz complete")

        # Apply stashed border logic mode now that all UI widgets exist
        if getattr(self, '_pending_border_logic_mode', None) is not None:
            mode_val = self._pending_border_logic_mode
            try:
                # Disable exclusivity briefly to avoid Qt state machine ordering issues
                self.border_action_group.setExclusive(False)
                self.border_logic_point.setChecked(mode_val == 0)
                self.border_logic_object.setChecked(mode_val == 1)
                self.border_logic_hybrid.setChecked(mode_val == 2)
                self.border_action_group.setExclusive(True)
                print(f"✅ Restored border logic mode from QSettings: {mode_val}")
            except Exception as _e:
                print(f"⚠️ Could not restore border logic mode: {_e}")
            self._pending_border_logic_mode = None

    @staticmethod
    def wire_palette_signal(app) -> bool:
        return _uam_connect(app)

    def _save_slot_state(self, slot_idx: int) -> None:
        """
        Bug-10 fix: single-pass save of checkboxes AND weights.
        Replaces the two separate _save_slot_checkboxes + _save_slot_weights
        passes that each iterated all table rows independently (2× scan → 1×).
        """
        if not hasattr(self, 'slot_shows'):
            self.slot_shows = {}
        self.slot_shows.setdefault(slot_idx, {})
        if not hasattr(self, 'view_palettes'):
            self.view_palettes = {}
        slot_pal = self.view_palettes.setdefault(slot_idx, {})

        for row in range(self.table.rowCount()):
            try:
                code_item = self.table.item(row, 1)
                if not code_item:
                    continue
                code = int(code_item.text())
                chk  = self.table.cellWidget(row, 0)
                show = chk.isChecked() if chk else True
                wt_item = self.table.item(row, 6)
                weight  = float(wt_item.text()) if wt_item else 1.0

                self.slot_shows[slot_idx][code] = show
                slot_pal.setdefault(code, {}).update({'show': show, 'weight': weight})
            except Exception:
                continue

    def _load_slot_state(self, slot_idx: int) -> None:
        """
        Bug-10 fix: single-pass load of checkboxes AND weights with table-level
        blockSignals — suppresses all stateChanged callbacks during bulk restore.

        Previously: _load_slot_checkboxes + _load_slot_weights = 2 full scans
        + per-checkbox blockSignals (still fires on_checkbox_toggled n times).
        Now: 1 scan, table-level signal block → zero spurious callbacks → O(n).
        """
        palette        = self.view_palettes.get(slot_idx, {}) if hasattr(self, 'view_palettes') else {}
        saved_shows    = self.slot_shows.get(slot_idx, {})     if hasattr(self, 'slot_shows')    else {}
        default_weight = 1.0 if slot_idx == 0 else 0.5

        # table.blockSignals suppresses ALL stateChanged during bulk setChecked —
        # eliminates the O(n²) callback storm caused by per-row blockSignals.
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                try:
                    code_item = self.table.item(row, 1)
                    if not code_item:
                        continue
                    code = int(code_item.text())
                    info = palette.get(code, {})

                    chk = self.table.cellWidget(row, 0)
                    if chk:
                        chk.setChecked(info.get('show', saved_shows.get(code, True)))

                    wt_item = self.table.item(row, 6)
                    if wt_item:
                        wt_item.setText(f"{info.get('weight', default_weight):.1f}")
                except Exception:
                    continue
        finally:
            self.table.blockSignals(False)

    # ── Backward-compat shims so existing callers don't break ─────────────
    def _load_slot_checkboxes(self, slot_idx: int) -> None:
        self._load_slot_state(slot_idx)

    def _save_slot_checkboxes(self, slot_idx: int) -> None:
        self._save_slot_state(slot_idx)

    def on_slot_changed(self, idx: int) -> None:
        # Bug-10 fix: single save + single load (was 4 separate table scans).
        # Bug-3/Signal: table.blockSignals handled inside _load_slot_state.
        self._save_slot_state(self.current_slot)   # 1 pass: checks + weights
        self.current_slot = idx
        self._load_slot_state(idx)                 # 1 pass: checks + weights, signals blocked
        self.update_border_display()
        self.load_view_border(idx)
        if idx == 5:
            self.on_view_switched_to_cut_section()

    def on_view_selection_changed(self, idx):
        self.view_switched.emit(idx)

    def add_class(self, code, desc, draw, lvl, color, show=False, weight=2.0):
        row = self.table.rowCount()
        self.table.insertRow(row)

        chk = QCheckBox()
        chk.setChecked(show)
        chk.setFocusPolicy(Qt.NoFocus)
        chk.setCursor(Qt.PointingHandCursor)
        chk.setStyleSheet(
            "QCheckBox { background: transparent; margin-left: 16px; padding: 0px; }"
        )
        # Bug-9 fix: closure captures `row` at connect time → O(1) handler,
        # no sender() search loop needed.
        chk.stateChanged.connect(
            lambda state, r=row: self._on_checkbox_toggled_fast(r, state)
        )
        self.table.setCellWidget(row, 0, chk)

        self.table.setItem(row, 1, QTableWidgetItem(str(code)))
        self.table.setItem(row, 2, QTableWidgetItem(desc))
        self.table.setItem(row, 3, QTableWidgetItem(draw))
        self.table.setItem(row, 4, QTableWidgetItem(str(lvl)))

        self._set_color_cell(row, color)

        try:
            weight_text = f"{float(weight):.2f}"
        except Exception:
            weight_text = str(weight)
        self.table.setItem(row, 6, QTableWidgetItem(weight_text))
        self._format_table_row(row)

    def _set_color_cell(self, row, color):
        qcolor = QColor(color)
        color_item = self.table.item(row, 5)
        if color_item is None:
            color_item = QTableWidgetItem()
            self.table.setItem(row, 5, color_item)
        color_item.setText("")
        color_item.setBackground(qcolor)

        border_color = qcolor.darker(145)
        swatch = QFrame()
        swatch.setFixedSize(52, 18)
        swatch.setStyleSheet(
            f"background-color: rgb({qcolor.red()}, {qcolor.green()}, {qcolor.blue()});"
            f"border: 1px solid {border_color.name()};"
            "border-radius: 5px;"
        )
        swatch.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        holder.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setAlignment(Qt.AlignCenter)
        holder_layout.addWidget(swatch)
        self.table.setCellWidget(row, 5, holder)

    def _format_table_row(self, row):
        alignments = {
            1: Qt.AlignCenter,
            4: Qt.AlignCenter,
            5: Qt.AlignCenter,
            6: Qt.AlignCenter,
        }
        for column in range(1, self.table.columnCount()):
            item = self.table.item(row, column)
            if item is None:
                continue
            item.setTextAlignment(alignments.get(column, Qt.AlignVCenter | Qt.AlignLeft))
            if column == 2 or column == 3 or column == 4:
                item.setToolTip(item.text())
            elif column == 5:
                rgb = item.background().color().getRgb()[:3]
                item.setToolTip(f"RGB: {rgb[0]}, {rgb[1]}, {rgb[2]}")

    def save_classes(self):
        if not self.current_ptc_path:
            return self.save_classes_as(update_active=True)
        self._write_ptc(self.current_ptc_path)
        print(f"💾 Saved class table to {self.current_ptc_path}")

    def save_classes_as(self, update_active=False):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Class Table As", "", "Point Class Table (*.ptc)"
        )
        if not path:
            return
        self._write_ptc(path)
        if update_active:
            self.current_ptc_path = path
            self.file_label.setText(f"Loaded: {os.path.basename(path)}")
            self.file_label.setToolTip(path)
            settings = QSettings("NakshaAI", "LidarApp")
            settings.setValue("last_ptc_path", path)

    def _write_ptc(self, path):
        with open(path, "w") as f:
            for row in range(self.table.rowCount()):
                code       = int(self.table.item(row, 1).text())
                desc       = self.table.item(row, 2).text()
                draw       = self.table.item(row, 3).text()
                lvl_item   = self.table.item(row, 4)
                lvl        = lvl_item.text() if lvl_item else ""
                color_item = self.table.item(row, 5)
                qcolor     = color_item.background().color()
                rgb        = f"{qcolor.red()},{qcolor.green()},{qcolor.blue()}"
                show       = int(self.table.cellWidget(row, 0).isChecked())
                weight_item = self.table.item(row, 6)
                weight     = self.table.item(row, 6).text() if weight_item else "2.0"
                try:
                    weight_float = max(0.5, min(float(weight), 3.0))
                    weight = f"{weight_float:.2f}"
                except Exception:
                    weight = "1.0"
                f.write(f"{code}\t{desc}\t{lvl}\n")
                f.write(f"*\t{draw}\t{code}\t{rgb}\t{show}\t{weight}\n\n")

    def load_classes(self):
        if self.current_slot != 0:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Restricted Action",
                "⚠️ <b>Cannot load PTC file in Cross-Section View!</b><br><br>"
                "Please switch to the <b>Main View</b> to load a PTC file."
            )
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Class Table", "", "Point Class Table (*.ptc)"
        )
        if not path:
            return
        self.load_classes_from_path(path)

    def load_classes_from_path(self, path):
        try:
            self.current_ptc_path = path
            self.table.setRowCount(0)

            with open(path, "r") as f:
                lines = [ln.strip() for ln in f if ln.strip()]

            class_0_found      = False
            class_0_was_hidden = False

            print(f"\n{'=' * 60}")
            print(f"📂 LOADING PTC: {os.path.basename(path)}")
            print(f"{'=' * 60}")

            for i in range(0, len(lines), 2):
                header = lines[i].split("\t")
                detail = lines[i + 1].split("\t")
                if len(header) < 2 or len(detail) < 5:
                    continue

                code   = int(header[0])
                desc   = header[1]
                lvl    = header[2] if len(header) > 2 else ""
                draw   = detail[1]
                rgb    = [int(c) for c in detail[3].split(",")]
                show   = (len(detail) > 4 and detail[4] == "1")
                weight = float(detail[5]) if len(detail) > 5 else 1.0
                color  = QColor(*rgb)

                if code == 0:
                    class_0_found      = True
                    class_0_was_hidden = not show

                self.add_class(code, desc, draw, lvl, color, show, weight)
                print(f"   Class {code:3d}: weight={weight:.1f}, show={show}")

            print(f"   ✅ All classes loaded")

            app = self.parent()
            needs_class_0_fix = False

            if app and hasattr(app, 'data') and app.data is not None:
                if 'classification' in app.data and app.data['classification'] is not None:
                    import numpy as np
                    unique_classes = np.unique(app.data['classification'])
                    if len(unique_classes) == 1 and unique_classes[0] == 0:
                        if class_0_was_hidden:
                            needs_class_0_fix = True

            if needs_class_0_fix:
                for row in range(self.table.rowCount()):
                    if int(self.table.item(row, 1).text()) == 0:
                        chk = self.table.cellWidget(row, 0)
                        if chk:
                            chk.setChecked(True)
                        color_item = self.table.item(row, 5)
                        if color_item:
                            current_color = color_item.background().color()
                            r, g, b = (current_color.red(),
                                       current_color.green(),
                                       current_color.blue())
                            if r + g + b < 30:
                                self._set_color_cell(row, QColor(200, 200, 200))
                        break

            print(f"\n{'=' * 60}")
            print(f"🔄 REBUILDING ALL VIEW PALETTES AFTER PTC LOAD")
            print(f"{'=' * 60}")

            master_palette = {}
            for row in range(self.table.rowCount()):
                code        = int(self.table.item(row, 1).text())
                desc        = self.table.item(row, 2).text()
                lvl_item    = self.table.item(row, 4)
                lvl         = lvl_item.text() if lvl_item else ""
                color       = self.table.item(row, 5).background().color().getRgb()[:3]
                weight_item = self.table.item(row, 6)
                weight      = float(weight_item.text()) if weight_item else 1.0
                chk         = self.table.cellWidget(row, 0)
                show        = chk.isChecked() if chk else False
                master_palette[code] = {
                    "show":        show,
                    "description": desc,
                    "lvl":         lvl,
                    "color":       color,
                    "weight":      weight
                }

            if not hasattr(self, 'view_palettes'):
                self.view_palettes = {}

            for view_idx in range(6):
                if view_idx not in self.view_palettes:
                    self.view_palettes[view_idx] = {}
                for code, info in master_palette.items():
                    if view_idx == 0:
                        # Slot 0 (Main View) ALWAYS takes weight from the PTC file.
                        # Never inherit stale weights from a previously-applied cross-section slot.
                        # Slots 1-5 preserve their own independently-set weights.
                        weight_to_use = float(info.get("weight", 1.0))
                    elif code in self.view_palettes[view_idx]:
                        weight_to_use = float(self.view_palettes[view_idx][code].get('weight', info.get("weight", 1.0)))
                    else:
                        weight_to_use = float(info.get("weight", 1.0))
                    self.view_palettes[view_idx][code] = {
                        "show":        bool(info["show"]),
                        "description": str(info["description"]),
                        "lvl":         str(info.get("lvl", "")),
                        "color":       tuple(info["color"]),
                        "weight":      weight_to_use
                    }

            if app and hasattr(app, 'class_palette'):
                app.class_palette = dict(master_palette)
                print(f"   ✅ Updated app.class_palette with {len(master_palette)} classes")

            print(f"{'=' * 60}\n")

            self.classes_loaded.emit()

            # Do NOT call update_class_mode here — that triggers a full GPU
            # repaint on every ribbon click / PTC load before Apply is pressed.
            # The class_picker UI update below is safe (no GPU work).

            if app and hasattr(app, 'class_picker') and app.class_picker:
                try:
                    if hasattr(app.class_picker, 'on_classes_changed'):
                        app.class_picker.on_classes_changed()
                except Exception as e:
                    print(f"⚠️ Failed to update Class Picker: {e}")

            self.current_ptc_path = path
            settings = QSettings("NakshaAI", "LidarApp")
            settings.setValue("global_last_ptc_path", path)
            settings.sync()
            print(f"✅ Loaded {self.table.rowCount()} classes from {os.path.basename(path)}")
            print(f"{'=' * 60}\n")
            self.connect_existing_checkboxes()

        except Exception as e:
            print(f"Failed to load PTC: {e}")
            import traceback
            traceback.print_exc()

    def on_add(self):
        dlg = EditClassDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.add_class(dlg.code(), dlg.desc(), dlg.draw(), dlg.lvl(), dlg.color())

    def on_edit(self):
        row = self.table.currentRow()
        if row < 0:
            return
        code   = int(self.table.item(row, 1).text())
        desc   = self.table.item(row, 2).text()
        draw   = self.table.item(row, 3).text()
        lvl    = self.table.item(row, 4).text()
        color  = self.table.item(row, 5).background().color()
        weight = self.table.item(row, 6).text() if self.table.columnCount() > 6 else "2.0"

        dlg = EditClassDialog(code, desc, color, self, draw, lvl, weight)
        if dlg.exec() == QDialog.Accepted:
            self.table.setItem(row, 1, QTableWidgetItem(str(dlg.code())))
            self.table.setItem(row, 2, QTableWidgetItem(dlg.desc()))
            self.table.setItem(row, 3, QTableWidgetItem(dlg.draw()))
            self.table.setItem(row, 4, QTableWidgetItem(dlg.lvl()))
            self._set_color_cell(row, dlg.color)
            self.table.setItem(row, 6, QTableWidgetItem(f"{float(dlg.weight()):.2f}"))
            self._format_table_row(row)

    def on_delete(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _on_color_mode_changed(self, idx):
        """
        When user switches between display modes, preserve existing checkbox states.
        The checked classes in the table determine which classes are visible for
        ALL modes (depth, intensity, rgb, elevation, classification).
        """
        # Do not auto-check or modify checkboxes — user controls visibility for all modes.
        pass

    def on_select_all(self):
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if chk:
                chk.setChecked(True)

    def on_clear_all(self):
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if chk:
                chk.setChecked(False)

    def _on_checkbox_toggled_fast(self, row: int, state: int) -> None:
        """
        Bug-9 fix: O(1) checkbox handler — row index captured at connect time.
        Replaces the O(n) sender-search loop that caused O(n²) cost during
        bulk _load_slot_checkboxes (n rows × n iterations = n² widget compares).
        GPU sync deliberately withheld until Apply — state only written to dicts.
        """
        try:
            code_item = self.table.item(row, 1)
            if code_item is None:
                return
            code       = int(code_item.text())
            is_checked = bool(state)

            if hasattr(self, 'view_palettes'):
                slot_pal = self.view_palettes.get(self.current_slot)
                if slot_pal is not None and code in slot_pal:
                    slot_pal[code]['show'] = is_checked

            if hasattr(self, 'slot_shows'):
                self.slot_shows.setdefault(self.current_slot, {})[code] = is_checked

            app = self.parent()
            if app and hasattr(app, 'view_palettes'):
                app.view_palettes.setdefault(
                    self.current_slot, {}
                ).setdefault(code, {})['show'] = is_checked

            if self.current_slot == 0 and app and hasattr(app, 'class_palette'):
                if code in app.class_palette:
                    app.class_palette[code]['show'] = is_checked

        except Exception:
            pass    # silent — checkbox flicker must not interrupt user workflow

    # Keep the old name as a shim so any external connections still resolve.
    def on_checkbox_toggled(self, state):
        sender = self.sender()
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 0) is sender:
                self._on_checkbox_toggled_fast(r, state)
                return

    def connect_existing_checkboxes(self):
        connected = 0
        for row in range(self.table.rowCount()):
            chk = self.table.cellWidget(row, 0)
            if chk:
                try:
                    chk.stateChanged.disconnect()
                except Exception:
                    pass
                chk.stateChanged.connect(self.on_checkbox_toggled)
                connected += 1
        print(f"   ✅ Connected {connected} checkboxes")

    ###########

    def on_apply(self):   
        from PySide6.QtWidgets import QMessageBox, QApplication, QAbstractItemView, QAbstractItemDelegate
        
        # Ensure any active editor in the table commits its data
        if self.table.state() == QAbstractItemView.State.EditingState:
            editor = self.table.focusWidget()
            if editor is not None:
                self.table.commitData(editor)
                self.table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)

        visible_count = sum(
            1 for row in range(self.table.rowCount())
            if (chk := self.table.cellWidget(row, 0)) and chk.isChecked()
        )
        if visible_count == 0:
            QMessageBox.warning(self, "No Classes Selected",
                                "Please select at least one class.")
            return

        idx          = self.color_mode.currentIndex()
        is_class_mode = (idx == 0)  # Only By Classification is a true class mode

        class_map = {}
        for row in range(self.table.rowCount()):
            try:
                code_item = self.table.item(row, 1)
                if not code_item:
                    continue
                code        = int(code_item.text())
                chk         = self.table.cellWidget(row, 0)
                show        = chk.isChecked() if chk else True
                weight_item = self.table.item(row, 6)
                weight      = float(weight_item.text()) if weight_item else 1.0
                desc        = self.table.item(row, 2).text()
                draw        = self.table.item(row, 3).text()
                lvl         = self.table.item(row, 4).text() if self.table.item(row, 4) else ""
                color       = self.table.item(row, 5).background().color().getRgb()[:3]
                class_map[code] = {
                    "show": show, "description": desc, "draw": draw,
                    "lvl":  lvl,  "color": color,      "weight": weight,
                }
            except Exception:
                continue

        app = self.parent()
        if not app:
            return

        if not hasattr(self, 'view_palettes'):
            self.view_palettes = {i: {} for i in range(6)}
        self.view_palettes[self.current_slot] = dict(class_map)
        self._save_slot_checkboxes(self.current_slot)

        if not hasattr(app, 'view_palettes'):
            app.view_palettes = {}
        app.view_palettes[self.current_slot] = dict(class_map)

        app.view_borders = dict(self.view_borders)

        if self.current_slot == 0:
            app.class_palette = dict(class_map)
            if is_class_mode:
                app._main_view_borders_active = (self.view_borders.get(0, 0) > 0)
                app.point_border_percent = float(self.view_borders.get(0, 0))
            else:
                app._main_view_borders_active = False
                app.point_border_percent      = 0

        # ── Track that this slot was explicitly Applied by the user ──────────
        if not hasattr(app, '_slot_weights_applied'):
            app._slot_weights_applied = set()
        app._slot_weights_applied.add(self.current_slot)

        fast_path_handled = False

        if self.current_slot == 0 and idx == 1:
            # Shaded Classification — trigger shading backend
            app.display_mode = "shaded_class"
            print("🔳 Borders DISABLED for shaded_class mode (forced to 0%)")
            print("🎨 Display mode → shaded_class")
            try:
                from gui.shading_display import (
                    update_shaded_class, has_cached_geometry
                )
                azimuth = getattr(app, 'last_shade_azimuth', 45.0)
                angle   = getattr(app, 'last_shade_angle',   45.0)
                ambient = getattr(app, 'shade_ambient',       0.25)
                new_vis = set(
                    int(c) for c, e in class_map.items() if e.get("show", True)
                )
                app._shading_visibility_override = new_vis

                # Guard: reuse cached geometry even if the shaded actor was removed.
                _xyz = (app.data.get("xyz")
                        if hasattr(app, 'data') and app.data else None)

                if _xyz is not None and has_cached_geometry(_xyz, new_vis):
                    print("   ⚡ Geometry cached — skipping rebuild")
                    update_shaded_class(app, azimuth, angle, ambient,
                                        force_rebuild=False)
                else:
                    update_shaded_class(app, azimuth, angle, ambient,
                                        force_rebuild=True)
            except Exception as _se:
                print(f"⚠️ Shading backend failed: {_se}")
            fast_path_handled = True

        elif self.current_slot == 0 and idx in (2, 3, 4, 5):
            # ── Depth / Intensity / RGB / Elevation modes ──────────────────────
            # Map combo index → internal display_mode string
            _IDX_TO_MODE = {2: "depth", 3: "intensity", 4: "rgb", 5: "elevation"}
            target_mode = _IDX_TO_MODE[idx]

            # Borders are not used in these modes
            app._main_view_borders_active = False
            app.point_border_percent = float(self.view_borders.get(0, 0))

            # Clear any shading override
            if hasattr(app, '_shading_visibility_override'):
                del app._shading_visibility_override

            _border_val = app.point_border_percent
            print(f"🟳 Border {_border_val}% preserved for {target_mode} mode (uniform only)")
            print(f"🎨 Display mode → {target_mode}")

            # Sync shader visibility LUT — respect the user's checked classes.
            # Only the checked (show=True) classes will be rendered in this mode.
            # One GPU uniform upload only, no geometry/actor change.
            try:
                from gui.unified_actor_manager import (
                    _get_unified_actor, _push_uniforms_direct
                )
                _actor = _get_unified_actor(app)
                if _actor is not None:
                    _ctx = getattr(_actor, '_naksha_shader_ctx', None)
                    if _ctx is not None:
                        _base_sz = float(getattr(_actor, '_naksha_base_point_size', 2.5))
                        _ctx.load_from_palette(class_map, _border_val, _base_sz)
                        _push_uniforms_direct(_actor, _ctx)
                        vis_count = sum(1 for v in class_map.values() if v.get('show', True))
                        print(f"⚡ Shader LUT: {vis_count}/{len(class_map)} classes visible for {target_mode}")
            except Exception as _lut_err:
                print(f"⚠️ Shader LUT reset failed: {_lut_err}")

            if hasattr(app, 'set_display_mode'):
                app.set_display_mode(target_mode)
                QApplication.processEvents()
            else:
                # Fallback: set flag and call update_pointcloud directly
                app.display_mode = target_mode
                try:
                    from gui.pointcloud_display import update_pointcloud
                    update_pointcloud(app, target_mode)
                except Exception as _me:
                    print(f"⚠️ {target_mode} mode switch failed: {_me}")

            fast_path_handled = True

        elif self.current_slot == 0 and idx == 0:
            target_mode  = "class"
            current_mode = getattr(app, 'display_mode', None)
            # Clear any shading override when switching back to class mode
            if hasattr(app, '_shading_visibility_override'):
                del app._shading_visibility_override

            border = float(self.view_borders.get(0, 0))

            if current_mode != target_mode:
                if hasattr(app, 'set_display_mode'):
                    print(f"⚡ Mode switch {current_mode} → {target_mode}")
                    app.set_display_mode(target_mode)
                    QApplication.processEvents()
                # ✅ FIX: Apply border AFTER mode switch — set_display_mode
                # rebuilds the actor with border=0 (default parameter).
                # Must re-push the user's border value to the GPU.
                if border > 0:
                    _uam_sync(app, 0, class_map, border, render=True)
                    print(f"   ✅ Border {border}% re-applied after mode switch")
                fast_path_handled = True
            else:
                refreshed = _uam_fast_refresh(app, class_map, border)
                if refreshed:
                    print(f"⚡ Main View: fast_palette_refresh (same mode, no rebuild)")
                else:
                    print("⚠️ Main View fast refresh unavailable - forcing rebuild")
                    update_class_mode(app, force_refresh=True)
                    # ✅ FIX: Apply border AFTER rebuild — update_class_mode
                    # calls build_unified_actor with border=0.
                    if border > 0:
                        _uam_sync(app, 0, class_map, border, render=True)
                        print(f"   ✅ Border {border}% applied after rebuild")
                fast_path_handled = True

        elif self.current_slot >= 1:
            if self.current_slot <= 4:
                view_idx = self.current_slot - 1
                border   = float(self.view_borders.get(self.current_slot, 0))
                ok       = _uam_refresh_section(app, view_idx, class_map, border)
                if ok:
                    fast_path_handled = True
                else:
                    print(f"⚠️ Section {view_idx + 1} fast-refresh failed — may need rebuild")
            elif self.current_slot == 5:
                if hasattr(app, 'cut_section_controller'):
                    ctrl = app.cut_section_controller
                    if hasattr(ctrl, 'apply_palette'):
                        ctrl.apply_palette(class_map)
                fast_path_handled = True

        # Bug-7 fix: emit palette_changed ONLY when the fast path did NOT already
        # push to GPU.  Unconditional emit caused a second full sync_palette_to_gpu
        # call (≈20-50 ms full rewrite) after the fast path already finished.
        if not fast_path_handled:
            self.palette_changed.emit(self.current_slot)
            payload = {
                "classes":        class_map,
                "slot":           self.current_slot,
                "target_view":    self.current_slot,
                "force_refresh":  True,
                "color_mode":     idx,
                "border_percent": (self.view_borders.get(self.current_slot, 0)
                                   if is_class_mode else 0),
            }
            self.applied.emit(payload)

        if hasattr(app, 'statusBar'):
            view_names = ["Main View", "View 1", "View 2", "View 3", "View 4", "Cut Section"]
            v_name = (view_names[self.current_slot]
                      if self.current_slot < len(view_names)
                      else f"View {self.current_slot}")
            app.statusBar().showMessage(f"Applied to {v_name}", 2000)

        # Bug-8 fix: debounce registry flush — no longer blocks Apply hot-path.
        # _save_timer fires 2 s after the last Apply click, not on every click.
        if hasattr(self, '_save_timer'):
            self._save_timer.start()

    def closeEvent(self, event):
        # On real close flush immediately; on hide just stop the timer.
        if hasattr(self, '_save_timer'):
            self._save_timer.stop()
        parent = self.parent()
        if getattr(self, "_allow_native_close", False) or getattr(parent, "_shutdown_in_progress", False):
            self.save_global_settings()      # blocking flush only on true app exit
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def reject(self):
        if hasattr(self, '_save_timer'):
            self._save_timer.stop()
        self.save_global_settings()
        self.hide()

    def show_safely(self):
        if self.windowState() & Qt.WindowMinimized:
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event):
        """Intercept minimize — hide the dialog instead of collapsing to ugly mini title-bar."""
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.WindowStateChange:
            if self.windowState() & Qt.WindowMinimized:
                event.ignore()
                self.setWindowState(Qt.WindowNoState)
                self.hide()
                return
        super().changeEvent(event)  ##

    

    def _handle_close(self):
        self.save_global_settings()
        self.hide()

    def save_global_settings(self):
        """Persist palettes, weights, show-states, borders, PTC path to QSettings."""
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings("NakshaAI", "LidarApp")

            # 1. Save current table edits into view_palettes for the active slot
            if self.current_slot not in self.view_palettes:
                self.view_palettes[self.current_slot] = {}
            for row in range(self.table.rowCount()):
                try:
                    code_item = self.table.item(row, 1)
                    if not code_item:
                        continue
                    code        = int(code_item.text())
                    chk         = self.table.cellWidget(row, 0)
                    show        = chk.isChecked() if chk else True
                    weight_item = self.table.item(row, 6)
                    weight      = float(weight_item.text()) if weight_item else 1.0
                    desc        = self.table.item(row, 2).text() if self.table.item(row, 2) else ''
                    color       = self.table.item(row, 5).background().color().getRgb()[:3] if self.table.item(row, 5) else (128, 128, 128)
                    self.view_palettes[self.current_slot][code] = {
                        'show': show, 'description': desc,
                        'color': tuple(color), 'weight': weight,
                    }
                except Exception:
                    continue

            # 2. Serialize all slot palettes (includes weights)
            palettes_to_save = {}
            for view_idx, palette in self.view_palettes.items():
                if not palette:
                    continue
                slot_dict = {}
                for code, info in palette.items():
                    slot_dict[str(code)] = {
                        'show':        bool(info.get('show', True)),
                        'description': str(info.get('description', '')),
                        'color':       list(info.get('color', (128, 128, 128))),
                        'weight':      float(info.get('weight', 1.0)),
                    }
                palettes_to_save[str(view_idx)] = slot_dict
            if palettes_to_save:
                settings.setValue("global_view_palettes", palettes_to_save)

            # 3. Save checkbox states
            self._save_slot_checkboxes(self.current_slot)
            shows_to_save = {
                str(slot): {str(code): bool(v) for code, v in show_dict.items()}
                for slot, show_dict in self.slot_shows.items()
            }
            if shows_to_save:
                settings.setValue("global_slot_shows", shows_to_save)

            # 4. Save border values
            settings.setValue("global_view_borders",
                              {str(k): v for k, v in self.view_borders.items()})

            # 5. Save PTC path
            if self.current_ptc_path and os.path.exists(self.current_ptc_path):
                settings.setValue("global_last_ptc_path", self.current_ptc_path)

            # 6. Save color mode & structured border mode
            settings.setValue("global_color_mode", self.color_mode.currentIndex())
            
            if self.border_logic_hybrid.isChecked():
                mode_val = 2
            elif self.border_logic_object.isChecked():
                mode_val = 1
            else:
                mode_val = 0
            settings.setValue("global_border_logic_mode", mode_val)
            settings.setValue("global_structured_border", str(self.border_logic_object.isChecked()))

            settings.sync()
            print(f"✅ Global display settings saved ({len(palettes_to_save)} palette slots)")
        except Exception as e:
            print(f"⚠️ save_global_settings failed: {e}")

    # def get_visible_classes_for_view(self, view_idx):
    #     try:
    #         if hasattr(self, 'view_palettes') and view_idx in self.view_palettes:
    #             palette = self.view_palettes[view_idx]
    #             return [code for code, info in palette.items() if info.get('show', True)]
    #         if view_idx == self.current_slot:
    #             return [
    #                 int(self.table.item(row, 1).text())
    #                 for row in range(self.table.rowCount())
    #                 if (chk := self.table.cellWidget(row, 0)) and chk.isChecked()
    #             ]
    #         if hasattr(self, 'slot_shows') and view_idx in self.slot_shows:
    #             return [code for code, checked in self.slot_shows[view_idx].items() if checked]
    #         return None
    #     except Exception as e:
    #         print(f"      ❌ get_visible_classes_for_view error: {e}")
    #         return None

    def get_visible_classes_for_view(self, view_idx):
        try:
            # ALWAYS prefer view_palettes — this is the GPU source of truth
            if hasattr(self, 'view_palettes') and view_idx in self.view_palettes:
                palette = self.view_palettes[view_idx]
                return [code for code, info in palette.items() if info.get('show', True)]

            # Fallback: read from live table ONLY if view_palettes not populated yet
            # (e.g. before first Apply click)
            if view_idx == self.current_slot:
                visible = []
                for row in range(self.table.rowCount()):
                    chk = self.table.cellWidget(row, 0)
                    if chk and chk.isChecked():
                        item = self.table.item(row, 1)
                        if item:
                            try:
                                code = int(item.text().strip())  # .strip() prevents whitespace bugs
                                visible.append(code)
                            except ValueError:
                                print(f"      ⚠️ Bad class code in table row {row}: '{item.text()}'")
                return visible

            if hasattr(self, 'slot_shows') and view_idx in self.slot_shows:
                return [code for code, checked in self.slot_shows[view_idx].items() if checked]

            return None

        except Exception as e:
            print(f"      ❌ get_visible_classes_for_view error: {e}")
            return None ##

    def _check_pending_restores(self):
        app = self.parent()
        if not app:
            return

        print(f"\n{'=' * 40}")
        print("📥 CHECKING PENDING RESTORES")

        if hasattr(app, '_pending_ptc_restore'):
            ptc_path = app._pending_ptc_restore
            print(f" 📄 Found pending PTC: {os.path.basename(ptc_path)}")
            if os.path.exists(ptc_path):
                self.load_classes_from_path(ptc_path)
            del app._pending_ptc_restore

        if hasattr(app, '_pending_checkbox_states'):
            saved_shows = app._pending_checkbox_states
            self.slot_shows = {}
            for slot_idx_str, show_dict in saved_shows.items():
                slot_idx = int(slot_idx_str)
                self.slot_shows[slot_idx] = {
                    int(code): checked for code, checked in show_dict.items()
                }
            self._load_slot_checkboxes(self.current_slot)
            if hasattr(self, 'view_palettes'):
                for slot_idx, shows in self.slot_shows.items():
                    if slot_idx in self.view_palettes:
                        for code, is_visible in shows.items():
                            if code in self.view_palettes[slot_idx]:
                                self.view_palettes[slot_idx][code]['show'] = is_visible
            del app._pending_checkbox_states
            print(" ✅ Checkbox states applied")

        if hasattr(app, '_pending_color_mode'):
            mode_idx = app._pending_color_mode
            self.color_mode.setCurrentIndex(mode_idx)
            del app._pending_color_mode

        if hasattr(app, 'pending_border_values'):
            border_values  = app.pending_border_values
            self.view_borders = {int(k): v for k, v in border_values.items()}
            self.load_view_border(self.current_slot)
            del app.pending_border_values

        print(f"{'=' * 40}\n")

    def _save_slot_weights(self, slot_idx: int) -> None:
        """Shim — delegates to unified _save_slot_state (Bug-10 fix)."""
        self._save_slot_state(slot_idx)

    def _load_slot_weights(self, slot_idx: int) -> None:
        """Shim — delegates to unified _load_slot_state (Bug-10 fix)."""
        self._load_slot_state(slot_idx)

    def sync_weights_to_all_views(self):
        if not hasattr(self, 'view_palettes'):
            return
        weight_map = {}
        for row in range(self.table.rowCount()):
            try:
                code        = int(self.table.item(row, 1).text())
                weight_item = self.table.item(row, 6)
                if weight_item:
                    weight_map[code] = float(weight_item.text())
            except Exception:
                continue

        for view_idx in range(1, 5):
            if view_idx not in self.view_palettes:
                continue
            for code, weight in weight_map.items():
                if code in self.view_palettes[view_idx]:
                    self.view_palettes[view_idx][code]['weight'] = weight

        app = self.parent()
        if app and hasattr(app, 'view_palettes'):
            for view_idx in range(1, 5):
                if view_idx in self.view_palettes:
                    if view_idx not in app.view_palettes:
                        app.view_palettes[view_idx] = {}
                    for code, info in self.view_palettes[view_idx].items():
                        if code not in app.view_palettes[view_idx]:
                            app.view_palettes[view_idx][code] = {}
                        app.view_palettes[view_idx][code]['weight'] = info.get('weight', 1.0)

    def increase_border(self):
        current_border = self.view_borders.get(self.current_slot, 0)
        new_border     = min(50, current_border + 5)
        self.view_borders[self.current_slot] = new_border
        self.update_border_display()
        app = self.parent()
        if app:
            if not hasattr(app, 'view_borders'):
                app.view_borders = {i: 0 for i in range(6)}
            app.view_borders[self.current_slot] = new_border
            # ✅ FIX: Immediately push border to GPU for instant feedback
            self._push_border_to_gpu(app, self.current_slot, new_border)

    def decrease_border(self):
        current_border = self.view_borders.get(self.current_slot, 0)
        new_border     = max(0, current_border - 5)
        self.view_borders[self.current_slot] = new_border
        self.update_border_display()
        app = self.parent()
        if app:
            if not hasattr(app, 'view_borders'):
                app.view_borders = {i: 0 for i in range(6)}
            app.view_borders[self.current_slot] = new_border
            # ✅ FIX: Immediately push border to GPU for instant feedback
            self._push_border_to_gpu(app, self.current_slot, new_border)

    def _push_border_to_gpu(self, app, slot_idx, border_value):
        """Immediately push border change to GPU without needing Apply click."""
        try:
            float_border = float(border_value)
            if slot_idx == 0:
                app.point_border_percent = float_border
                if hasattr(app, 'on_border_changed'):
                    app.on_border_changed(float_border)
                else:
                    _uam_sync(app, 0, border=float_border, render=True)
            else:
                _uam_sync(app, slot_idx, border=float_border, render=True)
        except Exception as e:
            print(f"⚠️ _push_border_to_gpu failed (slot={slot_idx}): {e}")

    def _on_border_mode_changed(self):
        app = self.parent()
        if app:
            current_border = self.view_borders.get(self.current_slot, 0)
            self._push_border_to_gpu(app, self.current_slot, current_border)

    def on_border_value_changed(self):
        pass
    def update_border_display(self):
        value = self.view_borders[self.current_slot]
        self.border_label.setText("Border")
        self.border_value_display.setText(f"{int(value)}%")

    def load_view_border(self, view_idx):
        if not hasattr(self, 'view_borders'):
            self.view_borders = {i: 0 for i in range(6)}
        border_value = self.view_borders.get(view_idx, 0)
        self.border_label.setText("Border")
        self.border_value_display.setText(f"{int(border_value)}%")

    def on_view_switched_to_cut_section(self):
        if self.current_slot != 5:
            return
        app = self.parent()
        if not app or not hasattr(app, 'cut_section_controller'):
            return
        ctrl = app.cut_section_controller
        if hasattr(ctrl, 'cut_palette') and ctrl.cut_palette:
            if not hasattr(self, 'view_palettes'):
                self.view_palettes = {}
            existing_palette = self.view_palettes.get(5, {})
            self.view_palettes[5] = {}
            for code, info in ctrl.cut_palette.items():
                code = int(code)
                preserved_weight = (
                    existing_palette[code]['weight']
                    if code in existing_palette and 'weight' in existing_palette[code]
                    else info.get('weight', 1.0)
                )
                self.view_palettes[5][code] = {
                    'show':        info.get('show', True),
                    'description': info.get('description', ''),
                    'color':       tuple(info.get('color', (128, 128, 128))),
                    'weight':      preserved_weight
                }
            self._load_slot_checkboxes(5)
            self._load_slot_weights(5)


# ─────────────────────────────────────────────────────────────────────────────
# EditClassDialog
# ─────────────────────────────────────────────────────────────────────────────
class EditClassDialog(QDialog):
    weight_applied = Signal(float)

    def __init__(self, code=0, desc="", color=QColor("white"), parent=None,
                 draw="Not set", lvl="", weight=2.0):
        super().__init__(parent)
        self.setProperty("themeStyledDialog", True)
        self.setWindowTitle("Edit Class")
        self.setStyleSheet(get_dialog_stylesheet())
        self.color           = color
        self.default_weight  = float(weight)
        self.current_weight  = float(weight)
        self.parent_dialog   = parent

        layout = QVBoxLayout(self)

        self.code_edit = QLineEdit(str(code))
        self.desc_edit = QLineEdit(desc)
        self.draw_edit = QLineEdit(draw)
        self.lvl_edit  = QLineEdit(str(lvl))

        self.color_btn = QPushButton("Pick Color")
        self.color_btn.clicked.connect(self.pick_color)

        weight_row = QHBoxLayout()
        self.weight_label      = QLabel("Weight:")
        self.weight_edit       = QLineEdit(f"{self.current_weight:.2f}")
        self.weight_edit.setFixedWidth(60)
        self.weight_edit.setAlignment(Qt.AlignCenter)
        self.apply_weight_btn  = QPushButton("Apply")
        self.reset_weight_btn  = QPushButton("Reset")
        self.apply_weight_btn.clicked.connect(self.apply_weight)
        self.reset_weight_btn.clicked.connect(self.reset_weight)
        weight_row.addWidget(self.weight_label)
        weight_row.addWidget(self.weight_edit)
        weight_row.addWidget(self.apply_weight_btn)
        weight_row.addWidget(self.reset_weight_btn)

        layout.addWidget(QLabel("Code:"))
        layout.addWidget(self.code_edit)
        layout.addWidget(QLabel("Description:"))
        layout.addWidget(self.desc_edit)
        layout.addWidget(QLabel("Draw:"))
        layout.addWidget(self.draw_edit)
        layout.addWidget(QLabel("Lvl:"))
        layout.addWidget(self.lvl_edit)
        layout.addWidget(QLabel("Color:"))
        layout.addWidget(self.color_btn)
        layout.addLayout(weight_row)

        row    = QHBoxLayout()
        ok     = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def pick_color(self):
        col = QColorDialog.getColor(self.color, self, "Pick Class Color")
        if col.isValid():
            self.color = col

   

    def apply_weight(self):
        """🚀 PRODUCTION FIX: Pokes GPU uniforms when weight changes"""
        try:
            # 1. Validate input
            try:
                new_weight = float(self.weight_edit.text())
            except ValueError:
                self.weight_edit.setText(f"{self.current_weight:.2f}")
                return

            # 2. Safety Clamp (0.1x to 10.0x)
            new_weight = max(0.1, min(new_weight, 10.0))
            self.current_weight = new_weight
            self.weight_edit.setText(f"{new_weight:.2f}")

            if not isinstance(self.parent_dialog, DisplayModeDialog):
                return

            # 3. Setup Context
            parent_table = self.parent_dialog.table
            code = int(self.code_edit.text())
            current_slot = self.parent_dialog.current_slot
            app = self.parent_dialog.parent()

            # 4. Update UI Table
            for row in range(parent_table.rowCount()):
                try:
                    if int(parent_table.item(row, 1).text()) == code:
                        weight_item = parent_table.item(row, 6)
                        if weight_item:
                            weight_item.setText(f"{new_weight:.2f}")
                        break
                except Exception:
                    continue

            # 5. Synchronize Palettes in Memory
            if not hasattr(self.parent_dialog, 'view_palettes'):
                self.parent_dialog.view_palettes = {i: {} for i in range(6)}
            
            if current_slot in self.parent_dialog.view_palettes:
                if code in self.parent_dialog.view_palettes[current_slot]:
                    self.parent_dialog.view_palettes[current_slot][code]['weight'] = new_weight

            if app and hasattr(app, 'view_palettes'):
                if current_slot not in app.view_palettes:
                    app.view_palettes[current_slot] = {}
                if code not in app.view_palettes[current_slot]:
                    app.view_palettes[current_slot][code] = {}
                app.view_palettes[current_slot][code]['weight'] = new_weight

            # Keep the active main-view palette in sync before emitting
            # palette_changed. Slot 0 GPU refreshes read from app.class_palette,
            # so if only view_palettes[0] changes the next sync can restore the
            # old weight and make the update appear flaky.
            if current_slot == 0 and app:
                if not hasattr(app, 'view_palettes') or app.view_palettes is None:
                    app.view_palettes = {}
                if not hasattr(app, 'class_palette') or app.class_palette is None:
                    app.class_palette = {}

                slot_palette = self.parent_dialog.view_palettes.get(current_slot, {})
                slot_entry = dict(slot_palette.get(code, {}))
                if not slot_entry:
                    slot_entry = dict(app.class_palette.get(code, {}))

                slot_entry['weight'] = new_weight
                slot_entry.setdefault('show', True)
                slot_entry.setdefault('color', (128, 128, 128))
                slot_entry.setdefault('description', '')

                app.class_palette[code] = slot_entry
                app.view_palettes[current_slot][code] = dict(slot_entry)

            # 🚀 THE CRITICAL GPU POKE:
            # We use the local helper functions defined at the top of display_mode.py
            # to bypass circular imports and talk directly to the shader.
            palette = self.parent_dialog.view_palettes.get(current_slot, {})
            
            try:
                refreshed = False
                if current_slot == 0:
                    # Main View Path
                    border = float(getattr(app, 'point_border_percent', 0.0) or 0.0)
                    refreshed = _uam_fast_refresh(app, palette, border)
                    if not refreshed and app is not None:
                        print("⚠️ Main View GPU poke unavailable - forcing rebuild")
                        update_class_mode(app, force_refresh=True)
                        refreshed = True
                else:
                    # Cross-Section Path
                    view_idx = current_slot - 1
                    border = float(self.parent_dialog.view_borders.get(current_slot, 0.0))
                    refreshed = _uam_refresh_section(app, view_idx, palette, border)

                # Mark slot as explicitly weight-applied
                if not hasattr(app, '_slot_weights_applied'):
                    app._slot_weights_applied = set()
                app._slot_weights_applied.add(current_slot)

                # Final hardware poke to force the shader to re-read the LUT
                self.parent_dialog.palette_changed.emit(current_slot)
                print(f"⚡ GPU Uniform Poke: Slot {current_slot} weights synchronized")

            except Exception as gpu_err:
                print(f"⚠️ GPU Weight Poke failed: {gpu_err}")

            # 6. UI FeedbackS
            if app and hasattr(app, 'statusBar'):
                app.statusBar().showMessage(f"✨ Weight {new_weight:.2f}x applied to Slot {current_slot}", 1500)

        except Exception as e:
            print(f"❌ critical error in apply_weight: {e}")####
        

    def _highlight_row(self, table, row):
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QColor

        original_colors = []
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item:
                original_colors.append((col, item.background()))

        highlight_color = QColor(255, 255, 0, 180)
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item and col != 5:
                item.setBackground(highlight_color)

        def restore_colors():
            for col, original_color in original_colors:
                item = table.item(row, col)
                if item:
                    item.setBackground(original_color)

        QTimer.singleShot(2000, restore_colors)

    def reset_weight(self):
        self.current_weight = self.default_weight
        self.weight_edit.setText(f"{self.default_weight:.2f}")

    def code(self):    return int(self.code_edit.text())
    def desc(self):    return self.desc_edit.text()
    def draw(self):    return self.draw_edit.text()
    def lvl(self):     return self.lvl_edit.text()
    def weight(self):  return self.current_weight()
