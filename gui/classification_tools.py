
import numpy as np
from matplotlib.path import Path
from vtkmodules.util import numpy_support

def sync_main_view_instant(app, global_mask, new_class):
    """🚀 Direct GPU Pointer Update - Millisecond Speed"""
    from gui.unified_actor_manager import fast_classify_update
    border_percent = float(getattr(app, "point_border_percent", 0.0))
    fast_classify_update(app, global_mask, new_class, border_percent=border_percent)

def update_main_view_scalars_direct(app, changed_indices):
    """🚀 Millisecond Refresh: Injects new colors directly into GPU buffer."""
    from gui.unified_actor_manager import fast_classify_update
    # Generate full mask
    if hasattr(app, "data") and "classification" in app.data:
        mask = np.zeros(len(app.data["classification"]), dtype=bool)
        mask[changed_indices] = True
        border_percent = float(getattr(app, "point_border_percent", 0.0))
        # Wait, this function doesn't know to_class. It's meant for undo/redo.
        from gui.unified_actor_manager import fast_undo_update
        fast_undo_update(app, mask, border_percent=border_percent)

def _get_display_mode_settings(app):
    """
    Get current Display Mode visibility settings.
    ✅ ALWAYS reads from dialog if it's visible, ensuring fresh state.
    ✅ UNIFIED: Supports both display_mode_dialog and display_dialog attribute names.
    """
    # ✅ PRIORITY: Resolve dialog reference (supports both naming conventions)
    dialog = getattr(app, 'display_mode_dialog', None) or getattr(app, 'display_dialog', None)
    
    if dialog is not None:
        try:
            if hasattr(dialog, 'table') and dialog.table.rowCount() > 0:
                print(f"   📋 Reading Display Mode from dialog...")
                
                class_palette = {}
                checked_classes = []
                
                for row in range(dialog.table.rowCount()):
                    try:
                        code = int(dialog.table.item(row, 1).text())
                        chk = dialog.table.cellWidget(row, 0)
                        desc = dialog.table.item(row, 2).text()
                        color = dialog.table.item(row, 5).background().color().getRgb()[:3]
                        weight_item = dialog.table.item(row, 6)
                        weight = float(weight_item.text()) if weight_item else 1.0
                        
                        is_checked = chk.isChecked() if chk else False
                        
                        class_palette[code] = {
                            "show": is_checked,
                            "description": desc,
                            "color": color,
                            "weight": weight
                        }
                        
                        if is_checked:
                            checked_classes.append(code)
                    except Exception as row_err:
                        print(f"      ⚠️ Error reading row {row}: {row_err}")
                        continue
                
                if class_palette:
                    print(f"      ✅ Read {len(class_palette)} classes, {len(checked_classes)} visible")
                    
                    # ✅ Store to view_palettes if section controller available
                    if hasattr(app, 'section_controller') and hasattr(app, 'view_palettes'):
                        view_idx = getattr(app.section_controller, 'active_view', 0) or 0
                        app.view_palettes[view_idx] = class_palette

                    return class_palette
                    
        except Exception as e:
            print(f"   ⚠️ Could not read Display Mode dialog: {e}")
            import traceback
            traceback.print_exc()
    
    # Fallback: Check stored palette
    if hasattr(app, 'class_palette') and app.class_palette:
        print(f"   📋 Using stored class_palette: {len(app.class_palette)} classes")
        visible_count = sum(1 for v in app.class_palette.values() if v.get('show', False))
        print(f"      Visible: {visible_count}/{len(app.class_palette)}")
        return app.class_palette
    
    print(f"   ⚠️ No Display Mode settings found - will show all classes")
    return None

def _visible_filter(section_points, visible_bounds):
    """Return boolean mask of points inside the visible viewport."""
    if visible_bounds is None or section_points is None:
        return np.ones(section_points.shape[0], dtype=bool)
    (xlim, zlim) = visible_bounds
    # For side view, section_points[:,0]=X and [:,2]=Z
    return (
        (section_points[:, 0] >= xlim[0]) & (section_points[:, 0] <= xlim[1]) &
        (section_points[:, 2] >= zlim[0]) & (section_points[:, 2] <= zlim[1])
    )
def _get_visible_mask_from_viewport(app, section_points):
    """
    Compute a boolean mask of section_points that are visible in the current
    cross-section or cut-section viewport.
 
    For cross-section views (side/front):
        - Projects points to (u, z) using _project_to_2d_view.
        - Uses camera focal point + ParallelScale + aspect ratio
          to define the visible (u, z) window.
 
    For cut-section:
        - Uses world X/Z bounds around the camera focal point.
 
    Returns
    -------
    mask : np.ndarray of bool, shape == len(section_points)
        True for points inside the current viewport.
        If anything fails, returns None (caller should treat as "no filter").
    """
    try:
        import numpy as np
 
        if section_points is None or len(section_points) == 0:
            return None
 
        vtk_widget = None
        ren = None
        is_cut_section = False
 
        # 1) CUT SECTION?
        if hasattr(app, 'cut_section_controller'):
            ctrl = app.cut_section_controller
            if (
                getattr(app, "active_classify_target", None) == "cut"
                and getattr(ctrl, 'is_cut_view_active', False)
                and getattr(ctrl, 'cut_vtk', None) is not None
            ):
                vtk_widget = ctrl.cut_vtk
                ren = vtk_widget.renderer
                is_cut_section = True
                # print("   📍 Viewport source: CUT SECTION (cut_vtk)")
 
        # 2) Normal cross-section (SIDE / FRONT)
        if vtk_widget is None:
            active_view = getattr(app.section_controller, 'active_view', None)
            if active_view is None or active_view not in app.section_vtks:
                return None
            vtk_widget = app.section_vtks[active_view]
            ren = vtk_widget.renderer
            # print(f"   📍 Viewport source: CROSS-SECTION view {active_view}")
 
        if ren is None:
            return None
 
        cam = ren.GetActiveCamera()
        fp_world = np.array(cam.GetFocalPoint(), dtype=float)
        scale = float(cam.GetParallelScale())
 
        try:
            size = ren.GetRenderWindow().GetSize()
            aspect = size[0] / max(size[1], 1)
        except Exception:
            aspect = 1.0
 
        half_w = scale * aspect   # horizontal half-extent in view units
        half_h = scale            # vertical half-extent in view units
 
        # ----------------------------------------------------
        # CUT SECTION: world X/Z bounds
        # ----------------------------------------------------
        if is_cut_section:
            xlim = (fp_world[0] - half_w, fp_world[0] + half_w)
            zlim = (fp_world[2] - half_h, fp_world[2] + half_h)
 
            spatial_mask = (
                (section_points[:, 0] >= xlim[0]) & (section_points[:, 0] <= xlim[1]) &
                (section_points[:, 2] >= zlim[0]) & (section_points[:, 2] <= zlim[1])
            )
            # print(f"   🔍 Viewport filter (CUT): {spatial_mask.sum()}/{len(section_points)} points visible")
            return spatial_mask
 
        # ----------------------------------------------------
        # CROSS-SECTION: SIDE / FRONT
        # Use same (u, z) projection as tools
        # ----------------------------------------------------
        view_mode = getattr(app, "cross_view_mode", "side")
 
        # Project section points to (u,z)
        pts_2d = _project_to_2d_view(section_points, view_mode)  # shape: (N, 2)
 
        # Project camera focal point to (u,z) as well
        fp_2d = _project_to_2d_view(fp_world.reshape(1, 3), view_mode)[0]
 
        u_center = fp_2d[0]
        z_center = fp_2d[1]
 
        ulim = (u_center - half_w, u_center + half_w)
        zlim = (z_center - half_h, z_center + half_h)
 
        spatial_mask = (
            (pts_2d[:, 0] >= ulim[0]) & (pts_2d[:, 0] <= ulim[1]) &
            (pts_2d[:, 1] >= zlim[0]) & (pts_2d[:, 1] <= zlim[1])
        )
 
        # print(f"   🔍 Viewport filter ({view_mode}): {spatial_mask.sum()}/{len(section_points)} points visible")
        return spatial_mask
 
    except Exception as e:
        print(f"⚠️ _get_visible_mask_from_viewport() failed: {e}")
        import traceback
        traceback.print_exc()
        return None
    
def _include_buffer_for_classification(app) -> bool:
    # Default False => CORE ONLY (your requirement)
    return bool(getattr(app, "classify_include_buffer", True))

