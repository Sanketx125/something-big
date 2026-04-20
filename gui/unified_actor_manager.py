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
_BASE_POINT_SIZE = 2.5
_BORDER_GROWTH_SCALE_PX = 4.0
_BORDER_GROWTH_CUBIC_PX = 8.0
_MAX_BORDER_GROWTH_PX = 3.0
_BORDER_DEPTH_BIAS = 0.001
# Fixed pixel-width for structured (object-edge) borders — stays constant at any zoom
_STRUCTURED_BORDER_PX = 2.0
 
 
# ─────────────────────────────────────────────────────────────────────────────
# VIEW SHADER CONTEXT
# ─────────────────────────────────────────────────────────────────────────────
class ViewShaderContext:
    __slots__ = (
        "slot_idx", "visibility_mask", "weight_lut", "color_lut",
        "border_ring", "_fingerprint", "_observer_id", "_generation",
        "_has_vertex_attr_cache",
        "_vis_list_cache", "_wt_list_cache", "structured_border_mode",
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
        self.structured_border_mode = 0.0
 
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
        ctx.structured_border_mode  = self.structured_border_mode
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
    """
    mesh = getattr(actor, '_naksha_mesh', None)
    if mesh is None:
        return
    mesh.GetPointData().Modified()
    mesh.Modified()
    mapper = actor.GetMapper()
    if mapper is not None:
        mapper.Modified()
    actor.Modified()
 
 
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
            ring_frac = min(0.25, ring_val * 0.5)
            inner     = 1.0 - ring_frac
            frag_code = (
                "//VTK::Color::Impl\n"
                "// Naksha per-class fallback border (round-circle)\n"
                "float r_pc = length(gl_PointCoord.xy - vec2(0.5)) * 2.0;\n"
                "if (r_pc > 1.0) discard;\n"
                f"if (r_pc >= {inner:.6f}) {{\n"
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
        ctx.load_from_palette(palette, float(ctx.border_ring * 100.0), base_point_size)
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
# GL_PROGRAM_POINT_SIZE — persistent observer helpers
# ─────────────────────────────────────────────────────────────────────────────

def _try_enable_program_point_size(render_window) -> bool:
    """
    Enable GL_PROGRAM_POINT_SIZE (0x8642) so vertex shaders can write gl_PointSize.

    This must be called AFTER the OpenGL context is initialized (i.e. after at
    least one render).  Returns True if the state object was available and the
    call succeeded.
    """
    if render_window is None:
        return False
    try:
        if hasattr(render_window, 'GetState'):
            state = render_window.GetState()
            if state and hasattr(state, 'vtkglEnable'):
                state.vtkglEnable(0x8642)          # GL_PROGRAM_POINT_SIZE
                return True
    except Exception as e:
        print(f"      ⚠️ GL_PROGRAM_POINT_SIZE enable: {e}")
    return False


def _install_program_point_size_observer(actor, render_window) -> bool:
    """
    Install a StartEvent observer on the render window so that
    GL_PROGRAM_POINT_SIZE is re-enabled before EVERY draw call.

    VTK's state machine can reset GL flags between renders.  This observer
    is the only guaranteed way to keep the flag set persistently.

    Safe to call multiple times — the guard flag prevents duplicate observers.
    """
    if render_window is None or getattr(actor, '_naksha_pps_observer_installed', False):
        return getattr(actor, '_naksha_pps_observer_installed', False)

    def _pps_start_event(caller, event):
        try:
            state = caller.GetState()
            if state and hasattr(state, 'vtkglEnable'):
                state.vtkglEnable(0x8642)
        except Exception:
            pass

    try:
        obs_id = render_window.AddObserver('StartEvent', _pps_start_event)
        actor._naksha_pps_observer_installed = True
        actor._naksha_pps_observer_id        = obs_id
        print("      ✅ GL_PROGRAM_POINT_SIZE StartEvent observer installed")
        return True
    except Exception as e:
        print(f"      ⚠️ PPS observer install failed: {e}")
        return False


def _deferred_actor_gpu_init(actor, ctx, plotter, label: str = "actor"):
    """
    Called via QTimer.singleShot(~500 ms) after build_unified_actor /
    build_section_unified_actor.

    By the time this fires the VTK window has rendered at least once, so
    GetState() is guaranteed to return a valid OpenGL state object.  We:

      1. Enable GL_PROGRAM_POINT_SIZE immediately (one-shot).
      2. Install the persistent StartEvent observer so it stays enabled.
      3. Re-push all GPU uniforms (weight_lut, visibility_lut, border_ring_val).
      4. Trigger one more render so the updated point sizes appear.

    Without this step, weight changes made right after the file loads have no
    visual effect because gl_PointSize writes are silently ignored by the GPU
    until GL_PROGRAM_POINT_SIZE is set.
    """
    try:
        rw = getattr(actor, '_naksha_render_window', None)
        if rw is None:
            # Try to fetch from plotter
            try:
                rw = plotter.render_window
                actor._naksha_render_window = rw
            except Exception:
                pass

        enabled = _try_enable_program_point_size(rw)
        _install_program_point_size_observer(actor, rw)

        if enabled:
            actor._naksha_needs_program_point_size = False
            print(f"      ✅ Deferred GPU init: GL_PROGRAM_POINT_SIZE enabled for {label}")
        else:
            print(f"      ⚠️ Deferred GPU init: GL state still unavailable for {label}")

        # Re-push uniforms now that the flag is active
        _push_uniforms_direct(actor, ctx)

        try:
            plotter.render()
        except Exception:
            pass

    except Exception as e:
        print(f"      ⚠️ _deferred_actor_gpu_init ({label}): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# CORE: PUSH UNIFORMS DIRECT
# ─────────────────────────────────────────────────────────────────────────────
def _push_uniforms_direct(actor, ctx: 'ViewShaderContext') -> bool:
    if actor is None or ctx is None:
        return False
    try:
        rw = getattr(actor, '_naksha_render_window', None)

        # ── GL_PROGRAM_POINT_SIZE ─────────────────────────────────────────────
        # Always attempt to enable when we push uniforms.
        # If the observer is already installed it costs nothing; if not yet
        # installed (first push before deferred init fires) we try anyway.
        # This is the critical fix: previously it only tried once and gave up
        # if the state wasn't ready, leaving gl_PointSize writes ignored.
        if rw:
            if not getattr(actor, '_naksha_pps_observer_installed', False):
                # Observer not yet installed — try to enable immediately and
                # install observer so it persists across future renders.
                if _try_enable_program_point_size(rw):
                    _install_program_point_size_observer(actor, rw)
                    actor._naksha_needs_program_point_size = False
                    print("      ✅ GL_PROGRAM_POINT_SIZE enabled via _push_uniforms_direct")
                else:
                    # State not ready yet — mark for retry by deferred init.
                    actor._naksha_needs_program_point_size = True
            else:
                # Observer installed — GL state maintained by observer; clear flag.
                actor._naksha_needs_program_point_size = False

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
                v_uni.SetUniformf("structured_border_mode", float(getattr(ctx, 'structured_border_mode', 0.0)))
                v_uni.Modified()
                sp.Modified()
 
        f_uni = sp.GetFragmentCustomUniforms()
        if f_uni:
            f_uni.SetUniformf("border_ring_val", float(ctx.border_ring))
            f_uni.SetUniformf("structured_border_mode", float(getattr(ctx, 'structured_border_mode', 0.0)))
 
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
        raw_m.MapDataArrayToVertexAttribute(
            "boundary_flag", "BoundaryFlag",
            vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, -1
        )
        vertex_attr_wired = True
        print(f"      🔗 Linked 'Classification' + 'BoundaryFlag' to shader")
    except Exception as e:
        print(f"      ⚠️ Shader Attribute Mapping failed: {e}")
 
    ctx._has_vertex_attr_cache = vertex_attr_wired
    actor.GetProperty().SetRenderPointsAsSpheres(False)
 
    sp = actor.GetShaderProperty()
 
    if not hasattr(actor, "_shaders_finalized_v26"):
        sp.ClearAllVertexShaderReplacements()
        sp.ClearAllFragmentShaderReplacements()

        sp.AddVertexShaderReplacement(
            "//VTK::PositionVC::Dec", True,
            "//VTK::PositionVC::Dec\n"
            "in  float class_code;\n"
            "in  float boundary_flag;\n"
            "out float v_point_size;\n"
            "out float v_core_size;\n"
            "out float v_boundary;\n",
            False
        )

        sp.AddVertexShaderReplacement(
            "//VTK::PositionVC::Impl", True,
            "//VTK::PositionVC::Impl\n"
            "{\n"
            "  int c_idx = clamp(int(class_code + 0.5), 0, 255);\n"
            "  v_boundary = boundary_flag;\n"
            "  if (visibility_lut[c_idx] <= 0.0) {\n"
            "    gl_Position  = vec4(2.0, 2.0, 2.0, 1.0);\n"
            "    gl_PointSize = 0.0;\n"
            "    v_point_size = 0.0;\n"
            "    v_core_size  = 0.0;\n"
            "  } else {\n"
            "    float ps = max(1.0, weight_lut[c_idx]);\n"
            "    if (structured_border_mode > 0.5) {\n"
            "      // Structured mode: only boundary points grow, and growth\n"
            "      // is driven by border_ring_val so the % slider is live.\n"
            f"      float border_growth = (boundary_flag > 0.5)\n"
            f"        ? clamp(\n"
            f"            (border_ring_val * {_BORDER_GROWTH_SCALE_PX:.1f})\n"
            f"            + (border_ring_val * border_ring_val * border_ring_val * {_BORDER_GROWTH_CUBIC_PX:.1f}),\n"
            f"            0.0, {_MAX_BORDER_GROWTH_PX:.1f}\n"
            f"          )\n"
            "        : 0.0;\n"
            "      float total_ps = ps + border_growth;\n"
            "      gl_PointSize = total_ps;\n"
            "      v_point_size = total_ps;\n"
            "      v_core_size  = ps;\n"
            "    } else {\n"
            f"      float border_growth = clamp((border_ring_val * {_BORDER_GROWTH_SCALE_PX:.1f}) + (border_ring_val * border_ring_val * border_ring_val * {_BORDER_GROWTH_CUBIC_PX:.1f}), 0.0, {_MAX_BORDER_GROWTH_PX:.1f});\n"
            "      float total_ps = ps + border_growth;\n"
            "      gl_PointSize = total_ps;\n"
            "      v_point_size = total_ps;\n"
            "      v_core_size  = ps;\n"
            "    }\n"
            "  }\n"
            "}\n",
            False
        )

        sp.AddFragmentShaderReplacement(
            "//VTK::Color::Dec", True,
            "//VTK::Color::Dec\n"
            "in float v_point_size;\n"
            "in float v_core_size;\n"
            "in float v_boundary;\n",
            False
        )
        sp.AddFragmentShaderReplacement(
            "//VTK::Color::Impl", True,
            "//VTK::Color::Impl\n"
            "vec2  uv25    = gl_PointCoord.xy - vec2(0.5);\n"
            "float dist_px = length(uv25) * v_point_size;\n"
            "if (dist_px > v_point_size * 0.5) discard;\n"
            "\n"
            "if (border_ring_val > 0.001) {\n"
            "  if (structured_border_mode > 0.5) {\n"
            "    if (v_boundary > 0.5) {\n"
            "      // boundary point: draw black ring outside core radius\n"
            "      if (dist_px >= v_core_size * 0.5) {\n"
            "        diffuseColor = vec3(0.0);\n"
            "        ambientColor = vec3(0.0);\n"
            f"        gl_FragDepth = clamp(gl_FragCoord.z + {_BORDER_DEPTH_BIAS:.4f}, 0.0, 1.0);\n"
            "      } else {\n"
            "        gl_FragDepth = gl_FragCoord.z;\n"
            "      }\n"
            "    } else {\n"
            "      // interior point: no ring at all\n"
            "      gl_FragDepth = gl_FragCoord.z;\n"
            "    }\n"
            "  } else {\n"
            "    if (dist_px >= v_core_size * 0.5) {\n"
            "      diffuseColor = vec3(0.0);\n"
            "      ambientColor = vec3(0.0);\n"
            f"      gl_FragDepth = clamp(gl_FragCoord.z + {_BORDER_DEPTH_BIAS:.4f}, 0.0, 1.0);\n"
            "    } else {\n"
            "      gl_FragDepth = gl_FragCoord.z;\n"
            "    }\n"
            "  }\n"
            "} else {\n"
            "  gl_FragDepth = gl_FragCoord.z;\n"
            "}\n"
            "opacity = 1.0;\n",
            False
        )
        actor._shaders_finalized_v25 = True
        actor._shaders_finalized_v26 = True
        print(f"      ✅ GPU Shader v26 (structured border respects slider): {actor_name}")
 
    # Mark that GL_PROGRAM_POINT_SIZE needs to be enabled (deferred until after
    # first render when the OpenGL context is guaranteed to be initialised).
    actor._naksha_needs_program_point_size = True
    actor.GetProperty().Modified()
    _push_uniforms_direct(actor, ctx)


# ─────────────────────────────────────────────────────────────────────────────
# sync_palette_to_gpu — called by Display Mode dialog Apply
# ─────────────────────────────────────────────────────────────────────────────
def sync_palette_to_gpu(app, slot_idx: int = 0, palette: Optional[dict] = None,
                        border: Optional[float] = None, render: bool = True, **kwargs):
    t0 = time.perf_counter()
 
    border_explicitly_provided = (border is not None)
    if border is None:
        kw_border = kwargs.get('border_percent', None)
        if kw_border is not None:
            border = float(kw_border)
            border_explicitly_provided = True
        else:
            border = 0.0

    if not border_explicitly_provided and float(border) <= 0.0 and slot_idx == 0:
        _ua = getattr(app, '_unified_actor', None)
        _uc = getattr(_ua, '_naksha_shader_ctx', None) if _ua else None
        if _uc is not None and float(_uc.border_ring) > 0.0:
            border = float(_uc.border_ring) * 100.0
        elif float(getattr(app, 'point_border_percent', 0) or 0.0) > 0.0:
            border = float(app.point_border_percent)
 
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

    palette = palette or _get_slot_palette(app, slot_idx)

    if 1 <= slot_idx <= 4:
        if not hasattr(app, 'view_borders'):
            app.view_borders = {}
        # ── AUTHORITATIVE BORDER SOURCE ──────────────────────────────
        # app.view_borders is set ONLY by the Display Mode dialog
        # (on_apply / increase_border / decrease_border).
        # NEVER overwrite it from a caller value — auto-display code
        # can accidentally pass app.point_border_percent (main view).
        if slot_idx in app.view_borders:
            border = float(app.view_borders[slot_idx])
        elif border_explicitly_provided:
            app.view_borders[slot_idx] = float(border)
        # ─────────────────────────────────────────────────────────────
        if section_requires_legacy_border_render(app, view_idx, palette, float(border)):

            if hasattr(app, '_refresh_single_section_view'):
                app._refresh_single_section_view(view_idx, float(border))
                return True

    actor = vtk_widget.actors.get(actor_name)
    if actor is None:
        if 1 <= slot_idx <= 4 and hasattr(app, '_refresh_single_section_view'):
            app._refresh_single_section_view(view_idx, float(border))
            return True
        return False
 
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is None:
        ctx = ViewShaderContext(slot_idx)
        _shader_contexts[actor_name] = ctx
        _attach_view_shader_context(actor, ctx, actor_name)
 
    # Fetch structured border mode from dialog/app (if user checked 'Structured' border)
    structured_mode = 0.0
    dialog = getattr(app, 'display_mode_dialog', None) or getattr(app, 'display_dialog', None)
    if dialog and hasattr(dialog, 'border_logic_object'):
        structured_mode = 1.0 if dialog.border_logic_object.isChecked() else 0.0
    ctx.structured_border_mode = structured_mode

    base_point_size = float(getattr(actor, '_naksha_base_point_size', _BASE_POINT_SIZE))
 
    ctx.force_reload()
    ctx.load_from_palette(palette, float(border), base_point_size)
    _push_uniforms_direct(actor, ctx)

    if slot_idx == 0:
        # Remove legacy border actor since the unified shader now handles it natively
        if "_naksha_unified_border" in (getattr(app, "vtk_widget", None) or {}).actors:
            app.vtk_widget.remove_actor("_naksha_unified_border", render=False)
 
    if slot_idx == 0 and float(border) > 0.0:
        app.point_border_percent = float(border)
    elif 1 <= slot_idx <= 5:
        if not hasattr(app, 'view_borders'):
            app.view_borders = {}
        app.view_borders[slot_idx] = float(border)
 
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
            if border <= 0.0:
                _ua = getattr(app, '_unified_actor', None)
                _uc = getattr(_ua, '_naksha_shader_ctx', None) if _ua else None
                if _uc is not None and float(_uc.border_ring) > 0.0:
                    border = float(_uc.border_ring) * 100.0
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

    # Always prefer per-view border from app.view_borders (authoritative source)
    if hasattr(app, 'view_borders') and slot_idx in app.view_borders:
        border_percent = float(app.view_borders[slot_idx])

    if not hasattr(app, 'section_vtks') or view_idx not in app.section_vtks:
        return False
    vtk_widget = app.section_vtks[view_idx]
    if vtk_widget is None:
        return False

    if section_requires_legacy_border_render(app, view_idx, palette, float(border_percent)):
        if hasattr(app, '_refresh_single_section_view'):
            app._refresh_single_section_view(view_idx, float(border_percent))
            return True
        return False
 
    actor_name = f"_section_{view_idx}_unified"
    actor = (vtk_widget.actors.get(actor_name)
             if hasattr(vtk_widget, 'actors') else None)
 
    if actor is None:
        if hasattr(app, '_refresh_single_section_view'):
            app._refresh_single_section_view(view_idx, float(border_percent))
            return True
        return False
 
    rgb_ptr = getattr(actor, '_naksha_rgb_ptr', None)
    if rgb_ptr is None or not _is_writable(rgb_ptr):
        return False
 
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
 
    structured_mode = 0.0
    dialog = getattr(app, 'display_mode_dialog', None) or getattr(app, 'display_dialog', None)
    if dialog and hasattr(dialog, 'border_logic_object'):
        structured_mode = 1.0 if dialog.border_logic_object.isChecked() else 0.0
    ctx.structured_border_mode = structured_mode

    sc = getattr(actor, '_naksha_section_class', None)
    if sc is not None:
        _rewrite_rgb_from_palette(rgb_ptr, sc, palette)
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

    if border_percent <= 0.0:
        if ctx is not None and float(ctx.border_ring) > 0.0:
            border_percent = float(ctx.border_ring) * 100.0
        else:
            border_percent = float(getattr(app, 'point_border_percent', 0) or 0.0)

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

    structured_mode = 0.0
    dialog = getattr(app, 'display_mode_dialog', None) or getattr(app, 'display_dialog', None)
    if dialog and hasattr(dialog, 'border_logic_object'):
        structured_mode = 1.0 if dialog.border_logic_object.isChecked() else 0.0
    ctx.structured_border_mode = structured_mode

    gi        = getattr(app, '_main_global_indices', None)
    vis_class = classification[gi] if gi is not None else classification
    _rewrite_rgb_from_palette(rgb_ptr, vis_class, palette)
 
    vtk_ca.Modified()
    _mark_actor_dirty(actor)
 
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
# SNT OVERLAY Z-OFFSET
# ─────────────────────────────────────────────────────────────────────────────
def _restore_snt_overlays(app):
    if hasattr(app, 'snt_dialog') and app.snt_dialog is not None:
        try:
            app.snt_dialog.restore_snt_actors()  # Already has the fixes above
            return
        except Exception as e:
            print(f"  ⚠️ SNT dialog restore: {e}")

    try:
        from gui.snt_attachment import (
            _get_snt_z_offset, _apply_z_offset_to_actor,
            _snt_enable_gl_point_size, _snt_push_border_uniforms,
        )
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
                    renderer.AddActor(actor)
                    count += 1
                except Exception:
                    pass

    if count > 0:
        # FIX: No clipping range expansion — tight range preserves depth precision.
        renderer.ResetCameraClippingRange()

        # FIX: Enable GL_PROGRAM_POINT_SIZE + push uniforms before render.
        _snt_enable_gl_point_size(app)
        _snt_push_border_uniforms(app)

        print(f"  🔄 SNT overlays: {count} actors restored (z_offset={z_offset:.1f})")
 
  
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

    # ── NEW: boundary flags must be on cloud BEFORE add_points ──
    _bf = _compute_boundary_flags(vis_xyz, vis_class)
    _bf_vtk = numpy_support.numpy_to_vtk(_bf, deep=False)
    _bf_vtk.SetName("BoundaryFlag")
    cloud.GetPointData().AddArray(_bf_vtk)
    print(f"      🔲 BoundaryFlag: {int(_bf.sum()):,}/{len(_bf):,} edge pts")
    # ────────────────────────────────────────────────────────────
 
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
        actor.GetProperty().LightingOff()
 
    if actor:
        try:
            actor._naksha_render_window = plotter.render_window
        except Exception:
            pass

    if actor:
        # ── Immediate GL_PROGRAM_POINT_SIZE attempt ──────────────────────────
        # If the GL context is already warm (file reloaded, not first-ever load),
        # this succeeds right away and the border is visible from the first render.
        # If the context isn't ready yet, _deferred_actor_gpu_init retries below.
        try:
            rw = plotter.render_window
            if _try_enable_program_point_size(rw):
                _install_program_point_size_observer(actor, rw)
                actor._naksha_needs_program_point_size = False
                print("      ✅ GL_PROGRAM_POINT_SIZE enabled immediately (warm context)")
        except Exception:
            pass

        # # ── Deferred GPU init (fallback for cold first-load) ─────────────
        # try:
        #     from PySide6.QtCore import QTimer
        #     _a, _c, _p = actor, ctx, plotter
        #     QTimer.singleShot(
        #         100,   # ← Reduced from 500ms to 100ms — closes the visibility gap
        #         lambda: _deferred_actor_gpu_init(_a, _c, _p, "MainView")
        #     )
        #     print("      ⏱️  Deferred GPU init scheduled (100 ms)")
        # except Exception as _te:
        #     print(f"      ⚠️ Could not schedule deferred init: {_te}")

        _ensure_opengl_polydata_mapper(actor, cloud)
        mesh   = actor.GetMapper().GetInput()
        vtk_ca = mesh.GetPointData().GetScalars()
        actor._naksha_rgb_ptr         = app._rgb_buffer
        actor._naksha_vtk_array       = vtk_ca
        actor._naksha_mesh            = mesh
        actor._naksha_base_point_size = actual_point_size
        # ── NEW ──
        actor._naksha_boundary_vtk = _bf_vtk
        # ─────────
        app._unified_actor            = actor
        ctx = ViewShaderContext(slot_idx=0)

        ctx.load_from_palette(palette, border_percent, actual_point_size)
        
        structured_mode = 0.0
        dialog = getattr(app, 'display_mode_dialog', None) or getattr(app, 'display_dialog', None)
        if dialog and hasattr(dialog, 'border_logic_object'):
            structured_mode = 1.0 if dialog.border_logic_object.isChecked() else 0.0
        ctx.structured_border_mode = structured_mode
        
        _attach_view_shader_context(actor, ctx, UNIFIED_ACTOR_NAME)
        print(f"      ✅ Main view: {len(app._rgb_buffer):,} pts "
              f"(base_size={actual_point_size}, LOD_step={max(1, n_pts//target_points)})")

        # ── Deferred GPU init ─────────────────────────────────────────────────
        # The OpenGL context may not be fully ready at build time (file is loaded
        # before the first render).  Schedule a deferred call that fires AFTER
        # the first render so GetState() returns a valid object and we can:
        #   1. Enable GL_PROGRAM_POINT_SIZE (makes gl_PointSize writes take effect)
        #   2. Install a persistent StartEvent observer so it stays enabled
        #   3. Re-push all uniforms so weight_lut is live from the very first
        #      weight change the user makes — no shortcut / rebuild required.
        try:
            from PySide6.QtCore import QTimer
            # Capture references — closure must not hold 'actor' as a local
            # that could be rebound if build_unified_actor is called again.
            _a, _c, _p = actor, ctx, plotter
            QTimer.singleShot(
                500,
                lambda: _deferred_actor_gpu_init(_a, _c, _p, "MainView")
            )
            print("      ⏱️  Deferred GPU init scheduled (500 ms)")
        except Exception as _te:
            print(f"      ⚠️ Could not schedule deferred init: {_te}")



    elapsed = (time.perf_counter() - t0) * 1000
    print(f"   🏗️ Unified actor built: {n_pts:,} pts in {elapsed:.1f} ms")

    _restore_snt_overlays(app)
    return actor


def _clear_section_visual_actors(vtk_widget, view_idx: int) -> None:
    actor_name = f"_section_{view_idx}_unified"
    actors = getattr(vtk_widget, "actors", {})

    if actor_name in actors:
        vtk_widget.remove_actor(actor_name, render=False)

    for name in list(actors.keys()):
        name_str = str(name)
        if name_str.startswith(("class_", "border_")) or name_str in ("border_layer", "color_layer"):
            vtk_widget.remove_actor(name, render=False)


def _section_draw_sizes(
    weight: float,
    border_percent: float,
    base_point_size: float = _BASE_POINT_SIZE,
) -> tuple[float, float]:
    clamped_weight = max(0.1, min(float(weight or 1.0), 10.0))
    color_size = max(1.0, min(base_point_size * clamped_weight, 15.0))

    if float(border_percent or 0.0) > 0.0:
        border_scale = 1.0 + (float(border_percent) / 60.0)
        border_size = max(1.0, min(color_size * border_scale, 15.0))
    else:
        border_size = color_size

    return color_size, border_size


def section_requires_legacy_border_render(
    app,
    view_idx: int,
    palette: Optional[dict] = None,
    border_percent: float = 0.0,
) -> bool:
    slot_idx = view_idx + 1
    palette = palette or _get_slot_palette(app, slot_idx)

    if border_percent <= 0.0 and hasattr(app, 'view_borders'):
        border_percent = float(app.view_borders.get(slot_idx, 0) or 0.0)

    visible_classes = {
        int(code) for code, info in (palette or {}).items()
        if info.get("show", True)
    }
    recent_class = getattr(app, "_last_classified_to_class", None)
    has_special_order = recent_class is not None and int(recent_class) in visible_classes
    return has_special_order


def build_section_legacy_border_actors(
    app,
    view_idx: int,
    palette: Optional[dict] = None,
    border_percent: float = 0.0,
    point_size: float = _BASE_POINT_SIZE,
) -> bool:
    slot_idx = view_idx + 1

    if not hasattr(app, 'section_vtks') or view_idx not in app.section_vtks:
        return False

    vtk_widget = app.section_vtks[view_idx]
    if vtk_widget is None:
        return False

    core_pts = getattr(app, f"section_{view_idx}_core_points", None)
    buf_pts = getattr(app, f"section_{view_idx}_buffer_points", None)
    core_mask = getattr(app, f"section_{view_idx}_core_mask", None)
    buf_mask = getattr(app, f"section_{view_idx}_buffer_mask", None)

    if core_pts is None or core_mask is None:
        return False

    data = getattr(app, "data", None)
    if data is None or "classification" not in data:
        return False

    classification_full = data["classification"]
    core_global_idx = np.where(core_mask)[0]

    if buf_pts is not None and buf_mask is not None and len(buf_pts) > 0:
        buf_only_mask = buf_mask & ~core_mask
        buf_global_idx = np.where(buf_only_mask)[0]
        all_pts = np.vstack([core_pts, buf_pts])
        all_cls = np.concatenate([
            classification_full[core_global_idx],
            classification_full[buf_global_idx],
        ])
        all_global_idx = np.concatenate([core_global_idx, buf_global_idx])
    else:
        all_pts = core_pts
        all_cls = classification_full[core_global_idx]
        all_global_idx = core_global_idx

    setattr(app, f"_section_{view_idx}_global_indices", all_global_idx)

    palette = palette or _get_slot_palette(app, slot_idx)
    if border_percent <= 0.0 and hasattr(app, 'view_borders'):
        border_percent = float(app.view_borders.get(slot_idx, 0) or 0.0)

    if not hasattr(app, 'view_borders'):
        app.view_borders = {}
    app.view_borders[slot_idx] = float(border_percent)

    visible_classes = [
        int(code) for code, info in (palette or {}).items()
        if info.get("show", True)
    ]

    try:
        cam_pos = vtk_widget.camera_position
    except Exception:
        cam_pos = None

    _clear_section_visual_actors(vtk_widget, view_idx)

    if len(all_pts) == 0 or not visible_classes:
        vtk_widget._naksha_section_render_mode = "legacy"
        if cam_pos is not None:
            try:
                vtk_widget.camera_position = cam_pos
            except Exception:
                pass
        vtk_widget.render()
        return True

    visible_mask = np.isin(all_cls, visible_classes)
    filtered_pts = all_pts[visible_mask]
    filtered_cls = all_cls[visible_mask]

    if len(filtered_pts) == 0:
        vtk_widget._naksha_section_render_mode = "legacy"
        if cam_pos is not None:
            try:
                vtk_widget.camera_position = cam_pos
            except Exception:
                pass
        vtk_widget.render()
        return True

    base_point_size = max(1.0, float(point_size or _BASE_POINT_SIZE))
    recent_class = getattr(app, "_last_classified_to_class", None)
    has_custom_weights = any(
        abs(float(info.get("weight", 1.0)) - 1.0) > 1e-6
        for info in (palette or {}).values()
    )
    use_special_order = recent_class is not None and int(recent_class) in visible_classes

    if has_custom_weights or use_special_order:
        class_weights = []
        for code in visible_classes:
            if use_special_order and int(code) == int(recent_class):
                continue
            weight = float((palette or {}).get(int(code), {}).get("weight", 1.0))
            class_weights.append((int(code), weight))

        class_weights.sort(key=lambda item: item[1], reverse=True)
        render_order = [code for code, _ in class_weights]
        if use_special_order:
            render_order.append(int(recent_class))

        for code in render_order:
            class_mask = (filtered_cls == code)
            if not np.any(class_mask):
                continue

            class_pts = filtered_pts[class_mask]
            entry = (palette or {}).get(int(code), {})
            weight = float(entry.get("weight", 1.0))
            color = np.asarray(entry.get("color", (128, 128, 128)), dtype=np.uint8)
            color_size, border_size = _section_draw_sizes(weight, border_percent, base_point_size)

            if float(border_percent) > 0.0:
                border_cloud = pv.PolyData(class_pts)
                border_cloud["RGB"] = np.zeros((len(class_pts), 3), dtype=np.uint8)
                vtk_widget.add_points(
                    border_cloud,
                    scalars="RGB",
                    rgb=True,
                    point_size=border_size,
                    render_points_as_spheres=True,
                    name=f"border_{code}",
                    reset_camera=False,
                    render=False,
                )

            cloud = pv.PolyData(class_pts)
            cloud["RGB"] = np.tile(color, (len(class_pts), 1)).astype(np.uint8)
            vtk_widget.add_points(
                cloud,
                scalars="RGB",
                rgb=True,
                point_size=color_size,
                render_points_as_spheres=True,
                name=f"class_{code}",
                reset_camera=False,
                render=False,
            )
    else:
        lut_size = max(int(filtered_cls.max()) + 1, 256)
        color_lut = np.full((lut_size, 3), 128, dtype=np.uint8)
        for code, entry in (palette or {}).items():
            idx = int(code)
            if 0 <= idx < lut_size:
                color_lut[idx] = entry.get("color", (128, 128, 128))

        _, border_size = _section_draw_sizes(1.0, border_percent, base_point_size)

        if float(border_percent) > 0.0:
            border_cloud = pv.PolyData(filtered_pts)
            border_cloud["RGB"] = np.zeros((len(filtered_pts), 3), dtype=np.uint8)
            vtk_widget.add_points(
                border_cloud,
                scalars="RGB",
                rgb=True,
                point_size=border_size,
                render_points_as_spheres=True,
                name="border_layer",
                reset_camera=False,
                render=False,
            )

        cloud = pv.PolyData(filtered_pts)
        cloud["RGB"] = color_lut[filtered_cls.astype(np.intp)]
        vtk_widget.add_points(
            cloud,
            scalars="RGB",
            rgb=True,
            point_size=base_point_size,
            render_points_as_spheres=True,
            name="color_layer",
            reset_camera=False,
            render=False,
        )

    vtk_widget._naksha_section_render_mode = "legacy"
    if cam_pos is not None:
        try:
            vtk_widget.camera_position = cam_pos
        except Exception:
            pass
    try:
        vtk_widget.renderer.ResetCameraClippingRange()
    except Exception:
        pass
    vtk_widget.render()

    print(
        f"   Section {view_idx + 1} legacy border render: "
        f"{len(filtered_pts):,} pts (border={border_percent}%)"
    )
    return True
 
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
 
    if hasattr(app, 'view_borders') and slot_idx in app.view_borders:
        border_percent = float(app.view_borders[slot_idx])
 
    actor_name = f"_section_{view_idx}_unified"
    cam_pos    = vtk_widget.camera_position
 
    if actor_name in vtk_widget.actors:
        vtk_widget.remove_actor(actor_name, render=False)
    for name in list(vtk_widget.actors.keys()):
        if str(name).startswith(("class_", "border_")) or str(name) in ("border_layer", "color_layer"):
            vtk_widget.remove_actor(name, render=False)
 
    cloud     = pv.PolyData(all_pts)
    cls_f32   = all_cls.astype(np.float32, copy=False)
    class_vtk = numpy_support.numpy_to_vtk(cls_f32, deep=False)
    class_vtk.SetName("Classification")
    cloud.GetPointData().AddArray(class_vtk)

    # ── NEW ──
    _bf = _compute_boundary_flags(all_pts, all_cls)
    _bf_vtk = numpy_support.numpy_to_vtk(_bf, deep=False)
    _bf_vtk.SetName("BoundaryFlag")
    cloud.GetPointData().AddArray(_bf_vtk)
    # ─────────
 
    rgb_buffer = np.zeros((len(all_pts), 3), dtype=np.uint8)
    lut        = _get_lut(f"section_{view_idx}")
    np.copyto(rgb_buffer, lut.map_classes(all_cls, palette))
 
    rgb_vtk = numpy_support.numpy_to_vtk(rgb_buffer, deep=False)
    rgb_vtk.SetName("RGB")
    cloud.GetPointData().SetScalars(rgb_vtk)
 
    n_pts          = len(all_pts)
    actual_pt_size = max(1.0, float(point_size or _BASE_POINT_SIZE))
 
    actor = vtk_widget.add_points(
        cloud, scalars="RGB", rgb=True,
        point_size=actual_pt_size,
        render_points_as_spheres=False,
        name=actor_name,
        reset_camera=False, render=False,
    )
    if actor:
        actor.GetProperty().LightingOff()
 
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
    # ── NEW ──
    actor._naksha_boundary_vtk = _bf_vtk
    # ─────────
 
    ctx = ViewShaderContext(slot_idx=slot_idx)
    ctx.load_from_palette(palette, border_percent, actual_pt_size)
    _attach_view_shader_context(actor, ctx, actor_name)

    # Deferred GL_PROGRAM_POINT_SIZE init for section views too
    try:
        from PySide6.QtCore import QTimer
        _a, _c, _w = actor, ctx, vtk_widget
        QTimer.singleShot(
            500,
            lambda: _deferred_actor_gpu_init(_a, _c, _w, f"Section{view_idx+1}")
        )
    except Exception:
        pass
 
    vtk_widget._naksha_section_render_mode = "unified"
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
 
    palette = kwargs.get("palette") or _get_slot_palette(app, 0)

    rgb_ptr = getattr(actor, "_naksha_rgb_ptr", None)
    if rgb_ptr is not None:
        entry = palette.get(int(to_class), {})
        new_color = (
            entry.get("color", (128, 128, 128))
            if entry.get("show", True)
            else (0, 0, 0)
        )
        rgb_ptr[local_changed] = new_color
        vtk_ca = getattr(actor, "_naksha_vtk_array", None)
        if vtk_ca is not None:
            vtk_ca.Modified()

 
    mesh = getattr(actor, '_naksha_mesh', None)
    if mesh is not None:
        class_vtk_arr = mesh.GetPointData().GetArray("Classification")
        if class_vtk_arr is not None:
            cls_np = numpy_support.vtk_to_numpy(class_vtk_arr)
            cls_np[local_changed] = np.float32(to_class)
            class_vtk_arr.Modified()
            print(f"   ✅ Main view Classification array updated: "
                  f"{len(local_changed)} pts → class {to_class}")
        else:
            print("   ⚠️  Main view: 'Classification' VTK array not found")
 
    _mark_actor_dirty(actor)
 
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is not None:
        _push_uniforms_direct(actor, ctx)
        actor._last_uniform_generation = ctx._generation
 
    try:
        app.vtk_widget.render()
    except Exception:
        pass
    
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
    t0 = time.perf_counter()
 
    if not hasattr(app, "section_vtks") or view_idx not in app.section_vtks:
        return False
 
    vtk_widget     = app.section_vtks[view_idx]
    slot_idx       = view_idx + 1
    palette        = palette or _get_slot_palette(app, slot_idx)
    if not palette:
        return False

    border_percent = float(getattr(app, "view_borders", {}).get(slot_idx, 0) or 0.0)
    if section_requires_legacy_border_render(app, view_idx, palette, border_percent):
        if hasattr(app, '_refresh_single_section_view'):
            app._refresh_single_section_view(view_idx, border_percent)
            return True
        return False
 
    actor_name     = f"_section_{view_idx}_unified"
    global_indices = getattr(app, f"_section_{view_idx}_global_indices", None)
 
    if actor_name not in vtk_widget.actors or global_indices is None:
        if hasattr(app, '_refresh_single_section_view'):
            app._refresh_single_section_view(view_idx, border_percent)
            return True
        return False
 
    actor = vtk_widget.actors.get(actor_name)
    if actor is None:
        if hasattr(app, '_refresh_single_section_view'):
            app._refresh_single_section_view(view_idx, border_percent)
            return True
        return False
 
    rgb_ptr = getattr(actor, "_naksha_rgb_ptr", None)
    if rgb_ptr is None or not _is_writable(rgb_ptr):
        return False
 
    classification = (app.data.get("classification")
                      if hasattr(app, 'data') and app.data else None)
    if classification is None:
        return False
 
    mapper = actor.GetMapper()
    poly   = mapper.GetInput() if mapper else None
    if poly is None:
        return False
 
    vtk_scalars = poly.GetPointData().GetScalars()
    if vtk_scalars is None:
        return False
 
    if (changed_mask_global is not None
            and len(changed_mask_global) >= global_indices.max(initial=0) + 1):
        section_changed = changed_mask_global[global_indices]
    else:
        section_changed = np.ones(len(global_indices), dtype=bool)
 
    n_changed = int(np.count_nonzero(section_changed))
 
    if n_changed > 0:
        changed_idx = np.where(section_changed)[0]
        new_classes = classification[global_indices[changed_idx]]
 
        max_c     = max(int(new_classes.max()) + 1, 256)
        color_lut = np.full((max_c, 3), 128, dtype=np.uint8)
        for c_code, entry in palette.items():
            idx = int(c_code)
            if 0 <= idx < max_c:
                color_lut[idx] = (entry.get("color", (128, 128, 128))
                                  if entry.get("show", True) else (0, 0, 0))
        rgb_ptr[changed_idx] = color_lut[new_classes.clip(0, max_c - 1).astype(np.intp)]
 
        class_vtk_arr = poly.GetPointData().GetArray("Classification")
        if class_vtk_arr is not None:
            cls_np = numpy_support.vtk_to_numpy(class_vtk_arr)
            cls_np[changed_idx] = new_classes.astype(np.float32)
            class_vtk_arr.Modified()
            print(f"   ✅ Classification VTK array updated: "
                  f"{n_changed} pts → class {np.unique(new_classes).tolist()}")
        else:
            print("   ⚠️  'Classification' VTK array not found on poly")
 
        if hasattr(actor, "_naksha_section_class"):
            actor._naksha_section_class[changed_idx] = new_classes
 
        vtk_scalars.Modified()
        _mark_actor_dirty(actor)
 
    ctx = getattr(actor, '_naksha_shader_ctx', None)
    if ctx is not None:
        _last_gen = getattr(actor, '_last_uniform_generation', -1)
        if ctx._generation != _last_gen:
            _push_uniforms_direct(actor, ctx)
            actor._last_uniform_generation = ctx._generation
    else:
        print("   ⚠️  No shader context on actor — uniforms not pushed")
 
    if not skip_render:
        try:
            vtk_widget.render()
        except Exception:
            pass
        app._gpu_sync_done = True
    
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"   ⚡ Section {view_idx + 1} RGB inject: {n_changed} pts [{elapsed:.1f} ms]")
    return True
 
 
def fast_undo_update(app, changed_mask: np.ndarray, **kwargs) -> bool:
    t0 = time.perf_counter()
    actors_updated = 0
    total_pts = 0
 
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
 
    if not (hasattr(app, 'section_vtks') and app.section_vtks):
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"   ⚡ fast_undo_update: {total_pts:,} pts across "
              f"{actors_updated} views [{elapsed:.1f} ms]")
        return actors_updated > 0
 
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
            continue
        _patch_actor_memory(app, sec_actor, local_sec_changed, slot_idx=view_idx + 1)
        sections_to_render.append((view_idx, vtk_widget, local_sec_changed.size))
        actors_updated += 1
        total_pts += local_sec_changed.size

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
    full_cls = app.data["classification"]
 
    if slot_idx == 0:
        gi = getattr(app, '_main_global_indices', None)
        if gi is not None:
            reverted_cls = full_cls[gi[local_indices]]
        else:
            reverted_cls = full_cls[local_indices]
    else:
        view_idx = slot_idx - 1
        gi_section = getattr(app, f'_section_{view_idx}_global_indices', None)
        if gi_section is None:
            return
        reverted_cls = full_cls[gi_section[local_indices]]
 
    if hasattr(actor, "_naksha_section_class"):
        actor._naksha_section_class[local_indices] = reverted_cls
 
    mesh = getattr(actor, '_naksha_mesh', None)
    if mesh is not None:
        class_vtk = mesh.GetPointData().GetArray("Classification")
        if class_vtk is not None:
            numpy_support.vtk_to_numpy(class_vtk)[local_indices] = (
                reverted_cls.astype(np.float32))
            class_vtk.Modified()
 
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
 
    _mark_actor_dirty(actor)
 
 
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
 
 
# def _get_slot_palette(app, slot_idx: int) -> dict:
#     master = getattr(app, "class_palette", {}) or {}
    
#     if not master:
#         return {}
 
#     overrides = {}
#     dlg = getattr(app, "display_mode_dialog", None)
#     if dlg and hasattr(dlg, "view_palettes"):
#         vp = getattr(dlg, "view_palettes", None)
#         if vp and slot_idx in vp:
#             overrides = vp[slot_idx] or {}
    
#     if not overrides:
#         vp = getattr(app, "view_palettes", {})
#         overrides = vp.get(slot_idx, {}) or {}
 
#     if slot_idx == 0:
#         return master
 
#     resolved_palette = {code: dict(info) for code, info in master.items()}
    
#     for code, info in overrides.items():
#         if code in resolved_palette:
#             resolved_palette[code].update(info)
#         else:
#             resolved_palette[code] = dict(info)
 
#     return resolved_palette
def _get_slot_palette(app, slot_idx: int) -> dict:
    master = getattr(app, "class_palette", {}) or {}
    
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
 
    if slot_idx == 0:
        # FIX: apply slot 0 Display Mode overrides (show flags) for main view.
        # Previously returned raw master — hidden classes showed their color.
        if not overrides:
            return master
        resolved_slot0 = {code: dict(info) for code, info in master.items()}
        for code, info in overrides.items():
            if code in resolved_slot0:
                resolved_slot0[code].update(info)
            else:
                resolved_slot0[code] = dict(info)
        return resolved_slot0
    resolved_palette = {code: dict(info) for code, info in master.items()}
    
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
 
def _compute_boundary_flags(xyz: np.ndarray, classification: np.ndarray = None,
                             resolution: float = 0.0) -> np.ndarray:
    """
    Computes per-point structural boundary flags using three criteria:
      1. Height discontinuity  — main structural edge detector (roof→ground drop)
      2. Class-change          — only when neighbour cell is OCCUPIED + different class
      3. Scan-edge             — point has < 4 of 8 occupied neighbours (true cloud edge)

    KEY FIX vs old version: empty neighbour cells (nb == -1) are NO LONGER
    treated as boundary. This was the root cause of dark-roof artefacts in
    structured border mode — interior roof points with scan gaps in their
    neighbourhood were wrongly flagged.
    """
    n = len(xyz)
    if n == 0:
        return np.zeros(0, dtype=np.float32)

    xy    = xyz[:, :2]
    z_arr = xyz[:, 2].astype(np.float64)

    xy_min = xy.min(axis=0)
    xy_max = xy.max(axis=0)

    if resolution <= 0.0:
        w     = max(float(xy_max[0] - xy_min[0]), 1.0)
        h_dim = max(float(xy_max[1] - xy_min[1]), 1.0)
        resolution = max(0.05, np.sqrt(w * h_dim / n) * 1.5)

    gc = ((xy - xy_min) / resolution).astype(np.int32) + 1
    gx, gy   = gc[:, 0], gc[:, 1]
    gx_max   = int(gx.max()) + 2
    gy_max   = int(gy.max()) + 2

    # ── Build Z-mean grid ────────────────────────────────────────────────────
    z_sum   = np.zeros((gx_max, gy_max), dtype=np.float64)
    z_count = np.zeros((gx_max, gy_max), dtype=np.int32)
    np.add.at(z_sum,   (gx, gy), z_arr)
    np.add.at(z_count, (gx, gy), 1)
    # Use 0.0 for empty cells — we gate all comparisons on nb_occ anyway
    z_mean = np.where(z_count > 0, z_sum / np.maximum(z_count, 1), 0.0)

    # Mean Z of THIS point's own cell (always valid — point is in the cell)
    my_z_cell = z_mean[gx, gy]

    # Adaptive Z threshold: structural edge = height change > 3% of total
    # Z range, minimum 0.5 m (handles both dense urban and sparse rural scenes)
    z_global_range = max(float(z_arr.max() - z_arr.min()), 1.0)
    z_thresh = max(0.5, z_global_range * 0.03)

    # ── Class grid ───────────────────────────────────────────────────────────
    has_class = classification is not None
    if has_class:
        class_grid = np.full((gx_max, gy_max), -1, dtype=np.int32)
        class_grid[gx, gy] = classification.astype(np.int32)
        my_class = classification.astype(np.int32)

    # ── Boundary accumulation over 8 neighbours ──────────────────────────────
    _DIRS = [(-1, -1), (-1, 0), (-1, 1),
             ( 0, -1),          ( 0, 1),
             ( 1, -1), ( 1, 0), ( 1, 1)]

    boundary     = np.zeros(n, dtype=bool)
    occ_nb_count = np.zeros(n, dtype=np.int32)

    for dx, dy in _DIRS:
        nx, ny = gx + dx, gy + dy
        nb_occ = (z_count[nx, ny] > 0)          # True if neighbour cell has points
        occ_nb_count += nb_occ.astype(np.int32)

        # ── Criterion 1: height discontinuity (geometric/structural edge) ────
        # Only compare against OCCUPIED neighbours to avoid gap-based false flags
        nb_z   = z_mean[nx, ny]
        z_diff = np.where(nb_occ, np.abs(my_z_cell - nb_z), 0.0)
        boundary |= nb_occ & (z_diff > z_thresh)

        # ── Criterion 2: class-change boundary ───────────────────────────────
        # Neighbour must be OCCUPIED and a different class — empty ≠ boundary
        if has_class:
            nb_cls = class_grid[nx, ny]
            boundary |= nb_occ & (nb_cls >= 0) & (nb_cls != my_class)

    # ── Criterion 3: scan/cloud edge ─────────────────────────────────────────
    # A point with < 4 occupied 8-neighbours is genuinely at the edge of the
    # scan (not a gap — a real spatial boundary).  This replaces the old
    # "empty neighbour = boundary" logic with a majority-vote approach that
    # is robust against irregular point spacing on roof interiors.
    boundary |= (occ_nb_count < 4)

    pct = int(boundary.sum()) * 100 // max(n, 1)
    print(f"      🔲 BoundaryFlag: {int(boundary.sum()):,}/{n:,} edge pts "
          f"({pct}%, z_thresh={z_thresh:.2f}m, res={resolution:.3f}m)")

    return boundary.astype(np.float32)
 
 
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
        print(f"    _naksha_pps_observer_installed: {getattr(actor, '_naksha_pps_observer_installed', False)}")
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
        print(f"    _shaders_finalized_v23:  {getattr(actor, '_shaders_finalized_v23', False)}")
 
    print(f"\n[4] render_window: {getattr(actor, '_naksha_render_window', None)}")
    print("=" * 70 + "\n")