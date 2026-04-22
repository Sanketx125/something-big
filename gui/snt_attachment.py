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
    QCoreApplication, Qt, QThread, Signal, QEvent,
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# COLOUR HELPERS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _aci_to_rgb(aci: int, cycle_idx: int = 0) -> Tuple[int, int, int]:
    if aci in _INVISIBLE_ACI:
        return _LAYER_COLOR_CYCLE[cycle_idx % len(_LAYER_COLOR_CYCLE)]
    if aci in _ACI_RGB:
        return _ACI_RGB[aci]
    return _LAYER_COLOR_CYCLE[aci % len(_LAYER_COLOR_CYCLE)]


def _normalise_vtk_color(color: Tuple[int, int, int]) -> List[float]:
    return [c / 255.0 for c in color]


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# FIX-G1 HELPER: Smart label scoring â€” mirrors DXF candidate_labels logic
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _score_label(text: str) -> int:
    """
    Return a priority score for a text string that mirrors the logic in
    DXF process_entity â†’ INSERT â†’ candidate_labels.

    Score  100 : looks like a grid ID  (e.g. "DW2039017_000347", "GR_0012_005")
    Score   50 : has underscore + 3+ digits  (e.g. "BLOCK_ABC_123")
    Score   10 : has any digit (generic label)
    Score    0 : skip â€” not a useful label
    """
    t = text.strip()
    if len(t) < 5:
        return 0
    # Must contain at least one digit OR underscore to be a label
    has_digit      = any(c.isdigit() for c in t)
    has_underscore = '_' in t

    if not has_digit and not has_underscore:
        return 10

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
    Return (vtk_color, text_height) for a label â€” mirrors DXF smart colour
    selection in process_entity INSERT block.

    The DXF code uses:
      â€¢ Cyan   (0,255,255) + height 3.0  â†’  grid IDs  (underscore + many digits)
      â€¢ Yellow (255,255,0) + height 2.5  â†’  feature names  (everything else)

    We apply the same split so SNT labels look identical to DXF labels.
    """
    score = _score_label(text)
    if score >= 100:
        # High-confidence grid ID â†’ cyan
        return (0, 255, 255), 3.0
    else:
        # Feature / generic label â†’ yellow
        return (255, 255, 0), 2.5
    

def _snt_enable_gl_point_size(app) -> bool:
    """
    Synchronously enable GL_PROGRAM_POINT_SIZE (0x8642) and install the
    persistent StartEvent observer so it stays enabled across future renders.
    """
    try:
        rw = app.vtk_widget.GetRenderWindow()
        if rw is None:
            return False
        state = rw.GetState() if hasattr(rw, 'GetState') else None
        if state and hasattr(state, 'vtkglEnable'):
            state.vtkglEnable(0x8642)

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
        print(f"  âš ï¸ _snt_enable_gl_point_size: {e}")
    return False


def _snt_push_border_uniforms(app) -> None:
    """
    Push weight_lut / visibility_lut / border_ring_val uniforms to the
    unified point-cloud actor right now, before the impending render.
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
        print(f"  âš ï¸ _snt_push_border_uniforms: {e}")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Z-OFFSET APPROACH: SNT actors rendered above point cloud in same renderer
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _get_snt_z_offset(app):
    try:
        if hasattr(app, 'data') and app.data is not None and 'xyz' in app.data:
            z_vals = app.data['xyz'][:, 2]
            z_max = float(z_vals.max())
            z_min = float(z_vals.min())
            z_range = z_max - z_min
            offset = z_max + max(z_range * 0.5, 50.0)
            print(f"  ðŸ“ SNT Z-offset: {offset:.1f} (z_min={z_min:.1f}, z_max={z_max:.1f})")
            return offset
    except Exception:
        pass
    return 0.0


