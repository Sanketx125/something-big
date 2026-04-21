import os
from pathlib import Path
import vtk
from PySide6.QtWidgets import QMessageBox, QFileDialog,QHBoxLayout
from PySide6.QtCore import QSettings
import numpy as np

class GridLabelManager:
    """
    Manages grid label clicking and automatic LAZ/LAS loading.
    Implements hyperlink-style behavior for DXF grid labels.
    """
    
    def __init__(self, app):
        self.app = app
        self.settings = QSettings("NakshaAI", "LidarApp")
        
        # Cache of DXF folder -> LAZ/LAS folder mappings
        self.folder_cache = {}
        self.loaded_grids = {}
        # ✨ NEW: Track highlighted labels
        self.highlighted_label = None
        self.original_colors = {}  # Store original colors for restoration
        self._interactor_observer_ids = {}
        
        print("✅ Grid Label Manager initialized")
    
    def setup_interactor(self):
        """Attach right-click observer to main VTK widget"""
        if not hasattr(self.app, 'vtk_widget'):
            print("⚠️ No VTK widget found")
            return
        
        self.ensure_interactor_observers()
        
        # ✨ NEW: Add hover detection for visual feedback
        
        print("✅ Grid label click detection enabled")
            
    def ensure_interactor_observers(self):
        """Re-install managed observers after another tool clears interactor callbacks."""
        if not hasattr(self.app, 'vtk_widget'):
            return

        interactor = self.app.vtk_widget.interactor
        managed = {
            "RightButtonPressEvent": self.on_right_click,
            "MouseMoveEvent": self.on_mouse_move,
        }
        if hasattr(self, 'on_key_press'):
            managed["KeyPressEvent"] = self.on_key_press

        for event_name, callback in managed.items():
            old_id = self._interactor_observer_ids.get(event_name)
            if old_id is not None:
                try:
                    interactor.RemoveObserver(old_id)
                except Exception:
                    pass

            priority = 2.0 if event_name == "RightButtonPressEvent" else 0.0
            self._interactor_observer_ids[event_name] = interactor.AddObserver(
                event_name, callback, priority
            )

    def _consume_vtk_event(self, obj):
        if obj is None:
            return

        try:
            if hasattr(obj, 'AbortFlagOn'):
                obj.AbortFlagOn()
            elif hasattr(obj, 'SetAbortFlag'):
                try:
                    obj.SetAbortFlag(1)
                except TypeError:
                    obj.SetAbortFlag(True)
        except Exception:
            pass

    def on_mouse_move(self, obj, event):
        """Highlight labels on hover"""
        clickPos = self.app.vtk_widget.interactor.GetEventPosition()
        
        # Use area picker for better detection
        area_picker = vtk.vtkAreaPicker()
        x, y = clickPos
        area_picker.AreaPick(x-10, y-10, x+10, y+10, self.app.vtk_widget.renderer)
        
        found_label = None
        for prop in area_picker.GetProp3Ds():
            if hasattr(prop, 'is_grid_label') and prop.is_grid_label:
                found_label = prop
                break
        
        # Update highlighting
        if found_label != self.highlighted_label:
            if self.highlighted_label:
                self._unhighlight_label(self.highlighted_label)
            if found_label:
                self._highlight_label(found_label)
            self.highlighted_label = found_label
            self.app.vtk_widget.update()

    def _highlight_label(self, actor):
        """Apply highlight effect to label"""
        if actor not in self.original_colors:
            prop = actor.GetProperty()
            self.original_colors[actor] = {
                'color': prop.GetColor(),
                'opacity': prop.GetOpacity()
            }
        
        # Apply bright highlight
        prop = actor.GetProperty()
        prop.SetColor(1.0, 1.0, 0.0)  # Bright yellow
        prop.SetOpacity(1.0)
        
        # Make it slightly bigger/bolder if possible
        if hasattr(actor, 'GetMapper'):
            mapper = actor.GetMapper()
            if mapper:
                mapper.ScalarVisibilityOff()

    def _unhighlight_label(self, actor):
        """Remove highlight effect from label"""
        if actor in self.original_colors:
            orig = self.original_colors[actor]
            prop = actor.GetProperty()
            prop.SetColor(*orig['color'])
            prop.SetOpacity(orig['opacity'])
            
            
    def _show_file_selection_dialog(self, las_folder, grid_name):
        """
        Fallback dialog: let user pick a LAS/LAZ file from las_folder
        when no automatic match is found for grid_name.
        """
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        # Make sure we have a string path
        folder_str = str(las_folder) if las_folder is not None else ""

        # Let user pick a file
        file_path, _ = QFileDialog.getOpenFileName(
            self.app,
            f"Select LAZ/LAS file for grid {grid_name}",
            folder_str,
            "LiDAR Files (*.laz *.las);;All Files (*.*)",
        )

        if not file_path:
            # User cancelled
            return

        # Optional: small confirmation
        reply = QMessageBox.question(
            self.app,
            "Confirm Grid File",
            f"Use this file for grid '{grid_name}'?\n\n{os.path.basename(file_path)}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if reply != QMessageBox.Yes:
            return

        # Reuse existing loading pipeline
        self._load_las_file(Path(file_path), grid_name)

            
    def _is_tool_operation_in_progress(self):
        """Returns True if any user tool is currently performing an operation that uses right-click."""
        app = self.app
        if not app: return False

        # 1. Digitize (Draw) Tools: active when a tool is selected and has points
        digitizer = getattr(app, "digitizer", None)
        if digitizer and (digitizer.active_tool or getattr(digitizer, "vertex_move_mode", False)):
            # If in the middle of drawing (any points clicked)
            if len(getattr(digitizer, "temp_points", [])) > 0:
                return True
            # If currently moving/dragging a vertex
            if getattr(digitizer, "dragging_vertex", None) is not None:
                return True

        # 2. Measurement Tool: active during measurement drag
        mtool = getattr(app, "measurement_tool", None)
        if mtool and getattr(mtool, "is_measuring", False):
            if len(getattr(mtool, "measurement_points", [])) > 0:
                return True

        # 3. Curve Tool: active during curve path drawing
        ctool = getattr(app, "curve_tool", None)
        if ctool and ctool.active:
            if len(getattr(ctool, "points", [])) > 0:
                return True

        # 4. Zoom Rectangle Tool: active when drawing rectangle
        ztool = getattr(app, "zoom_rectangle_tool", None)
        if ztool and ztool.active and getattr(ztool, "start_pos", None) is not None:
            return True

        # 5. Select Rectangle Tool: active when drawing/processing selection
        stool = getattr(app, "select_rectangle_tool", None)
        if stool and stool.active:
            if getattr(stool, "is_drawing", False) or getattr(stool, "start_pos", None) is not None:
                return True

        return False

    def on_right_click(self, obj, event):
        """Handle right-click on grid label OR point cloud"""
        from PySide6.QtWidgets import QMenu, QInputDialog
        from PySide6.QtGui import QAction, QCursor

        # ✅ FIXED: If a tool operation is in progress (drawing, measuring, etc.),
        # let the tool handle the right-click to finalize its operation.
        # This prevents the 'Shading controls' dialog from appearing prematurely.
        if self._is_tool_operation_in_progress():
            return 0  # Allow other observers (the tools) to handle it

        can_show_shading = getattr(self.app, "_can_show_shading_controls", None)
        if callable(can_show_shading) and can_show_shading():
            self._consume_vtk_event(obj)
            self.app.show_shading_controls()
            return 1

        clickPos = self.app.vtk_widget.interactor.GetEventPosition()
        
        # ═══════════════════════════════════════════════════════
        # STEP 1: Try to find grid label first
        # ═══════════════════════════════════════════════════════
        picker = vtk.vtkPropPicker()
        picker.Pick(clickPos[0], clickPos[1], 0, self.app.vtk_widget.renderer)
        actor = picker.GetActor()
        
        if not actor or not (hasattr(actor, 'is_grid_label') and actor.is_grid_label):
            # Try area picker with 10-pixel radius
            area_picker = vtk.vtkAreaPicker()
            x, y = clickPos
            area_picker.AreaPick(x-10, y-10, x+10, y+10, self.app.vtk_widget.renderer)
            
            for prop in area_picker.GetProp3Ds():
                if hasattr(prop, 'is_grid_label') and prop.is_grid_label:
                    actor = prop
                    break
        
        # ═══════════════════════════════════════════════════════
        # CASE A: Found grid label - show label menu
        # ═══════════════════════════════════════════════════════
        if actor and hasattr(actor, 'is_grid_label') and actor.is_grid_label:
            grid_name = getattr(actor, 'grid_name', '')
            
            if grid_name:
                menu = QMenu(self.app)
                menu.setStyleSheet("""
                    QMenu {
                        background-color: #2c2c2c;
                        color: #f0f0f0;
                        border: 1px solid #555;
                        padding: 5px;
                    }
                    QMenu::item {
                        padding: 8px 30px;
                        border-radius: 3px;
                    }
                    QMenu::item:selected {
                        background-color: #3c3c3c;
                    }
                """)
                
                load_action = QAction("📂 Load Grid Data", self.app)
                clear_action = QAction("🧹 Clear Grid Data", self.app)
                
                def confirm_clear():
                    reply = QMessageBox.question(
                        self.app,
                        "Confirm Clear",
                        f"Clear all points from grid:\n\n{grid_name}\n\n"
                        f"Points will be removed from view.\n\nContinue?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.Yes:
                        self.clear_grid_data(grid_name)

                clear_action.triggered.connect(confirm_clear)
                
                is_loaded = grid_name in self.loaded_grids
                
                if is_loaded:
                    load_action.setText("📂 Reload Grid Data")
                    point_count = len(self.loaded_grids[grid_name])
                    clear_action.setText(f"🧹 Clear Grid ({point_count:,} pts)")
                else:
                    clear_action.setEnabled(False)
                    clear_action.setText("🧹 (Grid not loaded)")

                load_action.triggered.connect(lambda: self.load_grid_las(grid_name))
                clear_action.triggered.connect(lambda: self.clear_grid_data(grid_name))

                menu.addAction(load_action)
                menu.addAction(clear_action)
                menu.exec(QCursor.pos())
                return

        # ═══════════════════════════════════════════════════════
        # CASE B: No label found - try picking point cloud
        # ═══════════════════════════════════════════════════════
        if not hasattr(self.app, 'data') or self.app.data is None:
            return  # No data loaded
        
        point_picker = vtk.vtkPointPicker()
        point_picker.Pick(clickPos[0], clickPos[1], 0, self.app.vtk_widget.renderer)
        point_id = point_picker.GetPointId()
        
        if point_id < 0:
            return  # No point picked
        
        # Find which grid this point belongs to
        grid_name = self._find_grid_for_point(point_id)
        
        # Create context menu
        menu = QMenu(self.app)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2c2c2c;
                color: #f0f0f0;
                border: 1px solid #555;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 30px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #3c3c3c;
            }
        """)
        
        # if grid_name:
        #     # Point belongs to a tracked grid
        #     point_count = len(self.loaded_grids[grid_name])
        #     clear_action = QAction(f"🧹 Clear Grid: {grid_name} ({point_count:,} pts)", self.app)
        #     clear_action.triggered.connect(lambda: self.clear_grid_data(grid_name))
        #     menu.addAction(clear_action)

        menu.exec(QCursor.pos())
        
    def _find_grid_for_point(self, point_id):
        """Find which grid a point belongs to"""
        for grid_name, indices in self.loaded_grids.items():
            if point_id in indices:
                return grid_name
        return None

    def _delete_area_by_point(self, point_id):
        """Delete area around clicked point by selecting nearby points"""
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        import numpy as np
        
        # Ask for grid name
        grid_name, ok = QInputDialog.getText(
            self.app,
            "Define Grid Area",
            f"Clicked point: {point_id}\n\n"
            f"Enter grid name to delete:"
        )
        
        if not ok or not grid_name:
            return
        
        # Ask for radius
        radius, ok = QInputDialog.getDouble(
            self.app,
            "Selection Radius",
            "Select points within radius (meters):",
            10.0,  # default
            1.0,   # min
            100.0, # max
            1      # decimals
        )
        
        if not ok:
            return
        
        # Find nearby points
        point_xyz = self.app.data['xyz'][point_id]
        all_xyz = self.app.data['xyz']
        
        distances = np.linalg.norm(all_xyz - point_xyz, axis=1)
        nearby_indices = np.where(distances <= radius)[0]
        
        if len(nearby_indices) == 0:
            QMessageBox.warning(self.app, "No Points", "No points found in selection area")
            return
        
        # Track and delete
        self.loaded_grids[grid_name] = nearby_indices
        
        reply = QMessageBox.question(
            self.app,
            "Confirm Selection",
            f"Selected {len(nearby_indices):,} points\n"
            f"within {radius}m radius\n\n"
            f"Delete grid '{grid_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.delete_grid_data(grid_name)
    
    def load_grid_las(self, grid_name):
        """
        Main entry point: Load LAZ/LAS file for clicked grid
        Uses multiple detection strategies
        """
        print(f"\n{'='*60}")
        print(f"📂 LOADING POINT CLOUD FOR GRID: {grid_name}")
        print(f"{'='*60}\n")
        
        # ✅ NEW: Check if we have original file path stored (for reloading cleared grids)
        if hasattr(self.app, 'original_file_paths') and grid_name in self.app.original_file_paths:
            original_file = Path(self.app.original_file_paths[grid_name])
            
            if original_file.exists():
                print(f"  ✅ Reloading from original file: {original_file.name}")
                self._load_las_file(original_file, grid_name)
                return
            else:
                print(f"  ⚠️ Original file not found: {original_file}")
                print(f"     Searching for file...")
        
        # Strategy 1: Find LAZ/LAS folder from DXF location
        las_folder = self._find_las_folder_from_dxf()
        
        if not las_folder:
            # Strategy 2: Ask user to select folder (first time only)
            las_folder = self._prompt_user_for_las_folder()
        
        if not las_folder:
            QMessageBox.warning(
                self.app,
                "Folder Not Found",
                "Could not locate LAZ/LAS folder.\n\n"
                "Please ensure LAZ/LAS files are in:\n"
                "- Same folder as DXF\n"
                "- 'lazz' subfolder\n"
                "- 'laz' subfolder"
            )
            return
        
        # Find matching LAZ/LAS file
        las_file = self._find_matching_las_file(las_folder, grid_name)
        
        if las_file:
            self._load_las_file(las_file, grid_name)
        else:
            # No exact match - show available files
            self._show_file_selection_dialog(las_folder, grid_name)
    
    def _find_las_folder_from_dxf(self):
        """
        ✅ UPDATED: Use full_path from dxf_actors
        """
        print("📋 STRATEGY 1: Auto-detect from DXF location")
        
        if not hasattr(self.app, 'dxf_actors') or not self.app.dxf_actors:
            print("   ❌ No DXF files loaded")
            return None
        
        for dxf_data in self.app.dxf_actors:
            # ✅ Use full_path instead of filename
            full_path = dxf_data.get('full_path')
            
            if not full_path:
                # Fallback to filename (old code compatibility)
                filename = dxf_data.get('filename', '')
                if filename:
                    dxf_path = Path(filename)
                else:
                    continue
            else:
                dxf_path = Path(full_path)
            
            print(f"   DXF file: {dxf_path.name}")
            print(f"   DXF folder: {dxf_path.parent}")
            print(f"   Path exists: {dxf_path.exists()}")
            
            if not dxf_path.exists():
                print(f"   ⚠️ Path doesn't exist: {dxf_path}")
                continue
            
            dxf_folder = dxf_path.parent
            
            # Check cache
            if str(dxf_folder) in self.folder_cache:
                cached = self.folder_cache[str(dxf_folder)]
                print(f"   ✅ Using cached folder: {cached}")
                return cached
            
            # Same folder as DXF
            las_files = list(dxf_folder.glob("*.laz")) + list(dxf_folder.glob("*.las"))
            if las_files:
                print(f"   ✅ FOUND {len(las_files)} LAZ/LAS files in DXF folder")
                self.folder_cache[str(dxf_folder)] = dxf_folder
                self._save_folder_to_settings(dxf_folder)
                return dxf_folder
            
            # Check subfolders
            for subfolder_name in ['lazz', 'LAZZ', 'laz', 'LAZ', 'las', 'LAS']:
                subfolder = dxf_folder / subfolder_name
                
                if subfolder.exists() and subfolder.is_dir():
                    las_files = list(subfolder.glob("*.laz")) + list(subfolder.glob("*.las"))
                    
                    if las_files:
                        print(f"   ✅ FOUND {len(las_files)} files in '{subfolder_name}' subfolder")
                        self.folder_cache[str(dxf_folder)] = subfolder
                        self._save_folder_to_settings(subfolder)
                        return subfolder
        
        return None
        
    def _prompt_user_for_las_folder(self):
        """
        Strategy 2: Ask user to select LAZ/LAS folder
        Only happens once - cached for future use
        """
        print("\n📋 STRATEGY 2: Prompt user for folder")
        
        reply = QMessageBox.question(
            self.app,
            "Select LAZ/LAS Folder",
            "Could not auto-detect LAZ/LAS folder.\n\n"
            "Would you like to select the folder manually?\n\n"
            "(This will be remembered for future clicks)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        
        if reply == QMessageBox.No:
            return None
        
        folder = QFileDialog.getExistingDirectory(
            self.app,
            "Select LAZ/LAS Folder",
            "",
            QFileDialog.ShowDirsOnly
        )
        
        if folder:
            folder_path = Path(folder)
            
            # Verify it contains LAZ/LAS files
            las_files = list(folder_path.glob("*.laz")) + list(folder_path.glob("*.las"))
            
            if not las_files:
                QMessageBox.warning(
                    self.app,
                    "No Files Found",
                    f"Selected folder contains no LAZ/LAS files:\n{folder}"
                )
                return None
            
            print(f"   ✅ User selected: {folder_path} ({len(las_files)} files)")
            self._save_folder_to_settings(folder_path)
            return folder_path
        
        return None
    
    def _find_matching_las_file(self, las_folder, grid_name):
        """
        Find LAZ/LAS file matching grid name using pattern matching
        
        Common patterns:
        - DW3032726_000005.laz  (exact match)
        - DW3032726_5.laz       (without leading zeros)
        - 000005.laz            (just the number)
        - DW3032726.laz         (base name only)
        """
        print(f"\n🔍 Searching for file matching: {grid_name}")
        
        las_folder_path = Path(las_folder)
        
        # Get all LAZ/LAS files
        all_files = list(las_folder_path.glob("*.laz")) + list(las_folder_path.glob("*.las"))
        
        print(f"   Total files in folder: {len(all_files)}")
        
        if not all_files:
            return None
        
        # Extract patterns from grid name
        patterns = self._extract_patterns(grid_name)
        
        print(f"   Search patterns: {patterns}")
        
        # Try each pattern
        # ✅ FIX: Try EXACT match first, then fallback to contains
        for pattern in patterns:
            # STEP 1: Try exact match (case-insensitive)
            for file_path in all_files:
                filename = file_path.stem
                if pattern.lower() == filename.lower():
                    print(f"   ✅ EXACT MATCH: {file_path.name}")
                    return file_path
            
            # STEP 2: Try suffix match (e.g., "000021" matches "SPECCHIA000021")
            for file_path in all_files:
                filename = file_path.stem
                if filename.lower().endswith(pattern.lower()):
                    print(f"   ✅ SUFFIX MATCH: {file_path.name}")
                    return file_path
            
            # STEP 3: Only use contains as last resort AND verify it's not a substring mismatch
            for file_path in all_files:
                filename = file_path.stem
                if pattern.lower() in filename.lower():
                    # ✅ CRITICAL: Verify this isn't "21" matching "221" or "121"
                    # Check if pattern appears at word boundary (start, end, or surrounded by non-digits)
                    import re
                    # Create pattern that matches whole number sequences
                    regex = r'(?<!\d)' + re.escape(pattern) + r'(?!\d)'
                    if re.search(regex, filename, re.IGNORECASE):
                        print(f"   ✅ CONTAINS MATCH (validated): {file_path.name}")
                        return file_path

        print(f"   ❌ No match found")
        return None
    
    def _extract_patterns(self, grid_name):
        """
        Extract search patterns from grid name
        
        Example: "DW3032726_000005" produces:
        - DW3032726_000005 (exact)
        - DW3032726_5 (without leading zeros)
        - 000005 (just number)
        - 5 (number without zeros)
        - DW3032726 (base prefix)
        """
        patterns = [grid_name]  # Always try exact match first
        
        # Split by underscore or space
        parts = grid_name.replace(' ', '_').split('_')
        
        for part in parts:
            if part:
                patterns.append(part)
                
                # Try removing leading zeros
                if part.isdigit():
                    patterns.append(str(int(part)))
        
        # Try base prefix (before first underscore/space)
        if '_' in grid_name:
            base = grid_name.split('_')[0]
            if base:
                patterns.append(base)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_patterns = []
        for p in patterns:
            if p not in seen:
                seen.add(p)
                unique_patterns.append(p)
        
        return unique_patterns
    
    def _load_las_file(self, las_file, grid_name):
        """
        Load LAZ/LAS file using the EXACT same path as menu bar loading.
        ✅ Mirrors open_file() logic exactly to ensure consistent behavior
        """
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QMessageBox
        from gui.progress_dialog import LoadingProgressDialog
        import os
        import time
        import numpy as np

        print(f"\n{'='*70}")
        print(f"📂 GRID LOAD - USING MENU BAR PATH")
        print(f"   Grid: {grid_name}")
        print(f"   File: {las_file.name}")
        print(f"{'='*70}")

        # ============================================================================
        # STEP 1: AUTO-SAVE CURRENT FILE (if exists) - SAME AS MENU BAR
        # ============================================================================
        if hasattr(self.app, 'data') and self.app.data is not None:
            save_path = getattr(self.app, 'last_save_path', None) or getattr(self.app, 'loaded_file', None)
            
            # Only save if there are points (prevent saving empty cleared state)
            current_point_count = len(self.app.data.get('xyz', [])) if self.app.data else 0
            
            if save_path and current_point_count > 0:
                try:
                    print(f"\n💾 AUTO-SAVING CURRENT FILE")
                    print(f"   Path: {os.path.basename(save_path)}")
                    print(f"   Points: {current_point_count:,}")
                    
                    from gui.save_pointcloud import save_pointcloud_quick
                    result = save_pointcloud_quick(self.app, save_path)
                    
                    if result:
                        print(f"✅ Saved successfully")
                        if hasattr(self.app, "statusBar"):
                            self.app.statusBar().showMessage(f"💾 Saved: {os.path.basename(save_path)}", 2000)
                            QCoreApplication.processEvents()
                    else:
                        print(f"⚠️ Save returned False")
                        
                except Exception as e:
                    print(f"❌ SAVE FAILED: {e}")
                    # Continue loading even if save fails (or ask user)
                    pass

        # ============================================================================
        # STEP 2: CLEAR GRID TRACKING
        # ============================================================================
        self.loaded_grids.clear()

       # ============================================================================
        # SAVE CAMERA STATE BEFORE CLEARING
        # ============================================================================
        saved_camera_state = None
        if hasattr(self.app, "vtk_widget") and self.app.vtk_widget:
            try:
                camera = self.app.vtk_widget.renderer.GetActiveCamera()
                saved_camera_state = {
                    'position': camera.GetPosition(),
                    'focal_point': camera.GetFocalPoint(),
                    'view_up': camera.GetViewUp(),
                    'parallel_scale': camera.GetParallelScale(),
                    'parallel_projection': camera.GetParallelProjection()
                }
                print(f"💾 Camera state saved (zoom: {saved_camera_state['parallel_scale']:.2f})")
            except Exception as e:
                print(f"⚠️ Could not save camera state: {e}")
        
        # Backup DXF actors
        dxf_backup = []
        if hasattr(self.app, 'dxf_actors') and self.app.dxf_actors:
            for dxf_data in self.app.dxf_actors:
                for actor in dxf_data.get('actors', []):
                    dxf_backup.append(actor)
            
            if dxf_backup:
                renderer = self.app.vtk_widget.renderer
                for actor in dxf_backup:
                    renderer.RemoveActor(actor)
                print(f"   💾 Backed up {len(dxf_backup)} DXF actors")
        
        # Clear VTK completely
        if hasattr(self.app, "vtk_widget") and self.app.vtk_widget:
            renderer = self.app.vtk_widget.renderer
            renderer.RemoveAllViewProps()
            
            if hasattr(self.app.vtk_widget, 'actors'):
                self.app.vtk_widget.actors.clear()
            if hasattr(self.app.vtk_widget, '_actors'):
                self.app.vtk_widget._actors.clear()
            
            self.app.vtk_widget.render()
            print(f"   ✅ VTK cleared")
        
        # Clear cross-sections
        if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
            for view_idx, vtk_widget in self.app.section_vtks.items():
                try:
                    vtk_widget.renderer.RemoveAllViewProps()
                    if hasattr(vtk_widget, 'actors'):
                        vtk_widget.actors.clear()
                    vtk_widget.render()
                except Exception:
                    pass
            print(f"   ✅ Cross-sections cleared")
        
        # Clear ALL internal state - SAME AS MENU BAR
        self.app.data = None
        self.app.loaded_file = None
        self.app.last_save_path = None
        self.app.class_palette = {}
        
        if hasattr(self.app, "view_palettes"):
            self.app.view_palettes.clear()
        
        if hasattr(self.app, 'undo_stack'):
            self.app.undo_stack.clear()
        if hasattr(self.app, 'redo_stack'):
            self.app.redo_stack.clear()
        
        if hasattr(self.app, 'spatial_index'):
            self.app.spatial_index = None
        
        print(f"   ✅ All data cleared")
        
        QCoreApplication.processEvents()
        
        # Restore DXF actors
        if dxf_backup:
            renderer = self.app.vtk_widget.renderer
            for actor in dxf_backup:
                renderer.AddActor(actor)
            self.app.vtk_widget.render()
            QCoreApplication.processEvents()
            print(f"   ✅ Restored {len(dxf_backup)} DXF actors")
        
        print(f"{'='*60}")
        print(f"✅ CLEAR COMPLETE")
        print(f"{'='*60}\n")

        # ============================================================================
        # STEP 4: LOAD FILE - SAME AS MENU BAR
        # ============================================================================
        print(f"{'='*60}")
        print(f"📂 LOADING FILE - SAME AS MENU BAR")
        print(f"{'='*60}")
        
        progress = LoadingProgressDialog(self.app, show_cancel=False)
        progress.set_filename(os.path.basename(str(las_file)))
        progress.show()

        def update_progress(percent, status, force=False):
            if force or not hasattr(update_progress, '_last_update'):
                progress.set_progress(percent)
                progress.set_status(status)
                QCoreApplication.processEvents()
                update_progress._last_update = time.time()
            else:
                if time.time() - update_progress._last_update > 0.2:
                    progress.set_progress(percent)
                    progress.set_status(status)
                    QCoreApplication.processEvents()
                    update_progress._last_update = time.time()

        load_start = time.time()

        try:
            # ============================================================================
            # LOAD THE FILE - SAME AS MENU BAR
            # ============================================================================
            update_progress(10, "Loading file...", force=True)
            
            from gui.data_loader import load_lidar_file
            
            tile_data = load_lidar_file(str(las_file), parent=self.app)
            
            if not tile_data:
                progress.finish_error("Load cancelled or failed")
                return
            
            total_points = len(tile_data.get('xyz', []))
            print(f"   ✅ Loaded {total_points:,} points")
            
            
            # ============================================================================
            # 🔍 DEBUG: VERIFY CORRECT FILE WAS LOADED
            # ============================================================================
            print(f"\n{'='*70}")
            print(f"🔍 FILE LOAD VERIFICATION")
            print(f"{'='*70}")
            print(f"   Requested Grid: {grid_name}")
            print(f"   Loaded File: {las_file.name}")
            print(f"   Full Path: {las_file}")

            # Calculate center of loaded data
            center = np.mean(tile_data['xyz'], axis=0)
            print(f"   Data Center: [{center[0]:.1f}, {center[1]:.1f}, {center[2]:.1f}]")

            # Calculate bounds
            xyz = tile_data['xyz']
            bounds = {
                'x_min': np.min(xyz[:, 0]),
                'x_max': np.max(xyz[:, 0]),
                'y_min': np.min(xyz[:, 1]),
                'y_max': np.max(xyz[:, 1]),
            }
            print(f"   Bounds:")
            print(f"      X: {bounds['x_min']:.1f} to {bounds['x_max']:.1f}")
            print(f"      Y: {bounds['y_min']:.1f} to {bounds['y_max']:.1f}")

            # Try to read file header directly to confirm
            try:
                import laspy
                with laspy.open(str(las_file)) as f:
                    header = f.header
                    print(f"   LAS Header Info:")
                    print(f"      Point Count: {header.point_count:,}")
                    print(f"      X Range: {header.x_min:.1f} to {header.x_max:.1f}")
                    print(f"      Y Range: {header.y_min:.1f} to {header.y_max:.1f}")
            except Exception as e:
                print(f"   ⚠️ Could not read LAS header: {e}")

            print(f"{'='*70}\n")
            # =====================
            
            # ============================================================================
            # SET DATA - SAME AS MENU BAR
            # ============================================================================
            update_progress(50, "Setting data...", force=True)
            
            # ✅ COORDINATE FIX: Detect if point cloud coords are wildly off from grid coords
            # Only triggers for MASSIVE mismatches (>100km) caused by missing LAS header offsets
            # e.g., point cloud at [5558, 45034] instead of [555800, 4503400]
            loaded_xyz = tile_data["xyz"]
            try:
                loaded_center = np.mean(loaded_xyz, axis=0)
                
                # Compute grid center from ALL actor bounds (not just first one)
                all_x_min, all_x_max = float('inf'), float('-inf')
                all_y_min, all_y_max = float('inf'), float('-inf')
                found_bounds = False
                
                for store_name in ('snt_actors', 'dxf_actors'):
                    store = getattr(self.app, store_name, None)
                    if store:
                        for entry in store:
                            for actor in entry.get('actors', []):
                                try:
                                    b = actor.GetBounds()
                                    if b and (b[1] - b[0]) > 0.1 and (b[3] - b[2]) > 0.1:
                                        all_x_min = min(all_x_min, b[0])
                                        all_x_max = max(all_x_max, b[1])
                                        all_y_min = min(all_y_min, b[2])
                                        all_y_max = max(all_y_max, b[3])
                                        found_bounds = True
                                except Exception:
                                    continue
                
                if found_bounds:
                    grid_center = np.array([
                        (all_x_min + all_x_max) / 2,
                        (all_y_min + all_y_max) / 2,
                        0
                    ])
                    dist_xy = np.sqrt((loaded_center[0] - grid_center[0])**2 + 
                                     (loaded_center[1] - grid_center[1])**2)
                    
                    # Only trigger for MASSIVE mismatches (>100km = missing LAS offset)
                    # Normal DXF grids can span 10-20km, so 100km threshold prevents false positives
                    if dist_xy > 100_000:
                        print(f"   ⚠️ COORDINATE MISMATCH DETECTED!")
                        print(f"      Point cloud center: [{loaded_center[0]:.1f}, {loaded_center[1]:.1f}]")
                        print(f"      Grid center: [{grid_center[0]:.1f}, {grid_center[1]:.1f}]")
                        print(f"      Distance: {dist_xy:.0f}m — applying LAS header offset...")
                        
                        try:
                            import laspy
                            with laspy.open(str(las_file)) as f:
                                hdr = f.header
                                hdr_center_x = (hdr.x_min + hdr.x_max) / 2
                                hdr_center_y = (hdr.y_min + hdr.y_max) / 2
                                
                                hdr_dist = np.sqrt((hdr_center_x - grid_center[0])**2 + 
                                                   (hdr_center_y - grid_center[1])**2)
                                
                                if hdr_dist < dist_xy:
                                    offset_x = hdr_center_x - loaded_center[0]
                                    offset_y = hdr_center_y - loaded_center[1]
                                    
                                    # Only apply if offset is significant (>10km)
                                    if abs(offset_x) > 10_000 or abs(offset_y) > 10_000:
                                        print(f"      LAS header center: [{hdr_center_x:.1f}, {hdr_center_y:.1f}]")
                                        print(f"      Applying offset: [{offset_x:.1f}, {offset_y:.1f}]")
                                        loaded_xyz[:, 0] += offset_x
                                        loaded_xyz[:, 1] += offset_y
                                        tile_data["xyz"] = loaded_xyz
                                        new_center = np.mean(loaded_xyz, axis=0)
                                        print(f"      ✅ Corrected center: [{new_center[0]:.1f}, {new_center[1]:.1f}]")
                                    else:
                                        print(f"      ⚠️ Offset too small ({offset_x:.1f}, {offset_y:.1f}) — skipping")
                                else:
                                    print(f"      ⚠️ Header coords also don't match grid — skipping")
                        except Exception as e:
                            print(f"      ⚠️ Could not read LAS header: {e}")
                    else:
                        print(f"   ✅ Coordinates match grid (distance: {dist_xy:.0f}m)")
            except Exception as e:
                print(f"   ⚠️ Coordinate check failed: {e}")
            
            self.app.data = {
                "xyz": tile_data["xyz"],
                "classification": tile_data["classification"]
            }
            
            if tile_data.get("rgb") is not None:
                self.app.data["rgb"] = tile_data["rgb"]
            if tile_data.get("intensity") is not None:
                self.app.data["intensity"] = tile_data["intensity"]
            
            # Set CRS - SAME AS MENU BAR
            if tile_data.get("crs_epsg"):
                self.app.project_crs_epsg = tile_data["crs_epsg"]
                self.app.project_crs_wkt = tile_data.get("crs_wkt")
                
                try:
                    from pyproj import CRS
                    self.app.crs = CRS.from_epsg(tile_data["crs_epsg"])
                    print(f"   📐 CRS: {self.app.crs.name}")
                except Exception:
                    pass
            
            # Store as layer - SAME AS MENU BAR
            layer = {
                "type": "laz_tile",
                "filename": str(las_file),
                "xyz": tile_data["xyz"],
                "classification": tile_data.get("classification"),
                "rgb": tile_data.get("rgb"),
                "intensity": tile_data.get("intensity"),
                "crs_epsg": tile_data.get("crs_epsg"),
                "visible": True,
            }
            
            if hasattr(self.app, 'layers'):
                self.app.layers.append(layer)
            
            if hasattr(self.app, 'layers_dock') and self.app.layers_dock:
                self.app.layers_dock.add_layer(layer)
            
            # Set file paths
            self.app.loaded_file = str(las_file)
            self.app.last_save_path = str(las_file)
            
            # ============================================================================
            # BUILD DEM FOR SHADING - SAME AS MENU BAR
            # ============================================================================
            try:
                from gui.shading_display import build_base_dem_mesh
                build_base_dem_mesh(self.app, percentile_filter=99.9, downsample=2)
            except Exception:
                pass
            
            # ============================================================================
            # BUILD SPATIAL INDEX - SAME AS MENU BAR
            # ============================================================================
            if total_points > 50_000:
                try:
                    update_progress(70, "Building spatial index...", force=True)
                    from gui.performance_optimizations import SpatialIndex
                    self.app.spatial_index = SpatialIndex(self.app.data["xyz"])
                    print(f"   ✅ Spatial index built")
                except Exception as e:
                    print(f"   ⚠️ Spatial index failed: {e}")
                    self.app.spatial_index = None
            
            # ============================================================================
            # RESTORE DISPLAY SETTINGS - SAME AS MENU BAR
            # ============================================================================
            update_progress(75, "Restoring settings...", force=True)
            
            # Set default display mode first
            self.app.display_mode = "class"
            
            try:
                from gui.display_mode import restore_display_settings_for_file
                restore_display_settings_for_file(self.app, str(las_file))
            except Exception:
                pass
            
            # ============================================================================
            # LOAD PALETTE - SAME AS MENU BAR
            # ============================================================================
            update_progress(80, "Loading palette...", force=True)
            
            palette_to_apply = None
            if hasattr(self.app, '_get_palette_for_file'):
                palette_to_apply = self.app._get_palette_for_file(str(las_file))
            
            # ============================================================================
            # APPLY PALETTE AND RENDER - SAME AS MENU BAR
            # ============================================================================
            # This is critical for per-class visibility and updates!
            
            if palette_to_apply:
                visible_count = len([c for c, v in palette_to_apply.items() if v.get("show")])
                update_progress(85, f"Rendering {visible_count} classes...", force=True)
                
                print(f"🎨 Applying palette with {visible_count} visible classes...")
                
                # Apply palette which will create Per-Class Actors
                self.app.apply_class_map({
                    "classes": palette_to_apply,
                    "slot": 0,
                    "color_mode": 0,
                    "target_view": 0
                })
            else:
                # Fallback: build palette from classification
                update_progress(85, "Building palette...", force=True)
                
                try:
                    from gui.class_display import build_class_palette, update_class_mode
                    self.app.class_palette = build_class_palette(tile_data['classification'])
                    print(f"   ✅ Built palette: {len(self.app.class_palette)} classes")
                    
                    # Use apply_class_map for consistent behavior (creates per-class actors)
                    self.app.apply_class_map({
                        "classes": self.app.class_palette,
                        "slot": 0,
                        "color_mode": 0,
                        "target_view": 0
                    })
                except Exception as e:
                    print(f"   ⚠️ Palette build failed: {e}")
                    # Ultimate fallback (creates unified cloud - NOT ideal but works)
                    from gui.pointcloud_display import update_pointcloud
                    update_pointcloud(self.app, "class")
            
            # ============================================================================
            # RESTORE CAMERA STATE (preserve zoom when loading into DXF)
            # ============================================================================
            if saved_camera_state:
                try:
                    camera = self.app.vtk_widget.renderer.GetActiveCamera()
                    camera.SetPosition(saved_camera_state['position'])
                    camera.SetFocalPoint(saved_camera_state['focal_point'])
                    camera.SetViewUp(saved_camera_state['view_up'])
                    camera.SetParallelScale(saved_camera_state['parallel_scale'])
                    camera.SetParallelProjection(saved_camera_state['parallel_projection'])
                    self.app.vtk_widget.renderer.ResetCameraClippingRange()
                    print(f"📷 Camera restored (zoom: {saved_camera_state['parallel_scale']:.2f})")
                except Exception as e:
                    print(f"⚠️ Camera restore failed: {e}")
            
            # ============================================================================
            # FINALIZE - SAME AS MENU BAR
            # ============================================================================
            update_progress(95, "Finalizing...", force=True)
            
            try:
                from gui.pointcloud_display import force_interactor_ready
                force_interactor_ready(self.app, delay_ms=300)
            except Exception:
                pass
            
            # Toggle view mode - BUT DON'T RESET CAMERA IF WE SAVED STATE
            if hasattr(self.app, 'toggle_view_mode'):
                if saved_camera_state is None:
                    # First load - reset to 2D view
                    self.app.toggle_view_mode("2d")
                else:
                    # Loading into DXF - preserve camera
                    print("📷 Skipping view reset (preserving zoom)")
            
            # ✅ RESTORE CAMERA STATE AFTER VIEW MODE (this is the key!)
            # ✅ RESTORE CAMERA STATE AFTER VIEW MODE WITH SMART ADJUSTMENT
            if saved_camera_state:
                try:
                    import numpy as np
                    camera = self.app.vtk_widget.renderer.GetActiveCamera()
                    
                    # Calculate the offset between old and new data centers
                    new_data_center = np.mean(self.app.data['xyz'], axis=0)
                    old_focal_point = np.array(saved_camera_state['focal_point'])
                    
                    # Calculate the shift needed to center on new data
                    shift = new_data_center - old_focal_point
                    
                    # Apply the shift to camera position and focal point
                    new_position = np.array(saved_camera_state['position']) + shift
                    new_focal_point = old_focal_point + shift
                    
                    # Restore camera with adjusted position
                    camera.SetPosition(new_position[0], new_position[1], new_position[2])
                    camera.SetFocalPoint(new_focal_point[0], new_focal_point[1], new_focal_point[2])
                    camera.SetViewUp(saved_camera_state['view_up'])
                    camera.SetParallelScale(saved_camera_state['parallel_scale'])  # ✅ Preserves zoom!
                    camera.SetParallelProjection(saved_camera_state['parallel_projection'])
                    
                    self.app.vtk_widget.renderer.ResetCameraClippingRange()
                    self.app.vtk_widget.render()
                    
                    print(f"📷 Camera restored with smart adjustment")
                    print(f"   Zoom: {saved_camera_state['parallel_scale']:.2f}")
                    print(f"   Old center: [{old_focal_point[0]:.1f}, {old_focal_point[1]:.1f}]")
                    print(f"   New center: [{new_data_center[0]:.1f}, {new_data_center[1]:.1f}]")
                    print(f"   Shift: [{shift[0]:.1f}, {shift[1]:.1f}]")
                except Exception as e:
                    print(f"⚠️ Camera restore failed: {e}")
                    import traceback
                    traceback.print_exc()
            
            if hasattr(self.app, 'ensure_main_view_2d_interaction'):
                self.app.ensure_main_view_2d_interaction(
                    preserve_camera=True,
                    reason=f"grid load: {grid_name}",
                )

            # Update title with grid name
            self.app._update_window_title(
                f"{grid_name} ({total_points:,} pts)", 
                getattr(self.app, 'project_crs_epsg', None)
            )
            
            # ============================================================================
            # AUTO-LOAD DRAWINGS - SAME AS MENU BAR
            # ============================================================================
            if hasattr(self.app, "digitizer") and self.app.digitizer:
                try:
                    self.app.digitizer.auto_load_drawings(str(las_file))
                except Exception:
                    pass
            
            # ============================================================================
            # UPDATE STATISTICS - SAME AS MENU BAR
            # ============================================================================
            if hasattr(self.app, 'point_count_widget') and self.app.point_count_widget:
                try:
                    from gui.point_count_widget import refresh_point_statistics
                    refresh_point_statistics(self.app)
                except Exception:
                    pass
            
            # ============================================================================
            # TRACK GRID (additional for grid system)
            # ============================================================================
            grid_indices = np.arange(total_points)
            self.loaded_grids[grid_name] = grid_indices
            
            if not hasattr(self.app, 'original_file_paths'):
                self.app.original_file_paths = {}
            self.app.original_file_paths[grid_name] = str(las_file)
            
            print(f"   📍 Tracked grid: {grid_name}")
            
            # ============================================================================
            # COMPLETE
            # ============================================================================
            total_time = time.time() - load_start
            
            print(f"\n{'='*60}")
            print(f"✅ GRID LOAD COMPLETE - SAME AS MENU BAR")
            print(f"   Grid: {grid_name}")
            print(f"   Points: {total_points:,}")
            print(f"   Time: {total_time:.1f}s")
            print(f"{'='*60}\n")
            
            # ✅ BULLETPROOF: Re-ensure all DXF/SNT overlay actors are in renderer
            # Some code paths during load (build_unified_actor, apply_class_map, etc.)
            # may have removed actors. This guarantees they're always visible.
            if hasattr(self.app, '_ensure_overlay_actors'):
                self.app._ensure_overlay_actors()
            
            progress.finish_success(f"Loaded {total_points:,} points in {total_time:.1f}s")
            
            # Show success message
            QMessageBox.information(
                self.app,
                "Grid Loaded",
                f"✅ Loaded: {grid_name}\n\n"
                f"File: {las_file.name}\n"
                f"Points: {total_points:,}"
            )
            
        except Exception as e:
            print(f"❌ Load failed: {e}")
            import traceback
            traceback.print_exc()
            progress.finish_error(f"Load failed: {e}")
            QMessageBox.critical(self.app, "Load Error", f"Failed to load: {e}")

    def _save_folder_to_settings(self, folder_path):
        """Save LAZ/LAS folder to settings for future use"""
        self.settings.setValue("last_las_folder", str(folder_path))
        self.settings.sync()
        print(f"💾 Saved LAZ folder: {folder_path}")
        
    def clear_grid_data(self, grid_name):
        """Delete points belonging to a specific grid from the loaded dataset"""
        print(f"\n{'='*60}")
        print(f"🗑️ DELETING GRID DATA: {grid_name}")
        print(f"{'='*60}\n")
        
        # Check if grid is tracked
        if grid_name not in self.loaded_grids:
            QMessageBox.warning(
                self.app,
                "Grid Not Found",
                f"Grid '{grid_name}' is not currently loaded.\n\n"
                f"Only grids loaded via grid label click can be deleted."
            )
            return
        
        # Confirm deletion
        points_to_delete = len(self.loaded_grids[grid_name])
        reply = QMessageBox.question(
            self.app,
            "Confirm Clear",
            f"Clear all points from grid:\n{grid_name}\n\n"
            f"Points: {points_to_delete:,}\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        try:
            import numpy as np
            from gui.pointcloud_display import update_pointcloud
            from PySide6.QtCore import QCoreApplication
            
            # Get total points before any operations
            total_points = len(self.app.data['xyz'])
            
            # ✅ FIX: Validate indices before using them
            indices_to_delete = self.loaded_grids[grid_name]
            indices_to_delete = self._validate_grid_indices(
                grid_name, indices_to_delete, total_points
            )
            
            if len(indices_to_delete) == 0:
                print(f"  ⚠️ No valid indices to delete")
                del self.loaded_grids[grid_name]
                QMessageBox.warning(
                    self.app,
                    "No Valid Points",
                    f"Grid '{grid_name}' has no valid point indices.\n"
                    f"The grid tracking has been cleared."
                )
                return
            
            # ✅ OPTIMIZED: Use boolean mask (much faster than index manipulation)
            print(f"  🔄 Creating deletion mask...")
            QCoreApplication.processEvents()
            
            keep_mask = np.ones(total_points, dtype=bool)
            keep_mask[indices_to_delete] = False
            
            remaining = np.sum(keep_mask)
            print(f"  Remaining: {remaining:,}")
            
            # ✅ OPTIMIZED: Filter all arrays in one pass
            print(f"  🔄 Filtering point data...")
            QCoreApplication.processEvents()
            
            self.app.data['xyz'] = self.app.data['xyz'][keep_mask]
            self.app.data['classification'] = self.app.data['classification'][keep_mask]
            
            if 'rgb' in self.app.data and self.app.data['rgb'] is not None:
                self.app.data['rgb'] = self.app.data['rgb'][keep_mask]
            
            if 'intensity' in self.app.data and self.app.data['intensity'] is not None:
                self.app.data['intensity'] = self.app.data['intensity'][keep_mask]
            
            # ✅ OPTIMIZED: Vectorized index updating for remaining grids
            print(f"  🔄 Updating grid tracking...")
            QCoreApplication.processEvents()
            
            if len(self.loaded_grids) > 1:
                # Create mapping: old_index -> new_index
                # This is MUCH faster than looping
                old_to_new = np.full(total_points, -1, dtype=np.int64)
                old_to_new[keep_mask] = np.arange(remaining)
                
                # Update all other grids in one vectorized operation
                for other_grid in list(self.loaded_grids.keys()):
                    if other_grid == grid_name:
                        continue
                    
                    old_indices = self.loaded_grids[other_grid]
                    new_indices = old_to_new[old_indices]
                    
                    # Filter out any invalid indices (shouldn't happen, but safety check)
                    valid = new_indices >= 0
                    self.loaded_grids[other_grid] = new_indices[valid]
                    
                    print(f"     Updated {other_grid}: {len(old_indices)} -> {len(new_indices[valid])} indices")
            
            # Remove deleted grid
            del self.loaded_grids[grid_name]
            
            print(f"  🔄 Rebuilding spatial index...")
            QCoreApplication.processEvents()
            
            # Rebuild spatial index if it exists
            if hasattr(self.app, 'spatial_index') and remaining > 50_000:
                try:
                    from gui.performance_optimizations import SpatialIndex
                    self.app.spatial_index = SpatialIndex(self.app.data["xyz"])
                    print(f"  ✅ Spatial index rebuilt")
                except Exception as e:
                    print(f"  ⚠️ Spatial index rebuild failed: {e}")
                    self.app.spatial_index = None
            
            # Update display
            print(f"  🔄 Updating display...")
            QCoreApplication.processEvents()
            
            
            # ✅ CHECK: If no points remain, clear everything
            if remaining == 0:
                print(f"  ⚠️ No points remaining - clearing scene")
                
                # Clear the renderer
                if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget:
                    self.app.vtk_widget.renderer.RemoveAllViewProps()
                    self.app.vtk_widget.render()
                
                # Reset data
                self.app.data = None
                self.app.loaded_file = None
                self.app.last_save_path = None
                
                # Update title
                self.app._update_window_title("No Data", None)
                
                # Restore DXF if exists
                if hasattr(self.app, 'preserve_dxf_actors'):
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(100, self.app.preserve_dxf_actors)
                
                QMessageBox.information(
                    self.app,
                    "All Grids Cleared",
                    f"✅ Cleared: {grid_name}\n\n"
                    f"All points removed.\n"
                    f"Load a new grid to continue."
                )
                
                print(f"✅ Scene cleared completely")
                return
            
            update_pointcloud(self.app, self.app.display_mode)
            
            # Restore DXF
            if hasattr(self.app, 'preserve_dxf_actors'):
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self.app.preserve_dxf_actors)
            
            # Update UI
            self.app._update_window_title(
                f"Multiple Grids ({remaining:,} pts)",
                self.app.project_crs_epsg
            )
            
            if hasattr(self.app, 'point_count_widget') and self.app.point_count_widget:
                from gui.point_count_widget import refresh_point_statistics
                refresh_point_statistics(self.app)
            
            print(f"✅ Grid deleted successfully")
            print(f"{'='*60}\n")
            
            QMessageBox.information(
                self.app,
                "Grid Cleared",
                f"✅ Cleared: {grid_name}\n\n"
                f"Removed: {points_to_delete:,} points\n"
                f"Remaining: {remaining:,} points"
            )
            self.app.last_save_path = None  # Clear save path so auto-save won't overwrite
            print(f"  ℹ️ Cleared save path - original file will not be overwritten")
        except Exception as e:
            print(f"❌ Delete failed: {e}")
            import traceback
            traceback.print_exc()
            
            QMessageBox.critical(
                self.app,
                "Delete Error",
                f"Failed to delete grid '{grid_name}':\n\n{str(e)}"
            )
            
            
    def setup_interactor(self):
        """Attach observers to main VTK widget"""
        if not hasattr(self.app, 'vtk_widget'):
            print("⚠️ No VTK widget found")
            return
        
        interactor = self.app.vtk_widget.interactor
        
        # ✨ NEW: Add keyboard shortcut for rectangle selection
        
        print("✅ Grid label system enabled (Press 'D' to delete grid by area)")

    def setup_interactor(self):
        """Attach observers to main VTK widget."""
        if not hasattr(self.app, 'vtk_widget'):
            print("No VTK widget found")
            return

        self.ensure_interactor_observers()
        print("Grid label system enabled (Press 'D' to delete grid by area)")

    def on_key_press(self, obj, event):
        """Handle keyboard shortcuts"""
        key = self.app.vtk_widget.interactor.GetKeySym()
        
        if key == 'd' or key == 'D':
            self._start_rectangle_delete_mode()

    def _start_rectangle_delete_mode(self):
        """Start interactive rectangle selection for deletion"""
        from PySide6.QtWidgets import QMessageBox
        
        QMessageBox.information(
            self.app,
            "Rectangle Delete Mode",
            "📦 RECTANGLE DELETE MODE\n\n"
            "1. Click and drag to draw a rectangle\n"
            "2. Release to select the grid area\n"
            "3. Confirm deletion\n\n"
            "Press ESC to cancel"
        )
        
        # Use VTK's rubber band picker
        style = vtk.vtkInteractorStyleRubberBandPick()
        self.app.vtk_widget.interactor.SetInteractorStyle(style)
        
        # Add observer for selection complete
        style.AddObserver("EndPickEvent", self._on_rectangle_selected)
        
        self._temp_style = style  # Store to restore later

    def _on_rectangle_selected(self, obj, event):
        """Handle rectangle selection complete"""
        import numpy as np
        from PySide6.QtWidgets import QInputDialog
        
        # Get selected area
        style = obj
        x1, y1, x2, y2 = style.GetStartPosition() + style.GetEndPosition()
        
        # Use area picker
        area_picker = vtk.vtkAreaPicker()
        area_picker.AreaPick(x1, y1, x2, y2, self.app.vtk_widget.renderer)
        
        # Get frustum (selection volume)
        frustum = area_picker.GetFrustum()
        
        if not frustum or not hasattr(self.app, 'data'):
            self._restore_normal_interaction()
            return
        
        # Find points inside selection
        points_xyz = self.app.data['xyz']
        
        # Convert to VTK points for frustum testing
        selected_indices = []
        
        for i, point in enumerate(points_xyz):
            vtk_point = vtk.vtkPoints()
            vtk_point.InsertNextPoint(point[0], point[1], point[2])
            
            # Check if point is inside frustum
            if frustum.EvaluateFunction(point[0], point[1], point[2]) < 0:
                selected_indices.append(i)
        
        selected_indices = np.array(selected_indices)
        
        if len(selected_indices) == 0:
            QMessageBox.warning(self.app, "No Points", "No points selected in this area")
            self._restore_normal_interaction()
            return
        
        # Ask for grid name or auto-detect
        grid_name, ok = QInputDialog.getText(
            self.app,
            "Delete Grid",
            f"Selected: {len(selected_indices):,} points\n\n"
            f"Enter grid name to delete:"
        )
        
        if ok and grid_name:
            # Track and delete
            self.loaded_grids[grid_name] = selected_indices
            self.delete_grid_data(grid_name)
        
        self._restore_normal_interaction()

    def _restore_normal_interaction(self):
        """Restore normal camera interaction"""
        if hasattr(self.app, 'ensure_main_view_2d_interaction') and not getattr(self.app, 'is_3d_mode', False):
            self.app.ensure_main_view_2d_interaction(
                preserve_camera=True,
                reason="grid_label_restore",
            )
            return

        style = vtk.vtkInteractorStyleTrackballCamera()
        self.app.vtk_widget.interactor.SetInteractorStyle(style)

    def _validate_grid_indices(self, grid_name, indices, current_data_size):
        """
        Validate that grid indices are within bounds of current data.
        Returns cleaned indices array.
        """
        import numpy as np
        
        if indices is None or len(indices) == 0:
            return np.array([], dtype=np.int64)
        
        # Check if any indices are out of bounds
        max_index = np.max(indices)
        if max_index >= current_data_size:
            print(f"  ⚠️ WARNING: Grid '{grid_name}' has invalid indices")
            print(f"     Max index: {max_index}, Data size: {current_data_size}")
            print(f"     Filtering out-of-bounds indices...")
            
            # Keep only valid indices
            valid_mask = indices < current_data_size
            valid_indices = indices[valid_mask]
            
            invalid_count = len(indices) - len(valid_indices)
            if invalid_count > 0:
                print(f"     Removed {invalid_count} invalid indices")
            
            return valid_indices
        
        return indices        
    
    def verify_dxf_labels(self):
        """Debug tool: Compare DXF label positions with actual LAZ file centers"""
        import laspy
        from pathlib import Path
        from PySide6.QtWidgets import QMessageBox, QTextEdit, QVBoxLayout, QDialog, QPushButton
        
        # Find LAZ folder automatically
        las_folder = self._find_las_folder_from_dxf()
        
        if not las_folder:
            QMessageBox.warning(
                self.app,
                "No LAZ Folder",
                "Could not locate LAZ/LAS folder.\n\n"
                "Please load a DXF file first."
            )
            return
        
        print(f"\n{'='*70}")
        print(f"🔍 DXF LABEL VERIFICATION")
        print(f"{'='*70}\n")
        
        # Get all label positions from DXF
        label_positions = {}
        if hasattr(self.app, 'dxf_actors') and self.app.dxf_actors:
            for dxf_data in self.app.dxf_actors:
                for actor in dxf_data.get('actors', []):
                    if hasattr(actor, 'is_grid_label') and actor.is_grid_label:
                        grid_name = getattr(actor, 'grid_name', '')
                        if grid_name:
                            pos = actor.GetPosition()
                            label_positions[grid_name] = pos
        
        if not label_positions:
            QMessageBox.warning(
                self.app,
                "No Labels Found",
                "No grid labels found in DXF.\n\n"
                "Make sure you've loaded a DXF with grid labels."
            )
            return
        
        # Build verification report
        report_lines = []
        misaligned_count = 0
        total_count = 0
        
        # Get all LAZ file centers
        las_folder_path = Path(las_folder)
        for las_file in sorted(las_folder_path.glob("*.laz")):
            try:
                with laspy.open(las_file) as f:
                    header = f.header
                    center_x = (header.x_min + header.x_max) / 2
                    center_y = (header.y_min + header.y_max) / 2
                    
                    grid_name = las_file.stem
                    total_count += 1
                    
                    if grid_name in label_positions:
                        label_pos = label_positions[grid_name]
                        distance = np.sqrt(
                            (center_x - label_pos[0])**2 + 
                            (center_y - label_pos[1])**2
                        )
                        
                        # Consider misaligned if >500m away
                        is_misaligned = distance > 500
                        if is_misaligned:
                            misaligned_count += 1
                        
                        status = "❌ MISALIGNED" if is_misaligned else "✅ OK"
                        
                        report_lines.append(f"{status} {grid_name}:")
                        report_lines.append(f"   Label Position: [{label_pos[0]:.1f}, {label_pos[1]:.1f}]")
                        report_lines.append(f"   Data Center:    [{center_x:.1f}, {center_y:.1f}]")
                        report_lines.append(f"   Distance: {distance:.1f}m")
                        report_lines.append("")
                        
                        # Print to console too
                        print(f"{status} {grid_name}:")
                        print(f"   Label: [{label_pos[0]:.1f}, {label_pos[1]:.1f}]")
                        print(f"   Data:  [{center_x:.1f}, {center_y:.1f}]")
                        print(f"   Distance: {distance:.1f}m\n")
                    else:
                        report_lines.append(f"⚠️ {grid_name}: No label found in DXF")
                        report_lines.append("")
                        print(f"⚠️ {grid_name}: No label found in DXF\n")
                        
            except Exception as e:
                report_lines.append(f"❌ {las_file.name}: Error reading file - {e}")
                report_lines.append("")
                print(f"❌ {las_file.name}: {e}\n")
        
        print(f"{'='*70}\n")
        
        # Create dialog to show results
        dialog = QDialog(self.app)
        dialog.setWindowTitle("DXF Label Verification")
        dialog.resize(700, 500)
        
        layout = QVBoxLayout()
        
        # Summary
        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setMaximumHeight(80)
        
        summary_text = f"""📊 VERIFICATION SUMMARY
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    Total LAZ files: {total_count}
    Labels in DXF: {len(label_positions)}
    Misaligned (>500m): {misaligned_count}
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """
        summary.setPlainText(summary_text)
        layout.addWidget(summary)
        
        # Detailed report
        report = QTextEdit()
        report.setReadOnly(True)
        report.setPlainText("\n".join(report_lines))
        layout.addWidget(report)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.setLayout(layout)
        dialog.exec()

    
    def list_all_text_in_dxf(self):
        """Debug: List all text actors in the scene - FIXED VERSION"""
        from PySide6.QtWidgets import QTextEdit, QDialog, QVBoxLayout, QPushButton
        import vtk
        
        text_actors = []
        
        if hasattr(self.app, 'dxf_actors') and self.app.dxf_actors:
            for dxf_data in self.app.dxf_actors:
                for actor in dxf_data.get('actors', []):
                    pos = actor.GetPosition()
                    
                    # Try multiple methods to get text content
                    text_content = "Unknown"
                    is_text_actor = False
                    
                    # Method 1: Check for custom properties we set
                    if hasattr(actor, 'grid_name'):
                        text_content = actor.grid_name
                        is_text_actor = True
                    elif hasattr(actor, 'text_content'):
                        text_content = actor.text_content
                        is_text_actor = True
                    
                    # Method 2: Check if it's a vtkTextActor3D
                    elif isinstance(actor, vtk.vtkTextActor3D):
                        text_content = actor.GetInput()
                        is_text_actor = True
                    
                    # Method 3: Check if it's a vtkFollower with vector text source
                    elif isinstance(actor, (vtk.vtkFollower, vtk.vtkActor)):
                        mapper = actor.GetMapper()
                        if mapper:
                            input_data = mapper.GetInput()
                            
                            # Check if it's from a vtkVectorText source
                            if input_data and hasattr(mapper, 'GetInputAlgorithm'):
                                algo = mapper.GetInputAlgorithm()
                                if isinstance(algo, vtk.vtkVectorText):
                                    text_content = algo.GetText()
                                    is_text_actor = True
                            
                            # Alternative: Check if it's a very small polydata (likely text)
                            elif input_data and input_data.GetNumberOfPoints() < 1000:
                                # Small polydata might be text
                                # Check point data for clues
                                if hasattr(input_data, 'GetPointData'):
                                    point_data = input_data.GetPointData()
                                    if point_data.GetNumberOfArrays() > 0:
                                        is_text_actor = True
                                        # Still unknown text but we know it's text-like
                    
                    # Method 4: Check property metadata
                    if not is_text_actor and hasattr(actor, 'GetProperty'):
                        prop = actor.GetProperty()
                        # Text actors often have specific rendering properties
                        if prop and prop.GetRepresentation() == vtk.VTK_SURFACE:
                            mapper = actor.GetMapper()
                            if mapper and mapper.GetInput():
                                num_points = mapper.GetInput().GetNumberOfPoints()
                                # Text typically has moderate point counts
                                if 10 < num_points < 2000:
                                    is_text_actor = True
                    
                    # Only add if we detected it as text
                    if is_text_actor:
                        is_label = hasattr(actor, 'is_grid_label') and actor.is_grid_label
                        
                        text_actors.append({
                            'text': text_content,
                            'position': pos,
                            'is_grid_label': is_label,
                            'actor_type': type(actor).__name__
                        })
        
        # Show dialog
        dialog = QDialog(self.app)
        dialog.setWindowTitle("DXF Text Analysis")
        dialog.resize(700, 500)
        
        layout = QVBoxLayout()
        
        report = QTextEdit()
        report.setReadOnly(True)
        
        lines = [f"Total text actors found: {len(text_actors)}\n"]
        lines.append("=" * 70)
        lines.append("")
        
        grid_labels = [t for t in text_actors if t['is_grid_label']]
        lines.append(f"Grid labels (is_grid_label=True): {len(grid_labels)}")
        lines.append(f"Other text: {len(text_actors) - len(grid_labels)}")
        lines.append("")
        lines.append("=" * 70)
        lines.append("")
        
        for i, actor_info in enumerate(text_actors[:50], 1):  # Show first 50
            status = "✅" if actor_info['is_grid_label'] else "❌"
            pos = actor_info['position']
            lines.append(f"{status} {i}. {actor_info['text']}")
            lines.append(f"   Position: [{pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}]")
            lines.append(f"   Type: {actor_info['actor_type']}")
            lines.append("")
        
        if len(text_actors) > 50:
            lines.append(f"... and {len(text_actors) - 50} more")
        
        report.setPlainText("\n".join(lines))
        layout.addWidget(report)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.setLayout(layout)
        dialog.exec()

    def show_grid_label_menu(self, grid_name):
        """
        Show context menu for a grid label.
        Called by CurveTool.eventFilter when it detects a right-click on a grid label.
        Extracted from on_right_click() so it can be called externally.
        """
        from PySide6.QtWidgets import QMenu, QMessageBox
        from PySide6.QtGui import QAction, QCursor

        if not grid_name:
            return

        menu = QMenu(self.app)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2c2c2c;
                color: #f0f0f0;
                border: 1px solid #555;
                padding: 5px;
            }
            QMenu::item {
                padding: 8px 30px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #3c3c3c;
            }
        """)

        load_action = QAction("📂 Load Grid Data", self.app)
        clear_action = QAction("🧹 Clear Grid Data", self.app)

        is_loaded = grid_name in self.loaded_grids

        if is_loaded:
            load_action.setText("📂 Reload Grid Data")
            point_count = len(self.loaded_grids[grid_name])
            clear_action.setText(f"🧹 Clear Grid ({point_count:,} pts)")
        else:
            clear_action.setEnabled(False)
            clear_action.setText("🧹 (Grid not loaded)")

        load_action.triggered.connect(lambda: self.load_grid_las(grid_name))

        def confirm_clear():
            reply = QMessageBox.question(
                self.app,
                "Confirm Clear",
                f"Clear all points from grid:\n\n{grid_name}\n\n"
                f"Points will be removed from view.\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.clear_grid_data(grid_name)

        clear_action.triggered.connect(confirm_clear)

        menu.addAction(load_action)
        menu.addAction(clear_action)
        menu.exec(QCursor.pos())        

def add_grid_label_system_to_app(app):
        """Initialize grid label manager"""
        if not hasattr(app, 'grid_label_manager'):
            app.grid_label_manager = GridLabelManager(app)
            app.grid_label_manager.setup_interactor()
            print("✅ Grid label system activated")
