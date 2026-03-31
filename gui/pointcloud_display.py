
# import numpy as np
# import pyvista as pv
# from scipy.spatial import Delaunay
# from .views import set_view
# from PySide6.QtCore import QObject, QThread, Signal, QTimer
# import vtk

# def _restore_snt_after_clear(app):
#     """
#     Re-add SNT actors to the renderer after clear() and apply Z offset
#     so SNT always renders on top of the current point cloud.

#     Must be called AFTER point cloud data is loaded into app.data
#     (otherwise Z offset = 0 and SNT stays behind the cloud).
#     """
#     # ── Step 1: Restore via snt_dialog (updates Z offset internally) ────
#     if hasattr(app, 'snt_dialog') and app.snt_dialog is not None:
#         try:
#             app.snt_dialog.restore_snt_actors()
#         except Exception as e:
#             print(f"  ⚠️ SNT restore via dialog: {e}")
#         return

#     # ── Step 2: Fallback — iterate snt_actors/dxf_actors directly ───────
#     from gui.snt_attachment import _get_snt_z_offset, _apply_z_offset_to_actor

#     try:
#         renderer = app.vtk_widget.renderer
#     except Exception:
#         return

#     z_offset = _get_snt_z_offset(app)
#     restored = 0

#     for store_name in ['snt_actors', 'dxf_actors']:
#         for entry in getattr(app, store_name, []):
#             for actor in entry.get("actors", []):
#                 try:
#                     is_overlay = getattr(actor, '_is_dxf_actor', False)
#                     if is_overlay and z_offset > 0:
#                         _apply_z_offset_to_actor(actor, z_offset)
#                     renderer.AddActor(actor)  # idempotent
#                     restored += 1
#                 except Exception:
#                     pass

#     if restored > 0:
#         renderer.ResetCameraClippingRange()
#         print(f"  🔄 Fallback SNT restore: {restored} actors (z_offset={z_offset:.1f})")
#         try:
#             app.vtk_widget.GetRenderWindow().Render()
#         except Exception:
#             pass
# # -------------------------------------------------------------
# # WORKER
# # -------------------------------------------------------------
# class ColorUpdateWorker(QObject):
#     finished = Signal(object)

#     def __init__(self, app, mask=None):
#         super().__init__()
#         self.app = app
#         self.mask = mask

#     def run(self):
#         try:
#             colors = compute_colors(self.app, mask=self.mask)
#             self.finished.emit(colors)
#         except Exception as e:
#             print(f"⚠️ Worker color computation failed: {e}")
#             self.finished.emit(None)


# # -------------------------------------------------------------
# # COLOR COMPUTATION
# # -------------------------------------------------------------
# def compute_colors(app, mask=None, section_points=None):
#     """Compute per-point colors for non-shaded modes."""
#     mode = app.display_mode
#     xyz = app.data["xyz"]

#     if mask is None:
#         mask = np.ones(xyz.shape[0], dtype=bool)

#     pts = xyz[mask]
#     colors = np.full((pts.shape[0], 3), 200, dtype=np.uint8)

#     # --- RGB ---
#     if mode == "rgb" and app.data.get("rgb") is not None:
#         rgb = app.data["rgb"][mask]
#         if rgb.max() <= 1.0:
#             rgb = (rgb * 255).astype(np.uint8)
#         colors = rgb

#     # --- Intensity ---
#     elif mode == "intensity" and app.data.get("intensity") is not None:
#         intens = app.data["intensity"][mask].astype(float)
#         norm = (intens - intens.min()) / (intens.max() - intens.min() + 1e-6)
#         gray = (norm * 255).astype(np.uint8)
#         colors = np.stack([gray, gray, gray], axis=1)

#     # --- Elevation ---
#     elif mode == "elevation":
#         if section_points is not None:
#             if section_points.shape[1] >= 3:
#                 z = section_points[:, 2]
#             else:
#                 z = section_points[:, 1]
#         else:
#             z = pts[:, 2]
#         norm = (z - z.min()) / (z.max() - z.min() + 1e-6)
#         colors = np.c_[norm * 255, norm * 255, (1 - norm) * 255].astype(np.uint8)

#     # --- Depth ---
#     elif mode == "depth":
#         """Grayscale depth map based on Z or section plane distance."""
#         print("🧱 Computing depth colors...")

#         # Use full xyz for depth (not filtered)
#         xyz_full = app.data.get("xyz")
#         if xyz_full is None or len(xyz_full) == 0:
#             print("⚠️ No XYZ data for depth")
#             return colors

#         # Compute distances
#         if hasattr(app, "section_origin") and hasattr(app, "section_normal") \
#            and app.section_origin is not None and app.section_normal is not None:
#             origin = np.asarray(app.section_origin, dtype=np.float64)
#             normal = np.asarray(app.section_normal, dtype=np.float64)
#             normal /= np.linalg.norm(normal) + 1e-9
#             distances = np.dot(xyz_full - origin, normal)
#             print("📏 Depth: using section plane distances")
#         else:
#             z = xyz_full[:, 2]
#             distances = z - np.min(z)
#             print("📏 Depth: using Z elevation")

#         # Normalize with percentile clipping
#         dmin, dmax = np.percentile(distances, [1, 99])
#         depth_norm = np.clip((distances - dmin) / (dmax - dmin + 1e-9), 0, 1)
        
#         # Gamma correction
#         depth_norm = depth_norm ** 0.6
        
#         # Apply mask if provided
#         if mask is not None and mask.size == depth_norm.size:
#             depth_norm = depth_norm[mask]

#         # Convert to grayscale
#         gray = (depth_norm * 255).astype(np.uint8)
#         colors = np.stack([gray, gray, gray], axis=1)

#     # --- Classification ---
#     elif mode in ("class", "shaded_class") and app.data.get("classification") is not None:
#         classes = app.data["classification"][mask]
#         colors = np.zeros((pts.shape[0], 3), dtype=np.uint8)

