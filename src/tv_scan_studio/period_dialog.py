"""Explicit date-window approval. Builders only read immutable snapshots."""
from PySide6 import QtCore, QtWidgets as Q
from .help_system import HelpSpec, TourSpec


class PeriodDialog(Q.QDialog):
    def __init__(self, builder, summary, *, training, parent, help_registry):
        super().__init__(parent)
        self.builder = builder
        self.approved_plan = None
        self.feature = "period_training" if training else "period_validation"
        title = "Sonraki eğitim dönemi" if training else "Ayrı dönemde doğrula"
        self.setWindowTitle(title); self.resize(720, 560)
        layout = Q.QVBoxLayout(self)
        self.note = Q.QLabel("Tamamlanmış doğrulamadan sonra eğitim penceresini ileri taşı. Yeni aday seçimi yalnız yeni eğitim sonuçlarında yapılacak."
            if training else "Seçtiğin aday ayar paketleri sabit kalacak. Doğrulama sonuçları bu adayların seçimine geri karıştırılmayacak.")
        self.note.setWordWrap(True); layout.addWidget(self.note)
        self.summary = Q.QPlainTextEdit(); self.summary.setReadOnly(True); self.summary.setPlainText(summary)
        layout.addWidget(self.summary, 1)
        form = Q.QFormLayout()
        self.start = Q.QLineEdit(); self.stop = Q.QLineEdit()
        self.start.setPlaceholderText("YYYY-MM-DD"); self.stop.setPlaceholderText("YYYY-MM-DD")
        form.addRow("Yeni dönemin başlangıcı", self.start); form.addRow("Yeni dönemin bitişi", self.stop)
        layout.addLayout(form)
        self.status = Q.QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.apply = Q.QPushButton("Dönemi onayla ve yeni koşuya ekle")
        self.cancel = Q.QPushButton("Vazgeç"); self.guide = Q.QPushButton("? Dönem araştırması rehberi")
        for widget in (self.apply, self.cancel, self.guide):
            layout.addWidget(widget)
        self.apply.clicked.connect(self.confirm); self.cancel.clicked.connect(self.reject)
        self.scope = help_registry.child_scope(self)
        entries = (
            ("note", self.note, "Aşamanın sınırı", "Eğitim ile doğrulamanın ayrı tutulmasını açıklar.", "Önce aday seçimi, sonra ayrı dönem doğrulaması yapılır. Uygulama içindeki ilişkiler izlenir; dışarıda aynı dönemin daha önce incelenmediğini veya gelecekte kazancı kanıtlamaz."),
            ("summary", self.summary, "Saklanan kapsam", "Önceki dönem ve sabit kaynak/ayar kapsamını gösterir.", "Liste salt okunurdur. Ayarlar bağımsız eksenler gibi karıştırılmaz. Eksik rapor dönemi veya kaynak kanıtında plan reddedilir."),
            ("start", self.start, "Dönem başlangıcı", "Yeni aşamanın başlangıç tarihini alır.", "YYYY-MM-DD biçimini kullan. Doğrulama seçim döneminden sonra başlamalı; ilerleyen eğitim penceresi geri taşınamaz."),
            ("stop", self.stop, "Dönem bitişi", "Yeni aşamanın bitiş tarihini alır.", "Bitiş başlangıçtan önce olamaz. İlerleyen eğitim tamamlanan doğrulama dönemini kapsamalı; yeni doğrulamalar önceki doğrulamayla çakışamaz."),
            ("status", self.status, "Plan özeti veya hata", "Yeni aşamanın kapsamını veya tarih hatasını gösterir.", "Başarılı önizleme kayıt değildir. Gerçek rapor dönemi ve ayarları test sonrasında ayrıca doğrulanır; gelecek performans garantisi yoktur."),
            ("apply", self.apply, "Dönemi onayla", "Aday ve tarih kapsamını onaylayarak yeni koşu hazırlığını başlatır.", "Kuyruk atomik ve iptal edilebilir hazırlanır. Plan, kaynak ve aşama ilişkileri son kayıtta yeniden kontrol edilir. Motor kendiliğinden başlamaz."),
            ("cancel", self.cancel, "Vazgeç", "Hiçbir araştırma görevi kaydetmeden kapatır.", "Önceki koşular, sonuçlar ve aday seçimi değişmez."),
            ("guide", self.guide, "Rehberi aç", "Bu aşamanın rehberini yeniden açar.", "Rehber tarih seçmez, onay vermez veya görev eklemez."),
        )
        for key, target, label, short, detail in entries:
            reason = (lambda: None if self.apply.isEnabled() else "Önce geçerli, ayrı bir dönem gir.") if key == "apply" else None
            self.scope.register(HelpSpec(self.feature + "." + key, 1, label, short, detail, target, reason))
        self.scope.register_tour(TourSpec(self.feature, 1, (
            (self.summary, "Kapsamı kontrol et", "Önceki dönem ve ayar paketlerini incele. Adaylar otomatik seçilmez; dışarıdaki veri incelemeleri takip edilemez.", None),
            (self.start, "Yeni dönemi belirle", "Başlangıç ve bitişi açıkça gir. Ayrı dönem ve ileri aşama kuralları kontrol edilir.", None),
            (self.apply, "Onayla", "Önizlemeyi inceleyip onayı kendin ver. Rehber görev oluşturmaz; tarama ayrıca hazırlanıp başlatılır.", None),
        )))
        self.guide.clicked.connect(lambda: self.scope.start_tour(self.feature))
        self.finished.connect(lambda *_: self.scope.finish_scope())
        self.start.textChanged.connect(self.preview); self.stop.textChanged.connect(self.preview)
        QtCore.QTimer.singleShot(0, self.scope, lambda: self.scope.start_tour(self.feature, automatic=True))
        self.preview()

    def plan(self):
        return self.builder({"from": self.start.text().strip(), "to": self.stop.text().strip()})

    def preview(self, *_args):
        try:
            plan = self.plan()
            self.status.setText(f"Yeni dönem: {plan.date_range['from']} – {plan.date_range['to']} · "
                f"{'Kural öncesi üst sınır' if plan.constraints else 'Test sayısı'}: {plan.cartesian_count:,}. "
                "Kaynak ve maliyetler korunur; motor kendiliğinden başlamaz.")
            self.apply.setEnabled(True)
        except (ValueError, TypeError) as error:
            self.status.setText(str(error)); self.apply.setEnabled(False)

    def confirm(self):
        try:
            self.approved_plan = self.plan()
        except (ValueError, TypeError) as error:
            self.status.setText(str(error)); self.apply.setEnabled(False)
            return
        self.accept()
