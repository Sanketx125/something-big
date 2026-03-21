import numpy as np
import torch
import json
import gc
import os
import time
import threading
import importlib.util
import concurrent.futures
from pathlib import Path
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from PySide6.QtCore import QThread, Signal

try:
    import jakteristics
    HAS_JAKTERISTICS = True
except ImportError:
    HAS_JAKTERISTICS = False

try:
    import CSF
    HAS_CSF = True
except ImportError:
    HAS_CSF = False

try:
    import onnxruntime as ort  # type: ignore
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False
    ort = None


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION  — defaults (overridden per-project via advanced_config)
# ═══════════════════════════════════════════════════════════════

class InferenceConfig:
    TILE_SIZE             = 50.0
    TILE_OVERLAP          = 10.0
    NUM_POINTS            = 8192
    VOTE_PASSES           = 3
    INFERENCE_BATCH_SIZE  = 8

    FEATURE_SCALES        = [0.5, 1.0, 2.0, 5.0, 10.0]
    GEOM_VOXEL_SIZE       = 0.30
    EXPECTED_NUM_FEATURES = 66

    # ── CSF ground defaults ──
    CSF_CLOTH_RESOLUTION  = 0.5
    CSF_RIGIDNESS         = 3
    CSF_CLASS_THRESHOLD   = 0.5
    CSF_TIME_STEP         = 0.65
    CSF_ITERATIONS        = 500

    # ── HAG vegetation boundary defaults ──
    LOWVEG_HAG_MIN        = 0.15   # below this → Ground (corrects LowVeg over-prediction)
    LOWVEG_HAG_MAX        = 0.50
    MIDVEG_HAG_MAX        = 3.00
    HIGHVEG_HAG_MIN       = 3.00

    # ── Wire detection defaults ──
    WIRE_VERTICALITY_MAX  = 0.15
    WIRE_INTERNAL_CODE    = 5
    POLE_INTERNAL_CODE    = 6
    WIRE_LINEARITY_MIN    = 0.72
    WIRE_PLANARITY_MAX    = 0.25
    WIRE_HAG_MIN          = 3.0
    WIRE_HAG_MAX          = 80.0
    WIRE_DENSITY_MAX      = 12
    WIRE_CHAIN_RADIUS     = 2.5
    WIRE_CHAIN_MIN        = 2
    WIRE_MIN_SEGMENT_PTS  = 50

    POLE_VERTICALITY_MIN  = 0.65
    POLE_HAG_MIN          = 1.5
    POLE_HAG_MAX          = 80.0
    POLE_2D_RADIUS        = 1.5
    POLE_CLUSTER_MIN_PTS  = 8
    POLE_WIRE_PROXIMITY   = 25.0

    RANDOM_SEED           = 42

    # GPU PCA safe limit — torch.cdist is O(N²), catastrophic above this
    GPU_PCA_MAX_VOXELS    = 30_000


# ── Feature column registry ──
_GEOM_FEATURE_NAMES = [
    'eigenvalue1', 'eigenvalue2', 'eigenvalue3',
    'linearity', 'planarity', 'sphericity',
    'omnivariance', 'anisotropy', 'eigenentropy',
    'surface_variation', 'verticality',
]
_N_GEOM_PER_SCALE = len(_GEOM_FEATURE_NAMES)
_GEOM_OFFSET      = 11


def _feat_col(scale_idx: int, feature_name: str) -> int:
    feat_idx = _GEOM_FEATURE_NAMES.index(feature_name)
    return _GEOM_OFFSET + scale_idx * _N_GEOM_PER_SCALE + feat_idx


def _validate_col_registry():
    n_geom = _N_GEOM_PER_SCALE * len(InferenceConfig.FEATURE_SCALES)
    expected_total = _GEOM_OFFSET + n_geom
    assert expected_total == InferenceConfig.EXPECTED_NUM_FEATURES, (
        f"Column registry mismatch: computed {expected_total}, "
        f"config says {InferenceConfig.EXPECTED_NUM_FEATURES}"
    )
    assert _feat_col(0, 'linearity')   == 14
    assert _feat_col(0, 'planarity')   == 15
    assert _feat_col(0, 'verticality') == 21
    assert _feat_col(1, 'linearity')   == 25
    assert _feat_col(1, 'verticality') == 32


_validate_col_registry()

DEFAULT_POWER_MAPPING = {
    InferenceConfig.WIRE_INTERNAL_CODE: 14,
    InferenceConfig.POLE_INTERNAL_CODE: 15,
}

_POST_PROC_COLUMNS = {
    'linearity_s0':   _feat_col(0, 'linearity'),
    'planarity_s0':   _feat_col(0, 'planarity'),
    'verticality_s0': _feat_col(0, 'verticality'),
    'linearity_s1':   _feat_col(1, 'linearity'),
    'verticality_s1': _feat_col(1, 'verticality'),
}
_POST_COL_INDICES = list(_POST_PROC_COLUMNS.values())
_POST_COL_NAMES   = list(_POST_PROC_COLUMNS.keys())

_GPU_K_PER_RADIUS = {0.5: 30, 1.0: 80, 2.0: 250, 5.0: 600, 10.0: 1500}


# ═══════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════

def voxel_downsample(xyz, voxel_size):
    shifted = xyz - xyz.min(axis=0)
    vc      = np.floor(shifted / voxel_size).astype(np.int64)
    dims    = vc.max(axis=0) + 1
    max_key = dims[0] * dims[1] * dims[2]
    if max_key > 2**62:
        raise ValueError(f"Voxel grid too large: {dims} -> {max_key}.")
    keys = (vc[:, 0] * dims[1] * dims[2] + vc[:, 1] * dims[2] + vc[:, 2])
    unique_keys, inverse, counts = np.unique(keys, return_inverse=True, return_counts=True)
    n_vox     = len(unique_keys)
    centroids = np.zeros((n_vox, 3), dtype=np.float64)
    np.add.at(centroids, inverse, xyz)
    centroids /= counts[:, None]
    return centroids, inverse, n_vox


# ═══════════════════════════════════════════════════════════════
# ONNX CONVERSION UTILITY
# ═══════════════════════════════════════════════════════════════

def convert_pth_to_onnx(pth_path: str, output_path: str = None) -> str:
    pth_path = Path(pth_path)
    if output_path is None:
        output_path = pth_path.with_suffix('.onnx')
    output_path = Path(output_path)

    device   = torch.device('cpu')
    ckpt     = torch.load(str(pth_path), map_location=device, weights_only=False)
    model_py = pth_path.parent / "model.py"
    if not model_py.exists():
        raise FileNotFoundError(f"model.py not found: {model_py}")

    spec = importlib.util.spec_from_file_location("pointnet2_model", str(model_py))
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    num_features = ckpt.get('num_features', InferenceConfig.EXPECTED_NUM_FEATURES)
    num_classes  = ckpt.get('num_classes', 5)
    model = mod.PointNet2SSG(num_features=num_features, num_classes=num_classes)
    model.load_state_dict(ckpt['model_state_dict'], strict=True)
    model.eval()

    B = InferenceConfig.INFERENCE_BATCH_SIZE
    N = InferenceConfig.NUM_POINTS
    F = num_features
    dummy_coords = torch.zeros(B, N, 3, dtype=torch.float32)
    dummy_feats  = torch.zeros(B, N, F, dtype=torch.float32)

    print(f"Exporting ONNX  batch={B}  points={N}  features={F}")
    with torch.no_grad():
        torch.onnx.export(
            model, (dummy_coords, dummy_feats), str(output_path),
            export_params=True, opset_version=17, do_constant_folding=True,
            input_names=['coords', 'features'], output_names=['logits'],
            dynamic_axes={'coords': {0: 'batch'}, 'features': {0: 'batch'},
                          'logits': {0: 'batch'}},
        )
    print(f"ONNX saved → {output_path}  ({output_path.stat().st_size/1e6:.1f} MB)")
    return str(output_path)


