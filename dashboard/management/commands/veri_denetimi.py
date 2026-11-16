import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count

from dashboard.models import (
    BreakfastBuffetItem, ConsumptionRecipe, InventoryItem, MonthlyExpenseCategory, MonthlyHotelExpense, Room,
    RoomPackageItem, RoomType, Stay,
)
from dashboard.services import effective_month_expenses, last_closed_day

Behavior = MonthlyExpenseCategory.CostBehavior
MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


class Command(BaseCommand):
    help = ("Maliyet hesabını etkileyen veri eksiklerini ve tutarsızlıkları listeler. Hiçbir şeyi değiştirmez; "
            "yalnızca rapor verir.")

    def add_arguments(self, parser):
        parser.add_argument("--yil", type=int, help="Denetlenecek yıl. Varsayılan: içinde bulunulan yıl.")

    def section(self, title):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(title))
        self._section_clean = True

    def warn(self, text):
        self.stdout.write(self.style.WARNING("  [!] ") + text)
        self.warnings += 1
        self._section_clean = False

    def info(self, text):
        self.stdout.write("    " + text)

    def ok(self, text="Sorun yok."):
        if self._section_clean:
            self.stdout.write(self.style.SUCCESS("  [OK] ") + text)

    def handle(self, *args, **options):
        self.year = options.get("yil") or date.today().year
        self.warnings = 0
        self.check_rooms()
        self.check_packages()
        self.check_breakfast()
        self.check_items()
        self.check_expenses()
        self.check_stays()
        self.check_day_close()
        self.stdout.write("")
        if self.warnings:
            self.stdout.write(self.style.WARNING(f"{self.warnings} uyarı var. Uyarılar hata değildir; her biri gözden geçirilmesi gereken bir veridir."))
        else:
            self.stdout.write(self.style.SUCCESS("Veri denetimi temiz: uyarı yok."))

    # ---------------------------------------------------------------------------------------------
    def check_rooms(self):
        self.section("1) Odalar ve oda tipleri")
        active = Room.objects.filter(status=Room.Status.ACTIVE, room_type__active=True)
        self.info(f"{active.count()} satışa açık oda, {RoomType.objects.filter(active=True).count()} oda tipi.")
        for room_type in RoomType.objects.filter(active=True).annotate(n=Count("room")):
            if not room_type.n:
                self.warn(f"{room_type.name}: bu tipte oda yok.")
        factors = sorted(RoomType.objects.filter(active=True).values_list("standard_cost_factor", flat=True))
        if factors and len(set(factors)) == 1 and len(factors) > 1:
            self.warn("Bütün oda tiplerinin maliyet payı katsayısı aynı; ortak giderler eşit dağılıyor.")
        self.ok()

    def check_packages(self):
        self.section("2) Oda paketi (kişi sayısına göre; bütün oda tiplerinde aynı)")
        most_guests = max(RoomType.objects.filter(active=True).values_list("max_guests", flat=True), default=0)
        for guests in range(1, most_guests + 1):
            components = list(RoomPackageItem.objects.filter(guest_count=guests, active=True).select_related("item"))
            if not components:
                self.warn(f"{guests} kişi: oda paketi boş; bu kişi sayısında oda içi ürün maliyeti 0 çıkar.")
                continue
            if not any(component.is_textile for component in components):
                self.warn(f"{guests} kişi: pakette tekstil yok.")
            for component in components:
                source = component.item
                if not source.average_unit_cost:
                    self.warn(f"{guests} kişi: {source.name} maliyeti 0.")
                if not source.active:
                    self.warn(f"{guests} kişi: {source.name} pasif bir ürün.")
            self.info(f"{guests} kişi: {len(components)} kalem.")
        self.ok()

    def check_breakfast(self):
        self.section("3) Kahvaltı büfesi")
        lines = list(BreakfastBuffetItem.objects.filter(active=True).select_related("item"))
        if not lines:
            self.warn("Kahvaltı büfesinde ürün yok; kahvaltı maliyeti 0 çıkar.")
            return
        total = sum((line.line_cost for line in lines), Decimal("0"))
        self.info(f"{len(lines)} ürün, kişi başı {total:.2f} TL.")
        for line in lines:
            if not line.item.average_unit_cost:
                self.warn(f"{line.item.name}: maliyeti 0.")
            if line.item.current_stock <= 0:
                self.warn(f"{line.item.name}: stokta yok.")
            if total and line.line_cost / total > Decimal("0.25"):
                self.warn(f"{line.item.name}: tek başına büfe maliyetinin %{100 * line.line_cost / total:.0f}'i "
                          f"({line.quantity} {line.item.unit} × {line.item.average_unit_cost:.2f} TL). "
                          f"Porsiyonu ve fiyatı gözden geçirin.")
        self.ok()

    def check_items(self):
        self.section("4) Envanter ürünleri")
        in_recipes = set(ConsumptionRecipe.objects.filter(active=True).values_list("item_id", flat=True))
        unused = []
        for item in InventoryItem.objects.filter(active=True).annotate(n=Count("movements")):
            used = item.id in in_recipes
            if item.supplier_id is None:
                self.warn(f"{item.sku} {item.name}: tedarikçisi boş.")
            if item.average_unit_cost and not item.n and used:
                self.warn(f"{item.sku} {item.name}: maliyeti var ama stok hareketi yok (maliyetin kaynağı belli değil).")
            if not item.average_unit_cost and used:
                self.warn(f"{item.sku} {item.name}: reçetede kullanılıyor ama maliyeti 0.")
            if not used:
                unused.append(item.name)
        if unused:
            self.info(f"{len(unused)} ürün hiçbir reçetede (büfe / oda paketi) kullanılmıyor; oda maliyetine girmez: "
                      + ", ".join(unused))
        self.ok()

    def check_expenses(self):
        self.section(f"5) Aylık giderler ({self.year})")
        for category in MonthlyExpenseCategory.objects.filter(active=True).annotate(n=Count("monthlyhotelexpense")):
            if not category.n:
                self.warn(f"{category.name}: hiç gider kaydı yok.")
        for expense in MonthlyHotelExpense.objects.filter(recurring_until__isnull=False).select_related("category"):
            self.warn(f"{expense.category.name} ({expense.expense_month:%m.%Y}): tekrar bitiş tarihi {expense.recurring_until:%d.%m.%Y}; "
                      f"bu tarihten sonra gider hesaba girmez. Süresiz bir giderse alanı boşaltın.")
        counts, totals = [], []
        all_names = set()
        by_month = {}
        for month in range(1, 13):
            expenses = effective_month_expenses(self.year, month)
            by_month[month] = {expense.category.name for expense in expenses}
            all_names |= by_month[month]
            counts.append(len(expenses))
            totals.append(sum((expense.amount for expense in expenses), Decimal("0")))
            for expense in expenses:
                if expense.category.cost_behavior == Behavior.SEMI_VARIABLE and (not expense.amount or not expense.variable_rate):
                    eksik = "sabit tabanı" if not expense.amount else "değişken tutarı"
                    self.warn(f"{expense.category.name} ({MONTHS[month - 1]}): yarı değişken kalemin {eksik} 0.")
        for name in sorted(all_names):
            missing = [MONTHS[month - 1] for month in range(1, 13) if name not in by_month[month]]
            if missing:
                self.warn(f"{name}: şu aylarda geçerli kayıt yok: {', '.join(missing)}.")
        self.info("Ay               : " + " ".join(f"{name:>6}" for name in MONTHS))
        self.info("Geçerli kalem    : " + " ".join(f"{count:>6}" for count in counts))
        self.info("Sabit tutar (bin): " + " ".join(f"{total / 1000:>6.0f}" for total in totals))
        for required in ("Personel", "Elektrik", "Kira", "amortisman"):
            if not any(required.lower() in name.lower() for name in all_names):
                self.warn(f"Adında '{required}' geçen bir gider kalemi yok.")
        self.ok()

    def check_day_close(self):
        self.section("7) Gün sonu (konaklamadan stok tüketimi)")
        last = last_closed_day()
        today = date.today()
        if last is None:
            self.warn("Gün sonu hiç çalıştırılmamış: konaklamaların tüketimi stoktan düşülmüyor (gun_sonu komutu).")
        elif last < today - timedelta(days=1):
            self.warn(f"Son gün sonu {last:%d.%m.%Y}; sonraki geceler stoktan düşülmedi (gun_sonu komutu).")
        else:
            self.info(f"Son gün sonu: {last:%d.%m.%Y}.")
        critical = [item.name for item in InventoryItem.objects.filter(active=True) if item.is_critical]
        if critical:
            self.warn(f"{len(critical)} ürün kritik stok seviyesinde ya da altında: " + ", ".join(critical))
        self.ok()

    def check_stays(self):
        self.section(f"6) Konaklamalar ve doluluk ({self.year})")
        rooms = Room.objects.filter(status=Room.Status.ACTIVE, room_type__active=True).count()
        rates, empty = [], []
        for month in range(1, 13):
            start = date(self.year, month, 1)
            days = calendar.monthrange(self.year, month)[1]
            end = date(self.year + (month == 12), month % 12 + 1, 1)
            nights = sum((min(check_out, end) - max(check_in, start)).days for check_in, check_out in
                         Stay.objects.occupying().filter(check_in__lt=end, check_out__gt=start).values_list("check_in", "check_out"))
            rates.append(100 * nights / (rooms * days) if rooms else 0)
            if not nights:
                empty.append(MONTHS[month - 1])
        if empty:
            self.warn(f"Konaklama kaydı olmayan aylar: {', '.join(empty)}. Bu ayların doluluğu ve satılan oda başına "
                      f"maliyeti hesaplanamaz.")
        self.info("Ay        : " + " ".join(f"{name:>5}" for name in MONTHS))
        self.info("Doluluk % : " + " ".join(f"{rate:>5.0f}" for rate in rates))
        year_stays = Stay.objects.occupying().filter(check_in__year=self.year)
        unpriced = year_stays.filter(nightly_rate__isnull=True).count()
        if unpriced:
            self.warn(f"{unpriced} onaylı konaklamanın gecelik fiyatı girilmemiş; bu geceler gelire girmez "
                      f"(satis_fiyati_yukle komutu ya da admin).")
        self.ok()
