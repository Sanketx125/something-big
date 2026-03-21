"""
DXF Attachment System with Multiple File Support and Management

Features:
- Select multiple DXF files at once
- Auto-detect matching .PRJ files for each DXF
- Manage attached DXFs with remove capability
- Coordinate reprojection support
- Overlay/underlay modes
"""

import os
import numpy as np
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QComboBox, QCheckBox, QGroupBox,
    QRadioButton, QButtonGroup, QSpinBox, QDoubleSpinBox,
    QListWidget, QListWidgetItem, QWidget, QScrollArea
)
from PySide6.QtCore import Qt, Signal , QCoreApplication
from PySide6.QtGui import QFont, QColor, QIcon
from gui.theme_manager import get_dialog_stylesheet, get_progress_dialog_stylesheet, get_title_banner_style, get_file_item_row_style, get_badge_style, get_icon_button_style, get_notice_banner_style, ThemeColors

try:
    import ezdxf
    from pyproj import CRS, Transformer
    DEPENDENCIES_AVAILABLE = True
except ImportError:
    DEPENDENCIES_AVAILABLE = False
    print("⚠️ Missing dependencies: pip install ezdxf pyproj")

"""
Add this class RIGHT AFTER the imports in your dxf_attachment.py file
Place it BEFORE the DXFDisplayOptionsDialog class
"""

from PySide6.QtCore import QThread, Signal
import traceback

# ============================================================================
# NEW: Background Worker Thread - Add this to your file
# ============================================================================

class DXFProcessWorker(QThread):
    """
    Background thread worker for processing DXF files
    Prevents UI freezing during heavy operations
    """
    progress = Signal(int, str)  # (percentage, status_message)
    finished = Signal(list)      # Emits list of processed attachments
    error = Signal(str)          # Emits error message
    
    def __init__(self, items, project_crs=None):
        super().__init__()
        self.items = items
        self.project_crs = project_crs
        self._is_cancelled = False
    
    def cancel(self):
        """Cancel the processing"""
        self._is_cancelled = True
    
    def run(self):
        """Run in background thread - DO NOT touch UI here!"""
        try:
            import ezdxf
            from pyproj import Transformer
            import numpy as np
            
            all_attachments = []
            total = len(self.items)
            
            for idx, item in enumerate(self.items):
                if self._is_cancelled:
                    return
                
                # Report progress
                progress_pct = int((idx / total) * 100)
                self.progress.emit(progress_pct, f"Processing {item.dxf_path.name}...")
                
                # Process the DXF file
                attachment_data = self._process_single_dxf(item)
                if attachment_data:
                    all_attachments.append(attachment_data)
            
            # Done!
            self.progress.emit(100, "Processing complete")
            self.finished.emit(all_attachments)
            
        except Exception as e:
            self.error.emit(f"Processing failed: {str(e)}\n{traceback.format_exc()}")
    
    def _process_single_dxf(self, item):
        """Process a single DXF file (runs in background thread)"""
        try:
            import ezdxf
            from pyproj import Transformer
            import numpy as np
            
            # Load DXF if not cached
            if item.cached_dxf_doc:
                dxf_doc = item.cached_dxf_doc
            else:
                dxf_doc = ezdxf.readfile(str(item.dxf_path))
                item.cached_dxf_doc = dxf_doc
            
            modelspace = dxf_doc.modelspace()
            
            # Get display options
            color_override = None
            if getattr(item, "override_enabled", False):
                color_override = getattr(item, "override_color", (255, 0, 0))
            
            display_mode = getattr(item, "display_mode", "overlay")
            
            # Setup transformer
            transformer = None
            if item.dxf_crs and self.project_crs:
                try:
                    transformer = Transformer.from_crs(
                        item.dxf_crs,
                        self.project_crs,
                        always_xy=True
                    )
                except Exception as e:
                    print(f"  ⚠️ Transformer failed: {e}")
            
            # Process entities - ✅ FIXED: Pass dxf_doc
            processed_entities = []
            for entity in modelspace:
                entity_data = self._process_entity(entity, transformer, color_override, dxf_doc)
                if entity_data:
                    processed_entities.append(entity_data)
            
            return {
                'filename': item.dxf_path.name,
                'full_path': str(item.dxf_path.resolve()),
                'mode': display_mode,
                'entities': processed_entities,
                'dxf_crs': item.dxf_crs.to_wkt() if item.dxf_crs else None,
                'project_crs': self.project_crs.to_wkt() if self.project_crs else None,
                'transformed': transformer is not None
            }
            
        except Exception as e:
            print(f"⚠️ Failed to process {item.dxf_path.name}: {e}")
            return None
        
    
    def _get_entity_color(self, entity):
        """Extract color from DXF entity"""
        try:
            color_index = entity.dxf.color
            if color_index == 256:
                return (255, 255, 255)
            aci_colors = {
                1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0),
                4: (0, 255, 255), 5: (0, 0, 255), 6: (255, 0, 255),
                7: (255, 255, 255)
            }
            return aci_colors.get(color_index, (255, 255, 255))
        except:
            return (255, 255, 255)
        