#         if not hasattr(app, "class_palette") or not app.class_palette:
#             unique_classes = np.unique(classes)
#             app.class_palette = {
#                 int(code): {"color": (160, 160, 160), "show": True}
#                 for code in unique_classes
#             }

#         for code in np.unique(classes):
#             local_mask = classes == code
#             entry = app.class_palette.get(
#                 int(code), {"color": (128, 128, 128), "show": True}
#             )
#             if entry["show"]:
#                 colors[local_mask] = entry["color"]
#             else:
#                 colors[local_mask] = [0, 0, 0]

#         weight = getattr(app, "class_weight", 1.0)
#         colors = np.clip(colors * weight, 0, 255).astype(np.uint8)

#     return colors


# class ShadedMeshWorker(QThread):
#     """Worker thread to build shaded mesh asynchronously."""
#     finished = Signal(object)

#     def __init__(self, app):
#         super().__init__()
#         self.app = app

#     def run(self):
#         try:
#             xyz = self.app.data["xyz"]
#             classes = self.app.data["classification"]
#             tri = Delaunay(xyz[:, :2])
#             F = tri.simplices
#             v1, v2, v3 = xyz[F[:, 0]], xyz[F[:, 1]], xyz[F[:, 2]]
#             fn = np.cross(v2 - v1, v3 - v1)
#             fn /= np.linalg.norm(fn, axis=1, keepdims=True) + 1e-9

#             az = np.deg2rad(getattr(self.app, "last_shade_azimuth", 45.0))
#             el = np.deg2rad(getattr(self.app, "last_shade_angle", 45.0))
#             Ld = np.array([np.cos(el) * np.cos(az),
#                            np.cos(el) * np.sin(az),
#                            np.sin(el)])
#             Ld /= np.linalg.norm(Ld)
#             shade = getattr(self.app, "shade_ambient", 0.2) + \
#                     (1 - getattr(self.app, "shade_ambient", 0.2)) * np.clip(fn @ Ld, 0, 1)

#             colors = np.zeros((F.shape[0], 3), dtype=np.uint8)
#             for i, face in enumerate(F):
#                 c = classes[face]
#                 majority = np.bincount(c).argmax()
#                 entry = self.app.class_palette.get(int(majority), {"color": (128, 128, 128)})
#                 base = np.array(entry["color"], dtype=np.float32)
#                 colors[i] = np.clip(base * shade[i], 0, 255)

#             faces = np.hstack([np.full((F.shape[0], 1), 3), F]).astype(np.int32)
#             mesh = pv.PolyData(xyz, faces)
#             mesh.cell_data["RGB"] = colors

#             self.finished.emit(mesh)
#         except Exception as e:
#             print(f"⚠️ ShadedMeshWorker failed: {e}")
#             self.finished.emit(None)

# def update_pointcloud(app, mode="rgb"):
#     """
#     Single unified point cloud update function.
#     ✅ Handles all display modes with proper validation
#     ✅ NEW: Supports saturation and sharpness amplifiers for depth/intensity modes
#     """
#     import numpy as np
#     import pyvista as pv

#     if app.data is None or "xyz" not in app.data:
#         print("⚠️ No point cloud data loaded")
#         return

#     xyz = app.data["xyz"]
    
#     # ✅ Validation
#     if len(xyz) == 0:
#         print("⚠️ Empty point cloud")
#         app.vtk_widget.clear()
#         app.vtk_widget.render()
#         return

#     if mode == "shaded_class":
#         # ✅ FIX: Delegate to the proper shading pipeline in shading_display.py
#         # The old code here called app.vtk_widget.clear() which destroyed
#         # all DXF/SNT overlay actors. The shading_display pipeline uses
#         # surgical actor management that preserves them.
#         from gui.shading_display import update_shaded_class, clear_shading_cache

#         classes = app.data.get("classification")
#         if classes is None:
#             print("⚠️ No classification found, falling back to class view")
#             return update_pointcloud(app, "class")

#         app.display_mode = "shaded_class"
#         clear_shading_cache("mode switch from menu")
#         update_shaded_class(
#             app,
#             getattr(app, "last_shade_azimuth", 45.0),
#             getattr(app, "last_shade_angle", 45.0),
#             getattr(app, "shade_ambient", 0.2),
#             force_rebuild=True
#         )
#         _restore_snt_after_clear(app)
#         return

#     # =========================================================
#     # --- NORMAL (RGB / INTENSITY / ELEVATION / CLASS / DEPTH) MODES ---
#     # =========================================================    
#     if mode == "class":
#         from gui.class_display import update_class_mode
#         update_class_mode(app, force_refresh=True)
#         # ── FIX: Restore SNT with Z-offset (this path was missing it!) ──
#         _restore_snt_after_clear(app)
#         return

#     colors = compute_colors(app)
    
#     # ✅ CRITICAL VALIDATION
#     if len(colors) == 0:
#         print("⚠️ Empty colors array from compute_colors()")
#         app.vtk_widget.clear()
#         app.vtk_widget.render()
#         return
    
#     if len(xyz) != len(colors):
#         print(f"⚠️ Length mismatch: xyz={len(xyz)}, colors={len(colors)}")
#         min_len = min(len(xyz), len(colors))
#         xyz = xyz[:min_len]
#         colors = colors[:min_len]
#         print(f"   Truncated to {min_len:,} points")

#     # ✅ NEW: Apply frequency amplifiers for depth and intensity modes
#     if mode in ["depth", "intensity"]:
#         saturation = getattr(app, "current_saturation", 1.0)
#         sharpness = getattr(app, "current_sharpness", 1.0)
        
#         print(f"🎚️ Applying amplifiers: saturation={saturation:.2f}x, sharpness={sharpness:.2f}x")
        
