# import os
# import numpy as np
# import laspy
# from PySide6.QtWidgets import QFileDialog, QMessageBox


# def _parse_filter(selected_filter: str):
#     sf = (selected_filter or "").lower()
#     if "laz" in sf and "1.2" in sf:
#         return ".laz", "1.2"
#     if "laz" in sf and "1.4" in sf:
#         return ".laz", "1.4"
#     if "las" in sf and "1.2" in sf:
#         return ".las", "1.2"
#     if "las" in sf and "1.4" in sf:
#         return ".las", "1.4"
#     return ".laz", "1.4"


# def _ensure_ext(path: str, ext: str) -> str:
#     root, cur_ext = os.path.splitext(path)
#     if cur_ext.lower() != ext.lower():
#         return root + ext
#     return path


# def _rgb_to_las16(rgb_arr):
#     """Convert RGB to LAS 16-bit (0..65535). Accepts float(0..1) / uint8 / uint16."""
#     if rgb_arr is None:
#         return None
#     rgb = np.asarray(rgb_arr)
#     if rgb.ndim != 2 or rgb.shape[1] != 3:
#         return None

#     if np.issubdtype(rgb.dtype, np.floating):
#         rgb = np.clip(rgb, 0.0, 1.0)
#         return (rgb * 65535.0).round().astype(np.uint16)

#     mx = int(rgb.max()) if rgb.size else 0
#     if mx <= 255:
#         return (rgb.astype(np.uint16) * 256)
#     return np.clip(rgb, 0, 65535).astype(np.uint16)


# def _intensity_to_uint16(intensity_arr, n_points: int):
#     """LAS intensity is uint16. If intensity is missing, return None."""
#     if intensity_arr is None:
#         return None
#     inten = np.asarray(intensity_arr)
#     if inten.shape[0] != n_points:
#         return None

#     if np.issubdtype(inten.dtype, np.floating):
#         mx = float(np.nanmax(inten)) if inten.size else 0.0
#         if mx <= 1.0:
#             inten = np.clip(inten, 0.0, 1.0) * 65535.0
#         inten = np.clip(inten, 0.0, 65535.0)
#         return inten.round().astype(np.uint16)

#     return np.clip(inten, 0, 65535).astype(np.uint16)


# def _choose_point_format(las_version: str, has_rgb: bool) -> int:
#     """
#     Use point formats valid for the chosen LAS version:
#       - LAS 1.2: 0 (no RGB) or 2 (RGB)
#       - LAS 1.4: 6 (no RGB) or 7 (RGB)
#     Intensity exists in all formats.
#     """
#     if las_version == "1.4":
#         return 7 if has_rgb else 6
#     return 2 if has_rgb else 0


# def save_pointcloud(app, path=None, file_format=None, las_version=None, show_dialog=True):
#     """
#     ✅ Save As behavior:
#     - Always opens OS Save dialog (browse local device) by default.
#     - Shows 4 file type options only:
#         .laz 1.2, .laz 1.4, .las 1.2, .las 1.4
#     - Removes the version popup completely.
#     """

#     data = getattr(app, "data", None)
#     if data is None or "xyz" not in data or data["xyz"] is None:
#         print("⚠️ No dataset loaded")
#         return

#     xyz = np.asarray(data["xyz"])
#     n = xyz.shape[0]

#     classes = data.get("classification")
#     if classes is None or np.asarray(classes).shape[0] != n:
#         classes = np.zeros(n, dtype=np.uint8)
#     else:
#         classes = np.asarray(classes)

#     rgb16 = _rgb_to_las16(data.get("rgb"))
#     intensity16 = _intensity_to_uint16(data.get("intensity"), n_points=n)

#     # ---------------------------------------------------------
#     # ✅ FORCE Save As dialog (even if caller passed a path)
#     # ---------------------------------------------------------
#     if show_dialog:
#         # initial name/folder suggestion
#         if path:
#             start_dir = os.path.dirname(path)
#             base_name = os.path.splitext(os.path.basename(path))[0] or "untitled"
#         elif getattr(app, "last_save_path", None):
#             start_dir = os.path.dirname(app.last_save_path)
#             base_name = os.path.splitext(os.path.basename(app.last_save_path))[0] or "untitled"
#         elif getattr(app, "loaded_file", None):
#             start_dir = os.path.dirname(app.loaded_file)
#             base_name = os.path.splitext(os.path.basename(app.loaded_file))[0] or "untitled"
#         else:
#             start_dir = ""
#             base_name = "untitled"

#         default_path = os.path.join(start_dir, base_name) if start_dir else base_name

#         filters = "LAZ 1.2 (*.laz);;LAZ 1.4 (*.laz);;LAS 1.2 (*.las);;LAS 1.4 (*.las)"
#         # ✅ Default filter should match the loaded file (extension + LAS version)
#         default_filter = "LAZ 1.4 (*.laz)"  # fallback

#         try:
#             loaded = getattr(app, "loaded_file", None) or getattr(app, "current_file_path", None)
#             if loaded:
#                 loaded_ext = os.path.splitext(loaded)[1].lower()  # .las / .laz

