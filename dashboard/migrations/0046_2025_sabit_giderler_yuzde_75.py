# 2025 sabit giderleri 2026'dan %25 düşük (v75, kullanıcı kararı; v74'teki %20'nin yerine).
#
# Her tekrarlayan gider kaleminin 2025 kaydı = aynı kalemin 2026 kaydı × 0,75 (sabit tutar ve değişken birim tutar).
# Kullanıcı "bütün sabit giderler" dediği için amortisman da dahil: 2026'dan geçerli kaydı açılır (300.000 ₺), 2025'i
# 225.000 ₺ olur. Tek seferlik tadilat faturaları (Aralık 2025, Şubat 2026) değişmez.

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations

FACTOR = Decimal("0.75")
FIRST_2026 = {"": date(2026, 1, 1), "kis": date(2026, 1, 1), "gecis": date(2026, 4, 1), "yaz": date(2026, 6, 1)}
TAG = " · 2025 fiyat seviyesi"


def _scaled(value, step):
    return (value * FACTOR / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def forward(apps, schema_editor):
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    for old in Expense.objects.filter(recurs_monthly="evet", expense_month__year=2025).select_related("category"):
        start = FIRST_2026[old.season]
        new = Expense.objects.filter(category=old.category, expense_month=start).first()
        if new is None:                                    # 2026 kaydı yok (ör. amortisman): bugünkü tutarla aç
            new = Expense.objects.create(
                category=old.category, expense_month=start, season=old.season, amount=old.amount,
                variable_rate=old.variable_rate, recurs_monthly="evet", recurring_until=old.recurring_until,
                description=(old.description + " · 2026'dan geçerli tutar (v75)")[:240])
        old.amount = _scaled(new.amount, Decimal("1000") if new.amount >= 100000 else Decimal("100"))
        old.variable_rate = _scaled(new.variable_rate, Decimal("0.01"))
        old.description = (old.description.split(TAG)[0] + TAG + " (2026 × 0,75)")[:240]
        old.save(update_fields=["amount", "variable_rate", "description"])


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0045_hammadde_fiyat_endeksi'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