# ✅ FIX: Include BOTH core AND buffer points for classification
def _get_cut_section_or_default(app, mask, section_points):
    """
    Return section data for classification.

    ✅ UPDATED: Now includes buffer points BY DEFAULT for cross-sections
    ✅ Cut sections use their own separate logic
    """
    import numpy as np

    active_view = getattr(app.section_controller, "active_view", None)

    # ═══════════════════════════════════════════════════════════
    # CROSS-SECTION VIEW LOGIC (includes buffers)
    # ═══════════════════════════════════════════════════════════
    if active_view is not None:
        # Try pre-computed combined data first
        combined_mask = getattr(app, f"section_{active_view}_combined_mask", None)
        points_transformed = getattr(app, f"section_{active_view}_points_transformed", None)
        
        if combined_mask is not None and points_transformed is not None:
            num_points = combined_mask.sum() if hasattr(combined_mask, 'sum') else 0
            print(f"📋 Classification mask: PRE-COMPUTED combined (core + buffer)")
            print(f"   Total: {num_points:,} points (transformed)")
            return combined_mask, points_transformed
        
        # Fallback: build combined mask
        core_mask = getattr(app, f"section_{active_view}_core_mask", None)
        buffer_mask = getattr(app, f"section_{active_view}_buffer_mask", None)

        if core_mask is not None:
            include_buffer = _include_buffer_for_classification(app)

            if include_buffer and buffer_mask is not None:
                combined_mask = core_mask | buffer_mask
                core_count = core_mask.sum()
                buffer_count = (buffer_mask & ~core_mask).sum()
                print(f"📋 Classification mask: CORE + BUFFER (include_buffer=True)")
                print(f"   Core: {core_count:,}, Buffer: {buffer_count:,}")
            else:
                combined_mask = core_mask
                print(f"📋 Classification mask: CORE ONLY (include_buffer=False)")

            # Try to get transformed points
            points_transformed = getattr(app, f"section_{active_view}_points_transformed", None)
            if points_transformed is not None:
                return combined_mask, points_transformed
            
            # Fallback to raw xyz
            section_xyz = app.data["xyz"][combined_mask]
            return combined_mask, section_xyz

    # ═══════════════════════════════════════════════════════════
    # FALLBACK: Use provided mask/points
    # ═══════════════════════════════════════════════════════════
    if mask is not None and section_points is not None:
        return mask, section_points

    return None, None

def _get_section_data_with_buffer(app, mask=None, section_points=None):
    """
    Get section data for classification.

    ✅ UPDATED: Now includes buffer points BY DEFAULT
    ✅ Uses combined transformed points (core + buffer) when available
    ✅ Falls back gracefully if transformed points not available
    
    Priority order:
    1. Pre-computed combined_mask + points_transformed (BEST)
    2. Separate core + buffer masks with transformed points
    3. Fallback to raw xyz coordinates
    """
    import numpy as np

    # Handle cut section separately
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    if is_cut_section:
        return _get_cut_section_or_default(app, mask, section_points)

    # Get active view
    active_view = getattr(app.section_controller, "active_view", None)
    if active_view is None:
        return (mask, section_points) if (mask is not None and section_points is not None) else (None, None)

    # ═══════════════════════════════════════════════════════════
    # PATH 1: Try pre-computed combined mask + transformed points (BEST)
    # ═══════════════════════════════════════════════════════════
    combined_mask = getattr(app, f"section_{active_view}_combined_mask", None)
    points_transformed = getattr(app, f"section_{active_view}_points_transformed", None)
    
    if combined_mask is not None and points_transformed is not None:
        num_points = combined_mask.sum() if hasattr(combined_mask, 'sum') else 0
        print(f"📋 Using PRE-COMPUTED combined data (core + buffer)")
        print(f"   Total points: {num_points:,} (transformed)")
        return combined_mask, points_transformed

    # ═══════════════════════════════════════════════════════════
    # PATH 2: Build combined mask from core + buffer (FALLBACK)
    # ═══════════════════════════════════════════════════════════
    core_mask = getattr(app, f"section_{active_view}_core_mask", None)
    buffer_mask = getattr(app, f"section_{active_view}_buffer_mask", None)
    include_buffer = _include_buffer_for_classification(app)

    if core_mask is None:
        return (mask, section_points) if (mask is not None and section_points is not None) else (None, None)

    # ✅ Build combined mask
    if include_buffer and buffer_mask is not None:
        combined_mask = core_mask | buffer_mask
        core_count = core_mask.sum() if hasattr(core_mask, 'sum') else 0
        buffer_count = (buffer_mask & ~core_mask).sum() if hasattr(buffer_mask, 'sum') else 0
        print(f"📋 Using BUILT combined mask (core + buffer)")
        print(f"   Core: {core_count:,}, Buffer: {buffer_count:,}, Total: {core_count + buffer_count:,}")
    else:
        combined_mask = core_mask
        core_count = core_mask.sum() if hasattr(core_mask, 'sum') else 0
        print(f"📋 Using CORE ONLY (buffer excluded)")
        print(f"   Core: {core_count:,}")

    # ═══════════════════════════════════════════════════════════
    # SUB-PATH 2A: Try to get transformed points (PREFERRED)
    # ═══════════════════════════════════════════════════════════
    
    # Try pre-transformed combined points first
    points_transformed = getattr(app, f"section_{active_view}_points_transformed", None)
    if points_transformed is not None:
        print(f"   ✅ Using transformed points (pre-computed)")
        return combined_mask, points_transformed
    
    # Try building from separate core + buffer transformed points
    if include_buffer and buffer_mask is not None:
        core_pts = getattr(app, f"section_{active_view}_core_points", None)
        buffer_pts = getattr(app, f"section_{active_view}_buffer_points", None)
        
        if core_pts is not None and buffer_pts is not None:
            section_xyz = np.vstack([core_pts, buffer_pts])
            print(f"   ✅ Using transformed points (built from core + buffer)")
            return combined_mask, section_xyz
        elif core_pts is not None:
            print(f"   ⚠️ Using transformed core points only (no buffer points available)")
            return combined_mask, core_pts
    else:
        # Core only - try transformed core points
        core_pts = getattr(app, f"section_{active_view}_core_points", None)
        if core_pts is not None:
            print(f"   ✅ Using transformed core points")
            return combined_mask, core_pts

    # ═══════════════════════════════════════════════════════════
    # SUB-PATH 2B: Build from raw xyz + transform (LAST RESORT)
    # ═══════════════════════════════════════════════════════════
    section_xyz_original = app.data["xyz"][combined_mask]
    P1 = getattr(app, f"section_{active_view}_P1", None)
    P2 = getattr(app, f"section_{active_view}_P2", None)

    if P1 is not None and P2 is not None and hasattr(app, "section_controller"):
        try:
            section_xyz = app.section_controller._transform_to_section_coordinates(section_xyz_original, P1, P2)
            print(f"   ✅ Using computed transform from raw xyz")
            return combined_mask, section_xyz
        except Exception as e:
            print(f"   ⚠️ Transform failed: {e}, using raw xyz")
            return combined_mask, section_xyz_original
    else:
        print(f"   ⚠️ Using raw xyz (no transform available)")
        return combined_mask, section_xyz_original


# ✅ CHANGE: Make decorators pass cut section context
def classify_with_stats_update(classify_func):
    def wrapper(app, *args, **kwargs):
        result = classify_func(app, *args, **kwargs)
 
        if getattr(app, "_suppress_section_refresh", False):
            return result  # 🔒 NO REFRESH DURING DRAG

        # ✅ FIX: Skip redundant refresh if _apply_mask_and_record already
        # did the GPU sync (fast_classify_update + fast_cross_section_update).
        # This prevents the 170ms double-refresh that was killing performance.
        if getattr(app, "_gpu_sync_done", False):
            app._gpu_sync_done = False
            return result

        # ✅ Determine which view is actually active
        is_cut_active = (
            hasattr(app, 'cut_section_controller') and 
            getattr(app.cut_section_controller, 'is_locked', False) and
            getattr(app, "active_classify_target", None) == "cut"
        )
        
        # ✅ Refresh CUT SECTION (if that's the active view)
        if is_cut_active:
            try:
                app.cut_section_controller._refresh_cut_colors_fast()
                if hasattr(app.cut_section_controller, 'cut_vtk') and app.cut_section_controller.cut_vtk:
                    app.cut_section_controller.cut_vtk.render()
            except Exception as e:
                print(f"   ⚠️ Cut section refresh failed: {e}")
        
        # ✅ UNIFIED ACTOR PATH: Refresh cross-section views via fast GPU update
        if not is_cut_active and hasattr(app, 'section_vtks') and app.section_vtks:
            try:
                from gui.unified_actor_manager import fast_cross_section_update
                changed_mask = getattr(app, '_last_changed_mask', None)

                for view_idx, vtk_widget in app.section_vtks.items():
                    if vtk_widget is None:
                        continue
                    try:
                        fast_cross_section_update(app, view_idx, changed_mask,
                                                  skip_render=True)
                    except Exception:
                        pass
                for sw in app.section_vtks.values():
                    if sw:
                        try: sw.render()
                        except: pass

            except ImportError:
                pass

        return result
 
    return wrapper

# In your classification tool functions (e.g., classify_as_building, classify_as_ground, etc.)

# def _apply_classification(app, update_mask, from_classes, to_class):
#     """
#     Apply classification to selected points.
    
#     ✅ FIXED: Protects hidden classes from classification
#     ✅ Works in: Main View, Cross-Section Views, Cut Section View
#     ✅ SYNC: Updates GPU color buffers in milliseconds (no actor rebuild)
#     """
    
#     # ═══════════════════════════════════════════════════════════════════════
#     # STEP 1: Safety checks
#     # ═══════════════════════════════════════════════════════════════════════
#     if app.data is None or app.data.get("classification") is None:
#         print("⚠️ No classification data available")
#         return
    
#     if to_class is None:
#         print("⚠️ No target class specified")
#         return
    
