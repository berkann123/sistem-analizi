"""Bir gider kaleminin bir ayda tek kaydı olur; geçiş artığı kayıtlar temizlenir.

1. Önceki geçiş, enerji tarifelerini gider kaydına çevirirken geçmiş aylar için de kayıt açmıştı
   (ör. Elektrik için Nisan'da tarife kaydı, Ekim'de fatura kaydı). Yenisi geçerli olduğu için
   eskisi hesaba girmiyor, yalnızca listede "Elektrik iki kez girilmiş" görüntüsü veriyordu.
   Bu kayıtlar, DOKUNULMAMIŞSA ve aynı kalemin daha yeni bir kaydı varsa silinir.
2. Aynı kalemin aynı aya ait birden çok kaydı tek kayıtta birleştirilir (tutarlar toplanır;
   sistem bunları zaten topluyordu, hesaplanan maliyet değişmez).
3. (gider kalemi, ay) çifti benzersiz yapılır: aynı gider aynı aya ikinci kez girilemez.
"""
from django.db import migrations, models

TARIFF_NOTE = "Tarifeden aktarıldı:"


def remove_superseded_tariff_records(apps, schema_editor):
    db = schema_editor.connection.alias
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    untouched = Expense.objects.using(db).filter(description__startswith=TARIFF_NOTE, amount=0)
    for record in untouched:
        newer_exists = Expense.objects.using(db).filter(
            category_id=record.category_id, expense_month__gt=record.expense_month).exists()
        if newer_exists:
            Expense.objects.using(db).filter(pk=record.pk).delete()


def merge_same_month_records(apps, schema_editor):
    db = schema_editor.connection.alias
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    seen = {}
    for record in Expense.objects.using(db).order_by("category_id", "expense_month", "pk"):
        key = (record.category_id, record.expense_month)
        keeper = seen.get(key)
        if keeper is None:
            seen[key] = record
            continue
        # İkinci kayıt ilkine eklenir, sonra silinir.
        keeper.amount += record.amount
        keeper.variable_rate += record.variable_rate
        if record.recurs_monthly == "evet":
            keeper.recurs_monthly = "evet"
        notes = [text for text in (keeper.description, record.description) if text]
        keeper.description = " + ".join(dict.fromkeys(notes))[:240]
        Expense.objects.using(db).filter(pk=keeper.pk).update(
            amount=keeper.amount, variable_rate=keeper.variable_rate,
            recurs_monthly=keeper.recurs_monthly, description=keeper.description)
        Expense.objects.using(db).filter(pk=record.pk).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0007_enerji_giderleri_ve_gider_gruplari"),
    ]

    operations = [
        migrations.RunPython(remove_superseded_tariff_records, migrations.RunPython.noop),
        migrations.RunPython(merge_same_month_records, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="monthlyhotelexpense",
            constraint=models.UniqueConstraint(fields=("category", "expense_month"), name="uq_gider_kalem_ay"),
        ),
    ]
