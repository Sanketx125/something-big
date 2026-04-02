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

import multiprocessing
from concurrent.futures import ThreadPoolExecutor

_LARGE_MESH_THRESHOLD = 50_000_000
_BASE_GRID_PRECISION_FACTOR = 0.3
_MIN_GRID_PRECISION_M = 0.005
_MAX_UNIQUE_POINTS = 350_000       # Single-class triangulation target
_MULTI_CLASS_TARGET_UNIQUE_POINTS = 2_500_000
_TILE_THRESHOLD = 150_000          # Activate parallel tiling above this

_rebuild_timer = None
_rebuild_reason = ""
_rebuild_changed_indices = None

# ── NUMBA JIT ACCELERATION ──────────────────────────────────────────────
try:
    from numba import njit, prange, types
    from numba.typed import Dict
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

if HAS_NUMBA:
    @njit(parallel=True, fastmath=True)
    def _compute_face_normals_fast(xyz, faces):
        n_faces = faces.shape[0]
        fn = np.empty((n_faces, 3), dtype=np.float64)
        for i in prange(n_faces):
            v0x, v0y, v0z = xyz[faces[i, 0]]
            v1x, v1y, v1z = xyz[faces[i, 1]]
            v2x, v2y, v2z = xyz[faces[i, 2]]
            
            ax, ay, az = v1x - v0x, v1y - v0y, v1z - v0z
            bx, by, bz = v2x - v0x, v2y - v0y, v2z - v0z
            
            nx = ay * bz - az * by
            ny = az * bx - ax * bz
            nz = ax * by - ay * bx
            
            length = np.sqrt(nx*nx + ny*ny + nz*nz)
            if length > 1e-10:
                nx, ny, nz = nx/length, ny/length, nz/length
                
            if nz < 0 and abs(nz) > 0.3:
                nx, ny, nz = -nx, -ny, -nz
                
            fn[i, 0] = nx
            fn[i, 1] = ny
            fn[i, 2] = nz
        return fn


# ── NUMBA WARMUP — pre-compile in background thread ─────────────────
if HAS_NUMBA:
    def _warmup_numba_jit():
        """Pre-compile all numba functions with tiny dummy data.
        Runs in daemon thread → doesn't block app startup.
        First real call will be instant instead of 2-5s penalty.
        """
        try:
            _d_xyz = np.array([[0,0,0],[1,0,0],[0,1,0],[1,1,1]], dtype=np.float64)
            _d_f = np.array([[0,1,2],[1,2,3]], dtype=np.int32)
            _d_fn = _compute_face_normals_fast(_d_xyz, _d_f)
            _compute_vertex_normals_fast(_d_xyz, _d_f, _d_fn)
            _d_z = np.array([0.0, 1.0], dtype=np.float64)
            _compute_shading_fast(_d_fn, _d_z, 0.5,0.5,0.7, 0.3,0.3,0.9, 0.25, 0.0, 1.0)
            _fast_centroids_z(_d_xyz, _d_f)
            _d_keys = np.array([0, 1, 1, 2], dtype=np.int64)
            _select_highest_grid_points_fast(_d_keys, _d_z[[0, 1, 1, 0]])
        except Exception:
            pass

    @njit(fastmath=True)
    def _select_highest_grid_points_fast(grid_key, z_values):
        best_indices = Dict.empty(
            key_type=types.int64,
            value_type=types.int64,
        )
        n = grid_key.shape[0]
        for i in range(n):
            key = grid_key[i]
            if key in best_indices:
                best_i = best_indices[key]
                if z_values[i] > z_values[best_i]:
                    best_indices[key] = i
            else:
                best_indices[key] = i

        out = np.empty(len(best_indices), dtype=np.int64)
        j = 0
        for idx in best_indices.values():
            out[j] = idx
            j += 1
        return out

    @njit(fastmath=True)
    def _compute_vertex_normals_fast(xyz, faces, fn):
        n_verts = xyz.shape[0]
        vn = np.zeros((n_verts, 3), dtype=np.float64)
        n_faces = faces.shape[0]
        for i in range(n_faces):
            v0, v1, v2 = faces[i, 0], faces[i, 1], faces[i, 2]
            
            p0x, p0y, p0z = xyz[v0]
            p1x, p1y, p1z = xyz[v1]
            p2x, p2y, p2z = xyz[v2]
            ax, ay, az = p1x - p0x, p1y - p0y, p1z - p0z
            bx, by, bz = p2x - p0x, p2y - p0y, p2z - p0z
            cx = ay * bz - az * by
            cy = az * bx - ax * bz
            cz = ax * by - ay * bx
            area = 0.5 * np.sqrt(cx*cx + cy*cy + cz*cz)
            
            wx, wy, wz = fn[i, 0] * area, fn[i, 1] * area, fn[i, 2] * area
            vn[v0, 0] += wx; vn[v0, 1] += wy; vn[v0, 2] += wz
            vn[v1, 0] += wx; vn[v1, 1] += wy; vn[v1, 2] += wz
            vn[v2, 0] += wx; vn[v2, 1] += wy; vn[v2, 2] += wz
            
        for i in range(n_verts):
            nx, ny, nz = vn[i, 0], vn[i, 1], vn[i, 2]
            length = np.sqrt(nx*nx + ny*ny + nz*nz)
            if length < 1e-10:
                vn[i, 0] = 0.0; vn[i, 1] = 0.0; vn[i, 2] = 1.0
            else:
                vn[i, 0] = nx/length; vn[i, 1] = ny/length; vn[i, 2] = nz/length
        return vn

    @njit(parallel=True, fastmath=True)
    def _compute_shading_fast(normals, z_values, lx, ly, lz, hx, hy, hz, ambient, z_lo, z_range):
        n = normals.shape[0]
        shade = np.empty(n, dtype=np.float32)
        has_z = z_range > 1e-5
        
        for i in prange(n):
            nx, ny, nz = normals[i, 0], normals[i, 1], normals[i, 2]
            ndotl = max(0.0, nx*lx + ny*ly + nz*lz)
            ndoth = max(0.0, nx*hx + ny*hy + nz*hz)
            
            specular = 0.25 * (ndoth ** 64.0)
            intensity = ambient + 0.70 * ndotl + specular
            intensity = intensity ** 0.85
            intensity = min(max(intensity, 0.0), 1.0)
            
            if has_z:
                elev_ramp = min(max((z_values[i] - z_lo) / z_range, 0.0), 1.0)
                elev_ramp = 0.15 + 0.85 * elev_ramp
                intensity = 0.70 * intensity + 0.30 * elev_ramp
                
            shade[i] = min(max(intensity, 0.0), 1.0)
        return shade

    @njit(parallel=True, fastmath=True)
    def _fast_centroids_z(xyz, faces):
        n = faces.shape[0]
        fz = np.empty(n, dtype=np.float64)
        for i in prange(n):
            fz[i] = (xyz[faces[i,0], 2] + xyz[faces[i,1], 2] + xyz[faces[i,2], 2]) / 3.0
        return fz
# ────────────────────────────────────────────────────────────────────────


if HAS_NUMBA:
    import threading
    threading.Thread(target=_warmup_numba_jit, daemon=True).start()


def _make_face_shade_placeholder(n_faces: int, ambient: float = 1.0):
    if n_faces <= 0:
        return np.array([], dtype=np.float32)
    return np.full(n_faces, float(np.clip(ambient, 0.0, 1.0)),
                   dtype=np.float32)


def _select_highest_points_per_grid_cell(xyz, precision):
    if xyz is None or len(xyz) == 0:
        return np.array([], dtype=np.intp)

    xy_grid = np.floor(xyz[:, :2] / precision).astype(np.int64)
    gx = xy_grid[:, 0] - xy_grid[:, 0].min()
    gy = xy_grid[:, 1] - xy_grid[:, 1].min()
    gy_span = int(gy.max()) + 1

    if HAS_NUMBA and gx.max() < 2**30 and gy_span < 2**30:
        grid_key = gx * gy_span + gy
        unique_indices_local = _select_highest_grid_points_fast(
            grid_key, xyz[:, 2].astype(np.float64, copy=False))
        if len(unique_indices_local) > 1:
            order = np.argsort(grid_key[unique_indices_local], kind='mergesort')
            unique_indices_local = unique_indices_local[order]
        return unique_indices_local.astype(np.intp, copy=False)

    if gx.max() < 2**30 and gy_span < 2**30:
        grid_key = gx * gy_span + gy
        sort_idx = np.lexsort((-xyz[:, 2], grid_key))
        sorted_keys = grid_key[sort_idx]
        unique_mask = np.concatenate([[True], np.diff(sorted_keys) != 0])
    else:
        sort_idx = np.lexsort((-xyz[:, 2], xy_grid[:, 1], xy_grid[:, 0]))
        xy_sorted = xy_grid[sort_idx]
        diff = np.diff(xy_sorted, axis=0)
        unique_mask = np.concatenate(
            [[True], (diff[:, 0] != 0) | (diff[:, 1] != 0)])

    return sort_idx[unique_mask].astype(np.intp, copy=False)


def triangulate_with_triangle(xy: np.ndarray) -> np.ndarray:
    if not HAS_TRIANGLE:
        raise ImportError("'triangle' library not installed")
    vertices = xy.astype(np.float64)
    tri_input = {'vertices': vertices}
    tri_output = tr.triangulate(tri_input, 'Qz')
    return tri_output['triangles'].astype(np.int32)


def triangulate_scipy_direct(xy: np.ndarray) -> np.ndarray:
    tri = Delaunay(xy)
    return tri.simplices.astype(np.int32)


def _do_triangulate(xy):
    if HAS_TRIANGLE:
        try:
            return triangulate_with_triangle(xy)
        except:
            pass
    return triangulate_scipy_direct(xy)


def _triangulate_tile_worker(tile_xy):
    try:
        if HAS_SCIPY:
            tri = Delaunay(tile_xy.astype(np.float64))
            return tri.simplices.astype(np.int32)
        return _do_triangulate(tile_xy)
    except Exception:
        return np.array([], dtype=np.int32).reshape(0, 3)
    

def _filter_edges_by_absolute(faces, xy, max_edge_length):
    if len(faces) == 0:
        return faces
    v0, v1, v2 = xy[faces[:, 0]], xy[faces[:, 1]], xy[faces[:, 2]]
    e0_sq = ((v1 - v0) ** 2).sum(axis=1)
    e1_sq = ((v2 - v1) ** 2).sum(axis=1)
    e2_sq = ((v0 - v2) ** 2).sum(axis=1)
    max_edge_sq = np.maximum(np.maximum(e0_sq, e1_sq), e2_sq)
    return faces[max_edge_sq <= max_edge_length * max_edge_length]


def _filter_edges_3d_abs(faces, xyz, max_xy_edge_m, max_slope_ratio=10.0):
    if len(faces) == 0:
        return faces
    xy = xyz[:, :2]
    v0x, v1x, v2x = xy[faces[:, 0]], xy[faces[:, 1]], xy[faces[:, 2]]
    e0_sq = ((v1x - v0x) ** 2).sum(axis=1)
    e1_sq = ((v2x - v1x) ** 2).sum(axis=1)
    e2_sq = ((v0x - v2x) ** 2).sum(axis=1)
    max_xy_edge_sq = np.maximum(np.maximum(e0_sq, e1_sq), e2_sq)
    return faces[max_xy_edge_sq <= max_xy_edge_m * max_xy_edge_m]


def _compute_face_normals(xyz, faces):
    if len(faces) == 0:
        return np.array([]).reshape(0, 3)
    if HAS_NUMBA:
        return _compute_face_normals_fast(xyz, faces)
        
    p0, p1, p2 = xyz[faces[:, 0]], xyz[faces[:, 1]], xyz[faces[:, 2]]
    fn = np.cross(p1 - p0, p2 - p0)
    fn_len = np.linalg.norm(fn, axis=1, keepdims=True)
    fn = fn / np.maximum(fn_len, 1e-10)
    downward = fn[:, 2] < 0
    mostly_horizontal = np.abs(fn[:, 2]) > 0.3
    flip_mask = downward & mostly_horizontal
    fn[flip_mask] *= -1
    return fn


def _compute_vertex_normals(xyz, faces, face_normals):
    if len(faces) == 0:
        n_verts = len(xyz)
        vn = np.zeros((n_verts, 3), dtype=np.float64)
        vn[:, 2] = 1.0
        return vn.astype(np.float32)

    if HAS_NUMBA:
        return _compute_vertex_normals_fast(xyz, faces, face_normals).astype(np.float32)

    n_verts = len(xyz)
    p0, p1, p2 = xyz[faces[:, 0]], xyz[faces[:, 1]], xyz[faces[:, 2]]
    cross = np.cross(p1 - p0, p2 - p0)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    weighted = face_normals * areas[:, np.newaxis]

    v0 = faces[:, 0]
    v1 = faces[:, 1]
    v2 = faces[:, 2]
    vn = np.empty((n_verts, 3), dtype=np.float64)
    for d in range(3):
        axis_weights = weighted[:, d]
        vn[:, d] = (
            np.bincount(v0, weights=axis_weights, minlength=n_verts) +
            np.bincount(v1, weights=axis_weights, minlength=n_verts) +
            np.bincount(v2, weights=axis_weights, minlength=n_verts)
        )

    lens = np.linalg.norm(vn, axis=1, keepdims=True)
    vn /= np.maximum(lens, 1e-10)
    vn[lens.ravel() < 1e-10] = [0.0, 0.0, 1.0]
    return vn.astype(np.float32)


