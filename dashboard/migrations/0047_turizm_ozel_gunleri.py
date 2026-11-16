# Turizm ve konaklama odaklı özel günler 2025–2026 (v77, kullanıcının verdiği liste).
#
# Endeks, günün konaklama talebine etkisine göre (gece fiyatı = temel fiyat × endeks):
#   Yılbaşı gecesi 1,80 · Sevgililer Günü 1,55–1,60 · Kurban Bayramı 1,40 (yılın en yüksek doluluğu) · Ramazan Bayramı 1,30
#   · Yılbaşı (1 Ocak) / uzun hafta sonu 1,25 · resmi tatil uzun hafta sonu 1,15 · tek günlük resmi tatil, Anneler Günü,
#   15 Temmuz köprüsü 1,05–1,10.
# Gece = o tarihten sonraki sabaha kadar kalınan gece (ör. "31 Aralık" = yılbaşı gecesi). Bu gecelerde otel tam dolu
# (veri `_yedek/v77_ozel_gun_betigi.py` ile dolduruldu).

from datetime import date
from decimal import Decimal

from django.db import migrations

SOURCE = "Turizm takvimi (kullanıcı listesi, v77)"

# (eski ad, eski ilk gece) → (yeni ad, ilk gece, son gece, endeks); geri almak için eski değerler de tutulur.
UPDATES = (
    ("Ramazan Bayramı", date(2025, 3, 29), "Ramazan Bayramı", date(2025, 3, 29), date(2025, 4, 1), "1.30"),
    ("19 Mayıs (uzun hafta sonu)", date(2025, 5, 17), "19 Mayıs (uzun hafta sonu)", date(2025, 5, 17), date(2025, 5, 18), "1.15"),
    ("Kurban Bayramı", date(2025, 6, 5), "Kurban Bayramı", date(2025, 6, 5), date(2025, 6, 9), "1.40"),
    ("Cumhuriyet Bayramı", date(2025, 10, 28), "Cumhuriyet Bayramı", date(2025, 10, 28), date(2025, 10, 29), "1.15"),
    ("Yılbaşı gecesi", date(2025, 12, 31), "Yılbaşı gecesi", date(2025, 12, 31), date(2025, 12, 31), "1.80"),
    ("Ramazan Bayramı", date(2026, 3, 19), "Ramazan Bayramı", date(2026, 3, 19), date(2026, 3, 22), "1.30"),
    ("23 Nisan (uzun hafta sonu)", date(2026, 4, 22), "23 Nisan (uzun hafta sonu)", date(2026, 4, 22), date(2026, 4, 25), "1.15"),
    ("1 Mayıs (uzun hafta sonu)", date(2026, 4, 30), "1 Mayıs (uzun hafta sonu)", date(2026, 4, 30), date(2026, 5, 2), "1.15"),
    ("19 Mayıs", date(2026, 5, 18), "19 Mayıs (köprü ile uzun hafta sonu)", date(2026, 5, 16), date(2026, 5, 18), "1.15"),
    ("Kurban Bayramı", date(2026, 5, 26), "Kurban Bayramı", date(2026, 5, 26), date(2026, 5, 30), "1.40"),
    ("Yılbaşı gecesi", date(2026, 12, 31), "Yılbaşı gecesi", date(2026, 12, 31), date(2026, 12, 31), "1.80"),
)
NEW = (
    ("Yılbaşı (1 Ocak)", "milli_bayram", date(2025, 1, 1), date(2025, 1, 1), "1.25", "Çarşamba; yılbaşı tatili"),
    ("Sevgililer Günü", "ozel_gun", date(2025, 2, 14), date(2025, 2, 15), "1.55",
     "Cuma: hafta sonu konaklamaları ve romantik paketler için yüksek talep"),
    ("23 Nisan Ulusal Egemenlik ve Çocuk Bayramı", "milli_bayram", date(2025, 4, 23), date(2025, 4, 23), "1.10", "Çarşamba"),
    ("1 Mayıs (köprü ile uzun hafta sonu)", "milli_bayram", date(2025, 5, 1), date(2025, 5, 3), "1.15",
     "Perşembe; Cuma köprüsüyle uzun hafta sonu"),
    ("15 Temmuz (köprü ile uzun hafta sonu)", "milli_bayram", date(2025, 7, 12), date(2025, 7, 14), "1.10",
     "Salı; Pazartesi köprü tatili ihtimali"),
    ("30 Ağustos Zafer Bayramı", "milli_bayram", date(2025, 8, 29), date(2025, 8, 30), "1.10", "Cumartesi"),
    ("Yılbaşı uzun hafta sonu", "milli_bayram", date(2026, 1, 1), date(2026, 1, 3), "1.25",
     "Perşembe; Cuma köprüsüyle uzun hafta sonu"),
    ("Sevgililer Günü", "ozel_gun", date(2026, 2, 13), date(2026, 2, 14), "1.60",
     "Cumartesi: hafta sonuna denk geldiği için zirve doluluk"),
    ("Anneler Günü", "ozel_gun", date(2026, 5, 9), date(2026, 5, 9), "1.10",
     "Pazar; hafta sonu kahvaltı/brunch ve kısa konaklama artışı"),
    ("15 Temmuz Demokrasi ve Millî Birlik Günü", "milli_bayram", date(2026, 7, 15), date(2026, 7, 15), "1.05", "Çarşamba"),
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
    Event = apps.get_model("dashboard", "Event")
    Event.objects.filter(source=SOURCE).delete()
    # Endeks güncellemeleri geri alınmaz (veritabanı yedeği: _yedek/pasaport_otel_v77_oncesi.sql).


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0046_2025_sabit_giderler_yuzde_75'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