#     # ═══════════════════════════════════════════════════════════════════════
#     # STEP 2: Apply cut section restriction (if locked)
#     # ═══════════════════════════════════════════════════════════════════════
#     is_cut_locked = False
#     if hasattr(app, 'cut_section_controller') and app.cut_section_controller is not None:
#         is_cut_locked = getattr(app.cut_section_controller, 'is_locked', False)
#         if is_cut_locked and app.cut_section_controller._cut_index_map is not None:
#             cut_idx = app.cut_section_controller._cut_index_map
#             # Direct intersection to avoid large mask creation
#             current_true_indices = np.where(update_mask)[0]
#             update_mask = np.zeros_like(update_mask)
#             valid_indices = np.intersect1d(current_true_indices, cut_idx, assume_unique=True)
#             update_mask[valid_indices] = True

#     # ═══════════════════════════════════════════════════════════════════════
#     # STEP 3: Filter indices
#     # ═══════════════════════════════════════════════════════════════════════
#     classes = app.data["classification"]
#     update_idx = np.where(update_mask)[0]
    
#     if update_idx.size == 0:
#         return

#     # ═══════════════════════════════════════════════════════════════════════
#     # STEP 4: Visibility protection
#     # ═══════════════════════════════════════════════════════════════════════
#     from .classification_tools import _get_visible_classes_for_current_view
#     visible_classes = _get_visible_classes_for_current_view(app)
    
#     if visible_classes is not None:
#         visible_mask = np.isin(classes[update_idx], visible_classes)
#         update_idx = update_idx[visible_mask]
#         if update_idx.size == 0: return

#     # ═══════════════════════════════════════════════════════════════════════
#     # STEP 5: from_classes filter
#     # ═══════════════════════════════════════════════════════════════════════
#     if from_classes:
#         class_mask = np.isin(classes[update_idx], from_classes)
#         update_idx = update_idx[class_mask]
#         if update_idx.size == 0: return

#     # ═══════════════════════════════════════════════════════════════════════
#     # STEP 6 & 7: Apply & Store for Undo
#     # ═══════════════════════════════════════════════════════════════════════
#     old_classes = classes[update_idx].copy()
    
#     # Generate final boolean mask for undo and fast_classify_update
#     final_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
#     final_mask[update_idx] = True

#     new_classes = np.full(old_classes.shape, to_class, dtype=classes.dtype)
#     app.undo_stack.append({
#         "mask": final_mask,
#         "old_classes": old_classes,
#         "new_classes": new_classes
#     })
#     app.redo_stack.clear()

#     classes[update_idx] = to_class
    
#     # ═══════════════════════════════════════════════════════════════════════
#     # STEP 11: 🚀 MILLISECOND SYNC (GPU SCALAR UPDATE)
#     # ═══════════════════════════════════════════════════════════════════════
    
#     try:
#         from gui.unified_actor_manager import fast_classify_update
#         border_percent = float(getattr(app, "point_border_percent", 0.0))
#         fast_classify_update(app, final_mask, to_class, border_percent=border_percent)
        
#         # 2. Update Cut Section View (if active)
#         if is_cut_locked and hasattr(app, 'cut_section_controller'):
#             ctrl = app.cut_section_controller
#             if ctrl.is_cut_view_active and hasattr(ctrl, 'cut_mesh'):
#                 # Map global update_idx to local cut_mesh indices
#                 local_indices = np.searchsorted(ctrl._cut_index_map, update_idx)
#                 valid = ctrl._cut_index_map[local_indices] == update_idx
#                 local_indices = local_indices[valid]
                
#                 if local_indices.size > 0:
#                     cut_colors = ctrl.cut_mesh.point_data.get('colors')
#                     if cut_colors is not None:
#                         new_color_rgb = app.class_palette.get(to_class, {}).get('color', (128, 128, 128))
#                         cut_colors[local_indices] = new_color_rgb
#                         ctrl.cut_vtk.render()
        
#     except Exception as e:
#         print(f"⚠️ Fast sync failed, falling back to slow refresh: {e}")
#         if is_cut_locked and hasattr(app.cut_section_controller, '_refresh_cut_colors_fast'):
#             app.cut_section_controller._refresh_cut_colors_fast()

#     # ═══════════════════════════════════════════════════════════════════════
#     # STEP 9: Undo Logic
#     # ═══════════════════════════════════════════════════════════════════════
#     if not hasattr(app, "undo_stack"): app.undo_stack = []
    
#     app.undo_stack.append({
#         "mask": final_mask,
#         "old_classes": old_classes,
#         "new_classes": np.full(len(update_idx), to_class, dtype=old_classes.dtype),
#         "is_cut_locked": is_cut_locked
#     })
    
#     app._last_changed_mask = final_mask
#     print(f"✅ Fast-Classified {len(update_idx)} points")

#     # ═══════════════════════════════════════════════════════════════════════
#     # FIX 1: Reactive Signal Injection — force GPU LUT reload for active slot
#     # ═══════════════════════════════════════════════════════════════════════
#     try:
#         # Determine the active classification slot
#         is_cut = (getattr(app, "active_classify_target", None) == "cut")
#         if is_cut:
#             active_slot = 5
#         elif hasattr(app, 'section_controller'):
#             av = getattr(app.section_controller, 'active_view', None)
#             active_slot = (av + 1) if av is not None and 0 <= av <= 3 else 0
#         else:
#             active_slot = 0

#         # Emit palette_changed to poke GPU uniforms
#         if hasattr(app, 'display_mode_dialog') and app.display_mode_dialog:
#             if hasattr(app.display_mode_dialog, 'palette_changed'):
#                 app.display_mode_dialog.palette_changed.emit(active_slot)
#                 print(f"   ⚡ palette_changed.emit({active_slot}) — GPU LUT refreshed")
#         # Also emit classification_finished for global view sync
#         if hasattr(app, 'classification_finished'):
#             app.classification_finished.emit(final_mask)
#     except Exception as e:
#         print(f"   ⚠️ Reactive signal injection failed: {e}")
#     # ═══════════════════════════════════════════════════════════════════════
#     # ✅ SYNC: Update view_palettes with new class color
#     # ═══════════════════════════════════════════════════════════════════════
#     if hasattr(app, 'class_palette') and hasattr(app, 'view_palettes'):
#         to_class_info = app.class_palette.get(to_class, {})
#         new_color = to_class_info.get("color", (128, 128, 128))
        
#         # Update ALL view_palettes with the new color
#         for view_idx in app.view_palettes.keys():
#             if to_class in app.view_palettes[view_idx]:
#                 app.view_palettes[view_idx][to_class]["color"] = new_color
        
#         print(f"   🔄 Synced Class {to_class} color to all view_palettes: {new_color}")
#          # ═══════════════════════════════════════════════════════════════════════
#         print(f"\n{'='*60}")
#         print(f"🔍 DEBUG: Checking app.class_palette after classification")
#         print(f"{'='*60}")
#         if hasattr(app, 'class_palette'):
#             print(f"Total classes in palette: {len(app.class_palette)}")
#             for code in sorted(app.class_palette.keys())[:5]:  # Show first 5
#                 info = app.class_palette[code]
#                 color = info.get("color", "NO COLOR")
#                 show = info.get("show", False)
#                 print(f"   Class {code}: color={color}, show={show}")
#         else:
#             print("   ⚠️ app.class_palette DOES NOT EXIST!")
#         print(f"{'='*60}\n")


