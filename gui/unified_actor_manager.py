
import numpy as np
import pyvista as pv
from vtkmodules.util import numpy_support
from typing import Optional, Dict
import time
import vtk
 
UNIFIED_ACTOR_NAME = "_naksha_unified_cloud"
 
# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
_BASE_POINT_SIZE = 3.0
 
 
# ─────────────────────────────────────────────────────────────────────────────
# VIEW SHADER CONTEXT
# ─────────────────────────────────────────────────────────────────────────────
class ViewShaderContext:
    __slots__ = (
        "slot_idx", "visibility_mask", "weight_lut", "color_lut",
        "border_ring", "_fingerprint", "_observer_id", "_generation",
        "_has_vertex_attr_cache",
        "_vis_list_cache", "_wt_list_cache",
    )
 
    def __init__(self, slot_idx: int = 0):
        self.slot_idx            = slot_idx
        self.visibility_mask     = np.ones(256, dtype=np.float32)
        self.weight_lut          = np.full(256, _BASE_POINT_SIZE, dtype=np.float32)
        self.color_lut           = np.full(256 * 3, 0.5, dtype=np.float32)
        self.border_ring         = np.float32(0.0)
        self._fingerprint: Optional[int] = None
        self._observer_id: Optional[int] = None
        self._generation: int    = 0
        self._vis_list_cache     = None
        self._wt_list_cache      = None
        self._has_vertex_attr_cache = False
 
    def load_from_palette(self, palette: dict, border_percent: float = 0.0,
                          base_point_size: float = _BASE_POINT_SIZE) -> bool:
        palette = palette or {}
        fp = _palette_fingerprint_full(palette, border_percent)
        if fp == self._fingerprint:
            return False
        self._fingerprint = fp
 
        self.visibility_mask[:] = 1.0
        self.weight_lut[:] = base_point_size
        self.color_lut[:] = 0.5
 
        for code, info in palette.items():
            idx = int(code)
            if idx < 0 or idx >= 256:
                continue
            self.visibility_mask[idx] = 1.0 if info.get("show", True) else 0.0
            raw_weight = float(info.get("weight", 1.0))
            clamped_weight = max(0.1, min(raw_weight, 10.0))
            self.weight_lut[idx] = compute_point_size(clamped_weight, base_point_size)
            r, g, b = info.get("color", (128, 128, 128))
            base = idx * 3
            self.color_lut[base]     = r / 255.0
            self.color_lut[base + 1] = g / 255.0
            self.color_lut[base + 2] = b / 255.0
 
        # ── Border ring (MicroStation square-sprite formula) ─────────────────
        # border_percent / 100.0  clamped to [0.0, 0.50]
        # 0% = no border (round circle), 10% = thin, 25% = medium, 50% = max.
        # Old formula (/ 60.0, cap 0.45) was broken: 27 %–100 % all produced
        # the same ring width of 0.45, making most of the slider range useless.
        self.border_ring = np.float32(min(0.50, max(0.0, border_percent / 100.0)))
        self._generation += 1
        self._vis_list_cache = None
        self._wt_list_cache  = None
        return True
 
    def force_reload(self):
        self._fingerprint    = None
        self._vis_list_cache = None
        self._wt_list_cache  = None
 
    def vis_as_list(self):
        if self._vis_list_cache is None:
            self._vis_list_cache = self.visibility_mask.tolist()
        return self._vis_list_cache
 
    def wt_as_list(self):
        if self._wt_list_cache is None:
            self._wt_list_cache = self.weight_lut.tolist()
        return self._wt_list_cache
 
    def clone_for_view(self, new_slot_idx: int) -> 'ViewShaderContext':
        ctx = ViewShaderContext(new_slot_idx)
        np.copyto(ctx.visibility_mask, self.visibility_mask)
        np.copyto(ctx.weight_lut,      self.weight_lut)
        np.copyto(ctx.color_lut,       self.color_lut)
        ctx.border_ring             = self.border_ring
        ctx._fingerprint            = self._fingerprint
        ctx._has_vertex_attr_cache  = self._has_vertex_attr_cache
        return ctx
 
 
def _palette_fingerprint_full(palette: dict, border_percent: float = 0.0) -> int:
    try:
        return hash((
            tuple(
                (k, v.get("show", True),
                 tuple(v.get("color", (128, 128, 128))),
                 round(float(v.get("weight", 1.0)), 3))
                for k, v in sorted(palette.items())
            ),
            round(border_percent, 2),
        ))
    except Exception:
        return id(palette) ^ int(border_percent * 100)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# SHADER REGISTRY
# ─────────────────────────────────────────────────────────────────────────────
_shader_contexts: Dict[str, ViewShaderContext] = {}
 
 
def get_shader_context(actor_name: str) -> Optional[ViewShaderContext]:
    return _shader_contexts.get(actor_name)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — defined first so every function below can call them safely
# ─────────────────────────────────────────────────────────────────────────────
 
def _mark_actor_dirty(actor) -> None:
    """
    Full VTK dirty chain for any in-place buffer modification.
 
    Call after ANY numpy write to an array that feeds the GPU (RGB or
    Classification).  Without all four levels, VTK's pipeline timestamp
    comparison will conclude "nothing changed" and skip the GPU re-upload.
 
    MicroStation equivalent: 'invalidate element display' — marks the element
    descriptor dirty at every level of the hierarchy so the renderer re-stamps
    the GPU buffer on the next draw call.
 
    FIX-5: moved to top of module so all functions below can call it safely.
    """
    mesh = getattr(actor, '_naksha_mesh', None)
    if mesh is None:
        return
    mesh.GetPointData().Modified()   # level 1 — PointData container
    mesh.Modified()                  # level 2 — geometry
    mapper = actor.GetMapper()
    if mapper is not None:
        mapper.Modified()            # level 3 — mapper cache
    actor.Modified()                 # level 4 — actor repaint flag
 
 
def _rewrite_rgb_from_palette(rgb_ptr: np.ndarray, classification: np.ndarray,
                               palette: dict):
    max_c = max(int(classification.max()) + 1, 256)
    lut = np.full((max_c, 3), 128, dtype=np.uint8)
    for code, info in palette.items():
        idx = int(code)
        if 0 <= idx < max_c:
            lut[idx] = (info.get("color", (128, 128, 128))
                        if info.get("show", True) else (0, 0, 0))
    np.copyto(rgb_ptr, lut[classification.clip(0, max_c - 1).astype(np.intp)])
 
 
def _touch_vtk_arrays(actor):
    """
    FIX-6: upgraded to use the full dirty chain via _mark_actor_dirty.
    Previously only called vtk_ca.Modified() + mesh.Modified(), missing
    GetPointData().Modified(), mapper.Modified(), actor.Modified().
    """
    vtk_ca = getattr(actor, '_naksha_vtk_array', None)
    if vtk_ca:
        vtk_ca.Modified()
    _mark_actor_dirty(actor)
 
 
def _is_writable(arr: np.ndarray) -> bool:
    return arr.flags.writeable
 
 
def _apply_border_once(actor, border_percent: float):
    """
    Fallback border shader for per-class actors that bypass
    _attach_view_shader_context.
 
    Matches v13: ring = clamp(border_ring_val × 0.5, 0.0, 0.25)
    No minimum-size threshold — border shows on ALL points.
    """
    if border_percent <= 0:
        return
 
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is not None:
        new_ring = np.float32(min(0.50, max(0.0, border_percent / 100.0)))
        if ctx.border_ring != new_ring:
            ctx.border_ring = new_ring
            ctx._fingerprint = None
        return
 
    cached = getattr(actor, "_naksha_border_percent", None)
    if cached == border_percent:
        return
    try:
        ring_val  = min(0.50, max(0.0, border_percent / 100.0))
        sp        = actor.GetShaderProperty()
        if sp is None:
            return
 
        if ring_val <= 0.001:
            frag_code = (
                "//VTK::Color::Impl\n"
                "if (length(gl_PointCoord.xy - vec2(0.5)) * 2.0 > 1.0) discard;\n"
                "opacity = 1.0;\n"
            )
        else:
            # v13: fixed 25%-max fraction, no threshold
            ring_frac = min(ring_val * 0.5, 0.25)
            inner     = 1.0 - ring_frac
            frag_code = (
                "//VTK::Color::Impl\n"
                "// Naksha per-class fallback border (v13)\n"
                "vec2  uv_pc = gl_PointCoord.xy - vec2(0.5);\n"
                "float sq_pc = max(abs(uv_pc.x), abs(uv_pc.y)) * 2.0;\n"
                "if (sq_pc > 1.0) discard;\n"
                f"if (sq_pc >= {inner:.6f}) {{\n"
                "    diffuseColor = vec3(0.0, 0.0, 0.0);\n"
                "    ambientColor = vec3(0.0, 0.0, 0.0);\n"
                "}\n"
                "opacity = 1.0;\n"
            )
 
        sp.ClearAllFragmentShaderReplacements()
        sp.AddFragmentShaderReplacement("//VTK::Color::Impl", True, frag_code, False)
        sp.Modified()
        actor.GetProperty().Modified()
        mapper = actor.GetMapper()
        if mapper:
            mapper.Modified()
        actor.Modified()
        actor._naksha_border_percent = border_percent
 
    except Exception as e:
        print(f"      ⚠️ _apply_border_once failed: {e}")
 
 
