"""Çamaşırhane gider merkezi kaldırılır; adlardaki "(örnek)" / "(demo)" ekleri silinir.

1. Tekstil kategorisi çamaşırhaneye bağlıydı. Otelde ayrı bir çamaşırhane gider merkezi
   izlenmiyor; tekstil kat hizmetlerinin sorumluluğunda. Çamaşırhaneye bağlı kategoriler
   kat hizmetlerine alınır ve seçenek listeden çıkarılır.
2. Gider kalemi ve ürün adlarının sonundaki "(örnek)", "(demo)", "(örnek ürün)" ekleri temizlenir.
   Verinin model verisi olduğu adın içinde değil, sunumdaki varsayımlar tablosunda belirtilir.
"""
import re

from django.db import migrations, models

SUFFIX = re.compile(r"\s*\((?:örnek|demo)[^)]*\)\s*$", re.IGNORECASE)


def move_laundry_to_housekeeping(apps, schema_editor):
    Category = apps.get_model("dashboard", "InventoryCategory")
    Category.objects.using(schema_editor.connection.alias).filter(cost_center="camasirhane").update(
        cost_center="kat_hizmetleri")


def strip_example_suffixes(apps, schema_editor):
    db = schema_editor.connection.alias
    ExpenseCategory = apps.get_model("dashboard", "MonthlyExpenseCategory")
    Item = apps.get_model("dashboard", "InventoryItem")

    # Gider kalemi adı benzersizdir: temiz ad başka bir kalemde kullanılıyorsa o kalem atlanır.
    taken = set(ExpenseCategory.objects.using(db).values_list("name", flat=True))
    for category in ExpenseCategory.objects.using(db).order_by("pk"):
        clean = SUFFIX.sub("", category.name).strip()
        if clean and clean != category.name and clean not in taken:
            taken.discard(category.name)
            taken.add(clean)
            ExpenseCategory.objects.using(db).filter(pk=category.pk).update(name=clean)

    for item in Item.objects.using(db).order_by("pk"):
        clean = SUFFIX.sub("", item.name).strip()
        if clean and clean != item.name:
            Item.objects.using(db).filter(pk=item.pk).update(name=clean)


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0008_gider_kaydi_ay_basina_tek"),
    ]

    operations = [
        migrations.RunPython(move_laundry_to_housekeeping, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="inventorycategory",
            name="cost_center",
            field=models.CharField(
                choices=[("mutfak", "Mutfak"), ("bar", "Bar"), ("kat_hizmetleri", "Kat hizmetleri"), ("diger", "Diğer")],
                db_column="gider_merkezi", max_length=30),
        ),
        migrations.RunPython(strip_example_suffixes, migrations.RunPython.noop),
    ]
