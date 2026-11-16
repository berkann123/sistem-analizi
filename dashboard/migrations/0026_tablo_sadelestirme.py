"""Tablo sadeleştirme (16.10.2026): 28 tablo -> 22 tablo. Veri kaybı yoktur; her tablonun bilgisi bir alana taşınır.

  gider_gruplari          -> aylik_gider_kategorileri.gider_grubu (sabit liste)
  birimler                -> envanter_urunleri.birim (sabit liste)
  mevsimler               -> mevsim_aylari.mevsim, aylik_otel_giderleri.mevsim, temel_fiyatlar.mevsim (sabit liste)
  kahvalti_bufeleri       -> kaldırıldı: otelin tek büfesi var; büfe = kahvalti_bufesi_urunleri satırları
  oda_paketleri           -> kaldırıldı: paket bütün oda tiplerinde aynı; oda_paketi satırları misafir sayısıyla tutulur
  hafta_gunu_endeksleri   -> etkinlikler (tür 'Her hafta' + hafta günü)
"""
from datetime import date

import django.core.validators
from django.db import migrations, models

GROUPS = {
    "Personel giderleri": "personel", "Enerji giderleri": "enerji", "Bina giderleri": "bina",
    "Bakım ve onarım giderleri": "bakim", "Genel yönetim giderleri": "genel_yonetim",
    "Pazarlama ve satış giderleri": "pazarlama", "Amortisman giderleri": "amortisman", "Diğer giderler": "diger",
}
SEASONS = {"Kış": "kis", "Geçiş": "gecis", "Yaz": "yaz"}
SEASON_CHOICES = [("kis", "Kış"), ("gecis", "Geçiş"), ("yaz", "Yaz")]
UNIT_CHOICES = [("adet", "Adet"), ("demet", "Demet"), ("kg", "Kilogram"), ("lt", "Litre")]
WEEKDAY_NAMES = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

DROP_VIEW = "DROP VIEW IF EXISTS kahvalti_bufesi_gorunumu"
CREATE_VIEW = """
CREATE OR REPLACE VIEW kahvalti_bufesi_gorunumu AS
SELECT
    s.id,
    s.urun_id,
    u.urun_kodu,
    u.urun_adi,
    s.kisi_basi_miktar,
    u.birim,
    u.birim_maliyeti AS birim_maliyeti_tl,
    GREATEST(s.fire_orani, u.fire_orani) AS uygulanan_fire_orani,
    ROUND(s.kisi_basi_miktar * (1 + GREATEST(s.fire_orani, u.fire_orani)) * u.birim_maliyeti, 2) AS kisi_basi_maliyet_tl,
    s.aciklama,
    s.aktif
FROM kahvalti_bufesi_urunleri s
JOIN envanter_urunleri u ON u.id = s.urun_id
"""


def copy_into_fields(apps, schema_editor):
    Category = apps.get_model("dashboard", "MonthlyExpenseCategory")
    Item = apps.get_model("dashboard", "InventoryItem")
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    BaseRate = apps.get_model("dashboard", "BaseRate")
    SeasonMonth = apps.get_model("dashboard", "SeasonMonth")
    BuffetItem = apps.get_model("dashboard", "BreakfastBuffetItem")
    Buffet = apps.get_model("dashboard", "BreakfastBuffet")
    Package = apps.get_model("dashboard", "RoomPackage")
    PackageItem = apps.get_model("dashboard", "RoomPackageItem")
    WeekdayIndex = apps.get_model("dashboard", "WeekdayIndex")
    Event = apps.get_model("dashboard", "Event")

    for category in Category.objects.select_related("group"):
        category.group_code = GROUPS.get(category.group.name, "diger")
        category.save(update_fields=["group_code"])
    for item in Item.objects.select_related("unit"):
        item.unit_code = item.unit.code if item.unit.code in dict(UNIT_CHOICES) else "adet"
        item.save(update_fields=["unit_code"])
    for model in (Expense, BaseRate, SeasonMonth):
        for row in model.objects.filter(season__isnull=False).select_related("season"):
            row.season_code = SEASONS.get(row.season.name, "")
            row.save(update_fields=["season_code"])

    # Kahvaltı büfesi: yalnızca etkin büfenin satırları kalır (otelin tek büfesi).
    active = Buffet.objects.filter(active=True).order_by("name").first()
    if active is not None:
        BuffetItem.objects.exclude(buffet=active).delete()

    # Oda paketi: her misafir sayısı için bir etkin paketin satırları alınır (paketler oda tiplerinde aynı),
    # diğer paketlerin satırları silinir. Önce en küçük oda tipinin paketi seçilir.
    keep = []
    for guests in sorted(set(Package.objects.filter(active=True).values_list("guest_count", flat=True))):
        package = (Package.objects.filter(active=True, guest_count=guests)
                   .order_by("room_type__standard_cost_factor", "room_type__code").first())
        rows = list(PackageItem.objects.filter(package=package))
        for row in rows:
            row.guest_count = guests
            row.save(update_fields=["guest_count"])
        keep += [row.id for row in rows]
    PackageItem.objects.exclude(id__in=keep).delete()

    # Hafta günü endeksleri etkinlik takvimine "her hafta" kuralı olarak taşınır (etkisiz olanlar hariç).
    for row in WeekdayIndex.objects.exclude(index=1):
        Event.objects.get_or_create(
            name=f"{WEEKDAY_NAMES[row.weekday]} geceleri", start_date=date(2025, 1, 1),
            defaults={"kind": "haftalik", "weekday": row.weekday, "end_date": date(2030, 12, 31), "index": row.index,
                      "notes": row.notes or "Hafta günü etkisi (varsayım)."})


