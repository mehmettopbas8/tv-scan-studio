# TV Scan Studio

TradingView Desktop üzerindeki Pine stratejilerinin input kombinasyonlarını yerel olarak taramak için Windows masaüstü uygulaması.

## Ürün özellikleri

- Pine `strategy()` doğrulama ve temel input ayrıştırma
- Lazy kombinasyon üretimi ve önizleme sayısı
- SQLite proje ve devam ettirilebilir görev kuyruğu
- Atomik worker görev alma, üç denemeli hata yönetimi ve manuel inceleme
- Başarılı, elenmiş ve teknik hatalı görevlerin saklanması; tüm görevler için CSV/Excel dışa aktarımı
- Çok satırlı Pine inputları ile options/min/max/step/group/tooltip ayrıştırma
- PySide6 uygulama giriş noktası
- Sembol, timeframe, tarih, input ve maliyet kanıtı doğrulanan CDP workerları
- Target başına ayrı strategy ID ile iki veya daha fazla bağımsız worker
- Dashboard, görev planlama, worker dağıtımı, sonuç/olay ekranı
- PF/DD/işlem/kanıt filtreleri, kayıtlı filtreler ve dönem-maliyet uyarılı karşılaştırma
- Normal ve Microsoft Store TradingView Desktop keşfi
- Tek CDP 9222 oturumu içinde güvenli chart tabı çoğaltma
- Worker başına bağımsız proje atama, proje önceliği, pause/cancel/retry
- CPU/RAM worker önerisi, 2/4/8/16 projeksiyonu, test/saat ve ETA
- Sabit/liste/aralık/exclude input taraması ve FTMO sembol profilleri
- Kaynakta tanımı dışında hiç kullanılmayan input başlangıçta otomatik dışlanır; kullanıcı tek seçimle geri alabilir. Aynı koşullarda en az üç doğrulanmış değerin aynı sonucu vermesi ise yalnız "etkisiz olabilir" uyarısı üretir, otomatik dışlama yapmaz.
- Pozisyon, risk ve maliyet varsayımları; gerçek `in_N` eşlemesi ve özel şablonlar
- Komşu değer, maliyet stresi ve alternatif sağlayıcı aşamalı doğrulaması
- İşlem bazlı günlük P/L, FTMO kayıp, seri, süre, long/short, session ve yoğunlaşma analizi
- Yakınlaştırılabilir equity/drawdown, PF–DD dağılımı, günlük takvim, saat/gün/session grafikleri
- Başarılı presetler için PDF/CSV/Excel; tüm görevler için yalnız CSV/Excel
- Sonuç ekranındaki "ekranda görünen" dışa aktarma yalnız filtrelenmiş sonuç satırlarını içerir; teknik hataları da indirmek için "projedeki tüm uygun kayıtlar" seçilir. CSV/Excel şeması seçilen görevlerdeki bütün input alanlarını korur.
- İsteğe bağlı yerel araştırma kataloğu ve tarihsel arşiv görünümü; özel araştırma verileri açık kaynak ve portable dağıtıma dahil değildir
- Aynı ayar/dönemle alternatif sağlayıcı görevi hazırlama; ilişkili inputları birlikte tutan kontrollü varyantlar
- Checksum doğrulamalı SQLite + Pine kaynak yedeği
- Yedeği mevcut dosyanın üzerine yazmadan yeni veritabanı dosyasına açma
- Windows bildirimleri ve tamamen yerel ayarlar; telemetri/kullanıcı hesabı yok

