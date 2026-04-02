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
_rebuild_timer = None
_rebuild_reason = ""
_rebuild_changed_indices = None

try:
    from numba import njit, prange
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
            length = np.sqrt(nx * nx + ny * ny + nz * nz)
            if length > 1e-10:
                nx, ny, nz = nx / length, ny / length, nz / length
            if nz < 0 and abs(nz) > 0.3:
                nx, ny, nz = -nx, -ny, -nz
            fn[i, 0] = nx; fn[i, 1] = ny; fn[i, 2] = nz
        return fn

    @njit(fastmath=True)
    def _compute_vertex_normals_fast(xyz, faces, fn):
        n_verts = xyz.shape[0]
        vn = np.zeros((n_verts, 3), dtype=np.float64)
        n_faces = faces.shape[0]
        for i in range(n_faces):
            v0, v1, v2 = faces[i, 0], faces[i, 1], faces[i, 2]
            p0x, p0y, p0z = xyz[v0]; p1x, p1y, p1z = xyz[v1]; p2x, p2y, p2z = xyz[v2]
            axx, ay, az = p1x - p0x, p1y - p0y, p1z - p0z
            bx, by, bz = p2x - p0x, p2y - p0y, p2z - p0z
            cx = ay * bz - az * by; cy = az * bx - axx * bz; cz = axx * by - ay * bx
            area = 0.5 * np.sqrt(cx * cx + cy * cy + cz * cz)
            wx, wy, wz = fn[i, 0] * area, fn[i, 1] * area, fn[i, 2] * area
            vn[v0, 0] += wx; vn[v0, 1] += wy; vn[v0, 2] += wz
            vn[v1, 0] += wx; vn[v1, 1] += wy; vn[v1, 2] += wz
            vn[v2, 0] += wx; vn[v2, 1] += wy; vn[v2, 2] += wz
        for i in range(n_verts):
            nx, ny, nz = vn[i, 0], vn[i, 1], vn[i, 2]
            length = np.sqrt(nx * nx + ny * ny + nz * nz)
            if length < 1e-10:
                vn[i, 0] = 0.0; vn[i, 1] = 0.0; vn[i, 2] = 1.0
            else:
                vn[i, 0] = nx / length; vn[i, 1] = ny / length; vn[i, 2] = nz / length
        return vn

    @njit(parallel=True, fastmath=True)
    def _compute_shading_fast(normals, z_values, lx, ly, lz, hx, hy, hz, ambient, z_lo, z_range):
        n = normals.shape[0]
        shade = np.empty(n, dtype=np.float32)
        has_z = z_range > 1e-5
        for i in prange(n):
            nx, ny, nz = normals[i, 0], normals[i, 1], normals[i, 2]
            ndotl = max(0.0, nx * lx + ny * ly + nz * lz)
            ndoth = max(0.0, nx * hx + ny * hy + nz * hz)
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
            fz[i] = (xyz[faces[i, 0], 2] + xyz[faces[i, 1], 2] + xyz[faces[i, 2], 2]) / 3.0
        return fz

    @njit(parallel=True, fastmath=True)
    def _numba_edge_filter(faces, xy, max_edge_sq):
        n = faces.shape[0]
        keep = np.empty(n, dtype=np.bool_)
        for i in prange(n):
            x0, y0 = xy[faces[i, 0], 0], xy[faces[i, 0], 1]
            x1, y1 = xy[faces[i, 1], 0], xy[faces[i, 1], 1]
            x2, y2 = xy[faces[i, 2], 0], xy[faces[i, 2], 1]
            e0 = (x1-x0)*(x1-x0) + (y1-y0)*(y1-y0)
            e1 = (x2-x1)*(x2-x1) + (y2-y1)*(y2-y1)
            e2 = (x0-x2)*(x0-x2) + (y0-y2)*(y0-y2)
            mx = e0
            if e1 > mx: mx = e1
            if e2 > mx: mx = e2
            keep[i] = mx <= max_edge_sq
        return keep

    @njit(parallel=True, fastmath=True)
    def _numba_degenerate_filter(faces, xy, min_area, min_aspect):
        n = faces.shape[0]
        keep = np.empty(n, dtype=np.bool_)
        for i in prange(n):
            x0, y0 = xy[faces[i, 0], 0], xy[faces[i, 0], 1]
            x1, y1 = xy[faces[i, 1], 0], xy[faces[i, 1], 1]
            x2, y2 = xy[faces[i, 2], 0], xy[faces[i, 2], 1]
            d0x, d0y = x1 - x0, y1 - y0
            cross_z = d0x * (y2 - y0) - d0y * (x2 - x0)
            tri_area = abs(cross_z) * 0.5
            d1x, d1y = x2 - x1, y2 - y1
            d2x, d2y = x0 - x2, y0 - y2
            e0 = d0x*d0x + d0y*d0y; e1 = d1x*d1x + d1y*d1y; e2 = d2x*d2x + d2y*d2y
            mx = e0
            if e1 > mx: mx = e1
            if e2 > mx: mx = e2
            keep[i] = (tri_area > min_area) and (tri_area / (mx + 1e-10) > min_aspect)
        return keep

if HAS_NUMBA:
    def _warmup_numba_jit():
        try:
            _xyz = np.array([[0,0,0],[1,0,0],[0,1,0],[1,1,1]], dtype=np.float64)
            _f = np.array([[0,1,2],[1,2,3]], dtype=np.int32)
            _fn = _compute_face_normals_fast(_xyz, _f)
            _compute_vertex_normals_fast(_xyz, _f, _fn)
            _z = np.array([0.0, 1.0], dtype=np.float64)
            _compute_shading_fast(_fn, _z, .5,.5,.7, .3,.3,.9, .25, 0., 1.)
            _fast_centroids_z(_xyz, _f)
            _xy = np.array([[0.,0.],[1.,0.],[0.,1.]], dtype=np.float64)
            _gf = np.array([[0,1,2]], dtype=np.int32)
            _numba_edge_filter(_gf, _xy, 100.)
            _numba_degenerate_filter(_gf, _xy, 1e-6, 0.001)
        except: pass
    import threading
    threading.Thread(target=_warmup_numba_jit, daemon=True).start()


def triangulate_with_triangle(xy):
    if not HAS_TRIANGLE: raise ImportError("no triangle")
    return tr.triangulate({'vertices': xy.astype(np.float64)}, 'Qz')['triangles'].astype(np.int32)

def triangulate_scipy_direct(xy):
    return Delaunay(xy).simplices.astype(np.int32)

def _do_triangulate(xy):
    if HAS_TRIANGLE:
        try: return triangulate_with_triangle(xy)
        except: pass
    return triangulate_scipy_direct(xy)

def _filter_edges_by_absolute(faces, xy, max_edge_length):
    if len(faces) == 0: return faces
    if HAS_NUMBA:
        return faces[_numba_edge_filter(faces, xy, max_edge_length * max_edge_length)]
    v0, v1, v2 = xy[faces[:,0]], xy[faces[:,1]], xy[faces[:,2]]
    e0 = ((v1-v0)**2).sum(1); e1 = ((v2-v1)**2).sum(1); e2 = ((v0-v2)**2).sum(1)
    return faces[np.maximum(np.maximum(e0, e1), e2) <= max_edge_length**2]

def _filter_edges_3d_abs(faces, xyz, max_xy, max_slope_ratio=10.0):
    if len(faces) == 0: return faces
    xy = xyz[:, :2]
    if HAS_NUMBA:
        return faces[_numba_edge_filter(faces, xy, max_xy * max_xy)]
    v0, v1, v2 = xy[faces[:,0]], xy[faces[:,1]], xy[faces[:,2]]
    e0 = ((v1-v0)**2).sum(1); e1 = ((v2-v1)**2).sum(1); e2 = ((v0-v2)**2).sum(1)
    return faces[np.maximum(np.maximum(e0, e1), e2) <= max_xy**2]

def _compute_face_normals(xyz, faces):
    if len(faces) == 0: return np.array([]).reshape(0, 3)
    if HAS_NUMBA: return _compute_face_normals_fast(xyz, faces)
    p0, p1, p2 = xyz[faces[:,0]], xyz[faces[:,1]], xyz[faces[:,2]]
    fn = np.cross(p1-p0, p2-p0)
    l = np.linalg.norm(fn, axis=1, keepdims=True)
    fn = fn / np.maximum(l, 1e-10)
    m = (fn[:,2] < 0) & (np.abs(fn[:,2]) > 0.3); fn[m] *= -1
    return fn

def _compute_vertex_normals(xyz, faces, face_normals):
    if len(faces) == 0:
        vn = np.zeros((len(xyz), 3), dtype=np.float64); vn[:,2] = 1.0; return vn.astype(np.float32)
    if HAS_NUMBA:
        return _compute_vertex_normals_fast(xyz, faces, face_normals).astype(np.float32)
    n = len(xyz); vn = np.zeros((n, 3), dtype=np.float64)
    p0, p1, p2 = xyz[faces[:,0]], xyz[faces[:,1]], xyz[faces[:,2]]
    a = 0.5 * np.linalg.norm(np.cross(p1-p0, p2-p0), axis=1)
    w = face_normals * a[:, np.newaxis]
    np.add.at(vn, faces[:,0], w); np.add.at(vn, faces[:,1], w); np.add.at(vn, faces[:,2], w)
    l = np.linalg.norm(vn, axis=1, keepdims=True)
    vn = vn / np.maximum(l, 1e-10); vn[l.ravel() < 1e-10] = [0,0,1]
    return vn.astype(np.float32)

