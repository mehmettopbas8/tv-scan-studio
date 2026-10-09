"""Explicit user-facing help, kept separate from scan implementation."""
from .help_system import HelpSpec, TourSpec


def register_main_actions_help(studio):
    """Explicit navigation/action help; never infer descriptions from labels."""
    registry = studio.help_registry
    register_strategy_events_help(studio)
    register_dashboard_help(studio)
    for feature, name, title, short, detail in (
        ("results.detail_float", "qt_dockwidget_floatbutton", "Ayrıntı panelini ayrı pencereye taşı",
         "Sonuç ayrıntı panelini ayrı pencere ile yan panel arasında taşır.",
         "Bu işlem yalnız pencere yerleşimini değiştirir. Sonuçları veya ayarları değiştirmez; tarama başlatmaz."),
        ("results.detail_close", "qt_dockwidget_closebutton", "Ayrıntı panelini kapat",
         "Sonuç ayrıntı panelini gizler.",
         "Test ve kanıt kayıtları silinmez; tarama durmaz. Sonuç tablosundaki satırı yeniden açarak ayrıntıları gösterebilirsin."),
    ):
        target = studio.result_detail_dock.findChild(studio.QtWidgets.QAbstractButton, name)
        if target is not None:
            registry.register(HelpSpec(feature, 1, title, short, detail, target))
    for index, key, short, detail in (
        (1, "strategies", "Kayıtlı stratejileri ve kod ekleme ekranını açar.", "Burada Pine kodunu inceleyip yerel strateji kaydı oluşturabilirsin. Ekranı açmak TradingView grafiğini değiştirmez veya tarama başlatmaz."),
        (2, "scan", "Strateji, test koşulları ve denenecek ayarları hazırlama ekranını açar.", "Sembol, zaman dilimi ve aday değerleri seç; özeti kontrol et. Bu gezinme düğmesi görev eklemez. Hazırla ve başlat ayrı doğrulama ve onay gerektirir."),
        (4, "results", "Tarama ilerlemesini ve kayıtlı sonuçları gösterir.", "Sonuçları incelemek, filtrelemek veya bir satırı seçmek yeni test başlatmaz. Dışa aktarmada kapsam ayrıca seçilir; başarılı sonuç gelecekte kazanç garantisi değildir."),
    ):
        target = studio.nav_group.button(index)
        registry.register(HelpSpec("navigation." + key, 1, target.text(), short, detail, target))
    entries = (
        ("navigation.settings", "settings_navigation_button", "Genel ayarlar", "Genel ayarları ayrı pencerede açar.", "Bağlantı bekleme, bildirim ve araştırma arşivi seçeneklerini burada bulabilirsin. Pencereyi açmak mevcut test planını değiştirmez."),
        ("strategy.analyze", "strategy_analyze_button", "Ayarları tekrar oku", "Yapıştırılmış Pine kodundaki ayarları yeniden analiz eder.", "Kod değişikliklerini yerel ayar listesine yansıtır. Bu analiz kodu kaydetmez, derleme başarısını veya TradingView'de çalışan stratejiyi doğrulamaz."),
        ("strategy.copy", "strategy_copy_button", "Kopya oluştur", "Aynı Pine kaynağı için bilerek ayrı bir yerel strateji kaydı oluşturur.", "Normal kaydetme aynı kaynak için mevcut kaydı kullanır. Ayrı çalışma istiyorsan bu düğmeyi kullan; mevcut kayıt ve sonuçlar korunur. TradingView scripti kopyalanmaz veya yayımlanmaz."),
        ("strategy.technical", "strategy_technical_toggle", "Kod ayarı ayrıntıları", "Ayar tablosundaki değişken, tür, sınır ve teknik sütunları açar.", "Sütunları göstermek Pine değerlerini değiştirmez. Kodda sınır veya açıklama yoksa uygulama bunu doğrulanmış bilgi gibi tamamlamaz."),
        ("scan.project_search", "project_search_button", "Kayıtlı strateji ara", "Kayıtlı stratejiler arasında arama ve seçim penceresini açar.", "Arama yapmak kayıtları veya kuyruğu değiştirmez. Seçimi onayladıktan sonra bu stratejinin ayar ve test kapsamını kontrol et."),
        ("scan.symbol_select", "symbol_select_button", "Sembol seç", "Test edilecek piyasaları arayıp seçme penceresini açar.", "Sağlayıcı ve tam sembol kodunu kontrol et; örneğin BIST:XU030D1!. Her seçili sembol ayrı kombinasyonlar oluşturur. Pencereyi açmak mevcut kişisel grafiği değiştirmez."),
        ("scan.timeframe_select", "timeframe_select_button", "Zaman dilimi seç", "15 dakika veya 1 saat gibi mum sürelerini seçme penceresini açar.", "Birden fazla zaman dilimi test sayısını çarpar. Seçimi onaylamadan mevcut kapsam değişmez; bu düğme tarama başlatmaz."),
        ("scan.date_select", "date_select_button", "Test dönemi seç", "İsteğe bağlı başlangıç ve bitiş tarihi seçimini açar.", "Boş tarihler erişilebilen geçmişi kullanır. Özel dönem plan önizlemesidir; TradingView tarih desteği ve rapor dönemi doğrulanmadan o dönemin test edildiği kabul edilmez."),
        ("scan.discovery", "strategy_discovery_button", "Açık stratejiyi bul", "TradingView bağlantısında görünen stratejileri okur.", "Bir stratejinin bulunması kaynak eşliği veya taramaya hazır olduğu anlamına gelmez. Bağlantı ve tam kaynak kimliği ayrıca doğrulanır; bu düğme kişisel grafiğe strateji eklemez."),
        ("scan.strategy_choice", "strategy_picker", "TradingView strateji seçimi", "Bulunan stratejilerden bu planla bağlanacak olanı seçer.", "Benzer ad veya aynı ayar yapısı tek başına yeterli değildir. Tam kaynak kimliği ve hazırlık durumu onaylanmadan test başlamaz."),
        ("results.filters_open", "result_filter_toggle", "Sonuç filtrelerini aç", "Metrik, sembol, dönem ve kanıt filtrelerini gösterir.", "Paneli açmak sonuç silmez veya testleri yeniden değerlendirmez. Filtreler görünümü daraltır; dışa aktarma kapsamını ayrıca kontrol et."),
        ("results.save_filter", "result_save_filter_button", "Filtreyi kaydet", "Geçerli görünüm filtrelerini bir adla yerel olarak kaydeder.", "Kaydedilen filtre yeni test veya sonuç kopyası değildir. Sonradan seçtiğinde aynı filtre koşulları uygulanır; kaynak sonuçlar değişmez."),
        ("results.stop", "results_stop_button", "Taramayı durdur", "Yeni görev alımını durdurur ve çalışan işlerin güvenli bitişini bekler.", "Durduruluyor ile Durdu farklı durumlardır. Sonuçlar silinmez; tamamlanan işler korunur. Bu düğme TradingView uygulamasını kapatmaz."),
        ("results.presets_open", "saved_presets_button", "Kaydettiğim presetler", "Sonuçlardan kaydettiğin ayar paketlerini ayrı pencerede gösterir.", "Preset geçmişte kullanılan ayarların kaydıdır, kâr garantisi değildir. Listeyi açmak planı değiştirmez. Bir presetin ayarlarını taramaya taşımak ayrıca onay gerektirir; tarih ve maliyetleri yeniden kontrol et."),
        ("results.tasks_open", "tasks_backup_button", "Görevler ve yedekleme", "Görev durumu, filtreler ve yedekleme araçlarını ayrı pencerede açar.", "Pencereyi açmak görev eklemez veya yedek dosyası oluşturmaz. Yedek hedefini ve dahil edilecek dosyaları ayrıca seçersin; geri yükleme aktif verinin üzerine yazmadan ayrı hedefe yapılır."),
        ("results.history_open", "historical_scans_button", "Geçmiş taramalar", "Yerel geçmiş tarama arşivini inceleme ve dışa aktarma penceresini açar.", "Arşivdeki kayıtlar güncel tarama kuyruğu değildir. Arşiv seçimi ve yükleme ayrı işlemdir; geçmiş kayıtları açmak yeni TradingView testi başlatmaz veya eski kanıtı yeniden doğrulamaz."),
        ("results.run_history", "run_history_button", "Koşu ve deneme geçmişi", "Bu veritabanındaki tarama koşularını ve sonuçsuz görevlerin denemelerini açar.", "Sayfalı liste bütün görevlere erişir; eski sonuçlar silinmez. Pencereyi açmak tarama başlatmaz veya yeniden sıraya alma işlemi yapmaz."),
        ("scan.measure_resources", "parallel_measure_button", "Paralellik önerisini ölç", "Bilgisayar kaynaklarından bir paralel grafik sayısı önerisi çıkarır.", "Ölçüm worker sayısını kendiliğinden değiştirmez ve gerçek test/saat hızını ölçmez. Sonuçlar ekranındaki tamamlanan test hızını kullanarak seçimini değerlendir; daha fazla grafik her zaman daha hızlı değildir."),
        ("scan.resource_recommendation", "parallel_recommendation", "Kaynak önerisi", "Son kaynak ölçümünün grafik sayısı önerisini ve boş belleği gösterir.", "Öneri performans garantisi veya zorunlu sınır değildir. Paralel tarama grafiği sayısını kendin seçersin; ölçüm alınamadıysa önerinin hazır olduğu varsayılmaz."),
        ("scan.preparation_details", "preparation_details_button", "TradingView hazırlık ayrıntıları", "Bağlantı ve bağımsız test grafikleri için gelişmiş hazırlık araçlarını açar.", "Pencereyi açmak kişisel grafiklere müdahale etmez. Grafik bağlama ve oluşturma o penceredeki ayrı eylemlerdir; isim benzerliği veya sekme kopyası kaynak doğrulaması sayılmaz."),
        ("scan.edit_values", "edit_input_button", "Seçili değerleri düzenle", "Seçili ayarın denenecek değerlerini düzenleme penceresini açar.", "Önce ayar tablosundan bir satır seç. Değişiklik ancak düzenleme onaylanınca uygulanır; iptal mevcut değerleri korur. Bu düğme test başlatmaz."),
        ("scan.edit_detail_values", "input_detail_edit", "Seçili ayarın değerlerini düzenle", "Seçili ayarın aday değerlerini düzenlemeyi açar.", "Bu eylem özellikle sayısal aralık yerine açık değer listesi gereken ayarlarda kullanılır. Tür ve kod seçeneklerine uygun değerler seç; önerilen değerler doğrulanmış optimum değildir."),
        ("scan.preview_update", "plan_preview_button", "Tarama özetini güncelle", "Geçerli alanlardan kombinasyon sayısını ve eksik koşulları yeniden hesaplar.", "Özet güncelleme görev eklemez, ayarları TradingView grafiğine uygulamaz ve tarama başlatmaz. Büyük kısıtlı planların sayımı sürerken bekleme veya iptal durumu gösterilir."),
    )
    for feature, attribute, title, short, detail in entries:
        registry.register(HelpSpec(feature, 1, title, short, detail, getattr(studio, attribute)))
    for key, (_panel, button, dismiss, _label) in studio.usage_help.items():
        registry.register(HelpSpec("guide." + key, 1, button.text(),
            "Bu ekranın ilgili kontrollerini gösteren popup rehberini yeniden açar.",
            "Rehber yalnız açıklama gösterir. Kayıt, grafik hazırlama, kuyruklama veya dışa aktarma işlemini senin yerine yapmaz.", button))
        registry.register(HelpSpec("guide." + key + ".legacy_close", 1, "İpuçlarını kapat",
            "Eski satır içi ipuçları panelini kapatır.",
            "İpuçlarını kapatmak taramayı durdurmaz veya ayarları değiştirmez. Ekranın rehber düğmesiyle popup yardımı yeniden açabilirsin.", dismiss))
    for feature in ("strategy.copy", "strategy.technical", "results.filters_open",
                    "results.presets_open", "results.tasks_open", "results.history_open",
                    "scan.measure_resources", "scan.preparation_details"):
        spec = registry.specs[feature]
        registry.register_tour(TourSpec(feature, 1, ((spec.target, spec.title, spec.detail, None),)))
        registry.bind_first_use(spec.target, feature)