def _apply_classification(app, update_mask, from_classes, to_class):
    """
    🚀 PRODUCTION-GRADE CLASSIFICATION ENGINE
    MicroStation-style: only touched points updated, no full RGB rewrite.
    """
    if app.data is None or to_class is None:
        return
 
    classes = app.data["classification"]
    update_idx = np.where(update_mask)[0]
    if update_idx.size == 0:
        return
 
    # --- 1. Visibility & Filter Protection ---
    visible_classes = _get_visible_classes_for_current_view(app)
    if visible_classes is not None:
        visible_mask = np.isin(classes[update_idx], visible_classes)
        update_idx = update_idx[visible_mask]
 
    if from_classes:
        class_mask = np.isin(classes[update_idx], from_classes)
        update_idx = update_idx[class_mask]
 
    if update_idx.size == 0:
        return
 
    # --- 2. LOG FOR UNDO ---
    final_bool_mask = np.zeros(len(classes), dtype=bool)
    final_bool_mask[update_idx] = True
 
    undo_entry = {
        "mask": final_bool_mask,
        "old_classes": classes[update_idx].copy(),
        "new_classes": np.full(update_idx.size, to_class, dtype=classes.dtype)
    }
    app.undo_stack.append(undo_entry)
    app.redo_stack.clear()
 
    # --- 3. APPLY TO DATA (CPU) ---
    classes[update_idx] = to_class
 
    # --- 4. SYNC TO GPU ---
    # DO NOT call sync_palette_to_gpu here — that rewrites ALL 13.4M points (290ms).
    # Instead use targeted updates: only update the changed points' RGB + push uniforms.
    try:
        from gui.unified_actor_manager import (
            fast_classify_update,
            fast_cross_section_update,
            is_unified_actor_ready,
            _push_uniforms_direct,
        )
        palette = getattr(app, 'class_palette', {})
 
        # Update main view: only changed points' RGB + uniform push (O(changed) not O(all))
        if is_unified_actor_ready(app):
            fast_classify_update(app, final_bool_mask, to_class, palette=palette)

        if getattr(app, "display_mode", "class") == "shaded_class":
            try:
                from gui.shading_display import refresh_shaded_after_classification_fast
                refresh_shaded_after_classification_fast(app, changed_mask=final_bool_mask)
            except Exception as _se:
                print(f"⚠️ Shading refresh failed: {_se}")
                try:
                    from gui.shading_display import update_shaded_class
                    update_shaded_class(app, force_rebuild=True)
                except Exception:
                    pass
        # Update ALL cross-sections — RGB inject first, then batch render
        if hasattr(app, 'section_vtks') and app.section_vtks:
            for view_idx in app.section_vtks:
                try:
                    fast_cross_section_update(app, view_idx, final_bool_mask,
                                              skip_render=True)
                except Exception:
                    pass
            for view_idx, sw in app.section_vtks.items():
                if sw:
                    try: sw.render()
                    except: pass

        # Update cut section if active — direct RGB poke (MicroStation: changed points only)
        if hasattr(app, 'cut_section_controller') and app.cut_section_controller:
            ctrl = app.cut_section_controller
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

                                # ⚡ VECTORIZED: replaces O(N) Python loop
                                # Old: for local_i in range(len(cut_map)): ...
                                # = 149,202 Python iterations per click → OOM crash after 15 clicks
                                # New: single numpy isin call → ~1ms regardless of size
                                cut_map_arr = np.asarray(ctrl._cut_index_map)
                                local_arr = np.where(np.isin(cut_map_arr, update_idx))[0]

                                if len(local_arr) > 0:
                                    new_color = palette.get(to_class, {}).get('color', (128, 128, 128))
                                    vtk_ptr[local_arr] = new_color
                                    vtk_colors.Modified()
                                    polydata.Modified()

                                if hasattr(ctrl, 'cut_vtk') and ctrl.cut_vtk:
                                    ctrl.cut_vtk.render()
                except Exception as _ce:
                    print(f"⚠️ Cut section poke failed: {_ce}")

        # Render main view
        try:
            app.vtk_widget.render()
        except Exception:
            pass

        # Section renders already batched above after RGB injects

        # ✅ FIX: Signal GPU sync done — prevents decorator double-refresh
        if getattr(app, "display_mode", "class") != "shaded_class":
            app._gpu_sync_done = True
 
    except Exception as e:
        print(f"⚠️ GPU Sync Error: {e}")
 
    print(f"⚡ Global Sync: All viewports updated via GPU uniforms.")



def classify_points_example(app, selected_indices, target_class):
    """
    Example of how to classify points and ensure they're visible.
    Add this pattern to ALL your classification functions.
    """
    
    # 1. Perform the classification
    app.data["classification"][selected_indices] = target_class
    
    # 2. ✅ CRITICAL: Mark this class as recently modified
    # This makes update_class_mode() render it LAST (on top)
    app._last_classified_to_class = target_class
    
    # 3. Trigger re-render (which will read the flag)
    from gui.class_display import update_class_mode
    update_class_mode(app)


def debug_priority_rendering(app):
    """
    Debug helper to check if priority rendering flags are set correctly.
    Call this after classification to verify the state.
    """
    print("\n" + "="*60)
    print("🔍 PRIORITY RENDERING DEBUG")
    print("="*60)
    
    # Check priority class flag
    has_priority_class = hasattr(app, '_last_classified_to_class')
    print(f"Priority class flag exists: {has_priority_class}")
    if has_priority_class:
        print(f"   → Class: {app._last_classified_to_class}")
        
        # Check if this class is in palette
        if hasattr(app, 'class_palette') and app._last_classified_to_class in app.class_palette:
            info = app.class_palette[app._last_classified_to_class]
            print(f"   → Visible: {info.get('show', False)}")
            print(f"   → Weight: {info.get('weight', 1.0)}")
            print(f"   → Color: {info.get('color', (0,0,0))}")
        else:
            print(f"   ⚠️ Class {app._last_classified_to_class} NOT in palette!")
    
    # Check priority mask
    has_priority_mask = hasattr(app, '_last_changed_mask')
    print(f"\nPriority mask flag exists: {has_priority_mask}")
    if has_priority_mask:
        mask = app._last_changed_mask
        print(f"   → Type: {type(mask)}")
        print(f"   → Shape: {mask.shape}")
        print(f"   → Points flagged: {np.sum(mask):,}")
        print(f"   → Total dataset: {len(app.data['classification']):,}")
        
        # Check what classes these points belong to
        if np.sum(mask) > 0:
            flagged_classes = np.unique(app.data['classification'][mask])
            print(f"   → Classes in flagged points: {flagged_classes}")
    
    print("="*60 + "\n")
    
    # The flag is automatically cleared after rendering

def _get_visible_classes_for_current_view(app):
    """
    Get visible classes for the CURRENT active view.
    
    ✅ FIXED: Properly detects cut section and uses slot 5 palette
    ✅ Returns list of class codes that are visible, or None if no filtering.
    ✅ Uses view-specific palette from display_mode_dialog
    ✅ Does NOT affect main view or cross-section logic
    
    View mapping:
    - Slot 0: Main View
    - Slot 1-4: Cross-Section Views 1-4
    - Slot 5: Cut Section View (NEW!)
    """
    try:
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 1: Determine which view context we're in
        # ═══════════════════════════════════════════════════════════════════════
        
        target_slot = None
        view_context = None
        
        # ✅ PRIORITY 1: Check CUT SECTION FIRST (highest priority)
        is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
        
        if is_cut_section:
            target_slot = 5  # ✅ CUT SECTION always uses slot 5
            view_context = "Cut Section"
            print(f"   📍 Classification in {view_context} View (slot {target_slot})")
        
        # ✅ PRIORITY 2: Check CROSS-SECTION (if not in cut section)
        else:
            is_cross_section = (
                hasattr(app, 'section_controller') and 
                hasattr(app, 'section_vtks') and 
                len(getattr(app, 'section_vtks', {})) > 0
            )
            
            if is_cross_section:
                # Get active cross-section view index (0-3)
                view_index = getattr(app.section_controller, 'active_view', None)
                
                if view_index is not None and 0 <= view_index <= 3:
                    target_slot = view_index + 1  # Convert to slot 1-4
                    view_context = f"Cross-Section View {view_index + 1}"
                    print(f"   📍 Classification in {view_context} (slot {target_slot})")
                else:
                    target_slot = 0  # Fallback to main view
                    view_context = "Main View (fallback)"
                    print(f"   📍 Classification in {view_context} (slot {target_slot})")
            
            # ✅ PRIORITY 3: Default to MAIN VIEW
            else:
                target_slot = 0
                view_context = "Main View"
                print(f"   📍 Classification in {view_context} (slot {target_slot})")
        
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 2: Get visible classes from display_mode_dialog
        # ═══════════════════════════════════════════════════════════════════════
        
        if hasattr(app, 'display_mode_dialog') and app.display_mode_dialog:
            dialog = app.display_mode_dialog
            
            # ✅ Method 1: Use dialog's dedicated method (if available)
            if hasattr(dialog, 'get_visible_classes_for_view'):
                try:
                    visible = dialog.get_visible_classes_for_view(target_slot)
                    
                    if visible is not None:
                        hidden = []
                        
                        # Get all classes in this view's palette to identify hidden ones
                        if hasattr(dialog, 'view_palettes') and target_slot in dialog.view_palettes:
                            all_classes = list(dialog.view_palettes[target_slot].keys())
                            hidden = [c for c in all_classes if c not in visible]
                        
                        print(f"   📋 Using get_visible_classes_for_view({target_slot})")
                        print(f"   👁️ Visible classes: {visible}")
                        if hidden:
                            print(f"   🚫 Hidden classes (protected): {hidden}")
                        
                        return visible
                
                except Exception as e:
                    print(f"   ⚠️ get_visible_classes_for_view({target_slot}) failed: {e}")
                    # Fall through to Method 2
            
            # ✅ Method 2: Direct access to view_palettes dictionary
            if hasattr(dialog, 'view_palettes') and target_slot in dialog.view_palettes:
                palette = dialog.view_palettes[target_slot]
                
                # Extract visible classes from palette
                visible = [c for c, info in palette.items() if info.get('show', True)]
                hidden = [c for c, info in palette.items() if not info.get('show', True)]
                
                print(f"   📋 Using view_palettes[{target_slot}]")
                print(f"   👁️ Visible classes: {visible}")
                if hidden:
                    print(f"   🚫 Hidden classes (protected): {hidden}")
                
                return visible
        
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 3: Fallback options (if display_mode_dialog not available)
        # ═══════════════════════════════════════════════════════════════════════
        
        # ✅ Fallback 1: For cut section, try cut_section_controller.cut_palette
        if is_cut_section and hasattr(app, 'cut_section_controller'):
            cut_ctrl = app.cut_section_controller
            
            if hasattr(cut_ctrl, 'cut_palette') and cut_ctrl.cut_palette:
                palette = cut_ctrl.cut_palette
                visible = [c for c, info in palette.items() if info.get('show', True)]
                hidden = [c for c, info in palette.items() if not info.get('show', True)]
                
                print(f"   📋 Using cut_section_controller.cut_palette (fallback)")
                print(f"   👁️ Visible classes: {visible}")
                if hidden:
                    print(f"   🚫 Hidden classes (protected): {hidden}")
                
                return visible
        
        # ✅ Fallback 2: Use global class_palette (main view only)
        if target_slot == 0 and hasattr(app, 'class_palette') and app.class_palette:
            visible = [c for c, info in app.class_palette.items() if info.get('show', True)]
            
            print(f"   ⚠️ Using global class_palette (fallback): {len(visible)} visible classes")
            return visible
        
        # ═══════════════════════════════════════════════════════════════════════
        # STEP 4: No filtering available - allow all classes
        # ═══════════════════════════════════════════════════════════════════════
        
        print(f"   ⚠️ No palette found for {view_context} - allowing all classes (no protection)")
        return None  # None = no filtering, classify all points
        
    except Exception as e:
        print(f"   ❌ Error getting visible classes: {e}")
        import traceback
        traceback.print_exc()
        return None    