#                 # If we know the source LAS version, use it
#                 src_ver = None
#                 if hasattr(app, "data") and isinstance(app.data, dict):
#                     # if your loader stored it, prefer that
#                     src_ver = app.data.get("las_version") or app.data.get("version")

#                 # Fallback: try to detect by reading header (safe, small cost)
#                 if src_ver is None and loaded_ext in (".las", ".laz") and os.path.exists(loaded):
#                     try:
#                         hdr = laspy.read(loaded).header
#                         src_ver = f"{hdr.version.major}.{hdr.version.minor}"
#                     except Exception:
#                         src_ver = None

#                 # Normalize
#                 if src_ver not in ("1.2", "1.4"):
#                     src_ver = "1.4"

#                 if loaded_ext == ".las":
#                     default_filter = f"LAS {src_ver} (*.las)"
#                 else:
#                     default_filter = f"LAZ {src_ver} (*.laz)"

#         except Exception:
#             pass

#         picked_path, selected_filter = QFileDialog.getSaveFileName(
#             app,
#             "Save As",
#             default_path,
#             filters,
#             default_filter
#         )
#         if not picked_path:
#             return

#         ext, picked_version = _parse_filter(selected_filter)
#         path = _ensure_ext(picked_path, ext)

#         las_version = picked_version
#         file_format = "laz" if ext == ".laz" else "las"

#     # If someone calls it programmatically with show_dialog=False
#     if not path:
#         print("⚠️ No output path provided")
#         return

#     ext = os.path.splitext(path)[1].lower()
#     if ext not in (".las", ".laz"):
#         print(f"⚠️ Unsupported extension: {ext}")
#         return

#     # ✅ If Save (no dialog) and las_version not provided, infer from existing file header
#     if las_version is None:
#         probe = path
#         if not os.path.exists(probe):
#             probe = getattr(app, "loaded_file", None)

#         if probe and os.path.exists(probe):
#             try:
#                 with laspy.open(probe) as reader:
#                     hv = reader.header.version
#                     las_version = f"{hv.major}.{hv.minor}"
#             except Exception as e:
#                 print(f"⚠️ Could not infer LAS version from '{probe}': {e}")

#     # Final fallback
#     if las_version is None:
#         las_version = "1.4"

#     major, minor = map(int, las_version.split("."))

#     point_format_id = _choose_point_format(las_version, has_rgb=(rgb16 is not None))
#     header = laspy.LasHeader(point_format=point_format_id, version=f"{major}.{minor}")

#     # ✅ Embed CRS
#     try:
#         import pyproj
#         if getattr(app, "project_crs_wkt", None):
#             crs = pyproj.CRS.from_wkt(app.project_crs_wkt)
#             header.parse_crs(crs)
#             print("📌 Embedded CRS from WKT into LAS header")
#         elif getattr(app, "project_crs_epsg", None):
#             crs = pyproj.CRS.from_epsg(app.project_crs_epsg)
#             header.parse_crs(crs)
#             print(f"📌 Embedded CRS EPSG:{app.project_crs_epsg} into LAS header")
#     except Exception as e:
#         print(f"⚠️ Failed to embed CRS into {ext.upper()} header: {e}")

#     las = laspy.LasData(header)
#     las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

#     # ✅ Classification handling:
#     # - LAS 1.2 supports only 0..31 classification (legacy)
#     # - LAS 1.4 supports full 0..255 classification
#     classes_u8 = np.asarray(classes).astype(np.uint8, copy=False)
#     max_cls = int(classes_u8.max()) if classes_u8.size else 0

#     # ✅ Respect user's choice: if they selected 1.2, we SAVE as 1.2.
#     # LAS 1.2 cannot represent classes >31, so we clip (51 -> 31).
#     if las_version == "1.2" and max_cls > 31:
#         print(f"⚠️ Saving as LAS 1.2: clipping classification >31 (max={max_cls}).")

#     # Now assign classification based on final las_version
#     # ✅ Classification writing rules:
#     # - LAS 1.4: write true 0..255 classes into las.classification
#     # - LAS 1.2: write 0..31 into las.classification (spec limitation),
#     #            but preserve original class in las.user_data + marker VLR.

#     if las_version == "1.4":
#         las.classification = np.clip(classes_u8, 0, 255).astype(np.uint8, copy=False)

#     else:
#         # LAS 1.2
#         max_cls = int(classes_u8.max()) if classes_u8.size else 0

#         # Always write spec-compliant classification
#         las.classification = np.clip(classes_u8, 0, 31).astype(np.uint8, copy=False)

#         # Preserve true class codes if needed
#         if max_cls > 31:
#             try:
#                 # Store original 8-bit class here
#                 las.user_data = classes_u8

#                 # Add a marker VLR so we can restore on load
#                 marker = laspy.VLR(
#                     user_id="NakshaAI",
#                     record_id=1001,
#                     description="Original classification stored in user_data",
#                     record_data=b"orig_class=user_data"
#                 )
#                 # Avoid duplicates
#                 existing = False
#                 for v in getattr(las, "vlrs", []):
#                     if v.user_id.strip() == "NakshaAI" and int(v.record_id) == 1001:
#                         existing = True
#                         break
#                 if not existing:
#                     las.vlrs.append(marker)

