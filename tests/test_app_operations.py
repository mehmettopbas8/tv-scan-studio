import os
import csv
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from tv_scan_studio.app import (CurveChart, DailyPnlCalendar, MetricBarsChart,
                                ProjectProgressBar, ResultScatterChart, StudioWindow,
                                WORKER_READY_LABEL)
from tv_scan_studio.storage import Store
from tv_scan_studio.supervisor import WorkerAssignment
from tv_scan_studio.tradingview import pine_source_hash


@pytest.mark.parametrize("different_source,changed_build", [(False,False),(True,False),(False,True)])
def test_worker_binding_checks_automatic_saved_source(tmp_path, monkeypatch, different_source, changed_build):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "automatic-source.db")
    source = 'strategy("Identity")\nlength=input.int(3,"Length")'
    project_id = store.create_project("Identity", source)
    studio = StudioWindow(store)
    studio.worker_table.setRowCount(1)
    project_choice = QtWidgets.QComboBox()
    project_choice.addItem("Identity", project_id)
    studio.worker_table.setCellWidget(0, 3, project_choice)
    strategy = {"id":"sid", "pine_id":"USER;one", "name":"Identity",
                "input_ids":["in_0"], "pine_digest":"build", "pine_version":"1.0"}
    strategy_cell = QtWidgets.QTableWidgetItem("Identity")
    strategy_cell.setData(QtCore.Qt.UserRole, strategy)
    studio.worker_table.setItem(0,4,strategy_cell)
    target_cell = QtWidgets.QTableWidgetItem("Worker 1")
    target_cell.setData(QtCore.Qt.UserRole,"target")
    studio.worker_table.setItem(0,2,target_cell)
    studio.worker_table.setCurrentCell(0,4)
    studio._safe_worker_targets = {"target":"layout"}
    studio.driver = SimpleNamespace(
        strategy_source_hash=lambda *_args: pine_source_hash(source + "changed" if different_source else source),
        strategies=lambda _target:[{**strategy,"pine_digest":"changed" if changed_build else "build"}],
    )
    monkeypatch.setattr(studio,"discover_targets",lambda:None)
    def no_manual_override(*_args):
        raise AssertionError("Automatic evidence must not request manual override")
    monkeypatch.setattr(QtWidgets.QMessageBox,"question",no_manual_override)
    studio.bind_selected_strategy()
    identity = (store.settings(project_id) or {}).get("tradingview_identity")
    if different_source or changed_build:
        assert identity is None
        assert "bağlanmadı" in studio.worker_status.text()
    else:
        assert identity["source_verification"] == "editor_saved_source_sha256"
        assert identity["source_sha256"] == pine_source_hash(source)
    studio.window.close()


def test_source_binding_is_disabled_during_active_scan(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "active-source.db")
    studio = StudioWindow(store)
    studio.supervisor = SimpleNamespace(running=True)
    studio.bind_selected_strategy()
    assert "workerları durdurun" in studio.worker_status.text()
    studio.supervisor = None
    studio.window.close()


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
    assert plan.costs["assumptions"]["commission_type"] == "percent"
    assert "risk_value" not in plan.costs["assumptions"]
    assert "risk_mode" not in plan.costs["assumptions"]
    studio.spread.setValue(1.5)
    with pytest.raises(ValueError, match="spread inputunu eşleyin"):
        studio._current_plan()
    studio.spread.setValue(0)
    assert "max_daily_loss_pct" not in plan.criteria
    assert not studio.max_daily_loss.isEnabled()
    studio.ftmo_risk_check.setChecked(True)
    assert studio._current_plan().criteria["max_daily_loss_pct"] == 5
    assert studio.max_daily_loss.isEnabled()
    studio.ftmo_risk_check.setChecked(False)

    studio.commission_input_id.setText("in_7")
    studio.commission.setValue(0.125)
    assert studio._current_plan().costs["tradingview_inputs"] == {"in_7": 0.125}
    assert studio.pages.count() == 7
    assert not studio.start_workers_button.isEnabled()
    if studio._research_catalog.get("available", True):
        assert studio.research_table.rowCount() == 7
        assert studio.research_table.item(0, 8).text() == "Sağlayıcı bekliyor"
    else:
        assert studio.research_table.rowCount() == 0
    studio.worker_timer.stop()
    studio.window.close()
    del application


def test_strategy_risk_is_scanned_through_pine_input_not_cost_template(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "risk-input.db")
    store.create_project("Risk", 'strategy("Risk")\n'
                         'daily_risk_pct=input.float(2.0,"Daily Risk Budget",step=0.1)\n'
                         'qty=100/daily_risk_pct')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.cost_templates["legacy"] = {
        "initial_capital": 100000, "position_size": 1,
        "commission_value": 0.01, "spread": 0, "slippage": 2,
        "risk_mode": "yüzde", "risk_value": 7,
    }
    studio.apply_cost_template("legacy")
    studio.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
    plan = studio._current_plan()
    assert plan.input_values["in_0"] == [1.9, 2.0, 2.1]
    assert "risk_value" not in plan.costs["assumptions"]
    studio.worker_timer.stop()
    studio.window.close()


def test_self_test_does_not_touch_live_database(monkeypatch):
    from tv_scan_studio import app as app_module

    monkeypatch.setattr(app_module.sys, "argv", ["TV-Scan-Studio.exe", "--self-test"])
    monkeypatch.setattr(app_module, "data_path", lambda: (_ for _ in ()).throw(
        AssertionError("self-test must not use the live data path")))
    assert app_module.main() == 0


