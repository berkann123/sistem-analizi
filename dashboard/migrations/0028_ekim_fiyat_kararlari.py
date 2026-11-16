from datetime import date
from decimal import Decimal

from django.db import migrations

# Ekim 2026 için örnek otel fiyat kararları: fiyat takvimi açılışta içinde bulunulan ayı gösterdiği için dört
# durum (hedefte, kârlı, katkı, zarar) Ekim'de de görünsün diye. Kasım örnekleri (0027) aynen durur.
DECISIONS = [
    ("Fashion Prime fuarı yoğun talep fiyatı", date(2026, 10, 20), date(2026, 10, 22), Decimal("1.40"),
     "Fashion Prime fuarı süresince katılımcı ve ziyaretçi talebi güçlü; fiyat temel fiyatın %40 üstüne çekildi."),
    ("Sonbahar flash kampanyası (taslak)", date(2026, 10, 24), date(2026, 10, 25), Decimal("0.10"),
     "Pazarlamanın önerdiği %90 indirimli hafta sonu flash kampanyası taslağı; yayına alınmadan önce maliyete göre "
     "kontrol için takvime girildi."),
    ("Hafta içi son dakika indirimi", date(2026, 10, 26), date(2026, 10, 27), Decimal("0.70"),
     "Bayram öncesi hafta içi talep zayıf; boş kalacak odaları doldurmak için son dakika satışlarına %30 indirim "
     "uygulandı."),
]
SOURCE = "Örnek senaryo: otelin fiyat kararı (gerçek karar değil)"


def add_decisions(apps, schema_editor):
    Event = apps.get_model("dashboard", "Event")
    for name, start, end, index, notes in DECISIONS:
        Event.objects.get_or_create(name=name, start_date=start, defaults={
            "kind": "fiyat_karari", "end_date": end, "index": index, "notes": notes, "source": SOURCE})


def remove_decisions(apps, schema_editor):
    Event = apps.get_model("dashboard", "Event")
    for name, start, *_ in DECISIONS:
        Event.objects.filter(name=name, start_date=start, kind="fiyat_karari").delete()


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0027_otel_fiyat_karari")]
    operations = [migrations.RunPython(add_decisions, remove_decisions)]