class DXFDisplayOptionsDialog(QDialog):
    """Per-file display options (overlay / underlay + color override)."""

    def __init__(self, parent=None, mode="overlay", override_enabled=False, override_color=(255, 0, 0)):
        super().__init__(parent)
        self.setWindowTitle("DXF Display Options")
        self.setModal(True)
        self.resize(260, 160)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Mode
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Display Mode:"))
        self.overlay_radio = QRadioButton("Overlay (on top)")
        self.underlay_radio = QRadioButton("Underlay (below)")
        if mode == "underlay":
            self.underlay_radio.setChecked(True)
        else:
            self.overlay_radio.setChecked(True)
        mode_row.addWidget(self.overlay_radio)
        mode_row.addWidget(self.underlay_radio)
        layout.addLayout(mode_row)

        # Color override
        color_row = QHBoxLayout()
        self.color_override_check = QCheckBox("Override color:")
        self.color_combo = QComboBox()
        self.color_combo.addItem("Red",    QColor(255, 0, 0))
        self.color_combo.addItem("Green",  QColor(0, 255, 0))
        self.color_combo.addItem("Blue",   QColor(0, 0, 255))
        self.color_combo.addItem("Yellow", QColor(255, 255, 0))
        self.color_combo.addItem("Cyan",   QColor(0, 255, 255))
        self.color_combo.addItem("Magenta",QColor(255, 0, 255))
        self.color_combo.addItem("White",  QColor(255, 255, 255))

        self.color_override_check.setChecked(override_enabled)
        self.color_combo.setEnabled(override_enabled)
        self.color_override_check.toggled.connect(self.color_combo.setEnabled)

        # Select initial color
        for i in range(self.color_combo.count()):
            q = self.color_combo.itemData(i)
            if (q.red(), q.green(), q.blue()) == override_color:
                self.color_combo.setCurrentIndex(i)
                break

        color_row.addWidget(self.color_override_check)
        color_row.addWidget(self.color_combo)
        layout.addLayout(color_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def get_values(self):
        mode = "underlay" if self.underlay_radio.isChecked() else "overlay"
        override_enabled = self.color_override_check.isChecked()
        qcolor = self.color_combo.currentData()
        override_color = (qcolor.red(), qcolor.green(), qcolor.blue())
        return mode, override_enabled, override_color

class DXFFileItem(QWidget):
    """Widget representing a single DXF file with remove button"""

    remove_requested = Signal(object)

    def __init__(self, dxf_path, prj_exists, parent=None):
        super().__init__(parent)
        self.dxf_path = Path(dxf_path)
        self.prj_exists = prj_exists
        self.dxf_crs = None
        self.entity_count = 0
        
        self.cached_dxf_doc = None
        self.cached_entities = None
        self.actor_cache = {}       # ✅ ADD THIS LINE
        self.entity_layers = {}     # ✅ ADD THIS LINE
        
        self.display_mode = "overlay"
        self.override_enabled = False
        self.override_color = (255, 0, 0)
        self.selected_layers = None  # None = all layers, or set of layer names

        self.init_ui()
    
    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        # Checkbox + file name  (default: checked)
        self.checkbox = QCheckBox(f"{self.dxf_path.name}")
        self.checkbox.setChecked(True)
        self.checkbox.setStyleSheet(f"color:{ThemeColors.get('accent')}; font-weight:bold; font-size:10px;")
        self.checkbox.stateChanged.connect(self.on_checkbox_changed)
        layout.addWidget(self.checkbox, 1)

        # PRJ status indicator
        if self.prj_exists:
            prj_label = QLabel("PRJ")
            prj_label.setStyleSheet(get_badge_style("success"))
        else:
            prj_label = QLabel("No PRJ")
            prj_label.setStyleSheet(get_badge_style("warning"))
        layout.addWidget(prj_label)

        # Entity count (will be updated after loading)
        self.count_label = QLabel("...")
        self.count_label.setStyleSheet(f"color:{ThemeColors.get('text_muted')}; font-size:9px;")
        layout.addWidget(self.count_label)
        # Layer selection button
        layers_btn = QPushButton("L")
        layers_btn.setFixedSize(26, 26)
        layers_btn.setToolTip("Select layers/levels")
        layers_btn.setStyleSheet(get_icon_button_style("default"))
        layers_btn.clicked.connect(self.open_layer_selection)
        layout.addWidget(layers_btn)
                

        # Display options button
        options_btn = QPushButton("O")
        options_btn.setFixedSize(26, 26)
        options_btn.setToolTip("Display options")
        options_btn.setStyleSheet(get_icon_button_style("settings"))
        options_btn.clicked.connect(self.open_display_options)
        layout.addWidget(options_btn)

        # Red remove button
        remove_btn = QPushButton("X")
        remove_btn.setFixedSize(26, 26)
        remove_btn.setStyleSheet(get_icon_button_style("danger"))
        remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(remove_btn)

        self.setStyleSheet(get_file_item_row_style())

    def cache_dxf_data(self, dxf_doc, processed_entities):
        """Cache the parsed DXF data for fast re-use"""
        self.cached_dxf_doc = dxf_doc
        self.cached_entities = processed_entities        
    
    def update_entity_count(self, count):
        """Update the entity count display"""
        self.entity_count = count
        self.count_label.setText(f"{count} entities")
        self.count_label.setStyleSheet(f"color:{ThemeColors.get('accent')}; font-size:7px; font-weight:bold;")

    def is_checked(self) -> bool:
        """Return whether this DXF file is selected for attachment."""
        return self.checkbox.isChecked()
    
    def on_checkbox_changed(self, state):
        """Handle checkbox state changes - show/hide this DXF's actors"""
        try:
            # ✅ FIX: Qt.Checked = 2, Qt.Unchecked = 0
            is_visible = (state == Qt.CheckState.Checked.value) or (state == 2)
            
            print(f"\n🔘 Checkbox changed: state={state}, is_visible={is_visible}")
            
            # Find the parent MultiDXFAttachmentDialog
            parent_dialog = self.parent()
            while parent_dialog and not isinstance(parent_dialog, MultiDXFAttachmentDialog):
                parent_dialog = parent_dialog.parent()
            
            if not parent_dialog or not hasattr(parent_dialog.app, 'dxf_actors'):
                print(f"  ⚠️ Cannot find dxf_actors")
                return
            
            # Find actors for this specific DXF file
            import os
            target_name = os.path.basename(str(self.dxf_path))
            
            actors_updated = 0
            
            # METHOD 1: Toggle via actor_cache (if available - respects layer filtering)
            if hasattr(self, 'actor_cache') and self.actor_cache:
                print(f"  🔍 Using actor_cache (layer-aware)")
                for layer_name, actors in self.actor_cache.items():
                    # Check if this layer should be visible based on layer selection
                    layer_should_be_visible = True
                    if self.selected_layers is not None:  # None means all layers
                        layer_should_be_visible = (layer_name in self.selected_layers)
                    
                    # Apply visibility: checkbox AND layer filter
                    final_visibility = is_visible and layer_should_be_visible
                    
                    for actor in actors:
                        actor.SetVisibility(1 if final_visibility else 0)
                        actors_updated += 1
                
                print(f"  ✅ DXF '{target_name}': {'VISIBLE' if is_visible else 'HIDDEN'} ({actors_updated} actors via actor_cache)")
            
            # METHOD 2: Fallback to dxf_actors list (if actor_cache not populated yet)
            else:
                print(f"  🔍 Using dxf_actors list (global)")
                for dxf_data in parent_dialog.app.dxf_actors:
                    stored_name = os.path.basename(str(dxf_data.get('filename', '')))
                    
                    if stored_name == target_name:
                        # Toggle visibility of all actors for this file
                        for actor in dxf_data.get('actors', []):
                            actor.SetVisibility(1 if is_visible else 0)  # VTK uses 1/0
                            actors_updated += 1
                        
                        print(f"  ✅ DXF '{target_name}': {'VISIBLE' if is_visible else 'HIDDEN'} ({actors_updated} actors)")
                        break
            
            if actors_updated == 0:
                print(f"  ⚠️ No actors found for '{target_name}'")
            
            # CRITICAL: Force render with multiple fallback methods
            rendered = False
            
            # Try method 1: Direct render window access
            if hasattr(parent_dialog.app, 'vtkwidget') and parent_dialog.app.vtkwidget:
                try:
                    render_window = parent_dialog.app.vtkwidget.GetRenderWindow()
                    if render_window:
                        render_window.Render()
                        print(f"  🔄 Display refreshed via GetRenderWindow()")
                        rendered = True
                except Exception as e:
                    print(f"  ⚠️ GetRenderWindow() failed: {e}")
            
            # Try method 2: Direct render() method
            if not rendered and hasattr(parent_dialog.app, 'vtkwidget'):
                try:
                    parent_dialog.app.vtkwidget.render()
                    print(f"  🔄 Display refreshed via render()")
                    rendered = True
                except Exception as e:
                    print(f"  ⚠️ render() method failed: {e}")
            
            # Try method 3: Renderer refresh
            if not rendered and hasattr(parent_dialog.app, 'vtkwidget'):
                try:
                    renderer = parent_dialog.app.vtkwidget.renderer
                    if renderer:
                        renderer.GetRenderWindow().Render()
                        print(f"  🔄 Display refreshed via renderer")
                        rendered = True
                except Exception as e:
                    print(f"  ⚠️ Renderer refresh failed: {e}")
            
            if not rendered:
                print(f"  ⚠️ Could not refresh display - no valid render method found")
            
        except Exception as e:
            print(f"  ⚠️ Checkbox toggle failed: {e}")
            import traceback
            traceback.print_exc()

    
    def set_crs(self, crs):
        """Store the parsed CRS"""
        self.dxf_crs = crs

    def open_display_options(self):
        """Open per-file display options dialog and store result."""
        dlg = DXFDisplayOptionsDialog(
            self,
            mode=self.display_mode,
            override_enabled=self.override_enabled,
            override_color=self.override_color,
        )
        if dlg.exec() == QDialog.Accepted:
            old_mode = self.display_mode
            
            mode, ov_enabled, ov_color = dlg.get_values()
            self.display_mode = mode
            self.override_enabled = ov_enabled
            self.override_color = ov_color
            
            # ✅ INSTANT UPDATE: Apply changes to actors
            print(f"\n⚡ INSTANT: Updating display options")
            
            for layer_name, actors in self.actor_cache.items():
                for actor in actors:
                    # Update color
                    if ov_enabled:
                        actor.GetProperty().SetColor([c/255.0 for c in ov_color])
                    elif hasattr(actor, '_original_color'):
                        actor.GetProperty().SetColor([c/255.0 for c in actor._original_color])
                    
                    # Update opacity if mode changed
                    if old_mode != mode:
                        opacity = 0.5 if mode == 'underlay' else 1.0
                        actor.GetProperty().SetOpacity(opacity)
            
            # Refresh display ONCE
            parent_dialog = self.parent()
            while parent_dialog and not isinstance(parent_dialog, MultiDXFAttachmentDialog):
                parent_dialog = parent_dialog.parent()
            
            if parent_dialog and hasattr(parent_dialog.app, 'vtk_widget'):
                render_window = parent_dialog.app.vtk_widget.GetRenderWindow()
                if render_window:
                    render_window.Render()
            
            print(f"  ✅ Done instantly!")
            
    # def open_layer_selection(self):
    #     """Open layer/level selection dialog"""
    #     try:
    #         dlg = DXFLayerSelectionDialog(self.dxf_path, self) 
    #         if dlg.exec() == QDialog.Accepted:
    #             selected = dlg.get_selected_layers()
                
    #             # ✅ FIX: Check if selection is empty or all layers
    #             total_layers = dlg.layer_list.count()
                
    #             if len(selected) == 0:
    #                 # No layers selected - treat as "All Off" (show nothing)
    #                 self.selected_layers = set()  # Empty set = show nothing
    #                 self.count_label.setText(f"{self.entity_count} entities | 0 layers ✓")
    #                 self.count_label.setStyleSheet(f"color:{ThemeColors.get('danger')}; font-size:7px; font-weight:bold;")
    #                 print(f"📋 DXF '{self.dxf_path.name}' → 0 layers selected (nothing will show)")
    #             elif len(selected) == total_layers:
    #                 # All layers selected - optimize by setting None
    #                 self.selected_layers = None  # None = show all (no filtering)
    #                 self.count_label.setText(f"{self.entity_count} entities")
    #                 self.count_label.setStyleSheet(f"color:{ThemeColors.get('accent')}; font-size:7px; font-weight:bold;")
    #                 print(f"📋 DXF '{self.dxf_path.name}' → All {total_layers} layers selected")
    #             else:
    #                 # Some layers selected - store the set
    #                 self.selected_layers = selected
    #                 layer_count = len(selected)
    #                 self.count_label.setText(f"{self.entity_count} entities | {layer_count} layers ✓")
    #                 self.count_label.setStyleSheet(f"color:{ThemeColors.get('text_secondary')}; font-size:7px; font-weight:bold;")
    #                 print(f"📋 DXF '{self.dxf_path.name}' → {layer_count} of {total_layers} layers selected")
                
    #             # Clear cached entities since layer selection changed
    #             print(f"\n⚡ INSTANT: Updating layer visibility")
                
    #             all_layers = set(self.entity_layers.values()) if self.entity_layers else set()
                
    #             if self.selected_layers is None:
    #                 # Show all layers
    #                 for layer_name, actors in self.actor_cache.items():
    #                     for actor in actors:
    #                         actor.SetVisibility(True)
    #             else:
    #                 # Show only selected layers
    #                 for layer_name, actors in self.actor_cache.items():
    #                     visible = layer_name in self.selected_layers
    #                     for actor in actors:
    #                         actor.SetVisibility(visible)
                
    #             # Refresh display ONCE
    #             parent_dialog = self.parent()
    #             while parent_dialog and not isinstance(parent_dialog, MultiDXFAttachmentDialog):
    #                 parent_dialog = parent_dialog.parent()
                
    #             if parent_dialog and hasattr(parent_dialog.app, 'vtk_widget'):
    #                 render_window = parent_dialog.app.vtk_widget.GetRenderWindow()
    #                 if render_window:
    #                     render_window.Render()
                
    #             print(f"  ✅ Done instantly!")
                
    #     except Exception as e:
    #         print(f"⚠️ Layer selection failed: {e}")
    #         import traceback
    #         traceback.print_exc()
    
    
    def open_layer_selection(self):
        """Open layer/level selection dialog"""
        try:
            dlg = DXFLayerSelectionDialog(self.dxf_path, self)
            if dlg.exec() == QDialog.Accepted:
                selected = dlg.get_selected_layers()
                
                total_layers = dlg.layer_list.count()
                
                if len(selected) == 0:
                    # No layers selected - hide everything
                    self.selected_layers = set()  # Empty set = show nothing
                    self.count_label.setText(f"{self.entity_count} entities (0 layers)")
                    self.count_label.setStyleSheet(f"color:{ThemeColors.get('danger')}; font-size:7px; font-weight:bold;")
                    print(f"📦 DXF '{self.dxf_path.name}': 0 layers selected - nothing will show")
                    
                elif len(selected) == total_layers:
                    # All layers selected - show everything
                    self.selected_layers = None  # None = show all (no filtering)
                    self.count_label.setText(f"{self.entity_count} entities")
                    self.count_label.setStyleSheet(f"color:{ThemeColors.get('accent')}; font-size:7px; font-weight:bold;")
                    print(f"📦 DXF '{self.dxf_path.name}': All {total_layers} layers selected")
                    
                else:
                    # Some layers selected
                    self.selected_layers = selected
                    layer_count = len(selected)
                    self.count_label.setText(f"{self.entity_count} entities ({layer_count} layers)")
                    self.count_label.setStyleSheet(f"color:{ThemeColors.get('text_secondary')}; font-size:7px; font-weight:bold;")
                    print(f"📦 DXF '{self.dxf_path.name}': {layer_count} of {total_layers} layers selected")
                
                # ⚡ INSTANT: Update layer visibility
                print(f"⚡ INSTANT: Updating layer visibility")
                
                # ✅ CHECK 1: Verify actor_cache exists
                if not hasattr(self, 'actor_cache') or not self.actor_cache:
                    print(f"  ⚠️ actor_cache is empty or missing!")
                    return
                
                print(f"  📊 actor_cache has {len(self.actor_cache)} layers")
                
                # ✅ NEW: Debug layer mismatch
                print(f"  🔍 DEBUG: Layer comparison")
                print(f"  📋 Layers in actor_cache: {list(self.actor_cache.keys())}")
                print(f"  ✅ Layers you selected: {self.selected_layers}")

                # Find missing layers
                if self.selected_layers:
                    missing = self.selected_layers - set(self.actor_cache.keys())
                    if missing:
                        print(f"  ⚠️ MISSING LAYERS (selected but not in cache): {missing}")

                
                # ✅ CHECK 2: Only apply if main checkbox is checked
                is_checked = self.checkbox.isChecked()
                print(f"  ☑️ Main checkbox is {'CHECKED' if is_checked else 'UNCHECKED'}")
                
                if not is_checked:
                    print(f"  ⚠️ Checkbox is unchecked - skipping visibility update")
                    return
                
                # ✅ CHECK 3: Apply layer filtering
                actors_updated = 0
                if self.selected_layers is None:
                    # Show all layers
                    print(f"  🔓 Showing ALL layers")
                    for layer_name, actors in self.actor_cache.items():
                        for actor in actors:
                            actor.SetVisibility(True)
                            actors_updated += 1
                else:
                    # Show only selected layers
                    print(f"  🔐 Showing SELECTED layers: {self.selected_layers}")
                    for layer_name, actors in self.actor_cache.items():
                        visible = (layer_name in self.selected_layers)
                        for actor in actors:
                            actor.SetVisibility(visible)
                            actors_updated += 1
                        
                        if visible:
                            print(f"    ✅ Layer '{layer_name}': VISIBLE ({len(actors)} actors)")
                        else:
                            print(f"    ❌ Layer '{layer_name}': HIDDEN ({len(actors)} actors)")
                
                print(f"  ✅ Updated {actors_updated} actors")
                
                # ✅ FORCE RENDER
                parent_dialog = self.parent()
                while parent_dialog and not isinstance(parent_dialog, MultiDXFAttachmentDialog):
                    parent_dialog = parent_dialog.parent()
                
                if parent_dialog and hasattr(parent_dialog.app, 'vtkwidget'):
                    render_window = parent_dialog.app.vtkwidget.GetRenderWindow()
                    if render_window:
                        render_window.Render()
                        print(f"  🔄 Display refreshed")
                
                print(f"  ✅ Done instantly!")
                
        except Exception as e:
            print(f"❌ Layer selection failed: {e}")
            import traceback
            traceback.print_exc()



class MultiDXFAttachmentDialog(QDialog):
    """
    Dialog for attaching multiple DXF files with automatic PRJ detection
    
    Features:
    - Select multiple DXF files at once
    - Auto-detect .PRJ file for each DXF
    - Manage attached DXFs (view list, remove individual files)
    - Coordinate reprojection support
    - Overlay/underlay modes
    """
    
    dxf_attached = Signal(list)  # Emits list of attachment data
    

    def __init__(self, app, parent=None):
        # ✅ FIX 1: Robust Parent Finding
        # Ensures we attach to the actual window widget so minimize works
        from PySide6.QtWidgets import QWidget
        target_parent = None
        
        # Try to find the valid parent widget
        if parent and isinstance(parent, QWidget):
            target_parent = parent
        elif isinstance(app, QWidget):
            target_parent = app
        elif hasattr(app, 'window') and isinstance(app.window, QWidget):
            target_parent = app.window

        # ✅ FIX 2: Use Qt.Window instead of Qt.Tool
        # - Qt.Window = Has Minimize/Maximize/Close buttons
        # - target_parent = Causes it to minimize when the software minimizes
        super().__init__(target_parent, Qt.Window)
        
        self.setWindowModality(Qt.NonModal)
        self.app = app
        self.setProperty("themeStyledDialog", True)
        
        self.dxf_items = []  # List of DXFFileItem widgets
        self.project_crs = None
        
        self.setWindowTitle("Attach Multiple DXF Files")
        self.setStyleSheet(get_dialog_stylesheet())
        self.setGeometry(150, 150, 700, 800)
        
        self.init_ui()
        # self.detect_project_crs()
    
    def init_ui(self):
        """Initialize the UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)
        
        # Title
        title = QLabel("Attach Multiple DXF Files")
        title.setStyleSheet(get_title_banner_style())
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        intro = QLabel(
            "Add one or more DXF overlays, review them in the list below, and attach the "
            "checked files to the active project."
        )
        intro.setStyleSheet(get_notice_banner_style("info"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        
        # Step 1: File Selection
        file_group = QGroupBox("Select DXF Files")
        file_layout = QVBoxLayout()
        
        select_btn = QPushButton("Browse and Add DXF Files...")
        select_btn.setObjectName("secondaryBtn")
        select_btn.setAutoDefault(False)
        select_btn.setDefault(False)
        select_btn.setFocusPolicy(Qt.NoFocus)
        select_btn.clicked.connect(self.select_dxf_files)
        file_layout.addWidget(select_btn)
        
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)
        
        # Step 2: Selected Files List
        list_group = QGroupBox("Selected DXF Files (Click X to remove)")
        list_layout = QVBoxLayout()
        
        # Scroll area for file items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        scroll.setMaximumHeight(300)
        
        self.file_list_widget = QWidget()
        self.file_list_layout = QVBoxLayout(self.file_list_widget)
        self.file_list_layout.setSpacing(5)
        self.file_list_layout.setContentsMargins(5, 5, 5, 5)
        self.file_list_layout.addStretch()
        
        scroll.setWidget(self.file_list_widget)
        list_layout.addWidget(scroll)
        
        # File count label
        self.file_count_label = QLabel("No files selected")
        self.file_count_label.setStyleSheet(f"color:{ThemeColors.get('text_muted')}; font-size:10px; padding:5px;")
        list_layout.addWidget(self.file_count_label)
        
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        # Action buttons
        button_row = QHBoxLayout()
        
        clear_btn = QPushButton("Clear All")
        clear_btn.setObjectName("dangerBtn")
        clear_btn.setAutoDefault(False)
        clear_btn.setDefault(False)
        clear_btn.setFocusPolicy(Qt.NoFocus)
        clear_btn.clicked.connect(self.clear_all_files)
        button_row.addWidget(clear_btn)
        
        button_row.addStretch()

        
        attach_btn = QPushButton("Attach All DXF Files")
        attach_btn.setObjectName("primaryBtn")
        attach_btn.setAutoDefault(False)
        attach_btn.setDefault(False)
        attach_btn.setFocusPolicy(Qt.NoFocus)
        attach_btn.clicked.connect(self.attach_all_dxf)
        button_row.addWidget(attach_btn)
        
        layout.addLayout(button_row)
   
    def select_dxf_files(self):
        """Open file dialog to select multiple DXF files"""
        if not DEPENDENCIES_AVAILABLE:
            QMessageBox.critical(
                self,
                "Missing Dependencies",
                "Required libraries not installed:\n\n"
                "pip install ezdxf pyproj"
            )
            return
        
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select DXF Files",
            "",
            "DXF Files (*.dxf);;All Files (*)"
        )
        
        if not file_paths:
            return
        
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QCoreApplication
        
        total_files = len(file_paths)
        
        # Create progress dialog
        if total_files == 1:
            # For single file: indeterminate progress (0-0 range = pulsing)
            progress = QProgressDialog(
                "Loading DXF file...",
                "Cancel",
                0,
                0,  # ✅ 0-0 range makes it indeterminate (pulsing)
                self
            )
        else:
            # For multiple files: regular progress bar
            progress = QProgressDialog(
                "Loading DXF files...",
                "Cancel",
                0,
                total_files,
                self
            )
        
        progress.setWindowTitle("Loading DXF Files")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setStyleSheet(get_progress_dialog_stylesheet())
        
        # Create worker thread
        self.load_worker = DXFLoadWorker(file_paths)
        
        # Connect signals
        def on_progress(value, message, is_indeterminate):
            progress.setLabelText(message)
            if not is_indeterminate:
                progress.setValue(value)
            # For indeterminate, don't set value (keeps it pulsing)
        
        def on_file_loaded(item_data, _):
            # Create UI item in main thread
            dxf_path = item_data['dxf_path']
            prj_exists = item_data['prj_exists']
            
            # Check if already added
            for item in self.dxf_items:
                if item.dxf_path == dxf_path:
                    return
            
            # Create item widget
            item = DXFFileItem(dxf_path, prj_exists)
            item.remove_requested.connect(self.remove_dxf_file)
            
            # Add to layout
            self.file_list_layout.insertWidget(len(self.dxf_items), item)
            self.dxf_items.append(item)
            
            # Set loaded data
            if 'dxf_doc' in item_data:
                item.cached_dxf_doc = item_data['dxf_doc']
                item.update_entity_count(item_data['entity_count'])
                if item_data.get('crs'):
                    item.set_crs(item_data['crs'])
                print(f"✅ Added: {dxf_path.name} (PRJ: {prj_exists})")
            elif 'error' in item_data:
                item.count_label.setText("Error")
                item.count_label.setStyleSheet(f"color:{ThemeColors.get('danger')}; font-size:9px;")
        
        def on_finished():
            if total_files > 1:
                progress.setValue(total_files)
            progress.close()
            self.update_file_count()
            print(f"✅ All {total_files} file(s) loaded")
        
        def on_error(error_msg):
            progress.close()
            QMessageBox.critical(self, "Loading Failed", error_msg)
        
        def on_canceled():
            if hasattr(self, 'load_worker') and self.load_worker.isRunning():
                self.load_worker.cancel()
                self.load_worker.wait(1000)
                if self.load_worker.isRunning():
                    self.load_worker.terminate()
                print("❌ Loading canceled by user")
        
        self.load_worker.progress.connect(on_progress)
        self.load_worker.file_loaded.connect(on_file_loaded)
        self.load_worker.finished.connect(on_finished)
        self.load_worker.error.connect(on_error)
        progress.canceled.connect(on_canceled)
        
        # Show dialog and start worker
        progress.show()
        QCoreApplication.processEvents()
        self.load_worker.start()
    
    
    def add_dxf_file(self, file_path, progress_callback=None):
        """Add a DXF file to the list"""
        dxf_path = Path(file_path)
        
        # Check if already added
        for item in self.dxf_items:
            if item.dxf_path == dxf_path:
                QMessageBox.information(self, "Already Added", f"{dxf_path.name} is already in the list")
                return
        
        # ❌ REMOVE THESE TWO LINES:
        # if progress_callback:
        #     progress_callback(f"📂 Reading {dxf_path.name}...")
        
        # ❌ REMOVE THIS LINE:
        # debug_dxf_contents(dxf_path)
        
        # Check for PRJ file
        prj_path = dxf_path.with_suffix('.prj')
        if not prj_path.exists():
            prj_path = dxf_path.with_suffix('.PRJ')
        prj_exists = prj_path.exists()
        
        # Create item widget
        item = DXFFileItem(dxf_path, prj_exists)
        item.remove_requested.connect(self.remove_dxf_file)
        
        # Add to layout (before the stretch)
        self.file_list_layout.insertWidget(len(self.dxf_items), item)
        self.dxf_items.append(item)
        
        # ❌ REMOVE THESE TWO LINES:
        # if progress_callback:
        #     progress_callback(f"⏳ Counting entities in {dxf_path.name}...")
        
        # Load DXF to get entity count and CRS
        self.load_dxf_info(item, prj_path if prj_exists else None)
        
        # ❌ REMOVE THIS LINE:
        # inspect_dxf_text_entities(dxf_path)
        
        print(f"✅ Added: {dxf_path.name} (PRJ: {prj_exists})")
        
    
    def load_dxf_info(self, item, prj_path):
        """
        ✅ Load DXF info synchronously with UI updates
        """
        try:
            from PySide6.QtCore import QCoreApplication
            
            # ✅ FORCE UI UPDATE BEFORE STARTING
            QCoreApplication.processEvents()
            
            # Show loading indicator on item
            item.count_label.setText("Loading...")
            item.count_label.setStyleSheet(f"color:{ThemeColors.get('warning')}; font-size:9px;")
            
            # ✅ FORCE UI UPDATE TO SHOW "Loading..."
            QCoreApplication.processEvents()
            
            # Load DXF - THIS IS THE BLOCKING OPERATION
            dxf_doc = ezdxf.readfile(str(item.dxf_path))
            
            # ✅ FORCE UI UPDATE AFTER LOADING FILE
            QCoreApplication.processEvents()
            
            # Count entities
            modelspace = dxf_doc.modelspace()
            entity_count = len(list(modelspace))
            
            # ✅ FORCE UI UPDATE AFTER COUNTING
            QCoreApplication.processEvents()
            
            # ✅ Cache the document for later use
            item.cached_dxf_doc = dxf_doc
            item.update_entity_count(entity_count)
            
            # ✅ FORCE UI UPDATE AFTER CACHING
            QCoreApplication.processEvents()
            
            # Parse PRJ if exists
            if prj_path:
                try:
                    with open(prj_path, 'r') as f:
                        prj_content = f.read().strip()
                    crs = CRS.from_wkt(prj_content)
                    item.set_crs(crs)
                    print(f"  ✅ CRS: {crs.name}")
                except Exception as e:
                    print(f"  ⚠️ PRJ parse failed: {e}")
            
            # ✅ FINAL UI UPDATE
            QCoreApplication.processEvents()
            
        except Exception as e:
            print(f"  ⚠️ DXF load failed: {e}")
            item.count_label.setText("Error")
            item.count_label.setStyleSheet("color: #f44336; font-size: 9px;")
            QCoreApplication.processEvents()

    def remove_dxf_file(self, item):
        """Remove a DXF file from the list and from VTK display"""
        if item in self.dxf_items:
            # Remove from UI list
            self.dxf_items.remove(item)
            self.file_list_layout.removeWidget(item)
            
            # Remove from VTK display
            self.remove_dxf_from_vtk(item.dxf_path.name)
            
            item.deleteLater()
            self.update_file_count()
            print(f"❌ Removed: {item.dxf_path.name}")
    
    
    def remove_dxf_from_vtk(self, filename):
        """Remove DXF actors from VTK renderer and detach from app lists."""
        import os
        try:
            if not hasattr(self.app, 'dxf_actors'):
                print("ℹ️ No dxf_actors list on app")
                return

            renderer = self.app.vtk_widget.renderer
            target_base = os.path.basename(str(filename))

            removed_groups = 0

            # 1) Remove actors & entries from app.dxf_actors
            for i in range(len(self.app.dxf_actors) - 1, -1, -1):
                dxf_data = self.app.dxf_actors[i]
                stored_name = os.path.basename(str(dxf_data.get('filename', '')))
                if stored_name == target_base:
                    # Remove all actors for this file
                    for actor in dxf_data.get('actors', []):
                        try:
                            renderer.RemoveActor(actor)
                        except Exception:
                            pass

                    self.app.dxf_actors.pop(i)
                    removed_groups += 1
                    print(f"  ✅ Removed {len(dxf_data.get('actors', []))} actors from display for '{target_base}'")

            # 2) Remove from dxf_attachments so it won't be re-added later
            if hasattr(self.app, 'dxf_attachments'):
                before = len(self.app.dxf_attachments)
                self.app.dxf_attachments = [
                    a for a in self.app.dxf_attachments
                    if os.path.basename(str(a.get('filename', ''))) != target_base
                ]
                after = len(self.app.dxf_attachments)
                if before != after:
                    print(f"  ✅ Removed {before - after} attachment record(s) for '{target_base}'")

            # 3) Refresh the display if anything changed
            if removed_groups:
                # ✅ SAFE: Check before rendering
                if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget:
                    render_window = self.app.vtk_widget.GetRenderWindow()
                    if render_window:
                        render_window.Render()
                print(f"  ✅ DXF '{target_base}' fully removed from main view ({removed_groups} group(s))")
            else:
                print(f"  ⚠️ No DXF actor group found for '{target_base}'")

        except Exception as e:
            print(f"  ⚠️ Failed to remove DXF '{filename}' from VTK: {e}")
            
            
    def refresh_dxf_display(self, item):
        """Refresh DXF display after layer selection changes"""
        try:
            print(f"\n🔄 Refreshing display for '{item.dxf_path.name}'...")
            
            # 1) Remove old actors from renderer
            self.remove_dxf_from_vtk(item.dxf_path.name)
            
            # 2) Clear cached entities so it will reprocess with new layers
            item.cached_entities = None
            
            # 3) Reprocess the DXF with new layer filter
            attachment_data = self.process_dxf_file(item)
            
            if not attachment_data:
                print(f"  ⚠️ No entities after filtering")
                return
            
            # 4) Update in app.dxf_attachments
            if hasattr(self.app, 'dxf_attachments'):
                # Remove old entry
                self.app.dxf_attachments = [
                    a for a in self.app.dxf_attachments
                    if a.get('filename') != item.dxf_path.name
                ]
                # Add new entry
                self.app.dxf_attachments.append(attachment_data)
            
            # 5) Render with new layer filter
            self.render_dxf_in_vtk(attachment_data)
            
            print(f"  ✅ Display refreshed with {len(attachment_data['entities'])} entities")
            
        except Exception as e:
            print(f"  ❌ Refresh failed: {e}")
            import traceback
            traceback.print_exc()       
        
    
    def clear_all_files(self):
        """Clear all DXF files and their cache"""
        if not self.dxf_items:
            return

        # Clear cache for all items
        for item in self.dxf_items:
            item.cached_dxf_doc = None
            item.cached_entities = None  # ✅ Clear cached entities
            item.checkbox.setChecked(False)

        self.update_file_count()
        print("🔘 All DXF files cleared (cache reset)")
    
    def update_file_count(self):
        """Update the file count label"""
        count = len(self.dxf_items)
        if count == 0:
            self.file_count_label.setText("No files selected")
            self.file_count_label.setStyleSheet(f"color:{ThemeColors.get('text_muted')}; font-size:10px; padding:5px;")
        else:
            total_entities = sum(item.entity_count for item in self.dxf_items)
            prj_count = sum(1 for item in self.dxf_items if item.prj_exists)
            self.file_count_label.setText(
                f"{count} file(s) selected | {total_entities} total entities | "
                f"{prj_count} with PRJ"
            )
            self.file_count_label.setStyleSheet(f"color:{ThemeColors.get('accent')}; font-size:10px; font-weight:bold; padding:5px;")
    
    def detect_project_crs(self):
        """Detect the project's coordinate system (silent detection)"""
        if hasattr(self.app, 'crs') and self.app.crs:
            self.project_crs = self.app.crs
            print(f"✅ Project CRS: {self.project_crs.name}")
        else:
            self.project_crs = None
            print("⚠️ Project CRS: Not detected")
    
    def attach_all_dxf(self):
        """
        ✅ ENHANCED: Auto-save current LAZ → Clear → Attach DXF → Load LAZ
        """
        from PySide6.QtWidgets import QProgressDialog, QMessageBox
        from PySide6.QtCore import Qt, QCoreApplication
        import os
        
        if not self.dxf_items:
            QMessageBox.warning(self, "No Files", "Please select DXF files first")
            return

        selected_items = [item for item in self.dxf_items if item.is_checked()]
        if not selected_items:
            QMessageBox.warning(
                self,
                "No Files Selected",
                "Please check at least one DXF file to attach."
            )
            return

        # ============================================================================
        # ✅ STEP 1: AUTO-SAVE CURRENT LAZ FILE (if exists)
        # ============================================================================
        print(f"\n{'='*60}")
        print(f"💾 AUTO-SAVING CURRENT FILE BEFORE DXF ATTACHMENT")
        print(f"{'='*60}")
        
        if hasattr(self.app, 'data') and self.app.data is not None:
            save_path = None
            
            # Determine save path
            if hasattr(self.app, 'last_save_path') and self.app.last_save_path:
                save_path = self.app.last_save_path
            elif hasattr(self.app, 'loaded_file') and self.app.loaded_file:
                save_path = self.app.loaded_file
            
            if save_path:
                try:
                    print(f"   Current file: {os.path.basename(save_path)}")
                    print(f"   Points: {len(self.app.data.get('xyz', [])):,}")
                    
                    from gui.save_pointcloud import save_pointcloud_quick
                    save_pointcloud_quick(self.app, save_path)
                    
                    print(f"✅ Current file saved successfully")
                    
                    if hasattr(self.app, "statusBar"):
                        self.app.statusBar().showMessage(f"💾 Saved: {os.path.basename(save_path)}", 2000)
                        QCoreApplication.processEvents()
                        
                except Exception as e:
                    print(f"⚠️ Failed to auto-save: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    reply = QMessageBox.warning(
                        self,
                        "Save Failed",
                        f"Failed to auto-save current file:\n\n{e}\n\n"
                        "Continue with DXF attachment anyway?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.No:
                        return
            else:
                print("ℹ️ No save path - data won't be saved")
        else:
            print("ℹ️ No current data to save")

        # ============================================================================
        # ✅ STEP 2: CONFIRMATION DIALOG
        # ============================================================================
        msg = f"Attach {len(selected_items)} DXF file(s)?\n\n"
        
        if hasattr(self.app, 'data') and self.app.data is not None:
            msg += "⚠️ Current point cloud will be CLEARED\n"
            msg += "✅ You can load LAZ files after DXF attachment\n\n"
        
        if self.project_crs:
            prj_count = sum(1 for item in selected_items if item.dxf_crs)
            msg += f"📐 {prj_count} file(s) will be reprojected to project CRS\n"
            msg += f"📐 {len(selected_items) - prj_count} without PRJ will use original coordinates"

        reply = QMessageBox.question(
            self,
            "Confirm DXF Attachment",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        # ============================================================================
        # ✅ STEP 3: CLEAR CURRENT POINT CLOUD (preserve nothing - DXF will be new)
        # ============================================================================
        print(f"\n🧹 CLEARING CURRENT PROJECT...")
        
        if hasattr(self.app, 'data') and self.app.data is not None:
            # Clear main viewer
            if hasattr(self.app, "vtk_widget") and self.app.vtk_widget:
                renderer = self.app.vtk_widget.renderer
                renderer.RemoveAllViewProps()
                
                if hasattr(self.app.vtk_widget, 'actors'):
                    self.app.vtk_widget.actors.clear()
                if hasattr(self.app.vtk_widget, '_actors'):
                    self.app.vtk_widget._actors.clear()
                
                self.app.vtk_widget.render()
                print(f"✅ Main viewer cleared")
            
            # Clear cross-section views
            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx, vtk_widget in self.app.section_vtks.items():
                    try:
                        vtk_widget.renderer.RemoveAllViewProps()
                        if hasattr(vtk_widget, 'actors'):
                            vtk_widget.actors.clear()
                        vtk_widget.render()
                    except:
                        pass
            
            # Clear internal state
            self.app.data = None
            self.app.loaded_file = None
            self.app.last_save_path = None
            self.app.class_palette = {}
            
            if hasattr(self.app, "view_palettes"):
                self.app.view_palettes.clear()
            
            # Clear DXF actors list (we're replacing them)
            if hasattr(self.app, 'dxf_actors'):
                self.app.dxf_actors.clear()
            
            if hasattr(self.app, 'dxf_attachments'):
                self.app.dxf_attachments.clear()
            
            print(f"✅ Project cleared\n")
            
            QCoreApplication.processEvents()

        # ============================================================================
        # ✅ STEP 4: ATTACH DXF FILES (process and render)
        # ============================================================================
        print(f"📎 ATTACHING {len(selected_items)} DXF FILE(S)...")
        
        # Show progress dialog
        progress = QProgressDialog(
            "Processing DXF files...", 
            "Cancel", 
            0, 
            len(selected_items) * 2,
            self
        )
        progress.setWindowTitle("Attaching DXF Files")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        progress.setStyleSheet(get_progress_dialog_stylesheet())
        progress.show()
        progress.forceShow()
        QCoreApplication.processEvents()
        
        try:
            all_attachments = []
            
            # Process all files
            for idx, item in enumerate(selected_items):
                if progress.wasCanceled():
                    return
                
                progress.setLabelText(f"Processing {item.dxf_path.name}...")
                progress.setValue(idx)
                QCoreApplication.processEvents()
                
                attachment_data = self.process_dxf_file(item)
                if attachment_data is not None:
                    # ✅ Store reference to item for actor caching
                    attachment_data['_dxf_item'] = item
                    all_attachments.append(attachment_data)
                if attachment_data is not None:
                    all_attachments.append(attachment_data)
                else:
                    print(f"  ⚠️ Failed to process {item.dxf_path.name}")

            if not all_attachments:
                progress.close()
                QMessageBox.information(
                    self,
                    "No Files Processed",
                    "Could not process any of the selected DXF files."
                )
                return

            # Initialize storage
            if not hasattr(self.app, 'dxf_attachments'):
                self.app.dxf_attachments = []
            if not hasattr(self.app, 'dxf_actors'):
                self.app.dxf_actors = []

            self.app.dxf_attachments.extend(all_attachments)
            self.dxf_attached.emit(all_attachments)

            # Render all files
            for idx, attachment_data in enumerate(all_attachments):
                if progress.wasCanceled():
                    return
                
                progress.setLabelText(f"Rendering {attachment_data['filename']}...")
                progress.setValue(len(selected_items) + idx)
                QCoreApplication.processEvents()
                
                self.render_dxf_in_vtk(attachment_data)

            progress.setValue(len(selected_items) * 2)
            progress.close()

            total_entities = sum(len(a['entities']) for a in all_attachments)
            files_with_geometry = sum(1 for a in all_attachments if len(a['entities']) > 0)
            files_without_geometry = len(all_attachments) - files_with_geometry

            msg = f"✅ Successfully attached {len(all_attachments)} DXF file(s)\n"
            msg += f"📊 Total: {total_entities} entities\n"
            if files_without_geometry > 0:
                msg += f"⚠️ {files_without_geometry} file(s) have no visible geometry\n"
            msg += f"\n💡 You can now load LAZ files for the grids"

            QMessageBox.information(self, "DXF Attached", msg)
            print(f"✅ Attached {len(all_attachments)} DXF files: {total_entities} entities")
            
            # Update window title
            self.app._update_window_title(f"DXF Grid ({len(all_attachments)} files)", None)

        except Exception as e:
            progress.close()
            QMessageBox.critical(
                self,
                "Attachment Failed",
                f"Failed to attach DXF files:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()

    def analyze_dxf_layers(self, dxf_path, dxf_doc):
        """Detailed analysis of what's in each layer"""
        print(f"\n🔬 DETAILED LAYER ANALYSIS: {dxf_path.name}")
        print("=" * 80)
        
        modelspace = dxf_doc.modelspace()
        
        # Collect stats by layer
        layer_data = {}
        
        for entity in modelspace:
            entity_type = entity.dxftype()
            layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else '0'
            
            if layer not in layer_data:
                layer_data[layer] = {}
            
            if entity_type not in layer_data[layer]:
                layer_data[layer][entity_type] = 0
            
            layer_data[layer][entity_type] += 1
        
        # Print layer breakdown
        for layer in sorted(layer_data.keys()):
            print(f"\n📁 Layer: '{layer}'")
            for entity_type in sorted(layer_data[layer].keys()):
                count = layer_data[layer][entity_type]
                print(f"   {entity_type:15s}: {count:5d}")
        
        print("=" * 80)
        
        
    def debug_insert_extraction(self, dxf_path, dxf_doc):
        """Debug: Show how many labels are being extracted from INSERT blocks"""
        print(f"\n{'='*80}")
        print(f"🔬 INSERT BLOCK EXTRACTION DEBUG")
        print(f"{'='*80}\n")
        
        modelspace = dxf_doc.modelspace()
        inserts = [e for e in modelspace if e.dxftype() == 'INSERT']
        
        print(f"Total INSERT blocks: {len(inserts)}")
        
        # Count extraction success
        labels_found = 0
        labels_failed = 0
        extraction_methods = {}
        
        for entity in inserts[:100]:  # Check first 100
            # Simulate extraction logic
            text_label = None
            method = "NONE"
            
            if hasattr(entity, 'attribs'):
                for idx, attrib in enumerate(entity.attribs):
                    if not hasattr(attrib.dxf, 'text'):
                        continue
                    
                    tag = attrib.dxf.tag if hasattr(attrib.dxf, 'tag') else 'NO_TAG'
                    attr_text = str(attrib.dxf.text).strip()
                    
                    skip_tags = {'LAYER', 'COLOR', 'LINETYPE', 'STYLE', 'LTYPE', 'WEIGHT'}
                    if tag.upper() in skip_tags or attr_text == 'FEATURE':
                        continue
                    
                    if attr_text and len(attr_text) >= 5:
                        if any(c.isdigit() for c in attr_text) or '_' in attr_text:
                            text_label = attr_text
                            method = f"ATTRIB_{tag}"
                            break
            
            if not text_label:
                block_name = entity.dxf.name
                if any(c.isdigit() for c in block_name) and len(block_name) >= 5:
                    text_label = block_name
                    method = "BLOCK_NAME"
            
            if text_label:
                labels_found += 1
                extraction_methods[method] = extraction_methods.get(method, 0) + 1
            else:
                labels_failed += 1
        
        print(f"\nSampled 100 blocks:")
        print(f"  ✅ Labels extracted: {labels_found}")
        print(f"  ❌ Labels failed: {labels_failed}")
        print(f"  Success rate: {labels_found/100*100:.1f}%")
        
        print(f"\nExtraction methods:")
        for method, count in sorted(extraction_methods.items(), key=lambda x: -x[1]):
            print(f"  {method}: {count}")
        
        # Extrapolate
        estimated_total = int((labels_found / 100) * len(inserts))
        print(f"\nEstimated total extractable labels: {estimated_total} / {len(inserts)}")
        print(f"{'='*80}\n")

    def process_dxf_file(self, item):
        """
        ✅ OPTIMIZED: Re-use cached DXF document
        Process geometry only once during attachment
        """
        try:
            # ✅ Check if we already processed this file
            if item.cached_entities:
                print(f"  ⚡ Using cached entities for {item.dxf_path.name}")
                return {
                    'filename': item.dxf_path.name,
                    'mode': item.display_mode,
                    'entities': item.cached_entities,
                    'dxf_crs': item.dxf_crs.to_wkt() if item.dxf_crs else None,
                    'project_crs': self.project_crs.to_wkt() if self.project_crs else None,
                    'transformed': item.dxf_crs is not None and self.project_crs is not None
                }
            
            # ✅ Use cached document if available
            if item.cached_dxf_doc:
                dxf_doc = item.cached_dxf_doc
            else:
                dxf_doc = ezdxf.readfile(str(item.dxf_path))
                item.cached_dxf_doc = dxf_doc
            modelspace = dxf_doc.modelspace()

            offset_x = 0.0
            offset_y = 0.0
            offset_z = 0.0

            color_override = None
            if getattr(item, "override_enabled", False):
                color_override = getattr(item, "override_color", (255, 0, 0))

            display_mode = getattr(item, "display_mode", "overlay")

            # Setup transformer if CRS available
            transformer = None
            if item.dxf_crs and self.project_crs:
                try:
                    transformer = Transformer.from_crs(
                        item.dxf_crs,
                        self.project_crs,
                        always_xy=True
                    )
                    print(f"  ✅ Transformer: {item.dxf_crs.name} → {self.project_crs.name}")
                except Exception as e:
                    print(f"  ⚠️ Transformer failed: {e}")

            processed_entities = []
            entity_type_counts = {}
            processed_type_counts = {}
            skipped_by_layer = 0
            failed_processing = 0

            # ✅ PRODUCTION: Direct iteration (no list(modelspace) copy)
            import time as _time
            t0 = _time.perf_counter()
            total = 0
            
            for entity in modelspace:
                total += 1
                entity_type = entity.dxftype()
                entity_type_counts[entity_type] = entity_type_counts.get(entity_type, 0) + 1
                
                # Layer filter
                if item.selected_layers is not None:
                    entity_layer = entity.dxf.layer if hasattr(entity.dxf, 'layer') else '0'
                    if len(item.selected_layers) > 0 and entity_layer not in item.selected_layers:
                        skipped_by_layer += 1
                        continue
                
                entity_data = self.process_entity(
                    entity, transformer, offset_x, offset_y, offset_z, color_override, dxf_doc
                )
                
                if entity_data:
                    if isinstance(entity_data, list):
                        processed_entities.extend(entity_data)
                        processed_type_counts[entity_type] = processed_type_counts.get(entity_type, 0) + len(entity_data)
                    else:
                        processed_entities.append(entity_data)
                        processed_type_counts[entity_type] = processed_type_counts.get(entity_type, 0) + 1
                else:
                    failed_processing += 1
            
            parse_ms = (_time.perf_counter() - t0) * 1000
            print(f"  ⚡ Parsed {total} entities → {len(processed_entities)} in {parse_ms:.0f}ms")

            # ✅ Cache processed entities for future use
            validated_entities = []
            skipped_empty_text = 0

            for entity in processed_entities:
                if entity['type'] == 'text':
                    # Validate text content
                    text = entity.get('text', '')
                    if not text or not isinstance(text, str) or len(str(text).strip()) == 0:
                        skipped_empty_text += 1
                        continue  # Skip this entity
                
                validated_entities.append(entity)

            if skipped_empty_text > 0:
                print(f"  🧹 Filtered out {skipped_empty_text} empty text entities")

            # ✅ Cache validated entities
            item.cache_dxf_data(dxf_doc, validated_entities)

            return {
                'filename': item.dxf_path.name,
                'mode': display_mode,
                'entities': validated_entities,
                'dxf_crs': item.dxf_crs.to_wkt() if item.dxf_crs else None,
                'project_crs': self.project_crs.to_wkt() if self.project_crs else None,
                'transformed': transformer is not None
            }

        except Exception as e:
            print(f"⚠️ Failed to process {item.dxf_path.name}: {e}")
            import traceback
            traceback.print_exc()
            return None


    
    def transform_block_point(self, point, insert_point, rotation, scale_x, scale_y, scale_z):
        """
        Transform a point from block coordinates to world coordinates
        
        Args:
            point: Point in block coordinate system [x, y, z]
            insert_point: Block insertion point [x, y, z]
            rotation: Rotation angle in degrees
            scale_x, scale_y, scale_z: Scale factors
        """
        import math
        
        pt = np.array(point)
        
        # Apply scale
        pt[0] *= scale_x
        pt[1] *= scale_y
        if len(pt) > 2:
            pt[2] *= scale_z
        
        # Apply rotation (around Z-axis)
        if rotation != 0:
            rad = math.radians(rotation)
            cos_r = math.cos(rad)
            sin_r = math.sin(rad)
            
            x_rot = pt[0] * cos_r - pt[1] * sin_r
            y_rot = pt[0] * sin_r + pt[1] * cos_r
            
            pt[0] = x_rot
            pt[1] = y_rot
        
        # Apply translation (insert point)
        pt[0] += insert_point[0]
        pt[1] += insert_point[1]
        if len(pt) > 2:
            pt[2] += insert_point[2]
        
        return pt
    
    
    def create_3dface_actor(self, entity):
        """
        Create VTK actor for 3DFACE (grid squares/polygons)
        Renders as crisp wireframe outline
        """
        import vtk
        
        points = vtk.vtkPoints()
        
        # Add all vertices
        for vertex in entity['vertices']:
            points.InsertNextPoint(vertex)
        
        # Create polygon or triangle
        if entity['is_triangle']:
            polygon = vtk.vtkTriangle()
            polygon.GetPointIds().SetId(0, 0)
            polygon.GetPointIds().SetId(1, 1)
            polygon.GetPointIds().SetId(2, 2)
        else:
            polygon = vtk.vtkQuad()
            polygon.GetPointIds().SetId(0, 0)
            polygon.GetPointIds().SetId(1, 1)
            polygon.GetPointIds().SetId(2, 2)
            polygon.GetPointIds().SetId(3, 3)
        
        polygons = vtk.vtkCellArray()
        polygons.InsertNextCell(polygon)
        
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetPolys(polygons)
        
        # ✅ Extract edges for wireframe rendering
        edges = vtk.vtkExtractEdges()
        edges.SetInputData(polydata)
        edges.Update()
        
        # Create mapper
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(edges.GetOutputPort())
        
        # ✅ CRITICAL: Proper Z-fighting prevention
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, -1)  # Changed from -2, -2
        
        # Create actor
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        
        # ✅ Set color
        actor.GetProperty().SetColor([c/255.0 for c in entity['color']])
        
        # ✅ ENHANCED: Better line visibility
        actor.GetProperty().SetLineWidth(2.0)  # Reduced from 3.0 for cleaner look
        actor.GetProperty().SetOpacity(1.0)
        
        # ✅ Lighting for better visibility
        actor.GetProperty().SetAmbient(0.5)  # Increased from 0.3
        actor.GetProperty().SetDiffuse(0.8)  # Increased from 0.7
        actor.GetProperty().SetSpecular(0.3)  # Add slight specular highlight
        
        # ✅ Ensure crisp rendering
        actor.GetProperty().SetRenderLinesAsTubes(False)  # Changed from True for sharper lines
        actor.GetProperty().EdgeVisibilityOn()
        
        return actor
   

    def process_entity(self, entity, transformer, offset_x, offset_y, offset_z, color_override, dxf_doc=None):
        """
        ✅ FIXED: Distinguishes between grid labels and feature labels by pattern
        """
        entity_data = None

        try:
            # === LINE ENTITY ===
            if entity.dxftype() == 'LINE':
                start = np.array(entity.dxf.start)
                end = np.array(entity.dxf.end)
                
                if transformer:
                    start[:2] = transformer.transform(start[0], start[1])
                    end[:2] = transformer.transform(end[0], end[1])
                
                start[0] += offset_x
                start[1] += offset_y
                if len(start) > 2:
                    start[2] += offset_z
                end[0] += offset_x
                end[1] += offset_y
                if len(end) > 2:
                    end[2] += offset_z
                
                entity_data = {
                    'type': 'line',
                    'start': start[:3].tolist(),
                    'end': end[:3].tolist(),
                    'color': color_override or self.get_entity_color(entity),
                    'layer': getattr(entity.dxf, 'layer', '0')
                }
            
            # === INSERT ENTITY (BLOCKS) ===
            elif entity.dxftype() == 'INSERT':
                if not dxf_doc:
                    print(f"  ⚠️ Cannot process INSERT without dxf_doc")
                    return None
                    
                try:
                    insert_point = np.array(entity.dxf.insert)
                    block_name = entity.dxf.name
                    
                    # ✅ Extract text label
                    # ✅ FIX: Extract text label with PRIORITY to grid-like patterns
                    text_label = None
                    extraction_method = "NONE"
                    candidate_labels = []  # ✅ Collect all candidates

                    if hasattr(entity, 'attribs'):
                        for idx, attrib in enumerate(entity.attribs):
                            if not hasattr(attrib.dxf, 'text'):
                                continue
                                
                            tag = attrib.dxf.tag if hasattr(attrib.dxf, 'tag') else 'NO_TAG'
                            attr_text = str(attrib.dxf.text).strip()
                            
                            # Skip metadata
                            skip_tags = {'LAYER', 'COLOR', 'LINETYPE', 'STYLE', 'LTYPE', 'WEIGHT'}
                            if tag.upper() in skip_tags or attr_text == 'FEATURE':
                                continue
                            
                            # Accept if looks like a label
                            if attr_text and len(attr_text) >= 5:
                                if any(char.isdigit() for char in attr_text) or '_' in attr_text:
                                    # ✅ Store candidate with priority score
                                    priority = 0
                                    
                                    # ✅ HIGH PRIORITY: Grid pattern like "DW2039017_000347"
                                    if attr_text.startswith('DW') and '_' in attr_text:
                                        priority = 100
                                    # ✅ MEDIUM PRIORITY: Contains underscore and digits
                                    elif '_' in attr_text and sum(c.isdigit() for c in attr_text) >= 3:
                                        priority = 50
                                    # ✅ LOW PRIORITY: Just has digits
                                    else:
                                        priority = 10
                                    
                                    candidate_labels.append({
                                        'text': attr_text,
                                        'method': f"ATTRIB[{idx}]:{tag}",
                                        'priority': priority
                                    })

                    # Select BEST candidate (highest priority)
                    if candidate_labels:
                        best = max(candidate_labels, key=lambda x: x['priority'])
                        text_label = best['text']
                        extraction_method = best['method']

                    # Fallback to block name
                    if not text_label and block_name:
                        if any(char.isdigit() for char in block_name) and len(block_name) >= 5:
                            text_label = block_name
                            extraction_method = "BLOCK_NAME"
                    
                    # Get transformation parameters
                    rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0.0
                    scale_x = entity.dxf.xscale if hasattr(entity.dxf, 'xscale') else 1.0
                    scale_y = entity.dxf.yscale if hasattr(entity.dxf, 'yscale') else 1.0
                    scale_z = entity.dxf.zscale if hasattr(entity.dxf, 'zscale') else 1.0
                    
                    # Transform insert point
                    if transformer:
                        insert_point[:2] = transformer.transform(insert_point[0], insert_point[1])
                    
                    insert_point[0] += offset_x
                    insert_point[1] += offset_y
                    if len(insert_point) > 2:
                        insert_point[2] += offset_z
                    
                    # Process block geometry
                    block_entities = []
                    
                    try:
                        block_layout = dxf_doc.blocks.get(block_name)
                        
                        for block_entity in block_layout:
                            block_entity_type = block_entity.dxftype()
                            
                            if block_entity_type == 'LINE':
                                start = np.array(block_entity.dxf.start)
                                end = np.array(block_entity.dxf.end)
                                
                                start_world = self.transform_block_point(
                                    start, insert_point, rotation, scale_x, scale_y, scale_z
                                )
                                end_world = self.transform_block_point(
                                    end, insert_point, rotation, scale_x, scale_y, scale_z
                                )
                                
                                block_entities.append({
                                    'type': 'line',
                                    'start': start_world[:3].tolist(),
                                    'end': end_world[:3].tolist(),
                                    'color': color_override or self.get_entity_color(block_entity),
                                     'layer': getattr(entity.dxf, 'layer', '0')
                                })
                            
                            elif block_entity_type == 'LWPOLYLINE':
                                points = []
                                for point in block_entity.get_points():
                                    pt = np.array(point)
                                    pt_world = self.transform_block_point(
                                        pt, insert_point, rotation, scale_x, scale_y, scale_z
                                    )
                                    points.append(pt_world[:3].tolist())
                                
                                if len(points) >= 2:
                                    block_entities.append({
                                        'type': 'polyline',
                                        'points': points,
                                        'closed': block_entity.is_closed if hasattr(block_entity, 'is_closed') else False,
                                        'color': color_override or self.get_entity_color(block_entity),
                                         'layer': getattr(entity.dxf, 'layer', '0')
                                    })
                            
                            elif block_entity_type == 'CIRCLE':
                                center = np.array(block_entity.dxf.center)
                                radius = block_entity.dxf.radius * scale_x
                                
                                center_world = self.transform_block_point(
                                    center, insert_point, rotation, scale_x, scale_y, scale_z
                                )
                                
                                block_entities.append({
                                    'type': 'circle',
                                    'center': center_world[:3].tolist(),
                                    'radius': radius,
                                    'color': color_override or self.get_entity_color(block_entity),
                                     'layer': getattr(entity.dxf, 'layer', '0')
                                })
                            
                            elif block_entity_type == 'ARC':
                                center = np.array(block_entity.dxf.center)
                                radius = block_entity.dxf.radius * scale_x
                                
                                center_world = self.transform_block_point(
                                    center, insert_point, rotation, scale_x, scale_y, scale_z
                                )
                                
                                block_entities.append({
                                    'type': 'arc',
                                    'center': center_world[:3].tolist(),
                                    'radius': radius,
                                    'start_angle': block_entity.dxf.start_angle + rotation,
                                    'end_angle': block_entity.dxf.end_angle + rotation,
                                    'color': color_override or self.get_entity_color(block_entity),
                                     'layer': getattr(entity.dxf, 'layer', '0')
                                })
                    
                    except Exception as e:
                        print(f"  ⚠️ Block geometry extraction failed: {e}")
                    
                    # Create result list
                    result_entities = []
                    result_entities.extend(block_entities)
                    
                    # ✅ Add text label with smart color selection
                    if text_label:
                        clean_text = str(text_label).strip()
                        
                        if clean_text and len(clean_text) > 0:
                            # ✅ SMART COLOR SELECTION based on label pattern
                            if 'DW' in clean_text.upper() and '_' in clean_text:
                                # Grid labels like "DW2039017_000347" → Keep cyan
                                label_color = (0, 255, 255)  # Cyan for grid IDs
                                label_height = 3.0  # Normal size
                            else:
                                # Feature labels like "FORNACE000015" → Yellow
                                label_color = (255, 255, 0)  # Yellow for feature names
                                label_height = 2.5  # Slightly smaller
                            
                            result_entities.append({
                                'type': 'text',
                                'text': clean_text,
                                'position': [insert_point[0], insert_point[1], insert_point[2]],
                                'height': label_height,
                                'rotation': rotation,
                                'color': label_color,
                                'extraction_method': extraction_method,
                                'layer': getattr(entity.dxf, 'layer', '0')
                            })
                        
                    return result_entities if result_entities else None
                    
                except Exception as e:
                    return None
            
            # === TEXT ENTITY ===
            elif entity.dxftype() in ('TEXT', 'MTEXT'):
                try:
                    text_content = entity.dxf.text if hasattr(entity.dxf, 'text') else ""
                    insert_point = np.array(entity.dxf.insert if hasattr(entity.dxf, 'insert') else [0, 0, 0])
                    height = entity.dxf.height if hasattr(entity.dxf, 'height') else 1.0
                    rotation = entity.dxf.rotation if hasattr(entity.dxf, 'rotation') else 0.0
                    entity.text_content = text_content  # ← Store text content
                    entity.is_grid_label = False    
                    
                    if transformer:
                        insert_point[:2] = transformer.transform(insert_point[0], insert_point[1])
                    
                    insert_point[0] += offset_x + 15.0 
                    insert_point[1] += offset_y - 2.5 
                    if len(insert_point) > 2:
                        insert_point[2] += offset_z

                    text_offset_x = height * 3
                    text_offset_y = height * 1

                    entity_data = {
                        'type': 'text',
                        'text': text_content,
                        'position': [insert_point[0] + text_offset_x,
                                    insert_point[1] + text_offset_y,
                                    insert_point[2]],
                        'height': height,
                        'rotation': rotation,
                        'color': color_override or self.get_entity_color(entity),
                        'layer': getattr(entity.dxf, 'layer', '0') 
                    }
                    entity_data['text_content'] = text_content  # ← ADD THIS LINE
                    entity_data['is_grid_label'] = False  # ← ADD THIS LINE
                except Exception as e:
                    print(f"  ⚠️ Text entity error: {e}")
                    return None
            
            # === POINT ENTITY ===
            elif entity.dxftype() == 'POINT':
                try:
                    location = np.array(entity.dxf.location)
                    
                    if transformer:
                        location[:2] = transformer.transform(location[0], location[1])
                    
                    location[0] += offset_x
                    location[1] += offset_y
                    if len(location) > 2:
                        location[2] += offset_z
                    
                    entity_data = {
                        'type': 'point',
                        'position': location[:3].tolist(),
                        'color': color_override or self.get_entity_color(entity),
                        'layer': getattr(entity.dxf, 'layer', '0')
                    }
                except Exception as e:
                    print(f"  ⚠️ Point entity error: {e}")
                    return None
            
            # === POLYLINE ENTITY ===
            elif entity.dxftype() in ('POLYLINE', 'LWPOLYLINE'):
                points = []
                
                if entity.dxftype() == 'LWPOLYLINE':
                    for point in entity.get_points():
                        pt = np.array(point)
                        if transformer:
                            pt[:2] = transformer.transform(pt[0], pt[1])
                        pt[0] += offset_x
                        pt[1] += offset_y
                        if len(pt) > 2:
                            pt[2] += offset_z
                        points.append(pt[:3].tolist())
                else:
                    for vertex in entity.vertices:
                        pt = np.array(vertex.dxf.location)
                        if transformer:
                            pt[:2] = transformer.transform(pt[0], pt[1])
                        pt[0] += offset_x
                        pt[1] += offset_y
                        if len(pt) > 2:
                            pt[2] += offset_z
                        points.append(pt[:3].tolist())
                
                if len(points) >= 2:
                    entity_data = {
                        'type': 'polyline',
                        'points': points,
                        'closed': entity.is_closed if hasattr(entity, 'is_closed') else False,
                        'color': color_override or self.get_entity_color(entity),
                         'layer': getattr(entity.dxf, 'layer', '0')  # ✅ ADD THIS LINE
                    }
            
            # === CIRCLE ENTITY ===
            elif entity.dxftype() == 'CIRCLE':
                center = np.array(entity.dxf.center)
                radius = entity.dxf.radius
                
                if transformer:
                    center[:2] = transformer.transform(center[0], center[1])
                
                center[0] += offset_x
                center[1] += offset_y
                if len(center) > 2:
                    center[2] += offset_z
                
                entity_data = {
                    'type': 'circle',
                    'center': center[:3].tolist(),
                    'radius': radius,
                    'color': color_override or self.get_entity_color(entity),
                    'layer': getattr(entity.dxf, 'layer', '0')
                }
            
            # === ARC ENTITY ===
            elif entity.dxftype() == 'ARC':
                center = np.array(entity.dxf.center)
                radius = entity.dxf.radius
                start_angle = entity.dxf.start_angle
                end_angle = entity.dxf.end_angle
                
                if transformer:
                    center[:2] = transformer.transform(center[0], center[1])
                
                center[0] += offset_x
                center[1] += offset_y
                if len(center) > 2:
                    center[2] += offset_z
                
                entity_data = {
                    'type': 'arc',
                    'center': center[:3].tolist(),
                    'radius': radius,
                    'start_angle': start_angle,
                    'end_angle': end_angle,
                    'color': color_override or self.get_entity_color(entity),
                    'layer': getattr(entity.dxf, 'layer', '0')
                }
            
            # === 3DFACE ENTITY (GRID SQUARES) ===
            elif entity.dxftype() == '3DFACE':
                try:
                    vtx0 = np.array(entity.dxf.vtx0) if hasattr(entity.dxf, 'vtx0') else np.array([0, 0, 0])
                    vtx1 = np.array(entity.dxf.vtx1) if hasattr(entity.dxf, 'vtx1') else np.array([0, 0, 0])
                    vtx2 = np.array(entity.dxf.vtx2) if hasattr(entity.dxf, 'vtx2') else np.array([0, 0, 0])
                    vtx3 = np.array(entity.dxf.vtx3) if hasattr(entity.dxf, 'vtx3') else vtx2
                    
                    vertices = []
                    for vtx in [vtx0, vtx1, vtx2, vtx3]:
                        if transformer:
                            vtx[:2] = transformer.transform(vtx[0], vtx[1])
                        vtx[0] += offset_x
                        vtx[1] += offset_y
                        if len(vtx) > 2:
                            vtx[2] += offset_z
                        vertices.append(vtx[:3].tolist())
                    
                    is_triangle = np.allclose(vtx2, vtx3, atol=1e-6)
                    
                    entity_data = {
                        'type': '3dface',
                        'vertices': vertices[:3] if is_triangle else vertices,
                        'is_triangle': is_triangle,
                        'color': color_override or self.get_entity_color(entity),
                         'layer': getattr(entity.dxf, 'layer', '0')
                    }
                    
                except Exception as e:
                    print(f"  ⚠️ 3DFACE entity error: {e}")
                    return None

        except Exception as e:
            print(f"  ⚠️ Entity processing error ({entity.dxftype()}): {e}")

        return entity_data


    def get_entity_color(self, entity):
        """Extract color from DXF entity"""
        try:
            color_index = entity.dxf.color
            if color_index == 256:  # BYLAYER
                return (255, 255, 255)
            aci_colors = {
                1: (255, 0, 0),    # Red
                2: (255, 255, 0),  # Yellow
                3: (0, 255, 0),    # Green
                4: (0, 255, 255),  # Cyan
                5: (0, 0, 255),    # Blue
                6: (255, 0, 255),  # Magenta
                7: (255, 255, 255) # White
            }
            return aci_colors.get(color_index, (255, 255, 255))
        except:
            return (255, 255, 255)
    
    def render_dxf_in_vtk(self, attachment_data):
        """
        ✅ MICROSTATION PRODUCTION: Batched rendering — ONE actor per (color, layer, type).
        Instead of 750 separate actors (one per entity), creates ~10-20 batched actors.
        This makes pan/zoom 50x faster because VTK iterates fewer actors per frame.
        """
        try:
            import vtk
            from collections import defaultdict
            import time
            t0 = time.perf_counter()
            
            if not hasattr(self.app, 'vtk_widget') or not self.app.vtk_widget:
                print(f"  ⚠️ VTK widget not ready - cannot render {attachment_data['filename']}")
                return
            
            renderer = self.app.vtk_widget.renderer
            actors = []
            
            if not attachment_data['entities']:
                print(f"  ℹ️ No entities to render for {attachment_data['filename']}")
                if not hasattr(self.app, 'dxf_actors'):
                    self.app.dxf_actors = []
                self.app.dxf_actors.append({
                    'filename': attachment_data['filename'],
                    'full_path': attachment_data.get('full_path'),
                    'actors': []
                })
                return
            
            # Count entity types for logging
            entity_type_counts = {}
            for entity in attachment_data['entities']:
                etype = entity['type']
                entity_type_counts[etype] = entity_type_counts.get(etype, 0) + 1
            
            print(f"\n📊 Rendering {attachment_data['filename']}:")
            for etype, count in sorted(entity_type_counts.items()):
                print(f"  {etype:15s}: {count:4d} entities")
            
            # Pause rendering during batch build
            render_window = self.app.vtk_widget.GetRenderWindow()
            if render_window:
                render_window.SetDesiredUpdateRate(0.0001)
            
            # ═══════════════════════════════════════════════════════════════
            # MICROSTATION BATCH: Group entities by (color, layer, type)
            # Each group becomes ONE VTK actor with merged geometry
            # ═══════════════════════════════════════════════════════════════
            line_groups = defaultdict(list)      # (color_tuple, layer) → [entity, ...]
            face_groups = defaultdict(list)      # (color_tuple, layer) → [entity, ...]
            circle_groups = defaultdict(list)    # (color_tuple, layer) → [entity, ...]
            text_entities = []                   # text rendered individually (3D labels)
            
            # Get DXF item for layer caching
            item = attachment_data.get('_dxf_item')
            
            for entity in attachment_data['entities']:
                etype = entity['type']
                color_key = tuple(entity.get('color', (255, 255, 255)))
                layer = entity.get('layer', '0')
                group_key = (color_key, layer)
                
                if etype == 'line':
                    line_groups[group_key].append(entity)
                elif etype == 'polyline':
                    line_groups[group_key].append(entity)
                elif etype == '3dface':
                    face_groups[group_key].append(entity)
                elif etype in ('circle', 'arc'):
                    circle_groups[group_key].append(entity)
                elif etype == 'text':
                    if entity.get('text') and len(str(entity['text']).strip()) > 0:
                        text_entities.append(entity)
                elif etype == 'point':
                    line_groups[group_key].append(entity)  # points go in line batch
            
            mode = attachment_data.get('mode', 'overlay')
            
            # ── BATCH 1: Lines + Polylines (ONE actor per color/layer group) ──
            for (color, layer_name), group in line_groups.items():
                appender = vtk.vtkAppendPolyData()
                
                for e in group:
                    pts = vtk.vtkPoints()
                    cells = vtk.vtkCellArray()
                    
                    if e['type'] == 'line':
                        pts.InsertNextPoint(e['start'])
                        pts.InsertNextPoint(e['end'])
                        line_cell = vtk.vtkLine()
                        line_cell.GetPointIds().SetId(0, 0)
                        line_cell.GetPointIds().SetId(1, 1)
                        cells.InsertNextCell(line_cell)
                        pd = vtk.vtkPolyData()
                        pd.SetPoints(pts)
                        pd.SetLines(cells)
                    elif e['type'] == 'polyline':
                        for i, pt in enumerate(e['points']):
                            pts.InsertNextPoint(pt)
                        pline = vtk.vtkPolyLine()
                        n = pts.GetNumberOfPoints()
                        pline.GetPointIds().SetNumberOfIds(n)
                        for i in range(n):
                            pline.GetPointIds().SetId(i, i)
                        cells.InsertNextCell(pline)
                        if e.get('closed', False) and n > 2:
                            close = vtk.vtkLine()
                            close.GetPointIds().SetId(0, n - 1)
                            close.GetPointIds().SetId(1, 0)
                            cells.InsertNextCell(close)
                        pd = vtk.vtkPolyData()
                        pd.SetPoints(pts)
                        pd.SetLines(cells)
                    elif e['type'] == 'point':
                        pts.InsertNextPoint(e.get('position', (0, 0, 0)))
                        verts = vtk.vtkCellArray()
                        verts.InsertNextCell(1)
                        verts.InsertCellPoint(0)
                        pd = vtk.vtkPolyData()
                        pd.SetPoints(pts)
                        pd.SetVerts(verts)
                    else:
                        continue
                    
                    appender.AddInputData(pd)
                
                appender.Update()
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputData(appender.GetOutput())
                mapper.SetResolveCoincidentTopologyToPolygonOffset()
                mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-1.0, -1.0)
                
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor([c / 255.0 for c in color])
                actor.GetProperty().SetLineWidth(2.0)
                actor.GetProperty().SetOpacity(1.0 if mode == 'overlay' else 0.6)
                actor.GetProperty().SetLighting(False)
                actor.GetProperty().SetAmbient(1.0)
                actor._original_color = color
                
                renderer.AddActor(actor)
                actors.append(actor)
                if item:
                    item.actor_cache.setdefault(layer_name, []).append(actor)
            
            # ── BATCH 2: 3DFACE wireframes (ONE actor per color/layer group) ──
            for (color, layer_name), group in face_groups.items():
                appender = vtk.vtkAppendPolyData()
                
                for e in group:
                    pts = vtk.vtkPoints()
                    for v in e['vertices']:
                        pts.InsertNextPoint(v)
                    
                    polys = vtk.vtkCellArray()
                    if e.get('is_triangle', False):
                        tri = vtk.vtkTriangle()
                        for i in range(3):
                            tri.GetPointIds().SetId(i, i)
                        polys.InsertNextCell(tri)
                    else:
                        quad = vtk.vtkQuad()
                        for i in range(4):
                            quad.GetPointIds().SetId(i, i)
                        polys.InsertNextCell(quad)
                    
                    pd = vtk.vtkPolyData()
                    pd.SetPoints(pts)
                    pd.SetPolys(polys)
                    appender.AddInputData(pd)
                
                appender.Update()
                
                # Extract edges for wireframe
                edges = vtk.vtkExtractEdges()
                edges.SetInputData(appender.GetOutput())
                edges.Update()
                
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(edges.GetOutputPort())
                mapper.SetResolveCoincidentTopologyToPolygonOffset()
                mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-1.0, -1.0)
                
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor([c / 255.0 for c in color])
                actor.GetProperty().SetLineWidth(2.0)
                actor.GetProperty().SetOpacity(1.0 if mode == 'overlay' else 0.6)
                actor.GetProperty().SetLighting(False)
                actor.GetProperty().SetAmbient(1.0)
                actor._original_color = color
                
                renderer.AddActor(actor)
                actors.append(actor)
                if item:
                    item.actor_cache.setdefault(layer_name, []).append(actor)
            
            # ── BATCH 3: Circles/Arcs (ONE actor per color/layer group) ──
            for (color, layer_name), group in circle_groups.items():
                appender = vtk.vtkAppendPolyData()
                
                for e in group:
                    if e['type'] == 'circle':
                        src = vtk.vtkRegularPolygonSource()
                        src.SetNumberOfSides(64)
                        src.SetRadius(e.get('radius', 1.0))
                        src.SetCenter(e.get('center', (0, 0, 0)))
                        src.SetGeneratePolygon(False)
                        src.SetGeneratePolyline(True)
                        src.Update()
                        appender.AddInputData(src.GetOutput())
                    elif e['type'] == 'arc':
                        arc = vtk.vtkArcSource()
                        arc.SetCenter(e.get('center', (0, 0, 0)))
                        arc.SetPoint1(e.get('start', (1, 0, 0)))
                        arc.SetPoint2(e.get('end', (0, 1, 0)))
                        arc.SetResolution(32)
                        arc.Update()
                        appender.AddInputData(arc.GetOutput())
                
                appender.Update()
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputData(appender.GetOutput())
                mapper.SetResolveCoincidentTopologyToPolygonOffset()
                mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-1.0, -1.0)
                
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor([c / 255.0 for c in color])
                actor.GetProperty().SetLineWidth(2.0)
                actor.GetProperty().SetOpacity(1.0 if mode == 'overlay' else 0.6)
                actor.GetProperty().SetLighting(False)
                actor.GetProperty().SetAmbient(1.0)
                actor._original_color = color
                
                renderer.AddActor(actor)
                actors.append(actor)
                if item:
                    item.actor_cache.setdefault(layer_name, []).append(actor)
            
            # ── TEXT (individual actors — typically few, need 3D positioning) ──
            for entity in text_entities:
                try:
                    actor = self.create_text_actor(entity)
                    if actor:
                        if actor.GetMapper():
                            actor.GetMapper().SetResolveCoincidentTopologyToPolygonOffset()
                            actor.GetMapper().SetRelativeCoincidentTopologyPolygonOffsetParameters(-20.0, -20.0)
                        actor.GetProperty().SetOpacity(1.0)
                        renderer.AddActor(actor)
                        actors.append(actor)
                        layer_name = entity.get('layer', '0')
                        if item:
                            item.actor_cache.setdefault(layer_name, []).append(actor)
                except Exception:
                    continue
            
            # ── Register actors ──
            if not hasattr(self.app, 'dxf_actors'):
                self.app.dxf_actors = []
            
            from pathlib import Path
            full_path = None
            for it in getattr(self, 'dxf_items', []):
                if it.dxf_path.name == attachment_data['filename']:
                    full_path = str(it.dxf_path.resolve())
                    break
            
            self.app.dxf_actors.append({
                'filename': attachment_data['filename'],
                'full_path': full_path,
                'actors': actors
            })
            
            # Re-enable rendering
            if render_window:
                render_window.SetDesiredUpdateRate(30.0)
                renderer.ResetCamera()
                renderer.ResetCameraClippingRange()
                renderer.GetActiveCamera().Zoom(0.85)
                render_window.Render()
            
            # Invalidate unified actor cache
            try:
                from gui.unified_actor_manager import invalidate_unified_actor, sync_palette_to_gpu
                invalidate_unified_actor(self.app)
                sync_palette_to_gpu(self.app, 0, render=False)
            except Exception:
                pass
            
            elapsed = (time.perf_counter() - t0) * 1000
            total_entities = sum(entity_type_counts.values())
            print(f"\n  ✅ BATCHED: {total_entities} entities → {len(actors)} actors in {elapsed:.0f}ms")
            print(f"  📊 Actor breakdown: {len(line_groups)} line groups, "
                  f"{len(face_groups)} face groups, {len(circle_groups)} circle groups, "
                  f"{len(text_entities)} text labels")
            
        except Exception as e:
            print(f"  ⚠️ VTK rendering failed: {e}")
            import traceback
            traceback.print_exc()
    
    
    def create_text_actor(self, entity):
        """Create VTK actor for text labels - ADAPTIVE SCALING based on grid context"""
        import vtk
        
        # ✅ EMERGENCY FIX: Validate text before creating VTK object
        text_content = entity.get('text', '')
        
        if not text_content or not isinstance(text_content, str):
            print(f"  ⚠️ Skipping invalid text entity: {entity}")
            return None
        
        text_content = str(text_content).strip()
        
        if len(text_content) == 0:
            print(f"  ⚠️ Skipping empty text entity")
            return None
        
        # ✅ Now safe to create VTK text
        text_source = vtk.vtkVectorText()
        text_source.SetText(text_content)
        text_source.Update()  # CRITICAL: Compute bounds before scaling
       
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(text_source.GetOutputPort())
       
        actor = vtk.vtkFollower()
        actor.SetMapper(mapper)
    
        actor.text_content = text_content  # ← Store text for later retrieval
        actor.is_grid_label = True  
       
        # Get actual text geometry bounds
        bounds = text_source.GetOutput().GetBounds()
        text_width = bounds[1] - bounds[0]   # X extent
        text_height = bounds[3] - bounds[2]  # Y extent
       
        # ADAPTIVE: Detect coordinate system scale from position magnitude
        # Text should be about 5-10% of typical grid cell width
        pos_magnitude = abs(entity['position'][0]) + abs(entity['position'][1])
       
        if pos_magnitude > 100000:  # Large coordinate system (e.g., UTM coordinates)
            desired_width = 80.0   # Increased to fit long block names
            desired_height = 20.0
        elif pos_magnitude > 10000:  # Medium coordinate system
            desired_width = 40.0   # Increased to fit long block names
            desired_height = 10.0
        elif pos_magnitude > 1000:  # Small coordinate system
            desired_width = 16.0   # Increased to fit long block names
            desired_height = 4.0
        else:  # Very small coordinate system
            desired_width = 4.0    # Increased to fit long block names
            desired_height = 1.0
       
        # Calculate scale factor to fit within bounding box
        if text_width > 0 and text_height > 0:
            scale_x = desired_width / text_width
            scale_y = desired_height / text_height
            scale_factor = min(scale_x, scale_y)  # Use minimum to ensure text fits
        else:
            scale_factor = 1.0
       
        # Apply uniform scaling
        actor.SetScale(scale_factor, scale_factor, scale_factor)
       
        # Set appearance
        actor.GetProperty().SetColor([c/255.0 for c in entity['color']])
        actor.GetProperty().SetLineWidth(3.0)
        actor.GetProperty().SetOpacity(1.0)
        actor.GetProperty().SetAmbient(0.6)
        actor.GetProperty().SetDiffuse(0.9)
       
        # Store grid label metadata
        actor.grid_name = entity['text']
        actor.is_grid_label = True
        actor.PickableOn()
       
        # Set camera for billboard effect
        try:
            if hasattr(self, 'app') and hasattr(self.app, 'vtk_widget'):
                actor.SetCamera(self.app.vtk_widget.renderer.GetActiveCamera())
                
        except:
            pass
        actor.SetPosition(entity['position']) 
       
        return actor
   

    def create_line_actor(self, entity):
        """Create VTK actor for line"""
        import vtk
        
        points = vtk.vtkPoints()
        points.InsertNextPoint(entity['start'])
        points.InsertNextPoint(entity['end'])
        
        line = vtk.vtkLine()
        line.GetPointIds().SetId(0, 0)
        line.GetPointIds().SetId(1, 1)
        
        lines = vtk.vtkCellArray()
        lines.InsertNextCell(line)
        
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetLines(lines)
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor([c/255.0 for c in entity['color']])
        actor.GetProperty().SetLineWidth(2)
        
        return actor
    
    def create_polyline_actor(self, entity):
        """
        ✅ ENHANCED: Better polyline rendering for grid lines
        """
        import vtk
        
        points = vtk.vtkPoints()
        points.SetNumberOfPoints(len(entity['points']))
        
        # Set all points
        for i, pt in enumerate(entity['points']):
            points.SetPoint(i, pt)
        
        # Create polyline
        polyline = vtk.vtkPolyLine()
        polyline.GetPointIds().SetNumberOfIds(len(entity['points']))
        for i in range(len(entity['points'])):
            polyline.GetPointIds().SetId(i, i)
        
        cells = vtk.vtkCellArray()
        cells.InsertNextCell(polyline)
        
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetLines(cells)
        
        # ✅ Add closed line if needed
        if entity.get('closed', False) and len(entity['points']) > 2:
            closing_line = vtk.vtkLine()
            closing_line.GetPointIds().SetId(0, len(entity['points']) - 1)
            closing_line.GetPointIds().SetId(1, 0)
            cells.InsertNextCell(closing_line)
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        
        # ✅ CRITICAL: Anti-aliasing for smooth lines
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(0, -1)
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        
        # ✅ Make lines VERY visible
        actor.GetProperty().SetColor([c/255.0 for c in entity['color']])
        actor.GetProperty().SetLineWidth(3.0)  # Thick lines
        actor.GetProperty().SetOpacity(1.0)
        actor.GetProperty().SetAmbient(0.6)
        actor.GetProperty().SetDiffuse(0.9)
        
        # ✅ Ensure lines render on top
        actor.GetProperty().SetRenderLinesAsTubes(True)
        
        return actor
        
    def create_circle_actor(self, entity):
        """Create VTK actor for circle"""
        import vtk
        
        polygon = vtk.vtkRegularPolygonSource()
        polygon.SetNumberOfSides(64)
        polygon.SetRadius(entity['radius'])
        polygon.SetCenter(entity['center'])
        polygon.GeneratePolygonOff()  # This makes it a circle outline, not filled
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(polygon.GetOutputPort())
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor([c/255.0 for c in entity['color']])
        
        # ✅ CRITICAL: Make circles much more visible
        actor.GetProperty().SetLineWidth(5.0)  # Increased from 2.0
        actor.GetProperty().SetOpacity(1.0)
        
        return actor
    
    def create_arc_actor(self, entity):
        """Create VTK actor for arc"""
        import vtk
        import math
        
        arc = vtk.vtkArcSource()
        arc.SetCenter(entity['center'])
        
        radius = entity['radius']
        start_rad = math.radians(entity['start_angle'])
        end_rad = math.radians(entity['end_angle'])
        
        start_pt = [
            entity['center'][0] + radius * math.cos(start_rad),
            entity['center'][1] + radius * math.sin(start_rad),
            entity['center'][2]
        ]
        end_pt = [
            entity['center'][0] + radius * math.cos(end_rad),
            entity['center'][1] + radius * math.sin(end_rad),
            entity['center'][2]
        ]
        
        arc.SetPoint1(start_pt)
        arc.SetPoint2(end_pt)
        arc.SetResolution(64)
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(arc.GetOutputPort())
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor([c/255.0 for c in entity['color']])
        actor.GetProperty().SetLineWidth(2)
        
        return actor
    
    def naksha_dark_theme(self):
        return """
        QWidget {
            background-color: #121212;
            color: #e0e0e0;
            font-family: "Segoe UI";
            font-size: 10pt;
        }
        QLabel { color: #e0e0e0; }
        QGroupBox {
            border: 1px solid #3a3a3a;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        QComboBox, QSpinBox, QDoubleSpinBox {
            background-color: #1e1e1e;
            border: 1px solid #3a3a3a;
            border-radius: 4px;
            padding: 5px;
            color: #eeeeee;
        }
        QPushButton {
            background-color: #333333;
            border: 1px solid #555555;
            border-radius: 5px;
            padding: 8px 12px;
            color: #dddddd;
        }
        QPushButton:hover {
            background-color: #444444;
            border-color: #007acc;
        }
        QRadioButton, QCheckBox {
            spacing: 6px;
            color: #cccccc;
        }
        QRadioButton::indicator, QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 2px solid #555555;
            background: #1e1e1e;
            border-radius: 8px;
        }
        QRadioButton::indicator:checked, QCheckBox::indicator:checked {
            background-color: #007acc;
            border-color: #007acc;
        }
        """

