# Turizm ve konaklama odaklı özel günler 2027 (v78, kullanıcı isteği; v77'deki 2025–2026 kurallarıyla aynı endeksler).
#
# 2027 takvimi (gece = o tarihte otelde kalınan gece):
#   1 Ocak Cuma → 1–2 Ocak uzun hafta sonu 1,25 · 14 Şubat Pazar → 13–14 Şubat Sevgililer Günü 1,55
#   · Ramazan Bayramı 8–11 Mart (arife dahil) 1,30 · 23 Nisan Cuma → 22–24 Nisan 1,15 · 1 Mayıs Cumartesi 1,10
#   · Anneler Günü 9 Mayıs Pazar → 8 Mayıs gecesi 1,10 · Kurban Bayramı 15–19 Mayıs (arife dahil) 1,40; 19 Mayıs
#   Çarşamba bayramın içinde · 15 Temmuz Perşembe → Cuma köprüsüyle 15–17 Temmuz 1,10 · 30 Ağustos Pazartesi → 28–29
#   Ağustos 1,10 · Cumhuriyet Bayramı 28 (yarım gün)–29 Ekim Cuma → 28–30 Ekim 1,15 · 31 Aralık Cuma Yılbaşı gecesi 1,80.
# Otel kararı olan gecede karar geçerlidir (ör. "Ağustos zirve ayı" 1,35 tüm Ağustos'u belirler).

from datetime import date
from decimal import Decimal

from django.db import migrations

SOURCE = "Turizm takvimi 2027 (v78)"

UPDATES = (   # (eski ad, eski ilk gece, yeni ad, ilk gece, son gece, endeks)
    ("Yılbaşı uzun hafta sonu", date(2027, 1, 1), "Yılbaşı uzun hafta sonu", date(2027, 1, 1), date(2027, 1, 2), "1.25"),
    ("Ramazan Bayramı", date(2027, 3, 8), "Ramazan Bayramı", date(2027, 3, 8), date(2027, 3, 11), "1.30"),
    ("23 Nisan (uzun hafta sonu)", date(2027, 4, 22), "23 Nisan (uzun hafta sonu)", date(2027, 4, 22), date(2027, 4, 24), "1.15"),
    ("1 Mayıs", date(2027, 4, 30), "1 Mayıs (hafta sonu)", date(2027, 4, 30), date(2027, 5, 1), "1.10"),
    ("Kurban Bayramı", date(2027, 5, 15), "Kurban Bayramı", date(2027, 5, 15), date(2027, 5, 19), "1.40"),
    ("15 Temmuz", date(2027, 7, 14), "15 Temmuz (köprü ile uzun hafta sonu)", date(2027, 7, 15), date(2027, 7, 17), "1.10"),
    ("30 Ağustos Zafer Bayramı (uzun hafta sonu)", date(2027, 8, 28), "30 Ağustos Zafer Bayramı (uzun hafta sonu)",
     date(2027, 8, 28), date(2027, 8, 29), "1.10"),
    ("Cumhuriyet Bayramı (uzun hafta sonu)", date(2027, 10, 28), "Cumhuriyet Bayramı (uzun hafta sonu)",
     date(2027, 10, 28), date(2027, 10, 30), "1.15"),
    ("Yılbaşı gecesi", date(2027, 12, 31), "Yılbaşı gecesi", date(2027, 12, 31), date(2027, 12, 31), "1.80"),
)
NEW = (
    ("Sevgililer Günü", "ozel_gun", date(2027, 2, 13), date(2027, 2, 14), "1.55",
     "14 Şubat Pazar: Cumartesi gecesi zirve, romantik paketler"),
    ("Anneler Günü", "ozel_gun", date(2027, 5, 8), date(2027, 5, 8), "1.10",
     "9 Mayıs Pazar; hafta sonu kahvaltı/brunch ve kısa konaklama artışı"),
    ("19 Mayıs Atatürk'ü Anma, Gençlik ve Spor Bayramı", "milli_bayram", date(2027, 5, 19), date(2027, 5, 19), "1.10",
     "Çarşamba; Kurban Bayramı'nın içinde (o gece bayram endeksi geçerli)"),
)


def forward(apps, schema_editor):
    Event = apps.get_model("dashboard", "Event")
    for old_name, old_start, name, first, last, index in UPDATES:
        Event.objects.filter(name=old_name, start_date=old_start).exclude(kind="fiyat_karari").update(
            name=name, start_date=first, end_date=last, index=Decimal(index))
    for name, kind, first, last, index, notes in NEW:
        Event.objects.update_or_create(name=name, start_date=first, defaults={
            "kind": kind, "end_date": last, "index": Decimal(index), "notes": notes, "source": SOURCE, "published": True})


def backward(apps, schema_editor):
    apps.get_model("dashboard", "Event").objects.filter(source=SOURCE).delete()
    # Endeks güncellemeleri geri alınmaz (veritabanı yedeği: _yedek/pasaport_otel_v78_oncesi.sql).


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0047_turizm_ozel_gunleri'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
