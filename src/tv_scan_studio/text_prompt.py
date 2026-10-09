"""Explicitly described text prompts; guidance cannot commit business data."""
from PySide6 import QtCore, QtWidgets
from .help_system import HelpSpec, TourSpec


PROMPTS = {
    "preset_name": (
        "Preset kaydet", "Preset adı", "Bu testin ayar kaydına bir ad ver.",
        "Onay bu testin yerel ayar kaydını saklar; test veya kaynak kanıtını yeniden doğrulamaz. Aynı test tekrar kaydedilirse ikinci preset oluşturulmaz. Kod TradingView'e yüklenmez veya yayımlanmaz.",
        "Preseti kaydet", "Bu testin ayar kaydını verilen adla yerel olarak saklar."),
    "cost_name": (
        "Maliyet şablonu", "Şablon adı", "Geçerli maliyet değerlerini saklamak için bir ad ver.",
        "Onay geçerli sermaye, pozisyon, komisyon, spread ve kayma değerlerini yerel şablona kaydeder. Aynı ad varsa şablon güncellenir ve seçilir. Şablon kaydı canlı grafiğe uygulanmış maliyet kanıtı değildir; eski sonuçlar yeniden hesaplanmaz.",
        "Şablonu kaydet", "Geçerli maliyet değerlerini adlandırılmış şablona kaydeder; aynı ad varsa günceller."),
    "filter_name": (
        "Filtreyi kaydet", "Filtre adı", "Geçerli sonuç görünümü filtrelerine bir ad ver.",
        "Onay bu stratejinin görünüm filtrelerini yerel olarak kaydeder. Aynı ad varsa önceki filtre tanımı güncellenir. Test ayarları, başarı ölçütleri ve kaynak sonuçlar değişmez; dosya dışa aktarma kapsamı ayrıca seçilir.",
        "Filtreyi kaydet", "Geçerli stratejinin sonuç filtrelerini kaydeder; aynı ad varsa tanımı günceller."),
    "input_values": (
        "Metin değerlerini düzenle", "Denenecek değerler", "Aday metin değerlerini virgülle ayırarak yaz.",
        "Onay virgülle ayrılmış metni aday listesine dönüştürür. Boş parçalar çıkarılır; değerin türü ve kod seçenekleri kontrol edilir. Değerin içinde virgül varsa bu düzenleyici onu ayrı adaylara böler. Eski liste yalnız geçerli ve boş olmayan seçimle değiştirilir; test başlamaz.",
        "Değerleri uygula", "Geçerli metin adaylarını seçili ayarın listesine aktarır; test başlatmaz."),
    "provider_symbol": (
        "Alternatif sağlayıcı", "Tam TradingView sembolü", "Alternatif sağlayıcının kodunu yaz; örneğin FX:EURUSD.",
        "Onay seçili doğrulanmış ve elenmemiş sonuçlar için sağlayıcı ve ek doğrulama görevleri hazırlayabilir. Bulunan görevler doğrudan başarılı sayılmaz; motoru kendiliğinden başlatmaz. Veri erişimi ve gerçek sembol/dönem/ayar uygulaması ayrıca doğrulanır.",
        "Doğrulama görevlerini hazırla", "Seçili uygun sonuçlar için doğrulama görevlerini kuyruğa hazırlamayı onaylar; motoru başlatmaz."),
}


def ask_text(parent, coordinator, key, *, title=None, text=""):
    """Return text/confirmation only; callers retain all validation and writes."""
    heading, label, short, detail, action, action_help = PROMPTS[key]
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title or heading)
    dialog.resize(480, 240)
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.addWidget(QtWidgets.QLabel(label))
    field = QtWidgets.QLineEdit(text)
    field.setObjectName("textPromptValue")
    field.setAccessibleName(label)
    layout.addWidget(field)
    note = QtWidgets.QLabel(detail)
    note.setWordWrap(True)
    layout.addWidget(note)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    confirm = buttons.button(QtWidgets.QDialogButtonBox.Ok)
    confirm.setText(action)
    cancel = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
    cancel.setText("Vazgeç")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    scope = coordinator.child_scope(dialog)
    dialog.help_registry = scope
    feature = "text." + key
    scope.register(HelpSpec(feature + ".value", 1, label, short, detail, field))
    scope.register(HelpSpec(feature + ".scope", 1, "Onayın etkisi", action_help, detail, note))
    scope.register(HelpSpec(feature + ".apply", 1, action, action_help, detail, confirm))
    scope.register(HelpSpec(feature + ".cancel", 1, "Değişiklikten vazgeç",
                           "Bu metin girişini uygulamadan kapatır.",
                           "Mevcut plan, kayıtlar ve sonuçlar korunur. Rehberde gezinmek onay yerine geçmez.", cancel))
    scope.register_tour(TourSpec(feature, 1, ((field, label, detail, None),)))
    guide = QtWidgets.QPushButton("Bu işlemin rehberi (?)")
    guide.clicked.connect(lambda: scope.start_tour(feature))
    layout.addWidget(guide)
    scope.register(HelpSpec(feature + ".guide", 1, "Metin girişi rehberi",
                           "Bu işlemin etkisini açıklayan popup rehberini yeniden açar.",
                           "Rehber metin yazmaz, kayıt yapmaz veya görev oluşturmaz.", guide))
    field.setFocus()
    QtCore.QTimer.singleShot(0, scope, lambda: scope.start_tour(feature, automatic=True))
    try:
        accepted = dialog.exec() == QtWidgets.QDialog.Accepted
        return field.text(), accepted
    finally:
        scope.finish_scope()
        dialog.deleteLater()
