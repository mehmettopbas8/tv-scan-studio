"""Opt-in pytest diagnostics for abrupt native exits; never imports product code."""
import ctypes
import os
import sys

from PySide6 import QtCore, QtWidgets

_previous_handler = None


def _message(kind, context, message):
    print(f"QT_PROBE_MESSAGE {kind}: {message}", file=sys.stderr, flush=True)
    if _previous_handler is not None:
        _previous_handler(kind, context, message)


def pytest_configure(config):
    global _previous_handler
    _previous_handler = QtCore.qInstallMessageHandler(_message)


def pytest_unconfigure(config):
    QtCore.qInstallMessageHandler(_previous_handler)


def pytest_runtest_setup(item):
    app = QtWidgets.QApplication.instance()
    widgets = len(app.allWidgets()) if app is not None else 0
    windows = len(app.topLevelWidgets()) if app is not None else 0
    user = gdi = None
    if os.name == 'nt':
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        get_resources = ctypes.windll.user32.GetGuiResources
        get_resources.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        get_resources.restype = ctypes.c_uint32
        handle = kernel.GetCurrentProcess()
        gdi, user = get_resources(handle, 0), get_resources(handle, 1)
    print(f"QT_PROBE {item.nodeid} widgets={widgets} windows={windows} user={user} gdi={gdi}", flush=True)
