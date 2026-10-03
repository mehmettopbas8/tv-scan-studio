# TV Scan Studio

TradingView Desktop üzerindeki Pine stratejilerini farklı input, sembol, timeframe ve maliyet ayarlarıyla tarayan yerel Windows uygulaması. Hesaplamayı Pine'ı Python'a çevirerek değil, TradingView'in gerçek Strategy Tester sonuçlarını okuyarak yapar.

Projeler, görev kuyruğu, sonuçlar ve doğrulama kayıtları SQLite'ta tutulur. TV Scan Studio hesabı veya bulut servisi gerekmez; uygulamada telemetri yoktur. TradingView'in kendi hesabı, internet bağlantısı, veri ve abonelik koşulları ayrıca geçerlidir.

> Sürüm durumu: `0.2.0` geliştirme / kabul adayıdır. Kaynak testleri ve portable paket kontrolleri, bütün canlı kullanıcı kabulünün tamamlandığı anlamına gelmez. Paketli uygulamada çalışan görevin kesilmesi ve kurtarılması gibi kalan kabul kapıları kapanmadan “MVP tamamlandı” denmez.

## İçindekiler

- [Kurulum](#kurulum)
- [İlk tarama](#ilk-tarama)
- [TradingView bağlantısı](#tradingview-bağlantısı)
- [Sonuçlar ve dışa aktarım](#sonuçlar-ve-dışa-aktarım)
- [Veriler ve yedekleme](#veriler-ve-yedekleme)
- [Dosya yapısı](#dosya-yapısı)
- [Dokümantasyon](#dokümantasyon)
- [Testler](#testler)
- [Portable paket oluşturma](#portable-paket-oluşturma)
- [Sorun giderme](#sorun-giderme)

## Kurulum

### Gereksinimler

- Hedef platform: Windows x64 masaüstü.
- Canlı tarama için TradingView Desktop ve grafiğe uygulanmış bir Pine **stratejisi**. Yalnız indikatör olan kod tarama projesi değildir.
- TradingView'e tek `9222` CDP bağlantısı. İkinci port, profil veya hesap oturumu kullanılmaz.
- Tarihli Deep Backtesting görevleri için TradingView hesabının ilgili özelliğe erişimi ve yeterli veri kapsamı gerekir.
- Kaynaktan çalıştırmak için Python **3.11–3.13**; aşağıdaki örnek Python 3.12 kullanır. Python 3.14 proje bağımlılık aralığında değildir.

### Son kullanıcı: EXE indirme ve çalıştırma

Kurulum sihirbazı yoktur: **indir → doğrula → EXE'ye çift tıkla**. Python, Git, pip veya kaynak kod indirmeniz gerekmez. `Code → Download ZIP` uygulama değil, kaynak kod indirir; EXE edinmek için aşağıdaki yolları kullanın.

#### 1. EXE'yi edinme

**Yayımlanmış sürüm varsa — önerilen yol:**

1. [GitHub Releases](https://github.com/mehmettopbas8/tv-scan-studio/releases) sayfasını açın ve istediğiniz sürüme girin. Ön sürüm / release candidate etiketi varsa bunu kararlı sürümle karıştırmayın.
2. Sürümün `Assets` bölümünde `TV-Scan-Studio-0.2.0.exe` ve `TV-Scan-Studio-0.2.0.exe.sha256` dosyalarına tıklayıp ikisini de indirin. Sürüm numarası farklı olabilir; EXE ve checksum aynı sürüme ait olmalı.
3. ZIP'i tercih ederseniz `TV-Scan-Studio-0.2.0-portable.zip` ve onun `.zip.sha256` dosyasını indirin. Önce ZIP'i aşağıdaki yöntemle doğrulayın, sonra Windows'ta sağ tık → `Tümünü ayıkla` ile içindeki tek EXE'yi çıkarın. ZIP'in içinden doğrudan çalıştırmayın.

**Henüz Release yoksa — mevcut geliştirme paketi:**

1. GitHub hesabınızla giriş yapıp [Actions](https://github.com/mehmettopbas8/tv-scan-studio/actions/workflows/windows-build.yml) sayfasını açın.
2. `Windows test and portable build` iş akışında istediğiniz commit'e ait, yeşil işaretli **tamamlanmış** çalışmayı seçin. Başarısız veya devam eden işi kullanmayın.
3. Çalışmanın özetindeki `Artifacts` bölümünden `TV-Scan-Studio-windows-x64` paketini indirin. GitHub artefakt indirmesi oturum açmayı gerektirebilir; artefaktlar saklama süresi dolunca silinebilir.
4. İndirilen artefakt ZIP'ine sağ tıklayıp `Tümünü ayıkla` seçin. Çıkan dosyalar arasından sürüm numaralı `.exe` ve ona ait `.exe.sha256` dosyasını kullanın. Yanındaki `portable.zip` alternatif dağıtım kopyasıdır; iki ayrı uygulama kurmanız gerekmez.
5. Bu paket bir **CI geliştirme çıktısıdır**, yayımlanmış kararlı sürüm değildir. Otomatik testlerin geçmesi bütün canlı kullanıcı kabulünün tamamlandığı anlamına gelmez.

Releases sayfasında paket yoksa yukarıdaki Actions yolu kullanılabilir. Bir EXE size doğrudan verildiyse de aşağıdaki doğrulama ve ilk açılış adımlarını izleyin.

#### 2. Dosyayı doğrulama

EXE ve ona ait checksum'u aynı klasöre koyun. Dosya Gezgini'nde bu klasörü açın, adres çubuğuna `powershell` yazıp Enter'a basın. Aşağıdaki komutta dosya adını indirdiğiniz sürüme göre değiştirin:

```powershell
$fileToCheck = ".\TV-Scan-Studio-0.2.0.exe"
$expected = (Get-Content "$fileToCheck.sha256").Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries)[0]
$actual = (Get-FileHash -LiteralPath $fileToCheck -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw "SHA-256 eşleşmiyor. Dosyayı çalıştırmayın." }
Write-Host "SHA-256 doğrulandı."
```

ZIP doğrularken yalnız ilk satırı `$fileToCheck = ".\TV-Scan-Studio-0.2.0-portable.zip"` olarak değiştirin; yanında aynı adlı `.zip.sha256` bulunmalı. Checksum dosyası çalışma bağımlılığı değildir, dosya bütünlüğü kontrolü içindir. Checksum'u da aynı güvenilir kaynaktan indirin; hash eşleşmesi yayıncı kimliği veya zararlı yazılım taraması yerine geçmez.

#### 3. İlk açılış

1. Doğruladığınız EXE'yi kalıcı bir klasöre koyun; örneğin kullanıcı klasörünüzde `Uygulamalar\TV Scan Studio`. İsterseniz yalnız bu EXE'yi masaüstüne koyabilirsiniz.
2. EXE'ye çift tıklayın. Normal kullanıcı olarak çalıştırın; yönetici yetkisi gerekmez. İlk açılışta bağımlılıklar çıkarıldığı için birkaç saniye bekleyin, art arda başka kopya başlatmayın.
3. İmzasız paket Windows SmartScreen uyarısı verebilir. Kaynağı ve checksum'u kontrol etmeden uyarıyı geçmeyin. Antivirüsü kapatmayın veya karantina engelini otomatik aşmayın; şüpheli indirmede durun.
4. Ana ekran açılınca kurulum tamamdır. Tarama kendiliğinden başlamaz. TradingView'i bağlamak ve ilk projeyi oluşturmak için aşağıdaki `TradingView bağlantısı` ve `İlk tarama` bölümlerini izleyin.
5. Kısayol isterseniz EXE'ye sağ tıklayın; Windows sürümüne göre `Daha fazla seçenek göster → Gönder → Masaüstü (kısayol oluştur)` yolunu kullanın. EXE'nin bulunduğu asıl dosyayı sonradan taşımayın; kısayol eski konumu işaret eder.

**Yalnız EXE yeterlidir:** Python kurulumu, yan DLL veya `_internal` klasörü taşımanız gerekmez. Checksum dosyası doğrulama içindir, çalıştırma bağımlılığı değildir. Bağımlılıklar EXE'nin içine gömülür; açılışta Windows geçici dizinine çıkarılır ve normal kapanışta temizlenir. Bu nedenle ilk açılış klasörlü paketten yavaş olabilir; geçici dizinin yazılabilir olması gerekir. Yönetici olarak çalıştırmayın. Bu, diske hiç dosya yazılmadığı anlamına gelmez: kalıcı kullanıcı verileri aşağıdaki AppData dizininde tutulur.

Bu çalışma biçimi [PyInstaller tek dosya paketleme açıklamasına](https://pyinstaller.org/en/stable/operating-mode.html#how-the-one-file-program-works) dayanır. Zorla kapatma/çökme durumunda geçici çıkarma klasörü kalabilir; uygulama veritabanı bu geçici klasöre yazılmaz.

#### 4. Yeni sürüme geçme ve kaldırma

Otomatik güncelleme yoktur. Yeni EXE'yi ve eşleşen checksum'u indirin; çalışan taramayı kontrollü durdurun, uygulamada `Yedek oluştur` ile verileri yedekleyip uygulamayı kapatın. Yeni EXE'yi doğruladıktan sonra eski dosyanın yerine koyun veya ayrı konumdan açın. Aynı Windows kullanıcısında uygulama verileri `%LOCALAPPDATA%\TVScanStudio\studio.db` içinde kalır; yedek olmadan eski sürüme dönüşü güvenli varsaymayın.

Başka bilgisayara **EXE'yi taşımak projeleri taşımaz**. Verileri ayrıca yedekleyin; `Yedeği yeni dosyaya aç` eyleminin aktif veritabanına otomatik geçmediğini aşağıdaki yedekleme bölümünde okuyun.

Kaldırmak için uygulamayı kapatıp EXE ve varsa kısayolunu silmeniz yeterlidir. Bu işlem kullanıcı veritabanını silmez. Verileri de kaldırmak istiyorsanız önce yedek alın; AppData klasörünü ayrı ve bilinçli olarak temizleyin.

### Geliştirici: kaynaktan çalıştırma

PowerShell'de, projeyi koymak istediğiniz dizinden başlayın:

```powershell
git clone https://github.com/mehmettopbas8/tv-scan-studio.git
cd tv-scan-studio
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\tv-scan-studio.exe
```

Depo zaten bilgisayarınızdaysa `git clone` yerine mevcut `tv-scan-studio` klasörüne girin. Komutlar proje kökünden çalıştırılır. Sanal ortamı aktive etmek gerekmez; bu yüzden PowerShell execution policy değişikliği de gerekmez. Bağımlılık kurulumu internet gerektirir.

Alternatif uygulama giriş noktası:

```powershell
.\.venv\Scripts\python.exe tools\run_tv_scan_studio.py
```

Uygulama tek masaüstü örneğiyle çalışır. İkinci başlatma, mevcut taramayı korumak için ikinci pencere açmaz.

## İlk tarama

1. **Yeni proje:** Projeye bir ad verin, Pine strateji kodunu yapıştırın, `Inputları analiz et` ile bulunan alanları inceleyin ve projeyi kaydedin.
2. **Tarama ayarları:** Projeyi, sembolleri, timeframe'leri, tarih aralığını, başarı kriterlerini ve maliyetleri seçin.
3. **Input kararı:** Varsayılanlar sabit kalır. Taramak istediğiniz inputta `Tara` seçin; önerilen değerleri gerekirse başlangıç/bitiş/adım veya seçenek listesiyle değiştirin. `Sabit bırak` tek değeri korur, `Hariç tut` tarama değişikliğinden çıkarır; Pine kaynağından input silmez.
4. **Plan önizlemesi:** Kombinasyon sayısını hesaplayıp kontrol edin, ardından görevleri kuyruğa ekleyin. Örneğin 3 input değeri × 2 sembol × 2 timeframe = 12 görev. Birden çok bağımsız inputun değer sayıları da çarpılır; kontrollü varyantlar ilişkili ayarları eşlenmiş durumlar halinde tutabilir.
5. **Worker dağıtımı:** TradingView bağlantısını kontrol edin. Her workerı ayrı kayıtlı layouta, doğru stratejiye ve istediğiniz projeye bağlayın. Stratejiyi görünen adıyla seçin; teknik Strategy ID'yi kullanıcı olarak bulmanız gerekmez.
6. **Başlatma:** Önizlemede strateji, görev sayısı ve worker atamalarını doğrulayıp `Taramayı başlat` düğmesine basın.
7. **Takip:** Tarama masasında ilerlemeyi; sonuç ekranında doğrulama, kriterler ve hataları inceleyin. Gerektiğinde workerı durdurun veya hatalı görevleri yeniden sıraya alın.

Input aralığı önerileri başlangıç önerisidir, kârlılık veya optimum ayar kanıtı değildir. Kaynakta tanımı dışında kullanılmayan input başlangıçta dışlanabilir; kullanıcı geri alabilir. Aynı koşullarda en az üç doğrulanmış değerin aynı sonucu vermesi yalnız “etkisiz olabilir” uyarısıdır, kesin etkisizlik kanıtı veya otomatik dışlama değildir.

CPU/RAM önerileri ve 2/4/8/16 worker projeksiyonları gerçek hız testi değildir. Ölçülmüş tarama hızı ve tahmini kalan süre ayrı değerlendirilmelidir.

## TradingView bağlantısı

### Tek oturum, bağımsız layoutlar

TradingView Desktop keşfi normal kurulumu ve Microsoft Store paketini destekler. Uygulamanın TradingView bulma/açma kontrolleriyle doğru çalıştırılabilir dosyayı seçin. **Bütün workerlar aynı `9222` oturumunda çalışmalıdır.** `9333` gibi ikinci portta başka oturum açmak TradingView oturumunun kopmasına yol açabilir.

Her worker için ayrı sekme yeterli değildir: **ayrı kayıtlı layout kimliği** gerekir. Aynı layoutun iki sekmede açılması ayarların senkronize olmasına ve işlerin çakışmasına yol açabilir. Kullanılan worker layoutlarını birbirinden ve kişisel çalışma grafiklerinden ayırın. Replay açık workerda tarama başlatmayın.

TradingView zaten CDP olmadan açıksa uygulama onu otomatik kapatmaz. Mevcut tarama, Replay ve kaydedilmemiş çalışmaları kontrol ederek kapatma/yeniden açma kararını verin. Uygulamanın açılması tek başına taramayı başlatmaz; kaynak bağlama, worker hazırlama ve başlatma eylemleri TradingView üzerinde işlem yapabilir.

İleri kullanımda, TradingView **kapalıyken** gerçek EXE yoluyla PowerShell'den açma:

```powershell
$tvExecutable = "C:\GERCEK_KURULUM_YOLU\TradingView.exe"
Start-Process -FilePath $tvExecutable -ArgumentList "--remote-debugging-port=9222", "--remote-allow-origins=*"
```

Bu örnekteki yolu olduğu gibi kullanmayın; gerçek kurulum yolunu seçin. CDP tarayıcı kontrolü sağlar: portu internete açmayın ve güvenilmeyen yazılımların erişmesine izin vermeyin.

### Kaynak ve görev doğrulaması

Başlık ve input yapısı eşleşmesi, Pine kimliği/sürümü ve yerel proje kaynağı bağlanırken kontrol edilir. Güvenle okunabilen kayıtlı tam kaynak, SHA-256 ile karşılaştırılır; yalnız satır sonları normalleştirilir. Kaydedilmemiş editör taslağı aktif stratejinin kanıtı sayılmaz.

Kapalı Pine paneli yalnız güvenle bağlanmış workerda geçici açılabilir; tekrar kapandığı doğrulanır. Açık editör veya başka iletişim kutusu değiştirilmez. Kaynak güvenle okunamıyorsa açık kullanıcı onayı gerekir; bu onay otomatik kaynak eşitliği kanıtı değildir. Uygulama belirsiz grafiğe otomatik kod yapıştırmaz veya mevcut çalışmayı gizlemez.

Sonuç doğrulaması sembol, timeframe, input, dönem, kimlik ve maliyet kanıtlarını kontrol eder. Tarihli görevlerde taze Strategy Report/XLSX eşleşmesi gerekir; yalnız grafiğin tarih aralığı yeterli değildir. Eksik veri veya belirsiz rapor başarılı sonuç olarak kabul edilmez.

**Pozisyon miktarı:** Emir miktarı doğrudan Pine inputundan alınırsa TradingView Properties varsayılan miktarı onu değiştirmez. Pozisyon alanını ilgili inputa eşleyin veya sabit değerleri uyumlu tutun; çelişkili sabit ayar planı engeller. Hesaplanmış risk/miktar ifadeleri bu kontrolle bütünüyle yorumlanmaz.

**Maliyet sınırı:** Properties/XLSX değerlerinin eşleşmesi, spread'in veya bütün miktar/risk ifadelerinin ekonomik etkisini tek başına kanıtlamaz. Kayma ve komisyon varsayımlarını, birimlerini ve rapora uygulanmasını ayrı kontrol edin.

## Sonuçlar ve dışa aktarım

- Sonuçları PF, maksimum DD, işlem sayısı ve kanıt durumuna göre filtreleyin; farklı dönem veya maliyet kapsamlarını doğrudan karşılaştırmayın.
- Veri bulunan sonuçlarda equity/drawdown, PF–DD dağılımı, günlük takvim ve saat/gün/session analizleri kullanılabilir. Boş görünüm doğrulanmış veri varmış gibi yorumlanmamalıdır.
- **Başarılı kayıtlar:** PDF, CSV veya Excel (`.xlsx`).
- **Bütün görevler:** Başarılı, elenmiş ve teknik hatalı görevler dahil CSV veya Excel. Bütün sonuçlar için PDF sunulmaz.
- `Ekranda görünen` kapsam yalnız filtrelenmiş sonuç satırlarını içerir. Teknik hataları da indirmek için `Projedeki tüm uygun kayıtlar` kapsamını seçin. Dışa aktarma öncesi kapsamı ve kayıt sayısını kontrol edin.

“Tamamlanan” görev sayısı, kârlı veya başarı kriterlerini geçen görev sayısı değildir. Temel kriterleri geçen tek ölçüm `hassas` kabul edilir; `dayanıklı` sınıfı komşu değer, maliyet stresi ve alternatif sağlayıcı kontrollerinin üçünü de gerektirir. Bunlar canlı işlem kârlılığı garantisi değildir.

FTMO gün içi equity ihlali yalnız kapanmış işlemlerden kanıtlanamaz. İşlem analizi bu sınırla okunmalıdır.

Özel araştırma kataloğu ve tarihsel arşiv açık kaynak/portable pakete dahil değildir. Temiz kurulumda araştırma ekranı veri eksikliğini açıklar; yeni proje oluşturma ve tarama için bu arşivlere ihtiyaç yoktur. Alternatif sağlayıcı görevi hazırlamak workerı kendiliğinden başlatmaz.

## Veriler ve yedekleme

Varsayılan veritabanı:

```text
%LOCALAPPDATA%\TVScanStudio\studio.db
```

Projeler, Pine kaynakları, ayarlar, görevler, sonuçlar ve olay kayıtları yerel tutulur. Uygulama klasörünün taşınması bu veritabanını taşımaz. Dışa aktarımlar ve yedekler, kaydetme penceresinde seçtiğiniz konuma yazılır. Kaynaklar ve sonuçlar özel bilgi içerebilir; paylaşmadan önce inceleyin.

- `Yedek oluştur`: SQLite anlık görüntüsü, Pine kaynakları ve dosya checksum'larını içeren yedek üretir. Açık veritabanını elle kopyalamak yerine bu yolu tercih edin.
- `Yedeği yeni dosyaya aç`: Önce yedek ZIP'ini, sonra **yeni** `.db` konumunu seçtirir. Checksum, SQLite bütünlüğü, ilişkiler ve Pine kaynak tutarlılığı kontrol edilir. Var olan dosyanın üzerine yazılmaz.
- Geri yükleme **açık uygulamanın aktif veritabanını değiştirmez**, yeni dosyaya otomatik geçmez. Bu eylem yedeği güvenli ayrı dosyaya çıkarmaktır; aktif veri değiştirme sihirbazı değildir.
- Normal uygulama başlangıcında yarım kalan işler yeniden bekleme kuyruğuna alınır. Kaynak testlerindeki kurtarma kanıtı, paketli uygulamadaki gerçek kesinti kabulünün yerine geçmez.

Yeni sürüme geçmeden önce yedek alın. Veritabanını, TradingView oturum bilgilerini veya özel araştırma arşivlerini dağıtım paketine koymayın.

## Dosya yapısı

Aşağıdaki yapı sürüm kaynaklarını gösterir; kişisel veri ve yerel test çıktıları değildir:

```text
tv-scan-studio/
├── README.md                       Kurulum ve genel kullanım
├── CHANGELOG.md                    Sürüm değişiklikleri
├── LICENSE                         AGPL-3.0-only lisansı
├── pyproject.toml                  Bağımlılıklar, Python aralığı, giriş noktası
├── TVScanStudio.spec                PyInstaller Windows paket tanımı
├── .github/workflows/
│   └── windows-build.yml            Windows test, paket ve etiketli yayın hattı
├── src/tv_scan_studio/              Uygulama kaynakları
│   ├── app.py                      Sayfalar, kullanıcı eylemleri ve giriş noktası
│   ├── ui_controls.py              Yeniden kullanılan arayüz kontrolleri
│   ├── pine.py                     Pine strateji / input ayrıştırma
│   ├── recommendations.py          Tarama değeri önerileri
│   ├── scan_values.py              Sabit, liste ve aralık değerleri
│   ├── combinations.py             Kombinasyon üretimi ve sayımı
│   ├── planner.py                  Görev planı ve önizleme
│   ├── storage.py                  SQLite proje, kuyruk ve sonuç erişimi
│   ├── supervisor.py               Worker ataması ve çalışma koordinasyonu
│   ├── worker.py                   Görev çalıştırma ve sonuç doğrulama
│   ├── tradingview.py              TradingView sürücü ve CDP işlemleri
│   ├── motor_bridge.py             Paket içindeki CDP motor köprüsü
│   ├── windows.py                  Desktop keşfi, 9222 ve layout güvenliği
│   ├── deep_capture.py             Taze Deep rapor / dosya yakalama
│   ├── deep_export.py              TradingView XLSX ayrıştırma
│   ├── cost_application.py         Maliyet ve miktar ayar kontrolleri
│   ├── analytics.py                İşlem ve performans analizleri
│   ├── result_filters.py           Sonuç filtreleri
│   ├── export.py                   CSV ve Excel dışa aktarma
│   ├── report.py                   PDF raporu
│   └── backup.py                   Yedek, checksum ve güvenli geri yükleme
├── tests/                          Birim ve entegrasyon testleri
└── tools/                          Paketleme ve geliştirici yardımcıları
    ├── run_tv_scan_studio.py        Kaynak / EXE paketleme başlatıcısı
    ├── build_release.py            Portable ZIP ve SHA-256 üretimi
    ├── live_two_worker_smoke.py     İzinli gerçek iki-worker kontrolü
    ├── render_ui_preview.py        Geliştirici arayüz önizlemesi
    ├── build_sample_report.py       Örnek rapor üretimi
    ├── build_research_catalog.py    Yerel araştırma kataloğu hazırlığı
    └── build_historical_archive.py  Yerel tarihsel arşiv hazırlığı
```

Diğer kaynak modülleri: `profiles.py` sembol profilleri, `session_variants.py` ilişkili session varyantları, `sensitivity.py` hassasiyet analizi, `validation.py` doğrulama, `resources.py` kaynak ölçümü, `research.py` / `historical.py` isteğe bağlı arşivler ve `instance.py` tek uygulama örneği kontrolüdür.

`.venv/` geliştirme ortamıdır; `build/` paketleme ara dosyaları, `dist/` dağıtım çıktılarıdır. `output/`, `output-local-*/`, `tmp/`, veritabanları ve ekran görüntüleri yerel çıktıdır; `.gitignore` bunları kaynak deposundan ayırır. Uygulama veritabanı proje kökünde değil, yukarıdaki kullanıcı veri dizinindedir.

Arayüz eylemleri `app.py` üzerinden planlamayı ve worker koordinasyonunu çağırır. `storage.py` kalıcı kayıtları tutar; `tradingview.py` gerçek grafiğe erişir; rapor yakalama/doğrulama sonucu kayıt altına alır. Analiz ve dışa aktarma bu kayıtları tüketir. UI değişikliği için önce `app.py` / `ui_controls.py`, görev hatası için `worker.py` / `supervisor.py`, TradingView uyumsuzluğu için sürücü ve yakalama modüllerine bakın.

## Dokümantasyon

- Kurulum, kullanım, dosya yapısı ve geliştirici komutları bu README'de yer alır.
- [Değişiklik günlüğü](CHANGELOG.md): Sürümler arasındaki değişiklikler.
- [Lisans](LICENSE): AGPL-3.0-only koşulları.

Yeni davranış eklerken ilgili testleri ve kullanıcıya görünen kullanım açıklamasını birlikte güncelleyin. Kaynak testi, gerçek chart testi, portable paket testi ve canlı kabul kanıtlarını birbirinden ayırın. Kişisel strateji, hesap bilgisi veya yerel kabul kayıtlarını public dokümantasyona eklemeyin.

İç kabul rehberleri, canlı test günlükleri ve geliştirme karar notları public depoya dahil edilmez. `tests/` ise doküman/sonuç arşivi değil, ürün davranışını ve CI'yi doğrulayan test kaynak kodudur.

## Testler

### Kaynak testleri — canlı tarama başlatmaz

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Başsız Windows/CI ortamında:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:\QT_QPA_PLATFORM
```

Özel yerel araştırma verisine bağlı testler temiz checkout'ta atlanabilir. Testler planlama, SQLite kuyruğu, doğrulama, arayüz kontrolleri, dışa aktarma ve paket güvenliğini kapsar; gerçek TradingView oturumunun bütün davranışlarını kanıtlamaz.

### Paket tanılama

```powershell
$exe = (Resolve-Path ".\dist\TV-Scan-Studio.exe").Path
$process = Start-Process -FilePath $exe -ArgumentList "--self-test" -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) { throw "Portable self-test başarısız." }
$process = Start-Process -FilePath $exe -ArgumentList "--ui-smoke-test" -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) { throw "Portable UI smoke testi başarısız." }
```

`--self-test` geçici veriyle SQLite, Türkçe PDF ve zaman dilimi desteğini kontrol eder; kullanıcı veritabanını kullanmaz. `--ui-smoke-test` arayüzü geçici veriyle açıp kontrol eder. Bunlar canlı TradingView taraması değildir.

### Gerçek iki-worker testi — TradingView üzerinde işlem yapar

Önce mevcut taramaların bittiğini doğrulayın ve canlı test etkisini kabul edin. Aynı 9222 oturumunda **önceden oluşturulmuş**, ayrı kayıtlı `TV Scan Worker 1` ve `TV Scan Worker 2` layoutları bulunmalı; ikisinde de test stratejisi hazır ve Replay kapalı olmalıdır.

```powershell
.\.venv\Scripts\python.exe tools\live_two_worker_smoke.py `
  --strategy-name "GRAFIKTEKI_STRATEJI_ADI" `
  --execute I_UNDERSTAND
```

Bu araç **yeni sekme açmaz veya TradingView'i yeniden başlatmaz**. Var olan iki worker layoutunu keşfeder, her birinde görünen adla tek hazır strateji bulur ve geçici veritabanında iki görev çalıştırır. Her worker kendi mevcut sembol/timeframe ve ilk input değerini yeniden uygular. Başka layout veya açık Replay görürse durur.

`--vary-first-input` ayrıca ikinci workerda ilk tam sayı inputunu bir artırır; bu seçenek canlı ayar değiştirir ve test bitiminde otomatik geri alma sağlamaz. Yalnız uygun inputta ve açık test kararıyla kullanın, önceki değerleri kaydedip test sonunda kontrol edin. Normal uygulamanın kaynak eşlemesi ve bütün kabul kapıları, bu küçük geliştirici testiyle tamamlanmış sayılmaz.

## Portable paket oluşturma

Windows'ta, geliştirme bağımlılıkları kurulduktan sonra proje kökünde:

```powershell
.\.venv\Scripts\pyinstaller.exe --noconfirm --clean TVScanStudio.spec
.\.venv\Scripts\python.exe tools\build_release.py dist\TV-Scan-Studio.exe --output dist --version 0.2.0
```

Çıktılar:

```text
dist/
├── TV-Scan-Studio.exe               Tek dosyalı build çıktısı
├── TV-Scan-Studio-0.2.0.exe          Doğrudan dağıtılabilir tek EXE
├── TV-Scan-Studio-0.2.0.exe.sha256
├── TV-Scan-Studio-0.2.0-portable.zip
└── TV-Scan-Studio-0.2.0-portable.zip.sha256
```

Paketleme komutları aynı adlı eski build/ZIP çıktılarını yenileyebilir; kişisel verinizi bu çıktı dizinlerinde tutmayın. `build_release.py` uygulama dosyasını kontrol eder ve yerel veritabanı, belirli gizli/kişisel çıktı dosyaları ile özel araştırma arşivleri bulunan paketi reddeder. Bu kontrol, bütün gizli veriler için genel amaçlı tarayıcı değildir; dağıtım içeriğini ayrıca inceleyin.

[Windows iş akışı](.github/workflows/windows-build.yml) Python 3.11, 3.12 ve 3.13 üzerinde test çalıştırır; 3.13 işi portable paket üretir. EXE ve ZIP'ten çıkarılmış EXE tanılamaları, hash eşleşmesi ve özel arşiv kontrolü yapılır. `v*` etiketiyle tetiklenen yayın işi, test/build işleri geçtikten sonra GitHub Release oluşturur. Dal push'u tek başına Release oluşturmaz. Yayından önce sürüm numarası, değişiklik günlüğü, kabul kanıtı ve temiz Windows davranışı ayrıca kontrol edilmelidir.

## Sorun giderme

**`py -3.12` bulunamıyor:** Python 3.12 x64 kurulumunu ve Windows Python launcher'ı kontrol edin. Kurulu başka bir desteklenen 3.11–3.13 sürümü kullanıyorsanız ortam oluşturma komutundaki sürümü değiştirin.

**EXE açılmıyor / bağımlılık eksik:** Güncel tek dosyalı sürümü kullandığınızı, checksum'un eşleştiğini, Windows geçici dizininin yazılabilir olduğunu ve güvenlik yazılımının dosyayı karantinaya almadığını kontrol edin. Eski klasörlü sürümlerin EXE'leri tek dosyalı değildir; bunları yeni dağıtımla karıştırmayın.

**“Uygulama zaten açık”:** Mevcut TV Scan Studio penceresini kullanın. Aynı veritabanıyla ikinci uygulama açarak devam etmeyin.

**“CDP 9222 target listesi okunamadı”:** TradingView Desktop'ın 9222 ile açıldığını kontrol edin. Açık ama CDP'siz oturumu zorla sonlandırmayın; mevcut çalışmayı güvene alıp kontrollü yeniden açın. Çözüm olarak ikinci port açmayın.

**Workerlar çakışıyor:** Sekmelerin farklı kayıtlı layout kimliklerine sahip olduğunu doğrulayın; aynı layoutun iki kopya sekmesi bağımsız worker değildir.

**Strateji bağlanamıyor:** Doğru stratejinin grafikte hazır olduğunu, projenin kaynak/input yapısının eşleştiğini ve açık editör/modalin kontrolü engellemediğini inceleyin. Yalnız aynı ad, aynı kaynak kanıtı değildir.

**Değer listesi boş:** Taranacak inputa en az bir geçerli değer/aralık verin; taramayacaksanız `Sabit bırak` veya `Hariç tut` seçin. Sayısal adımın geçerli olduğunu kontrol edin.

**Araştırma ekranında veri yok:** Özel araştırma arşivleri dağıtılmaz; bu temiz kurulum için beklenen durumdur. Kendi Pine projenizle ilerleyebilirsiniz.

**Tarihli görev doğrulanmıyor:** Hesap erişimi, veri kapsamı, Strategy Report tarihleri, rapor tazeliği ve indirilen dosya eşleşmesini kontrol edin. Eksik kanıtı başarı gibi göstermek için kontrolü devre dışı bırakmayın.

**Hata bildirirken:** Uygulama sürümü, Windows/Python sürümü (kaynak kurulumda), ekran adı, tekrar üretme adımları ve beklenen/gerçek davranışı paylaşın. Ekran görüntüsündeki strateji kaynaklarını, hesap ve kişisel bilgileri önce temizleyin.
