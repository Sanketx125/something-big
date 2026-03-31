"""
Measurement Tools for NakshaAI
Vertex-to-vertex distance measurement with live display
"""

import time
import vtk
import numpy as np


class MeasurementTool:
    """
    Live measurement tool for vertex-to-vertex distances.
    Shows distance labels as you draw measurement lines.
    """
    
    def __init__(self, digitizer):
        self.digitizer = digitizer
        self.app = digitizer.app
        self.renderer = digitizer.renderer
        self.interactor = digitizer.interactor


        self.original_interactor_style = self.interactor.GetInteractorStyle()
        
        # Storage
        # Storage
        self.measurements = []
        self.active_measurement = None
        self.temp_line_actor = None
        self.distance_labels = []
        self.vertex_markers = []
        self.continuous_line_actor = None
        # ✅ Overlay renderer for always-on-top measurement lines
        self._overlay_renderer = None
        try:
            rw = self.app.vtk_widget.GetRenderWindow()
            for i in range(rw.GetRenderers().GetNumberOfItems()):
                ren = rw.GetRenderers().GetItemAsObject(i)
                if ren.GetLayer() == 1 and not ren.GetInteractive():
                    self._overlay_renderer = ren
                    break
        except Exception:
            pass
        # ⚡ Throttle + reuse state for fast mouse-move preview (Microstation-style)
        self._render_timer = None
        self._last_z = 0.0
        self._last_preview_time = 0.0          # epoch time of last preview render
        self._preview_interval = 0.0           # no frame cap — render every mouse event
        self._preview_pts = None               # reusable vtkPoints (2-pt line)
        self._preview_polydata = None          # reusable vtkPolyData for preview
        self._preview_actor_in_scene = False   # track whether actor was added
        self._last_cursor_pos = None           # last known world cursor position
        
        # Selection
        # Selection
        self.selected_measurement_index = None
        self.selected_segment_index = None  # Track individual segment
        self.original_colors = {}  # Store original colors for unhighlighting
        
        # Mouse state
        self.active = False
        self.is_measuring = False
        self.is_panning = False 
        self.measurement_points = []
        self._observer_tags = [] 
        # Undo/Redo state
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo_levels = 50
        self._temp_vertex_stack = []

    def _ensure_overlay_renderer(self):
        """
        Lazily create a Layer-1 renderer that shares the main camera.
        All measurement actors live here so they always draw on top of the point cloud.
        """
        if self._overlay_renderer is not None:
            return self._overlay_renderer

        render_window = self.app.vtk_widget.GetRenderWindow()
        # We need at least 2 layers
        if render_window.GetNumberOfLayers() < 2:
            render_window.SetNumberOfLayers(2)

        ren = vtk.vtkRenderer()
        ren.SetLayer(1)                             # Draw on top of layer 0 (point cloud)
        ren.InteractiveOff()                        # Don't intercept mouse events
        ren.SetBackground(0.0, 0.0, 0.0)
        ren.SetBackgroundAlpha(0.0)                 # Fully transparent background
        ren.EraseOff()                              # CRITICAL: don't glClear() before rendering —
                                                    # prevents wiping the point cloud layer
        ren.SetActiveCamera(self.renderer.GetActiveCamera())  # Share camera
        render_window.AddRenderer(ren)

        self._overlay_renderer = ren
        return ren

    def _scene_add(self, actor):
        """Add a measurement actor to the overlay renderer (always on top)."""
        if actor is None:
            return
        ren = self._ensure_overlay_renderer()
        ren.AddActor(actor)

    def _scene_remove(self, actor):
        """Remove a measurement actor from the overlay renderer."""
        if actor is None:
            return
        if self._overlay_renderer is not None:
            try:
                self._overlay_renderer.RemoveActor(actor)
            except Exception:
                pass
        # Fallback: also try main renderer in case actor ended up there
        try:
            self.renderer.RemoveActor(actor)
        except Exception:
            pass
        
    def _render_overlay_only(self):
        """Throttled full render — safe across all VTK backends."""
        try:
            self.app.vtk_widget.GetRenderWindow().Render()
        except Exception:
            try:
                self.app.vtk_widget.render()
            except Exception:
                pass

    def _update_preview_line(self, p1, p2):
        """
        Update the rubber-band preview line in-place (Microstation-style).
        Reuses a single persistent vtkPolyData — no allocation/GC on every mouse move.
        """
        if self._preview_polydata is None:
            # One-time setup — allocate the reusable VTK pipeline
            ren = self._ensure_overlay_renderer()   # only called once

            pts = vtk.vtkPoints()
            pts.SetNumberOfPoints(2)
            pts.SetPoint(0, p1[0], p1[1], p1[2])
            pts.SetPoint(1, p2[0], p2[1], p2[2])

            cell = vtk.vtkLine()
            cell.GetPointIds().SetId(0, 0)
            cell.GetPointIds().SetId(1, 1)

            cells = vtk.vtkCellArray()
            cells.InsertNextCell(cell)

            pd = vtk.vtkPolyData()
            pd.SetPoints(pts)
            pd.SetLines(cells)

            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(pd)
            mapper.StaticOn()   # hint: geometry won't be re-tessellated each frame

            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0, 1, 1)
            actor.GetProperty().SetLineWidth(2)
            actor.GetProperty().SetOpacity(1.0)
            actor.PickableOff()

            self._preview_pts = pts
            self._preview_polydata = pd
            self.temp_line_actor = actor
            ren.AddActor(actor)
            self._preview_actor_in_scene = True
        else:
            # Hot path: just move the two endpoints — zero allocation, no renderer lookup
            self._preview_pts.SetPoint(0, p1[0], p1[1], p1[2])
            self._preview_pts.SetPoint(1, p2[0], p2[1], p2[2])
            self._preview_pts.Modified()
            self._preview_polydata.Modified()
            if not self._preview_actor_in_scene:
                ren = self._ensure_overlay_renderer()
                ren.AddActor(self.temp_line_actor)
                self._preview_actor_in_scene = True

    def _screen_to_world_fast(self):
        """
        Project screen cursor to world XY at cached Z depth using camera-ray math.
        Zero scene traversal — ~10x faster than picker.Pick() on large point clouds.
        The ray from the camera through pixel (x,y) is intersected with the Z=_last_z plane.
        """
        x, y = self.interactor.GetEventPosition()
        ren = self.renderer

        ren.SetDisplayPoint(x, y, 0.0)
        ren.DisplayToWorld()
        nh = ren.GetWorldPoint()
        w = nh[3] if nh[3] != 0.0 else 1.0
        near = np.array([nh[0]/w, nh[1]/w, nh[2]/w])

        ren.SetDisplayPoint(x, y, 1.0)
        ren.DisplayToWorld()
        fh = ren.GetWorldPoint()
        w = fh[3] if fh[3] != 0.0 else 1.0
        far = np.array([fh[0]/w, fh[1]/w, fh[2]/w])

        direction = far - near
        dz = direction[2]
        if abs(dz) > 1e-10:
            t = (self._last_z - near[2]) / dz
            return (float(near[0] + t * direction[0]),
                    float(near[1] + t * direction[1]),
                    float(self._last_z))
        # Fallback: ray parallel to Z plane — return near point at cached Z
        return (float(near[0]), float(near[1]), float(self._last_z))

    def _hide_preview_line(self):
        """Remove preview actor from scene without deleting VTK objects."""
        if self._preview_actor_in_scene and self._overlay_renderer is not None:
            try:
                self._overlay_renderer.RemoveActor(self.temp_line_actor)
            except Exception:
                pass
            self._preview_actor_in_scene = False

    def _capture_state(self):
        """Capture measurement data (without VTK actors) for undo/redo."""
        state = []
        for measurement in self.measurements:
            state.append({
                'type': measurement.get('type', 'measure_line'),
                'points': [tuple(p) for p in measurement.get('points', [])],
            })
        return state

    def _save_state(self):
        """Save current state to undo stack and clear redo stack."""
        self.undo_stack.append(self._capture_state())
        if len(self.undo_stack) > self.max_undo_levels:
            self.undo_stack.pop(0)
        self.redo_stack = []
        print(f"💾 Measurement state saved (undo stack: {len(self.undo_stack)})")

    def _remove_all_measurement_visuals(self):
        """Remove all finalized measurement actors without touching undo/redo."""
        for measurement in self.measurements:
            for label_data in measurement.get('labels', []):
                try:
                    self._scene_remove(label_data.get('line'))
                except Exception:
                    pass
                try:
                    self._scene_remove(label_data.get('label'))
                except Exception:
                    pass

            for vertex in measurement.get('vertices', []):
                try:
                    self._scene_remove(vertex)
                except Exception:
                    pass

            try:
                self._scene_remove(measurement.get('continuous_line'))
            except Exception:
                pass

    def _clear_active_drawing_visuals(self):
        """Remove in-progress measurement actors."""
        # Hide reusable preview actor without destroying it
        self._hide_preview_line()
        if self.temp_line_actor and not self._preview_polydata:
            # Only destroy if it is NOT the reusable preview actor
            try:
                self._scene_remove(self.temp_line_actor)
            except Exception:
                pass
            self.temp_line_actor = None

        if self.continuous_line_actor:
            try:
                self._scene_remove(self.continuous_line_actor)
            except Exception:
                pass
            self.continuous_line_actor = None

        for label_data in self.distance_labels:
            try:
                self._scene_remove(label_data.get('line'))
            except Exception:
                pass
            try:
                self._scene_remove(label_data.get('label'))
            except Exception:
                pass

        for vertex in self.vertex_markers:
            try:
                self._scene_remove(vertex)
            except Exception:
                pass

        self.distance_labels = []
        self.vertex_markers = []

    def _rebuild_active_measurement(self, points, render=True):
        """Rebuild current in-progress measurement from point list."""
        self._clear_active_drawing_visuals()
        self.measurement_points = []

        for point in points:
            pos = tuple(point)
            self.measurement_points.append(pos)

            if len(self.measurement_points) == 1:
                sphere = self._create_vertex_marker(pos, color=(0, 1, 0), radius=0.02)
            else:
                sphere = self._create_vertex_marker(pos, color=(1, 1, 0), radius=0.02)
                if len(self.vertex_markers) > 1:
                    self.vertex_markers[-1].GetProperty().SetColor(1, 1, 0)
                    self.vertex_markers[-1].sphere_source.SetRadius(0.02)

            self._scene_add(sphere)
            self.vertex_markers.append(sphere)

            if len(self.measurement_points) >= 2 and self.mode != "measure_polygon":
                self._update_continuous_line()
                self._create_distance_line()

        # Restore preview line immediately if cursor position is known (e.g. after undo)
        if render and self.measurement_points and self._last_cursor_pos is not None:
            self._update_preview_line(self.measurement_points[-1], self._last_cursor_pos)

        if render:
            self.app.vtk_widget.GetRenderWindow().Render()

    def _recreate_measurement_from_state(self, measurement_state):
        """Recreate one finalized measurement from captured state."""
        points = measurement_state.get('points', [])
        if len(points) < 2:
            return

        prev_mode = getattr(self, "mode", "measure_line")
        self.mode = measurement_state.get('type', 'measure_line')
        self._rebuild_active_measurement(points, render=False)
        self._finalize_measurement(push_undo=False)
        self.mode = prev_mode

    def _restore_state(self, state):
        """Restore finalized measurements from captured state."""
        prev_mode = getattr(self, "mode", "measure_line")

        self._clear_selection()
        self._remove_all_measurement_visuals()
        self.measurements = []

        self._clear_active_drawing_visuals()
        self.measurement_points = []
        self._temp_vertex_stack = []

        for measurement_state in state:
            self._recreate_measurement_from_state(measurement_state)

        self.mode = prev_mode
                # ⚡ FIX: must repaint all layers so overlay actors update
        try:
            self.app.vtk_widget.GetRenderWindow().Render()
        except Exception:
            self.app.vtk_widget.render()
        print(f"✅ Measurement state restored: {len(self.measurements)} measurements")

    def undo(self):
        """Undo last measurement operation (Ctrl+Z)."""
        if self.measurement_points:
            if self._temp_vertex_stack:
                prev_points = self._temp_vertex_stack.pop()
                self._rebuild_active_measurement(prev_points)
            else:
                self._rebuild_active_measurement([])
            return

        if not self.undo_stack:
            print("⚠️ Nothing to undo")
            return

        current_state = self._capture_state()
        self.redo_stack.append(current_state)
        # Cap redo stack to same limit as undo
        if len(self.redo_stack) > self.max_undo_levels:
            self.redo_stack.pop(0)
        previous_state = self.undo_stack.pop()
        self._restore_state(previous_state)
        print(f"↶ Undo (undo stack: {len(self.undo_stack)}, redo stack: {len(self.redo_stack)})")

    def redo(self):
        """Redo previously undone measurement operation (Ctrl+Y)."""
        if not self.redo_stack:
            print("⚠️ Nothing to redo")
            return

        current_state = self._capture_state()
        self.undo_stack.append(current_state)
        if len(self.undo_stack) > self.max_undo_levels:
            self.undo_stack.pop(0)

        next_state = self.redo_stack.pop()
        self._restore_state(next_state)
        print(f"↷ Redo (undo stack: {len(self.undo_stack)}, redo stack: {len(self.redo_stack)})")

    def activate(self, mode="measure_line"):
        """
        Activate measurement mode with proper tool coordination.
        """
        self.mode = mode
        self.active = True
        self.is_measuring = True
        self.is_panning = False
        self.measurement_points = []
        self.vertex_markers = []
        self._temp_vertex_stack = []
        self._last_cursor_pos = None

        # ✅ CRITICAL FIX: Only remove OUR specific observers, never wipe global events
        if hasattr(self, '_observer_tags') and self._observer_tags:
            for tag in self._observer_tags:
                try:
                    self.interactor.RemoveObserver(tag)
                except:
                    pass
        self._observer_tags = []

        # ---------------------------------------------------------
        # 🔥 HIGH PRIORITY (2.0): Measurement tool observers
        # ---------------------------------------------------------
        # NOTE: We DO NOT call RemoveObservers("EventType") anymore.
        # This preserves default camera controls (rotate/orbit).
        # ---------------------------------------------------------

        self._tag_left_button = self.interactor.AddObserver("LeftButtonPressEvent", self._on_click, 2.0)
        self._tag_mouse_move  = self.interactor.AddObserver("MouseMoveEvent", self._on_mouse_move, 2.0)
        tag3 = self.interactor.AddObserver("RightButtonPressEvent", self._on_right_click_select, 2.0)
        tag4 = self.interactor.AddObserver("KeyPressEvent", self._on_key_press, 2.0)
        tag5 = self.interactor.AddObserver("MiddleButtonPressEvent", self._on_middle_press, 2.0)
        tag6 = self.interactor.AddObserver("MiddleButtonReleaseEvent", self._on_middle_release, 2.0)
        self._observer_tags.extend([self._tag_left_button, self._tag_mouse_move, tag3, tag4, tag5, tag6])

        print(f"📏 Measurement tool activated: {mode} (priority 2.0)")
        self.app.statusBar().showMessage(
            "📏 Left-click: measure | Middle-click: pan | Right-click: finish/select | ESC: cancel",
            5000
        )


    def deactivate(self):
        """Deactivate measurement tool but keep selection/deletion active."""
        self.active = False
        self.is_measuring = False
        self.is_panning = False
        
        # ✅ FIX: We do NOT remove observers here.
        # We just set is_measuring=False so _on_click and _on_mouse_move return early.
        # This keeps the selection (RightClick) and Deletion (KeyPress) active
        # without breaking default camera controls.

        # Clear temp visuals — hide reusable preview actor, don't destroy
        self._hide_preview_line()

        if self.continuous_line_actor:
            try:
                self._scene_remove(self.continuous_line_actor)
            except:
                pass
            self.continuous_line_actor = None

        self.measurement_points = []
        self.vertex_markers = []
        self._temp_vertex_stack = []
        print("📏 Measurement drawing deactivated (selection/deletion still active)")
    
    def _on_click(self, _obj, _evt):  # noqa: unused-args — VTK callback signature
        """Handle left click to add measurement point."""
        self.is_panning = False  # Safety reset: left-click always ends any panning state
        if self.interactor.GetShiftKey():
            return  # Allow shift+click for camera
        if not self.is_measuring:
            return
        if self._should_block_measurement():
            return
        # Allow ctrl/alt for camera controls
        if self.interactor.GetControlKey() or self.interactor.GetAltKey():
            return

        # Consume the click so the interactor style does NOT enter rotate state.
        try:
            self.interactor.GetInteractorStyle().AbortFlagOn()
        except Exception:
            pass

        self._temp_vertex_stack.append(list(self.measurement_points))
        
        pos = self.digitizer._get_mouse_world()
        self._last_z = pos[2]  # ← cache Z for fast preview
        self.measurement_points.append(pos)
        
        # Add vertex marker with color coding
        # First point = GREEN, Last point = RED (will update as we add more)
        if len(self.measurement_points) == 1:
            # First point - GREEN
            sphere = self._create_vertex_marker(pos, color=(0, 1, 0), radius=0.02)
        else:
            # Middle points - YELLOW
            sphere = self._create_vertex_marker(pos, color=(1, 1, 0), radius=0.02)
            
            # Update previous "end" vertex from RED back to YELLOW (if it exists and isn't the first)
            if len(self.vertex_markers) > 1:
                self.vertex_markers[-1].GetProperty().SetColor(1, 1, 0)  # Yellow
                self.vertex_markers[-1].sphere_source.SetRadius(0.02)
        
        self._scene_add(sphere)
        self.vertex_markers.append(sphere)
        
        # (verbose per-click prints removed to avoid Python overhead in hot path)
        
        # Update continuous line through all points
       # Update continuous line through all points
        # Update continuous line through all points
        if len(self.measurement_points) >= 2:
            # For line mode, create the line and finalize immediately after 2 points
            if self.mode != "measure_polygon":
                self._update_continuous_line()
                self._create_distance_line()
            
            # For polygon mode, also show closing line preview
            if self.mode == "measure_polygon" and len(self.measurement_points) >= 3:
                self._update_polygon_closing_line()
        
        self.app.vtk_widget.render()
    
    def _on_mouse_move(self, obj, evt):
        """Show preview line as mouse moves — throttled to 40 fps, zero-alloc hot path."""
        if self._allow_camera_pan(obj, evt):
            return   # Middle button: allow panning
        if not self.is_measuring or not self.measurement_points:
            return   # Not measuring: allow normal camera rotation

        # Consume the mouse-move event during active measurement so the
        # interactor style does not rotate/pan the camera.
        try:
            self.interactor.GetInteractorStyle().AbortFlagOn()
        except Exception:
            pass

        # ⚡ Frame-rate cap: skip render if last preview was < 25 ms ago
        now = time.monotonic()
        if now - self._last_preview_time < self._preview_interval:
            return
        self._last_preview_time = now

        if self._should_block_measurement():
            return

        try:
            pos = self._screen_to_world_fast()   # no picker — pure camera math
        except Exception:
            return

        last_point = self.measurement_points[-1]
        self._last_cursor_pos = pos             # cache for post-undo restore

        # ⚡ Reuse preview actor — no VTK object allocation per frame
        self._update_preview_line(last_point, pos)

        # Distance calculations — use pre-built numpy array to avoid repeated casting
        pts = self.measurement_points
        lp = np.asarray(last_point)
        cp = np.asarray(pos)
        next_distance = float(np.linalg.norm(cp - lp))

        if self.mode == "measure_polygon" and len(pts) >= 3:
            arr = np.asarray(pts)
            current_total = float(np.sum(np.linalg.norm(np.diff(arr, axis=0), axis=1)))
            closing_distance = float(np.linalg.norm(cp - arr[0]))
            total_if_closed = current_total + next_distance + closing_distance
            self.app.statusBar().showMessage(
                f"📏 Current: {current_total:.2f} m | Next: {next_distance:.2f} m | "
                f"Close: {closing_distance:.2f} m | Total: {total_if_closed:.2f} m", 100
            )
        elif self.mode == "measure_path" and len(pts) >= 2:
            arr = np.asarray(pts)
            current_total = float(np.sum(np.linalg.norm(np.diff(arr, axis=0), axis=1)))
            self.app.statusBar().showMessage(
                f"📏 Current: {current_total:.2f} m | Next: {next_distance:.2f} m | "
                f"Total: {current_total + next_distance:.2f} m", 100
            )
        else:
            self.app.statusBar().showMessage(f"📏 Distance: {next_distance:.2f} m", 100)

        self._render_overlay_only()
    
    def _on_right_click_select(self, obj, evt):
        """Right click to select measurement or finalize current drawing."""
        # If we're actively drawing, finalize the measurement
        if self.measurement_points and len(self.measurement_points) >= 2:
            self._finalize_measurement()
            # Stop drawing after finalizing path/polygon
            if self.mode in ['measure_line', 'measure_path', 'measure_polygon']:
                self.stop_drawing()
                self.app.statusBar().showMessage("✅ Measurement completed. Click the button again to draw more.", 3000)    
            return
            
        # Otherwise, select a measurement
        # Try cell picker first
        self._select_measurement_at_cursor()
        
        # If that didn't work, try distance-based selection
        if self.selected_measurement_index is None:
            print("🔄 Trying alternative selection method...")
            self._select_measurement_at_cursor_alternative()
            
            # If that didn't work, try distance-based selection
            if self.selected_measurement_index is None:
                print("🔄 Trying alternative selection method...")
                self._select_measurement_at_cursor_alternative()
        
    def _create_distance_line(self):
        """Create a line with distance label between last two points."""
        if len(self.measurement_points) < 2:
            return
        
        p1 = self.measurement_points[-2]
        p2 = self.measurement_points[-1]
        
        # Calculate distance
        distance = np.linalg.norm(np.array(p2) - np.array(p1))
        
        # Create line actor (make it easier to pick by increasing width)
        line_actor = self._create_line_actor([p1, p2], color=(1, 1, 0), width=4)
        if line_actor:
            self._scene_add(line_actor)
        # Create distance label at midpoint
        if self.mode == "measure_line":
            label_actor = None
        else:
            midpoint = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, (p1[2] + p2[2]) / 2)
            label_actor = self._create_distance_label(midpoint, distance)
            self._scene_add(label_actor)
        
        # Store for later removal
       # Store for later removal
        label_entry = {
            'line': line_actor,
            'label': label_actor,
            'p1': p1,
            'p2': p2,
            'distance': distance
        }
        self.distance_labels.append(label_entry)
        
        print(f"📏 Distance: {distance:.3f} m (stored {len(self.distance_labels)} labels)")
    
    def _finalize_measurement(self, push_undo=True):
        """Finalize the current measurement."""
        if push_undo and len(self.measurement_points) >= 2:
            self._save_state()

        # Hide preview line — use hide (not destroy) to keep reusable actor for next session
        self._hide_preview_line()
        
        total_distance = 0.0
        area = 0.0
        
        # Calculate total distance for all modes
        if len(self.measurement_points) >= 2:
            for i in range(len(self.measurement_points) - 1):
                p1 = self.measurement_points[i]
                p2 = self.measurement_points[i + 1]
                total_distance += np.linalg.norm(np.array(p2) - np.array(p1))
        
        # Handle polygon mode - close the shape and calculate area
        if self.mode == "measure_polygon" and len(self.measurement_points) >= 3:
            # Add closing segment from last point to first point
            first_point = self.measurement_points[0]
            last_point = self.measurement_points[-1]
            
            # Calculate closing distance
            closing_distance = np.linalg.norm(np.array(first_point) - np.array(last_point))
            total_distance += closing_distance
            
            # Create closing line with distance label
            closing_line_actor = self._create_line_actor([last_point, first_point], color=(1, 0.5, 0), width=4)
            if closing_line_actor:
                self._scene_add(closing_line_actor)
            
            # Create distance label for closing segment
            midpoint = (
                (first_point[0] + last_point[0]) / 2,
                (first_point[1] + last_point[1]) / 2,
                (first_point[2] + last_point[2]) / 2
            )
            closing_label_actor = self._create_distance_label(midpoint, closing_distance)
            if closing_label_actor:
                self._scene_add(closing_label_actor)
            
            # Store closing segment
            self.distance_labels.append({
                'line': closing_line_actor,
                'label': closing_label_actor,
                'p1': last_point,
                'p2': first_point,
                'distance': closing_distance
            })
            
            # Calculate area
            area = self._calculate_polygon_area(self.measurement_points)
            
            print(f"📏 Polygon perimeter: {total_distance:.3f} m")
            print(f"📐 Polygon area: {area:.3f} m²")
            
            # Create combined summary label at centroid
            centroid = np.mean(self.measurement_points, axis=0)
            summary_label = self._create_polygon_summary_label(centroid, total_distance, area)
            if summary_label:
                self._scene_add(summary_label)
                print(f"  ✅ Created summary label at centroid: {centroid}")
                # Store the summary label so it can be deleted later
                self.distance_labels.append({
                    'line': None,
                    'label': summary_label,
                    'p1': centroid,
                    'p2': centroid,
                    'distance': 0
                })
            else:
                print(f"  ⚠️ Failed to create summary label")
            
            self.app.statusBar().showMessage(
                f"📏 Perimeter: {total_distance:.2f} m | Area: {area:.2f} m²", 
                5000
            )
        
        elif self.mode == "measure_path" and len(self.measurement_points) > 2:
            # Calculate area (treating path as if it were closed)
            area = self._calculate_polygon_area(self.measurement_points)
            
            print(f"📏 Total path distance: {total_distance:.3f} m")
            print(f"📐 Enclosed area: {area:.3f} m²")
            
            # Create combined label at the centroid
            centroid = np.mean(self.measurement_points, axis=0)
            combined_label = self._create_path_summary_label(centroid, total_distance, area)
            if combined_label:
                self._scene_add(combined_label)
                print(f"  ✅ Created summary label at centroid: {centroid}")
                # Store the label so it can be deleted later
                self.distance_labels.append({
                    'line': None,
                    'label': combined_label,
                    'p1': centroid,
                    'p2': centroid,
                    'distance': 0
                })
            else:
                print(f"  ⚠️ Failed to create summary label")
            
            self.app.statusBar().showMessage(
                f"📏 Total: {total_distance:.2f} m | Area: {area:.2f} m²", 
                5000
            )
        
        elif self.mode == "measure_line" and len(self.measurement_points) >= 2:
            print(f"📏 Line distance: {total_distance:.3f} m")
            self.app.statusBar().showMessage(f"📏 Total Distance: {total_distance:.2f} m", 5000)
            # Create single total distance label at midpoint of the full line
            # Place label near the last point, slightly offset
            last_pt = self.measurement_points[-1]
            second_last_pt = self.measurement_points[-2]
            seg_dir = np.array(last_pt) - np.array(second_last_pt)
            seg_len = np.linalg.norm(seg_dir[:2])
            if seg_len > 0:
                perp = np.array([-seg_dir[1], seg_dir[0], 0]) / seg_len
            else:
                perp = np.array([0, 1, 0])
            offset_amount = total_distance * 0.02
            offset_pt = (
                last_pt[0] + perp[0] * offset_amount,
                last_pt[1] + perp[1] * offset_amount,
                last_pt[2]
            )
            total_label = self._create_distance_label(offset_pt, total_distance)
            if total_label:
                self._scene_add(total_label)
                self.distance_labels.append({
                    'line': None,
                    'label': total_label,
                    'p1': last_pt,
                    'p2': last_pt,
                    'distance': total_distance
                })
        if len(self.vertex_markers) > 0:
            if self.mode == "measure_line":
                # For line: first=GREEN, last=RED
                if len(self.vertex_markers) >= 2:
                    self.vertex_markers[-1].GetProperty().SetColor(1, 0, 0)  # Red
                    self.vertex_markers[-1].sphere_source.SetRadius(0.02)
            elif self.mode in ["measure_path", "measure_polygon"]:
                # For path/polygon: first=GREEN, last=RED, middle=YELLOW
                if len(self.vertex_markers) >= 2:
                    self.vertex_markers[-1].GetProperty().SetColor(1, 0, 0)  # Red
                    self.vertex_markers[-1].sphere_source.SetRadius(0.02)
        
        # Store measurement with all visual elements
        self.measurements.append({
            'type': self.mode,
            'points': list(self.measurement_points),
            'labels': list(self.distance_labels),
            'vertices': list(self.vertex_markers),
            'continuous_line': self.continuous_line_actor,
            'total_distance': total_distance,
            'area': area  # Store area for all modes
        })
        
        
        # Reset for next measurement
        self.measurement_points = []
        self.distance_labels = []
        self.vertex_markers = []
        self.continuous_line_actor = None
        self._temp_vertex_stack = []
        
        print(f"✅ Measurement finalized ({self.mode})")
    
    def clear_all_measurements(self):
        """Remove all measurement lines and labels."""
        if self.measurements:
            self._save_state()

        # Clear any selection first
        self._clear_selection()
        
        for measurement in self.measurements:
            # Remove all visual elements
            for label_data in measurement['labels']:
                try:
                    self._scene_remove(label_data['line'])
                    self._scene_remove(label_data['label'])
                except:
                    pass
            
            # Remove vertex markers
            for vertex in measurement.get('vertices', []):
                try:
                    self._scene_remove(vertex)
                except:
                    pass
            
            # Remove continuous line if exists
            if 'continuous_line' in measurement:
                try:
                    self._scene_remove(measurement['continuous_line'])
                except:
                    pass
        
        self.measurements.clear()
        self.measurement_points = []
        self.distance_labels = []
        self.vertex_markers = []
        self._temp_vertex_stack = []
        # Clear undo/redo stacks so history doesn't bleed after a full clear
        self.undo_stack.clear()
        self.redo_stack.clear()
        
        # Clear temp visuals
        self._hide_preview_line()

        if self.continuous_line_actor:
            try:
                self._scene_remove(self.continuous_line_actor)
            except:
                pass
            self.continuous_line_actor = None

