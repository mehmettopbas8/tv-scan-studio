import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store
from tv_scan_studio.text_prompt import PROMPTS


@pytest.fixture
def studio(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "prompts.db")
    store.create_project("Demo", 'strategy("Demo")\ns=input.string("first","Mode")')
    window = StudioWindow(store)
    window.worker_timer.stop()
    yield window
    window.window.close()
    app.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


@pytest.mark.parametrize("key", list(PROMPTS))
@pytest.mark.parametrize("accepted", [False, True])
def test_text_prompt_help_is_readonly_and_cleans_up(studio, monkeypatch, key, accepted):
    app = QtWidgets.QApplication.instance()
    store = studio.store
    project = studio.plan_project.currentData()
    before = (store.projects(), store.tasks(project), store.settings(project), store.saved_presets())
    feature = "text." + key

    def inspect(dialog):
        dialog.show()
        app.processEvents()
        scope = dialog.help_registry
        assert not scope.missing_controls(dialog)
        assert scope.active_tour is not None
        field = scope.specs[feature + ".value"].target
        assert field.text() == "original"
        assert before == (store.projects(), store.tasks(project), store.settings(project), store.saved_presets())
        scope.active_tour.skip.click()
        assert store.app_settings()[f"help_tour_{feature}_completed"]
        scope.specs[feature + ".guide"].target.click()
        assert field.text() == "original"
        scope.active_tour.skip.click()
        scope.show_help(feature + ".apply")
        assert scope.dialog is not None
        scope.dialog.close()
        field.setText("replacement")
        scope.start_tour(feature)
        tour = scope.active_tour
        scope.specs[feature + (".apply" if accepted else ".cancel")].target.click()
        assert scope.active_tour is None
        assert not tour.timer.isActive()
        return dialog.result()

    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    assert studio._ask_text_with_help(key, text="original") == ("replacement", accepted)
    assert before == (store.projects(), store.tasks(project), store.settings(project), store.saved_presets())
    assert studio.supervisor is None


@pytest.mark.parametrize("operation,key", [
    ("save_local_preset", "preset_name"),
    ("save_cost_template", "cost_name"),
    ("save_result_filter", "filter_name"),
    ("validate_selected_results", "provider_symbol"),
    ("edit_scan_values", "input_values"),
])
def test_caller_cancellation_preserves_business_state(studio, monkeypatch, operation, key):
    project = studio.plan_project.currentData()
    studio.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
    cell = studio.plan_inputs.item(0, 4)
    before = (studio.store.tasks(project), studio.store.settings(project),
              studio.store.app_settings(), dict(studio.cost_templates),
              cell.text(), cell.data(QtCore.Qt.UserRole))
    calls = []
    def cancelled(prompt_key, **kwargs):
        calls.append(prompt_key)
        return "modified but cancelled", False
    monkeypatch.setattr(studio, "_ask_text_with_help", cancelled)
    monkeypatch.setattr(studio, "selected_result_rows", lambda: [{"verified": True}])
    if operation == "save_local_preset":
        studio.save_local_preset(-1)
    elif operation == "edit_scan_values":
        studio.edit_scan_values(cell)
    else:
        getattr(studio, operation)()
    assert calls == [key]
    assert before == (studio.store.tasks(project), studio.store.settings(project),
                      studio.store.app_settings(), dict(studio.cost_templates),
                      cell.text(), cell.data(QtCore.Qt.UserRole))
    assert not studio.store.saved_presets()
    assert studio.supervisor is None


@pytest.mark.parametrize("accepted", [False, True])
def test_real_text_editor_confirmation_changes_only_candidates(studio, monkeypatch, accepted):
    studio.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
    cell = studio.plan_inputs.item(0, 4)
    original = cell.data(QtCore.Qt.UserRole)
    def inspect(dialog):
        scope = dialog.help_registry
        scope.specs["text.input_values.value"].target.setText("one, , two")
        scope.specs["text.input_values" + (".apply" if accepted else ".cancel")].target.click()
        return dialog.result()
    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect)
    studio.edit_scan_values(cell)
    assert cell.data(QtCore.Qt.UserRole) == (["one", "two"] if accepted else original)
    assert not studio.store.tasks(studio.plan_project.currentData())
    assert studio.supervisor is None


@pytest.mark.parametrize("method,key", [
    ("save_cost_template", "cost_name"), ("save_result_filter", "filter_name"),
])
def test_real_prompt_confirmation_saves_and_updates_named_record(studio, monkeypatch, method, key):
    project = studio.plan_project.currentData()
    def confirm(dialog):
        scope = dialog.help_registry
        scope.specs[f"text.{key}.value"].target.setText("  Saved definition  ")
        scope.specs[f"text.{key}.apply"].target.click()
        return dialog.result()
    monkeypatch.setattr(QtWidgets.QDialog, "exec", confirm)
    for value in (2, 3):
        if key == "cost_name":
            studio.commission.setValue(value)
        else:
            studio.filter_pf.setValue(value)
        getattr(studio, method)()
        if key == "cost_name":
            saved = studio.store.app_settings()["cost_templates"]
            assert saved["Saved definition"]["commission_value"] == value
            assert studio.cost_scenario.currentText() == "Saved definition"
        else:
            saved = studio.store.settings(project)["result_filters"]
            assert saved["Saved definition"]["min_pf"] == value
            assert studio.saved_result_filter.currentText() == "Saved definition"
        assert list(saved).count("Saved definition") == 1
    assert not studio.store.tasks(project)
    assert studio.supervisor is None


@pytest.mark.parametrize("key", list(PROMPTS))
def test_native_modal_event_loop_closes_prompt_and_guide(studio, monkeypatch, key):
    native_exec = QtWidgets.QDialog.exec
    checks = []
    def execute(dialog):
        def close_after_open():
            scope = dialog.help_registry
            checks.append(scope.active_tour is not None)
            checks.append(not scope.missing_controls(dialog))
            scope.specs[f"text.{key}.cancel"].target.click()
            checks.append(scope.active_tour is None)
        QtCore.QTimer.singleShot(30, dialog, close_after_open)
        return native_exec(dialog)
    monkeypatch.setattr(QtWidgets.QDialog, "exec", execute)
    assert studio._ask_text_with_help(key, text="unchanged") == ("unchanged", False)
    assert checks == [True, True, True]