#                 print("✅ LAS 1.2: preserved >31 classes using user_data + NakshaAI VLR (record_id=1001)")

#             except Exception as e:
#                 print(f"⚠️ LAS 1.2: could not preserve >31 classes in user_data: {e}")

#     if rgb16 is not None:
#         las.red, las.green, las.blue = rgb16[:, 0], rgb16[:, 1], rgb16[:, 2]
#     if intensity16 is not None:
#         las.intensity = intensity16

#     las.write(path)
#     print(f"💾 Saved {ext.upper()} {las_version}, Point Format {point_format_id}: {path}")

#     # .prj sidecar
#     prj_path = os.path.splitext(path)[0] + ".prj"
#     try:
#         if getattr(app, "project_crs_wkt", None):
#             with open(prj_path, "w") as f:
#                 f.write(app.project_crs_wkt)
#             print(f"📌 CRS WKT saved to {prj_path}")
#         elif getattr(app, "project_crs_epsg", None):
#             with open(prj_path, "w") as f:
#                 f.write(f"EPSG:{app.project_crs_epsg}")
#             print(f"📌 EPSG code saved to {prj_path}")
#     except Exception as e:
#         print(f"⚠️ Failed to write .prj: {e}")

#     app.last_save_path = path
#     app.last_save_format = file_format
#     app.last_save_version = las_version
#     if hasattr(app, "statusBar"):
#         app.statusBar().showMessage(f"Saved: {path}", 5000)


# # ---------------- QUICK AUTO-BACKUP SAVE ----------------
# def save_pointcloud_quick(app, path):
#     """
#     Silent quick-save version used for auto-backup.
#     ✅ UPDATED:
#       - Backup LAS version matches the loaded file (1.2 or 1.4)
#       - If saving as 1.2 and classes >31 exist, preserve originals in user_data + VLR marker
#         so your loader can restore them.
#     """
#     try:
#         data = getattr(app, "data", None)
#         if data is None or "xyz" not in data or data["xyz"] is None:
#             print("⚠️ No data to save for backup")
#             return

#         ext = os.path.splitext(path)[1].lower()
#         if ext not in (".las", ".laz"):
#             print(f"⚠️ Unsupported backup extension: {ext}")
#             return

#         xyz = np.asarray(data["xyz"])
#         n = xyz.shape[0]

#         # ---------- Determine backup LAS version (match loaded file) ----------
#         las_version = None

#         # Prefer what loader stored
#         try:
#             v = data.get("input_format_version", None)
#             if isinstance(v, tuple) and len(v) >= 2:
#                 las_version = f"{int(v[0])}.{int(v[1])}"
#         except Exception:
#             pass

#         # Fallback: read loaded file header
#         if las_version not in ("1.2", "1.4"):
#             probe = getattr(app, "loaded_file", None)
#             if probe and os.path.exists(probe):
#                 try:
#                     with laspy.open(probe) as reader:
#                         hv = reader.header.version
#                         las_version = f"{hv.major}.{hv.minor}"
#                 except Exception as e:
#                     print(f"⚠️ Could not infer LAS version for backup from '{probe}': {e}")

#         # Final fallback
#         if las_version not in ("1.2", "1.4"):
#             las_version = "1.4"

#         # ---------- Prepare attributes ----------
#         classes = data.get("classification", np.zeros(n, dtype=np.uint8))
#         classes_u8 = np.asarray(classes).astype(np.uint8, copy=False)
#         if classes_u8.shape[0] != n:
#             classes_u8 = np.zeros(n, dtype=np.uint8)

#         rgb16 = _rgb_to_las16(data.get("rgb"))
#         intensity16 = _intensity_to_uint16(data.get("intensity"), n_points=n)

#         # ---------- Header / point format ----------
#         point_format = _choose_point_format(las_version, has_rgb=(rgb16 is not None))
#         header = laspy.LasHeader(point_format=point_format, version=las_version)

#         # CRS embedding (keep silent-ish, but safe)
#         try:
#             import pyproj
#             if getattr(app, "project_crs_wkt", None):
#                 header.parse_crs(pyproj.CRS.from_wkt(app.project_crs_wkt))
#             elif getattr(app, "project_crs_epsg", None):
#                 header.parse_crs(pyproj.CRS.from_epsg(app.project_crs_epsg))
#         except Exception as e:
#             print(f"⚠️ CRS embedding skipped: {e}")

#         las = laspy.LasData(header)
#         las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

#         # ---------- Classification writing ----------
#         max_cls = int(classes_u8.max()) if classes_u8.size else 0

#         if las_version == "1.4":
#             # full 0..255
#             las.classification = np.clip(classes_u8, 0, 255).astype(np.uint8, copy=False)
#         else:
#             # LAS 1.2: classification is 0..31 in spec field
#             if max_cls > 31:
#                 print(f"⚠️ Backup LAS 1.2: clipping classification >31 (max={max_cls}) in classification field")
#             las.classification = np.clip(classes_u8, 0, 31).astype(np.uint8, copy=False)

