# Sade dönem kapanışı: ay başına bir satır (donem_kapanislari) + oda tipi × kişi birim maliyeti (donem_maliyetleri).

import django.db.models.deletion
import django.utils.timezone
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0032_donem_kapanisini_kaldir'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClosedPeriod',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.DateField(db_column='ay', help_text='Ayın ilk günü.', unique=True, verbose_name='Ay')),
                ('closed_at', models.DateTimeField(db_column='kapanis_tarihi', default=django.utils.timezone.now, verbose_name='Kapanış tarihi')),
                ('available_room_nights', models.PositiveIntegerField(db_column='musait_oda_gece', verbose_name='Müsait oda-gece')),
                ('occupied_room_nights', models.PositiveIntegerField(db_column='satilan_oda_gece', verbose_name='Satılan oda-gece')),
                ('room_revenue', models.DecimalField(db_column='oda_geliri', decimal_places=2, max_digits=14, verbose_name='Oda geliri (TL, KDV hariç)')),
                ('commission_total', models.DecimalField(db_column='kanal_komisyonu', decimal_places=2, default=Decimal('0'), max_digits=14, verbose_name='Kanal komisyonu (TL)')),
                ('variable_total', models.DecimalField(db_column='degisken_gider', decimal_places=2, max_digits=14, verbose_name='Değişken gider (TL)')),
                ('shared_total', models.DecimalField(db_column='ortak_gider', decimal_places=2, help_text='Sabit kalemler + yarı değişken kalemlerin sabit tabanı.', max_digits=14, verbose_name='Ortak gider (TL)')),
                ('notes', models.CharField(blank=True, db_column='aciklama', max_length=240, verbose_name='Açıklama')),
            ],
            options={
                'verbose_name': 'Dönem kapanışı',
                'verbose_name_plural': 'Dönem kapanışları',
                'db_table': 'donem_kapanislari',
                'ordering': ['-month'],
            },
        ),
        migrations.CreateModel(
            name='ClosedPeriodCost',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('guests', models.PositiveSmallIntegerField(db_column='kisi_sayisi', verbose_name='Kişi sayısı')),
                ('variable', models.DecimalField(db_column='degisken_maliyet', decimal_places=2, max_digits=12, verbose_name='Oda satılınca oluşan gider (TL)')),
                ('shared', models.DecimalField(db_column='ortak_gider_payi', decimal_places=2, max_digits=12, verbose_name='Ortak gider payı (TL)')),
                ('period', models.ForeignKey(db_column='donem_id', on_delete=django.db.models.deletion.CASCADE, related_name='costs', to='dashboard.closedperiod', verbose_name='Dönem')),
                ('room_type', models.ForeignKey(db_column='oda_tipi_id', on_delete=django.db.models.deletion.PROTECT, to='dashboard.roomtype', verbose_name='Oda tipi')),
            ],
            options={
                'verbose_name': 'Dönem maliyeti',
                'verbose_name_plural': 'Dönem maliyetleri',
                'db_table': 'donem_maliyetleri',
                'ordering': ['period', 'room_type', 'guests'],
                'constraints': [models.UniqueConstraint(fields=('period', 'room_type', 'guests'), name='uq_donem_oda_kisi')],
            },
        ),
    ]