def debug_dxf_contents(dxf_path):
        """Debug: Show what entity types are in the DXF file"""
        try:
            import ezdxf
            print(f"\n🔍 DEBUG: Analyzing DXF file: {dxf_path}")
            
            dxf_doc = ezdxf.readfile(str(dxf_path))
            modelspace = dxf_doc.modelspace()
            
            # Count entity types
            entity_counts = {}
            text_samples = []
            
            for entity in modelspace:
                entity_type = entity.dxftype()
                entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
                
                # Collect text samples
                if entity_type in ('TEXT', 'MTEXT'):
                    text_content = entity.dxf.text if hasattr(entity.dxf, 'text') else "NO TEXT"
                    text_samples.append(text_content)
                    if len(text_samples) <= 5:  # Show first 5
                        print(f"  📝 Found TEXT: '{text_content}'")
            
            print(f"\n📊 Entity type summary:")
            for entity_type, count in sorted(entity_counts.items()):
                print(f"  {entity_type}: {count}")
            
            print(f"\n📝 Total TEXT/MTEXT entities: {entity_counts.get('TEXT', 0) + entity_counts.get('MTEXT', 0)}")
            
            if not text_samples:
                print("  ⚠️ WARNING: NO TEXT ENTITIES FOUND IN DXF!")
                print("  The grid labels might be in a different format (BLOCKS, ATTRIBUTES, etc.)")
            
        except Exception as e:
            print(f"❌ Debug failed: {e}")
            import traceback
            traceback.print_exc()

