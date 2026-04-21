from __future__ import annotations
import math
import os
import struct
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from PySide6.QtCore import (
    QCoreApplication, Qt, QThread, Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog,
    QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QRadioButton, QScrollArea,
    QVBoxLayout, QWidget, QProgressDialog,
)

from gui.theme_manager import (
    get_dialog_stylesheet, get_progress_dialog_stylesheet,
    get_title_banner_style, get_file_item_row_style,
    get_badge_style, get_icon_button_style, get_notice_banner_style, ThemeColors,
)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

_LEGACY_MAGIC_V0: bytes = b"SNT\x00"
_LEGACY_MAGIC_V1: bytes = b"SNT\x01"

_LEGACY_ETYPE_POLYLINE: int = 0
_LEGACY_ETYPE_TEXT:     int = 1
_LEGACY_ETYPE_3DFACE:   int = 2

_DEFAULT_COLOR: Tuple[int, int, int] = (0, 255, 200)

_LAYER_COLOR_CYCLE: List[Tuple[int, int, int]] = [
    (  0, 255,  80),
    (  0, 220, 255),
    (255, 220,  50),
    (255,  80, 100),
    (200, 130, 255),
    (255, 160,  60),
    (100, 255, 150),
]

_ACI_RGB: Dict[int, Tuple[int, int, int]] = {
      1: (255,   0,   0),    2: (255, 255,   0),    3: (  0, 255,   0),
      4: (  0, 255, 255),    5: (  0,   0, 255),    6: (255,   0, 255),
      7: (255, 255, 255),    8: (128, 128, 128),    9: (192, 192, 192),
     10: (255,   0,   0),   20: (255, 127,   0),   30: (255, 191,   0),
     40: (255, 255,   0),   50: (127, 255,   0),   60: (  0, 255,   0),
     70: (  0, 255, 127),   80: (  0, 255, 255),   90: (  0, 127, 255),
    100: (  0,   0, 255),  110: (127,   0, 255),  120: (255,   0, 255),
    130: (255,   0, 127),  140: (255, 127, 127),  150: (255, 200, 127),
    160: (255, 255, 127),  170: (200, 255, 127),  180: (127, 255, 127),
    190: (127, 255, 200),  200: (127, 255, 255),  210: (127, 200, 255),
    220: (127, 127, 255),  230: (200, 127, 255),  240: (255, 127, 255),
    250: (  0,   0,   0),  251: ( 42,  42,  42),  252: ( 84,  84,  84),
    253: (127, 127, 127),  254: (170, 170, 170),  255: (255, 255, 255),
}

_INVISIBLE_ACI: Set[int] = {0, 7, 256}

_ARC_SEGMENTS:    int = 32
_CIRCLE_SEGMENTS: int = 36


# ─────────────────────────────────────────────────────────────────────────────
# COLOUR HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _aci_to_rgb(aci: int, cycle_idx: int = 0) -> Tuple[int, int, int]:
    if aci in _INVISIBLE_ACI:
        return _LAYER_COLOR_CYCLE[cycle_idx % len(_LAYER_COLOR_CYCLE)]
    if aci in _ACI_RGB:
        return _ACI_RGB[aci]
    return _LAYER_COLOR_CYCLE[aci % len(_LAYER_COLOR_CYCLE)]


def _normalise_vtk_color(color: Tuple[int, int, int]) -> List[float]:
    return [c / 255.0 for c in color]


# ─────────────────────────────────────────────────────────────────────────────
# FIX-G1 HELPER: Smart label scoring — mirrors DXF candidate_labels logic
# ─────────────────────────────────────────────────────────────────────────────

def _score_label(text: str) -> int:
    """
    Return a priority score for a text string that mirrors the logic in
    DXF process_entity → INSERT → candidate_labels.

    Score  100 : looks like a grid ID  (e.g. "DW2039017_000347", "GR_0012_005")
    Score   50 : has underscore + 3+ digits  (e.g. "BLOCK_ABC_123")
    Score   10 : has any digit (generic label)
    Score    0 : skip — not a useful label
    """
    t = text.strip()
    if len(t) < 5:
        return 0
    # Must contain at least one digit OR underscore to be a label
    has_digit      = any(c.isdigit() for c in t)
    has_underscore = '_' in t
    # if not has_digit and not has_underscore:
    #     return 0

    if not has_digit and not has_underscore:
        return 10  ##

    # HIGH: starts with a letter prefix, then digits, then underscore + digits
    # Covers "DW2039017_000347", "GR0012_005", "SRV_001_XYZ" etc.
    if has_underscore and sum(c.isdigit() for c in t) >= 4:
        return 100
    # MEDIUM: underscore + some digits
    if has_underscore and has_digit:
        return 50
    # LOW: just has digits
    if has_digit:
        return 10
    return 0


def _label_color_and_height(
    text: str,
) -> Tuple[Tuple[int, int, int], float]:
    """
    Return (vtk_color, text_height) for a label — mirrors DXF smart colour
    selection in process_entity INSERT block.

    The DXF code uses:
      • Cyan   (0,255,255) + height 3.0  →  grid IDs  (underscore + many digits)
      • Yellow (255,255,0) + height 2.5  →  feature names  (everything else)

    We apply the same split so SNT labels look identical to DXF labels.
    """
    score = _score_label(text)
    if score >= 100:
        # High-confidence grid ID → cyan
        return (0, 255, 255), 3.0
    else:
        # Feature / generic label → yellow
        return (255, 255, 0), 2.5
    

def _snt_enable_gl_point_size(app) -> bool:
    """
    Synchronously enable GL_PROGRAM_POINT_SIZE (0x8642) and install the
    persistent StartEvent observer so it stays enabled across future renders.

    Called from restore_snt_actors() which fires BEFORE the 500ms deferred
    init in build_unified_actor. Without this, gl_PointSize writes are ignored
    and points render at 1px — no border ring pixels, border invisible.
    """
    try:
        rw = app.vtk_widget.GetRenderWindow()
        if rw is None:
            return False
        state = rw.GetState() if hasattr(rw, 'GetState') else None
        if state and hasattr(state, 'vtkglEnable'):
            state.vtkglEnable(0x8642)

            # Also install/refresh the persistent StartEvent observer
            # so VTK's state machine can't clear the flag between renders.
            try:
                from gui.unified_actor_manager import (
                    _install_program_point_size_observer,
                    _try_enable_program_point_size,
                )
                ua = getattr(app, '_unified_actor', None)
                if ua is not None:
                    _try_enable_program_point_size(rw)
                    _install_program_point_size_observer(ua, rw)
            except Exception:
                pass

            return True
    except Exception as e:
        print(f"  ⚠️ _snt_enable_gl_point_size: {e}")
    return False