def _recompute_vertex_normals_partial(cache, patch_face_start_idx):
    if cache.face_normals is None or cache.faces is None or len(cache.faces) == 0: return
    if patch_face_start_idx >= len(cache.faces): return
    if cache.xyz_unique is None or len(cache.xyz_unique) == 0: return
    nv = len(cache.xyz_unique)
    if cache.vertex_normals is None or len(cache.vertex_normals) < nv:
        no = len(cache.vertex_normals) if cache.vertex_normals is not None else 0
        na = nv - no; nn = np.zeros((na, 3), dtype=np.float32); nn[:,2] = 1.0
        cache.vertex_normals = nn if cache.vertex_normals is None or no == 0 else np.vstack([cache.vertex_normals, nn])
    if cache.vertex_shade is None or len(cache.vertex_shade) < nv:
        no = len(cache.vertex_shade) if cache.vertex_shade is not None else 0
        na = nv - no; amb = cache.last_ambient if cache.last_ambient >= 0 else 0.25
        ns = np.full(na, float(amb), dtype=np.float32)
        cache.vertex_shade = ns if cache.vertex_shade is None or no == 0 else np.concatenate([cache.vertex_shade, ns])
    pv2 = np.unique(cache.faces[patch_face_start_idx:].ravel()); pv2 = pv2[pv2 < nv]
    if len(pv2) == 0: return
    am = np.isin(cache.faces[:,0], pv2) | np.isin(cache.faces[:,1], pv2) | np.isin(cache.faces[:,2], pv2)
    af = cache.faces[am]; afn = cache.face_normals[am]
    if len(af) == 0: return
    p0 = cache.xyz_unique[af[:,0]]; p1 = cache.xyz_unique[af[:,1]]; p2 = cache.xyz_unique[af[:,2]]
    a = 0.5 * np.linalg.norm(np.cross(p1-p0, p2-p0), axis=1); w = afn * a[:, None]
    cache.vertex_normals[pv2] = 0.0
    np.add.at(cache.vertex_normals, af[:,0], w); np.add.at(cache.vertex_normals, af[:,1], w); np.add.at(cache.vertex_normals, af[:,2], w)
    l = np.linalg.norm(cache.vertex_normals[pv2], axis=1, keepdims=True)
    cache.vertex_normals[pv2] /= np.maximum(l, 1e-10)
    if cache.vertex_shade is not None and len(cache.vertex_shade) >= nv and cache.last_azimuth >= 0:
        pn = cache.vertex_normals[pv2]; pz = cache.xyz_unique[pv2, 2]
        ar = np.radians(cache.last_azimuth); er = np.radians(cache.last_angle); amb = cache.last_ambient
        ld = np.array([np.cos(er)*np.cos(ar), np.cos(er)*np.sin(ar), np.sin(er)], dtype=np.float64)
        ld /= np.linalg.norm(ld); N = pn.astype(np.float64)
        NdL = np.maximum((N*ld).sum(1), 0.0)
        hv = ld + np.array([0.,0.,1.]); hv /= np.linalg.norm(hv)
        NdH = np.maximum((N*hv).sum(1), 0.0)
        ni = np.clip(amb + 0.70*NdL + 0.25*(NdH**64.), 0., 1.); ni = np.power(ni, 0.85)
        za = cache.xyz_unique[:,2]; zl = float(np.percentile(za, 1)); zh = float(np.percentile(za, 99))
        zr = max(zh-zl, 1e-3); er2 = np.clip((pz-zl)/zr, 0., 1.); er2 = 0.15 + 0.85*er2
        cache.vertex_shade[pv2] = np.clip(0.70*ni + 0.30*er2, 0., 1.).astype(np.float32)

def _compute_shading(normals, azimuth, angle, ambient, z_values=None):
    if len(normals) == 0: return np.array([])
    az, el = np.radians(azimuth), np.radians(angle)
    lx, ly, lz = np.cos(el)*np.cos(az), np.cos(el)*np.sin(az), np.sin(el)
    hx, hy, hz = lx, ly, lz+1.0; hl = np.sqrt(hx*hx+hy*hy+hz*hz)
    if hl > 1e-10: hx, hy, hz = hx/hl, hy/hl, hz/hl
    if HAS_NUMBA:
        if z_values is not None and len(z_values) == len(normals):
            zl = float(np.percentile(z_values, 1)); zh = float(np.percentile(z_values, 99)); zr = max(zh-zl, 1e-3)
        else: zl, zr = 0., 0.; z_values = np.empty(0, dtype=np.float64)
        return _compute_shading_fast(normals, z_values, lx, ly, lz, hx, hy, hz, ambient, zl, zr)
    ld = np.array([lx,ly,lz], dtype=np.float64); NdL = np.maximum((normals*ld).sum(1), 0.)
    hv = np.array([hx,hy,hz], dtype=np.float64); NdH = np.maximum((normals*hv).sum(1), 0.)
    ni = np.clip(ambient + 0.70*NdL + 0.25*(NdH**64.), 0., 1.); ni = np.power(ni, 0.85)
    if z_values is not None and len(z_values) == len(normals):
        zl = float(np.percentile(z_values, 1)); zh = float(np.percentile(z_values, 99)); zr = max(zh-zl, 1e-3)
        er = np.clip((z_values-zl)/zr, 0., 1.); er = 0.15 + 0.85*er
        return np.clip(0.70*ni + 0.30*er, 0., 1.)
    return np.clip(ni, 0., 1.)

def _compute_face_shade(xyz, faces, azimuth, angle, ambient, face_normals=None, z_values=None):
    if xyz is None or faces is None or len(faces) == 0: return np.array([], dtype=np.float32)
    if face_normals is None or len(face_normals) != len(faces): face_normals = _compute_face_normals(xyz, faces)
    fz = _fast_centroids_z(xyz, faces) if HAS_NUMBA else xyz[faces, 2].mean(axis=1)
    return _compute_shading(face_normals, azimuth, angle, ambient, z_values=fz)

def _remove_shaded_edge_overlay(app):
    p = getattr(app, 'vtk_widget', None)
    if p:
        try: p.remove_actor("shaded_mesh_edges", render=False)
        except: pass
    app._shaded_mesh_edge_actor = None; app._shaded_mesh_edge_polydata = None

def _setup_microstation_lighting(renderer, azimuth=45., angle=45.):
    renderer.RemoveAllLights()
    ar, er = np.radians(azimuth), np.radians(angle)
    kl = vtk.vtkLight(); kl.SetLightTypeToSceneLight()
    kl.SetPosition(np.cos(er)*np.cos(ar)*100, np.cos(er)*np.sin(ar)*100, np.sin(er)*100)
    kl.SetFocalPoint(0,0,0); kl.SetIntensity(0.85); kl.SetColor(1.,1.,0.98); kl.SetPositional(False)
    renderer.AddLight(kl)
    fl = vtk.vtkLight(); fl.SetLightTypeToSceneLight()
    fl.SetPosition(-np.cos(er)*np.cos(ar)*100, -np.cos(er)*np.sin(ar)*100, np.sin(er)*50)
    fl.SetFocalPoint(0,0,0); fl.SetIntensity(0.15); fl.SetColor(0.85,0.85,1.); fl.SetPositional(False)
    renderer.AddLight(fl); renderer.SetAmbient(0.20, 0.20, 0.20)


class ShadingGeometryCache:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls); cls._instance._initialized = False
        return cls._instance
    def __init__(self):
        if self._initialized: return
        self._initialized = True; self._clear_internal()
    def _clear_internal(self):
        self.xyz_unique = None; self.xyz_final = None; self.faces = None
        self.face_normals = None; self.vertex_normals = None
        self.shade = None; self.vertex_shade = None; self.unique_indices = None
        self.offset = None; self.spacing = 0.0; self.max_edge_factor = 3.0
        self.last_azimuth = -1; self.last_angle = -1; self.last_ambient = -1
        self.visible_classes_hash = None; self.n_visible_classes = 0
        self.single_class_id = None; self.visible_classes_set = None
        self.data_hash = None; self._vtk_colors_ptr = None
        self._hidden_face_mask = None; self._global_to_unique = None
        self._cached_face_class = None; self._tri_lod_factor = 1.0
    def clear(self, reason=""):
        if reason: print(f"   🗑️ Cache cleared: {reason}")
        self._clear_internal()
    def get_visible_hash(self, vc): return hash(frozenset(vc))
    def is_valid(self, xyz, vc):
        if self.xyz_unique is None or self.faces is None: return False
        if self.get_visible_hash(vc) != self.visible_classes_hash: return False
        try: return hash((len(xyz), float(xyz[0,0]), float(xyz[-1,2]))) == self.data_hash
        except: return False
    def is_fully_current(self, xyz, vc, az, an, am, app):
        if not self.is_geometry_valid(xyz, vc): return False
        if self.needs_shading_update(az, an, am): return False
        return getattr(app, '_shaded_mesh_actor', None) is not None
    def is_geometry_valid(self, xyz, vc):
        if self.xyz_unique is None or self.faces is None or len(self.faces) == 0: return False
        if self.get_visible_hash(vc) != self.visible_classes_hash: return False
        try: return hash((len(xyz), float(xyz[0,0]), float(xyz[-1,2]))) == self.data_hash
        except: return False
    def is_cached_subset_of(self, nvc, xyz):
        if self.visible_classes_set is None or self.xyz_unique is None or self.faces is None or len(self.faces) == 0 or self.data_hash is None: return False
        if not self.visible_classes_set.issubset(nvc): return False
        try: return hash((len(xyz), float(xyz[0,0]), float(xyz[-1,2]))) == self.data_hash
        except: return False
    def needs_shading_update(self, az, an, am):
        return abs(self.last_azimuth-az) > .001 or abs(self.last_angle-an) > .001 or abs(self.last_ambient-am) > .001
    def get_gpu_color_pointer(self, app):
        if self._vtk_colors_ptr is not None: return self._vtk_colors_ptr
        m = getattr(app, '_shaded_mesh_polydata', None)
        if m is None: return None
        try:
            vc = m.GetPointData().GetScalars()
            if vc is None: vc = m.GetCellData().GetScalars()
            if vc: self._vtk_colors_ptr = numpy_support.vtk_to_numpy(vc); return self._vtk_colors_ptr
        except: pass
        return None
    def build_global_to_unique(self, total):
        if self._global_to_unique is not None and len(self._global_to_unique) == total: return self._global_to_unique
        self._global_to_unique = np.full(total, -1, dtype=np.int32)
        if self.unique_indices is not None:
            self._global_to_unique[self.unique_indices] = np.arange(len(self.unique_indices))
        return self._global_to_unique

_cache = None
def get_cache():
    global _cache
    if _cache is None: _cache = ShadingGeometryCache()
    return _cache
def clear_shading_cache(reason=""): get_cache().clear(reason)
def invalidate_cache_for_new_file(fp=""): get_cache().clear("new file")