def _recompute_vertex_normals_partial(cache, patch_face_start_idx):
    if (cache.face_normals is None or cache.faces is None or len(cache.faces) == 0):
        return
    if patch_face_start_idx >= len(cache.faces):
        return
    if cache.xyz_unique is None or len(cache.xyz_unique) == 0:
        return
    n_verts_needed = len(cache.xyz_unique)
    if cache.vertex_normals is None or len(cache.vertex_normals) < n_verts_needed:
        n_old = len(cache.vertex_normals) if cache.vertex_normals is not None else 0
        n_add = n_verts_needed - n_old
        new_normals = np.zeros((n_add, 3), dtype=np.float32)
        new_normals[:, 2] = 1.0
        if cache.vertex_normals is None or n_old == 0:
            cache.vertex_normals = new_normals
        else:
            cache.vertex_normals = np.vstack([cache.vertex_normals, new_normals])
    if cache.vertex_shade is None or len(cache.vertex_shade) < n_verts_needed:
        n_old = len(cache.vertex_shade) if cache.vertex_shade is not None else 0
        n_add = n_verts_needed - n_old
        amb = cache.last_ambient if cache.last_ambient >= 0 else 0.25
        new_shade = np.full(n_add, float(amb), dtype=np.float32)
        if cache.vertex_shade is None or n_old == 0:
            cache.vertex_shade = new_shade
        else:
            cache.vertex_shade = np.concatenate([cache.vertex_shade, new_shade])
    patch_verts = np.unique(cache.faces[patch_face_start_idx:].ravel())
    patch_verts = patch_verts[patch_verts < n_verts_needed]
    if len(patch_verts) == 0:
        return
    v0_adj = np.isin(cache.faces[:, 0], patch_verts)
    v1_adj = np.isin(cache.faces[:, 1], patch_verts)
    v2_adj = np.isin(cache.faces[:, 2], patch_verts)
    adj_mask = v0_adj | v1_adj | v2_adj
    adj_faces = cache.faces[adj_mask]
    adj_fn = cache.face_normals[adj_mask]
    if len(adj_faces) == 0:
        return
    p0 = cache.xyz_unique[adj_faces[:, 0]]
    p1 = cache.xyz_unique[adj_faces[:, 1]]
    p2 = cache.xyz_unique[adj_faces[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    weighted = adj_fn * areas[:, None]
    cache.vertex_normals[patch_verts] = 0.0
    np.add.at(cache.vertex_normals, adj_faces[:, 0], weighted)
    np.add.at(cache.vertex_normals, adj_faces[:, 1], weighted)
    np.add.at(cache.vertex_normals, adj_faces[:, 2], weighted)
    lens = np.linalg.norm(cache.vertex_normals[patch_verts], axis=1, keepdims=True)
    cache.vertex_normals[patch_verts] /= np.maximum(lens, 1e-10)
    if (cache.vertex_shade is not None
            and len(cache.vertex_shade) >= n_verts_needed
            and cache.last_azimuth >= 0):
        patch_normals = cache.vertex_normals[patch_verts]
        patch_z = cache.xyz_unique[patch_verts, 2]
        az_r = np.radians(cache.last_azimuth)
        el_r = np.radians(cache.last_angle)
        amb = cache.last_ambient
        light_dir = np.array([
            np.cos(el_r) * np.cos(az_r),
            np.cos(el_r) * np.sin(az_r),
            np.sin(el_r)
        ], dtype=np.float64)
        light_dir /= np.linalg.norm(light_dir)
        N = patch_normals.astype(np.float64)
        NdotL = np.maximum((N * light_dir).sum(axis=1), 0.0)
        view_dir = np.array([0.0, 0.0, 1.0])
        half_vec = light_dir + view_dir
        half_vec /= np.linalg.norm(half_vec)
        NdotH = np.maximum((N * half_vec).sum(axis=1), 0.0)
        Kd = 0.70
        Ks = 0.25
        shininess = 64.0
        specular = Ks * (NdotH ** shininess)
        normal_intensity = np.clip(amb + Kd * NdotL + specular, 0.0, 1.0)
        normal_intensity = np.power(normal_intensity, 0.85)
        z_all = cache.xyz_unique[:, 2]
        z_lo = float(np.percentile(z_all, 1))
        z_hi = float(np.percentile(z_all, 99))
        z_range = max(z_hi - z_lo, 1e-3)
        elev_ramp = np.clip((patch_z - z_lo) / z_range, 0.0, 1.0)
        elev_ramp = 0.15 + 0.85 * elev_ramp
        ELEV_BLEND = 0.30
        intensity = (1.0 - ELEV_BLEND) * normal_intensity + ELEV_BLEND * elev_ramp
        cache.vertex_shade[patch_verts] = np.clip(
            intensity, 0.0, 1.0).astype(np.float32)


def _compute_shading(normals, azimuth, angle, ambient, z_values=None):
    if len(normals) == 0:
        return np.array([])
    az, el = np.radians(azimuth), np.radians(angle)
    
    lx = np.cos(el) * np.cos(az)
    ly = np.cos(el) * np.sin(az)
    lz = np.sin(el)
    
    hx, hy, hz = lx, ly, lz + 1.0
    hlen = np.sqrt(hx*hx + hy*hy + hz*hz)
    if hlen > 1e-10:
        hx, hy, hz = hx/hlen, hy/hlen, hz/hlen

    if HAS_NUMBA:
        if z_values is not None and len(z_values) == len(normals):
            z_lo = float(np.percentile(z_values, 1))
            z_hi = float(np.percentile(z_values, 99))
            z_range = max(z_hi - z_lo, 1e-3)
        else:
            z_lo, z_range = 0.0, 0.0
            z_values = np.empty(0, dtype=np.float64)
            
        return _compute_shading_fast(
            normals, z_values, lx, ly, lz, hx, hy, hz, ambient, z_lo, z_range
        )

    light_dir = np.array([lx, ly, lz], dtype=np.float64)
    NdotL = np.maximum((normals * light_dir).sum(axis=1), 0.0)
    half_vec = np.array([hx, hy, hz], dtype=np.float64)
    NdotH = np.maximum((normals * half_vec).sum(axis=1), 0.0)
    
    specular = 0.25 * (NdotH ** 64.0)
    normal_intensity = np.clip(ambient + 0.70 * NdotL + specular, 0.0, 1.0)
    normal_intensity = np.power(normal_intensity, 0.85)
    
    if z_values is not None and len(z_values) == len(normals):
        z_lo = float(np.percentile(z_values, 1))
        z_hi = float(np.percentile(z_values, 99))
        z_range = max(z_hi - z_lo, 1e-3)
        elev_ramp = np.clip((z_values - z_lo) / z_range, 0.0, 1.0)
        elev_ramp = 0.15 + 0.85 * elev_ramp
        intensity = 0.70 * normal_intensity + 0.30 * elev_ramp
        return np.clip(intensity, 0.0, 1.0)
    return np.clip(normal_intensity, 0.0, 1.0)


def _compute_face_shade(xyz, faces, azimuth, angle, ambient, face_normals=None, z_values=None):
    if xyz is None or faces is None or len(faces) == 0:
        return np.array([], dtype=np.float32)
    if face_normals is None or len(face_normals) != len(faces):
        face_normals = _compute_face_normals(xyz, faces)
        
    if HAS_NUMBA:
        face_z = _fast_centroids_z(xyz, faces)
    else:
        face_z = xyz[faces, 2].mean(axis=1)
        
    return _compute_shading(face_normals, azimuth, angle, ambient, z_values=face_z)


def _remove_shaded_edge_overlay(app):
    plotter = getattr(app, 'vtk_widget', None)
    if plotter is not None:
        try:
            plotter.remove_actor("shaded_mesh_edges", render=False)
        except Exception:
            pass
    app._shaded_mesh_edge_actor = None
    app._shaded_mesh_edge_polydata = None


def _setup_microstation_lighting(renderer, azimuth=45.0, angle=45.0):
    renderer.RemoveAllLights()
    az_rad = np.radians(azimuth)
    el_rad = np.radians(angle)
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
    fill_light.SetPositional(False)
    renderer.AddLight(fill_light)
    renderer.SetAmbient(0.20, 0.20, 0.20)


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
        self._hidden_face_mask = None
        self._global_to_unique = None
        self._cached_face_class = None

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

    def is_fully_current(self, xyz, visible_classes, azimuth, angle, ambient, app):
        """
        Returns True only when NOTHING needs to be done:
          • geometry cache valid (triangulation + normals)
          • shading params unchanged
          • VTK actor present in the renderer
        All three must hold.  For the "re-render only" case (actor gone after
        mode switch) use is_geometry_valid() instead.
        """
        if not self.is_geometry_valid(xyz, visible_classes):
            return False
        if self.needs_shading_update(azimuth, angle, ambient):
            return False
        return getattr(app, '_shaded_mesh_actor', None) is not None

    def is_geometry_valid(self, xyz, visible_classes):
        """
        Returns True when the triangulated geometry cache is reusable —
        regardless of whether the VTK actor currently exists in the renderer.
 
        Weaker than is_fully_current():  shading params and actor presence
        are NOT checked.  Use this to decide "can we skip triangulation?"
        """
        if self.xyz_unique is None or self.faces is None or len(self.faces) == 0:
            return False
        if self.get_visible_hash(visible_classes) != self.visible_classes_hash:
            return False
        try:
            new_hash = hash((len(xyz), float(xyz[0, 0]), float(xyz[-1, 2])))
            return new_hash == self.data_hash
        except Exception:
            return False
 
    def is_cached_subset_of(self, new_visible_classes, xyz):
        """
        Returns True when the currently cached geometry covers a SUBSET of the
        newly-requested visible classes AND the point data is unchanged.
 
        Example: cache = {class 5 only}, request = {all classes}.
        single ⊂ all  → True → incremental add is safe.
 
        Also checks data hash so we never add points from a different file.
        """
        if (self.visible_classes_set is None
                or self.xyz_unique is None
                or self.faces is None
                or len(self.faces) == 0
                or self.data_hash is None):
            return False
        if not self.visible_classes_set.issubset(new_visible_classes):
            return False
        try:
            new_hash = hash((len(xyz), float(xyz[0, 0]), float(xyz[-1, 2])))
            return new_hash == self.data_hash
        except Exception:
            return False

    def needs_shading_update(self, azimuth, angle, ambient):
        return (abs(self.last_azimuth - azimuth) > 0.001 or
                abs(self.last_angle   - angle)   > 0.001 or
                abs(self.last_ambient - ambient)  > 0.001)

    def get_gpu_color_pointer(self, app):
        if self._vtk_colors_ptr is not None:
            return self._vtk_colors_ptr
        mesh = getattr(app, '_shaded_mesh_polydata', None)
        if mesh is None:
            return None
        try:
            vtk_colors = mesh.GetPointData().GetScalars()
            if vtk_colors is None:
                vtk_colors = mesh.GetCellData().GetScalars()
            if vtk_colors is not None:
                self._vtk_colors_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                return self._vtk_colors_ptr
        except:
            pass
        return None

    def build_global_to_unique(self, total_points):
        if (self._global_to_unique is not None and
                len(self._global_to_unique) == total_points):
            return self._global_to_unique
        self._global_to_unique = np.full(total_points, -1, dtype=np.int32)
        if self.unique_indices is not None:
            self._global_to_unique[self.unique_indices] = np.arange(
                len(self.unique_indices))
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
    shading_override = getattr(app, '_shading_visibility_override', None)
    if shading_override is not None:
        print(f"   📍 Shading visibility from SHORTCUT OVERRIDE: "
              f"{sorted(shading_override)}")
        return shading_override
    dialog = getattr(app, 'display_mode_dialog', None)
    if dialog is None:
        dialog = getattr(app, 'display_dialog', None)
    if dialog is not None:
        view_palettes = getattr(dialog, 'view_palettes', None)
        if view_palettes is not None and 0 in view_palettes:
            main_view_palette = view_palettes[0]
            visible_classes = {
                int(c) for c, e in main_view_palette.items()
                if e.get("show", True)
            }
            if visible_classes:
                print(f"   📍 Shading visibility from Display Mode (Slot 0): "
                      f"{sorted(visible_classes)}")
                return visible_classes
    visible_classes = {
        int(c) for c, e in app.class_palette.items()
        if e.get("show", True)
    }
    if visible_classes:
        print(f"   📍 Shading visibility from class_palette: "
              f"{sorted(visible_classes)}")
    return visible_classes


def _save_camera(app):
    try:
        cam = app.vtk_widget.renderer.GetActiveCamera()
        return {'pos': cam.GetPosition(), 'fp': cam.GetFocalPoint(),
                'up': cam.GetViewUp(),
                'parallel': cam.GetParallelProjection(),
                'scale': cam.GetParallelScale()}
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


def _queue_deferred_rebuild(app, reason="", newly_visible_indices=None):
    global _rebuild_timer, _rebuild_reason, _rebuild_changed_indices
    _rebuild_reason = reason
    _rebuild_changed_indices = newly_visible_indices

    if _rebuild_timer is not None:
        try:
            _rebuild_timer.stop()
            _rebuild_timer.deleteLater()
        except:
            pass
        _rebuild_timer = None

    def do_rebuild():
        global _rebuild_timer, _rebuild_changed_indices
        _rebuild_timer = None
        deferred_indices = _rebuild_changed_indices
        _rebuild_changed_indices = None
        is_dragging = getattr(app, 'is_dragging', False)
        if hasattr(app, 'interactor'):
            is_dragging = is_dragging or getattr(
                app.interactor, 'is_dragging', False)
        if is_dragging:
            _queue_deferred_rebuild(app, _rebuild_reason, deferred_indices)
            return
        print(f"   🔄 Deferred patch ({_rebuild_reason})...")
        cache = get_cache()
        visible_classes = _get_shading_visibility(app)
        classes = app.data.get("classification").astype(np.int32)
        xyz = app.data.get("xyz")
        classes_mesh = classes[cache.unique_indices]
        vis_array = np.array(sorted(visible_classes), dtype=np.int32)
        now_hidden = ~np.isin(classes_mesh, vis_array)
        if np.any(now_hidden):
            hidden_global_indices = cache.unique_indices[now_hidden]
            n_affected = len(hidden_global_indices)
            print(f"   🔍 Found {n_affected:,} affected points")
            success = _incremental_visibility_patch(
                app, hidden_global_indices, visible_classes)
            if not success:
                print("   ⚠️ Incremental patch failed - full rebuild")
                clear_shading_cache("patch failed")
                update_shaded_class(app, force_rebuild=True)
            return
        if deferred_indices is not None and len(deferred_indices) > 0:
            g2u = cache.build_global_to_unique(len(xyz))
            current_classes = classes[deferred_indices]
            still_visible = np.isin(current_classes, vis_array)
            visible_of_deferred = deferred_indices[still_visible]
            if len(visible_of_deferred) > 0:
                not_in_mesh_mask = (g2u[visible_of_deferred] < 0)
                missing_global = visible_of_deferred[not_in_mesh_mask]
            else:
                missing_global = np.array([], dtype=np.intp)
            if len(missing_global) > 0:
                print(f"   🔍 Adding {len(missing_global):,} newly-visible "
                      f"points to mesh")
                success = _fast_incremental_add_points(app, missing_global)
                if success:
                    print(f"   ✅ Fast incremental add complete")
                else:
                    print(f"   ⚠️ Fast add failed — trying region patch")
                    changed_mask = np.zeros(len(xyz), dtype=bool)
                    changed_mask[missing_global] = True
                    success = _multi_class_region_undo_patch(
                        app, changed_mask, visible_classes)
                    if success:
                        print(f"   ✅ Region patch complete")
                    else:
                        print("   ⚠️ Region patch failed — full rebuild")
                        clear_shading_cache("region patch failed")
                        update_shaded_class(app, force_rebuild=True)
                return
        print(f"   ✅ No void geometry to clean up")

    _delay_ms = 150 if (newly_visible_indices is not None
                        and len(newly_visible_indices) > 0) else 1000
    _rebuild_timer = QTimer()
    _rebuild_timer.setSingleShot(True)
    _rebuild_timer.timeout.connect(do_rebuild)
    _rebuild_timer.start(_delay_ms)
    print(f"   ⏰ Patch queued ({_delay_ms}ms delay)")


def _queue_incremental_patch(app, single_class_id):
    global _rebuild_timer, _rebuild_reason
    _rebuild_reason = "single-class patch"
    if _rebuild_timer is not None:
        try:
            _rebuild_timer.stop()
            _rebuild_timer.deleteLater()
        except:
            pass
        _rebuild_timer = None

    def do_patch():
        global _rebuild_timer
        _rebuild_timer = None
        is_dragging = getattr(app, 'is_dragging', False)
        if hasattr(app, 'interactor'):
            is_dragging = is_dragging or getattr(
                app.interactor, 'is_dragging', False)
        if is_dragging:
            _queue_incremental_patch(app, single_class_id)
            return
        print(f"   🔄 Incremental patch...")
        _rebuild_single_class(app, single_class_id)

    _rebuild_timer = QTimer()
    _rebuild_timer.setSingleShot(True)
    _rebuild_timer.timeout.connect(do_patch)
    _rebuild_timer.start(1000)
    print(f"   ⏰ Patch queued (1s delay)")


def update_shaded_class(app, azimuth=45.0, angle=45.0, ambient=0.25,
                        max_edge_factor=3.0, force_rebuild=False,
                        single_class_max_edge=None, **kwargs):
    cache = get_cache()
    xyz_raw = app.data.get("xyz")
    classes_raw = app.data.get("classification")
    if xyz_raw is None or classes_raw is None:
        return

    azimuth = getattr(app, 'last_shade_azimuth', azimuth)
    angle   = getattr(app, 'last_shade_angle',   angle)
    ambient = getattr(app, 'shade_ambient',       ambient)

    visible_classes = _get_shading_visibility(app)

    # ── EARLY EXIT 1: Truly nothing changed (geometry + shading + actor) ─────
    if cache.is_fully_current(xyz_raw, visible_classes, azimuth, angle, ambient, app):
        print("   ✅ Shading fully current — skipping rebuild")
        return
 
    # ── EARLY EXIT 2: Geometry cached, actor just needs re-rendering ──────────
    # Covers: switching from "By Classification" back to "Shaded" with same
    # class selection.  The actor was hidden/removed by the mode switch but
    # the triangulation is still valid.
    if not force_rebuild and cache.is_geometry_valid(xyz_raw, visible_classes):
        print("   ⚡ Geometry cached — re-rendering without triangulation")
        _refresh_from_cache(app, cache, azimuth, angle, ambient)
        return
 
    # ── EARLY EXIT 3: New request is a SUPERSET of cached geometry ────────────
    # Covers: single-class shading → all-classes shading.
    # The single-class mesh is already in the cache; incrementally add the
    # extra classes' points rather than triangulating everything from scratch.
    if not force_rebuild and cache.is_cached_subset_of(visible_classes, xyz_raw):
        print(f"   ⚡ Cached geometry ({cache.visible_classes_set}) ⊂ request "
              f"({visible_classes}) — incremental add")
        try:
            extra_classes = visible_classes - cache.visible_classes_set
            extra_mask    = np.isin(classes_raw.astype(np.int32),
                                    list(extra_classes))
            extra_indices = np.where(extra_mask)[0]
            if len(extra_indices) > 0:
                success = _fast_incremental_add_points(app, extra_indices)
                if success:
                    # Update cache metadata so subsequent checks are correct
                    cache.visible_classes_hash = cache.get_visible_hash(visible_classes)
                    cache.visible_classes_set  = visible_classes.copy()
                    cache.n_visible_classes    = len(visible_classes)
                    cache.single_class_id      = (list(visible_classes)[0]
                                                  if len(visible_classes) == 1 else None)
                    app.last_shade_azimuth = azimuth
                    app.last_shade_angle   = angle
                    app.shade_ambient      = ambient
                    print(f"   ✅ Incremental add complete (+{len(extra_indices):,} pts)")
                    return
        except Exception as _inc_err:
            print(f"   ⚠️ Incremental superset add failed ({_inc_err}) — full rebuild")
        # Fall through to full rebuild if incremental fails
    # ─────────────────────────────────────────────────────────────────────

    for c in app.class_palette:   # ← existing line continues here  
        app.class_palette[c]["show"] = (int(c) in visible_classes)
    app._shading_visible_classes = (visible_classes.copy()
                                    if visible_classes else set())
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


def _tiled_triangulate(xyz_unique, max_pts_per_tile=None):
    n_pts = len(xyz_unique)

    n_cpus   = multiprocessing.cpu_count()
    n_workers = min(n_cpus, 16)           # was: min(max(n_cpus//2,4), 12)

    if max_pts_per_tile is None:
        target_tiles   = max(n_workers * 3, 12)           # was: n_workers*2, 8
        max_pts_per_tile = max(n_pts // target_tiles, 30_000)  # was 50_000 min
        max_pts_per_tile = min(max_pts_per_tile, 150_000)      # was 300_000 cap

    if n_pts <= max_pts_per_tile:
        return _do_triangulate(xyz_unique[:, :2])

    t0 = time.time()
    xy = xyz_unique[:, :2]
    x_min, y_min = xy.min(axis=0)
    x_max, y_max = xy.max(axis=0)
    x_range = x_max - x_min
    y_range = y_max - y_min
    area = max(x_range * y_range, 1.0)

    n_tiles_needed = max(int(np.ceil(n_pts / max_pts_per_tile)), 2)
    aspect = x_range / max(y_range, 1e-6)
    ny = max(int(np.sqrt(n_tiles_needed / max(aspect, 0.01))), 1)
    nx = max(int(np.ceil(n_tiles_needed / ny)), 1)
    tile_w = x_range / nx
    tile_h = y_range / ny
    spacing = np.sqrt(area / n_pts)
    margin = spacing * 5.0

    t_prep = time.time()
    tile_args = []
    px = xy[:, 0]
    py = xy[:, 1]

    for ty in range(ny):
        cy0 = y_min + ty * tile_h
        cy1 = y_min + (ty + 1) * tile_h
        by0 = cy0 - margin
        by1 = cy1 + margin

        y_band_mask = (py >= by0) & (py <= by1)
        y_band_indices = np.where(y_band_mask)[0]
        if len(y_band_indices) < 3:
            continue
        band_px = px[y_band_indices]

        for tx in range(nx):
            cx0 = x_min + tx * tile_w
            cx1 = x_min + (tx + 1) * tile_w
            bx0 = cx0 - margin
            bx1 = cx1 + margin

            x_mask = (band_px >= bx0) & (band_px <= bx1)
            tile_indices = y_band_indices[x_mask]

            if len(tile_indices) < 3:
                continue

            tile_xy = xy[tile_indices]
            tile_args.append((
                tile_xy, tile_indices,
                cx0, cx1, cy0, cy1, tx, ty
            ))

    n_total_tiles = len(tile_args)
    if n_total_tiles == 0:
        print(f"   ⚠️ No valid tiles — direct fallback")
        return _do_triangulate(xy)

    n_workers = min(n_total_tiles, n_workers)
    t_prep_ms = (time.time() - t_prep) * 1000

    print(f"   🔲 Parallel tiled triangulation: {nx}×{ny} grid, "
          f"{n_total_tiles} tiles "
          f"(~{max_pts_per_tile:,} pts/tile, margin={margin:.3f}m)")
    print(f"   ⚡ {n_workers} workers on {n_cpus} CPUs "
          f"[prep={t_prep_ms:.0f}ms]")

    min_area_threshold = (spacing * 0.1) ** 2

    def _process_tile(args):
        tile_xy, tile_indices, cx0, cx1, cy0, cy1, tx, ty = args

        try:
            if HAS_SCIPY:
                tri = Delaunay(tile_xy.astype(np.float64))
                local_faces = tri.simplices.astype(np.int32)
            else:
                local_faces = _do_triangulate(tile_xy)
        except Exception:
            return np.array([], dtype=np.int32).reshape(0, 3)

        if len(local_faces) == 0:
            return np.array([], dtype=np.int32).reshape(0, 3)

        global_faces = tile_indices[local_faces]

        # ⚡ Single vertex lookup — reused for centroids AND degenerate filter
        v0 = xy[global_faces[:, 0]]
        v1 = xy[global_faces[:, 1]]
        v2 = xy[global_faces[:, 2]]

        # ⚡ Centroids via direct arithmetic (no .mean() overhead)
        ctr_x = (v0[:, 0] + v1[:, 0] + v2[:, 0]) * (1.0 / 3.0)
        ctr_y = (v0[:, 1] + v1[:, 1] + v2[:, 1]) * (1.0 / 3.0)

        # Core-face selection
        in_core = (
            (ctr_x >= cx0) & (ctr_x < cx1) &
            (ctr_y >= cy0) & (ctr_y < cy1)
        )
        # Handle edge tiles
        if tx == nx - 1:
            in_core |= ((ctr_x >= cx0) & (ctr_x <= cx1 + margin))
            in_core &= (ctr_y >= cy0)
            if ty == ny - 1:
                in_core |= ((ctr_y >= cy0) & (ctr_y <= cy1 + margin))
            else:
                in_core &= (ctr_y < cy1)
        if ty == ny - 1:
            in_core = (
                (ctr_x >= cx0) &
                (ctr_x <= cx1 + (margin if tx == nx - 1 else 0)) &
                (ctr_y >= cy0) &
                (ctr_y <= cy1 + margin)
            )

        core_mask = in_core
        if not np.any(core_mask):
            return np.array([], dtype=np.int32).reshape(0, 3)

        # ⚡ Filter vertices to core subset ONCE
        core_faces = global_faces[core_mask]
        p0 = v0[core_mask]
        p1 = v1[core_mask]
        p2 = v2[core_mask]

        # Degenerate filter — reuses p0/p1/p2 (zero extra indexing)
        d10 = p1 - p0
        d20 = p2 - p0
        cross_z = d10[:, 0] * d20[:, 1] - d10[:, 1] * d20[:, 0]
        tri_area = np.abs(cross_z) * 0.5

        d21 = p2 - p1
        e0_sq = (d10 ** 2).sum(axis=1)
        e1_sq = (d21 ** 2).sum(axis=1)
        e2_sq = (d20 ** 2).sum(axis=1)
        max_edge_sq = np.maximum(np.maximum(e0_sq, e1_sq), e2_sq)

        aspect_ratio = tri_area / np.maximum(max_edge_sq, 1e-10)
        valid = (tri_area > min_area_threshold) & (aspect_ratio > 0.001)

        return core_faces[valid]

    # ══════════════════════════════════════════════════════════════════════
    # EXECUTE PARALLEL TRIANGULATION (THIS WAS MISSING!)
    # ══════════════════════════════════════════════════════════════════════
    
    t_tri = time.time()
    all_faces = []
    
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        results = list(executor.map(_process_tile, tile_args))
    
    for tile_faces in results:
        if len(tile_faces) > 0:
            all_faces.append(tile_faces)
    
    if len(all_faces) == 0:
        print(f"   ⚠️ No faces from tiled triangulation — direct fallback")
        return _do_triangulate(xy)
    
    combined_faces = np.vstack(all_faces)
    
    t_tri_ms = (time.time() - t_tri) * 1000
    t_total_ms = (time.time() - t0) * 1000
    print(f"   ✅ Tiled triangulation: {len(combined_faces):,} faces "
          f"[tri={t_tri_ms:.0f}ms, total={t_total_ms:.0f}ms]")
    
    return combined_faces

def _build_visible_geometry(app, xyz_raw, classes_raw, azimuth, angle,
                            ambient, max_edge_factor, cache, visible_classes,
                            single_class_max_edge=None):
    n_visible = len(visible_classes)
    is_single_class = (n_visible == 1)
    print(f"\n{'='*60}")
    print(f"🔺 {'SINGLE-CLASS' if is_single_class else 'MULTI-CLASS'} "
          f"SHADING (MicroStation mode)")
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
        classes = classes_raw.astype(np.int16, copy=False)
        max_c = int(np.max(classes)) + 1 if len(classes) > 0 else 256
        vis_lookup = np.zeros(max_c, dtype=bool)
        for v_class in visible_classes:
            if v_class < max_c:
                vis_lookup[v_class] = True
        visible_mask = vis_lookup[classes]
        if np.all(visible_mask):
            visible_indices = np.arange(len(classes), dtype=np.intp)
            xyz_visible = xyz_raw
        else:
            visible_indices = np.where(visible_mask)[0]
            xyz_visible = xyz_raw[visible_indices]
        if len(visible_indices) < 3:
            print(f"   ⚠️ Only {len(visible_indices)} visible points — "
                  f"clearing mesh")
            if hasattr(app, '_shaded_mesh_actor') and app._shaded_mesh_actor:
                try:
                    app.vtk_widget.remove_actor("shaded_mesh", render=False)
                except:
                    pass
                app._shaded_mesh_actor = None
            if hasattr(app, '_shaded_mesh_polydata'):
                app._shaded_mesh_polydata = None
            _remove_shaded_edge_overlay(app)
            if hasattr(app, 'vtk_widget') and hasattr(app.vtk_widget, 'actors'):
                for name in list(app.vtk_widget.actors.keys()):
                    if str(name).startswith("class_"):
                        app.vtk_widget.actors[name].SetVisibility(False)
            cache.n_visible_classes = n_visible
            cache.visible_classes_set = visible_classes.copy()
            cache.single_class_id = (list(visible_classes)[0]
                                     if is_single_class else None)
            _restore_camera(app, saved_camera)
            app.vtk_widget.render()
            progress.close()
            print(f"   🖤 Screen cleared (0 visible points)")
            print(f"{'='*60}\n")
            return
        print(f"   📍 {len(visible_indices):,} visible points")
        progress.setValue(10)
        QApplication.processEvents()
        offset = xyz_visible.min(axis=0)
        xyz = (xyz_visible - offset).astype(np.float64)
        x_range = xyz[:, 0].max() - xyz[:, 0].min()
        y_range = xyz[:, 1].max() - xyz[:, 1].min()
        area = max(x_range * y_range, 1.0)
        n_pts = len(xyz)
        natural_spacing = np.sqrt(area / n_pts)
        base_precision = max(natural_spacing * _BASE_GRID_PRECISION_FACTOR,
                             _MIN_GRID_PRECISION_M)
        precision = base_precision
        print(f"   📐 Grid precision: {precision:.4f}m "
              f"(natural spacing: {natural_spacing:.4f}m)")

        unique_indices_local = _select_highest_points_per_grid_cell(
            xyz, base_precision)
        xyz_unique = xyz[unique_indices_local]
        unique_indices_global = visible_indices[unique_indices_local]
        x_range = xyz_unique[:, 0].max() - xyz_unique[:, 0].min()
        y_range = xyz_unique[:, 1].max() - xyz_unique[:, 1].min()
        data_extent = max(x_range, y_range)
        spacing = np.sqrt((x_range * y_range) / max(len(xyz_unique), 1))
        cache.offset = offset
        cache.unique_indices = unique_indices_global
        cache.xyz_unique = xyz_unique
        cache.xyz_final = xyz_unique + offset
        cache.spacing = spacing
        cache.max_edge_factor = max_edge_factor
        cache.visible_classes_hash = cache.get_visible_hash(visible_classes)
        cache.n_visible_classes = n_visible
        cache.visible_classes_set = visible_classes.copy()
        cache.single_class_id = (list(visible_classes)[0]
                                  if is_single_class else None)
        cache._vtk_colors_ptr = None
        cache._global_to_unique = None
        cache._cached_face_class = None

        # ── Hard cap: reduce precision if we're still over budget ─────────
        _MAX = _MAX_UNIQUE_POINTS
        if False and len(xyz_unique) > _MAX:  # Legacy fallback kept disabled.
            ratio = np.sqrt(len(xyz_unique) / _MAX)
            precision2 = precision * ratio
            print(f"   📉 Point budget: {len(xyz_unique):,} → ~{_MAX:,} "
                  f"(precision {precision:.4f}m → {precision2:.4f}m)")
            xy_grid2 = np.floor(xyz[:, :2] / precision2).astype(np.int64)
            gx2 = xy_grid2[:, 0] - xy_grid2[:, 0].min()
            gy2 = xy_grid2[:, 1] - xy_grid2[:, 1].min()
            gy_span2 = int(gy2.max()) + 1
            if gx2.max() < 2**30 and gy_span2 < 2**30:
                gk2 = gx2 * gy_span2 + gy2
                sidx2 = np.lexsort((-xyz[:, 2], gk2))
                sk2   = gk2[sidx2]
                umask2 = np.concatenate([[True], np.diff(sk2) != 0])
            else:
                sidx2  = np.lexsort((-xyz[:, 2], xy_grid2[:, 1], xy_grid2[:, 0]))
                xys2   = xy_grid2[sidx2]
                diff2  = np.diff(xys2, axis=0)
                umask2 = np.concatenate([[True], (diff2[:, 0] != 0) | (diff2[:, 1] != 0)])
            unique_indices_local  = sidx2[umask2]
            xyz_unique            = xyz[unique_indices_local]
            unique_indices_global = visible_indices[unique_indices_local]
            x_range = xyz_unique[:, 0].max() - xyz_unique[:, 0].min()
            y_range = xyz_unique[:, 1].max() - xyz_unique[:, 1].min()
            data_extent = max(x_range, y_range)
            spacing = np.sqrt((x_range * y_range) / max(len(xyz_unique), 1))
            # Refresh cache references
            cache.unique_indices  = unique_indices_global
            cache.xyz_unique      = xyz_unique
            cache.xyz_final       = xyz_unique + offset
            cache.spacing = spacing

        print(f"   ✅ {len(xyz_unique):,} unique points (ALL kept)")

        progress.setValue(20)
        QApplication.processEvents()
        t0 = time.time()
        xy = xyz_unique[:, :2]

        _tile_threshold = 800_000
        _used_tiled = False
        if len(xyz_unique) > _tile_threshold:
            faces = _tiled_triangulate(xyz_unique)
            _used_tiled = True
        else:
            faces = _do_triangulate(xy)

        if len(faces) > 0 and not _used_tiled:
            _p0 = xy[faces[:, 0]]
            _p1 = xy[faces[:, 1]]
            _p2 = xy[faces[:, 2]]
            _cross_z = ((_p1[:, 0] - _p0[:, 0]) * (_p2[:, 1] - _p0[:, 1]) -
                        (_p1[:, 1] - _p0[:, 1]) * (_p2[:, 0] - _p0[:, 0]))
            _tri_area = np.abs(_cross_z) * 0.5
            _e0_sq = ((_p1 - _p0) ** 2).sum(axis=1)
            _e1_sq = ((_p2 - _p1) ** 2).sum(axis=1)
            _e2_sq = ((_p0 - _p2) ** 2).sum(axis=1)
            _max_edge_sq = np.maximum(np.maximum(_e0_sq, _e1_sq), _e2_sq)
            _aspect = _tri_area / np.maximum(_max_edge_sq, 1e-10)
            _min_area = (spacing * 0.1) ** 2
            _non_degen = (_tri_area > _min_area) & (_aspect > 0.001)
            n_removed_degen = int(np.sum(~_non_degen))
            if n_removed_degen > 0:
                faces = faces[_non_degen]
                print(f"   ✂️ Removed {n_removed_degen:,} degenerate triangles")

        if is_single_class:
            max_edge = (single_class_max_edge if single_class_max_edge
                        else data_extent * 0.2)
            faces = _filter_edges_by_absolute(faces, xy, max_edge)
        else:
            max_xy_edge_abs = data_extent * 0.10
            faces = _filter_edges_3d_abs(faces, xyz_unique, max_xy_edge_abs,
                                         max_slope_ratio=10.0)
            cache.max_edge_factor = max_xy_edge_abs / max(spacing, 1e-9)
        cache.faces = faces
        print(f"   ✅ {len(faces):,} triangles in {time.time()-t0:.1f}s")
        progress.setValue(70)
        QApplication.processEvents()

        if len(faces) > 0:
            cache.face_normals = _compute_face_normals(xyz_unique, faces)
            if is_single_class:
                cache.shade = _compute_face_shade(
                    xyz_unique, cache.faces, azimuth, angle, ambient,
                    face_normals=cache.face_normals)
                cache.vertex_normals = None
                cache.vertex_shade = None
            else:
                cache.vertex_normals = _compute_vertex_normals(
                    xyz_unique, faces, cache.face_normals)
                cache.vertex_shade = _compute_shading(
                    cache.vertex_normals, azimuth, angle, ambient,
                    z_values=xyz_unique[:, 2])
                cache.shade = _compute_face_shade(
                    xyz_unique, cache.faces, azimuth, angle, ambient,
                    face_normals=cache.face_normals)
        else:
            cache.face_normals = np.array([]).reshape(0, 3)
            cache.vertex_normals = np.array([]).reshape(0, 3)
            cache.shade = np.array([])
            cache.vertex_shade = np.array([])

        cache.last_azimuth = azimuth
        cache.last_angle = angle
        cache.last_ambient = ambient
        cache.data_hash = hash((len(xyz_raw), float(xyz_raw[0, 0]),
                                float(xyz_raw[-1, 2])))
        
        QApplication.processEvents()
        _render_mesh(app, cache, classes_raw, saved_camera)
        progress.setValue(100)
        print(f"   ✅ COMPLETE: {time.time()-t_total:.1f}s")
        print(f"{'='*60}\n")
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        progress.close()


def _refresh_from_cache(app, cache, azimuth, angle, ambient):
    app.last_shade_azimuth = azimuth
    app.last_shade_angle = angle
    app.shade_ambient = ambient
    app.display_mode = "shaded_class"
    saved_camera = _save_camera(app)

    needs_update = cache.needs_shading_update(azimuth, angle, ambient)
    print(f"   🔍 Shading update needed: {needs_update} "
          f"(az={azimuth} vs cached={cache.last_azimuth}, "
          f"el={angle} vs cached={cache.last_angle}, "
          f"amb={ambient} vs cached={cache.last_ambient})")

    if needs_update:
        is_single_class = getattr(cache, 'n_visible_classes', 0) == 1
        z_vals = cache.xyz_unique[:, 2] if cache.xyz_unique is not None else None

        if is_single_class:
            # ✅ Recompute face-based shading for single class using NUMBA
            if cache.face_normals is not None and len(cache.face_normals) > 0:
                cache.shade = _compute_face_shade(
                    cache.xyz_unique, cache.faces, azimuth, angle, ambient,
                    face_normals=cache.face_normals
                )
                print(f"   ✅ Single-class face shading recomputed (NUMBA): "
                      f"min={cache.shade.min():.3f} "
                      f"max={cache.shade.max():.3f} "
                      f"mean={cache.shade.mean():.3f}")
        else:
            # ✅ Recompute vertex-based shading for multi class
            if cache.vertex_normals is not None and len(cache.vertex_normals) > 0:
                cache.vertex_shade = _compute_shading(
                    cache.vertex_normals, azimuth, angle, ambient,
                    z_values=z_vals)
                print(f"   ✅ Multi-class vertex shading recomputed: "
                      f"min={cache.vertex_shade.min():.3f} "
                      f"max={cache.vertex_shade.max():.3f} "
                      f"mean={cache.vertex_shade.mean():.3f}")
            cache.shade = _compute_face_shade(
                cache.xyz_unique, cache.faces, azimuth, angle, ambient,
                face_normals=cache.face_normals)

        cache.last_azimuth = azimuth
        cache.last_angle   = angle
        cache.last_ambient = ambient
        cache._vtk_colors_ptr = None

    _render_mesh(app, cache, app.data.get("classification"), saved_camera)


def _render_mesh(app, cache, classes_raw, saved_camera):
    if cache.faces is None or len(cache.faces) == 0:
        return
    t0 = time.time()
    classes = classes_raw.astype(np.int32)
    classes_mesh = classes[cache.unique_indices]
    visible_classes = _get_shading_visibility(app)
    n_verts = len(cache.xyz_final)
    n_faces = len(cache.faces)
    azimuth = getattr(app, 'last_shade_azimuth', 45.0)
    angle   = getattr(app, 'last_shade_angle', 45.0)
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
        # ── SINGLE-CLASS: Faceted flat shading ───────────────────────────────
        # ⚡ USE THE NUMBA-ACCELERATED CACHE INSTEAD OF RECOMPUTING IN NUMPY!
        ambient = getattr(app, 'shade_ambient', 0.25)
        
        if cache.shade is None or len(cache.shade) != n_faces:
            cache.shade = _compute_face_shade(
                cache.xyz_unique, cache.faces, azimuth, angle, ambient, 
                face_normals=cache.face_normals
            )
            
        face_intensity = cache.shade
        
        face_vert0_class = np.clip(
            classes_mesh[cache.faces[:, 0]], 0, max_c - 1)
        face_base_color = lut[face_vert0_class]
        face_colors = np.clip(
            face_base_color * face_intensity[:, None], 0, 255
        ).astype(np.uint8)

        # ── Reuse detection (cell data) ───────────────────────────────────────
        existing_mesh  = getattr(app, '_shaded_mesh_polydata', None)
        existing_actor = getattr(app, '_shaded_mesh_actor', None)
        _can_reuse = (
            existing_mesh is not None
            and existing_actor is not None
            and existing_mesh.GetNumberOfPoints() == n_verts
            and existing_mesh.GetNumberOfCells() == n_faces
        )
        if _can_reuse:
            try:
                vtk_colors = existing_mesh.GetCellData().GetScalars()
                if vtk_colors is not None:
                    vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                    vtk_ptr[:] = face_colors
                    vtk_colors.Modified()
                    existing_mesh.Modified()
                    existing_actor.GetMapper().Modified()
                    _restore_camera(app, saved_camera)
                    app.vtk_widget.render()
                    elapsed = (time.time() - t0) * 1000
                    print(f"   🎨 Flat Mesh (single-class) Rendered: "
                          f"{n_faces:,} faces in {elapsed:.0f}ms (GPU in-place)")
                    return
            except Exception as _reuse_err:
                print(f"   ⚠️ In-place patch failed ({_reuse_err}), rebuilding")
            cache._vtk_colors_ptr = None

        # ── Full rebuild ──────────────────────────────────────────────────────
        # ⚡ ZERO-COPY VTK ARRAY BUILD (Bypasses np.hstack and ravel overhead)
        faces_vtk = np.empty(n_faces * 4, dtype=np.int32)
        faces_vtk[0::4] = 3
        faces_vtk[1::4] = cache.faces[:, 0]
        faces_vtk[2::4] = cache.faces[:, 1]
        faces_vtk[3::4] = cache.faces[:, 2]
        
        mesh = pv.PolyData(cache.xyz_final, faces_vtk)
        mesh.cell_data["RGB"] = face_colors

        plotter = app.vtk_widget
        _DXF_PREFIXES = ("dxf_", "snt_", "grid_", "guideline", "snap_", "axis")

        def _is_protected_actor(name_str, actor):
            if any(name_str.lower().startswith(p) for p in _DXF_PREFIXES):
                return True
            return getattr(actor, '_is_dxf_actor', False)

        protected_actors = {}
        for name in list(plotter.actors.keys()):
            try:
                actor = plotter.actors[name]
                if _is_protected_actor(name, actor):
                    protected_actors[name] = (actor, bool(actor.GetVisibility()))
            except Exception:
                pass
        for name in list(plotter.actors.keys()):
            if name in protected_actors:
                continue
            name_str = str(name).lower()
            if name_str.startswith("class_") or name_str in (
                    "main_pc", "main_pc_border", "_naksha_unified_cloud"):
                plotter.actors[name].SetVisibility(False)
            elif any(name_str.startswith(p) for p in [
                    "border_", "shaded_mesh", "__lod_overlay_"]):
                plotter.remove_actor(name, render=False)

        app._shaded_mesh_actor = plotter.add_mesh(
            mesh, scalars="RGB", rgb=True, show_edges=False,
            lighting=False, smooth_shading=False, preference="cell",
            name="shaded_mesh", render=False)
        if app._shaded_mesh_actor is not None:
            prop = app._shaded_mesh_actor.GetProperty()
            prop.SetInterpolationToFlat()
            prop.SetAmbient(1.0)
            prop.SetDiffuse(0.0)
            prop.SetSpecular(0.0)
            prop.EdgeVisibilityOff()
        app._shaded_mesh_polydata = mesh
        cache._vtk_colors_ptr = cache.get_gpu_color_pointer(app)

    else:
        # ── MULTI-CLASS: Vertex-based shading (unchanged) ─────────────────────
        if cache.vertex_shade is not None and len(cache.vertex_shade) == n_verts:
            vertex_colors = np.clip(
                vert_base_color * cache.vertex_shade[:, None], 0, 255
            ).astype(np.uint8)
        else:
            vertex_colors = vert_base_color.astype(np.uint8)

        existing_mesh  = getattr(app, '_shaded_mesh_polydata', None)
        existing_actor = getattr(app, '_shaded_mesh_actor', None)
        _can_reuse = (
            existing_mesh is not None
            and existing_actor is not None
            and existing_mesh.GetNumberOfPoints() == n_verts
            and existing_mesh.GetNumberOfCells() == n_faces
        )
        if _can_reuse:
            try:
                vtk_colors = existing_mesh.GetPointData().GetScalars()
                if vtk_colors is not None:
                    vtk_ptr = numpy_support.vtk_to_numpy(vtk_colors)
                    vtk_ptr[:] = vertex_colors
                    vtk_colors.Modified()
                    existing_mesh.Modified()
                    existing_actor.GetMapper().Modified()
                    _restore_camera(app, saved_camera)
                    app.vtk_widget.render()
                    elapsed = (time.time() - t0) * 1000
                    print(f"   🎨 Shaded Mesh Rendered: {n_faces:,} faces "
                          f"in {elapsed:.0f}ms (GPU in-place)")
                    return
            except Exception as _reuse_err:
                print(f"   ⚠️ In-place patch failed ({_reuse_err}), rebuilding")
            cache._vtk_colors_ptr = None

        # ⚡ ZERO-COPY VTK ARRAY BUILD
        faces_vtk = np.empty(n_faces * 4, dtype=np.int32)
        faces_vtk[0::4] = 3
        faces_vtk[1::4] = cache.faces[:, 0]
        faces_vtk[2::4] = cache.faces[:, 1]
        faces_vtk[3::4] = cache.faces[:, 2]
        
        mesh = pv.PolyData(cache.xyz_final, faces_vtk)
        mesh.point_data["RGB"] = vertex_colors
        if cache.vertex_normals is not None and len(cache.vertex_normals) == n_verts:
            vtk_normals = numpy_support.numpy_to_vtk(
                cache.vertex_normals.astype(np.float32), deep=True)
            vtk_normals.SetName("Normals")
            mesh.GetPointData().SetNormals(vtk_normals)

        plotter = app.vtk_widget
        _DXF_PREFIXES = ("dxf_", "snt_", "grid_", "guideline", "snap_", "axis")

        def _is_protected_actor(name_str, actor):
            if any(name_str.lower().startswith(p) for p in _DXF_PREFIXES):
                return True
            return getattr(actor, '_is_dxf_actor', False)

        protected_actors = {}
        for name in list(plotter.actors.keys()):
            try:
                actor = plotter.actors[name]
                if _is_protected_actor(name, actor):
                    protected_actors[name] = (actor, bool(actor.GetVisibility()))
            except Exception:
                pass
        for name in list(plotter.actors.keys()):
            if name in protected_actors:
                continue
            name_str = str(name).lower()
            if name_str.startswith("class_") or name_str in (
                    "main_pc", "main_pc_border", "_naksha_unified_cloud"):
                plotter.actors[name].SetVisibility(False)
            elif any(name_str.startswith(p) for p in [
                    "border_", "shaded_mesh", "__lod_overlay_"]):
                plotter.remove_actor(name, render=False)

        app._shaded_mesh_actor = plotter.add_mesh(
            mesh, scalars="RGB", rgb=True, show_edges=False,
            lighting=True, smooth_shading=True, preference="point",
            name="shaded_mesh", render=False)
        if app._shaded_mesh_actor is not None:
            prop = app._shaded_mesh_actor.GetProperty()
            prop.SetAmbient(0.12)
            prop.SetDiffuse(0.88)
            prop.SetSpecular(0.18)
            prop.SetSpecularPower(48.0)
            prop.SetInterpolationToFlat()
            prop.EdgeVisibilityOff()
        _setup_microstation_lighting(plotter.renderer, azimuth, angle)
        app._shaded_mesh_polydata = mesh
        cache._vtk_colors_ptr = cache.get_gpu_color_pointer(app)

    # ── Restore DXF/SNT actors (shared) ──────────────────────────────────────
    plotter = app.vtk_widget
    renderer = plotter.renderer
    n_restored = 0
    for name, (actor, was_visible) in protected_actors.items():
        try:
            if was_visible:
                actor.SetVisibility(True)
            if not renderer.HasViewProp(actor):
                renderer.AddActor(actor)
                n_restored += 1
        except Exception:
            pass
    for store_name in ("dxf_actors", "snt_actors"):
        for entry in getattr(app, store_name, []):
            for actor in entry.get("actors", []):
                try:
                    if not renderer.HasViewProp(actor):
                        renderer.AddActor(actor)
                        n_restored += 1
                    actor.SetVisibility(True)
                except Exception:
                    pass
    if n_restored > 0:
        print(f"   ✅ Restored {n_restored} DXF/SNT actors on top")
    _restore_camera(app, saved_camera)
    plotter.set_background("black")
    plotter.renderer.ResetCameraClippingRange()

    # ⚡ GPU rendering hints for T400
    try:
        mapper = app._shaded_mesh_actor.GetMapper()
        if mapper:
            mapper.StaticOn()                    # mesh won't change topology often
            mapper.SetResolveCoincidentTopologyToPolygonOffset()
            mapper.InterpolateScalarsBeforeMappingOff()  # RGB already computed
    except Exception:
        pass

    plotter.render()
    mode_str = ("FLAT/FACETED (single-class)" if is_single_class
                else "FLAT (multi-class)")
    print(f"   🎨 Shaded Mesh [{mode_str}]: "
          f"{n_faces:,} faces in {(time.time()-t0)*1000:.0f}ms")


def refresh_shaded_after_classification_fast(app, changed_mask=None):
    cache = get_cache()
    if cache.faces is None or len(cache.faces) == 0:
        update_shaded_class(app, force_rebuild=True)
        return True
    t0 = time.time()
    if hasattr(app, 'vtk_widget'):
        for name in list(app.vtk_widget.actors.keys()):
            name_str = str(name).lower()
            if name_str.startswith("class_") or name_str in (
                    "main_pc", "main_pc_border"):
                app.vtk_widget.actors[name].SetVisibility(False)

    is_single_class = getattr(cache, 'n_visible_classes', 0) == 1
    single_class_id = getattr(cache, 'single_class_id', None)
    visible_classes = _get_shading_visibility(app)
    vis_array = np.array(sorted(visible_classes), dtype=np.int32)

    if changed_mask is None or not np.any(changed_mask):
        if not is_single_class or single_class_id is None:
            return _update_colors_gpu_fast(
                app, cache, changed_mask=None,
                _visible_classes=visible_classes)
        return True

    classes = app.data.get("classification").astype(np.int32)
    changed_indices = np.where(changed_mask)[0]
    changed_classes = classes[changed_indices]
    now_hidden = ~np.isin(changed_classes, vis_array)
    now_visible = np.isin(changed_classes, vis_array)
    g2u = cache.build_global_to_unique(len(app.data["xyz"]))

    # ══════════════════════════════════════════════════════════════
    # ✅ SINGLE-CLASS FAST PATH — handles cell-data mesh directly
    # ══════════════════════════════════════════════════════════════
    if is_single_class and single_class_id is not None:
        mesh = getattr(app, '_shaded_mesh_polydata', None)

        if np.all(now_hidden):
            print(f"   🔧 Single-class: {len(changed_indices):,} pts left "
                  f"class {single_class_id} → incremental patch")

            if mesh is not None:
                cell_colors = mesh.GetCellData().GetScalars()
                if (cell_colors is not None and
                        cache.faces is not None and
                        cell_colors.GetNumberOfTuples() == len(cache.faces)):
                    try:
                        vtk_ptr = numpy_support.vtk_to_numpy(cell_colors)
                        changed_unique = g2u[changed_indices]
                        changed_unique = changed_unique[changed_unique >= 0]
                        if len(changed_unique) > 0:
                            cu_set = np.zeros(len(cache.unique_indices), dtype=bool)
                            cu_set[changed_unique] = True
                            affected_face_mask = (
                                cu_set[cache.faces[:, 0]] |
                                cu_set[cache.faces[:, 1]] |
                                cu_set[cache.faces[:, 2]]
                            )
                            vtk_ptr[affected_face_mask] = [0, 0, 0]
                            cell_colors.Modified()
                            mesh.Modified()
                            actor = getattr(app, '_shaded_mesh_actor', None)
                            if actor:
                                actor.GetMapper().Modified()
                            app.vtk_widget.render()
                            elapsed = (time.time() - t0) * 1000
                            print(f"   ⚡ Instant face blackout: "
                                  f"{int(np.sum(affected_face_mask)):,} faces "
                                  f"in {elapsed:.0f}ms")
                    except Exception as _e:
                        print(f"   ⚠️ Face blackout failed: {_e}")

            _queue_incremental_patch(app, single_class_id)
            return True

        if np.all(now_visible):
            newly_visible_global = changed_indices[now_visible]
            not_in_mesh_mask = (g2u[newly_visible_global] < 0)
            missing_global = newly_visible_global[not_in_mesh_mask]

            if len(missing_global) == 0:
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ Single-class: all pts already in mesh "
                      f"({elapsed:.0f}ms)")
                return True

            print(f"   🔧 Single-class: {len(missing_global):,} new pts → "
                  f"incremental add")
            success = _fast_incremental_add_points(app, missing_global)
            if success:
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ Single-class incremental add: {elapsed:.0f}ms")
                return True
            else:
                _queue_deferred_rebuild(
                    app, "single-class new visible pts",
                    newly_visible_indices=missing_global)
                return True

        print(f"   🔧 Single-class mixed: "
              f"{int(np.sum(now_hidden)):,} hidden, "
              f"{int(np.sum(now_visible)):,} visible")

        if mesh is not None:
            cell_colors = mesh.GetCellData().GetScalars()
            if (cell_colors is not None and
                    cache.faces is not None and
                    cell_colors.GetNumberOfTuples() == len(cache.faces)):
                try:
                    vtk_ptr = numpy_support.vtk_to_numpy(cell_colors)
                    hidden_global = changed_indices[now_hidden]
                    hidden_unique = g2u[hidden_global]
                    hidden_unique = hidden_unique[hidden_unique >= 0]
                    if len(hidden_unique) > 0:
                        cu_set = np.zeros(len(cache.unique_indices), dtype=bool)
                        cu_set[hidden_unique] = True
                        affected = (
                            cu_set[cache.faces[:, 0]] |
                            cu_set[cache.faces[:, 1]] |
                            cu_set[cache.faces[:, 2]]
                        )
                        vtk_ptr[affected] = [0, 0, 0]
                        cell_colors.Modified()
                        mesh.Modified()
                        actor = getattr(app, '_shaded_mesh_actor', None)
                        if actor:
                            actor.GetMapper().Modified()
                        app.vtk_widget.render()
                except Exception as _e:
                    print(f"   ⚠️ Mixed blackout failed: {_e}")

        _queue_incremental_patch(app, single_class_id)
        return True

    # ══════════════════════════════════════════════════════════════
    # MULTI-CLASS PATH (unchanged from before)
    # ══════════════════════════════════════════════════════════════
    if np.all(now_visible):
        prev_also_visible = _check_previous_classes_visible(
            app, changed_indices, vis_array)
        if prev_also_visible:
            success = _update_colors_gpu_fast(
                app, cache, changed_mask=changed_mask,
                _visible_classes=visible_classes, _defer_render=True)
            if success:
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ Color update: {elapsed:.0f}ms")
                return True
        newly_visible_global = changed_indices[now_visible]
        not_in_mesh_mask = (g2u[newly_visible_global] < 0)
        missing_global = newly_visible_global[not_in_mesh_mask]
        if len(missing_global) > 0:
            success = _fast_incremental_add_points(app, missing_global)
            if success:
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ Incremental add: {elapsed:.0f}ms "
                      f"(+{len(missing_global)} pts)")
                return True
            else:
                _queue_deferred_rebuild(
                    app, "classification added new visible pts",
                    newly_visible_indices=missing_global)
                _update_colors_gpu_fast(
                    app, cache, changed_mask=changed_mask,
                    _visible_classes=visible_classes, _defer_render=True)
                return True
        else:
            success = _update_colors_gpu_fast(
                app, cache, changed_mask=changed_mask,
                _visible_classes=visible_classes, _defer_render=True)
            if success:
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ Color-only: {elapsed:.0f}ms")
                return True

    voided_global_indices = None
    if np.any(now_visible):
        newly_visible_global = changed_indices[now_visible]
        n_not_in_mesh = int(np.sum(g2u[newly_visible_global] < 0))
        if n_not_in_mesh > 0:
            shading_override = getattr(
                app, '_shading_visibility_override', None)
            _prev_was_hidden = True
            if shading_override is None:
                for _stack_attr in ('undo_stack', 'undostack'):
                    _stk = getattr(app, _stack_attr, None)
                    if _stk:
                        try:
                            _last = _stk[-1]
                            _old = (_last.get('old_classes') or
                                    _last.get('oldclasses'))
                            if _old is not None:
                                _old_set = set(
                                    int(x) for x in np.unique(
                                        np.asarray(_old)))
                                _vis_set = set(
                                    int(c) for c in visible_classes)
                                _prev_was_hidden = not _old_set.issubset(
                                    _vis_set)
                        except Exception:
                            pass
                        break
            if _prev_was_hidden:
                missing_in_mesh = newly_visible_global[
                    g2u[newly_visible_global] < 0]
                _queue_deferred_rebuild(
                    app, "classification added new visible pts",
                    newly_visible_indices=missing_in_mesh)

    if np.any(now_hidden):
        voided_global_indices = changed_indices[now_hidden]
        mesh = getattr(app, '_shaded_mesh_polydata', None)
        if mesh:
            point_colors = mesh.GetPointData().GetScalars()
            if (point_colors is not None and
                    point_colors.GetNumberOfTuples() ==
                    len(cache.unique_indices)):
                hidden_unique = g2u[voided_global_indices]
                hidden_unique = hidden_unique[
                    (hidden_unique >= 0) &
                    (hidden_unique < len(cache.unique_indices))]
                if len(hidden_unique) > 0:
                    vtk_ptr = numpy_support.vtk_to_numpy(point_colors)
                    vtk_ptr[hidden_unique] = [0, 0, 0]
                    point_colors.Modified()

    success = _update_colors_gpu_fast(
        app, cache, changed_mask,
        _visible_classes=visible_classes, _defer_render=True)
    if success:
        elapsed = (time.time() - t0) * 1000
        print(f"   ⚡ Multi-class GPU: {elapsed:.0f}ms")
        if (voided_global_indices is not None and
                len(voided_global_indices) > 0):
            _queue_deferred_rebuild(app, "void cleanup")
        return True
    else:
        update_shaded_class(app, force_rebuild=True)
        return True

def _incremental_visibility_patch(app, changed_global_indices,
                                   visible_classes_set):
    cache = get_cache()
    if cache.faces is None or cache.xyz_unique is None or cache.xyz_final is None:
        return False
    t0 = time.time()
    xyz_raw = app.data.get("xyz")
    classes_raw = app.data.get("classification")
    if xyz_raw is None or classes_raw is None:
        return False
    classes = classes_raw.astype(np.int32)
    classes_mesh = classes[cache.unique_indices]
    vis_array = np.array(sorted(visible_classes_set), dtype=np.int32)
    vertex_is_visible = np.isin(classes_mesh, vis_array)
    g2u = cache.build_global_to_unique(len(xyz_raw))
    changed_in_mesh = g2u[changed_global_indices]
    changed_in_mesh = changed_in_mesh[changed_in_mesh >= 0]
    if len(changed_in_mesh) > 0:
        changed_vertices_visible = vertex_is_visible[changed_in_mesh]
        if np.all(changed_vertices_visible):
            print(f"   🔙 UNDO detected: {len(changed_in_mesh)} vertices "
                  f"returned to visible")
            v0_changed = np.isin(cache.faces[:, 0], changed_in_mesh)
            v1_changed = np.isin(cache.faces[:, 1], changed_in_mesh)
            v2_changed = np.isin(cache.faces[:, 2], changed_in_mesh)
            faces_with_changed = v0_changed | v1_changed | v2_changed
            n_to_remove = np.sum(faces_with_changed)
            if n_to_remove > 0:
                print(f"   ✂️ Removing {n_to_remove:,} patch faces")
                keep_mask = ~faces_with_changed
                cache.faces = cache.faces[keep_mask]
                cache.shade = cache.shade[keep_mask]
                cache.face_normals = (cache.face_normals[keep_mask]
                                      if cache.face_normals is not None else None)
                if cache.face_normals is not None and len(cache.face_normals) > 0:
                    cache.vertex_normals = _compute_vertex_normals(
                        cache.xyz_unique, cache.faces, cache.face_normals)
                    cache.vertex_shade = _compute_shading(
                        cache.vertex_normals,
                        getattr(app, 'last_shade_azimuth', 45.0),
                        getattr(app, 'last_shade_angle', 45.0),
                        getattr(app, 'shade_ambient', 0.25))
                cache._vtk_colors_ptr = None
                _render_mesh(app, cache, classes_raw, _save_camera(app))
                print(f"   ⚡ UNDO COMPLETE: {(time.time()-t0)*1000:.0f}ms")
                return True
    vertices_now_hidden = ~vertex_is_visible
    n_hidden = np.sum(vertices_now_hidden)
    if n_hidden == 0:
        print(f"   ✅ No vertices became hidden")
        return True
    print(f"   🔍 {n_hidden:,} vertices became hidden")
    v0_hidden = vertices_now_hidden[cache.faces[:, 0]]
    v1_hidden = vertices_now_hidden[cache.faces[:, 1]]
    v2_hidden = vertices_now_hidden[cache.faces[:, 2]]
    invalid_face_mask = v0_hidden | v1_hidden | v2_hidden
    valid_face_mask = ~invalid_face_mask
    n_invalid = np.sum(invalid_face_mask)
    n_valid = np.sum(valid_face_mask)
    print(f"   ✂️ Removing {n_invalid:,} faces")
    print(f"   ✅ Keeping {n_valid:,} valid faces")
    if n_valid == 0:
        return False
    valid_faces = cache.faces[valid_face_mask]
    valid_shade = cache.shade[valid_face_mask]
    valid_normals = (cache.face_normals[valid_face_mask]
                     if cache.face_normals is not None else None)
    hidden_vertex_indices = np.where(vertices_now_hidden)[0]
    invalid_faces_arr = cache.faces[invalid_face_mask]
    _is_hidden_flag = np.zeros(len(cache.unique_indices), dtype=bool)
    if len(hidden_vertex_indices) > 0:
        _is_hidden_flag[hidden_vertex_indices] = True
    _all_verts_invalid = invalid_faces_arr.ravel()
    _boundary_mask = ~_is_hidden_flag[_all_verts_invalid]
    boundary_vertices = np.unique(
        _all_verts_invalid[_boundary_mask]).astype(np.int32)
    n_boundary = len(boundary_vertices)
    print(f"   🔷 {n_boundary} boundary vertices")
    if n_boundary < 3:
        cache.faces = valid_faces
        cache.shade = valid_shade
        cache.face_normals = valid_normals
        if valid_normals is not None and len(valid_normals) > 0:
            cache.vertex_normals = _compute_vertex_normals(
                cache.xyz_unique, valid_faces, valid_normals)
            cache.vertex_shade = _compute_shading(
                cache.vertex_normals,
                getattr(app, 'last_shade_azimuth', 45.0),
                getattr(app, 'last_shade_angle', 45.0),
                getattr(app, 'shade_ambient', 0.25))
        cache._vtk_colors_ptr = None
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        print(f"   ⚡ Complete (no patch): {(time.time()-t0)*1000:.0f}ms")
        return True
    t_tri = time.time()
    boundary_xyz = cache.xyz_unique[boundary_vertices]
    boundary_xy = boundary_xyz[:, :2]
    try:
        local_faces = _do_triangulate(boundary_xy)
        print(f"   🔺 Boundary triangulation: {len(local_faces)} raw faces")
    except Exception as e:
        print(f"   ⚠️ Triangulation failed: {e}")
        cache.faces = valid_faces
        cache.shade = valid_shade
        cache.face_normals = valid_normals
        cache._vtk_colors_ptr = None
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        return True
    if len(local_faces) == 0:
        cache.faces = valid_faces
        cache.shade = valid_shade
        cache.face_normals = valid_normals
        cache._vtk_colors_ptr = None
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        print(f"   ⚡ Complete (no faces): {(time.time()-t0)*1000:.0f}ms")
        return True
    x_range = boundary_xy[:, 0].max() - boundary_xy[:, 0].min()
    y_range = boundary_xy[:, 1].max() - boundary_xy[:, 1].min()
    boundary_extent = max(x_range, y_range)
    max_edge_len = max(boundary_extent * 0.5,
                       cache.spacing * cache.max_edge_factor)
    v0_xy = boundary_xy[local_faces[:, 0]]
    v1_xy = boundary_xy[local_faces[:, 1]]
    v2_xy = boundary_xy[local_faces[:, 2]]
    e0 = np.sqrt(((v1_xy - v0_xy) ** 2).sum(axis=1))
    e1 = np.sqrt(((v2_xy - v1_xy) ** 2).sum(axis=1))
    e2 = np.sqrt(((v0_xy - v2_xy) ** 2).sum(axis=1))
    max_edges = np.maximum(np.maximum(e0, e1), e2)
    valid_mask = max_edges <= max_edge_len
    local_faces = local_faces[valid_mask]
    print(f"   📐 After filter (max={max_edge_len:.2f}m): "
          f"{len(local_faces)} faces")
    print(f"   ⏱️ Triangulation: {(time.time()-t_tri)*1000:.0f}ms")
    if len(local_faces) == 0:
        cache.faces = valid_faces
        cache.shade = valid_shade
        cache.face_normals = valid_normals
        cache._vtk_colors_ptr = None
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        print(f"   ⚡ Complete (all filtered): {(time.time()-t0)*1000:.0f}ms")
        return True
    patch_faces = boundary_vertices[local_faces]
    patch_normals = _compute_face_normals(cache.xyz_unique, patch_faces)
    patch_shade = _compute_face_shade(
        cache.xyz_unique, patch_faces,
        getattr(app, 'last_shade_azimuth', 45.0),
        getattr(app, 'last_shade_angle', 45.0),
        getattr(app, 'shade_ambient', 0.25),
        face_normals=patch_normals)
    merged_faces = np.vstack([valid_faces, patch_faces])
    merged_shade = np.concatenate([valid_shade, patch_shade])
    merged_normals = (patch_normals if valid_normals is None
                      else np.vstack([valid_normals, patch_normals]))
    cache.faces = merged_faces
    cache.shade = merged_shade
    cache.face_normals = merged_normals
    _recompute_vertex_normals_partial(cache, len(valid_faces))
    cache._vtk_colors_ptr = None
    print(f"   ✅ Merged: {n_valid:,} + {len(patch_faces)} = "
          f"{len(merged_faces):,}")
    _render_mesh(app, cache, classes_raw, _save_camera(app))
    print(f"   ⚡ PATCH COMPLETE: {(time.time()-t0)*1000:.0f}ms")
    return True


def refresh_shaded_after_visibility_change(app, changed_global_indices,
                                            visible_classes_set):
    cache = get_cache()
    if cache.faces is None or cache.xyz_unique is None:
        print("   ⚠️ No cache — full rebuild")
        clear_shading_cache("no cache for incremental")
        update_shaded_class(app, force_rebuild=True)
        return
    success = _incremental_visibility_patch(
        app, changed_global_indices, visible_classes_set)
    if not success:
        print("   ⚠️ Incremental patch failed — full rebuild")
        clear_shading_cache("incremental patch failed")
        update_shaded_class(app, force_rebuild=True)


def _multi_class_region_undo_patch(app, changed_mask, visible_classes_set):
    cache = get_cache()
    if cache.faces is None or cache.xyz_unique is None:
        return False
    t0 = time.time()
    xyz = app.data.get("xyz")
    classes_raw = app.data.get("classification")
    if xyz is None or classes_raw is None:
        return False
    classes = classes_raw.astype(np.int32)
    vis_array = np.array(sorted(visible_classes_set), dtype=np.int32)
    changed_indices = np.where(changed_mask)[0]
    changed_xyz = xyz[changed_indices]
    x_min, y_min = changed_xyz[:, 0].min(), changed_xyz[:, 1].min()
    x_max, y_max = changed_xyz[:, 0].max(), changed_xyz[:, 1].max()
    margin = max(cache.spacing * 5, 1.0) if cache.spacing > 0 else 10.0
    x_min -= margin
    y_min -= margin
    x_max += margin
    y_max += margin
    print(f"   📐 Region: X=[{x_min:.1f},{x_max:.1f}] "
          f"Y=[{y_min:.1f},{y_max:.1f}]")
    cache_xyz = cache.xyz_final
    in_region_mesh = (
        (cache_xyz[:, 0] >= x_min) & (cache_xyz[:, 0] <= x_max) &
        (cache_xyz[:, 1] >= y_min) & (cache_xyz[:, 1] <= y_max)
    )
    v0_in = in_region_mesh[cache.faces[:, 0]]
    v1_in = in_region_mesh[cache.faces[:, 1]]
    v2_in = in_region_mesh[cache.faces[:, 2]]
    faces_in_region = v0_in & v1_in & v2_in
    faces_outside = cache.faces[~faces_in_region]
    shade_outside = cache.shade[~faces_in_region]
    normals_outside = (cache.face_normals[~faces_in_region]
                       if cache.face_normals is not None else None)
    n_removed = int(np.sum(faces_in_region))
    n_kept = len(faces_outside)
    print(f"   ✂️ Removed {n_removed:,} region faces, keeping {n_kept:,}")
    visible_mask_all = np.isin(classes, vis_array)
    vis_indices = np.where(visible_mask_all)[0]
    vis_xyz = xyz[vis_indices]
    in_region_vis = (
        (vis_xyz[:, 0] >= x_min) & (vis_xyz[:, 0] <= x_max) &
        (vis_xyz[:, 1] >= y_min) & (vis_xyz[:, 1] <= y_max)
    )
    local_global_indices = vis_indices[in_region_vis]
    local_xyz = vis_xyz[in_region_vis]
    n_local = len(local_xyz)
    print(f"   📍 {n_local:,} visible points in region")
    if n_local < 3:
        cache.faces = faces_outside
        cache.shade = shade_outside
        cache.face_normals = normals_outside
        cache._vtk_colors_ptr = None
        if normals_outside is not None and len(normals_outside) > 0:
            cache.vertex_normals = _compute_vertex_normals(
                cache.xyz_unique, faces_outside, normals_outside)
            cache.vertex_shade = _compute_shading(
                cache.vertex_normals,
                getattr(app, 'last_shade_azimuth', 45.0),
                getattr(app, 'last_shade_angle', 45.0),
                getattr(app, 'shade_ambient', 0.25))
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        print(f"   ⚠️ Too few points — cleared region only")
        return True
    local_offset = local_xyz.min(axis=0)
    local_xyz_off = local_xyz - local_offset
    _LOCAL_TRI_MAX = 80_000
    _x_ext = local_xyz_off[:, 0].max() - local_xyz_off[:, 0].min()
    _y_ext = local_xyz_off[:, 1].max() - local_xyz_off[:, 1].min()
    _area_m = max(_x_ext * _y_ext, 1.0)
    _nat_sp = np.sqrt(_area_m / max(n_local, 1))
    precision = max(_nat_sp * 0.3, 0.005)
    _proj_u = n_local / max((precision / max(_nat_sp, 1e-9)) ** 2, 1)
    if _proj_u > _LOCAL_TRI_MAX:
        precision = max(precision * np.sqrt(_proj_u / _LOCAL_TRI_MAX), 0.005)
    xy_grid = np.floor(local_xyz_off[:, :2] / precision).astype(np.int64)
    sort_idx = np.lexsort((-local_xyz_off[:, 2], xy_grid[:, 1], xy_grid[:, 0]))
    xy_sorted = xy_grid[sort_idx]
    diff = np.diff(xy_sorted, axis=0)
    unique_mask_local = np.concatenate(
        [[True], (diff[:, 0] != 0) | (diff[:, 1] != 0)])
    u_idx = sort_idx[unique_mask_local]
    unique_xyz = local_xyz_off[u_idx]
    unique_global = local_global_indices[u_idx]
    print(f"   📍 {len(unique_xyz):,} unique local points")
    if len(unique_xyz) < 3:
        cache.faces = faces_outside
        cache.shade = shade_outside
        cache.face_normals = normals_outside
        cache._vtk_colors_ptr = None
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        return True
    xy = unique_xyz[:, :2]
    try:
        local_faces = _do_triangulate(xy)
    except Exception as e:
        print(f"   ⚠️ Triangulation failed: {e}")
        cache.faces = faces_outside
        cache.shade = shade_outside
        cache.face_normals = normals_outside
        cache._vtk_colors_ptr = None
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        return True
    if len(local_faces) == 0:
        cache.faces = faces_outside
        cache.shade = shade_outside
        cache.face_normals = normals_outside
        cache._vtk_colors_ptr = None
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        return True
    x_range_l = xy[:, 0].max() - xy[:, 0].min()
    y_range_l = xy[:, 1].max() - xy[:, 1].min()
    local_spacing = np.sqrt((x_range_l * y_range_l) / max(len(xy), 1))
    max_edge = max(local_spacing * 100.0, cache.spacing * 100.0)
    local_faces = _filter_edges_by_absolute(local_faces, xy, max_edge)
    print(f"   📐 After filter: {len(local_faces):,} faces")
    if len(local_faces) == 0:
        cache.faces = faces_outside
        cache.shade = shade_outside
        cache.face_normals = normals_outside
        cache._vtk_colors_ptr = None
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        return True
    g2u = cache.build_global_to_unique(len(xyz))
    local_to_cache = g2u[unique_global]
    new_points_mask = (local_to_cache < 0)
    n_new = int(np.sum(new_points_mask))
    if n_new > 0:
        print(f"   ➕ Adding {n_new} new vertices to cache")
        new_global = unique_global[new_points_mask]
        new_xyz = unique_xyz[new_points_mask] + local_offset - cache.offset
        cache.unique_indices = np.concatenate([cache.unique_indices, new_global])
        cache.xyz_unique = np.vstack([cache.xyz_unique, new_xyz])
        cache.xyz_final = np.vstack([cache.xyz_final, new_xyz + cache.offset])
        cache._global_to_unique = None
        g2u = cache.build_global_to_unique(len(xyz))
        local_to_cache = g2u[unique_global]
    new_patch_faces = local_to_cache[local_faces]
    if np.any(new_patch_faces < 0):
        print(f"   ⚠️ Invalid face indices after mapping")
        return False
    patch_normals = _compute_face_normals(cache.xyz_unique, new_patch_faces)
    patch_shade = _compute_face_shade(
        cache.xyz_unique, new_patch_faces,
        getattr(app, 'last_shade_azimuth', 45.0),
        getattr(app, 'last_shade_angle', 45.0),
        getattr(app, 'shade_ambient', 0.25),
        face_normals=patch_normals)
    all_faces = np.vstack([faces_outside, new_patch_faces])
    all_shade = np.concatenate([shade_outside, patch_shade])
    all_normals = (patch_normals if normals_outside is None
                   else np.vstack([normals_outside, patch_normals]))
    cache.faces = all_faces
    cache.shade = all_shade
    cache.face_normals = all_normals
    _recompute_vertex_normals_partial(cache, len(faces_outside))
    cache._vtk_colors_ptr = None
    print(f"   ✅ Merged: {n_kept:,} + {len(new_patch_faces):,} = "
          f"{len(all_faces):,}")
    _render_mesh(app, cache, classes_raw, _save_camera(app))
    print(f"   ⚡ MULTI-CLASS REGION UNDO: {(time.time()-t0)*1000:.0f}ms")
    return True


def _rebuild_single_class(app, single_class_id):
    cache = get_cache()
    if cache.faces is None or len(cache.faces) == 0:
        cache.clear("no existing mesh")
        _do_full_rebuild(app, single_class_id)
        return
    t0 = time.time()
    classes = app.data.get("classification").astype(np.int32)
    cached_vertex_classes = classes[cache.unique_indices]
    vertices_left = (cached_vertex_classes != single_class_id)
    n_left = np.sum(vertices_left)
    if n_left == 0:
        print(f"   ✅ No vertices left class - no patch needed")
        return
    print(f"   🔧 INCREMENTAL PATCH: {n_left:,} vertices left class")
    v0_bad = vertices_left[cache.faces[:, 0]]
    v1_bad = vertices_left[cache.faces[:, 1]]
    v2_bad = vertices_left[cache.faces[:, 2]]
    invalid_face_mask = v0_bad | v1_bad | v2_bad
    valid_face_mask = ~invalid_face_mask
    n_invalid = np.sum(invalid_face_mask)
    n_valid = np.sum(valid_face_mask)
    print(f"   ✂️ {n_invalid:,} faces to remove, {n_valid:,} faces to keep")
    if n_valid == 0:
        cache.clear("all faces invalid")
        _do_full_rebuild(app, single_class_id)
        return
    removed_vertex_arr = np.where(vertices_left)[0].astype(np.int32)
    invalid_faces = cache.faces[invalid_face_mask]
    _is_removed_flag = np.zeros(len(cache.unique_indices), dtype=bool)
    if len(removed_vertex_arr) > 0:
        _is_removed_flag[removed_vertex_arr] = True
    _all_verts_bad = invalid_faces.ravel()
    _bnd_mask = ~_is_removed_flag[_all_verts_bad]
    boundary_vertices = np.unique(
        _all_verts_bad[_bnd_mask]).astype(np.int32)
    n_boundary = len(boundary_vertices)
    print(f"   🔷 {n_boundary} boundary vertices")
    new_patch_faces = np.array([], dtype=np.int32).reshape(0, 3)
    new_patch_shade = np.array([], dtype=np.float32)
    if n_boundary >= 3:
        t1 = time.time()
        boundary_xy = cache.xyz_unique[boundary_vertices, :2]
        try:
            local_faces = _do_triangulate(boundary_xy)
            print(f"   🔺 Local triangulation: {len(local_faces)} faces "
                  f"in {(time.time()-t1)*1000:.0f}ms")
            if len(local_faces) > 0:
                if n_boundary > 10:
                    x_range = (boundary_xy[:, 0].max() -
                                boundary_xy[:, 0].min())
                    y_range = (boundary_xy[:, 1].max() -
                                boundary_xy[:, 1].min())
                    local_spacing = np.sqrt((x_range * y_range) / n_boundary)
                    max_edge = max(local_spacing * 5, cache.spacing * 1000)
                    local_faces = _filter_edges_by_absolute(
                        local_faces, boundary_xy, max_edge)
                    print(f"   📐 After filter: {len(local_faces)} faces")
                if len(local_faces) > 0:
                    new_patch_faces = boundary_vertices[local_faces]
                    patch_normals = _compute_face_normals(
                        cache.xyz_unique, new_patch_faces)
                    new_patch_shade = _compute_face_shade(
                        cache.xyz_unique, new_patch_faces,
                        getattr(app, 'last_shade_azimuth', 45),
                        getattr(app, 'last_shade_angle', 45),
                        getattr(app, 'shade_ambient', 0.25),
                        face_normals=patch_normals)
        except Exception as e:
            print(f"   ⚠️ Local triangulation failed: {e}")
    valid_faces = cache.faces[valid_face_mask]
    valid_shade = cache.shade[valid_face_mask]
    valid_normals = (cache.face_normals[valid_face_mask]
                     if cache.face_normals is not None else None)
    if len(new_patch_faces) > 0:
        all_faces = np.vstack([valid_faces, new_patch_faces])
        all_shade = np.concatenate([valid_shade, new_patch_shade])
        patch_normals_merged = _compute_face_normals(
            cache.xyz_unique, new_patch_faces)
        all_normals = (patch_normals_merged if valid_normals is None
                       else np.vstack([valid_normals, patch_normals_merged]))
        print(f"   ✅ Merged: {len(valid_faces):,} + "
              f"{len(new_patch_faces)} = {len(all_faces):,} faces")
    else:
        all_faces = valid_faces
        all_shade = valid_shade
        all_normals = valid_normals
        print(f"   ✅ Kept {len(all_faces):,} faces (no patch)")
    cache.faces = all_faces
    cache.shade = all_shade
    cache.face_normals = all_normals
    _recompute_vertex_normals_partial(cache, len(valid_faces))
    cache._vtk_colors_ptr = None
    _render_mesh(app, cache, app.data.get("classification"), _save_camera(app))
    elapsed = (time.time() - t0) * 1000
    print(f"   ⚡ PATCH COMPLETE: {elapsed:.0f}ms")


def _do_full_rebuild(app, single_class_id):
    saved_visibility = {}
    for c in app.class_palette:
        saved_visibility[c] = app.class_palette[c].get("show", True)
        app.class_palette[c]["show"] = (int(c) == single_class_id)
    try:
        update_shaded_class(app, force_rebuild=True)
    finally:
        for c, vis in saved_visibility.items():
            app.class_palette[c]["show"] = vis


def _check_previous_classes_visible(app, changed_indices, vis_array):
    try:
        if hasattr(app, 'redostack') and app.redostack:
            step = app.redostack[-1]
            prev = step.get('newclasses') or step.get('new_classes')
            if prev is not None:
                if not hasattr(prev, '__iter__') or np.ndim(prev) == 0:
                    return int(prev) in set(vis_array.tolist())
                return bool(np.all(np.isin(np.asarray(prev), vis_array)))
        if hasattr(app, 'undostack') and app.undostack:
            step = app.undostack[-1]
            prev = step.get('oldclasses') or step.get('old_classes')
            if prev is not None:
                if not hasattr(prev, '__iter__') or np.ndim(prev) == 0:
                    return int(prev) in set(vis_array.tolist())
                return bool(np.all(np.isin(np.asarray(prev), vis_array)))
        all_palette = set(int(c) for c in app.class_palette.keys())
        all_visible = set(vis_array.tolist())
        if all_palette.issubset(all_visible):
            return True
        return False
    except Exception:
        return False


def refresh_shaded_after_undo_fast(app, changed_mask=None):
    cache = get_cache()
    if cache.faces is None or len(cache.faces) == 0:
        print("   ⚠️ No cache for undo - full rebuild needed")
        return False
    t0 = time.time()
    is_single_class = getattr(cache, 'n_visible_classes', 0) == 1
    single_class_id = getattr(cache, 'single_class_id', None)
    visible_classes = getattr(cache, 'visible_classes_set', None)
    if not visible_classes:
        visible_classes = _get_shading_visibility(app)
    print(f"   📊 Undo/Redo refresh: "
          f"{'single' if is_single_class else 'multi'}-class mode")
    print(f"   📊 Cached faces: {len(cache.faces):,}")
    if changed_mask is None or not np.any(changed_mask):
        print("   ⚡ No changed mask - full color update")
        return _update_colors_gpu_fast(app, cache, changed_mask=None)
    classes = app.data.get("classification")
    xyz = app.data.get("xyz")
    if classes is None or xyz is None:
        return False
    classes = classes.astype(np.int32)
    changed_indices = np.where(changed_mask)[0]
    if len(changed_indices) == 0:
        return True
    vis_array = (np.array(sorted(visible_classes), dtype=np.int32)
                 if visible_classes else np.array([], dtype=np.int32))
    now_visible = (np.isin(classes[changed_indices], vis_array)
                   if len(vis_array) > 0
                   else np.zeros(len(changed_indices), dtype=bool))
    if np.all(now_visible):
        prev_also_visible = _check_previous_classes_visible(
            app, changed_indices, vis_array)
        if prev_also_visible:
            print("   ⚡ No visibility change — fast color update")
            success = _update_colors_gpu_fast(
                app, cache, changed_mask=changed_mask)
            if success:
                global _rebuild_timer
                if _rebuild_timer is not None:
                    try:
                        _rebuild_timer.stop()
                        print("   ✅ Cancelled stale deferred rebuild timer")
                    except Exception:
                        pass
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ Undo color update: {elapsed:.0f}ms")
                return True
            print("   ⚠️ GPU color injection failed, trying geometry path")
    print("   🔨 Visibility change detected — geometry patch needed")
    g2u = cache.build_global_to_unique(len(xyz))
    changed_unique = g2u[changed_indices]
    in_cache = changed_unique >= 0
    used_vertices = np.zeros(len(cache.unique_indices), dtype=bool)
    if cache.faces is not None and len(cache.faces) > 0:
        used_vertices[np.unique(cache.faces.ravel())] = True
    active_in_mesh = np.zeros(len(changed_indices), dtype=bool)
    valid_pos = np.where(in_cache)[0]
    if len(valid_pos) > 0:
        active_in_mesh[valid_pos] = used_vertices[changed_unique[valid_pos]]
    hidden_mask = active_in_mesh & (~now_visible)
    visible_mask = now_visible & (~active_in_mesh)
    if np.any(visible_mask):
        prev_also_visible = _check_previous_classes_visible(
            app, changed_indices, vis_array)
        if prev_also_visible:
            print(f"   ℹ️ {np.sum(visible_mask)} points flagged as 'visible' "
                  f"are just downsampled — ignoring")
            visible_mask[:] = False
    points_became_hidden = changed_indices[hidden_mask]
    points_became_visible = changed_indices[visible_mask]
    if len(points_became_hidden) > 0:
        print(f"   🔍 {len(points_became_hidden):,} points became HIDDEN")
    if len(points_became_visible) > 0:
        print(f"   🔍 {len(points_became_visible):,} points became VISIBLE")
    visibility_changed = (len(points_became_hidden) > 0 or
                          len(points_became_visible) > 0)
    if not visibility_changed:
        print("   ⚡ No visibility change - fast color update")
        success = _update_colors_gpu_fast(
            app, cache, changed_mask=changed_mask)
        if success:
            elapsed = (time.time() - t0) * 1000
            print(f"   ⚡ Undo color update: {elapsed:.0f}ms")
            return True
        return False
    if not is_single_class or single_class_id is None:
        if len(points_became_visible) > 0:
            success = _multi_class_region_undo_patch(
                app, changed_mask, visible_classes)
            if success:
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ Multi-class undo region patch: {elapsed:.0f}ms")
                return True
            print("   ⚠️ Multi-class undo region patch failed")
            return False
        if len(points_became_hidden) > 0:
            success = _incremental_visibility_patch(
                app, points_became_hidden, visible_classes)
            if success:
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ Multi-class hidden patch: {elapsed:.0f}ms")
                return True
            print("   ⚠️ Multi-class hidden patch failed")
            return False
        return True
    if len(points_became_visible) > 0 and len(points_became_hidden) > 0:
        print("   ⚠️ Mixed single-class undo/redo change - full rebuild needed")
        return False
    if len(points_became_visible) > 0:
        _rebuild_single_class_for_undo(app, single_class_id, changed_mask)
        elapsed = (time.time() - t0) * 1000
        print(f"   ⚡ Single-class undo rebuild: {elapsed:.0f}ms")
        return True
    if len(points_became_hidden) > 0:
        _rebuild_single_class(app, single_class_id)
        elapsed = (time.time() - t0) * 1000
        print(f"   ⚡ Single-class redo patch: {elapsed:.0f}ms")
        return True
    return True


def _update_colors_gpu_fast(app, cache, changed_mask=None,
                             _visible_classes=None, _defer_render=False):
    t0 = time.time()
    try:
        mesh = getattr(app, '_shaded_mesh_polydata', None)
        if mesh is None:
            return False

        is_single = getattr(cache, 'n_visible_classes', 0) == 1
        single_class_id = getattr(cache, 'single_class_id', None)
        visible_classes = (_visible_classes if _visible_classes
                           else _get_shading_visibility(app))

        if is_single and single_class_id is not None:
            cell_colors = mesh.GetCellData().GetScalars()
            if (cell_colors is not None and
                    cell_colors.GetNumberOfTuples() == len(cache.faces)):
                vtk_ptr = numpy_support.vtk_to_numpy(cell_colors)
                az  = getattr(app, 'last_shade_azimuth', 45.0)
                el  = getattr(app, 'last_shade_angle',   45.0)
                amb = getattr(app, 'shade_ambient',       0.25)
                shade = (cache.shade
                         if cache.shade is not None and
                         len(cache.shade) == len(cache.faces)
                         else np.ones(len(cache.faces), dtype=np.float32))
                base_color = np.array(
                    app.class_palette.get(single_class_id, {}).get(
                        "color", (128, 128, 128)),
                    dtype=np.float32)
                new_colors = np.clip(
                    base_color * shade[:, None], 0, 255
                ).astype(np.uint8)
                vtk_ptr[:] = new_colors
                cell_colors.Modified()
                if _defer_render:
                    mesh.Modified()
                    actor = getattr(app, '_shaded_mesh_actor', None)
                    if actor:
                        actor.GetMapper().Modified()
                    QTimer.singleShot(0, lambda: (
                        app.vtk_widget.render()
                        if not getattr(app, 'is_dragging', False) else None
                    ))
                else:
                    app.vtk_widget.render()
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ GPU single-class face write: "
                      f"{len(cache.faces):,} faces in {elapsed:.0f}ms")
                return True

        point_colors = mesh.GetPointData().GetScalars()
        if (point_colors is None or
                point_colors.GetNumberOfTuples() != len(cache.unique_indices)):
            return False

        vtk_ptr = numpy_support.vtk_to_numpy(point_colors)
        classes = app.data.get("classification").astype(np.int32)
        classes_mesh = classes[cache.unique_indices]
        n_verts = len(classes_mesh)
        shade = (cache.vertex_shade
                 if cache.vertex_shade is not None and
                 len(cache.vertex_shade) == n_verts
                 else np.ones(n_verts, dtype=np.float32))

        max_c = max(int(classes_mesh.max()) + 1, 256)
        lut = np.zeros((max_c, 3), dtype=np.float32)
        for c, e in app.class_palette.items():
            ci = int(c)
            if ci < max_c and ci in visible_classes:
                lut[ci] = e.get("color", (128, 128, 128))
        vertex_class = np.clip(classes_mesh, 0, max_c - 1)

        if changed_mask is not None and np.any(changed_mask):
            g2u = cache.build_global_to_unique(len(app.data["xyz"]))
            changed_unique = g2u[np.where(changed_mask)[0]]
            changed_unique = changed_unique[
                (changed_unique >= 0) & (changed_unique < n_verts)]
            if len(changed_unique) > 0:
                vtk_ptr[changed_unique] = np.clip(
                    lut[vertex_class[changed_unique]] *
                    shade[changed_unique, None], 0, 255
                ).astype(np.uint8)
                point_colors.Modified()
                if _defer_render or len(changed_unique) < 500:
                    mesh.Modified()
                    actor = getattr(app, '_shaded_mesh_actor', None)
                    if actor:
                        actor.GetMapper().Modified()
                    QTimer.singleShot(0, lambda: (
                        app.vtk_widget.render()
                        if not getattr(app, 'is_dragging', False) else None
                    ))
                else:
                    app.vtk_widget.render()
                elapsed = (time.time() - t0) * 1000
                print(f"   ⚡ GPU partial vertex update: "
                      f"{len(changed_unique):,}/{n_verts:,} in {elapsed:.0f}ms")
                return True

        vtk_ptr[:] = np.clip(
            lut[vertex_class] * shade[:, None], 0, 255
        ).astype(np.uint8)
        point_colors.Modified()
        if _defer_render:
            mesh.Modified()
            actor = getattr(app, '_shaded_mesh_actor', None)
            if actor:
                actor.GetMapper().Modified()
            QTimer.singleShot(0, lambda: (
                app.vtk_widget.render()
                if not getattr(app, 'is_dragging', False) else None
            ))
        else:
            app.vtk_widget.render()
        elapsed = (time.time() - t0) * 1000
        print(f"   ⚡ GPU full vertex write: {n_verts:,} verts in "
              f"{elapsed:.0f}ms")
        return True

    except Exception as e:
        print(f"   ❌ GPU color injection failed: {e}")
        return False


