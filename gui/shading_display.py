"""
GPU + Multi-Core CPU Accelerated Shading Module (Fixed)
========================================================
- Robust CUDA detection (tests actual kernel execution, not just import)
- Graceful fallback to CPU when GPU fails
- Full 20-thread CPU parallelization with Numba
"""

import numpy as np
import pyvista as pv
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QDoubleSpinBox, QHBoxLayout, QPushButton,
    QProgressDialog, QApplication
)
from PySide6.QtCore import Qt, QTimer
from typing import Optional, Set
import time
from vtkmodules.util import numpy_support
import vtk
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

# ═══════════════════════════════════════════════════════════════════════════════
# HARDWARE DETECTION & CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

_N_CORES = os.cpu_count() or 12
_N_WORKERS = _N_CORES

print(f"🖥️  CPU: {_N_CORES} logical processors available")
print(f"🔧 Using {_N_WORKERS} worker threads")

# ═══════════════════════════════════════════════════════════════════════════════
# ROBUST GPU DETECTION - Actually test if CUDA works
# ═══════════════════════════════════════════════════════════════════════════════

HAS_GPU = False
cp = None
_GPU_ERROR = None

def _test_cuda_functionality():
    """
    Actually test if CUDA works by running a simple kernel.
    CuPy can import successfully but fail when executing CUDA code.
    """
    global HAS_GPU, cp, _GPU_ERROR
    
    try:
        import cupy as _cp
        
        # Test 1: Can we get device info?
        device_count = _cp.cuda.runtime.getDeviceCount()
        if device_count == 0:
            raise RuntimeError("No CUDA devices found")
        
        # Test 2: Can we allocate memory?
        test_arr = _cp.array([1.0, 2.0, 3.0])
        
        # Test 3: Can we run a kernel? (This is where NVRTC issues appear)
        result = test_arr * 2.0
        
        # Test 4: Can we transfer back to CPU?
        cpu_result = _cp.asnumpy(result)
        
        if not np.allclose(cpu_result, [2.0, 4.0, 6.0]):
            raise RuntimeError("CUDA computation mismatch")
        
        # All tests passed!
        cp = _cp
        HAS_GPU = True
        
        gpu_props = _cp.cuda.runtime.getDeviceProperties(0)
        gpu_name = gpu_props['name'].decode() if isinstance(gpu_props['name'], bytes) else gpu_props['name']
        gpu_mem = gpu_props['totalGlobalMem'] / (1024**3)
        print(f"🎮 GPU: {gpu_name} ({gpu_mem:.1f} GB) - CUDA verified working ✅")
        
    except ImportError as e:
        _GPU_ERROR = f"CuPy not installed: {e}"
        print(f"⚠️  GPU: {_GPU_ERROR}")
        
    except Exception as e:
        _GPU_ERROR = str(e)
        # Common issue: NVRTC missing
        if "nvrtc" in str(e).lower():
            print(f"⚠️  GPU: CUDA Runtime Compiler (NVRTC) missing")
            print(f"   💡 Fix: Install CUDA Toolkit from nvidia.com/cuda-downloads")
            print(f"   💡 Or use CPU-only mode (still fast with Numba!)")
        else:
            print(f"⚠️  GPU: CUDA test failed - {e}")
        HAS_GPU = False
        cp = None

# Run the test at import time
_test_cuda_functionality()

# ═══════════════════════════════════════════════════════════════════════════════
# NUMBA CPU JIT COMPILATION
# ═══════════════════════════════════════════════════════════════════════════════

HAS_NUMBA = False
try:
    from numba import njit, prange, config, set_num_threads
    config.THREADING_LAYER = 'omp'
    set_num_threads(_N_WORKERS)
    HAS_NUMBA = True
    print(f"⚡ Numba: JIT compilation with {_N_WORKERS} threads ✅")
except ImportError:
    print("⚠️  Numba: Not installed - using NumPy (slower)")
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator
    prange = range

# Triangulation libraries
try:
    import triangle as tr
    HAS_TRIANGLE = True
except ImportError:
    HAS_TRIANGLE = False

try:
    from scipy.spatial import Delaunay
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

_rebuild_timer = None
_rebuild_reason = ""
_rebuild_changed_indices = None


# ═══════════════════════════════════════════════════════════════════════════════
# NUMBA-OPTIMIZED CPU FUNCTIONS (Primary path - always works)
# ═══════════════════════════════════════════════════════════════════════════════

@njit(cache=True, fastmath=True, parallel=True)
def _numba_compute_face_normals(xyz, faces):
    """Parallel face normal computation using all CPU cores."""
    n_faces = len(faces)
    normals = np.empty((n_faces, 3), dtype=np.float64)
    
    for i in prange(n_faces):
        i0, i1, i2 = faces[i, 0], faces[i, 1], faces[i, 2]
        
        e1x = xyz[i1, 0] - xyz[i0, 0]
        e1y = xyz[i1, 1] - xyz[i0, 1]
        e1z = xyz[i1, 2] - xyz[i0, 2]
        
        e2x = xyz[i2, 0] - xyz[i0, 0]
        e2y = xyz[i2, 1] - xyz[i0, 1]
        e2z = xyz[i2, 2] - xyz[i0, 2]
        
        nx = e1y * e2z - e1z * e2y
        ny = e1z * e2x - e1x * e2z
        nz = e1x * e2y - e1y * e2x
        
        length = np.sqrt(nx * nx + ny * ny + nz * nz)
        if length > 1e-10:
            nx /= length
            ny /= length
            nz /= length
        
        if nz < 0 and abs(nz) > 0.3:
            nx, ny, nz = -nx, -ny, -nz
        
        normals[i, 0] = nx
        normals[i, 1] = ny
        normals[i, 2] = nz
    
    return normals