def test_cost_input_mapping_uses_named_pine_input_and_clears_on_project_change(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "cost-names.db")
    store.create_project("Costs", 'strategy("Costs")\nfee = input.float(0.1, "Commission rate")')
    store.create_project("Other", 'strategy("Other")\nlength = input.int(3, "Length")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.plan_project.setCurrentIndex(studio.plan_project.findText("Costs"))
    choice = studio.cost_input_choices["commission_value"]
    assert choice.findText("Commission rate") >= 0
    choice.setCurrentIndex(choice.findText("Commission rate"))
    assert studio.commission_input_id.text() == "in_0"
    studio.commission.setValue(0.125)
    assert studio._current_plan().costs["tradingview_inputs"] == {"in_0": 0.125}
    studio.plan_project.setCurrentIndex(studio.plan_project.findText("Other"))
    assert studio.commission_input_id.text() == ""
    assert choice.currentData() == ""
    assert studio._current_plan().costs["tradingview_inputs"] == {}
    studio.worker_timer.stop()
    studio.window.close()


def test_project_picker_filters_names_and_switches_only_after_accept(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "project-picker.db")
    store.create_project("Birinci", 'strategy("Birinci")')
    store.create_project("İkinci", 'strategy("İkinci")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    original_id = studio.plan_project.currentData()

    def cancel_search(dialog):
        search = dialog.findChild(QtWidgets.QLineEdit)
        search.setText("bir")
        assert studio.plan_project.currentData() == original_id
        return QtWidgets.QDialog.Rejected

    monkeypatch.setattr(QtWidgets.QDialog, "exec", cancel_search)
    studio.open_project_picker()
    assert studio.plan_project.currentData() == original_id

    def accept_search(dialog):
        search = dialog.findChild(QtWidgets.QLineEdit)
        results = dialog.findChild(QtWidgets.QListWidget)
        search.setText("ikin")
        assert results.count() == 1
        assert results.item(0).text() == "İkinci"
        assert studio.plan_project.currentData() == original_id
        return QtWidgets.QDialog.Accepted

    monkeypatch.setattr(QtWidgets.QDialog, "exec", accept_search)
    studio.open_project_picker()
    assert studio.plan_project.currentText() == "İkinci"
    studio.worker_timer.stop()
    studio.window.close()


def test_project_picker_groups_recent_projects_without_changing_active_plan(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "project-recents.db")
    first = store.create_project("Birinci", 'strategy("Birinci")')
    second = store.create_project("İkinci", 'strategy("İkinci")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    active_id = studio.plan_project.currentData()
    studio._remember_project(second)

    def inspect_then_cancel(dialog):
        results = dialog.findChild(QtWidgets.QListWidget)
        assert [results.item(row).text() for row in range(results.count())] == [
            "Son kullanılanlar", "İkinci", "Diğer projeler", "Birinci"
        ]
        assert not (results.item(0).flags() & QtCore.Qt.ItemIsSelectable)
        assert studio.plan_project.currentData() == active_id
        return QtWidgets.QDialog.Rejected

    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect_then_cancel)
    studio.open_project_picker()
    assert studio.plan_project.currentData() == active_id
    assert store.app_settings()["recent_project_ids"] == [second]
    studio.worker_timer.stop()
    studio.window.close()


def test_project_picker_offers_new_project_without_changing_active_selection(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "project-picker-new.db")
    store.create_project("Mevcut", 'strategy("Mevcut")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    active_id = studio.plan_project.currentData()

    def choose_new(dialog):
        assert dialog.width() <= 400
        button = dialog.findChild(QtWidgets.QPushButton, "projectPickerNewProject")
        assert button is not None
        assert button.text() == "+ Yeni proje oluştur"
        return 2

    monkeypatch.setattr(QtWidgets.QDialog, "exec", choose_new)
    studio.open_project_picker()
    assert studio.pages.currentIndex() == 1
    assert studio.plan_project.currentData() == active_id
    studio.worker_timer.stop()
    studio.window.close()


def test_programmatic_navigation_highlights_visible_page(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "navigation.db"))
    studio._show_page(2)
    assert studio.pages.currentIndex() == 2
    assert studio.nav_group.checkedId() == 2
    studio._show_page(4)
    assert studio.nav_group.checkedId() == 4
    studio.worker_timer.stop()
    studio.window.close()


def test_results_keep_metrics_and_evidence_first_in_narrow_layout(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "results-columns.db"))
    header = studio.results_table.horizontalHeader()
    assert [header.logicalIndex(position) for position in range(6)] == [0, 5, 6, 7, 8, 9]
    assert studio.results_table.horizontalHeaderItem(8).text() == "Net"
    assert studio.results_table.horizontalHeaderItem(9).text() == "Kanıt"
    studio.worker_timer.stop()
    studio.window.close()


def test_success_view_explains_when_only_eliminated_results_exist(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "non-success-results.db")
    project_id = store.create_project("Only eliminated", 'strategy("Only eliminated")')
    store.enqueue(project_id, "eliminated", {"symbol": "EURUSD", "timeframe": "15"})
    task = store.claim_next(1)
    store.complete(task.id, 1, {"trades": 3, "profit_factor": 0.8}, "elenmiş", verified=True)
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.result_project.setCurrentIndex(studio.result_project.findData(project_id))
    studio.refresh_results()
    assert studio.result_filter.currentText() == "Başarılı"
    assert studio.results_table.rowCount() == 0
    assert "Bu görünümde sonuç yok" in studio.result_empty.text()
    studio.result_filter.setCurrentText("Tümü")
    assert studio.results_table.rowCount() == 1
    studio.filter_dates.setChecked(True)
    assert studio.results_table.rowCount() == 0
    assert "Dönemi bilinmeyen" in studio.result_empty.text()
    studio.worker_timer.stop()
    studio.window.close()


def test_result_empty_state_reflects_project_task_status(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "empty-states.db")
    project_id = store.create_project("Empty states", 'strategy("Empty states")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.result_project.setCurrentIndex(studio.result_project.findData(project_id))
    studio.refresh_results()
    assert "henüz görev yok" in studio.result_empty.text()
    store.enqueue(project_id, "pending", {"symbol": "EURUSD"})
    studio.refresh_results()
    assert "Görevler bekliyor" in studio.result_empty.text()
    task = store.claim_next(1)
    store.fail(task.id, 1, "Bağlantı kesildi", max_attempts=1)
    studio.refresh_results()
    assert "müdahale gerektiren" in studio.result_empty.text()
    studio.worker_timer.stop()
    studio.window.close()


def test_active_result_filters_are_visible_and_clear_together(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "filter-chips.db")
    project_id = store.create_project("Filter chips", 'strategy("Filter chips")')
    for key, classification, pf in (("candidate", "hassas", 1.7),
                                    ("eliminated", "elenmiş", 0.8)):
        store.enqueue(project_id, key, {"symbol": "EURUSD", "timeframe": "15"})
        task = store.claim_next(1)
        store.complete(task.id, 1, {"trades": 80, "profit_factor": pf},
                       classification, verified=True)
    studio = StudioWindow(store)
    assert isinstance(studio.pages.widget(4), QtWidgets.QScrollArea)
    studio.refresh_project_selectors()
    studio.result_project.setCurrentIndex(studio.result_project.findData(project_id))
    studio.filter_pf.setValue(2)
    studio.filter_symbol.setText("EUR")
    assert studio.results_table.rowCount() == 0
    labels = [studio.result_chip_grid.itemAt(index).widget().text()
              for index in range(studio.result_chip_grid.count())]
    assert "Başarılı" in labels
    assert any("PF ≥" in label for label in labels)
    assert "Sembol: EUR" in labels
    studio.result_clear_filters.click()
    assert studio.result_filter.currentText() == "Tümü"
    assert studio.filter_pf.value() == 0
    assert studio.filter_symbol.text() == ""
    assert studio.results_table.rowCount() == 2
    assert studio.results_table.maximumHeight() < 200
    assert studio.result_active_filters.isHidden()
    studio.worker_timer.stop()
    studio.window.close()


def test_empty_results_filter_chip_does_not_expand_into_blank_panel(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "compact-filter-chip.db")
    store.create_project("Demo", 'strategy("Demo")')
    studio = StudioWindow(store)
    studio.window.resize(1240, 810)
    studio.window.show()
    studio._show_page(4)
    application.processEvents()
    assert not studio.result_active_filters.isHidden()
    assert studio.result_active_filters.height() < 60
    chip = studio.result_chip_grid.itemAt(0).widget()
    assert chip.text() == "Başarılı"
    assert chip.width() < 180
    studio.worker_timer.stop()
    studio.window.close()


def test_input_detail_panel_follows_selection_and_mode(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "input-detail.db")
    store.create_project("Inputs", (
        'strategy("Inputs")\n'
        'length = input.int(3, "Length", minval=1)\n'
        'enabled = input.bool(true, "Enabled")\n'
        'plot(length)\nplot(enabled ? 1 : 0)'
    ))
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    assert studio.plan_inputs.accessibleName() == "Strateji inputları"
    assert studio.input_range_start.accessibleName() == "Tarama aralığı başlangıcı"
    assert studio.input_range_stop.accessibleName() == "Tarama aralığı bitişi"
    assert studio.input_range_step.accessibleName() == "Tarama aralığı adımı"
    studio.plan_inputs.selectRow(0)
    assert studio.input_detail_title.text() == "Length"
    assert "Varsayılan: 3" in studio.input_detail_values.text()
    studio.input_detail_mode.setCurrentText("Tara")
    assert studio.plan_inputs.cellWidget(0, 3).currentText() == "Tara"
    studio.input_range_start.setText("2")
    studio.input_range_stop.setText("4")
    studio.input_range_step.setText("1")
    studio.input_detail_mode.setCurrentText("Sabit bırak")
    studio.apply_input_numeric_range()
    assert studio.plan_inputs.item(0, 4).data(QtCore.Qt.UserRole) == [2, 3, 4]
    assert studio.input_detail_mode.currentText() == "Tara"
    assert studio.input_range_step.text() == "1"
    studio.input_range_start.setText("0")
    studio.apply_input_numeric_range()
    assert studio.plan_inputs.item(0, 4).data(QtCore.Qt.UserRole) == [2, 3, 4]
    assert "En küçük değer 1" in studio.plan_status.text()
    studio.plan_inputs.selectRow(1)
    assert studio.input_detail_title.text() == "Enabled"
    assert studio.input_detail_mode.currentText() == "Sabit bırak"
    assert studio.input_numeric_range.isHidden()
    studio.worker_timer.stop()
    studio.window.close()


def test_dashboard_empty_state_guides_user_without_zero_cards_or_blank_tables(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "dashboard-empty.db")
    studio = StudioWindow(store)
    assert not studio.dashboard_setup.isHidden()
    assert studio.dashboard_metrics.isHidden()
    assert studio.project_table.isHidden()
    assert studio.dashboard_events.isHidden()
    assert studio.dashboard_setup_page == 1

    project_id = store.create_project("Demo", 'strategy("Demo")')
    studio.refresh_dashboard()
    assert studio.dashboard_setup_page == 2
    assert not studio.project_table.isHidden()
    assert studio.project_table.item(0, 2).text() == "Taslak"

    store.enqueue(project_id, "first", {"symbol": "OANDA:EURUSD", "timeframe": "15"})
    studio.refresh_dashboard()
    assert studio.dashboard_setup.isHidden()
    assert not studio.dashboard_metrics.isHidden()
    studio.worker_timer.stop()
    studio.window.close()


def test_real_ict_project_previews_without_strategy_id_or_json(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    pine_path = (Path(__file__).resolve().parents[2] / "5_Araclar" /
                 "ICT_Uni_tv2mt5_baglantili.pine")
    if not pine_path.is_file():
        pytest.skip("Kullanıcının yerel ICT Pine dosyası bu ortamda yok; taşınabilir fixture testi ayrı.")
    source = pine_path.read_text(encoding="utf-8")
    store = Store(tmp_path / "ict.db")
    store.create_project("ICT FTMO", source)
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.symbols.setText("OANDA:DE30EUR")
    studio.timeframes.setText("15")
    # This is the user's live Pine file; its input count can evolve independently
    # of the app. The UI must render every currently parsed input.
    assert studio.plan_inputs.rowCount() == len(studio._plan_parsed_inputs) > 100
    assert not studio.scope_frame.isHidden()
    assert "12 grafik rengi inputu" in studio.auto_excluded_notice.text()
    color_row = next(row for row, item in enumerate(studio._plan_parsed_inputs)
                     if item.variable == "asiaCol")
    assert studio.plan_inputs.item(color_row, 1).text() == "asiaCol (grafik rengi)"
    assert studio.plan_inputs.cellWidget(color_row, 3).currentText() == "Hariç tut"
    assert studio._current_plan().task_count == 1
    assert studio.study_id.text() == ""
    assert not studio.enqueue_plan_button.isEnabled()
    assert "1 görev" in studio.plan_status.text()
    studio.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
    assert studio._current_plan().task_count == 3
    assert "3 görev" in studio.plan_status.text()
    assert "7.5 KB" in studio.plan_status.text()
    assert "ZigZag Length ×3" in studio.plan_factors.text()
    assert "3 input birleşimi = 3 görev" in studio.plan_factors.text()
    studio.window.resize(1280, 720)
    studio.window.show()
    studio._show_page(2)
    application.processEvents()
    assert not studio.scope_frame.isHidden()
    assert studio.scan_scroll.verticalScrollBar().maximum() > 0
    assert studio.symbols.text() == "OANDA:DE30EUR"
    assert studio._current_plan().task_count == 3
    assert studio.plan_inputs.item(0, 4).data(0x0100) == [2, 3, 4]
    if studio.session_variants_check.isEnabled():
        studio.session_variants_check.setChecked(True)
        assert studio._current_plan().task_count == 12  # 3 lengths × 4 observed DE30 bundles.
        assert len(studio._current_plan().variants) == 4
    else:
        assert studio._current_plan().task_count == 3  # Source hash no longer matches catalog.
    studio.worker_timer.stop()
    studio.window.close()


def test_typed_10am_inputs_render_in_project_and_scan_pages(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "typed-10am.db")
    source = '''
strategy("ICT 10AM First FVG Daily Strategy")
string timezoneInput = input.string("America/New_York", "Timezone")
int startHour = input.int(10, "Setup start hour", minval=0, maxval=23)
bool enableLong = input.bool(true, "Enable long")
plot(startHour)
'''
    store.create_project("10AM", source)
    studio = StudioWindow(store)
    studio.project_name.setText("10AM preview")
    studio.pine_source.setPlainText(source)
    assert len(studio.analyze_source()) == 3
    assert studio.input_table.rowCount() == 3
    studio.refresh_project_selectors()
    assert studio.plan_inputs.rowCount() == 3
    assert [studio.plan_inputs.item(row, 1).text() for row in range(3)] == [
        "Timezone", "Setup start hour", "Enable long",
    ]
    studio.symbols.setText("OANDA:EURUSD")
    studio.timeframes.setText("15")
    assert studio._current_plan().task_count == 1
    studio.worker_timer.stop()
    studio.window.close()


def test_user_10am_file_inputs_visible_when_available(tmp_path):
    pine_path = (Path(__file__).resolve().parents[2] / "5_Araclar" /
                 "ICT_10AM_First_FVG_Daily_Strategy.pine")
    if not pine_path.is_file():
        pytest.skip("Kullanıcının yerel 10AM Pine dosyası bu ortamda yok.")
    source = pine_path.read_text(encoding="utf-8")
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "real-10am.db")
    store.create_project("10AM", source)
    studio = StudioWindow(store)
    studio.project_name.setText("10AM preview")
    studio.pine_source.setPlainText(source)
    analyzed = studio.analyze_source()
    studio.refresh_project_selectors()
    assert analyzed
    assert studio.input_table.rowCount() == len(analyzed)
    assert studio.plan_inputs.rowCount() == len(analyzed)
    assert studio.plan_inputs.item(0, 1).text() == "Timezone"
    assert studio.plan_inputs.item(len(analyzed) - 1, 1).text() == "Show open / entry / stop / target"
    studio.worker_timer.stop()
    studio.window.close()


def test_large_pine_input_list_scrolls_without_external_user_file(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    source = '\n'.join([
        'strategy("Large synthetic")',
        *(f'int length_{index} = input.int(3, "Length {index}")' for index in range(110)),
        *(f'color shade_{index} = input.color(color.blue, "Shade {index}")'
          for index in range(12)),
        'plot(length_0)',
    ])
    store = Store(tmp_path / "large-synthetic.db")
    store.create_project("Large synthetic", source)
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    assert studio.plan_inputs.rowCount() == 122
    assert "12 grafik rengi inputu" in studio.auto_excluded_notice.text()
    studio.window.resize(1280, 720)
    studio.window.show()
    studio._show_page(2)
    application.processEvents()
    assert studio.scan_scroll.verticalScrollBar().maximum() > 0
    studio.worker_timer.stop()
    studio.window.close()


def test_scan_range_edit_is_visible_without_exposing_internal_input_ids(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "range-button.db")
    store.create_project("Demo", 'strategy("Demo")\nlength=input.int(3,"Length")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    assert studio.plan_inputs.isColumnHidden(0)
    assert studio.plan_inputs.isColumnHidden(5)
    assert studio.plan_inputs.isColumnHidden(6)
    assert studio.edit_input_button.text() == "Seçili aralığı değiştir"
    studio.plan_inputs.clearSelection()
    studio.plan_inputs.setCurrentCell(-1, -1)
    studio.edit_input_button.click()
    assert "Önce" in studio.plan_status.text()
    studio.plan_inputs.setCurrentCell(0, 1)
    studio.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
    edited = []
    monkeypatch.setattr(studio, "edit_scan_values", lambda cell: edited.append(cell))
    studio.edit_input_button.click()
    assert edited == [studio.plan_inputs.item(0, 4)]
    studio.worker_timer.stop()
    studio.window.close()


def test_returning_to_scan_page_preserves_input_choice_and_custom_range(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "plan-navigation.db")
    store.create_project("Demo", 'strategy("Demo")\nlength=input.int(3,"Length")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.symbols.setText("OANDA:EURUSD")
    studio.timeframes.setText("15")
    studio.plan_inputs.cellWidget(0, 3).setCurrentText("Tara")
    studio.plan_inputs.item(0, 4).setData(QtCore.Qt.UserRole, [3, 5])
    studio.preview_plan()
    assert studio._current_plan().task_count == 2

    studio._show_page(0)
    studio._show_page(2)
    assert studio.plan_inputs.cellWidget(0, 3).currentText() == "Tara"
    assert studio.plan_inputs.item(0, 4).data(QtCore.Qt.UserRole) == [3, 5]
    assert studio._current_plan().task_count == 2
    studio.worker_timer.stop()
    studio.window.close()


def test_success_criteria_are_collapsed_but_kept_in_plan(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "criteria.db"))
    assert not studio.criteria_toggle.isChecked()
    assert "İşlem ≥60" in studio.criteria_toggle.text()
    studio.min_trades.setValue(82)
    assert "İşlem ≥82" in studio.criteria_toggle.text()
    studio.criteria_toggle.click()
    assert studio.criteria_toggle.text() == "Başarı kriterleri"
    assert studio._current_plan().criteria["min_trades"] == 82
    studio.worker_timer.stop()
    studio.window.close()


def test_project_change_resets_session_bundle_and_strategy_binding(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    source = 'strategy("ICT FTMO")\nlength=input.int(3,"Length")'
    store = Store(tmp_path / "switch.db")
    store.create_project("ICT FTMO", source)
    store.create_project("Other", 'strategy("Other")\nlength=input.int(3,"Length")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.plan_project.setCurrentIndex(studio.plan_project.findText("ICT FTMO"))
    # Exercise reset even if this external Pine file no longer matches the
    # snapshot hash in the research catalog.
    studio.session_variants_check.setEnabled(True)
    studio.session_variants_check.setChecked(True)
    studio.plan_project.setCurrentIndex(studio.plan_project.findText("Other"))
    assert not studio.session_variants_check.isChecked()
    assert not studio.session_variants_check.isEnabled()
    assert studio.study_id.text() == ""
    assert not studio.enqueue_plan_button.isEnabled()
    studio.worker_timer.stop()
    studio.window.close()


def test_failed_strategy_rediscovery_clears_stale_queue_binding(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "rediscover.db")
    store.create_project("Demo", 'strategy("Demo")\nlength=input.int(3,"Length")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.symbols.setText("OANDA:DE30EUR")
    studio.timeframes.setText("15")
    studio.strategy_picker.addItem("Demo · eski grafik", {
        "study_id": "stale-id", "target_id": "old-target"})
    studio.strategy_picker.setCurrentIndex(1)
    assert studio.enqueue_plan_button.isEnabled()

    class BrokenDriver:
        def __init__(self, *_args):
            pass
        def inventory(self):
            raise RuntimeError("bağlantı kesildi")

    monkeypatch.setattr(app_module, "GncZihinDriver", BrokenDriver)
    studio.discover_plan_strategies()
    assert studio.study_id.text() == ""
    assert studio.strategy_picker.currentData() is None
    assert not studio.enqueue_plan_button.isEnabled()
    assert "bağlantı kesildi" in studio.plan_status.text()
    studio.enqueue_current_plan()
    assert store.counts(store.projects()[0]["id"]) == {}
    studio.worker_timer.stop()
    studio.window.close()


@pytest.mark.parametrize('ready', [False, True])
def test_ui_refuses_date_plan_until_tradingview_can_apply_dates(tmp_path, monkeypatch, ready):
    from tv_scan_studio.planner import ScanPlan
    from tv_scan_studio.tradingview import GncZihinDriver
    monkeypatch.setattr(GncZihinDriver, 'date_range_ready', ready)

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "date-plan.db")
    project = store.create_project("Dates", 'strategy("Dates")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.plan_project.setCurrentIndex(studio.plan_project.findData(project))
    studio.study_id.setText("study-1")
    studio.strategy_picker.addItem("Dates · worker", {"study_id": "study-1", "target_id": "worker-1"})
    studio.strategy_picker.setCurrentIndex(studio.strategy_picker.count() - 1)
    monkeypatch.setattr(studio, "_current_plan", lambda: ScanPlan(
        "study-1", ("OANDA:EURUSD",), ("15",), {"in_0": [20]},
        date_range={"from": "2025-01-01", "to": "2025-12-31"},
    ))
    studio.preview_plan()
    assert studio.enqueue_plan_button.isEnabled() is ready
    if not ready:
        assert "özel tarih henüz" in studio.plan_status.text()
    studio.enqueue_current_plan()
    assert store.counts(project) == ({'pending':1} if ready else {})
    if not ready:
        assert "tarihli görevler kuyruklanamaz" in studio.plan_status.text()
    studio.worker_timer.stop()
    studio.window.close()


def test_project_selection_restores_saved_symbols_timeframes_and_dates(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / 'saved-plan.db')
    project = store.create_project('Saved', 'strategy("Saved")\nn = input.int(3, "Length")')
    store.save_settings(project, dict(symbols=['OANDA:EURUSD'], timeframes=['1m','2m'],
        date_range={'from':'2026-09-15','to':'2026-09-23'}, input_values={'in_0':[4,5]},
        costs={'assumptions':{'initial_capital':50000,'position_size':2,
                             'commission_value':.02,'slippage':5}},
        criteria={'min_profit_factor':1.7,'min_trades':80}))
    store.save_settings(project, {'input_ui':{'in_0':{'decision':'Sabit bırak',
        'values':[4,5], 'range':{'start':4,'end':5,'step':1}}}})
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.plan_project.setCurrentIndex(studio.plan_project.findData(project))
    studio.load_plan_inputs()
    assert studio.symbols.text() == 'OANDA:EURUSD'
    assert studio.timeframes.text() == '1m, 2m'
    assert studio.date_from.text() == '2026-09-15'
    assert studio.date_to.text() == '2026-09-23'
    assert studio.plan_inputs.cellWidget(0,3).currentText() == 'Sabit bırak'
    assert studio.plan_inputs.item(0,4).data(QtCore.Qt.UserRole) == [4,5]
    assert studio.plan_inputs.item(0,4).data(QtCore.Qt.UserRole + 1) == {'start':4,'end':5,'step':1}
    assert studio.initial_capital.value() == 50000
    assert studio.slippage.value() == 5
    assert studio.min_pf.value() == 1.7
    assert studio.min_trades.value() == 80
    assert not studio.study_id.text()  # Never reuse a stale chart identity.
    studio.worker_timer.stop()
    studio.window.close()


def test_dashboard_projects_keep_space_when_events_are_visible(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / 'dashboard-space.db')
    for index in range(8):
        store.create_project(f'Project {index}', 'strategy("Demo")')
    studio = StudioWindow(store)
    studio.window.resize(1280, 800)
    studio.dashboard_events_heading.show()
    studio.dashboard_events.show()
    studio.dashboard_events.setRowCount(4)
    studio.window.show()
    application.processEvents()
    assert studio.project_table.height() >= 140
    dashboard_layout = studio.dashboard.layout()
    assert dashboard_layout.itemAt(dashboard_layout.count() - 1).widget() is studio.dashboard_status
    studio.worker_timer.stop()
    studio.window.close()


def test_new_project_does_not_inherit_previous_projects_costs_or_criteria(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / 'project-isolation.db')
    first = store.create_project('First', 'strategy("First")\nn=input.int(3,"Length")')
    second = store.create_project('Second', 'strategy("Second")\nn=input.int(3,"Length")')
    store.save_settings(first, {'costs': {'assumptions': {
        'initial_capital': 50000, 'position_size': 2, 'commission_value': .04,
        'spread': 1, 'slippage': 10}}, 'criteria': {
        'min_trades': 80, 'min_profit_factor': 2, 'min_win_rate_pct': 70,
        'max_drawdown_pct_exclusive': 3, 'min_net_profit': 100,
        'max_daily_loss_pct': 2, 'max_total_loss_pct': 4}})
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.plan_project.setCurrentIndex(studio.plan_project.findData(first))
    studio.load_plan_inputs()
    assert studio.slippage.value() == 10
    assert studio.ftmo_risk_check.isChecked()
    studio.plan_project.setCurrentIndex(studio.plan_project.findData(second))
    studio.load_plan_inputs()
    assert [field.value() for field in (studio.initial_capital, studio.position_size,
            studio.commission, studio.spread, studio.slippage)] == [100000, 1, 0, 0, 0]
    assert [field.value() for field in (studio.min_trades, studio.min_pf, studio.min_win,
            studio.max_dd, studio.min_net, studio.max_daily_loss,
            studio.max_total_loss)] == [60, 1.4, 40, 5, 0, 5, 10]
    assert not studio.ftmo_risk_check.isChecked()
    assert not studio.symbols.text()
    assert not studio.study_id.text()
    studio.worker_timer.stop()
    studio.window.close()


def test_scan_input_shows_controlled_no_effect_hint_without_excluding(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "no-effect.db")
    project = store.create_project("No effect", 'strategy("No effect")\nlength=input.int(3,"Length")\nplot(length)')
    metrics = {"trades": 80, "profit_factor": 1.7, "max_drawdown_pct": 4.0,
               "net_profit": 900}
    for value in (2, 3, 4):
        store.enqueue(project, f"length-{value}", {"symbol": "DE30", "timeframe": "15",
                                                  "inputs": {"in_0": value}})
        task = store.claim_next(1)
        store.complete(task.id, 1, metrics, "hassas", verified=True)
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    note = studio.plan_inputs.item(0, 6).text()
    assert "etkisiz olabilir" in note
    assert "Otomatik dışlanmadı" in note
    assert studio.plan_inputs.cellWidget(0, 3).currentText() == "Sabit bırak"
    assert studio.auto_excluded_notice.isHidden()
    studio.worker_timer.stop()
    studio.window.close()


def test_source_unused_input_is_auto_excluded_but_user_can_restore_it(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "unused-input.db")
    store.create_project("Unused", 'strategy("Unused")\n'
                         'unused=input.int(3,"Unused setting")\n'
                         'used=input.int(5,"Used setting")\nplot(used)')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    unused_choice = studio.plan_inputs.cellWidget(0, 3)
    assert unused_choice.currentText() == "Hariç tut"
    assert studio.plan_inputs.cellWidget(1, 3).currentText() == "Sabit bırak"
    assert "otomatik dışlandı" in studio.plan_inputs.item(0, 6).text()
    assert not studio.auto_excluded_notice.isHidden()
    assert "1 input" in studio.auto_excluded_notice.text()
    assert "in_0" not in studio._current_plan().input_values
    assert studio._current_plan().input_values["in_1"] == [5]
    unused_choice.setCurrentText("Tara")
    assert studio._current_plan().input_values["in_0"] == [2, 3, 4]
    studio.worker_timer.stop()
    studio.window.close()


def test_tooltip_declared_non_backtest_input_starts_excluded_but_is_editable(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "alert-only.db")
    store.create_project("Risk", 'strategy("Risk")\n'
                         'risk=input.float(1.0,"Bridge risk",tooltip="Backtest boyutunu ETKILEMEZ.")\n'
                         'message=str.tostring(risk)')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    choice = studio.plan_inputs.cellWidget(0, 3)
    assert choice.currentText() == "Hariç tut"
    assert "Pine açıklamasına göre" in studio.plan_inputs.item(0, 6).text()
    choice.setCurrentText("Tara")
    assert "in_0" in studio._current_plan().input_values
    studio.worker_timer.stop()
    studio.window.close()


def test_project_progress_counts_finished_and_issues_without_claiming_success(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "progress.db")
    project_id = store.create_project("Progress", 'strategy("Progress")')
    for key in ("done", "issue", "pending"):
        store.enqueue(project_id, key, {"symbol": "EURUSD"})
    done = store.claim_next(1)
    store.complete(done.id, 1, {"trades": 1}, "elenmiş", verified=True)
    issue = store.claim_next(1)
    store.fail(issue.id, 1, "error", max_attempts=1)
    studio = StudioWindow(store)
    progress = studio.project_table.cellWidget(0, 5)
    assert isinstance(progress, ProjectProgressBar)
    assert progress.maximum() == 3
    assert progress.value() == 2
    assert "Hata/inceleme 1" in progress.toolTip()
    opened = []
    studio.open_dashboard_tasks = lambda status, project_id=None: opened.append((status, project_id))
    progress.clicked.emit()
    assert opened == [(None, project_id)]
    studio.worker_timer.stop()
    studio.window.close()


def test_result_export_dialog_enforces_all_vs_success_format_matrix(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "export-ui.db")
    project = store.create_project("Export UI", 'strategy("Export UI")')
    store.enqueue(project, "success", {"symbol": "EURUSD", "timeframe": "15", "inputs": {"in_0": 1}})
    success = store.claim_next(1)
    store.complete(success.id, 1, {"trades": 80, "profit_factor": 1.7,
                                   "max_drawdown_pct": 4.0}, "hassas", verified=True)
    store.enqueue(project, "failed", {"symbol": "EURUSD", "timeframe": "15", "inputs": {"in_0": 2}})
    failed = store.claim_next(1)
    store.fail(failed.id, 1, "CDP koptu", max_attempts=1)
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.refresh_results()
    assert studio.results_table.columnCount() == 10
    assert studio.results_table.horizontalHeaderItem(7).text() == "DD %"
    assert studio.results_table.horizontalHeaderItem(8).text() == "Net"
    assert studio.results_table.item(0, 9).text() == "Doğrulandı"
    choice = {"kind": 0, "format": 0, "scope": 0, "path": tmp_path / "all.csv"}

    def choose_export(dialog):
        kinds = dialog.findChildren(QtWidgets.QComboBox)
        assert len(kinds) == 3
        kinds[2].setCurrentIndex(choice["format"])
        kinds[0].setCurrentIndex(choice["kind"])
        kinds[1].setCurrentIndex(choice["scope"])
        assert not kinds[0].isEnabled() if choice["format"] == 2 else kinds[0].isEnabled()
        preview = dialog.findChild(QtWidgets.QLabel, "export_count_preview")
        expected = 2 if choice["scope"] == 0 and choice["kind"] == 0 and choice["format"] != 2 else 1
        assert f"{expected} kayıt" in preview.text()
        return QtWidgets.QDialog.Accepted

    monkeypatch.setattr(QtWidgets.QDialog, "exec", choose_export)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda *_args: (str(choice["path"]), ""))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *_args: None)

    studio.export_current_results()
    with choice["path"].open(encoding="utf-8-sig", newline="") as stream:
        assert {row["task_key"] for row in csv.DictReader(stream)} == {"success", "failed"}

    choice.update(scope=1, path=tmp_path / "visible.csv")
    studio.export_current_results()
    with choice["path"].open(encoding="utf-8-sig", newline="") as stream:
        assert [row["task_key"] for row in csv.DictReader(stream)] == ["success"]

    choice.update(kind=1, format=1, scope=0, path=tmp_path / "success.xlsx")
    studio.export_current_results()
    with zipfile.ZipFile(choice["path"]) as archive:
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert len(sheet.find("{*}sheetData")) == 2

    choice.update(kind=0, format=2, path=tmp_path / "success.pdf")
    studio.export_current_results()
    assert choice["path"].read_bytes().startswith(b"%PDF")
    studio.worker_timer.stop()
    studio.window.close()


def test_pdf_export_excludes_unverified_candidate(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "pdf-verification.db")
    project = store.create_project("PDF Verification", 'strategy("PDF Verification")')
    for key in ("confirmed", "unverified"):
        store.enqueue(project, key, {"symbol": "EURUSD", "timeframe": "15"})
        task = store.claim_next(1)
        store.complete(task.id, 1, {"trades": 80, "profit_factor": 1.7},
                       "hassas", verified=True)
    # Simulate a legacy/imported result whose class was stored without proof.
    with store.connect() as connection:
        connection.execute(
            "UPDATE results SET verified=0 WHERE task_id=(SELECT id FROM tasks WHERE task_key=?)",
            ("unverified",),
        )
        connection.commit()
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.result_project.setCurrentIndex(studio.result_project.findData(project))
    studio.refresh_results()
    assert studio.results_table.rowCount() == 1
    captured = {}

    def choose_pdf(dialog):
        combos = dialog.findChildren(QtWidgets.QComboBox)
        combos[2].setCurrentText("PDF")
        return QtWidgets.QDialog.Accepted

    monkeypatch.setattr(QtWidgets.QDialog, "exec", choose_pdf)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda *_args: (str(tmp_path / "success.pdf"), "PDF (*.pdf)"))
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(app_module, "export_project_pdf",
                        lambda _project, rows, _destination: captured.setdefault(
                            "keys", [row["task_key"] for row in rows]) and len(rows))
    studio.export_current_results()
    assert captured["keys"] == ["confirmed"]
    studio.worker_timer.stop()
    studio.window.close()


def test_historical_export_keeps_input_columns_first_seen_later(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "historical-ui.db"))
    first = {"payload": {"inputs": {"in_0": 1}}}
    last = {"payload": {"inputs": {"in_0": 2, "in_1": 9}}}
    records = [first] * 33_074 + [last]
    monkeypatch.setattr(app_module, "iter_historical_records", lambda: iter(records))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda *_args: (str(tmp_path / "all.csv"), "CSV (*.csv)"))
    captured = {}

    def writer(rows, _path, input_ids):
        captured["input_ids"] = list(input_ids)
        captured["rows"] = list(rows)
        return 33_075

    monkeypatch.setattr(app_module, "export_task_csv", writer)
    studio.export_historical_records()
    assert captured["input_ids"] == ["in_0", "in_1"]
    assert len(captured["rows"]) == 33_075
    assert captured["rows"][-1] == last
    studio.worker_timer.stop()
    studio.window.close()


def test_historical_export_reports_corrupt_archive_before_writing(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "corrupt-archive.db"))
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName",
                        lambda *_args: (str(tmp_path / "all.csv"), "CSV (*.csv)"))

    def broken_records():
        yield {"payload": {"inputs": {"in_0": 1}}}
        raise ValueError("Arşiv satırı okunamadı")

    monkeypatch.setattr(app_module, "iter_historical_records", broken_records)
    studio.export_historical_records()
    assert "Arşiv satırı okunamadı" in studio.research_status.text()
    assert not (tmp_path / "all.csv").exists()
    studio.worker_timer.stop()
    studio.window.close()


