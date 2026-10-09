"""Explicit, preview-bound local diagnostics; never uploads anything."""
from PySide6 import QtCore, QtWidgets as Q
from .help_system import HelpRegistry, HelpSpec, TourSpec
from .support_package import diagnostic_items
from .support_jobs import SupportJob


class SupportDialog(Q.QDialog):
    drained = QtCore.Signal()

    def __init__(self, store, parent=None, help_registry=None):
        super().__init__(parent)
        self.job = None
        self.outcome = None
        self.closing = False
        self.cancel_requested = False
        self.number = 0
        self.items = list(diagnostic_items(store))
        self.setWindowTitle("Yerel destek paketi"); self.resize(760, 620)
        layout = Q.QVBoxLayout(self)
        self.note = Q.QLabel("Yalnız seçtiğin içerikler yeni bir ZIP'e kaydedilir. Otomatik yükleme yapılmaz. Özel kod, hesap bilgileri ve ekran görüntüleri kendiliğinden eklenmez.")
        self.note.setWordWrap(True); layout.addWidget(self.note)
        self.heading = Q.QLabel("Pakete alınacak içerikleri seç, ardından önizlemelerini kontrol et.")
        self.heading.setWordWrap(True); layout.addWidget(self.heading)
        self.contents = Q.QListWidget(); layout.addWidget(self.contents, 1)
        self.preview = Q.QPlainTextEdit(); self.preview.setReadOnly(True); layout.addWidget(self.preview, 2)
        self.add = Q.QPushButton("İsteğe bağlı dosyayı önizle")
        self.remove = Q.QPushButton("Seçili ek dosyayı çıkar")
        row = Q.QHBoxLayout(); row.addWidget(self.add); row.addWidget(self.remove); layout.addLayout(row)
        self.consent = Q.QCheckBox("Ek dosyaları kontrol ettim; özel içeriği eklemeyi onaylıyorum.")
        layout.addWidget(self.consent)
        self.status = Q.QLabel("ZIP oluşturulmadı. Varsayılan içerik yalnız sürüm ve isimsiz kayıt sayılarıdır.")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.details = Q.QPlainTextEdit(); self.details.setReadOnly(True); self.details.setMaximumHeight(70); self.details.hide()
        layout.addWidget(self.details)
        self.activity = Q.QProgressBar(); self.activity.setRange(0, 0); self.activity.hide(); layout.addWidget(self.activity)
        self.create = Q.QPushButton("Seçilenlerle ZIP oluştur")
        self.cancel = Q.QPushButton("İşlemi iptal et"); self.cancel.setEnabled(False)
        self.close_button = Q.QPushButton("Kapat"); self.guide = Q.QPushButton("? Destek paketi rehberi")
        row = Q.QGridLayout()
        for index, widget in enumerate((self.create, self.cancel, self.close_button, self.guide)):
            row.addWidget(widget, index // 2, index % 2)
        layout.addLayout(row)
        self.scope = help_registry.child_scope(self) if help_registry else HelpRegistry(self)
        entries = (
            ("note", self.note, "Yerel ve isteğe bağlı", "ZIP yalnız yerelde oluşturulur; hiçbir yere yüklenmez."),
            ("heading", self.heading, "İçerik seçimi", "Seçilen her içerik ZIP'e alınır; seçilmeyen dosyalar ZIP için okunmaz."),
            ("contents", self.contents, "Paket kapsamı", "Kutuları işaretleyerek içerikleri seç; satırı seçerek önizlemeyi gör."),
            ("preview", self.preview, "İçerik önizlemesi", "Boyut, SHA-256 ve ilk 64 KB gösterilir. Büyük dosyaların kalan içeriğini ayrıca kontrol et."),
            ("add", self.add, "Ek dosyayı önizle", "Açıkça seçtiğin dosya okunup checksum'ı hesaplanır; pakete otomatik alınmaz."),
            ("remove", self.remove, "Ek dosyayı çıkar", "Seçili ek dosyayı listeden çıkarır; diskteki dosyayı silmez."),
            ("consent", self.consent, "Özel içerik onayı", "Ek dosyalarda otomatik sansürleme yoktur. Kod, hesap bilgisi veya ekran görüntüsü varsa içeriği kendin kontrol et."),
            ("status", self.status, "İşlem durumu", "Gerçek aşama veya gerekli işlem gösterilir; başarı ancak ZIP doğrulanıp kaydedilince bildirilir."),
            ("details", self.details, "Teknik ayrıntılar", "İşlem hatasının teknik metnini gösterir; bu metin pakete otomatik eklenmez."),
            ("activity", self.activity, "Arka plan işlemi", "İşlem sürdüğünü gösterir; yüzde veya süre tahmini değildir."),
            ("create", self.create, "ZIP oluştur", "Seçimi yeni dosyaya kaydeder. Değişen içerik reddedilir; mevcut dosya ezilmez."),
            ("cancel", self.cancel, "Güvenli iptal", "Güvenli temizliğin bitmesini bekler. Yayımlanmış ZIP geç gelen iptalle silinmez."),
            ("close", self.close_button, "Kapat", "Çalışan işlem varsa iptal ister; işlem sonlanmadan pencereyi kapatmaz."),
            ("guide", self.guide, "Rehberi aç", "Salt okunur rehberi yeniden gösterir; dosya seçmez veya ZIP oluşturmaz."),
        )
        for key, target, title, short in entries:
            reason = self.block_reason if key == "create" else None
            self.scope.register(HelpSpec("support." + key, 1, title, short, short, target, reason))
        self.scope.register_tour(TourSpec("local_support", 1, (
            (self.contents, "Kapsamı sen seç", "Varsayılan içerikler özel kod veya hesap verisi taşımaz. Ek dosya zorunlu değildir.", None),
            (self.preview, "İçeriği incele", "Önizleme büyük dosyada kısadır. Ek dosyalar otomatik sansürlenmez; seçtiklerini ayrıca kontrol et.", None),
            (self.create, "Yalnız yerelde kaydet", "ZIP yeni dosyaya yazılır; otomatik yükleme yapılmaz. Rehber hiçbir işlem başlatmaz.", None),
        )))
        self.guide.clicked.connect(lambda: self.scope.start_tour("local_support"))
        self.finished.connect(lambda *_: self.scope.finish_scope())
        self.contents.currentRowChanged.connect(self.show_preview)
        self.contents.itemChanged.connect(self.selection_changed)
        self.consent.toggled.connect(self.refresh)
        self.add.clicked.connect(self.pick_file); self.remove.clicked.connect(self.remove_file)
        self.create.clicked.connect(self.pick_destination); self.cancel.clicked.connect(self.request_cancel)
        self.close_button.clicked.connect(self.reject)
        self.rebuild()
        QtCore.QTimer.singleShot(0, self.scope, lambda: self.scope.start_tour("local_support", automatic=True))

    def rebuild(self):
        selected_keys = {item.key for index, item in enumerate(self.items[:self.contents.count()])
            if self.contents.item(index).checkState() == QtCore.Qt.Checked}
        self.contents.blockSignals(True); self.contents.clear()
        for item in self.items:
            entry = Q.QListWidgetItem(item.label)
            entry.setFlags(entry.flags() | QtCore.Qt.ItemIsUserCheckable)
            entry.setCheckState(QtCore.Qt.Checked if item.key in selected_keys else QtCore.Qt.Unchecked)
            self.contents.addItem(entry)
        self.contents.blockSignals(False)
        if self.items: self.contents.setCurrentRow(0)
        self.refresh()

    def selected_items(self):
        return tuple(item for index, item in enumerate(self.items)
            if self.contents.item(index) is not None and self.contents.item(index).checkState() == QtCore.Qt.Checked)

    def block_reason(self):
        if self.job is not None: return "Önce çalışan işlemin bitmesini bekle."
        selected = self.selected_items()
        if not selected: return "En az bir içeriği seç ve önizlemesini kontrol et."
        if any(item.path is not None for item in selected) and not self.consent.isChecked():
            return "Ek dosyaları kontrol edip görünür özel içerik onayını işaretle."
        return None

    def selection_changed(self, *_args):
        self.consent.setChecked(False); self.refresh()

    def refresh(self, *_args):
        busy = self.job is not None
        self.create.setEnabled(self.block_reason() is None)
        for widget in (self.contents, self.consent, self.add): widget.setEnabled(not busy)
        row = self.contents.currentRow()
        self.remove.setEnabled(not busy and row >= 0 and self.items[row].path is not None)
        self.cancel.setEnabled(busy and not self.cancel_requested)
        self.activity.setVisible(busy)

    def show_preview(self, row):
        if row < 0: self.preview.clear(); return
        item = self.items[row]
        prefix = f"{item.label}\nZIP yolu: {item.name}\nBoyut: {item.size:,} bayt\nSHA-256: {item.sha256}\n"
        prefix += "Kısaltılmış önizleme: yalnız ilk 64 KB. Kalan içerik burada gösterilmez.\n" if len(item.preview) < item.size else "Tam içerik önizlemesi.\n"
        try:
            content = item.preview.decode("utf-8")
            if "\x00" in content: raise UnicodeError()
        except UnicodeError:
            content = "İkili dosya: metin önizlemesi yok. İçeriği kendi uygulamasında kontrol et; paket dosyanın tamamını içerir."
        self.preview.setPlainText(prefix + "\n" + content); self.refresh()

    def pick_file(self):
        if self.job is not None: return
        path, _ = Q.QFileDialog.getOpenFileName(self, "Önizlenecek isteğe bağlı dosyayı seç")
        if path: self.preview_file(path)

    def preview_file(self, path):
        if self.job is not None: return False
        self.number += 1
        self.start_job(SupportJob(path=path, number=self.number)); return True

    def remove_file(self):
        if self.job is not None: return
        row = self.contents.currentRow()
        if row >= 0 and self.items[row].path is not None:
            self.contents.takeItem(row); self.items.pop(row)
            self.consent.setChecked(False); self.rebuild()

    def pick_destination(self):
        if self.block_reason(): return
        path, _ = Q.QFileDialog.getSaveFileName(self, "Yeni destek ZIP'ini kaydet", "tvscan-support.zip", "ZIP (*.zip)")
        if path: self.create_zip(path)

    def create_zip(self, path):
        reason = self.block_reason()
        if reason: self.status.setText(reason); return False
        self.start_job(SupportJob(items=self.selected_items(), destination=path)); return True

    def start_job(self, job):
        self.job = job; self.outcome = None; self.cancel_requested = False
        self.details.clear(); self.details.hide(); self.status.setText("Hazırlanıyor…")
        job.progress.connect(self.update_progress); job.result.connect(self.receive_result); job.finished.connect(self.retire)
        self.refresh(); job.start()

    def update_progress(self, value):
        if not self.cancel_requested:
            self.status.setText(value["stage"] + f" · bu aşamada {value.get('bytes', 0):,} bayt")

    def receive_result(self, value): self.outcome = value

    def retire(self):
        job = self.job; self.job = None
        outcome = self.outcome or {"status": "error", "message": "İşlem sonuç bildirmeden sona erdi."}
        if outcome["status"] == "preview":
            self.items.append(outcome["item"]); self.consent.setChecked(False); self.rebuild()
            self.contents.setCurrentRow(len(self.items) - 1)
            self.status.setText("Dosya önizlendi; pakete eklenmedi. Kutuyu seçip içeriği ayrıca onayla.")
        elif outcome["status"] == "ready":
            self.status.setText("ZIP doğrulandı ve kaydedildi: " + outcome["destination"] + "\nHiçbir yere yüklenmedi.")
        elif outcome["status"] == "cancelled": self.status.setText("İşlem iptal edildi; yeni ZIP kaydedilmedi.")
        else:
            self.status.setText("İşlem tamamlanamadı. Dosyayı yeniden önizle veya yeni, yazılabilir bir ZIP adı seç. Teknik ayrıntılar aşağıda.")
            self.details.setPlainText(outcome["message"]); self.details.show()
        job.deleteLater(); self.refresh(); self.drained.emit()
        if self.closing: super().reject()

    def request_cancel(self):
        if self.job is not None:
            self.cancel_requested = True; self.job.cancel()
            self.status.setText("İptal ediliyor… Güvenli temizliğin bitmesi bekleniyor."); self.refresh()

    def reject(self):
        if self.job is not None: self.closing = True; self.request_cancel()
        else: super().reject()

    def accept(self): self.reject()

    def closeEvent(self, event):
        if self.job is not None:
            self.closing = True; self.request_cancel(); event.ignore()
        else: super().closeEvent(event)
