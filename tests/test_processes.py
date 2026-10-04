from subprocess import CompletedProcess
import os
import pytest
from tv_scan_studio import processes


def test_external_helper_uses_isolation_context(monkeypatch):
    from contextlib import contextmanager
    events = []
    @contextmanager
    def isolated():
        events.append("isolate")
        try:
            yield
        finally:
            events.append("restore")
    monkeypatch.setattr(processes, "external_dll_search", isolated)
    monkeypatch.setattr(processes.subprocess, "run", lambda *a, **k:
        (events.append("spawn") or CompletedProcess(a, 0)))
    assert processes.run_hidden(["helper"]).returncode == 0
    assert events == ["isolate", "spawn", "restore"]


@pytest.mark.skipif(os.name != "nt", reason="Windows loader status")
@pytest.mark.parametrize("status", [0xc0000142, -1073741502])
def test_loader_failure_is_actionable_not_empty_success(monkeypatch, status):
    monkeypatch.setattr(processes.subprocess, "run", lambda *a, **k: CompletedProcess(a, status, "", ""))
    with pytest.raises(processes.HelperStartupError, match="0xc0000142") as error:
        processes.run_hidden(["helper"], check=False)
    assert error.value.status == 0xc0000142


@pytest.mark.skipif(os.name != "nt", reason="Windows process error mode")
def test_helper_error_mode_preserves_and_restores_process_flags_on_exception():
    import ctypes
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetErrorMode.restype = ctypes.c_uint32
    before = kernel.GetErrorMode()
    with pytest.raises(RuntimeError):
        with processes.helper_error_mode():
            assert kernel.GetErrorMode() == before | 1
            raise RuntimeError("spawn failed")
    assert kernel.GetErrorMode() == before
