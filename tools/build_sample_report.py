"""Build a deterministic PDF used for release visual QA."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from tv_scan_studio.report import export_project_pdf


app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
destination = Path("output/pdf/tv-scan-studio-sample-report.pdf")
project = {
    "name": "FTMO Çoklu Sağlayıcı Tarama",
    "pine_hash": "d7f31b7a" * 8,
    "settings": {"symbols": ["OANDA:DE30EUR", "OANDA:EURUSD"], "timeframes": ["15", "60"]},
}
rows = [
    {"task_key": f"verified-{index:04d}-abcdef", "classification": classification, "verified": True,
     "payload": {"symbol": symbol, "timeframe": timeframe},
     "metrics": {"trades": 75 + index * 4, "profit_factor": round(1.35 + index * .08, 2),
                 "win_rate_pct": 44 + index, "max_drawdown_pct": round(4.8 - index * .25, 2),
                 "net_profit": 980 + index * 145}}
    for index, (classification, symbol, timeframe) in enumerate([
        ("hassas", "OANDA:DE30EUR", "15"), ("dayanıklı", "OANDA:DE30EUR", "15"),
        ("dayanıklı", "OANDA:EURUSD", "60"), ("elenmiş", "OANDA:EURUSD", "15"),
    ])
]
export_project_pdf(project, rows, destination)
print(destination.resolve())