#             # Preserve original classes in user_data + marker VLR for restore-on-load
#             if max_cls > 31:
#                 try:
#                     # user_data is standard and should exist for these point formats
#                     if "user_data" in las.point_format.dimension_names:
#                         las.user_data = classes_u8

#                         marker = laspy.VLR(
#                             user_id="NakshaAI",
#                             record_id=1001,
#                             description="Original classification stored in user_data",
#                             record_data=b"orig_class=user_data"
#                         )

#                         # Avoid duplicate markers
#                         already = any(
#                             (getattr(v, "user_id", "").strip() == "NakshaAI" and int(getattr(v, "record_id", -1)) == 1001)
#                             for v in getattr(las, "vlrs", [])
#                         )
#                         if not already:
#                             las.vlrs.append(marker)

#                         print("✅ Backup LAS 1.2: preserved >31 classes using user_data + NakshaAI VLR (1001)")
#                     else:
#                         print("⚠️ Backup LAS 1.2: user_data dimension not available; cannot preserve >31 classes")
#                 except Exception as e:
#                     print(f"⚠️ Backup LAS 1.2: failed to store original classes in user_data: {e}")

#         # ---------- RGB / intensity ----------
#         if rgb16 is not None:
#             las.red, las.green, las.blue = rgb16[:, 0], rgb16[:, 1], rgb16[:, 2]
#         if intensity16 is not None:
#             las.intensity = intensity16

#         # ---------- Write ----------
#         las.write(path)
#         print(f"💾 Auto-backup (LAS/LAZ) saved → {path} (version={las_version}, point_format={point_format})")

#     except Exception as e:
#         print(f"⚠️ Quick-save failed: {e}")

import os
import json
import numpy as np
import laspy
from PySide6.QtWidgets import QFileDialog, QMessageBox


def _parse_filter(selected_filter: str):
    sf = (selected_filter or "").lower()
    if "laz" in sf and "1.2" in sf:
        return ".laz", "1.2"
    if "laz" in sf and "1.4" in sf:
        return ".laz", "1.4"
    if "las" in sf and "1.2" in sf:
        return ".las", "1.2"
    if "las" in sf and "1.4" in sf:
        return ".las", "1.4"
    return ".laz", "1.4"


def _ensure_ext(path: str, ext: str) -> str:
    root, cur_ext = os.path.splitext(path)
    if cur_ext.lower() != ext.lower():
        return root + ext
    return path


def _rgb_to_las16(rgb_arr):
    """Convert RGB to LAS 16-bit (0..65535). Accepts float(0..1) / uint8 / uint16."""
    if rgb_arr is None:
        return None
    rgb = np.asarray(rgb_arr)
    if rgb.ndim != 2 or rgb.shape[1] != 3:
        return None

    if np.issubdtype(rgb.dtype, np.floating):
        rgb = np.clip(rgb, 0.0, 1.0)
        return (rgb * 65535.0).round().astype(np.uint16)

    mx = int(rgb.max()) if rgb.size else 0
    if mx <= 255:
        return (rgb.astype(np.uint16) * 256)
    return np.clip(rgb, 0, 65535).astype(np.uint16)


def _intensity_to_uint16(intensity_arr, n_points: int):
    """LAS intensity is uint16. If intensity is missing, return None."""
    if intensity_arr is None:
        return None
    inten = np.asarray(intensity_arr)
    if inten.shape[0] != n_points:
        return None

    if np.issubdtype(inten.dtype, np.floating):
        mx = float(np.nanmax(inten)) if inten.size else 0.0
        if mx <= 1.0:
            inten = np.clip(inten, 0.0, 1.0) * 65535.0
        inten = np.clip(inten, 0.0, 65535.0)
        return inten.round().astype(np.uint16)

    return np.clip(inten, 0, 65535).astype(np.uint16)


def _choose_point_format(las_version: str, has_rgb: bool) -> int:
    """
    Use point formats valid for the chosen LAS version:
      - LAS 1.2: 0 (no RGB) or 2 (RGB)
      - LAS 1.4: 6 (no RGB) or 7 (RGB)
    """
    if las_version == "1.4":
        return 7 if has_rgb else 6
    return 2 if has_rgb else 0


