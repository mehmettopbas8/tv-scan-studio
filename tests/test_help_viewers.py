import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


@pytest.mark.parametrize("method,feature", [
    ("tasks", "viewer.task_summary"), ("research", "viewer.research_details"),
])
def test_readonly_viewer_has_complete_scoped_help_and_safe_reopening(tmp_path, monkeypatch, method, feature):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "viewer.db")
    project = store.create_project("Demo", 'strategy("Demo")\nn=input.int(8,"Fast EMA")')
    store.enqueue(project, "test-one", {"symbol": "BIST:XU030D1!", "timeframe": "15", "inputs": {"in_0": 8}})
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    before = store.tasks(project)
    inspections = []
    def inspect(dialog):
        dialog.show()
        app.processEvents()
        scope = dialog.help_registry
        inspections.append(scope)
        assert not scope.missing_controls(dialog)
        tour = scope.active_tour
        assert tour is not None and tour.window is dialog
        tour.skip.click()
        assert store.app_settings()[f"help_tour_{feature}_completed"]
        scope.specs[feature + ".guide"].target.click()
        assert scope.active_tour is not None
        scope.active_tour.skip.click()
        if method == "tasks":
            table = scope.specs[feature + ".table"].target
            assert table.rowCount() == 1
            for column in range(table.columnCount()):
                assert table.horizontalHeaderItem(column).toolTip()
            assert "kanıtı değildir" in scope.specs[feature + ".table.column.2"].detail
        else:
            details = scope.specs[feature + ".text"].target
            assert details.isReadOnly()
            assert "yeniden doğrulamaz" in scope.specs[feature + ".text"].detail
        scope.show_help(feature + ".close")
        assert scope.dialog is not None
        scope.dialog.close()
        scope.start_tour(feature)
        tour = scope.active_tour
        dialog.accept()
        assert scope.active_tour is None and not tour.timer.isActive()
        assert store.tasks(project) == before
        return QtWidgets.QDialog.Accepted
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        if method == "tasks":
            studio.open_dashboard_tasks("pending", project)
        else:
            studio.open_research_details()
        assert len(inspections) == 1
        assert studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()


@pytest.mark.parametrize("accepted", [False, True])
def test_project_picker_help_does_not_apply_unconfirmed_selection(tmp_path, monkeypatch, accepted):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "picker.db")
    ids = [store.create_project(name, f'strategy("{name}")\nn=input.int(8,"Fast EMA")')
           for name in ("First", "Second")]
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    original = studio.plan_project.currentData()
    chosen = next(project for project in ids if project != original)
    calls = []
    def inspect(dialog):
        dialog.show()
        app.processEvents()
        scope = dialog.help_registry
        assert not scope.missing_controls(dialog)
        assert scope.active_tour is not None
        scope.active_tour.skip.click()
        scope.specs["selection.projects.search"].target.setText("Second" if chosen == ids[1] else "First")
        listing = scope.specs["selection.projects.list"].target
        assert listing.currentItem().data(QtCore.Qt.UserRole) == chosen
        scope.specs["selection.projects.new"].target.clicked.connect(lambda: calls.append("new"))
        scope.specs["selection.projects.guide"].target.click()
        assert studio.plan_project.currentData() == original
        tour = scope.active_tour
        if accepted:
            dialog.accept()
        else:
            dialog.reject()
        assert not tour.timer.isActive()
        return QtWidgets.QDialog.Accepted if accepted else QtWidgets.QDialog.Rejected
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio.open_project_picker()
        assert studio.plan_project.currentData() == (chosen if accepted else original)
        assert calls == [] and len(store.projects()) == 2
        assert all(not store.tasks(project) for project in ids)
        assert studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()