def show_multi_dxf_attachment_dialog(app):
    """Show the multi-DXF attachment dialog (persistent)"""
    
    # Reuse existing dialog if it exists
    if hasattr(app, '_dxf_dialog') and app._dxf_dialog is not None:
        try:
            app._dxf_dialog.show()
            app._dxf_dialog.raise_()
            app._dxf_dialog.activateWindow()
            return app._dxf_dialog
        except:
            pass
    
    # Create new dialog
    dialog = MultiDXFAttachmentDialog(app, parent=app)
    dialog.setModal(False)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    
    # Store reference
    app._dxf_dialog = dialog
    
    # Override close event to hide instead
    original_close = dialog.closeEvent
    def on_close(event):
        event.ignore()
        dialog.hide()
    dialog.closeEvent = on_close
    
    return dialog

# Backward compatibility
def show_dxf_attachment_dialog(app):
    return show_multi_dxf_attachment_dialog(app)

def inspect_dxf_text_entities(dxf_path):
        """Show first 20 text entities to verify content"""
        try:
            import ezdxf
            print(f"\n🔍 Inspecting TEXT entities in: {dxf_path}")
            
            dxf_doc = ezdxf.readfile(str(dxf_path))
            modelspace = dxf_doc.modelspace()
            
            text_count = 0
            for entity in modelspace:
                if entity.dxftype() in ('TEXT', 'MTEXT', 'INSERT'):
                    text_count += 1
                    
                    # Get text content
                    if entity.dxftype() == 'INSERT':
                        text = f"BLOCK: {entity.dxf.name}"
                        if hasattr(entity, 'attribs'):
                            for attrib in entity.attribs:
                                if hasattr(attrib.dxf, 'text'):
                                    text += f" | ATTRIB: {attrib.dxf.text}"
                    else:
                        text = entity.dxf.text if hasattr(entity.dxf, 'text') else "NO TEXT"
                    
                    position = entity.dxf.insert if hasattr(entity.dxf, 'insert') else entity.dxf.location
                    
                    if text_count <= 20:  # Show first 20
                        print(f"  [{text_count}] {entity.dxftype()}: '{text}' at {position[:2]}")
            
            print(f"\n📊 Total text entities: {text_count}")
            
        except Exception as e:
            print(f"❌ Inspection failed: {e}")
    