def _serialize_drawings(app) -> bytes:
    """
    Serialize all drawing objects from app into JSON bytes.
    ✅ FIXED: Proper numpy array handling
    """
    try:
        # Get drawings from digitizer if available
        if hasattr(app, 'digitizer') and hasattr(app.digitizer, 'drawings'):
            drawings = app.digitizer.drawings
            print(f"📐 Found {len(drawings)} drawings in digitizer")
        else:
            drawings = getattr(app, "drawings", [])
        
        if not drawings:
            print("ℹ️ No drawings to serialize")
            return b""
        
        serializable = []
        for obj in drawings:
            # ✅ FIXED: Handle numpy arrays properly
            coords = None
            if 'coords' in obj:
                coords = obj['coords']
            elif 'points' in obj:
                coords = obj['points']
            
            # Check if coords is valid
            if coords is None:
                print(f"  ⚠️ Skipping drawing with no coordinates")
                continue
            
            # Check if it's an empty array/list
            try:
                if isinstance(coords, np.ndarray):
                    if coords.size == 0:
                        print(f"  ⚠️ Skipping drawing with empty array")
                        continue
                elif len(coords) == 0:
                    print(f"  ⚠️ Skipping drawing with empty list")
                    continue
            except:
                print(f"  ⚠️ Skipping drawing with invalid coordinates")
                continue
            
            obj_copy = {
                'type': obj.get('type', 'line'),
                'points': []
            }
            
            # Convert coordinates safely
            try:
                if isinstance(coords, np.ndarray):
                    obj_copy['points'] = coords.tolist()
                elif isinstance(coords, list):
                    obj_copy['points'] = [[float(c) for c in pt] for pt in coords]
                else:
                    print(f"  ⚠️ Unknown coordinate format: {type(coords)}")
                    continue
            except Exception as e:
                print(f"  ⚠️ Failed to convert coordinates: {e}")
                continue
            
            # Copy metadata
            if 'text' in obj:
                obj_copy['text'] = str(obj['text'])
            
            # Handle color
            if 'original_color' in obj:
                obj_copy['color'] = [float(c) for c in obj['original_color']]
            elif 'color' in obj:
                color = obj['color']
                if isinstance(color, (list, tuple, np.ndarray)):
                    obj_copy['color'] = [float(c) for c in color]
            
            # Handle width
            if 'original_width' in obj:
                obj_copy['width'] = float(obj['original_width'])
            elif 'width' in obj:
                obj_copy['width'] = float(obj['width'])
            
            serializable.append(obj_copy)
        
        if not serializable:
            print("ℹ️ No valid drawings after processing")
            return b""
        
        json_str = json.dumps(serializable, separators=(',', ':'))
        print(f"✅ Serialized {len(serializable)} drawing(s) to JSON ({len(json_str)} bytes)")
        return json_str.encode('utf-8')
    
    except Exception as e:
        print(f"⚠️ Failed to serialize drawings: {e}")
        import traceback
        traceback.print_exc()
        return b""


def _deserialize_drawings(data: bytes) -> list:
    """
    Deserialize drawing objects from JSON bytes.
    Returns list of drawing dictionaries.
    """
    try:
        if not data:
            return []
        json_str = data.decode('utf-8')
        drawings = json.loads(json_str)
        
        # Convert lists back to numpy arrays where needed
        for obj in drawings:
            if 'points' in obj and isinstance(obj['points'], list):
                obj['points'] = np.array(obj['points'])
            if 'properties' in obj and isinstance(obj['properties'], dict):
                for key, val in obj['properties'].items():
                    if isinstance(val, list) and key in ['color', 'vertices']:
                        obj['properties'][key] = np.array(val)
        
        return drawings
    
    except Exception as e:
        print(f"⚠️ Failed to deserialize drawings: {e}")
        return []

def load_drawings_from_las(las_path: str, app):
    """
    Load digitized drawings from VLR in existing LAS/LAZ file.
    ✅ FIXED: Stores drawings temporarily, to be restored AFTER point cloud renders
    """
    try:
        with laspy.open(las_path) as reader:
            for vlr in reader.header.vlrs:
                if vlr.user_id.strip() == "NakshaAI" and int(vlr.record_id) == 1002:
                    print("📐 Found drawing data in LAS file")
                    drawings = _deserialize_drawings(vlr.record_data)
                    
                    if not hasattr(app, 'digitizer') or not hasattr(app.digitizer, 'drawings'):
                        print("⚠️ Digitizer not available, skipping drawing load")
                        return False
                    
                    # ✅ CRITICAL FIX: Store for later, don't add to renderer yet
                    app._pending_drawings_restore = drawings
                    print(f"💾 Stored {len(drawings)} drawings for post-render restoration")
                    
                    return True
        
        # No drawings found
        if hasattr(app, 'digitizer'):
            if not hasattr(app.digitizer, 'drawings'):
                app.digitizer.drawings = []
        
        return False
    
    except Exception as e:
        print(f"⚠️ Failed to load drawings from {las_path}: {e}")
        import traceback
        traceback.print_exc()
        
        if hasattr(app, 'digitizer'):
            if not hasattr(app.digitizer, 'drawings'):
                app.digitizer.drawings = []
        
        return False
    
    

