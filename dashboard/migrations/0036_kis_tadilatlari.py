# Kış tadilatları (v56, kullanıcı isteği: "bir iki ayda anormal bir sabit gider olsun"). Model verisidir.
#
# Otel Kordon'da, denize bakan bir binada. Tadilatlar düşük sezonda yapılır:
#   Aralık 2025  Kahvaltı salonu ve lobi yenileme             680.000 TL
#   Şubat 2026   Kordon cephesi ve pencere doğramaları      1.150.000 TL
# "Tadilat ve yenileme" sabit gider kalemidir; kayıtlar tekrarlamaz (yalnız o ayda geçerli, tek seferlik). Ay kapanmışsa
# kapanıştaki sabit gider tutar kadar artırılır ve oda tiplerinin dondurulmuş payı aynı oranda büyütülür (gece payı ayın
# sabit gideriyle orantılıdır). Değişken gider, gelir ve doluluk değişmez.

from datetime import date
from decimal import Decimal

from django.db import migrations

CATEGORY = "Tadilat ve yenileme"
WORKS = (
    (date(2025, 12, 1), Decimal("680000.00"),
     "Kahvaltı salonu ve lobi yenileme: zemin, aydınlatma ve mobilya döşemeleri (düşük sezonda, bölüm bölüm)."),
    (date(2026, 2, 1), Decimal("1150000.00"),
     "Kordon cephesi ve pencere doğramaları: deniz tuzu ve lodosun yıprattığı doğramalar, cephe boyası, su yalıtımı."),
)


def forward(apps, schema_editor):
    Category = apps.get_model("dashboard", "MonthlyExpenseCategory")
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    ClosedPeriod = apps.get_model("dashboard", "ClosedPeriod")
    if not Expense.objects.exists():            # boş (test) veritabanı: model verisi yüklenmez
        return
    category, _ = Category.objects.get_or_create(
        name=CATEGORY, defaults={"group": "bakim", "cost_behavior": "sabit", "variable_basis": "oda_gecesi",
                                 "notes": "Tek seferlik tadilat ve yenileme işleri; tekrarlamaz, yalnız yapıldığı ay."})
    cent = Decimal("0.01")
    for month, amount, description in WORKS:
        _, created = Expense.objects.get_or_create(
            category=category, expense_month=month,
            defaults={"amount": amount, "variable_rate": Decimal("0"), "recurs_monthly": "hayir", "description": description})
        period = ClosedPeriod.objects.filter(month=month).first()
        if created and period and period.shared_total:
            ratio = (period.shared_total + amount) / period.shared_total
            period.shared_total += amount
            period.notes = (period.notes + " · tadilat eklendi").strip(" ·")[:240]
            period.save(update_fields=["shared_total", "notes"])
            for cost in period.costs.all():
                cost.shared = (cost.shared * ratio).quantize(cent)
                cost.save(update_fields=["shared"])


def backward(apps, schema_editor):
    Category = apps.get_model("dashboard", "MonthlyExpenseCategory")
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    ClosedPeriod = apps.get_model("dashboard", "ClosedPeriod")
    cent = Decimal("0.01")
    for month, amount, _ in WORKS:
        if not Expense.objects.filter(category__name=CATEGORY, expense_month=month).exists():
            continue
        period = ClosedPeriod.objects.filter(month=month).first()
        if period and period.shared_total > amount:
            ratio = (period.shared_total - amount) / period.shared_total
            period.shared_total -= amount
            period.save(update_fields=["shared_total"])
            for cost in period.costs.all():
                cost.shared = (cost.shared * ratio).quantize(cent)
                cost.save(update_fields=["shared"])
    Expense.objects.filter(category__name=CATEGORY).delete()
    Category.objects.filter(name=CATEGORY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0035_executive_suite_4_kisi'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
