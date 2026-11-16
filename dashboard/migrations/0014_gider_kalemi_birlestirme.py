from django.db import migrations

# 1) Bilgi işlem ile İletişim ve yayın aynı türden giderdir (dışarıdan alınan teknoloji hizmetleri): tek kalem olur.
MERGE_INTO, MERGE_FROM, MERGED_NAME = "Bilgi işlem", "İletişim ve yayın", "Bilgi işlem ve iletişim"
MERGED_NOTE = "Model varsayımı (KDV hariç): yazılım lisansları, internet, telefon ve oda televizyonu yayın aboneliği."
# 2) Pazarlama personeli personel giderindedir; bu kalemde yalnızca dışarıya ödenen reklam harcaması kalır.
RENAMED = {"Pazarlama ve tanıtım": "Reklam ve tanıtım"}
RENAMED_NOTE = ("Varsayım: yalnızca dışarıya ödenen reklam ve tanıtım harcaması (dijital reklam, çekim, tanıtım). "
                "Pazarlama personeli personel giderindedir.")
# 3) Çamaşırlar otelin kendi çamaşırhanesinde yıkanır: personeli personel giderinde, suyu ve elektriği enerji
#    giderindedir. Dışarıya yıkatma varsayımıyla eklenen kalemler kaldırılır.
REMOVED = ["Havlu yıkama", "Çarşaf ve nevresim yıkama", "Havlu yıkama (dış çamaşırhane)",
           "Çarşaf ve nevresim yıkama (dış çamaşırhane)"]
EMPTY_GROUP = "Kat hizmetleri giderleri"


def simplify(apps, schema_editor):
    Group = apps.get_model("dashboard", "ExpenseGroup")
    Category = apps.get_model("dashboard", "MonthlyExpenseCategory")
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")

    target = Category.objects.filter(name=MERGE_INTO).first() or Category.objects.filter(name=MERGED_NAME).first()
    source = Category.objects.filter(name=MERGE_FROM).first()
    if target and source:
        for expense in Expense.objects.filter(category=source):
            same_month = Expense.objects.filter(category=target, expense_month=expense.expense_month).first()
            if same_month:                               # aynı ayın tutarları toplanır: 18.000 + 25.000 = 43.000
                same_month.amount += expense.amount
                same_month.description = MERGED_NOTE
                same_month.save(update_fields=["amount", "description"])
                expense.delete()
            else:                                        # hedefte o ay yoksa kayıt olduğu gibi devralınır
                expense.category = target
                expense.save(update_fields=["category"])
        source.delete()
    if target and target.name != MERGED_NAME:
        target.name = MERGED_NAME
        target.save(update_fields=["name"])

    for old, new in RENAMED.items():
        if not Category.objects.filter(name=new).exists() and Category.objects.filter(name=old).update(name=new):
            Expense.objects.filter(category__name=new).update(description=RENAMED_NOTE)

    Expense.objects.filter(category__name__in=REMOVED).delete()
    Category.objects.filter(name__in=REMOVED).delete()
    # İçinde kalem kalmayan grup da kaldırılır (boş başlık kalmasın).
    group = Group.objects.filter(name=EMPTY_GROUP).first()
    if group and not Category.objects.filter(group=group).exists():
        group.delete()


class Migration(migrations.Migration):
    dependencies = [("dashboard", "0013_gider_kalemi_sadelestirme")]
    operations = [migrations.RunPython(simplify, migrations.RunPython.noop)]
