"""Doluluk, odalara bağlı konaklama kayıtlarından türetilir; elle girilen günlük tablo kaldırılır.

Önce: `gunluk_otel_metrikleri` tablosuna "bugün 37 oda dolu" diye elle bir sayı giriliyordu.
      Bu sayı hiçbir odaya bağlı değildi; odalar tablosuna bakınca hangi odanın dolu olduğu görünmüyordu.
Sonra: `konaklamalar` tablosu her konaklamayı odasına bağlar (oda, giriş, çıkış, misafir sayısı).
       Bir odanın bugün dolu olup olmadığı da, ayın doluluk oranı da bu kayıtlardan hesaplanır.
       Aynı bilgi ikinci bir yerde saklanmaz.

Günlük tablodaki toplam sayılar oda bazına çevrilemez (hangi 37 oda olduğu bilinmiyor), bu yüzden
aktarılmaz; tablo, içindeki örnek kayıtla birlikte kaldırılır. Oda geliri de şimdilik tutulmaz.
"""
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0009_gider_merkezi_ve_ad_temizligi"),
    ]

    operations = [
        migrations.CreateModel(
            name="Stay",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("room", models.ForeignKey(
                    db_column="oda_id", on_delete=django.db.models.deletion.PROTECT, related_name="stays",
                    to="dashboard.room", verbose_name="Oda")),
                ("check_in", models.DateField(db_column="giris_tarihi", verbose_name="Giriş tarihi")),
                ("check_out", models.DateField(db_column="cikis_tarihi", verbose_name="Çıkış tarihi")),
                ("guests", models.PositiveSmallIntegerField(
                    db_column="misafir_sayisi", default=1,
                    validators=[django.core.validators.MinValueValidator(1)], verbose_name="Misafir sayısı")),
                ("notes", models.CharField(blank=True, db_column="aciklama", max_length=240, verbose_name="Açıklama")),
            ],
            options={
                "verbose_name": "Konaklama",
                "verbose_name_plural": "Konaklamalar",
                "db_table": "konaklamalar",
                "ordering": ["-check_in", "room__room_number"],
            },
        ),
        migrations.AddConstraint(
            model_name="stay",
            constraint=models.CheckConstraint(
                condition=models.Q(("check_out__gt", models.F("check_in"))),
                name="ck_konaklama_cikis_giristen_sonra"),
        ),
        migrations.DeleteModel(name="DailyHotelMetric"),
    ]