#         # Apply sharpness (contrast adjustment)
#         if sharpness != 1.0:
#             # Convert to 0-1 range
#             colors_norm = colors.astype(np.float32) / 255.0
            
#             # Increase contrast by pushing away from 0.5
#             colors_norm = 0.5 + (colors_norm - 0.5) * sharpness
#             colors_norm = np.clip(colors_norm, 0, 1)
            
#             colors = (colors_norm * 255).astype(np.uint8)
#             print(f"   ✅ Sharpness applied: {sharpness:.2f}x")
        
#         # Apply saturation (color intensity)
#         if saturation != 1.0:
#             # Convert to float
#             colors_float = colors.astype(np.float32)
            
#             # Calculate grayscale (luminance)
#             gray = 0.299 * colors_float[:, 0] + 0.587 * colors_float[:, 1] + 0.114 * colors_float[:, 2]
#             gray = gray[:, np.newaxis]
            
#             # Blend between grayscale and color based on saturation
#             # saturation = 0.0 → full grayscale
#             # saturation = 1.0 → original colors
#             # saturation = 2.0 → hyper-saturated
#             if saturation < 1.0:
#                 # Desaturate towards gray
#                 colors_float = gray + (colors_float - gray) * saturation
#             else:
#                 # Hyper-saturate away from gray
#                 colors_float = gray + (colors_float - gray) * saturation
            
#             colors = np.clip(colors_float, 0, 255).astype(np.uint8)
#             print(f"   ✅ Saturation applied: {saturation:.2f}x")

#     app.vtk_widget.clear()

#     # Dynamic class-weighted point size
#     base_point_size = 2.0
#     classes = app.data.get("classification")

#     if not hasattr(app, "class_weights"):
#         app.class_weights = {}

#     if classes is not None:
#         weights = np.ones_like(classes, dtype=float)
#         for cls_code, w in app.class_weights.items():
#             weights[classes == cls_code] = w
#         point_sizes = np.clip(base_point_size * weights, 1.0, 8.0)
#     else:
#         point_sizes = np.ones(xyz.shape[0], dtype=float) * base_point_size

#     app.data["point_size"] = point_sizes
#     print(f"📏 Point sizes: min={point_sizes.min():.1f}, max={point_sizes.max():.1f}")

#     # Replace the section in pointcloud_display.py starting from "border_pct = getattr(app..."
# # with this corrected version:

#     border_pct = getattr(app, "point_border_percent", 0)
#     halo_add = min(1 + int(border_pct / 4), 5)

#     colors_u8 = colors.astype(np.uint8)

#     # Draw border FIRST (underneath) if enabled
#     if border_pct > 0:
#         border_cloud = pv.PolyData(xyz)
#         border_cloud["RGB"] = np.full_like(colors_u8, 255, dtype=np.uint8)
#         app.vtk_widget.add_points(
#             border_cloud,
#             scalars="RGB",
#             rgb=True,
#             point_size=np.mean(point_sizes) + halo_add,
#             opacity=0.3,
#         )

#     # Draw main points SECOND (on top) - ONLY ONCE
#     cloud = pv.PolyData(xyz)
#     cloud["RGB"] = colors_u8
#     app.vtk_widget.add_points(
#         cloud,
#         scalars="RGB",
#         rgb=True,
#         point_size=np.mean(point_sizes),
#     )

#     from gui.theme_manager import ThemeManager
#     bg_color = "white" if ThemeManager.current() == "light" else "black"
#     app.vtk_widget.set_background(bg_color)
#     from gui.views import set_view
#     set_view(app, app.current_view)

#     # Cross-section
#     if hasattr(app, "sec_vtk") and app.sec_vtk is not None:
#         try:
#             app.sec_vtk.clear()
#         except AttributeError:
#             print("⚠️ sec_vtk already cleared")
#         if getattr(app, "section_points", None) is not None:
#             slice_xyz = app.section_points
#             slice_colors = compute_colors(
#                 app,
#                 mask=getattr(app.section_controller, "last_mask", None),
#                 section_points=slice_xyz
#             )
            
#             # ✅ NEW: Apply amplifiers to cross-section too
#             if mode in ["depth", "intensity"]:
#                 saturation = getattr(app, "current_saturation", 1.0)
#                 sharpness = getattr(app, "current_sharpness", 1.0)
                
#                 if sharpness != 1.0:
#                     slice_colors_norm = slice_colors.astype(np.float32) / 255.0
#                     slice_colors_norm = 0.5 + (slice_colors_norm - 0.5) * sharpness
#                     slice_colors_norm = np.clip(slice_colors_norm, 0, 1)
#                     slice_colors = (slice_colors_norm * 255).astype(np.uint8)
                
#                 if saturation != 1.0:
#                     slice_colors_float = slice_colors.astype(np.float32)
#                     gray = 0.299 * slice_colors_float[:, 0] + 0.587 * slice_colors_float[:, 1] + 0.114 * slice_colors_float[:, 2]
#                     gray = gray[:, np.newaxis]
                    
#                     if saturation < 1.0:
#                         slice_colors_float = gray + (slice_colors_float - gray) * saturation
#                     else:
#                         slice_colors_float = gray + (slice_colors_float - gray) * saturation
                    
#                     slice_colors = np.clip(slice_colors_float, 0, 255).astype(np.uint8)
            
#             slice_cloud = pv.PolyData(slice_xyz)
#             slice_cloud["RGB"] = slice_colors
#             app.sec_vtk.add_points(slice_cloud, scalars="RGB", rgb=True, point_size=2)
#             app.sec_vtk.set_background(bg_color)