def _get_shading_visibility(app):
    so = getattr(app, '_shading_visibility_override', None)
    if so is not None:
        print(f"   📍 Shading visibility from SHORTCUT OVERRIDE: {sorted(so)}"); return so
    d = getattr(app, 'display_mode_dialog', None) or getattr(app, 'display_dialog', None)
    if d:
        vp = getattr(d, 'view_palettes', None)
        if vp and 0 in vp:
            vc = {int(c) for c, e in vp[0].items() if e.get("show", True)}
            if vc: print(f"   📍 Shading visibility from Display Mode (Slot 0): {sorted(vc)}"); return vc
    vc = {int(c) for c, e in app.class_palette.items() if e.get("show", True)}
    if vc: print(f"   📍 Shading visibility from class_palette: {sorted(vc)}")
    return vc

def _save_camera(app):
    try:
        c = app.vtk_widget.renderer.GetActiveCamera()
        return {'pos': c.GetPosition(), 'fp': c.GetFocalPoint(), 'up': c.GetViewUp(),
                'parallel': c.GetParallelProjection(), 'scale': c.GetParallelScale()}
    except: return None

def _restore_camera(app, c):
    if c:
        try:
            cam = app.vtk_widget.renderer.GetActiveCamera()
            cam.SetPosition(c['pos']); cam.SetFocalPoint(c['fp']); cam.SetViewUp(c['up'])
            cam.SetParallelProjection(c['parallel']); cam.SetParallelScale(c['scale'])
        except: pass

def _queue_deferred_rebuild(app, reason="", newly_visible_indices=None):
    global _rebuild_timer, _rebuild_reason, _rebuild_changed_indices
    _rebuild_reason = reason; _rebuild_changed_indices = newly_visible_indices
    if _rebuild_timer is not None:
        try: _rebuild_timer.stop(); _rebuild_timer.deleteLater()
        except: pass
        _rebuild_timer = None
    def do_rebuild():
        global _rebuild_timer, _rebuild_changed_indices
        _rebuild_timer = None; di = _rebuild_changed_indices; _rebuild_changed_indices = None
        if getattr(app, 'is_dragging', False) or (hasattr(app, 'interactor') and getattr(app.interactor, 'is_dragging', False)):
            _queue_deferred_rebuild(app, _rebuild_reason, di); return
        cache = get_cache(); vc = _get_shading_visibility(app)
        cls = app.data.get("classification").astype(np.int32); xyz = app.data.get("xyz")
        cm = cls[cache.unique_indices]; va = np.array(sorted(vc), dtype=np.int32)
        nh = ~np.isin(cm, va)
        if np.any(nh):
            if not _incremental_visibility_patch(app, cache.unique_indices[nh], vc):
                clear_shading_cache("patch failed"); update_shaded_class(app, force_rebuild=True)
            return
        if di is not None and len(di) > 0:
            g2u = cache.build_global_to_unique(len(xyz))
            sv = np.isin(cls[di], va); vod = di[sv]
            mg = vod[g2u[vod] < 0] if len(vod) > 0 else np.array([], dtype=np.intp)
            if len(mg) > 0:
                if not _fast_incremental_add_points(app, mg):
                    cm2 = np.zeros(len(xyz), dtype=bool); cm2[mg] = True
                    if not _multi_class_region_undo_patch(app, cm2, vc):
                        clear_shading_cache("region failed"); update_shaded_class(app, force_rebuild=True)
    dl = 150 if (newly_visible_indices is not None and len(newly_visible_indices) > 0) else 1000
    _rebuild_timer = QTimer(); _rebuild_timer.setSingleShot(True)
    _rebuild_timer.timeout.connect(do_rebuild); _rebuild_timer.start(dl)

def _queue_incremental_patch(app, sci):
    global _rebuild_timer, _rebuild_reason
    _rebuild_reason = "single-class patch"
    if _rebuild_timer is not None:
        try: _rebuild_timer.stop(); _rebuild_timer.deleteLater()
        except: pass
        _rebuild_timer = None
    def do_patch():
        global _rebuild_timer
        _rebuild_timer = None
        if getattr(app, 'is_dragging', False) or (hasattr(app, 'interactor') and getattr(app.interactor, 'is_dragging', False)):
            _queue_incremental_patch(app, sci); return
        _rebuild_single_class(app, sci)
    _rebuild_timer = QTimer(); _rebuild_timer.setSingleShot(True)
    _rebuild_timer.timeout.connect(do_patch); _rebuild_timer.start(1000)

def update_shaded_class(app, azimuth=45., angle=45., ambient=0.25,
                        max_edge_factor=3.0, force_rebuild=False,
                        single_class_max_edge=None, **kwargs):
    cache = get_cache()
    xyz_raw = app.data.get("xyz"); classes_raw = app.data.get("classification")
    if xyz_raw is None or classes_raw is None: return
    azimuth = getattr(app, 'last_shade_azimuth', azimuth)
    angle = getattr(app, 'last_shade_angle', angle)
    ambient = getattr(app, 'shade_ambient', ambient)
    vc = _get_shading_visibility(app)
    if cache.is_fully_current(xyz_raw, vc, azimuth, angle, ambient, app): return
    if not force_rebuild and cache.is_geometry_valid(xyz_raw, vc):
        _refresh_from_cache(app, cache, azimuth, angle, ambient); return
    if not force_rebuild and cache.is_cached_subset_of(vc, xyz_raw):
        try:
            ec = vc - cache.visible_classes_set
            ei = np.where(np.isin(classes_raw.astype(np.int32), list(ec)))[0]
            if len(ei) > 0 and _fast_incremental_add_points(app, ei):
                cache.visible_classes_hash = cache.get_visible_hash(vc)
                cache.visible_classes_set = vc.copy(); cache.n_visible_classes = len(vc)
                cache.single_class_id = list(vc)[0] if len(vc) == 1 else None
                app.last_shade_azimuth = azimuth; app.last_shade_angle = angle; app.shade_ambient = ambient
                return
        except: pass
    for c in app.class_palette: app.class_palette[c]["show"] = (int(c) in vc)
    app._shading_visible_classes = vc.copy() if vc else set()
    if not vc:
        if hasattr(app, '_shaded_mesh_actor'): app.vtk_widget.remove_actor("shaded_mesh"); app._shaded_mesh_actor = None
        _remove_shaded_edge_overlay(app); app.vtk_widget.render(); return
    if cache.is_valid(xyz_raw, vc) and not force_rebuild:
        _refresh_from_cache(app, cache, azimuth, angle, ambient)
    else:
        _build_visible_geometry(app, xyz_raw, classes_raw, azimuth, angle, ambient, max_edge_factor, cache, vc, single_class_max_edge)


def _grid_dedup_at_precision(xyz, precision):
    """Grid dedup at given precision. Returns local indices of unique points."""
    xy_grid = np.floor(xyz[:, :2] / precision).astype(np.int64)
    gx = xy_grid[:, 0] - xy_grid[:, 0].min()
    gy = xy_grid[:, 1] - xy_grid[:, 1].min()
    gy_span = int(gy.max()) + 1
    if gx.max() < 2**30 and gy_span < 2**30:
        grid_key = gx * gy_span + gy
        sort_idx = np.lexsort((-xyz[:, 2], grid_key))
        sorted_keys = grid_key[sort_idx]
        unique_mask = np.empty(len(sorted_keys), dtype=bool)
        unique_mask[0] = True
        unique_mask[1:] = np.diff(sorted_keys) != 0
    else:
        sort_idx = np.lexsort((-xyz[:, 2], xy_grid[:, 1], xy_grid[:, 0]))
        xy_sorted = xy_grid[sort_idx]
        d = np.diff(xy_sorted, axis=0)
        unique_mask = np.concatenate([[True], (d[:, 0] != 0) | (d[:, 1] != 0)])
    return sort_idx[unique_mask]


