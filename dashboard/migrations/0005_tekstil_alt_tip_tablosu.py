"""Tekstil tablosu, envanter ürününün temiz bir ALT TİP tablosuna dönüştürülür.

Önce: tekstil_varliklari kendi adını (tekstil_adi) ve kendi maliyetini (set_alim_maliyeti) tutuyor,
      stok kartına bağlantısı isteğe bağlıydı. Aynı bilgi iki tabloda duruyordu.
Sonra: her kayıt bir stok kartına bire bir bağlıdır; ad ve maliyet stok kartından okunur.
       Tabloda yalnızca yıpranma bilgileri kalır (hurda değeri, kullanım ömrü, set sayısı, tüketim esası).

Stok kartı olmayan tekstil kayıtları silinmez: her biri için adı ve maliyeti korunarak bir stok kartı açılır.
"""
import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


def give_every_textile_a_stock_card(apps, schema_editor):
    db = schema_editor.connection.alias
    Item = apps.get_model("dashboard", "InventoryItem")
    Textile = apps.get_model("dashboard", "TextileAsset")
    Category = apps.get_model("dashboard", "InventoryCategory")
    Unit = apps.get_model("dashboard", "Unit")

    existing_codes = set(Item.objects.using(db).values_list("sku", flat=True))
    numbers = [int(code[4:]) for code in existing_codes if code.startswith("TXT-") and code[4:].isdigit()]
    next_number = max(numbers, default=0) + 1

    linked_items = set()
    for asset in Textile.objects.using(db).order_by("pk"):
        if asset.item_id and asset.item_id not in linked_items:
            linked_items.add(asset.item_id)
            continue
        # Stok kartı yok (ya da aynı karta ikinci kayıt bağlanmış): bu kayıt için yeni stok kartı açılır.
        category, _ = Category.objects.using(db).get_or_create(name="Tekstil", defaults={"cost_center": "camasirhane"})
        unit, _ = Unit.objects.using(db).get_or_create(code="adet", defaults={"name": "Adet"})
        while f"TXT-{next_number:03d}" in existing_codes:
            next_number += 1
        code = f"TXT-{next_number:03d}"
        existing_codes.add(code)
        item = Item.objects.using(db).create(
            sku=code, name=asset.name, category=category, unit=unit, item_type="Demirbaş",
            # Hareketi olmayan üründe ortalama maliyet elle verilen değerde kalır; böylece
            # bu tekstilin oda maliyetine yansıyan payı değişmez.
            average_unit_cost=asset.set_purchase_cost, active=asset.active,
        )
        Textile.objects.using(db).filter(pk=asset.pk).update(item_id=item.pk)
        linked_items.add(item.pk)


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0004_gorunumleri_kaldir"),
    ]

    operations = [
        migrations.RunPython(give_every_textile_a_stock_card, migrations.RunPython.noop),
        # İlişki zorunlu ve bire bir olur: her tekstil ürününe en fazla bir yıpranma kaydı.
        migrations.AlterField(
            model_name="textileasset",
            name="item",
            field=models.OneToOneField(
                db_column="urun_id", on_delete=django.db.models.deletion.PROTECT, related_name="textile",
                to="dashboard.inventoryitem", verbose_name="Envanter ürünü (stok kartı)"),
        ),
        # Stok kartında zaten bulunan bilgilerin kopyaları kaldırılır.
        migrations.RemoveField(model_name="textileasset", name="name"),
        migrations.RemoveField(model_name="textileasset", name="set_purchase_cost"),
        migrations.AlterModelOptions(
            name="textileasset",
            options={"ordering": ["item__name"], "verbose_name": "Tekstil yıpranma kaydı",
                     "verbose_name_plural": "Tekstil yıpranma kayıtları"},
        ),
        migrations.AlterModelOptions(
            name="roompackageitem",
            options={"ordering": ["item__name", "textile_asset__item__name"], "verbose_name": "Paket bileşeni",
                     "verbose_name_plural": "Paket bileşenleri"},
        ),
        # Aşağıdakiler yalnızca ekrandaki alan adlarını (verbose_name) günceller; tablo yapısı değişmez.
        migrations.AlterField(
            model_name="textileasset", name="active",
            field=models.BooleanField(db_column="aktif", default=True, verbose_name="Aktif"),
        ),
        migrations.AlterField(
            model_name="textileasset", name="notes",
            field=models.CharField(blank=True, db_column="aciklama", max_length=240, verbose_name="Açıklama"),
        ),
        migrations.AlterField(
            model_name="textileasset", name="salvage_value",
            field=models.DecimalField(
                db_column="hurda_degeri", decimal_places=2, default=0,
                help_text="Ömrü dolan setin kalan değeri (KDV hariç).", max_digits=14,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))], verbose_name="Hurda değeri"),
        ),
        migrations.AlterField(
            model_name="textileasset", name="sets_per_room",
            field=models.DecimalField(
                db_column="oda_basi_set_sayisi", decimal_places=3, default=1, max_digits=8,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))], verbose_name="Oda başı set sayısı"),
        ),
        migrations.AlterField(
            model_name="textileasset", name="usage_basis",
            field=models.CharField(
                choices=[("oda_gecesi", "Oda seti / gece"), ("kisi_gecesi", "Kişi seti / gece")],
                db_column="tuketim_esasi", default="oda_gecesi", max_length=20, verbose_name="Tüketim esası"),
        ),
        migrations.AlterField(
            model_name="textileasset", name="useful_room_nights",
            field=models.PositiveIntegerField(
                db_column="tahmini_oda_gecesi_omru", help_text="Bir setin tahmini toplam oda-gece kullanım ömrü",
                validators=[django.core.validators.MinValueValidator(1)], verbose_name="Kullanım ömrü (oda-gece)"),
        ),
    ]