def test_equity_chart_interactions_use_actual_points():
    from PySide6 import QtCore, QtGui, QtTest

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    points = [{"time": 1_700_000_000_000 + index * 86_400_000,
               "equity": 1000 + index * 10, "drawdown": index % 3}
              for index in range(20)]
    chart = CurveChart(points)
    chart.resize(600, 240)
    chart.show()
    application.processEvents()
    assert chart._index_at(chart._area().left()) == 0
    assert chart._index_at(chart._area().right()) == 19
    position = QtCore.QPointF(chart._area().center())
    wheel = QtGui.QWheelEvent(position, position, QtCore.QPoint(), QtCore.QPoint(0, 120),
                              QtCore.Qt.NoButton, QtCore.Qt.NoModifier,
                              QtCore.Qt.ScrollUpdate, False)
    chart.wheelEvent(wheel)
    assert chart._view_end - chart._view_start < len(points)
    chart.mouseDoubleClickEvent(None)
    assert (chart._view_start, chart._view_end) == (0, len(points))
    assert chart.focusPolicy() == QtCore.Qt.StrongFocus
    chart.setFocus()
    QtTest.QTest.keyClick(chart, QtCore.Qt.Key_Plus)
    assert chart._view_end - chart._view_start < len(points)
    zoomed_count = chart._view_end - chart._view_start
    QtTest.QTest.keyClick(chart, QtCore.Qt.Key_Minus)
    assert chart._view_end - chart._view_start > zoomed_count
    QtTest.QTest.keyClick(chart, QtCore.Qt.Key_Home)
    assert (chart._view_start, chart._view_end) == (0, len(points))
    chart.close()


