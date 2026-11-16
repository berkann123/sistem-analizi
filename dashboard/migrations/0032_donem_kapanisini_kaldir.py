# Dönem kapanışı kaldırıldı: donem_kapanislari, donem_giderleri, donem_maliyetleri. Bütün aylar güncel kayıtlardan hesaplanır.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0031_tekrarlanan_kolonlari_kaldir'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='closedperiodcost',
            name='uq_donem_oda_kisi',
        ),
        migrations.RemoveConstraint(
            model_name='closedperiodexpense',
            name='uq_donem_gider_kalem',
        ),
        migrations.RemoveField(
            model_name='closedperiodexpense',
            name='category',
        ),
        migrations.RemoveField(
            model_name='closedperiodexpense',
            name='period',
        ),
        migrations.DeleteModel(
            name='ClosedPeriodCost',
        ),
        migrations.DeleteModel(
            name='ClosedPeriod',
        ),
        migrations.DeleteModel(
            name='ClosedPeriodExpense',
        ),
    ]
