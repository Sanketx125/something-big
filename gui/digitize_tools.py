from ast import Pass
import vtk
import numpy as np
try:
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                    QLineEdit, QSpinBox, QFontComboBox, QComboBox,
                                    QCheckBox, QPushButton, QGroupBox, QColorDialog,QRadioButton, QMenu)
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QCursor
except ImportError:
    try:
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                      QLineEdit, QSpinBox, QFontComboBox, QComboBox,
                                      QCheckBox, QPushButton, QGroupBox, QColorDialog, QMenu)
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QColor, QCursor
    except ImportError:
        print("⚠️ Qt library not found - text editing will be limited")

try:
    from gui.theme_manager import get_dialog_stylesheet, ThemeColors as _TC
except Exception:
    def get_dialog_stylesheet(): return ""
    class _TC:
        @staticmethod
        def get(k): return ""

class DigitizeManager:
    """
    Full-featured geo-referenced digitizing system for Naksha Plan View.
    Supports: line (continuous smartline), rectangle, circle, polygon, text, freehand.
    """

    def __init__(self, app, renderer, interactor):
        self.enabled = True
        self._event_forward = True

        self.app = app
        self.renderer = renderer
        self.interactor = interactor

        # Data storage
        self.drawings = []  
        # Undo/Redo system
        self.undo_stack = []     # Stack of previous states
        self.redo_stack = []     # Stack of undone states
        self.max_undo_levels = 50  # Limit undo history
        # list of {type, coords, actor, text}
        self.active_tool = None
        self.temp_points = []
        # ✅ All tools permanent by default
        self.polyline_permanent_mode = True
        self.rectangle_permanent_mode = True
        self.circle_permanent_mode = True
        self.freehand_permanent_mode = True
        self.smartline_permanent_mode = True
        self.line_permanent_mode = True

        # --- Smart line additions ---
        self._continuous_line_actor = None
        self._preview_line_actor = None

        # Editing
        self.selected = None
        self.move_mode = False
        self._last_pos = None
        self.left_down = False
        self.middle_down = False 
        self._is_panning = False 

        self.coord_labels = []   # stores floating coordinate labels
        self.selected_drawing = None  # ✅
        self._is_panning = False
        self._pan_start_pos = None
        self._middle_press_processed = False 
        self._temp_vertex_stack = []
        self._temp_redo_stack = []

        # Track our own VTK observer IDs so we can remove only ours
        # (not grid_label_system's or other tools' observers)
        self._draw_observer_ids = []
        # Suspended drawing state (preserved when section tool activated mid-draw)
        self._suspended_state = None   # {"tool": str, "temp_points": list, "markers": list}
        self._suspended_preview_actor = None

        self.snap_enabled = False  # ✅ Snap disabled by default
        self.vertex_move_mode = False
        self.dragging_vertex = None
        self.vertex_hover_marker = None
        self.vertex_drag_marker = None
        self.vertex_auto_drag = False

        # Picker setup
        self.picker = vtk.vtkWorldPointPicker()
        self.interactor.SetPicker(self.picker)

        # Disable 3D rotation
        try:
            style = vtk.vtkInteractorStyleTrackballCamera()
            self.interactor.SetInteractorStyle(style)

            print("🎯 Digitizer interactor style locked (no 3D rotation)")
        except Exception as e:
            print("⚠️ Failed to set interactor style:", e)

        # Event bindings — store IDs so we can remove only our observers later
        self._ensure_plan_view_interaction("digitizer init")
        self._draw_observer_ids.append(self.interactor.AddObserver("LeftButtonPressEvent", self._on_left_press))
        self._draw_observer_ids.append(self.interactor.AddObserver("MouseMoveEvent", self._on_mouse_move))
        self._draw_observer_ids.append(self.interactor.AddObserver("LeftButtonReleaseEvent", self._on_left_release))
        self._draw_observer_ids.append(self.interactor.AddObserver("RightButtonPressEvent", self._on_right_press))
        self.interactor.AddObserver("KeyPressEvent", self._on_key_press)
        # Middle mouse button for panning
        self.interactor.AddObserver("MiddleButtonPressEvent", self._on_middle_press)
        self.interactor.AddObserver("MiddleButtonReleaseEvent", self._on_middle_release)
        # After existing interactor.AddObserver calls (~line 91):
        self.interactor.AddObserver("MouseWheelForwardEvent", self._on_zoom, 1.0)
        self.interactor.AddObserver("MouseWheelBackwardEvent", self._on_zoom, 1.0)
                # Ensure interactor focus for key handling
        try:
            self.interactor.EnableRenderOn()
            print("🎹 Key focus ensured for digitizer interactor")
        except Exception:
            pass

        self.picker = vtk.vtkWorldPointPicker()
        self.interactor.SetPicker(self.picker)
        
        # Native optimized pickers
        self._cell_picker = vtk.vtkCellPicker()
        self._cell_picker.SetTolerance(0.005)
        self._prop_picker = vtk.vtkPropPicker()

        # ── OVERLAY RENDERER (always draws on top of point cloud) ──────────────────
        render_window = self.interactor.GetRenderWindow()
        self.overlay_renderer = vtk.vtkRenderer()
        self.overlay_renderer.SetLayer(1)          # Layer 1 = always above layer 0
        self.overlay_renderer.SetInteractive(0)    # Don't intercept mouse events
        self.overlay_renderer.SetBackgroundAlpha(0.0)
        render_window.SetNumberOfLayers(2)
        render_window.AddRenderer(self.overlay_renderer)
        # Share the EXACT same camera — pan/zoom stays in sync automatically
        self.overlay_renderer.SetActiveCamera(self.renderer.GetActiveCamera())
        print("✅ Overlay renderer created (digitize tools always on top)")
        # ───────────────────────────────────────────────────────────────────────────

        # ── Draw tool style settings (per-tool color/width/style) ─────────────────
        from gui.draw_settings_dialog import load_draw_settings, DEFAULT_DRAW_STYLES
        self.default_draw_tool_styles = {k: dict(v) for k, v in DEFAULT_DRAW_STYLES.items()}
        try:
            loaded_styles = load_draw_settings()
            self.draw_tool_styles = {
                key: {
                    **self.default_draw_tool_styles.get(key, {}),
                    **dict(loaded_styles.get(key, {})),
                }
                for key in self.default_draw_tool_styles
            }
        except Exception:
            self.draw_tool_styles = {
                k: dict(v) for k, v in self.default_draw_tool_styles.items()
            }
        print("✅ Draw tool styles loaded")
        # ───────────────────────────────────────────────────────────────────────────

    def _on_zoom(self, obj, evt):
        """Schedule preview update AFTER VTK finishes processing zoom."""
        if not self.temp_points:
            return
        # ✅ VTK hasn't zoomed the camera yet — defer to next event loop
        try:
            from PySide6.QtCore import QTimer
        except ImportError:
            from PyQt5.QtCore import QTimer
        QTimer.singleShot(0, self._deferred_preview_update)

    def _get_draw_style(self, tool_key):
        """Return a draw style merged with defaults so previews use configured colors immediately."""
        default_style = getattr(self, "default_draw_tool_styles", {}).get(
            tool_key, {'color': (1.0, 0.0, 0.0), 'width': 2, 'style': 'solid'}
        )
        style = dict(default_style)
        style.update((getattr(self, "draw_tool_styles", {}) or {}).get(tool_key, {}) or {})
        return style


    def _deferred_preview_update(self):
        """Reproject all 2D preview actors AFTER camera has finished moving."""
        if not self.temp_points or not self.active_tool:
            return

        mouse_x, mouse_y = self.interactor.GetEventPosition()

        if self.active_tool in ("smartline", "line"):
            style = self._get_draw_style(self.active_tool)
            color = style['color']
            width = style['width']
            line_style = style['style']
            if len(self.temp_points) >= 2:
                self._update_continuous_preview(color=color, width=width, line_style=line_style)
            if len(self.temp_points) >= 1:
                self._update_cursor_preview(color=color, width=width, line_style=line_style)

        elif self.active_tool == "polyline":
            style = self._get_draw_style('polyline')
            color = style['color']
            width = style['width']
            line_style = style['style']
            if len(self.temp_points) >= 2:
                self._update_continuous_preview(color=color, width=width, line_style=line_style)
            if len(self.temp_points) >= 1:
                self._update_cursor_preview(color=color, width=width, line_style='dotted', close_loop=True)

        elif self.active_tool == "rectangle" and len(self.temp_points) == 1:
            style = self._get_draw_style('rectangle')
            self._update_rectangle_preview(color=style['color'], width=style['width'], line_style=style['style'])

        elif self.active_tool == "circle" and len(self.temp_points) == 1:
            style = self._get_draw_style('circle')
            self._update_circle_preview_world(color=style['color'], width=style['width'], line_style=style['style'])

        elif self.active_tool == "freehand" and len(self.temp_points) >= 2:
            fh_style = self._get_draw_style('freehand')
            self._update_freehand_preview_world(
                color=fh_style['color'],
                width=fh_style['width'],
                line_style=fh_style['style'],
            )

        self.app.vtk_widget.render()

    def _update_continuous_preview(self, color, width=3, line_style='solid'):
        """Keep placed preview vertices in world space so pan/zoom cannot detach them."""
        if len(self.temp_points) < 2:
            self._remove_preview_actor_2d('_continuous_line_actor')
            return

        self._update_continuous_line_world(
            '_continuous_line_actor',
            list(self.temp_points),
            color=color,
            width=width,
            line_style=line_style,
        )

    def _update_cursor_preview(self, color, width=2, line_style='solid', close_loop=False, current_world=None):
        """Keep the live rubber-band preview in world space during pan/zoom."""
        if len(self.temp_points) < 1:
            self._remove_preview_actor_2d('_preview_line_actor')
            return

        if current_world is None:
            current_world = self._get_mouse_world()
        preview_points = [tuple(self.temp_points[-1]), tuple(current_world)]
        if close_loop and self.temp_points:
            preview_points.append(tuple(self.temp_points[0]))

        self._update_continuous_line_world(
            '_preview_line_actor',
            preview_points,
            color=color,
            width=width,
            line_style=line_style,
        )

    def _build_rectangle_preview_points(self, p1, p2):
        """Build rectangle preview coordinates in world space."""
        x1, y1, z1 = p1
        x2, y2, z2 = p2
        return [
            (x1, y1, z1),
            (x2, y1, z1),
            (x2, y2, z2),
            (x1, y2, z2),
            (x1, y1, z1),
        ]

    def _build_circle_preview_points(self, center, edge, n=None):
        """Build circle preview coordinates in world space."""
        radius = np.sqrt((edge[0] - center[0]) ** 2 + (edge[1] - center[1]) ** 2)
        if radius <= 0:
            return []

        if n is None:
            n = self._get_circle_segment_count(center, edge)

        thetas = np.linspace(0, 2 * np.pi, n, endpoint=False)
        coords = [
            (center[0] + radius * np.cos(t), center[1] + radius * np.sin(t), center[2])
            for t in thetas
        ]
        coords.append(coords[0])
        return coords

    def _get_circle_segment_count(self, center, edge, min_segments=128, max_segments=1440):
        """Choose circle resolution from current on-screen size so zoomed previews stay smooth."""
        try:
            screen_radius = float(self._world_to_screen_distance(center, edge))
        except Exception:
            screen_radius = 0.0

        if screen_radius > 0.0:
            circumference_px = 2.0 * np.pi * screen_radius
            segments = int(np.ceil(circumference_px / 2.0))  # about one segment per ~2 px
        else:
            world_radius = float(np.sqrt((edge[0] - center[0]) ** 2 + (edge[1] - center[1]) ** 2))
            segments = 128 if world_radius < 50 else 180

        segments = max(min_segments, min(max_segments, segments))
        return int(np.ceil(segments / 8.0) * 8)

    def _update_rectangle_preview(self, color, width=2, line_style='solid'):
        """Keep rectangle preview in world space so it stays aligned while panning."""
        if len(self.temp_points) != 1:
            self._remove_preview_actor_2d('_rectangle_preview_actor')
            return

        world_pos = self._get_mouse_world_no_snap()
        coords = self._build_rectangle_preview_points(self.temp_points[0], world_pos)
        self._update_continuous_line_world(
            '_rectangle_preview_actor',
            coords,
            color=color,
            width=width,
            line_style=line_style,
        )

    def _update_circle_preview_world(self, color, width=2, line_style='solid'):
        """Keep circle preview in world space so it stays aligned while panning."""
        if len(self.temp_points) != 1:
            self._remove_preview_actor_2d('_circle_preview_actor')
            self._remove_preview_actor_2d('_circle_preview_actor_2d')
            return

        self._remove_preview_actor_2d('_circle_preview_actor_2d')
        world_pos = self._get_mouse_world_no_snap()
        coords = self._build_circle_preview_points(self.temp_points[0], world_pos)
        if coords:
            self._update_continuous_line_world(
                '_circle_preview_actor',
                coords,
                color=color,
                width=width,
                line_style=line_style,
            )
            actor = getattr(self, '_circle_preview_actor', None)
            if actor is not None:
                try:
                    actor.GetProperty().RenderLinesAsTubesOn()
                except Exception:
                    pass
        else:
            self._remove_preview_actor_2d('_circle_preview_actor')

    def _update_freehand_preview_world(self, color, width=2, line_style='solid'):
        """Keep freehand preview in world space so it stays aligned while panning."""
        if len(self.temp_points) < 2:
            self._remove_preview_actor_2d('_preview_actor')
            self._remove_preview_actor_2d('_freehand_preview_actor_2d')
            return

        self._update_continuous_line_world(
            '_preview_actor',
            list(self.temp_points),
            color=color,
            width=width,
            line_style=line_style,
        )

    def _get_line_dash_pattern(self, line_style):
        """Return the visible dash pattern in screen-pixel units."""
        if line_style == 'dashed':
            return [(10.0, 6.0)]
        if line_style == 'dotted':
            return [(2.0, 6.0)]
        if line_style == 'dash-dot':
            return [(10.0, 6.0), (2.0, 6.0)]
        if line_style == 'dash-dot-dot':
            return [(10.0, 6.0), (2.0, 4.0), (2.0, 6.0)]
        return None

    def _build_styled_polydata_world(self, world_points, line_style='solid'):
        """Build world-space polydata with visible line styles using explicit segments."""
        poly = vtk.vtkPolyData()
        pts = vtk.vtkPoints()
        pts.SetDataTypeToDouble()
        lines = vtk.vtkCellArray()

        if not world_points or len(world_points) < 2:
            poly.SetPoints(pts)
            poly.SetLines(lines)
            poly.Modified()
            return poly

        dash_pattern = self._get_line_dash_pattern(line_style)
        if not dash_pattern:
            for p in world_points:
                pts.InsertNextPoint(float(p[0]), float(p[1]), float(p[2]))

            n = pts.GetNumberOfPoints()
            lines.InsertNextCell(n)
            for i in range(n):
                lines.InsertCellPoint(i)

            poly.SetPoints(pts)
            poly.SetLines(lines)
            poly.Modified()
            return poly

        point_idx = 0
        for seg_idx in range(len(world_points) - 1):
            p1 = np.array(world_points[seg_idx], dtype=np.float64)
            p2 = np.array(world_points[seg_idx + 1], dtype=np.float64)

            world_vec = p2 - p1
            world_len = np.linalg.norm(world_vec)
            if world_len < 1e-9:
                continue

            screen_len = float(self._world_to_screen_distance(p1, p2))
            if screen_len < 1e-6:
                screen_len = world_len

            direction = world_vec / world_len
            t_px = 0.0
            pattern_idx = 0

            while t_px < screen_len:
                dash_length, gap_length = dash_pattern[pattern_idx]
                dash_end_px = min(t_px + dash_length, screen_len)
                if dash_end_px - t_px <= 1e-6:
                    break

                start_ratio = t_px / screen_len
                end_ratio = dash_end_px / screen_len
                dash_start = p1 + direction * (world_len * start_ratio)
                dash_end = p1 + direction * (world_len * end_ratio)

                pts.InsertNextPoint(float(dash_start[0]), float(dash_start[1]), float(dash_start[2]))
                start_idx = point_idx
                point_idx += 1

                pts.InsertNextPoint(float(dash_end[0]), float(dash_end[1]), float(dash_end[2]))
                end_idx = point_idx
                point_idx += 1

                lines.InsertNextCell(2)
                lines.InsertCellPoint(start_idx)
                lines.InsertCellPoint(end_idx)

                t_px = dash_end_px + gap_length
                pattern_idx = (pattern_idx + 1) % len(dash_pattern)

        poly.SetPoints(pts)
        poly.SetLines(lines)
        poly.Modified()
        return poly

    def _apply_world_line_style(self, prop, line_style='solid'):
        """World actors use explicit segmented geometry, so keep the property itself solid."""
        try:
            prop.SetLineStippleRepeatFactor(1)
            prop.SetLineStipplePattern(0xFFFF)
        except Exception:
            pass

    def _update_continuous_line_world(self, attr_name, world_points, color=(0,1,0), width=3, line_style='solid'):
        """
        World-space preview geometry — zooms/pans perfectly with no lag.
        Uses vtkPolyDataMapper (3D) instead of 2D screen-space mapper.
        """
        if not world_points or len(world_points) < 2:
            actor = getattr(self, attr_name, None)
            if actor:
                self.overlay_renderer.RemoveActor(actor)
                setattr(self, attr_name, None)
            return

        poly = self._build_styled_polydata_world(world_points, line_style=line_style)

        actor = getattr(self, attr_name, None)
        if actor is not None and actor.IsA("vtkActor2D"):
            self._remove_preview_actor_2d(attr_name)
            actor = None

        if actor is None:
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly)
            mapper.SetResolveCoincidentTopologyToPolygonOffset()
            mapper.SetResolveCoincidentTopologyPolygonOffsetParameters(-3, -3)
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(float(color[0]), float(color[1]), float(color[2]))
            actor.GetProperty().SetLineWidth(float(width))
            actor.GetProperty().SetOpacity(1.0)
            self._apply_world_line_style(actor.GetProperty(), line_style=line_style)
            actor.PickableOff()
            actor.SetVisibility(1)
            self._add_actor_to_overlay(actor)
            setattr(self, attr_name, actor)
        else:
            actor.GetMapper().SetInputData(poly)
            actor.GetMapper().Modified()
            actor.GetProperty().SetColor(float(color[0]), float(color[1]), float(color[2]))
            actor.GetProperty().SetLineWidth(float(width))
            self._apply_world_line_style(actor.GetProperty(), line_style=line_style)
            actor.SetVisibility(1)

    def _restore_shared_interactor_observers(self):
        """Re-install non-digitizer observers that may be removed during tool switches."""
        grid_manager = getattr(self.app, 'grid_label_manager', None)
        if not grid_manager:
            return

        try:
            if hasattr(grid_manager, 'ensure_interactor_observers'):
                grid_manager.ensure_interactor_observers()
            else:
                grid_manager.setup_interactor()
        except Exception as e:
            print(f"âš ï¸ Failed to restore grid-label observers: {e}")

    def _ensure_plan_view_interaction(self, reason="digitizer"):
        """Keep the main viewer in 2D plan interaction while digitizing."""
        if getattr(self.app, 'is_3d_mode', False):
            return

        try:
            if hasattr(self.app, 'ensure_main_view_2d_interaction'):
                self.app.ensure_main_view_2d_interaction(
                    preserve_camera=True,
                    reason=reason,
                )
                return
        except Exception as e:
            print(f"⚠️ Digitizer failed to request 2D interaction: {e}")

        try:
            from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage

            style = self.interactor.GetInteractorStyle()
            style_name = style.GetClassName() if style is not None else "None"
            if style_name != "vtkInteractorStyleImage":
                style_2d = vtkInteractorStyleImage()
                try:
                    style_2d.SetInteractionModeToImageSlicing()
                except Exception:
                    pass
                self.interactor.SetInteractorStyle(style_2d)

            camera = self.renderer.GetActiveCamera()
            if camera is not None:
                camera.ParallelProjectionOn()
                self.renderer.ResetCameraClippingRange()

            self.app.vtk_widget.render()
            print(f"🔒 Digitizer forced 2D plan interaction ({reason})")

        except Exception as e:
            print(f"⚠️ Digitizer could not enforce 2D interaction: {e}")

    def _consume_vtk_event(self, obj):
        """Stop the default VTK interactor style from also processing our draw events."""
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

    def _clear_suspended_preview_actor(self):
        actor = getattr(self, '_suspended_preview_actor', None)
        if actor is None:
            return

        try:
            self.overlay_renderer.RemoveActor(actor)
        except Exception:
            try:
                self.renderer.RemoveActor(actor)
            except Exception:
                pass

        self._suspended_preview_actor = None

    def _clear_live_preview_actors(self):
        """Remove transient preview actors so suspended drawings do not freeze on-screen."""
        for attr in (
            '_preview_line_actor',
            '_continuous_line_actor',
            '_rectangle_preview_actor',
            '_preview_actor',
            '_circle_preview_actor_2d',
            '_circle_preview_actor',
            '_freehand_preview_actor_2d',
        ):
            self._remove_preview_actor_2d(attr)

    def _show_suspended_preview(self, tool_name, temp_points):
        """Show a world-space placeholder while a draw tool is suspended."""
        self._clear_suspended_preview_actor()
        self._clear_live_preview_actors()

        if not tool_name or not temp_points:
            self.app.vtk_widget.render()
            return

        world_points = None
        if tool_name in ("smartline", "line", "freehand") and len(temp_points) >= 2:
            world_points = list(temp_points)
        elif tool_name == "polyline" and len(temp_points) >= 2:
            world_points = list(temp_points)
            world_points.append(world_points[0])

        if not world_points or len(world_points) < 2:
            self.app.vtk_widget.render()
            return

        style = self._get_draw_style(tool_name)
        self._update_continuous_line_world(
            '_suspended_preview_actor',
            world_points,
            color=style.get('color', (1, 0, 0)),
            width=style.get('width', 3),
        )
        self.app.vtk_widget.render()

    def _get_display_coords_from_world(self, world_points):
        """
        TRASH REMOVAL: Converts 3D world points to 2D display points for overlay rendering.
        """
        if not world_points:
            return None

        renderer = self.renderer
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToWorld()

        display_points = vtk.vtkPoints()
        
        for p in world_points:
            coord.SetValue(p[0], p[1], p[2])
            d = coord.GetComputedDisplayValue(renderer)
            display_points.InsertNextPoint(d[0], d[1], 0.0)

        return display_points
    
    def _update_circle_preview_2d(self, center, radius, segments=None):
        """
        Generates a smooth 2D overlay for the circle preview. 
        NO Z-FIGHTING allowed.
        """
        # 1. Clean up old 3D preview if it exists (legacy trash)
        if hasattr(self, "_circle_preview_actor") and self._circle_preview_actor:
            self.renderer.RemoveActor(self._circle_preview_actor)
            self._circle_preview_actor = None

        # 2. Generate World Points (Resolution matters)
        n = segments or 128
        thetas = np.linspace(0, 2 * np.pi, n, endpoint=True)
        # Assume Z is constant at center for the preview ring
        world_coords = [
            (center[0] + radius * np.cos(t), center[1] + radius * np.sin(t), center[2])
            for t in thetas
        ]

        # 3. Convert to Display Space
        display_pts = self._get_display_coords_from_world(world_coords)

        # 4. Create 2D PolyData
        lines = vtk.vtkCellArray()
        lines.InsertNextCell(n)
        for i in range(n):
            lines.InsertCellPoint(i)

        poly = vtk.vtkPolyData()
        poly.SetPoints(display_pts)
        poly.SetLines(lines)

        # 5. Mapper & Actor 2D
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        
        # Coordinate system must be Display
        c = vtk.vtkCoordinate()
        c.SetCoordinateSystemToDisplay()
        mapper.SetTransformCoordinate(c)

        if not hasattr(self, "_circle_preview_actor_2d") or self._circle_preview_actor_2d is None:
            self._circle_preview_actor_2d = vtk.vtkActor2D()
            self.renderer.AddActor2D(self._circle_preview_actor_2d)

        self._circle_preview_actor_2d.SetMapper(mapper)
        
        # Style: Use configured tool settings
        _ci = self._get_draw_style('circle')
        prop = self._circle_preview_actor_2d.GetProperty()
        prop.SetColor(*_ci['color'])
        prop.SetLineWidth(_ci['width'])
        prop.SetOpacity(1.0)

    ####newww
    def _world_to_display_pt(self, world_point):
        """Convert one world point to screen pixel coords."""
        self.renderer.SetWorldPoint(
            float(world_point[0]), float(world_point[1]), float(world_point[2]), 1.0
        )
        self.renderer.WorldToDisplay()
        d = self.renderer.GetDisplayPoint()
        return (d[0], d[1])

    def _make_preview_actor_screen(self, screen_points, color=(0, 1, 0), width=3):
        """
        Pure screen-space 2D line. Points are already in display pixels.
        No world transform — no Z picking — no offset ever.
        """
        if not screen_points or len(screen_points) < 2:
            return None

        pts = vtk.vtkPoints()
        for p in screen_points:
            pts.InsertNextPoint(float(p[0]), float(p[1]), 0.0)

        n = pts.GetNumberOfPoints()
        cell = vtk.vtkCellArray()
        cell.InsertNextCell(n)
        for i in range(n):
            cell.InsertCellPoint(i)

        poly = vtk.vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(cell)

        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        # ✅ No SetTransformCoordinate — points are raw pixels, no conversion needed

        actor = vtk.vtkActor2D()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(float(color[0]), float(color[1]), float(color[2]))
        prop.SetLineWidth(float(width))
        prop.SetOpacity(1.0)
        prop.SetDisplayLocationToForeground()
        return actor  ###

        
    def _update_freehand_preview_2d(self, points):
        """
        Updates freehand trace using 2D Actor.
        """
        # 1. Clean up old 3D preview
        if hasattr(self, "_preview_actor") and self._preview_actor:
            self.renderer.RemoveActor(self._preview_actor)
            self._preview_actor = None
            
        if len(points) < 2:
            return

        # 2. Convert to Display Space
        display_pts = self._get_display_coords_from_world(points)

        # 3. Create Lines
        n = display_pts.GetNumberOfPoints()
        lines = vtk.vtkCellArray()
        lines.InsertNextCell(n)
        for i in range(n):
            lines.InsertCellPoint(i)

        poly = vtk.vtkPolyData()
        poly.SetPoints(display_pts)
        poly.SetLines(lines)

        # 4. Mapper 2D
        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        
        c = vtk.vtkCoordinate()
        c.SetCoordinateSystemToDisplay()
        mapper.SetTransformCoordinate(c)

        # 5. Actor 2D
        if not hasattr(self, "_freehand_preview_actor_2d") or self._freehand_preview_actor_2d is None:
            self._freehand_preview_actor_2d = vtk.vtkActor2D()
            self.renderer.AddActor2D(self._freehand_preview_actor_2d)
            
        self._freehand_preview_actor_2d.SetMapper(mapper)
        
        fh_style = self._get_draw_style('freehand')
        prop = self._freehand_preview_actor_2d.GetProperty()
        prop.SetColor(*fh_style['color'])
        prop.SetLineWidth(float(fh_style.get('width', 2)))
        
    # ---------------- PUBLIC ----------------
    def enable(self, state: bool = True):
        self.enabled = state
        print("✏️ Digitizer ENABLED" if state else "🚫 Digitizer DISABLED")
        
        
        
    def _force_render(self):
        """✅ Hardware-level forced flush to the screen"""
        self.renderer.Modified()
        try:
            self.app.vtk_widget.interactor.GetRenderWindow().Render()
        except: pass
        try:
            self.app.vtk_widget.render()
        except: pass

    def _auto_select_last_drawing(self):
        # """Automatically selects the newly created drawing."""
        # if not self.drawings: return
        # self.clear_coordinate_labels()
        # self._unhighlight_all_lines()
        # self.selected_drawing = self.drawings[-1]
        # self._highlight_line(self.selected_drawing)
        # if "coords" in self.selected_drawing:
        #     self.show_vertex_coordinates(self.selected_drawing["coords"])
        # self._force_render()
        pass

    def _on_right_press(self, obj, evt):
        """
        Handle right-click.
        Priority Order:
        1. FINALIZE Drawing
        2. SELECT Drawing
        """
        if not self.enabled: return

        # =====================================================================
        # 1. PRIORITY: FINALIZE ACTIVE DRAWING TOOLS
        # =====================================================================
        if self.active_tool:
            self._consume_vtk_event(obj)
            if self.active_tool == "rectangle" and len(self.temp_points) == 1:
                pos = self._get_mouse_world_no_snap()
                self.temp_points.append(pos)
                # REPLACE WITH:
                self._finalize_rectangle()
                if not getattr(self, 'rectangle_permanent_mode', True):
                    self.active_tool = None
                return
            
            if self.active_tool == "circle" and len(self.temp_points) == 1:
                pos = self._get_mouse_world_no_snap()
                self.temp_points.append(pos)
                # REPLACE WITH:
                self._finalize_circle()
                self._auto_select_last_drawing()
                if not getattr(self, 'circle_permanent_mode', True):
                    self.active_tool = None
                return 
            
            if self.active_tool == "polyline" and len(self.temp_points) >= 3:
                self._finalize_polyline()
                if getattr(self, 'polyline_permanent_mode', False):
                    self.temp_points = []
                    self.clear_coordinate_labels()
                    self._unhighlight_all_lines()
                    self.selected_drawing = None
                else:
                    self.active_tool = None
                return 

            # ✅ BULLETPROOF FREEHAND FINALIZATION
            if self.active_tool == "freehand":
                self.left_down = False
                self.is_drawing_freehand = False
                
                if hasattr(self, "temp_points") and len(self.temp_points) > 1:
                    # Auto-close loop if the start and end points aren't exactly the same
                    start_pt = np.array(self.temp_points[0])
                    end_pt = np.array(self.temp_points[-1])
                    
                    if np.linalg.norm(end_pt - start_pt) > 0.01:
                        self.temp_points.append(tuple(start_pt))
                        print("🔗 Freehand auto-closed on Right-Click")
                        
                    self._finalize_freehand()
                else:
                    print("❌ Freehand cancelled (not enough points)")
                    if hasattr(self, "_preview_actor") and self._preview_actor:
                        try: self.renderer.RemoveViewProp(self._preview_actor)
                        except: pass
                        self._preview_actor = None
                                
                self.temp_points = []
                if not getattr(self, 'freehand_permanent_mode', True):
                    self.active_tool = None
                self._force_render()
                return
                
            if self.active_tool in ("smartline", "line") and len(self.temp_points) >= 2:
                current = self.active_tool
                func = self._finalize_smart_line if current == "smartline" else self._finalize_line
                func()
                flag = 'smartline_permanent_mode' if current == "smartline" else 'line_permanent_mode'
                if not getattr(self, flag, True):
                    self.active_tool = None
                return
            
            # If an active tool is clicked but conditions aren't met to finalize, reset it
            self.temp_points = []
            
            if self.active_tool == "text" and getattr(self, "_placing_text", False):
                self._finalize_text_drag(None, None)
                self._force_render()
                return
            
            # For other tools, it just resets their points
            self._force_render()
            return 
        
        

        # =====================================================================
        # 2. SELECTION MODE (IDLE) 
        # =====================================================================
        x, y = self.interactor.GetEventPosition()
        picked_drawing = None
        
        # A. Hardware picker
        actor = self._pick_actor(x, y)
        if actor:
            for d in self.drawings:
                if d.get("actor") is actor:
                    picked_drawing = d
                    break
        
        # B. Math picker fallback
        if not picked_drawing:
            picked_drawing = self._get_drawing_under_cursor(x, y, tolerance=25.0)
        
        if picked_drawing:
            if picked_drawing["type"] == "text":
                self.clear_coordinate_labels()
                self._unhighlight_all_lines()
                self.multi_selected = []
                self.selected_drawing = picked_drawing
                
                self._show_text_context_menu(picked_drawing)
                
                self._force_render()
                return
            
            # Shape selection
            shift_held = self.interactor.GetShiftKey()
            if getattr(self, "selected_drawing", None) is picked_drawing and not shift_held:
                # Toggle Off
                self._unhighlight_line(picked_drawing)
                self.clear_coordinate_labels()
                self.selected_drawing = None
            elif shift_held:
                # Multi-Select
                if not hasattr(self, "multi_selected"): self.multi_selected = []
                
                if picked_drawing not in self.multi_selected:
                    self.multi_selected.append(picked_drawing)
                    self._highlight_line(picked_drawing)
                else:
                    self.multi_selected.remove(picked_drawing)
                    self._unhighlight_line(picked_drawing)
                self.selected_drawing = None
            else:
                # Single Select
                self.clear_coordinate_labels()
                self._unhighlight_all_lines()
                self.multi_selected = []
                self.selected_drawing = picked_drawing
                self._highlight_line(picked_drawing)
                
                if "coords" in picked_drawing:
                    self.show_vertex_coordinates(picked_drawing["coords"])
            
            self._force_render()
            return  

        # C. Deselect All
        print("⚪ Clicked empty space - clearing selection")
        self.clear_coordinate_labels()
        self.selected_drawing = None
        self._unhighlight_all_lines()
        self._force_render()
        
    def set_tool(self, tool, suspend_only=False):
        """Activate drawing tool and handle tool-specific setup.

        suspend_only=True  →  only pause input handling, do NOT cancel/clear
                               any in-progress drawing (preview actors + temp_points
                               are preserved so the user can resume later).
        """

        # Clear the shared canvas tool cursor if no draw tool is selected
        if tool is None and hasattr(self.app, 'set_cross_cursor_active'):
            self.app.set_cross_cursor_active(False, "draw")

        # Remove only OUR observers (not grid_label_system's etc.)
        for oid in list(self._draw_observer_ids):
            try:
                self.interactor.RemoveObserver(oid)
            except Exception:
                pass
        self._draw_observer_ids = []
        # Re-add our right-press observer
        self._draw_observer_ids.append(
            self.interactor.AddObserver("RightButtonPressEvent", self._on_right_press, 1.0)
        )

        # ✅ Deactivate measurement tool FIRST
        if hasattr(self.app, 'measurement_tool') and self.app.measurement_tool:
            self.app.measurement_tool.deactivate()
            print("📏 Measurement tool deactivated before drawing")

        # When suspend_only=True we are just parking the tool temporarily
        # (e.g. user activated a section tool mid-draw).  Keep all preview
        # actors and temp_points intact so the drawing is NOT lost.
        if not suspend_only:
            # Cancel any unfinished SmartLine before switching
            if getattr(self, "active_tool", None) == "smartline" and self.temp_points:
                self._cancel_smart_line()

            # Cancel any unfinished Line before switching
            if getattr(self, "active_tool", None) == "line" and self.temp_points:
                if hasattr(self, '_line_vertex_markers'):
                    for m in self._line_vertex_markers:
                        try: self._remove_actor_from_overlay(m)
                        except: pass
                    self._line_vertex_markers = []
                self._remove_preview_actor_2d('_preview_line_actor')
                self._remove_preview_actor_2d('_continuous_line_actor')
                self.temp_points = []
                print("🧹 Cancelled unfinished Line on tool switch")

            # Cancel any unfinished Polyline before switching
            if getattr(self, "active_tool", None) == "polyline" and self.temp_points:
                if hasattr(self, '_polyline_vertex_markers'):
                    for m in self._polyline_vertex_markers:
                        try: self._remove_actor_from_overlay(m)
                        except: pass
                    self._polyline_vertex_markers = []
                self._remove_preview_actor_2d('_preview_line_actor')
                self._remove_preview_actor_2d('_continuous_line_actor')
                self.temp_points = []
                print("🧹 Cancelled unfinished Polyline on tool switch")

        # Normalize tool name
        if tool:
            tool = tool.lower().replace(" ", "").replace("_", "")

        # Draw tool selection must immediately shut down an active classification session.
        if tool and getattr(self.app, 'active_classify_tool', None):
            try:
                print(f"🛑 Draw tool '{tool}' selected — deactivating classification tool")
                self.app.deactivate_classification_tool(preserve_cross_section=True)
            except Exception as e:
                print(f"⚠️ Failed to deactivate classification before drawing: {e}")

        if tool:
            if getattr(self.app, 'cross_section_active', False):
                try:
                    print(f"ðŸ›‘ Draw tool '{tool}' selected â€” deactivating cross-section tool")
                    self.app.deactivate_cross_section_tool()
                except Exception as e:
                    print(f"âš ï¸ Failed to deactivate cross-section before drawing: {e}")
            if getattr(self.app, 'cut_section_mode_on', False):
                try:
                    print(f"ðŸ›‘ Draw tool '{tool}' selected â€” deactivating cut-section tool")
                    self.app.cut_section_controller.cancel_cut_section()
                    self.app.cut_section_mode_on = False
                except Exception as e:
                    print(f"âš ï¸ Failed to deactivate cut-section before drawing: {e}")

        if tool:
            self._ensure_plan_view_interaction(f"draw tool: {tool}")

        # --- Handle suspend / resume logic ---
        _resumed = False

        if suspend_only and tool is None and getattr(self, 'active_tool', None):
            # SUSPENDING: save current drawing state so it can be resumed later
            markers = []
            if hasattr(self, '_line_vertex_markers'):
                markers = list(self._line_vertex_markers)
            elif hasattr(self, '_polyline_vertex_markers'):
                markers = list(self._polyline_vertex_markers)
            self._suspended_state = {
                "tool": self.active_tool,
                "temp_points": list(self.temp_points) if self.temp_points else [],
                "markers": markers,
            }
            self._show_suspended_preview(self.active_tool, self.temp_points)
            print(f"💾 Suspended drawing state: tool={self.active_tool}, points={len(self.temp_points)}")

        elif not suspend_only and self._suspended_state:
            suspended_tool = self._suspended_state["tool"]
            normalized = tool.lower().replace(" ", "").replace("_", "") if tool else ""
            if normalized == suspended_tool:
                # RESUMING same tool → restore temp_points (drawing continues)
                self.temp_points = self._suspended_state["temp_points"]
                _resumed = True
                self._clear_suspended_preview_actor()
                print(f"♻️ Resumed drawing: tool={tool}, restored {len(self.temp_points)} points")
            else:
                # Different tool → cancel the old suspended drawing
                old_pts = self._suspended_state.get("temp_points", [])
                old_markers = self._suspended_state.get("markers", [])
                for m in old_markers:
                    try: self._remove_actor_from_overlay(m)
                    except: pass
                self._clear_suspended_preview_actor()
                if old_pts:
                    self._clear_live_preview_actors()
                    print(f"🧹 Cleared old suspended drawing ({suspended_tool}, {len(old_pts)} pts)")
            self._suspended_state = None

        elif not suspend_only:
            self._clear_suspended_preview_actor()

        self.active_tool = tool
        # Clear temp_points only on normal activation (not suspend, not resume)
        if not suspend_only and not _resumed:
            self.temp_points = []
            self._clear_temp_vertex_history()

        # ✅ NEW: Handle Move Vertex tool
        if self.active_tool == "movevertex":
            print("🔄 Move Vertex mode activated")
            self._activate_move_vertex_mode()
            return

        # Special handling for vertex insertion tool
        if self.active_tool == "vertex":
            print("🔵 Vertex insertion mode activated - click on any line to add a vertex")
        else:
            print(f"🖊️ Tool activated: {self.active_tool or 'select'}")

        # ✅ Re-attach event observers for drawing tools
        if self.active_tool and self.active_tool not in ("text", "movevertex"):
            # Remove only OUR old observers (not grid_label_system's or other tools')
            for oid in list(self._draw_observer_ids):
                try:
                    self.interactor.RemoveObserver(oid)
                except Exception:
                    pass
            self._draw_observer_ids = []

            # Add fresh observers and track their IDs
            self._draw_observer_ids.append(
                self.interactor.AddObserver("LeftButtonPressEvent", self._on_left_press, 1.0))
            self._draw_observer_ids.append(
                self.interactor.AddObserver("MouseMoveEvent", self._on_mouse_move, 1.0))
            self._draw_observer_ids.append(
                self.interactor.AddObserver("RightButtonPressEvent", self._on_right_press, 1.0))

            print(f"✅ Event observers attached for {self.active_tool}")
        
        # Handle polyline modes
        if self.active_tool == "polyline":
            if getattr(self, 'polyline_permanent_mode', False):
                try:
                    self.app.statusBar().showMessage(
                        "🔄 Permanent Polyline Mode - Draw multiple polylines (Shift+Esc to exit)"
                    )
                except:
                    pass    
            
        # REPLACE WITH:
        if tool and "polyline" in tool.lower():
            self.active_tool = "polyline"
            print("🔄 Permanent Polyline mode activated" if self.polyline_permanent_mode else "🖊️ Polyline activated")

        # ✅ Start text placement if text tool
        if self.active_tool == "text":
            self._start_text_label()
        
        # Activate the shared canvas tool cursor after interactor changes
        if self.active_tool and hasattr(self.app, 'set_cross_cursor_active'):
            self.app.set_cross_cursor_active(True, "draw")
            print("Canvas tool cursor activated for drawing")


        if _resumed and self.active_tool and self.temp_points:
            self._deferred_preview_update()

        self._restore_shared_interactor_observers()

    # ---------------- INTERNAL HELPERS ----------------
    def _get_mouse_world(self):
        x, y = self.interactor.GetEventPosition()
        self.picker.Pick(x, y, 0, self.renderer)
        pos = np.array(self.picker.GetPickPosition())
        if self.active_tool and self.snap_enabled:  # ✅ Only snap if enabled
            pos = self._snap_point(pos)
        return pos
    
    
    def _get_mouse_world_no_snap(self):
        """Get mouse position WITHOUT snapping - for smooth freehand/circle drawing."""
        x, y = self.interactor.GetEventPosition()
        self.picker.Pick(x, y, 0, self.renderer)
        pos = np.array(self.picker.GetPickPosition())
        return pos  # No snapping applied

    def _snap_point(self, pos, tol=0.5):
        snap_target = None
        best = tol
        for d in self.drawings:
            for c in d["coords"]:
                dist = np.linalg.norm(np.array(c) - pos)
                if dist < best:
                    best = dist
                    snap_target = c

        if not hasattr(self, "_snap_marker"):
            sphere = vtk.vtkSphereSource()
            sphere.SetRadius(0.15)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(sphere.GetOutputPort())
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0, 1, 0)
            actor.GetProperty().SetOpacity(0.8)
            actor.SetVisibility(False)
            self._snap_marker = actor
            self._add_actor_to_overlay(actor)

        if snap_target is not None:
            self._snap_marker.SetPosition(*snap_target)
            self._snap_marker.SetVisibility(True)
        else:
            self._snap_marker.SetVisibility(False)

        return np.array(snap_target) if snap_target is not None else pos
    
    
    def keyPressEvent(self, event):
        """Handle keyboard events - check digitizer first!"""
        
        # ✅ CRITICAL: Let digitizer handle Ctrl+Z/Ctrl+Y if it's active
        if hasattr(self, 'digitizer') and self.digitizer.enabled:
            key = event.key()
            modifiers = event.modifiers()
            
            from PySide6.QtCore import Qt
            
            # Ctrl+Z - Undo (digitizer priority)
            if key == Qt.Key_Z and modifiers == Qt.ControlModifier:
                self.digitizer.undo()
                event.accept()
                return
            
            # Ctrl+Y - Redo (digitizer priority)
            if key == Qt.Key_Y and modifiers == Qt.ControlModifier:
                self.digitizer.redo()
                event.accept()
                return  
        # If digitizer didn't handle it, pass to parent (classification undo/redo)
        super().keyPressEvent(event)
        

    def _on_left_press(self, obj, evt):
        """Handle left mouse press - add vertices continuously."""
        if not self.enabled:
            return
        self._consume_vtk_event(obj)
        self.left_down = True
        pos = self._get_mouse_world()
        x, y = self.interactor.GetEventPosition()
        world_pos = self._display_to_world(x, y)

        # Shift+Click vertex drag
        if self.interactor.GetShiftKey() and not self.active_tool:
            nearest_vertex, nearest_drawing, vertex_idx = self._find_nearest_vertex_at_position(x, y, tolerance=15.0)
            if nearest_vertex is not None and nearest_drawing:
                self._save_state()
                self.dragging_vertex = {
                    'drawing': nearest_drawing,
                    'vertex_index': vertex_idx,
                    'original_pos': nearest_vertex
                }
                if self.vertex_drag_marker:
                    self._remove_actor_from_overlay(self.vertex_drag_marker)
                self.vertex_drag_marker = self._add_endpoint_sphere(nearest_vertex, color=(1, 1, 0), radius=0.12)
                self.app.vtk_widget.render()
                return

        # Vertex insertion tool
        if self.active_tool == "vertex":
            render_window = self.app.vtk_widget.GetRenderWindow()
            window_height = render_window.GetSize()[1]
            qt_y = window_height - y
            picked_drawing, insertion_point = self._find_line_at_position(x, qt_y)
            if picked_drawing and insertion_point is not None:
                self._insert_vertex_at_point(picked_drawing, insertion_point)
            else:
                print("⚪ No line found at cursor position")
            return

        # Selection mode
        if not self.active_tool:
            actor = self._pick_actor(x, y)
            if actor:
                self._select_actor(actor)
            return

        # ============ FREEHAND ============
        if self.active_tool == "freehand":
            if not self.temp_points:
                self.temp_points = [world_pos]
                print("🖊️ Freehand STARTED")
            else:
                self.temp_points.append(world_pos)
                if len(self.temp_points) >= 2:
                    fh_style = self._get_draw_style('freehand')
                    self._update_freehand_preview_world(
                        color=fh_style['color'],
                        width=fh_style['width'],
                        line_style=fh_style['style'],
                    )
                self.app.vtk_widget.render()
                print("🖊️ Freehand RESUMED")
            self.is_drawing_freehand = True
            return

        # ============ SMARTLINE ============
        if self.active_tool == "smartline":
            sl_style = self._get_draw_style('smartline')
            self._push_temp_vertex_history()

            if len(self.temp_points) == 0:
                snap_target = None
                snap_distance = float('inf')
                snap_tolerance = 0.95
                for drawing in self.drawings:
                    if 'coords' in drawing:
                        for vertex in drawing['coords']:
                            vertex_arr = np.array(vertex)
                            dist = np.linalg.norm(pos - vertex_arr)
                            if dist < snap_tolerance and dist < snap_distance:
                                snap_distance = dist
                                snap_target = vertex_arr
                if snap_target is not None:
                    pos = snap_target

            self.temp_points.append(pos)

            if not hasattr(self, '_smartline_vertex_markers'):
                self._smartline_vertex_markers = []

            if len(self.temp_points) == 1:
                sphere = self._add_endpoint_sphere(pos, color=(0, 1, 0), radius=0.20)
            else:
                sphere = self._add_endpoint_sphere(pos, color=(1, 1, 0), radius=0.20)
                if len(self._smartline_vertex_markers) > 1:
                    self._smartline_vertex_markers[-1].GetProperty().SetColor(1, 1, 0)
            self._smartline_vertex_markers.append(sphere)

            # ✅ Use update in-place — no remove+add = no blink on click
            if len(self.temp_points) >= 2:
                self._update_continuous_preview(
                    color=sl_style['color'],
                    width=sl_style['width'],
                    line_style=sl_style['style'],
                )
                self._update_cursor_preview(
                    color=sl_style['color'],
                    width=sl_style['width'],
                    line_style=sl_style['style'],
                    current_world=pos,
                )
                self.app.vtk_widget.render()
            return

        # ============ LINE ============
        if self.active_tool == "line":
            ln_style = self._get_draw_style('line')
            self._push_temp_vertex_history()

            self.temp_points.append(pos)

            if not hasattr(self, '_line_vertex_markers'):
                self._line_vertex_markers = []

            if len(self.temp_points) == 1:
                sphere = self._add_endpoint_sphere(pos, color=(0, 1, 0), radius=0.05)
                sphere.GetProperty().SetOpacity(0.8)
            else:
                sphere = self._add_endpoint_sphere(pos, color=(1, 1, 0), radius=0.05)
                sphere.GetProperty().SetOpacity(0.8)
                if len(self._line_vertex_markers) > 1:
                    self._line_vertex_markers[-1].GetProperty().SetColor(1, 1, 0)
            self._line_vertex_markers.append(sphere)

            # ✅ Use update in-place
            if len(self.temp_points) >= 2:
                self._update_continuous_preview(
                    color=ln_style['color'],
                    width=ln_style['width'],
                    line_style=ln_style['style'],
                )
                self._update_cursor_preview(
                    color=ln_style['color'],
                    width=ln_style['width'],
                    line_style=ln_style['style'],
                    current_world=pos,
                )
                self.app.vtk_widget.render()
            return

        # ============ RECTANGLE ============
        if self.active_tool == "rectangle":
            if not self.temp_points:
                self.temp_points = [pos]
                return
            if len(self.temp_points) == 1:
                self.temp_points.append(pos)
                self._remove_preview_actor_2d('_rectangle_preview_actor')
                self._finalize_rectangle()
                return

        # ============ CIRCLE ============
        if self.active_tool == "circle":
            if not self.temp_points:
                self.temp_points = [pos]
                return
            if len(self.temp_points) == 1:
                self.temp_points.append(pos)
                self._finalize_circle()
                return

        # ============ POLYLINE ============
        if self.active_tool == "polyline":
            pl_style = self._get_draw_style('polyline')
            self._push_temp_vertex_history()

            self.temp_points.append(pos)

            if not hasattr(self, '_polyline_vertex_markers'):
                self._polyline_vertex_markers = []

            if len(self.temp_points) == 1:
                sphere = self._add_endpoint_sphere(pos, color=(0, 1, 0), radius=0.05)
                sphere.GetProperty().SetOpacity(0.8)
            else:
                sphere = self._add_endpoint_sphere(pos, color=(1, 1, 0), radius=0.05)
                sphere.GetProperty().SetOpacity(0.8)
                if len(self._polyline_vertex_markers) > 1:
                    self._polyline_vertex_markers[-1].GetProperty().SetColor(1, 1, 0)
            self._polyline_vertex_markers.append(sphere)

            # ✅ Use update in-place
            if len(self.temp_points) >= 2:
                self._update_continuous_preview(
                    color=pl_style['color'],
                    width=pl_style['width'],
                    line_style=pl_style['style'],
                )
                self._update_cursor_preview(
                    color=pl_style['color'],
                    width=pl_style['width'],
                    line_style='dotted',
                    close_loop=True,
                    current_world=pos,
                )
                self.app.vtk_widget.render()
            return

        if self.active_tool == "text":
            return  ###

    # ============================================================================
    # VERTEX INSERTION METHODS
    # ============================================================================
    
    def _find_line_at_position(self, x, y, tolerance=50.0):  # ✅ Increased from 15 to 50
        """
        Find which line/polyline is near the clicked position and 
        determine the closest point on that line for vertex insertion.
        
        Returns:
            (drawing, insertion_point) if found, (None, None) otherwise
        """
        try:
            # ✅ CRITICAL: Get VTK Y coordinate (flip from Qt coordinate system)
            render_window = self.app.vtk_widget.GetRenderWindow()
            window_height = render_window.GetSize()[1]
            vtk_y = window_height - y
            
            print(f"🔍 Looking for line at Qt({x}, {y}) -> VTK({x}, {vtk_y})")
            
            # Get world coordinates of click
            picker = vtk.vtkWorldPointPicker()
            picker.Pick(x, vtk_y, 0, self.renderer)  # ✅ Use vtk_y not y
            click_world = np.array(picker.GetPickPosition())
            
            print(f"   World position: {click_world}")
            
            closest_drawing = None
            closest_point = None
            min_distance = float('inf')
            
            # Search through all drawings
            for drawing in self.drawings:
                # Only consider line-based drawings
                if drawing['type'] not in ['line_segment', 'smartline', 'polyline', 'freehand', 'rectangle', 'polygon', 'circle']:
                    continue
                
                coords = drawing['coords']
                if len(coords) < 2:
                    continue
                
                print(f"   Checking {drawing['type']} with {len(coords)} points")
                
                # Check each line segment
                for i in range(len(coords) - 1):
                    p1 = np.array(coords[i])
                    p2 = np.array(coords[i + 1])
                    
                    # Find closest point on this segment to click position
                    point_on_segment, dist = self._closest_point_on_segment(click_world, p1, p2)
                    
                    # Convert to screen space for accurate distance check
                    screen_dist = self._world_to_screen_distance(point_on_segment, click_world)
                    
                    if screen_dist < min_distance:
                        print(f"      Segment {i}: distance = {screen_dist:.2f}px")
                    
                    if screen_dist < tolerance and screen_dist < min_distance:
                        min_distance = screen_dist
                        closest_drawing = drawing
                        closest_point = {
                            'coords': point_on_segment.tolist(),
                            'segment_index': i,
                            'distance': screen_dist
                        }
            
            if closest_drawing and closest_point:
                print(f"✅ Found {closest_drawing['type']} at distance {min_distance:.1f}px, segment {closest_point['segment_index']}")
                return closest_drawing, closest_point
            else:
                print(f"⚪ No line found within {tolerance}px tolerance")
            
            return None, None
            
        except Exception as e:
            print(f"⚠️ Error finding line: {e}")
            import traceback
            traceback.print_exc()
            return None, None
      
    def _closest_point_on_segment(self, point, seg_start, seg_end):
        """
        Find the closest point on a line segment to a given point.
        
        Returns:
            (closest_point, distance)
        """
        # Vector from seg_start to seg_end
        segment = seg_end - seg_start
        segment_length_sq = np.dot(segment, segment)
        
        if segment_length_sq == 0:
            # Degenerate segment (point)
            return seg_start, np.linalg.norm(point - seg_start)
        
        # Project point onto line segment
        # t = how far along the segment (0 = start, 1 = end)
        t = max(0, min(1, np.dot(point - seg_start, segment) / segment_length_sq))
        
        # Closest point on segment
        closest = seg_start + t * segment
        distance = np.linalg.norm(point - closest)
        
        return closest, distance
    
    
    def _world_to_screen_distance(self, world_pos1, world_pos2):
        """
        Calculate distance between two world points in screen pixels.
        More accurate for user interaction than world-space distance.
        """
        try:
            # Convert first point to screen
            self.renderer.SetWorldPoint(world_pos1[0], world_pos1[1], world_pos1[2], 1.0)
            self.renderer.WorldToDisplay()
            screen1 = self.renderer.GetDisplayPoint()
            
            # Convert second point to screen
            self.renderer.SetWorldPoint(world_pos2[0], world_pos2[1], world_pos2[2], 1.0)
            self.renderer.WorldToDisplay()
            screen2 = self.renderer.GetDisplayPoint()
            
            # Calculate 2D screen distance
            dx = screen2[0] - screen1[0]
            dy = screen2[1] - screen1[1]
            return np.sqrt(dx*dx + dy*dy)
            
        except Exception:
            # Fallback to world distance
            return np.linalg.norm(np.array(world_pos1) - np.array(world_pos2))
    
    
    def _insert_vertex_at_point(self, drawing, insertion_point):
        """
        Insert a new vertex into an existing line, splitting it into two segments.
        Optionally enables dragging for the new vertex based on vertex_auto_drag setting.
        
        Args:
            drawing: The drawing dict to modify
            insertion_point: Dict with 'coords', 'segment_index', 'distance'
        """
        try:
            self._save_state() 
            new_vertex = insertion_point['coords']
            segment_idx = insertion_point['segment_index']
            
            print(f"📍 Inserting vertex at segment {segment_idx}: {new_vertex}")
            
            coords = drawing['coords']
            drawing_type = drawing.get('type')
            
            new_vertex_tuple = tuple(new_vertex)
            target_drawing = None
            target_vertex_idx = None
            
            # ✅ HANDLE LINE_SEGMENT: Split into TWO independent segments
            if drawing_type == 'line_segment':
                # Get the original segment endpoints
                p1 = coords[0]
                p2 = coords[-1]
                
                # ✅ ENHANCED CLEANUP: Remove the original segment completely
                if 'actor' in drawing and drawing['actor']:
                    try:
                        self._remove_actor_from_overlay(drawing['actor'])
                        drawing['actor'].VisibilityOff()
                    except Exception:
                        pass
                    drawing['actor'] = None
                
                # Remove old markers
                for marker_key in ['start_marker', 'end_marker']:
                    if marker_key in drawing and drawing[marker_key]:
                        try:
                            self._remove_actor_from_overlay(drawing[marker_key])
                            drawing[marker_key].VisibilityOff()
                        except Exception:
                            pass
                        drawing[marker_key] = None
                
                # Remove from drawings list
                try:
                    self.drawings.remove(drawing)
                    print("  🗑️ Removed original segment from drawings list")
                except ValueError:
                    print("  ⚠️ Original segment not found in drawings list")
                
                # ✅ FORCE RENDER before creating new segments
                self.renderer.Modified()
                self.app.vtk_widget.render()
                
                # ✅ CREATE SEGMENT 1: p1 → new_vertex
                coords_1 = [p1, new_vertex_tuple]
                actor_1 = self._make_polyline_actor(coords_1, color=(1, 0, 0), width=2)
                actor_1.PickableOn()
                actor_1.SetPickable(1)
                self._add_actor_to_overlay(actor_1)
                
                start_marker_1 = self._add_endpoint_sphere(coords_1[0], color=(0, 1, 0), radius=0.05)
                end_marker_1 = self._add_endpoint_sphere(coords_1[1], color=(1, 1, 0), radius=0.05)  # Yellow (shared)
                
                segment_1 = {
                    "type": "line_segment",
                    "coords": coords_1,
                    "actor": actor_1,
                    "bounds": actor_1.GetBounds(),
                    "start_marker": start_marker_1,
                    "end_marker": end_marker_1,
                    "original_color": (1, 0, 0),
                    "original_width": 2
                }
                self.drawings.append(segment_1)
                
                # ✅ CREATE SEGMENT 2: new_vertex → p2
                coords_2 = [new_vertex_tuple, p2]
                actor_2 = self._make_polyline_actor(coords_2, color=(1, 0, 0), width=2)
                actor_2.PickableOn()
                actor_2.SetPickable(1)
                self._add_actor_to_overlay(actor_2)
                
                start_marker_2 = self._add_endpoint_sphere(coords_2[0], color=(1, 1, 0), radius=0.05)  # Yellow (shared)
                end_marker_2 = self._add_endpoint_sphere(coords_2[1], color=(1, 0, 0), radius=0.05)
                
                segment_2 = {
                    "type": "line_segment",
                    "coords": coords_2,
                    "actor": actor_2,
                    "bounds": actor_2.GetBounds(),
                    "start_marker": start_marker_2,
                    "end_marker": end_marker_2,
                    "original_color": (1, 0, 0),
                    "original_width": 2
                }
                self.drawings.append(segment_2)
                
                print(f"✅ Line segment SPLIT into 2 segments:")
                print(f"   Segment 1: {coords_1}")
                print(f"   Segment 2: {coords_2}")
                
                # Store reference for optional drag mode
                target_drawing = segment_1
                target_vertex_idx = 1  # The end point of segment_1 (the new vertex)
            
            # ✅ HANDLE SMARTLINE/POLYLINE/FREEHAND: Add vertex to existing multi-vertex line
            elif drawing_type in ['smartline', 'line', 'polyline', 'freehand']:
                # Insert new vertex into coordinates list
                new_vertex_idx = segment_idx + 1
                coords.insert(new_vertex_idx, new_vertex_tuple)
                
                # ✅ ENHANCED CLEANUP: Remove ALL old geometry systematically
                # 1. Remove main actor
                if 'actor' in drawing and drawing['actor']:
                    try:
                        self._remove_actor_from_overlay(drawing['actor'])
                        drawing['actor'].VisibilityOff()
                    except Exception as e:
                        print(f"  ⚠️ Failed to remove main actor: {e}")
                    drawing['actor'] = None
                
                # 2. Remove ALL vertex markers
                if 'vertex_markers' in drawing and drawing['vertex_markers']:
                    for marker in drawing['vertex_markers']:
                        try:
                            self._remove_actor_from_overlay(marker)
                            marker.VisibilityOff()
                        except Exception:
                            pass
                    drawing['vertex_markers'] = []
                
                # 3. Remove arrows if present
                if 'arrow_actor' in drawing and drawing['arrow_actor']:
                    arrows = drawing['arrow_actor']
                    if not isinstance(arrows, list):
                        arrows = [arrows]
                    for arr in arrows:
                        try:
                            self.renderer.RemoveActor2D(arr)
                            arr.VisibilityOff()
                        except Exception:
                            pass
                    drawing['arrow_actor'] = None
                
                # ✅ FORCE RENDER PIPELINE FLUSH before creating new geometry
                self.renderer.Modified()
                self.app.vtk_widget.render()
                
                # Recreate actor with new geometry
                color = drawing.get('original_color', (1, 0, 0))
                width = drawing.get('original_width', 2)
                new_actor = self._make_polyline_actor(coords, color=color, width=width)
                
                # ✅ CRITICAL: Ensure new actor is pickable and visible
                new_actor.PickableOn()
                new_actor.VisibilityOn()
                new_actor.SetPickable(1)
                
                # Update drawing
                drawing['actor'] = new_actor
                drawing['coords'] = coords
                drawing['bounds'] = new_actor.GetBounds()
                
                # Add new actor to renderer
                self._add_actor_to_overlay(new_actor)
                
                # CREATE PERMANENT VERTEX MARKERS
                drawing['vertex_markers'] = []
                
                for i, pt in enumerate(coords):
                    if i == 0:
                        marker_color = (0, 1, 0)  # Green start
                    elif i == len(coords) - 1:
                        marker_color = (1, 0, 0)  # Red end
                    else:
                        marker_color = (1, 1, 0)  # Yellow middle
                    
                    marker = self._add_endpoint_sphere(pt, color=marker_color, radius=0.05)
                    marker.GetProperty().SetOpacity(0.8)
                    drawing['vertex_markers'].append(marker)
                
                print(f"✅ Vertex inserted! Line now has {len(coords)} points")
                
                # Store reference for optional drag mode
                target_drawing = drawing
                target_vertex_idx = new_vertex_idx
            
            # ✅ FORCE COMPLETE RENDER before optional drag mode
            self.renderer.Modified()
            self.app.vtk_widget.interactor.GetRenderWindow().Render()
            self.app.vtk_widget.render()
            
            # ✅ CONDITIONAL: Enable drag mode ONLY if setting is enabled
            if getattr(self, 'vertex_auto_drag', False) and target_drawing and target_vertex_idx is not None:
                self.dragging_vertex = {
                    'drawing': target_drawing,
                    'vertex_index': target_vertex_idx,
                    'original_pos': new_vertex_tuple
                }
                
                # Create drag marker
                if hasattr(self, 'vertex_drag_marker') and self.vertex_drag_marker:
                    try:
                        self._remove_actor_from_overlay(self.vertex_drag_marker)
                    except Exception:
                        pass
                
                self.vertex_drag_marker = self._add_endpoint_sphere(
                    new_vertex_tuple, color=(1, 1, 0), radius=0.12
                )
                
                print("🖱️ Drag mode enabled - move mouse to reposition, click to place")
            else:
                print("✅ Vertex inserted (insert-only mode)")
            
        except Exception as e:
            print(f"❌ Failed to insert vertex: {e}")
            import traceback
            traceback.print_exc()
        
        
    def _on_middle_press(self, obj, evt):
        """Start panning - always works, even during drawing."""
        print("🖱️ Middle button PRESSED - starting pan")
        
        self._consume_vtk_event(obj)
        self.middle_down = True
        self._is_panning = True
        self._pan_start_pos = self.interactor.GetEventPosition()
        self._last_pos = None
        # Allow VTK's built-in pan to also handle this
        style = self.interactor.GetInteractorStyle()
        if hasattr(style, "OnMiddleButtonDown"):
            style.OnMiddleButtonDown()
        
        # ✅ NEW: Ensure release handler has HIGH priority
        self.interactor.RemoveObservers("MiddleButtonReleaseEvent")
        self.interactor.AddObserver("MiddleButtonReleaseEvent", self._on_middle_release, 10.0)
        
        
    def _reset_pan_state(self):
        """Emergency reset for stuck pan state - can be called manually"""
        self.middle_down = False
        self._is_panning = False
        self._pan_start_pos = None
        print("🔄 Pan state forcibly reset")

    def _on_middle_release(self, obj, evt):
        """Stop panning IMMEDIATELY when button is released."""
        self._consume_vtk_event(obj)
        if not self._is_panning:
            return
            
        print("🛑 Middle button RELEASED - stopping pan NOW")
        
        self.middle_down = False
        self._is_panning = False
        self._pan_start_pos = None
        
        style = self.interactor.GetInteractorStyle()
        if hasattr(style, "OnMiddleButtonUp"):
            style.OnMiddleButtonUp()
        
        # ✅ Refresh preview lines after pan moved camera
        if self.temp_points and self.active_tool:
            try:
                from PySide6.QtCore import QTimer
            except ImportError:
                from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, self._deferred_preview_update)
        
        print("✅ Pan stopped")
            
    def debug_pan_state(self):
        """Debug helper to check pan state - call from console if needed"""
        print(f"🔍 Pan State Debug:")
        print(f"   middle_down: {self.middle_down}")
        print(f"   _is_panning: {self._is_panning}")
        print(f"   _pan_start_pos: {self._pan_start_pos}")
        print(f"   active_tool: {self.active_tool}")
        
        # Try auto-fix if stuck
        if self._is_panning and not self.middle_down:
            print("   ⚠️ STUCK STATE DETECTED - Auto-fixing...")
            self._reset_pan_state()

    def _on_mouse_move(self, obj, evt):
        """Show rubber-band preview line as you move mouse."""
        if not self.enabled:
            if not getattr(self, "active_tool", None) or not getattr(self, "is_drawing_freehand", False):
                return
            return

        if self._is_panning or self.dragging_vertex or self.active_tool:
            self._consume_vtk_event(obj)

        # Pan state guard
        if self._is_panning:
            if not self.middle_down:
                self._is_panning = False
                self._pan_start_pos = None
                self.app.vtk_widget.render()
                return

        # Vertex dragging
        if self.dragging_vertex:
            new_pos = self._get_mouse_world()
            drawing = self.dragging_vertex['drawing']
            vertex_idx = self.dragging_vertex['vertex_index']
            coords = drawing['coords']
            coords[vertex_idx] = tuple(new_pos)
            if self.vertex_drag_marker:
                self.vertex_drag_marker.SetPosition(*new_pos)
            self._rebuild_drawing_actor(drawing)
            if self.selected_drawing is drawing:
                self.clear_coordinate_labels()
                self.show_vertex_coordinates(coords)
            self.app.vtk_widget.render()
            return

        # Panning
        if self._is_panning:
            if not self._pan_start_pos:
                self.middle_down = False
                self._is_panning = False
                return
            style = self.interactor.GetInteractorStyle()
            if style and hasattr(style, "OnMouseMove"):
                style.OnMouseMove()
            self.app.vtk_widget.render()
            return   ####

        # --- FREEHAND CONTINUOUS DRAWING ---
        if self.active_tool == "freehand" and getattr(self, "left_down", False) and getattr(self, "is_drawing_freehand", False):
            world_pos = self._get_mouse_world_no_snap()
            dist_px = 999
            if self.temp_points:
                dist_px = self._world_to_screen_distance(world_pos, self.temp_points[-1])
            if len(self.temp_points) == 0 or dist_px > 2.0:
                self.temp_points.append(world_pos)
                if len(self.temp_points) >= 2:
                    fh_style = self._get_draw_style('freehand')
                    self._update_freehand_preview_world(
                        color=fh_style['color'],
                        width=fh_style['width'],
                        line_style=fh_style['style'],
                    )
                self.app.vtk_widget.render()
            return

        # --- SMARTLINE ---
        if self.active_tool == "smartline" and len(self.temp_points) >= 1:
            mouse_x, mouse_y = self.interactor.GetEventPosition()
            sl_style = self._get_draw_style('smartline')

            # Continuous line through all placed points
            if len(self.temp_points) >= 2:
                self._update_continuous_preview(
                    color=sl_style['color'],
                    width=sl_style['width'],
                    line_style=sl_style['style'],
                )

            self._update_cursor_preview(
                color=sl_style['color'],
                width=sl_style['width'],
                line_style=sl_style['style'],
            )
            self.app.vtk_widget.render()
            return

        # --- LINE ---
        if self.active_tool == "line" and len(self.temp_points) >= 1:
            mouse_x, mouse_y = self.interactor.GetEventPosition()
            ln_style = self._get_draw_style('line')

            if len(self.temp_points) >= 2:
                self._update_continuous_preview(
                    color=ln_style['color'],
                    width=ln_style['width'],
                    line_style=ln_style['style'],
                )

            self._update_cursor_preview(
                color=ln_style['color'],
                width=ln_style['width'],
                line_style=ln_style['style'],
            )
            self.app.vtk_widget.render()
            return

        # --- RECTANGLE PREVIEW ---
        if self.active_tool == "rectangle" and len(self.temp_points) == 1:
            rc_style = self._get_draw_style('rectangle')
            self._update_rectangle_preview(
                color=rc_style['color'],
                width=rc_style['width'],
                line_style=rc_style['style'],
            )
            self.app.vtk_widget.render()
            return

        # --- CIRCLE PREVIEW ---
        if self.active_tool == "circle" and len(self.temp_points) == 1:
            ci_style = self._get_draw_style('circle')
            self._update_circle_preview_world(
                color=ci_style['color'],
                width=ci_style['width'],
                line_style=ci_style['style'],
            )
            self.app.vtk_widget.render()
            return

        # --- POLYLINE ---
        if self.active_tool == "polyline" and len(self.temp_points) >= 1:
            mouse_x, mouse_y = self.interactor.GetEventPosition()
            pl_style = self._get_draw_style('polyline')

            if len(self.temp_points) >= 2:
                self._update_continuous_preview(
                    color=pl_style['color'],
                    width=pl_style['width'],
                    line_style=pl_style['style'],
                )

            self._update_cursor_preview(
                color=pl_style['color'],
                width=pl_style['width'],
                line_style='dotted',
                close_loop=True,
            )
            self.app.vtk_widget.render()
            return

            # --- MOVE SELECTED ACTOR ---
        if getattr(self, "move_mode", False) and getattr(self, "selected", None) and self.left_down and not self._is_panning:
            pos = self._get_mouse_world()
            if not hasattr(self, "_last_pos") or self._last_pos is None:
                self._last_pos = pos
            delta = np.array(pos) - np.array(self._last_pos)
            self._last_pos = pos
            self._translate_selected(delta)
            self.app.vtk_widget.render()
            return

            
            
    def _on_left_release(self, obj, evt):
        """Finalize freehand and deactivate cleanly."""
        if not self.enabled:
            return
        
        # ✅ NEW: Finish vertex dragging from INSERT mode
        self._consume_vtk_event(obj)
        if self.dragging_vertex and self.active_tool == "vertex":
            drawing = self.dragging_vertex['drawing']
            vertex_idx = self.dragging_vertex['vertex_index']
            new_pos = drawing['coords'][vertex_idx]
            
            print(f"✅ Vertex {vertex_idx} placed at {new_pos} (auto-drag mode)")
            
            if self.vertex_drag_marker:
                self._remove_actor_from_overlay(self.vertex_drag_marker)
                self.vertex_drag_marker = None
            
            self._rebuild_drawing_actor(drawing)
            self.dragging_vertex = None
            self.app.vtk_widget.render()
            
            self.left_down = False
            self._last_pos = None 
            return
        
        # ✅ Existing: Finish vertex dragging from SHIFT+CLICK mode
        if self.dragging_vertex:
            drawing = self.dragging_vertex['drawing']
            vertex_idx = self.dragging_vertex['vertex_index']
            new_pos = drawing['coords'][vertex_idx]
            
            print(f"✅ Vertex {vertex_idx} moved to {new_pos}")
            
            if self.vertex_drag_marker:
                self._remove_actor_from_overlay(self.vertex_drag_marker)
                self.vertex_drag_marker = None
            
            self._rebuild_drawing_actor(drawing)
            self.dragging_vertex = None
            self.app.vtk_widget.render()
            
            self.left_down = False
            return
            
        # Reset left mouse button state
        self.left_down = False

        # 3. FREEHAND: PAUSE LOGIC (Replaced the old Finalization logic)
        # ======================= FREEHAND PAUSE (DO NOT FINISH) =======================
        if self.active_tool == "freehand" and getattr(self, "is_drawing_freehand", False):
            # Just pause recording. Do NOT clear points. Do NOT finalize.
            self.is_drawing_freehand = False
            print("⏸️ Freehand PAUSED. (Left-drag to continue, Right-click to finish)")
            return

        # -------------------- Other Tools (unchanged) --------------------
        if self.active_tool == "rectangle" and len(self.temp_points) == 2:
            self._finalize_rectangle()
            return
        if self.active_tool == "circle" and len(self.temp_points) == 2:
            self._finalize_circle()
            return
        if self.active_tool == "polygon" and len(self.temp_points) >= 3:
            print("ℹ️ Polygon still active (awaiting right-click to finalize).")
            return
        
    def test_pan_functionality(self):
        """
        Quick test to verify pan works.
        Call this after activating a drawing tool.
        """
        print("\n" + "="*60)
        print("🧪 PAN FUNCTIONALITY TEST")
        print("="*60)
        print(f"Active tool: {self.active_tool}")
        print(f"Interactor style: {self.interactor.GetInteractorStyle()}")
        print(f"Ctrl key check works: {self.interactor.GetControlKey()}")
        print("\n📋 INSTRUCTIONS:")
        print("1. Hold Ctrl key")
        print("2. Click and drag with left mouse")
        print("3. View should pan without adding points")
        print("4. Release Ctrl")
        print("5. Click again - point should be added")
    
   

    def _handle_right_click_selection(self):
        """
        Robust Selection Handler.
        """
        x, y = self.interactor.GetEventPosition()
        shift_held = self.interactor.GetShiftKey()

        picked_drawing = None

        # --- STEP 1: Try Hardware Picking (Fast, good for text/labels) ---
        actor = self._pick_actor(x, y)
        if actor:
            for d in self.drawings:
                if d.get("actor") is actor:
                    picked_drawing = d
                    break
        
        # --- STEP 2: Force Math Picker if Hardware failed ---
        if not picked_drawing:
            picked_drawing = self._get_drawing_under_cursor(x, y, tolerance=25.0)

        # --- STEP 3: Apply Selection ---
        if picked_drawing:
            # TEXT EDITING (Selection only, Edit is in right-click Context Menu)
            if picked_drawing["type"] == "text":
                self.clear_coordinate_labels()
                self._unhighlight_all_lines()
                self.multi_selected = []
                self.selected_drawing = picked_drawing
                self.renderer.Modified()
                self.app.vtk_widget.render()
                return

            # SHAPE SELECTION
            if self.selected_drawing is picked_drawing and not shift_held:
                # Toggle Off
                self._unhighlight_line(picked_drawing)
                self.clear_coordinate_labels()
                self.selected_drawing = None
            elif shift_held:
                # Multi-Select
                if picked_drawing not in self.multi_selected:
                    self.multi_selected.append(picked_drawing)
                    self._highlight_line(picked_drawing)
                else:
                    self.multi_selected.remove(picked_drawing)
                    self._unhighlight_line(picked_drawing)
                self.selected_drawing = None
            else:
                # Single Select (The most common case)
                self.clear_coordinate_labels()
                self._unhighlight_all_lines()
                self.multi_selected = []
                self.selected_drawing = picked_drawing
                self._highlight_line(picked_drawing)
                
                # Show vertices if available
                if "coords" in picked_drawing:
                    self.show_vertex_coordinates(picked_drawing["coords"])
            
            self.renderer.Modified()
            self.app.vtk_widget.render()
            return

        # --- STEP 4: Deselect All (Clicked Empty Space) ---
        self.clear_coordinate_labels()
        self.selected_drawing = None
        self._unhighlight_all_lines()
        self.app.vtk_widget.render()
        

    def _on_key_press(self, obj, evt):
        """Handle key presses: delete, move, copy/paste, cancel, etc."""
        if not self.enabled:
            return

        key = self.interactor.GetKeySym().lower()
        
        # --- UNDO (Ctrl+Z) ---
        if key == "z" and self.interactor.GetControlKey():
            if getattr(self, "active_tool", None):
                self.undo()
                return

        # --- REDO (Ctrl+Y) ---
        elif key == "y" and self.interactor.GetControlKey():
            if getattr(self, "active_tool", None):
                self.redo()
                return

        # --- SHIFT+ESC: Exit permanent modes or active tools ---
        if key == "escape" and self.interactor.GetShiftKey():
            if self._deactivate_active_tool_keep_drawings():
                return

            # No active digitize tool: treat Shift+ESC as selection clear only.
            self.clear_coordinate_labels()
            self.selected_drawing = None
            self.selected_vertex_idx = None
            if hasattr(self, "multi_selected"):
                self.multi_selected = []
            if hasattr(self, "_vertex_highlight") and self._vertex_highlight:
                self._remove_actor_from_overlay(self._vertex_highlight)
                self._vertex_highlight = None
            self._unhighlight_all_lines()
            print("⚪ All selections cleared")
            self.app.vtk_widget.render()
            return

        # --- S KEY: Toggle snapping ---
        elif key == "s":
            self.snap_enabled = not self.snap_enabled
            state = "ON" if self.snap_enabled else "OFF"
            print(f"🧲 Snapping: {state}")

        # --- DELETE / BACKSPACE ---
        elif key in ("delete", "backspace"):
            self._save_state()
            pos = self._get_mouse_world()

            # === TEXT LABEL DELETE (single selection) ===
            if getattr(self, "selected_drawing", None) and self.selected_drawing.get("type") == "text":
                print(f"🗑️ Deleting text label: {self.selected_drawing.get('text', 'N/A')}")
                self._remove_drawing(self.selected_drawing)
                self.selected_drawing = None
                self.renderer.Modified()
                self.app.vtk_widget.render()
                print("✅ Text label deleted")
                return

            # === LINE SEGMENT DELETE ===
            if getattr(self, "selected_drawing", None) and self.selected_drawing.get("type") == "line_segment":
                d = self.selected_drawing
                print(f"🗑️ Deleting selected line segment: {d['coords']}")
                self._remove_drawing(d)
                self.selected_drawing = None
                self.clear_coordinate_labels()
                self.renderer.Modified()
                self.app.vtk_widget.render()
                print("✅ Line segment deleted")
                return

            # === FREEHAND DELETE ===
            if getattr(self, "selected_drawing", None) and self.selected_drawing.get("type") == "freehand":
                d = self.selected_drawing
                print(f"🗑️ Deleting selected freehand drawing ({len(d['coords'])} points)")
                self._remove_drawing(d)
                self.selected_drawing = None
                self.clear_coordinate_labels()
                self.renderer.Modified()
                self.app.vtk_widget.render()
                print("✅ Freehand drawing deleted")
                return

            # === POLYLINE DELETE ===
            if getattr(self, "selected_drawing", None) and self.selected_drawing.get("type") == "polyline":
                d = self.selected_drawing
                print(f"🗑️ Deleting selected polyline drawing ({len(d['coords'])} points)")
                self._remove_drawing(d)
                self.selected_drawing = None
                self.clear_coordinate_labels()
                self.renderer.Modified()
                self.app.vtk_widget.render()
                print("✅ Polyline drawing deleted")
                return

            # === MULTI-SELECTION DELETE ===
            if getattr(self, "multi_selected", []):
                print(f"🗑️ Multi-delete: {len(self.multi_selected)} selected drawings")

                for d in list(self.multi_selected):
                    if "coords" not in d:
                        continue

                    # Freehand: remove directly
                    if d["type"] == "freehand":
                        print("🗑️ Removing freehand from multi-selection")
                        self._remove_drawing(d)
                        continue

                    coords = d["coords"]
                    idx, dist = self._find_nearest_vertex(pos, coords, threshold=5.0)

                    if idx is not None:
                        print(f"✅ Removing vertex {idx} ({dist:.2f}) from {d['type']}")
                        del coords[idx]

                        if len(coords) < 2:
                            self._remove_drawing(d)
                            continue

                        # Rebuild actor
                        self._remove_actor_from_overlay(d["actor"])
                        new_actor = self._make_polyline_actor(coords)
                        self._add_actor_to_overlay(new_actor)
                        d["actor"] = new_actor
                        d["coords"] = coords
                        d["bounds"] = new_actor.GetBounds()

                        if d["type"] == "line":
                            for mk in ("start_marker", "end_marker"):
                                if mk in d and d[mk]:
                                    try:
                                        self._remove_actor_from_overlay(d[mk])
                                    except:
                                        pass
                                    d[mk] = None
                            start_pt, end_pt = coords[0], coords[-1]
                            d["start_marker"] = self._add_endpoint_sphere(start_pt, color=(0, 1, 0))
                            d["end_marker"] = self._add_endpoint_sphere(end_pt, color=(1, 0, 0))

                    else:
                        print(f"⚪ No nearby vertex — removing full {d['type']}")
                        self._remove_drawing(d)

                self.multi_selected = []
                self.clear_coordinate_labels()
                self.renderer.Modified()
                self.app.vtk_widget.render()
                print("✅ Multi-delete complete")
                return

            # === SINGLE SELECTION VERTEX DELETE ===
            if getattr(self, "selected_vertex_idx", None) is not None and self.selected_drawing:
                idx = self.selected_vertex_idx
                d = self.selected_drawing
                coords = d["coords"]

                print(f"🗑️ Deleting selected vertex {idx} from {d['type']}")
                del coords[idx]

                if len(coords) < 2:
                    self._remove_drawing(d)
                    self.selected_drawing = None
                    self.selected_vertex_idx = None
                    print("⚠️ Line too short, entire drawing removed.")
                else:
                    self._remove_actor_from_overlay(d["actor"])
                    new_actor = self._make_polyline_actor(coords)
                    self._add_actor_to_overlay(new_actor)
                    d["actor"] = new_actor
                    d["coords"] = coords
                    d["bounds"] = new_actor.GetBounds()

                    if d["type"] == "line":
                        for mk in ("start_marker", "end_marker"):
                            if mk in d and d[mk]:
                                try:
                                    self._remove_actor_from_overlay(d[mk])
                                except:
                                    pass
                                d[mk] = None
                        start_pt, end_pt = coords[0], coords[-1]
                        d["start_marker"] = self._add_endpoint_sphere(start_pt, color=(0, 1, 0))
                        d["end_marker"] = self._add_endpoint_sphere(end_pt, color=(1, 0, 0))

                    print("✅ Vertex deleted and line rebuilt.")

                self.clear_coordinate_labels()
                if d and len(coords) >= 2:
                    self.show_vertex_coordinates(coords)
                self.selected_vertex_idx = None
                self.renderer.Modified()
                self.app.vtk_widget.render()
                return

            # === FALLBACK: DELETE ENTIRE SELECTED DRAWING ===
            if getattr(self, "selected_drawing", None):
                d = self.selected_drawing
                print(f"🗑️ Removing full {d['type']} drawing")
                self._remove_drawing(d)
                self.selected_drawing = None
                self.clear_coordinate_labels()
                self.renderer.Modified()
                self.app.vtk_widget.render()
                print("✅ Entire drawing deleted")
                return

            print("⚪ Nothing selected to delete")
            return

        # --- MOVE MODE TOGGLE ---
        elif key == "m":
            self.move_mode = not getattr(self, "move_mode", False)
            print("🔄 Move mode:", self.move_mode)

        # --- COPY / PASTE ---
        elif key == "c" and self.interactor.GetControlKey():
            if hasattr(self, "_copy_selected"):
                self._copy_selected()
            else:
                print("⚠️ Copy not implemented")
        elif key == "v" and self.interactor.GetControlKey():
            if hasattr(self, "_paste_selected"):
                self._paste_selected()
            else:
                print("⚠️ Paste not implemented")

        # --- ESC: Exit move vertex mode or clear selections ---
        elif key == "escape":
            # Check if in move vertex mode
            if getattr(self, 'vertex_moving', False):
                self._deactivate_move_vertex_mode()
                self.active_tool = None
                try:
                    self.app.statusBar().showMessage("Move Vertex mode exited")
                except:
                    pass
                return
            
            # Normal selection clearing
            self.clear_coordinate_labels()
            self.selected_drawing = None
            self.selected_vertex_idx = None
            if hasattr(self, "multi_selected"):
                self.multi_selected = []
            if hasattr(self, "_vertex_highlight") and self._vertex_highlight:
                self._remove_actor_from_overlay(self._vertex_highlight)
                self._vertex_highlight = None
            self._unhighlight_all_lines()
            print("⚪ All selections cleared")

        # --- E KEY: Edit selected drawing (text or line) ---
        elif key == "e":
            if getattr(self, "selected_drawing", None):
                drawing_type = self.selected_drawing.get("type")
                
                # Text editing
                if drawing_type == "text":
                    self._edit_text_label(self.selected_drawing)
                    return
                
                # Line/SmartLine/Polyline/Freehand editing
                elif drawing_type in ("line_segment", "smartline", "polyline", "freehand", "rectangle", "circle", "polygon"):
                    self._edit_line_properties(self.selected_drawing)
                    return
                
                else:
                    print(f"ℹ️ Editing not supported for {drawing_type}")
            else:
                print("⚠️ No drawing selected - right-click on a line first")


    # ---------------- SELECTION HIGHLIGHTING ----------------
    def _highlight_line(self, drawing):
        """Highlight selected line segment."""
        if "actor" not in drawing:
            return
        
        prop = drawing["actor"].GetProperty()
        
        # ✅ CRITICAL: Save original color and width BEFORE changing
        if "original_color" not in drawing:
            drawing["original_color"] = prop.GetColor()
        if "original_width" not in drawing:
            drawing["original_width"] = prop.GetLineWidth()
        
        # Apply cyan highlight (Must be floats)
        prop.SetColor(0.0, 1.0, 1.0)   # Cyan highlight
        prop.SetLineWidth(5)
        
        # ✅ FORCE PIPELINE UPDATE
        drawing["actor"].Modified() 
        print(f"✨ Highlighted: saved original color {drawing['original_color']}")

    def _unhighlight_line(self, drawing=None):
        """Restore the line to its original appearance."""
        target = drawing if drawing is not None else getattr(self, "selected_drawing", None)
        
        if target is None or "actor" not in target:
            return
        
        prop = target["actor"].GetProperty()
        
        # Restore original properties
        if "original_color" in target:
            prop.SetColor(*target["original_color"])
        else:
            prop.SetColor(1.0, 0.0, 0.0)  # Default red
        
        if "original_width" in target:
            prop.SetLineWidth(target["original_width"])
        else:
            prop.SetLineWidth(2)  # Default width
            
        # ✅ FORCE PIPELINE UPDATE
        target["actor"].Modified()
        print(f"🔄 Line unhighlighted: restored to original appearance")

    def _remove_drawing(self, drawing):
        """
        ✅ BULLETPROOF: Completely remove a drawing and ALL associated geometry.
        Includes state-desync prevention to guarantee zero memory leaks.
        """
        try:
            print(f"🧹 Commencing full deletion of: {drawing.get('type', 'unknown')}")
            
            # 🛑 0️⃣ STATE DESYNC PREVENTION (THE FIX) 🛑
            if getattr(self, "selected_drawing", None) is drawing:
                self.clear_coordinate_labels()
                self.selected_drawing = None

            if hasattr(self, "multi_selected") and drawing in self.multi_selected:
                self.multi_selected.remove(drawing)
                
            if getattr(self, "selected", None) is drawing:
                self._clear_selection()
                self.selected = None

            # --- 1️⃣ Remove the main actor ---
            if "actor" in drawing and drawing["actor"]:
                if drawing.get("type") == "text":
                    if drawing.get("scalable", False):
                        # Scalable text lives in overlay renderer
                        self._remove_actor_from_overlay(drawing["actor"])
                    else:
                        # Legacy billboard text
                        try: self.renderer.RemoveViewProp(drawing["actor"])
                        except: pass
                    # Safety net
                    try: self._remove_actor_from_overlay(drawing["actor"])
                    except: pass
                else:
                    self._remove_actor_from_overlay(drawing["actor"])

            # --- 2️⃣ Remove standard markers ---
            for key in ("start_marker", "end_marker"):
                if key in drawing and drawing[key]:
                    try: self._remove_actor_from_overlay(drawing[key])
                    except: pass
                    drawing[key] = None

            # --- 3️⃣ Remove explicitly linked vertex markers ---
            if "vertex_markers" in drawing and drawing["vertex_markers"]:
                for marker in drawing["vertex_markers"]:
                    try: self._remove_actor_from_overlay(marker)
                    except: pass
                drawing["vertex_markers"] = []
            
            # --- 4️⃣ Remove 2D arrow overlays ---
            if "arrow_actor" in drawing and drawing["arrow_actor"]:
                arrows = drawing["arrow_actor"]
                if not isinstance(arrows, list): arrows = [arrows]
                for arr in arrows:
                    try: self.renderer.RemoveActor2D(arr)
                    except: pass
                drawing["arrow_actor"] = None

            # --- 5️⃣ Remove from list ---
            if drawing in self.drawings:
                self.drawings.remove(drawing)

            # --- 6️⃣ Rebuild remaining segment connections ---
            if hasattr(self, '_refresh_segment_markers'):
                self._refresh_segment_markers()
                
            self.renderer.Modified()
            print(f"✅ Drawing and all associated geometry purged.")

        except Exception as e:
            print(f"⚠️ Error while removing drawing: {e}")
            import traceback
            traceback.print_exc()

    def _capture_state_snapshot(self):
        """Capture drawings with the properties needed for undo/redo restoration."""
        state = []
        for d in self.drawings:
            drawing_copy = {
                'type': d['type'],
                'coords': list(d['coords']),
                'text': d.get('text', ''),
                'original_color': d.get('original_color', (1, 0, 0)),
                'original_width': d.get('original_width', 2),
                'original_style': d.get('original_style', 'solid'),
                'original_text_color': d.get('original_text_color', (1, 1, 1)),
                'font_size': d.get('font_size', 18),
                'bold': d.get('bold', True),
                'font_family': d.get('font_family', 'Arial'),
                'justify': d.get('justify', 'center'),
                'scalable': d.get('scalable', False),
                'center': d.get('center', None),
                'radius': d.get('radius', None),
                'has_arrow': bool(d.get('arrow_actor')),
            }
            state.append(drawing_copy)
        return state

    def _save_state(self):
        """Save current state to undo stack with full properties."""
        self.undo_stack.append(self._capture_state_snapshot())
        
        if len(self.undo_stack) > self.max_undo_levels:
            self.undo_stack.pop(0)
        
        self.redo_stack = []
        print(f"💾 State saved (undo stack: {len(self.undo_stack)})")            

    def _push_temp_vertex_history(self):
        """Store the current in-progress vertex state before adding a new point."""
        if not hasattr(self, "_temp_vertex_stack"):
            self._temp_vertex_stack = []
        if not hasattr(self, "_temp_redo_stack"):
            self._temp_redo_stack = []
        self._temp_vertex_stack.append(list(self.temp_points))
        # Cap temp stacks to prevent unbounded growth during long drawing sessions
        if len(self._temp_vertex_stack) > self.max_undo_levels:
            self._temp_vertex_stack.pop(0)
        self._temp_redo_stack = []

    def _clear_temp_vertex_history(self):
        """Drop any in-progress undo/redo history for active line-based tools."""
        self._temp_vertex_stack = []
        self._temp_redo_stack = []

    def _get_active_vertex_marker_attr(self):
        return {
            "smartline": "_smartline_vertex_markers",
            "line": "_line_vertex_markers",
            "polyline": "_polyline_vertex_markers",
        }.get(self.active_tool)

    def _rebuild_active_vertex_markers(self):
        """Recreate in-progress vertex markers after temp undo/redo changes."""
        marker_attr = self._get_active_vertex_marker_attr()
        if not marker_attr:
            return

        markers = getattr(self, marker_attr, [])
        for marker in markers:
            try:
                self._remove_actor_from_overlay(marker)
            except Exception:
                pass

        rebuilt_markers = []
        radius = 0.20 if self.active_tool == "smartline" else 0.05
        for idx, pt in enumerate(self.temp_points):
            color = (0, 1, 0) if idx == 0 else (1, 1, 0)
            marker = self._add_endpoint_sphere(pt, color=color, radius=radius)
            try:
                marker.GetProperty().SetOpacity(0.8)
            except Exception:
                pass
            rebuilt_markers.append(marker)

        setattr(self, marker_attr, rebuilt_markers)

    def _restore_state(self, state):
        """Restore drawings from a saved state - recreates ALL drawing types."""
        # ✅ FIX: Remove 2D preview actors
        self._remove_preview_actor_2d('_continuous_line_actor')
        self._remove_preview_actor_2d('_preview_line_actor')
        self._remove_preview_actor_2d('_rectangle_preview_actor')
        self._remove_preview_actor_2d('_preview_actor')

        # Reset temp drawing state
        self.temp_points = []
        self.selected = None
        self.selected_drawing = None
        self._last_pos = None
        self.left_down = False
        self._clear_temp_vertex_history()

        # ✅ Clear all active in-progress vertex markers
        for attr in ['_smartline_vertex_markers', '_polyline_vertex_markers', '_line_vertex_markers']:
            markers = getattr(self, attr, [])
            for marker in markers:
                try:
                    self._remove_actor_from_overlay(marker)
                except Exception:
                    pass
            setattr(self, attr, [])

        # --- Remove existing drawing actors ---
        for d in list(self.drawings):
            try:
                if "actor" in d and d["actor"]:
                    if d.get("type") == "text":
                        if d.get("scalable", False):
                            self._remove_actor_from_overlay(d["actor"])
                        else:
                            try:
                                self.renderer.RemoveViewProp(d["actor"])
                            except:
                                pass
                            try:
                                self._remove_actor_from_overlay(d["actor"])
                            except:
                                pass
                    else:
                        self._remove_actor_from_overlay(d["actor"])
                
                for key in ("start_marker", "end_marker"):
                    if key in d and d[key]:
                        try:
                            self._remove_actor_from_overlay(d[key])
                        except:
                            pass
                
                if "vertex_markers" in d and d["vertex_markers"]:
                    for marker in d["vertex_markers"]:
                        try:
                            self._remove_actor_from_overlay(marker)
                        except Exception:
                            pass
                
                if "arrow_actor" in d and d["arrow_actor"]:
                    arrows = d["arrow_actor"]
                    if not isinstance(arrows, list):
                        arrows = [arrows]
                    for arr in arrows:
                        try:
                            self.renderer.RemoveActor2D(arr)
                        except:
                            pass
            except Exception:
                pass
        self.drawings.clear()

        # --- ✅ FIX: Recreate ALL drawings from saved state ---
        for d in state:
            # ✅ SKIP any 'curve' entries to ensure isolation from curve tool
            if d.get('type') == 'curve':
                continue
                
            coords = d["coords"]
            color = d.get("original_color", (1, 0, 0))
            width = d.get("original_width", 2)
            line_style = d.get("original_style", "solid")
            dtype = d["type"]

            if dtype == "text":
                pos = coords[0]
                text = d.get("text", "Text")
                t_color = d.get("original_text_color", d.get("original_color", (1, 1, 1)))
                t_font_size = d.get("font_size", 18)
                t_bold = d.get("bold", True)
                t_font_family = d.get("font_family", "Arial")
                t_justify = d.get("justify", "center")
                
                actor = self._make_scalable_text_actor(
                    text=text,
                    position=pos,
                    color=t_color,
                    font_size=t_font_size,
                    bold=t_bold,
                    font_family=t_font_family,
                    justify=t_justify,
                )
                self._add_actor_to_overlay(actor)
                
                drawing_entry = {
                    "type": dtype,
                    "coords": coords,
                    "actor": actor,
                    "text": text,
                    "bounds": actor.GetBounds(),
                    "original_text_color": t_color,
                    "font_size": t_font_size,
                    "bold": t_bold,
                    "font_family": t_font_family,
                    "justify": t_justify,
                    "scalable": True,
                }
                self.drawings.append(drawing_entry)

            elif dtype == "line_segment":
                # ✅ Line segments get endpoint markers
                if len(coords) >= 2:
                    actor = self._make_polyline_actor(coords, color=color, width=width, line_style=line_style)
                    actor.PickableOn()
                    self._add_actor_to_overlay(actor)
                    arrow_actor = self._add_arrow_to_line(coords) if d.get("has_arrow", False) else None
                    
                    start_marker = self._add_endpoint_sphere(coords[0], color=(0, 1, 0), radius=0.05)
                    end_marker = self._add_endpoint_sphere(coords[-1], color=(1, 0, 0), radius=0.05)
                    
                    drawing_entry = {
                        "type": dtype,
                        "coords": list(coords),
                        "actor": actor,
                        "bounds": actor.GetBounds(),
                        "start_marker": start_marker,
                        "end_marker": end_marker,
                        "arrow_actor": arrow_actor,
                        "original_color": color,
                        "original_width": width,
                        "original_style": line_style,
                    }
                    self.drawings.append(drawing_entry)

            elif dtype in ("smartline", "line", "polyline", "freehand", "rectangle", "polygon", "circle"):
                # ✅ All geometry types get recreated with vertex markers
                if len(coords) >= 2:
                    actor = self._make_polyline_actor(coords, color=color, width=width, line_style=line_style)
                    actor.PickableOn()
                    self._add_actor_to_overlay(actor)
                    arrow_actor = None
                    if dtype in ("smartline", "line") and d.get("has_arrow", False):
                        arrow_actor = self._add_arrow_to_line(coords)
                    
                    # Create vertex markers
                    vertex_markers = []
                    for i, pt in enumerate(coords):
                        if i == 0:
                            marker_color = (0, 1, 0)   # Green start
                        elif i == len(coords) - 1:
                            marker_color = (1, 0, 0)    # Red end
                        else:
                            marker_color = (1, 1, 0)    # Yellow middle
                        
                        marker = self._add_endpoint_sphere(pt, color=marker_color, radius=0.05)
                        marker.GetProperty().SetOpacity(0.8)
                        vertex_markers.append(marker)
                    
                    drawing_entry = {
                        "type": dtype,
                        "coords": list(coords),
                        "actor": actor,
                        "bounds": actor.GetBounds(),
                        "vertex_markers": vertex_markers,
                        "arrow_actor": arrow_actor,
                        "original_color": color,
                        "original_width": width,
                        "original_style": line_style,
                    }
                    
                    # Preserve extra properties for circles
                    if dtype == "circle" and "center" in d:
                        drawing_entry["center"] = d["center"]
                        drawing_entry["radius"] = d["radius"]
                    
                    self.drawings.append(drawing_entry)

            else:
                # ✅ Fallback for any unknown type
                if len(coords) >= 2:
                    actor = self._make_polyline_actor(coords, color=color, width=width)
                    actor.PickableOn()
                    self._add_actor_to_overlay(actor)
                    
                    drawing_entry = {
                        "type": dtype,
                        "coords": list(coords),
                        "actor": actor,
                        "bounds": actor.GetBounds(),
                        "original_color": color,
                        "original_width": width,
                        "original_style": line_style,
                    }
                    self.drawings.append(drawing_entry)

        # ✅ Refresh segment markers for line_segments
        if any(d['type'] == 'line_segment' for d in self.drawings):
            try:
                self._refresh_segment_markers()
            except Exception:
                pass

        self.renderer.Modified()
        self.app.vtk_widget.render()
        print(f"✅ State restored: {len(self.drawings)} drawings recreated")

    def undo(self):
        """Undo last drawing operation (Ctrl+Z)."""

        # Per-vertex undo during active drawing
        if self.active_tool in ("smartline", "line", "polyline") and self.temp_points:
            if not hasattr(self, '_temp_redo_stack'):
                self._temp_redo_stack = []
            self._temp_redo_stack.append(list(self.temp_points))
            # Cap temp redo stack
            if len(self._temp_redo_stack) > self.max_undo_levels:
                self._temp_redo_stack.pop(0)

            if hasattr(self, '_temp_vertex_stack') and self._temp_vertex_stack:
                self.temp_points = list(self._temp_vertex_stack.pop())
            else:
                self.temp_points = []

            self._rebuild_active_vertex_markers()
            self._rebuild_active_preview()
            return

        # Drawing-level undo
        if not self.undo_stack:
            print("⚠️ Nothing to undo")
            return

        self.redo_stack.append(self._capture_state_snapshot())
        # Cap redo stack to same limit as undo
        if len(self.redo_stack) > self.max_undo_levels:
            self.redo_stack.pop(0)

        previous_state = self.undo_stack.pop()
        self._restore_state(previous_state)
        print(f"↶ Undo (undo stack: {len(self.undo_stack)}, redo stack: {len(self.redo_stack)})")


    def redo(self):
        """Redo previously undone operation (Ctrl+Y)."""
        if self.active_tool in ("smartline", "line", "polyline") and getattr(self, "_temp_redo_stack", None):
            if not hasattr(self, "_temp_vertex_stack"):
                self._temp_vertex_stack = []
            self._temp_vertex_stack.append(list(self.temp_points))
            self.temp_points = list(self._temp_redo_stack.pop())
            self._rebuild_active_vertex_markers()
            self._rebuild_active_preview()
            return
        if not self.redo_stack:
            print("⚠️ Nothing to redo")
            return

        self.undo_stack.append(self._capture_state_snapshot())
        # Cap undo stack
        if len(self.undo_stack) > self.max_undo_levels:
            self.undo_stack.pop(0)

        next_state = self.redo_stack.pop()
        self._restore_state(next_state)

        print(f"↷ Redo (undo stack: {len(self.undo_stack)}, redo stack: {len(self.redo_stack)})")



    def _unhighlight_all_lines(self):
        """Restore all highlighted lines to normal appearance."""
        if not hasattr(self, "multi_selected"):
            return
        for d in self.multi_selected:
            if "actor" in d:
                prop = d["actor"].GetProperty()
                prop.SetColor(1, 0, 0)
                prop.SetLineWidth(2)
            if d["type"] == "line":
                if "start_marker" in d:
                    d["start_marker"].GetProperty().SetColor(0, 1, 0)
                if "end_marker" in d:
                    d["end_marker"].GetProperty().SetColor(1, 0, 0)
        self.multi_selected = []



    def _find_nearest_vertex(self, pos, coords, threshold=10.0):
        """
        Finds the nearest vertex to the mouse click in screen space (2D), 
        ignoring Z depth — so works in 2D top view or 3D perspective reliably.
        """
        if not coords or not self.renderer or not self.interactor:
            return None, None

        min_dist = float("inf")
        nearest_idx = None

        # Get current display-space mouse position
        mouse_x, mouse_y = self.interactor.GetEventPosition()

        # Loop through vertices and project to display space
        for i, c in enumerate(coords):
            self.renderer.SetWorldPoint(c[0], c[1], c[2], 1.0)
            self.renderer.WorldToDisplay()
            disp_x, disp_y, _ = self.renderer.GetDisplayPoint()

            # Compare only X/Y (2D distance)
            dist = ((mouse_x - disp_x) ** 2 + (mouse_y - disp_y) ** 2) ** 0.5

            if dist < min_dist and dist < threshold:
                min_dist = dist
                nearest_idx = i

        if nearest_idx is not None:
            return nearest_idx, min_dist
        return None, None

     # ---------------- SMARTLINE HELPERS ----------------
    def _finalize_smart_line(self):
        self._save_state()
        if len(self.temp_points) < 2:
            return

        end_point = np.array(self.temp_points[-1])
        snap_target = None
        snap_distance = float('inf')
        snap_tolerance = 0.99

        for drawing in self.drawings:
            if 'coords' in drawing:
                for vertex in drawing["coords"]:
                    vertex_arr = np.array(vertex)
                    dist = np.linalg.norm(end_point - vertex_arr)
                    if dist < snap_tolerance and dist < snap_distance:
                        snap_distance = dist
                        snap_target = vertex_arr

        if len(self.temp_points) > 2:
            start_point = np.array(self.temp_points[0])
            dist_to_start = np.linalg.norm(end_point - start_point)
            if dist_to_start < snap_tolerance and dist_to_start < snap_distance:
                snap_target = start_point
                snap_distance = dist_to_start

        if snap_target is not None:
            self.temp_points[-1] = tuple(snap_target)
            if hasattr(self, '_smartline_vertex_markers') and self._smartline_vertex_markers:
                self._smartline_vertex_markers[-1].SetPosition(snap_target)
            if len(self.temp_points) < 2 or not np.allclose(snap_target, self.temp_points[-2]):
                self.temp_points.append(tuple(snap_target))

        if hasattr(self, '_smartline_vertex_markers') and self._smartline_vertex_markers:
            self._smartline_vertex_markers[-1].GetProperty().SetColor(1, 0, 0)

        # ✅ FIX: Remove 2D preview actors
        self._remove_preview_actor_2d('_preview_line_actor')
        self._remove_preview_actor_2d('_continuous_line_actor')

        sl_style = self._get_draw_style('smartline')
        sl_color = sl_style['color']
        sl_width = sl_style['width']
        sl_lstyle = sl_style['style']

        actor = self._make_polyline_actor(self.temp_points, color=sl_color, width=sl_width, line_style=sl_lstyle)
        actor.PickableOn()
        self._add_actor_to_overlay(actor)

        arrow_actor = None
        if getattr(self, 'smartline_arrow_mode', False):
            arrow_actor = self._add_arrow_to_line(self.temp_points)

        drawing_entry = {
            "type": "smartline",
            "coords": list(self.temp_points),
            "actor": actor,
            "bounds": actor.GetBounds(),
            "vertex_markers": list(self._smartline_vertex_markers) if hasattr(self, '_smartline_vertex_markers') else [],
            "arrow_actor": arrow_actor,
            "original_color": sl_color,
            "original_width": sl_width,
            "original_style": sl_lstyle,
        }
        self.drawings.append(drawing_entry)

        print(f"✅ SmartLine finalized: {len(self.temp_points)} vertices")
        self.temp_points = []
        self._smartline_vertex_markers = []
        self._clear_temp_vertex_history()
        if not getattr(self, 'smartline_permanent_mode', True):
            self.active_tool = None
        self.renderer.Modified()
        self.app.vtk_widget.render()
            
        
    def _finalize_line(self):
        if len(self.temp_points) < 2:
            return
        self._save_state()

        if hasattr(self, '_line_vertex_markers') and self._line_vertex_markers:
            self._line_vertex_markers[-1].GetProperty().SetColor(1, 0, 0)

        all_points = list(self.temp_points)
        self.temp_points = []

        # ✅ FIX: Remove 2D preview actors
        self._remove_preview_actor_2d('_preview_line_actor')
        self._remove_preview_actor_2d('_continuous_line_actor')

        ln_style = self._get_draw_style('line')
        ln_color = ln_style['color']
        ln_width = ln_style['width']
        ln_lstyle = ln_style['style']

        arrow_enabled = getattr(self, 'line_arrow_mode', False)

        for i in range(len(all_points) - 1):
            p1, p2 = all_points[i], all_points[i + 1]
            coords = [p1, p2]
            actor = self._make_polyline_actor(coords, color=ln_color, width=ln_width, line_style=ln_lstyle)
            self._add_actor_to_overlay(actor)

            arrow_actor = None
            if arrow_enabled:
                arrow_actor = self._add_arrow_to_line(coords)

            start_marker = self._line_vertex_markers[i] if i < len(self._line_vertex_markers) else None
            end_marker = self._line_vertex_markers[i + 1] if (i + 1) < len(self._line_vertex_markers) else None

            self.drawings.append({
                "type": "line_segment",
                "coords": coords,
                "actor": actor,
                "bounds": actor.GetBounds(),
                "start_marker": start_marker,
                "end_marker": end_marker,
                "arrow_actor": arrow_actor,
                "original_color": ln_color,
                "original_width": ln_width,
                "original_style": ln_lstyle,
            })

        # REPLACE WITH:
        self._line_vertex_markers = []
        self._clear_temp_vertex_history()
        if not getattr(self, 'line_permanent_mode', True):
            self.active_tool = None
        self.renderer.Modified()
        self.app.vtk_widget.render()
        print(f"✅ Created {len(all_points) - 1} independent line segments.")


    def _cancel_smart_line(self):
        # ✅ FIX: All preview actors are now 2D
        self._remove_preview_actor_2d('_preview_line_actor')
        self._remove_preview_actor_2d('_continuous_line_actor')

        if hasattr(self, "_line_start_marker") and self._line_start_marker:
            try:
                self._remove_actor_from_overlay(self._line_start_marker)
            except Exception:
                pass
            self._line_start_marker = None

        # Clear all in-progress vertex markers
        for attr in ['_smartline_vertex_markers', '_line_vertex_markers', '_polyline_vertex_markers']:
            markers = getattr(self, attr, [])
            for m in markers:
                try:
                    self._remove_actor_from_overlay(m)
                except Exception:
                    pass
            setattr(self, attr, [])

        self.temp_points = []
        self._clear_temp_vertex_history()
        self.app.vtk_widget.render()
        print("❌ Line/SmartLine cancelled")


    def _finalize_polyline(self):
        if len(self.temp_points) < 3:
            print("⚠️ Polyline needs at least 3 points")
            return
        self._save_state()

        if hasattr(self, '_polyline_vertex_markers') and self._polyline_vertex_markers:
            self._polyline_vertex_markers[-1].GetProperty().SetColor(1, 0, 0)

        all_points = list(self.temp_points)
        if not np.array_equal(all_points[0], all_points[-1]):
            all_points.append(all_points[0])
        self.temp_points = []

        # ✅ FIX: Remove 2D preview actors
        self._remove_preview_actor_2d('_preview_line_actor')
        self._remove_preview_actor_2d('_continuous_line_actor')

        pl_style = self._get_draw_style('polyline')
        pl_color = pl_style['color']
        pl_width = pl_style['width']
        pl_lstyle = pl_style['style']

        actor = self._make_polyline_actor(all_points, color=pl_color, width=pl_width, line_style=pl_lstyle)
        self._add_actor_to_overlay(actor)

        drawing_entry = {
            "type": "polyline",
            "coords": all_points,
            "actor": actor,
            "bounds": actor.GetBounds(),
            "vertex_markers": list(self._polyline_vertex_markers) if hasattr(self, '_polyline_vertex_markers') else [],
            "original_color": pl_color,
            "original_width": pl_width,
            "original_style": pl_lstyle,
        }
        self.drawings.append(drawing_entry)
        self._polyline_vertex_markers = []
        self._clear_temp_vertex_history()
        self.renderer.Modified()
        self.app.vtk_widget.render()
        print(f"✅ Polyline finalized: {len(all_points)} vertices (closed polygon)")

        if not getattr(self, 'polyline_permanent_mode', False):
            self.active_tool = None


    # ---------------- SELECTION / EDITING ----------------
    def _pick_actor(self, x, y):
        """
        Hybrid picker: supports both geometric and billboard/text actors.
        """
        actor = None
        
        # 1️⃣ Try PropPicker FIRST for text or billboard props
        self._prop_picker.Pick(x, y, 0, self.renderer)
        prop_actor = self._prop_picker.GetViewProp()
        if prop_actor and isinstance(prop_actor, vtk.vtkBillboardTextActor3D):
            print("🟡 Picked text/prop actor")
            return prop_actor
            
        # 2️⃣ Try CellPicker for geometric shapes
        self._cell_picker.Pick(x, y, 0, self.renderer)
        actor = self._cell_picker.GetActor()
        if actor:
            print("🎯 Picked geometry actor")
        else:
            print("⚪ Nothing picked (no geometry or text)")

        return actor


    def _select_actor(self, actor):
        self._clear_selection()
        self.selected = next((d for d in self.drawings if d["actor"] == actor), None)
        if not self.selected:
            return

        # Highlight line (only geometry has GetProperty, text has GetTextProperty and doesn't need line width changes)
        if hasattr(self.selected["actor"], "GetProperty"):
            prop = self.selected["actor"].GetProperty()
            if hasattr(prop, "SetLineWidth"):
                prop.SetLineWidth(5)
                prop.SetColor(0, 1, 1)

        self.selection_vertices = []

        for pt in self.selected["coords"]:
            marker = self._add_endpoint_sphere(pt, color=(1, 1, 0), radius=4.0)
            self.selection_vertices.append(marker)
        
        self.app.vtk_widget.render()

    def _clear_selection(self):
        if self.selected:
            prop = self.selected["actor"].GetProperty() if hasattr(self.selected["actor"], "GetProperty") else None
            if prop:
                prop.SetColor(1, 0, 0)
                prop.SetLineWidth(2)
        for v in getattr(self, "selection_vertices", []):
            try:
                self._remove_actor_from_overlay(v)
            except Exception:
                pass
        self.selection_vertices = []
        self.app.vtk_widget.render()


    def _translate_selected(self, delta):
        coords = [tuple(np.array(c) + delta) for c in self.selected["coords"]]
        self.selected["coords"] = coords
        self._remove_actor_from_overlay(self.selected["actor"])
        self.selected["actor"] = self._make_polyline_actor(coords)
        self._add_actor_to_overlay(self.selected["actor"])
        self.app.vtk_widget.render()

    def _delete_selected(self):
        try:
            self._remove_actor_from_overlay(self.selected["actor"])
            self.drawings.remove(self.selected)
            print("🗑️ Deleted selected vector")
        except Exception as e:
            print(f"⚠️ Delete failed: {e}")
        self.selected = None
        self.app.vtk_widget.render()

    def _copy_selected(self):
        if not self.selected:
            return
        new_coords = [tuple(np.array(c) + np.array([1, 1, 0])) for c in self.selected["coords"]]
        new_actor = self._make_polyline_actor(new_coords)
        self._add_actor_to_overlay(new_actor)
        copy = {"type": self.selected["type"], "coords": new_coords, "actor": new_actor}
        self.drawings.append(copy)
        self.app.vtk_widget.render()
        print("📄 Copied selected")
    

    def _make_polyline_actor(self, points, color=(1, 0, 0), width=2, line_style='solid'):
        """
        ✅ BULLETPROOF 3D LINE
        Uses 3D mapping so it pans correctly, but relies on OpenGL LineWidth 
        so thickness never scales with zoom.
        """
        if len(points) < 2: return None

        # 1. Geometry
        polydata = self._build_styled_polydata_world(points, line_style=line_style)

        # 2. 3D Mapper
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetResolveCoincidentTopologyPolygonOffsetParameters(-3, -3)

        # 3. 3D Actor
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        
        actor.GetProperty().SetColor(color)
        actor.GetProperty().SetLineWidth(width)

        self._apply_world_line_style(actor.GetProperty(), line_style=line_style)

        actor._digitize_overlay = True 
        
        return actor
    
    # ============================================================
    # ✅ THE FIX: Single source of truth for actor routing
    # ALL drawing actors go through overlay_renderer ONLY.
    # ============================================================

    def _add_actor_to_overlay(self, actor):
        """Add digitize actor to overlay renderer (always above point cloud)."""
        if hasattr(self, 'overlay_renderer') and self.overlay_renderer:
            self.overlay_renderer.AddActor(actor)
        else:
            self.renderer.AddActor(actor)   # fallback

    def _remove_actor_from_overlay(self, actor):
        """Remove digitize actor from overlay renderer."""
        if hasattr(self, 'overlay_renderer') and self.overlay_renderer:
            self.overlay_renderer.RemoveActor(actor)
        # Also try base renderer as safety net (handles legacy actors)
        try:
            self.renderer.RemoveActor(actor)
        except Exception:
            pass

    def _remove_preview_actor_2d(self, attr_name):
        """Safely remove a transient preview actor from any renderer layer."""
        actor = getattr(self, attr_name, None)
        if actor is not None:
            try:
                actor.VisibilityOff()
            except Exception:
                pass
            try:
                if hasattr(self, 'overlay_renderer') and self.overlay_renderer:
                    self.overlay_renderer.RemoveActor(actor)
            except Exception:
                pass
            try:
                self.renderer.RemoveActor2D(actor)
            except Exception:
                pass
            try:
                self.renderer.RemoveActor(actor)
            except Exception:
                pass
            try:
                self.renderer.RemoveViewProp(actor)
            except Exception:
                pass
            setattr(self, attr_name, None) 

    def deactivate_all(self):
        """Exit the current digitize tool while preserving completed drawings."""
        if self._deactivate_active_tool_keep_drawings():
            return True

        self._clear_live_preview_actors()
        self._clear_suspended_preview_actor()
        self.temp_points = []
        self.left_down = False
        self.middle_down = False
        self._clear_temp_vertex_history()

        if hasattr(self.app, 'set_cross_cursor_active'):
            self.app.set_cross_cursor_active(False, "draw")

        try:
            self.app.vtk_widget.render()
        except Exception:
            pass

        print("Digitizer already idle")
        return False

    def disable_all_tools(self):
        """Disable digitizer interaction entirely, e.g. while the app is in 3D view."""
        self.deactivate_all()

        if hasattr(self.app, 'measurement_tool') and self.app.measurement_tool:
            try:
                self.app.measurement_tool.deactivate()
            except Exception as e:
                print(f"Failed to deactivate measurement tool while disabling digitizer: {e}")

        self.enabled = False
        if hasattr(self.app, 'set_cross_cursor_active'):
            self.app.set_cross_cursor_active(False, "draw")
        print("Digitizer DISABLED")

    def _build_preview_polydata_screen(self, screen_points, line_style='solid'):
        """Build screen-space preview geometry, including real dashed/dotted segments."""
        poly = vtk.vtkPolyData()
        pts = vtk.vtkPoints()
        lines = vtk.vtkCellArray()

        if line_style == 'solid':
            for p in screen_points:
                pts.InsertNextPoint(float(p[0]), float(p[1]), 0.0)

            n = pts.GetNumberOfPoints()
            lines.InsertNextCell(n)
            for i in range(n):
                lines.InsertCellPoint(i)

            poly.SetPoints(pts)
            poly.SetLines(lines)
            poly.Modified()
            return poly

        if line_style == 'dashed':
            dash_pattern = [(10.0, 6.0)]
        elif line_style == 'dotted':
            dash_pattern = [(2.0, 6.0)]
        elif line_style == 'dash-dot':
            dash_pattern = [(10.0, 6.0), (2.0, 6.0)]
        elif line_style == 'dash-dot-dot':
            dash_pattern = [(10.0, 6.0), (2.0, 4.0), (2.0, 6.0)]
        else:
            dash_pattern = [(10.0, 6.0)]

        point_idx = 0
        for seg_idx in range(len(screen_points) - 1):
            p1 = np.array(screen_points[seg_idx], dtype=np.float64)
            p2 = np.array(screen_points[seg_idx + 1], dtype=np.float64)

            edge_vec = p2 - p1
            edge_len = np.linalg.norm(edge_vec)
            if edge_len < 1e-6:
                continue

            direction = edge_vec / edge_len
            t = 0.0
            pattern_idx = 0

            while t < edge_len:
                dash_length, gap_length = dash_pattern[pattern_idx]
                dash_end_t = min(t + dash_length, edge_len)
                if dash_end_t - t <= 1e-6:
                    break

                dash_start = p1 + direction * t
                dash_end = p1 + direction * dash_end_t

                pts.InsertNextPoint(float(dash_start[0]), float(dash_start[1]), 0.0)
                start_idx = point_idx
                point_idx += 1

                pts.InsertNextPoint(float(dash_end[0]), float(dash_end[1]), 0.0)
                end_idx = point_idx
                point_idx += 1

                lines.InsertNextCell(2)
                lines.InsertCellPoint(start_idx)
                lines.InsertCellPoint(end_idx)

                t = dash_end_t + gap_length
                pattern_idx = (pattern_idx + 1) % len(dash_pattern)

        poly.SetPoints(pts)
        poly.SetLines(lines)
        poly.Modified()
        return poly

    def _update_preview_actor_screen(self, attr_name, screen_points, color=(0,1,0), width=3, line_style='solid'):
        """
        ANTI-BLINK: Reuse existing actor, just swap polydata in-place.
        No Remove+Add per frame = zero flicker.
        """
        if not screen_points or len(screen_points) < 2:
            self._remove_preview_actor_2d(attr_name)
            return

        poly = self._build_preview_polydata_screen(screen_points, line_style=line_style)

        actor = getattr(self, attr_name, None)

        if actor is None:
            mapper = vtk.vtkPolyDataMapper2D()
            mapper.SetInputData(poly)

            actor = vtk.vtkActor2D()
            actor.SetMapper(mapper)
            prop = actor.GetProperty()
            prop.SetColor(float(color[0]), float(color[1]), float(color[2]))
            prop.SetLineWidth(float(width))
            prop.SetOpacity(1.0)
            prop.SetDisplayLocationToForeground()

            self.renderer.AddActor2D(actor)
            setattr(self, attr_name, actor)
        else:
            mapper = actor.GetMapper()
            mapper.SetInputData(poly)
            mapper.Modified()
            prop = actor.GetProperty()
            prop.SetColor(float(color[0]), float(color[1]), float(color[2]))
            prop.SetLineWidth(float(width))
            actor.SetVisibility(1)
        return

        pts = vtk.vtkPoints()
        for p in screen_points:
            pts.InsertNextPoint(float(p[0]), float(p[1]), 0.0)

        n = pts.GetNumberOfPoints()
        cell = vtk.vtkCellArray()
        cell.InsertNextCell(n)
        for i in range(n):
            cell.InsertCellPoint(i)

        poly = vtk.vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(cell)
        # ✅ CRITICAL: must call Modified() so VTK pipeline knows data changed
        poly.Modified()

        actor = getattr(self, attr_name, None)

        if actor is None:
            mapper = vtk.vtkPolyDataMapper2D()
            mapper.SetInputData(poly)

            actor = vtk.vtkActor2D()
            actor.SetMapper(mapper)
            prop = actor.GetProperty()
            prop.SetColor(float(color[0]), float(color[1]), float(color[2]))
            prop.SetLineWidth(float(width))
            prop.SetOpacity(1.0)
            prop.SetDisplayLocationToForeground()

            self.renderer.AddActor2D(actor)
            setattr(self, attr_name, actor)
        else:
            # ✅ Swap data in-place — actor never leaves renderer
            mapper = actor.GetMapper()
            mapper.SetInputData(poly)
            # ✅ CRITICAL: force mapper to re-read new polydata
            mapper.Modified()
            actor.GetProperty().SetColor(float(color[0]), float(color[1]), float(color[2]))
            actor.GetProperty().SetLineWidth(float(width))
            actor.SetVisibility(1)###
    
    def _add_endpoint_sphere(self, position, color=(1, 1, 0), radius=None):
        """
        ✅ TRUE BULLETPROOF SCREEN VERTEX
        Uses native VTK 3D points. PointSize is fixed in screen pixels 
        and mathematically ignores camera zoom natively.
        """
        pts = vtk.vtkPoints()
        pts.SetDataTypeToDouble()
        pts.InsertNextPoint(position[0], position[1], position[2])

        verts = vtk.vtkCellArray()
        verts.InsertNextCell(1)
        verts.InsertCellPoint(0)

        poly = vtk.vtkPolyData()
        poly.SetPoints(pts)
        poly.SetVerts(verts)

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly)
        
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetResolveCoincidentTopologyPolygonOffsetParameters(-4, -4)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        prop = actor.GetProperty()
        prop.SetColor(color)
        prop.SetOpacity(1.0)
        prop.SetPointSize(5.0)
        prop.SetRenderPointsAsSpheres(True)

        self._add_actor_to_overlay(actor)
        return actor

    # ============================================================
    # PATCH FIX 4: Enhanced _make_scalable_text_actor
    # ============================================================

    def _make_scalable_text_actor(self, text, position, color=(1, 1, 1), font_size=18, 
                                    bold=True, font_family="Arial", justify="center"):
        """
        Creates a vtkTextActor3D that lives in WORLD SPACE.
        Unlike vtkBillboardTextActor3D (fixed screen size), this actor
        scales with zoom — text grows when you zoom in, shrinks when you zoom out.
        """
        actor = vtk.vtkTextActor3D()
        actor.SetInput(text)
        actor.SetPosition(position[0], position[1], position[2])
        
        # ✅ All styling goes through GetTextProperty()
        prop = actor.GetTextProperty()
        prop.SetColor(color[0], color[1], color[2])
        prop.SetFontSize(font_size)
        prop.SetOpacity(1.0)  # Default full opacity
        
        if bold:
            prop.BoldOn()
        else:
            prop.BoldOff()
        
        font_family_lower = font_family.lower() if font_family else "arial"
        if "courier" in font_family_lower:
            prop.SetFontFamilyToCourier()
        elif "times" in font_family_lower:
            prop.SetFontFamilyToTimes()
        else:
            prop.SetFontFamilyToArial()
        
        if justify == "left":
            prop.SetJustificationToLeft()
        elif justify == "right":
            prop.SetJustificationToRight()
        else:
            prop.SetJustificationToCentered()
        
        prop.SetVerticalJustificationToCentered()
        
        # Calculate base scale from current camera
        camera = self.renderer.GetActiveCamera()
        if camera.GetParallelProjection():
            parallel_scale = camera.GetParallelScale()
        else:
            focal = np.array(camera.GetFocalPoint())
            cam_pos = np.array(camera.GetPosition())
            parallel_scale = np.linalg.norm(cam_pos - focal) * 0.1
        
        # Prevent division by zero
        if parallel_scale < 0.001:
            parallel_scale = 100.0
        
        base_scale = (parallel_scale / 100.0) * (font_size / 18.0) * 0.05
        actor.SetScale(base_scale, base_scale, base_scale)
        
        # Store metadata for later use
        actor._text_scale_base = base_scale
        actor._text_font_size = font_size
        actor._text_parallel_scale_ref = parallel_scale
        
        actor.PickableOn()
        actor._digitize_overlay = True
        
        return actor

    # ---------------- FINALIZE EXISTING SHAPES ----------------
    def _finalize_rectangle(self):
        """Finalize rectangle drawing immediately."""
        self._save_state()
        if len(self.temp_points) != 2:
            print("⚠️ Rectangle needs exactly 2 points")
            return
        
        self._remove_preview_actor_2d('_rectangle_preview_actor')
        
        p1, p2 = self.temp_points
        x1, y1, z1 = p1
        x2, y2, z2 = p2
        
        coords = [
            (x1, y1, z1), 
            (x2, y1, z1), 
            (x2, y2, z2), 
            (x1, y2, z2), 
            (x1, y1, z1)
        ]
        
        rc_style = self._get_draw_style('rectangle')
        rc_color = rc_style['color']
        rc_width = rc_style['width']
        rc_lstyle = rc_style['style']

        actor = self._make_polyline_actor(coords, color=rc_color, width=rc_width, line_style=rc_lstyle)
        actor.PickableOn()
        self._add_actor_to_overlay(actor)
        
        drawing_entry = {
            "type": "rectangle", 
            "coords": coords, 
            "actor": actor,
            "bounds": actor.GetBounds(),
            "original_color": rc_color,
            "original_width": rc_width,
            "original_style": rc_lstyle,
        }
        self.drawings.append(drawing_entry)    

        self.temp_points = []
        if getattr(self, 'rectangle_permanent_mode', False):
            self.active_tool = "rectangle"
            print(f"✅ Rectangle finalized (Permanent - ready for next)")
        else:
            self.active_tool = None
            print(f"✅ Rectangle finalized")
        self.renderer.Modified()
        self.app.vtk_widget.render()

    def _finalize_circle(self, n=None):
        self._save_state()
        if len(self.temp_points) != 2: return
        
        self._remove_preview_actor_2d('_circle_preview_actor_2d')
        self._remove_preview_actor_2d('_circle_preview_actor')
        
        center, edge = self.temp_points
        radius = np.sqrt((edge[0]-center[0])**2 + (edge[1]-center[1])**2)
        
        if n is None:
            n = self._get_circle_segment_count(center, edge)
        
        thetas = np.linspace(0, 2 * np.pi, n, endpoint=False)
        coords = [(center[0] + radius * np.cos(t), center[1] + radius * np.sin(t), center[2]) for t in thetas]
        coords.append(coords[0]) 
        
        ci_style = self._get_draw_style('circle')
        ci_color = ci_style['color']
        ci_width = ci_style['width']
        ci_lstyle = ci_style['style']

        actor = self._make_polyline_actor(coords, color=ci_color, width=ci_width, line_style=ci_lstyle)
        self._add_actor_to_overlay(actor)
        
        self.drawings.append({
            'type': 'circle', 'coords': coords, 'actor': actor, 
            'bounds': actor.GetBounds(), 'center': center, 'radius': radius,
            'original_color': ci_color, 'original_width': ci_width,
            'original_style': ci_lstyle,
        })
        
        self.temp_points = []
        if getattr(self, 'circle_permanent_mode', False):
            self.active_tool = "circle"
            print(f"✅ Circle finalized (Permanent - ready for next, Radius={radius:.3f})")
        else:
            self.active_tool = None
            print(f"✅ Circle finalized (Radius={radius:.3f})")
        self.renderer.Modified()
        self.app.vtk_widget.render()

    def _finalize_polygon(self):
        self._save_state()
        coords = self.temp_points + [self.temp_points[0]]
        actor = self._make_polyline_actor(coords)
        self._add_actor_to_overlay(actor)
        self.drawings.append({
            "type": "polygon", 
            "coords": coords, 
            "actor": actor,
            "bounds": actor.GetBounds(),
            "original_color": (1, 0, 0),
            "original_width": 2,
        })
        self.temp_points = []
        self.app.vtk_widget.render()
    
    
    
    def _finalize_freehand(self):
        """
        ✅ FIX: Commit freehand drawing using overlay renderer (consistent with all other tools).
        Previously used self.renderer.AddActor2D() which bypassed overlay_renderer.
        """
        self._save_state()
        
        self._remove_preview_actor_2d('_preview_actor')
        self._remove_preview_actor_2d('_freehand_preview_actor_2d')

        if len(self.temp_points) < 2:
            self.temp_points = []
            return

        # 2. FORCE AUTO-CLOSE
        start_pt = self.temp_points[0]
        end_pt = self.temp_points[-1]
        
        dist = np.linalg.norm(np.array(start_pt) - np.array(end_pt))
        
        if dist > 0.001:
            self.temp_points.append(start_pt)
            print("🔗 Freehand loop Auto-Closed (Forced)")
        else:
            print("🔗 Freehand loop already closed")

        # 3. Create Final Actor — use 3D polyline actor like all other tools
        fh_style = self._get_draw_style('freehand')
        fh_color = fh_style['color']
        fh_width = fh_style['width']
        fh_lstyle = fh_style['style']

        final_actor = self._make_polyline_actor(self.temp_points, color=fh_color, width=fh_width, line_style=fh_lstyle)
        
        # 4. Add via overlay renderer (THE FIX — was AddActor2D before)
        self._add_actor_to_overlay(final_actor)
        
        # 5. Store Drawing
        self.drawings.append({
            "type": "freehand", 
            "coords": list(self.temp_points), 
            "actor": final_actor,
            "bounds": final_actor.GetBounds(),
            "original_color": fh_color,
            "original_width": fh_width,
            "original_style": fh_lstyle,
        })
        
        self.temp_points = []
        self.is_drawing_freehand = False
        if getattr(self, 'freehand_permanent_mode', False):
            self.active_tool = "freehand"
            print(f"✅ Freehand finalized (Permanent - ready for next)")
        else:
            self.active_tool = None
        self.renderer.Modified()
        self.app.vtk_widget.render()

    def _finalize_text(self, text):
        """
        ✅ Text uses renderer directly (not overlay) because vtkTextActor is 2D.
        This is intentional and separate from the overlay system.
        """
        self._save_state()
        if not self.temp_points:
            return
            
        pos = self.temp_points[-1]
        
        actor = vtk.vtkTextActor()
        actor.SetInput(text)
        
        prop = actor.GetTextProperty()
        prop.SetColor(1, 1, 0) # Yellow
        prop.BoldOn()
        prop.SetFontSize(18)
        prop.SetJustificationToCentered()
        prop.SetVerticalJustificationToCentered()
        
        coord = actor.GetActualPositionCoordinate()
        coord.SetCoordinateSystemToWorld()
        coord.SetValue(pos[0], pos[1], pos[2])
        
        actor.GetProperty().SetDisplayLocationToForeground()
        
        # TEXT actors must use renderer.AddActor2D (they are inherently 2D)
        self.renderer.AddActor2D(actor)
        
        self.drawings.append({
            "type": "text", 
            "coords": [tuple(pos)], 
            "actor": actor, 
            "text": text,
            "original_text_color": (1, 1, 0)
        })
        
        self.temp_points = []
        self.renderer.Modified()
        self.app.vtk_widget.render()
        print(f"✅ Zoom-immune 2D Text placed at {pos}")

    def clear_drawings(self, clear_classified=False):
        """
        ✅ FIX: Clear all drawings consistently.
        All non-text actors live in overlay_renderer.
        Text actors live in self.renderer (they are 2D by nature).
        """
        print("🧹 Clearing all drawings and previews (safe mode)...")

        self._clear_suspended_preview_actor()
        self._suspended_state = None

        def _safe_remove(actor, is_text=False, is_scalable=False):
            """Route removal to the correct renderer."""
            if actor is None:
                return
            if is_text:
                if is_scalable:
                    # Scalable text lives in overlay
                    try:
                        if hasattr(self, 'overlay_renderer') and self.overlay_renderer:
                            self.overlay_renderer.RemoveActor(actor)
                    except: pass
                else:
                    # Legacy billboard text
                    try: self.renderer.RemoveViewProp(actor)
                    except: pass
                    try: self.renderer.RemoveActor2D(actor)
                    except: pass
                # Safety net
                try: self._remove_actor_from_overlay(actor)
                except: pass
            else:
                try:
                    if hasattr(self, 'overlay_renderer') and self.overlay_renderer:
                        self.overlay_renderer.RemoveActor(actor)
                except: pass
                try: self.renderer.RemoveActor(actor)
                except: pass

        for d in list(self.drawings):
            try:
                # ✅ Skip cyan classified fences unless Shift+Clear
                if not clear_classified and d.get('classified_fence', False):
                    continue
                is_text = d.get('type') == 'text'
                is_scalable = d.get('scalable', False)
                
                if d.get('actor') is not None:
                    _safe_remove(d['actor'], is_text=is_text, is_scalable=is_scalable)
                    try: d['actor'].VisibilityOff()
                    except: pass

                # Endpoint markers (always in overlay)
                _safe_remove(d.get('start_marker'), is_text=False)
                _safe_remove(d.get('end_marker'), is_text=False)

                # Vertex markers (always in overlay)
                for marker in d.get('vertex_markers', []):
                    _safe_remove(marker, is_text=False)

                # Arrow actors (2D, in self.renderer)
                arrows = d.get('arrow_actor')
                if arrows is not None:
                    if not isinstance(arrows, list):
                        arrows = [arrows]
                    for arr in arrows:
                        try: self.renderer.RemoveActor2D(arr)
                        except: pass

            except Exception as e:
                print(f"⚠️ Failed to remove drawing: {e}")

        # REPLACE WITH:
        if clear_classified:
            self.drawings.clear()
        else:
            # Keep only classified fence drawings
            self.drawings[:] = [d for d in self.drawings if d.get('classified_fence', False)]

        # ── 2. Remove preview line actors (in self.renderer — they are temp) ────
        for attr in ['_preview_line_actor', '_continuous_line_actor', '_line_start_marker',
                    '_rectangle_preview_actor']:
            self._remove_preview_actor_2d(attr)

        # ── 3. Remove circle / freehand preview actors ───────────────────────────
        for attr in ['_circle_preview_actor_2d', '_circle_preview_actor',
                    '_freehand_preview_actor_2d']:
            actor = getattr(self, attr, None)
            if actor:
                try: self.renderer.RemoveViewProp(actor)
                except: pass
                setattr(self, attr, None)

        # Freehand in-progress preview (now in overlay)
        if hasattr(self, '_preview_actor') and self._preview_actor:
            _safe_remove(self._preview_actor, is_text=False)
            self._preview_actor = None

        # ── 4. Remove in-progress vertex marker arrays (all in overlay) ──────────
        for attr in ['_smartline_vertex_markers', '_polyline_vertex_markers', '_line_vertex_markers']:
            markers = getattr(self, attr, [])
            for marker in markers:
                _safe_remove(marker, is_text=False)
            setattr(self, attr, [])

        # ── 5. Clear coordinate labels ───────────────────────────────────────────
        self.clear_coordinate_labels()

        # ── 6. Reset drawing state ───────────────────────────────────────────────
        self.temp_points = []
        self.selected = None
        self.selected_drawing = None
        self.left_down = False
        self._clear_temp_vertex_history()
        # self.active_tool = None

        # ── 7. Force full re-render ──────────────────────────────────────────────
        if hasattr(self, 'overlay_renderer') and self.overlay_renderer:
            self.overlay_renderer.Modified()
        self.renderer.Modified()
        try:
            self.interactor.GetRenderWindow().Render()
        except Exception:
            pass
        try:
            self.app.vtk_widget.render()
        except Exception:
            pass
        
        try:
            dlg = getattr(self.app, 'inside_fence_dialog', None)
            if dlg:
                for actor in getattr(dlg, '_classified_fence_actors', []):
                    try: self.overlay_renderer.RemoveActor(actor)
                    except: pass
                dlg._classified_fence_actors = []
                dlg.selected_fences = []
                dlg._clear_fence_highlights()
        except Exception as e:
            print(f"⚠️ Could not clear fence highlights: {e}")

        print("✅ Cleared all drawn vectors, previews, and arrows - point cloud preserved.")

    # ---------------- COORDINATE LABELS ----------------
    def show_vertex_coordinates(self, points):
        """Display constant-size sphere markers at each vertex."""
        self.clear_coordinate_labels()
        self.coord_labels = []

        for pt in points:
            marker = self._add_endpoint_sphere(pt, color=(1.0, 1.0, 0.0), radius=None)
            self.coord_labels.append(marker)

        self.app.vtk_widget.render()
        print(f"📍 Displayed {len(points)} vertex markers (constant size).")

    def clear_coordinate_labels(self):
        """Remove all coordinate labels and markers without leaking memory."""
        if not hasattr(self, "coord_labels"):
            self.coord_labels = []
            return
        
        print(f"🧹 Clearing {len(self.coord_labels)} coordinate labels...")
        
        for lbl in self.coord_labels:
            try:
                if hasattr(self, 'overlay_renderer') and self.overlay_renderer:
                    self.overlay_renderer.RemoveViewProp(lbl)
                self.renderer.RemoveViewProp(lbl)  # harmless fallback
            except Exception as e:
                print(f"⚠️ Failed to remove marker: {e}")
        
        self.coord_labels = []
        self.renderer.Modified()
        print("✅ Coordinate labels cleared")

    # ============================================================
    # PATCH 12: Update rebind_drawings for scalable text
    # ============================================================

    def rebind_drawings(self):
        """Restores all 3D actors AND 2D overlays after a renderer clear."""
        if not hasattr(self, "drawings") or not self.drawings:
            return
            
        print(f"🔄 Rebinding {len(self.drawings)} drawings to renderer...")
        
        for d in self.drawings:
            is_text = d.get('type') == 'text'
            is_scalable = d.get('scalable', False)
            
            if "actor" in d and d["actor"]:
                if is_text:
                    if is_scalable:
                        # Scalable text goes to overlay
                        self._add_actor_to_overlay(d["actor"])
                    else:
                        # Legacy billboard text
                        self.renderer.AddViewProp(d["actor"])
                else:
                    self._add_actor_to_overlay(d["actor"])
                
            if d.get("start_marker"): 
                self._add_actor_to_overlay(d["start_marker"])
            if d.get("end_marker"): 
                self._add_actor_to_overlay(d["end_marker"])
            
            if d.get("vertex_markers"):
                for marker in d["vertex_markers"]:
                    self._add_actor_to_overlay(marker)
                    
            if d.get("arrow_actor"):
                arrows = d["arrow_actor"]
                if not isinstance(arrows, list): arrows = [arrows]
                for arr in arrows:
                    self.renderer.AddActor2D(arr)
                    
        self.renderer.Modified()
        try: 
            self.app.vtk_widget.render()
        except: 
            pass
        print("✅ Rebind complete.")


    def debug_test_sphere(self):
        if self.drawings and self.drawings[0]["coords"]:
            x, y, z = self.drawings[0]["coords"][0]
        else:
            x, y, z = 0, 0, 0
        sphere = vtk.vtkSphereSource()
        sphere.SetRadius(1.0)
        sphere.SetCenter(x, y, z)
        sphere.SetThetaResolution(32)
        sphere.SetPhiResolution(32)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        marker = vtk.vtkActor()
        marker.SetMapper(mapper)
        marker.GetProperty().SetColor(1, 0, 1)
        marker.GetProperty().SetOpacity(1.0)
        self.renderer.AddActor(marker)
        self.app.vtk_widget.interactor.GetRenderWindow().Render()
        print(f"DEBUG: drew sphere at ({x},{y},{z}) with radius 5.0")

    def _focus_camera_on_points(self, points):
        pts = np.array(points)
        if pts.shape[0] == 0:
            return
        min_xyz = pts.min(axis=0)
        max_xyz = pts.max(axis=0)
        center = (min_xyz + max_xyz) / 2
        radius = np.linalg.norm(max_xyz - min_xyz) * 1.5 + 5

        camera = self.renderer.GetActiveCamera()
        camera.SetFocalPoint(*center)
        camera.SetPosition(center[0], center[1] - radius, center[2] + radius)
        camera.SetViewUp(0, 0, 1)
        camera.SetClippingRange(0.01, radius * 100)
        self.renderer.ResetCameraClippingRange()
        self.app.vtk_widget.render()

    def set_vertex_move_mode(self, enabled=True):
        """Toggle vertex move mode on/off."""
        self.vertex_move_mode = enabled
        
        if enabled:
            print("🔵 Vertex Move Mode ON - Click and drag vertices")
            self.active_tool = None
            
            self.interactor.RemoveObservers("MouseMoveEvent")
            self.interactor.RemoveObservers("LeftButtonPressEvent")
            self.interactor.RemoveObservers("LeftButtonReleaseEvent")
            
            self.interactor.AddObserver("MouseMoveEvent", self._on_vertex_move_hover, 1.0)
            self.interactor.AddObserver("LeftButtonPressEvent", self._on_vertex_move_start, 1.0)
            self.interactor.AddObserver("LeftButtonReleaseEvent", self._on_vertex_move_end, 1.0)
        else:
            print("⚪ Vertex Move Mode OFF")
            self.dragging_vertex = None
            
            if self.vertex_hover_marker:
                self._remove_actor_from_overlay(self.vertex_hover_marker)
                self.vertex_hover_marker = None
            
            if self.vertex_drag_marker:
                self._remove_actor_from_overlay(self.vertex_drag_marker)
                self.vertex_drag_marker = None
            
            self.interactor.RemoveObservers("MouseMoveEvent")
            self.interactor.RemoveObservers("LeftButtonPressEvent")
            self.interactor.RemoveObservers("LeftButtonReleaseEvent")
            
            self.interactor.AddObserver("LeftButtonPressEvent", self._on_left_press, 1.0)
            self.interactor.AddObserver("MouseMoveEvent", self._on_mouse_move, 1.0)
            self.interactor.AddObserver("LeftButtonReleaseEvent", self._on_left_release, 1.0)
            
            
    def _rebuild_drawing_actor(self, drawing):
        """
        Rebuild the visual actor for a drawing after coordinates changed.
        Preserves color, width, arrows, and markers.
        """
        try:
            coords = drawing['coords']
            color = drawing.get('original_color', (1, 0, 0))
            width = drawing.get('original_width', 2)
            
            if 'actor' in drawing and drawing['actor']:
                self._remove_actor_from_overlay(drawing['actor'])
            
            new_actor = self._make_polyline_actor(coords, color=color, width=width)
            
            drawing['actor'] = new_actor
            drawing['bounds'] = new_actor.GetBounds()
            
            self._add_actor_to_overlay(new_actor)
            
            if 'vertex_markers' in drawing and drawing['vertex_markers']:
                for marker in drawing['vertex_markers']:
                    try:
                        self._remove_actor_from_overlay(marker)
                    except:
                        pass
                
                drawing['vertex_markers'] = []
                for i, pt in enumerate(coords):
                    if i == 0:
                        marker_color = (0, 1, 0)
                    elif i == len(coords) - 1:
                        marker_color = (1, 0, 0)
                    else:
                        marker_color = (1, 1, 0)
                    
                    marker = self._add_endpoint_sphere(pt, color=marker_color, radius=0.05)
                    marker.GetProperty().SetOpacity(0.8)
                    drawing['vertex_markers'].append(marker)
            
            if 'arrow_actor' in drawing and drawing['arrow_actor']:
                arrows = drawing['arrow_actor']
                if not isinstance(arrows, list):
                    arrows = [arrows]
                for arr in arrows:
                    try:
                        self.renderer.RemoveActor2D(arr)
                    except:
                        pass
                
                if getattr(self, f"{drawing['type']}_arrow_mode", False):
                    drawing['arrow_actor'] = self._add_arrow_to_line(coords)
                else:
                    drawing['arrow_actor'] = None
            
            self.renderer.Modified()
            
        except Exception as e:
            print(f"⚠️ Failed to rebuild drawing actor: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_vertex_move_hover(self, obj, evt):
        """Show cyan marker when hovering over a vertex."""
        if self.dragging_vertex:
            self._on_vertex_drag(obj, evt)
            return
        
        x, y = self.interactor.GetEventPosition()
        nearest_vertex, nearest_drawing, vertex_idx = self._find_nearest_vertex_at_position(x, y, tolerance=15.0)
        
        if nearest_vertex is not None:
            if not self.vertex_hover_marker:
                self.vertex_hover_marker = self._add_endpoint_sphere(
                    nearest_vertex, color=(0, 1, 1), radius=0.08
                )
            else:
                self.vertex_hover_marker.SetPosition(*nearest_vertex)
                self.vertex_hover_marker.SetVisibility(True)
            self.app.vtk_widget.render()
        else:
            if self.vertex_hover_marker:
                self.vertex_hover_marker.SetVisibility(False)
                self.app.vtk_widget.render()
    
    def _on_vertex_move_start(self, obj, evt):
        """Click on vertex to start dragging."""
        x, y = self.interactor.GetEventPosition()
        nearest_vertex, nearest_drawing, vertex_idx = self._find_nearest_vertex_at_position(x, y, tolerance=15.0)
        
        if nearest_vertex and nearest_drawing:
            self._save_state()
            
            self.dragging_vertex = {
                'drawing': nearest_drawing,
                'vertex_index': vertex_idx,
                'original_pos': nearest_vertex
            }
            
            if self.vertex_drag_marker:
                self._remove_actor_from_overlay(self.vertex_drag_marker)
            
            self.vertex_drag_marker = self._add_endpoint_sphere(
                nearest_vertex, color=(1, 1, 0), radius=0.12
            )
            
            if self.vertex_hover_marker:
                self.vertex_hover_marker.SetVisibility(False)
            
            print(f"🔵 Dragging vertex {vertex_idx}")
            self.app.vtk_widget.render()
    
    def _on_vertex_drag(self, obj, evt):
        """Update vertex position while dragging."""
        if not self.dragging_vertex:
            return
        
        new_pos = self._get_mouse_world()
        
        drawing = self.dragging_vertex['drawing']
        vertex_idx = self.dragging_vertex['vertex_index']
        
        coords = drawing['coords']
        coords[vertex_idx] = tuple(new_pos)
        
        if self.vertex_drag_marker:
            self.vertex_drag_marker.SetPosition(*new_pos)
        
        self._rebuild_drawing_actor(drawing)
        
        if self.selected_drawing is drawing:
            self.clear_coordinate_labels()
            self.show_vertex_coordinates(coords)
        
        self.app.vtk_widget.render()
    
    def _on_vertex_move_end(self, obj, evt):
        """Release to finish dragging."""
        if not self.dragging_vertex:
            return
        
        drawing = self.dragging_vertex['drawing']
        vertex_idx = self.dragging_vertex['vertex_index']
        new_pos = drawing['coords'][vertex_idx]
        
        print(f"✅ Vertex {vertex_idx} moved to {new_pos}")
        
        if self.vertex_drag_marker:
            self._remove_actor_from_overlay(self.vertex_drag_marker)
            self.vertex_drag_marker = None
        
        self._rebuild_drawing_actor(drawing)
        self.dragging_vertex = None
        self.app.vtk_widget.render()
    
    def _find_nearest_vertex_at_position(self, x, y, tolerance=15.0):
        """Find nearest vertex to screen position."""
        min_dist = tolerance
        nearest_vertex = None
        nearest_drawing = None
        nearest_idx = None
        
        for drawing in self.drawings:
            if 'coords' not in drawing:
                continue
            
            coords = drawing['coords']
            for i, vertex in enumerate(coords):
                self.renderer.SetWorldPoint(vertex[0], vertex[1], vertex[2], 1.0)
                self.renderer.WorldToDisplay()
                screen_pos = self.renderer.GetDisplayPoint()
                
                dx = screen_pos[0] - x
                dy = screen_pos[1] - y
                dist = (dx*dx + dy*dy) ** 0.5
                
                if dist < min_dist:
                    min_dist = dist
                    nearest_vertex = vertex
                    nearest_drawing = drawing
                    nearest_idx = i
        
        return nearest_vertex, nearest_drawing, nearest_idx
    
    def save_drawings_to_file(self, filepath):
        """Save all drawings to a JSON file."""
        import json
        import os
        
        try:
            drawings_data = []
            for d in self.drawings:
                drawing_info = {
                    "type": d["type"],
                    "coords": d["coords"],
                }
                
                if "text" in d:
                    drawing_info["text"] = d["text"]
                
                # Save text-specific properties
                if d["type"] == "text":
                    if "original_text_color" in d:
                        drawing_info["color"] = list(d["original_text_color"])
                    if "font_size" in d:
                        drawing_info["font_size"] = d["font_size"]
                    if "bold" in d:
                        drawing_info["bold"] = d["bold"]
                    if "font_family" in d:
                        drawing_info["font_family"] = d["font_family"]
                    if "scalable" in d:
                        drawing_info["scalable"] = d["scalable"]
                
                drawings_data.append(drawing_info)
            
            if not filepath.endswith('.json'):
                base_name = os.path.splitext(filepath)[0]
                json_path = base_name + "_drawings.json"
            else:
                json_path = filepath
            
            with open(json_path, 'w') as f:
                json.dump(drawings_data, f, indent=2)
            
            print(f"✅ Saved {len(drawings_data)} drawings to: {json_path}")
            return json_path
            
        except Exception as e:
            print(f"⚠️ Failed to save drawings: {e}")
            import traceback
            traceback.print_exc()
            return None

    def load_drawings_from_file(self, filepath):
        """Load drawings from a JSON file and recreate them in the scene."""
        import json
        import os
        
        try:
            if not filepath.endswith('.json'):
                base_name = os.path.splitext(filepath)[0]
                json_path = base_name + "_drawings.json"
            else:
                json_path = filepath
            
            if not os.path.exists(json_path):
                print(f"ℹ️ No drawings file found: {json_path}")
                return False
            
            with open(json_path, 'r') as f:
                drawings_data = json.load(f)
            
            for d in list(self.drawings):
                try:
                    if "actor" in d and d["actor"] is not None:
                        if d.get('type') == 'text':
                            self.renderer.RemoveActor(d["actor"])
                        else:
                            self._remove_actor_from_overlay(d["actor"])
                except Exception:
                    pass
            self.drawings.clear()
            
            for d in drawings_data:
                drawing_type = d["type"]
                coords = [tuple(c) for c in d["coords"]]
                
                if drawing_type in ("smartline", "line", "freehand", "rectangle", "polygon", "circle"):
                    actor = self._make_polyline_actor(coords)
                    
                    if "color" in d:
                        actor.GetProperty().SetColor(*d["color"])
                    if "width" in d:
                        actor.GetProperty().SetLineWidth(d["width"])
                    
                    self._add_actor_to_overlay(actor)
                    
                    drawing_entry = {
                        "type": drawing_type,
                        "coords": coords,
                        "actor": actor,
                        "bounds": actor.GetBounds()
                    }
                    
                    if "color" in d:
                        drawing_entry["original_color"] = tuple(d["color"])
                    if "width" in d:
                        drawing_entry["original_width"] = d["width"]
                    
                    self.drawings.append(drawing_entry)
                    
                elif drawing_type == "text":
                    pos = coords[0]
                    text = d.get("text", "Text")
                    t_color = d.get("color", d.get("original_text_color", (0, 0, 1)))
                    if isinstance(t_color, list):
                        t_color = tuple(t_color)
                    # Normalize color to 0-1 range
                    if t_color and all(c <= 1.0 for c in t_color):
                        pass
                    elif t_color:
                        t_color = tuple(c / 255.0 for c in t_color)
                    else:
                        t_color = (0, 0, 1)
                    
                    t_font_size = d.get("font_size", 18)
                    t_bold = d.get("bold", True)
                    t_font_family = d.get("font_family", "Arial")
                    
                    # Create scalable text actor
                    t = self._make_scalable_text_actor(
                        text=text,
                        position=pos,
                        color=t_color,
                        font_size=t_font_size,
                        bold=t_bold,
                        font_family=t_font_family,
                        justify='center',
                    )
                    self._add_actor_to_overlay(t)
                    
                    self.drawings.append({
                        "type": "text",
                        "coords": [tuple(pos)],
                        "actor": t,
                        "text": text,
                        "bounds": t.GetBounds(),
                        "original_text_color": t_color,
                        "font_size": t_font_size,
                        "bold": t_bold,
                        "font_family": t_font_family,
                        "scalable": True,
                    })

            
            self.app.vtk_widget.render()
            
            print(f"✅ Loaded {len(drawings_data)} drawings from: {json_path}")
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to load drawings: {e}")
            import traceback
            traceback.print_exc()
            return False

    def auto_save_drawings(self, las_filepath):
        if not self.drawings:
            print("ℹ️ No drawings to save")
            return None
        path = self.save_drawings_to_file(las_filepath)
        if path:
            print(f"💾 Auto-saved drawings to: {path}")
        return path

    def auto_load_drawings(self, las_filepath):
        success = self.load_drawings_from_file(las_filepath)
        if success:
            try:
                self.renderer.Modified()
                self.app.vtk_widget.interactor.GetRenderWindow().Render()
                self.app.vtk_widget.render()
            except Exception:
                pass
        return success


    # ----------Text Label Helper----------
    def _apply_text_properties(self, text_prop, font_family, font_size, bold, italic, color):
        """Helper to apply standard Qt font properties securely to VTK properties."""
        text_prop.SetColor(*color)
        text_prop.SetBold(1 if bold else 0)
        text_prop.SetItalic(1 if italic else 0)
        text_prop.SetFontSize(int(font_size))
        
        family_lower = font_family.lower()
        if "times" in family_lower or "serif" in family_lower:
            text_prop.SetFontFamily(vtk.VTK_TIMES)
        elif "courier" in family_lower or "mono" in family_lower:
            text_prop.SetFontFamily(vtk.VTK_COURIER)
        else:
            text_prop.SetFontFamily(vtk.VTK_ARIAL)
        print(f"🔧 Text font applied: {font_family} -> VTK Enum {text_prop.GetFontFamily()}")

    def _start_text_label(self):
        """Opens text input dialog, then enters placement mode with scalable text."""
        dialog = TextEditDialog(
            current_text="New Text",
            current_size=40,
            current_font="Arial",
            current_bold=True,
            current_italic=False,
            current_color=(1, 0, 0)
        )
        
        try:
            from PySide6.QtWidgets import QDialog
            result = dialog.exec()
        except ImportError:
            from PyQt5.QtWidgets import QDialog
            result = dialog.exec_()
            
        if result == QDialog.Accepted:
            values = dialog.get_values()
            
            if not values['text'].strip():
                print("⚠️ Empty text - cancelled")
                self.active_tool = None
                return
            
            self._pending_text_config = values
            self._placing_text = True
            
            pos = self._get_mouse_world_no_snap()
            
            # Create scalable preview actor
            self._temp_text_actor = self._make_scalable_text_actor(
                text=values['text'],
                position=pos,
                color=(1, 1, 0),  # Yellow while placing
                font_size=values['font_size'],
                bold=values['bold'],
                font_family=values['font_family'],
                justify='center',
            )
            
            # ✅ FIX: vtkTextActor3D uses GetTextProperty(), not GetProperty()
            self._temp_text_actor.GetTextProperty().SetOpacity(0.6)
            
            self._add_actor_to_overlay(self._temp_text_actor)
            
            self._temp_text_color = values['color']
            
            # After removing observers and before adding text drag ones, re-add middle mouse at high priority:
            self.interactor.RemoveObservers("MouseMoveEvent")
            self.interactor.RemoveObservers("LeftButtonPressEvent")
            self.interactor.RemoveObservers("MiddleButtonPressEvent")    # ADD
            self.interactor.RemoveObservers("MiddleButtonReleaseEvent")  # ADD
            self.interactor.AddObserver("MouseMoveEvent", self._on_text_drag, 2.0)
            self.interactor.AddObserver("LeftButtonPressEvent", self._finalize_text_drag, 2.0)
            self.interactor.AddObserver("MiddleButtonPressEvent", self._on_middle_press, 2.0)    # ADD
            self.interactor.AddObserver("MiddleButtonReleaseEvent", self._on_middle_release, 2.0) # ADD

            
            self.app.vtk_widget.render()
            print(f"📝 Scalable text ready for placement: '{values['text']}' — click to place")
        else:
            print("❌ Text tool cancelled")
            self.active_tool = None
            if hasattr(self.app, 'set_cross_cursor_active'):
                self.app.set_cross_cursor_active(False, "draw")

    # ============================================================
    # COMPLETE _finalize_text_drag with proper existing text handling
    # ============================================================

    def _finalize_text_drag(self, obj, evt):
        """Finalize scalable text position."""
        if not getattr(self, "_placing_text", False):
            return

        self._save_state()
        
        pos = self._get_mouse_world_no_snap()
        config = getattr(self, '_pending_text_config', {})
        
        # Remove preview actor (only if creating new text)
        if getattr(self, '_temp_text_actor', None) and not hasattr(self, "_dragging_text_drawing"):
            self._remove_actor_from_overlay(self._temp_text_actor)
            self._temp_text_actor = None
        
        # Handle repositioning existing text
        if hasattr(self, "_dragging_text_drawing") and self._dragging_text_drawing:
            drawing = self._dragging_text_drawing
            actor = drawing['actor']
            
            # Update position
            actor.SetPosition(pos[0], pos[1], pos[2])
            
            # Restore original appearance
            text_prop = actor.GetTextProperty()
            
            if 'original_text_color' in drawing:
                text_prop.SetColor(*drawing['original_text_color'])
            
            text_prop.SetOpacity(1.0)
            
            # Update drawing entry
            drawing['coords'] = [tuple(pos)]
            drawing['bounds'] = actor.GetBounds()
            
            print(f"✅ Text repositioned at ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
            
            # Cleanup dragging state
            self._placing_text = False
            self._dragging_text_drawing = None
            self._temp_text_actor = None
            
        else:
            # Creating new text - remove preview first
            if getattr(self, '_temp_text_actor', None):
                self._remove_actor_from_overlay(self._temp_text_actor)
                self._temp_text_actor = None
            
            # Create new scalable text actor
            final_color = getattr(self, "_temp_text_color", config.get('color', (0, 0, 1)))
            
            text_actor = self._make_scalable_text_actor(
                text=config.get('text', 'Text'),
                position=pos,
                color=final_color,
                font_size=config.get('font_size', 18),
                bold=config.get('bold', True),
                font_family=config.get('font_family', 'Arial'),
                justify='center',
            )
            
            text_actor.GetTextProperty().SetOpacity(1.0)
            
            self._add_actor_to_overlay(text_actor)
            
            drawing_entry = {
                "type": "text",
                "coords": [tuple(pos)],
                "actor": text_actor,
                "text": config.get('text', 'Text'),
                "bounds": text_actor.GetBounds(),
                "original_text_color": final_color,
                "font_size": config.get('font_size', 18),
                "bold": config.get('bold', True),
                "font_family": config.get('font_family', 'Arial'),
                "justify": 'center',
                "scalable": True,
            }
            self.drawings.append(drawing_entry)
            
            print(f"✅ Scalable text placed at ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
        
        # Cleanup all state
        self._placing_text = False
        self._pending_text_config = None
        
        if hasattr(self, "_temp_text_color"):
            delattr(self, "_temp_text_color")
        if hasattr(self, "_dragging_text_drawing"):
            self._dragging_text_drawing = None

        self.interactor.RemoveObservers("MouseMoveEvent")
        self.interactor.RemoveObservers("LeftButtonPressEvent")
        self.interactor.RemoveObservers("MiddleButtonPressEvent")
        self.interactor.RemoveObservers("MiddleButtonReleaseEvent")
        self.interactor.AddObserver("LeftButtonPressEvent", self._on_left_press, 1.0)
        self.interactor.AddObserver("MouseMoveEvent", self._on_mouse_move, 1.0)
        self.interactor.AddObserver("MiddleButtonPressEvent", self._on_middle_press, 1.0)
        self.interactor.AddObserver("MiddleButtonReleaseEvent", self._on_middle_release, 1.0)
                
        # Clear tool state
        self._clear_temp_vertex_history()
        self._clear_temp_vertex_history()
        self.active_tool = None
        if hasattr(self.app, 'set_cross_cursor_active'):
            self.app.set_cross_cursor_active(False, "draw")
        self._restore_shared_interactor_observers()

        self._force_render()

    # ============================================================
    # PATCH: Text Context Menu and Related Methods for Scalable Text
    # ============================================================

    def _show_text_context_menu(self, drawing):
        """Show context menu for text objects (Edit, Move, Copy, Delete)."""
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QMenu
            from PySide6.QtGui import QCursor
        except ImportError:
            from PyQt5.QtCore import QTimer
            from PyQt5.QtWidgets import QMenu
            from PyQt5.QtGui import QCursor
            
        def _deferred_menu():
            menu = QMenu(self.app)
            menu.setStyleSheet(f"""
                QMenu {{
                    background-color: {_TC.get('bg_secondary')};
                    color: {_TC.get('text_primary')};
                    border: 1px solid {_TC.get('border')};
                    padding: 5px;
                }}
                QMenu::item {{
                    padding: 8px 30px;
                    border-radius: 3px;
                }}
                QMenu::item:selected {{
                    background-color: {_TC.get('bg_button_hover')};
                    color: {_TC.get('text_primary')};
                }}
            """)
            
            edit_action = menu.addAction("✏️ Edit Text")
            move_action = menu.addAction("🔄 Move Text")
            menu.addSeparator()
            copy_action = menu.addAction("📋 Copy Text")
            delete_action = menu.addAction("🗑️ Delete Text")
            
            try:
                action = menu.exec(QCursor.pos())
            except AttributeError:
                action = menu.exec_(QCursor.pos())
            
            if action == edit_action:
                self._edit_text_label(drawing)
            elif action == move_action:
                self._enable_text_dragging(drawing)
            elif action == copy_action:
                self._copy_text_label(drawing)
            elif action == delete_action:
                self._delete_text_label(drawing)
                
        QTimer.singleShot(50, _deferred_menu)
        
    def _on_text_drag_middle_press(self, obj, evt):
        """Handle middle button press during text drag - enable pan."""
        self._text_drag_middle_button_down = True
        self._text_drag_pan_start = self.interactor.GetEventPosition()
        
        # Forward to interactor style for pan
        try:
            style = self.interactor.GetInteractorStyle()
            if style and hasattr(style, 'OnMiddleButtonDown'):
                style.OnMiddleButtonDown()
        except Exception:
            pass
        
        print("🖱️ Pan started during text drag")


    def _on_text_drag_middle_release(self, obj, evt):
        """Handle middle button release during text drag - stop pan."""
        self._text_drag_middle_button_down = False
        self._text_drag_pan_start = None
        
        # Forward to interactor style
        try:
            style = self.interactor.GetInteractorStyle()
            if style and hasattr(style, 'OnMiddleButtonUp'):
                style.OnMiddleButtonUp()
        except Exception:
            pass
        
        print("🛑 Pan stopped during text drag")


    def _on_text_drag_with_pan(self, obj, evt):
        """Update text position while dragging, with pan support."""
        if not getattr(self, "_placing_text", False):
            return
        
        # ✅ If middle button is held, handle pan instead of text drag
        if getattr(self, '_text_drag_middle_button_down', False):
            # Let the interactor style handle the pan
            try:
                style = self.interactor.GetInteractorStyle()
                if style and hasattr(style, 'OnMouseMove'):
                    style.OnMouseMove()
            except Exception:
                pass
            
            # Also manually update camera for smooth panning
            if hasattr(self, '_text_drag_pan_start') and self._text_drag_pan_start:
                current_pos = self.interactor.GetEventPosition()
                dx = current_pos[0] - self._text_drag_pan_start[0]
                dy = current_pos[1] - self._text_drag_pan_start[1]
                
                if abs(dx) > 0 or abs(dy) > 0:
                    camera = self.renderer.GetActiveCamera()
                    focal = camera.GetFocalPoint()
                    cam_pos = camera.GetPosition()
                    
                    self.renderer.SetWorldPoint(focal[0], focal[1], focal[2], 1.0)
                    self.renderer.WorldToDisplay()
                    display_focal = self.renderer.GetDisplayPoint()
                    
                    self.renderer.SetDisplayPoint(
                        display_focal[0] - dx, 
                        display_focal[1] - dy, 
                        display_focal[2]
                    )
                    self.renderer.DisplayToWorld()
                    world_focal = self.renderer.GetWorldPoint()
                    
                    delta_x = world_focal[0] / world_focal[3] - focal[0]
                    delta_y = world_focal[1] / world_focal[3] - focal[1]
                    delta_z = world_focal[2] / world_focal[3] - focal[2]
                    
                    camera.SetFocalPoint(
                        focal[0] + delta_x, 
                        focal[1] + delta_y, 
                        focal[2] + delta_z
                    )
                    camera.SetPosition(
                        cam_pos[0] + delta_x, 
                        cam_pos[1] + delta_y, 
                        cam_pos[2] + delta_z
                    )
                    
                    self._text_drag_pan_start = current_pos
            
            self.app.vtk_widget.render()
            return
        
        # Normal text dragging (when middle button is NOT held)
        pos = self._get_mouse_world_no_snap()
        
        if hasattr(self, "_temp_text_actor") and self._temp_text_actor:
            self._temp_text_actor.SetPosition(pos[0], pos[1], pos[2])
            self.app.vtk_widget.render()


    def _on_text_drag(self, obj, evt):
        """Update scalable text position while dragging."""
        if not getattr(self, "_placing_text", False):
            return
        
        pos = self._get_mouse_world_no_snap()
        
        if hasattr(self, "_temp_text_actor") and self._temp_text_actor:
            self._temp_text_actor.SetPosition(pos[0], pos[1], pos[2])
            self.app.vtk_widget.render()

    def _delete_text_label(self, drawing):
        """Delete a text label from the scene."""
        try:
            self._save_state()
            
            actor = drawing.get('actor')
            if actor:
                if drawing.get('scalable', False):
                    self._remove_actor_from_overlay(actor)
                else:
                    try:
                        self.renderer.RemoveViewProp(actor)
                    except:
                        pass
                    try:
                        self._remove_actor_from_overlay(actor)
                    except:
                        pass
            
            if drawing in self.drawings:
                self.drawings.remove(drawing)
            
            # Clear selection if this was selected
            if getattr(self, 'selected_drawing', None) is drawing:
                self.selected_drawing = None
            
            self._force_render()
            print(f"🗑️ Text label deleted: '{drawing.get('text', 'N/A')}'")
            
        except Exception as e:
            print(f"❌ Failed to delete text: {e}")
            import traceback
            traceback.print_exc()

    def _copy_text_label(self, drawing):
        """Duplicate a scalable text label at the current mouse position."""
        try:
            self._save_state()
            old_actor = drawing["actor"]
            
            new_pos = self._get_mouse_world()
            
            # Get properties from original
            original_color = drawing.get("original_text_color", (1, 1, 1))
            font_size = drawing.get("font_size", 18)
            bold = drawing.get("bold", True)
            font_family = drawing.get("font_family", "Arial")
            text = drawing.get("text", old_actor.GetInput() if hasattr(old_actor, 'GetInput') else "Text")
            
            # Create new scalable text actor
            new_actor = self._make_scalable_text_actor(
                text=text,
                position=new_pos,
                color=original_color,
                font_size=font_size,
                bold=bold,
                font_family=font_family,
                justify='center',
            )
            self._add_actor_to_overlay(new_actor)
            
            entry = {
                "type": "text",
                "coords": [tuple(new_pos)],
                "actor": new_actor,
                "text": text,
                "bounds": new_actor.GetBounds(),
                "original_text_color": original_color,
                "font_size": font_size,
                "bold": bold,
                "font_family": font_family,
                "scalable": True,
            }
            
            self.drawings.append(entry)
            self.app.vtk_widget.render()
            
            self.clear_coordinate_labels()
            self._unhighlight_all_lines()
            self.multi_selected = []
            self.selected_drawing = entry
            
            self.app.vtk_widget.setFocus()
            
            print(f"✅ Scalable text copied.")
            self._enable_text_dragging(entry)
        except Exception as e:
            print(f"❌ Failed to copy text: {e}")
            import traceback
            traceback.print_exc()

    def _edit_text_label(self, drawing):
        """Edit text label with full property support for scalable text."""
        try:
            self._save_state()
            actor = drawing["actor"]
            
            # Get current properties
            if hasattr(actor, 'GetTextProperty'):
                text_prop = actor.GetTextProperty()
                old_text = actor.GetInput()
                old_size = drawing.get('font_size', text_prop.GetFontSize())
                current_color = drawing.get('original_text_color', text_prop.GetColor())
                
                font_family = drawing.get('font_family', 'Arial')
                if not font_family:
                    font_enum = text_prop.GetFontFamily()
                    if font_enum == vtk.VTK_TIMES: font_family = "Times"
                    elif font_enum == vtk.VTK_COURIER: font_family = "Courier"
                    else: font_family = "Arial"
            else:
                old_text = drawing.get('text', 'Text')
                old_size = drawing.get('font_size', 18)
                current_color = drawing.get('original_text_color', (1, 1, 1))
                font_family = drawing.get('font_family', 'Arial')
                
            dialog = TextEditDialog(
                current_text=old_text,
                current_size=old_size,
                current_font=font_family,
                current_bold=drawing.get('bold', True),
                current_italic=False,
                current_color=current_color
            )
            
            try:
                from PySide6.QtWidgets import QDialog
                result = dialog.exec()
            except ImportError:
                from PyQt5.QtWidgets import QDialog
                result = dialog.exec_()
            
            if result == QDialog.Accepted:
                values = dialog.get_values()
                
                # Get current position
                pos = actor.GetPosition()
                
                # Remove old actor
                if drawing.get('scalable', False):
                    self._remove_actor_from_overlay(actor)
                else:
                    try: self.renderer.RemoveViewProp(actor)
                    except: pass
                    try: self._remove_actor_from_overlay(actor)
                    except: pass
                
                # Create new scalable text actor
                new_actor = self._make_scalable_text_actor(
                    text=values['text'],
                    position=pos,
                    color=values['color'],
                    font_size=values['font_size'],
                    bold=values['bold'],
                    font_family=values['font_family'],
                    justify='center',
                )
                self._add_actor_to_overlay(new_actor)
                
                # Update drawing entry
                drawing['actor'] = new_actor
                drawing['text'] = values['text']
                drawing['original_text_color'] = values['color']
                drawing['font_size'] = values['font_size']
                drawing['bold'] = values['bold']
                drawing['font_family'] = values['font_family']
                drawing['scalable'] = True
                drawing['bounds'] = new_actor.GetBounds()
                
                self._force_render()
                print(f"✅ Text updated: '{values['text']}'")
            else:
                print("❌ Text edit cancelled")
                
        except Exception as e:
            print(f"⚠️ Text edit error: {e}")
            import traceback
            traceback.print_exc()
            
    def _edit_line_properties(self, drawing):
        """Open dialog to edit line color and thickness."""
        try:
            self._save_state()
            
            actor = drawing["actor"]
            prop = actor.GetProperty()
            
            old_color = drawing.get("original_color", prop.GetColor())
            old_width = drawing.get("original_width", prop.GetLineWidth())
            
            dialog = LineEditDialog(
                current_color=old_color,
                current_width=int(old_width)
            )
            
            try:
                from PySide6.QtWidgets import QDialog
                result = dialog.exec()
            except ImportError:
                from PyQt5.QtWidgets import QDialog
                result = dialog.exec_()
            
            if result == QDialog.Accepted:
                values = dialog.get_values()
                
                prop.SetColor(*values['color'])
                prop.SetLineWidth(values['width'])
                
                drawing['original_color'] = values['color']
                drawing['original_width'] = values['width']
                
                self.app.vtk_widget.render()
                print(f"🎨 Line updated: color=RGB{values['color']}, width={values['width']}px")
                
        except Exception as e:
            print(f"⚠️ Line edit failed: {e}")
            import traceback
            traceback.print_exc()        
                
   # ============================================================
    # PATCH FIX 3: Corrected _enable_text_dragging for vtkTextActor3D
    # ============================================================

    def _enable_text_dragging(self, text_drawing, suppress_color_change=False):
        """Enable dragging mode for a scalable text label."""
        try:
            self._placing_text = True
            self._temp_text_actor = text_drawing["actor"]
            self._dragging_text_drawing = text_drawing
            
            # Get text property (works for both vtkTextActor3D and vtkBillboardTextActor3D)
            text_prop = text_drawing["actor"].GetTextProperty()
            
            if 'original_text_color' not in text_drawing:
                text_drawing['original_text_color'] = text_prop.GetColor()
            
            # Set yellow color while dragging
            if not suppress_color_change:
                text_prop.SetColor(1, 1, 0)
            
            # ✅ FIX: Use GetTextProperty() for opacity
            text_prop.SetOpacity(0.6)
            
            # AFTER:
            self.interactor.RemoveObservers("MouseMoveEvent")
            self.interactor.RemoveObservers("LeftButtonPressEvent")
            self.interactor.RemoveObservers("MiddleButtonPressEvent")
            self.interactor.RemoveObservers("MiddleButtonReleaseEvent")

            self.interactor.AddObserver("MouseMoveEvent", self._on_text_drag_with_pan, 2.0)
            self.interactor.AddObserver("LeftButtonPressEvent", self._finalize_text_drag, 2.0)
            self.interactor.AddObserver("MiddleButtonPressEvent", self._on_text_drag_middle_press, 10.0)
            self.interactor.AddObserver("MiddleButtonReleaseEvent", self._on_text_drag_middle_release, 10.0)
            
            self.app.vtk_widget.render()
            print("✏️ Text drag enabled - move mouse to reposition, click to place")
            
        except Exception as e:
            print(f"⚠️ Failed to enable text dragging: {e}")
            import traceback
            traceback.print_exc()

    def _refresh_segment_markers(self):
        """Ensure correct coloring for all segment endpoints after deletion, and detect closed loops."""
        from collections import Counter, defaultdict

        segment_points = []
        adjacency = defaultdict(set)
        for d in self.drawings:
            if d.get("type") == "line_segment":
                p1, p2 = tuple(d["coords"][0]), tuple(d["coords"][-1])
                segment_points.extend([p1, p2])
                adjacency[p1].add(p2)
                adjacency[p2].add(p1)

        vertex_counts = Counter(segment_points)

        is_closed_loop = all(len(neighbors) == 2 for neighbors in adjacency.values()) and len(adjacency) > 2

        for d in self.drawings:
            if d.get("type") != "line_segment":
                continue

            start = tuple(d["coords"][0])
            end = tuple(d["coords"][-1])

            for key in ("start_marker", "end_marker"):
                if key in d and d[key]:
                    try:
                        self._remove_actor_from_overlay(d[key])
                    except Exception:
                        pass
                    d[key] = None

            if is_closed_loop:
                color = (1, 1, 0)
                d["start_marker"] = self._add_endpoint_sphere(start, color=color)
                d["end_marker"] = self._add_endpoint_sphere(end, color=color)
            else:
                start_color = (1, 1, 0) if vertex_counts[start] > 1 else (0, 1, 0)
                end_color = (1, 1, 0) if vertex_counts[end] > 1 else (1, 0, 0)
                d["start_marker"] = self._add_endpoint_sphere(start, color=start_color)
                d["end_marker"] = self._add_endpoint_sphere(end, color=end_color)

        self.renderer.Modified()
        self.app.vtk_widget.render()

        if is_closed_loop:
            print("🔁 Closed ring detected — all endpoints set to yellow")
        else:
            print("🎨 Endpoint markers refreshed (Green=start, Red=end, Yellow=shared)")

    def _display_to_world(self, x, y):
        """Convert display (x, y) coordinates to world coordinates using the renderer."""
        picker = vtk.vtkWorldPointPicker()
        picker.Pick(x, y, 0, self.renderer)
        world_pos = picker.GetPickPosition()
        return world_pos

    def add_drawing_from_data(self, drawing_data: dict):
        """Add a drawing from imported data (DXF, GeoJSON, Shapefile)."""
        try:
            shape_type = drawing_data.get('type')
            coords = drawing_data.get('coordinates') or drawing_data.get('coords', [])
            color = drawing_data.get('color', (255, 255, 255))
            
            if not coords:
                print(f"⚠️ No coordinates for {shape_type}")
                return False
            
            print(f"🔍 Importing {shape_type} with {len(coords)} points")
            
            if isinstance(color, (list, tuple)) and len(color) == 3:
                if all(c <= 1.0 for c in color):
                    color_vtk = color
                else:
                    color_vtk = tuple(c / 255.0 for c in color)
            else:
                color_vtk = (1.0, 0.0, 0.0)
            
            actor = None
            
            if shape_type == 'circle':
                if len(coords) == 1:
                    center = coords[0]
                    radius = drawing_data.get('radius', 5.0)
                    
                    cx, cy, cz = center[0], center[1], center[2] if len(center) > 2 else 0
                    
                    if radius < 10:
                        n = 64
                    elif radius < 50:
                        n = 128
                    else:
                        n = 180
                    
                    thetas = np.linspace(0, 2 * np.pi, n, endpoint=False)
                    circle_coords = [
                        (cx + radius * np.cos(t), cy + radius * np.sin(t), cz) 
                        for t in thetas
                    ]
                    circle_coords.append(circle_coords[0])
                    coords = circle_coords
                    
                elif len(coords) >= 3:
                    if coords[0] != coords[-1]:
                        coords = list(coords) + [coords[0]]
                else:
                    print(f"⚠️ Circle needs either 1 point (center) or 3+ points (outline)")
                    return False
                
                actor = self._make_polyline_actor(coords, color=color_vtk, width=3)
            
            elif shape_type == 'rectangle':
                if len(coords) == 5:
                    actor = self._make_polyline_actor(coords, color=color_vtk, width=3)
                elif len(coords) >= 2:
                    p1, p2 = coords[0], coords[1]
                    rect_coords = [
                        (p1[0], p1[1], p1[2] if len(p1) > 2 else 0),
                        (p2[0], p1[1], p1[2] if len(p1) > 2 else 0),
                        (p2[0], p2[1], p2[2] if len(p2) > 2 else 0),
                        (p1[0], p2[1], p2[2] if len(p2) > 2 else 0),
                        (p1[0], p1[1], p1[2] if len(p1) > 2 else 0)
                    ]
                    coords = rect_coords
                    actor = self._make_polyline_actor(rect_coords, color=color_vtk, width=3)
                else:
                    return False
            
            elif shape_type in ['polyline', 'polygon']:
                if len(coords) >= 3:
                    if coords[0] != coords[-1]:
                        coords = list(coords) + [coords[0]]
                    actor = self._make_polyline_actor(coords, color=color_vtk, width=3)
                else:
                    return False
            
            elif shape_type in ['line', 'line_segment']:
                if len(coords) >= 2:
                    actor = self._make_polyline_actor(coords, color=color_vtk, width=3)
                else:
                    return False
            
            else:
                if len(coords) >= 2:
                    actor = self._make_polyline_actor(coords, color=color_vtk, width=3)
                else:
                    return False
            
            if actor:
                actor.PickableOn()
                actor.VisibilityOn()
                
                self._add_actor_to_overlay(actor)
                
                drawing = {
                    'type': shape_type,
                    'coords': coords,
                    'coordinates': coords,
                    'actor': actor,
                    'bounds': actor.GetBounds(),
                    'original_color': color_vtk,
                    'original_width': 3,
                    'color': color,
                    'text': drawing_data.get('text', ''),
                    'radius': drawing_data.get('radius', 0)
                }
                
                self.drawings.append(drawing)
                print(f"✅ Added {shape_type} to scene\n")
                return True
            else:
                print(f"⚠️ Failed to create actor for {shape_type}\n")
                return False
                
        except Exception as e:
            print(f"❌ Failed to add drawing from data: {e}")
            import traceback
            traceback.print_exc()
            return False

    def select_drawing_at_position(self, x: float, y: float):
        """Select a drawing near the clicked position."""
        try:
            picker = vtk.vtkPropPicker()
            picker.Pick(x, y, 0, self.app.vtk_widget.renderer)
            
            picked_prop = picker.GetViewProp()
            
            if picked_prop:
                for drawing in self.drawings:
                    if drawing.get('actor') == picked_prop:
                        print(f"✅ Selected {drawing['type']}")
                        return drawing
            
            return None
            
        except Exception as e:
            print(f"⚠️ Selection failed: {e}")
            return None

    def delete_selected_drawing(self, drawing: dict):
        """Delete a drawing from the scene."""
        try:
            if drawing in self.drawings:
                actor = drawing.get('actor')
                if actor:
                    if drawing.get("type") == "text":
                        self.renderer.RemoveActor(actor)
                    else:
                        self._remove_actor_from_overlay(actor)
                
                self.drawings.remove(drawing)
                self.app.vtk_widget.render()
                
                print(f"🗑️ Deleted {drawing['type']}")
                return True
            else:
                print("⚠️ Drawing not found")
                return False
                
        except Exception as e:
            print(f"❌ Delete failed: {e}")
            return False

    def get_drawing_info(self, drawing: dict) -> str:
        """Get human-readable info about a drawing."""
        shape_type = drawing.get('type', 'unknown')
        coords = drawing.get('coordinates', [])
        
        if shape_type == 'line':
            return f"Line: 2 points"
        elif shape_type in ['polyline', 'freehand']:
            return f"Polyline: {len(coords)} points"
        elif shape_type == 'polygon':
            return f"Polygon: {len(coords)} vertices"
        elif shape_type == 'circle':
            radius = drawing.get('radius', 0)
            return f"Circle: radius={radius:.2f}m"
        elif shape_type == 'rectangle':
            return f"Rectangle"
        elif shape_type == 'text':
            text = drawing.get('text', '')
            return f"Text: '{text}'"
        else:
            return f"Unknown: {shape_type}"
        
    def _deactivate_active_tool_keep_drawings(self):
        """
        ESC behavior: Exit/deactivate current tool.
        Cancel ONLY in-progress preview. KEEP all already drawn lines.
        """
        tool = getattr(self, "active_tool", None)
        if not tool or tool == "none":
            return False

        if tool in ("smartline", "line"):
            self._cancel_smart_line()

        elif tool == "movevertex":
            self._deactivate_move_vertex_mode()
            self.interactor.RemoveObservers("RightButtonPressEvent")
            self.interactor.RemoveObservers("MiddleButtonPressEvent")
            self.interactor.RemoveObservers("MiddleButtonReleaseEvent")
            self.interactor.AddObserver("RightButtonPressEvent", self._on_right_press, 1.0)
            self.interactor.AddObserver("MiddleButtonPressEvent", self._on_middle_press, 1.0)
            self.interactor.AddObserver("MiddleButtonReleaseEvent", self._on_middle_release, 1.0)

        elif tool == "freehand":
            self._remove_preview_actor_2d('_freehand_preview_actor_2d')
            self._remove_preview_actor_2d('_preview_actor')
            self.is_drawing_freehand = False
            self.left_down = False
            self.temp_points = []

        elif tool == "circle":
            self._remove_preview_actor_2d('_circle_preview_actor_2d')
            self._remove_preview_actor_2d('_circle_preview_actor')
            self.temp_points = []

        elif tool == "rectangle":
            self._remove_preview_actor_2d('_rectangle_preview_actor')
            self.temp_points = []

        elif tool == "polyline":
            self._remove_preview_actor_2d('_preview_line_actor')
            self._remove_preview_actor_2d('_continuous_line_actor')
            self.temp_points = []

        elif tool == "text":
            dragging_text = getattr(self, "_dragging_text_drawing", None)
            if dragging_text and dragging_text.get("actor") is not None:
                try:
                    text_prop = dragging_text["actor"].GetTextProperty()
                    if 'original_text_color' in dragging_text:
                        text_prop.SetColor(*dragging_text['original_text_color'])
                    text_prop.SetOpacity(1.0)
                except Exception:
                    pass

            if getattr(self, '_temp_text_actor', None) and not dragging_text:
                try:
                    self._remove_actor_from_overlay(self._temp_text_actor)
                except Exception:
                    pass
            self._temp_text_actor = None
            self._placing_text = False
            self._pending_text_config = None
            if hasattr(self, "_temp_text_color"):
                delattr(self, "_temp_text_color")
            if hasattr(self, "_dragging_text_drawing"):
                self._dragging_text_drawing = None

            self.interactor.RemoveObservers("MouseMoveEvent")
            self.interactor.RemoveObservers("LeftButtonPressEvent")
            self.interactor.RemoveObservers("LeftButtonReleaseEvent")
            self.interactor.RemoveObservers("RightButtonPressEvent")
            self.interactor.RemoveObservers("MiddleButtonPressEvent")
            self.interactor.RemoveObservers("MiddleButtonReleaseEvent")
            self.interactor.AddObserver("LeftButtonPressEvent", self._on_left_press, 1.0)
            self.interactor.AddObserver("MouseMoveEvent", self._on_mouse_move, 1.0)
            self.interactor.AddObserver("LeftButtonReleaseEvent", self._on_left_release, 1.0)
            self.interactor.AddObserver("RightButtonPressEvent", self._on_right_press, 1.0)
            self.interactor.AddObserver("MiddleButtonPressEvent", self._on_middle_press, 1.0)
            self.interactor.AddObserver("MiddleButtonReleaseEvent", self._on_middle_release, 1.0)

        else:
            self._remove_preview_actor_2d('_preview_line_actor')
            self._remove_preview_actor_2d('_continuous_line_actor')
            self._remove_preview_actor_2d('_rectangle_preview_actor')
            self.temp_points = []

        for attr in ('_smartline_vertex_markers', '_line_vertex_markers', '_polyline_vertex_markers'):
            markers = getattr(self, attr, [])
            for marker in markers:
                try:
                    self._remove_actor_from_overlay(marker)
                except Exception:
                    pass
            setattr(self, attr, [])

        self.left_down = False
        self.middle_down = False
        self._clear_temp_vertex_history()
        self.active_tool = None
        if hasattr(self.app, 'set_cross_cursor_active'):
            self.app.set_cross_cursor_active(False, "draw")
        self._restore_shared_interactor_observers()
        self.app.vtk_widget.render()
        print(f"✅ {tool} exited — tool deactivated (drawings kept)")
        return True

        
    def _cancel_active_tool(self):
        """Cancel/deactivate the currently active digitize tool (if any)."""
        tool = getattr(self, "active_tool", None)
        if not tool or tool == "none":
            return False

        if tool in ("smartline", "line"):
            self._cancel_smart_line()

        elif tool == "freehand":
            self._remove_preview_actor_2d('_freehand_preview_actor_2d')
            self._remove_preview_actor_2d('_preview_actor')
                
            self.is_drawing_freehand = False
            self.left_down = False
            self.temp_points = []

        elif tool == "circle":
            self._remove_preview_actor_2d('_circle_preview_actor_2d')
            self._remove_preview_actor_2d('_circle_preview_actor')
            
            self.temp_points = []

        else:
            self._remove_preview_actor_2d('_preview_line_actor')
            self.temp_points = []

        self._clear_temp_vertex_history()
        self.active_tool = None
        try:
            self.app.statusBar().showMessage(f"{tool} cancelled")
        except Exception:
            pass
        self.app.vtk_widget.render()
        print(f"❌ {tool} cancelled — tool deactivated")
        return True     
        

    def _rebuild_active_preview(self):
        """Rebuild screen-space preview after undo — immediate visual update, no blink."""

        if len(self.temp_points) < 2:
            # Hide actors instead of removing them
            for attr in ('_continuous_line_actor', '_preview_line_actor'):
                actor = getattr(self, attr, None)
                if actor is not None:
                    actor.SetVisibility(0)
            self.app.vtk_widget.render()
            return

        if self.active_tool == "smartline":
            s = self._get_draw_style('smartline')
            color = s['color']
        elif self.active_tool == "line":
            s = self._get_draw_style('line')
            color = s['color']
        elif self.active_tool == "polyline":
            s = self._get_draw_style('polyline')
            color = s['color']
        else:
            return

        self._update_continuous_preview(color=color, width=s['width'], line_style=s['style'])

        if self.active_tool == "polyline":
            self._update_cursor_preview(color=color, width=s['width'], line_style='dotted', close_loop=True)
        else:
            self._update_cursor_preview(color=color, width=s['width'], line_style=s['style'])

        self.app.vtk_widget.render()
            
        
    def _get_drawing_under_cursor(self, mouse_x, mouse_y, tolerance=25.0):
        """
        Mathematic Picker with Debugging.
        Projects every line segment to the screen and checks distance.
        """
        best_drawing = None
        min_dist = tolerance

        for d_idx, d in enumerate(self.drawings):
            coords = d.get('coords', [])
            dtype = d.get('type', 'unknown')
            
            if not coords:
                continue
                
            # ✅ Handle 1-point objects like TEXT
            if dtype == 'text' and len(coords) == 1:
                actor = d.get('actor')
                hit = False

                # Try bounding box test first (works when zoomed in and anchor is off-screen)
                if actor:
                    try:
                        bounds = actor.GetBounds()  # (xmin,xmax,ymin,ymax,zmin,zmax)
                        corners = [
                            (bounds[0], bounds[2], bounds[4]),
                            (bounds[1], bounds[2], bounds[4]),
                            (bounds[0], bounds[3], bounds[4]),
                            (bounds[1], bounds[3], bounds[4]),
                        ]
                        sx_vals, sy_vals = [], []
                        for c in corners:
                            self.renderer.SetWorldPoint(c[0], c[1], c[2], 1.0)
                            self.renderer.WorldToDisplay()
                            dp = self.renderer.GetDisplayPoint()
                            sx_vals.append(dp[0])
                            sy_vals.append(dp[1])
                        bx_min, bx_max = min(sx_vals), max(sx_vals)
                        by_min, by_max = min(sy_vals), max(sy_vals)
                        # Expand by tolerance
                        bx_min -= tolerance; bx_max += tolerance
                        by_min -= tolerance; by_max += tolerance
                        if bx_min <= mouse_x <= bx_max and by_min <= mouse_y <= by_max:
                            dist = 0.0  # inside box = direct hit
                            hit = True
                    except Exception:
                        pass

                # Fallback: anchor point distance (original logic)
                if not hit:
                    p_world = coords[0]
                    self.renderer.SetWorldPoint(p_world[0], p_world[1], p_world[2], 1.0)
                    self.renderer.WorldToDisplay()
                    display_p = self.renderer.GetDisplayPoint()
                    screen_p = np.array(display_p[:2])
                    mouse_p = np.array([mouse_x, mouse_y])
                    dist = np.linalg.norm(mouse_p - screen_p)
                    hit = dist < (tolerance * 5)

                if hit and dist < min_dist:
                    min_dist = dist
                    best_drawing = d
                continue

            if len(coords) < 2: continue
            
            for i in range(len(coords) - 1):
                p1_world = coords[i]
                p2_world = coords[i+1]

                self.renderer.SetWorldPoint(p1_world[0], p1_world[1], p1_world[2], 1.0)
                self.renderer.WorldToDisplay()
                display_p1 = self.renderer.GetDisplayPoint()
                s1 = np.array(display_p1[:2]) 

                self.renderer.SetWorldPoint(p2_world[0], p2_world[1], p2_world[2], 1.0)
                self.renderer.WorldToDisplay()
                display_p2 = self.renderer.GetDisplayPoint()
                s2 = np.array(display_p2[:2])

                dist = self._distance_point_to_segment_2d(np.array([mouse_x, mouse_y]), s1, s2)

                if dist < min_dist:
                    min_dist = dist
                    best_drawing = d
        
        if best_drawing:
            print(f"🎯 Math Picker SELECTED: {best_drawing.get('type')} (Dist: {min_dist:.2f}px)")
        
        return best_drawing

    def _distance_point_to_segment_2d(self, p, a, b):
        """Calculates closest distance from point P to segment A-B in 2D."""
        ab = b - a
        len_sq = np.dot(ab, ab)
        
        if len_sq == 0:
            return np.linalg.norm(p - a)

        t = np.dot(p - a, ab) / len_sq
        t = max(0, min(1, t))

        projection = a + t * ab
        return np.linalg.norm(p - projection)

    def _add_arrow_to_line(self, coords):
        """Add 2D screen-space arrows to a line."""
        if len(coords) < 2:
            return None
        
        arrow_actors = []
        
        try:
            renderer = self.renderer
            
            for i in range(len(coords) - 1):
                p1_world = np.array(coords[i])
                p2_world = np.array(coords[i+1])
                midpoint = (p1_world + p2_world) / 2.0
                
                renderer.SetWorldPoint(p1_world[0], p1_world[1], p1_world[2], 1.0)
                renderer.WorldToDisplay()
                d1 = np.array(renderer.GetDisplayPoint()[:2])
                
                renderer.SetWorldPoint(p2_world[0], p2_world[1], p2_world[2], 1.0)
                renderer.WorldToDisplay()
                d2 = np.array(renderer.GetDisplayPoint()[:2])
                
                dx, dy = d2[0] - d1[0], d2[1] - d1[1]
                
                if np.hypot(dx, dy) < 20.0: 
                    continue 
                    
                angle_deg = np.degrees(np.arctan2(dy, dx))
                
                arrow_src = vtk.vtkGlyphSource2D()
                arrow_src.SetGlyphTypeToArrow()
                arrow_src.SetScale(15.0)
                arrow_src.SetFilled(True)
                arrow_src.Update()
                
                transform = vtk.vtkTransform()
                transform.RotateZ(angle_deg)
                transform.Translate(-7.5, 0, 0)
                
                tf = vtk.vtkTransformPolyDataFilter()
                tf.SetInputConnection(arrow_src.GetOutputPort())
                tf.SetTransform(transform)
                tf.Update()
                
                mapper = vtk.vtkPolyDataMapper2D()
                mapper.SetInputConnection(tf.GetOutputPort())
                
                actor = vtk.vtkActor2D()
                actor.SetMapper(mapper)
                
                actor.GetPositionCoordinate().SetCoordinateSystemToWorld()
                actor.GetPositionCoordinate().SetValue(midpoint[0], midpoint[1], midpoint[2])
                
                actor.GetProperty().SetColor(1, 0, 0)
                
                renderer.AddActor2D(actor)
                arrow_actors.append(actor)
                
            print(f"  ➡️ Added {len(arrow_actors)} fixed-size 2D direction arrows")
            return arrow_actors
            
        except Exception as e:
            print(f"⚠️ Failed to create 2D arrows: {e}")
            return None

    def _activate_move_vertex_mode(self):
        """Activate vertex move mode.
        ✅ FIX: Preserves middle-button pan by NOT removing MouseMoveEvent
        and by tracking middle button state.
        """
        self.vertex_moving = True
        self.moving_vertex_data = None
        self._middle_button_down = False
        
        mode = getattr(self, 'vertex_move_mode_type', 'click')
        
        if mode == 'drag':
            print("🖱️ Drag mode: Click and hold to move vertices")
        else:
            print("🖱️ Click mode: Click to select, click again to place")
        
        # ✅ Only remove LEFT button observers — never touch middle button or mouse move
        self.interactor.RemoveObservers("LeftButtonPressEvent")
        self.interactor.RemoveObservers("LeftButtonReleaseEvent")
        
        # Add our left button handlers
        self.interactor.AddObserver("LeftButtonPressEvent", self._on_move_vertex_press, 1.0)
        self.interactor.AddObserver("LeftButtonReleaseEvent", self._on_move_vertex_release, 1.0)
        
        # ✅ Add mouse move WITH middle button awareness (don't remove existing ones)
        self.interactor.AddObserver("MouseMoveEvent", self._on_move_vertex_hover, 1.0)
        
        # ✅ Track middle button for pan detection
        self.interactor.AddObserver("MiddleButtonPressEvent", self._on_move_middle_press, 10.0)
        self.interactor.AddObserver("MiddleButtonReleaseEvent", self._on_move_middle_release, 10.0)
        
        try:
            self.app.statusBar().showMessage(
                "🔄 Move Vertex Mode - Click near a vertex to move it (ESC to exit)")
        except:
            pass


    def _on_move_middle_press(self, obj, evt):
        """Track middle button down — let interactor style handle pan."""
        self._middle_button_down = True
        # ✅ Forward to interactor style so pan actually works
        try:
            style = self.interactor.GetInteractorStyle()
            if style:
                style.OnMiddleButtonDown()
        except Exception:
            pass


    def _on_move_middle_release(self, obj, evt):
        """Track middle button up."""
        self._middle_button_down = False
        try:
            style = self.interactor.GetInteractorStyle()
            if style:
                style.OnMiddleButtonUp()
        except Exception:
            pass


    def _on_move_vertex_hover(self, obj, evt):
        """Show cyan highlight when hovering over vertices.
        ✅ FIX: When middle button is held, forward to style for pan."""
        
        # ✅ If middle button is held → user is panning, don't interfere
        if getattr(self, '_middle_button_down', False):
            try:
                style = self.interactor.GetInteractorStyle()
                if style:
                    style.OnMouseMove()
            except Exception:
                pass
            return
        
        if self.moving_vertex_data:
            self._on_move_vertex_drag(obj, evt)
            return
        
        x, y = self.interactor.GetEventPosition()
        nearest_vertex, nearest_drawing, vertex_idx = self._find_nearest_vertex_at_position(
            x, y, tolerance=15.0)
        
        if nearest_vertex is not None:
            if not hasattr(self, 'vertex_hover_marker') or not self.vertex_hover_marker:
                self.vertex_hover_marker = self._add_endpoint_sphere(
                    nearest_vertex, color=(0, 1, 1), radius=0.12
                )
            else:
                self.vertex_hover_marker.SetPosition(*nearest_vertex)
                self.vertex_hover_marker.SetVisibility(True)
            self.app.vtk_widget.render()
        else:
            if hasattr(self, 'vertex_hover_marker') and self.vertex_hover_marker:
                self.vertex_hover_marker.SetVisibility(False)
                self.app.vtk_widget.render()



    def _on_move_vertex_press(self, obj, evt):
        """Handle vertex selection for moving"""
        x, y = self.interactor.GetEventPosition()
        nearest_vertex, nearest_drawing, vertex_idx = self._find_nearest_vertex_at_position(x, y, tolerance=15.0)
        
        if nearest_vertex is None or nearest_drawing is None:
            print("⚪ No vertex found near click")
            return
        
        mode = getattr(self, 'vertex_move_mode_type', 'click')
        
        if mode == 'click' and self.moving_vertex_data:
            new_pos = self._get_mouse_world()
            self._finalize_vertex_move(new_pos)
            return
        
        self._save_state()
        
        self.moving_vertex_data = {
            'drawing': nearest_drawing,
            'vertex_index': vertex_idx,
            'original_pos': nearest_vertex
        }
        
        if hasattr(self, 'vertex_drag_marker') and self.vertex_drag_marker:
            self._remove_actor_from_overlay(self.vertex_drag_marker)
        
        self.vertex_drag_marker = self._add_endpoint_sphere(
            nearest_vertex, color=(1, 1, 0), radius=0.14
        )
        
        if hasattr(self, 'vertex_hover_marker') and self.vertex_hover_marker:
            self.vertex_hover_marker.SetVisibility(False)
        
        print(f"🔵 Moving vertex {vertex_idx} of {nearest_drawing['type']}")
        self.app.vtk_widget.render()


    def _on_move_vertex_drag(self, obj, evt):
        """Update vertex position while moving"""
        if not self.moving_vertex_data:
            return
        
        new_pos = self._get_mouse_world()
        
        drawing = self.moving_vertex_data['drawing']
        vertex_idx = self.moving_vertex_data['vertex_index']
        
        coords = drawing['coords']
        coords[vertex_idx] = tuple(new_pos)
        
        if hasattr(self, 'vertex_drag_marker') and self.vertex_drag_marker:
            self.vertex_drag_marker.SetPosition(*new_pos)
        
        self._rebuild_drawing_actor(drawing)
        
        if hasattr(self, 'selected_drawing') and self.selected_drawing is drawing:
            self.clear_coordinate_labels()
            self.show_vertex_coordinates(coords)
        
        self.app.vtk_widget.render()


    def _on_move_vertex_release(self, obj, evt):
        """Handle mouse release for drag mode"""
        mode = getattr(self, 'vertex_move_mode_type', 'click')
        
        if mode == 'drag' and self.moving_vertex_data:
            new_pos = self._get_mouse_world()
            self._finalize_vertex_move(new_pos)


    def _finalize_vertex_move(self, new_pos):
        """Complete the vertex move operation"""
        if not self.moving_vertex_data:
            return
        
        drawing = self.moving_vertex_data['drawing']
        vertex_idx = self.moving_vertex_data['vertex_index']
        
        coords = drawing['coords']
        coords[vertex_idx] = tuple(new_pos)
        
        print(f"✅ Vertex {vertex_idx} moved to {new_pos}")
        
        if hasattr(self, 'vertex_drag_marker') and self.vertex_drag_marker:
            self._remove_actor_from_overlay(self.vertex_drag_marker)
            self.vertex_drag_marker = None
        
        self._rebuild_drawing_actor(drawing)
        self.moving_vertex_data = None
        self.app.vtk_widget.render()


    def _deactivate_move_vertex_mode(self):
        """Exit move vertex mode.
        ✅ FIX: Clean up middle button observers too."""
        self.vertex_moving = False
        self.moving_vertex_data = None
        self._middle_button_down = False
        
        if hasattr(self, 'vertex_hover_marker') and self.vertex_hover_marker:
            self._remove_actor_from_overlay(self.vertex_hover_marker)
            self.vertex_hover_marker = None
        
        if hasattr(self, 'vertex_drag_marker') and self.vertex_drag_marker:
            self._remove_actor_from_overlay(self.vertex_drag_marker)
            self.vertex_drag_marker = None
        
        # ✅ Remove only our observers
        self.interactor.RemoveObservers("LeftButtonPressEvent")
        self.interactor.RemoveObservers("LeftButtonReleaseEvent")
        self.interactor.RemoveObservers("MouseMoveEvent")
        self.interactor.RemoveObservers("MiddleButtonPressEvent")
        self.interactor.RemoveObservers("MiddleButtonReleaseEvent")
        
        # Restore normal drawing observers
        self.interactor.AddObserver("LeftButtonPressEvent", self._on_left_press, 1.0)
        self.interactor.AddObserver("MouseMoveEvent", self._on_mouse_move, 1.0)
        self.interactor.AddObserver("LeftButtonReleaseEvent", self._on_left_release, 1.0)
        self._restore_shared_interactor_observers()
        
        print("⚪ Move Vertex mode deactivated")
        self.app.vtk_widget.render()
        
class LineEditDialog(QDialog):
    """Custom dialog for editing line properties (color and thickness)."""
    
    def __init__(self, current_color=(1, 0, 0), current_width=2, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Line Properties")
        self.setModal(True)
        self.resize(350, 200)
        self.setProperty("themeStyledDialog", True)
        self.setStyleSheet(get_dialog_stylesheet())
        
        layout = QVBoxLayout()
        
        props_group = QGroupBox("Line Properties")
        props_layout = QVBoxLayout()
        
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("Thickness:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 20)
        self.width_spin.setValue(current_width)
        self.width_spin.setSuffix(" px")
        width_layout.addWidget(self.width_spin)
        width_layout.addStretch()
        props_layout.addLayout(width_layout)
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        
        self.color_button = QPushButton()
        self.color_button.setFixedSize(80, 30)
        self.current_color = (
            int(current_color[0] * 255),
            int(current_color[1] * 255),
            int(current_color[2] * 255)
        )
        self._update_color_button()
        self.color_button.clicked.connect(self._pick_color)
        color_layout.addWidget(self.color_button)
        color_layout.addStretch()
        props_layout.addLayout(color_layout)
        
        props_group.setLayout(props_layout)
        layout.addWidget(props_group)
        
        button_layout = QHBoxLayout()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def _update_color_button(self):
        r, g, b = self.current_color
        self.color_button.setStyleSheet(f"""
            QPushButton {{
                background-color: rgb({r}, {g}, {b});
                border: 2px solid {_TC.get('border_light')};
                border-radius: 3px;
            }}
        """)
    
    def _pick_color(self):
        try:
            from PySide6.QtWidgets import QColorDialog
            from PySide6.QtGui import QColor
        except ImportError:
            from PyQt5.QtWidgets import QColorDialog
            from PyQt5.QtGui import QColor
        
        initial_color = QColor(*self.current_color)
        color = QColorDialog.getColor(initial_color, self, "Choose Line Color")
        
        if color.isValid():
            self.current_color = (color.red(), color.green(), color.blue())
            self._update_color_button()
    
    def get_values(self):
        vtk_color = (
            self.current_color[0] / 255.0,
            self.current_color[1] / 255.0,
            self.current_color[2] / 255.0
        )
        
        return {
            'color': vtk_color,
            'width': self.width_spin.value()
        }
        
    def enable_pan_while_drawing(self):
        try:
            from vtkmodules.vtkInteractionStyle import vtkInteractorStyleUser
            current_style = self.interactor.GetInteractorStyle()
            if hasattr(current_style, 'SetMiddleButtonPressEvent'):
                print("✅ Pan while drawing enabled (middle mouse button)")
            else:
                print("⚠️ Current interactor doesn't support pan while drawing")
        except Exception as e:
            print(f"⚠️ Failed to enable pan while drawing: {e}")      
        

class TextEditDialog(QDialog):
    """Custom dialog for editing text labels with font controls and color picker."""
    
    def __init__(self, current_text="", current_size=40, current_font="Arial",
                 current_bold=False, current_italic=False, current_color=(1, 1, 0), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Text Label")
        self.setModal(True)
        self.resize(400, 320)
        self.setProperty("themeStyledDialog", True)
        self.setStyleSheet(get_dialog_stylesheet())
        
        layout = QVBoxLayout()
        
        text_group = QGroupBox("Text Content")
        text_layout = QVBoxLayout()
        self.text_input = QLineEdit(current_text)
        self.text_input.setPlaceholderText("Enter text here...")
        text_layout.addWidget(self.text_input)
        text_group.setLayout(text_layout)
        layout.addWidget(text_group)
        
        font_group = QGroupBox("Font Settings")
        font_layout = QVBoxLayout()
        
        font_family_layout = QHBoxLayout()
        font_family_layout.addWidget(QLabel("Font:"))
        self.font_combo = QComboBox()
        self.font_combo.addItems([
            "Arial", "Arial Black", "Arial Narrow",
            "Times New Roman", "Georgia", "Palatino Linotype",
            "Courier New", "Courier", "Lucida Console",
            "Verdana", "Tahoma", "Trebuchet MS",
            "Impact", "Comic Sans MS",
            "Calibri", "Cambria", "Segoe UI",
            "Helvetica", "Century Gothic", "Franklin Gothic Medium",
        ])
        # Set current font if it matches
        index = self.font_combo.findText(current_font, Qt.MatchContains)
        if index >= 0:
            self.font_combo.setCurrentIndex(index)
        font_family_layout.addWidget(self.font_combo)
        font_layout.addLayout(font_family_layout)
        
        font_size_layout = QHBoxLayout()
        font_size_layout.addWidget(QLabel("Size:"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 72)
        self.size_spin.setValue(current_size)
        self.size_spin.setSuffix(" pt")
        font_size_layout.addWidget(self.size_spin)
        font_size_layout.addStretch()
        font_layout.addLayout(font_size_layout)
        
        style_layout = QHBoxLayout()
        self.bold_check = QCheckBox("Bold")
        self.bold_check.setChecked(current_bold)
        self.italic_check = QCheckBox("Italic")
        self.italic_check.setChecked(current_italic)
        style_layout.addWidget(self.bold_check)
        style_layout.addWidget(self.italic_check)
        style_layout.addStretch()
        font_layout.addLayout(style_layout)
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        
        self.color_button = QPushButton()
        self.color_button.setFixedSize(60, 30)
        self.current_color = (
            int(current_color[0] * 255),
            int(current_color[1] * 255),
            int(current_color[2] * 255)
        )
        self._update_color_button()
        self.color_button.clicked.connect(self._pick_color)
        color_layout.addWidget(self.color_button)
        color_layout.addStretch()
        font_layout.addLayout(color_layout)
        
        font_group.setLayout(font_layout)
        layout.addWidget(font_group)
        
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def _update_color_button(self):
        r, g, b = self.current_color
        self.color_button.setStyleSheet(f"""
            QPushButton {{
                background-color: rgb({r}, {g}, {b});
                border: 2px solid {_TC.get('border_light')};
                border-radius: 3px;
            }}
        """)
    
    def _pick_color(self):
        try:
            from PySide6.QtWidgets import QColorDialog
            from PySide6.QtGui import QColor
        except ImportError:
            from PyQt5.QtWidgets import QColorDialog
            from PyQt5.QtGui import QColor
        
        initial_color = QColor(*self.current_color)
        color = QColorDialog.getColor(initial_color, self, "Choose Text Color")
        
        if color.isValid():
            self.current_color = (color.red(), color.green(), color.blue())
            self._update_color_button()
    
    def get_values(self):
        vtk_color = (
            self.current_color[0] / 255.0,
            self.current_color[1] / 255.0,
            self.current_color[2] / 255.0
        )
        
        return {
            'text': self.text_input.text(),
            'font_family': self.font_combo.currentText(),
            'font_size': self.size_spin.value(),
            'bold': self.bold_check.isChecked(),
            'italic': self.italic_check.isChecked(),
            'color': vtk_color
        }


class PolylineSettingsDialog(QDialog):
    """Settings dialog for Polyline drawing mode"""
    
    def __init__(self, current_permanent=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Polyline Settings")
        self.setModal(True)
        self.resize(300, 150)
        
        layout = QVBoxLayout()
        
        mode_group = QGroupBox("Drawing Mode")
        mode_layout = QVBoxLayout()
        
        self.temp_radio = QRadioButton("Temporary (finishes on right-click)")
        self.permanent_radio = QRadioButton("Permanent (stays active)")
        
        if current_permanent or True:   # always default to permanent
            self.permanent_radio.setChecked(True)
        else:
            self.temp_radio.setChecked(True)
        
        mode_layout.addWidget(self.temp_radio)
        mode_layout.addWidget(self.permanent_radio)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
        
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def get_permanent_mode(self):
        return self.permanent_radio.isChecked()
    
    
class LineArrowSettingsDialog(QDialog):
    """Settings dialog for Line/SmartLine arrow direction"""
    
    def __init__(self, tool_name="Line", current_arrow=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{tool_name} Arrow Settings")
        self.setModal(True)
        self.resize(350, 180)
        self.setProperty("themeStyledDialog", True)
        self.setStyleSheet(get_dialog_stylesheet())
        
        layout = QVBoxLayout()
        
        arrow_group = QGroupBox("Direction Arrow")
        arrow_layout = QVBoxLayout()
        
        self.no_arrow_radio = QRadioButton("No arrow (simple line)")
        self.with_arrow_radio = QRadioButton("With arrow (shows drawing direction)")
        
        if current_arrow:
            self.with_arrow_radio.setChecked(True)
        else:
            self.no_arrow_radio.setChecked(True)
        
        arrow_layout.addWidget(self.no_arrow_radio)
        arrow_layout.addWidget(self.with_arrow_radio)
        arrow_group.setLayout(arrow_layout)
        layout.addWidget(arrow_group)
        
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def get_arrow_mode(self):
        return self.with_arrow_radio.isChecked()

    ##newww
    def _make_preview_actor_2d(self, points, color=(0, 1, 0), width=3):
        """
        Pixel-perfect 2D preview line.
        Converts world→display coords explicitly to avoid vtkMapper2D projection bugs.
        """
        if not points or len(points) < 2:
            return None

        # ✅ Convert world coords to display pixels directly — no Z projection issues
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToWorld()

        display_pts = vtk.vtkPoints()
        for p in points:
            coord.SetValue(float(p[0]), float(p[1]), float(p[2]))
            d = coord.GetComputedDisplayValue(self.renderer)
            display_pts.InsertNextPoint(float(d[0]), float(d[1]), 0.0)

        n = display_pts.GetNumberOfPoints()
        cell = vtk.vtkCellArray()
        cell.InsertNextCell(n)
        for i in range(n):
            cell.InsertCellPoint(i)

        poly = vtk.vtkPolyData()
        poly.SetPoints(display_pts)
        poly.SetLines(cell)

        # Use Display system — coordinates are already in pixels
        coord2 = vtk.vtkCoordinate()
        coord2.SetCoordinateSystemToDisplay()

        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        mapper.SetTransformCoordinate(coord2)

        actor = vtk.vtkActor2D()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(float(color[0]), float(color[1]), float(color[2]))
        prop.SetLineWidth(float(width))
        prop.SetOpacity(1.0)
        prop.SetDisplayLocationToForeground()

        return actor

    def _remove_preview_actor_2d(self, attr_name):
        """Safely remove a named 2D preview actor from renderer."""
        actor = getattr(self, attr_name, None)
        if actor is not None:
            try:
                self.renderer.RemoveActor2D(actor)
            except Exception:
                pass
            setattr(self, attr_name, None)
