from decimal import ROUND_DOWN, Decimal as D

from django.core.management.base import BaseCommand
from django.db import transaction

from dashboard.models import InventoryItem, InventoryMovement

NOTE = "Gösterim amaçlı sayım düzeltmesi (model verisi): stok kritik seviyenin altına indirildi"
TARGET_SHARE = D("0.7")     # stok, kritik seviyenin %70'ine indirilir
# Farklı tedarikçilerden, konaklamada tüketilen 10 ürün: uyarı kutusunda birkaç tedarikçi grubu görünsün diye.
ITEMS = ["GID-001", "GID-002", "GID-008", "GID-019", "GID-021", "ICE-001", "ICE-002", "BKL-001", "BKL-011", "TEM-109"]


class Command(BaseCommand):
    help = ("Gösterim için seçili 10 ürünün stoğunu kritik seviyenin altına indirir (eksi sayım düzeltmesi, model "
            "verisi). Zaten kritik olan ürüne dokunmaz. Stok, sipariş teslim alınınca yeniden yükselir.")

    def add_arguments(self, parser):
        parser.add_argument("--onizle", action="store_true", help="Değişiklik yapmadan yapılacakları listeler.")

    def handle(self, *args, **options):
        changed = 0
        with transaction.atomic():
            for item in InventoryItem.objects.filter(sku__in=ITEMS, active=True).select_related("supplier").order_by("sku"):
                if item.is_critical or not item.reorder_level:
                    self.stdout.write(f"  {item.sku} {item.name}: zaten kritik ya da kritik seviyesi yok; atlandı.")
                    continue
                places = D("1") if item.unit in ("adet", "demet") else D("0.001")
                target = (item.reorder_level * TARGET_SHARE).quantize(places, rounding=ROUND_DOWN)
                difference = item.current_stock - target
                InventoryMovement.objects.create(item=item, movement_type=InventoryMovement.MovementType.COUNT_ADJUSTMENT,
                                                 quantity=-difference, unit_cost=item.average_unit_cost, notes=NOTE)
                changed += 1
                self.stdout.write(f"  {item.sku} {item.name}: {item.current_stock.normalize():f} -> {target.normalize():f} "
                                  f"{item.unit} (kritik {item.reorder_level.normalize():f}) · {item.supplier}")
            if options["onizle"]:
                transaction.set_rollback(True)
        verb = "indirilecek" if options["onizle"] else "indirildi"
        self.stdout.write(self.style.SUCCESS(f"{changed} ürün kritik seviyenin altına {verb}."))
