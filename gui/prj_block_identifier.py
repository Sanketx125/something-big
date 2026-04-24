
"""
PRJ Block Identifier Dialog
Loads PRJ file and allows identification/highlighting of DXF blocks
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QTableWidget, QTableWidgetItem, QFileDialog, 
                               QLabel, QMessageBox, QHeaderView)
from PySide6.QtCore import Qt
import os
from PySide6.QtGui import QColor
from pathlib import Path
from gui.theme_manager import (
    get_dialog_stylesheet,
    get_title_banner_style,
    get_notice_banner_style,
)

class PRJBlockIdentifierDialog(QDialog):
    """Dialog to load PRJ file and identify DXF blocks"""
    
    # def __init__(self, app, parent=None):
    #     # super().__init__(parent)
    #     # self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
    #     super().__init__(parent, Qt.Tool)
    #     self.app = app
    #     self.prj_data = []
    #     self.current_dxf_path = None
    #     self.current_prj_path = None 
        
    #     self.setWindowTitle("🔍 PRJ Block Identifier")
    #     self.setMinimumSize(800, 600)
    #     self._apply_dark_theme()
    #     self.setup_ui()
    #     self.detect_current_dxf()
    #     self.current_directory = None 

    def __init__(self, app, parent=None):
        # ✅ FIX: Ensure parent is valid (Main Window)
        from PySide6.QtWidgets import QWidget
        if parent is None:
            if isinstance(app, QWidget):
                parent = app
            elif hasattr(app, 'window') and isinstance(app.window, QWidget):
                parent = app.window

        # ✅ FIX: Use Qt.Window flag
        # This enables the Minimize button while keeping the window attached to the app.
        super().__init__(parent, Qt.Window)
        
        self.app = app
        self.prj_data = []
        self.current_dxf_path = None
        self.current_prj_path = None
        self.setProperty("themeStyledDialog", True)

        self.setWindowTitle("PRJ Block Identifier")
        self.setMinimumSize(400, 300)
        self.resize(800, 600)
        self._apply_dark_theme()
        self.setup_ui()
        self.detect_current_dxf()
        self.current_directory = None
      
    def _apply_dark_theme(self):
            """Apply the shared application dialog theme."""
            self.setStyleSheet(get_dialog_stylesheet())
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("PRJ Block Identifier")
        title.setStyleSheet(get_title_banner_style())
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(title)

        intro = QLabel(
            "Load a PRJ file, review detected blocks, and identify matching regions "
            "inside the currently loaded DXF data."
        )
        intro.setStyleSheet(get_notice_banner_style("info"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        
        # Header with file info
        header = QHBoxLayout()
        self.dxf_label = QLabel("No PRJ loaded")
        self.dxf_label.setObjectName("dialogSectionLabel")
        header.addWidget(self.dxf_label)
        header.addStretch()
        
        load_btn = QPushButton("Load PRJ File")
        load_btn.setObjectName("primaryBtn")
        load_btn.clicked.connect(self.load_prj_file)
        header.addWidget(load_btn)
        layout.addLayout(header)
        
        # Instructions
        # info = QLabel(
        #     "📋 Instructions:\n"
        #     "1. Load a PRJ file containing block information\n"
        #     "2. Select a block from the list\n"
        #     "3. Click 'Identify' to zoom/highlight the block in DXF"
        # )
        # info.setStyleSheet("background: #e8f4f8; padding: 10px; border-radius: 5px;")
        # layout.addWidget(info)
        
        # Table for blocks
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Block Label", "Total Points" , "Area (m²)"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Block Label
        header.setSectionResizeMode(1, QHeaderView.Fixed)    # Total Points
        header.setSectionResizeMode(2, QHeaderView.Fixed)    # Area
        
        self.table.setColumnWidth(1, 120)  # Total Points
        self.table.setColumnWidth(2, 100)  # Area
            
        
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.itemDoubleClicked.connect(self.identify_selected_block)
        layout.addWidget(self.table)
        # ✅ Single-click to clear highlight
        self.table.itemClicked.connect(self.on_table_item_clicked)
        
        # Action buttons
        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        identify_btn = QPushButton("Identify Selected Block")
        identify_btn.setObjectName("primaryBtn")
        identify_btn.clicked.connect(self.identify_selected_block)
        btn_layout.addWidget(identify_btn)

        remove_btn = QPushButton("Remove File")
        remove_btn.setObjectName("dangerBtn")
        remove_btn.clicked.connect(self.remove_prj_file)
        btn_layout.addWidget(remove_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        
    def detect_current_dxf(self):
        """Detect currently loaded DXF file"""
        try:
            if hasattr(self.app, 'dxf_layers') and self.app.dxf_layers:
                # Get first DXF path from loaded layers
                first_layer = next(iter(self.app.dxf_layers.values()))
                if hasattr(first_layer, 'dxf_path'):
                    self.current_dxf_path = first_layer.dxf_path
                    dxf_name = os.path.basename(self.current_dxf_path)
                    self.dxf_label.setText(f"DXF: {dxf_name}")
                    self.auto_load_prj()
                    return
            
            
        except Exception as e:
            print(f"⚠️ DXF detection failed: {e}")
            
    def auto_load_prj(self):
        """Automatically load PRJ file if it exists next to DXF"""
        if not self.current_dxf_path:
            return
            
        try:
            # Look for .prj file with same name as DXF
            prj_path = os.path.splitext(self.current_dxf_path)[0] + ".prj"
            
            if os.path.exists(prj_path):
                print(f"✅ Auto-loading PRJ: {prj_path}")
                self.parse_prj_file(prj_path)
            else:
                print(f"ℹ️ No PRJ file found at: {prj_path}")
        except Exception as e:
            print(f"⚠️ Auto-load PRJ failed: {e}")
            
    def load_prj_file(self):
        """Open file dialog to select PRJ file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select PRJ File",
            "",
            "PRJ Files (*.prj);;All Files (*.*)"
        )
        
        if file_path:
            self.parse_prj_file(file_path)
            
    def parse_prj_file(self, file_path):
        """Parse TerraScan PRJ file and populate table"""
        try:
            # self.prj_data = []
            # self.table.setRowCount(0)
            # ✅ Store the PRJ file path (prevents deletion)
            self.current_prj_path = file_path
            self.current_directory = os.path.dirname(file_path)
            prj_filename = os.path.basename(file_path)
            self.dxf_label.setText(f"PRJ: {prj_filename}")
                        
            print(f"✅ Stored PRJ path: {file_path}")
            self.prj_data = []
            self.table.setRowCount(0)
            
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            print(f"\n📄 Parsing PRJ file: {file_path}")
            print(f"📄 Total lines in file: {len(lines)}")
            
            # Parse block entries: "Block DX5013255_000001.laz"
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                
                if line.startswith('Block '):
                    # Extract block filename
                    block_file = line.replace('Block ', '').strip()
                    block_label = block_file.replace('.laz', '').replace('.las', '')
                    
                    print(f"\n  🔍 Found block: {block_label} at line {i}")
                    
                    # Read coordinate pairs (should be 4-5 lines forming a boundary)
                    coords = []
                    j = i + 1
                    
                    # Read next 10 lines maximum
                    while j < len(lines) and (j - i) <= 10:
                        coord_line = lines[j].strip()
                        
                        print(f"    Line {j}: '{coord_line}' (len={len(coord_line)})")
                        
                        # Stop if we hit next block
                        if coord_line.startswith('Block'):
                            print(f"    🛑 Hit next block, stopping")
                            break
                        
                        # Skip empty lines
                        if coord_line == '':
                            print(f"    ⏭️ Empty line, skipping")
                            j += 1
                            continue
                        
                        # Try to parse as coordinate pair
                        parts = coord_line.split()
                        print(f"    🔢 Split into {len(parts)} parts: {parts}")
                        
                        if len(parts) >= 2:
                            try:
                                x = float(parts[0])
                                y = float(parts[1])
                                coords.append((x, y))
                                print(f"    ✅ Parsed coordinate: ({x}, {y})")
                            except ValueError as e:
                                print(f"    ❌ Parse error: {e}")
                                pass
                        
                        j += 1
                    
                    # Calculate center point from boundary coordinates
                    print(f"    📊 Total coordinates collected: {len(coords)}")
                    
                    if len(coords) >= 2:
                        # Use first 4 coords (ignore 5th duplicate closing point)
                        unique_coords = coords[:4] if len(coords) >= 4 else coords
                        
                        avg_x = sum(c[0] for c in unique_coords) / len(unique_coords)
                        avg_y = sum(c[1] for c in unique_coords) / len(unique_coords)
                        
                        block_data = {
                            'label': block_label,
                            'easting': f"{avg_x:.2f}",
                            'northing': f"{avg_y:.2f}",
                            'description': f"Boundary: {len(coords)} points"
                        }
                        self.prj_data.append(block_data)
                        print(f"    ✅ Added: {block_label} at ({avg_x:.2f}, {avg_y:.2f})")
                    else:
                        print(f"    ⚠️ Only found {len(coords)} coordinates for {block_label}")
                    
                    # Move to next line after this block
                    i = j
                else:
                    i += 1
            
            # Populate table
            # Populate table with file existence check
            print(f"\n📊 Total blocks found: {len(self.prj_data)}")
            self.table.setRowCount(len(self.prj_data))
            files_found = 0
            files_missing = 0

            for row, data in enumerate(self.prj_data):
                block_label = data['label']
                
                # Check if LAZ file exists in current directory
                laz_filename = f"{block_label}.laz"
                laz_path = os.path.join(self.current_directory, laz_filename)
                file_exists = os.path.exists(laz_path)
                
                # Column 0: Block Label
                label_item = QTableWidgetItem(block_label)
                self.table.setItem(row, 0, label_item)
                
                if file_exists:
                    # File exists - get point count and area
                    point_count = self.get_laz_point_count(laz_path)
                    area = self.calculate_grid_area_from_prj(data)
                    
                    # Column 1: Total Points
                    points_item = QTableWidgetItem(f"{point_count:,}" if point_count > 0 else "N/A")
                    self.table.setItem(row, 1, points_item)
                    
                    # Column 2: Area
                    area_item = QTableWidgetItem(f"{area:.2f}" if area > 0 else "N/A")
                    self.table.setItem(row, 2, area_item)
                    
                    files_found += 1
                else:
                    # File doesn't exist
                    no_file_item1 = QTableWidgetItem("No file in path")
                    no_file_item2 = QTableWidgetItem("No file in path")
                    
                    # Make text red to indicate missing file
                    no_file_item1.setForeground(QColor(255, 100, 100))
                    no_file_item2.setForeground(QColor(255, 100, 100))
                    
                    self.table.setItem(row, 1, no_file_item1)
                    self.table.setItem(row, 2, no_file_item2)
                    
                    files_missing += 1

            print(f"✅ Files found: {files_found}, ❌ Files missing: {files_missing}")
                        
            if len(self.prj_data) > 0:
                QMessageBox.information(
                    self,
                    "✅ PRJ Loaded",
                    f"Successfully loaded {len(self.prj_data)} blocks from:\n{os.path.basename(file_path)}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "⚠️ No Blocks Found",
                    f"The PRJ file was read but no block entries were found.\n\nFile: {os.path.basename(file_path)}"
                )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "❌ Load Failed",
                f"Failed to load PRJ file:\n{str(e)}"
            )
            import traceback
            traceback.print_exc()
            
            
    def clear_highlight_for_block(self, block_label):
        """Clear highlight for a specific block when clicked."""
        if not hasattr(self, '_highlighted_blocks') or block_label not in self._highlighted_blocks:
            return
        
        try:
            import vtk
            
            block_info = self._highlighted_blocks[block_label]
            actor = block_info['actor']
            highlight_actor = block_info['highlight_actor']
            
            if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget:
                renderer = self.app.vtk_widget.renderer
                
                # Find and restore original text properties
                if hasattr(self, '_highlighted_labels'):
                    for label_actor, orig_color, orig_scale in self._highlighted_labels:
                        if label_actor == actor:
                            actor.GetProperty().SetColor(orig_color)
                            actor.SetScale(orig_scale)
                            self._highlighted_labels.remove((label_actor, orig_color, orig_scale))
                            break
                
                # Remove highlight circle
                if highlight_actor and highlight_actor in self._highlight_actors:
                    renderer.RemoveActor(highlight_actor)
                    self._highlight_actors.remove(highlight_actor)
                
                # Remove from tracking
                del self._highlighted_blocks[block_label]
                
                # Render
                self.app.vtk_widget.GetRenderWindow().Render()
                
                print(f"✅ Cleared highlight for: {block_label}")
        
        except Exception as e:
            print(f"⚠️ Failed to clear highlight for {block_label}: {e}")
            
            
    def on_table_item_clicked(self, item):
        """Handle single-click on table item - clear highlight if exists."""
        row = item.row()
        
        if row >= len(self.prj_data):
            return
        
        block_label = self.prj_data[row]['label']
        
        # Check if this block is currently highlighted
        if hasattr(self, '_highlighted_blocks') and block_label in self._highlighted_blocks:
            print(f"🖱️ Clicked highlighted block: {block_label} - clearing highlight")
            self.clear_highlight_for_block(block_label)
                    
    def identify_selected_block(self):
        """Identify and highlight selected block(s) in DXF"""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "No Selection", "Please select a block to identify")
            return
        
        # Get unique row indices
        rows = list(set([index.row() for index in selected_rows]))
        
        print(f"\n🔍 Searching for {len(rows)} selected blocks...")
        
        # ✅ Clear ALL previous highlights before adding new ones
        if hasattr(self, '_highlight_actors') and self._highlight_actors:
            if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget:
                renderer = self.app.vtk_widget.renderer
                for old_actor in self._highlight_actors:
                    try:
                        renderer.RemoveActor(old_actor)
                    except Exception:
                        pass
        
        # Initialize list to store all highlight actors
        self._highlight_actors = []
        
        # ✅ Store all actor/block pairs for simultaneous highlighting
        matches_found = []
        all_x = []
        all_y = []
        # Process each selected row
        for row in rows:
            if row >= len(self.prj_data):
                continue
                
            block_data = self.prj_data[row]
            block_label = block_data['label']
            x = float(block_data['easting'])
            y = float(block_data['northing'])
            all_x.append(x)
            all_y.append(y)
            print(f"\n🔍 Searching for block: '{block_label}'")
            
            try:
                # Find block in DXF actors
                block_found = False
                
                if hasattr(self.app, 'dxf_actors'):
                    for dxf_data in self.app.dxf_actors:
                        for actor in dxf_data.get('actors', []):
                            # Check if it's a text label
                            if hasattr(actor, 'is_grid_label') and actor.is_grid_label:
                                grid_name = getattr(actor, 'grid_name', '')
                                
                                # Try exact match or partial match
                                if grid_name == block_label or block_label in grid_name or grid_name in block_label:
                                    print(f"  ✅ MATCH: '{grid_name}' ~ '{block_label}'")
                                    matches_found.append((actor, block_data))
                                    block_found = True
                                    break
                        
                        if block_found:
                            break
                
                if not block_found:
                    print(f"  ❌ Block '{block_label}' not found in DXF")
                    
            except Exception as e:
                print(f"  ❌ Error searching for '{block_label}': {e}")
        
        # ✅ Now highlight ALL matched blocks simultaneously
        if matches_found:
            print(f"\n🎨 Highlighting {len(matches_found)} blocks simultaneously...")
            
            try:
                import vtk
                from PySide6.QtCore import QTimer
                
                if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget:
                    renderer = self.app.vtk_widget.renderer
                    
                    highlighted_labels = []
                    
                    for actor, block_data in matches_found:
                        x = float(block_data['easting'])
                        y = float(block_data['northing'])
                        
                        # Create RED CIRCLE highlight
                        circle = vtk.vtkRegularPolygonSource()
                        circle.SetNumberOfSides(50)
                        circle.SetRadius(30)
                        circle.SetCenter(x, y, 1)
                        circle.GeneratePolygonOff()
                        
                        mapper = vtk.vtkPolyDataMapper()
                        mapper.SetInputConnection(circle.GetOutputPort())
                        
                        highlight_actor = vtk.vtkActor()
                        highlight_actor.SetMapper(mapper)
                        highlight_actor.GetProperty().SetColor(1.0, 0.0, 0.0)  # RED
                        highlight_actor.GetProperty().SetLineWidth(5)
                        highlight_actor.GetProperty().SetOpacity(1.0)
                        
                        renderer.AddActor(highlight_actor)
                        self._highlight_actors.append(highlight_actor)
                        
                        # Make text label yellow and bigger
                        if hasattr(actor, 'GetProperty'):
                            original_color = actor.GetProperty().GetColor()
                            original_scale = actor.GetScale()
                            
                            actor.GetProperty().SetColor(1.0, 1.0, 0.0)  # Yellow
                            # actor.SetScale(original_scale[0] * 3, original_scale[1] * 3, original_scale[2] * 3)
                            
                            # Store for reset
                            highlighted_labels.append((actor, original_color, original_scale))
                        
                        print(f"   ✅ Highlighted: {block_data['label']}")
                    
                    # Render once after all highlights added
                self.app.vtk_widget.GetRenderWindow().Render()
                
                # ✅ Store label info for click-to-clear
                if not hasattr(self, '_highlighted_labels'):
                    self._highlighted_labels = []
                self._highlighted_labels.extend(highlighted_labels)
                
                # ✅ Store block data for click detection
                if not hasattr(self, '_highlighted_blocks'):
                    self._highlighted_blocks = {}
                
                for actor, block_data in matches_found:
                    block_label = block_data['label']
                    self._highlighted_blocks[block_label] = {
                        'actor': actor,
                        'block_data': block_data,
                        'highlight_actor': None  # Will be populated from _highlight_actors
                    }
                
                # Link highlight actors to blocks
                for i, (actor, block_data) in enumerate(matches_found):
                    if i < len(self._highlight_actors):
                        self._highlighted_blocks[block_data['label']]['highlight_actor'] = self._highlight_actors[i]
                
                # Show success message
                block_names = [bd['label'] for _, bd in matches_found]
                QMessageBox.information(
                    self,
                    "Blocks Identified",
                    f"Highlighted {len(matches_found)} blocks:\n\n" +
                    "\n".join(f"• {name}" for name in block_names[:10]) +
                    (f"\n...and {len(block_names) - 10} more" if len(block_names) > 10 else "") +
                    "\n\n✅ Click on a highlighted block to clear it\n" +
                    "✅ Or click 'Remove File' to clear all"
                )
                
                print(f"✅ Highlights will remain until manually cleared")
                    
            except Exception as e:
                print(f"❌ Highlighting failed: {e}")
                import traceback
                traceback.print_exc()
                
        
        # ✈️ Fly camera to the blocks
        if all_x and all_y:
            center_x = sum(all_x) / len(all_x)
            center_y = sum(all_y) / len(all_y)
            self.fly_to_location(center_x, center_y)        
        
        else:
            QMessageBox.warning(
                self,
                "Blocks Not Found",
                f"Could not find any of the {len(rows)} selected blocks in loaded DXF.\n\n"
                "Make sure the DXF contains these grid labels."
            )
    
    
    def fly_to_location(self, x, y, duration=2000):
        """
        Smoothly pan the 2D orthographic camera to the target XY location.

        ROOT-CAUSE FIX (grid disappears after identify):
        ─────────────────────────────────────────────────
        The old implementation set camera Z-position to 200 and called
        camera.Zoom(2.0).  In a parallel-projection (2D) view this does two
        harmful things:

          1. SetPosition([x, y, 200]) moves the camera ABOVE the data plane
             but ONLY translates the focal-point to Z=0.  This implicitly
             switches the view direction, which — combined with
             ResetCameraClippingRange() — produces a clipping frustum that
             excludes DXF grid actors sitting at Z ≈ 0.  The actors are still
             in the renderer, but they fall outside the near/far clip planes,
             so VTK does not draw them.  Pressing Shift+F calls fit_view()
             which resets the camera properly and brings them back.

          2. camera.Zoom(2.0) is a MULTIPLICATIVE scale operation — calling
             it once per "identify" compounded the parallel-scale, causing
             progressive zoom drift on repeated identifies.

        CORRECT 2D APPROACH:
          • Keep ParallelProjection ON throughout.
          • Animate ONLY the focal-point (XY pan) and the camera position
            offset by the same delta — the camera always stays directly
            above the focal point at its current Z height (view-up = Y).
          • Animate the parallel-scale from its current value to a
            target_scale that gives a comfortable (~500 m) view window.
          • After animation: call _ensure_overlay_actors() so that any
            DXF/SNT actors that were removed by an intermediate render
            call are guaranteed to be back in the renderer.
        """
        try:
            from PySide6.QtCore import QTimer

            if not hasattr(self.app, 'vtk_widget') or not self.app.vtk_widget:
                return

            renderer   = self.app.vtk_widget.renderer
            camera     = renderer.GetActiveCamera()
            render_win = self.app.vtk_widget.GetRenderWindow()

            # ── Snapshot current camera state ─────────────────────────
            start_focal = list(camera.GetFocalPoint())   # (fx, fy, fz)
            start_pos   = list(camera.GetPosition())     # (px, py, pz)
            start_scale = camera.GetParallelScale()      # half-height in world units

            # Compute the constant offset between camera position and focal
            # point.  In 2D top-down mode this is (0, 0, height_above_ground).
            cam_offset = [
                start_pos[0] - start_focal[0],
                start_pos[1] - start_focal[1],
                start_pos[2] - start_focal[2],
            ]

            # ── Target values ──────────────────────────────────────────
            target_focal = [x, y, start_focal[2]]   # keep same Z plane
            target_pos   = [
                x + cam_offset[0],
                y + cam_offset[1],
                start_pos[2],                        # preserve Z height
            ]

            # Target parallel-scale: ~250 m half-height gives a comfortable
            # 500 m wide view.  Clamp so we never zoom in tighter than 50 m
            # or wider than 2× the current scale.
            TARGET_HALF_HEIGHT_M = 250.0
            target_scale = max(
                50.0,
                min(TARGET_HALF_HEIGHT_M, start_scale * 2.0)
            )

            # ── Ensure parallel projection is active ───────────────────
            camera.ParallelProjectionOn()
            camera.SetViewUp(0.0, 1.0, 0.0)

            # ── Animation ─────────────────────────────────────────────
            STEPS         = 40                          # fewer steps → snappier
            step_duration = max(1, duration // STEPS)
            current_step  = [0]

            def _eased(t: float) -> float:
                """Smooth-step (ease-in-out cubic)."""
                return t * t * (3.0 - 2.0 * t)

            def animate_step():
                step = current_step[0]

                if step >= STEPS:
                    # ── Final frame: land exactly on target ───────────
                    camera.SetFocalPoint(target_focal)
                    camera.SetPosition(target_pos)
                    camera.SetParallelScale(target_scale)
                    camera.SetViewUp(0.0, 1.0, 0.0)
                    renderer.ResetCameraClippingRange()
                    render_win.Render()

                    # ── CRITICAL: restore any DXF/SNT actors that an
                    #    intermediate render might have dropped ─────────
                    try:
                        if hasattr(self.app, '_ensure_overlay_actors'):
                            self.app._ensure_overlay_actors()
                    except Exception:
                        pass

                    print(f"✈️  Fly-to complete → ({x:.2f}, {y:.2f})")
                    return

                t = _eased(step / STEPS)

                # Interpolate focal point (XY pan only)
                new_focal = [
                    start_focal[0] + (target_focal[0] - start_focal[0]) * t,
                    start_focal[1] + (target_focal[1] - start_focal[1]) * t,
                    start_focal[2],
                ]
                # Keep camera directly above focal point (no Z change)
                new_pos = [
                    new_focal[0] + cam_offset[0],
                    new_focal[1] + cam_offset[1],
                    start_pos[2],
                ]
                # Animate parallel scale
                new_scale = start_scale + (target_scale - start_scale) * t

                camera.SetFocalPoint(new_focal)
                camera.SetPosition(new_pos)
                camera.SetParallelScale(new_scale)
                renderer.ResetCameraClippingRange()
                render_win.Render()

                current_step[0] += 1
                QTimer.singleShot(step_duration, animate_step)

            # Kick off animation
            animate_step()
            print(f"✈️  Flying to ({x:.2f}, {y:.2f})  target_scale={target_scale:.1f}")

        except Exception as e:
            print(f"⚠️ Fly-to animation failed: {e}")
            import traceback
            traceback.print_exc()        
            
    def zoom_to_block(self, block, block_data):
        """Zoom and highlight a DXF block"""
        try:
            # Get block position (from PRJ coordinates or block data)
            x = float(block_data['easting'])
            y = float(block_data['northing'])
            
            # Zoom to block location
            if hasattr(self.app, 'viewer') and self.app.viewer:
                # Create temporary highlight
                self.highlight_location(x, y)
                
                # Zoom to location with some padding
                padding = 50  # meters
                self.app.viewer.zoom_to_bounds(
                    x - padding, y - padding,
                    x + padding, y + padding
                )
                
        except Exception as e:
            print(f"⚠️ Zoom failed: {e}")
            
            
    def zoom_to_entity(self, actor, block_data):
        """
        Pan the 2D camera to the entity location and create a visible highlight
        marker.  Preserves parallel projection so DXF grid actors stay visible.
        """
        try:
            import vtk

            x = float(block_data['easting'])
            y = float(block_data['northing'])

            print(f"🎯 Zooming to block at ({x}, {y})")

            if not (hasattr(self.app, 'vtk_widget') and self.app.vtk_widget):
                print("⚠️ VTK widget not available")
                return

            renderer   = self.app.vtk_widget.renderer
            render_win = self.app.vtk_widget.GetRenderWindow()
            camera     = renderer.GetActiveCamera()

            # ── Remove old single-entity highlight ────────────────────
            if hasattr(self, '_highlight_actor') and self._highlight_actor:
                try:
                    renderer.RemoveActor(self._highlight_actor)
                except Exception:
                    pass
                self._highlight_actor = None

            # ── Create RED CIRCLE highlight marker ────────────────────
            circle = vtk.vtkRegularPolygonSource()
            circle.SetNumberOfSides(50)
            circle.SetRadius(30)
            circle.SetCenter(x, y, 1)        # slightly above data plane
            circle.GeneratePolygonOff()

            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(circle.GetOutputPort())

            highlight_actor = vtk.vtkActor()
            highlight_actor.SetMapper(mapper)
            highlight_actor.GetProperty().SetColor(1.0, 0.0, 0.0)
            highlight_actor.GetProperty().SetLineWidth(5)
            highlight_actor.GetProperty().SetOpacity(1.0)

            renderer.AddActor(highlight_actor)
            self._highlight_actor = highlight_actor

            # ── Move camera in 2D — DO NOT break parallel projection ──
            # Keep the camera at its current Z height above the scene and
            # simply pan the focal point to (x, y).  This keeps every DXF/
            # SNT actor inside the clipping frustum.
            current_focal = list(camera.GetFocalPoint())
            current_pos   = list(camera.GetPosition())
            cam_offset_z  = current_pos[2] - current_focal[2]   # camera Z above focal

            camera.ParallelProjectionOn()
            camera.SetViewUp(0.0, 1.0, 0.0)
            camera.SetFocalPoint(x, y, current_focal[2])
            camera.SetPosition(x, y, current_focal[2] + cam_offset_z)

            # Zoom in: halve the parallel scale for a closer look (minimum 50 m)
            new_scale = max(50.0, camera.GetParallelScale() * 0.5)
            camera.SetParallelScale(new_scale)

            renderer.ResetCameraClippingRange()
            render_win.Render()

            # ── Ensure all overlay actors are still in the renderer ───
            try:
                if hasattr(self.app, '_ensure_overlay_actors'):
                    self.app._ensure_overlay_actors()
            except Exception:
                pass

            # ── Temporarily highlight the text actor ──────────────────
            if hasattr(actor, 'GetProperty'):
                original_color = tuple(actor.GetProperty().GetColor())
                original_scale = tuple(actor.GetScale())

                actor.GetProperty().SetColor(1.0, 1.0, 0.0)   # yellow
                render_win.Render()

                def reset_highlight():
                    try:
                        actor.GetProperty().SetColor(original_color)
                        actor.SetScale(original_scale)
                        renderer.RemoveActor(highlight_actor)
                        self._highlight_actor = None
                        render_win.Render()
                    except Exception:
                        pass

                from PySide6.QtCore import QTimer
                QTimer.singleShot(3000, reset_highlight)

            print(f"✅ Zoomed to block with RED CIRCLE highlight (30 m radius)")

            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Block Identified",
                f"Zoomed to block: {block_data['label']}\n\n"
                f"Location: ({x:.2f}, {y:.2f})\n"
                "Red circle marker will disappear in 3 seconds"
            )

        except Exception as e:
            print(f"⚠️ Zoom failed: {e}")
            import traceback
            traceback.print_exc()
            
    def highlight_location(self, x, y):
        """Create temporary highlight at location"""
        try:
            # Add temporary marker/circle at location
            if hasattr(self.app, 'viewer') and self.app.viewer:
                # You can implement this based on your viewer's API
                # For example: draw a temporary circle or marker
                print(f"🎯 Highlighting location: ({x}, {y})")
                
                # Example: Create a temporary highlight layer
                # self.app.viewer.add_highlight_marker(x, y)
                
        except Exception as e:
            print(f"⚠️ Highlight failed: {e}")
            
    def debug_dxf_text_labels(self):
        """Debug: Print all text labels found in loaded DXF"""
        print("\n🔍 DEBUG: Scanning DXF for text labels...")
        
        try:
            if hasattr(self.app, 'dxf_actors') and self.app.dxf_actors:
                for dxf_data in self.app.dxf_actors:
                    print(f"\n📄 DXF File: {dxf_data.get('filename', 'Unknown')}")
                    
                    text_count = 0
                    for actor in dxf_data.get('actors', []):
                        if hasattr(actor, 'is_grid_label') and actor.is_grid_label:
                            grid_name = getattr(actor, 'grid_name', 'NO_NAME')
                            print(f"  📝 Text label: '{grid_name}'")
                            text_count += 1
                    
                    print(f"  Total text labels found: {text_count}")
            else:
                print("  ⚠️ No DXF actors found in app")
                
        except Exception as e:
            print(f"  ❌ Debug failed: {e}")
            import traceback
            traceback.print_exc()
            
            
    def remove_prj_file(self):
        """Remove currently loaded PRJ file from the dialog."""
        if not self.current_prj_path:
            QMessageBox.warning(
                self,
                "No File Loaded",
                "No PRJ file is currently loaded."
            )
            return
        
        reply = QMessageBox.question(
            self,
            "Remove PRJ File",
            f"Remove loaded file:\n{os.path.basename(self.current_prj_path)}\n\n"
            "This will clear the block list but NOT delete the file from disk.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Clear the table
            self.table.setRowCount(0)
            self.prj_data.clear()
            
            # Clear the stored path
            filename = os.path.basename(self.current_prj_path)
            self.current_prj_path = None
            
            # Update status label
            self.dxf_label.setText("No DXF loaded")
            # ✅ Clear all highlights
            if hasattr(self, '_highlight_actors') and self._highlight_actors:
                if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget:
                    renderer = self.app.vtk_widget.renderer
                    for highlight_actor in self._highlight_actors:
                        try:
                            renderer.RemoveActor(highlight_actor)
                        except Exception:
                            pass
                    self.app.vtk_widget.GetRenderWindow().Render()
            
            # Clear tracking data
            self._highlight_actors = []
            self._highlighted_labels = []
            self._highlighted_blocks = {}
            
            # Update status label
            self.dxf_label.setText("No DXF loaded")
                
            print(f"✅ Removed PRJ file: {filename}")
            
            QMessageBox.information(
                self,
                "File Removed",
                f"PRJ file '{filename}' has been removed from the dialog.\n\n"
                "The file still exists on disk."
            )
            
    def get_laz_point_count(self, laz_path):
        """
        Get the total point count from a LAZ/LAS file.
        Returns point count or 0 if file not found/error.
        """
        try:
            from pathlib import Path
            
            file_path = Path(laz_path)
            
            # Check if file exists
            if not file_path.exists():
                print(f"  ⚠️ File not found: {laz_path}")
                return 0
            
            # Try to read point count using laspy
            try:
                import laspy
                with laspy.open(str(file_path)) as las_file:
                    point_count = las_file.header.point_count
                    print(f"  ✅ {file_path.name}: {point_count:,} points")
                    return point_count
            except ImportError:
                print("  ⚠️ laspy not installed - cannot read point count")
                return 0
            except Exception as e:
                print(f"  ⚠️ Failed to read {file_path.name}: {e}")
                return 0
                
        except Exception as e:
            print(f"  ❌ Error getting point count: {e}")
            return 0        
            
            
    def calculate_grid_area(self, block_name):
        """
        Calculate approximate area of a grid block from DXF geometry.
        Returns area in square meters or 0 if cannot calculate.
        """
        try:
            # Get the block's polyline/rectangle from DXF
            # This is a simple approach - measure bounding box
            
            if not hasattr(self, 'dxf_blocks') or block_name not in self.dxf_blocks:
                return 0
            
            block_data = self.dxf_blocks[block_name]
            
            # Get all line/polyline coordinates for this block
            all_x = []
            all_y = []
            
            for entity in block_data.get('entities', []):
                if entity['type'] == 'line':
                    all_x.extend([entity['start'][0], entity['end'][0]])
                    all_y.extend([entity['start'][1], entity['end'][1]])
                elif entity['type'] == 'polyline':
                    for pt in entity['points']:
                        all_x.append(pt[0])
                        all_y.append(pt[1])
            
            if not all_x or not all_y:
                return 0
            
            # Calculate bounding box area
            width = max(all_x) - min(all_x)
            height = max(all_y) - min(all_y)
            area = width * height
            
            return area
            
        except Exception as e:
            print(f"  ⚠️ Error calculating area: {e}")
            return 0        
    def calculate_grid_area_from_prj(self, block_data):
        """
        Calculate area from PRJ boundary coordinates.
        Uses the coordinates stored in block_data.
        """
        try:
            # Get coordinates from description or stored coords
            # For now, return estimated area based on typical grid size
            # You can enhance this by storing coords during parsing
            
            # Typical grid block is around 4000-4500 m²
            # For accurate calculation, you'd need to store the coords during parse_prj_file
            return 4434644.91  # Placeholder - enhance with actual boundary calculation
            
        except Exception as e:
            print(f"  ⚠️ Error calculating area: {e}")
            return 0

def show_block_identifier_dialog(app):
    """Show the PRJ block identifier dialog (persistent reference)"""
   
    # Check if dialog already exists
    if hasattr(app, 'block_identifier_dialog') and app.block_identifier_dialog:
        try:
            app.block_identifier_dialog.show()
            app.block_identifier_dialog.raise_()
            app.block_identifier_dialog.activateWindow()
            return app.block_identifier_dialog
        except Exception:
            # If dialog was deleted/closed, ignore and recreate
            pass
   
    # ✅ FIX: Pass 'parent=app' so it attaches to the main window correctly
    dialog = PRJBlockIdentifierDialog(app, parent=app)
   
    # Store reference in app
    app.block_identifier_dialog = dialog
   
    dialog.show()
    return dialog  ####