def register_strategy_events_help(studio):
    """Explain parsed source and recorded events without implying live proof."""
    registry = studio.help_registry
    entries = (
        ("strategy.inputs", studio.input_table, "Koddan okunan ayarlar",
         "Pine kodundaki ayar başlıklarını, varsayılan değerleri ve açıklamaları gösterir.",
         "Bu tablo salt okunurdur. Varsayılan, koddaki başlangıç değeridir; açık TradingView grafiğindeki mevcut değeri kanıtlamaz. Denenecek değerleri Tarama ekranında seç. Teknik sütunları Kod ayarı ayrıntıları ile açabilirsin."),
        ("strategy.status", studio.project_status, "Kod analizi ve kayıt durumu",
         "Yerel kod analizinin veya strateji kaydının durumunu gösterir.",
         "Hazır ifadesi yerel olarak okunabilen ayar bilgisidir; Pine derlemesi, canlı grafik veya tarama sonucu doğrulaması değildir. Okunamayan değer varsa kaydetmeden ve taramadan önce açıklamayı kontrol et."),
        ("results.events", studio.events_table, "Tarama olayları",
         "Son olay kayıtlarının seviye, çalışma kaynağı, görev ve mesaj bilgilerini gösterir.",
         "Olaylar sonuç metrikleri değil, işlem kayıtlarıdır. Bir uyarı tek başına tüm testlerin başarısız olduğunu göstermez. Mesaj hücresinin üzerine gelerek teknik ayrıntıyı inceleyebilirsin. Liste son 100 olay içinden seçili stratejinin görevlerine göre süzülür; tam hata geçmişi olduğu varsayılmamalı."),
        ("results.guide", studio.results_help_button, "Sonuç okuma rehberi",
         "Sonuç tablosu ve grafiklerini açıklayan popup rehberini yeniden açar.",
         "Rehber sonuçları değiştirmez veya tarama başlatmaz. Metrikleri, uygulanan ayarları ve doğrulama kanıtını birlikte incele; geçmiş kazanç gelecek performansı garanti etmez."),
        ("results.guide_close", studio.results_help_dismiss, "Sonuç ipuçlarını kapat",
         "Satır içi sonuç ipuçlarını kapatır.",
         "İpuçlarını kapatmak sonuçları silmez ve taramayı durdurmaz. Grafikleri nasıl okuyacağım düğmesiyle popup rehberini yeniden açabilirsin."),
    )
    for feature, target, title, short, detail in entries:
        registry.register(HelpSpec(feature, 1, title, short, detail, target))
    columns = (
        ("strategy.inputs", studio.input_table, (
            ("Değişken", "Pine kodundaki teknik ayar adıdır; kullanıcı başlığıyla aynı olmak zorunda değildir."),
            ("Başlık", "Kodun kullanıcıya gösterdiği ayar adıdır; açıklama yoksa anlamı uygulama tarafından uydurulmaz."),
            ("Tür", "Koddan okunan değer türüdür; örneğin tam sayı, ondalık sayı veya seçim."),
            ("Varsayılan", "Pine kodundaki başlangıç değeridir; canlı grafikte değiştirilmiş değer olabilir."),
            ("Seçenekler", "Kodda tanımlanmış seçim değerleridir; boş olması önerilen seçeneklerin kanıtı değildir."),
            ("Min/Max/Adım", "Kodda bulunan alt sınır, üst sınır ve adımdır; çizgi ilgili bilginin kodda bulunmadığını belirtir."),
            ("Grup", "Kodun ayarları topladığı bölüm adıdır; test grubu veya sonuç sınıfı değildir."),
            ("Tooltip", "Pine kodunun ayar için sağladığı açıklamadır; uygulamanın doğrulanmış performans önerisi değildir."),
            ("Durum", "Yerel ayrıştırmanın değer ve ek bilgi durumudur; Hazır canlı test doğrulaması değildir."),
        )),
        ("results.events", studio.events_table, (
            ("Seviye", "Olayın bilgi, uyarı veya hata düzeyidir; sonuç başarı sınıfı değildir."),
            ("Worker", "Olayı üreten çalışma kaynağının referansıdır; aktif worker sayısı değildir."),
            ("Görev", "Olayın bağlı olduğu test görevinin referansıdır; çizgi görev bağlantısı olmadığını belirtir."),
            ("Mesaj", "Olayın kullanıcı açıklamasıdır; hücre tooltipinde varsa ham teknik ayrıntı bulunur."),
            ("Ekran görüntüsü", "Özgün kanıt yolu salt okunur korunur. Yeni konumu ve checksum kontrolünü görmek için hücreye çift tıkla. Sayfa yenileme dosyaları doğrulamaz; çizgi dosya kaydı olmadığını belirtir."),
        )),
    )
    for feature, table, explanations in columns:
        registry.register_columns(feature, table, tuple(
            (title, short, short + " Bu salt okunur sütun ayarı veya kayıtları değiştirmez.")
            for title, short in explanations))
        spec = registry.specs[feature]
        registry.register_tour(TourSpec(feature, 1, ((table, spec.title, spec.detail, None),)))
        registry.bind_first_use(table, feature)


