import numpy as np
import pyvista as pv
import vtk
from pyvistaqt import QtInteractor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QDockWidget, QHBoxLayout, QPushButton, QLabel, QSpinBox
from PySide6.QtCore import Qt
from .interactor_classify import ClassificationInteractor
from .cut_section_controller import CutSectionController

class SectionController:
    def __init__(self, app ,interactor=None):
        self.app = app
        self.app.cross_view_mode ="side"   # Added by bala for view
        self.P1 = None
        self.P2 = None
        self.half_width = None
        self.active_view = 0  # ✅ Track which view dock is active
        # self._view_section_actors = {}

        # rubberband actors
        self.rubber_points = None
        self.rubber_poly = None
        self.rubber_actor = None
        self.last_mask = None
        self.section_points = None
        self._last_update_time = 0
        self._update_interval = 16

        # section actor (per-view tracking)
        self._section_actor = None
        self._core_actor = None  # ✅ Add these for multi-view
        self._buffer_actor = None
        self.cut_controller = CutSectionController(self.app)
        self.is_cut_mode = False
        self._is_initial_section_plot = True
    # ---------------------------------------------------------------------------
        if interactor is not None:
            self._attach_observers(interactor)
        
        print("✅ SectionController initialized")
        # ------------------------------------------------------------------------------------------
               
    def is_classification_active(self):
        """Check if classification tool is active (blocks section drawing)"""
        return getattr(self.app, 'active_classify_tool', None) is not None
        
    def _should_throttle_update(self):
        """Check if we should skip this update for performance"""
        import time
        current_time = time.time() * 1000  # milliseconds
        if current_time - self._last_update_time < self._update_interval:
            return True  # Skip this update
        self._last_update_time = current_time
        return False
    
    
    def _attach_observers(self, interactor):
        """
        Attach event observers to interactor.
        Can be called later if interactor wasn't available during __init__.
        
        Args:
            interactor: vtk.vtkRenderWindowInteractor
        """
        # Store observer tags for later removal
        if not hasattr(self, '_observer_tags'):
            self._observer_tags = []
        
        # Add observers with HIGH priority (higher than measurement tool's -10.0)
        tag1 = interactor.AddObserver("LeftButtonPressEvent", self.on_left_press, 1.0)
        tag2 = interactor.AddObserver("MouseMoveEvent", self.on_mouse_move, 1.0)
        tag3 = interactor.AddObserver("RightButtonPressEvent", self.on_right_press, 1.0)
        
        self._observer_tags.extend([tag1, tag2, tag3])
        
        print("✅ SectionController observers attached")

    def on_left_press(self, obj, event):
        """Handle left button press."""
        if self.is_classification_active():
            print(f"⏭️ Classification active - section drawing disabled")
            return  # Let classification handle it
        
        # ✅ Check if measurement tool is active and should take priority
        if self._should_block_for_measurement():
            print("📏 Measurement tool active - cross-section blocked")
            return
        
    def _display_to_world_no_snap(self, x, y, z_lock=None):
        """
        TRUE cursor-following conversion.
        No snapping, no picking, zoom-safe.
        """
        ren = self.app.vtk_widget.renderer
 
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToDisplay()
        coord.SetValue(float(x), float(y), 0.0)
 
        world = coord.GetComputedWorldValue(ren)
        P = np.array(world, dtype=np.float64)
 
        if z_lock is not None:
            P[2] = z_lock
 
        return P    
        
    def on_mouse_move(self, obj, evt):
            """Draw preview as mouse moves - handles BOTH cross-section and cut section."""

            # ✅ THROTTLE FIRST - CRITICAL for smooth lines
            if self._should_throttle_update():
                return
            # Safety checks
            if not hasattr(self, 'app') or self.app is None:
                return
            if not hasattr(self, 'interactor') or self.interactor is None:
                return
            
            tool = getattr(self.app, "active_classify_tool", None)
            if tool is None:
                return
            
            # Get current mouse position
            x, y = self.interactor.GetEventPosition()
            
            # Determine if we're in cut section
            vtk_widget = self._get_active_vtk_widget()
            is_cut_section = False
            if hasattr(self.app, 'cut_section_controller'):
                cut_vtk = getattr(self.app.cut_section_controller, 'cut_vtk', None)
                if cut_vtk and vtk_widget == cut_vtk:
                    is_cut_section = True
            
            # ═══════════════════════════════════════════════════════════════════
            # FREEHAND - Collect points while dragging
            # ═══════════════════════════════════════════════════════════════════
            if tool == "freehand" and getattr(self, 'is_drawing_freehand', False):
                try:
                    pt = self._pick_world_point(x, y)
                    P = self._get_view_coordinates(pt)
                    self.drawing_points.append(P)
                    
                    # Store display coordinates for cut section preview
                    if is_cut_section:
                        if not hasattr(self, 'drawing_points_display_cut'):
                            self.drawing_points_display_cut = []
                        self.drawing_points_display_cut.append((x, y))
                        self._draw_freehand_preview_cut()
                    else:
                        self._draw_freehand_preview()
                except Exception:
                    pass
                return
            
            # ═══════════════════════════════════════════════════════════════════
            # BRUSH / POINT - Draw circle at cursor
            # ═══════════════════════════════════════════════════════════════════
            if tool in ("brush", "point"):
                try:
                    pt = self._pick_world_point(x, y)
                    radius = getattr(self.app, "brush_radius", 1.0) if tool == "brush" else getattr(self.app, "point_radius", 0.5)
                    
                    if is_cut_section:
                        self._draw_brush_preview_cut(pt, radius)
                    else:
                        self._draw_brush_preview(pt, radius)
                except Exception:
                    pass
                return
            
            # ═══════════════════════════════════════════════════════════════════
            # LINE / RECTANGLE / CIRCLE - Need P1 and dragging
            # ═══════════════════════════════════════════════════════════════════
            # ✅ FIX: Don't snap during preview - use raw world coordinates
            try:
    
                P2 = self._display_to_world_no_snap(x, y, z_lock=self.P1[2])
                
            except Exception:
                return

            
            # ═══════════════════════════════════════════════════════════════════
            # ABOVE LINE / BELOW LINE
            # ═══════════════════════════════════════════════════════════════════
            if tool in ("above_line", "below_line"):
                if is_cut_section:
                    print(f"🔧 Drawing line preview in CUT SECTION (P1={self.P1[:2]}, P2={P2[:2]})")
                    self._draw_line_preview_cut(self.P1, P2)
                else:
                    self._draw_line_preview(self.P1, P2)
            
            # ═══════════════════════════════════════════════════════════════════
            # RECTANGLE
            # ═══════════════════════════════════════════════════════════════════
            elif tool == "rectangle":
                if is_cut_section:
                    self._draw_rectangle_preview_cut(self.P1, P2)
                else:
                    self._draw_rectangle_preview(self.P1, P2)
            
            # ═══════════════════════════════════════════════════════════════════
            # CIRCLE
            # ═══════════════════════════════════════════════════════════════════
            elif tool == "circle":
                # Calculate center and radius
                center = np.array([
                    (self.P1[0] + P2[0]) / 2,
                    (self.P1[1] + P2[1]) / 2,
                    (self.P1[2] + P2[2]) / 2
                ])
                radius = np.linalg.norm(P2 - self.P1) / 2
                
                if is_cut_section:
                    self._draw_circle_preview_cut(center, radius)
                else:
                    self._draw_circle_preview(center, radius)

    def on_right_press(self, obj, event):
        """Handle right button press."""
        # ✅ Check if measurement tool is active and should take priority
        if self._should_block_for_measurement():
            return

    def _get_view_palette(self, view_index):
        """
        Get the palette for a specific view from DisplayModeDialog.
        Returns view-specific palette or falls back to global palette.
        """
        try:
            if hasattr(self.app, 'display_mode_dialog'):
                dialog = self.app.display_mode_dialog
                target_slot = view_index + 1  # View 1 = slot 1, View 2 = slot 2, etc.
                
                if hasattr(dialog, 'view_palettes') and target_slot in dialog.view_palettes:
                    palette = dialog.view_palettes[target_slot]
                    print(f"   📋 Using view_palettes[{target_slot}] for filtering")
                    return palette
            
            # Fallback to global palette
            print(f"   ⚠️ Using global class_palette (no view-specific palette)")
            return getattr(self.app, 'class_palette', {})
        except Exception as e:
            print(f"   ⚠️ Error getting view palette: {e}")
            return getattr(self.app, 'class_palette', {})

    def _get_visible_classes_from_palette(self, palette):
        """
        Get list of class codes that are visible (show=True) in the palette.
        Returns None if no filtering should be applied (all visible).
        """
        if not palette:
            return None  # No filtering
        
        visible = [code for code, info in palette.items() if info.get('show', True)]
        
        # If all classes are visible, return None (no filtering needed)
        if len(visible) == len(palette):
            return None
        
        return visible if visible else []

    def _make_colors_with_palette(self, points, classes, palette):
        """
        🚀 VECTORIZED COLOR MAPPING: 
        Builds colors using GLOBAL app.class_palette while respecting per-view visibility.
        ✅ SPEED: Processes millions of points in ~5ms.
        ✅ LOGIC: Keeps colors consistent with Main View but allows local hiding.
        """
        import numpy as np
        
        # 1. Initialize result array (default to middle gray)
        colors = np.full((points.shape[0], 3), 128, dtype=np.uint8)
        
        if classes.size == 0:
            return colors

        # 2. Get palettes
        global_palette = getattr(self.app, 'class_palette', {}) or {}
        # If per-view palette is empty, we assume everything is visible
        view_palette = palette if palette else {}

        # 3. Create a Fast Lookup Table (LUT)
        # We find the highest class code to determine LUT size
        max_c = int(classes.max())
        lut = np.zeros((max_c + 1, 3), dtype=np.uint8)

        # 4. Fill the LUT
        # This is where we combine Global Color + View Visibility
        unique_codes = np.unique(classes)
        for code in unique_codes:
            code_int = int(code)
            if code_int > max_c: continue
            
            # Check visibility from the per-view palette
            vp = view_palette.get(code_int, {"show": True})
            is_visible = vp.get("show", True)

            if is_visible:
                # Get the "True" color from the global application palette
                global_entry = global_palette.get(code_int, {"color": (128, 128, 128)})
                lut[code_int] = global_entry.get("color", (128, 128, 128))
            else:
                # If hidden in this view, we paint it background-black
                lut[code_int] = (0, 0, 0)

        # 5. ⚡ THE MAGIC: One-shot vectorized mapping
        # Maps every point to its color based on its classification code
        colors = lut[classes.astype(int)]

        return colors
    
    def _clear_cross_section_point_actors(self, vtk_widget, view_index: int):
        """
        Remove ONLY point-cloud actors for a cross-section view.
        ✅ UNIFIED ACTOR: removes the unified section actor so it can be rebuilt.
        Also clears legacy class_* / section_* names for any leftover old-mode actors.
        NOTE: do NOT call this during a fast GPU refresh — only call on full rebuild.
        """
        if vtk_widget is None or not hasattr(vtk_widget, "actors"):
            return

        # Unified actor for this view (primary target on rebuild)
        unified_name = f"_section_{view_index}_unified"

        # Legacy per-class actor prefixes (safe to remove if they somehow exist)
        prefixes = (
            "class_",                           # class_{code}, class_{code}_border
            f"section_core_{view_index}",        # section_core_{view}_{code}
            f"section_buffer_{view_index}",      # section_buffer_{view}_{code}
        )

        for name in list(vtk_widget.actors.keys()):
            if name == unified_name or any(name.startswith(p) for p in prefixes):
                try:
                    vtk_widget.remove_actor(name, render=False)
                except Exception:
                    pass

    def set_active_view(self, view_index):
        """Don't switch view if cut is locked."""
        # ✅ BLOCK view switch if cut locked
        if hasattr(self.app, 'cut_section_controller'):
            if getattr(self.app.cut_section_controller, 'is_locked', False):
                print(f"🔒 CUT LOCKED - Cannot switch views")
                return
        
        self.active_view = view_index
        print(f"Active view: {view_index}")

    def store_section_data(self, section_index, P1, P2, half_width, core_points, buffer_points, core_mask, buffer_mask):
        """
        ✅ Store section data with view-specific keys
        """
        # Store per-view data
        setattr(self.app, f'section_{section_index}_P1', P1)
        setattr(self.app, f'section_{section_index}_P2', P2)
        setattr(self.app, f'section_{section_index}_half_width', half_width)
        setattr(self.app, f'section_{section_index}_core_points', core_points)
        setattr(self.app, f'section_{section_index}_buffer_points', buffer_points)
        setattr(self.app, f'section_{section_index}_core_mask', core_mask)
        setattr(self.app, f'section_{section_index}_buffer_mask', buffer_mask)
        
        print(f"✅ Stored section data for view {section_index + 1}: {len(core_points)} core, {len(buffer_points)} buffer")

    # ✅ NEW: Get the active VTK widget for current view
    def _get_active_vtk(self):
        """Return the VTK widget for the currently active view."""
        if not hasattr(self, 'active_view'):
            self.active_view = 0
        
        # Check if we have view-specific VTK widgets
        if hasattr(self.app, 'section_vtks') and self.active_view in self.app.section_vtks:
            vtk_widget = self.app.section_vtks[self.active_view]
            print(f"🎯 Using VTK widget for View {self.active_view + 1}")
            return vtk_widget
        
        # Fallback to default sec_vtk
        if hasattr(self.app, 'sec_vtk') and self.app.sec_vtk:
            print(f"⚠️ Falling back to default sec_vtk")
            return self.app.sec_vtk
        
        print(f"❌ No VTK widget found for view {self.active_view}")
        return None

    # ---------------- CLEANUP ----------------
    def clear(self):
        vtk_widget = self._get_active_vtk()
        if vtk_widget:
            vtk_widget.clear()
        if self.rubber_actor:
            self.app.vtk_widget.renderer.RemoveActor(self.rubber_actor)
        self.rubber_actor = None
        self.rubber_points = None
        self.rubber_poly = None
        self._section_actor = None
        self.app.vtk_widget.render()

    def clear_preview(self):
        """Clear only the active drawing preview elements (centerline and rubberband), leaving finalized sections intact."""
        renderer = self.app.vtk_widget.renderer
        needs_render = False
        
        # Clear 3D rubber band
        if hasattr(self, "rubber_actor") and self.rubber_actor:
            renderer.RemoveActor(self.rubber_actor)
            self.rubber_actor = None
            self.rubber_points = None
            self.rubber_poly = None
            needs_render = True
            
        # Clear 2D rubber band
        if hasattr(self, "_rubber_actor_2d") and self._rubber_actor_2d:
            renderer.RemoveActor(self._rubber_actor_2d)
            self._rubber_actor_2d = None
            needs_render = True
            
        # Clear 2D centerline
        if hasattr(self, "_centerline_actor_2d") and self._centerline_actor_2d:
            renderer.RemoveActor(self._centerline_actor_2d)
            self._centerline_actor_2d = None
            needs_render = True
            
        if needs_render:
            self.app.vtk_widget.render()

    # ---------------- RECTANGLE INIT ----------------
    def _init_rectangle(self, npoints=5):
        """OPTIMIZED: Initialize rectangle once with reusable structures"""
        import vtk
        
        if hasattr(self, "rubber_actor") and self.rubber_actor is not None \
        and hasattr(self, "rubber_points") and self.rubber_points is not None \
        and self.rubber_points.GetNumberOfPoints() == npoints:
            print(f"Rectangle already initialized with {npoints} points, skipping")
            return
        
        if hasattr(self, "rubber_actor") and self.rubber_actor:
            try:
                self.app.vtk_widget.renderer.RemoveActor(self.rubber_actor)
            except Exception:
                pass
        
        # Create points array
        self.rubber_points = vtk.vtkPoints()
        self.rubber_points.SetNumberOfPoints(npoints)
        
        for i in range(npoints):
            self.rubber_points.SetPoint(i, 0.0, 0.0, 0.0)
        
        self.rubber_poly = vtk.vtkPolyData()
        self.rubber_poly.SetPoints(self.rubber_points)
        
        # Get user settings
        color = getattr(self.app, "cross_line_color", (1, 0, 1))
        width = getattr(self.app, "cross_line_width", 1)
        style = getattr(self.app, "cross_line_style", "solid")
        
        # Create INITIAL line topology (solid)
        lines = vtk.vtkCellArray()
        for i in range(npoints - 1):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i)
            lines.InsertCellPoint(i + 1)
        
        self.rubber_poly.SetLines(lines)
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(self.rubber_poly)
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        
        self.rubber_actor = vtk.vtkActor()
        self.rubber_actor.SetMapper(mapper)
        
        prop = self.rubber_actor.GetProperty()
        prop.SetColor(color)
        prop.SetLineWidth(width)
        prop.SetOpacity(1.0)
        
        self.app.vtk_widget.renderer.AddActor(self.rubber_actor)
        self._rubber_initialized = True
        print(f"✅ Rectangle geometry initialized with {npoints} points (style: {style})")
        
        # CRITICAL FIX: Apply the style immediately after initialization
        # This will NOT work here because points are all at (0,0,0) initially
        # Style must be applied AFTER points are set to actual positions

    def _init_centerline_2d(self):
        import vtk
 
        self._centerline_points_2d = vtk.vtkPoints()
        self._centerline_points_2d.SetNumberOfPoints(2)
 
        self._centerline_poly_2d = vtk.vtkPolyData()
        self._centerline_poly_2d.SetPoints(self._centerline_points_2d)
 
        lines = vtk.vtkCellArray()
        lines.InsertNextCell(2)
        lines.InsertCellPoint(0)
        lines.InsertCellPoint(1)
        self._centerline_poly_2d.SetLines(lines)
 
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(self._centerline_poly_2d)
 
        actor = vtk.vtkActor2D()
        actor.SetMapper(mapper)
 
        prop = actor.GetProperty()
        prop.SetColor(*getattr(self.app, "cross_line_color", (1, 0, 1)))
        prop.SetLineWidth(getattr(self.app, "cross_line_width", 2))
 
        self.app.vtk_widget.renderer.AddActor2D(actor)
 
        self._centerline_actor_2d = actor    
       

    def update_rectangle_style(self):
        """Update rectangle line style by regenerating geometry for dashed/dotted lines"""
        import numpy as np
        import vtk
        
        if not hasattr(self, "rubber_actor") or self.rubber_actor is None:
            print("⚠️ No rubber_actor found")
            return
        
        if not hasattr(self, "rubber_points") or self.rubber_points is None:
            print("⚠️ No rubber_points found")
            return
        
        # Get current corner points
        npoints = self.rubber_points.GetNumberOfPoints()
        corners = []
        for i in range(npoints):
            pt = self.rubber_points.GetPoint(i)
            corners.append(pt)
        
        if len(corners) < 2:
            print("⚠️ Not enough corner points")
            return
        
        style = getattr(self.app, "cross_line_style", "solid")
        print(f"🎨 Applying style '{style}' to rectangle with {len(corners)} corners")
        
        if style == "solid":
            # Use normal continuous line - restore original topology
            lines = vtk.vtkCellArray()
            for i in range(len(corners) - 1):
                lines.InsertNextCell(2)
                lines.InsertCellPoint(i)
                lines.InsertCellPoint(i + 1)
            
            # CRITICAL: Use original points, not new ones
            self.rubber_poly.SetLines(lines)
            self.rubber_poly.Modified()
            print("✅ Solid line applied")
            return
            
        # ============================================================
        # Create dashed geometry by breaking lines into segments
        # ============================================================
        newpoints = vtk.vtkPoints()
        lines = vtk.vtkCellArray()
        
        # ✅ FIX: Use ABSOLUTE dash/gap lengths instead of ratios
        # This ensures visibility regardless of segment length
        if style == "dashed":
            dash_length = 10.0   # 10 units dash
            gap_length = 5.0     # 5 units gap
        elif style == "dotted":
            dash_length = 2.0    # 2 units (small dots)
            gap_length = 4.0     # 4 units gap
        elif style == "dash-dot":
            # Pattern: long dash, gap, dot, gap, repeat
            dash_pattern = [(10.0, 5.0), (2.0, 5.0)]  # (dash, gap) pairs
        elif style == "dash-dot-dot":
            # Pattern: long dash, gap, dot, gap, dot, gap, repeat
            dash_pattern = [(10.0, 5.0), (2.0, 4.0), (2.0, 5.0)]
        else:
            dash_length = 10.0
            gap_length = 5.0
        
        point_idx = 0
        total_segments = 0
        
        # Create dashed segments for each edge
        for edge_idx in range(len(corners) - 1):
            p1 = np.array(corners[edge_idx])
            p2 = np.array(corners[edge_idx + 1])
            segment_vec = p2 - p1
            segment_len = np.linalg.norm(segment_vec)
            
            if segment_len < 1e-6:
                continue
            
            direction = segment_vec / segment_len
            
            if style in ["dash-dot", "dash-dot-dot"]:
                # Complex pattern with multiple dash types
                t = 0.0
                pattern_idx = 0
                
                while t < segment_len:
                    current_dash, current_gap = dash_pattern[pattern_idx]
                    
                    # Start of dash
                    if t < segment_len:
                        dash_start = p1 + direction * t
                        newpoints.InsertNextPoint(dash_start[0], dash_start[1], dash_start[2])
                        start_idx = point_idx
                        point_idx += 1
                        
                        # End of dash
                        dash_end_t = min(t + current_dash, segment_len)
                        dash_end = p1 + direction * dash_end_t
                        newpoints.InsertNextPoint(dash_end[0], dash_end[1], dash_end[2])
                        end_idx = point_idx
                        point_idx += 1
                        
                        # Add this dash as a line segment
                        lines.InsertNextCell(2)
                        lines.InsertCellPoint(start_idx)
                        lines.InsertCellPoint(end_idx)
                        total_segments += 1
                        
                        # Move to next position
                        t = dash_end_t + current_gap
                    
                    # Move to next pattern element
                    pattern_idx = (pattern_idx + 1) % len(dash_pattern)
            else:
                # Simple pattern (dashed or dotted)
                t = 0.0
                while t < segment_len:
                    # Start of dash
                    dash_start = p1 + direction * t
                    newpoints.InsertNextPoint(dash_start[0], dash_start[1], dash_start[2])
                    start_idx = point_idx
                    point_idx += 1
                    
                    # End of dash
                    dash_end_t = min(t + dash_length, segment_len)
                    dash_end = p1 + direction * dash_end_t
                    newpoints.InsertNextPoint(dash_end[0], dash_end[1], dash_end[2])
                    end_idx = point_idx
                    point_idx += 1
                    
                    # Add this dash as a line segment
                    lines.InsertNextCell(2)
                    lines.InsertCellPoint(start_idx)
                    lines.InsertCellPoint(end_idx)
                    total_segments += 1
                    
                    # Move to next dash (skip gap)
                    t = dash_end_t + gap_length
        
        print(f"✅ Created {point_idx} points and {total_segments} dash segments for '{style}' style")
        
        # Update polydata with new dashed geometry
        self.rubber_poly.SetPoints(newpoints)
        self.rubber_poly.SetLines(lines)
        
        # Notify VTK pipeline that data changed
        self.rubber_poly.Modified()
        
        print(f"✅ Rectangle style updated to: {style}")

            
    def _create_dashed_line_geometry(self, corners, style='solid'):
        """
        Create line segments with gaps for dashed/dotted styles.
        Returns a vtkCellArray with the line segments.
        """
        import vtk
        
        lines = vtk.vtkCellArray()
        
        if style == 'solid':
            # Normal continuous line
            for i in range(len(corners) - 1):
                lines.InsertNextCell(2)
                lines.InsertCellPoint(i)
                lines.InsertCellPoint(i + 1)
            return lines
        
        # For dashed/dotted, we need to create multiple small segments
        new_points = vtk.vtkPoints()
        point_idx = 0
        
        # Define dash/gap ratios for each style
        if style == 'dashed':
            dash_ratio = 0.05  # 5% of segment length
            gap_ratio = 0.03   # 3% of segment length
        elif style == 'dotted':
            dash_ratio = 0.01  # 1% (tiny dashes = dots)
            gap_ratio = 0.02   # 2% gap
        elif style == 'dash-dot':
            dash_ratio = 0.05
            gap_ratio = 0.02
        elif style == 'dash-dot-dot':
            dash_ratio = 0.04
            gap_ratio = 0.015
        else:
            dash_ratio = 0.05
            gap_ratio = 0.03
        
        # Create dashed segments for each edge of the rectangle
        for i in range(len(corners) - 1):
            p1 = np.array(corners[i])
            p2 = np.array(corners[i + 1])
            
            segment_vec = p2 - p1
            segment_len = np.linalg.norm(segment_vec)
            
            if segment_len < 1e-6:
                continue
            
            direction = segment_vec / segment_len
            
            # Create dashes along this edge
            t = 0.0
            while t < segment_len:
                # Start of dash
                dash_start = p1 + direction * t
                new_points.InsertNextPoint(dash_start[0], dash_start[1], dash_start[2])
                start_idx = point_idx
                point_idx += 1
                
                # End of dash
                dash_length = dash_ratio * segment_len
                dash_end_t = min(t + dash_length, segment_len)
                dash_end = p1 + direction * dash_end_t
                new_points.InsertNextPoint(dash_end[0], dash_end[1], dash_end[2])
                end_idx = point_idx
                point_idx += 1
                
                # Add this dash as a line segment
                lines.InsertNextCell(2)

    # ---------------- CENTERLINE ----------------

    def draw_centerline(self, P1, P2):
        """
        TRUE cursor-following centerline (2D overlay, no depth test)
        """
        if self._should_throttle_update():
            return

        # Initialize 2D overlay if needed
        if not hasattr(self, '_centerline_actor_2d') or self._centerline_actor_2d is None:
            self._init_centerline_2d()
 
        renderer = self.app.vtk_widget.renderer
 
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
 
        # P1 → display
        coord.SetValue(P1[0], P1[1], P1[2])
        p1d = coord.GetComputedDisplayValue(renderer)
 
        # P2 → display
        coord.SetValue(P2[0], P2[1], P2[2])
        p2d = coord.GetComputedDisplayValue(renderer)
 
        # Update 2D points
        self._centerline_points_2d.SetPoint(0, p1d[0], p1d[1], 0.0)
        self._centerline_points_2d.SetPoint(1, p2d[0], p2d[1], 0.0)
 
        self._centerline_points_2d.Modified()
        self._centerline_poly_2d.Modified()
 
        self.app.vtk_widget.render()    
    

    def draw_rubber_rectangle(self, P1, P2, half_width):
        """✅ MICROSTATION METHOD: 2D overlay actor - always perfect rectangle"""
       
        # ✅ THROTTLE FIRST
        if self._should_throttle_update():
            return
       
        # ============================================================
        # ✅ USE 2D OVERLAY ACTOR (screen space, not world space)
        # ============================================================
       
        # Get current style BEFORE initialization
        style = getattr(self.app, 'cross_line_style', 'solid')
       
        # Initialize 2D overlay actor if needed
        if not hasattr(self, '_rubber_actor_2d') or self._rubber_actor_2d is None:
            self._init_rectangle_2d()
       
        # Get renderer
        renderer = self.app.vtk_widget.renderer
       
        # ============================================================
        # ✅ Convert P1, P2 to DISPLAY coordinates (screen pixels)
        # ============================================================
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
       
        # P1 to screen
        coord.SetValue(P1[0], P1[1], P1[2])
        p1_display = coord.GetComputedDisplayValue(renderer)
       
        # P2 to screen
        coord.SetValue(P2[0], P2[1], P2[2])
        p2_display = coord.GetComputedDisplayValue(renderer)
       
        # Now work in pure 2D screen space (pixels)
        p1_screen = np.array([p1_display[0], p1_display[1]], dtype=np.float64)
        p2_screen = np.array([p2_display[0], p2_display[1]], dtype=np.float64)
       
        # ============================================================
        # ✅ Calculate rectangle in SCREEN SPACE (always parallel)
        # ============================================================
        vec = p2_screen - p1_screen
        length = np.linalg.norm(vec)
       
        if length < 1e-6:
            return
       
        # Direction and perpendicular in screen space
        dir_vec = vec / length
        perp = np.array([-dir_vec[1], dir_vec[0]], dtype=np.float64)
       
        # Convert half_width from world to screen pixels
        # Estimate: pixels per world unit
        world_dist = np.linalg.norm(P2[:2] - P1[:2])
        if world_dist > 1e-6:
            pixels_per_unit = length / world_dist
            hw_screen = float(half_width) * pixels_per_unit
        else:
            hw_screen = 10.0  # Fallback
       
        offset = perp * hw_screen
       
        # Rectangle corners in screen space
        c1 = p1_screen + offset
        c2 = p2_screen + offset
        c3 = p2_screen - offset
        c4 = p1_screen - offset
       
        # ============================================================
        # ✅ Apply line style by creating dashed/dotted geometry
        # ============================================================
        if style == 'solid':
            # Simple corners for solid line
            corners_display = [
                [c1[0], c1[1]],
                [c2[0], c2[1]],
                [c3[0], c3[1]],
                [c4[0], c4[1]],
                [c1[0], c1[1]],  # Close
            ]
           
            # Update points
            for i, (x, y) in enumerate(corners_display):
                self._rubber_points_2d.SetPoint(i, float(x), float(y), 0.0)
           
            # Solid line topology (4 edges)
            lines = vtk.vtkCellArray()
            for i in range(4):
                lines.InsertNextCell(2)
                lines.InsertCellPoint(i)
                lines.InsertCellPoint(i + 1)
           
            self._rubber_poly_2d.SetLines(lines)
           
        else:
            # ✅ CREATE DASHED GEOMETRY for 2D actor
            corners_2d = [c1, c2, c3, c4, c1]
            dashed_points, dashed_lines = self._create_dashed_rectangle_2d(corners_2d, style)
           
            # Update polydata with dashed geometry
            self._rubber_poly_2d.SetPoints(dashed_points)
            self._rubber_poly_2d.SetLines(dashed_lines)
       
        self._rubber_points_2d.Modified()
        self._rubber_poly_2d.Modified()
       
        # Render
        self.app.vtk_widget.render()
       
        # Store state
        self.P1, self.P2, self.half_width = P1, P2, half_width


    def _create_dashed_rectangle_2d(self, corners, style):
        """Create dashed/dotted geometry for 2D rectangle in screen space"""
        import vtk
        import numpy as np
        
        # Define dash/gap lengths in SCREEN PIXELS
        if style == 'dashed':
            dash_length = 10.0  # pixels
            gap_length = 5.0
        elif style == 'dotted':
            dash_length = 2.0
            gap_length = 4.0
        elif style == 'dash-dot':
            dash_pattern = [(10.0, 5.0), (2.0, 5.0)]
        elif style == 'dash-dot-dot':
            dash_pattern = [(10.0, 5.0), (2.0, 4.0), (2.0, 5.0)]
        else:
            dash_length = 10.0
            gap_length = 5.0
        
        new_points = vtk.vtkPoints()
        lines = vtk.vtkCellArray()
        point_idx = 0
        
        # Create dashed segments for each edge
        for edge_idx in range(len(corners) - 1):
            p1 = np.array(corners[edge_idx], dtype=np.float64)
            p2 = np.array(corners[edge_idx + 1], dtype=np.float64)
            
            edge_vec = p2 - p1
            edge_len = np.linalg.norm(edge_vec)
            
            if edge_len < 1e-6:
                continue
            
            direction = edge_vec / edge_len
            
            if style in ['dash-dot', 'dash-dot-dot']:
                # Complex pattern
                t = 0.0
                pattern_idx = 0
                while t < edge_len:
                    current_dash, current_gap = dash_pattern[pattern_idx]
                    
                    # Dash segment
                    dash_start = p1 + direction * t
                    new_points.InsertNextPoint(dash_start[0], dash_start[1], 0.0)
                    start_idx = point_idx
                    point_idx += 1
                    
                    dash_end_t = min(t + current_dash, edge_len)
                    dash_end = p1 + direction * dash_end_t
                    new_points.InsertNextPoint(dash_end[0], dash_end[1], 0.0)
                    end_idx = point_idx
                    point_idx += 1
                    
                    # Add line segment
                    lines.InsertNextCell(2)
                    lines.InsertCellPoint(start_idx)
                    lines.InsertCellPoint(end_idx)
                    
                    # Next position
                    t = dash_end_t + current_gap
                    pattern_idx = (pattern_idx + 1) % len(dash_pattern)
            else:
                # Simple dashed/dotted
                t = 0.0
                while t < edge_len:
                    # Dash segment
                    dash_start = p1 + direction * t
                    new_points.InsertNextPoint(dash_start[0], dash_start[1], 0.0)
                    start_idx = point_idx
                    point_idx += 1
                    
                    dash_end_t = min(t + dash_length, edge_len)
                    dash_end = p1 + direction * dash_end_t
                    new_points.InsertNextPoint(dash_end[0], dash_end[1], 0.0)
                    end_idx = point_idx
                    point_idx += 1
                    
                    # Add line segment
                    lines.InsertNextCell(2)
                    lines.InsertCellPoint(start_idx)
                    lines.InsertCellPoint(end_idx)
                    
                    # Next dash
                    t = dash_end_t + gap_length
        
        return new_points, lines


    def _init_rectangle_2d(self):
        """Initialize 2D overlay actor (screen space)"""
        import vtk
       
        # Remove old 3D actor if exists
        if hasattr(self, 'rubber_actor') and self.rubber_actor:
            try:
                self.app.vtk_widget.renderer.RemoveActor(self.rubber_actor)
            except Exception:
                pass
            self.rubber_actor = None
       
        # Create 2D points
        self._rubber_points_2d = vtk.vtkPoints()
        self._rubber_points_2d.SetNumberOfPoints(5)
        for i in range(5):
            self._rubber_points_2d.SetPoint(i, 0.0, 0.0, 0.0)
       
        # Create polydata
        self._rubber_poly_2d = vtk.vtkPolyData()
        self._rubber_poly_2d.SetPoints(self._rubber_points_2d)
       
        # Create line cells (initial solid topology)
        lines = vtk.vtkCellArray()
        for i in range(4):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i)
            lines.InsertCellPoint(i + 1)
        self._rubber_poly_2d.SetLines(lines)
       
        # Mapper for 2D
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(self._rubber_poly_2d)
       
        # ✅ CRITICAL: Use Actor2D (renders in SCREEN SPACE)
        self._rubber_actor_2d = vtk.vtkActor2D()
        self._rubber_actor_2d.SetMapper(mapper)
       
        # Set color and width
        color = getattr(self.app, 'cross_line_color', (1, 0, 1))
        width = getattr(self.app, 'cross_line_width', 3)
       
        prop = self._rubber_actor_2d.GetProperty()
        prop.SetColor(*color)
        prop.SetLineWidth(width)
       
        # ✅ Add to renderer (2D overlay)
        self.app.vtk_widget.renderer.AddActor2D(self._rubber_actor_2d)
       
        print("✅ 2D overlay rectangle initialized")
 
    def _remove_actor_from_all_renderers(self, actor, is_2d=False):
        if not actor:
            return
 
        renderers = []
 
        # Main renderer
        if hasattr(self.app, "vtk_widget"):
            renderers.append(self.app.vtk_widget.renderer)
 
        # Active section view renderer
        try:
            vtk_widget = self._get_active_vtk()
            if vtk_widget:
                renderers.append(vtk_widget.renderer)
        except Exception:
            pass
 
        # Digitize / picked renderer (CRITICAL)
        if hasattr(self.app, "digitize_manager"):
            ren = getattr(self.app.digitize_manager, "renderer", None)
            if ren:
                renderers.append(ren)
 
        # Remove from all
        for ren in set(renderers):
            try:
                if is_2d:
                    ren.RemoveActor2D(actor)
                else:
                    ren.RemoveActor(actor)
            except Exception:
                pass
 
 
    #Added by bala
    def finalize_rectangle(self):
        """FINAL FIX: removes rectangle & centerline from ALL renderers"""
 
        # ✅ REMOVE 2D CENTERLINE
        if hasattr(self, '_centerline_actor_2d') and self._centerline_actor_2d:
            self._remove_actor_from_all_renderers(
                self._centerline_actor_2d, is_2d=True
            )
            self._centerline_actor_2d = None
            self._centerline_points_2d = None
            self._centerline_poly_2d = None
 
        # ✅ REMOVE 2D RECTANGLE OVERLAY (THIS WAS MISSING)
        if hasattr(self, '_rubber_actor_2d') and self._rubber_actor_2d:
            self._remove_actor_from_all_renderers(
                self._rubber_actor_2d, is_2d=True
            )
            self._rubber_actor_2d = None
            self._rubber_points_2d = None
            self._rubber_poly_2d = None
 
        # ✅ REMOVE 3D RUBBER ACTOR
        if self.rubber_actor:
            self._remove_actor_from_all_renderers(
                self.rubber_actor, is_2d=False
            )
            self.rubber_actor = None
            self.rubber_points = None
            self.rubber_poly = None
            self._rubber_initialized = False
 
        self.app.vtk_widget.render()
        print("✅ Rectangle finalized (removed from ALL renderers)")


    def finalize_section(self, P1, P2):
                """
                ✅ MICROSTATION METHOD:
                - Width = ONLY what user dragged (half_width)
                - Buffer extends LENGTH (along the line) only
                ✅ FIXED:
                - Stores section-local transformed coordinates (X=along, Y=across, Z=elev)
                    so CUT SECTION works again
                - Creates the selected cross-section dock on-demand
                - Keeps world-point copies for debugging / future needs
                """
    
                import numpy as np
    
                # ---------------- SAFETY ----------------
                if self.half_width is None:
                    print("⚠️ Half width not set")
                    return
    
                if not hasattr(self.app, 'data') or self.app.data is None or 'xyz' not in self.app.data:
                    print("❌ No point cloud data loaded!")
                    self.finalize_rectangle()
                    return
    
                xyz = self.app.data["xyz"]
                if xyz is None or len(xyz) == 0:
                    print("❌ Point cloud data is empty!")
                    self.finalize_rectangle()
                    return
    
                # Apply line style before finalizing rectangle
                style = getattr(self.app, "cross_line_style", "solid")
                if style != "solid":
                    print(f"🎨 Applying {style} style to rectangle before finalization")
                    if hasattr(self, 'update_rectangle_style'):
                        try:
                            self.update_rectangle_style()
                            self.app.vtk_widget.render()
                            print(f"✅ Style applied: {style}")
                        except Exception as e:
                            print(f"⚠️ Failed to apply style: {e}")
    
                # Remove preview rectangle
                self.finalize_rectangle()
    
                # ---------------- GEOMETRY ----------------
                v = P2[:2] - P1[:2]
                length = float(np.linalg.norm(v))
                if length < 1e-9:
                    print("❌ Invalid section line (zero length)")
                    return
    
                dir_vec = v / length
                perp = np.array([-dir_vec[1], dir_vec[0]], dtype=np.float64)
    
                buffer = float(getattr(self.app, "section_buffer", 2.0))
    
                print(f"✅ Cross-section computed:")
                print(f"   Line: P1={P1[:2]}, P2={P2[:2]}")
                print(f"   Length: {length:.2f}m")
                print(f"   Core width: ±{self.half_width:.2f}m (user drag)")
                print(f"   Buffer depth: {buffer:.2f}m (length extension only)")
    
                # ── MICROSTATION-LEVEL MEMORY: minimal allocs for 50M-point files ──
                # rel would be (N,2) float64 = 800 MB for 50M pts — avoid it.
                # @ operator with (N,2)·(2,) is BLAS-optimised; peak = 1.6 GB.
                rel    = xyz[:, :2] - P1[:2]   # (N,2) float64 — freed below
                along  = rel @ dir_vec          # (N,)  float64
                across = rel @ perp             # (N,)  float64
                del rel                         # free 800 MB immediately

                half_w = float(self.half_width)
                core_mask = (
                    (along >= 0.0) & (along <= length) &
                    (np.abs(across) <= half_w)
                )

                buffer_mask = (
                    (along >= -buffer) & (along <= length + buffer) &
                    (np.abs(across) <= half_w) &
                    (~core_mask)
                )

                full_mask = core_mask | buffer_mask

                core_count  = int(np.count_nonzero(core_mask))
                buf_count   = int(np.count_nonzero(buffer_mask))
                total_count = core_count + buf_count

                print(f"   Core points: {core_count}")
                print(f"   Buffer points: {buf_count}")

                if total_count == 0:
                    del along, across
                    print("⚠️ No points found in cross-section")
                    return

                # ── BUILD SECTION-LOCAL POINTS (float32 — sufficient for display) ──
                # Coordinate system: X=along (0..length), Y=across (±half_w), Z=elev.
                # float64 → float32 halves section-point memory (12 B vs 24 B/pt).
                core_indices    = np.flatnonzero(core_mask)
                buffer_indices  = np.flatnonzero(buffer_mask)
                # section_indices: core-first, buffer-second (preserves display order)
                section_indices = np.concatenate([core_indices, buffer_indices])

                # Extract filtered coords from along/across, then free them
                _ca = along[core_mask];   _cb = across[core_mask]
                _ba = along[buffer_mask]; _bb = across[buffer_mask]
                del along, across   # free 800 MB — masks already computed

                core_points_local = np.column_stack([
                    _ca, _cb, xyz[core_indices, 2]
                ]).astype(np.float32, copy=False)
                del _ca, _cb

                buffer_points_local = np.column_stack([
                    _ba, _bb, xyz[buffer_indices, 2]
                ]).astype(np.float32, copy=False)
                del _ba, _bb

                # all_points_local: concat instead of recomputing full_mask pass
                all_points_local = np.vstack([core_points_local, buffer_points_local])

                # World-coordinate copies eliminated — use indices for on-demand access.
                # (xyz[section_indices] if ever needed downstream)

                # ---------------- STORE PER-VIEW DATA ----------------
                view_index = int(getattr(self, "active_view", 0))
    
                setattr(self.app, f'section_{view_index}_P1', P1)
                setattr(self.app, f'section_{view_index}_P2', P2)
                setattr(self.app, f'section_{view_index}_half_width', float(self.half_width))
    
                # ✅ Store LOCAL points (used for plotting + picking + cut-section workflow)
                setattr(self.app, f'section_{view_index}_core_points', core_points_local)
                setattr(self.app, f'section_{view_index}_buffer_points', buffer_points_local)
    
                setattr(self.app, f'section_{view_index}_core_mask', core_mask)
                setattr(self.app, f'section_{view_index}_buffer_mask', buffer_mask)
                setattr(self.app, f'section_{view_index}_core_indices', core_indices)
                setattr(self.app, f'section_{view_index}_buffer_indices', buffer_indices)
                setattr(self.app, f'section_{view_index}_indices', section_indices)
    
                # ✅ These are what CutSectionController reads
                setattr(self.app, f'section_{view_index}_points_transformed', all_points_local)
                setattr(self.app, f'section_{view_index}_combined_mask', full_mask)
    
                print(f"💾 Stored section data for View {view_index + 1}")
                print(f"   ✅ Transformed coordinates stored for cut section ({len(all_points_local)} points)")
    
                # ---------------- STORE GLOBAL (BACKWARD COMPAT) ----------------
                # Many parts of your app re-use these globals
                self.app.section_core_points = core_points_local
                self.app.section_buffer_points = buffer_points_local
                self.app.section_core_mask = core_mask
                self.app.section_core_indices = core_indices
                self.app.section_indices = section_indices
    
                self.last_mask = full_mask
                self.app.section_points = all_points_local  # ✅ IMPORTANT: section_points should be LOCAL in cross-section context
    
                # ---------------- ENSURE DOCK EXISTS ----------------
                if not hasattr(self.app, 'section_vtks') or view_index not in self.app.section_vtks:
                    print(f"🔨 Creating View {view_index + 1} dock on-demand...")
                    if hasattr(self.app, '_open_specific_cross_section_view'):
                        self.app._open_specific_cross_section_view(view_index)
                        print(f"✅ View {view_index + 1} dock created")
                    else:
                        print("❌ Cannot create dock - _open_specific_cross_section_view not found")
                        return
                if view_index in self.app.section_docks:
                    dock = self.app.section_docks[view_index]
                
                    # Restore from minimized state
                    if dock.isMinimized():
                        dock.showNormal()
                
                    # Make visible if hidden
                    if not dock.isVisible():
                        dock.show()
                
                    # Bring to front and activate
                    dock.raise_()
                    dock.activateWindow()
                
                    print(f"✨ Auto-displayed Cross Section View {view_index + 1}")    
    
                # ---------------- PLOT (LOCAL POINTS) ----------------
                # ✅ CRITICAL FIX: Disable camera sync during initial rendering
                # This prevents the initial plot + zoom from triggering a sync cascade
                prev_syncing = getattr(self.app, '_syncing_camera', False)
                self.app._syncing_camera = True
    
                self._plot_section(
                    core_points_local,
                    buffer_points_local,
                    view=getattr(self.app, "cross_view_mode", "front")
                )
    
                # # ---------------- FORCE ZOOM TO CORE ----------------
                # # Fixes "view zoomed out/down" issue by ignoring buffer points for camera setup
                # try:
                #     vtk_widget = self._get_active_vtk()
                #     if vtk_widget and len(core_points_local) > 0:
                #         # 1. Calculate bounds of ONLY the core (user-selected) points
                #         xmin, ymin, zmin = core_points_local.min(axis=0)
                #         xmax, ymax, zmax = core_points_local.max(axis=0)

                #         # 2. Force 2D orthographic camera BEFORE ResetCamera
                #         # Cross section local coords: X=along, Y=across, Z=elevation
                #         # We look along the Y axis so we see X (along) vs Z (elevation)
                #         camera = vtk_widget.renderer.GetActiveCamera()
                #         camera.ParallelProjectionOn()
                #         xc = (xmin + xmax) / 2.0
                #         zc = (zmin + zmax) / 2.0
                #         y_dist = max(xmax - xmin, zmax - zmin) * 3.0 + 1.0
                #         camera.SetPosition(xc, -y_dist, zc)
                #         camera.SetFocalPoint(xc, 0.0, zc)
                #         camera.SetViewUp(0.0, 0.0, 1.0)

                #         # 3. Reset camera to fit the XZ data bounds (along vs elevation)
                #         bounds = [xmin, xmax, ymin, ymax, zmin, zmax]
                #         vtk_widget.renderer.ResetCamera(bounds)

                #         # 4. Zoom out slightly (5% margin) so points aren't touching edges
                #         camera.Zoom(0.95)

                #         vtk_widget.renderer.ResetCameraClippingRange()
                #         vtk_widget.render()
                #         print(f"   🔎 2D view: Zoomed to core bounds X=[{xmin:.2f}, {xmax:.2f}] Z=[{zmin:.2f}, {zmax:.2f}]")
                # except Exception as e:
                #     print(f"   ⚠️ Force zoom failed: {e}")

                # ---------------- FIT CAMERA ----------------
                try:
                    vtk_widget = self._get_active_vtk()
                    self._fit_camera_to_section_points(vtk_widget, core_points_local)
                except Exception as e:
                    print(f"   ⚠️ Force zoom failed: {e}")  ###
            
                # ✅ Re-enable camera sync BEFORE auto-apply
                # Auto-apply will handle its own sync prevention
                self.app._syncing_camera = prev_syncing
    
                # ════════════════════════════════════════════════════════════════════════════════════
                # ✅ AUTO-APPLY: Isolated palette to THIS VIEW ONLY (NOT main view)
                # ════════════════════════════════════════════════════════════════════════════════════
    
                try:
                    if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog is not None:
                        dialog = self.app.display_mode_dialog
                        target_slot = view_index + 1  # View 0 = slot 1, View 1 = slot 2, etc.
                    
                        if hasattr(dialog, 'view_palettes') and target_slot in dialog.view_palettes:
                            view_palette = dialog.view_palettes[target_slot]
                        
                            print(f" 📋 Using view_palettes[{target_slot}] for View {view_index + 1}")
                            print(f" 📊 Palette has {len(view_palette)} classes")
                        
                            # ✅ CRITICAL: Call ISOLATED apply (only affects THIS view, not main)
                            self._auto_apply_view_palette(view_index, view_palette)
                        
                            print(f" ✅ Auto-apply complete for View {view_index + 1}")
                        else:
                            print(f" ⚠️ No view-specific palette for slot {target_slot}")
                    else:
                        print(f" ⚠️ Display Mode dialog not open - skipping auto-apply")
                    
                except Exception as e:
                    print(f" ⚠️ Auto-apply failed: {e}")
                    import traceback
                    traceback.print_exc()
    
                finally:
                    print(f"{'='*60}\n")

                # ═══════════════════════════════════════════════════════════
                # FIX 3: View Context Invalidation — flush stale state
                # ═══════════════════════════════════════════════════════════
                try:
                    # Invalidate classify interactor coord cache for this view
                    if hasattr(self.app, 'classify_interactors'):
                        interactor = self.app.classify_interactors.get(view_index)
                        if interactor and hasattr(interactor, '_invalidate_coord_cache'):
                            interactor._invalidate_coord_cache()
                            print(f"   🔄 View {view_index + 1}: coord cache invalidated")

                    # Build unified actor for this cross-section view
                    if hasattr(self.app, '_refresh_single_section_view'):
                        self.app._refresh_single_section_view(view_index)
                        print(f"   ✅ View {view_index + 1}: unified actor built")
                    else:
                        # Fallback to sync if refresh not available
                        from gui.unified_actor_manager import sync_palette_to_gpu
                        slot_idx = view_index + 1
                        sync_palette_to_gpu(self.app, slot_idx)
                        print(f"   ⚡ View {view_index + 1}: GPU palette synced (slot {slot_idx})")
                except ImportError:
                    pass
                except Exception as e:
                    print(f"   ⚠️ View context invalidation failed: {e}")

    ##NEWWW
    def _fit_camera_to_section_points(self, vtk_widget, points, padding_fraction=0.18):
        if vtk_widget is None or points is None or len(points) == 0:
            return

        try:
            import numpy as np

            ren = vtk_widget.renderer
            cam = ren.GetActiveCamera()

            # ── 1. Axis mapping ──────────────────────────────────────────────
            # side  → displays X (col 0, along)  vs Z  — camera looks along -Y
            # front → displays Y (col 1, across) vs Z  — camera looks along -X
            view_mode = getattr(self.app, 'cross_view_mode', 'side')

            if view_mode == 'side':
                h_col   = 0          # X = along-section (0 → length)
                h_label = 'X'
            else:                    # front
                h_col   = 1          # Y = perpendicular (±half_width)
                h_label = 'Y'
                # front view camera looks along X, so we need the X midpoint
                x_mid = float((points[:, 0].min() + points[:, 0].max()) / 2.0)

            # ── 2. Window aspect ratio ───────────────────────────────────────
            try:
                win_w, win_h = vtk_widget.GetRenderWindow().GetSize()
            except Exception:
                win_w, win_h = 0, 0
            if win_w < 10 or win_h < 10:
                try:
                    win_w, win_h = vtk_widget.width(), vtk_widget.height()
                except Exception:
                    win_w, win_h = 900, 450
            if win_w < 10 or win_h < 10:
                win_w, win_h = 900, 450
            aspect = win_w / win_h

            # ── 3. Horizontal bounds ─────────────────────────────────────────
            h_min = float(np.percentile(points[:, h_col],  2))
            h_max = float(np.percentile(points[:, h_col], 98))

            # ── 4. Z bottom — remove underground noise ───────────────────────
            z_min = float(np.percentile(points[:, 2], 5))

            # ── 5. Z top — density-gap detection ────────────────────────────
            z_vals     = np.sort(points[:, 2])
            z_p95      = float(np.percentile(z_vals, 95))
            z_p99      = float(np.percentile(z_vals, 99))
            z_true_max = float(z_vals[-1])

            main_z_range = max(z_p95 - z_min, 0.5)
            gap_to_max   = z_true_max - z_p95

            if gap_to_max > main_z_range * 0.30:
                z_max = z_p99
                print(f"   🔍 Gap detected ({gap_to_max:.2f}m > 30% of {main_z_range:.2f}m) → z_top=p99={z_p99:.2f}")
            else:
                z_max = z_true_max
                print(f"   🔍 No gap → z_top=true_max={z_true_max:.2f}")

            # ── 6. Minimum range guard ───────────────────────────────────────
            h_range = max(h_max - h_min, 1.0)
            z_range = max(z_max - z_min, 1.0)

            # ── 7. Padding — 18% each side ───────────────────────────────────
            padded_h = h_range + 2.0 * h_range * padding_fraction
            padded_z = z_range + 2.0 * z_range * padding_fraction

            # ── 8. Display centre ────────────────────────────────────────────
            h_center = (h_min + h_max) / 2.0
            z_center = (z_min + z_max) / 2.0

            # ── 9. Aspect-correct parallel scale ─────────────────────────────
            scale_from_h = (padded_h / 2.0) / aspect
            scale_from_z =  padded_z / 2.0
            parallel_scale = max(scale_from_h, scale_from_z)
            parallel_scale = max(parallel_scale, max(h_range, z_range) * 0.20)

            # ── 10. Camera placement ─────────────────────────────────────────
            stand_off = max(padded_h, padded_z) * 10.0 + 100.0

            cam.ParallelProjectionOn()
            cam.SetViewUp(0.0, 0.0, 1.0)
            cam.SetParallelScale(parallel_scale)

            if view_mode == 'side':
                # Looking along -Y → sees X (horizontal) vs Z (vertical)
                cam.SetFocalPoint(h_center, 0.0,        z_center)
                cam.SetPosition( h_center, -stand_off,  z_center)
            else:
                # Looking along -X → sees Y (horizontal) vs Z (vertical)
                cam.SetFocalPoint(x_mid,            h_center, z_center)
                cam.SetPosition( x_mid - stand_off, h_center, z_center)

            ren.ResetCameraClippingRange()
            vtk_widget.render()

            print(
                f"   📷 Camera fit [{view_mode}]: "
                f"{h_label}[{h_min:.2f}~{h_max:.2f}] "
                f"Z[{z_min:.2f}~{z_max:.2f}] "
                f"scale={parallel_scale:.3f} aspect={aspect:.2f}"
            )

        except Exception as e:
            print(f"   ⚠️ _fit_camera_to_section_points failed: {e}")
            try:
                vtk_widget.reset_camera()
                vtk_widget.render()
            except Exception:
                pass  ##

    def _auto_apply_view_palette(self, view_index: int, view_palette: dict):
        """
        ✅ AUTO-APPLY palette to ONLY this specific view (NOT main view)
       
        - Gets view-specific palette from Display Mode dialog
        - Re-renders ONLY that cross-section view
        - Does NOT touch main view
       
        Args:
            view_index: 0-based view index (0=View 1, 1=View 2, etc.)
            view_palette: The view-specific palette dict from dialog
        """
       
        print(f"\n{'='*60}")
        print(f"🎨 AUTO-APPLY PALETTE TO VIEW {view_index + 1}")
        print(f"{'='*60}")
       
        try:
            # ✅ CRITICAL: Get the section data for THIS specific view
            core_points = getattr(self.app, f"section_{view_index}_core_points", None)
            buffer_points = getattr(self.app, f"section_{view_index}_buffer_points", None)
            core_mask = getattr(self.app, f"section_{view_index}_core_mask", None)
            buffer_mask = getattr(self.app, f"section_{view_index}_buffer_mask", None)
           
            if core_points is None or core_mask is None:
                print(f" ⚠️ No section data for View {view_index + 1}")
                print(f"{'='*60}\n")
                return
           
            # ✅ Get this view's VTK widget
            if view_index not in self.app.section_vtks:
                print(f" ⚠️ View {view_index + 1} not open")
                print(f"{'='*60}\n")
                return
           
            vtk_widget = self.app.section_vtks[view_index]
           
            # Get current classifications from MAIN data (not view-specific)
            current_classes = self.app.data.get("classification")
            if current_classes is None:
                print(f" ⚠️ No classification data")
                print(f"{'='*60}\n")
                return
           
            # ✅ Get VISIBLE classes from THIS VIEW's palette ONLY
            visible_classes = [c for c, info in view_palette.items() if info.get("show", True)]
           
            if not visible_classes:
                print(f" ⚠️ No visible classes in View {view_index + 1} palette")
                vtk_widget.clear()
                vtk_widget.render()
                print(f"{'='*60}\n")
                return
           
            print(f" 📋 Visible classes: {visible_classes}")
            print(f" 📊 View palette has {len(view_palette)} classes")
           
            # ✅ Re-render ONLY this view with the palette
            import numpy as np
            import pyvista as pv
           
            # Combine core + buffer
            if buffer_points is not None and buffer_mask is not None:
                all_points = np.vstack([core_points, buffer_points])
                all_classes = np.concatenate([
                    current_classes[core_mask],
                    current_classes[buffer_mask & ~core_mask]
                ])
            else:
                all_points = core_points
                all_classes = current_classes[core_mask]
           
            # Filter by visible classes
            visible_mask = np.isin(all_classes, visible_classes)
            filtered_points = all_points[visible_mask]
            filtered_classes = all_classes[visible_mask]
           
            print(f" 📊 Total points in section: {len(all_points)}:,")
            print(f" 📊 Visible points: {len(filtered_points)}:,")
           
            if len(filtered_points) == 0:
                print(f" ⚠️ No visible points after filtering")
                vtk_widget.clear()
                vtk_widget.render()
                print(f"{'='*60}\n")
                return
           
            # Save camera
            try:
                cam = vtk_widget.renderer.GetActiveCamera()
                cam_state = {
                    "pos": cam.GetPosition(),
                    "fp": cam.GetFocalPoint(),
                    "up": cam.GetViewUp(),
                    "ps": cam.GetParallelScale(),
                    "pp": cam.GetParallelProjection(),
                }
            except Exception:
                cam_state = None
           
            # ✅ CRITICAL: Disable camera sync during this render to prevent blinking cascade
            # When we re-render with new palette, we don't want it to trigger sync to other views
            prev_syncing = getattr(self.app, '_syncing_camera', False)
            self.app._syncing_camera = True

            # ✅ UNIFIED ACTOR: push palette change via GPU uniform — never rebuild actors
            try:
                from gui.unified_actor_manager import sync_palette_to_gpu, is_unified_actor_ready
                slot_idx = view_index + 1
                if is_unified_actor_ready(self.app) or \
                        f"_section_{view_index}_unified" in vtk_widget.actors:
                    border_pct = float(
                        (self.app.view_borders.get(view_index, 0) or 0.0)
                        if hasattr(self.app, "view_borders") else 0.0
                    )
                    sync_palette_to_gpu(self.app, slot_idx, view_palette, border_pct,
                                        render=False)
                    print(f"   ⚡ sync_palette_to_gpu fired for slot {slot_idx}")
                else:
                    # Unified actor not built yet — build it now
                    from gui.unified_actor_manager import build_section_unified_actor
                    build_section_unified_actor(
                        self.app, view_index,
                        view=getattr(self.app, 'cross_view_mode', 'front')
                    )
                    print(f"   🔨 Built unified section actor for View {view_index + 1}")
            except Exception as _ue:
                print(f"   ⚠️ Unified palette apply failed: {_ue}")
                import traceback
                traceback.print_exc()

            # ✅ Lock this view's palette so sync operations can't overwrite visibility
            if not hasattr(self.app, '_view_palette_locks'):
                self.app._view_palette_locks = {}
            self.app._view_palette_locks[view_index] = True

            self.app._syncing_camera = prev_syncing

            vtk_widget.render()
            print(f" 🔒 Palette locked for View {view_index + 1} (prevents sync overwrite)")
            print(f" ✅ View {view_index + 1} re-rendered via GPU uniform (ISOLATED)")
            print(f"{'='*60}\n")
           
        except Exception as e:
            print(f" ❌ Auto-apply failed: {e}")
            import traceback
            traceback.print_exc()
            print(f"{'='*60}\n")


    def refresh_colors(self):
        """
        ✅ UNIFIED ACTOR: Refresh cross-section view via fast_cross_section_update.
        Writes directly into _naksha_rgb_ptr — no per-class actor create/destroy.
        MicroStation equivalent: invalidate element display → single GPU redraw.
        """
        if self.active_view is None:
            print("⚠️ No active view to refresh")
            return

        view_idx = int(self.active_view)

        print(f"\n{'='*60}")
        print(f"🎨 REFRESHING COLORS (UNIFIED ACTOR): Cross-Section {view_idx + 1}")
        print(f"{'='*60}")

        vtk_widget = getattr(self.app, "section_vtks", {}).get(view_idx)
        if not vtk_widget:
            print(f"   ⚠️ No VTK widget for view {view_idx}")
            print(f"{'='*60}\n")
            return

        core_points = getattr(self.app, f"section_{view_idx}_core_points", None)
        core_mask   = getattr(self.app, f"section_{view_idx}_core_mask", None)
        if core_points is None or core_mask is None:
            print(f"   ⚠️ No section data for view {view_idx}")
            print(f"{'='*60}\n")
            return

        view_palette = self._get_view_palette(view_idx) or {}

        # ── UNIFIED ACTOR FAST PATH ──────────────────────────────────────
        try:
            from gui.unified_actor_manager import fast_cross_section_update
            changed_mask = getattr(self.app, '_last_changed_mask', None)
            fast_cross_section_update(self.app, view_idx, changed_mask,
                                      palette=view_palette)
            vtk_widget.render()
            print(f"   ✅ Unified fast update complete — View {view_idx + 1}")
            print(f"{'='*60}\n")
            return
        except Exception as e:
            print(f"   ⚠️ Unified fast path failed, using build fallback: {e}")

        # ── FALLBACK: unified actor not yet built — trigger build ────────
        try:
            from gui.unified_actor_manager import build_section_unified_actor
            border_pct = float(
                (self.app.view_borders.get(view_idx, 0) or 0.0)
                if hasattr(self.app, "view_borders") else 0.0
            )
            build_section_unified_actor(self.app, view_idx,
                                        view=getattr(self.app, 'cross_view_mode', 'front'))
            vtk_widget.render()
            print(f"   ✅ Unified actor built — View {view_idx + 1}")
        except Exception as e2:
            print(f"   ❌ Unified build fallback also failed: {e2}")
            import traceback
            traceback.print_exc()

        print(f"{'='*60}\n")