def _build_visible_geometry(app, xyz_raw, classes_raw, azimuth, angle,
                            ambient, max_edge_factor, cache, visible_classes,
                            single_class_max_edge=None):
    nv = len(visible_classes); is_sc = (nv == 1)
    print(f"\n{'='*60}")
    print(f"🔺 {'SINGLE-CLASS' if is_sc else 'MULTI-CLASS'} SHADING (MicroStation mode)")
    print(f"{'='*60}")
    t_total = time.time()
    app.last_shade_azimuth = azimuth; app.last_shade_angle = angle
    app.shade_ambient = ambient; app.display_mode = "shaded_class"
    saved_camera = _save_camera(app)
    progress = QProgressDialog("Building surface...", None, 0, 100, app)
    progress.setWindowModality(Qt.WindowModal); progress.setMinimumDuration(0)
    progress.show(); QApplication.processEvents()
    try:
        # ── PHASE 1: Visibility ──
        progress.setValue(5); QApplication.processEvents()
        t1 = time.time()
        classes = classes_raw.astype(np.int16)
        mc = int(np.max(classes)) + 1 if len(classes) > 0 else 256
        vl = np.zeros(mc, dtype=bool)
        for v in visible_classes:
            if v < mc: vl[v] = True
        vm = vl[classes]; vi = np.where(vm)[0]
        if len(vi) < 3:
            if hasattr(app, '_shaded_mesh_actor') and app._shaded_mesh_actor:
                try: app.vtk_widget.remove_actor("shaded_mesh", render=False)
                except: pass
                app._shaded_mesh_actor = None
            if hasattr(app, '_shaded_mesh_polydata'): app._shaded_mesh_polydata = None
            _remove_shaded_edge_overlay(app)
            cache.n_visible_classes = nv; cache.visible_classes_set = visible_classes.copy()
            cache.single_class_id = list(visible_classes)[0] if is_sc else None
            _restore_camera(app, saved_camera); app.vtk_widget.render(); progress.close(); return
        xv = xyz_raw[vi]
        print(f"   📍 {len(vi):,} visible points [{(time.time()-t1)*1000:.0f}ms]")

        # ── PHASE 2: Guaranteed-fast dedup ──
        progress.setValue(10); QApplication.processEvents()
        t2 = time.time()
        offset = xv.min(axis=0)
        xyz = (xv - offset).astype(np.float64)
        xr = xyz[:,0].max() - xyz[:,0].min()
        yr = xyz[:,1].max() - xyz[:,1].min()
        area = max(xr * yr, 1.0)
        n_pts = len(xyz)
        natural_spacing = np.sqrt(area / n_pts)

        # Target: max 3.5M unique points for <5s Delaunay
        TARGET_MAX = 3_500_000
        
        # Start with finest precision
        precision = max(natural_spacing * 0.3, 0.005)
        
        # First pass dedup
        unique_local = _grid_dedup_at_precision(xyz, precision)
        n_unique = len(unique_local)
        lod_factor = 1.0
        
        print(f"   📐 Pass 1: precision={precision:.4f}m → {n_unique:,} unique")
        
        # If too many, coarsen and re-dedup (fast — just sorting)
        if n_unique > TARGET_MAX:
            # Calculate exact factor needed
            lod_factor = np.sqrt(n_unique / TARGET_MAX)
            lod_factor = min(max(lod_factor, 1.0), 5.0)
            precision2 = precision * lod_factor
            
            unique_local = _grid_dedup_at_precision(xyz, precision2)
            n_unique = len(unique_local)
            precision = precision2
            
            print(f"   📐 Pass 2: precision={precision:.4f}m, LOD={lod_factor:.2f}x → {n_unique:,} unique")
            
            # Safety: if STILL too many, force harder
            if n_unique > TARGET_MAX * 1.3:
                lod_factor2 = np.sqrt(n_unique / TARGET_MAX)
                precision3 = precision * lod_factor2
                unique_local = _grid_dedup_at_precision(xyz, precision3)
                n_unique = len(unique_local)
                lod_factor *= lod_factor2
                precision = precision3
                print(f"   📐 Pass 3: precision={precision:.4f}m, LOD={lod_factor:.2f}x → {n_unique:,} unique")

        xyz_unique = xyz[unique_local]
        unique_indices_global = vi[unique_local]
        
        xr2 = xyz_unique[:,0].max() - xyz_unique[:,0].min()
        yr2 = xyz_unique[:,1].max() - xyz_unique[:,1].min()
        data_extent = max(xr2, yr2)
        spacing = np.sqrt((xr2 * yr2) / max(len(xyz_unique), 1))
        
        cache.offset = offset; cache.unique_indices = unique_indices_global
        cache.xyz_unique = xyz_unique; cache.xyz_final = xyz_unique + offset
        cache.spacing = spacing; cache.max_edge_factor = max_edge_factor
        cache.visible_classes_hash = cache.get_visible_hash(visible_classes)
        cache.n_visible_classes = nv; cache.visible_classes_set = visible_classes.copy()
        cache.single_class_id = list(visible_classes)[0] if is_sc else None
        cache._vtk_colors_ptr = None; cache._global_to_unique = None
        cache._cached_face_class = None; cache._tri_lod_factor = lod_factor
        
        p2ms = (time.time()-t2)*1000
        print(f"   ✅ {n_unique:,} unique points ({100*n_unique/n_pts:.1f}%) [{p2ms:.0f}ms]")

        # ── PHASE 3: Triangulation ──
        progress.setValue(25); QApplication.processEvents()
        t3 = time.time()
        xy = xyz_unique[:, :2]
        
        # With guaranteed ≤3.5M points, single Delaunay is fastest
        print(f"   🔺 Direct Delaunay on {n_unique:,} points...")
        t_del = time.time()
        faces = _do_triangulate(xy)
        del_ms = (time.time()-t_del)*1000
        print(f"   ✅ Delaunay: {len(faces):,} raw faces [{del_ms:.0f}ms]")

        # Post-filter
        if len(faces) > 0:
            if HAS_NUMBA:
                ma = (spacing * 0.1) ** 2
                keep = _numba_degenerate_filter(faces, xy, ma, 0.001)
                nr = int(np.sum(~keep))
                if nr > 0: faces = faces[keep]; print(f"   ✂️ Removed {nr:,} degenerate")
            else:
                p0 = xy[faces[:,0]]; p1 = xy[faces[:,1]]; p2 = xy[faces[:,2]]
                cz = ((p1[:,0]-p0[:,0])*(p2[:,1]-p0[:,1]) - (p1[:,1]-p0[:,1])*(p2[:,0]-p0[:,0]))
                ta = np.abs(cz)*0.5
                e0 = ((p1-p0)**2).sum(1); e1 = ((p2-p1)**2).sum(1); e2 = ((p0-p2)**2).sum(1)
                me = np.maximum(np.maximum(e0,e1),e2)
                ma2 = (spacing*0.1)**2
                nd = (ta > ma2) & (ta/np.maximum(me, 1e-10) > 0.001)
                nr = int(np.sum(~nd))
                if nr > 0: faces = faces[nd]; print(f"   ✂️ Removed {nr:,} degenerate")

        if is_sc:
            me = single_class_max_edge if single_class_max_edge else data_extent * 0.2
            faces = _filter_edges_by_absolute(faces, xy, me)
        else:
            mea = data_extent * 0.10
            faces = _filter_edges_3d_abs(faces, xyz_unique, mea)
            cache.max_edge_factor = mea / max(spacing, 1e-9)
        cache.faces = faces
        p3ms = (time.time()-t3)*1000
        print(f"   ✅ {len(faces):,} triangles [{p3ms:.0f}ms]")

        # ── PHASE 4: Normals + Shading ──
        progress.setValue(70); QApplication.processEvents()
        t4 = time.time()
        if len(faces) > 0:
            cache.face_normals = _compute_face_normals(xyz_unique, faces)
            if is_sc:
                cache.shade = _compute_face_shade(xyz_unique, faces, azimuth, angle, ambient, face_normals=cache.face_normals)
                cache.vertex_normals = None; cache.vertex_shade = None
            else:
                cache.vertex_normals = _compute_vertex_normals(xyz_unique, faces, cache.face_normals)
                cache.vertex_shade = _compute_shading(cache.vertex_normals, azimuth, angle, ambient, z_values=xyz_unique[:,2])
                cache.shade = _compute_face_shade(xyz_unique, faces, azimuth, angle, ambient)
        else:
            cache.face_normals = np.array([]).reshape(0,3)
            cache.vertex_normals = np.array([]).reshape(0,3)
            cache.shade = np.array([]); cache.vertex_shade = np.array([])
        cache.last_azimuth = azimuth; cache.last_angle = angle; cache.last_ambient = ambient
        cache.data_hash = hash((len(xyz_raw), float(xyz_raw[0,0]), float(xyz_raw[-1,2])))
        p4ms = (time.time()-t4)*1000
        print(f"   ✅ Normals + shading [{p4ms:.0f}ms]")

        # ── PHASE 5: Render ──
        progress.setValue(90); QApplication.processEvents()
        _render_mesh(app, cache, classes_raw, saved_camera)
        progress.setValue(100)
        print(f"   ✅ COMPLETE: {time.time()-t_total:.1f}s")
        print(f"{'='*60}\n")
    except Exception as e:
        print(f"   ❌ Error: {e}"); import traceback; traceback.print_exc()
    finally:
        progress.close()


def _refresh_from_cache(app, cache, azimuth, angle, ambient):
    app.last_shade_azimuth = azimuth; app.last_shade_angle = angle
    app.shade_ambient = ambient; app.display_mode = "shaded_class"
    sc = _save_camera(app)
    if cache.needs_shading_update(azimuth, angle, ambient):
        isc = getattr(cache, 'n_visible_classes', 0) == 1
        zv = cache.xyz_unique[:,2] if cache.xyz_unique is not None else None
        if isc:
            if cache.face_normals is not None and len(cache.face_normals) > 0:
                cache.shade = _compute_face_shade(cache.xyz_unique, cache.faces, azimuth, angle, ambient, face_normals=cache.face_normals)
        else:
            if cache.vertex_normals is not None and len(cache.vertex_normals) > 0:
                cache.vertex_shade = _compute_shading(cache.vertex_normals, azimuth, angle, ambient, z_values=zv)
            cache.shade = _compute_face_shade(cache.xyz_unique, cache.faces, azimuth, angle, ambient, face_normals=cache.face_normals)
        cache.last_azimuth = azimuth; cache.last_angle = angle; cache.last_ambient = ambient
        cache._vtk_colors_ptr = None
    _render_mesh(app, cache, app.data.get("classification"), sc)