def register_dashboard_help(studio, registry=None):
    """Preserve explicit explanations when management is reparented to a dialog."""
    registry = registry or studio.help_registry
    entries = (
        ("management.projects", studio.project_table, "Kayıtlı projeler", "Projelerin durumunu, önceliğini ve görev ilerlemesini gösterir.", "Bir satır seçmek görevi değiştirmez. İlerleme hata, inceleme ve iptal durumlarını da içerir; yüzde 100 tüm testlerin başarıyla doğrulandığı anlamına gelmez."),
        ("management.events", studio.dashboard_events, "Son işlem kayıtları", "Son sekiz olayın seviye, çalışma kaynağı ve görev bilgisini gösterir.", "Bu kısa liste tüm geçmiş değildir. Teknik olay mesajı tek başına test başarısını veya tüm görevlerin başarısızlığını kanıtlamaz."),
        ("management.speed", studio.throughput_label, "Son beş dakikanın hızı", "Etkin tarama koşusunun doğrulanmış test/saat hızını gösterir.", "Eski koşular ve doğrulanmamış sonuçlar dahil edilmez. En az 5 doğrulanmış sonuç ve 60 saniye aktif test süresi gerekir. Paralel süreler birleştirilir; duraklamalar çıkarılır. Kaynak önerisi veya başka bilgisayardaki hız bu ölçümün yerine geçmez."),
        ("management.eta", studio.eta_label, "Kalan süre tahmini", "Etkin taramanın kalan görevlerini son beş dakika hızına göre tahmin eder.", "Yeterli doğrulanmış veri ve aynı sembol, zaman dilimi, dönem ve maliyet bağlamı gerekir. Çizgi, karşılaştırılabilir ölçüm olmadığını belirtir. Kaynak kullanımının veya test süresinin değişmesi tahmini etkiler; bitiş garantisi değildir."),
        ("management.priority", studio.project_priority, "Proje önceliği", "Seçili projeye uygulanacak görev önceliğini belirler.", "Yüksek öncelik önce alınır. Değer ancak Projeyi güncelle ile kaydedilir; alanı değiştirmek çalışan görevi kesmez veya kendi başına tarama başlatmaz."),
        ("management.state", studio.project_state, "Proje durumu", "Seçili projeye uygulanacak yönetim durumunu seçer.", "Seçim Projeyi güncelle ile kaydedilir. Durum etiketi bir testin doğrulandığının kanıtı değildir; çalışan taramayı durdurmak için Durdur eylemini kullan."),
        ("management.update", studio.dashboard_project_actions[2], "Projeyi güncelle", "Seçili projenin öncelik ve durumunu kaydeder.", "Önce proje tablosunda satır seç ve iki alanı kontrol et. Kuyrukta çalışmaya uygun proje durumları görev alınmasını etkileyebilir; bu eylem yeni test oluşturmaz veya tarama motorunu başlatmaz."),
        ("management.cancel", studio.dashboard_project_actions[3], "Bekleyenleri iptal et", "Seçili projenin bekleyen görevlerini iptal eder ve proje durumunu iptal olarak kaydeder.", "Çalışan görevler bu eylemle kesilmez, sonuçlar silinmez. Sonradan yeniden sırala iptal edilmiş görevleri de beklemeye alabilir. Tarama motorunu durdurmak ayrı işlemdir."),
        ("management.retry", studio.dashboard_project_actions[4], "Görevleri yeniden sırala", "Seçili projenin hata, inceleme ve iptal görevlerini tekrar beklemeye alır.", "Düğme adı Hatalıları yeniden sırala olsa da iptal görevleri de dahildir. Önce hata nedenini kontrol et; tamamlanan görevler ve sonuçlar silinmez. Görev varsa proje kuyruğa alınır; motor kendiliğinden başlamaz."),
        ("management.backup", studio.dashboard_backup_button, "Yedek oluştur", "Yedek kapsamı ve hedef dosyası seçimini açar.", "Veritabanı ve seçtiğin ek dosyalar taşınabilir yedeğe alınır. Yedek oluşturma tarama doğruluğunu kanıtlamaz; dosya kapsamını ve tamamlanma mesajını kontrol et."),
        ("management.restore", studio.restore_backup_button, "Yedeği ayrı dosyaya aç", "Yedeği mevcut veritabanının üzerine yazmadan yeni hedefe geri yükler.", "Yeni dosya hedefini seç. Aktif veri otomatik değiştirilmez; geri yükleme kanıt dosyalarının ve kayıtların doğrulandığı ayrı işlemdir."),
        ("management.setup", studio.dashboard_setup_action, "Strateji veya tarama ekranına git", "Hazırlık durumuna göre strateji ekleme ya da tarama ekranını açar.", "Düğmenin güncel metni sonraki ekranı belirtir. Bu geçiş görev üretmez, grafik değiştirmez veya tarama başlatmaz."),
        ("management.status", studio.dashboard_status, "Proje işlemi durumu", "Son proje yönetimi veya yedekleme işleminin mesajını gösterir.", "Mesajın kapsamını kontrol et; projenin güncellenmesi testlerin tamamlandığı anlamına gelmez."),
    )
    for feature, target, title, short, detail in entries:
        registry.register(HelpSpec(feature, 1, title, short, detail, target))
    for key, title, explanation in (
        ("projects", "Proje sayısı", "Kayıtlı proje sayısını gösterir; tıklamak proje listesine odaklanır."),
        ("pending", "Bekleyen görevler", "Kuyrukta bekleyen görev sayısıdır; tıklamak bu durumdaki görev listesini açar."),
        ("running", "Çalışan görevler", "Şu an işlemde olan görev sayısıdır; tıklamak bu durumdaki kayıtları gösterir."),
        ("done", "Tamamlanan görevler", "Tamamlanmış görev sayısıdır; başarı sınıfıyla aynı şey değildir. Tıklamak görev listesini açar."),
        ("failed", "Hata görevleri", "Hata durumundaki görev sayısıdır; tıklamak kayıtları gösterir, yeniden deneme yapmaz."),
        ("manual_review", "İnceleme görevleri", "İnceleme gerektiren görev sayısıdır; doğrulanmış başarı sayılmaz. Tıklamak kayıtları gösterir."),
    ):
        registry.register(HelpSpec("management.count." + key, 1, title, explanation,
                                  explanation + " Listeyi açmak görevleri veya sonuçları değiştirmez.", studio.metric_labels[key]))
    for feature, table, columns in (
        ("management.projects", studio.project_table, (
            ("ID", "Yerel proje referansıdır; strateji adı değildir."),
            ("Proje", "Kayıtlı stratejinin kullanıcı adıdır."),
            ("Durum", "Projenin yönetim durumudur; kaynak veya test doğrulaması değildir."),
            ("Öncelik", "Görev seçim önceliğidir; yüksek değer önce alınır."),
            ("Görev", "Projeye bağlı toplam görev sayısıdır; sonuç sayısı değildir."),
            ("İlerleme", "Tamamlanan, hata/inceleme ve iptal görevlerini birlikte sayar. Tıklamak görevleri açar; yüzde 100 başarı garantisi değildir."),
        )),
        ("management.events", studio.dashboard_events, (
            ("Seviye", "Bilgi, uyarı veya hata seviyesidir; sonuç sınıfı değildir."),
            ("Worker", "Olayı üreten çalışma kaynağının referansıdır."),
            ("Görev", "Olayın bağlı olduğu test görevidir; çizgi bağlantı olmadığını belirtir."),
            ("Olay", "Kayıtlı teknik işlem mesajıdır; tek başına test sonucu değildir."),
        )),
    ):
        registry.register_columns(feature, table, tuple(
            (title, short, short + " Tablo salt okunurdur; kayıtları bu sütunda değiştiremezsin.")
            for title, short in columns))


