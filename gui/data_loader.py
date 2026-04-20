import laspy
import numpy as np
import open3d as o3d
from PySide6.QtWidgets import QDialog

from .dialogs.load_pointcloud_dialog import DEFAULT_IMPORT_OPTIONS, LoadPointCloudDialog


def restore_class_from_user_data_if_marked(las_obj) -> np.ndarray | None:
    """
    If this LAZ/LAS was saved by Naksha as LAS 1.2 with original classes stored
    in user_data, restore them.
    """
    try:
        vlrs = []
        if hasattr(las_obj, "vlrs") and las_obj.vlrs:
            vlrs.extend(list(las_obj.vlrs))
        if hasattr(las_obj, "header") and hasattr(las_obj.header, "vlrs") and las_obj.header.vlrs:
            vlrs.extend(list(las_obj.header.vlrs))

        has_marker = any(
            (
                getattr(v, "user_id", "").strip() == "NakshaAI"
                and int(getattr(v, "record_id", -1)) == 1001
            )
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
            print("Restored original classification from user_data (NakshaAI marker VLR found)")
            return ud

        return None

    except Exception as exc:
        print(f"Restore-from-user_data failed: {exc}")
        return None


def get_default_lidar_import_options(disabled_attrs=None):
    disabled_attrs = set(disabled_attrs or [])
    options = {
        key: value
        for key, value in DEFAULT_IMPORT_OPTIONS.items()
        if key != "attributes"
    }
    options["attributes"] = dict(DEFAULT_IMPORT_OPTIONS["attributes"])
    for attr_name in disabled_attrs:
        if attr_name in options["attributes"]:
            options["attributes"][attr_name] = False
    return options


def _merge_import_options(import_options=None, disabled_attrs=None):
    merged = get_default_lidar_import_options(disabled_attrs)
    if not import_options:
        return merged

    for key, value in import_options.items():
        if key == "attributes" and isinstance(value, dict):
            merged["attributes"].update(value)
        else:
            merged[key] = value

    for attr_name in set(disabled_attrs or []):
        if attr_name in merged["attributes"]:
            merged["attributes"][attr_name] = False

    return merged


def prompt_lidar_import_options(filename, parent=None, disabled_attrs=None, initial_options=None):
    dlg = LoadPointCloudDialog(
        filename,
        parent=parent,
        disabled_attrs=disabled_attrs,
        initial_options=initial_options,
    )
    if dlg.exec() != QDialog.Accepted:
        return None
    return dlg.get_import_options()


def _extract_classification_array(las):
    classification = None
    if "classification" not in las.point_format.dimension_names:
        return classification

    restored = restore_class_from_user_data_if_marked(las)
    if restored is not None:
        return restored

    version = las.header.version
    if isinstance(version, str):
        major, minor = map(int, version.split("."))
    else:
        major, minor = version.major, version.minor

    print(f"\n{'=' * 60}")
    print(f"LAS File Version: {major}.{minor}")
    print(f"   Point Format: {las.header.point_format.id}")

    if major == 1 and minor >= 4:
        print("   LAS 1.4+ detected - using full 8-bit classification")
        if hasattr(las, "classification"):
            classification = np.array(las.classification, dtype=np.uint8)
        else:
            classification = np.array(las.raw_classification, dtype=np.uint8)
    else:
        print(f"   LAS {major}.{minor} - checking for extended classes...")
        if hasattr(las, "raw_classification"):
            raw_class = np.array(las.raw_classification, dtype=np.uint8)
            max_class = raw_class.max()
            if max_class > 31:
                print(f"   Extended classes detected (max={max_class}) in LAS {major}.{minor}")
                print("   Using raw classification to preserve classes > 31")
                classification = raw_class
            else:
                classification = np.array(las.classification, dtype=np.uint8)
        else:
            classification = np.array(las.classification, dtype=np.uint8)

    unique_classes = np.unique(classification)
    print(f"   Unique classes found: {unique_classes}")

    if 51 in unique_classes:
        count_51 = np.sum(classification == 51)
        print(f"   Class 51 (noise): {count_51:,} points correctly preserved")
    if 19 in unique_classes:
        count_19 = np.sum(classification == 19)
        print(f"   Class 19: {count_19:,} points")

    print(f"{'=' * 60}\n")
    return classification


def _extract_crs(las):
    crs_wkt = None
    crs_epsg = None

    try:
        crs = las.header.parse_crs()
        if crs:
            crs_wkt = crs.to_wkt()
            try:
                crs_epsg = crs.to_epsg()
            except Exception:
                crs_epsg = None
    except Exception as exc:
        print(f"CRS not found in LAS/LAZ header: {exc}")

    return crs_wkt, crs_epsg


def _apply_import_filters(xyz, rgb, intensity, classification, options):
    total_points = len(xyz)
    if total_points == 0:
        return xyz, rgb, intensity, classification

    mask = np.ones(total_points, dtype=bool)

    nth_point = max(1, int(options.get("nth_point", 1) or 1))
    if options.get("only_every") and nth_point > 1:
        nth_mask = np.zeros(total_points, dtype=bool)
        nth_mask[::nth_point] = True
        mask &= nth_mask

    if options.get("only_class") and classification is not None:
        mask &= classification == int(options.get("class_code", 0))

    if mask.all():
        return xyz, rgb, intensity, classification

    xyz = xyz[mask]
    if rgb is not None:
        rgb = rgb[mask]
    if intensity is not None:
        intensity = intensity[mask]
    if classification is not None:
        classification = classification[mask]
    return xyz, rgb, intensity, classification


def load_lidar_file(
    filename,
    parent=None,
    import_options=None,
    prompt_user=True,
    disabled_attrs=None,
):
    """Load LAS/LAZ/PLY, optionally prompting for import settings first."""

    if filename.lower().endswith((".las", ".laz")):
        options = _merge_import_options(import_options, disabled_attrs)
        if prompt_user:
            options = prompt_lidar_import_options(
                filename,
                parent=parent,
                disabled_attrs=disabled_attrs,
                initial_options=options,
            )
            if options is None:
                return None

        las = laspy.read(filename)

        xyz = np.vstack([las.x, las.y, las.z]).T

# ✅ REPLACE WITH THIS:
        attrs = options.get("attributes", {}) if isinstance(options, dict) else {}
        rgb = None
        # Check if RGB channels exist in the file
        _has_rgb_fields = (
            hasattr(las, 'red') and
            hasattr(las, 'green') and
            hasattr(las, 'blue')
        )

        if _has_rgb_fields:
            if attrs.get("Color", True):
                r = np.asarray(las.red,   dtype=np.uint32)
                g = np.asarray(las.green, dtype=np.uint32)
                b = np.asarray(las.blue,  dtype=np.uint32)

                raw_max = int(max(r.max(), g.max(), b.max()))
                print(f"  🔍 RGB raw: dtype=uint16, max={raw_max}")

                if raw_max > 255:
                    # Standard LAS uint16 [0-65535] → uint8 [0-255]
                    rgb = np.column_stack([
                        (r // 257).astype(np.uint8),
                        (g // 257).astype(np.uint8),
                        (b // 257).astype(np.uint8),
                    ])
                else:
                    # Already in uint8 range
                    rgb = np.column_stack([
                        r.astype(np.uint8),
                        g.astype(np.uint8),
                        b.astype(np.uint8),
                    ])

                print(f"  ✅ RGB ready: max={rgb.max()}, min={rgb.min()}, mean={rgb.mean():.1f}")
            else:
                print(f"  ⚠️ RGB skipped (Color=False in options)")
        else:
            print(f"  ⚠️ No RGB fields in file")

        intensity = None
        if attrs.get("Intensity", False) and "intensity" in las.point_format.dimension_names:
            intensity = las.intensity.astype(float)

        classification = _extract_classification_array(las)
        xyz, rgb, intensity, classification = _apply_import_filters(
            xyz, rgb, intensity, classification, options
        )

        crs_wkt, crs_epsg = _extract_crs(las)

        version_str = las.header.version
        if isinstance(version_str, tuple):
            version = version_str
        else:
            version = tuple(map(int, str(version_str).split(".")))

        if parent is not None:
            parent.loaded_file = filename
            parent.last_save_path = filename
            try:
                from .save_pointcloud import load_drawings_from_las

                load_drawings_from_las(filename, parent)
            except Exception as exc:
                print(f"Could not load drawings: {exc}")

        return {
            "xyz": xyz,
            "rgb": rgb,
            "intensity": intensity,
            "classification": classification,
            "crs_wkt": crs_wkt,
            "crs_epsg": crs_epsg,
            "input_format_version": version,
            "input_point_format": las.header.point_format.id,
            "import_options": options,
            "type": "las",
        }

    if filename.lower().endswith(".ply"):
        pcd = o3d.io.read_point_cloud(filename)

        if parent is not None:
            parent.loaded_file = filename
            parent.last_save_path = filename
            try:
                from .save_pointcloud import load_drawings_from_las

                load_drawings_from_las(filename, parent)
            except Exception as exc:
                print(f"Could not load drawings: {exc}")

        return {
            "xyz": np.asarray(pcd.points),
            "rgb": np.asarray(pcd.colors),
            "intensity": None,
            "classification": None,
            "crs_wkt": None,
            "crs_epsg": None,
            "type": "ply",
        }

    raise ValueError("Unsupported format")
