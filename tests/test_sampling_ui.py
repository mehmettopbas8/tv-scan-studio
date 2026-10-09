import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets
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


def test_sampling_first_use_requires_selected_sampling_and_remains_reopenable(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / 'sampling-tour.db')
    # Skip unrelated page introductions; sampling itself is deliberately new.
    store.save_app_settings({'guided_tour_strategies_v1': True, 'guided_tour_scan_v1': True,
                             'help_tour_strategies_completed': True, 'help_tour_scan_completed': True})
    studio = StudioWindow(store)
    studio.worker_timer.stop()
    registry = studio.help_registry
    focus = QtCore.QEvent(QtCore.QEvent.FocusIn)
    try:
        studio.window.show()
        studio.pages.setCurrentIndex(2)
        # Advanced fields must be visible, but merely focusing their default
        # method is not opting into the sampling feature.
        studio.scan_method.parentWidget().show()
        studio.scan_method.show()
        app.processEvents()
        if registry.active_tour:
            registry.active_tour.finish()
        app.sendEvent(studio.scan_method, focus)
        app.processEvents()
        assert studio.scan_method.currentData() == 'cartesian'
        assert registry.active_tour is None
        studio.scan_method.setCurrentIndex(studio.scan_method.findData('sample'))
        assert registry.active_tour is not None
        assert registry.active_tour.steps[0][0] is studio.scan_method
        registry.active_tour.skip.click()
        app.sendEvent(studio.sample_budget, focus)
        app.processEvents()
        assert registry.active_tour is None  # completion remains persistent
        studio.scan_method.setCurrentIndex(studio.scan_method.findData('cartesian'))
        registry.show_help('sampling.method')
        reopen = next(button for button in registry.dialog.findChildren(QtWidgets.QPushButton)
                      if 'Rehberi' in button.text())
        reopen.click()
        assert registry.active_tour is not None
        registry.active_tour.finish()
        with store.connect() as connection:
            assert connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0] == 0
    finally:
        studio.window.close()
        app.processEvents()
