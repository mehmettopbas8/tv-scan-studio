"""Frozen execution history and explicit policy-only evaluation in result details."""
import json
from datetime import datetime

from PySide6 import QtCore, QtWidgets

from .help_system import HelpSpec, TourSpec


CRITERIA = (
    ("min_trades", "Asgari işlem sayısı"),
    ("min_profit_factor", "Asgari kâr faktörü"),
    ("min_win_rate_pct", "Asgari kazanma oranı (%)"),
    ("min_net_profit", "Asgari net sonuç"),
    ("max_drawdown_pct", "Azami düşüş, dâhil (%)"),
    ("max_drawdown_pct_exclusive", "Azami düşüş, hariç (%)"),
    ("max_daily_loss_pct", "Günlük kayıp sınırı (%)"),
    ("max_total_loss_pct", "Toplam kayıp sınırı (%)"),
)
EVENTS = {"claimed": "Test alındı", "failed": "Deneme başarısız",
          "interrupted": "Kesinti kaydedildi", "completed": "Sonuç kaydedildi",
          "invalidated": "Kanıt geçersiz"}
WARNINGS = {"present": "Var", "absent": "Yok", "unknown": "Bilinmiyor"}


def timestamp(value):
    return datetime.fromtimestamp(value).strftime("%d.%m.%Y %H:%M:%S")


def table(headers):
    widget = QtWidgets.QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    widget.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


