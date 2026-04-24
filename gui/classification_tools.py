import numpy as np
from matplotlib.path import Path
from vtkmodules.util import numpy_support

# ── Bug-6: single master debug switch — set True only during development ──────
# When False, ALL diagnostic print() calls in hot classification paths are
# compiled to no-ops by the interpreter (the `if _DBG:` block is never entered).
_DBG: bool = False


def _log(msg: str) -> None:
    """Zero-cost logger: skipped entirely when _DBG is False."""
    if _DBG:
        print(msg)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION-VIEW BOUNDING BOX CULLING HELPERS
# Called once per classification event — O(1) per section view.
# ─────────────────────────────────────────────────────────────────────────────

def _edit_bbox(xyz: np.ndarray, indices: np.ndarray):
    """Return (xmin,xmax,ymin,ymax,zmin,zmax) of the edited point set. O(k)."""
    pts = xyz[indices]
    mn  = pts.min(axis=0)
    mx  = pts.max(axis=0)
    return mn[0], mx[0], mn[1], mx[1], mn[2], mx[2]


def _section_bbox_overlaps(app, view_idx: int, edit_bb: tuple) -> bool:
    """
    Return True when the edit bounding box overlaps the stored section bbox.
    Falls back to True (conservative) when no section bbox is available.
    Prevents redundant fast_cross_section_update calls for distant sections.
    """
    sbbox = getattr(app, f"_section_{view_idx}_bbox", None)
    if sbbox is None:
        return True                              # unknown → assume overlap
    ex0, ex1, ey0, ey1, ez0, ez1 = edit_bb
    sx0, sx1, sy0, sy1, sz0, sz1 = sbbox
    return (ex0 <= sx1 and ex1 >= sx0 and
            ey0 <= sy1 and ey1 >= sy0 and
            ez0 <= sz1 and ez1 >= sz0)

def _shading_mesh_exists(app):
    """Return True if the shaded mesh has been built and is active."""
    return (
        bool(getattr(app, '_shaded_mesh_actor', None)) or
        getattr(app, '_shaded_mesh_polydata', None) is not None
    )


def _get_palette_color_lut(app):
    """Cache a dense class->RGB lookup table for fast vectorized color writes."""
    palette = getattr(app, "class_palette", {}) or {}

    signature = []
    max_code = 0
    for code, info in palette.items():
        try:
            class_code = int(code)
        except Exception:
            continue
        if class_code < 0:
            continue

        color = info.get("color", (128, 128, 128))
        if hasattr(color, "red"):
            rgb = (int(color.red()), int(color.green()), int(color.blue()))
        else:
            rgb = tuple(int(c) for c in color[:3])
        signature.append((class_code, rgb))
        if class_code > max_code:
            max_code = class_code

    signature = tuple(sorted(signature))
    cache = getattr(app, "_class_color_lut_cache", None)
    if cache and cache.get("signature") == signature:
        return cache["lut"]

    lut = np.empty((max_code + 1, 3), dtype=np.uint8)
    lut[:] = np.array((128, 128, 128), dtype=np.uint8)

    for class_code, rgb in signature:
        lut[class_code] = np.array(rgb, dtype=np.uint8)

    app._class_color_lut_cache = {
        "signature": signature,
        "lut": lut,
    }
    return lut


def _get_section_global_to_local_map(app, view_idx, combined_mask):
    """Cache global->local point remapping for repeated section color updates."""
    if combined_mask is None:
        return None

    cache = getattr(app, "_section_global_to_local_cache", None)
    if cache is None:
        cache = {}
        app._section_global_to_local_cache = cache

    key = (
        id(combined_mask),
        int(combined_mask.shape[0]),
        int(np.count_nonzero(combined_mask)),
    )
    entry = cache.get(view_idx)
    if entry and entry.get("key") == key:
        return entry["map"]

    global_to_local = np.cumsum(combined_mask, dtype=np.int64) - 1
    cache[view_idx] = {"key": key, "map": global_to_local}
    return global_to_local


