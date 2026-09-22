# TV Scan Studio

TradingView Desktop üzerindeki Pine stratejilerinin input kombinasyonlarını yerel olarak taramak için Windows masaüstü uygulaması.

## Ürün özellikleri

- Pine `strategy()` doğrulama ve temel input ayrıştırma
- Lazy kombinasyon üretimi ve önizleme sayısı
- SQLite proje ve devam ettirilebilir görev kuyruğu
- Atomik worker görev alma, üç denemeli hata yönetimi ve manuel inceleme
- Yalnızca doğrulanmış görevler için sonuç kaydı ve CSV dışa aktarımı
- Çok satırlı Pine inputları ile options/min/max/step/group/tooltip ayrıştırma
- PySide6 uygulama giriş noktası
- Sembol, timeframe, tarih, input ve maliyet kanıtı doğrulanan CDP workerları
- Target başına ayrı strategy ID ile iki veya daha fazla bağımsız worker
- Dashboard, görev planlama, worker dağıtımı, sonuç/olay ekranı
- Başarılı preset filtreleme, yan yana tablo karşılaştırması ve CSV
- Normal ve Microsoft Store TradingView Desktop keşfi
- Tek CDP 9222 oturumu içinde güvenli chart tabı çoğaltma
- Worker başına bağımsız proje atama, proje önceliği, pause/cancel/retry
- CPU/RAM worker önerisi, 2/4/8/16 projeksiyonu, test/saat ve ETA
- Sabit/liste/aralık/exclude input taraması ve FTMO sembol profilleri
- Pozisyon, risk ve maliyet varsayımları; gerçek `in_N` eşlemesi ve özel şablonlar
- Komşu değer, maliyet stresi ve alternatif sağlayıcı aşamalı doğrulaması
- İşlem bazlı günlük P/L, FTMO kayıp, seri, süre, long/short, session ve yoğunlaşma analizi
- Equity/drawdown grafiği, günlük P/L görünümü, PDF raporu ve doğrulanmış CSV
- Checksum doğrulamalı SQLite + Pine kaynak yedeği
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

Portable paketin SQLite ve Türkçe PDF bağımlılıklarını GUI açmadan doğrulamak için:

```powershell
dist\TV-Scan-Studio\TV-Scan-Studio.exe --self-test
```

Uygulama mevcut TradingView taramalarından ayrı çalışır. Uygulama açılışta hiçbir
grafiği veya layout'u değiştirmez; CDP otomasyonu yalnızca kullanıcı workerları
başlattığında devreye girer.

Tarama kendiliğinden başlamaz. Kullanıcı önce Pine projesini ve görev planını
kaydeder, Worker dağıtımı ekranında CDP targetlarını bulur ve ardından
`Workerları başlat` düğmesine basar. Her worker farklı target kullanır. Uygulama
kapanırsa yarım kalan görevler yeniden bekleme kuyruğuna alınır.

Temel kriterleri geçen tek ölçüm `hassas` kabul edilir. `dayanıklı` sınıfı için
komşu değer, maliyet stresi ve farklı sağlayıcı kontrollerinin üçü de gerekir.

TradingView Desktop yalnızca `9222` portuyla açılır. Ek workerlar ikinci bir
port veya ikinci hesap oturumu başlatmaz; uygulama aynı CDP profili içinde yeni
chart tabları açar. Worker çalıştırmadan önce Pine başlığı ve input yapısı
eşleşmeli, ilk kullanımda kullanıcı kalıcı `pine_id` ve yerel Pine SHA-256
eşlemesini onaylamalıdır. Kaynak değişirse worker kilidi yeniden devreye girer;
uygulama belirsiz bir grafiğe otomatik kod yapıştırmaz veya mevcut çalışmayı gizlemez.

Lisans: AGPL-3.0-only.

İki gerçek target üzerinde uçtan uca smoke testi güvenlik kilitlidir:

```powershell
.venv\Scripts\python.exe tools\live_two_worker_smoke.py `
  --target TARGET_1 --target TARGET_2 --study-id STUDY_ID `
  --execute I_UNDERSTAND
```

Komut mevcut sembol, timeframe ve inputları snapshot olarak alır; yalnızca aynı
değerleri yeniden uygular ve geçici veritabanında iki doğrulanmış sonuç bekler.
