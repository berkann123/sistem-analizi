# Ortak gider gece payı yıllık esasa geçti (v54) ve gider kayıtları konaklama verisinin başladığı 2025'e uzatıldı.
#
# 1) Kapanmış ayların oda tipi payı (donem_maliyetleri.ortak_gider_payi) eskiden ayın tutarı ÷ (oda × ayın günü) idi;
#    artık ayın tutarı ÷ (oda × 365/12). Yeni pay = eski pay × ayın günü ÷ (365/12). Değişken maliyet ve kapanışın
#    toplamları (gelir, gider, doluluk) değişmez.
# 2) Bütün gider kayıtları 2026'da başlıyordu; 2025'in konaklamaları ve gelirleri vardı ama gideri yoktu (2025 çok
#    kârlı görünüyordu). 2025'ten önce gider kaydı yoksa her kaydın başlangıç ayı bir yıl geri alınır (tutarlar aynı;
#    mevsimli kayıtlar 2025'te de kendi aylarında geçerli olur).

import calendar
from datetime import date
from decimal import Decimal

from django.db import migrations


def forward(apps, schema_editor):
    ClosedPeriodCost = apps.get_model("dashboard", "ClosedPeriodCost")
    MonthlyHotelExpense = apps.get_model("dashboard", "MonthlyHotelExpense")
    cent = Decimal("0.01")
    for cost in ClosedPeriodCost.objects.select_related("period"):
        month = cost.period.month
        days = calendar.monthrange(month.year, month.month)[1]
        average = Decimal(366 if calendar.isleap(month.year) else 365) / Decimal(12)
        cost.shared = (cost.shared * Decimal(days) / average).quantize(cent)
        cost.save(update_fields=["shared"])

    expenses = MonthlyHotelExpense.objects.all()
    if expenses.exists() and not expenses.filter(expense_month__lt=date(2026, 1, 1)).exists():
        for expense in expenses.filter(expense_month__year=2026):
            expense.expense_month = expense.expense_month.replace(year=2025)
            expense.save(update_fields=["expense_month"])


def backward(apps, schema_editor):
    ClosedPeriodCost = apps.get_model("dashboard", "ClosedPeriodCost")
    MonthlyHotelExpense = apps.get_model("dashboard", "MonthlyHotelExpense")
    cent = Decimal("0.01")
    for cost in ClosedPeriodCost.objects.select_related("period"):
        month = cost.period.month
        days = calendar.monthrange(month.year, month.month)[1]
        average = Decimal(366 if calendar.isleap(month.year) else 365) / Decimal(12)
        cost.shared = (cost.shared * average / Decimal(days)).quantize(cent)
        cost.save(update_fields=["shared"])
    for expense in MonthlyHotelExpense.objects.filter(expense_month__year=2025):
        expense.expense_month = expense.expense_month.replace(year=2026)
        expense.save(update_fields=["expense_month"])


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0033_sade_donem_kapanisi'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
