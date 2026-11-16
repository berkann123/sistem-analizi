# Tablo sadeleştirme (v93, kullanıcı kararı): 23 iş tablosu → 16. Sistem aynı çalışır; yalnız veri yeri değişir.
#
#   temel_fiyatlar           → oda_tipleri.kis_fiyati / gecis_fiyati / yaz_fiyati
#   envanter_kategorileri    → envanter_urunleri.kategori (sabit liste; gider merkezi koddaki eşlemeden)
#   tekstil_varliklari       → envanter_urunleri.tekstil_omru_oda_gece / tekstil_hurda_degeri / tekstil_oda_basi_set
#   kahvalti_bufesi_urunleri + oda_paketi → standart_tuketim (reçete; esas: kahvalti / oda_gecesi / kisi_gecesi)
#   hammadde_fiyat_endeksi   → oranlar (eski vergi_oranlari; tür "hammadde", geçerlilik yılın 1 Ocak'ı)
#   mevsim_aylari            → fiyat_kurallari.mevsim_aylari (12 kod, virgülle)
#   donem_maliyetleri        → donem_kapanislari.maliyetler (JSON)
#   kahvalti_bufesi_gorunumu (veritabanı görünümü) silinir.
# Geri dönüş: veritabanı yedeği `_yedek/pasaport_otel_v93_oncesi.sql`.

from datetime import date
from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

DEFAULT_SEASONS = "kis,kis,kis,gecis,gecis,yaz,yaz,yaz,yaz,gecis,gecis,kis"
CATEGORY_CODES = {"Yiyecek": "yiyecek", "İçecek": "icecek", "Restoran malzemeleri": "restoran", "Buklet": "buklet",
                  "Tekstil": "tekstil", "Temizlik malzemeleri": "temizlik"}
CENTER_CODES = {"mutfak": "yiyecek", "bar": "icecek", "restoran": "restoran", "kat_hizmetleri": "temizlik", "diger": "temizlik"}
SEASON_FIELDS = {"kis": "winter_rate", "gecis": "transition_rate", "yaz": "summer_rate"}


def forward(apps, schema_editor):
    RoomType = apps.get_model("dashboard", "RoomType")
    BaseRate = apps.get_model("dashboard", "BaseRate")
    InventoryItem = apps.get_model("dashboard", "InventoryItem")
    TextileAsset = apps.get_model("dashboard", "TextileAsset")
    Breakfast = apps.get_model("dashboard", "BreakfastBuffetItem")
    Package = apps.get_model("dashboard", "RoomPackageItem")
    Recipe = apps.get_model("dashboard", "ConsumptionRecipe")
    MaterialPriceIndex = apps.get_model("dashboard", "MaterialPriceIndex")
    TaxRate = apps.get_model("dashboard", "TaxRate")
    SeasonMonth = apps.get_model("dashboard", "SeasonMonth")
    PricingRules = apps.get_model("dashboard", "PricingRules")
    ClosedPeriod = apps.get_model("dashboard", "ClosedPeriod")
    ClosedPeriodCost = apps.get_model("dashboard", "ClosedPeriodCost")

    for rate in BaseRate.objects.all():
        field = SEASON_FIELDS.get(rate.season)
        if field:
            RoomType.objects.filter(pk=rate.room_type_id).update(**{field: rate.price})

    for item in InventoryItem.objects.select_related("category"):
        item.category_code = CATEGORY_CODES.get(item.category.name) or CENTER_CODES.get(item.category.cost_center, "temizlik")
        item.save(update_fields=["category_code"])

    textile_basis = {}
    for asset in TextileAsset.objects.all():
        InventoryItem.objects.filter(pk=asset.item_id).update(
            textile_life=asset.useful_room_nights, textile_salvage_value=asset.salvage_value,
            textile_sets_per_room=asset.sets_per_room)
        textile_basis[asset.pk] = (asset.item_id, asset.usage_basis, asset.active)

    for row in Breakfast.objects.all():
        Recipe.objects.create(item_id=row.item_id, basis="kahvalti", guest_count=None, quantity=row.quantity_per_guest,
                              waste_rate=row.waste_rate, notes=row.notes, active=row.active)
    for row in Package.objects.all():
        if row.item_id:
            item_id, basis, active = row.item_id, row.usage_basis, row.active
        else:
            item_id, basis, asset_active = textile_basis[row.textile_asset_id]
            active = row.active and asset_active
        Recipe.objects.create(item_id=item_id, basis=basis, guest_count=row.guest_count,
                              quantity=row.quantity_per_room_night, waste_rate=row.waste_rate, notes=row.notes, active=active)

    for index in MaterialPriceIndex.objects.all():
        TaxRate.objects.update_or_create(kind="hammadde", valid_from=date(index.year, 1, 1),
                                         defaults={"rate": index.factor, "notes": index.notes})

    months = dict(SeasonMonth.objects.values_list("month", "season"))
    default = DEFAULT_SEASONS.split(",")
    codes = ",".join(months.get(month, default[month - 1]) for month in range(1, 13))
    rules = PricingRules.objects.first()
    if rules is None:
        rules = PricingRules.objects.create()
    rules.season_months = codes
    rules.save(update_fields=["season_months"])

    for period in ClosedPeriod.objects.all():
        period.costs_data = [{"room_type_id": cost.room_type_id, "guests": cost.guests, "variable": str(cost.variable),
                              "shared": str(cost.shared)}
                             for cost in ClosedPeriodCost.objects.filter(period=period).order_by("room_type_id", "guests")]
        period.save(update_fields=["costs_data"])


