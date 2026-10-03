"""Prevent a second desktop process from recovering a live process's tasks."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def desktop_instance(name: str = "Local\\TVScanStudioDesktop") -> Iterator[bool]:
    """Hold a session-scoped Windows mutex for the lifetime of the desktop UI."""
    if os.name != "nt":  # pragma: no cover - Windows desktop is the supported target
        yield True
        return

    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise OSError(ctypes.get_last_error(), "Uygulama tek örnek kilidi oluşturulamadı")
    acquired = ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    try:
        yield acquired
    finally:
        kernel32.CloseHandle(handle)