## Geliştirme

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\tv-scan-studio.exe
```

## Portable Windows paketi

```powershell
.venv\Scripts\pyinstaller.exe --noconfirm --clean TVScanStudio.spec
```

Çıktı `dist\TV-Scan-Studio` klasöründe oluşur. GitHub Actions ayrıca portable
ZIP ve SHA-256 checksum üretir. İlk sürüm imzasızdır; Windows SmartScreen
uyarısında dosyanın GitHub Release checksum değeri doğrulanmalıdır.

Portable paketin SQLite, Türkçe PDF ve zaman dilimi desteğini GUI açmadan doğrulamak için (özel araştırma arşivleri dağıtıma dahil değildir):

```powershell
dist\TV-Scan-Studio\TV-Scan-Studio.exe --self-test
```

Uygulama mevcut TradingView taramalarından ayrı çalışır. Uygulama açılışta hiçbir
grafiği veya layout'u değiştirmez. Kullanıcının kaynak bağlama, worker hazırlama
ve tarama eylemleri CDP otomasyonunu başlatabilir; kaynak okuma için açılan
worker Pine panelinin yeniden kapandığı doğrulanır.

Tarama kendiliğinden başlamaz. Kullanıcı önce Pine projesini ve görev planını
kaydeder, Worker dağıtımı ekranında CDP targetlarını bulur ve ardından
`Taramayı başlat` düğmesine basar. Her çalışan farklı sekme kullanır. Uygulama
kapanırsa yarım kalan görevler yeniden bekleme kuyruğuna alınır.

Temel kriterleri geçen tek ölçüm `hassas` kabul edilir. `dayanıklı` sınıfı için
komşu değer, maliyet stresi ve farklı sağlayıcı kontrollerinin üçü de gerekir.

Tarama masasındaki `Yedeği yeni dosyaya aç` eylemi önce yedek ZIP'ini, ardından
yeni bir `.db` dosyası konumunu ister. Checksum, SQLite bütünlüğü, proje/görev
ilişkileri ve Pine kaynaklarının veritabanıyla tutarlılığı kontrol edilir.
Mevcut dosya seçilirse işlem reddedilir. Bu eylem açık uygulamanın veritabanını
değiştirmez ve yeni dosyaya otomatik geçiş yapmaz. Yarım kalmış görevler dosyada
korunur; normal uygulama açılışında kuyruğa döndürülür.

Strateji emirlerinde miktar doğrudan bir Pine inputundan (örneğin `Contracts`)
alınıyorsa TradingView'in varsayılan pozisyon alanı bu miktarı değiştirmez.
Sabit input değeri pozisyon ayarıyla çelişirse plan oluşturulmaz; pozisyon
alanını ilgili inputa eşleyin veya değerleri aynı tutun. Birden fazla kontrat
değerinin taranması korunur ve bu durumda emir miktarını seçilen input değerleri
belirler. Bu kontrol hesaplanmış risk/miktar ifadelerini yorumlamaz; Properties
değerinin okunması tek başına gerçek işlem miktarının ekonomik doğrulaması değildir.

TradingView Desktop yalnızca `9222` portuyla açılır. Ek workerlar ikinci bir
port veya ikinci hesap oturumu başlatmaz; uygulama aynı CDP profili içinde yeni
chart tabları açar. Worker çalıştırmadan önce Pine başlığı ve input yapısı
eşleşmeli, ilk kullanımda kalıcı `pine_id` ve yerel Pine kaynağı
eşlemesi doğrulanmalıdır. Başlatma onayından sonra sekme ve kimlik yeniden salt
okunur doğrulanır; kaydedilmiş kimlik veya input yapısı değişirse worker kilidi yeniden devreye girer;
uygulama belirsiz bir grafiğe otomatik kod yapıştırmaz veya mevcut çalışmayı gizlemez.
Bağımsız worker sekmesinde kaynak bağlama sırasında uygulama aynı
Pine ID/sürüme ait kayıtlı tam kaynak metnini okuyup proje koduyla SHA-256
üzerinden karşılaştırabilir. Yalnız satır sonları normalleştirilir; kod ve diğer
boşluklar korunur. Farklı kaynak veya okuma sırasında değişen derleme kimliği
bağlamayı engeller. Editör kapalıysa yalnız güvenle bağlanmış worker layoutunda
Pine paneli geçici açılır; tam metin okunduktan sonra kapandığı doğrulanır.
Çalışan tarama sırasında kaynak bağlanmaz. Açık editör veya başka bir iletişim
kutusu değiştirilmez. Tam metin güvenle okunamıyorsa açık
kullanıcı onayı gerekir; bu onay otomatik kaynak eşitliği kanıtı değildir.
Panelin kapanması doğrulanamazsa bağlama reddedilir. Kaydedilmemiş editör taslağı
uygulanmış stratejinin kaynak kanıtı olarak kullanılmaz.
TradingView'in sekmeler arası layout/bulut eşitlemesinin mevcut grafikleri nasıl
etkilediği canlı test edilmeden ayrıca doğrulanmış sayılmaz.

Özel araştırma kataloğu ve tarihsel arşiv dağıtımda yoktur. Bu dosyalar yerel
olarak sağlanmadığında araştırma ekranı veri eksikliğini açıklar ve ilgili
eylemleri kapatır; yeni proje, input planlama ve tarama akışı kullanılabilir.
Yerel araştırma verisi varsa dönem, maliyet ve sağlayıcı kapsamı ayrıca
incelenmelidir; farklı dönemlerdeki sonuçlar doğrudan kıyaslanmamalıdır.
Alternatif sağlayıcı görevi hazırlamak worker başlatmaz.
FTMO gün içi equity ihlali kapalı işlem listesinden kanıtlanamaz; raporda bu
sınır açıkça belirtilir. Kontrollü varyantlar, birlikte değişmesi gereken input
gruplarını çapraz çarpım yerine eşlenmiş durumlar olarak çalıştırır.

Lisans: AGPL-3.0-only.

İki gerçek target üzerinde uçtan uca smoke testi güvenlik kilitlidir:

```powershell
.venv\Scripts\python.exe tools\live_two_worker_smoke.py `
  --strategy-name "GRAFIKTEKI_STRATEJI_ADI" `
  --execute I_UNDERSTAND
```

Komut önce mevcut 9222 targetlarını kaydeder, aynı oturumda iki **yeni** chart
sekmesi açar ve yalnız bu yeni targetlara worker bağlar. Her sekmede stratejiyi
görünür adıyla ayrı keşfeder; aynı sembol, timeframe ve bir input değerini
yeniden uygular, geçici veritabanında iki doğrulanmış sonuç bekler. 9222 hazır
değilse TradingView'i yeniden başlatmaz ve mevcut grafiklere dokunmaz.
