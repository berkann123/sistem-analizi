from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from dashboard.models import (
    BreakfastBuffetItem, InventoryItem, InventoryMovement,
    MonthlyExpenseCategory, MonthlyHotelExpense, Room, RoomPackageItem, RoomType,
)

Group = MonthlyExpenseCategory.Group
Behavior = MonthlyExpenseCategory.CostBehavior
Basis = MonthlyExpenseCategory.VariableBasis
Unit = InventoryItem.Unit

DEMO_STOCK_NOTE = "Demo açılış stoku"
DEMO_EXPENSE_NOTE = "Ekran gösterimi için örnek tutar; gerçek gider değildir."

# (kod, ad, oda sayısı, azami misafir, sıralama katsayısı, ilk oda no, manzara)
ROOM_TYPES = [
    # Otelin oda tipleri, ucuzdan pahalıya (kullanıcı bilgisi; pasaportpier.com). Manzara odada tutulur.
    # v90: 5 oda tipi, ucuzdan pahalıya
    ("STD", "Standart Oda", 10, 2, "0.8500", 101, "manzarasiz"),     # en küçük ve en ucuz oda
    ("SUP", "Superior Oda", 20, 2, "1.0000", 201, "kara"),
    ("JRS", "Junior Suite", 10, 2, "1.2000", 601, "sehir"),
    ("EXR", "Executive Oda", 10, 2, "1.5000", 501, "deniz"),
    ("DLX", "Deluxe Oda", 4, 2, "1.8000", 301, "deniz"),             # en pahalı
]
# (ürün kodu, kişi başı miktar, fire)
BREAKFAST_LINES = [("GID-010", "0.0500", "0.0500"), ("GID-011", "0.0200", "0.0700")]
# (ürün kodu, miktar, tüketim esası, fire)
PACKAGE_LINES = [
    ("BKL-001", "0.5000", RoomPackageItem.Basis.PER_ROOM_NIGHT, "0.0500"),
    ("BKL-002", "0.5000", RoomPackageItem.Basis.PER_GUEST_NIGHT, "0.0500"),
    ("MIN-001", "0.3000", RoomPackageItem.Basis.PER_GUEST_NIGHT, "0.0000"),
    ("MIN-002", "0.1500", RoomPackageItem.Basis.PER_GUEST_NIGHT, "0.0000"),
]
# (gider kalemi, grubu, davranış, değişken esası, aylık sabit tutar, değişken birim tutar)
MONTHLY_EXPENSES = [
    ("Kira", Group.BUILDING, Behavior.FIXED, Basis.PER_ROOM_NIGHT, "280000.00", "0"),
    ("Personel giderleri", Group.STAFF, Behavior.FIXED, Basis.PER_ROOM_NIGHT, "720000.00", "0"),
    ("Bakım ve onarım", Group.MAINTENANCE, Behavior.FIXED, Basis.PER_ROOM_NIGHT, "25000.00", "0"),
    ("Bilgi işlem ve iletişim", Group.ADMINISTRATION, Behavior.FIXED, Basis.PER_ROOM_NIGHT, "18000.00", "0"),
    ("Sigorta ve ruhsat", Group.BUILDING, Behavior.FIXED, Basis.PER_ROOM_NIGHT, "14000.00", "0"),
    ("Elektrik", Group.ENERGY, Behavior.SEMI_VARIABLE, Basis.PER_ROOM_NIGHT, "180000.00", "45"),
    ("Su ve atık su", Group.ENERGY, Behavior.SEMI_VARIABLE, Basis.PER_GUEST_NIGHT, "35000.00", "25"),
    ("Doğalgaz", Group.ENERGY, Behavior.SEMI_VARIABLE, Basis.PER_ROOM_NIGHT, "40000.00", "20"),
]


