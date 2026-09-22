"""TV Scan Studio desktop application."""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .pine import parse_strategy_inputs
from .planner import ScanPlan, enqueue_plan
from .export import export_results_csv
from .backup import create_backup, verify_backup
from .resources import project_worker_throughput, recommend_workers, system_snapshot
from .supervisor import WorkerAssignment, WorkerSupervisor
from .tradingview import GncZihinDriver
from .windows import cdp_healthy, find_tradingview_executables, launch_with_cdp
from .storage import Store
from .scan_values import parse_scan_values
from .profiles import COST_SCENARIOS, FTMO_SYMBOL_PROFILES, apply_cost_multiplier


STYLE = """
QWidget { background:#0b1424; color:#dbe7f7; font-family:'Segoe UI'; font-size:13px; }
QMainWindow { background:#0b1424; }
#rail { background:#101d31; border-right:1px solid #233754; }
#brand { color:#f4f8ff; font-size:20px; font-weight:700; padding:18px 14px; }
#tagline { color:#7390b3; padding:0 14px 20px 14px; }
QPushButton[nav='true'] { text-align:left; padding:11px 14px; border:0; border-left:3px solid transparent; color:#9fb4ce; }
QPushButton[nav='true']:checked { background:#162842; border-left-color:#4ca6ff; color:#ffffff; }
QPushButton[nav='true']:hover { background:#14243b; color:#ffffff; }
QPushButton#primary { background:#1683e6; color:white; border:0; border-radius:4px; padding:9px 18px; font-weight:600; }
QPushButton#primary:hover { background:#2997f2; }
QLineEdit,QPlainTextEdit,QTableWidget,QComboBox,QSpinBox,QDoubleSpinBox { background:#0f1b2e; border:1px solid #29405f; border-radius:4px; padding:7px; selection-background-color:#1f75bd; }
QLineEdit:focus,QPlainTextEdit:focus { border-color:#4ca6ff; }
QHeaderView::section { background:#14243b; color:#8fa8c5; border:0; border-bottom:1px solid #29405f; padding:8px; }
QTableWidget { gridline-color:#1e314b; }
#title { font-size:26px; font-weight:700; color:#f5f8fc; }
#subtitle { color:#8099b8; font-size:14px; }
#metric { background:#101d31; border-top:3px solid #294e73; padding:18px; font-size:22px; font-weight:700; }
#metricLabel { color:#8099b8; font-size:12px; }
#status { color:#79c7ff; padding:8px 0; }
"""


def data_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TVScanStudio"
    return base / "studio.db"