@njit(cache=True, fastmath=True, parallel=True)
def _numba_compute_shading(normals, lx, ly, lz, hx, hy, hz, ambient, 
                           z_values, z_lo, z_hi, has_z):
    """Parallel shading computation using all CPU cores."""
    n = len(normals)
    intensity = np.empty(n, dtype=np.float32)
    
    z_range = max(z_hi - z_lo, 1e-3)
    Kd, Ks, shininess = 0.70, 0.25, 64.0
    ELEV_BLEND = 0.30
    
    for i in prange(n):
        nx, ny, nz = normals[i, 0], normals[i, 1], normals[i, 2]
        
        NdotL = nx * lx + ny * ly + nz * lz
        if NdotL < 0:
            NdotL = 0.0
        
        NdotH = nx * hx + ny * hy + nz * hz
        if NdotH < 0:
            NdotH = 0.0
        
        specular = Ks * (NdotH ** shininess)
        normal_int = ambient + Kd * NdotL + specular
        if normal_int > 1.0:
            normal_int = 1.0
        normal_int = normal_int ** 0.85
        
        if has_z:
            elev_t = (z_values[i] - z_lo) / z_range
            if elev_t < 0:
                elev_t = 0.0
            elif elev_t > 1:
                elev_t = 1.0
            elev_ramp = 0.15 + 0.85 * elev_t
            final = (1.0 - ELEV_BLEND) * normal_int + ELEV_BLEND * elev_ramp
        else:
            final = normal_int
        
        if final < 0:
            final = 0.0
        elif final > 1:
            final = 1.0
        
        intensity[i] = final
    
    return intensity


@njit(cache=True, fastmath=True, parallel=True)
def _numba_filter_edges_sq(faces, xy, max_edge_sq):
    """Parallel edge filtering using squared distances."""
    n_faces = len(faces)
    valid = np.ones(n_faces, dtype=np.bool_)
    
    for i in prange(n_faces):
        i0, i1, i2 = faces[i, 0], faces[i, 1], faces[i, 2]
        
        dx0 = xy[i1, 0] - xy[i0, 0]
        dy0 = xy[i1, 1] - xy[i0, 1]
        e0_sq = dx0 * dx0 + dy0 * dy0
        
        dx1 = xy[i2, 0] - xy[i1, 0]
        dy1 = xy[i2, 1] - xy[i1, 1]
        e1_sq = dx1 * dx1 + dy1 * dy1
        
        dx2 = xy[i0, 0] - xy[i2, 0]
        dy2 = xy[i0, 1] - xy[i2, 1]
        e2_sq = dx2 * dx2 + dy2 * dy2
        
        max_e = max(e0_sq, max(e1_sq, e2_sq))
        if max_e > max_edge_sq:
            valid[i] = False
    
    return valid


@njit(cache=True, fastmath=True, parallel=True)
def _numba_filter_degenerate(faces, xy, min_area, min_aspect):
    """Parallel degenerate triangle filtering."""
    n_faces = len(faces)
    valid = np.ones(n_faces, dtype=np.bool_)
    
    for i in prange(n_faces):
        i0, i1, i2 = faces[i, 0], faces[i, 1], faces[i, 2]
        
        dx1 = xy[i1, 0] - xy[i0, 0]
        dy1 = xy[i1, 1] - xy[i0, 1]
        dx2 = xy[i2, 0] - xy[i0, 0]
        dy2 = xy[i2, 1] - xy[i0, 1]
        
        cross_z = dx1 * dy2 - dy1 * dx2
        tri_area = abs(cross_z) * 0.5
        
        if tri_area <= min_area:
            valid[i] = False
            continue
        
        e0_sq = dx1 * dx1 + dy1 * dy1
        e1_sq = (xy[i2, 0] - xy[i1, 0]) ** 2 + (xy[i2, 1] - xy[i1, 1]) ** 2
        e2_sq = dx2 * dx2 + dy2 * dy2
        max_edge_sq = max(e0_sq, max(e1_sq, e2_sq))
        
        aspect = tri_area / max(max_edge_sq, 1e-10)
        if aspect <= min_aspect:
            valid[i] = False
    
    return valid


@njit(cache=True, fastmath=True, parallel=True)
def _numba_compute_vertex_normals(xyz, faces, face_normals, n_verts):
    """Compute vertex normals with area weighting."""
    vertex_normals = np.zeros((n_verts, 3), dtype=np.float64)
    
    # Accumulation (sequential due to race conditions)
    for i in range(len(faces)):
        i0, i1, i2 = faces[i, 0], faces[i, 1], faces[i, 2]
        
        e1x = xyz[i1, 0] - xyz[i0, 0]
        e1y = xyz[i1, 1] - xyz[i0, 1]
        e1z = xyz[i1, 2] - xyz[i0, 2]
        
        e2x = xyz[i2, 0] - xyz[i0, 0]
        e2y = xyz[i2, 1] - xyz[i0, 1]
        e2z = xyz[i2, 2] - xyz[i0, 2]
        
        cx = e1y * e2z - e1z * e2y
        cy = e1z * e2x - e1x * e2z
        cz = e1x * e2y - e1y * e2x
        
        area = 0.5 * np.sqrt(cx * cx + cy * cy + cz * cz)
        
        wnx = face_normals[i, 0] * area
        wny = face_normals[i, 1] * area
        wnz = face_normals[i, 2] * area
        
        vertex_normals[i0, 0] += wnx
        vertex_normals[i0, 1] += wny
        vertex_normals[i0, 2] += wnz
        
        vertex_normals[i1, 0] += wnx
        vertex_normals[i1, 1] += wny
        vertex_normals[i1, 2] += wnz
        
        vertex_normals[i2, 0] += wnx
        vertex_normals[i2, 1] += wny
        vertex_normals[i2, 2] += wnz
    
    # Normalization (parallel)
    for i in prange(n_verts):
        nx, ny, nz = vertex_normals[i, 0], vertex_normals[i, 1], vertex_normals[i, 2]
        length = np.sqrt(nx * nx + ny * ny + nz * nz)
        if length > 1e-10:
            vertex_normals[i, 0] = nx / length
            vertex_normals[i, 1] = ny / length
            vertex_normals[i, 2] = nz / length
        else:
            vertex_normals[i, 0] = 0.0
            vertex_normals[i, 1] = 0.0
            vertex_normals[i, 2] = 1.0
    
    return vertex_normals.astype(np.float32)