class ResultHistoryPanel(QtWidgets.QWidget):
    def __init__(self, store, task_id, parent=None):
        super().__init__(parent)
        self.store, self.task_id = store, task_id
        self.records = store.result_history(task_id)
        self.fields = {}
        self.help_registry = None
        layout = QtWidgets.QVBoxLayout(self)
        self.note = QtWidgets.QLabel("Eski sonuçlar ve denemeler korunur. Yeni ölçütler ayrı değerlendirme "
                                     "oluşturur; TradingView testi çalıştırılmaz.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.guide = QtWidgets.QPushButton("? Geçmiş ve değerlendirme rehberi")
        layout.addWidget(self.guide)
        self.selector = QtWidgets.QComboBox()
        for record in self.records:
            self.selector.addItem(f"Deneme {record['attempt_number']} · {timestamp(record['created_at'])}", record["id"])
        layout.addWidget(self.selector)
        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.pages = QtWidgets.QTabWidget()
        layout.addWidget(self.pages, 1)
        attempt_page = QtWidgets.QWidget()
        attempt_layout = QtWidgets.QVBoxLayout(attempt_page)
        self.attempts = table(["Zaman", "Deneme", "Olay"])
        events = store.attempt_history(task_id)
        self.attempts.setRowCount(len(events))
        for row, event in enumerate(events):
            for column, value in enumerate((timestamp(event["created_at"]), event["attempt_number"],
                                             EVENTS.get(event["event"], "Teknik olay"))):
                self.attempts.setItem(row, column, QtWidgets.QTableWidgetItem(str(value)))
        self.attempt_note = QtWidgets.QLabel("Eski kayıtlarda deneme kanıtı bulunmayabilir; eksik geçmiş üretilmez.")
        self.attempt_note.setWordWrap(True)
        attempt_layout.addWidget(self.attempt_note)
        attempt_layout.addWidget(self.attempts)
        self.pages.addTab(attempt_page, "Denemeler")
        evaluation_page = QtWidgets.QWidget()
        evaluation_layout = QtWidgets.QVBoxLayout(evaluation_page)
        form = QtWidgets.QFormLayout()
        for key, label in CRITERIA:
            field = QtWidgets.QLineEdit()
            field.setPlaceholderText("Ölçüt uygulanmaz")
            self.fields[key] = field
            form.addRow(label, field)
        evaluation_layout.addLayout(form)
        self.evaluate = QtWidgets.QPushButton("Ayrı değerlendirme kaydet")
        self.evaluate.clicked.connect(self.save_evaluation)
        evaluation_layout.addWidget(self.evaluate)
        self.evaluations = table(["Zaman", "Sonuç sınıfı", "Başarı ölçütleri"])
        evaluation_layout.addWidget(self.evaluations)
        self.evaluations.setMinimumHeight(140)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        evaluation_layout.insertWidget(1, self.status)
        evaluation_scroll = QtWidgets.QScrollArea()
        self.evaluation_scroll = evaluation_scroll
        evaluation_scroll.setWidgetResizable(True)
        evaluation_scroll.setWidget(evaluation_page)
        self.pages.addTab(evaluation_scroll, "Değerlendirmeler")
        self.technical = QtWidgets.QPlainTextEdit()
        self.technical.setReadOnly(True)
        self.pages.addTab(self.technical, "Teknik ayrıntılar")
        self.selector.currentIndexChanged.connect(self.refresh)
        self.selector.setCurrentIndex(len(self.records) - 1)
        self.refresh()

    def selected(self):
        return next((record for record in self.records if record["id"] == self.selector.currentData()), None)

    def refresh(self, *_args):
        record = self.selected()
        self.evaluate.setEnabled(record is not None)
        self.status.clear()
        if record is None:
            self.summary.setText("Bu görev için henüz sonuç anlık görüntüsü yok. Deneme geçmişini inceleyebilirsin.")
            self.evaluations.setRowCount(0)
            self.technical.clear()
            return
        source = ("Deneme sırasında kaynak kaydedildi" if record["source_provenance"] == "claim_snapshot"
                  else "Eski kayıtta kaynak kanıtı eksik")
        self.summary.setText(f"Özgün sınıf: {record['classification']}. "
                             f"Kanıt: {'doğrulanmış' if record['verified'] else 'doğrulanmamış'}. "
                             f"TradingView uyarısı: {WARNINGS[record['warning_state']]}. {source}. "
                             "Bu bilgiler gelecekte kâr garantisi değildir.")
        for key, field in self.fields.items():
            field.setText(str(record["payload"].get("criteria", {}).get(key, "")))
        self.refresh_evaluations()
        # Deliberately do not put private Pine source in this default technical view.
        self.technical.setPlainText(json.dumps({key: record[key] for key in
            ("id", "task_id", "run_id", "attempt_number", "source_provenance", "warning_state",
             "payload", "metrics", "evidence")}, ensure_ascii=False, indent=2))

    def refresh_evaluations(self):
        record = self.selected()
        rows = self.store.result_evaluations(record["id"]) if record else []
        self.evaluations.setRowCount(len(rows))
        labels = dict(CRITERIA)
        for row, evaluation in enumerate(rows):
            criteria = evaluation["definition"].get("criteria", {})
            description = "; ".join(f"{labels.get(key, key)}: {value}" for key, value in criteria.items()) or "Ölçüt yok"
            for column, value in enumerate((timestamp(evaluation["created_at"]), evaluation["classification"], description)):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip(value)
                self.evaluations.setItem(row, column, item)

    def save_evaluation(self):
        record = self.selected()
        if record is None:
            return
        try:
            criteria = {key: (int(field.text()) if key == "min_trades" else float(field.text()))
                        for key, field in self.fields.items() if field.text().strip()}
            if {"max_drawdown_pct", "max_drawdown_pct_exclusive"}.issubset(criteria):
                raise ValueError("Azami düşüş için dâhil veya hariç sınırdan yalnız birini doldurun.")
            answer = QtWidgets.QMessageBox.question(self, "Ayrı değerlendirme",
                "Seçili kaydın dondurulmuş metrikleri bu ölçütlerle değerlendirilsin mi?\n"
                "Özgün sonuç, kanıt ve görevler değişmez; yeni TradingView testi yapılmaz.")
            if answer != QtWidgets.QMessageBox.Yes:
                return
            self.store.reevaluate_result(record["id"], criteria)
            self.refresh_evaluations()
            self.status.setText("Ayrı değerlendirme kaydedildi. Özgün sonuç ve görevler korunuyor.")
            self.evaluation_scroll.ensureWidgetVisible(self.status)
        except (ValueError, OverflowError) as error:
            self.status.setText("Değerlendirme kaydedilmedi: " + str(error))
            self.evaluation_scroll.ensureWidgetVisible(self.status)

    def register_help(self, registry):
        self.help_registry = registry
        entries = (
            ("note", self.note, "Değişmez geçmiş", "Sonuç geçmişi ile değerlendirme arasındaki farkı açıklar.", "Yeni ölçütler ayrı kayıt oluşturur; eski sonuç ve kanıtlar değiştirilmez."),
            ("guide", self.guide, "Geçmiş rehberi", "Geçmiş ve ayrı değerlendirme rehberini açar.", "Rehber değerlendirme kaydetmez veya test çalıştırmaz."),
            ("select", self.selector, "Sonuç anlık görüntüsü", "Hangi denemenin kaydedilmiş sonucunu inceleyeceğini seçer.", "Seçim salt okunurdur. Son başarısız deneme daha önceki sonucun üstüne yazılmaz."),
            ("summary", self.summary, "Kanıt kapsamı", "Özgün sınıf, kaynak kanıtı ve TradingView uyarısını gösterir.", "Bilinmiyor, uyarı olmadığı anlamına gelmez. Doğrulanmış kanıt gelecekte kazanç garantisi değildir."),
            ("pages", self.pages, "Geçmiş bölümleri", "Denemeler, ayrı değerlendirmeler ve teknik ayrıntılar arasında geçer.", "Sekme değiştirmek test veya kayıt işlemi yapmaz."),
            ("attempts", self.attempts, "Deneme geçmişi", "Test alma, kesinti, hata ve sonuç olaylarını sırasıyla gösterir.", "Deneme sayısı başarılı test sayısı değildir. Eski eksik olaylar tahmin edilmez."),
            ("attempt_note", self.attempt_note, "Eski kayıt sınırı", "Eski verilerde bulunmayan deneme kanıtını açıklar.", "Eksik kayıtlar yeni kanıt gibi üretilmez."),
            ("save", self.evaluate, "Ayrı değerlendirme kaydet", "Seçili donmuş sonuca yeni başarı ölçütleri uygular.", "Onaydan sonra ayrı kayıt eklenir. Kaynak, sonuç, kanıt ve görevler değişmez; aynı ölçütler tekrar kayıt şişirmez."),
            ("evaluations", self.evaluations, "Değerlendirme kayıtları", "Her ölçüt paketinin bu sonuç için verdiği sınıfı gösterir.", "Bunlar ayrı TradingView testleri değil, aynı donmuş metriklerin değerlendirmeleridir."),
            ("status", self.status, "Değerlendirme durumu", "Kaydın tamamlandığını veya neden reddedildiğini gösterir.", "Geçersiz değerlerde değerlendirme kaydedilmez; önce alanı düzelt."),
            ("technical", self.technical, "Teknik geçmiş kanıtı", "Kaydedilmiş ayar, metrik ve kanıt ayrıntılarını salt okunur gösterir.", "Bu görünüm test yapmaz; özel Pine kaynak metni burada gösterilmez."),
        )
        for key, target, title, short, detail in entries:
            reason = (lambda: None if self.selected() else "Önce kaydedilmiş bir sonuç seç.") if key == "save" else None
            registry.register(HelpSpec("result_history." + key, 1, title, short, detail, target, reason))
        for key, label in CRITERIA:
            registry.register(HelpSpec("result_history.criteria." + key, 1, label,
                f"Ayrı değerlendirme için {label.lower()} değerini belirler.",
                "Boş alan bu ölçütü uygulamaz. Bu değer Pine riskini veya emirlerini değiştirmez. "
                "Günlük kayıp değerlendirmesi yeterli gün içi kanıt olmadan uygunluk garantisi vermez.", self.fields[key]))
        registry.register_columns("result_history.attempt_columns", self.attempts, (
            ("Zaman", "Deneme olayının kaydedildiği yerel zamandır.", "Backtestin başlangıç veya bitiş tarihi değildir."),
            ("Deneme", "Görevin kaçıncı çalıştırma denemesine ait olduğunu gösterir.", "Aynı denemenin test alma ve bitiş olayları aynı numarayı taşır; satır sayısı test sayısı değildir."),
            ("Olay", "Denemenin test alma, hata, kesinti veya sonuç olayını gösterir.", "Sonuç kaydedilmesi tek başına kanıtın doğrulandığını göstermez; sonuç özetini de kontrol et."),
        ))
        registry.register_columns("result_history.evaluation_columns", self.evaluations, (
            ("Zaman", "Bu değerlendirmenin kaydedildiği yerel zamandır.", "TradingView test tarihi veya test dönemi değildir."),
            ("Sonuç sınıfı", "Bu ölçüt paketinin donmuş sonuca verdiği sınıftır.", "Ayrı bir TradingView testi değildir; özgün sonuç sınıfı değiştirilmez."),
            ("Başarı ölçütleri", "Bu sınıfı üretirken kullanılan eşikleri gösterir.", "Bu eşikler Pine giriş, çıkış veya risk ayarları değildir; gelecekte başarı garantisi vermez."),
        ))
        registry.register_tour(TourSpec("result_history", 1, (
            (self.selector, "Denemeyi seç", "Kaydedilmiş sonuçlar birbirinin üzerine yazılmaz. İnceleyeceğin denemeyi seç.", None),
            (self.summary, "Kanıtın sınırını oku", "Kaynak ve uyarı kanıtını kontrol et. Bilinmiyor, yok demek değildir.", None),
            (self.pages, "Ayrı değerlendirme", "Değerlendirmeler sekmesinde yeni ölçütleri gir. Kaydet ayrıca onay ister; rehber kayıt yapmaz.", None),
        )))
        registry.bind_first_use(self.selector, "result_history")
        self.guide.clicked.connect(lambda: registry.start_tour("result_history"))
