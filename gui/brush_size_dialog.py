
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QDoubleSpinBox, QPushButton, QSlider, QRadioButton,
    QButtonGroup, QGroupBox, QFrame
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPalette, QFont

class BrushSizeDialog(QDialog):
    """
    A modernized dialog to set brush size and shape.
    Updated with green accents and a highlighted outer border to match the specific UI theme.
    """
    
    def __init__(self, parent=None, current_size=1.0, current_shape="circle"):
        super().__init__(parent)
        self.setWindowTitle("Brush Settings")
        self.setModal(True)
        self.setMinimumWidth(400)
        
        # Remove standard window frame to better control the 'highlight border' look if needed,
        # but here we'll use a CSS-based border on the main dialog.
        
        self.brush_size = current_size
        self.brush_shape = current_shape
        self._settings_changed = False
        
        self._setup_ui()
        self._apply_styles()
        
        # Connect change tracking
        self.slider.valueChanged.connect(self._mark_changed)
        self.spinbox.valueChanged.connect(self._mark_changed)
        self.circle_radio.toggled.connect(self._mark_changed)
        self.rectangle_radio.toggled.connect(self._mark_changed)

    def _mark_changed(self):
        self._settings_changed = True

    def _apply_styles(self):
        """Apply the green-accented dark theme with an outer highlight border."""
        # Theme Color: Emerald Green #27ae60 or #1db954 (Based on screenshots)
        # Using #2ecc71 / #1abc9c style green for high visibility
        green_accent = "#1abc9c" 
        green_hover = "#16a085"
        
        self.setStyleSheet(f"""
            QDialog {{
                background-color: #000000;
                color: #ffffff;
                border: 2px solid #22252a; /* Outer border */
            }}
            QLabel {{
                color: #ffffff;
                font-family: 'Segoe UI', sans-serif;
            }}
            QGroupBox {{
                border: 1px solid #22252a;
                border-radius: 8px;
                margin-top: 1.2em;
                font-weight: bold;
                color: {green_accent};
                padding-top: 15px;
                background-color: #0c0d0e;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
            }}
            QRadioButton {{
                color: #e0e0e0;
                padding: 10px;
                font-size: 13px;
                background: transparent;
            }}
            QRadioButton::indicator {{
                width: 22px;
                height: 22px;
                border-radius: 11px;
                border: 2px solid #373a40;
                background: #1a1b1e;
            }}
            QRadioButton::indicator:checked {{
                background-color: {green_accent};
                border: 2px solid {green_accent};
            }}
            QRadioButton::indicator:hover {{
                border-color: {green_accent};
            }}
            QSlider::groove:horizontal {{
                border: 1px solid #373a40;
                height: 4px;
                background: #1a1b1e;
                margin: 2px 0;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {green_accent};
                border: none;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QDoubleSpinBox {{
                background-color: #1a1b1e;
                color: #ffffff;
                border: 1px solid #373a40;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 90px;
                selection-background-color: {green_accent};
                selection-color: #000000;
            }}
            QPushButton {{
                background-color: #25262b;
                color: #ffffff;
                border: 1px solid #373a40;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: #2c2e33;
                border-color: #5c5f66;
            }}
            QPushButton#okButton {{
                background-color: {green_accent};
                color: #000000;
                border: none;
                padding: 8px 20px;
                font-weight: bold;
            }}
            QPushButton#okButton:hover {{
                background-color: {green_hover};
            }}
            #previewPanel {{
                background-color: #080808;
                border: 1px solid #22252a;
                border-radius: 4px;
                color: #cccccc;
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.5px;
                margin-top: 10px;
            }}
            #presetContainer {{
                background-color: #0c0d0e;
                border-radius: 6px;
                padding: 5px;
            }}
            #presetLabel {{
                font-size: 9px; 
                font-weight: bold; 
                color: #5c5f66;
                letter-spacing: 1px;
            }}
        """)

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # --- Header ---
        header_layout = QVBoxLayout()
        header_layout.setSpacing(2)
        title = QLabel("BRUSH CONFIGURATION")
        # Color updated to green
        title.setStyleSheet("font-weight: 800; font-size: 14px; color: #1abc9c; letter-spacing: 0.5px;")
        
        desc = QLabel("Adjust tool properties for point cloud classification.")
        desc.setStyleSheet("color: #666666; font-size: 11px;")
        
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        layout.addLayout(header_layout)

        # --- Shape Selection ---
        shape_group = QGroupBox("Brush Shape")
        shape_layout = QHBoxLayout()
        shape_layout.setContentsMargins(15, 10, 15, 15)
        
        self.shape_button_group = QButtonGroup(self)
        self.circle_radio = QRadioButton("Circle")
        self.rectangle_radio = QRadioButton("Square")
        
        self.shape_button_group.addButton(self.circle_radio, 0)
        self.shape_button_group.addButton(self.rectangle_radio, 1)
        
        if self.brush_shape == "circle":
            self.circle_radio.setChecked(True)
        else:
            self.rectangle_radio.setChecked(True)
            
        shape_layout.addWidget(self.circle_radio)
        shape_layout.addSpacing(30)
        shape_layout.addWidget(self.rectangle_radio)
        shape_layout.addStretch()
        shape_group.setLayout(shape_layout)
        layout.addWidget(shape_group)

        # --- Size Controls ---
        size_group = QGroupBox("Size Settings")
        size_group_layout = QVBoxLayout()
        size_group_layout.setContentsMargins(15, 15, 15, 15)
        size_group_layout.setSpacing(12)
        
        # Slider
        slider_row = QHBoxLayout()
        slider_label = QLabel("Scale")
        slider_label.setFixedWidth(50)
        slider_label.setStyleSheet("color: #bbbbbb;")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(1)
        self.slider.setMaximum(100)
        self.slider.setValue(int(self.brush_size * 10))
        slider_row.addWidget(slider_label)
        slider_row.addWidget(self.slider)
        size_group_layout.addLayout(slider_row)
        
        # Precise Input
        spin_row = QHBoxLayout()
        spin_label = QLabel("Radius")
        spin_label.setFixedWidth(50)
        spin_label.setStyleSheet("color: #bbbbbb;")
        self.spinbox = QDoubleSpinBox()
        self.spinbox.setRange(0.1, 10.0)
        self.spinbox.setSingleStep(0.1)
        self.spinbox.setValue(self.brush_size)
        self.spinbox.setSuffix(" units")
        spin_row.addWidget(spin_label)
        spin_row.addStretch()
        spin_row.addWidget(self.spinbox)
        size_group_layout.addLayout(spin_row)
        
        size_group.setLayout(size_group_layout)
        layout.addWidget(size_group)

        # --- Presets ---
        preset_frame = QFrame()
        preset_frame.setObjectName("presetContainer")
        preset_layout = QHBoxLayout(preset_frame)
        preset_layout.setContentsMargins(10, 5, 10, 5)
        preset_layout.setSpacing(10)
        
        preset_label = QLabel("PRESETS:")
        preset_label.setObjectName("presetLabel")
        preset_layout.addWidget(preset_label)
        
        for size in [0.5, 1.0, 2.0, 5.0]:
            btn = QPushButton(f"{size:.1f}")
            btn.setFixedWidth(55)
            btn.clicked.connect(lambda checked, s=size: self.set_size(s))
            preset_layout.addWidget(btn)
        
        preset_layout.addStretch()
        layout.addWidget(preset_frame)

        # --- Live Preview Bar ---
        self.preview_label = QLabel()
        self.preview_label.setObjectName("previewPanel")
        self.preview_label.setFixedHeight(35)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self._update_preview()
        layout.addWidget(self.preview_label)

        # --- Actions ---
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        button_layout.setContentsMargins(0, 10, 0, 0)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedWidth(90)
        self.cancel_button.clicked.connect(self.reject)
        
        self.ok_button = QPushButton("Apply Settings")
        self.ok_button.setObjectName("okButton")
        self.ok_button.setFixedWidth(130)
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setDefault(True)
        
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Logic connections
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.spinbox.valueChanged.connect(self._on_spinbox_changed)
        self.circle_radio.toggled.connect(self._on_shape_changed)

    def _update_preview(self):
        shape_icon = "●" if self.brush_shape == "circle" else "■"
        self.preview_label.setText(
            f"{shape_icon} {self.brush_shape.upper()} PREVIEW | RADIUS: {self.brush_size:.1f} UNITS"
        )

    def _on_slider_changed(self, value):
        size = value / 10.0
        self.spinbox.blockSignals(True)
        self.spinbox.setValue(size)
        self.spinbox.blockSignals(False)
        self.brush_size = size
        self._update_preview()

    def _on_spinbox_changed(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(int(value * 10))
        self.slider.blockSignals(False)
        self.brush_size = value
        self._update_preview()

    def _on_shape_changed(self):
        self.brush_shape = "circle" if self.circle_radio.isChecked() else "rectangle"
        self._update_preview()

    def set_size(self, size):
        self.spinbox.setValue(size)

    def get_brush_size(self):
        return self.brush_size

    def get_brush_shape(self):
        return self.brush_shape

    def accept(self):
        if not self._settings_changed:
            pass 
        super().accept()

def show_brush_size_dialog(app):
    """
    Show the brush settings dialog and update app brush configuration.
    Returns: 'accepted', 'unchanged', or 'cancelled'
    
    Args:
        app: Your main application instance
        
    Returns:
        str: 'accepted' if user changed and clicked OK
             'unchanged' if user didn't change anything (auto-accepts)
             'cancelled' if user clicked cancel
    """
    current_size = getattr(app, "brush_radius", 1.0)
    current_shape = getattr(app, "brush_shape", "circle")
    
    dialog = BrushSizeDialog(
        parent=app, 
        current_size=current_size,
        current_shape=current_shape
    )
    
    # ✅ CRITICAL: Track if user makes ANY changes
    settings_changed = [False]  # Use list so inner function can modify it
    
    def on_any_change():
        settings_changed[0] = True
    
    # Connect ALL input widgets to detect changes
    dialog.slider.valueChanged.connect(on_any_change)
    dialog.spinbox.valueChanged.connect(on_any_change)
    dialog.circle_radio.toggled.connect(on_any_change)
    dialog.rectangle_radio.toggled.connect(on_any_change)
    
    result = dialog.exec_()
    
    new_size = dialog.get_brush_size()
    new_shape = dialog.get_brush_shape()
    
    if result == QDialog.Accepted:
        if not settings_changed[0]:
            # User clicked OK but nothing changed - auto-accept
            print("ℹ️ No changes to brush settings - auto-accepting")
            return 'unchanged'
        
        # Settings changed and user clicked OK
        # ✅ CRITICAL FIX: Set BOTH world radius and pixel preview size
        app.brush_radius = new_size  # World units (for classification)
        
        # ✅ Convert world radius to pixel size for preview
        base_pixel_size = 20.0  # Base size for 1.0 unit
        app.brush_preview_px = new_size * base_pixel_size
        
        # Store shape
        app.brush_shape = new_shape
        
        shape_icon = "●" if new_shape == "circle" else "■"
        
        if hasattr(app, "statusBar"):
            app.statusBar().showMessage(
                f"🖌️ Brush: {shape_icon} {new_shape} - {new_size:.1f} units "
                f"({app.brush_preview_px:.0f}px preview)", 
                3000
            )
        
        print(f"✅ Brush updated: {new_shape} shape, {new_size:.1f} units, "
              f"{app.brush_preview_px:.0f}px preview")
        return 'accepted'
    else:
        # User clicked Cancel
        print("❌ Brush settings dialog cancelled")
        return 'cancelled'


def activate_brush_tool_with_dialog(app):
    """
    Activate brush tool with smart behavior:
    - Normal click: Use last settings (instant activation)
    - Shift+Click: Show settings dialog first
    - First time ever: Auto-show settings dialog
    """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    
    # Check if this is first time using brush
    first_time = not hasattr(app, "brush_radius")
    
    # Check if Shift key is held
    modifiers = QApplication.keyboardModifiers()
    shift_held = bool(modifiers & Qt.ShiftModifier)
    
    # Show dialog if: first time OR Shift held
    if first_time or shift_held:
        result = show_brush_size_dialog(app)
        
        if result == 'cancelled':
            print("Brush tool activation cancelled by user")
            if hasattr(app, "statusBar"):
                app.statusBar().showMessage("❌ Brush cancelled", 2000)
            return False
    
    # Activate brush with current/last settings
    app.active_classify_tool = "brush"
    
    # Ensure defaults exist
    if not hasattr(app, "brush_radius"):
        app.brush_radius = 1.0
    if not hasattr(app, "brush_shape"):
        app.brush_shape = "circle"
    if not hasattr(app, "brush_preview_px"):
        app.brush_preview_px = 20.0
    
    radius = app.brush_radius
    shape = app.brush_shape
    shape_icon = "●" if shape == "circle" else "■"
    
    # Show status message
    if hasattr(app, "statusBar"):
        hint = " (Shift+Click for settings)" if not first_time else ""
        app.statusBar().showMessage(
            f"🖌️ Brush: {shape_icon} {shape}, {radius:.1f} units{hint}", 
            4000
        )
    
    print(f"✅ Brush activated: {shape} shape, radius {radius:.1f}")
    
    # Open class picker
    _open_class_picker_safely(app)
    
    return True


def _open_class_picker_safely(app):
    """
    Safely open class picker without stealing focus from main view.
    """
    from gui.class_picker import ClassPicker
    
    if not hasattr(app, "class_picker") or app.class_picker is None:
        app.class_picker = ClassPicker(app)
        app.class_picker.configure_for_background_mode()
        app.class_picker.ensure_visible()
    else:
        app.class_picker.sync_with_app()
        if not app.class_picker.isVisible():
            app.class_picker.ensure_visible()
    
    # ✅ CRITICAL: Keep focus on main view
    if hasattr(app, 'vtk_widget'):
        app.vtk_widget.setFocus()
    