def register_scan_results_help(studio):
    registry = studio.help_registry
    entries = (
        ("scan.project", "plan_project", "Taranacak strateji", "Bu planın hangi kayıtlı stratejiye ait olduğunu seçer.", "Strateji değiştirmek bir tarama başlatmaz. Başlatmadan önce ayar listesini ve tarama özetini tekrar kontrol et."),
        ("scan.symbol_profile", "symbol_profile", "Sembol grubu", "Hazır bir sembol grubunu test kapsamına ekler.", "Grup seçimi sembol listesini değiştirebilir. Sağlayıcı ve sembol adlarını kontrol et; grup adı başarı garantisi değildir."),
        ("scan.timezone", "analysis_timezone", "İşlem analizi saat dilimi", "İşlem zamanlarının analizinde kullanılacak saat dilimini seçer.", "Bu seçim Pine stratejisinin seans ayarını veya bilgisayar saatini değiştirmez. Günlere göre işlem incelemesini yorumlarken saat dilimini dikkate al."),
        ("scan.date_from", "date_from", "Başlangıç tarihi", "Test dönemi için isteğe bağlı başlangıç tarihidir.", "Boş bırakıldığında erişilebilen geçmiş kullanılır. Özel tarih yalnız doğrulanmış tarih desteği varsa çalıştırılır; plan önizlemesi TradingView'e uygulandığının kanıtı değildir."),
        ("scan.date_to", "date_to", "Bitiş tarihi", "Test dönemi için isteğe bağlı bitiş tarihidir.", "Başlangıçtan önce olamaz. Tarih desteği doğrulanmadan bu dönemin gerçekten test edildiği kabul edilmez."),
        ("scan.input_table", "plan_inputs", "Denenecek ayarlar", "Her ayarın sabit kalacağını veya farklı değerlerle test edileceğini seçer.", "Birden fazla ayarı taramak kombinasyon sayısını çarpar. Öneriler başlangıç içindir; doğrulanmış en iyi değerler değildir. Ayrıntıları görmek için satır seç."),
        ("scan.input_mode", "input_detail_mode", "Ayarın tarama kararı", "Seçili ayarı sabit tutar, tarar veya tarama değişikliğinden hariç tutar.", "Farklı değerleri dene seçimi aday değerleri kullanır. Sabit tut mevcut değeri korur; hariç tutmak Pine kodundan ayarı silmez."),
        ("scan.range_start", "input_range_start", "Aralık başlangıcı", "Seçili sayısal ayarda denenecek ilk değerdir.", "Değer ayarın türü ve kodda belirtilen sınırlarla uyumlu olmalıdır. Aralığı uygula düğmesiyle listeyi güncelle; tarama henüz başlamaz."),
        ("scan.range_stop", "input_range_stop", "Aralık bitişi", "Seçili sayısal ayarda denenecek son sınırdır.", "Başlangıç, bitiş ve adım birlikte değer listesini üretir. Oluşan listeyi başlatmadan önce kontrol et."),
        ("scan.range_step", "input_range_step", "Aralık adımı", "Denenecek değerler arasındaki artışı belirler.", "Pozitif ve ayar türüne uygun bir sayı kullan. Küçük adımlar daha fazla test üretir; daha iyi sonuç garantisi değildir."),
        ("criteria.open", "criteria_toggle", "Başarı ölçütleri", "Bir testin hangi koşullarda başarılı sayılacağını gösterir.", "Bu eşikler sonuçları değerlendirmek içindir; Pine stratejisinin giriş, çıkış veya risk mantığını değiştirmez. Geçmiş başarı gelecekte kazanç garantisi değildir."),
        ("criteria.trades", "min_trades", "Asgari işlem sayısı", "Başarılı kabul için gereken en az işlem sayısıdır.", "Az sayıda işlem içeren sonuçlar daha sınırlı kanıt sunar. Bu eşik stratejiye işlem açtırmaz."),
        ("criteria.pf", "min_pf", "Asgari kâr faktörü", "Başarılı kabul için gereken kâr faktörü alt sınırıdır.", "Kâr faktörü toplam kazancın toplam kayba oranıdır. Tek başına işlem sayısı, düşüş veya kaynak doğrulamasının yerine geçmez."),
        ("criteria.win", "min_win", "Asgari kazanma oranı", "Başarılı kabul için kazançla kapanan işlemlerin en az yüzdesidir.", "Yüksek kazanma oranı tek başına pozitif net sonuç anlamına gelmez; kazanç ve kayıp büyüklükleri de önemlidir."),
        ("criteria.dd", "max_dd", "Azami düşüş", "Başarılı kabul için sermaye düşüşü üst sınırıdır.", "Rapordaki en yüksek sermayeden sonraki en büyük düşüş yüzdesi bu eşikle karşılaştırılır. Bu alan stratejiye zarar durdurma emri eklemez."),
        ("criteria.net", "min_net", "Asgari net sonuç", "Başarılı kabul için gereken net sonuç alt sınırıdır.", "Sonucun para birimi, sermayesi ve maliyet koşullarını birlikte incele. Farklı koşullardaki net tutarlar doğrudan karşılaştırılamaz."),
        ("criteria.risk", "ftmo_risk_check", "Gün içi kayıp kontrolü", "Günlük ve toplam kayıp ölçütlerini değerlendirmeye ekler.", "Gün içi sermaye kanıtı gerekir. Yalnız kapanmış işlemler veya özet rapor tüm gün içi kaybı kanıtlamaz; bu kontrol hesap kurallarına uygunluk garantisi değildir."),
        ("criteria.daily_loss", "max_daily_loss", "Günlük kayıp eşiği", "Günlük kayıp kontrolünde kullanılacak yüzde sınırıdır.", "Gün içi kayıp kontrolü etkin olduğunda düzenlenir. Yeterli sermaye kanıtı olmadan kurala uyulduğu varsayılmaz."),
        ("criteria.total_loss", "max_total_loss", "Toplam kayıp eşiği", "Toplam kayıp kontrolünde kullanılacak yüzde sınırıdır.", "Gün içi kayıp kontrolü etkin olduğunda düzenlenir. Bu eşik stratejinin işlem riskini değiştirmez."),
        ("costs.open", "advanced_cost_toggle", "Maliyet ve ayar eşlemesi", "Test sermayesi, pozisyon boyutu ve maliyet koşullarını gösterir.", "Strateji özellikleri ile Pine ayarları farklıdır. Bir Pine ayarını ancak gerçekten aynı maliyeti temsil ettiğini biliyorsan eşle; isim benzerliği yeterli değildir."),
        ("costs.capital", "initial_capital", "Başlangıç sermayesi", "Testin başlangıç sermayesi değeridir.", "Para birimini ve strateji özelliklerini kontrol et. Sermayeyi değiştirmek risk yüzdesi ayarını otomatik değiştirmez."),
        ("costs.position", "position_size", "Pozisyon boyutu", "Testte kullanılan pozisyon büyüklüğü değeridir.", "Birim ve miktar türü stratejinin özelliklerine bağlıdır. Bu değer risk bütçesi yüzdesiyle aynı değildir."),
        ("costs.commission", "commission", "Komisyon", "Testin yüzde komisyon değeridir.", "Sıfır komisyon maliyet olmadığı varsayımıdır. Gerçek işlem koşulları veya farklı komisyon türleriyle karıştırma; uygulanan değerin doğrulanması gerekir."),
        ("costs.slippage", "slippage", "Kayma", "Testteki fiyat kaymasını tick cinsinden belirtir.", "Tick sembolün en küçük fiyat adımıdır. Sıfır kayma gerçek işlemlerde kayma olmayacağını kanıtlamaz."),
        ("costs.spread", "spread", "Alış-satış farkı", "Spread için testte kullanılacak değerdir.", "Spread'in Pine stratejisinde doğru karşılığı bulunmalıdır. Eşleme ve birim doğrulanmadan değerin gerçekten uygulandığı kabul edilmez."),
        ("costs.scenario", "cost_scenario", "Maliyet senaryosu", "Hazır veya kayıtlı maliyet koşullarını seçer.", "Bir stres senaryosu seçmek sıfır olan maliyeti kendiliğinden gerçekçi yapmaz. Komisyon, kayma ve spread değerlerini ve eşlemelerini kontrol et."),
        ("scan.sessions", "session_variants_check", "Seans varyantları", "Seçili sembol ve zaman dilimindeki seans paketlerini test kapsamına ekler.", "Kayıtlı plan yüklenince özgün paketler korunur; güncel arşivden yeniden hesaplanmaz. Yeni seçimde yalnız kaynakla eşleşen araştırma paketleri kullanılır. Kayıtlı paketlerin sembol veya zaman dilimini değiştirirsen bu seçimi kapat. Yeni seans keşfetmez; görev sayısı artabilir."),
        ("results.project", "result_project", "Sonuç stratejisi", "Sonuçlarını görmek istediğin stratejiyi seçer.", "Bu seçim kayıtları değiştirmez veya yeni tarama başlatmaz. Dışa aktarmadan önce seçili strateji ve kapsamı kontrol et."),
        ("results.class", "result_filter", "Sonuç sınıfı", "Görüntülenen sonuçları değerlendirme sınıfına göre süzer.", "Başarılı, dayanıklı ve hassas sınıfları geçmiş değerlendirmelerdir. Filtre kayıt silmez ve gelecekte kâr garantisi oluşturmaz."),
        ("results.saved_filter", "saved_result_filter", "Kayıtlı filtre", "Daha önce kaydettiğin sonuç filtrelerini uygular.", "Filtre seçmek yalnız görünümü değiştirir. Veri veya test ayarları yeniden hesaplanmaz."),
        ("results.clear", "result_clear_filters", "Filtreleri temizle", "Etkin sonuç filtrelerini kaldırır.", "Sonuçlar veya kayıtlı filtre tanımları silinmez. Daha geniş kapsamı görürsün; dışa aktarma kapsamını ayrıca seçersin."),
        ("results.table", "results_table", "Test sonuçları", "Test metriklerini ve doğrulama durumunu listeler.", "Bir satırı çift tıklayarak uygulanan ayarları ve rapor kanıtını incele. Birden fazla satır seçmek dışa aktarma veya karşılaştırma için seçim oluşturur."),
        ("results.chart", "result_scatter", "Sonuç grafiği", "Her noktayı bir test sonucu olarak gösterir.", "Noktayı seçerek testin ayrıntılarını aç. Doğrulanmış renk veya yüksek kâr, gelecekte kazanç garantisi değildir."),
        ("results.evidence", "filter_evidence", "Doğrulama filtresi", "Sonuçları test kanıtının doğrulama durumuna göre süzer.", "Doğrulanmış, ayar ve rapor kanıtı kontrol edildi demektir. Stratejinin risksiz veya gelecekte kârlı olduğu anlamına gelmez."),
        ("results.symbol", "filter_symbol", "Sembol filtresi", "Sonuçları girilen sembol metnine göre süzer.", "Yeni sembol taramaz. Yalnız kayıtlı sonuçlar içinde arama yapar."),
        ("results.timeframe", "filter_tf", "Zaman dilimi filtresi", "Sonuçları zaman dilimine göre süzer.", "Bu seçim yeni test üretmez veya grafiğin zaman dilimini değiştirmez."),
        ("results.cost", "filter_cost_scenario", "Maliyet filtresi", "Sonuçları kayıtlı maliyet senaryosuna göre süzer.", "Senaryo adının yanında gerçekten uygulanan değerleri de incele. Filtre mevcut sonuçların maliyetini değiştirmez."),
        ("results.date_enabled", "filter_dates", "Dönem filtresi", "Seçilen dönem filtresini açar veya kapatır.", "Bu bir sonuç görüntüleme filtresidir; TradingView test dönemini değiştirmez."),
        ("results.date_from", "filter_from", "Filtre başlangıcı", "Etkin dönem filtresinin başlangıç tarihidir.", "Dönem filtresi açıkken kullanılır. Test ayarlarını veya kayıtlı raporu değiştirmez."),
        ("results.date_to", "filter_to", "Filtre bitişi", "Etkin dönem filtresinin bitiş tarihidir.", "Dönem filtresi açıkken kullanılır. Görüntülenen ve dışa aktarılacak kapsamı kontrol et."),
        ("scan.prepare_saved", "prepare_saved_button", "Taramayı hazırla", "Kayıtlı stratejiyle Tarama ekranına geçer.", "Bu düğme grafikleri değiştirmez veya taramayı başlatmaz. Sonraki ekranda sembol, zaman dilimi ve denenecek değerleri kontrol et."),
        ("scan.range_apply", "apply_range_button", "Aralığı uygula", "Başlangıç, bitiş ve adımdan seçili ayarın değer listesini oluşturur.", "Yalnız bu ayarın tarama değerleri değişir. Oluşan listeyi ve toplam görev sayısını kontrol et; bu işlem testi başlatmaz."),
        ("scan.input_details", "input_detail_toggle", "Ayar ayrıntıları", "Seçili ayarın değer düzenleyicisini açar veya kapatır.", "Paneli açmak değerleri değiştirmez. Sayısal aralığı değiştirdikten sonra Aralığı uygula ile listeyi güncelle."),
        ("scan.advanced", "scan_advanced_toggle", "Gelişmiş ayarlar", "Maliyet, başarı ölçütü, seans ve hazırlık seçeneklerini açar.", "Bu bölümü açmak mevcut planı değiştirmez. Basit bir tarama için tüm gelişmiş seçenekleri düzenlemen gerekmez."),
        ("scan.missing", "missing_field_button", "Eksik alana git", "Tarama planındaki ilk eksik veya geçersiz alana gider.", "Eksik alanın yanındaki açıklamayı okuyup düzelt. Bu düğme bilgileri senin yerine doldurmaz veya tarama başlatmaz."),
        ("scan.stop", "scan_stop_button", "Durdur", "Yeni görev almayı durdurur; çalışan işlemin güvenli bitişini bekler.", "Durduruluyor durumunda arayüz kullanılabilir kalır. Mevcut sonuçlar silinmez; Durdu durumu çalışan işler gerçekten sona erince gösterilir."),
        ("costs.save", "save_cost_button", "Maliyet şablonunu kaydet", "Mevcut maliyet değerlerini adlandırılmış yerel şablon olarak saklar.", "Şablonu kaydetmek mevcut sonuçları yeniden hesaplamaz veya TradingView'de test başlatmaz. Şablonun birim ve eşlemelerini kullanmadan önce kontrol et."),
        ("results.export", "result_export_button", "Sonuçları dışa aktar", "Dosya türü ve kayıt kapsamı seçimiyle dışa aktarma penceresini açar.", "CSV ve Excel için uygun görev/sonuç kapsamını seç. PDF yalnız desteklenen başarılı sonuç kapsamını kullanır; ekrandaki filtre ile dışa aktarma kapsamını karıştırma."),
        ("results.compare", "result_compare", "Seçilenleri karşılaştır", "Seçtiğin 2–5 sonucun ayarlarını ve metriklerini yan yana gösterir.", "Kaynak, sembol, sağlayıcı, dönem, para birimi, sermaye ve maliyet farkları belirtilir. Eksik kanıt eşitlik sayılmaz; doğrulanmamış kayıtlarla karar verme. Karşılaştırma kayıtları değiştirmez veya test başlatmaz."),
        ("results.validate", "result_validate", "Aşamalı doğrula", "Seçili uygun sonuçlar için ek doğrulama görevleri hazırlamayı açar.", "Alternatif sağlayıcının tam TradingView sembolünü kontrol et. Yalnız doğrulanmış ve elenmemiş sonuçlar için görev eklenir; bu işlem sıradan bir görünüm filtresi değildir."),
        ("results.refine", "result_refine", "Adaylardan ayrıntılı tara", "Seçtiğin kaba tarama adaylarından ayrıntılı değer planı hazırlar.", "Önce Kaba→ince yönteminin kaba aşamasını tamamla. Aynı koşul ve kaynaktaki adayları kendin seç. Değerler açıkça onaylanmadan görev eklenmez; motor otomatik başlamaz."),
        ("results.period", "result_period", "Ayrı dönemde doğrula", "Seçtiğin eğitim adaylarını sabit ayarlarla sonraki ayrı dönemde doğrular.", "Aynı tamamlanmış seçim koşusundan doğrulanmış adayları seç. Tarihler açık onayla kilitlenir; dönemler çakışamaz. Doğrulama sonuçları aday seçimine geri karıştırılmaz; gelecekte kazanç garanti edilmez."),
        ("results.next_training", "result_next_training", "Sonraki eğitim dönemi", "Tamamlanmış ayrı dönem doğrulamasından sonraki eğitim penceresini hazırlar.", "Yeni eğitim önceki doğrulamadan sonra ayrıca onaylanır. Eski eğitim aralıkları korunur; doğrulamada kazanan ayar otomatik seçilmez. Her aşamanın önceki koşuya bağlantısı saklanır."),
        ("results.retry", "result_retry_button", "Hatalıları yeniden sırala", "Seçili stratejinin yeniden denenebilir hata görevlerini kuyruğa alır.", "Önce hata nedenini kontrol et. Bu eylem başarılı sonuçları silmez; yeniden denemek hatanın çözüldüğünü kanıtlamaz."),
        ("scan.summary", "plan_status", "Tarama özeti", "Planın hazır olup olmadığını ve eksik koşulları gösterir.", "Başlatmadan önce görev sayısını, strateji bağlantısını ve varsa hata açıklamasını kontrol et. Özet, testin tamamlandığı anlamına gelmez."),
        ("scan.factors", "plan_factors", "Kombinasyon sayısı", "Sembol, zaman dilimi ve aday ayarların toplam görev sayısına etkisini gösterir.", "Birden fazla değer içeren ayarlar birlikte çarpılır. Büyük sayı otomatik olarak kesilmez; kaynak ve süre ölçümünü dikkate al."),
    )
    for feature, attribute, title, short, detail in entries:
        target = getattr(studio, attribute)
        reason = None
        if attribute in ("max_daily_loss", "max_total_loss"):
            reason = lambda: (None if studio.ftmo_risk_check.isChecked() else "Gün içi kayıp kontrolünü etkinleştir.")
        elif attribute == "prepare_saved_button":
            reason = lambda: (None if studio.prepare_saved_button.isEnabled() else "Önce stratejiyi kaydet veya kayıtlı bir strateji seç.")
        elif attribute == "result_compare":
            reason = lambda: (None if studio.result_compare.isEnabled() else "Sonuç tablosundan 2–5 satır seç; fazlasını seçtiysen seçimi azalt.")
        elif attribute == "result_validate":
            reason = lambda: (None if studio.result_validate.isEnabled() else "Sonuç tablosundan bir sonuç seç; yalnız doğrulanmış ve elenmemiş kayıtlar işlenir.")
        elif attribute == "result_refine":
            reason = lambda: (None if studio.result_refine.isEnabled() else "Kaba koşudan aday seç ve devam eden hazırlığın bitmesini bekle.")
        elif attribute in {"result_period", "result_next_training"}:
            reason = lambda: (None if studio.result_period.isEnabled() else "İlgili tamamlanmış araştırma koşusundan sonuç seç ve hazırlığın bitmesini bekle.")
        registry.register(HelpSpec(feature, 1, title, short, detail, target, reason))
    for attribute, title, explanation in (
        ("filter_pf", "Kâr faktörü filtresi", "Kâr faktörü bu alt sınırın altında olan sonuçları görünümden çıkarır."),
        ("filter_dd", "Düşüş filtresi", "Sermaye düşüşü bu yüzde sınırını aşan sonuçları görünümden çıkarır."),
        ("filter_trades", "İşlem sayısı filtresi", "İşlem sayısı bu alt sınırın altında olan sonuçları görünümden çıkarır."),
        ("filter_win", "Kazanma oranı filtresi", "Kazançla kapanan işlem yüzdesi bu sınırın altında olan sonuçları görünümden çıkarır."),
        ("filter_net", "Net sonuç filtresi", "Net sonucu bu alt sınırın altında olan kayıtları görünümden çıkarır."),
    ):
        registry.register(HelpSpec("results." + attribute, 1, title, explanation,
                                  explanation + " Filtre kayıt silmez, strateji mantığını veya başarı ölçütlerini değiştirmez.", getattr(studio, attribute)))
    for key, target in studio.cost_input_choices.items():
        registry.register(HelpSpec("costs.mapping." + key, 1, "Maliyet ayarı eşlemesi",
                                  "Bu maliyetin Pine stratejisindeki doğrulanmış karşılığını seçer.",
                                  "Emin değilsen Eşleme yok bırak. Birim ve anlam aynı olmalıdır; örneğin trailing mesafesi pozisyon boyutu değildir.", target))
    for feature, attribute in (("criteria", "criteria_toggle"), ("costs", "advanced_cost_toggle")):
        target = getattr(studio, attribute)
        spec = registry.resolve(target)
        registry.register_tour(TourSpec(feature, 1, ((target, spec.title, spec.detail, None),)))
        registry.bind_first_use(target, feature)
    registry.register_columns("results.table", studio.results_table, tuple(
        (title, short, short + " Sonuç ayrıntısındaki ayar ve rapor kanıtlarıyla birlikte değerlendir.")
        for title, short in (
            ("Görev", "Bu test kaydının görev referansıdır; satırı çift tıklayarak ayrıntıları açabilirsin."),
            ("Sembol", "Test edilen piyasa ve veri sağlayıcısını gösterir."),
            ("Zaman dilimi", "Testin mum süresidir; örneğin 15, 15 dakikalık mumları belirtir."),
            ("Sınıf", "Başarı ölçütleriyle oluşturulan geçmiş değerlendirme sınıfıdır; kâr garantisi değildir."),
            ("İşlem", "Test raporundaki işlem sayısıdır."),
            ("Kâr faktörü", "Toplam kazancın toplam kayba oranıdır; tek başına yeterli kanıt değildir."),
            ("Kazanma oranı", "Kazançla kapanan işlemlerin yüzdesidir."),
            ("Düşüş", "En yüksek sermayeden sonraki en büyük düşüş yüzdesidir."),
            ("Net sonuç", "Rapordaki net sonuçtur; para birimi, sermaye ve maliyet koşulları önemlidir."),
            ("Kanıt", "Ayar ve rapor doğrulamasının durumudur; gelecekteki kazancı doğrulamaz."),
        )))
    registry.register_columns("scan.input_table", studio.plan_inputs, tuple(
        (title, short, short + " Kodda bulunmayan sınırlar veya açıklamalar doğrulanmış bilgi gibi varsayılmaz.")
        for title, short in (
            ("Teknik kimlik", "Pine ayarının iç kimliğidir; normal kullanımda adını seçmen yeterlidir."),
            ("Ayar", "Pine kodundan okunan kullanıcıya yönelik ayar adıdır."),
            ("Varsayılan", "Pine kodunda tanımlanan başlangıç değeridir; en iyi değer olduğu anlamına gelmez."),
            ("Karar", "Bu ayarın sabit tutulacağını veya aday değerlerinin deneneceğini belirler."),
            ("Tarama değerleri", "Farklı değerleri dene seçildiğinde gerçekten denenmesi planlanan değerlerdir."),
            ("Kaynak", "Değer önerisinin koddan veya tahmini öneriden geldiğini belirtir."),
            ("Not", "Kodda bulunan açıklamayı veya önerinin sınırını gösterir."),
        )))