def test_equity_chart_does_not_draw_invented_zero_for_missing_point():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    chart = CurveChart([
        {"time": 1_700_000_000_000, "equity": 1000, "drawdown": 0},
        {"time": 1_700_086_400_000, "equity": None, "drawdown": 4},
    ])
    assert chart._invalid_points
    assert chart.points == []
    chart.resize(600, 240)
    chart.show()
    application.processEvents()
    chart.close()


def test_result_scatter_selects_real_task_and_skips_missing_metrics():
    from PySide6 import QtCore, QtTest

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    chart = ResultScatterChart()
    chart.resize(600, 220)
    chart.set_rows([
        {"task_id": 7, "task_key": "candidate-7", "payload": {"symbol": "DE30"},
         "verified": True, "metrics": {"profit_factor": 1.7, "max_drawdown_pct": 4.1, "trades": 82}},
        {"task_id": 8, "task_key": "missing-8", "payload": {},
         "verified": False, "metrics": {"trades": 0}},
        {"task_id": 10, "task_key": "invalid-10", "payload": {},
         "verified": False, "metrics": {"profit_factor": True, "max_drawdown_pct": 2}},
    ])
    chart.show()
    application.processEvents()
    assert len(chart._points) == 1
    selected = []
    chart.selected.connect(selected.append)
    x, y, _radius, _row = chart._points[0]
    QtTest.QTest.mouseClick(chart, QtCore.Qt.LeftButton, pos=QtCore.QPoint(round(x), round(y)))
    assert selected == [7]
    chart.set_rows([
        {"task_id": 7, "task_key": "candidate-7", "payload": {"symbol": "DE30"},
         "verified": True, "metrics": {"profit_factor": 1.7, "max_drawdown_pct": 4.1, "trades": 82}},
        {"task_id": 9, "task_key": "candidate-9", "payload": {"symbol": "DE30"},
         "verified": True, "metrics": {"profit_factor": 1.5, "max_drawdown_pct": 3.8, "trades": 74}},
    ])
    application.processEvents()
    assert chart.focusPolicy() == QtCore.Qt.StrongFocus
    chart.setFocus()
    QtTest.QTest.keyClick(chart, QtCore.Qt.Key_Right)
    QtTest.QTest.keyClick(chart, QtCore.Qt.Key_Return)
    assert selected[-1] == 9
    QtTest.QTest.keyClick(chart, QtCore.Qt.Key_Home)
    QtTest.QTest.keyClick(chart, QtCore.Qt.Key_Return)
    assert selected[-1] == 7
    chart.close()


