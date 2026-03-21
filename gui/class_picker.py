

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, 
                               QHBoxLayout, QListWidget, QListWidgetItem)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QIcon, QColor, QPainter, QBrush, QPen, QLinearGradient
from PySide6.QtGui import QPixmap, QIcon, QColor
import os

def make_color_icon(rgb):
    """Creates a high-fidelity color pill icon with a subtle glow."""
    pix = QPixmap(32, 32)
    pix.fill(Qt.transparent)
    
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    
    color = QColor(*rgb)
    
    # Draw subtle shadow
    painter.setBrush(QBrush(QColor(0, 0, 0, 60)))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, 24, 24)
    
    # Draw main color circle with a slight gradient for depth
    grad = QLinearGradient(0, 0, 0, 32)
    grad.setColorAt(0, color.lighter(115))
    grad.setColorAt(1, color.darker(115))
    
    painter.setBrush(QBrush(grad))
    # Subtle white border to make colors pop against dark UI
    painter.setPen(QPen(QColor(255, 255, 255, 50), 1.5))
    painter.drawEllipse(2, 2, 24, 24)
    
    painter.end()
    return QIcon(pix)

class ClassPicker(QWidget):
    """
    Persistent floating Class Picker window for classification tools.
    ✅ FIXED: "To class" selection persists across file loads
    """
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        
        # ✅ CRITICAL: Save initial app state BEFORE any UI is built
        self._saved_to_class = getattr(app, 'to_class', None)
        self._saved_from_classes = getattr(app, 'from_classes', None)
        print(f"📌 ClassPicker init - saved to_class: {self._saved_to_class}, from_classes: {self._saved_from_classes}")
 
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowMinimizeButtonHint |
            Qt.WindowCloseButtonHint
        )
        self.setWindowModality(Qt.NonModal)
        
        # Set window icon
        try:
            logo_path = os.path.join(os.path.dirname(__file__), "icons", "logo.png")
            if os.path.exists(logo_path):
                icon = QIcon(logo_path)
                from PySide6.QtCore import QSize
                for size in [16, 20, 24, 32, 48]:
                    icon.addFile(logo_path, QSize(size, size))
                self.setWindowIcon(icon)
                from PySide6.QtWidgets import QApplication
                QApplication.instance().setWindowIcon(icon)
        except Exception as e:
            print(f"⚠️ Failed to set window icon: {e}")

        self._update_title()

        layout = QVBoxLayout()
        
        # --- From class (multi-select)
        layout.addWidget(QLabel("From class (Ctrl+Click for multiple):"))
        self.from_list = QListWidget()
        self.from_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.from_list.setMaximumHeight(150)
        
        # Add "Any class" option
        any_item = QListWidgetItem("Any class")
        any_item.setData(Qt.UserRole, None)
        self.from_list.addItem(any_item)
        
        # Populate from classes
        for code, entry in sorted(app.class_palette.items()):
            desc = entry.get("description", "")
            lvl = entry.get("lvl", "")
            color = entry.get("color", (128, 128, 128))
            text = f"{code} - {lvl}"
            if desc:
                text += f" ({desc})"
            item = QListWidgetItem(make_color_icon(color), text)
            item.setData(Qt.UserRole, code)
            self.from_list.addItem(item)
        
        layout.addWidget(self.from_list)

        # --- To class dropdown (single selection)
        layout.addWidget(QLabel("To class:"))
        self.to_combo = QComboBox()

        for code, entry in app.class_palette.items():
            desc = entry.get("description", "")
            lvl = entry.get("lvl", "")
            color = entry.get("color", (128, 128, 128))
            text = f"{code} - {lvl}"
            if desc:
                text += f" ({desc})"
            self.to_combo.addItem(make_color_icon(color), text, code)
        layout.addWidget(self.to_combo)

        # --- Invert button
        btn_row = QHBoxLayout()
        invert_btn = QPushButton("Invert")
        btn_row.addWidget(invert_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)

        # ✅ BLOCK signals during initial setup to prevent unwanted resets
        self.from_list.blockSignals(True)
        self.to_combo.blockSignals(True)

        # Connect to Display Mode
        display_dialog = getattr(app, 'display_mode_dialog', getattr(app, 'display_dialog', None))
        if display_dialog:
            try:
                display_dialog.classes_loaded.connect(self.on_classes_changed)
                print("✅ ClassPicker connected to display_mode_dialog.classes_loaded")
            except Exception as e:
                print(f"⚠️ Could not connect to display_dialog: {e}")
        
        # Populate dropdowns (this will preserve saved selections)
        self.populate_dropdowns()

        # ✅ UNBLOCK signals after setup
        self.from_list.blockSignals(False)
        self.to_combo.blockSignals(False)

        # Connect signals AFTER initial population
        self.from_list.itemSelectionChanged.connect(self._on_from_changed)
        self.to_combo.currentIndexChanged.connect(self._on_to_changed)
        invert_btn.clicked.connect(self._invert_classes)

        # Default size
        self.setGeometry(200, 200, 320, 280)
        self.setStyleSheet("""
            QWidget {
                background-color: #0d0d0d;
                color: #e0e0e0;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            
            QLabel#sectionLabel {
                color: #666666;
                font-size: 10px;
                font-weight: 800;
                letter-spacing: 1.5px;
                margin-bottom: -4px;
            }

            QListWidget {
                background-color: #141414;
                border: 1px solid #252525;
                border-radius: 10px;
                padding: 5px;
                outline: none;
            }
            
            QListWidget::item {
                background-color: #1a1a1a;
                border-radius: 6px;
                padding: 10px;
                margin: 2px 4px;
                border: 1px solid transparent;
            }
            
            QListWidget::item:hover {
                background-color: #222222;
                border: 1px solid #333333;
            }

            QListWidget::item:selected {
                background-color: #004d40;
                color: #00ffa2;
                border: 1px solid #00796b;
            }

            QComboBox {
                background-color: #141414;
                border: 1px solid #252525;
                border-radius: 8px;
                padding: 10px 15px;
                min-height: 20px;
            }
            
            QComboBox:hover {
                border-color: #444444;
            }

            QComboBox::drop-down {
                border: none;
                width: 30px;
            }

            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #666666;
            }

            QComboBox QAbstractItemView {
                background-color: #141414;
                border: 1px solid #252525;
                selection-background-color: #004d40;
                selection-color: #00ffa2;
                outline: none;
                border-radius: 8px;
            }

            QPushButton {
                background-color: #1a1a1a;
                border: 1px solid #2a2a2a;
                border-radius: 8px;
                color: #ffffff;
                padding: 12px;
                font-weight: 700;
                font-size: 11px;
                letter-spacing: 1px;
            }

            QPushButton:hover {
                background-color: #00aa88;
                border-color: #00ffa2;
                color: #000000;
            }

            QPushButton:pressed {
                background-color: #008866;
                transform: translateY(1px);
            }
            
            QScrollBar:vertical {
                border: none;
                background: #0d0d0d;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #2a2a2a;
                min-height: 30px;
                border-radius: 5px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: #3a3a3a;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
    def _create_logo_header(self, logo_path):
        """Create a header widget with logo and title."""
        if not os.path.exists(logo_path):
            return None
        
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(5, 5, 5, 5)
        
        logo_label = QLabel()
        pixmap = QPixmap(logo_path)
        scaled_pixmap = pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        logo_label.setPixmap(scaled_pixmap)
        
        self.header_title_label = QLabel("Class Picker")
        self.header_title_label.setStyleSheet("font-weight: bold; font-size: 11pt;")
        
        header_layout.addWidget(logo_label)
        header_layout.addWidget(self.header_title_label)
        header_layout.addStretch()
        
        header.setStyleSheet("""
            QWidget {
                background-color: #2a2a2a;
                border-bottom: 1px solid #404040;
            }
        """)
        
        return header

    def showEvent(self, event):
        super().showEvent(event)
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def ensure_visible(self):
        """Force the ClassPicker to be visible and active."""
        print(f"🔄 Ensuring ClassPicker is visible...")
        if self.isMinimized():
            self.showNormal()
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def _update_title(self):
        """Update the window title to show the current tool."""
        tool = getattr(self.app, "active_classify_tool", None)
        title = f"Tool: {tool}" if tool else "Tool: None"
        self.setWindowTitle(title)
        if hasattr(self, 'header_title_label'):
            self.header_title_label.setText(title)

    def _on_from_changed(self):
        """Called when From class selection changes."""
        selected_items = self.from_list.selectedItems()
        
        if not selected_items:
            self.app.from_classes = None
            print(f"👉 From class cleared")
            return
        
        any_selected = any(item.data(Qt.UserRole) is None for item in selected_items)
        
        if any_selected:
            self.app.from_classes = None
            print(f"👉 From class: Any class")
        else:
            selected_codes = [item.data(Qt.UserRole) for item in selected_items]
            self.app.from_classes = selected_codes
            print(f"👉 From classes: {selected_codes}")

    def _on_to_changed(self, idx):
        """Called when To class dropdown changes."""
        new_to_class = self.to_combo.currentData()
        self.app.to_class = new_to_class
        
        # ✅ CRITICAL: Also update saved value for persistence
        self._saved_to_class = new_to_class
        
        print(f"👉 To class changed to {new_to_class}")

    def _invert_classes(self):
        print("🔄 Invert triggered")
 
        old_from = []
        for i in range(self.from_list.count()):
            item = self.from_list.item(i)
            if item.isSelected():
                val = item.data(Qt.UserRole)
                if val is not None:
                    old_from.append(val)
 
        old_to = self.to_combo.currentData()
 
        self.from_list.blockSignals(True)
        self.to_combo.blockSignals(True)
 
        if not old_from:
            for i in range(self.from_list.count()):
                item = self.from_list.item(i)
                item.setSelected(item.data(Qt.UserRole) == old_to)
            if self.to_combo.count() > 0:
                self.to_combo.setCurrentIndex(0)
        else:
            first_from = old_from[0]
            for i in range(self.from_list.count()):
                item = self.from_list.item(i)
                item.setSelected(False)
            for i in range(self.from_list.count()):
                item = self.from_list.item(i)
                if item.data(Qt.UserRole) == old_to:
                    item.setSelected(True)
                    break
            idx = self.to_combo.findData(first_from)
            if idx >= 0:
                self.to_combo.setCurrentIndex(idx)
 
        self.from_list.blockSignals(False)
        self.to_combo.blockSignals(False)
 
        self._on_from_changed()
        self._on_to_changed(self.to_combo.currentIndex())

    def _restore_from_selection(self, from_classes):
        """Restore From list selections from a list of class codes"""
        self.from_list.clearSelection()
        
        if from_classes is None:
            self.from_list.item(0).setSelected(True)
            return
        
        if not isinstance(from_classes, (list, tuple)):
            from_classes = [from_classes]
        
        for i in range(self.from_list.count()):
            item = self.from_list.item(i)
            code = item.data(Qt.UserRole)
            if code in from_classes:
                item.setSelected(True)
    
    def sync_with_app(self):
        """Call this whenever tool/classes change externally."""
        self.from_list.blockSignals(True)
        self.to_combo.blockSignals(True)

        self._update_title()

        if hasattr(self.app, "from_classes"):
            self._restore_from_selection(self.app.from_classes)

        if getattr(self.app, "to_class", None) is not None:
            idx = self.to_combo.findData(self.app.to_class)
            if idx >= 0:
                self.to_combo.setCurrentIndex(idx)

        self.from_list.blockSignals(False)
        self.to_combo.blockSignals(False)

    def on_classes_changed(self):
        """
        Called when Display Mode loads new classes.
        ✅ FIXED: Properly preserves user's "To class" selection
        """
        print("\n" + "="*60)
        print("🔄 CLASS PICKER: Detected class changes from Display Mode")
        print("="*60)
        
        # ✅ CRITICAL: Save current selections BEFORE rebuild
        # Priority: 1) Current UI state, 2) Saved instance var, 3) App state
        old_to = self.to_combo.currentData()
        if old_to is None:
            old_to = self._saved_to_class
        if old_to is None:
            old_to = getattr(self.app, 'to_class', None)
        
        selected_items = self.from_list.selectedItems()
        old_from = [item.data(Qt.UserRole) for item in selected_items] if selected_items else None
        if old_from is None or len(old_from) == 0:
            old_from = self._saved_from_classes
        if old_from is None:
            old_from = getattr(self.app, 'from_classes', None)
        
        print(f"   📌 Preserving selections - From: {old_from}, To: {old_to}")
        
        # ✅ Update saved values before rebuild
        self._saved_to_class = old_to
        self._saved_from_classes = old_from
        
        # Rebuild dropdowns (will use saved values)
        self.populate_dropdowns()
        
        print(f"✅ Class Picker updated with preserved selections")
        print("="*60 + "\n")

    def _restore_selection(self, combo, old_value):
        """Try to restore a previous selection in combo box"""
        if old_value is None:
            return False
        
        for i in range(combo.count()):
            if combo.itemData(i) == old_value:
                combo.setCurrentIndex(i)
                print(f"   ✅ Restored selection: class {old_value}")
                return True
        
        print(f"   ⚠️ Could not find class {old_value}")
        return False

    def populate_dropdowns(self):
        """
        Build class dropdowns with FORCEFUL defaults.
        ✅ FIXED: Preserves "To class" and "From class" selections across rebuilds
        """
        print(f"\n🔄 Populating Class Picker...")
        
        # ---------------------------------------------------------
        # ✅ CRITICAL FIX: Get saved selections BEFORE clearing
        # ---------------------------------------------------------
        # Priority order: saved instance var > current UI > app state
        
        # Get "To class" to preserve
        to_class_to_restore = self._saved_to_class
        if to_class_to_restore is None:
            to_class_to_restore = self.to_combo.currentData() if self.to_combo.count() > 0 else None
        if to_class_to_restore is None:
            to_class_to_restore = getattr(self.app, 'to_class', None)
        
        # Get "From classes" to preserve
        from_classes_to_restore = self._saved_from_classes
        if from_classes_to_restore is None:
            selected_items = self.from_list.selectedItems()
            if selected_items:
                from_classes_to_restore = [item.data(Qt.UserRole) for item in selected_items 
                                           if item.data(Qt.UserRole) is not None]
        if from_classes_to_restore is None:
            from_classes_to_restore = getattr(self.app, 'from_classes', None)
        
        print(f"   📌 Will restore - To: {to_class_to_restore}, From: {from_classes_to_restore}")
        
        # ---------------------------------------------------------
        # Define Forceful Defaults (Safety Net)
        # ---------------------------------------------------------
        STANDARD_LEVELS = {
            0: "Created",
            1: "Ground",
            2: "Low vegetation",
            3: "Medium vegetation",
            4: "High vegetation",
            5: "Buildings",
            6: "Water",
            7: "Railways",
            8: "Railways (structure)",
            9: "Type 1 Street",
            10: "Type 2 Street",
            11: "Type 3 Street",
            12: "Type 4 Street",
            13: "Bridge",
            14: "Bare Conductors",
            15: "Elicord Overhead Cables",
            16: "Pylons or Poles",
            17: "HV Overhead Lines",
            18: "MV Overhead Lines",
            19: "LV Overhead Lines",
        }

        # Block signals during rebuild
        self.from_list.blockSignals(True)
        self.to_combo.blockSignals(True)

        # Clear existing items
        self.from_list.clear()
        self.to_combo.clear()
        
        class_list = []
        
        # Get classes from Display Mode
        display_dialog = getattr(self.app, 'display_mode_dialog', getattr(self.app, 'display_dialog', None))

        if display_dialog:
            table = display_dialog.table
            for row in range(table.rowCount()):
                try:
                    code_item = table.item(row, 1)
                    if not code_item: continue
                    
                    code = int(code_item.text())
                    desc = table.item(row, 2).text()
                    
                    lvl_item = table.item(row, 4)
                    lvl = lvl_item.text() if lvl_item else ""
                    
                    color_item = table.item(row, 5)
                    color = color_item.background().color() if color_item else QColor(128, 128, 128)
                    
                    class_list.append({'code': code, 'desc': desc, 'lvl': lvl, 'color': color})
                except Exception:
                    continue
                    
        # Fallback: Use app's class_palette
        if not class_list and hasattr(self.app, 'class_palette'):
            for code, info in sorted(self.app.class_palette.items()):
                color_tuple = info.get('color', (128, 128, 128))
                class_list.append({
                    'code': code,
                    'desc': info.get('description', ''),
                    'lvl': info.get('lvl', ''),
                    'color': QColor(*color_tuple)
                })

        # ---------------------------------------------------------
        # Populate UI
        # ---------------------------------------------------------
        
        # Add "Any class" to From list
        any_item = QListWidgetItem("Any class")
        any_item.setData(Qt.UserRole, None)
        self.from_list.addItem(any_item)
        
        class_list.sort(key=lambda x: x['code'])
        
        for cls in class_list:
            code = cls['code']
            lvl = cls['lvl']
            
            if not lvl or lvl.strip() == "":
                lvl = STANDARD_LEVELS.get(code, str(code))
            
            pixmap = QPixmap(16, 16)
            pixmap.fill(cls['color'])
            icon = QIcon(pixmap)
            
            desc = cls['desc']
            label = f"{code} - {lvl} ({desc})" if desc else f"{code} - {lvl}"
            
            # Add to "From" List
            item = QListWidgetItem(icon, label)
            item.setData(Qt.UserRole, code)
            self.from_list.addItem(item)
            
            # Add to "To" Dropdown
            self.to_combo.addItem(icon, label, code)
        
        # ---------------------------------------------------------
        # ✅ CRITICAL FIX: Restore selections AFTER rebuilding
        # ---------------------------------------------------------
        
        # Restore "To class"
        restored_to = False
        if to_class_to_restore is not None:
            for i in range(self.to_combo.count()):
                if self.to_combo.itemData(i) == to_class_to_restore:
                    self.to_combo.setCurrentIndex(i)
                    restored_to = True
                    print(f"   ✅ Restored To class: {to_class_to_restore}")
                    break
        
        if not restored_to and self.to_combo.count() > 0:
            # Default to first non-zero class if available, else first item
            default_idx = 0
            for i in range(self.to_combo.count()):
                if self.to_combo.itemData(i) != 0:
                    default_idx = i
                    break
            self.to_combo.setCurrentIndex(default_idx)
            print(f"   ℹ️ No saved To class, defaulting to index {default_idx}")
        
        # Restore "From classes"
        if from_classes_to_restore is not None and len(from_classes_to_restore) > 0:
            for i in range(self.from_list.count()):
                item = self.from_list.item(i)
                code = item.data(Qt.UserRole)
                if code in from_classes_to_restore:
                    item.setSelected(True)
            print(f"   ✅ Restored From classes: {from_classes_to_restore}")
        else:
            # Default to "Any class"
            self.from_list.item(0).setSelected(True)
            print(f"   ℹ️ No saved From class, defaulting to 'Any class'")
        
        # Unblock signals
        self.from_list.blockSignals(False)
        self.to_combo.blockSignals(False)
        
        # ✅ Update app state to match restored selections
        self.app.to_class = self.to_combo.currentData()
        self._saved_to_class = self.app.to_class
        
        selected_items = self.from_list.selectedItems()
        if any(item.data(Qt.UserRole) is None for item in selected_items):
            self.app.from_classes = None
        else:
            self.app.from_classes = [item.data(Qt.UserRole) for item in selected_items]
        self._saved_from_classes = self.app.from_classes
        
        print(f"   ✅ Final state - To: {self.app.to_class}, From: {self.app.from_classes}")
        print(f"✅ Populated Class Picker with {len(class_list)} classes\n")

    def configure_for_background_mode(self):
        """Configure picker when 'To class' is background (0)."""
        self.setEnabled(True)
        print("🎨 ClassPicker: background mode configured")