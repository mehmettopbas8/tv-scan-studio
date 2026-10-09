"""Explicit numeric-input relations, with no evaluation of user expressions."""
from PySide6 import QtCore, QtWidgets as Q
from .help_system import HelpSpec, TourSpec


class ConstraintEditor(Q.QWidget):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rules = []
        self.names = {}
        layout = Q.QVBoxLayout(self)
        self.note = Q.QLabel("İsteğe bağlı: iki sayısal ayar arasında ilişki tanımla. Kurala uymayan testler çalıştırılmaz.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        form = Q.QFormLayout()
        self.left = Q.QComboBox()
        self.operation = Q.QComboBox()
        for label, code in (("<", "<"), ("≤", "<="), (">", ">"), ("≥", ">=")):
            self.operation.addItem(label, code)
        self.right = Q.QComboBox()
        form.addRow("Birinci ayar", self.left)
        form.addRow("İlişki", self.operation)
        form.addRow("İkinci ayar", self.right)
        layout.addLayout(form)
        self.add = Q.QPushButton("Kural ekle")
        self.remove = Q.QPushButton("Seçili kuralı kaldır")
        self.guide = Q.QPushButton("? Ayar ilişkileri rehberi")
        layout.addWidget(self.add)
        self.listing = Q.QListWidget()
        self.listing.setMaximumHeight(120)
        layout.addWidget(self.listing)
        layout.addWidget(self.remove)
        layout.addWidget(self.guide)
        self.status = Q.QLabel("Henüz ilişki yok; bütün kombinasyonlar geçerli.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.add.clicked.connect(self.add_rule)
        self.remove.clicked.connect(self.remove_rule)
        self.left.currentIndexChanged.connect(self.update_actions)
        self.right.currentIndexChanged.connect(self.update_actions)
        self.listing.currentRowChanged.connect(self.update_actions)
        self.update_actions()

    def load(self, definitions, rules):
        self.names = {key: spec.title for key, spec in definitions.items() if spec.kind in {"int", "float"}}
        self.left.clear(); self.right.clear()
        for key, title in self.names.items():
            self.left.addItem(title, key); self.right.addItem(title, key)
        if self.right.count() > 1:
            self.right.setCurrentIndex(1)
        self.rules = [dict(rule) for rule in rules]
        self.render()

    def update_actions(self, *_args):
        self.add.setEnabled(self.left.currentData() is not None and self.right.currentData() is not None
                            and self.left.currentData() != self.right.currentData())
        self.remove.setEnabled(0 <= self.listing.currentRow() < len(self.rules))

    def render(self):
        self.listing.clear()
        for rule in self.rules:
            left = self.names.get(rule.get("left"), "Kaynakta bulunmayan ayar")
            right = self.names.get(rule.get("right"), "Kaynakta bulunmayan ayar")
            op = {"<=": "≤", ">=": "≥"}.get(rule.get("operator"), rule.get("operator", "?"))
            self.listing.addItem(f"{left} {op} {right}")
        self.update_actions()

    def add_rule(self):
        if not self.add.isEnabled():
            return
        rule = {"left": self.left.currentData(), "operator": self.operation.currentData(), "right": self.right.currentData()}
        if rule not in self.rules:
            self.rules.append(rule)
            self.render()
            self.changed.emit()

    def remove_rule(self):
        index = self.listing.currentRow()
        if 0 <= index < len(self.rules):
            self.rules.pop(index)
            self.render()
            self.changed.emit()

    def register_help(self, registry):
        entries = (
            ("left", self.left, "Birinci ayar", "İlişkinin sol tarafındaki sayısal ayarı seçer.", "Yalnız sayısal Pine ayarları listelenir. Aynı ayar iki tarafa seçilemez."),
            ("operator", self.operation, "Karşılaştırma", "Küçük, küçük veya eşit, büyük, büyük veya eşit ilişkisini seçer.", "İlişki test değerleri arasında uygulanır; sonuçların kârlılığını ölçmez."),
            ("right", self.right, "İkinci ayar", "İlişkinin sağ tarafındaki sayısal ayarı seçer.", "Örneğin Fast EMA < Slow EMA, yalnız bu koşula uyan değer çiftlerini çalıştırır."),
            ("add", self.add, "Kural ekle", "Seçilen ilişkiyi plana ekler; tarama başlatmaz.", "Birden fazla kural birlikte uygulanır. Bütün testler elenirse başlatma engellenir."),
            ("remove", self.remove, "Kural kaldır", "Listede seçilen ilişkiyi plandan kaldırır.", "Eski testleri veya sonuçları silmez; yeni planın kapsamını değiştirir."),
            ("listing", self.listing, "Plan kuralları", "Eklenen ilişkileri gösterir; kaldırmak için bir satır seç.", "Bütün kuralların aynı anda sağlanması gerekir. Kaynakta bulunmayan ayar yeniden seçilmelidir."),
            ("status", self.status, "İlişki sayımları", "Kural öncesi, atlanan ve kalan test sayılarını gösterir.", "Kalan sayı örnekleme bütçesinden önceki geçerli test sayısıdır; denenmeyen kombinasyonlar sonuç değildir."),
            ("note", self.note, "İlişkilerin etkisi", "İlişkilerin hangi testleri dışladığını açıklar.", "Bir kural eklemek stratejinin kodunu değiştirmez."),
            ("guide", self.guide, "İlişki rehberi", "Ayar ilişkileri rehberini yeniden açar.", "Rehber kural eklemez veya görev oluşturmaz."),
        )
        for key, target, title, short, detail in entries:
            reason = ((lambda: None if self.add.isEnabled() else "İki farklı sayısal ayar seç.") if key == "add" else
                      (lambda: None if self.remove.isEnabled() else "Önce listeden bir kural seç.") if key == "remove" else None)
            registry.register(HelpSpec("constraints." + key, 1, title, short, detail, target, reason))
        registry.register_tour(TourSpec("constraints", 1, (
            (self.left, "İki ayarı seç", "Sayısal ayarları ve karşılaştırmayı seç. Örnek: Fast EMA < Slow EMA.", None),
            (self.add, "Kuralı plana ekle", "Kural ekle yalnız planı değiştirir; test başlatmaz. Birden fazla kural birlikte uygulanır.", None),
            (self.status, "Sayımları kontrol et", "Kural öncesi, atlanan ve kalan sayıları incele. Rehber senin yerine kural eklemez.", None),
        )))
        registry.bind_first_use(self.left, "constraints")
        self.guide.clicked.connect(lambda: registry.start_tour("constraints"))