def register_settings_help(studio, registry=None):
    registry = registry or studio.help_registry
    entries = (
        ("port", "settings_port", "TradingView bağlantısı", "Yerel TradingView bağlantısının kullandığı portu gösterir.", "Bu teknik bilgi salt okunurdur. Normal tarama akışında port girmen gerekmez; hazırlık bağlantıyı kontrol eder."),
        ("database", "settings_database", "Yerel veri dosyası", "Projelerin, görevlerin ve sonuçların saklandığı dosyayı gösterir.", "Bu alan dosyayı taşımaz veya silmez. Veri taşımak için yedekleme ve ayrı hedefe geri yükleme araçlarını kullan."),
        ("notifications", "notifications_enabled", "Bildirimler", "Uygulamanın Windows bildirimlerini açar veya kapatır.", "Windows'un kendi bildirim izni de gerekir. Bildirimleri kapatmak taramayı durdurmaz; durum uygulamada görünür kalır."),
        ("timeout", "default_timeout", "Azami bekleme", "Bir görevde raporun hazır olması için beklenecek süreyi saniye olarak belirler.", "Kısa süre yavaş raporları zaman aşımına düşürebilir. Uzun süre test doğrulamasının yerine geçmez; bu seçenek tek başına hızı artırmaz."),
        ("poll", "default_poll", "Kontrol sıklığı", "Rapor durumunun kaç saniyede bir kontrol edileceğini belirler.", "Daha sık kontrol kaynak tüketimini artırabilir. Bu ayar TradingView'in hesaplama süresini kısaltmaz."),
        ("stable", "default_stable", "Kararlı okuma sayısı", "Raporun kararlı sayılması için gereken ardışık okuma sayısıdır.", "Azaltmak eski veya değişen raporu kabul etme riskini artırabilir. Kaynak, ayar ve rapor kanıtı kontrolleri ayrıca uygulanır."),
        ("advanced", "settings_advanced_toggle", "Gelişmiş bağlantı ayarları", "Bekleme ve rapor kontrol seçeneklerini gösterir.", "Bu paneli açmak ayarları değiştirmez. Değişiklikleri Ayarları kaydet ile sakla; yalnız bir sorun araştırıyorsan varsayılanları değiştir."),
        ("save", "settings_save_button", "Ayarları kaydet", "Bekleme, kontrol ve bildirim tercihlerini yerel olarak saklar.", "Kaydetmek tarama başlatmaz veya geçmiş sonuçları yeniden hesaplamaz. Çalışan taramanın koşullarıyla karıştırma."),
        ("status", "settings_status", "Ayar durumu", "Ayar veya arşiv işleminin sonucunu gösterir.", "Başarı mesajı yalnız belirtilen işlem içindir; içe aktarma TradingView sonuçlarının yeniden doğrulandığı anlamına gelmez."),
        ("archive_import", "archive_import_button", "Araştırma arşivi içe aktar", "Desteklenen yerel araştırma kataloğunu seçip içe aktarır.", "İçe aktarılan geçmiş veriler kendi testlerinden ayrıdır ve yeniden test edilmiş sayılmaz. Dosyadaki kaynak ve dönem bilgisini kontrol et."),
        ("archive_open", "archive_open_button", "Araştırma arşivini aç", "İçe aktarılan araştırma kataloğunu inceleme penceresinde açar.", "Arşiv yoksa önce desteklenen katalog dosyasını içe aktar. Bu pencereyi açmak tarama veya sağlayıcı görevi başlatmaz."),
        ("support", "support_package_button", "Yerel destek paketi", "İçerik seçimi ve önizlemesiyle yerel ZIP oluşturma penceresini açar.", "Otomatik yükleme yoktur. Özel dosyalar kendiliğinden eklenmez; ek dosya seçimi ve gizlilik onayı ayrıca gerekir. Pencereyi açmak ZIP oluşturmaz."),
    )
    for key, attribute, title, short, detail in entries:
        reason = (lambda: None if studio.archive_open_button.isEnabled() else "Önce araştırma kataloğunu içe aktar.") if key == "archive_open" else None
        registry.register(HelpSpec("settings." + key, 1, title, short, detail, getattr(studio, attribute), reason))


