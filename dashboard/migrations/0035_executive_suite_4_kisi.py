# Executive Suite 4 kişilik oldu (kullanıcı kararı, v55) ve 4 kişilik oda paketi eklendi.
#
# Yatak düzeni kuralı: 4 kişi = iki çift kişilik yatak. Paket 2 kişilik paketten türetilir; çift kişilik çarşaf,
# çift kişilik nevresim, alez ve yorgan yatak başına olduğu için 2'şer adet. Kişi başı satırlar (buklet, minibar,
# havlu...) zaten misafir sayısıyla çarpılır. 4 kişilik paket varsa ya da 2 kişilik paket yoksa dokunulmaz.

from django.db import migrations

PER_BED = ("Çift kişilik çarşaf", "Çift kişilik nevresim", "Alez / yatak koruyucu", "Yorgan")


def forward(apps, schema_editor):
    RoomType = apps.get_model("dashboard", "RoomType")
    RoomPackageItem = apps.get_model("dashboard", "RoomPackageItem")
    RoomType.objects.filter(code="EXS", max_guests__lt=4).update(max_guests=4)
    if RoomPackageItem.objects.filter(guest_count=4).exists():
        return
    for line in RoomPackageItem.objects.filter(guest_count=2).select_related("item", "textile_asset__item"):
        name = line.item.name if line.item_id else line.textile_asset.item.name
        RoomPackageItem.objects.create(
            guest_count=4, item_id=line.item_id, textile_asset_id=line.textile_asset_id,
            quantity_per_room_night=line.quantity_per_room_night * 2 if name in PER_BED else line.quantity_per_room_night,
            usage_basis=line.usage_basis, waste_rate=line.waste_rate, active=line.active,
            notes=(line.notes + " · 4 kişi: iki çift kişilik yatak")[:240] if name in PER_BED else line.notes)


def backward(apps, schema_editor):
    RoomType = apps.get_model("dashboard", "RoomType")
    RoomPackageItem = apps.get_model("dashboard", "RoomPackageItem")
    RoomType.objects.filter(code="EXS", max_guests=4).update(max_guests=3)
    RoomPackageItem.objects.filter(guest_count=4).delete()
    apps.get_model("dashboard", "ClosedPeriodCost").objects.filter(room_type__code="EXS", guests=4).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0034_ortak_gider_yillik_esas'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