def _rebuild_single_class_for_undo(app, single_class_id, changed_mask):
    cache = get_cache()
    if cache.faces is None or cache.xyz_unique is None:
        _do_full_rebuild(app, single_class_id)
        return
    t0 = time.time()
    classes = app.data.get("classification").astype(np.int32)
    xyz = app.data.get("xyz")
    changed_indices = np.where(changed_mask)[0]
    returned_mask = (classes[changed_indices] == single_class_id)
    returned_global_indices = changed_indices[returned_mask]
    if len(returned_global_indices) == 0:
        return
    print(f"   🔙 {len(returned_global_indices)} points returned to "
          f"class {single_class_id}")
    returned_xyz = xyz[returned_global_indices]
    x_min, y_min = returned_xyz[:, 0].min(), returned_xyz[:, 1].min()
    x_max, y_max = returned_xyz[:, 0].max(), returned_xyz[:, 1].max()
    margin = cache.spacing * 5 if cache.spacing > 0 else 1000.0
    x_min -= margin
    y_min -= margin
    x_max += margin
    y_max += margin
    all_visible_mask = (classes == single_class_id)
    all_visible_indices = np.where(all_visible_mask)[0]
    all_visible_xyz = xyz[all_visible_indices]
    in_region = (
        (all_visible_xyz[:, 0] >= x_min) & (all_visible_xyz[:, 0] <= x_max) &
        (all_visible_xyz[:, 1] >= y_min) & (all_visible_xyz[:, 1] <= y_max)
    )
    local_global_indices = all_visible_indices[in_region]
    local_xyz = all_visible_xyz[in_region]
    n_local = len(local_xyz)
    if n_local < 3:
        return
    cache_xyz = cache.xyz_final
    in_region_mesh = (
        (cache_xyz[:, 0] >= x_min) & (cache_xyz[:, 0] <= x_max) &
        (cache_xyz[:, 1] >= y_min) & (cache_xyz[:, 1] <= y_max)
    )
    v0_in = in_region_mesh[cache.faces[:, 0]]
    v1_in = in_region_mesh[cache.faces[:, 1]]
    v2_in = in_region_mesh[cache.faces[:, 2]]
    faces_in_region_mask = v0_in & v1_in & v2_in
    faces_outside_region = cache.faces[~faces_in_region_mask]
    shade_outside = cache.shade[~faces_in_region_mask]
    normals_outside = (cache.face_normals[~faces_in_region_mask]
                       if cache.face_normals is not None else None)
    n_kept = len(faces_outside_region)
    
    local_offset = local_xyz.min(axis=0)
    local_xyz_offset = local_xyz - local_offset
    _LOCAL_TRI_MAX = 80_000
    x_ext = local_xyz_offset[:, 0].max() - local_xyz_offset[:, 0].min()
    y_ext = local_xyz_offset[:, 1].max() - local_xyz_offset[:, 1].min()
    _area = max(x_ext * y_ext, 1.0)
    _nat_spacing = np.sqrt(_area / max(n_local, 1))
    precision = max(_nat_spacing * 0.3, 0.005)
    _proj_unique = n_local / max((precision / max(_nat_spacing, 1e-9)) ** 2, 1)
    if _proj_unique > _LOCAL_TRI_MAX:
        precision = max(precision * np.sqrt(_proj_unique / _LOCAL_TRI_MAX),
                        0.005)
    xy_grid = np.floor(local_xyz_offset[:, :2] / precision).astype(np.int64)
    sort_idx = np.lexsort(
        (-local_xyz_offset[:, 2], xy_grid[:, 1], xy_grid[:, 0]))
    xy_sorted = xy_grid[sort_idx]
    diff = np.diff(xy_sorted, axis=0)
    unique_mask = np.concatenate(
        [[True], (diff[:, 0] != 0) | (diff[:, 1] != 0)])
    unique_local_idx = sort_idx[unique_mask]
    unique_local_xyz = local_xyz_offset[unique_local_idx]
    unique_local_global = local_global_indices[unique_local_idx]
    if len(unique_local_xyz) < 3:
        return
    xy = unique_local_xyz[:, :2]
    try:
        local_faces = _do_triangulate(xy)
    except Exception as e:
        print(f"   ⚠️ Local triangulation failed: {e}")
        return
    if len(local_faces) == 0:
        return
    x_range = xy[:, 0].max() - xy[:, 0].min()
    y_range = xy[:, 1].max() - xy[:, 1].min()
    local_spacing = (np.sqrt((x_range * y_range) / len(xy))
                     if len(xy) > 0 else cache.spacing)
    max_edge = max(local_spacing * 5, cache.spacing * 1000)
    local_faces = _filter_edges_by_absolute(local_faces, xy, max_edge)
    if len(local_faces) == 0:
        return
    g2u = cache.build_global_to_unique(len(xyz))
    local_to_cache = g2u[unique_local_global]
    new_points_mask = (local_to_cache < 0)
    n_new = np.sum(new_points_mask)
    if n_new > 0:
        new_global_indices = unique_local_global[new_points_mask]
        new_xyz = (unique_local_xyz[new_points_mask] +
                   local_offset - cache.offset)
        cache.unique_indices = np.concatenate(
            [cache.unique_indices, new_global_indices])
        cache.xyz_unique = np.vstack([cache.xyz_unique, new_xyz])
        cache.xyz_final = np.vstack(
            [cache.xyz_final, new_xyz + cache.offset])
        cache._global_to_unique = None
        g2u = cache.build_global_to_unique(len(xyz))
        local_to_cache = g2u[unique_local_global]
    new_patch_faces = local_to_cache[local_faces]
    if np.any(new_patch_faces < 0):
        return
    fn = _compute_face_normals(cache.xyz_unique, new_patch_faces)
    new_patch_shade = _compute_face_shade(
        cache.xyz_unique, new_patch_faces,
        getattr(app, 'last_shade_azimuth', 45),
        getattr(app, 'last_shade_angle', 45),
        getattr(app, 'shade_ambient', 0.25),
        face_normals=fn)
    all_faces = np.vstack([faces_outside_region, new_patch_faces])
    all_shade = np.concatenate([shade_outside, new_patch_shade])
    all_normals = (fn if normals_outside is None
                   else np.vstack([normals_outside, fn]))
    cache.faces = all_faces
    cache.shade = all_shade
    cache.face_normals = all_normals
    _recompute_vertex_normals_partial(cache, len(faces_outside_region))
    cache._vtk_colors_ptr = None
    _render_mesh(app, cache, app.data.get("classification"), _save_camera(app))
    elapsed = (time.time() - t0) * 1000
    print(f"   ⚡ UNDO PATCH COMPLETE: {elapsed:.0f}ms")


