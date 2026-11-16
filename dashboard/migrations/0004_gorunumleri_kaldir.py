"""Okunabilirlik için eklenen altı görünüm (VIEW) kaldırılır.

Görünümler veri tutmaz ve uygulama tarafından kullanılmıyordu; yalnızca phpMyAdmin'de tabloları
adlarıyla birlikte okumak içindi. Kimlikler sayısal ve kolonlar düzenli olduğu için şimdilik
gerek kalmadı; Tasarımcı'da ilişkisiz kutu olarak kalabalık yapıyorlardı.

İleride rapor amaçlı görünümler ve tetikleyiciler (trigger) eklenecekse, yeni bir migration
içinde `migrations.RunSQL` ile tanımlanmalıdır. Böylece veritabanı sıfırdan kurulduğunda da oluşurlar.
"""
from django.db import migrations

VIEWS = [
    "v_odalar", "v_stok_durumu", "v_envanter_hareketleri",
    "v_kahvalti_bufesi", "v_oda_paketleri", "v_aylik_giderler",
]


class Migration(migrations.Migration):

    dependencies = [("dashboard", "0003_tedarikci_ve_tekstil_iliskileri")]

    operations = [
        migrations.RunSQL(
            sql=[f"DROP VIEW IF EXISTS {name}" for name in VIEWS],
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
