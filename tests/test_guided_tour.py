import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
from tv_scan_studio.guided_tour import unobstructed_tour_position
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_narrow_dialog_tour_moves_outside_without_covering_target():
    window = QtCore.QRect(500, 220, 200, 340)
    target = QtCore.QRect(510, 275, 180, 30)
    size = QtCore.QSize(240, 200)
    screen = QtCore.QRect(0, 0, 1240, 810)
    point = unobstructed_tour_position(target, size, window, screen)
    popup = QtCore.QRect(point, size)
    assert screen.contains(popup)
    assert not popup.intersects(target.adjusted(-3, -3, 3, 3))


def test_large_list_tour_does_not_cover_list_when_dialog_space_is_insufficient():
    window = QtCore.QRect(350, 180, 500, 410)
    target = QtCore.QRect(365, 350, 470, 160)
    size = QtCore.QSize(360, 220)
    screen = QtCore.QRect(0, 0, 1240, 810)
    popup = QtCore.QRect(unobstructed_tour_position(target, size, window, screen), size)
    assert screen.contains(popup)
    assert not popup.intersects(target.adjusted(-3, -3, 3, 3))


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