def _consume_pending_main_view_indices(app):
    """Return deduplicated pending indices accumulated during brush/box updates."""
    chunks = getattr(app, "_pending_main_view_index_chunks", None)
    if chunks:
        valid_chunks = [np.asarray(chunk, dtype=np.int64).ravel() for chunk in chunks if chunk is not None and len(chunk) > 0]
        app._pending_main_view_index_chunks = []
        if not valid_chunks:
            return np.array([], dtype=np.int64)
        if len(valid_chunks) == 1:
            return np.unique(valid_chunks[0])
        return np.unique(np.concatenate(valid_chunks))

    legacy_set = getattr(app, "_pending_main_view_indices", None)
    if legacy_set:
        indices = np.array(list(legacy_set), dtype=np.int64)
        legacy_set.clear()
        return np.unique(indices)

    return np.array([], dtype=np.int64)

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
        # Prefer pre-built global_indices (core-first order, matches points_transformed)
        global_indices = getattr(app, f"_section_{active_view}_global_indices", None)
        points_transformed = getattr(app, f"section_{active_view}_points_transformed", None)
        if global_indices is not None and points_transformed is not None:
            if len(global_indices) == len(points_transformed):
                print(f"📋 Classification mask: PRE-COMPUTED combined (core + buffer)")
                print(f"   Total: {len(global_indices):,} points (transformed)")
                return global_indices, points_transformed

        # Fallback: boolean combined_mask → convert to int array so callers always
        # get an index array in the same order as points_transformed (core-first).
        combined_mask = getattr(app, f"section_{active_view}_combined_mask", None)
        points_transformed = getattr(app, f"section_{active_view}_points_transformed", None)

        if combined_mask is not None and points_transformed is not None:
            # Build core-first index array: core indices first, then buffer indices
            core_mask_fb  = getattr(app, f"section_{active_view}_core_mask",   None)
            buf_mask_fb   = getattr(app, f"section_{active_view}_buffer_mask",  None)
            if core_mask_fb is not None and buf_mask_fb is not None:
                gi = np.concatenate([np.flatnonzero(core_mask_fb),
                                     np.flatnonzero(buf_mask_fb)])
            else:
                gi = np.flatnonzero(combined_mask)  # best-effort scan-order
            if len(gi) == len(points_transformed):
                print(f"📋 Classification mask: PRE-COMPUTED combined (core + buffer)")
                print(f"   Total: {len(gi):,} points (transformed)")
                return gi, points_transformed

        # Last fallback: build from stored masks
        core_mask = getattr(app, f"section_{active_view}_core_mask", None)
        buffer_mask = getattr(app, f"section_{active_view}_buffer_mask", None)

        if core_mask is not None:
            include_buffer = _include_buffer_for_classification(app)

            if include_buffer and buffer_mask is not None:
                core_idx = np.flatnonzero(core_mask)
                buf_idx  = np.flatnonzero(buffer_mask)
                gi = np.concatenate([core_idx, buf_idx])
                print(f"📋 Classification mask: CORE + BUFFER (include_buffer=True)")
                print(f"   Core: {len(core_idx):,}, Buffer: {len(buf_idx):,}")
            else:
                gi = np.flatnonzero(core_mask)
                print(f"📋 Classification mask: CORE ONLY (include_buffer=False)")

            points_transformed = getattr(app, f"section_{active_view}_points_transformed", None)
            if points_transformed is not None and len(gi) == len(points_transformed):
                return gi, points_transformed

            # Absolute last resort: raw xyz (scan-order, but gi is scan-order too)
            section_xyz = app.data["xyz"][np.flatnonzero(core_mask | buffer_mask)
                                          if (include_buffer and buffer_mask is not None)
                                          else np.flatnonzero(core_mask)]
            return gi, section_xyz

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
    # PATH 1: Pre-built global_indices + transformed points (BEST)
    # ─────────────────────────────────────────────────────────
    # CRITICAL: points_transformed is in core-first order (np.vstack of core then
    # buffer). The boolean combined_mask is in scan-order (full-cloud flatnonzero).
    # Using np.flatnonzero(combined_mask)[local_mask] would misalign core-first
    # local_mask against scan-order indices → wrong global points get classified.
    # _section_{v}_global_indices is built by build_section_unified_actor in the
    # same core-first order as points_transformed, so subscripting it with a
    # core-first local_mask gives the correct global indices.
    # ═══════════════════════════════════════════════════════════
    global_indices = getattr(app, f"_section_{active_view}_global_indices", None)
    points_transformed = getattr(app, f"section_{active_view}_points_transformed", None)

    if global_indices is not None and points_transformed is not None:
        if len(global_indices) == len(points_transformed):
            print(f"📋 Using PRE-COMPUTED combined data (core + buffer)")
            print(f"   Total points: {len(global_indices):,} (transformed)")
            return global_indices, points_transformed

    # ═══════════════════════════════════════════════════════════
    # PATH 2: Build core-first index array from stored masks
    # Always return int index array (never boolean) so callers use the
    # correct `else: mask_or_indices[local_mask]` branch.
    # ═══════════════════════════════════════════════════════════
    core_mask = getattr(app, f"section_{active_view}_core_mask", None)
    buffer_mask = getattr(app, f"section_{active_view}_buffer_mask", None)
    include_buffer = _include_buffer_for_classification(app)

    if core_mask is None:
        return (mask, section_points) if (mask is not None and section_points is not None) else (None, None)

    # Build core-first index array
    core_idx = np.flatnonzero(core_mask)
    if include_buffer and buffer_mask is not None:
        buf_idx = np.flatnonzero(buffer_mask)
        gi = np.concatenate([core_idx, buf_idx])
        print(f"📋 Using BUILT combined indices (core + buffer)")
        print(f"   Core: {len(core_idx):,}, Buffer: {len(buf_idx):,}, Total: {len(gi):,}")
    else:
        gi = core_idx
        print(f"📋 Using CORE ONLY (buffer excluded)")
        print(f"   Core: {len(gi):,}")

    # ─── Try pre-stored transformed points first (PREFERRED) ─────────────
    points_transformed = getattr(app, f"section_{active_view}_points_transformed", None)
    if points_transformed is not None and len(gi) == len(points_transformed):
        print(f"   ✅ Using transformed points (pre-computed)")
        return gi, points_transformed

    # ─── Build transformed points from core + buffer parts ───────────────
    core_pts = getattr(app, f"section_{active_view}_core_points", None)
    if include_buffer and buffer_mask is not None:
        buffer_pts = getattr(app, f"section_{active_view}_buffer_points", None)
        if core_pts is not None and buffer_pts is not None:
            section_xyz = np.vstack([core_pts, buffer_pts])
            print(f"   ✅ Using transformed points (built from core + buffer)")
            return gi, section_xyz
        elif core_pts is not None:
            gi = core_idx   # mismatch — fall back to core only
            print(f"   ⚠️ Using transformed core points only")
            return gi, core_pts
    elif core_pts is not None:
        print(f"   ✅ Using transformed core points")
        return gi, core_pts

    # ═══════════════════════════════════════════════════════════
    # SUB-PATH 2B: Build from raw xyz + transform (LAST RESORT)
    # gi is still valid (core-first index array built above)
    # ═══════════════════════════════════════════════════════════
    section_xyz_original = app.data["xyz"][gi]
    P1 = getattr(app, f"section_{active_view}_P1", None)
    P2 = getattr(app, f"section_{active_view}_P2", None)

    if P1 is not None and P2 is not None and hasattr(app, "section_controller"):
        try:
            section_xyz = app.section_controller._transform_to_section_coordinates(section_xyz_original, P1, P2)
            print(f"   ✅ Using computed transform from raw xyz")
            return gi, section_xyz
        except Exception as e:
            print(f"   ⚠️ Transform failed: {e}, using raw xyz")
            return gi, section_xyz_original
    else:
        print(f"   ⚠️ Using raw xyz (no transform available)")
        return gi, section_xyz_original


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

        changed_mask = getattr(app, "_last_changed_mask", None)
        if changed_mask is None or not isinstance(changed_mask, np.ndarray) or not np.any(changed_mask):
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

                for view_idx, vtk_widget in app.section_vtks.items():
                    if vtk_widget is None:
                        continue
                    try:
                        fast_cross_section_update(app, view_idx, changed_mask)
                    except Exception:
                        pass

            except ImportError:
                pass

        return result
 
    return wrapper