def debug_insert_blocks(dxf_path):
    """Debug: Show all INSERT blocks and their attributes"""
    try:
        import ezdxf
        print(f"\n🔍 DEBUG: Analyzing INSERT blocks in: {dxf_path}")
        
        dxf_doc = ezdxf.readfile(str(dxf_path))
        modelspace = dxf_doc.modelspace()
        
        insert_count = 0
        for entity in modelspace:
            if entity.dxftype() == 'INSERT':
                insert_count += 1
                print(f"\n📦 INSERT #{insert_count}:")
                print(f"   Block name: {entity.dxf.name}")
                print(f"   Position: {entity.dxf.insert}")
                
                if hasattr(entity, 'attribs'):
                    print(f"   Attributes ({len(entity.attribs)}):")
                    for idx, attrib in enumerate(entity.attribs):
                        tag = attrib.dxf.tag if hasattr(attrib.dxf, 'tag') else 'NO TAG'
                        text = attrib.dxf.text if hasattr(attrib.dxf, 'text') else 'NO TEXT'
                        print(f"     [{idx}] Tag: {tag}, Text: '{text}'")
                else:
                    print(f"   ⚠️ No attributes")
                
                # Check block definition
                try:
                    block = dxf_doc.blocks.get(entity.dxf.name)
                    print(f"   Block definition entities: {len(list(block))}")
                    for block_entity in block:
                        if block_entity.dxftype() in ('TEXT', 'MTEXT', 'ATTDEF'):
                            text = block_entity.dxf.text if hasattr(block_entity.dxf, 'text') else 'NO TEXT'
                            print(f"     - {block_entity.dxftype()}: '{text}'")
                except:
                    print(f"   ⚠️ Could not read block definition")
        
        print(f"\n📊 Total INSERT blocks: {insert_count}")
        
    except Exception as e:
        print(f"❌ Debug failed: {e}")
        import traceback
        traceback.print_exc()
        
        
        
        
        