def test_comparison_marks_unverified_result_as_unverified(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "comparison.db"))
    rows = [
        {"task_key": "verified", "payload": {"symbol": "DE30", "timeframe": "15"},
         "metrics": {"profit_factor": 1.7}, "verified": True, "classification": "hassas"},
        {"task_key": "invalid", "payload": {"symbol": "DE30", "timeframe": "15"},
         "metrics": {"profit_factor": 1.6}, "verified": False, "classification": "geçersiz"},
    ]
    monkeypatch.setattr(studio, "selected_result_rows", lambda: rows)
    observed = {}

    def inspect_dialog(dialog):
        labels = [label.text() for label in dialog.findChildren(QtWidgets.QLabel)]
        table = dialog.findChild(QtWidgets.QTableWidget)
        observed["labels"] = labels
        observed["proof"] = [table.item(4, column).text() for column in range(2)]
        return QtWidgets.QDialog.Rejected

    monkeypatch.setattr(QtWidgets.QDialog, "exec", inspect_dialog)
    studio.compare_selected_results()
    assert any("Doğrulanmamış kayıtlar var" in label for label in observed["labels"])
    assert observed["proof"] == ["Doğrulandı", "Doğrulanmadı"]
    studio.worker_timer.stop()
    studio.window.close()


def test_metric_bars_only_uses_saved_numeric_buckets():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    chart = MetricBarsChart({"09:00": 12.5, "10:00": -3.0, "unknown": None,
                             "nan": float("nan"), "infinite": float("inf"), "flag": True})
    chart.resize(600, 250)
    chart.show()
    application.processEvents()
    assert len(chart._bars) == 2
    assert [(label, value) for _, label, value in chart._bars] == [
        ("09:00", 12.5), ("10:00", -3.0)]
    chart.close()


def test_daily_calendar_omits_nonfinite_and_boolean_pnl():
    from tv_scan_studio.app import DailyPnlCalendar

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    calendar = DailyPnlCalendar({"2026-09-01": 0, "2026-09-02": float("nan"),
                                 "2026-09-03": True})
    assert calendar.daily == {"2026-09-01": 0.0}
    calendar.close()


