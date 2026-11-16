# Kâr koruması (v70, kullanıcı kararı): büyük ve lüks odalar hiçbir gün zararına ya da kârsız satılmaz.
#   İlk 4 kategori (Standart, Superior, Junior Suite, Luxury): koruma yok. Doluluk için başabaş, katkı, hatta kampanyada
#   zarar görebilir.
#   Deluxe, Executive Oda, Executive Suite: asgari kâr marjı %5. Otele kalan tutar (indirim ve komisyondan sonra) her
#   zaman tam maliyet + %5'in üstünde; son dakika indirimi ve otel kararları da bunu aşamaz.

import django.core.validators
from decimal import Decimal
from django.db import migrations, models

PROTECTED = {"DLX": Decimal("0.05"), "EXR": Decimal("0.05"), "EXS": Decimal("0.05")}


def protect(apps, schema_editor):
    RoomType = apps.get_model("dashboard", "RoomType")
    for code, markup in PROTECTED.items():
        RoomType.objects.filter(code=code).update(min_markup=markup)


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0041_subat_zarar_agustos_hedef'),
    ]

    operations = [
        migrations.AddField(
            model_name='roomtype',
            name='min_markup',
            field=models.DecimalField(db_column='asgari_kar_marji', decimal_places=4, default=Decimal('0'), help_text="0'dan büyükse oda tipi hiçbir gün kârsız satılmaz: gece fiyatı ve konaklamanın otele kalan tutarı (indirim ve kanal komisyonundan sonra) tam maliyet × (1 + bu oran) altına inmez; son dakika indirimi ve otel kararları da bu sınırı aşamaz. 0 = koruma yok (oda başabaş ya da katkı için satılabilir). 0,05 = maliyet + %5.", max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('1'))], verbose_name='Asgari kâr marjı (kâr koruması)'),
        ),
        migrations.RunPython(protect, migrations.RunPython.noop),
    ]