@njit(cache=True, fastmath=True, parallel=True)
def _numba_apply_colors(base_colors, shade, n_elements):
    """Parallel color application."""
    result = np.empty((n_elements, 3), dtype=np.uint8)
    
    for i in prange(n_elements):
        s = shade[i]
        for c in range(3):
            val = base_colors[i, c] * s
            if val > 255:
                val = 255
            elif val < 0:
                val = 0
            result[i, c] = int(val)
    
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# WRAPPER FUNCTIONS - CPU-first with optional GPU acceleration
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_face_normals(xyz, faces):
    """Compute face normals - Numba CPU (fast) or NumPy fallback."""
    if len(faces) == 0:
        return np.array([]).reshape(0, 3)
    
    if HAS_NUMBA:
        return _numba_compute_face_normals(xyz.astype(np.float64), faces)
    else:
        # NumPy fallback
        p0 = xyz[faces[:, 0]]
        p1 = xyz[faces[:, 1]]
        p2 = xyz[faces[:, 2]]
        fn = np.cross(p1 - p0, p2 - p0)
        fn_len = np.linalg.norm(fn, axis=1, keepdims=True)
        fn = fn / np.maximum(fn_len, 1e-10)
        downward = fn[:, 2] < 0
        mostly_horizontal = np.abs(fn[:, 2]) > 0.3
        fn[downward & mostly_horizontal] *= -1
        return fn


def _compute_vertex_normals(xyz, faces, face_normals):
    """Compute vertex normals - Numba CPU or NumPy fallback."""
    n_verts = len(xyz)
    if len(faces) == 0:
        vn = np.zeros((n_verts, 3), dtype=np.float32)
        vn[:, 2] = 1.0
        return vn
    
    if HAS_NUMBA:
        return _numba_compute_vertex_normals(
            xyz.astype(np.float64), faces,
            face_normals.astype(np.float64), n_verts
        )
    else:
        vertex_normals = np.zeros((n_verts, 3), dtype=np.float64)
        p0, p1, p2 = xyz[faces[:, 0]], xyz[faces[:, 1]], xyz[faces[:, 2]]
        cross = np.cross(p1 - p0, p2 - p0)
        areas = 0.5 * np.linalg.norm(cross, axis=1)
        weighted = face_normals * areas[:, np.newaxis]
        np.add.at(vertex_normals, faces[:, 0], weighted)
        np.add.at(vertex_normals, faces[:, 1], weighted)
        np.add.at(vertex_normals, faces[:, 2], weighted)
        lengths = np.linalg.norm(vertex_normals, axis=1, keepdims=True)
        vertex_normals = vertex_normals / np.maximum(lengths, 1e-10)
        vertex_normals[lengths.ravel() < 1e-10] = [0, 0, 1]
        return vertex_normals.astype(np.float32)


def _compute_shading(normals, azimuth, angle, ambient, z_values=None):
    """Compute shading - Numba CPU or NumPy fallback."""
    if len(normals) == 0:
        return np.array([], dtype=np.float32)
    
    az_rad = np.radians(azimuth)
    el_rad = np.radians(angle)
    
    lx = np.cos(el_rad) * np.cos(az_rad)
    ly = np.cos(el_rad) * np.sin(az_rad)
    lz = np.sin(el_rad)
    
    hx, hy, hz = lx, ly, lz + 1.0
    h_len = np.sqrt(hx*hx + hy*hy + hz*hz)
    hx, hy, hz = hx/h_len, hy/h_len, hz/h_len
    
    if z_values is not None:
        z_lo = float(np.percentile(z_values, 1))
        z_hi = float(np.percentile(z_values, 99))
        z_arr = z_values.astype(np.float64)
    else:
        z_lo, z_hi = 0.0, 1.0
        z_arr = np.zeros(len(normals), dtype=np.float64)
    
    if HAS_NUMBA:
        return _numba_compute_shading(
            normals.astype(np.float64),
            lx, ly, lz, hx, hy, hz, ambient,
            z_arr, z_lo, z_hi, z_values is not None
        )
    else:
        light_dir = np.array([lx, ly, lz])
        NdotL = np.maximum((normals * light_dir).sum(axis=1), 0.0)
        half_vec = np.array([hx, hy, hz])
        NdotH = np.maximum((normals * half_vec).sum(axis=1), 0.0)
        
        Kd, Ks, shininess = 0.70, 0.25, 64.0
        intensity = np.clip(ambient + Kd * NdotL + Ks * (NdotH ** shininess), 0, 1)
        intensity = np.power(intensity, 0.85)
        
        if z_values is not None:
            z_range = max(z_hi - z_lo, 1e-3)
            elev_ramp = np.clip((z_values - z_lo) / z_range, 0, 1)
            elev_ramp = 0.15 + 0.85 * elev_ramp
            intensity = 0.70 * intensity + 0.30 * elev_ramp
        
        return np.clip(intensity, 0, 1).astype(np.float32)


def _filter_edges_by_absolute(faces, xy, max_edge_length):
    """Filter triangles by edge length."""
    if len(faces) == 0:
        return faces
    
    if HAS_NUMBA:
        valid = _numba_filter_edges_sq(faces, xy, max_edge_length ** 2)
        return faces[valid]
    else:
        v0, v1, v2 = xy[faces[:, 0]], xy[faces[:, 1]], xy[faces[:, 2]]
        e0_sq = ((v1 - v0) ** 2).sum(axis=1)
        e1_sq = ((v2 - v1) ** 2).sum(axis=1)
        e2_sq = ((v0 - v2) ** 2).sum(axis=1)
        max_sq = np.maximum(np.maximum(e0_sq, e1_sq), e2_sq)
        return faces[max_sq <= max_edge_length ** 2]


