# Sunum senaryosu genişletildi (v68, kullanıcı isteği):
#   Şubat flaş kampanya   20–28 Şubat 2027 (önce 22–25)  endeks 0,07 (önce 0,20) → her rezervasyon "Zarar: satılmamalı"
# Şubat için ölçüm: misafir gelince harcanan, piyasa fiyatının %8–21'i (en düşük Executive Suite 1 kişi %8,3). 0,20 yalnız
# Standart'ı zarara düşürüyordu; 0,07 (%93 indirim) her oda tipini ve kişi sayısını değişken maliyetin altına indirir.
#   Ağustos zirve ayı     1–31 Ağustos 2027 (önce 9–15)  endeks 1,35 → her rezervasyon "Hedefte"
# Ağustos için ölçüm: en zor oda tipinde (Executive Room, 1 kişi) hedefe ulaşmak için gereken endeks 0,92; erken rezervasyon
# (%15) ve uzun konaklama (%12) indirimleri birlikte uygulansa bile 1,23 yeter. 1,35 tüm doğrudan satışları hedefte tutar.

from datetime import date
from decimal import Decimal

from django.db import migrations

SOURCE = "örnek senaryo (sunum)"
CHANGES = (
    # (eski ad, yeni ad, yeni başlangıç, yeni bitiş, yeni endeks, yeni not, eski başlangıç, eski bitiş, eski endeks, eski not)
    ("Şubat flaş kampanya", "Şubat flaş kampanya", date(2027, 2, 20), date(2027, 2, 28), Decimal("0.07"),
     "Sosyal medya flaş kampanyası (%93 indirim), 20–28 Şubat. Fiyat odanın kendi giderinin altında: her satış zarar yazar.",
     date(2027, 2, 22), date(2027, 2, 25), Decimal("0.20"),
     "Sosyal medya flaş kampanyası (%80 indirim). Fiyat odanın kendi giderinin altında: her satış zarar yazar."),
    ("Ağustos zirve haftası", "Ağustos zirve ayı", date(2027, 8, 1), date(2027, 8, 31), Decimal("1.35"),
     "Yaz zirvesi ve yüksek ön satış: Ağustos boyunca fiyat artışı. İndirimler uygulansa bile hedef kârın üstünde satılır.",
     date(2027, 8, 9), date(2027, 8, 15), Decimal("1.35"),
     "Yaz zirvesi ve yüksek ön satış: fiyat artışı. Hedef kârın üstünde satılır."),
)


def forward(apps, schema_editor):
    Event = apps.get_model("dashboard", "Event")
    for old, new, first, last, index, notes, *_ in CHANGES:
        Event.objects.filter(source=SOURCE, name=old).update(name=new, start_date=first, end_date=last, index=index,
                                                             notes=notes)


def backward(apps, schema_editor):
    Event = apps.get_model("dashboard", "Event")
    for old, new, _first, _last, _index, _notes, first, last, index, notes in CHANGES:
        Event.objects.filter(source=SOURCE, name=new).update(name=old, start_date=first, end_date=last, index=index,
                                                             notes=notes)


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0040_sunum_fiyat_kararlari'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
