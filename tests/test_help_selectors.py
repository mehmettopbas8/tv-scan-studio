import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


@pytest.mark.parametrize("method,key", [
    ("choose_symbols", "symbols"), ("choose_timeframes", "timeframes"), ("choose_dates", "dates"),
])
def test_selector_help_is_scoped_read_only_reopenable_and_cancel_preserves_plan(tmp_path, monkeypatch, method, key):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "selection.db")
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    studio.symbols.setText("BIST:XU030D1!")
    studio.timeframes.setText("15 dakika")
    studio.date_from.setText("2025-01-01")
    studio.date_to.setText("2025-12-31")
    fields = (studio.symbols, studio.timeframes, studio.date_from, studio.date_to)
    original = tuple(field.text() for field in fields)
    scopes = []
    def inspect(dialog):
        dialog.show()
        app.processEvents()
        scope = dialog.help_registry
        scopes.append(scope)
        assert not scope.missing_controls(dialog)
        assert scope.active_tour is not None and scope.active_tour.window is dialog
        scope.active_tour.skip.click()
        assert store.app_settings()[f"help_tour_selection.{key}_completed"]
        guide = scope.specs[f"selection.{key}.guide"].target
        guide.click()
        assert scope.active_tour is not None
        scope.active_tour.skip.click()
        scope.show_help(f"selection.{key}.apply")
        assert scope.dialog is not None
        scope.dialog.close()
        assert tuple(field.text() for field in fields) == original
        for date in dialog.findChildren(QtWidgets.QDateEdit):
            before = date.date()
            position = QtCore.QPointF(5, 5)
            wheel = QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, 120),
                                     QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
                                     QtCore.Qt.NoScrollPhase, False)
            app.sendEvent(date, wheel)
            assert date.date() == before
            date.setDate(QtCore.QDate(2020, 1, 1))
        for check in dialog.findChildren(QtWidgets.QCheckBox):
            check.setChecked(not check.isChecked())
        for listing in dialog.findChildren(QtWidgets.QListWidget):
            if listing.count():
                listing.item(0).setCheckState(QtCore.Qt.Checked)
        scope.start_tour(f"selection.{key}")
        tour = scope.active_tour
        dialog.reject()
        assert scope.active_tour is None and not tour.timer.isActive()
        return QtWidgets.QDialog.Rejected
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        getattr(studio, method)()
        assert tuple(field.text() for field in fields) == original
        assert not store.projects() and studio.supervisor is None
        assert len(scopes) == 1
    finally:
        studio.window.close()
        app.processEvents()


@pytest.mark.parametrize("method,key", [
    ("choose_symbols", "symbols"), ("choose_timeframes", "timeframes"), ("choose_dates", "dates"),
])
def test_selector_apply_only_updates_its_plan_fields(tmp_path, monkeypatch, method, key):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "selection.db")
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    studio.symbols.setText("BIST:XU030D1!")
    def apply(dialog):
        scope = dialog.help_registry
        if key == "symbols":
            listing = scope.specs["selection.symbols.list"].target
            for index in range(listing.count()):
                item = listing.item(index)
                item.setCheckState(QtCore.Qt.Checked if item.data(QtCore.Qt.UserRole) == "BIST:XU030D1!" else QtCore.Qt.Unchecked)
        elif key == "timeframes":
            for code in ("1", "5", "15", "30", "60", "240", "1D"):
                scope.specs[f"selection.timeframes.{code}"].target.setChecked(code == "15")
        else:
            scope.specs["selection.dates.start"].target.setDate(QtCore.QDate(2025, 1, 1))
            scope.specs["selection.dates.stop"].target.setDate(QtCore.QDate(2025, 12, 31))
        dialog.accept()
        return QtWidgets.QDialog.Accepted
    monkeypatch.setattr(QtWidgets.QDialog, "exec", apply)
    try:
        getattr(studio, method)()
        if key == "symbols":
            assert studio.symbols.text() == "BIST:XU030D1!"
        elif key == "timeframes":
            assert studio.timeframes.text() == "15 dakika"
        else:
            assert studio.date_from.text() == "2025-01-01"
            assert studio.date_to.text() == "2025-12-31"
        assert not store.projects() and studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()


@pytest.mark.parametrize("declaration,key", [
    ('n=input.int(8,"Fast EMA",minval=1,maxval=100)', "input_range"),
    ('n=input.bool(true,"Enabled")', "input_options"),
])
def test_value_editor_tour_and_cancel_preserve_candidates(tmp_path, monkeypatch, declaration, key):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "editor.db")
    store.create_project("Demo", 'strategy("Demo")\n' + declaration)
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    studio.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
    cell = studio.plan_inputs.item(0, 4)
    original = (cell.text(), cell.data(QtCore.Qt.UserRole))
    def inspect(dialog):
        dialog.show()
        app.processEvents()
        scope = dialog.help_registry
        assert not scope.missing_controls(dialog)
        assert scope.active_tour is not None
        scope.active_tour.skip.click()
        scope.start_tour("selection." + key)
        tour = scope.active_tour
        for spin in dialog.findChildren(QtWidgets.QSpinBox):
            previous = spin.value()
            position = QtCore.QPointF(5, 5)
            app.sendEvent(spin, QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, 120),
                                                QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
                                                QtCore.Qt.NoScrollPhase, False))
            assert spin.value() == previous
        dialog.reject()
        assert not tour.timer.isActive() and scope.active_tour is None
        return QtWidgets.QDialog.Rejected
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    try:
        studio.edit_scan_values(cell)
        assert (cell.text(), cell.data(QtCore.Qt.UserRole)) == original
        assert studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()


@pytest.mark.parametrize("start,stop,expected", [(7, 9, [7, 8, 9]), (0, 2, None)])
def test_numeric_editor_validates_code_bounds_before_replacing_values(tmp_path, monkeypatch, start, stop, expected):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "editor.db")
    store.create_project("Demo", 'strategy("Demo")\nn=input.int(8,"Fast EMA",minval=1,maxval=100)')
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    studio.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
    cell = studio.plan_inputs.item(0, 4)
    previous = cell.data(QtCore.Qt.UserRole)
    def apply(dialog):
        scope = dialog.help_registry
        scope.specs["selection.input_range.start"].target.setValue(start)
        scope.specs["selection.input_range.stop"].target.setValue(stop)
        scope.specs["selection.input_range.step"].target.setValue(1)
        dialog.accept()
        return QtWidgets.QDialog.Accepted
    monkeypatch.setattr(QtWidgets.QDialog, "exec", apply)
    try:
        studio.edit_scan_values(cell)
        assert cell.data(QtCore.Qt.UserRole) == (previous if expected is None else expected)
        if expected is None:
            assert "en küçük değer" in studio.plan_status.text()
        assert studio.supervisor is None
    finally:
        studio.window.close()
        app.processEvents()
