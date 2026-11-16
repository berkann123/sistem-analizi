"""STOK modülü: ürün kartları, stok hareketleri, tedarikçiler ve siparişler.

Stok miktarı ve ortalama maliyet ürün kartında saklanmaz gibi düşünülmeli: hareketlerden hesaplanır
(signals.py hareket kaydedilince kartı günceller). Sipariş stoğu değiştirmez; teslim alınınca alım hareketi yazılır.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.core.validators import MinValueValidator
from django.utils import timezone

from .ortak import NON_NEGATIVE, POSITIVE, RATE, ZERO


class Supplier(models.Model):
    """Tedarikçi kartı. Ürünler tedarikçiye serbest metinle değil, bu tabloya ilişkiyle bağlanır."""
    name = models.CharField(max_length=160, unique=True, db_column="tedarikci_adi", verbose_name="Tedarikçi adı")
    phone = models.CharField(max_length=40, blank=True, db_column="telefon", verbose_name="Telefon")
    email = models.EmailField(blank=True, db_column="e_posta", verbose_name="E-posta")
    notes = models.CharField(max_length=240, blank=True, db_column="aciklama", verbose_name="Açıklama")
    active = models.BooleanField(default=True, db_column="aktif", verbose_name="Aktif")

    class Meta:
        db_table = "tedarikciler"
        ordering = ["name"]
        verbose_name = "Tedarikçi"
        verbose_name_plural = "Tedarikçiler"

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    """Stok kartı. Kategori sabit bir listeden seçilir; gider merkezi kategoriden türetilir (v93, ayrı tablo yok).

    Tekstil ürünlerinde yıpranma bilgileri (ömür, hurda değeri, oda başı set) de bu kartta tutulur (v93; eski
    tekstil_varliklari tablosu). Ömrü girilmiş ürün tekstil sayılır: tüketilmez, yıpranır.
    """
    class Category(models.TextChoices):
        FOOD = "yiyecek", "Yiyecek"
        DRINK = "icecek", "İçecek"
        RESTAURANT = "restoran", "Restoran malzemeleri"
        AMENITY = "buklet", "Buklet"
        TEXTILE = "tekstil", "Tekstil"
        CLEANING = "temizlik", "Temizlik malzemeleri"

    class CostCenter(models.TextChoices):
        KITCHEN = "mutfak", "Mutfak"
        BAR = "bar", "Bar"
        HOUSEKEEPING = "kat_hizmetleri", "Kat hizmetleri"
        RESTAURANT = "restoran", "Restoran"

    # Kategori → gider merkezi. Kahvaltı büfesinde mutfak ve bar ürünleri GIDA, diğerleri restoranın servis sarfıdır.
    COST_CENTERS = {"yiyecek": "mutfak", "icecek": "bar", "restoran": "restoran", "buklet": "kat_hizmetleri",
                    "tekstil": "kat_hizmetleri", "temizlik": "kat_hizmetleri"}
    FOOD_COST_CENTERS = ("mutfak", "bar")

    class Unit(models.TextChoices):
        PIECE = "adet", "Adet"
        BUNCH = "demet", "Demet"
        KILOGRAM = "kg", "Kilogram"
        LITRE = "lt", "Litre"

    sku = models.CharField(max_length=80, unique=True, db_column="urun_kodu", verbose_name="Ürün kodu")
    name = models.CharField(max_length=180, db_column="urun_adi", verbose_name="Ürün adı")
    category = models.CharField(max_length=20, choices=Category.choices, db_column="kategori", verbose_name="Kategori")
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.PIECE, db_column="birim", verbose_name="Birim")
    current_stock = models.DecimalField(
        max_digits=14, decimal_places=3, default=0, db_column="mevcut_stok", verbose_name="Mevcut stok",
        help_text="Stok hareketlerinden otomatik hesaplanır.")
    reorder_level = models.DecimalField(max_digits=14, decimal_places=3, default=0, db_column="kritik_stok",
                                        validators=NON_NEGATIVE, verbose_name="Kritik stok")
    average_unit_cost = models.DecimalField(
        max_digits=14, decimal_places=4, default=0, db_column="birim_maliyeti", validators=NON_NEGATIVE,
        verbose_name="Birim maliyeti (KDV hariç)",
        help_text="Hareketli ağırlıklı ortalama; alım hareketlerinden otomatik hesaplanır.")
    wastage_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0, db_column="fire_orani",
                                       validators=RATE, verbose_name="Stok fire oranı",
                                       help_text="0 ile 1 arasında oran; ör. %5 için 0.05")
    is_perishable = models.BooleanField(default=False, db_column="bozulabilir", verbose_name="Bozulabilir")
    # PROTECT: ürünü olan tedarikçi silinemez; kullanılmıyorsa "Aktif" işaretini kaldırın.
    supplier = models.ForeignKey(Supplier, null=True, blank=True, related_name="items", db_column="tedarikci_id",
                                 on_delete=models.PROTECT, verbose_name="Tedarikçi")
    active = models.BooleanField(default=True, db_column="aktif", verbose_name="Aktif")
    # Tekstil yıpranması (v93): yalnız tekstil ürünlerinde doldurulur.
    textile_life = models.PositiveIntegerField(
        null=True, blank=True, db_column="tekstil_omru_oda_gece", validators=[MinValueValidator(1)],
        verbose_name="Tekstil ömrü (oda-gece)", help_text="Bir setin tahmini toplam oda-gece kullanım ömrü. "
                                                          "Doluysa ürün tekstil sayılır: tüketilmez, yıpranır.")
    textile_salvage_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, db_column="tekstil_hurda_degeri", validators=NON_NEGATIVE,
        verbose_name="Tekstil hurda değeri", help_text="Ömrü dolan setin kalan değeri (KDV hariç).")
    textile_sets_per_room = models.DecimalField(
        max_digits=8, decimal_places=3, default=1, db_column="tekstil_oda_basi_set", validators=NON_NEGATIVE,
        verbose_name="Oda başı set sayısı")

    class Meta:
        db_table = "envanter_urunleri"
        ordering = ["name"]
        verbose_name = "Envanter ürünü"
        verbose_name_plural = "Envanter ürünleri"

    @property
    def cost_center(self):
        return self.COST_CENTERS.get(self.category, "")

    @property
    def is_food(self):
        return self.cost_center in self.FOOD_COST_CENTERS

    @property
    def is_textile(self):
        return self.textile_life is not None

    def textile_cost(self, guests=1):
        """Bir oda-gecelik yıpranma payı: (maliyet − hurda) × oda başı set × (kişi esasında kişi) ÷ ömür."""
        if not self.textile_life:
            return ZERO
        # Hurda değeri maliyetten büyük girilmişse yıpranma payı eksiye düşmez.
        depreciable = max(Decimal(self.average_unit_cost) - Decimal(self.textile_salvage_value), ZERO)
        set_count = Decimal(self.textile_sets_per_room) * guests
        return depreciable * set_count / self.textile_life

    @property
    def textile_cost_per_set_night(self):
        return self.textile_cost(1)

    @property
    def is_critical(self):
        return self.current_stock <= self.reorder_level

    @property
    def stock_value(self):
        return self.current_stock * self.average_unit_cost

    def __str__(self):
        return f"{self.sku} — {self.name}"


class InventoryMovement(models.Model):
    """Stok hareketi (muhasebe fişi gibi düşünün): ürün kartındaki stok ve maliyet buradan türetilir."""
    class MovementType(models.TextChoices):
        PURCHASE = "alim", "Alım"
        CONSUMPTION = "tuketim", "Tüketim"
        WASTE = "fire", "Fire"
        TRANSFER_IN = "devir_giris", "Depoya giriş"
        TRANSFER_OUT = "devir_cikis", "Depodan çıkış"
        COUNT_ADJUSTMENT = "sayim_duzeltme", "Sayım düzeltmesi"

    INCOMING = (MovementType.PURCHASE, MovementType.TRANSFER_IN)
    OUTGOING = (MovementType.CONSUMPTION, MovementType.WASTE, MovementType.TRANSFER_OUT)

    movement_at = models.DateTimeField(default=timezone.now, db_column="hareket_tarihi", verbose_name="Hareket tarihi",
                                       help_text="Fatura/işlem tarihi. Geçmiş tarihli kayıt girilebilir.")
    consumption_day = models.DateField(
        null=True, blank=True, db_column="tuketim_gunu", verbose_name="Gün sonu tarihi",
        help_text="Yalnızca gün sonu komutunun konaklamalardan ürettiği tüketim ve fire kayıtlarında dolar: "
                  "bu hareket o gecenin konaklamalarının tüketimidir. Elle girilen harekette boş bırakın.")
    # PROTECT: hareketi olan ürün silinemez. Kullanılmayan ürünü silmek yerine "Aktif" işaretini kaldırın.
    item = models.ForeignKey(InventoryItem, related_name="movements", db_column="urun_id", on_delete=models.PROTECT,
                             verbose_name="Envanter ürünü")
    movement_type = models.CharField(max_length=30, choices=MovementType.choices, default=MovementType.PURCHASE,
                                     db_column="hareket_turu_kodu", verbose_name="Hareket türü")
    quantity = models.DecimalField(
        max_digits=14, decimal_places=3, db_column="hareket_miktari", verbose_name="Miktar",
        help_text="Her zaman pozitif girin; yönü hareket türü belirler. Yalnızca sayım düzeltmesi "
                  "eksi olabilir (sayımda eksik çıkan miktar).")
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0, db_column="birim_maliyeti_tl",
                                    validators=NON_NEGATIVE, verbose_name="Birim maliyeti (TL, KDV hariç)")
    notes = models.TextField(blank=True, null=True, db_column="aciklama", verbose_name="İşlem açıklaması / kaynağı")
    created_at = models.DateTimeField(auto_now_add=True, db_column="kayit_zamani", verbose_name="Kayıt zamanı")

    class Meta:
        db_table = "envanter_hareketleri"
        ordering = ["-movement_at", "-created_at"]
        verbose_name = "Stok hareketi"
        verbose_name_plural = "Stok hareketleri"
        constraints = [
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="ck_hareket_maliyet_negatif_olamaz"),
            models.CheckConstraint(
                condition=Q(quantity__gt=0) | Q(movement_type="sayim_duzeltme"),
                name="ck_hareket_miktar_pozitif",
            ),
            # Bir ürünün bir gecelik tüketimi (ve firesi) yalnızca bir kez düşülür; gün sonu iki kez çalışsa da.
            # Elle girilen hareketlerde gün boştur (NULL); MySQL boş değerleri tekrar saymaz.
            models.UniqueConstraint(fields=["item", "consumption_day", "movement_type"], name="uq_hareket_urun_gun_tur"),
        ]

    @staticmethod
    def signed(movement_type, quantity):
        """Hareketin stoğa etkisi: girişler artı, çıkışlar eksi, sayım düzeltmesi girildiği işaretle."""
        if movement_type in InventoryMovement.OUTGOING:
            return -quantity
        return quantity

    @property
    def signed_quantity(self):
        return self.signed(self.movement_type, self.quantity)

    def clean(self):
        if self.quantity is None:
            return
        is_adjustment = self.movement_type == self.MovementType.COUNT_ADJUSTMENT
        if self.quantity == 0:
            raise ValidationError({"quantity": "Miktar sıfır olamaz."})
        if self.quantity < 0 and not is_adjustment:
            raise ValidationError({"quantity": "Miktar pozitif olmalı. Stoğu azaltmak için tüketim, fire veya "
                                               "depodan çıkış türünü seçin."})
        if self.consumption_day and self.movement_type not in (self.MovementType.CONSUMPTION, self.MovementType.WASTE):
            raise ValidationError({"consumption_day": "Gün sonu tarihi yalnızca tüketim ve fire hareketlerinde olur."})
        if not self.item_id:
            return
        # Stok eksiye düşemez. Kayıt düzenleniyorsa eski etkisi hesaptan çıkarılır;
        # yalnızca durumu kötüleştiren değişiklik engellenir.
        others = InventoryMovement.objects.filter(item_id=self.item_id).exclude(pk=self.pk)
        stock_without_this = ZERO
        for movement_type, quantity in others.values_list("movement_type", "quantity"):
            stock_without_this += self.signed(movement_type, quantity)
        old_effect = ZERO
        previous = InventoryMovement.objects.filter(pk=self.pk).values_list("item_id", "movement_type", "quantity").first()
        if previous and previous[0] == self.item_id:
            old_effect = self.signed(previous[1], previous[2])
        new_effect = self.signed_quantity
        if stock_without_this + new_effect < 0 and new_effect < old_effect:
            available = stock_without_this + old_effect
            raise ValidationError({"quantity": f"Stok yetersiz: eldeki miktar {available:.3f}. "
                                               "Stok eksiye düşürülemez."})

    def save(self, *args, **kwargs):
        # Doğrulama yalnızca admin formunda değil, koddan yapılan her kayıtta da çalışsın.
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_movement_type_display()} · {self.quantity}"


class PurchaseOrder(models.Model):
    """Tedarikçiye verilen satın alma siparişi.

    Sipariş stoğu değiştirmez; yalnızca "teslim alındı" olduğunda her kalem için bir alım hareketi yazılır
    (stok ve ortalama maliyet hareketlerden türetildiği için). Açık siparişteki miktar, stok sayfasında
    "siparişte" olarak görünür; böylece aynı ürün iki kez sipariş edilmez.
    """
    class Status(models.TextChoices):
        OPEN = "acik", "Açık (teslim bekleniyor)"
        DELIVERED = "teslim_alindi", "Teslim alındı"
        CANCELLED = "iptal", "İptal"

    # PROTECT: siparişi olan tedarikçi silinemez.
    supplier = models.ForeignKey(Supplier, related_name="orders", db_column="tedarikci_id", on_delete=models.PROTECT,
                                 verbose_name="Tedarikçi")
    ordered_at = models.DateTimeField(default=timezone.now, db_column="siparis_tarihi", verbose_name="Sipariş tarihi")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_column="durum",
                              verbose_name="Durum")
    delivered_at = models.DateTimeField(null=True, blank=True, db_column="teslim_tarihi", verbose_name="Teslim tarihi")
    notes = models.CharField(max_length=240, blank=True, db_column="aciklama", verbose_name="Açıklama")

    class Meta:
        db_table = "siparisler"
        ordering = ["-ordered_at", "-id"]
        verbose_name = "Sipariş"
        verbose_name_plural = "Siparişler"

    @property
    def total(self):
        return sum((line.total for line in self.lines.all()), ZERO)

    def __str__(self):
        return f"Sipariş #{self.pk} · {self.supplier.name}"


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, related_name="lines", db_column="siparis_id", on_delete=models.CASCADE,
                              verbose_name="Sipariş")
    item = models.ForeignKey(InventoryItem, related_name="order_lines", db_column="urun_id", on_delete=models.PROTECT,
                             verbose_name="Envanter ürünü")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, db_column="siparis_miktari", validators=POSITIVE,
                                   verbose_name="Sipariş miktarı")
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, default=0, db_column="birim_fiyat_tl",
                                     validators=NON_NEGATIVE, verbose_name="Birim fiyat (TL, KDV hariç)")

    class Meta:
        db_table = "siparis_kalemleri"
        ordering = ["item__name"]
        verbose_name = "Sipariş kalemi"
        verbose_name_plural = "Sipariş kalemleri"
        constraints = [
            models.UniqueConstraint(fields=["order", "item"], name="uq_siparis_urun"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="ck_siparis_miktar_pozitif"),
        ]

    @property
    def total(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.item.name} · {self.quantity}"
