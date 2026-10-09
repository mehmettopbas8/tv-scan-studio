"""Explicit, read-only run selection; admission remains the transactional authority."""
from copy import deepcopy
from datetime import datetime

from PySide6 import QtCore, QtWidgets

from .help_system import HelpSpec, TourSpec
from .scan_runs import comparable_plan
from .ui_controls import SafeWheelFilter


class RunChoice(QtWidgets.QWidget):
    changed = QtCore.Signal()
    restore_requested = QtCore.Signal(object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.project_id = None
        self.runs = {}
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        self.label = QtWidgets.QLabel("Tarama koşusu")
        self.choice = QtWidgets.QComboBox()
        self.choice.addItem("Yeni tarama", None)
        self.label.setBuddy(self.choice)
        self.restore = QtWidgets.QPushButton("Kayıtlı planı yükle")
        self.guide = QtWidgets.QPushButton("?")
        self.guide.setAccessibleName("Tarama koşusu rehberi")
        row.addWidget(self.label)
        row.addWidget(self.choice, 1)
        row.addWidget(self.restore)
        row.addWidget(self.guide)
        box.addLayout(row)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.wheel_filter = SafeWheelFilter(self)
        self.choice.installEventFilter(self.wheel_filter)
        self.choice.currentIndexChanged.connect(self._changed)
        self.restore.clicked.connect(self._restore)
        self._changed()

    def refresh(self, project_id, selected=None):
        self.project_id = project_id
        self.runs = {run["id"]: run for run in self.store.scan_runs(project_id)
                     if run["kind"] == "scan"} if project_id is not None else {}
        blocker = QtCore.QSignalBlocker(self.choice)
        self.choice.clear()
        self.choice.addItem("Yeni tarama", None)
        for run in self.runs.values():
            date = datetime.fromtimestamp(run["created_at"]).strftime("%d.%m.%Y %H:%M")
            self.choice.addItem(f"Devam et: {date} (koşu {run['id']})", run["id"])
        self.choice.setCurrentIndex(max(0, self.choice.findData(selected)))
        del blocker
        self._changed()

    def _changed(self, *_args):
        resume = self.choice.currentData() in self.runs
        self.restore.setEnabled(resume and self.isEnabled())
        self.status.setText(
            "Aynı koşu sürdürülür; tamamlanmış testler yeniden eklenmez. Kaynak ve plan aynı olmalıdır."
            if resume else
            "Yeni bir koşu oluşturulur. Önceki görevler ve sonuçlar korunur; yalnız yeni koşu çalıştırılır.")
        self.changed.emit()

    def _restore(self):
        run = self.runs.get(self.choice.currentData())
        if run:
            try:
                self._check_source(run)
            except ValueError as error:
                self.status.setText(str(error))
                return
            self.restore_requested.emit(deepcopy(run["plan_snapshot"]))

    def _check_source(self, run):
        project = self.store.project(self.project_id)
        if not project or project["pine_source"] != run["source_snapshot"]:
            raise ValueError("Bu koşunun strateji kodu değişmiş. Eski koşuya devam etmek yerine Yeni tarama seçin.")

    def request(self, project_id, plan):
        if project_id != self.project_id:
            raise ValueError("Strateji değişti; tarama koşusu seçimini yeniden kontrol edin.")
        run_id = self.choice.currentData()
        if run_id is None:
            return {"new_run": True}
        run = self.runs.get(run_id)
        if run is None:
            raise ValueError("Devam edilecek koşu bulunamadı. Yeni tarama seçin.")
        self._check_source(run)
        if comparable_plan(plan.to_dict()) != comparable_plan(run["plan_snapshot"]):
            raise ValueError("Koşunun planı değişmiş. Kayıtlı planı yükleyin veya Yeni tarama seçin. "
                             "Başarı ölçütü değişikliği ayrı değerlendirme gerektirir.")
        return {"run_id": run_id}

    def register_help(self, registry):
        entries = (
            ("label", self.label, "Tarama koşusu", "Yeni bir tarama veya eski koşuya devam etmeyi seç.", "Her koşu kaynak ve planın ayrı anlık görüntüsünü taşır; eski kayıtlar silinmez."),
            ("choice", self.choice, "Yeni tarama veya devam et", "Yeni tarama eski sonuçları korur; Devam et aynı koşuyu sürdürür.", "Devam et kaynak ve plan aynıysa çalışır. Başka koşuların bekleyen görevleri bu taramada alınmaz. Seçim tek başına görev oluşturmaz."),
            ("restore", self.restore, "Kayıtlı planı yükle", "Seçili koşunun planını düzenleyiciye yükler; tarama başlatmaz.", "Ekrandaki kaydedilmemiş plan değişikliklerinin yerini alır. Kaynak kodu veya eski sonuçlar değiştirilmez. Yükledikten sonra kapsamı kontrol et."),
            ("status", self.status, "Koşu seçiminin etkisi", "Seçimin eski görevler ve sonuçlar üzerindeki etkisini açıklar.", "Bu açıklama tamamlanma kanıtı değildir; koşu ancak kuyruk işlemi başarıyla kaydedildiğinde oluşturulur."),
            ("guide", self.guide, "Koşu rehberi", "Yeni tarama ve devam et rehberini açar.", "Rehber plan yüklemez, kayıt oluşturmaz veya worker başlatmaz."),
        )
        for key, target, title, short, detail in entries:
            reason = (lambda: None if self.restore.isEnabled() else
                      "Önce devam edilecek bir koşu seç; hazırlık sürüyorsa tamamlanmasını bekle.") if key == "restore" else None
            registry.register(HelpSpec("runs." + key, 1, title, short, detail, target, reason))
        registry.register_tour(TourSpec("runs", 1, (
            (self.choice, "Yeni tarama mı, devam mı?", entries[1][4], None),
            (self.restore, "Kayıtlı plan", entries[2][4], None),
            (self.status, "Başlatmadan önce kontrol et", "Kaynak, dönem ve değerleri kontrol et. Hazırla ve başlat ayrıca onay ister; rehber işlem yapmaz.", None),
        )))
        registry.bind_first_use(self.choice, "runs")
        self.guide.clicked.connect(lambda: registry.start_tour("runs"))