def update_visibility_lut(actor, palette, base_point_size=_BASE_POINT_SIZE):
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is not None:
        ctx.force_reload()
        ctx.load_from_palette(palette, float(ctx.border_ring * 60.0), base_point_size)
        _push_uniforms_direct(actor, ctx)
        return
    vis_arr = np.zeros(256, dtype=np.float32)
    for i in range(256):
        info = (palette or {}).get(i, {})
        vis_arr[i] = (compute_point_size(info.get("weight", 1.0), base_point_size)
                      if info.get("show", True) else 0.0)
    actor._local_vis_arr = vis_arr
    try:
        actor.GetMapper().Modified()
    except Exception:
        pass
 
 
# ─────────────────────────────────────────────────────────────────────────────
# CORE: PUSH UNIFORMS DIRECT
# ─────────────────────────────────────────────────────────────────────────────
def _push_uniforms_direct(actor, ctx: 'ViewShaderContext') -> bool:
    if actor is None or ctx is None:
        return False
    try:
        rw = getattr(actor, '_naksha_render_window', None)
        if rw and getattr(actor, '_naksha_needs_program_point_size', False):
            try:
                if hasattr(rw, 'GetState'):
                    state = rw.GetState()
                    if state and hasattr(state, 'vtkglEnable'):
                        state.vtkglEnable(0x8642)  # GL_PROGRAM_POINT_SIZE
                        print(f"      ✅ GL_PROGRAM_POINT_SIZE enabled via state")
                actor._naksha_needs_program_point_size = False
            except Exception as e:
                print(f"      ⚠️ PROGRAM_POINT_SIZE: {e}")
 
        sp = actor.GetShaderProperty()
        if sp is None:
            return False
 
        attached_ctx = getattr(actor, '_naksha_shader_ctx', ctx)
        has_vertex   = attached_ctx._has_vertex_attr_cache
 
        if has_vertex:
            v_uni = sp.GetVertexCustomUniforms()
            if v_uni:
                v_uni.SetUniform1fv("visibility_lut", 256, ctx.vis_as_list())
                v_uni.SetUniform1fv("weight_lut",     256, ctx.wt_as_list())
                v_uni.SetUniformf("border_ring_val", float(ctx.border_ring))
                v_uni.Modified()
                sp.Modified()
 
        f_uni = sp.GetFragmentCustomUniforms()
        if f_uni:
            f_uni.SetUniformf("border_ring_val", float(ctx.border_ring))
 
        actor.GetMapper().Modified()
        actor.GetProperty().Modified()
        return True
 
    except Exception as e:
        print(f"⚠️ _push_uniforms_direct failed: {e}")
        return False
 
 
_push_shader_uniforms = _push_uniforms_direct
 
 
# ─────────────────────────────────────────────────────────────────────────────
# SHADER ATTACHMENT — called ONCE at actor build time
# ─────────────────────────────────────────────────────────────────────────────
def _attach_view_shader_context(actor, ctx, actor_name, use_sphere_shaders=True):
    if actor is None:
        return
 
    actor._naksha_shader_ctx = ctx
    _shader_contexts[actor_name] = ctx
 
    mesh = getattr(actor, '_naksha_mesh', None)
    _ensure_opengl_polydata_mapper(actor, mesh)
 
    vertex_attr_wired = False
    try:
        mapper = actor.GetMapper()
        raw_m  = mapper.GetMapper() if hasattr(mapper, 'GetMapper') else mapper
        raw_m.MapDataArrayToVertexAttribute(
            "class_code", "Classification",
            vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, -1
        )
        vertex_attr_wired = True
        print(f"      🔗 Linked 'Classification' array to shader 'class_code'")
    except Exception as e:
        print(f"      ⚠️ Shader Attribute Mapping failed: {e}")
 
    ctx._has_vertex_attr_cache = vertex_attr_wired
    actor.GetProperty().SetRenderPointsAsSpheres(False)
 
    sp = actor.GetShaderProperty()
 
    if not hasattr(actor, "_shaders_finalized_v13"):
        sp.ClearAllVertexShaderReplacements()
        sp.ClearAllFragmentShaderReplacements()
 
        # ── Vertex shader (v13) ───────────────────────────────────────────────
        sp.AddVertexShaderReplacement(
            "//VTK::PositionVC::Dec", True,
            "//VTK::PositionVC::Dec\n"
            "in  float class_code;\n"
            "out float v_point_size;\n"
            "out float v_core_size;\n",
            False
        )
        sp.AddVertexShaderReplacement(
            "//VTK::PositionVC::Impl", True,
            "//VTK::PositionVC::Impl\n"
            "{\n"
            "  int c_idx = clamp(int(class_code + 0.5), 0, 255);\n"
            "  if (visibility_lut[c_idx] <= 0.0) {\n"
            "    gl_Position  = vec4(2.0, 2.0, 2.0, 1.0);\n"
            "    gl_PointSize = 0.0;\n"
            "    v_point_size = 0.0;\n"
            "  } else {\n"
            "    float ps     = max(1.0, weight_lut[c_idx]);\n"
            "    float target_border_pixels = border_ring_val * 4.0;\n"
            "    float total_ps = ps;\n"
            "    if (border_ring_val > 0.001) {\n"
            "        float border_pixels = min(target_border_pixels, 4.0);\n"
            "        total_ps = ps + border_pixels;\n"
            "    }\n"
            "    gl_PointSize = total_ps;\n"
            "    v_point_size = total_ps;\n"
            "    v_core_size  = ps;\n"
            "  }\n"
            "}\n",
            False
        )
 
        # ── Fragment shader (v13) — MicroStation Correct Border ──────────────
        #
        # DIAGNOSIS OF ALL PREVIOUS VERSIONS:
        # ──────────────────────────────────────────────────────────────────────
        # v9:  ring = border_percent/100 = 0.50 → 50% BLACK on every point.
        #      Dark cloud at all zoom levels. ❌
        #
        # v10: MIN_BORDER_PX = 3.0 == BASE_PS → threshold never triggered.
        #      Same 50% ring on every point. Dark cloud. ❌
        #
        # v11: MIN_BORDER_PX = 4.0. ring = (0.50×3)/ps.
        #      At DPI 150%: ps=4.5 → ring=0.33 → still 33% black. Dark. ❌
        #
        # v12: MIN_BORDER_PX = 3.5. target_px=1.0. ring=1.0/ps.
        #      At 100% DPI: ps=3.0 < 3.5 → threshold ALWAYS fires.
        #      Border NEVER shown on default-weight points. User sees no border. ❌
        #
        # ROOT MISUNDERSTANDING fixed in v13:
        # ──────────────────────────────────────────────────────────────────────
        # The MIN_BORDER_PX threshold approach was wrong from the start.
        # MicroStation does NOT suppress borders on small points — it shows
        # the border on ALL points when border_percent > 0.
        #
        # The "dark cloud" problem (v9) was caused by the ring fraction being
        # TOO LARGE (50%), not by applying border to small points.
        #
        # At small point sizes (1-2px), even a 25% ring fraction is
        # SUB-PIXEL — it contributes < 0.5px of black, which is invisible.
        # There is NO dark cloud at small sizes with a 25% cap.
        #
        # CORRECT MICROSTATION FORMULA (v13):
        # ──────────────────────────────────────────────────────────────────────
        # ring_fraction = clamp(border_ring_val × 0.5, 0.0, 0.25)
        #
        # Mapping (border_ring_val = border_percent / 100.0):
        #   border  0% → ring 0.000  (no border, round circle)
        #   border 10% → ring 0.050  (5%  of sprite = barely visible)
        #   border 25% → ring 0.125  (12% of sprite = thin frame)
        #   border 50% → ring 0.250  (25% of sprite = MicroStation default)
        #   border100% → ring 0.250  (capped at 25% — never goes darker)
        #
        # Why this works at ALL zoom levels:
        #   ps=1px: 25% ring = 0.25px black = sub-pixel → invisible, no dark  ✅
        #   ps=2px: 25% ring = 0.50px black = barely visible                  ✅
        #   ps=3px: 25% ring = 0.75px black = thin visible border              ✅
        #   ps=4px: 25% ring = 1.00px black = clean 1px border (MS default)   ✅
        #   ps=6px: 25% ring = 1.50px black = visible border at zoom-in        ✅
        #   ps=9px: 25% ring = 2.25px black = prominent border zoomed in       ✅
        #
        # Shape: Chebyshev (L∞) distance → SQUARE sprite (MicroStation style)
        # when border active. Round circle when border = 0.
        sp.AddFragmentShaderReplacement(
            "//VTK::Color::Dec", True,
            "//VTK::Color::Dec\n"
            "in float v_point_size;\n"
            "in float v_core_size;\n",
            False
        )
        sp.AddFragmentShaderReplacement(
            "//VTK::Color::Impl", True,
            "//VTK::Color::Impl\n"
            "// === Naksha MicroStation Border v17 (Depth-Biased) ===\n"
            "vec2 uv_v17 = gl_PointCoord.xy - vec2(0.5);\n"
            "\n"
            "if (border_ring_val > 0.001) {\n"
            "    float dist_px = max(abs(uv_v17.x), abs(uv_v17.y)) * v_point_size;\n"
            "    if (dist_px > v_point_size / 2.0) discard;\n"
            "\n"
            "    if (dist_px >= v_core_size / 2.0) {\n"
            "        diffuseColor = vec3(0.0);\n"
            "        ambientColor = vec3(0.0);\n"
            "        // Push border fragments backwards in depth space!\n"
            "        // This guarantees that adjacent points' colored cores will OVERLAP these black borders,\n"
            "        // leaving black outlines ONLY around the silhouette of the cloud (MicroStation style).\n"
            "        // We use an offset of 0.005 to solidly push it behind adjacent points.\n"
            "        gl_FragDepth = clamp(gl_FragCoord.z + 0.005, 0.0, 1.0);\n"
            "    } else {\n"
            "        gl_FragDepth = gl_FragCoord.z;\n"
            "    }\n"
            "} else {\n"
            "    // ── No border: plain round circle ─────────────────────────\n"
            "    if (length(uv_v17) * 2.0 > 1.0) discard;\n"
            "    gl_FragDepth = gl_FragCoord.z;\n"
            "}\n"
            "opacity = 1.0;\n"
            "// === End Naksha Border v17 ===\n",
            False
        )
        actor._shaders_finalized_v13 = True
        print(f"      ✅ GPU Shader Pipeline v13 (MicroStation border) initialised: {actor_name}")
 
    actor._naksha_needs_program_point_size = True
    actor.GetProperty().Modified()
    _push_uniforms_direct(actor, ctx)  ###
 