RATE = [django.core.validators.MinValueValidator(Decimal("0")), django.core.validators.MaxValueValidator(Decimal("0.9999"))]
NON_NEGATIVE = [django.core.validators.MinValueValidator(Decimal("0"))]


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0048_turizm_ozel_gunleri_2027'),
    ]

    operations = [
        migrations.RunSQL("DROP VIEW IF EXISTS kahvalti_bufesi_gorunumu", migrations.RunSQL.noop),

        # 1) Yeni alanlar
        migrations.AddField('roomtype', 'winter_rate', models.DecimalField(
            blank=True, db_column='kis_fiyati', decimal_places=2, max_digits=12, null=True, validators=NON_NEGATIVE,
            verbose_name='Kış piyasa fiyatı (TL)')),
        migrations.AddField('roomtype', 'transition_rate', models.DecimalField(
            blank=True, db_column='gecis_fiyati', decimal_places=2, max_digits=12, null=True, validators=NON_NEGATIVE,
            verbose_name='Geçiş piyasa fiyatı (TL)')),
        migrations.AddField('roomtype', 'summer_rate', models.DecimalField(
            blank=True, db_column='yaz_fiyati', decimal_places=2, max_digits=12, null=True, validators=NON_NEGATIVE,
            verbose_name='Yaz piyasa fiyatı (TL)')),
        migrations.AddField('inventoryitem', 'category_code', models.CharField(db_column='kategori', max_length=20, null=True)),
        migrations.AddField('inventoryitem', 'textile_life', models.PositiveIntegerField(
            blank=True, db_column='tekstil_omru_oda_gece', null=True,
            validators=[django.core.validators.MinValueValidator(1)], verbose_name='Tekstil ömrü (oda-gece)',
            help_text='Bir setin tahmini toplam oda-gece kullanım ömrü. Doluysa ürün tekstil sayılır: tüketilmez, yıpranır.')),
        migrations.AddField('inventoryitem', 'textile_salvage_value', models.DecimalField(
            db_column='tekstil_hurda_degeri', decimal_places=2, default=0, max_digits=14, validators=NON_NEGATIVE,
            verbose_name='Tekstil hurda değeri', help_text='Ömrü dolan setin kalan değeri (KDV hariç).')),
        migrations.AddField('inventoryitem', 'textile_sets_per_room', models.DecimalField(
            db_column='tekstil_oda_basi_set', decimal_places=3, default=1, max_digits=8, validators=NON_NEGATIVE,
            verbose_name='Oda başı set sayısı')),
        migrations.CreateModel(
            name='ConsumptionRecipe',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('basis', models.CharField(choices=[('kahvalti', 'Kahvaltı büfesi (kişi başı)'), ('oda_gecesi', 'Oda başına / gece'),
                                                    ('kisi_gecesi', 'Kişi başına / gece')], db_column='esas', max_length=20,
                                           verbose_name='Esas')),
                ('guest_count', models.PositiveSmallIntegerField(
                    blank=True, db_column='misafir_sayisi', null=True, validators=[django.core.validators.MinValueValidator(1)],
                    verbose_name='Misafir sayısı', help_text='Oda paketinde yatak düzeni; kahvaltı büfesinde boş.')),
                ('quantity', models.DecimalField(db_column='miktar', decimal_places=4, max_digits=12, validators=NON_NEGATIVE,
                                                 verbose_name='Miktar')),
                ('waste_rate', models.DecimalField(db_column='fire_orani', decimal_places=4, default=0, max_digits=5,
                                                   validators=RATE, verbose_name='Fire oranı')),
                ('notes', models.CharField(blank=True, db_column='aciklama', max_length=240, verbose_name='Açıklama')),
                ('active', models.BooleanField(db_column='aktif', default=True, verbose_name='Aktif')),
                ('item', models.ForeignKey(db_column='urun_id', on_delete=django.db.models.deletion.PROTECT,
                                           to='dashboard.inventoryitem', verbose_name='Envanter ürünü (kod ve ad)')),
            ],
            options={
                'db_table': 'standart_tuketim', 'ordering': ['basis', 'guest_count', 'item__name'],
                'verbose_name': 'Standart tüketim (reçete)', 'verbose_name_plural': 'Standart tüketim (reçete)',
                'constraints': [models.UniqueConstraint(fields=('basis', 'guest_count', 'item'), name='uq_recete_esas_kisi_urun')],
            },
        ),
        migrations.AddField('pricingrules', 'season_months', models.CharField(
            db_column='mevsim_aylari', default=DEFAULT_SEASONS, max_length=80, verbose_name='Mevsim ayları',
            help_text="Ocak'tan Aralık'a 12 ayın mevsimi, virgülle: kis, gecis ya da yaz (v93; eski mevsim_aylari tablosu).")),
        migrations.AddField('closedperiod', 'costs_data', models.JSONField(
            blank=True, db_column='maliyetler', default=list, verbose_name='Oda-gece maliyetleri (oda tipi × kişi)')),
        migrations.AlterField('taxrate', 'kind', models.CharField(
            choices=[('kdv', 'KDV'), ('konaklama', 'Konaklama vergisi'), ('hammadde', 'Hammadde fiyat endeksi')],
            db_column='vergi', max_length=10, verbose_name='Vergi')),
        migrations.AlterField('taxrate', 'rate', models.DecimalField(
            db_column='oran', decimal_places=4, max_digits=6,
            validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('5'))],
            verbose_name='Oran',
            help_text="Vergide 0,10 = %10. Hammadde endeksinde o yılın fiyat düzeyi: 0,75 = bugünkünden %25 ucuz "
                      "(geçerlilik başlangıcı yılın 1 Ocak'ı).")),

        # 2) Veri taşıma
        migrations.RunPython(forward, migrations.RunPython.noop),

        # 3) Kategori alanı son hâline, eski tablolar silinir
        migrations.RemoveField('inventoryitem', 'category'),
        migrations.RenameField('inventoryitem', 'category_code', 'category'),
        migrations.AlterField('inventoryitem', 'category', models.CharField(
            choices=[('yiyecek', 'Yiyecek'), ('icecek', 'İçecek'), ('restoran', 'Restoran malzemeleri'), ('buklet', 'Buklet'),
                     ('tekstil', 'Tekstil'), ('temizlik', 'Temizlik malzemeleri')],
            db_column='kategori', max_length=20, verbose_name='Kategori')),
        migrations.DeleteModel('RoomPackageItem'),
        migrations.DeleteModel('TextileAsset'),
        migrations.DeleteModel('BreakfastBuffetItem'),
        migrations.DeleteModel('BaseRate'),
        migrations.DeleteModel('MaterialPriceIndex'),
        migrations.DeleteModel('SeasonMonth'),
        migrations.DeleteModel('ClosedPeriodCost'),
        migrations.DeleteModel('InventoryCategory'),
        migrations.AlterModelTable('taxrate', 'oranlar'),
        migrations.AlterModelOptions('taxrate', {
            'ordering': ['kind', '-valid_from'], 'verbose_name': 'Oran (vergi, hammadde endeksi)',
            'verbose_name_plural': 'Oranlar (vergi, hammadde endeksi)'}),

        # 4) Kahvaltı büfesi ve oda paketi: aynı tablonun Admin ekranları (ayrı tablo değil)
        migrations.CreateModel(name='BreakfastBuffetItem', fields=[], options={
            'proxy': True, 'verbose_name': 'Kahvaltı büfesi ürünü', 'verbose_name_plural': 'Kahvaltı büfesi',
            'indexes': [], 'constraints': []}, bases=('dashboard.consumptionrecipe',)),
        migrations.CreateModel(name='RoomPackageItem', fields=[], options={
            'proxy': True, 'verbose_name': 'Oda paketi kalemi', 'verbose_name_plural': 'Oda paketi',
            'indexes': [], 'constraints': []}, bases=('dashboard.consumptionrecipe',)),
    ]
