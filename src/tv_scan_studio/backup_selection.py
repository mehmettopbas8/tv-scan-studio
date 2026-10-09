"""Explicit, read-only attachment selection for portable backups."""
from pathlib import Path

from PySide6 import QtWidgets as Q

from .backup import BackupAttachment
from .help_system import HelpSpec, TourSpec


class BackupSelection(Q.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected = []
        layout = Q.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.note = Q.QLabel("İsteğe bağlı ek dosyalar. Projeler, Pine kodları, görevler, sonuçlar ve ayarlar zaten yedeğe girer. Kayıtlı arşivin kaynak dosyasını seçersen doğrulanmış arşiv manifesti de birlikte yedeklenir. Yedek özel veriler içerebilir; güvenli bir yerde sakla.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = Q.QHBoxLayout()
        self.add_buttons = {}
        for category, label in (("archive", "Arşiv ekle"), ("report", "Rapor ekle"), ("evidence", "Kanıt ekle")):
            button = Q.QPushButton(label)
            button.setObjectName("backupAdd" + category.title())
            button.clicked.connect(lambda _checked=False, kind=category: self.choose(kind))
            buttons.addWidget(button)
            self.add_buttons[category] = button
        self.guide = Q.QPushButton("?")
        buttons.addWidget(self.guide)
        layout.addLayout(buttons)
        self.listing = Q.QListWidget()
        self.listing.setObjectName("backupAttachmentList")
        self.listing.setMaximumHeight(110)
        layout.addWidget(self.listing)
        self.remove = Q.QPushButton("Seçili dosyayı yedek listesinden çıkar")
        self.remove.setObjectName("backupRemoveAttachment")
        self.remove.setEnabled(False)
        self.remove.clicked.connect(self.remove_selected)
        self.listing.currentRowChanged.connect(lambda row: self.remove.setEnabled(row >= 0))
        layout.addWidget(self.remove)
        self.status = Q.QLabel("Ek dosya seçilmedi; yalnız uygulama verileri yedeklenir.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def items(self):
        return tuple(self.selected)

    def choose(self, category):
        paths, _ = Q.QFileDialog.getOpenFileNames(self, "Yedeğe eklenecek dosyaları seç", "", "Tüm dosyalar (*)")
        if paths:
            self.add_paths(paths, category)

    def add_paths(self, paths, category):
        if category not in self.add_buttons:
            raise ValueError("Geçersiz yedek dosyası türü.")
        candidates = []
        known = {item.path.resolve() for item in self.selected}
        try:
            for name in paths:
                path = Path(name)
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"Dosya okunamadı: {path.name}. Mevcut, normal bir dosya seç.")
                if path.resolve() not in known:
                    candidates.append(BackupAttachment(path, category))
                    known.add(path.resolve())
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return False
        self.selected.extend(candidates)
        self.render()
        return True

    def remove_selected(self):
        row = self.listing.currentRow()
        if 0 <= row < len(self.selected):
            self.selected.pop(row)
            self.render()

    def render(self):
        self.listing.clear()
        names = {"archive": "Arşiv", "report": "Rapor", "evidence": "Kanıt"}
        for attachment in self.selected:
            item = Q.QListWidgetItem(f"{names[attachment.category]}: {attachment.path.name}")
            item.setToolTip(str(attachment.path))
            self.listing.addItem(item)
        self.status.setText(f"{len(self.selected)} ek dosya seçildi; kayıtlı arşiv manifesti gerektiğinde ayrıca eklenir. Özgün dosyalar değiştirilmez." if self.selected else
                            "Ek dosya seçilmedi; yalnız uygulama verileri yedeklenir.")

    def register_help(self, registry):
        entries = [
            ("note", self.note, "Yedek kapsamı", "Uygulama verileri her yedeğe girer; ek dosyaları sen seçersin.", "Yedek Pine kodu ve özel sonuçlar içerir. Bu dosyaları paylaşmadan önce kapsamı kontrol et. Dosya eklemek araştırmayı içe aktarmaz."),
            ("listing", self.listing, "Seçilen ek dosyalar", "Seçtiğin dosyaların türünü ve adını gösterir.", "Aynı dosya tekrar eklenmez. Kayıtlı arşivin kaynak dosyasına ait doğrulanmış manifest de yedeğe eklenir; bu, arşivin başka konumda açılmasını sağlar. Fareyle bir satırın üzerine gelerek tam yolu görebilirsin."),
            ("remove", self.remove, "Seçimden çıkar", "Seçili dosyayı yalnız yedek listesinden çıkarır; diskte silmez.", "Bu işlem önceki yedekleri değiştirmez. Dosyayı tekrar ekleyebilirsin."),
            ("status", self.status, "Ek dosya durumu", "Seçili dosya sayısını veya seçim hatasını gösterir.", "Yedek oluşturulurken dosyalar tekrar okunur ve bütünlükleri doğrulanır. Eksik veya değişen dosyada yedekleme başarısız olur."),
            ("guide", self.guide, "Ek dosya rehberi", "Ek dosya seçiminin adım adım rehberini açar.", "Rehber dosya seçmez, yedek oluşturmaz veya dosya silmez."),
        ]
        for category, button in self.add_buttons.items():
            entries.append((category, button, button.text(), "Seçtiğin dosyaları bu türle yedeğe ekler; özgün dosyayı değiştirmez.", "Dosya seçimi yalnız yedek kapsamını belirler; internete göndermez. Kayıtlı arşiv kaynağının doğrulanmış manifesti birlikte taşınır. Geri yükleme yalnız yeni hedefte arşiv erişimini kurar; geçmişi yeniden doğrulanmış sonuçlara veya görev kuyruğuna dönüştürmez."))
        for key, widget, title, short, detail in entries:
            reason = (lambda: None if self.remove.isEnabled() else "Önce ek dosya listesinden bir satır seç.") if key == "remove" else None
            registry.register(HelpSpec("backup.files." + key, 1, title, short, detail, widget, reason))
        registry.register_tour(TourSpec("backup_files", 1, (
            (self.note, "Yedek kapsamını belirle", "Uygulama verileri zaten yedeklenir. Arşiv, rapor ve kanıt dosyaları isteğe bağlıdır; yedek özel bilgiler içerebilir.", None),
            (self.add_buttons["archive"], "Dosyaları kendin seç", "Dosyanın türüne uygun ekleme düğmesini kullan. Bu işlem dosyayı silmez veya araştırmayı içe aktarmaz.", None),
            (self.listing, "Listeyi kontrol et", "Seçtiğin ek dosyalar ve kayıtlı arşivin gerekli doğrulanmış manifesti yedeğe girer. Seçimden çıkar düğmesi diskteki dosyaya dokunmaz.", None),
        )))
        registry.bind_first_use(self.add_buttons["archive"], "backup_files")
        self.guide.clicked.connect(lambda: registry.start_tour("backup_files"))
