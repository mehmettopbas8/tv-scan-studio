import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


@pytest.mark.parametrize("feature,attribute,count", [
    ("strategy.inputs", "input_table", 9),
    ("results.events", "events_table", 5),
])
def test_read_only_tables_have_explicit_help_for_every_column(tmp_path, feature, attribute, count):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "help.db"))
    studio.worker_timer.stop()
    registry = studio.help_registry
    table = getattr(studio, attribute)
    try:
        assert registry.resolve(table).feature_id == feature
        assert table not in registry.missing_controls()
        assert table.editTriggers() == QtWidgets.QAbstractItemView.NoEditTriggers
        header = table.horizontalHeader()
        for index in range(count):
            spec = registry.specs[f"{feature}.column.{index}"]
            assert registry._column_specs[header, index] is spec
            assert table.horizontalHeaderItem(index).toolTip() == spec.tooltip
            assert "salt okunur" in spec.detail
        header.setSectionsMovable(True)
        header.moveSection(0, count - 1)
        assert registry._column_specs[header, 0].feature_id == feature + ".column.0"
        registry.show_help(feature)
        assert registry.dialog.windowTitle() == registry.specs[feature].title
        registry.dialog.close()
        assert not studio.store.projects()
        assert studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()


@pytest.mark.parametrize("feature,attribute,page", [
    ("strategy.inputs", "input_table", 1),
    ("results.events", "events_table", 4),
])
def test_table_guides_persist_and_reopen_without_business_actions(tmp_path, feature, attribute, page):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "help.db")
    store.save_app_settings({"guided_tour_strategies_v1": True, "guided_tour_results_v1": True})
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    studio._show_page(page)
    table = getattr(studio, attribute)
    # Events are hidden for an empty store; expose only the read-only test target.
    table.show()
    studio.window.show()
    registry = studio.help_registry
    columns_hidden = [table.isColumnHidden(index) for index in range(table.columnCount())]
    try:
        app.sendEvent(table, QtCore.QEvent(QtCore.QEvent.FocusIn))
        app.processEvents()
        tour = registry.active_tour
        assert tour is not None and tour.steps[0][0] is table
        tour.next.click()
        assert tour.ended and not tour.timer.isActive()
        assert store.app_settings()["help_tour_" + feature + "_completed"]
        app.sendEvent(table, QtCore.QEvent(QtCore.QEvent.FocusIn))
        app.processEvents()
        assert registry.active_tour is None
        registry.show_help(feature)
        next(button for button in registry.dialog.findChildren(QtWidgets.QPushButton)
             if "Rehberi" in button.text()).click()
        assert registry.active_tour.steps[0][0] is table
        registry.active_tour.skip.click()
        assert registry.active_tour is None
        assert columns_hidden == [table.isColumnHidden(index) for index in range(table.columnCount())]
        assert table.rowCount() == 0
        assert not store.projects() and studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()


def test_source_status_and_result_guide_explain_verification_boundary(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "help.db"))
    studio.worker_timer.stop()
    try:
        registry = studio.help_registry
        assert "canlı grafik" in registry.specs["strategy.status"].detail
        assert "başlangıç değeri" in registry.specs["strategy.inputs.column.3"].detail
        assert "son 100" in registry.specs["results.events"].detail
        assert registry.resolve(studio.results_help_button).feature_id == "results.guide"
        assert registry.resolve(studio.results_help_dismiss).feature_id == "results.guide_close"
    finally:
        studio.window.close()
        app.processEvents()
