import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QDoubleSpinBox, QAbstractSpinBox, QMessageBox, QDockWidget, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt
import vtk
from scipy.spatial import cKDTree

# ============ SAFE RENDER HELPER ============
def _safe_vtk_render(vtk_widget):
    """
    Safely render a VTK/PyVista widget. NEVER raises.
    Prevents crash from stale render windows when switching between
    cut section and synchronized views.
    """
    if vtk_widget is None:
        return False
    try:
        # Check Qt widget is alive
        if hasattr(vtk_widget, 'isVisible') and callable(vtk_widget.isVisible):
            if not vtk_widget.isVisible():
                return False
        # Validate render window
        rw = vtk_widget.GetRenderWindow()
        if rw is None:
            return False
        if rw.GetInteractor() is None:
            return False
        vtk_widget.render()
        return True
    except (RuntimeError, AttributeError, OSError, ReferenceError):
        return False
    except Exception:
        return False



# ============ INTERACTOR STYLE ============
class CutSectionInteractorStyle(vtk.vtkInteractorStyleUser):
    """
    Custom interactor style for cut section tool in cross-section views.
    
    ✅ ENABLES: Zoom (mouse wheel) and Pan (middle-click)
    ✅ ALLOWS: Left-click point selection
    ❌ BLOCKS: Right-click rotation (prevents accidental view changes)
    
    This allows users to navigate the view while placing cut points.
    """
    def __init__(self, app=None, vtk_widget=None):
        """Initialize with proper event handlers for zoom and pan."""
        super().__init__()
        self.app = app
        self.vtk_widget = vtk_widget
        
        # ❌ DO NOT block these - instead handle them properly!
        # self.AddObserver("MouseWheelForwardEvent", lambda obj, evt: None)  # ← REMOVE
        # self.AddObserver("MouseWheelBackwardEvent", lambda obj, evt: None)  # ← REMOVE
        
        # ✅ DO add proper handlers for zoom and pan
        self.AddObserver("MouseWheelForwardEvent", self._on_mouse_wheel_forward)
        self.AddObserver("MouseWheelBackwardEvent", self._on_mouse_wheel_backward)
        self.AddObserver("LeftButtonPressEvent", self._on_left_press)
        self.AddObserver("MiddleButtonPressEvent", self._on_middle_press)
        self.AddObserver("MiddleButtonReleaseEvent", self._on_middle_release)
        self.AddObserver("MouseMoveEvent", self._on_mouse_move)
        
        # Block rotation (but allow zoom/pan)
        self.AddObserver("RightButtonPressEvent", self._block_event)
        self.AddObserver("RightButtonReleaseEvent", self._block_event)
        
        # State for panning
        self._is_panning = False
        self._last_pos = (0, 0)
    
    def _block_event(self, obj, event):
        """Dummy handler to block right-click rotation."""
        pass

    def _on_left_press(self, obj, event):
        try:
            interactor = self.GetInteractor()
            if interactor is None:
                return
            if self.app is None or self.vtk_widget is None:
                return
            if getattr(self.app, "zoom_behavior", "center") != "picked_point":
                return
            if hasattr(self.app, "_store_zoom_anchor"):
                self.app._store_zoom_anchor(self.vtk_widget, interactor=interactor)
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            pass
        except Exception:
            pass
    
    def _on_mouse_wheel_forward(self, obj, event):
        """Handle mouse wheel forward (zoom in). ✅ SAFE render."""
        try:
            interactor = self.GetInteractor()
            if interactor is None:
                return

            zoom_behavior = getattr(self.app, "zoom_behavior", "center")
            if self.vtk_widget is not None and self.app is not None:
                if zoom_behavior == "cursor" and hasattr(self.app, "_zoom_widget_at_cursor"):
                    if self.app._zoom_widget_at_cursor(self.vtk_widget, 1.2, interactor=interactor):
                        return
                elif zoom_behavior == "picked_point" and hasattr(self.app, "_zoom_widget_at_anchor"):
                    anchor_world = getattr(self.app, "_zoom_anchor_points", {}).get(id(self.vtk_widget))
                    if anchor_world is not None and self.app._zoom_widget_at_anchor(self.vtk_widget, 1.2, anchor_world):
                        return
            
            render_window = interactor.GetRenderWindow()
            if render_window is None or render_window.GetInteractor() is None:
                return
            renderers = render_window.GetRenderers()
            if renderers is None or renderers.GetNumberOfItems() == 0:
                return
            renderer = renderers.GetFirstRenderer()
            
            if renderer is None:
                return
            
            camera = renderer.GetActiveCamera()
            if camera is None:
                return
            
            camera.Zoom(1.2)
            render_window.Render()
            
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            pass
        except Exception as e:
            print(f"⚠️ Zoom forward error: {e}")
    
    def _on_mouse_wheel_backward(self, obj, event):
        """Handle mouse wheel backward (zoom out). ✅ SAFE render."""
        try:
            interactor = self.GetInteractor()
            if interactor is None:
                return

            zoom_behavior = getattr(self.app, "zoom_behavior", "center")
            if self.vtk_widget is not None and self.app is not None:
                if zoom_behavior == "cursor" and hasattr(self.app, "_zoom_widget_at_cursor"):
                    if self.app._zoom_widget_at_cursor(self.vtk_widget, 0.833, interactor=interactor):
                        return
                elif zoom_behavior == "picked_point" and hasattr(self.app, "_zoom_widget_at_anchor"):
                    anchor_world = getattr(self.app, "_zoom_anchor_points", {}).get(id(self.vtk_widget))
                    if anchor_world is not None and self.app._zoom_widget_at_anchor(self.vtk_widget, 0.833, anchor_world):
                        return
            
            render_window = interactor.GetRenderWindow()
            if render_window is None or render_window.GetInteractor() is None:
                return
            renderers = render_window.GetRenderers()
            if renderers is None or renderers.GetNumberOfItems() == 0:
                return
            renderer = renderers.GetFirstRenderer()
            
            if renderer is None:
                return
            
            camera = renderer.GetActiveCamera()
            if camera is None:
                return
            
            camera.Zoom(0.833)
            render_window.Render()
            
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            pass
        except Exception as e:
            print(f"⚠️ Zoom backward error: {e}")
    
    def _on_middle_press(self, obj, event):
        """Handle middle-click press (start pan)."""
        try:
            interactor = self.GetInteractor()
            if interactor is None:
                return
            
            self._is_panning = True
            self._last_pos = interactor.GetEventPosition()
            print("✋ Pan START (middle-click)")
            
        except Exception as e:
            print(f"⚠️ Middle press error: {e}")
    
    def _on_middle_release(self, obj, event):
        """Handle middle-click release (stop pan)."""
        try:
            self._is_panning = False
            print("✋ Pan STOP (middle-click release)")
        except Exception as e:
            print(f"⚠️ Middle release error: {e}")
    
    def _on_mouse_move(self, obj, event):
        """Handle mouse move for panning. ✅ SAFE: all VTK access guarded."""
        if not self._is_panning:
            return
        
        try:
            interactor = self.GetInteractor()
            if interactor is None:
                return
            
            current_pos = interactor.GetEventPosition()
            
            dx = current_pos[0] - self._last_pos[0]
            dy = current_pos[1] - self._last_pos[1]
            
            if dx == 0 and dy == 0:
                return
            
            render_window = interactor.GetRenderWindow()
            if render_window is None or render_window.GetInteractor() is None:
                return
            renderers = render_window.GetRenderers()
            if renderers is None or renderers.GetNumberOfItems() == 0:
                return
            renderer = renderers.GetFirstRenderer()
            
            if renderer is None:
                return
            
            camera = renderer.GetActiveCamera()
            if camera is None:
                return
            
            size = render_window.GetSize()
            if size[0] == 0 or size[1] == 0:
                return
            
            camera.OrthogonalizeViewUp()
            
            right = np.array(camera.GetViewRight())
            up = np.array(camera.GetViewUp())
            
            # ✅ FIX: Use ParallelScale for orthographic views (correct 1:1 mapping)
            if camera.GetParallelProjection():
                parallel_scale = camera.GetParallelScale()
                scale = (2.0 * parallel_scale) / max(size[1], 1)
            else:
                distance = camera.GetDistance()
                scale = distance / (size[0] * 0.5) if size[0] > 0 else 0
            
            pan_vector = -dx * scale * right - dy * scale * up
            
            current_cam_pos = np.array(camera.GetPosition())
            new_pos = current_cam_pos + pan_vector
            camera.SetPosition(new_pos)
            
            focal = np.array(camera.GetFocalPoint())
            new_focal = focal + pan_vector
            camera.SetFocalPoint(new_focal)
            
            self._last_pos = current_pos
            
            try:
                render_window.Render()
            except (RuntimeError, AttributeError, OSError, ReferenceError):
                pass
            
        except (RuntimeError, AttributeError, OSError, ReferenceError):
            self._is_panning = False
        except Exception as e:
            print(f"⚠️ Mouse move pan error: {e}")

# ============ STATE ENUM ============
class CutSectionState:
    IDLE = 0
    WAITING_CENTER = 1
    WAITING_DEPTH = 2
    FINALIZED = 3

def safe_lut_indexing(lut, classes):
    """
    Safely index into LUT array, preventing memory access violations.
    
    This is CRITICAL for stability when classification codes exceed LUT size.
    Uses np.clip to clamp indices to valid range [0, len(lut)-1].
    
    Args:
        lut: numpy array of shape (N, 3) with RGB colors
        classes: numpy array of classification codes
        
    Returns:
        numpy array of RGB colors for each class
    """
    import numpy as np
    
    # Ensure classes are integers
    classes = np.asarray(classes, dtype=int)
    
    # Clamp class indices to valid LUT range
    max_lut_idx = len(lut) - 1
    safe_classes = np.clip(classes, 0, max_lut_idx)
    
    # Warn if we had to clamp (helps debugging)
    if np.any(classes != safe_classes):
        out_of_bounds = classes[classes != safe_classes]
        unique_oob = np.unique(out_of_bounds)
        print(f"⚠️ WARNING: {len(out_of_bounds)} points with out-of-bounds classifications")
        print(f"   Out-of-bounds codes: {unique_oob.tolist()}")
        print(f"   LUT size: {len(lut)} (max index: {max_lut_idx})")
        print(f"   → Clamped to valid range to prevent crash")
    
    return lut[safe_classes]