#     # Restore camera
#     try:
#         if hasattr(app, "_saved_camera_state") and app._saved_camera_state:
#             s = app._saved_camera_state
#             cam = app.vtk_widget.renderer.GetActiveCamera()
#             cam.SetPosition(s["pos"])
#             cam.SetFocalPoint(s["fp"])
#             cam.SetViewUp(s["vu"])
#             cam.SetParallelProjection(s["parallel"])
#             cam.SetParallelScale(s["scale"])
#             print("✅ Camera restored")
#     except Exception as e:
#         print(f"⚠️ Camera restore failed: {e}")

#     # ── FIX: Re-add SNT actors (clear() removed them) with Z offset ──
#     _restore_snt_after_clear(app)

#     # ── FIX: Expand clipping range to include SNT overlay actors ──────────
#     # The overlay renderer (Layer 1) shares the same camera. After the main
#     # renderer sets the clipping range from point cloud bounds, we expand it
#     # to also include SNT actor bounds so grids are never clipped.
#     _sync_overlay_clipping_range(app)

# def force_interactor_ready(app, delay_ms=200):
#         """Fully re-initialize VTK interactor."""
#         try:
#             def _activate():
#                 try:
#                     plotter = getattr(app.vtk_widget, "plotter", None)
#                     if plotter is None:
#                         return
#                     iren = getattr(plotter, "iren", None)
#                     if iren is None:
#                         return

#                     if hasattr(iren, "Initialize"):
#                         iren.Initialize()
#                     if hasattr(iren, "Start"):
#                         iren.Start()

#                     if hasattr(app.vtk_widget, "setFocus"):
#                         app.vtk_widget.setFocus()
#                     if hasattr(app.vtk_widget, "activateWindow"):
#                         app.vtk_widget.activateWindow()

#                     camera = plotter.renderer.GetActiveCamera()
#                     current_style = iren.GetInteractorStyle()
#                     current_style_name = (
#                         current_style.GetClassName() if current_style is not None else "None"
#                     )

#                     if getattr(app, "is_3d_mode", False):
#                         if current_style_name != "vtkInteractorStyleTrackballCamera":
#                             if hasattr(plotter, "enable_trackball_style"):
#                                 plotter.enable_trackball_style()
#                             else:
#                                 plotter.enable_trackball_camera()
#                         if camera is not None:
#                             camera.ParallelProjectionOff()
#                     elif hasattr(app, "ensure_main_view_2d_interaction"):
#                         app.ensure_main_view_2d_interaction(
#                             preserve_camera=True,
#                             reason="force_interactor_ready",
#                         )
#                     else:
#                         from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage

#                         style_2d = vtkInteractorStyleImage()
#                         try:
#                             style_2d.SetInteractionModeToImageSlicing()
#                         except Exception:
#                             pass
#                         iren.SetInteractorStyle(style_2d)
#                         if camera is not None:
#                             camera.ParallelProjectionOn()

#                     plotter.render()
#                     print("🟢 Interactor ready")
#                 except Exception as e:
#                     print(f"⚠️ _activate() failed: {e}")

#             QTimer.singleShot(delay_ms, _activate)
#         except Exception as e:
#             print(f"⚠️ force_interactor_ready() failed: {e}")


# def fast_update_colors(app, changed_mask=None):
#     """
#     ✅ TRUE PARTIAL UPDATE: Routes directly to unified_actor_manager zero-copy functions.
#     """
#     from gui.unified_actor_manager import fast_palette_refresh, fast_undo_update
    
#     if changed_mask is None:
#         return fast_palette_refresh(app, border_percent=getattr(app, "point_border_percent", 0.0))
#     else:
#         return fast_undo_update(app, changed_mask, border_percent=getattr(app, "point_border_percent", 0.0))


# def fast_update_main_view(app):
#     """Fast refresh for main view."""
#     try:
#         print("⚡ fast_update_main_view()")
#         fast_update_colors(app, None)
#     except Exception as e:
#         print(f"⚠️ fast_update_main_view() failed: {e}")

#     # ── FIX: Ensure SNT stays above point cloud after refresh ──
#     _restore_snt_after_clear(app)


import numpy as np
import pyvista as pv
from scipy.spatial import Delaunay
from .views import set_view
from PySide6.QtCore import QObject, QThread, Signal, QTimer
import vtk


# ─────────────────────────────────────────────────────────────
# SNT RESTORE HELPER
# ─────────────────────────────────────────────────────────────
def _restore_snt_after_clear(app):
    """
    Re-add SNT actors to the renderer after clear() and apply Z offset
    so SNT always renders on top of the current point cloud.
    """
    if hasattr(app, 'snt_dialog') and app.snt_dialog is not None:
        try:
            app.snt_dialog.restore_snt_actors()
        except Exception as e:
            print(f"  ⚠️ SNT restore via dialog: {e}")
        return

    from gui.snt_attachment import _get_snt_z_offset, _apply_z_offset_to_actor

    try:
        renderer = app.vtk_widget.renderer
    except Exception:
        return

    z_offset = _get_snt_z_offset(app)
    restored = 0

    for store_name in ['snt_actors', 'dxf_actors']:
        for entry in getattr(app, store_name, []):
            for actor in entry.get("actors", []):
                try:
                    is_overlay = getattr(actor, '_is_dxf_actor', False)
                    if is_overlay and z_offset > 0:
                        _apply_z_offset_to_actor(actor, z_offset)
                    renderer.AddActor(actor)
                    restored += 1
                except Exception:
                    pass

    if restored > 0:
        renderer.ResetCameraClippingRange()
        print(f"  🔄 Fallback SNT restore: {restored} actors (z_offset={z_offset:.1f})")
        try:
            app.vtk_widget.GetRenderWindow().Render()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