def _apply_classification(app, update_mask: np.ndarray, from_classes, to_class: int) -> bool:
    """
    Vectorized classification engine — zero Python loops.

    All filtering, index mapping, and GPU pokes are O(k) NumPy C-layer operations
    where k = number of changed points.  No set(), no range(len()), no list.append().
    """
    if app.data is None or to_class is None:
        return False

    app._gpu_sync_done     = False
    app._last_changed_mask = None

    classes    = app.data["classification"]
    orig_dtype = classes.dtype                   # capture dtype — must not drift

    # ── 1. Candidate indices (vectorized flatnonzero, faster than np.where()[0]) ─
    update_idx = np.flatnonzero(update_mask)
    if update_idx.size == 0:
        return False

    # ── 2. Visibility filter — O(k) vectorized isin, no Python loop ──────
    visible_classes = _get_visible_classes_for_current_view(app)
    if visible_classes is not None:
        update_idx = update_idx[np.isin(classes[update_idx], visible_classes,
                                        assume_unique=False)]

    # ── 3. from_classes filter — O(k) vectorized isin ────────────────────
    if from_classes:
        update_idx = update_idx[np.isin(classes[update_idx], from_classes,
                                        assume_unique=False)]

    if update_idx.size == 0:
        if hasattr(app, "statusBar"):
            app.statusBar().showMessage("No visible/from-class points in selection.", 2500)
        return False

    # ── 4. Undo entry — dtype preserved, no extra allocation ─────────────
    final_bool_mask             = np.zeros(len(classes), dtype=bool)
    final_bool_mask[update_idx] = True
    app.undo_stack.append({
        "mask":        final_bool_mask,
        "old_classes": classes[update_idx].copy(),
        "new_classes": np.full(update_idx.size, to_class, dtype=orig_dtype),
    })
    app.redo_stack.clear()
    # Enforce undo stack size limit immediately — prevents unbounded memory growth
    # during 8+ hour sessions (each entry ≈ 3×N_changed bytes of numpy arrays).
    _max_undo = getattr(app, 'max_undo_steps', 50)
    while len(app.undo_stack) > _max_undo:
        app.undo_stack.pop(0)   # drop oldest; FIFO

    # ── 5. Apply to CPU array — dtype-safe, in-place ─────────────────────
    classes[update_idx] = orig_dtype.type(to_class)
    assert classes.dtype == orig_dtype, (
        f"dtype drift: expected {orig_dtype}, got {classes.dtype}"
    )
    app._last_changed_mask = final_bool_mask
    app._last_from_classes = list(from_classes or [])

    # ── 6. Edit bounding box — computed ONCE for section-view culling ─────
    edit_bb = None
    xyz = app.data.get("xyz")
    if xyz is not None and update_idx.size > 0:
        edit_bb = _edit_bbox(xyz, update_idx)    # O(k) min/max, single NumPy pass

    # ── 7. GPU sync ───────────────────────────────────────────────────────
    try:
        from gui.unified_actor_manager import (
            fast_classify_update,
            fast_cross_section_update,
            is_unified_actor_ready,
        )
        palette = getattr(app, 'class_palette', {})

        # 7a. Main view — targeted RGB poke only on changed points
        if is_unified_actor_ready(app):
            fast_classify_update(app, final_bool_mask, to_class, palette=palette)
            if getattr(app, "display_mode", "class") == "shaded_class":
                try:
                    from gui.shading_display import refresh_shaded_after_classification_fast
                    refresh_shaded_after_classification_fast(app, changed_mask=final_bool_mask)
                except Exception:
                    try:
                        from gui.shading_display import update_shaded_class
                        update_shaded_class(app, force_rebuild=True)
                    except Exception:
                        pass

        # 7b. Section views — bbox-culled, render deferred (skip_render=True)
        #     fast_classify_update already called app.vtk_widget.render() once.
        #     We do NOT render section views a second time here.
        if hasattr(app, 'section_vtks') and app.section_vtks:
            for view_idx in app.section_vtks:
                # Dirty flag: skip section entirely if edit bbox doesn't overlap
                if edit_bb is not None and not _section_bbox_overlaps(app, view_idx, edit_bb):
                    continue
                try:
                    fast_cross_section_update(
                        app, view_idx, final_bool_mask,
                        skip_render=True,            # render batched in step 7e below
                    )
                except Exception:
                    pass

        # 7c. Cut section — vectorized update of BOTH Colors and Classification ID
        if hasattr(app, 'cut_section_controller') and app.cut_section_controller:
            ctrl = app.cut_section_controller
            if getattr(ctrl, 'is_cut_view_active', False) and ctrl._cut_index_map is not None:
                try:
                    target_actor = getattr(ctrl, 'cut_core_actor', None)
                    if target_actor and hasattr(target_actor, 'GetMapper'):
                        _mapper = target_actor.GetMapper()
                        polydata = _mapper.GetInput() if _mapper is not None else None
                        if polydata:
                            # 1. Resolve which palette to use for color lookup (Slot 5)
                            from gui.unified_actor_manager import _get_slot_palette, _push_uniforms_direct
                            view_palette = _get_slot_palette(app, 5)
                            new_color = view_palette.get(to_class, {}).get('color', (128, 128, 128))

                            # 2. Map global indices to cut-local indices
                            cut_map = ctrl._cut_index_map
                            _, _, local_arr = np.intersect1d(
                                update_idx, cut_map,
                                return_indices=True,
                                assume_unique=True,
                            )
                            
                            if local_arr.size > 0:
                                # 3. Update Colors (Scalars)
                                vtk_colors = polydata.GetPointData().GetScalars()
                                if vtk_colors:
                                    vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                                    vtk_ptr[local_arr] = new_color
                                    vtk_colors.Modified()

                                # 4. Update Classification ID (Used by shader for weight lookup)
                                class_arr = polydata.GetPointData().GetArray("Classification")
                                if class_arr:
                                    cls_ptr = numpy_support.vtk_to_numpy(class_arr)
                                    cls_ptr[local_arr] = cls_ptr.dtype.type(to_class)
                                    class_arr.Modified()
                                
                                polydata.Modified()

                                # 5. Sync Uniforms (Ensure weight_lut is fresh)
                                ctx = getattr(target_actor, '_naksha_shader_ctx', None)
                                if ctx:
                                    last_gen = getattr(target_actor, '_last_uniform_gen', -1)
                                    if ctx._generation != last_gen:
                                        ctx.force_reload()
                                        _bsz = float(getattr(app, 'point_size', 2.5))
                                        ctx.load_from_palette(view_palette, 0, _bsz)
                                        _push_uniforms_direct(target_actor, ctx)
                                        target_actor._last_uniform_gen = ctx._generation

                            if hasattr(ctrl, 'cut_vtk') and ctrl.cut_vtk:
                                ctrl.cut_vtk.render()
                except Exception as ce:
                    print(f"   ⚠️ Cut Section GPU sync failed: {ce}")

        # 7d. Section view renders — one pass, bbox-culled, no duplicate calls
        if hasattr(app, 'section_vtks'):
            for view_idx, sw in app.section_vtks.items():
                if sw is None:
                    continue
                if edit_bb is not None and not _section_bbox_overlaps(app, view_idx, edit_bb):
                    continue
                try:
                    sw.render()
                except Exception:
                    pass

        # 7e. Signal GPU sync complete (suppresses decorator double-refresh)
        if getattr(app, "display_mode", "class") != "shaded_class":
            app._gpu_sync_done = True

    except Exception:
        pass    # classification already applied to CPU — do not surface GPU errors

    return True



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
    """Classify points above a drawn line in cross/cut-section views."""
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    if is_cut_section:
        if app.cut_section_controller is None or app.cut_section_controller.cut_points is None:
            return
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)

    if line_pts is None or len(line_pts) < 2:
        return
    if section_points is None or len(section_points) == 0:
        return

    if is_cut_section:
        pts_2d = _project_to_cut_view(app, section_points)
        view_mode = "cut"
    else:
        view_mode = getattr(app, "cross_view_mode", "side")
        pts_2d = _project_to_2d_view(section_points, view_mode)

    viewport_mask = _get_viewport_mask_for_2d(app, pts_2d, is_cut_section, view_mode)
    if viewport_mask is None:
        viewport_mask = np.ones(len(section_points), dtype=bool)

    (x1, z1), (x2, z2) = line_pts
    m = (z2 - z1) / (x2 - x1 + 1e-9)
    b = z1 - m * x1
    xmin, xmax = sorted([x1, x2])

    in_strip = (pts_2d[:, 0] >= xmin) & (pts_2d[:, 0] <= xmax)
    above = pts_2d[:, 1] >= (m * pts_2d[:, 0] + b)
    local_mask = (in_strip & above) & viewport_mask

    visible_classes = _get_visible_classes_for_current_view(app)
    if visible_classes is not None:
        section_indices = mask_or_indices if not (isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool) else np.flatnonzero(mask_or_indices)
        class_mask = np.isin(app.data["classification"][section_indices], visible_classes)
        local_mask = local_mask & class_mask

    if not np.any(local_mask):
        return

    update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
    selected_indices = mask_or_indices[local_mask] if not (isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool) else np.flatnonzero(mask_or_indices)[local_mask]
    update_mask[selected_indices] = True
    _apply_classification(app, update_mask, from_classes, to_class)

