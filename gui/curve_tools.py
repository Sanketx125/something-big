"""
Curve Drawing Tool for NakshaAI
MicroStation-style point-by-point curve drawing with real-time preview
"""

import numpy as np
import vtk
from PySide6.QtCore import Qt, QEvent, QObject # ✅ ADD QObject
from PySide6.QtGui import QFont, QPixmap, QIcon, QColor
from PySide6.QtWidgets import QColorDialog

class CurveTool(QObject):  # ✅ INHERIT FROM QObject
    """
    MicroStation-style Curve Point Tool
    
    Workflow:
    1. Click "Curve Point" button → Tool activates
    2. Click on canvas → Add point 1
    3. Click on canvas → Add point 2 (line preview)
    4. Click on canvas → Add point 3 (curve preview appears)
    5. Continue clicking → Curve updates in real-time
    6. Press ENTER or right-click → Finalize curve
    7. Press ESC → Cancel
    """
    
    def __init__(self, app):
        super().__init__()  # ✅ CALL QObject.__init__()
        self.app = app
        self.active = False
        self._select_mode = False          # ◀◀◀ ADD THIS
        self.points = []  # List of [x, y, z] clicked points
        
        # VTK actors for visualization
        self.preview_actor = None      # Real-time curve preview (blue)
        self.point_actors = []         # Point markers (red dots)
        self.finalized_actors = []  
        self.dynamic_line_actor = None  # Completed curves (green)
        
        
        # Undo/Redo stacks for point-by-point
        self.undo_stack = []  # Stores removed points
        self.redo_stack = []  # Stores re-added points

        # Undo/Redo stacks for completed curves (whole-operation undo after right-click)
        self.history_stack = []       # List of curve_data after each finalization
        self.history_redo_stack = []  # For redo after undoing a completed curve

        # Selection
        self.selected_curve = None     # Currently selected curve actor
        self.selected_curve_data = None # Store curve info for editing
        
        # Settings
        self.tension = 0.5             # Catmull-Rom tension (0 = tight, 1 = loose)
        self.samples = 100             # Number of interpolation points
        self.app.vtk_widget.installEventFilter(self)
        
        print("✅ CurveTool initialized")
    
    def activate(self):
        """Activate the curve drawing tool"""
        if self.active:
            return
        
        self.active = True
        self.points = []
        self._finalizing = False  # ✅ Add flag to prevent double-finalization
        
        # ✅ Enable mouse tracking for live preview
        self.app.vtk_widget.setMouseTracking(True)
        
        if hasattr(self.app, 'set_cross_cursor_active'):
            self.app.set_cross_cursor_active(True, "curve")
        
        print("🎯 Curve Point tool ACTIVATED - Click to add points")
        
        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                "🔮 Curve Point: Click to add points | ENTER = Apply | ESC = Cancel | Right-click = Finish",
                0  # Persistent message
            )
            
            
    def _enable_line_stippling(self):
        """Enable OpenGL line stippling for dotted lines"""
        try:
            # Get the render window
            render_window = self.app.vtk_widget.GetRenderWindow()
            
            # Enable line smoothing for better appearance
            render_window.LineSmoothingOn()
            
            print("   ✅ Line stippling enabled")
        except Exception as e:
            print(f"   ⚠️ Could not enable line stippling: {e}")
    
    def deactivate(self):
        """Deactivate the curve drawing tool"""
        if not self.active:
            return
        
        self.active = False
        self._select_mode = False          # ◀◀◀ ADD THIS
       
        # ✅ Disable mouse tracking
        digitizer = getattr(self.app, 'digitizer', None)
        if not (digitizer and getattr(digitizer, 'enabled', False)):
            self.app.vtk_widget.setMouseTracking(False)
    
        if hasattr(self.app, 'set_cross_cursor_active'):
            self.app.set_cross_cursor_active(False, "curve")
        
        # Clear preview
        self._clear_preview()
        
        print("⏹️ Curve Point tool DEACTIVATED (selection still enabled)")
        
        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                "💡 Right-click curves to select | Delete to remove | Shift+E to edit color",
                3000
            )
        
    def eventFilter(self, obj, event):
        """
        Qt-level event filter.
        
        CRITICAL: This runs BEFORE VTK interactor observers (digitizer, etc).
        When no tool is active, we check for grid labels on right-click and
        show the menu directly — preventing the digitizer from swallowing it.
        """
        
        # ══════════════════════════════════════════════════════════════
        # STATE: NO TOOL ACTIVE — grid labels should work
        # ══════════════════════════════════════════════════════════════
        if not self.active and not getattr(self, '_select_mode', False):
            
            # ── RIGHT-CLICK: Grid label check (MUST run before VTK) ──
            if (event.type() == QEvent.MouseButtonPress 
                    and event.button() == Qt.RightButton):
                
                grid_name = self._check_grid_label_at_click(event)
                if grid_name:
                    print(f"   🏷️ Grid label found: '{grid_name}' → showing menu")
                    if hasattr(self.app, 'grid_label_manager'):
                        self.app.grid_label_manager.show_grid_label_menu(grid_name)
                    return True   # ← BLOCK digitizer from seeing this click
                
                # No grid label → let VTK / digitizer handle normally
                return False
            
            # ── Delete/Edit key for previously selected curves ──
            if event.type() == QEvent.KeyPress and self.selected_curve_data is not None:
                if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                    self._delete_selected_curve()
                    return True
                elif event.key() == Qt.Key_E and event.modifiers() == Qt.ShiftModifier:
                    self._edit_selected_curve_color()
                    return True
            
            return False   # ← everything else passes through
        
        # ══════════════════════════════════════════════════════════════
        # STATE: SELECT MODE — curve selection clicks
        # ══════════════════════════════════════════════════════════════
        if getattr(self, '_select_mode', False) and not self.active:
            
            if event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    self._select_curve_at_click(event)
                    return True
                elif event.button() == Qt.RightButton:
                    if self.selected_curve_data:
                        self._deselect_curve()
                    return True
            
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self.deactivate_select_mode()
                    return True
                if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                    if self.selected_curve_data:
                        self._delete_selected_curve()
                        return True
                if event.key() == Qt.Key_E and event.modifiers() == Qt.ShiftModifier:
                    if self.selected_curve_data:
                        self._edit_selected_curve_color()
                        return True
            
            return False
        
        # ══════════════════════════════════════════════════════════════
        # STATE: DRAWING ACTIVE — full curve drawing mode
        # ══════════════════════════════════════════════════════════════
        
        if event.type() == QEvent.MouseMove:
            if len(self.points) > 0:
                self._update_dynamic_preview(event)
            return False
        
        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                self._on_left_click(event)
                return True
            elif event.button() == Qt.RightButton:
                self._finalize_curve()
                return True
        
        if event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._finalize_curve()
                return True
            elif event.key() == Qt.Key_Escape:
                self._cancel_curve()
                return True
            elif event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
                self._undo_last_point()
                return True
            elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
                self._undo_last_point()
                return True
            elif event.key() == Qt.Key_Y and event.modifiers() == Qt.ControlModifier:
                self._redo_last_point()
                return True
        
        return False

    def activate_select_mode(self):
        """
        Enter selection mode — user can click curves to select/delete them.
        Activated from the "Select Drawing" button in Draw ribbon.
        """
        # Deactivate drawing mode if active
        if self.active:
            self._cancel_curve()
        
        self._select_mode = True
        self.app.vtk_widget.setCursor(Qt.PointingHandCursor)
        
        print("🎯 Select Drawing mode ACTIVATED — Click curves to select, ESC to exit")
        
        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                "🎯 Select Drawing: Click to select | Delete to remove | "
                "Shift+E = color | ESC = exit",
                0
            )

    def deactivate_select_mode(self):
        """Exit selection mode — right-clicks now go to grid labels."""
        self._select_mode = False
        
        # Deselect any selected curve
        self._deselect_curve()
        
        # Restore cursor
        self.app.vtk_widget.setCursor(Qt.ArrowCursor)
        
        print("⏹️ Select Drawing mode DEACTIVATED — Grid labels now respond to right-click")
        
        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                "✅ Selection mode off — Right-click grid labels to load data",
                3000
            )

    def is_any_mode_active(self) -> bool:
        """Check if curve tool has any active mode."""
        return self.active or getattr(self, '_select_mode', False) 

    def _update_dynamic_preview(self, event):
        """Update the dotted line from last point to cursor (Actor2D)"""
        if not self.points:
            return
        
        # Remove old dynamic line
        if self.dynamic_line_actor:
            self.app.vtk_widget.renderer.RemoveViewProp(self.dynamic_line_actor)
            self.dynamic_line_actor = None
        
        # Get cursor position
        pos = event.pos()
        cursor_world = self._screen_to_world(pos.x(), pos.y())
        
        if cursor_world is None:
            return
        
        # Create line geometry
        points = vtk.vtkPoints()
        points.SetDataTypeToDouble()
        points.InsertNextPoint(self.points[-1])  # Last clicked
        points.InsertNextPoint(cursor_world)     # Cursor
        
        line = vtk.vtkLine()
        line.GetPointIds().SetId(0, 0)
        line.GetPointIds().SetId(1, 1)
        
        cells = vtk.vtkCellArray()
        cells.InsertNextCell(line)
        
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetLines(cells)
        
        # Mapper 2D
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(polydata)
        
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        mapper.SetTransformCoordinate(coord)
        
        self.dynamic_line_actor = vtk.vtkActor2D()
        self.dynamic_line_actor.SetMapper(mapper)
        
        # Styling (Light gray, dotted effect is hard in 2D, keeping solid thin)
        self.dynamic_line_actor.GetProperty().SetColor(0.7, 0.7, 0.7)
        self.dynamic_line_actor.GetProperty().SetLineWidth(1)
        self.dynamic_line_actor.GetProperty().SetDisplayLocationToForeground()
        
        self.app.vtk_widget.renderer.AddViewProp(self.dynamic_line_actor)
        self.app.vtk_widget.render()
    
    def _on_left_click(self, event):
        """Handle left mouse click - add point to curve"""
        # Get 3D coordinates from click position
        pos = event.pos()
        x, y = pos.x(), pos.y()
        
        # Convert screen coordinates to 3D world coordinates
        world_pos = self._screen_to_world(x, y)
        
        if world_pos is None:
            print("⚠️ Could not get 3D coordinates")
            return
        
        # Add point
        self.points.append(world_pos)
        
        print(f"📍 Point {len(self.points)} added: ({world_pos[0]:.2f}, {world_pos[1]:.2f}, {world_pos[2]:.2f})")
        
        # Update visualization
        self._update_preview()
        
        # Update status
        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                f"🔮 Curve Point: {len(self.points)} points | ENTER = Apply | ESC = Cancel",
                0
            )
    
    def _screen_to_world(self, screen_x, screen_y):
        """
        Convert screen coordinates to 3D world coordinates
        Uses VTK's picker to find intersection with existing geometry
        """
        try:
            # Get renderer and render window
            renderer = self.app.vtk_widget.renderer
            render_window = self.app.vtk_widget.GetRenderWindow()
            
            # Create picker
            picker = vtk.vtkPropPicker()
            
            # Get window size for coordinate conversion
            window_size = render_window.GetSize()
            
            # VTK uses bottom-left origin, Qt uses top-left
            vtk_y = window_size[1] - screen_y
            
            # Pick at screen coordinates
            picker.Pick(screen_x, vtk_y, 0, renderer)
            
            # Get picked position
            world_pos = picker.GetPickPosition()
            
            # ✅ NEW: If no intersection, calculate Z from data OR use 0
            if world_pos == (0, 0, 0):
                # Try to get average Z from point cloud
                avg_z = 0.0
                if hasattr(self.app, 'data') and self.app.data is not None:
                    if 'xyz' in self.app.data:
                        avg_z = np.mean(self.app.data['xyz'][:, 2])
                        print(f"   Using point cloud Z: {avg_z:.2f}")
                    else:
                        print(f"   No point cloud - using Z=0")
                else:
                    if not hasattr(self, '_z_warned'):
                        print("   No data loaded - using Z=0")
                        self._z_warned = True
                
                # Project screen point onto plane at avg_z
                world_pos = self._project_to_plane(screen_x, vtk_y, avg_z, renderer)
            
            return list(world_pos)
        
        except Exception as e:
            print(f"❌ Screen to world conversion failed: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _project_to_plane(self, screen_x, screen_y, z_plane, renderer):
        """Project screen coordinates onto a horizontal plane at given Z"""
        # Get camera
        camera = renderer.GetActiveCamera()
        
        # Create coordinate converter
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToDisplay()
        coord.SetValue(screen_x, screen_y, 0)
        
        # Convert to world coordinates
        world_pos = coord.GetComputedWorldValue(renderer)
        
        # Adjust Z to plane
        return (world_pos[0], world_pos[1], z_plane)
    
    def _update_preview(self):
        """Update the real-time curve preview (NOT the dynamic line to cursor)"""
        # Clear old CURVE preview only (keep dynamic line separate)
        if self.preview_actor:
            self.app.vtk_widget.renderer.RemoveViewProp(self.preview_actor)
            self.preview_actor = None
        
        # Clear point markers
        for actor in self.point_actors:
            self.app.vtk_widget.renderer.RemoveActor(actor)
        self.point_actors = []
        
        num_points = len(self.points)
        
        if num_points == 0:
            return
        
        # Draw point markers at clicked locations
        self._draw_point_markers()
        
        # ✅ ONLY draw the smooth curve if we have 3+ points
        # Do NOT draw line preview for 2 points - let dynamic line handle that
        if num_points >= 2:
            self._draw_curve_preview()
        
        # Render
        self.app.vtk_widget.render()
    
    def _draw_point_markers(self):
        for i, point in enumerate(self.points):

            pixel_source = vtk.vtkRegularPolygonSource()
            pixel_source.SetNumberOfSides(20)

            # 🎯 Different styling
            if i == 0:
                pixel_source.SetRadius(3.0)  # smaller start point
            else:
                pixel_source.SetRadius(5.0)

            pixel_source.GeneratePolygonOn()

            coordinate = vtk.vtkCoordinate()
            coordinate.SetCoordinateSystemToWorld()
            coordinate.SetValue(point[0], point[1], point[2])

            mapper = vtk.vtkPolyDataMapper2D()
            mapper.SetInputConnection(pixel_source.GetOutputPort())
            mapper.SetTransformCoordinate(coordinate)

            actor = vtk.vtkActor2D()
            actor.SetMapper(mapper)

            # 🎯 Color logic
            if i == 0:
                actor.GetProperty().SetColor(1, 1, 0)  # yellow start point
            else:
                actor.GetProperty().SetColor(1, 0, 0)  # red others

            actor.GetProperty().SetDisplayLocationToForeground()

            self.app.vtk_widget.renderer.AddViewProp(actor)
            self.point_actors.append(actor)
   
    def _draw_curve_preview(self):
        """Draw smooth Catmull-Rom spline preview (Actor2D)"""
        curve_points = self._interpolate_catmull_rom(self.points)
        
        if curve_points is None or len(curve_points) < 2:
            return
        
        # Create VTK points
        vtk_points = vtk.vtkPoints()
        vtk_points.SetDataTypeToDouble()
        for pt in curve_points:
            vtk_points.InsertNextPoint(pt)
        
        # Create polyline
        polyline = vtk.vtkPolyLine()
        polyline.GetPointIds().SetNumberOfIds(len(curve_points))
        for i in range(len(curve_points)):
            polyline.GetPointIds().SetId(i, i)
        
        cells = vtk.vtkCellArray()
        cells.InsertNextCell(polyline)
        
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(vtk_points)
        polydata.SetLines(cells)
        
        # Mapper 2D with World Coordinates
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(polydata)
        
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        mapper.SetTransformCoordinate(coord)
        
        self.preview_actor = vtk.vtkActor2D()
        self.preview_actor.SetMapper(mapper)
        
        # Cyan solid curve, render on top
        self.preview_actor.GetProperty().SetColor(0, 1, 1)  # Cyan
        self.preview_actor.GetProperty().SetLineWidth(2)
        self.preview_actor.GetProperty().SetDisplayLocationToForeground()
        
        # Use AddViewProp for 2D actors
        self.app.vtk_widget.renderer.AddViewProp(self.preview_actor)
    
    def _interpolate_catmull_rom(self, control_points):
        """
        Interpolate smooth Catmull-Rom spline through control points
        Returns array of interpolated points
        """
        if len(control_points) < 2:
            return None
        
        control_points = np.array(control_points)
        num_segments = len(control_points) - 1
        points_per_segment = 20  # constant per segment (smooth)        
        interpolated = []
        
        for i in range(num_segments):
            # Get control points for this segment
            p0 = control_points[max(0, i - 1)]
            p1 = control_points[i]
            p2 = control_points[i + 1]
            p3 = control_points[min(len(control_points) - 1, i + 2)]
            
            # Interpolate this segment
            for j in range(points_per_segment):
                t = j / points_per_segment
                pt = self._catmull_rom_point(p0, p1, p2, p3, t)
                interpolated.append(pt)
        
        # Add final point
        interpolated.append(control_points[-1])
        
        return np.array(interpolated)
    
    def _catmull_rom_point(self, p0, p1, p2, p3, t):
        """Calculate single point on Catmull-Rom spline"""
        t2 = t * t
        t3 = t2 * t
        
        # Catmull-Rom basis matrix
        result = 0.5 * (
            (2 * p1) +
            (-p0 + p2) * t +
            (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
            (-p0 + 3 * p1 - 3 * p2 + p3) * t3
        )
        
        return result
    
    def _clear_preview(self):
        """Remove all preview actors using RemoveViewProp"""
        if self.preview_actor:
            self.app.vtk_widget.renderer.RemoveViewProp(self.preview_actor)
            self.preview_actor = None
        
        if self.dynamic_line_actor:
            self.app.vtk_widget.renderer.RemoveViewProp(self.dynamic_line_actor)
            self.dynamic_line_actor = None
        
        for actor in self.point_actors:
            self.app.vtk_widget.renderer.RemoveViewProp(actor)
        self.point_actors = []
    
    def _finalize_curve(self):
        """Finalize the curve (ENTER or right-click)"""
        # ✅ Prevent double-finalization from multiple events
        if hasattr(self, '_finalizing') and self._finalizing:
            return
        
        # ✅ Guard against insufficient points
        if len(self.points) < 2:
            if len(self.points) > 0:
                print("⚠️ Need at least 2 points to create a curve")
            return
        
        # ✅ Set flag immediately
        self._finalizing = True
        
        print(f"✅ Finalizing curve with {len(self.points)} points")
        
        # ✅ Save points before clearing
        points_to_save = self.points.copy()
        
        # ✅ Clear points IMMEDIATELY to prevent re-entry
        self.points = []
        
        # Create final curve actor (green)
        curve_points = self._interpolate_catmull_rom(points_to_save)
        
        if curve_points is not None:
            actor = self._create_curve_actor(curve_points, color=(0, 1, 0))  # Green
            
            # ✅ Store curve data with actor for later editing
            curve_data = {
                'actor': actor,
                'control_points': points_to_save.copy(),
                'interpolated': curve_points.copy(),
                'color': (0, 1, 0)  # Default green
            }
            
            self.finalized_actors.append(curve_data)
            self.app.vtk_widget.renderer.AddActor(actor)
        
        # Save to history for whole-operation undo/redo after completion
        if curve_points is not None:
            self.history_stack.append(curve_data)
            self.history_redo_stack.clear()
        
        # Clear preview and reset
        self._clear_preview()
        
        # Render
        # Render
        self.app.vtk_widget.render()

        # ✅ Reset flag after a short delay
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, lambda: setattr(self, '_finalizing', False))

        # ✅ DEACTIVATE the tool after finalizing (so curves can be selected)
        self.deactivate()

        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                "✅ Curve created! Right-click to select | Shift+E to edit color",
                3000
            )
    
    def _cancel_curve(self):
        """Cancel current curve and deactivate tool (ESC)"""
        print("❌ Curve cancelled - deactivating tool")
        
        self._clear_preview()
        self.points = []
        
        # ✅ Deactivate the tool completely
        self.deactivate()
        
        self.app.vtk_widget.render()
        
        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                "❌ Curve tool deactivated",
                2000
            )
        
    def _undo_last_point(self):
        """Remove the last added point (Backspace/Delete)"""
        if not self.points:
            return

        removed = self.points.pop()
        self.redo_stack.append(removed)  # Save for redo
        # Cap redo stack (point entries are small, but prevent unbounded growth)
        if len(self.redo_stack) > 200:
            self.redo_stack.pop(0)

        print(f"↶ Undo point: ({removed[0]:.2f}, {removed[1]:.2f}, {removed[2]:.2f})")

        self._update_preview()

        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                f"↶ Undo: {len(self.points)} points | Ctrl+Y to redo",
                2000
            )

    def _redo_last_point(self):
        """Re-add the last removed point (Ctrl+Y)"""
        if not self.redo_stack:
            print("Nothing to redo")
            return

        restored = self.redo_stack.pop()
        self.points.append(restored)

        print(f"↷ Redo point: ({restored[0]:.2f}, {restored[1]:.2f}, {restored[2]:.2f})")

        self._update_preview()

        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                f"↷ Redo: {len(self.points)} points",
                2000
            )
               
    def _select_curve_at_click(self, event):
        """Select a curve by clicking on it"""
        pos = event.pos()
        x, y = pos.x(), pos.y()

        print(f"🔍 Curve tool: Checking for curve at ({x}, {y})")

        render_window = self.app.vtk_widget.GetRenderWindow()
        window_size = render_window.GetSize()
        vtk_y = window_size[1] - y

        print(f"   📐 Window size: {window_size}, VTK Y: {vtk_y}")

        # Try vtkCellPicker first (best for lines)
        cell_picker = vtk.vtkCellPicker()
        cell_picker.SetTolerance(0.02)
        success = cell_picker.Pick(x, vtk_y, 0, self.app.vtk_widget.renderer)
        picked_actor = cell_picker.GetActor()

        # ──────────────────────────────────────────────────────────────
        # 🚫  SKIP GRID LABELS  (robust — survives VTK wrapper mismatch)
        # ──────────────────────────────────────────────────────────────
        if picked_actor:
            # Direct attribute check
            if hasattr(picked_actor, 'is_grid_label') and picked_actor.is_grid_label:
                print("   🔵 Clicked grid label (direct) - skipping curve tool")
                self.selected_curve_data = None
                return

            # Position-based match against known grid labels
            picked_pos    = picked_actor.GetPosition()
            picked_bounds = picked_actor.GetBounds()
            for store_name in ('snt_actors', 'dxf_actors'):
                for data in getattr(self.app, store_name, []):
                    for actor in data.get('actors', []):
                        if hasattr(actor, 'is_grid_label') and actor.is_grid_label:
                            try:
                                if (actor.GetPosition() == picked_pos and
                                        actor.GetBounds() == picked_bounds):
                                    print("   🔵 Clicked grid label (matched) - skipping curve tool")
                                    self.selected_curve_data = None
                                    return
                            except Exception:
                                pass

        # If CellPicker failed, try PropPicker as fallback
        if not picked_actor:
            print("   🔄 Trying PropPicker as fallback...")
            prop_picker = vtk.vtkPropPicker()
            prop_picker.Pick(x, vtk_y, 0, self.app.vtk_widget.renderer)
            picked_actor = prop_picker.GetActor()
            print(f"   🎯 PropPicker actor: {picked_actor}")

        if not picked_actor:
            print("   ⚪ No actor picked - allowing digitizer to handle")
            self.selected_curve_data = None
            return

        print(f"   📋 Total finalized curves: {len(self.finalized_actors)}")

        # Check if picked actor is one of our curves
        for i, curve_data in enumerate(self.finalized_actors):
            actor = curve_data['actor'] if isinstance(curve_data, dict) else curve_data
            if actor is picked_actor:
                print(f"   ✅ MATCH! Selecting curve {i}")
                self._select_curve(curve_data)
                return

        print("   ⚪ Picked actor is not a curve - allowing digitizer to handle")
        self.selected_curve_data = None

    def _check_grid_label_at_click(self, event):
        """
        Check if a grid label exists at the click position.
        Returns grid_name string if found, None otherwise.
        
        Uses multiple picker strategies to handle VTK's Python wrapper
        mismatch (where GetActor() returns a different wrapper that lost
        custom attributes like is_grid_label).
        """
        try:
            x, y = event.pos().x(), event.pos().y()
            render_window = self.app.vtk_widget.GetRenderWindow()
            window_size = render_window.GetSize()
            vtk_y = window_size[1] - y
            renderer = self.app.vtk_widget.renderer

            # ── Method 1: AreaPicker (returns original Python objects) ──
            area_picker = vtk.vtkAreaPicker()
            area_picker.AreaPick(
                x - 12, vtk_y - 12, x + 12, vtk_y + 12, renderer
            )

            for prop in area_picker.GetProp3Ds():
                if hasattr(prop, 'is_grid_label') and prop.is_grid_label:
                    grid_name = getattr(prop, 'grid_name', '')
                    if grid_name:
                        return grid_name

            # ── Method 2: PropPicker + match against known actors ──────
            prop_picker = vtk.vtkPropPicker()
            prop_picker.Pick(x, vtk_y, 0, renderer)
            picked = prop_picker.GetActor()

            if picked is None:
                return None

            # Direct attribute check
            if hasattr(picked, 'is_grid_label') and picked.is_grid_label:
                return getattr(picked, 'grid_name', '')

            # ── Method 3: Match by position/bounds with all known labels ─
            try:
                picked_pos = picked.GetPosition()
                picked_bounds = picked.GetBounds()
            except Exception:
                return None

            for store_name in ('snt_actors', 'dxf_actors'):
                for data in getattr(self.app, store_name, []):
                    for actor in data.get('actors', []):
                        if not (hasattr(actor, 'is_grid_label') and actor.is_grid_label):
                            continue
                        try:
                            if (actor.GetPosition() == picked_pos
                                    and actor.GetBounds() == picked_bounds):
                                gn = getattr(actor, 'grid_name', '')
                                if gn:
                                    return gn
                        except Exception:
                            pass

        except Exception as exc:
            print(f"   ⚠️ Grid label check failed: {exc}")

        return None

    def _select_curve(self, curve_data):
        """Highlight selected curve"""
        # Deselect previous
        self._deselect_curve()
        
        # Select new
        self.selected_curve_data = curve_data
        actor = curve_data['actor'] if isinstance(curve_data, dict) else curve_data
        self.selected_curve = actor
        
        # Highlight with yellow color
        actor.GetProperty().SetColor(1, 1, 0)  # Yellow
        actor.GetProperty().SetLineWidth(4)    # Thicker (increased from 3)
        
        self.app.vtk_widget.render()
        
        # ✅ Show status message
        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage(
                "🎯 Curve selected | Delete to remove | Shift+E to change color | Right-click again to deselect",
                5000
            )
        
        print("✅ Curve selected - Press Delete to remove, Shift+E to change color")

    def _deselect_curve(self):
        """Remove selection highlight"""
        if self.selected_curve and self.selected_curve_data:
            # Restore original color
            if isinstance(self.selected_curve_data, dict):
                color = self.selected_curve_data.get('color', (0, 1, 0))
                self.selected_curve.GetProperty().SetColor(*color)
                self.selected_curve.GetProperty().SetLineWidth(2)
            
            self.app.vtk_widget.render()
        
        self.selected_curve = None
        self.selected_curve_data = None
        
    def _delete_selected_curve(self):
        """Delete the currently selected curve"""
        if not self.selected_curve_data:
            print("⚠️ No curve selected")
            return
        
        try:
            # Remove actor from renderer
            actor = self.selected_curve_data['actor']
            self.app.vtk_widget.renderer.RemoveActor(actor)
            
            # Remove from finalized list
            self.finalized_actors.remove(self.selected_curve_data)
            
            # Clear selection
            self.selected_curve = None
            self.selected_curve_data = None
            
            # Render
            self.app.vtk_widget.render()
            
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage("🗑️ Curve deleted", 2000)
                
        except Exception as e:
            print(f"❌ Failed to delete curve: {e}")
            import traceback
            traceback.print_exc()
        
    def _edit_selected_curve_color(self):
        """Open color picker to change selected curve color"""
        if not self.selected_curve or not self.selected_curve_data:
            print("⚠️ No curve selected - Right-click on a curve first")
            return
        
        # Get current color
        current_color = self.selected_curve_data.get('color', (0, 1, 0))
        qcolor = QColor.fromRgbF(current_color[0], current_color[1], current_color[2])
        
        # Show color picker
        new_color = QColorDialog.getColor(qcolor, self.app, "Choose Curve Color")
        
        if new_color.isValid():
            # Convert to RGB tuple (0-1 range)
            rgb = (new_color.redF(), new_color.greenF(), new_color.blueF())
            
            # Update curve color
            self.selected_curve.GetProperty().SetColor(*rgb)
            self.selected_curve_data['color'] = rgb
            
            self.app.vtk_widget.render()
            
            print(f"🎨 Curve color changed to RGB({rgb[0]:.2f}, {rgb[1]:.2f}, {rgb[2]:.2f})")
            
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage("🎨 Curve color updated", 2000)
        
    def _create_curve_actor(self, points, color=(0, 1, 0), width=2):
        """Create VTK Actor2D for a curve (Always on Top)"""
        # 1. Create Points
        vtk_points = vtk.vtkPoints()
        vtk_points.SetDataTypeToDouble() # High precision
        for pt in points:
            vtk_points.InsertNextPoint(pt)
        
        # 2. Create PolyLine
        polyline = vtk.vtkPolyLine()
        polyline.GetPointIds().SetNumberOfIds(len(points))
        for i in range(len(points)):
            polyline.GetPointIds().SetId(i, i)
        
        cells = vtk.vtkCellArray()
        cells.InsertNextCell(polyline)
        
        polydata = vtk.vtkPolyData()
        polydata.SetPoints(vtk_points)
        polydata.SetLines(cells)
        
        # 3. Use Mapper 2D
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(polydata)
        
        # 4. Map World 3D Coords -> Screen 2D
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        mapper.SetTransformCoordinate(coord)
        
        # 5. Create Actor 2D
        actor = vtk.vtkActor2D()
        actor.SetMapper(mapper)
        
        # 6. Styling & Foreground Force
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetLineWidth(width)
        actor.GetProperty().SetDisplayLocationToForeground() # CRITICAL: Draws on top of data
        
        return actor
    
    def clear_all_curves(self):
        """Clear EVERYTHING related to curves (final + preview + dynamic)"""

        print("🧹 Clearing all curve data...")

        # ✅ 1. Remove finalized curves
        for curve_data in self.finalized_actors:
            actor = curve_data['actor'] if isinstance(curve_data, dict) else curve_data
            self.app.vtk_widget.renderer.RemoveActor(actor)

        self.finalized_actors = []

        # ✅ 2. Clear preview (CRITICAL FIX)
        self._clear_preview()

        # ✅ 3. Reset state
        self.points = []
        self.undo_stack = []
        self.redo_stack = []
        self.history_stack = []
        self.history_redo_stack = []

        # ✅ 4. Clear curve entries from digitizer (if any left) to ensure NO LINK in undo
        if hasattr(self.app, 'digitizer'):
            # Filter out all 'curve' type drawings
            self.app.digitizer.drawings = [
                d for d in self.app.digitizer.drawings 
                if d.get('type') != 'curve'
            ]
            print("   🧹 Cleared curves from digitizer drawings list")

        # ✅ 5. Clear selection
        self.selected_curve = None
        self.selected_curve_data = None

        # ✅ 6. Force render refresh
        self.app.vtk_widget.render()

        print("✅ All curves + previews cleared")


    def undo_curve(self):
        """Undo the last completed curve (whole-operation undo after right-click)."""
        if not self.history_stack:
            print("⚠️ No completed curve to undo")
            return

        curve_data = self.history_stack.pop()

        # Save to redo stack
        self.history_redo_stack.append(curve_data)

        # Remove actor from renderer and finalized list
        try:
            self.finalized_actors.remove(curve_data)
        except ValueError:
            pass
        self.app.vtk_widget.renderer.RemoveActor(curve_data['actor'])

        self.app.vtk_widget.render()
        print(f"↶ Undo completed curve (history: {len(self.history_stack)})")

        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage("↶ Curve undone | Ctrl+Y to redo", 2000)

    def redo_curve(self):
        """Redo the last undone completed curve."""
        if not self.history_redo_stack:
            print("⚠️ Nothing to redo")
            return

        curve_data = self.history_redo_stack.pop()

        # Push back to history
        self.history_stack.append(curve_data)

        # Re-add actor and finalized entry
        self.finalized_actors.append(curve_data)
        self.app.vtk_widget.renderer.AddActor(curve_data['actor'])

        self.app.vtk_widget.render()
        print(f"↷ Redo completed curve (history: {len(self.history_stack)})")

        if hasattr(self.app, 'statusBar'):
            self.app.statusBar().showMessage("↷ Curve redone", 2000)    