def finalize_drawing_render(app):
    """
    ✅ Restore drawings AFTER point cloud is rendered - forces them ON TOP
    """
    if not hasattr(app, '_pending_drawings_restore'):
        return
    
    drawings = app._pending_drawings_restore
    delattr(app, '_pending_drawings_restore')
    
    if not drawings:
        return
    
    print(f"\n{'='*60}")
    print(f"🎨 RESTORING {len(drawings)} DRAWINGS ON TOP")
    print(f"{'='*60}")
    
    try:
        app.digitizer.drawings = []  # Clear existing
        renderer = app.vtk_widget.renderer
        
        for drawing_data in drawings:
            coords = drawing_data.get('points', [])
            
            if len(coords) == 0:
                continue
            
            # Create actor
            actor = app.digitizer._make_polyline_actor(
                coords,
                color=drawing_data.get('color', (1, 0, 0)),
                width=drawing_data.get('width', 2)
            )
            
            if actor:
                # ✅ Force rendering ON TOP with multiple strategies
                try:
                    # Strategy 1: Polygon offset (pulls toward camera)
                    mapper = actor.GetMapper()
                    if mapper:
                        mapper.SetResolveCoincidentTopologyToPolygonOffset()
                        mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-2.0, -2.0)
                    
                    # Strategy 2: Thick, bright lines
                    prop = actor.GetProperty()
                    width = drawing_data.get('width', 2)
                    prop.SetLineWidth(max(5, width * 2))
                    prop.SetOpacity(1.0)
                    
                    # Strategy 3: Disable lighting
                    prop.LightingOff()
                    
                    # Strategy 4: Render as tubes for visibility
                    prop.SetRenderLinesAsTubes(True)
                    
                except Exception as e:
                    print(f"  ⚠️ Render setup warning: {e}")
                
                # Add to renderer (will be added AFTER point cloud)
                renderer.AddActor(actor)
                
                entry = {
                    'type': drawing_data.get('type', 'line'),
                    'coords': coords,
                    'actor': actor,
                    'bounds': actor.GetBounds(),
                    'original_color': drawing_data.get('color', (1, 0, 0)),
                    'original_width': drawing_data.get('width', 2)
                }
                
                if 'text' in drawing_data:
                    entry['text'] = drawing_data['text']
                
                app.digitizer.drawings.append(entry)
        
        print(f"✅ {len(app.digitizer.drawings)} drawings restored ON TOP")
        
        # Reset clipping range
        renderer.ResetCameraClippingRange()
        
        # Force render
        renderer.GetRenderWindow().Render()
        
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"❌ Drawing restoration failed: {e}")
        import traceback
        traceback.print_exc()
    
def debug_renderer_setup(app):
    """Debug helper to understand renderer configuration"""
    print("\n🔍 RENDERER DEBUG:")
    
    if hasattr(app, 'digitizer'):
        print(f"  Digitizer renderer: {id(app.digitizer.renderer)}")
    
    if hasattr(app, 'vtk_widget'):
        print(f"  VTK widget renderer: {id(app.vtk_widget.renderer)}")
        
    if hasattr(app, 'renderer'):
        print(f"  App renderer: {id(app.renderer)}")
    
    # Check if they're the same object
    if hasattr(app, 'digitizer') and hasattr(app, 'vtk_widget'):
        same = app.digitizer.renderer == app.vtk_widget.renderer
        print(f"  Same renderer? {same}")
    
    print()    