# ─────────────────────────────────────────────────────────────────────────────
# sync_palette_to_gpu — called by Display Mode dialog Apply
# ─────────────────────────────────────────────────────────────────────────────
def sync_palette_to_gpu(app, slot_idx: int = 0, palette: Optional[dict] = None,
                        border: Optional[float] = None, render: bool = True, **kwargs):
    t0 = time.perf_counter()
 
    if border is None:
        border = kwargs.get('border_percent', 0.0)
 
    if slot_idx == 0:
        actor_name = UNIFIED_ACTOR_NAME
        vtk_widget = getattr(app, "vtk_widget", None)
    elif 1 <= slot_idx <= 4:
        view_idx   = slot_idx - 1
        actor_name = f"_section_{view_idx}_unified"
        vtk_widget = app.section_vtks.get(view_idx) if hasattr(app, "section_vtks") else None
    elif slot_idx == 5:
        actor_name = "_cut_section_unified"
        ctrl       = getattr(app, "cut_section_controller", None)
        vtk_widget = getattr(ctrl, "cut_vtk", None) if ctrl else None
    else:
        return False
 
    if vtk_widget is None:
        return False
 
    actor = vtk_widget.actors.get(actor_name)
    if actor is None:
        return False
 
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is None:
        ctx = ViewShaderContext(slot_idx)
        _shader_contexts[actor_name] = ctx
        _attach_view_shader_context(actor, ctx, actor_name)
 
    palette         = palette or _get_slot_palette(app, slot_idx)
    base_point_size = float(getattr(actor, '_naksha_base_point_size', _BASE_POINT_SIZE))
 
    ctx.force_reload()
    ctx.load_from_palette(palette, float(border), base_point_size)
    _push_uniforms_direct(actor, ctx)
 
    # Rewrite RGB buffer so colours stay in sync with palette changes
    rgb_ptr = getattr(actor, '_naksha_rgb_ptr', None)
    if rgb_ptr is not None and _is_writable(rgb_ptr):
        sc = getattr(actor, '_naksha_section_class', None)
        if sc is not None:
            _rewrite_rgb_from_palette(rgb_ptr, sc, palette)
        else:
            gi             = getattr(app, '_main_global_indices', None)
            classification = app.data.get("classification") if hasattr(app, 'data') else None
            if classification is not None:
                vis_class = classification[gi] if gi is not None else classification
                _rewrite_rgb_from_palette(rgb_ptr, vis_class, palette)
 
        vtk_ca = getattr(actor, '_naksha_vtk_array', None)
        if vtk_ca:
            vtk_ca.Modified()
        # FIX-5 (was using incomplete dirty here): use full dirty chain
        _mark_actor_dirty(actor)
 
    if render:
        try:
            vtk_widget.render()
        except Exception:
            pass
 
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"   ⚡ GPU Sync (Slot {slot_idx}): {elapsed:.1f} ms")
    return True
 
 
# ─────────────────────────────────────────────────────────────────────────────
# connect_palette_signal
# ─────────────────────────────────────────────────────────────────────────────
def connect_palette_signal(app) -> bool:
    dialog = (getattr(app, 'display_mode_dialog', None)
              or getattr(app, 'display_dialog', None))
    if dialog is None:
        print("   ⚠️ connect_palette_signal: no dialog found")
        return False
    if not hasattr(dialog, 'palette_changed'):
        print("   ⚠️ connect_palette_signal: no palette_changed signal")
        return False
 
    def _on_palette_changed(slot_idx: int):
        palette = _get_slot_palette(app, slot_idx)
        if slot_idx == 0:
            border = float(getattr(app, 'point_border_percent', 0) or 0.0)
        else:
            dlg    = (getattr(app, 'display_mode_dialog', None)
                      or getattr(app, 'display_dialog', None))
            border = float(dlg.view_borders.get(slot_idx, 0)) if dlg else 0.0
        sync_palette_to_gpu(app, slot_idx, palette, border, render=True)
 
    try:
        dialog.palette_changed.disconnect(_on_palette_changed)
    except (TypeError, RuntimeError):
        pass
    dialog.palette_changed.connect(_on_palette_changed)
    print("   ✅ connect_palette_signal: wired")
    return True
 
 
