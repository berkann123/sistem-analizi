"""Eksik ilişkiler: tedarikçiler tablosu ve tekstil varlığı -> envanter ürünü bağı.

1. Tedarikçi, ürün kartında serbest metindi (aynı firma farklı yazılabiliyordu). Artık ayrı bir
   tablodur ve ürünler ona yabancı anahtarla bağlanır. Mevcut metinler tabloya taşınır.
2. Tekstil varlıkları, envanterdeki karşılıklarıyla yalnızca aynı adı taşıyarak eşleşiyordu.
   Artık `urun_id` yabancı anahtarı vardır; adı birebir eşleşen kayıtlar otomatik bağlanır.

MySQL yeni kolonu tablonun sonuna ekler. Kolon sırası düzenli kalsın diye her eklemeden sonra
kolon `ALTER TABLE ... MODIFY ... AFTER ...` ile mantıksal yerine alınır.
"""
import django.db.models.deletion
from django.db import migrations, models


def move_supplier_text_to_table(apps, schema_editor):
    db = schema_editor.connection.alias
    Item = apps.get_model("dashboard", "InventoryItem")
    Supplier = apps.get_model("dashboard", "Supplier")
    suppliers = {}  # küçük harfe çevrilmiş ad -> tedarikçi (aynı firmanın farklı yazımları birleşsin)
    for item in Item.objects.using(db).exclude(preferred_supplier__isnull=True).order_by("sku"):
        name = " ".join((item.preferred_supplier or "").split())[:160]
        if not name:
            continue
        key = name.casefold()
        if key not in suppliers:
            suppliers[key] = Supplier.objects.using(db).create(name=name)
        Item.objects.using(db).filter(pk=item.pk).update(supplier_id=suppliers[key].pk)


def link_textiles_to_items(apps, schema_editor):
    db = schema_editor.connection.alias
    Item = apps.get_model("dashboard", "InventoryItem")
    Textile = apps.get_model("dashboard", "TextileAsset")
    for asset in Textile.objects.using(db).filter(item__isnull=True):
        matches = list(Item.objects.using(db).filter(name=asset.name)[:2])
        if len(matches) == 1:  # yalnızca tek ve kesin eşleşme bağlanır; belirsiz olan elle seçilir
            Textile.objects.using(db).filter(pk=asset.pk).update(item_id=matches[0].pk)


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0002_okunabilir_gorunumler"),
    ]

    operations = [
        migrations.CreateModel(
            name="Supplier",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(db_column="tedarikci_adi", max_length=160, unique=True, verbose_name="Tedarikçi adı")),
                ("phone", models.CharField(blank=True, db_column="telefon", max_length=40, verbose_name="Telefon")),
                ("email", models.EmailField(blank=True, db_column="e_posta", max_length=254, verbose_name="E-posta")),
                ("notes", models.CharField(blank=True, db_column="aciklama", max_length=240, verbose_name="Açıklama")),
                ("active", models.BooleanField(db_column="aktif", default=True, verbose_name="Aktif")),
            ],
            options={
                "verbose_name": "Tedarikçi",
                "verbose_name_plural": "Tedarikçiler",
                "db_table": "tedarikciler",
                "ordering": ["name"],
            },
        ),
        # --- ürün -> tedarikçi
        migrations.AddField(
            model_name="inventoryitem",
            name="supplier",
            field=models.ForeignKey(
                blank=True, db_column="tedarikci_id", null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="items", to="dashboard.supplier", verbose_name="Tedarikçi"),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE envanter_urunleri MODIFY COLUMN tedarikci_id bigint NULL AFTER bozulabilir",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(move_supplier_text_to_table, migrations.RunPython.noop),
        migrations.RemoveField(model_name="inventoryitem", name="preferred_supplier"),
        # --- tekstil varlığı -> envanter ürünü
        migrations.AddField(
            model_name="textileasset",
            name="item",
            field=models.ForeignKey(
                blank=True, db_column="urun_id", null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="textile_assets", to="dashboard.inventoryitem",
                verbose_name="Envanter ürünü (stok kartı)"),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE tekstil_varliklari MODIFY COLUMN urun_id bigint NULL AFTER tekstil_adi",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(link_textiles_to_items, migrations.RunPython.noop),
    ]
