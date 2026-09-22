import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from tv_scan_studio.app import StudioWindow
from tv_scan_studio.storage import Store


def test_app_builds_operational_controls_and_cost_mapping(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "studio.db"))
    studio.project_name.setText("Smoke")
    studio.pine_source.setPlainText(
        '//@version=6\nstrategy("Smoke")\nlength = input.int(20, "Length")'
    )
    studio.save_project()
    studio.refresh_project_selectors()

    plan = studio._current_plan()
    assert plan.costs["tradingview_inputs"] == {}
    assert plan.costs["assumptions"]["initial_capital"] == 100000

    studio.commission_input_id.setText("in_7")
    studio.commission.setValue(0.125)
    assert studio._current_plan().costs["tradingview_inputs"] == {"in_7": 0.125}
    assert studio.pages.count() == 6
    studio.worker_timer.stop()
    studio.window.close()
    del application
