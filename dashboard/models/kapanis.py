"""DÖNEM KAPANIŞI modülü: biten ayın sonuçlarını ve birim maliyetlerini o ayın fiyatlarıyla dondurur.

Tek tablo (v93): donem_kapanislari — ay başına bir satır: doluluk sayımları, gelir, komisyon, değişken ve ortak gider
toplamı ve "maliyetler" alanında kapanan ayda bir oda-gecenin maliyeti (oda tipi × kişi sayısı: değişken + ortak gider
payı; eski donem_maliyetleri tablosu).

Giderler ayrıca kopyalanmaz: gider kayıtları zaten aya göre tarihlidir. Kapanış kendiliğindendir (biten ay, sonraki
ayın 5. gününden sonra bir ekran açılınca); hesap services.py'deki close_month'tadır.
"""
from decimal import Decimal
from types import SimpleNamespace

from django.db import models
from django.utils import timezone

from .ortak import ZERO


class ClosedPeriod(models.Model):
    """Kapanmış ay. Doluluk, sonuç ve oda başı maliyet saklanmaz; bu sayılardan hesaplanır."""
    month = models.DateField(unique=True, db_column="ay", verbose_name="Ay", help_text="Ayın ilk günü.")
    closed_at = models.DateTimeField(default=timezone.now, db_column="kapanis_tarihi", verbose_name="Kapanış tarihi")
    available_room_nights = models.PositiveIntegerField(db_column="musait_oda_gece", verbose_name="Müsait oda-gece")
    occupied_room_nights = models.PositiveIntegerField(db_column="satilan_oda_gece", verbose_name="Satılan oda-gece")
    room_revenue = models.DecimalField(max_digits=14, decimal_places=2, db_column="oda_geliri",
                                       verbose_name="Oda geliri (TL, KDV hariç)")
    commission_total = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO, db_column="kanal_komisyonu",
                                           verbose_name="Kanal komisyonu (TL)")
    variable_total = models.DecimalField(max_digits=14, decimal_places=2, db_column="degisken_gider",
                                         verbose_name="Değişken gider (TL)")
    shared_total = models.DecimalField(max_digits=14, decimal_places=2, db_column="ortak_gider",
                                       verbose_name="Ortak gider (TL)",
                                       help_text="Sabit kalemler + yarı değişken kalemlerin sabit tabanı.")
    notes = models.CharField(max_length=240, blank=True, db_column="aciklama", verbose_name="Açıklama")
    # v93: oda tipi × kişi birim maliyetleri — [{"room_type_id", "guests", "variable", "shared"}, ...] (tutarlar metin)
    costs_data = models.JSONField(default=list, blank=True, db_column="maliyetler",
                                  verbose_name="Oda-gece maliyetleri (oda tipi × kişi)")

    class Meta:
        db_table = "donem_kapanislari"
        ordering = ["-month"]
        verbose_name = "Dönem kapanışı"
        verbose_name_plural = "Dönem kapanışları"

    def cost_rows(self):
        """Kapanıştaki oda-gece maliyetleri: room_type_id, guests, variable, shared alanlı satırlar."""
        return [SimpleNamespace(room_type_id=row["room_type_id"], guests=row["guests"],
                                variable=Decimal(row["variable"]), shared=Decimal(row["shared"]))
                for row in self.costs_data or []]

    def set_cost(self, room_type_id, guests, variable, shared):
        """Bir oda tipi × kişi maliyetini ekler ya da günceller (kaydetmez)."""
        rows = [row for row in (self.costs_data or []) if not (row["room_type_id"] == room_type_id and row["guests"] == guests)]
        rows.append({"room_type_id": room_type_id, "guests": guests, "variable": str(variable), "shared": str(shared)})
        self.costs_data = sorted(rows, key=lambda row: (row["room_type_id"], row["guests"]))

    @property
    def occupancy_rate(self):
        return self.occupied_room_nights / self.available_room_nights if self.available_room_nights else None

    @property
    def result(self):
        """Oda satışının sonucu: gelir − değişken gider − ortak gider − komisyon."""
        return self.room_revenue - self.variable_total - self.shared_total - self.commission_total

    def __str__(self):
        return f"{self.month:%m.%Y}"
