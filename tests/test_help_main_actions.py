import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtTest, QtWidgets
import pytest
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_navigation_and_selection_actions_have_explicit_read_only_help(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "help.db")
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    registry = studio.help_registry
    expected = {
        "navigation.settings": studio.settings_navigation_button,
        "strategy.analyze": studio.strategy_analyze_button,
        "strategy.copy": studio.strategy_copy_button,
        "strategy.technical": studio.strategy_technical_toggle,
        "scan.project_search": studio.project_search_button,
        "scan.symbol_select": studio.symbol_select_button,
        "scan.timeframe_select": studio.timeframe_select_button,
        "scan.date_select": studio.date_select_button,
        "scan.discovery": studio.strategy_discovery_button,
        "scan.strategy_choice": studio.strategy_picker,
        "results.filters_open": studio.result_filter_toggle,
        "results.save_filter": studio.result_save_filter_button,
        "results.stop": studio.results_stop_button,
        "results.presets_open": studio.saved_presets_button,
        "results.tasks_open": studio.tasks_backup_button,
        "results.history_open": studio.historical_scans_button,
        "scan.measure_resources": studio.parallel_measure_button,
        "scan.resource_recommendation": studio.parallel_recommendation,
        "scan.preparation_details": studio.preparation_details_button,
        "scan.edit_values": studio.edit_input_button,
        "scan.edit_detail_values": studio.input_detail_edit,
        "scan.preview_update": studio.plan_preview_button,
        **{"navigation." + key: studio.nav_group.button(index)
           for index, key in ((1, "strategies"), (2, "scan"), (4, "results"))},
    }
    try:
        for feature, target in expected.items():
            spec = registry.specs[feature]
            assert spec.target is target
            assert registry.resolve(target) is spec
            assert target.toolTip() == spec.text()
            assert target not in registry.missing_controls()
        for key, (_panel, button, dismiss, _label) in studio.usage_help.items():
            assert registry.resolve(button).feature_id == "guide." + key
            assert registry.resolve(dismiss).feature_id == "guide." + key + ".legacy_close"
        calls = []
        target = studio.nav_group.button(2)
        target.clicked.connect(lambda: calls.append("navigation"))
        studio.window.show()
        QtTest.QTest.keyClick(target, QtCore.Qt.Key_F1)
        assert registry.dialog is not None
        assert registry.dialog.windowTitle() == "Tarama"
        registry.dialog.close()
        assert calls == []
        assert not store.projects()
        assert studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()


@pytest.mark.parametrize("feature,attribute,page", [
    ("strategy.copy", "strategy_copy_button", 1),
    ("strategy.technical", "strategy_technical_toggle", 1),
    ("results.filters_open", "result_filter_toggle", 4),
    ("results.presets_open", "saved_presets_button", 4),
    ("results.tasks_open", "tasks_backup_button", 4),
    ("results.history_open", "historical_scans_button", 4),
    ("scan.measure_resources", "parallel_measure_button", 2),
    ("scan.preparation_details", "preparation_details_button", 2),
])
def test_feature_popup_never_runs_action_and_can_be_reopened(tmp_path, feature, attribute, page):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "help.db")
    store.save_app_settings({"guided_tour_strategies_v1": True, "guided_tour_results_v1": True})
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    studio._show_page(page)
    if attribute == "preparation_details_button":
        studio.scan_advanced.show()
    studio.window.show()
    calls = []
    target = getattr(studio, attribute)
    checked = target.isChecked()
    target.clicked.connect(lambda: calls.append("action"))
    registry = studio.help_registry
    try:
        app.sendEvent(target, QtCore.QEvent(QtCore.QEvent.FocusIn))
        app.processEvents()
        tour = registry.active_tour
        assert tour is not None
        assert tour.steps[0][0] is target
        tour.next.click()
        assert tour.ended and not tour.timer.isActive()
        assert store.app_settings()["help_tour_" + feature + "_completed"]
        registry.show_help(feature)
        next(button for button in registry.dialog.findChildren(QtWidgets.QPushButton)
             if "Rehberi" in button.text()).click()
        reopened = registry.active_tour
        assert reopened is not None
        reopened.skip.click()
        assert registry.active_tour is None
        assert calls == [] and not store.projects()
        assert target.isChecked() == checked
    finally:
        studio.window.close()
        app.processEvents()
