# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files
from pathlib import Path
import shiboken6

reportlab_data = collect_data_files("reportlab", includes=["fonts/*.ttf"])
shiboken_dir = Path(shiboken6.__file__).parent
msvc_runtime = [
    (str(path), ".") for path in shiboken_dir.glob("*.dll")
    if path.name.lower() != "shiboken6.abi3.dll"
]

a = Analysis(
    ["run_tv_scan_studio.py"],
    pathex=["src"],
    binaries=msvc_runtime,
    datas=reportlab_data,
    hiddenimports=["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "websocket"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
a.binaries = [
    entry for entry in a.binaries
    if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}
]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TV-Scan-Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="TV-Scan-Studio",
)
