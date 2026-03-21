from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import os
import re

import laspy
from laspy.vlrs.known import WktCoordinateSystemVlr
from pyproj import CRS

from gui.theme_manager import ThemeColors, get_dialog_stylesheet


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


DEFAULT_IMPORT_OPTIONS = {
    "cloud_type": "Airborne lidar",
    "system": "Other",
    "input_proj": "",
    "active_proj": "",
    "only_every": False,
    "nth_point": 10,
    "only_class": False,
    "class_code": 0,
    "line_mode": "Use from file",
    "scanner_mode": "File -- scanner byte",
    "attributes": {
        "XYZ": True,
        "Amplitude": False,
        "Angle": False,
        "Normal vector": False,
        "Reflectance": False,
        "Line": False,
        "Group": False,
        "Time": False,
        "Deviation": False,
        "Color": True,
        "Intensity": True,
        "Distance": False,
        "Scanner": False,
    },
}


class LoadPointCloudDialog(QDialog):
    def __init__(self, filename, parent=None, disabled_attrs=None, initial_options=None):
        super().__init__(parent)
        self.setProperty("themeStyledDialog", True)
        self.filename = filename
        self.disabled_attrs = set(disabled_attrs or [])
        self._metadata = self._read_header_metadata(filename)
        self._options = self._merge_options(initial_options)

        self.setWindowTitle(f"Read points - {os.path.basename(filename)}")
        self.resize(760, 620)
        self.refresh_theme()

        self._build_ui()
        self._connect_signals()
        self._apply_initial_state()

    def _build_stylesheet(self):
        c = ThemeColors
        return (
            get_dialog_stylesheet()
            + f"""
            QFrame#dialogSheet {{
                background-color: {c.get('bg_secondary')};
                border: 1px solid {c.get('border_light')};
                border-radius: 14px;
            }}
            QFrame#summaryStrip {{
                background-color: {c.get('bg_input')};
                border: 1px solid {c.get('border_light')};
                border-radius: 10px;
            }}
            QFrame#sheetDivider {{
                min-height: 1px;
                max-height: 1px;
                border: none;
                background-color: {c.get('border_light')};
            }}
            QLabel#metaLabel {{
                color: {c.get('text_secondary')};
                font-size: 8.5pt;
                font-weight: 600;
            }}
            QLabel#metaValue {{
                color: {c.get('text_primary')};
                font-size: 10.5pt;
                font-weight: 700;
            }}
            QLabel#sheetSectionTitle {{
                color: {c.get('text_primary')};
                font-size: 10pt;
                font-weight: 700;
            }}
            QLabel#sheetSectionHint {{
                color: {c.get('text_secondary')};
                font-size: 8.8pt;
            }}
            QLabel#fieldLabel {{
                color: {c.get('text_primary')};
                font-weight: 600;
            }}
            QLineEdit#rangeField {{
                padding-top: 6px;
                padding-bottom: 6px;
            }}
            """
        )

    def refresh_theme(self):
        self.setStyleSheet(self._build_stylesheet())

    def _merge_options(self, initial_options):
        merged = {
            key: value
            for key, value in DEFAULT_IMPORT_OPTIONS.items()
            if key != "attributes"
        }
        merged["attributes"] = dict(DEFAULT_IMPORT_OPTIONS["attributes"])
        if not initial_options:
            return merged

        for key, value in initial_options.items():
            if key == "attributes" and isinstance(value, dict):
                merged["attributes"].update(value)
            else:
                merged[key] = value
        return merged

    def _read_header_metadata(self, filename):
        metadata = {
            "point_count": 0,
            "format": "Unknown",
            "coords_text": "",
            "crs_epsg": None,
        }

        try:
            if filename.lower().endswith((".las", ".laz")):
                with laspy.open(filename) as las_file:
                    header = las_file.header
                    metadata["point_count"] = header.point_count
                    ext = os.path.splitext(filename)[1].lower()
                    fmt_prefix = "LAZ" if ext == ".laz" else "LAS"
                    metadata["format"] = f"{fmt_prefix} {header.version.major}.{header.version.minor}"
                    metadata["coords_text"] = f"{header.mins}  ->  {header.maxs}"

                    for vlr in header.vlrs:
                        if isinstance(vlr, WktCoordinateSystemVlr):
                            try:
                                metadata["crs_epsg"] = CRS.from_wkt(vlr.string).to_epsg()
                            except Exception:
                                match = re.search(r"EPSG[\"']?,?\s?(\d+)", vlr.string, re.IGNORECASE)
                                if match:
                                    metadata["crs_epsg"] = int(match.group(1))
                            break

            if metadata["crs_epsg"] is None:
                prj_file = os.path.splitext(filename)[0] + ".prj"
                if os.path.exists(prj_file):
                    with open(prj_file, "r", encoding="utf-8", errors="ignore") as file_obj:
                        prj_text = file_obj.read().strip()
                    try:
                        metadata["crs_epsg"] = CRS.from_wkt(prj_text).to_epsg()
                    except Exception:
                        metadata["crs_epsg"] = None
        except Exception:
            pass

        return metadata

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        title = QLabel("Import Point Cloud")
        title.setObjectName("dialogTitle")
        title_col.addWidget(title)

        subtitle = QLabel(os.path.basename(self.filename))
        subtitle.setObjectName("dialogSubtitle")
        title_col.addWidget(subtitle)

        header_row.addLayout(title_col, 1)
        header_row.addStretch()

        header_row.addWidget(self._make_value_pill(self._metadata["format"]))
        header_row.addWidget(
            self._make_value_pill(f"{self._metadata['point_count']:,} points")
        )
        root.addLayout(header_row)

        summary_strip = QFrame()
        summary_strip.setObjectName("summaryStrip")
        summary_layout = QGridLayout(summary_strip)
        summary_layout.setContentsMargins(14, 10, 14, 10)
        summary_layout.setHorizontalSpacing(18)
        summary_layout.setVerticalSpacing(4)

        summary_layout.addWidget(self._make_meta_block("Format", self._metadata["format"]), 0, 0)
        summary_layout.addWidget(
            self._make_meta_block("Points", f"{self._metadata['point_count']:,}"),
            0,
            1,
        )
        summary_layout.addWidget(
            self._make_meta_block(
                "EPSG",
                str(self._metadata["crs_epsg"]) if self._metadata["crs_epsg"] else "Unknown",
            ),
            0,
            2,
        )
        root.addWidget(summary_strip)

        sheet = QFrame()
        sheet.setObjectName("dialogSheet")
        sheet_layout = QVBoxLayout(sheet)
        sheet_layout.setContentsMargins(18, 18, 18, 18)
        sheet_layout.setSpacing(14)

        sheet_layout.addLayout(
            self._make_section_header(
                "Source and coordinate setup",
                "Set cloud context, projection values, and the import filters you want to apply.",
            )
        )

        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(14)
        form_grid.setVerticalSpacing(12)

        self.cloud_type = QComboBox()
        self.cloud_type.addItems(["Airborne lidar", "Terrestrial lidar", "Mobile lidar", "Other"])

        self.system_box = QComboBox()
        self.system_box.addItems(["Other", "Optech", "Leica", "Riegl"])

        self.format_box = self._make_readonly_field(self._metadata["format"])
        self.points_box = self._make_readonly_field(f"{self._metadata['point_count']:,}")
        self.input_proj = QLineEdit()
        self.active_proj = QLineEdit()
        self.coordinates_box = self._make_readonly_field(self._metadata["coords_text"])
        self.coordinates_box.setObjectName("rangeField")
        self.coordinates_box.setToolTip(self._metadata["coords_text"])

        form_grid.addWidget(self._make_field_label("Cloud type"), 0, 0)
        form_grid.addWidget(self.cloud_type, 0, 1)
        form_grid.addWidget(self._make_field_label("System"), 0, 2)
        form_grid.addWidget(self.system_box, 0, 3)

        form_grid.addWidget(self._make_field_label("Format"), 1, 0)
        form_grid.addWidget(self.format_box, 1, 1)
        form_grid.addWidget(self._make_field_label("Points"), 1, 2)
        form_grid.addWidget(self.points_box, 1, 3)

        form_grid.addWidget(self._make_field_label("Input projection (EPSG)"), 2, 0)
        form_grid.addWidget(self.input_proj, 2, 1)
        form_grid.addWidget(self._make_field_label("Active projection (EPSG)"), 2, 2)
        form_grid.addWidget(self.active_proj, 2, 3)

        form_grid.addWidget(self._make_field_label("Coordinate range"), 3, 0)
        form_grid.addWidget(self.coordinates_box, 3, 1, 1, 3)
        sheet_layout.addLayout(form_grid)

        sheet_layout.addWidget(self._make_divider())

        options_grid = QGridLayout()
        options_grid.setHorizontalSpacing(14)
        options_grid.setVerticalSpacing(12)

        options_grid.addLayout(
            self._make_section_header("Import filters", "Keep the load decision focused and predictable."),
            0,
            0,
            1,
            4,
        )

        self.only_every = QCheckBox("Load every Nth point")
        self.nth_spin = QSpinBox()
        self.nth_spin.setRange(1, 1000)
        self.nth_spin.setFixedWidth(96)

        self.only_class = QCheckBox("Load one classification")
        self.class_box = QComboBox()
        self.class_box.addItems(
            [f"{code} - {CLASS_NAMES.get(code, 'Unknown')}" for code in range(19)]
        )

        self.line_mode = QComboBox()
        self.line_mode.addItems(["Use from file", "Generate"])

        self.scanner_mode = QComboBox()
        self.scanner_mode.addItems(["File -- scanner byte", "Auto assign"])

        options_grid.addWidget(self.only_every, 1, 0)
        options_grid.addWidget(self.nth_spin, 1, 1)
        options_grid.addWidget(self._make_field_label("Line numbers"), 1, 2)
        options_grid.addWidget(self.line_mode, 1, 3)

        options_grid.addWidget(self.only_class, 2, 0)
        options_grid.addWidget(self.class_box, 2, 1)
        options_grid.addWidget(self._make_field_label("Scanner numbers"), 2, 2)
        options_grid.addWidget(self.scanner_mode, 2, 3)
        sheet_layout.addLayout(options_grid)

        sheet_layout.addWidget(self._make_divider())

        sheet_layout.addLayout(
            self._make_section_header(
                "Attributes to carry into the session",
                "Leave rarely used channels off unless the next tool really needs them.",
            )
        )

        attr_grid = QGridLayout()
        attr_grid.setHorizontalSpacing(30)
        attr_grid.setVerticalSpacing(10)

        self.attr_checks = {}
        attrs = [
            "XYZ",
            "Amplitude",
            "Angle",
            "Normal vector",
            "Reflectance",
            "Line",
            "Group",
            "Time",
            "Deviation",
            "Color",
            "Intensity",
            "Distance",
            "Scanner",
        ]

        for index, attr_name in enumerate(attrs):
            checkbox = QCheckBox(attr_name)
            checkbox.setProperty("primaryAttr", attr_name in {"XYZ", "Color", "Intensity"})
            if attr_name in self.disabled_attrs:
                checkbox.setChecked(False)
                checkbox.setEnabled(False)
            self.attr_checks[attr_name] = checkbox
            attr_grid.addWidget(checkbox, index // 3, index % 3)
        sheet_layout.addLayout(attr_grid)

        root.addWidget(sheet)

        hint = QLabel(
            "Review the file metadata, adjust any sampling or class filter, then start the import."
        )
        hint.setObjectName("dialogCaption")
        hint.setWordWrap(True)
        root.addWidget(hint)

        actions = QHBoxLayout()
        actions.addStretch()

        cancel_btn = QPushButton("Cancel")
        load_btn = QPushButton("Load Points")
        load_btn.setObjectName("primaryBtn")
        load_btn.setMinimumWidth(128)

        actions.addWidget(cancel_btn)
        actions.addWidget(load_btn)
        root.addLayout(actions)

        cancel_btn.clicked.connect(self.reject)
        load_btn.clicked.connect(self.accept)

    def _make_value_pill(self, text):
        label = QLabel(text)
        label.setObjectName("valuePill")
        label.setAlignment(Qt.AlignCenter)
        return label

    def _make_meta_block(self, label_text, value_text):
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        label = QLabel(label_text)
        label.setObjectName("metaLabel")
        layout.addWidget(label)

        value = QLabel(value_text)
        value.setObjectName("metaValue")
        value.setWordWrap(True)
        layout.addWidget(value)
        return wrapper

    def _make_section_header(self, title_text, hint_text):
        layout = QVBoxLayout()
        layout.setSpacing(2)

        title = QLabel(title_text)
        title.setObjectName("sheetSectionTitle")
        layout.addWidget(title)

        hint = QLabel(hint_text)
        hint.setObjectName("sheetSectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return layout

    def _make_field_label(self, text):
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _make_readonly_field(self, text):
        field = QLineEdit(text)
        field.setReadOnly(True)
        field.setCursorPosition(0)
        return field

    def _make_divider(self):
        divider = QFrame()
        divider.setObjectName("sheetDivider")
        divider.setFrameShape(QFrame.HLine)
        divider.setFrameShadow(QFrame.Plain)
        return divider

    def _connect_signals(self):
        self.only_every.toggled.connect(self.nth_spin.setEnabled)
        self.only_class.toggled.connect(self.class_box.setEnabled)

    def _apply_initial_state(self):
        self.cloud_type.setCurrentText(self._options["cloud_type"])
        self.system_box.setCurrentText(self._options["system"])
        self.input_proj.setText(
            self._options["input_proj"]
            or (str(self._metadata["crs_epsg"]) if self._metadata["crs_epsg"] else "")
        )
        self.active_proj.setText(
            self._options["active_proj"]
            or (str(self._metadata["crs_epsg"]) if self._metadata["crs_epsg"] else "")
        )
        self.only_every.setChecked(bool(self._options["only_every"]))
        self.nth_spin.setValue(max(1, int(self._options["nth_point"])))
        self.only_class.setChecked(bool(self._options["only_class"]))
        self.class_box.setCurrentText(
            f"{int(self._options['class_code'])} - {CLASS_NAMES.get(int(self._options['class_code']), 'Unknown')}"
        )
        self.line_mode.setCurrentText(self._options["line_mode"])
        self.scanner_mode.setCurrentText(self._options["scanner_mode"])

        for attr_name, checkbox in self.attr_checks.items():
            if attr_name in self.disabled_attrs:
                checkbox.setChecked(False)
                checkbox.setEnabled(False)
                continue
            checkbox.setChecked(bool(self._options["attributes"].get(attr_name, False)))

        self.nth_spin.setEnabled(self.only_every.isChecked())
        self.class_box.setEnabled(self.only_class.isChecked())

    def get_import_options(self):
        class_code = 0
        try:
            class_code = int(self.class_box.currentText().split(" - ", 1)[0])
        except Exception:
            class_code = 0

        return {
            "cloud_type": self.cloud_type.currentText(),
            "system": self.system_box.currentText(),
            "input_proj": self.input_proj.text().strip(),
            "active_proj": self.active_proj.text().strip(),
            "only_every": self.only_every.isChecked(),
            "nth_point": int(self.nth_spin.value()),
            "only_class": self.only_class.isChecked(),
            "class_code": class_code,
            "line_mode": self.line_mode.currentText(),
            "scanner_mode": self.scanner_mode.currentText(),
            "attributes": {
                name: checkbox.isChecked()
                for name, checkbox in self.attr_checks.items()
            },
        }
