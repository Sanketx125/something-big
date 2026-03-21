# # In classification_tools.py or wherever you handle classification

# def classify_region_ultra_fast(app, region_mask, new_class):
#     """
#     FASTEST classification - no geometry rebuild, color-only update.
#     Works on datasets with 100M+ points.
#     """
#     if not np.any(region_mask):
#         return
    
#     changed_indices = np.where(region_mask)[0]
#     n_changed = len(changed_indices)
    
#     if n_changed == 0:
#         return
    
#     print(f"⚡ Classifying {n_changed:,} points...")
    
#     # ✅ Store old for undo (only changed points to save memory)
#     old_classes = app.data["classification"][region_mask].copy()
    
#     # ✅ Apply change
#     app.data["classification"][region_mask] = new_class
    
#     # ✅ Add to undo (compact format)
#     app.undo_stack.append({
#         "indices": changed_indices,
#         "old_classes": old_classes,
#         "new_class": new_class
#     })
    
#     # ✅ Limit undo stack to prevent memory bloat
#     if len(app.undo_stack) > 50:
#         app.undo_stack.pop(0)
    
#     # ✅ CRITICAL: Only update colors in-place, NO geometry rebuild
#     try:
#         from gui.performance_optimizations import fast_update_colors_optimized
#         fast_update_colors_optimized(app, region_mask)
#     except ImportError:
#         # Fallback
#         from gui.pointcloud_display import fast_update_colors
#         fast_update_colors(app, region_mask)
    
#     print(f"✅ Classification complete ({n_changed:,} points → class {new_class})")


# def classify_brush_ultra_fast(app, center_3d, radius, new_class):
#     """
#     Ultra-fast brush using spatial index (O(log n) instead of O(n)).
#     """
#     # ✅ Use spatial index if available (100x faster!)
#     if hasattr(app, 'spatial_index') and app.spatial_index:
#         try:
#             indices = app.spatial_index.query_radius(center_3d, radius)
            
#             if len(indices) == 0:
#                 return
            
#             # Create mask from indices
#             mask = np.zeros(len(app.data["xyz"]), dtype=bool)
#             mask[indices] = True
            
#             print(f"🎯 Brush (spatial index): {len(indices):,} points in {radius:.2f}m radius")
            
#         except Exception as e:
#             print(f"⚠️ Spatial index failed: {e}, falling back...")
#             # Fallback below
#             mask = None
#     else:
#         mask = None
    
#     # ✅ Fallback: vectorized distance calculation
#     if mask is None:
#         distances = np.linalg.norm(app.data["xyz"] - center_3d, axis=1)
#         mask = distances <= radius
#         print(f"🎯 Brush (fallback): {mask.sum():,} points")
    
#     classify_region_ultra_fast(app, mask, new_class)


# def classify_rectangle_ultra_fast(app, x_min, x_max, y_min, y_max, new_class):
#     """
#     Ultra-fast rectangular selection using spatial index.
#     """
#     if hasattr(app, 'spatial_index') and app.spatial_index:
#         try:
#             indices = app.spatial_index.query_rectangle(x_min, x_max, y_min, y_max)
            
#             if len(indices) == 0:
#                 return
            
#             mask = np.zeros(len(app.data["xyz"]), dtype=bool)
#             mask[indices] = True
            
#             print(f"📦 Rectangle (spatial index): {len(indices):,} points")
            
#         except Exception as e:
#             print(f"⚠️ Spatial index failed: {e}, falling back...")
#             mask = None
#     else:
#         mask = None
    
#     # Fallback: vectorized bounds check
#     if mask is None:
#         xyz = app.data["xyz"]
#         mask = ((xyz[:, 0] >= x_min) & (xyz[:, 0] <= x_max) &
#                 (xyz[:, 1] >= y_min) & (xyz[:, 1] <= y_max))
#         print(f"📦 Rectangle (fallback): {mask.sum():,} points")
    
#     classify_region_ultra_fast(app, mask, new_class)
"""
Ultra-optimized classification tools for massive point clouds (100M+ points)
Key optimizations:
- Batch processing for multiple operations
- Minimal memory allocation
- Direct color buffer updates (no rebuilds)
- Chunked processing for huge datasets
- Async/threaded color updates
"""

