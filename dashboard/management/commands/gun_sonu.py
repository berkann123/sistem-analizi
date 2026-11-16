from datetime import datetime, time, timedelta
from decimal import Decimal as D

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from dashboard.models import InventoryItem, InventoryMovement
from dashboard.services import night_consumption

Move = InventoryMovement.MovementType
THOUSANDTH = D("0.001")
RESTOCK_NOTE = "Otomatik ikmal (model verisi): stok kritik seviyenin altına inecekti"


def at(day, hour, minute):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class Command(BaseCommand):
    help = ("Gün sonu (night audit): konaklamalardan doğan stok tüketimini işler. Her gece için o gece konaklayan "
            "odaların kahvaltı ve oda paketi tüketimi reçeteye göre hesaplanır; ürün başına bir tüketim ve bir fire "
            "hareketi olarak stoktan düşülür. İşlenmiş gece tekrar işlenmez. Bir ürün, ilk alımından önceki "
            "gecelerden düşülmez.")

    def add_arguments(self, parser):
        parser.add_argument("--kadar", help="Bu geceye kadar (dahil) işler, YYYY-AA-GG. Varsayılan: bugün.")
        parser.add_argument("--ikmal", action="store_true",
                            help="Stok kritik seviyenin altına inecekse önce otomatik alım girer (model verisi). "
                                 "Verilmezse stoğu yetmeyen ürün o gece için atlanır ve uyarılır.")
        parser.add_argument("--onizle", action="store_true", help="Değişiklik yapmadan yapılacakları listeler.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        try:
            until = datetime.strptime(options["kadar"], "%Y-%m-%d").date() if options.get("kadar") else today
        except ValueError as exc:
            raise CommandError("--kadar biçimi YYYY-AA-GG olmalı, ör. 2026-10-31") from exc
        if until > today:
            self.stdout.write(self.style.WARNING(f"{until:%d.%m.%Y} ileri bir tarih: gelecek geceler için ileri "
                                                 "tarihli konaklamalarla SİMÜLASYON yapılıyor."))

        # Her ürün, ilk alımının yapıldığı günden itibaren tüketilebilir.
        first_purchase = {
            item_id: timezone.localtime(moment).date() for item_id, moment in
            InventoryMovement.objects.filter(movement_type=Move.PURCHASE).values("item_id")
            .annotate(first=Min("movement_at")).values_list("item_id", "first")
        }
        if not first_purchase:
            self.stdout.write("Hiçbir üründe alım yok; işlenecek stok yok.")
            return
        closed = set(InventoryMovement.objects.filter(consumption_day__isnull=False, movement_type=Move.CONSUMPTION)
                     .values_list("item_id", "consumption_day"))
        self.skipped = 0
        totals = {"nights": 0, "movements": 0, "restocks": 0, "value": D("0")}

        with transaction.atomic():
            day = min(first_purchase.values())
            while day <= until:
                self.close_day(day, first_purchase, closed, options["ikmal"], totals)
                day += timedelta(days=1)
            if options["onizle"]:
                transaction.set_rollback(True)

        if not totals["movements"]:
            self.stdout.write("İşlenecek yeni gece yok; stok güncel.")
            return
        summary = (f"{totals['nights']} gece işlendi: {totals['movements']} stok hareketi, "
                   f"tüketim değeri {totals['value']:,.2f} TL"
                   + (f", {totals['restocks']} otomatik ikmal" if totals["restocks"] else "") + ".")
        if options["onizle"]:
            self.stdout.write(self.style.WARNING("ÖNİZLEME: " + summary + " Hiçbir şey kaydedilmedi."))
        else:
            self.stdout.write(self.style.SUCCESS(summary))
        if self.skipped:
            self.stdout.write(self.style.WARNING(
                f"{self.skipped} ürün-gece stok yetmediği için işlenmedi. Alım girip gün sonunu yeniden çalıştırın "
                "ya da --ikmal ile çalıştırın."))

    def close_day(self, day, first_purchase, closed, restock, totals):
        consumption, rooms, guests = night_consumption(day)
        pending = {item_id: values for item_id, values in consumption.items()
                   if item_id in first_purchase and first_purchase[item_id] <= day and (item_id, day) not in closed}
        if not pending:
            return
        items = InventoryItem.objects.in_bulk(pending.keys())
        note = f"Gün sonu {day:%d.%m.%Y}: {rooms} dolu oda, {guests} kişi (konaklama tüketimi)"
        night_value, posted = D("0"), 0
        for item_id, (net, waste) in sorted(pending.items(), key=lambda pair: items[pair[0]].sku):
            item = items[item_id]
            net, waste = net.quantize(THOUSANDTH), waste.quantize(THOUSANDTH)
            need = net + waste
            if need <= 0:
                continue
            item.refresh_from_db(fields=["current_stock", "average_unit_cost"])
            if restock and item.current_stock - need < item.reorder_level:
                last_price = (item.movements.filter(movement_type=Move.PURCHASE).order_by("-movement_at")
                              .values_list("unit_cost", flat=True).first() or item.average_unit_cost)
                quantity = max(item.reorder_level * 3, need - item.current_stock + item.reorder_level)
                InventoryMovement.objects.create(item=item, movement_type=Move.PURCHASE, quantity=quantity,
                                                 unit_cost=last_price, movement_at=at(day, 23, 58), notes=RESTOCK_NOTE)
                totals["restocks"] += 1
                item.refresh_from_db(fields=["current_stock", "average_unit_cost"])
            if item.current_stock < need:
                self.stdout.write(self.style.WARNING(
                    f"  {day:%d.%m.%Y} {item.sku} {item.name}: gereken {need} {item.unit}, eldeki "
                    f"{item.current_stock}; işlenmedi."))
                self.skipped += 1
                continue
            for movement_type, quantity in ((Move.CONSUMPTION, net), (Move.WASTE, waste)):
                if quantity > 0:
                    InventoryMovement.objects.create(
                        item=item, movement_type=movement_type, quantity=quantity, unit_cost=item.average_unit_cost,
                        movement_at=at(day, 23, 59), consumption_day=day, notes=note)
                    posted += 1
            night_value += need * item.average_unit_cost
        if posted:
            totals["nights"] += 1
            totals["movements"] += posted
            totals["value"] += night_value
            self.stdout.write(f"  {day:%d.%m.%Y}: {rooms} oda, {guests} kişi -> {posted} hareket, {night_value:,.2f} TL")