def _render_mesh(app, cache, classes_raw, saved_camera):
    if cache.faces is None or len(cache.faces) == 0: return
    t0 = time.time()
    classes = classes_raw.astype(np.int32); cm = classes[cache.unique_indices]
    vc = _get_shading_visibility(app); nv = len(cache.xyz_final); nf = len(cache.faces)
    az = getattr(app, 'last_shade_azimuth', 45.); an = getattr(app, 'last_shade_angle', 45.)
    isc = getattr(cache, 'n_visible_classes', 0) == 1
    mc = max(int(cm.max())+1, 256)
    lut = np.zeros((mc, 3), dtype=np.float32)
    for c, e in app.class_palette.items():
        ci = int(c)
        if ci < mc and ci in vc: lut[ci] = e.get("color", (128,128,128))
    vcl = np.clip(cm, 0, mc-1); vbc = lut[vcl]

    if isc:
        amb = getattr(app, 'shade_ambient', 0.25)
        if cache.shade is None or len(cache.shade) != nf:
            cache.shade = _compute_face_shade(cache.xyz_unique, cache.faces, az, an, amb, face_normals=cache.face_normals)
        fi = cache.shade; fvc = np.clip(cm[cache.faces[:,0]], 0, mc-1)
        fbc = lut[fvc]; fc = np.clip(fbc * fi[:, None], 0, 255).astype(np.uint8)
        em = getattr(app, '_shaded_mesh_polydata', None); ea = getattr(app, '_shaded_mesh_actor', None)
        if em is not None and ea is not None and em.GetNumberOfPoints() == nv and em.GetNumberOfCells() == nf:
            try:
                vtc = em.GetCellData().GetScalars()
                if vtc is not None:
                    numpy_support.vtk_to_numpy(vtc)[:] = fc; vtc.Modified(); em.Modified(); ea.GetMapper().Modified()
                    _restore_camera(app, saved_camera); app.vtk_widget.render(); return
            except: pass
            cache._vtk_colors_ptr = None
        fv = np.empty(nf*4, dtype=np.int32); fv[0::4] = 3
        fv[1::4] = cache.faces[:,0]; fv[2::4] = cache.faces[:,1]; fv[3::4] = cache.faces[:,2]
        mesh = pv.PolyData(cache.xyz_final, fv); mesh.cell_data["RGB"] = fc
    else:
        if cache.vertex_shade is not None and len(cache.vertex_shade) == nv:
            vco = np.clip(vbc * cache.vertex_shade[:, None], 0, 255).astype(np.uint8)
        else: vco = vbc.astype(np.uint8)
        em = getattr(app, '_shaded_mesh_polydata', None); ea = getattr(app, '_shaded_mesh_actor', None)
        sc2 = cache._vtk_colors_ptr is None
        if not sc2 and em is not None and ea is not None and em.GetNumberOfPoints() == nv and em.GetNumberOfCells() == nf:
            try:
                vtc = em.GetPointData().GetScalars()
                if vtc is not None:
                    numpy_support.vtk_to_numpy(vtc)[:] = vco; vtc.Modified(); em.Modified(); ea.GetMapper().Modified()
                    _restore_camera(app, saved_camera); app.vtk_widget.render(); return
            except: pass
            cache._vtk_colors_ptr = None
        fv = np.empty(nf*4, dtype=np.int32); fv[0::4] = 3
        fv[1::4] = cache.faces[:,0]; fv[2::4] = cache.faces[:,1]; fv[3::4] = cache.faces[:,2]
        mesh = pv.PolyData(cache.xyz_final, fv); mesh.point_data["RGB"] = vco
        if cache.vertex_normals is not None and len(cache.vertex_normals) == nv:
            vn = numpy_support.numpy_to_vtk(cache.vertex_normals.astype(np.float32), deep=True)
            vn.SetName("Normals"); mesh.GetPointData().SetNormals(vn)

    plotter = app.vtk_widget; DXF = ("dxf_", "snt_", "grid_", "guideline", "snap_", "axis")
    def _prot(ns, a):
        if any(ns.lower().startswith(p) for p in DXF): return True
        return getattr(a, '_is_dxf_actor', False)
    protected = {}
    for name in list(plotter.actors.keys()):
        try:
            a = plotter.actors[name]
            if _prot(name, a): protected[name] = (a, bool(a.GetVisibility()))
        except: pass
    for name in list(plotter.actors.keys()):
        if name in protected: continue
        ns = str(name).lower()
        if ns.startswith("class_") or ns in ("main_pc", "main_pc_border", "_naksha_unified_cloud"):
            plotter.actors[name].SetVisibility(False)
        elif any(ns.startswith(p) for p in ["border_", "shaded_mesh", "__lod_overlay_"]):
            plotter.remove_actor(name, render=False)

    if isc:
        app._shaded_mesh_actor = plotter.add_mesh(mesh, scalars="RGB", rgb=True, show_edges=False,
            lighting=False, smooth_shading=False, preference="cell", name="shaded_mesh", render=False)
        if app._shaded_mesh_actor:
            p2 = app._shaded_mesh_actor.GetProperty()
            p2.SetInterpolationToFlat(); p2.SetAmbient(1.); p2.SetDiffuse(0.); p2.SetSpecular(0.); p2.EdgeVisibilityOff()
    else:
        app._shaded_mesh_actor = plotter.add_mesh(mesh, scalars="RGB", rgb=True, show_edges=False,
            lighting=True, smooth_shading=True, preference="point", name="shaded_mesh", render=False)
        if app._shaded_mesh_actor:
            p2 = app._shaded_mesh_actor.GetProperty()
            p2.SetAmbient(0.12); p2.SetDiffuse(0.88); p2.SetSpecular(0.18); p2.SetSpecularPower(48.)
            p2.SetInterpolationToFlat(); p2.EdgeVisibilityOff()
        _setup_microstation_lighting(plotter.renderer, az, an)
    app._shaded_mesh_polydata = mesh; cache._vtk_colors_ptr = None

    renderer = plotter.renderer; nr = 0
    for name, (a, wv) in protected.items():
        try:
            if wv: a.SetVisibility(True)
            if not renderer.HasViewProp(a): renderer.AddActor(a); nr += 1
        except: pass
    for sn in ("dxf_actors", "snt_actors"):
        for entry in getattr(app, sn, []):
            for a in entry.get("actors", []):
                try:
                    if not renderer.HasViewProp(a): renderer.AddActor(a); nr += 1
                    a.SetVisibility(True)
                except: pass
    if nr > 0: print(f"   ✅ Restored {nr} DXF/SNT actors")
    _restore_camera(app, saved_camera); plotter.set_background("black")
    plotter.renderer.ResetCameraClippingRange()
    try:
        m = app._shaded_mesh_actor.GetMapper()
        if m: m.StaticOn(); m.SetResolveCoincidentTopologyToPolygonOffset(); m.InterpolateScalarsBeforeMappingOff()
    except: pass
    plotter.render()
    ms = "FLAT/FACETED (single-class)" if isc else "FLAT (multi-class)"
    print(f"   🎨 Shaded Mesh [{ms}]: {nf:,} faces in {(time.time()-t0)*1000:.0f}ms")


# ═══════════════════════════════════════════════════════════════
# ALL REMAINING FUNCTIONS — identical behavior, compressed
# ═══════════════════════════════════════════════════════════════

def refresh_shaded_after_classification_fast(app, changed_mask=None):
    cache = get_cache()
    if cache.faces is None or len(cache.faces) == 0:
        update_shaded_class(app, force_rebuild=True); return True
    if hasattr(app, 'vtk_widget'):
        for name in list(app.vtk_widget.actors.keys()):
            ns = str(name).lower()
            if ns.startswith("class_") or ns in ("main_pc", "main_pc_border"):
                app.vtk_widget.actors[name].SetVisibility(False)
    isc = getattr(cache, 'n_visible_classes', 0) == 1; sci = getattr(cache, 'single_class_id', None)
    vc = _get_shading_visibility(app); va = np.array(sorted(vc), dtype=np.int32)
    if changed_mask is None or not np.any(changed_mask):
        if not isc or sci is None: return _update_colors_gpu_fast(app, cache, changed_mask=None, _visible_classes=vc)
        return True
    cls = app.data.get("classification").astype(np.int32); ci = np.where(changed_mask)[0]
    cc = cls[ci]; nh = ~np.isin(cc, va); nvis = np.isin(cc, va)
    g2u = cache.build_global_to_unique(len(app.data["xyz"]))
    if isc and sci is not None:
        mesh = getattr(app, '_shaded_mesh_polydata', None)
        if np.all(nh):
            if mesh:
                cellc = mesh.GetCellData().GetScalars()
                if cellc and cache.faces is not None and cellc.GetNumberOfTuples() == len(cache.faces):
                    try:
                        vp = numpy_support.vtk_to_numpy(cellc); cu = g2u[ci]; cu = cu[cu >= 0]
                        if len(cu) > 0:
                            cs = np.zeros(len(cache.unique_indices), dtype=bool); cs[cu] = True
                            af = cs[cache.faces[:,0]] | cs[cache.faces[:,1]] | cs[cache.faces[:,2]]
                            vp[af] = [0,0,0]; cellc.Modified(); mesh.Modified()
                            a = getattr(app, '_shaded_mesh_actor', None)
                            if a: a.GetMapper().Modified()
                            app.vtk_widget.render()
                    except: pass
            _queue_incremental_patch(app, sci); return True
        if np.all(nvis):
            nvg = ci[nvis]; mg = nvg[g2u[nvg] < 0]
            if len(mg) == 0: return True
            if _fast_incremental_add_points(app, mg): return True
            _queue_deferred_rebuild(app, "single new vis", newly_visible_indices=mg); return True
        if mesh:
            cellc = mesh.GetCellData().GetScalars()
            if cellc and cache.faces is not None and cellc.GetNumberOfTuples() == len(cache.faces):
                try:
                    vp = numpy_support.vtk_to_numpy(cellc); hg = ci[nh]; hu = g2u[hg]; hu = hu[hu >= 0]
                    if len(hu) > 0:
                        cs = np.zeros(len(cache.unique_indices), dtype=bool); cs[hu] = True
                        af = cs[cache.faces[:,0]] | cs[cache.faces[:,1]] | cs[cache.faces[:,2]]
                        vp[af] = [0,0,0]; cellc.Modified(); mesh.Modified()
                        a = getattr(app, '_shaded_mesh_actor', None)
                        if a: a.GetMapper().Modified()
                        app.vtk_widget.render()
                except: pass
        _queue_incremental_patch(app, sci); return True
    if np.all(nvis):
        if _check_previous_classes_visible(app, ci, va):
            if _update_colors_gpu_fast(app, cache, changed_mask=changed_mask, _visible_classes=vc, _defer_render=True): return True
        nvg = ci[nvis]; mg = nvg[g2u[nvg] < 0]
        if len(mg) > 0:
            if _fast_incremental_add_points(app, mg): return True
            _queue_deferred_rebuild(app, "cls new vis", newly_visible_indices=mg)
            _update_colors_gpu_fast(app, cache, changed_mask=changed_mask, _visible_classes=vc, _defer_render=True); return True
        if _update_colors_gpu_fast(app, cache, changed_mask=changed_mask, _visible_classes=vc, _defer_render=True): return True
    voided = None
    if np.any(nvis):
        nvg = ci[nvis]; nim = int(np.sum(g2u[nvg] < 0))
        if nim > 0:
            pwh = True
            if getattr(app, '_shading_visibility_override', None) is None:
                for sa in ('undo_stack', 'undostack'):
                    stk = getattr(app, sa, None)
                    if stk:
                        try:
                            old = (stk[-1].get('old_classes') or stk[-1].get('oldclasses'))
                            if old is not None: pwh = not set(int(x) for x in np.unique(np.asarray(old))).issubset(set(int(c) for c in vc))
                        except: pass
                        break
            if pwh: _queue_deferred_rebuild(app, "cls new vis", newly_visible_indices=nvg[g2u[nvg] < 0])
    if np.any(nh):
        voided = ci[nh]; mesh = getattr(app, '_shaded_mesh_polydata', None)
        if mesh:
            pc = mesh.GetPointData().GetScalars()
            if pc and pc.GetNumberOfTuples() == len(cache.unique_indices):
                hu = g2u[voided]; hu = hu[(hu >= 0) & (hu < len(cache.unique_indices))]
                if len(hu) > 0: numpy_support.vtk_to_numpy(pc)[hu] = [0,0,0]; pc.Modified()
    if _update_colors_gpu_fast(app, cache, changed_mask, _visible_classes=vc, _defer_render=True):
        if voided is not None and len(voided) > 0: _queue_deferred_rebuild(app, "void cleanup")
        return True
    update_shaded_class(app, force_rebuild=True); return True