def _apply_z_offset_to_actor(actor, new_offset: float):
    old_offset = getattr(actor, '_snt_z_offset', 0.0)
    delta = new_offset - old_offset
    if abs(delta) > 0.001:
        actor.AddPosition(0, 0, delta)
        actor._snt_z_offset = new_offset

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SNT v1.1 BODY DECODERS
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# SNT BINARY FILE READER
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _read_snt_file(filepath: str) -> Dict:
    result: Dict = {"version": (1, 0), "layers": [], "entities": []}

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
        print("  âš ï¸ snt_core not on PYTHONPATH â€” using legacy inline reader")
    except Exception as exc:
        print(f"  âš ï¸ SntReader failed ({type(exc).__name__}): {exc}")
        traceback.print_exc()
        return result

    # â”€â”€ Legacy inline parser â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        with open(filepath, "rb") as f:
            raw: bytes = f.read()
    except OSError as exc:
        print(f"  âŒ Cannot read SNT file: {exc}")
        return result

    if len(raw) < 24:
        print("  âŒ File too small to be a valid SNT file")
        return result

    magic = raw[:4]
    if magic not in (_LEGACY_MAGIC_V0, _LEGACY_MAGIC_V1):
        print(f"  âŒ Unrecognised magic {magic!r} â€” not an SNT file")
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
                break
        except struct.error:
            break

    result["entities"] = legacy_entities
    return result


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# BACKGROUND LOAD WORKER
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
                    return
                
                QCoreApplication.processEvents()
                if self._cancelled:
                    return
                    
                snt_path = Path(fp)
                self.progress.emit(
                    0 if indeterminate else idx,
                    f"ðŸ“‚ Reading {snt_path.name}...",
                    indeterminate,
                )
                item_data = {"snt_path": snt_path}
                try:
                    parsed = _read_snt_file(str(snt_path))
                    if self._cancelled:
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# DISPLAY OPTIONS DIALOG
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# LAYER SELECTION DIALOG
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class SNTLayerSelectionDialog(QDialog):
    def __init__(self, snt_path: Path, parent_item=None):
        super().__init__(parent_item)
        self.snt_path    = snt_path
        self.parent_item = parent_item
        self.setWindowTitle(f"Layer Display â€” {snt_path.name}")
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
            except Exception:
                pass

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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# FILE ITEM WIDGET
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        self.setObjectName("sntFileItemRow")
        self.setFixedHeight(34)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignVCenter)

        # 1. Checkbox
        self.checkbox = QCheckBox(f"{self.snt_path.name}")
        self.checkbox.setChecked(True)
        self.checkbox.setObjectName("sntItemCheckbox")
        self.checkbox.setFixedHeight(26)
        self.checkbox.stateChanged.connect(self._on_checkbox_changed)
        layout.addWidget(self.checkbox, 1)

        # 2. SNT Badge
        self.snt_badge = QLabel("SNT")
        self.snt_badge.setObjectName("sntBadge")
        self.snt_badge.setFixedSize(35, 20)
        self.snt_badge.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.snt_badge)

        # 3. Entity Count
        self.count_label = QLabel("...")
        self.count_label.setObjectName("sntCountBadge")
        self.count_label.setFixedSize(85, 20)
        self.count_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.count_label)

        # 4. Layers Button
        self.layers_btn = QPushButton(" 📋 Layers")
        self.layers_btn.setObjectName("secondaryBtn")
        self.layers_btn.setFixedSize(75, 24)
        self.layers_btn.clicked.connect(self._open_layer_selection)
        layout.addWidget(self.layers_btn)

        # 5. Settings Button
        self.settings_btn = QPushButton(" ⚙ Settings")
        self.settings_btn.setObjectName("secondaryBtn")
        self.settings_btn.setFixedSize(85, 24)
        self.settings_btn.clicked.connect(self._open_display_options)
        layout.addWidget(self.settings_btn)

        # 6. Remove Button
        self.rm_btn = QPushButton("X")
        self.rm_btn.setObjectName("dangerBtn")
        self.rm_btn.setFixedSize(24, 24)
        self.rm_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(self.rm_btn)

        self.refresh_theme()

    def refresh_theme(self):
        """Re-apply styles based on current theme."""
        c = ThemeColors
        accent = c.get('accent')
        
        self.setStyleSheet(f"""
            QWidget#sntFileItemRow {{
                background: {c.get('bg_secondary')};
                border: 1px solid {c.get('border_light')};
                border-radius: 8px;
            }}
            QWidget#sntFileItemRow:hover {{
                border-color: {accent};
            }}
            QCheckBox#sntItemCheckbox {{
                color: {accent};
                font-weight: bold;
                font-size: 10px;
                background: {c.get('bg_input')};
                border: 1px solid {c.get('border_light')};
                border-radius: 13px;
                padding: 0px 10px;
            }}
            QLabel#sntBadge {{
                background: {c.get('success')};
                color: white;
                border-radius: 4px;
                font-size: 9px;
                font-weight: bold;
            }}
            QLabel#sntCountBadge {{
                background: {c.get('bg_input')};
                color: {accent};
                border: 1px solid {c.get('border_light')};
                border-radius: 10px;
                font-size: 9px;
                font-weight: bold;
            }}
            QPushButton#secondaryBtn, QPushButton#dangerBtn {{
                font-size: 9px;
                font-weight: bold;
                padding: 0px;
            }}
        """)

    def update_entity_count(self, count: int):
        self.entity_count = count
        self.count_label.setText(f"{count:,} entities")

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
                        if is_visible and renderer is not None:
                            try:
                                renderer.AddActor(actor)
                            except Exception:
                                pass
                        actor.SetVisibility(1 if vis else 0)
            else:
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
            print(f"  âš ï¸ SNT checkbox toggle failed: {exc}")

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
            print(f"âŒ Layer selection failed: {exc}")
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
        self.setGeometry(150, 150, 720, 800)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        # 1. Main Title
        self.title_label = QLabel("Attach SNT Files (NakshaApp Native Format)")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(get_title_banner_style())
        layout.addWidget(self.title_label)

        # 2. Info Banner
        self.info_label = QLabel(
            "SNT loads 10-50x faster than DXF  |  "
            "Colours & layers preserved  |  Grid pipeline fully compatible")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet(get_notice_banner_style("info"))
        layout.addWidget(self.info_label)

        # 3. File Selection Group
        file_group = QGroupBox("Select SNT Files")
        file_layout = QVBoxLayout()
        self.browse_btn  = QPushButton(" 📂 Browse and Add SNT Files...")
        self.browse_btn.setObjectName("secondaryBtn")
        self.browse_btn.setMinimumHeight(45)
        self.browse_btn.setAutoDefault(False)
        self.browse_btn.setDefault(False)
        self.browse_btn.setFocusPolicy(Qt.NoFocus)
        self.browse_btn.clicked.connect(self._select_snt_files)
        file_layout.addWidget(self.browse_btn)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # 4. List Group
        list_group = QGroupBox("Selected SNT Files (click ✖ to remove)")
        list_layout = QVBoxLayout()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(200)
        scroll.setMaximumHeight(350)
        
        self.file_list_widget = QWidget()
        self.file_list_layout = QVBoxLayout(self.file_list_widget)
        self.file_list_layout.setSpacing(5)
        self.file_list_layout.setContentsMargins(5, 5, 5, 5)
        self.file_list_layout.addStretch()
        scroll.setWidget(self.file_list_widget)
        list_layout.addWidget(scroll)

        self.file_count_label = QLabel("No files selected")
        self.file_count_label.setStyleSheet(f"color: {ThemeColors.get('text_muted')}; font-size: 10px; padding: 5px;")
        list_layout.addWidget(self.file_count_label)
        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        btn_row = QHBoxLayout()
        clear_btn = QPushButton(" 🗑 Clear All")
        clear_btn.setObjectName("dangerBtn")
        clear_btn.setMinimumHeight(40)
        clear_btn.setAutoDefault(False)
        clear_btn.setDefault(False)
        clear_btn.setFocusPolicy(Qt.NoFocus)
        clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(clear_btn)

        btn_row.addStretch()

        self.attach_btn = QPushButton(" ✅ Attach All SNT Files")
        self.attach_btn.setObjectName("primaryBtn")
        self.attach_btn.setMinimumHeight(40)
        self.attach_btn.setAutoDefault(False)
        self.attach_btn.setDefault(False)
        self.attach_btn.setFocusPolicy(Qt.NoFocus)
        self.attach_btn.clicked.connect(self._attach_all)
        btn_row.addWidget(self.attach_btn)
        layout.addLayout(btn_row)

    def refresh_theme(self):
        """Re-apply styles to the entire dialog and all items."""
        self.setStyleSheet(get_dialog_stylesheet())
        self.title_label.setStyleSheet(get_title_banner_style())
        self.info_label.setStyleSheet(get_notice_banner_style("info"))
        self.browse_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ThemeColors.get('bg_secondary')};
                color: {ThemeColors.get('accent')};
                border: 1px solid {ThemeColors.get('border_light')};
                border-radius: 8px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {ThemeColors.get('bg_input')};
                border: 1px solid {ThemeColors.get('accent')};
            }}
        """)
        for item in self.snt_items:
            item.refresh_theme()

    def changeEvent(self, event):
        """Detect theme property changes and refresh."""
        if event.type() == QEvent.DynamicPropertyChange:
            if event.propertyName() == "themeStyledDialog":
                self.refresh_theme()
        super().changeEvent(event)

    def _select_snt_files(self):
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select SNT Files", "", "SNT Files (*.snt);;All Files (*)")
        if not file_paths:
            return

        if self._load_worker is not None:
            if self._load_worker.isRunning():
                self._load_worker.cancel()
                self._load_worker.wait(5000)
                if self._load_worker.isRunning():
                    self._load_worker.terminate()
            self._load_worker = None
        
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
                pass

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
                pass

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
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.cancel()
            self._load_worker.wait(3000)
            if self._load_worker.isRunning():
                self._load_worker.terminate()
        event.accept()

    def _remove_item(self, item: SNTFileItem):
        if item not in self.snt_items:
            return
        try:
            filename = str(item.snt_path.name)
            self.snt_items.remove(item)
            self.file_list_layout.removeWidget(item)
            if hasattr(item, 'actor_cache'):
                item.actor_cache.clear()
            self._remove_from_vtk(filename)
            try:
                item.remove_requested.disconnect()
            except Exception:
                pass
            item.setParent(None)
            item.deleteLater()
            self._update_file_count()
        except Exception as exc:
            print(f"âš ï¸ Error in _remove_item: {exc}")

    def _remove_from_vtk(self, filename: str):
        try:
            target = os.path.basename(filename)
            renderer = None
            try:
                if (hasattr(self.app, 'vtk_widget') and 
                    self.app.vtk_widget is not None and
                    hasattr(self.app.vtk_widget, 'renderer')):
                    renderer = self.app.vtk_widget.renderer
            except Exception:
                renderer = None
            
            for store_name in ['snt_actors', 'dxf_actors']:
                if not hasattr(self.app, store_name):
                    continue
                store = getattr(self.app, store_name, [])
                indices_to_remove = []
                for i, snt_data in enumerate(store):
                    if os.path.basename(snt_data.get("filename", "")) == target:
                        indices_to_remove.append(i)
                        if renderer is not None:
                            for actor in snt_data.get("actors", []):
                                try:
                                    if actor is not None:
                                        renderer.RemoveActor(actor)
                                except Exception:
                                    pass
                for i in reversed(indices_to_remove):
                    try:
                        store.pop(i)
                    except IndexError:
                        pass
            
            for list_name in ['snt_attachments', 'dxf_attachments']:
                if hasattr(self.app, list_name):
                    try:
                        current_list = getattr(self.app, list_name)
                        setattr(self.app, list_name, [
                            a for a in current_list
                            if os.path.basename(a.get("filename", "")) != target
                        ])
                    except Exception:
                        pass
            
            if renderer is not None:
                try:
                    rw = self.app.vtk_widget.GetRenderWindow()
                    if rw is not None:
                        rw.Render()
                except Exception:
                    pass
        except Exception as exc:
            print(f"  âš ï¸ _remove_from_vtk failed: {exc}")

    def _clear_all(self):
        if self._load_worker is not None and self._load_worker.isRunning():
            self._load_worker.cancel()
            self._load_worker.wait(5000)
            if self._load_worker.isRunning():
                self._load_worker.terminate()
            self._load_worker = None
        
        QCoreApplication.processEvents()
        items_to_remove = list(self.snt_items)
        for item in items_to_remove:
            try:
                self._remove_item(item)
            except Exception:
                pass
        self._update_file_count()
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
            renderer.ResetCameraClippingRange()
            _snt_enable_gl_point_size(self.app)
            _snt_push_border_uniforms(self.app)
            try:
                rw = self.app.vtk_widget.GetRenderWindow()
                if rw:
                    rw.Render()
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

    def _attach_all(self):
        selected_items = [it for it in self.snt_items if it.is_checked()]
        if not selected_items:
            QMessageBox.warning(self, "No Files", "Please select SNT files first.")
            return

        if hasattr(self.app, 'data') and self.app.data is not None:
            save_path = (getattr(self.app, 'last_save_path', None)
                         or getattr(self.app, 'loaded_file', None))
            if save_path:
                try:
                    from gui.save_pointcloud import save_pointcloud_quick
                    save_pointcloud_quick(self.app, save_path)
                except Exception as e:
                    reply = QMessageBox.warning(
                        self, "Save Failed",
                        f"Failed to auto-save current file:\n\n{e}\n\n"
                        "Continue with SNT attachment anyway?",
                        QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if reply == QMessageBox.No:
                        return

        msg = f"Attach {len(selected_items)} SNT file(s)?\n\n"
        if hasattr(self.app, "data") and self.app.data is not None:
            msg += "WARNING: Current point cloud will be CLEARED\n"
            msg += "You can reload LAZ files after SNT attachment\n"

        if QMessageBox.question(
                        self, "Confirm SNT Attachment", msg,
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    ) != QMessageBox.Yes:
            return

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

            for attr in ['snt_actors', 'snt_attachments',
                         'dxf_actors', 'dxf_attachments']:
                if hasattr(self.app, attr):
                    getattr(self.app, attr).clear()

            QCoreApplication.processEvents()

        progress = QProgressDialog(
            "Processing SNT files...", "Cancel",
            0, len(selected_items) * 2, self)
        progress.setWindowTitle("Attaching SNT Files")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setStyleSheet(get_progress_dialog_stylesheet())
        progress.show()
        QCoreApplication.processEvents()

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
                QMessageBox.information(self, "No Data", "No entities found.")
                return

            self.app.snt_attachments.extend(all_attachments)
            self.app.dxf_attachments.extend(all_attachments)
            self.snt_attached.emit(all_attachments)

            for idx, attachment in enumerate(all_attachments):
                if progress.wasCanceled():
                    return
                progress.setLabelText(f"Rendering {attachment['filename']}...")
                progress.setValue(len(selected_items) + idx)
                QCoreApplication.processEvents()
                self._render_snt_in_vtk(attachment)

            progress.setValue(len(selected_items) * 2)
            progress.close()

            total_ent = sum(len(a["entities"]) for a in all_attachments)
            QMessageBox.information(
                self, "SNT Attached",
                f"Attached {len(all_attachments)} SNT file(s)\n"
                f"Total entities: {total_ent:,}")
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Attachment Failed", str(exc))

    def _process_snt_file(self, item: SNTFileItem) -> Optional[Dict]:
        try:
            if item.cached_parsed:
                parsed = item.cached_parsed
            else:
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

            return {
                "filename":  item.snt_path.name,
                "full_path": str(item.snt_path.resolve()),
                "mode":      item.display_mode,
                "entities":  render_entities,
            }
        except Exception:
            return None

    def _convert_entities(self, entities: List[Dict]) -> List[Dict]:
        out: List[Dict] = []
        for ent in entities:
            etype = ent.get("type", "")
            color = ent.get("color", _DEFAULT_COLOR)
            layer = ent.get("layer", "0")

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
            elif etype == "TEXT":
                text = str(ent.get("text", "")).strip()
                score = _score_label(text)
                if score == 0:
                    continue
                label_color, label_height = _label_color_and_height(text)
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
        try:
            import vtk
            if not hasattr(self.app, "vtk_widget"):
                return
            renderer = self.app.vtk_widget.renderer
            actors: List = []
            z_offset = _get_snt_z_offset(self.app)
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

            def _cache(actor, layer_name: str) -> None:
                if item is not None:
                    item.actor_cache.setdefault(layer_name, []).append(actor)

            def _tag_snt(actor) -> None:
                try:
                    from gui.optimized_refresh import tag_actor_as_dxf
                    tag_actor_as_dxf(actor)
                except Exception:
                    setattr(actor, '_is_dxf_actor', True)

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
                mapper.SetResolveCoincidentTopologyToPolygonOffset()
                mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-10000.0, -10000.0)

                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor([c / 255.0 for c in color])
                actor.GetProperty().SetLineWidth(4.0)
                actor.GetProperty().SetLighting(False)
                actor.GetProperty().SetAmbient(1.0)
                actor.GetProperty().SetOpacity(1.0)
                actor._original_color = color
                _tag_snt(actor)
                _apply_z_offset_to_actor(actor, z_offset)
                renderer.AddActor(actor)
                actors.append(actor)
                _cache(actor, layer_name)

            for e in text_ents:
                a = self._create_text_actor(e)
                if a:
                    bounds_points.InsertNextPoint(e["position"])
                    if a.GetMapper():
                        a.GetMapper().SetResolveCoincidentTopologyToPolygonOffset()
                        a.GetMapper().SetRelativeCoincidentTopologyPolygonOffsetParameters(-20000.0, -20000.0)
                    a.GetProperty().SetOpacity(1.0)
                    a.GetProperty().SetLighting(False)
                    if "color" in e:
                        a._original_color = e["color"]
                    _tag_snt(a)
                    _apply_z_offset_to_actor(a, z_offset)
                    renderer.AddActor(a)
                    actors.append(a)
                    _cache(a, e.get("layer", "0"))

            fpath = str(Path(attachment.get("full_path", attachment["filename"])).resolve())
            actor_entry = {
                "filename":  attachment["filename"],
                "full_path": fpath,
                "actors":    actors,
            }
            self.app.snt_actors.append(actor_entry)
            self.app.dxf_actors.append(actor_entry)

            try:
                from gui.optimized_refresh import invalidate_dxf_actor_cache
                invalidate_dxf_actor_cache()
            except Exception:
                pass

            attachment["actors"] = actors

            if bounds_points.GetNumberOfPoints() > 0:
                temp_pd = vtk.vtkPolyData()
                temp_pd.SetPoints(bounds_points)
                renderer.ResetCamera(temp_pd.GetBounds())
            renderer.ResetCameraClippingRange()
            self.app.vtk_widget.render()
        except Exception as e:
            print(f"âŒ Render Error: {e}")

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
        if   mag > 100_000: desired_w, desired_h = 80.0, 20.0
        elif mag > 10_000:  desired_w, desired_h = 40.0, 10.0
        elif mag > 1_000:   desired_w, desired_h = 16.0,  4.0
        else:               desired_w, desired_h =  4.0,  1.0
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
        actor.SetPosition(pos[0] - half_w, pos[1] - half_h, pos[2] if len(pos) > 2 else 0.0)
        return actor

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


def show_snt_attachment_dialog(app) -> MultiSNTAttachmentDialog:
    if hasattr(app, "snt_dialog") and app.snt_dialog is not None:
        try:
            dlg = app.snt_dialog
            if dlg.isVisible():
                dlg.setWindowState(dlg.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
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