class StudioWindow:
    def __init__(self, store: Store):
        self.QtWidgets = QtWidgets
        self.store = store
        self.store.recover_interrupted()
        self.supervisor = None
        self.driver = None
        self.window = QtWidgets.QMainWindow()
        self.window.setWindowTitle("TV Scan Studio")
        self.window.resize(1240, 780)
        self._last_dashboard_counts = None
        self._notified_worker_errors = set()
        self.tray = QtWidgets.QSystemTrayIcon(
            self.window.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon), self.window
        )
        self.tray.setToolTip("TV Scan Studio")
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        root = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._rail(), 0)
        self.pages = QtWidgets.QStackedWidget()
        self.dashboard = self._dashboard_page()
        self.new_project = self._new_project_page()
        self.scan_setup = self._scan_setup_page()
        self.workers_page = self._workers_page()
        self.results_page = self._results_page()
        self.pages.addWidget(self.dashboard)
        self.pages.addWidget(self.new_project)
        self.pages.addWidget(self.scan_setup)
        self.pages.addWidget(self.workers_page)
        self.pages.addWidget(self.results_page)
        layout.addWidget(self.pages, 1)
        self.window.setCentralWidget(root)
        self.worker_timer = QtCore.QTimer(self.window)
        self.worker_timer.timeout.connect(self.refresh_worker_states)
        self.worker_timer.start(1000)
        self.refresh_dashboard()

    def _rail(self):
        Q = self.QtWidgets
        rail = Q.QFrame(objectName="rail")
        rail.setFixedWidth(224)
        box = Q.QVBoxLayout(rail)
        box.setContentsMargins(0, 0, 0, 16)
        box.addWidget(Q.QLabel("TV Scan Studio", objectName="brand"))
        box.addWidget(Q.QLabel("Yerel strateji laboratuvarı", objectName="tagline"))
        group = Q.QButtonGroup(rail)
        group.setExclusive(True)
        for index, label in enumerate(("Tarama masası", "Yeni proje", "Tarama ayarları", "Worker dağıtımı", "Sonuçlar ve hatalar")):
            button = Q.QPushButton(label)
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _checked=False, i=index: self._show_page(i))
            group.addButton(button)
            box.addWidget(button)
        box.addStretch()
        box.addWidget(Q.QLabel("Veriler yalnızca bu bilgisayarda tutulur", objectName="tagline"))
        return rail

    def _page_header(self, title, subtitle):
        Q = self.QtWidgets
        block = Q.QWidget()
        box = Q.QVBoxLayout(block)
        box.setContentsMargins(0, 0, 0, 18)
        box.addWidget(Q.QLabel(title, objectName="title"))
        box.addWidget(Q.QLabel(subtitle, objectName="subtitle"))
        return block

    def _dashboard_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Tarama masası", "Kuyrukların ve doğrulanmış sonuçların canlı özeti"))
        metrics = Q.QHBoxLayout()
        self.metric_labels = {}
        for key, label in (("projects", "Projeler"), ("pending", "Bekleyen"), ("running", "Çalışan"), ("done", "Tamamlanan"), ("failed", "Geçersiz"), ("manual_review", "İnceleme")):
            frame = Q.QFrame(objectName="metric")
            inner = Q.QVBoxLayout(frame)
            value = Q.QLabel("0")
            value.setStyleSheet("font-size:24px;font-weight:700")
            inner.addWidget(value)
            inner.addWidget(Q.QLabel(label, objectName="metricLabel"))
            self.metric_labels[key] = value
            metrics.addWidget(frame)
        box.addLayout(metrics)
        operational = Q.QHBoxLayout()
        self.throughput_label = Q.QLabel("Hız: ölçüm bekleniyor", objectName="status")
        self.eta_label = Q.QLabel("ETA: —", objectName="status")
        self.candidate_label = Q.QLabel("Aday: 0", objectName="status")
        operational.addWidget(self.throughput_label); operational.addWidget(self.eta_label); operational.addWidget(self.candidate_label)
        operational.addStretch()
        backup = Q.QPushButton("Yedek oluştur"); backup.clicked.connect(self.create_portable_backup)
        operational.addWidget(backup)
        box.addLayout(operational)
        box.addSpacing(20)
        box.addWidget(Q.QLabel("Projeler", objectName="subtitle"))
        self.project_table = Q.QTableWidget(0, 5)
        self.project_table.setHorizontalHeaderLabels(["ID", "Proje", "Durum", "Öncelik", "Görev"])
        self.project_table.horizontalHeader().setStretchLastSection(True)
        self.project_table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.project_table.setSelectionBehavior(Q.QAbstractItemView.SelectRows)
        box.addWidget(self.project_table, 1)
        controls = Q.QHBoxLayout()
        self.project_priority = Q.QSpinBox(); self.project_priority.setRange(-100, 100); self.project_priority.setPrefix("Öncelik ")
        self.project_state = Q.QComboBox(); self.project_state.addItems(["draft", "queued", "running", "paused", "complete", "cancelled"])
        apply_project = Q.QPushButton("Projeyi güncelle"); apply_project.clicked.connect(self.update_selected_project)
        cancel = Q.QPushButton("Bekleyenleri iptal et"); cancel.clicked.connect(self.cancel_selected_project)
        retry = Q.QPushButton("Hatalıları yeniden sırala"); retry.clicked.connect(self.retry_selected_project)
        for widget in (self.project_priority, self.project_state, apply_project, cancel, retry): controls.addWidget(widget)
        controls.addStretch(); box.addLayout(controls)
        self.dashboard_status = Q.QLabel("", objectName="status"); box.addWidget(self.dashboard_status)
        return page

    def _scan_setup_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Tarama ayarları", "Kombinasyonları hesaplayın ve tekrar üretilebilir görevler oluşturun."))
        form = Q.QFormLayout()
        self.plan_project = Q.QComboBox()
        self.plan_project.currentIndexChanged.connect(self.load_plan_inputs)
        self.study_id = Q.QLineEdit(); self.study_id.setPlaceholderText("Grafikteki strategy study ID")
        self.symbols = Q.QLineEdit(); self.symbols.setPlaceholderText("OANDA:EURUSD, OANDA:GBPUSD")
        self.symbol_profile = Q.QComboBox(); self.symbol_profile.addItem("Özel")
        self.symbol_profile.addItems(FTMO_SYMBOL_PROFILES.keys())
        self.symbol_profile.currentTextChanged.connect(self.apply_symbol_profile)
        self.timeframes = Q.QLineEdit(); self.timeframes.setPlaceholderText("15, 1H")
        self.date_from = Q.QLineEdit(); self.date_from.setPlaceholderText("2025-01-01")
        self.date_to = Q.QLineEdit(); self.date_to.setPlaceholderText("2025-12-31")
        form.addRow("Proje", self.plan_project); form.addRow("Strategy ID", self.study_id)
        symbol_row = Q.QHBoxLayout(); symbol_row.addWidget(self.symbol_profile); symbol_row.addWidget(self.symbols, 1)
        form.addRow("Sembol profili", symbol_row); form.addRow("Timeframe'ler", self.timeframes)
        dates = Q.QHBoxLayout(); dates.addWidget(self.date_from); dates.addWidget(self.date_to)
        form.addRow("Tarih aralığı", dates)
        criteria = Q.QHBoxLayout()
        self.min_trades = Q.QSpinBox(); self.min_trades.setRange(0, 1_000_000); self.min_trades.setValue(60); self.min_trades.setPrefix("İşlem ≥ ")
        self.min_pf = Q.QDoubleSpinBox(); self.min_pf.setRange(0, 100); self.min_pf.setValue(1.4); self.min_pf.setPrefix("PF ≥ ")
        self.min_win = Q.QDoubleSpinBox(); self.min_win.setRange(0, 100); self.min_win.setValue(40); self.min_win.setPrefix("WR ≥ "); self.min_win.setSuffix("%")
        self.max_dd = Q.QDoubleSpinBox(); self.max_dd.setRange(0, 100); self.max_dd.setValue(5); self.max_dd.setPrefix("DD ≤ "); self.max_dd.setSuffix("%")
        self.min_net = Q.QDoubleSpinBox(); self.min_net.setRange(-1_000_000_000, 1_000_000_000); self.min_net.setPrefix("Net ≥ ")
        self.max_daily_loss = Q.QDoubleSpinBox(); self.max_daily_loss.setRange(0, 100); self.max_daily_loss.setValue(5); self.max_daily_loss.setPrefix("Günlük kayıp ≤ "); self.max_daily_loss.setSuffix("%")
        self.max_total_loss = Q.QDoubleSpinBox(); self.max_total_loss.setRange(0, 100); self.max_total_loss.setValue(10); self.max_total_loss.setPrefix("Toplam kayıp ≤ "); self.max_total_loss.setSuffix("%")
        for widget in (self.min_trades, self.min_pf, self.min_win, self.max_dd, self.min_net, self.max_daily_loss, self.max_total_loss): criteria.addWidget(widget)
        form.addRow("Başarı kriterleri", criteria)
        costs = Q.QHBoxLayout()
        self.commission = Q.QDoubleSpinBox(); self.commission.setRange(0, 100); self.commission.setDecimals(4); self.commission.setPrefix("Komisyon % ")
        self.slippage = Q.QSpinBox(); self.slippage.setRange(0, 10000); self.slippage.setPrefix("Slippage tick ")
        self.spread = Q.QDoubleSpinBox(); self.spread.setRange(0, 100000); self.spread.setDecimals(5); self.spread.setPrefix("Spread ")
        self.initial_capital = Q.QDoubleSpinBox(); self.initial_capital.setRange(1, 1_000_000_000); self.initial_capital.setValue(100000); self.initial_capital.setPrefix("Sermaye ")
        self.position_size = Q.QDoubleSpinBox(); self.position_size.setRange(0.00001, 1_000_000_000); self.position_size.setValue(1); self.position_size.setPrefix("Pozisyon ")
        self.risk_value = Q.QDoubleSpinBox(); self.risk_value.setRange(0, 1_000_000_000); self.risk_value.setValue(1); self.risk_value.setPrefix("Risk ")
        self.risk_mode = Q.QComboBox(); self.risk_mode.addItems(["yüzde", "sabit"])
        self.cost_scenario = Q.QComboBox(); self.cost_scenario.addItems(COST_SCENARIOS.keys())
        for widget in (self.initial_capital, self.position_size, self.commission, self.spread, self.slippage, self.risk_mode, self.risk_value, self.cost_scenario): costs.addWidget(widget)
        form.addRow("TradingView maliyetleri", costs)
        cost_ids = Q.QHBoxLayout()
        self.capital_input_id = Q.QLineEdit(); self.capital_input_id.setPlaceholderText("Sermaye in_N (opsiyonel)")
        self.commission_input_id = Q.QLineEdit(); self.commission_input_id.setPlaceholderText("Komisyon in_N (opsiyonel)")
        self.slippage_input_id = Q.QLineEdit(); self.slippage_input_id.setPlaceholderText("Slippage in_N (opsiyonel)")
        for widget in (self.capital_input_id, self.commission_input_id, self.slippage_input_id): cost_ids.addWidget(widget)
        form.addRow("Maliyet input eşlemesi", cost_ids)
        box.addLayout(form)
        box.addWidget(Q.QLabel("Input değerleri", objectName="subtitle"))
        self.plan_inputs = Q.QTableWidget(0, 6)
        self.plan_inputs.setHorizontalHeaderLabels(["TradingView ID", "Pine değişkeni", "Başlık", "Tür", "Liste/aralık JSON veya exclude", "Durum"])
        self.plan_inputs.horizontalHeader().setStretchLastSection(True)
        self.plan_inputs.itemChanged.connect(self.preview_plan)
        box.addWidget(self.plan_inputs, 1)
        actions = Q.QHBoxLayout()
        preview = Q.QPushButton("Hesapla", objectName="primary"); preview.clicked.connect(self.preview_plan)
        enqueue = Q.QPushButton("Görevleri kuyruğa ekle", objectName="primary"); enqueue.clicked.connect(self.enqueue_current_plan)
        actions.addWidget(preview); actions.addWidget(enqueue); actions.addStretch()
        self.plan_status = Q.QLabel("Bir proje seçin", objectName="status")
        actions.addWidget(self.plan_status)
        box.addLayout(actions)
        return page

    def _results_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Sonuçlar ve hatalar", "Doğrulanmış presetler ve müdahale gerektiren olaylar."))
        controls = Q.QHBoxLayout()
        self.result_project = Q.QComboBox(); self.result_project.currentIndexChanged.connect(self.refresh_results)
        self.result_filter = Q.QComboBox(); self.result_filter.addItems(["Tümü", "dayanıklı", "hassas", "elenmiş", "geçersiz"]); self.result_filter.currentIndexChanged.connect(self.refresh_results)
        export = Q.QPushButton("CSV dışa aktar", objectName="primary"); export.clicked.connect(self.export_current_results)
        compare = Q.QPushButton("Seçilenleri karşılaştır"); compare.clicked.connect(self.compare_selected_results)
        retry = Q.QPushButton("Hatalıları yeniden sırala"); retry.clicked.connect(self.retry_result_project)
        controls.addWidget(self.result_project); controls.addWidget(self.result_filter); controls.addWidget(export); controls.addWidget(compare); controls.addWidget(retry); controls.addStretch()
        box.addLayout(controls)
        self.results_table = Q.QTableWidget(0, 7)
        self.results_table.setHorizontalHeaderLabels(["Görev", "Sembol", "TF", "Sınıf", "İşlem", "PF", "Maks. DD"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionBehavior(Q.QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(Q.QAbstractItemView.ExtendedSelection)
        box.addWidget(self.results_table, 2)
        box.addWidget(Q.QLabel("Son olaylar", objectName="subtitle"))
        self.events_table = Q.QTableWidget(0, 5)
        self.events_table.setHorizontalHeaderLabels(["Seviye", "Worker", "Görev", "Mesaj", "Ekran görüntüsü"])
        self.events_table.horizontalHeader().setStretchLastSection(True)
        self.events_table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        box.addWidget(self.events_table, 1)
        return page

    def _workers_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Worker dağıtımı", "Her worker ayrı TradingView chart penceresine bağlanır."))
        form = Q.QFormLayout()
        self.motor_path = Q.QLineEdit()
        self.motor_path.setPlaceholderText("Boş bırakılırsa paket içindeki gnc-zihin CDP köprüsü kullanılır")
        self.tv_executable = Q.QLineEdit(); self.tv_executable.setPlaceholderText("TradingView.exe yolu")
        self.worker_project = Q.QComboBox()
        tv_row = Q.QHBoxLayout(); tv_row.addWidget(self.tv_executable)
        find_tv = Q.QPushButton("Bul"); find_tv.clicked.connect(self.find_tradingview); tv_row.addWidget(find_tv)
        open_tv = Q.QPushButton("CDP ile aç"); open_tv.clicked.connect(self.open_tradingview); tv_row.addWidget(open_tv)
        form.addRow("TradingView Desktop", tv_row)
        form.addRow("gnc-zihin motoru", self.motor_path)
        form.addRow("Atanacak proje", self.worker_project)
        box.addLayout(form)
        resource_row = Q.QHBoxLayout()
        self.resource_status = Q.QLabel("Kaynak ölçümü yapılmadı", objectName="status")
        measure = Q.QPushButton("Kaynakları ölç"); measure.clicked.connect(self.measure_resources)
        resource_row.addWidget(measure); resource_row.addWidget(self.resource_status); resource_row.addStretch()
        box.addLayout(resource_row)
        note = Q.QLabel("TradingView Desktop CDP 9222 ile açık olmalı. Her seçili satır farklı bir chart target olmalıdır.")
        note.setWordWrap(True); note.setObjectName("subtitle"); box.addWidget(note)
        self.worker_table = Q.QTableWidget(0, 6)
        self.worker_table.setHorizontalHeaderLabels(["Kullan", "Worker", "Target", "Strategy ID", "Durum", "Tamamlanan"])
        self.worker_table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.worker_table, 1)
        actions = Q.QHBoxLayout()
        discover = Q.QPushButton("Targetları bul", objectName="primary"); discover.clicked.connect(self.discover_targets)
        start = Q.QPushButton("Workerları başlat", objectName="primary"); start.clicked.connect(self.start_workers)
        stop = Q.QPushButton("Durdur"); stop.clicked.connect(self.stop_workers)
        actions.addWidget(discover); actions.addWidget(start); actions.addWidget(stop); actions.addStretch()
        self.worker_status = Q.QLabel("Bağlantı kontrol edilmedi", objectName="status"); actions.addWidget(self.worker_status)
        box.addLayout(actions)
        return page

    def find_tradingview(self):
        found = find_tradingview_executables()
        if found:
            self.tv_executable.setText(str(found[0]))
            self.worker_status.setText(f"TradingView bulundu · CDP {'hazır' if cdp_healthy() else 'kapalı'}")
        else:
            path, _ = self.QtWidgets.QFileDialog.getOpenFileName(self.window, "TradingView.exe seç", "", "Uygulama (*.exe)")
            if path: self.tv_executable.setText(path)

    def open_tradingview(self):
        try:
            launch_with_cdp(self.tv_executable.text().strip())
            self.worker_status.setText("TradingView CDP ile başlatıldı; bağlantı hazırlanıyor")
        except Exception as exc:
            self.worker_status.setStyleSheet("color:#ff8e8e"); self.worker_status.setText(str(exc))

    def _new_project_page(self):
        Q = self.QtWidgets
        page = Q.QWidget()
        box = Q.QVBoxLayout(page)
        box.setContentsMargins(34, 28, 34, 28)
        box.addWidget(self._page_header("Yeni tarama projesi", "Pine strategy kodunu analiz edin; inputlar kaydetmeden önce görünür."))
        self.project_name = Q.QLineEdit()
        self.project_name.setPlaceholderText("Proje adı")
        box.addWidget(self.project_name)
        self.pine_source = Q.QPlainTextEdit()
        self.pine_source.setPlaceholderText('//@version=6\nstrategy("Stratejim")\nlength = input.int(20, "Length")')
        self.pine_source.setMinimumHeight(230)
        box.addWidget(self.pine_source)
        controls = Q.QHBoxLayout()
        analyze = Q.QPushButton("Inputları analiz et", objectName="primary")
        analyze.clicked.connect(self.analyze_source)
        save = Q.QPushButton("Projeyi kaydet", objectName="primary")
        save.clicked.connect(self.save_project)
        controls.addWidget(analyze)
        controls.addWidget(save)
        controls.addStretch()
        box.addLayout(controls)
        self.project_status = Q.QLabel("Pine kodu bekleniyor", objectName="status")
        box.addWidget(self.project_status)
        self.input_table = Q.QTableWidget(0, 6)
        self.input_table.setHorizontalHeaderLabels(["Değişken", "Başlık", "Tür", "Varsayılan", "Seçenekler", "Durum"])
        self.input_table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.input_table, 1)
        return page

    def _show_page(self, index):
        self.pages.setCurrentIndex(index)
        if index == 0:
            self.refresh_dashboard()
        elif index == 2:
            self.refresh_project_selectors()
        elif index == 3:
            self.refresh_project_selectors()
        elif index == 4:
            self.refresh_project_selectors(); self.refresh_results()

    def analyze_source(self):
        Q = self.QtWidgets
        try:
            inputs = parse_strategy_inputs(self.pine_source.toPlainText())
        except ValueError as exc:
            self.project_status.setText(str(exc))
            self.project_status.setStyleSheet("color:#ff8e8e")
            return
        self.input_table.setRowCount(len(inputs))
        for row, item in enumerate(inputs):
            values = (item.variable, item.title, item.kind, repr(item.default), repr(item.options or ""), "Manuel tanım" if item.manual_definition_required else "Hazır")
            for column, value in enumerate(values):
                self.input_table.setItem(row, column, Q.QTableWidgetItem(str(value)))
        self.project_status.setStyleSheet("color:#79c7ff")
        self.project_status.setText(f"{len(inputs)} input bulundu")
        return inputs

    def save_project(self):
        name = self.project_name.text().strip()
        source = self.pine_source.toPlainText()
        if not name:
            self.project_status.setText("Proje adı gerekli")
            self.project_status.setStyleSheet("color:#ff8e8e")
            return
        try:
            self.analyze_source()
            parse_strategy_inputs(source)
        except ValueError:
            return
        project_id = self.store.create_project(name, source)
        self.project_status.setStyleSheet("color:#64d6a1")
        self.project_status.setText(f"Proje kaydedildi · #{project_id}")
        self.refresh_dashboard()
        self.refresh_project_selectors()

    def refresh_project_selectors(self):
        projects = self.store.projects()
        for combo in (self.plan_project, self.result_project, self.worker_project):
            current = combo.currentData()
            combo.blockSignals(True); combo.clear()
            for project in projects: combo.addItem(project["name"], project["id"])
            index = combo.findData(current)
            if index >= 0: combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self.load_plan_inputs()

    def discover_targets(self):
        try:
            self.driver = GncZihinDriver(self.motor_path.text().strip())
            inventory = self.driver.inventory()
            self.worker_table.setRowCount(len(inventory))
            ready_count = 0
            for row, item in enumerate(inventory):
                target = item["target_id"]
                enabled = self.QtWidgets.QTableWidgetItem()
                enabled.setFlags(enabled.flags() | QtCore.Qt.ItemIsUserCheckable)
                ready = [strategy for strategy in item["strategies"]
                         if (strategy.get("status") or {}).get("type") == 2]
                enabled.setCheckState(QtCore.Qt.Checked if len(ready) == 1 else QtCore.Qt.Unchecked)
                self.worker_table.setItem(row, 0, enabled)
                strategy_id = ready[0].get("id", "") if len(ready) == 1 else ""
                status = "hazır" if strategy_id else (item["error"] or "hazır strategy seçin")
                if strategy_id: ready_count += 1
                for column, value in enumerate((row + 1, target, strategy_id, status, 0), start=1):
                    self.worker_table.setItem(row, column, self.QtWidgets.QTableWidgetItem(str(value)))
            color = "#64d6a1" if ready_count >= 2 else "#f1bc60"
            self.worker_status.setStyleSheet(f"color:{color}")
            self.worker_status.setText(f"{len(inventory)} target · {ready_count} hazır worker adayı")
        except Exception as exc:
            self.worker_status.setStyleSheet("color:#ff8e8e"); self.worker_status.setText(str(exc))

    def start_workers(self):
        try:
            project_id = self.worker_project.currentData()
            if project_id is None: raise ValueError("Worker için proje seçilmedi.")
            if self.driver is None: raise ValueError("Önce targetları bulun.")
            assignments = []
            for row in range(self.worker_table.rowCount()):
                if self.worker_table.item(row, 0).checkState() == QtCore.Qt.Checked:
                    assignments.append(WorkerAssignment(
                        int(self.worker_table.item(row, 1).text()),
                        self.worker_table.item(row, 2).text(), (project_id,),
                        self.worker_table.item(row, 3).text().strip() or None,
                    ))
            if not assignments: raise ValueError("En az bir worker seçin.")
            self.supervisor = WorkerSupervisor(self.store, self.driver)
            self.supervisor.start(assignments)
            self.worker_status.setStyleSheet("color:#64d6a1")
            self.worker_status.setText(f"{len(assignments)} worker çalışıyor")
        except Exception as exc:
            self.worker_status.setStyleSheet("color:#ff8e8e"); self.worker_status.setText(str(exc))

    def stop_workers(self):
        if self.supervisor and self.supervisor.running:
            self.supervisor.stop()
            if hasattr(self, "worker_status"): self.worker_status.setText("Workerlar durduruldu")

    def refresh_worker_states(self):
        if not self.supervisor: return
        for row in range(self.worker_table.rowCount()):
            worker_id = int(self.worker_table.item(row, 1).text())
            state = self.supervisor.states.get(worker_id)
            if state:
                self.worker_table.item(row, 4).setText(state.status)
                self.worker_table.item(row, 5).setText(str(state.completed))
                if state.status == "failed" and worker_id not in self._notified_worker_errors:
                    self._notified_worker_errors.add(worker_id)
                    self.notify("Worker müdahalesi gerekiyor", f"Worker {worker_id}: {state.error or 'bilinmeyen hata'}")
        self.refresh_dashboard()

    def load_plan_inputs(self):
        project_id = self.plan_project.currentData()
        project = self.store.project(project_id) if project_id is not None else None
        if not project: self.plan_inputs.setRowCount(0); return
        inputs = parse_strategy_inputs(project["pine_source"])
        self.plan_inputs.blockSignals(True); self.plan_inputs.setRowCount(len(inputs))
        for row, item in enumerate(inputs):
            scan_values = [] if item.manual_definition_required else [item.default]
            values = (f"in_{row}", item.variable, item.title, item.kind,
                      json.dumps(scan_values, ensure_ascii=False),
                      "Manuel değer gerekli" if item.manual_definition_required else "Hazır")
            for column, value in enumerate(values):
                cell = self.QtWidgets.QTableWidgetItem(str(value))
                if column != 4: cell.setFlags(cell.flags() & ~QtCore.Qt.ItemIsEditable)
                self.plan_inputs.setItem(row, column, cell)
        self.plan_inputs.blockSignals(False); self.preview_plan()

    def apply_symbol_profile(self, name):
        profile = FTMO_SYMBOL_PROFILES.get(name)
        if profile:
            self.symbols.setText(", ".join(profile))
            self.preview_plan()

    def _current_plan(self):
        values = {}
        for row in range(self.plan_inputs.rowCount()):
            key = self.plan_inputs.item(row, 0).text()
            raw = self.plan_inputs.item(row, 4).text().strip()
            parsed = "exclude" if raw.lower() == "exclude" else json.loads(raw)
            expanded = parse_scan_values(parsed)
            if expanded is not None:
                values[key] = expanded
        split = lambda text: tuple(value.strip() for value in text.split(",") if value.strip())
        date_range = {}
        if self.date_from.text().strip(): date_range["from"] = self.date_from.text().strip()
        if self.date_to.text().strip(): date_range["to"] = self.date_to.text().strip()
        multiplier = COST_SCENARIOS[self.cost_scenario.currentText()]
        scenario_costs = apply_cost_multiplier(
            self.commission.value(), self.spread.value(), self.slippage.value(), multiplier
        )
        assumptions = {"initial_capital": self.initial_capital.value(),
                       "position_size": self.position_size.value(),
                       "risk_mode": self.risk_mode.currentText(), "risk_value": self.risk_value.value(),
                       "scenario": self.cost_scenario.currentText(), **scenario_costs}
        tradingview_inputs = {}
        mappings = ((self.capital_input_id.text().strip(), assumptions["initial_capital"]),
                    (self.commission_input_id.text().strip(), assumptions["commission_value"]),
                    (self.slippage_input_id.text().strip(), assumptions["slippage"]))
        for input_id, value in mappings:
            if input_id:
                if not input_id.startswith("in_") or not input_id[3:].isdigit():
                    raise ValueError(f"Geçersiz maliyet input ID: {input_id}")
                tradingview_inputs[input_id] = value
        return ScanPlan(
            study_id=self.study_id.text().strip(), symbols=split(self.symbols.text()),
            timeframes=split(self.timeframes.text()), input_values=values, date_range=date_range,
            criteria={"min_trades": self.min_trades.value(), "min_profit_factor": self.min_pf.value(),
                      "min_win_rate_pct": self.min_win.value(), "max_drawdown_pct": self.max_dd.value(),
                      "min_net_profit": self.min_net.value(),
                      "max_daily_loss_pct": self.max_daily_loss.value(),
                      "max_total_loss_pct": self.max_total_loss.value()},
            costs={"assumptions": assumptions, "tradingview_inputs": tradingview_inputs},
        )

    def preview_plan(self, *_args):
        try:
            count = self._current_plan().task_count
            disk_mb = count * 2.5 / 1024
            warning = " · geniş arama/curve-fitting riski" if count > 10_000 else ""
            self.plan_status.setStyleSheet("color:#79c7ff")
            self.plan_status.setText(f"{count:,} görev · tahmini {disk_mb:.1f} MB{warning}")
        except (ValueError, json.JSONDecodeError) as exc:
            self.plan_status.setStyleSheet("color:#ff8e8e"); self.plan_status.setText(str(exc))

    def enqueue_current_plan(self):
        try:
            project_id = self.plan_project.currentData()
            if project_id is None: raise ValueError("Proje seçilmedi.")
            plan = self._current_plan()
            inserted = enqueue_plan(self.store, project_id, plan)
            self.plan_status.setStyleSheet("color:#64d6a1")
            self.plan_status.setText(f"{inserted:,} yeni görev kuyruğa eklendi · toplam {plan.task_count:,}")
            self.refresh_dashboard()
        except (ValueError, json.JSONDecodeError) as exc:
            self.plan_status.setStyleSheet("color:#ff8e8e"); self.plan_status.setText(str(exc))

    def refresh_results(self, *_args):
        project_id = self.result_project.currentData()
        classification = self.result_filter.currentText() if hasattr(self, "result_filter") else "Tümü"
        rows = self.store.results(project_id, None if classification == "Tümü" else classification) if project_id is not None else []
        self._result_rows = rows
        self.results_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            payload, metrics = row["payload"], row["metrics"]
            values = (row["task_key"][:12], payload.get("symbol"), payload.get("timeframe"), row["classification"], metrics.get("trades"), metrics.get("profit_factor"), metrics.get("max_drawdown_pct"))
            for column, value in enumerate(values): self.results_table.setItem(row_index, column, self.QtWidgets.QTableWidgetItem(str(value if value is not None else "—")))
        events = self.store.events(100)
        self.events_table.setRowCount(len(events))
        for row_index, event in enumerate(events):
            for column, value in enumerate((event["level"], event["worker_id"], event["task_id"], event["message"], event["screenshot_path"])):
                self.events_table.setItem(row_index, column, self.QtWidgets.QTableWidgetItem(str(value if value is not None else "—")))

    def compare_selected_results(self):
        selected = sorted({index.row() for index in self.results_table.selectionModel().selectedRows()})
        if len(selected) < 2:
            self.QtWidgets.QMessageBox.information(self.window, "Preset karşılaştırma", "En az iki sonuç satırı seçin.")
            return
        rows = [self._result_rows[index] for index in selected]
        metric_names = sorted({name for row in rows for name in row["metrics"]})
        dialog = self.QtWidgets.QDialog(self.window)
        dialog.setWindowTitle("Preset karşılaştırma"); dialog.resize(900, 560)
        layout = self.QtWidgets.QVBoxLayout(dialog)
        table = self.QtWidgets.QTableWidget(len(metric_names) + 3, len(rows))
        table.setHorizontalHeaderLabels([row["task_key"][:12] for row in rows])
        labels = ["Sembol", "Timeframe", "Sınıf", *metric_names]
        table.setVerticalHeaderLabels(labels)
        for column, row in enumerate(rows):
            values = [row["payload"].get("symbol"), row["payload"].get("timeframe"), row["classification"]]
            values.extend(row["metrics"].get(name, "—") for name in metric_names)
            for line, value in enumerate(values):
                table.setItem(line, column, self.QtWidgets.QTableWidgetItem(str(value)))
        table.setEditTriggers(self.QtWidgets.QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True); layout.addWidget(table)
        close = self.QtWidgets.QPushButton("Kapat"); close.clicked.connect(dialog.accept); layout.addWidget(close)
        dialog.exec()

    def export_current_results(self):
        project_id = self.result_project.currentData()
        if project_id is None: return
        classification = self.result_filter.currentText()
        rows = self.store.results(project_id, None if classification == "Tümü" else classification)
        path, _ = self.QtWidgets.QFileDialog.getSaveFileName(self.window, "CSV dışa aktar", "tv-scan-results.csv", "CSV (*.csv)")
        if path: export_results_csv(rows, path)

    def refresh_dashboard(self):
        Q = self.QtWidgets
        projects = self.store.projects()
        counts = self.store.total_counts()
        stats = self.store.dashboard_stats()
        self.metric_labels["projects"].setText(str(len(projects)))
        for key in ("pending", "running", "done", "failed", "manual_review"):
            self.metric_labels[key].setText(str(counts.get(key, 0)))
        rate = stats["tests_per_hour"]
        self.throughput_label.setText(f"Hız: {rate:,.1f} test/saat" if rate else "Hız: yeterli veri yok")
        eta = stats["eta_seconds"]
        self.eta_label.setText(f"ETA: {self._format_duration(eta)}" if eta is not None else "ETA: —")
        candidates = stats["candidates"]
        self.candidate_label.setText(
            f"Aday: {candidates.get('dayanıklı', 0) + candidates.get('hassas', 0)}"
        )
        previous = self._last_dashboard_counts
        current_candidates = candidates.get("dayanıklı", 0) + candidates.get("hassas", 0)
        if previous is not None:
            previous_candidates = previous.get("candidates", 0)
            if current_candidates > previous_candidates:
                self.notify("Yeni preset adayı", f"{current_candidates - previous_candidates} yeni aday doğrulandı.")
            previous_active = previous.get("pending", 0) + previous.get("running", 0)
            current_active = counts.get("pending", 0) + counts.get("running", 0)
            if previous_active > 0 and current_active == 0:
                self.notify("Tarama tamamlandı", f"Toplam {counts.get('done', 0)} görev tamamlandı.")
        self._last_dashboard_counts = {**counts, "candidates": current_candidates}
        self.project_table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            values = (project["id"], project["name"], project["status"], project["priority"], project["task_count"])
            for column, value in enumerate(values):
                self.project_table.setItem(row, column, Q.QTableWidgetItem(str(value)))

    @staticmethod
    def _format_duration(seconds):
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return f"{hours} sa {minutes} dk" if hours else f"{minutes} dk"

    def _selected_project_id(self):
        row = self.project_table.currentRow()
        if row < 0:
            raise ValueError("Önce proje tablosundan bir satır seçin.")
        return int(self.project_table.item(row, 0).text())

    def update_selected_project(self):
        try:
            self.store.update_project(self._selected_project_id(), priority=self.project_priority.value(),
                                      status=self.project_state.currentText())
            self.dashboard_status.setText("Proje güncellendi."); self.refresh_dashboard()
        except ValueError as exc:
            self.dashboard_status.setText(str(exc))

    def cancel_selected_project(self):
        try:
            count = self.store.cancel_pending(self._selected_project_id())
            self.dashboard_status.setText(f"{count} bekleyen görev iptal edildi."); self.refresh_dashboard()
        except ValueError as exc:
            self.dashboard_status.setText(str(exc))

    def retry_selected_project(self):
        try:
            count = self.store.retry_tasks(self._selected_project_id())
            self.dashboard_status.setText(f"{count} görev yeniden sıraya alındı."); self.refresh_dashboard()
        except ValueError as exc:
            self.dashboard_status.setText(str(exc))

    def retry_result_project(self):
        project_id = self.result_project.currentData()
        if project_id is None:
            return
        count = self.store.retry_tasks(project_id)
        self.refresh_results(); self.refresh_dashboard()
        self.dashboard_status.setText(f"{count} görev yeniden sıraya alındı.")

    def create_portable_backup(self):
        path, _ = self.QtWidgets.QFileDialog.getSaveFileName(
            self.window, "TV Scan Studio yedeği", "tv-scan-studio-backup.tvscan.zip", "TV Scan yedeği (*.tvscan.zip)"
        )
        if not path:
            return
        try:
            create_backup(self.store, path); manifest = verify_backup(path)
            self.dashboard_status.setText(f"Yedek doğrulandı · {manifest['project_count']} proje")
        except Exception as exc:
            self.dashboard_status.setText(f"Yedekleme başarısız: {exc}")

    def measure_resources(self):
        try:
            snapshot = system_snapshot(); recommendation = recommend_workers(snapshot)
            available_gb = snapshot.available_memory_bytes / (1024 ** 3)
            self.resource_status.setText(
                f"CPU %{snapshot.cpu_percent:.0f} · boş RAM {available_gb:.1f} GB · öneri {recommendation.recommended} worker"
            )
            observed = self.store.observed_seconds_per_test(self.worker_project.currentData())
            if observed:
                projections = project_worker_throughput(observed, recommendation.recommended)
                summary = " · ".join(
                    f"{row['workers']}w≈{row['tests_per_hour']:.0f}/sa{'*' if not row['within_safe_limit'] else ''}"
                    for row in projections
                )
                self.resource_status.setText(self.resource_status.text() + " · " + summary + " (*limit üstü)")
            if snapshot.cpu_percent >= 90 or available_gb < 2:
                self.notify("Kaynak sınırına yaklaşıldı", self.resource_status.text())
        except RuntimeError as exc:
            self.resource_status.setText(str(exc))

    def notify(self, title, message):
        if self.tray.isVisible():
            self.tray.showMessage(title, message, self.QtWidgets.QSystemTrayIcon.Information, 6000)


def main() -> int:
    application = QtWidgets.QApplication(sys.argv)
    application.setStyleSheet(STYLE)
    studio = StudioWindow(Store(data_path()))
    application.aboutToQuit.connect(studio.stop_workers)
    studio.window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