def _incremental_visibility_patch(app, cgi, vcs):
    cache = get_cache()
    if cache.faces is None or cache.xyz_unique is None or cache.xyz_final is None: return False
    xr = app.data.get("xyz"); cr = app.data.get("classification")
    if xr is None or cr is None: return False
    cls = cr.astype(np.int32); cm = cls[cache.unique_indices]
    va = np.array(sorted(vcs), dtype=np.int32); viv = np.isin(cm, va)
    g2u = cache.build_global_to_unique(len(xr)); cim = g2u[cgi]; cim = cim[cim >= 0]
    if len(cim) > 0 and np.all(viv[cim]):
        fwc = np.isin(cache.faces[:,0], cim) | np.isin(cache.faces[:,1], cim) | np.isin(cache.faces[:,2], cim)
        if np.sum(fwc) > 0:
            km = ~fwc; cache.faces = cache.faces[km]; cache.shade = cache.shade[km]
            cache.face_normals = cache.face_normals[km] if cache.face_normals is not None else None
            if cache.face_normals is not None and len(cache.face_normals) > 0:
                cache.vertex_normals = _compute_vertex_normals(cache.xyz_unique, cache.faces, cache.face_normals)
                cache.vertex_shade = _compute_shading(cache.vertex_normals, getattr(app, 'last_shade_azimuth', 45.), getattr(app, 'last_shade_angle', 45.), getattr(app, 'shade_ambient', .25))
            cache._vtk_colors_ptr = None; _render_mesh(app, cache, cr, _save_camera(app)); return True
    vnh = ~viv
    if np.sum(vnh) == 0: return True
    ifm = vnh[cache.faces[:,0]] | vnh[cache.faces[:,1]] | vnh[cache.faces[:,2]]; vfm = ~ifm
    if np.sum(vfm) == 0: return False
    vf = cache.faces[vfm]; vs = cache.shade[vfm]; vn = cache.face_normals[vfm] if cache.face_normals is not None else None
    hvi = np.where(vnh)[0]; ifa = cache.faces[ifm]
    ihf = np.zeros(len(cache.unique_indices), dtype=bool)
    if len(hvi) > 0: ihf[hvi] = True
    avi = ifa.ravel(); bv = np.unique(avi[~ihf[avi]]).astype(np.int32)
    if len(bv) < 3:
        cache.faces = vf; cache.shade = vs; cache.face_normals = vn
        if vn is not None and len(vn) > 0:
            cache.vertex_normals = _compute_vertex_normals(cache.xyz_unique, vf, vn)
            cache.vertex_shade = _compute_shading(cache.vertex_normals, getattr(app, 'last_shade_azimuth', 45.), getattr(app, 'last_shade_angle', 45.), getattr(app, 'shade_ambient', .25))
        cache._vtk_colors_ptr = None; _render_mesh(app, cache, cr, _save_camera(app)); return True
    bxy = cache.xyz_unique[bv, :2]
    try: lf = _do_triangulate(bxy)
    except:
        cache.faces = vf; cache.shade = vs; cache.face_normals = vn; cache._vtk_colors_ptr = None
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    if len(lf) == 0:
        cache.faces = vf; cache.shade = vs; cache.face_normals = vn; cache._vtk_colors_ptr = None
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    be = max(bxy[:,0].max()-bxy[:,0].min(), bxy[:,1].max()-bxy[:,1].min())
    lf = _filter_edges_by_absolute(lf, bxy, max(be*0.5, cache.spacing*cache.max_edge_factor))
    if len(lf) == 0:
        cache.faces = vf; cache.shade = vs; cache.face_normals = vn; cache._vtk_colors_ptr = None
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    pf = bv[lf]; pn = _compute_face_normals(cache.xyz_unique, pf)
    ps = _compute_face_shade(cache.xyz_unique, pf, getattr(app, 'last_shade_azimuth', 45.), getattr(app, 'last_shade_angle', 45.), getattr(app, 'shade_ambient', .25), face_normals=pn)
    cache.faces = np.vstack([vf, pf]); cache.shade = np.concatenate([vs, ps])
    cache.face_normals = pn if vn is None else np.vstack([vn, pn])
    _recompute_vertex_normals_partial(cache, len(vf)); cache._vtk_colors_ptr = None
    _render_mesh(app, cache, cr, _save_camera(app)); return True

def refresh_shaded_after_visibility_change(app, cgi, vcs):
    cache = get_cache()
    if cache.faces is None or cache.xyz_unique is None:
        clear_shading_cache("no cache"); update_shaded_class(app, force_rebuild=True); return
    if not _incremental_visibility_patch(app, cgi, vcs):
        clear_shading_cache("patch failed"); update_shaded_class(app, force_rebuild=True)

def _multi_class_region_undo_patch(app, changed_mask, vcs):
    cache = get_cache()
    if cache.faces is None or cache.xyz_unique is None: return False
    xyz = app.data.get("xyz"); cr = app.data.get("classification")
    if xyz is None or cr is None: return False
    cls = cr.astype(np.int32); va = np.array(sorted(vcs), dtype=np.int32)
    ci = np.where(changed_mask)[0]; cx = xyz[ci]
    xn, yn = cx[:,0].min(), cx[:,1].min(); xx, yx = cx[:,0].max(), cx[:,1].max()
    mg = max(cache.spacing*5, 1.) if cache.spacing > 0 else 10.
    xn -= mg; yn -= mg; xx += mg; yx += mg
    cf = cache.xyz_final
    irm = (cf[:,0] >= xn) & (cf[:,0] <= xx) & (cf[:,1] >= yn) & (cf[:,1] <= yx)
    fir = irm[cache.faces[:,0]] & irm[cache.faces[:,1]] & irm[cache.faces[:,2]]
    fo = cache.faces[~fir]; so = cache.shade[~fir]; no = cache.face_normals[~fir] if cache.face_normals is not None else None
    nk = len(fo)
    vm = np.isin(cls, va); vi = np.where(vm)[0]; vx = xyz[vi]
    irv = (vx[:,0] >= xn) & (vx[:,0] <= xx) & (vx[:,1] >= yn) & (vx[:,1] <= yx)
    lgi = vi[irv]; lx = vx[irv]; nl = len(lx)
    if nl < 3:
        cache.faces = fo; cache.shade = so; cache.face_normals = no; cache._vtk_colors_ptr = None
        if no is not None and len(no) > 0:
            cache.vertex_normals = _compute_vertex_normals(cache.xyz_unique, fo, no)
            cache.vertex_shade = _compute_shading(cache.vertex_normals, getattr(app, 'last_shade_azimuth', 45.), getattr(app, 'last_shade_angle', 45.), getattr(app, 'shade_ambient', .25))
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    lo = lx.min(axis=0); lxo = lx - lo
    xe = lxo[:,0].max()-lxo[:,0].min(); ye = lxo[:,1].max()-lxo[:,1].min()
    ns = np.sqrt(max(xe*ye, 1.) / max(nl, 1)); pr = max(ns*0.3, 0.005)
    pu = nl / max((pr / max(ns, 1e-9))**2, 1)
    if pu > 80000: pr = max(pr * np.sqrt(pu / 80000), 0.005)
    xyg = np.floor(lxo[:,:2] / pr).astype(np.int64)
    si = np.lexsort((-lxo[:,2], xyg[:,1], xyg[:,0])); xys = xyg[si]
    d = np.diff(xys, axis=0); um = np.concatenate([[True], (d[:,0] != 0) | (d[:,1] != 0)])
    ui = si[um]; ux = lxo[ui]; ug = lgi[ui]
    if len(ux) < 3:
        cache.faces = fo; cache.shade = so; cache.face_normals = no; cache._vtk_colors_ptr = None
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    xy = ux[:,:2]
    try: lf = _do_triangulate(xy)
    except:
        cache.faces = fo; cache.shade = so; cache.face_normals = no; cache._vtk_colors_ptr = None
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    if len(lf) == 0:
        cache.faces = fo; cache.shade = so; cache.face_normals = no; cache._vtk_colors_ptr = None
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    ls = np.sqrt((xy[:,0].max()-xy[:,0].min())*(xy[:,1].max()-xy[:,1].min()) / max(len(xy), 1))
    lf = _filter_edges_by_absolute(lf, xy, max(ls*100, cache.spacing*100))
    if len(lf) == 0:
        cache.faces = fo; cache.shade = so; cache.face_normals = no; cache._vtk_colors_ptr = None
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    g2u = cache.build_global_to_unique(len(xyz)); ltc = g2u[ug]; npm = ltc < 0
    if int(np.sum(npm)) > 0:
        ng = ug[npm]; nx2 = ux[npm] + lo - cache.offset
        cache.unique_indices = np.concatenate([cache.unique_indices, ng])
        cache.xyz_unique = np.vstack([cache.xyz_unique, nx2]); cache.xyz_final = np.vstack([cache.xyz_final, nx2 + cache.offset])
        cache._global_to_unique = None; g2u = cache.build_global_to_unique(len(xyz)); ltc = g2u[ug]
    npf = ltc[lf]
    if np.any(npf < 0): return False
    pn = _compute_face_normals(cache.xyz_unique, npf)
    ps = _compute_face_shade(cache.xyz_unique, npf, getattr(app, 'last_shade_azimuth', 45.), getattr(app, 'last_shade_angle', 45.), getattr(app, 'shade_ambient', .25), face_normals=pn)
    cache.faces = np.vstack([fo, npf]); cache.shade = np.concatenate([so, ps])
    cache.face_normals = pn if no is None else np.vstack([no, pn])
    _recompute_vertex_normals_partial(cache, nk); cache._vtk_colors_ptr = None
    _render_mesh(app, cache, cr, _save_camera(app)); return True

