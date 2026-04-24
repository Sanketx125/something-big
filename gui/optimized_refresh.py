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
                
            
            if ENABLE_PERFORMANCE_LOGGING:
                print(f"   📊 Dirty state: classes={state.dirty_classes}, views={state.dirty_views}")
            
            # Step 1: Delta weight sync
            self._weights_changed_this_cycle = False
            if ENABLE_DELTA_WEIGHT_SYNC:
                self._sync_weights_delta()
            else:
                self._sync_weights_full()
                self._weights_changed_this_cycle = True 
            
            if ENABLE_DIRTY_VIEW_TRACKING:
                self._refresh_dirty_cross_sections(state)
            
            # Step 3: Main View refresh
            self._refresh_main_view_for_classification(to_class, state)
            self._pending_renders.add(0)

            if 5 in state.dirty_views:
                self._refresh_cut_section()
                self._pending_renders.add(5)
            
            # Step 5: Render all pending views
            if ENABLE_BATCHED_RENDERING:
                self._batched_render()
            else:
                self._individual_renders()
            
            if ENABLE_PERFORMANCE_LOGGING:
                self._update_statistics()
                self._show_status(to_class)
            
        finally:
            state.end_refresh()
            state.clear()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, lambda: setattr(self.app, "_optimized_refresh_active", False))

    def _sync_weights_delta(self):
        """
        ✅ FIXED: Strictly syncs ONLY Slot 0 (Main View) to the global palette.
        """
        weight_cache = get_weight_cache()
        dialog = getattr(self.app, 'display_mode_dialog', None)
        if not dialog or not hasattr(dialog, 'view_palettes'):
            return
        
        if hasattr(dialog, 'view_palettes') and 0 in dialog.view_palettes:
            if not hasattr(self.app, 'class_palette'):
                self.app.class_palette = {}
            for cls, info in dialog.view_palettes[0].items():
                if cls in self.app.class_palette:
                    self.app.class_palette[cls]['weight'] = info.get('weight', 1.0)
                    self.app.class_palette[cls]['color'] = info.get('color', (128, 128, 128))
                    self.app.class_palette[cls]['show'] = info.get('show', True)
                else:
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
            self._weights_changed_this_cycle = True
            self._pending_renders.add(0)
        weight_cache.update_cache(dialog.view_palettes)

    def _sync_weights_full(self):
        """Full weight sync (original behavior)."""
        if hasattr(self.app, 'interactor') and hasattr(self.app.interactor, '_sync_main_view_palette_weights'):
            self.app.interactor._sync_main_view_palette_weights()

    def _refresh_dirty_cross_sections(self, state):
        """
        Refresh cross-section views that are marked as dirty.
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
        
        if not cross_section_slots:
            return
        
        for slot_idx in cross_section_slots:
            view_idx = slot_idx - 1 
            if not hasattr(self.app, 'section_vtks') or view_idx not in self.app.section_vtks:
                continue
            self._refresh_single_cross_section(view_idx, state)
            self._pending_renders.add(slot_idx)
    
    def _refresh_single_cross_section(self, view_idx, state):
        """
        Optimized single cross-section refresh.
        """
        if not hasattr(self.app, 'section_vtks') or view_idx not in self.app.section_vtks:
            return
        vtk_widget = self.app.section_vtks[view_idx]
        slot_idx = view_idx + 1

        # Check for view mode change
        current_view_mode = getattr(self.app, 'cross_view_mode', 'side')
        if not hasattr(self, '_last_view_modes'): self._last_view_modes = {}
        last_view_mode = self._last_view_modes.get(view_idx)
        
        if last_view_mode is not None and last_view_mode != current_view_mode:
            self._last_view_modes[view_idx] = current_view_mode
            try:
                core_pts = getattr(self.app, f'section_{view_idx}_core_points', None)
                buffer_pts = getattr(self.app, f'section_{view_idx}_buffer_points', None)
                if core_pts is not None:
                    old_active = self.app.section_controller.active_view
                    self.app.section_controller.active_view = view_idx
                    self.app.section_controller.current_vtk = vtk_widget
                    self.app.section_controller._plot_section(core_pts, buffer_pts, view=current_view_mode)                
                    self.app.section_controller.active_view = old_active
                    return
            except Exception: pass
        else:
            self._last_view_modes[view_idx] = current_view_mode

        # Fast shared memory update
        try:
            from gui.unified_actor_manager import fast_cross_section_update
            changed_mask = getattr(self.app, '_last_changed_mask', None)
            palette = self._get_view_palette(slot_idx)
            fast_cross_section_update(self.app, view_idx, changed_mask, palette=palette, skip_render=True)
        except Exception as e:
            print(f"      ⚠️ Unified cross-section update failed: {e}")

    def _refresh_main_view_for_classification(self, to_class, state):
        """
        🚀 REFACTORED: Delegates to unified_actor_manager.fast_classify_update.
        """
        app = self.app
        display_mode = getattr(app, "display_mode", "class")

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
                            skip_render=True
                        )
                        if _done:
                            self._pending_renders.add(0)
                            return
            except Exception as e:
                print(f"   ⚠️ fast_classify_update failed: {e}")

        # Fallback for non-class modes or if unified actor fails
        if display_mode == "class":
            self._refresh_main_view_class_mode(to_class, state)
        elif display_mode == "shaded_class":
            self._refresh_shaded_mode()
        else:
            self._refresh_other_mode(display_mode)

    def _refresh_main_view_class_mode(self, to_class, state):
        """
        ✅ FIXED: Standard refresh mode (only used if fast path fails).
        """
        app = self.app
        plotter = getattr(app, 'vtk_widget', None)
        if plotter is None: return
        try:
            from gui.pointcloud_display import update_pointcloud
            update_pointcloud(app, "class")
            self._pending_renders.add(0)
        except Exception: pass

    def _refresh_shaded_mode(self):
        """Refresh shaded mode."""
        try:
            from gui.shading_display import refresh_shaded_after_classification_fast
            changed_mask = getattr(self.app, '_last_changed_mask', None)
            refresh_shaded_after_classification_fast(self.app, changed_mask)
        except Exception: pass

    def _refresh_other_mode(self, display_mode):
        """Refresh other display modes."""
        try:
            from gui.pointcloud_display import update_pointcloud
            update_pointcloud(self.app, display_mode)
        except Exception: pass
    
    def _refresh_cut_section(self):
        """Refresh cut section if active."""
        ctrl = getattr(self.app, "cut_section_controller", None)
        if not ctrl or not ctrl.is_cut_view_active: return
        try:
            ctrl._refresh_cut_colors_fast()
            ctrl.cut_vtk.render()
        except Exception: pass
        
    def _get_view_palette(self, slot_idx):
        """Get palette for a view slot."""
        if hasattr(self.app, 'display_mode_dialog') and self.app.display_mode_dialog:
            dialog = self.app.display_mode_dialog
            if hasattr(dialog, 'view_palettes') and slot_idx in dialog.view_palettes:
                if dialog.view_palettes[slot_idx]: return dialog.view_palettes[slot_idx]
        return getattr(self.app, 'class_palette', {})
    
    def _batched_render(self):
        """Single batched render pass for all pending views."""
        if not self._pending_renders: return
        
        border_percent = getattr(self.app, "point_border_percent", 0)
        weights_changed = getattr(self, '_weights_changed_this_cycle', False)
        
        if 0 in self._pending_renders:
            vtk_widget = getattr(self.app, 'vtk_widget', None)
            if vtk_widget:
                try:
                    if border_percent > 0 or weights_changed:
                        from gui.unified_actor_manager import sync_palette_to_gpu
                        sync_palette_to_gpu(self.app, 0, render=False)
                    vtk_widget.render()
                except Exception: pass

        cross_section_slots = [v for v in self._pending_renders if 1 <= v <= 4]
        if cross_section_slots and hasattr(self.app, 'section_vtks'):
            for slot_idx in cross_section_slots:
                view_idx = slot_idx - 1
                if view_idx not in self.app.section_vtks: continue
                vtk_widget = self.app.section_vtks[view_idx]
                try:
                    if border_percent > 0 or weights_changed:
                        from gui.unified_actor_manager import sync_palette_to_gpu
                        sync_palette_to_gpu(self.app, slot_idx, render=False)
                    vtk_widget.render()
                except Exception: pass
        
        if 5 in self._pending_renders:
            ctrl = getattr(self.app, 'cut_section_controller', None)
            if ctrl and hasattr(ctrl, 'cut_vtk'):
                try: ctrl.cut_vtk.render()
                except Exception: pass
        self._pending_renders.clear()
    
    def _individual_renders(self):
        self._batched_render()
    
    def _update_statistics(self):
        try:
            from gui.point_count_widget import refresh_point_statistics
            refresh_point_statistics(self.app)
        except Exception: pass
            
    def _show_status(self, to_class):
        try:
            changed_mask = getattr(self.app, '_last_changed_mask', None)
            num_changed = int(np.sum(changed_mask)) if changed_mask is not None else 0
            if hasattr(self.app, 'statusBar'):
                self.app.statusBar().showMessage(f"✅ {num_changed:,} points classified", 3000)
        except Exception: pass

_optimizer: Optional[OptimizedRefreshPipeline] = None

def get_optimizer(app) -> OptimizedRefreshPipeline:
    global _optimizer
    if _optimizer is None or _optimizer.app != app:
        _optimizer = OptimizedRefreshPipeline(app)
    return _optimizer

def install_optimized_refresh(app):
    app._optimized_refresh = OptimizedRefreshPipeline(app)
    print("✅ Optimized refresh pipeline installed")