# ═══════════════════════════════════════════════════════════════
# INFERENCE WORKER
# ═══════════════════════════════════════════════════════════════

class InferenceWorker(QThread):
    progress = Signal(int, str)
    finished = Signal()
    error    = Signal(str)

    GROUND   = 0
    LOWVEG   = 1
    MIDVEG   = 2
    HIGHVEG  = 3
    BUILDING = 4

    def __init__(self, data_dict, class_mapping, power_mapping,
                 advanced_config=None):
        super().__init__()

        self._xyz = np.array(data_dict["xyz"], dtype=np.float64)

        self._intensity = None
        if data_dict.get("intensity") is not None:
            self._intensity = np.array(data_dict["intensity"], dtype=np.float32)

        self._return_number = self._number_of_returns = None
        if data_dict.get("return_number") is not None:
            self._return_number = np.array(data_dict["return_number"], dtype=np.float32)
        if data_dict.get("number_of_returns") is not None:
            self._number_of_returns = np.array(data_dict["number_of_returns"], dtype=np.float32)

        self._data_dict_ref    = data_dict
        self.class_mapping     = dict(class_mapping)
        self.power_mapping     = dict(power_mapping)
        self._cancel_requested = threading.Event()
        self.model     = None
        self.ort_sess  = None
        self.device    = None
        self.feat_mean = self.feat_std = None
        self._use_onnx = False

        # ── Apply advanced config (override InferenceConfig defaults) ──
        cfg = advanced_config or {}

        # CSF
        self._csf_cloth_resolution = float(cfg.get('csf_cloth_resolution',
                                                     InferenceConfig.CSF_CLOTH_RESOLUTION))
        self._csf_rigidness        = int(cfg.get('csf_rigidness',
                                                  InferenceConfig.CSF_RIGIDNESS))
        self._csf_class_threshold  = float(cfg.get('csf_class_threshold',
                                                    InferenceConfig.CSF_CLASS_THRESHOLD))

        # HAG vegetation correction thresholds
        self._lowveg_min  = float(cfg.get('lowveg_min',  InferenceConfig.LOWVEG_HAG_MIN))
        self._lowveg_max  = float(cfg.get('lowveg_max',  InferenceConfig.LOWVEG_HAG_MAX))
        self._midveg_max  = float(cfg.get('midveg_max',  InferenceConfig.MIDVEG_HAG_MAX))
        self._highveg_min = float(cfg.get('highveg_min', InferenceConfig.HIGHVEG_HAG_MIN))

        # Wire geometry
        self._wire_hag_min        = float(cfg.get('wire_hag_min',
                                                   InferenceConfig.WIRE_HAG_MIN))
        self._wire_hag_max        = float(cfg.get('wire_hag_max',
                                                   InferenceConfig.WIRE_HAG_MAX))
        self._wire_chain_radius   = float(cfg.get('wire_chain_radius',
                                                   InferenceConfig.WIRE_CHAIN_RADIUS))
        self._wire_density_max    = int(cfg.get('wire_density_max',
                                                 InferenceConfig.WIRE_DENSITY_MAX))
        self._wire_min_segment_pts = int(cfg.get('wire_min_segment_pts',
                                                  InferenceConfig.WIRE_MIN_SEGMENT_PTS))
        self._wire_linearity_min  = float(cfg.get('wire_linearity_min',
                                                   InferenceConfig.WIRE_LINEARITY_MIN))

        self._build_mapping_array()
        seed      = InferenceConfig.RANDOM_SEED
        self._rng = np.random.RandomState(seed) if seed is not None else np.random.RandomState()

        self._log_active_config()

    def _log_active_config(self):
        print("\n  ── Active inference config ──")
        print(f"  CSF: cloth_res={self._csf_cloth_resolution}  rigidness={self._csf_rigidness}"
              f"  threshold={self._csf_class_threshold}")
        print(f"  HAG veg: Ground<{self._lowveg_min}m  LowVeg:{self._lowveg_min}-{self._lowveg_max}m"
              f"  MidVeg:{self._lowveg_max}-{self._midveg_max}m  HighVeg>={self._highveg_min}m")
        print(f"  Wire: HAG={self._wire_hag_min}-{self._wire_hag_max}m"
              f"  chain_r={self._wire_chain_radius}m  density_max={self._wire_density_max}"
              f"  min_seg={self._wire_min_segment_pts}pts  lin_min={self._wire_linearity_min}")

    def _build_mapping_array(self):
        all_keys = list(self.class_mapping.keys()) + list(self.power_mapping.keys())
        all_vals = list(self.class_mapping.values()) + list(self.power_mapping.values())
        for k in all_keys:
            if not isinstance(k, int) or k < 0:
                raise ValueError(f"Mapping key must be non-negative int, got {k}")
        for v in all_vals:
            if not isinstance(v, int) or v < 0 or v > 255:
                raise ValueError(f"Mapping value must be 0-255, got {v}")
        max_idx        = max(all_keys)
        self.map_array = np.zeros(max_idx + 1, dtype=np.uint8)
        for k, v in self.class_mapping.items():
            self.map_array[k] = v
        for k, v in self.power_mapping.items():
            self.map_array[k] = v
        print(f"  Class mapping array: {self.map_array}")

    def cancel(self):
        self._cancel_requested.set()

    def _check_cancel(self):
        if self._cancel_requested.is_set():
            self._cleanup_gpu()
            raise InterruptedError("Cancelled by user")

    def _cleanup_gpu(self):
        if self.model is not None:
            del self.model; self.model = None
        if self.ort_sess is not None:
            del self.ort_sess; self.ort_sess = None
        if self.device is not None and self.device.type == 'cuda':
            torch.cuda.empty_cache()
        gc.collect()

    def run(self):
        try:
            self.progress.emit(1, "Loading AI model...")
            self._load_model_internal()
            self._check_cancel()
            self._classify_memory()
            if not self._cancel_requested.is_set():
                self.finished.emit()
        except InterruptedError:
            self.error.emit("Classification cancelled by user")
        except Exception as e:
            import traceback
            self.error.emit(
                f"Classification failed: {str(e)}\n\n{traceback.format_exc()}"
            )
        finally:
            self._cleanup_gpu()

    # ── MODEL LOADING ─────────────────────────────────────────

    def _load_model_internal(self):
        script_dir = Path(__file__).parent.parent
        model_path = script_dir / "models" / "best_building.pth"
        stats_path = script_dir / "models" / "feature_stats.json"

        if not model_path.exists():
            fallback   = Path.cwd() / "models"
            model_path = fallback / "best_building.pth"
            stats_path = fallback / "feature_stats.json"
            if not model_path.exists():
                raise FileNotFoundError(f"Model not found: {model_path}")

        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        onnx_path = model_path.with_suffix('.onnx')
        if HAS_ONNX and onnx_path.exists():
            print(f"  ONNX model found: {onnx_path}")
            providers  = (['CUDAExecutionProvider', 'CPUExecutionProvider']
                          if self.device.type == 'cuda' else ['CPUExecutionProvider'])
            sess_opts  = ort.SessionOptions()
            sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_opts.intra_op_num_threads      = os.cpu_count()
            self.ort_sess      = ort.InferenceSession(
                str(onnx_path), sess_options=sess_opts, providers=providers
            )
            self._use_onnx      = True
            self._onnx_in_names = [i.name for i in self.ort_sess.get_inputs()]
            print(f"  ONNX providers: {self.ort_sess.get_providers()}")
        else:
            if HAS_ONNX and not onnx_path.exists():
                print(f"  No ONNX model — using PyTorch.")
            self._use_onnx = False

        model_py = model_path.parent / "model.py"
        if not model_py.exists():
            raise FileNotFoundError(f"model.py not found: {model_py}")
        spec = importlib.util.spec_from_file_location("pointnet2_model", str(model_py))
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        PointNet2SSG = mod.PointNet2SSG

        ckpt         = torch.load(str(model_path), map_location=self.device,
                                   weights_only=False)
        num_features = ckpt.get('num_features', InferenceConfig.EXPECTED_NUM_FEATURES)
        num_classes  = ckpt.get('num_classes', 5)

        if num_features != InferenceConfig.EXPECTED_NUM_FEATURES:
            raise ValueError(
                f"Model expects {num_features} features, "
                f"pipeline generates {InferenceConfig.EXPECTED_NUM_FEATURES}"
            )

        if not self._use_onnx:
            self.model = PointNet2SSG(
                num_features=num_features, num_classes=num_classes
            ).to(self.device)
            self.model.load_state_dict(ckpt['model_state_dict'], strict=True)
            self.model.eval()

        with open(stats_path) as f:
            stats = json.load(f)
        self.feat_mean = np.array(stats['mean'], dtype=np.float32)
        self.feat_std  = np.array(stats['std'],  dtype=np.float32)

        if len(self.feat_mean) != InferenceConfig.EXPECTED_NUM_FEATURES:
            raise ValueError(
                f"Stats {len(self.feat_mean)} dims != "
                f"{InferenceConfig.EXPECTED_NUM_FEATURES}"
            )

        print(f"  Model: {model_path}")
        print(f"  Device: {self.device}")
        print(f"  Features: {num_features}, Classes: {num_classes}")
        print(f"  Backend: {'ONNX Runtime' if self._use_onnx else 'PyTorch'}")

    # ── MAIN PIPELINE ─────────────────────────────────────────

    def _classify_memory(self):
        t_start = time.time()
        self._check_cancel()

        xyz     = self._xyz
        n_total = len(xyz)
        print(f"  Points: {n_total:,}")

        has_intensity = self._intensity is not None
        has_returns   = (self._return_number is not None
                         and self._number_of_returns is not None)

        if has_returns:
            rn_arr = self._return_number
            nr_arr = self._number_of_returns
            if rn_arr.max() == 1.0 and nr_arr.max() == 1.0 and rn_arr.min() == 1.0:
                print("  WARNING: Synthesized single-return detected — treating as no-return")
                has_returns = False

        if not has_intensity: print("  WARNING: No intensity — zero-filled")
        if not has_returns:   print("  WARNING: No returns — zero-filled")

        cols = [xyz]
        if has_intensity: cols.append(self._intensity.reshape(-1, 1))
        if has_returns:
            cols.append(rn_arr.reshape(-1, 1))
            cols.append(nr_arr.reshape(-1, 1))
        points = np.hstack(cols)

        self._check_cancel()
        self.progress.emit(10, "Computing Height Above Ground (CSF)...")
        t0  = time.time()
        hag = self._compute_hag_csf(xyz)
        print(f"    HAG done: {time.time()-t0:.1f}s  "
              f"range=[{hag.min():.2f}, {hag.max():.2f}]")

        self._check_cancel()
        self.progress.emit(30, "Extracting geometric features...")
        t0       = time.time()
        features = self._build_features(points, hag, has_intensity, has_returns)
        print(f"    Features done: {time.time()-t0:.1f}s  shape={features.shape}")

        assert features.shape == (n_total, InferenceConfig.EXPECTED_NUM_FEATURES)

        # Compact post-processing feature slice (saves RAM)
        post_features = features[:, _POST_COL_INDICES].copy()

        # In-place standardize
        self._check_cancel()
        self.progress.emit(45, "Normalizing features...")
        features -= self.feat_mean
        features /= self.feat_std
        np.clip(features, -10.0, 10.0, out=features)
        np.nan_to_num(features, copy=False, nan=0.0)

        self._check_cancel()
        self.progress.emit(50, "Running AI classification...")
        t0 = time.time()
        predictions, vote_counts = self._run_inference(xyz, features, n_total)
        print(f"    Inference done: {time.time()-t0:.1f}s")

        self._check_cancel()
        total_votes = vote_counts.sum(axis=1, keepdims=True).astype(np.float32)
        total_votes[total_votes == 0] = 1
        confidence  = vote_counts.max(axis=1) / total_votes.squeeze()

        # ── HAG correction pass (before standard post-processing) ──
        self._check_cancel()
        self.progress.emit(86, "Applying HAG vegetation correction...")
        t0 = time.time()
        predictions, hag_fixes = self._hag_correction_pass(predictions, hag)
        print(f"    HAG correction: {hag_fixes:,} fixes ({time.time()-t0:.1f}s)")

        self._check_cancel()
        self.progress.emit(88, "Post-processing...")
        t0 = time.time()
        predictions, fix_report = self._post_process_all(
            xyz, predictions, confidence, hag, post_features
        )
        print(f"    Post-processing: {sum(fix_report.values()):,} fixes "
              f"({time.time()-t0:.1f}s)")
        for k, v in fix_report.items():
            print(f"      {k}: {v:,}")

        self._check_cancel()
        self.progress.emit(92, "Detecting power lines and poles...")
        t0 = time.time()
        predictions, power_report = self._detect_power_lines(
            xyz, predictions, hag, post_features
        )
        print(f"    Power lines: {time.time()-t0:.1f}s")
        for k, v in power_report.items():
            print(f"      {k}: {v:,}")

        self._check_cancel()
        self.progress.emit(97, "Applying class mapping...")
        classified = self.map_array[predictions]

        names = {0:'Ground',1:'LowVeg',2:'MidVeg',3:'HighVeg',4:'Building',
                 5:'Wire',6:'Pole'}
        print(f"\n  Mapping applied:")
        for model_idx in range(7):
            mask = predictions == model_idx
            n    = mask.sum()
            if n > 0:
                print(f"    {names[model_idx]} (idx {model_idx}) "
                      f"-> code {self.map_array[model_idx]}: {n:,} pts")

        self._data_dict_ref["classification"] = classified

        unique, counts = np.unique(classified, return_counts=True)
        print(f"\n  Final classification codes in memory:")
        for cls, cnt in zip(unique, counts):
            print(f"    Code {cls}: {cnt:>12,} ({100*cnt/n_total:.1f}%)")

        has_votes = vote_counts.sum(axis=1) > 0
        print(f"\n  Confidence: mean={confidence[has_votes].mean():.3f}")
        print(f"  Total time: {time.time()-t_start:.1f}s")
        self.progress.emit(100, "Classification complete!")

    # ── HAG ───────────────────────────────────────────────────

    def _compute_hag_csf(self, xyz):
        """
        CSF ground extraction using per-project parameters from advanced_config.
        cloth_resolution / rigidness / class_threshold are user-tunable.
        """
        if not HAS_CSF:
            raise RuntimeError("CSF required.")
        csf = CSF.CSF()
        csf.params.bSloopSmooth     = False
        csf.params.cloth_resolution = self._csf_cloth_resolution
        csf.params.rigidness        = self._csf_rigidness
        csf.params.time_step        = InferenceConfig.CSF_TIME_STEP
        csf.params.class_threshold  = self._csf_class_threshold
        csf.params.interations      = InferenceConfig.CSF_ITERATIONS
        csf.setPointCloud(xyz)
        ground_idx = CSF.VecInt(); non_ground_idx = CSF.VecInt()
        csf.do_filtering(ground_idx, non_ground_idx)
        ground_idx = np.array(ground_idx)

        if len(ground_idx) < 3:
            print("    WARNING: Very few ground points")
            return (xyz[:, 2] - xyz[:, 2].min()).astype(np.float32)

        ground_pts = xyz[ground_idx]
        if len(ground_pts) > 500000:
            sel        = self._rng.choice(len(ground_pts), 500000, replace=False)
            ground_pts = ground_pts[sel]

        tree        = cKDTree(ground_pts[:, :2])
        k           = min(5, len(ground_pts))
        dists, idxs = tree.query(xyz[:, :2], k=k, workers=-1)
        if k == 1:
            dists = dists.reshape(-1, 1); idxs = idxs.reshape(-1, 1)
        w  = 1.0 / (dists + 1e-6); w /= w.sum(axis=1, keepdims=True)
        gz = np.sum(ground_pts[idxs, 2] * w, axis=1)
        return np.clip(xyz[:, 2] - gz, -2.0, None).astype(np.float32)

    # ── HAG CORRECTION PASS ───────────────────────────────────

    def _hag_correction_pass(self, predictions, hag):
        """
        After model voting, apply HAG-based corrections for clear boundary
        violations. Only corrects confident mistakes — conservative by design.

        Corrections applied:
          1. Any veg class (LowVeg/MidVeg/HighVeg) with HAG < lowveg_min
             → forced to Ground.
             Addresses: Ground misclassified as LowVeg (most common error).

          2. Ground class with HAG > lowveg_max (significantly above surface)
             that is NOT near a building → corrected to LowVeg.
             Conservative: only applied when HAG is clearly non-ground
             and no building neighbour context.

        Buildings, Wire, Pole are never touched by this pass.
        """
        fixes = 0
        n     = len(predictions)

        # ── Correction 1: Veg below minimum ground threshold → Ground ──
        veg_mask = np.isin(predictions, [self.LOWVEG, self.MIDVEG, self.HIGHVEG])
        below_ground = veg_mask & (hag < self._lowveg_min)
        n1 = int(below_ground.sum())
        if n1 > 0:
            predictions[below_ground] = self.GROUND
            fixes += n1
            print(f"      HAG corr-1 (veg→ground, HAG<{self._lowveg_min:.2f}m): {n1:,}")

        # ── Correction 2: Ground above lowveg_max → LowVeg ──
        # Only apply if HAG is clearly above threshold and point is not
        # immediately surrounded by buildings (avoid clipping roof points)
        ground_mask   = predictions == self.GROUND
        above_lowveg  = ground_mask & (hag > self._lowveg_max)
        n_candidates  = int(above_lowveg.sum())

        if n_candidates > 0:
            # Build quick building proximity check using 2D KD-tree
            building_mask = predictions == self.BUILDING
            n_corrected   = 0
            cand_idx      = np.where(above_lowveg)[0]

            if building_mask.sum() > 0:
                tree_bldg = cKDTree(self._xyz[building_mask][:, :2])
                dists, _  = tree_bldg.query(
                    self._xyz[cand_idx][:, :2], k=1, workers=-1
                )
                # Only correct if clearly away from buildings (>= 3m)
                safe_to_correct = dists >= 3.0
                to_fix = cand_idx[safe_to_correct]
            else:
                to_fix = cand_idx

            if len(to_fix) > 0:
                predictions[to_fix] = self.LOWVEG
                n_corrected = len(to_fix)
                fixes += n_corrected

            print(f"      HAG corr-2 (ground→lowveg, HAG>{self._lowveg_max:.2f}m): "
                  f"{n_corrected:,} of {n_candidates:,} candidates")

        return predictions, fixes

    # ── FEATURES ──────────────────────────────────────────────

    def _build_features(self, points, hag, has_intensity, has_returns):
        n = len(points); xyz = points[:, :3]
        features = np.zeros(
            (n, InferenceConfig.EXPECTED_NUM_FEATURES), dtype=np.float32
        )
        features[:, 0:3] = xyz.astype(np.float32)
        features[:, 3]   = hag
        if has_intensity:
            intensity = points[:, 3].astype(np.float32)
            mx = intensity.max()
            if mx > 0: intensity /= mx
            features[:, 4] = intensity
        if has_returns:
            col_rn = 4 if has_intensity else 3; col_nr = col_rn + 1
            rn = points[:, col_rn].astype(np.float32)
            nr = points[:, col_nr].astype(np.float32)
            features[:, 5]  = rn; features[:, 6]  = nr
            features[:, 7]  = np.where(nr > 0, rn / nr, 0)
            features[:, 8]  = (nr == 1).astype(np.float32)
            features[:, 9]  = (rn == 1).astype(np.float32)
            features[:, 10] = (rn == nr).astype(np.float32)

        print("    Computing geometric features...")
        geom = self._compute_geometric_features(xyz.astype(np.float64))
        expected_geom = _N_GEOM_PER_SCALE * len(InferenceConfig.FEATURE_SCALES)
        if geom.shape[1] != expected_geom:
            raise ValueError(
                f"Geom features: expected {expected_geom}, got {geom.shape[1]}"
            )
        features[:, 11:11 + geom.shape[1]] = geom
        total_used = 11 + geom.shape[1]
        if total_used != InferenceConfig.EXPECTED_NUM_FEATURES:
            raise ValueError(
                f"Feature count mismatch: expected "
                f"{InferenceConfig.EXPECTED_NUM_FEATURES}, built {total_used}"
            )
        np.nan_to_num(features, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        return features

    # ── GEOMETRIC FEATURE ROUTER ─────────────────────────────

    def _compute_geometric_features(self, xyz: np.ndarray) -> np.ndarray:
        ds_pts, vox_map, n_vox = voxel_downsample(
            xyz, InferenceConfig.GEOM_VOXEL_SIZE
        )
        print(f"    Voxel: {len(xyz):,} -> {n_vox:,}")

        use_gpu_pca = (
            self.device.type == 'cuda'
            and n_vox <= InferenceConfig.GPU_PCA_MAX_VOXELS
        )

        if use_gpu_pca:
            print(f"    Feature path: GPU PCA (N_vox={n_vox:,})")
            ds_all = self._geom_features_gpu(ds_pts, n_vox)
        elif HAS_JAKTERISTICS:
            print(f"    Feature path: Parallel jakteristics (N_vox={n_vox:,})")
            ds_all = self._geom_features_cpu_parallel(ds_pts)
        else:
            raise RuntimeError(
                "Neither GPU PCA (cloud too large) nor jakteristics available."
            )

        return ds_all[vox_map]

    # ── GPU PCA ───────────────────────────────────────────────

    def _geom_features_gpu(self, ds_pts: np.ndarray, n_vox: int) -> np.ndarray:
        pts_gpu = torch.from_numpy(ds_pts.astype(np.float32)).to(self.device)
        N = n_vox
        try:
            free_vram, _ = torch.cuda.mem_get_info(self.device)
            safe_bytes   = min(free_vram * 0.40, 512e6)
        except Exception:
            safe_bytes = 256e6
        chunk = max(64, min(2048, int(safe_bytes / max(N * 4, 1))))
        print(f"    GPU PCA chunk={chunk}")

        feat_blocks = []
        for radius in InferenceConfig.FEATURE_SCALES:
            self._check_cancel()
            t0 = time.time()
            k  = min(_GPU_K_PER_RADIUS.get(radius, 300), N - 1)
            try:
                feats = self._gpu_pca_block(pts_gpu, radius, k, chunk, N)
            except RuntimeError as e:
                if 'memory' in str(e).lower() and HAS_JAKTERISTICS:
                    print(f"      Scale {radius}m: GPU OOM → jakteristics fallback")
                    torch.cuda.empty_cache()
                    feats = jakteristics.compute_features(
                        ds_pts.astype(np.float64),
                        search_radius=radius,
                        feature_names=_GEOM_FEATURE_NAMES,
                        num_threads=-1,
                    )
                    feats = np.nan_to_num(feats, nan=0.0).astype(np.float32)
                else:
                    raise
            print(f"      Scale {radius}m: {time.time()-t0:.2f}s")
            feat_blocks.append(feats)
        return np.hstack(feat_blocks)

    def _gpu_pca_block(self, pts, radius, k, chunk, N):
        k1  = min(k + 1, N)
        out = torch.zeros((N, 11), dtype=torch.float32, device=self.device)
        with torch.inference_mode():
            for start in range(0, N, chunk):
                end = min(start + chunk, N); B_cur = end - start
                query = pts[start:end]
                dist  = torch.cdist(query, pts)
                kd, ki = dist.topk(k1, dim=1, largest=False)
                valid  = (kd <= radius) & (kd > 1e-8)
                n_valid = valid.float().sum(dim=1)
                has_min = n_valid >= 3
                if not has_min.any(): continue
                nb = pts[ki]; v_f = valid.unsqueeze(-1).float()
                nv_safe  = n_valid.clamp(min=1).view(B_cur, 1)
                centroid = (nb * v_f).sum(1) / nv_safe
                centered = (nb - centroid.unsqueeze(1)) * v_f
                cov = (
                    torch.bmm(centered.transpose(1, 2), centered)
                    / n_valid.clamp(min=1).view(B_cur, 1, 1)
                )
                try:
                    ev, evec = torch.linalg.eigh(cov)
                except RuntimeError:
                    continue
                ev = ev.flip(-1).clamp(min=1e-10); evec = evec.flip(-1)
                l1, l2, l3 = ev[:,0], ev[:,1], ev[:,2]
                l1c = l1.clamp(min=1e-10); lsum = (l1+l2+l3).clamp(min=1e-10)
                f = out[start:end]
                f[:,0]=l1; f[:,1]=l2; f[:,2]=l3
                f[:,3]=(l1-l2)/l1c; f[:,4]=(l2-l3)/l1c; f[:,5]=l3/l1c
                f[:,6]=(l1*l2*l3).clamp(min=1e-30).pow(1/3)
                f[:,7]=(l1-l3)/l1c
                l_norm=(ev/lsum.unsqueeze(1)).clamp(min=1e-10)
                f[:,8]=-(l_norm*l_norm.log()).sum(1)
                f[:,9]=l3/lsum
                f[:,10]=1.0-evec[:,2,2].abs()
                f[~has_min]=0.0
        return out.cpu().numpy()

    # ── PARALLEL JAKTERISTICS ─────────────────────────────────

    def _geom_features_cpu_parallel(self, ds_pts: np.ndarray) -> np.ndarray:
        scales      = InferenceConfig.FEATURE_SCALES
        n_scales    = len(scales)
        n_cpu       = os.cpu_count() or 4
        t_per_scale = max(1, n_cpu // n_scales)
        pts_f64     = ds_pts.astype(np.float64)

        print(f"    Parallel jakteristics: {n_scales} scales × {t_per_scale} threads")

        def _one_scale(radius: float) -> tuple:
            t0 = time.time()
            f  = jakteristics.compute_features(
                pts_f64,
                search_radius=radius,
                feature_names=_GEOM_FEATURE_NAMES,
                num_threads=t_per_scale,
            )
            f = np.nan_to_num(f, nan=0.0).astype(np.float32)
            print(f"      Scale {radius}m: {time.time()-t0:.1f}s")
            return (radius, f)

        ordered = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_scales) as ex:
            futures = {ex.submit(_one_scale, r): r for r in scales}
            for fut in concurrent.futures.as_completed(futures):
                radius, feats = fut.result()
                ordered[radius] = feats

        return np.hstack([ordered[r] for r in scales])

    # ── INFERENCE ─────────────────────────────────────────────

    def _run_inference(self, xyz, features, n_total):
        vote_counts = np.zeros((n_total, 5), dtype=np.int32)
        stride       = InferenceConfig.TILE_SIZE - InferenceConfig.TILE_OVERLAP
        x_min, y_min = xyz[:,0].min(), xyz[:,1].min()
        x_max, y_max = xyz[:,0].max(), xyz[:,1].max()

        tile_specs = []
        xs = x_min
        while xs <= x_max:
            ys = y_min
            while ys <= y_max:
                tile_specs.append((xs, ys)); ys += stride
            xs += stride

        print(f"    Tiles: {len(tile_specs)}")
        total_batches = 0
        total_work    = max(1, len(tile_specs) * InferenceConfig.VOTE_PASSES)

        for vote in range(InferenceConfig.VOTE_PASSES):
            self._check_cancel()
            gpu_batch = []; batch_meta = []

            for tile_idx, (tx, ty) in enumerate(tile_specs):
                if tile_idx % 50 == 0: self._check_cancel()
                mask = (
                    (xyz[:,0] >= tx) & (xyz[:,0] < tx + InferenceConfig.TILE_SIZE) &
                    (xyz[:,1] >= ty) & (xyz[:,1] < ty + InferenceConfig.TILE_SIZE)
                )
                n_tile = mask.sum()
                if n_tile < 100: continue
                tile_indices = np.where(mask)[0]
                if n_tile >= InferenceConfig.NUM_POINTS:
                    sel = self._rng.choice(n_tile, InferenceConfig.NUM_POINTS,
                                           replace=False)
                else:
                    sel = self._rng.choice(n_tile, InferenceConfig.NUM_POINTS,
                                           replace=True)
                batch_coords  = xyz[tile_indices[sel]].copy().astype(np.float32)
                batch_feat    = features[tile_indices[sel]].copy()
                batch_coords -= batch_coords.mean(axis=0)
                gpu_batch.append((batch_coords, batch_feat))
                batch_meta.append((tile_indices, sel))

                if len(gpu_batch) >= InferenceConfig.INFERENCE_BATCH_SIZE:
                    self._check_cancel()
                    preds_list = self._run_batched_inference(gpu_batch)
                    for pred, (t_idx, s) in zip(preds_list, batch_meta):
                        actual = t_idx[s]; valid = pred < 5
                        np.add.at(vote_counts, (actual[valid], pred[valid]), 1)
                    total_batches += len(gpu_batch)
                    gpu_batch = []; batch_meta = []
                    pct = int(50 + 36 * total_batches / total_work)
                    self.progress.emit(
                        min(pct, 85),
                        f"Vote {vote+1}/{InferenceConfig.VOTE_PASSES}"
                    )
                    if total_batches % 50 == 0 and self.device.type == 'cuda':
                        torch.cuda.empty_cache()

            if gpu_batch:
                preds_list = self._run_batched_inference(gpu_batch)
                for pred, (t_idx, s) in zip(preds_list, batch_meta):
                    actual = t_idx[s]; valid = pred < 5
                    np.add.at(vote_counts, (actual[valid], pred[valid]), 1)

        has_votes   = vote_counts.sum(axis=1) > 0
        n_no_votes  = (~has_votes).sum()
        predictions = np.zeros(n_total, dtype=np.uint8)
        predictions[has_votes] = vote_counts[has_votes].argmax(axis=1)

        if n_no_votes > 0:
            print(f"    {n_no_votes:,} without votes — NN fill")
            tree    = cKDTree(xyz[has_votes])
            _, nn_i = tree.query(xyz[~has_votes], k=1)
            predictions[~has_votes] = predictions[has_votes][nn_i]

        return predictions, vote_counts

    def _run_batched_inference(self, tile_batch):
        B = len(tile_batch)
        if B == 0: return []
        coords_batch = np.stack([t[0] for t in tile_batch])
        feats_batch  = np.stack([t[1] for t in tile_batch])

        if self._use_onnx and self.ort_sess is not None:
            ort_inputs = {
                self._onnx_in_names[0]: coords_batch.astype(np.float32),
                self._onnx_in_names[1]: feats_batch.astype(np.float32),
            }
            logits_np = self.ort_sess.run(None, ort_inputs)[0]
            preds     = logits_np.argmax(axis=-1)
            return [preds[i] for i in range(B)]

        c_t = torch.from_numpy(coords_batch).float().to(self.device)
        f_t = torch.from_numpy(feats_batch).float().to(self.device)
        with torch.inference_mode():
            if self.device.type == 'cuda':
                with torch.amp.autocast('cuda'):
                    logits = self.model(c_t, f_t)
            else:
                logits = self.model(c_t, f_t)
        preds = logits.argmax(dim=-1).cpu().numpy()
        return [preds[i] for i in range(B)]

    # ── POST-PROCESSING ───────────────────────────────────────

    _PF_LIN_S0  = 0
    _PF_PLAN_S0 = 1
    _PF_VERT_S0 = 2
    _PF_LIN_S1  = 3
    _PF_VERT_S1 = 4

    def _post_process_all(self, xyz, predictions, confidence, hag, post_features):
        fix_report = {}

        self.progress.emit(89, "Post-processing: ground-on-roof...")
        t0 = time.time()
        predictions, n = self._fix_ground_on_roofs(xyz, predictions, hag)
        fix_report['ground_on_roof'] = n
        print(f"      ground_on_roof: {n:,} ({time.time()-t0:.1f}s)")

        self._check_cancel()
        self.progress.emit(90, "Post-processing: wall recovery...")
        t0 = time.time()
        predictions, n = self._fix_building_walls(
            xyz, predictions, hag, post_features
        )
        fix_report['wall_recovery'] = n
        print(f"      wall_recovery: {n:,} ({time.time()-t0:.1f}s)")

        self._check_cancel()
        self.progress.emit(91, "Post-processing: boundary cleanup...")
        t0 = time.time()
        predictions, n = self._fix_salt_pepper(xyz, predictions, confidence)
        fix_report['salt_pepper'] = n
        print(f"      salt_pepper: {n:,} ({time.time()-t0:.1f}s)")

        return predictions, fix_report

    def _fix_ground_on_roofs(self, xyz, predictions, hag):
        ground_mask   = predictions == self.GROUND
        building_mask = predictions == self.BUILDING
        if ground_mask.sum() == 0 or building_mask.sum() == 0:
            return predictions, 0
        ground_indices = np.where(ground_mask)[0]
        tree_bldg_2d   = cKDTree(xyz[building_mask][:, :2])
        dists, _       = tree_bldg_2d.query(
            xyz[ground_indices][:, :2], k=1, workers=-1
        )
        candidates = ground_indices[dists < 3.0]
        if len(candidates) == 0: return predictions, 0
        tree_all       = cKDTree(xyz)
        neighbor_lists = tree_all.query_ball_point(
            xyz[candidates], r=2.0, workers=-1
        )
        all_ground_xyz = xyz[ground_mask]
        if len(all_ground_xyz) == 0: return predictions, 0
        tree_ground_2d = cKDTree(all_ground_xyz[:, :2])
        fixes = 0
        for pt_idx, neighbors in zip(candidates, neighbor_lists):
            if len(neighbors) < 5: continue
            if (predictions[neighbors] == self.BUILDING).sum() / len(neighbors) < 0.50:
                continue
            d_g, i_g = tree_ground_2d.query(xyz[pt_idx, :2], k=10)
            near_gz  = all_ground_xyz[i_g[d_g < 20.0], 2]
            if (len(near_gz) > 0
                    and xyz[pt_idx, 2] - np.median(near_gz) > 2.5):
                predictions[pt_idx] = self.BUILDING; fixes += 1
        return predictions, fixes

    def _fix_building_walls(self, xyz, predictions, hag, post_features):
        building_mask = predictions == self.BUILDING
        veg_mask      = (predictions == self.HIGHVEG) | (predictions == self.MIDVEG)
        if building_mask.sum() == 0 or veg_mask.sum() == 0:
            return predictions, 0
        building_xyz = xyz[building_mask]; building_hag = hag[building_mask]
        tree_bldg_2d = cKDTree(building_xyz[:, :2])
        veg_idx = np.where(veg_mask)[0]; veg_hag = hag[veg_idx]
        vert_05 = post_features[veg_idx, self._PF_VERT_S0]
        d_b, nn_b   = tree_bldg_2d.query(
            xyz[veg_idx][:, :2], k=1, workers=-1
        )
        nn_bldg_hag = building_hag[nn_b]
        wall = (
            (d_b < 3.0) & (vert_05 > 0.4) & (veg_hag > 1.0) &
            (veg_hag < nn_bldg_hag + 2.0) & (veg_hag > 0.15 * nn_bldg_hag)
        )
        predictions[veg_idx[wall]] = self.BUILDING; fixes = wall.sum()
        rem = np.where(
            (predictions == self.HIGHVEG) | (predictions == self.MIDVEG)
        )[0]
        if len(rem) > 0:
            d_r, nn_r = tree_bldg_2d.query(xyz[rem][:, :2], k=1, workers=-1)
            buf = (
                (d_r < 0.5) & (hag[rem] > 1.0) &
                (hag[rem] < building_hag[nn_r] + 1.0)
            )
            predictions[rem[buf]] = self.BUILDING; fixes += buf.sum()
        return predictions, fixes

    def _fix_salt_pepper(self, xyz, predictions, confidence):
        fixes = 0; tree_all = cKDTree(xyz)
        b_mask = predictions == self.BUILDING
        if b_mask.sum() > 100:
            nb_idx = np.where(~b_mask)[0]
            tree_b = cKDTree(xyz[b_mask])
            d, _   = tree_b.query(xyz[nb_idx], k=1, workers=-1)
            cand   = nb_idx[d < 2.0]
            if len(cand) > 0:
                nls = tree_all.query_ball_point(xyz[cand], r=1.5, workers=-1)
                for pi, nbrs in zip(cand, nls):
                    if (len(nbrs) >= 5 and
                            (predictions[nbrs] == self.BUILDING).sum() / len(nbrs) > 0.70):
                        predictions[pi] = self.BUILDING; fixes += 1

        b_mask = predictions == self.BUILDING; b_idx = np.where(b_mask)[0]
        if len(b_idx) > 100:
            check = (
                self._rng.choice(b_idx, min(200_000, len(b_idx)), replace=False)
                if len(b_idx) > 200_000 else b_idx
            )
            nls      = tree_all.query_ball_point(xyz[check], r=2.0, workers=-1)
            isolated = []
            for pi, nbrs in zip(check, nls):
                if len(nbrs) < 5: isolated.append(pi)
                elif (predictions[nbrs] == self.BUILDING).sum() / len(nbrs) < 0.15:
                    isolated.append(pi)
            for idx in isolated:
                _, nn = tree_all.query(xyz[idx], k=20)
                nb    = predictions[nn[1:]][predictions[nn[1:]] != self.BUILDING]
                if len(nb) > 0:
                    v, c = np.unique(nb, return_counts=True)
                    predictions[idx] = v[c.argmax()]; fixes += 1

        lc = np.where(
            (confidence < 0.6) &
            np.isin(predictions, [self.MIDVEG, self.HIGHVEG, self.BUILDING])
        )[0]
        if 0 < len(lc) < 500_000:
            for idx in lc:
                _, nn = tree_all.query(xyz[idx], k=15)
                nc = confidence[nn[1:]]; np_ = predictions[nn[1:]]
                hc = nc > 0.8
                if hc.sum() >= 5:
                    hp = np_[hc]; v, c = np.unique(hp, return_counts=True)
                    new = v[c.argmax()]
                    if new != predictions[idx]:
                        predictions[idx] = new; fixes += 1
        return predictions, fixes

    # ── POWER LINE DETECTION ─────────────────────────────────

    def _detect_power_lines(self, xyz, predictions, hag, post_features):
        """
        Wire and pole detection using per-project geometry params.
        chain_radius / density_max / min_segment_pts / linearity_min
        are all user-tunable via Advanced config.
        """
        report = {
            'wire_candidates': 0, 'wires_final': 0,
            'pole_candidates': 0, 'poles_final': 0,
        }
        cfg = InferenceConfig
        HAG_CONSISTENCY_MAX = 1.0

        # ── Resolved per-project wire params ──
        wire_hag_min        = self._wire_hag_min
        wire_hag_max        = self._wire_hag_max
        wire_chain_radius   = self._wire_chain_radius
        wire_density_max    = self._wire_density_max
        wire_min_seg        = self._wire_min_segment_pts
        wire_linearity_min  = self._wire_linearity_min
        wire_planarity_max  = cfg.WIRE_PLANARITY_MAX

        print(f"    Wire params: HAG={wire_hag_min}-{wire_hag_max}m  "
              f"chain_r={wire_chain_radius}m  density_max={wire_density_max}  "
              f"min_seg={wire_min_seg}  lin_min={wire_linearity_min}")

        # STEP 1: WIRE DETECTION
        veg_pool_mask = (
            ((predictions == self.MIDVEG) | (predictions == self.HIGHVEG)) &
            (hag >= wire_hag_min) &
            (hag <= wire_hag_max)
        )
        veg_pool_idx = np.where(veg_pool_mask)[0]
        wire_idx     = np.array([], dtype=np.int64)

        if len(veg_pool_idx) >= 10:
            lin_s0  = post_features[veg_pool_idx, self._PF_LIN_S0]
            plan_s0 = post_features[veg_pool_idx, self._PF_PLAN_S0]
            lin_s1  = post_features[veg_pool_idx, self._PF_LIN_S1]
            geom_pass = (
                (lin_s0  >= wire_linearity_min) &
                (plan_s0 <= wire_planarity_max) &
                (lin_s1  >= wire_linearity_min - 0.05)
            )
            geom_idx = veg_pool_idx[geom_pass]
            report['wire_candidates'] = len(geom_idx)
            print(f"    Wire candidates after geom filter: {len(geom_idx):,}")

            if len(geom_idx) >= 3:
                tree_cand  = cKDTree(xyz[geom_idx])
                raw_counts = np.array(
                    tree_cand.query_ball_point(
                        xyz[geom_idx], r=0.5,
                        workers=-1, return_length=True
                    )
                ) - 1
                sparse_idx = geom_idx[raw_counts <= wire_density_max]
                print(f"    Wire after density filter: {len(sparse_idx):,}")

                if len(sparse_idx) >= 3:
                    tree_sparse  = cKDTree(xyz[sparse_idx])
                    chain_counts = np.array(
                        tree_sparse.query_ball_point(
                            xyz[sparse_idx], r=wire_chain_radius,
                            workers=-1, return_length=True
                        )
                    ) - 1
                    chain_pass_idx = sparse_idx[chain_counts >= cfg.WIRE_CHAIN_MIN]
                    print(f"    Wire after chain filter: {len(chain_pass_idx):,}")

                    if len(chain_pass_idx) >= 3:
                        k_hag      = min(10, len(chain_pass_idx))
                        tree_chain = cKDTree(xyz[chain_pass_idx])
                        _, nn_idx  = tree_chain.query(
                            xyz[chain_pass_idx], k=k_hag, workers=-1
                        )
                        chain_hag = hag[chain_pass_idx]
                        nb_hag    = chain_hag[nn_idx]
                        hag_ok    = (
                            nb_hag.max(axis=1) - nb_hag.min(axis=1)
                        ) < HAG_CONSISTENCY_MAX
                        hag_consistent_idx = chain_pass_idx[hag_ok]
                        print(f"    Wire after HAG consistency: "
                              f"{len(hag_consistent_idx):,} "
                              f"({(~hag_ok).sum():,} removed)")

                        if len(hag_consistent_idx) >= wire_min_seg:
                            seg_tree  = cKDTree(xyz[hag_consistent_idx])
                            seg_pairs = seg_tree.query_pairs(
                                r=wire_chain_radius, output_type='ndarray'
                            )
                            n_ch = len(hag_consistent_idx)
                            if len(seg_pairs) > 0:
                                row  = np.concatenate(
                                    [seg_pairs[:,0], seg_pairs[:,1]]
                                )
                                col  = np.concatenate(
                                    [seg_pairs[:,1], seg_pairs[:,0]]
                                )
                                graph = csr_matrix(
                                    (np.ones(len(row), dtype=np.bool_),
                                     (row, col)),
                                    shape=(n_ch, n_ch)
                                )
                                _, seg_labels = connected_components(
                                    graph, directed=False
                                )
                            else:
                                seg_labels = np.arange(n_ch)

                            unique_seg, seg_counts = np.unique(
                                seg_labels, return_counts=True
                            )
                            valid_segs = unique_seg[seg_counts >= wire_min_seg]
                            print(
                                f"    Wire segments: {len(unique_seg):,} total, "
                                f"{(seg_counts < wire_min_seg).sum():,} dropped, "
                                f"{len(valid_segs):,} kept"
                            )
                            wire_idx = hag_consistent_idx[
                                np.isin(seg_labels, valid_segs)
                            ]
                        else:
                            wire_idx = np.array([], dtype=np.int64)

            report['wires_final'] = len(wire_idx)
            print(f"    Wire FINAL: {len(wire_idx):,} pts")
            if len(wire_idx) > 0:
                predictions[wire_idx] = cfg.WIRE_INTERNAL_CODE
        else:
            print(f"    Wire: no veg candidates in HAG {wire_hag_min}-{wire_hag_max}m — skipping")

        # STEP 2: POLE DETECTION
        pole_pool_mask = (
            ((predictions == self.BUILDING) |
             (predictions == self.HIGHVEG)  |
             (predictions == self.MIDVEG))  &
            (hag >= cfg.POLE_HAG_MIN) &
            (hag <= cfg.POLE_HAG_MAX)
        )
        pole_pool_idx = np.where(pole_pool_mask)[0]
        print(f"    Pole pool size: {len(pole_pool_idx):,}")

        if len(pole_pool_idx) < cfg.POLE_CLUSTER_MIN_PTS:
            print(f"    Pole: pool too small — skipping")
            return predictions, report

        vert_s0 = post_features[pole_pool_idx, self._PF_VERT_S0]
        vert_s1 = post_features[pole_pool_idx, self._PF_VERT_S1]
        vert_pass     = (
            (vert_s0 >= cfg.POLE_VERTICALITY_MIN) &
            (vert_s1 >= cfg.POLE_VERTICALITY_MIN - 0.05)
        )
        pole_cand_idx = pole_pool_idx[vert_pass]
        report['pole_candidates'] = len(pole_cand_idx)
        print(f"    Pole candidates after vert filter: {len(pole_cand_idx):,}")

        if len(pole_cand_idx) < cfg.POLE_CLUSTER_MIN_PTS:
            print(f"    Pole: too few after vert filter — skipping")
            return predictions, report

        wire_confirmed = len(wire_idx) > 0
        wire_score     = np.zeros(len(pole_cand_idx), dtype=np.float32)
        if wire_confirmed:
            tree_wire = cKDTree(xyz[wire_idx, :2])
            dists_to_wire, _ = tree_wire.query(
                xyz[pole_cand_idx, :2], k=1, workers=-1
            )
            wire_score = np.clip(
                1.0 - dists_to_wire / cfg.POLE_WIRE_PROXIMITY, 0.0, 1.0
            )
            print(f"    Pole near wires: "
                  f"{(dists_to_wire <= cfg.POLE_WIRE_PROXIMITY).sum():,}")

        pole_xyz_2d = xyz[pole_cand_idx, :2]
        t0    = time.time()
        pairs = cKDTree(pole_xyz_2d).query_pairs(r=3.0, output_type='ndarray')
        n_cand = len(pole_cand_idx)
        if len(pairs) > 0:
            row = np.concatenate([pairs[:,0], pairs[:,1]])
            col = np.concatenate([pairs[:,1], pairs[:,0]])
            graph = csr_matrix(
                (np.ones(len(row), dtype=np.bool_), (row, col)),
                shape=(n_cand, n_cand)
            )
            n_components, labels = connected_components(graph, directed=False)
        else:
            labels = np.arange(n_cand); n_components = n_cand
        print(f"    Pole clusters: {n_components:,} ({time.time()-t0:.1f}s)")

        unique_labels, label_counts = np.unique(labels, return_counts=True)
        pole_final_idx = []
        for label, count in zip(unique_labels, label_counts):
            if count < cfg.POLE_CLUSTER_MIN_PTS: continue
            cluster_local  = np.where(labels == label)[0]
            cluster_global = pole_cand_idx[cluster_local]
            cluster_hag    = hag[cluster_global]
            hag_span       = cluster_hag.max() - cluster_hag.min()
            if hag_span < 1.5: continue
            cluster_xy = xyz[cluster_global, :2]
            if max(cluster_xy[:,0].max() - cluster_xy[:,0].min(),
                   cluster_xy[:,1].max() - cluster_xy[:,1].min()) > 5.0:
                continue
            cluster_wire_score = wire_score[cluster_local].mean()
            if wire_confirmed and cluster_wire_score < 0.05:
                if hag_span < 4.0: continue
                if (post_features[cluster_global, self._PF_VERT_S0].mean()
                        < cfg.POLE_VERTICALITY_MIN + 0.10):
                    continue
            pole_final_idx.extend(cluster_global.tolist())

        pole_final_idx        = np.array(pole_final_idx, dtype=np.int64)
        report['poles_final'] = len(pole_final_idx)
        print(f"    Pole FINAL: {len(pole_final_idx):,} pts")
        if len(pole_final_idx) > 0:
            predictions[pole_final_idx] = cfg.POLE_INTERNAL_CODE

        return predictions, report