class DXFLayerSelectionDialog(QDialog):
    """MicroStation-style layer/level selection dialog"""
    
    def __init__(self, dxf_path, parent_item=None):
        super().__init__(parent_item)
        self.dxf_path = dxf_path
        self.parent_item = parent_item  # Reference to DXFFileItem
        self.layer_items = {}
        self.selected_layers = set()
        
        self.setWindowTitle(f"Level Display - {Path(dxf_path).name}")
        self.setModal(True)
        self.resize(400, 600)
        
        self.init_ui()
        self.load_dxf_layers()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        self.setProperty("themeStyledDialog", True)
        self.setStyleSheet(get_dialog_stylesheet())
        
        # Title
        title = QLabel("Select Layers and Levels to Display")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        
        # Layer list
        list_label = QLabel("Layers:")
        list_label.setObjectName("dialogSectionLabel")
        layout.addWidget(list_label)
        
        self.layer_list = QListWidget()
        self.layer_list.setAlternatingRowColors(True)
        layout.addWidget(self.layer_list)
        
        # Quick actions
        action_row = QHBoxLayout()
        
        all_on_btn = QPushButton("All On")
        all_on_btn.setAutoDefault(False)
        all_on_btn.setDefault(False)
        all_on_btn.setFocusPolicy(Qt.NoFocus)
        all_on_btn.clicked.connect(self.select_all)
        action_row.addWidget(all_on_btn)
        
        all_off_btn = QPushButton("All Off")
        all_off_btn.setAutoDefault(False)
        all_off_btn.setDefault(False)
        all_off_btn.setFocusPolicy(Qt.NoFocus)
        all_off_btn.clicked.connect(self.deselect_all)
        action_row.addWidget(all_off_btn)
        
        invert_btn = QPushButton("Invert")
        invert_btn.setAutoDefault(False)
        invert_btn.setDefault(False)
        invert_btn.setFocusPolicy(Qt.NoFocus)
        invert_btn.clicked.connect(self.invert_selection)
        action_row.addWidget(invert_btn)
        
        layout.addLayout(action_row)
        
        # Dialog buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        
        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.setAutoDefault(False)
        ok_btn.setDefault(False)
        ok_btn.setFocusPolicy(Qt.NoFocus)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        cancel_btn.setFocusPolicy(Qt.NoFocus)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        
        layout.addLayout(btn_row)
    
    def load_dxf_layers(self):
        """Load layers/levels from DXF file - OPTIMIZED to use cache"""
        try:
            import ezdxf
            
            # ✅ OPTIMIZATION: Use cached DXF doc if available
            if self.parent_item and hasattr(self.parent_item, 'cached_dxf_doc') and self.parent_item.cached_dxf_doc:
                print(f"✅ Using cached DXF doc (instant load)")
                dxf_doc = self.parent_item.cached_dxf_doc
            else:
                print(f"⏳ Loading DXF from disk (slower)...")
                dxf_doc = ezdxf.readfile(str(self.dxf_path))
                
                # Cache it for next time
                if self.parent_item:
                    self.parent_item.cached_dxf_doc = dxf_doc
            
            modelspace = dxf_doc.modelspace()
            
            # Collect all unique layers
            layer_stats = {}
            for entity in modelspace:
                layer_name = entity.dxf.layer if hasattr(entity.dxf, 'layer') else '0'
                
                if layer_name not in layer_stats:
                    layer_stats[layer_name] = {'count': 0, 'types': set()}
                
                layer_stats[layer_name]['count'] += 1
                layer_stats[layer_name]['types'].add(entity.dxftype)
            
            # Sort layers alphabetically
            sorted_layers = sorted(layer_stats.keys())
            
            # Get current selection from parent item
            current_selection = getattr(self.parent_item, 'selected_layers', None)
            
            # Add to list widget
            for layer_name in sorted_layers:
                stats = layer_stats[layer_name]
                item = QListWidgetItem()
                item.setText(f"{layer_name} ({stats['count']} entities)")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                
                # Restore previous selection state
                if current_selection is None:
                    # None means all layers (default)
                    item.setCheckState(Qt.Checked)
                    self.selected_layers.add(layer_name)
                elif len(current_selection) == 0:
                    # Empty set means nothing selected
                    item.setCheckState(Qt.Unchecked)
                elif layer_name in current_selection:
                    # Layer is in the selected set
                    item.setCheckState(Qt.Checked)
                    self.selected_layers.add(layer_name)
                else:
                    # Layer is not selected
                    item.setCheckState(Qt.Unchecked)
                
                item.setData(Qt.UserRole, layer_name)
                
                # Color code by entity count
                if stats['count'] > 100:
                    item.setForeground(QColor('#4caf50'))  # Green
                elif stats['count'] > 10:
                    item.setForeground(QColor('#2196f3'))  # Blue
                else:
                    item.setForeground(QColor('#888888'))  # Gray
                
                self.layer_list.addItem(item)
                self.layer_items[layer_name] = item
            
            print(f"✅ Loaded {len(layer_stats)} layers")
            
        except Exception as e:
            print(f"❌ Failed to load layers: {e}")
            import traceback
            traceback.print_exc()

    
    def select_all(self):
        """Select all layers"""
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            item.setCheckState(Qt.Checked)
        self.update_selection()
    
    def deselect_all(self):
        """Deselect all layers"""
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            item.setCheckState(Qt.Unchecked)
        self.update_selection()
    
    def invert_selection(self):
        """Invert layer selection"""
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            item.setCheckState(
                Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
            )
        self.update_selection()
    
    def update_selection(self):
        """Update selected layers set"""
        self.selected_layers.clear()
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if item.checkState() == Qt.Checked:
                layer_name = item.data(Qt.UserRole)
                self.selected_layers.add(layer_name)
    
    def get_selected_layers(self):
        """Get set of selected layer names"""
        self.update_selection()
        return self.selected_layers