@classify_with_stats_update
def classify_below_line(app, line_pts=None, from_classes=None, to_class=None,
                        mask=None, section_points=None, visible_bounds=None):
    """Classify points below a drawn line in cross/cut-section views."""
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")
    if is_cut_section:
        if app.cut_section_controller is None or app.cut_section_controller.cut_points is None:
            return
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)

    if line_pts is None or len(line_pts) < 2:
        return
    if section_points is None or len(section_points) == 0:
        return

    if is_cut_section:
        pts_2d = _project_to_cut_view(app, section_points)
        view_mode = "cut"
    else:
        view_mode = getattr(app, "cross_view_mode", "side")
        pts_2d = _project_to_2d_view(section_points, view_mode)

    viewport_mask = _get_viewport_mask_for_2d(app, pts_2d, is_cut_section, view_mode)
    if viewport_mask is None:
        viewport_mask = np.ones(len(section_points), dtype=bool)

    (x1, z1), (x2, z2) = line_pts
    m = (z2 - z1) / (x2 - x1 + 1e-9)
    b = z1 - m * x1
    xmin, xmax = sorted([x1, x2])

    in_strip = (pts_2d[:, 0] >= xmin) & (pts_2d[:, 0] <= xmax)
    below = pts_2d[:, 1] <= (m * pts_2d[:, 0] + b)
    local_mask = (in_strip & below) & viewport_mask

    visible_classes = _get_visible_classes_for_current_view(app)
    if visible_classes is not None:
        section_indices = mask_or_indices if not (isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool) else np.flatnonzero(mask_or_indices)
        class_mask = np.isin(app.data["classification"][section_indices], visible_classes)
        local_mask = local_mask & class_mask

    if not np.any(local_mask):
        return

    update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
    selected_indices = mask_or_indices[local_mask] if not (isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool) else np.flatnonzero(mask_or_indices)[local_mask]
    update_mask[selected_indices] = True
    _apply_classification(app, update_mask, from_classes, to_class)
    
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

        except Exception:
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
    """Classify rectangle selection."""
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")

    if is_cut_section:
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)

    if rect_bounds is None:
        update_mask = getattr(app, "last_mask", None)
        if update_mask is None:
            return
        return _apply_classification(app, update_mask.copy(), from_classes, to_class)

    if mask_or_indices is None:
        mask_or_indices = np.ones(len(app.data["xyz"]), dtype=bool)

    if section_points is not None:
        if is_cut_section:
            pts_2d = _project_to_cut_view(app, section_points)
        else:
            pts_2d = _project_to_2d_view(section_points, getattr(app, "cross_view_mode", "side"))

        xmin, xmax, ymin, ymax = rect_bounds
        local_mask = (
            (pts_2d[:, 0] >= xmin) & (pts_2d[:, 0] <= xmax) &
            (pts_2d[:, 1] >= ymin) & (pts_2d[:, 1] <= ymax)
        )

        if not np.any(local_mask):
            return

        update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
        selected_indices = mask_or_indices[local_mask] if not (isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool) else np.flatnonzero(mask_or_indices)[local_mask]
        update_mask[selected_indices] = True
        _apply_classification(app, update_mask, from_classes, to_class)


