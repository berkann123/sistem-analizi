# Sunum senaryosu için 2027 otel fiyat kararları (v67, örnek veri). Rezervasyon ekranında farklı sonuçlar görünsün:
#   Ocak sessiz hafta indirimi  -%35  → fiyat tam maliyetin altında: "Katkı sağlıyor" (zarar değil, oda boş kalmasın)
#   Şubat flaş kampanya          -%80  → fiyat misafir gelince harcananın altında: "Zarar: satılmamalı" (hatalı karar örneği)
#   Ağustos zirve haftası        +%35  → yüksek talep: "Hedefte"
# Otel kararı son sözdür: fiyat motorunun alt sınırı uygulanmaz, zarar yazan kararda ekran uyarı verir.

from datetime import date
from decimal import Decimal

from django.db import migrations

SOURCE = "örnek senaryo (sunum)"
DECISIONS = (
    ("Ocak sessiz hafta indirimi", date(2027, 1, 11), date(2027, 1, 14), Decimal("0.65"),
     "Fuarlar arası boş hafta; doluluğu artırmak için indirim. Fiyat tam maliyetin altında: katkı sağlar, kâr ettirmez."),
    ("Şubat flaş kampanya", date(2027, 2, 22), date(2027, 2, 25), Decimal("0.20"),
     "Sosyal medya flaş kampanyası (%80 indirim). Fiyat odanın kendi giderinin altında: her satış zarar yazar."),
    ("Ağustos zirve haftası", date(2027, 8, 9), date(2027, 8, 15), Decimal("1.35"),
     "Yaz zirvesi ve yüksek ön satış: fiyat artışı. Hedef kârın üstünde satılır."),
)


def forward(apps, schema_editor):
    Event = apps.get_model("dashboard", "Event")
    for name, first, last, index, notes in DECISIONS:
        Event.objects.get_or_create(name=name, start_date=first, defaults={
            "kind": "fiyat_karari", "end_date": last, "index": index, "notes": notes, "source": SOURCE, "published": True})


def backward(apps, schema_editor):
    Event = apps.get_model("dashboard", "Event")
    Event.objects.filter(source=SOURCE, name__in=[name for name, *_ in DECISIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0039_son_dakika_indirimi'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
