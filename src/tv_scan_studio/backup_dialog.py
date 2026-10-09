"""Responsive backup progress with close-as-cancel and safe thread retirement."""
from PySide6 import QtCore, QtWidgets as Q

from .help_system import HelpSpec, TourSpec


class BackupProgressDialog(Q.QDialog):
    def __init__(self, job, parent=None, help_coordinator=None):
        super().__init__(parent)
        self.job = job
        self.outcome = None
        self.cancel_requested = False
        self.setWindowTitle("Yedek oluşturuluyor" if job.operation == "create" else "Yedek yeni dosyaya açılıyor")
        self.resize(520, 260)
        layout = Q.QVBoxLayout(self)
        self.note = Q.QLabel("Dosyalar arka planda işleniyor. İptal veya kapatma isteğinde güvenli temizliğin bitmesi beklenir; aktif veritabanı değiştirilmez.")
        self.note.setWordWrap(True)
        self.status = Q.QLabel("Hazırlanıyor…")
        self.status.setWordWrap(True)
        self.activity = Q.QProgressBar()
        self.activity.setRange(0, 0)
        self.activity.setTextVisible(False)
        self.cancel_button = Q.QPushButton("İptal et")
        self.cancel_button.clicked.connect(self.request_cancel)
        self.guide = Q.QPushButton("? Yedek işlemi rehberi")
        for widget in (self.note, self.status, self.activity, self.cancel_button, self.guide):
            layout.addWidget(widget)
        from .help_system import HelpRegistry
        self.help_registry = (help_coordinator.child_scope(self) if help_coordinator else HelpRegistry(self))
        entries = (
            ("note", self.note, "Güvenli dosya işlemi", "Aktif veritabanını değiştirmeden yedek oluşturur veya ayrı hedefe açar.", "İptalde bu denemenin geçici dosyaları temizlenir. Önceden var olan yedek, aktif veritabanı ve kaynak dosyalar korunur."),
            ("status", self.status, "İşlem aşaması", "Gerçek işlem aşamasını ve bu aşamada işlenen veri miktarını gösterir.", "Aşamalar kopyalama ve doğrulama için aynı dosyayı tekrar okuyabilir. Veri miktarı toplam ilerleme yüzdesi değildir; yeni aşamada sıfırlanır."),
            ("activity", self.activity, "İşlem devam ediyor", "Dosya işleminin sürdüğünü gösterir; yüzde veya süre tahmini değildir.", "Başarı yalnız doğrulama ve hedefe kaydetme tamamlandıktan sonra bildirilir."),
            ("cancel", self.cancel_button, "Yedek işlemini iptal et", "İptal isteği gönderir; güvenli temizleme bitene kadar pencere açık kalır.", "Pencereyi kapatmak veya Escape de aynı isteği gönderir. Dosya yayımlandıktan sonra gelen geç bir iptal başarıyı geri almaz."),
            ("guide", self.guide, "Yedek işlemi rehberi", "İlerleme ve iptal açıklamalarını yeniden gösterir.", "Rehber yedek oluşturmaz, iptal etmez veya dosya silmez."),
        )
        if job.operation == 'evidence':
            self.setWindowTitle('Kanıt dosyası kontrolü')
            self.note.setText('Salt okunur checksum kontrolü arka planda yapılır. İptal veya kapatma isteği dosya okumanın durmasını bekler; özgün olay kaydı değiştirilmez.')
            self.guide.setText('? Kanıt kontrolü rehberi')
            entries = tuple((key, target, 'Kanıt kontrolü: ' + title,
                             'Geri yüklenen dosyanın mevcut içerik checksum kontrolünü salt okunur yapar.',
                             'Dosya kopyalanmaz, yayımlanmaz veya silinmez. Özgün geçmiş değişmez. İptal isteği güvenli okuma sınırında uygulanır; rehber işlemi başlatmaz veya iptal etmez.')
                            for key, target, title, short, detail in entries)
        for key, target, title, short, detail in entries:
            reason = (lambda: "İptal istendi; güvenli temizliğin bitmesini bekle." if self.cancel_requested else None) if key == "cancel" else None
            self.help_registry.register(HelpSpec("backup.operation." + key, 1, title, short, detail, target, reason))
        self.help_registry.register_tour(TourSpec("backup_operation", 1, (
            (self.status, "Gerçek aşamayı izle", "Burada yapılan işlem gösterilir. Okunan veri miktarı toplam yüzde veya kalan süre değildir.", None),
            (self.cancel_button, "Güvenle iptal et", "İptal et veya pencereyi kapat. İşlemin güvenli biçimde durması beklenir.", None),
        )))
        self.guide.clicked.connect(lambda: self.help_registry.start_tour("backup_operation"))
        job.progress.connect(self.update_progress)
        job.result.connect(self.receive_result)
        job.finished.connect(self.retire)

    def start(self):
        self.job.start()
        QtCore.QTimer.singleShot(0, self.help_registry, lambda: self.help_registry.start_tour("backup_operation", automatic=True))

    @QtCore.Slot(object)
    def update_progress(self, value):
        if not self.cancel_requested:
            count = value.get("bytes", 0)
            suffix = f" · bu aşamada {count / (1024 * 1024):.1f} MB işlendi" if count else ""
            self.status.setText(value["stage"] + suffix)

    @QtCore.Slot(object)
    def receive_result(self, value):
        self.outcome = value

    @QtCore.Slot()
    def retire(self):
        job = self.job
        self.job = None
        if self.outcome is None:
            self.outcome = {"status": "error", "message": "Yedek işlemi sonuç bildirmeden sona erdi."}
        self.help_registry.finish_scope()
        job.deleteLater()
        super().accept()

    def request_cancel(self):
        if self.job is not None:
            self.cancel_requested = True
            self.cancel_button.setEnabled(False)
            self.status.setText("İptal ediliyor… Dosya kontrolünün durması bekleniyor." if self.job.operation == 'evidence' else
                                "İptal ediliyor… Geçici dosyaların temizlenmesi bekleniyor.")
            self.job.cancel()

    def reject(self):
        if self.job is not None:
            self.request_cancel()
        else:
            super().reject()

    def accept(self):
        if self.job is not None:
            self.request_cancel()
        else:
            super().accept()

    def closeEvent(self, event):
        if self.job is not None:
            self.request_cancel()
            event.ignore()
        else:
            super().closeEvent(event)