@classify_with_stats_update
def classify_circle(app, center=None, radius=None, from_classes=None, to_class=None,
                    mask=None, section_points=None, visible_bounds=None):
    """Classify circle selection."""
    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")

    if is_cut_section:
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)

    if center is None or radius is None:
        update_mask = getattr(app, "last_mask", None)
        if update_mask is None:
            return
        return _apply_classification(app, update_mask.copy(), from_classes, to_class)

    if mask_or_indices is None:
        mask_or_indices = np.ones(len(app.data["xyz"]), dtype=bool)

    if section_points is not None:
        if is_cut_section:
            pts_2d = _project_to_cut_view(app, section_points)
        else:
            pts_2d = _project_to_2d_view(section_points, getattr(app, "cross_view_mode", "side"))

        cx, cy = center
        local_mask = ((pts_2d[:, 0] - cx) ** 2 + (pts_2d[:, 1] - cy) ** 2) <= radius ** 2

        if not np.any(local_mask):
            return

        update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
        selected_indices = mask_or_indices[local_mask] if not (isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool) else np.flatnonzero(mask_or_indices)[local_mask]
        update_mask[selected_indices] = True
        _apply_classification(app, update_mask, from_classes, to_class)


@classify_with_stats_update
def classify_polygon(app, polygon_xy=None, from_classes=None, to_class=None,
                     mask=None, section_points=None, visible_bounds=None):
    """Classify polygon selection."""
    from matplotlib.path import Path

    is_cut_section = (getattr(app, "active_classify_target", None) == "cut")

    if is_cut_section:
        section_points = app.cut_section_controller.cut_points
        mask_or_indices = app.cut_section_controller._cut_index_map
    else:
        mask_or_indices, section_points = _get_section_data_with_buffer(app, mask, section_points)

    if polygon_xy is None:
        update_mask = getattr(app, "last_mask", None)
        if update_mask is None:
            return
        return _apply_classification(app, update_mask.copy(), from_classes, to_class)

    if mask_or_indices is None:
        mask_or_indices = np.ones(len(app.data["xyz"]), dtype=bool)

    if section_points is not None:
        if is_cut_section:
            pts_2d = _project_to_cut_view(app, section_points)
        else:
            pts_2d = _project_to_2d_view(section_points, getattr(app, "cross_view_mode", "side"))

        path = Path(polygon_xy, closed=True)
        local_mask = path.contains_points(pts_2d)

        if not np.any(local_mask):
            return

        update_mask = np.zeros(len(app.data["xyz"]), dtype=bool)
        selected_indices = mask_or_indices[local_mask] if not (isinstance(mask_or_indices, np.ndarray) and mask_or_indices.dtype == bool) else np.flatnonzero(mask_or_indices)[local_mask]
        update_mask[selected_indices] = True
        _apply_classification(app, update_mask, from_classes, to_class)
    else:
        xyz = app.data["xyz"]
        pts = xyz[mask_or_indices]
        path = Path(polygon_xy, closed=True)
        inside = path.contains_points(pts[:, :2])
        update_mask = np.zeros(len(xyz), dtype=bool)
        update_mask[mask_or_indices] = inside
        _apply_classification(app, update_mask, from_classes, to_class)


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
            section_indices = np.flatnonzero(mask_or_indices)
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