class DXFDisplayOptionsDialog(QDialog):
    """Per-file display options (overlay / underlay + color override)."""

    def __init__(self, parent=None, mode="overlay", override_enabled=False, override_color=(255, 0, 0)):
        super().__init__(parent)
        self.setWindowTitle("DXF Display Options")
        self.setModal(True)
        self.resize(260, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Mode
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Display Mode:"))
        self.overlay_radio = QRadioButton("Overlay (on top)")
        self.underlay_radio = QRadioButton("Underlay (below)")
        if mode == "underlay":
            self.underlay_radio.setChecked(True)
        else:
            self.overlay_radio.setChecked(True)
        mode_row.addWidget(self.overlay_radio)
        mode_row.addWidget(self.underlay_radio)
        layout.addLayout(mode_row)

        # Color override
        color_row = QHBoxLayout()
        self.color_override_check = QCheckBox("Override color:")
        self.color_combo = QComboBox()
        self.color_combo.addItem("Red",    QColor(255, 0, 0))
        self.color_combo.addItem("Green",  QColor(0, 255, 0))
        self.color_combo.addItem("Blue",   QColor(0, 0, 255))
        self.color_combo.addItem("Yellow", QColor(255, 255, 0))
        self.color_combo.addItem("Cyan",   QColor(0, 255, 255))
        self.color_combo.addItem("Magenta",QColor(255, 0, 255))
        self.color_combo.addItem("White",  QColor(255, 255, 255))

        self.color_override_check.setChecked(override_enabled)
        self.color_combo.setEnabled(override_enabled)
        self.color_override_check.toggled.connect(self.color_combo.setEnabled)

        # Select initial color
        for i in range(self.color_combo.count()):
            q = self.color_combo.itemData(i)
            if (q.red(), q.green(), q.blue()) == override_color:
                self.color_combo.setCurrentIndex(i)
                break

        color_row.addWidget(self.color_override_check)
        color_row.addWidget(self.color_combo)
        layout.addLayout(color_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def get_values(self):
        mode = "underlay" if self.underlay_radio.isChecked() else "overlay"
        override_enabled = self.color_override_check.isChecked()
        qcolor = self.color_combo.currentData()
        override_color = (qcolor.red(), qcolor.green(), qcolor.blue())
        return mode, override_enabled, override_color
    
    
class DXFLoadWorker(QThread):
    """Background thread for loading DXF files one at a time"""
    progress = Signal(int, str, bool)  # (current_value, status_message, is_indeterminate)
    file_loaded = Signal(object, object)  # (item_data, None)
    finished = Signal()
    error = Signal(str)
    
    def __init__(self, file_paths):
        super().__init__()
        self.file_paths = file_paths
        self._is_cancelled = False
    
    def cancel(self):
        self._is_cancelled = True
    
    def run(self):
        """Load files in background"""
        try:
            import ezdxf
            from pyproj import CRS
            
            total_files = len(self.file_paths)
            
            for idx, file_path in enumerate(self.file_paths):
                if self._is_cancelled:
                    return
                
                dxf_path = Path(file_path)
                filename = dxf_path.name
                
                # For single file: use indeterminate progress
                # For multiple files: use regular progress
                if total_files == 1:
                    # Indeterminate progress (pulsing bar)
                    self.progress.emit(0, f"📂 Reading {filename}...", True)
                else:
                    # Regular progress
                    self.progress.emit(idx, f"📂 Loading {filename}... ({idx + 1}/{total_files})", False)
                
                # Check for PRJ file
                prj_path = dxf_path.with_suffix('.prj')
                if not prj_path.exists():
                    prj_path = dxf_path.with_suffix('.PRJ')
                prj_exists = prj_path.exists()
                
                item_data = {
                    'dxf_path': dxf_path,
                    'prj_exists': prj_exists,
                    'prj_path': prj_path if prj_exists else None
                }
                
                try:
                    # ✅ Show "Reading file..." for single file
                    if total_files == 1:
                        self.progress.emit(0, f"📂 Reading {filename}...", True)
                    
                    # Load DXF
                    dxf_doc = ezdxf.readfile(str(dxf_path))
                    
                    # ✅ Show "Counting entities..." for single file
                    if total_files == 1:
                        self.progress.emit(0, f"⏳ Counting entities in {filename}...", True)
                    
                    modelspace = dxf_doc.modelspace()
                    entity_count = len(list(modelspace))
                    
                    item_data['dxf_doc'] = dxf_doc
                    item_data['entity_count'] = entity_count
                    
                    # ✅ Show "Parsing CRS..." for single file
                    if total_files == 1 and prj_exists:
                        self.progress.emit(0, f"🗺️ Parsing coordinate system...", True)
                    
                    # Parse PRJ if exists
                    if prj_exists:
                        try:
                            with open(prj_path, 'r') as f:
                                prj_content = f.read().strip()
                            crs = CRS.from_wkt(prj_content)
                            item_data['crs'] = crs
                        except Exception as e:
                            print(f"  ⚠️ PRJ parse failed: {e}")
                            item_data['crs'] = None
                    else:
                        item_data['crs'] = None
                    
                    self.file_loaded.emit(item_data, None)
                    
                except Exception as e:
                    print(f"  ⚠️ Failed to load {filename}: {e}")
                    item_data['error'] = str(e)
                    self.file_loaded.emit(item_data, None)
            
            self.finished.emit()
            
        except Exception as e:
            self.error.emit(f"Loading failed: {str(e)}")
