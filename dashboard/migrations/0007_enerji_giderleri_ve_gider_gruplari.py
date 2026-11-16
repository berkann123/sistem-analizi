"""Enerji, diğer giderlerle aynı yapıda tutulur; gider kalemleri gruplanır.

Önce: enerji için iki ayrı mekanizma vardı ve birbirini devre dışı bırakıyordu:
      (a) `oda_enerji_su_gaz_tarifeleri` tablosu: oda/kişi başı tüketim × birim fiyat
      (b) `bagli_hizmet_turu` ile işaretli aylık fatura kalemi
Sonra: tek mekanizma. "Enerji giderleri" grubunda Elektrik, Su ve Doğalgaz kalemleri yarı değişkendir:
       aylık sabit tutar (otel boşken de gelen fatura) + misafirle artan değişken birim tutar.

- `gider_gruplari` tablosu eklenir; her gider kalemi bir gruba bağlanır.
- Kalemlere `degisken_tutar_esasi` eklenir: değişken tutar oda-gece ya da kişi-gece ile çarpılır.
- Tarifeler, aynı sonucu veren gider kayıtlarına çevrilir (tüketim × birim fiyat = değişken birim tutar);
  hesaplanan maliyetler değişmez. Ardından tarife tablosu ve `bagli_hizmet_turu` kolonu kaldırılır.
"""
import django.core.validators
import django.db.models.deletion
from decimal import ROUND_HALF_UP, Decimal
from django.db import migrations, models

GROUPS = [  # (ad, sıra)
    ("Personel giderleri", 1), ("Enerji giderleri", 2), ("Bina giderleri", 3),
    ("Bakım ve onarım giderleri", 4), ("Genel yönetim giderleri", 5), ("Diğer giderler", 9),
]
# Mevcut kalemler adlarındaki anahtar kelimeye göre gruplanır; eşleşmeyen "Diğer giderler"e düşer.
KEYWORDS = [
    ("Enerji giderleri", ("enerji", "elektrik", "doğalgaz", "dogalgaz", " su ", "su ve", "ısıtma")),
    ("Personel giderleri", ("personel", "maaş", "ücret", "bordro")),
    ("Bina giderleri", ("kira", "sigorta", "ruhsat", "aidat", "emlak")),
    ("Bakım ve onarım giderleri", ("bakım", "onarım", "tamir")),
    ("Genel yönetim giderleri", ("bilgi işlem", "yazılım", "muhasebe", "danışman", "yönetim", "internet")),
]
ENERGY_NAMES = {"elektrik": "Elektrik", "su": "Su ve atık su", "dogalgaz": "Doğalgaz"}


def check_no_room_type_tariffs(apps, schema_editor):
    """Oda tipine özel tarife yeni yapıda karşılanmaz; sessizce kaybolmasın diye geçiş durdurulur."""
    Rate = apps.get_model("dashboard", "UtilityRate")
    if Rate.objects.using(schema_editor.connection.alias).filter(active=True, room_type__isnull=False).exists():
        raise RuntimeError(
            "Oda tipine özel etkin enerji tarifesi var. Yeni yapıda enerji bütün odalar için tek kalemdir. "
            "Önce bu tarifeleri Admin'den pasif yapın ya da genel tarifeye çevirin, sonra komutu yeniden çalıştırın.")


def tr_lower(text):
    return f" {(text or '').replace('I', 'ı').replace('İ', 'i').lower()} "


