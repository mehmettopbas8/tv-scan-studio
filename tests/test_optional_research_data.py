"""Core application behavior when private historical research files are omitted."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tv_scan_studio import app, historical, research


def test_missing_optional_research_data_keeps_core_app_usable(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "files", lambda _name: tmp_path)
    monkeypatch.setattr(historical, "files", lambda _name: tmp_path)
    catalog = research.load_catalog()
    assert catalog["available"] is False
    assert catalog["records"] == []
    assert catalog["session_tests"]["planned"] == 0
    assert list(historical.iter_historical_records()) == []
    assert app.ui_smoke_test() == 0
    monkeypatch.setattr(sys, "argv", ["tv-scan-studio", "--self-test"])
    assert app.main() == 0
