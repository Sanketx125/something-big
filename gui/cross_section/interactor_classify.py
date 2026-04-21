from json import tool
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage, vtkInteractorStyleTrackballCamera
from vtkmodules.vtkRenderingCore import vtkActor, vtkPolyDataMapper, vtkCoordinate
from vtkmodules.vtkCommonDataModel import vtkPolyData, vtkCellArray
from vtkmodules.vtkCommonCore import vtkPoints
import vtk
import numpy as np
import time
# ✅ Shared helper — avoids triggering shading rebuild when no mesh exists yet
from gui.classification_tools import _shading_mesh_exists
          
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QTimer
from PySide6.QtCore import Qt, QPoint, QPointF, QLineF
from PySide6.QtGui import QPainter, QColor, QPen
import pyvista as pv

class PreviewOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Allow mouse events to pass through to the VTK interactor
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        # Allow a translucent background so we can draw overlays if needed
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # Start hidden; _init_preview_overlay will show and size it.
        self._shapes = []  # placeholder for future use
        self.hide()

    def set_shapes(self, shapes):
        self._shapes = list(shapes or [])
        if self._shapes:
            self.show()
            self.raise_()
        else:
            self.hide()
        self.update()

    def clear_shapes(self):
        self.set_shapes([])

    def translate_shapes(self, dx, dy):
        if not self._shapes or (dx == 0 and dy == 0):
            return

        shifted_shapes = []
        for shape in self._shapes:
            shifted_segments = []
            for p0, p1 in shape.get("segments", []):
                shifted_segments.append((
                    (float(p0[0]) + dx, float(p0[1]) + dy),
                    (float(p1[0]) + dx, float(p1[1]) + dy),
                ))

            shifted_shape = dict(shape)
            shifted_shape["segments"] = shifted_segments
            shifted_shapes.append(shifted_shape)

        self._shapes = shifted_shapes
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for shape in self._shapes:
            color = shape.get("color", (255, 255, 0, 220))
            width = float(shape.get("width", 2.0))
            pen = QPen(QColor(*color))
            pen.setWidthF(max(width, 1.0))
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)

            for p0, p1 in shape.get("segments", []):
                painter.drawLine(
                    QLineF(
                        QPointF(float(p0[0]), float(p0[1])),
                        QPointF(float(p1[0]), float(p1[1])),
                    )
                )
        painter.end()

