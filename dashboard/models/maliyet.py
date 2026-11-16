"""MALİYET modülü: bir oda-gecenin maliyetini oluşturan her şey.

Odalar ve oda tipleri, aylık giderler (kalemleri, mevsimleri), kahvaltı büfesi, oda paketi (buklet, temizlik,
minibar) ve tekstil yıpranması. Hesap kuralları services.py'dedir (calculate_monthly_room_cost).
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .ortak import NON_NEGATIVE, POSITIVE, RATE, ZERO, Season, months_of, season_of
from .stok import InventoryItem


class RoomType(models.Model):
    code = models.CharField(max_length=30, unique=True, db_column="oda_kodu")
    name = models.CharField(max_length=120, db_column="oda_tipi_adi")
    description = models.TextField(blank=True, null=True, db_column="aciklama")
    max_guests = models.SmallIntegerField(default=2, db_column="azami_misafir", validators=[MinValueValidator(1)])
    standard_cost_factor = models.DecimalField(
        max_digits=8, decimal_places=4, default=1, db_column="standart_maliyet_katsayisi", validators=POSITIVE,
        verbose_name="Maliyet payı katsayısı",
        help_text="Odanın ortak giderlerden aldığı payın ağırlığı (büyüklük ve donanım ölçüsü). 1,00 ölçü alınan "
                  "odadır; 2,00 olan oda tipi, sabit giderlerden ve oda başına değişken giderlerden iki kat pay alır. "
                  "Toplam gider değişmez, yalnızca oda tipleri arasındaki paylaşım değişir.",
    )
    target_markup = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.50"), db_column="hedef_kar_marji",
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal("5"))], verbose_name="Hedef kâr marjı",
        help_text="Başabaş maliyetinin üstüne eklenen kâr oranı: 0,50 = maliyet + %50. Hedef fiyat = başabaş × (1 + marj). "
                  "(Maliyet + %50, satış fiyatının yaklaşık üçte biri kârdır.)")
    min_markup = models.DecimalField(
        max_digits=5, decimal_places=4, default=ZERO, db_column="asgari_kar_marji",
        validators=[MinValueValidator(ZERO), MaxValueValidator(Decimal("1"))], verbose_name="Asgari kâr marjı (kâr koruması)",
        help_text="0'dan büyükse oda tipi hiçbir gün kârsız satılmaz: gece fiyatı ve konaklamanın otele kalan tutarı "
                  "(indirim ve kanal komisyonundan sonra) tam maliyet × (1 + bu oran) altına inmez; son dakika "
                  "indirimi ve otel kararları da bu sınırı aşamaz. 0 = koruma yok (oda başabaş ya da katkı için "
                  "satılabilir). 0,05 = maliyet + %5.")
    single_discount = models.DecimalField(
        max_digits=5, decimal_places=4, default=Decimal("0.10"), db_column="tek_kisi_indirimi", validators=RATE,
        verbose_name="Tek kişi indirimi",
        help_text="Odada tek kişi kalırsa 2 kişilik fiyattan yapılan indirim: 0,10 = %10 indirim.")
    extra_guest_rate = models.DecimalField(
        max_digits=12, decimal_places=2, default=ZERO, db_column="ek_kisi_ucreti", validators=NON_NEGATIVE,
        verbose_name="Ek kişi ücreti (TL / gece, KDV hariç)",
        help_text="2 kişiden sonraki her kişi için gecelik ücret (kahvaltı dahil). Etkinlik endeksiyle çarpılmaz.")
    active = models.BooleanField(default=True, db_column="aktif")
    # v93: piyasa (temel) fiyatları oda tipinde; eski temel_fiyatlar tablosu. 2 kişi + kahvaltı, bir gece, KDV hariç.
    winter_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, db_column="kis_fiyati",
                                      validators=NON_NEGATIVE, verbose_name="Kış piyasa fiyatı (TL)")
    transition_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, db_column="gecis_fiyati",
                                          validators=NON_NEGATIVE, verbose_name="Geçiş piyasa fiyatı (TL)")
    summer_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, db_column="yaz_fiyati",
                                      validators=NON_NEGATIVE, verbose_name="Yaz piyasa fiyatı (TL)")

    SEASON_FIELDS = {"kis": "winter_rate", "gecis": "transition_rate", "yaz": "summer_rate"}

    def market_rate(self, season):
        """Mevsimin 2 kişilik piyasa fiyatı (kış / geçiş / yaz); girilmemişse None."""
        field = self.SEASON_FIELDS.get(season)
        return getattr(self, field) if field else None

    class Meta:
        db_table = "oda_tipleri"
        ordering = ["code"]
        verbose_name = "Oda tipi"
        verbose_name_plural = "Oda tipleri"

    def __str__(self):
        return f"{self.code} — {self.name}"


class Room(models.Model):
    class ViewType(models.TextChoices):
        # Manzara odanın özelliğidir, oda tipinin adına yazılmaz (ör. "Deluxe Oda" + deniz manzaralı oda).
        SEA = "deniz", "Deniz manzaralı"
        CITY = "sehir", "Şehir manzaralı"
        LAND = "kara", "Kara manzaralı"
        NONE = "manzarasiz", "Manzarasız"

    class Status(models.TextChoices):
        # Durum, odanın SATILABİLİR olup olmadığını söyler; dolu/boş bilgisi konaklamalardan gelir.
        ACTIVE = "aktif", "Aktif (satışa açık)"
        MAINTENANCE = "bakimda", "Bakımda"
        INACTIVE = "pasif", "Pasif"

    room_number = models.CharField(max_length=30, unique=True, db_column="oda_numarasi")
    # PROTECT: odası olan bir oda tipi silinemez; önce odalar başka tipe taşınmalıdır.
    room_type = models.ForeignKey(RoomType, db_column="oda_tipi_id", on_delete=models.PROTECT)
    floor = models.SmallIntegerField(blank=True, null=True, db_column="kat")
    view_type = models.CharField(max_length=12, choices=ViewType.choices, default=ViewType.NONE, db_column="manzara_tipi",
                                 verbose_name="Manzara")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_column="durum")
    opened_on = models.DateField(blank=True, null=True, db_column="acilis_tarihi")

    class Meta:
        db_table = "odalar"
        ordering = ["room_number"]
        verbose_name = "Oda"
        verbose_name_plural = "Odalar"

    def is_occupied_on(self, day):
        """O gece odada konaklama var mı? Odada saklanan bir işaret değil, konaklamalardan hesaplanır."""
        return self.stays.filter(check_in__lte=day, check_out__gt=day).exists()

    def __str__(self):
        return self.room_number


class MonthlyExpenseCategory(models.Model):
    """Gider kalemi ve maliyet davranışı.

    Davranış, giderin dolulukla nasıl değiştiğini söyler ve odaya nasıl yükleneceğini belirler:
      sabit         -> otel boş da olsa oluşur. Aylık tutar müsait oda-gecelere bölünür.
      yarı değişken -> iki parçalıdır: sabit taban (müsait oda-gecelere bölünür)
                       + satılan her oda-gece (ya da konaklayan her kişi-gece) için eklenen değişken tutar.
      değişken      -> yalnızca oda satılınca oluşur. Aylık sabit tutarı yoktur;
                       satılan her oda-geceye (ya da kişi-geceye) doğrudan eklenir.

    Değişken tutarın üç esası vardır: oda-gece (odaya bağlı tüketim), kişi-gece (kişiye bağlı tüketim)
    ve konaklama (gece sayısından bağımsız, her giriş-çıkışta bir kez oluşan gider; ör. çarşaf yıkama).

    Enerji de bu yapıyla tutulur: "Enerji giderleri" grubunda Elektrik, Su ve Doğalgaz kalemleri
    yarı değişkendir. Sabit taban otel boşken de gelen faturadır; değişken tutar misafirle artan kısımdır.
    """
    class Group(models.TextChoices):
        # Raporlardaki sıra bu listenin sırasıdır.
        STAFF = "personel", "Personel giderleri"
        ENERGY = "enerji", "Enerji giderleri"
        BUILDING = "bina", "Bina giderleri"
        MAINTENANCE = "bakim", "Bakım ve onarım giderleri"
        ADMINISTRATION = "genel_yonetim", "Genel yönetim giderleri"
        MARKETING = "pazarlama", "Pazarlama ve satış giderleri"
        DEPRECIATION = "amortisman", "Amortisman giderleri"
        OTHER = "diger", "Diğer giderler"

    class CostBehavior(models.TextChoices):
        FIXED = "sabit", "Sabit"
        SEMI_VARIABLE = "yari_degisken", "Yarı değişken (sabit taban + satılan oda başı tutar)"
        VARIABLE = "degisken", "Değişken (yalnızca satılan oda başı tutar)"

    class VariableBasis(models.TextChoices):
        PER_ROOM_NIGHT = "oda_gecesi", "Satılan oda-gece başına"
        PER_GUEST_NIGHT = "kisi_gecesi", "Konaklayan kişi-gece başına"
        PER_STAY = "konaklama", "Konaklama başına (her giriş-çıkışta bir kez)"

    name = models.CharField(max_length=120, unique=True, db_column="gider_kalemi", verbose_name="Gider kalemi")
    group = models.CharField(max_length=20, choices=Group.choices, default=Group.OTHER, db_column="gider_grubu",
                             verbose_name="Gider grubu")
    cost_behavior = models.CharField(max_length=20, choices=CostBehavior.choices, default=CostBehavior.FIXED,
                                     db_column="gider_davranisi", verbose_name="Maliyet davranışı")
    variable_basis = models.CharField(
        max_length=20, choices=VariableBasis.choices, default=VariableBasis.PER_ROOM_NIGHT,
        db_column="degisken_tutar_esasi", verbose_name="Değişken tutarın esası",
        help_text="Yarı değişken ve değişken kalemlerde değişken tutarın neyle çarpılacağı. Oda kliması gibi "
                  "odaya bağlı tüketim için oda-gece, su gibi kişiye bağlı tüketim için kişi-gece, çıkışta "
                  "çarşaf yıkama gibi gece sayısından bağımsız giderler için konaklama seçin.")
    notes = models.CharField(max_length=240, blank=True, db_column="aciklama")
    active = models.BooleanField(default=True, db_column="aktif")

    class Meta:
        db_table = "aylik_gider_kategorileri"
        ordering = ["name"]
        verbose_name = "Aylık gider kategorisi"
        verbose_name_plural = "Aylık gider kategorileri"

    def clean(self):
        # Davranış değiştirilirken, bu kalemin mevcut gider kayıtlarıyla çelişki oluşmamalı.
        if not self.pk:
            return
        expenses = self.monthlyhotelexpense_set.all()
        if self.cost_behavior == self.CostBehavior.FIXED and expenses.filter(variable_rate__gt=0).exists():
            raise ValidationError({"cost_behavior": "Bu kalemin değişken tutar girilmiş kayıtları var. Sabit yapmadan "
                                                    "önce o kayıtlardaki değişken tutarı sıfırlayın."})
        if self.cost_behavior == self.CostBehavior.VARIABLE and expenses.filter(amount__gt=0).exists():
            raise ValidationError({"cost_behavior": "Bu kalemin aylık sabit tutar girilmiş kayıtları var. Sabit tabanı "
                                                    "olan bir kalem için 'Yarı değişken' seçin."})

    @property
    def group_order(self):
        """Grubun raporlardaki sırası (Group listesindeki yeri)."""
        return list(self.Group.values).index(self.group) if self.group in self.Group.values else len(self.Group.values)

    def __str__(self):
        return self.name


class MonthlyHotelExpense(models.Model):
    """Aylık gider kaydı.

    Bir gider kaleminin her ay için en fazla BİR kaydı olur.
    Kalemin o aya ait kaydı varsa o ay için o geçerlidir. Yoksa aynı kalemin en son
    "her ay tekrarlar" kaydı o aya devreder. Böylece zamlı kira yeni ay için girildiğinde
    eski tutarla birlikte iki kez sayılmaz.

    Aynı kalemin farklı aylara ait birden çok kaydı olması tekrar değil, tutarın GEÇMİŞİDİR
    (ör. Ekim'de 280.000 TL, Ocak'ta 350.000 TL kira). Geçerli olan her zaman en yenisidir.
    """
    class MonthlyRepeat(models.TextChoices):
        YES = "evet", "Evet"
        NO = "hayir", "Hayır"

    expense_month = models.DateField(db_column="gider_ayi", verbose_name="Gider ayı",
                                     help_text="İlgili aydan herhangi bir gün seçin; ayın ilk günü olarak kaydedilir.")
    category = models.ForeignKey(MonthlyExpenseCategory, db_column="gider_kategorisi_id", on_delete=models.PROTECT, verbose_name="Gider kategorisi")
    season = models.CharField(
        max_length=10, choices=Season.choices, blank=True, default="", db_column="mevsim", verbose_name="Mevsim",
        help_text="Boş: kayıt bütün aylarda geçerlidir. Seçilirse yalnızca o mevsimin aylarında (her yıl) geçerlidir; "
                  "ör. elektriğin kış, geçiş ve yaz değerleri için birer kayıt.")
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, db_column="tutar", validators=NON_NEGATIVE,
        verbose_name="Aylık sabit tutar (TL, KDV hariç)",
        help_text="Sabit kalemde giderin tamamı; yarı değişken kalemde yalnızca sabit taban. Değişken kalemde 0.")
    variable_rate = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, db_column="degisken_birim_tutar", validators=NON_NEGATIVE,
        verbose_name="Değişken birim tutar (TL, KDV hariç)",
        help_text="Satılan bir oda-gece, konaklayan bir kişi-gece ya da bir konaklama için eklenen tutar; hangisi "
                  "olduğunu gider kaleminin 'Değişken tutarın esası' belirler. Sabit kalemde 0.")
    recurs_monthly = models.CharField(
        max_length=5, choices=MonthlyRepeat.choices, default=MonthlyRepeat.NO, db_column="her_ay_tekrarlar",
        verbose_name="Her ay tekrarlar mı?",
        help_text="Evet seçilirse gider sonraki aylara da uygulanır. Aynı kategoride sonraki bir aya yeni "
                  "kayıt girildiğinde o aydan itibaren yeni kayıt geçerli olur (iki kez sayılmaz).")
    recurring_until = models.DateField(
        null=True, blank=True, db_column="tekrar_bitis_tarihi", verbose_name="Tekrar bitiş tarihi",
        help_text="Çoğu gider için BOŞ bırakın: gider süresiz devam eder. Yalnızca gider belirli bir tarihte "
                  "sona erecekse doldurun; bu tarihten sonraki aylarda gider hesaba girmez.")
    description = models.CharField(max_length=240, blank=True, db_column="aciklama", verbose_name="Açıklama")

    class Meta:
        db_table = "aylik_otel_giderleri"
        ordering = ["-expense_month", "category__name"]
        verbose_name = "Aylık otel gideri"
        verbose_name_plural = "Aylık otel giderleri"
        constraints = [
            # Bir gider kaleminin bir ayda tek kaydı olur. Aynı kalem aynı aya iki kez girilirse
            # tutarlar toplanır ve gider iki kez sayılırdı; veritabanı buna izin vermez.
            models.UniqueConstraint(fields=["category", "expense_month"], name="uq_gider_kalem_ay"),
        ]

    def clean(self):
        # Ay, benzersizlik denetiminden önce ayın ilk gününe çevrilir; böylece "15 Ekim" girilen
        # bir kayıt, var olan "1 Ekim" kaydıyla aynı ay olarak yakalanır.
        if self.expense_month:
            self.expense_month = self.expense_month.replace(day=1)
        if self.recurring_until and self.expense_month and self.recurring_until < self.expense_month:
            raise ValidationError({"recurring_until": "Tekrar bitiş tarihi gider ayından önce olamaz."})
        if self.season:
            if self.recurs_monthly != self.MonthlyRepeat.YES:
                raise ValidationError({"recurs_monthly": "Mevsim kaydı her yıl tekrarlanır; 'Her ay tekrarlar' Evet olmalı."})
            months = months_of(self.season)
            if self.expense_month and self.expense_month.month not in months:
                raise ValidationError({"expense_month": f"Gider ayı {self.get_season_display()} mevsiminin aylarından biri "
                                                        f"olmalı ({', '.join(str(m) for m in months)})."})
        if not self.category_id or self.amount is None or self.variable_rate is None:
            return
        behavior = self.category.cost_behavior
        Behavior = MonthlyExpenseCategory.CostBehavior
        if behavior == Behavior.FIXED and self.variable_rate > 0:
            raise ValidationError({"variable_rate": "Sabit bir gider kaleminde değişken tutar olmaz. Kalemin "
                                                    "davranışını 'Yarı değişken' yapın ya da bu alanı 0 bırakın."})
        if behavior == Behavior.VARIABLE:
            if self.amount > 0:
                raise ValidationError({"amount": "Değişken bir gider kaleminin aylık sabit tutarı olmaz. Sabit tabanı "
                                                 "varsa kalemin davranışını 'Yarı değişken' yapın."})
            if self.variable_rate <= 0:
                raise ValidationError({"variable_rate": "Değişken gider kaleminde değişken birim tutar girilmelidir."})
        if behavior != Behavior.VARIABLE and self.amount <= 0 and self.variable_rate <= 0:
            raise ValidationError("Aylık sabit tutar ya da değişken tutardan en az biri sıfırdan büyük olmalı.")

    def save(self, *args, **kwargs):
        if self.expense_month:
            self.expense_month = self.expense_month.replace(day=1)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.category.name} · {self.expense_month:%Y-%m}"


class ConsumptionRecipe(models.Model):
    """Standart tüketim reçetesi (v93): bir satışta ne kadar malzeme harcanır. Eski kahvaltı büfesi ve oda paketi.

    esas = kahvalti      : kahvaltı büfesi, kişi başı miktar (misafir sayısı boş)
    esas = oda_gecesi    : oda paketi, oda başına bir gecelik miktar (misafir sayısına göre satır)
    esas = kisi_gecesi   : oda paketi, kişi başına bir gecelik miktar (miktar × misafir sayısı)
    Tekstil ürünü (ömrü girilmiş) tüketilmez; maliyeti yıpranma payıdır (envanter kartındaki tekstil bilgileri).
    """
    class Basis(models.TextChoices):
        BREAKFAST = "kahvalti", "Kahvaltı büfesi (kişi başı)"
        PER_ROOM_NIGHT = "oda_gecesi", "Oda başına / gece"
        PER_GUEST_NIGHT = "kisi_gecesi", "Kişi başına / gece"

    item = models.ForeignKey(InventoryItem, db_column="urun_id", on_delete=models.PROTECT,
                             verbose_name="Envanter ürünü (kod ve ad)")
    basis = models.CharField(max_length=20, choices=Basis.choices, db_column="esas", verbose_name="Esas")
    guest_count = models.PositiveSmallIntegerField(null=True, blank=True, db_column="misafir_sayisi",
                                                   validators=[MinValueValidator(1)], verbose_name="Misafir sayısı",
                                                   help_text="Oda paketinde yatak düzeni; kahvaltı büfesinde boş.")
    quantity = models.DecimalField(max_digits=12, decimal_places=4, db_column="miktar", validators=NON_NEGATIVE,
                                   verbose_name="Miktar")
    waste_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0, db_column="fire_orani",
                                     validators=RATE, verbose_name="Fire oranı")
    notes = models.CharField(max_length=240, blank=True, db_column="aciklama", verbose_name="Açıklama")
    active = models.BooleanField(default=True, db_column="aktif", verbose_name="Aktif")

    class Meta:
        db_table = "standart_tuketim"
        ordering = ["basis", "guest_count", "item__name"]
        verbose_name = "Standart tüketim (reçete)"
        verbose_name_plural = "Standart tüketim (reçete)"
        constraints = [models.UniqueConstraint(fields=["basis", "guest_count", "item"], name="uq_recete_esas_kisi_urun")]

    def clean(self):
        if self.basis == self.Basis.BREAKFAST and self.guest_count:
            raise ValidationError({"guest_count": "Kahvaltı büfesi satırında misafir sayısı boş bırakılır."})
        if self.basis != self.Basis.BREAKFAST and not self.guest_count:
            raise ValidationError({"guest_count": "Oda paketi satırında misafir sayısı girilmelidir."})

    @property
    def is_textile(self):
        return self.item.is_textile

    @property
    def is_service_supply(self):
        """Gıda değil, restoranın servis sarfı mı? (ürün kategorisinin gider merkezinden)"""
        return not self.item.is_food

    @property
    def kind_label(self):
        return "Restoran sarfı" if self.is_service_supply else "Gıda"

    @property
    def effective_waste_rate(self):
        """Satırdaki fire ile ürün kartındaki fireden büyük olanı kullanılır."""
        return max(self.waste_rate, self.item.wastage_rate)

    @property
    def line_cost(self):
        """Bir birimin (kişi ya da oda) maliyeti; tekstilde yıpranma payı, diğerlerinde fireli tüketim."""
        if self.is_textile:
            return self.quantity * self.item.textile_cost_per_set_night
        return self.quantity * (Decimal("1") + self.effective_waste_rate) * self.item.average_unit_cost

    # Eski alan adları (okuma): kahvaltı "kişi başı miktar", oda paketi "oda-gece miktarı".
    @property
    def quantity_per_guest(self):
        return self.quantity

    @property
    def quantity_per_room_night(self):
        return self.quantity

    def __str__(self):
        if self.basis == self.Basis.BREAKFAST:
            return f"{self.item.name} / kişi"
        return f"{self.guest_count} kişi · {self.item.name}"


class _BasisManager(models.Manager):
    def __init__(self, bases):
        super().__init__()
        self.bases = bases

    def get_queryset(self):
        return super().get_queryset().filter(basis__in=self.bases)


class BreakfastBuffetItem(ConsumptionRecipe):
    """Kahvaltı büfesi: reçete tablosunun kahvaltı satırları (Admin'de ayrı ekran; ayrı tablo değil)."""
    objects = _BasisManager([ConsumptionRecipe.Basis.BREAKFAST])

    class Meta:
        proxy = True
        verbose_name = "Kahvaltı büfesi ürünü"
        verbose_name_plural = "Kahvaltı büfesi"

    def save(self, *args, **kwargs):
        self.basis, self.guest_count = self.Basis.BREAKFAST, None
        super().save(*args, **kwargs)


class RoomPackageItem(ConsumptionRecipe):
    """Oda paketi: reçete tablosunun oda-gece / kişi-gece satırları (Admin'de ayrı ekran; ayrı tablo değil)."""
    objects = _BasisManager([ConsumptionRecipe.Basis.PER_ROOM_NIGHT, ConsumptionRecipe.Basis.PER_GUEST_NIGHT])
    UsageBasis = ConsumptionRecipe.Basis

    class Meta:
        proxy = True
        verbose_name = "Oda paketi kalemi"
        verbose_name_plural = "Oda paketi"

    def save(self, *args, **kwargs):
        if not self.basis or self.basis == self.Basis.BREAKFAST:
            self.basis = self.Basis.PER_GUEST_NIGHT
        super().save(*args, **kwargs)
