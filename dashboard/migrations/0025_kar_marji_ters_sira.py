from decimal import Decimal

from django.db import migrations

# Kullanıcı kararı (16.10.2026): hedef kâr marjı en ucuz odada en yüksek. Standart Oda %80'den başlar,
# her üst oda tipinde %3 azalır: 80, 77, 74, 71, 68, 65, 62.
MARKUPS = {"STD": "0.80", "SUP": "0.77", "JRS": "0.74", "LUX": "0.71", "DLX": "0.68", "EXR": "0.65", "EXS": "0.62"}


def set_markups(apps, schema_editor):
    RoomType = apps.get_model("dashboard", "RoomType")
    for code, markup in MARKUPS.items():
        RoomType.objects.filter(code=code).update(target_markup=Decimal(markup))


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0024_oda_sirasi_kara_manzara"),
    ]

    operations = [
        migrations.RunPython(set_markups, migrations.RunPython.noop),
    ]