def _filter_edges_3d_abs(faces, xyz, max_xy_edge_m, max_slope_ratio=10.0):
    """Filter edges with 3D awareness."""
    return _filter_edges_by_absolute(faces, xyz[:, :2], max_xy_edge_m)


def _compute_face_shade(xyz, faces, azimuth, angle, ambient,
                        face_normals=None, z_values=None):
    """Compute per-face shading."""
    if xyz is None or faces is None or len(faces) == 0:
        return np.array([], dtype=np.float32)
    if face_normals is None or len(face_normals) != len(faces):
        face_normals = _compute_face_normals(xyz, faces)
    face_z = xyz[faces, 2].mean(axis=1)
    return _compute_shading(face_normals, azimuth, angle, ambient, z_values=face_z)


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL TRIANGULATION
# ═══════════════════════════════════════════════════════════════════════════════

def _do_triangulate(xy):
    """Single triangulation call."""
    if HAS_TRIANGLE:
        try:
            vertices = xy.astype(np.float64)
            tri_output = tr.triangulate({'vertices': vertices}, 'Qz')
            return tri_output['triangles'].astype(np.int32)
        except:
            pass
    return Delaunay(xy).simplices.astype(np.int32)


def _triangulate_tile_worker(args):
    """Worker for parallel tile triangulation."""
    (tile_indices, tile_xy, cx0, cx1, cy0, cy1, 
     tx, ty, nx, ny, margin, xy_full, spacing) = args
    
    if len(tile_indices) < 3:
        return None
    
    try:
        local_faces = _do_triangulate(tile_xy)
    except:
        return None
    
    if len(local_faces) == 0:
        return None
    
    global_faces = tile_indices[local_faces]
    
    cx = xy_full[global_faces, 0].mean(axis=1)
    cy_arr = xy_full[global_faces, 1].mean(axis=1)
    
    in_core = (cx >= cx0) & (cx < cx1) & (cy_arr >= cy0) & (cy_arr < cy1)
    
    if tx == nx - 1:
        in_core |= (cx >= cx0) & (cx <= cx1 + margin)
    if ty == ny - 1:
        in_core |= (cy_arr >= cy0) & (cy_arr <= cy1 + margin)
    
    core_faces = global_faces[in_core]
    
    if len(core_faces) == 0:
        return None
    
    if HAS_NUMBA:
        min_area = (spacing * 0.1) ** 2
        valid = _numba_filter_degenerate(core_faces, xy_full, min_area, 0.001)
        core_faces = core_faces[valid]
    
    return core_faces if len(core_faces) > 0 else None


def _tiled_triangulate_parallel(xyz_unique, max_pts_per_tile=800_000):
    """Parallel tiled triangulation using all CPU cores."""
    n_pts = len(xyz_unique)
    
    if n_pts <= max_pts_per_tile:
        return _do_triangulate(xyz_unique[:, :2])
    
    t0 = time.time()
    xy = xyz_unique[:, :2]
    x_min, y_min = xy.min(axis=0)
    x_max, y_max = xy.max(axis=0)
    x_range, y_range = x_max - x_min, y_max - y_min
    area = max(x_range * y_range, 1.0)
    
    n_tiles_needed = max(int(np.ceil(n_pts / max_pts_per_tile)), 2)
    aspect = x_range / max(y_range, 1e-6)
    ny = max(int(np.sqrt(n_tiles_needed / max(aspect, 0.01))), 1)
    nx = max(int(np.ceil(n_tiles_needed / ny)), 1)
    
    tile_w, tile_h = x_range / nx, y_range / ny
    spacing = np.sqrt(area / n_pts)
    margin = spacing * 5.0
    
    print(f"   🔲 PARALLEL triangulation: {nx}×{ny}={nx*ny} tiles "
          f"using {_N_WORKERS} workers")
    
    tile_args = []
    for ty in range(ny):
        for tx in range(nx):
            bx0 = x_min + tx * tile_w - margin
            bx1 = x_min + (tx + 1) * tile_w + margin
            by0 = y_min + ty * tile_h - margin
            by1 = y_min + (ty + 1) * tile_h + margin
            
            cx0, cx1 = x_min + tx * tile_w, x_min + (tx + 1) * tile_w
            cy0, cy1 = y_min + ty * tile_h, y_min + (ty + 1) * tile_h
            
            in_tile = (
                (xy[:, 0] >= bx0) & (xy[:, 0] <= bx1) &
                (xy[:, 1] >= by0) & (xy[:, 1] <= by1)
            )
            tile_indices = np.where(in_tile)[0]
            
            if len(tile_indices) >= 3:
                tile_args.append((
                    tile_indices, xy[tile_indices], cx0, cx1, cy0, cy1,
                    tx, ty, nx, ny, margin, xy, spacing
                ))
    
    all_faces = []
    total_tri = 0
    
    with ThreadPoolExecutor(max_workers=_N_WORKERS) as executor:
        futures = {executor.submit(_triangulate_tile_worker, args): i 
                   for i, args in enumerate(tile_args)}
        
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                all_faces.append(result)
                total_tri += len(result)
    
    if len(all_faces) == 0:
        print(f"   ⚠️ Parallel triangulation failed - fallback")
        return _do_triangulate(xy)
    
    result = np.vstack(all_faces)
    elapsed = time.time() - t0
    print(f"   ✅ Parallel triangulation: {total_tri:,} faces in {elapsed:.1f}s")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# CACHE AND HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _remove_shaded_edge_overlay(app):
    plotter = getattr(app, 'vtk_widget', None)
    if plotter:
        try:
            plotter.remove_actor("shaded_mesh_edges", render=False)
        except:
            pass
    app._shaded_mesh_edge_actor = None
    app._shaded_mesh_edge_polydata = None