@classify_with_stats_update
def classify_freehand(app, freehand_xy=None, from_classes=None, to_class=None,
                     mask=None, section_points=None, visible_bounds=None):
    """
    Classify freehand - uses polygon logic WITHOUT viewport filtering.
    """
    print(f"\n{'='*60}")
    print(f"📍 classify_freehand CALLED")
    print(f"{'='*60}")
    print(f"   freehand_xy: {len(freehand_xy) if freehand_xy else 0} points")
    print(f"   from_classes: {from_classes}")
    print(f"   to_class: {to_class}")
    print(f"   mask: {type(mask)}, {len(mask) if mask is not None else 0}")
    print(f"   section_points: {section_points.shape if section_points is not None else None}")
    print(f"{'='*60}\n")
    
    return classify_polygon(app, freehand_xy, from_classes, to_class, mask, section_points, visible_bounds)

@classify_with_stats_update
def classify_above_line(app, line_pts=None, from_classes=None, to_class=None,
                        mask=None, section_points=None, visible_bounds=None):
    """
    Classify points above a drawn line in cross/cut-section views.
    ✅ NOW: Properly applies viewport filtering when zoomed
    ✅ FIX: Respects visible class filters
    """
    # ✅ CRITICAL FIX: Check if in CUT SECTION FIRST
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    if is_cut_section:
        print("🔒 CUT SECTION MODE - Using cut data directly")
        if app.cut_section_controller is None or app.cut_section_controller.cut_points is None:
            print("❌ No cut section data available")
            return
        
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
        print(f"🔒 Cut section: {len(section_points)} points, {len(mask_or_indices)} indices")
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)

    if line_pts is None or len(line_pts) < 2:
        print("⚠️ No line defined for AboveLine tool.")
        return

    if section_points is None or len(section_points) == 0:
        print("⚠️ No section points found.")
        return

    # Project points to 2D FIRST (same view as rectangle/circle)
    if is_cut_section:
        pts_2d = _project_to_cut_view(app, section_points)
        view_mode = "cut"
    else:
        view_mode = getattr(app, "cross_view_mode", "side")
        pts_2d = _project_to_2d_view(section_points, view_mode)

    # ✅ FIX: Get viewport bounds in the SAME 2D coordinate system
    viewport_mask = _get_viewport_mask_for_2d(app, pts_2d, is_cut_section, view_mode)
    if viewport_mask is None:
        viewport_mask = np.ones(len(section_points), dtype=bool)

    num_visible = int(np.sum(viewport_mask))
    print(f"📍 Viewport contains {num_visible}/{len(section_points)} points (zoomed view)")

    # Calculate line equation
    (x1, z1), (x2, z2) = line_pts
    m = (z2 - z1) / (x2 - x1 + 1e-9)
    b = z1 - m * x1
    xmin, xmax = sorted([x1, x2])

    # Select points above line
    in_strip = (pts_2d[:, 0] >= xmin) & (pts_2d[:, 0] <= xmax)
    above = pts_2d[:, 1] >= (m * pts_2d[:, 0] + b)

    # ✅ CRITICAL: Apply viewport filter BEFORE converting to dataset indices
    geometry_mask = in_strip & above
    local_mask = geometry_mask & viewport_mask

    # ✅ NEW: Apply visible class filter
    visible_classes = _get_visible_classes_for_current_view(app)
    if visible_classes is not None:
        # Get classification array for section points
        if isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool:
            section_indices = np.where(mask_or_indices)[0]
        else:
            section_indices = mask_or_indices
        
        section_classification = app.data["classification"][section_indices]
        class_mask = np.isin(section_classification, visible_classes)
        
        num_before_class_filter = int(np.sum(local_mask))
        local_mask = local_mask & class_mask
        num_after_class_filter = int(np.sum(local_mask))
        
        print(f"🔍 Class filter: {num_before_class_filter} → {num_after_class_filter} points")
        print(f"   Only classifying visible classes: {visible_classes}")

    num_geometry = int(np.sum(geometry_mask))
    num_selected = int(np.sum(local_mask))
    print(f"📐 Above Line: {num_geometry} in geometry, {num_selected} after all filters")

    if num_selected == 0:
        print("⚠️ No points above line in visible viewport with visible classes")
        return

    # Create update mask
    update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)

    # Map to dataset indices
    if isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool:
        selected_indices = np.where(mask_or_indices)[0][local_mask]
    else:
        selected_indices = mask_or_indices[local_mask]

    update_mask[selected_indices] = True

    _apply_classification(app, update_mask, from_classes, to_class)
    verify_classification_applied(app, update_mask, to_class, "Above Line")

@classify_with_stats_update
def classify_below_line(app, line_pts=None, from_classes=None, to_class=None,
                        mask=None, section_points=None, visible_bounds=None):
    """
    Classify points below a drawn line in cross/cut-section views.
    ✅ FIXED: Uses SAME coordinate handling as classify_above_line
    """
    print(f"\n{'='*60}")
    print(f"📐 classify_below_line CALLED")
    print(f"{'='*60}")
   
    # ✅ CRITICAL FIX: Check if in CUT SECTION FIRST
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    if is_cut_section:
        print("🔒 CUT SECTION MODE - Using cut data directly")
        if app.cut_section_controller is None or app.cut_section_controller.cut_points is None:
            print("❌ No cut section data available")
            return
       
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
        print(f"🔒 Cut section: {len(section_points)} points, {len(mask_or_indices)} indices")
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)
 
    if line_pts is None or len(line_pts) < 2:
        print("⚠️ No line defined for BelowLine tool.")
        print(f"{'='*60}\n")
        return
 
    if section_points is None or len(section_points) == 0:
        print("⚠️ No section points found.")
        print(f"{'='*60}\n")
        return
 
    # ✅ CRITICAL: Use SAME projection logic as classify_above_line
    if is_cut_section:
        pts_2d = _project_to_cut_view(app, section_points)
        view_mode = "cut"
    else:
        view_mode = getattr(app, "cross_view_mode", "side")
        pts_2d = _project_to_2d_view(section_points, view_mode)
   
    print(f"   View mode: {view_mode}")
    print(f"   Projected to 2D using: {view_mode} mode")
    print(f"   Points 2D shape: {pts_2d.shape}")
 
    # ✅ Get viewport bounds - uses correct view_mode
    viewport_mask = _get_viewport_mask_for_2d(app, pts_2d, is_cut_section, view_mode)
    if viewport_mask is None:
        viewport_mask = np.ones(len(section_points), dtype=bool)
 
    num_visible = int(np.sum(viewport_mask))
    print(f"📍 Viewport contains {num_visible}/{len(section_points)} points")
 
    # ✅ Calculate line equation (SAME as above_line)
    (x1, z1), (x2, z2) = line_pts
    print(f"   Line: ({x1:.2f}, {z1:.2f}) → ({x2:.2f}, {z2:.2f})")
   
    m = (z2 - z1) / (x2 - x1 + 1e-9)
    b = z1 - m * x1
    xmin, xmax = sorted([x1, x2])
   
    print(f"   Line equation: z = {m:.4f} * x + {b:.4f}")
    print(f"   X range: [{xmin:.2f}, {xmax:.2f}]")
 
    # ✅ ONLY DIFFERENCE: <= instead of >=
    in_strip = (pts_2d[:, 0] >= xmin) & (pts_2d[:, 0] <= xmax)
    below = pts_2d[:, 1] <= (m * pts_2d[:, 0] + b)  # ← ONLY DIFFERENCE
 
    print(f"   Points in X strip: {np.sum(in_strip)}")
    print(f"   Points below line: {np.sum(below)}")
 
    # ✅ Apply viewport filter
    geometry_mask = in_strip & below
    local_mask = geometry_mask & viewport_mask
 
    print(f"   After viewport filter: {np.sum(local_mask)}")
 
    # ✅ Apply visible class filter
    visible_classes = _get_visible_classes_for_current_view(app)
    if visible_classes is not None:
        if isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool:
            section_indices = np.where(mask_or_indices)[0]
        else:
            section_indices = mask_or_indices
       
        section_classification = app.data["classification"][section_indices]
        class_mask = np.isin(section_classification, visible_classes)
       
        num_before_class_filter = int(np.sum(local_mask))
        local_mask = local_mask & class_mask
        num_after_class_filter = int(np.sum(local_mask))
       
        print(f"🔍 Class filter: {num_before_class_filter} → {num_after_class_filter} points")
        print(f"   Visible classes: {visible_classes}")
 
    num_geometry = int(np.sum(geometry_mask))
    num_selected = int(np.sum(local_mask))
    print(f"📐 Below Line: {num_geometry} in geometry, {num_selected} after all filters")
 
    if num_selected == 0:
        print("⚠️ No points below line in visible viewport with visible classes")
        print(f"{'='*60}\n")
        return
 
    # ✅ Create update mask and map to dataset indices
    update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
 
    if isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool:
        selected_indices = np.where(mask_or_indices)[0][local_mask]
    else:
        selected_indices = mask_or_indices[local_mask]
 
    update_mask[selected_indices] = True
   
    print(f"   Final dataset indices: {len(selected_indices)}")
 
    # ✅ Apply classification
    _apply_classification(app, update_mask, from_classes, to_class)
    verify_classification_applied(app, update_mask, to_class, "Below Line")
   
    print(f"{'='*60}\n")
    