def _fast_incremental_add_points(app, new_global_indices):
    cache = get_cache()
    if (cache.faces is None or cache.xyz_unique is None or
            cache.xyz_final is None):
        return False
    if len(new_global_indices) == 0:
        return True
    t0 = time.time()
    xyz_raw = app.data.get("xyz")
    classes_raw = app.data.get("classification")
    if xyz_raw is None or classes_raw is None:
        return False
    g2u = cache.build_global_to_unique(len(xyz_raw))
    not_in_mesh = g2u[new_global_indices] < 0
    missing_global = new_global_indices[not_in_mesh]
    if len(missing_global) == 0:
        print(f"   ⚡ All {len(new_global_indices)} points already in mesh "
              f"— color-only update")
        return _update_colors_gpu_fast(app, cache, changed_mask=None)
    n_new = len(missing_global)
    print(f"   ⚡ Fast incremental add: {n_new} new points")
    new_xyz_raw = xyz_raw[missing_global]
    new_xyz_local = (new_xyz_raw - cache.offset).astype(np.float64)
    x_min = new_xyz_local[:, 0].min()
    y_min = new_xyz_local[:, 1].min()
    x_max = new_xyz_local[:, 0].max()
    y_max = new_xyz_local[:, 1].max()
    margin = max(cache.spacing * 8, 0.5)
    x_min -= margin
    y_min -= margin
    x_max += margin
    y_max += margin
    existing_in_box = (
        (cache.xyz_unique[:, 0] >= x_min) &
        (cache.xyz_unique[:, 0] <= x_max) &
        (cache.xyz_unique[:, 1] >= y_min) &
        (cache.xyz_unique[:, 1] <= y_max)
    )
    existing_indices = np.where(existing_in_box)[0]
    n_existing_local = len(existing_indices)
    old_n_verts = len(cache.xyz_unique)
    new_vert_start = old_n_verts
    cache.unique_indices = np.concatenate(
        [cache.unique_indices, missing_global])
    cache.xyz_unique = np.vstack([cache.xyz_unique, new_xyz_local])
    cache.xyz_final = np.vstack([cache.xyz_final, new_xyz_raw])
    cache._global_to_unique = None
    cache._vtk_colors_ptr = None
    new_vert_indices = np.arange(
        new_vert_start, new_vert_start + n_new, dtype=np.int32)
    if n_existing_local > 0:
        _in_box = np.zeros(len(cache.xyz_unique), dtype=bool)
        _in_box[existing_indices] = True
        _in_box[new_vert_indices] = True
        v0_in = _in_box[cache.faces[:, 0]]
        v1_in = _in_box[cache.faces[:, 1]]
        v2_in = _in_box[cache.faces[:, 2]]
        faces_in_region = v0_in & v1_in & v2_in
        faces_outside = cache.faces[~faces_in_region]
        shade_outside = (cache.shade[~faces_in_region]
                         if cache.shade is not None else np.array([]))
        normals_outside = (cache.face_normals[~faces_in_region]
                           if cache.face_normals is not None else None)
        n_removed = int(np.sum(faces_in_region))
    else:
        faces_outside = cache.faces
        shade_outside = (cache.shade if cache.shade is not None
                         else np.array([]))
        normals_outside = cache.face_normals
        n_removed = 0
    local_all_indices = np.concatenate([existing_indices, new_vert_indices])
    local_xy = cache.xyz_unique[local_all_indices, :2]
    n_local_total = len(local_all_indices)
    if n_local_total < 3:
        cache.faces = faces_outside
        cache.shade = shade_outside
        cache.face_normals = normals_outside
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        return True
    t_tri = time.time()
    try:
        local_faces = _do_triangulate(local_xy)
    except Exception as e:
        print(f"   ⚠️ Local triangulation failed: {e}")
        cache.faces = faces_outside
        cache.shade = shade_outside
        cache.face_normals = normals_outside
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        return True
    tri_ms = (time.time() - t_tri) * 1000
    if len(local_faces) > 0:
        x_range_l = local_xy[:, 0].max() - local_xy[:, 0].min()
        y_range_l = local_xy[:, 1].max() - local_xy[:, 1].min()
        local_extent = max(x_range_l, y_range_l)
        max_edge_len = max(local_extent * 0.5,
                           cache.spacing * cache.max_edge_factor)
        local_faces = _filter_edges_by_absolute(
            local_faces, local_xy, max_edge_len)
    if len(local_faces) == 0:
        cache.faces = faces_outside
        cache.shade = shade_outside
        cache.face_normals = normals_outside
        _render_mesh(app, cache, classes_raw, _save_camera(app))
        return True
    patch_faces = local_all_indices[local_faces]
    patch_normals = _compute_face_normals(cache.xyz_unique, patch_faces)
    patch_shade = _compute_face_shade(
        cache.xyz_unique, patch_faces,
        getattr(app, 'last_shade_azimuth', 45.0),
        getattr(app, 'last_shade_angle', 45.0),
        getattr(app, 'shade_ambient', 0.25),
        face_normals=patch_normals)
    n_kept = len(faces_outside)
    cache.faces = np.vstack([faces_outside, patch_faces])
    cache.shade = np.concatenate([shade_outside, patch_shade])
    cache.face_normals = (patch_normals if normals_outside is None
                          else np.vstack([normals_outside, patch_normals]))
    _recompute_vertex_normals_partial(cache, n_kept)
    visible_classes = _get_shading_visibility(app)
    cache.visible_classes_hash = cache.get_visible_hash(visible_classes)
    cache.data_hash = hash((len(xyz_raw), float(xyz_raw[0, 0]),
                            float(xyz_raw[-1, 2])))
    _render_mesh(app, cache, classes_raw, _save_camera(app))
    elapsed = (time.time() - t0) * 1000
    print(f"   ⚡ FAST ADD: +{n_new} pts, -{n_removed} faces, "
          f"+{len(patch_faces)} faces, tri={tri_ms:.0f}ms, "
          f"total={elapsed:.0f}ms")
    return True


