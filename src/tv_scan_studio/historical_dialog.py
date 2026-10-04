"""Optional local scan archive browser, separate from the runnable task queue."""
import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets as Q

from .historical import iter_legacy_scan_records
from .export import CSV_FILTERS, export_task_csv, export_task_xlsx


class HistoricalDialog(Q.QDialog):
    PAGE_SIZE = 100

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.rows = []
        self.page = 0
        self.setWindowTitle("Geçmiş taramalar")
        self.resize(1040, 700)
        layout = Q.QVBoxLayout(self)
        note = Q.QLabel("Eski testleri incele ve dışa aktar. Arşiv kayıtları yeni tarama kuyruğuna eklenmez; bu uygulamada yeniden doğrulanmış sayılmaz.")
        note.setWordWrap(True); layout.addWidget(note)
        controls = Q.QHBoxLayout()
        self.open_button = Q.QPushButton("Arşiv dosyası seç")
        self.open_button.clicked.connect(self.choose_archive)
        controls.addWidget(self.open_button)
        self.filter = Q.QComboBox()
        self.filter.addItems(["Tüm geçmiş kayıtlar", "Geçmiş başarılı", "Geçmiş elenmiş", "Geçmiş teknik hata"])
        self.filter.currentIndexChanged.connect(self.reset_page)
        controls.addWidget(self.filter)
        self.export_button = Q.QPushButton("CSV / Excel dışa aktar")
        self.export_button.clicked.connect(self.export_records)
        controls.addWidget(self.export_button)
        layout.addLayout(controls)
        self.status = Q.QLabel("JSONL veya sıkıştırılmış JSONL arşivini seç. Araştırma preset kataloğu Genel ayarlardan ayrıca içe aktarılabilir.")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.table = Q.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Sembol", "Zaman dilimi", "Durum", "İşlem", "Kâr faktörü", "Düşüş %", "Ayarlar"])
        self.table.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(Q.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(Q.QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(Q.QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.show_detail)
        layout.addWidget(self.table, 1)
        pager = Q.QHBoxLayout()
        self.previous = Q.QPushButton("Önceki sayfa")
        self.next = Q.QPushButton("Sonraki sayfa")
        self.previous.clicked.connect(lambda: self.move_page(-1))
        self.next.clicked.connect(lambda: self.move_page(1))
        self.page_label = Q.QLabel()
        pager.addWidget(self.previous); pager.addWidget(self.page_label, 1); pager.addWidget(self.next)
        layout.addLayout(pager)
        self.detail = Q.QPlainTextEdit()
        self.detail.setReadOnly(True); self.detail.setMaximumHeight(180)
        layout.addWidget(self.detail)
        close = Q.QPushButton("Kapat"); close.clicked.connect(self.accept); layout.addWidget(close)
        saved = store.app_settings().get("historical_archive_path")
        if saved:
            self.load_archive(saved)
        self.render_page()

    def choose_archive(self):
        path, _ = Q.QFileDialog.getOpenFileName(self, "Geçmiş tarama arşivi seç", "", "Tarama günlükleri (*.jsonl *.gz)")
        if path:
            self.load_archive(path)

    def load_archive(self, path):
        try:
            rows = list(iter_legacy_scan_records(path))
            if not rows:
                raise ValueError("Arşivde tarama kaydı yok.")
        except Exception as error:
            self.status.setText("Arşiv açılamadı. Dosyayı kontrol edip yeniden seç: " + str(error))
            return False
        self.rows = rows
        self.page = 0
        self.store.save_app_settings({"historical_archive_path": str(Path(path).resolve())})
        self.status.setText(f"{Path(path).name}: {len(rows):,} geçmiş kayıt. Yeniden doğrulanmadı.")
        self.render_page()
        return True

    def selected_records(self):
        classifications = {1: "geçmiş başarılı", 2: "geçmiş elenmiş", 3: "geçmiş teknik hata"}
        wanted = classifications.get(self.filter.currentIndex())
        return [row for row in self.rows if wanted is None or row["classification"] == wanted]

    def reset_page(self):
        self.page = 0
        self.render_page()

    def move_page(self, delta):
        self.page += delta
        self.render_page()

    def render_page(self):
        rows = self.selected_records()
        self.visible_rows = rows[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]
        self.table.setRowCount(len(self.visible_rows))
        for index, row in enumerate(self.visible_rows):
            metrics = row["metrics"]
            tf = row["payload"]["timeframe"]
            tf = f"{tf} dakika" if tf.isdigit() else tf
            values = [row["payload"]["symbol"], tf, row["classification"], metrics.get("trades"),
                      metrics.get("profit_factor"), metrics.get("max_drawdown_pct"), len(row["payload"]["inputs"])]
            for col, value in enumerate(values):
                self.table.setItem(index, col, Q.QTableWidgetItem("—" if value is None else str(value)))
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled((self.page + 1) * self.PAGE_SIZE < len(rows))
        self.page_label.setText(f"{len(rows):,} kayıt; sayfa {self.page + 1}/{max(1, (len(rows) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)}")
        self.export_button.setEnabled(bool(rows))
        self.detail.clear()

    def show_detail(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.visible_rows):
            record = self.visible_rows[row]
            self.detail.setPlainText("Bu geçmiş kayıt yeniden doğrulanmadı. Kaynak kodun tam kimliği arşivde yoksa ayar adları kesin olarak eşlenemez.\n\n" +
                                     json.dumps(record, ensure_ascii=False, indent=2))

    def export_records(self):
        rows = self.selected_records()
        path, selected = Q.QFileDialog.getSaveFileName(self, f"Filtreye uyan {len(rows):,} geçmiş kaydı dışa aktar", "gecmis-taramalar.xlsx", CSV_FILTERS)
        if not path:
            return
        excel = "*.xlsx" in selected if selected else Path(path).suffix.lower() == ".xlsx"
        path = Path(path).with_suffix(".xlsx" if excel else ".csv")
        try:
            inputs = sorted({key for row in rows for key in row["payload"]["inputs"]})
            options = {} if excel else {"excel_tr": "Türkçe Excel" in selected}
            count = (export_task_xlsx if excel else export_task_csv)(iter(rows), path, inputs, **options)
            self.status.setText(f"Filtreye uyan {count:,} kayıt {path.name} dosyasına kaydedildi. Yalnız bu sayfa değil, filtrenin tüm kayıtları aktarıldı.")
            if options.get("excel_tr"):
                self.status.setText(self.status.text() + " Excel içe aktarma sihirbazı açılırsa UTF-8 ve noktalı virgül ayracını seçin. Doğrudan açmak için Excel (.xlsx) kullanabilirsiniz.")
        except Exception as error:
            self.status.setText("Dışa aktarılamadı: " + str(error))