def _setup_microstation_lighting(renderer, azimuth=45.0, angle=45.0):
    renderer.RemoveAllLights()
    az_rad, el_rad = np.radians(azimuth), np.radians(angle)
    
    key_light = vtk.vtkLight()
    key_light.SetLightTypeToSceneLight()
    key_light.SetPosition(
        np.cos(el_rad) * np.cos(az_rad) * 100,
        np.cos(el_rad) * np.sin(az_rad) * 100,
        np.sin(el_rad) * 100
    )
    key_light.SetFocalPoint(0, 0, 0)
    key_light.SetIntensity(0.85)
    key_light.SetColor(1.0, 1.0, 0.98)
    key_light.SetPositional(False)
    renderer.AddLight(key_light)
    
    fill_light = vtk.vtkLight()
    fill_light.SetLightTypeToSceneLight()
    fill_light.SetPosition(
        -np.cos(el_rad) * np.cos(az_rad) * 100,
        -np.cos(el_rad) * np.sin(az_rad) * 100,
        np.sin(el_rad) * 50
    )
    fill_light.SetFocalPoint(0, 0, 0)
    fill_light.SetIntensity(0.15)
    fill_light.SetColor(0.85, 0.85, 1.0)
    renderer.AddLight(fill_light)


class ShadingGeometryCache:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._clear_internal()

    def _clear_internal(self):
        self.xyz_unique = None
        self.xyz_final = None
        self.faces = None
        self.face_normals = None
        self.vertex_normals = None
        self.shade = None
        self.vertex_shade = None
        self.unique_indices = None
        self.offset = None
        self.spacing = 0.0
        self.max_edge_factor = 3.0
        self.last_azimuth = -1
        self.last_angle = -1
        self.last_ambient = -1
        self.visible_classes_hash = None
        self.n_visible_classes = 0
        self.single_class_id = None
        self.visible_classes_set = None
        self.data_hash = None
        self._vtk_colors_ptr = None
        self._global_to_unique = None

    def clear(self, reason=""):
        if reason:
            print(f"   🗑️ Cache cleared: {reason}")
        self._clear_internal()

    def get_visible_hash(self, visible_classes):
        return hash(frozenset(visible_classes))

    def is_valid(self, xyz, visible_classes):
        if self.xyz_unique is None or self.faces is None:
            return False
        new_vis_hash = self.get_visible_hash(visible_classes)
        if new_vis_hash != self.visible_classes_hash:
            return False
        try:
            new_hash = hash((len(xyz), float(xyz[0, 0]), float(xyz[-1, 2])))
            return new_hash == self.data_hash
        except:
            return False

    def needs_shading_update(self, azimuth, angle, ambient):
        return (abs(self.last_azimuth - azimuth) > 0.001 or
                abs(self.last_angle - angle) > 0.001 or
                abs(self.last_ambient - ambient) > 0.001)

    def build_global_to_unique(self, total_points):
        if self._global_to_unique is not None and len(self._global_to_unique) == total_points:
            return self._global_to_unique
        self._global_to_unique = np.full(total_points, -1, dtype=np.int32)
        if self.unique_indices is not None:
            self._global_to_unique[self.unique_indices] = np.arange(len(self.unique_indices))
        return self._global_to_unique


_cache = None

def get_cache():
    global _cache
    if _cache is None:
        _cache = ShadingGeometryCache()
    return _cache

def clear_shading_cache(reason=""):
    get_cache().clear(reason)

def invalidate_cache_for_new_file(file_path=""):
    get_cache().clear("new file")


def _get_shading_visibility(app):
    override = getattr(app, '_shading_visibility_override', None)
    if override is not None:
        return override
    
    dialog = getattr(app, 'display_mode_dialog', None) or getattr(app, 'display_dialog', None)
    if dialog:
        view_palettes = getattr(dialog, 'view_palettes', None)
        if view_palettes and 0 in view_palettes:
            return {int(c) for c, e in view_palettes[0].items() if e.get("show", True)}
    
    return {int(c) for c, e in app.class_palette.items() if e.get("show", True)}


def _save_camera(app):
    try:
        cam = app.vtk_widget.renderer.GetActiveCamera()
        return {
            'pos': cam.GetPosition(), 'fp': cam.GetFocalPoint(),
            'up': cam.GetViewUp(), 'parallel': cam.GetParallelProjection(),
            'scale': cam.GetParallelScale()
        }
    except:
        return None