# ─────────────────────────────────────────────────────────────────────────────
# refresh_section_after_weight_change
# ─────────────────────────────────────────────────────────────────────────────
def refresh_section_after_weight_change(
    app,
    view_idx: int,
    palette: Optional[dict] = None,
    border_percent: float = 0.0,
) -> bool:
    slot_idx = view_idx + 1
    palette  = palette or _get_slot_palette(app, slot_idx)
 
    if not hasattr(app, 'section_vtks') or view_idx not in app.section_vtks:
        return False
    vtk_widget = app.section_vtks[view_idx]
    if vtk_widget is None:
        return False
 
    actor_name = f"_section_{view_idx}_unified"
    actor = (vtk_widget.actors.get(actor_name)
             if hasattr(vtk_widget, 'actors') else None)
 
    if actor is None:
        # ═══════════════════════════════════════════════════════════════════
        # PERFORMANCE FIX: Skip if not ready, don't trigger rebuild
        # ═══════════════════════════════════════════════════════════════════
        return False  # No actor yet - skip
 
    rgb_ptr = getattr(actor, '_naksha_rgb_ptr', None)
    if rgb_ptr is None or not _is_writable(rgb_ptr):
        return False  # Not writable - skip
 
    base_point_size = float(getattr(actor, '_naksha_base_point_size', _BASE_POINT_SIZE))
 
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is not None:
        ctx.force_reload()
        ctx.load_from_palette(palette, border_percent, base_point_size)
    else:
        print(f"   ⚠️ Section {view_idx+1}: no shader context — attaching fresh")
        ctx = ViewShaderContext(slot_idx=slot_idx)
        ctx.load_from_palette(palette, border_percent, base_point_size)
        _attach_view_shader_context(actor, ctx, actor_name)
 
    sc = getattr(actor, '_naksha_section_class', None)
    if sc is not None:
        _rewrite_rgb_from_palette(rgb_ptr, sc, palette)
        # FIX-3: was calling _touch_vtk_arrays (incomplete) — now full chain
        vtk_ca = getattr(actor, '_naksha_vtk_array', None)
        if vtk_ca:
            vtk_ca.Modified()
        _mark_actor_dirty(actor)
 
    _push_uniforms_direct(actor, ctx)
 
    try:
        vtk_widget.render()
    except Exception:
        pass
 
    print(f"   ✅ refresh_section_after_weight_change: view={view_idx+1} "
          f"(slot={slot_idx}, border={border_percent}%, base_size={base_point_size})")
    return True
 
 
# ─────────────────────────────────────────────────────────────────────────────
# fast_palette_refresh — main view weight/visibility/color update
# ─────────────────────────────────────────────────────────────────────────────
def fast_palette_refresh(
    app,
    palette: Optional[dict] = None,
    border_percent: float = 0.0,
) -> bool:
    t0 = time.perf_counter()
 
    actor = _get_unified_actor(app)
    if actor is None:
        return False
 
    rgb_ptr = getattr(actor, "_naksha_rgb_ptr", None)
    vtk_ca  = getattr(actor, "_naksha_vtk_array", None)
    if rgb_ptr is None or vtk_ca is None or not _is_writable(rgb_ptr):
        return False
 
    palette         = palette or getattr(app, "class_palette", {})
    classification  = app.data["classification"]
    base_point_size = float(getattr(actor, '_naksha_base_point_size', _BASE_POINT_SIZE))
 
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is not None:
        ctx.force_reload()
        ctx.load_from_palette(palette, border_percent, base_point_size)
    else:
        print(f"   ⚠️ Main view: shader context missing — recovering")
        ctx = ViewShaderContext(slot_idx=0)
        ctx.load_from_palette(palette, border_percent, base_point_size)
        raw_mapper = actor.GetMapper()
        if hasattr(raw_mapper, 'GetMapper'):
            raw_mapper = raw_mapper.GetMapper()
        ctx._has_vertex_attr_cache = hasattr(raw_mapper, 'MapDataArrayToVertexAttribute')
        actor._naksha_shader_ctx   = ctx
        _shader_contexts[UNIFIED_ACTOR_NAME] = ctx
 
    gi        = getattr(app, '_main_global_indices', None)
    vis_class = classification[gi] if gi is not None else classification
    _rewrite_rgb_from_palette(rgb_ptr, vis_class, palette)
 
    # FIX-4: was missing GetPointData().Modified() and mapper.Modified()
    vtk_ca.Modified()
    _mark_actor_dirty(actor)          # replaces the old bare mesh.Modified() call
 
    _apply_border_once(actor, border_percent)
    _push_uniforms_direct(actor, ctx)
 
    try:
        app.vtk_widget.render()
    except Exception:
        pass
 
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"   ⚡ fast_palette_refresh: {len(vis_class):,} pts "
          f"[{elapsed:.1f} ms] base_size={base_point_size}")
    return True
 
 
# ─────────────────────────────────────────────────────────────────────────────
# COLOR LUT
# ─────────────────────────────────────────────────────────────────────────────
class ColorLUT:
    def __init__(self):
        self._lut: Optional[np.ndarray] = None
        self._palette_id: Optional[int] = None
        self._max_class: int = 0
        self._hidden_color = np.array([0, 0, 0], dtype=np.uint8)
 
    def _palette_fingerprint(self, palette: dict) -> int:
        try:
            return hash(tuple(
                (k, v.get("show", True), tuple(v.get("color", (128, 128, 128))))
                for k, v in sorted(palette.items())
            ))
        except Exception:
            return id(palette)
 
    def build(self, palette: dict, max_class_hint: int = 256) -> np.ndarray:
        fp = self._palette_fingerprint(palette)
        if fp == self._palette_id and self._lut is not None:
            return self._lut
        max_c = max(max_class_hint, max(palette.keys(), default=0) + 1)
        lut = np.full((max_c, 3), 128, dtype=np.uint8)
        for code, info in palette.items():
            if code < max_c:
                lut[code] = (info.get("color", (128, 128, 128))
                             if info.get("show", True) else self._hidden_color)
        self._lut        = lut
        self._palette_id = fp
        self._max_class  = max_c
        return lut
 
    def map_classes(self, classification: np.ndarray, palette: dict) -> np.ndarray:
        lut = self.build(palette, int(classification.max()) + 1)
        return lut[classification.clip(0, len(lut) - 1).astype(np.intp)]
 
    def map_subset(self, classification: np.ndarray, indices: np.ndarray,
                   palette: dict) -> np.ndarray:
        lut = self.build(palette, int(classification.max()) + 1)
        return lut[classification[indices].clip(0, len(lut) - 1).astype(np.intp)]
 
 
_lut_cache: Dict[str, ColorLUT] = {}
 
 
def _get_lut(view_key: str = "main") -> ColorLUT:
    if view_key not in _lut_cache:
        _lut_cache[view_key] = ColorLUT()
    return _lut_cache[view_key]
 
# ─────────────────────────────────────────────────────────────────────────────
# SNT OVERLAY Z-OFFSET — ensures SNT renders ABOVE point cloud in plan view
# ─────────────────────────────────────────────────────────────────────────────
def _restore_snt_overlays(app):
    """
    After building the point cloud actor, update SNT overlay Z-offsets
    so grid lines render ABOVE the point cloud in plan view.

    Plan view = camera looks DOWN the Z axis.
    Point cloud Z: ~850-1000 (terrain elevation)
    SNT original Z: ~0 (2D CAD file)
    
    Without offset: point cloud (Z=928) is CLOSER to camera → hides SNT (Z=0)
    With offset:    SNT moved to Z=1075 → CLOSER to camera → renders on top ✅
    
    Called at the end of build_unified_actor() — guaranteed to run after
    every point cloud load, regardless of code path (grid click, File→Open,
    classification refresh, etc.).
    """
    # ── Path 1: Via snt_dialog (has actor_cache with layer filtering) ────
    if hasattr(app, 'snt_dialog') and app.snt_dialog is not None:
        try:
            app.snt_dialog.restore_snt_actors()
            return
        except Exception as e:
            print(f"  ⚠️ SNT dialog restore: {e}")

    # ── Path 2: Direct fallback via snt_actors list ──────────────────────
    try:
        from gui.snt_attachment import _get_snt_z_offset, _apply_z_offset_to_actor
    except ImportError:
        return

    z_offset = _get_snt_z_offset(app)
    if z_offset <= 0:
        return

    try:
        renderer = app.vtk_widget.renderer
    except Exception:
        return

    count = 0
    for store_name in ['snt_actors']:
        for entry in getattr(app, store_name, []):
            for actor in entry.get('actors', []):
                try:
                    _apply_z_offset_to_actor(actor, z_offset)
                    renderer.AddActor(actor)  # idempotent — safe if already there
                    count += 1
                except Exception:
                    pass

    if count > 0:
        renderer.ResetCameraClippingRange()
        try:
            camera = renderer.GetActiveCamera()
            near, far = camera.GetClippingRange()
            camera.SetClippingRange(near * 0.01, far * 100.0)
        except Exception:
            pass
        print(f"  🔄 SNT overlays: {count} actors moved above point cloud (z_offset={z_offset:.1f})")
 
  
