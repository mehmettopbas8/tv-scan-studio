"""Explicit approval of a user-selected refinement; never executes a scan."""
import json
from PySide6 import QtCore, QtWidgets as Q
from .coarse_fine import refinement_plan
from .help_system import HelpSpec, TourSpec
from .comparison import period_summary


class RefinementDialog(Q.QDialog):
    def __init__(self, context, parent, help_registry):
        super().__init__(parent)
        self.context = context
        self.approved_plan = None
        self.setWindowTitle("Kaba taramadan ayrıntılı plan hazırla")
        self.resize(740, 600)
        layout = Q.QVBoxLayout(self)
        self.note = Q.QLabel("Adayları sen seçtin. Bir sayısal ayar için ayrıntılı değerleri gir; diğer ayarlar aday paketleri olarak korunur. Otomatik en iyi ayar seçilmez.")
        self.note.setWordWrap(True); layout.addWidget(self.note)
        self.candidates = Q.QPlainTextEdit()
        self.candidates.setReadOnly(True)
        rows = []
        for index, record in enumerate(context["records"]):
            values = ", ".join(f"{context['definitions'][key].title if key in context['definitions'] else 'Adı bilinmeyen ayar'}: {value}"
                               for key, value in record["payload"]["inputs"].items())
            rows.append(f"Seçilen aday {index + 1}: {values}")
        payload = context["records"][0]["payload"]
        evidence = context["records"][0].get("evidence") or {}
        period = evidence.get("period")
        if isinstance(period, dict) and "dateRange" in period:
            period = (period.get("dateRange") or {}).get("backtest")
        timeframe = str(payload['timeframe'])
        timeframe = f"{timeframe} dakika" if timeframe.isdigit() else timeframe
        self.candidates.setPlainText(f"Sembol: {payload['symbol']}\nZaman dilimi: {timeframe}\nPlan dönemi: {period_summary(payload.get('date_range'))}\n"
            f"Kayıtlı rapor dönemi: {period_summary(period)}\nRapor para birimi: {evidence.get('report_currency') or 'Kanıt yok'}\n"
            "Maliyet kapsamı kısmi olabilir; spread doğrulanmış sayılmaz.\n\n" + "\n".join(rows))
        layout.addWidget(self.candidates, 1)
        form = Q.QFormLayout()
        self.input = Q.QComboBox()
        mapped = (context["parent_plan"].get("costs") or {}).get("tradingview_inputs", {})
        for key, spec in context["definitions"].items():
            if spec.kind in {"int", "float"} and key not in mapped and all(key in record["payload"]["inputs"] for record in context["records"]):
                self.input.addItem(spec.title, key)
        self.values = Q.QLineEdit()
        self.values.setPlaceholderText("Örnek biçim: 7, 8, 9 — bunlar önerilen optimum değerler değildir")
        form.addRow("Ayrıntılı taranacak ayar", self.input)
        form.addRow("Onaylayacağın değer listesi", self.values)
        layout.addLayout(form)
        self.status = Q.QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.apply = Q.QPushButton("Değerleri onayla ve yeni koşuya ekle")
        self.cancel = Q.QPushButton("Vazgeç")
        self.apply.clicked.connect(self.confirm)
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(self.apply); layout.addWidget(self.cancel)
        self.scope = help_registry.child_scope(self)
        self.help_registry = self.scope
        entries = (
            ("note", self.note, "Seçimin sınırı", "Aday seçimini ve ayrıntılı taramanın sınırını açıklar.", "Geçmiş başarı gelecekte kazanç garantisi değildir. Bu adım ayrı dönem doğrulaması değildir; yeni sonuçların rapor dönemi ve maliyetleri ayrıca doğrulanır."),
            ("candidates", self.candidates, "Seçtiğin adaylar", "Saklanan kaba sonuçların ayarlarını gösterir.", "Liste salt okunurdur; diğer ayarlar bu adayların paketleri olarak korunur, bağımsız eksenler gibi yeniden karıştırılmaz. Maliyet, başarı ölçütü, sembol ve zaman dilimi korunur."),
            ("input", self.input, "Ayrıntılı ayar", "Daha sık değerlerle denemek istediğin sayısal ayarı seçer.", "Maliyet tarafından ezilen veya adayda uygulanmamış ayarlar seçilemez. Bir ayarı seçmek onu değiştirmez; değerleri girip onaylamalısın."),
            ("values", self.values, "Denenecek değerler", "Virgülle ayrılan yeni deneme değerlerini alır.", "Örneğin 7, 8, 9 yaz. Ondalık değerlerde nokta kullan: 0.1, 0.2. Köşeli parantezli liste de kabul edilir. Tam sayı, min/max, adım ve seçenek sınırları Pine kaynağına göre kontrol edilir. Tekrar eden ve sonlu olmayan değerler reddedilir."),
            ("status", self.status, "Plan özeti veya hata", "Görev üst sınırını veya düzeltmen gereken alanı gösterir.", "Ayar ilişkileri varsa üst sınır kuyrukta süzülür; kurala uymayan görevler eklenmez. Eksik/bozuk değerlerde eski plan ve görevler değişmez."),
            ("apply", self.apply, "Onayla ve kuyruğa ekle", "Ayrıntılı değerleri açıkça onaylar; yeni koşu kaydı hazırlanır.", "Kaba koşu ve aday sonuç kimlikleri değişmez plan kaydına bağlanır. Kuyruk hazırlığı iptal edilebilir. Tarama motoru bu düğmeyle otomatik başlamaz."),
            ("cancel", self.cancel, "Vazgeç", "Onay vermeden pencereyi kapatır.", "Görev, koşu veya proje ayarı kaydedilmez; seçilen kaba sonuçlar değişmez."),
        )
        for key, target, title, short, detail in entries:
            reason = (lambda: None if self.apply.isEnabled() else "Önce bir sayısal ayar ve geçerli değer listesi gir.") if key == "apply" else None
            self.scope.register(HelpSpec("refinement." + key, 1, title, short, detail, target, reason))
        self.scope.register_tour(TourSpec("refinement", 1, (
            (self.candidates, "Adayları kontrol et", "Yalnız senin seçtiğin kaba sonuçlar kullanılır. Diğer ayar paketleri korunur; otomatik kazanan seçilmez.", None),
            (self.input, "Bir ayarı ayrıntılı tara", "Sayısal ayarı seç ve açık değer listesini gir. Rehber seçim veya öneri uygulamaz.", None),
            (self.apply, "Yeni koşuyu onayla", "Özeti incele, sonra kendin onayla. Rehber görev oluşturmaz. Yeni koşu kaba sonuçları silmez ve kendiliğinden çalışmaz.", None),
        )))
        guide = Q.QPushButton("? Ayrıntılı tarama rehberi")
        guide.clicked.connect(lambda: self.scope.start_tour("refinement"))
        layout.addWidget(guide)
        self.scope.register(HelpSpec("refinement.guide", 1, "Rehberi aç", "Ayrıntılı plan rehberini yeniden açar.", "Rehber onay vermez veya görev oluşturmaz.", guide))
        self.input.currentIndexChanged.connect(self.preview)
        self.values.textChanged.connect(self.preview)
        self.finished.connect(lambda *_args: self.scope.finish_scope())
        QtCore.QTimer.singleShot(0, self.scope, lambda: self.scope.start_tour("refinement", automatic=True))
        self.preview()

    def plan(self):
        try:
            text = self.values.text().strip()
            values = json.loads(text if text.startswith("[") else "[" + text + "]")
        except json.JSONDecodeError as error:
            raise ValueError("Değerleri 7, 8, 9 biçiminde virgülle ayır. Ondalık değerlerde nokta kullan.") from error
        return refinement_plan(self.context, self.input.currentData(), values)

    def preview(self, *_args):
        try:
            plan = self.plan()
            self.status.setText(f"{len(self.context['records'])} seçili aday → {len(plan.variants) or 1} farklı ayar paketi × {len(next(iter(plan.input_values.values())))} değer. "
                f"{'Kural öncesi üst sınır' if plan.constraints else 'Planlanan test'}: {plan.cartesian_count:,}. "
                "Kaynak, sembol, dönem ve maliyetler korunur; motor otomatik başlamaz.")
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