def test_result_filter_preset_round_trip(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "filters.db")
    store.create_project("Filter test", 'strategy("Filter test")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.filter_pf.setValue(1.55)
    studio.filter_symbol.setText("DE30")
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *_args: ("DE30 güçlü", True))
    studio.save_result_filter()
    studio.filter_pf.setValue(0)
    studio.filter_symbol.clear()
    studio.saved_result_filter.setCurrentText("DE30 güçlü")
    studio.apply_saved_result_filter(0)
    assert studio.filter_pf.value() == 1.55
    assert studio.filter_symbol.text() == "DE30"
    assert "DE30 güçlü" in (store.settings(1) or {})["result_filters"]
    studio.worker_timer.stop()
    studio.window.close()


def test_cost_scenario_filter_uses_project_values_and_persists(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "cost-filter.db")
    project_id = store.create_project("Cost filter", 'strategy("Cost filter")')
    for key, scenario in (("normal", "Normal"), ("heavy", "Ağır stres")):
        store.enqueue(project_id, key, {"symbol": "EURUSD", "timeframe": "15",
                                        "costs": {"assumptions": {"scenario": scenario}}})
        task = store.claim_next(1)
        store.complete(task.id, 1, {"trades": 80, "profit_factor": 1.7},
                       "hassas", verified=True)
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.result_project.setCurrentIndex(studio.result_project.findData(project_id))
    studio.refresh_results()
    assert studio.filter_cost_scenario.findData("Ağır stres") >= 0
    studio.filter_cost_scenario.setCurrentIndex(studio.filter_cost_scenario.findData("Ağır stres"))
    assert studio.results_table.rowCount() == 1
    assert "Maliyet: Ağır stres" in studio._active_result_filter_labels()
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *_args: ("Ağır maliyet", True))
    studio.save_result_filter()
    studio.clear_result_filters()
    assert studio.results_table.rowCount() == 2
    studio.saved_result_filter.setCurrentText("Ağır maliyet")
    studio.apply_saved_result_filter(0)
    assert studio.filter_cost_scenario.currentData() == "Ağır stres"
    assert studio.results_table.rowCount() == 1
    studio.worker_timer.stop()
    studio.window.close()


def test_daily_calendar_does_not_invent_missing_day_pnl():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    calendar = DailyPnlCalendar({"2026-09-01": 12.5, "2026-09-03": -4.0})
    assert calendar.month.currentText() == "2026-09"
    assert calendar.table.item(0, 1).data(0x0100) == "2026-09-01"
    assert calendar.table.item(0, 1).text().endswith("+12.50")
    assert calendar.table.item(0, 2).text() == "2"
    calendar.show_day(0, 2)
    assert "sıfır varsayılmadı" in calendar.detail.text()
    calendar.close()


def test_new_worker_targets_are_tracked_without_touching_existing_tabs(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "safe-targets.db"))
    monkeypatch.setattr(app_module, "open_chart_tabs", lambda count, port: ["new-1", "new-2"])
    studio.create_worker_tabs()
    assert studio._safe_worker_targets == set()
    assert "existing-live" not in studio._safe_worker_targets
    assert not studio.start_workers_button.isEnabled()
    studio.worker_timer.stop()
    studio.window.close()


def test_worker_identity_is_rechecked_after_user_confirmation(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "identity.db")
    project_id = store.create_project("Identity", 'strategy("Identity")\nlength=input.int(3,"Length")')
    store.save_settings(project_id, {"tradingview_identity": {
        "pine_id": "USER;expected", "pine_hash": store.project(project_id)["pine_hash"]}})
    studio = StudioWindow(store)
    studio._safe_worker_targets.add("new-tab")
    studio._safe_worker_layouts["new-tab"] = "Unique1"
    strategy = {"id": "study-1", "pine_id": "USER;expected", "name": "Identity",
                "input_ids": ["in_0"], "status": {"type": 2}}

    class Driver:
        def __init__(self):
            self.items = [{"target_id": "new-tab", "strategies": [strategy]}]
        def inventory(self):
            return self.items
        def layout_name(self, _target_id):
            return "TV Scan Worker 1"
        def replay_active(self, _target_id):
            return False

    driver = Driver()
    studio.driver = driver
    monkeypatch.setattr(app_module, "chart_targets", lambda **_kwargs: [
        {"id": "new-tab", "url": "https://www.tradingview.com/chart/Unique1/"}])
    assignment = WorkerAssignment(1, "new-tab", (project_id,), "study-1")
    with pytest.raises(ValueError, match="Strateji kimliği"):
        studio._validate_live_worker_assignments([assignment])
    store.save_settings(project_id, {"tradingview_identity": {
        "pine_id": "USER;expected", "pine_hash": store.project(project_id)["pine_hash"],
        "input_ids": ["in_0"], "user_source_confirmed": True}})
    studio._validate_live_worker_assignments([assignment])
    driver.items = [{"target_id": "new-tab", "strategies": [
        {**strategy, "input_ids": ["in_0", "in_1"]}]}]
    with pytest.raises(ValueError, match="input yapısı"):
        studio._validate_live_worker_assignments([assignment])
    driver.items = [{"target_id": "new-tab", "strategies": [
        {**strategy, "pine_id": "USER;changed"}]}]
    with pytest.raises(ValueError, match="Strateji kimliği"):
        studio._validate_live_worker_assignments([assignment])
    driver.items = []
    with pytest.raises(ValueError, match="artık 9222"):
        studio._validate_live_worker_assignments([assignment])
    studio.worker_timer.stop()
    studio.window.close()


def test_worker_binding_records_explicit_user_source_confirmation(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "user-source-confirmation.db")
    project_id = store.create_project("Identity", 'strategy("Identity")\nlength=input.int(3,"Length")')
    studio = StudioWindow(store)
    studio.worker_table.setRowCount(1)
    project_choice = QtWidgets.QComboBox()
    project_choice.addItem("Identity", project_id)
    studio.worker_table.setCellWidget(0, 3, project_choice)
    strategy = QtWidgets.QTableWidgetItem("Identity")
    strategy.setData(QtCore.Qt.UserRole, {
        "id": "study-1", "pine_id": "USER;expected", "name": "Identity",
        "input_ids": ["in_0"],
    })
    studio.worker_table.setItem(0, 4, strategy)
    studio.worker_table.setCurrentCell(0, 4)
    prompts = []

    def confirm(_parent, _title, message):
        prompts.append(message)
        return QtWidgets.QMessageBox.Yes

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", confirm)
    monkeypatch.setattr(studio, "discover_targets", lambda: None)
    studio.bind_selected_strategy()
    identity = store.settings(project_id)["tradingview_identity"]
    assert identity["user_source_confirmed"] is True
    assert "otomatik doğrulanamadı" in prompts[0]
    assert identity["source_verification"] == "user_confirmation"
    assert identity["source_sha256"] is None
    studio.worker_timer.stop()
    studio.window.close()


def test_worker_start_aborts_when_identity_changes_after_confirmation(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "race.db")
    project_id = store.create_project("Race", 'strategy("Race")\nlength=input.int(3,"Length")')
    store.save_settings(project_id, {"tradingview_identity": {
        "pine_id": "USER;expected", "pine_hash": store.project(project_id)["pine_hash"],
        "user_source_confirmed": True}})
    studio = StudioWindow(store)
    studio.driver = type("Driver", (), {"inventory": lambda _self: [{
        "target_id": "new-tab", "strategies": [{"id": "study-1", "pine_id": "USER;changed",
        "name": "Race", "input_ids": ["in_0"], "status": {"type": 2}}]}]})()
    studio._safe_worker_targets.add("new-tab")
    studio._safe_worker_layouts["new-tab"] = "Unique1"
    monkeypatch.setattr(app_module, "chart_targets", lambda **_kwargs: [
        {"id": "new-tab", "url": "https://www.tradingview.com/chart/Unique1/"}])
    studio.driver.layout_name = lambda _target_id: "TV Scan Worker 1"
    studio.driver.replay_active = lambda _target_id: False
    studio.worker_table.setRowCount(1)
    enabled = QtWidgets.QTableWidgetItem()
    enabled.setCheckState(QtCore.Qt.Checked)
    studio.worker_table.setItem(0, 0, enabled)
    for column, value in ((1, "1"), (2, "Çalışma sekmesi 1"), (5, WORKER_READY_LABEL)):
        studio.worker_table.setItem(0, column, QtWidgets.QTableWidgetItem(value))
    studio.worker_table.item(0, 2).setData(QtCore.Qt.UserRole, "new-tab")
    project_combo = QtWidgets.QComboBox()
    project_combo.addItem("Race", project_id)
    studio.worker_table.setCellWidget(0, 3, project_combo)
    strategy_cell = QtWidgets.QTableWidgetItem("Race")
    strategy_cell.setData(QtCore.Qt.UserRole, {"id": "study-1"})
    studio.worker_table.setItem(0, 4, strategy_cell)
    monkeypatch.setattr(app_module, "cdp_healthy", lambda port: True)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_args: QtWidgets.QMessageBox.Yes)
    monkeypatch.setattr(app_module, "WorkerSupervisor", lambda *_args: pytest.fail("worker başlatıldı"))
    studio.start_workers()
    assert "Strateji kimliği" in studio.worker_status.text()
    assert studio.supervisor is None
    studio.worker_timer.stop()
    studio.window.close()