# ─────────────────────────────────────────────────────────────────────────────
# BUILD UNIFIED ACTOR  (main view)
# ─────────────────────────────────────────────────────────────────────────────
def build_unified_actor(
    app,
    palette: Optional[dict] = None,
    border_percent: float = 0.0,
    point_size: float = _BASE_POINT_SIZE,
) -> Optional[object]:
    t0 = time.perf_counter()
 
    plotter = getattr(app, "vtk_widget", None)
    if plotter is None:
        return None
    data = getattr(app, "data", None)
    if data is None or "xyz" not in data:
        return None
    xyz            = data["xyz"]
    classification = data.get("classification")
    if classification is None:
        return None
 
    palette = palette or getattr(app, "class_palette", {})
 
    if UNIFIED_ACTOR_NAME in plotter.actors:
        plotter.remove_actor(UNIFIED_ACTOR_NAME, render=False)
    for name in list(plotter.actors.keys()):
        if str(name).startswith("class_"):
            plotter.remove_actor(name, render=False)
 
    N_total      = len(xyz)
    target_points = 10_000_000
    if N_total > target_points:
        step           = max(1, N_total // target_points)
        global_indices = np.arange(0, N_total, step)
    else:
        global_indices = np.arange(N_total)
 
    app._main_global_indices = global_indices
    vis_xyz   = xyz[global_indices]
    vis_class = classification[global_indices]
 
    cloud     = pv.PolyData(vis_xyz)
    class_vtk = numpy_support.numpy_to_vtk(vis_class.astype(np.float32, copy=False),
                                            deep=False)
    class_vtk.SetName("Classification")
    cloud.GetPointData().AddArray(class_vtk)
 
    if not hasattr(app, "_rgb_buffer") or len(app._rgb_buffer) != len(vis_xyz):
        app._rgb_buffer = np.zeros((len(vis_xyz), 3), dtype=np.uint8)
 
    rgb_vtk = numpy_support.numpy_to_vtk(app._rgb_buffer, deep=False)
    rgb_vtk.SetName("RGB")
    cloud.GetPointData().SetScalars(rgb_vtk)
 
    lut = _get_lut("main")
    np.copyto(app._rgb_buffer, lut.map_classes(vis_class, palette))
 
    n_pts             = len(xyz)
    actual_point_size = _BASE_POINT_SIZE
 
    actor = plotter.add_points(
        cloud, scalars="RGB", rgb=True,
        point_size=actual_point_size,
        render_points_as_spheres=False,
        name=UNIFIED_ACTOR_NAME,
        reset_camera=False, render=False,
    )
 
    if actor:
        try:
            actor._naksha_render_window = plotter.render_window
        except Exception:
            pass
 
        _ensure_opengl_polydata_mapper(actor, cloud)
        mesh   = actor.GetMapper().GetInput()
        vtk_ca = mesh.GetPointData().GetScalars()
        actor._naksha_rgb_ptr         = app._rgb_buffer
        actor._naksha_vtk_array       = vtk_ca
        actor._naksha_mesh            = mesh
        actor._naksha_base_point_size = actual_point_size
        app._unified_actor            = actor
        ctx = ViewShaderContext(slot_idx=0)
        ctx.load_from_palette(palette, border_percent, actual_point_size)
        _attach_view_shader_context(actor, ctx, UNIFIED_ACTOR_NAME)
        print(f"      ✅ Main view: {len(app._rgb_buffer):,} pts "
              f"(base_size={actual_point_size}, LOD_step={max(1, n_pts//target_points)})")
 
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"   🏗️ Unified actor built: {n_pts:,} pts in {elapsed:.1f} ms")

    # ── FIX: Move SNT grids above the point cloud so they're visible ──
    _restore_snt_overlays(app)
    return actor
 
# ─────────────────────────────────────────────────────────────────────────────
# BUILD SECTION UNIFIED ACTOR
# ─────────────────────────────────────────────────────────────────────────────
def build_section_unified_actor(
    app,
    view_idx: int,
    palette: Optional[dict] = None,
    border_percent: float = 0.0,
    point_size: float = _BASE_POINT_SIZE,
    **kwargs
) -> Optional[object]:
    t0 = time.perf_counter()
    slot_idx = view_idx + 1
 
    if not hasattr(app, 'section_vtks') or view_idx not in app.section_vtks:
        return None
    vtk_widget = app.section_vtks[view_idx]
    if vtk_widget is None:
        return None
 
    core_pts  = getattr(app, f"section_{view_idx}_core_points",  None)
    buf_pts   = getattr(app, f"section_{view_idx}_buffer_points", None)
    core_mask = getattr(app, f"section_{view_idx}_core_mask",    None)
    buf_mask  = getattr(app, f"section_{view_idx}_buffer_mask",  None)
 
    if core_pts is None or core_mask is None:
        return None
 
    data = getattr(app, 'data', None)
    if data is None or 'classification' not in data:
        return None
 
    classification_full = data['classification']
    core_global_idx     = np.where(core_mask)[0]
 
    if buf_pts is not None and buf_mask is not None and len(buf_pts) > 0:
        buf_only_mask        = buf_mask & ~core_mask
        buf_global_idx       = np.where(buf_only_mask)[0]
        all_pts              = np.vstack([core_pts, buf_pts])
        all_cls              = np.concatenate([
            classification_full[core_global_idx],
            classification_full[buf_global_idx],
        ])
        all_global_indices   = np.concatenate([core_global_idx, buf_global_idx])
        combined_global_mask = core_mask | buf_mask
    else:
        all_pts              = core_pts
        all_cls              = classification_full[core_global_idx]
        all_global_indices   = core_global_idx
        combined_global_mask = core_mask
 
    if len(all_pts) == 0:
        return None
 
    setattr(app, f"_section_{view_idx}_global_indices", all_global_indices)
    palette = palette or _get_slot_palette(app, slot_idx)
 
    if border_percent <= 0 and hasattr(app, 'view_borders'):
        border_percent = float(app.view_borders.get(slot_idx, 0))
 
    actor_name = f"_section_{view_idx}_unified"
    cam_pos    = vtk_widget.camera_position
 
    if actor_name in vtk_widget.actors:
        vtk_widget.remove_actor(actor_name, render=False)
    for name in list(vtk_widget.actors.keys()):
        if str(name).startswith("class_") or str(name) in ("border_layer", "color_layer"):
            vtk_widget.remove_actor(name, render=False)
 
    cloud     = pv.PolyData(all_pts)
    cls_f32   = all_cls.astype(np.float32, copy=False)
    class_vtk = numpy_support.numpy_to_vtk(cls_f32, deep=False)
    class_vtk.SetName("Classification")
    cloud.GetPointData().AddArray(class_vtk)
 
    rgb_buffer = np.zeros((len(all_pts), 3), dtype=np.uint8)
    lut        = _get_lut(f"section_{view_idx}")
    np.copyto(rgb_buffer, lut.map_classes(all_cls, palette))
 
    rgb_vtk = numpy_support.numpy_to_vtk(rgb_buffer, deep=False)
    rgb_vtk.SetName("RGB")
    cloud.GetPointData().SetScalars(rgb_vtk)
 
    n_pts          = len(all_pts)
    actual_pt_size = _BASE_POINT_SIZE
 
    actor = vtk_widget.add_points(
        cloud, scalars="RGB", rgb=True,
        point_size=actual_pt_size,
        render_points_as_spheres=False,
        name=actor_name,
        reset_camera=False, render=False,
    )
 
    if actor is None:
        return None
 
    try:
        actor._naksha_render_window = vtk_widget.render_window
    except Exception:
        pass
 
    _ensure_opengl_polydata_mapper(actor, cloud)
 
    mesh   = actor.GetMapper().GetInput()
    vtk_ca = mesh.GetPointData().GetScalars()
 
    actor._naksha_rgb_ptr         = rgb_buffer
    actor._naksha_vtk_array       = vtk_ca
    actor._naksha_mesh            = mesh
    actor._naksha_section_class   = all_cls.copy()
    actor._naksha_section_mask    = combined_global_mask
    actor._naksha_base_point_size = actual_pt_size
 
    ctx = ViewShaderContext(slot_idx=slot_idx)
    ctx.load_from_palette(palette, border_percent, actual_pt_size)
    _attach_view_shader_context(actor, ctx, actor_name)
 
    vtk_widget.camera_position = cam_pos
    vtk_widget.render()
 
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"   🏗️ Section {view_idx+1} unified actor: {n_pts:,} pts in {elapsed:.1f} ms "
          f"(slot={slot_idx}, border={border_percent}%, base_size={actual_pt_size})")
    return actor
 
 
