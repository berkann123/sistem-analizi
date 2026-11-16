"""SATIŞ VE FİYAT modülü: konaklamalar, satış kanalları, temel fiyatlar, etkinlik takvimi ve vergiler.

Konaklamalar doluluğu (ve gün sonunda stok tüketimini) belirler. Fiyat önerisi = mevsimin temel fiyatı × o gecenin
en yüksek etkinlik etkisi; hesap services.py'deki price_calendar'dadır.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from .maliyet import Room, RoomType
from .ortak import DEFAULT_SEASON_MONTHS, NON_NEGATIVE, RATE, ZERO, Season, index_label


class SalesChannel(models.Model):
    """Satış kanalı: konaklamanın nereden satıldığı (web sitesi, telefon, Booking.com vb.).

    Ayrı tablodur; yeni kanal kod değişmeden admin'den eklenir. Fiyatlandırmada kanal komisyonu buraya eklenecek.
    """
    name = models.CharField(max_length=80, unique=True, db_column="kanal_adi", verbose_name="Kanal")
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=4, default=ZERO, db_column="komisyon_orani", validators=RATE,
        verbose_name="Komisyon oranı",
        help_text="Kanalın satış tutarından (KDV hariç) aldığı pay: 0,17 = %17. Doğrudan satışta 0.")
    notes = models.CharField(max_length=240, blank=True, db_column="aciklama", verbose_name="Açıklama")

    class Meta:
        db_table = "satis_kanallari"
        ordering = ["id"]
        verbose_name = "Satış kanalı"
        verbose_name_plural = "Satış kanalları"

    def __str__(self):
        return self.name


class StayQuerySet(models.QuerySet):
    def occupying(self):
        """Odayı gerçekten dolduran konaklamalar: iptal edilen ve misafirin gelmediği kayıtlar hariç."""
        return self.filter(status=Stay.Status.CONFIRMED)


class Stay(models.Model):
    """Konaklama: bir odanın hangi tarihlerde dolu olduğunu ve kaça satıldığını söyleyen kayıt.

    Doluluk bu tablodan TÜRETİLİR; ayrıca bir yerde "dolu oda sayısı" ya da odada "dolu" işareti
    tutulmaz. Bir odanın bugün dolu olup olmadığı da, ayın doluluk oranı da bu kayıtlardan hesaplanır.
    Aynı bilgiyi iki yerde saklamak (ör. elle girilen günlük dolu oda sayısı) iki kaynağın
    birbirini tutmamasına yol açar.

    Giriş günü dahil, çıkış günü hariçtir: 10 Ekim giriş, 12 Ekim çıkış = 10 ve 11 Ekim geceleri.

    Satış bilgisi: gecelik fiyat, kanal, rezervasyon tarihi ve durum. Konaklamanın toplam tutarı ayrıca
    saklanmaz; gecelik fiyat × gece sayısıdır. Konaklamanın geçmişte mi gelecekte mi olduğu da tarihlerden
    bellidir; durum yalnızca iptal ve gelmeme (no-show) bilgisini taşır. Yalnızca "Onaylandı" durumundaki
    konaklama doluluğa girer ve gün sonunda stoktan tüketim düşer.
    """
    class Status(models.TextChoices):
        CONFIRMED = "onaylandi", "Onaylandı"
        CANCELLED = "iptal", "İptal edildi"
        NO_SHOW = "gelmedi", "Misafir gelmedi (no-show)"

    room = models.ForeignKey("Room", related_name="stays", db_column="oda_id", on_delete=models.PROTECT,
                             verbose_name="Oda")
    channel = models.ForeignKey(SalesChannel, null=True, blank=True, related_name="stays", db_column="satis_kanali_id",
                                on_delete=models.PROTECT, verbose_name="Satış kanalı")
    booked_on = models.DateField(null=True, blank=True, db_column="rezervasyon_tarihi", verbose_name="Rezervasyon tarihi",
                                 help_text="Rezervasyonun yapıldığı gün. Giriş tarihinden sonra olamaz.")
    check_in = models.DateField(db_column="giris_tarihi", verbose_name="Giriş tarihi")
    check_out = models.DateField(db_column="cikis_tarihi", verbose_name="Çıkış tarihi")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED, db_column="durum",
                              verbose_name="Durum")
    guests = models.PositiveSmallIntegerField(default=1, db_column="misafir_sayisi", validators=[MinValueValidator(1)],
                                              verbose_name="Misafir sayısı")
    nightly_rate = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, db_column="gecelik_fiyat", validators=NON_NEGATIVE,
        verbose_name="Gecelik satış fiyatı (TL, KDV hariç)",
        help_text="Odanın bir gecelik satış fiyatı (bütün misafirler için). Maliyetler gibi KDV hariç girilir.")
    notes = models.CharField(max_length=240, blank=True, db_column="aciklama", verbose_name="Açıklama")

    objects = StayQuerySet.as_manager()

    class Meta:
        db_table = "konaklamalar"
        ordering = ["-check_in", "room__room_number"]
        verbose_name = "Konaklama"
        verbose_name_plural = "Konaklamalar"
        constraints = [
            models.CheckConstraint(condition=Q(check_out__gt=models.F("check_in")),
                                   name="ck_konaklama_cikis_giristen_sonra"),
            models.CheckConstraint(condition=Q(nightly_rate__isnull=True) | Q(nightly_rate__gte=0),
                                   name="ck_konaklama_fiyat_negatif_degil"),
        ]

    @property
    def nights(self):
        return (self.check_out - self.check_in).days

    @property
    def total_price(self):
        """Konaklamanın toplam tutarı (TL, KDV hariç); fiyat girilmemişse None."""
        return self.nightly_rate * self.nights if self.nightly_rate is not None else None

    def clean(self):
        if not (self.check_in and self.check_out):
            return
        if self.check_out <= self.check_in:
            raise ValidationError({"check_out": "Çıkış tarihi giriş tarihinden sonra olmalı."})
        if self.booked_on and self.booked_on > self.check_in:
            raise ValidationError({"booked_on": "Rezervasyon tarihi giriş tarihinden sonra olamaz."})
        if not self.room_id:
            return
        if self.guests and self.guests > self.room.room_type.max_guests:
            raise ValidationError({"guests": f"Bu oda en fazla {self.room.room_type.max_guests} misafir alır."})
        if self.status != self.Status.CONFIRMED:
            return                                     # iptal / gelmeyen kayıt odayı tutmaz; çakışma denetlenmez
        if self.room.status != Room.Status.ACTIVE:
            raise ValidationError({"room": "Bu oda satışa açık değil (bakımda ya da pasif)."})
        # Aynı oda aynı gece iki konaklamaya verilemez. İki aralık, biri diğeri bitmeden başlıyorsa çakışır.
        clash = (Stay.objects.occupying()
                 .filter(room_id=self.room_id, check_in__lt=self.check_out, check_out__gt=self.check_in)
                 .exclude(pk=self.pk).first())
        if clash:
            raise ValidationError({"check_in": f"Oda bu tarihlerde dolu: {clash.check_in:%d.%m.%Y} – "
                                               f"{clash.check_out:%d.%m.%Y} arasında başka bir konaklama var."})

    def save(self, *args, **kwargs):
        # Çakışma denetimi yalnızca admin formunda değil, koddan yapılan her kayıtta da çalışsın.
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.room.room_number} · {self.check_in:%d.%m.%Y} – {self.check_out:%d.%m.%Y}"


class Event(models.Model):
    """Fiyatı etkileyen etkinlik ya da özel gün (fuar, bayram, festival...).

    Tarihler GECE olarak girilir (giriş günü dahil, bitiş günü dahil): 4-6 Aralık = 4, 5 ve 6 Aralık geceleri.
    Hafta günü seçilirse kayıt, tarih aralığı içinde her hafta o gece geçerlidir (ör. "Cuma geceleri +%10").
    Endeks temel fiyatın çarpanıdır (1,40 = %40 fazla). Aynı geceye birden çok etkinlik denk gelirse en yüksek
    endeks geçerlidir. Dini bayramların tarihi her yıl değiştiği için her yıl ayrı kayıt girilir.
    "Otel fiyat kararı" türü dış bir etkinlik değil, otelin kendi kararıdır (talep artışı, kampanya, indirim):
    girildiği gecede otomatik kuralın yerine geçer ve açıklaması takvimde gerekçe olarak gösterilir.
    """
    class Kind(models.TextChoices):
        FAIR = "fuar", "Fuar"
        NATIONAL = "milli_bayram", "Milli bayram / resmi tatil"
        RELIGIOUS = "dini_bayram", "Dini bayram"
        FESTIVAL = "festival", "Festival / kültür-sanat"
        SPORT = "spor", "Spor"
        SPECIAL = "ozel_gun", "Özel gün"
        WEEKLY = "haftalik", "Her hafta (hafta günü)"
        DECISION = "fiyat_karari", "Otel fiyat kararı (artış / kampanya / indirim)"

    WEEKDAYS = [(0, "Pazartesi"), (1, "Salı"), (2, "Çarşamba"), (3, "Perşembe"), (4, "Cuma"), (5, "Cumartesi"),
                (6, "Pazar")]

    name = models.CharField(max_length=120, db_column="etkinlik_adi", verbose_name="Etkinlik")
    kind = models.CharField(max_length=20, choices=Kind.choices, db_column="tur", verbose_name="Tür")
    start_date = models.DateField(db_column="baslangic_gecesi", verbose_name="İlk gece")
    end_date = models.DateField(db_column="son_gece", verbose_name="Son gece")
    weekday = models.PositiveSmallIntegerField(
        null=True, blank=True, choices=WEEKDAYS, db_column="hafta_gunu", verbose_name="Hafta günü",
        help_text="Yalnızca 'Her hafta' türünde: tarih aralığı içinde her hafta bu gece geçerlidir.")
    estimated = models.BooleanField(default=False, db_column="tarih_tahmini", verbose_name="Tarih tahmini",
                                    help_text="İşaretliyse tarih henüz açıklanmadı; geçen yıla göre tahmin edildi.")
    index = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.10"), db_column="fiyat_endeksi",
                                validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("3.00"))],
                                verbose_name="Fiyat endeksi",
                                help_text="Temel fiyatın çarpanı: 1,40 = %40 fazla, 0,90 = %10 indirim. 0,50'nin altı yalnızca otel fiyat kararında.")
    source = models.CharField(max_length=240, blank=True, db_column="kaynak", verbose_name="Kaynak")
    notes = models.CharField(max_length=240, blank=True, db_column="aciklama", verbose_name="Açıklama")
    published = models.BooleanField(
        default=True, db_column="yayinda", verbose_name="Yayında",
        help_text="Yalnızca otel fiyat kararında anlamlıdır. İşaretsizse karar taslaktır: fiyat takviminde değerlendirme "
                  "için görünür, rezervasyon fiyatına uygulanmaz.")

    class Meta:
        db_table = "etkinlikler"
        ordering = ["start_date", "name"]
        verbose_name = "Etkinlik"
        verbose_name_plural = "Etkinlik takvimi"
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=models.F("start_date")), name="ck_etkinlik_tarih_sirasi"),
            models.UniqueConstraint(fields=["name", "start_date"], name="uq_etkinlik_ad_tarih"),
        ]

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Son gece ilk geceden önce olamaz."})
        if (self.kind == self.Kind.WEEKLY) != (self.weekday is not None):
            raise ValidationError({"weekday": "Hafta günü yalnızca 'Her hafta' türündeki kayıtta seçilir ve orada zorunludur."})
        if self.kind != self.Kind.DECISION and self.index is not None and self.index < Decimal("0.50"):
            raise ValidationError({"index": "%50'den büyük indirim yalnızca 'Otel fiyat kararı' türünde girilebilir."})
        if self.kind == self.Kind.DECISION and not self.notes.strip():
            raise ValidationError({"notes": "Fiyat kararında açıklama zorunludur; takvimde gecenin gerekçesi olarak gösterilir."})

    @property
    def is_decision(self):
        return self.kind == self.Kind.DECISION

    def applies_on(self, day):
        """Bu kayıt o gece geçerli mi? (tarih aralığı içinde; haftalıksa yalnızca kendi hafta gününde)"""
        return self.start_date <= day <= self.end_date and (self.weekday is None or day.weekday() == self.weekday)

    @property
    def percent(self):
        return (self.index - 1) * 100

    @property
    def change_label(self):
        return index_label(self.index)

    def __str__(self):
        return f"{self.name} ({self.start_date:%d.%m.%Y})"


class TaxRate(models.Model):
    """Tarihli oranlar (v93): konaklama vergileri ve yıllık hammadde fiyat endeksi, geçerlilik başlangıcıyla.

    Bir tarihte geçerli oran: o tarihe kadar başlamış en son kayıt. İki vergi de KDV hariç oda bedeli
    üzerinden ayrı ayrı hesaplanır; konaklama vergisi KDV matrahına girmez.
    """
    class Kind(models.TextChoices):
        VAT = "kdv", "KDV"
        ACCOMMODATION = "konaklama", "Konaklama vergisi"
        MATERIAL = "hammadde", "Hammadde fiyat endeksi"     # v93: eski hammadde_fiyat_endeksi tablosu

    kind = models.CharField(max_length=10, choices=Kind.choices, db_column="vergi", verbose_name="Vergi")
    valid_from = models.DateField(db_column="gecerlilik_baslangici", verbose_name="Geçerlilik başlangıcı")
    rate = models.DecimalField(max_digits=6, decimal_places=4, db_column="oran",
                               validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("5"))],
                               verbose_name="Oran",
                               help_text="Vergide 0,10 = %10. Hammadde endeksinde o yılın fiyat düzeyi: 0,75 = bugünkünden "
                                         "%25 ucuz (geçerlilik başlangıcı yılın 1 Ocak'ı).")
    source = models.CharField(max_length=240, blank=True, db_column="kaynak", verbose_name="Kaynak")
    notes = models.CharField(max_length=240, blank=True, db_column="aciklama", verbose_name="Açıklama")

    class Meta:
        db_table = "oranlar"
        ordering = ["kind", "-valid_from"]
        verbose_name = "Oran (vergi, hammadde endeksi)"
        verbose_name_plural = "Oranlar (vergi, hammadde endeksi)"
        constraints = [models.UniqueConstraint(fields=["kind", "valid_from"], name="uq_vergi_tarih")]

    def clean(self):
        if self.kind != self.Kind.MATERIAL and self.rate is not None and self.rate >= 1:
            raise ValidationError({"rate": "Vergi oranı 0 ile 1 arasında yazılır (0,10 = %10)."})

    def __str__(self):
        if self.kind == self.Kind.MATERIAL:
            return f"Hammadde endeksi {self.valid_from:%Y}: {self.rate}"
        return f"{self.get_kind_display()} %{self.rate * 100:g} ({self.valid_from:%d.%m.%Y})"


class PricingRules(models.Model):
    """Dinamik fiyat kuralları: tek satırlık ayar tablosu (Admin › Fiyat kuralları).

    Gece fiyatı = temel fiyat × gecenin etkisi × doluluk çarpanı. Doluluk anlıktır: rezervasyon anında o gece için
    satılmış oda ÷ aktif oda. Konaklama fiyatına erken rezervasyon ve konaklama süresi indirimi sırayla uygulanır.
    Oranlar 0–1 arası yazılır (0,15 = %15); çarpanlar 1'e göre (1,15 = %15 artış, 0,95 = %5 indirim).
    """
    season_months = models.CharField(
        max_length=80, default=DEFAULT_SEASON_MONTHS, db_column="mevsim_aylari", verbose_name="Mevsim ayları",
        help_text="Ocak'tan Aralık'a 12 ayın mevsimi, virgülle: kis, gecis ya da yaz (v93; eski mevsim_aylari tablosu).")
    low_limit = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.50"), db_column="dusuk_doluluk_ust_siniri",
                                    validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("1"))],
                                    verbose_name="Düşük doluluk üst sınırı",
                                    help_text="Bu oranın altındaki doluluk 'düşük' sayılır (0,50 = %50).")
    low_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.95"), db_column="dusuk_doluluk_carpani",
                                     validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("2"))],
                                     verbose_name="Düşük dolulukta çarpan", help_text="0,95 = %5 indirim.")
    mid_limit = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.70"), db_column="orta_doluluk_ust_siniri",
                                    validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("1"))],
                                    verbose_name="Orta doluluk üst sınırı")
    mid_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.05"), db_column="orta_doluluk_carpani",
                                     validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("2"))],
                                     verbose_name="Orta dolulukta çarpan", help_text="1,05 = %5 artış.")
    high_limit = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.90"), db_column="yuksek_doluluk_ust_siniri",
                                     validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("1"))],
                                     verbose_name="Yüksek doluluk üst sınırı")
    high_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.15"), db_column="yuksek_doluluk_carpani",
                                      validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("2"))],
                                      verbose_name="Yüksek dolulukta çarpan")
    full_factor = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.30"), db_column="dolmak_uzere_carpani",
                                      validators=[MinValueValidator(Decimal("0.50")), MaxValueValidator(Decimal("2"))],
                                      verbose_name="Otel dolmak üzereyken çarpan",
                                      help_text="Yüksek doluluk üst sınırı ve üstünde (ör. %90–100).")
    early_days = models.PositiveSmallIntegerField(default=30, db_column="erken_rezervasyon_gun",
                                                  validators=[MinValueValidator(1)],
                                                  verbose_name="Erken rezervasyon: en az kaç gün önce")
    early_discount = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.15"), db_column="erken_rezervasyon_indirimi",
                                         validators=RATE, verbose_name="Erken rezervasyon indirimi", help_text="0,15 = %15.")
    stay_1_nights = models.PositiveSmallIntegerField(default=3, db_column="sure_1_gece", validators=[MinValueValidator(2)],
                                                     verbose_name="Süre indirimi 1: en az gece")
    stay_1_discount = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.05"), db_column="sure_1_indirim",
                                          validators=RATE, verbose_name="Süre indirimi 1")
    stay_2_nights = models.PositiveSmallIntegerField(default=6, db_column="sure_2_gece", validators=[MinValueValidator(2)],
                                                     verbose_name="Süre indirimi 2: en az gece")
    stay_2_discount = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.08"), db_column="sure_2_indirim",
                                          validators=RATE, verbose_name="Süre indirimi 2")
    stay_3_nights = models.PositiveSmallIntegerField(default=15, db_column="sure_3_gece", validators=[MinValueValidator(2)],
                                                     verbose_name="Süre indirimi 3: en az gece")
    stay_3_discount = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.12"), db_column="sure_3_indirim",
                                          validators=RATE, verbose_name="Süre indirimi 3")
    # Alt sınır (fiyat motoru): normalde fiyat tam maliyetin altına inmez; son dakikada boş kalacak odada
    # değişken maliyet × (1 + pay) seviyesine kadar inebilir (oda boş kalmasın, sabit gidere katkı versin).
    last_minute_days = models.PositiveSmallIntegerField(default=7, db_column="son_dakika_gun",
                                                        verbose_name="Son dakika: girişe en çok kaç gün kala",
                                                        help_text="Bu kadar gün ya da daha az kalmışsa son dakika sayılır.")
    last_minute_occupancy = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.50"),
                                                db_column="son_dakika_doluluk",
                                                validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("1"))],
                                                verbose_name="Son dakika: o gecenin doluluğu bunun altındaysa",
                                                help_text="0,50 = %50. Gece bu kadar boşsa fiyat değişken maliyete kadar inebilir.")
    last_minute_discount = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.30"),
                                               db_column="son_dakika_indirim", validators=RATE,
                                               verbose_name="Son dakika: boş otel indirimi",
                                               help_text="0,30 = %30. Son dakika koşulunda (az gün kala, otel boş) fiyat bu "
                                                         "kadar indirilir; alt sınırın altına inmez.")
    last_minute_markup = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("0.20"),
                                             db_column="son_dakika_pay", validators=RATE,
                                             verbose_name="Son dakika: değişken maliyetin üstüne pay",
                                             help_text="0,20 = %20. Son dakika alt sınırı = değişken maliyet × 1,20.")
    updated_at = models.DateTimeField(auto_now=True, db_column="guncellenme_zamani", verbose_name="Son değişiklik")

    class Meta:
        db_table = "fiyat_kurallari"
        verbose_name = "Fiyat kuralları"
        verbose_name_plural = "Fiyat kuralları"

    def clean(self):
        errors = {}
        if self.low_limit is not None and self.mid_limit is not None and self.high_limit is not None:
            if not (self.low_limit < self.mid_limit < self.high_limit):
                errors["mid_limit"] = "Doluluk sınırları küçükten büyüğe olmalı: düşük < orta < yüksek."
        if self.stay_1_nights and self.stay_2_nights and self.stay_3_nights:
            if not (self.stay_1_nights < self.stay_2_nights < self.stay_3_nights):
                errors["stay_2_nights"] = "Süre indirimlerinin gece sayıları küçükten büyüğe olmalı."
        if errors:
            raise ValidationError(errors)

    @classmethod
    def current(cls):
        """Geçerli kurallar (tek satır); tablo boşsa varsayılanlarla oluşturulur."""
        rules = cls.objects.order_by("pk").first()
        return rules if rules is not None else cls.objects.create()

    def bands(self):
        """[(alt, üst ya da None, çarpan, açıklama)] — ekranlarda bandı yazmak için."""
        return [(ZERO, self.low_limit, self.low_factor, "düşük doluluk"),
                (self.low_limit, self.mid_limit, self.mid_factor, "orta doluluk"),
                (self.mid_limit, self.high_limit, self.high_factor, "yüksek doluluk"),
                (self.high_limit, None, self.full_factor, "otel dolmak üzere")]

    def stay_discounts(self):
        """[(en az gece, indirim)] büyükten küçüğe."""
        return [(self.stay_3_nights, self.stay_3_discount), (self.stay_2_nights, self.stay_2_discount),
                (self.stay_1_nights, self.stay_1_discount)]

    @staticmethod
    def _pct(value):
        return f"%{value * 100:.0f}"

    def band_text(self):
        """Ekranlar için: "%0–50 -%5, %50–70 +%5, %70–90 +%15, %90–100 +%30"."""
        return ", ".join(f"%{low * 100:.0f}–{(high if high is not None else 1) * 100:.0f} {index_label(factor)}"
                         for low, high, factor, _ in self.bands())

    def stay_text(self):
        """Ekranlar için: "3+ gece %5, 6+ gece %8, 15+ gece %12"."""
        return ", ".join(f"{nights}+ gece {self._pct(discount)}" for nights, discount in reversed(self.stay_discounts()))

    def __str__(self):
        return "Fiyat kuralları"