def save_pointcloud(app, path=None, file_format=None, las_version=None, show_dialog=True):
    """
    ✅ Enhanced Save behavior:
    - Saves point cloud data (XYZ, RGB, classification, intensity)
    - Saves digitized drawings (lines, polygons, annotations) as VLR
    - Drawings are fully editable after reload
    """

    data = getattr(app, "data", None)
    if data is None or "xyz" not in data or data["xyz"] is None:
        print("⚠️ No dataset loaded")
        return

    xyz = np.asarray(data["xyz"])
    n = xyz.shape[0]

    classes = data.get("classification")
    if classes is None or np.asarray(classes).shape[0] != n:
        classes = np.zeros(n, dtype=np.uint8)
    else:
        classes = np.asarray(classes)

    rgb16 = _rgb_to_las16(data.get("rgb"))
    intensity16 = _intensity_to_uint16(data.get("intensity"), n_points=n)

    # ---------------------------------------------------------
    # ✅ Save As dialog
    # ---------------------------------------------------------
    if show_dialog:
        if path:
            start_dir = os.path.dirname(path)
            base_name = os.path.splitext(os.path.basename(path))[0] or "untitled"
        elif getattr(app, "last_save_path", None):
            start_dir = os.path.dirname(app.last_save_path)
            base_name = os.path.splitext(os.path.basename(app.last_save_path))[0] or "untitled"
        elif getattr(app, "loaded_file", None):
            start_dir = os.path.dirname(app.loaded_file)
            base_name = os.path.splitext(os.path.basename(app.loaded_file))[0] or "untitled"
        else:
            start_dir = ""
            base_name = "untitled"

        default_path = os.path.join(start_dir, base_name) if start_dir else base_name

        filters = "LAZ 1.2 (*.laz);;LAZ 1.4 (*.laz);;LAS 1.2 (*.las);;LAS 1.4 (*.las)"
        default_filter = "LAZ 1.4 (*.laz)"

        try:
            loaded = getattr(app, "loaded_file", None) or getattr(app, "current_file_path", None)
            if loaded:
                loaded_ext = os.path.splitext(loaded)[1].lower()
                src_ver = None
                if hasattr(app, "data") and isinstance(app.data, dict):
                    src_ver = app.data.get("las_version") or app.data.get("version")

                if src_ver is None and loaded_ext in (".las", ".laz") and os.path.exists(loaded):
                    try:
                        hdr = laspy.read(loaded).header
                        src_ver = f"{hdr.version.major}.{hdr.version.minor}"
                    except Exception:
                        src_ver = None

                if src_ver not in ("1.2", "1.4"):
                    src_ver = "1.4"

                if loaded_ext == ".las":
                    default_filter = f"LAS {src_ver} (*.las)"
                else:
                    default_filter = f"LAZ {src_ver} (*.laz)"

        except Exception:
            pass

        picked_path, selected_filter = QFileDialog.getSaveFileName(
            app,
            "Save As",
            default_path,
            filters,
            default_filter
        )
        if not picked_path:
            return

        ext, picked_version = _parse_filter(selected_filter)
        path = _ensure_ext(picked_path, ext)

        las_version = picked_version
        file_format = "laz" if ext == ".laz" else "las"

    if not path:
        print("⚠️ No output path provided")
        return

    ext = os.path.splitext(path)[1].lower()
    if ext not in (".las", ".laz"):
        print(f"⚠️ Unsupported extension: {ext}")
        return

    # Infer version if needed
    if las_version is None:
        probe = path
        if not os.path.exists(probe):
            probe = getattr(app, "loaded_file", None)

        if probe and os.path.exists(probe):
            try:
                with laspy.open(probe) as reader:
                    hv = reader.header.version
                    las_version = f"{hv.major}.{hv.minor}"
            except Exception as e:
                print(f"⚠️ Could not infer LAS version from '{probe}': {e}")

    if las_version is None:
        las_version = "1.4"

    major, minor = map(int, las_version.split("."))

    point_format_id = _choose_point_format(las_version, has_rgb=(rgb16 is not None))
    header = laspy.LasHeader(point_format=point_format_id, version=f"{major}.{minor}")

    # Embed CRS
    try:
        import pyproj
        if getattr(app, "project_crs_wkt", None):
            crs = pyproj.CRS.from_wkt(app.project_crs_wkt)
            header.parse_crs(crs)
            print("📌 Embedded CRS from WKT into LAS header")
        elif getattr(app, "project_crs_epsg", None):
            crs = pyproj.CRS.from_epsg(app.project_crs_epsg)
            header.parse_crs(crs)
            print(f"📌 Embedded CRS EPSG:{app.project_crs_epsg} into LAS header")
    except Exception as e:
        print(f"⚠️ Failed to embed CRS into {ext.upper()} header: {e}")

    las = laspy.LasData(header)
    las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

    # Classification handling
    classes_u8 = np.asarray(classes).astype(np.uint8, copy=False)
    max_cls = int(classes_u8.max()) if classes_u8.size else 0

    if las_version == "1.2" and max_cls > 31:
        print(f"⚠️ Saving as LAS 1.2: clipping classification >31 (max={max_cls}).")

    if las_version == "1.4":
        las.classification = np.clip(classes_u8, 0, 255).astype(np.uint8, copy=False)
    else:
        las.classification = np.clip(classes_u8, 0, 31).astype(np.uint8, copy=False)

        if max_cls > 31:
            try:
                las.user_data = classes_u8
                marker = laspy.VLR(
                    user_id="NakshaAI",
                    record_id=1001,
                    description="Original classification stored in user_data",
                    record_data=b"orig_class=user_data"
                )
                existing = False
                for v in getattr(las, "vlrs", []):
                    if v.user_id.strip() == "NakshaAI" and int(v.record_id) == 1001:
                        existing = True
                        break
                if not existing:
                    las.vlrs.append(marker)

                print("✅ LAS 1.2: preserved >31 classes using user_data + NakshaAI VLR (record_id=1001)")

            except Exception as e:
                print(f"⚠️ LAS 1.2: could not preserve >31 classes in user_data: {e}")

    if rgb16 is not None:
        las.red, las.green, las.blue = rgb16[:, 0], rgb16[:, 1], rgb16[:, 2]
    if intensity16 is not None:
        las.intensity = intensity16

    # ---------------------------------------------------------
    # ✅ NEW: Save digitized drawings as VLR (record_id=1002)
    # ---------------------------------------------------------
    # ---------------------------------------------------------
    # ✅ NEW: Save digitized drawings as VLR (record_id=1002)
    # ---------------------------------------------------------
    try:
        drawing_data = _serialize_drawings(app)
        if drawing_data:
            # ✅ Decode to count actual drawings
            decoded = json.loads(drawing_data.decode('utf-8'))
            print(f"✅ Prepared {len(decoded)} drawings for VLR")
            
            drawing_vlr = laspy.VLR(
                user_id="NakshaAI",
                record_id=1002,
                description="Digitized drawings (lines, polygons, annotations)",
                record_data=drawing_data
            )
            
            # Remove old drawing VLR if exists
            las.vlrs = [v for v in getattr(las, "vlrs", []) 
                    if not (v.user_id.strip() == "NakshaAI" and int(v.record_id) == 1002)]
            
            las.vlrs.append(drawing_vlr)
            print(f"📐 Saved {len(decoded)} drawing object(s) to VLR")

    except Exception as e:
        print(f"⚠️ Failed to save drawings: {e}")
        import traceback
        traceback.print_exc()

    las.write(path)
    print(f"💾 Saved {ext.upper()} {las_version}, Point Format {point_format_id}: {path}")

    # .prj sidecar
    prj_path = os.path.splitext(path)[0] + ".prj"
    try:
        if getattr(app, "project_crs_wkt", None):
            with open(prj_path, "w") as f:
                f.write(app.project_crs_wkt)
            print(f"📌 CRS WKT saved to {prj_path}")
        elif getattr(app, "project_crs_epsg", None):
            with open(prj_path, "w") as f:
                f.write(f"EPSG:{app.project_crs_epsg}")
            print(f"📌 EPSG code saved to {prj_path}")
    except Exception as e:
        print(f"⚠️ Failed to write .prj: {e}")

    app.last_save_path = path
    app.last_save_format = file_format
    app.last_save_version = las_version
    if hasattr(app, "statusBar"):
        app.statusBar().showMessage(f"Saved: {path}", 5000)