def _get_viewport_mask_for_2d(app, pts_2d, is_cut_section, view_mode):

    """

    Get viewport bounds in the SAME 2D coordinate system used by tools.

    This ensures viewport filtering works correctly for zoomed views.

    Args:

        pts_2d: Nx2 array of 2D projected points

        is_cut_section: bool - whether we're in cut section view

        view_mode: "side", "front", or "cut"

    Returns:

        Boolean mask of points inside visible viewport

    """

    try:

        if pts_2d is None or len(pts_2d) == 0:

            return None

        # Get the renderer

        vtk_widget = None

        if is_cut_section and hasattr(app, 'cut_section_controller'):

            ctrl = app.cut_section_controller

            if getattr(ctrl, 'is_cut_view_active', False) and getattr(ctrl, 'cut_vtk', None) is not None:

                vtk_widget = ctrl.cut_vtk

        if vtk_widget is None and hasattr(app, 'section_controller'):

            active_view = getattr(app.section_controller, 'active_view', None)

            if active_view is not None and active_view in getattr(app, 'section_vtks', {}):

                vtk_widget = app.section_vtks[active_view]

        if vtk_widget is None:

            return None

        ren = vtk_widget.renderer

        if ren is None:

            return None

        cam = ren.GetActiveCamera()

        fp_world = np.array(cam.GetFocalPoint(), dtype=float)

        scale = float(cam.GetParallelScale())

        try:

            size = ren.GetRenderWindow().GetSize()

            aspect = size[0] / max(size[1], 1)

        except:

            aspect = 1.0

        half_w = scale * aspect

        half_h = scale

        # ✅ For both cut and cross-section, project focal point to 2D

        if is_cut_section:

            fp_2d = _project_to_cut_view(app, fp_world.reshape(1, 3))[0]

        else:

            fp_2d = _project_to_2d_view(fp_world.reshape(1, 3), view_mode)[0]

        u_center = fp_2d[0]

        z_center = fp_2d[1]

        # Define viewport bounds in 2D space

        u_min = u_center - half_w

        u_max = u_center + half_w

        z_min = z_center - half_h

        z_max = z_center + half_h

        # Create mask of points inside viewport

        viewport_mask = (

            (pts_2d[:, 0] >= u_min) & (pts_2d[:, 0] <= u_max) &

            (pts_2d[:, 1] >= z_min) & (pts_2d[:, 1] <= z_max)

        )

        num_in_viewport = int(np.sum(viewport_mask))

        print(f"   🔍 Viewport 2D bounds: u=[{u_min:.1f}, {u_max:.1f}], z=[{z_min:.1f}, {z_max:.1f}]")

        print(f"   🔍 Points in viewport: {num_in_viewport}/{len(pts_2d)}")

        return viewport_mask

    except Exception as e:

        print(f"⚠️ _get_viewport_mask_for_2d() failed: {e}")

        import traceback

        traceback.print_exc()

        return None

 
@classify_with_stats_update
def classify_rectangle(app, rect_bounds=None, from_classes=None, to_class=None,
                       mask=None, section_points=None, visible_bounds=None):
    """
    Classify rectangle selection.
    ✅ FIXED: Uses cut data when in cut section
    """
    # ✅ CHECK CUT SECTION FIRST
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    
    if is_cut_section:
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
        print(f"🔒 Cut section: {len(section_points)} points, {len(mask_or_indices)} indices")
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)
    
    if rect_bounds is None:
        update_mask = getattr(app, "last_mask", None)
        if update_mask is None:
            print("⚠️ No active rectangle ROI")
            return
        return _apply_classification(app, update_mask.copy(), from_classes, to_class)
    
    if mask_or_indices is None:
        mask_or_indices = np.ones(len(app.data["xyz"]), dtype=bool)
    
    if section_points is not None:
        # ✅ Project to correct view
        if is_cut_section:
            pts_2d = _project_to_cut_view(app, section_points)
            view_mode = "cut"
        else:
            view_mode = getattr(app, "cross_view_mode", "side")
            pts_2d = _project_to_2d_view(section_points, view_mode)
        
        xmin, xmax, ymin, ymax = rect_bounds
        in_rect = (
            (pts_2d[:, 0] >= xmin) & (pts_2d[:, 0] <= xmax) &
            (pts_2d[:, 1] >= ymin) & (pts_2d[:, 1] <= ymax)
        )
        
        local_mask = in_rect
        num_selected = int(np.sum(local_mask))
        print(f"▭ Rectangle: {num_selected} points selected")
        
        if num_selected == 0:
            print("⚠️ No points in rectangle")
            return
        
        update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
        
        if isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool:
            selected_indices = np.where(mask_or_indices)[0][local_mask]
        else:
            selected_indices = mask_or_indices[local_mask]
        
        update_mask[selected_indices] = True
        
        _apply_classification(app, update_mask, from_classes, to_class)
        verify_classification_applied(app, update_mask, to_class, "Rectangle")


@classify_with_stats_update
def classify_circle(app, center=None, radius=None, from_classes=None, to_class=None,
                    mask=None, section_points=None, visible_bounds=None):
    """
    Classify circle selection.
    ✅ FIXED: Uses cut data when in cut section
    """
    # ✅ CHECK CUT SECTION FIRST
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    
    if is_cut_section:
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
        print(f"🔒 Cut section: {len(section_points)} points, {len(mask_or_indices)} indices")
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)
    
    if center is None or radius is None:
        update_mask = getattr(app, "last_mask", None)
        if update_mask is None:
            print("⚠️ No active circle ROI")
            return
        return _apply_classification(app, update_mask.copy(), from_classes, to_class)
    
    if mask_or_indices is None:
        mask_or_indices = np.ones(len(app.data["xyz"]), dtype=bool)
    
    if section_points is not None:
        # ✅ Project to correct view
        if is_cut_section:
            pts_2d = _project_to_cut_view(app, section_points)
            view_mode = "cut"
        else:
            view_mode = getattr(app, "cross_view_mode", "side")
            pts_2d = _project_to_2d_view(section_points, view_mode)
        
        cx, cy = center
        d2 = (pts_2d[:, 0] - cx) ** 2 + (pts_2d[:, 1] - cy) ** 2
        in_circle = d2 <= radius ** 2
        
        local_mask = in_circle
        num_selected = int(np.sum(local_mask))
        print(f"⭕ Circle: {num_selected} points selected")
        
        if num_selected == 0:
            print("⚠️ No points in circle")
            return
        
        update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
        
        if isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool:
            selected_indices = np.where(mask_or_indices)[0][local_mask]
        else:
            selected_indices = mask_or_indices[local_mask]
        
        update_mask[selected_indices] = True
        
        _apply_classification(app, update_mask, from_classes, to_class)
        verify_classification_applied(app, update_mask, to_class, "Circle")
pass


@classify_with_stats_update
def classify_polygon(app, polygon_xy=None, from_classes=None, to_class=None,
                     mask=None, section_points=None, visible_bounds=None):
    """
    Classify polygon selection.
    ✅ FIXED: Uses cut data when in cut section
    """
    from matplotlib.path import Path
    
    # ✅ CHECK CUT SECTION FIRST
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    
    if is_cut_section:
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
        print(f"🔒 Cut section: {len(section_points)} points, {len(mask_or_indices)} indices")
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)
    
    if polygon_xy is None:
        update_mask = getattr(app, "last_mask", None)
        if update_mask is None:
            print("⚠️ No active polygon ROI")
            return
        return _apply_classification(app, update_mask.copy(), from_classes, to_class)
    
    if mask_or_indices is None:
        mask_or_indices = np.ones(len(app.data["xyz"]), dtype=bool)
    
    if section_points is not None:
        # ✅ Project to correct view
        if is_cut_section:
            pts_2d = _project_to_cut_view(app, section_points)
            view_mode = "cut"
        else:
            view_mode = getattr(app, "cross_view_mode", "side")
            pts_2d = _project_to_2d_view(section_points, view_mode)
        
        path = Path(polygon_xy, closed=True)
        in_polygon = path.contains_points(pts_2d)
        
        local_mask = in_polygon
        num_selected = int(np.sum(local_mask))
        print(f"⬠ Polygon: {num_selected} points selected")
        
        if num_selected == 0:
            print("⚠️ No points in polygon")
            return
        
        update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
        
        if isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool:
            selected_indices = np.where(mask_or_indices)[0][local_mask]
        else:
            selected_indices = mask_or_indices[local_mask]
        
        update_mask[selected_indices] = True
        
        _apply_classification(app, update_mask, from_classes, to_class)
        verify_classification_applied(app, update_mask, to_class, "Polygon")
    else:
        # Main view - no section points
        xyz = app.data["xyz"]
        pts = xyz[mask_or_indices]
        
        path = Path(polygon_xy, closed=True)
        inside = path.contains_points(pts[:, :2])
        
        update_mask = np.zeros(len(xyz), dtype=bool)
        update_mask[mask_or_indices] = inside
        
        _apply_classification(app, update_mask, from_classes, to_class)
        verify_classification_applied(app, update_mask, to_class, "Polygon")


