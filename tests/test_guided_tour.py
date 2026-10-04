import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_tour_anchors_gates_actions_and_can_reopen(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "tour.db")
    studio = StudioWindow(store)
    studio.window.resize(1024, 768)
    studio.window.show()
    application.processEvents()
    try:
        studio.start_guided_tour("strategies")
        tour = studio.guided_tour
        assert tour.isVisible()
        assert tour.highlight.isVisible()
        tour.next.click()
        assert tour.index == 1
        assert not tour.next.isEnabled()
        assert not studio.pine_source.toPlainText()
        studio.pine_source.setPlainText('strategy("Test")')
        tour.update_anchor()
        assert tour.next.isEnabled()
        tour.next.click()
        assert tour.index == 2
        tour.back.click()
        assert tour.index == 1
        assert tour.geometry().right() <= studio.window.frameGeometry().right()
        tour.skip.click()
        assert studio.guided_tour is None
        assert store.app_settings()["guided_tour_strategies_v1"] is True
        studio.start_guided_tour("strategies", automatic=True)
        assert studio.guided_tour is None
        studio.usage_help["strategies"][1].click()
        assert studio.guided_tour is not None
        studio.guided_tour.finish()
        assert not store.projects()
    finally:
        studio.window.close()


def test_scan_selection_advances_without_starting_a_scan(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "scan-tour.db")
    store.create_project("Test", 'strategy("Test")\nn=input.int(8,"Fast EMA")')
    studio = StudioWindow(store)
    studio.window.show()
    studio._show_page(2)
    application.processEvents()
    try:
        studio.start_guided_tour("scan")
        tour = studio.guided_tour
        tour.next.click()
        assert tour.index == 1
        assert not tour.next.isEnabled()
        studio.symbols.setText("BIST:XU030D1!")
        tour.update_anchor()
        assert tour.index == 2
        studio.timeframes.setText("15 dakika")
        tour.update_anchor()
        assert tour.index == 3
        tour.skip.click()
        assert studio.guided_tour is None
        assert store.app_settings()["guided_tour_scan_v1"] is True
    finally:
        studio.window.close()
