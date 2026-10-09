"""Bounded, read-only browsing of all run tasks, including resultless attempts."""
import json
from PySide6 import QtCore, QtWidgets as Q
from .help_system import HelpSpec, TourSpec
from .result_history_panel import ResultHistoryPanel, timestamp
from .tradingview import chart_resolution

PAGE_SIZE = 100
STATES = {"pending": "Bekleyen", "running": "Çalışan", "done": "Tamamlanan",
          "failed": "Başarısız", "cancelled": "İptal", "manual_review": "İnceleme gerekli"}


def timeframe_label(value):
    code = chart_resolution(str(value))
    if code.isdigit():
        minutes = int(code)
        return f"{minutes // 60} saat" if minutes and minutes % 60 == 0 else f"{minutes} dakika"
    return {"D": "1 gün", "W": "1 hafta", "1M": "1 ay"}.get(code, str(value))


class RunBrowser(Q.QDialog):
    def __init__(self, store, *, parent, help_registry):
        super().__init__(parent)
        self.store = store
        self.offset = 0
        self.setWindowTitle("Koşu ve deneme geçmişi"); self.resize(850, 610)
        layout = Q.QVBoxLayout(self)
        self.note = Q.QLabel("Her tarama koşusu ayrı saklanır. Sonuçsuz ve kesilmiş görevlerin denemeleri de korunur. "
                            "Bu pencere tarama başlatmaz veya görevleri yeniden sıraya almaz.")
        self.note.setWordWrap(True); layout.addWidget(self.note)
        self.projects = Q.QComboBox()
        for project in store.projects():
            self.projects.addItem(project["name"], project["id"])
        self.runs = Q.QComboBox()
        form = Q.QFormLayout(); form.addRow("Strateji", self.projects); form.addRow("Tarama koşusu", self.runs)
        layout.addLayout(form)
        self.context = Q.QPlainTextEdit(); self.context.setReadOnly(True); self.context.setMaximumHeight(120)
        layout.addWidget(self.context)
        self.tasks = Q.QTableWidget(0, 6)
        self.tasks.setHorizontalHeaderLabels(["Sembol", "Zaman dilimi", "Durum", "Deneme", "Saklanan sonuç", "Kanıt"])
        self.tasks.setEditTriggers(Q.QAbstractItemView.NoEditTriggers)
        self.tasks.setSelectionBehavior(Q.QAbstractItemView.SelectRows)
        self.tasks.setSelectionMode(Q.QAbstractItemView.SingleSelection)
        self.tasks.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.tasks, 1)
        self.status = Q.QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        actions = Q.QHBoxLayout()
        self.previous = Q.QPushButton("Önceki sayfa"); self.next = Q.QPushButton("Sonraki sayfa")
        self.refresh = Q.QPushButton("Yenile"); self.details = Q.QPushButton("Denemeleri ve sonuçları aç")
        for control in (self.previous, self.next, self.refresh, self.details):
            actions.addWidget(control)
        layout.addLayout(actions)
        self.guide = Q.QPushButton("? Koşu geçmişi rehberi"); self.close_button = Q.QPushButton("Kapat")
        layout.addWidget(self.guide); layout.addWidget(self.close_button)
        self.scope = help_registry.child_scope(self)
        entries = (
            ("note", self.note, "Geçmişin kapsamı", "Koşular ve sonuçsuz görevler ayrı saklanır."),
            ("projects", self.projects, "Strateji", "Geçmişi incelenecek stratejiyi seçer; kaynak veya görev değişmez."),
            ("runs", self.runs, "Tarama koşusu", "Aynı stratejinin ayrı koşularını listeler. Eski kayıtlar eksik kaynak kanıtıyla gösterilir."),
            ("context", self.context, "Saklanan plan", "Koşunun değişmez dönem, araştırma aşaması ve kapsamını gösterir. Özel kod gösterilmez."),
            ("tasks", self.tasks, "Koşu görevleri", "Seçili koşunun görevlerini yüz satırlık sayfalarla gösterir. Sayfa dışındaki kayıtlar silinmez."),
            ("status", self.status, "Gösterilen kapsam", "Toplam görev sayısı ve mevcut sayfayı gösterir; sayılar test başarısı değildir."),
            ("previous", self.previous, "Önceki sayfa", "Önceki yüz göreve geçer."),
            ("next", self.next, "Sonraki sayfa", "Sonraki yüz göreve geçer."),
            ("refresh", self.refresh, "Yenile", "Seçili koşuyu tekrar okur; yeni görev oluşturmaz."),
            ("details", self.details, "Deneme ayrıntıları", "Seçili görevin bütün denemelerini, sonuçlarını ve ayrı değerlendirmelerini açar."),
            ("guide", self.guide, "Rehber", "Geçmiş rehberini yeniden açar; seçim veya kayıt yapmaz."),
            ("close", self.close_button, "Kapat", "Geçmiş penceresini kayıt değiştirmeden kapatır."),
        )
        for key, target, title, text in entries:
            reason = (lambda: None if self.details.isEnabled() else "Önce görev tablosunda bir satır seç.") if key == "details" else None
            self.scope.register(HelpSpec("run_browser." + key, 1, title, text, text, target, reason))
        self.scope.register_columns("run_browser.columns", self.tasks, (
            ("Sembol", "Görevdeki piyasa kodu.", "Saklanan görevin sembolüdür; canlı grafiği değiştirmez."),
            ("Zaman dilimi", "Görevdeki mum süresi.", "15 değeri 15 dakikayı ifade eder."),
            ("Durum", "Güncel görev durumu.", "Tamamlanma ile kanıt doğrulaması farklıdır."),
            ("Deneme", "Kaydedilen deneme numarası.", "Tekrarlar özgün deneme geçmişini silmez."),
            ("Saklanan sonuç", "Değişmez sonuç anlık görüntüsü sayısı.", "Geçersizleşen ve eski sonuçlar da saklanır."),
            ("Kanıt", "Son saklanan sonucun kanıt durumu.", "Bu etiket kaynak bağlamı veya gelecekte kâr garantisi değildir."),
        ))
        self.scope.register_tour(TourSpec("run_browser", 1, (
            (self.runs, "Koşuyu seç", "Yeniden taramalar ayrı koşudur; eski kayıtlar korunur.", None),
            (self.tasks, "Görevleri incele", "Sonuçsuz görevler de görünür. Sayfalar bütün görevlere erişim verir.", None),
            (self.details, "Denemeleri aç", "Bir satırı kendin seçerek bütün denemelerini incele. Rehber kayıt veya değerlendirme oluşturmaz.", None),
        )))
        self.projects.currentIndexChanged.connect(self.load_runs)
        self.runs.currentIndexChanged.connect(self.reset_page)
        self.tasks.itemSelectionChanged.connect(self.update_actions)
        self.previous.clicked.connect(lambda: self.change_page(-1)); self.next.clicked.connect(lambda: self.change_page(1))
        self.refresh.clicked.connect(self.load_page); self.details.clicked.connect(self.open_details)
        self.guide.clicked.connect(lambda: self.scope.start_tour("run_browser"))
        self.close_button.clicked.connect(self.accept)
        self.load_runs()
        QtCore.QTimer.singleShot(0, self.scope, lambda: self.scope.start_tour("run_browser", automatic=True))

    def load_runs(self, *_args):
        self.runs.blockSignals(True); self.runs.clear()
        for run in self.store.scan_runs(self.projects.currentData()):
            label = "Eski kayıtlar · kaynak kanıtı eksik" if run["kind"] == "legacy" else "Tarama"
            self.runs.addItem(f"{label} · {timestamp(run['created_at'])} · #{run['id']}", run["id"])
        self.runs.blockSignals(False); self.reset_page()

    def reset_page(self, *_args):
        self.offset = 0; self.load_page()

    def change_page(self, direction):
        self.offset = max(0, self.offset + direction * PAGE_SIZE); self.load_page()

    def load_page(self):
        run_id = self.runs.currentData()
        with self.store.connect() as connection:
            connection.execute("BEGIN")
            run = connection.execute("SELECT kind,plan_snapshot,source_hash FROM scan_runs WHERE id=?", (run_id,)).fetchone()
            count = connection.execute("SELECT COUNT(*) FROM run_tasks WHERE run_id=?", (run_id,)).fetchone()[0]
            self.offset = min(self.offset, max(0, (count - 1) // PAGE_SIZE * PAGE_SIZE))
            rows = connection.execute("SELECT t.id,t.status,t.attempts,t.payload,"
                "(SELECT COUNT(*) FROM result_history h WHERE h.task_id=t.id) AS snapshots,"
                "(SELECT verified FROM result_history h WHERE h.task_id=t.id ORDER BY h.id DESC LIMIT 1) AS verified "
                "FROM tasks t JOIN run_tasks rt ON rt.task_id=t.id WHERE rt.run_id=? ORDER BY t.id LIMIT ? OFFSET ?",
                (run_id, PAGE_SIZE, self.offset)).fetchall()
        self.rows = [dict(row) for row in rows]
        plan = json.loads(run["plan_snapshot"]) if run else {}
        dates = plan.get("date_range") or {}
        research = plan.get("research") or {}
        stage = {"period_validation": "Ayrı dönem doğrulaması", "walkforward_training": "İlerleyen eğitim dönemi",
                 "coarse_fine": "Adaylardan ayrıntılı tarama"}.get(research.get("kind"),
                     "Bağımsız tarama" if not research else "Araştırma aşaması")
        lines = ["Dönem: " + (f"{dates.get('from', 'Eksik')} – {dates.get('to', 'Eksik')}" if dates else "Sınır belirtilmemiş"),
                 "Semboller: " + (", ".join(plan.get("symbols", [])) or "Eski kayıtta kapsam eksik"),
                 "Zaman dilimleri: " + (", ".join(timeframe_label(value) for value in plan.get("timeframes", [])) or "Kanıt eksik"),
                 "Aşama: " + stage,
                 "Kaynak: " + ("Koşu oluşturulurken kaydedilmiş; canlı eşliği ayrıca doğrulanır." if run and run["source_hash"] else "Eski kayıtta kaynak kanıtı eksik.")]
        for key, title in (("parent_run_id", "Adayların seçildiği koşu"), ("selection_run_id", "Seçim koşusu"),
                           ("previous_validation_run_id", "Önceki doğrulama koşusu")):
            if research.get(key) is not None:
                lines.append(f"{title}: #{research[key]}")
        self.context.setPlainText("\n".join(lines))
        self.tasks.setRowCount(len(rows)); self.tasks.clearSelection()
        for index, row in enumerate(rows):
            payload = json.loads(row["payload"])
            values = (payload.get("symbol", "Bilinmiyor"), timeframe_label(payload.get("timeframe", "Bilinmiyor")),
                STATES.get(row["status"], "Bilinmeyen durum"), row["attempts"], row["snapshots"],
                "Sonuç yok" if row["verified"] is None else "Doğrulanmış" if row["verified"] else "Doğrulanmamış")
            for column, value in enumerate(values):
                self.tasks.setItem(index, column, Q.QTableWidgetItem(str(value)))
        self.status.setText(f"{count:,} görev · gösterilen: {self.offset + 1 if count else 0}–{self.offset + len(rows)}. "
                            "Eski veya geçersiz sonuçlar ayrıntıda korunur.")
        self.previous.setEnabled(self.offset > 0); self.next.setEnabled(self.offset + len(rows) < count)
        self.update_actions()

    def update_actions(self):
        self.details.setEnabled(bool(self.tasks.selectionModel().selectedRows()))

    def open_details(self):
        selected = self.tasks.selectionModel().selectedRows()
        if not selected:
            return
        dialog = Q.QDialog(self); dialog.setWindowTitle("Denemeler ve saklanan sonuçlar"); dialog.resize(800, 630)
        scope = self.scope.child_scope(dialog)
        layout = Q.QVBoxLayout(dialog)
        panel = ResultHistoryPanel(self.store, self.rows[selected[0].row()]["id"], dialog)
        panel.register_help(scope); layout.addWidget(panel)
        close = Q.QPushButton("Kapat"); close.clicked.connect(dialog.accept); layout.addWidget(close)
        scope.register(HelpSpec("run_browser.detail_close", 1, "Kapat", "Görev ayrıntısını kapatır.",
                                "Önceki deneme ve sonuçlar değişmez.", close))
        dialog.exec()
