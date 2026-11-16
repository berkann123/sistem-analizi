"""Veri modeli dört modüle ayrılmıştır (v93: 16 tablo):

    stok.py     ürün kartları (kategori ve tekstil yıpranması dahil), stok hareketleri, tedarikçiler, siparişler
    maliyet.py  oda tipleri (mevsim fiyatlarıyla) ve odalar, aylık giderler, standart tüketim reçetesi
                (kahvaltı büfesi ve oda paketi aynı tabloda)
    satis.py    konaklamalar, satış kanalları, etkinlik takvimi, oranlar (vergi, hammadde endeksi), fiyat kuralları
                (mevsim ayları dahil)
    kapanis.py  dönem kapanışı (biten ayın o ayın fiyatlarıyla dondurulmuş sonuçları ve oda-gece maliyetleri)

Kodun geri kalanı modelleri buradan alır: `from dashboard.models import Stay`.
"""
from .kapanis import ClosedPeriod
from .maliyet import (
    BreakfastBuffetItem, ConsumptionRecipe, MonthlyExpenseCategory, MonthlyHotelExpense, Room, RoomPackageItem,
    RoomType,
)
from .ortak import DEFAULT_SEASON_MONTHS, NON_NEGATIVE, POSITIVE, RATE, ZERO, Season, index_label, months_of, season_map, season_of
from .satis import Event, PricingRules, SalesChannel, Stay, StayQuerySet, TaxRate
from .stok import InventoryItem, InventoryMovement, PurchaseOrder, PurchaseOrderLine, Supplier
