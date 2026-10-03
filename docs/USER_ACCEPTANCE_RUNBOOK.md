# TV Scan Studio — kullanıcı kabul testi

Durum: **kabul rehberi, canlı test izni değildir.** Mevcut TradingView taramaları, grafikler ve alarmlar korunur. Yalnız aynı 9222 oturumunda bağımsız kayıtlı worker layoutları kullanılabilir; 9333/ikinci profil açılmaz. Canlı değişiklikler ve yayın işlemleri kullanıcı talebinin sınırları içinde yapılır; bu belge tek başına izin vermez.

Bu rehber, kullanıcı ekran başındayken bir adımı deneyip sonucu bildirmesi için hazırlanmıştır. Teknik terimler yerine ekranda görünen eylemler kullanılır. Ürün sınırları için [README](../README.md), tarihli sonuç doğrulaması için [sürücü sözleşmesi](DATE_RANGE_DRIVER_CONTRACT.md) okunabilir. Yerel geliştirici kabul kayıtları dağıtıma dahil değildir.

## Oturum kaydı

Her adım için şu beş alan doldurulur: **beklenen**, **gerçekte görülen**, **ekran görüntüsü veya sonuç kaydı**, **etki (engelleyici/yüksek/orta/düşük)**, **tekrar üretme adımı**. Başarılı gözlem ile yalnız kod/test kanıtı karıştırılmaz. Strateji, hesap, broker veya gizli bilgi içeren görüntüler paylaşılmadan önce gözden geçirilir.

## Bölüm A — TradingView'e dokunmadan yapılabilecekler

1. **Yeni proje:** Uygulamayı aç; “Yeni proje”de strateji adını ve Pine kodunu gir; “Inputları analiz et”e bas. Beklenen: strateji olmayan kod açıklanarak reddedilir; geçerli stratejide bulunan inputlar başlık, tip ve varsayılanla görünür. Uzun kaynakta arayüz donmaz. Not: “Proje kaydet” öncesi analiz görünür olmalı.
2. **Proje seçimi:** Kayıtlı projelerde arama yap, sonuçları ve “Son kullanılanlar” grubunu incele; seçimi iptal et ve ardından gerçekten bir proje seç. Beklenen: açılır alan ekranı kaplamaz; iptal mevcut planı değiştirmez; seçilen projeye özgü inputlar yüklenir. Kullanıcının bilmediği Strategy ID istenmez.
3. **Input kararı:** Bir sayısal, bir bool, bir seçenekli ve varsa bir session/timeframe inputu seç. Sırayla “Tara”, “Sabit bırak” ve “Dışla”yı dene; sayısal aralığı değiştir, hatalı adım gir ve geri dön. Beklenen: önerinin kaynağı ve gerekçesi okunur; değişiklikten sonra değer korunur; hatalı giriş eski geçerli planı bozmaz. Kullanıcı JSON yazmaya mecbur kalmaz.
4. **Kombinasyon:** Tek bir iki-değerli inputu tara; sonra ikinci bir iki-değerli input ekle. Sembol/timeframe sayıları sabitken toplamın beklenen çarpanla değiştiğini kontrol et. Bir inputu sabit bırakınca ve dışlayınca toplamın farkını not et. Beklenen: görev sayısı açıkça gösterilir; önerilen süre varsayım/ölçüm olarak etiketlenir. “Etkisiz” denen inputun gerekçesi ve geri alma yolu görünür.
5. **Sonuç ve grafik görünümü:** Gerçek yeni sonuç yoksa mevcut araştırma arşivi ile yeni tarama sonuçlarının ayrı etiketlendiğini incele. Boş sonuç ekranı sahte veri çizmemeli. Veri bulunan bir görünümde huniyle PF ve DD filtrelerini uygula, seçili kaydı aç, tablo/tooltip/grafik değerlerini karşılaştır. Görüntü kesilmesi, yatay kaydırma ve %125/%150 DPI kusurlarını ayrı kaydet.
6. **Dışa aktarım:** Varsa yerel doğrulanmış başarılı kayıtta CSV, Excel ve PDF seçeneklerini; bütün sonuç kapsamındaysa yalnız CSV ve Excel'i kontrol et. Ekrandaki filtre mi tüm proje mi indirileceği ve kayıt sayısı indirmeden önce görünmeli. İndirilen dosyanın içeriği ayrıca denetlenmeden bu adım “geçti” sayılmaz.
7. **Ayarlar:** Veritabanı ve CDP portunun anlaşılır olup olmadığını; timeout/poll/stabil okuma gibi teknik seçeneklerin açıklanmış gelişmiş bölümde kaldığını kontrol et. Siyah spinbox parçaları, okunmayan sayı ve klavye odak kusurlarını ekran görüntüsüyle işaretle.

