"""Gider kalemlerinde üç maliyet davranışı: sabit, yarı değişken, değişken.

Önce: yalnızca "sabit" ve "degisken" vardı; ikisi de aynı formülle (aylık tutar ÷ müsait oda-gece)
      dağıtılıyordu. "degisken" gerçek anlamda değişken değil, "her ay tutarı değişen fatura" demekti.
Sonra: gider kaydına `degisken_birim_tutar` (satılan oda-gece başına TL) eklenir.
       - sabit         : yalnızca aylık tutar
       - yarı değişken : aylık tutar (sabit taban) + değişken birim tutar
       - değişken      : yalnızca değişken birim tutar

Mevcut "degisken" kalemler "yari_degisken" olur ve değişken tutarları 0 kalır. Bu kayıtlar
bugüne kadar olduğu gibi dağıtılmaya devam eder; hesaplanan maliyetler değişmez.
"""
import django.core.validators
from decimal import Decimal
from django.db import migrations, models

BEHAVIORS = [
    ("sabit", "Sabit"),
    ("yari_degisken", "Yarı değişken (sabit taban + satılan oda başı tutar)"),
    ("degisken", "Değişken (yalnızca satılan oda başı tutar)"),
]


def old_variable_becomes_semi_variable(apps, schema_editor):
    db = schema_editor.connection.alias
    Category = apps.get_model("dashboard", "MonthlyExpenseCategory")
    Category.objects.using(db).filter(cost_behavior="degisken").update(cost_behavior="yari_degisken")


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0005_tekstil_alt_tip_tablosu"),
    ]

    operations = [
        # "yari_degisken" 13 karakterdir; kolon 12 karakterlikti.
        migrations.AlterField(
            model_name="monthlyexpensecategory",
            name="cost_behavior",
            field=models.CharField(choices=BEHAVIORS, db_column="gider_davranisi", default="sabit", max_length=20,
                                   verbose_name="Maliyet davranışı"),
        ),
        migrations.RunPython(old_variable_becomes_semi_variable, migrations.RunPython.noop),
        migrations.AddField(
            model_name="monthlyhotelexpense",
            name="variable_rate",
            field=models.DecimalField(
                db_column="degisken_birim_tutar", decimal_places=2, default=0, max_digits=14,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="Satılan oda-gece başına değişken tutar (TL, KDV hariç)",
                help_text="Yarı değişken ve değişken kalemlerde doldurulur. Sabit kalemde 0."),
        ),
        # Yeni kolon tablonun sonuna eklenir; mantıksal yerine (tutar'ın yanına) alınır.
        migrations.RunSQL(
            sql="ALTER TABLE aylik_otel_giderleri MODIFY COLUMN degisken_birim_tutar decimal(14,2) NOT NULL AFTER tutar",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="monthlyhotelexpense",
            name="amount",
            field=models.DecimalField(
                db_column="tutar", decimal_places=2, default=0, max_digits=14,
                validators=[django.core.validators.MinValueValidator(Decimal("0"))],
                verbose_name="Aylık sabit tutar (TL, KDV hariç)",
                help_text="Sabit kalemde giderin tamamı; yarı değişken kalemde yalnızca sabit taban. Değişken kalemde 0."),
        ),
    ]
