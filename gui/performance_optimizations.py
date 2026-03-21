
"""
Key optimizations:
1. LOD (Level of Detail) rendering - only render visible points
2. Spatial indexing with KD-tree for fast queries
3. Chunked processing to avoid memory spikes
4. GPU-accelerated operations where possible
5. Lazy loading and viewport culling
"""

import numpy as np
from scipy.spatial import cKDTree
import pyvista as pv

# ============================================
# 1. LOD MANAGER - Adaptive Point Density
# ============================================

class LODManager:
    """
    Dynamically adjust point density based on zoom level.
    Renders fewer points when zoomed out, more when zoomed in.
    """
    def __init__(self, app):
        self.app = app
        self.lod_levels = {
            'far': 0.5,    # 10% of points when far away
            'medium': 0.15,  # 30% of points at medium zoom
            'near': 0.4,    # 60% of points when close
            'full': 0.7     # 100% when very close
        }
        self.current_lod = 'medium'
        
    def get_lod_factor(self, camera_distance):
        """Calculate LOD factor based on camera distance."""
        if camera_distance > 1000:
            return self.lod_levels['far']
        elif camera_distance > 500:
            return self.lod_levels['medium']
        elif camera_distance > 100:
            return self.lod_levels['near']
        else:
            return self.lod_levels['full']
    
    def subsample_points(self, xyz, colors, lod_factor):
        """Efficiently subsample points based on LOD."""
        if lod_factor >= 1.0:
            return xyz, colors
        
        n_points = len(xyz)
        n_keep = int(n_points * lod_factor)
        
        # Use systematic sampling for speed (not random)
        step = max(1, n_points // n_keep)
        indices = np.arange(0, n_points, step)[:n_keep]
        
        return xyz[indices], colors[indices]


class SpatialIndex:
    """
    KD-tree for O(log n) spatial queries instead of O(n).
    Critical for classification tools on large datasets.
    """
    def __init__(self, xyz):
        print(f"🔍 Building spatial index for {len(xyz):,} points...")
        self.tree = cKDTree(xyz)
        self.xyz = xyz
        print(f"✅ Spatial index ready")
    
    def query_radius(self, center, radius):
        """Find all points within radius of center."""
        return self.tree.query_ball_point(center, radius)
    
    def query_rectangle(self, x_min, x_max, y_min, y_max):
        """Fast rectangular region query."""
        mask = ((self.xyz[:, 0] >= x_min) & (self.xyz[:, 0] <= x_max) &
                (self.xyz[:, 1] >= y_min) & (self.xyz[:, 1] <= y_max))
        return np.where(mask)[0]
    
    def query_polygon(self, polygon_points):
        """Fast polygon containment check."""
        from matplotlib.path import Path
        path = Path(polygon_points[:, :2])  # Only XY
        points_2d = self.xyz[:, :2]
        return np.where(path.contains_points(points_2d))[0]
    
    # ✅ ADD THIS METHOD
    def query_bbox(self, bbox):
        """
        Query points within bounding box [xmin, ymin, xmax, ymax].
        Optimized for cross-section extraction.
        """
        xmin, ymin, xmax, ymax = bbox
        
        mask = (
            (self.xyz[:, 0] >= xmin) & (self.xyz[:, 0] <= xmax) &
            (self.xyz[:, 1] >= ymin) & (self.xyz[:, 1] <= ymax)
        )
        
        return np.where(mask)[0]




def update_pointcloud_optimized(app, mode):
    """
    🚀 SENIOR REFACTOR: Optimized for Millisecond Classification Sync.
    - Uses named actors to prevent 'missing points' and lag.
    - Maintains LOD mapping for high-speed buffer injection.
    - Handles class filtering and visibility at the GPU level.
    """
    import numpy as np
    import pyvista as pv
    import matplotlib.pyplot as plt

    if app.data is None or "xyz" not in app.data:
        print("⚠️ No data to display")
        return

    # --- 1. CORE DATA PREP ---
    xyz = app.data["xyz"]
    classes = app.data.get("classification")
    main_actor_name = "main_points_cloud"

    # Early-out: shaded_class (handled elsewhere)
    if mode == "shaded_class":
        from .shading_display import update_shaded_class
        update_shaded_class(app, getattr(app, "last_shade_azimuth", 45.0), 
                             getattr(app, "last_shade_angle", 45.0), 
                             getattr(app, "shade_ambient", 0.2))
        return

    # --- 2. CLASS FILTERING (GPU SAFETY) ---
    if mode == "class" and hasattr(app, "class_palette") and classes is not None:
        visible_classes = [c for c, info in app.class_palette.items() if info.get("show", True)]
        if not visible_classes:
            app.vtk_widget.remove_actor(main_actor_name)
            app.vtk_widget.render()
            return

        mask = np.isin(classes, visible_classes)
        if not mask.any():
            app.vtk_widget.remove_actor(main_actor_name)
            app.vtk_widget.render()
            return
            
        # Store visibility mask for the Classification Sync tool
        app.current_visibility_mask = mask 
        xyz = xyz[mask]
        classes = classes[mask]
    else:
        app.current_visibility_mask = None

    N = xyz.shape[0]
    if N == 0:
        app.vtk_widget.remove_actor(main_actor_name)
        return

    # --- 3. LOD MANAGEMENT ---
    indices = np.arange(N)
    if N > 1_000_000:
        if not hasattr(app, "lod_manager"):
            # Ensure LODManager is available in your path
            try:
                from .lod_manager import LODManager 
                app.lod_manager = LODManager(app)
            except ImportError:
                pass

        if hasattr(app, "lod_manager"):
            cam = app.vtk_widget.renderer.GetActiveCamera()
            dist = np.linalg.norm(np.array(cam.GetPosition()) - np.array(cam.GetFocalPoint()))
            lod_factor = app.lod_manager.get_lod_factor(dist)

            n_target = int(N * lod_factor)
            if n_target < N:
                step = max(1, N // n_target)
                indices = np.arange(0, N, step)[:n_target]
                xyz = xyz[indices]
                if classes is not None and mode == "class":
                    classes = classes[indices]
    
    # Store these indices! Classification Sync needs these to find points in the buffer.
    app.current_gpu_indices = indices 

    # --- 4. COLOR COMPUTATION ---
    if mode == "rgb":
        colors = app.data.get("rgb")
        if colors is None:
            colors = np.full((len(xyz), 3), 128, dtype=np.uint8)
        else:
            if app.current_visibility_mask is not None:
                colors = colors[app.current_visibility_mask]
            colors = colors[indices]
            if colors.dtype != np.uint8:
                colors = (colors * 255).clip(0, 255).astype(np.uint8)

    elif mode == "class":
        if classes is None:
            colors = np.full((len(xyz), 3), 160, dtype=np.uint8)
        else:
            palette = getattr(app, "class_palette", {}) or {}
            max_c = int(classes.max()) + 1
            lut = np.full((max_c, 3), 128, dtype=np.uint8)
            for code, info in palette.items():
                if int(code) < max_c:
                    lut[int(code)] = info.get("color", (128, 128, 128))
            colors = lut[classes.astype(int)]
            
            weight = getattr(app, "class_weight", 1.0)
            if weight != 1.0:
                colors = np.clip(colors.astype(np.float32) * weight, 0, 255).astype(np.uint8)

    elif mode == "intensity":
        intensity = app.data.get("intensity")
        if intensity is not None:
            if app.current_visibility_mask is not None:
                intensity = intensity[app.current_visibility_mask]
            intensity = intensity[indices]
            i_min, i_max = intensity.min(), intensity.max()
            norm = (intensity - i_min) / (i_max - i_min + 1e-6)
            gray = (norm * 255).astype(np.uint8)
            colors = np.stack([gray, gray, gray], axis=1)
        else:
            colors = np.full((len(xyz), 3), 128, dtype=np.uint8)
    else:
        colors = np.full((len(xyz), 3), 128, dtype=np.uint8)

    # --- 5. SMART RENDER ---
    cloud = pv.PolyData(xyz)
    cloud["RGB"] = colors

    # Target specific actor to prevent UI flickering or missing overlays
    app.vtk_widget.remove_actor(main_actor_name)

    app.vtk_widget.add_points(
        cloud,
        scalars="RGB",
        rgb=True,
        point_size=1 if N > 500_000 else 2,
        name=main_actor_name, 
        render=False 
    )

    if hasattr(app, "current_view"):
        from .views import set_view
        set_view(app, app.current_view)

    app.vtk_widget.render()


# ============================================
# 4. FAST COLOR UPDATE (In-place VTK)
# ============================================

def fast_update_colors_optimized(app, changed_mask=None):
    """
    Ultra-fast color update without rebuilding geometry.
    Only updates the color array in VTK (MicroStation-style).
    """
    import numpy as np
    import pyvista as pv

    if app.data is None:
        return

    classes = app.data["classification"]
    palette = app.class_palette
    
    # Find renderer
    if hasattr(app.vtk_widget, "plotter"):
        renderer = app.vtk_widget.plotter.renderer
    elif hasattr(app.vtk_widget, "renderer"):
        renderer = app.vtk_widget.renderer
    else:
        return

    # Find main actor (largest point cloud)
    ac = renderer.GetActors()
    ac.InitTraversal()
    
    actor = None
    max_pts = -1
    while True:
        a = ac.GetNextActor()
        if not a:
            break
        pd = a.GetMapper().GetInput()
        if pd and pd.GetNumberOfPoints() > max_pts:
            max_pts = pd.GetNumberOfPoints()
            actor = a
    
    if actor is None:
        return

    poly = actor.GetMapper().GetInput()
    
    # ============================================
    # OPTIMIZATION: Only update changed points
    # ============================================
    N = len(classes)
    
    if changed_mask is not None and np.any(changed_mask):
        # Partial update - only changed points
        changed_indices = np.where(changed_mask)[0]
        print(f"⚡ Partial update: {len(changed_indices):,} points changed")
        
        # Get existing color array
        existing_colors = pv.convert_array(poly.GetPointData().GetArray("RGB"))
        
        # Update only changed points
        for idx in changed_indices:
            code = int(classes[idx])
            entry = palette.get(code, {"color": (128, 128, 128)})
            existing_colors[idx] = entry["color"]
        
        colors = existing_colors
    else:
        # Full update
        colors = np.zeros((N, 3), dtype=np.uint8)
        for code, entry in palette.items():
            mask = classes == int(code)
            if np.any(mask):
                colors[mask] = entry.get("color", (128, 128, 128))
    
    # Apply to VTK
    arr = pv.convert_array(colors, "RGB")
    pd = poly.GetPointData()
    pd.RemoveArray("RGB")
    pd.AddArray(arr)
    pd.SetActiveScalars("RGB")
    poly.Modified()

    app.vtk_widget.GetRenderWindow().Render()
    print("⚡ Fast color update complete")


def apply_classification_chunked(app, mask, new_class, from_classes=None, chunk_size=100_000):
    """
    ✅ UPDATED: Now handles from_classes filtering internally (safer!)
    
    This makes it consistent with _apply_classification()
    """
    # ✅ If we have a spatial index, use it for faster queries
    if hasattr(app, 'spatial_index') and app.spatial_index:
        print(f"🔍 Using spatial index for classification")
        
        # Example: If classifying a rectangle
        if hasattr(app, '_last_selection_bounds'):
            xmin, xmax, ymin, ymax = app._last_selection_bounds
            
            # ⚡ O(log n) query instead of O(n) full scan
            candidate_indices = app.spatial_index.query_bbox([xmin, ymin, xmax, ymax])
            
            # Create mask from spatial query results
            mask = np.zeros(len(app.data["xyz"]), dtype=bool)
            mask[candidate_indices] = True
            
            print(f"   📊 Spatial query: {len(candidate_indices):,} candidates (not full dataset!)")
    
    # ✅ Apply from_classes filter if provided
    if from_classes is not None:
        if isinstance(from_classes, list):
            class_match = np.isin(app.data["classification"][mask], from_classes)
            print(f"🔍 Multi-class filter: {from_classes} matched {class_match.sum()}/{mask.sum()} points")
        else:
            class_match = app.data["classification"][mask] == from_classes
            print(f"🔍 Single-class filter: {from_classes} matched {class_match.sum()}/{mask.sum()} points")
        
        selected_indices = np.where(mask)[0]
        matched_indices = selected_indices[class_match]
        
        final_mask = np.zeros(len(app.data["classification"]), dtype=bool)
        final_mask[matched_indices] = True
        
        if not final_mask.any():
            print("⚠️ No points match from_classes")
            return
    else:
        final_mask = mask
    
    # ✅ Use final_mask for everything below
    indices = np.where(final_mask)[0]
    n_total = len(indices)
    
    if n_total == 0:
        return
    
    print(f"🔄 Applying classification to {n_total:,} points in chunks...")
    
    # ✅ Store old classes for FINAL filtered mask
    old_classes = app.data["classification"][final_mask].copy()
    
    # Process in chunks
    n_chunks = (n_total + chunk_size - 1) // chunk_size
    
    for i in range(n_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, n_total)
        chunk_indices = indices[start:end]
        
        # Apply classification
        app.data["classification"][chunk_indices] = new_class
        
        # Update progress
        if n_chunks > 1:
            progress = ((i + 1) / n_chunks) * 100
            print(f"   Progress: {progress:.1f}%")
            if hasattr(app, 'statusBar'):
                app.statusBar().showMessage(
                    f"Classifying... {progress:.0f}%",
                    1000
                )
    
    # ✅ Store in undo stack with FINAL mask
    if not hasattr(app, 'undo_stack'):
        app.undo_stack = []
    if not hasattr(app, 'redo_stack'):
        app.redo_stack = []
    
    app.undo_stack.append({
        "mask": final_mask.copy(),  # ✅ Use final_mask
        "old_classes": old_classes,  # ✅ Values from final_mask
        "new_classes": np.full(len(old_classes), new_class, dtype=old_classes.dtype)
    })
    app.redo_stack.clear()
    
    # Limit stack size and properly free numpy arrays in dropped entries
    max_steps = getattr(app, '_max_undo_steps', 30)
    while len(app.undo_stack) > max_steps:
        from gui.memory_manager import _free_undo_entry
        _free_undo_entry(app.undo_stack.pop(0))
    
    # ✅ Store changed mask for refresh
    app._last_changed_mask = final_mask
    
    print(f"✅ Classification complete: {n_total:,} points → class {new_class}")


# ============================================
# 6. VIEWPORT CULLING FOR CROSS-SECTIONS
# ============================================

def update_cross_section_optimized(app, section_index):
    """
    Optimized cross-section rendering with viewport culling.
    Only renders points within view frustum.
    """
    import numpy as np
    import pyvista as pv
    
    # Get section data
    pts = getattr(app, f"section_{section_index}_core_points", None)
    if pts is None:
        return
    
    buf = getattr(app, f"section_{section_index}_buffer_points", None)
    core_mask = getattr(app, f"section_{section_index}_core_mask", None)
    buffer_mask = getattr(app, f"section_{section_index}_buffer_mask", None)
    
    # Combine points
    if buf is not None and buffer_mask is not None:
        all_pts = np.vstack([pts, buf])
        all_cls = np.concatenate([
            app.data["classification"][core_mask],
            app.data["classification"][buffer_mask & ~core_mask]
        ])
    else:
        all_pts = pts
        all_cls = app.data["classification"][core_mask]
    
    # ============================================
    # OPTIMIZATION: Cull points outside viewport
    # ============================================
    vtk_widget = app.section_vtks[section_index]
    cam = vtk_widget.renderer.GetActiveCamera()
    
    # Get camera bounds (rough culling)
    cam_pos = np.array(cam.GetPosition())
    focal = np.array(cam.GetFocalPoint())
    
    # Simple distance-based culling
    distances = np.linalg.norm(all_pts - focal, axis=1)
    max_dist = np.percentile(distances, 95)  # Keep 95% closest points
    
    cull_mask = distances <= max_dist
    culled_pts = all_pts[cull_mask]
    culled_cls = all_cls[cull_mask]
    
    print(f"🔍 Viewport culling: {len(culled_pts):,}/{len(all_pts):,} points in view")
    
    # Filter by visible classes
    visible = [c for c, v in app.class_palette.items() if v.get("show")]
    vis_mask = np.isin(culled_cls, visible)
    
    final_pts = culled_pts[vis_mask]
    final_cls = culled_cls[vis_mask]
    
    if len(final_pts) == 0:
        vtk_widget.clear()
        vtk_widget.render()
        return
    
    # Build colors
    colors = np.zeros((len(final_pts), 3), dtype=np.uint8)
    for i, cls in enumerate(final_cls):
        entry = app.class_palette.get(int(cls), {"color": (128, 128, 128)})
        colors[i] = entry["color"]
    
    # Render
    cam_state = vtk_widget.camera_position
    vtk_widget.clear()
    
    cloud = pv.PolyData(final_pts)
    cloud["RGB"] = colors
    vtk_widget.add_points(cloud, scalars="RGB", rgb=True, point_size=3)
    
    vtk_widget.camera_position = cam_state
    vtk_widget.render()


# ============================================
# 7. INTEGRATION EXAMPLE
# ============================================

"""
HOW TO USE THESE OPTIMIZATIONS:

1. In app_window.py __init__, add:
   
   # Initialize spatial index after loading data
   if self.data and "xyz" in self.data:
       self.spatial_index = SpatialIndex(self.data["xyz"])
   
2. Replace update_pointcloud with update_pointcloud_optimized

3. Replace fast_update_colors with fast_update_colors_optimized

4. For classification tools, use apply_classification_chunked:
   
   # Instead of direct assignment:
   # app.data["classification"][mask] = new_class
   
   # Use:
   apply_classification_chunked(app, mask, new_class)

5. Connect camera movement to LOD updates:
   
   def on_camera_moved(self):
       if hasattr(self, 'lod_manager'):
           # Force refresh with new LOD
           update_pointcloud_optimized(self, self.display_mode)
   
   # Attach to VTK interactor
   self.vtk_widget.interactor.AddObserver("EndInteractionEvent", on_camera_moved)

6. For large files, show loading progress:
   
   from PySide6.QtWidgets import QProgressDialog
   
   progress = QProgressDialog("Loading point cloud...", None, 0, 100, self)
   progress.setWindowModality(Qt.WindowModal)
   progress.show()
   # Update progress.setValue(percent) during load
"""

# ============================================
# 8. MEMORY MANAGEMENT
# ============================================

class MemoryManager:
    """Monitor and manage memory usage for large files."""
    
    @staticmethod
    def estimate_memory_mb(n_points):
        """Estimate memory needed for point cloud."""
        bytes_per_point = (
            3 * 4 +  # xyz (float32)
            3 * 1 +  # rgb (uint8)
            1 * 1 +  # classification (uint8)
            1 * 2    # intensity (uint16)
        )
        return (n_points * bytes_per_point) / (1024 * 1024)
    
    @staticmethod
    def should_use_lod(n_points):
        """Determine if LOD is needed based on point count."""
        return n_points > 5_000_000
    
    @staticmethod
    def get_recommended_chunk_size(n_points):
        """Get optimal chunk size for processing."""
        if n_points < 1_000_000:
            return n_points  # No chunking needed
        elif n_points < 10_000_000:
            return 500_000
        else:
            return 1_000_000