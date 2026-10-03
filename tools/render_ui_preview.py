"""Render the research page offscreen without opening TradingView."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui, QtWidgets

from tv_scan_studio.app import STYLE, StudioWindow
from tv_scan_studio.storage import Store


def main() -> None:
    page = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 1440
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 900
    names = {0: "dashboard", 1: "project", 2: "scan", 3: "workers",
             4: "results", 5: "research", 6: "settings"}
    ict = "--ict" in sys.argv
    demo_results = "--demo-results" in sys.argv
    demo_workers = "--demo-workers" in sys.argv
    detail = "--detail" in sys.argv
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeuib.ttf")
    app.setStyleSheet(STYLE)
    store = Store(Path("tmp/ui-review/workers-demo.db" if demo_workers else
                       "tmp/ui-review/results-demo-v2.db" if demo_results else
                       "tmp/ui-review/ict-review.db" if ict else "tmp/ui-review/studio.db"))
    if demo_workers and not store.projects():
        store.create_project("ICT FTMO", 'strategy("ICT FTMO")\nlength=input.int(3,"Length")')
    if ict and not store.projects():
        source = (Path(__file__).resolve().parents[2] / "5_Araclar" /
                  "ICT_Uni_tv2mt5_baglantili.pine").read_text(encoding="utf-8")
        store.create_project("ICT FTMO", source)
    if demo_results and not store.projects():
        project_id = store.create_project("Çevrimdışı örnek", 'strategy("Çevrimdışı örnek")')
        for index, (pf, dd, trades) in enumerate(((1.72, 4.1, 82),
                                                   (1.48, 3.4, 93)), 1):
            store.enqueue(project_id, f"demo-{index}", {
                "symbol": "OANDA:DE30EUR", "timeframe": "15", "inputs": {"in_0": index},
                "date_range": {"from": "2025-09-01", "to": "2026-09-22"},
                "costs": {"commission_pct": .04},
            })
            task = store.claim_next(1)
            store.complete(task.id, 1, {
                "trades": trades, "profit_factor": pf, "max_drawdown_pct": dd,
                "win_rate_pct": 44.0, "net_profit": 10500,
                "equity_curve": [
                    {"time": 1_700_000_000_000 + day * 86_400_000,
                     "equity": 100000 + day * 95 + ((day % 7) - 3) * 300,
                     "drawdown": (day % 5) * 100}
                    for day in range(30)],
                "daily_pnl": {"2026-09-01": 100, "2026-09-02": -45},
                "hourly_pnl": {"09:00": 300, "10:00": -120},
                "weekday_pnl": {"Monday": 300, "Tuesday": -120},
                "session_pnl": {"NYAM": 300, "LONDON": -120},
            }, "hassas", verified=True)
    window = StudioWindow(store)
    window.window.resize(width, height)
    window.window.show()
    window._show_page(page)
    if demo_workers and page == 3:
        from tv_scan_studio import app as app_module

        class DemoDriver:
            def __init__(self, *_args):
                pass
            def inventory(self):
                return [
                    {"target_id": "live-demo", "error": "", "strategies": [
                        {"id": "study-live", "name": "ICT FTMO", "input_ids": ["in_0"],
                         "pine_id": "USER;demo", "status": {"type": 2}}]},
                    {"target_id": "new-demo", "error": "", "strategies": [
                        {"id": "study-new", "name": "ICT FTMO", "input_ids": ["in_0"],
                         "pine_id": "USER;demo", "status": {"type": 2}}]},
                ]

        app_module.GncZihinDriver = DemoDriver
        window._safe_worker_targets.add("new-demo")
        window.discover_targets()
    if ict and page == 2:
        window.symbols.setText("OANDA:DE30EUR")
        window.timeframes.setText("15")
        if "--scan-first-input" in sys.argv and window.plan_inputs.rowCount():
            window.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
    if "--cost-open" in sys.argv and page == 2:
        window.advanced_cost_toggle.setChecked(True)
    if detail and page == 4 and window._result_rows:
        window.open_result_details_by_id(window._result_rows[0]["task_id"])
        if "--detail-expanded" in sys.argv:
            window.result_detail_expand.click()
    if "--filters-open" in sys.argv and page == 4:
        window.filter_pf.setValue(1.5)
        window.filter_dd.setValue(5)
        window.filter_symbol.setText("DE30")
        window.result_filter_panel.show()
    if "--chart-focus" in sys.argv and page == 4:
        window.result_scatter.setFocus()
    app.processEvents()
    scale = os.environ.get("QT_SCALE_FACTOR", "1").replace(".", "p")
    destination = Path(f"tmp/ui-review/{names[page]}-{width}x{height}"
                       f"{'-ict' if ict else '-demo' if demo_results else '-workers' if demo_workers else ''}"
                       f"{'-scope' if '--scope-open' in sys.argv else ''}"
                       f"{'-filters' if '--filters-open' in sys.argv else ''}"
                       f"{'-chart-focus' if '--chart-focus' in sys.argv else ''}"
                       f"{'-scan-first-input' if '--scan-first-input' in sys.argv else ''}"
                       f"{'-detail-expanded' if '--detail-expanded' in sys.argv else '-detail' if detail else ''}"
                       f"-scale-{scale}.png")
    capture = window.result_detail_dock if "--detail-expanded" in sys.argv else window.window
    if not capture.grab().save(str(destination)):
        raise RuntimeError("UI önizlemesi kaydedilemedi.")
    window.worker_timer.stop()
    window.window.close()
    print(destination.resolve())
    print("rendered", window.window.size().width(), window.window.size().height())
    print("page minimums", [(index, window.pages.widget(index).minimumSizeHint().width(),
                             window.pages.widget(index).minimumSizeHint().height())
                            for index in range(window.pages.count())])


if __name__ == "__main__":
    main()