def _fast_update_colors(app, indices: np.ndarray, new_class: int, is_cut_section: bool) -> None:
    """
    Vectorized GPU color poke for brush/drag strokes.

    Key changes vs original:
    - Cross-section actor: O(1) named dict lookup instead of O(n_actors) VTK traversal.
    - All index mapping: vectorized NumPy boolean indexing — zero Python loops.
    - Cut section: np.intersect1d (unchanged, already vectorized).
    - Dirty flag: vtk_colors.Modified() only called when local_idx.size > 0.
    - Main view: no .copy() on append (chunks are consumed once on release).
    """
    indices = np.asarray(indices, dtype=np.int64)
    if indices.size == 0:
        return

    new_rgb = np.asarray(
        app.class_palette.get(new_class, {}).get('color', (128, 128, 128)),
        dtype=np.uint8,
    )

    # ── Cross-section: O(1) named actor lookup — no VTK actor traversal ──
    if not is_cut_section and hasattr(app, 'section_controller'):
        active_view = getattr(app.section_controller, 'active_view', None)
        if active_view is not None and active_view in getattr(app, 'section_vtks', {}):
            vtk_widget  = app.section_vtks[active_view]
            actor_name  = f"_section_{active_view}_unified"
            actor       = vtk_widget.actors.get(actor_name)   # O(1) dict, was O(n_actors)

            if actor is not None:
                mapper   = actor.GetMapper()
                polydata = mapper.GetInput() if mapper else None
                if polydata is not None:
                    vtk_colors = polydata.GetPointData().GetScalars()
                    if vtk_colors is not None:
                        combined_mask = getattr(
                            app, f"section_{active_view}_combined_mask", None
                        )
                        if combined_mask is not None:
                            global_to_local = _get_section_global_to_local_map(
                                app, active_view, combined_mask
                            )
                            num_tuples = vtk_colors.GetNumberOfTuples()

                            # Vectorized bounds gate — O(k) NumPy, no Python loop
                            valid    = (indices >= 0) & (indices < combined_mask.shape[0])
                            cand     = indices[valid]
                            if cand.size > 0:
                                in_sec   = cand[combined_mask[cand]]   # boolean index
                                if in_sec.size > 0:
                                    local_idx = global_to_local[in_sec]
                                    local_idx = local_idx[local_idx < num_tuples]
                                    if local_idx.size > 0:
                                        # Dirty flag: only write + mark when hits exist
                                        vtk_ptr            = numpy_support.vtk_to_numpy(vtk_colors)
                                        vtk_ptr[local_idx] = new_rgb   # vectorized broadcast
                                        vtk_colors.Modified()

            vtk_widget.render()   # single render after all pokes

    # ── Cut section: vectorized intersect1d (unchanged, already correct) ─
    if is_cut_section and hasattr(app, 'cut_section_controller'):
        ctrl = app.cut_section_controller
        if ctrl.is_cut_view_active and ctrl.cut_vtk is not None:
            actor = getattr(ctrl, 'cut_core_actor', None)
            if actor is not None:
                mapper   = actor.GetMapper()
                polydata = mapper.GetInput() if mapper else None
                if polydata is not None:
                    vtk_colors = polydata.GetPointData().GetScalars()
                    if vtk_colors is not None:
                        cut_idx = ctrl._cut_index_map
                        _, _, local_cut = np.intersect1d(
                            indices, cut_idx,
                            return_indices=True, assume_unique=False,
                        )
                        if local_cut.size > 0:
                            # Dirty flag: only write when intersection is non-empty
                            vtk_ptr             = numpy_support.vtk_to_numpy(vtk_colors)
                            vtk_ptr[local_cut]  = new_rgb
                            vtk_colors.Modified()
            ctrl.cut_vtk.render()

    # ── Main view: deferred batch (flushed on mouse-release via clear_brush_cache) ─
    if not hasattr(app, '_pending_main_view_index_chunks') or \
            app._pending_main_view_index_chunks is None:
        app._pending_main_view_index_chunks = []
    app._pending_main_view_index_chunks.append(indices)   # no .copy() — consumed once


def clear_brush_cache(app):
    """Call this when brush drag ends to clear the cache."""
    if hasattr(app, '_brush_cache'):
        del app._brush_cache
    
    # Flush pending main view updates
    indices = _consume_pending_main_view_indices(app)
    if len(indices) > 0:
        try:
            # Update main view in one batch
            if hasattr(app, 'vtk_widget') and hasattr(app.vtk_widget, 'actors'):
                actor = app.vtk_widget.actors.get("main_points_cloud")
                
                if actor is not None:
                    _m = actor.GetMapper()
                    polydata = _m.GetInput() if _m else None
                    vtk_colors = polydata.GetPointData().GetScalars() if polydata else None
                    
                    if vtk_colors is not None:
                        vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                        classes = app.data["classification"][indices].astype(np.int64, copy=False)
                        color_lut = _get_palette_color_lut(app)
                        safe_classes = np.clip(classes, 0, color_lut.shape[0] - 1)
                        vtk_ptr[indices] = color_lut[safe_classes]
                        vtk_colors.Modified()
                        app.vtk_widget.render()
            
            
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
    except Exception:
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

def onclassificationchanged(self, changed_indices=None):
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
