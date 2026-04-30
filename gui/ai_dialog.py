from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QProgressBar, QPushButton, QMessageBox,
    QSpinBox, QDoubleSpinBox, QCheckBox,
    QGroupBox, QFrame, QTabWidget, QWidget,
    QFormLayout, QFileDialog, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from pathlib import Path
import numpy as np

from gui.ai_inference import (
    InferenceConfig,
    DEFAULT_POWER_MAPPING,
)

# ═══════════════════════════════════════════════════════════════
# TerraScan MAC PARSER
# ═══════════════════════════════════════════════════════════════

def _split_mac_args(args_str: str) -> list:
    parts = []; current = ''; in_quote = False
    for ch in args_str:
        if ch == '"':
            in_quote = not in_quote
        elif ch == ',' and not in_quote:
            parts.append(current.strip()); current = ''
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def parse_mac_file(path: str) -> dict:
    """
    Parse TerraScan .mac → extract pipeline-relevant params.
    Returns dict with keys matching advanced_config.
    Only successfully parsed keys are included.
    """
    result = {}
    path   = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"MAC file not found: {path}")
    with open(path, encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    if '[TerraScan macro]' not in ''.join(lines):
        raise ValueError("Not a valid TerraScan .mac file.")

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('[') or '(' not in line:
            continue
        fn_name  = line[:line.index('(')]
        args_str = line[line.index('(') + 1: line.rindex(')')]
        args     = [a.strip().strip('"') for a in args_str.split(',')]

        # FnScanClassifyGround → CSF cloth_resolution + rigidness
        if fn_name == 'FnScanClassifyGround' and len(args) >= 10:
            try:
                max_angle = float(args[4])
                iter_dist = float(args[9])
                result['csf_cloth_resolution'] = round(max(0.1, min(5.0, iter_dist)), 2)
                result['csf_rigidness'] = (1 if max_angle > 60
                                           else 2 if max_angle > 30 else 3)
            except (ValueError, IndexError):
                pass

        # FnScanClassifyHgtGrd → HAG vegetation boundaries
        elif fn_name == 'FnScanClassifyHgtGrd' and len(args) >= 6:
            try:
                from_cls = int(args[2]); to_cls = int(args[3])
                min_hgt  = float(args[4]); max_hgt = float(args[5])
                if from_cls not in (0, 1):
                    continue
                if to_cls == 2:
                    if min_hgt >= 0:   result['lowveg_min'] = round(max(0.0, min_hgt), 3)
                    if max_hgt < 500:  result['lowveg_max'] = round(max_hgt, 3)
                elif to_cls == 3:
                    if max_hgt < 500:  result['midveg_max'] = round(max_hgt, 3)
                elif to_cls == 4:
                    if min_hgt >= 0:   result['highveg_min'] = round(min_hgt, 3)
            except (ValueError, IndexError):
                pass

        # FnScanFindWires → wire geometry
        elif fn_name == 'FnScanFindWires':
            try:
                raw_args = _split_mac_args(args_str)
                if len(raw_args) >= 10:
                    result['wire_chain_radius'] = round(max(0.5, float(raw_args[5])), 2)
                    result['wire_hag_max']       = round(max(5.0, float(raw_args[9])), 1)
                    if len(raw_args) >= 12:
                        result['wire_hag_min']   = round(max(0.0, float(raw_args[11])), 1)
            except (ValueError, IndexError):
                pass

    return result


# ═══════════════════════════════════════════════════════════════
# DEFAULT VALUES (mirrors InferenceConfig — single source of truth)
# ═══════════════════════════════════════════════════════════════

_DEFAULTS = {
    'csf_cloth_resolution':  InferenceConfig.CSF_CLOTH_RESOLUTION,
    'csf_rigidness':         InferenceConfig.CSF_RIGIDNESS,
    'csf_class_threshold':   InferenceConfig.CSF_CLASS_THRESHOLD,
    'lowveg_min':            InferenceConfig.LOWVEG_HAG_MIN,
    'lowveg_max':            InferenceConfig.LOWVEG_HAG_MAX,
    'midveg_max':            InferenceConfig.MIDVEG_HAG_MAX,
    'highveg_min':           InferenceConfig.HIGHVEG_HAG_MIN,
    'wire_hag_min':          InferenceConfig.WIRE_HAG_MIN,
    'wire_hag_max':          InferenceConfig.WIRE_HAG_MAX,
    'wire_chain_radius':     InferenceConfig.WIRE_CHAIN_RADIUS,
    'wire_density_max':      InferenceConfig.WIRE_DENSITY_MAX,
    'wire_min_segment_pts':  InferenceConfig.WIRE_MIN_SEGMENT_PTS,
    'wire_linearity_min':    InferenceConfig.WIRE_LINEARITY_MIN,
}


# ═══════════════════════════════════════════════════════════════
# CLASS MAPPING DIALOG
# ═══════════════════════════════════════════════════════════════

class ClassMappingDialog(QDialog):

    _CLASSES = [
        (0,      "Ground",            1),
        (1,      "Low Vegetation",    2),
        (2,      "Medium Vegetation", 3),
        (3,      "High Vegetation",   4),
        (4,      "Building",          5),
        ('wire', "Power Line Wire",  14),
        ('pole', "Power Line Pole",  15),
    ]

    def __init__(self, parent=None, existing_classes=None):
        super().__init__(parent)
        self.existing_classes           = existing_classes or set()
        self.accepted_class_mapping     = None
        self.accepted_power_mapping     = None
        self.accepted_advanced          = None
        self.accepted_enable_power_lines = False
        self._code_spins                = {}
        self._code_labels               = {}    # name labels for power rows
        self._adv                       = {}
        self._enable_power_cb           = None
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setWindowTitle("AI Classification")
        self.setMinimumWidth(680)
        self.setMinimumHeight(520)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(12, 12, 12, 12)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_mapping_tab(), "Class Mapping")
        self.tabs.addTab(self._build_advanced_tab(), "Advanced")
        root.addWidget(self.tabs)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(80)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()

        start_btn = QPushButton("Start Classification")
        start_btn.setDefault(True)
        start_btn.setMinimumWidth(190)
        f = QFont(); f.setBold(True)
        start_btn.setFont(f)
        start_btn.clicked.connect(self._validate_and_accept)
        btn_row.addWidget(start_btn)
        root.addLayout(btn_row)

    # ── TAB 1: CLASS MAPPING ──────────────────────────────────

    def _build_mapping_tab(self):
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        grp        = QGroupBox("Class → Output Code Mapping")
        grp_layout = QVBoxLayout(grp)
        grp_layout.setSpacing(0)

        # Header row
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 6, 8, 4)
        lbl_cls  = QLabel("Class")
        lbl_cls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lbl_code = QLabel("Output Code")
        lbl_code.setAlignment(Qt.AlignCenter)
        lbl_code.setFixedWidth(120)
        hdr_font = QFont(); hdr_font.setBold(True)
        lbl_cls.setFont(hdr_font); lbl_code.setFont(hdr_font)
        hdr.addWidget(lbl_cls); hdr.addWidget(lbl_code)
        grp_layout.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        grp_layout.addWidget(sep)

        for idx, (key, name, default_code) in enumerate(self._CLASSES):
            if idx == 5:
                # ── Divider + power-line toggle BEFORE the power rows ──
                div = QFrame()
                div.setFrameShape(QFrame.HLine)
                div.setFrameShadow(QFrame.Sunken)
                grp_layout.addWidget(div)

                cb_row = QHBoxLayout()
                cb_row.setContentsMargins(8, 6, 8, 4)
                self._enable_power_cb = QCheckBox(
                    "Enable Power Line Detection (Wire & Pole)"
                )
                self._enable_power_cb.setChecked(False)
                self._enable_power_cb.setToolTip(
                    "OFF (default): pipeline runs in 5-class mode "
                    "(Ground / Low / Mid / High Veg / Building).\n"
                    "Building detection is preserved exactly.\n\n"
                    "ON: an additional post-pass attempts to identify "
                    "wires and poles. Some building walls may be "
                    "reclassified as poles when this is enabled."
                )
                cb_font = QFont(); cb_font.setBold(True)
                self._enable_power_cb.setFont(cb_font)
                self._enable_power_cb.toggled.connect(self._on_power_toggle)
                cb_row.addWidget(self._enable_power_cb)
                cb_row.addStretch()
                grp_layout.addLayout(cb_row)

            row = QHBoxLayout()
            row.setContentsMargins(8, 5, 8, 5)

            name_lbl = QLabel(name)
            name_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.setValue(default_code)
            spin.setAlignment(Qt.AlignCenter)
            spin.setFixedWidth(120)
            self._code_spins[key] = spin

            # Track power rows so we can grey them out when checkbox is off
            if key in ('wire', 'pole'):
                self._code_labels[key] = name_lbl
                spin.setEnabled(False)
                name_lbl.setEnabled(False)

            row.addWidget(name_lbl)
            row.addWidget(spin)
            grp_layout.addLayout(row)

        layout.addWidget(grp)

        # Presets
        preset_row = QHBoxLayout()
        asprs_btn  = QPushButton("ASPRS Preset")
        asprs_btn.setToolTip(
            "Ground=1  LowVeg=2  MidVeg=3  HighVeg=4  Building=5  Wire=14  Pole=15"
        )
        asprs_btn.clicked.connect(self._apply_asprs)
        preset_row.addWidget(asprs_btn)

        zero_btn = QPushButton("Zero-Based Preset")
        zero_btn.setToolTip(
            "Ground=0  LowVeg=1  MidVeg=2  HighVeg=3  Building=4  Wire=14  Pole=15"
        )
        zero_btn.clicked.connect(self._apply_zero)
        preset_row.addWidget(zero_btn)

        layout.addLayout(preset_row)
        layout.addStretch()
        return page

    # ── POWER TOGGLE HANDLER ─────────────────────────────────

    def _on_power_toggle(self, checked: bool):
        """Enable / disable Wire and Pole spinbox + label together."""
        for key in ('wire', 'pole'):
            if key in self._code_spins:
                self._code_spins[key].setEnabled(checked)
            if key in self._code_labels:
                self._code_labels[key].setEnabled(checked)

    # ── TAB 2: ADVANCED (2-column grid) ──────────────────────

    def _build_advanced_tab(self):
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── MAC loader row ──
        mac_row = QHBoxLayout()
        mac_row.setSpacing(8)

        self._mac_status = QLabel("No .mac file loaded")
        self._mac_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        browse_btn = QPushButton("Browse .mac…")
        browse_btn.setFixedWidth(120)
        browse_btn.clicked.connect(self._load_mac_file)

        reset_btn = QPushButton("Reset Defaults")
        reset_btn.setFixedWidth(120)
        reset_btn.setToolTip("Restore all Advanced parameters to their default values")
        reset_btn.clicked.connect(self._reset_defaults)

        mac_row.addWidget(self._mac_status)
        mac_row.addWidget(browse_btn)
        mac_row.addWidget(reset_btn)
        layout.addLayout(mac_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        grid = QGridLayout()
        grid.setSpacing(8)

        grid.addWidget(self._build_csf_group(),  0, 0)
        grid.addWidget(self._build_hag_group(),  0, 1)
        grid.addWidget(self._build_wire_group(), 1, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch()
        return page

    # ── GROUP BUILDERS ────────────────────────────────────────

    def _build_csf_group(self):
        grp  = QGroupBox("CSF Ground Extraction")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)

        self._adv['csf_cloth_resolution'] = self._dspin(
            0.1, 5.0, _DEFAULTS['csf_cloth_resolution'], 0.1, 2,
            "Cloth grid resolution. Larger = smoother ground model."
        )
        self._adv['csf_rigidness'] = self._ispin(
            1, 3, _DEFAULTS['csf_rigidness'],
            "1 = flat/gentle    2 = moderate    3 = steep/rough terrain"
        )
        self._adv['csf_class_threshold'] = self._dspin(
            0.05, 2.0, _DEFAULTS['csf_class_threshold'], 0.05, 2,
            "Max height above cloth surface to be considered ground."
        )
        form.addRow("Cloth Resolution (m):", self._adv['csf_cloth_resolution'])
        form.addRow("Rigidness (1–3):",       self._adv['csf_rigidness'])
        form.addRow("Class Threshold (m):",   self._adv['csf_class_threshold'])
        return grp

    def _build_hag_group(self):
        grp  = QGroupBox("Vegetation Height Boundaries")
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)

        self._adv['lowveg_min']  = self._dspin(
            0.0, 1.0,  _DEFAULTS['lowveg_min'],  0.05, 2,
            "Points below this HAG are forced to Ground."
        )
        self._adv['lowveg_max']  = self._dspin(
            0.1, 2.0,  _DEFAULTS['lowveg_max'],  0.05, 2,
            "Low Vegetation upper height boundary."
        )
        self._adv['midveg_max']  = self._dspin(
            0.5, 15.0, _DEFAULTS['midveg_max'],  0.25, 2,
            "Medium Vegetation upper height boundary."
        )
        self._adv['highveg_min'] = self._dspin(
            0.5, 15.0, _DEFAULTS['highveg_min'], 0.25, 2,
            "High Vegetation lower boundary."
        )
        form.addRow("Low Veg min (m):",  self._adv['lowveg_min'])
        form.addRow("Low Veg max (m):",  self._adv['lowveg_max'])
        form.addRow("Mid Veg max (m):",  self._adv['midveg_max'])
        form.addRow("High Veg min (m):", self._adv['highveg_min'])
        return grp

    def _build_wire_group(self):
        grp  = QGroupBox("Wire Detection Geometry  (used only when Power Line Detection is enabled)")
        grid = QGridLayout(grp)
        grid.setSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)

        self._adv['wire_hag_min'] = self._dspin(
            0.0, 30.0, _DEFAULTS['wire_hag_min'], 0.5, 1,
            "Wire points below this height are ignored."
        )
        self._adv['wire_hag_max'] = self._dspin(
            5.0, 200.0, _DEFAULTS['wire_hag_max'], 5.0, 1,
            "Wire points above this height are ignored."
        )
        self._adv['wire_chain_radius'] = self._dspin(
            0.5, 20.0, _DEFAULTS['wire_chain_radius'], 0.5, 1,
            "Max gap between wire points to connect."
        )
        self._adv['wire_density_max'] = self._ispin(
            1, 200, _DEFAULTS['wire_density_max'],
            "Max neighbours in 0.5 m radius — filters dense non-wire clusters."
        )
        self._adv['wire_min_segment_pts'] = self._ispin(
            5, 500, _DEFAULTS['wire_min_segment_pts'],
            "Minimum connected points to keep a wire segment."
        )
        self._adv['wire_linearity_min'] = self._dspin(
            0.30, 0.99, _DEFAULTS['wire_linearity_min'], 0.01, 2,
            "Minimum linearity score (0–1). Higher = stricter."
        )

        params_grid = [
            ("HAG Min (m)",         'wire_hag_min',        0, 0),
            ("HAG Max (m)",         'wire_hag_max',        0, 2),
            ("Chain Radius (m)",    'wire_chain_radius',   1, 0),
            ("Density Max",         'wire_density_max',    1, 2),
            ("Min Segment Pts",     'wire_min_segment_pts',2, 0),
            ("Linearity Min",       'wire_linearity_min',  2, 2),
        ]
        for label_text, key, row, col in params_grid:
            lbl = QLabel(label_text + ":")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(lbl,                   row, col)
            grid.addWidget(self._adv[key],        row, col + 1)

        return grp

    # ── MAC LOADER ────────────────────────────────────────────

    def _load_mac_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load TerraScan Macro", "",
            "TerraScan Macro (*.mac);;All Files (*)"
        )
        if not path:
            return

        try:
            params = parse_mac_file(path)
        except Exception as e:
            QMessageBox.warning(self, "MAC Parse Error",
                f"Could not parse the file:\n\n{str(e)}")
            self._mac_status.setText("⚠  Parse failed")
            return

        if not params:
            self._mac_status.setText("⚠  No params found")
            return

        _type_map = {
            'csf_cloth_resolution': float, 'csf_rigidness':        int,
            'csf_class_threshold':  float, 'lowveg_min':           float,
            'lowveg_max':           float, 'midveg_max':           float,
            'highveg_min':          float, 'wire_hag_min':         float,
            'wire_hag_max':         float, 'wire_chain_radius':    float,
            'wire_density_max':     int,   'wire_min_segment_pts': int,
            'wire_linearity_min':   float,
        }
        n_filled = 0
        for key, typ in _type_map.items():
            if key in params and key in self._adv:
                self._adv[key].setValue(typ(params[key]))
                n_filled += 1

        self._mac_status.setText(
            f"✓  {Path(path).name}  ({n_filled} params loaded)"
        )
        print(f"\n  MAC loaded: {path}  ({n_filled} params)")
        for k in params:
            print(f"    {k}: {params[k]}")

    # ── RESET ─────────────────────────────────────────────────

    def _reset_defaults(self):
        for key, val in _DEFAULTS.items():
            if key in self._adv:
                self._adv[key].setValue(val)
        self._mac_status.setText("No .mac file loaded")

    # ── WIDGET FACTORIES ─────────────────────────────────────

    def _dspin(self, lo, hi, val, step, dec, tip=""):
        w = QDoubleSpinBox()
        w.setRange(lo, hi); w.setValue(val)
        w.setSingleStep(step); w.setDecimals(dec)
        w.setAlignment(Qt.AlignRight)
        if tip: w.setToolTip(tip)
        return w

    def _ispin(self, lo, hi, val, tip=""):
        w = QSpinBox()
        w.setRange(lo, hi); w.setValue(val)
        w.setAlignment(Qt.AlignRight)
        if tip: w.setToolTip(tip)
        return w

    # ── PRESETS ───────────────────────────────────────────────

    def _apply_asprs(self):
        for k, v in {0:1, 1:2, 2:3, 3:4, 4:5, 'wire':14, 'pole':15}.items():
            self._code_spins[k].setValue(v)

    def _apply_zero(self):
        for k, v in {0:0, 1:1, 2:2, 3:3, 4:4, 'wire':14, 'pole':15}.items():
            self._code_spins[k].setValue(v)

    # ── VALIDATE + ACCEPT ────────────────────────────────────

    def _validate_and_accept(self):
        enable_power = self._enable_power_cb.isChecked()

        model_codes = [self._code_spins[i].value() for i in range(5)]

        # Only validate wire/pole codes when power detection is enabled.
        if enable_power:
            wire_code = self._code_spins['wire'].value()
            pole_code = self._code_spins['pole'].value()
            all_codes = model_codes + [wire_code, pole_code]

            if len(set(all_codes)) != len(all_codes):
                dupes = {c for c in all_codes if all_codes.count(c) > 1}
                QMessageBox.warning(self, "Duplicate Codes",
                    f"All output codes must be unique.\nDuplicates: {dupes}")
                return
            if wire_code == pole_code:
                QMessageBox.warning(self, "Duplicate Power Codes",
                    f"Wire and Pole codes must differ (both = {wire_code}).")
                return
        else:
            # Validate only the 5 base classes
            if len(set(model_codes)) != len(model_codes):
                dupes = {c for c in model_codes if model_codes.count(c) > 1}
                QMessageBox.warning(self, "Duplicate Codes",
                    f"All output codes must be unique.\nDuplicates: {dupes}")
                return
            wire_code = self._code_spins['wire'].value()
            pole_code = self._code_spins['pole'].value()

        lv_min = self._adv['lowveg_min'].value()
        lv_max = self._adv['lowveg_max'].value()
        mv_max = self._adv['midveg_max'].value()
        wh_min = self._adv['wire_hag_min'].value()
        wh_max = self._adv['wire_hag_max'].value()

        if lv_min >= lv_max:
            self.tabs.setCurrentIndex(1)
            QMessageBox.warning(self, "Invalid HAG Boundaries",
                "Low Veg min must be less than Low Veg max.")
            return
        if lv_max >= mv_max:
            self.tabs.setCurrentIndex(1)
            QMessageBox.warning(self, "Invalid HAG Boundaries",
                "Low Veg max must be less than Mid Veg max.")
            return
        if enable_power and wh_min >= wh_max:
            self.tabs.setCurrentIndex(1)
            QMessageBox.warning(self, "Invalid Wire HAG Range",
                "Wire HAG Min must be less than Wire HAG Max.")
            return

        self.accepted_enable_power_lines = enable_power
        self.accepted_class_mapping      = {i: self._code_spins[i].value()
                                             for i in range(5)}
        self.accepted_power_mapping      = {
            InferenceConfig.WIRE_INTERNAL_CODE: wire_code,
            InferenceConfig.POLE_INTERNAL_CODE: pole_code,
        }
        self.accepted_advanced = {
            'csf_cloth_resolution':  self._adv['csf_cloth_resolution'].value(),
            'csf_rigidness':         self._adv['csf_rigidness'].value(),
            'csf_class_threshold':   self._adv['csf_class_threshold'].value(),
            'lowveg_min':  lv_min,  'lowveg_max':  lv_max,
            'midveg_max':  mv_max,
            'highveg_min': self._adv['highveg_min'].value(),
            'wire_hag_min':          wh_min,
            'wire_hag_max':          wh_max,
            'wire_chain_radius':     self._adv['wire_chain_radius'].value(),
            'wire_density_max':      self._adv['wire_density_max'].value(),
            'wire_min_segment_pts':  self._adv['wire_min_segment_pts'].value(),
            'wire_linearity_min':    self._adv['wire_linearity_min'].value(),
        }
        self.accept()

    def get_class_mapping(self):        return self.accepted_class_mapping
    def get_power_mapping(self):        return self.accepted_power_mapping
    def get_advanced_config(self):      return self.accepted_advanced
    def get_enable_power_lines(self):   return self.accepted_enable_power_lines