def _snt_push_border_uniforms(app) -> None:
    """
    Push weight_lut / visibility_lut / border_ring_val uniforms to the
    unified point-cloud actor right now, before the impending render.

    The deferred GPU init (500ms) would do this later, but restore_snt_actors
    renders immediately. If uniforms aren't pushed first, border_ring_val = 0
    in the shader → border condition never triggers → invisible border.
    """
    try:
        from gui.unified_actor_manager import _push_uniforms_direct
        ua = getattr(app, '_unified_actor', None)
        if ua is None:
            return
        ctx = getattr(ua, '_naksha_shader_ctx', None)
        if ctx is None:
            return
        _push_uniforms_direct(ua, ctx)
    except Exception as e:
        print(f"  ⚠️ _snt_push_border_uniforms: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Z-OFFSET APPROACH: SNT actors rendered above point cloud in same renderer
# ─────────────────────────────────────────────────────────────────────────────

def _get_snt_z_offset(app):
    """
    Calculate Z offset to position SNT actors ABOVE the entire point cloud.

    SNT entities are typically at Z≈0 (2D CAD files).
    Point cloud Z values can be 100s or 1000s (e.g. elevation 928m).
    Camera looks DOWN in plan view → higher Z = closer to camera = on top.

    So offset = z_max + margin → moves SNT from Z≈0 to above point cloud.
    """
    try:
        if hasattr(app, 'data') and app.data is not None and 'xyz' in app.data:
            z_vals = app.data['xyz'][:, 2]
            z_max = float(z_vals.max())
            z_min = float(z_vals.min())
            z_range = z_max - z_min
            # Offset must place SNT ABOVE z_max, not just above z_range
            # SNT is at Z≈0, so offset = z_max + margin
            offset = z_max + max(z_range * 0.5, 50.0)
            print(f"  📐 SNT Z-offset: {offset:.1f} (z_min={z_min:.1f}, z_max={z_max:.1f})")
            return offset
    except Exception:
        pass
    return 0.0


def _apply_z_offset_to_actor(actor, new_offset: float):
    """
    Apply (or update) the Z-position offset on an SNT actor.
    Tracks the current offset to avoid cumulative drift from repeated calls.
    """
    old_offset = getattr(actor, '_snt_z_offset', 0.0)
    delta = new_offset - old_offset
    if abs(delta) > 0.001:
        actor.AddPosition(0, 0, delta)
        actor._snt_z_offset = new_offset

# ─────────────────────────────────────────────────────────────────────────────
# SNT v1.1 BODY DECODERS  (unchanged from v2.0)
# ─────────────────────────────────────────────────────────────────────────────

def _decode_point_body(body, layer, color):
    if len(body) < 12:
        return None
    try:
        x, y, z = struct.unpack_from("<3f", body)
        return {"type": "POINT", "layer": layer, "color": color,
                "position": (float(x), float(y), float(z))}
    except struct.error:
        return None


def _decode_line_body(body, layer, color):
    if len(body) < 24:
        return None
    try:
        sx, sy, sz, ex, ey, ez = struct.unpack_from("<6f", body)
        return {"type": "POLYLINE", "layer": layer, "color": color,
                "vertices": [(float(sx), float(sy), float(sz)),
                             (float(ex), float(ey), float(ez))],
                "closed": False}
    except struct.error:
        return None


def _decode_arc_body(body, layer, color):
    if len(body) < 24:
        return None
    try:
        cx, cy, cz, r, sa, ea = struct.unpack_from("<6f", body)
        sa_r = math.radians(float(sa))
        ea_r = math.radians(float(ea))
        if ea_r <= sa_r:
            ea_r += 2.0 * math.pi
        verts = [
            (float(cx) + float(r) * math.cos(sa_r + (ea_r - sa_r) * i / _ARC_SEGMENTS),
             float(cy) + float(r) * math.sin(sa_r + (ea_r - sa_r) * i / _ARC_SEGMENTS),
             float(cz))
            for i in range(_ARC_SEGMENTS + 1)
        ]
        return {"type": "POLYLINE", "layer": layer, "color": color,
                "vertices": verts, "closed": False}
    except struct.error:
        return None


def _decode_circle_body(body, layer, color):
    if len(body) < 16:
        return None
    try:
        cx, cy, cz, r = struct.unpack_from("<4f", body)
        verts = [
            (float(cx) + float(r) * math.cos(2.0 * math.pi * i / _CIRCLE_SEGMENTS),
             float(cy) + float(r) * math.sin(2.0 * math.pi * i / _CIRCLE_SEGMENTS),
             float(cz))
            for i in range(_CIRCLE_SEGMENTS + 1)
        ]
        return {"type": "POLYLINE", "layer": layer, "color": color,
                "vertices": verts, "closed": True}
    except struct.error:
        return None


def _decode_lwpolyline_body(body, layer, color):
    if len(body) < 9:
        return None
    try:
        elev, flags, count = struct.unpack_from("<fBI", body)
        if len(body) < 9 + count * 12:
            return None
        verts = []
        pos = 9
        for _ in range(count):
            x, y, _bulge = struct.unpack_from("<3f", body, pos)
            verts.append((float(x), float(y), float(elev)))
            pos += 12
        if not verts:
            return None
        return {"type": "POLYLINE", "layer": layer, "color": color,
                "vertices": verts, "closed": bool(flags & 0x01)}
    except struct.error:
        return None


def _decode_polyline_body(body, layer, color):
    if len(body) < 5:
        return None
    try:
        flags, count = struct.unpack_from("<BI", body)
        if len(body) < 5 + count * 12:
            return None
        verts = []
        pos = 5
        for _ in range(count):
            x, y, z = struct.unpack_from("<3f", body, pos)
            verts.append((float(x), float(y), float(z)))
            pos += 12
        if not verts:
            return None
        return {"type": "POLYLINE", "layer": layer, "color": color,
                "vertices": verts, "closed": bool(flags & 0x01)}
    except struct.error:
        return None


def _decode_text_body(body, layer, color, string_fn):
    if len(body) < 28:
        return None
    try:
        ix, iy, iz, height, _rot, str_idx, _style = struct.unpack_from("<5fII", body)
        text = string_fn(str_idx)
        if not text or not text.strip():
            return None
        return {"type": "TEXT", "layer": layer, "color": color,
                "text": text,
                "position": (float(ix), float(iy), float(iz)),
                "height": float(height) if height > 0.0 else 1.0}
    except struct.error:
        return None


def _decode_face3d_body(body, layer, color):
    if len(body) < 48:
        return None
    try:
        verts = [tuple(struct.unpack_from("<3f", body, i * 12)) for i in range(4)]
        return {"type": "3DFACE", "layer": layer, "color": color,
                "vertices": [(float(v[0]), float(v[1]), float(v[2])) for v in verts]}
    except struct.error:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SNT BINARY FILE READER  (unchanged from v2.0)
# ─────────────────────────────────────────────────────────────────────────────

def _read_snt_file(filepath: str) -> Dict:
    result: Dict = {"version": (1, 0), "layers": [], "entities": []}

    # ── Strategy 1: snt_core v1.1 reader ────────────────────────────────
    try:
        from snt_core.snt_reader import SntReader
        from snt_core.snt_format import ColorMode, EntityType

        with SntReader(filepath) as reader:
            result["version"] = (reader.version_major, reader.version_minor)
            layers_out: List[Dict] = []
            for i, rec in enumerate(reader.layers):
                lname = reader.string(rec.name_idx)
                color = _aci_to_rgb(rec.color_aci, i)
                layers_out.append({"name": lname, "color": color})
            result["layers"] = layers_out

            entities_out: List[Dict] = []
            for hdr in reader.iter_entities():
                body       = reader.read_body(hdr)
                layer_name = reader.layer_name(hdr.layer_idx)

                if hdr.color_mode == ColorMode.BYLAYER:
                    idx   = hdr.layer_idx
                    color = (layers_out[idx]["color"]
                             if 0 <= idx < len(layers_out) else _DEFAULT_COLOR)
                elif hdr.color_mode == ColorMode.ACI:
                    color = _aci_to_rgb(hdr.color_value & 0xFF, hdr.layer_idx)
                else:
                    r = (hdr.color_value >> 16) & 0xFF
                    g = (hdr.color_value >>  8) & 0xFF
                    b =  hdr.color_value        & 0xFF
                    color = (r, g, b)

                etype = hdr.entity_type
                ent: Optional[Dict] = None

                if   etype == EntityType.POINT:
                    ent = _decode_point_body(body, layer_name, color)
                elif etype == EntityType.LINE:
                    ent = _decode_line_body(body, layer_name, color)
                elif etype == EntityType.ARC:
                    ent = _decode_arc_body(body, layer_name, color)
                elif etype == EntityType.CIRCLE:
                    ent = _decode_circle_body(body, layer_name, color)
                elif etype == EntityType.LWPOLYLINE:
                    ent = _decode_lwpolyline_body(body, layer_name, color)
                elif etype == EntityType.POLYLINE:
                    ent = _decode_polyline_body(body, layer_name, color)
                elif etype in (EntityType.TEXT, EntityType.MTEXT,
                               EntityType.DIMENSION, EntityType.LEADER):
                    ent = _decode_text_body(body, layer_name, color, reader.string)
                elif etype in (EntityType.SOLID, EntityType.FACE3D):
                    ent = _decode_face3d_body(body, layer_name, color)

                if ent is not None:
                    entities_out.append(ent)

            result["entities"] = entities_out
            print(f"  SNT v{reader.version_major}.{reader.version_minor} | "
                  f"layers={len(layers_out)} entities={len(entities_out)}")
            return result

    except ImportError:
        print("  ⚠️ snt_core not on PYTHONPATH — using legacy inline reader")
    except Exception as exc:
        print(f"  ⚠️ SntReader failed ({type(exc).__name__}): {exc}")
        traceback.print_exc()
        return result

    # ── Strategy 2: Legacy inline parser ────────────────────────────────
    try:
        with open(filepath, "rb") as f:
            raw: bytes = f.read()
    except OSError as exc:
        print(f"  ❌ Cannot read SNT file: {exc}")
        return result

    if len(raw) < 24:
        print("  ❌ File too small to be a valid SNT file")
        return result

    magic = raw[:4]
    if magic not in (_LEGACY_MAGIC_V0, _LEGACY_MAGIC_V1):
        print(f"  ❌ Unrecognised magic {magic!r} — not an SNT file")
        return result

    pos = 4
    ver_major, ver_minor = struct.unpack_from("<HH", raw, pos); pos += 4
    result["version"] = (ver_major, ver_minor)
    pos += 4  # skip CRC
    num_strings, num_layers, num_entities = struct.unpack_from("<III", raw, pos)
    pos += 12
    print(f"  [legacy] SNT v{ver_major}.{ver_minor} | "
          f"strings={num_strings} layers={num_layers} entities={num_entities}")

    legacy_strings: List[str] = []
    for _ in range(num_strings):
        if pos + 4 > len(raw):
            break
        slen = struct.unpack_from("<I", raw, pos)[0]; pos += 4
        legacy_strings.append(raw[pos:pos + slen].decode("utf-8", errors="replace"))
        pos += slen

    legacy_layers: List[Dict] = []
    for i in range(num_layers):
        if pos + 7 > len(raw):
            break
        name_idx = struct.unpack_from("<I", raw, pos)[0]; pos += 4
        r, g, b  = struct.unpack_from("<BBB", raw, pos); pos += 3
        name  = (legacy_strings[name_idx] if name_idx < len(legacy_strings)
                 else f"Layer{i}")
        color = ((r, g, b) if (r + g + b) > 0
                 else _LAYER_COLOR_CYCLE[i % len(_LAYER_COLOR_CYCLE)])
        legacy_layers.append({"name": name, "color": color})
    result["layers"] = legacy_layers

    legacy_entities: List[Dict] = []
    for _ in range(num_entities):
        if pos >= len(raw):
            break
        try:
            etype     = struct.unpack_from("<B", raw, pos)[0]; pos += 1
            layer_idx = struct.unpack_from("<I", raw, pos)[0]; pos += 4
            lname  = (legacy_layers[layer_idx]["name"]
                      if layer_idx < len(legacy_layers) else "0")
            lcolor = (legacy_layers[layer_idx]["color"]
                      if layer_idx < len(legacy_layers) else _DEFAULT_COLOR)

            if etype == _LEGACY_ETYPE_POLYLINE:
                nv = struct.unpack_from("<I", raw, pos)[0]; pos += 4
                verts = []
                for _ in range(nv):
                    x, y, z = struct.unpack_from("<ddd", raw, pos); pos += 24
                    verts.append((x, y, z))
                closed = (len(verts) >= 3 and
                          np.allclose(verts[0], verts[-1], atol=1e-6))
                legacy_entities.append({
                    "type": "POLYLINE", "layer": lname, "color": lcolor,
                    "vertices": verts, "closed": closed})
            elif etype == _LEGACY_ETYPE_TEXT:
                tlen = struct.unpack_from("<I", raw, pos)[0]; pos += 4
                text = raw[pos:pos + tlen].decode("utf-8", errors="replace")
                pos += tlen
                x, y, z = struct.unpack_from("<ddd", raw, pos); pos += 24
                height = (struct.unpack_from("<d", raw, pos)[0]
                          if pos + 8 <= len(raw) else 1.0)
                pos += 8
                legacy_entities.append({
                    "type": "TEXT", "layer": lname, "color": lcolor,
                    "text": text, "position": (x, y, z), "height": height})
            elif etype == _LEGACY_ETYPE_3DFACE:
                verts = []
                for _ in range(4):
                    x, y, z = struct.unpack_from("<ddd", raw, pos); pos += 24
                    verts.append((x, y, z))
                legacy_entities.append({
                    "type": "3DFACE", "layer": lname, "color": lcolor,
                    "vertices": verts})
            else:
                print(f"  ⚠️ [legacy] Unknown entity type={etype} — stopping")
                break
        except struct.error as exc:
            print(f"  ⚠️ [legacy] Parse error at pos={pos}: {exc}")
            break

    result["entities"] = legacy_entities
    return result


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND LOAD WORKER  (unchanged from v2.0)
# ─────────────────────────────────────────────────────────────────────────────

class SNTLoadWorker(QThread):
    progress    = Signal(int, str, bool)
    file_loaded = Signal(object, object)
    finished    = Signal()
    error       = Signal(str)

    def __init__(self, file_paths: List[str]) -> None:
        super().__init__()
        self.file_paths: List[str] = file_paths
        self._cancelled: bool      = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
            try:
                total = len(self.file_paths)
                indeterminate = (total == 1)
                for idx, fp in enumerate(self.file_paths):
                    if self._cancelled:
                        print("  🛑 SNT load cancelled by user")
                        return
                    
                    # Check cancellation more frequently
                    QCoreApplication.processEvents()
                    if self._cancelled:
                        return
                        
                    snt_path = Path(fp)
                    self.progress.emit(
                        0 if indeterminate else idx,
                        f"📂 Reading {snt_path.name}...",
                        indeterminate,
                    )
                    item_data = {"snt_path": snt_path}
                    try:
                        parsed = _read_snt_file(str(snt_path))
                        if self._cancelled:  # Check after long operation
                            return
                        item_data["parsed"] = parsed
                        item_data["entity_count"] = len(parsed["entities"])
                        item_data["layer_count"] = len(parsed["layers"])
                    except Exception as exc:
                        if not self._cancelled:
                            item_data["error"] = str(exc)
                    
                    if not self._cancelled:
                        self.file_loaded.emit(item_data, None)
                
                if not self._cancelled:
                    self.finished.emit()
            except Exception as exc:
                if not self._cancelled:
                    self.error.emit(f"SNT loading failed: {exc}\n{traceback.format_exc()}")


# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY OPTIONS DIALOG  (unchanged from v2.0)
# ─────────────────────────────────────────────────────────────────────────────

class SNTDisplayOptionsDialog(QDialog):
    _COLOR_PRESETS: List[Tuple[str, QColor]] = [
        ("Green",   QColor(  0, 255,  80)),
        ("Cyan",    QColor(  0, 255, 255)),
        ("Yellow",  QColor(255, 255,   0)),
        ("Red",     QColor(255,   0,   0)),
        ("White",   QColor(255, 255, 255)),
        ("Magenta", QColor(255,   0, 255)),
        ("Blue",    QColor(  0,   0, 255)),
    ]

    def __init__(self, parent=None, mode="overlay", override_enabled=False,
                 override_color=(0, 255, 80)):
        super().__init__(parent)
        self.setWindowTitle("SNT Display Options")
        self.setModal(True)
        self.resize(300, 180)
        self.setStyleSheet(get_dialog_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Display Mode:"))
        self.overlay_radio  = QRadioButton("Overlay (on top)")
        self.underlay_radio = QRadioButton("Underlay (below)")
        (self.underlay_radio if mode == "underlay" else self.overlay_radio).setChecked(True)
        mode_row.addWidget(self.overlay_radio)
        mode_row.addWidget(self.underlay_radio)
        layout.addLayout(mode_row)

        color_row = QHBoxLayout()
        self.color_check = QCheckBox("Override colour:")
        self.color_combo  = QComboBox()
        for name, qc in self._COLOR_PRESETS:
            self.color_combo.addItem(name, qc)
        self.color_check.setChecked(override_enabled)
        self.color_combo.setEnabled(override_enabled)
        self.color_check.toggled.connect(self.color_combo.setEnabled)
        for i in range(self.color_combo.count()):
            q = self.color_combo.itemData(i)
            if (q.red(), q.green(), q.blue()) == override_color:
                self.color_combo.setCurrentIndex(i)
                break
        color_row.addWidget(self.color_check)
        color_row.addWidget(self.color_combo)
        layout.addLayout(color_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn     = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def get_values(self):
        mode    = "underlay" if self.underlay_radio.isChecked() else "overlay"
        enabled = self.color_check.isChecked()
        qc      = self.color_combo.currentData()
        return mode, enabled, (qc.red(), qc.green(), qc.blue())


# ─────────────────────────────────────────────────────────────────────────────
# LAYER SELECTION DIALOG  (unchanged from v2.0)
# ─────────────────────────────────────────────────────────────────────────────

class SNTLayerSelectionDialog(QDialog):
    def __init__(self, snt_path: Path, parent_item=None):
        super().__init__(parent_item)
        self.snt_path    = snt_path
        self.parent_item = parent_item
        self.setWindowTitle(f"Layer Display — {snt_path.name}")
        self.setModal(True)
        self.resize(400, 550)
        self._init_ui()
        self._load_layers()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.setStyleSheet(get_dialog_stylesheet())

        title = QLabel("Select Layers to Display")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        self.layer_list = QListWidget()
        self.layer_list.setAlternatingRowColors(True)
        layout.addWidget(self.layer_list)

        action_row = QHBoxLayout()
        for label, slot in [("All On", self._select_all),
                             ("All Off", self._deselect_all),
                             ("Invert", self._invert)]:
            btn = QPushButton(label)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(slot)
            action_row.addWidget(btn)
        layout.addLayout(action_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)  # Fix: Enter triggers OK
        ok_btn.setObjectName("primaryBtn")
        ok_btn.setAutoDefault(False)
        ok_btn.setDefault(False)
        ok_btn.setFocusPolicy(Qt.NoFocus)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        cancel_btn.setFocusPolicy(Qt.NoFocus)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _load_layers(self):
        parsed: Optional[Dict] = None
        if (self.parent_item is not None
                and hasattr(self.parent_item, "cached_parsed")
                and self.parent_item.cached_parsed):
            parsed = self.parent_item.cached_parsed
        else:
            try:
                parsed = _read_snt_file(str(self.snt_path))
                if self.parent_item is not None:
                    self.parent_item.cached_parsed = parsed
            except Exception as exc:
                print(f"❌ Layer load failed: {exc}")

        layers_info: List[Tuple[str, int, Tuple[int, int, int]]] = []
        if parsed:
            stats: Dict = {
                layer["name"]: {"count": 0, "color": layer["color"]}
                for layer in parsed.get("layers", [])
            }
            for ent in parsed.get("entities", []):
                name = ent.get("layer", "0")
                if name not in stats:
                    stats[name] = {"count": 0, "color": _DEFAULT_COLOR}
                stats[name]["count"] += 1
            layers_info = [(name, s["count"], s["color"])
                           for name, s in stats.items()]

        current_sel = getattr(self.parent_item, "selected_layers", None)
        for name, count, color in sorted(layers_info, key=lambda x: x[0]):
            item = QListWidgetItem()
            item.setText(f"{name}  ({count} entities)")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            checked = (current_sel is None) or (name in current_sel)
            item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            item.setData(Qt.UserRole, name)
            item.setForeground(QColor(*color))
            self.layer_list.addItem(item)

    def _select_all(self):
        for i in range(self.layer_list.count()):
            self.layer_list.item(i).setCheckState(Qt.Checked)

    def _deselect_all(self):
        for i in range(self.layer_list.count()):
            self.layer_list.item(i).setCheckState(Qt.Unchecked)

    def _invert(self):
        for i in range(self.layer_list.count()):
            it = self.layer_list.item(i)
            it.setCheckState(
                Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def get_selected_layers(self) -> Set[str]:
        return {
            self.layer_list.item(i).data(Qt.UserRole)
            for i in range(self.layer_list.count())
            if self.layer_list.item(i).checkState() == Qt.Checked
        }


# ─────────────────────────────────────────────────────────────────────────────
# FILE ITEM WIDGET  (unchanged from v2.0)
# ─────────────────────────────────────────────────────────────────────────────

class SNTFileItem(QWidget):
    remove_requested = Signal(object)

    def __init__(self, snt_path: Path, parent=None):
        super().__init__(parent)
        self.snt_path:         Path               = Path(snt_path)
        self.cached_parsed:    Optional[Dict]     = None
        self.actor_cache:      Dict[str, List]    = {}
        self.entity_layers:    Dict[int, str]     = {}
        self.entity_count:     int                = 0
        self.display_mode:     str                = "overlay"
        self.override_enabled: bool               = False
        self.override_color:   Tuple[int,int,int] = (0, 255, 80)
        self.selected_layers:  Optional[Set[str]] = None
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)

        self.checkbox = QCheckBox(f"{self.snt_path.name}")
        self.checkbox.setChecked(True)
        self.checkbox.setStyleSheet(f"color:{ThemeColors.get('accent')}; font-weight:bold; font-size:10px;")
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.checkbox, 1)

        badge = QLabel("SNT")
        badge.setStyleSheet(get_badge_style("success"))
        layout.addWidget(badge)

        self.count_label = QLabel("...")
        self.count_label.setStyleSheet(f"color:{ThemeColors.get('text_muted')}; font-size:9px;")
        layout.addWidget(self.count_label)

        for icon, tip, slot, role in [
            ("📋", "Select layers",   self._open_layer_selection, "default"),
            ("⚙",  "Display options", self._open_display_options, "settings"),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(26, 26)
            btn.setToolTip(tip)
            btn.setStyleSheet(get_icon_button_style(role))
            btn.clicked.connect(slot)
            layout.addWidget(btn)

        rm_btn = QPushButton("✖")
        rm_btn.setFixedSize(26, 26)
        rm_btn.setStyleSheet(get_icon_button_style("danger"))
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(rm_btn)

        self.setStyleSheet(get_file_item_row_style())

    def update_entity_count(self, count: int):
        self.entity_count = count
        self.count_label.setText(f"{count} entities")
        self.count_label.setStyleSheet(f"color:{ThemeColors.get('accent')}; font-size:7px; font-weight:bold;")

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def _on_checkbox_changed(self, state: int):
        try:
            is_visible = (state == Qt.Checked or state == Qt.CheckState.Checked or state == 2)
            parent_dlg = self._find_parent_dialog()
            if parent_dlg is None:
                return

            renderer = None
            try:
                renderer = parent_dlg.app.vtk_widget.renderer
            except Exception:
                pass

            if self.actor_cache:
                for layer_name, actors in self.actor_cache.items():
                    layer_ok = (self.selected_layers is None
                                or layer_name in self.selected_layers)
                    vis = is_visible and layer_ok
                    for actor in actors:
                        # Re-add actor to renderer if classification removed it
                        # (GetVisibility returning 0 after being removed from
                        # the renderer is the symptom of the bug).
                        if is_visible and renderer is not None:
                            try:
                                # AddActor is idempotent — safe to call again
                                renderer.AddActor(actor)
                            except Exception:
                                pass
                        actor.SetVisibility(1 if vis else 0)
            else:
                # Fallback: check both snt_actors and dxf_actors
                target = self.snt_path.name
                for store in ['snt_actors', 'dxf_actors']:
                    for snt_data in getattr(parent_dlg.app, store, []):
                        if os.path.basename(snt_data.get("filename", "")) == target:
                            for actor in snt_data.get("actors", []):
                                if is_visible and renderer is not None:
                                    try:
                                        renderer.AddActor(actor)
                                    except Exception:
                                        pass
                                actor.SetVisibility(1 if is_visible else 0)

            self._force_render(parent_dlg)
        except Exception as exc:
            print(f"  ⚠️ SNT checkbox toggle failed: {exc}")

    def _open_display_options(self):
        dlg = SNTDisplayOptionsDialog(
            self, mode=self.display_mode,
            override_enabled=self.override_enabled,
            override_color=self.override_color)
        if dlg.exec() != QDialog.Accepted:
            return
        old_mode = self.display_mode
        self.display_mode, self.override_enabled, self.override_color = dlg.get_values()
        for _layer, actors in self.actor_cache.items():
            for actor in actors:
                if self.override_enabled:
                    actor.GetProperty().SetColor(_normalise_vtk_color(self.override_color))
                elif hasattr(actor, "_original_color"):
                    actor.GetProperty().SetColor(_normalise_vtk_color(actor._original_color))
                if old_mode != self.display_mode:
                    actor.GetProperty().SetOpacity(
                        0.5 if self.display_mode == "underlay" else 1.0)
        parent_dlg = self._find_parent_dialog()
        if parent_dlg:
            self._force_render(parent_dlg)

    def _open_layer_selection(self):
        try:
            dlg = SNTLayerSelectionDialog(self.snt_path, self)
            if dlg.exec() != QDialog.Accepted:
                return
            selected      = dlg.get_selected_layers()
            total_layers  = dlg.layer_list.count()

            if len(selected) == 0:
                self.selected_layers = set()
                self.count_label.setText(f"{self.entity_count} entities (0 layers)")
                self.count_label.setStyleSheet(f"color:{ThemeColors.get('danger')}; font-size:7px; font-weight:bold;")
            elif len(selected) == total_layers:
                self.selected_layers = None
                self.count_label.setText(f"{self.entity_count} entities")
                self.count_label.setStyleSheet(f"color:{ThemeColors.get('accent')}; font-size:7px; font-weight:bold;")
            else:
                self.selected_layers = selected
                self.count_label.setText(
                    f"{self.entity_count} entities ({len(selected)} layers)")
                self.count_label.setStyleSheet(f"color:{ThemeColors.get('text_secondary')}; font-size:7px; font-weight:bold;")

            if self.actor_cache and self.checkbox.isChecked():
                for layer_name, actors in self.actor_cache.items():
                    vis = (self.selected_layers is None
                           or layer_name in self.selected_layers)
                    for actor in actors:
                        actor.SetVisibility(vis)

            parent_dlg = self._find_parent_dialog()
            if parent_dlg:
                self._force_render(parent_dlg)
        except Exception as exc:
            print(f"❌ Layer selection failed: {exc}")
            traceback.print_exc()

    def _find_parent_dialog(self):
        p = self.parent()
        while p is not None and not isinstance(p, MultiSNTAttachmentDialog):
            p = p.parent()
        return p

    @staticmethod
    def _force_render(parent_dlg):
        try:
            rw = parent_dlg.app.vtk_widget.GetRenderWindow()
            if rw:
                rw.Render()
                return
        except Exception:
            pass
        try:
            parent_dlg.app.vtk_widget.render()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ATTACHMENT DIALOG
# ─────────────────────────────────────────────────────────────────────────────

class MultiSNTAttachmentDialog(QDialog):
    """
    Dialog for attaching multiple SNT overlay files.
    All actors are dual-registered in both app.snt_actors AND app.dxf_actors
    so that every downstream system (grid-click → LAZ load, Grid Label Manager,
    classification refresh) works identically for SNT and DXF.
    """

    snt_attached = Signal(list)

    def __init__(self, app, parent=None):
        target_parent = None
        if isinstance(parent, QWidget):
            target_parent = parent
        elif isinstance(app, QWidget):
            target_parent = app
        elif hasattr(app, "window") and isinstance(app.window, QWidget):
            target_parent = app.window

        super().__init__(target_parent, Qt.Window)
        self.setWindowModality(Qt.NonModal)
        self.app             = app
        self.snt_items:      List[SNTFileItem]       = []
        self._load_worker:   Optional[SNTLoadWorker] = None
        self.setProperty("themeStyledDialog", True)

        self.setWindowTitle("Attach SNT Files  —  NakshaApp Native Format")
        self.setStyleSheet(get_dialog_stylesheet())
        self.setGeometry(150, 150, 700, 780)
        self._init_ui()

    # ── UI ────────────────────────────────────────────────────────────────

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        title = QLabel("Attach SNT Files (NakshaApp Native Format)")
        title.setStyleSheet(get_title_banner_style())
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        info = QLabel(
            "SNT loads 10-50x faster than DXF  |  "
            "Colours & layers preserved  |  Grid pipeline fully compatible")
        info.setStyleSheet(get_notice_banner_style("info"))
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)

        file_group = QGroupBox("Select SNT Files")
        file_layout = QVBoxLayout()
        browse_btn  = QPushButton("Browse and Add SNT Files...")
        browse_btn.setObjectName("secondaryBtn")
        browse_btn.setAutoDefault(False)
        browse_btn.setDefault(False)
        browse_btn.setFocusPolicy(Qt.NoFocus)
        browse_btn.clicked.connect(self._select_snt_files)
        file_layout.addWidget(browse_btn)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        list_group = QGroupBox("Selected SNT Files  (click X to remove)")
        list_layout = QVBoxLayout()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        scroll.setMaximumHeight(320)
        self.file_list_widget = QWidget()
        self.file_list_layout = QVBoxLayout(self.file_list_widget)
        self.file_list_layout.setSpacing(5)
        self.file_list_layout.setContentsMargins(5, 5, 5, 5)
        self.file_list_layout.addStretch()
        scroll.setWidget(self.file_list_widget)
        list_layout.addWidget(scroll)

        self.file_count_label = QLabel("No files selected")
        self.file_count_label.setStyleSheet(f"color:{ThemeColors.get('text_muted')}; font-size:10px; padding:5px;")
        list_layout.addWidget(self.file_count_label)
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear All")
        clear_btn.setObjectName("dangerBtn")
        clear_btn.setAutoDefault(False)
        clear_btn.setDefault(False)
        clear_btn.setFocusPolicy(Qt.NoFocus)
        clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        attach_btn = QPushButton("Attach All SNT Files")
        attach_btn.setObjectName("primaryBtn")
        attach_btn.setAutoDefault(False)
        attach_btn.setDefault(False)
        attach_btn.setFocusPolicy(Qt.NoFocus)
        attach_btn.clicked.connect(self._attach_all)
        btn_row.addWidget(attach_btn)
        layout.addLayout(btn_row)

    # ── File selection ────────────────────────────────────────────────────

    def _select_snt_files(self):
        """Select and load SNT files with improved worker management."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select SNT Files", "", "SNT Files (*.snt);;All Files (*)")
        if not file_paths:
            return

        # Improved worker cancellation
        if self._load_worker is not None:
            if self._load_worker.isRunning():
                self._load_worker.cancel()
                self._load_worker.wait(5000)  # Wait up to 5 seconds
                if self._load_worker.isRunning():
                    self._load_worker.terminate()  # Force terminate
                    self._load_worker.wait(1000)
            self._load_worker = None
        
        # Process events to ensure cleanup
        QCoreApplication.processEvents()
        
        total = len(file_paths)
        indeterminate = (total == 1)

        progress = QProgressDialog(
            "Loading SNT file..." if indeterminate else "Loading SNT files...",
            "Cancel", 0, 0 if indeterminate else total, self)
        progress.setWindowTitle("Loading SNT Files")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setStyleSheet(get_progress_dialog_stylesheet())
        progress.show()
        QCoreApplication.processEvents()

        self._load_worker = SNTLoadWorker(file_paths)

        def on_progress(value, message, is_indet):
            try:
                if progress is not None and not progress.wasCanceled():
                    progress.setLabelText(message)
                    if not is_indet:
                        progress.setValue(value)
            except RuntimeError:
                pass  # Dialog deleted

        def on_file_loaded(item_data, _):
            try:
                snt_path = item_data["snt_path"]
                if any(it.snt_path == snt_path for it in self.snt_items):
                    return
                item = SNTFileItem(snt_path)
                item.remove_requested.connect(self._remove_item)
                self.file_list_layout.insertWidget(len(self.snt_items), item)
                self.snt_items.append(item)
                if "parsed" in item_data:
                    item.cached_parsed = item_data["parsed"]
                    item.update_entity_count(item_data["entity_count"])
                else:
                    item.count_label.setText("Error")
                    item.count_label.setStyleSheet(
                        f"color:{ThemeColors.get('danger')}; font-size:9px;")
            except RuntimeError:
                pass  # Item deleted

        def on_finished():
            try:
                if progress is not None and not progress.wasCanceled():
                    if not indeterminate:
                        progress.setValue(total)
                    progress.close()
                self._update_file_count()
            except RuntimeError:
                pass

        def on_error(msg):
            try:
                if progress is not None:
                    progress.close()
                QMessageBox.critical(self, "Load Failed", msg)
            except RuntimeError:
                pass

        def on_canceled():
            if self._load_worker and self._load_worker.isRunning():
                self._load_worker.cancel()
                self._load_worker.wait(3000)
                if self._load_worker.isRunning():
                    self._load_worker.terminate()

        self._load_worker.progress.connect(on_progress)
        self._load_worker.file_loaded.connect(on_file_loaded)
        self._load_worker.finished.connect(on_finished)
        self._load_worker.error.connect(on_error)
        progress.canceled.connect(on_canceled)
        self._load_worker.start()

    def closeEvent(self, event):
        """Override closeEvent to ensure proper cleanup."""
        # Cancel worker thread
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.cancel()
            self._load_worker.wait(3000)
            if self._load_worker.isRunning():
                self._load_worker.terminate()
        
        event.accept()

    # ── Item management ───────────────────────────────────────────────────

    def _remove_item(self, item: SNTFileItem):
        """Safely remove an SNT item with proper cleanup."""
        if item not in self.snt_items:
            return
        
        try:
            # Store needed data before removal
            filename = str(item.snt_path.name)
            
            # Remove from list first
            self.snt_items.remove(item)
            
            # Remove from layout
            self.file_list_layout.removeWidget(item)
            
            # Clear actor cache to break circular references
            if hasattr(item, 'actor_cache'):
                item.actor_cache.clear()
            
            # Remove from VTK
            self._remove_from_vtk(filename)
            
            # Disconnect signals before deletion
            try:
                item.remove_requested.disconnect()
            except Exception:
                pass
            
            # Schedule deletion
            item.setParent(None)
            item.deleteLater()
            
            # Update UI
            self._update_file_count()
            
        except Exception as exc:
            print(f"⚠️ Error in _remove_item: {exc}")
            traceback.print_exc()

    def _remove_from_vtk(self, filename: str):
        """Safely remove VTK actors with extensive error handling."""
        try:
            target = os.path.basename(filename)
            
            # Safely get renderer
            renderer = None
            try:
                if (hasattr(self.app, 'vtk_widget') and 
                    self.app.vtk_widget is not None and
                    hasattr(self.app.vtk_widget, 'renderer')):
                    renderer = self.app.vtk_widget.renderer
            except (RuntimeError, AttributeError) as e:
                print(f"  ⚠️ Cannot access renderer: {e}")
                renderer = None
            
            # Remove from both actor stores
            for store_name in ['snt_actors', 'dxf_actors']:
                if not hasattr(self.app, store_name):
                    continue
                    
                store = getattr(self.app, store_name, [])
                indices_to_remove = []
                
                # Find indices to remove
                for i, snt_data in enumerate(store):
                    if os.path.basename(snt_data.get("filename", "")) == target:
                        indices_to_remove.append(i)
                        
                        # Remove actors from renderer if available
                        if renderer is not None:
                            for actor in snt_data.get("actors", []):
                                try:
                                    # Check if actor is still valid
                                    if actor is not None:
                                        renderer.RemoveActor(actor)
                                except (RuntimeError, AttributeError) as e:
                                    print(f"  ⚠️ Error removing actor: {e}")
                
                # Remove in reverse order to maintain indices
                for i in reversed(indices_to_remove):
                    try:
                        store.pop(i)
                    except IndexError:
                        pass
            
            # Remove from attachment lists
            for list_name in ['snt_attachments', 'dxf_attachments']:
                if hasattr(self.app, list_name):
                    try:
                        current_list = getattr(self.app, list_name)
                        setattr(self.app, list_name, [
                            a for a in current_list
                            if os.path.basename(a.get("filename", "")) != target
                        ])
                    except Exception as e:
                        print(f"  ⚠️ Error cleaning {list_name}: {e}")
            
            # Safely render
            if renderer is not None:
                try:
                    rw = self.app.vtk_widget.GetRenderWindow()
                    if rw is not None:
                        rw.Render()
                except (RuntimeError, AttributeError) as e:
                    print(f"  ⚠️ Render failed: {e}")
            
        except Exception as exc:
            print(f"  ⚠️ _remove_from_vtk failed: {exc}")
            traceback.print_exc()

    def _clear_all(self):
        """Safely clear all SNT items with proper cleanup."""
        # Cancel any running worker first
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.cancel()
            self._load_worker.wait(5000)  # Longer wait
            if self._load_worker.isRunning():
                self._load_worker.terminate()  # Force terminate if still running
            self._load_worker = None
        
        # Process pending events to ensure worker cleanup
        QCoreApplication.processEvents()
        
        # Copy list to avoid modification during iteration
        items_to_remove = list(self.snt_items)
        for item in items_to_remove:
            try:
                self._remove_item(item)
            except Exception as e:
                print(f"⚠️ Error removing item: {e}")
        
        self._update_file_count()
        
        # Force garbage collection
        import gc
        gc.collect()

    def restore_snt_actors(self) -> None:
        try:
            renderer = self.app.vtk_widget.renderer
        except Exception:
            return

        z_offset = _get_snt_z_offset(self.app)

        restored = 0
        for item in self.snt_items:
            if not item.is_checked():
                continue
            if item.actor_cache:
                for layer_name, actors in item.actor_cache.items():
                    layer_ok = (item.selected_layers is None
                                or layer_name in item.selected_layers)
                    for actor in actors:
                        try:
                            _apply_z_offset_to_actor(actor, z_offset)
                            renderer.AddActor(actor)
                            actor.SetVisibility(1 if layer_ok else 0)
                            restored += 1
                        except Exception:
                            pass
            else:
                target = item.snt_path.name
                for store in ['snt_actors', 'dxf_actors']:
                    for snt_data in getattr(self.app, store, []):
                        if os.path.basename(snt_data.get("filename", "")) == target:
                            for actor in snt_data.get("actors", []):
                                try:
                                    _apply_z_offset_to_actor(actor, z_offset)
                                    renderer.AddActor(actor)
                                    actor.SetVisibility(1)
                                    restored += 1
                                except Exception:
                                    pass

        if restored:
            # FIX 1: No manual SetClippingRange — ResetCameraClippingRange already correct.
            renderer.ResetCameraClippingRange()

            # FIX 2: Explicitly enable GL_PROGRAM_POINT_SIZE RIGHT NOW.
            # restore_snt_actors() fires in the same callstack as build_unified_actor,
            # BEFORE the 500ms deferred timer. Without this, gl_PointSize writes in the
            # vertex shader are silently ignored → all points render at 1px → no border
            # ring pixels exist → border "applies" in data but is completely invisible.
            # This is why DXF works (attached later, GL already warm) but SNT doesn't.
            _snt_enable_gl_point_size(self.app)

            # FIX 3: Push border uniforms before the render that follows.
            # The 500ms deferred init would push them later, but we need them NOW.
            _snt_push_border_uniforms(self.app)

            print(f"  🔄 restore_snt_actors: re-added {restored} actors "
                f"(z_offset={z_offset:.1f})")
            try:
                rw = self.app.vtk_widget.GetRenderWindow()
                if rw:
                    rw.Render()
            except Exception:
                try:
                    self.app.vtk_widget.render()
                except Exception:
                    pass

    def _update_file_count(self):
        count = len(self.snt_items)
        if count == 0:
            self.file_count_label.setText("No files selected")
            self.file_count_label.setStyleSheet(f"color:{ThemeColors.get('text_muted')}; font-size:10px; padding:5px;")
        else:
            total_ent = sum(it.entity_count for it in self.snt_items)
            self.file_count_label.setText(
                f"{count} file(s)  |  {total_ent:,} total entities")
            self.file_count_label.setStyleSheet(
                f"color:{ThemeColors.get('accent')}; font-size:10px; font-weight:bold; padding:5px;")

    # ── Attach all ────────────────────────────────────────────────────────

    def _attach_all(self):
        selected_items = [it for it in self.snt_items if it.is_checked()]
        if not selected_items:
            QMessageBox.warning(self, "No Files", "Please select SNT files first.")
            return

        # ── Auto-save current LAZ ─────────────────────────────────────────
        print(f"\n{'='*60}")
        print(f"💾 AUTO-SAVING CURRENT FILE BEFORE SNT ATTACHMENT")
        print(f"{'='*60}")

        if hasattr(self.app, 'data') and self.app.data is not None:
            save_path = (getattr(self.app, 'last_save_path', None)
                         or getattr(self.app, 'loaded_file', None))
            if save_path:
                try:
                    from gui.save_pointcloud import save_pointcloud_quick
                    save_pointcloud_quick(self.app, save_path)
                    print(f"✅ Current file saved successfully")
                    if hasattr(self.app, "statusBar"):
                        self.app.statusBar().showMessage(
                            f"Saved: {os.path.basename(save_path)}", 2000)
                        QCoreApplication.processEvents()
                except Exception as e:
                    print(f"⚠️ Failed to auto-save: {e}")
                    reply = QMessageBox.warning(
                        self, "Save Failed",
                        f"Failed to auto-save current file:\n\n{e}\n\n"
                        "Continue with SNT attachment anyway?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if reply == QMessageBox.No:
                        return

        # ── Confirmation ───────────────────────────────────────────────────
        msg = f"Attach {len(selected_items)} SNT file(s)?\n\n"
        if hasattr(self.app, "data") and self.app.data is not None:
            msg += "WARNING: Current point cloud will be CLEARED\n"
            msg += "You can reload LAZ files after SNT attachment\n"

        if QMessageBox.question(
                        self, "Confirm SNT Attachment", msg,
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,  # Fix: Enter triggers Yes
                    ) != QMessageBox.Yes:
        
            return

        # ── Clear current project ──────────────────────────────────────────
        print(f"\n🧹 CLEARING CURRENT PROJECT...")
        if hasattr(self.app, 'data') and self.app.data is not None:
            if hasattr(self.app, "vtk_widget") and self.app.vtk_widget:
                renderer = self.app.vtk_widget.renderer
                renderer.RemoveAllViewProps()
                for attr in ['actors', '_actors']:
                    if hasattr(self.app.vtk_widget, attr):
                        getattr(self.app.vtk_widget, attr).clear()
                self.app.vtk_widget.render()

            if hasattr(self.app, 'section_vtks'):
                for vtk_widget in self.app.section_vtks.values():
                    try:
                        vtk_widget.renderer.RemoveAllViewProps()
                        if hasattr(vtk_widget, 'actors'):
                            vtk_widget.actors.clear()
                        vtk_widget.render()
                    except Exception:
                        pass

            self.app.data           = None
            self.app.loaded_file    = None
            self.app.last_save_path = None
            self.app.class_palette  = {}
            if hasattr(self.app, "view_palettes"):
                self.app.view_palettes.clear()

            # Clear both SNT and DXF lists — full reset
            for attr in ['snt_actors', 'snt_attachments',
                         'dxf_actors', 'dxf_attachments']:
                if hasattr(self.app, attr):
                    getattr(self.app, attr).clear()

            print(f"✅ Project cleared\n")
            QCoreApplication.processEvents()

        # ── Process and render ─────────────────────────────────────────────
        progress = QProgressDialog(
            "Processing SNT files...", "Cancel",
            0, len(selected_items) * 2, self)
        progress.setWindowTitle("Attaching SNT Files")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setStyleSheet(get_progress_dialog_stylesheet())
        progress.show()
        progress.forceShow()
        QCoreApplication.processEvents()

        # Ensure storage lists exist
        for attr in ['snt_attachments', 'snt_actors',
                     'dxf_attachments', 'dxf_actors']:
            if not hasattr(self.app, attr):
                setattr(self.app, attr, [])

        all_attachments: List[Dict] = []

        try:
            for idx, item in enumerate(selected_items):
                if progress.wasCanceled():
                    return
                progress.setLabelText(f"Processing {item.snt_path.name}...")
                progress.setValue(idx)
                QCoreApplication.processEvents()

                attachment = self._process_snt_file(item)
                if attachment:
                    attachment["_snt_item"] = item
                    all_attachments.append(attachment)

            if not all_attachments:
                progress.close()
                QMessageBox.information(
                    self, "No Data",
                    "No entities found in selected SNT file(s).\n"
                    "The files may be empty or use an unsupported format.")
                return

            # Register in BOTH attachment lists so all consumers find them
            self.app.snt_attachments.extend(all_attachments)
            self.app.dxf_attachments.extend(all_attachments)  # ← bridge
            self.snt_attached.emit(all_attachments)

            for idx, attachment in enumerate(all_attachments):
                if progress.wasCanceled():
                    return
                progress.setLabelText(f"Rendering {attachment['filename']}...")
                progress.setValue(len(selected_items) + idx)
                QCoreApplication.processEvents()
                # _render_snt_in_vtk registers actors in BOTH snt_actors and dxf_actors
                self._render_snt_in_vtk(attachment)

            progress.setValue(len(selected_items) * 2)
            progress.close()

            total_ent = sum(len(a["entities"]) for a in all_attachments)
            QMessageBox.information(
                self, "SNT Attached",
                f"Attached {len(all_attachments)} SNT file(s)\n"
                f"Total entities: {total_ent:,}\n\n"
                f"You can now load LAZ files for the grids.")
            try:
                self.app._update_window_title(
                    f"SNT Grid ({len(all_attachments)} files)", None)
            except Exception:
                pass

        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Attachment Failed", str(exc))
            traceback.print_exc()

    # ── Process one SNT file ──────────────────────────────────────────────

    def _process_snt_file(self, item: SNTFileItem) -> Optional[Dict]:
        try:
            if item.cached_parsed:
                parsed = item.cached_parsed
                print(f"  ⚡ Using cached SNT data for {item.snt_path.name}")
            else:
                print(f"  📂 Reading SNT file {item.snt_path.name}...")
                parsed = _read_snt_file(str(item.snt_path))
                item.cached_parsed = parsed

            color_override = item.override_color if item.override_enabled else None
            raw_entities   = parsed.get("entities", [])

            filtered: List[Dict] = []
            for ent in raw_entities:
                if (item.selected_layers is not None
                        and ent.get("layer", "0") not in item.selected_layers):
                    continue
                if color_override:
                    ent = {**ent, "color": color_override}
                filtered.append(ent)

            render_entities = self._convert_entities(filtered)
            item.update_entity_count(len(raw_entities))

            print(f"  ✅ {item.snt_path.name}: "
                  f"{len(raw_entities)} total → "
                  f"{len(render_entities)} after filter")

            return {
                "filename":  item.snt_path.name,
                "full_path": str(item.snt_path.resolve()),
                "mode":      item.display_mode,
                "entities":  render_entities,
            }

        except Exception as exc:
            print(f"⚠️ Failed to process {item.snt_path.name}: {exc}")
            traceback.print_exc()
            return None

    # ── FIX-G1: Entity conversion with smart label scoring ────────────────

    def _convert_entities(self, entities: List[Dict]) -> List[Dict]:
        """
        Convert parsed SNT entity dicts → VTK-renderable dicts.

        TEXT handling mirrors DXF process_entity INSERT candidate_labels logic:
          • Score each label with _score_label() (priority 0-100)
          • Skip score-0 strings (metadata, attribute tags, etc.)
          • Score ≥ 100  →  grid ID  (cyan, height 3.0)
          • Score 10-99  →  feature label  (yellow, height 2.5)

        This replaces the previous hardcoded 'DW'/'MURAGLIONE' filter so the
        dialog works correctly for ANY project, not just the original test data.
        """
        out: List[Dict] = []

        for ent in entities:
            etype = ent.get("type", "")
            color = ent.get("color", _DEFAULT_COLOR)
            layer = ent.get("layer", "0")

            # ── POLYLINE (includes arcs, circles, lines after decode) ──────
            if etype == "POLYLINE":
                verts = ent.get("vertices", [])
                if len(verts) < 2:
                    continue
                out.append({
                    "type":   "polyline",
                    "points": [[p[0], p[1], p[2]] for p in verts],
                    "closed": ent.get("closed", False),
                    "color":  color,
                    "layer":  layer,
                })

            # ── 3DFACE (grid squares) ──────────────────────────────────────
            elif etype == "3DFACE":
                verts = ent.get("vertices", [])
                if len(verts) < 3:
                    continue
                v = list(verts[:4])
                while len(v) < 4:
                    v.append(v[-1])
                is_tri = np.allclose(v[2], v[3], atol=1e-6)
                out.append({
                    "type":        "3dface",
                    "vertices":    [[p[0], p[1], p[2]] for p in v],
                    "is_triangle": is_tri,
                    "color":       color,
                    "layer":       layer,
                })

            # ── TEXT — smart scoring, project-agnostic ─────────────────────
            elif etype == "TEXT":
                text = str(ent.get("text", "")).strip()

                # Score the label using the same priority logic as DXF
                score = _score_label(text)
                if score == 0:
                    # Zero score = metadata / noise — skip exactly as DXF does
                    continue

                # Derive colour and height from score (mirrors DXF smart colour)
                label_color, label_height = _label_color_and_height(text)

                # If the SNT entity already has an explicit non-default colour
                # and we're not overriding, respect it for feature labels
                if score < 100 and color != _DEFAULT_COLOR:
                    label_color = color

                pos = ent.get("position", (0.0, 0.0, 0.0))
                out.append({
                    "type":     "text",
                    "text":     text,
                    "position": [pos[0], pos[1], pos[2]],
                    "height":   label_height,
                    "rotation": 0.0,
                    "color":    label_color,
                    "layer":    layer,
                })

            # ── POINT ─────────────────────────────────────────────────────
            elif etype == "POINT":
                pos = ent.get("position", (0.0, 0.0, 0.0))
                out.append({
                    "type":     "point",
                    "position": [pos[0], pos[1], pos[2]],
                    "color":    color,
                    "layer":    layer,
                })

        return out

    def _render_snt_in_vtk(self, attachment: Dict) -> None:
        """
        ULTIMATE FIX: Forces 'Resolve Coincident Topology' ON and uses
        the Translucent Pass Hack to match MicroStation behavior.

        BUG FIX (visibility regression after repeated classification):
          - Populates SNTFileItem.actor_cache so the checkbox handler uses
            direct actor references instead of the fragile fallback path.
          - Stores actors back on the attachment dict so restore_snt_actors()
            can re-add them to the renderer after a classification pass wipes
            RemoveAllViewProps().
        """
        try:
            import vtk
            from pathlib import Path
            from collections import defaultdict

            if not hasattr(self.app, "vtk_widget"):
                return
            renderer = self.app.vtk_widget.renderer  # ← FIX: same renderer, no overlay
            actors: List = []
            z_offset = _get_snt_z_offset(self.app)  # ← FIX: calculate Z offset
            # Retrieve the SNTFileItem so we can populate its actor_cache
            item: Optional[SNTFileItem] = attachment.get("_snt_item")
            entities = attachment.get("entities", [])
            bounds_points = vtk.vtkPoints()

            line_groups: Dict = defaultdict(list)
            text_ents:   List = []
            for e in entities:
                etype = e.get("type", "").lower()
                if etype in ("line", "polyline"):
                    line_groups[(tuple(e["color"]), e["layer"])].append(e)
                elif etype == "text":
                    text_ents.append(e)

            # ── Helper: register actor in item.actor_cache ─────────────────
            def _cache(actor, layer_name: str) -> None:
                if item is not None:
                    item.actor_cache.setdefault(layer_name, []).append(actor)

            # Tag helper — marks actors so optimized_refresh freeze/unfreeze
            # and _rebuild_dxf_actor_cache recognise them as overlay actors.
            def _tag_snt(actor) -> None:
                try:
                    from gui.optimized_refresh import tag_actor_as_dxf
                    tag_actor_as_dxf(actor)
                except Exception:
                    # Fallback: set the attribute directly
                    setattr(actor, '_is_dxf_actor', True)

            # ── Lines / Polylines ──────────────────────────────────────────
            for (color, layer_name), group in line_groups.items():
                appender = vtk.vtkAppendPolyData()
                for e in group:
                    pts = vtk.vtkPoints()
                    for pt in e["points"]:
                        pts.InsertNextPoint(pt)
                        bounds_points.InsertNextPoint(pt)
                    pline = vtk.vtkPolyLine()
                    pline.GetPointIds().SetNumberOfIds(pts.GetNumberOfPoints())
                    for i in range(pts.GetNumberOfPoints()):
                        pline.GetPointIds().SetId(i, i)
                    pd = vtk.vtkPolyData()
                    pd.SetPoints(pts)
                    cells = vtk.vtkCellArray()
                    cells.InsertNextCell(pline)
                    pd.SetLines(cells)
                    appender.AddInputData(pd)

                appender.Update()
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputData(appender.GetOutput())

                # Force polygon-offset ON (was missing in new render path)
                mapper.SetResolveCoincidentTopologyToPolygonOffset()
                mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(
                    -10000.0, -10000.0)

                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor([c / 255.0 for c in color])
                actor.GetProperty().SetLineWidth(4.0)
                actor.GetProperty().SetLighting(False)
                actor.GetProperty().SetAmbient(1.0)
                # 0.99 opacity forces translucent render pass → renders on top
                actor.GetProperty().SetOpacity(1.0)
                actor._original_color = color   # kept for display-options override
                _tag_snt(actor)       
                
                _apply_z_offset_to_actor(actor, z_offset)           # marks as overlay for freeze/unfreeze

                renderer.AddActor(actor)
                actors.append(actor)
                _cache(actor, layer_name)       # ← FIX: populate actor_cache

            # ── Text labels ────────────────────────────────────────────────
            for e in text_ents:
                a = self._create_text_actor(e)
                if a:
                    bounds_points.InsertNextPoint(e["position"])
                    if a.GetMapper():
                        a.GetMapper().SetResolveCoincidentTopologyToPolygonOffset()
                        a.GetMapper().SetRelativeCoincidentTopologyPolygonOffsetParameters(
                            -20000.0, -20000.0)
                    a.GetProperty().SetOpacity(1.0)
                    a.GetProperty().SetLighting(False)
                    if "color" in e:
                        a._original_color = e["color"]
                    _tag_snt(a)                     # marks as overlay for freeze/unfreeze
                    _apply_z_offset_to_actor(a, z_offset)
                    renderer.AddActor(a)
                    actors.append(a)
                    _cache(a, e.get("layer", "0"))  # ← FIX: populate actor_cache

            # ── Dual registration in snt_actors + dxf_actors ──────────────
            fpath = str(Path(
                attachment.get("full_path", attachment["filename"])).resolve())
            actor_entry = {
                "filename":  attachment["filename"],
                "full_path": fpath,
                "actors":    actors,
            }
            self.app.snt_actors.append(actor_entry)
            self.app.dxf_actors.append(actor_entry)

            # Invalidate the optimized_refresh actor cache so it rebuilds
            # on the next classification pass and includes these SNT actors.
            try:
                from gui.optimized_refresh import invalidate_dxf_actor_cache
                invalidate_dxf_actor_cache()
            except Exception:
                pass

            # Store actors back on the attachment so restore_snt_actors() can
            # re-add them after a classification pass wipes the renderer.
            attachment["actors"] = actors

            # ── Camera fit ────────────────────────────────────────────────
            # ── Camera fit ────────────────────────────────────────────────
            if bounds_points.GetNumberOfPoints() > 0:
                temp_pd = vtk.vtkPolyData()
                temp_pd.SetPoints(bounds_points)
                renderer.ResetCamera(temp_pd.GetBounds())
            # Always reset clipping to include Z-offset actors
            renderer.ResetCameraClippingRange()

            self.app.vtk_widget.render()
            print(f"  ✅ Rendered {len(actors)} SNT actors, "
                  f"actor_cache layers={len(item.actor_cache) if item else 'N/A'}")

        except Exception as e:
            print(f"❌ Render Error: {e}")
            traceback.print_exc()

    # ── Text actor (unchanged from v2.0) ──────────────────────────────────

    def _create_text_actor(self, entity: Dict):
        import vtk

        text_content = str(entity.get("text", "")).strip()
        if not text_content:
            return None

        text_source = vtk.vtkVectorText()
        text_source.SetText(text_content)
        text_source.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(text_source.GetOutputPort())

        actor = vtk.vtkFollower()
        actor.SetMapper(mapper)
        actor.text_content = text_content
        actor.is_grid_label = True
        actor.grid_name     = text_content
        actor.PickableOn()

        bounds      = text_source.GetOutput().GetBounds()
        text_width  = bounds[1] - bounds[0]
        text_height = bounds[3] - bounds[2]

        pos = entity["position"]
        mag = abs(pos[0]) + abs(pos[1])
        if   mag > 100_000:
            desired_w, desired_h = 80.0, 20.0
        elif mag > 10_000:
            desired_w, desired_h = 40.0, 10.0
        elif mag > 1_000:
            desired_w, desired_h = 16.0,  4.0
        else:
            desired_w, desired_h =  4.0,  1.0

        scale = (min(desired_w / text_width, desired_h / text_height)
                 if text_width > 0 and text_height > 0 else 1.0)
        actor.SetScale(scale, scale, scale)
        actor.GetProperty().SetColor(_normalise_vtk_color(entity["color"]))
        actor.GetProperty().SetLineWidth(3.0)
        actor.GetProperty().SetOpacity(1.0)
        actor.GetProperty().SetAmbient(0.6)
        actor.GetProperty().SetDiffuse(0.9)

        try:
            actor.SetCamera(self.app.vtk_widget.renderer.GetActiveCamera())
        except Exception:
            pass

        half_w = (text_width  * scale) / 2.0
        half_h = (text_height * scale) / 2.0
        actor.SetPosition(
            pos[0] - half_w,
            pos[1] - half_h,
            pos[2] if len(pos) > 2 else 0.0)
        return actor

    # ── Point actor ────────────────────────────────────────────────────────

    def _create_point_actor(self, entity: Dict):
        import vtk

        pts = vtk.vtkPoints()
        pts.InsertNextPoint(entity["position"])
        verts = vtk.vtkCellArray()
        verts.InsertNextCell(1)
        verts.InsertCellPoint(0)
        pd = vtk.vtkPolyData()
        pd.SetPoints(pts)
        pd.SetVerts(verts)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(pd)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(_normalise_vtk_color(entity["color"]))
        actor.GetProperty().SetPointSize(5.0)
        return actor

    # ── Theme helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _naksha_dark_theme() -> str:
        return """
        QWidget { background:#121212; color:#e0e0e0;
                  font-family:"Segoe UI"; font-size:10pt; }
        QLabel  { color:#e0e0e0; }
        QGroupBox { border:1px solid #3a3a3a; border-radius:5px;
                    margin-top:10px; padding-top:10px; }
        QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; }
        QComboBox, QSpinBox {
            background:#1e1e1e; border:1px solid #3a3a3a;
            border-radius:4px; padding:5px; color:#eee; }
        QPushButton { background:#333; border:1px solid #555;
                      border-radius:5px; padding:8px 12px; color:#ddd; }
        QPushButton:hover { background:#444; border-color:#007acc; }
        QRadioButton, QCheckBox { spacing:6px; color:#ccc; }
        QRadioButton::indicator, QCheckBox::indicator {
            width:16px; height:16px; border:2px solid #555;
            background:#1e1e1e; border-radius:8px; }
        QRadioButton::indicator:checked, QCheckBox::indicator:checked {
            background:#007acc; border-color:#007acc; }
        """

    @staticmethod
    def _progress_style() -> str:
        return """
        QProgressDialog { background:#1e1e1e; color:#e0e0e0; min-width:420px; }
        QLabel { color:#00ff50; font-size:11pt; padding:10px; }
        QProgressBar { border:2px solid #3a3a3a; border-radius:5px;
                       text-align:center; background:#121212; color:#fff;
                       min-height:25px; font-size:10pt; }
        QProgressBar::chunk { background:#2e7d32; border-radius:3px; }
        QPushButton { background:#d32f2f; color:white; padding:8px 16px;
                      border-radius:4px; }
        """


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def show_snt_attachment_dialog(app) -> MultiSNTAttachmentDialog:
    """
    Show (or raise) the SNT attachment dialog.
    Mirrors show_multi_dxf_attachment_dialog() exactly.
    """
    if hasattr(app, "snt_dialog") and app.snt_dialog is not None:
        try:
            dlg = app.snt_dialog
            if dlg.isVisible():
                dlg.setWindowState(
                    dlg.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
                dlg.raise_()
                dlg.activateWindow()
            else:
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
            return dlg
        except RuntimeError:
            app.snt_dialog = None

    dlg = MultiSNTAttachmentDialog(app, parent=app)
    dlg.setModal(False)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    app.snt_dialog = dlg

    def _on_close(event):
        event.ignore()
        dlg.hide()

    dlg.closeEvent = _on_close
    return dlg