# Hedef kâr marjları fiyat motoruna göre ayarlandı (v65, kullanıcı kararı).
#
# Eski marjlarla (%62–80, migration 0025) maliyetten gelen hedef fiyat her oda tipinde piyasa fiyatının üstündeydi; karma
# çapada (hedef ile piyasanın düşüğü) fiyat hep piyasadan geliyordu. Yeni marj: her oda tipinde hedef fiyat GEÇİŞ mevsimi
# piyasa fiyatına denk (Nisan 2027 tam maliyetiyle, 2 kişi): kışın çapa piyasa, yazın maliyet. Ölçüm (2027 takvimi):
# gecelerin %53'ünde fiyatı maliyet belirler; ortalama gece fiyatı yaklaşık %4,6 düşer.

from decimal import Decimal

from django.db import migrations

NEW = {"STD": "0.50", "SUP": "0.42", "JRS": "0.39", "LUX": "0.39", "DLX": "0.41", "EXR": "0.26", "EXS": "0.27"}
OLD = {"STD": "0.80", "SUP": "0.77", "JRS": "0.74", "LUX": "0.71", "DLX": "0.68", "EXR": "0.65", "EXS": "0.62"}


def apply(values):
    def run(apps, schema_editor):
        RoomType = apps.get_model("dashboard", "RoomType")
        for code, markup in values.items():
            RoomType.objects.filter(code=code).update(target_markup=Decimal(markup))
    return run


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0037_fiyat_motoru_alt_sinir'),
    ]

    operations = [
        migrations.RunPython(apply(NEW), apply(OLD)),
    ]
