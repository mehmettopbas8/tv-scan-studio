import os
import sys

from tv_scan_studio import app


def test_packaged_self_test_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["tv-scan-studio", "--self-test"])
    assert app.main() == 0
    assert (tmp_path / "TVScanStudio" / "studio.db").is_file()
    assert (tmp_path / "TVScanStudio" / "portable-self-test.pdf").is_file()