def build_groups_and_convert_tariffs(apps, schema_editor):
    db = schema_editor.connection.alias
    Group = apps.get_model("dashboard", "ExpenseGroup")
    Category = apps.get_model("dashboard", "MonthlyExpenseCategory")
    Expense = apps.get_model("dashboard", "MonthlyHotelExpense")
    Rate = apps.get_model("dashboard", "UtilityRate")

    groups = {name: Group.objects.using(db).get_or_create(name=name, defaults={"sort_order": order})[0]
              for name, order in GROUPS}

    # 1) Mevcut kalemleri grupla.
    for category in Category.objects.using(db).all():
        text = tr_lower(category.name)
        target = "Diğer giderler"
        if category.utility_type:
            target = "Enerji giderleri"
        else:
            for group_name, words in KEYWORDS:
                if any(word in text for word in words):
                    target = group_name
                    break
        Category.objects.using(db).filter(pk=category.pk).update(group=groups[target])

    # 2) Her enerji türü için tek kalem: varsa fatura kalemi kullanılır, yoksa yenisi açılır.
    for utility, clean_name in ENERGY_NAMES.items():
        tariffs = list(Rate.objects.using(db).filter(utility_type=utility, active=True, room_type__isnull=True)
                       .order_by("effective_from"))
        category = Category.objects.using(db).filter(utility_type=utility).order_by("pk").first()
        if category is None and not tariffs:
            continue
        if category is None:
            category = Category.objects.using(db).filter(name=clean_name).first() or Category.objects.using(db).create(
                name=clean_name, group=groups["Enerji giderleri"], cost_behavior="yari_degisken")
        # "Ortak enerji faturası" gibi genel adlar, kalemin gerçekte ne olduğunu söyleyen adla değiştirilir.
        new_name = category.name
        if category.name != clean_name and not Category.objects.using(db).filter(name=clean_name).exists():
            new_name = clean_name
        basis = tariffs[-1].usage_basis if tariffs else "oda_gecesi"
        Category.objects.using(db).filter(pk=category.pk).update(
            name=new_name, group=groups["Enerji giderleri"], cost_behavior="yari_degisken", variable_basis=basis)

        # 3) Tarife -> gider kaydı. Değişken birim tutar = tüketim × birim fiyat.
        for tariff in tariffs:
            month = tariff.effective_from.replace(day=1)
            # Eski kural: o ay için fatura geçerliyse tarife kullanılmazdı. Aynı sonuç için,
            # faturanın geçerli olduğu aya tarife kaydı açılmaz.
            billed = Expense.objects.using(db).filter(category_id=category.pk, expense_month__lte=month).filter(
                models.Q(expense_month=month)
                | (models.Q(recurs_monthly="evet")
                   & (models.Q(recurring_until__isnull=True) | models.Q(recurring_until__gte=month)))
            ).exists()
            if billed:
                continue
            rate = (tariff.quantity_per_room_night * tariff.unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            Expense.objects.using(db).create(
                category_id=category.pk, expense_month=month, amount=Decimal("0"), variable_rate=rate,
                recurs_monthly="evet",
                description=(f"Tarifeden aktarıldı: {tariff.quantity_per_room_night.normalize():f} {tariff.unit} × "
                             f"{tariff.unit_cost.normalize():f} TL")[:240],
            )


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0006_uc_maliyet_davranisi"),
    ]

    operations = [
        migrations.RunPython(check_no_room_type_tariffs, migrations.RunPython.noop),
        migrations.CreateModel(
            name="ExpenseGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(db_column="grup_adi", max_length=120, unique=True, verbose_name="Grup adı")),
                ("sort_order", models.PositiveSmallIntegerField(
                    db_column="sira", default=0, help_text="Raporlarda grupların görünme sırası.", verbose_name="Sıra")),
            ],
            options={
                "verbose_name": "Gider grubu", "verbose_name_plural": "Gider grupları",
                "db_table": "gider_gruplari", "ordering": ["sort_order", "name"],
            },
        ),
        # Önce boş bırakılabilir eklenir, veriler doldurulur, sonra zorunlu yapılır.
        migrations.AddField(
            model_name="monthlyexpensecategory",
            name="group",
            field=models.ForeignKey(
                db_column="gider_grubu_id", null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="categories", to="dashboard.expensegroup", verbose_name="Gider grubu"),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE aylik_gider_kategorileri MODIFY COLUMN gider_grubu_id bigint NULL AFTER gider_kalemi",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddField(
            model_name="monthlyexpensecategory",
            name="variable_basis",
            field=models.CharField(
                choices=[("oda_gecesi", "Satılan oda-gece başına"), ("kisi_gecesi", "Konaklayan kişi-gece başına")],
                db_column="degisken_tutar_esasi", default="oda_gecesi", max_length=20,
                verbose_name="Değişken tutarın esası",
                help_text="Yarı değişken ve değişken kalemlerde değişken tutarın neyle çarpılacağı. Oda kliması gibi "
                          "odaya bağlı tüketim için oda-gece, su gibi kişiye bağlı tüketim için kişi-gece seçin."),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE aylik_gider_kategorileri MODIFY COLUMN degisken_tutar_esasi varchar(20) NOT NULL AFTER gider_davranisi",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(build_groups_and_convert_tariffs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="monthlyexpensecategory",
            name="group",
            field=models.ForeignKey(
                db_column="gider_grubu_id", on_delete=django.db.models.deletion.PROTECT,
                related_name="categories", to="dashboard.expensegroup", verbose_name="Gider grubu"),
        ),
        migrations.RemoveField(model_name="monthlyexpensecategory", name="utility_type"),
        migrations.DeleteModel(name="UtilityRate"),
        # Aşağıdakiler yalnızca sıralama ve ekrandaki alan adlarını günceller; tablo yapısı değişmez.
        migrations.AlterModelOptions(
            name="monthlyexpensecategory",
            options={"ordering": ["group__sort_order", "group__name", "name"],
                     "verbose_name": "Aylık gider kategorisi", "verbose_name_plural": "Aylık gider kategorileri"},
        ),
        migrations.AlterField(
            model_name="monthlyexpensecategory",
            name="name",
            field=models.CharField(db_column="gider_kalemi", max_length=120, unique=True, verbose_name="Gider kalemi"),
        ),
        migrations.AlterField(
            model_name="monthlyhotelexpense",
            name="variable_rate",
            field=models.DecimalField(
                db_column="degisken_birim_tutar", decimal_places=2, default=0, max_digits=14,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="Değişken birim tutar (TL, KDV hariç)",
                help_text="Satılan bir oda-gece ya da konaklayan bir kişi-gece için eklenen tutar; hangisi olduğunu "
                          "gider kaleminin 'Değişken tutarın esası' belirler. Sabit kalemde 0."),
        ),
    ]
