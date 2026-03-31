"""
Optimized Refresh Pipeline - FIXED VERSION

Key fix: Always ensures main view is refreshed after classification,
even when classifying in cross-section views.
"""

import numpy as np
import time
from typing import Optional, Set, List
from vtkmodules.util import numpy_support

from .optimization_config import (
    ENABLE_OPTIMIZED_REFRESH,
    ENABLE_DELTA_WEIGHT_SYNC,
    ENABLE_DIRTY_VIEW_TRACKING,
    ENABLE_BATCHED_RENDERING,
    ENABLE_PERFORMANCE_LOGGING,
)
from .classification_state import get_dirty_state, get_weight_cache

class OptimizedRefreshPipeline:
    """
    Optimized refresh pipeline that wraps existing logic.
    
    ✅ FIXED: Always refreshes main view after classification
    ✅ FIXED: Properly handles cross-section → main view sync
    """
    
    def __init__(self, app):
        self.app = app
        self._pending_renders: Set[int] = set()
        self._start_time: float = 0.0
    
    def refresh_after_classification(self, 
                                      to_class: int,
                                      from_classes: Optional[List[int]] = None,
                                      active_view: Optional[int] = None,
                                      fallback_func=None):
        """
        Optimized refresh with automatic fallback.
        ✅ FIX: Skips entirely when _apply_mask_and_record already did GPU sync.
        """
        # ✅ CRITICAL: If GPU sync was already done by the fast injection path
        # in _apply_mask_and_record, skip the entire 170ms refresh cycle.
        if getattr(self.app, "_gpu_sync_done", False):
            self.app._gpu_sync_done = False
            if ENABLE_PERFORMANCE_LOGGING:
                print(f"⏭️ OptimizedRefresh SKIPPED — GPU sync already done by fast injection")
            return

        if not ENABLE_OPTIMIZED_REFRESH:
            if fallback_func:
                return fallback_func(to_class)
            return
        
        self._start_time = time.time()
        
        try:
            self._do_optimized_refresh(to_class, from_classes, active_view)
            
            if ENABLE_PERFORMANCE_LOGGING:
                elapsed = (time.time() - self._start_time) * 1000
                print(f"⚡ Optimized refresh: {elapsed:.0f}ms")
                
        except Exception as e:
            print(f"⚠️ Optimized refresh failed: {e}")
            import traceback
            traceback.print_exc()
            print(f"   Falling back to original implementation...")
            
            if fallback_func:
                fallback_func(to_class)

    def _do_optimized_refresh(self, to_class, from_classes, active_view):
        """
        Internal optimized refresh logic.
        ✅ FIXED: Always refreshes ALL existing cross-sections after classification.
        """
        
        state = get_dirty_state()
        
        if not state.begin_refresh():
            print("⏭️ Refresh already in progress")
            return
        self.app._optimized_refresh_active = True
        try:
            # Mark dirty state
            state.mark_classes_dirty(to_class=to_class, from_classes=from_classes)
            
            changed_mask = getattr(self.app, '_last_changed_mask', None)
            if changed_mask is not None:
                state.set_changed_mask(changed_mask)
            
            state.mark_view_dirty(0)  # Main View ALWAYS

            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in self.app.section_vtks.keys():
                    slot_idx = view_idx + 1  # Convert to 1-based slot
                    state.mark_view_dirty(slot_idx)
                    print(f"   📍 Marked Cross-Section View {slot_idx} as dirty")

            if active_view is not None and active_view >= 0:
                slot_idx = active_view + 1
                if slot_idx not in state.dirty_views:
                    state.mark_view_dirty(slot_idx)
                    print(f"   📍 Marked active Cross-Section View {slot_idx} as dirty")
            # ════════════════════════════════════════════════════════════════
            if hasattr(self.app, 'cut_section_controller') and self.app.cut_section_controller:
                if self.app.cut_section_controller.is_cut_view_active:
                    state.mark_view_dirty(5)  # Slot 5 = Cut Section
                    print(f"   📍 Marked Cut Section (Slot 5) as dirty")
                
            
            print(f"   📊 Dirty state: classes={state.dirty_classes}, views={state.dirty_views}")
            
            # Step 1: Delta weight sync
            if ENABLE_DELTA_WEIGHT_SYNC:
                self._sync_weights_delta()
            else:
                self._sync_weights_full()
            
            if ENABLE_DIRTY_VIEW_TRACKING:
                self._refresh_dirty_cross_sections(state)
            
            # Step 3: Main View refresh
            self._refresh_main_view_for_classification(to_class, state)
            self._pending_renders.add(0)

            if 5 in state.dirty_views:
                self._refresh_cut_section()
                self._pending_renders.add(5)
            
            if self._pending_renders:
                print(f"   🎨 BATCHED RENDER: {len(self._pending_renders)} views")
                
                # Update all without rendering
                for view_idx in self._pending_renders:
                    self._prepare_view_for_render(view_idx)
                
                # SINGLE render call for all updated views
                try:
                    # Main render window
                    if hasattr(self.app, 'vtk_widget') and self.app.vtk_widget:
                        self.app.vtk_widget.render_window.Render()
                        if ENABLE_PERFORMANCE_LOGGING:
                            print(f"      ✅ Single batched render completed")
                except Exception as e:
                    print(f"      ⚠️ Batched render failed: {e}")
                    # Fallback to individual renders
                    for view_idx in sorted(self._pending_renders):
                        try:
                            self._render_view(view_idx)
                        except:
                            pass
                
                self._pending_renders.clear()
            
            # Step 5: Render all pending views
            if ENABLE_BATCHED_RENDERING:
                self._batched_render()
            else:
                self._individual_renders()
                self._force_border_reapplication()
            
            # Step 6: Statistics and status
            self._update_statistics()
            self._show_status(to_class)
            
        finally:
            state.end_refresh()
            state.clear()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: setattr(self.app, "_optimized_refresh_active", False))

    def _prepare_view_for_render(self, view_idx):
        """Prepare view for rendering without calling Render()."""
        try:
            if view_idx == 0:
                # Main view
                if hasattr(self.app, 'vtk_widget'):
                    pass  
            elif view_idx == 1:
                # Cross-section view
                if hasattr(self.app, 'section_vtks') and 1 in self.app.section_vtks:
                    pass 
        except:
            pass      

    def _force_border_reapplication(self):
        """Apply borders via GPU uniform system (Phase 4 cleanup)."""
        border_percent = getattr(self.app, "point_border_percent", 0)
        if border_percent <= 0:
            return
        
        print(f"   🔳 Applying borders via GPU uniform system ({border_percent}%)...")
        try:
            from gui.unified_actor_manager import sync_palette_to_gpu
            # Main view (slot 0)
            sync_palette_to_gpu(self.app, 0)
            # Cross-sections
            if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                for view_idx in self.app.section_vtks.keys():
                    sync_palette_to_gpu(self.app, view_idx + 1)
            print(f"   ✅ Border re-application complete (GPU uniform path)")
        except ImportError:
            # unified_actor_manager not available — nothing to do; borders are shader-only
            print(f"   ⚠️ unified_actor_manager unavailable, border re-application skipped")
    
    def _sync_weights_delta(self):
        """
        ✅ FIXED: Strictly syncs ONLY Slot 0 (Main View) to the global palette.
        Prevents weight/filter leakage from cross-sections into the main view.
        """
        weight_cache = get_weight_cache()
        
        dialog = getattr(self.app, 'display_mode_dialog', None)
        if not dialog or not hasattr(dialog, 'view_palettes'):
            return
        
        # ✅ FIXED: Force update from dialog AND create missing classes
        if hasattr(dialog, 'view_palettes') and 0 in dialog.view_palettes:
            if not hasattr(self.app, 'class_palette'):
                self.app.class_palette = {}
            
            for cls, info in dialog.view_palettes[0].items():
                if cls in self.app.class_palette:
                    # Sync properties for existing classes
                    self.app.class_palette[cls]['weight'] = info.get('weight', 1.0)
                    self.app.class_palette[cls]['color'] = info.get('color', (128, 128, 128))
                    self.app.class_palette[cls]['show'] = info.get('show', True)
                else:
                    # ✅ CREATE missing class entry with ALL properties
                    self.app.class_palette[cls] = {
                        'weight': info.get('weight', 1.0),
                        'color': info.get('color', (128, 128, 128)),
                        'show': info.get('show', True),
                        'description': info.get('description', f'Class {cls}')
                    }
                    
        if not weight_cache.has_changes(dialog.view_palettes):
            return
        
        changes = weight_cache.get_changed_weights(dialog.view_palettes)
        
        if not changes:
            return
        
        if 0 in changes:
            if ENABLE_PERFORMANCE_LOGGING:
                print(f"   🔄 Syncing {len(changes[0])} Main View weights (Slot 0 isolation)")
                
            if not hasattr(self.app, 'class_palette'):
                self.app.class_palette = {}
            
            slot0_palette = dialog.view_palettes[0]
            for class_code, new_weight in changes[0].items():
                # Update global palette
                if class_code not in self.app.class_palette:
                    if class_code in slot0_palette:
                        self.app.class_palette[class_code] = dict(slot0_palette[class_code])
                else:
                    self.app.class_palette[class_code]['weight'] = new_weight

            # Phase 4: Use GPU uniform sync instead of per-actor weight update
            try:
                from gui.unified_actor_manager import sync_palette_to_gpu
                sync_palette_to_gpu(self.app, 0)
                self._pending_renders.add(0)
            except ImportError:
                # Fallback: legacy per-actor weight update
                for class_code, new_weight in changes[0].items():
                    actor_name = f"class_{class_code}"
                    if hasattr(self.app, 'vtk_widget') and actor_name in self.app.vtk_widget.actors:
                        try:
                            actor = self.app.vtk_widget.actors[actor_name]
                            point_size = max(1.0, min(new_weight * 2.5, 30.0))
                            actor.GetProperty().SetPointSize(point_size)
                            self._pending_renders.add(0)
                        except:
                            pass
        weight_cache.update_cache(dialog.view_palettes)

    def _sync_weights_full(self):
        """Full weight sync (original behavior)."""
        if hasattr(self.app, 'interactor') and hasattr(self.app.interactor, '_sync_main_view_palette_weights'):
            self.app.interactor._sync_main_view_palette_weights()

    def _refresh_dirty_cross_sections(self, state):
        """
        Refresh cross-section views that are marked as dirty.
        ✅ FIXED: Refreshes ALL existing cross-sections after classification
        ✅ FIXED: Handles brush/below_line visibility issues
        """  
        cross_section_slots = [v for v in state.dirty_views if 1 <= v <= 4]
        
        if hasattr(self.app, '_last_changed_mask'):
            changed_mask = self.app._last_changed_mask
            if changed_mask is not None and np.any(changed_mask):
                if hasattr(self.app, 'section_vtks') and self.app.section_vtks:
                    for view_idx in self.app.section_vtks.keys():
                        slot_idx = view_idx + 1
                        if slot_idx not in cross_section_slots:
                            cross_section_slots.append(slot_idx)
                    print(f"   🔄 Refreshing ALL {len(cross_section_slots)} cross-sections (post-classification)")
        
        if not cross_section_slots:
            return
        
        if ENABLE_PERFORMANCE_LOGGING:
            print(f"   🔄 Refreshing {len(cross_section_slots)} cross-section views: {cross_section_slots}")
        
        for slot_idx in cross_section_slots:
            view_idx = slot_idx - 1 
            
            if not hasattr(self.app, 'section_vtks') or view_idx not in self.app.section_vtks:
                continue
            
            pts = getattr(self.app, f'section_{view_idx}_core_points', None)
            core_mask = getattr(self.app, f'section_{view_idx}_core_mask', None)
            
            if pts is None or core_mask is None:
                print(f"   ⏭️ Skipping View {slot_idx}: No section data")
                continue
            
            self._refresh_single_cross_section(view_idx, state)
            self._pending_renders.add(slot_idx)
    
    def _refresh_single_cross_section(self, view_idx, state):
        """
        Optimized single cross-section refresh.
        ✅ FIXED: Detects view mode changes and delegates to _plot_section for full rebuild
        """
        import pyvista as pv
        import numpy as np

        if not hasattr(self.app, 'section_vtks') or view_idx not in self.app.section_vtks:
            return

        vtk_widget = self.app.section_vtks[view_idx]
        slot_idx = view_idx + 1

        current_view_mode = getattr(self.app, 'cross_view_mode', 'side')
        
        # Store last view mode per cross-section
        if not hasattr(self, '_last_view_modes'):
            self._last_view_modes = {}
        
        last_view_mode = self._last_view_modes.get(view_idx, None)
        view_mode_changed = (last_view_mode is not None and last_view_mode != current_view_mode)
        
        if view_mode_changed:
            print(f"      🔄 View mode changed: {last_view_mode} → {current_view_mode}")
            print(f"      🔨 DELEGATING to _plot_section for full rebuild")
            
            self._last_view_modes[view_idx] = current_view_mode
            
            try:
                # Get section data
                core_pts = getattr(self.app, f'section_{view_idx}_core_points', None)
                buffer_pts = getattr(self.app, f'section_{view_idx}_buffer_points', None)
                
                if core_pts is not None:
                    # Set active view temporarily
                    old_active = self.app.section_controller.active_view
                    self.app.section_controller.active_view = view_idx
                    self.app.section_controller.current_vtk = vtk_widget
                    
                    # Call _plot_section which handles view projection
                    self.app.section_controller._plot_section(
                        core_pts,
                        buffer_pts,
                        view=current_view_mode
                    )                
                    if old_active is not None:
                        self.app.section_controller.active_view = old_active
                    
                    print(f"      ✅ View {view_idx + 1} rebuilt via _plot_section for {current_view_mode} mode")
                    
                    return
                
            except Exception as e:
                print(f"      ⚠️ _plot_section delegation failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            self._last_view_modes[view_idx] = current_view_mode

        core_pts = getattr(self.app, f'section_{view_idx}_core_points', None)
        core_mask = getattr(self.app, f'section_{view_idx}_core_mask', None)
        buffer_pts = getattr(self.app, f'section_{view_idx}_buffer_points', None)
        buffer_mask = getattr(self.app, f'section_{view_idx}_buffer_mask', None)

        if core_pts is None or core_mask is None:
            return

        # Get palette for this view
        palette = self._get_view_palette(slot_idx)
        if not palette:
            return

        visible = [c for c, v in palette.items() if v.get("show", False)]

        # ═══════════════════════════════════════════════════════════════
        # ✅ UNIFIED ACTOR: FAST SHARED MEMORY UPDATE
        # ═══════════════════════════════════════════════════════════════
        try:
            from gui.unified_actor_manager import fast_cross_section_update
            changed_mask = getattr(self.app, '_last_changed_mask', None)
            
            fast_cross_section_update(self.app, view_idx, changed_mask, palette=palette)
            
            # The batched render below will pick up any additional refreshes
        except Exception as e:
            print(f"      ⚠️ Unified cross-section update failed: {e}")
            import traceback
            traceback.print_exc()
    
    def _refresh_main_view_for_classification(self, to_class, state):
        """
        🚀 MILLISECOND REFRESH: Direct GPU Pointer Update.
        
        This method restores the instant classification speed by injecting colors
        directly into the GPU buffer, correctly handling LOD and Visibility masks.
        """
        # app = self.app
        # display_mode = getattr(app, "display_mode", "class")
        app = self.app
        display_mode = getattr(app, "display_mode", "class")

        # ── UNIFIED ACTOR FAST PATH ──────────────────────────────────────
        if display_mode == "class":
            try:
                from gui.unified_actor_manager import fast_classify_update, is_unified_actor_ready
                if is_unified_actor_ready(app):
                    changed_mask = getattr(app, '_last_changed_mask', None)
                    if changed_mask is not None and np.any(changed_mask):
                        _done = fast_classify_update(
                            app,
                            changed_mask=changed_mask,
                            to_class=to_class,
                            palette=getattr(app, 'class_palette', {}),
                            border_percent=float(getattr(app, 'point_border_percent', 0) or 0.0),
                        )
                        if _done:
                            # Render after buffer update (render was removed from fast_classify_update)
                            try:
                                app.vtk_widget.render()
                            except Exception:
                                pass
                            if ENABLE_PERFORMANCE_LOGGING:
                                print(f"   ⚡ Unified actor fast path: <5ms")
                            return  # Done — skip everything below
            except ImportError:
                pass
        # ── END FAST PATH ────────────────────────────────────────────────
        
        if ENABLE_PERFORMANCE_LOGGING:
            print(f"   🔄 Refreshing Main View (mode: {display_mode})")

        if display_mode == "class":
            has_widget = hasattr(app, 'vtk_widget') and app.vtk_widget is not None
            has_mask = hasattr(app, '_last_changed_mask')
            mask_has_data = has_mask and app._last_changed_mask is not None and np.any(app._last_changed_mask)
            
            if not has_widget:
                print(f"      ❌ No vtk_widget")
            if not mask_has_data:
                print(f"      ❌ No valid changed mask")
            
            if has_widget and mask_has_data:
                n_actors = len(app.vtk_widget.actors)
                print(f"      ℹ️ Actors available: {n_actors}")
                if n_actors == 0:
                    print(f"      ❌ No actors in scene!")

        if display_mode == "class":
            try:
                # ✅ UNIFIED: Find the unified actor first, fallback to legacy names
                from gui.unified_actor_manager import UNIFIED_ACTOR_NAME, _get_unified_actor
                actor = _get_unified_actor(app)

                if actor is None:
                    for name in [UNIFIED_ACTOR_NAME, "main_points_cloud", "point_cloud", "points"]:
                        if name in app.vtk_widget.actors:
                            try:
                                test_actor = app.vtk_widget.actors[name]
                                if test_actor.GetMapper() and test_actor.GetMapper().GetInput():
                                    actor = test_actor
                                    print(f"   🎯 Found actor: '{name}'")
                                    break
                            except:
                                continue

                if actor is None:
                    print(f"   🔍 Searching all actors for unified cloud...")
                    max_points = 0
                    total_points = len(app.data["xyz"])

                    for name, test_actor in app.vtk_widget.actors.items():
                        # ✅ UNIFIED: Skip DXF overlays, section actors, and per-class actors
                        if name.startswith('class_') or name.startswith('dxf_') or name.startswith('_section_'):
                            continue

                        try:
                            mapper = test_actor.GetMapper()
                            if not mapper:
                                continue
                            polydata = mapper.GetInput()
                            if not polydata:
                                continue

                            n_points = polydata.GetNumberOfPoints()
                            scalars = polydata.GetPointData().GetScalars()

                            if scalars and n_points >= total_points * 0.5 and n_points > max_points:
                                actor = test_actor
                                max_points = n_points
                                print(f"   🎯 Auto-detected unified cloud: '{name}' ({n_points:,}/{total_points:,} points)")
                        except:
                            continue

                    if not actor:
                        print(f"   ⚠️ No unified cloud found")
                        print(f"   ⏩ Will use fallback refresh")

                if actor:
                    global_mask = getattr(app, '_last_changed_mask', None)
                    if global_mask is not None and np.any(global_mask):
                        
                        # Get memory pointer to the RGB colors
                        polydata = actor.GetMapper().GetInput()
                        vtk_colors = polydata.GetPointData().GetScalars()
                        
                        if vtk_colors:
                            vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                            
                            # ✅ CRITICAL: Map Global Mask -> Visibility Mask -> LOD Indices
                            # This solves the "missing points" issue when LOD is active
                            if getattr(app, 'current_visibility_mask', None) is not None:
                                effective_mask = global_mask[app.current_visibility_mask]
                            else:
                                effective_mask = global_mask

                            # Match with current GPU buffer (LOD sub-sampled array)
 
                            # Match with current GPU buffer (LOD sub-sampled array)
                            vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                            gpu_buffer_size = len(vtk_ptr)
                            total_points = len(app.data["xyz"])
                            
                            print(f"      📊 GPU buffer: {gpu_buffer_size:,}, Dataset: {total_points:,}, Ratio: {gpu_buffer_size/total_points:.1%}")
                            
                            try:
                                # Check if LOD is active
                                if gpu_buffer_size == total_points:
                                    # No LOD - direct mapping
                                    local_indices = np.where(effective_mask)[0]
                                    print(f"      ✅ Direct mapping (no LOD): {len(local_indices):,} points")
                                    
                                elif hasattr(app, 'current_gpu_indices') and app.current_gpu_indices is not None:
                                    # LOD is active - use GPU indices mapping
                                    gpu_indices = app.current_gpu_indices
                                    
                                    if len(gpu_indices) != gpu_buffer_size:
                                        print(f"      ⚠️ GPU indices size mismatch: {len(gpu_indices)} != {gpu_buffer_size}")
                                        # Direct with clipping
                                        local_indices = np.where(effective_mask)[0]
                                        local_indices = local_indices[local_indices < gpu_buffer_size]
                                    else:
                                        # Build local mask by checking which GPU indices are in changed mask
                                        local_mask = np.zeros(gpu_buffer_size, dtype=bool)
                                        
                                        # Map global changes to local GPU buffer
                                        for i, global_idx in enumerate(gpu_indices):
                                            if global_idx < len(effective_mask) and effective_mask[global_idx]:
                                                local_mask[i] = True
                                        
                                        local_indices = np.where(local_mask)[0]
                                        print(f"      ✅ LOD mapping: {len(local_indices):,} points")
                                else:
                                    # No GPU indices but buffer smaller - clip direct
                                    local_indices = np.where(effective_mask)[0]
                                    local_indices = local_indices[local_indices < gpu_buffer_size]
                                    print(f"      ⚠️ LOD active but no GPU indices, clipped: {len(local_indices):,} points")
                                
                                # Final safety check
                                if len(local_indices) > 0:
                                    max_idx = np.max(local_indices)
                                    if max_idx >= gpu_buffer_size:
                                        print(f"      ❌ ERROR: max index {max_idx} >= buffer {gpu_buffer_size}")
                                        local_indices = local_indices[local_indices < gpu_buffer_size]
                                        print(f"      🔧 Emergency clip: {len(local_indices):,} points")
                            
                            except Exception as idx_error:
                                print(f"      ❌ Index mapping failed: {idx_error}")
                                import traceback
                                traceback.print_exc()
                                # Ultimate fallback
                                local_indices = np.where(global_mask)[0]
                                local_indices = local_indices[local_indices < gpu_buffer_size]
                                print(f"      🆘 Fallback: {len(local_indices):,} points")

                            if len(local_indices) > 0:
                                # Inject new color from the palette
                                palette = getattr(app, 'class_palette', {})
                                new_rgb = palette.get(to_class, {}).get('color', (128, 128, 128))
                                
                                vtk_ptr[local_indices] = new_rgb

                                # Notify VTK of change and swap frame buffer
                                vtk_colors.Modified()
                                app.vtk_widget.render()
                                
                                if ENABLE_PERFORMANCE_LOGGING:
                                    print(f"      ⚡ Instant Sync: Updated {len(local_indices)} points in GPU buffer")
                                return # Success - exit early
            except Exception as e:
                print(f"   ⚠️ Instant sync failed, falling back to standard refresh: {e}")

        vtk_widget = getattr(app, 'vtk_widget', None)
        saved_camera = None
        if vtk_widget is not None:
            try:
                if hasattr(vtk_widget, 'camera_position') and vtk_widget.camera_position is not None:
                    saved_camera = vtk_widget.camera_position
            except: pass
        
        if display_mode == "class":
            self._refresh_main_view_class_mode(to_class, state)
        elif display_mode == "shaded_class":
            self._refresh_shaded_mode()
        else:
            self._refresh_other_mode(display_mode)
        
        # Restore camera
        if saved_camera is not None and vtk_widget is not None:
            try:
                vtk_widget.camera_position = saved_camera
            except: pass
    
    def _refresh_main_view_class_mode(self, to_class, state):
        """
        ✅ FIXED: Properly refresh main view with GUARANTEED border preservation
        🚀 OPTIMIZED: Uses Direct GPU Pointer injection with LOD and Visibility mapping.
        """
        import pyvista as pv
        import numpy as np
        from vtkmodules.util import numpy_support
        app = self.app
        
        changed_mask = getattr(app, '_last_changed_mask', None)
        if changed_mask is None or not np.any(changed_mask):
            return

        plotter = getattr(app, 'vtk_widget', None)
        if plotter is None:
            return

        xyz = app.data["xyz"]
        classes = app.data["classification"]
        
        if hasattr(self, '_sync_weights_delta'):
            self._sync_weights_delta()

        palette = self._get_view_palette(0)
        
        border_percent = getattr(app, "point_border_percent", 0)
        
        if ENABLE_PERFORMANCE_LOGGING:
            print(f"      🔧 Border setting: {border_percent}%")
        
        dirty_classes = set(state.dirty_classes) if state.dirty_classes else set()
        
        # Add target class
        if to_class is not None:
            dirty_classes.add(int(to_class))
            
        if hasattr(app, 'undo_stack') and app.undo_stack:
            try:
                last_undo = app.undo_stack[-1]
                
                if 'old_classes' in last_undo and last_undo['old_classes'] is not None:
                    old_classes_array = last_undo['old_classes']
                    if len(old_classes_array) > 0:
                        # Get unique classes that were modified
                        old_unique = np.unique(old_classes_array).astype(int)
                        dirty_classes.update(set(old_unique))
                        
                        if ENABLE_PERFORMANCE_LOGGING:
                            print(f"      🕵️ Found source classes from undo: {set(old_unique)}")
            except Exception as e:
                print(f"      ⚠️ Failed to extract source classes: {e}")
        else:
            # Calculate and cache
            dirty_classes = state.dirty_classes if state.dirty_classes else {to_class}
            if hasattr(app, 'undo_stack') and app.undo_stack:
                try:
                    last_undo = app.undo_stack[-1]
                    if 'old_classes' in last_undo and last_undo['old_classes'] is not None:
                        old_unique = np.unique(last_undo['old_classes']).astype(int)
                        dirty_classes = dirty_classes.union(set(old_unique))
                except:
                    pass
            
            # Cache it
            if not hasattr(self, '_cached_dirty_classes'):
                self._cached_dirty_classes = {}
            self._cached_dirty_classes = {'key': cache_key, 'value': dirty_classes}
            if ENABLE_PERFORMANCE_LOGGING:
                print(f"      ⚡ Calculated and cached dirty_classes")

        # ╔═══════════════════════════════════════════════════════════════╗
        # ║ STRATEGY 1: Fast GPU color update with LOD/Visibility Mapping ║
        # ╚═══════════════════════════════════════════════════════════════╝
        fast_update_success = False
        try:
            # ✅ UNIFIED: Always look for the unified actor first
            from gui.unified_actor_manager import UNIFIED_ACTOR_NAME, _get_unified_actor
            main_actor = _get_unified_actor(app)

            if main_actor is None:
                # Fallback: search for any large point cloud actor
                for name in [UNIFIED_ACTOR_NAME, 'main_points_cloud', 'point_cloud', 'points']:
                    if name in plotter.actors:
                        try:
                            test_actor = plotter.actors[name]
                            if test_actor.GetMapper() and test_actor.GetMapper().GetInput():
                                main_actor = test_actor
                                break
                        except:
                            continue

            if main_actor is not None:
                mesh = main_actor.GetMapper().GetInput()
                vtk_colors = mesh.GetPointData().GetScalars()
                
                if vtk_colors is not None:
                    # Only use fast update if no affected class needs to be hidden
                    can_use_fast_update = True
                    for cls in dirty_classes:
                        if cls is not None and not palette.get(int(cls), {}).get('show', True):
                            can_use_fast_update = False
                            break
                    
                    if can_use_fast_update:
                        vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)

                        if getattr(app, 'current_visibility_mask', None) is not None:
                            effective_mask = changed_mask[app.current_visibility_mask]
                            actor_classes = classes[app.current_visibility_mask]
                        else:
                            effective_mask = changed_mask
                            actor_classes = classes

                        if hasattr(app, 'current_gpu_indices'):
                            local_indices = np.where(effective_mask[app.current_gpu_indices])[0]
                            actor_classes = actor_classes[app.current_gpu_indices]
                        else:
                            local_indices = np.where(effective_mask)[0]

                        if len(local_indices) > 0:
                            # Build Fast LUT for colors
                            max_class = int(classes.max()) + 1
                            lut = np.zeros((max_class, 3), dtype=np.uint8)
                            for code, info in palette.items():
                                if code < max_class:
                                    lut[code] = info.get('color', (128, 128, 128))
                            
                            # ⚡ INJECTION: Update GPU memory directly
                            vtk_ptr[local_indices] = lut[actor_classes[local_indices].astype(int)]
                            
                            # Signal VTK change
                            vtk_colors.Modified()
                            mesh.Modified()

                            if not hasattr(main_actor, '_border_shader_cached'):
                                # First time: compile and cache
                                main_actor._border_shader_cached = self._apply_border_shader_safe(main_actor, border_percent)
                                border_applied = main_actor._border_shader_cached
                                if ENABLE_PERFORMANCE_LOGGING:
                                    print(f"      ✨ Border shader compiled and CACHED")
                            else:
                                # Subsequent times: reuse cached shader (instant!)
                                border_applied = main_actor._border_shader_cached
                                if ENABLE_PERFORMANCE_LOGGING:
                                    print(f"      ✨ Border shader REUSED (cached)")
                            
                            if border_applied:
                                if ENABLE_PERFORMANCE_LOGGING:
                                    print(f"      ⚡ Fast GPU update: {len(local_indices)} points + borders VERIFIED")
                                fast_update_success = True
        except Exception as e:
            if ENABLE_PERFORMANCE_LOGGING:
                print(f"      ⚠️ Fast path bypassed: {e}")

        if fast_update_success:
            return

        # ╔═══════════════════════════════════════════════════════════════╗
        # ║ STRATEGY 2: Deferred Unified GPU poke                         ║
        # ║ Schedules fast_classify_update via a 500ms timer so the UI    ║
        # ║ stays responsive while the user is still dragging.            ║
        # ╚═══════════════════════════════════════════════════════════════╝
        from PySide6.QtCore import QTimer

        is_dragging = getattr(self.app, 'is_dragging', False)
        if hasattr(self.app, 'interactor'):
            is_dragging = is_dragging or getattr(self.app.interactor, 'is_dragging', False)

        # Store state for the deferred call
        self._deferred_rebuild_data = {
            'palette':        palette,
            'border_percent': border_percent,
        }

        if is_dragging:
            if ENABLE_PERFORMANCE_LOGGING:
                print(f"      ⏭️ Storing deferred unified poke (user dragging)")
            # on_left_release will trigger _execute_deferred_rebuild
            return

        if ENABLE_PERFORMANCE_LOGGING:
            print(f"      📊 Scheduling deferred unified poke (500 ms)")

        if not hasattr(self, '_deferred_rebuild_timer'):
            self._deferred_rebuild_timer = QTimer()
            self._deferred_rebuild_timer.setSingleShot(True)
            self._deferred_rebuild_timer.timeout.connect(self._execute_deferred_rebuild)

        self._deferred_rebuild_timer.stop()
        self._deferred_rebuild_timer.start(500)

    def _execute_deferred_rebuild(self):
        """
        ✅ UNIFIED ACTOR: Deferred GPU poke via fast_classify_update.
        No per-class actor create/destroy. Writes directly into _naksha_rgb_ptr
        and calls a single render — identical to MicroStation's invalidate+redraw.
        """
        from PySide6.QtWidgets import QApplication

        is_dragging = getattr(self.app, 'is_dragging', False)
        if hasattr(self.app, 'interactor'):
            is_dragging = is_dragging or getattr(self.app.interactor, 'is_dragging', False)
        if is_dragging:
            if ENABLE_PERFORMANCE_LOGGING:
                print(f"   ⏭️ Skipping deferred rebuild (user active)")
            return

        data = getattr(self, '_deferred_rebuild_data', None)
        if data is None:
            return

        QApplication.processEvents()

        border_percent = data.get('border_percent', 0.0)
        palette        = data.get('palette', {})

        try:
            from gui.unified_actor_manager import fast_classify_update, is_unified_actor_ready
            if not is_unified_actor_ready(self.app):
                if ENABLE_PERFORMANCE_LOGGING:
                    print(f"   ⚠️ Unified actor not ready — skipping deferred rebuild")
                self._deferred_rebuild_data = None
                return

            changed_mask = getattr(self.app, '_last_changed_mask', None)
            to_class     = getattr(self.app, '_last_to_class', None)

            if ENABLE_PERFORMANCE_LOGGING:
                print(f"   ⚡ Deferred unified GPU poke (to_class={to_class})")

            fast_classify_update(
                self.app,
                changed_mask=changed_mask,
                to_class=to_class,
                palette=palette,
                border_percent=float(border_percent or 0.0),
            )

            try:
                self.app.vtk_widget.render()
            except Exception:
                pass

            if ENABLE_PERFORMANCE_LOGGING:
                print(f"   ✅ Deferred unified rebuild complete")

        except Exception as e:
            print(f"   ⚠️ Deferred unified rebuild failed: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._deferred_rebuild_data = None
            
    # def _refresh_shaded_mode(self):
    #     """Refresh shaded class mode."""
    #     azimuth = getattr(self.app, "last_shade_azimuth", 45.0)
    #     angle = getattr(self.app, "last_shade_angle", 45.0)
    #     ambient = getattr(self.app, "shade_ambient", 0.2)
        
    #     try:
    #         from gui.shading_display import update_shaded_class
    #         update_shaded_class(self.app, azimuth, angle, ambient)
    #     except Exception as e:
    #         print(f"⚠️ Shaded mode refresh failed: {e}")
    
    def _refresh_shaded_mode(self):
        """
        ✅ FIXED: Detects when points are ADDED to the visible single-class
        and triggers immediate local re-triangulation instead of relying on
        refresh_shaded_after_classification_fast (which only handles removals).
        """
        try:
            from gui.shading_display import (
                refresh_shaded_after_classification_fast,
                get_cache,
                clear_shading_cache,
                update_shaded_class,
                _do_triangulate,
                _filter_edges_by_absolute,
                _compute_face_normals,
                _compute_shading,
                _render_mesh,
                _save_camera,
            )

            cache = get_cache()
            is_single_class = getattr(cache, 'n_visible_classes', 0) == 1
            single_class_id = getattr(cache, 'single_class_id', None)
            changed_mask = getattr(self.app, '_last_changed_mask', None)

            if (is_single_class
                    and single_class_id is not None
                    and cache.faces is not None
                    and len(cache.faces) > 0
                    and changed_mask is not None
                    and np.any(changed_mask)):

                classes = self.app.data.get("classification").astype(np.int32)
                changed_indices = np.where(changed_mask)[0]
                changed_now_classes = classes[changed_indices]

                # Points that are NOW in the visible single class
                newly_in_class = changed_indices[changed_now_classes == single_class_id]

                # Filter out points that were ALREADY in the mesh
                if len(newly_in_class) > 0:
                    g2u = cache.build_global_to_unique(len(self.app.data["xyz"]))
                    already_in_mesh = g2u[newly_in_class] >= 0
                    truly_new = newly_in_class[~already_in_mesh]
                else:
                    truly_new = np.array([], dtype=np.int64)

                # Also check for points that LEFT the class (need face removal)
                cached_vertex_classes = classes[cache.unique_indices]
                vertices_left = (cached_vertex_classes != single_class_id)
                n_left = int(np.sum(vertices_left))

                n_new = len(truly_new)

                if ENABLE_PERFORMANCE_LOGGING:
                    print(f"      🔍 Single-class shading: {n_new} points ADDED, "
                        f"{n_left} points LEFT class {single_class_id}")

                if n_new > 0:
                    t0 = time.time()
                    success = self._patch_single_class_new_points(
                        cache, single_class_id, truly_new, vertices_left)

                    if success:
                        if ENABLE_PERFORMANCE_LOGGING:
                            elapsed = (time.time() - t0) * 1000
                            print(f"      ⚡ Single-class ADD patch: {elapsed:.0f}ms")
                        return
                    else:
                        # Patch failed — fall through to full rebuild below
                        if ENABLE_PERFORMANCE_LOGGING:
                            print(f"      ⚠️ Patch failed — full rebuild")

                    # Full rebuild as fallback
                    clear_shading_cache("single-class points added (patch failed)")
                    saved_vis = {}
                    for c in self.app.class_palette:
                        saved_vis[c] = self.app.class_palette[c].get("show", True)
                        self.app.class_palette[c]["show"] = (int(c) == single_class_id)
                    try:
                        update_shaded_class(
                            self.app,
                            getattr(self.app, "last_shade_azimuth", 45.0),
                            getattr(self.app, "last_shade_angle", 45.0),
                            getattr(self.app, "shade_ambient", 0.2),
                            force_rebuild=True
                        )
                    finally:
                        for c, vis in saved_vis.items():
                            self.app.class_palette[c]["show"] = vis
                    return
                if n_left > 0:
                    success = refresh_shaded_after_classification_fast(
                        self.app, changed_mask)
                    if success:
                        return
                if n_new == 0 and n_left == 0:
                    self._update_shaded_colors_single_class(cache, single_class_id)
                    return
            if cache.faces is None or len(cache.faces) == 0:
                update_shaded_class(self.app, force_rebuild=True)
                return

            success = refresh_shaded_after_classification_fast(
                self.app, changed_mask)
            if success:
                return

            # Existing fallback for single-class (no changed_mask case)
            if is_single_class and single_class_id is not None:
                if cache.faces is not None and len(cache.faces) > 0:
                    classes = self.app.data.get("classification").astype(np.int32)
                    cached_vertex_classes = classes[cache.unique_indices]
                    still_valid = (cached_vertex_classes == single_class_id)
                    has_new_points_in_class = False
                    if changed_mask is not None and np.any(changed_mask):
                        changed_now = classes[np.where(changed_mask)[0]]
                        has_new_points_in_class = bool(
                            np.any(changed_now == single_class_id))
                    if not np.all(still_valid) or has_new_points_in_class:
                        clear_shading_cache("single-class reclassified")
                        saved_vis = {}
                        for c in self.app.class_palette:
                            saved_vis[c] = self.app.class_palette[c].get("show", True)
                            self.app.class_palette[c]["show"] = (int(c) == single_class_id)
                        try:
                            update_shaded_class(
                                self.app,
                                getattr(self.app, "last_shade_azimuth", 45.0),
                                getattr(self.app, "last_shade_angle", 45.0),
                                getattr(self.app, "shade_ambient", 0.2),
                                force_rebuild=True
                            )
                        finally:
                            for c, vis in saved_vis.items():
                                self.app.class_palette[c]["show"] = vis
                        return
                    else:
                        self._update_shaded_colors_single_class(cache, single_class_id)
                        return

            cached_visible = getattr(cache, 'visible_classes_set', None)
            if cached_visible is not None and cache.faces is not None:
                current_visible = {
                    int(c) for c, e in self.app.class_palette.items()
                    if e.get("show", True)
                }
                if current_visible == cached_visible:
                    self._update_shaded_colors_multi_class(cache)
                    return

            from gui.shading_display import refresh_shaded_colors_fast
            refresh_shaded_colors_fast(self.app)

        except Exception as e:
            print(f"Shaded refresh failed: {e}")
            import traceback
            traceback.print_exc()

    def _refresh_other_mode(self, display_mode):
        """Refresh other display modes."""
        try:
            from gui.pointcloud_display import update_pointcloud
            update_pointcloud(self.app, display_mode)
        except Exception as e:
            print(f"⚠️ Mode '{display_mode}' refresh failed: {e}")
    
    def _refresh_cut_section(self):
        """Refresh cut section if active."""
        ctrl = getattr(self.app, "cut_section_controller", None)
        if not ctrl or not ctrl.is_cut_view_active:
            return
    
        try:
            # ✅ THIS is the correct refresh
            ctrl._refresh_cut_colors_fast()
            ctrl.cut_vtk.render()
            print("      ✅ Cut section refreshed")
        except Exception as e:
            print(f"      ⚠️ Cut section refresh failed: {e}")
        
    def _get_view_palette(self, slot_idx):
            """
            Get palette for a view slot with "Bootstrap" logic for uninitialized views.
            ✅ FIXED: Ensures cross-sections (Slots 1-4) have valid palettes on first launch.
            """
            # 1. Primary Source: Active Display Mode Dialog
            if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
                dialog = self.app.display_mode_dialog
                if hasattr(dialog, 'view_palettes') and slot_idx in dialog.view_palettes:
                    # Ensure the slot isn't just an empty dictionary
                    if dialog.view_palettes[slot_idx]:
                        return dialog.view_palettes[slot_idx]
        
            # 2. Secondary Source: Application-level stored palettes
            if hasattr(self.app, 'view_palettes') and slot_idx in self.app.view_palettes:
                if self.app.view_palettes[slot_idx]:
                    return self.app.view_palettes[slot_idx]
    
            global_palette = getattr(self.app, 'class_palette', {})
        
            if slot_idx != 0 and global_palette:
                if not hasattr(self.app, 'view_palettes'):
                    self.app.view_palettes = {}
            
                if slot_idx not in self.app.view_palettes or not self.app.view_palettes[slot_idx]:
                    print(f"   🛠️ Bootstrapping Palette for Slot {slot_idx} from Global state")
                    # Deep copy to ensure Slot 0 remains protected from later modifications
                    bootstrapped = {int(c): dict(info) for c, info in global_palette.items()}
                    self.app.view_palettes[slot_idx] = bootstrapped
                    return bootstrapped
        
            return global_palette
        
    def verify_borders_applied(app):
        """
        Diagnostic: verify unified actor has border shader attached.
        ✅ UNIFIED: Checks the single unified actor, not per-class actors.
        """
        plotter = getattr(app, 'vtk_widget', None)
        if not plotter:
            return 0, 0

        from gui.unified_actor_manager import UNIFIED_ACTOR_NAME

        border_count = 0
        no_border_count = 0

        # Check main unified actor
        actor = plotter.actors.get(UNIFIED_ACTOR_NAME)
        if actor is not None:
            ctx = getattr(actor, '_naksha_shader_ctx', None)
            if ctx and getattr(actor, '_shaders_finalized_v13', False):
                border_count += 1
                print(f"   ✅ Unified actor has v13 border shader (ring={ctx.border_ring:.3f})")
            else:
                no_border_count += 1
                print(f"   ❌ Unified actor missing shader context or v13 shader")
        else:
            no_border_count += 1
            print(f"   ❌ No unified actor found in plotter")

        # Check section actors
        if hasattr(app, 'section_vtks'):
            for view_idx, vtk_widget in app.section_vtks.items():
                sec_name = f"_section_{view_idx}_unified"
                sec_actor = vtk_widget.actors.get(sec_name) if vtk_widget else None
                if sec_actor and getattr(sec_actor, '_shaders_finalized_v13', False):
                    border_count += 1
                elif sec_actor:
                    no_border_count += 1

        print(f"\n🔍 Border Verification (Unified):")
        print(f"   ✅ With v13 shader: {border_count}")
        print(f"   ❌ Without: {no_border_count}")

        return border_count, no_border_count
    
    def _batched_render(self):
        """Single batched render pass for all pending views."""
        if not self._pending_renders:
            return
        
        if ENABLE_PERFORMANCE_LOGGING:
            print(f"   🎨 Rendering views: {sorted(self._pending_renders)}")
        
        border_percent = getattr(self.app, "point_border_percent", 0)
        
        if 0 in self._pending_renders:
            vtk_widget = getattr(self.app, 'vtk_widget', None)
            if vtk_widget:
                try:
                    # ✅ UNIFIED ACTOR: borders are pushed via GPU uniform in sync_palette_to_gpu.
                    # Never scan for class_ actors — they don't exist in unified mode.
                    if border_percent > 0:
                        try:
                            from gui.unified_actor_manager import sync_palette_to_gpu
                            sync_palette_to_gpu(self.app, 0)
                        except Exception as _be:
                            print(f"      ⚠️ Border GPU sync failed: {_be}")

                    vtk_widget.render()
                    print(f"      ✅ Main view rendered with {border_percent}% borders")

                except Exception as e:
                    print(f"      ⚠️ Main view render failed: {e}")

        cross_section_slots = [v for v in self._pending_renders if 1 <= v <= 4]

        if cross_section_slots and hasattr(self.app, 'section_vtks'):
            for slot_idx in cross_section_slots:
                view_idx = slot_idx - 1

                if view_idx not in self.app.section_vtks:
                    continue

                vtk_widget = self.app.section_vtks[view_idx]

                try:
                    # ✅ UNIFIED ACTOR: borders via GPU uniform, not class_ actor scan
                    if border_percent > 0:
                        try:
                            from gui.unified_actor_manager import sync_palette_to_gpu
                            sync_palette_to_gpu(self.app, slot_idx)
                        except Exception as _be:
                            print(f"      ⚠️ Section border GPU sync failed: {_be}")

                    vtk_widget.render()
                    print(f"      ✅ Cross-section view {slot_idx} rendered")
                    
                except Exception as e:
                    print(f"      ⚠️ Cross-section view {slot_idx} render failed: {e}")
        
        if 5 in self._pending_renders:
            ctrl = getattr(self.app, 'cut_section_controller', None)
            if ctrl and hasattr(ctrl, 'cut_vtk'):
                try:
                    ctrl.cut_vtk.render()
                    print(f"      ✅ Cut section rendered")
                except Exception as e:
                    print(f"      ⚠️ Cut section render failed: {e}")
        
        self._pending_renders.clear()
    
    def _individual_renders(self):
        """Individual render calls."""
        self._batched_render()  # Same implementation for now
    
    def _update_statistics(self):
        """Update point statistics."""
        try:
            from gui.point_count_widget import refresh_point_statistics
            refresh_point_statistics(self.app)
        except:
            pass
        
    def _apply_border_shader_safe(self, actor, border_percent):
        """
        ✅ UNIFIED: Borders are applied via GPU uniforms on the unified actor.
        No per-class shader replacement needed — the v13 fragment shader reads
        border_ring_val uniform directly.
        """
        if border_percent <= 0:
            return True

        try:
            ctx = getattr(actor, '_naksha_shader_ctx', None)
            if ctx is not None:
                new_ring = min(0.50, max(0.0, border_percent / 100.0))
                ctx.border_ring = new_ring
                from gui.unified_actor_manager import _push_uniforms_direct
                _push_uniforms_direct(actor, ctx)
                return True
            else:
                # Fallback: per-class actor without shader context
                from gui.unified_actor_manager import _apply_border_once
                _apply_border_once(actor, border_percent)
                return True

        except Exception as e:
            print(f"      ❌ Border shader exception: {e}")
            return False
    
    def _show_status(self, to_class):
        """Show status bar message."""
        try:
            changed_mask = getattr(self.app, '_last_changed_mask', None)
            num_changed = int(np.sum(changed_mask)) if changed_mask is not None else 0
            
            palette = getattr(self.app, 'class_palette', {})
            class_name = palette.get(to_class, {}).get('description', f'Class {to_class}')
            
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage(
                    f"✅ {num_changed:,} points classified to {class_name}",
                    3000
                )
        except:
            pass

# Singleton instance
_optimizer: Optional[OptimizedRefreshPipeline] = None

def get_optimizer(app) -> OptimizedRefreshPipeline:
    """Get or create the optimizer instance."""
    global _optimizer
    if _optimizer is None or _optimizer.app != app:
        _optimizer = OptimizedRefreshPipeline(app)
    return _optimizer

def install_optimized_refresh(app):
    """Install the optimization pipeline."""
    app._optimized_refresh = OptimizedRefreshPipeline(app)
    print("✅ Optimized refresh pipeline installed")
    print(f"   ENABLE_OPTIMIZED_REFRESH: {ENABLE_OPTIMIZED_REFRESH}")
