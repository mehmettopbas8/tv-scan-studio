import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from tv_scan_studio.report import _metric_text, export_project_pdf, export_research_pdf
from tv_scan_studio.research import load_catalog


def test_pdf_metric_precision_fits_result_columns():
    assert _metric_text(0.718966758368993, 3) == "0.719"
    assert _metric_text(33.3333333333333, 1) == "33.3"
    assert _metric_text(7.12480464389827, 2) == "7.12"
    assert _metric_text(-5036.2000000015, 2) == "-5036.20"
    assert _metric_text(float("nan"), 2) == "—"


def test_pdf_report_is_created(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    path = tmp_path / "report.pdf"
    count = export_project_pdf(
        {"name": "Türkçe Strateji", "pine_hash": "abc", "settings": {"timeframe": "15"}},
        [{"task_key": "1234567890abcdef", "classification": "dayanıklı", "verified": True,
          "payload": {"symbol": "OANDA:EURUSD", "timeframe": "15"},
          "metrics": {"trades": 100, "profit_factor": 1.6, "win_rate_pct": 51,
                      "max_drawdown_pct": 4, "net_profit": 1200}}],
        path,
    )
    assert count == 1
    assert path.read_bytes().startswith(b"%PDF")
    assert path.stat().st_size > 5_000
    del application


def test_pdf_report_never_includes_failed_rows(tmp_path, monkeypatch):
    from tv_scan_studio import report
    captured = []

    class CapturingDocument:
        def __init__(self, *_args, **_kwargs):
            pass

        def build(self, story, **_kwargs):
            captured.extend(story)

    monkeypatch.setattr(report, "SimpleDocTemplate", CapturingDocument)
    path = tmp_path / "successful-only.pdf"
    rows = [
        {"task_key": "success001", "classification": "dayanıklı", "verified": True,
         "payload": {"symbol": "OANDA:EURUSD", "timeframe": "15"},
         "metrics": {"trades": 80, "profit_factor": 1.7}},
        {"task_key": "failed0001", "classification": "geçersiz", "verified": False,
         "payload": {"symbol": "OANDA:EURUSD", "timeframe": "15"},
         "metrics": {"trades": 0, "profit_factor": 0}},
        {"task_key": "unverified", "classification": "dayanıklı", "verified": False,
         "payload": {"symbol": "OANDA:EURUSD", "timeframe": "15"},
         "metrics": {"trades": 80, "profit_factor": 1.8}},
    ]
    assert export_project_pdf({"name": "Test", "settings": {}}, rows, path) == 1
    from reportlab.platypus import Table
    tables = [item for item in captured if isinstance(item, Table)]
    cells = tables[-1]._cellvalues
    content = "\n".join(getattr(cell, "text", "") for row in cells for cell in row)
    assert "success001" in content
    assert "failed0001" not in content
    assert "unverified" not in content
    assert "geçersiz" not in content


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "src/tv_scan_studio/data/ftmo_session_20260923.json").is_file(),
    reason="Optional private research catalog is not bundled",
)
def test_research_pdf_renders_all_seven_source_presets(tmp_path):
    path = tmp_path / "research.pdf"
    assert export_research_pdf(load_catalog(), path) == 7
    assert path.read_bytes().startswith(b"%PDF")
    assert path.stat().st_size > 20_000