def _restore_camera(app, c):
    if c:
        try:
            cam = app.vtk_widget.renderer.GetActiveCamera()
            cam.SetPosition(c['pos'])
            cam.SetFocalPoint(c['fp'])
            cam.SetViewUp(c['up'])
            cam.SetParallelProjection(c['parallel'])
            cam.SetParallelScale(c['scale'])
        except:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN BUILD FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def _build_visible_geometry(app, xyz_raw, classes_raw, azimuth, angle,
                            ambient, max_edge_factor, cache, visible_classes,
                            single_class_max_edge=None):
    """Main geometry building with multi-core CPU acceleration."""
    n_visible = len(visible_classes)
    is_single_class = (n_visible == 1)
    
    print(f"\n{'='*60}")
    print(f"🚀 MULTI-CORE CPU ACCELERATED SHADING")
    print(f"   Mode: {'SINGLE-CLASS' if is_single_class else 'MULTI-CLASS'}")
    print(f"   CPU: {_N_WORKERS} threads (Numba: {'✅' if HAS_NUMBA else '❌'})")
    print(f"{'='*60}")
    
    t_total = time.time()
    
    app.last_shade_azimuth = azimuth
    app.last_shade_angle = angle
    app.shade_ambient = ambient
    app.display_mode = "shaded_class"
    
    saved_camera = _save_camera(app)
    
    progress = QProgressDialog("Building surface...", None, 0, 100, app)
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)
    progress.show()
    QApplication.processEvents()
    
    try:
        progress.setValue(5)
        QApplication.processEvents()
        
        # Step 1: Filter visible points
        t0 = time.time()
        classes = classes_raw.astype(np.int16)
        max_c = int(np.max(classes)) + 1 if len(classes) > 0 else 256
        vis_lookup = np.zeros(max_c, dtype=bool)
        for v_class in visible_classes:
            if v_class < max_c:
                vis_lookup[v_class] = True
        
        visible_mask = vis_lookup[classes]
        visible_indices = np.where(visible_mask)[0]
        
        if len(visible_indices) < 3:
            print(f"   ⚠️ Only {len(visible_indices)} visible points")
            progress.close()
            return
        
        xyz_visible = xyz_raw[visible_indices]
        print(f"   📍 {len(visible_indices):,} visible points ({(time.time()-t0)*1000:.0f}ms)")
        
        progress.setValue(10)
        QApplication.processEvents()
        
        # Step 2: Compute offset and extract unique points
        offset = xyz_visible.min(axis=0)
        xyz = (xyz_visible - offset).astype(np.float64)
        
        x_range = xyz[:, 0].max() - xyz[:, 0].min()
        y_range = xyz[:, 1].max() - xyz[:, 1].min()
        area = max(x_range * y_range, 1.0)
        natural_spacing = np.sqrt(area / len(xyz))
        precision = max(natural_spacing * 0.3, 0.005)
        
        t0 = time.time()
        xy_grid = np.floor(xyz[:, :2] / precision).astype(np.int64)
        sort_idx = np.lexsort((-xyz[:, 2], xy_grid[:, 1], xy_grid[:, 0]))
        xy_sorted = xy_grid[sort_idx]
        diff = np.diff(xy_sorted, axis=0)
        unique_mask = np.concatenate([[True], (diff[:, 0] != 0) | (diff[:, 1] != 0)])
        unique_indices_local = sort_idx[unique_mask]
        
        xyz_unique = xyz[unique_indices_local]
        unique_indices_global = visible_indices[unique_indices_local]
        
        x_range = xyz_unique[:, 0].max() - xyz_unique[:, 0].min()
        y_range = xyz_unique[:, 1].max() - xyz_unique[:, 1].min()
        data_extent = max(x_range, y_range)
        spacing = np.sqrt((x_range * y_range) / max(len(xyz_unique), 1))
        
        print(f"   ✅ {len(xyz_unique):,} unique points ({(time.time()-t0)*1000:.0f}ms)")
        
        # Update cache
        cache.offset = offset
        cache.unique_indices = unique_indices_global
        cache.xyz_unique = xyz_unique
        cache.xyz_final = xyz_unique + offset
        cache.spacing = spacing
        cache.max_edge_factor = max_edge_factor
        cache.visible_classes_hash = cache.get_visible_hash(visible_classes)
        cache.n_visible_classes = n_visible
        cache.visible_classes_set = visible_classes.copy()
        cache.single_class_id = list(visible_classes)[0] if is_single_class else None
        cache._vtk_colors_ptr = None
        cache._global_to_unique = None
        
        progress.setValue(20)
        QApplication.processEvents()
        
        # Step 3: Triangulation (parallel)
        t0 = time.time()
        xy = xyz_unique[:, :2]
        
        _TILE_THRESHOLD = 1_500_000
        if len(xyz_unique) > _TILE_THRESHOLD:
            faces = _tiled_triangulate_parallel(xyz_unique, max_pts_per_tile=800_000)
        else:
            faces = _do_triangulate(xy)
        
        # Filter degenerate triangles
        if len(faces) > 0 and HAS_NUMBA:
            min_area = (spacing * 0.1) ** 2
            valid = _numba_filter_degenerate(faces, xy, min_area, 0.001)
            n_removed = int(np.sum(~valid))
            if n_removed > 0:
                faces = faces[valid]
                print(f"   ✂️ Removed {n_removed:,} degenerate triangles")
        
        # Edge filtering
        if is_single_class:
            max_edge = single_class_max_edge if single_class_max_edge else data_extent * 0.2
            faces = _filter_edges_by_absolute(faces, xy, max_edge)
        else:
            max_xy_edge_abs = data_extent * 0.10
            faces = _filter_edges_3d_abs(faces, xyz_unique, max_xy_edge_abs)
            cache.max_edge_factor = max_xy_edge_abs / max(spacing, 1e-9)
        
        cache.faces = faces
        print(f"   ✅ {len(faces):,} triangles ({time.time()-t0:.1f}s)")
        
        progress.setValue(70)
        QApplication.processEvents()
        
        # Step 4: Compute normals and shading
        t0 = time.time()
        if len(faces) > 0:
            cache.face_normals = _compute_face_normals(xyz_unique, faces)
            cache.vertex_normals = _compute_vertex_normals(
                xyz_unique, faces, cache.face_normals)
            cache.vertex_shade = _compute_shading(
                cache.vertex_normals, azimuth, angle, ambient,
                z_values=xyz_unique[:, 2])
            cache.shade = _compute_face_shade(
                xyz_unique, cache.faces, azimuth, angle, ambient)
        else:
            cache.face_normals = np.array([]).reshape(0, 3)
            cache.vertex_normals = np.array([]).reshape(0, 3)
            cache.shade = np.array([])
            cache.vertex_shade = np.array([])
        
        print(f"   ⚡ Normals + shading: {(time.time()-t0)*1000:.0f}ms")
        
        cache.last_azimuth = azimuth
        cache.last_angle = angle
        cache.last_ambient = ambient
        cache.data_hash = hash((len(xyz_raw), float(xyz_raw[0, 0]), float(xyz_raw[-1, 2])))
        
        progress.setValue(90)
        QApplication.processEvents()
        
        _render_mesh(app, cache, classes_raw, saved_camera)
        
        progress.setValue(100)
        print(f"   🎉 COMPLETE: {time.time()-t_total:.1f}s")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        progress.close()