# ---------------- QUICK AUTO-BACKUP SAVE ----------------
def save_pointcloud_quick(app, path):
    """
    Silent quick-save version used for auto-backup.
    ✅ Also saves drawings.
    """
    try:
        data = getattr(app, "data", None)
        if data is None or "xyz" not in data or data["xyz"] is None:
            print("⚠️ No data to save for backup")
            return

        ext = os.path.splitext(path)[1].lower()
        if ext not in (".las", ".laz"):
            print(f"⚠️ Unsupported backup extension: {ext}")
            return

        xyz = np.asarray(data["xyz"])
        n = xyz.shape[0]

        # Determine backup LAS version
        las_version = None
        try:
            v = data.get("input_format_version", None)
            if isinstance(v, tuple) and len(v) >= 2:
                las_version = f"{int(v[0])}.{int(v[1])}"
        except Exception:
            pass

        if las_version not in ("1.2", "1.4"):
            probe = getattr(app, "loaded_file", None)
            if probe and os.path.exists(probe):
                try:
                    with laspy.open(probe) as reader:
                        hv = reader.header.version
                        las_version = f"{hv.major}.{hv.minor}"
                except Exception as e:
                    print(f"⚠️ Could not infer LAS version for backup: {e}")

        if las_version not in ("1.2", "1.4"):
            las_version = "1.4"

        classes = data.get("classification", np.zeros(n, dtype=np.uint8))
        classes_u8 = np.asarray(classes).astype(np.uint8, copy=False)
        if classes_u8.shape[0] != n:
            classes_u8 = np.zeros(n, dtype=np.uint8)

        rgb16 = _rgb_to_las16(data.get("rgb"))
        intensity16 = _intensity_to_uint16(data.get("intensity"), n_points=n)

        point_format = _choose_point_format(las_version, has_rgb=(rgb16 is not None))
        header = laspy.LasHeader(point_format=point_format, version=las_version)

        try:
            import pyproj
            if getattr(app, "project_crs_wkt", None):
                header.parse_crs(pyproj.CRS.from_wkt(app.project_crs_wkt))
            elif getattr(app, "project_crs_epsg", None):
                header.parse_crs(pyproj.CRS.from_epsg(app.project_crs_epsg))
        except Exception as e:
            print(f"⚠️ CRS embedding skipped: {e}")

        las = laspy.LasData(header)
        las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

        max_cls = int(classes_u8.max()) if classes_u8.size else 0

        if las_version == "1.4":
            las.classification = np.clip(classes_u8, 0, 255).astype(np.uint8, copy=False)
        else:
            if max_cls > 31:
                print(f"⚠️ Backup LAS 1.2: clipping classification >31 (max={max_cls})")
            las.classification = np.clip(classes_u8, 0, 31).astype(np.uint8, copy=False)

            if max_cls > 31:
                try:
                    if "user_data" in las.point_format.dimension_names:
                        las.user_data = classes_u8

                        marker = laspy.VLR(
                            user_id="NakshaAI",
                            record_id=1001,
                            description="Original classification stored in user_data",
                            record_data=b"orig_class=user_data"
                        )

                        already = any(
                            (getattr(v, "user_id", "").strip() == "NakshaAI" and int(getattr(v, "record_id", -1)) == 1001)
                            for v in getattr(las, "vlrs", [])
                        )
                        if not already:
                            las.vlrs.append(marker)

                        print("✅ Backup LAS 1.2: preserved >31 classes using user_data")
                except Exception as e:
                    print(f"⚠️ Backup LAS 1.2: failed to store original classes: {e}")

        if rgb16 is not None:
            las.red, las.green, las.blue = rgb16[:, 0], rgb16[:, 1], rgb16[:, 2]
        if intensity16 is not None:
            las.intensity = intensity16

        # ✅ Save drawings in backup
        try:
            drawing_data = _serialize_drawings(app)
            if drawing_data:
                drawing_vlr = laspy.VLR(
                    user_id="NakshaAI",
                    record_id=1002,
                    description="Digitized drawings",
                    record_data=drawing_data
                )
                las.vlrs = [v for v in getattr(las, "vlrs", []) 
                           if not (v.user_id.strip() == "NakshaAI" and int(v.record_id) == 1002)]
                las.vlrs.append(drawing_vlr)
        except Exception as e:
            print(f"⚠️ Backup: failed to save drawings: {e}")

        las.write(path)
        print(f"💾 Auto-backup saved → {path} (version={las_version}, point_format={point_format})")

    except Exception as e:
        print(f"⚠️ Quick-save failed: {e}")