COLUMN_ORDER = [
    "ALTER TABLE aylik_gider_kategorileri MODIFY COLUMN gider_grubu varchar(20) NOT NULL AFTER gider_kalemi",
    "ALTER TABLE envanter_urunleri MODIFY COLUMN birim varchar(10) NOT NULL AFTER urun_tipi",
    "ALTER TABLE aylik_otel_giderleri MODIFY COLUMN mevsim varchar(10) NOT NULL AFTER gider_kategorisi_id",
    "ALTER TABLE temel_fiyatlar MODIFY COLUMN mevsim varchar(10) NOT NULL AFTER oda_tipi_id",
    "ALTER TABLE mevsim_aylari MODIFY COLUMN mevsim varchar(10) NOT NULL AFTER ay",
    "ALTER TABLE oda_paketi MODIFY COLUMN misafir_sayisi smallint unsigned NOT NULL AFTER id",
    "ALTER TABLE etkinlikler MODIFY COLUMN hafta_gunu smallint unsigned NULL AFTER tur",
]


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0025_kar_marji_ters_sira"),
    ]

    operations = [
        migrations.RunSQL(DROP_VIEW, migrations.RunSQL.noop),
        # 1) Yeni alanlar (geçici adlarla) ---------------------------------------------------------
        migrations.AddField("monthlyexpensecategory", "group_code", models.CharField(
            max_length=20, default="diger", db_column="gider_grubu", verbose_name="Gider grubu")),
        migrations.AddField("inventoryitem", "unit_code", models.CharField(
            max_length=10, default="adet", db_column="birim", verbose_name="Birim")),
        migrations.AddField("monthlyhotelexpense", "season_code", models.CharField(
            max_length=10, blank=True, default="", db_column="mevsim", verbose_name="Mevsim")),
        migrations.AddField("baserate", "season_code", models.CharField(
            max_length=10, default="", db_column="mevsim", verbose_name="Mevsim")),
        migrations.AddField("seasonmonth", "season_code", models.CharField(
            max_length=10, default="", db_column="mevsim", verbose_name="Mevsim")),
        migrations.AddField("roompackageitem", "guest_count", models.PositiveSmallIntegerField(
            null=True, db_column="misafir_sayisi", verbose_name="Misafir sayısı")),
        migrations.AddField("event", "weekday", models.PositiveSmallIntegerField(
            null=True, blank=True, db_column="hafta_gunu", verbose_name="Hafta günü",
            choices=[(0, "Pazartesi"), (1, "Salı"), (2, "Çarşamba"), (3, "Perşembe"), (4, "Cuma"), (5, "Cumartesi"),
                     (6, "Pazar")],
            help_text="Yalnızca 'Her hafta' türünde: tarih aralığı içinde her hafta bu gece geçerlidir.")),
        migrations.AlterField("event", "kind", models.CharField(
            max_length=20, db_column="tur", verbose_name="Tür",
            choices=[("fuar", "Fuar"), ("milli_bayram", "Milli bayram / resmi tatil"), ("dini_bayram", "Dini bayram"),
                     ("festival", "Festival / kültür-sanat"), ("spor", "Spor"), ("ozel_gun", "Özel gün"),
                     ("haftalik", "Her hafta (hafta günü)")])),
        # 2) Veriyi taşı -------------------------------------------------------------------------------
        migrations.RunPython(copy_into_fields, migrations.RunPython.noop),
        # 3) Eski ilişkileri ve kısıtları kaldır ---------------------------------------------------
        migrations.RemoveConstraint("baserate", "uq_temel_fiyat_oda_mevsim"),
        migrations.RemoveConstraint("breakfastbuffetitem", "uq_kahvalti_bufe_urun"),
        migrations.RemoveConstraint("roompackageitem", "uq_oda_paketi_urun"),
        migrations.RemoveConstraint("roompackageitem", "uq_oda_paketi_tekstil"),
        migrations.RemoveField("monthlyexpensecategory", "group"),
        migrations.RemoveField("inventoryitem", "unit"),
        migrations.RemoveField("monthlyhotelexpense", "season"),
        migrations.RemoveField("baserate", "season"),
        migrations.RemoveField("seasonmonth", "season"),
        migrations.RemoveField("breakfastbuffetitem", "buffet"),
        migrations.RemoveField("roompackageitem", "package"),
        # 4) Yeni alanlara son adlarını ver ------------------------------------------------------------
        migrations.RenameField("monthlyexpensecategory", "group_code", "group"),
        migrations.RenameField("inventoryitem", "unit_code", "unit"),
        migrations.RenameField("monthlyhotelexpense", "season_code", "season"),
        migrations.RenameField("baserate", "season_code", "season"),
        migrations.RenameField("seasonmonth", "season_code", "season"),
        migrations.AlterField("monthlyexpensecategory", "group", models.CharField(
            max_length=20, default="diger", db_column="gider_grubu", verbose_name="Gider grubu",
            choices=[("personel", "Personel giderleri"), ("enerji", "Enerji giderleri"), ("bina", "Bina giderleri"),
                     ("bakim", "Bakım ve onarım giderleri"), ("genel_yonetim", "Genel yönetim giderleri"),
                     ("pazarlama", "Pazarlama ve satış giderleri"), ("amortisman", "Amortisman giderleri"),
                     ("diger", "Diğer giderler")])),
        migrations.AlterField("inventoryitem", "unit", models.CharField(
            max_length=10, default="adet", db_column="birim", verbose_name="Birim", choices=UNIT_CHOICES)),
        migrations.AlterField("monthlyhotelexpense", "season", models.CharField(
            max_length=10, blank=True, default="", db_column="mevsim", verbose_name="Mevsim", choices=SEASON_CHOICES,
            help_text="Boş: kayıt bütün aylarda geçerlidir. Seçilirse yalnızca o mevsimin aylarında (her yıl) geçerlidir; "
                      "ör. elektriğin kış, geçiş ve yaz değerleri için birer kayıt.")),
        migrations.AlterField("baserate", "season", models.CharField(
            max_length=10, db_column="mevsim", verbose_name="Mevsim", choices=SEASON_CHOICES)),
        migrations.AlterField("seasonmonth", "season", models.CharField(
            max_length=10, db_column="mevsim", verbose_name="Mevsim", choices=SEASON_CHOICES)),
        migrations.AlterField("roompackageitem", "guest_count", models.PositiveSmallIntegerField(
            db_column="misafir_sayisi", verbose_name="Misafir sayısı",
            validators=[django.core.validators.MinValueValidator(1)])),
        # 5) Yeni kısıtlar -------------------------------------------------------------------------------
        migrations.AddConstraint("baserate", models.UniqueConstraint(
            fields=("room_type", "season"), name="uq_temel_fiyat_oda_mevsim")),
        migrations.AddConstraint("breakfastbuffetitem", models.UniqueConstraint(
            fields=("item",), name="uq_kahvalti_bufe_urun")),
        migrations.AddConstraint("roompackageitem", models.UniqueConstraint(
            fields=("guest_count", "item"), name="uq_oda_paketi_kisi_urun")),
        migrations.AddConstraint("roompackageitem", models.UniqueConstraint(
            fields=("guest_count", "textile_asset"), name="uq_oda_paketi_kisi_tekstil")),
        # 6) Gereksiz kalan tablolar --------------------------------------------------------------------
        migrations.DeleteModel("ExpenseGroup"),
        migrations.DeleteModel("Unit"),
        migrations.DeleteModel("Season"),
        migrations.DeleteModel("BreakfastBuffet"),
        migrations.DeleteModel("RoomPackage"),
        migrations.DeleteModel("WeekdayIndex"),
        migrations.AlterModelTable("roompackageitem", "oda_paketi"),
        migrations.AlterModelOptions("roompackageitem", {
            "ordering": ["guest_count", "item__name", "textile_asset__item__name"],
            "verbose_name": "Oda paketi kalemi", "verbose_name_plural": "Oda paketi"}),
        migrations.AlterModelOptions("breakfastbuffetitem", {
            "ordering": ["item__name"], "verbose_name": "Kahvaltı büfesi ürünü", "verbose_name_plural": "Kahvaltı büfesi"}),
        migrations.AlterModelOptions("baserate", {
            "ordering": ["room_type__standard_cost_factor", "season"], "verbose_name": "Temel fiyat",
            "verbose_name_plural": "Temel fiyatlar"}),
        migrations.AlterModelOptions("monthlyexpensecategory", {
            "ordering": ["name"], "verbose_name": "Aylık gider kategorisi", "verbose_name_plural": "Aylık gider kategorileri"}),
    ] + [migrations.RunSQL(sql, migrations.RunSQL.noop) for sql in COLUMN_ORDER] + [
        migrations.RunSQL(CREATE_VIEW, DROP_VIEW),
    ]
