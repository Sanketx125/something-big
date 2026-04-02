# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec file for Naksha Point Cloud Tool
# Build command:  pyinstaller naksha.spec
#

import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

block_cipher = None

# ── Collect entire packages that hide their internals ──────────────────────
open3d_datas, open3d_binaries, open3d_hiddenimports = collect_all('open3d')
vtk_datas,    vtk_binaries,    vtk_hiddenimports    = collect_all('vtk')
pyvista_datas, pyvista_binaries, pyvista_hiddenimports = collect_all('pyvista')
pyvistaqt_datas, pyvistaqt_binaries, pyvistaqt_hiddenimports = collect_all('pyvistaqt')
laspy_datas,  laspy_binaries,  laspy_hiddenimports  = collect_all('laspy')
shapely_datas, shapely_binaries, shapely_hiddenimports = collect_all('shapely')

# ── Data files (assets bundled into the exe) ───────────────────────────────
added_datas = [
    # GUI assets
    ('gui/icons',         'gui/icons'),
    ('gui/theme.qss',     'gui/'),
    ('gui/theme_light.qss', 'gui/'),

    # AI models
    ('models',            'models'),

    # Any .mnu menu files in root
    ('*.mnu',             '.'),
]

# Merge collected datas
added_datas += open3d_datas + vtk_datas + pyvista_datas + pyvistaqt_datas + laspy_datas + shapely_datas

# ── Binaries (DLLs / .pyd files) ──────────────────────────────────────────
added_binaries = [
    # Your custom compiled accelerator
    ('classify_accel.cp310-win_amd64.pyd', '.'),
]

added_binaries += open3d_binaries + vtk_binaries + pyvista_binaries + pyvistaqt_binaries + laspy_binaries + shapely_binaries

# ── Hidden imports (packages PyInstaller misses via static analysis) ───────
hidden_imports = [
    # App packages
    'gui',
    'gui.app_window',
    'gui.menu_sidebar_system',
    'gui.icon_provider',
    'gui.shortcut_manager',
    'gui.global_shortcuts',
    'gui.display_mode',
    'gui.shading_display',
    'gui.digitize_tools',
    'gui.vector_export',
    'gui.backup_settings_dialog',
    'gui.cross_section',
    'gui.cross_section.section_controller',
    'gui.cross_section.cut_section_controller',
    'gui.cross_section.backup_settings_dialog',
    'gui.cross_section.interactor_classify',
    'gui.cross_section.interactor_slice',
    'gui.dialogs',
    'gui.dialogs.load_pointcloud_dialog',

    # Scientific stack
    'numpy',
    'scipy',
    'scipy.spatial',
    'scipy.spatial.transform',
    'matplotlib',
    'matplotlib.backends.backend_agg',

    # Geospatial
    'pyproj',
    'geopandas',
    'fiona',
    'rasterio',
    'ezdxf',

    # Qt / PySide6
    'PySide6',
    'PySide6.QtWidgets',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',

    # Other
    'zstandard',
    'psutil',
    'GPUtil',
    'torch',
    'onnxruntime',
]

hidden_imports += open3d_hiddenimports + vtk_hiddenimports + pyvista_hiddenimports + pyvistaqt_hiddenimports + laspy_hiddenimports + shapely_hiddenimports

# ── Analysis ───────────────────────────────────────────────────────────────
a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=added_binaries,
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        '_pytest',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── EXE ───────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,      # use COLLECT (one-folder mode) — much more reliable
    name='Naksha',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # keep UPX off — it breaks many DLLs
    console=False,              # set True during debugging to see error output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='gui/icons/logo.png',  # optional: use an .ico file for best results
)

# ── COLLECT (one-folder bundle — all DLLs alongside the .exe) ─────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Naksha',
)