import numpy as np
from concurrent.futures import ThreadPoolExecutor
import time


class UltraFastClassifier:
    """
    High-performance classifier with batch operations and minimal overhead.
    """
    
    def __init__(self, app, chunk_size=1_000_000):
        self.app = app
        self.chunk_size = chunk_size
        self.executor = ThreadPoolExecutor(max_workers=4)
        
    def classify_region(self, region_mask, new_class, skip_undo=False):
        """
        Fastest possible classification with optional undo skip for batch ops.
        """
        if not np.any(region_mask):
            return 0
        
        t0 = time.perf_counter()
        
        # Get changed indices efficiently
        changed_indices = np.flatnonzero(region_mask)
        n_changed = len(changed_indices)
        
        if n_changed == 0:
            return 0
        
        # Store undo data (only if not in batch mode)
        if not skip_undo:
            old_classes = self.app.data["classification"][changed_indices].copy()
            self._add_to_undo(changed_indices, old_classes, new_class)
        
        # Apply classification change (in-place)
        self.app.data["classification"][region_mask] = new_class
        
        # Update colors WITHOUT geometry rebuild
        from gui.unified_actor_manager import fast_classify_update
        border_percent = float(getattr(self.app, "point_border_percent", 0.0))
        fast_classify_update(self.app, region_mask, new_class, border_percent=border_percent)
        
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"⚡ {n_changed:,} pts → class {new_class} in {elapsed:.1f}ms")
        
        return n_changed
    
    def _add_to_undo(self, indices, old_classes, new_class):
        """
        Store undo data in the standard format expected by app_window.py.
        """
        if not hasattr(self.app, 'undo_stack'):
            self.app.undo_stack = []
            
        final_mask = np.zeros(len(self.app.data["xyz"]), dtype=bool)
        final_mask[indices] = True
        
        new_classes = np.full(old_classes.shape, new_class, dtype=old_classes.dtype)

        undo_data = {
            "mask": final_mask,
            "old_classes": old_classes,
            "new_classes": new_classes
        }
        
        self.app.undo_stack.append(undo_data)
        # Clear stale redo entries after new action
        if hasattr(self.app, 'redo_stack'):
            self.app.redo_stack.clear()

        # Limit stack size (keep last 30 operations to save memory)
        if len(self.app.undo_stack) > 30:
            from gui.memory_manager import _free_undo_entry
            _free_undo_entry(self.app.undo_stack.pop(0))
    
    def classify_brush_spatial(self, center_3d, radius, new_class):
        """
        Ultra-fast brush using spatial index (KD-tree or octree).
        """
        t0 = time.perf_counter()
        
        # Try spatial index first (O(log n))
        if hasattr(self.app, 'spatial_index') and self.app.spatial_index:
            try:
                indices = self.app.spatial_index.query_ball_point(center_3d, radius)
                
                if len(indices) == 0:
                    return 0
                
                # Create mask efficiently
                mask = np.zeros(len(self.app.data["xyz"]), dtype=bool)
                mask[indices] = True
                
                n = self.classify_region(mask, new_class)
                
                elapsed = (time.perf_counter() - t0) * 1000
                print(f"🎯 Brush (spatial): {n:,} pts in {elapsed:.1f}ms")
                return n
                
            except Exception as e:
                print(f"Spatial index failed: {e}")
        
        # Fallback: vectorized distance (still fast)
        return self._classify_brush_fallback(center_3d, radius, new_class, t0)
    
    def _classify_brush_fallback(self, center_3d, radius, new_class, t0):
        """
        Vectorized fallback for brush (no spatial index).
        """
        xyz = self.app.data["xyz"]
        
        # Chunked processing for huge datasets
        if len(xyz) > 10_000_000:
            mask = self._chunked_distance_check(xyz, center_3d, radius)
        else:
            # Single vectorized operation for smaller datasets
            dist_sq = np.sum((xyz - center_3d) ** 2, axis=1)
            mask = dist_sq <= radius ** 2
        
        n = self.classify_region(mask, new_class)
        
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"🎯 Brush (vectorized): {n:,} pts in {elapsed:.1f}ms")
        return n
    
    def _chunked_distance_check(self, xyz, center, radius):
        """
        Process distance check in chunks to avoid memory spikes.
        """
        n = len(xyz)
        mask = np.zeros(n, dtype=bool)
        radius_sq = radius ** 2
        
        for i in range(0, n, self.chunk_size):
            end = min(i + self.chunk_size, n)
            chunk = xyz[i:end]
            dist_sq = np.sum((chunk - center) ** 2, axis=1)
            mask[i:end] = dist_sq <= radius_sq
        
        return mask
    
    def classify_rectangle_spatial(self, x_min, x_max, y_min, y_max, new_class, z_min=None, z_max=None):
        """
        Ultra-fast rectangular selection with optional Z bounds.
        """
        t0 = time.perf_counter()
        xyz = self.app.data["xyz"]
        
        # Vectorized bounds check (fastest for rectangles)
        mask = ((xyz[:, 0] >= x_min) & (xyz[:, 0] <= x_max) &
                (xyz[:, 1] >= y_min) & (xyz[:, 1] <= y_max))
        
        # Optional Z filtering
        if z_min is not None and z_max is not None:
            mask &= (xyz[:, 2] >= z_min) & (xyz[:, 2] <= z_max)
        
        n = self.classify_region(mask, new_class)
        
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"📦 Rectangle: {n:,} pts in {elapsed:.1f}ms")
        return n
    
    def classify_polygon_fast(self, polygon_points, new_class):
        """
        Fast polygon classification using ray casting.
        """
        t0 = time.perf_counter()
        xyz = self.app.data["xyz"]
        
        # Use optimized point-in-polygon test
        mask = self._points_in_polygon(xyz[:, :2], polygon_points)
        
        n = self.classify_region(mask, new_class)
        
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"🔷 Polygon: {n:,} pts in {elapsed:.1f}ms")
        return n
    
    def _points_in_polygon(self, points, polygon):
        """
        Vectorized ray-casting algorithm for point-in-polygon test.
        """
        n = len(points)
        mask = np.zeros(n, dtype=bool)
        
        px, py = points[:, 0], points[:, 1]
        
        # Ray casting from each point
        for i in range(len(polygon)):
            j = (i + 1) % len(polygon)
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            
            # Check if ray crosses edge
            intersect = ((yi > py) != (yj > py)) & \
                        (px < (xj - xi) * (py - yi) / (yj - yi + 1e-10) + xi)
            
            mask ^= intersect  # Toggle for each crossing
        
        return mask
    
    def batch_classify(self, operations):
        """
        Batch multiple classification operations for efficiency.
        Operations format: [(mask, class), (mask, class), ...]
        """
        t0 = time.perf_counter()
        total_changed = 0
        
        # Combine all undo data first
        all_indices = []
        all_old_classes = []
        
        for mask, new_class in operations:
            if not np.any(mask):
                continue
            
            indices = np.flatnonzero(mask)
            old_classes = self.app.data["classification"][indices].copy()
            
            all_indices.extend(indices)
            all_old_classes.extend(old_classes)
            
            # Apply change
            self.app.data["classification"][mask] = new_class
            total_changed += len(indices)
        
        # Single undo entry for entire batch
        if all_indices:
            self._add_to_undo(np.array(all_indices), np.array(all_old_classes), -1)
        
        # Single color update for all changes
        if total_changed > 0:
            self._trigger_minimal_render()
        
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"📦 Batch: {total_changed:,} pts in {elapsed:.1f}ms ({len(operations)} ops)")
        
        return total_changed


# Convenience functions for backward compatibility
def classify_region_ultra_fast(app, region_mask, new_class):
    """Legacy wrapper for existing code."""
    if not hasattr(app, '_classifier'):
        app._classifier = UltraFastClassifier(app)
    return app._classifier.classify_region(region_mask, new_class)


def classify_brush_ultra_fast(app, center_3d, radius, new_class):
    """Legacy wrapper for existing code."""
    if not hasattr(app, '_classifier'):
        app._classifier = UltraFastClassifier(app)
    return app._classifier.classify_brush_spatial(center_3d, radius, new_class)


def classify_rectangle_ultra_fast(app, x_min, x_max, y_min, y_max, new_class):
    """Legacy wrapper for existing code."""
    if not hasattr(app, '_classifier'):
        app._classifier = UltraFastClassifier(app)
    return app._classifier.classify_rectangle_spatial(x_min, x_max, y_min, y_max, new_class)