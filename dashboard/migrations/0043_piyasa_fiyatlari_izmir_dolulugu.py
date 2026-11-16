# Piyasa (temel) fiyatları yeni maliyete göre ayarlandı (v72, kullanıcı kararı).
#
# v71'de doluluk Bakanlığın İzmir verisine çekildi: normal doluluk %70 → %49,7. Sabit gider daha az geceye bölündüğü için
# tam maliyet ~%36 arttı ve kışın piyasa fiyatının üstüne çıktı (fiyat çoğu gece alt sınırda, büyük odalar piyasanın
# üstünde). v65'teki kural yeniden kuruldu: her oda tipinde GEÇİŞ mevsimi piyasa fiyatı = maliyetten hedef fiyat
# (Nisan 2027 tam maliyeti × (1 + hedef marj), 2 kişi). Kış ve yaz fiyatı aynı oranla ölçeklendi (mevsim farkı korunur).
# 50 ₺'ye yuvarlandı. TL, KDV hariç, 2 kişi kahvaltı dahil. Ek kişi ücreti değişmedi (kahvaltı maliyeti dolulukla değişmez).

from decimal import Decimal

from django.db import migrations

NEW = {
    "STD": ("6250", "6950", "8050"), "SUP": ("6850", "7600", "8650"), "JRS": ("8400", "9150", "10700"),
    "LUX": ("9250", "10400", "11850"), "DLX": ("10400", "11550", "13400"), "EXR": ("12600", "13800", "16150"),
    "EXS": ("13600", "15100", "17700"),
}
OLD = {
    "STD": ("4694.76", "5247.09", "6075.58"), "SUP": ("5247.09", "5799.41", "6627.90"),
    "JRS": ("6075.58", "6627.90", "7732.55"), "LUX": ("6904.06", "7732.55", "8837.20"),
    "DLX": ("7732.55", "8561.04", "9941.85"), "EXR": ("8837.20", "9665.69", "11322.66"),
    "EXS": ("9941.85", "11046.50", "12979.64"),
}
SEASONS = ("kis", "gecis", "yaz")


def apply(values):
    def run(apps, schema_editor):
        BaseRate = apps.get_model("dashboard", "BaseRate")
        for code, prices in values.items():
            for season, price in zip(SEASONS, prices):
                BaseRate.objects.filter(room_type__code=code, season=season).update(price=Decimal(price))
    return run


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0042_kar_korumasi'),
    ]

    operations = [
        migrations.RunPython(apply(NEW), apply(OLD)),
    ]