# OVERLAY CLIPPING RANGE SYNC (was missing → caused NameError)
# ─────────────────────────────────────────────────────────────
def _sync_overlay_clipping_range(app):
    """
    Expand the main camera clipping range to include SNT/DXF overlay
    actors so they are never clipped out of view.
    
    This fixes the NameError that occurred when depth mode called
    this function which didn't exist in the module.
    """
    try:
        renderer = app.vtk_widget.renderer
        if renderer is None:
            return

        camera = renderer.GetActiveCamera()
        if camera is None:
            return

        # Get current clipping range from point cloud
        near, far = camera.GetClippingRange()

        # Check all SNT/DXF actors for extended bounds
        expanded = False
        for store_name in ['snt_actors', 'dxf_actors']:
            for entry in getattr(app, store_name, []):
                for actor in entry.get("actors", []):
                    try:
                        if actor.GetVisibility():
                            bounds = actor.GetBounds()
                            if bounds and bounds[0] != 1.0 and bounds[1] != -1.0:
                                # Actor has valid bounds - renderer should include it
                                expanded = True
                    except Exception:
                        pass

        if expanded:
            # Let VTK recalculate to include all actors
            renderer.ResetCameraClippingRange()
            new_near, new_far = camera.GetClippingRange()
            
            # Ensure we don't clip too aggressively - add margin
            margin = (new_far - new_near) * 0.1
            camera.SetClippingRange(
                max(new_near - margin, 0.01),
                new_far + margin
            )
    except Exception as e:
        print(f"  ⚠️ _sync_overlay_clipping_range: {e}")


# ─────────────────────────────────────────────────────────────
# PYVISTA ORPHAN ACTOR CLEANUP
# ─────────────────────────────────────────────────────────────
def _remove_pyvista_point_actors(app):
    """
    Remove any pyvista-added point cloud actors from the renderer.
    
    When depth/intensity/elevation/rgb modes use app.vtk_widget.add_points(),
    they create actors that are NOT managed by the unified_actor_manager.
    These 'orphan' actors must be explicitly removed before switching to
    class or shading modes, otherwise they bleed through.
    
    We identify them by checking for the '_naksha_pyvista_points' flag
    we set when adding them, or by checking they are NOT the unified actor
    and NOT SNT/DXF actors.
    """
    try:
        renderer = app.vtk_widget.renderer
        if renderer is None:
            return

        actors_to_remove = []
        actor_collection = renderer.GetActors()
        actor_collection.InitTraversal()

        # Get the unified actor name so we don't remove it
        unified_actor = getattr(app, '_unified_cloud_actor', None)

        for i in range(actor_collection.GetNumberOfItems()):
            actor = actor_collection.GetNextActor()
            if actor is None:
                continue

            # Skip unified actor managed by unified_actor_manager
            if unified_actor is not None and actor is unified_actor:
                continue

            # Skip SNT/DXF overlay actors
            if getattr(actor, '_is_dxf_actor', False):
                continue
            if getattr(actor, '_is_snt_actor', False):
                continue

            # Skip shading mesh actors
            if getattr(actor, '_is_shading_mesh', False):
                continue

            # Skip any actor with a custom preservation flag
            if getattr(actor, '_naksha_preserve', False):
                continue

            # Check if this is a pyvista-added point cloud actor
            if getattr(actor, '_naksha_pyvista_points', False):
                actors_to_remove.append(actor)
                continue

            # Also check by mapper type - pyvista adds actors with PolyDataMapper
            # that have RGB scalars but are not the unified actor
            mapper = actor.GetMapper()
            if mapper is not None:
                input_data = mapper.GetInput()
                if input_data is not None:
                    # Check if it's a point cloud (has points but no cells or only vertex cells)
                    n_points = input_data.GetNumberOfPoints()
                    n_cells = input_data.GetNumberOfCells()
                    if n_points > 1000 and (n_cells == 0 or n_cells == n_points):
                        # Large point cloud not managed by unified actor - likely orphan
                        if hasattr(input_data, 'GetPointData'):
                            pd = input_data.GetPointData()
                            if pd and pd.GetArray("RGB"):
                                actors_to_remove.append(actor)
                                continue

        for actor in actors_to_remove:
            renderer.RemoveActor(actor)

        if actors_to_remove:
            print(f"  🧹 Removed {len(actors_to_remove)} orphan pyvista point actors")

    except Exception as e:
        print(f"  ⚠️ _remove_pyvista_point_actors: {e}")


def _tag_pyvista_actor(app, tag="_naksha_pyvista_points"):
    """
    Tag the most recently added actor with a flag so we can find and
    remove it later. Call this right after app.vtk_widget.add_points().
    """
    try:
        renderer = app.vtk_widget.renderer
        if renderer is None:
            return

        # The last added actor is typically the last in the collection
        actor_collection = renderer.GetActors()
        actor_collection.InitTraversal()
        last_actor = None
        for i in range(actor_collection.GetNumberOfItems()):
            a = actor_collection.GetNextActor()
            if a is not None:
                last_actor = a

        if last_actor is not None:
            setattr(last_actor, tag, True)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# WORKER
# ─────────────────────────────────────────────────────────────
class ColorUpdateWorker(QObject):
    finished = Signal(object)

    def __init__(self, app, mask=None):
        super().__init__()
        self.app = app
        self.mask = mask

    def run(self):
        try:
            colors = compute_colors(self.app, mask=self.mask)
            self.finished.emit(colors)
        except Exception as e:
            print(f"⚠️ Worker color computation failed: {e}")
            self.finished.emit(None)


