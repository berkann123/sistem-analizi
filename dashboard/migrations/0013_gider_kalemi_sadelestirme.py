from django.db import migrations

# Muhasebe ve danışmanlık ayrı bir kalem değildir: bu iş personel giderinin içinde hesaba katılmıştır.
REMOVED = ["Muhasebe ve danışmanlık"]
# Otelin tek bir çamaşırhanesi vardır; kalem adında "dış çamaşırhane" ayrımına gerek yoktur.
RENAMED = {
    "Havlu yıkama (dış çamaşırhane)": "Havlu yıkama",
    "Çarşaf ve nevresim yıkama (dış çamaşırhane)": "Çarşaf ve nevresim yıkama",
}
DESCRIPTION_FIXES = {
    "30 TL/kg dış çamaşırhane fiyatı": "30 TL/kg yıkama maliyeti",
    "4 kg × 30 TL/kg.": "4 kg × 30 TL/kg yıkama maliyeti.",
}


def simplify(apps, schema_editor):
    Category = apps.get_model("dashboard", "MonthlyExpenseCategory")
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    # Gider kaydı olan kalem silinemez (PROTECT); önce kayıtları, sonra kalemin kendisi silinir.
    Expense.objects.filter(category__name__in=REMOVED).delete()
    Category.objects.filter(name__in=REMOVED).delete()
    for old, new in RENAMED.items():
        if not Category.objects.filter(name=new).exists():
            Category.objects.filter(name=old).update(name=new)
    for expense in Expense.objects.filter(category__name__in=RENAMED.values()):
        description = expense.description
        for old, new in DESCRIPTION_FIXES.items():
            if new not in description:
                description = description.replace(old, new)
        if description != expense.description:
            expense.description = description
            expense.save(update_fields=["description"])


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0012_paket_bileseni_kisi_basi_varsayilan")]
    operations = [migrations.RunPython(simplify, migrations.RunPython.noop)]