# ═══════════════════════════════════════════════════════════════
# PROGRESS DIALOG
# ═══════════════════════════════════════════════════════════════

class AIClassificationDialog(QDialog):

    def __init__(self, app, class_mapping, power_mapping,
                 advanced_config=None, enable_power_lines=False, parent=None):
        super().__init__(parent)
        self.app                = app
        self.class_mapping      = class_mapping
        self.power_mapping      = power_mapping
        self.advanced_config    = advanced_config or {}
        self.enable_power_lines = bool(enable_power_lines)
        self.worker             = None
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("AI Classification")
        self.setMinimumWidth(520)
        self.setModal(True)
        layout = QVBoxLayout(self)

        mode = "with Power Lines" if self.enable_power_lines else "5-class mode"
        self.status_label = QLabel(f"Initializing AI pipeline ({mode})...")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_classification)
        btn_row.addWidget(self.cancel_btn)
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

    def start_classification(self, data_dict):
        from gui.ai_inference import InferenceWorker
        self.worker = InferenceWorker(
            data_dict,
            self.class_mapping,
            self.power_mapping,
            advanced_config=self.advanced_config,
            enable_power_lines=self.enable_power_lines,
        )
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.classification_finished)
        self.worker.error.connect(self.classification_error)
        self.worker.start()

    def update_progress(self, percent, message):
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def classification_finished(self):
        self.progress_bar.setValue(100)
        self.status_label.setText("Classification complete!")
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                torch.cuda.empty_cache()
                print("✅ AI finish: CUDA memory released")
        except Exception:
            pass
        try:
            import gc
            gc.collect()
            print("✅ AI finish: GC collected")
        except Exception:
            pass

        self._teardown_worker()

        try:
            summary = self._build_result_summary()
            if hasattr(self.app, 'refresh_display'):
                self.app.refresh_display()
            elif hasattr(self.app, 'vtk_widget'):
                if hasattr(self.app.vtk_widget, 'update_colors_from_classification'):
                    self.app.vtk_widget.update_colors_from_classification()
                else:
                    self.app.vtk_widget.render()
            QMessageBox.information(self, "AI Classification Complete", summary)
            self.accept()
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Display Update Failed",
                f"Classification succeeded but display update failed:\n\n"
                f"{str(e)}\n\nData IS stored in memory.")
            print(f"Display error:\n{traceback.format_exc()}")

    def _build_result_summary(self):
        from gui.ai_inference import InferenceConfig
        model_names = {0:'Ground', 1:'Low Vegetation', 2:'Medium Vegetation',
                       3:'High Vegetation', 4:'Building'}
        code_to_name = {v: model_names[k] for k, v in self.class_mapping.items()}

        wire_out = pole_out = None
        if self.enable_power_lines:
            wire_out = self.power_mapping.get(InferenceConfig.WIRE_INTERNAL_CODE, 14)
            pole_out = self.power_mapping.get(InferenceConfig.POLE_INTERNAL_CODE, 15)
            code_to_name[wire_out] = "Power Line Wire"
            code_to_name[pole_out] = "Power Line Pole/Tower"

        try:
            classification = self.app.data.get("classification")
            if classification is None:
                return "Classification complete!\n\nNo result data available."
            n_total      = len(classification)
            unique, cnts = np.unique(classification, return_counts=True)
            mode = "Power Line mode" if self.enable_power_lines else "5-class mode"
            lines = [f"Classification complete! ({mode})\n",
                     f"Total points: {n_total:,}\n", "Results:"]
            for cls, cnt in zip(unique, cnts):
                ci   = int(cls)
                name = code_to_name.get(ci, f'Code {ci}')
                pct  = 100 * cnt / n_total
                icon = "⚡" if (self.enable_power_lines and ci in (wire_out, pole_out)) else " "
                lines.append(f"  {icon} {name} (code {ci}): {cnt:,} ({pct:.1f}%)")
            if self.enable_power_lines:
                n_wire = int(np.sum(classification == wire_out))
                n_pole = int(np.sum(classification == pole_out))
                if n_wire > 0 or n_pole > 0:
                    lines.append("\nPower Line Detection:")
                    if n_wire > 0: lines.append(f"  Wire (code {wire_out}): {n_wire:,} pts")
                    if n_pole > 0: lines.append(f"  Pole (code {pole_out}): {n_pole:,} pts")
            return "\n".join(lines)
        except Exception:
            return "Classification complete!\n\nPoint cloud updated."

    def classification_error(self, error_msg):
        self.status_label.setText("Classification failed")
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self._teardown_worker()
        QMessageBox.critical(self, "AI Classification Failed",
            f"Error:\n\n{error_msg}")

    def cancel_classification(self):
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Cancelling...")
            self.cancel_btn.setEnabled(False)
            self.worker.cancel()
            if not self.worker.wait(5000):
                QMessageBox.warning(self, "Timeout",
                    "Worker did not respond in time. Force closing.")
            self.status_label.setText("Classification cancelled")
            self.close_btn.setEnabled(True)

    def _teardown_worker(self):
        if self.worker is None:
            return
        try:
            self.worker.progress.disconnect()
            self.worker.finished.disconnect()
            self.worker.error.disconnect()
        except RuntimeError:
            pass
        self.worker.deleteLater()
        self.worker = None

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(self, "In Progress",
                "Classification is still running. Cancel and close?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.worker.cancel()
                self.worker.wait(5000)
                self._teardown_worker()
                event.accept()
            else:
                event.ignore()
        else:
            self._teardown_worker()
            event.accept()


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

def _find_source_file_from_app(app):
    if hasattr(app, 'data') and app.data is not None:
        for key in ['file_path','filepath','source_file','path','filename',
                    'las_path','laz_path','input_path','current_file',
                    'loaded_file','source_path','file','las_file','laz_file']:
            if key in app.data:
                val = app.data[key]
                if val is not None:
                    p = Path(str(val))
                    if p.exists() and p.suffix.lower() in ('.laz', '.las'):
                        return p
        for key, val in app.data.items():
            if isinstance(val, (str, Path)):
                p = Path(str(val))
                if p.exists() and p.suffix.lower() in ('.laz', '.las'):
                    return p
    for attr in ['current_file','file_path','filepath','loaded_file',
                 'source_file','current_path','las_path','laz_path',
                 'input_file','filename']:
        if hasattr(app, attr):
            val = getattr(app, attr)
            if val is not None:
                p = Path(str(val))
                if p.exists() and p.suffix.lower() in ('.laz', '.las'):
                    return p
    return None


def show_ai_classification_dialog(app):
    from gui.ai_inference import HAS_JAKTERISTICS, HAS_CSF
    try:
        if not HAS_JAKTERISTICS:
            QMessageBox.critical(app, "Missing Dependency",
                "jakteristics is required.\n\npip install jakteristics"); return
        if not HAS_CSF:
            QMessageBox.critical(app, "Missing Dependency",
                "CSF is required.\n\npip install cloth-simulation-filter"); return
        if not hasattr(app, 'data') or app.data is None:
            QMessageBox.warning(app, "No Point Cloud",
                "Please load a LAZ/LAS file first."); return
        if 'xyz' not in app.data or app.data['xyz'] is None:
            QMessageBox.warning(app, "Invalid Data",
                "Missing XYZ coordinates. Please reload the file."); return

        n_points = len(app.data['xyz'])
        if n_points < 100:
            QMessageBox.warning(app, "Too Few Points",
                f"Only {n_points} points found."); return

        print(f"\n{'='*60}\nAI CLASSIFICATION — DATA VALIDATION\n{'='*60}")
        print(f"  Points: {n_points:,}")

        source_file = _find_source_file_from_app(app)
        if source_file:
            print(f"  Source file: {source_file}")
            app.data['_source_file_path'] = str(source_file)
        else:
            print("  WARNING: Source LAZ/LAS file not found!")

        has_rn = ('return_number' in app.data
                  and app.data['return_number'] is not None
                  and len(app.data['return_number']) == n_points
                  and np.max(app.data['return_number']) > 0)
        has_nr = ('number_of_returns' in app.data
                  and app.data['number_of_returns'] is not None
                  and len(app.data['number_of_returns']) == n_points
                  and np.max(app.data['number_of_returns']) > 0)

        if (not has_rn or not has_nr) and source_file:
            print("  Returns missing — reading from source file...")
            try:
                import laspy
                las = laspy.read(str(source_file))
                rn = None; nr = None
                if hasattr(las, 'return_number'):
                    c = np.array(las.return_number, dtype=np.float32)
                    if c.max() > 0: rn = c
                if hasattr(las, 'number_of_returns'):
                    c = np.array(las.number_of_returns, dtype=np.float32)
                    if c.max() > 0: nr = c
                if rn is None or nr is None:
                    dim_names = list(las.point_format.dimension_names)
                    for name in ['return_number','ReturnNumber','return_num']:
                        if name in dim_names and rn is None:
                            c = np.array(las[name], dtype=np.float32)
                            if c.max() > 0: rn = c; break
                    for name in ['number_of_returns','NumberOfReturns','num_returns']:
                        if name in dim_names and nr is None:
                            c = np.array(las[name], dtype=np.float32)
                            if c.max() > 0: nr = c; break
                if rn is None or nr is None or rn.max() == 0 or nr.max() == 0:
                    print("  WARNING: synthesizing single-return.")
                    rn = np.ones(len(las.x), dtype=np.float32)
                    nr = np.ones(len(las.x), dtype=np.float32)
                if len(rn) == n_points and len(nr) == n_points:
                    app.data['return_number'] = rn
                    app.data['number_of_returns'] = nr
                    has_rn = rn.max() > 0; has_nr = nr.max() > 0
                has_intensity = ('intensity' in app.data
                                 and app.data['intensity'] is not None
                                 and len(app.data['intensity']) == n_points
                                 and np.max(app.data['intensity']) > 0)
                if not has_intensity and hasattr(las, 'intensity'):
                    intensity = np.array(las.intensity, dtype=np.float32)
                    if len(intensity) == n_points:
                        app.data['intensity'] = intensity
                del las
            except Exception as e:
                import traceback
                print(f"  WARNING: Failed to read source file: {e}")
                traceback.print_exc()

        has_intensity = ('intensity' in app.data
                         and app.data['intensity'] is not None
                         and len(app.data['intensity']) == n_points)
        print(f"  has_intensity: {has_intensity}")
        print(f"  has_returns:   {has_rn and has_nr}")
        print(f"{'='*60}\n")

        warnings = []
        if not has_intensity:
            warnings.append("• INTENSITY unavailable — zero-filled")
        if not (has_rn and has_nr):
            warnings.append("• RETURN NUMBER data unavailable.\n"
                            "  Building and vegetation separation WILL be degraded.")
        if warnings:
            reply = QMessageBox.warning(app, "Missing LiDAR Attributes",
                "Data warnings:\n\n" + "\n\n".join(warnings) + "\n\nProceed anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return

        existing_classes = set()
        if ('classification' in app.data and app.data['classification'] is not None):
            existing_classes = set(
                int(c) for c in np.unique(app.data['classification'])
            )

        mapping_dialog = ClassMappingDialog(
            parent=app, existing_classes=existing_classes
        )
        if mapping_dialog.exec() != QDialog.Accepted:
            print("  Cancelled by user"); return

        class_mapping       = mapping_dialog.get_class_mapping()
        power_mapping       = mapping_dialog.get_power_mapping()
        advanced_config     = mapping_dialog.get_advanced_config()
        enable_power_lines  = mapping_dialog.get_enable_power_lines()

        if class_mapping is None or power_mapping is None:
            return

        print(f"  Power-line detection: "
              f"{'ENABLED' if enable_power_lines else 'DISABLED (5-class mode)'}")

        progress_dialog = AIClassificationDialog(
            app, class_mapping, power_mapping,
            advanced_config=advanced_config,
            enable_power_lines=enable_power_lines,
            parent=app,
        )
        progress_dialog.start_classification(app.data)
        progress_dialog.exec()

    except Exception as e:
        import traceback
        QMessageBox.critical(app, "Initialization Failed",
            f"Failed to start AI classification:\n\n{str(e)}")
        print(f"Dialog init error:\n{traceback.format_exc()}")