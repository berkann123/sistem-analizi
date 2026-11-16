# Eski tasarım taslağı (kullanılmıyor)

Bu klasördeki SQL dosyaları projenin ilk PostgreSQL taslağıdır; çalışan uygulamanın şeması DEĞİLDİR.
Çalışan şema `dashboard/models.py` ve `dashboard/migrations/` içindedir (MySQL).

Dinamik fiyatlandırma modülü tasarlanırken başvuru için saklanıyor: `seasons`,
`seasonal_price_multipliers`, `occupancy_price_multipliers`, `room_rate_plans`, `reservations`
ve `reservation_nights` tabloları o modülün veri modeline başlangıç noktası olabilir.