###################################################################################################################

    def refresh_colors_direct(self):
        """
        ✅ FIXED: Delegates to the unified actor refresh in app_window.py.
        """
        if not hasattr(self, "active_view") or self.active_view is None:
            print("⚠️ No active view to refresh")
            return

        view_idx = int(self.active_view)

        print(f"\n{'='*60}")
        print(f"🎨 DIRECT REFRESH (UNIFIED ACTOR): Cross-Section View {view_idx + 1}")
        print(f"{'='*60}")
        
        try:
            if hasattr(self.app, "_refresh_single_section_view"):
                # Use the new unified path in app_window.py
                self.app._refresh_single_section_view(view_idx)
            else:
                print(f"   ⚠️ _refresh_single_section_view not found!")
        except Exception as e:
            print(f"   ❌ Direct refresh failed: {e}")
            import traceback
            traceback.print_exc()
            print(f"{'='*60}\n")



    def _refresh_cut_section_if_active(self):
        """
        ✅ UNIFIED: Delegate to CutSectionController._refresh_cut_colors_fast().
        That method does a direct VTK pointer write — no actor destroy/create.
        """
        try:
            if not hasattr(self.app, 'cut_section_controller'):
                return
            cut_ctrl = self.app.cut_section_controller
            if not getattr(cut_ctrl, 'is_cut_view_active', False):
                return
            if cut_ctrl.cut_points is None or cut_ctrl._cut_index_map is None:
                return

            print(f"\n{'='*60}")
            print(f"🔄 AUTO-REFRESHING CUT SECTION (fast path)")
            print(f"{'='*60}")

            cut_ctrl._refresh_cut_colors_fast()

            print(f"   ✅ Cut section refreshed")
            print(f"{'='*60}\n")

        except Exception as e:
            print(f"❌ Failed to refresh cut section: {e}")
            import traceback
            traceback.print_exc()

    def _show_refresh_indicator(self):
        """
        Show a subtle indicator that auto-refresh happened.
        Makes the user aware their changes were applied.
        """
        if hasattr(self.app, 'statusBar'):
            active_view = getattr(self.app.section_controller, 'active_view', 0)
            self.app.statusBar().showMessage(
                f"✨ View {active_view + 1} updated", 
                1500  # Short duration - not intrusive
            )


        # ============================================
        # DIAGNOSTIC METHOD - Add this for debugging
        # ============================================

    def diagnose_view_state(self):
            """
            Diagnostic method to check which view is being updated.
            Call this before refresh to verify target view.
            """
            print(f"\n{'='*60}")
            print(f"🔍 SECTION CONTROLLER DIAGNOSTICS")
            print(f"{'='*60}")
            print(f"   active_view: {getattr(self, 'active_view', 'NOT SET')}")
            print(f"   Available section views: {list(getattr(self.app, 'section_vtks', {}).keys())}")
            print(f"   Main view display mode: {getattr(self.app, 'display_mode', 'UNKNOWN')}")
            
            if hasattr(self.app, 'class_palette'):
                visible = [c for c, i in self.app.class_palette.items() if i.get('show', False)]
                print(f"   Visible classes in palette: {visible}")
            
            print(f"{'='*60}\n")

    def _make_colors(self, points, classes=None):
        """
        ✅ UNIFIED: Assign colors using vectorized LUT (no per-class Python loop).
        Matches unified_actor_manager.ColorLUT.map_classes() for consistency.
        """
        mode = self.app.display_mode
        colors = np.full((points.shape[0], 3), 200, dtype=np.uint8)

        if mode == "rgb" and self.app.data.get("rgb") is not None:
            global_rgb = (self.app.data["rgb"] * 255).astype(np.uint8)
            n = min(points.shape[0], global_rgb.shape[0])
            colors[:n] = global_rgb[:n]

        elif mode == "intensity" and self.app.data.get("intensity") is not None:
            intens = self.app.data["intensity"][:points.shape[0]].astype(float)
            norm = (intens - intens.min()) / (intens.max() - intens.min() + 1e-6)
            colors = np.c_[norm * 255, norm * 255, norm * 255].astype(np.uint8)

        elif mode == "elevation":
            z = points[:, 2]
            norm = (z - z.min()) / (z.max() - z.min() + 1e-6)
            colors = np.c_[norm * 255, norm * 255, (1 - norm) * 255].astype(np.uint8)

        elif mode in ("class", "shaded_class") and classes is not None:
            # ✅ VECTORIZED: Build LUT once, apply to all points in one numpy op
            palette = getattr(self.app, 'class_palette', {})
            max_c = max(int(classes.max()) + 1, 256) if len(classes) > 0 else 256
            lut = np.full((max_c, 3), 128, dtype=np.uint8)
            for code, info in palette.items():
                idx = int(code)
                if 0 <= idx < max_c:
                    if info.get("show", True):
                        lut[idx] = info.get("color", (200, 200, 200))
                    else:
                        lut[idx] = (0, 0, 0)
            colors = lut[classes.clip(0, max_c - 1).astype(np.intp)]

        return colors



    def _plot_section(self, core_points, buffer_points, view="side"):
        """
        Unified implementation. Persistent actor — no rebuild on re-slice.
        """
        view_idx   = self.active_view
        actor_name = f"_section_{view_idx}_unified"
        vtk_widget = self.app.section_vtks[view_idx]

        # ── FAST PATH: actor exists → geometry already in GPU, just re-colour ──
        if actor_name in vtk_widget.actors:
            from gui.unified_actor_manager import fast_cross_section_update
            fast_cross_section_update(self.app, view_idx, changed_mask_global=None)
            vtk_widget.render()
            return

        # ── COLD PATH: first slice of this view → build once ──────────────────
        # Remove any legacy class_ actors from old mode before building
        for name in list(vtk_widget.actors.keys()):
            if name.startswith("class_") or name.startswith("section_core_") \
                    or name.startswith("section_buffer_"):
                try:
                    vtk_widget.remove_actor(name, render=False)
                except Exception:
                    pass

        from gui.unified_actor_manager import build_section_unified_actor
        build_section_unified_actor(self.app, view_idx, view=view)  ###

    # Other methods remain unchanged...

    # ---------------- DOCK ---------------

    def _init_dock(self):
        self.app.section_frame = QWidget()
        sec_layout = QVBoxLayout()
   
        # --- Buttons row ---
        btn_row = QHBoxLayout()
        self.side_btn = QPushButton("Side View")
        self.front_btn = QPushButton("Front View")
        for b in (self.side_btn, self.front_btn):
            b.setCheckable(True)
            btn_row.addWidget(b)
        sec_layout.addLayout(btn_row)

        self.front_btn.setChecked(True)
        self.side_btn.setChecked(False)

   
        # --- Buffer depth control (UPDATED LABEL) ---
        buffer_row = QHBoxLayout()
        buffer_row.addWidget(QLabel("Buffer Depth:"))  # ✅ Changed from "Width"
        self.buffer_spin = QSpinBox()
        self.buffer_spin.setRange(0, 50)   # allow 0–50 m
        self.buffer_spin.setValue(getattr(self.app, "section_buffer", 2))
        self.buffer_spin.setSuffix(" m")
        # ✅ Add tooltip explaining MicroStation behavior
        self.buffer_spin.setToolTip(
            "Extends section LENGTH (along the line) for context.\n"
            "Does NOT affect cross-section width.\n\n"
            "Width is determined only by your perpendicular drag."
        )
        buffer_row.addWidget(self.buffer_spin)
        sec_layout.addLayout(buffer_row)
   
        # --- Viewer ---
        self.app.sec_vtk = QtInteractor(self.app.section_frame)
        from gui.theme_manager import ThemeManager
        bg_color = "white" if ThemeManager.current() == "light" else "black"
        self.app.sec_vtk.set_background(bg_color)
        sec_layout.addWidget(self.app.sec_vtk.interactor)
   
        # ✅ Install shortcut filter here (now sec_vtk exists)
        if hasattr(self.app, "_shortcut_filter"):
            self.app.sec_vtk.interactor.installEventFilter(self.app._shortcut_filter)
   
        self.app.section_frame.setLayout(sec_layout)
        self.app.section_dock = QDockWidget("Cross Section", self.app)
        self.app.section_dock.setWidget(self.app.section_frame)
        self.app.addDockWidget(Qt.RightDockWidgetArea, self.app.section_dock)
   
        # ✅ Install global shortcut filter here too
        self.app.sec_vtk.interactor.installEventFilter(self.app._shortcut_filter)
   
        self.app.section_frame.setLayout(sec_layout)
        self.app.section_dock = QDockWidget("Cross Section", self.app)
        self.app.section_dock.setWidget(self.app.section_frame)
        self.app.addDockWidget(Qt.RightDockWidgetArea, self.app.section_dock)
   
        # Connect buttons
        # ✅ FIXED: Connect buttons to trigger refresh on view mode change
        self.side_btn.clicked.connect(lambda: self.set_cross_view_mode("side"))
        self.front_btn.clicked.connect(lambda: self.set_cross_view_mode("front"))
   
        # Connect buffer spin
        self.buffer_spin.valueChanged.connect(self._update_buffer)
   
        # self.app.cross_view_mode = "side"
        #Added by bala for view
        self.app.cross_view_mode = "front"


    def _update_buffer(self, val):
        """Triggered when spinbox changes."""
        self.app.section_buffer = val
        print(f"🔄 Buffer width set to {val} m")

        # Recompute section if a slice is active
        if self.P1 is not None and self.P2 is not None:
            self.finalize_section(self.P1, self.P2)

    def _plot_cut_section(self, cut_points):
        """Display perpendicular cut slice inside the same Cross Section dock,
        with full classification, color, and refresh support identical to normal section view."""
        if cut_points is None or len(cut_points) == 0:
            print("⚠️ No points to plot in cut section")
            return

        print("🔄 Rendering CUT section with TerraScan classification colors...")

        # --- Save state ---
        self.app.section_cut_points = cut_points
        self.app.cross_view_mode = "cut"

        # Remove previous actors
        if hasattr(self, "_cut_actor") and self._cut_actor is not None:
            self.app.sec_vtk.remove_actor(self._cut_actor, reset_camera=False)
            self._cut_actor = None

        # --- Compute accurate mask based on geometry (nearest match to source) ---
        try:
            all_xyz = self.app.data["xyz"]
            # Find nearest neighbors of cut_points in the main cloud
            from scipy.spatial import cKDTree
            tree = cKDTree(all_xyz)
            _, idx = tree.query(cut_points, k=1)
            cut_classes = self.app.data["classification"][idx]
            cut_colors = self._make_colors(cut_points, cut_classes)
        except Exception as e:
            print(f"⚠️ Failed to compute color mapping for cut-section: {e}")
            cut_colors = np.full((cut_points.shape[0], 3), 200, dtype=np.uint8)

        # --- Create and render the point cloud ---
        import pyvista as pv
        cloud = pv.PolyData(cut_points)
        cloud["RGB"] = cut_colors
        self._cut_actor = self.app.sec_vtk.add_points(
            cloud, scalars="RGB", rgb=True, point_size=3
        )

        # ✅ Register cut section state for classification
        try:
            # self.app.cut_section_active = True
            self.app.section_cut_points = cut_points
            all_xyz = self.app.data["xyz"]
            # If KDTree query succeeded earlier, `idx` holds nearest-neighbour indices for cut_points.
            # Create a boolean mask marking those indices and store the indices for color lookups.
            if 'idx' in locals():
                cut_mask = np.zeros(len(all_xyz), dtype=bool)
                cut_mask[idx] = True
                self.app.cut_section_mask = cut_mask
                self.app.section_indices = idx
            else:
                # Fallback: no match indices available
                self.app.cut_section_mask = np.zeros(len(all_xyz), dtype=bool)
                self.app.section_indices = None
            print("🟢 Cut Section state registered for classification tools.")
        except Exception as e:
            print(f"⚠️ Could not register cut section state: {e}")

        # --- Camera setup (~80° rotated perpendicular view) ---
        cam = self.app.sec_vtk.renderer.GetActiveCamera()
        cam.ParallelProjectionOn()
        # self.app.sec_vtk.view_yz()
        # cam.Azimuth(80)
        # self.app.sec_vtk.renderer.ResetCamera()
        self.app.sec_vtk.render()

        # --- Reattach classification interactor ---
        from .interactor_classify import ClassificationInteractor
        iren = self.app.sec_vtk.interactor

        # ✅ Disable camera rotations in cut-section mode
        try:
            style = vtk.vtkInteractorStyleRubberBand2D()
  # completely user-driven style
            iren.SetInteractorStyle(style)
            print("🧭 Camera rotation/panning disabled for Cut Section view.")
        except Exception as e:
            print(f"⚠️ Failed to disable default interactor style: {e}")

        # ✅ Attach classification interactor for 2D interaction
        self.app.cut_section_active = True  
        self.is_locked = True
        wrapper = ClassificationInteractor(self.app, iren, mode="2d")
        iren.SetInteractorStyle(wrapper.style)
        self.app.classify_interactor = wrapper
        wrapper.is_cut_section_mode = True
        print("🟣 ClassificationInteractor attached (cut-section mode, locked to 2D).")

        # # --- Refresh colors support ---
        # try:
        #     self.last_mask = np.ones(len(self.app.data["xyz"]), dtype=bool)
        #     self.app.section_points = cut_points
        #     self.app.section_controller.refresh_colors()
        # except Exception as e:
        #     print(f"⚠️ refresh_colors() failed in cut mode: {e}")

        # --- Handle shaded class / DSM modes ---
        if getattr(self.app, "display_mode", "") == "shaded_class":
            try:
                from ..pointcloud_display import update_pointcloud
                update_pointcloud(self.app, "shaded_class")
                print("✅ Shaded mode updated in Cut Section.")
            except Exception as e:
                print(f"⚠️ Shaded update failed: {e}")

        print("✅ Cut Section rendered with true classification colors.")

    # ------------------------------------------------------------------
    # ✅ Overlay indicator for Cut View
    # ------------------------------------------------------------------
    def show_cut_overlay(self):
        """Show 'CUT VIEW ACTIVE' overlay on the cross-section dock."""
        try:
            if not hasattr(self.app, "sec_vtk") or self.app.sec_vtk is None:
                return

            from PySide6.QtWidgets import QLabel
            from PySide6.QtGui import QFont

            label = QLabel("✂ CUT VIEW ACTIVE", self.app.sec_vtk.interactor)
            label.setStyleSheet("""
                QLabel {
                    background-color: rgba(0, 0, 0, 120);
                    color: rgb(255, 85, 85);
                    border: 1px solid rgba(255, 85, 85, 180);
                    border-radius: 5px;
                    padding: 3px 10px;
                }
            """)
            label.setFont(QFont("Segoe UI", 10, QFont.Bold))
            label.adjustSize()
            label.move(15, 15)
            label.show()
            label.raise_()
            self.cut_overlay_label = label
            print("🟢 Overlay shown: CUT VIEW ACTIVE")
        except Exception as e:
            print(f"⚠️ show_cut_overlay failed: {e}")


    def hide_cut_overlay(self):
        """Hide overlay label if visible."""
        try:
            if hasattr(self, "cut_overlay_label") and self.cut_overlay_label:
                self.cut_overlay_label.hide()
                self.cut_overlay_label.deleteLater()
                self.cut_overlay_label = None
                print("🔵 Overlay hidden.")
        except Exception as e:
            print(f"⚠️ hide_cut_overlay failed: {e}")

            # New functions for multi-view support
    def refresh_colors_for_view(self, view_index, palette=None):
        """
        🚀 MILLISECOND REFRESH: Updates GPU buffers for cross-sections.
        Eliminates the 3-4 second lag by avoiding actor re-creation.
        """
        if hasattr(self.app, 'cut_section_controller') and getattr(self.app.cut_section_controller, 'is_locked', False):
            return

        try:
            import numpy as np
            from vtkmodules.util import numpy_support

            # 1. Validation
            if not hasattr(self, 'view_vtks') or view_index not in self.view_vtks:
                return
            
            # 2. Identify the Actor
            # We look for the actor we created during the first _plot_section call
            actor_name = f"section_buffer_{view_index}"
            vtk_widget = self.view_vtks[view_index]
            
            actor = vtk_widget.actors.get(actor_name)
            
            # 🛑 FALLBACK: If actor doesn't exist yet, do a full plot once
            if actor is None or not hasattr(self, 'view_indices') or view_index not in self.view_indices:
                print(f"🔄 Initializing full plot for view {view_index}...")
                old_active = self.active_view
                self.active_view = view_index
                self.current_vtk = vtk_widget
                self._plot_section(
                    self.app.section_core_points,
                    self.app.section_buffer_points,
                    view=getattr(self, 'current_section_view', 'side')
                )
                self.active_view = old_active
                return

            # 3. 🚀 THE FAST PATH (Direct GPU update)
            # Get the point indices that belong to THIS specific cross-section view
            indices = self.view_indices.get(view_index)
            if indices is None: return

            # Get the classification data for these specific points
            classes = self.app.data["classification"][indices]
            
            # Use provided palette or fall back to app default
            active_palette = palette or getattr(self.app, 'class_palette', {})

            # Access the VTK Color Buffer
            _m = actor.GetMapper()
            polydata = _m.GetInput() if _m else None
            vtk_colors = polydata.GetPointData().GetScalars() if polydata else None
            
            if vtk_colors:
                # Create a local Lookup Table for speed
                max_c = int(classes.max()) if classes.size > 0 else 0
                lut = np.zeros((max_c + 1, 3), dtype=np.uint8)
                
                for code, info in active_palette.items():
                    if code <= max_c:
                        # If hidden, we paint it black (0,0,0) or background color
                        lut[code] = info['color'] if info.get('show', True) else (0, 0, 0)

                # Vectorized mapping: Millions of points mapped in ~5-10ms
                new_rgb = lut[classes.astype(int)]
                
                # Zero-copy pointer access to GPU memory
                vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                np.copyto(vtk_ptr, new_rgb)
                
                # Notify VTK that data has changed so it re-renders
                vtk_colors.Modified()
                vtk_widget.render()
                
                print(f"🚀 Fast Sync: Section View {view_index+1} updated via GPU buffer")

        except Exception as e:
            print(f"⚠️ Fast refresh failed for view {view_index}: {e}")
            # Final safety fallback: run the original slow refresh
            self._plot_section(self.app.section_core_points, self.app.section_buffer_points)

    def refresh_colors_with_filter(self, view_index):
        """
        Refresh colors for a specific cross-section view with visibility filtering.
        Only shows points from classes that are checked in Display Mode.
        """
        try:
            if not hasattr(self, 'view_vtks') or view_index not in self.view_vtks:
                print(f"⚠️ View {view_index} not found")
                return
            
            vtk_widget = self.view_vtks[view_index]
            
            if not hasattr(self.app, 'section_core_points') or self.app.section_core_points is None:
                print(f"⚠️ No section data available")
                return
            
            # Get visibility filter (list of visible class codes)
            visible_classes = getattr(self, 'view_visibility_filter', None)
            
            # Clear the view
            vtk_widget.clear()
            
            # Get section data
            core_pts = self.app.section_core_points
            buffer_pts = self.app.section_buffer_points if hasattr(self.app, 'section_buffer_points') else None
            
            # ✅ Apply visibility filter if specified
            if visible_classes is not None and len(visible_classes) > 0:
                print(f"   🔍 Filtering to show only classes: {visible_classes}")
                
                # Get classifications for section points
                if hasattr(self.app, 'section_indices') and self.app.section_indices is not None:
                    section_classes = self.app.data['classification'][self.app.section_indices]
                    
                    # Create mask for visible classes
                    mask = np.isin(section_classes, visible_classes)
                    
                    # Filter core points
                    if core_pts is not None and len(core_pts) > 0:
                        core_mask = mask[:len(core_pts)]
                        core_pts = core_pts[core_mask]
                    
                    # Filter buffer points
                    if buffer_pts is not None and len(buffer_pts) > 0:
                        buffer_mask = mask[len(core_pts):] if len(mask) > len(core_pts) else np.zeros(len(buffer_pts), dtype=bool)
                        buffer_pts = buffer_pts[buffer_mask] if np.any(buffer_mask) else None
                    
                    print(f"   ✅ Filtered: {len(core_pts)} core points, {len(buffer_pts) if buffer_pts is not None else 0} buffer points")
            
            # Re-plot with filtered data
            if core_pts is not None and len(core_pts) > 0:
                self._plot_section_filtered(core_pts, buffer_pts, view_index)
            else:
                print(f"   ⚠️ No points to display after filtering")
            
        except Exception as e:
            print(f"⚠️ Error refreshing filtered view: {e}")
            import traceback
            traceback.print_exc()

    def _plot_section_filtered(self, core_pts, buffer_pts, view_index):
        """
        Plot section with filtered points and proper coloring.
        """
        try:
            vtk_widget = self.view_vtks[view_index]
            
            # Determine view orientation
            current_view = getattr(self, 'current_section_view', 'side')
            
            # Get button states to determine view
            if hasattr(self.app, 'section_view_buttons') and view_index in self.app.section_view_buttons:
                buttons = self.app.section_view_buttons[view_index]
                if buttons['side'].isChecked():
                    current_view = 'side'
                elif buttons['front'].isChecked():
                    current_view = 'front'
            
            # Transform points based on view
            if current_view == 'side':
                # Side view: X-Z (distance along section vs elevation)
                if core_pts is not None and len(core_pts) > 0:
                    display_pts = np.column_stack([core_pts[:, 0], core_pts[:, 2]])
                buffer_display = None
                if buffer_pts is not None and len(buffer_pts) > 0:
                    buffer_display = np.column_stack([buffer_pts[:, 0], buffer_pts[:, 2]])
            else:
                # Front view: Y-Z (perpendicular distance vs elevation)
                if core_pts is not None and len(core_pts) > 0:
                    display_pts = np.column_stack([core_pts[:, 1], core_pts[:, 2]])
                buffer_display = None
                if buffer_pts is not None and len(buffer_pts) > 0:
                    buffer_display = np.column_stack([buffer_pts[:, 1], buffer_pts[:, 2]])
            
            # Add Z coordinate (zero for 2D)
            if len(display_pts) > 0:
                display_pts = np.column_stack([display_pts, np.zeros(len(display_pts))])
            if buffer_display is not None and len(buffer_display) > 0:
                buffer_display = np.column_stack([buffer_display, np.zeros(len(buffer_display))])
            
            # Get colors based on current display mode
            colors = self._get_section_colors(core_pts, buffer_pts)
            
            # Plot core points
            if len(display_pts) > 0:
                import pyvista as pv
                cloud = pv.PolyData(display_pts)
                
                if colors is not None and len(colors) == len(display_pts):
                    vtk_widget.add_points(
                        cloud,
                        scalars=colors[:len(display_pts)],
                        rgb=True,
                        point_size=3,
                        render_points_as_spheres=True
                    )
                else:
                    vtk_widget.add_points(
                        cloud,
                        color='white',
                        point_size=3,
                        render_points_as_spheres=True
                    )
            
            # Plot buffer points (if any)
            if buffer_display is not None and len(buffer_display) > 0:
                buffer_cloud = pv.PolyData(buffer_display)
                buffer_colors = colors[len(display_pts):] if colors is not None and len(colors) > len(display_pts) else None
                
                if buffer_colors is not None:
                    vtk_widget.add_points(
                        buffer_cloud,
                        scalars=buffer_colors,
                        rgb=True,
                        point_size=2,
                        opacity=1.0,
                        render_points_as_spheres=True
                    )
                else:
                    vtk_widget.add_points(
                        buffer_cloud,
                        color='gray',
                        point_size=2,
                        opacity=1.0,
                        render_points_as_spheres=True
                    )
            
            # Reset camera and render
            vtk_widget.reset_camera()
            vtk_widget.render()
            
            print(f"✅ Plotted filtered section: {len(display_pts)} points")
            
        except Exception as e:
            print(f"⚠️ Error plotting filtered section: {e}")
            import traceback
            traceback.print_exc()


    def _get_section_colors(self, core_pts, buffer_pts):
        """
        Get colors for section points based on current display mode.
        """
        try:
            if not hasattr(self.app, 'section_indices') or self.app.section_indices is None:
                return None
            
            indices = self.app.section_indices
            
            # Get colors based on display mode
            if self.app.display_mode == "class":
                # Classification colors
                classes = self.app.data['classification'][indices]
                colors = np.zeros((len(classes), 3), dtype=np.uint8)
                
                for code, info in self.app.class_palette.items():
                    mask = (classes == code)
                    if np.any(mask):
                        colors[mask] = info['color']
                
                return colors
                
            elif self.app.display_mode == "rgb" and 'rgb' in self.app.data:
                # Original RGB colors
                return self.app.data['rgb'][indices]
                
            elif self.app.display_mode == "intensity" and 'intensity' in self.app.data:
                # Intensity grayscale
                intensity = self.app.data['intensity'][indices]
                intensity_norm = ((intensity - intensity.min()) / (intensity.max() - intensity.min()) * 255).astype(np.uint8)
                return np.column_stack([intensity_norm] * 3)
                
            elif self.app.display_mode == "elevation":
                # Elevation color ramp
                z_vals = self.app.data['xyz'][indices, 2]
                z_norm = (z_vals - z_vals.min()) / (z_vals.max() - z_vals.min())
                
                # Create color ramp (blue -> green -> yellow -> red)
                colors = np.zeros((len(z_norm), 3), dtype=np.uint8)
                colors[:, 0] = (z_norm * 255).astype(np.uint8)  # Red
                colors[:, 1] = ((1 - np.abs(z_norm - 0.5) * 2) * 255).astype(np.uint8)  # Green
                colors[:, 2] = ((1 - z_norm) * 255).astype(np.uint8)  # Blue
                
                return colors
            
            return None
            
        except Exception as e:
            print(f"⚠️ Error getting section colors: {e}")
            return None
        

    def refresh_colors_isolated(self, view_index=None):
        """
        ✅ UNIFIED ACTOR: Refresh ONLY the specified cross-section view.
        Routes to fast_cross_section_update — no actor destroy/create.
        """
        if hasattr(self.app, 'cut_section_controller'):
            if getattr(self.app.cut_section_controller, 'is_locked', False):
                print("🔒 Cut section locked → BLOCKING cross-section refresh")
                return

        if view_index is None:
            view_index = self.active_view

        if view_index is None or view_index not in self.app.section_vtks:
            print("⚠️ No valid view to refresh")
            return

        print(f"🔄 Isolated refresh (unified): View {view_index + 1}")

        try:
            from gui.unified_actor_manager import fast_cross_section_update
            view_palette = self._get_view_palette(view_index) or {}
            changed_mask = getattr(self.app, '_last_changed_mask', None)
            fast_cross_section_update(self.app, view_index, changed_mask,
                                      palette=view_palette)
            vtk_widget = self.app.section_vtks[view_index]
            vtk_widget.render()
            print(f"✅ View {view_index + 1} isolated refresh complete")
        except Exception as e:
            print(f"⚠️ Isolated refresh failed: {e}")
            import traceback
            traceback.print_exc()


    
    def _refresh_all_section_colors(self, app=None):
            """
            Refresh colors in ALL open cross-section views.
            UNIFIED: Uses fast_cross_section_update for GPU-direct refresh.
            """
            app = app or self.app

            # Block refresh if cut section is locked
            if hasattr(app, 'cut_section_controller') and getattr(app.cut_section_controller, 'is_locked', False):
                print("Cut section locked: blocking _refresh_all_section_colors")
                return

            if not hasattr(app, "section_vtks") or not app.section_vtks:
                return

            try:
                from gui.unified_actor_manager import fast_cross_section_update
                changed_mask = getattr(app, '_last_changed_mask', None)

                for view_idx in sorted(app.section_vtks.keys()):
                    try:
                        fast_cross_section_update(app, view_idx, changed_mask)
                    except Exception as e:
                        print(f"Section {view_idx + 1} unified refresh failed: {e}")
            except ImportError:
                prev_active = getattr(self, "active_view", None)
                try:
                    for view_idx in sorted(app.section_vtks.keys()):
                        try:
                            self.active_view = view_idx
                            self.refresh_colors()
                        except Exception as e:
                            print(f"Fallback refresh View {view_idx + 1}: {e}")
                finally:
                    if prev_active is not None:
                        self.active_view = prev_active

    def refresh_cut_section_colors(self):
        """
        Refresh colors in the cut section view after classification changes.
        ✅ ISOLATED: Does NOT trigger cross-section or main view updates.
        """
        # Check if cut section is active
        if not hasattr(self.app, 'section_cut_points') or self.app.section_cut_points is None:
            print("⚠️ No active cut section to refresh")
            return
        
        if not hasattr(self.app, 'sec_vtk'):
            print("⚠️ No VTK widget for cut section")
            return
        
        print(f"\n{'='*60}")
        print(f"🔄 REFRESHING CUT SECTION COLORS")
        print(f"{'='*60}")
        
        try:
            import numpy as np
            import pyvista as pv
            from scipy.spatial import cKDTree
            
            cut_points = self.app.section_cut_points
            all_xyz = self.app.data["xyz"]
            
            # Find nearest neighbors to get current classifications
            tree = cKDTree(all_xyz)
            _, idx = tree.query(cut_points, k=1)
            
            # Get CURRENT classifications (after modification)
            current_classes = self.app.data["classification"][idx]
            
            # Get visible classes from palette
            if hasattr(self.app, 'class_palette') and self.app.class_palette:
                visible_classes = [code for code, info in self.app.class_palette.items() if info.get("show", False)]
                
                # If no classes selected, show all
                if len(visible_classes) == 0:
                    visible_classes = list(np.unique(current_classes))
            else:
                visible_classes = list(np.unique(current_classes))
            
            print(f"   📋 Visible classes: {visible_classes}")
            
            # Filter by visible classes
            visible_mask = np.isin(current_classes, visible_classes)
            filtered_points = cut_points[visible_mask]
            filtered_classes = current_classes[visible_mask]
            
            if len(filtered_points) == 0:
                print(f"   ⚠️ No visible points after filtering")
                self.app.sec_vtk.clear()
                self.app.sec_vtk.render()
                print(f"{'='*60}\n")
                return
            
            print(f"   📊 Total: {len(cut_points)} → Visible: {len(filtered_points)}")
            
            # ✅ VECTORIZED: Calculate colors using LUT (no per-point Python loop)
            palette = getattr(self.app, 'class_palette', {})
            if palette:
                max_c = max(int(filtered_classes.max()) + 1, 256) if len(filtered_classes) > 0 else 256
                lut = np.full((max_c, 3), 128, dtype=np.uint8)
                for code, info in palette.items():
                    idx = int(code)
                    if 0 <= idx < max_c:
                        lut[idx] = info.get("color", (128, 128, 128))
                colors = lut[filtered_classes.clip(0, max_c - 1).astype(np.intp)]
            else:
                # Default color scheme
                default_palette = np.array([
                    [160, 160, 160], [255, 255, 255], [150, 100, 50],
                    [0, 255, 0], [0, 200, 0], [0, 150, 0],
                    [255, 0, 0], [0, 0, 255], [255, 255, 0],
                ], dtype=np.uint8)
                colors = default_palette[filtered_classes % len(default_palette)]
            
            # Debug color distribution
            unique = np.unique(filtered_classes)
            print(f"   🎨 Classes in view: {unique}")
            for cls in unique:
                count = np.sum(filtered_classes == cls)
                color = self.app.class_palette.get(int(cls), {}).get("color", (128, 128, 128)) if hasattr(self.app, 'class_palette') else (128, 128, 128)
                print(f"      Class {cls}: {count} pts, RGB={color}")
            
            # Save camera position
            camera_pos = self.app.sec_vtk.camera_position
            
            # Clear and redraw
            self.app.sec_vtk.clear()
            
            cloud = pv.PolyData(filtered_points)
            cloud["RGB"] = colors
            
            self.app.sec_vtk.add_points(
                cloud,
                scalars="RGB",
                rgb=True,
                point_size=3.0,
                render_points_as_spheres=True,
                name="cut_section_points"
            )
            
            # Restore camera
            self.app.sec_vtk.camera_position = camera_pos
            self.app.sec_vtk.render()
            
            print(f"   ✅ Cut section refreshed with {len(filtered_points)} points")
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"❌ Failed to refresh cut section: {e}")
            import traceback
            traceback.print_exc()
            print(f"{'='*60}\n")

    def deactivate_for_measurement(self):
        """
        Temporarily deactivate cross-section when measurement tool starts.
        """
        print("🔄 Deactivating cross-section for measurement tool")
        
        # Reset drawing state
        self.P1 = None
        self.P2 = None
        self.half_width = None
        
        # Remove rubber band
        if self.rubber_actor:
            try:
                self.app.vtk_widget.renderer.RemoveActor(self.rubber_actor)
            except Exception:
                pass
            self.rubber_actor = None
        
        self.app.vtk_widget.render()


    def _should_block_for_measurement(self):
        """
        Check if measurement tool is active and should take priority.
        Returns True if cross-section should be blocked.
        """
        if not hasattr(self.app, 'digitizer') or not self.app.digitizer:
            return False
        
        if not hasattr(self.app.digitizer, 'measurement_tool') or not self.app.digitizer.measurement_tool:
            return False
        
        # Check if measurement tool is actively measuring
        measurement_tool = self.app.digitizer.measurement_tool
        
        # If measurement is in drawing mode, block cross-section
        if getattr(measurement_tool, 'is_measuring', False):
            return True
        
        # If measurement has started collecting points, block
        if hasattr(measurement_tool, 'measurement_points') and len(measurement_tool.measurement_points) > 0:
            return True
        

    def update_section_colors_partial(self, changed_indices):
        """
        Update only the colors of the points whose classification changed.
        No full refresh, no actor rebuild.
        """
        vtk_widget = self._get_active_vtk()
        if vtk_widget is None:
            return

        # Actor exists?
        actor = getattr(self, "_core_actor", None)
        if actor is None:
            print("⚠️ No core actor found (cannot partial-refresh)")
            return

        # Get VTK polydata from actor
        mapper = actor.GetMapper()
        poly = mapper.GetInput()

        if poly is None:
            print("⚠️ No polydata available")
            return

        rgb_array = poly.GetPointData().GetArray("RGB")
        if rgb_array is None:
            print("⚠️ No RGB array found")
            return

        # Current palette
        palette = self._get_view_palette(self.active_view)

        # Update only modified points
        cls = self.app.data["classification"]

        for idx in changed_indices:
            if idx >= len(self.app.section_core_mask):
                continue

            if not self.app.section_core_mask[idx]:
                continue

            # VTK index in core actor
            vtk_i = np.flatnonzero(self.app.section_core_mask).tolist().index(idx)

            code = int(cls[idx])
            entry = palette.get(code, {"color": (128,128,128)})

            color = entry["color"]
            rgb_array.SetTuple3(vtk_i, color[0], color[1], color[2])

        rgb_array.Modified()
        poly.Modified()

        vtk_widget.render()
        print(f"🔄 Partial refresh applied to {len(changed_indices)} points")

    def unlock_after_classification(self):
        """
        Restore normal interaction after classification is complete.
        Called when user presses ESC or closes class picker.
        """
        try:
            print("🔓 Unlocking section controller after classification")
            
            # Restore default 2D interactor on all cross-section views
            if hasattr(self.app, 'section_vtks'):
                from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
                
                for view_idx, vtk_widget in self.app.section_vtks.items():
                    try:
                        if vtk_widget and hasattr(vtk_widget, 'interactor'):
                            # Restore 2D pan/zoom style
                            style = vtkInteractorStyleImage()
                            vtk_widget.interactor.SetInteractorStyle(style)
                            print(f"   ✅ View {view_idx + 1}: Interactor restored")
                    except Exception as e:
                        print(f"   ⚠️ View {view_idx + 1}: Failed to restore interactor - {e}")
            
            # Clear any classification-specific state
            self._classification_active = False
            
            print("✅ Section controller unlocked")
            
        except Exception as e:
            print(f"⚠️ unlock_after_classification failed: {e}")

    def _get_current_view_mode(self):
        """
        Get the ACTUAL current view mode (front/side) from the active view's button state.
        ✅ FIXED: Checks button state instead of assuming app.cross_view_mode
        """
        if not hasattr(self, 'active_view') or self.active_view is None:
            return getattr(self.app, 'cross_view_mode', 'front')
        
        # Check if we have section docks with buttons
        if hasattr(self.app, 'section_view_buttons') and self.active_view in self.app.section_view_buttons:
            buttons = self.app.section_view_buttons[self.active_view]
            
            if buttons['side'].isChecked():
                return 'side'
            elif buttons['front'].isChecked():
                return 'front'
        
        # Fallback to app-level setting
        return getattr(self.app, 'cross_view_mode', 'front')

    # ✅ ADD THESE TWO NEW METHODS HERE:

    def set_cross_view_mode(self, mode):
        """
        Set view mode and trigger immediate refresh if changed.
        ✅ FIXED: Automatically refreshes the cross-section when switching views.
        """
        old_mode = getattr(self.app, 'cross_view_mode', 'side')
        
        if old_mode != mode:
            print(f"\n{'='*60}")
            print(f"🔄 VIEW MODE CHANGING: {old_mode} → {mode}")
            print(f"{'='*60}")
            
            # Set new mode
            self.app.cross_view_mode = mode
            
            # Get active view
            if not hasattr(self, 'active_view') or self.active_view is None:
                print("   ⚠️ No active view to refresh")
                print(f"{'='*60}\n")
                return
            
            # Mark for rebuild
            setattr(self.app, f'_force_rebuild_view_{self.active_view}', True)
            
            # Clear coordinate cache in classification interactor
            if hasattr(self.app, 'classify_interactor'):
                try:
                    self.app.classify_interactor._invalidate_coord_cache()
                    print("   ✅ Classification coordinate cache cleared")
                except Exception:
                    pass
            
            # Get section data for active view
            core_points = getattr(self.app, f"section_{self.active_view}_core_points", None)
            buffer_points = getattr(self.app, f"section_{self.active_view}_buffer_points", None)
            
            if core_points is None:
                print("   ⚠️ No section data for active view")
                print(f"{'='*60}\n")
                return
            
            print(f"   🔄 Refreshing Cross-Section View {self.active_view + 1}...")
            
            try:
                # Trigger immediate re-render with new view mode
                self._plot_section(core_points, buffer_points, view=mode)
                print(f"   ✅ View {self.active_view + 1} refreshed for {mode} mode")
            except Exception as e:
                print(f"   ❌ View refresh failed: {e}")
                import traceback
                traceback.print_exc()
            
            # Update button states
            self._update_view_buttons(mode)
            
            print(f"{'='*60}\n")
        else:
            # No change
            self.app.cross_view_mode = mode

    def _update_view_buttons(self, mode):
        """Update button states to reflect current view mode"""
        try:
            if hasattr(self.app, 'section_view_buttons') and self.active_view in self.app.section_view_buttons:
                buttons = self.app.section_view_buttons[self.active_view]
                
                # Block signals to prevent recursive calls
                buttons['side'].blockSignals(True)
                buttons['front'].blockSignals(True)
                
                # Update checked state
                buttons['side'].setChecked(mode == 'side')
                buttons['front'].setChecked(mode == 'front')
                
                # Unblock signals
                buttons['side'].blockSignals(False)
                buttons['front'].blockSignals(False)
                
                print(f"   ✅ Updated button states for {mode} mode")
        except Exception as e:
            print(f"   ⚠️ Failed to update button states: {e}")