def _rebuild_single_class(app, sci):
    cache = get_cache()
    if cache.faces is None or len(cache.faces) == 0: cache.clear("no mesh"); _do_full_rebuild(app, sci); return
    cls = app.data.get("classification").astype(np.int32); cvl = cls[cache.unique_indices]; vl = cvl != sci
    if np.sum(vl) == 0: return
    ifm = vl[cache.faces[:,0]] | vl[cache.faces[:,1]] | vl[cache.faces[:,2]]; vfm = ~ifm
    if np.sum(vfm) == 0: cache.clear("all invalid"); _do_full_rebuild(app, sci); return
    rva = np.where(vl)[0].astype(np.int32); ifa = cache.faces[ifm]
    irf = np.zeros(len(cache.unique_indices), dtype=bool)
    if len(rva) > 0: irf[rva] = True
    bv = np.unique(ifa.ravel()[~irf[ifa.ravel()]]).astype(np.int32)
    npf = np.array([], dtype=np.int32).reshape(0, 3); nps = np.array([], dtype=np.float32)
    if len(bv) >= 3:
        bxy = cache.xyz_unique[bv, :2]
        try:
            lf = _do_triangulate(bxy)
            if len(lf) > 0 and len(bv) > 10:
                xr = bxy[:,0].max()-bxy[:,0].min(); yr = bxy[:,1].max()-bxy[:,1].min()
                lf = _filter_edges_by_absolute(lf, bxy, max(np.sqrt(xr*yr/len(bv))*5, cache.spacing*1000))
            if len(lf) > 0:
                npf = bv[lf]; pn = _compute_face_normals(cache.xyz_unique, npf)
                nps = _compute_face_shade(cache.xyz_unique, npf, getattr(app, 'last_shade_azimuth', 45), getattr(app, 'last_shade_angle', 45), getattr(app, 'shade_ambient', .25), face_normals=pn)
        except: pass
    vf = cache.faces[vfm]; vs = cache.shade[vfm]; vn = cache.face_normals[vfm] if cache.face_normals is not None else None
    if len(npf) > 0:
        pnm = _compute_face_normals(cache.xyz_unique, npf)
        cache.faces = np.vstack([vf, npf]); cache.shade = np.concatenate([vs, nps])
        cache.face_normals = pnm if vn is None else np.vstack([vn, pnm])
    else: cache.faces = vf; cache.shade = vs; cache.face_normals = vn
    _recompute_vertex_normals_partial(cache, len(vf)); cache._vtk_colors_ptr = None
    _render_mesh(app, cache, app.data.get("classification"), _save_camera(app))

def _do_full_rebuild(app, sci):
    sv = {c: app.class_palette[c].get("show", True) for c in app.class_palette}
    for c in app.class_palette: app.class_palette[c]["show"] = (int(c) == sci)
    try: update_shaded_class(app, force_rebuild=True)
    finally:
        for c, v in sv.items(): app.class_palette[c]["show"] = v

def _check_previous_classes_visible(app, ci, va):
    try:
        for attr, key in [('redostack', 'newclasses'), ('redostack', 'new_classes'), ('undostack', 'oldclasses'), ('undostack', 'old_classes')]:
            stk = getattr(app, attr, None)
            if stk:
                prev = stk[-1].get(key)
                if prev is not None:
                    if not hasattr(prev, '__iter__') or np.ndim(prev) == 0: return int(prev) in set(va.tolist())
                    return bool(np.all(np.isin(np.asarray(prev), va)))
        return set(int(c) for c in app.class_palette.keys()).issubset(set(va.tolist()))
    except: return False

def refresh_shaded_after_undo_fast(app, changed_mask=None):
    cache = get_cache()
    if cache.faces is None or len(cache.faces) == 0: return False
    isc = getattr(cache, 'n_visible_classes', 0) == 1; sci = getattr(cache, 'single_class_id', None)
    vc = getattr(cache, 'visible_classes_set', None) or _get_shading_visibility(app)
    if changed_mask is None or not np.any(changed_mask): return _update_colors_gpu_fast(app, cache, changed_mask=None)
    cls = app.data.get("classification"); xyz = app.data.get("xyz")
    if cls is None or xyz is None: return False
    cls = cls.astype(np.int32); ci = np.where(changed_mask)[0]
    if len(ci) == 0: return True
    va = np.array(sorted(vc), dtype=np.int32) if vc else np.array([], dtype=np.int32)
    nv = np.isin(cls[ci], va) if len(va) > 0 else np.zeros(len(ci), dtype=bool)
    if np.all(nv) and _check_previous_classes_visible(app, ci, va):
        if _update_colors_gpu_fast(app, cache, changed_mask=changed_mask):
            global _rebuild_timer
            if _rebuild_timer:
                try: _rebuild_timer.stop()
                except: pass
            return True
    g2u = cache.build_global_to_unique(len(xyz)); cu = g2u[ci]; ic = cu >= 0
    uv = np.zeros(len(cache.unique_indices), dtype=bool)
    if cache.faces is not None and len(cache.faces) > 0: uv[np.unique(cache.faces.ravel())] = True
    aim = np.zeros(len(ci), dtype=bool); vp = np.where(ic)[0]
    if len(vp) > 0: aim[vp] = uv[cu[vp]]
    hm = aim & (~nv); vm = nv & (~aim)
    if np.any(vm) and _check_previous_classes_visible(app, ci, va): vm[:] = False
    pbh = ci[hm]; pbv = ci[vm]
    if len(pbh) == 0 and len(pbv) == 0:
        return _update_colors_gpu_fast(app, cache, changed_mask=changed_mask) or False
    if not isc or sci is None:
        if len(pbv) > 0: return _multi_class_region_undo_patch(app, changed_mask, vc)
        if len(pbh) > 0: return _incremental_visibility_patch(app, pbh, vc)
        return True
    if len(pbv) > 0 and len(pbh) > 0: return False
    if len(pbv) > 0: _rebuild_single_class_for_undo(app, sci, changed_mask); return True
    if len(pbh) > 0: _rebuild_single_class(app, sci); return True
    return True

def _update_colors_gpu_fast(app, cache, changed_mask=None, _visible_classes=None, _defer_render=False):
    try:
        mesh = getattr(app, '_shaded_mesh_polydata', None)
        if mesh is None: return False
        isc = getattr(cache, 'n_visible_classes', 0) == 1; sci = getattr(cache, 'single_class_id', None)
        vc = _visible_classes or _get_shading_visibility(app)
        if isc and sci is not None:
            cc = mesh.GetCellData().GetScalars()
            if cc and cc.GetNumberOfTuples() == len(cache.faces):
                vp = numpy_support.vtk_to_numpy(cc)
                sh = cache.shade if cache.shade is not None and len(cache.shade) == len(cache.faces) else np.ones(len(cache.faces), dtype=np.float32)
                bc = np.array(app.class_palette.get(sci, {}).get("color", (128,128,128)), dtype=np.float32)
                vp[:] = np.clip(bc * sh[:, None], 0, 255).astype(np.uint8); cc.Modified()
                if _defer_render:
                    mesh.Modified(); a = getattr(app, '_shaded_mesh_actor', None)
                    if a: a.GetMapper().Modified()
                    QTimer.singleShot(0, lambda: app.vtk_widget.render() if not getattr(app, 'is_dragging', False) else None)
                else: app.vtk_widget.render()
                return True
        pc = mesh.GetPointData().GetScalars()
        if pc is None or pc.GetNumberOfTuples() != len(cache.unique_indices): return False
        vp = numpy_support.vtk_to_numpy(pc); cls = app.data.get("classification").astype(np.int32)
        cm = cls[cache.unique_indices]; nv2 = len(cm)
        sh = cache.vertex_shade if cache.vertex_shade is not None and len(cache.vertex_shade) == nv2 else np.ones(nv2, dtype=np.float32)
        mc = max(int(cm.max())+1, 256); lut = np.zeros((mc, 3), dtype=np.float32)
        for c, e in app.class_palette.items():
            ci = int(c)
            if ci < mc and ci in vc: lut[ci] = e.get("color", (128,128,128))
        vcl = np.clip(cm, 0, mc-1)
        if changed_mask is not None and np.any(changed_mask):
            g2u = cache.build_global_to_unique(len(app.data["xyz"]))
            cu = g2u[np.where(changed_mask)[0]]; cu = cu[(cu >= 0) & (cu < nv2)]
            if len(cu) > 0:
                vp[cu] = np.clip(lut[vcl[cu]] * sh[cu, None], 0, 255).astype(np.uint8); pc.Modified()
                if _defer_render or len(cu) < 500:
                    mesh.Modified(); a = getattr(app, '_shaded_mesh_actor', None)
                    if a: a.GetMapper().Modified()
                    QTimer.singleShot(0, lambda: app.vtk_widget.render() if not getattr(app, 'is_dragging', False) else None)
                else: app.vtk_widget.render()
                return True
        vp[:] = np.clip(lut[vcl] * sh[:, None], 0, 255).astype(np.uint8); pc.Modified()
        if _defer_render:
            mesh.Modified(); a = getattr(app, '_shaded_mesh_actor', None)
            if a: a.GetMapper().Modified()
            QTimer.singleShot(0, lambda: app.vtk_widget.render() if not getattr(app, 'is_dragging', False) else None)
        else: app.vtk_widget.render()
        return True
    except: return False