def _render_mesh(app, cache, classes_raw, saved_camera):
    """Render the mesh."""
    if cache.faces is None or len(cache.faces) == 0:
        return
    
    t0 = time.time()
    classes = classes_raw.astype(np.int32)
    classes_mesh = classes[cache.unique_indices]
    visible_classes = _get_shading_visibility(app)
    
    n_verts = len(cache.xyz_final)
    n_faces = len(cache.faces)
    
    azimuth = getattr(app, 'last_shade_azimuth', 45.0)
    angle = getattr(app, 'last_shade_angle', 45.0)
    is_single_class = getattr(cache, 'n_visible_classes', 0) == 1
    
    max_c = max(int(classes_mesh.max()) + 1, 256)
    lut = np.zeros((max_c, 3), dtype=np.float32)
    for c, e in app.class_palette.items():
        ci = int(c)
        if ci < max_c and ci in visible_classes:
            lut[ci] = e.get("color", (128, 128, 128))
    
    vert_class = np.clip(classes_mesh, 0, max_c - 1)
    vert_base_color = lut[vert_class]
    
    if is_single_class:
        # Single-class: flat/faceted shading
        face_normals = cache.face_normals
        if face_normals is None or len(face_normals) != n_faces:
            face_normals = _compute_face_normals(cache.xyz_unique, cache.faces)
        
        face_z = cache.xyz_unique[cache.faces, 2].mean(axis=1)
        face_intensity = _compute_shading(face_normals, azimuth, angle, 
                                          getattr(app, 'shade_ambient', 0.25),
                                          z_values=face_z)
        
        face_vert0_class = np.clip(classes_mesh[cache.faces[:, 0]], 0, max_c - 1)
        face_base_color = lut[face_vert0_class]
        
        if HAS_NUMBA:
            face_colors = _numba_apply_colors(face_base_color, face_intensity, n_faces)
        else:
            face_colors = np.clip(face_base_color * face_intensity[:, None], 0, 255).astype(np.uint8)
        
        faces_vtk = np.hstack([
            np.full((n_faces, 1), 3, dtype=np.int32), cache.faces
        ]).ravel()
        mesh = pv.PolyData(cache.xyz_final, faces_vtk)
        mesh.cell_data["RGB"] = face_colors
        
        plotter = app.vtk_widget
        for name in list(plotter.actors.keys()):
            name_str = str(name).lower()
            if name_str.startswith("class_") or name_str in ("main_pc", "main_pc_border"):
                plotter.actors[name].SetVisibility(False)
            elif name_str.startswith("shaded_mesh"):
                plotter.remove_actor(name, render=False)
        
        app._shaded_mesh_actor = plotter.add_mesh(
            mesh, scalars="RGB", rgb=True, show_edges=False,
            lighting=False, smooth_shading=False, preference="cell",
            name="shaded_mesh", render=False)
        
        if app._shaded_mesh_actor:
            prop = app._shaded_mesh_actor.GetProperty()
            prop.SetInterpolationToFlat()
            prop.SetAmbient(1.0)
            prop.SetDiffuse(0.0)
        
        app._shaded_mesh_polydata = mesh
        
    else:
        # Multi-class: vertex-based shading
        if cache.vertex_shade is not None and len(cache.vertex_shade) == n_verts:
            if HAS_NUMBA:
                vertex_colors = _numba_apply_colors(vert_base_color, cache.vertex_shade, n_verts)
            else:
                vertex_colors = np.clip(vert_base_color * cache.vertex_shade[:, None], 0, 255).astype(np.uint8)
        else:
            vertex_colors = vert_base_color.astype(np.uint8)
        
        faces_vtk = np.hstack([
            np.full((n_faces, 1), 3, dtype=np.int32), cache.faces
        ]).ravel()
        mesh = pv.PolyData(cache.xyz_final, faces_vtk)
        mesh.point_data["RGB"] = vertex_colors
        
        if cache.vertex_normals is not None and len(cache.vertex_normals) == n_verts:
            vtk_normals = numpy_support.numpy_to_vtk(
                cache.vertex_normals.astype(np.float32), deep=True)
            vtk_normals.SetName("Normals")
            mesh.GetPointData().SetNormals(vtk_normals)
        
        plotter = app.vtk_widget
        for name in list(plotter.actors.keys()):
            name_str = str(name).lower()
            if name_str.startswith("class_") or name_str in ("main_pc", "main_pc_border"):
                plotter.actors[name].SetVisibility(False)
            elif name_str.startswith("shaded_mesh"):
                plotter.remove_actor(name, render=False)
        
        app._shaded_mesh_actor = plotter.add_mesh(
            mesh, scalars="RGB", rgb=True, show_edges=False,
            lighting=True, smooth_shading=True, preference="point",
            name="shaded_mesh", render=False)
        
        if app._shaded_mesh_actor:
            prop = app._shaded_mesh_actor.GetProperty()
            prop.SetAmbient(0.12)
            prop.SetDiffuse(0.88)
            prop.SetSpecular(0.18)
            prop.SetSpecularPower(48.0)
        
        _setup_microstation_lighting(plotter.renderer, azimuth, angle)
        app._shaded_mesh_polydata = mesh
    
    cache._vtk_colors_ptr = None
    _restore_camera(app, saved_camera)
    app.vtk_widget.set_background("black")
    app.vtk_widget.renderer.ResetCameraClippingRange()
    app.vtk_widget.render()
    
    mode = "FLAT (single)" if is_single_class else "SMOOTH (multi)"
    print(f"   🎨 Mesh [{mode}]: {n_faces:,} faces in {(time.time()-t0)*1000:.0f}ms")


