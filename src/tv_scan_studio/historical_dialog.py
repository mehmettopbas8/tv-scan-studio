"""Optional local scan archive browser, separate from the runnable task queue."""
import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets as Q

from .historical import iter_legacy_scan_records
from .export import CSV_FILTERS, export_task_csv, export_task_xlsx


def phase_label(phase):
    return {"baseline": "Başlangıç", "heavy": "Ağır maliyet", "provider": "Sağlayıcı doğrulaması",
            "unknown": "Aşama bilinmiyor"}.get(phase, phase)


class HistoricalDialog(Q.QDialog):
    PAGE_SIZE = 100

    def __init__(self, store, parent=None, help_coordinator=None):
        super().__init__(parent)
        self.store = store
        self.rows = []
        self.page = 0
        self.load_job = None
        self.load_result = None
        self.load_closing = False
        self.catalog_entries = []
        self.initial_saved = None
        self.initial_catalog_pending = False
        self.initial_requested = None
        self.archive_root = self.store.path.parent / "research-archives"
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
        catalog_row = Q.QHBoxLayout()
        self.catalog = Q.QComboBox()
        self.catalog.addItem("Kayıtlı arşiv yok", None)
        self.catalog_open = Q.QPushButton("Kayıtlı arşivi aç")
        self.catalog_open.clicked.connect(self.open_catalog_selection)
        self.catalog_refresh = Q.QPushButton("Listeyi yenile")
        self.catalog_refresh.clicked.connect(self.refresh_catalog)
        catalog_row.addWidget(self.catalog, 1); catalog_row.addWidget(self.catalog_open); catalog_row.addWidget(self.catalog_refresh)
        layout.addLayout(catalog_row)
        self.phase = Q.QComboBox()
        self.phase.addItem("Tüm araştırma aşamaları", None)
        self.phase.currentIndexChanged.connect(self.reset_page)
        layout.addWidget(self.phase)
        self.status = Q.QLabel("JSONL veya sıkıştırılmış JSONL arşivini seç. Araştırma preset kataloğu Genel ayarlardan ayrıca içe aktarılabilir.")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        activity_row = Q.QHBoxLayout()
        self.activity = Q.QProgressBar()
        self.activity.setRange(0, 0); self.activity.setTextVisible(False)
        self.cancel_load = Q.QPushButton("Yüklemeyi iptal et")
        self.cancel_load.clicked.connect(self.cancel_loading)
        self.load_guide = Q.QPushButton("? Yükleme rehberi")
        activity_row.addWidget(self.activity, 1); activity_row.addWidget(self.cancel_load)
        activity_row.addWidget(self.load_guide)
        layout.addLayout(activity_row)
        self.activity.hide(); self.cancel_load.hide(); self.load_guide.hide()
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
        self.render_page()
        from .help_system import HelpRegistry, HelpSpec, TourSpec
        self.help_registry = (help_coordinator.child_scope(self) if help_coordinator else
                              HelpRegistry(self, store.app_settings, store.save_app_settings))
        registry = self.help_registry
        entries = (
            ("catalog", self.catalog, "Kayıtlı arşivler", "Uygulama veri alanındaki ayrı arşivleri listeler; seçim tek başına dosya açmaz.", "Kayıt sayısı manifest bilgisidir, henüz dosya doğrulaması değildir. Aç düğmesi seçilen kopyanın checksum ve kapsamını yeniden doğrular. Farklı aşama ve kaynak dosyaları birleştirilmez; bozuk kayıt başka arşivi engellemez."),
            ("catalog_open", self.catalog_open, "Kayıtlı arşivi aç", "Seçilen arşivi arka planda doğrulayıp görüntüler.", "Özgün dosyayı tekrar bulman gerekmez. Eksik veya bozuk kopyada önceki görüntü korunur; arşiv yeni içerik gibi yeniden kaydedilmez."),
            ("catalog_refresh", self.catalog_refresh, "Arşiv listesini yenile", "Kayıtlı arşivlerin manifest listesini arka planda yeniden okur.", "Liste yenileme test çalıştırmaz, kayıt silmez ve dosya içeriğinin yeniden doğrulandığı anlamına gelmez."),
            ("phase", self.phase, "Araştırma aşaması", "Açık arşivin kaynak kayıtta bulunan aşamasını süzer.", "Başlangıç, maliyet veya sağlayıcı aşaması dosya adından tahmin edilmez. Eksik aşama bilinmiyor olarak gösterilir. Durum filtresiyle birlikte uygulanır; dışa aktarım iki filtreye de uyar."),
            ("open", self.open_button, "Arşiv seç", "Yerel JSONL arşivini doğrulayıp uygulama veri alanına kopyalar; özgün dosyayı değiştirmez.", "Aynı dosya checksum ile tanınır ve tekrar eklenmez. Manifest aşama, dönem ve gerçek kayıt sayılarını saklar; eksik kaynak bilgisi bilinmiyor olarak kalır. Eski kayıtlar yeni görev oluşturmaz ve yeniden doğrulanmış sayılmaz."),
            ("filter", self.filter, "Geçmiş filtresi", "Arşivdeki eski sınıflandırmaya göre kayıtları süzer.", "Başarılı etiketi arşivin eski değerlendirmesidir; güncel kaynak veya dönem doğrulaması değildir."),
            ("export", self.export_button, "Geçmişi dışa aktar", "Filtreye uyan bütün kayıtları CSV veya Excel'e aktarır.", "Yalnız görünen sayfa veya seçili satır değil, filtrenin tüm kayıtları aktarılır."),
            ("table", self.table, "Geçmiş kayıtlar", "Bir satır seçerek eski testin ayrıntılarını inceleyebilirsin.", "Her sayfa en fazla 100 kayıt gösterir. Eksik metrikler sonuç uydurulmadan boş gösterilir."),
            ("previous", self.previous, "Önceki sayfa", "Filtrelenmiş arşivin önceki sayfasını gösterir.", "Sayfa değiştirmek arşivi veya filtreyi değiştirmez."),
            ("next", self.next, "Sonraki sayfa", "Filtrelenmiş arşivin sonraki sayfasını gösterir.", "Dışa aktarma sayfalamadan bağımsız olarak bütün filtrelenmiş kayıtları kapsar."),
            ("detail", self.detail, "Kayıt ayrıntısı", "Seçili kaydın ham ayar ve metriklerini salt okunur gösterir.", "Kaynak kimliği eksikse eski ayarların yeni stratejiyle eşleştiği varsayılmaz."),
            ("status", self.status, "Arşiv durumu", "Dosya checksum kontrolünü, aktarım sonucunu ve arşivde bulunan aşama sayılarını gösterir.", "Aşama ve dönemler kayıttan okunur; dosya adı veya özet sayılarından tahmin edilmez. Checksum hatasında kayıtlı kopyayı kullanmak yerine özgün arşivi kontrol et. Yeniden seçmek kayıt sayısını artırmaz."),
            ("page", self.page_label, "Sayfa bilgisi", "Filtrelenmiş kayıt sayısını ve mevcut sayfayı gösterir.", "Kayıt sayısı yeniden doğrulanmış test sayısı değildir."),
            ("note", note, "Geçmişin sınırı", "Arşiv kayıtları ile güncel tarama sonuçlarının farkını açıklar.", "Arşivi incelemek TradingView'de yeni test çalıştırmaz."),
            ("close", close, "Kapat", "Geçmiş penceresini kapatır.", "Kayıtları silmez ve çalışan taramayı durdurmaz."),
            ("activity", self.activity, "Arşiv yükleniyor", "Arşiv okuma ve doğrulama işleminin sürdüğünü gösterir.", "Hareket göstergesi yüzde veya süre tahmini değildir. Önceki görüntü yalnız yeni arşiv tamamen okununca değişir."),
            ("cancel_load", self.cancel_load, "Arşiv yüklemesini iptal et", "Okuma işleminin durmasını ister; güvenli noktaya ulaşılmasını bekler.", "Özgün dosya ve önceki görüntü korunur. Aktarım bitmişse doğrulanmış yerel kopya tutulabilir; bu işlem onu silmez. Pencereyi kapatmak da iptal ister."),
            ("load_guide", self.load_guide, "Yükleme rehberi", "Arşiv yükleme ve iptal rehberini yeniden açar.", "Rehber dosya seçmez, arşiv yüklemez veya işlemi iptal etmez."),
        )
        reasons = {
            "catalog_open": lambda: ("Önce süren yüklemeyi bitir veya iptal et." if self.load_job is not None else
                                      None if self.catalog_open.isEnabled() else
                                      "Liste bilgisi okunamadı; arşiv seçimini ve manifesti kontrol et." if isinstance(self.catalog.currentData(), dict) else
                                      "Önce listeden okunabilir bir arşiv seç."),
            "catalog_refresh": lambda: "Önce süren yüklemeyi bitir veya iptal et." if self.load_job is not None else None,
            "open": lambda: "Önce süren arşiv yüklemesini bitir veya iptal et." if self.load_job is not None else None,
            "export": lambda: ("Arşiv yüklemesinin bitmesini bekle." if self.load_job is not None else
                                None if self.export_button.isEnabled() else "Önce bir arşiv yükle veya kayıt içeren bir filtre seç."),
            "cancel_load": lambda: None if self.cancel_load.isEnabled() else "İptal istendi; okumanın durmasını bekle.",
            "previous": lambda: None if self.previous.isEnabled() else "İlk sayfadasın; önceki sayfa yok.",
            "next": lambda: None if self.next.isEnabled() else "Son sayfadasın; sonraki sayfa yok.",
        }
        for key, target, title, short, detail in entries:
            registry.register(HelpSpec("history." + key, 1, title, short, detail, target, reasons.get(key)))
        registry.register_columns("history", self.table, tuple(
            (title, short, detail) for title, short, detail in (
                ("Sembol", "Arşivdeki sağlayıcı ve sembol kodu.", "Yeni grafikte doğrulanmış sembol değildir."),
                ("Zaman dilimi", "Eski testin zaman dilimi.", "Sayısal değerler dakika olarak gösterilir."),
                ("Durum", "Eski araştırmanın sınıflandırması.", "Güncel doğrulama veya kârlılık garantisi değildir."),
                ("İşlem", "Arşivdeki tamamlanmış işlem sayısı.", "Eksik metrik çizgiyle gösterilir."),
                ("Kâr faktörü", "Arşivdeki kâr faktörü metriği.", "Yeni dönemde aynı performans garantisi değildir."),
                ("Düşüş %", "Arşivdeki yüzde düşüş metriği.", "Eski testin koşullarıyla birlikte değerlendirilmelidir."),
                ("Ayarlar", "Kaydedilmiş Pine ayarı sayısı.", "Değerleri görmek için satırı seç; kaynak eşliği ayrıca doğrulanmalıdır."),
            )))
        registry.register_tour(TourSpec("history", 1, (
            (self.open_button, "Eski arşivi seç", "JSONL veya sıkıştırılmış arşivi açabilirsin. Bu rehber dosya seçmez; eski kayıtlar yeniden doğrulanmış sayılmaz.", None),
            (self.catalog, "Kayıtlı arşive dön", "Farklı arşivler ayrı tutulur. Listeden seç, ardından Kayıtlı arşivi aç düğmesine bas. Liste bilgisi dosya doğrulaması değildir.", None),
            (self.phase, "Aşamaları ayır", "Kaynakta bulunan aşamayı ve geçmiş durumunu birlikte süzebilirsin. Eksik aşama bilinmiyor kalır.", None),
            (self.filter, "Kayıtları incele", "Filtreyi seç ve ayrıntılar için bir satıra bas. Arşivin eski başarılı etiketi güncel doğrulama değildir.", None),
            (self.export_button, "Kapsamı kontrol et", "CSV / Excel düğmesi yalnız bu sayfayı değil filtrenin tüm kayıtlarını aktarır. Rehber dosya oluşturmaz.", None),
        )))
        registry.register_tour(TourSpec("history_load", 1, (
            (self.status, "Yükleme aşamasını izle", "Kopyalama, doğrulama ve okuma arka planda yapılır. Önceki görüntü yeni dosya tamamen okununca değiştirilir.", None),
            (self.cancel_load, "Güvenle iptal et", "İptal et veya pencereyi kapat. Okuma bitene kadar beklenir; özgün dosya ve önceki görüntü korunur. Rehber iptal işlemi yapmaz.", None),
        )))
        registry.register_tour(TourSpec("history_catalog", 1, (
            (self.catalog, "Arşivleri ayrı seç", "Liste manifest bilgisidir. Bir arşiv seçmek mevcut görüntüyü değiştirmez; farklı arşivler birleştirilmez.", None),
            (self.catalog_open, "Kopyayı yeniden doğrula", "Aç düğmesi checksum ve kayıt kapsamını kontrol eder. Bozuk kopya yeni arşiv gibi eklenmez. Bu rehber arşivi açmaz.", None),
            (self.phase, "Aşamaya göre süz", "Açık arşivin gerçek kaynak aşamasını seç. Durum ve aşama filtresi birlikte uygulanır; eksik aşama bilinmiyor kalır.", None),
        )))
        for control in (self.catalog, self.catalog_open, self.catalog_refresh, self.phase):
            registry.bind_first_use(control, "history_catalog")
        catalog_guide = Q.QPushButton("? Arşiv seçimi")
        catalog_row.addWidget(catalog_guide)
        catalog_guide.clicked.connect(lambda: registry.start_tour("history_catalog"))
        registry.register(HelpSpec("history.catalog_guide", 1, "Arşiv seçim rehberi", "Kayıtlı arşiv ve aşama seçimi rehberini yeniden açar.", "Rehber dosya doğrulamaz, seçim uygulamaz ve kayıt silmez.", catalog_guide))
        registry.bind_first_use(self.cancel_load, "history_load")
        self.load_guide.clicked.connect(lambda: registry.start_tour("history_load"))
        guide = Q.QPushButton("? Geçmiş rehberi")
        controls.addWidget(guide)
        registry.register(HelpSpec("history.guide", 1, "Rehberi aç", "Geçmiş taramalar rehberini yeniden açar.", "Rehber arşiv yüklemez veya dosya oluşturmaz.", guide))
        guide.clicked.connect(lambda: registry.start_tour("history"))
        QtCore.QTimer.singleShot(0, registry, lambda: registry.start_tour("history", automatic=True))
        self.catalog.currentIndexChanged.connect(self.update_catalog_action)
        self.update_catalog_action()
        if self.archive_root.exists():
            self.initial_saved = saved
            self.initial_catalog_pending = True
            self.refresh_catalog()
        elif saved:
            self.load_archive(saved)

    def update_catalog_action(self, *_args):
        entry = self.catalog.currentData()
        self.catalog_open.setEnabled(self.load_job is None and isinstance(entry, dict) and entry.get("status") != "error")
        if self.load_job is None and isinstance(entry, dict) and entry.get("status") == "error":
            self.status.setText("Arşiv liste bilgisi okunamadı. Manifesti veya özgün arşivi kontrol et: " + entry.get("message", ""))

    def display_catalog(self, entries, selected_id=None):
        self.catalog_entries = entries
        blocker = QtCore.QSignalBlocker(self.catalog)
        self.catalog.clear()
        for entry in entries:
            manifest = entry.get("manifest") or {}
            label = (f"{manifest['source_name']} — {manifest['record_count']:,} kayıt (manifest)"
                     if manifest else "Arşiv liste bilgisi okunamadı")
            self.catalog.addItem(label, entry)
            self.catalog.setItemData(self.catalog.count() - 1, json.dumps(manifest, ensure_ascii=False, indent=2)
                                     if manifest else entry.get("message", ""), QtCore.Qt.ToolTipRole)
        if not entries:
            self.catalog.addItem("Kayıtlı arşiv yok", None)
        if selected_id:
            for index, entry in enumerate(entries):
                if entry["archive_id"] == selected_id:
                    self.catalog.setCurrentIndex(index)
                    break
        del blocker
        self.update_catalog_action()

    def refresh_catalog(self):
        if self.load_job is not None or self.load_closing:
            return False
        from .archive_jobs import ArchiveCatalogJob
        return self.start_archive_job(ArchiveCatalogJob(None, self.archive_root), "Kayıtlı arşiv listesi okunuyor… Dosyalar açıldığında ayrıca doğrulanacak.")

    def open_catalog_selection(self):
        entry = self.catalog.currentData()
        if not isinstance(entry, dict) or entry.get("status") == "error":
            self.status.setText("Kayıtlı arşiv açılamıyor: " + (entry.get("message", "Önce bir arşiv seç.") if isinstance(entry, dict) else "Önce bir arşiv seç."))
            return False
        return self.load_archive(entry["path"])

    def choose_archive(self):
        path, _ = Q.QFileDialog.getOpenFileName(self, "Geçmiş tarama arşivi seç", "", "Tarama günlükleri (*.jsonl *.gz)")
        if path:
            self.load_archive(path)

    def load_archive(self, path):
        # An explicit first choice must not disappear behind the constructor's
        # asynchronous catalog read, nor be replaced by the previous saved path.
        # Keep one pending choice only; ordinary concurrent loads are rejected.
        if self.load_job is not None and self.initial_catalog_pending and not self.load_closing:
            if self.initial_requested is not None:
                return False
            self.initial_requested = path
            self.initial_saved = None
            self.status.setText("Arşiv seçimi alındı; kayıtlı liste okunduktan sonra seçtiğin dosya açılacak.")
            return True
        if self.load_job is not None or self.load_closing:
            return False
        from .archive_jobs import ArchiveLoadJob
        return self.start_archive_job(ArchiveLoadJob(path, self.archive_root), "Arşiv kontrol ediliyor… Önceki görüntü işlem tamamlanana kadar korunur.")

    def start_archive_job(self, job, message):
        self.load_result = None
        self.load_job = job
        for widget in (self.open_button, self.filter, self.export_button, self.previous, self.next,
                       self.catalog, self.catalog_open, self.catalog_refresh, self.phase):
            widget.setEnabled(False)
        self.activity.show(); self.cancel_load.show(); self.load_guide.show(); self.cancel_load.setEnabled(True)
        self.status.setText(message)
        job.progress.connect(self.archive_progress)
        job.result.connect(self.archive_result)
        job.finished.connect(self.archive_finished)
        job.start()
        QtCore.QTimer.singleShot(0, self.help_registry, lambda: self.help_registry.start_tour("history_load", automatic=True) if self.load_job is not None else None)
        return True

    @QtCore.Slot(object)
    def archive_progress(self, value):
        if self.load_job is not None and not self.load_job.cancel_event.is_set():
            self.status.setText(f"{value['stage']}: {value.get('records', 0):,} kayıt.")

    @QtCore.Slot(object)
    def archive_result(self, value):
        self.load_result = value

    @QtCore.Slot()
    def archive_finished(self):
        job = self.load_job
        cancelled = job.cancel_event.is_set()
        self.load_job = None
        job.deleteLater()
        tour = self.help_registry.active_tour
        # Retire only a load tour whose target will now disappear; do not close the screen guide.
        if tour is not None and any(step[0] is self.cancel_load for step in tour.steps):
            tour.finish()
        self.activity.hide(); self.cancel_load.hide(); self.load_guide.hide()
        for widget in (self.open_button, self.filter, self.catalog, self.catalog_refresh, self.phase):
            widget.setEnabled(True)
        self.update_catalog_action()
        result = self.load_result or {"status": "error", "message": "İşlem sonuç bildirmeden sona erdi."}
        initial_catalog, self.initial_catalog_pending = self.initial_catalog_pending, False
        requested, self.initial_requested = self.initial_requested, None
        saved, self.initial_saved = self.initial_saved, None
        if not self.load_closing and result["status"] == "catalog_ready":
            current = self.catalog.currentData()
            self.display_catalog(result["entries"], current.get("archive_id") if isinstance(current, dict) else None)
            self.render_page()
            errors = sum(entry["status"] == "error" for entry in result["entries"])
            self.status.setText(f"{len(result['entries'])} kayıtlı arşiv; {errors} liste hatası. Liste bilgisi manifestten okundu; dosyalar açıldığında doğrulanacak.")
            if not cancelled and (requested or saved):
                self.load_archive(requested or saved)
        elif not self.load_closing and result["status"] == "ready":
            try:
                self.apply_archive(result["imported"], result["rows"])
            except Exception as error:
                self.render_page()
                self.status.setText("Arşiv seçimi kaydedilemedi; yeniden dene: " + str(error))
        else:
            self.render_page()
            self.status.setText("Arşiv yüklemesi iptal edildi; önceki görüntü ve özgün dosya korundu." if result["status"] == "cancelled" or self.load_closing else
                                "Arşiv açılamadı. Dosyayı kontrol edip yeniden seç: " + result["message"])
            # Catalog failure does not invalidate an explicitly selected file.
            # Cancellation and close never launch another background job.
            if initial_catalog and requested and not cancelled and not self.load_closing and result["status"] == "error":
                self.load_archive(requested)
        if self.load_closing:
            super().accept()

    def cancel_loading(self):
        if self.load_job is not None:
            self.load_job.cancel()
            self.cancel_load.setEnabled(False)
            self.status.setText("Arşiv yüklemesi iptal ediliyor… Okumanın güvenli biçimde durması bekleniyor.")

    def accept(self):
        if self.load_job is not None:
            self.load_closing = True
            self.cancel_loading()
        else:
            super().accept()

    def reject(self):
        self.accept()

    def closeEvent(self, event):
        if self.load_job is not None:
            self.load_closing = True
            self.cancel_loading()
            event.ignore()
        else:
            super().closeEvent(event)

    def apply_archive(self, imported, rows):
        self.store.save_app_settings({"historical_archive_path": str(imported["path"].resolve())})
        self.rows = rows
        self.page = 0
        manifest = imported["manifest"]
        entries = [entry for entry in self.catalog_entries if entry["archive_id"] != manifest["archive_id"]]
        entries.append({"archive_id": manifest["archive_id"], "manifest": manifest, "path": imported["path"], "status": "unchecked"})
        self.display_catalog(entries, manifest["archive_id"])
        blocker = QtCore.QSignalBlocker(self.phase)
        self.phase.clear(); self.phase.addItem("Tüm araştırma aşamaları", None)
        for phase in sorted(manifest["phases"]):
            self.phase.addItem(phase_label(phase), phase)
            self.phase.setItemData(self.phase.count() - 1, "Kaynak aşama: " + phase, QtCore.Qt.ToolTipRole)
        del blocker
        action = "Kayıtlı kopya doğrulandı; tekrar eklenmedi" if imported["reused"] else "Uygulama veri alanına kopyalandı; özgün dosya korunuyor"
        phases = ", ".join(f"{phase_label(phase)}: {count:,}" for phase, count in manifest["phases"].items())
        self.status.setText(f"{manifest['source_name']}: {len(rows):,} geçmiş kayıt. {action}. Aşamalar: {phases}. Yeniden doğrulanmadı.")
        self.render_page()

    def selected_records(self):
        classifications = {1: "geçmiş başarılı", 2: "geçmiş elenmiş", 3: "geçmiş teknik hata"}
        wanted = classifications.get(self.filter.currentIndex())
        phase = self.phase.currentData()
        return [row for row in self.rows if (wanted is None or row["classification"] == wanted) and
                (phase is None or (row["payload"].get("source_phase") or "unknown") == phase)]

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
