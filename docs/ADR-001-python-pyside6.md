# ADR-001: Python ve PySide6 ile yerel masaüstü MVP

**Durum:** Kabul edildi  
**Tarih:** 2026-09-22  
**Karar veren:** Mehmet Topbaş

## Bağlam

Uygulama TradingView Desktop'u CDP üzerinden yönetecek, Pine strategy inputlarını tarayacak, birden fazla projeyi ve workerı yönetecek ve sonuçları tamamen yerel tutacaktır. İlk sürümün hızlı yayımlanması, mevcut Python tarama motorunun yeniden kullanılması ve kod imzalamanın MVP'yi geciktirmemesi önceliklidir.

## Karar

MVP Python, PySide6 ve SQLite ile geliştirilecek. TradingView otomasyonu mevcut `gnc-zihin/motor/ciz_paralel.py` yeteneklerinin bir adaptörü üzerinden kullanılacak. Dağıtım başlangıçta GitHub Releases üzerinde imzasız portable ZIP/EXE olacaktır. Kod imzalama ve otomatik güncelleme ürün doğrulandıktan sonra ele alınacaktır.

## Sonuçlar

- Mevcut CDP ve worker kodu yeniden kullanılabilir.
- Proje, kuyruk ve sonuçlar tek bir yerel SQLite veritabanında tutulabilir.
- UI ile otomasyon motoru ayrı modüller olarak test edilebilir.
- İlk sürümde Windows SmartScreen uyarısı görülebilir.
- PySide6 kurulumu ve daha sonra PyInstaller paketleme hattı gerekir.

