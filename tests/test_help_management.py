import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_management_controls_explain_actual_mutation_scope(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "help.db"))
    studio.worker_timer.stop()
    registry = studio.help_registry
    try:
        for target in (studio.project_table, studio.dashboard_events, studio.project_priority,
                       studio.project_state, *studio.dashboard_project_actions[2:],
                       studio.dashboard_backup_button, studio.restore_backup_button,
                       studio.dashboard_setup_action, *studio.metric_labels.values()):
            assert registry.resolve(target) is not None
            assert target not in registry.missing_controls()
        assert "Yüksek öncelik önce" in registry.specs["management.priority"].detail
        assert registry.resolve(studio.throughput_label).feature_id == "management.speed"
        assert registry.resolve(studio.eta_label).feature_id == "management.eta"
        assert "5 doğrulanmış" in registry.specs["management.speed"].detail
        assert "Çalışan görevler" in registry.specs["management.cancel"].detail
        assert "iptal görevleri de" in registry.specs["management.retry"].detail
        assert "yüzde 100" in registry.specs["management.projects.column.5"].detail
        for feature, table in (("management.projects", studio.project_table),
                               ("management.events", studio.dashboard_events)):
            for index in range(table.columnCount()):
                assert table.horizontalHeaderItem(index).toolTip() == registry.specs[f"{feature}.column.{index}"].tooltip
        calls = []
        studio.dashboard_project_actions[3].clicked.connect(lambda: calls.append("cancel"))
        registry.show_help("management.cancel")
        registry.dialog.close()
        assert calls == [] and not studio.store.projects()
        for feature in ("results.detail_float", "results.detail_close"):
            spec = registry.specs[feature]
            assert spec.target not in registry.missing_controls()
            assert spec.target.toolTip() == spec.tooltip
            registry.show_help(feature)
            registry.dialog.close()
        assert not studio.result_detail_dock.isFloating()
        assert studio.result_detail_dock.isHidden()
    finally:
        studio.window.close()
        app.processEvents()
