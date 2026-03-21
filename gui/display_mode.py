
###
import importlib as _importlib
import sys as _sys
import os as _os

from PySide6.QtGui import QColor, QFont
from PySide6.QtCore import Qt, Signal, QSettings, QMutex, QMutexLocker
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QCheckBox, QColorDialog, QLabel, QLineEdit,
    QFileDialog, QMenuBar, QComboBox, QWidget
)
from gui.class_display import update_class_mode


# ─────────────────────────────────────────────────────────────────────────────
# unified_actor_manager import resolver
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_uam():
    try:
        return _importlib.import_module('unified_actor_manager')
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
            return _importlib.import_module('unified_actor_manager')
    raise ModuleNotFoundError(
        "unified_actor_manager.py not found. "
        "Place it in the project root or the same folder as display_mode.py."
    )


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

            if dialog:
                dialog.view_borders = parsed_borders
                if hasattr(dialog, 'load_view_border'):
                    try:
                        dialog.load_view_border(dialog.current_slot)
                    except Exception:
                        pass
            else:
                app.view_borders = parsed_borders

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
            self.current_ptc_path = None
            self.setWindowFlags(
                Qt.Window |
                Qt.WindowMinimizeButtonHint |
                Qt.WindowMaximizeButtonHint |
                Qt.WindowCloseButtonHint
            )

        main_layout = QVBoxLayout(self)

        self.setStyleSheet("""
            QDialog { background-color: #0c0c0c; color: #e0e0e0; font-family: 'Segoe UI'; }
            #header_label { color: #26a69a; font-weight: bold; text-transform: uppercase; }
            #apply_btn {
                background-color: #26a69a; color: #0c0c0c;
                border-radius: 4px; font-weight: bold; padding: 6px;
            }
            #apply_btn:hover { background-color: #4db6ac; }
            QPushButton {
                background-color: #2b2b2b; border: 1px solid #444444;
                border-radius: 4px; color: white; padding: 4px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
                border: 1px solid #26a69a;
            }
            QTableWidget {
                background-color: #1a1a1a; border: 1px solid #333333;
                gridline-color: #2a2a2a; border-radius: 4px;
            }
            QCheckBox { color: #e0e0e0; spacing: 8px; }
            QCheckBox::indicator {
                width: 18px; height: 18px;
                background-color: #1a1a1a; border: 1px solid #444444; border-radius: 4px;
            }
            QCheckBox::indicator:hover { border: 1px solid #26a69a; background-color: #252525; }
            QCheckBox::indicator:checked {
                background-color: #26a69a; border: 1px solid #26a69a; image: url(none);
            }
            QCheckBox::indicator:checked:pressed { background-color: #4db6ac; }
        """)

        self.menu_bar = QMenuBar(self)
        file_menu    = self.menu_bar.addMenu("File")
        load_action  = file_menu.addAction("Open...")
        save_action  = file_menu.addAction("Save...")
        save_as_action = file_menu.addAction("Save As...")
        file_menu.addSeparator()
        exit_action  = file_menu.addAction("Close")
        load_action.triggered.connect(self.load_classes)
        save_action.triggered.connect(self.save_classes)
        save_as_action.triggered.connect(lambda: self.save_classes_as(update_active=False))
        exit_action.triggered.connect(self.close)
        main_layout.setMenuBar(self.menu_bar)

        topbar = QHBoxLayout()
        self.slot_box = QComboBox()
        self.slot_box.addItems([
            "Main View",
            "View 1", "View 2", "View 3", "View 4",
            "Cut Section View"
        ])
        self.slot_box.currentIndexChanged.connect(self.on_slot_changed)
        self.slot_box.currentIndexChanged.connect(self.on_view_selection_changed)
        topbar.addWidget(self.slot_box)

        self.color_mode = QComboBox()
        self.color_mode.addItems([
            "By Classification",
            "Shaded Classification",
        ])
        topbar.addWidget(self.color_mode)

        border_container = QWidget()
        border_layout    = QVBoxLayout(border_container)
        border_layout.setContentsMargins(8, 2, 8, 2)
        border_layout.setSpacing(2)

        self.border_label = QLabel("🔳 Border: 0%")
        self.border_label.setFont(QFont("Segoe UI", 8))
        self.border_label.setAlignment(Qt.AlignCenter)
        border_layout.addWidget(self.border_label)

        border_buttons        = QWidget()
        border_buttons_layout = QHBoxLayout(border_buttons)
        border_buttons_layout.setContentsMargins(0, 0, 0, 0)
        border_buttons_layout.setSpacing(2)

        self.border_minus_btn = QPushButton("-")
        self.border_minus_btn.setFixedSize(30, 24)
        self.border_minus_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.border_minus_btn.clicked.connect(self.decrease_border)
        border_buttons_layout.addWidget(self.border_minus_btn)

        self.border_value_display = QLabel("0%")
        self.border_value_display.setFixedWidth(50)
        self.border_value_display.setAlignment(Qt.AlignCenter)
        self.border_value_display.setFont(QFont("Segoe UI", 9))
        self.border_value_display.setStyleSheet(
            "background-color: #2b2b2b; padding: 2px; border-radius: 2px;"
        )
        border_buttons_layout.addWidget(self.border_value_display)

        self.border_plus_btn = QPushButton("+")
        self.border_plus_btn.setFixedSize(30, 24)
        self.border_plus_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.border_plus_btn.clicked.connect(self.increase_border)
        border_buttons_layout.addWidget(self.border_plus_btn)

        border_layout.addWidget(border_buttons)
        topbar.addWidget(border_container)
        main_layout.addLayout(topbar)

        table_layout = QHBoxLayout()
        self.table   = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Show", "Code", "Description", "Draw", "Lvl", "Color", "Weight"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table_layout.addWidget(self.table)

        side = QVBoxLayout()
        self.add_btn    = QPushButton("Add")
        self.edit_btn   = QPushButton("Edit")
        self.del_btn    = QPushButton("Delete")
        self.select_btn = QPushButton("Select All")
        self.clear_btn  = QPushButton("Clear All")
        for b in [self.add_btn, self.edit_btn, self.del_btn,
                  self.select_btn, self.clear_btn]:
            side.addWidget(b)
        side.addStretch()
        table_layout.addLayout(side)
        main_layout.addLayout(table_layout)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("apply_btn")
        self.close_btn = QPushButton("Close")
        bottom.addWidget(self.apply_btn)
        bottom.addWidget(self.close_btn)
        main_layout.addLayout(bottom)

        self.close_btn.clicked.connect(self.accept)
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
        print(f"🎯 DisplayModeDialog initialization complete")

    @staticmethod
    def wire_palette_signal(app) -> bool:
        return _uam_connect(app)

    def _load_slot_checkboxes(self, slot_idx):
        print(f"\n   📂 Loading checkboxes for slot {slot_idx}...")

        if slot_idx in self.view_palettes and self.view_palettes[slot_idx]:
            saved_states = {
                code: info.get('show', True)
                for code, info in self.view_palettes[slot_idx].items()
            }
        else:
            saved_states = self.slot_shows.get(slot_idx, {})

        if not saved_states:
            for row in range(self.table.rowCount()):
                chk = self.table.cellWidget(row, 0)
                if chk:
                    chk.setChecked(True)
            return

        checked_count   = 0
        unchecked_count = 0
        for row in range(self.table.rowCount()):
            try:
                code_item = self.table.item(row, 1)
                if not code_item:
                    continue
                code = int(code_item.text())
                chk  = self.table.cellWidget(row, 0)
                if chk:
                    is_checked = saved_states.get(code, True)
                    chk.blockSignals(True)
                    chk.setChecked(is_checked)
                    chk.blockSignals(False)
                    if is_checked:
                        checked_count += 1
                    else:
                        unchecked_count += 1
            except Exception as e:
                print(f"      ⚠️ Error on row {row}: {e}")
                continue

        print(f"      ✅ Loaded slot {slot_idx}: "
              f"{checked_count} checked, {unchecked_count} unchecked")

    def _save_slot_checkboxes(self, slot_idx):
        current_states = {}
        checked_count  = 0
        for row in range(self.table.rowCount()):
            code = int(self.table.item(row, 1).text())
            chk  = self.table.cellWidget(row, 0)
            if chk:
                is_checked = chk.isChecked()
                current_states[int(code)] = bool(is_checked)
                if is_checked:
                    checked_count += 1

        if not hasattr(self, 'slot_shows'):
            self.slot_shows = {}
        self.slot_shows[slot_idx] = current_states
        print(f"      ✅ Saved {checked_count} checked classes for slot {slot_idx}")

    def on_slot_changed(self, idx):
        print(f"\n{'=' * 60}")
        print(f"🔄 SWITCHING VIEWS: {self.current_slot} → {idx}")
        print(f"{'=' * 60}")

        self._save_slot_checkboxes(self.current_slot)
        self._save_slot_weights(self.current_slot)

        old_slot       = self.current_slot
        self.current_slot = idx

        self._load_slot_checkboxes(idx)
        self._load_slot_weights(idx)

        self.update_border_display()
        self.load_view_border(idx)

        if idx == 5:
            self.on_view_switched_to_cut_section()

        print(f"✅ View switch complete: Slot {idx}")
        print(f"{'=' * 60}\n")

    def on_view_selection_changed(self, idx):
        self.view_switched.emit(idx)

    def add_class(self, code, desc, draw, lvl, color, show=False, weight=2.0):
        row = self.table.rowCount()
        self.table.insertRow(row)

        chk = QCheckBox()
        chk.setChecked(show)
        chk.stateChanged.connect(self.on_checkbox_toggled)
        self.table.setCellWidget(row, 0, chk)

        self.table.setItem(row, 1, QTableWidgetItem(str(code)))
        self.table.setItem(row, 2, QTableWidgetItem(desc))
        self.table.setItem(row, 3, QTableWidgetItem(draw))
        self.table.setItem(row, 4, QTableWidgetItem(str(lvl)))

        color_item = QTableWidgetItem()
        color_item.setBackground(color)
        self.table.setItem(row, 5, color_item)

        self.table.setItem(row, 6, QTableWidgetItem(str(weight)))

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
                                color_item.setBackground(QColor(200, 200, 200))
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
                    # Preserve existing view-specific weight if already loaded/synced
                    if code in self.view_palettes[view_idx]:
                        weight_to_use = float(self.view_palettes[view_idx][code].get('weight', info.get("weight", 1.0)))
                    else:
                        # Inherit from master palette
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
            color_item = QTableWidgetItem()
            color_item.setBackground(dlg.color)
            self.table.setItem(row, 5, color_item)
            self.table.setItem(row, 6, QTableWidgetItem(str(dlg.weight())))

    def on_delete(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

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

    def on_checkbox_toggled(self, state):
        sender = self.sender()
        row    = None
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 0) == sender:
                row = r
                break
        if row is None:
            return

        try:
            code       = int(self.table.item(row, 1).text())
            is_checked = sender.isChecked()

            if hasattr(self, 'view_palettes'):
                if self.current_slot in self.view_palettes:
                    if code in self.view_palettes[self.current_slot]:
                        self.view_palettes[self.current_slot][code]['show'] = is_checked

            if hasattr(self, 'slot_shows'):
                if self.current_slot not in self.slot_shows:
                    self.slot_shows[self.current_slot] = {}
                self.slot_shows[self.current_slot][code] = is_checked

            app = self.parent()
            if app and hasattr(app, 'view_palettes'):
                if self.current_slot not in app.view_palettes:
                    app.view_palettes[self.current_slot] = {}
                if code not in app.view_palettes[self.current_slot]:
                    app.view_palettes[self.current_slot][code] = {}
                app.view_palettes[self.current_slot][code]['show'] = is_checked

            if self.current_slot == 0:
                if app and hasattr(app, 'class_palette'):
                    if code in app.class_palette:
                        app.class_palette[code]['show'] = is_checked

            # State saved. GPU sync only on Apply click — do NOT emit here.

        except Exception as e:
            print(f"⚠️ Checkbox toggle error: {e}")
            import traceback
            traceback.print_exc()

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
        from PySide6.QtWidgets import QMessageBox, QApplication

        visible_count = sum(
            1 for row in range(self.table.rowCount())
            if (chk := self.table.cellWidget(row, 0)) and chk.isChecked()
        )
        if visible_count == 0:
            QMessageBox.warning(self, "No Classes Selected",
                                "Please select at least one class.")
            return

        idx          = self.color_mode.currentIndex()
        is_class_mode = (idx == 0)

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

        if self.current_slot == 0:
            app.class_palette = dict(class_map)
            app.view_borders  = self.view_borders
            if is_class_mode:
                app._main_view_borders_active = (self.view_borders.get(0, 0) > 0)
                app.point_border_percent = float(self.view_borders.get(0, 0))
            else:
                app._main_view_borders_active = False
                app.point_border_percent      = 0

        # ── Track that this slot was explicitly Applied by the user ──────────
        # _get_slot_palette uses this to decide whether to trust the weight
        # stored in view_palettes[slot] vs reset to 1.0 (base).
        if not hasattr(app, '_slot_weights_applied'):
            app._slot_weights_applied = set()
        app._slot_weights_applied.add(self.current_slot)

        # palette_changed emit moved to AFTER GPU push below —
        # emitting here caused sync_palette_to_gpu to fire with border=0
        # before app.point_border_percent was set, wiping the border value.

        fast_path_handled = False

        # if self.current_slot == 0 and idx in [0, 1]:
        #     target_mode  = "class" if idx == 0 else "rgb"
        #     current_mode = getattr(app, 'display_mode', None)

        #     if current_mode != target_mode:
        #         if hasattr(app, 'set_display_mode'):
        #             print(f"⚡ Mode switch {current_mode} → {target_mode}")
        #             app.set_display_mode(target_mode)
        #             QApplication.processEvents()
        #     else:
        #         border = float(self.view_borders.get(0, 0)) if is_class_mode else 0.0
        #         _uam_fast_refresh(app, class_map, border)
        #         print(f"⚡ Main View: fast_palette_refresh (same mode, no rebuild)")
        #         fast_path_handled = True

        if self.current_slot == 0 and idx == 1:
            # Shaded Classification — trigger shading backend
            app.display_mode = "shaded_class"
            print("🔳 Borders DISABLED for shaded_class mode (forced to 0%)")
            print("🎨 Display mode → shaded_class")
            try:
                from gui.shading_display import update_shaded_class, clear_shading_cache
                azimuth = getattr(app, 'last_shade_azimuth', 45.0)
                angle   = getattr(app, 'last_shade_angle',   45.0)
                ambient = getattr(app, 'shade_ambient',       0.25)
                app._shading_visibility_override = set(
                    int(c) for c, e in class_map.items() if e.get("show", True)
                )
                clear_shading_cache("display mode shading applied")
                update_shaded_class(app, azimuth, angle, ambient, force_rebuild=True)
            except Exception as _se:
                print(f"⚠️ Shading backend failed: {_se}")
            fast_path_handled = True

        elif self.current_slot == 0 and idx == 0:
            target_mode  = "class"
            current_mode = getattr(app, 'display_mode', None)
            # Clear any shading override when switching back to class mode
            if hasattr(app, '_shading_visibility_override'):
                del app._shading_visibility_override

            if current_mode != target_mode:
                if hasattr(app, 'set_display_mode'):
                    print(f"⚡ Mode switch {current_mode} → {target_mode}")
                    app.set_display_mode(target_mode)
                    QApplication.processEvents()
            else:
                border = float(self.view_borders.get(0, 0))
                _uam_fast_refresh(app, class_map, border)
                print(f"⚡ Main View: fast_palette_refresh (same mode, no rebuild)")
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

        # Emit AFTER GPU push so palette_changed signal sees correct border value
        self.palette_changed.emit(self.current_slot)

        if not fast_path_handled:
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
        else:
            print(f"⚡ Slot {self.current_slot}: skipping applied.emit (fast path handled)")

        if hasattr(app, 'statusBar'):
            view_names = ["Main View", "View 1", "View 2", "View 3", "View 4", "Cut Section"]
            v_name = (view_names[self.current_slot]
                    if self.current_slot < len(view_names)
                    else f"View {self.current_slot}")
            app.statusBar().showMessage(f"✅ Applied to {v_name}", 2000)  ###

    def closeEvent(self, event):
        super().closeEvent(event)

    def _handle_close(self):
        self.close()

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

    def _save_slot_weights(self, slot_idx):
        if not hasattr(self, 'view_palettes'):
            return
        if slot_idx not in self.view_palettes:
            return
        for row in range(self.table.rowCount()):
            try:
                code        = int(self.table.item(row, 1).text())
                weight_item = self.table.item(row, 6)
                if weight_item and code in self.view_palettes[slot_idx]:
                    self.view_palettes[slot_idx][code]['weight'] = float(weight_item.text())
            except Exception:
                continue

    def _load_slot_weights(self, slot_idx):
        if not hasattr(self, 'view_palettes'):
            return
        if slot_idx not in self.view_palettes:
            return
        palette        = self.view_palettes[slot_idx]
        default_weight = 1.0 if slot_idx == 0 else 0.5
        for row in range(self.table.rowCount()):
            try:
                code        = int(self.table.item(row, 1).text())
                weight_item = self.table.item(row, 6)
                if weight_item and code in palette:
                    saved_weight = palette[code].get('weight', default_weight)
                    weight_item.setText(f"{saved_weight:.1f}")
            except Exception:
                continue

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

    def on_border_value_changed(self):
        pass

    def update_border_display(self):
        value = self.view_borders[self.current_slot]
        self.border_label.setText(f"🔳 Border: {value}%")
        self.border_value_display.setText(f"{value}%")

    def load_view_border(self, view_idx):
        if not hasattr(self, 'view_borders'):
            self.view_borders = {i: 0 for i in range(6)}
        border_value = self.view_borders.get(view_idx, 0)
        self.border_label.setText(f"🔳 Border: {border_value}%")
        self.border_value_display.setText(f"{border_value}%")

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
        self.setWindowTitle("Edit Class")
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

            # 🚀 THE CRITICAL GPU POKE:
            # We use the local helper functions defined at the top of display_mode.py
            # to bypass circular imports and talk directly to the shader.
            palette = self.parent_dialog.view_palettes.get(current_slot, {})
            
            try:
                if current_slot == 0:
                    # Main View Path
                    border = float(getattr(app, 'point_border_percent', 0.0) or 0.0)
                    _uam_fast_refresh(app, palette, border)
                else:
                    # Cross-Section Path
                    view_idx = current_slot - 1
                    border = float(self.parent_dialog.view_borders.get(current_slot, 0.0))
                    _uam_refresh_section(app, view_idx, palette, border)

                # Final hardware poke to force the shader to re-read the LUT
                # Mark slot as explicitly weight-applied
                if not hasattr(app, '_slot_weights_applied'):
                    app._slot_weights_applied = set()
                app._slot_weights_applied.add(current_slot)

                self.parent_dialog.palette_changed.emit(current_slot)
                print(f"⚡ GPU Uniform Poke: Slot {current_slot} weights synchronized")

            except Exception as gpu_err:
                print(f"⚠️ GPU Weight Poke failed: {gpu_err}")

            # 6. UI Feedback
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
    def weight(self):  return self.current_weight