# ─────────────────────────────────────────────────────────────────────────────
# fast_classify_update — main view
# ─────────────────────────────────────────────────────────────────────────────
def fast_classify_update(app, changed_mask: np.ndarray, to_class: int, **kwargs):
    """
    In-place reclassification update for the MAIN view.
 
    6-step MicroStation pipeline:
      1. Resolve local changed indices
      2. Update RGB buffer + vtk_ca.Modified()
      3. Update Classification VTK array + FULL dirty chain  ← FIX-1 + FIX-2
      4. Push GPU uniforms
    """
    actor = _get_unified_actor(app)
    if actor is None:
        return False
 
    global_indices = getattr(app, '_main_global_indices', None)
    if global_indices is not None:
        local_changed = np.where(changed_mask[global_indices])[0]
    else:
        local_changed = np.where(changed_mask)[0]
 
    if local_changed.size == 0:
        return True
 
    palette = kwargs.get("palette") or getattr(app, "class_palette", {})
 
    # ── Step 1: Update RGB colour buffer ────────────────────────────────────
    rgb_ptr = getattr(actor, "_naksha_rgb_ptr", None)
    if rgb_ptr is not None:
        new_color = palette.get(to_class, {}).get("color", (128, 128, 128))
        rgb_ptr[local_changed] = new_color
        vtk_ca = getattr(actor, "_naksha_vtk_array", None)
        if vtk_ca is not None:
            vtk_ca.Modified()
 
    # ── Step 2: Update Classification VTK array + full dirty chain ───────────
    # FIX-1: was missing mesh.GetPointData().Modified(), mapper.Modified(),
    #         actor.Modified() — VTK silently skipped GPU upload without them.
    # FIX-2: _mark_actor_dirty now called here (was never called before).
    mesh = getattr(actor, '_naksha_mesh', None)
    if mesh is not None:
        class_vtk_arr = mesh.GetPointData().GetArray("Classification")
        if class_vtk_arr is not None:
            cls_np = numpy_support.vtk_to_numpy(class_vtk_arr)  # zero-copy
            cls_np[local_changed] = np.float32(to_class)
            class_vtk_arr.Modified()
            print(f"   ✅ Main view Classification array updated: "
                  f"{len(local_changed)} pts → class {to_class}")
        else:
            print("   ⚠️  Main view: 'Classification' VTK array not found")
 
    # Full dirty chain covers both the RGB and Classification changes above
    _mark_actor_dirty(actor)
 
    # ── Step 3: Push weight uniforms ────────────
    # ⚡ PERF FIX removed: VTK sometimes drops custom uniforms on mapper.Modified().
    # Always push uniforms since it takes <0.1ms.
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is not None:
        _push_uniforms_direct(actor, ctx)
        actor._last_uniform_generation = ctx._generation
 
    # ═══════════════════════════════════════════════════════════════════════
    # PERFORMANCE FIX: Render immediately + signal done to skip refresh cycle
    # This prevents the redundant 170ms refresh_after_classification call
    # ═══════════════════════════════════════════════════════════════════════
    try:
        app.vtk_widget.render()
    except Exception:
        pass
    
    # Signal that GPU update is complete - skip redundant refresh
    app._gpu_sync_done = True
    
    return True
 
 
# ─────────────────────────────────────────────────────────────────────────────
# fast_cross_section_update — section views
# ─────────────────────────────────────────────────────────────────────────────
def fast_cross_section_update(
    app,
    view_idx: int,
    changed_mask_global: np.ndarray,
    palette: Optional[dict] = None,
    skip_render: bool = False,
) -> bool:
    """
    In-place reclassification update for a CROSS-SECTION view.
 
    6-step MicroStation pipeline:
      1. Resolve local changed indices (off-by-one fix with >=)
      2. Update RGB buffer
      3. Update Classification VTK array + full dirty chain
      4. Push GPU uniforms
      5. Render
    """
    t0 = time.perf_counter()
 
    if not hasattr(app, "section_vtks") or view_idx not in app.section_vtks:
        return False
 
    vtk_widget     = app.section_vtks[view_idx]
    slot_idx       = view_idx + 1
    palette        = palette or _get_slot_palette(app, slot_idx)
    if not palette:
        return False
 
    actor_name     = f"_section_{view_idx}_unified"
    global_indices = getattr(app, f"_section_{view_idx}_global_indices", None)
 
    # ═══════════════════════════════════════════════════════════════════════
    # PERFORMANCE FIX: Skip if not ready, don't trigger rebuild
    # Rebuilds should only happen explicitly, not as fallbacks
    # ═══════════════════════════════════════════════════════════════════════
    if actor_name not in vtk_widget.actors or global_indices is None:
        return False  # Not ready - skip silently
 
    actor = vtk_widget.actors.get(actor_name)
    if actor is None:
        return False  # Actor missing - skip silently
 
    rgb_ptr = getattr(actor, "_naksha_rgb_ptr", None)
    if rgb_ptr is None or not _is_writable(rgb_ptr):
        return False  # RGB buffer not writable - skip silently
 
    classification = (app.data.get("classification")
                      if hasattr(app, 'data') and app.data else None)
    if classification is None:
        return False
 
    mapper = actor.GetMapper()
    poly   = mapper.GetInput() if mapper else None
    if poly is None:
        return False  # No polydata - skip silently
 
    vtk_scalars = poly.GetPointData().GetScalars()
    if vtk_scalars is None:
        return False  # No scalars - skip silently
 
    # ── Resolve local indices (>= fixes off-by-one from original code) ───────
    if (changed_mask_global is not None
            and len(changed_mask_global) >= global_indices.max(initial=0) + 1):
        section_changed = changed_mask_global[global_indices]
    else:
        section_changed = np.ones(len(global_indices), dtype=bool)
 
    n_changed = int(np.count_nonzero(section_changed))
 
    if n_changed > 0:
        changed_idx = np.where(section_changed)[0]
        new_classes = classification[global_indices[changed_idx]]
 
        # ── Step 1: Update RGB buffer ─────────────────────────────────────────
        max_c     = max(int(new_classes.max()) + 1, 256)
        color_lut = np.full((max_c, 3), 128, dtype=np.uint8)
        for c_code, entry in palette.items():
            idx = int(c_code)
            if 0 <= idx < max_c:
                color_lut[idx] = (entry.get("color", (128, 128, 128))
                                  if entry.get("show", True) else (0, 0, 0))
        rgb_ptr[changed_idx] = color_lut[new_classes.clip(0, max_c - 1).astype(np.intp)]
 
        # ── Step 2: Update Classification VTK array ───────────────────────────
        class_vtk_arr = poly.GetPointData().GetArray("Classification")
        if class_vtk_arr is not None:
            cls_np = numpy_support.vtk_to_numpy(class_vtk_arr)  # zero-copy
            cls_np[changed_idx] = new_classes.astype(np.float32)
            class_vtk_arr.Modified()
            print(f"   ✅ Classification VTK array updated: "
                  f"{n_changed} pts → class {np.unique(new_classes).tolist()}")
        else:
            print("   ⚠️  'Classification' VTK array not found on poly")
 
        # ── Step 3: Keep _naksha_section_class mirror in sync ─────────────────
        if hasattr(actor, "_naksha_section_class"):
            actor._naksha_section_class[changed_idx] = new_classes
 
        # ── Step 4: Full dirty chain ──────────────────────────────────────────
        vtk_scalars.Modified()
        _mark_actor_dirty(actor)   # GetPointData + mesh + mapper + actor
 
    # ── Step 5: Push GPU uniforms ONLY when palette changed ──────────────────
    # ⚡ PERF FIX: Classification never changes the LUT — skip 256-float upload
    # when _generation matches. Saves ~3ms per section update.
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is not None:
        _last_gen = getattr(actor, '_last_uniform_generation', -1)
        if ctx._generation != _last_gen:
            _push_uniforms_direct(actor, ctx)
            actor._last_uniform_generation = ctx._generation
        # else: palette unchanged — skip SetUniform1fv (LUT is already on GPU)
    else:
        print("   ⚠️  No shader context on actor — uniforms not pushed")
 
    # ── Step 6: Render (caller can batch renders with skip_render=True) ───────
    if not skip_render:
        try:
            vtk_widget.render()
        except Exception:
            pass
        # Signal GPU sync complete only when we rendered immediately.
        # skip_render=True means the caller owns the render — don't mark done yet,
        # or the optimizer's final render pass will be skipped prematurely.
        app._gpu_sync_done = True
    
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"   ⚡ Section {view_idx + 1} RGB inject: {n_changed} pts [{elapsed:.1f} ms]")
    return True
 
 
 