class ClassificationInteractor:
    """
    Hybrid interactor for classification in cross-section dock.
    Left mouse → classification tools.
    Middle mouse → pan (while tools remain active).
    """

    def __init__(self, app, interactor, mode="2d"):
        """
        ✅ FIXED: Set self.app FIRST before any operations that might access it
        """
        # ✅ CRITICAL: Set instance variables FIRST
        self.app = app
        self.interactor = interactor
        self.mode = mode
        self.guide_actors = []  # Temporary visual guides (rubber-band lines)
        self.section_actors = [] 

        # added by bala
        # SAFE MULTI-CLASS SYNC (read-only, not modifying app)
        self.from_classes = getattr(app, "from_classes", None)
        self.to_class = getattr(app, "to_class", None)

         # ✅ NEW: Qt-based preview overlay (ultra-fast)
        self._preview_overlay = None
        self._last_update_time = 0
        self._last_render_time = 0 
        self._update_interval = 16  # ~60 FPS throttle (milliseconds)
        self._cached_renderer = None
        self._widget_height = 0
                
        # ✅ NEW FIX: Deactivate cut section tool if it's in WAITING state
        if hasattr(app, 'cut_section_controller'):
            cut_ctrl = app.cut_section_controller
            if hasattr(cut_ctrl, 'deactivate_if_waiting'):
                try:
                    cut_ctrl.deactivate_if_waiting()
                    print("✅ Checked and handled cut section tool state")
                except Exception as e:
                    print(f"⚠️ Failed to deactivate cut section: {e}")

        # Cancel any active cut section mode (legacy code - kept for backwards compatibility)
        if hasattr(app, 'section_controller') and hasattr(app.section_controller, "_cut_active"):
            if app.section_controller._cut_active:
                app.section_controller.cancel_cut_section()

        # base style
        if mode == "2d":
            self.style = vtkInteractorStyleImage()
        else:
            self.style = vtkInteractorStyleTrackballCamera()

        self.interactor.SetInteractorStyle(self.style)

        # disable double-click reset
        self.style.AddObserver("LeftButtonDoubleClickEvent", lambda o, e: None)

        # attach events
        self.style.AddObserver("LeftButtonPressEvent", self.on_left_press)
        self.style.AddObserver("LeftButtonReleaseEvent", self.on_left_release)
        self.style.AddObserver("KeyPressEvent", self.on_key_press)

        # ✅ CRITICAL FIX: Use custom mouse move handler that ALWAYS shows previews
        self.style.AddObserver("MouseMoveEvent", self._on_mouse_move_with_preview)

        # ✅ CUSTOM PAN: Do NOT forward to style.OnMiddleButtonDown/Up — those call
        # VTK's internal C++ Render() which segfaults on stale render windows.
        # Instead, implement pan manually with safe deferred rendering.
        self._is_panning = False
        self._last_pan_pos = (0, 0)
        self._pan_render_pending = False
        self._preview_hidden_for_pan = False
        self._pan_hidden_actor_names = []
        self._deferred_left_release_timer = QTimer()
        self._deferred_left_release_timer.setInterval(16)
        self._deferred_left_release_timer.timeout.connect(self._check_deferred_left_release)
        self.style.AddObserver("MiddleButtonPressEvent", self._on_safe_pan_start)
        self.style.AddObserver("MiddleButtonReleaseEvent", self._on_safe_pan_stop)

        # state
        self.P1 = None
        self.is_dragging = False 
        self._gesture_tool = None
        self.line_actor = None
        self.dotted_actor = None
        self.rect_actor = None
        self.circle_actor = None
        self.poly_actor = None
        self.brush_actor = None
        self.freehand_actor = None

        # polygon / freehand classification state
        self.drawing_points = []
        self.is_drawing_freehand = False
        
        self._brush_grid_size = 50  # Grid cells for spatial lookup
        self._brush_spatial_index = None
        self._last_brush_build_time = 0
        
        # ✅ BRUSH OPTIMIZATION: Smooth interpolation
        self._brush_interpolation_step = 0.5  # Smaller = smoother
        self._brush_min_move_distance = 0.1  # Minimum movement to register
        
        # ✅ BRUSH OPTIMIZATION: Render throttling
        self._brush_render_counter = 0
        self._brush_render_every = 3
        
        # ✅ TEST: Draw a test line to verify rendering works
        self._draw_test_line()
        
        print("✅ ClassificationInteractor initialized with live previews")
        self.style.AddObserver("RightButtonPressEvent", self.on_right_press)

    def cleanup(self):
        """Clear transient preview state before this interactor is discarded."""
        try:
            self._finalize_pending_main_brush_stroke()
        except Exception as e:
            print(f"⚠️ ClassificationInteractor cleanup brush finalize failed: {e}")

        try:
            self._clear_all_previews()
        except Exception as e:
            print(f"⚠️ ClassificationInteractor cleanup preview clear failed: {e}")

        overlay = getattr(self, "_preview_overlay", None)
        if overlay is not None:
            try:
                overlay.hide()
                overlay.deleteLater()
            except Exception as e:
                print(f"⚠️ ClassificationInteractor overlay cleanup failed: {e}")
            self._preview_overlay = None

        self.P1 = None
        self.is_dragging = False
        self.drawing_points = []
        self.is_drawing_freehand = False
        self._is_panning = False  # ✅ BUG FIX: Reset panning state on cleanup
        self._pan_render_pending = False
        self._hide_preview_overlay_for_pan()
        timer = getattr(self, "_deferred_left_release_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def _get_preview_actor_names(self):
        return [
            "line_actor", "dotted_actor", "rect_actor", "circle_actor",
            "brush_actor", "polygon_actor", "freehand_actor", "poly_actor",
            "line_actor_cut", "dotted_actor_cut", "rect_actor_cut", "circle_actor_cut",
            "brush_actor_cut", "freehand_actor_cut", "poly_actor_cut",
        ]

    def _get_active_tool_preview_actor_names(self, tool=None):
        tool = tool or getattr(self.app, "active_classify_tool", None)
        vtk_widget = self._get_active_vtk_widget()
        cut_vtk = getattr(getattr(self.app, "cut_section_controller", None), "cut_vtk", None)
        suffix = "_cut" if (vtk_widget is not None and cut_vtk is not None and vtk_widget == cut_vtk) else ""
        mapping = {
            "above_line": [f"line_actor{suffix}", f"dotted_actor{suffix}"],
            "below_line": [f"line_actor{suffix}", f"dotted_actor{suffix}"],
            "rectangle": [f"rect_actor{suffix}"],
            "circle": [f"circle_actor{suffix}"],
            "freehand": [f"freehand_actor{suffix}"],
            "polygon": [f"poly_actor{suffix}"],
            "brush": [f"brush_actor{suffix}"],
        }
        return mapping.get(tool, [])

    def _set_preview_visibility(self, visible, actor_names=None):
        """Toggle preview actors without clearing the active classification state."""
        actor_names = actor_names or self._get_preview_actor_names()

        for name in actor_names:
            actor = getattr(self, name, None)
            if actor is None:
                continue
            if visible:
                actor.VisibilityOn()
            else:
                actor.VisibilityOff()

    def _get_visible_preview_actor_names(self, actor_names=None):
        visible = []
        vtk_widget = self._get_active_vtk_widget()
        renderer = getattr(vtk_widget, "renderer", None) if vtk_widget is not None else None
        actor_names = actor_names or self._get_preview_actor_names()
        for name in actor_names:
            actor = getattr(self, name, None)
            if actor is None:
                continue
            try:
                if renderer is not None and hasattr(renderer, "HasViewProp"):
                    if not renderer.HasViewProp(actor):
                        continue
                if actor.GetVisibility():
                    visible.append(name)
            except Exception:
                continue
        return visible

    def _collect_preview_overlay_shapes(self, actor_names=None):
        """Capture currently visible preview actors as display-space line segments."""
        actor_names = actor_names or self._get_preview_actor_names()
        vtk_widget = self._get_active_vtk_widget()
        renderer = getattr(vtk_widget, "renderer", None) if vtk_widget is not None else None

        shapes = []
        id_list = vtk.vtkIdList()

        for name in actor_names:
            actor = getattr(self, name, None)
            if actor is None:
                continue

            try:
                if renderer is not None and hasattr(renderer, "HasViewProp"):
                    if not renderer.HasViewProp(actor):
                        continue
                if not actor.GetVisibility():
                    continue
            except Exception:
                continue

            try:
                mapper = actor.GetMapper()
                poly = mapper.GetInput() if mapper is not None else None
                points = poly.GetPoints() if poly is not None else None
                lines = poly.GetLines() if poly is not None else None
            except Exception:
                continue

            if points is None or lines is None:
                continue

            try:
                lines.InitTraversal()
            except Exception:
                continue

            segments = []
            while lines.GetNextCell(id_list):
                if id_list.GetNumberOfIds() < 2:
                    continue

                prev_id = id_list.GetId(0)
                prev_pt = points.GetPoint(prev_id)
                for idx in range(1, id_list.GetNumberOfIds()):
                    curr_id = id_list.GetId(idx)
                    curr_pt = points.GetPoint(curr_id)

                    # Freeze overlay in DISPLAY space so it stays visually fixed
                    # while camera pans.
                    prev_xy = (float(prev_pt[0]), float(prev_pt[1]))
                    curr_xy = (float(curr_pt[0]), float(curr_pt[1]))
                    # Most classification preview actors are vtkActor2D with
                    # display-space points already. Only world-project non-2D actors.
                    if renderer is not None and not isinstance(actor, vtk.vtkActor2D):
                        try:
                            coord = vtk.vtkCoordinate()
                            coord.SetCoordinateSystemToWorld()
                            coord.SetValue(float(prev_pt[0]), float(prev_pt[1]), float(prev_pt[2]))
                            d0 = coord.GetComputedDisplayValue(renderer)
                            coord.SetValue(float(curr_pt[0]), float(curr_pt[1]), float(curr_pt[2]))
                            d1 = coord.GetComputedDisplayValue(renderer)
                            prev_xy = (float(d0[0]), float(d0[1]))
                            curr_xy = (float(d1[0]), float(d1[1]))
                        except Exception:
                            pass

                    segments.append(
                        (
                            prev_xy,
                            curr_xy,
                        )
                    )
                    prev_pt = curr_pt

            if not segments:
                continue

            prop = actor.GetProperty() if hasattr(actor, "GetProperty") else None
            color = (255, 255, 0, 220)
            width = 2.0
            if prop is not None:
                try:
                    rgb = prop.GetColor()
                    opacity = prop.GetOpacity()
                    color = (
                        int(max(0.0, min(1.0, rgb[0])) * 255),
                        int(max(0.0, min(1.0, rgb[1])) * 255),
                        int(max(0.0, min(1.0, rgb[2])) * 255),
                        int(max(0.0, min(1.0, opacity)) * 255),
                    )
                    width = float(prop.GetLineWidth())
                except Exception:
                    pass

            shapes.append({
                "segments": segments,
                "color": color,
                "width": width,
            })

        return shapes

    def _show_preview_overlay_for_pan(self):
        """Freeze the current preview in a Qt overlay while the camera pans."""
        tool = getattr(self, "_gesture_tool", None) or getattr(self.app, "active_classify_tool", None)
        active_actor_names = self._get_active_tool_preview_actor_names(tool)
        if active_actor_names:
            non_active_actor_names = [
                n for n in self._get_preview_actor_names() if n not in active_actor_names
            ]
            # Ensure stale previews from other tools/views are not visible during pan.
            self._set_preview_visibility(False, non_active_actor_names)
        self._pan_hidden_actor_names = self._get_visible_preview_actor_names(active_actor_names)
        if not self._pan_hidden_actor_names:
            return

        shapes = self._collect_preview_overlay_shapes(self._pan_hidden_actor_names)
        if not shapes:
            # Keep live preview visible if overlay freeze data is unavailable.
            self._preview_hidden_for_pan = False
            return

        if self._preview_overlay is None:
            self._init_preview_overlay()
        else:
            self._update_overlay_geometry()

        if self._preview_overlay is None:
            return

        self._preview_overlay.set_shapes(shapes)
        try:
            self._update_overlay_geometry()
            self._preview_overlay.show()
            self._preview_overlay.raise_()
            self._preview_overlay.update()
        except Exception:
            pass
        # Freeze mode: hide live preview actors so the visible overlay
        # stays fixed while camera pans.
        self._set_preview_visibility(False, self._pan_hidden_actor_names)
        self._preview_hidden_for_pan = True

    def _hide_preview_overlay_for_pan(self):
        """Dismiss the frozen overlay preview and restore VTK preview actors."""
        overlay = getattr(self, "_preview_overlay", None)
        if overlay is not None:
            try:
                overlay.clear_shapes()
            except Exception:
                try:
                    overlay.hide()
                except Exception:
                    pass

        if self._preview_hidden_for_pan:
            self._set_preview_visibility(True, self._pan_hidden_actor_names)

        self._pan_hidden_actor_names = []
        self._preview_hidden_for_pan = False

    def _translate_preview_actors_for_pan(self, dx, dy, actor_names=None):
        """Shift live preview actors in display space so they stay aligned while panning."""
        if dx == 0 and dy == 0:
            return

        actor_names = actor_names or self._get_preview_actor_names()

        for name in actor_names:
            actor = getattr(self, name, None)
            if actor is None:
                continue

            try:
                if not actor.GetVisibility():
                    continue
            except Exception:
                continue

            try:
                mapper = actor.GetMapper()
                poly = mapper.GetInput() if mapper is not None else None
                points = poly.GetPoints() if poly is not None else None
                if points is None:
                    continue

                for idx in range(points.GetNumberOfPoints()):
                    x, y, z = points.GetPoint(idx)
                    points.SetPoint(idx, x + dx, y + dy, z)

                points.Modified()
                if poly is not None:
                    poly.Modified()
            except Exception:
                continue

        overlay = getattr(self, "_preview_overlay", None)
        if overlay is not None and getattr(self, "_preview_hidden_for_pan", False):
            try:
                overlay.translate_shapes(dx, dy)
            except Exception:
                pass

    def _has_active_drag_classification(self, tool=None):
        """Return True while a left-drag classification gesture is in progress."""
        tool = tool or getattr(self.app, "active_classify_tool", None)
        if tool == "freehand":
            return bool(getattr(self, "is_drawing_freehand", False))
        return bool(getattr(self, "is_dragging", False) and getattr(self, "P1", None) is not None)

    def _stop_deferred_left_release_watch(self):
        timer = getattr(self, "_deferred_left_release_timer", None)
        if timer is None:
            return
        try:
            timer.stop()
        except Exception:
            pass

    def _start_deferred_left_release_watch(self):
        """Fallback for the left-release event path during/after middle-button pan."""
        if not self._has_active_drag_classification():
            return

        timer = getattr(self, "_deferred_left_release_timer", None)
        if timer is None:
            return

        if not timer.isActive():
            timer.start()

    def _check_deferred_left_release(self):
        """
        Some middle-pan sequences do not forward a final LeftButtonReleaseEvent
        through VTK. When that happens, finish the paused classification as soon
        as Qt reports the left button is no longer pressed.
        """
        if not self._has_active_drag_classification():
            self._stop_deferred_left_release_watch()
            return

        try:
            from PySide6.QtWidgets import QApplication
            buttons = QApplication.mouseButtons()
        except Exception:
            return

        middle_pressed = bool(buttons & Qt.MiddleButton)
        left_pressed = bool(buttons & Qt.LeftButton)

        # Keep our internal pan state in sync even if VTK misses MiddleButtonReleaseEvent.
        if getattr(self, "_is_panning", False) and not middle_pressed:
            self._is_panning = False
            self._last_mouse_move_time = 0.0
            self._last_render_time = 0.0
            self._last_pan_pos = (0, 0)
            self._hide_preview_overlay_for_pan()

        if left_pressed:
            return

        if getattr(self, "_is_panning", False):
            self._is_panning = False
            self._last_pan_pos = (0, 0)
            self._hide_preview_overlay_for_pan()

        self._stop_deferred_left_release_watch()
        self.on_left_release(self.interactor, "DeferredLeftReleaseAfterPan")

    def _finalize_pending_main_brush_stroke(self):
        """
        Finalize a live main-view brush stroke when the tool ends without a
        normal mouse-release event, so undo/redo still works.
        """
        if not self._is_main_view():
            return None

        mask = getattr(self, "_brush_accumulated_mask", None)
        old_classes_dict = getattr(self, "_brush_old_classes", None) or {}
        to_class = getattr(self.app, "to_class", None)
        undo_mask = None

        if mask is not None and np.any(mask):
            if old_classes_dict and to_class is not None:
                indices = np.array(sorted(old_classes_dict.keys()), dtype=np.int64)
                old_cls = np.array(
                    [old_classes_dict[int(i)] for i in indices],
                    dtype=self.app.data["classification"].dtype,
                )
                new_cls = np.full(len(indices), to_class, dtype=old_cls.dtype)

                undo_mask = np.zeros(len(self.app.data["xyz"]), dtype=bool)
                undo_mask[indices] = True

                self.app.undo_stack.append({
                    "mask": undo_mask,
                    "old_classes": old_cls,
                    "new_classes": new_cls,
                })
                self.app.redo_stack.clear()
                self.app._last_changed_mask = undo_mask

                max_steps = getattr(self.app, "_max_undo_steps", 30)
                while len(self.app.undo_stack) > max_steps:
                    from gui.memory_manager import _free_undo_entry
                    _free_undo_entry(self.app.undo_stack.pop(0))

                try:
                    from gui.point_count_widget import refresh_point_statistics
                    refresh_point_statistics(self.app)
                except Exception:
                    pass

                if hasattr(self.app, "statusBar"):
                    self.app.statusBar().showMessage(
                        f"✅ {len(indices):,} points → class {to_class}", 3000
                    )

            if getattr(self.app, "display_mode", "class") != "shaded_class":
                self.app._gpu_sync_done = True
            elif _shading_mesh_exists(self.app):
                try:
                    from gui.shading_display import refresh_shaded_after_classification_fast
                    refresh_shaded_after_classification_fast(
                        self.app,
                        changed_mask=mask,
                    )
                except Exception as e:
                    print(f"⚠️ Brush cleanup shading refresh: {e}")
            else:
                self.app._gpu_sync_done = True

            try:
                if hasattr(self.app, "section_vtks") and undo_mask is not None:
                    from gui.unified_actor_manager import fast_cross_section_update
                    for view_idx in self.app.section_vtks:
                        try:
                            fast_cross_section_update(self.app, view_idx, undo_mask)
                        except Exception:
                            pass

                self._safe_render_pyvista(self.app.vtk_widget)
                if hasattr(self.app, "section_vtks"):
                    for vtk_widget in self.app.section_vtks.values():
                        if vtk_widget:
                            self._safe_render_pyvista(vtk_widget)
            except Exception:
                pass

            try:
                if hasattr(self.app, "cut_section_controller"):
                    ctrl = self.app.cut_section_controller
                    if (
                        ctrl.is_cut_view_active
                        and ctrl.cut_points is not None
                        and ctrl._cut_index_map is not None
                        and ctrl.cut_vtk is not None
                    ):
                        ctrl._refresh_cut_colors_fast()
            except Exception as e:
                print(f"⚠️ Brush cleanup cut refresh failed: {e}")

        self._brush_accumulated_mask = None
        self._brush_old_classes = {}
        self._brush_frame_chunks = []
        self._brush_stroke_positions = []
        self._last_brush_center = None
        self._brush_needs_render = False
        self._brush_main_visible_classes = None
        self._brush_main_visible_classes_arr = None
        self.app._suppress_section_refresh = False
        self.is_dragging = False

        return undo_mask

    # ═══════════════════════════════════════════════════════════════════════
    # ✅ SAFE RENDER GUARDS - Prevents crash on stale VTK render windows
    # Root cause: switching between cut section ↔ synchronized views leaves
    # render windows in an invalid state. Unguarded Render() dereferences
    # near-null pointer (0x24) → win32 memory access violation → hard crash.
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _is_vtk_widget_alive(vtk_widget):
        """Check if a VTK widget is still alive and renderable."""
        if vtk_widget is None:
            return False
        try:
            # Qt widget destroyed?
            if hasattr(vtk_widget, 'isVisible') and callable(vtk_widget.isVisible):
                if not vtk_widget.isVisible():
                    return False
            # Render window accessible?
            rw = vtk_widget.GetRenderWindow()
            if rw is None:
                return False
            # Interactor alive? (None if window finalized)
            if rw.GetInteractor() is None:
                return False
            # Has at least one renderer?
            renderers = rw.GetRenderers()
            if renderers is None or renderers.GetNumberOfItems() == 0:
                return False
            return True
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            return False
        except Exception:
            return False

    @staticmethod
    def _safe_render(vtk_widget):
        """
        Safely render a VTK widget. Returns True on success, False otherwise.
        NEVER raises — all exceptions are caught to prevent crash.
        """
        if vtk_widget is None:
            return False
        try:
            # Inline validity checks (avoid second method call for speed)
            rw = vtk_widget.GetRenderWindow()
            if rw is None:
                return False
            if rw.GetInteractor() is None:
                return False
            renderers = rw.GetRenderers()
            if renderers is None or renderers.GetNumberOfItems() == 0:
                return False
            rw.Render()
            return True
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            return False
        except Exception:
            return False

    @staticmethod
    def _safe_render_pyvista(vtk_widget):
        """Safely call .render() on a PyVista widget."""
        if vtk_widget is None:
            return False
        try:
            if hasattr(vtk_widget, 'isVisible') and callable(vtk_widget.isVisible):
                if not vtk_widget.isVisible():
                    return False
            rw = vtk_widget.GetRenderWindow()
            if rw is None or rw.GetInteractor() is None:
                return False
            vtk_widget.render()
            return True
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            return False
        except Exception:
            return False

    def _safe_render_interactor(self):
        """Safely render via self.interactor's render window."""
        try:
            if self.interactor is None:
                return False
            rw = self.interactor.GetRenderWindow()
            if rw is None or rw.GetInteractor() is None:
                return False
            renderers = rw.GetRenderers()
            if renderers is None or renderers.GetNumberOfItems() == 0:
                return False
            rw.Render()
            return True
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            return False
        except Exception:
            return False

    @staticmethod
    def _safe_render_from_renderer(renderer):
        """Safely render from a VTK renderer reference."""
        if renderer is None:
            return False
        try:
            rw = renderer.GetRenderWindow()
            if rw is None or rw.GetInteractor() is None:
                return False
            rw.Render()
            return True
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            return False
        except Exception:
            return False

    @staticmethod
    def _safe_get_render_window(vtk_widget):
        """Safely get render window from a VTK widget. Returns None if dead."""
        if vtk_widget is None:
            return None
        try:
            rw = vtk_widget.GetRenderWindow()
            if rw is None or rw.GetInteractor() is None:
                return None
            return rw
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            return None
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # ✅ CUSTOM SAFE PAN - Replaces VTK's built-in pan which crashes
    # VTK's OnMiddleButtonDown/Up → OnMouseMove internally calls C++ Render()
    # which segfaults on stale OpenGL contexts. This custom pan does camera
    # math in Python and uses Qt deferred repaint — zero C++ Render() calls.
    # ═══════════════════════════════════════════════════════════════════════

    def _on_safe_pan_start(self, obj, event):
        """Start custom pan (replaces style.OnMiddleButtonDown)."""
        try:
            if self.interactor is None:
                return
            
            # ═══════════════════════════════════════════════════════════════
            # ✅ CRITICAL: Verify middle button is actually pressed via Qt
            # VTK sends phantom MiddleButtonPressEvent after classification
            # ═══════════════════════════════════════════════════════════════
            try:
                from PySide6.QtWidgets import QApplication
                from PySide6.QtCore import Qt
                buttons = QApplication.mouseButtons()
                if not (buttons & Qt.MiddleButton):
                    # Phantom event - ignore completely
                    return
            except Exception:
                pass
            
            self._is_panning = True
            self._last_pan_pos = self.interactor.GetEventPosition()

            tool = getattr(self.app, "active_classify_tool", None)
            has_preview_gesture = bool(
                self._has_active_drag_classification(tool)
                or getattr(self, "P1", None) is not None
                or bool(getattr(self, "drawing_points", []))
                or bool(getattr(self, "is_drawing_freehand", False))
            )
            if tool in {"rectangle", "circle", "freehand", "above_line", "below_line", "polygon", "brush"} and has_preview_gesture:
                # Keep the live preview actors active and translate them with the pan,
                # otherwise the preview appears frozen while the cloud moves.
                self._hide_preview_overlay_for_pan()
                self._start_deferred_left_release_watch()
            print("🖱️ Middle button PRESSED - starting pan")
            
        except (RuntimeError, AttributeError):
            pass

    def _on_safe_pan_stop(self, obj, event):
        """Stop custom pan (replaces style.OnMiddleButtonUp)."""
        self._is_panning = False
        # Let the next post-pan mouse move update the preview immediately.
        self._last_mouse_move_time = 0.0
        self._last_render_time = 0.0
        self._hide_preview_overlay_for_pan()
        self._start_deferred_left_release_watch()

    def _is_classification_paused_for_pan(self, tool=None):
        """
        Return True while a drag-style classification gesture should be frozen
        so middle-button pan can run without changing the active selection.
        """
        if not getattr(self, "_is_panning", False):
            return False
        return self._has_active_drag_classification(tool)

    def _do_safe_pan(self):
        """
        Execute pan: move camera by mouse delta.
        ✅ CRITICAL FIX: Verify middle button is ACTUALLY pressed before panning.
        This prevents phantom pan from corrupted VTK interactor state.
        """
        # ═══════════════════════════════════════════════════════════════════
        # ✅ CRITICAL: Check Qt button state, not just our flag
        # VTK can send phantom MiddleButtonPressEvent after classification
        # tools complete, setting _is_panning=True incorrectly.
        # ═══════════════════════════════════════════════════════════════════
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtCore import Qt
            buttons = QApplication.mouseButtons()
            middle_actually_pressed = bool(buttons & Qt.MiddleButton)
            
            if not middle_actually_pressed:
                # Middle button not pressed - reset our flag if it was set
                if self._is_panning:
                    self._is_panning = False
                return
        except Exception:
            # Fallback: use our flag only
            if not getattr(self, '_is_panning', False):
                return
        
        if not getattr(self, '_is_panning', False):
            return
        
        try:
            if self.interactor is None:
                return
            
            current_pos = self.interactor.GetEventPosition()
            last = getattr(self, '_last_pan_pos', current_pos)
            
            dx = current_pos[0] - last[0]
            dy = current_pos[1] - last[1]
            
            if dx == 0 and dy == 0:
                return
            
            vtk_widget = self._get_active_vtk_widget()
            if vtk_widget is None:
                return
            
            renderer = getattr(vtk_widget, 'renderer', None)
            if renderer is None:
                return
            
            camera = renderer.GetActiveCamera()
            if camera is None:
                return
            
            # Get window size for pixel-to-world conversion
            try:
                rw = vtk_widget.GetRenderWindow()
                size = rw.GetSize() if rw is not None else (800, 600)
            except (RuntimeError, AttributeError):
                size = (800, 600)
            
            w = max(size[0], 1)
            h = max(size[1], 1)
            
            # Use ParallelScale for orthographic views
            if camera.GetParallelProjection():
                parallel_scale = camera.GetParallelScale()
                scale_x = (2.0 * parallel_scale) / h
                scale_y = scale_x
            else:
                distance = camera.GetDistance()
                scale_x = distance / (w * 0.5)
                scale_y = scale_x
            
            # Camera axes
            camera.OrthogonalizeViewUp()
            up = list(camera.GetViewUp())
            pos = list(camera.GetPosition())
            fp = list(camera.GetFocalPoint())
            
            vd = [fp[i] - pos[i] for i in range(3)]
            
            # Right vector = vd × up
            right = [
                vd[1] * up[2] - vd[2] * up[1],
                vd[2] * up[0] - vd[0] * up[2],
                vd[0] * up[1] - vd[1] * up[0]
            ]
            mag = (right[0]**2 + right[1]**2 + right[2]**2) ** 0.5
            if mag < 1e-12:
                self._last_pan_pos = current_pos
                return
            right = [r / mag for r in right]
            
            # Pan vector
            pan = [-dx * scale_x * right[i] - dy * scale_y * up[i] for i in range(3)]
            
            camera.SetPosition(*[pos[i] + pan[i] for i in range(3)])
            camera.SetFocalPoint(*[fp[i] + pan[i] for i in range(3)])
            
            self._last_pan_pos = current_pos

            tool = getattr(self, "_gesture_tool", None) or getattr(self.app, "active_classify_tool", None)
            if self._has_active_drag_classification(tool):
                if tool == "freehand" and hasattr(self, "drawing_points_display_cut"):
                    self.drawing_points_display_cut = [
                        (float(px) + dx, float(py) + dy)
                        for px, py in self.drawing_points_display_cut
                    ]
                elif tool == "rectangle" and getattr(self, "P1_display_cut", None) is not None:
                    self.P1_display_cut = (
                        float(self.P1_display_cut[0]) + dx,
                        float(self.P1_display_cut[1]) + dy,
                    )

                self._translate_preview_actors_for_pan(
                    dx,
                    dy,
                    self._get_active_tool_preview_actor_names(tool),
                )
            
            # Deferred render
            if not getattr(self, '_pan_render_pending', False):
                self._pan_render_pending = True
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, self._execute_deferred_pan_render)
            
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            self._is_panning = False
        except Exception:
            pass

    def _execute_deferred_pan_render(self):
        """Render on the Qt event loop (valid OpenGL context). Called by QTimer."""
        self._pan_render_pending = False
        try:
            vtk_widget = self._get_active_vtk_widget()
            if vtk_widget is not None:
                # ✅ Check widget is visible (Qt-level, safe)
                if hasattr(vtk_widget, 'isVisible') and not vtk_widget.isVisible():
                    return
                vtk_widget.render()
                overlay = getattr(self, "_preview_overlay", None)
                if overlay is not None and getattr(self, "_preview_hidden_for_pan", False):
                    try:
                        self._update_overlay_geometry()
                        overlay.show()
                        overlay.raise_()
                        overlay.update()
                    except Exception:
                        pass
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            pass
        except Exception:
            pass

    # Added by bala for mouse smooth
    def _get_display_point(self):
        """Exact mouse position in DISPLAY coords (no snapping, very fast)."""
        x, y = self.interactor.GetEventPosition()
        return float(x), float(y)

    def _display_to_world_fast(self, x, y):
        """DISPLAY → WORLD without picker (no snapping). ✅ SAFE: guarded render window access."""
        if not hasattr(self, "_cached_renderer") or self._cached_renderer is None:
            try:
                rw = self.interactor.GetRenderWindow()
                if rw is None:
                    return (0.0, 0.0, 0.0)
                renderers = rw.GetRenderers()
                if renderers is None:
                    return (0.0, 0.0, 0.0)
                self._cached_renderer = renderers.GetFirstRenderer()
            except (RuntimeError, AttributeError, OSError, ReferenceError):
                return (0.0, 0.0, 0.0)
            except Exception:
                return (0.0, 0.0, 0.0)

        if self._cached_renderer is None:
            return (0.0, 0.0, 0.0)

        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToDisplay()
        coord.SetValue(x, y, 0)
        try:
            return coord.GetComputedWorldValue(self._cached_renderer)
        except Exception:
            return (0.0, 0.0, 0.0)

    def _is_main_view(self):
        """True if this interactor is attached to the main plan view widget."""
        try:
            return self._get_active_vtk_widget() == getattr(self.app, 'vtk_widget', None)
        except Exception:
            return False

    def _view2d_to_world(self, u, v):
        """Map 2D tool coords to 3D world - OPTIMIZED with caching"""
        
        if self._is_main_view():
            return (float(u), float(v), 0.0)
        
        view_mode = getattr(self.app, 'cross_view_mode', 'side')
        
        # ✅ CRITICAL OPTIMIZATION: Cache perpendicular coordinate
        # Only recalculate when view changes, not on every mouse move
        cache_key = f"perp_coord_{view_mode}"
        
        if not hasattr(self, '_coord_cache'):
            self._coord_cache = {}
        
        if cache_key not in self._coord_cache:
            # Calculate once and cache
            active_view = self._get_view_index_from_interactor()
            perpendicular_coord = 0.0
            
            if active_view is not None:
                core_mask = getattr(self.app, f"section_{active_view}_core_mask", None)
                if core_mask is not None and core_mask.sum() > 0:
                    section_xyz = self.app.data["xyz"][core_mask]
                    
                    if view_mode == 'front':
                        perpendicular_coord = float(np.median(section_xyz[:, 0]))
                    else:
                        perpendicular_coord = float(np.median(section_xyz[:, 1]))
            
            self._coord_cache[cache_key] = perpendicular_coord
            print(f"✅ Cached {cache_key} = {perpendicular_coord:.2f}")
        
        perpendicular_coord = self._coord_cache[cache_key]
        
        if view_mode == 'front':
            return (float(perpendicular_coord), float(u), float(v))
        else:
            return (float(u), float(perpendicular_coord), float(v)) 
        
    def _invalidate_coord_cache(self):
        """Clear coordinate cache when section changes"""
        if hasattr(self, '_coord_cache'):
            self._coord_cache.clear()
            print("🔄 Coordinate cache cleared")
        
    def _get_view_coordinates(self, pt):
        """
        2D coordinates in the active view's plane.
        - Main view: (x, y)
        - Cross-section: (u, z) [side: XZ, front: YZ]
        - Cut section: (u, z) [projected to cut plane]
        """
        if self._is_main_view():
            return (pt[0], pt[1])
        
        # ✅ FIX: Check if we're in cut section
        vtk_widget = self._get_active_vtk_widget()
        is_cut_section = (
            hasattr(self.app, 'cut_section_controller') and
            vtk_widget == getattr(self.app.cut_section_controller, 'cut_vtk', None)
        )
        
        if is_cut_section:
            # ✅ CRITICAL FIX: Project to cut section coordinates
            from ..classification_tools import _project_to_cut_view
            pt_array = np.array([pt])
            projected = _project_to_cut_view(self.app, pt_array)
            return (projected[0, 0], projected[0, 1])  # Return (u, z)
        
        # Regular cross-section
        view_mode = getattr(self.app, 'cross_view_mode', 'side')
        if view_mode == 'front':
            return (pt[1], pt[2])  # Y-Z
        else:
            return (pt[0], pt[2])  # X-Z
 
    def _get_active_vtk_widget(self):
        """
        Get the correct VTK widget by matching the current interactor.
        ✅ SAFE: All GetRenderWindow() calls guarded to prevent crash on stale windows.
        """
        if self.interactor is None:
            return None
       
        # 1. Check Cut Section
        if hasattr(self.app, 'cut_section_controller'):
            cut_vtk = getattr(self.app.cut_section_controller, 'cut_vtk', None)
            if cut_vtk:
                if getattr(cut_vtk, 'interactor', None) == self.interactor:
                    return cut_vtk
                rw = self._safe_get_render_window(cut_vtk)
                if rw is not None:
                    try:
                        if rw.GetInteractor() == self.interactor:
                            return cut_vtk
                    except Exception:
                        pass
 
        # 2. Check Section Docks (SAFE)
        section_vtks = getattr(self.app, 'section_vtks', None)
        if isinstance(section_vtks, dict):
            for widget in section_vtks.values():
                if widget:
                    if getattr(widget, 'interactor', None) == self.interactor:
                        return widget
                    rw = self._safe_get_render_window(widget)
                    if rw is not None:
                        try:
                            if rw.GetInteractor() == self.interactor:
                                return widget
                        except Exception:
                            pass

 
        # 3. Check Main View
        main_widget = getattr(self.app, 'vtk_widget', None)
        if main_widget:
            if getattr(main_widget, 'interactor', None) == self.interactor:
                return main_widget
            rw = self._safe_get_render_window(main_widget)
            if rw is not None:
                try:
                    if rw.GetInteractor() == self.interactor:
                        return main_widget
                except Exception:
                    pass
 
        # 4. FALLBACK: Match by RenderWindow
        try:
            current_rw = self.interactor.GetRenderWindow()
            if current_rw is None:
                return None
           
            if hasattr(self.app, 'cut_section_controller'):
                cut_vtk = getattr(self.app.cut_section_controller, 'cut_vtk', None)
                if cut_vtk:
                    rw = self._safe_get_render_window(cut_vtk)
                    if rw is not None and rw == current_rw:
                        return cut_vtk
                   
            if hasattr(self.app, 'section_vtks'):
                for widget in self.app.section_vtks.values():
                    if widget:
                        rw = self._safe_get_render_window(widget)
                        if rw is not None and rw == current_rw:
                            return widget
        except Exception:
            pass                  
        return None
   
    def _get_view_index_from_interactor(self):
        """Return cross-section view index (0..3) for this interactor, or None."""
        try:
            if hasattr(self.app, "section_vtks"):
                for idx, vtk_widget in self.app.section_vtks.items():
                    if getattr(vtk_widget, "interactor", None) == self.interactor:
                        return idx
                    rw = vtk_widget.GetRenderWindow() if hasattr(vtk_widget, "GetRenderWindow") else None
                    if rw and rw.GetInteractor() == self.interactor:
                        return idx
        except Exception:
            pass
        return None
 
    def _get_section_context_for_view(self, view_idx):
        """
        Build (mask, section_points) for the requested view index from app's stored per-view data.
        
        Returns:
            mask: boolean array over full dataset (includes core + buffer points)
            section_points: transformed 2D coordinates for the section view OR 3D xyz[mask]
        
        ✅ UPDATED LOGIC:
            1. First tries to use pre-computed combined_mask + transformed points (fastest)
            2. Falls back to building combined mask from core + buffer
            3. Always prefers transformed points over raw xyz
            4. Provides detailed debug logging
        
        The transformed points are in the 2D coordinate system of the cross-section view:
            - For side view: (x, z) coordinates
            - For front view: (y, z) coordinates
        """
        try:
            app = self.app
            
            # ═══════════════════════════════════════════════════════════
            # PRIORITY PATH 1: Use pre-computed combined_mask + transformed points
            # ═══════════════════════════════════════════════════════════
            # This is the fastest and most accurate path when available
            combined_mask = getattr(app, f"section_{view_idx}_combined_mask", None)
            section_points_transformed = getattr(app, f"section_{view_idx}_points_transformed", None)
            
            if combined_mask is not None and section_points_transformed is not None:
                num_points = combined_mask.sum() if hasattr(combined_mask, 'sum') else len([x for x in combined_mask if x])
                print(f"   ✅ _get_section_context [Path 1]: Pre-computed combined_mask + transformed points")
                print(f"      View: {view_idx}, Points: {num_points:,} (core + buffer)")
                return combined_mask, section_points_transformed
            
            # ═══════════════════════════════════════════════════════════
            # FALLBACK PATH 2: Build combined mask from separate core + buffer masks
            # ═══════════════════════════════════════════════════════════
            core_mask = getattr(app, f"section_{view_idx}_core_mask", None)
            buffer_mask = getattr(app, f"section_{view_idx}_buffer_mask", None)
            
            # Check if we have any masks at all
            if core_mask is None and buffer_mask is None:
                print(f"   ⚠️ _get_section_context [Path 2]: No masks found for view {view_idx}")
                return None, None
            
            # Build combined mask
            if core_mask is None:
                combined_mask = buffer_mask
                print(f"   ⚠️ _get_section_context [Path 2]: Only buffer_mask available (unusual)")
            elif buffer_mask is None:
                combined_mask = core_mask
                print(f"   ⚠️ _get_section_context [Path 2]: Only core_mask available (no buffer)")
            else:
                combined_mask = (core_mask | buffer_mask)
                core_count = core_mask.sum() if hasattr(core_mask, 'sum') else len([x for x in core_mask if x])
                buffer_count = buffer_mask.sum() if hasattr(buffer_mask, 'sum') else len([x for x in buffer_mask if x])
                total_count = combined_mask.sum() if hasattr(combined_mask, 'sum') else len([x for x in combined_mask if x])
                print(f"   ✅ _get_section_context [Path 2]: Built combined mask")
                print(f"      Core: {core_count:,}, Buffer: {buffer_count:,}, Total: {total_count:,}")
            
            # ═══════════════════════════════════════════════════════════
            # SUB-PATH 2A: Try to use transformed points (preferred)
            # ═══════════════════════════════════════════════════════════
            section_points_transformed = getattr(app, f"section_{view_idx}_points_transformed", None)
            if section_points_transformed is not None:
                print(f"   ✅ _get_section_context [Path 2A]: Using transformed points")
                return combined_mask, section_points_transformed
            
            # ═══════════════════════════════════════════════════════════
            # SUB-PATH 2B: Fall back to raw xyz coordinates (last resort)
            # ═══════════════════════════════════════════════════════════
            # This is slower and less accurate but ensures backward compatibility
            section_points = app.data["xyz"][combined_mask]
            print(f"   ⚠️ _get_section_context [Path 2B]: Using raw xyz (fallback)")
            print(f"      Points shape: {section_points.shape if hasattr(section_points, 'shape') else 'unknown'}")
            return combined_mask, section_points
            
        except Exception as e:
            print(f"   ❌ _get_section_context_for_view FAILED for view {view_idx}: {e}")
            import traceback
            traceback.print_exc()
            return None, None
    
    def _get_view_index_from_interactor(self):
        """Return cross-section view index (0..3) for this interactor, or None."""
        try:
            if hasattr(self.app, "section_vtks"):
                for idx, vtk_widget in self.app.section_vtks.items():
                    if getattr(vtk_widget, "interactor", None) == self.interactor:
                        return idx
                    rw = vtk_widget.GetRenderWindow() if hasattr(vtk_widget, "GetRenderWindow") else None
                    if rw and rw.GetInteractor() == self.interactor:
                        return idx
        except Exception:
            pass
        return None

    # def _get_section_context_for_view(self, view_idx):
    #     """
    #     Build (mask, section_points) for the requested view index from app's stored per-view data.
    #     mask: boolean array over full dataset
    #     section_points: xyz[mask]
    #     """
    #     try:
    #         app = self.app
    #         core_mask = getattr(app, f"section_{view_idx}_core_mask", None)
    #         buffer_mask = getattr(app, f"section_{view_idx}_buffer_mask", None)

    #         if core_mask is None and buffer_mask is None:
    #             return None, None

    #         if core_mask is None:
    #             combined_mask = buffer_mask
    #         elif buffer_mask is None:
    #             combined_mask = core_mask
    #         else:
    #             combined_mask = (core_mask | buffer_mask)

    #         section_points = app.data["xyz"][combined_mask]
    #         return combined_mask, section_points
    #     except Exception as e:
    #         print(f"⚠️ _get_section_context_for_view failed for view {view_idx}: {e}")
    #         return None, None

    def _init_preview_overlay(self):
        """Initialize Qt-based preview overlay"""
        try:
            # Get the parent widget for the overlay
            parent_widget = self.interactor
            
            # Create overlay
            self._preview_overlay = PreviewOverlay(parent_widget)
            self._preview_overlay.setGeometry(parent_widget.rect())
            self._preview_overlay.show()
            self._preview_overlay.raise_()
            
            # Cache renderer and widget height for coordinate conversion
            self._cached_renderer = self.interactor.GetRenderWindow().GetRenderers().GetFirstRenderer()
            self._widget_height = parent_widget.height()
            
            print("✅ Qt preview overlay initialized")
            
        except Exception as e:
            print(f"⚠️ Failed to create Qt preview overlay: {e}")
            self._preview_overlay = None
    
    def _update_overlay_geometry(self):
        """Update overlay size to match interactor widget"""
        if self._preview_overlay is None:
            return
            
        try:
            self._preview_overlay.setGeometry(self.interactor.rect())
            self._widget_height = self.interactor.height()
        except:
            pass
    
    def _should_update(self):
        """Throttle updates to maintain smooth performance"""
        current_time = time.time() * 1000  # Convert to milliseconds
        
        if current_time - self._last_update_time >= self._update_interval:
            self._last_update_time = current_time
            return True
        return False
    
    def _world_to_screen(self, world_point):
        """Convert world coordinates to screen coordinates - OPTIMIZED"""
        try:
            if self._cached_renderer is None:
                self._cached_renderer = self.interactor.GetRenderWindow().GetRenderers().GetFirstRenderer()
            
            # Create coordinate converter
            coord = vtk.vtkCoordinate()
            coord.SetCoordinateSystemToWorld()
            
            # Handle both 2D (u, z) and 3D (x, y, z) coordinates
            if len(world_point) == 2:
                coord.SetValue(world_point[0], 0, world_point[1])
            else:
                coord.SetValue(world_point[0], world_point[1], world_point[2])
            
            # Get display coordinates
            display = coord.GetComputedDisplayValue(self._cached_renderer)
            
            # VTK uses bottom-left origin, Qt uses top-left
            screen_x = int(display[0])
            screen_y = int(self._widget_height - display[1])
            
            return QPoint(screen_x, screen_y)
            
        except Exception as e:
            return QPoint(0, 0)
    
    def _world_radius_to_screen(self, center_world, radius_world):
        """Convert world radius to screen pixels"""
        try:
            # Get screen position of center
            center_screen = self._world_to_screen(center_world)
            
            # Get screen position of a point at radius distance
            edge_world = (center_world[0] + radius_world, center_world[1])
            edge_screen = self._world_to_screen(edge_world)
            
            # Calculate pixel radius
            pixel_radius = abs(edge_screen.x() - center_screen.x())
            return max(5, pixel_radius)  # Minimum 5 pixels
            
        except:
            return 20  # Default radius

    def _display_to_world_same_depth(self, vtk_widget, center_world, dx_px=0.0, dy_px=0.0):
        """
        Convert a display offset (dx_px, dy_px) around center_world into a world point
        at the SAME display depth. This converts pixel size to world size (zoom-aware).
        """
        renderer = vtk_widget.renderer
        cxw, cyw, czw = float(center_world[0]), float(center_world[1]), float(center_world[2])

        # World -> Display to get depth (z in display space)
        renderer.SetWorldPoint(cxw, cyw, czw, 1.0)
        renderer.WorldToDisplay()
        cx, cy, cz = renderer.GetDisplayPoint()

        # Display -> World at same depth
        renderer.SetDisplayPoint(float(cx + dx_px), float(cy + dy_px), float(cz))
        renderer.DisplayToWorld()
        wx, wy, wz, w = renderer.GetWorldPoint()
        if abs(w) < 1e-12:
            return (wx, wy, wz)
        return (wx / w, wy / w, wz / w)

    def _pixel_radius_to_view_radius(self, vtk_widget, center_world, radius_px):
        """
        Convert pixel radius (screen space) into radius in tool coords:
        - Main view: (x,y)
        - Cross-section: (u,z)
        - Cut-section: projected (u,z)
        """
        try:
            center_world = (float(center_world[0]), float(center_world[1]), float(center_world[2]))
            edge_world = self._display_to_world_same_depth(vtk_widget, center_world, dx_px=float(radius_px), dy_px=0.0)

            u0, v0 = self._get_view_coordinates(center_world)
            u1, v1 = self._get_view_coordinates(edge_world)

            return float(np.hypot(u1 - u0, v1 - v0))
        except Exception:
            # fallback to old behavior if something goes wrong
            return float(getattr(self.app, "brush_radius", 1.0))

    def get_visible_class_filter(self, section_mask):
        """
        Restrict section_mask to ONLY those points whose class is visible
        in the ACTIVE view's Display Mode.
        
        ✅ FIXED: Properly detects cut section and uses slot 5 palette
        ✅ Works for: Main View, Cross-Section Views (1-4), Cut Section View
        
        section_mask: boolean mask of points in the current section
                    (same length as the full dataset)
        returns: boolean mask, same shape, with invisible classes removed.
        
        View mapping:
        - Slot 0: Main View
        - Slot 1-4: Cross-Section Views 1-4
        - Slot 5: Cut Section View (NEW!)
        """
        
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 1: Safety checks
        # ═══════════════════════════════════════════════════════════════════════
        
        if section_mask is None:
            return None
        
        # Need classification array
        if not hasattr(self.app, "data") or "classification" not in self.app.data:
            print("⚠️ No classification data – skipping visibility filter")
            return section_mask
        
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 2: Determine which view is active (main, cross-section, or cut)
        # ═══════════════════════════════════════════════════════════════════════
        
        dialog = getattr(self.app, "display_mode_dialog", None)
        
        if dialog is None:
            print("ℹ️ No DisplayModeDialog – using section_mask only (no protection)")
            return section_mask
        
        # ✅ PRIORITY 1: Check if we're in CUT SECTION (highest priority)
        is_cut_section = False
        slot_idx = None
        view_context = None
        
        # Method 1: Check active_classify_target flag
        if getattr(self.app, "active_classify_target", None) == "cut":
            is_cut_section = True
        
        # Method 2: Check by comparing interactor's widget with cut_vtk
        if not is_cut_section and hasattr(self.app, 'cut_section_controller'):
            try:
                active_widget = self._get_active_vtk_widget()
                cut_vtk = getattr(self.app.cut_section_controller, 'cut_vtk', None)
                
                if active_widget is not None and cut_vtk is not None:
                    if active_widget == cut_vtk:
                        is_cut_section = True
                        print("✅ Detected: In CUT SECTION (by widget match)")
            except Exception as e:
                print(f"⚠️ Widget detection failed: {e}")
        
        # ✅ Cut section handling
        if is_cut_section:
            slot_idx = 5  # ✅ CUT SECTION always uses slot 5
            view_context = "Cut Section View"
            print(f"📍 Visibility filter for {view_context} (slot {slot_idx})")
        
        # ✅ PRIORITY 2: Check if we're in CROSS-SECTION
        else:
            active_view = getattr(self.app.section_controller, "active_view", None)
            
            if active_view is not None and 0 <= active_view <= 3:
                slot_idx = active_view + 1  # Convert 0-3 to 1-4
                view_context = f"Cross-Section View {active_view + 1}"
                print(f"📍 Visibility filter for {view_context} (slot {slot_idx})")
            
            # ✅ PRIORITY 3: Fallback (shouldn't normally happen here)
            else:
                print("ℹ️ No active_view detected – using section_mask only")
                return section_mask
        
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 3: Get visible classes from display_mode_dialog
        # ═══════════════════════════════════════════════════════════════════════
        
        if slot_idx is None:
            print("ℹ️ Could not determine view slot – using section_mask only")
            return section_mask
        
        try:
            # ✅ Method 1: Use dialog's dedicated method
            if hasattr(dialog, 'get_visible_classes_for_view'):
                visible_classes = set(dialog.get_visible_classes_for_view(slot_idx))
            
            # ✅ Method 2: Direct access to view_palettes
            elif hasattr(dialog, 'view_palettes') and slot_idx in dialog.view_palettes:
                palette = dialog.view_palettes[slot_idx]
                visible_classes = set([c for c, info in palette.items() if info.get('show', True)])
                print(f"   📋 Using view_palettes[{slot_idx}] directly")
            
            else:
                print(f"⚠️ Could not get visible classes for {view_context} (slot {slot_idx})")
                return section_mask
        
        except Exception as e:
            print(f"⚠️ get_visible_classes_for_view({slot_idx}) failed: {e}")
            return section_mask
        
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 4: Check if any classes are visible
        # ═══════════════════════════════════════════════════════════════════════
        
        # If nothing is checked for this view, don't block classification
        if not visible_classes:
            print(f"ℹ️ {view_context}: no visible classes selected – allowing all section points")
            return section_mask
        
        print(f"🔍 {view_context} (slot {slot_idx}) visible classes: {visible_classes}")
        
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 5: Build final mask = section_mask ∧ (class ∈ visible_classes)
        # ═══════════════════════════════════════════════════════════════════════
        
        cls_all = self.app.data["classification"]
        
        # indices of points that are in this section
        section_idx = np.where(section_mask)[0]
        section_cls = cls_all[section_idx]
        
        # True only for section points whose class is visible in THIS view
        visible_in_section = np.isin(section_cls, list(visible_classes))
        
        # Start from all False; enable only visible section points
        filtered_mask = np.zeros_like(section_mask, dtype=bool)
        filtered_mask[section_idx[visible_in_section]] = True
        
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 6: Report statistics
        # ═══════════════════════════════════════════════════════════════════════
        
        total_section = section_mask.sum()
        visible_section = filtered_mask.sum()
        filtered_out = total_section - visible_section
        
        print(f"   📊 Section statistics:")
        print(f"      Total points in section: {total_section}")
        print(f"      Visible points (will classify): {visible_section}")
        print(f"      Hidden points (PROTECTED): {filtered_out}")
        
        return filtered_mask


    # ---------------- PICK ----------------
    def _pick_world_point(self, x, y):
        """Pick 3D world coordinates from screen position."""
        picker = self.interactor.GetPicker()
        renderer = self.interactor.GetRenderWindow().GetRenderers().GetFirstRenderer()
        picker.Pick(x, y, 0, renderer)
        return picker.GetPickPosition()

    # ---------------- TEST ----------------
    def _draw_test_line(self):
        """Draw a static test line to verify rendering works."""
        try:
            renderer = self.interactor.GetRenderWindow().GetRenderers().GetFirstRenderer()
            
            # Get camera bounds to place line in view
            cam = renderer.GetActiveCamera()
            fp = cam.GetFocalPoint()
            
            # Draw a diagonal test line
            pts = vtkPoints()
            pts.InsertNextPoint(fp[0] - 5, 0, fp[2] - 5)
            pts.InsertNextPoint(fp[0] + 5, 0, fp[2] + 5)
            
            lines = vtkCellArray()
            lines.InsertNextCell(2)
            lines.InsertCellPoint(0)
            lines.InsertCellPoint(1)
            
            poly = vtkPolyData()
            poly.SetPoints(pts)
            poly.SetLines(lines)
            
            mapper = vtkPolyDataMapper()
            mapper.SetInputData(poly)
            
            test_actor = vtkActor()
            test_actor.SetMapper(mapper)
            
            prop = test_actor.GetProperty()
            prop.SetColor(1, 0, 0)  # RED
            prop.SetLineWidth(10)
            prop.SetDepthTest(False)
            prop.SetLighting(False)
            
            renderer.AddActor(test_actor)
            self._safe_render_interactor()
            
            print("✅ Test line drawn (RED diagonal) - if you see this, rendering works!")
        except Exception as e:
            print(f"⚠️ Test line failed: {e}")

    # ---------------- PREVIEWS ----------------
    def _draw_temp_line(self, P1, P2):
        """
        ✅ Senior Refactor: Handles rapid-fire classification.
        Ensures actor persistence even if the renderer is cleared between actions.
        """
        vtk_widget = self._get_active_vtk_widget()
        if not vtk_widget: return
        renderer = vtk_widget.renderer

        # 1. Pipeline Initialization & Recovery
        if not hasattr(self, "line_actor") or self.line_actor is None:
            self.line_pts = vtk.vtkPoints()
            self.line_pts.SetNumberOfPoints(2)
            lines = vtk.vtkCellArray()
            lines.InsertNextCell(2); lines.InsertCellPoint(0); lines.InsertCellPoint(1)
            self.line_poly = vtk.vtkPolyData()
            self.line_poly.SetPoints(self.line_pts); self.line_poly.SetLines(lines)
            
            mapper = vtk.vtkPolyDataMapper2D()
            mapper.SetInputData(self.line_poly)
            c = vtk.vtkCoordinate(); c.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(c)

            self.line_actor = vtk.vtkActor2D()
            self.line_actor.SetMapper(mapper)
            p = self.line_actor.GetProperty()
            p.SetColor(1, 1, 0); p.SetLineWidth(2); p.SetOpacity(1.0)

        # 2. MANDATORY SYNC: Ensure actor is actually in the renderer's draw list
        if not renderer.HasViewProp(self.line_actor):
            renderer.AddActor2D(self.line_actor)
        
        self.line_actor.VisibilityOn()

        # 3. Fast Coordinate Update
        u1, v1 = self._get_view_coordinates(P1)
        u2, v2 = self._get_view_coordinates(P2)
        w1 = self._view2d_to_world(u1, v1)
        w2 = self._view2d_to_world(u2, v2)

        if not hasattr(self, "_coord_converter"):
            self._coord_converter = vtk.vtkCoordinate()
            self._coord_converter.SetCoordinateSystemToWorld()

        for i, pos in enumerate([w1, w2]):
            self._coord_converter.SetValue(*pos)
            d = self._coord_converter.GetComputedDisplayValue(renderer)
            self.line_pts.SetPoint(i, d[0], d[1], 0)

        self.line_pts.Modified()
        self.line_poly.Modified()

        # 4. Vertical Guides Sync
        tool = getattr(self.app, "active_classify_tool", None)
        if tool in ("above_line", "below_line"):
            self._draw_vertical_guides(P1, P2, tool, renderer)
        # Render is batched by _on_mouse_move_with_preview — do NOT call here

    def _draw_vertical_guides(self, P1, P2, tool, renderer):
        """
        ✅ Senior Refactor: Persistent dashed guides.
        Verified for high-speed repeated interaction.
        """
        if not hasattr(self, "dotted_actor") or self.dotted_actor is None:
            self.dotted_pts = vtk.vtkPoints()
            self.dotted_lines = vtk.vtkCellArray()
            self.dotted_poly = vtk.vtkPolyData()
            self.dotted_poly.SetPoints(self.dotted_pts); self.dotted_poly.SetLines(self.dotted_lines)
            m = vtk.vtkPolyDataMapper2D(); m.SetInputData(self.dotted_poly)
            c = vtk.vtkCoordinate(); c.SetCoordinateSystemToDisplay()
            m.SetTransformCoordinate(c)
            self.dotted_actor = vtk.vtkActor2D(); self.dotted_actor.SetMapper(m)
            p = self.dotted_actor.GetProperty()
            p.SetColor(1, 1, 0); p.SetLineWidth(2); p.SetOpacity(0.9)

        # Ensure actor presence in the current renderer
        if not renderer.HasViewProp(self.dotted_actor):
            renderer.AddActor2D(self.dotted_actor)

        # Update Display values
        self._coord_converter.SetValue(*P1)
        p1 = self._coord_converter.GetComputedDisplayValue(renderer)
        self._coord_converter.SetValue(*P2)
        p2 = self._coord_converter.GetComputedDisplayValue(renderer)
        win_h = renderer.GetRenderWindow().GetSize()[1]

        self.dotted_pts.Reset(); self.dotted_lines.Reset()
        dash, gap, idx = 8, 6, 0

        def fill(x, y_start):
            nonlocal idx
            y = y_start
            step = (dash + gap) if tool == "above_line" else -(dash + gap)
            limit = win_h if tool == "above_line" else 0
            
            while (y < limit if tool == "above_line" else y > limit):
                y2 = min(y + dash, win_h) if tool == "above_line" else max(y - dash, 0)
                self.dotted_pts.InsertNextPoint(x, y, 0)
                self.dotted_pts.InsertNextPoint(x, y2, 0)
                self.dotted_lines.InsertNextCell(2)
                self.dotted_lines.InsertCellPoint(idx); self.dotted_lines.InsertCellPoint(idx + 1)
                idx += 2; y += step

        fill(p1[0], p1[1]); fill(p2[0], p2[1])
        
        if idx > 0:
            self.dotted_pts.Modified(); self.dotted_poly.Modified()
            self.dotted_actor.VisibilityOn()
        else:
            self.dotted_actor.VisibilityOff()

    def _draw_rectangle_preview(self, P1, P2):
        """
        ✅ Senior Refactor: Persistent Rectangle.
        Forces re-attachment to renderer to prevent disappearance during fast clicks.
        """
        vtk_widget = self._get_active_vtk_widget()
        if not vtk_widget: return
        renderer = vtk_widget.renderer

        if not hasattr(self, "rect_actor") or self.rect_actor is None:
            self.rect_pts = vtk.vtkPoints()
            self.rect_pts.SetNumberOfPoints(4)
            self.rect_lines = vtk.vtkCellArray()
            for i in range(4):
                self.rect_lines.InsertNextCell(2)
                self.rect_lines.InsertCellPoint(i); self.rect_lines.InsertCellPoint((i + 1) % 4)
            self.rect_poly = vtk.vtkPolyData()
            self.rect_poly.SetPoints(self.rect_pts); self.rect_poly.SetLines(self.rect_lines)
            m = vtk.vtkPolyDataMapper2D(); m.SetInputData(self.rect_poly)
            c = vtk.vtkCoordinate(); c.SetCoordinateSystemToDisplay()
            m.SetTransformCoordinate(c)
            self.rect_actor = vtk.vtkActor2D(); self.rect_actor.SetMapper(m)
            p = self.rect_actor.GetProperty()
            p.SetColor(1, 1, 0); p.SetLineWidth(2); p.SetOpacity(1.0)

        # Recovery Logic: If renderer was cleared, re-add actor immediately
        if not renderer.HasViewProp(self.rect_actor):
            renderer.AddActor2D(self.rect_actor)
        
        self.rect_actor.VisibilityOn()

        u1, v1 = self._get_view_coordinates(P1)
        u2, v2 = self._get_view_coordinates(P2)
        corners = [(u1, v1), (u2, v1), (u2, v2), (u1, v2)]

        if not hasattr(self, "_coord_converter"):
            self._coord_converter = vtk.vtkCoordinate()
            self._coord_converter.SetCoordinateSystemToWorld()

        for i, (u, v) in enumerate(corners):
            xw, yw, zw = self._view2d_to_world(u, v)
            self._coord_converter.SetValue(xw, yw, zw)
            d = self._coord_converter.GetComputedDisplayValue(renderer)
            self.rect_pts.SetPoint(i, d[0], d[1], 0)

        self.rect_pts.Modified()
        self._safe_render(vtk_widget)

    def _draw_freehand_preview(self, live_point=None):
        """
        ✅ PERFORMANCE FIX: Reuse VTK actor — NO RemoveActor/AddActor per frame.
        Only updates point coordinates and calls Modified(). Zero allocation after init.
        """
        if len(self.drawing_points) < 1:
            return

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        # Collect all points
        all_pts = list(self.drawing_points)
        if live_point:
            all_pts.append(live_point)

        if len(all_pts) < 2:
            return

        n = len(all_pts)

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_freehand_pts") or self.freehand_actor is None:
            from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D, vtkActor2D, vtkCoordinate as _C

            self._freehand_pts   = vtkPoints()
            self._freehand_lines = vtkCellArray()
            self._freehand_poly  = vtkPolyData()
            self._freehand_poly.SetPoints(self._freehand_pts)
            self._freehand_poly.SetLines(self._freehand_lines)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._freehand_poly)
            dc = _C(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.freehand_actor = vtkActor2D()
            self.freehand_actor.SetMapper(mapper)
            prop = self.freehand_actor.GetProperty()
            prop.SetColor(1, 0.8, 0)
            prop.SetLineWidth(2)
            prop.SetOpacity(0.8)

            renderer.AddActor2D(self.freehand_actor)

        # Re-attach if renderer was cleared
        if not renderer.HasViewProp(self.freehand_actor):
            renderer.AddActor2D(self.freehand_actor)
        self.freehand_actor.VisibilityOn()

        # ── FAST COORDINATE UPDATE ───────────────────────────────────────────
        if not hasattr(self, "_freehand_coord"):
            from vtkmodules.vtkRenderingCore import vtkCoordinate as _C
            self._freehand_coord = _C()
            self._freehand_coord.SetCoordinateSystemToWorld()

        coord = self._freehand_coord
        self._freehand_pts.Reset()
        self._freehand_lines.Reset()

        for i, (u, z) in enumerate(all_pts):
            xw, yw, zw = self._view2d_to_world(u, z)
            coord.SetValue(xw, yw, zw)
            d = coord.GetComputedDisplayValue(renderer)
            self._freehand_pts.InsertNextPoint(d[0], d[1], 0)
            if i > 0:
                self._freehand_lines.InsertNextCell(2)
                self._freehand_lines.InsertCellPoint(i - 1)
                self._freehand_lines.InsertCellPoint(i)

        self._freehand_pts.Modified()
        self._freehand_poly.Modified()
        # Render is batched by caller (_on_mouse_move_with_preview)



    def _draw_polygon_preview(self, live_point=None):
        """
        ✅ PERFORMANCE FIX: Reuse Actor2D — no RemoveActor/new objects per frame.
        """
        if len(self.drawing_points) < 1:
            return

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        all_pts = list(self.drawing_points)
        if live_point:
            all_pts.append(live_point)

        n = len(all_pts)

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_poly_pts_2d") or self.poly_actor is None:
            from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D, vtkActor2D, vtkCoordinate as _C

            self._poly_pts_2d   = vtkPoints()
            self._poly_lines_2d = vtkCellArray()
            self._poly_poly_2d  = vtkPolyData()
            self._poly_poly_2d.SetPoints(self._poly_pts_2d)
            self._poly_poly_2d.SetLines(self._poly_lines_2d)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._poly_poly_2d)
            dc = _C(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.poly_actor = vtkActor2D()
            self.poly_actor.SetMapper(mapper)
            prop = self.poly_actor.GetProperty()
            prop.SetColor(1, 1, 0)
            prop.SetLineWidth(4)
            prop.SetOpacity(1.0)

            renderer.AddActor2D(self.poly_actor)

        if not renderer.HasViewProp(self.poly_actor):
            renderer.AddActor2D(self.poly_actor)
        self.poly_actor.VisibilityOn()

        # ── FAST COORDINATE UPDATE ───────────────────────────────────────────
        if not hasattr(self, "_poly_coord_conv"):
            from vtkmodules.vtkRenderingCore import vtkCoordinate as _C
            self._poly_coord_conv = _C()
            self._poly_coord_conv.SetCoordinateSystemToWorld()

        coord = self._poly_coord_conv
        self._poly_pts_2d.Reset()
        self._poly_lines_2d.Reset()

        for i, (u, z) in enumerate(all_pts):
            xw, yw, zw = self._view2d_to_world(u, z)
            coord.SetValue(xw, yw, zw)
            d = coord.GetComputedDisplayValue(renderer)
            self._poly_pts_2d.InsertNextPoint(d[0], d[1], 0)
            if i > 0:
                self._poly_lines_2d.InsertNextCell(2)
                self._poly_lines_2d.InsertCellPoint(i - 1)
                self._poly_lines_2d.InsertCellPoint(i)

        # Close polygon if > 2 points
        if n > 2:
            self._poly_lines_2d.InsertNextCell(2)
            self._poly_lines_2d.InsertCellPoint(n - 1)
            self._poly_lines_2d.InsertCellPoint(0)

        self._poly_pts_2d.Modified()
        self._poly_poly_2d.Modified()
        # Render batched by caller

    def _draw_brush_cursor(self, center, radius=20.0):
        """
        ✅ PERFORMANCE FIX: Brush cursor in DISPLAY pixels (zoom invariant).
        Reuses VTK actor — only updates point data. Zero allocation per frame.
        """
        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        x, y = self.interactor.GetEventPosition()
        r = max(float(radius), 3.0)

        num_segments = 32
        dot_segments = 8

        # Total points: dashed circle (num_segments pts) + crosshair (4 pts) + dot (dot_segments*2 pts)
        # Each dash: 2 pts  ×  num_segments/2 dashes = num_segments pts
        # Crosshair: 4 pts (2 lines × 2 pts)
        # Dot ring: dot_segments × 2 pts
        total_pts = num_segments + 4 + dot_segments * 2

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_brush_pts") or self.brush_actor is None:
            from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D, vtkActor2D, vtkCoordinate as _C

            self._brush_pts   = vtkPoints()
            self._brush_lines = vtkCellArray()
            self._brush_poly  = vtkPolyData()
            self._brush_poly.SetPoints(self._brush_pts)
            self._brush_poly.SetLines(self._brush_lines)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._brush_poly)
            dc = _C(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.brush_actor = vtkActor2D()
            self.brush_actor.SetMapper(mapper)
            prop = self.brush_actor.GetProperty()
            prop.SetColor(1, 1, 0)
            prop.SetLineWidth(3)
            prop.SetOpacity(0.9)

            renderer.AddActor2D(self.brush_actor)

        if not renderer.HasViewProp(self.brush_actor):
            renderer.AddActor2D(self.brush_actor)
        self.brush_actor.VisibilityOn()

        # ── FAST GEOMETRY UPDATE (display coords, no world conversion) ────────
        pts   = self._brush_pts
        lines = self._brush_lines
        pts.Reset()
        lines.Reset()

        def add_seg(p0, p1):
            i0 = pts.InsertNextPoint(float(p0[0]), float(p0[1]), 0.0)
            i1 = pts.InsertNextPoint(float(p1[0]), float(p1[1]), 0.0)
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i0)
            lines.InsertCellPoint(i1)

        # dashed circle (every other segment)
        for i in range(0, num_segments, 2):
            a1 = 2.0 * np.pi * i / num_segments
            a2 = 2.0 * np.pi * (i + 1) / num_segments
            p1 = (x + r * np.cos(a1), y + r * np.sin(a1))
            p2 = (x + r * np.cos(a2), y + r * np.sin(a2))
            add_seg(p1, p2)

        # crosshair
        ch = r * 0.3
        add_seg((x - ch, y), (x + ch, y))
        add_seg((x, y - ch), (x, y + ch))

        # center dot ring
        dot_r = max(2.0, r * 0.05)
        for i in range(dot_segments):
            a1 = 2.0 * np.pi * i / dot_segments
            a2 = 2.0 * np.pi * (i + 1) / dot_segments
            p1 = (x + dot_r * np.cos(a1), y + dot_r * np.sin(a1))
            p2 = (x + dot_r * np.cos(a2), y + dot_r * np.sin(a2))
            add_seg(p1, p2)

        pts.Modified()
        self._brush_poly.Modified()
        # Render batched by caller

    # def _clear_all_previews(self):
    #     """
    #     ✅ Optimized Clear: Uses Visibility toggles instead of Actor removal.
    #     Eliminates the 'Delete-Recreate' lag and prevents preview flickering.
    #     """
    #     # 1. Identify all potential actor names
    #     actor_names = [
    #         "line_actor", "dotted_actor", "rect_actor", "circle_actor",
    #         "brush_actor", "polygon_actor", "freehand_actor", "poly_actor",
    #         "line_actor_cut", "dotted_actor_cut", "rect_actor_cut", "circle_actor_cut",
    #         "brush_actor_cut", "freehand_actor_cut", "poly_actor_cut",
    #     ]

    #     # 2. Batch Visibility Change (Instantaneous)
    #     for name in actor_names:
    #         actor = getattr(self, name, None)
    #         if actor:
    #             # Instead of removing/None, we just hide. 
    #             # This keeps the VTK pipeline ready for the next interaction.
    #             actor.VisibilityOff()

    #     # 3. Reset state variables
    #     self.P1 = None
    #     self.is_dragging = False
    #     self.drawing_points = []
    #     self.is_drawing_freehand = False
        
    #     if hasattr(self, 'drawing_points_display_cut'):
    #         self.drawing_points_display_cut = []
    #     if hasattr(self, 'P1_display_cut'):
    #         self.P1_display_cut = None

    #     # 4. Single Final Render Call
    #     # We only render ONCE to update the screen, not once per renderer/actor.
    #     vtk_widget = self._get_active_vtk_widget()
    #     if vtk_widget:
    #         try:
    #             self._safe_render(vtk_widget)
    #         except Exception:
    #             pass
        
    #     # Also render cut-section if it exists
    #     if hasattr(self.app, 'cut_section_controller'):
    #         cut_vtk = getattr(self.app.cut_section_controller, 'cut_vtk', None)
    #         if cut_vtk and hasattr(cut_vtk, 'renderer'):
    #             try:
    #                 self._safe_render(cut_vtk)
    #             except Exception:
    #                 pass

    def _clear_all_previews(self):
        """
        ✅ Optimized Clear: Uses Visibility toggles instead of Actor removal.
        Eliminates the 'Delete-Recreate' lag and prevents preview flickering.
    
        ✅ FIX (fast-classification): Reset throttle timestamps so the very
        first mouse-move of the NEXT classification is never skipped.
        """
        # 1. Identify all potential actor names
        actor_names = [
            "line_actor", "dotted_actor", "rect_actor", "circle_actor",
            "brush_actor", "polygon_actor", "freehand_actor", "poly_actor",
            "line_actor_cut", "dotted_actor_cut", "rect_actor_cut", "circle_actor_cut",
            "brush_actor_cut", "freehand_actor_cut", "poly_actor_cut",
        ]
    
        # 2. Batch Visibility Change (Instantaneous)
        for name in actor_names:
            actor = getattr(self, name, None)
            if actor:
                actor.VisibilityOff()
        self._hide_preview_overlay_for_pan()
    
        # 3. Reset state variables
        self.P1 = None
        self.is_dragging = False
        self.drawing_points = []
        self.is_drawing_freehand = False
    
        if hasattr(self, 'drawing_points_display_cut'):
            self.drawing_points_display_cut = []
        if hasattr(self, 'P1_display_cut'):
            self.P1_display_cut = None
    
        # ✅ FIX A — Reset render/move throttles so the NEXT classification's
        # first mouse-move is never accidentally skipped by the 16 ms guard.
        self._last_render_time     = 0.0
        self._last_mouse_move_time = 0.0
    
        # 4. Single Final Render Call
        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget:
            try:
                self._safe_render(vtk_widget)
            except Exception:
                pass
    
        # Also render cut-section if it exists
        if hasattr(self.app, 'cut_section_controller'):
            cut_vtk = getattr(self.app.cut_section_controller, 'cut_vtk', None)
            if cut_vtk and hasattr(cut_vtk, 'renderer'):
                try:
                    self._safe_render(cut_vtk)
                except Exception:
                    pass  
 

    def _on_mouse_move_with_preview(self, obj, evt):
            """
            ✅ FIXED: Shows previews during drag for ALL tools
            ✅ FIXED: Brush preview size does NOT change with zoom
            ✅ FIXED: Brush classification area MATCHES the preview (pixel -> view radius conversion)
            ✅ FIXED: Above/Below line uses EXACT same P2 on release as preview (prevents snapping to pole)
            ✅ FIXED: Rectangle uses EXACT same P2 on release as preview (prevents coordinate mismatch)

            ✅ FIX (safe): ensure np is always defined in this function scope to avoid:
            "local variable 'np' referenced before assignment"
            """
            import numpy as np  # ✅ IMPORTANT: prevents UnboundLocalError for np in this method

            current_time = time.time()

            if not hasattr(self, '_last_mouse_move_time'):
                self._last_mouse_move_time = 0.0

            # Skip if less than 16ms since last update (60 FPS)
            if (current_time - self._last_mouse_move_time) < 0.016:
                self._do_safe_pan()  # ✅ Custom pan — no VTK Render()
                return

            self._last_mouse_move_time = current_time

            # ✅ SAFETY CHECKS
            if not hasattr(self, 'app') or self.app is None:
                return
            if not hasattr(self, 'style') or self.style is None:
                return
            if not hasattr(self, 'interactor') or self.interactor is None:
                return

            tool = getattr(self.app, "active_classify_tool", None)

            if self._is_classification_paused_for_pan(tool):
                self._do_safe_pan()
                return

            # Try to pick world point (fast, non-snapping)
            try:
                dx, dy = self._get_display_point()
                P2 = self._display_to_world_fast(dx, dy)
            except Exception:
                self._do_safe_pan()  # ✅ Custom pan — no VTK Render()
                return

            # ✅ Cache active vtk widget (refresh every 100ms)
            if not hasattr(self, '_cached_vtk_widget'):
                self._cached_vtk_widget = None
                self._cached_widget_time = 0.0

            if (current_time - self._cached_widget_time) > 0.1:
                self._cached_vtk_widget = self._get_active_vtk_widget()
                self._cached_widget_time = current_time

            vtk_widget = self._cached_vtk_widget

            # ✅ Detect CUT SECTION
            is_cut_section = False
            if hasattr(self.app, 'cut_section_controller'):
                if vtk_widget == getattr(self.app.cut_section_controller, 'cut_vtk', None):
                    is_cut_section = True

            # Render throttle
            if not hasattr(self, '_last_render_time'):
                self._last_render_time = 0.0

            # -----------------------
            # PREVIEW RENDER LOGIC
            # -----------------------

            # ✅ Circle preview
            if tool == "circle" and self.P1 is not None and self.is_dragging:
                # ✅ CRITICAL: Store P2 for classification to match preview
                self._last_circle_preview_P2 = P2
                
                if is_cut_section:
                    self._draw_circle_preview_cut(self.P1, P2)
                elif self._is_main_view():
                    self._draw_circle_preview_main(self.P1, P2)
                else:
                    self._draw_circle_preview(self.P1, P2)

                if vtk_widget and (current_time - self._last_render_time) > 0.016:
                    self._safe_render(vtk_widget)
                    self._last_render_time = current_time

            # ✅ Rectangle preview
            if tool == "rectangle" and self.P1 is not None and self.is_dragging:
                # ✅ CRITICAL: Store P2 for classification to match preview
                self._last_rectangle_preview_P2 = P2
                
                if is_cut_section:
                    if hasattr(self, "rect_actor_cut") and self.rect_actor_cut:
                        try:
                            vtk_widget.renderer.RemoveActor2D(self.rect_actor_cut)
                        except Exception:
                            pass
                        self.rect_actor_cut = None
                    self._draw_rectangle_preview_cut(self.P1, P2)
                else:
                    self._draw_rectangle_preview(self.P1, P2)

                if vtk_widget and (current_time - self._last_render_time) > 0.016:
                    self._safe_render(vtk_widget)
                    self._last_render_time = current_time

            # ✅ Line tools preview
            elif tool in ("above_line", "below_line") and self.P1 is not None and self.is_dragging:
                self._last_line_preview_P2 = P2

                if is_cut_section:
                    self._draw_line_preview_cut(self.P1, P2)
                else:
                    self._draw_temp_line(self.P1, P2)

                if vtk_widget and (current_time - self._last_render_time) > 0.016:
                    self._safe_render(vtk_widget)
                    self._last_render_time = current_time

            # ✅ Brush tool
            elif tool == "brush":
                if self.is_dragging:
                    self._last_brush_preview_P2 = P2  # ✅ non-snapping endpoint used for preview
                    # ✅ FIX 1: Calculate center differently for cut section
                    if is_cut_section:
                        # For cut section, use projected coordinates
                        try:
                            from ..classification_tools import _project_to_cut_view
                            P2_cut = _project_to_cut_view(self.app, np.array([P2]))[0]
                            center = (float(P2_cut[0]), float(P2_cut[1]))
                            print(f"🖌️ Cut brush center (projected): ({center[0]:.2f}, {center[1]:.2f})")
                        except Exception as e:
                            print(f"⚠️ Cut projection failed: {e}, using fallback")
                            center = self._get_view_coordinates(P2)
                    else:
                        # Cross-section or main view - existing logic works
                        center = self._get_view_coordinates(P2)

                    brush_size_pixels = float(getattr(self.app, "brush_preview_px", 20.0))

                    radius_view = float(getattr(self.app, "brush_radius", 1.0))
                    if vtk_widget is not None:
                        try:
                            radius_view = float(self._pixel_radius_to_view_radius(
                                vtk_widget, P2, brush_size_pixels
                            ))
                        except Exception:
                            radius_view = float(getattr(self.app, "brush_radius", 1.0))

                    self._last_brush_radius_view = radius_view

                    brush_shape = getattr(self.app, "brush_shape", "circle")

                    if is_cut_section:
                        if brush_shape == "rectangle":
                            self._draw_rectangle_cursor_cut_display(P2, brush_size_pixels)
                        else:
                            self._draw_brush_cursor_cut_display(P2, brush_size_pixels)
                    else:
                        if brush_shape == "rectangle":
                            self._draw_rectangle_cursor(center, brush_size_pixels)
                        else:
                            self._draw_brush_cursor(center, brush_size_pixels)

                # ✅ UNIFIED RENDER: For main view brush, DON'T render here —
                # the classification drag handler below does a throttled render
                # that includes both cursor + classification changes in one pass.
                if self._is_main_view() and self.is_dragging and tool == "brush":
                    pass  # Skip — render happens in classification block below
                elif vtk_widget and (current_time - self._last_render_time) > 0.016:
                    self._safe_render(vtk_widget)
                    self._last_render_time = current_time

                if self.is_dragging:
                    if self._is_main_view():
                        # ═══════════════════════════════════════════════════════
                        # MICROSTATION PRODUCTION BRUSH
                        # Phase 1 (every mouse move): spatial lookup → CPU classify → accumulate
                        # Phase 2 (30fps tick only): single GPU injection + render
                        # Zero allocation per stamp. All numpy, no Python loops.
                        # ═══════════════════════════════════════════════════════
                        xyz = self.app.data["xyz"]
                        to_class = getattr(self.app, "to_class", None)

                        if not hasattr(self, "_brush_accumulated_mask") or self._brush_accumulated_mask is None:
                            self._brush_accumulated_mask = np.zeros(len(xyz), dtype=bool)
                            self._brush_old_classes = {}
                            self._brush_frame_chunks = []

                        if not hasattr(self, "_brush_stroke_positions") or self._brush_stroke_positions is None:
                            self._brush_stroke_positions = []

                        prev = getattr(self, "_last_brush_center", None)

                        positions = []
                        if prev is None:
                            positions.append(center)
                        else:
                            dx2 = center[0] - prev[0]
                            dy2 = center[1] - prev[1]
                            dist = float(np.hypot(dx2, dy2))
                            step = max(radius_view * 0.5, 1e-6)
                            n = max(1, int(dist / step))
                            for i in range(1, n + 1):
                                cx = prev[0] + dx2 * (i / n)
                                cy = prev[1] + dy2 * (i / n)
                                positions.append((cx, cy))

                        # PHASE 1: Spatial lookup + CPU classify (no GPU, no render)
                        has_index = (
                            getattr(self, '_brush_spatial_index', None) is not None
                            and getattr(self, '_brush_grid_params', None) is not None
                        )

                        if has_index and to_class is not None:
                            classes = self.app.data["classification"]
                            from_classes = getattr(self.app, "from_classes", None)
                            visible_classes = getattr(self, "_brush_main_visible_classes", None)
                            visible_classes_arr = getattr(self, "_brush_main_visible_classes_arr", None)

                            for pos in positions:
                                hit = self._get_points_in_radius_fast(
                                    float(pos[0]), float(pos[1]), float(radius_view)
                                )
                                if len(hit) == 0:
                                    continue

                                # Filter already-done points
                                fresh = hit[~self._brush_accumulated_mask[hit]]
                                if len(fresh) == 0:
                                    continue

                                # Filter by Main View visibility (slot 0): hidden classes are protected.
                                if visible_classes == []:
                                    continue
                                if visible_classes_arr is not None:
                                    vis_mask = np.isin(classes[fresh], visible_classes_arr)
                                    fresh = fresh[vis_mask]
                                    if len(fresh) == 0:
                                        continue

                                # Filter from_classes
                                if from_classes:
                                    fc_mask = np.isin(classes[fresh], from_classes)
                                    fresh = fresh[fc_mask]
                                    if len(fresh) == 0:
                                        continue

                                # Save old classes for undo (vectorized)
                                old_cls = classes[fresh]
                                for i in range(len(fresh)):
                                    idx = int(fresh[i])
                                    if idx not in self._brush_old_classes:
                                        self._brush_old_classes[idx] = int(old_cls[i])

                                # CPU classify immediately
                                classes[fresh] = to_class
                                self._brush_accumulated_mask[fresh] = True

                                # Accumulate raw chunks and dedupe once per render tick.
                                self._brush_frame_chunks.append(fresh)

                            self._brush_needs_render = True

                        # PHASE 2: 30fps tick — single GPU injection + render
                        frame_chunks = getattr(self, '_brush_frame_chunks', None)
                        frame_fresh = None
                        if frame_chunks:
                            if len(frame_chunks) == 1:
                                frame_fresh = np.unique(frame_chunks[0])
                            else:
                                frame_fresh = np.unique(np.concatenate(frame_chunks))

                        if (frame_fresh is not None and len(frame_fresh) > 0
                                and getattr(self, '_brush_needs_render', False)):
                            now = time.time()
                            if (now - getattr(self, '_brush_last_render_time', 0)) > 0.033:
                                try:
                                    from gui.unified_actor_manager import (
                                        _get_unified_actor, _mark_actor_dirty,
                                        fast_cross_section_update
                                    )
                                    palette = self._get_main_view_palette() or {}
                                    entry = palette.get(int(to_class), {})
                                    color = np.array(
                                        entry.get('color', (128, 128, 128))
                                        if entry.get('show', True)
                                        else (0, 0, 0),
                                        dtype=np.uint8
                                    )

                                    # Direct RGB poke on unified actor (no mask scan)
                                    actor = _get_unified_actor(self.app)
                                    if actor is not None:
                                        rgb_ptr = getattr(actor, '_naksha_rgb_ptr', None)
                                        gi = getattr(self.app, '_main_global_indices', None)
                                        if rgb_ptr is not None and rgb_ptr.flags.writeable:
                                            if gi is not None:
                                                # Write ALL accumulated points (idempotent — same color re-write is free)
                                                local = np.where(self._brush_accumulated_mask[gi])[0]
                                                if len(local) > 0:
                                                    rgb_ptr[local] = color
                                            else:
                                                rgb_ptr[frame_fresh] = color

                                            vtk_ca = getattr(actor, '_naksha_vtk_array', None)
                                            if vtk_ca:
                                                vtk_ca.Modified()
                                            _mark_actor_dirty(actor)
                                  
                                        # ✅ MAIN VIEW ONLY during drag — sections update on release
                                        if (getattr(self.app, "display_mode", "class") == "shaded_class"
                                                and _shading_mesh_exists(self.app)):
                                            try:
                                                from gui.shading_display import refresh_shaded_after_classification_fast
                                                acc_mask = self._brush_accumulated_mask
                                                refresh_shaded_after_classification_fast(self.app, changed_mask=acc_mask)
                                            except Exception as _se:
                                                print(f"⚠️ Brush shading refresh: {_se}")
                                        else:
                                            self._safe_render_pyvista(self.app.vtk_widget)

                                except Exception as e:
                                    print(f"⚠️ Brush GPU inject: {e}")

                                self._brush_frame_chunks = []
                                self._brush_last_render_time = now
                                self._brush_needs_render = False

                        self._last_brush_center = center
                        self._brush_stroke_positions.append(center)

                    else:
                        # ✅ FIX 2: This section now works correctly because 'center' is already projected for cut section
                        # CROSS-SECTION / CUT accumulation
                        try:
                            if (
                                getattr(self, "_brush_section_local_mask", None) is None or
                                getattr(self, "_brush_section_pts2d", None) is None or
                                getattr(self, "_brush_section_indices", None) is None
                            ):
                                pass  # Skip if buffers not initialized
                            else:
                                # ✅ NOW THIS WORKS: center is in the same coordinate space as _brush_section_pts2d
                                u, z = float(center[0]), float(center[1])
                                prev = getattr(self, "_last_brush_center_uv", None)

                                centers = []
                                if prev is None:
                                    centers = [(u, z)]
                                else:
                                    pu, pz = prev
                                    dist = float(np.hypot(u - pu, z - pz))
                                    step = max(float(radius_view) * 0.3, 1e-6)
                                    n = max(1, int(dist / step))
                                    for i in range(1, n + 1):
                                        cu = pu + (u - pu) * (i / n)
                                        cz = pz + (z - pz) * (i / n)
                                        centers.append((cu, cz))

                                pts2d = self._brush_section_pts2d

                                if brush_shape == "rectangle":
                                    for cu, cz in centers:
                                        local = (
                                            (np.abs(pts2d[:, 0] - cu) <= radius_view) &
                                            (np.abs(pts2d[:, 1] - cz) <= radius_view)
                                        )
                                        self._brush_section_local_mask |= local
                                else:
                                    rr = float(radius_view) * float(radius_view)
                                    for cu, cz in centers:
                                        du = pts2d[:, 0] - cu
                                        dz = pts2d[:, 1] - cz
                                        local = (du * du + dz * dz) <= rr
                                        self._brush_section_local_mask |= local

                                self._last_brush_center_uv = (u, z)

                        except Exception as e:
                            print(f"⚠️ Section/Cut brush accumulate failed (non-critical): {e}")

            # ✅ Polygon preview
            elif tool == "polygon":
                self._draw_polygon_preview((P2[0], P2[2]))
                if vtk_widget and (current_time - self._last_render_time) > 0.016:
                    self._safe_render(vtk_widget)
                    self._last_render_time = current_time

            # ✅ Freehand preview
            elif tool == "freehand" and self.is_drawing_freehand:
                u, v = self._get_view_coordinates(P2)

                if len(self.drawing_points) == 0:
                    self.drawing_points.append((u, v))
                else:
                    last_u, last_v = self.drawing_points[-1]
                    dist = np.sqrt((u - last_u) ** 2 + (v - last_v) ** 2)
                    threshold = 0.05 if is_cut_section else 0.1
                    if dist > threshold:
                        self.drawing_points.append((u, v))

                if is_cut_section:
                    x2, y2 = self.interactor.GetEventPosition()
                    if not hasattr(self, "drawing_points_display_cut"):
                        self.drawing_points_display_cut = []
                    if len(self.drawing_points_display_cut) == 0:
                        self.drawing_points_display_cut.append((x2, y2))
                    else:
                        last_x, last_y = self.drawing_points_display_cut[-1]
                        pixel_dist = np.sqrt((x2 - last_x) ** 2 + (y2 - last_y) ** 2)
                        if pixel_dist > 2.0:
                            self.drawing_points_display_cut.append((x2, y2))
                    self._draw_freehand_preview_cut()
                else:
                    self._draw_freehand_preview()

                if vtk_widget and (current_time - self._last_render_time) > 0.016:
                    self._safe_render(vtk_widget)
                    self._last_render_time = current_time

            # ✅ SAFE PAN: Custom implementation — no VTK C++ Render()
            self._do_safe_pan()

    def on_left_press(self, obj, evt):
        """✅ Start drawing - sets P1 for preview rendering (FIXED for above/below line snapping)"""

        if not hasattr(self, 'app') or self.app is None:
            return
        if not hasattr(self, 'interactor') or self.interactor is None:
            return
        self._stop_deferred_left_release_watch()
        self._hide_preview_overlay_for_pan()

        # ════════════════════════════════════════════════════════════════
        # ✅ CRITICAL: Cancel any pending deferred rebuild immediately
        # This prevents lag when user starts a new classification quickly
        # ════════════════════════════════════════════════════════════════
        try:
            if hasattr(self.app, '_optimized_refresh') and self.app._optimized_refresh:
                optimizer = self.app._optimized_refresh
                # STOP TIMER instantly
                if hasattr(optimizer, '_deferred_rebuild_timer'):
                    optimizer._deferred_rebuild_timer.stop()
                # We do NOT clear data, so we can resume later if needed
        except:
            pass

        is_cut_interaction = False
        vtk_widget = self._get_active_vtk_widget()

        if hasattr(self.app, 'cut_section_controller'):
            cut_vtk = getattr(self.app.cut_section_controller, 'cut_vtk', None)
            if cut_vtk and vtk_widget == cut_vtk:
                is_cut_interaction = True

        if getattr(self.app, "active_mode", None) == "cut":
            if not is_cut_interaction:
                if hasattr(self.app, 'statusBar'):
                    self.app.statusBar().showMessage(
                        "⚠️ Cut Section is active - classifying in Main View",
                        2000
                    )
            else:
                print("🔧 Interaction detected inside Cut Section — Allowing classification.")

        if self._is_main_view():
            self.app.active_classify_target = "main"
            print("🎯 MAIN VIEW classification ACTIVE - XY bounds")
        elif is_cut_interaction:
            self.app.active_classify_target = "cut"
            print("🎯 CUT SECTION classification ACTIVE")
        else:
            self.app.active_classify_target = "section"
            print("🎯 CROSS-SECTION classification ACTIVE")

        if not is_cut_interaction:
            v_idx = self._get_view_index_from_interactor()
            if v_idx is not None:
                try:
                    self.app.section_controller.active_view = v_idx
                    self.app.section_controller.current_vtk = self.app.section_vtks.get(v_idx)
                    print(f"🎯 Active cross-section view set to {v_idx}")
                except Exception:
                    pass

        tool = getattr(self.app, "active_classify_tool", None)
        self._gesture_tool = tool
        print(f"🔍 DEBUG: is_main={self._is_main_view()}, target='{getattr(self.app, 'active_classify_target', 'NONE')}', tool={tool}")

        # ❌ BLOCK Above/Below Line in MAIN VIEW ONLY
        # ==========================================================
        if tool in ("above_line", "below_line") and self._is_main_view():
            print("❌ Above/Below Line blocked in MAIN view")

            if hasattr(self.app, "statusBar"):
                self.app.statusBar().showMessage(
                    "❌ Above / Below Line tools work only in cross-section views",
                    3000
                )

            # Let camera interaction continue, but STOP classification
            try:
                self.style.OnLeftButtonDown()
            except Exception:
                pass

            return

        if tool is None:
            try:
                return self.style.OnLeftButtonDown()
            except Exception:
                return

        # ✅ IMPORTANT: clear stored preview end when starting a new above/below line
        if tool in ("above_line", "below_line"):
            self._last_line_preview_P2 = None

        self.from_classes = getattr(self.app, "from_classes", None)
        self.to_class = getattr(self.app, "to_class", None)
        print(f"🎯 SYNC LEFT_PRESS: from={self.from_classes}, to={self.to_class}")

        x, y = self.interactor.GetEventPosition()

        print(f"\n{'='*60}")
        print(f"🖱️ LEFT PRESS - Tool: {tool}")
        print(f"   Mouse position: ({x}, {y})")

        try:
            if tool in ("above_line", "below_line") and (not self._is_main_view()):
                dx, dy = self._get_display_point()
                pt = self._display_to_world_fast(dx, dy)
                print(f"   Picked NON-SNAP world point: ({pt[0]:.2f}, {pt[1]:.2f}, {pt[2]:.2f})")
            else:
                pt = self._pick_world_point(x, y)
                print(f"   Picked world point: ({pt[0]:.2f}, {pt[1]:.2f}, {pt[2]:.2f})")
        except Exception as e:
            print(f"⚠️ Pick failed on left press: {e}")
            print(f"{'='*60}\n")
            return

        P = self._get_view_coordinates(pt)

        if tool == "rectangle" and is_cut_interaction:
            self.P1_display_cut = (x, y)

        if tool == "polygon":
            self.drawing_points.append(P)
            self._draw_polygon_preview()
            self._safe_render_interactor()
            print(f"{'='*60}\n")
            return

        if tool == "freehand":
            self.is_drawing_freehand = True
            self.drawing_points = []
            if is_cut_interaction:
                self.drawing_points_display_cut = [(x, y)]
            try:
                pt2 = self._pick_world_point(x, y)
                P2 = self._get_view_coordinates(pt2)
                self.drawing_points.append(P2)
            except Exception:
                pass
            print(f"{'='*60}\n")
            return

        # self.P1 = pt
        # self.app._suppress_section_refresh = True
        # self.is_dragging = True
        # # ❌ REMOVED: self.app._suppress_section_refresh = True
        # # ✅ This flag should ONLY be set for brush tool, not for rectangle/other tools
        self.P1 = pt
        self.app._suppress_section_refresh = True
        self.is_dragging = True
        # ✅ FIX B — reset throttles so first preview frame of this
        # new classification is never skipped by the 16 ms guard.
        self._last_render_time     = 0.0
        self._last_mouse_move_time = 0.0
        # ❌ REMOVED: self.app._suppress_section_refresh = Tru

        # ✅ MAIN VIEW brush init
        if tool == "brush" and self._is_main_view():
            if self._brush_spatial_index is None:
                self._build_spatial_index_for_brush()

            import numpy as np
            self._brush_accumulated_mask = np.zeros(len(self.app.data["xyz"]), dtype=bool)
            self._brush_old_classes = {}
            self._brush_frame_chunks = []
            self._brush_stroke_positions = []
            self._last_brush_center = None
            self._brush_render_counter = 0
            self._brush_last_render_time = 0.0
            self._brush_needs_render = False
            self._brush_main_visible_classes = self._get_visible_classes_for_slot(0)
            self._brush_main_visible_classes_arr = None
            if self._brush_main_visible_classes not in (None, []):
                self._brush_main_visible_classes_arr = np.asarray(
                    self._brush_main_visible_classes,
                    dtype=self.app.data["classification"].dtype,
                )
            elif self._brush_main_visible_classes == [] and hasattr(self.app, "statusBar"):
                self.app.statusBar().showMessage(
                    "No visible classes selected in Display Mode.",
                    2000,
                )
            # ✅ Only set suppress flag for BRUSH tool
            self.app._suppress_section_refresh = True
                

        if tool == "brush" and (not self._is_main_view()):
            # ✅ Only set suppress flag for BRUSH tool
            self.app._suppress_section_refresh = True
            
            try:
                import numpy as np
    
                self._brush_section_indices = None
                self._brush_section_pts2d = None
                self._brush_section_local_mask = None
                self._last_brush_center_uv = None

                if is_cut_interaction:
                    # ✅ CRITICAL FIX: Cut section initialization with PROJECTION
                    ctrl = getattr(self.app, "cut_section_controller", None)
                    if ctrl is not None:
                        cut_pts = getattr(ctrl, "cut_points", None)
                        cut_idx = getattr(ctrl, "_cut_index_map", None)
                        if cut_pts is not None and cut_idx is not None:
                            from ..classification_tools import _project_to_cut_view
                        
                            idxs = np.asarray(cut_idx, dtype=np.int64)
                        
                            # ✅ KEY FIX: Project cut points to cut view 2D space
                            pts2d = _project_to_cut_view(self.app, cut_pts)
                        
                            self._brush_section_indices = idxs
                            self._brush_section_pts2d = pts2d  # Now in cut view coordinates!
                            self._brush_section_local_mask = np.zeros(len(idxs), dtype=bool)
                        
                            print(f"✅ Cut brush init: {len(idxs)} points")
                            print(f"   2D bounds: u=[{pts2d[:,0].min():.1f},{pts2d[:,0].max():.1f}], z=[{pts2d[:,1].min():.1f},{pts2d[:,1].max():.1f}]")
                else:
                    # Cross-section - ✅ INCLUDE BUFFER POINTS
                    v_idx = self._get_view_index_from_interactor()
                    if v_idx is None:
                        v_idx = getattr(self.app.section_controller, "active_view", 0)
    
                    # ✅ FIX 1: Get transformed points (includes core + buffer)
                    pts3 = getattr(self.app, f"section_{v_idx}_points_transformed", None)
                    
                    # ✅ FIX 2: ALWAYS use combined_mask (not section_indices)
                    # This ensures we get BOTH core AND buffer indices
                    combined_mask = getattr(self.app, f"section_{v_idx}_combined_mask", None)
                    
                    if combined_mask is not None:
                        idxs = np.where(combined_mask)[0]
                        print(f"✅ Brush init: Using COMBINED mask (core + buffer)")
                        print(f"   Total indices: {len(idxs):,}")
                    else:
                        # Fallback: try to build from core + buffer masks
                        core_mask = getattr(self.app, f"section_{v_idx}_core_mask", None)
                        buffer_mask = getattr(self.app, f"section_{v_idx}_buffer_mask", None)
                        
                        if core_mask is not None and buffer_mask is not None:
                            combined_mask = core_mask | buffer_mask
                            idxs = np.where(combined_mask)[0]
                            print(f"✅ Brush init: Built combined mask from core + buffer")
                            print(f"   Core: {core_mask.sum():,}, Buffer: {(buffer_mask & ~core_mask).sum():,}")
                        elif core_mask is not None:
                            idxs = np.where(core_mask)[0]
                            print(f"⚠️ Brush init: Using CORE ONLY (no buffer available)")
                        else:
                            idxs = None
                            print(f"❌ Brush init: No mask available")
    
                    if pts3 is not None and idxs is not None:
                        view_mode = getattr(self.app, "cross_view_mode", "side")
                        if view_mode == "front":
                            pts2d = pts3[:, [1, 2]]
                        else:
                            pts2d = pts3[:, [0, 2]]
    
                        self._brush_section_indices = np.asarray(idxs, dtype=np.int64)
                        self._brush_section_pts2d = np.asarray(pts2d, dtype=np.float64)
                        self._brush_section_local_mask = np.zeros(len(self._brush_section_indices), dtype=bool)
                        
                        # ✅ Debug output
                        print(f"   Points 2D shape: {pts2d.shape}")
                        print(f"   2D bounds: u=[{pts2d[:,0].min():.1f}, {pts2d[:,0].max():.1f}], z=[{pts2d[:,1].min():.1f}, {pts2d[:,1].max():.1f}]")
    
            except Exception as e:
                print(f"⚠️ Section brush init skipped (safe): {e}")
                    
        print(f"✅ is_dragging = True")
        print(f"{'='*60}\n")
    
    def on_left_release(self, obj, evt):
        """
        Execute classification on mouse release
        ✅ Includes MAIN-VIEW path + fixed cross/cut section path
        ✅ FIXED: Rectangle/Circle use EXACT same P2 as preview (no coordinate mismatch)
        
        ✅ SENIOR REFACTOR:
        - Brush tool accumulates strokes in memory and flushes ONCE on release.
        - Unified coordinate projection for Cut Section vs Cross-Section views.
        - Debounced and state-safe cleanup.
        """
        # 1. Safety checks
        if not hasattr(self, 'app') or self.app is None:
            return

        if not hasattr(self, 'style') or self.style is None:
            try:
                if hasattr(self, 'style'):
                    self.style.OnLeftButtonUp()
            except:
                pass
            return

        # 2. Debounce (100ms)
        import time
        current_time = time.time()
        if hasattr(self, '_last_release_time'):
            if current_time - self._last_release_time < 0.1:
                return
        self._last_release_time = current_time

        from ..classification_tools import (
            classify_above_line, classify_below_line,
            classify_rectangle, classify_circle,
            classify_freehand, classify_brush, classify_point,
            _get_cut_section_or_default,
            _apply_classification
        )

        try:
            tool = getattr(self.app, "active_classify_tool", None)
            was_dragging = self.is_dragging
            to_class = getattr(self.app, "to_class", None)
            from_classes = getattr(self.app, "from_classes", None)

            # --- BRANCH A: MAIN VIEW BRUSH STROKE ---
            if tool == "brush" and self._is_main_view() and was_dragging:
                undo_mask = None  # Will be set if points were classified
                if hasattr(self, '_brush_accumulated_mask') and np.any(self._brush_accumulated_mask):
                    start = time.time()

                    # ✅ MICROSTATION: Classification was already applied during drag.
                    # Only push the undo entry here (no re-classification needed).
                    mask = self._brush_accumulated_mask
                    old_classes_dict = getattr(self, '_brush_old_classes', {})

                    if old_classes_dict and to_class is not None:
                        indices = np.array(sorted(old_classes_dict.keys()), dtype=np.int64)
                        old_cls = np.array([old_classes_dict[int(i)] for i in indices],
                                           dtype=self.app.data["classification"].dtype)
                        new_cls = np.full(len(indices), to_class, dtype=old_cls.dtype)

                        undo_mask = np.zeros(len(self.app.data["xyz"]), dtype=bool)
                        undo_mask[indices] = True

                        self.app.undo_stack.append({
                            "mask": undo_mask,
                            "old_classes": old_cls,
                            "new_classes": new_cls,
                        })
                        self.app.redo_stack.clear()
                        self.app._last_changed_mask = undo_mask

                        # Point stats
                        try:
                            from gui.point_count_widget import refresh_point_statistics
                            refresh_point_statistics(self.app)
                        except Exception:
                            pass

                        n_pts = len(indices)
                        if hasattr(self.app, 'statusBar'):
                            self.app.statusBar().showMessage(
                                f"✅ {n_pts:,} points → class {to_class}", 3000)

                    elapsed = (time.time() - start) * 1000
                    print(f"✅ Main Brush stroke complete: {int(mask.sum()):,} points in {elapsed:.0f}ms")

                # Clean up brush state
                self._brush_accumulated_mask = None
                self._brush_old_classes = {}
                self._brush_frame_chunks = []
                self._brush_stroke_positions = []
                self._last_brush_center = None
                self._brush_needs_render = False
                self._brush_main_visible_classes = None
                self._brush_main_visible_classes_arr = None
                self.app._suppress_section_refresh = False
                # In shaded_class mode keep OptimizedRefresh alive — shading mesh needs its own rebuild
                if getattr(self.app, "display_mode", "class") != "shaded_class":
                    self.app._gpu_sync_done = True
                elif _shading_mesh_exists(self.app):
                    try:
                        from gui.shading_display import refresh_shaded_after_classification_fast
                        refresh_shaded_after_classification_fast(
                            self.app,
                            changed_mask=getattr(self, '_brush_accumulated_mask', None)
                        )
                    except Exception as _se:
                        print(f"⚠️ Brush release shading refresh: {_se}")
                else:
                    # No mesh yet — treat like class mode so GPU sync completes
                    self.app._gpu_sync_done = True
                    print("⏭️ Brush release: skipping shading refresh — no mesh built yet")

                 # ✅ Final: sync sections (deferred from drag) + render all
                try:
                    # Update cross-sections with the full undo_mask
                    if hasattr(self.app, 'section_vtks') and undo_mask is not None:
                        from gui.unified_actor_manager import fast_cross_section_update
                        for vi in self.app.section_vtks:
                            try:
                                fast_cross_section_update(self.app, vi, undo_mask)
                            except Exception:
                                pass

                    self._safe_render_pyvista(self.app.vtk_widget)
                    if hasattr(self.app, 'section_vtks'):
                        for sw in self.app.section_vtks.values():
                            if sw:
                                self._safe_render_pyvista(sw)
                except Exception:
                    pass

                # ═══════════════════════════════════════════════════════════
                # ✅ FIX: Refresh cut section view after main view brush
                # 
                # Branch A returns early (before _refresh_all_views_after_classification),
                # so cross-sections get updated via fast_cross_section_update() above,
                # but the cut section was NEVER refreshed. This fixes that gap.
                # ═══════════════════════════════════════════════════════════
                try:
                    if hasattr(self.app, 'cut_section_controller'):
                        ctrl = self.app.cut_section_controller
                        if (ctrl.is_cut_view_active 
                                and ctrl.cut_points is not None 
                                and ctrl._cut_index_map is not None
                                and ctrl.cut_vtk is not None):
                            ctrl._refresh_cut_colors_fast()
                            print(f"   ⚡ Cut section refreshed after main view brush")
                except Exception as e:
                    print(f"   ⚠️ Cut section refresh failed: {e}")

                self.is_dragging = False
                try: self.style.OnLeftButtonUp()
                except: pass
                return

            # 3. Basic Validation
            if (not was_dragging) and (tool not in ("freehand", "polygon")):
                print("⚠️ Release without drag - ignoring")
                try: self.style.OnLeftButtonUp()
                except: pass
                return

            if self.P1 is None and tool not in ("freehand", "polygon"):
                print("⚠️ P1 is None, cannot execute classification")
                return

            x, y = self.interactor.GetEventPosition()
            
            # 4. Resolve P2 (Endpoint) - FIXED TO MATCH PREVIEW
            try:
                if tool in ("above_line", "below_line") and (not self._is_main_view()):
                    # Use stored preview P2 for line tools
                    P2 = getattr(self, "_last_line_preview_P2", None)
                    if P2 is None:
                        dx, dy = self._get_display_point()
                        P2 = self._display_to_world_fast(dx, dy)
                elif tool == "rectangle" and (not self._is_main_view()):
                    # ✅ NEW: Use stored preview P2 for rectangle tool
                    P2 = getattr(self, "_last_rectangle_preview_P2", None)
                    if P2 is None:
                        dx, dy = self._get_display_point()
                        P2 = self._display_to_world_fast(dx, dy)
                    print(f"🔍 Rectangle using preview P2: {P2}")
                elif tool == "circle" and (not self._is_main_view()):
                    # ✅ NEW: Use stored preview P2 for circle tool
                    P2 = getattr(self, "_last_circle_preview_P2", None)
                    if P2 is None:
                        dx, dy = self._get_display_point()
                        P2 = self._display_to_world_fast(dx, dy)
                else:
                    # Main view or point tool can use snapping
                    P2 = self._pick_world_point(x, y)
            except Exception as e:
                print(f"⚠️ Pick failed on release: {e}")
                return

            # 5. Detect View Context
            vtk_widget = self._get_active_vtk_widget()
            is_cut_section = bool(
                hasattr(self.app, 'cut_section_controller') and
                vtk_widget == getattr(self.app.cut_section_controller, 'cut_vtk', None)
            )

            # --- BRANCH B: SECTION / CUT VIEW BRUSH STROKE ---
            if tool == "brush" and (not self._is_main_view()) and was_dragging:
                try:
                    idxs = getattr(self, "_brush_section_indices", None)
                    pts2d = getattr(self, "_brush_section_pts2d", None)
                    local_mask = getattr(self, "_brush_section_local_mask", None)

                    if idxs is not None and pts2d is not None and local_mask is not None:
                        idxs_arr = np.asarray(idxs)
                        if idxs_arr.dtype == bool:
                            idxs_arr = np.where(idxs_arr)[0]
                        idxs_arr = idxs_arr.astype(np.int64, copy=False)

                        # Final stamp at release position to close the gap
                        radius_px = float(getattr(self.app, "brush_preview_px", 20.0))
                        radius_view = float(self._pixel_radius_to_view_radius(vtk_widget, P2, radius_px))
                        u2, z2 = self._get_view_coordinates(P2)
                        
                        du, dz = pts2d[:, 0] - float(u2), pts2d[:, 1] - float(z2)
                        if getattr(self.app, "brush_shape", "circle") == "rectangle":
                            local_mask |= (np.abs(du) <= radius_view) & (np.abs(dz) <= radius_view)
                        else:
                            local_mask |= (du*du + dz*dz) <= (radius_view * radius_view)

                        # if np.any(local_mask):
                        #     update_mask = np.zeros(len(self.app.data["xyz"]), dtype=bool)
                        #     update_mask[idxs_arr[local_mask]] = True
                        #     _apply_classification(self.app, update_mask, from_classes, to_class)
                        #                             #     force_vtk_pipeline_update(self.app)

                        # self._refresh_all_views_after_classification(to_class)
                        # return

                        if np.any(local_mask):
                            update_mask = np.zeros(len(self.app.data["xyz"]), dtype=bool)
                            update_mask[idxs_arr[local_mask]] = True
 
                            # ✅ FIXED: Removed core-only clamp to allow buffer classification
                            # Brush initialization uses combined_mask (core + buffer)
                            # No need to filter here - buffer points should be classified!
                            
                            print(f"   📊 Brush classification: {np.sum(update_mask):,} points")
                            if hasattr(self.app, 'section_controller'):
                                v_idx = self._get_view_index_from_interactor()
                                if v_idx is not None:
                                    core_mask = getattr(self.app, f"section_{v_idx}_core_mask", None)
                                    if core_mask is not None:
                                        core_pts = (update_mask & core_mask).sum()
                                        buffer_pts = (update_mask & ~core_mask).sum()
                                        print(f"      Core: {core_pts:,}, Buffer: {buffer_pts:,}")
 
                            _apply_classification(self.app, update_mask, from_classes, to_class)
                            
 
                        self._refresh_all_views_after_classification(to_class)
                        return
                    
                except Exception as e:
                    print(f"⚠️ Section brush failed (fallback): {e}")

            # --- BRANCH C: MAIN VIEW (NON-BRUSH) ---
            if self._is_main_view():
                if tool == "rectangle":
                    u1, v1 = self._get_view_coordinates(self.P1)
                    u2, v2 = self._get_view_coordinates(P2)
                    self._classify_rectangle_main((u1, v1), (u2, v2), to_class)
                elif tool == "circle":
                    u1, v1 = self._get_view_coordinates(self.P1)
                    u2, v2 = self._get_view_coordinates(P2)
                    center = ((u1 + u2) / 2.0, (v1 + v2) / 2.0)
                    radius = float(np.hypot(u2 - u1, v2 - v1)) / 2.0
                    self._classify_circle_main(center, radius, to_class)
                elif tool == "freehand" and len(self.drawing_points) > 2:
                    self._classify_polygon_main(self.drawing_points, to_class)
                elif tool == "point":
                    u2, v2 = self._get_view_coordinates(P2)
                    self._classify_point_main((u2, v2), getattr(self.app, "point_radius", 0.5), to_class)
                return

            # --- BRANCH D: SECTION / CUT VIEW (NON-BRUSH) ---
            # Resolve data context
            # if is_cut_section:
            #     mask = getattr(self.app.section_controller, "last_mask", None)
            #     section_points = getattr(self.app, "section_points", None)
            # else:
            #     v_idx = self._get_view_index_from_interactor()
            #     mask, section_points = self._get_section_context_for_view(v_idx) if v_idx is not None else (None, None)

            # section_indices, section_points = _get_cut_section_or_default(self.app, mask, section_points)
            # if section_indices is None or section_points is None:
            #     return

            if is_cut_section:
                # Cut section uses its own stored mask/points
                mask = getattr(self.app.section_controller, "last_mask", None)
                section_points = getattr(self.app, "section_points", None)
                print(f"   🔪 Cut section mode: mask={mask is not None}, points={section_points is not None}")
            else:
                # Cross-section view - use integrated buffer logic
                v_idx = self._get_view_index_from_interactor()
                print(f"   📊 Cross-section view index: {v_idx}")
                
                # ═══════════════════════════════════════════════════════════
                # KEY FIX: Use COMBINED mask (core + buffer) instead of just core
                # ═══════════════════════════════════════════════════════════
                if v_idx is not None:
                    # Try direct access to combined mask first (fastest)
                    combined_mask = getattr(self.app, f"section_{v_idx}_combined_mask", None)
                    section_points_transformed = getattr(self.app, f"section_{v_idx}_points_transformed", None)
                    
                    if combined_mask is not None and section_points_transformed is not None:
                        # Best case: pre-computed combined data available
                        mask = combined_mask
                        section_points = section_points_transformed
                        num_points = mask.sum() if hasattr(mask, 'sum') else len([x for x in mask if x])
                        print(f"   ✅ Using COMBINED mask for classification (includes buffer points)")
                        print(f"      Total points: {num_points:,} (core + buffer)")
                        print(f"      Using transformed coordinates for accurate classification")
                    else:
                        # Fallback: use helper method to build combined mask
                        print(f"   🔄 Combined mask not available, using helper method...")
                        mask, section_points = self._get_section_context_for_view(v_idx)
                        
                        if mask is not None:
                            num_points = mask.sum() if hasattr(mask, 'sum') else len([x for x in mask if x])
                            print(f"   ✅ Helper method returned: {num_points:,} points")
                        else:
                            print(f"   ❌ Helper method failed to get mask/points")
                else:
                    print(f"   ❌ Could not determine view index")
                    mask, section_points = None, None

            # Validate we have the data we need
            section_indices, section_points = _get_cut_section_or_default(self.app, mask, section_points)
            if section_indices is None or section_points is None:
                print(f"   ❌ Classification aborted: missing section data")
                print(f"{'='*60}\n")
                return

            # Special case for Freehand completion
            if tool == "freehand" and self.is_drawing_freehand:
                if len(self.drawing_points) >= 2:
                    classify_freehand(self.app, self.drawing_points, from_classes, to_class, mask, section_points, None)
                    self._refresh_all_views_after_classification(to_class)
                return

            # Geometric Tools (Line, Rect, Circle)
            if is_cut_section:
                from ..classification_tools import _project_to_cut_view
                (u1, z1), (u2, z2) = _project_to_cut_view(self.app, np.vstack([self.P1, P2]))
            else:
                u1, z1 = self._get_view_coordinates(self.P1)
                u2, z2 = self._get_view_coordinates(P2)

            # ✅ DEBUG: Print rectangle bounds
            if tool == "rectangle":
                print(f"🔍 RECTANGLE CLASSIFICATION BOUNDS:")
                print(f"   P1 world: {self.P1}")
                print(f"   P2 world: {P2}")
                print(f"   u_range: ({min(u1, u2):.2f}, {max(u1, u2):.2f})")
                print(f"   z_range: ({min(z1, z2):.2f}, {max(z1, z2):.2f})")

            if tool == "above_line":
                classify_above_line(self.app, [(u1, z1), (u2, z2)], from_classes, to_class, mask, section_points, None)
            elif tool == "below_line":
                classify_below_line(self.app, [(u1, z1), (u2, z2)], from_classes, to_class, mask, section_points, None)
            elif tool == "rectangle":
                u_range = sorted([u1, u2])
                z_range = sorted([z1, z2])
                classify_rectangle(self.app, (u_range[0], u_range[1], z_range[0], z_range[1]), from_classes, to_class, mask, section_points, "disable_filter")
            elif tool == "circle":
                center = ((u1 + u2) / 2, (z1 + z2) / 2)
                radius = float(np.hypot(u2 - u1, z2 - z1)) / 2.0
                classify_circle(self.app, center, radius, from_classes, to_class, mask, section_points, None)
            elif tool == "point":
                classify_point(self.app, (u2, z2), getattr(self.app, "point_radius", 0.5), from_classes, to_class, mask, section_points, None)

            self._refresh_all_views_after_classification(to_class)

        except Exception as e:
            print(f"⚠️ Classification failed: {e}")
            import traceback
            traceback.print_exc()

        finally:
            self._stop_deferred_left_release_watch()
            self._gesture_tool = None
            # 1. CLEANUP STATE
            self.is_dragging = False
            self.P1 = None
            self.drawing_points = []
            self.is_drawing_freehand = False
            self._last_brush_center = None
            self._is_panning = False
            self._hide_preview_overlay_for_pan()
            self._last_pan_pos = (0, 0) 
            # Clear previews
            self._last_rectangle_preview_P2 = None
            self._last_circle_preview_P2 = None
            self._last_line_preview_P2 = None

            # Clean stroke buffers
            for attr in ("_brush_accumulated_mask", "_brush_stroke_positions", 
                        "_brush_main_visible_classes", "_brush_main_visible_classes_arr",
                        "_brush_section_indices", "_brush_section_pts2d", 
                        "_brush_section_local_mask", "_last_brush_center_uv"):
                if hasattr(self, attr):
                    try: delattr(self, attr)
                    except: setattr(self, attr, None)

            self._clear_all_previews()
            
            # 2. FORCE RENDER (Closes the preview visual instantly)
            try:
                vtk_widget = self._get_active_vtk_widget()
                if vtk_widget:
                    self._safe_render(vtk_widget)
            except:
                pass
            
            # 3. 🚀 CRITICAL: Force UI update to allow next mouse move to register IMMEDIATELY
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
            
            # 4. START DEFERRED TIMER (Non-blocking)
            try:
                if hasattr(self.app, '_optimized_refresh') and self.app._optimized_refresh:
                    optimizer = self.app._optimized_refresh
                    if hasattr(optimizer, '_deferred_rebuild_data') and optimizer._deferred_rebuild_data:
                        if hasattr(optimizer, '_deferred_rebuild_timer'):
                            optimizer._deferred_rebuild_timer.stop()
                            # 500ms delay ensures user has time to move mouse before heavy rebuild starts
                            optimizer._deferred_rebuild_timer.start(500) 
            except Exception as e:
                pass
            
            try: self.style.OnLeftButtonUp()
            except: pass
            
    def _ensure_target_class_visible(self, to_class):
        """
        ✅ FINAL SENIOR FIX
        Auto-enable ONLY if user has NO filter active.
        Never mutate filtered views.
        """
        try:
            print(f"\n{'='*60}")
            print(f"👁️ Checking target class {to_class} visibility")

            dialog = getattr(self.app, 'display_mode_dialog', None)
            if not dialog:
                print("   ⚠️ No display_mode_dialog found")
                return

            # ✅ MAIN vs SECTION
            active_view = getattr(self.app.section_controller, 'active_view', None)
            target_slot = 0 if active_view is None else active_view + 1

            print(f"   Active view: {active_view}, slot: {target_slot}")

            dialog.slot_shows.setdefault(target_slot, {})
            dialog.view_palettes.setdefault(target_slot, {})

            view_palette = dialog.view_palettes.get(target_slot, {})
            if not view_palette:
                print("   ℹ️ No palette - nothing to auto-enable")
                return

            visible_count = sum(1 for v in view_palette.values() if v.get("show", False))
            total_count = len(view_palette)

            print(f"   📊 Visible: {visible_count}/{total_count} classes")

            # 🔒 USER FILTER → NEVER AUTO-ENABLE
            if 0 < visible_count < total_count:
                print("   🔒 User has filter - NOT auto-enabling")
                return

            if view_palette.get(to_class, {}).get("show", False):
                print("   ✓ Already visible")
                return

            # Enable only when safe
            dialog.slot_shows[target_slot][int(to_class)] = True
            dialog.view_palettes[target_slot][int(to_class)]["show"] = True

            print(f"   ✅ Auto-enabled class {to_class} (no user filter)")

        except Exception as e:
            print(f"⚠️ _ensure_target_class_visible failed: {e}")
            import traceback
            traceback.print_exc()
            
    def _refresh_all_views_after_classification(self, to_class):
        changed_mask = getattr(self.app, "_last_changed_mask", None)
        if changed_mask is None or not isinstance(changed_mask, np.ndarray) or not np.any(changed_mask):
            print("⏭️ Skipping post-classification refresh - no changed points in current operation")
            return

        try:
            # ✅ CRITICAL FIX: ALWAYS use optimizer for multi-view scenarios
            # The optimizer is specifically designed to handle this efficiently
            from gui.optimization_config import ENABLE_OPTIMIZED_REFRESH
            if ENABLE_OPTIMIZED_REFRESH:
                from gui.optimized_refresh import get_optimizer
                optimizer = get_optimizer(self.app)

                from_classes = getattr(self.app, '_last_from_classes', None)
                if from_classes is None:
                    from_classes = getattr(self.app, 'from_classes', None)

                active_view = None
                if hasattr(self.app, 'section_controller'):
                    active_view = getattr(self.app.section_controller, 'active_view', None)

                optimizer.refresh_after_classification(
                    to_class=to_class,
                    from_classes=from_classes,
                    active_view=active_view,
                    fallback_func=self._refresh_all_views_original
                )
                return
        except Exception as e:
            print(f"⚠️ Optimizer unavailable: {e}")

        self._refresh_all_views_original(to_class)


    def _refresh_all_views_original(self, to_class):
        """
        ✅ ORIGINAL CODE - Renamed but unchanged.
        
        This is your existing _refresh_all_views_after_classification method.
        """
        # ═══════════════════════════════════════════════════════════════════════
        # YOUR EXISTING CODE GOES HERE - COMPLETELY UNCHANGED
        # ═══════════════════════════════════════════════════════════════════════
        
        print(f"\n{'='*60}")
        print(f"🔄 REFRESHING VIEWS AFTER CLASSIFICATION")
        print(f"   Target class: {to_class}")
        print(f"   Display mode: {self.app.display_mode}")
        print(f"{'='*60}")

        num_changed = 0
        class_text = "no changes"

        try:
            import numpy as np
            app = self.app

            # ✅ 1. Sync weights BEFORE any refresh
            print(f"\n🔧 SYNCING WEIGHTS FROM DISPLAY MODE...")
            self._sync_main_view_palette_weights()

            # STEP 1: Info about what was classified
            changed_mask = getattr(app, "_last_changed_mask", None)
            if to_class is not None:
                num_changed = int(changed_mask.sum()) if isinstance(changed_mask, np.ndarray) else "?"
                print(f"\nℹ️ Classified {num_changed} points to class {to_class}")

                already_visible = False
                if hasattr(app, 'display_mode_dialog') and app.display_mode_dialog:
                    dialog = app.display_mode_dialog
                    if hasattr(dialog, 'view_palettes') and 0 in dialog.view_palettes:
                        slot0 = dialog.view_palettes[0]
                        if to_class in slot0:
                            already_visible = slot0[to_class].get("show", False)

                if already_visible:
                    print(f"   ✅ Class {to_class} is already visible")
                else:
                    print(f"   ⚠️ Class {to_class} is HIDDEN")

            # STEP 2: Refresh ALL cross-section views
            if hasattr(app, 'section_vtks') and app.section_vtks:
                num_views = len(app.section_vtks)
                print(f"\n🔄 Refreshing ALL {num_views} cross-section views...")

                for view_idx in sorted(app.section_vtks.keys()):
                    try:
                        self._refresh_single_view(view_idx)
                    except Exception as e:
                        print(f"      ⚠️ View {view_idx + 1} refresh failed: {e}")

            # STEP 3: MAIN VIEW REFRESH
            print(f"\n🔄 Refreshing Main View...")

            vtk_widget = getattr(app, 'vtk_widget', None)
            saved_camera = None
            if vtk_widget is not None:
                try:
                    if hasattr(vtk_widget, 'camera_position') and vtk_widget.camera_position is not None:
                        saved_camera = vtk_widget.camera_position
                except Exception as e:
                    print(f"   ⚠️ Camera save failed: {e}")

            display_mode = getattr(app, "display_mode", "class")

            if display_mode == "class":
                # ✅ UNIFIED ACTOR: write directly into shared GPU buffer — no rebuild
                from gui.unified_actor_manager import fast_classify_update, is_unified_actor_ready
                if is_unified_actor_ready(app):
                    changed_mask = getattr(app, '_last_changed_mask', None)
                    palette      = getattr(app, 'class_palette', {})
                    border_pct   = float(getattr(app, 'point_border_percent', 0) or 0.0)
                    fast_classify_update(app, changed_mask=changed_mask,
                                         to_class=to_class, palette=palette,
                                         border_percent=border_pct)
                    try:
                        self._safe_render_pyvista(vtk_widget)
                    except Exception:
                        pass
                    print(f"   ✅ Unified actor GPU poke complete")
                else:
                    # Unified actor not built yet — trigger a one-time build
                    print(f"   ⚠️ Unified actor not ready — triggering build")
                    from gui.class_display import update_class_mode
                    update_class_mode(app, force_refresh=True)

            elif display_mode == "shaded_class":
                print(f"   🌗 Shaded mode – forcing rebuild...")
                azimuth = getattr(app, "last_shade_azimuth", 45.0)
                angle = getattr(app, "last_shade_angle", 45.0)
                ambient = getattr(app, "shade_ambient", 0.2)
                from gui.shading_display import update_shaded_class
                update_shaded_class(app, azimuth, angle, ambient)

            else:
                print(f"   📊 Mode '{display_mode}' – standard refresh...")
                from gui.pointcloud_display import update_pointcloud
                update_pointcloud(app, display_mode)

            if saved_camera is not None and vtk_widget is not None:
                try:
                    vtk_widget.camera_position = saved_camera
                    self._safe_render_pyvista(vtk_widget)
                except Exception as e:
                    print(f"   ⚠️ Camera restore failed: {e}")

            # # STEP 4: CUT SECTION
            # if hasattr(app, "cut_section_controller") and app.cut_section_controller is not None:
            #     try:
            #         cut_ctrl = app.cut_section_controller
            #         if hasattr(cut_ctrl, 'onclassificationchanged'):
            #             cut_ctrl.onclassificationchanged()
            #         print("   ✅ Cut Section refreshed")
            #     except Exception:
            #         pass
            # STEP 4: CUT SECTION
            if (hasattr(app, "cut_section_controller") and app.cut_section_controller is not None
                    and not getattr(app, "_optimized_refresh_active", False)):
                try:
                    cut_ctrl = app.cut_section_controller
                    if hasattr(cut_ctrl, 'onclassificationchanged'):
                        cut_ctrl.onclassificationchanged()
                    print("   ✅ Cut Section refreshed")
                except Exception:
                    pass  ###

            # STEP 5: POINT STATISTICS
            try:
                from gui.point_count_widget import refresh_point_statistics
                refresh_point_statistics(app)
            except Exception:
                pass

            # STEP 6: Status bar
            def _get_class_name(code):
                try:
                    palette = getattr(app, 'class_palette', {})
                    if code in palette:
                        return palette[code].get("description", f"Class {code}")
                except: pass
                return f"Class {code}"

            to_name = _get_class_name(to_class)
            app.statusBar().showMessage(
            # REPLACE with this safe version:
            f"✅ {num_changed:,} points classified to {to_name}" if isinstance(num_changed, (int, float)) else f"✅ {num_changed} points classified to {to_name}",
                3000
            )

            print(f"\n{'='*60}")
            print(f"✅ REFRESH COMPLETE")
            print(f"{'='*60}\n")

        except Exception as e:
            print(f"\n⚠️ MULTI-VIEW REFRESH ERROR: {e}")
            import traceback
            traceback.print_exc()

    def _refresh_main_view_with_filter(self, to_class):
        """
        ✅ UNIFIED ACTOR: Apply visibility filter via sync_palette_to_gpu (slot 0).
        Never calls plotter.clear() — that would destroy the unified actor.
        """
        print(f"\n{'='*60}")
        print(f"🔄 FILTERED MAIN VIEW REFRESH (UNIFIED GPU PATH)")
        print(f"{'='*60}")

        try:
            app = self.app

            if app.display_mode != "class":
                print("   ⏭️ Not in class mode")
                return

            visible_classes = self._get_visible_classes_for_slot(0)
            if visible_classes is None:
                print("   ⏭️ No filter active")
                return

            print(f"   👁️ Filter: showing {len(visible_classes)} classes: {visible_classes}")

            from gui.unified_actor_manager import sync_palette_to_gpu, is_unified_actor_ready
            if not is_unified_actor_ready(app):
                print("   ⚠️ Unified actor not ready — skipping filter refresh")
                return

            # Build a palette copy with show=False for hidden classes, then push to GPU
            palette = dict(getattr(app, 'class_palette', {}))
            visible_set = set(visible_classes)
            filtered_palette = {}
            for code, info in palette.items():
                entry = dict(info)
                entry['show'] = (code in visible_set)
                filtered_palette[code] = entry

            border_pct = float(getattr(app, 'point_border_percent', 0) or 0.0)
            sync_palette_to_gpu(app, 0, filtered_palette, border_pct, render=True)
            print(f"   ✅ Unified filter refresh complete")

        except Exception as e:
            print(f"   ❌ Filtered refresh FAILED: {e}")
            import traceback
            traceback.print_exc()

        print(f"{'='*60}\n")

    def _refresh_single_view(self, view_index, changed_mask=None):
        """
        Refresh a single cross-section view:
        ✅ ZERO BLINK: Routes directly to unified_actor_manager.fast_cross_section_update
        """
        import time
        from gui.unified_actor_manager import fast_cross_section_update
        
        t0 = time.perf_counter()
        slot = view_index + 1
        
        # Get palette for this specific view (slot 1-4)
        view_palette = None
        if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
            dialog = self.app.display_mode_dialog
            if hasattr(dialog, 'view_palettes') and slot in dialog.view_palettes:
                view_palette = dialog.view_palettes[slot]
                
        if not view_palette and hasattr(self.app, 'class_palette'):
            view_palette = self.app.class_palette
            
        fast_cross_section_update(self.app, view_index, changed_mask, palette=view_palette)
        
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"      ⚡ View {view_index + 1} unified update: {elapsed:.1f} ms")

    def refresh_main_view_partial(self):
        """
        SMART PARTIAL REFRESH: Update ONLY the cross-sectioned area in Main View.
        - Reads changed points from _last_changed_mask
        - Updates actors for BOTH old and new classes
        - Preserves independent main view display settings
        """
        print("\n" + "="*60)
        print("🔄 PARTIAL MAIN VIEW REFRESH")
        print("="*60)
        
        try:
            if self.app.display_mode != "class":
                print("⏭️  Not in class mode - skipping")
                print("="*60 + "\n")
                return
            
            if not hasattr(self.app, '_last_changed_mask') or self.app._last_changed_mask is None:
                print("⏭️  No changed points mask")
                print("="*60 + "\n")
                return
            
            changed_mask = self.app._last_changed_mask
            num_changed = np.sum(changed_mask)
            
            if num_changed == 0:
                print("⏭️  No points changed")
                print("="*60 + "\n")
                return
            
            print(f"   📊 Changed points: {num_changed:,}")

            palette = getattr(self.app, "class_palette", {})
            if not palette:
                print("⚠️  No palette - cannot refresh")
                print("="*60 + "\n")
                return

            # ✅ UNIFIED ACTOR: write changed colours directly into _naksha_rgb_ptr.
            # Never remove/re-add class_ actors — that path is for per-class mode only.
            from gui.unified_actor_manager import fast_classify_update, is_unified_actor_ready

            classes    = self.app.data["classification"]
            changed_indices  = np.where(changed_mask)[0]
            changed_classes  = classes[changed_indices]

            print(f"   📍 Changed points by class:")
            for cls in np.unique(changed_classes):
                count = np.sum(changed_classes == cls)
                print(f"      Class {cls}: {count:,} points")

            if is_unified_actor_ready(self.app):
                border_pct = float(getattr(self.app, 'point_border_percent', 0) or 0.0)
                to_class   = getattr(self.app, '_last_to_class', None)
                fast_classify_update(self.app,
                                     changed_mask=changed_mask,
                                     to_class=to_class,
                                     palette=palette,
                                     border_percent=border_pct)
                try:
                    self._safe_render_pyvista(self.app.vtk_widget)
                except Exception:
                    pass
                print(f"   ✅ Unified partial refresh complete")
            else:
                print(f"   ⚠️ Unified actor not ready — skipping partial refresh")

            print("="*60 + "\n")
            
        except Exception as e:
            print(f"❌ Partial main view refresh failed: {e}")
            import traceback
            traceback.print_exc()
            print("="*60 + "\n")

    def _get_main_view_palette(self):
        """
        Get the Main View's color palette (Slot 0 in Display Mode).
        
        Returns:
            dict: Color palette for main view, or None if not available
        """
        # Try Display Mode dialog first
        if hasattr(self.app, 'display_mode_dialog'):
            dialog = self.app.display_mode_dialog
            
            if hasattr(dialog, 'view_palettes') and 0 in dialog.view_palettes:
                return dialog.view_palettes[0]
        
        # Try display_dialog attribute
        if hasattr(self.app, 'display_dialog'):
            dialog = self.app.display_dialog
            
            if hasattr(dialog, 'view_palettes') and 0 in dialog.view_palettes:
                return dialog.view_palettes[0]
        
        # Fallback to global class_palette
        if hasattr(self.app, 'class_palette') and self.app.class_palette:
            return self.app.class_palette
        
        return None
    
    def _refresh_main_view(self):
        """
        ✅ FIXED: Refresh Main View with proper weight synchronization
        """
        print(f"      📋 Main View (Slot 0):")
        
        # Only refresh if in class mode
        if self.app.display_mode != "class":
            print(f"         ⏭️ Not in class mode")
            return
        
        # ✅ CRITICAL FIX: Sync weights BEFORE refresh
        self._sync_main_view_palette_weights()
        
        # Get visible classes
        palette = getattr(self.app, 'class_palette', {})
        
        if not palette:
            print(f"         ❌ No palette available")
            return
        
        visible = [c for c, v in palette.items() if v.get("show", False)]
        
        if not visible:
            print(f"         ⏭️ No visible classes")
            return
        
        print(f"         👁️ Visible classes: {len(visible)}")
        
        # ✅ DEBUG: Show current weights
        print(f"         📊 Current weights:")
        for code in sorted(visible):
            weight = palette[code].get('weight', 1.0)
            desc = palette[code].get('description', f'Class {code}')
            print(f"            Class {code} ({desc[:20]}): {weight:.2f}x")
        
        # ✅ UNIFIED ACTOR: push updated weights into GPU uniform LUT — no rebuild
        try:
            from gui.unified_actor_manager import sync_palette_to_gpu, is_unified_actor_ready
            if is_unified_actor_ready(self.app):
                border_pct = float(getattr(self.app, 'point_border_percent', 0) or 0.0)
                sync_palette_to_gpu(self.app, 0, palette, border_pct, render=True)
                print(f"         ✅ Unified GPU weight sync complete")
            else:
                from gui.class_display import update_class_mode
                update_class_mode(self.app)
                print(f"         ✅ Refreshed with updated weights (build path)")
        except Exception as e:
            print(f"         ⚠️ Refresh failed: {e}")
            import traceback
            traceback.print_exc()
            
    def _show_refresh_flash(self, view_index):
        """
        ✅ Show a subtle visual flash to indicate refresh happened
        Makes the user aware their classification was instantly applied
        """
        try:
            if not hasattr(self.app, 'section_vtks') or view_index not in self.app.section_vtks:
                return
            
            vtk_widget = self.app.section_vtks[view_index]
            
            # Method 1: Brief background color flash (subtle)
            original_bg = vtk_widget.renderer.GetBackground()
            
            # Flash to slightly brighter background
            flash_color = (
                min(original_bg[0] + 0.1, 1.0),
                min(original_bg[1] + 0.1, 1.0),
                min(original_bg[2] + 0.1, 1.0)
            )
            
            vtk_widget.renderer.SetBackground(*flash_color)
            self._safe_render_pyvista(vtk_widget)
            
            # Restore original background after brief delay
            from PySide6.QtCore import QTimer
            
            def restore_background():
                try:
                    vtk_widget.renderer.SetBackground(*original_bg)
                    self._safe_render_pyvista(vtk_widget)
                except:
                    pass
            
            # Flash duration: 150ms (very brief, not annoying)
            QTimer.singleShot(150, restore_background)
            
            print(f"   ✨ Visual feedback shown")
            
        except Exception as e:
            # Visual feedback is optional - don't break if it fails
            print(f"   ⚠️ Visual feedback failed (non-critical): {e}")

    def _show_cursor_feedback(self):
        """
        Alternative visual feedback: briefly change cursor to indicate success
        Less intrusive than background flash
        """
        try:
            from PySide6.QtCore import Qt, QTimer
            from PySide6.QtWidgets import QApplication
            
            # Save original cursor
            original_cursor = QApplication.overrideCursor()
            
            # Show "success" cursor briefly (pointing hand)
            QApplication.setOverrideCursor(Qt.PointingHandCursor)
            
            # Restore after 200ms
            def restore_cursor():
                QApplication.restoreOverrideCursor()
                if original_cursor:
                    QApplication.setOverrideCursor(original_cursor)
            
            QTimer.singleShot(200, restore_cursor)
            
        except Exception as e:
            print(f"   ⚠️ Cursor feedback failed: {e}")

    def _verify_actor_update(self, view_index, class_code, expected_size):
        """
        ✅ UNIFIED ACTOR: Verify weight via ViewShaderContext.weight_lut.
        Per-class actors no longer exist — point sizes live in the GPU uniform LUT.
        """
        try:
            vtk_widget = getattr(self.app, 'section_vtks', {}).get(view_index)
            if vtk_widget is None:
                return False

            # Unified section actor name
            actor = vtk_widget.actors.get(f"_section_{view_index}_unified")
            if actor is None:
                print(f"      ⚠️ View {view_index+1}: unified actor not found — skipping verify")
                return False

            ctx = getattr(actor, '_naksha_shader_ctx', None)
            if ctx is None:
                print(f"      ⚠️ View {view_index+1}: no shader ctx on unified actor")
                return False

            actual_size = float(ctx.weight_lut[int(class_code)])
            size_match  = abs(actual_size - expected_size) < 0.05

            if size_match:
                print(f"      ✅ View {view_index+1}: Class {class_code} LUT verified ({actual_size:.2f})")
            else:
                print(f"      ❌ View {view_index+1}: Class {class_code} LUT MISMATCH! "
                      f"expected={expected_size:.2f} actual={actual_size:.2f}")
            return size_match

        except Exception as e:
            print(f"      ⚠️ Verify failed: {e}")
            return False

    def on_key_press(self, obj, evt):
        """Handle keyboard shortcuts."""
        # ✅ CRITICAL SAFETY CHECK
        if not hasattr(self, 'app') or self.app is None:
            return
        
        if not hasattr(self, 'interactor') or self.interactor is None:
            return
        
        key = self.interactor.GetKeySym().lower()
        
        # EXISTING ESC HANDLER
        if key == "escape":
            print("\n⚠️ ESC pressed - deactivating classification tool")
            
            if hasattr(self.app, 'deactivate_classification'):
                self.app.deactivate_classification()
            else:
                self.app.active_classify_tool = None
                self.app.skip_main_view_refresh = False
            
            self.P1 = None
            self.is_dragging = False
            self.drawing_points = []
            self.is_drawing_freehand = False
            self._clear_all_previews()
            
            print("✅ Classification tool cancelled")
        
        elif key == "f":
            return

    def handle_escape(self):
        """Handle ESC key inside classification context safely."""
        try:
            if hasattr(self.app, "active_classify_tool"):
                print(f"🟣 ESC pressed in classification tool '{self.app.active_classify_tool}'")
                self.app.active_classify_tool = None
                if hasattr(self.app, "statusBar"):
                    self.app.statusBar().showMessage("Classification cancelled.", 3000)
                print("✅ Classification ESC handled cleanly.")
        except Exception as e:
            print(f"⚠️ Classification ESC error: {e}")


    def _draw_freehand_preview(self, live_point=None):
        """
        ✅ PERFORMANCE FIX: Delegates to the optimised version above (no duplicate pipeline).
        Works for MAIN (XY) and SECTION (u,z) — uses self._freehand_* reusable pipeline.
        """
        # The optimised _draw_freehand_preview defined earlier in the class handles this.
        # Python uses the LAST definition of a method, so this body must contain the logic.
        if len(self.drawing_points) < 1:
            return

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            # Fallback: use first renderer
            try:
                rw = self.interactor.GetRenderWindow()
                renderer = rw.GetRenderers().GetFirstRenderer()
            except Exception:
                return
        else:
            renderer = vtk_widget.renderer

        all_pts = list(self.drawing_points)
        if live_point:
            all_pts.append(live_point)
        if len(all_pts) < 2:
            return

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_freehand_pts") or self.freehand_actor is None:
            from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D, vtkActor2D, vtkCoordinate as _C

            self._freehand_pts   = vtkPoints()
            self._freehand_lines = vtkCellArray()
            self._freehand_poly  = vtkPolyData()
            self._freehand_poly.SetPoints(self._freehand_pts)
            self._freehand_poly.SetLines(self._freehand_lines)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._freehand_poly)
            dc = _C(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.freehand_actor = vtkActor2D()
            self.freehand_actor.SetMapper(mapper)
            prop = self.freehand_actor.GetProperty()
            prop.SetColor(1, 0.8, 0)
            prop.SetLineWidth(2)
            prop.SetOpacity(0.8)

            renderer.AddActor2D(self.freehand_actor)

        if not renderer.HasViewProp(self.freehand_actor):
            renderer.AddActor2D(self.freehand_actor)
        self.freehand_actor.VisibilityOn()

        if not hasattr(self, "_freehand_coord"):
            from vtkmodules.vtkRenderingCore import vtkCoordinate as _C
            self._freehand_coord = _C()
            self._freehand_coord.SetCoordinateSystemToWorld()

        coord = self._freehand_coord
        self._freehand_pts.Reset()
        self._freehand_lines.Reset()

        for i, (u, v) in enumerate(all_pts):
            xw, yw, zw = self._view2d_to_world(u, v)
            coord.SetValue(xw, yw, zw)
            d = coord.GetComputedDisplayValue(renderer)
            self._freehand_pts.InsertNextPoint(d[0], d[1], 0)
            if i > 0:
                self._freehand_lines.InsertNextCell(2)
                self._freehand_lines.InsertCellPoint(i - 1)
                self._freehand_lines.InsertCellPoint(i)

        self._freehand_pts.Modified()
        self._freehand_poly.Modified()
        # Render batched by caller

    def _draw_point_cursor(self, center, radius=0.5):
        """✅ POINT CURSOR: Filled circle with outline (different from brush/circle tools)"""
        renderWindow = self.interactor.GetRenderWindow()
        renderer = renderWindow.GetRenderers().GetFirstRenderer()
 
        # Remove previous actor
        if hasattr(self, "brush_actor") and self.brush_actor:
            renderer.RemoveActor2D(self.brush_actor)
            self.brush_actor = None
 
        cx, cz = center
 
        # Force minimum radius
        if radius < 0.05:
            radius = 0.1
 
        from vtkmodules.vtkRenderingCore import vtkCoordinate
       
        # ========== CREATE FILLED POINT SHAPE ==========
        # 1. Filled circle (using triangle fan)
        # 2. Outline circle
       
        num_segments = 32
       
        # Create circle points in world space
        circle_world = []
        for i in range(num_segments + 1):
            angle = 2 * np.pi * i / num_segments
            x = cx + radius * np.cos(angle)
            z = cz + radius * np.sin(angle)
            circle_world.append((x, 0, z))
       
        # Convert to 2D display coordinates
        pts = vtkPoints()
       
        # Add center point first (for triangle fan)
        coord_center = vtkCoordinate()
        coord_center.SetCoordinateSystemToWorld()
        coord_center.SetValue(cx, 0, cz)
        display_center = coord_center.GetComputedDisplayValue(renderer)
        pts.InsertNextPoint(display_center[0], display_center[1], 0)
       
        # Add circle perimeter points
        for point in circle_world:
            coord = vtkCoordinate()
            coord.SetCoordinateSystemToWorld()
            coord.SetValue(point[0], point[1], point[2])
            display_pos = coord.GetComputedDisplayValue(renderer)
            pts.InsertNextPoint(display_pos[0], display_pos[1], 0)
 
        # Create filled circle using triangle fan
        from vtkmodules.vtkCommonDataModel import vtkCellArray
        polys = vtkCellArray()
       
        # Triangle fan from center to perimeter
        for i in range(1, num_segments + 1):
            polys.InsertNextCell(3)
            polys.InsertCellPoint(0)  # Center
            polys.InsertCellPoint(i)
            polys.InsertCellPoint(i + 1 if i < num_segments else 1)
 
        # Create outline
        lines = vtkCellArray()
        for i in range(1, num_segments + 1):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i)
            lines.InsertCellPoint(i + 1 if i < num_segments else 1)
 
        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetPolys(polys)  # Filled triangles
        poly.SetLines(lines)   # Outline
 
        # Create 2D mapper
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D
        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
       
        coordinate = vtkCoordinate()
        coordinate.SetCoordinateSystemToDisplay()
        mapper.SetTransformCoordinate(coordinate)
 
        # Create 2D actor
        from vtkmodules.vtkRenderingCore import vtkActor2D
        self.brush_actor = vtkActor2D()
        self.brush_actor.SetMapper(mapper)
 
        # Set properties - Semi-transparent filled yellow circle with outline
        prop = self.brush_actor.GetProperty()
        prop.SetColor(1, 1, 0)  # Yellow
        prop.SetLineWidth(2)
        prop.SetOpacity(0.5)  # Semi-transparent for filled area
 
        renderer.AddActor2D(self.brush_actor)
        print(f"🎯 Point cursor drawn (filled circle, radius={radius:.2f})")

     # ======== MAIN-VIEW CLASSIFIERS (Plan View: XY) ========
 
    def _apply_mask_and_record(self, mask, to_class):
        """
        Apply classification to app.data using mask and push an undo step.

        ✅ FIX: In MAIN VIEW, classification affects ONLY classes that are visible
            in Display Mode (slot 0). Hidden classes are protected.
        ✅ Also enforces from_classes here (so brush + any caller is consistent).
        """
        self.app._gpu_sync_done = False
        self.app._last_changed_mask = None

        if mask is None or not np.any(mask):
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage("No points found in selection.", 2000)
            return False

        if to_class is None:
            to_class = getattr(self.app, "to_class", None)
        if to_class is None:
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage("Target class not set.", 2000)
            return False

        classes = self.app.data["classification"]

        # ---------------------------------------------------------
        # ✅ 1) Enforce from_classes filter (safe even if caller did it already)
        # ---------------------------------------------------------
        mask = self._filter_from_classes(mask)

        # ---------------------------------------------------------
        # ✅ 2) Enforce Display Mode visibility filter for MAIN VIEW (slot 0)
        # ---------------------------------------------------------
        if self._is_main_view():
            visible_classes = self._get_visible_classes_for_slot(0)

            # If palette exists but nothing visible -> do nothing
            if visible_classes == []:
                if hasattr(self.app, 'statusBar'):
                    self.app.statusBar().showMessage("No visible classes selected in Display Mode.", 2500)
                return False

            # If we can filter, protect hidden classes
            if visible_classes is not None:
                vis_mask = np.isin(classes, np.asarray(visible_classes, dtype=classes.dtype))
                mask = mask & vis_mask

        # Final check
        if not np.any(mask):
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage("No visible/from-class points in selection.", 2500)
            return False

        # ---------------------------------------------------------
        # Apply + Undo/Redo
        # ---------------------------------------------------------
        old = classes[mask].copy()
        new = np.full(old.shape, to_class, dtype=classes.dtype)

        self.app.undo_stack.append({"mask": mask, "old_classes": old, "new_classes": new})
        self.app.redo_stack.clear()

        classes[mask] = to_class
        self.app._last_changed_mask = mask

        # ✅ Store from_classes for undo
        self.app._last_from_classes = list(getattr(self.app, "from_classes", []) or [])

        # ─────────────────────────────────────────────────────────────
        # ⚡ MICROSTATION-STYLE INSTANT GPU INJECTION (replaces heavy optimizer)
        # ─────────────────────────────────────────────────────────────
        try:
            from gui.unified_actor_manager import fast_classify_update, fast_cross_section_update
            
            border_percent = float(getattr(self.app, "point_border_percent", 0.0))
            palette = getattr(self.app, "class_palette", {})
            
            # 1. Main view: inject colors directly into GPU buffer (O(changed_points))
            fast_classify_update(self.app, mask, to_class, palette=palette, border_percent=border_percent)
            
            # 2. Cross-sections: shared memory slave update (O(1) - just render)
            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in self.app.section_vtks.keys():
                    try:
                        fast_cross_section_update(self.app, view_idx, mask)
                    except Exception:
                        pass
            
            # 3. Cut section: direct RGB poke (MicroStation style — changed points only)
            if hasattr(self.app, 'cut_section_controller') and self.app.cut_section_controller:
                ctrl = self.app.cut_section_controller
                if getattr(ctrl, 'is_cut_view_active', False) and ctrl._cut_index_map is not None:
                    try:
                        target_actor = getattr(ctrl, 'cut_core_actor', None)
                        if target_actor and hasattr(target_actor, 'GetMapper'):
                            polydata = target_actor.GetMapper().GetInput()
                            if polydata:
                                vtk_colors = polydata.GetPointData().GetScalars()
                                if vtk_colors:
                                    from vtkmodules.util import numpy_support as _ns
                                    vtk_ptr = _ns.vtk_to_numpy(vtk_colors)
                                    
                                    cut_map = ctrl._cut_index_map
                                    update_idx = np.where(mask)[0]
                                    
                                    # Build reverse lookup: global_idx → local_idx
                                    # cut_map is NOT sorted, so searchsorted won't work
                                    update_set = set(update_idx.tolist())
                                    local_hits = []
                                    for local_i in range(len(cut_map)):
                                        if int(cut_map[local_i]) in update_set:
                                            local_hits.append(local_i)
                                    
                                    if local_hits:
                                        local_arr = np.array(local_hits, dtype=np.int64)
                                        new_color = palette.get(to_class, {}).get('color', (128, 128, 128))
                                        vtk_ptr[local_arr] = new_color
                                        vtk_colors.Modified()
                                        polydata.Modified()
                                    
                                    if hasattr(ctrl, 'cut_vtk') and ctrl.cut_vtk:
                                        self._safe_render_pyvista(ctrl.cut_vtk)
                    except Exception as _ce:
                        print(f"⚠️ Cut section poke failed: {_ce}")
            
            # 4. SINGLE BATCHED RENDER (replaces per-function render calls)
            try:
                self._safe_render_pyvista(self.app.vtk_widget)
            except Exception:
                pass
            
            # 5. Point statistics
            try:
                from gui.point_count_widget import refresh_point_statistics
                refresh_point_statistics(self.app)
            except Exception:
                pass
            
            # 6. Status bar
            n_pts = int(mask.sum())
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage(f"✅ {n_pts:,} points → class {to_class}", 3000)

            # ✅ FIX: Signal that GPU sync is complete — prevents the
            # classify_with_stats_update decorator from triggering a
            # redundant 170ms OptimizedRefreshPipeline cycle.
            self.app._gpu_sync_done = True
            
            if (getattr(self.app, "display_mode", None) == "shaded_class"
                    and _shading_mesh_exists(self.app)):
                try:
                    from gui.shading_display import refresh_shaded_after_classification_fast
                    refresh_shaded_after_classification_fast(self.app, mask)
                except Exception as _se:
                    print(f"⚠️ Shading refresh failed: {_se}")
                    try:
                        from gui.shading_display import update_shaded_class
                        update_shaded_class(self.app, force_rebuild=True)
                    except Exception:
                        pass
            elif getattr(self.app, "display_mode", None) == "shaded_class":
                print("⏭️ Skipping shading refresh — no shading mesh built yet "
                      "(mode restored from settings, Apply not pressed)")

        except Exception as e:
            print(f"⚠️ Fast injection failed, falling back to full refresh: {e}")
            import traceback
            traceback.print_exc()
            self._refresh_all_views_after_classification(to_class)
            return True

        return True

    def _get_visible_classes_for_slot(self, slot: int):
        """
        slot 0 = Main View, slot 1..4 = Cross Section views.
        Returns:
        - []  : if palette exists but nothing is visible (block classification)
        - None: if no palette available (do not filter)
        - list of visible class codes otherwise
        """
        dialog = getattr(self.app, "display_mode_dialog", None) or getattr(self.app, "display_dialog", None)

        palette = None

        # Priority 1: dialog palettes (most accurate)
        if dialog is not None and hasattr(dialog, "view_palettes") and slot in dialog.view_palettes:
            palette = dialog.view_palettes.get(slot)

        # Priority 2: app stored palettes
        if (not palette) and hasattr(self.app, "view_palettes"):
            palette = self.app.view_palettes.get(slot)

        # Priority 3: fallback main palette
        if (not palette) and slot == 0:
            palette = getattr(self.app, "class_palette", None)

        if not palette:
            return None  # no filtering possible

        visible = [int(code) for code, info in palette.items() if info.get("show", False)]
        return visible  # can be [] intentionally
 
    def _filter_from_classes(self, mask):
        """If from-classes are set, keep only those; otherwise return mask."""
        fc = getattr(self.app, "from_classes", None)
        if not fc:
            return mask
        classes = self.app.data["classification"]
        return mask & np.isin(classes, np.asarray(fc, dtype=classes.dtype))
 
    def _classify_rectangle_main(self, p1, p2, to_class):
        """Rectangle selection on plan view (XY)."""
        xyz = self.app.data["xyz"]
        x1, y1 = p1
        x2, y2 = p2
        xmin, xmax = sorted([x1, x2])
        ymin, ymax = sorted([y1, y2])
        mask = (xyz[:, 0] >= xmin) & (xyz[:, 0] <= xmax) & (xyz[:, 1] >= ymin) & (xyz[:, 1] <= ymax)
        mask = self._filter_from_classes(mask)
        self._apply_mask_and_record(mask, to_class)
 
    def _classify_circle_main(self, center, radius, to_class):
        """Circle selection on plan view (XY)."""
        xyz = self.app.data["xyz"]
        cx, cy = center
        dx = xyz[:, 0] - cx
        dy = xyz[:, 1] - cy
        mask = (dx * dx + dy * dy) <= (radius * radius)
        mask = self._filter_from_classes(mask)
        self._apply_mask_and_record(mask, to_class)
 
    def _classify_polygon_main(self, poly2d, to_class):
        """Polygon/freehand selection on plan view (XY)."""
        xs = np.array([p[0] for p in poly2d], dtype=np.float64)
        ys = np.array([p[1] for p in poly2d], dtype=np.float64)
        xmin, xmax = xs.min(), xs.max()
        ymin, ymax = ys.min(), ys.max()
 
        xy = self.app.data["xyz"][:, :2]
        bbmask = (xy[:, 0] >= xmin) & (xy[:, 0] <= xmax) & (xy[:, 1] >= ymin) & (xy[:, 1] <= ymax)
        candidates = np.where(bbmask)[0]
 
        if candidates.size == 0:
            self._apply_mask_and_record(bbmask, to_class)  # no points
            return
 
        # Fast point-in-polygon using matplotlib, with fallback
        try:
            from matplotlib.path import Path
            path = Path(np.c_[xs, ys], closed=True)
            inside = path.contains_points(xy[candidates])
            final_mask = np.zeros(len(xy), dtype=bool)
            final_mask[candidates[inside]] = True
        except Exception:
            # Ray casting fallback
            final_mask = np.zeros(len(xy), dtype=bool)
            poly = np.c_[xs, ys]
            for idx in candidates:
                x, y = xy[idx]
                c = False
                j = len(poly) - 1
                for i in range(len(poly)):
                    xi, yi = poly[i]
                    xj, yj = poly[j]
                    if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
                        c = not c
                    j = i
                if c:
                    final_mask[idx] = True
 
        final_mask = self._filter_from_classes(final_mask)
        self._apply_mask_and_record(final_mask, to_class)
 
    def _classify_brush_main(self, center, radius, to_class):
        """Brush = circle selection at current mouse position (plan view)."""
        self._classify_circle_main(center, radius, to_class)
 
    def _classify_point_main(self, center, radius, to_class):
        """Point tool acts like a very small circle on plan view."""
        self._classify_circle_main(center, radius, to_class)
        
    def _draw_circle_preview_main(self, P1, P2):
        """✅ Draw circle preview for MAIN VIEW (XY plane)"""
        renderWindow = self.interactor.GetRenderWindow()
        renderer = renderWindow.GetRenderers().GetFirstRenderer()

        # Remove previous actor
        if hasattr(self, "circle_actor") and self.circle_actor:
            renderer.RemoveActor2D(self.circle_actor)
            self.circle_actor = None

        # Extract XY coordinates (plan view)
        x1, y1 = P1[0], P1[1]
        x2, y2 = P2[0], P2[1]

        # Calculate circle parameters
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        radius = np.sqrt((x2 - x1)**2 + (y2 - y1)**2) / 2.0

        print(f"  Main view circle: center=({center_x:.2f}, {center_y:.2f}), radius={radius:.2f}")

        # Generate circle points in XY plane
        num_segments = 64
        theta = np.linspace(0, 2 * np.pi, num_segments)
        circle_x = center_x + radius * np.cos(theta)
        circle_y = center_y + radius * np.sin(theta)

        # Build 3D coordinates (Z = 0 for plan view)
        circle_points = np.column_stack([
            circle_x,
            circle_y,
            np.zeros(num_segments)  # Z = 0 for plan view
        ])

        # Convert world coordinates to display coordinates
        from vtkmodules.vtkRenderingCore import vtkCoordinate, vtkPolyDataMapper2D, vtkActor2D
        pts = vtkPoints()
        coord = vtkCoordinate()
        coord.SetCoordinateSystemToWorld()

        for pt in circle_points:
            coord.SetValue(pt[0], pt[1], pt[2])
            display_pos = coord.GetComputedDisplayValue(renderer)
            pts.InsertNextPoint(display_pos[0], display_pos[1], 0)

        # Create polyline
        lines = vtkCellArray()
        for i in range(num_segments):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i)
            lines.InsertCellPoint((i + 1) % num_segments)

        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)

        # Create 2D mapper
        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)

        coordinate = vtkCoordinate()
        coordinate.SetCoordinateSystemToDisplay()
        mapper.SetTransformCoordinate(coordinate)

        # Create 2D actor (always on top)
        self.circle_actor = vtkActor2D()
        self.circle_actor.SetMapper(mapper)

        # Set properties - Yellow like other tools
        prop = self.circle_actor.GetProperty()
        prop.SetColor(1.0, 1.0, 0.0)  # Yellow
        prop.SetLineWidth(2)
        prop.SetOpacity(1.0)

        renderer.AddActor2D(self.circle_actor)
        print("✅ Circle preview rendered (main view)")    

    def _draw_circle_preview(self, P1, P2):
        """
        ✅ PERFORMANCE FIX: Reuse Actor2D — no RemoveActor/new objects per frame.
        """
        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        u1, z1 = self._get_view_coordinates(P1)
        u2, z2 = self._get_view_coordinates(P2)
        center_u = (u1 + u2) / 2.0
        center_z = (z1 + z2) / 2.0
        radius = float(np.hypot(u2 - u1, z2 - z1)) / 2.0
        if radius < 0.01:
            return

        num_segments = 64

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_circle_pts") or self.circle_actor is None:
            from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D, vtkActor2D, vtkCoordinate as _C

            self._circle_pts   = vtkPoints()
            self._circle_lines = vtkCellArray()
            self._circle_poly  = vtkPolyData()
            self._circle_poly.SetPoints(self._circle_pts)
            self._circle_poly.SetLines(self._circle_lines)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._circle_poly)
            dc = _C(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.circle_actor = vtkActor2D()
            self.circle_actor.SetMapper(mapper)
            prop = self.circle_actor.GetProperty()
            prop.SetColor(1.0, 1.0, 0.0)
            prop.SetLineWidth(2)
            prop.SetOpacity(1.0)

            renderer.AddActor2D(self.circle_actor)

        if not renderer.HasViewProp(self.circle_actor):
            renderer.AddActor2D(self.circle_actor)
        self.circle_actor.VisibilityOn()

        # ── FAST GEOMETRY UPDATE ─────────────────────────────────────────────
        if not hasattr(self, "_circle_coord"):
            from vtkmodules.vtkRenderingCore import vtkCoordinate as _C
            self._circle_coord = _C()
            self._circle_coord.SetCoordinateSystemToWorld()

        coord = self._circle_coord
        self._circle_pts.Reset()
        self._circle_lines.Reset()

        theta = np.linspace(0, 2 * np.pi, num_segments + 1)
        circle_u = center_u + radius * np.cos(theta)
        circle_z = center_z + radius * np.sin(theta)

        for i in range(num_segments + 1):
            wx, wy, wz = self._view2d_to_world(circle_u[i], circle_z[i])
            coord.SetValue(wx, wy, wz)
            d = coord.GetComputedDisplayValue(renderer)
            self._circle_pts.InsertNextPoint(d[0], d[1], 0)
            if i > 0:
                self._circle_lines.InsertNextCell(2)
                self._circle_lines.InsertCellPoint(i - 1)
                self._circle_lines.InsertCellPoint(i)

        self._circle_pts.Modified()
        self._circle_poly.Modified()
        # Render batched by caller

    def _calculate_perpendicular_coord(self):
        """Calculate perpendicular coordinate ONCE per drawing session"""
        view_mode = getattr(self.app, 'cross_view_mode', 'side')
        active_view = self._get_view_index_from_interactor()
        
        if active_view is None:
            return 0.0
        
        core_mask = getattr(self.app, f"section_{active_view}_core_mask", None)
        if core_mask is None or core_mask.sum() == 0:
            return 0.0
        
        section_xyz = self.app.data["xyz"][core_mask]
        
        if view_mode == 'front':
            return float(np.median(section_xyz[:, 0]))
        else:
            return float(np.median(section_xyz[:, 1]))

    def _force_immediate_refresh(self):
        """
        Force immediate visual refresh after classification.
        DOES NOT re-apply classifications, only updates colors/rendering.
        
        IMPORTANT: This should ONLY refresh cross-section/cut-section views.
        The main view has its own independent display settings and should NOT
        be modified during cross-section classification operations.
        """
        print(f"\n{'='*60}")
        print(f"🔄 FORCING VISUAL REFRESH (CROSS-SECTIONS ONLY)")
        print(f"{'='*60}")
        
        try:
            # DO NOT REFRESH MAIN VIEW OR TRIGGER apply_class_map
            # The main view has independent display mode settings that should
            # not be affected by cross-section classification operations
            print("⏭️ Skipping main view refresh (preserving independent display settings)")
            print("⏭️ NOT calling apply_class_map (would trigger unwanted main view update)")
            
            # 1. Refresh cross-section colors (ALWAYS) - Direct color update only
            if hasattr(self.app, 'section_controller'):
                if hasattr(self.app.section_controller, 'current_section_indices'):
                    if self.app.section_controller.current_section_indices is not None:
                        print("🔄 Refreshing cross-section colors...")
                        # Instead of calling apply_class_map, directly update colors
                        self.app.section_controller.refresh_colors_direct()
                        print("   ✅ Cross-section colors updated")
            
            # 2. Refresh cut-section colors if active (ALWAYS) - Direct color update only
            if hasattr(self.app, 'cut_section_controller'):
                if self.app.cut_section_controller.cut_points is not None:
                    print("🔄 Refreshing cut-section colors...")
                    # Direct color update without triggering apply_class_map
                    self.app.cut_section_controller.refresh_colors_direct()
                    print("   ✅ Cut-section colors updated")
            
            # 3. Update status bar
            self.app.statusBar().showMessage(
                "✅ Cross-section classification updated", 
                3000
            )
            
            print(f"{'='*60}")
            print(f"✅ CROSS-SECTION REFRESH COMPLETE")
            print(f"   Main view display settings preserved")
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"⚠️ ERROR DURING REFRESH: {e}")
            print(f"{'='*60}\n")
            import traceback
            traceback.print_exc()

    def test_palette_isolation(dialog):
        """Test that view palettes are truly independent"""
        print("\n" + "="*60)
        print("🧪 TESTING PALETTE ISOLATION")
        print("="*60)
        
        # Test 1: Check dictionary IDs
        print("\n1. Dictionary Identity Test:")
        for i in range(5):
            dict_id = id(dialog.view_palettes[i])
            print(f"   Slot {i}: ID = {dict_id}")
        
        # Test 2: Modify one slot
        print("\n2. Modification Test:")
        print("   Adding test class to slot 2...")
        dialog.view_palettes[2][999] = {"show": True, "description": "TEST", "color": (255, 0, 0), "weight": 1.0}
        
        for i in range(5):
            has_test = 999 in dialog.view_palettes[i]
            print(f"   Slot {i}: Has test class = {has_test} (should be True ONLY for slot 2)")
        
        # Clean up
        if 999 in dialog.view_palettes[2]:
            del dialog.view_palettes[2][999]
        
        print("\n✅ Test complete")
        print("="*60 + "\n")

    def _ensure_target_class_visible_single_view(self, to_class, view_index):
        """
        ✅ SAFE VERSION
        Auto-enable target class ONLY if NO user filter is active.
        """
        try:
            if not hasattr(self.app, 'display_mode_dialog'):
                return

            dialog = self.app.display_mode_dialog

            if view_index == -1:
                target_slot = 0
                view_name = "Main View"
            else:
                target_slot = view_index + 1
                view_name = f"View {view_index + 1}"

            print(f"      🔍 Checking {view_name} (slot {target_slot})...")

            dialog.view_palettes.setdefault(target_slot, {})

            # 🔒 USER FILTER GUARD (THIS IS THE FIX)
            view_palette = dialog.view_palettes[target_slot]
            visible_count = sum(1 for v in view_palette.values() if v.get("show", False))
            total_count = len(view_palette)

            if 0 < visible_count < total_count:
                print(f"         🔒 User filter active - NOT auto-enabling")
                return

            if to_class in view_palette and view_palette[to_class].get("show", False):
                print(f"         ✓ Class {to_class} already visible")
                return

            table = dialog.table
            for row in range(table.rowCount()):
                code = int(table.item(row, 1).text())
                if code == to_class:
                    class_desc = table.item(row, 2).text()
                    color = table.item(row, 5).background().color().getRgb()[:3]
                    weight_item = table.item(row, 6)
                    weight = float(weight_item.text()) if weight_item else 1.0

                    dialog.view_palettes[target_slot][to_class] = {
                        "show": True,
                        "description": class_desc,
                        "color": tuple(map(int, color)),
                        "weight": float(weight)
                    }

                    print(f"         ✅ Enabled class {to_class} in {view_name}")

                    if target_slot == 0:
                        self.app.class_palette[to_class]["show"] = True

                    if dialog.current_slot == target_slot:
                        chk = table.cellWidget(row, 0)
                        if chk:
                            chk.setChecked(True)

                    break

        except Exception as e:
            print(f"         ⚠️ Error: {e}")
            import traceback
            traceback.print_exc()

    def _refresh_only_active_dock(self):
        """Refresh ONLY the currently active cross-section dock."""
        try:
            active = getattr(self.app.section_controller, "active_view", None)
            if active is None:
                return

            # Extract changed indices from the changed mask
            if hasattr(self.app, '_last_changed_mask') and self.app._last_changed_mask is not None:
                changed_indices = np.where(self.app._last_changed_mask)[0]
            else:
                changed_indices = np.array([], dtype=np.int64)

            # refresh ONLY this view
            self.app.section_controller.active_view = active
            self.app.section_controller.update_section_colors_partial(changed_indices)


            # render its vtk widget
            if active in self.app.section_vtks:
                self._safe_render_pyvista(self.app.section_vtks[active])

            print(f"🔄 Refreshed ONLY Cross-Section View {active+1}")

        except Exception as e:
            print(f"⚠️ Failed refreshing only active dock: {e}")

    def _refresh_changed_points_in_all_docks(self):
        """
        Refresh ONLY the points modified by classification across all docks.
        Uses each dock's own Display Mode palette.
        """

        if not hasattr(self.app, "_last_changed_mask"):
            return

        changed_mask = self.app._last_changed_mask
        if changed_mask.sum() == 0:
            return

        # Extract changed indices from the changed mask
        changed_indices = np.where(changed_mask)[0]

        # All cross-section views
        for view_idx, vtk_view in self.app.section_vtks.items():

            # Get per-view palette
            palette = self.app.view_palettes.get(view_idx, None)

            if palette is not None:
                self.app.class_palette = palette.copy()
            else:
                self.app.class_palette = {}

            # Set active view so refresh uses correct palette
            old = self.app.section_controller.active_view
            self.app.section_controller.active_view = view_idx

            # Refresh only changed points
            self.app.section_controller.update_section_colors_partial(changed_indices)

            # Restore original active view
            self.app.section_controller.active_view = old

        print("🔄 Updated ONLY changed points across all views")
    def _refresh_shaded_mode_partial(self):
        """
        ✅ PARTIAL SHADED REFRESH: Update ONLY triangles containing changed points
        Much faster than full mesh rebuild - only affects classified area
        """
        if self.app.display_mode != "shaded_class":
            return
        
        if not hasattr(self.app, '_last_changed_mask') or self.app._last_changed_mask is None:
            print("⏭️ No changed points mask for shaded refresh")
            return
        
        changed_mask = self.app._last_changed_mask
        num_changed = np.sum(changed_mask)
        
        if num_changed == 0:
            return
        
        print(f"\n{'='*60}")
        print(f"🌗 PARTIAL SHADED REFRESH")
        print(f"   Changed points: {num_changed:,}")
        print(f"{'='*60}")
        
        try:
            import numpy as np
            import pyvista as pv
            
            # ============================================================
            # STEP 1: Get existing mesh from VTK
            # ============================================================
            plotter = getattr(self.app.vtk_widget, "plotter", None)
            if plotter is None or not plotter.renderer.actors:
                print("   ⚠️ No existing shaded mesh - doing full refresh")
                self._refresh_shaded_mode_after_classification()
                return
            
            # Get the first actor (main shaded mesh)
            actor = list(plotter.renderer.actors.values())[0]
            mesh = actor.GetMapper().GetInput()
            
            if mesh is None or mesh.GetNumberOfCells() == 0:
                print("   ⚠️ No mesh cells - doing full refresh")
                self._refresh_shaded_mode_after_classification()
                return
            
            print(f"   ✅ Found existing mesh with {mesh.GetNumberOfCells()} triangles")
            
            # ============================================================
            # STEP 2: Find which triangles contain changed points
            # ============================================================
            cells = np.asarray(mesh.faces).reshape(-1, 4)[:, 1:]  # Get triangle indices
            
            # Check which triangles have at least one changed vertex
            changed_indices = np.where(changed_mask)[0]
            affected_triangles = np.isin(cells, changed_indices).any(axis=1)
            num_affected = np.sum(affected_triangles)
            
            print(f"   📊 Affected triangles: {num_affected:,} / {len(cells):,}")
            
            if num_affected == 0:
                print("   ⏭️ No triangles affected")
                print(f"{'='*60}\n")
                return
            
            # ============================================================
            # STEP 3: Recompute colors ONLY for affected triangles
            # ============================================================
            xyz = self.app.data["xyz"]
            classes = self.app.data["classification"]
            
            # Get shading parameters
            az = np.deg2rad(getattr(self.app, "last_shade_azimuth", 45.0))
            el = np.deg2rad(getattr(self.app, "last_shade_angle", 45.0))
            Ld = np.array([
                np.cos(el) * np.cos(az),
                np.cos(el) * np.sin(az),
                np.sin(el)
            ])
            Ld /= np.linalg.norm(Ld)
            ambient = getattr(self.app, "shade_ambient", 0.2)
            
            # Get current colors array
            current_colors = np.asarray(mesh.GetCellData().GetArray("RGB"))
            
            # Recompute ONLY affected triangles
            affected_indices = np.where(affected_triangles)[0]
            
            for idx in affected_indices:
                face = cells[idx]
                
                # Recompute normal
                v1, v2, v3 = xyz[face[0]], xyz[face[1]], xyz[face[2]]
                fn = np.cross(v2 - v1, v3 - v1)
                fn /= np.linalg.norm(fn) + 1e-9
                
                # Recompute shading
                shade = ambient + (1 - ambient) * np.clip(np.dot(fn, Ld), 0, 1)
                
                # Get majority class (with CURRENT classifications)
                c = classes[face]
                majority = np.bincount(c).argmax()
                entry = self.app.class_palette.get(int(majority), {"color": (128, 128, 128)})
                
                # Check visibility
                if not entry.get("show", True):
                    current_colors[idx] = [0, 0, 0]  # Black for hidden
                else:
                    base = np.array(entry["color"], dtype=np.float32)
                    current_colors[idx] = np.clip(base * shade, 0, 255).astype(np.uint8)
            
            print(f"   ✅ Recomputed colors for {len(affected_indices)} triangles")
            
            # ============================================================
            # STEP 4: Update mesh colors (in-place, no rebuild!)
            # ============================================================
            arr = pv.convert_array(current_colors, name="RGB")
            mesh.GetCellData().RemoveArray("RGB")
            mesh.GetCellData().AddArray(arr)
            mesh.GetCellData().SetActiveScalars("RGB")
            mesh.Modified()
            
            # Single render
            self._safe_render_pyvista(self.app.vtk_widget)
            
            print(f"   ✅ Mesh updated in-place (no rebuild!)")
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"   ❌ Partial shaded refresh failed: {e}")
            print(f"   ⚠️ Falling back to full refresh")
            import traceback
            traceback.print_exc()
            
            # Fallback to full refresh if partial fails
            self._refresh_shaded_mode_after_classification()
            print(f"{'='*60}\n")

    def _draw_circle_preview_cut(self, P1, P2):
        """
        ✅ FIXED: Circle preview for CUT SECTION using display coordinates
        P1 and P2 are world coordinates (diameter endpoints)
        """
        from vtkmodules.vtkRenderingCore import vtkCoordinate, vtkPolyDataMapper2D, vtkActor2D
        from vtkmodules.vtkCommonCore import vtkPoints
        from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
        import math
        import numpy as np

        print(f"\n🔵 _draw_circle_preview_cut called")
        print(f"   P1 (world): ({P1[0]:.2f}, {P1[1]:.2f}, {P1[2]:.2f})")
        print(f"   P2 (world): ({P2[0]:.2f}, {P1[1]:.2f}, {P2[2]:.2f})")

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            print("❌ No VTK widget for circle preview (cut section)")
            return

        renderer = vtk_widget.renderer

        # Remove previous actor
        if hasattr(self, "circle_actor_cut") and self.circle_actor_cut:
            try:
                renderer.RemoveActor2D(self.circle_actor_cut)
                print("   🧹 Removed old circle_actor_cut")
            except Exception as e:
                print(f"   ⚠️ Could not remove old circle_actor_cut: {e}")
            self.circle_actor_cut = None

        # ✅ CRITICAL FIX: Ensure P1 and P2 are tuples/lists, not nested
        P1 = tuple(P1) if not isinstance(P1[0], (list, tuple)) else tuple(P1[0])
        P2 = tuple(P2) if not isinstance(P2[0], (list, tuple)) else tuple(P2[0])

        # ✅ CRITICAL FIX: Convert world coordinates to display coordinates
        coord = vtkCoordinate()
        coord.SetCoordinateSystemToWorld()

        # Get P1 in display space
        coord.SetValue(float(P1[0]), float(P1[1]), float(P1[2]))
        display_p1 = coord.GetComputedDisplayValue(renderer)

        # Get P2 in display space
        coord.SetValue(float(P2[0]), float(P2[1]), float(P2[2]))
        display_p2 = coord.GetComputedDisplayValue(renderer)

        print(f"   📐 Display coords: P1=({display_p1[0]:.1f}, {display_p1[1]:.1f}), P2=({display_p2[0]:.1f}, {display_p2[1]:.1f})")

        # Calculate center and radius in DISPLAY space (pixels)
        cx = (display_p1[0] + display_p2[0]) / 2.0
        cy = (display_p1[1] + display_p2[1]) / 2.0
        dx = display_p2[0] - display_p1[0]
        dy = display_p2[1] - display_p1[1]
        radius_display = math.sqrt(dx*dx + dy*dy) / 2.0  # ✅ This is now a float

        # Minimum visible radius
        if radius_display < 5.0:
            radius_display = 5.0

        print(f"   ⭕ Circle: center=({cx:.1f}, {cy:.1f}), radius={radius_display:.1f}px")

        # Build circle in DISPLAY coordinates
        num_segments = 64
        pts = vtkPoints()
        lines = vtkCellArray()

        for i in range(num_segments + 1):
            angle = 2.0 * math.pi * i / num_segments
            px = cx + radius_display * math.cos(angle)
            py = cy + radius_display * math.sin(angle)
            pts.InsertNextPoint(px, py, 0.0)

            if i > 0:
                lines.InsertNextCell(2)
                lines.InsertCellPoint(i - 1)
                lines.InsertCellPoint(i)

        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)

        # Create 2D mapper
        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)

        # Use display coordinate system
        coordinate = vtkCoordinate()
        coordinate.SetCoordinateSystemToDisplay()
        mapper.SetTransformCoordinate(coordinate)

        # Create 2D actor (always on top)
        self.circle_actor_cut = vtkActor2D()
        self.circle_actor_cut.SetMapper(mapper)

        # Set properties - Yellow like other tools
        prop = self.circle_actor_cut.GetProperty()
        prop.SetColor(1.0, 1.0, 0.0)  # Yellow
        prop.SetLineWidth(2)
        prop.SetOpacity(1.0)

        renderer.AddActor2D(self.circle_actor_cut)
        print(f"   ✅ Added circle_actor_cut to renderer")

        # Force render
        try:
            self._safe_render(vtk_widget)
            print("   ✅ Circle preview rendered")
        except Exception as e:
            print(f"   ⚠️ Render failed: {e}")



    def _draw_rectangle_preview_cut(self, P1, P2):
        """✅ Rectangle preview for CUT SECTION – uses DISPLAY coords like before."""
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D, vtkActor2D
        from vtkmodules.vtkCommonCore import vtkPoints
        from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        # Remove previous cut-rectangle actor
        if hasattr(self, "rect_actor_cut") and self.rect_actor_cut:
            try:
                renderer.RemoveActor2D(self.rect_actor_cut)
            except Exception:
                pass
            self.rect_actor_cut = None

        # Corner 1 in DISPLAY coords = where mouse was pressed
        if not hasattr(self, "P1_display_cut"):
            x1, y1 = self.interactor.GetEventPosition()
        else:
            x1, y1 = self.P1_display_cut

        # Corner 2 in DISPLAY coords = current mouse position
        x2, y2 = self.interactor.GetEventPosition()

        x_min, x_max = sorted((x1, x2))
        y_min, y_max = sorted((y1, y2))

        # Build rectangle in DISPLAY coordinates
        pts = vtkPoints()
        corners = [
            (x_min, y_min, 0.0),
            (x_max, y_min, 0.0),
            (x_max, y_max, 0.0),
            (x_min, y_max, 0.0),
            (x_min, y_min, 0.0),
        ]
        for c in corners:
            pts.InsertNextPoint(*c)

        lines = vtkCellArray()
        for i in range(1, len(corners)):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i - 1)
            lines.InsertCellPoint(i)

        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)

        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)

        self.rect_actor_cut = vtkActor2D()
        self.rect_actor_cut.SetMapper(mapper)

        prop = self.rect_actor_cut.GetProperty()
        prop.SetColor(1, 1, 0)   # same yellow as cross-section
        prop.SetLineWidth(2)     # same thickness as cross-section
        prop.SetOpacity(1.0)

        renderer.AddActor2D(self.rect_actor_cut)
        try:
            self._safe_render(vtk_widget)
        except Exception:
            pass


    def _draw_freehand_preview_cut(self, live_point=None):
        """Freehand preview for CUT SECTION – smooth flowing line in display coords."""
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D, vtkActor2D

        if len(self.drawing_points) < 1:
            return

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        # Remove previous cut-freehand actor
        if hasattr(self, "freehand_actor_cut") and self.freehand_actor_cut:
            try:
                renderer.RemoveActor2D(self.freehand_actor_cut)
            except Exception:
                pass
            self.freehand_actor_cut = None

        # Collect all points in display space
        # drawing_points are stored as (u, z) world; convert to display or store display directly
        # For simplicity, store display points on left press/mouse move for freehand in cut mode
        all_pts = list(self.drawing_points_display_cut) if hasattr(self, "drawing_points_display_cut") else []
        if live_point:
            all_pts.append(live_point)

        if len(all_pts) < 2:
            return

        pts = vtkPoints()
        for pt in all_pts:
            pts.InsertNextPoint(pt[0], pt[1], 0.0)

        lines = vtkCellArray()
        for i in range(len(all_pts) - 1):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i)
            lines.InsertCellPoint(i + 1)

        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)

        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)

        self.freehand_actor_cut = vtkActor2D()
        self.freehand_actor_cut.SetMapper(mapper)
        prop = self.freehand_actor_cut.GetProperty()
        prop.SetColor(1, 0.8, 0)   # Orange-yellow
        prop.SetLineWidth(2)       # Match thin look like cross-section
        prop.SetOpacity(0.8)       # Semi-transparent

        renderer.AddActor2D(self.freehand_actor_cut)
        self._safe_render(vtk_widget)


    def _draw_line_preview_cut(self, P1, P2):
        """
        ✅ PERFORMANCE FIX: Line preview for CUT SECTION.
        Reuses Actor2D — no RemoveActor/new objects per frame. Zero print spam.
        """
        from vtkmodules.vtkRenderingCore import vtkCoordinate, vtkPolyDataMapper2D, vtkActor2D

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_line_cut_pts") or self.line_actor_cut is None:
            self._line_cut_pts = vtkPoints()
            self._line_cut_pts.SetNumberOfPoints(2)
            _lines = vtkCellArray()
            _lines.InsertNextCell(2)
            _lines.InsertCellPoint(0)
            _lines.InsertCellPoint(1)
            self._line_cut_poly = vtkPolyData()
            self._line_cut_poly.SetPoints(self._line_cut_pts)
            self._line_cut_poly.SetLines(_lines)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._line_cut_poly)
            dc = vtkCoordinate(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.line_actor_cut = vtkActor2D()
            self.line_actor_cut.SetMapper(mapper)
            prop = self.line_actor_cut.GetProperty()
            prop.SetColor(1, 1, 0)
            prop.SetLineWidth(2)
            prop.SetOpacity(1.0)

            renderer.AddActor2D(self.line_actor_cut)

        if not renderer.HasViewProp(self.line_actor_cut):
            renderer.AddActor2D(self.line_actor_cut)
        self.line_actor_cut.VisibilityOn()

        # ── FAST COORDINATE UPDATE ───────────────────────────────────────────
        if not hasattr(self, "_line_cut_coord"):
            self._line_cut_coord = vtkCoordinate()
            self._line_cut_coord.SetCoordinateSystemToWorld()

        coord = self._line_cut_coord
        coord.SetValue(float(P1[0]), float(P1[1]), float(P1[2]))
        d1 = coord.GetComputedDisplayValue(renderer)
        coord.SetValue(float(P2[0]), float(P2[1]), float(P2[2]))
        d2 = coord.GetComputedDisplayValue(renderer)

        self._line_cut_pts.SetPoint(0, d1[0], d1[1], 0)
        self._line_cut_pts.SetPoint(1, d2[0], d2[1], 0)
        self._line_cut_pts.Modified()
        self._line_cut_poly.Modified()

        # Vertical dashed guides for above/below line
        tool = getattr(self.app, "active_classify_tool", None)
        if tool in ("above_line", "below_line"):
            self._draw_vertical_guides_cut(P1, P2, tool, renderer)
        # Render batched by caller


    def _draw_vertical_guides_cut(self, P1, P2, tool, renderer):
        """
        ✅ PERFORMANCE FIX: Vertical dashed guides for CUT SECTION above/below line.
        Reuses Actor2D — no RemoveActor/new objects per frame. Zero render call here.
        """
        from vtkmodules.vtkRenderingCore import vtkCoordinate, vtkPolyDataMapper2D, vtkActor2D

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_dotted_cut_pts") or self.dotted_actor_cut is None:
            self._dotted_cut_pts   = vtkPoints()
            self._dotted_cut_lines = vtkCellArray()
            self._dotted_cut_poly  = vtkPolyData()
            self._dotted_cut_poly.SetPoints(self._dotted_cut_pts)
            self._dotted_cut_poly.SetLines(self._dotted_cut_lines)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._dotted_cut_poly)
            dc = vtkCoordinate(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.dotted_actor_cut = vtkActor2D()
            self.dotted_actor_cut.SetMapper(mapper)
            prop = self.dotted_actor_cut.GetProperty()
            prop.SetColor(1, 1, 0)
            prop.SetLineWidth(2)
            prop.SetOpacity(0.8)

            renderer.AddActor2D(self.dotted_actor_cut)

        if not renderer.HasViewProp(self.dotted_actor_cut):
            renderer.AddActor2D(self.dotted_actor_cut)

        # ── FAST COORDINATE UPDATE ───────────────────────────────────────────
        if not hasattr(self, "_dotted_cut_coord"):
            self._dotted_cut_coord = vtkCoordinate()
            self._dotted_cut_coord.SetCoordinateSystemToWorld()

        coord = self._dotted_cut_coord
        coord.SetValue(float(P1[0]), float(P1[1]), float(P1[2]))
        p1_disp = coord.GetComputedDisplayValue(renderer)
        coord.SetValue(float(P2[0]), float(P2[1]), float(P2[2]))
        p2_disp = coord.GetComputedDisplayValue(renderer)

        try:
            win_size = renderer.GetRenderWindow().GetSize()
            height = win_size[1]
        except Exception:
            height = 600

        seg_len = 10
        gap = 6

        pts   = self._dotted_cut_pts
        lines = self._dotted_cut_lines
        pts.Reset()
        lines.Reset()
        idx = 0

        def fill(x_disp, y_start):
            nonlocal idx
            if tool == "above_line":
                y, y_end, step = y_start, height, seg_len + gap
                while y < y_end:
                    y2 = min(y + seg_len, y_end)
                    pts.InsertNextPoint(x_disp, y, 0)
                    pts.InsertNextPoint(x_disp, y2, 0)
                    lines.InsertNextCell(2)
                    lines.InsertCellPoint(idx); lines.InsertCellPoint(idx + 1)
                    idx += 2; y += step
            else:
                y, y_end, step = y_start, 0, seg_len + gap
                while y > y_end:
                    y2 = max(y - seg_len, y_end)
                    pts.InsertNextPoint(x_disp, y, 0)
                    pts.InsertNextPoint(x_disp, y2, 0)
                    lines.InsertNextCell(2)
                    lines.InsertCellPoint(idx); lines.InsertCellPoint(idx + 1)
                    idx += 2; y -= step

        fill(p1_disp[0], p1_disp[1])
        fill(p2_disp[0], p2_disp[1])

        if idx > 0:
            pts.Modified()
            self._dotted_cut_poly.Modified()
            self.dotted_actor_cut.VisibilityOn()
        else:
            self.dotted_actor_cut.VisibilityOff()
        # Render batched by caller

    def _draw_rectangle_preview_cut(self, P1, P2):
        """Rectangle preview for CUT SECTION."""
        from vtkmodules.vtkRenderingCore import vtkCoordinate, vtkPolyDataMapper2D, vtkActor2D
        from vtkmodules.vtkCommonDataModel import vtkPolyData
        from vtkmodules.vtkCommonCore import vtkPoints
        from vtkmodules.vtkCommonDataModel import vtkCellArray
        
        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        
        renderer = vtk_widget.renderer
        
        # Remove previous actor
        if hasattr(self, "rect_actor_cut") and self.rect_actor_cut:
            try:
                renderer.RemoveActor2D(self.rect_actor_cut)
            except:
                pass
            self.rect_actor_cut = None
        
        # World → display
        coord = vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        
        coord.SetValue(P1[0], P1[1], P1[2])
        d1 = coord.GetComputedDisplayValue(renderer)
        
        coord.SetValue(P2[0], P2[1], P2[2])
        d2 = coord.GetComputedDisplayValue(renderer)
        
        x1, y1 = d1[0], d1[1]
        x2, y2 = d2[0], d2[1]
        
        # Build rectangle in display coords
        pts = vtkPoints()
        pts.InsertNextPoint(x1, y1, 0)
        pts.InsertNextPoint(x2, y1, 0)
        pts.InsertNextPoint(x2, y2, 0)
        pts.InsertNextPoint(x1, y2, 0)
        pts.InsertNextPoint(x1, y1, 0)  # close
        
        lines = vtkCellArray()
        lines.InsertNextCell(5)
        for i in range(5):
            lines.InsertCellPoint(i)
        
        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)
        
        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        
        coordinate = vtkCoordinate()
        coordinate.SetCoordinateSystemToDisplay()
        mapper.SetTransformCoordinate(coordinate)
        
        self.rect_actor_cut = vtkActor2D()
        self.rect_actor_cut.SetMapper(mapper)
        self.rect_actor_cut.GetProperty().SetColor(1, 1, 0)
        self.rect_actor_cut.GetProperty().SetLineWidth(2)
        
        renderer.AddActor2D(self.rect_actor_cut)
        self._safe_render_from_renderer(renderer)
        print(f"📦 Rectangle preview (cut section) drawn")


    def _draw_brush_preview_cut(self, center, radius_world):
        """Brush preview for CUT SECTION - same as circle."""
        self._draw_circle_preview_cut(center, radius_world)


    
    def _draw_freehand_preview_cut(self, live_point=None):
        """Freehand preview for CUT SECTION – smooth flowing line in display coords."""
        from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D, vtkActor2D

        if len(self.drawing_points) < 1:
            return

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        # Remove previous cut-freehand actor
        if hasattr(self, "freehand_actor_cut") and self.freehand_actor_cut:
            try:
                renderer.RemoveActor2D(self.freehand_actor_cut)
            except Exception:
                pass
            self.freehand_actor_cut = None

        # Collect all points in display space
        # drawing_points are stored as (u, z) world; convert to display or store display directly
        # For simplicity, store display points on left press/mouse move for freehand in cut mode
        all_pts = list(self.drawing_points_display_cut) if hasattr(self, "drawing_points_display_cut") else []
        if live_point:
            all_pts.append(live_point)

        if len(all_pts) < 2:
            return

        pts = vtkPoints()
        for pt in all_pts:
            pts.InsertNextPoint(pt[0], pt[1], 0.0)

        lines = vtkCellArray()
        for i in range(len(all_pts) - 1):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i)
            lines.InsertCellPoint(i + 1)

        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)

        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)

        self.freehand_actor_cut = vtkActor2D()
        self.freehand_actor_cut.SetMapper(mapper)
        prop = self.freehand_actor_cut.GetProperty()
        prop.SetColor(1, 0.8, 0)   # Orange-yellow
        prop.SetLineWidth(2)       # Match thin look like cross-section
        prop.SetOpacity(0.8)       # Semi-transparent

        renderer.AddActor2D(self.freehand_actor_cut)
        self._safe_render(vtk_widget)


    def _draw_brush_cursor_cut(self, center, radius=1.0):
        """Brush cursor for CUT SECTION - dashed circle with crosshair."""
        from vtkmodules.vtkRenderingCore import vtkCoordinate, vtkPolyDataMapper2D, vtkActor2D
        from vtkmodules.vtkCommonCore import vtkPoints
        from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
        import numpy as np
        
        print(f"🖌️ _draw_brush_cursor_cut called: center={center}, radius={radius}")
        
        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            print("❌ No VTK widget for brush cursor (cut section)")
            return
        
        # ✅ CRITICAL FIX: Get renderer properly
        if hasattr(vtk_widget, 'renderer'):
            renderer = vtk_widget.renderer
        elif hasattr(vtk_widget, 'GetRenderer'):
            renderer = vtk_widget.GetRenderer()
        else:
            rw = vtk_widget.GetRenderWindow()
            renderer = rw.GetRenderers().GetFirstRenderer()
        
        print(f"   ✅ Got renderer: {renderer}")
        
        # Remove previous brush actor
        if hasattr(self, "brush_actor_cut") and self.brush_actor_cut:
            try:
                renderer.RemoveActor2D(self.brush_actor_cut)
                print("   🧹 Removed old brush_actor_cut")
            except Exception as e:
                print(f"   ⚠️ Could not remove old brush_actor_cut: {e}")
            self.brush_actor_cut = None
        
        cu, cv = center
        
        # Force minimum radius
        if radius < 0.05:
            radius = 0.1
        
        print(f"   📐 Creating brush shape: center=({cu:.2f}, {cv:.2f}), radius={radius:.2f}")
        
        # ========== CREATE BRUSH SHAPE IN WORLD COORDINATES ==========
        num_segments = 32
        brush_world = []
        
        # Outer circle (every other segment for dashed effect)
        for i in range(0, num_segments, 2):  # Skip every other segment
            angle1 = 2 * np.pi * i / num_segments
            angle2 = 2 * np.pi * (i + 1) / num_segments
            
            u1 = cu + radius * np.cos(angle1)
            v1 = cv + radius * np.sin(angle1)
            brush_world.append(self._view2d_to_world(u1, v1))
            
            u2 = cu + radius * np.cos(angle2)
            v2 = cv + radius * np.sin(angle2)
            brush_world.append(self._view2d_to_world(u2, v2))
        
        # Add crosshair lines
        crosshair_size = radius * 0.3  # 30% of radius
        
        # Horizontal crosshair
        brush_world.append(self._view2d_to_world(cu - crosshair_size, cv))
        brush_world.append(self._view2d_to_world(cu + crosshair_size, cv))
        
        # Vertical crosshair
        brush_world.append(self._view2d_to_world(cu, cv - crosshair_size))
        brush_world.append(self._view2d_to_world(cu, cv + crosshair_size))
        
        # Center dot (small circle)
        dot_segments = 8
        dot_radius = radius * 0.05
        for i in range(dot_segments + 1):
            angle = 2 * np.pi * i / dot_segments
            u = cu + dot_radius * np.cos(angle)
            v = cv + dot_radius * np.sin(angle)
            brush_world.append(self._view2d_to_world(u, v))
        
        print(f"   ✅ Created {len(brush_world)} world coordinate points")
        
        # ========== CONVERT TO DISPLAY COORDINATES ==========
        pts = vtkPoints()
        coord = vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        
        for point in brush_world:
            coord.SetValue(point[0], point[1], point[2])
            display_pos = coord.GetComputedDisplayValue(renderer)
            pts.InsertNextPoint(display_pos[0], display_pos[1], 0)
        
        print(f"   ✅ Converted to display coordinates")
        
        # ========== CREATE LINE SEGMENTS ==========
        lines = vtkCellArray()
        
        # Dashed circle (pairs of points)
        num_circle_points = num_segments  # Each dash is 2 points
        for i in range(0, num_circle_points, 2):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i)
            lines.InsertCellPoint(i + 1)
        
        # Horizontal crosshair
        h_start = num_circle_points
        lines.InsertNextCell(2)
        lines.InsertCellPoint(h_start)
        lines.InsertCellPoint(h_start + 1)
        
        # Vertical crosshair
        v_start = h_start + 2
        lines.InsertNextCell(2)
        lines.InsertCellPoint(v_start)
        lines.InsertCellPoint(v_start + 1)
        
        # Center dot
        dot_start = v_start + 2
        for i in range(dot_segments):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(dot_start + i)
            lines.InsertCellPoint(dot_start + i + 1)
        
        # ========== CREATE 2D ACTOR ==========
        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)
        
        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        
        coordinate = vtkCoordinate()
        coordinate.SetCoordinateSystemToDisplay()
        mapper.SetTransformCoordinate(coordinate)
        
        self.brush_actor_cut = vtkActor2D()
        self.brush_actor_cut.SetMapper(mapper)
        
        # Set properties - Yellow like other tools
        prop = self.brush_actor_cut.GetProperty()
        prop.SetColor(1, 1, 0)  # Yellow
        prop.SetLineWidth(3)
        prop.SetOpacity(0.9)
        
        # Add as 2D actor (always on top!)
        renderer.AddActor2D(self.brush_actor_cut)
        print(f"   ✅ Added brush_actor_cut to renderer")
        print(f"   📊 Renderer now has {renderer.GetActors2D().GetNumberOfItems()} 2D actors")
        
        # ✅ CRITICAL: Force immediate render
        try:
            if hasattr(vtk_widget, 'GetRenderWindow'):
                self._safe_render(vtk_widget)
            elif hasattr(vtk_widget, 'render'):
                self._safe_render_pyvista(vtk_widget)
            print(f"   ✅ Render called successfully")
        except Exception as e:
            print(f"   ⚠️ Render failed: {e}")
            
    def _draw_brush_cursor_cut_display(self, center_world, radius_px=20.0):
        """
        ✅ PERFORMANCE FIX: Brush cursor for CUT SECTION in DISPLAY coords.
        Reuses actor — zero allocation per frame after init.
        """
        from vtkmodules.vtkRenderingCore import vtkCoordinate, vtkPolyDataMapper2D, vtkActor2D

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        # Convert center to display coords
        coord = vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        coord.SetValue(float(center_world[0]), float(center_world[1]), float(center_world[2]))
        c_disp = coord.GetComputedDisplayValue(renderer)
        cx, cy = float(c_disp[0]), float(c_disp[1])
        pixel_radius = max(6.0, float(radius_px))

        num_segments = 32
        dot_segments = 8

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_brush_cut_pts") or self.brush_actor_cut is None:
            self._brush_cut_pts   = vtkPoints()
            self._brush_cut_lines = vtkCellArray()
            self._brush_cut_poly  = vtkPolyData()
            self._brush_cut_poly.SetPoints(self._brush_cut_pts)
            self._brush_cut_poly.SetLines(self._brush_cut_lines)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._brush_cut_poly)
            dc = vtkCoordinate(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.brush_actor_cut = vtkActor2D()
            self.brush_actor_cut.SetMapper(mapper)
            prop = self.brush_actor_cut.GetProperty()
            prop.SetColor(1, 1, 0)
            prop.SetLineWidth(3)
            prop.SetOpacity(0.9)

            renderer.AddActor2D(self.brush_actor_cut)

        if not renderer.HasViewProp(self.brush_actor_cut):
            renderer.AddActor2D(self.brush_actor_cut)
        self.brush_actor_cut.VisibilityOn()

        # ── FAST GEOMETRY UPDATE ─────────────────────────────────────────────
        pts   = self._brush_cut_pts
        lines = self._brush_cut_lines
        pts.Reset()
        lines.Reset()

        def add_seg(p0, p1):
            i0 = pts.InsertNextPoint(p0[0], p0[1], 0.0)
            i1 = pts.InsertNextPoint(p1[0], p1[1], 0.0)
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i0)
            lines.InsertCellPoint(i1)

        for i in range(0, num_segments, 2):
            a1 = 2.0 * np.pi * i / num_segments
            a2 = 2.0 * np.pi * (i + 1) / num_segments
            add_seg((cx + pixel_radius * np.cos(a1), cy + pixel_radius * np.sin(a1)),
                    (cx + pixel_radius * np.cos(a2), cy + pixel_radius * np.sin(a2)))

        ch = pixel_radius * 0.3
        add_seg((cx - ch, cy), (cx + ch, cy))
        add_seg((cx, cy - ch), (cx, cy + ch))

        dot_r = max(2.0, pixel_radius * 0.05)
        for i in range(dot_segments):
            a1 = 2.0 * np.pi * i / dot_segments
            a2 = 2.0 * np.pi * (i + 1) / dot_segments
            add_seg((cx + dot_r * np.cos(a1), cy + dot_r * np.sin(a1)),
                    (cx + dot_r * np.cos(a2), cy + dot_r * np.sin(a2)))

        pts.Modified()
        self._brush_cut_poly.Modified()
        # Render batched by caller
        
    def _draw_rectangle_cursor_cut_display(self, center_world, radius_px=20.0):
        """
        ✅ PERFORMANCE FIX: Rectangle brush cursor for CUT SECTION in DISPLAY coords.
        Reuses actor — zero allocation per frame after init.
        """
        from vtkmodules.vtkRenderingCore import vtkCoordinate, vtkPolyDataMapper2D, vtkActor2D

        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        coord = vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        coord.SetValue(float(center_world[0]), float(center_world[1]), float(center_world[2]))
        c_disp = coord.GetComputedDisplayValue(renderer)
        cx, cy = float(c_disp[0]), float(c_disp[1])
        dx = dy = max(6.0, float(radius_px))
        x_min, x_max = cx - dx, cx + dx
        y_min, y_max = cy - dy, cy + dy

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_rect_cut_pts") or self.brush_actor_cut is None:
            self._rect_cut_pts   = vtkPoints()
            self._rect_cut_lines = vtkCellArray()
            self._rect_cut_poly  = vtkPolyData()
            self._rect_cut_poly.SetPoints(self._rect_cut_pts)
            self._rect_cut_poly.SetLines(self._rect_cut_lines)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._rect_cut_poly)
            dc = vtkCoordinate(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.brush_actor_cut = vtkActor2D()
            self.brush_actor_cut.SetMapper(mapper)
            prop = self.brush_actor_cut.GetProperty()
            prop.SetColor(1, 1, 0)
            prop.SetLineWidth(3)
            prop.SetOpacity(0.9)

            renderer.AddActor2D(self.brush_actor_cut)

        if not renderer.HasViewProp(self.brush_actor_cut):
            renderer.AddActor2D(self.brush_actor_cut)
        self.brush_actor_cut.VisibilityOn()

        # ── FAST GEOMETRY UPDATE ─────────────────────────────────────────────
        pts   = self._rect_cut_pts
        lines = self._rect_cut_lines
        pts.Reset()
        lines.Reset()

        corners = [
            (x_min, y_min, 0.0),
            (x_max, y_min, 0.0),
            (x_max, y_max, 0.0),
            (x_min, y_max, 0.0),
            (x_min, y_min, 0.0),
        ]
        for c in corners:
            pts.InsertNextPoint(*c)
        for i in range(1, len(corners)):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i - 1)
            lines.InsertCellPoint(i)

        pts.Modified()
        self._rect_cut_poly.Modified()
        # Render batched by caller

    # Add this helper method to ClassificationInteractor class

    def _transform_cut_to_world_rect(self, P1, P2):
        """
        Transform rectangle coordinates from cut section's local space 
        to global world space for classification.
        
        Returns: (u_min, u_max, z_min, z_max) in world coordinates
        """
        # Check if we're in cut section mode
        is_cut_section = getattr(self, 'is_cut_section', False) or \
                        (hasattr(self.app, 'cut_section_controller') and
                        getattr(self.app.cut_section_controller, 'is_cut_view_active', False))
        
        if not is_cut_section:
            # Normal cross-section - use coordinates as-is
            u1, z1 = P1[0], P1[2]
            u2, z2 = P2[0], P2[2]
            return (min(u1, u2), max(u1, u2), min(z1, z2), max(z1, z2))
        
        # ✅ CUT SECTION: Transform using cutting plane basis
        try:
            cut_ctrl = self.app.cut_section_controller
            
            # Get the cutting plane's coordinate system
            origin = np.array(cut_ctrl.plane_origin)  # Cut plane origin in world space
            normal = np.array(cut_ctrl.plane_normal)  # Cut plane normal (perpendicular to view)
            
            # Build the cut section's local coordinate system
            # u_axis: along the cutting direction (horizontal in cut view)
            # v_axis: perpendicular to normal and u_axis (vertical in cut view)
            # normal: points "out of screen" in cut view
            
            # Get u_axis from the plane definition
            if hasattr(cut_ctrl, 'u_axis'):
                u_axis = np.array(cut_ctrl.u_axis)
            else:
                # Fallback: compute perpendicular to normal
                if abs(normal[2]) < 0.9:
                    u_axis = np.cross(normal, [0, 0, 1])
                else:
                    u_axis = np.cross(normal, [0, 1, 0])
            
            u_axis = u_axis / np.linalg.norm(u_axis)
            v_axis = np.cross(normal, u_axis)
            v_axis = v_axis / np.linalg.norm(v_axis)
            
            # Transform P1 and P2 from local cut coordinates to world coordinates
            # Local coords: (u, 0, z) where u is horizontal, z is vertical in cut view
            # World coords: origin + u*u_axis + z*v_axis
            
            def local_to_world(p):
                """Convert (u, y, z) in cut section to (x, y, z) in world"""
                u_local = p[0]  # Horizontal in cut view
                z_local = p[2]  # Vertical in cut view
                
                # Transform to world space
                world_pt = origin + u_local * u_axis + z_local * v_axis
                return world_pt
            
            # Transform both corners
            world_p1 = local_to_world(P1)
            world_p2 = local_to_world(P2)
            
            # Now we need to define the rectangle in the cutting plane's 2D space
            # that corresponds to the 3D world rectangle
            
            # Project world corners back to local u,z coordinates
            u1 = np.dot(world_p1 - origin, u_axis)
            z1 = np.dot(world_p1 - origin, v_axis)
            u2 = np.dot(world_p2 - origin, u_axis)
            z2 = np.dot(world_p2 - origin, v_axis)
            
            print(f"   🔄 Cut section rect transform:")
            print(f"      Local: P1=({P1[0]:.2f}, {P1[2]:.2f}), P2=({P2[0]:.2f}, {P2[2]:.2f})")
            print(f"      World: u1={u1:.2f}, z1={z1:.2f}, u2={u2:.2f}, z2={z2:.2f}")
            
            return (min(u1, u2), max(u1, u2), min(z1, z2), max(z1, z2))
            
        except Exception as e:
            print(f"   ⚠️ Cut section transform failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback to direct coordinates
            u1, z1 = P1[0], P1[2]
            u2, z2 = P2[0], P2[2]
            return (min(u1, u2), max(u1, u2), min(z1, z2), max(z1, z2))

    def _partial_refresh_main_view(self, changed_indices):
        """Fast main-view color update (no full rebuild)."""
        try:
            from gui.performance_optimizations import fast_update_colors_optimized
            fast_update_colors_optimized(self.app, changed_mask=changed_indices)
            print(f"⚡ Partial main-view refresh: {len(changed_indices)} points updated")
        except Exception as e:
            print(f"❌ Partial main-view refresh failed: {e}")

    def clear_guides(self):
        """Clear only temporary visual guides (rubber-band line during drawing)"""
        for actor in self.guide_actors:
            self.renderer.RemoveActor(actor)
        self.guide_actors.clear()
    
    def clear_all(self):
        """Clear everything including saved cross-sections (use for reset/clear all)"""
        self.clear_guides()
        for actor in self.section_actors:
            self.renderer.RemoveActor(actor)
        self.section_actors.clear()
    
    def add_section(self, actor):
        """Add a permanent cross-section actor"""
        self.section_actors.append(actor)
        self.renderer.AddActor(actor)
    
    def add_guide(self, actor):
        """Add a temporary guide actor (like rubber-band line)"""
        self.guide_actors.append(actor)
        self.renderer.AddActor(actor)
        
    # Add this method to ClassificationInteractor class:

    def _classify_brush_with_shape(self, center, radius, to_class, section_mask, section_points):
        """
        Classify points using brush with configurable shape (circle or rectangle).
        """
        from ..classification_tools import classify_brush, classify_rectangle
        
        # Get brush shape from app
        brush_shape = getattr(self.app, "brush_shape", "circle")
        
        if brush_shape == "rectangle":
            # Convert center + radius to rectangle bounds
            u, z = center
            u_min = u - radius
            u_max = u + radius
            z_min = z - radius
            z_max = z + radius
            
            print(f"🖌️ Rectangle brush: ({u_min:.2f}, {u_max:.2f}, {z_min:.2f}, {z_max:.2f})")
            
            # Use rectangle classification
            classify_rectangle(
                self.app,
                (u_min, u_max, z_min, z_max),
                self.app.from_classes,
                to_class,
                section_mask,
                section_points,
                None
            )
        else:
            # Default circle brush
            print(f"🖌️ Circle brush: center=({center[0]:.2f}, {center[1]:.2f}), radius={radius:.2f}")
            
            classify_brush(
                self.app,
                center,
                radius,
                self.app.from_classes,
                to_class,
                section_mask,
                section_points,
                None
            )
                
    def _draw_rectangle_cursor(self, center, radius):
        """
        ✅ PERFORMANCE FIX: Rectangle brush cursor in DISPLAY pixels (zoom invariant).
        Reuses actor — zero allocation per frame after init.
        """
        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            return
        renderer = vtk_widget.renderer

        x, y = self.interactor.GetEventPosition()
        r = max(float(radius), 3.0)
        x_min, x_max = x - r, x + r
        y_min, y_max = y - r, y + r

        # ── ONE-TIME PIPELINE INIT ───────────────────────────────────────────
        if not hasattr(self, "_rect_cursor_pts") or self.brush_actor is None:
            from vtkmodules.vtkRenderingCore import vtkPolyDataMapper2D, vtkActor2D, vtkCoordinate as _C

            self._rect_cursor_pts   = vtkPoints()
            self._rect_cursor_lines = vtkCellArray()
            self._rect_cursor_poly  = vtkPolyData()
            self._rect_cursor_poly.SetPoints(self._rect_cursor_pts)
            self._rect_cursor_poly.SetLines(self._rect_cursor_lines)

            mapper = vtkPolyDataMapper2D()
            mapper.SetInputData(self._rect_cursor_poly)
            dc = _C(); dc.SetCoordinateSystemToDisplay()
            mapper.SetTransformCoordinate(dc)

            self.brush_actor = vtkActor2D()
            self.brush_actor.SetMapper(mapper)
            prop = self.brush_actor.GetProperty()
            prop.SetColor(1, 1, 0)
            prop.SetLineWidth(3)
            prop.SetOpacity(0.9)

            renderer.AddActor2D(self.brush_actor)

        if not renderer.HasViewProp(self.brush_actor):
            renderer.AddActor2D(self.brush_actor)
        self.brush_actor.VisibilityOn()

        # ── FAST GEOMETRY UPDATE ─────────────────────────────────────────────
        pts   = self._rect_cursor_pts
        lines = self._rect_cursor_lines
        pts.Reset()
        lines.Reset()

        corners = [
            (x_min, y_min, 0.0),
            (x_max, y_min, 0.0),
            (x_max, y_max, 0.0),
            (x_min, y_max, 0.0),
            (x_min, y_min, 0.0),
        ]
        for c in corners:
            pts.InsertNextPoint(*c)
        for i in range(1, len(corners)):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i - 1)
            lines.InsertCellPoint(i)

        pts.Modified()
        self._rect_cursor_poly.Modified()
        # Render batched by caller
        
    def _draw_rectangle_cursor_cut(self, center, radius):
        """Draw rectangle cursor for brush tool in CUT SECTION"""
        from vtkmodules.vtkRenderingCore import vtkCoordinate, vtkPolyDataMapper2D, vtkActor2D
        from vtkmodules.vtkCommonCore import vtkPoints
        from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData
        
        print(f"■ _draw_rectangle_cursor_cut called: center={center}, radius={radius}")
        
        vtk_widget = self._get_active_vtk_widget()
        if vtk_widget is None:
            print("❌ No VTK widget for rectangle cursor (cut section)")
            return
        
        # ✅ CRITICAL FIX: Get renderer properly
        if hasattr(vtk_widget, 'renderer'):
            renderer = vtk_widget.renderer
        elif hasattr(vtk_widget, 'GetRenderer'):
            renderer = vtk_widget.GetRenderer()
        else:
            rw = vtk_widget.GetRenderWindow()
            renderer = rw.GetRenderers().GetFirstRenderer()
        
        print(f"   ✅ Got renderer: {renderer}")
        
        # Remove previous brush actor
        if hasattr(self, "brush_actor_cut") and self.brush_actor_cut:
            try:
                renderer.RemoveActor2D(self.brush_actor_cut)
            except Exception:
                pass
            self.brush_actor_cut = None
        
        cu, cv = center
        
        # Force minimum radius
        if radius < 0.05:
            radius = 0.1
        
        # Build rectangle corners in world space
        u_min, u_max = cu - radius, cu + radius
        v_min, v_max = cv - radius, cv + radius
        
        corners_world = [
            self._view2d_to_world(u_min, v_min),
            self._view2d_to_world(u_max, v_min),
            self._view2d_to_world(u_max, v_max),
            self._view2d_to_world(u_min, v_max),
            self._view2d_to_world(u_min, v_min)  # Close the rectangle
        ]
        
        # Convert to display coordinates
        pts = vtkPoints()
        coord = vtkCoordinate()
        coord.SetCoordinateSystemToWorld()
        
        for point in corners_world:
            coord.SetValue(point[0], point[1], point[2])
            display_pos = coord.GetComputedDisplayValue(renderer)
            pts.InsertNextPoint(display_pos[0], display_pos[1], 0)
        
        # Create line segments
        lines = vtkCellArray()
        for i in range(len(corners_world) - 1):
            lines.InsertNextCell(2)
            lines.InsertCellPoint(i)
            lines.InsertCellPoint(i + 1)
        
        # Create polydata
        poly = vtkPolyData()
        poly.SetPoints(pts)
        poly.SetLines(lines)
        
        # Create 2D mapper
        mapper = vtkPolyDataMapper2D()
        mapper.SetInputData(poly)
        
        coordinate = vtkCoordinate()
        coordinate.SetCoordinateSystemToDisplay()
        mapper.SetTransformCoordinate(coordinate)
        
        # Create 2D actor
        self.brush_actor_cut = vtkActor2D()
        self.brush_actor_cut.SetMapper(mapper)
        
        # Set properties - Yellow like other tools
        prop = self.brush_actor_cut.GetProperty()
        prop.SetColor(1, 1, 0)  # Yellow
        prop.SetLineWidth(3)
        prop.SetOpacity(0.9)
        
        # Add as 2D actor (always on top!)
        renderer.AddActor2D(self.brush_actor_cut)
        print(f"   ✅ Added brush_actor_cut (rectangle) to renderer")
        
        # ✅ CRITICAL: Force immediate render
        try:
            if hasattr(vtk_widget, 'GetRenderWindow'):
                self._safe_render(vtk_widget)
            elif hasattr(vtk_widget, 'render'):
                self._safe_render_pyvista(vtk_widget)
            print(f"   ✅ Render called successfully")
        except Exception as e:
            print(f"   ⚠️ Render failed: {e}")
            
    def _sync_main_view_palette_weights(self):
        """
        ✅ OPTIMIZED: Only syncs weights when they actually change.
        Uses WeightCache to detect real changes.
        """
        from gui.classification_state import get_weight_cache
        
        try:
            dialog = getattr(self.app, 'display_mode_dialog', None)
            if not dialog or not hasattr(dialog, 'view_palettes'):
                return
            
            weight_cache = get_weight_cache()
            
            # Check if any weights actually changed
            if not weight_cache.has_changes(dialog.view_palettes):
                # No changes - skip sync entirely
                return
            
            # Get only changed weights
            changes = weight_cache.get_changed_weights(dialog.view_palettes)
            
            if not changes:
                return
            
            total_changes = sum(len(v) for v in changes.values())
            print(f"   🔄 Syncing {total_changes} changed weights (delta-based)")
            
            # Update only changed weights
            if not hasattr(self.app, 'class_palette'):
                self.app.class_palette = {}
            
            for slot_idx, slot_changes in changes.items():
                for class_code, new_weight in slot_changes.items():
                    if class_code not in self.app.class_palette:
                        # Copy from dialog palette
                        if class_code in dialog.view_palettes.get(slot_idx, {}):
                            self.app.class_palette[class_code] = dict(
                                dialog.view_palettes[slot_idx][class_code]
                            )
                        else:
                            self.app.class_palette[class_code] = {'weight': new_weight}
                    else:
                        self.app.class_palette[class_code]['weight'] = new_weight
            
            # Update cache
            weight_cache.update_cache(dialog.view_palettes)
            
        except Exception as e:
            print(f"⚠️ Delta weight sync failed: {e}")    

    def force_main_view_refresh_with_weights(self):
        """
        ✅ UNIFIED ACTOR: Force weight sync and GPU uniform push.
        Replaces the old full-actor-wipe rebuild — no actor destroy/create needed.
        """
        print(f"\n{'='*60}")
        print(f"💥 FORCING MAIN VIEW WEIGHT REFRESH (UNIFIED GPU POKE)")
        print(f"{'='*60}")

        try:
            self._sync_main_view_palette_weights()

            from gui.unified_actor_manager import sync_palette_to_gpu, is_unified_actor_ready
            app = self.app

            if is_unified_actor_ready(app):
                palette    = getattr(app, 'class_palette', {})
                border_pct = float(getattr(app, 'point_border_percent', 0) or 0.0)
                sync_palette_to_gpu(app, 0, palette, border_pct, render=True)
                print(f"   ✅ Unified GPU poke complete — weights applied without rebuild")
            else:
                # Unified actor not built yet — do a one-time build
                print(f"   ⚠️ Unified actor not ready — triggering build")
                from gui.class_display import update_class_mode
                update_class_mode(app, force_refresh=True)

            print(f"{'='*60}\n")

        except Exception as e:
            print(f"❌ Force refresh failed: {e}")
            import traceback
            traceback.print_exc()
                  
    def _update_brush_preview_colors(self):
        """
        ✅ UNIFIED ACTOR: Instant brush preview via direct _naksha_rgb_ptr write.
        ✅ FIX: Maps global mask → LOD local indices before writing to GPU buffer.
        """
        try:
            if not hasattr(self, '_brush_accumulated_mask'):
                return
            if not np.any(self._brush_accumulated_mask):
                return

            to_class = getattr(self.app, "to_class", None)
            if to_class is None:
                return

            palette = getattr(self.app, "class_palette", {})
            if to_class not in palette:
                return

            target_color = np.array(palette[to_class].get("color", (255, 255, 0)),
                                    dtype=np.uint8)

            if self.app.display_mode != "class":
                return

            # ✅ UNIFIED ACTOR path: write directly into shared GPU colour buffer
            from gui.unified_actor_manager import _get_unified_actor
            actor = _get_unified_actor(self.app)
            if actor is None:
                return

            rgb_ptr = getattr(actor, '_naksha_rgb_ptr', None)
            if rgb_ptr is None or not rgb_ptr.flags.writeable:
                return

            # ✅ FIX: Map global mask through LOD indices
            # rgb_ptr only has len(_main_global_indices) entries, not len(xyz)
            global_indices = getattr(self.app, '_main_global_indices', None)
            if global_indices is not None:
                local_changed = np.where(self._brush_accumulated_mask[global_indices])[0]
            else:
                local_changed = np.where(self._brush_accumulated_mask)[0]

            if len(local_changed) == 0:
                return

            rgb_ptr[local_changed] = target_color

            vtk_ca = getattr(actor, '_naksha_vtk_array', None)
            if vtk_ca is not None:
                vtk_ca.Modified()
            from gui.unified_actor_manager import _mark_actor_dirty
            _mark_actor_dirty(actor)

            try:
                self._safe_render_pyvista(self.app.vtk_widget)
            except Exception:
                pass

        except Exception:
            # Preview is optional — never break classification on preview failure
            pass
        
    def _build_spatial_index_for_brush(self):
        """
        ✅ MICROSTATION GRID INDEX: Vectorized build for O(1) brush lookup.
        Uses numpy sorting instead of Python dict append loop.
        Builds in ~200ms instead of 5400ms.
        """
        import time
        start = time.time()
        
        xyz = self.app.data["xyz"]
        n_pts = len(xyz)
        
        # Calculate grid bounds
        x_min, x_max = float(xyz[:, 0].min()), float(xyz[:, 0].max())
        y_min, y_max = float(xyz[:, 1].min()), float(xyz[:, 1].max())
        
        # Use finer grid for better locality (100x100 instead of 50x50)
        grid_size = 100
        x_range = x_max - x_min + 1e-6
        y_range = y_max - y_min + 1e-6
        x_step = x_range / grid_size
        y_step = y_range / grid_size
        
        # Vectorized cell assignment (no Python loop)
        x_cells = np.clip(((xyz[:, 0] - x_min) / x_step).astype(np.int32), 0, grid_size - 1)
        y_cells = np.clip(((xyz[:, 1] - y_min) / y_step).astype(np.int32), 0, grid_size - 1)
        
        # Flat cell key: cell_id = y * grid_size + x
        cell_ids = y_cells * grid_size + x_cells
        
        # Sort by cell_id — groups all points in the same cell together
        sort_order = np.argsort(cell_ids, kind='mergesort')
        sorted_cells = cell_ids[sort_order]
        
        # Find boundaries between cells using np.searchsorted
        unique_cells, cell_starts = np.unique(sorted_cells, return_index=True)
        cell_ends = np.append(cell_starts[1:], n_pts)
        
        # Build lookup: cell_id → slice of sort_order array
        self._brush_spatial_index = {}
        self._brush_sort_order = sort_order
        for i in range(len(unique_cells)):
            cid = int(unique_cells[i])
            cx = cid % grid_size
            cy = cid // grid_size
            self._brush_spatial_index[(cx, cy)] = (int(cell_starts[i]), int(cell_ends[i]))
        
        # Store grid parameters
        self._brush_grid_params = {
            'x_min': x_min, 'y_min': y_min,
            'x_step': x_step, 'y_step': y_step,
            'grid_size': grid_size
        }
        self._brush_grid_size = grid_size
        
        build_time = (time.time() - start) * 1000
        print(f"   ⚡ Spatial index built in {build_time:.0f}ms ({grid_size}x{grid_size} grid, {n_pts:,} pts)")
        self._last_brush_build_time = time.time()
        
        
    def _get_points_in_radius_fast(self, center_x, center_y, radius):
        """
        ✅ MICROSTATION O(1) GRID LOOKUP: Get points within radius.
        Uses sort-order slicing — zero Python loops for candidate collection.
        Typical: 0.1-0.5ms per stamp (vs 10-50ms for full scan).
        """
        if self._brush_spatial_index is None or time.time() - self._last_brush_build_time > 60:
            self._build_spatial_index_for_brush()
        
        params = self._brush_grid_params
        grid_size = params['grid_size']
        sort_order = self._brush_sort_order
        
        # Calculate which grid cells overlap with the brush circle
        cell_x_min = max(0, int((center_x - radius - params['x_min']) / params['x_step']))
        cell_x_max = min(grid_size - 1, int((center_x + radius - params['x_min']) / params['x_step']))
        cell_y_min = max(0, int((center_y - radius - params['y_min']) / params['y_step']))
        cell_y_max = min(grid_size - 1, int((center_y + radius - params['y_min']) / params['y_step']))
        
        # Collect candidate point indices from overlapping cells via sort_order slices
        slices = []
        for cx in range(cell_x_min, cell_x_max + 1):
            for cy in range(cell_y_min, cell_y_max + 1):
                cell_range = self._brush_spatial_index.get((cx, cy))
                if cell_range is not None:
                    s, e = cell_range
                    slices.append(sort_order[s:e])
        
        if not slices:
            return np.array([], dtype=np.int64)
        
        candidates = np.concatenate(slices)
        
        # Fast vectorized distance check on candidates only
        xyz = self.app.data["xyz"]
        pts = xyz[candidates]
        dx = pts[:, 0] - center_x
        dy = pts[:, 1] - center_y
        within = candidates[(dx * dx + dy * dy) <= (radius * radius)]
        return within
    
    def _interpolate_brush_stroke(self, p1, p2, radius):
        """
        ✅ SMOOTH STROKES: Interpolate between positions for gap-free painting
        """
        x1, y1 = p1
        x2, y2 = p2
        
        # Calculate distance
        dx = x2 - x1
        dy = y2 - y1
        dist = np.sqrt(dx*dx + dy*dy)
        
        # Calculate number of interpolation steps
        step_size = self._brush_interpolation_step * radius
        num_steps = max(1, int(dist / step_size))
        
        # Generate interpolated positions
        positions = []
        for i in range(num_steps + 1):
            t = i / num_steps
            x = x1 + dx * t
            y = y1 + dy * t
            positions.append((x, y))
        
        return positions
    
    
    def _get_points_in_box_fast(self, x_min, x_max, y_min, y_max):
        """
        ✅ FAST: Get points in rectangle using spatial index
        """
        # Rebuild index if needed
        if (self._brush_spatial_index is None or 
            time.time() - self._last_brush_build_time > 60):
            self._build_spatial_index_for_brush()
        
        params = self._brush_grid_params
        grid_size = params['grid_size']
        
        # Calculate overlapping grid cells
        cell_x_min = int((x_min - params['x_min']) / params['x_step'])
        cell_x_max = int((x_max - params['x_min']) / params['x_step'])
        cell_y_min = int((y_min - params['y_min']) / params['y_step'])
        cell_y_max = int((y_max - params['y_min']) / params['y_step'])
        
        # Clip to grid bounds
        cell_x_min = max(0, cell_x_min)
        cell_x_max = min(grid_size - 1, cell_x_max)
        cell_y_min = max(0, cell_y_min)
        cell_y_max = min(grid_size - 1, cell_y_max)
        
        # Collect candidates
        candidate_indices = []
        for cx in range(cell_x_min, cell_x_max + 1):
            for cy in range(cell_y_min, cell_y_max + 1):
                cell = (cx, cy)
                if cell in self._brush_spatial_index:
                    candidate_indices.extend(self._brush_spatial_index[cell])
        
        if not candidate_indices:
            return np.array([], dtype=np.int64)
        
        # Precise box check on candidates
        xyz = self.app.data["xyz"]
        candidates = np.array(candidate_indices, dtype=np.int64)
        pts = xyz[candidates]
        
        in_box = (
            (pts[:, 0] >= x_min) & (pts[:, 0] <= x_max) &
            (pts[:, 1] >= y_min) & (pts[:, 1] <= y_max)
        )
        
        return candidates[in_box]

    def on_right_press(self, obj, evt):
        """Right-click handler for cross-section views."""
        if self._is_main_view():
            try:
                self.style.OnRightButtonDown()
            except:
                pass
            return
        
        x, y = self.interactor.GetEventPosition()
        
        try:
            pt = self._pick_world_point(x, y)
            
            # ✅ ADD: Set flag to trigger fly-to after next classification
            self._fly_to_after_classify = pt
            
        except Exception as e:
            print(f"⚠️ Right-click handler failed: {e}")


    def _execute_fly_to(self, world_point):
        """Execute fly-to with delay"""
        from PySide6.QtCore import QTimer
        
        # Clear the flag (user chose manual fly-to)
        self._fly_to_after_classify = None
        
        # Add delay to let any pending refresh complete
        QTimer.singleShot(200, lambda: self._fly_to_main_view(world_point))

    def _fly_to_main_view(self, world_point):
        """
        Smoothly fly camera to classification location in main view.
        Shows visual indicator at target location.
        """
        print(f"\n{'='*60}")
        print(f"✈️ FLYING TO CLASSIFICATION LOCATION")
        print(f"{'='*60}")
        print(f"   Target (raw): ({world_point[0]:.2f}, {world_point[1]:.2f}, {world_point[2]:.2f})")
        
        # ✅ CRITICAL FIX: Transform cross-section coordinates to global world coordinates
        try:
            # Check if we're in a cross-section view
            active_view = self._get_view_index_from_interactor()
            
            if active_view is not None:
                # We're in a cross-section - need to transform coordinates
                print(f"   🔄 Transforming from cross-section View {active_view + 1} coordinates...")
                
                # Get section data to find the actual world coordinates
                core_mask = getattr(self.app, f"section_{active_view}_core_mask", None)
                buffer_mask = getattr(self.app, f"section_{active_view}_buffer_mask", None)
                
                if core_mask is not None:
                    # Combine masks
                    if buffer_mask is not None:
                        section_mask = core_mask | buffer_mask
                    else:
                        section_mask = core_mask
                    
                    # Get the actual 3D points in this section
                    section_xyz = self.app.data["xyz"][section_mask]
                    
                    print(f"   📊 Section has {len(section_xyz)} points")
                    
                    # Get the 2D coordinates we clicked on (u, z in cross-section view)
                    u_clicked = world_point[0]
                    z_clicked = world_point[2]
                    
                    print(f"   🎯 Clicked at: u={u_clicked:.2f}, z={z_clicked:.2f}")
                    
                    # Get view mode to know which coordinates to use
                    view_mode = getattr(self.app, 'cross_view_mode', 'side')
                    print(f"   📐 View mode: {view_mode}")
                    
                    # Project section points to 2D (same way classification does it)
                    if view_mode == 'front':
                        # Front view: u is Y coordinate, z is Z coordinate
                        section_2d = np.column_stack([section_xyz[:, 1], section_xyz[:, 2]])
                        print(f"   📐 Using front view projection (Y, Z)")
                    else:
                        # Side view (default): u is X coordinate, z is Z coordinate
                        section_2d = np.column_stack([section_xyz[:, 0], section_xyz[:, 2]])
                        print(f"   📐 Using side view projection (X, Z)")
                    
                    # Find the closest point in the section to where we clicked
                    clicked_2d = np.array([u_clicked, z_clicked])
                    distances = np.sum((section_2d - clicked_2d) ** 2, axis=1)
                    closest_idx = np.argmin(distances)
                    closest_distance = np.sqrt(distances[closest_idx])
                    
                    # Get the actual 3D world coordinates of the closest point
                    world_point = tuple(section_xyz[closest_idx])
                    
                    print(f"   ✅ Found closest point in section:")
                    print(f"      2D distance: {closest_distance:.2f}")
                    print(f"      World coords: ({world_point[0]:.2f}, {world_point[1]:.2f}, {world_point[2]:.2f})")
                else:
                    print(f"   ⚠️ No section mask for View {active_view + 1}")
            
            # Validate against data bounds
            xyz = self.app.data["xyz"]
            x_min, x_max = xyz[:, 0].min(), xyz[:, 0].max()
            y_min, y_max = xyz[:, 1].min(), xyz[:, 1].max()
            z_min, z_max = xyz[:, 2].min(), xyz[:, 2].max()
            
            print(f"   📊 Data bounds:")
            print(f"      X: {x_min:.2f} to {x_max:.2f}")
            print(f"      Y: {y_min:.2f} to {y_max:.2f}")
            print(f"      Z: {z_min:.2f} to {z_max:.2f}")
            
            # Check if transformed point is within reasonable bounds
            if (world_point[0] < x_min or world_point[0] > x_max or
                world_point[1] < y_min or world_point[1] > y_max):
                
                print(f"   ⚠️ Warning: Target may be outside main data bounds")
                print(f"      X: {world_point[0]:.2f} (bounds: {x_min:.2f} to {x_max:.2f})")
                print(f"      Y: {world_point[1]:.2f} (bounds: {y_min:.2f} to {y_max:.2f})")
        
        except Exception as e:
            print(f"   ⚠️ Coordinate transformation failed: {e}")
            import traceback
            traceback.print_exc()
            # Don't return - still try to fly to the point even if transformation failed
        
        try:
            main_plotter = self.app.vtk_widget
            
            # Get current camera
            if hasattr(main_plotter, 'renderer'):
                renderer = main_plotter.renderer
                cam = renderer.GetActiveCamera()
            elif hasattr(main_plotter, 'camera'):
                cam = main_plotter.camera
            else:
                print("   ❌ No camera in main view")
                return
            
            # Calculate new camera position
            target_x, target_y, target_z = world_point
            
            # Get current camera distance to maintain zoom level
            current_pos = np.array(cam.GetPosition())
            current_focal = np.array(cam.GetFocalPoint())
            current_distance = np.linalg.norm(current_pos - current_focal)
            
            # New focal point is the target location at its actual elevation
            new_focal_point = np.array([target_x, target_y, target_z])
            
            # For main view, ALWAYS use top-down view (Z-axis looking down)
            # Position camera above the target at current distance
            view_direction = np.array([0, 0, 1])  # Always look straight down in main view
            new_position = new_focal_point + view_direction * current_distance
                        
            print(f"   📷 Current focal: {current_focal}")
            print(f"   📷 New focal: {new_focal_point}")
            print(f"   📷 New position: {new_position}")
            print(f"   📷 Distance: {current_distance:.2f}")

            # ✅ FIX: Delay animation to let refresh complete
            from PySide6.QtCore import QTimer

            def start_animation():
                self._animate_camera_to(
                    main_plotter,
                    new_position,
                    new_focal_point,
                    duration_ms=800
                )

            # Wait 100ms for any pending refreshes to complete
            QTimer.singleShot(100, start_animation)
            
            # Show visual indicator at target
            self._show_target_indicator(world_point)
            
            # Update status bar
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage(
                    f"✈️ Flew to ({target_x:.1f}, {target_y:.1f}, {target_z:.1f})",
                    3000
                )
            
            print(f"   ✅ Camera animated to target")
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"   ❌ Fly-to failed: {e}")
            import traceback
            traceback.print_exc()

    def _animate_camera_to(self, plotter, new_pos, new_focal, duration_ms=800):
        """
        Smooth camera animation using Qt timer.
        Uses easing curve for natural motion.
        """
        from PySide6.QtCore import QTimer
        import numpy as np
        self.app._fly_to_in_progress = True
        
        try:
            # Get camera
            if hasattr(plotter, 'renderer'):
                cam = plotter.renderer.GetActiveCamera()
            elif hasattr(plotter, 'camera'):
                cam = plotter.camera
            else:
                print("   ⚠️ No camera found for animation")
                return
            
            # Store start state
            start_pos = np.array(cam.GetPosition())
            start_focal = np.array(cam.GetFocalPoint())
            
            end_pos = np.array(new_pos)
            end_focal = np.array(new_focal)
            
            # Animation parameters
            steps = 30
            step_duration = duration_ms // steps
            
            # Easing function (ease in-out cubic)
            def ease_in_out_cubic(t):
                """Smooth easing curve"""
                if t < 0.5:
                    return 4 * t * t * t
                else:
                    p = 2 * t - 2
                    return 1 + p * p * p / 2
            
            current_step = [0]  # Mutable container for closure
            
            def animate_step():
                try:
                    t = current_step[0] / steps
                    eased_t = ease_in_out_cubic(t)
                    
                    # Interpolate position and focal point
                    interp_pos = start_pos + (end_pos - start_pos) * eased_t
                    interp_focal = start_focal + (end_focal - start_focal) * eased_t
                    
                    # Update camera
                    cam.SetPosition(interp_pos.tolist())
                    cam.SetFocalPoint(interp_focal.tolist())
                    
                    # Render
                    if hasattr(plotter, 'GetRenderWindow'):
                        self._safe_render(plotter)
                    elif hasattr(plotter, 'render'):
                        self._safe_render_pyvista(plotter)
                    
                    current_step[0] += 1
                    
                    # Continue animation
                    if current_step[0] <= steps:
                        QTimer.singleShot(step_duration, animate_step)
                    else:
                        print("   ✅ Animation complete")
                        self.app._fly_to_in_progress = False
                        
                except Exception as e:
                    print(f"   ⚠️ Animation step failed: {e}")
            
            # Start animation
            animate_step()
            
        except Exception as e:
            print(f"   ⚠️ Animation setup failed: {e}")
            # Fallback: instant camera move
            try:
                cam.SetPosition(new_pos.tolist())
                cam.SetFocalPoint(new_focal.tolist())
                if hasattr(plotter, 'render'):
                    self._safe_render_pyvista(plotter)
            except:
                pass

    def _show_target_indicator(self, world_point):
        """
        Flash MULTIPLE visual indicators at target location.
        Creates sphere + crosshair + rings + label for unmistakable visibility.
        """
        try:
            main_plotter = self.app.vtk_widget
            import pyvista as pv
            
            # Determine appropriate radius based on data bounds
            xyz = self.app.data.get("xyz")
            if xyz is not None:
                data_range = np.max(xyz, axis=0) - np.min(xyz, axis=0)
                base_radius = np.mean(data_range) * 0.008  # Smaller radius (0.8%)
            else:
                base_radius = 1.5
            
            print(f"   ✨ Creating multi-part indicator (base_radius={base_radius:.2f})")
            
            # 1. CENTRAL SPHERE (Smooth, semi-transparent)
            sphere = pv.Sphere(radius=base_radius, center=world_point, theta_resolution=30, phi_resolution=30)
            main_plotter.add_mesh(
                sphere, 
                color='red', 
                opacity=0.6,  # Semi-transparent
                name='fly_to_sphere', 
                lighting=True,  # Enable lighting for better look
                smooth_shading=True
            )
            
            # 2. OUTER RING (Circle at same height)
            ring = pv.Circle(radius=base_radius * 2.5, center=world_point, resolution=64)
            main_plotter.add_mesh(
                ring, 
                color='yellow', 
                line_width=4,
                opacity=0.8,
                name='fly_to_ring', 
                lighting=False
            )
            
            # 3. CROSSHAIR LINES (Thinner, longer)
            crosshair_size = base_radius * 5
            
            # Horizontal line (X-axis)
            h_line = pv.Line(
                [world_point[0] - crosshair_size, world_point[1], world_point[2]],
                [world_point[0] + crosshair_size, world_point[1], world_point[2]]
            )
            main_plotter.add_mesh(
                h_line, 
                color='yellow', 
                line_width=2,
                opacity=0.7,
                name='fly_to_h_line', 
                lighting=False
            )
            
            # Vertical line (Y-axis)
            v_line = pv.Line(
                [world_point[0], world_point[1] - crosshair_size, world_point[2]],
                [world_point[0], world_point[1] + crosshair_size, world_point[2]]
            )
            main_plotter.add_mesh(
                v_line, 
                color='yellow', 
                line_width=2,
                opacity=0.7,
                name='fly_to_v_line', 
                lighting=False
            )
            
            # 4. TEXT LABEL (Above the sphere)
            label_pos = [world_point[0], world_point[1], world_point[2] + base_radius * 4]
            main_plotter.add_point_labels(
                [label_pos], 
                ['🎯 TARGET'],
                point_size=0,  # Hide the point itself
                font_size=28,
                text_color='yellow', 
                name='fly_to_label',
                bold=True, 
                shadow=True,
                always_visible=True
            )
            
            print(f"   ✅ Multi-element indicator created")
            
            # Animate for 12 seconds (10-15 range)
            self._animate_indicator(main_plotter, base_radius, duration_ms=12000)
            
        except Exception as e:
            print(f"   ⚠️ Indicator creation failed: {e}")
            import traceback
            traceback.print_exc()
            
    def _animate_indicator(self, plotter, base_radius, duration_ms=12000):
        """Animate all indicator elements with pulse + expand + fade over 12 seconds"""
        from PySide6.QtCore import QTimer
        
        steps = 120  # More steps for smoother animation over 12 seconds
        step_duration = duration_ms // steps
        current_step = [0]
        
        # Store timer reference to prevent garbage collection
        timer = QTimer()
        
        def animate_step():
            try:
                t = current_step[0] / steps
                
                # Gentle fade (starts fading after 60% of time)
                if t < 0.6:
                    opacity = 1.0
                else:
                    fade_progress = (t - 0.6) / 0.4
                    opacity = 1.0 - fade_progress
                
                # Sphere: gentle pulsing
                pulse = 0.15 * np.sin(t * 3 * np.pi)  # 3 slow pulses
                sphere_opacity = max(0, min(1, (opacity * 0.6) + pulse))
                
                # Update actors if they exist
                if 'fly_to_sphere' in plotter.actors:
                    plotter.actors['fly_to_sphere'].GetProperty().SetOpacity(sphere_opacity)
                
                if 'fly_to_ring' in plotter.actors:
                    plotter.actors['fly_to_ring'].GetProperty().SetOpacity(opacity * 0.8)
                    # Gentle ring expansion
                    scale = 1 + t * 0.5  # Grows to 1.5x size slowly
                    plotter.actors['fly_to_ring'].SetScale(scale, scale, 1)
                
                if 'fly_to_h_line' in plotter.actors:
                    plotter.actors['fly_to_h_line'].GetProperty().SetOpacity(opacity * 0.7)
                
                if 'fly_to_v_line' in plotter.actors:
                    plotter.actors['fly_to_v_line'].GetProperty().SetOpacity(opacity * 0.7)
                
                if 'fly_to_label' in plotter.actors:
                    # Label stays visible longer
                    label_opacity = 1.0 if t < 0.8 else (1.0 - (t - 0.8) / 0.2)
                    plotter.actors['fly_to_label'].GetProperty().SetOpacity(max(0, label_opacity))
                
                self._safe_render_pyvista(plotter)
                
                current_step[0] += 1
                
                if current_step[0] <= steps:
                    timer.singleShot(step_duration, animate_step)
                else:
                    # Remove all indicators after animation completes
                    indicator_names = ['fly_to_sphere', 'fly_to_ring', 'fly_to_h_line', 
                                    'fly_to_v_line', 'fly_to_label']
                    removed_count = 0
                    
                    for name in indicator_names:
                        if name in plotter.actors:
                            try:
                                plotter.remove_actor(name)
                                removed_count += 1
                                print(f"   ✅ Removed actor: {name}")
                            except Exception as e:
                                print(f"   ⚠️ Failed to remove {name}: {e}")
                    
                    self._safe_render_pyvista(plotter)
                    print(f"   ✅ Animation complete. Removed {removed_count} indicators")
                    
            except Exception as e:
                print(f"   ⚠️ Animation step failed at step {current_step[0]}: {e}")
                import traceback
                traceback.print_exc()
        
        self._indicator_timer = timer
        animate_step()

    def _verify_buffer_classification(self, view_idx):

        try:
            app = self.app
            
            core_mask = getattr(app, f"section_{view_idx}_core_mask", None)
            buffer_mask = getattr(app, f"section_{view_idx}_buffer_mask", None)
            combined_mask = getattr(app, f"section_{view_idx}_combined_mask", None)
            
            # Get last changed mask from classification
            last_changed = getattr(app, "_last_changed_mask", None)
            
            if last_changed is None:
                print(f"   ⚠️ No _last_changed_mask found")
                return
            
            print(f"\n{'='*60}")
            print(f"🔍 BUFFER CLASSIFICATION VERIFICATION - View {view_idx}")
            print(f"{'='*60}")
            
            # Count points in each category
            if core_mask is not None:
                core_classified = (last_changed & core_mask).sum()
                print(f"   Core points classified: {core_classified:,}")
            
            if buffer_mask is not None:
                buffer_classified = (last_changed & buffer_mask).sum()
                print(f"   Buffer points classified: {buffer_classified:,}")
                if buffer_classified > 0:
                    print(f"   ✅ SUCCESS: Buffer points WERE classified!")
                else:
                    print(f"   ⚠️ WARNING: No buffer points were classified")
            
            if combined_mask is not None:
                total_classified = (last_changed & combined_mask).sum()
                print(f"   Total points classified: {total_classified:,}")
            
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"   ❌ Verification failed: {e}")    

    def verify_brush_buffer_classification(app):
        """
        Debug helper to verify brush tool includes buffer points.
        Call this after brush initialization (after left press).
        """
        print(f"\n{'='*60}")
        print(f"🔍 BRUSH BUFFER VERIFICATION")
        print(f"{'='*60}")
        
        # Check if brush is initialized
        if not hasattr(app, 'section_controller'):
            print("   ⚠️ No section controller")
            return
        
        active_view = getattr(app.section_controller, "active_view", None)
        if active_view is None:
            print("   ⚠️ No active view")
            return
        
        # Check masks
        combined_mask = getattr(app, f"section_{active_view}_combined_mask", None)
        core_mask = getattr(app, f"section_{active_view}_core_mask", None)
        buffer_mask = getattr(app, f"section_{active_view}_buffer_mask", None)
        
        if combined_mask is not None:
            combined_count = combined_mask.sum()
            print(f"   ✅ Combined mask: {combined_count:,} points")
        
        if core_mask is not None:
            core_count = core_mask.sum()
            print(f"   Core mask: {core_count:,} points")
        
        if buffer_mask is not None and core_mask is not None:
            buffer_only = (buffer_mask & ~core_mask).sum()
            print(f"   Buffer mask: {buffer_only:,} exclusive buffer points")
        
        # Check brush initialization
        interactor = None
        for vtk_widget in getattr(app, 'section_vtks', {}).values():
            if hasattr(vtk_widget, 'interactor'):
                interactor = vtk_widget.interactor
                if hasattr(interactor, 'GetInteractorStyle'):
                    style = interactor.GetInteractorStyle()
                    if hasattr(style, '_brush_section_indices'):
                        brush_indices = style._brush_section_indices
                        print(f"\n   🖌️ Brush indices: {len(brush_indices):,}")
                        
                        if combined_mask is not None:
                            expected = combined_mask.sum()
                            if len(brush_indices) == expected:
                                print(f"   ✅ Brush indices match combined mask!")
                            elif core_mask is not None and len(brush_indices) == core_mask.sum():
                                print(f"   ❌ Brush indices only include CORE (missing buffer!)")
                            else:
                                print(f"   ⚠️ Brush indices count unexpected: {len(brush_indices)} vs {expected}")
                        break
        
        print(f"{'='*60}\n")

    def _commit_classification(self, mask, from_classes, to_class):
        """Apply classification and maintain undo/redo stacks correctly."""
        import numpy as np

        classification = self.app.data["classification"]
        old_classes = classification[mask].copy()

        # Apply to ground truth
        classification[mask] = to_class

        # Push undo step
        step = {
            "mask": mask.copy(),
            "old_classes": old_classes,
            "new_classes": np.full(mask.sum(), to_class, dtype=classification.dtype),
        }
        self.app.undo_stack.append(step)

        self.app.redo_stack.clear()

        # Cap undo stack
        max_steps = getattr(self.app, '_max_undo_steps', 30)
        while len(self.app.undo_stack) > max_steps:
            from gui.memory_manager import _free_undo_entry
            _free_undo_entry(self.app.undo_stack.pop(0))

        if hasattr(self.app, 'section_vtks'):
            for view_idx in self.app.section_vtks.keys():
                self.app._sync_section_mirror_from_data(view_idx)

        self.app.classification_finished.emit(mask)