def _rebuild_mesh_vtk(app, cache, classes_raw, saved_camera):
    _render_mesh(app, cache, classes_raw, saved_camera)


def refresh_shaded_colors_fast(app):
    if getattr(app, 'display_mode', None) != "shaded_class":
        return
    refresh_shaded_after_classification_fast(app, None)


def refresh_shaded_colors_only(app):
    refresh_shaded_colors_fast(app)


def on_class_visibility_changed(app):
    if getattr(app, 'display_mode', None) == "shaded_class":
        clear_shading_cache("visibility changed")
        update_shaded_class(app, force_rebuild=True)


def handle_shaded_view_change(app, view_name):
    try:
        actor = getattr(app, '_shaded_mesh_actor', None)
        if not actor:
            return
        bounds = actor.GetMapper().GetInput().GetBounds()
        cx = (bounds[0] + bounds[1]) / 2
        cy = (bounds[2] + bounds[3]) / 2
        cz = (bounds[4] + bounds[5]) / 2
        ex = bounds[1] - bounds[0]
        ey = bounds[3] - bounds[2]
        ez = bounds[5] - bounds[4]
        d = max(ex, ey, ez) * 2
        cam = app.vtk_widget.renderer.GetActiveCamera()
        if view_name in ("plan", "top"):
            cam.SetPosition(cx, cy, cz + d)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 1, 0)
            cam.SetParallelProjection(True)
            cam.SetParallelScale(max(ex, ey) / 2)
        elif view_name == "front":
            cam.SetPosition(cx, cy - d, cz)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 0, 1)
            cam.SetParallelProjection(True)
        elif view_name in ("side", "left"):
            cam.SetPosition(cx - d, cy, cz)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 0, 1)
            cam.SetParallelProjection(True)
        else:
            cam.SetPosition(cx - d * .7, cy - d * .7, cz + d * .7)
            cam.SetFocalPoint(cx, cy, cz)
            cam.SetViewUp(0, 0, 1)
            cam.SetParallelProjection(False)
        app.vtk_widget.renderer.ResetCameraClippingRange()
        app.vtk_widget.render()
    except:
        pass