def test_worker_table_hides_target_id_but_retains_internal_binding(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "friendly-tabs.db"))

    class Driver:
        def __init__(self, *_args):
            pass
        def inventory(self):
            return [{"target_id": "secret-live-id", "strategies": [], "error": ""},
                    {"target_id": "secret-new-id", "strategies": [], "error": ""}]

    studio._safe_worker_targets.add("secret-new-id")
    monkeypatch.setattr(app_module, "GncZihinDriver", Driver)
    studio.discover_targets()
    assert studio.worker_table.item(0, 2).text() == "Mevcut grafik 1"
    assert studio.worker_table.item(1, 2).text() == "Çalışma sekmesi 2"
    assert studio.worker_table.item(1, 2).data(QtCore.Qt.UserRole) == "secret-new-id"
    assert "secret" not in studio.worker_table.item(1, 2).text()
    studio.worker_timer.stop()
    studio.window.close()


def test_bound_layout_without_ready_strategy_is_not_reported_as_scan_ready(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "unready-worker.db")
    project_id = store.create_project(
        "Example", 'strategy("Example")\nlength=input.int(3,"Length")')
    studio = StudioWindow(store)

    class Driver:
        def __init__(self, *_args): pass
        def inventory(self):
            return [{"target_id": "worker-1", "strategies": [{
                "id": "study-1", "name": "Example", "input_ids": ["in_0"],
                "status": {"type": 0}}], "error": None}]

    studio._safe_worker_targets.add("worker-1")
    studio._safe_worker_layouts["worker-1"] = "Unique1"
    monkeypatch.setattr(app_module, "GncZihinDriver", Driver)
    studio.worker_project.setCurrentIndex(studio.worker_project.findData(project_id))
    studio.discover_targets()
    assert studio.worker_table.item(0, 4).text() == "Example"
    assert "test raporu hazır değil" in studio.worker_table.item(0, 5).text()
    assert studio.worker_table.item(0, 0).checkState() == QtCore.Qt.Unchecked
    assert "1 ayrı layout bağlı · 0 taramaya hazır" in studio.worker_status.text()
    assert not studio.start_workers_button.isEnabled()
    studio.worker_timer.stop()
    studio.window.close()


def test_10am_version_mismatch_explained_in_plan_and_worker(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "10am-mismatch.db")
    project_id = store.create_project(
        "10AM", 'strategy("10AM")\nint startHour = input.int(10, "Hour")')
    studio = StudioWindow(store)

    class Driver:
        def __init__(self, *_args): pass
        def inventory(self):
            return [{"target_id": "worker-1", "strategies": [{
                "id": "study-1", "name": "10AM", "input_ids": ["in_0", "in_1"],
                "status": {"type": 0}}], "error": None}]

    studio._safe_worker_targets.add("worker-1")
    studio._safe_worker_layouts["worker-1"] = "Unique1"
    monkeypatch.setattr(app_module, "GncZihinDriver", Driver)
    studio.refresh_project_selectors()
    studio.worker_project.setCurrentIndex(studio.worker_project.findData(project_id))
    studio.discover_targets()
    assert "projede 1, grafikte 2 input" in studio.worker_table.item(0, 5).text()
    assert studio.worker_table.item(0, 0).checkState() == QtCore.Qt.Unchecked
    studio.discover_plan_strategies()
    assert studio.strategy_picker.currentData() is None
    assert "projede 1 input, grafikte 2 input" in studio.plan_status.text()
    assert not studio.enqueue_plan_button.isEnabled()
    studio.worker_timer.stop()
    studio.window.close()


def test_worker_discovery_keeps_target_project_assignments(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "assignments.db")
    first = store.create_project("First", 'strategy("First")')
    second = store.create_project("Second", 'strategy("Second")')
    studio = StudioWindow(store)
    class Driver:
        def __init__(self, *_args): pass
        def inventory(self):
            return [{"target_id": "worker-1", "strategies": [], "error": ""},
                    {"target_id": "worker-2", "strategies": [], "error": ""}]
    monkeypatch.setattr(app_module, "GncZihinDriver", Driver)
    studio.discover_targets()
    studio.worker_table.cellWidget(0, 3).setCurrentIndex(
        studio.worker_table.cellWidget(0, 3).findData(second))
    studio.worker_table.cellWidget(1, 3).setCurrentIndex(
        studio.worker_table.cellWidget(1, 3).findData(first))
    studio.discover_targets()
    assert studio.worker_table.cellWidget(0, 3).currentData() == second
    assert studio.worker_table.cellWidget(1, 3).currentData() == first
    studio.worker_timer.stop()
    studio.window.close()


def test_manual_worker_layout_claim_requires_confirmation_and_distinct_ids(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "manual-layouts.db"))
    tabs = [
        {"id": "original", "url": "https://www.tradingview.com/chart/Coding/"},
        {"id": "worker-1", "url": "https://www.tradingview.com/chart/Unique1/"},
        {"id": "worker-2", "url": "https://www.tradingview.com/chart/Unique2/"},
    ]
    class Driver:
        def __init__(self, *_args): pass
        def layout_name(self, target_id):
            return {"original": "Coding", "worker-1": "TV Scan Worker 1",
                    "worker-2": "TV Scan Worker 2"}[target_id]

    monkeypatch.setattr(app_module, "GncZihinDriver", Driver)
    monkeypatch.setattr(app_module, "cdp_healthy", lambda port: port == 9222)
    monkeypatch.setattr(app_module, "chart_targets", lambda **_kwargs: tabs)
    monkeypatch.setattr(studio, "discover_targets", lambda: None)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_args: QtWidgets.QMessageBox.No)
    studio.claim_worker_layouts()
    assert not studio._safe_worker_targets
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *_args: QtWidgets.QMessageBox.Yes)
    studio.claim_worker_layouts()
    assert studio._safe_worker_layouts == {"worker-1": "Unique1", "worker-2": "Unique2"}
    assert "original" not in studio._safe_worker_targets
    studio.worker_timer.stop()
    studio.window.close()


def test_claimed_worker_layout_is_rechecked_before_each_task(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "layout-guard.db"))
    studio._safe_worker_layouts["worker-1"] = "Unique1"
    class Driver:
        def __init__(self): self.name = "TV Scan Worker 1"
        def layout_name(self, _target_id): return self.name
        def replay_active(self, _target_id): return self.replay
    studio.driver = Driver()
    studio.driver.replay = False
    tabs = [{"id": "worker-1", "url": "https://www.tradingview.com/chart/Unique1/"}]
    monkeypatch.setattr(app_module, "chart_targets", lambda **_kwargs: tabs)
    studio._guard_worker_layout("worker-1")
    studio.driver.replay = True
    with pytest.raises(ValueError, match="Bar Replay açık"):
        studio._guard_worker_layout("worker-1")
    studio.driver.replay = False
    studio.driver.name = "Coding"
    with pytest.raises(ValueError, match="değişti"):
        studio._guard_worker_layout("worker-1")
    studio.driver.name = "TV Scan Worker 1"
    tabs.append({"id": "other", "url": "https://www.tradingview.com/chart/Unique1/"})
    with pytest.raises(ValueError, match="benzersiz"):
        studio._guard_worker_layout("worker-1")
    studio.worker_timer.stop()
    studio.window.close()


def test_worker_assignment_guard_rechecks_confirmed_study_before_chart_action(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "study-guard.db")
    project_id = store.create_project("Guard", 'strategy("Guard")\nlength=input.int(3,"Length")')
    store.save_settings(project_id, {"tradingview_identity": {
        "pine_id": "USER;confirmed", "pine_hash": store.project(project_id)["pine_hash"],
        "input_ids": ["in_0", "in_150"], "user_source_confirmed": True}})
    studio = StudioWindow(store)
    studio._safe_worker_layouts["worker-1"] = "Unique1"
    strategy = {"id": "study-1", "name": "Guard", "pine_id": "USER;confirmed",
                "input_ids": ["in_0", "in_150"]}
    class Driver:
        def layout_name(self, _target_id): return "TV Scan Worker 1"
        def replay_active(self, _target_id): return False
        def strategies(self, _target_id): return [strategy]
    studio.driver = Driver()
    monkeypatch.setattr(app_module, "chart_targets", lambda **_kwargs: [
        {"id": "worker-1", "url": "https://www.tradingview.com/chart/Unique1/"}])
    assignment = WorkerAssignment(1, "worker-1", (project_id,), "study-1")
    studio._guard_worker_assignment(assignment)
    strategy["input_ids"] = ["in_0", "in_151"]
    with pytest.raises(ValueError, match="strateji/input kimliği değişti"):
        studio._guard_worker_assignment(assignment)
    studio.worker_timer.stop()
    studio.window.close()


def test_two_worker_guards_keep_project_and_target_identity_separate(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "two-study-guards.db")
    projects = [store.create_project(name, f'strategy("{name}")\nlength=input.int(3,"Length")')
                for name in ("First", "Second")]
    names = {"target-1": "TV Scan Worker 1", "target-2": "TV Scan Worker 2"}
    chart_ids = {"target-1": "Unique1", "target-2": "Unique2"}
    strategies = {}
    for index, project_id in enumerate(projects, 1):
        target = f"target-{index}"
        store.save_settings(project_id, {"tradingview_identity": {
            "pine_id": f"USER;{index}", "pine_hash": store.project(project_id)["pine_hash"],
            "input_ids": ["in_0"], "user_source_confirmed": True}})
        strategies[target] = [{"id": f"study-{index}", "name": ("First", "Second")[index - 1],
                               "pine_id": f"USER;{index}", "input_ids": ["in_0"]}]
    studio = StudioWindow(store)
    studio._safe_worker_layouts.update(chart_ids)
    class Driver:
        def layout_name(self, target): return names[target]
        def replay_active(self, _target): return False
        def strategies(self, target): return strategies[target]
    studio.driver = Driver()
    monkeypatch.setattr(app_module, "chart_targets", lambda **_kwargs: [
        {"id": target, "url": f"https://www.tradingview.com/chart/{chart}/"}
        for target, chart in chart_ids.items()])
    guard = studio._worker_target_guard([
        WorkerAssignment(1, "target-1", (projects[0],), "study-1"),
        WorkerAssignment(2, "target-2", (projects[1],), "study-2"),
    ])
    guard("target-1"); guard("target-2")
    strategies["target-2"][0]["input_ids"] = ["in_0", "in_1"]
    guard("target-1")
    with pytest.raises(ValueError, match="strateji/input kimliği değişti"):
        guard("target-2")
    with pytest.raises(ValueError, match="atanmamış"):
        guard("target-3")
    studio.worker_timer.stop()
    studio.window.close()


