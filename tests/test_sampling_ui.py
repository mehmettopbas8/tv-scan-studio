import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store
from tv_scan_studio.planner import iter_tasks


def test_sampling_ui_help_and_plan_budget(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "sample.db")
    store.create_project("EMA", 'strategy("EMA")\nema = input.int(8, "Fast EMA")')
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    try:
        assert studio.scan_method.currentData() == "cartesian"
        assert not studio.sample_budget.isEnabled()
        assert "Tohumlu" in studio.help_registry.specs["sampling.budget"].text()
        studio.symbols.setText("BIST:XU030D1!")
        studio.timeframes.setText("15")
        studio.study_id.setText("study")
        studio.scan_method.setCurrentIndex(1)
        studio.sample_budget.setText("1")
        studio.sample_seed.setText("42")
        plan = studio._current_plan()
        assert plan.method == "sample" and plan.task_count == 1
        assert len(list(iter_tasks(plan))) == 1
        assert "denenmeyen" in studio.plan_status.text()
        studio.sample_budget.setText("0")
        assert not studio.enqueue_plan_button.isEnabled()
        assert not store.tasks(studio.plan_project.currentData())
    finally:
        studio.window.close()
        app.processEvents()