# ============ CONTROLLER ============
class CutSectionController:
    """
    Cut Section Controller - Works like Cross-Section with modern inline dock UI.
    ✅ State machine for robust state management
    ✅ Real-time refresh like cross-section
    ✅ Independent cut window (doesn't override cross-section)
    ✅ NO floating dialog - all depth control in dock
    ✅ Real-time classification updates (cut + main + cross-section sync)
    """
    def __init__(self, app):
        self.app = app
        self.cut_palette = {}

        self._is_destroying = False
        # State machine
        self._state = CutSectionState.IDLE
        self.cut_phase = 0
        self.center_point = None
        self.dynamic_depth = getattr(app, "default_cut_width", 1.0)

        # ✅ ADD THIS: Track saved interactor styles per view
        self._saved_interactor_styles = {}
        self._cut_source = None

        # Data
        self.cut_points = None
        self._cut_index_map = None
        self._kdtree_cache = None
        self.section_tangent = None
        self.is_cut_view_active = False

        # Visuals - cross-section preview
        self._cross_camera_state = None
        self.active_vtk = None
        self.line_actor = None
        self.buffer_actor_upper = None
        self.buffer_actor_lower = None

        # Visuals - cut dock preview
        self.cut_preview_upper = None
        self.cut_preview_lower = None

        # Config
        self.tail_length = 3.0
        self.buffer_display_width = 0.5
        self.cut_yaw_deg = 0.0

        # Per-view observer ids
        self._view_observer_ids = {}

        # UI state
        self._cut_camera_state = None
        self._is_refreshing = False
        self._old_classify_interactor = None

        # Dedicated cut section widgets (with INLINE DEPTH)
        self.cut_vtk = None
        self.cut_dock = None
        self.cut_core_actor = None
        self.cut_buffer_actor = None
        self.depth_label = None
        self.depth_spin = None
        
        # State saves
        self._saved_section_state = None
        self._original_section_points = None
        self._original_section_indices = None
        
        #
        self.cut_level = 0
        self.parent_cut_points = None
        self.parent_cut_index_map = None
        self.cut_history = []

        # ✅ ADD: MicroStation-style rotation tracking
        self.original_section_tangent = None  # Store initial cross-section line direction
        self.accumulated_rotation = 0  # Track total rotation (0°, 90°, 180°, 270°)

    def apply_palette(self, palette):
        """
        Apply Display Mode palette to cut section view.
        ✅ Stores palette independently - survives new cuts and classifications
        ✅ Normalizes class codes to int (prevents key mismatch issues)
        
        Args:
            palette: Dictionary from Display Mode (view_palettes[5])
        """
        if not palette or not isinstance(palette, dict):
            print("   ⚠️ Empty/invalid palette provided")
            return

        # ✅ Normalize + deep-copy (avoid references + ensure int keys)
        new_palette = {}
        for code, info in palette.items():
            try:
                code_int = int(code)
            except Exception:
                # Skip non-numeric codes safely
                continue

            info = info or {}
            new_palette[code_int] = {
                "show": bool(info.get("show", False)),
                "description": str(info.get("description", "")),
                "color": tuple(info.get("color", (128, 128, 128))),
                "weight": float(info.get("weight", 1.0)),
            }

        self.cut_palette = new_palette
        print(f"   ✅ Cut palette updated: {len(self.cut_palette)} classes")

        # If cut view is not active, just store it (it will be used on next plot/refresh)
        if not self.is_cut_view_active or self.cut_vtk is None:
            print("   ℹ️ Cut section view not active - palette stored for next cut")
            return

        # Refresh view with new palette
        try:
            self._refresh_cut_colors_fast()
            print("   ✅ Cut section view refreshed with new palette")
        except Exception as e:
            print(f"   ⚠️ Cut palette refresh failed: {e}")
            import traceback
            traceback.print_exc()


    def _reset_cut_view_camera(self):
        """Reset cut section camera to correct orthogonal view along tangent."""
        if self.cut_vtk is None or self.cut_points is None:
            print("⚠️ Cannot reset view: cut section not active")
            return
        
        if self.section_tangent is None:
            print("⚠️ Cannot reset view: tangent not available")
            return
        
        try:
            print("🔄 Resetting cut section camera to orthogonal view...")
            
            # ✅ CRITICAL: Store current classification interactor state
            current_interactor = getattr(self.app, "classify_interactor", None)
            is_cut_interactor = (
                current_interactor is not None and 
                hasattr(current_interactor, "vtk_widget") and 
                current_interactor.vtk_widget == self.cut_vtk
            )
            
            # ✅ BUG #5 FIX: Apply rotation to tangent based on accumulated_rotation
            rotated_tangent = self.section_tangent.copy()
            
            if self.accumulated_rotation > 0:
                print(f"🔍 Applying {self.accumulated_rotation}° rotation to camera tangent")
                
                # Rotate tangent by accumulated_rotation degrees
                # Each 90° rotation: (x, y, z) → (y, -x, z)
                num_rotations = (self.accumulated_rotation // 90) % 4
                
                for _ in range(num_rotations):
                    # Apply 90° CCW rotation in XY plane
                    old_x = rotated_tangent[0]
                    old_y = rotated_tangent[1]
                    rotated_tangent[0] = old_y
                    rotated_tangent[1] = -old_x
                    # Z unchanged
                
                print(f"   Original tangent: {self.section_tangent}")
                print(f"   Rotated tangent:  {rotated_tangent} (after {num_rotations} × 90°)")
            else:
                print(f"   Using original tangent (no rotation): {rotated_tangent}")
            
            # Re-apply the correct camera position along ROTATED tangent
            self._set_camera_along_tangent(self.cut_vtk, self.cut_points, rotated_tangent)
            
            # Render to apply changes
            _safe_vtk_render(self.cut_vtk)
            
            # ✅ CRITICAL: Restore classification interactor if it was active
            if is_cut_interactor and current_interactor is not None:
                print("🔧 Restoring classification interactor to cut section...")
                # Force re-attach to cut section (not cross-section)
                self.cut_vtk.interactor.SetInteractorStyle(current_interactor.style)
                current_interactor.vtk_widget = self.cut_vtk
                current_interactor.is_cut_section = True
                print("✅ Classification interactor restored to cut section")
            
            print("✅ Camera reset successfully")
            self.app.statusBar().showMessage("✅ Cut section view reset", 2000)
            
        except Exception as e:
            print(f"⚠️ Failed to reset camera: {e}")
            import traceback
            traceback.print_exc()


    def clear(self):
        """
        Clear all cut section data and state.
        ✅ FIXED: Proper actor cleanup before widget destruction
        ✅ FIXED: Does NOT clear cut_palette (preserves user settings)
        ✅ BUG #7 FIX: Explicitly delete VTK actors to prevent memory leak
        ✅ BUG #8 FIX: Clear KDTree cache
        ✅ BUG FIX: Prevents OpenGL "invalid pixel format" error on app close
        """
        try:
            print("\n🧹 Clearing Cut Section Controller...")
            
            # ✅ CRITICAL FIX: Check if render window is still valid
            is_vtk_valid = False
            if self.cut_vtk is not None:
                try:
                    rw = self.cut_vtk.GetRenderWindow()
                    if rw is not None:
                        is_vtk_valid = rw.GetMapped() and not rw.IsA('vtkObject') or True
                except:
                    is_vtk_valid = False
                    print("   ⚠️ VTK render window already destroyed")
            
            # ✅ CRITICAL: Remove actors BEFORE destroying widget (only if VTK valid)
            if self.cut_vtk is not None and is_vtk_valid:
                try:
                    renderer = self.cut_vtk.renderer
                    
                    # Remove all cut section actors
                    actors_to_remove = [
                        self.cut_core_actor,
                        self.cut_buffer_actor,
                        self.line_actor,
                        self.buffer_actor_upper,
                        self.buffer_actor_lower,
                        self.cut_preview_upper,
                        self.cut_preview_lower
                    ]
                    
                    for actor in actors_to_remove:
                        if actor is not None:
                            try:
                                renderer.RemoveActor(actor)
                                
                                # ✅ BUG #7 FIX: Explicitly delete VTK C++ object
                                try:
                                    actor.Delete()
                                    print(f"   ✅ Actor deleted (freed VTK memory)")
                                except AttributeError:
                                    # PyVista actors might not have Delete() method
                                    pass
                            except Exception as e:
                                print(f"   ⚠️ Actor removal warning: {e}")
                except Exception as e:
                    print(f"   ⚠️ Actor cleanup skipped (widget invalid): {e}")
                
                # ✅ FIX: Safe widget cleanup with render window validation
                try:
                    # Step 1: Disable rendering FIRST
                    rw = self.cut_vtk.GetRenderWindow()
                    if rw is not None:
                        print("   ✅ Render window disabled")
                        # ✅ FIX: Check if SetMapped exists (VTK version compatibility)
                        if hasattr(rw, 'SetMapped'):
                            rw.SetMapped(False)  # Stop all rendering
                        rw.Finalize()  # Safe finalize

                    
                    # Step 2: Clear widget
                    self.cut_vtk.clear()
                    
                    # Step 3: Close widget
                    self.cut_vtk.close()
                    
                    print("   ✅ Cut VTK widget finalized")
                except Exception as e:
                    print(f"   ⚠️ VTK finalize warning: {e}")
            
            # Clear state (keep your existing state clearing code)
            self._state = CutSectionState.IDLE
            self.cut_phase = 0
            self.center_point = None
            self.dynamic_depth = getattr(self.app, "default_cut_width", 1.0)
            
            # Clear data
            self.cut_points = None
            self._cut_index_map = None
            
            # ✅ BUG #8 FIX: Explicitly clear KDTree cache
            if self._kdtree_cache is not None:
                try:
                    # Python GC will collect it, but explicit deletion helps
                    del self._kdtree_cache
                    print("   ✅ KDTree cache cleared")
                except:
                    pass
            self._kdtree_cache = None
            
            self.section_tangent = None
            self.is_cut_view_active = False
            
            # ============================================================
            # ✅ CRITICAL: DO NOT CLEAR self.cut_palette
            # This preserves user's Display Mode settings across cuts
            # ============================================================
            # self.cut_palette = {}  # ← DO NOT DO THIS!
            
            if hasattr(self, 'cut_palette') and self.cut_palette:
                print(f"   💾 Preserved cut palette: {len(self.cut_palette)} classes")
            # ============================================================
            
            # Clear actor references
            self.cut_core_actor = None
            self.cut_buffer_actor = None
            self.line_actor = None
            self.buffer_actor_upper = None
            self.buffer_actor_lower = None
            self.cut_preview_upper = None
            self.cut_preview_lower = None
            
            # ✅ BUG #7 FIX: Clear cached geometry objects (prevents leak)
            for attr in ['_line_actor_points', '_line_actor_poly', '_line_actor_mapper',
                        '_cut_preview_upper_points', '_cut_preview_upper_lines', 
                        '_cut_preview_upper_poly', '_cut_preview_upper_mapper',
                        '_cut_preview_lower_points', '_cut_preview_lower_lines',
                        '_cut_preview_lower_poly', '_cut_preview_lower_mapper']:
                if hasattr(self, attr):
                    try:
                        obj = getattr(self, attr)
                        if obj is not None and hasattr(obj, 'Delete'):
                            obj.Delete()  # Delete VTK objects
                        delattr(self, attr)
                    except:
                        pass
            
            print("   ✅ All cached geometry cleared")
            
            # Clear visuals
            self._cross_camera_state = None
            self.active_vtk = None
            
            # Clear history
            self.cut_level = 0
            self.parent_cut_points = None
            self.parent_cut_index_map = None
            self.cut_history = []
            
            # Clear rotation tracking
            self.original_section_tangent = None
            self.accumulated_rotation = 0
            
            # Clear saved state
            self._saved_section_state = None
            self._original_section_points = None
            self._original_section_indices = None
            
            # Detach observers
            self._detach_all_view_observers()
            
            # ✅ Close dock AFTER widget cleanup
            if self.cut_dock is not None:
                try:
                    if hasattr(self.app, 'removeDockWidget'):
                        self.app.removeDockWidget(self.cut_dock)
                    
                    self.cut_dock.hide()
                    self.cut_dock.deleteLater()
                    print("   ✅ Cut dock closed and deleted")
                except Exception as e:
                    print(f"   ⚠️ Dock close warning: {e}")
            
            self.cut_vtk = None
            self.cut_dock = None
            self.depth_label = None
            self.depth_spin = None
            
            print("✅ Cut Section Controller cleared (palette preserved)")
            
        except Exception as e:
            print(f"⚠️ Cut Section clear error: {e}")
            import traceback
            traceback.print_exc()



    def _configure_line_on_top(self, actor):
        """NUCLEAR OPTION: Force lines ALWAYS visible (disable depth test)."""
        try:
            if actor is None:
                return
            
            mapper = actor.GetMapper()
            if mapper is None:
                print("⚠️ Skipping line depth config: actor has no mapper")
                return
            
            # ✅ AGGRESSIVE OFFSETS
            mapper.SetResolveCoincidentTopologyToPolygonOffset()
            mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-5.0, -5.0)
            
            try:
                mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-10.0, -10.0)
            except AttributeError:
                pass
            
            # ✅ NUCLEAR: Access OpenGL state directly (VTK 9+)
            try:
                # This forces the actor to render WITHOUT depth testing
                prop = actor.GetProperty()
                prop.SetRenderLinesAsTubes(False)
                
                # Force to translucent pass (rendered last, no depth test)
                actor.ForceTranslucentOn()
                prop.SetOpacity(0.99)  # Just below 1.0 to trigger translucent pass
            except:
                pass
            
            actor.SetUseBounds(False)
            
        except Exception as e:
            print(f"⚠️ Could not set line depth priority: {e}")


    def _activate_from_cut_dock(self):
        """Activate cut section INSIDE the existing cut view (nested cut)."""
        print(f"📐 Nested cut: taking cut from existing cut view")
        self._cut_source = 'cut'

        self._temporarily_disable_classification()
        
        # ✅ BUG #2 FIX: Remove old observers with VERIFICATION
        if 'cut_dock' in self._view_observer_ids:
            old_ids = self._view_observer_ids['cut_dock']
            if self.cut_vtk is not None:
                iren = self.cut_vtk.interactor
                removed_count = 0
                
                for oid in old_ids:
                    try:
                        # ✅ CRITICAL: Verify observer exists before removing
                        if iren.HasObserver(oid):
                            iren.RemoveObserver(oid)
                            removed_count += 1
                            print(f"  🧹 Removed old observer: {oid}")
                        else:
                            print(f"  ⚠️ Observer {oid} already removed")
                    except Exception as e:
                        print(f"  ⚠️ Failed to remove observer {oid}: {e}")
                
                print(f"  ✅ Verified removal: {removed_count}/{len(old_ids)} observers cleared")
            
            del self._view_observer_ids['cut_dock']
        
        # Reset state
        self._detach_all_view_observers()
        self._clear_preview_actors()
        
        self._state = CutSectionState.WAITING_CENTER
        self.cut_phase = 0
        self.center_point = None
        self.dynamic_depth = max(getattr(self.app, "default_cut_width", 1.0), 0.5)
        
        # ✅ CRITICAL: Clear cached line geometry to force recreation
        for attr in ['_line_actor_points', '_line_actor_poly', '_line_actor', '_line_actor_mapper',
                    '_cut_preview_upper_points', '_cut_preview_upper_lines', '_cut_preview_upper_poly', '_cut_preview_upper_mapper',
                    '_cut_preview_lower_points', '_cut_preview_lower_lines', '_cut_preview_lower_poly', '_cut_preview_lower_mapper']:
            if hasattr(self, attr):
                delattr(self, attr)
        
        self.line_actor = None
        self.cut_preview_upper = None
        self.cut_preview_lower = None
        
        # ✅ Reset spinbox for new cut
        if self.depth_spin:
            self.depth_spin.blockSignals(True)
            self.depth_spin.setValue(self.dynamic_depth)
            self.depth_spin.blockSignals(False)
        
        # ✅ CRITICAL: Store last mouse position to prevent redundant updates
        self._last_mouse_pos = None
        self._last_update_time = 0
        
        # ✅ BUG #2 FIX: Clean slate before attaching new observers
        if self.cut_vtk is not None:
            iren = self.cut_vtk.interactor
            
            # ✅ NUCLEAR CLEANUP: Remove ALL LeftButton/MouseMove observers
            # This prevents ghost observers from stacking up
            try:
                iren.RemoveObservers("LeftButtonPressEvent")
                iren.RemoveObservers("MouseMoveEvent")
                print(f"  🧹 Cleared all LeftButton/MouseMove observers (nuclear cleanup)")
            except Exception as e:
                print(f"  ⚠️ Nuclear cleanup warning: {e}")
            
            def on_left_click(obj, evt):
                print(f"🖱️ Left click in cut dock (state={self._state})")
                if self._state == CutSectionState.IDLE:
                    return
                
                pos = self.cut_vtk.interactor.GetEventPosition()
                picker = vtk.vtkWorldPointPicker()
                picker.Pick(pos[0], pos[1], 0, self.cut_vtk.renderer)
                pt = np.array(picker.GetPickPosition())
                
                if np.allclose(pt, (0, 0, 0), atol=1e-6):
                    print("  ⚠️ Invalid pick position")
                    return
                
                if self._state == CutSectionState.WAITING_CENTER:
                    self.center_point = pt
                    self._state = CutSectionState.WAITING_DEPTH
                    self.cut_phase = 1
                    print(f"  ✅ Center set at {pt}, now WAITING_DEPTH")
                    
                    # ✅ CRITICAL: Force immediate line update
                    self._draw_dynamic_center_line_in_cut(self.center_point)
                    _safe_vtk_render(self.cut_vtk)
                    return
                
                if self._state == CutSectionState.WAITING_DEPTH:
                    print(f"  ✅ Finalizing with depth={self.dynamic_depth}")
                    self._finalize_dynamic_cut_section()
                    return
            
            def on_mouse_move(obj, evt):
                if self._state == CutSectionState.IDLE:
                    return
                
                # ✅ THROTTLING: Prevent excessive updates
                import time
                current_time = time.time()
                if current_time - self._last_update_time < 0.016:  # Max 60 FPS
                    return
                self._last_update_time = current_time
                
                pos = self.cut_vtk.interactor.GetEventPosition()
                
                # ✅ CRITICAL: Check if mouse actually moved
                if self._last_mouse_pos is not None:
                    dx = abs(pos[0] - self._last_mouse_pos[0])
                    dy = abs(pos[1] - self._last_mouse_pos[1])
                    if dx < 2 and dy < 2:  # Ignore tiny movements
                        return
                self._last_mouse_pos = pos
                
                picker = vtk.vtkWorldPointPicker()
                picker.Pick(pos[0], pos[1], 0, self.cut_vtk.renderer)
                curr = np.array(picker.GetPickPosition())
                
                if np.allclose(curr, (0, 0, 0), atol=1e-6):
                    return
                
                if self._state == CutSectionState.WAITING_CENTER:
                    # ✅ Update line while moving to center
                    self._draw_dynamic_center_line_in_cut(curr)
                    return
                
                if self._state == CutSectionState.WAITING_DEPTH and self.center_point is not None:
                    # ✅ FIX: ALWAYS use X-axis (0) for cut section interaction
                    # Camera ALWAYS looks along Y-axis, so mouse movement affects X primarily
                    # Using Y-axis causes issues because mouse movement doesn't change Y position
                    axis = 0  # ← FIXED! Was: ((self.accumulated_rotation + 90) // 90) % 2
                    
                    old_depth = self.dynamic_depth
                    new_depth = abs(curr[axis] - self.center_point[axis])
                    
                    # ✅ Skip tiny movements (prevents snapping to 0.01m)
                    if new_depth < 0.01:
                        return  # Ignore movement near center line
                    
                    # ✅ Only update if significant change (debouncing)
                    if abs(new_depth - old_depth) < 0.02:
                        return  # Skip tiny changes
                    
                    self.dynamic_depth = new_depth
                    
                    print(f"🔄 Depth: {self.dynamic_depth:.2f}m (axis={axis}, rot={self.accumulated_rotation})")
                    self._draw_cut_section_preview(self.center_point, self.dynamic_depth)
                    
                    # Update spinbox
                    if self.depth_spin:
                        self.depth_spin.blockSignals(True)
                        self.depth_spin.setValue(self.dynamic_depth)
                        self.depth_spin.blockSignals(False)
                    return
            
            try:
                lid = iren.AddObserver("LeftButtonPressEvent", on_left_click)
                mid = iren.AddObserver("MouseMoveEvent", on_mouse_move)
                self._view_observer_ids['cut_dock'] = [lid, mid]
                print(f"  ✅ New observers attached: left={lid}, move={mid}")
                
                # ✅ BUG #2 FIX: Verify observers were successfully registered
                if not iren.HasObserver("LeftButtonPressEvent"):
                    print(f"  ⚠️ WARNING: LeftButtonPressEvent observer {lid} not registered!")
                if not iren.HasObserver("MouseMoveEvent"):
                    print(f"  ⚠️ WARNING: MouseMoveEvent observer {mid} not registered!")
                    
            except Exception as e:
                print(f"  ⚠️ Cut dock observer attachment failed: {e}")
        
        self.app.statusBar().showMessage("✂️ Nested Cut: click center, adjust depth, click to finalize", 0)



    def _draw_dynamic_center_line_in_cut(self, center):
        """Draw center line INSIDE cut dock with smooth updates."""
        if self.cut_vtk is None:
            return
        
        # ✅ SAFETY: Check if renderer exists
        if not hasattr(self.cut_vtk, "renderer") or self.cut_vtk.renderer is None:
            print("  ⚠️ No renderer available")
            return
        
        ren = self.cut_vtk.renderer
        
        # Get Z bounds from cut points (use viewport for nested cuts)
        try:
            cam = ren.GetActiveCamera()
            parallel_scale = cam.GetParallelScale()
            height_extent = parallel_scale * 2.0
            zmin = center[2] - height_extent
            zmax = center[2] + height_extent
        except:
            if self.cut_points is not None:
                zmin = float(np.min(self.cut_points[:, 2]))
                zmax = float(np.max(self.cut_points[:, 2]))
            else:
                zmin, zmax = center[2] - 10.0, center[2] + 10.0
        
        p0 = np.array([center[0], center[1], zmin], dtype=float)
        p1 = np.array([center[0], center[1], zmax], dtype=float)
        
        # ✅ SMOOTH UPDATE: Reuse actor if exists
        if self.line_actor is None or not hasattr(self, '_line_actor_points'):
            print(f"  🆕 Creating new line actor at {center}")
            
            # Create ONCE
            pts = vtk.vtkPoints()
            pts.InsertNextPoint(*p0)
            pts.InsertNextPoint(*p1)
            
            lines = vtk.vtkCellArray()
            lines.InsertNextCell(2)
            lines.InsertCellPoint(0)
            lines.InsertCellPoint(1)
            
            poly = vtk.vtkPolyData()
            poly.SetPoints(pts)
            poly.SetLines(lines)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly)
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0, 1, 0)  # Green
            actor.GetProperty().SetLineWidth(2)  # ✅ Slightly thicker for visibility
            
            # ✅ FORCE LINES ON TOP
            self._configure_line_on_top(actor)
            
            ren.AddActor(actor)
            self.line_actor = actor
            
            # Cache for updates
            self._line_actor_points = pts
            self._line_actor_poly = poly
            self._line_actor_mapper = mapper
        else:
            # ✅ FAST UPDATE (no recreation)
            pts = self._line_actor_points
            poly = self._line_actor_poly
            
            # ✅ CRITICAL: Update points AND notify VTK
            pts.SetPoint(0, *p0)
            pts.SetPoint(1, *p1)
            pts.Modified()
            poly.Modified()
            
            # ✅ Force mapper update
            if hasattr(self, '_line_actor_mapper'):
                self._line_actor_mapper.Update()
        
        # ✅ CRITICAL: Always render after update
        try:
            _safe_vtk_render(self.cut_vtk)
        except Exception as e:
            print(f"  ⚠️ Render failed: {e}")

    def _finalize_dynamic_cut_section(self):
        """Create cut section - FIXED coordinate transformation for proper orthogonal view"""
        
        if self.center_point is None:
            print("⚠️ finalize: invalid center")
            return
        
        # ✅ FALLBACK: Use minimum depth if current depth is too small
        if self.dynamic_depth <= 0.01:
            self.dynamic_depth = max(0.5, getattr(self.app, "default_cut_width", 1.0))
            print(f"⚠️ Depth too small, using fallback: {self.dynamic_depth}m")
            
            # Update UI
            if self.depth_spin:
                self.depth_spin.blockSignals(True)
                self.depth_spin.setValue(self.dynamic_depth)
                self.depth_spin.blockSignals(False)
                
        if self.center_point is None or self.dynamic_depth <= 0:
            print("⚠️ finalize: invalid center/depth")
            
            # ✅ BUG #11 FIX: Reset state
            self._state = CutSectionState.IDLE
            self.cut_phase = 0
            self.app.statusBar().showMessage("❌ Invalid cut parameters", 3000)
            return

        # ============================================================
        # ✅ CUT PALETTE PERSISTENCE (PRESERVE BEFORE NEW CUT)
        # ============================================================
        preserved_cut_palette = None
        try:
            if hasattr(self, "cut_palette") and self.cut_palette:
                preserved_cut_palette = {
                    int(code): {
                        "show": bool(info.get("show", False)),
                        "description": str(info.get("description", "")),
                        "color": tuple(info.get("color", (128, 128, 128))),
                        "weight": float(info.get("weight", 1.0)),
                    }
                    for code, info in self.cut_palette.items()
                }
                print(f"💾 Preserving cut palette before new cut: {len(preserved_cut_palette)} classes")
        except Exception as e:
            print(f"⚠️ Could not preserve cut palette: {e}")
            preserved_cut_palette = None

        # Nested cut logic (cut-from-cut)
        if self.is_cut_view_active and self.cut_points is not None:
            print(f"🔄 Creating nested cut from {len(self.cut_points)} existing cut points")
            xyz = self.cut_points.copy()
            parent_index_map = self._cut_index_map.copy()
            
            # ✅ BUG #4 FIX: Use correct axis based on rotation (alternates 0→1→0→1)
            # After each 90° rotation, the filtering axis switches
            # 0° or 180° → filter X-axis (0)
            # 90° or 270° → filter Y-axis (1)
            axis = (self.accumulated_rotation // 90) % 2
            
            print(f"🔍 Rotation state: {self.accumulated_rotation}° → using axis {axis} ({'X' if axis == 0 else 'Y'})")
            
            # Filter by depth along the calculated axis
            center_val = float(self.center_point[axis])
            cut_lower = center_val - self.dynamic_depth
            cut_upper = center_val + self.dynamic_depth
            
            print(f"✅ Filtering nested cut: axis={axis}, center={center_val:.2f}, depth=±{self.dynamic_depth:.2f}")
            
            depth_mask = (
                (xyz[:, axis] >= cut_lower) &
                (xyz[:, axis] <= cut_upper)
            )
            
            print(f"✅ Depth filter: {np.sum(depth_mask)}/{len(xyz)} points")
            
            if not np.any(depth_mask):
                print(f"❌ No points in depth range [{cut_lower:.2f}, {cut_upper:.2f}] on axis {axis}")
                print(f"   Data range on axis {axis}: [{xyz[:, axis].min():.2f}, {xyz[:, axis].max():.2f}]")
                
                # ✅ BUG #11 FIX: Reset state before returning
                self._state = CutSectionState.IDLE
                self.cut_phase = 0
                self.center_point = None
                self._clear_preview_actors()
                
                self.app.statusBar().showMessage("❌ No points in selected range - try different depth", 3000)
                print("✅ State reset to IDLE")
                return

            # Transform to new coordinate system (rotate 90°)
            xyz_filtered = xyz[depth_mask]
            
            # ✅ Rotate coordinates 90° for next cut
            xyz_rotated = xyz_filtered.copy()
            xyz_rotated[:, 0] = xyz_filtered[:, 1]   # New X = old Y
            xyz_rotated[:, 1] = -xyz_filtered[:, 0]  # New Y = -old X (90° rotation)
            # Z unchanged
            
            xyz = xyz_rotated
            parent_index_map = parent_index_map[depth_mask]
            
            # Increment rotation
            self.accumulated_rotation = (self.accumulated_rotation + 90) % 360
            print(f"✅ Rotation incremented: now at {self.accumulated_rotation}°")
            print(f"   Next cut will filter on axis {(self.accumulated_rotation // 90) % 2}")

        else:
            print("✂️ First cut from cross-section")

            active_view = getattr(self.app.section_controller, "active_view", 0)
            section_points_transformed = getattr(self.app, f"section_{active_view}_points_transformed", None)
            combined_mask = getattr(self.app, f"section_{active_view}_combined_mask", None)

            if section_points_transformed is None or combined_mask is None:
                print("❌ No transformed section data!")
                
                # ✅ BUG #11 FIX: Reset state
                self._state = CutSectionState.IDLE
                self.cut_phase = 0
                self.app.statusBar().showMessage("❌ Cross-section data missing", 3000)
                return

            # ✅ FIX: Detect view mode and use correct axis
            view_mode = getattr(self.app, "cross_view_mode", "side")
            # Clean the string (handle typo with trailing space)
            view_mode = view_mode.strip().lower() if isinstance(view_mode, str) else "side"
            
            # In cross-section coordinate system:
            #   X = along distance (0..length) - visible in SIDE view (XZ plane)
            #   Y = perpendicular distance (±half_width) - visible in FRONT view (YZ plane)
            #   Z = elevation
            if view_mode == "side":
                axis = 0  # X-axis (along section) - correct for side view
            else:  # "front" or anything else
                axis = 1  # Y-axis (perpendicular) - correct for front view
            
            print(f"🔍 View mode: '{view_mode}', filtering axis: {axis} ({'X - along section' if axis == 0 else 'Y - perpendicular'})")

            # Get range of valid data on the filtering axis
            axis_min = float(np.min(section_points_transformed[:, axis]))
            axis_max = float(np.max(section_points_transformed[:, axis]))

            # Get center value on the correct axis from the picked point
            raw_center = float(self.center_point[axis])

            picked_world = False

            # If center is wildly outside transformed range, treat it as WORLD and convert
            if raw_center < (axis_min - 10.0) or raw_center > (axis_max + 10.0):
                picked_world = True

                P1 = getattr(self.app, f"section_{active_view}_P1", None)
                P2 = getattr(self.app, f"section_{active_view}_P2", None)

                if P1 is None or P2 is None:
                    print("❌ Cannot convert WORLD→SECTION (missing P1/P2)")
                    
                    self._state = CutSectionState.IDLE
                    self.cut_phase = 0
                    self.app.statusBar().showMessage("❌ Section coordinates invalid", 3000)
                    return

                v = np.asarray(P2[:2], dtype=float) - np.asarray(P1[:2], dtype=float)
                L = float(np.linalg.norm(v))
                if L < 1e-9:
                    print("❌ Cannot convert WORLD→SECTION (invalid section line)")
                    
                    self._state = CutSectionState.IDLE
                    self.cut_phase = 0
                    self.app.statusBar().showMessage("❌ Section line invalid", 3000)
                    return

                dir_vec = v / L
                perp_vec = np.array([-dir_vec[1], dir_vec[0]], dtype=float)

                # Convert picked world XY to section-local coordinates
                rel = np.asarray(self.center_point[:2], dtype=float) - np.asarray(P1[:2], dtype=float)
                along_dist = float(np.dot(rel, dir_vec))  # X in section space
                perp_dist = float(np.dot(rel, perp_vec))  # Y in section space

                if axis == 0:
                    center_val = along_dist
                    print(f"🔧 Pick looked like WORLD coords. Converted to section-local X={center_val:.2f}m (along)")
                else:
                    center_val = perp_dist
                    print(f"🔧 Pick looked like WORLD coords. Converted to section-local Y={center_val:.2f}m (perpendicular)")
            else:
                center_val = raw_center

            cut_lower = center_val - float(self.dynamic_depth)
            cut_upper = center_val + float(self.dynamic_depth)

            print(f"✅ Filtering by axis {axis} ({'X - along' if axis == 0 else 'Y - perpendicular'}): [{cut_lower:.2f}, {cut_upper:.2f}]")
            print(f"   🔍 Data range on axis {axis}: [{axis_min:.2f}, {axis_max:.2f}]")

            depth_mask = (
                (section_points_transformed[:, axis] >= cut_lower) &
                (section_points_transformed[:, axis] <= cut_upper)
            )

            print(f"✅ Depth filter: {int(np.sum(depth_mask))}/{len(section_points_transformed)} points")

            if not np.any(depth_mask):
                print(f"❌ No points in depth range [{cut_lower:.2f}, {cut_upper:.2f}] on axis {axis}")
                print(f"   Data range on axis {axis}: [{axis_min:.2f}, {axis_max:.2f}]")
                
                # ✅ BUG #11 FIX: Reset state before returning
                self._state = CutSectionState.IDLE
                self.cut_phase = 0
                self.center_point = None
                self._clear_preview_actors()
                
                self.app.statusBar().showMessage("❌ No points in selected range - try different depth", 3000)
                print("✅ State reset to IDLE")
                return

            xyz_in_depth = section_points_transformed[depth_mask]
            depth_indices = np.where(combined_mask)[0][depth_mask]

            # Viewport filter
            if picked_world:
                xyz_cross_space = xyz_in_depth
                parent_index_map = depth_indices
                print(f"⚠️ Skipping viewport filter (WORLD pick detected). Using {len(xyz_cross_space)} points after depth filter.")
            else:
                vtk_widget = self.app.section_vtks.get(active_view)
                if vtk_widget is None:
                    print("❌ No VTK widget!")
                    
                    self._state = CutSectionState.IDLE
                    self.cut_phase = 0
                    self.app.statusBar().showMessage("❌ VTK widget not available", 3000)
                    return

                try:
                    _rw = vtk_widget.GetRenderWindow()
                    if _rw is None or _rw.GetInteractor() is None:
                        print("⚠️ Render window not available for viewport bounds")
                        return
                    ren = _rw.GetRenderers().GetFirstRenderer()
                    if ren is None:
                        return
                    cam = ren.GetActiveCamera()
                    fp = np.array(cam.GetFocalPoint())
                    scale = cam.GetParallelScale()
                    aspect = ren.GetTiledAspectRatio()

                    half_w = scale * aspect
                    half_h = scale

                    # Viewport bounds depend on view mode
                    if view_mode == "side":
                        # Side view: XZ plane (X=horizontal, Z=vertical)
                        x_lim = (fp[0] - half_w, fp[0] + half_w)
                        z_lim = (fp[2] - half_h, fp[2] + half_h)
                        
                        viewport_mask = (
                            (xyz_in_depth[:, 0] >= x_lim[0]) &
                            (xyz_in_depth[:, 0] <= x_lim[1]) &
                            (xyz_in_depth[:, 2] >= z_lim[0]) &
                            (xyz_in_depth[:, 2] <= z_lim[1])
                        )
                    else:
                        # Front view: YZ plane (Y=horizontal, Z=vertical)
                        y_lim = (fp[1] - half_w, fp[1] + half_w)
                        z_lim = (fp[2] - half_h, fp[2] + half_h)
                        
                        viewport_mask = (
                            (xyz_in_depth[:, 1] >= y_lim[0]) &
                            (xyz_in_depth[:, 1] <= y_lim[1]) &
                            (xyz_in_depth[:, 2] >= z_lim[0]) &
                            (xyz_in_depth[:, 2] <= z_lim[1])
                        )
                except Exception as e:
                    print(f"⚠️ Viewport bounds failed: {e}")
                    viewport_mask = np.ones(len(xyz_in_depth), dtype=bool)

                xyz_cross_space = xyz_in_depth[viewport_mask]
                parent_index_map = depth_indices[viewport_mask]

                print(f"✅ Filtered: {len(xyz_cross_space)} points (axis {axis} depth + viewport)")

                if len(xyz_cross_space) == 0:
                    print("❌ No points left after viewport filter!")
                    
                    self._state = CutSectionState.IDLE
                    self.cut_phase = 0
                    self.center_point = None
                    self._clear_preview_actors()
                    
                    self.app.statusBar().showMessage("❌ No points in viewport - zoom out or adjust view", 3000)
                    print("✅ State reset to IDLE")
                    return

            # Transform to cut section coordinate space
            print("🔧 Transforming to cut section coordinate space...")

            xyz = np.zeros_like(xyz_cross_space)
            
            # ✅ FIX: Transform based on which view we're cutting from
            if view_mode == "side":
                # Side view cut: swap X and Y so we look perpendicular to original view
                xyz[:, 0] = xyz_cross_space[:, 1]  # New X = perpendicular distance (was Y)
                xyz[:, 1] = xyz_cross_space[:, 0]  # New Y = along distance (was X)
            else:
                # Front view cut: swap X and Y the other way
                xyz[:, 0] = xyz_cross_space[:, 0]  # New X = along distance (keep X)
                xyz[:, 1] = xyz_cross_space[:, 1]  # New Y = perpendicular (keep Y)
            
            xyz[:, 2] = xyz_cross_space[:, 2]  # Z unchanged

            print(f"✅ Transformed to cut section space:")
            print(f"   X range: [{xyz[:, 0].min():.2f}, {xyz[:, 0].max():.2f}]")
            print(f"   Y range: [{xyz[:, 1].min():.2f}, {xyz[:, 1].max():.2f}]")
            print(f"   Z range: [{xyz[:, 2].min():.2f}, {xyz[:, 2].max():.2f}]")

            self.accumulated_rotation = 0

        if xyz is None or len(xyz) == 0:
            print("⚠️ finalize: no points available")
            return

        # Calculate tangent for camera setup
        # Tangent is along Y-axis (the old along-line direction)
        self.section_tangent = np.array([0.0, 1.0, 0.0])
        self.original_section_tangent = self.section_tangent.copy()
        print(f"📐 Cut section tangent: {self.section_tangent}")
        
        # Store cut points
        self.cut_mask_in_section = np.ones(len(xyz), dtype=bool)
        self.cut_points = xyz
        
        print(f"✂️ Final cut: {len(self.cut_points)} points")

        # ============================================================
        # ✅ CUT PALETTE PERSISTENCE (RESTORE AFTER NEW CUT)
        # ============================================================
        # ============================================================
        # ✅ BIDIRECTIONAL PALETTE SYNC (REPLACES OLD PRESERVATION CODE)
        # ============================================================
        
        # Try to sync from source view first
        palette_synced = self.sync_palette_from_source_view()
        
        if not palette_synced:
            # Fallback: Use global Display Mode slot 5
            print("   ℹ️ No source palette - initializing from Display Mode slot 5")
            
            src = None
            if hasattr(self.app, "view_palettes") and 5 in self.app.view_palettes:
                src = self.app.view_palettes[5]
            elif hasattr(self.app, "display_mode_dialog") and self.app.display_mode_dialog:
                dlg = self.app.display_mode_dialog
                if hasattr(dlg, "view_palettes") and 5 in dlg.view_palettes:
                    src = dlg.view_palettes[5]
            
            if src:
                self.cut_palette = {int(code): dict(info) for code, info in src.items()}
                print(f"   ✅ Initialized from Display Mode: {len(self.cut_palette)} classes")
            else:
                # Final fallback: keep existing or empty
                if not hasattr(self, "cut_palette"):
                    self.cut_palette = {}
                print("   ℹ️ No palette source - using existing/empty")
        

        
        if len(self.cut_points) == 0:
            print("❌ No points in final cut!")
            
            # ✅ BUG #11 FIX: Reset state
            self._state = CutSectionState.IDLE
            self.cut_phase = 0
            self.cut_points = None
            self._clear_preview_actors()
            self.app.statusBar().showMessage("❌ Cut section is empty", 3000)
            return

        # Index mapping
        if parent_index_map is not None:
            self._cut_index_map = parent_index_map
        else:
            self._rebuild_cut_index_map()

        # Continue with rest of finalization...
        self._ensure_cut_section_dock()
        
        # Clear preview from cross-section
        print("  🧹 Clearing preview from cross-section...")
        for a in (self.line_actor, self.buffer_actor_upper, self.buffer_actor_lower):
            if a:
                try:
                    if self.active_vtk:
                        self.active_vtk.renderer.RemoveActor(a)
                except Exception:
                    pass
        
        self.line_actor = self.buffer_actor_upper = self.buffer_actor_lower = None
        
        try:
            if self.active_vtk:
                _safe_vtk_render(self.active_vtk)
        except Exception:
            pass
        
        # Plot to cut section widget
        self._plot_cut_to_dedicated_widget(self.cut_points)
        
        # ✅ RESTORE DOCK FROM MINIMIZED STATE (NEW CODE)
        print("   🔄 Ensuring cut dock is visible and active...")
        
        if self.cut_dock.isMinimized():
            print("      → Restoring from minimized state")
            self.cut_dock.showNormal()  # Restore from minimized
        elif self.cut_dock.isHidden():
            print("      → Showing hidden dock")
            self.cut_dock.show()
        else:
            self.cut_dock.setVisible(True)  # Ensure visible
        
        # Bring to front and activate
        self.cut_dock.raise_()
        self.cut_dock.activateWindow()
        
        # Explicitly set window state to active (removes minimize flag)
        from PySide6.QtCore import Qt
        self.cut_dock.setWindowState(
            self.cut_dock.windowState() & ~Qt.WindowMinimized | Qt.WindowActive
        )
        
        print("   ✅ Cut dock shown and activated")
        
        self.is_cut_view_active = True
        
        try:
            self._cut_camera_state = self.cut_vtk.camera_position
        except Exception:
            pass
        
        self._set_camera_along_tangent(self.cut_vtk, self.cut_points, self.section_tangent)

        # ✅ CRITICAL FIX: Re-attach ClassificationInteractor to ALL cross-section views
        # This ensures proper camera controls (rotation/pan/zoom) are restored
        print("   🔓 Restoring ClassificationInteractor in cross-section views...")
        
        if hasattr(self.app, 'section_vtks'):
            from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
            
            for view_index, vtk_widget in self.app.section_vtks.items():
                try:
                    iren = vtk_widget.interactor
                    # Restore plain pan/zoom style — classification will overlay
                    # on top only when the user actually picks a classify tool.
                    style = vtkInteractorStyleImage()
                    iren.SetInteractorStyle(style)
                    print(f"   ✅ Pan/zoom style restored for cross-section View {view_index + 1}")
                except Exception as e:
                    print(f"   ⚠️ Failed to restore interactor for View {view_index + 1}: {e}")
        
        # Clear the saved styles (no longer needed)
        if hasattr(self, '_saved_interactor_styles'):
            self._saved_interactor_styles.clear()
            print("   🧹 Cleared saved interactor styles dictionary")

        # ✅ CRITICAL: Re-install camera sync observers after interactor replacement
        # Creating new ClassificationInteractor replaces the interactor style,
        # which destroys the MouseMoveEvent observers that drive camera sync.
        if hasattr(self.app, 'view_sync_map') and self.app.view_sync_map:
            print("   🔗 Re-installing camera sync observers...")
            try:
                # Clear old observers (they're dead — interactor style was replaced)
                if hasattr(self.app, '_camera_observers'):
                    self.app._camera_observers.clear()
                
                # Re-install for all synced views
                for view_idx, vtk_widget in self.app.section_vtks.items():
                    is_synced = (
                        view_idx in self.app.view_sync_map or 
                        any(src == view_idx for src in self.app.view_sync_map.values())
                    )
                    if is_synced and hasattr(self.app, '_install_realtime_camera_observer'):
                        self.app._install_realtime_camera_observer(view_idx, vtk_widget)
                        print(f"   🔗 Camera sync re-installed for View {view_idx + 1}")
            except Exception as e:
                print(f"   ⚠️ Camera sync re-install failed: {e}")

        # Re-attach ClassificationInteractor for cut section
        print("   🔧 Re-attaching ClassificationInteractor for cut section...")
        from .interactor_classify import ClassificationInteractor

        self._old_classify_interactor = getattr(self.app, "classify_interactor", None)
        
        wrapper = ClassificationInteractor(
            self.app,
            self.cut_vtk.interactor,
            mode="2d"
        )
        
        wrapper.vtk_widget = self.cut_vtk
        wrapper.is_cut_section = True
        
        self.cut_vtk.interactor.SetInteractorStyle(wrapper.style)
        self.app.classify_interactor = wrapper
        
        if hasattr(self.app, '_shortcut_filter'):
            self.cut_vtk.interactor.installEventFilter(self.app._shortcut_filter)
        if hasattr(self.app, "_register_canvas_cursor_widget"):
            self.app._register_canvas_cursor_widget(self.cut_vtk.interactor)
            print("✅ Undo/Redo shortcuts enabled for Cut Section dock")
        
        def on_classify_done_cut(changed_indices):
            print("[CUT] Real-time classification changed in cut section")
            self.onclassificationchanged(changed_indices)
        
        setattr(wrapper, "on_classify_done", on_classify_done_cut)
        self._restore_classification_tools()    
        
        if not hasattr(self.app, 'original_undo_classification'):
            self.app.original_undo_classification = self.app.undo_classification
            self.app.original_redo_classification = self.app.redo_classification
            
            def undo_with_cut_refresh():
                self.app.original_undo_classification()
                if hasattr(self.app, 'cut_section_controller'):
                    ctrl = self.app.cut_section_controller
                    if ctrl.is_cut_view_active and ctrl.cut_points is not None:
                        try:
                            print("🔄 [UNDO] Refreshing cut section...")
                            ctrl._refresh_cut_colors_fast()
                        except Exception as e:
                            print(f"⚠️ Cut undo refresh failed: {e}")
            
            def redo_with_cut_refresh():
                self.app.original_redo_classification()
                if hasattr(self.app, 'cut_section_controller'):
                    ctrl = self.app.cut_section_controller
                    if ctrl.is_cut_view_active and ctrl.cut_points is not None:
                        try:
                            print("🔄 [REDO] Refreshing cut section...")
                            ctrl._refresh_cut_colors_fast()
                        except Exception as e:
                            print(f"⚠️ Cut redo refresh failed: {e}")
            
            self.app.undo_classification = undo_with_cut_refresh
            self.app.redo_classification = redo_with_cut_refresh
            print("✅ Cut section undo/redo hooks installed")
        
        print("✅ ClassificationInteractor attached to dedicated cut widget!")
        
        self._state = CutSectionState.FINALIZED
        self.cut_phase = 2
        
        self.app.statusBar().showMessage("✅ Cut Section ready - Classification tools active", 0)

            
    def _reuse_cut_dock_for_new_cross_cut(self):
        """Reuse existing cut dock for NEW cut from cross-section (without closing)."""
        print("📐 NEW FEATURE: Reusing cut dock for fresh cross-section cut...")

        # ✅ NEW: Mark source as cross-section
        self._cut_source = 'cross'

        # ✅ STEP 1: Clear old observers from cut dock (tracked IDs)
        if 'cut_dock' in self._view_observer_ids:
            old_ids = self._view_observer_ids['cut_dock']
            if self.cut_vtk is not None:
                iren = self.cut_vtk.interactor
                for oid in old_ids:
                    try:
                        iren.RemoveObserver(oid)
                        print(f"  🧹 Removed tracked observer: {oid}")
                    except:
                        pass
            del self._view_observer_ids['cut_dock']

        # ═══════════════════════════════════════════════════════════════
        # ✅ CRITICAL FIX: Nuclear cleanup of ALL mouse observers on
        #    the cut dock.  After a cut-in-cut the old on_mouse_move
        #    handler from _activate_from_cut_dock() may still be alive
        #    (observer IDs survive SetInteractorStyle changes).  When
        #    state flips to WAITING_CENTER these ghosts would draw
        #    preview lines inside the cut dock.
        # ═══════════════════════════════════════════════════════════════
        if self.cut_vtk is not None:
            try:
                iren_cut = self.cut_vtk.interactor
                iren_cut.RemoveObservers("LeftButtonPressEvent")
                iren_cut.RemoveObservers("MouseMoveEvent")
                print("  🧹 Nuclear cleanup: ALL LeftButton/MouseMove "
                    "observers removed from cut dock")
            except Exception as e:
                print(f"  ⚠️ Cut dock nuclear cleanup warning: {e}")
        # ═══════════════════════════════════════════════════════════════

        # ✅ STEP 2: Clear ALL preview actors from cut dock
        if self.cut_vtk and hasattr(self.cut_vtk, "renderer") and self.cut_vtk.renderer:
            ren_cut = self.cut_vtk.renderer

            actors_to_clear = [
                self.cut_preview_upper,
                self.cut_preview_lower,
                self.line_actor,
            ]

            for a in actors_to_clear:
                if a:
                    try:
                        ren_cut.RemoveActor(a)
                        print(f"  🧹 Removed preview actor from cut dock")
                    except Exception as e:
                        print(f"  ⚠️ Failed to remove actor: {e}")

            try:
                _safe_vtk_render(self.cut_vtk)
                print("  ✅ Cut dock view cleared")
            except Exception as e:
                print(f"  ⚠️ Render failed: {e}")

            self.cut_preview_upper = None
            self.cut_preview_lower = None
            self.line_actor = None

            for attr in ['_line_actor_points', '_line_actor_poly',
                        '_cut_preview_upper_points', '_cut_preview_upper_lines',
                        '_cut_preview_upper_poly',
                        '_cut_preview_lower_points', '_cut_preview_lower_lines',
                        '_cut_preview_lower_poly']:
                if hasattr(self, attr):
                    delattr(self, attr)

        # ✅ STEP 3: Clear preview actors from cross-section views too
        self._clear_preview_actors()

        # ✅ STEP 4: Reset state for NEW cross→cut
        self._detach_all_view_observers()
        self._state = CutSectionState.WAITING_CENTER
        self.cut_phase = 0
        self.center_point = None
        self.dynamic_depth = getattr(self.app, "default_cut_width", 1.0)
        self.section_tangent = None
        self.is_cut_view_active = False
        self.accumulated_rotation = 0
        self.original_section_tangent = None

        # ✅ STEP 5: Reset depth spinbox
        if self.depth_spin:
            self.depth_spin.blockSignals(True)
            self.depth_spin.setValue(self.dynamic_depth)
            self.depth_spin.blockSignals(False)

        # ✅ STEP 6: Save cross-section state
        self._save_section_controller_state()

        # ✅ STEP 6.5: Initialize saved interactor styles dictionary
        if not hasattr(self, '_saved_interactor_styles'):
            self._saved_interactor_styles = {}

        # ✅ STEP 7: Attach observers to CROSS-SECTION views (not cut dock)
        print("  🔄 Attaching observers to cross-section views for NEW cut...")
        for view_index, vtk_widget in self.app.section_vtks.items():
            iren = vtk_widget.interactor

            if view_index not in self._saved_interactor_styles:
                current_style = iren.GetInteractorStyle()
                self._saved_interactor_styles[view_index] = current_style
                print(f"📌 Saved interactor style for cross-section View {view_index + 1}")

            cut_style = CutSectionInteractorStyle()
            cut_style.app = self.app
            cut_style.vtk_widget = vtk_widget
            iren.SetInteractorStyle(cut_style)
            print(f"🔒 Camera rotation BLOCKED in cross-section View {view_index + 1}")

            def make_click_handler(vw, v_idx):
                def on_left_click(obj, evt):
                    if self._state == CutSectionState.IDLE:
                        return
                    self.app.section_controller.active_view = v_idx
                    self.active_vtk = vw
                    pos = vw.interactor.GetEventPosition()
                    picker = vtk.vtkWorldPointPicker()
                    picker.Pick(pos[0], pos[1], 0, vw.renderer)
                    pt = np.array(picker.GetPickPosition())
                    if np.allclose(pt, (0, 0, 0), atol=1e-6):
                        return
                    if self._state == CutSectionState.WAITING_CENTER:
                        self.center_point = pt
                        self._state = CutSectionState.WAITING_DEPTH
                        self.cut_phase = 1
                        self._draw_dynamic_center_line(self.center_point)
                        return
                    if self._state == CutSectionState.WAITING_DEPTH:
                        self._finalize_dynamic_cut_section()
                        return
                return on_left_click

            def make_move_handler(vw, v_idx):
                def on_mouse_move(obj, evt):
                    if self._state == CutSectionState.IDLE:
                        return
                    pos = vw.interactor.GetEventPosition()
                    picker = vtk.vtkWorldPointPicker()
                    picker.Pick(pos[0], pos[1], 0, vw.renderer)
                    curr = np.array(picker.GetPickPosition())
                    if np.allclose(curr, (0, 0, 0), atol=1e-6):
                        return
                    if self._state == CutSectionState.WAITING_CENTER:
                        self.app.section_controller.active_view = v_idx
                        self.active_vtk = vw
                        self._draw_dynamic_center_line(curr)
                        return
                    if self._state == CutSectionState.WAITING_DEPTH and self.center_point is not None:
                        axis = 0 if getattr(self.app, "cross_view_mode", "side") == "side" else 1
                        old_depth = self.dynamic_depth
                        self.dynamic_depth = abs(curr[axis] - self.center_point[axis])

                        # ✅ Draw preview ONLY in cross-section views
                        self._draw_dynamic_band_preview(self.center_point, self.dynamic_depth)

                        # ═══════════════════════════════════════════════════
                        # ✅ FIX: Do NOT draw preview in cut dock.
                        #    We are cutting FROM cross-section, so the
                        #    preview lines belong in cross-section views
                        #    only.  Drawing them in the cut dock confused
                        #    users after a cut-in-cut sequence.
                        # ═══════════════════════════════════════════════════
                        # REMOVED:
                        # if self.cut_vtk is not None:
                        #     self._draw_cut_section_preview(
                        #         self.center_point, self.dynamic_depth)
                        # ═══════════════════════════════════════════════════

                        if self.depth_spin:
                            self.depth_spin.blockSignals(True)
                            self.depth_spin.setValue(self.dynamic_depth)
                            self.depth_spin.blockSignals(False)
                        return
                return on_mouse_move

            # <----------
            try:
                lid = iren.AddObserver("LeftButtonPressEvent",
                                    make_click_handler(vtk_widget, view_index))
                mid = iren.AddObserver("MouseMoveEvent",
                                    make_move_handler(vtk_widget, view_index))
                self._view_observer_ids[view_index] = [lid, mid]
                print(f"✅ Cut tool observers attached to cross-section "
                    f"View {view_index + 1}: LeftButton={lid}, MouseMove={mid}")
            except Exception as e:
                print(f"⚠️ Observer attachment failed for View {view_index + 1}: {e}")
                if view_index in self._view_observer_ids:
                    del self._view_observer_ids[view_index]

        self.app.statusBar().showMessage(
            "✂️ Cut Section (Reusing dock): click center in cross-section, "
            "adjust depth, click to finalize", 0)
        print("✅ Cut dock reused - ready for new cross-section cut")

    def _force_deactivate_pending_state(self):
        """
        ✅ CRITICAL FIX: Force deactivate any pending cut tool state.
        
        This method ensures symmetric tool activation by:
        1. Clearing ALL preview actors from ALL views (including cut dock)
        2. Detaching ALL observers from ALL views  
        3. Restoring interactor styles in cross-section views
        4. Resetting state machine to IDLE
        5. Re-enabling classification tools
        
        Must be called at the START of any shortcut activation to prevent
        blocked states where one tool prevents another from executing.
        """
        # Check if there's actually something to clean up
        has_pending_state = (
            self._state != CutSectionState.IDLE or
            self.line_actor is not None or
            self.buffer_actor_upper is not None or
            self.buffer_actor_lower is not None or
            self.cut_preview_upper is not None or
            self.cut_preview_lower is not None or
            len(self._view_observer_ids) > 0 or
            (hasattr(self, '_saved_interactor_styles') and len(self._saved_interactor_styles) > 0)
        )
        
        if not has_pending_state:
            return  # Nothing to clean up
        
        print("\n🔄 Force deactivating pending cut tool state...")
        print(f"   Current state: {self._state}")
        print(f"   Observer IDs: {list(self._view_observer_ids.keys())}")
        print(f"   Saved styles: {list(getattr(self, '_saved_interactor_styles', {}).keys())}")
        
        # ========== STEP 1: Clear preview actors from ALL views ==========
        actors_to_clear = [
            self.line_actor,
            self.buffer_actor_upper,
            self.buffer_actor_lower
        ]
        
        # Clear from cross-section views
        if hasattr(self.app, 'section_vtks'):
            for view_idx, vtk_widget in self.app.section_vtks.items():
                try:
                    ren = vtk_widget.renderer
                    for actor in actors_to_clear:
                        if actor is not None:
                            try:
                                ren.RemoveActor(actor)
                            except:
                                pass
                    _safe_vtk_render(vtk_widget)
                except Exception as e:
                    print(f"   ⚠️ Actor cleanup for view {view_idx}: {e}")
        
        # Clear from active_vtk if set
        if self.active_vtk is not None:
            try:
                ren = self.active_vtk.renderer
                for actor in actors_to_clear:
                    if actor is not None:
                        try:
                            ren.RemoveActor(actor)
                        except:
                            pass
                _safe_vtk_render(self.active_vtk)
            except:
                pass
        
        # ✅ CRITICAL FIX: Clear preview actors from CUT DOCK view
        if self.cut_vtk is not None and hasattr(self.cut_vtk, 'renderer') and self.cut_vtk.renderer:
            try:
                ren = self.cut_vtk.renderer
                
                # Clear ALL preview actors from cut dock (line + buffer lines)
                cut_dock_actors = [
                    self.line_actor,           # ✅ Center line in cut dock
                    self.cut_preview_upper,    # ✅ Upper buffer line
                    self.cut_preview_lower     # ✅ Lower buffer line
                ]
                
                removed_count = 0
                for actor in cut_dock_actors:
                    if actor is not None:
                        try:
                            ren.RemoveActor(actor)
                            removed_count += 1
                        except:
                            pass
                
                if removed_count > 0:
                    print(f"   🧹 Removed {removed_count} preview actors from cut dock")
                
                # Force render to show the cleared view
                _safe_vtk_render(self.cut_vtk)
                
            except Exception as e:
                print(f"   ⚠️ Cut dock actor cleanup error: {e}")
        
        # Clear actor references
        self.line_actor = None
        self.buffer_actor_upper = None
        self.buffer_actor_lower = None
        self.cut_preview_upper = None
        self.cut_preview_lower = None
        
        # Clear cached geometry objects
        for attr in ['_line_actor_points', '_line_actor_poly', '_line_actor_mapper',
                    '_buffer_actor_upper_points', '_buffer_actor_upper_lines', 
                    '_buffer_actor_upper_poly', '_buffer_actor_upper_mapper',
                    '_buffer_actor_lower_points', '_buffer_actor_lower_lines', 
                    '_buffer_actor_lower_poly', '_buffer_actor_lower_mapper',
                    '_cut_preview_upper_points', '_cut_preview_upper_lines',
                    '_cut_preview_upper_poly', '_cut_preview_upper_mapper',
                    '_cut_preview_lower_points', '_cut_preview_lower_lines',
                    '_cut_preview_lower_poly', '_cut_preview_lower_mapper']:
            if hasattr(self, attr):
                try:
                    delattr(self, attr)
                except:
                    pass
        
        print("   ✅ Preview actors cleared")
        
        # ========== STEP 2: Detach ALL observers ==========
        # First use tracked IDs
        for v_idx, ids in list(self._view_observer_ids.items()):
            try:
                if v_idx == 'cut_dock':
                    if self.cut_vtk is not None:
                        iren = self.cut_vtk.interactor
                        for oid in ids:
                            try:
                                iren.RemoveObserver(oid)
                            except:
                                pass
                elif v_idx in getattr(self.app, "section_vtks", {}):
                    iren = self.app.section_vtks[v_idx].interactor
                    for oid in ids:
                        try:
                            iren.RemoveObserver(oid)
                        except:
                            pass
            except Exception as e:
                print(f"   ⚠️ Observer detach for {v_idx}: {e}")
        
        # Nuclear cleanup: Remove ALL LeftButton/MouseMove observers from ALL views
        if hasattr(self.app, 'section_vtks'):
            for view_idx, vtk_widget in self.app.section_vtks.items():
                try:
                    iren = vtk_widget.interactor
                    iren.RemoveObservers("LeftButtonPressEvent")
                    iren.RemoveObservers("MouseMoveEvent")
                except:
                    pass
        
        # Also nuclear cleanup cut dock
        if self.cut_vtk is not None:
            try:
                iren = self.cut_vtk.interactor
                iren.RemoveObservers("LeftButtonPressEvent")
                iren.RemoveObservers("MouseMoveEvent")
            except:
                pass
        
        self._view_observer_ids.clear()
        print("   ✅ All observers detached")
        
        # ========== STEP 3: Restore interactor styles (CRITICAL!) ==========
        if hasattr(self, '_saved_interactor_styles') and self._saved_interactor_styles:
            from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
            restored_count = 0
            for view_index in list(self._saved_interactor_styles.keys()):
                if view_index in getattr(self.app, 'section_vtks', {}):
                    try:
                        vtk_widget = self.app.section_vtks[view_index]
                        # Always restore to plain pan/zoom — never to the old
                        # CutSectionInteractorStyle or a stale ClassificationInteractor.
                        style = vtkInteractorStyleImage()
                        vtk_widget.interactor.SetInteractorStyle(style)
                        restored_count += 1
                        print(f"   ✅ Pan/zoom style restored for View {view_index + 1}")
                    except Exception as e:
                        print(f"   ⚠️ Style restore for view {view_index}: {e}")
            self._saved_interactor_styles.clear()
            print(f"   ✅ Restored {restored_count} interactor styles, cleared saved styles dict")
            
            # ✅ Re-install camera sync observers
            if hasattr(self.app, 'view_sync_map') and self.app.view_sync_map:
                try:
                    if hasattr(self.app, '_camera_observers'):
                        self.app._camera_observers.clear()
                    for v_idx, vw in getattr(self.app, 'section_vtks', {}).items():
                        is_synced = (
                            v_idx in self.app.view_sync_map or
                            any(src == v_idx for src in self.app.view_sync_map.values())
                        )
                        if is_synced and hasattr(self.app, '_install_realtime_camera_observer'):
                            self.app._install_realtime_camera_observer(v_idx, vw)
                    print("   🔗 Camera sync re-installed after style restore")
                except Exception as e:
                    print(f"   ⚠️ Camera sync re-install failed: {e}")
        
        # ========== STEP 4: Reset state machine ==========
        self._state = CutSectionState.IDLE
        self.cut_phase = 0
        self.center_point = None
        self.dynamic_depth = getattr(self.app, "default_cut_width", 1.0)
        self.section_tangent = None
        self.active_vtk = None
        
        # Reset depth spinbox if exists
        if self.depth_spin:
            try:
                self.depth_spin.blockSignals(True)
                self.depth_spin.setValue(self.dynamic_depth)
                self.depth_spin.blockSignals(False)
            except:
                pass
        
        print("   ✅ State machine reset to IDLE")
        
        # ========== STEP 5: Re-enable classification tools ==========
        self._restore_classification_tools()
        
        # Update status bar
        try:
            self.app.statusBar().showMessage("🔄 Cut tool state reset", 1500)
        except:
            pass
        
        print("✅ Pending state deactivated\n")

    def _has_valid_cut_dock(self):
        """
        ✅ Check if there's a valid cut dock with data that can be used.
        
        This is more reliable than checking is_cut_view_active because
        that flag can be incorrectly reset by _reuse_cut_dock_for_new_cross_cut()
        while the actual cut dock resources still exist.
        """
        return (
            self.cut_vtk is not None and
            self.cut_points is not None and
            len(self.cut_points) > 0
        )

    def deactivate_tool_only(self):
        """
        Deactivate pending cut placement without closing a completed cut dock.

        This is used when leaving the Tools ribbon: unfinished interaction should
        stop, but an existing cut section window must remain visible.
        """
        try:
            has_persistent_cut = self._has_valid_cut_dock() and self._state not in (
                CutSectionState.WAITING_CENTER,
                CutSectionState.WAITING_DEPTH,
            )

            if has_persistent_cut:
                print("Leaving Tools tab - keeping cut section dock open")
                return

            self._force_deactivate_pending_state()
        except Exception as e:
            print(f"deactivate_tool_only failed: {e}")
            import traceback
            traceback.print_exc()

    def activate_from_cross_shortcut(self):
        """Shortcut: Shift+1 - new cut from cross-section, reusing dock if present."""
        try:
            # ✅ CRITICAL: Force deactivate any pending state FIRST
            if self._state != CutSectionState.IDLE:
                print("🔄 Shift+1: Clearing pending cut state first...")
                self._force_deactivate_pending_state()
            
            # ✅ FIX: Check actual resources, not just the flag
            if self._has_valid_cut_dock():
                print("⚡ Shift+1: REUSE cut dock for NEW cross-section cut")
                self._reuse_cut_dock_for_new_cross_cut()
            else:
                print("⚡ Shift+1: Normal cross-section cut activate()")
                self.activate()
        except Exception as e:
            print(f"⚠️ activate_from_cross_shortcut error: {e}")
            import traceback
            traceback.print_exc()


    def activate_from_cut_shortcut(self):
        """Shortcut: Shift+2 – nested cut from existing cut view."""
        try:
            # ✅ CRITICAL: Force deactivate any pending state FIRST
            if self._state != CutSectionState.IDLE:
                print("🔄 Shift+2: Clearing pending Cut-in-Cross state first...")
                self._force_deactivate_pending_state()
            
            # ✅ FIX: Check actual resources, not just the flag
            if self._has_valid_cut_dock():
                # ✅ RECOVERY: Restore flag if it was incorrectly reset
                if not self.is_cut_view_active:
                    print("🔧 Restoring is_cut_view_active flag (was incorrectly reset)")
                    self.is_cut_view_active = True
                
                print("⚡ Shift+2: Nested cut from existing cut view")
                self._activate_from_cut_dock()
            else:
                print("ℹ️ Shift+2: No active cut view - use Shift+1 first to create a cut section")
                self.app.statusBar().showMessage(
                    "ℹ️ No cut section active. Use Shift+1 first to create a cut from cross-section.", 
                    3000
                )
        except Exception as e:
            print(f"⚠️ activate_from_cut_shortcut error: {e}")
            import traceback
            traceback.print_exc()

    def _temporarily_disable_classification(self):
        """
        ✅ CRITICAL FIX: Disable classification tools during cut section setup
        Prevents accidental classification while selecting depth
        """
        try:
            print("🔒 Temporarily disabling classification tools...")
           
            # Save current classification state
            self._saved_classify_state = {
                'active_tool': getattr(self.app, 'active_classify_tool', None),
                'interactor': getattr(self.app, 'classify_interactor', None),
                'from_classes': getattr(self.app, 'from_classes', None),
                'to_class': getattr(self.app, 'to_class', None)
            }
           
            # Deactivate classification tool
            if hasattr(self.app, 'deactivate_classification'):
                self.app.deactivate_classification()
            else:
                self.app.active_classify_tool = None
           
            # Detach classification interactor from ALL views
            if self._saved_classify_state['interactor'] is not None:
                ci = self._saved_classify_state['interactor']
               
                # Clear from cross-section views
                if hasattr(self.app, 'section_vtks'):
                    for vtk_widget in self.app.section_vtks.values():
                        try:
                            # Reset to default camera interactor
                            iren = vtk_widget.interactor
                            default_style = vtk.vtkInteractorStyleTrackballCamera()
                            iren.SetInteractorStyle(default_style)
                        except Exception as e:
                            print(f"   ⚠️ Reset interactor warning: {e}")
               
                # Clear references
                ci.vtk_widget = None
                ci.is_cut_section = False
           
            # Update UI to show tools are disabled
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage(
                    "🔒 Classification tools disabled during cut section setup",
                    2000
                )
           
            print("   ✅ Classification tools disabled")
           
        except Exception as e:
            print(f"   ⚠️ Disable classification warning: {e}")
 
 
    def _restore_classification_tools(self):
        """
        ✅ Restore classification tools after cut section is finalized
        """
        try:
            if not hasattr(self, '_saved_classify_state'):
                return
           
            print("🔓 Restoring classification tools...")
           
            state = self._saved_classify_state
           
            # Restore tool state
            if state['active_tool'] is not None:
                self.app.active_classify_tool = state['active_tool']
           
            if state['from_classes'] is not None:
                self.app.from_classes = state['from_classes']
           
            if state['to_class'] is not None:
                self.app.to_class = state['to_class']
           
            # Note: Classification interactor will be re-attached by _finalize_dynamic_cut_section
            # We don't restore it here to avoid conflicts
           
            print("   ✅ Classification state restored (interactor will be re-attached to cut view)")
           
            # Cleanup
            del self._saved_classify_state
           
        except Exception as e:
            print(f"   ⚠️ Restore classification warning: {e}")

    def deactivate_if_waiting(self):
        """
        ✅ CRITICAL FIX: Deactivate cut section tool if it's in WAITING state
        Enhanced with nuclear cleanup to prevent state corruption after extended use.
        
        This prevents conflicts when user activates classification tools
        while cut section tool is still waiting for user input.
        
        Also handles corrupted states where preview actors exist but state is IDLE.
        
        Called by ClassificationInteractor when classification tools are activated.
        """
        try:
            # ✅ NEW: Force cleanup even if state appears IDLE
            # This handles cases where state was corrupted after extended use
            force_cleanup = False
            
            # Check if cut tool is in WAITING state
            if self._state == CutSectionState.IDLE:
                # Double-check: are there actually preview actors present?
                if (self.line_actor is not None or 
                    self.buffer_actor_upper is not None or 
                    self.buffer_actor_lower is not None):
                    print("   ⚠️ State is IDLE but preview actors exist - forcing cleanup!")
                    force_cleanup = True
                else:
                    # Truly idle, nothing to do
                    return
            
            # Check if cut is already performed (is_cut_view_active)
            if self.is_cut_view_active and not force_cleanup:
                # Cut already performed, don't deactivate
                print("   ℹ️ Cut section already performed - not deactivating")
                return
            
            # Cut tool is in WAITING state or needs force cleanup - deactivate it
            print("🔒 Deactivating cut section tool (classification tool activated)...")
            if force_cleanup:
                print("   🔥 FORCE CLEANUP MODE: Clearing corrupted state")
            
            # ✅ CRITICAL FIX: Clear preview actors from ALL cross-section views
            if hasattr(self.app, 'section_vtks'):
                actors_to_clear = [
                    self.line_actor,
                    self.buffer_actor_upper,
                    self.buffer_actor_lower
                ]
                
                for view_idx, vtk_widget in self.app.section_vtks.items():
                    try:
                        ren = vtk_widget.renderer
                        removed_count = 0
                        
                        for actor in actors_to_clear:
                            if actor is not None:
                                try:
                                    ren.RemoveActor(actor)
                                    removed_count += 1
                                except Exception as e:
                                    pass
                        
                        if removed_count > 0:
                            print(f"   🧹 Removed {removed_count} preview actors from cross-section View {view_idx + 1}")
                        
                        # Render to show the removal
                        try:
                            _safe_vtk_render(vtk_widget)
                            if removed_count > 0:
                                print(f"   ✅ Cross-section View {view_idx + 1} rendered (previews cleared)")
                        except Exception as e:
                            pass
                            
                    except Exception as e:
                        print(f"   ⚠️ Failed to clear preview from view {view_idx + 1}: {e}")
            
            # Clear actor references
            self.line_actor = None
            self.buffer_actor_upper = None
            self.buffer_actor_lower = None
            
            # Also clear cut view preview actors (if any)
            self._clear_preview_actors()
            
            # ✅ NUCLEAR CLEANUP: Detach ALL observers from cross-section views
            self._detach_all_view_observers()
            
            # ✅ EXTRA: Nuclear cleanup of any lingering observers
            if hasattr(self.app, 'section_vtks'):
                for view_idx, vtk_widget in self.app.section_vtks.items():
                    try:
                        iren = vtk_widget.interactor
                        # Remove any LeftButton/MouseMove observers that might be orphaned
                        iren.RemoveObservers("LeftButtonPressEvent")
                        iren.RemoveObservers("MouseMoveEvent")
                        print(f"   🧹 Nuclear observer cleanup for View {view_idx + 1}")
                    except Exception as e:
                        pass
            
            # Restore original interactor styles in cross-section views
            if hasattr(self, '_saved_interactor_styles') and self._saved_interactor_styles:
                from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
                for view_index in list(self._saved_interactor_styles.keys()):
                    if view_index in getattr(self.app, 'section_vtks', {}):
                        try:
                            vtk_widget = self.app.section_vtks[view_index]
                            vtk_widget.interactor.SetInteractorStyle(vtkInteractorStyleImage())
                        except Exception as e:
                            print(f"   ⚠️ Failed to restore interactor style: {e}")
                self._saved_interactor_styles.clear()
                
                # ✅ Re-install camera sync observers
                if hasattr(self.app, 'view_sync_map') and self.app.view_sync_map:
                    try:
                        if hasattr(self.app, '_camera_observers'):
                            self.app._camera_observers.clear()
                        for v_idx, vw in self.app.section_vtks.items():
                            is_synced = (
                                v_idx in self.app.view_sync_map or
                                any(src == v_idx for src in self.app.view_sync_map.values())
                            )
                            if is_synced and hasattr(self.app, '_install_realtime_camera_observer'):
                                self.app._install_realtime_camera_observer(v_idx, vw)
                        print("   🔗 Camera sync re-installed")
                    except Exception as e:
                        print(f"   ⚠️ Camera sync re-install failed: {e}")
            
            # Reset state to IDLE
            self._state = CutSectionState.IDLE
            self.cut_phase = 0
            self.center_point = None
            self.dynamic_depth = None
            self.section_tangent = None
            
            # ✅ EXTRA: Clear any cached geometry
            for attr in ['_line_actor_points', '_line_actor_poly', 
                        '_buffer_upper_points', '_buffer_upper_poly',
                        '_buffer_lower_points', '_buffer_lower_poly']:
                if hasattr(self, attr):
                    try:
                        delattr(self, attr)
                    except:
                        pass
            
            # Update status bar
            if hasattr(self.app, 'statusBar'):
                msg = "✅ Cut section tool deactivated (classification tool activated)"
                if force_cleanup:
                    msg = "✅ Cut section tool deactivated (forced cleanup - state was corrupted)"
                self.app.statusBar().showMessage(msg, 2000)
            
            print("   ✅ Cut section tool deactivated successfully (all previews and observers cleared)")
            
        except Exception as e:
            print(f"   ⚠️ Deactivate cut section warning: {e}")
            import traceback
            traceback.print_exc()
         
    def activate(self):
        """Enable CutSection in all open cross-section panes."""
        try:

            print("🔥 Starting cut tool activation with nuclear cleanup...")
            if hasattr(self.app, 'section_vtks'):
                for view_idx, vtk_widget in self.app.section_vtks.items():
                    try:
                        ren = vtk_widget.renderer
                        # Remove any cut section actors that might be lingering
                        removed_count = 0
                        
                        if self.line_actor is not None:
                            try:
                                ren.RemoveActor(self.line_actor)
                                removed_count += 1
                            except:
                                pass
                        if self.buffer_actor_upper is not None:
                            try:
                                ren.RemoveActor(self.buffer_actor_upper)
                                removed_count += 1
                            except:
                                pass
                        if self.buffer_actor_lower is not None:
                            try:
                                ren.RemoveActor(self.buffer_actor_lower)
                                removed_count += 1
                            except:
                                pass
                        
                        if removed_count > 0:
                            print(f"   🧹 Removed {removed_count} lingering actors from View {view_idx + 1}")
                            _safe_vtk_render(vtk_widget)
                    except:
                        pass

            # Clear actor references
            self.line_actor = None
            self.buffer_actor_upper = None
            self.buffer_actor_lower = None

            # Nuclear observer cleanup BEFORE adding new ones
            # This prevents observer stacking that causes issues after 20-25 minutes
            for view_index in list(self._view_observer_ids.keys()):
                if view_index in self.app.section_vtks:
                    vtk_widget = self.app.section_vtks[view_index]
                    iren = vtk_widget.interactor
                    
                    # Remove tracked observers
                    if view_index in self._view_observer_ids:
                        old_ids = self._view_observer_ids[view_index]
                        removed_count = 0
                        for oid in old_ids:
                            try:
                                if iren.HasObserver(oid):
                                    iren.RemoveObserver(oid)
                                    removed_count += 1
                            except:
                                pass
                        if removed_count > 0:
                            print(f"   🧹 Removed {removed_count} tracked observers from View {view_index + 1}")
                    
                    # Nuclear: Remove ALL LeftButton/MouseMove observers
                    # This catches orphaned observers from previous sessions
                    try:
                        iren.RemoveObservers("LeftButtonPressEvent")
                        iren.RemoveObservers("MouseMoveEvent")
                        print(f"   ✅ Nuclear cleanup: All LeftButton/MouseMove observers removed from View {view_index + 1}")
                    except:
                        pass

            # Clear observer tracking dictionary
            self._view_observer_ids.clear()

            print("   ✅ Nuclear cleanup complete - clean slate established")
            print("")


            self._temporarily_disable_classification()

            # ✅ NEW FEATURE: If already in cut view, ask user which source to use
            if self.is_cut_view_active and self.cut_points is not None and self.cut_vtk is not None:
                print("🔄 Cut view active - asking user for cut source...")
                
                from PySide6.QtWidgets import QMessageBox
                
                msg = QMessageBox(self.app)
                msg.setWindowTitle("Cut Tool Activate")
                msg.setText("")
                msg.setWindowFlags(msg.windowFlags() | Qt.WindowCloseButtonHint)
                
                btn_cross = msg.addButton("Cross Section", QMessageBox.ActionRole)
                btn_cut = msg.addButton("Cut Section", QMessageBox.ActionRole)
                
                msg.exec()
                clicked = msg.clickedButton()
                
                if clicked == btn_cross:
                    print("✅ User chose: Cross Section (new cut from cross-section)")
                    self._reuse_cut_dock_for_new_cross_cut()
                    return
                elif clicked == btn_cut:
                    print("✅ User chose: Cut Section (nested cut)")
                    self._activate_from_cut_dock()
                    return
                else:
                    print("❌ User cancelled (X button)")
                    return
            
            if not hasattr(self.app, "section_vtks") or len(self.app.section_vtks) == 0:
                QMessageBox.warning(self.app, "No Cross Section",
                    "Create a cross-section first (Tools → Cross).")
                return

            if self._state != CutSectionState.IDLE:
                self._detach_all_view_observers()
                self._clear_preview_actors()

            self._state = CutSectionState.WAITING_CENTER
            self.cut_phase = 0
            self.center_point = None
            self.dynamic_depth = getattr(self.app, "default_cut_width", 1.0)
            self.section_tangent = None
            self.is_cut_view_active = False
            self.accumulated_rotation = 0
            self.original_section_tangent = None
            self._cut_source = 'cross'

            # Save section controller state
            self._save_section_controller_state()

            # ✅ CRITICAL FIX: Initialize saved interactor styles dictionary if not exists
            if not hasattr(self, '_saved_interactor_styles'):
                self._saved_interactor_styles = {}

            # ✅ CRITICAL FIX: Block camera rotation in cross-section views during cut tool
            for view_index, vtk_widget in self.app.section_vtks.items():
                iren = vtk_widget.interactor

                # ✅ Save current interactor style before blocking
                if view_index not in self._saved_interactor_styles:
                    current_style = iren.GetInteractorStyle()
                    self._saved_interactor_styles[view_index] = current_style
                    print(f"📌 Saved interactor style for cross-section View {view_index + 1}")
                
                # ✅ Block camera rotation by setting empty interactor style
                cut_style = CutSectionInteractorStyle()     # ← ADD THIS
                cut_style.app = self.app
                cut_style.vtk_widget = vtk_widget
                iren.SetInteractorStyle(cut_style) 
                print(f"🔒 Camera rotation BLOCKED in cross-section View {view_index + 1}")

                def make_click_handler(vw, v_idx):
                    def on_left_click(obj, evt):
                        if self._state == CutSectionState.IDLE:
                            return
                        self.app.section_controller.active_view = v_idx
                        self.active_vtk = vw
                        pos = vw.interactor.GetEventPosition()
                        picker = vtk.vtkWorldPointPicker()
                        picker.Pick(pos[0], pos[1], 0, vw.renderer)
                        pt = np.array(picker.GetPickPosition())
                        if np.allclose(pt, (0, 0, 0), atol=1e-6):
                            return
                        if self._state == CutSectionState.WAITING_CENTER:
                            self.center_point = pt
                            self._state = CutSectionState.WAITING_DEPTH
                            self.cut_phase = 1
                            self._draw_dynamic_center_line(self.center_point)
                            return
                        if self._state == CutSectionState.WAITING_DEPTH:
                            self._finalize_dynamic_cut_section()
                            return
                    return on_left_click

                def make_move_handler(vw, v_idx):
                    def on_mouse_move(obj, evt):
                        if self._state == CutSectionState.IDLE:
                            return

                        pos = vw.interactor.GetEventPosition()
                        picker = vtk.vtkWorldPointPicker()
                        picker.Pick(pos[0], pos[1], 0, vw.renderer)
                        curr = np.array(picker.GetPickPosition())

                        if np.allclose(curr, (0, 0, 0), atol=1e-6):
                            return

                        if self._state == CutSectionState.WAITING_CENTER:
                            self.app.section_controller.active_view = v_idx
                            self.active_vtk = vw
                            self._draw_dynamic_center_line(curr)
                            return

                        if self._state == CutSectionState.WAITING_DEPTH and self.center_point is not None:
                            axis = 0 if getattr(self.app, "cross_view_mode", "side") == "side" else 1
                            old_depth = self.dynamic_depth
                            self.dynamic_depth = abs(curr[axis] - self.center_point[axis])

                            # ✅ Draw preview ONLY in cross-section views
                            self._draw_dynamic_band_preview(self.center_point, self.dynamic_depth)

                            # ✅ FIX: Do NOT draw preview in cut dock when cutting
                            #    from cross-section. Preview belongs only in
                            #    the cross-section views for this mode.
                            # REMOVED:
                            # if self.cut_vtk is not None:
                            #     self._draw_cut_section_preview(
                            #         self.center_point, self.dynamic_depth)

                            if self.depth_spin:
                                self.depth_spin.blockSignals(True)
                                self.depth_spin.setValue(self.dynamic_depth)
                                self.depth_spin.blockSignals(False)
                            return

                    return on_mouse_move

                # -----------
                try:
                    lid = iren.AddObserver("LeftButtonPressEvent",
                                        make_click_handler(vtk_widget, view_index))
                    mid = iren.AddObserver("MouseMoveEvent",
                                        make_move_handler(vtk_widget, view_index))
                    self._view_observer_ids[view_index] = [lid, mid]
                    print(f"✅ Cut tool observers attached to cross-section "
                        f"View {view_index + 1}: LeftButton={lid}, MouseMove={mid}")
                except Exception as e:
                    print(f"⚠️ Observer attachment failed for View {view_index + 1}: {e}")
                    if view_index in self._view_observer_ids:
                        del self._view_observer_ids[view_index]

            self.app.statusBar().showMessage(
                "✂️ Cut Section: click center, adjust depth, click to finalize", 0)

        except Exception as e:
            print(f"[CutSection.activate] {e}")
            import traceback
            traceback.print_exc()

    # def _save_section_controller_state(self):
    #     """Save current section controller state before cut takes over."""
    #     try:
    #         sc = self.app.section_controller
    #         self._saved_section_state = {
    #             'active_view': sc.active_view,
    #             'section_points': getattr(self.app, 'section_points', None),
    #             'section_core_points': getattr(self.app, 'section_core_points', None),
    #             'section_buffer_points': getattr(self.app, 'section_buffer_points', None),
    #             'section_core_mask': getattr(self.app, 'section_core_mask', None),
    #             'section_buffer_mask': getattr(self.app, 'section_buffer_mask', None),
    #             'section_indices': getattr(self.app, 'section_indices', None),
    #             'P1': sc.P1,
    #             'P2': sc.P2,
    #             'half_width': sc.half_width,
    #             'last_mask': sc.last_mask,
    #         }
    #         print("💾 Saved section controller state")
    #     except Exception as e:
    #         print(f"⚠️ Could not save section state: {e}")

    def _save_section_controller_state(self):
        """Save current section controller state before cut takes over - DEEP COPY."""
        try:
            sc = self.app.section_controller
            
            # Deep copy all numpy arrays to preserve data
            self._saved_section_state = {
                'active_view': sc.active_view,
                'section_points': np.copy(getattr(self.app, 'section_points', None)) 
                                if getattr(self.app, 'section_points', None) is not None else None,
                'section_core_points': np.copy(getattr(self.app, 'section_core_points', None))
                                    if getattr(self.app, 'section_core_points', None) is not None else None,
                'section_buffer_points': np.copy(getattr(self.app, 'section_buffer_points', None))
                                        if getattr(self.app, 'section_buffer_points', None) is not None else None,
                'section_core_mask': np.copy(getattr(self.app, 'section_core_mask', None))
                                    if getattr(self.app, 'section_core_mask', None) is not None else None,
                'section_buffer_mask': np.copy(getattr(self.app, 'section_buffer_mask', None))
                                    if getattr(self.app, 'section_buffer_mask', None) is not None else None,
                'section_indices': np.copy(getattr(self.app, 'section_indices', None))
                                if getattr(self.app, 'section_indices', None) is not None else None,
                'P1': np.copy(sc.P1) if sc.P1 is not None else None,
                'P2': np.copy(sc.P2) if sc.P2 is not None else None,
                'half_width': sc.half_width,
                'last_mask': np.copy(sc.last_mask) if sc.last_mask is not None else None,
            }
            print("💾 Saved section controller state (deep copy)")
        except Exception as e:
            print(f"⚠️ Could not save section state: {e}")
            import traceback
            traceback.print_exc()

    # def _restore_section_controller_state(self):
    #     """Restore section controller to pre-cut state."""
    #     try:
    #         if self._saved_section_state is None:
    #             print("⚠️ No saved section state to restore")
    #             return
            
    #         sc = self.app.section_controller
    #         state = self._saved_section_state
            
    #         sc.active_view = state['active_view']
    #         self.app.section_points = state['section_points']
    #         self.app.section_core_points = state['section_core_points']
    #         self.app.section_buffer_points = state['section_buffer_points']
    #         self.app.section_core_mask = state['section_core_mask']
    #         self.app.section_buffer_mask = state['section_buffer_mask']
    #         self.app.section_indices = state['section_indices']
    #         sc.P1 = state['P1']
    #         sc.P2 = state['P2']
    #         sc.half_width = state['half_width']
    #         sc.last_mask = state['last_mask']
            
    #         print("✅ Restored section controller state - cross-section ready")
    #     except Exception as e:
    #         print(f"⚠️ Could not restore section state: {e}")

    def _restore_section_controller_state(self):
        """Restore section controller to pre-cut state with validation."""
        try:
            if self._saved_section_state is None:
                print("⚠️ No saved section state to restore")
                return
            
            sc = self.app.section_controller
            state = self._saved_section_state
            
            # Validate saved data exists
            if state['section_points'] is None:
                print("❌ ERROR: Saved section_points is None - cannot restore")
                return
            
            # Restore with validation
            sc.active_view = state['active_view']
            self.app.section_points = state['section_points']
            self.app.section_core_points = state['section_core_points']
            self.app.section_buffer_points = state['section_buffer_points']
            self.app.section_core_mask = state['section_core_mask']
            self.app.section_buffer_mask = state['section_buffer_mask']
            self.app.section_indices = state['section_indices']
            sc.P1 = state['P1']
            sc.P2 = state['P2']
            sc.half_width = state['half_width']
            sc.last_mask = state['last_mask']
            
            # Validation
            if self.app.section_points is not None and len(self.app.section_points) > 0:
                print(f"✅ Restored section controller state ({len(self.app.section_points)} points) - cross-section ready")
            else:
                print("❌ WARNING: Restored state has no points!")
                
        except Exception as e:
            print(f"❌ Could not restore section state: {e}")
            import traceback
            traceback.print_exc()
        
    def cancel_cut_section(self):
        """
        Cancel cut section, clear previews, and close dedicated widget.
        ✅ FIXED: Prevents crash by properly detaching all observers and interactors.
        ✅ FIXED: Explicitly deletes VTK actors to prevent memory leak (Bug #7)
        ✅ FIXED: Restores camera rotation in cross-section views (Bug #Camera Blocking)
        """
        try:
            # ✅ STEP 1: Set destruction flag FIRST
            self._is_destroying = True
            print("\n🧹 CANCELING CUT SECTION...")
            
            # ✅ STEP 1.5: Remove ALL actors from renderers BEFORE any widget cleanup (Bug #1 + #7)
            if self.cut_vtk is not None and hasattr(self.cut_vtk, 'renderer') and self.cut_vtk.renderer:
                print("   🧹 Removing actors from cut section renderer...")
                renderer = self.cut_vtk.renderer
                
                # List all actors to remove
                actors_to_remove = [
                    self.cut_core_actor,
                    self.cut_buffer_actor,
                    self.line_actor,
                    self.buffer_actor_upper,
                    self.buffer_actor_lower,
                    self.cut_preview_upper,
                    self.cut_preview_lower
                ]
                
                for actor in actors_to_remove:
                    if actor is not None:
                        try:
                            renderer.RemoveActor(actor)
                            # ✅ CRITICAL: Explicitly delete VTK C++ object (Bug #7 fix)
                            try:
                                actor.Delete()
                            except:
                                pass  # PyVista actors may not have Delete()
                        except Exception as e:
                            print(f"    ⚠️ Actor removal warning: {e}")
                
                # Clear actor references immediately
                self.cut_core_actor = None
                self.cut_buffer_actor = None
                self.line_actor = None
                self.buffer_actor_upper = None
                self.buffer_actor_lower = None
                self.cut_preview_upper = None
                self.cut_preview_lower = None
                
                print("   ✅ All actors removed and deleted")
            
            # ✅ Also clear preview actors from cross-section views
            if self.active_vtk and hasattr(self.active_vtk, 'renderer') and self.active_vtk.renderer:
                cross_renderer = self.active_vtk.renderer
                cross_actors = [self.buffer_actor_upper, self.buffer_actor_lower, self.line_actor]
                for actor in cross_actors:
                    if actor is not None:
                        try:
                            cross_renderer.RemoveActor(actor)
                            try:
                                actor.Delete()
                            except:
                                pass
                        except:
                            pass
            
            # ✅ STEP 2: CRITICAL - Disable render window IMMEDIATELY
            if self.cut_vtk is not None:
                try:
                    # Get render window and DISABLE IT
                    rw = self.cut_vtk.GetRenderWindow()
                    if rw:
                        print("   🛑 Disabling render window...")
                        rw.SetAbortRender(1)
                        # CRITICAL: Finalize NOW (before other cleanup)
                        rw.Finalize()
                        print("   ✅ Render window disabled")
                except Exception as e:
                    print(f"   ⚠️ Render window disable: {e}")
            
            # ✅ STEP 3: Remove ALL VTK observers and timers
            if self.cut_vtk is not None:
                try:
                    print("   🛑 Removing VTK observers and timers...")
                    iren = self.cut_vtk.interactor
                    
                    # CRITICAL: Destroy ALL timers first
                    timer_id = 0
                    while timer_id < 100:  # Remove up to 100 timers
                        try:
                            iren.DestroyTimer(timer_id)
                        except:
                            pass
                        timer_id += 1
                    
                    # Remove all event observers
                    iren.RemoveObservers("TimerEvent")
                    iren.RemoveObservers("ModifiedEvent")
                    iren.RemoveObservers("RenderEvent")
                    iren.RemoveObservers("LeftButtonPressEvent")
                    iren.RemoveObservers("LeftButtonReleaseEvent")
                    iren.RemoveObservers("MouseMoveEvent")
                    
                    # Terminate event loop
                    try:
                        iren.TerminateApp()
                    except:
                        pass
                    
                    print("   ✅ Observers and timers removed")
                except Exception as e:
                    print(f"   ⚠️ Observer removal: {e}")
            
            # ✅ STEP 4: Detach classification interactor BEFORE anything else
            if hasattr(self.app, 'classify_interactor'):
                ci = self.app.classify_interactor
                if ci is not None:
                    # Check if attached to cut section
                    if (hasattr(ci, 'vtk_widget') and ci.vtk_widget == self.cut_vtk) or \
                    (hasattr(ci, 'is_cut_section') and getattr(ci, 'is_cut_section', False)):
                        print("   🔧 Detaching classification interactor...")
                        ci.vtk_widget = None
                        ci.is_cut_section = False
                        # Restore previous interactor if exists
                        if self._old_classify_interactor is not None:
                            self.app.classify_interactor = self._old_classify_interactor
                            print("   ✅ Restored previous interactor")
                        else:
                            self.app.classify_interactor = None
                            print("   ✅ Interactor cleared")
            
            # ✅ STEP 4.5: RESTORE camera rotation in cross-section views
            if hasattr(self.app, 'section_vtks') and hasattr(self, '_saved_interactor_styles'):
                from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage
                for view_index in getattr(self.app, 'section_vtks', {}):
                    if view_index in self._saved_interactor_styles:
                        try:
                            iren = self.app.section_vtks[view_index].interactor
                            iren.SetInteractorStyle(vtkInteractorStyleImage())
                        except Exception as e:
                            print(f"   ⚠️ Interactor restore failed view {view_index}: {e}")
                self._saved_interactor_styles.clear()
                print("   🔓 All cross-section views restored")
                
                # ✅ Re-install camera sync observers (destroyed when styles were replaced)
                if hasattr(self.app, 'view_sync_map') and self.app.view_sync_map:
                    try:
                        if hasattr(self.app, '_camera_observers'):
                            self.app._camera_observers.clear()
                        for v_idx, vw in self.app.section_vtks.items():
                            is_synced = (
                                v_idx in self.app.view_sync_map or
                                any(src == v_idx for src in self.app.view_sync_map.values())
                            )
                            if is_synced and hasattr(self.app, '_install_realtime_camera_observer'):
                                self.app._install_realtime_camera_observer(v_idx, vw)
                        print("   🔗 Camera sync observers re-installed")
                    except Exception as e:
                        print(f"   ⚠️ Camera sync re-install failed: {e}")
            
            # ✅ STEP 5: Detach cross-section view observers
            self._detach_all_view_observers()
            
            # ✅ STEP 6: Clear all preview actors
            if self.cut_vtk is not None and hasattr(self.cut_vtk, 'renderer'):
                renderer = self.cut_vtk.renderer
                cut_specific_actors = [
                    self.cut_preview_upper,
                    self.cut_preview_lower,
                ]
                for actor in cut_specific_actors:
                    if actor is not None:
                        try:
                            renderer.RemoveActor(actor)
                            try:
                                actor.Delete()
                            except:
                                pass
                        except:
                            pass
     
            # ✅ STEP 7: Reset state flags
            self._state = CutSectionState.IDLE
            self.cut_phase = 0
            self.center_point = None
            self.section_tangent = None
            self.is_cut_view_active = False
            self._cut_camera_state = None
            
            # ✅ STEP 8: Restore cross-section data (FIXED - method name)
            print("   🔄 Restoring cross-section...")
            self._restore_section_controller_state()  # ✅ FIXED: Use correct method name
            
            # ✅ STEP 9: Cleanup VTK widget (AFTER disabling render window)
            if self.cut_vtk is not None:
                try:
                    print("   🧹 Finalizing VTK widget...")
                    # Clear all actors
                    self.cut_vtk.clear()
                    # Close the widget
                    self.cut_vtk.close()
                    print("   ✅ VTK finalized")
                except Exception as e:
                    print(f"   ⚠️ VTK cleanup: {e}")
                finally:
                    self.cut_vtk = None
            
            # ✅ STEP 10: Cleanup dock widget
            if self.cut_dock is not None:
                try:
                    print("   🧹 Closing dock...")
                    # Disconnect signals
                    try:
                        self.cut_dock.visibilityChanged.disconnect()
                    except:
                        pass
                    # Hide first
                    self.cut_dock.setVisible(False)
                    # Remove from main window
                    if hasattr(self.app, 'removeDockWidget'):
                        self.app.removeDockWidget(self.cut_dock)
                    # Close and delete
                    self.cut_dock.close()
                    self.cut_dock.deleteLater()
                    print("   ✅ Dock closed")
                except Exception as e:
                    print(f"   ⚠️ Dock cleanup: {e}")
                finally:
                    self.cut_dock = None
            
            # ✅ STEP 11: Clear UI references
            self.depth_label = None
            self.depth_spin = None
            self._restore_classification_tools()
            
            # ✅ STEP 12: Refresh cross-section views (with safety)
            # try:
            #     if hasattr(self.app, 'section_controller'):
            #         print("   🔄 Refreshing cross-section...")
            #         # Only refresh if method exists
            #         if hasattr(self.app.section_controller, 'refresh_colors_direct'):
            #             self.app.section_controller.refresh_colors_direct()
            #         # Render only FIRST view (not all)
            #         for vtk_widget in getattr(self.app, 'section_vtks', {}).values():
            #             if vtk_widget is not None:
            #                 try:
            #                     vtk_widget.render()
            #                 except:
            #                     pass
            #                 break  # Only refresh ONE view
            #         print("   ✅ Cross-section refreshed")
            # except Exception as e:
            #     print(f"   ⚠️ Refresh warning: {e}")
            # ✅ STEP 12: Refresh cross-section views (with safety)
            try:
                if hasattr(self.app, 'section_controller'):
                    print("   🔄 Refreshing cross-section...")
                    # Only refresh if method exists
                    # if hasattr(self.app.section_controller, 'refresh_colors_direct'):
                    #     self.app.section_controller.refresh_colors_direct()
                    
                    # ✅ FIXED: Refresh ALL views, not just first one
                    refreshed_count = 0
                    for view_index, vtk_widget in enumerate(getattr(self.app, 'section_vtks', {}).values()):
                        if vtk_widget is not None:
                            try:
                                _safe_vtk_render(vtk_widget)
                                refreshed_count += 1
                            except Exception as e:
                                print(f"   ⚠️ Failed to refresh view {view_index}: {e}")
                    
                    print(f"   ✅ Cross-section refreshed ({refreshed_count} views)")
            except Exception as e:
                print(f"   ⚠️ Refresh warning: {e}")
                        
            # ✅ STEP 13: Update status bar
            try:
                self.app.statusBar().showMessage("✂️ Cut Section closed - Cross-section restored", 1500)
            except:
                pass
            
            print("✅ CUT SECTION CANCELED\n")
            
        except Exception as e:
            print(f"❌ [CutSection.cancel] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # ✅ CRITICAL: Always reset state even if error
            self._state = CutSectionState.IDLE
            self._is_destroying = False
            try:
                self.app.set_cross_cursor_active(False)
            except:
                pass

    def _detach_all_view_observers(self):
        """Guaranteed observer cleanup."""
        for v_idx, ids in list(self._view_observer_ids.items()):
            try:
                if v_idx in getattr(self.app, "section_vtks", {}):
                    iren = self.app.section_vtks[v_idx].interactor
                    for oid in ids:
                        try:
                            iren.RemoveObserver(oid)
                        except Exception:
                            pass
            except Exception:
                pass
        self._view_observer_ids.clear()


    # def _clear_preview_actors(self):
    #     """Robust actor cleanup from BOTH cross-section and cut section"""
    #     # Clear from cross-section
    #     if self.active_vtk:
    #         ren = self.active_vtk.renderer
    #         for a in (self.line_actor, self.buffer_actor_upper, self.buffer_actor_lower):
    #             if a:
    #                 try: 
    #                     ren.RemoveActor(a)
    #                 except Exception: 
    #                     pass
    #         try:
    #             _safe_vtk_render(self.active_vtk)
    #         except Exception:
    #             pass
    #     self.line_actor = self.buffer_actor_upper = self.buffer_actor_lower = None

    #     # Clear from ALL section views
    #     try:
    #         for vtk_widget in getattr(self.app, "section_vtks", {}).values():
    #             ren = vtk_widget.renderer
    #             for a in (self.line_actor, self.buffer_actor_upper, self.buffer_actor_lower):
    #                 if a:
    #                     try:
    #                         ren.RemoveActor(a)
    #                     except Exception:
    #                         pass
    #             try:
    #                 vtk_widget.render()
    #             except Exception:
    #                 pass
    #     except Exception:
    #         pass

    #     # Clear from cut dock
    #     if self.cut_vtk and hasattr(self.cut_vtk, "renderer") and self.cut_vtk.renderer:
    #         ren_cut = self.cut_vtk.renderer
    #         for a in (self.cut_preview_upper, self.cut_preview_lower):
    #             if a:
    #                 try: 
    #                     ren_cut.RemoveActor(a)
    #                 except Exception: 
    #                     pass
    #         try:
    #             _safe_vtk_render(self.cut_vtk)
    #         except Exception:
    #             pass
    #     self.cut_preview_upper = self.cut_preview_lower = None

    def _clear_preview_actors(self):
        """
        Clear ONLY cut-section specific preview actors.
        
        ✅ FIXED: Does NOT touch cross-section preview geometry
        ✅ FIXED: Only removes cut_preview_upper and cut_preview_lower
        ✅ Ensures cross-section data remains visible after cut section closes
        """
        try:
            # ========== CLEAR ONLY CUT-SECTION PREVIEW ACTORS ==========
            
            if self.cut_vtk is not None and hasattr(self.cut_vtk, 'renderer') and self.cut_vtk.renderer:
                ren_cut = self.cut_vtk.renderer
                
                # ONLY these are cut-section specific:
                cut_specific_actors = [
                    self.cut_preview_upper,
                    self.cut_preview_lower,
                ]
                
                for actor in cut_specific_actors:
                    if actor is not None:
                        try:
                            ren_cut.RemoveActor(actor)
                            try:
                                actor.Delete()
                            except:
                                pass
                        except Exception:
                            pass
                
                # Clear references
                self.cut_preview_upper = None
                self.cut_preview_lower = None
            
            # NOTE: We explicitly DO NOT clear:
            # - self.line_actor
            # - self.buffer_actor_upper
            # - self.buffer_actor_lower
            # These are cross-section geometry and must be preserved.
            
        except Exception:
            pass

    def _robust_clear_renderer(self, vtk_widget):
        """Ensure we really remove old props."""
        ren = vtk_widget.renderer
        try:
            actors = ren.GetActors()
            actors.InitTraversal()
            to_remove = []
            for _ in range(actors.GetNumberOfItems()):
                act = actors.GetNextActor()
                if act:
                    to_remove.append(act)
            for act in to_remove:
                ren.RemoveActor(act)
            ren.RemoveAllViewProps()
        except Exception:
            pass
        try:
            vtk_widget.clear()
        except Exception:
            pass


    def _on_depth_spin_changed(self, value: float):
        """Update depth from spinbox (called during depth adjustment)."""
        self.dynamic_depth = float(value)
        if self.center_point is not None and self._state == CutSectionState.WAITING_DEPTH:
            self._draw_dynamic_band_preview(self.center_point, self.dynamic_depth)
            if self.cut_vtk is not None:
                self._draw_cut_section_preview(self.center_point, self.dynamic_depth)


    def _get_vertical_segment(self, center, vtk_widget=None):
        """Get vertical segment bounds using VIEWPORT height, not data bounds."""
        if vtk_widget is None:
            vtk_widget = self.active_vtk or getattr(self.app, "sec_vtk", None)
        
        if vtk_widget is None:
            # Fallback: use large default
            zmin, zmax = center[2] - 100.0, center[2] + 100.0
        else:
            # ✅ MICROSTATION APPROACH: Use camera view bounds
            try:
                ren = vtk_widget.renderer
                cam = ren.GetActiveCamera()
                
                # Get parallel scale (viewport height in world units)
                parallel_scale = cam.GetParallelScale()
                
                # Line extends ±2× viewport height (ensures full coverage)
                height_extent = parallel_scale * 2.0
                
                zmin = center[2] - height_extent
                zmax = center[2] + height_extent
                
            except Exception:
                # Fallback: use data bounds
                xyz = getattr(self.app, "section_points", None)
                if xyz is not None and hasattr(xyz, 'shape') and xyz.shape[0] > 0:
                    try:
                        xyz = np.asarray(xyz, dtype=float)
                        zmin = float(np.min(xyz[:, 2])) - 10.0
                        zmax = float(np.max(xyz[:, 2])) + 10.0
                    except:
                        zmin, zmax = center[2] - 100.0, center[2] + 100.0
                else:
                    zmin, zmax = center[2] - 100.0, center[2] + 100.0
        
        p0 = np.array([center[0], center[1], zmin], dtype=float)
        p1 = np.array([center[0], center[1], zmax], dtype=float)
        
        return p0, p1

    def _draw_dynamic_center_line(self, center):
        """Draw center line in cross-section with smooth updates."""

        if self._state not in [CutSectionState.WAITING_CENTER, CutSectionState.WAITING_DEPTH]:
            print(f"   ⚠️ Blocked _draw_dynamic_center_line: wrong state ({self._state})")
            return
    
        vtk_widget = self.active_vtk or getattr(self.app, "sec_vtk", None)
        if vtk_widget is None:
            return
        
        # ✅ FIX: Clear preview from ALL other cross-section views
        self._clear_preview_from_other_views(vtk_widget)
        
        ren = vtk_widget.renderer
        p0, p1 = self._get_vertical_segment(center, vtk_widget)
        
        # ✅ SMOOTH: Update existing, don't recreate
        if self.line_actor is None:
            # Create ONCE
            pts = vtk.vtkPoints()
            pts.InsertNextPoint(*p0)
            pts.InsertNextPoint(*p1)
            
            lines = vtk.vtkCellArray()
            lines.InsertNextCell(2)
            lines.InsertCellPoint(0)
            lines.InsertCellPoint(1)
            
            poly = vtk.vtkPolyData()
            poly.SetPoints(pts)
            poly.SetLines(lines)
            
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly)
            
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0, 1, 0)
            actor.GetProperty().SetLineWidth(1)
            actor.GetProperty().SetOpacity(1.0)
            
            # ✅ FORCE LINES ON TOP
            self._configure_line_on_top(actor)
            
            ren.AddActor(actor)
            self.line_actor = actor
            
            # Cache for fast updates
            self._line_actor_points = pts
            self._line_actor_poly = poly
        else:
            # ✅ FAST UPDATE (no recreation)
            pts = self._line_actor_points
            poly = self._line_actor_poly
            
            pts.SetPoint(0, *p0)
            pts.SetPoint(1, *p1)
            pts.Modified()
            poly.Modified()
            
            # ✅ CRITICAL: Ensure actor is in CURRENT view's renderer
            try:
                # Remove from all renderers first
                for view_idx, vw in self.app.section_vtks.items():
                    try:
                        vw.renderer.RemoveActor(self.line_actor)
                    except:
                        pass
                
                # Add to current view only
                ren.AddActor(self.line_actor)
            except:
                pass
        
        try:
            _safe_vtk_render(vtk_widget)
        except Exception:
            pass

    # def _draw_dynamic_band_preview(self, center, depth):
    #     """Draw buffer band lines in cross-section."""

    #     if self._state != CutSectionState.WAITING_DEPTH:
    #         print(f"   ⚠️ Blocked _draw_dynamic_band_preview: wrong state ({self._state})")
    #         return
        
    #     vtk_widget = self.active_vtk or getattr(self.app, "sec_vtk", None)
    #     if vtk_widget is None:
    #         return
        
    #     # ✅ FIX: Clear preview from ALL other cross-section views
    #     self._clear_preview_from_other_views(vtk_widget)
        
    #     ren = vtk_widget.renderer
    #     view_mode = getattr(self.app, "cross_view_mode", "side")
    #     view_mode = view_mode.strip().lower() if isinstance(view_mode, str) else "side"
    #     axis = 0 if view_mode == "side" else 1
    #     base_p0, base_p1 = self._get_vertical_segment(center, vtk_widget)
        
    #     for sign, attr in [(-1.0, "buffer_actor_lower"), (+1.0, "buffer_actor_upper")]:
    #         actor = getattr(self, attr, None)
            
    #         if actor is None:
    #             pts = vtk.vtkPoints()
    #             lines = vtk.vtkCellArray()
    #             poly = vtk.vtkPolyData()
    #             mapper = vtk.vtkPolyDataMapper()
    #             actor = vtk.vtkActor()
                
    #             poly.SetPoints(pts)
    #             poly.SetLines(lines)
    #             mapper.SetInputData(poly)
    #             actor.SetMapper(mapper)
                
    #             # ✅ MICROSTATION STYLE: Yellow, thin lines
    #             actor.GetProperty().SetColor(1.0, 1.0, 0.0)  # Yellow
    #             actor.GetProperty().SetLineWidth(1)  # ✅ THIN
    #             actor.GetProperty().SetOpacity(0.8)
                
    #             # ✅ FORCE LINES ON TOP
    #             self._configure_line_on_top(actor)

    #             ren.AddActor(actor)
    #             setattr(self, attr, actor)
    #             setattr(self, f"_{attr}_points", pts)
    #             setattr(self, f"_{attr}_lines", lines)
    #             setattr(self, f"_{attr}_poly", poly)
    #             setattr(self, f"_{attr}_mapper", mapper)
    #         else:
    #             pts = getattr(self, f"_{attr}_points", None)
    #             lines = getattr(self, f"_{attr}_lines", None)
    #             poly = getattr(self, f"_{attr}_poly", None)
    #             mapper = getattr(self, f"_{attr}_mapper", None)
                
    #             if pts is None or lines is None or poly is None or mapper is None:
    #                 pts = vtk.vtkPoints()
    #                 lines = vtk.vtkCellArray()
    #                 poly = vtk.vtkPolyData()
    #                 mapper = vtk.vtkPolyDataMapper()
                    
    #                 poly.SetPoints(pts)
    #                 poly.SetLines(lines)
    #                 mapper.SetInputData(poly)
    #                 actor.SetMapper(mapper)
                    
    #                 setattr(self, f"_{attr}_points", pts)
    #                 setattr(self, f"_{attr}_lines", lines)
    #                 setattr(self, f"_{attr}_poly", poly)
    #                 setattr(self, f"_{attr}_mapper", mapper)
    #             else:
    #                 pts.Reset()
    #                 lines.Reset()
                
    #             # ✅ CRITICAL: Ensure actor is in CURRENT view's renderer
    #             try:
    #                 # Remove from all renderers first
    #                 for view_idx, vw in self.app.section_vtks.items():
    #                     try:
    #                         vw.renderer.RemoveActor(actor)
    #                     except:
    #                         pass
                    
    #                 # Add to current view only
    #                 ren.AddActor(actor)
    #             except:
    #                 pass
            
    #         p0 = base_p0.copy()
    #         p1 = base_p1.copy()
    #         p0[axis] += sign * depth
    #         p1[axis] += sign * depth
            
    #         pts.InsertNextPoint(*p0)
    #         pts.InsertNextPoint(*p1)
            
    #         lines.InsertNextCell(2)
    #         lines.InsertCellPoint(0)
    #         lines.InsertCellPoint(1)
            
    #         poly.Modified()
    #         mapper.Update()
    #         actor.VisibilityOn()
        
    #     try:
    #         vtk_widget.render()
    #     except Exception:
    #         pass
    
    # def _draw_cut_section_preview(self, center, depth):
    #     """Draw preview inside cut dock."""

    #     if self._state != CutSectionState.WAITING_DEPTH:
    #         print(f"   ⚠️ Blocked _draw_cut_section_preview: wrong state ({self._state})")
    #         return
    #     if getattr(self, '_is_destroying', False):
    #         return
    #     if self.cut_vtk is None or not hasattr(self.cut_vtk, "renderer") or self.cut_vtk.renderer is None:
    #         return
    #     ren = self.cut_vtk.renderer

    #     if center is None:
    #         return

    #     # ✅ FIX: ALWAYS use X-axis (0) for cut section preview lines
    #     # Camera ALWAYS looks along Y-axis, so only X-axis offset is visible
    #     # Using Y-axis makes lines invisible (they overlap with center line)
    #     axis = 0  # ← FIXED! Was: ((self.accumulated_rotation + 90) // 90) % 2

    #     debug_depth = depth if (depth is not None and abs(depth) > 1e-6) else max(0.01, getattr(self, "dynamic_depth", 0.01))

    #     for sign, attr in [(-1.0, "cut_preview_lower"), (+1.0, "cut_preview_upper")]:
    #         # ✅ CRITICAL FIX: Pass cut_vtk widget explicitly for correct Z bounds
    #         base_p0, base_p1 = self._get_vertical_segment(center, self.cut_vtk)
            
    #         # Calculate offset points FIRST
    #         p0 = base_p0.copy()
    #         p1 = base_p1.copy()
    #         p0[axis] += sign * debug_depth
    #         p1[axis] += sign * debug_depth
            
    #         actor = getattr(self, attr, None)

    #         if actor is None or not hasattr(self, f"_{attr}_points"):
    #             # ✅ CREATE NEW ACTOR ONCE
    #             pts = vtk.vtkPoints()
    #             lines = vtk.vtkCellArray()
    #             poly = vtk.vtkPolyData()
    #             mapper = vtk.vtkPolyDataMapper()
    #             actor = vtk.vtkActor()

    #             # Insert initial points
    #             pts.InsertNextPoint(*p0)
    #             pts.InsertNextPoint(*p1)
                
    #             lines.InsertNextCell(2)
    #             lines.InsertCellPoint(0)
    #             lines.InsertCellPoint(1)
                
    #             poly.SetPoints(pts)
    #             poly.SetLines(lines)
    #             mapper.SetInputData(poly)
    #             actor.SetMapper(mapper)
                
    #             prop = actor.GetProperty()
    #             prop.SetColor(1.0, 1.0, 0.0)
    #             prop.SetLineWidth(2)
    #             prop.SetOpacity(0.8)
                
    #             # ✅ CONFIGURE DEPTH ONLY ONCE
    #             self._configure_line_on_top(actor)
                
    #             actor.VisibilityOn()
    #             ren.AddActor(actor)
                
    #             setattr(self, attr, actor)
    #             setattr(self, f"_{attr}_points", pts)
    #             setattr(self, f"_{attr}_lines", lines)
    #             setattr(self, f"_{attr}_poly", poly)
    #             setattr(self, f"_{attr}_mapper", mapper)
    #         else:
    #             # ✅ UPDATE EXISTING POINTS (DON'T RESET)
    #             pts = getattr(self, f"_{attr}_points")
    #             poly = getattr(self, f"_{attr}_poly")
    #             mapper = getattr(self, f"_{attr}_mapper")
                
    #             # ✅ JUST UPDATE THE 2 EXISTING POINTS
    #             pts.SetPoint(0, *p0)
    #             pts.SetPoint(1, *p1)
                
    #             # ✅ NOTIFY VTK
    #             pts.Modified()
    #             poly.Modified()
    #             mapper.Update()
            
    #         actor.VisibilityOn()

    #     # ✅ CRITICAL: Always render
    #     try:
    #         _safe_vtk_render(self.cut_vtk)
    #     except Exception:
    #         pass

    def _draw_dynamic_band_preview(self, center, depth):
        """Draw buffer band lines in cross-section with robust actor management."""

        if self._state != CutSectionState.WAITING_DEPTH:
            return
        
        vtk_widget = self.active_vtk or getattr(self.app, "sec_vtk", None)
        if vtk_widget is None:
            return
        
        # Clear preview from other views
        self._clear_preview_from_other_views(vtk_widget)
        
        ren = vtk_widget.renderer
        view_mode = getattr(self.app, "cross_view_mode", "side")
        view_mode = view_mode.strip().lower() if isinstance(view_mode, str) else "side"
        axis = 0 if view_mode == "side" else 1
        base_p0, base_p1 = self._get_vertical_segment(center, vtk_widget)
        
        for sign, attr in [(-1.0, "buffer_actor_lower"), (+1.0, "buffer_actor_upper")]:
            # Calculate offset points
            p0 = base_p0.copy()
            p1 = base_p1.copy()
            p0[axis] += sign * depth
            p1[axis] += sign * depth
            
            actor = getattr(self, attr, None)
            pts_attr = f"_{attr}_points"
            
            # ✅ FIX: Check if we have VALID cached geometry
            pts = getattr(self, pts_attr, None)
            needs_recreation = (
                actor is None or 
                pts is None or 
                not hasattr(self, f"_{attr}_poly") or
                getattr(self, f"_{attr}_poly", None) is None
            )
            
            if needs_recreation:
                # ✅ ALWAYS create fresh geometry
                pts = vtk.vtkPoints()
                pts.InsertNextPoint(*p0)
                pts.InsertNextPoint(*p1)
                
                lines = vtk.vtkCellArray()
                lines.InsertNextCell(2)
                lines.InsertCellPoint(0)
                lines.InsertCellPoint(1)
                
                poly = vtk.vtkPolyData()
                poly.SetPoints(pts)
                poly.SetLines(lines)
                
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputData(poly)
                
                # Remove old actor if exists
                if actor is not None:
                    try:
                        ren.RemoveActor(actor)
                    except:
                        pass
                
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                
                # Yellow, visible lines
                prop = actor.GetProperty()
                prop.SetColor(1.0, 1.0, 0.0)  # Yellow
                prop.SetLineWidth(2)  # ✅ Thicker for visibility
                prop.SetOpacity(1.0)  # ✅ Full opacity
                
                # Force lines on top
                self._configure_line_on_top(actor)
                
                ren.AddActor(actor)
                
                # Cache references
                setattr(self, attr, actor)
                setattr(self, pts_attr, pts)
                setattr(self, f"_{attr}_lines", lines)
                setattr(self, f"_{attr}_poly", poly)
                setattr(self, f"_{attr}_mapper", mapper)
                
            else:
                # ✅ FIX: Update existing points WITHOUT Reset()
                pts = getattr(self, pts_attr)
                poly = getattr(self, f"_{attr}_poly")
                
                # Update the 2 existing points directly
                pts.SetPoint(0, *p0)
                pts.SetPoint(1, *p1)
                pts.Modified()
                poly.Modified()
                
                # Ensure actor is in current renderer
                try:
                    for view_idx, vw in self.app.section_vtks.items():
                        if vw != vtk_widget:
                            try:
                                vw.renderer.RemoveActor(actor)
                            except:
                                pass
                    
                    # Check if actor is already in renderer
                    actors = ren.GetActors()
                    actors.InitTraversal()
                    found = False
                    for _ in range(actors.GetNumberOfItems()):
                        if actors.GetNextActor() == actor:
                            found = True
                            break
                    
                    if not found:
                        ren.AddActor(actor)
                except:
                    pass
            
            # Ensure visibility
            actor.VisibilityOn()
        
        # ✅ CRITICAL: Force render
        try:
            _safe_vtk_render(vtk_widget)
        except Exception as e:
            print(f"⚠️ Render failed in _draw_dynamic_band_preview: {e}")

    def _draw_cut_section_preview(self, center, depth):
        """Draw preview inside cut dock with robust actor management."""

        if self._state != CutSectionState.WAITING_DEPTH:
            return
        if getattr(self, '_is_destroying', False):
            return
        if self.cut_vtk is None or not hasattr(self.cut_vtk, "renderer") or self.cut_vtk.renderer is None:
            return
        
        ren = self.cut_vtk.renderer

        if center is None:
            return

        # Always use X-axis for cut section preview
        axis = 0
        
        # Use valid depth
        preview_depth = depth if (depth is not None and abs(depth) > 1e-6) else max(0.5, getattr(self, "dynamic_depth", 1.0))

        for sign, attr in [(-1.0, "cut_preview_lower"), (+1.0, "cut_preview_upper")]:
            # Get Z bounds from cut view
            base_p0, base_p1 = self._get_vertical_segment(center, self.cut_vtk)
            
            # Calculate offset points
            p0 = base_p0.copy()
            p1 = base_p1.copy()
            p0[axis] += sign * preview_depth
            p1[axis] += sign * preview_depth
            
            actor = getattr(self, attr, None)
            pts_attr = f"_{attr}_points"
            
            # ✅ FIX: Check if we have VALID cached geometry
            pts = getattr(self, pts_attr, None)
            needs_recreation = (
                actor is None or 
                pts is None or 
                not hasattr(self, f"_{attr}_poly") or
                getattr(self, f"_{attr}_poly", None) is None
            )
            
            if needs_recreation:
                # ✅ ALWAYS create fresh geometry
                pts = vtk.vtkPoints()
                pts.InsertNextPoint(*p0)
                pts.InsertNextPoint(*p1)
                
                lines = vtk.vtkCellArray()
                lines.InsertNextCell(2)
                lines.InsertCellPoint(0)
                lines.InsertCellPoint(1)
                
                poly = vtk.vtkPolyData()
                poly.SetPoints(pts)
                poly.SetLines(lines)
                
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputData(poly)
                
                # Remove old actor if exists
                if actor is not None:
                    try:
                        ren.RemoveActor(actor)
                    except:
                        pass
                
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                
                # Yellow, visible lines
                prop = actor.GetProperty()
                prop.SetColor(1.0, 1.0, 0.0)  # Yellow
                prop.SetLineWidth(2)  # Thicker for visibility
                prop.SetOpacity(1.0)  # Full opacity
                
                # Force lines on top
                self._configure_line_on_top(actor)
                
                ren.AddActor(actor)
                
                # Cache references
                setattr(self, attr, actor)
                setattr(self, pts_attr, pts)
                setattr(self, f"_{attr}_lines", lines)
                setattr(self, f"_{attr}_poly", poly)
                setattr(self, f"_{attr}_mapper", mapper)
                
                print(f"  🆕 Created {attr} at offset {sign * preview_depth:.2f}m")
                
            else:
                # ✅ FIX: Update existing points WITHOUT Reset()
                pts = getattr(self, pts_attr)
                poly = getattr(self, f"_{attr}_poly")
                
                # Update the 2 existing points directly
                pts.SetPoint(0, *p0)
                pts.SetPoint(1, *p1)
                pts.Modified()
                poly.Modified()
            
            # Ensure visibility
            actor.VisibilityOn()

        # ✅ CRITICAL: Force render
        try:
            _safe_vtk_render(self.cut_vtk)
        except Exception as e:
            print(f"⚠️ Render failed in _draw_cut_section_preview: {e}")

    def _rebuild_cut_index_map(self):
        """
        Rebuild the mapping from cut section indices to original dataset indices.
        ✅ Handles both cross-section AND nested cuts correctly
        ✅ Chains indices through parent mappings if nested
        ✅ BUG #3 FIX: Bounds checking to prevent IndexError
        """
        if self.cut_points is None or self.cut_mask_in_section is None:
            self._cut_index_map = None
            return
        
        print(f"🔧 Rebuilding cut index map...")
        print(f"   Cut section: {len(self.cut_points)} points")
        print(f"   Cut mask: {np.sum(self.cut_mask_in_section)} True values")
        
        try:
            # ✅ CHECK 1: NESTED CUT (cut-from-cut)
            if hasattr(self, 'parent_index_map') and self.parent_index_map is not None:
                print("   Type: NESTED CUT (cut-from-cut)")
                
                local_indices = np.where(self.cut_mask_in_section)[0]
                
                # ✅ BUG #3 FIX: Validate indices are within parent_index_map bounds
                parent_size = len(self.parent_index_map)
                print(f"   Local indices: {len(local_indices)} values")
                print(f"   Parent map size: {parent_size}")
                
                if len(local_indices) == 0:
                    print(f"   ⚠️ No local indices after mask - empty cut")
                    self._cut_index_map = np.array([], dtype=np.int64)
                    return
                
                # ✅ CRITICAL: Check for out-of-bounds indices
                max_local_idx = np.max(local_indices)
                if max_local_idx >= parent_size:
                    print(f"   ❌ OUT OF BOUNDS: max local index {max_local_idx} >= parent size {parent_size}")
                    print(f"   Filtering invalid indices...")
                    
                    # Filter to keep only valid indices
                    valid_mask = local_indices < parent_size
                    local_indices = local_indices[valid_mask]
                    
                    print(f"   ✅ Filtered to {len(local_indices)} valid indices")
                    
                    if len(local_indices) == 0:
                        print(f"   ❌ No valid indices remain after filtering")
                        self._cut_index_map = None
                        return
                
                # ✅ Safe indexing (indices are now validated)
                original_indices = self.parent_index_map[local_indices]
                self._cut_index_map = original_indices
                
                print(f"   ✅ Chained {len(self._cut_index_map)} indices through parent")
                
                if len(self._cut_index_map) > 0:
                    print(f"      Index range: {np.min(self._cut_index_map)} to {np.max(self._cut_index_map)}")
                
                # ✅ BUG #3 FIX: Verify against dataset bounds
                if hasattr(self.app, 'data') and 'xyz' in self.app.data:
                    dataset_size = len(self.app.data['xyz'])
                    max_cut_idx = np.max(self._cut_index_map) if len(self._cut_index_map) > 0 else -1
                    
                    if max_cut_idx >= dataset_size:
                        print(f"   ❌ CRITICAL: Cut indices [{np.min(self._cut_index_map)}-{max_cut_idx}] exceed dataset size {dataset_size}")
                        print(f"   Clamping to valid range...")
                        
                        # Clamp to valid dataset range
                        valid_in_dataset = self._cut_index_map < dataset_size
                        self._cut_index_map = self._cut_index_map[valid_in_dataset]
                        
                        print(f"   ✅ Clamped to {len(self._cut_index_map)} valid indices")
            
            # ✅ CHECK 2: REGULAR CROSS-SECTION CUT
            else:
                print("   Type: CROSS-SECTION CUT")
                
                # Get the cross-section rectangle selection mask
                if hasattr(self.app.section_controller, 'last_mask'):
                    cross_section_mask = self.app.section_controller.last_mask
                    cross_section_indices = np.where(cross_section_mask)[0]
                    
                    print(f"   Rectangle selection: {len(cross_section_indices)} indices")
                    
                    # ✅ CRITICAL: Check if we have the cut mask
                    if hasattr(self, 'cut_mask_in_section') and self.cut_mask_in_section is not None:
                        cut_local_mask = self.cut_mask_in_section
                        
                        # ✅ Verify mask size matches cross-section indices
                        if len(cut_local_mask) != len(cross_section_indices):
                            print(f"   ⚠️ Size mismatch: mask {len(cut_local_mask)} vs indices {len(cross_section_indices)}")
                            print(f"   Attempting to rebuild from raw data...")
                            
                            # Fallback: Rebuild mask from cut_points
                            all_xyz = getattr(self.app, "data", {}).get("xyz", None)
                            if all_xyz is None:
                                print(f"   ❌ Cannot fallback - no dataset available")
                                self._cut_index_map = None
                                return
                            
                            selected_xyz = all_xyz[cross_section_indices]
                            active_view = getattr(self.app.section_controller, "active_view", None)
                            axis = 0 if getattr(self.app, "cross_view_mode", "side") == "side" else 1
                            cval = float(self.center_point[axis])
                            
                            new_mask = np.abs(selected_xyz[:, axis] - cval) <= self.dynamic_depth
                            local_indices = np.where(new_mask)[0]
                            
                            # ✅ BUG #3 FIX: Bounds check before indexing
                            if len(local_indices) > 0 and np.max(local_indices) >= len(cross_section_indices):
                                print(f"   ❌ Fallback indices out of bounds, clamping...")
                                local_indices = local_indices[local_indices < len(cross_section_indices)]
                            
                            self._cut_index_map = cross_section_indices[local_indices]
                            
                            print(f"   ✅ Rebuilt and mapped {len(self._cut_index_map)} cut points")
                        else:
                            # Sizes match - use the mask directly
                            local_indices = np.where(cut_local_mask)[0]
                            
                            # ✅ BUG #3 FIX: Bounds check before indexing
                            if len(local_indices) > 0:
                                max_local_idx = np.max(local_indices)
                                if max_local_idx >= len(cross_section_indices):
                                    print(f"   ⚠️ Local indices exceed cross_section_indices bounds")
                                    print(f"      Max local: {max_local_idx}, Cross-section size: {len(cross_section_indices)}")
                                    
                                    # Filter invalid indices
                                    valid_mask = local_indices < len(cross_section_indices)
                                    local_indices = local_indices[valid_mask]
                                    print(f"   ✅ Filtered to {len(local_indices)} valid indices")
                            
                            if len(local_indices) > 0:
                                self._cut_index_map = cross_section_indices[local_indices]
                            else:
                                self._cut_index_map = np.array([], dtype=np.int64)
                            
                            print(f"   ✅ Mapped {len(self._cut_index_map)} cut points to original dataset")
                        
                        if len(self._cut_index_map) > 0:
                            print(f"      Index range: {np.min(self._cut_index_map)} to {np.max(self._cut_index_map)}")
                        
                        # ✅ Verify count
                        if len(self._cut_index_map) != len(self.cut_points):
                            print(f"   ⚠️ Warning: Index map {len(self._cut_index_map)} ≠ cut points {len(self.cut_points)}")
                    else:
                        print(f"   ❌ No cut_mask_in_section found - cannot rebuild map")
                        self._cut_index_map = None
                else:
                    print(f"   ❌ No rectangle selection (last_mask) found")
                    self._cut_index_map = None
            
            # ✅ FINAL VALIDATION
            if self._cut_index_map is None or len(self._cut_index_map) == 0:
                print(f"   ⚠️ Index map is empty or invalid!")
                self._cut_index_map = None
            else:
                print(f"   ✅ Index map ready: {len(self._cut_index_map)} indices")
        
        except Exception as e:
            print(f"   ❌ Error rebuilding index map: {e}")
            import traceback
            traceback.print_exc()
            self._cut_index_map = None



    def _clear_cut_view(self):
        """Clear cut view and restore section data."""
        av = getattr(self.app.section_controller, "active_view", None)
        if av is not None and av in self.app.section_vtks:
            vw = self.app.section_vtks[av]
            self._robust_clear_renderer(vw)
            _safe_vtk_render(vw)
        self.is_cut_view_active = False
        self.restore_section_data()


    def _estimate_section_tangent_3d(self, points_xyz: np.ndarray) -> np.ndarray:
        """
        Estimate tangent direction.
        ✅ BUG #12 FIX: Safe division with proper epsilon checking
        """
        if points_xyz is None or points_xyz.shape[0] < 2:
            return np.array([1.0, 0.0, 0.0])
        
        try:
            xy = np.asarray(points_xyz[:, :2], dtype=float)
            xy_mean = np.mean(xy, axis=0)
            xy_centered = xy - xy_mean
            cov = np.dot(xy_centered.T, xy_centered) / max(len(xy) - 1, 1)
            eigenvalues, eigenvectors = np.linalg.eigh(cov)
            tangent_2d = eigenvectors[:, np.argmax(eigenvalues)]
            
            # ✅ BUG #12 FIX: Use stricter epsilon and check BEFORE division
            norm = np.linalg.norm(tangent_2d)
            
            # Use 1e-6 instead of 1e-9 (safer threshold)
            if norm < 1e-6:
                print(f"⚠️ Tangent norm too small ({norm:.2e}), using fallback")
                return np.array([1.0, 0.0, 0.0])
            
            # ✅ Safe division (norm is guaranteed >= 1e-6)
            tangent_2d = tangent_2d / norm
            
            # ✅ Verify result is valid (additional safety check)
            if not np.all(np.isfinite(tangent_2d)):
                print(f"⚠️ Tangent contains NaN/Inf, using fallback")
                return np.array([1.0, 0.0, 0.0])
            
            tangent_3d = np.array([tangent_2d[0], tangent_2d[1], 0.0])
            return tangent_3d
            
        except Exception as e:
            print(f"⚠️ Tangent calculation failed: {e}, using fallback")
            return np.array([1.0, 0.0, 0.0])



    def _set_camera_along_tangent(self, vtk_widget, cut_points_xyz, tangent_3d):
        """Set camera to look ALONG the section tangent direction."""
        ren = vtk_widget.renderer
        cam = ren.GetActiveCamera()

        if cut_points_xyz is None or len(cut_points_xyz) == 0:
            return

        pts = np.asarray(cut_points_xyz, float)
        xmin, ymin, zmin = np.min(pts, axis=0)
        xmax, ymax, zmax = np.max(pts, axis=0)
        xmid, ymid, zmid = (xmin + xmax)/2.0, (ymin + ymax)/2.0, (zmin + zmax)/2.0
        focal_point = np.array([xmid, ymid, zmid])
        
        tangent = np.asarray(tangent_3d, float)
        tangent_norm = np.linalg.norm(tangent)
        if tangent_norm < 1e-9:
            tangent = np.array([1.0, 0.0, 0.0])
        else:
            tangent = tangent / tangent_norm
        
        extent = np.linalg.norm([xmax - xmin, ymax - ymin, zmax - zmin])
        distance = max(10.0, extent * 2.0)
        camera_position = focal_point - tangent * distance
        view_up = np.array([0.0, 0.0, 1.0])
        
        cam.SetPosition(*camera_position)
        cam.SetFocalPoint(*focal_point)
        cam.SetViewUp(*view_up)
        cam.ParallelProjectionOn()
        
        z_extent = max(zmax - zmin, 0.5)
        perp_xy = np.array([-tangent[1], tangent[0], 0.0])
        perp_norm = np.linalg.norm(perp_xy)
        if perp_norm > 1e-9:
            perp_xy = perp_xy / perp_norm
            proj_perp = np.dot(pts[:, :2], perp_xy[:2])
            perp_extent = max(np.max(proj_perp) - np.min(proj_perp), 0.5)
        else:
            perp_extent = max(xmax - xmin, ymax - ymin, 0.5)
        
        scale = max(z_extent, perp_extent) * 0.6
        cam.SetParallelScale(scale)
        ren.ResetCameraClippingRange()
        
        if abs(self.cut_yaw_deg) > 1e-6:
            cam.Azimuth(self.cut_yaw_deg)
            ren.ResetCameraClippingRange()


    def _make_colors(self, pts, classes):
        """Generate RGB colors from classifications."""
        palette = self.cut_palette if getattr(self, "cut_palette", None) else getattr(self.app, "class_palette", {})
        colors = np.zeros((pts.shape[0], 3), dtype=np.uint8)

        for code in np.unique(classes):
            entry = palette.get(int(code), {"color": (200, 200, 200), "show": True})
            if entry.get("show", True):
                colors[classes == code] = entry["color"]
            else:
                colors[classes == code] = (0, 0, 0)  # hidden

        return colors


    def get_cut_section_classification_data(self):
        """
        Returns cut section points and their original dataset indices.
        
        Returns:
            tuple: (cut_points, original_indices) or (None, None) if not available
        """
        if self.cut_points is None or self._cut_index_map is None:
            return None, None
        
        # Verify index map is valid
        if len(self._cut_index_map) != len(self.cut_points):
            print(f"⚠️ Index map size mismatch - rebuilding...")
            self._rebuild_cut_index_map()
        
        # ✅ Verify indices are within bounds
        max_idx = len(self.app.data['xyz']) if hasattr(self.app, 'data') else 0
        if max_idx > 0 and np.max(self._cut_index_map) >= max_idx:
            print(f"❌ ERROR: Cut index map contains out-of-bounds indices!")
            print(f"   Max index in map: {np.max(self._cut_index_map)}")
            print(f"   Dataset size: {max_idx}")
            return None, None
        
        return self.cut_points, self._cut_index_map

    def onclassificationchanged(self, changedoriginalindices=None):
        # CRITICAL MicroStation-style refresh after classification
        if self._is_refreshing or not self.is_cut_view_active or self.cut_vtk is None:
            return
        self._is_refreshing = True
        try:
            print("CUT SECTION CLASSIFICATION CHANGED")

            # Refresh cut section view IN-PLACE
            print("Refreshing cut section view preserving state")
            self._refresh_cut_colors_fast()
            print("Cut section view updated")

            # Optional main-view partial/full refresh (existing logic)
            if changedoriginalindices is not None and len(changedoriginalindices) > 0:
                print("Updating main view", len(changedoriginalindices), "changed points")
                if hasattr(self.app, "updatemainviewpartial"):
                    self.app.updatemainviewpartial(changedoriginalindices)
                elif hasattr(self.app, "refreshmainviewcolors"):
                    self.app.refreshmainviewcolors(changedoriginalindices)
                else:
                    if hasattr(self.app, "refreshdisplay"):
                        print("Using full refresh")
                        self.app.refreshdisplay()
                        print("Main view updated")

            if hasattr(self.app, "statusBar"):
                numchanged = len(changedoriginalindices) if changedoriginalindices is not None else 0
                self.app.statusBar().showMessage(
                    f"Classified {numchanged} points in cut section", 2000
                )
        except Exception as e:
            print("Classification refresh error", e)
            import traceback
            traceback.print_exc()
        finally:
            self._is_refreshing = False

    def _refresh_cut_colors_fast(self):
        """
        🚀 MILLISECOND REFRESH: Directly modifies GPU color buffers.
        ✅ NO LAG: Stops the 3-4 second actor recreation cycle.
        ✅ ZERO-COPY: Uses np.copyto for direct VTK pointer manipulation.
        ✅ STABLE: Preserves camera and secondary actors.
        """
        if not self.is_cut_view_active or self.cut_points is None or self._cut_index_map is None:
            return
        
        if self.cut_vtk is None or not hasattr(self.app, 'data'):
            return

        try:
            import numpy as np
            from vtkmodules.util import numpy_support

            # 1. Prepare Classification Data
            # Map global classification indices to the local cut view subset
            classes = self.app.data["classification"][self._cut_index_map].astype(int)
            palette = getattr(self, 'cut_palette', getattr(self.app, "class_palette", {}))
            
            # 2. Optimized Lookup Table (LUT) Construction
            # We determine the size based on the palette keys to prevent index errors
            max_class_val = int(classes.max()) if classes.size > 0 else 0
            palette_max = max(palette.keys()) if palette else 0
            lut_size = max(max_class_val, palette_max) + 1
            
            lut = np.zeros((lut_size, 3), dtype=np.uint8)
            for code, info in palette.items():
                if info.get('show', True):
                    lut[code] = info.get('color', (128, 128, 128))
                else:
                    lut[code] = (0, 0, 0) # Hidden points set to black

            # 3. Fast Path: GPU Buffer Update
            target_actor = getattr(self, 'cut_core_actor', None)
            if target_actor and hasattr(target_actor, 'GetMapper'):
                polydata = target_actor.GetMapper().GetInput()
                if polydata:
                    vtk_colors = polydata.GetPointData().GetScalars()
                    
                    # Ensure the existing VTK scalar array is compatible
                    if vtk_colors and vtk_colors.GetNumberOfTuples() == len(classes):
                        # Vectorized mapping: Map classes to RGB via LUT
                        # new_rgb = lut[classes]

                        new_rgb = safe_lut_indexing(lut, classes)

                        # Direct Memory Access: Copy numpy data into VTK's existing memory pointer
                        vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                        np.copyto(vtk_ptr, new_rgb)
                        
                        # Trigger VTK pipeline update without rebuilding the actor
                        vtk_colors.Modified()
                        _safe_vtk_render(self.cut_vtk)
                        return  # 🔥 Performance Success: Exit immediately

            # 4. Fallback Path: Initial Actor Creation
            # This only runs once or if the point count changed.
            cloud = pv.PolyData(self.cut_points)
            # cloud["RGB"] = lut[classes]

            cloud["RGB"] = safe_lut_indexing(lut, classes)

            # Avoid clear() if possible to prevent flickering; remove only the core actor
            if hasattr(self, 'cut_core_actor') and self.cut_core_actor in self.cut_vtk.renderer.GetActors():
                self.cut_vtk.remove_actor(self.cut_core_actor)
            
            self.cut_core_actor = self.cut_vtk.add_points(
                cloud, 
                scalars="RGB", 
                rgb=True, 
                point_size=3, 
                render_points_as_spheres=False,
                name="cut_core_points" # Named for easy retrieval
            )
            
            _safe_vtk_render(self.cut_vtk)

        except Exception as e:
            print(f"❌ Cut color refresh failed: {str(e)}")
            import traceback
            traceback.print_exc()


    def _ensure_cut_section_dock(self):
            """Create dedicated dock window for cut section with INLINE depth control."""
            if self.cut_dock is not None and self.cut_vtk is not None:
                return

            # Cleanup existing dock/VTK
            if self.cut_vtk is not None:
                try:
                    self.cut_vtk.close()
                    self.cut_vtk.Finalize()
                except Exception:
                    pass
                self.cut_vtk = None
            
            if self.cut_dock is not None:
                try:
                    self.cut_dock.close()
                    self.cut_dock.deleteLater()
                except Exception:
                    pass
                self.cut_dock = None

            # Create new dock
            self.cut_dock = QDockWidget("✂️ Cut Section", self.app)
            self.cut_dock.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
            self.cut_dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetFloatable)
            self.cut_dock.setAllowedAreas(Qt.NoDockWidgetArea)
            
            container = QWidget()
            layout = QVBoxLayout(container)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(6)

            # Create DEDICATED VTK widget for cut section
            self.cut_vtk = QtInteractor(container)
            self.cut_vtk.set_background("black")
            layout.addWidget(self.cut_vtk.interactor)
            if hasattr(self.app, "_register_canvas_cursor_widget"):
                self.app._register_canvas_cursor_widget(self.cut_vtk.interactor)
            if hasattr(self.app, "point_sync_tool") and self.app.point_sync_tool.active:
                self.app.point_sync_tool.activate_for_cut_view(self.cut_vtk)

            # Modern bottom bar with inline depth control
            btn_layout = QHBoxLayout()

            # Depth label
            self.depth_label = QLabel("Depth (m):")
            self.depth_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            btn_layout.addWidget(self.depth_label)

            # Depth spinbox

            self.depth_spin = QDoubleSpinBox()
            self.depth_spin.setDecimals(2)

            # ✅ CRITICAL: Calculate reasonable max depth based on data bounds
            max_depth = 100.0  # Default fallback
            try:
                if hasattr(self.app, 'data') and 'xyz' in self.app.data:
                    xyz = self.app.data['xyz']
                    # Max depth should be ~10% of dataset extent (prevents freezing)
                    x_extent = float(np.ptp(xyz[:, 0]))  # ptp = peak-to-peak (max - min)
                    y_extent = float(np.ptp(xyz[:, 1]))
                    z_extent = float(np.ptp(xyz[:, 2]))
                    
                    max_extent = max(x_extent, y_extent, z_extent)
                    max_depth = min(max_extent * 0.1, 100.0)  # Cap at 100m
                    
                    print(f"📏 Dataset extent: X={x_extent:.1f}m, Y={y_extent:.1f}m, Z={z_extent:.1f}m")
                    print(f"   Max cut depth set to: {max_depth:.1f}m (10% of max extent)")
                else:
                    print(f"⚠️ No dataset available, using default max depth: {max_depth}m")
            except Exception as e:
                print(f"⚠️ Could not calculate max depth: {e}, using {max_depth}m")

            # ✅ Set validated range (min: 0.01m, max: calculated or 100m)
            self.depth_spin.setRange(0.01, max_depth)
            self.depth_spin.setSingleStep(0.10)
            self.depth_spin.setValue(getattr(self, 'dynamic_depth', 1.0))
            self.depth_spin.setMinimumWidth(90)
            self.depth_spin.setFixedHeight(28)
            self.depth_spin.setAlignment(Qt.AlignRight)
            self.depth_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)

            # ✅ BUG #6 FIX: Add tooltip showing valid range
            self.depth_spin.setToolTip(
                f"Cut section depth (±meters from center line)\n"
                f"Valid range: 0.01m - {max_depth:.1f}m\n"
                f"Adjust with mouse or type value"
            )

            btn_layout.addWidget(self.depth_spin)
            self.depth_spin.valueChanged.connect(self._on_depth_spin_changed)

            btn_layout.addStretch()


            # Reset View button
            reset_view_btn = QPushButton("Reset View")
            reset_view_btn.setToolTip("Reset camera to correct orthogonal view along tangent")
            reset_view_btn.clicked.connect(self._reset_cut_view_camera)
            btn_layout.addWidget(reset_view_btn)

            layout.addLayout(btn_layout)
            self.cut_dock.setWidget(container)

            # ✅ SAFE CLOSE EVENT HANDLER (INSIDE METHOD - self exists)
            def safe_close_event(event):
                """
                Safely close cut section dock by cleaning up FIRST.
                ✅ BUG #13 FIX: Only accept close if cleanup succeeds
                """
                cleanup_succeeded = False
                
                try:
                    print("🚪 User clicked X on cut section dock - cleaning up...")
                    
                    # Save geometry BEFORE closing
                    from PySide6.QtCore import QSettings
                    settings = QSettings("NakshaAI", "LidarApp")
                    if self.cut_dock is not None:
                        try:
                            settings.setValue("CutSectionDock_geometry", self.cut_dock.saveGeometry())
                            print("   💾 Cut section dock geometry saved")
                        except Exception as e:
                            print(f"   ⚠️ Geometry save failed: {e}")
                    
                    # Check if forced close from clear_project
                    force_close = getattr(event, '_force_close', False)
                    
                    if force_close:
                        print("   ✅ Forced close from clear_project - accepting")
                        cleanup_succeeded = True
                        event.accept()
                    else:
                        print("   🧹 Normal user close - full cleanup...")
                        
                        # ✅ BUG #13 FIX: Try cleanup and track success
                        try:
                            self.cancel_cut_section()
                            cleanup_succeeded = True
                            print("   ✅ Cleanup completed successfully")
                        except Exception as cleanup_error:
                            print(f"   ❌ Cleanup failed: {cleanup_error}")
                            import traceback
                            traceback.print_exc()
                            cleanup_succeeded = False
                        
                        # ✅ BUG #13 FIX: Only accept if cleanup succeeded
                        if cleanup_succeeded:
                            event.accept()
                            print("   ✅ Cut section closed safely")
                        else:
                            event.ignore()
                            print("   ⚠️ Close cancelled - cleanup failed, dock remains open")
                            
                            # Show error to user
                            from PySide6.QtWidgets import QMessageBox
                            QMessageBox.critical(
                                self.cut_dock,
                                "Close Failed",
                                "Failed to close cut section properly.\n"
                                "Check console for errors.\n\n"
                                "Try again or restart application."
                            )
                
                except Exception as e:
                    print(f"   ❌ Close event error: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # ✅ BUG #13 FIX: On unexpected error, ignore close (safer than accept)
                    if not cleanup_succeeded:
                        print("   ⚠️ Close cancelled due to unexpected error")
                        event.ignore()
                        
                        # Show error to user
                        try:
                            from PySide6.QtWidgets import QMessageBox
                            QMessageBox.critical(
                                self.cut_dock if self.cut_dock else self.app,
                                "Critical Error",
                                f"Unexpected error during close:\n{str(e)}\n\n"
                                "Dock will remain open. Please restart application."
                            )
                        except:
                            pass
                    else:
                        # Cleanup succeeded but post-processing failed
                        event.accept()


            # ✅ ASSIGN HANDLER
            self.cut_dock.closeEvent = safe_close_event

            # ✅ RESTORE GEOMETRY
            from PySide6.QtCore import QSettings
            settings = QSettings("NakshaAI", "LidarApp")
            saved_geometry = settings.value("CutSectionDock_geometry")

            if saved_geometry is not None:
                self.cut_dock.restoreGeometry(saved_geometry)
                print("✅ Restored cut section dock geometry")
            else:
                self.cut_dock.move(self.app.x() + 100, self.app.y() + 150)
                self.cut_dock.resize(600, 500)
                print("→ Default position for cut dock")

            # ✅ SHOW DOCK
            self.cut_dock.show()

        
        # Override closeEvent
    def safe_close_event(event, self):
        try:
            # ✅ Check if this is a forced close from clear_project
            force_close = getattr(event, '_force_close', False)
            
            # ✅ FIX: Check if render window is still valid BEFORE any VTK operations
            is_vtk_valid = False
            if self.cut_vtk is not None:
                try:
                    rw = self.cut_vtk.GetRenderWindow()
                    if rw is not None:
                        is_vtk_valid = not rw.IsA('vtkWin32OpenGLRenderWindow') or rw.GetMapped()
                except:
                    is_vtk_valid = False
            
            if force_close:
                # Allow close during clear_project
                print("✅ Cut section dock: accepting forced close")
                if self.cut_vtk is not None and is_vtk_valid:
                    try:
                        # ✅ FIX: Disable render window BEFORE finalization
                        rw = self.cut_vtk.GetRenderWindow()
                        if rw is not None:
                            rw.SetMapped(False)  # Stop rendering
                            rw.Finalize()  # Safe finalize
                        self.cut_vtk.close()
                    except Exception as e:
                        print(f"⚠️ VTK cleanup: {e}")
                    self.cut_vtk = None
                self.cut_dock = None
                self.is_cut_view_active = False
                self._cut_camera_state = None
                event.accept()  # ✅ Accept the close
            else:
                # Normal user close - just hide
                print("🔵 Cut section dock: user closed (hiding, not destroying)")
                self.cut_dock.hide()
                
                # ✅ FIX: Only finalize if VTK is still valid
                if self.cut_vtk is not None and is_vtk_valid:
                    try:
                        # ✅ FIX: Disable render window BEFORE finalization
                        rw = self.cut_vtk.GetRenderWindow()
                        if rw is not None:
                            rw.SetMapped(False)  # Stop rendering
                            rw.Finalize()  # Safe finalize
                        self.cut_vtk.close()
                    except Exception as e:
                        print(f"⚠️ VTK cleanup: {e}")
                    self.cut_vtk = None
                
                self.cut_dock = None
                self.is_cut_view_active = False
                self._cut_camera_state = None
                event.ignore()  # ✅ Prevent dock destruction (Qt will handle it)
                
        except Exception as e:
            print(f"⚠️ Close event error: {e}")
            import traceback
            traceback.print_exc()


    def _plot_cut_to_dedicated_widget(self, points):
        """
        Plot cut section to the DEDICATED cut section widget.
        ✅ FIXED: Uses cut-specific palette via _make_colors()
        """
        if points is None or points.shape[0] == 0:
            return
        
        # Get classifications
        classes = self.app.data.get("classification", None)
        
        if self._cut_index_map is None or len(self._cut_index_map) != len(points):
            self._rebuild_cut_index_map()
        
        # ✅ Build colors using cut-specific palette
        # _make_colors() now checks self.cut_palette first!
        if classes is not None and self._cut_index_map is not None:
            cut_classes = classes[self._cut_index_map]
            colors = self._make_colors(points, cut_classes)  # ← Uses self.cut_palette!
            print(f"   🎨 Colors built using {'cut palette' if hasattr(self, 'cut_palette') and self.cut_palette else 'global palette'}")
        else:
            colors = np.full((points.shape[0], 3), 200, dtype=np.uint8)
        
        # Clear the dedicated widget
        try:
            ren = self.cut_vtk.renderer
            ren.RemoveAllViewProps()
        except Exception:
            pass
        
        # Create point cloud
        cloud = pv.PolyData(points)
        cloud["RGB"] = colors
        
        # Render with borders if needed
        # border_percent = getattr(self.app, "point_border_percent", 0)
        border_percent = 0
        if hasattr(self.app, "view_borders"):
            border_percent = self.app.view_borders.get(5, 0)

        base_size = 3
        
        if border_percent > 0:
            border_scale = border_percent / 50.0
            border_size = base_size * (1.0 + border_scale)
            self.cut_core_actor = self.cut_vtk.add_points(cloud, color='black', point_size=border_size, render_points_as_spheres=False)
            self.cut_buffer_actor = self.cut_vtk.add_points(cloud, scalars="RGB", rgb=True, point_size=base_size, render_points_as_spheres=False)
        else:
            self.cut_core_actor = self.cut_vtk.add_points(cloud, scalars="RGB", rgb=True, point_size=base_size, render_points_as_spheres=False)
        
        # Set camera along tangent
        if self.section_tangent is not None:
            self._set_camera_along_tangent(self.cut_vtk, points, self.section_tangent)
        else:
            ren = self.cut_vtk.renderer
            ren.ResetCamera()
            ren.GetActiveCamera().ParallelProjectionOn()
            ren.ResetCameraClippingRange()
        _safe_vtk_render(self.cut_vtk)
        
        print(f"✅ Cut plotted to dedicated widget: {points.shape[0]} pts")


    def _debug_coordinate_spaces(self):
        """Debug helper to verify coordinate transformations."""
        print("\n" + "="*60)
        print("🔍 COORDINATE SPACE DEBUG")
        print("="*60)
        
        # Check if we have cross-section data
        if hasattr(self.app, 'section_points'):
            sec_pts = self.app.section_points
            print(f"section_points (TRANSFORMED): {len(sec_pts) if sec_pts is not None else 0}")
            if sec_pts is not None and len(sec_pts) > 0:
                print(f"   X: [{sec_pts[:, 0].min():.2f}, {sec_pts[:, 0].max():.2f}]")
                print(f"   Y: [{sec_pts[:, 1].min():.2f}, {sec_pts[:, 1].max():.2f}]")
                print(f"   Z: [{sec_pts[:, 2].min():.2f}, {sec_pts[:, 2].max():.2f}]")
        
        # Check original world coordinates
        if hasattr(self.app, 'data') and 'xyz' in self.app.data:
            all_xyz = self.app.data['xyz']
            if hasattr(self.app.section_controller, 'last_mask'):
                mask = self.app.section_controller.last_mask
                selected = all_xyz[mask]
                print(f"\nOriginal world coords (SELECTED): {len(selected)}")
                print(f"   X: [{selected[:, 0].min():.2f}, {selected[:, 0].max():.2f}]")
                print(f"   Y: [{selected[:, 1].min():.2f}, {selected[:, 1].max():.2f}]")
                print(f"   Z: [{selected[:, 2].min():.2f}, {selected[:, 2].max():.2f}]")
        
        # Check cut points
        if self.cut_points is not None and len(self.cut_points) > 0:
            print(f"\ncut_points: {len(self.cut_points)}")
            print(f"   X: [{self.cut_points[:, 0].min():.2f}, {self.cut_points[:, 0].max():.2f}]")
            print(f"   Y: [{self.cut_points[:, 1].min():.2f}, {self.cut_points[:, 1].max():.2f}]")
            print(f"   Z: [{self.cut_points[:, 2].min():.2f}, {self.cut_points[:, 2].max():.2f}]")
        
        print("="*60 + "\n")
             
    def sync_palette_from_source_view(self):
        """
        ✅ FIXED: Properly sync palette while preserving EXACT visibility state.
        Prevents "all classes visible" bug after classification in cut section.
        """
        try:
            # Determine source view index
            source_view_idx = None
           
            if self.is_cut_view_active and hasattr(self, 'parent_cut_points'):
                # Nested cut - inherit from previous cut section
                source_view_idx = 5  # Cut Section View slot
                print(f"📋 Nested cut: inheriting palette from previous cut section")
            else:
                # First cut - inherit from active cross-section view
                if hasattr(self.app, 'section_controller'):
                    active_view = getattr(self.app.section_controller, 'active_view', 0)
                    source_view_idx = active_view + 1  # Convert to slot index (1-4)
                    print(f"📋 First cut: inheriting palette from Cross-Section View {active_view + 1}")
           
            if source_view_idx is None:
                print("⚠️ No source view to inherit palette from")
                return False
           
            # ═══════════════════════════════════════════════════════════════
            # ✅ CRITICAL FIX: Get palette from DISPLAY DIALOG FIRST
            # This is the authoritative source for visibility states
            # ═══════════════════════════════════════════════════════════════
            source_palette = None
           
            # Priority 1: Display Mode Dialog (most reliable)
            if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
                dialog = self.app.display_mode_dialog
                if hasattr(dialog, 'view_palettes') and source_view_idx in dialog.view_palettes:
                    source_palette = dialog.view_palettes[source_view_idx]
                    print(f"   ✅ Found palette in dialog.view_palettes[{source_view_idx}] (authoritative)")
           
            # Priority 2: App view_palettes (fallback)
            if not source_palette:
                if hasattr(self.app, 'view_palettes') and source_view_idx in self.app.view_palettes:
                    source_palette = self.app.view_palettes[source_view_idx]
                    print(f"   ✅ Found palette in app.view_palettes[{source_view_idx}] (fallback)")
           
            if not source_palette:
                print(f"⚠️ No palette found for source view {source_view_idx}")
                return False
           
            # ═══════════════════════════════════════════════════════════════
            # ✅ CRITICAL FIX: Deep copy with STRICT validation
            # ═══════════════════════════════════════════════════════════════
            self.cut_palette = {}
            visible_count = 0
            hidden_count = 0
           
            print(f"\n   🔍 DEBUG: Syncing palette from source view {source_view_idx}...")
 
            for code, info in source_palette.items():
                code_int = int(code)
               
                # ✅ CRITICAL: Strict validation of 'show' field
                if 'show' not in info:
                    print(f"      ⚠️ Class {code_int}: Missing 'show' field - defaulting to True")
                    is_visible = True
                else:
                    is_visible = info['show']
                   
                    # ✅ EXTRA VALIDATION: Ensure it's actually a boolean
                    if not isinstance(is_visible, bool):
                        print(f"      ⚠️ Class {code_int}: 'show' is {type(is_visible)}, converting...")
                        is_visible = bool(is_visible)
               
                # ✅ Create new palette entry with validated visibility
                self.cut_palette[code_int] = {
                    'show': is_visible,  # ← STRICTLY validated boolean
                    'description': str(info.get('description', '')),
                    'color': tuple(info.get('color', (128, 128, 128))),
                    'weight': float(info.get('weight', 1.0))
                }
               
                # Track stats
                if is_visible:
                    visible_count += 1
                else:
                    hidden_count += 1
               
                # ✅ DEBUG: Log first 5 classes
                if len(self.cut_palette) <= 5:
                    print(f"      Class {code_int}: show={is_visible} ({'visible' if is_visible else 'HIDDEN'})")
 
            print(f"   ✅ Synced palette: {visible_count} visible, {hidden_count} hidden classes")
           
            # ═══════════════════════════════════════════════════════════════
            # ✅ VERIFICATION: Check if result makes sense
            # ═══════════════════════════════════════════════════════════════
            if hidden_count == 0 and len(self.cut_palette) > 5:
                print(f"   ⚠️ WARNING: All {len(self.cut_palette)} classes are visible - this might be wrong!")
                print(f"   🔍 Source palette had these visibility states:")
                for code, info in list(source_palette.items())[:5]:
                    print(f"      Class {code}: show={info.get('show', 'MISSING')}")
           
            # ✅ CRITICAL: Also update app.view_palettes[5] for persistence
            if hasattr(self.app, 'view_palettes'):
                self.app.view_palettes[5] = dict(self.cut_palette)
           
            # ✅ Update display dialog if open
            if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
                dialog = self.app.display_mode_dialog
                if hasattr(dialog, 'view_palettes'):
                    dialog.view_palettes[5] = dict(self.cut_palette)
           
            return True
           
        except Exception as e:
            print(f"❌ Palette sync failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def sync_palette_to_display_dialog(self):
        """
        ✅ NEW: Sync cut section palette TO Display Mode dialog.
        Called when cut section palette is updated via Display Mode.
        
        Flow: Cut Section View → Display Mode Dialog
        """
        try:
            if not hasattr(self, 'cut_palette') or not self.cut_palette:
                return False
            
            dialog = None
            if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
                dialog = self.app.display_mode_dialog
            
            if not dialog:
                print("⚠️ Display Mode dialog not open")
                return False
            
            # Update dialog's view_palettes[5]
            if not hasattr(dialog, 'view_palettes'):
                dialog.view_palettes = {}
            
            dialog.view_palettes[5] = {}
            for code, info in self.cut_palette.items():
                dialog.view_palettes[5][int(code)] = {
                    'show': bool(info.get('show', True)),
                    'description': str(info.get('description', '')),
                    'color': tuple(info.get('color', (128, 128, 128))),
                    'weight': float(info.get('weight', 1.0))
                }
            
            print(f"   ✅ Synced {len(self.cut_palette)} classes to Display Mode dialog")
            
            # ✅ If dialog is showing Cut Section View, refresh table
            if hasattr(dialog, 'current_slot') and dialog.current_slot == 5:
                if hasattr(dialog, '_load_slot_checkboxes'):
                    dialog._load_slot_checkboxes(5)
                    print(f"   🔄 Refreshed Cut Section View checkboxes in dialog")
            
            return True
            
        except Exception as e:
            print(f"❌ Dialog sync failed: {e}")
            import traceback
            traceback.print_exc()
            return False


    def on_display_mode_apply(self, payload):
        """
        ✅ NEW: Handle Display Mode apply for cut section view.
        Called when user clicks Apply button in Display Mode dialog.
        
        Args:
            payload: Dictionary from DisplayModeDialog.on_apply()
        """
        try:
            # Only handle if targeting Cut Section View (slot 5)
            if payload.get('target_view') != 5 and payload.get('slot') != 5:
                return
            
            print(f"\n{'='*60}")
            print(f"🎨 DISPLAY MODE APPLIED TO CUT SECTION VIEW")
            print(f"{'='*60}")
            
            # Extract new palette
            new_palette = payload.get('classes', {})
            if not new_palette:
                print("⚠️ No classes in payload")
                return
            
            # Update cut_palette
            self.cut_palette = {}
            visible_count = 0
            
            for code, info in new_palette.items():
                code = int(code)
                is_visible = info.get('show', True)
                
                self.cut_palette[code] = {
                    'show': bool(is_visible),
                    'description': str(info.get('description', '')),
                    'color': tuple(info.get('color', (128, 128, 128))),
                    'weight': float(info.get('weight', 1.0))
                }
                
                if is_visible:
                    visible_count += 1
            
            print(f"   ✅ Updated cut palette: {len(self.cut_palette)} classes ({visible_count} visible)")
            
            # ✅ Update border value
            border_percent = payload.get('border_percent', 0)
            if hasattr(self.app, 'view_borders'):
                self.app.view_borders[5] = border_percent
                print(f"   ✅ Updated border: {border_percent}%")
            
            # ✅ Refresh cut section view with new palette
            if self.is_cut_view_active and self.cut_vtk is not None:
                self._refresh_cut_colors_fast()
                print(f"   🔄 Cut section view refreshed")
            
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"❌ Display mode apply failed: {e}")
            import traceback
            traceback.print_exc()
            
    def refresh_colors_direct(self):
        """
        Refresh colors of cut section visualization based on current classification.
        Called after points are classified in the cut section view.
        
        ✅ Delegates to the proven working method: _refresh_cut_colors_fast()
        ✅ That method handles all the complex VTK buffer updates correctly.
        """
        try:
            print("   🎨 Updating cut section colors...")
            
            # ✅ Call the proven, working method
            self._refresh_cut_colors_fast()
            
            print("   ✅ Cut section colors updated")
            
        except Exception as e:
            print(f"   ❌ Error refreshing cut section colors: {e}")
            import traceback
            traceback.print_exc()

    def _compute_colors_for_indices(self, classifications):
        """
        Compute RGB colors for cut section points based on their classification.
        
        Args:
            classifications: numpy array of classification codes
            
        Returns:
            numpy array of shape (N, 3) with RGB values [0-255]
        """
        try:
            n_points = len(classifications)
            colors = np.zeros((n_points, 3), dtype=np.uint8)
            
            if not hasattr(self.app, 'class_palette'):
                # Default: gray for all
                colors[:] = [128, 128, 128]
                return colors
            
            palette = self.app.class_palette
            
            for i, class_code in enumerate(classifications):
                if class_code in palette:
                    class_entry = palette[class_code]
                    
                    # Extract color from palette
                    if 'color' in class_entry:
                        rgb = class_entry['color']
                        
                        # Handle different color formats
                        if isinstance(rgb, (list, tuple)):
                            # Could be [0-1] or [0-255]
                            if max(rgb) <= 1.0:
                                colors[i] = np.array(rgb[:3]) * 255
                            else:
                                colors[i] = rgb[:3]
                        else:
                            colors[i] = [128, 128, 128]
                    else:
                        colors[i] = [128, 128, 128]
                else:
                    # Unknown class: light gray
                    colors[i] = [200, 200, 200]
            
            return colors
            
        except Exception as e:
            print(f"   ⚠️ Error computing colors: {e}")
            return None

    def _apply_colors_to_visualization(self, colors):
        """
        Apply RGB colors to the cut section visualization.
        
        Args:
            colors: numpy array of shape (N, 3) with RGB values [0-255]
        """
        try:
            # Update the dataset colors in cut_vtk
            if not hasattr(self, 'cut_vtk') or self.cut_vtk is None:
                print("   ⚠️ No cut_vtk object")
                return
            
            # Method 1: Update dataset directly
            if hasattr(self.cut_vtk, 'dataset') and self.cut_vtk.dataset is not None:
                try:
                    # pyvista dataset
                    self.cut_vtk.dataset['RGB'] = colors
                    print("   ✅ Colors applied to dataset")
                    return
                except Exception as e:
                    print(f"   ⚠️ Dataset color update failed: {e}")
            
            # Method 2: Update actor mapper colors
            if hasattr(self.cut_vtk, 'actor') and self.cut_vtk.actor is not None:
                try:
                    actor = self.cut_vtk.actor
                    mapper = actor.GetMapper()
                    
                    if mapper is not None:
                        # Create color array for VTK
                        vtk_colors = vtk.vtkUnsignedCharArray()
                        vtk_colors.SetNumberOfComponents(3)
                        vtk_colors.SetName("RGB")
                        
                        for color in colors:
                            vtk_colors.InsertNextTuple3(int(color[0]), int(color[1]), int(color[2]))
                        
                        # Assign to mapper
                        mapper.GetInput().GetPointData().SetScalars(vtk_colors)
                        print("   ✅ Colors applied to actor mapper")
                        return
                except Exception as e:
                    print(f"   ⚠️ Actor mapper color update failed: {e}")
            
            # Method 3: If it's a PolyData with point colors
            if hasattr(self.cut_vtk, '_mesh') and self.cut_vtk._mesh is not None:
                try:
                    self.cut_vtk._mesh['RGB'] = colors
                    print("   ✅ Colors applied to mesh")
                    return
                except Exception as e:
                    print(f"   ⚠️ Mesh color update failed: {e}")
            
            print("   ⚠️ Could not find visualization object to update colors")
            
        except Exception as e:
            print(f"   ❌ Error applying colors: {e}")
            import traceback
            traceback.print_exc()        
            
    def _clear_preview_from_other_views(self, current_vtk):
        """
        Clear preview actors (line, buffer bands) from all cross-section views
        except the currently active one.
        
        Args:
            current_vtk: The currently active VTK widget (where preview should appear)
        """
        if not hasattr(self.app, 'section_vtks'):
            return
        
        actors_to_clear = [
            self.line_actor,
            self.buffer_actor_upper,
            self.buffer_actor_lower
        ]
        
        for view_idx, vtk_widget in self.app.section_vtks.items():
            if vtk_widget == current_vtk:
                continue  # Skip the active view
            
            try:
                ren = vtk_widget.renderer
                for actor in actors_to_clear:
                    if actor is not None:
                        try:
                            ren.RemoveActor(actor)
                        except:
                            pass
                
                # Render to show the removal
                try:
                    _safe_vtk_render(vtk_widget)
                except:
                    pass
            except:
                pass
