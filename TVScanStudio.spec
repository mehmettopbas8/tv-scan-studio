# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ["run_tv_scan_studio.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "websocket"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
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
