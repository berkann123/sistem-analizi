"""Dinamik fiyat kuralları. Oranlar veritabanındaki tek satırlık `fiyat_kurallari` tablosunda durur ve
Admin paneli › Fiyat kuralları ekranından değiştirilir; bu dosya yalnızca kuralları uygular.

Gece fiyatı (fiyat takvimi):
    temel fiyat × gecenin endeksi (hafta günü / etkinlik, en yüksek olan) × doluluk çarpanı
    Otelin fiyat kararı olan gecede karar son sözdür: doluluk çarpanı uygulanmaz.
    Doluluk ANLIKTIR: rezervasyon anında o gece için satılmış oda ÷ aktif oda; tahmin kullanılmaz.

Konaklama fiyatı (rezervasyon ekranı):
    gece fiyatlarının toplamı × (1 − erken rezervasyon indirimi) × (1 − konaklama süresi indirimi)
    İki indirim sırayla uygulanır (çarpılır), toplanmaz: %15 ve %12 birlikte %25,2 eder, %27 değil.

Her fonksiyon `rules` alır; döngü içinde her seferinde veritabanına gitmemek için kurallar bir kez okunup verilir.
"""
from decimal import Decimal as D


def current():
    from .models import PricingRules
    return PricingRules.current()


def occupancy_band(rate, rules=None):
    """Doluluk oranına (0–1) göre (çarpan, açıklama). Doluluk bilinmiyorsa etkisiz: (1, "")."""
    if rate is None:
        return D("1"), ""
    rules = rules or current()
    for _, upper, factor, label in rules.bands():
        if upper is None or rate < upper:
            return factor, label
    return D("1"), ""


def early_booking_discount(days_ahead, rules=None):
    rules = rules or current()
    return rules.early_discount if days_ahead is not None and days_ahead >= rules.early_days else D("0")


def length_of_stay_discount(nights, rules=None):
    rules = rules or current()
    for minimum, discount in rules.stay_discounts():
        if nights >= minimum:
            return discount
    return D("0")