## Bölüm B — yalnız canlı test penceresi onaylanınca

Ön koşullar: kullanıcı mevcut taramaların bittiğini ve iki **yeni** TradingView sekmesi açılabileceğini açıkça söyler; 9222'nin sağlıklı olduğu salt okunur doğrulanır; test stratejisi ve sembol/timeframe kullanıcı tarafından seçilir. Bu koşullardan biri yoksa burada durulur. TradingView yeniden başlatılmaz; mevcut sekme veya Pine kaynağı değiştirilmez.

1. Uygulamada “TradingView'i kontrol et” ile bulunan stratejinin görünen adını, sembolünü ve timeframe'ini kullanıcı teyit eder. Pine kaynak metni otomatik karşılaştırılmıyorsa arayüzün bunu açıkça söylediği görülür.
2. Başlatma önizlemesinde açılacak yeni sekme sayısı, seçilen inputlar, maliyetler ve görev sayısı okunur. Belirsiz/yanlış eşleşmede başlatma kapalı kalır.
3. Yalnız onaylanan iki yeni sekmede iki worker çalıştırılır. Her workerın kendi target'ında kaldığı; Strategy Tester sembol, timeframe, tarih, input ve maliyet değerlerinin görevle eşleştiği; tamamlanan sonuçların çapraz karışmadığı kaydedilir.
   Mevcut smoke aracı inputu değiştirmeden mevcut değeri yeniden uygular. Kombinasyon taramasını doğrulamak için ayrıca kullanıcı onayıyla **aynı yeni test sekmesinde** bir inputun iki farklı değeri sırayla denenir; her denemede geri okunan değer ve karşılık gelen Strategy Tester sonucu kaydedilir. Bu ikinci senaryo yapılmazsa “iki worker smoke geçti” denebilir, “input taraması canlı doğrulandı” denemez.
4. Kullanıcı bir workerı durdurup uygulamayı kapat/aç senaryosunu ayrıca onaylarsa, tamamlanmış işin tekrarlanmadığı ve yarım işin güvenli kuyruğa döndüğü izlenir. Onay yoksa bu adıma geçilmez.
5. Test sonu: yalnız testin açtığı sekmeler belirlenir; kapatma veya eski chart görünürlüğünü değiştirme kullanıcı kararıyla yapılır. Geçici test verisi ile gerçek proje verisi ayrı tutulur. Mevcut tarama/alarmların durumu kullanıcıyla karşılaştırılır.

`tools/live_two_worker_smoke.py` ayrıca `--execute I_UNDERSTAND` kilidi taşır ve 9222 sağlıklı değilse sekme açmadan durur. Bu kilit tek başına kullanıcı onayı yerine geçmez. Betik iki yeni chart sekmesi açabilir; çalıştırmadan önce kullanıcıya tam etki ve geri dönüş anlatılır. Testin başarılı çıkış kodu bile gerçek pencere, oturum senkronizasyonu ve mevcut taramaların etkilenmediği gözlemini tek başına kanıtlamaz.

## Durma ve karar kuralları

- Oturum kopması, mevcut taramada değişiklik, yanlış strateji/hesap veya beklenmeyen sekme görülürse worker durdurulur; TradingView yeniden başlatılmaz ve kayıt alınır.
- Kod testleri, sentetik veri ve portable EXE self-test; gerçek iki-worker ve temiz Windows doğrulaması yerine geçmez.
- Bölüm A'nın bulguları önce eksik listesine girer. Bölüm B ve temiz Windows/CI kapıları geçilmeden “MVP tamamlandı” denmez. Bundan sonra özgün plan madde madde yeniden denetlenir; ancak gerçekten tamamlandığında rakip analizi ve yeni özellik önerileri hazırlanır.
