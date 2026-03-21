from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QCheckBox, QPushButton, QSpinBox, QFormLayout, QGroupBox, QGridLayout
)
from PySide6.QtCore import Qt
import laspy, os, re
from laspy.vlrs.known import WktCoordinateSystemVlr
from pyproj import CRS


class LoadPointCloudDialog(QDialog):
    def __init__(self, filename, parent=None, disabled_attrs=None):
        super().__init__(parent)
        self.setWindowTitle(f"Read points - {os.path.basename(filename)}")
        self.resize(600, 500)

        # ✅ allow disabling attributes for formats like DXF
        if disabled_attrs is None:
            disabled_attrs = []

        layout = QVBoxLayout()

        # --- Read LAS header if possible ---
        las = None
        point_count, fmt = 0, "Unknown"
        try:
            if filename.lower().endswith((".las", ".laz")):
                las = laspy.read(filename)
                point_count = las.header.point_count
                ext = os.path.splitext(filename)[1].lower()  # .las or .laz
                fmt_prefix = "LAZ" if ext == ".laz" else "LAS"
                fmt = f"{fmt_prefix} {las.header.version.major}.{las.header.version.minor}"
        except Exception:
            pass

        # --- Detect CRS ---
        crs_wkt, crs_epsg = None, None
        if las:
            for vlr in las.header.vlrs:
                if isinstance(vlr, WktCoordinateSystemVlr):
                    crs_wkt = vlr.string
                    try:
                        crs_epsg = CRS.from_wkt(crs_wkt).to_epsg()
                    except Exception:
                        m = re.search(r"EPSG[\"']?,?\s?(\d+)", crs_wkt, re.IGNORECASE)
                        if m:
                            crs_epsg = int(m.group(1))
                    break

        if crs_wkt is None:
            prj_file = os.path.splitext(filename)[0] + ".prj"
            if os.path.exists(prj_file):
                with open(prj_file, "r") as f:
                    crs_wkt = f.read().strip()
                try:
                    crs_epsg = CRS.from_wkt(crs_wkt).to_epsg()
                except Exception:
                    crs_epsg = None

        # --- Row 1: Cloud type & System ---
        row1 = QHBoxLayout()
        self.cloud_type = QComboBox()
        self.cloud_type.addItems(["Airborne lidar", "Terrestrial lidar", "Mobile lidar", "Other"])
        self.system_box = QComboBox()
        self.system_box.addItems(["Other", "Optech", "Leica", "Riegl"])
        row1.addWidget(QLabel("Cloud type:"))
        row1.addWidget(self.cloud_type)
        row1.addWidget(QLabel("System:"))
        row1.addWidget(self.system_box)
        layout.addLayout(row1)

        # --- Row 2: Format & Points ---
        row2 = QHBoxLayout()
        self.format_box = QLineEdit(fmt)
        self.format_box.setReadOnly(True)
        row2.addWidget(QLabel("Format:"))
        row2.addWidget(self.format_box)
        row2.addWidget(QLabel(f"Points: {point_count:,}"))
        layout.addLayout(row2)

        # --- CRS Input & Active projection ---
        form = QFormLayout()
        self.input_proj = QLineEdit(str(crs_epsg) if crs_epsg else "")
        self.active_proj = QLineEdit(str(crs_epsg) if crs_epsg else "")
        form.addRow("Input projection (EPSG):", self.input_proj)
        form.addRow("Active projection (EPSG):", self.active_proj)
        layout.addLayout(form)

        # --- Coordinates ---
        if las:
            coords = f"{las.header.mins} --> {las.header.maxs}"
            layout.addWidget(QLabel(f"Coordinates: {coords}"))

        # --- Filters ---
        self.only_every = QCheckBox("Only every Nth point")
        self.nth_spin = QSpinBox()
        self.nth_spin.setRange(1, 1000)
        self.nth_spin.setValue(10)
        row3 = QHBoxLayout()
        row3.addWidget(self.only_every)
        row3.addWidget(self.nth_spin)
        layout.addLayout(row3)

        self.only_class = QCheckBox("Only class")
        self.class_box = QComboBox()

        CLASS_NAMES = {
            0: "Created, never classified",
            1: "Unclassified",
            2: "Ground",
            3: "Low vegetation",
            4: "Medium vegetation",
            5: "High vegetation",
            6: "Building",
            7: "Low point (noise)",
            8: "Model key-point",
            9: "Water",
            10: "Rail",
            11: "Road surface",
            12: "Overlap points",
            13: "Wire guard",
            14: "Wire conductor",
            15: "Transmission tower",
            16: "Wire connector",
            17: "Bridge deck",
            18: "High noise",
        }
        self.class_box.addItems([f"{c} - {CLASS_NAMES.get(c, 'Unknown')}"
                                 for c in range(0, 19)])

        row4 = QHBoxLayout()
        row4.addWidget(self.only_class)
        row4.addWidget(self.class_box)
        layout.addLayout(row4)

        # --- Attributes selection ---
        attrs_group = QGroupBox("Attributes")
        grid = QGridLayout()
        self.attr_checks = {}
        attrs = [
            "XYZ","Amplitude","Angle","Normal vector","Reflectance","Line",
            "Group","Time","Deviation","Color","Intensity","Distance","Scanner"
        ]
        for i, a in enumerate(attrs):
            cb = QCheckBox(a)
            cb.setChecked(a in ["XYZ", "Color", "Intensity"])
            if a in disabled_attrs:
                cb.setChecked(False)
                cb.setEnabled(False)  # ✅ grey out
            self.attr_checks[a] = cb
            grid.addWidget(cb, i // 3, i % 3)
        attrs_group.setLayout(grid)
        layout.addWidget(attrs_group)

        # --- Line/Scanner numbers ---
        self.line_mode = QComboBox()
        self.line_mode.addItems(["Use from file", "Generate"])
        self.scanner_mode = QComboBox()
        self.scanner_mode.addItems(["File -- scanner byte", "Auto assign"])
        form2 = QFormLayout()
        form2.addRow("Line numbers:", self.line_mode)
        form2.addRow("Scanner numbers:", self.scanner_mode)
        layout.addLayout(form2)

        # --- Buttons ---
        btns = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)

        self.setLayout(layout)