# ─────────────────────────────────────────────────────────────
# COLOR COMPUTATION
# ─────────────────────────────────────────────────────────────
def compute_colors(app, mask=None, section_points=None):
    """Compute per-point colors for non-shaded modes."""
    mode = app.display_mode
    xyz = app.data["xyz"]

    if mask is None:
        mask = np.ones(xyz.shape[0], dtype=bool)

    pts = xyz[mask]
    colors = np.full((pts.shape[0], 3), 200, dtype=np.uint8)

    # --- RGB ---
    if mode == "rgb" and app.data.get("rgb") is not None:
        rgb = app.data["rgb"][mask]
        if rgb.max() <= 1.0:
            rgb = (rgb * 255).astype(np.uint8)
        colors = rgb

    # --- Intensity ---
    elif mode == "intensity" and app.data.get("intensity") is not None:
        intens = app.data["intensity"][mask].astype(float)
        norm = (intens - intens.min()) / (intens.max() - intens.min() + 1e-6)
        gray = (norm * 255).astype(np.uint8)
        colors = np.stack([gray, gray, gray], axis=1)

    # --- Elevation ---
    elif mode == "elevation":
        if section_points is not None:
            if section_points.shape[1] >= 3:
                z = section_points[:, 2]
            else:
                z = section_points[:, 1]
        else:
            z = pts[:, 2]
        norm = (z - z.min()) / (z.max() - z.min() + 1e-6)
        colors = np.c_[norm * 255, norm * 255, (1 - norm) * 255].astype(np.uint8)

    # --- Depth ---
    elif mode == "depth":
        """Grayscale depth map based on Z or section plane distance."""
        print("🧱 Computing depth colors...")

        xyz_full = app.data.get("xyz")
        if xyz_full is None or len(xyz_full) == 0:
            print("⚠️ No XYZ data for depth")
            return colors

        if hasattr(app, "section_origin") and hasattr(app, "section_normal") \
           and app.section_origin is not None and app.section_normal is not None:
            origin = np.asarray(app.section_origin, dtype=np.float64)
            normal = np.asarray(app.section_normal, dtype=np.float64)
            normal /= np.linalg.norm(normal) + 1e-9
            distances = np.dot(xyz_full - origin, normal)
            print("📏 Depth: using section plane distances")
        else:
            z = xyz_full[:, 2]
            distances = z - np.min(z)
            print("📏 Depth: using Z elevation")

        dmin, dmax = np.percentile(distances, [1, 99])
        depth_norm = np.clip((distances - dmin) / (dmax - dmin + 1e-9), 0, 1)
        depth_norm = depth_norm ** 0.6

        if mask is not None and mask.size == depth_norm.size:
            depth_norm = depth_norm[mask]

        gray = (depth_norm * 255).astype(np.uint8)
        colors = np.stack([gray, gray, gray], axis=1)

    # --- Classification ---
    elif mode in ("class", "shaded_class") and app.data.get("classification") is not None:
        classes = app.data["classification"][mask]
        colors = np.zeros((pts.shape[0], 3), dtype=np.uint8)

        if not hasattr(app, "class_palette") or not app.class_palette:
            unique_classes = np.unique(classes)
            app.class_palette = {
                int(code): {"color": (160, 160, 160), "show": True}
                for code in unique_classes
            }

        for code in np.unique(classes):
            local_mask = classes == code
            entry = app.class_palette.get(
                int(code), {"color": (128, 128, 128), "show": True}
            )
            if entry["show"]:
                colors[local_mask] = entry["color"]
            else:
                colors[local_mask] = [0, 0, 0]

        weight = getattr(app, "class_weight", 1.0)
        colors = np.clip(colors * weight, 0, 255).astype(np.uint8)

    return colors


class ShadedMeshWorker(QThread):
    """Worker thread to build shaded mesh asynchronously."""
    finished = Signal(object)

    def __init__(self, app):
        super().__init__()
        self.app = app

    def run(self):
        try:
            xyz = self.app.data["xyz"]
            classes = self.app.data["classification"]
            tri = Delaunay(xyz[:, :2])
            F = tri.simplices
            v1, v2, v3 = xyz[F[:, 0]], xyz[F[:, 1]], xyz[F[:, 2]]
            fn = np.cross(v2 - v1, v3 - v1)
            fn /= np.linalg.norm(fn, axis=1, keepdims=True) + 1e-9

            az = np.deg2rad(getattr(self.app, "last_shade_azimuth", 45.0))
            el = np.deg2rad(getattr(self.app, "last_shade_angle", 45.0))
            Ld = np.array([np.cos(el) * np.cos(az),
                           np.cos(el) * np.sin(az),
                           np.sin(el)])
            Ld /= np.linalg.norm(Ld)
            shade = getattr(self.app, "shade_ambient", 0.2) + \
                    (1 - getattr(self.app, "shade_ambient", 0.2)) * np.clip(fn @ Ld, 0, 1)

            colors = np.zeros((F.shape[0], 3), dtype=np.uint8)
            for i, face in enumerate(F):
                c = classes[face]
                majority = np.bincount(c).argmax()
                entry = self.app.class_palette.get(int(majority), {"color": (128, 128, 128)})
                base = np.array(entry["color"], dtype=np.float32)
                colors[i] = np.clip(base * shade[i], 0, 255)

            faces = np.hstack([np.full((F.shape[0], 1), 3), F]).astype(np.int32)
            mesh = pv.PolyData(xyz, faces)
            mesh.cell_data["RGB"] = colors

            self.finished.emit(mesh)
        except Exception as e:
            print(f"⚠️ ShadedMeshWorker failed: {e}")
            self.finished.emit(None)