# ─────────────────────────────────────────────────────────────────────────────
# REPLACE these two functions in gui/unified_actor_manager.py
# ─────────────────────────────────────────────────────────────────────────────
#
# ROOT CAUSE OF BUG:
#   Both functions used  app.section_{view_idx}_combined_mask  which is NEVER
#   set anywhere in the codebase.
#
#   build_section_unified_actor() writes:
#       setattr(app, f"_section_{view_idx}_global_indices", all_global_indices)
#
#   all_global_indices is an int array where  gi[i] = global dataset index
#   of local point i inside that section actor's buffer.
#   This is the bridge we must use — not a boolean mask.
#
# ADDITIONAL FIXES in this patch:
#   • Vectorised numpy LUT replaces the Python  for i_loc, c_val in zip(...)
#     loop in _patch_actor_memory  (was O(N) Python — freezes on large sections)
#   • _mark_actor_dirty() called after every GPU poke (was missing entirely)
#   • Guard: changed_mask shorter than max global index → safe fallback
#   • Guard: sec_actor with no writable rgb_ptr → skip gracefully
#   • Renderer errors caught per-view so one bad widget can't crash the rest
# ─────────────────────────────────────────────────────────────────────────────
 
 
def fast_undo_update(app, changed_mask: np.ndarray, **kwargs) -> bool:
    """
    Universal undo/redo — patches Main View AND every open Cross-Section
    instantly, in-place.  Zero allocation, no actor rebuild.
 
    MicroStation equivalent: 'undo element change' invalidates only the
    affected element descriptors in the display list — not the whole view.
 
    Parameters
    ----------
    app          : NakshaApp instance
    changed_mask : boolean ndarray, length == len(app.data["classification"])
                   True where classification was reverted by undo/redo.
    """
    t0 = time.perf_counter()
    actors_updated = 0
    total_pts = 0
 
    # ── 1. Main View (LOD-subsampled, ~10 M rendered points) ─────────────────
    main_actor = _get_unified_actor(app)
    if main_actor:
        gi = getattr(app, '_main_global_indices', None)
        if gi is not None:
            local_changed = np.where(changed_mask[gi])[0]
        else:
            local_changed = np.where(changed_mask)[0]
 
        if local_changed.size > 0:
            _patch_actor_memory(app, main_actor, local_changed, slot_idx=0)
            actors_updated += 1
            total_pts += local_changed.size
 
    # ── 2. All open Cross-Section Views ──────────────────────────────────────
    if not (hasattr(app, 'section_vtks') and app.section_vtks):
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"   ⚡ fast_undo_update: {total_pts:,} pts across "
              f"{actors_updated} views [{elapsed:.1f} ms]")
        return actors_updated > 0
 
    # RGB inject all sections first, then render all (batched = faster GPU pipeline)
    sections_to_render = []
    for view_idx, vtk_widget in app.section_vtks.items():
        if vtk_widget is None:
            continue
        actor_name = f"_section_{view_idx}_unified"
        sec_actor = vtk_widget.actors.get(actor_name)
        if sec_actor is None:
            continue
        rgb_ptr = getattr(sec_actor, "_naksha_rgb_ptr", None)
        if rgb_ptr is None or not _is_writable(rgb_ptr):
            continue
        gi_section = getattr(app, f'_section_{view_idx}_global_indices', None)
        if gi_section is None:
            continue
        max_gi = int(gi_section.max(initial=0))
        if len(changed_mask) < max_gi + 1:
            local_sec_changed = np.arange(len(gi_section), dtype=np.intp)
        else:
            local_sec_changed = np.where(changed_mask[gi_section])[0]
        if local_sec_changed.size == 0:
            continue  # nothing changed in this section — skip render too
        _patch_actor_memory(app, sec_actor, local_sec_changed, slot_idx=view_idx + 1)
        sections_to_render.append((view_idx, vtk_widget, local_sec_changed.size))
        actors_updated += 1
        total_pts += local_sec_changed.size
    # Batch render after all RGB injects
    for view_idx, vtk_widget, n_pts in sections_to_render:
        try:
            vtk_widget.render()
            print(f"   ⚡ Section {view_idx+1} RGB inject: {n_pts} pts")
        except Exception as e:
            print(f"   ⚠️  fast_undo_update: render failed section {view_idx+1}: {e}")
 
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"   ⚡ fast_undo_update: {total_pts:,} pts across "
          f"{actors_updated} views [{elapsed:.1f} ms]")
    return actors_updated > 0
 
 
def _patch_actor_memory(app, actor, local_indices: np.ndarray,
                        slot_idx: int) -> None:
    """
    Zero-allocation GPU poke for instant colour/class reversion.
 
    Writes directly into the actor's numpy-backed VTK buffers — no actor
    rebuild, no buffer swap.  Equivalent to MicroStation's 'modify element
    descriptor in place' after an undo step.
 
    Parameters
    ----------
    app           : NakshaApp instance
    actor         : the VTK actor whose buffers to patch
    local_indices : int ndarray — LOCAL point indices inside this actor's buffer
    slot_idx      : 0 = main view, 1..N = section (view_idx = slot_idx - 1)
    """
    # ── 1. Source of truth: CPU classification (already reverted by undo) ─────
    full_cls = app.data["classification"]
 
    # ── 2. Map local → global → get reverted classes ──────────────────────────
    if slot_idx == 0:
        # Main view: _main_global_indices[local_i] = global_i
        gi = getattr(app, '_main_global_indices', None)
        if gi is not None:
            reverted_cls = full_cls[gi[local_indices]]
        else:
            reverted_cls = full_cls[local_indices]
    else:
        view_idx = slot_idx - 1
        # ── FIX: _section_{view_idx}_global_indices is an int array ──────────
        # gi_section[local_i] = global_i  →  full_cls[gi_section[local_i]]
        # Old code used section_{view_idx}_combined_mask (bool, never set)
        # then np.where(mask)[0][local_indices] which produced wrong indices.
        gi_section = getattr(app, f'_section_{view_idx}_global_indices', None)
        if gi_section is None:
            # Section was rebuilt between undo push and now — skip safely
            return
        reverted_cls = full_cls[gi_section[local_indices]]
 
    # ── 3. Sync _naksha_section_class mirror ──────────────────────────────────
    # Prevents the next palette refresh from re-reading stale mirror data
    # and overwriting our GPU poke with the pre-undo classification.
    if hasattr(actor, "_naksha_section_class"):
        actor._naksha_section_class[local_indices] = reverted_cls
 
    # ── 4. Poke GPU Classification array (drives point sizes via shader LUT) ──
    mesh = getattr(actor, '_naksha_mesh', None)
    if mesh is not None:
        class_vtk = mesh.GetPointData().GetArray("Classification")
        if class_vtk is not None:
            numpy_support.vtk_to_numpy(class_vtk)[local_indices] = (
                reverted_cls.astype(np.float32))
            class_vtk.Modified()
 
    # ── 5. Poke GPU colour buffer (vectorised numpy — no Python loop) ─────────
    # Old code:  for i_loc, c_val in zip(local_indices, reverted_cls): ...
    # That is O(N) Python and freezes the UI on large sections.
    rgb_ptr = getattr(actor, "_naksha_rgb_ptr", None)
    if rgb_ptr is not None and _is_writable(rgb_ptr):
        palette = _get_slot_palette(app, slot_idx)
 
        max_c = max(int(reverted_cls.max()) + 1, 256) if reverted_cls.size else 256
        color_lut = np.full((max_c, 3), 128, dtype=np.uint8)
        for c_code, entry in palette.items():
            idx = int(c_code)
            if 0 <= idx < max_c:
                color_lut[idx] = (entry.get("color", (128, 128, 128))
                                  if entry.get("show", True) else (0, 0, 0))
 
        rgb_ptr[local_indices] = color_lut[
            reverted_cls.clip(0, max_c - 1).astype(np.intp)]
 
        vtk_ca = getattr(actor, "_naksha_vtk_array", None)
        if vtk_ca is not None:
            vtk_ca.Modified()
 
    # ── 6. Full VTK dirty chain ───────────────────────────────────────────────
    # All four levels required: GetPointData + mesh + mapper + actor.
    # Without this, VTK's pipeline timestamp comparison sees no change
    # and skips the GPU re-upload entirely.
    _mark_actor_dirty(actor)  ##
 
 