def _rebuild_single_class_for_undo(app, sci, changed_mask):
    cache = get_cache()
    if cache.faces is None or cache.xyz_unique is None: _do_full_rebuild(app, sci); return
    cls = app.data.get("classification").astype(np.int32); xyz = app.data.get("xyz")
    ci = np.where(changed_mask)[0]; rgi = ci[cls[ci] == sci]
    if len(rgi) == 0: return
    rx = xyz[rgi]; xn, yn = rx[:,0].min(), rx[:,1].min(); xx, yx = rx[:,0].max(), rx[:,1].max()
    mg = cache.spacing * 5 if cache.spacing > 0 else 1000.
    xn -= mg; yn -= mg; xx += mg; yx += mg
    avi = np.where(cls == sci)[0]; avx = xyz[avi]
    ir = (avx[:,0] >= xn) & (avx[:,0] <= xx) & (avx[:,1] >= yn) & (avx[:,1] <= yx)
    lgi = avi[ir]; lx = avx[ir]
    if len(lx) < 3: return
    cf = cache.xyz_final
    irm = (cf[:,0] >= xn) & (cf[:,0] <= xx) & (cf[:,1] >= yn) & (cf[:,1] <= yx)
    fir = irm[cache.faces[:,0]] & irm[cache.faces[:,1]] & irm[cache.faces[:,2]]
    fo = cache.faces[~fir]; so = cache.shade[~fir]; no = cache.face_normals[~fir] if cache.face_normals is not None else None
    lo = lx.min(axis=0); lxo = lx - lo
    ns = np.sqrt(max((lxo[:,0].max()-lxo[:,0].min())*(lxo[:,1].max()-lxo[:,1].min()), 1.) / max(len(lx), 1))
    pr = max(ns*0.3, 0.005); pu = len(lx) / max((pr/max(ns, 1e-9))**2, 1)
    if pu > 80000: pr = max(pr*np.sqrt(pu/80000), 0.005)
    xyg = np.floor(lxo[:,:2]/pr).astype(np.int64)
    si = np.lexsort((-lxo[:,2], xyg[:,1], xyg[:,0])); xys = xyg[si]
    d = np.diff(xys, axis=0); um = np.concatenate([[True], (d[:,0]!=0)|(d[:,1]!=0)])
    uli = si[um]; ulx = lxo[uli]; ulg = lgi[uli]
    if len(ulx) < 3: return
    xy = ulx[:,:2]
    try: lf = _do_triangulate(xy)
    except: return
    if len(lf) == 0: return
    ls = np.sqrt((xy[:,0].max()-xy[:,0].min())*(xy[:,1].max()-xy[:,1].min())/len(xy)) if len(xy) > 0 else cache.spacing
    lf = _filter_edges_by_absolute(lf, xy, max(ls*5, cache.spacing*1000))
    if len(lf) == 0: return
    g2u = cache.build_global_to_unique(len(xyz)); ltc = g2u[ulg]
    if int(np.sum(ltc < 0)) > 0:
        ngi = ulg[ltc < 0]; nx2 = ulx[ltc < 0] + lo - cache.offset
        cache.unique_indices = np.concatenate([cache.unique_indices, ngi])
        cache.xyz_unique = np.vstack([cache.xyz_unique, nx2]); cache.xyz_final = np.vstack([cache.xyz_final, nx2+cache.offset])
        cache._global_to_unique = None; g2u = cache.build_global_to_unique(len(xyz)); ltc = g2u[ulg]
    npf = ltc[lf]
    if np.any(npf < 0): return
    fn = _compute_face_normals(cache.xyz_unique, npf)
    nps = _compute_face_shade(cache.xyz_unique, npf, getattr(app, 'last_shade_azimuth', 45), getattr(app, 'last_shade_angle', 45), getattr(app, 'shade_ambient', .25), face_normals=fn)
    cache.faces = np.vstack([fo, npf]); cache.shade = np.concatenate([so, nps])
    cache.face_normals = fn if no is None else np.vstack([no, fn])
    _recompute_vertex_normals_partial(cache, len(fo)); cache._vtk_colors_ptr = None
    _render_mesh(app, cache, app.data.get("classification"), _save_camera(app))

def _fast_incremental_add_points(app, ngi):
    cache = get_cache()
    if cache.faces is None or cache.xyz_unique is None or cache.xyz_final is None: return False
    if len(ngi) == 0: return True
    xr = app.data.get("xyz"); cr = app.data.get("classification")
    if xr is None or cr is None: return False
    g2u = cache.build_global_to_unique(len(xr)); mg = ngi[g2u[ngi] < 0]
    if len(mg) == 0: return _update_colors_gpu_fast(app, cache, changed_mask=None)
    nn = len(mg); nxr2 = xr[mg]; nxl = (nxr2 - cache.offset).astype(np.float64)
    xn = nxl[:,0].min(); yn = nxl[:,1].min(); xx = nxl[:,0].max(); yx = nxl[:,1].max()
    mrg = max(cache.spacing*8, 0.5); xn -= mrg; yn -= mrg; xx += mrg; yx += mrg
    eib = (cache.xyz_unique[:,0] >= xn) & (cache.xyz_unique[:,0] <= xx) & (cache.xyz_unique[:,1] >= yn) & (cache.xyz_unique[:,1] <= yx)
    ei = np.where(eib)[0]; onv = len(cache.xyz_unique)
    cache.unique_indices = np.concatenate([cache.unique_indices, mg])
    cache.xyz_unique = np.vstack([cache.xyz_unique, nxl]); cache.xyz_final = np.vstack([cache.xyz_final, nxr2])
    cache._global_to_unique = None; cache._vtk_colors_ptr = None
    nvi = np.arange(onv, onv+nn, dtype=np.int32)
    if len(ei) > 0:
        ib = np.zeros(len(cache.xyz_unique), dtype=bool); ib[ei] = True; ib[nvi] = True
        fir = ib[cache.faces[:,0]] & ib[cache.faces[:,1]] & ib[cache.faces[:,2]]
        fo = cache.faces[~fir]; so = cache.shade[~fir] if cache.shade is not None else np.array([])
        no = cache.face_normals[~fir] if cache.face_normals is not None else None
    else: fo = cache.faces; so = cache.shade if cache.shade is not None else np.array([]); no = cache.face_normals
    lai = np.concatenate([ei, nvi]); lxy = cache.xyz_unique[lai, :2]
    if len(lai) < 3:
        cache.faces = fo; cache.shade = so; cache.face_normals = no
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    try: lf = _do_triangulate(lxy)
    except:
        cache.faces = fo; cache.shade = so; cache.face_normals = no
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    if len(lf) > 0:
        le = max(lxy[:,0].max()-lxy[:,0].min(), lxy[:,1].max()-lxy[:,1].min())
        lf = _filter_edges_by_absolute(lf, lxy, max(le*0.5, cache.spacing*cache.max_edge_factor))
    if len(lf) == 0:
        cache.faces = fo; cache.shade = so; cache.face_normals = no
        _render_mesh(app, cache, cr, _save_camera(app)); return True
    pf = lai[lf]; pn = _compute_face_normals(cache.xyz_unique, pf)
    ps = _compute_face_shade(cache.xyz_unique, pf, getattr(app, 'last_shade_azimuth', 45.), getattr(app, 'last_shade_angle', 45.), getattr(app, 'shade_ambient', .25), face_normals=pn)
    nk = len(fo); cache.faces = np.vstack([fo, pf]); cache.shade = np.concatenate([so, ps])
    cache.face_normals = pn if no is None else np.vstack([no, pn])
    _recompute_vertex_normals_partial(cache, nk)
    vc = _get_shading_visibility(app); cache.visible_classes_hash = cache.get_visible_hash(vc)
    cache.data_hash = hash((len(xr), float(xr[0,0]), float(xr[-1,2])))
    _render_mesh(app, cache, cr, _save_camera(app)); return True

def _rebuild_mesh_vtk(app, cache, cr, sc): _render_mesh(app, cache, cr, sc)
def refresh_shaded_colors_fast(app):
    if getattr(app, 'display_mode', None) != "shaded_class": return
    refresh_shaded_after_classification_fast(app, None)
def refresh_shaded_colors_only(app): refresh_shaded_colors_fast(app)
def on_class_visibility_changed(app):
    if getattr(app, 'display_mode', None) == "shaded_class":
        clear_shading_cache("visibility changed"); update_shaded_class(app, force_rebuild=True)

def handle_shaded_view_change(app, view_name):
    try:
        a = getattr(app, '_shaded_mesh_actor', None)
        if not a: return
        b = a.GetMapper().GetInput().GetBounds()
        cx, cy, cz = (b[0]+b[1])/2, (b[2]+b[3])/2, (b[4]+b[5])/2
        ex, ey, ez = b[1]-b[0], b[3]-b[2], b[5]-b[4]; d = max(ex, ey, ez)*2
        cam = app.vtk_widget.renderer.GetActiveCamera()
        if view_name in ("plan", "top"):
            cam.SetPosition(cx, cy, cz+d); cam.SetFocalPoint(cx, cy, cz); cam.SetViewUp(0,1,0)
            cam.SetParallelProjection(True); cam.SetParallelScale(max(ex, ey)/2)
        elif view_name == "front":
            cam.SetPosition(cx, cy-d, cz); cam.SetFocalPoint(cx, cy, cz); cam.SetViewUp(0,0,1); cam.SetParallelProjection(True)
        elif view_name in ("side", "left"):
            cam.SetPosition(cx-d, cy, cz); cam.SetFocalPoint(cx, cy, cz); cam.SetViewUp(0,0,1); cam.SetParallelProjection(True)
        else:
            cam.SetPosition(cx-d*.7, cy-d*.7, cz+d*.7); cam.SetFocalPoint(cx, cy, cz); cam.SetViewUp(0,0,1); cam.SetParallelProjection(False)
        app.vtk_widget.renderer.ResetCameraClippingRange(); app.vtk_widget.render()
    except: pass

class ShadingControlPanel(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app; self.setWindowTitle("Shading")
        layout = QVBoxLayout()
        for label, attr, rng, default, step in [("Max edge (m):", "max_edge", (1,1000), 100, 10), ("Azimuth:", "az", (0,360), 45, 5), ("Angle:", "el", (0,90), 45, 5), ("Ambient:", "amb", (0,1), 0.25, 0.05)]:
            h = QHBoxLayout(); h.addWidget(QLabel(label)); spin = QDoubleSpinBox(); spin.setRange(*rng); spin.setValue(default); spin.setSingleStep(step)
            setattr(self, attr, spin); h.addWidget(spin); layout.addLayout(h)
        btn = QPushButton("Apply"); btn.clicked.connect(self._on_apply); layout.addWidget(btn)
        rb = QPushButton("Full Rebuild"); rb.clicked.connect(self._on_full_rebuild); layout.addWidget(rb)
        self.setLayout(layout); self._restore_from_app()
    def _restore_from_app(self):
        for a, s in [('last_shade_azimuth', 'az'), ('last_shade_angle', 'el'), ('shade_ambient', 'amb')]:
            v = getattr(self.app, a, None)
            if v is not None: getattr(self, s).setValue(v)
    def _on_apply(self):
        self.app.last_shade_azimuth = self.az.value(); self.app.last_shade_angle = self.el.value(); self.app.shade_ambient = self.amb.value()
        update_shaded_class(self.app, self.az.value(), self.el.value(), self.amb.value(), single_class_max_edge=self.max_edge.value())
    def _on_full_rebuild(self):
        self.app.last_shade_azimuth = self.az.value(); self.app.last_shade_angle = self.el.value(); self.app.shade_ambient = self.amb.value()
        clear_shading_cache("manual"); update_shaded_class(self.app, self.az.value(), self.el.value(), self.amb.value(), force_rebuild=True, single_class_max_edge=self.max_edge.value())

__all__ = ['update_shaded_class', 'refresh_shaded_colors_fast', 'refresh_shaded_colors_only',
    'refresh_shaded_after_classification_fast', 'refresh_shaded_after_undo_fast',
    'refresh_shaded_after_visibility_change', 'handle_shaded_view_change',
    '_multi_class_region_undo_patch', 'ShadingControlPanel', 'clear_shading_cache',
    'get_cache', 'invalidate_cache_for_new_file', 'on_class_visibility_changed', '_get_shading_visibility']