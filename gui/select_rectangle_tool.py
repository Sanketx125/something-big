import numpy as np
import vtk
from PySide6.QtWidgets import QMessageBox, QProgressDialog
from PySide6.QtCore import Qt, QTimer


class SelectRectangleTool:
    """Tool for selecting points AND DXF entities within a drawn rectangle"""
    
    def __init__(self, app):
        self.app = app
        self.active = False
        self.start_pos = None
        self.rubber_band_actor = None
        self.selected_mask = None
        self.selected_count = 0
        self.selected_dxf_actors = []  # ✅ NEW: Store selected DXF actors
        self.is_drawing = False
        self._processing_click = False 
        
        # VTK event tags for cleanup
        self.observer_ids = []
        
    def activate(self):
        """Activate the selection tool"""
        if self.active:
            return
        
        self.active = True
        self.start_pos = None
        self.selected_mask = None
        self.selected_count = 0
        self.selected_dxf_actors = []
        self.is_drawing = False
        
        # Get main VTK interactor
        if not hasattr(self.app, 'vtk_widget') or not self.app.vtk_widget:
            print("⚠️ No VTK widget found")
            return
        
        interactor = self.app.vtk_widget.interactor
        
        # Add observers with HIGH PRIORITY
        press_id = interactor.AddObserver("LeftButtonPressEvent", self.on_left_press, 1.0)
        move_id = interactor.AddObserver("MouseMoveEvent", self.on_mouse_move, 1.0)
        right_id = interactor.AddObserver("RightButtonPressEvent", self.on_right_click, 1.0)
        
        self.observer_ids = [press_id, move_id, right_id]
        
        print("✅ Select Rectangle tool activated")
        print("   📍 Left-click & drag to draw rectangle")
        print("   🖱️ Right-click to finish and show delete dialog")
        print("   🎯 Selects BOTH point cloud AND DXF entities")
        
        self.app.statusBar().showMessage("🟧 Draw rectangle: LEFT-CLICK & drag, RIGHT-CLICK to finish", 5000)
        
    def deactivate(self):
        """Deactivate the selection tool"""
        if not self.active:
            return
        
        self.active = False
        self.is_drawing = False
        
        # Clear rubber band
        self._clear_rubber_band()
        
        # Clear selection highlight
        self._clear_selection_highlight()
        
        # Clear selection
        self.selected_mask = None
        self.selected_count = 0
        self.selected_dxf_actors = []
        self.start_pos = None
        
        # Remove ALL observers
        if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget:
            interactor = self.app.vtk_widget.interactor
            
            for obs_id in self.observer_ids:
                try:
                    interactor.RemoveObserver(obs_id)
                except:
                    pass
            
            self.observer_ids = []
        
        print("✅ Select Rectangle tool deactivated")
        
    def on_left_press(self, obj, event):
        """Start drawing rectangle"""
        if not self.active:
            return
        
        print(f"\n{'='*60}")
        print(f"🟧 SELECT TOOL: Left-click pressed")
        
        interactor = obj
        self.start_pos = interactor.GetEventPosition()
        self.is_drawing = True
        
        # Clear previous rubber band and selection
        self._clear_rubber_band()
        self._clear_selection_highlight()
        
        print(f"   📍 Start position: {self.start_pos}")
        print(f"{'='*60}\n")
        
        # ✅ FIXED: Abort event properly
        try:
            interactor.GetInteractorStyle().OnLeftButtonDown()
        except:
            pass
        
    def on_mouse_move(self, obj, event):
        """Update rubber band rectangle during drag"""
        if not self.active or not self.is_drawing or not self.start_pos:
            return
        
        interactor = obj
        current_pos = interactor.GetEventPosition()
        
        # Update rubber band visual
        self._draw_rubber_band(self.start_pos, current_pos)
        
    def on_right_click(self, obj, event):
        """Right-click to finish selection and show delete dialog"""
        if not self.active:
            return
        
        # ✅ FIX: Prevent multiple rapid clicks
        if hasattr(self, '_processing_click') and self._processing_click:
            print("⚠️ Already processing a click, ignoring...")
            return
        
        self._processing_click = True
        
        print(f"\n{'='*60}")
        print(f"🟧 SELECT TOOL: Right-click pressed")
        
        try:
            interactor = obj
            
            # If we're currently drawing, finish the rectangle
            if self.is_drawing and self.start_pos:
                end_pos = interactor.GetEventPosition()
                
                # Check if this is a valid rectangle
                x_diff = abs(end_pos[0] - self.start_pos[0])
                y_diff = abs(end_pos[1] - self.start_pos[1])
                
                print(f"   📍 End position: {end_pos}")
                print(f"   📏 Rectangle size: {x_diff}x{y_diff}")
                
                if x_diff > 5 and y_diff > 5:
                    # Select points AND DXF within rectangle
                    self._select_in_rectangle_fast(self.start_pos, end_pos)
                    
                    # Stop drawing
                    self.is_drawing = False
                    
                    # Show delete confirmation if anything was selected
                    total_selected = self.selected_count + len(self.selected_dxf_actors)
                    
                    if total_selected > 0:
                        print(f"   ✅ Total selected: {self.selected_count:,} points + {len(self.selected_dxf_actors)} DXF entities")
                        print(f"   💬 Showing delete confirmation dialog")
                        print(f"{'='*60}\n")
                        
                        # Show confirmation dialog
                        self._show_delete_confirmation()
                    else:
                        print(f"   ⚠️ Nothing selected in rectangle")
                        print(f"{'='*60}\n")
                        
                        self._clear_rubber_band()
                        self.start_pos = None
                        self.app.statusBar().showMessage("⚠️ Nothing selected in rectangle", 2000)
                else:
                    print(f"   ⚠️ Rectangle too small - ignored")
                    print(f"{'='*60}\n")
                    
                    self._clear_rubber_band()
                    self.start_pos = None
                    self.is_drawing = False
                    self.app.statusBar().showMessage("⚠️ Draw a larger rectangle", 2000)
            
            # If we already have a selection, show confirmation again
            elif (self.selected_mask is not None and np.any(self.selected_mask)) or self.selected_dxf_actors:
                print(f"   💬 Re-showing delete confirmation")
                print(f"{'='*60}\n")
                self._show_delete_confirmation()
            
            else:
                print(f"   ⚠️ No active selection")
                print(f"{'='*60}\n")
            
            # Abort event properly
            try:
                interactor.GetInteractorStyle().OnRightButtonDown()
            except:
                pass
        
        finally:
            # ✅ FIX: Always reset the processing flag
            self._processing_click = False
    def _select_in_rectangle_fast(self, start_pos, end_pos):
        """
        ✅ OPTIMIZED: Select both point cloud AND DXF entities in rectangle
        """
        import time
        start_time = time.time()
        
        # Create progress dialog
        progress = QProgressDialog("Detecting elements...", "Cancel", 0, 100, self.app)
        progress.setWindowTitle("Selection Progress")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setAutoClose(True)
        progress.setAutoReset(True)
        
        progress.setStyleSheet("""
            QProgressDialog {
                background-color: #2c2c2c;
                color: #f0f0f0;
            }
            QProgressBar {
                border: 2px solid #555;
                border-radius: 5px;
                text-align: center;
                background-color: #1c1c1c;
                color: #f0f0f0;
            }
            QProgressBar::chunk {
                background-color: #ff6f00;
                border-radius: 3px;
            }
            QPushButton {
                background-color: #3c3c3c;
                color: #f0f0f0;
                border: 1px solid #555;
                padding: 5px 15px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #4c4c4c;
            }
        """)
        
        try:
            # Get screen bounds
            x1, y1 = start_pos
            x2, y2 = end_pos
            
            xmin, xmax = min(x1, x2), max(x1, x2)
            ymin, ymax = min(y1, y2), max(y1, y2)
            
            # ========================================
            # PART 1: Select Point Cloud (50% of progress)
            # ========================================
            progress.setLabelText("Analyzing point cloud...")
            progress.setValue(5)
            
            if hasattr(self.app, 'data') and self.app.data is not None:
                self._select_points_fast(xmin, xmax, ymin, ymax, progress, 5, 50)
            else:
                self.selected_mask = None
                self.selected_count = 0
            
            if progress.wasCanceled():
                print("⚠️ Selection cancelled")
                self._clear_rubber_band()
                self.start_pos = None
                return
            
            # ========================================
            # PART 2: Select DXF Entities (50% of progress)
            # ========================================
            progress.setLabelText("Analyzing DXF entities...")
            progress.setValue(50)
            
            self._select_dxf_fast(xmin, xmax, ymin, ymax, progress, 50, 90)
            
            if progress.wasCanceled():
                print("⚠️ Selection cancelled")
                self._clear_rubber_band()
                self.start_pos = None
                return
            
            # ========================================
            # PART 3: Highlight selections
            # ========================================
            progress.setLabelText("Highlighting selections...")
            progress.setValue(95)
            
            self._clear_selection_highlight()
            
            # Highlight selected points
            if self.selected_count > 0:
                self._highlight_selected_points()
            
            # Highlight selected DXF
            if self.selected_dxf_actors:
                self._highlight_selected_dxf()
            
            progress.setValue(100)
            
            elapsed = time.time() - start_time
            total_selected = self.selected_count + len(self.selected_dxf_actors)
            
            print(f"   📊 Total selected: {total_selected:,} ({self.selected_count:,} points + {len(self.selected_dxf_actors)} DXF)")
            print(f"   ⚡ Time: {elapsed:.3f}s")
            
            # Update UI
            if hasattr(self.app, 'ribbon_manager'):
                identify_ribbon = self.app.ribbon_manager.ribbons.get('identify')
                if identify_ribbon:
                    identify_ribbon.update_selected_count(total_selected)
            
        except Exception as e:
            print(f"❌ Selection error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            progress.close()
    
    def _select_points_fast(self, xmin, xmax, ymin, ymax, progress, start_pct, end_pct):
        """Select point cloud points in rectangle"""
        xyz = self.app.data.get('xyz')
        if xyz is None or len(xyz) == 0:
            self.selected_mask = None
            self.selected_count = 0
            return
        
        total_points = len(xyz)
        progress.setLabelText(f"Checking {total_points:,} points...")
        progress.setValue(start_pct + 5)
        
        # Get visible points mask
        visible_mask = np.ones(len(xyz), dtype=bool)
        
        if self.app.display_mode == "class" and hasattr(self.app, 'class_palette'):
            visible_classes = [c for c, v in self.app.class_palette.items() if v.get('show', True)]
            if visible_classes and 'classification' in self.app.data:
                classes = self.app.data['classification']
                visible_mask = np.isin(classes, visible_classes)
        
        visible_xyz = xyz[visible_mask]
        visible_indices = np.where(visible_mask)[0]
        
        progress.setValue(start_pct + 10)
        
        # Vectorized coordinate transformation
        renderer = self.app.vtk_widget.renderer
        camera = renderer.GetActiveCamera()
        
        composite = camera.GetCompositeProjectionTransformMatrix(
            renderer.GetTiledAspectRatio(), 0, 1
        )
        
        progress.setLabelText("Converting coordinates...")
        progress.setValue(start_pct + 20)
        
        # Batch transform
        ones = np.ones((len(visible_xyz), 1))
        homogeneous = np.hstack([visible_xyz, ones])
        
        matrix = np.zeros((4, 4))
        for i in range(4):
            for j in range(4):
                matrix[i, j] = composite.GetElement(i, j)
        
        transformed = homogeneous @ matrix.T
        
        progress.setValue(start_pct + 30)
        
        # Normalize by w
        with np.errstate(divide='ignore', invalid='ignore'):
            transformed[:, :3] /= transformed[:, 3:4]
        
        # Convert to display coordinates
        size = renderer.GetSize()
        width, height = size
        
        display_x = (transformed[:, 0] + 1.0) * width * 0.5
        display_y = (transformed[:, 1] + 1.0) * height * 0.5
        
        progress.setLabelText("Selecting points...")
        progress.setValue(start_pct + 40)
        
        # Vectorized bounds check
        in_bounds = (
            (display_x >= xmin) & (display_x <= xmax) &
            (display_y >= ymin) & (display_y <= ymax)
        )
        
        selected_visible_indices = visible_indices[in_bounds]
        
        # Create selection mask
        self.selected_mask = np.zeros(len(xyz), dtype=bool)
        self.selected_mask[selected_visible_indices] = True
        self.selected_count = len(selected_visible_indices)
        
        progress.setValue(end_pct)
        print(f"   ✅ Points selected: {self.selected_count:,}")
    
    def _select_dxf_fast(self, xmin, xmax, ymin, ymax, progress, start_pct, end_pct):
        """
        ✅ NEW: Select DXF actors whose geometry falls within rectangle
        """
        self.selected_dxf_actors = []
        
        if not hasattr(self.app, 'dxf_actors') or not self.app.dxf_actors:
            progress.setValue(end_pct)
            return
        
        total_dxf = len(self.app.dxf_actors)
        progress.setLabelText(f"Checking {total_dxf} DXF entities...")
        progress.setValue(start_pct + 5)
        
        renderer = self.app.vtk_widget.renderer
        
        for idx, dxf_data in enumerate(self.app.dxf_actors):
            # Update progress
            pct = start_pct + 5 + int((idx / total_dxf) * (end_pct - start_pct - 5))
            progress.setValue(pct)
            
            if progress.wasCanceled():
                return
            
            actors = dxf_data.get('actors', [])
            
            for actor in actors:
                # Skip if not visible
                if not actor.GetVisibility():
                    continue
                
                # Check if any part of this actor is in the rectangle
                if self._is_actor_in_rectangle(actor, xmin, xmax, ymin, ymax, renderer):
                    self.selected_dxf_actors.append({
                        'dxf_data': dxf_data,
                        'actor': actor
                    })
                    break  # One actor per DXF entity is enough
        
        progress.setValue(end_pct)
        print(f"   ✅ DXF entities selected: {len(self.selected_dxf_actors)}")
    
    def _is_actor_in_rectangle(self, actor, xmin, xmax, ymin, ymax, renderer):
        """
        ✅ FIXED: Check if any part of a VTK actor intersects with the screen rectangle
        Uses the same reliable coordinate transformation as point cloud selection
        """
        try:
            # Get actor's mapper
            mapper = actor.GetMapper()
            if not mapper:
                print(f"            ⚠️ No mapper")
                return False
            
            # Get polydata
            polydata = mapper.GetInput()
            if not polydata:
                print(f"            ⚠️ No polydata")
                return False
            
            # Get points
            points = polydata.GetPoints()
            if not points or points.GetNumberOfPoints() == 0:
                print(f"            ⚠️ No points in polydata")
                return False
            
            num_points = points.GetNumberOfPoints()
            print(f"            📍 Actor has {num_points} points")
            
            # ✅ Use the same transformation as point cloud selection
            camera = renderer.GetActiveCamera()
            
            # Get composite projection matrix
            composite = camera.GetCompositeProjectionTransformMatrix(
                renderer.GetTiledAspectRatio(), 0, 1
            )
            
            # Convert VTK matrix to numpy
            matrix = np.zeros((4, 4))
            for i in range(4):
                for j in range(4):
                    matrix[i, j] = composite.GetElement(i, j)
            
            # Sample points for performance (check max 100 points for large geometries)
            sample_step = max(1, num_points // 100)
            print(f"            📊 Sample step: {sample_step} (will check ~{num_points // sample_step} points)")
            
            points_checked = 0
            points_in_rect = 0
            
            for i in range(0, num_points, sample_step):
                world_pt = points.GetPoint(i)
                
                # Create homogeneous coordinate
                homogeneous = np.array([world_pt[0], world_pt[1], world_pt[2], 1.0])
                
                # Transform to clip space
                transformed = matrix @ homogeneous
                
                # Normalize by w
                if abs(transformed[3]) < 1e-10:
                    continue
                
                normalized = transformed[:3] / transformed[3]
                
                # Convert to display coordinates
                size = renderer.GetSize()
                width, height = size
                
                display_x = (normalized[0] + 1.0) * width * 0.5
                display_y = (normalized[1] + 1.0) * height * 0.5
                
                points_checked += 1
                
                # Debug first and last few points
                if points_checked <= 2 or i >= num_points - 2:
                    print(f"            Point {i}: world=({world_pt[0]:.3f}, {world_pt[1]:.3f}, {world_pt[2]:.3f})")
                    print(f"                     → display=({display_x:.1f}, {display_y:.1f})")
                    print(f"                     → in rect? x:{xmin:.1f}≤{display_x:.1f}≤{xmax:.1f}, y:{ymin:.1f}≤{display_y:.1f}≤{ymax:.1f}")
                
                # Check if in rectangle
                if xmin <= display_x <= xmax and ymin <= display_y <= ymax:
                    points_in_rect += 1
                    if points_in_rect == 1:  # First match
                        print(f"            ✅ FIRST MATCH at point {i}: ({display_x:.1f}, {display_y:.1f})")
                    return True
            
            print(f"            ❌ No match: checked {points_checked} points, {points_in_rect} were in rectangle bounds")
            return False
            
        except Exception as e:
            print(f"            ❌ Exception in check: {e}")
            import traceback
            traceback.print_exc()
            return False
                    
                
    def _draw_rubber_band(self, start_pos, end_pos):
        """Draw a rubber band rectangle on screen"""
        self._clear_rubber_band()
        
        x1, y1 = start_pos
        x2, y2 = end_pos
        
        points = vtk.vtkPoints()
        points.InsertNextPoint(x1, y1, 0)
        points.InsertNextPoint(x2, y1, 0)
        points.InsertNextPoint(x2, y2, 0)
        points.InsertNextPoint(x1, y2, 0)
        points.InsertNextPoint(x1, y1, 0)
        
        lines = vtk.vtkCellArray()
        lines.InsertNextCell(5)
        for i in range(5):
            lines.InsertCellPoint(i)
        
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetLines(lines)
        
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(polydata)
        
        self.rubber_band_actor = vtk.vtkActor2D()
        self.rubber_band_actor.SetMapper(mapper)
        self.rubber_band_actor.GetProperty().SetColor(1.0, 0.5, 0.0)
        self.rubber_band_actor.GetProperty().SetLineWidth(4)
        self.rubber_band_actor.GetProperty().SetOpacity(0.8)
        
        self.app.vtk_widget.renderer.AddActor2D(self.rubber_band_actor)
        self.app.vtk_widget.render()
        
    def _clear_rubber_band(self):
        """Remove rubber band from display"""
        if self.rubber_band_actor:
            try:
                self.app.vtk_widget.renderer.RemoveActor2D(self.rubber_band_actor)
                self.app.vtk_widget.render()
            except:
                pass
            self.rubber_band_actor = None
    
    def _clear_selection_highlight(self):
        """Clear all selection highlights"""
        # Clear point highlight
        if hasattr(self.app.vtk_widget, 'actors') and 'selection_highlight' in self.app.vtk_widget.actors:
            try:
                self.app.vtk_widget.remove_actor('selection_highlight', render=False)
            except:
                pass
        
        # ✅ Clear DXF highlight overlays
        if hasattr(self.app.vtk_widget, 'actors') and 'dxf_selection_highlight' in self.app.vtk_widget.actors:
            try:
                self.app.vtk_widget.remove_actor('dxf_selection_highlight', render=False)
            except:
                pass
            
    def _highlight_selected_points(self):
        """Visually highlight the selected points"""
        if self.selected_mask is None or not np.any(self.selected_mask):
            return
        
        xyz = self.app.data['xyz']
        selected_xyz = xyz[self.selected_mask]
        
        print(f"   🎨 Highlighting {len(selected_xyz):,} points in orange")
        
        import pyvista as pv
        cloud = pv.PolyData(selected_xyz)
        
        self.app.vtk_widget.add_points(
            cloud,
            color='orange',
            point_size=12,
            render_points_as_spheres=True,
            name='selection_highlight',
            reset_camera=False,
            render=False
        )
    
    def _highlight_selected_dxf(self):
        """
        ✅ NEW: Highlight selected DXF entities by changing their color to orange
        """
        print(f"   🎨 Highlighting {len(self.selected_dxf_actors)} DXF entities in orange")
        
        for item in self.selected_dxf_actors:
            actor = item['actor']
            try:
                # Change color to orange
                actor.GetProperty().SetColor(1.0, 0.5, 0.0)  # Orange
                actor.GetProperty().SetLineWidth(5)  # Thicker
                actor.GetProperty().SetOpacity(1.0)
            except:
                pass
        
        self.app.vtk_widget.render()
    
    def _show_delete_confirmation(self):
        """Show confirmation dialog for deletion"""
        total_selected = self.selected_count + len(self.selected_dxf_actors)
        
        if total_selected == 0:
            print("⚠️ Nothing selected")
            return
        
        # Build message
        message = f"Delete selected items?\n\n"
        message += f"• {self.selected_count:,} point cloud points\n"
        message += f"• {len(self.selected_dxf_actors)} DXF entities\n\n"
        message += "This action cannot be undone."
        
        # ✅ FIX: Force process events before showing dialog
        from PySide6.QtCore import QCoreApplication
        QCoreApplication.processEvents()
        
        # ✅ FIX: Store selection state before dialog
        stored_mask = self.selected_mask.copy() if self.selected_mask is not None else None
        stored_dxf = list(self.selected_dxf_actors)  # Copy list
        stored_count = self.selected_count
        
        reply = QMessageBox.question(
            self.app,
            "Delete Selection",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        # ✅ FIX: Restore selection state after dialog
        self.selected_mask = stored_mask
        self.selected_dxf_actors = stored_dxf
        self.selected_count = stored_count
        
        if reply == QMessageBox.Yes:
            self._delete_selection()
        else:
            print("🚫 Deletion cancelled")
            self._cancel_selection()
    
    def _cancel_selection(self):
        """Cancel selection and clear highlights"""
        print("   🔄 Cancelling selection and restoring colors...")
        
        # Clear rubber band
        self._clear_rubber_band()
        
        # Restore DXF colors BEFORE clearing selection list
        for item in self.selected_dxf_actors:
            actor = item['actor']
            dxf_data = item['dxf_data']
            try:
                # Restore original color
                original_color = dxf_data.get('color', (0, 1, 0))
                actor.GetProperty().SetColor(*original_color)
                actor.GetProperty().SetLineWidth(2)
                actor.GetProperty().SetOpacity(0.8)
            except Exception as e:
                print(f"⚠️ Failed to restore actor color: {e}")
        
        # Clear highlights
        self._clear_selection_highlight()
        
        # Force render to show restored colors
        try:
            self.app.vtk_widget.render()
        except:
            pass
        
        # Clear selection state
        self.selected_mask = None
        self.selected_count = 0
        self.selected_dxf_actors = []
        self.start_pos = None
        self.is_drawing = False
        
        # Update UI
        if hasattr(self.app, 'ribbon_manager'):
            identify_ribbon = self.app.ribbon_manager.ribbons.get('identify')
            if identify_ribbon:
                identify_ribbon.update_selected_count(0)
        
        self.app.statusBar().showMessage("🚫 Selection cancelled", 2000)
    
    def _delete_selection(self):
        """Delete both selected points AND DXF entities"""
        progress = QProgressDialog("Deleting selection...", None, 0, 100, self.app)
        progress.setWindowTitle("Deletion Progress")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setCancelButton(None)
        
        progress.setStyleSheet("""
            QProgressDialog {
                background-color: #2c2c2c;
                color: #f0f0f0;
            }
            QProgressBar {
                border: 2px solid #555;
                border-radius: 5px;
                text-align: center;
                background-color: #1c1c1c;
                color: #f0f0f0;
            }
            QProgressBar::chunk {
                background-color: #d32f2f;
                border-radius: 3px;
            }
        """)
        
        try:
            deleted_points = 0
            deleted_dxf = 0
            
            # ✅ NEW: Save deleted data BEFORE removing
            deleted_xyz = None
            deleted_classification = None
            deleted_rgb = None
            deleted_intensity = None
            
            # ========================================
            # PART 1: Save & Delete Point Cloud Points (50%)
            # ========================================
            if self.selected_count > 0:
                progress.setLabelText(f"Saving deleted points...")
                progress.setValue(5)
                
                # Extract deleted points data
                xyz = self.app.data['xyz']
                deleted_xyz = xyz[self.selected_mask].copy()
                
                if 'classification' in self.app.data:
                    deleted_classification = self.app.data['classification'][self.selected_mask].copy()
                
                if 'rgb' in self.app.data and self.app.data['rgb'] is not None:
                    deleted_rgb = self.app.data['rgb'][self.selected_mask].copy()
                
                if 'intensity' in self.app.data and self.app.data['intensity'] is not None:
                    deleted_intensity = self.app.data['intensity'][self.selected_mask].copy()
                
                progress.setLabelText(f"Deleting {self.selected_count:,} points...")
                progress.setValue(10)
                
                # Create keep mask
                keep_mask = ~self.selected_mask
                
                # Update all data arrays
                self.app.data['xyz'] = self.app.data['xyz'][keep_mask]
                progress.setValue(20)
                
                if 'classification' in self.app.data:
                    self.app.data['classification'] = self.app.data['classification'][keep_mask]
                progress.setValue(30)
                
                if 'rgb' in self.app.data and self.app.data['rgb'] is not None:
                    self.app.data['rgb'] = self.app.data['rgb'][keep_mask]
                progress.setValue(40)
                
                if 'intensity' in self.app.data and self.app.data['intensity'] is not None:
                    self.app.data['intensity'] = self.app.data['intensity'][keep_mask]
                progress.setValue(50)
                
                deleted_points = self.selected_count
                print(f"   ✅ Deleted {deleted_points:,} points")
            
            # ========================================
            # PART 2: Delete DXF Entities (25%)
            # ========================================
            if self.selected_dxf_actors:
                progress.setLabelText(f"Deleting {len(self.selected_dxf_actors)} DXF entities...")
                progress.setValue(55)
                
                renderer = self.app.vtk_widget.renderer
                
                # Group by DXF data to remove entire entities
                dxf_to_remove = set()
                
                for item in self.selected_dxf_actors:
                    dxf_data = item['dxf_data']
                    actor = item['actor']
                    
                    # Remove actor from renderer
                    try:
                        renderer.RemoveActor(actor)
                    except:
                        pass
                    
                    dxf_to_remove.add(id(dxf_data))
                
                progress.setValue(65)
                
                # Remove from app's dxf_actors list
                self.app.dxf_actors = [
                    dxf for dxf in self.app.dxf_actors
                    if id(dxf) not in dxf_to_remove
                ]
                
                deleted_dxf = len(self.selected_dxf_actors)
                print(f"   ✅ Deleted {deleted_dxf} DXF entities")
                
                progress.setValue(70)
            
            # ========================================
            # PART 2.5: Save deleted data to file (10%)
            # ========================================
            progress.setLabelText("Saving deleted data...")
            progress.setValue(72)
            
            if deleted_xyz is not None or deleted_dxf > 0:
                save_path = self._save_deleted_data(
                    deleted_xyz if deleted_xyz is not None else np.array([]),
                    deleted_classification,
                    deleted_rgb,
                    deleted_intensity,
                    deleted_dxf
                )
                if save_path:
                    print(f"💾 Deleted data saved to: {save_path}")
            
            progress.setValue(75)
            
            # ========================================
            # PART 3: Clear and Refresh (25%)
            # ========================================
            progress.setLabelText("Clearing selection...")
            progress.setValue(80)
            
            self._clear_rubber_band()
            self._clear_selection_highlight()
            
            self.selected_mask = None
            self.selected_count = 0
            self.selected_dxf_actors = []
            self.start_pos = None
            self.is_drawing = False
            
            progress.setLabelText("Refreshing display...")
            progress.setValue(85)
            
            # Refresh point cloud display
            if deleted_points > 0:
                if self.app.display_mode == "class":
                    from gui.class_display import update_class_mode
                    update_class_mode(self.app)
                else:
                    from gui.pointcloud_display import update_pointcloud
                    update_pointcloud(self.app, self.app.display_mode)
            
            # If only DXF deleted, just render
            if deleted_dxf > 0 and deleted_points == 0:
                self.app.vtk_widget.render()
            
            progress.setValue(95)
            
            # Update UI
            if hasattr(self.app, 'ribbon_manager'):
                identify_ribbon = self.app.ribbon_manager.ribbons.get('identify')
                if identify_ribbon:
                    identify_ribbon.update_selected_count(0)
            
            # Update statistics
            if hasattr(self.app, 'point_count_widget') and self.app.point_count_widget:
                from gui.point_count_widget import refresh_point_statistics
                refresh_point_statistics(self.app)
            
            progress.setValue(100)
            
            # ========================================
            # PART 4: Clear Undo/Redo Stacks (CRITICAL)
            # ========================================
            # Point deletion invalidates all stored indices/masks.
            # We must clear stacks to prevent IndexErrors on undo.
            if hasattr(self.app, 'undo_stack'): self.app.undo_stack.clear()
            if hasattr(self.app, 'undostack'):  self.app.undostack.clear()
            if hasattr(self.app, 'redo_stack'): self.app.redo_stack.clear()
            if hasattr(self.app, 'redostack'):  self.app.redostack.clear()
            print("   🧹 Undo/Redo stacks cleared (indices invalidated by deletion)")

            # Show summary

            
            # Show summary
            message = f"✅ Deleted {deleted_points:,} points + {deleted_dxf} DXF entities (saved to *_removed.las)"
            self.app.statusBar().showMessage(message, 5000)
            print(f"\n{message}")
            
        except Exception as e:
            print(f"❌ Deletion error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            progress.close()
    
    def delete_selected_points(self):
        """Public method called from ribbon buttons to delete current selection"""
        if self.selected_mask is None and not self.selected_dxf_actors:
            print("⚠️ No active selection to delete")
            self.app.statusBar().showMessage("⚠️ No selection to delete", 2000)
            return
        
        total_selected = self.selected_count + len(self.selected_dxf_actors)
        if total_selected == 0:
            print("⚠️ Nothing selected")
            self.app.statusBar().showMessage("⚠️ Nothing selected", 2000)
            return
        
        # Show the same confirmation dialog
        self._show_delete_confirmation()

    def get_selection_summary(self):
        """Get summary of current selection"""
        return {
            'points': self.selected_count,
            'dxf_entities': len(self.selected_dxf_actors),
            'total': self.selected_count + len(self.selected_dxf_actors),
            'has_selection': (self.selected_count > 0) or (len(self.selected_dxf_actors) > 0)
        }

    def clear_selection(self):
        """Clear current selection without deleting"""
        self._cancel_selection()
        
        
        
    def _select_dxf_fast(self, xmin, xmax, ymin, ymax, progress, start_pct, end_pct):
        """
        ✅ NEW: Select DXF actors whose geometry falls within rectangle
        """
        self.selected_dxf_actors = []
        
        if not hasattr(self.app, 'dxf_actors') or not self.app.dxf_actors:
            print(f"   ⚠️ DEBUG: No dxf_actors attribute or empty list")
            print(f"   Has attribute: {hasattr(self.app, 'dxf_actors')}")
            if hasattr(self.app, 'dxf_actors'):
                print(f"   List length: {len(self.app.dxf_actors)}")
            progress.setValue(end_pct)
            return
        
        total_dxf = len(self.app.dxf_actors)
        print(f"   🔍 DEBUG: Found {total_dxf} DXF entities in app.dxf_actors")
        print(f"   🔍 DEBUG: Selection rectangle: x=[{xmin:.1f}, {xmax:.1f}], y=[{ymin:.1f}, {ymax:.1f}]")
        
        progress.setLabelText(f"Checking {total_dxf} DXF entities...")
        progress.setValue(start_pct + 5)
        
        renderer = self.app.vtk_widget.renderer
        
        for idx, dxf_data in enumerate(self.app.dxf_actors):
            # Update progress
            pct = start_pct + 5 + int((idx / total_dxf) * (end_pct - start_pct - 5))
            progress.setValue(pct)
            
            if progress.wasCanceled():
                return
            
            actors = dxf_data.get('actors', [])
            dxf_type = dxf_data.get('type', 'unknown')
            dxf_filename = dxf_data.get('filename', 'unknown')
            
            print(f"\n   📋 DEBUG: Entity {idx}:")
            print(f"      Type: {dxf_type}")
            print(f"      Filename: {dxf_filename}")
            print(f"      Number of actors: {len(actors)}")
            
            for actor_idx, actor in enumerate(actors):
                print(f"      🎭 Actor {actor_idx}:")
                
                # Skip if not visible
                if not actor.GetVisibility():
                    print(f"         ⚠️ Not visible - SKIPPING")
                    continue
                else:
                    print(f"         ✅ Visible")
                
                # Get actor bounds for debugging
                try:
                    bounds = actor.GetBounds()
                    print(f"         Bounds: {bounds}")
                except:
                    print(f"         ⚠️ Could not get bounds")
                
                # Check if any part of this actor is in the rectangle
                print(f"         🔍 Checking if in rectangle...")
                is_in_rect = self._is_actor_in_rectangle(actor, xmin, xmax, ymin, ymax, renderer)
                
                if is_in_rect:
                    print(f"         ✅✅✅ SELECTED!")
                    self.selected_dxf_actors.append({
                        'dxf_data': dxf_data,
                        'actor': actor
                    })
                    break  # One actor per DXF entity is enough
                else:
                    print(f"         ❌ Not in rectangle")
        
        progress.setValue(end_pct)
        print(f"\n   ✅ Total DXF entities selected: {len(self.selected_dxf_actors)}")
        
        
        
    def _save_deleted_data(self, deleted_points_xyz, deleted_points_classification=None, 
                       deleted_points_rgb=None, deleted_points_intensity=None,
                       deleted_dxf_count=0):
        """
        Save deleted points to a new LAS file with '_removed' suffix.
        Example: if original was 'data.las', saves as 'data_removed.las'
        """
        try:
            # Check if we have a loaded file path
            if not hasattr(self.app, 'current_file_path') or not self.app.current_file_path:
                print("⚠️ No original file path found - cannot save deleted data")
                return None
            
            import os
            from pathlib import Path
            
            # Get original file path
            original_path = Path(self.app.current_file_path)
            
            # Create new filename with '_removed' suffix
            base_name = original_path.stem  # filename without extension
            extension = original_path.suffix  # .las or .laz
            new_filename = f"{base_name}_removed{extension}"
            save_path = original_path.parent / new_filename
            
            print(f"\n💾 Saving deleted data to: {save_path}")
            
            # If no points to save, just create a summary file
            if len(deleted_points_xyz) == 0:
                summary_path = original_path.parent / f"{base_name}_removed_summary.txt"
                with open(summary_path, 'w') as f:
                    f.write(f"Deletion Summary\n")
                    f.write(f"=" * 50 + "\n")
                    f.write(f"Original file: {original_path.name}\n")
                    f.write(f"Points deleted: 0\n")
                    f.write(f"DXF entities deleted: {deleted_dxf_count}\n")
                print(f"✅ Saved summary to: {summary_path}")
                return summary_path
            
            # Save deleted points to LAS/LAZ file
            try:
                import laspy
                
                # Create header
                header = laspy.LasHeader(point_format=3, version="1.2")
                header.offsets = np.min(deleted_points_xyz, axis=0)
                header.scales = np.array([0.001, 0.001, 0.001])
                
                # Create LAS data
                las = laspy.LasData(header)
                
                # Add coordinates
                las.x = deleted_points_xyz[:, 0]
                las.y = deleted_points_xyz[:, 1]
                las.z = deleted_points_xyz[:, 2]
                
                # Add classification if available
                if deleted_points_classification is not None:
                    las.classification = deleted_points_classification
                
                # Add RGB if available
                if deleted_points_rgb is not None and deleted_points_rgb.shape[1] >= 3:
                    las.red = (deleted_points_rgb[:, 0] * 65535).astype(np.uint16)
                    las.green = (deleted_points_rgb[:, 1] * 65535).astype(np.uint16)
                    las.blue = (deleted_points_rgb[:, 2] * 65535).astype(np.uint16)
                
                # Add intensity if available
                if deleted_points_intensity is not None:
                    las.intensity = deleted_points_intensity
                
                # Write file
                las.write(str(save_path))
                
                print(f"✅ Saved {len(deleted_points_xyz):,} deleted points to: {save_path}")
                
                # Also save a summary text file
                summary_path = original_path.parent / f"{base_name}_removed_summary.txt"
                with open(summary_path, 'w') as f:
                    f.write(f"Deletion Summary\n")
                    f.write(f"=" * 50 + "\n")
                    f.write(f"Original file: {original_path.name}\n")
                    f.write(f"Deleted file: {new_filename}\n")
                    f.write(f"Points deleted: {len(deleted_points_xyz):,}\n")
                    f.write(f"DXF entities deleted: {deleted_dxf_count}\n")
                    f.write(f"\nDeleted point bounds:\n")
                    f.write(f"  X: {np.min(deleted_points_xyz[:, 0]):.3f} to {np.max(deleted_points_xyz[:, 0]):.3f}\n")
                    f.write(f"  Y: {np.min(deleted_points_xyz[:, 1]):.3f} to {np.max(deleted_points_xyz[:, 1]):.3f}\n")
                    f.write(f"  Z: {np.min(deleted_points_xyz[:, 2]):.3f} to {np.max(deleted_points_xyz[:, 2]):.3f}\n")
                
                print(f"✅ Saved summary to: {summary_path}")
                
                return save_path
                
            except ImportError:
                print("⚠️ laspy not available - saving as numpy array")
                # Fallback: save as numpy array
                np_save_path = original_path.parent / f"{base_name}_removed.npy"
                np.save(str(np_save_path), {
                    'xyz': deleted_points_xyz,
                    'classification': deleted_points_classification,
                    'rgb': deleted_points_rgb,
                    'intensity': deleted_points_intensity
                })
                print(f"✅ Saved deleted points (numpy) to: {np_save_path}")
                return np_save_path
                
        except Exception as e:
            print(f"❌ Failed to save deleted data: {e}")
            import traceback
            traceback.print_exc()
            return None