class Command(BaseCommand):
    help = ("Boş bir veritabanına küçük bir ÖRNEK veri kurar (54 oda, birkaç ürün, büfe, paket, giderler). "
            "Testler ve ilk deneme içindir; otelin asıl verisi phpMyAdmin yedeğindedir. Tekrar çalıştırılabilir: "
            "Admin'den düzenlenmiş büfe ve paket içeriklerinin üzerine yazmaz.")

    @transaction.atomic
    def handle(self, *args, **options):
        created_rooms = self._seed_rooms()
        self._seed_inventory()
        self._seed_breakfast()
        self._seed_textiles()
        self._seed_packages()
        self._seed_expenses()
        self.stdout.write(self.style.SUCCESS(
            f"Demo verisi hazır. Toplam oda: {Room.objects.count()}; yeni eklenen oda: {created_rooms}."
        ))

    def _seed_rooms(self):
        created = 0
        for code, name, count, max_guests, factor, first_room, view in ROOM_TYPES:
            room_type, _ = RoomType.objects.update_or_create(
                code=code,
                defaults={"name": name, "max_guests": max_guests,
                          "standard_cost_factor": Decimal(factor), "active": True},
            )
            for offset in range(count):
                number = first_room + offset
                _, was_created = Room.objects.update_or_create(
                    room_number=str(number),
                    defaults={"room_type": room_type, "view_type": view, "floor": number // 100,
                              "status": Room.Status.ACTIVE},
                )
                created += int(was_created)
        # Kullanılmayan eski demo oda tiplerini temizle; odası olanlara dokunma.
        for old_type in RoomType.objects.exclude(code__in=[spec[0] for spec in ROOM_TYPES]):
            if not Room.objects.filter(room_type=old_type).exists():
                old_type.delete()
        return created

    def _seed_inventory(self):
        Category = InventoryItem.Category                  # v93: kategori ürünün alanı, ayrı tablo yok
        food, beverages, amenities = Category.FOOD, Category.DRINK, Category.AMENITY
        kg, pieces = Unit.KILOGRAM, Unit.PIECE
        # (kod, ad, kategori, birim, kritik stok, açılış stoku, KDV hariç birim maliyet)
        demo_items = [
            ("GID-010", "Kahvaltılık peynir", food, kg, "5", "12", "520.00"),
            ("GID-011", "Zeytin", food, kg, "8", "10", "600.00"),
            ("BKL-001", "Şampuan", amenities, pieces, "30", "75", "5.50"),
            ("BKL-002", "Sabun", amenities, pieces, "40", "100", "4.50"),
            ("MIN-001", "Minibar suyu", beverages, pieces, "30", "100", "9.00"),
            ("MIN-002", "Minibar atıştırmalığı", food, pieces, "20", "50", "35.00"),
        ]
        for sku, name, category, unit, reorder, stock, cost in demo_items:
            item, _ = InventoryItem.objects.get_or_create(
                sku=sku,
                defaults={"name": name, "category": category, "unit": unit,
                          "reorder_level": Decimal(reorder), "active": True},
            )
            # Yalnızca hiç hareketi olmayan ürüne açılış stoku yazılır.
            if not item.movements.exists():
                InventoryMovement.objects.create(
                    item=item, movement_type=InventoryMovement.MovementType.PURCHASE,
                    quantity=Decimal(stock), unit_cost=Decimal(cost), notes=DEMO_STOCK_NOTE)

    def _seed_breakfast(self):
        if BreakfastBuffetItem.objects.exists():
            return  # Admin'de düzenlenmiş büfenin üzerine yazma.
        for sku, quantity, waste in BREAKFAST_LINES:
            BreakfastBuffetItem.objects.create(
                item=InventoryItem.objects.get(sku=sku),
                quantity=Decimal(quantity), waste_rate=Decimal(waste),
                notes="Demo kişi başı porsiyon varsayımı.")

    def _seed_textiles(self):
        # Tekstil önce stok kartı olarak açılır; yıpranma bilgileri o karta bire bir bağlı ayrı kayıttır.
        textiles = InventoryItem.Category.TEXTILE
        pieces = Unit.PIECE
        for sku, name, cost, stock, life, basis in (
            ("TXT-901", "Nevresim seti", "450.00", "108", 180, RoomPackageItem.Basis.PER_ROOM_NIGHT),
            ("TXT-902", "Havlu seti", "300.00", "162", 120, RoomPackageItem.Basis.PER_GUEST_NIGHT),
        ):
            item = InventoryItem.objects.filter(name=name).first()
            if item is None:
                item = InventoryItem.objects.create(sku=sku, name=name, category=textiles, unit=pieces,
                                                    reorder_level=Decimal("54"))
                InventoryMovement.objects.create(
                    item=item, movement_type=InventoryMovement.MovementType.PURCHASE,
                    quantity=Decimal(stock), unit_cost=Decimal(cost), notes=DEMO_STOCK_NOTE)
            # v93: yıpranma bilgileri stok kartında. Pakete eklenmeden oda maliyetine girmez.
            if item.textile_life is None:
                item.textile_life, item.textile_salvage_value, item.textile_sets_per_room = life, Decimal("0"), Decimal("1")
                item.save(update_fields=["textile_life", "textile_salvage_value", "textile_sets_per_room"])

    def _seed_packages(self):
        """Oda paketi misafir sayısına göredir (bütün oda tipleri aynı paketle satılır)."""
        most_guests = max((spec[3] for spec in ROOM_TYPES), default=2)
        for guests in range(1, most_guests + 1):
            if RoomPackageItem.objects.filter(guest_count=guests).exists():
                continue  # Admin'de düzenlenmiş paketin üzerine yazma.
            for sku, quantity, basis, waste in PACKAGE_LINES:
                RoomPackageItem.objects.create(
                    guest_count=guests, item=InventoryItem.objects.get(sku=sku),
                    quantity=Decimal(quantity), basis=basis,
                    waste_rate=Decimal(waste), notes="Demo tüketim varsayımı")


    def _seed_expenses(self):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        for name, group, behavior, basis, amount, rate in MONTHLY_EXPENSES:
            category, _ = MonthlyExpenseCategory.objects.get_or_create(
                name=name, defaults={"group": group, "cost_behavior": behavior, "variable_basis": basis, "active": True})
            # Kategoride herhangi bir kayıt varsa (elle girilmiş olabilir) dokunma.
            if not MonthlyHotelExpense.objects.filter(category=category).exists():
                MonthlyHotelExpense.objects.create(
                    category=category, expense_month=month_start, amount=Decimal(amount), variable_rate=Decimal(rate),
                    description=DEMO_EXPENSE_NOTE, recurs_monthly=MonthlyHotelExpense.MonthlyRepeat.YES)