def register_research_help(studio, registry=None):
    registry = registry or studio.help_registry
    entries = (
        ("table", "research_table", "Araştırma kayıtları", "İçe aktarılan geçmiş araştırmaların ayarlarını ve metriklerini listeler.", "Satır seçerek dönem, maliyet ve kaynak bilgisini incele. İçe aktarma bu kayıtları yeniden doğrulamaz; arşiv sonucu kendi yeni testin değildir."),
        ("project", "research_project", "Doğrulama stratejisi", "Sağlayıcı doğrulaması için kullanılacak kayıtlı stratejiyi seçer.", "Kaynak ve ayar yapısı araştırmayla eşleşmelidir. Strateji seçmek tek başına görev oluşturmaz."),
        ("symbol", "research_provider_symbol", "Alternatif sağlayıcı sembolü", "Doğrulamada kullanılacak sağlayıcının tam TradingView sembolüdür.", "Sağlayıcı kodu ve piyasanın gerçekten karşılaştırılabilir olduğunu kontrol et. Farklı piyasa veya sözleşme doğrudan eşdeğer sayılmaz."),
        ("prepare", "research_prepare_button", "Sağlayıcı görevlerini hazırla", "Seçili araştırma kayıtları için alternatif sağlayıcı test görevleri oluşturur.", "Bu eylem kuyruğa görev ekler; worker başlatmaz. Kaynağı, sembolü ve seçilen araştırma satırlarını önce kontrol et."),
        ("pdf", "research_pdf_button", "Araştırma PDF'i", "Mevcut araştırma kataloğunun desteklenen raporunu dışa aktarır.", "Bu rapor içe aktarılan araştırmayı anlatır. Eksik ham kayıtları tamamlamaz ve kendi tarama sonuçlarının tamamını içeren PDF değildir."),
        ("export", "research_export_button", "Arşiv kayıtlarını indir", "Mevcut arşiv kayıtlarını CSV veya Excel olarak dışa aktarır.", "Dosyadaki kayıt kapsamı arşivde gerçekten bulunan verilere bağlıdır. Özet sayılar eksik test satırlarını yeniden oluşturmaz."),
        ("raw", "research_raw_button", "Ham araştırma kayıtları", "Varsa yerel ham araştırma verisini dışa aktarır.", "Katalog içe aktarma ayrı ham kayıt dosyasını taşımaz. Dosya yokken ham test kayıtları varmış gibi sonuç üretilmez."),
        ("details", "research_details", "Araştırma ayrıntısı", "Seçili araştırmanın dönem, maliyet, ayar ve kanıt bilgilerini gösterir.", "Salt okunurdur. Burada görülen geçmiş metrikler tekrar test veya gelecekte kâr kanıtı değildir."),
        ("status", "research_status", "Araştırma durumu", "Arşivin veya sağlayıcı doğrulama işleminin durumunu gösterir.", "Kuyruğa alındı, tamamlandı veya doğrulandı farklı durumlardır. Yalnız görev hazırlanması doğrulamanın geçtiği anlamına gelmez."),
    )
    for key, attribute, title, short, detail in entries:
        target = getattr(studio, attribute)
        reason = None
        if key in ("prepare", "pdf", "export", "raw"):
            reason = lambda: None if studio._research_catalog.get("available", True) else "Desteklenen yerel araştırma kataloğunu önce içe aktar."
        registry.register(HelpSpec("research." + key, 1, title, short, detail, target, reason))


