# Ürün türü kategoriyi tekrarlıyordu, temel kapasite her oda tipinde 2 ve hiçbir hesapta kullanılmıyordu.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0030_fiyat_kurallari_tablosu'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='inventoryitem',
            name='item_type',
        ),
        migrations.RemoveField(
            model_name='roomtype',
            name='base_capacity',
        ),
    ]