def test_running_workers_cannot_be_started_again(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "already-running.db"))
    studio.driver = object()
    studio.supervisor = type("Running", (), {"running": True})()
    studio.start_workers()
    assert "zaten çalışıyor" in studio.worker_status.text()
    studio.worker_timer.stop()
    studio.window.close()


def test_strategy_picker_uses_name_symbol_timeframe_not_target_id(tmp_path, monkeypatch):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "strategy-picker.db")
    project_id = store.create_project("Friendly", 'strategy("Friendly")\nlength=input.int(3,"Length")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.symbols.setText("OANDA:DE30EUR")
    studio.timeframes.setText("15")

    class Driver:
        def __init__(self, *_args):
            pass
        def inventory(self):
            return [{"target_id": "secret-target", "strategies": [{
                "id": "secret-study", "pine_id": "pine-1", "name": "Friendly", "input_ids": ["in_0"],
                "status": {"type": 2}}]}]
        def snapshot(self, *_args):
            return SimpleNamespace(symbol="OANDA:DE30EUR", timeframe="15")

    monkeypatch.setattr(app_module, "GncZihinDriver", Driver)
    studio.discover_plan_strategies()
    assert studio.strategy_picker.count() == 2
    label = studio.strategy_picker.itemText(1)
    assert "Friendly" in label and "OANDA:DE30EUR" in label and "15" in label
    assert "kaynak onayı gerekli" in label
    assert "secret" not in label
    assert studio.strategy_picker.itemData(1) == {
        "study_id": "secret-study", "target_id": "secret-target", "source_confirmed": False}
    assert "yapısal eşleşme" in studio.scan_flow_status.text()
    assert "kaynak onayı worker ekranında gerekli" in studio.plan_status.text()
    store.save_settings(project_id, {"tradingview_identity": {
        "pine_id": "pine-1", "name": "Friendly", "input_ids": ["in_0"],
        "pine_hash": store.project(project_id)["pine_hash"],
        "user_source_confirmed": True,
    }})
    studio.discover_plan_strategies()
    assert studio.strategy_picker.itemData(1)["source_confirmed"] is True
    assert "kaynak onaylı" in studio.strategy_picker.itemText(1)
    assert "kaynak onaylı" in studio.scan_flow_status.text()
    studio.worker_timer.stop()
    studio.window.close()


@pytest.mark.parametrize("unreadable", ["error", "empty"])
def test_strategy_picker_rejects_unreadable_chart_context(tmp_path, monkeypatch, unreadable):
    from tv_scan_studio import app as app_module

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    store = Store(tmp_path / "unreadable-strategy.db")
    store.create_project("Friendly", 'strategy("Friendly")\nlength=input.int(3,"Length")')
    studio = StudioWindow(store)
    studio.refresh_project_selectors()
    studio.symbols.setText("OANDA:DE30EUR")
    studio.timeframes.setText("15")

    class Driver:
        def __init__(self, *_args):
            pass

        def inventory(self):
            return [{"target_id": "worker-tab", "strategies": [{
                "id": "study-1", "name": "Friendly", "input_ids": ["in_0"],
                "status": {"type": 2},
            }]}]

        def snapshot(self, *_args):
            if unreadable == "error":
                raise RuntimeError("snapshot unavailable")
            return SimpleNamespace(symbol="", timeframe="15")

    monkeypatch.setattr(app_module, "GncZihinDriver", Driver)
    studio.discover_plan_strategies()
    assert studio.strategy_picker.count() == 1
    assert studio.strategy_picker.currentData() is None
    assert studio.study_id.text() == ""
    assert not studio.enqueue_plan_button.isEnabled()
    assert "sembol/zaman dilimi okunamadı" in studio.plan_status.text()
    studio.worker_timer.stop()
    studio.window.close()


def test_result_detail_exposes_saved_interactive_views(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "details.db"))
    row = {"task_id": 10, "task_key": "test-task", "payload": {"inputs": {}},
           "classification": "hassas", "metrics": {
               "equity_curve": [{"time": 1_700_000_000_000, "equity": 100, "drawdown": 0},
                                {"time": 1_700_086_400_000, "equity": 110, "drawdown": 2}],
               "daily_pnl": {"2026-09-01": 10}, "hourly_pnl": {"09:00": 10},
               "weekday_pnl": {"Tuesday": 10}, "session_pnl": {"NY": 10},
               "long_short": {"long": {"net_profit": 10}},
           }}
    studio._result_by_id = {10: row}
    monkeypatch.setattr(studio.store, "results", lambda *_args: [row])
    studio.window.show()
    studio.open_result_details_by_id(10)
    tabs = studio.result_detail_dock.findChild(QtWidgets.QTabWidget)
    tab_names = [tabs.tabText(index) for index in range(tabs.count())]
    assert {"Equity ve DD", "Günlük takvim", "Saat", "Haftanın günü", "Session",
            "İşlem profili", "Input hassasiyeti"}.issubset(tab_names)
    assert not studio.result_detail_dock.isHidden()
    studio.result_detail_expand.click()
    assert studio.result_detail_dock.isFloating()
    assert studio.result_detail_dock.width() >= 800
    assert studio.result_detail_expand.text() == "Yan panele dön"
    studio.result_detail_expand.click()
    assert not studio.result_detail_dock.isFloating()
    studio._show_page(0)
    assert studio.result_detail_dock.isHidden()
    studio.worker_timer.stop()
    studio.window.close()


def test_result_detail_labels_closed_trade_curve_as_reconstruction(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "closed-curve.db"))
    row = {"task_id": 11, "task_key": "closed-trades", "payload": {"inputs": {}},
           "classification": "hassas", "metrics": {
               "equity_curve": [],
               "closed_trade_equity_curve": [
                   {"time": 1_700_000_000_000, "equity": 100, "drawdown": 0},
                   {"time": 1_700_000_060_000, "equity": 95, "drawdown": 5},
               ]}}
    studio._result_by_id = {11: row}
    monkeypatch.setattr(studio.store, "results", lambda *_args: [row])
    studio.open_result_details_by_id(11)
    tabs = studio.result_detail_dock.findChild(QtWidgets.QTabWidget)
    assert tabs.tabText(0) == "Kapanış eğrisi"
    chart = tabs.widget(0).findChild(CurveChart)
    assert len(chart.points) == 2
    assert chart.closed_trade_only
    assert chart._area().left() >= 106
    assert "Kapanmış işlem" in chart.accessibleName()
    labels = tabs.widget(0).findChildren(QtWidgets.QLabel)
    assert any("Açık pozisyonu" in label.text() for label in labels)
    studio.worker_timer.stop()
    studio.window.close()


def test_result_detail_discloses_partial_cost_evidence(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "cost-evidence-detail.db"))
    row = {"task_id": 11, "task_key": "cost-task", "payload": {
        "inputs": {}, "costs": {"assumptions": {"commission_value": 0.01}}},
        "evidence": {"cost_verification_scope": "strategy_properties_scalars_only"},
        "classification": "hassas", "metrics": {}}
    studio._result_by_id = {11: row}
    studio.open_result_details_by_id(11)
    labels = [item.text() for item in studio.result_detail_dock.findChildren(QtWidgets.QLabel)]
    assert any("komisyon türü ve spread etkisi" in text for text in labels)
    studio.worker_timer.stop()
    studio.window.close()


def test_small_window_keeps_scan_actions_in_view(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "small.db"))
    studio.window.resize(1280, 720)
    studio.window.show()
    studio._show_page(2)
    application.processEvents()
    assert studio.window.width() == 1280
    assert studio.window.height() == 720
    position = studio.enqueue_plan_button.mapTo(studio.window, studio.enqueue_plan_button.rect().center())
    assert studio.window.rect().contains(position)
    status_bottom = studio.plan_status.mapTo(studio.window, studio.plan_status.rect().bottomLeft()).y()
    button_top = studio.enqueue_plan_button.mapTo(studio.window, studio.enqueue_plan_button.rect().topLeft()).y()
    assert status_bottom < button_top
    studio.worker_timer.stop()
    studio.window.close()


def test_desktop_reopen_recovers_only_interrupted_tasks(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    database = tmp_path / "restart.db"
    store = Store(database)
    project = store.create_project("Resume", 'strategy("Resume")')
    for index in range(3):
        store.enqueue(project, f"restart-{index}", {"symbol": "OANDA:DE30EUR"})
    interrupted = store.claim_next(1)
    completed = store.claim_next(2)
    store.complete(completed.id, 2, {"trades": 80, "profit_factor": 1.5},
                   "hassas", verified=True)

    first = StudioWindow(Store(database))
    assert first.store.counts(project) == {"done": 1, "pending": 2}
    first.worker_timer.stop()
    first.window.close()

    reopened = StudioWindow(Store(database))
    assert reopened.store.counts(project) == {"done": 1, "pending": 2}
    rows = reopened.store.tasks(project_id=project)
    assert len({row["id"] for row in rows}) == 3
    assert any(row["id"] == interrupted.id and row["status"] == "pending" for row in rows)
    assert any(row["id"] == completed.id and row["status"] == "done" for row in rows)
    reopened.worker_timer.stop()
    reopened.window.close()
