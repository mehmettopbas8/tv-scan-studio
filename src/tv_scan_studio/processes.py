"""Launch external Windows helpers without inheriting the frozen DLL directory."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
from contextlib import contextmanager

_launch_lock = threading.RLock()


class HelperStartupError(OSError):
    """A native loader failure, not a successful empty helper response."""

    def __init__(self, status):
        self.status = status & 0xffffffff
        super().__init__(f"Arka plan yardımcı işlemi başlatılamadı (0x{self.status:08x}).")


@contextmanager
def helper_error_mode():
    # Child processes inherit the process error mode. Keep native loader
    # failures in the return-code path instead of a blocking Windows dialog.
    # This is failure containment, not a diagnosis of the original DLL failure.
    with _launch_lock:
        kernel = None
        previous = None
        if os.name == "nt":
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetErrorMode.restype = ctypes.c_uint32
            kernel.SetErrorMode.argtypes = [ctypes.c_uint32]
            kernel.SetErrorMode.restype = ctypes.c_uint32
            previous = kernel.GetErrorMode()
            kernel.SetErrorMode(previous | 0x0001)  # SEM_FAILCRITICALERRORS
        try:
            yield
        finally:
            if kernel is not None:
                kernel.SetErrorMode(previous)


@contextmanager
def external_dll_search():
    # PyInstaller sets a process-wide DLL directory. A system helper must not
    # load the application's bundled DLLs. Restore it even when spawning fails.
    with _launch_lock:
        kernel = None
        previous = None
        if os.name == "nt" and getattr(sys, "frozen", False):
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
            kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
            size = kernel.GetDllDirectoryW(0, None)
            buffer = ctypes.create_unicode_buffer(size + 1)
            kernel.GetDllDirectoryW(len(buffer), buffer)
            previous = buffer.value
            if not kernel.SetDllDirectoryW(None):
                raise OSError(ctypes.get_last_error(), "External helper DLL isolation failed")
        try:
            yield
        finally:
            if kernel is not None:
                if not kernel.SetDllDirectoryW(previous or None):
                    raise OSError(ctypes.get_last_error(), "Application DLL directory restore failed")


def run_hidden(*args, **kwargs):
    if os.name == "nt":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        kwargs.setdefault("startupinfo", startup)
    with helper_error_mode(), external_dll_search():
        result = subprocess.run(*args, **kwargs)
    if os.name == "nt" and (result.returncode & 0xffffffff) >= 0xc0000000:
        raise HelperStartupError(result.returncode)
    return result


def popen_external(*args, **kwargs):
    with external_dll_search():
        return subprocess.Popen(*args, **kwargs)
