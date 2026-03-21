import numpy as np
import open3d as o3d
import os
import laspy
from PySide6.QtWidgets import QDialog
from pyproj import CRS
from laspy.vlrs.known import WktCoordinateSystemVlr

from .dialogs.load_pointcloud_dialog import LoadPointCloudDialog

def restore_class_from_user_data_if_marked(las_obj) -> np.ndarray | None:
    """
    If this LAZ/LAS was saved by Naksha as LAS 1.2 with original classes stored
    in user_data, restore them.
    """
    try:
        # Collect VLRs from both las and header (depending on laspy version)
        vlrs = []
        if hasattr(las_obj, "vlrs") and las_obj.vlrs:
            vlrs.extend(list(las_obj.vlrs))
        if hasattr(las_obj, "header") and hasattr(las_obj.header, "vlrs") and las_obj.header.vlrs:
            vlrs.extend(list(las_obj.header.vlrs))

        has_marker = any(
            (getattr(v, "user_id", "").strip() == "NakshaAI" and int(getattr(v, "record_id", -1)) == 1001)
            for v in vlrs
        )
        if not has_marker:
            return None

        if "user_data" not in las_obj.point_format.dimension_names:
            return None

        ud = np.asarray(las_obj.user_data, dtype=np.uint8)
        if ud.size == 0:
            return None

        npts = len(las_obj.x)
        if ud.shape[0] != npts:
            return None

        if int(ud.max()) > 31:
            print("✅ Restored original classification from user_data (NakshaAI marker VLR found)")
            return ud

        return None

    except Exception as e:
        print(f"⚠️ Restore-from-user_data failed: {e}")
        return None


# ---------------- Main Loader ----------------
def load_lidar_file(filename, parent=None):
    """Load LAS/LAZ/PLY with dialog settings applied."""

    def is_valid_las_signature(file_path):
        try:
            with open(file_path, 'rb') as f:
                signature = f.read(4)
                print(f"🔍 File signature: {signature!r} ({signature.hex()})")
                return signature == b'LASF'
        except Exception as e:
            print(f"❌ Cannot read file header: {e}")
            return False
    # --- LAS/LAZ ---
    if filename.lower().endswith((".las", ".laz")):
        las = laspy.read(filename)

        dlg = LoadPointCloudDialog(filename, parent)
        if dlg.exec() != QDialog.Accepted:
            return None

        xyz = np.vstack([las.x, las.y, las.z]).T

        rgb = None
        if dlg.attr_checks["Color"].isChecked() and {"red", "green", "blue"}.issubset(las.point_format.dimension_names):
            rgb = np.vstack([las.red, las.green, las.blue]).T / 65535.0

        intensity = None
        if dlg.attr_checks["Intensity"].isChecked() and "intensity" in las.point_format.dimension_names:
            intensity = las.intensity.astype(float)

        # ============================================================
        # ✅ CRITICAL FIX: Handle extended classification properly
        # ============================================================
        classification = None
        if "classification" in las.point_format.dimension_names:

            # ✅ FIRST: try restore from user_data if this is a Naksha LAS 1.2 “preserve classes” file
            restored = restore_class_from_user_data_if_marked(las)
            if restored is not None:
                classification = restored
            else:
                # --- keep your existing version-based logic exactly as it is ---
                version = las.header.version
                if isinstance(version, str):
                    major, minor = map(int, version.split('.'))
                else:
                    major, minor = version.major, version.minor

                print(f"\n{'='*60}")
                print(f"📄 LAS File Version: {major}.{minor}")
                print(f"   Point Format: {las.header.point_format.id}")

                if major == 1 and minor >= 4:
                    print(f"   ✅ LAS 1.4+ detected - using full 8-bit classification")
                    if hasattr(las, 'classification'):
                        classification = np.array(las.classification, dtype=np.uint8)
                    else:
                        classification = np.array(las.raw_classification, dtype=np.uint8)
                else:
                    print(f"   ⚠️ LAS {major}.{minor} - checking for extended classes...")
                    if hasattr(las, 'raw_classification'):
                        raw_class = np.array(las.raw_classification, dtype=np.uint8)
                        max_class = raw_class.max()
                        if max_class > 31:
                            print(f"   🔧 Extended classes detected (max={max_class}) in LAS {major}.{minor}")
                            print(f"   🔧 Using raw classification to preserve classes > 31")
                            classification = raw_class
                        else:
                            classification = np.array(las.classification, dtype=np.uint8)
                    else:
                        classification = np.array(las.classification, dtype=np.uint8)

                unique_classes = np.unique(classification)
                print(f"   📊 Unique classes found: {unique_classes}")

                if 51 in unique_classes:
                    count_51 = np.sum(classification == 51)
                    print(f"   ✅ Class 51 (noise): {count_51:,} points CORRECTLY PRESERVED")
                if 19 in unique_classes:
                    count_19 = np.sum(classification == 19)
                    print(f"   📍 Class 19: {count_19:,} points")

                print(f"{'='*60}\n")

        # ✅ Extract CRS
        crs_wkt, crs_epsg = None, None
        try:
            crs = las.header.parse_crs()
            if crs:
                crs_wkt = crs.to_wkt()
                try:
                    crs_epsg = crs.to_epsg()
                except Exception:
                    crs_epsg = None
        except Exception as e:
            print(f"⚠️ CRS not found in LAS/LAZ header: {e}")

        # ✅ Extract version & point format for later save
        version_str = las.header.version
        if isinstance(version_str, tuple):
            version = version_str
        else:
            version = tuple(map(int, version_str.split(".")))

        # ✅ Remember file path for autosave
        if parent is not None:
            parent.loaded_file = filename
            parent.last_save_path = filename
            try:
                from .save_pointcloud import load_drawings_from_las
                load_drawings_from_las(filename, parent)
            except Exception as e:
                print(f"⚠️ Could not load drawings: {e}")
            
        return {
            "xyz": xyz,
            "rgb": rgb,
            "intensity": intensity,
            "classification": classification,
            "crs_wkt": crs_wkt,
            "crs_epsg": crs_epsg,
            "input_format_version": version,
            "input_point_format": las.header.point_format.id,
            "type": "las",
        }

    # --- PLY ---
    elif filename.lower().endswith(".ply"):
        pcd = o3d.io.read_point_cloud(filename)
        
        # ✅ Remember file path for autosave
        if parent is not None:
            parent.loaded_file = filename
            parent.last_save_path = filename
            
            try:
                from .save_pointcloud import load_drawings_from_las
                load_drawings_from_las(filename, parent)
            except Exception as e:
                print(f"⚠️ Could not load drawings: {e}")
            
        return {
            "xyz": np.asarray(pcd.points),
            "rgb": np.asarray(pcd.colors),
            "intensity": None,
            "classification": None,
            "crs_wkt": None,
            "crs_epsg": None,
            "type": "ply",
        }

    else:
        raise ValueError("Unsupported format")