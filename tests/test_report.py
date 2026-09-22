import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from tv_scan_studio.report import export_project_pdf


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