# ─────────────────────────────────────────────────────────────
# MAIN UPDATE FUNCTION
# ─────────────────────────────────────────────────────────────
def update_pointcloud(app, mode="rgb"):
    """
    Single unified point cloud update function.
    ✅ Handles all display modes with proper validation
    ✅ Supports saturation and sharpness amplifiers for depth/intensity modes
    ✅ FIX: Properly cleans up orphan actors when switching between modes
    ✅ FIX: _sync_overlay_clipping_range is now defined in this module
    """
    import numpy as np
    import pyvista as pv

    if app.data is None or "xyz" not in app.data:
        print("⚠️ No point cloud data loaded")
        return

    xyz = app.data["xyz"]

    if len(xyz) == 0:
        print("⚠️ Empty point cloud")
        app.vtk_widget.clear()
        app.vtk_widget.render()
        return

    # ─────────────────────────────────────────────────────────
    # SHADED CLASS MODE
    # ─────────────────────────────────────────────────────────
    if mode == "shaded_class":
        from gui.shading_display import update_shaded_class, clear_shading_cache

        classes = app.data.get("classification")
        if classes is None:
            print("⚠️ No classification found, falling back to class view")
            return update_pointcloud(app, "class")

        # ✅ FIX: Remove orphan pyvista actors BEFORE shading
        # This prevents depth/intensity point actors from bleeding through
        _remove_pyvista_point_actors(app)

        app.display_mode = "shaded_class"
        clear_shading_cache("mode switch from menu")
        update_shaded_class(
            app,
            getattr(app, "last_shade_azimuth", 45.0),
            getattr(app, "last_shade_angle", 45.0),
            getattr(app, "shade_ambient", 0.2),
            force_rebuild=True
        )
        _restore_snt_after_clear(app)
        return

    # ─────────────────────────────────────────────────────────
    # CLASS MODE (uses unified actor manager)
    # ─────────────────────────────────────────────────────────
    if mode == "class":
        # ✅ FIX: Remove orphan pyvista actors BEFORE switching to class
        # This prevents depth/intensity actors from persisting over the
        # unified actor that class mode uses
        _remove_pyvista_point_actors(app)

        from gui.class_display import update_class_mode
        update_class_mode(app, force_refresh=True)
        _restore_snt_after_clear(app)
        return

    # ─────────────────────────────────────────────────────────
    # PYVISTA-BASED MODES: RGB / INTENSITY / ELEVATION / DEPTH
    # ─────────────────────────────────────────────────────────
    colors = compute_colors(app)

    # ✅ CRITICAL VALIDATION
    if len(colors) == 0:
        print("⚠️ Empty colors array from compute_colors()")
        app.vtk_widget.clear()
        app.vtk_widget.render()
        return

    if len(xyz) != len(colors):
        print(f"⚠️ Length mismatch: xyz={len(xyz)}, colors={len(colors)}")
        min_len = min(len(xyz), len(colors))
        xyz = xyz[:min_len]
        colors = colors[:min_len]
        print(f"   Truncated to {min_len:,} points")

    # ✅ Apply frequency amplifiers for depth and intensity modes
    if mode in ["depth", "intensity"]:
        saturation = getattr(app, "current_saturation", 1.0)
        sharpness = getattr(app, "current_sharpness", 1.0)

        print(f"🎚️ Applying amplifiers: saturation={saturation:.2f}x, sharpness={sharpness:.2f}x")

        if sharpness != 1.0:
            colors_norm = colors.astype(np.float32) / 255.0
            colors_norm = 0.5 + (colors_norm - 0.5) * sharpness
            colors_norm = np.clip(colors_norm, 0, 1)
            colors = (colors_norm * 255).astype(np.uint8)
            print(f"   ✅ Sharpness applied: {sharpness:.2f}x")

        if saturation != 1.0:
            colors_float = colors.astype(np.float32)
            gray = 0.299 * colors_float[:, 0] + 0.587 * colors_float[:, 1] + 0.114 * colors_float[:, 2]
            gray = gray[:, np.newaxis]
            colors_float = gray + (colors_float - gray) * saturation
            colors = np.clip(colors_float, 0, 255).astype(np.uint8)
            print(f"   ✅ Saturation applied: {saturation:.2f}x")

    # ✅ FIX: Remove the unified actor if it exists, so it doesn't
    # render underneath the pyvista-added actors
    try:
        unified_actor = getattr(app, '_unified_cloud_actor', None)
        if unified_actor is not None:
            renderer = app.vtk_widget.renderer
            if renderer is not None:
                renderer.RemoveActor(unified_actor)
                print("  🧹 Removed unified actor before pyvista mode")
    except Exception:
        pass

    # ✅ FIX: Also remove any shading mesh actors
    try:
        renderer = app.vtk_widget.renderer
        if renderer is not None:
            actors_to_remove = []
            actor_collection = renderer.GetActors()
            actor_collection.InitTraversal()
            for i in range(actor_collection.GetNumberOfItems()):
                actor = actor_collection.GetNextActor()
                if actor is not None and getattr(actor, '_is_shading_mesh', False):
                    actors_to_remove.append(actor)
            for actor in actors_to_remove:
                renderer.RemoveActor(actor)
            if actors_to_remove:
                print(f"  🧹 Removed {len(actors_to_remove)} shading mesh actors")
    except Exception:
        pass

    app.vtk_widget.clear()

    # Dynamic class-weighted point size
    base_point_size = 2.0
    classes = app.data.get("classification")

    if not hasattr(app, "class_weights"):
        app.class_weights = {}

    if classes is not None:
        weights = np.ones_like(classes, dtype=float)
        for cls_code, w in app.class_weights.items():
            weights[classes == cls_code] = w
        point_sizes = np.clip(base_point_size * weights, 1.0, 8.0)
    else:
        point_sizes = np.ones(xyz.shape[0], dtype=float) * base_point_size

    app.data["point_size"] = point_sizes
    print(f"📏 Point sizes: min={point_sizes.min():.1f}, max={point_sizes.max():.1f}")

    border_pct = getattr(app, "point_border_percent", 0)
    halo_add = min(1 + int(border_pct / 4), 5)

    colors_u8 = colors.astype(np.uint8)

    # Draw border FIRST (underneath) if enabled
    if border_pct > 0:
        border_cloud = pv.PolyData(xyz)
        border_cloud["RGB"] = np.full_like(colors_u8, 255, dtype=np.uint8)
        app.vtk_widget.add_points(
            border_cloud,
            scalars="RGB",
            rgb=True,
            point_size=np.mean(point_sizes) + halo_add,
            opacity=0.3,
        )
        _tag_pyvista_actor(app)  # ✅ Tag for cleanup

    # Draw main points SECOND (on top) - ONLY ONCE
    cloud = pv.PolyData(xyz)
    cloud["RGB"] = colors_u8
    app.vtk_widget.add_points(
        cloud,
        scalars="RGB",
        rgb=True,
        point_size=np.mean(point_sizes),
    )
    _tag_pyvista_actor(app)  # ✅ Tag for cleanup

    from gui.theme_manager import ThemeManager
    bg_color = "white" if ThemeManager.current() == "light" else "black"
    app.vtk_widget.set_background(bg_color)
    from gui.views import set_view
    set_view(app, app.current_view)

    # Cross-section
    if hasattr(app, "sec_vtk") and app.sec_vtk is not None:
        try:
            app.sec_vtk.clear()
        except AttributeError:
            print("⚠️ sec_vtk already cleared")
        if getattr(app, "section_points", None) is not None:
            slice_xyz = app.section_points
            slice_colors = compute_colors(
                app,
                mask=getattr(app.section_controller, "last_mask", None),
                section_points=slice_xyz
            )

            if mode in ["depth", "intensity"]:
                saturation = getattr(app, "current_saturation", 1.0)
                sharpness = getattr(app, "current_sharpness", 1.0)

                if sharpness != 1.0:
                    slice_colors_norm = slice_colors.astype(np.float32) / 255.0
                    slice_colors_norm = 0.5 + (slice_colors_norm - 0.5) * sharpness
                    slice_colors_norm = np.clip(slice_colors_norm, 0, 1)
                    slice_colors = (slice_colors_norm * 255).astype(np.uint8)

                if saturation != 1.0:
                    slice_colors_float = slice_colors.astype(np.float32)
                    gray = 0.299 * slice_colors_float[:, 0] + 0.587 * slice_colors_float[:, 1] + 0.114 * slice_colors_float[:, 2]
                    gray = gray[:, np.newaxis]
                    slice_colors_float = gray + (slice_colors_float - gray) * saturation
                    slice_colors = np.clip(slice_colors_float, 0, 255).astype(np.uint8)

            slice_cloud = pv.PolyData(slice_xyz)
            slice_cloud["RGB"] = slice_colors
            app.sec_vtk.add_points(slice_cloud, scalars="RGB", rgb=True, point_size=2)
            app.sec_vtk.set_background(bg_color)

    # Restore camera
    try:
        if hasattr(app, "_saved_camera_state") and app._saved_camera_state:
            s = app._saved_camera_state
            cam = app.vtk_widget.renderer.GetActiveCamera()
            cam.SetPosition(s["pos"])
            cam.SetFocalPoint(s["fp"])
            cam.SetViewUp(s["vu"])
            cam.SetParallelProjection(s["parallel"])
            cam.SetParallelScale(s["scale"])
            print("✅ Camera restored")
    except Exception as e:
        print(f"⚠️ Camera restore failed: {e}")

    # Re-add SNT actors with Z offset
    _restore_snt_after_clear(app)

    # Expand clipping range to include SNT overlay actors
    _sync_overlay_clipping_range(app)