def register_task_dialog_help(registry, widgets):
    entries = (
        ("projects", "Strateji filtresi", "Görevleri seçilen stratejiye göre gösterir.", "Tüm stratejiler seçimi daha geniş görünüm sunar. Filtre görevleri değiştirmez veya iptal etmez."),
        ("states", "Görev durumu", "Bekleyen, çalışan veya tamamlanan görevleri durumuna göre süzer.", "İnceleme gerekli durumu otomatik başarı sayılmaz. Durum seçmek yeniden deneme veya tarama başlatmaz."),
        ("refresh", "Görevleri yenile", "Görev listesini yerel veritabanından tekrar okur.", "Bu düğme görev üretmez veya TradingView'e müdahale etmez. Listede gösterilen kayıt sınırı toplam görev sayısından farklı olabilir."),
        ("summary", "Görev sayısı", "Seçili kapsamdaki toplam görev ve gösterilen kayıt sayısını belirtir.", "Son kayıtların gösterilmesi eski görevlerin silindiği anlamına gelmez. Tam kapsamı dışa aktarırken ayrıca kontrol et."),
        ("table", "Görev listesi", "Görevlerin strateji, durum, sembol ve ayar özetini gösterir.", "Liste salt okunurdur. Başarısız veya sonuçsuz görevler başarılı tarama sonucu gibi değerlendirilmez."),
        ("status", "Yedekleme durumu", "Son yedekleme veya geri yükleme işleminin sonucunu gösterir.", "Hata açıklamasını işlem tamamlanmadan kapatma. Yedek oluşturmak canlı taramayı doğrulamaz."),
        ("backup", "Yedek oluştur", "Yerel veri için taşınabilir bir yedek dosyası oluşturur.", "Dosya hedefini seç. Yedeğin taşıdığı kayıt ve dosya kapsamını kontrol et; eksik dış dosyaların otomatik dahil olduğunu varsayma."),
        ("restore", "Yedeği ayrı dosyaya aç", "Yedeği aktif veritabanının üzerine yazmadan ayrı hedefe geri yükler.", "Yeni hedefi seç ve işlemin tamamlanmasını bekle. Geri yüklenen veriye geçmeden önce kayıtları ve eksik dosya uyarılarını kontrol et."),
        ("advanced", "Gelişmiş proje yönetimi", "Öncelik, iptal ve yeniden deneme araçlarına erişimi açar.", "Paneli açmak görevleri değiştirmez. İptal veya yeniden deneme gibi eylemlerin etkisini uygulamadan önce kontrol et."),
        ("management", "Proje yönetimini aç", "Görev önceliği ve durum işlemlerinin bulunduğu pencereyi açar.", "Bu düğme tek başına iptal veya yeniden deneme yapmaz. Görev değişiklikleri o penceredeki eylemlerle uygulanır."),
        ("close", "Pencereyi kapat", "Görevler ve yedekleme penceresini kapatır.", "Pencereyi kapatmak taramayı durdurmaz veya kayıtları silmez."),
    )
    for key, title, short, detail in entries:
        registry.register(HelpSpec("tasks." + key, 1, title, short, detail, widgets[key]))
    registry.register_tour(TourSpec("tasks_backup", 1, (
        (widgets["projects"], "Görevlerini incele", "Strateji ve durum filtreleri yalnız listeyi değiştirir. Toplam ve gösterilen kayıt sayıları ayrı belirtilir.", None),
        (widgets["backup"], "Yedek oluştur", "Yedek dosyasının hedefini bu düğmeyle seçebilirsin. Tur yedek oluşturmaz veya dosya seçmez.", None),
        (widgets["restore"], "Ayrı hedefe geri yükle", "Geri yükleme mevcut veritabanının üzerine yazmaz. Ayrı dosyayı ve işlem sonucunu kontrol et.", None),
    )))


def register_export_help(registry, widgets):
    entries = (
        ("kind", "Kaydedilecek kayıtlar", "Tüm görevleri veya yalnız başarılı ve doğrulanmış presetleri seçer.", "Başarısız ve teknik hata görevleri CSV/Excel ile alınabilir. PDF yalnız başarılı ve doğrulanmış sonuçları içerir."),
        ("scope", "Dosyanın kapsamı", "Tüm proje, ekranda görünen veya seçili sonuç satırları kapsamını belirler.", "Ekrandaki filtre tüm proje kapsamını sınırlamaz. Teknik hatalar yalnız görev kapsamındadır; seçili satır kapsamı yalnız gerçekten seçtiğin sonuçları taşır."),
        ("format", "Dosya türü", "CSV, Excel çalışma kitabı veya başarılı sonuç PDF'i seçer.", "Excel (.xlsx) sayısal hücreler ve filtrelerle doğrudan açılır. CSV açılışında karakter kodlaması ve ayraç seçimi gerekebilir. PDF tüm hata görevlerini kapsamaz."),
        ("count", "Kayıt sayısı önizlemesi", "Seçili kayıt türü ve kapsamın şu anki sayısını gösterir.", "Çalışan taramada sayı dosya kaydedilene kadar değişebilir. Sıfır sonuç, kapsamda uygun kayıt bulunmadığını gösterir; sonuç uydurulmaz."),
        ("note", "Kapsam açıklaması", "Seçilen dosya türünün ve kapsamın sınırlarını açıklar.", "Bu görünür açıklamayı kaydetmeden önce kontrol et. Başarılı sonuç dosyası bütün görevlerin yedeği değildir."),
        ("save", "Dosyayı kaydet", "Seçilen kapsam için hedef dosya seçimine geçer.", "Bu eylem yerel dosya oluşturur. Kayıtlar veya grafikteki ayarlar değiştirilmez; hedefi ve kayıt kapsamını kontrol et."),
        ("cancel", "Vazgeç", "Dışa aktarmayı dosya oluşturmadan kapatır.", "İptal etmek kayıtlı sonuçları silmez veya çalışan taramayı durdurmaz."),
    )
    for key, title, short, detail in entries:
        reason = (lambda: "PDF yalnız başarılı ve doğrulanmış sonuçları destekler; tüm görevler için CSV veya Excel seç."
                  if widgets["format"].currentText() == "PDF" else None) if key == "kind" else None
        registry.register(HelpSpec("export." + key, 1, title, short, detail, widgets[key], reason))
    registry.register_tour(TourSpec("export", 1, tuple(
        (widgets[key], title, text, None) for key, title, text in (
            ("scope", "Kayıt kapsamını seç", "Tüm proje, ekranda görünen veya seçili sonuç satırları farklı kapsamlardır. Önce istediğin kapsamı seç."),
            ("format", "Dosya türünü seç", "Excel sayısal veriler için uygundur. PDF yalnız başarılı ve doğrulanmış sonuçları içerir; tüm görevler PDF'e aktarılmaz."),
            ("save", "Sayımı kontrol edip kaydet", "Önizlemedeki kayıt sayısını kontrol et. Dosyayı kaydet ile hedefi seçebilirsin; bu rehber dosya kaydetmez."),
        ))))