# @classify_with_stats_update
# def classify_brush(app, center=None, radius=None, from_classes=None, to_class=None,
#                   mask=None, section_points=None, visible_bounds=None):
#     """
#     Classify brush tool - uses circle logic WITH viewport filtering.
#     ✅ FIXED: Properly detects active view and applies correct projection
#     ✅ FIXED: Respects visible class filters
#     """
#     print(f"\n{'='*60}")
#     print(f"🖌️ classify_brush CALLED")
#     print(f"{'='*60}")
    
#     # ✅ STEP 1: Determine correct view mode FIRST
#     is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    
#     if is_cut_section:
#         view_mode = "cut"
#         active_view = None
#         print(f"   View: Cut Section")
#     else:
#         active_view = getattr(app.section_controller, "active_view", None)
#         # ✅ CRITICAL: Determine view_mode from active view INDEX
#         if active_view in [1, 3]:  # Views 2 and 4 are front views
#             view_mode = "front"
#         else:  # Views 1 and 3 are side views
#             view_mode = "side"
        
#         print(f"   View: Cross-Section {active_view + 1 if active_view is not None else '?'}")
#         print(f"   Mode: {view_mode}")
        
#         # ✅ Store for refresh tracking
#         if hasattr(app, '_last_classification_view'):
#             app._last_classification_view = active_view
    
#     # ✅ STEP 2: Get section data with correct view mode stored
#     app._current_brush_view_mode = view_mode  # Store for use in classify_circle
    
#     # Call classify_circle with the stored view mode
#     result = classify_circle(app, center, radius, from_classes, to_class, mask, section_points, visible_bounds)
    
#     # Clean up
#     if hasattr(app, '_current_brush_view_mode'):
#         delattr(app, '_current_brush_view_mode')
    
#     print(f"{'='*60}\n")
#     return result

@classify_with_stats_update
def classify_brush(app, center=None, radius=None, from_classes=None, to_class=None,
                  mask=None, section_points=None, visible_bounds=None):
    """
    🚀 OPTIMIZED BRUSH: Millisecond classification using cached KDTree.
    
    Key optimizations:
    1. Uses cached KDTree (built once, reused for drag)
    2. Direct GPU buffer update (no actor rebuild)
    3. Minimal logging (only errors)
    4. Single render pass
    """
    
    if center is None or radius is None:
        return
    
    # ═══════════════════════════════════════════════════════════════════════
    # STEP 1: Get section data (cached during drag)
    # ═══════════════════════════════════════════════════════════════════════
    
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    
    # Use cached data if available (set during brush init)
    if hasattr(app, '_brush_cache') and app._brush_cache is not None:
        cache = app._brush_cache
        pts_2d = cache['pts_2d']
        mask_or_indices = cache['mask_or_indices']
        kdtree = cache['kdtree']
        visible_classes = cache.get('visible_classes')
        section_classification = cache.get('section_classification')
    else:
        # First brush stroke - build cache
        if is_cut_section:
            if app.cut_section_controller is None or app.cut_section_controller.cut_points is None:
                return
            section_points = app.cut_section_controller.cut_points
            mask_or_indices = app.cut_section_controller._cut_index_map
            pts_2d = _project_to_cut_view(app, section_points)
        else:
            mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)
            if section_points is None:
                return
            view_mode = getattr(app, "cross_view_mode", "side")
            pts_2d = _project_to_2d_view(section_points, view_mode)
        
        # Build KDTree (expensive, but only once)
        from scipy.spatial import cKDTree
        kdtree = cKDTree(pts_2d)
        
        # Get visible classes (once)
        visible_classes = _get_visible_classes_for_current_view(app)
        
        # Cache section classification
        if isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool:
            section_indices = np.where(mask_or_indices)[0]
        else:
            section_indices = mask_or_indices
        section_classification = app.data["classification"][section_indices]
        
        # Store cache
        app._brush_cache = {
            'pts_2d': pts_2d,
            'mask_or_indices': mask_or_indices,
            'kdtree': kdtree,
            'visible_classes': visible_classes,
            'section_classification': section_classification,
            'section_indices': section_indices
        }
        cache = app._brush_cache
    
    # ═══════════════════════════════════════════════════════════════════════
    # STEP 2: Fast radius query using KDTree
    # ═══════════════════════════════════════════════════════════════════════
    
    local_indices = kdtree.query_ball_point([center[0], center[1]], radius)
    
    if len(local_indices) == 0:
        return
    
    local_indices = np.array(local_indices, dtype=np.int64)
    
    # ═══════════════════════════════════════════════════════════════════════
    # STEP 3: Apply filters (visible classes, from_classes)
    # ═══════════════════════════════════════════════════════════════════════
    
    section_classification = cache['section_classification']
    local_classes = section_classification[local_indices]
    
    # Filter by visible classes
    if cache.get('visible_classes') is not None:
        visible_mask = np.isin(local_classes, cache['visible_classes'])
        local_indices = local_indices[visible_mask]
        local_classes = local_classes[visible_mask]
        
        if len(local_indices) == 0:
            return
    
    # Filter by from_classes
    if from_classes is not None and len(from_classes) > 0:
        from_mask = np.isin(local_classes, from_classes)
        local_indices = local_indices[from_mask]
        
        if len(local_indices) == 0:
            return
    
    # ═══════════════════════════════════════════════════════════════════════
    # STEP 4: Map to global indices and apply classification
    # ═══════════════════════════════════════════════════════════════════════
    
    section_indices = cache['section_indices']
    
    if isinstance(section_indices, np.ndarray):
        global_indices = section_indices[local_indices]
    else:
        global_indices = np.array(section_indices)[local_indices]
    
    # Store old classes for undo
    old_classes = app.data["classification"][global_indices].copy()
    
    # Apply classification
    app.data["classification"][global_indices] = to_class
    
    # Update cached section_classification
    cache['section_classification'][local_indices] = to_class
    
    # ═══════════════════════════════════════════════════════════════════════
    # STEP 5: Store undo info
    # ═══════════════════════════════════════════════════════════════════════
    
    if not hasattr(app, "undo_stack"):
        app.undo_stack = []
    
    update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
    update_mask[global_indices] = True
    
    app.undo_stack.append({
        "mask": update_mask,
        "old_classes": old_classes,
        "new_classes": np.full(len(global_indices), to_class, dtype=old_classes.dtype),
        "is_cut_locked": is_cut_section
    })
    # Clear stale redo entries and cap undo stack
    if hasattr(app, "redo_stack"):
        app.redo_stack.clear()
    max_steps = getattr(app, '_max_undo_steps', 30)
    while len(app.undo_stack) > max_steps:
        from gui.memory_manager import _free_undo_entry
        _free_undo_entry(app.undo_stack.pop(0))

    app._last_changed_mask = update_mask
    
    # ═══════════════════════════════════════════════════════════════════════
    # STEP 6: Fast GPU color update (NO actor rebuild!)
    # ═══════════════════════════════════════════════════════════════════════
    
    _fast_update_colors(app, global_indices, to_class, is_cut_section)


