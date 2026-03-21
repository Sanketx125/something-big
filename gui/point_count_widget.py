from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QFrame, QPushButton
)
from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QFont
import numpy as np


class PointCountWidget(QWidget):
    """
    Simple, clean floating statistics widget.
    ✅ FIXED: Now properly displays LVL (Level/Class Name) from Display Mode
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.app = None
        self.update_timer = QTimer()
        self.update_timer.setSingleShot(True)
        self.update_timer.timeout.connect(self._delayed_update)
        self.is_expanded = False
        self.parent_window = parent  # ✅ Store parent for event filter
        self.init_ui()
        self.panel.hide()  
        
        # Make it float on top
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.raise_()

    def eventFilter(self, obj, event):
        """Handle parent window resize events (ribbon system method)."""
        if obj == self.parent_window and event.type() == QEvent.Resize:
            # Reposition on window resize
            self.position_in_ribbon_system(self.parent_window)
        return super().eventFilter(obj, event)

    def position_in_ribbon_system(self, parent_window):
        """Position widget using ribbon system method (setGeometry)."""
        if parent_window:
            # Get window dimensions
            window_width = parent_window.width()
            
            # Calculate position: far right with 10px margin
            x = window_width - self.toggle_btn.width() - 10
            y = 10
            
            # Use setGeometry (ribbon system method)
            self.setGeometry(x, y, self.toggle_btn.width(), self.toggle_btn.height())

    def init_ui(self):
        """Initialize the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
       
        # ===== COMPACT BUTTON =====
        self.toggle_btn = QPushButton("Stats")
        self.toggle_btn.setFixedSize(90, 32)  
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #2c2c2c;
                color: #f0f0f0;
                font-weight: bold;
                font-size: 10px;
                border: 2px solid #3c3c3c;
                border-radius: 5px;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #3c3c3c;
                border-color: #4c4c4c;
            }
            QPushButton:pressed {
                background-color: #ffaa00;
                color: black;
            }
        """)
        self.toggle_btn.clicked.connect(self.toggle_panel)
        layout.addWidget(self.toggle_btn, alignment=Qt.AlignTop)
       
        # ===== PANEL (FIXED PARENTING) =====
        # ✅ FIX: Use self.parent_window so it attaches to the main software
        # This ensures it minimizes and closes along with the app.
        parent = self.parent_window if self.parent_window else self
        self.panel = QWidget(parent)
       
        # ✅ Qt.Tool makes it a floating palette that stays on top but belongs to the app
        self.panel.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
       
        self.panel.setFixedSize(320, 420)  
        self.panel.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                border: 2px solid #3c3c3c;
                border-radius: 8px;
            }
        """)
       
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(8)
       
        # Title
        title = QLabel("Point Statistics")
        title.setStyleSheet("""
            QLabel {
                font-weight: bold;
                font-size: 12px;
                color: #f0f0f0;
                padding: 4px 0px;
            }
        """)
        panel_layout.addWidget(title)
       
        # Total count
        self.total_label = QLabel("Total: 0")
        self.total_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 0px;
            }
        """)
        panel_layout.addWidget(self.total_label)
       
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background-color: #3c3c3c;")
        line.setFixedHeight(1)
        panel_layout.addWidget(line)
       
        # Scrollable area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background: #1e1e1e;
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: #3c3c3c;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4c4c4c;
            }
        """)
       
        self.stats_container = QWidget()
        self.stats_layout = QVBoxLayout(self.stats_container)
        self.stats_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_layout.setSpacing(2)
        self.stats_layout.setAlignment(Qt.AlignTop)
       
        scroll.setWidget(self.stats_container)
        panel_layout.addWidget(scroll)
       
        # Close button
        close_btn = QPushButton("✕ Close")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #2c2c2c;
                color: #f0f0f0;
                font-size: 10px;
                font-weight: bold;
                padding: 6px;
                border-radius: 4px;
                border: 1px solid #3c3c3c;
            }
            QPushButton:hover {
                background-color: #d32f2f;
                color: white;
            }
        """)
        close_btn.clicked.connect(self.toggle_panel)
        panel_layout.addWidget(close_btn)
       
        self.panel.hide()  
    
    def toggle_panel(self):
        """Toggle the statistics panel."""
        self.is_expanded = not self.is_expanded
        
        if self.is_expanded:
            btn_global = self.mapToGlobal(self.toggle_btn.geometry().bottomLeft())
            self.panel.move(btn_global.x(), btn_global.y() + 5)
            self.panel.show()
            self.panel.raise_()
            self.toggle_btn.setText("Stats ▼")
            self.update_statistics()
        else:
            self.toggle_btn.setText("Stats")
            self.panel.hide()
    
    def set_app(self, app):
        """Set the main application reference and connect signals."""
        self.app = app
        
        if hasattr(app, 'display_dialog') and app.display_dialog:
            self.connect_to_display_mode(app.display_dialog)
        
        if hasattr(app, 'classification_changed'):
            app.classification_changed.connect(self.schedule_update)
        
        if hasattr(app, 'classify_dialog') and app.classify_dialog:
            self.connect_to_classify_dialog(app.classify_dialog)
    
    def connect_to_display_mode(self, display_mode_dialog):
        """Connect to DisplayModeDialog to receive class updates."""
        try:
            if hasattr(display_mode_dialog, 'classes_loaded'):
                display_mode_dialog.classes_loaded.connect(self.schedule_update)
            
            if hasattr(display_mode_dialog, 'applied'):
                display_mode_dialog.applied.connect(self.schedule_update)
        except Exception as e:
            print(f"   ⚠️ Could not connect to display_mode: {e}")
    
    def connect_to_classify_dialog(self, classify_dialog):
        """Connect to ClassifyDialog for updates."""
        try:
            if hasattr(classify_dialog, 'classification_complete'):
                classify_dialog.classification_complete.connect(self.schedule_update)
        except Exception as e:
            print(f"   ⚠️ Could not connect to classify_dialog: {e}")
    
    def schedule_update(self):
        """Schedule an update with debouncing."""
        self.update_timer.stop()
        self.update_timer.start(200)
    
    def _delayed_update(self):
        """Delayed update after debouncing."""
        if self.is_expanded:
            self.update_statistics()

    def get_class_info_from_ptc(self):
        """
        ✅ FIXED: Properly reads and displays LVL (Level/Class Name)
        Priority: Display Mode table > class_palette > fallback
        """
        class_info = {}

        # ✅ PRIORITY 1: Get from Display Mode table (includes user changes)
        dialog = None
        if self.app:
            # Try display_mode_dialog FIRST (correct name)
            if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
                dialog = self.app.display_mode_dialog
            # Fallback to display_dialog (old name)
            elif hasattr(self.app, 'display_dialog') and self.app.display_dialog:
                dialog = self.app.display_dialog
        
        if dialog and hasattr(dialog, 'table'):
            table = dialog.table
            
            print(f"   📋 Reading from Display Mode table ({table.rowCount()} rows)...")
            
            for row in range(table.rowCount()):
                    try:
                        # Column 1: Code
                        code_item = table.item(row, 1)
                        if not code_item:
                            continue
                        
                        code = int(code_item.text())
                        
                        # Column 2: Description
                        desc_item = table.item(row, 2)
                        desc = desc_item.text() if desc_item else f"Class {code}"
                        
                        # ✅ Column 4: LVL (Level/Class Name) - THIS IS THE KEY!
                        lvl_item = table.item(row, 4)
                        lvl = lvl_item.text() if lvl_item else ""
                        
                        # ✅ Clean up level value
                        if lvl in (None, "", " ", "Zero length ..."):
                            lvl = ""  # Empty = don't show
                        
                        # Column 5: Color
                        color_item = table.item(row, 5)
                        color = (160, 160, 160)  # default gray
                        if color_item:
                            try:
                                rgb = color_item.background().color().getRgb()[:3]
                                color = tuple(rgb)
                            except:
                                pass
                        
                        # Column 0: Show (checkbox)
                        chk = table.cellWidget(row, 0)
                        show = chk.isChecked() if chk else True
                        
                        class_info[code] = {
                            "description": desc,
                            "color": color,
                            "show": show,
                            "lvl": lvl,  # ✅ Level from Display Mode - will be displayed!
                        }
                        
                        print(f"      ✅ Code {code}: lvl='{lvl}'")
                        
                    except Exception as e:
                        print(f"   ⚠️ Error reading row {row}: {e}")
                        continue

            if class_info:
                print(f"   ✅ Loaded {len(class_info)} classes from Display Mode")
                return class_info

        # ✅ PRIORITY 2: Get from class_palette (fallback when Display Mode not open)
        if self.app and hasattr(self.app, 'class_palette') and self.app.class_palette:
            print(f"   ℹ️ Using class_palette fallback")
            for code, info in self.app.class_palette.items():
                lvl = info.get("lvl", "")
                
                # ✅ Clean up level value
                if lvl in (None, "", " "):
                    lvl = ""
                
                class_info[code] = {
                    "description": info.get("description", f"Class {code}"),
                    "color": info.get("color", (160, 160, 160)),
                    "show": info.get("show", True),
                    "lvl": lvl,  # ✅ Level from palette
                }
            return class_info

        return class_info
    
    def update_statistics(self):
        """Update the statistics display."""
        # Clear existing
        while self.stats_layout.count():
            child = self.stats_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        if self.app is None or self.app.data is None:
            self.total_label.setText("Total: 0")
            return
        
        xyz = self.app.data.get("xyz")
        classification = self.app.data.get("classification")
        
        if xyz is None or len(xyz) == 0:
            self.total_label.setText("Total: 0")
            return
        
        total_points = len(xyz)
        self.total_label.setText(f"Total: {total_points:,}")
        
        class_info = self.get_class_info_from_ptc()
        
        if classification is None:
            for class_code in sorted(class_info.keys()):
                info = class_info[class_code]
                widget = self._create_class_widget(
                    class_code,
                    info["description"],
                    0,
                    info["color"],
                    info["show"],
                    info["lvl"],  # ✅ Pass the LVL
                )
                self.stats_layout.addWidget(widget)
            return
        
        # Count points per class
        unique_classes, counts = np.unique(classification, return_counts=True)
        point_counts = {int(cls): int(cnt) for cls, cnt in zip(unique_classes, counts)}
        
        for class_code in sorted(class_info.keys()):
            info = class_info[class_code]
            count = point_counts.get(class_code, 0)
            
            widget = self._create_class_widget(
                class_code,
                info["description"],
                count,
                info["color"],
                info["show"],
                info["lvl"],  # ✅ Pass the LVL
            )
            self.stats_layout.addWidget(widget)
    
    def _create_class_widget(self, code, description, count, color, visible, lvl):
        """
        ✅ FIXED: Properly displays LVL (Level/Class Name) prominently
        """
        label = QLabel()

        r, g, b = color if color else (80, 80, 80)
        bg_color = f"rgba({r}, {g}, {b}, 0.25)"
        count_text = f"({count:,})" if count > 0 else "(0)"
        
        # ✅ Handle level display - show if available
        if lvl and lvl not in (None, "", " ", "-"):
            # ✅ Show both class name/level
            html = f"""
            <table width="100%" cellspacing="0" cellpadding="0" style="border: none;">
            <tr>
                <td style="text-align: left;">
                    <div style="color: #ffffff; font-weight: 900;">[{code}] {description}</div>
                    <div style="color: #ffaa00; font-size: 10px; font-weight: bold; margin-top: 2px;">→ {lvl}</div>
                </td>
                <td style="text-align: right; color: #ffffff; width: 70px; vertical-align: middle;">
                    {count_text}
                </td>
            </tr>
            </table>
            """
        else:
            # No level - simpler layout
            html = f"""
            <table width="100%" cellspacing="0" cellpadding="0" style="border: none;">
            <tr>
                <td style="text-align: left; color: #ffffff;">
                    <span style="font-weight: 900;">[{code}]</span> {description}
                </td>
                <td style="text-align: right; color: #ffffff; width: 70px;">
                    {count_text}
                </td>
            </tr>
            </table>
            """

        label.setText(html)
        label.setTextFormat(Qt.RichText)

        opacity = "1.0" if visible and count > 0 else "0.4"

        label.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                padding: 8px 10px;
                border-radius: 3px;
                font-size: 11px;
                opacity: {opacity};
            }}
        """)

        label.setProperty('class_code', code)
        return label


# ===== HELPER FUNCTIONS =====

def add_point_stats_dropdown(app, parent_widget):
    """
    Add the statistics widget using ribbon system positioning.
    Auto-repositions on window resize using event filter.
    """
    dropdown = PointCountWidget(parent_widget)
    dropdown.set_app(app)
    
    # Install event filter to catch resize events (ribbon system method)
    if parent_widget:
        parent_widget.installEventFilter(dropdown)
    
    # Initial positioning
    dropdown.position_in_ribbon_system(parent_widget)
    dropdown.show()
    
    # Store reference in app
    app.point_count_widget = dropdown
    
    print("✅ Point Stats widget added (ribbon system with LVL display)")
    return dropdown


def refresh_point_statistics(app):
    """Refresh the statistics display."""
    if hasattr(app, "point_count_widget") and app.point_count_widget:
        app.point_count_widget.schedule_update()