def force_interactor_ready(app, delay_ms=200):
    """Fully re-initialize VTK interactor."""
    try:
        def _activate():
            try:
                plotter = getattr(app.vtk_widget, "plotter", None)
                if plotter is None:
                    return
                iren = getattr(plotter, "iren", None)
                if iren is None:
                    return

                if hasattr(iren, "Initialize"):
                    iren.Initialize()
                if hasattr(iren, "Start"):
                    iren.Start()

                if hasattr(app.vtk_widget, "setFocus"):
                    app.vtk_widget.setFocus()
                if hasattr(app.vtk_widget, "activateWindow"):
                    app.vtk_widget.activateWindow()

                camera = plotter.renderer.GetActiveCamera()
                current_style = iren.GetInteractorStyle()
                current_style_name = (
                    current_style.GetClassName() if current_style is not None else "None"
                )

                if getattr(app, "is_3d_mode", False):
                    if current_style_name != "vtkInteractorStyleTrackballCamera":
                        if hasattr(plotter, "enable_trackball_style"):
                            plotter.enable_trackball_style()
                        else:
                            plotter.enable_trackball_camera()
                    if camera is not None:
                        camera.ParallelProjectionOff()
                elif hasattr(app, "ensure_main_view_2d_interaction"):
                    app.ensure_main_view_2d_interaction(
                        preserve_camera=True,
                        reason="force_interactor_ready",
                    )
                else:
                    from vtkmodules.vtkInteractionStyle import vtkInteractorStyleImage

                    style_2d = vtkInteractorStyleImage()
                    try:
                        style_2d.SetInteractionModeToImageSlicing()
                    except Exception:
                        pass
                    iren.SetInteractorStyle(style_2d)
                    if camera is not None:
                        camera.ParallelProjectionOn()

                plotter.render()
                print("🟢 Interactor ready")
            except Exception as e:
                print(f"⚠️ _activate() failed: {e}")

        QTimer.singleShot(delay_ms, _activate)
    except Exception as e:
        print(f"⚠️ force_interactor_ready() failed: {e}")


def fast_update_colors(app, changed_mask=None):
    """
    ✅ TRUE PARTIAL UPDATE: Routes directly to unified_actor_manager zero-copy functions.
    """
    from gui.unified_actor_manager import fast_palette_refresh, fast_undo_update

    if changed_mask is None:
        return fast_palette_refresh(app, border_percent=getattr(app, "point_border_percent", 0.0))
    else:
        return fast_undo_update(app, changed_mask, border_percent=getattr(app, "point_border_percent", 0.0))


def fast_update_main_view(app):
    """Fast refresh for main view."""
    try:
        print("⚡ fast_update_main_view()")
        fast_update_colors(app, None)
    except Exception as e:
        print(f"⚠️ fast_update_main_view() failed: {e}")

    _restore_snt_after_clear(app)