# ⚡ FIX: vtk_widget.render() only repaints layer 0 (point cloud).
        # Measurement actors live in overlay renderer at layer 1.
        # Must call GetRenderWindow().Render() to repaint ALL layers,
        # otherwise removed overlay actors remain visible until next
        # full-window render event.
        try:
            rw = self.app.vtk_widget.GetRenderWindow()
            for i in range(rw.GetRenderers().GetNumberOfItems()):
                ren = rw.GetRenderers().GetItemAsObject(i)
                if ren.GetLayer() == 1 and not ren.GetInteractive():
                    ren.RemoveAllViewProps()
        except Exception:
            pass

        try:
            self.app.vtk_widget.GetRenderWindow().Render()
        except Exception:
            self.app.vtk_widget.render()
        print("🗑️ All measurements cleared")
    # ============================================================
    # HELPER METHODS
    # ============================================================
    
    def _create_vertex_marker(self, position, color=(1, 1, 0), radius=0.03):
        """Create a sphere marker at vertex position."""
        sphere = vtk.vtkSphereSource()
        sphere.SetRadius(radius)
        sphere.SetCenter(position)
        sphere.SetThetaResolution(8)   # Sufficient for visual quality, 75% fewer triangles
        sphere.SetPhiResolution(8)
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(color)
        actor.GetProperty().SetOpacity(0.8)
        actor.PickableOff()
        
        # Store reference to the sphere source for later radius modification
        actor.sphere_source = sphere
        
        return actor
    
    def _create_line_actor(self, points, color=(1, 1, 0), width=3):
        """Create a line actor connecting points."""
        if len(points) < 2:
            return None
        
        try:
            vtk_points = vtk.vtkPoints()
            for p in points:
                vtk_points.InsertNextPoint(p)
            
            line = vtk.vtkPolyLine()
            line.GetPointIds().SetNumberOfIds(len(points))
            for i in range(len(points)):
                line.GetPointIds().SetId(i, i)
            
            cells = vtk.vtkCellArray()
            cells.InsertNextCell(line)
            
            polydata = vtk.vtkPolyData()
            polydata.SetPoints(vtk_points)
            polydata.SetLines(cells)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(polydata)
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(color)
            actor.GetProperty().SetLineWidth(width)
            actor.GetProperty().SetOpacity(1.0)  # Ensure fully opaque
            actor.PickableOn()  # Make pickable for deletion
            actor.GetProperty().RenderLinesAsTubesOn()
            return actor
        except Exception as e:
            print(f"  ⚠️ Error creating line actor: {e}")
            return None
    
    def _create_distance_label(self, position, distance):
        """Create a beautiful modern distance label."""
        # Compact format with visual separator
        text = f"↔ {distance:.2f}m"
        
        # Create billboard text (always faces camera)
        text_actor = vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(text)
        text_actor.SetPosition(position)
        
        # Style the text - sleek minimal style
        prop = text_actor.GetTextProperty()
        prop.SetColor(1.0, 1.0, 1.0)  # Pure white
        prop.SetFontSize(16)
        prop.BoldOn()
        prop.SetBackgroundOpacity(0.0)  # Fully transparent - no box
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        prop.SetFrame(False)            # No border
        
        text_actor.PickableOn()
        
        return text_actor
    
    def export_measurements(self):
        """Export measurements to text format."""
        if not self.measurements:
            print("⚠️ No measurements to export")
            return None
        
        output = []
        output.append("="*60)
        output.append("MEASUREMENT REPORT")
        output.append("="*60)
        
        for i, measurement in enumerate(self.measurements, 1):
            output.append(f"\nMeasurement {i} ({measurement['type']}):")
            output.append("-" * 40)
            
            for j, label_data in enumerate(measurement['labels'], 1):
                p1 = label_data['p1']
                p2 = label_data['p2']
                dist = label_data['distance']
                
                output.append(f"  Segment {j}:")
                output.append(f"    From: ({p1[0]:.2f}, {p1[1]:.2f}, {p1[2]:.2f})")
                output.append(f"    To:   ({p2[0]:.2f}, {p2[1]:.2f}, {p2[2]:.2f})")
                output.append(f"    Distance: {dist:.3f} m")
            
            # Add total distance and area if available
            if 'total_distance' in measurement and measurement['total_distance'] > 0:
                output.append(f"\n  Total Distance: {measurement['total_distance']:.3f} m")
            
            if 'area' in measurement and measurement['area'] > 0:
                output.append(f"  Total Area: {measurement['area']:.3f} m²")
        
        output.append("\n" + "="*60)
        
        report = "\n".join(output)
        print(report)
        return report
    

    def _update_continuous_line(self):
        """Update the continuous line connecting all measurement points."""
        # Remove old continuous line
        if self.continuous_line_actor:
            try:
                self._scene_remove(self.continuous_line_actor)
            except:
                pass
        
        # Create new continuous line through all points
        # Create new continuous line through all points
        if len(self.measurement_points) >= 2:
            self.continuous_line_actor = self._create_line_actor(
                self.measurement_points, 
                color=(1, 1, 0), 
                width=2
            )
            # Make continuous line non-pickable so only segments can be selected
            self.continuous_line_actor.PickableOff()
            self._scene_add(self.continuous_line_actor)
    
    def _on_key_press(self, obj, evt):
        """Handle key press for deleting measurements."""
        key = self.interactor.GetKeySym()
        key_lower = key.lower() if isinstance(key, str) else ""

        if self.interactor.GetControlKey() and key_lower == "z":
            self.undo()
            return
        if self.interactor.GetControlKey() and key_lower == "y":
            self.redo()
            return
        
        if key == "Delete" or key == "BackSpace":
            if self.is_measuring and self.measurement_points:
                print("↶ BackSpace/Delete → Undo last point")
                self.undo()
            elif self.selected_measurement_index is not None:
                self._delete_selected_measurement()
            else:
                print("⚠️ No point to undo or measurement selected. Right-click on a line to select it first.")
        elif key == "Escape":
            self._clear_selection()
        
    def _delete_selected_measurement(self):
        """Delete the currently selected segment and rebuild the measurement."""
        if self.selected_measurement_index is None or self.selected_segment_index is None:
            print("⚠️ No segment selected")
            return
        
        if self.selected_measurement_index >= len(self.measurements):
            print("⚠️ Invalid selection")
            self.selected_measurement_index = None
            self.selected_segment_index = None
            return
        
        measurement = self.measurements[self.selected_measurement_index]
        
        if self.selected_segment_index >= len(measurement['labels']):
            print("⚠️ Invalid segment")
            return
        
        self._save_state()

        # FOR LINE MODE: Just delete the entire measurement (it only has 1 segment anyway)
        if measurement['type'] == 'measure_line':
            self._remove_entire_measurement(self.selected_measurement_index)
            self.selected_measurement_index = None
            self.selected_segment_index = None
            self.original_colors.clear()
            self.app.vtk_widget.render()
            print("🗑️ Line measurement deleted")
            return
        
        # FOR PATH/POLYGON MODE: Smart deletion and rebuild
        points = measurement.get('points', [])
        
        if not points or len(points) <= 2:
            # If too few points, delete entire measurement
            self._remove_entire_measurement(self.selected_measurement_index)
            self.selected_measurement_index = None
            self.selected_segment_index = None
            self.original_colors.clear()
            self.app.vtk_widget.render()
            return
        
        # Remove the point at selected_segment_index + 1 
        # (because segment i connects point i to point i+1)
        if self.selected_segment_index + 1 < len(points):
            points.pop(self.selected_segment_index + 1)
            print(f"  🗑️ Removed point at index {self.selected_segment_index + 1}")
        elif self.selected_segment_index == len(points) - 1:
            # If it's the closing segment in polygon mode, remove the last point
            points.pop(-1)
            print(f"  🗑️ Removed last point (closing segment)")
        
        # Clear all visual elements for this measurement
        for label_data in measurement['labels']:
            try:
                if label_data['line']:
                    self._scene_remove(label_data['line'])
                self._scene_remove(label_data['label'])
            except:
                pass
        
        for vertex in measurement.get('vertices', []):
            try:
                self._scene_remove(vertex)
            except:
                pass
        
        if 'continuous_line' in measurement and measurement['continuous_line']:
            try:
                self._scene_remove(measurement['continuous_line'])
            except:
                pass
        
        # Rebuild the entire measurement from remaining points
        measurement['labels'] = []
        measurement['vertices'] = []
        measurement['points'] = points
        
        # Create new vertex markers
        # Create new vertex markers with color coding
        for i, point in enumerate(points):
            if i == 0:
                # First point - GREEN
                sphere = self._create_vertex_marker(point, color=(0, 1, 0), radius=0.02)
            elif i == len(points) - 1:
                # Last point - RED
                sphere = self._create_vertex_marker(point, color=(1, 0, 0), radius=0.02)
            else:
                # Middle points - YELLOW
                sphere = self._create_vertex_marker(point, color=(1, 1, 0), radius=0.02)
            
            self._scene_add(sphere)
            measurement['vertices'].append(sphere)
        
        # Create new segments
        # Create new segments
        total_distance = 0.0
        for i in range(len(points) - 1):
            p1 = points[i]
            p2 = points[i + 1]
            distance = np.linalg.norm(np.array(p2) - np.array(p1))
            total_distance += distance
            
            # Create line
            line_actor = self._create_line_actor([p1, p2], color=(1, 1, 0), width=4)
            self._scene_add(line_actor)
            
            # Create label
            midpoint = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, (p1[2] + p2[2]) / 2)
            label_actor = self._create_distance_label(midpoint, distance)
            self._scene_add(label_actor)
            
            measurement['labels'].append({
                'line': line_actor,
                'label': label_actor,
                'p1': p1,
                'p2': p2,
                'distance': distance
            })
        
        # CHECK: If no valid segments were created, delete entire measurement
        if len(measurement['labels']) == 0:
            print("⚠️ No valid segments remaining after deletion")
            self._remove_entire_measurement(self.selected_measurement_index)
            self.selected_measurement_index = None
            self.selected_segment_index = None
            self.original_colors.clear()
            self.app.vtk_widget.render()
            return
        
        # For polygon mode, add closing segment
        if measurement['type'] == 'measure_polygon' and len(points) >= 3:
            p1 = points[-1]
            p2 = points[0]
            distance = np.linalg.norm(np.array(p2) - np.array(p1))
            total_distance += distance
            
            line_actor = self._create_line_actor([p1, p2], color=(1, 0.5, 0), width=4)
            self._scene_add(line_actor)
            
            midpoint = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, (p1[2] + p2[2]) / 2)
            label_actor = self._create_distance_label(midpoint, distance)
            self._scene_add(label_actor)
            
            measurement['labels'].append({
                'line': line_actor,
                'label': label_actor,
                'p1': p1,
                'p2': p2,
                'distance': distance
            })
        elif measurement['type'] == 'measure_polygon' and len(points) < 3:
            # Polygon needs at least 3 points, delete if not enough
            print("⚠️ Polygon needs at least 3 points, deleting measurement")
            self._remove_entire_measurement(self.selected_measurement_index)
            self.selected_measurement_index = None
            self.selected_segment_index = None
            self.original_colors.clear()
            self.app.vtk_widget.render()
            return
        
        # Rebuild continuous line
        if len(points) >= 2 and measurement['type'] in ['measure_path', 'measure_polygon']:
            continuous_line_actor = self._create_line_actor(points, color=(1, 1, 0), width=2)
            continuous_line_actor.PickableOff()
            self._scene_add(continuous_line_actor)
            measurement['continuous_line'] = continuous_line_actor
        
        # Recalculate area and create summary
        # Recalculate area and create summary
        area = 0.0
        if len(points) >= 3:
            area = self._calculate_polygon_area(points)
        
        measurement['total_distance'] = total_distance
        measurement['area'] = area
        
        # Only create summary label if measurement is valid (has actual segments)
        if total_distance > 0.001 and len(points) >= 2:
            # Create new summary label
            centroid = np.mean(points, axis=0)
            if measurement['type'] == 'measure_polygon':
                summary_label = self._create_polygon_summary_label(centroid, total_distance, area)
            elif measurement['type'] == 'measure_path':
                summary_label = self._create_path_summary_label(centroid, total_distance, area)
            else:
                summary_label = None
            
            if summary_label:
                self._scene_add(summary_label)
                measurement['labels'].append({
                    'line': None,
                    'label': summary_label,
                    'p1': centroid,
                    'p2': centroid,
                    'distance': 0
                })
        else:
            # No valid measurement, delete it
            print("⚠️ No valid measurement remaining (total_distance = 0)")
            self._remove_entire_measurement(self.selected_measurement_index)
            self.selected_measurement_index = None
            self.selected_segment_index = None
            self.original_colors.clear()
            self.app.vtk_widget.render()
            return
        
        print(f"✅ Measurement rebuilt: {len(points)} points, {total_distance:.2f} m, {area:.2f} m²")
        
        # Clear selection
        self.selected_measurement_index = None
        self.selected_segment_index = None
        self.original_colors.clear()
        
        self.app.vtk_widget.render()


    def _remove_entire_measurement(self, measurement_index):
        """Helper to remove an entire measurement."""
        if measurement_index >= len(self.measurements):
            return
            
        measurement = self.measurements[measurement_index]
        
        for label_data in measurement['labels']:
            try:
                if label_data['line']:
                    self._scene_remove(label_data['line'])
                self._scene_remove(label_data['label'])
            except:
                pass
        
        for vertex in measurement.get('vertices', []):
            try:
                self._scene_remove(vertex)
            except:
                pass
        
        if 'continuous_line' in measurement and measurement['continuous_line']:
            try:
                self._scene_remove(measurement['continuous_line'])
            except:
                pass
        
        self.measurements.pop(measurement_index)
        print(f"🗑️ Entire measurement removed")

    def _select_measurement_at_cursor(self):
        """Select the individual segment under the cursor."""
        # Use CellPicker for better line picking
        picker = vtk.vtkCellPicker()
        picker.SetTolerance(0.01)  # Increase tolerance for easier picking
        
        pos = self.interactor.GetEventPosition()
        picker.Pick(pos[0], pos[1], 0, self.renderer)
        picked_actor = picker.GetActor()
        
        if not picked_actor:
            print("⚠️ No measurement at cursor position")
            return
        
        print(f"🔍 Picked actor: {picked_actor}")
        
        # Clear previous selection
        self._clear_selection()
        
        # Find which specific segment this actor belongs to
        for i, measurement in enumerate(self.measurements):
            for j, label_data in enumerate(measurement['labels']):
                if picked_actor == label_data['line']:
                    # Select this specific segment
                    self.selected_measurement_index = i
                    self.selected_segment_index = j
                    self._highlight_segment(i, j)
                    print(f"✅ Segment {j+1} of Measurement {i+1} selected (Press Delete to remove)")
                    self.app.statusBar().showMessage(f"✅ Segment {j+1} selected (Press Delete to remove)", 3000)
                    return
            
            # Also check continuous line
            # Also check continuous line - if clicked, select the closest segment
            if 'continuous_line' in measurement and measurement['continuous_line']:
                if picked_actor == measurement['continuous_line']:
                    print(f"📍 Clicked continuous line - finding closest segment...")
                    # Use alternative method to find closest segment
                    self._select_closest_segment_to_click(i)
                    return
        
        print("⚠️ Clicked on a non-selectable element")
    def _highlight_measurement(self, index):
        """Highlight the selected measurement in blue."""
        if index >= len(self.measurements):
            return
        
        measurement = self.measurements[index]
        
        # Store original colors and highlight lines
        for label_data in measurement['labels']:
            line_actor = label_data['line']
            # Store original color
            original_color = line_actor.GetProperty().GetColor()
            self.original_colors[id(line_actor)] = original_color
            # Set to blue
            line_actor.GetProperty().SetColor(0, 0.5, 1)  # Bright blue
            line_actor.GetProperty().SetLineWidth(5)  # Make thicker
        
        # Highlight continuous line
        if 'continuous_line' in measurement and measurement['continuous_line']:
            line_actor = measurement['continuous_line']
            original_color = line_actor.GetProperty().GetColor()
            self.original_colors[id(line_actor)] = original_color
            line_actor.GetProperty().SetColor(0, 0.5, 1)  # Bright blue
            line_actor.GetProperty().SetLineWidth(4)  # Make thicker
        
        # Highlight vertices
        for vertex in measurement.get('vertices', []):
            original_color = vertex.GetProperty().GetColor()
            self.original_colors[id(vertex)] = original_color
            vertex.GetProperty().SetColor(0, 0.5, 1)  # Bright blue
        
        self.app.vtk_widget.render()
    
    def _clear_selection(self):
        """Clear the current selection and restore original colors."""
        if self.selected_measurement_index is None:
            return
        
        if self.selected_measurement_index >= len(self.measurements):
            self.selected_measurement_index = None
            self.selected_segment_index = None
            self.original_colors.clear()
            return
        
        measurement = self.measurements[self.selected_measurement_index]
        
        # Restore original colors for all actors that were highlighted
        for actor_id, original_color in self.original_colors.items():
            # Find the actor by ID
            for label_data in measurement['labels']:
                if id(label_data['line']) == actor_id:
                    label_data['line'].GetProperty().SetColor(original_color)
                    label_data['line'].GetProperty().SetLineWidth(3)
            
            for vertex in measurement.get('vertices', []):
                if id(vertex) == actor_id:
                    vertex.GetProperty().SetColor(original_color)
        
        self.selected_measurement_index = None
        self.selected_segment_index = None
        self.original_colors.clear()
        
        self.app.vtk_widget.render()


    def _highlight_segment(self, measurement_index, segment_index):
        """Highlight only the selected segment (one line + its two vertices)."""
        if measurement_index >= len(self.measurements):
            return
        
        measurement = self.measurements[measurement_index]
        
        if segment_index >= len(measurement['labels']):
            return
        
        label_data = measurement['labels'][segment_index]
        
        # Highlight the line segment
        line_actor = label_data['line']
        original_color = line_actor.GetProperty().GetColor()
        self.original_colors[id(line_actor)] = original_color
        line_actor.GetProperty().SetColor(0, 0.5, 1)  # Bright blue
        line_actor.GetProperty().SetLineWidth(5)  # Make thicker
        
        # Highlight the two vertices of this segment
        # Get the points for this segment
        p1 = label_data['p1']
        p2 = label_data['p2']
        
        # Find and highlight the vertices at these positions
        for vertex in measurement.get('vertices', []):
            vertex_pos = vertex.GetMapper().GetInput().GetCenter()
            
            # Check if this vertex is at p1 or p2 (with small tolerance)
            if (abs(vertex_pos[0] - p1[0]) < 0.01 and 
                abs(vertex_pos[1] - p1[1]) < 0.01 and 
                abs(vertex_pos[2] - p1[2]) < 0.01) or \
               (abs(vertex_pos[0] - p2[0]) < 0.01 and 
                abs(vertex_pos[1] - p2[1]) < 0.01 and 
                abs(vertex_pos[2] - p2[2]) < 0.01):
                
                original_color = vertex.GetProperty().GetColor()
                self.original_colors[id(vertex)] = original_color
                vertex.GetProperty().SetColor(0, 0.5, 1)  # Bright blue
        
        self.app.vtk_widget.render()


    def _update_continuous_line_for_measurement(self, measurement_index):
        """Rebuild the continuous line for a measurement after segment deletion."""
        if measurement_index >= len(self.measurements):
            return
        
        measurement = self.measurements[measurement_index]
        
        # Remove old continuous line
        if 'continuous_line' in measurement and measurement['continuous_line']:
            try:
                self._scene_remove(measurement['continuous_line'])
            except:
                pass
        
        # Rebuild points list from remaining segments (excluding summary labels)
        points = []
        if measurement['labels']:
            # Only process actual segments (not summary labels where distance = 0)
            valid_segments = [label_data for label_data in measurement['labels'] 
                            if label_data['distance'] > 0]
            
            if valid_segments:
                # Add first point
                points.append(valid_segments[0]['p1'])
                # Add all second points
                for label_data in valid_segments:
                    points.append(label_data['p2'])
        
        # Create new continuous line only if we have valid points
        if len(points) >= 2:
            continuous_line_actor = self._create_line_actor(points, color=(1, 1, 0), width=2)
            continuous_line_actor.PickableOff()  # Make non-pickable
            self._scene_add(continuous_line_actor)
            measurement['continuous_line'] = continuous_line_actor
        else:
            measurement['continuous_line'] = None


    def _select_measurement_at_cursor_alternative(self):
        """Alternative selection using world coordinates."""
        # Get the 3D world position of the click
        click_pos = self.digitizer._get_mouse_world()
        
        if click_pos is None:
            print("⚠️ Could not get world position")
            return
        
        print(f"🔍 Click position: {click_pos}")
        
        # Clear previous selection
        self._clear_selection()
        
        # Find the closest segment to the click position
        min_distance = float('inf')
        closest_measurement_idx = None
        closest_segment_idx = None
        
        for i, measurement in enumerate(self.measurements):
            for j, label_data in enumerate(measurement['labels']):
                p1 = np.array(label_data['p1'])
                p2 = np.array(label_data['p2'])
                click = np.array(click_pos)
                
                # Calculate distance from click point to line segment
                line_vec = p2 - p1
                line_len = np.linalg.norm(line_vec)
                
                if line_len < 0.001:  # Degenerate segment
                    continue
                
                line_unitvec = line_vec / line_len
                
                # Project click point onto the line
                point_vec = click - p1
                projection_length = np.dot(point_vec, line_unitvec)
                
                # Clamp to segment
                projection_length = max(0, min(line_len, projection_length))
                
                # Get closest point on segment
                closest_point = p1 + line_unitvec * projection_length
                
                # Calculate distance
                distance = np.linalg.norm(click - closest_point)
                
                if distance < min_distance:
                    min_distance = distance
                    closest_measurement_idx = i
                    closest_segment_idx = j
        
        # If we found a segment within reasonable distance (e.g., 1 meter)
        if closest_measurement_idx is not None and min_distance < 1.0:
            self.selected_measurement_index = closest_measurement_idx
            self.selected_segment_index = closest_segment_idx
            self._highlight_segment(closest_measurement_idx, closest_segment_idx)
            print(f"✅ Segment {closest_segment_idx+1} of Measurement {closest_measurement_idx+1} selected (distance: {min_distance:.2f}m)")
            self.app.statusBar().showMessage(f"✅ Segment {closest_segment_idx+1} selected (Press Delete to remove)", 3000)
        else:
            print(f"⚠️ No segment found within 1m (closest was {min_distance:.2f}m away)")


    def _select_closest_segment_to_click(self, measurement_index):
        """Select the segment closest to the click position."""
        click_pos = self.digitizer._get_mouse_world()
        
        if click_pos is None:
            print("⚠️ Could not get world position")
            return
        
        measurement = self.measurements[measurement_index]
        
        # Find the closest segment
        min_distance = float('inf')
        closest_segment_idx = None
        
        for j, label_data in enumerate(measurement['labels']):
            p1 = np.array(label_data['p1'])
            p2 = np.array(label_data['p2'])
            click = np.array(click_pos)
            
            # Calculate distance from click point to line segment
            line_vec = p2 - p1
            line_len = np.linalg.norm(line_vec)
            
            if line_len < 0.001:  # Degenerate segment
                continue
            
            line_unitvec = line_vec / line_len
            
            # Project click point onto the line
            point_vec = click - p1
            projection_length = np.dot(point_vec, line_unitvec)
            
            # Clamp to segment
            projection_length = max(0, min(line_len, projection_length))
            
            # Get closest point on segment
            closest_point = p1 + line_unitvec * projection_length
            
            # Calculate distance
            distance = np.linalg.norm(click - closest_point)
            
            if distance < min_distance:
                min_distance = distance
                closest_segment_idx = j
        
        if closest_segment_idx is not None:
            self.selected_measurement_index = measurement_index
            self.selected_segment_index = closest_segment_idx
            self._highlight_segment(measurement_index, closest_segment_idx)
            print(f"✅ Segment {closest_segment_idx+1} selected (closest to click, {min_distance:.2f}m away)")
            self.app.statusBar().showMessage(f"✅ Segment {closest_segment_idx+1} selected (Press Delete to remove)", 3000)
        else:
            print("⚠️ No valid segment found")
    
    def _calculate_polygon_area(self, points):
        """Calculate the area of a polygon using the Shoelace formula (2D projection)."""
        if len(points) < 3:
            return 0.0
        
        # Project to XY plane (ignore Z coordinate for area calculation)
        # Using Shoelace formula: Area = 0.5 * |sum(x[i]*y[i+1] - x[i+1]*y[i])|
        area = 0.0
        n = len(points)
        
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]
        
        area = abs(area) / 2.0
        return area
    

    def _create_area_label(self, position, area):
        """Create a 3D text label showing area."""
        # Format area string
        if area >= 1000000:
            text = f"Area: {area/1000000:.2f} km²"
        elif area >= 1:
            text = f"Area: {area:.2f} m²"
        else:
            text = f"Area: {area*10000:.1f} cm²"
        
        # Create billboard text (always faces camera)
        text_actor = vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(text)
        text_actor.SetPosition(position)
        
        # Style the text - make it larger and different color
        prop = text_actor.GetTextProperty()
        prop.SetColor(0, 1, 0.5)  # Cyan/green for area
        prop.SetFontSize(24)
        prop.BoldOn()
        prop.SetBackgroundColor(0, 0, 0)
        prop.SetBackgroundOpacity(0.8)
        
        text_actor.PickableOn()  # Make pickable for deletion
        
        return text_actor
    


    def _create_polygon_summary_label(self, position, perimeter, area):
        """Create an ultra-modern premium label for polygon measurements."""
        # Format with consistent meters
        perim_text = f"{perimeter:.1f}"
        area_text = f"{area:.2f}"
        
        # Premium format with gradient symbols
        text = f"◆ {perim_text}m  ◇  {area_text}m²"
        
        # Create billboard text (always faces camera)
        text_actor = vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(text)
        text_actor.SetPosition(position)
        
        # Style - premium neon style
        prop = text_actor.GetTextProperty()
        prop.SetColor(0.2, 1.0, 0.8)  # Neon cyan
        prop.SetFontSize(12)
        prop.BoldOn()
        prop.SetBackgroundColor(0.0, 0.05, 0.1)  # Almost black with blue tint
        prop.SetBackgroundOpacity(0.9)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        prop.SetFrameColor(0.0, 0.8, 1.0)  # Electric blue border
        prop.SetFrame(True)
        prop.SetFrameWidth(3)
        
        text_actor.PickableOn()
        
        return text_actor


    def _create_path_summary_label(self, position, total_distance, area):
        """Create an ultra-modern premium label for path measurements."""
        # Format with consistent meters
        dist_text = f"{total_distance:.1f}"
        area_text = f"{area:.2f}"
        
        # Premium format with gradient symbols
        text = f"▸ {dist_text}m  ◇  {area_text}m²"
        
        # Create billboard text (always faces camera)
        text_actor = vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(text)
        text_actor.SetPosition(position)
        
        # Style - premium gold style
        prop = text_actor.GetTextProperty()
        prop.SetColor(1.0, 0.85, 0.3)  # Premium gold
        prop.SetFontSize(12)
        prop.BoldOn()
        prop.SetBackgroundColor(0.1, 0.05, 0.0)  # Dark with warm tint
        prop.SetBackgroundOpacity(0.9)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        prop.SetFrameColor(1.0, 0.6, 0.0)  # Orange-gold border
        prop.SetFrame(True)
        prop.SetFrameWidth(3)
        
        text_actor.PickableOn()
        
        return text_actor


    def _create_distance_label(self, position, distance):
        """Create an ultra-modern premium distance label."""
        # Sleek minimal format
        text = f"— {distance:.2f}m —"
        
        # Create billboard text (always faces camera)
        text_actor = vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(text)
        text_actor.SetPosition(position)
        
        # Style - sleek white-blue
        prop = text_actor.GetTextProperty()
        prop.SetColor(1.0, 1.0, 1.0)  # Pure white
        prop.SetFontSize(16)
        prop.BoldOn()
        prop.SetBackgroundOpacity(0.0)  # No background box
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        prop.SetFrame(False)            # No border
        
        text_actor.PickableOn()
        
        return text_actor


    def _create_total_distance_label(self, position, total_distance):
        """Create a 3D text label showing total distance/perimeter."""
        # Format distance string
        if total_distance >= 1000:
            text = f"Total: {total_distance/1000:.2f} km"
        elif total_distance >= 1:
            text = f"Total: {total_distance:.2f} m"
        else:
            text = f"Total: {total_distance*100:.1f} cm"
        
        # Create billboard text (always faces camera)
        text_actor = vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(text)
        text_actor.SetPosition(position)
        
        # Style the text - make it large and prominent
        prop = text_actor.GetTextProperty()
        prop.SetColor(1, 0.5, 0)  # Orange for total
        prop.SetFontSize(28)  # Large font
        prop.BoldOn()
        prop.SetBackgroundColor(0, 0, 0)
        prop.SetBackgroundOpacity(0.9)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        
        text_actor.PickableOn()  # Make pickable for deletion
        
        return text_actor
    

    def _create_path_summary_label(self, position, total_distance, area):
        """Create a beautiful modern text label for path measurements."""
        # Format with consistent meters
        dist_text = f"{total_distance:.1f}m"
        area_text = f"{area:.2f}m²"
        
        # Beautiful modern format with emoji icons
        text = f"📏 {dist_text}  •  {area_text}"
        
        # Create billboard text (always faces camera)
        text_actor = vtk.vtkBillboardTextActor3D()
        text_actor.SetInput(text)
        text_actor.SetPosition(position)
        
        # Style the text - warm gradient style
        prop = text_actor.GetTextProperty()
        prop.SetColor(1.0, 0.9, 0.4)  # Warm golden glow
        prop.SetFontSize(13)
        prop.BoldOn()
        prop.SetBackgroundColor(0.2, 0.12, 0.05)  # Warm dark amber
        prop.SetBackgroundOpacity(0.85)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        prop.SetFrameColor(1.0, 0.7, 0.2)  # Orange-gold border
        prop.SetFrame(True)
        prop.SetFrameWidth(2)
        
        text_actor.PickableOn()
        
        return text_actor

    def _recalculate_measurement_summary(self, measurement_index):
        """Recalculate and update the summary label after segment deletion."""
        if measurement_index >= len(self.measurements):
            return
        
        measurement = self.measurements[measurement_index]
        
        # Remove old summary label (the one without a line, usually the last one)
        for i in range(len(measurement['labels']) - 1, -1, -1):
            label_data = measurement['labels'][i]
            if label_data['line'] is None:  # This is a summary label
                try:
                    self._scene_remove(label_data['label'])
                    measurement['labels'].pop(i)
                    print("  🗑️ Removed old summary label")
                except:
                    pass
                break
        
        # Recalculate total distance
        total_distance = 0.0
        for label_data in measurement['labels']:
            if label_data['distance'] > 0:  # Skip summary labels
                total_distance += label_data['distance']
        
        # Recalculate points from remaining segments
        points = []
        if measurement['labels']:
            points.append(measurement['labels'][0]['p1'])
            for label_data in measurement['labels']:
                if label_data['distance'] > 0:  # Skip summary labels
                    points.append(label_data['p2'])
        
        # Recalculate area
        area = 0.0
        if len(points) >= 3:
            area = self._calculate_polygon_area(points)
        
        # Update stored values
        measurement['total_distance'] = total_distance
        measurement['area'] = area
        measurement['points'] = points
        
        # Create new summary label at centroid
        if len(points) >= 2:
            centroid = np.mean(points, axis=0)
            
            # Choose the right label type based on measurement type
            if measurement['type'] == 'measure_polygon':
                summary_label = self._create_polygon_summary_label(centroid, total_distance, area)
            elif measurement['type'] == 'measure_path':
                summary_label = self._create_path_summary_label(centroid, total_distance, area)
            else:
                # For line mode, just show distance
                summary_label = self._create_distance_label(centroid, total_distance)
            
            if summary_label:
                self._scene_add(summary_label)
                # Store the new summary label
                measurement['labels'].append({
                    'line': None,
                    'label': summary_label,
                    'p1': centroid,
                    'p2': centroid,
                    'distance': 0
                })
                print(f"  ✅ Created new summary: Total: {total_distance:.2f} m, Area: {area:.2f} m²")


    def stop_drawing(self):
        """Stop drawing mode but keep selection/deletion active."""
        self.is_measuring = False
        
        for attr in ('_tag_left_button', '_tag_mouse_move'):
            tag = getattr(self, attr, None)
            if tag is not None:
                try:
                    self.interactor.RemoveObserver(tag)
                except Exception:
                    pass
                setattr(self, attr, None)
        
        # Clear temp visuals — hide reusable preview, don't destroy
        self._hide_preview_line()

        if self.continuous_line_actor:
            try:
                self._scene_remove(self.continuous_line_actor)
            except:
                pass
            self.continuous_line_actor = None

        self.measurement_points = []
        self.vertex_markers = []
        self._temp_vertex_stack = []
        print("📏 Drawing stopped (selection/deletion still active)")


    def deactivate_completely(self):
        """
        Completely deactivate measurement tool and remove ALL observers.
        Call this when switching to other tools.
        """
        self.active = False
        self.is_measuring = False
        self.is_panning = False
        
        # ✅ Remove ONLY our stored observer tags
        if hasattr(self, '_observer_tags') and self._observer_tags:
            for tag in self._observer_tags:
                try:
                    self.interactor.RemoveObserver(tag)
                except:
                    pass
            self._observer_tags = []
        
        # Clear temp visuals — hide reusable preview, don't destroy
        self._hide_preview_line()

        if self.continuous_line_actor:
            try:
                self._scene_remove(self.continuous_line_actor)
            except:
                pass
            self.continuous_line_actor = None

        self.measurement_points = []
        self.vertex_markers = []
        self._temp_vertex_stack = []
        print("📏 Measurement tool fully deactivated")


    def _on_middle_press(self, obj, evt):
        """✅ NEW: Handle middle click start (Pan)."""
        self.is_panning = True
        # We do NOT abort the event, so the default interactor style will handle the actual panning
        
    def _on_middle_release(self, obj, evt):
        """Handle middle click end (Pan)."""
        self.is_panning = False
        # Hide stale preview so it redraws from the new camera position
        self._hide_preview_line()
        self.app.vtk_widget.render()

    def _should_block_measurement(self):
        """
        Check if measurement tool should be blocked by other active tools.
        Returns True if another tool should take precedence.
        
        ✅ REMOVED cross-section blocking - tools should coexist peacefully
        """
        # Check digitizer tools (drawing tools like line, rectangle, etc.)
        if hasattr(self.app, 'digitizer'):
            if hasattr(self.app.digitizer, 'active_tool') and self.app.digitizer.active_tool is not None:
                return True
        
        # Check cut section (perpendicular cuts)
        if hasattr(self.app, 'cut_section_controller'):
            if getattr(self.app.cut_section_controller, 'is_drawing', False):
                return True
        
        # ✅ NOTE: Cross-section is NOT blocked anymore - they can coexist
        return False
    
    def _allow_camera_pan(self, obj, evt):
        if evt == "MiddleButtonPressEvent":
            return True
        if self.interactor.GetShiftKey() and evt == "MouseMoveEvent":
            return True
        return False