# ─────────────────────────────────────────────────────────────────────────────
# ACTOR LOOKUP HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def is_unified_actor_ready(app) -> bool:
    return _get_unified_actor(app) is not None
 
 
def _get_unified_actor(app) -> Optional[object]:
    actor = getattr(app, "_unified_actor", None)
    if actor is not None:
        rgb = getattr(actor, "_naksha_rgb_ptr", None)
        if rgb is not None and _is_writable(rgb):
            return actor
 
    plotter = getattr(app, "vtk_widget", None)
    if plotter is None:
        return None
 
    if UNIFIED_ACTOR_NAME in plotter.actors:
        actor = plotter.actors[UNIFIED_ACTOR_NAME]
        rgb   = getattr(actor, "_naksha_rgb_ptr", None)
        if rgb is not None and _is_writable(rgb):
            app._unified_actor = actor
            return actor
 
    return None
 
 
def _get_all_unified_actors(app):
    main_actor = _get_unified_actor(app)
    vtk_widget = getattr(app, "vtk_widget", None)
    if main_actor is not None and vtk_widget is not None:
        yield (main_actor, 0, getattr(app, "_main_global_indices", None), vtk_widget)
 
    if hasattr(app, "section_vtks"):
        for view_idx, widget in app.section_vtks.items():
            actor_name = f"_section_{view_idx}_unified"
            if actor_name in widget.actors:
                actor = widget.actors[actor_name]
                rgb   = getattr(actor, "_naksha_rgb_ptr", None)
                if rgb is not None and _is_writable(rgb):
                    gi = getattr(app, f"_section_{view_idx}_global_indices", None)
                    yield (actor, view_idx + 1, gi, widget)
 
 
def _get_slot_palette(app, slot_idx: int) -> dict:
    """
    Get palette for a slot, with proper inheritance from main palette.
    
    FIXED: Always inherits from master palette, even for new sections.
    This ensures new cross-sections get current colors, not defaults.
    """
    master = getattr(app, "class_palette", {}) or {}
    
    # If master is empty, return empty (no data loaded)
    if not master:
        return {}
 
    overrides = {}
    dlg = getattr(app, "display_mode_dialog", None)
    if dlg and hasattr(dlg, "view_palettes"):
        vp = getattr(dlg, "view_palettes", None)
        if vp and slot_idx in vp:
            overrides = vp[slot_idx] or {}
    
    if not overrides:
        vp = getattr(app, "view_palettes", {})
        overrides = vp.get(slot_idx, {}) or {}
 
    # Main view (slot 0) - just return master
    if slot_idx == 0:
        return master
 
    # ═══════════════════════════════════════════════════════════════════
    # PERFORMANCE FIX: Start with FULL copy of master palette
    # This ensures new sections inherit all colors even if no overrides
    # ═══════════════════════════════════════════════════════════════════
    resolved_palette = {code: dict(info) for code, info in master.items()}
    
    # Apply view-specific overrides on top
    for code, info in overrides.items():
        if code in resolved_palette:
            resolved_palette[code].update(info)
        else:
            resolved_palette[code] = dict(info)
 
    return resolved_palette
 
 
def invalidate_unified_actor(app):
    if hasattr(app, "_unified_actor"):
        del app._unified_actor
    for key in list(_lut_cache.keys()):
        _lut_cache[key]._palette_id = None
    print("   🗑️ Unified actor cache invalidated")
 
 
def _ensure_opengl_polydata_mapper(actor, cloud, use_spheres=True):
    if actor is None:
        return
    raw_mapper = actor.GetMapper()
    if hasattr(raw_mapper, 'GetMapper'):
        raw_mapper = raw_mapper.GetMapper()
    if not hasattr(raw_mapper, 'MapDataArrayToVertexAttribute'):
        new_mapper = vtk.vtkOpenGLPolyDataMapper()
        new_mapper.SetInputData(cloud)
        new_mapper.SetScalarModeToUsePointFieldData()
        new_mapper.SelectColorArray("RGB")
        new_mapper.SetScalarVisibility(raw_mapper.GetScalarVisibility())
        actor.SetMapper(new_mapper)
        print("      ℹ️ Swapped vtkDataSetMapper → vtkOpenGLPolyDataMapper")
 
 
def compute_point_size(weight: float, base: float = _BASE_POINT_SIZE) -> float:
    min_size = max(0.5, base * 0.1)
    return float(max(min_size, min(base * weight, 30.0)))
 
 
def diagnose_weight_pipeline(app, slot_idx=1):
    print("\n" + "=" * 70)
    print(f"🔬 WEIGHT PIPELINE DIAGNOSTIC  (slot={slot_idx})")
    print("=" * 70)
 
    if slot_idx == 0:
        actor_name = UNIFIED_ACTOR_NAME
        vtk_widget = getattr(app, "vtk_widget", None)
    else:
        view_idx   = slot_idx - 1
        actor_name = f"_section_{view_idx}_unified"
        vtk_widget = (app.section_vtks.get(view_idx)
                      if hasattr(app, "section_vtks") else None)
 
    print(f"\n[1] Actor: {actor_name}")
    if vtk_widget is None:
        print("    ❌ No vtk_widget"); return
 
    actor = vtk_widget.actors.get(actor_name) if hasattr(vtk_widget, 'actors') else None
    if actor is None:
        print("    ❌ Actor not found"); return
 
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    print(f"\n[2] shader_ctx: {'✅' if ctx else '❌ None'}")
    if ctx:
        print(f"    _has_vertex_attr_cache:  {ctx._has_vertex_attr_cache}")
        print(f"    _naksha_base_point_size: {getattr(actor, '_naksha_base_point_size', '?')}")
        for c in [2, 6, 7]:
            print(f"    class {c}: weight_lut={ctx.weight_lut[c]:.2f}  "
                  f"vis={ctx.visibility_mask[c]:.1f}")
 
    sp = actor.GetShaderProperty() if actor else None
    print(f"\n[3] ShaderProperty: {'✅' if sp else '❌'}")
    if sp:
        v_uni = sp.GetVertexCustomUniforms()
        f_uni = sp.GetFragmentCustomUniforms()
        print(f"    VertexCustomUniforms:   {'✅' if v_uni else '❌'}")
        print(f"    FragmentCustomUniforms: {'✅' if f_uni else '❌'}")
        print(f"    _shaders_finalized_v6:  {getattr(actor, '_shaders_finalized_v6', False)}")
 
    print(f"\n[4] render_window: {getattr(actor, '_naksha_render_window', None)}")
    print("=" * 70 + "\n")