def register_preparation_help(studio, registry=None):
    registry = registry or studio.help_registry
    entries = (
        ("path", "tv_executable", "TradingView yolu", "Yerel TradingView uygulamasının dosya yoludur.", "Bul düğmesi kurulu uygulamayı arar. Yol hatırlanır; güncellemeden sonra dosyanın geçerli olması yeniden kontrol edilmelidir."),
        ("find", "worker_find_tv", "TradingView'i bul", "Kurulu TradingView Desktop uygulamasının dosyasını bulur.", "Uygulamayı bulmak bağlantının hazır olduğu anlamına gelmez. Bağlantı durumunu ayrıca kontrol et."),
        ("open", "worker_open_tv", "TradingView bağlantısını hazırla", "TradingView'i yerel otomasyon bağlantısıyla açmayı dener.", "Bağlantısız açık oturumun yeniden başlatılması ayrıca onay gerektirir. Bağlanıyor durumu başarı değildir; Hazır veya İşlem gerekli sonucunu bekle."),
        ("motor_toggle", "worker_motor_toggle", "Gelişmiş motor yolu", "Harici tarama köprüsü yolunu düzenleme alanını açar.", "Normal kullanımda paket içindeki köprü kullanılır. Bu alanı yalnız hangi uyumlu motoru kullanacağını biliyorsan değiştir."),
        ("motor", "motor_path", "Harici motor yolu", "İsteğe bağlı harici tarama köprüsü dosyasının yoludur.", "Boş bırakılırsa paket içindeki köprü kullanılır. Rastgele dosya seçmek bağlantı veya tarama doğrulamasını sağlamaz."),
        ("project", "worker_project", "Atanacak strateji", "Hazırlık ve kaynak bağlama için kayıtlı stratejiyi seçer.", "Seçilmesi bütün grafikleri taramaya hazır yapmaz. Grafik kaynağı ve ayarları ayrıca doğrulanmalıdır."),
        ("measure", "worker_measure_button", "Kaynakları ölç", "Bilgisayarın kaynak kullanımını ölçerek paralellik önerisine yardımcı olur.", "Kaynak ölçümü test/saat ölçümü değildir. Gerçek hızı kontrollü tamamlanan testlerle karşılaştır."),
        ("resource", "resource_status", "Kaynak durumu", "Son kaynak ölçümünün sonucunu gösterir.", "Öneri hız garantisi değildir; strateji, rapor süresi ve diğer uygulamalar sonucu etkileyebilir."),
        ("count", "new_tab_count", "Yeni grafik sayısı", "Hazırlanması istenen yeni sekme sayısını belirler (1–16).", "Yeni sekme tek başına bağımsız ve doğrulanmış tarama grafiği sayılmaz. Kaynak ve grafik kimliği kontrolleri tamamlanmalıdır."),
        ("new_tabs", "worker_open_tabs", "Yeni sekmeler aç", "Yerel bağlantı oturumunda istenen sayıda yeni sekme açmayı dener.", "Açılma başarıyla taramaya hazır olmak farklıdır. Kopya sekmenin bağımsız kayıtlı grafik kimliği ve doğru stratejisi ayrıca doğrulanır."),
        ("claim", "worker_claim_tabs", "Hazır grafikleri bağla", "Desteklenen ayrı çalışma grafiklerini kullanıcı onayıyla bağlamayı açar.", "Kişisel grafikler tarama için kullanılmamalıdır. Aynı grafik kimliğini paylaşan kopyalar hazır sayılmaz; çakışma veya kaynak uyarılarını çöz."),
        ("bind", "worker_bind_button", "Kaynağı stratejiye bağla", "Seçili grafiğin strateji kaynağını kayıtlı projeyle doğrulama akışını açar.", "Yalnız ayar yapısının benzemesi yeterli değildir. Tam olarak hangi stratejiyi onayladığını kontrol et; yanlış kaynakla tarama başlatma."),
        ("discover", "worker_discover_button", "Sekmeleri bul", "Yerel bağlantıdaki grafiklerin hazırlık durumunu yeniden okur.", "Grafiklerin bulunması taramaya hazır olduğu anlamına gelmez. Hazırlık sütunu ve açıklanan sonraki adımı kontrol et."),
        ("table", "worker_table", "Grafik hazırlığı", "Grafiklerin proje, strateji, hazırlık ve kullanım durumlarını gösterir.", "Yalnız bağımsız ve kaynağı doğrulanmış grafikleri seç. Proje adının görünmesi kaynak eşleşmesini kanıtlamaz."),
        ("start", "start_workers_button", "Taramayı başlat", "Uygun seçili çalışma grafikleriyle kuyruktaki görevleri çalıştırır.", "Bağımsız grafik, doğru kaynak ve bekleyen görev gereklidir. Kontrol tamamlanmadan başlat düğmesi açılmaz."),
        ("stop", "worker_stop_button", "Taramayı durdur", "Yeni görev alımını durdurur ve çalışan işlemin güvenli bitişini bekler.", "Durduruluyor durumunu Durdu ile karıştırma. Mevcut sonuçlar silinmez ve kişisel grafikler taramaya dahil edilmez."),
        ("status", "worker_status", "Hazırlık durumu", "Bağlantı veya grafik hazırlığının son durumunu gösterir.", "Hata açıklamasındaki sonraki adımı izle. Bir yolun bulunması, sekmenin açılması ve kaynağın doğrulanması ayrı aşamalardır."),
    )
    for key, attribute, title, short, detail in entries:
        reason = (lambda: None if studio.start_workers_button.isEnabled() else
                  "Bağlantıyı, bağımsız grafik hazırlığını, doğru stratejiyi ve bekleyen görevleri kontrol et.") if key == "start" else None
        registry.register(HelpSpec("preparation." + key, 1, title, short, detail, getattr(studio, attribute), reason))


def register_preset_help(registry, widgets):
    entries = (
        ("note", "Preset durumu", "Kayıtlı test ayarlarının ne olduğunu ve boş listede sonraki adımı açıklar.", "Preset bir testte kullanılan ayarların kaydıdır. Gelecekte kazanç veya yeni dönemde aynı performans garantisi değildir."),
        ("listing", "Kayıtlı presetler", "İncelemek istediğin test ayar kaydını seçer.", "Satır seçmek ayarları taramaya taşımaz. Önce kaynak, dönem ve maliyet bilgisini ayrıntıda kontrol et."),
        ("details", "Preset ayrıntıları", "Kayıt anındaki ayarları, dönemi, maliyetleri ve kanıtı salt okunur gösterir.", "Bu bilgiler eski testin kaydıdır. Kaynak değişmişse eski ayarlar yeni koda otomatik uygulanmaz."),
        ("reuse", "Ayarları taramaya taşı", "Seçili presetin Pine ayarlarını, sembolünü ve zaman dilimini onayla Tarama ekranına taşır.", "Tarih, maliyetler ve başarı ölçütleri taşınmaz. Bunları ayrıca kontrol et. Bu işlem görev oluşturmaz veya tarama başlatmaz; kaynak değişmişse reddedilir."),
        ("close", "Pencereyi kapat", "Preset penceresini kapatır.", "Kapatmak kayıtlı presetleri silmez veya taramayı durdurmaz."),
    )
    for key, title, short, detail in entries:
        reason = (lambda: None if widgets["reuse"].isEnabled() else
                  "Önce listeden bir preset seç. Liste boşsa Sonuçlar'da bir testi preset olarak kaydet.") if key == "reuse" else None
        registry.register(HelpSpec("presets." + key, 1, title, short, detail, widgets[key], reason))
    registry.register_tour(TourSpec("presets", 1, tuple(
        (widgets[key], title, text, None) for key, title, text in (
            ("listing", "Bir ayar kaydını seç", "Preset bir testin ayar kaydıdır. Liste boşsa önce Sonuçlar ekranında bir testi açıp preset olarak kaydet."),
            ("details", "Eski testin koşullarını incele", "Ayar, dönem ve maliyetleri kontrol et. Bu değerler kayıt anındaki teste aittir; yeni dönemde aynı sonucu garanti etmez."),
            ("reuse", "Kontrol edip taramaya taşı", "Bu düğme kaynak kontrolü ve onaydan sonra Pine ayarlarını, sembolü ve zaman dilimini taşır. Tarih ve maliyetleri ayrıca kontrol et. Tur düğmeye senin yerine basmaz."),
        ))))