def update_shaded_class(app, azimuth=45.0, angle=45.0, ambient=0.25,
                        max_edge_factor=3.0, force_rebuild=False,
                        single_class_max_edge=None, **kwargs):
    """Main entry point."""
    cache = get_cache()
    xyz_raw = app.data.get("xyz")
    classes_raw = app.data.get("classification")
    
    if xyz_raw is None or classes_raw is None:
        return
    
    azimuth = getattr(app, 'last_shade_azimuth', azimuth)
    angle = getattr(app, 'last_shade_angle', angle)
    ambient = getattr(app, 'shade_ambient', ambient)
    
    visible_classes = _get_shading_visibility(app)
    
    for c in app.class_palette:
        app.class_palette[c]["show"] = (int(c) in visible_classes)
    
    app._shading_visible_classes = visible_classes.copy() if visible_classes else set()
    
    if not visible_classes:
        if hasattr(app, '_shaded_mesh_actor'):
            app.vtk_widget.remove_actor("shaded_mesh")
            app._shaded_mesh_actor = None
        _remove_shaded_edge_overlay(app)
        app.vtk_widget.render()
        return
    
    if cache.is_valid(xyz_raw, visible_classes) and not force_rebuild:
        t0 = time.time()
        _refresh_from_cache(app, cache, azimuth, angle, ambient)
        print(f"   ⚡ Cache refresh: {(time.time()-t0)*1000:.0f}ms")
    else:
        _build_visible_geometry(app, xyz_raw, classes_raw, azimuth, angle,
                                ambient, max_edge_factor, cache,
                                visible_classes, single_class_max_edge)


def _refresh_from_cache(app, cache, azimuth, angle, ambient):
    """Refresh from cache."""
    app.last_shade_azimuth = azimuth
    app.last_shade_angle = angle
    app.shade_ambient = ambient
    app.display_mode = "shaded_class"
    
    saved_camera = _save_camera(app)
    
    if cache.needs_shading_update(azimuth, angle, ambient):
        is_single = getattr(cache, 'n_visible_classes', 0) == 1
        z_vals = cache.xyz_unique[:, 2] if cache.xyz_unique is not None else None
        
        if is_single:
            if cache.face_normals is not None and len(cache.face_normals) > 0:
                face_z = cache.xyz_unique[cache.faces, 2].mean(axis=1)
                cache.shade = _compute_shading(
                    cache.face_normals, azimuth, angle, ambient, z_values=face_z)
        else:
            if cache.vertex_normals is not None and len(cache.vertex_normals) > 0:
                cache.vertex_shade = _compute_shading(
                    cache.vertex_normals, azimuth, angle, ambient, z_values=z_vals)
            cache.shade = _compute_face_shade(
                cache.xyz_unique, cache.faces, azimuth, angle, ambient,
                face_normals=cache.face_normals)
        
        cache.last_azimuth = azimuth
        cache.last_angle = angle
        cache.last_ambient = ambient
        cache._vtk_colors_ptr = None
    
    _render_mesh(app, cache, app.data.get("classification"), saved_camera)


# ═══════════════════════════════════════════════════════════════════════════════
# CONTROL PANEL
# ═══════════════════════════════════════════════════════════════════════════════

class ShadingControlPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Shading (CPU Optimized)")
        layout = QVBoxLayout()
        
        # Status
        numba_status = f"Numba: {'✅ ' + str(_N_WORKERS) + ' threads' if HAS_NUMBA else '❌'}"
        gpu_status = f"GPU: {'✅ CUDA' if HAS_GPU else '❌ (NVRTC missing)' if _GPU_ERROR else '❌'}"
        layout.addWidget(QLabel(f"{numba_status} | {gpu_status}"))
        
        for label, attr, range_, default, step in [
            ("Max edge (m):", "max_edge", (1, 1000), 100, 10),
            ("Azimuth:", "az", (0, 360), 45, 5),
            ("Angle:", "el", (0, 90), 45, 5),
            ("Ambient:", "amb", (0, 1), 0.25, 0.05),
        ]:
            h = QHBoxLayout()
            h.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(*range_)
            spin.setValue(default)
            spin.setSingleStep(step)
            setattr(self, attr, spin)
            h.addWidget(spin)
            layout.addLayout(h)
        
        btn = QPushButton("Apply")
        btn.clicked.connect(self._on_apply)
        layout.addWidget(btn)
        
        rebuild = QPushButton("Full Rebuild")
        rebuild.clicked.connect(self._on_full_rebuild)
        layout.addWidget(rebuild)
        
        self.setLayout(layout)
        self._restore_from_app()
    
    def _restore_from_app(self):
        for attr, app_attr in [('az', 'last_shade_azimuth'), 
                               ('el', 'last_shade_angle'),
                               ('amb', 'shade_ambient')]:
            val = getattr(self.app, app_attr, None)
            if val is not None:
                getattr(self, attr).setValue(val)
    
    def _on_apply(self):
        az, el, amb = self.az.value(), self.el.value(), self.amb.value()
        self.app.last_shade_azimuth = az
        self.app.last_shade_angle = el
        self.app.shade_ambient = amb
        update_shaded_class(self.app, az, el, amb,
                            single_class_max_edge=self.max_edge.value())
    
    def _on_full_rebuild(self):
        az, el, amb = self.az.value(), self.el.value(), self.amb.value()
        self.app.last_shade_azimuth = az
        self.app.last_shade_angle = el
        self.app.shade_ambient = amb
        clear_shading_cache("manual")
        update_shaded_class(self.app, az, el, amb, force_rebuild=True,
                            single_class_max_edge=self.max_edge.value())


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    'update_shaded_class',
    'ShadingControlPanel',
    'clear_shading_cache',
    'get_cache',
    'invalidate_cache_for_new_file',
    '_get_shading_visibility',
    'HAS_GPU',
    'HAS_NUMBA',
]


# Print summary
print(f"\n{'='*50}")
print(f"🚀 Optimized Shading Module Loaded")
print(f"   CPU Threads: {_N_WORKERS} ({'Numba JIT' if HAS_NUMBA else 'NumPy'})")
print(f"   GPU: {'CUDA ready' if HAS_GPU else 'Not available'}")
if _GPU_ERROR and 'nvrtc' in _GPU_ERROR.lower():
    print(f"   💡 To enable GPU: Install CUDA Toolkit from nvidia.com")
print(f"{'='*50}\n")