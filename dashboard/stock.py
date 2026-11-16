"""Stok ve maliyet hesabının saf (veritabanından bağımsız) çekirdeği.

Yöntem: HAREKETLİ AĞIRLIKLI ORTALAMA (moving weighted average).
Her alımda ortalama, o an depoda kalan stok ile yeni gelen malın değerinden
yeniden hesaplanır. Tüketim ve fire ortalamayı değiştirmez, yalnızca stoğu azaltır.

Örnek: 10 adet × 100 TL al, 10 adet tüket, 10 adet × 200 TL al.
  Tüm alımların ortalaması (eski yöntem): 150 TL  -> yanlış, depoda 100 TL'lik mal kalmadı.
  Hareketli ortalama (bu dosya):          200 TL  -> depodaki malın gerçek maliyeti.
"""
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
COST_PRECISION = Decimal("0.0001")

INCOMING = ("alim", "devir_giris")
OUTGOING = ("tuketim", "fire", "devir_cikis")
ADJUSTMENT = "sayim_duzeltme"


def replay_movements(movements, fallback_cost=ZERO):
    """Hareketleri tarih sırasıyla işleyip (eldeki stok, ortalama birim maliyet) döndürür.

    movements: (hareket_turu, miktar, birim_maliyet) üçlüleri; ESKİDEN YENİYE sıralı olmalı.
    fallback_cost: hiç alım hareketi yoksa korunacak mevcut birim maliyet.
    """
    stock = ZERO
    average = None
    for movement_type, quantity, unit_cost in movements:
        if movement_type in INCOMING:
            if stock <= 0 or average is None:
                # Depo boşsa (ya da eksideyse) yeni gelen mal kendi maliyetiyle başlar.
                average = unit_cost
            else:
                average = (stock * average + quantity * unit_cost) / (stock + quantity)
            stock += quantity
        elif movement_type in OUTGOING:
            stock -= quantity
        elif movement_type == ADJUSTMENT:
            # Sayım düzeltmesi işaretli girilir (+ fazla, − eksik); ortalamayı değiştirmez.
            if average is None and quantity > 0 and unit_cost > 0:
                average = unit_cost
            stock += quantity
    if average is None:
        average = fallback_cost or ZERO
    return stock, Decimal(average).quantize(COST_PRECISION, rounding=ROUND_HALF_UP)