class ShadingControlPanel(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Shading")
        layout = QVBoxLayout()
        for label, attr, range_, default, step in [
            ("Max edge (m):", "max_edge", (1, 1000), 100, 10),
            ("Azimuth:",      "az",       (0, 360),  45,  5),
            ("Angle:",        "el",       (0, 90),   45,  5),
            ("Ambient:",      "amb",      (0, 1),    0.25, 0.05),
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
        """Restore spin box values from app state."""
        az  = getattr(self.app, 'last_shade_azimuth', None)
        el  = getattr(self.app, 'last_shade_angle',   None)
        amb = getattr(self.app, 'shade_ambient',       None)
        if az  is not None: self.az.setValue(az)
        if el  is not None: self.el.setValue(el)
        if amb is not None: self.amb.setValue(amb)

    def _on_apply(self):
        az  = self.az.value()
        el  = self.el.value()
        amb = self.amb.value()
        self.app.last_shade_azimuth = az
        self.app.last_shade_angle   = el
        self.app.shade_ambient      = amb
        update_shaded_class(
            self.app, az, el, amb,
            single_class_max_edge=self.max_edge.value()
        )

    def _on_full_rebuild(self):
        az  = self.az.value()
        el  = self.el.value()
        amb = self.amb.value()
        self.app.last_shade_azimuth = az
        self.app.last_shade_angle   = el
        self.app.shade_ambient      = amb
        clear_shading_cache("manual")
        update_shaded_class(
            self.app, az, el, amb,
            force_rebuild=True,
            single_class_max_edge=self.max_edge.value()
        )


__all__ = [
    'update_shaded_class',
    'refresh_shaded_colors_fast',
    'refresh_shaded_colors_only',
    'refresh_shaded_after_classification_fast',
    'refresh_shaded_after_undo_fast',
    'refresh_shaded_after_visibility_change',
    'handle_shaded_view_change',
    '_multi_class_region_undo_patch',
    'ShadingControlPanel',
    'clear_shading_cache',
    'get_cache',
    'invalidate_cache_for_new_file',
    'on_class_visibility_changed',
    '_get_shading_visibility',
]
