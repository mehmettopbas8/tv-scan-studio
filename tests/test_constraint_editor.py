import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.constraint_editor import ConstraintEditor
from tv_scan_studio.help_system import HelpRegistry
from tv_scan_studio.pine import PineInput


def test_editor_relations_help_and_no_business_actions():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(window)
    editor = ConstraintEditor()
    layout.addWidget(editor)
    registry = HelpRegistry(window)
    editor.register_help(registry)
    editor.load({"in_0": PineInput("fast", "int", 8, "Fast EMA"),
                 "in_1": PineInput("slow", "int", 21, "Slow EMA")}, [])
    assert editor.add.isEnabled()
    editor.add.click()
    assert editor.rules == [{"left": "in_0", "operator": "<", "right": "in_1"}]
    assert editor.listing.item(0).text() == "Fast EMA < Slow EMA"
    editor.add.click()
    assert len(editor.rules) == 1
    window.show()
    app.processEvents()
    tour = registry.start_tour("constraints")
    while not tour.ended:
        tour.next.click()
    assert len(editor.rules) == 1
    assert not registry.missing_controls(window)
    editor.listing.setCurrentRow(0)
    editor.remove.click()
    assert editor.rules == []
    editor.right.setCurrentIndex(0)
    assert not editor.add.isEnabled()
    assert "İki farklı" in registry.specs["constraints.add"].text()
    window.close()


def test_saved_rules_load_into_plan_and_counts(tmp_path):
    from tv_scan_studio.app import StudioWindow
    from tv_scan_studio.storage import Store
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "rules.db")
    project = store.create_project("EMA", 'strategy("EMA")\nfast = input.int(8, "Fast EMA")\nslow = input.int(9, "Slow EMA")')
    rules = [{"left": "in_0", "operator": "<", "right": "in_1"}]
    store.save_settings(project, {"symbols": ["BIST:XU030D1!"], "timeframes": ["15"],
        "input_values": {"in_0": [7, 8, 9], "in_1": [8, 9]}, "constraints": rules,
        "input_ui": {"in_0": {"decision": "Tara", "values": [7, 8, 9]},
                     "in_1": {"decision": "Tara", "values": [8, 9]}}})
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    try:
        plan = studio._current_plan()
        assert plan.constraints == rules
        assert plan.task_count == 3
        assert "Atlanan: 3" in studio.constraint_editor.status.text()
        assert not store.tasks(project)
    finally:
        studio.window.close()
        app.processEvents()