def _fast_update_colors(app, indices, new_class, is_cut_section):
    """
    🚀 Direct GPU buffer update - NO actor rebuild.
    Updates colors in ~1ms instead of ~200ms.
    """
    try:
        # Get new color
        new_rgb = app.class_palette.get(new_class, {}).get('color', (128, 128, 128))
        new_rgb = np.array(new_rgb, dtype=np.uint8)
        
        # ═══════════════════════════════════════════════════════════════════
        # Update CROSS-SECTION views (only the active one)
        # ═══════════════════════════════════════════════════════════════════
        
        if not is_cut_section and hasattr(app, 'section_controller'):
            active_view = getattr(app.section_controller, 'active_view', None)
            
            if active_view is not None and active_view in getattr(app, 'section_vtks', {}):
                vtk_widget = app.section_vtks[active_view]
                
                # Get the actor for this view
                actors = vtk_widget.renderer.GetActors()
                actors.InitTraversal()
                
                for _ in range(actors.GetNumberOfItems()):
                    actor = actors.GetNextActor()
                    if actor is None:
                        continue
                    
                    mapper = actor.GetMapper()
                    if mapper is None:
                        continue
                    
                    polydata = mapper.GetInput()
                    if polydata is None:
                        continue
                    
                    vtk_colors = polydata.GetPointData().GetScalars()
                    if vtk_colors is None:
                        continue
                    
                    num_tuples = vtk_colors.GetNumberOfTuples()
                    
                    # Get the combined mask for this view
                    combined_mask = getattr(app, f"section_{active_view}_combined_mask", None)
                    
                    if combined_mask is not None:
                        # Map global indices to local view indices
                        global_to_local = np.cumsum(combined_mask) - 1
                        
                        # Filter indices that are in this view
                        valid_global = indices[combined_mask[indices]]
                        
                        if len(valid_global) > 0:
                            local_indices = global_to_local[valid_global]
                            valid_local = local_indices[local_indices < num_tuples]
                            
                            if len(valid_local) > 0:
                                # Direct color injection
                                vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                                vtk_ptr[valid_local] = new_rgb
                                vtk_colors.Modified()
                
                # Single render
                vtk_widget.render()
        
        # ═══════════════════════════════════════════════════════════════════
        # Update CUT SECTION view
        # ═══════════════════════════════════════════════════════════════════
        
        if is_cut_section and hasattr(app, 'cut_section_controller'):
            ctrl = app.cut_section_controller
            
            if ctrl.is_cut_view_active and ctrl.cut_vtk is not None:
                # Get cut actor
                actor = getattr(ctrl, 'cut_core_actor', None)
                
                if actor is not None:
                    mapper = actor.GetMapper()
                    if mapper is not None:
                        polydata = mapper.GetInput()
                        if polydata is not None:
                            vtk_colors = polydata.GetPointData().GetScalars()
                            
                            if vtk_colors is not None:
                                # Map global indices to cut-local indices
                                cut_idx = ctrl._cut_index_map
                                
                                # Find which of our indices are in the cut
                                _, idx_in_indices, idx_in_cut = np.intersect1d(
                                    indices, cut_idx, 
                                    return_indices=True, assume_unique=False
                                )
                                
                                if len(idx_in_cut) > 0:
                                    vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                                    vtk_ptr[idx_in_cut] = new_rgb
                                    vtk_colors.Modified()
                
                ctrl.cut_vtk.render()
        
        # ═══════════════════════════════════════════════════════════════════
        # Update MAIN VIEW (deferred - only on mouse release)
        # ═══════════════════════════════════════════════════════════════════
        
        # Mark for deferred update (don't update during drag)
        if not hasattr(app, '_pending_main_view_indices'):
            app._pending_main_view_indices = set()
        
        app._pending_main_view_indices.update(indices.tolist())
        
    except Exception as e:
        # Silent fail - don't slow down brush with error logging
        pass


def clear_brush_cache(app):
    """Call this when brush drag ends to clear the cache."""
    if hasattr(app, '_brush_cache'):
        del app._brush_cache
    
    # Flush pending main view updates
    if hasattr(app, '_pending_main_view_indices') and len(app._pending_main_view_indices) > 0:
        try:
            indices = np.array(list(app._pending_main_view_indices), dtype=np.int64)
            
            # Update main view in one batch
            if hasattr(app, 'vtk_widget') and hasattr(app.vtk_widget, 'actors'):
                actor = app.vtk_widget.actors.get("main_points_cloud")
                
                if actor is not None:
                    polydata = actor.GetMapper().GetInput()
                    vtk_colors = polydata.GetPointData().GetScalars()
                    
                    if vtk_colors is not None:
                        vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                        
                        # Get colors for all changed indices
                        classes = app.data["classification"][indices].astype(int)
                        palette = app.class_palette
                        
                        for idx, cls in zip(indices, classes):
                            color = palette.get(cls, {}).get('color', (128, 128, 128))
                            vtk_ptr[idx] = color
                        
                        vtk_colors.Modified()
                        app.vtk_widget.render()
            
            app._pending_main_view_indices.clear()
            
        except Exception as e:
            print(f"⚠️ Main view flush failed: {e}")

@classify_with_stats_update
def classify_point(app, point=None, radius=None, from_classes=None, to_class=None,
                  mask=None, section_points=None, visible_bounds=None):
    """
    Classify single point - uses brush logic WITHOUT viewport filtering.
    ✅ FIXED: Delegates to classify_brush → classify_circle (already fixed)
    ✅ NEW: Respects from_classes filter
    """
    return classify_brush(app, point, radius, from_classes, to_class, mask, section_points, visible_bounds)


@classify_with_stats_update
def classify_freehand(app, freehand_xy=None, from_classes=None, to_class=None,
                     mask=None, section_points=None, visible_bounds=None):
    """
    Classify freehand - uses polygon logic WITHOUT viewport filtering.
    ✅ FIXED: Delegates to classify_polygon (needs fixing if not done yet)
    ✅ NEW: Respects from_classes filter
    """
    return classify_polygon(app, freehand_xy, from_classes, to_class, mask, section_points, visible_bounds)




def _check_auto_deactivate(app):
    """
    Check if tools should auto-deactivate after classification.
    """
    try:
        from PySide6.QtCore import QSettings
        settings = QSettings("NakshaAI", "LidarApp")
        auto_deactivate = settings.value("auto_deactivate_after_classify", False, type=bool)
        return auto_deactivate
    except:
        return False
    

    


def _project_to_2d_view(points, view_mode="side"):
    """
    Project 3D points to 2D view coordinates.
    
    Args:
        points: Nx3 array of 3D coordinates (X, Y, Z)
        view_mode: "side" (XZ) or "front" (YZ)
    
    Returns:
        Nx2 array of 2D coordinates for comparison with selection shapes
    """
    if view_mode == "front":
        # Front view: Y (horizontal) vs Z (vertical)
        return points[:, [1, 2]]
    else:
        # Side view: X (horizontal) vs Z (vertical)
        return points[:, [0, 2]]
    
def _project_to_cut_view(app, points):
    """
    Project 3D points to the (u, z) coordinates used in the CUT SECTION view.

    u: coordinate perpendicular to the section tangent in the XY-plane
    z: vertical (same Z as world)
    """
    try:
        ctrl = getattr(app, 'cut_section_controller', None)
        if ctrl is None or getattr(ctrl, 'section_tangent', None) is None:
            # Fallback: behave like 'side' view
            return points[:, [0, 2]]

        tangent = np.asarray(ctrl.section_tangent, float)
        if tangent.shape[0] < 2:
            return points[:, [0, 2]]

        # Perpendicular vector in XY-plane
        perp = np.array([-tangent[1], tangent[0]], dtype=float)
        n = np.linalg.norm(perp)
        if n < 1e-9:
            return points[:, [0, 2]]

        perp /= n  # normalize

        xy = points[:, :2]         # (N, 2)
        u = xy @ perp              # dot product with perp
        z = points[:, 2]

        pts_2d = np.column_stack((u, z))
        return pts_2d

    except Exception as e:
        print(f"⚠️ _project_to_cut_view() failed: {e}")
        import traceback
        traceback.print_exc()
        # Fallback: side projection
        return points[:, [0, 2]]


def _get_visible_classes(app):
    """
    Get list of class codes that are currently visible in Display Mode.
    Returns None if all classes should be considered (no filtering).
    """
    if not hasattr(app, 'class_palette') or not app.class_palette:
        return None
    
    visible = [code for code, info in app.class_palette.items() 
               if info.get('show', True)]
    
    if len(visible) == 0:
        print("⚠️ No visible classes - classification will affect nothing")
        return []
    
    return visible


def verify_classification_applied(app, mask, to_class, tool_name):
    """Debug helper to verify classification was applied"""
    if mask is None or not hasattr(app, 'data'):
        print(f"⚠️ {tool_name}: No mask or data available")
        return False
    
    modified_region = app.data['classification'][mask]
    unique_classes = np.unique(modified_region)
    
    print(f"\n🔍 {tool_name} Verification:")
    print(f"   Modified {np.sum(mask)} points")
    print(f"   Classes after: {unique_classes}")
    
    if to_class in unique_classes:
        count = np.sum(modified_region == to_class)
        total = len(modified_region)
        print(f"   ✅ Success: {count}/{total} points are now class {to_class}")
        return True
    else:
        print(f"   ❌ FAILED: Class {to_class} not found in modified region!")
        return False


# Before ANY classification in cross-section:
def classify_in_section(app, mask, new_class, view_idx):
    # ✅ Verify class exists
    if hasattr(app, 'display_dialog') and app.display_dialog:
        palette = app.display_dialog.view_palettes.get(view_idx + 1, {})
        
        if new_class not in palette:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                app,
                "Invalid Class",
                f"Class {new_class} not in palette!\n"
                f"Please reload Display Mode and apply."
            )
            return
    
    # Proceed with classification...
    app.data["classification"][mask] = new_class


# ✅ ADD to CutSectionController class:

def on_classification_changed(self, changed_indices=None):
    """Sync classification changes back to UI."""
    # Refresh cut colors
    self._refresh_cut_colors_fast()
    
    # Mark changed indices for priority rendering
    if changed_indices is not None and self._cut_index_map is not None:
        app = self.app
        if not hasattr(app, '_last_changed_mask'):
            app._last_changed_mask = np.zeros(len(app.data['classification']), dtype=bool)
        app._last_changed_mask[changed_indices] = True

# ============================
# CUT-SECTION CLASSIFICATION FIX
# ============================
def get_active_classification_indices(self):
    """
    Override: When cut section is active, return cut-index map instead of cross-section indices.
    """
    app = self.app

    # CUT-SECTION ACTIVE?
    if getattr(app, "cut_section_active", False):
        controller = getattr(app, "cut_section_controller", None)
        if controller is not None:
            cut_data = controller.get_cut_section_classification_data()
            if cut_data is not None:
                cut_points, cut_idx = cut_data
                return cut_idx  # 🔥 Only original-cloud indices for cut section

    # FALLBACK – normal cross-section
    return getattr(app, "section_indices", None)