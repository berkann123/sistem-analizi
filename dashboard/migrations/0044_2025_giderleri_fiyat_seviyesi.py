# 2025 giderleri 2025 fiyat seviyesine çekildi (v74, kullanıcı kararı).
#
# Sorun: örnek veride 2025 konaklama fiyatları 2026'nın %80'i (PRICE_2025, yıllık ~%25 fiyat artışı varsayımı), ama
# 2025 giderleri migration 0034'te 2026 tutarlarıyla birebir geriye yazılmıştı. Gelir %25 artarken gider aynı kalınca
# 2025 kârı yapay olarak düşük (Ocak–Ekim marj %9), 2026 kârı yüksek (%23) çıkıyordu.
#
# Düzeltme: her "her ay tekrarlar" gider kaleminin 2025 kaydı (sabit tutar ve değişken birim tutar) × 0,80. Mevcut
# tutarlar 2026'dan geçerli yeni kayıtlara taşındı (mevsimli kalemde mevsimin 2026'daki ilk ayı: kış Ocak, geçiş Nisan,
# yaz Haziran). Böylece 2026 ve sonrası (fiyat motoru dahil) değişmez.
# Dokunulmayanlar: amortisman (alış bedeli üzerinden, enflasyonla değişmez) ve tek seferlik tadilat faturaları.

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations

FACTOR = Decimal("0.80")
KEEP = {"Mobilya ve demirbaş amortismanı"}
FIRST_2026 = {"": date(2026, 1, 1), "kis": date(2026, 1, 1), "gecis": date(2026, 4, 1), "yaz": date(2026, 6, 1)}
NOTE = " · 2026'dan geçerli tutar (v74)"


def _round(value, step):
    return (value * FACTOR / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def forward(apps, schema_editor):
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    rows = Expense.objects.filter(recurs_monthly="evet", expense_month__year=2025).select_related("category")
    for row in rows:
        if row.category.name in KEEP:
            continue
        start = FIRST_2026[row.season]
        if Expense.objects.filter(category=row.category, expense_month=start).exists():
            continue                                             # 2026 kaydı zaten var: iki kez çalıştırma
        Expense.objects.create(category=row.category, expense_month=start, season=row.season, amount=row.amount,
                               variable_rate=row.variable_rate, recurs_monthly="evet",
                               recurring_until=row.recurring_until, description=(row.description + NOTE)[:240])
        row.amount = _round(row.amount, Decimal("1000")) if row.amount >= 10000 else _round(row.amount, Decimal("1"))
        row.variable_rate = _round(row.variable_rate, Decimal("0.01"))
        row.description = (row.description.split(" · 2025 fiyat seviyesi")[0] + " · 2025 fiyat seviyesi (2026 × 0,80)")[:240]
        row.save(update_fields=["amount", "variable_rate", "description"])


def backward(apps, schema_editor):
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    for new in Expense.objects.filter(description__endswith=NOTE):
        old = Expense.objects.filter(category=new.category, season=new.season, expense_month__year=2025,
                                     recurs_monthly="evet").first()
        if old is not None:
            old.amount, old.variable_rate = new.amount, new.variable_rate
            old.description = old.description.split(" · 2025 fiyat seviyesi")[0]
            old.save(update_fields=["amount", "variable_rate", "description"])
        new.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0043_piyasa_fiyatlari_izmir_dolulugu'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
