"""Otomatik testler. Çalıştırmak için:  python manage.py test

Her test, bulunup düzeltilen bir hatanın geri gelmesini engeller (regresyon testi).
Testler `test_<veritabanı adı>` adlı geçici bir veritabanında çalışır; gerçek veriye dokunmaz.
"""
from datetime import date, datetime, timedelta, timezone as tz
from decimal import Decimal as D
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, connections, router, transaction
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

# Ortak gider gece payı yıllık esasla: aylık tutar ÷ (oda × 365/12 gün). 10 odalı test otelinde payda 304,17.
MONTH_DAYS = 365 / 12

from .models import (
    BreakfastBuffetItem, InventoryItem,
    InventoryMovement, MonthlyExpenseCategory, MonthlyHotelExpense, PurchaseOrder, Room, RoomPackageItem,
    RoomType, Season, SalesChannel, ClosedPeriod, Event, TaxRate, PricingRules,
    Supplier,
    Stay,
)
from .fiyat_motoru import FiyatMotoru, channel_price
from .services import (
    monthly_overview, auto_close_months, close_month, expected_occupancy, price_calendar, price_status,
    guest_price, price_for_guests, tax_rates, booking_pace, month_sales, pricing_overview,
    average_stay_nights, calculate_monthly_room_cost, calculate_stay_quote, effective_month_expenses,
    get_stock_summary, month_occupancy, normal_occupancy, occupied_room_ids, PRICE_STATUS, night_reason, nightly_occupancy, stay_price_quote, reservation_overview, abnormal_idle_cost, type_normal_occupancy, month_absorption, absorption_window, complete_closed_costs, overview_totals, price_overview, night_factors,
)
from . import fiyat_kurallari as kural
from .stock import replay_movements

Move = InventoryMovement.MovementType


def make_item(sku="TST-001", **extra):
    extra.setdefault("category", InventoryItem.Category.CLEANING)            # gıda dışı (v93: kategori ürünün alanı)
    return InventoryItem.objects.create(sku=sku, name=f"Ürün {sku}", unit="adet", **extra)


def set_rate(room_type, season, price):
    """Oda tipinin bir mevsimdeki piyasa fiyatı (v93: oda tipinde kış / geçiş / yaz alanı)."""
    setattr(room_type, RoomType.SEASON_FIELDS[season], D(price))
    room_type.save()


def set_all_rates(room_type, price):
    for season in RoomType.SEASON_FIELDS:
        setattr(room_type, RoomType.SEASON_FIELDS[season], D(price))
    room_type.save()


def make_category(name, behavior="sabit", group="diger", basis="oda_gecesi"):
    return MonthlyExpenseCategory.objects.create(name=name, group=group, cost_behavior=behavior,
                                                 variable_basis=basis)


def move(item, movement_type, quantity, unit_cost="0"):
    return InventoryMovement.objects.create(
        item=item, movement_type=movement_type, quantity=D(quantity), unit_cost=D(unit_cost))


class MovingAverageTests(SimpleTestCase):
    """Düzeltme 3: hareketli ağırlıklı ortalama (veritabanı gerektirmez)."""

    def test_stock_emptied_then_repurchased_uses_new_price(self):
        stock, average = replay_movements([("alim", D(10), D(100)), ("tuketim", D(10), D(0)), ("alim", D(10), D(200))])
        self.assertEqual(stock, D(10))
        self.assertEqual(average, D("200.0000"))  # eski yöntem 150 veriyordu

    def test_purchase_is_weighted_by_remaining_stock(self):
        # 10 adet × 100 TL; 6 tüket (kalan 4 × 100); 12 adet × 200 al -> (400 + 2400) / 16 = 175
        stock, average = replay_movements([("alim", D(10), D(100)), ("tuketim", D(6), D(0)), ("alim", D(12), D(200))])
        self.assertEqual((stock, average), (D(16), D("175.0000")))

    def test_consumption_and_adjustment_do_not_change_average(self):
        stock, average = replay_movements([("alim", D(10), D(50)), ("fire", D(2), D(0)), ("sayim_duzeltme", D(-1), D(0))])
        self.assertEqual((stock, average), (D(7), D("50.0000")))

    def test_without_purchases_existing_cost_is_kept(self):
        self.assertEqual(replay_movements([], fallback_cost=D("12.5")), (D(0), D("12.5000")))


class InventoryIntegrityTests(TestCase):
    """Düzeltme 6, 7 ve 9."""

    def setUp(self):
        self.item = make_item()

    def test_item_totals_follow_movements(self):
        move(self.item, Move.PURCHASE, "10", "100")
        move(self.item, Move.CONSUMPTION, "4")
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock, D("6.000"))
        self.assertEqual(self.item.average_unit_cost, D("100.0000"))

    def test_stock_cannot_go_negative(self):
        move(self.item, Move.PURCHASE, "5", "10")
        with self.assertRaises(ValidationError):
            move(self.item, Move.CONSUMPTION, "6")

    def test_negative_quantity_and_cost_are_rejected(self):
        with self.assertRaises(ValidationError):
            move(self.item, Move.PURCHASE, "-5", "10")
        with self.assertRaises(ValidationError):
            move(self.item, Move.PURCHASE, "5", "-10")
        with self.assertRaises(ValidationError):
            move(self.item, Move.PURCHASE, "0", "10")

    def test_database_also_rejects_invalid_rows(self):
        # update() doğrulamayı atlar; son savunma hattı veritabanındaki CHECK kısıtıdır.
        movement = move(self.item, Move.PURCHASE, "5", "10")
        with self.assertRaises(IntegrityError), transaction.atomic():
            InventoryMovement.objects.filter(pk=movement.pk).update(quantity=D("-1"))

    def test_count_adjustment_may_be_negative_but_not_below_zero_stock(self):
        move(self.item, Move.PURCHASE, "5", "10")
        move(self.item, Move.COUNT_ADJUSTMENT, "-2")
        self.item.refresh_from_db()
        self.assertEqual(self.item.current_stock, D("3.000"))
        with self.assertRaises(ValidationError):
            move(self.item, Move.COUNT_ADJUSTMENT, "-10")

    def test_item_with_movements_cannot_be_deleted(self):
        move(self.item, Move.PURCHASE, "5", "10")
        with self.assertRaises(ProtectedError):
            self.item.delete()
        self.assertEqual(InventoryMovement.objects.count(), 1)

    def test_movement_can_be_backdated(self):
        when = datetime(2026, 9, 1, 10, 0, tzinfo=tz.utc)
        movement = InventoryMovement.objects.create(
            item=self.item, movement_type=Move.PURCHASE, quantity=D(1), unit_cost=D(1), movement_at=when)
        movement.refresh_from_db()
        self.assertEqual(movement.movement_at, when)
        self.assertNotEqual(movement.created_at, when)

    def test_backdated_purchase_is_replayed_in_date_order(self):
        move(self.item, Move.PURCHASE, "10", "200")
        InventoryMovement.objects.create(
            item=self.item, movement_type=Move.PURCHASE, quantity=D(10), unit_cost=D(100),
            movement_at=datetime(2020, 1, 1, tzinfo=tz.utc))
        self.item.refresh_from_db()
        self.assertEqual(self.item.average_unit_cost, D("150.0000"))

    def test_room_number_is_unique(self):
        room_type = RoomType.objects.create(code="T1", name="Test", max_guests=2)
        Room.objects.create(room_type=room_type, room_number="101")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Room.objects.create(room_type=room_type, room_number="101")

    def test_stock_summary_reports_value_and_critical_items(self):
        low = make_item("TST-002", reorder_level=D(10))
        move(low, Move.PURCHASE, "4", "25")
        summary = get_stock_summary()
        self.assertEqual(summary["critical_count"], 2)  # setUp'taki stoksuz ürün de kritik
        self.assertEqual(summary["stock_value"], D("100.0000000"))


class ExpenseRuleTests(TestCase):
    """Düzeltme 2: tekrarlayan gider + yeni ay kaydı iki kez sayılmaz."""

    def setUp(self):
        self.rent = make_category("Kira")
        self.staff = make_category("Personel")
        MonthlyHotelExpense.objects.create(category=self.rent, expense_month=date(2026, 10, 1),
                                           amount=D("280000"), recurs_monthly="evet")
        MonthlyHotelExpense.objects.create(category=self.staff, expense_month=date(2026, 10, 1),
                                           amount=D("720000"), recurs_monthly="evet")

    def total(self, year, month):
        return sum(expense.amount for expense in effective_month_expenses(year, month))

    def test_recurring_expense_carries_forward(self):
        self.assertEqual(self.total(2026, 10), D("1000000"))
        self.assertEqual(self.total(2027, 1), D("1000000"))
        self.assertEqual(self.total(2026, 9), D("0"))  # başlamadan önceki aya yansımaz

    def test_new_month_record_replaces_recurring_one(self):
        MonthlyHotelExpense.objects.create(category=self.rent, expense_month=date(2026, 11, 1),
                                           amount=D("300000"), recurs_monthly="evet")
        self.assertEqual(self.total(2026, 10), D("1000000"))
        self.assertEqual(self.total(2026, 11), D("1020000"))  # eski hata: 1.300.000
        self.assertEqual(self.total(2026, 12), D("1020000"))  # zamlı kira devreder

    def test_one_off_record_applies_only_to_its_month(self):
        MonthlyHotelExpense.objects.create(category=self.rent, expense_month=date(2026, 11, 1),
                                           amount=D("300000"), recurs_monthly="hayir")
        self.assertEqual(self.total(2026, 11), D("1020000"))
        self.assertEqual(self.total(2026, 12), D("1000000"))

    def test_recurring_until_stops_the_expense(self):
        MonthlyHotelExpense.objects.filter(category=self.staff).update(recurring_until=date(2026, 12, 31))
        self.assertEqual(self.total(2026, 12), D("1000000"))
        self.assertEqual(self.total(2027, 1), D("280000"))

    def test_same_item_cannot_be_entered_twice_for_a_month(self):
        # Veritabanı düzeyinde: aynı kalem + aynı ay ikinci kez yazılamaz.
        with self.assertRaises(IntegrityError), transaction.atomic():
            MonthlyHotelExpense.objects.create(category=self.rent, expense_month=date(2026, 10, 1), amount=D("5000"))
        # Form düzeyinde: ayın başka bir günü girilse de aynı ay olarak yakalanır.
        with self.assertRaises(ValidationError):
            MonthlyHotelExpense(category=self.rent, expense_month=date(2026, 10, 15), amount=D("5000")).full_clean()
        # Farklı ay tekrar değil, tutarın geçmişidir.
        MonthlyHotelExpense(category=self.rent, expense_month=date(2026, 11, 15), amount=D("5000")).full_clean()

    def test_expense_month_is_stored_as_first_day(self):
        expense = MonthlyHotelExpense.objects.create(category=self.rent, expense_month=date(2026, 12, 17), amount=D(1))
        self.assertEqual(expense.expense_month, date(2026, 12, 1))


class CostBehaviorTests(TestCase):
    """Üç maliyet davranışı: sabit, yarı değişken, değişken."""

    def setUp(self):
        self.room_type = RoomType.objects.create(code="T1", name="Test", max_guests=2)
        for number in range(1, 11):                      # 10 oda × 30 gün (Kasım) = 300 müsait oda-gece
            Room.objects.create(room_type=self.room_type, room_number=str(100 + number))
        self.month = date(2026, 11, 1)
        Behavior = MonthlyExpenseCategory.CostBehavior
        self.rent = make_category("Kira", Behavior.FIXED, group="bina")
        self.staff = make_category("Personel", Behavior.SEMI_VARIABLE, group="personel")
        self.laundry = make_category("Dış çamaşırhane", Behavior.VARIABLE, group="diger")
        MonthlyHotelExpense.objects.create(category=self.rent, expense_month=self.month, amount=D("30000"))
        MonthlyHotelExpense.objects.create(category=self.staff, expense_month=self.month, amount=D("60000"),
                                           variable_rate=D("80"))
        MonthlyHotelExpense.objects.create(category=self.laundry, expense_month=self.month, variable_rate=D("40"))

    def quote(self, **extra):
        return calculate_stay_quote(self.room_type, 1, date(2026, 11, 10), date(2026, 11, 12), **extra)

    def test_each_behavior_is_charged_its_own_way(self):
        totals = self.quote()["totals"]                   # 2 gece
        self.assertAlmostEqual(float(totals["fixed"]), 2 * 30000 / (10 * MONTH_DAYS), places=6)       # 98,63 × 2 gece
        self.assertAlmostEqual(float(totals["semi_fixed"]), 2 * 60000 / (10 * MONTH_DAYS), places=6)  # 197,26 × 2 gece
        self.assertEqual(totals["variable_overhead"], D("240"))  # (80 + 40) TL × 2 gece, bölünmez

    def test_variable_part_raises_the_price_floor(self):
        quote = self.quote()
        self.assertEqual(quote["variable_total"], D("240"))     # başka değişken maliyet tanımlı değil
        self.assertAlmostEqual(float(quote["grand_total"]), 240 + 2 * 90000 / (10 * MONTH_DAYS), places=6)
        self.assertEqual(quote["grand_total"], quote["variable_total"] + quote["cost_groups"]["monthly_shared"])

    def test_occupancy_scales_only_the_fixed_parts(self):
        quote = self.quote(expected_occupancy=D("0.5"))
        # Sabit + taban iki katına çıkar; değişken kısım (240) aynı kalır.
        self.assertAlmostEqual(float(quote["at_occupancy"]["grand_total"]), 240 + 2 * 2 * 90000 / (10 * MONTH_DAYS), places=6)

    def test_idle_capacity_covers_fixed_and_semi_fixed_base_but_not_variable(self):
        # 10 odanın 4'ü Kasım boyunca dolu: doluluk %40.
        for room in Room.objects.order_by("room_number")[:4]:
            Stay.objects.create(room=room, check_in=date(2026, 11, 1), check_out=date(2026, 12, 1))
        summary = calculate_monthly_room_cost(2026, 11, as_of=date(2026, 12, 15))
        self.assertEqual(summary["fixed_monthly_total"], D("30000"))
        self.assertEqual(summary["semi_fixed_monthly_total"], D("60000"))
        self.assertEqual(summary["variable_room"], D("120"))
        self.assertEqual(summary["occupancy"]["idle_capacity_cost"], D("54000"))   # 90.000 × (1 − 0,40)

    def test_energy_is_a_group_of_semi_variable_items(self):
        # Enerji giderleri: otel boşken de gelen fatura (taban) + misafirle artan tüketim (değişken).
        Behavior, Basis = MonthlyExpenseCategory.CostBehavior, MonthlyExpenseCategory.VariableBasis
        electricity = make_category("Elektrik", Behavior.SEMI_VARIABLE, group="enerji")
        water = make_category("Su", Behavior.SEMI_VARIABLE, group="enerji", basis=Basis.PER_GUEST_NIGHT)
        MonthlyHotelExpense.objects.create(category=electricity, expense_month=self.month, amount=D("9000"),
                                           variable_rate=D("70"))
        MonthlyHotelExpense.objects.create(category=water, expense_month=self.month, amount=D("3000"),
                                           variable_rate=D("50"))
        one_guest = calculate_stay_quote(self.room_type, 1, date(2026, 11, 10), date(2026, 11, 11))
        two_guests = calculate_stay_quote(self.room_type, 2, date(2026, 11, 10), date(2026, 11, 11))
        # Taban: (60.000 + 9.000 + 3.000) ÷ (10 oda × 365/12) TL; kişi sayısıyla değişmez.
        self.assertAlmostEqual(float(one_guest["totals"]["semi_fixed"]), 72000 / (10 * MONTH_DAYS), places=6)
        self.assertEqual(two_guests["totals"]["semi_fixed"], one_guest["totals"]["semi_fixed"])
        # Değişken: oda başına 80 + 40 + 70 = 190 TL; kişi başına 50 TL.
        self.assertEqual(one_guest["totals"]["variable_overhead"], D("240"))
        self.assertEqual(two_guests["totals"]["variable_overhead"], D("290"))   # ikinci misafir yalnızca suyu artırır

        energy = next(group for group in calculate_monthly_room_cost(2026, 11)["expense_groups"]
                      if group["name"] == "Enerji giderleri")
        self.assertEqual(energy["fixed"], D("12000"))
        self.assertEqual((energy["variable_room"], energy["variable_guest"]), (D("70"), D("50")))
        self.assertEqual([line["name"] for line in energy["lines"]], ["Elektrik", "Su"])

    def test_expense_must_match_its_category_behavior(self):
        with self.assertRaises(ValidationError):   # sabit kalemde değişken tutar olmaz
            MonthlyHotelExpense(category=self.rent, expense_month=self.month, amount=D(1), variable_rate=D(5)).full_clean()
        with self.assertRaises(ValidationError):   # değişken kalemde aylık sabit tutar olmaz
            MonthlyHotelExpense(category=self.laundry, expense_month=self.month, amount=D(100), variable_rate=D(5)).full_clean()
        with self.assertRaises(ValidationError):   # değişken kalemde birim tutar zorunlu
            MonthlyHotelExpense(category=self.laundry, expense_month=self.month).full_clean()
        MonthlyHotelExpense(category=self.staff, expense_month=date(2026, 12, 1), amount=D(1), variable_rate=D(5)).full_clean()

    def test_category_behavior_cannot_contradict_existing_expenses(self):
        self.staff.cost_behavior = MonthlyExpenseCategory.CostBehavior.FIXED
        with self.assertRaises(ValidationError):   # kayıtlarında değişken tutar var
            self.staff.full_clean()
        self.staff.cost_behavior = MonthlyExpenseCategory.CostBehavior.VARIABLE
        with self.assertRaises(ValidationError):   # kayıtlarında sabit taban var
            self.staff.full_clean()
        self.rent.cost_behavior = MonthlyExpenseCategory.CostBehavior.SEMI_VARIABLE
        self.rent.full_clean()                     # sabit -> yarı değişken her zaman mümkün


class CostEngineTests(TestCase):
    """Düzeltme 1, 4 ve 12: seed_demo verisiyle uçtan uca hesap."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", stdout=StringIO())
        cls.room_type = RoomType.objects.get(code="SUP")
        today = date.today()
        cls.check_in = date(today.year, today.month, 1)
        cls.check_out = date(today.year, today.month, 3)

    def quote(self, **extra):
        return calculate_stay_quote(self.room_type, 2, self.check_in, self.check_out, **extra)

    def test_demo_has_54_active_rooms(self):
        self.assertEqual(Room.objects.filter(status=Room.Status.ACTIVE).count(), 54)

    def test_buffet_screen_drives_breakfast_cost(self):
        before = self.quote()["totals"]["breakfast"]
        self.assertGreater(before, 0)
        line = BreakfastBuffetItem.objects.filter(active=True).first()
        line.quantity *= 10
        line.save()
        self.assertGreater(self.quote()["totals"]["breakfast"], before)  # eski hata: değişmiyordu

    def test_quote_total_is_sum_of_parts(self):
        quote = self.quote()
        self.assertEqual(quote["nights"], 2)
        self.assertEqual(quote["grand_total"], sum(quote["totals"].values()))
        # İki farklı toplama sırası; ondalık hassasiyetin son basamağında (10^-24) fark olabilir: kuruşa yuvarlanır.
        self.assertEqual(round(quote["grand_total"], 6),
                         round(quote["variable_total"] + quote["cost_groups"]["monthly_shared"], 6))

    def test_lower_occupancy_raises_cost_per_sold_room(self):
        quote = self.quote(expected_occupancy=D("0.5"))
        shared = quote["cost_groups"]["monthly_shared"]
        self.assertEqual(quote["at_occupancy"]["monthly_shared"], shared * 2)
        self.assertGreater(quote["at_occupancy"]["grand_total"], quote["grand_total"])

    def test_monthly_report_shows_idle_capacity_when_stays_exist(self):
        today = date.today()
        month_start = today.replace(day=1)
        next_month = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        Stay.objects.all().delete()
        summary = calculate_monthly_room_cost(today.year, today.month)
        self.assertIsNone(summary["occupancy"])            # konaklama yoksa "veri yok", %0 değil
        # 54 odanın 27'si ay boyunca dolu: doluluk %50.
        for room in Room.objects.order_by("room_number")[:27]:
            Stay.objects.create(room=room, check_in=month_start, check_out=next_month)
        summary = calculate_monthly_room_cost(today.year, today.month, as_of=next_month)
        occupancy = summary["occupancy"]
        self.assertEqual(occupancy["rate"], D("0.5"))
        # Sabit giderler + yarı değişken tabanlar (demo veride enerji tabanı) birlikte değerlendirilir.
        fixed_and_base = summary["fixed_monthly_total"] + summary["semi_fixed_monthly_total"]
        per_available_night = fixed_and_base / (54 * summary["days"])
        self.assertAlmostEqual(occupancy["fixed_per_sold_night"], per_available_night * 2, places=6)
        self.assertEqual(occupancy["idle_capacity_cost"], fixed_and_base / 2)

    def test_quote_uses_few_queries_regardless_of_length(self):
        # Bir yıllık (365 gece) teklifte bile sorgu sayısı gece sayısıyla artmamalı:
        # her ay için 1 gider sorgusu + sabit birkaç sorgu. Eski sürüm 30 gecede 196 sorgu atıyordu.
        one_year_later = date(self.check_in.year + 1, self.check_in.month, 1)
        with CaptureQueriesContext(connection) as queries:
            calculate_stay_quote(self.room_type, 2, self.check_in, one_year_later)
        self.assertLess(len(queries), 25)

    def test_seed_demo_can_run_twice_without_overwriting(self):
        line = BreakfastBuffetItem.objects.filter(active=True).first()
        line.quantity = D("0.1234")
        line.save()
        counts = (InventoryMovement.objects.count(), Room.objects.count(), MonthlyHotelExpense.objects.count())
        call_command("seed_demo", stdout=StringIO())
        line.refresh_from_db()
        self.assertEqual(line.quantity, D("0.1234"))
        self.assertEqual(counts, (InventoryMovement.objects.count(), Room.objects.count(), MonthlyHotelExpense.objects.count()))


class AccessTests(TestCase):
    """Düzeltme 12: maliyet ekranları giriş ister."""
    # Kullanıcı ve oturum tabloları "sistem" veritabanındadır; bu testler iki veritabanını da kullanır.
    databases = {"default", "sistem"}
    PAGES = ("home", "cost_report", "stock_analysis", "reservation_cost")

    def test_anonymous_user_is_redirected_to_login(self):
        for name in self.PAGES:
            response = self.client.get(reverse(name))
            self.assertRedirects(response, f"{reverse('login')}?next={reverse(name)}", msg_prefix=name)

    def test_logged_in_user_sees_pages(self):
        user = get_user_model().objects.create_user("deneme", password="Guclu-Parola-2026")
        self.client.force_login(user)
        for name in self.PAGES:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_home_cards_link_to_their_screens(self):
        """Ana sayfa: maliyet, fiyat ve satış, stok kartları ilgili ekrana götürür."""
        user = get_user_model().objects.create_user("deneme", password="Guclu-Parola-2026")
        self.client.force_login(user)
        response = self.client.get(reverse("home"))
        self.assertTrue(response.context["database_ready"])
        for name in ("cost_report", "price_calendar", "stock_analysis"):
            self.assertContains(response, f'href="{reverse(name)}"', msg_prefix=name)
        self.assertEqual(set(response.context["summary"]), {"cost", "sales", "stock", "today"})


class RelationTests(TestCase):
    """Eksik ilişkiler: tedarikçi tablosu ve tekstil -> envanter ürünü bağı."""

    def test_supplier_with_items_cannot_be_deleted(self):
        supplier = Supplier.objects.create(name="Ege Buklet")
        item = make_item("TST-010", supplier=supplier)
        self.assertEqual(list(supplier.items.all()), [item])
        with self.assertRaises(ProtectedError):
            supplier.delete()

    def test_supplier_name_is_unique(self):
        Supplier.objects.create(name="Ege Buklet")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Supplier.objects.create(name="Ege Buklet")

    def test_textile_cost_comes_from_its_stock_card(self):
        """v93: tekstil yıpranma bilgileri stok kartında; maliyet hareketli ortalamadan gelir."""
        item = make_item("TXT-900", category=InventoryItem.Category.TEXTILE, textile_life=100)
        move(item, Move.PURCHASE, "10", "450")
        item.refresh_from_db()
        self.assertTrue(item.is_textile)
        self.assertEqual(item.textile_cost_per_set_night, D("4.5"))     # 450 / 100
        # Daha pahalıya yeni alım yapılınca yıpranma payı kendiliğinden güncellenir: (4500 + 5500) / 20 = 500
        move(item, Move.PURCHASE, "10", "550")
        item.refresh_from_db()
        self.assertEqual(item.textile_cost_per_set_night, D("5"))
        line = RoomPackageItem.objects.create(guest_count=2, item=item, quantity=D("1"), basis="oda_gecesi")
        with self.assertRaises(ProtectedError):
            item.delete()
        self.assertEqual(line.line_cost, D("5"))

    def test_recipe_row_is_unique_per_basis_guest_and_item(self):
        item = make_item("TXT-901", textile_life=100)
        RoomPackageItem.objects.create(guest_count=2, item=item, quantity=D("1"), basis="oda_gecesi")
        with self.assertRaises(IntegrityError), transaction.atomic():
            RoomPackageItem.objects.create(guest_count=2, item=item, quantity=D("2"), basis="oda_gecesi")

    def test_salvage_above_cost_never_gives_negative_depreciation(self):
        item = make_item("TXT-902", textile_life=10, textile_salvage_value=D(150))
        move(item, Move.PURCHASE, "1", "100")
        item.refresh_from_db()
        self.assertEqual(item.textile_cost_per_set_night, D(0))

    def test_guest_based_textile_scales_with_guests(self):
        from .services import _room_package_cost
        item = make_item("TXT-903", textile_life=100)
        move(item, Move.PURCHASE, "1", "300")
        RoomPackageItem.objects.create(guest_count=3, item=item, quantity=D("1"), basis="kisi_gecesi")
        room_type = RoomType.objects.create(code="TX3", name="Tekstil test", max_guests=3)
        self.assertEqual(_room_package_cost(3, room_type)[3], D(9))       # 300 / 100 × 3 kişi

    def test_breakfast_and_package_share_one_recipe_table(self):
        """v93: kahvaltı büfesi ve oda paketi aynı tablonun (standart_tuketim) iki görünümü."""
        from .models import ConsumptionRecipe
        item = make_item("REC-1")
        BreakfastBuffetItem.objects.create(item=item, quantity=D("2"))
        RoomPackageItem.objects.create(guest_count=1, item=item, quantity=D("1"))
        self.assertEqual(ConsumptionRecipe._meta.db_table, "standart_tuketim")
        self.assertEqual(BreakfastBuffetItem._meta.db_table, "standart_tuketim")
        self.assertEqual(sorted(ConsumptionRecipe.objects.values_list("basis", flat=True)), ["kahvalti", "kisi_gecesi"])
        self.assertEqual(BreakfastBuffetItem.objects.count(), 1)
        self.assertEqual(RoomPackageItem.objects.count(), 1)


class DatabaseSplitTests(TestCase):
    """Django'nun kendi tabloları otel veritabanında değil, ayrı `sistem` veritabanında durur."""
    databases = {"default", "sistem"}

    def test_models_are_routed_to_the_right_database(self):
        self.assertEqual(router.db_for_write(get_user_model()), "sistem")
        self.assertEqual(router.db_for_read(InventoryItem), "default")

    def test_hotel_database_contains_no_django_tables(self):
        hotel_tables = set(connections["default"].introspection.table_names())
        system_tables = set(connections["sistem"].introspection.table_names())
        self.assertIn("odalar", hotel_tables)
        self.assertIn("auth_user", system_tables)
        # django_migrations Django'nun her veritabanında tuttuğu kayıt tablosudur; tek istisna odur.
        leaked = {name for name in hotel_tables if name.startswith(("auth_", "django_"))} - {"django_migrations"}
        self.assertEqual(leaked, set())
        self.assertNotIn("odalar", system_tables)


class StayTests(TestCase):
    """Doluluk, odalara bağlı konaklama kayıtlarından türetilir."""

    def setUp(self):
        self.room_type = RoomType.objects.create(code="T2", name="Test çift kişilik", max_guests=2)
        self.rooms = [Room.objects.create(room_type=self.room_type, room_number=str(200 + n)) for n in range(1, 5)]
        self.room = self.rooms[0]

    def stay(self, room, check_in, check_out, guests=1):
        return Stay.objects.create(room=room, check_in=check_in, check_out=check_out, guests=guests)

    def test_room_is_occupied_from_check_in_until_the_night_before_check_out(self):
        self.stay(self.room, date(2026, 10, 10), date(2026, 10, 12))
        self.assertFalse(self.room.is_occupied_on(date(2026, 10, 9)))
        self.assertTrue(self.room.is_occupied_on(date(2026, 10, 10)))
        self.assertTrue(self.room.is_occupied_on(date(2026, 10, 11)))
        self.assertFalse(self.room.is_occupied_on(date(2026, 10, 12)))    # çıkış günü oda yeniden boştur
        self.assertEqual(occupied_room_ids(date(2026, 10, 11)), {self.room.pk})

    def test_same_room_cannot_be_booked_twice_for_the_same_night(self):
        self.stay(self.room, date(2026, 10, 10), date(2026, 10, 12))
        with self.assertRaises(ValidationError):
            self.stay(self.room, date(2026, 10, 11), date(2026, 10, 13))
        self.stay(self.room, date(2026, 10, 12), date(2026, 10, 14))      # çıkış günü yeni giriş olabilir
        self.stay(self.rooms[1], date(2026, 10, 10), date(2026, 10, 12))  # başka oda aynı tarihte olabilir

    def test_invalid_stays_are_rejected(self):
        with self.assertRaises(ValidationError):   # çıkış girişten sonra olmalı
            self.stay(self.room, date(2026, 10, 12), date(2026, 10, 12))
        with self.assertRaises(ValidationError):   # oda kapasitesi 2
            self.stay(self.room, date(2026, 10, 1), date(2026, 10, 2), guests=3)
        self.rooms[2].status = Room.Status.MAINTENANCE
        self.rooms[2].save()
        with self.assertRaises(ValidationError):   # bakımdaki oda satılamaz
            self.stay(self.rooms[2], date(2026, 10, 1), date(2026, 10, 2))

    def test_room_with_stays_cannot_be_deleted(self):
        self.stay(self.room, date(2026, 10, 10), date(2026, 10, 12))
        with self.assertRaises(ProtectedError):
            self.room.delete()

    def test_monthly_occupancy_counts_only_nights_inside_the_month(self):
        # Konaklama 29 Eylül - 3 Ekim: Ekim'e yalnızca 1 ve 2 Ekim geceleri düşer.
        self.stay(self.room, date(2026, 9, 29), date(2026, 10, 3), guests=2)
        self.stay(self.rooms[1], date(2026, 10, 30), date(2026, 11, 2))     # Ekim'e 30 ve 31 Ekim düşer
        result = month_occupancy(2026, 10, as_of=date(2026, 12, 1))
        self.assertEqual(result["occupied_room_nights"], 4)
        self.assertEqual(result["available_room_nights"], 4 * 31)
        self.assertEqual(result["guest_nights"], 2 * 2 + 2 * 1)
        self.assertEqual(result["rate"], D(4) / D(124))

    def test_current_month_is_measured_up_to_today(self):
        self.stay(self.room, date(2026, 10, 1), date(2026, 10, 11))         # 10 gece
        result = month_occupancy(2026, 10, as_of=date(2026, 10, 10))        # ayın 10. günü
        self.assertEqual(result["days_counted"], 10)
        self.assertEqual(result["occupied_room_nights"], 10)
        self.assertEqual(result["rate"], D(10) / D(40))                     # 4 oda × 10 gün
        self.assertIsNone(month_occupancy(2026, 8, as_of=date(2026, 10, 10)))   # konaklama yoksa veri yok


class RoomTypeShareTests(TestCase):
    """Ortak giderler oda tipinin maliyet payı katsayısıyla ağırlıklı dağıtılır."""

    def setUp(self):
        self.small = RoomType.objects.create(code="KCK", name="Küçük", max_guests=2, standard_cost_factor=D("1"))
        self.large = RoomType.objects.create(code="BYK", name="Büyük", max_guests=2, standard_cost_factor=D("2"))
        for number in range(1, 7):                       # 6 küçük + 4 büyük oda = 10 oda, ortalama katsayı 1,4
            Room.objects.create(room_type=self.small, room_number=str(100 + number))
        for number in range(1, 5):
            Room.objects.create(room_type=self.large, room_number=str(200 + number))
        self.month = date(2026, 11, 1)                   # 30 gün -> 300 müsait oda-gece
        Behavior = MonthlyExpenseCategory.CostBehavior
        MonthlyHotelExpense.objects.create(category=make_category("Kira"), expense_month=self.month, amount=D("42000"))
        MonthlyHotelExpense.objects.create(category=make_category("Elektrik", Behavior.SEMI_VARIABLE),
                                           expense_month=self.month, amount=D("21000"), variable_rate=D("70"))
        MonthlyHotelExpense.objects.create(
            category=make_category("Su", Behavior.VARIABLE, basis="kisi_gecesi"), expense_month=self.month,
            variable_rate=D("50"))

    def quote(self, room_type, guests=1):
        return calculate_stay_quote(room_type, guests, date(2026, 11, 10), date(2026, 11, 11))

    def test_larger_room_type_takes_a_larger_share(self):
        small, large = self.quote(self.small)["totals"], self.quote(self.large)["totals"]
        # Ortalama oda payı 42.000 ÷ (10 × 365/12). Küçük oda bunun 1/1,4'ü, büyük oda 2/1,4'ü; büyük tam iki katı.
        average = 42000 / (10 * MONTH_DAYS)
        self.assertAlmostEqual(float(small["fixed"]), average / 1.4, places=6)
        self.assertAlmostEqual(float(large["fixed"]), 2 * float(small["fixed"]), places=9)
        self.assertAlmostEqual(float(large["semi_fixed"]), 2 * float(small["semi_fixed"]), places=9)

    def test_weighting_does_not_change_the_total_allocated(self):
        summary = calculate_monthly_room_cost(2026, 11)
        # Ortalama ay uzunluğu (365/12 gün) boyunca dağıtılan toplam = 42.000 sabit + 21.000 taban.
        allocated = sum(item["shared_per_night"] * item["count"] for item in summary["room_distribution"]) * D(365) / D(12)
        self.assertAlmostEqual(float(allocated), 63000, places=6)

    def test_room_based_variable_is_weighted_but_guest_based_is_not(self):
        # Oda-gece başına 70 TL ortalama oda içindir: küçük 50, büyük 100. Kişi başına 50 TL her odada aynıdır.
        self.assertEqual(self.quote(self.small)["totals"]["variable_overhead"], D("100"))
        self.assertEqual(self.quote(self.large)["totals"]["variable_overhead"], D("150"))
        self.assertEqual(self.quote(self.large, guests=2)["totals"]["variable_overhead"], D("200"))

    def test_report_has_a_row_for_each_room_type_and_guest_count(self):
        rows = calculate_monthly_room_cost(2026, 11)["rows"]
        self.assertEqual([(row["room_type_code"], row["guests"]) for row in rows],
                         [("KCK", 1), ("KCK", 2), ("BYK", 1), ("BYK", 2)])
        self.assertGreater(rows[2]["total"], rows[0]["total"])     # aynı kişi sayısında büyük oda daha pahalı


class PerStayCostTests(TestCase):
    """Konaklama başına giderler gece sayısından bağımsızdır; her giriş-çıkışta bir kez oluşur."""

    def setUp(self):
        self.room_type = RoomType.objects.create(code="T5", name="Test", max_guests=2)
        self.rooms = [Room.objects.create(room_type=self.room_type, room_number=str(500 + number)) for number in range(4)]
        laundry = make_category("Çarşaf yıkama", MonthlyExpenseCategory.CostBehavior.VARIABLE, basis="konaklama")
        MonthlyHotelExpense.objects.create(category=laundry, expense_month=date(2026, 11, 1), variable_rate=D("120"))

    def test_charged_once_regardless_of_nights(self):
        one = calculate_stay_quote(self.room_type, 1, date(2026, 11, 10), date(2026, 11, 11))
        four = calculate_stay_quote(self.room_type, 1, date(2026, 11, 10), date(2026, 11, 14))
        self.assertEqual((one["totals"]["per_stay"], four["totals"]["per_stay"]), (D("120"), D("120")))
        self.assertEqual((one["grand_total"], four["grand_total"]), (D("120"), D("120")))
        # Uzun konaklamada gecelik maliyet düşer: 120 TL'ye karşı 30 TL.
        self.assertEqual((one["variable_per_night"], four["variable_per_night"]), (D("120"), D("30")))

    def test_monthly_report_spreads_it_over_the_average_stay_length(self):
        # Konaklama kaydı yokken varsayılan 2 gece kullanılır.
        summary = calculate_monthly_room_cost(2026, 11)
        self.assertFalse(summary["stay_nights_measured"])
        self.assertEqual(summary["rows"][0]["variable_overhead"], D("60"))
        # 1 ve 3 gecelik iki konaklama: ortalama 2 gece... üçüncü, 4 gecelik konaklamayla ortalama (1+3+4)÷3.
        Stay.objects.create(room=self.rooms[0], check_in=date(2026, 11, 3), check_out=date(2026, 11, 4))
        Stay.objects.create(room=self.rooms[1], check_in=date(2026, 11, 3), check_out=date(2026, 11, 6))
        Stay.objects.create(room=self.rooms[2], check_in=date(2026, 11, 3), check_out=date(2026, 11, 7))
        self.assertEqual(average_stay_nights(2026, 11), D(8) / D(3))
        summary = calculate_monthly_room_cost(2026, 11, as_of=date(2026, 12, 15))
        self.assertTrue(summary["stay_nights_measured"])
        self.assertEqual(summary["rows"][0]["variable_overhead"], D("120") / (D(8) / D(3)))   # 45 TL / gece


class DayCloseTests(TestCase):
    """Gün sonu: konaklamaların reçeteye göre tüketimi stoktan düşülür."""

    def setUp(self):
        self.room_type = RoomType.objects.create(code="T20", name="Test", max_guests=2)
        self.room = Room.objects.create(room_type=self.room_type, room_number="2001")
        self.egg = make_item("GID-950", wastage_rate=D("0.05"), reorder_level=D("2"))
        self.soap = make_item("BKL-950", reorder_level=D("1"))
        self.cleaner = make_item("TEM-950", reorder_level=D("1"))
        self.towel = make_item("TXT-950")
        for item, quantity in ((self.egg, "30"), (self.soap, "10"), (self.cleaner, "10"), (self.towel, "10")):
            InventoryMovement.objects.create(item=item, movement_type=Move.PURCHASE, quantity=D(quantity), unit_cost=D("10"),
                                             movement_at=datetime(2026, 11, 1, 9, 0, tzinfo=tz.utc))
        BreakfastBuffetItem.objects.create(item=self.egg, quantity=D("2"))
        RoomPackageItem.objects.create(guest_count=2, item=self.soap, quantity=D("0.5"), basis="kisi_gecesi")
        RoomPackageItem.objects.create(guest_count=2, item=self.cleaner, quantity=D("0.1"), basis="oda_gecesi")
        InventoryItem.objects.filter(pk=self.towel.pk).update(textile_life=100)   # v93: tekstil bilgisi stok kartında
        RoomPackageItem.objects.create(guest_count=2, item=self.towel, quantity=D("1"), basis="oda_gecesi")
        Stay.objects.create(room=self.room, check_in=date(2026, 11, 3), check_out=date(2026, 11, 5), guests=2)   # 2 gece

    def stock(self, item):
        item.refresh_from_db()
        return item.current_stock

    def test_material_price_index_scales_breakfast_package_and_textile_of_that_year(self):
        """Hammadde fiyat endeksi (v75): geçmiş yılın kahvaltı, sarf ve tekstil maliyeti bugünkü fiyat × endeks."""
        from .services import material_index
        self.assertEqual(material_index(2025), D("0.75"))                    # migration: 2025 = 2026 × 0,75
        self.assertEqual(material_index(2031), D("1"))                       # kaydı olmayan yıl bugünkü fiyat
        today = calculate_stay_quote(self.room_type, 2, date(2026, 11, 3), date(2026, 11, 5))
        self.assertGreater(today["variable_total"], 0)
        TaxRate.objects.create(kind=TaxRate.Kind.MATERIAL, valid_from=date(2026, 1, 1), rate=D("0.50"))
        cheaper = calculate_stay_quote(self.room_type, 2, date(2026, 11, 3), date(2026, 11, 5))
        self.assertAlmostEqual(float(cheaper["variable_total"]), float(today["variable_total"]) / 2, places=6)
        row = next(r for r in calculate_monthly_room_cost(2026, 11, as_of=date(2026, 12, 15))["rows"] if r["guests"] == 2)
        self.assertAlmostEqual(float(row["variable"] * 2), float(today["variable_total"]) / 2, places=6)

    def test_each_night_is_deducted_once_with_waste(self):
        call_command("gun_sonu", kadar="2026-11-10", stdout=StringIO())
        # 2 gece × 2 kişi × 2 yumurta = 8 adet tüketim + %5 fire = 0,4 adet.
        self.assertEqual(self.stock(self.egg), D("30") - D("8.4"))
        self.assertEqual(self.egg.movements.filter(movement_type=Move.WASTE).count(), 2)
        self.assertEqual(self.stock(self.soap), D("8"))          # kişi başına: 2 gece × 2 kişi × 0,5
        self.assertEqual(self.stock(self.cleaner), D("9.8"))     # oda başına: 2 gece × 0,1
        self.assertEqual(self.stock(self.towel), D("10"))        # tekstil tüketilmez, yıpranır
        self.assertEqual(InventoryMovement.objects.filter(consumption_day=date(2026, 11, 3)).count(), 4)
        output = StringIO()
        call_command("gun_sonu", kadar="2026-11-10", stdout=output)       # ikinci çalıştırma tekrar düşmez
        self.assertIn("İşlenecek yeni gece yok", output.getvalue())
        self.assertEqual(self.stock(self.egg), D("21.6"))

    def test_nights_before_the_first_purchase_are_not_deducted(self):
        Stay.objects.create(room=self.room, check_in=date(2026, 10, 20), check_out=date(2026, 10, 21), guests=1)
        call_command("gun_sonu", kadar="2026-11-10", stdout=StringIO())
        self.assertFalse(InventoryMovement.objects.filter(consumption_day=date(2026, 10, 20)).exists())

    def test_insufficient_stock_is_skipped_or_restocked(self):
        InventoryMovement.objects.create(item=self.egg, movement_type=Move.CONSUMPTION, quantity=D("28"),
                                         movement_at=datetime(2026, 11, 1, 10, 0, tzinfo=tz.utc))
        output = StringIO()
        call_command("gun_sonu", kadar="2026-11-10", stdout=output)       # eldeki 2 yumurta, gereken 4,2
        self.assertIn("işlenmedi", output.getvalue())
        self.assertFalse(self.egg.movements.filter(consumption_day__isnull=False).exists())
        self.assertGreaterEqual(self.stock(self.egg), 0)
        call_command("gun_sonu", kadar="2026-11-10", ikmal=True, stdout=StringIO())
        self.assertTrue(self.egg.movements.filter(movement_type=Move.PURCHASE, notes__startswith="Otomatik ikmal").exists())
        self.assertEqual(self.egg.movements.filter(movement_type=Move.CONSUMPTION, consumption_day__isnull=False).count(), 2)
        self.assertGreaterEqual(self.stock(self.egg), self.egg.reorder_level)

    def test_preview_changes_nothing(self):
        call_command("gun_sonu", kadar="2026-11-10", onizle=True, stdout=StringIO())
        self.assertEqual(self.stock(self.egg), D("30"))

    def test_day_is_only_for_consumption_and_waste(self):
        with self.assertRaises(ValidationError):
            InventoryMovement.objects.create(item=self.egg, movement_type=Move.PURCHASE, quantity=D("1"),
                                             consumption_day=date(2026, 11, 3))


class PurchaseOrderTests(TestCase):
    """Kritik stok uyarısı ve tedarikçiye sipariş."""
    databases = {"default", "sistem"}

    def setUp(self):
        self.supplier = Supplier.objects.create(name="Test Tedarik", email="satis@ornek.test")
        self.honey = make_item("GID-960", supplier=self.supplier, reorder_level=D("5"))
        InventoryItem.objects.filter(pk=self.honey.pk).update(unit="kg")
        move(self.honey, Move.PURCHASE, "4", "300")                          # 4 kg < kritik 5 kg
        self.other = make_item("GID-961", supplier=self.supplier, reorder_level=D("1"))
        move(self.other, Move.PURCHASE, "10", "20")                          # yeterli
        user = get_user_model().objects.create_user("depo", password="Parola-12345")
        self.client.force_login(user)

    def test_stock_page_alerts_critical_items_grouped_by_supplier(self):
        response = self.client.get(reverse("stock_analysis"))
        self.assertContains(response, 'role="alert"')
        self.assertContains(response, "1 ürün kritik stok seviyesinde")
        self.assertContains(response, reverse("order_create", args=[self.supplier.pk]))
        alerts = response.context["summary"]["alerts"]
        self.assertEqual([(group["supplier"], [row["name"] for row in group["items"]]) for group in alerts],
                         [("Test Tedarik", [self.honey.name])])

    def test_order_form_suggests_quantity_up_to_target_level(self):
        response = self.client.get(reverse("order_create", args=[self.supplier.pk]))
        groups = response.context["groups"]
        self.assertEqual([row["item"].pk for row in groups["main"]], [self.honey.pk])     # öne çıkan: kritik ürün
        rows = {row["item"].pk: row for row in groups["main"] + groups["others"]}
        self.assertEqual(rows[self.honey.pk]["suggested"], D("11"))     # hedef 3 × 5 = 15 kg − eldeki 4 kg
        self.assertEqual(rows[self.honey.pk]["price"], D("300"))         # son alım fiyatı
        self.assertEqual(rows[self.other.pk]["suggested"], D("0"))       # kritik değil

    def test_row_button_opens_the_form_for_that_item_only(self):
        # Stok tablosundaki satır butonu yalnızca o ürünü öne çıkarır; tedarikçinin diğer ürünleri kapalı bölümde 0'dır.
        page = self.client.get(reverse("stock_analysis"))
        self.assertContains(page, f'{reverse("order_create", args=[self.supplier.pk])}?urun={self.other.pk}')
        groups = self.client.get(reverse("order_create", args=[self.supplier.pk]), {"urun": self.other.pk}).context["groups"]
        self.assertEqual([row["item"].pk for row in groups["main"]], [self.other.pk])
        self.assertEqual(groups["main"][0]["suggested"], D("1"))       # stoğu yeterli: bir kritik seviye kadar önerilir
        self.assertEqual([(row["item"].pk, row["suggested"]) for row in groups["others"]], [(self.honey.pk, D("0"))])

    def test_order_flow_create_receive_and_no_double_receive(self):
        response = self.client.post(reverse("order_create", args=[self.supplier.pk]), {
            f"miktar_{self.honey.pk}": "11", f"fiyat_{self.honey.pk}": "310",
            f"miktar_{self.other.pk}": "0", f"fiyat_{self.other.pk}": "20"})
        self.assertRedirects(response, reverse("order_list"))
        order = PurchaseOrder.objects.get()
        self.assertEqual([(line.item_id, line.quantity) for line in order.lines.all()], [(self.honey.pk, D("11"))])
        self.honey.refresh_from_db()
        self.assertEqual(self.honey.current_stock, D("4"))               # sipariş stoğu değiştirmez
        summary = self.client.get(reverse("stock_analysis")).context["summary"]
        row = next(row for row in summary["rows"] if row["sku"] == "GID-960")
        self.assertEqual((row["on_order"], row["covered"]), (D("11"), True))
        self.assertFalse(summary["alerts"][0]["needs_order"])          # siparişte: yeniden sipariş gerekmez
        self.assertContains(self.client.get(reverse("order_list")), "mailto:satis@ornek.test")

        self.client.post(reverse("order_receive", args=[order.pk]))
        self.honey.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.Status.DELIVERED)
        self.assertEqual(self.honey.current_stock, D("15"))
        self.assertEqual(self.honey.average_unit_cost, D("307.3333"))     # (4 × 300 + 11 × 310) ÷ 15, ağırlıklı ortalama
        self.client.post(reverse("order_receive", args=[order.pk]))       # ikinci teslim stok eklemez
        self.honey.refresh_from_db()
        self.assertEqual(self.honey.current_stock, D("15"))

    def test_empty_order_is_rejected_and_cancel_works(self):
        response = self.client.post(reverse("order_create", args=[self.supplier.pk]), {
            f"miktar_{self.honey.pk}": "0", f"fiyat_{self.honey.pk}": "300"})
        self.assertContains(response, "en az bir ürünün")
        response = self.client.post(reverse("order_create", args=[self.supplier.pk]), {
            f"miktar_{self.honey.pk}": "abc", f"fiyat_{self.honey.pk}": "300"})
        self.assertContains(response, "sayı olmalı")
        self.client.post(reverse("order_create", args=[self.supplier.pk]), {
            f"miktar_{self.honey.pk}": "2,5", f"fiyat_{self.honey.pk}": "300"})
        order = PurchaseOrder.objects.get()
        self.assertEqual(order.lines.get().quantity, D("2.5"))         # virgüllü giriş kabul edilir
        self.client.post(reverse("order_cancel", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, PurchaseOrder.Status.CANCELLED)
        self.assertEqual(self.client.get(reverse("stock_analysis")).context["summary"]["rows"][0]["on_order"], 0)

    def test_order_pages_need_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("order_list")).status_code, 302)
        self.assertEqual(self.client.post(reverse("order_receive", args=[1])).status_code, 302)


class MonthlyOverviewTests(TestCase):
    """Aylık analiz: ay bitince kesinleşir, geçmiş aylar ayrı ayrı izlenir."""
    databases = {"default", "sistem"}

    def setUp(self):
        room_type = RoomType.objects.create(code="T30", name="Test", max_guests=2)
        for number in range(1, 21):
            Room.objects.create(room_type=room_type, room_number=str(3000 + number))
        MonthlyHotelExpense.objects.create(category=make_category("Kira"), expense_month=date(2026, 1, 1),
                                           amount=D("60000"), recurs_monthly="evet")

    def test_overview_marks_finished_months_and_splits_used_and_idle_cost(self):
        for room in Room.objects.all()[:15]:                     # Eylül: 20 odanın 15'i ay boyunca dolu = %75
            Stay.objects.create(room=room, check_in=date(2026, 9, 1), check_out=date(2026, 10, 1))
        rows = monthly_overview(2026, as_of=date(2026, 10, 12))
        self.assertEqual(len(rows), 10)                          # Ocak - Ekim
        september = rows[8]
        self.assertTrue(september["complete"])
        self.assertFalse(rows[9]["complete"])                    # Ekim devam ediyor
        self.assertEqual(september["rate"], D("0.75"))
        self.assertEqual((september["used_cost"], september["idle_cost"]), (D("45000"), D("15000")))
        self.assertIsNone(rows[7]["rate"])                       # Ağustos'ta konaklama yok: veri yok

    def test_current_month_row_uses_one_period_and_totals_give_a_verdict(self):
        """Devam eden ayda bütün sütunlar bugüne kadarki günlere göre; toplam satırı kâr / zarar söyler."""
        for room in Room.objects.all()[:10]:                     # Ekim'in ilk 12 günü: 20 odanın 10'u dolu = %50
            Stay.objects.create(room=room, check_in=date(2026, 10, 1), check_out=date(2026, 10, 13),
                                nightly_rate=D("1000"))
        rows = monthly_overview(2026, as_of=date(2026, 10, 12))
        october = rows[9]
        self.assertEqual(october["days_counted"], 12)
        self.assertEqual(october["shared_total"], D("60000") * 12 / 31)            # ayın 12 günlük payı
        self.assertEqual(october["idle_cost"], october["shared_total"] * D("0.5"))  # aynı dönemin boşluğu
        self.assertEqual(october["revenue"], D("120000"))                          # 10 oda × 12 gece × 1.000
        totals = overview_totals(rows)
        self.assertEqual(totals["result"], sum(row["result"] for row in rows))
        self.assertEqual(totals["shared_total"], sum(row["shared_total"] for row in rows))
        self.assertEqual(totals["profitable"], totals["result"] >= 0)
        self.assertEqual(totals["profit_months"] + totals["loss_months"], 10)

    def test_one_off_expense_raises_only_its_month_and_is_flagged(self):
        """Tek seferlik gider (tadilat) yalnız kendi ayının sabit giderine ve oda maliyetine girer, raporda işaretlenir."""
        MonthlyHotelExpense.objects.create(category=make_category("Tadilat"), expense_month=date(2026, 2, 1),
                                           amount=D("30000"), recurs_monthly="hayir", description="Cephe")
        rows = monthly_overview(2026, as_of=date(2026, 5, 10))
        self.assertEqual((rows[0]["shared_total"], rows[1]["shared_total"], rows[2]["shared_total"]),
                         (D("60000"), D("90000"), D("60000")))
        self.assertEqual([line["name"] for line in rows[1]["one_off"]], ["Tadilat"])
        self.assertEqual(rows[0]["one_off"], [])
        january = calculate_monthly_room_cost(2026, 1)["rows"][0]
        february = calculate_monthly_room_cost(2026, 2)["rows"][0]
        self.assertAlmostEqual(float(february["fixed"]), float(january["fixed"]) * 1.5, places=6)

    def test_report_opens_on_the_last_finished_month(self):
        user = get_user_model().objects.create_user("analist", password="Parola-12345")
        self.client.force_login(user)
        response = self.client.get(reverse("cost_report"))
        today = date.today()
        expected = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        self.assertEqual(response.context["month_value"], expected)
        self.assertContains(response, "aylara göre özeti")

class SalesAndClosingTests(TestCase):
    """Konaklamanın satış bilgisi, dönem kapanışı (dondurma) ve fiyatlandırma dashboard'u."""
    databases = {"default", "sistem"}

    def setUp(self):
        self.room_type = RoomType.objects.create(code="T40", name="Test", max_guests=2)
        self.rooms = [Room.objects.create(room_type=self.room_type, room_number=str(4000 + n)) for n in range(1, 11)]
        self.rent = MonthlyHotelExpense.objects.create(category=make_category("Kira"), expense_month=date(2026, 1, 1),
                                                       amount=D("30000"), recurs_monthly="evet")
        self.egg = make_item("YMR-001", average_unit_cost=D("10"))
        BreakfastBuffetItem.objects.create(item=self.egg, quantity=D("2"))
        self.web = SalesChannel.objects.get(name="Web sitesi (doğrudan)")

    def stay(self, room, check_in, check_out, guests=2, **extra):
        return Stay.objects.create(room=room, check_in=check_in, check_out=check_out, guests=guests, **extra)

    def test_sales_channels_are_seeded(self):
        self.assertTrue(SalesChannel.objects.filter(name="Booking.com").exists())

    def test_cancelled_and_no_show_stays_do_not_occupy_the_room(self):
        self.stay(self.rooms[0], date(2026, 9, 1), date(2026, 9, 11), status="iptal")
        self.stay(self.rooms[1], date(2026, 9, 1), date(2026, 9, 11), status="gelmedi")
        self.assertIsNone(month_occupancy(2026, 9, as_of=date(2026, 10, 5)))
        self.assertEqual(occupied_room_ids(date(2026, 9, 5)), set())
        # İptal edilen konaklamanın odası aynı tarihlere yeniden satılabilir.
        self.stay(self.rooms[0], date(2026, 9, 3), date(2026, 9, 5))
        self.assertEqual(occupied_room_ids(date(2026, 9, 3)), {self.rooms[0].id})

    def test_booking_date_cannot_be_after_check_in_and_price_cannot_be_negative(self):
        with self.assertRaises(ValidationError):
            self.stay(self.rooms[0], date(2026, 9, 1), date(2026, 9, 2), booked_on=date(2026, 9, 2))
        with self.assertRaises(ValidationError):
            self.stay(self.rooms[0], date(2026, 9, 1), date(2026, 9, 2), nightly_rate=D("-1"))
        stay = self.stay(self.rooms[0], date(2026, 9, 1), date(2026, 9, 4), booked_on=date(2026, 8, 1),
                         nightly_rate=D("4000"), channel=self.web)
        self.assertEqual(stay.total_price, D("12000"))

    def test_month_sales_counts_only_the_nights_inside_the_month(self):
        self.stay(self.rooms[0], date(2026, 8, 30), date(2026, 9, 3), nightly_rate=D("1000"), channel=self.web)
        self.stay(self.rooms[1], date(2026, 9, 10), date(2026, 9, 12))                  # fiyatsız
        sales = month_sales(2026, 9)
        self.assertEqual((sales["room_nights"], sales["priced_room_nights"], sales["revenue"]), (4, 2, D("2000")))
        self.assertEqual(sales["channels"][self.web.id]["room_nights"], 2)

    def test_closed_month_keeps_that_months_prices(self):
        for room in self.rooms[:5]:
            self.stay(room, date(2026, 9, 1), date(2026, 10, 1), nightly_rate=D("1000"))
        before = calculate_monthly_room_cost(2026, 9, as_of=date(2026, 10, 5))
        period = close_month(2026, 9, as_of=date(2026, 10, 5))
        self.assertEqual((period.occupied_room_nights, period.available_room_nights), (150, 300))
        self.assertEqual(period.room_revenue, D("150000"))
        self.assertEqual(period.variable_total, D("6000"))                # 150 gece × 2 kişi × 2 yumurta × 10 TL
        self.assertEqual(period.shared_total, D("30000"))
        self.assertEqual(period.result, D("150000") - D("6000") - D("30000"))
        self.assertEqual(len(period.cost_rows()), len(before["rows"]))

        InventoryItem.objects.filter(pk=self.egg.pk).update(average_unit_cost=D("50"))   # yumurta zamlandı
        MonthlyHotelExpense.objects.filter(pk=self.rent.pk).update(amount=D("90000"))     # kira değişti
        Room.objects.filter(pk=self.rooms[9].pk).update(status=Room.Status.INACTIVE)      # bir oda pasife alındı
        frozen = calculate_monthly_room_cost(2026, 9, as_of=date(2026, 10, 5))
        live = calculate_monthly_room_cost(2026, 8, as_of=date(2026, 10, 5))
        self.assertIsNotNone(frozen["frozen"])
        self.assertEqual(frozen["shared_total"], D("30000"))
        self.assertEqual(live["shared_total"], D("90000"))
        self.assertAlmostEqual(frozen["rows"][1]["variable"], before["rows"][1]["variable"], places=2)
        self.assertEqual(month_occupancy(2026, 9, as_of=date(2026, 10, 5))["rate"], D("0.5"))
        september = pricing_overview(2026, as_of=date(2026, 10, 5))["months"][8]
        self.assertEqual((september["status"], september["result"]), ("closed", D("114000")))

    def test_only_finished_months_can_be_closed_and_reopen_recalculates(self):
        with self.assertRaises(ValidationError):
            close_month(2026, 10, as_of=date(2026, 10, 5))
        close_month(2026, 9, as_of=date(2026, 10, 5))
        with self.assertRaises(ValidationError):
            close_month(2026, 9, as_of=date(2026, 10, 5))
        MonthlyHotelExpense.objects.filter(pk=self.rent.pk).update(amount=D("45000"))
        period = close_month(2026, 9, as_of=date(2026, 10, 5), reopen=True)
        self.assertEqual(period.shared_total, D("45000"))
        self.assertEqual(ClosedPeriod.objects.count(), 1)

    def test_finished_months_close_automatically_after_the_grace_days(self):
        with self.settings(PERIOD_CLOSE_GRACE_DAYS=5):
            closed = auto_close_months(today=date(2026, 10, 5))           # Eylül'ün bekleme süresi dolmadı
            self.assertNotIn(date(2026, 9, 1), [period.month for period in closed])
            self.assertTrue(ClosedPeriod.objects.filter(month=date(2026, 8, 1)).exists())
            closed = auto_close_months(today=date(2026, 10, 6))
            self.assertEqual([period.month for period in closed], [date(2026, 9, 1)])
            self.assertEqual(auto_close_months(today=date(2026, 10, 7)), [])          # ikinci kez kapatmaz

    def test_closing_runs_in_background_without_a_screen_or_reclose_option(self):
        """Kapanış arka planda çalışır (ekran açılınca); menüde kapanış ekranı ve "Yeniden kapat" seçeneği yoktur."""
        user = get_user_model().objects.create_user("kapanis", password="Parola-12345")
        self.client.force_login(user)
        with self.settings(PERIOD_CLOSE_GRACE_DAYS=0):
            response = self.client.get(reverse("cost_report"))
        period = ClosedPeriod.objects.order_by("-month").first()
        self.assertEqual(period.notes, "Otomatik kapanış")
        self.assertNotContains(response, "Dönem kapanışları")
        self.assertNotContains(response, "Yeniden kapat")
        self.assertEqual(self.client.get("/donem-kapanislari/").status_code, 404)

    def test_pricing_overview_calculation(self):
        for room in self.rooms[:5]:
            self.stay(room, date(2026, 9, 1), date(2026, 10, 1), nightly_rate=D("1000"), channel=self.web)
        data = pricing_overview(2026, as_of=date(2026, 10, 5))
        september = data["months"][8]
        self.assertEqual(september["occupancy"], D("0.5"))
        self.assertEqual(september["adr"], D("1000"))
        self.assertEqual(september["revpar"], D("500"))
        self.assertEqual(september["result"], D("150000") - D("6000") - D("30000"))
        # Başabaş: 30.000 ÷ (300 × (1.000 − 40)) = %10,4
        self.assertAlmostEqual(float(september["breakeven"]), 30000 / (300 * 960), places=6)
        self.assertEqual(data["channels"][0]["name"], "Web sitesi (doğrudan)")
        # v92: "Satış ve kârlılık" sayfası kaldırıldı; hesap fonksiyonu duruyor, adres artık yok.
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse("pricing_dashboard")


class PriceCalendarTests(TestCase):
    """Fiyat takvimi: temel fiyat × en yüksek etkinlik endeksi, maliyet sınırlarıyla karşılaştırma."""
    databases = {"default", "sistem"}

    def setUp(self):
        self.room_type = RoomType.objects.create(code="T50", name="Test", max_guests=2, target_markup=D("0.50"))
        self.rooms = [Room.objects.create(room_type=self.room_type, room_number=str(5000 + n)) for n in range(1, 11)]
        MonthlyHotelExpense.objects.create(category=make_category("Kira"), expense_month=date(2026, 1, 1),
                                           amount=D("30000"), recurs_monthly="evet")
        self.winter = Season.WINTER
        set_rate(self.room_type, self.winter, D("1000"))
        self.seeded = {(event.name, event.start_date) for event in Event.objects.all()}
        Event.objects.all().delete()                                   # migration'daki gerçek takvim testi etkilemesin

    def market_anchored(self, markup="7"):
        """Gerçek oteldeki gibi: maliyetten hedef fiyat piyasa fiyatının üstünde -> fiyat motorunun çapası piyasa fiyatı.

        Test otelinin tam maliyeti ~141 TL; marj 7 ile hedef ~1.127 TL > piyasa 1.000 TL. Talep kuralları piyasa fiyatı
        üzerinden sınanır.
        """
        self.room_type.target_markup = D(markup)
        self.room_type.save()

    def test_event_calendar_and_room_markups_are_seeded(self):
        # Migration gerçek takvimi yükler: bayramlar Diyanet tarihleriyle, İEF ve Fuar İzmir fuarları.
        self.assertGreaterEqual(len(self.seeded), 40)
        self.assertIn(("Kurban Bayramı", date(2027, 5, 15)), self.seeded)
        self.assertIn(("Ramazan Bayramı", date(2027, 3, 8)), self.seeded)
        self.assertEqual(self.room_type.target_markup, D("0.50"))

    def test_price_status_bands(self):
        self.assertEqual(price_status(D("50"), D("100"), D("400"), D("600")), "critical")
        self.assertEqual(price_status(D("300"), D("100"), D("400"), D("600")), "serious")
        self.assertEqual(price_status(D("500"), D("100"), D("400"), D("600")), "warning")
        self.assertEqual(price_status(D("600"), D("100"), D("400"), D("600")), "good")
        self.assertEqual(price_status(D("600"), D("100"), None, None), "unknown")

    def test_highest_event_index_applies_and_costs_use_last_years_occupancy(self):
        self.market_anchored()
        for room in self.rooms[:5]:                                      # Aralık 2026: %50 doluluk
            Stay.objects.create(room=room, check_in=date(2026, 12, 1), check_out=date(2027, 1, 1), guests=2)
        Event.objects.create(name="Fuar", kind="fuar", start_date=date(2027, 12, 10), end_date=date(2027, 12, 12),
                             index=D("1.40"))
        Event.objects.create(name="Festival", kind="festival", start_date=date(2027, 12, 12),
                             end_date=date(2027, 12, 13), index=D("1.10"))
        occupancy, source = expected_occupancy(2027, 12, as_of=date(2027, 11, 1))
        # Geçen yıl %50; bu yıl henüz hiç satış yok (geçen yıl aynı gün 155 oda-gece) -> hız düzeltmesi alt sınırda -%25.
        self.assertEqual(occupancy, D("0.375"))
        self.assertIn("rezervasyon hızına göre düzeltildi (-%25)", source)
        data = price_calendar(2027, 12, as_of=date(2027, 11, 1))
        item = data["types"][0]
        prices = {cell["date"].day: cell["price"] for cell in item["cells"]}
        # Aralık 2027 geceleri için henüz satılmış oda yok (anlık doluluk %0) -> her gecede ayrıca %5 indirim.
        self.assertEqual((prices[9], prices[10], prices[12], prices[13]), (D("950"), D("1330"), D("1330"), D("1045")))
        # Tam maliyet beklenen dolulukla (%37,5) değil, NORMAL dolulukla hesaplanır: boş odalar fiyata yüklenmez.
        # Son 12 ayda yalnız 1 ay veri var -> varsayım %70. Ortak gider 30.000 TL ÷ 310 müsait oda-gece ÷ %70.
        self.assertEqual(data["normal_occupancy"], D("0.70"))
        self.assertIn("varsayım", data["normal_source"])
        self.assertAlmostEqual(float(item["breakeven"]), 30000 / (10 * MONTH_DAYS) / 0.70, places=2)
        self.assertAlmostEqual(float(item["target"]), 30000 / (10 * MONTH_DAYS) / 0.70 * 8, places=2)   # marj 7
        self.assertEqual(data["occupancy"], D("0.375"))                  # talep bilgisi olarak gösterilmeye devam eder
        # Çapa piyasa fiyatı (hedef piyasanın üstünde): yalnız talebin hedefi aştığı geceler "hedefte", diğerleri kârlı.
        self.assertEqual(item["counts"]["good"], sum(1 for cell in item["cells"] if cell["price"] >= item["target"]))
        self.assertEqual(item["counts"]["good"] + item["counts"]["warning"], 31)
        self.assertEqual(data["event_nights"], 4)

    def test_normal_occupancy_is_last_12_months_average_and_low_month_does_not_raise_cost(self):
        # Ocak-Haziran 2027: 10 odanın 6'sı dolu (%60); Temmuz'da otel bomboş.
        for room in self.rooms[:6]:
            Stay.objects.create(room=room, check_in=date(2027, 1, 1), check_out=date(2027, 7, 1), guests=2)
        rate, source = normal_occupancy(as_of=date(2027, 8, 1))
        self.assertAlmostEqual(float(rate), 0.6, places=6)               # boş Temmuz verisiz sayılır, ortalamayı bozmaz
        self.assertIn("son 6 biten ayın ortalaması, 01.2027–06.2027", source)
        july = price_calendar(2027, 7, as_of=date(2027, 8, 1))
        june = price_calendar(2027, 6, as_of=date(2027, 8, 1))
        # İki ayın ortak gideri aynı (30.000 TL). Pay yıllık esasla bölündüğü için ayın 30 ya da 31 gün çekmesi de,
        # Temmuz'un boşluğu da gecenin maliyetini değiştirmez.
        self.assertAlmostEqual(float(july["types"][0]["breakeven"]), 30000 / (10 * MONTH_DAYS) / 0.6, places=2)
        self.assertEqual(july["types"][0]["breakeven"], june["types"][0]["breakeven"])

    def test_each_room_type_uses_its_own_normal_occupancy(self):
        """Az satılan oda tipi boş gecelerinin payını kendi fiyatında taşır (otel ortalaması kullanılmaz)."""
        other = RoomType.objects.create(code="T51", name="Az satılan", max_guests=2, target_markup=D("0.50"))
        others = [Room.objects.create(room_type=other, room_number=str(5100 + n)) for n in range(1, 11)]
        set_rate(other, self.winter, D("1000"))
        for room in self.rooms[:6] + others[:3]:          # Ocak-Haziran 2027: T50 %60, T51 %30, otel %45
            Stay.objects.create(room=room, check_in=date(2027, 1, 1), check_out=date(2027, 7, 1), guests=2)
        normals = type_normal_occupancy(as_of=date(2027, 8, 1))
        self.assertAlmostEqual(float(normals[self.room_type.id]), 0.6, places=6)
        self.assertAlmostEqual(float(normals[other.id]), 0.3, places=6)
        self.assertAlmostEqual(float(normal_occupancy(as_of=date(2027, 8, 1))[0]), 0.45, places=6)
        types = {item["room_type"].code: item for item in price_calendar(2027, 7, as_of=date(2027, 8, 1))["types"]}
        share = 30000 / (20 * MONTH_DAYS)                  # iki tipin katsayısı aynı: ortalama oda payı
        self.assertAlmostEqual(float(types["T50"]["breakeven"]), share / 0.6, places=2)
        self.assertAlmostEqual(float(types["T51"]["breakeven"]), share / 0.3, places=2)

    def test_empty_month_is_not_absorbed_and_window_nets_the_seasons(self):
        """Ortak giderin satışla karşılanması: boş ay hiç karşılamaz; olağan dışı boşluk 12 ayın net eksiğidir."""
        for room in self.rooms[:6]:
            Stay.objects.create(room=room, check_in=date(2027, 1, 1), check_out=date(2027, 7, 1), guests=2)
        july = month_absorption(2027, 7, as_of=date(2027, 8, 15))
        self.assertEqual((july["shared"], july["absorbed"], july["difference"]), (D("30000"), D("0"), D("-30000")))
        window = absorption_window(2027, 7, as_of=date(2027, 8, 15))
        self.assertEqual(window["count"], 12)
        self.assertEqual(window["net"], window["over"] - window["short"])
        self.assertEqual(window["abnormal"], max(D("0"), -window["net"]))
        self.assertGreater(window["abnormal"], 0)          # yılın yarısı bomboş: normalin altında

    def test_occupancy_target_command_only_adds_and_can_be_undone(self):
        """doluluk_hedefi: ayı hedef doluluğa tamamlar (mevcut kayıt silinmez), ay dışına taşmaz, --sil geri alır."""
        existing = Stay.objects.create(room=self.rooms[0], check_in=date(2027, 1, 5), check_out=date(2027, 1, 9), guests=2)
        call_command("doluluk_hedefi", yil=2027, hedef="1=60", stdout=StringIO())
        self.assertEqual(month_occupancy(2027, 1, as_of=date(2027, 3, 1))["occupied_room_nights"], 186)   # %60 × 310
        self.assertTrue(Stay.objects.filter(pk=existing.pk).exists())
        added = Stay.objects.filter(notes="Doluluk hedefi")
        self.assertFalse(added.filter(check_out__gt=date(2027, 2, 1)).exists())                       # Şubat'a taşmaz
        self.assertTrue(all(stay.nightly_rate for stay in added))                                       # kış temel fiyatı var
        call_command("doluluk_hedefi", yil=2027, sil=True, stdout=StringIO())
        self.assertEqual(list(Stay.objects.values_list("pk", flat=True)), [existing.pk])

    def test_pricing_engine_anchor_floor_last_minute_and_decision(self):
        """Fiyat motoru: çapa = min(hedef, piyasa); normalde tam maliyetin altına inmez; son dakikada boş gecede inebilir;
        otel kararı son sözdür (alt sınır uygulanmaz)."""
        full = 30000 / (10 * MONTH_DAYS) / 0.70                             # ~140,9 TL; değişken gider yok
        night = date(2027, 12, 20)                                          # Pazartesi, etkinliksiz, otel boş (-%5)
        cheap = FiyatMotoru(night, night + timedelta(days=1), as_of=date(2027, 11, 1)).night(self.room_type, 2, night)
        self.assertEqual(cheap["anchor_source"], "target")                  # maliyet hedefi (211) < piyasa (1.000)
        self.assertAlmostEqual(float(cheap["price"]), full * 1.5 * 0.95, places=2)
        set_all_rates(self.room_type, D("100"))   # piyasa tam maliyetin altında
        normal = FiyatMotoru(night, night + timedelta(days=1), as_of=date(2027, 11, 1)).night(self.room_type, 2, night)
        self.assertEqual((normal["anchor_source"], normal["floor_kind"], normal["floor_applied"]), ("market", "tam maliyet", True))
        self.assertAlmostEqual(float(normal["price"]), full, places=2)      # 95 TL'ye inmez, tam maliyette durur
        late = FiyatMotoru(night, night + timedelta(days=1), as_of=date(2027, 12, 17)).night(self.room_type, 2, night)
        self.assertEqual((late["floor_kind"], late["floor_applied"]), ("son dakika", False))
        self.assertTrue(late["last_minute"])
        self.assertEqual(late["price"], D("66.5"))                          # 3 gün kala, boş otel: -%5 × son dakika -%30;
                                                                            # taban değişken × 1,2 (burada 0)
        Event.objects.create(name="Kampanya", kind="fiyat_karari", start_date=night, end_date=night, index=D("0.50"),
                             notes="Deneme kararı.")
        decided = FiyatMotoru(night, night + timedelta(days=1), as_of=date(2027, 11, 1)).night(self.room_type, 2, night)
        self.assertEqual((decided["price"], decided["floor_applied"]), (D("50"), False))   # karar alt sınırı geçer

    def test_stay_total_cannot_fall_below_the_nightly_floors_and_channel_price_is_grossed_up(self):
        set_all_rates(self.room_type, D("150"))   # piyasa tam maliyetin az üstünde
        quote = stay_price_quote(self.room_type, 2, date(2027, 12, 1), date(2027, 12, 17), booked_on=date(2027, 9, 1),
                                 as_of=date(2027, 9, 1))
        self.assertGreater(quote["floor_lift"], 0)                          # erken + süre indirimi tabanı delmek istedi
        self.assertEqual(quote["total"], quote["floor_total"])
        self.assertTrue(quote["break_even"])
        self.assertEqual(quote["status_label"], "Başabaş: alt sınırda")
        self.assertEqual(channel_price(D("850"), D("0.15")), D("1000"))      # komisyon düşülünce otele 850 kalır

    def test_profit_guard_keeps_large_rooms_profitable_every_day(self):
        """Kâr koruması (v70): asgari kâr marjı olan oda tipi son dakikada, otel kararında, indirimlerde ve kanal
        komisyonunda bile tam maliyet + marjın altına inmez. Marjı 0 olan tip eskisi gibi katkı/zarar görebilir."""
        full = 30000 / (10 * MONTH_DAYS) / 0.70
        night = date(2027, 12, 20)
        set_all_rates(self.room_type, D("100"))   # piyasa tam maliyetin altında
        self.room_type.min_markup = D("0.05")
        self.room_type.save()
        for as_of in (date(2027, 11, 1), date(2027, 12, 17)):                      # normal gün ve son dakika
            quote = FiyatMotoru(night, night + timedelta(days=1), as_of=as_of).night(self.room_type, 2, night)
            self.assertEqual((quote["floor_kind"], quote["floor_applied"], quote["protected"]), ("kâr koruması", True, True))
            self.assertAlmostEqual(float(quote["price"]), full * 1.05, places=2)
            self.assertEqual(quote["status"], "warning")                            # kârlı (hedefin altında)
        Event.objects.create(name="Kampanya", kind="fiyat_karari", start_date=night, end_date=night, index=D("0.50"))
        decided = FiyatMotoru(night, night + timedelta(days=1), as_of=date(2027, 11, 1)).night(self.room_type, 2, night)
        self.assertAlmostEqual(float(decided["price"]), full * 1.05, places=2)     # karar 50 TL diyordu
        self.assertIn("Kâr koruması", decided["warning"])
        channel = SalesChannel.objects.filter(commission_rate__gt=0).order_by("-commission_rate").first()
        stay = stay_price_quote(self.room_type, 2, date(2027, 12, 1), date(2027, 12, 21), booked_on=date(2027, 9, 1),
                                as_of=date(2027, 9, 1), channel=channel)
        self.assertTrue(stay["protected"])
        self.assertGreater(stay["floor_lift"], 0)
        self.assertGreater(stay["net"], stay["full_cost"] * D("1.03"))             # komisyondan sonra da kârlı
        self.assertEqual(stay["status"], "warning")
        self.assertFalse(stay["break_even"])
        # Koruma kapalıyken aynı karar fiyatı tam maliyetin altına indirir (ilk 4 kategori böyle çalışır).
        self.room_type.min_markup = D("0")
        self.room_type.save()
        open_type = FiyatMotoru(night, night + timedelta(days=1), as_of=date(2027, 11, 1)).night(self.room_type, 2, night)
        self.assertEqual(open_type["price"], D("50"))

    def test_presale_command_books_future_nights_before_today(self):
        """Ön satış: gelecek aralık hedef doluluğa bugüne kadar alınmış rezervasyonlarla tamamlanır; fiyat motoru görür."""
        call_command("doluluk_hedefi", aralik="2027-12-10:2027-12-13=80", bugun="2027-11-01", stdout=StringIO())
        added = Stay.objects.filter(notes="Doluluk hedefi · ön satış")
        self.assertTrue(added.exists())
        self.assertFalse(added.filter(booked_on__gt=date(2027, 11, 1)).exists())       # rezervasyon tarihi geçmişte
        self.assertFalse(added.filter(check_out__gt=date(2027, 12, 13)).exists())       # aralık dışına taşmaz
        night = FiyatMotoru(date(2027, 12, 10), date(2027, 12, 11), as_of=date(2027, 11, 1)).night(
            self.room_type, 2, date(2027, 12, 10))
        self.assertEqual(night["occupancy"], D("0.8"))                                  # 10 odanın 8'i satılmış
        call_command("doluluk_hedefi", yil=2027, sil=True, stdout=StringIO())
        self.assertFalse(Stay.objects.filter(notes__startswith="Doluluk hedefi").exists())

    def test_price_between_variable_cost_and_full_cost_is_contribution_not_loss(self):
        self.assertEqual(price_status(D("300"), D("100"), D("400"), D("600")), "serious")
        self.assertEqual(PRICE_STATUS["serious"], "Katkı sağlıyor")
        self.assertEqual(PRICE_STATUS["critical"], "Zarar: satılmamalı")

    def test_event_end_cannot_be_before_start(self):
        event = Event(name="Hatalı", kind="fuar", start_date=date(2027, 5, 2), end_date=date(2027, 5, 1))
        with self.assertRaises(ValidationError):
            event.full_clean()
        self.assertEqual(Event(index=D("1.40")).change_label, "+%40")
        self.assertEqual(Event(index=D("0.90")).change_label, "-%10")

    def test_price_overview_separates_normal_nights_from_hotel_decisions(self):
        # Özet kart: kampanya/karar geceleri aralığı bozmasın; ayrı listelenir ve art arda geceler gruplanır.
        campaign = Event(name="Kampanya", kind="fiyat_karari", index=D("0.10"), published=False)
        def cell(day, price, decision=None, status="warning"):
            return {"date": date(2027, 3, day), "price": D(price), "status": status, "status_label": PRICE_STATUS[status],
                    "engine": {"decision": decision}}
        cells = [cell(1, "4000"), cell(2, "5000"), cell(3, "300", campaign, "critical"),
                 cell(4, "300", campaign, "critical"), cell(5, "4500")]
        overview = price_overview(cells, D("900"), D("3500"), D("5250"))
        self.assertEqual((overview["normal_low"], overview["normal_high"]), (D("4000"), D("5000")))
        self.assertEqual(overview["normal_nights"], 3)
        self.assertEqual(len(overview["special"]), 1)
        group = overview["special"][0]
        self.assertEqual((group["start"].day, group["end"].day, group["nights"], group["low"]), (3, 4, 2, D("300")))
        self.assertTrue(overview["has_draft"])
        self.assertAlmostEqual(sum(overview["scale"]["zones"]), 100, places=6)

    def test_calendar_page_renders_plain_language_summary(self):
        user = get_user_model().objects.create_user("takvim", password="Parola-12345")
        self.client.force_login(user)
        response = self.client.get(reverse("price_calendar") + "?ay=2027-01&oda=T50")
        self.assertContains(response, "fiyat özeti")
        self.assertContains(response, "Sıradan gecelerde")
        self.assertContains(response, "1.000 ₺")
        self.assertNotContains(response, "Satış ve kârlılık")                          # v92: menüden kaldırıldı

    def test_hotel_price_decision_overrides_automatic_rule_and_explains_the_night(self):
        self.market_anchored()
        # Seed verisi Kasım 2026 için üç örnek karar içerir (yeşil, turuncu, kırmızı geceler için).
        names = {name for name, _ in self.seeded}
        self.assertTrue({"MOTTA fuarı yoğun talep fiyatı", "Hafta içi son dakika indirimi",
                         "Black Friday kampanyası (taslak)"} <= names)
        Event.objects.create(name="Fuar", kind="fuar", start_date=date(2027, 12, 6), end_date=date(2027, 12, 10),
                             index=D("1.40"))
        Event.objects.create(name="Fuar sonrası indirim", kind="fiyat_karari", start_date=date(2027, 12, 9),
                             end_date=date(2027, 12, 9), index=D("0.70"), notes="Fuar erken bitti; talep düştü.")
        Event.objects.create(name="Hatalı kampanya", kind="fiyat_karari", start_date=date(2027, 12, 15),
                             end_date=date(2027, 12, 15), index=D("0.05"), notes="Yanlış girilmiş indirim.")
        data = price_calendar(2027, 12, as_of=date(2027, 11, 1))
        item = data["types"][0]
        cells = {cell["date"].day: cell for cell in item["cells"]}
        self.assertEqual(cells[8]["price"], D("1330"))                   # fuar +%40, boş otel -%5
        self.assertEqual(cells[9]["price"], D("700"))                    # otelin kararı fuarı geçer; doluluk etkisi yok
        self.assertEqual(cells[9]["occupancy_factor"], D("1"))
        self.assertEqual(cells[9]["event"].name, "Fuar sonrası indirim")
        self.assertEqual(cells[8]["status"], "good")
        self.assertEqual(cells[8]["why"], "Güçlü talep: hedef kâr tutuyor")
        self.assertEqual(cells[15]["price"], D("50"))
        explained = item["explained"]
        # Art arda aynı sebep ve durumdaki geceler tek satır; farklı karar ayrı satır olur. Kârlı ama hedefin altındaki
        # olağan geceler (1-5 Aralık, 9 Aralık kararı) açıklanmaz; fuarın hedefi aşan geceleri ve zarar yazan karar açıklanır.
        self.assertEqual([(row["from"].day, row["to"].day) for row in explained[:3]], [(6, 8), (10, 10), (15, 15)])
        self.assertEqual(cells[2]["why"], "")                              # olağan gece: gerekçe yazılmaz
        self.assertTrue(explained[2]["detail"].startswith("Yanlış girilmiş indirim. "))

    def test_price_decision_needs_reason_and_deep_discount_only_for_decisions(self):
        decision = Event(name="Kampanya", kind="fiyat_karari", start_date=date(2027, 1, 5), end_date=date(2027, 1, 5),
                         index=D("0.30"))
        with self.assertRaises(ValidationError):                        # açıklama zorunlu
            decision.full_clean()
        decision.notes = "Sezon dışı tanıtım."
        decision.full_clean()
        festival = Event(name="Festival", kind="festival", start_date=date(2027, 1, 5), end_date=date(2027, 1, 5),
                         index=D("0.30"))
        with self.assertRaises(ValidationError):                        # dış etkinlikte %50'den büyük indirim olmaz
            festival.full_clean()

    def test_night_reasons_explain_contribution_and_loss(self):
        event = Event(name="Son dakika", kind="fiyat_karari", index=D("0.70"), notes="Talep zayıf.")
        night = {"event": event, "weekday": None}
        short, detail = night_reason("serious", night, D("1000"), D("200"), D("800"))
        self.assertIn("boş kalmasından iyi", short)
        self.assertTrue(detail.startswith("Talep zayıf. "))
        self.assertIn("indirim en fazla %20 olmalı", detail)
        short, detail = night_reason("critical", night, D("1000"), D("200"), D("800"))
        self.assertEqual(short, "Oda giderinin altında: satılmamalı")
        self.assertIn("indirim en fazla %80 olabilir", detail)
        self.assertEqual(night_reason("warning", {}, D("1000"), D("200"), D("800")), ("", ""))

    def test_occupancy_bands_change_the_night_price_but_not_hotel_decisions(self):
        self.market_anchored()
        # Şubat 2027 bitmiş: gerçekleşen doluluk kullanılır. 10 odalı otel.
        for room in self.rooms[:9]:                                       # 10 Şubat: %90 -> +%30
            Stay.objects.create(room=room, check_in=date(2027, 2, 10), check_out=date(2027, 2, 11), guests=2)
        for room in self.rooms[:7]:                                       # 11 Şubat: %70 -> +%15
            Stay.objects.create(room=room, check_in=date(2027, 2, 11), check_out=date(2027, 2, 12), guests=2)
        for room in self.rooms[:5]:                                       # 12 Şubat: %50 -> +%5
            Stay.objects.create(room=room, check_in=date(2027, 2, 12), check_out=date(2027, 2, 13), guests=2)
        Stay.objects.create(room=self.rooms[0], check_in=date(2027, 2, 15), check_out=date(2027, 2, 16), guests=2)
        Event.objects.create(name="Kampanya", kind="fiyat_karari", start_date=date(2027, 2, 15),
                             end_date=date(2027, 2, 15), index=D("0.80"), notes="Sezon dışı kampanya.")
        cells = {cell["date"].day: cell for cell in price_calendar(2027, 2, as_of=date(2027, 3, 15))["types"][0]["cells"]}
        self.assertEqual([cells[day]["price"] for day in (10, 11, 12, 13)], [D("1300"), D("1150"), D("1050"), D("950")])
        self.assertEqual(cells[10]["occupancy_label"], "otel dolmak üzere")
        self.assertEqual(cells[10]["why"], "Yüksek doluluk: hedef kâr tutuyor")
        self.assertEqual(cells[15]["price"], D("800"))                   # %10 doluluk ama kararda doluluk indirimi yok

    def test_occupancy_is_instant_rooms_sold_at_booking_time_not_a_forecast(self):
        self.market_anchored()
        for room in self.rooms[:8]:                                       # geçen yıl aynı gece %80: dikkate alınmaz
            Stay.objects.create(room=room, check_in=date(2026, 12, 2), check_out=date(2026, 12, 3), guests=2)
        for room in self.rooms[:3]:                                       # 1 Eylül'de satılan 3 oda
            Stay.objects.create(room=room, check_in=date(2027, 12, 1), check_out=date(2027, 12, 2), guests=2,
                                booked_on=date(2027, 9, 1))
        for room in self.rooms[3:7]:                                      # 1 Kasım'da satılan 4 oda daha
            Stay.objects.create(room=room, check_in=date(2027, 12, 1), check_out=date(2027, 12, 2), guests=2,
                                booked_on=date(2027, 11, 1))
        night = date(2027, 12, 1)
        rate, source, sold, rooms = nightly_occupancy(night, night + timedelta(days=1), as_of=date(2027, 10, 1))[night]
        self.assertEqual((sold, rooms), (3, 10))
        self.assertEqual(rate, D("0.3"))                                   # 1 Ekim'de: yalnız 3 oda satılmış
        self.assertIn("satılan oda: 3 / 10", source)
        rate, *_ = nightly_occupancy(night, night + timedelta(days=1), as_of=date(2027, 11, 15))[night]
        self.assertEqual(rate, D("0.7"))                                   # 15 Kasım'da: 7 oda -> +%15 bandı
        # Rezervasyon ekranı doluluğu rezervasyon tarihine göre okur: aynı gece, farklı fiyat.
        early = stay_price_quote(self.room_type, 2, night, night + timedelta(days=1), booked_on=date(2027, 10, 1),
                                 as_of=date(2027, 10, 1))
        late = stay_price_quote(self.room_type, 2, night, night + timedelta(days=1), booked_on=date(2027, 11, 15),
                                as_of=date(2027, 11, 15))
        self.assertEqual(early["subtotal"], D("950"))                      # %30 dolu -> %5 indirim
        self.assertEqual(late["subtotal"], D("1150"))                      # %70 dolu -> %15 zam

    def test_stay_discounts_are_applied_in_order_and_judged_against_cost(self):
        self.market_anchored()
        self.assertEqual([kural.length_of_stay_discount(n) for n in (2, 3, 5, 6, 14, 15)],
                         [D("0"), D("0.05"), D("0.05"), D("0.08"), D("0.08"), D("0.12")])
        self.assertEqual((kural.early_booking_discount(29), kural.early_booking_discount(30)), (D("0"), D("0.15")))
        self.assertEqual([kural.occupancy_band(D(x))[0] for x in ("0.49", "0.5", "0.69", "0.7", "0.89", "0.9", "1")],
                         [D("0.95"), D("1.05"), D("1.05"), D("1.15"), D("1.15"), D("1.30"), D("1.30")])
        # Ocak 2027, 16 gece, 61 gün önce: geceler 1000 × 0,95 (boş otel) = 950; toplam 15.200.
        quote = stay_price_quote(self.room_type, 2, date(2027, 1, 1), date(2027, 1, 17), booked_on=date(2026, 11, 1),
                                 as_of=date(2026, 11, 1))
        self.assertEqual(quote["subtotal"], D("15200"))
        self.assertEqual((quote["early_rate"], quote["length_rate"]), (D("0.15"), D("0.12")))
        self.assertEqual(quote["total"], D("15200") * D("0.85") * D("0.88"))   # sırayla: %25,2, %27 değil
        self.assertEqual(quote["status"], "warning")                       # tam maliyetin üstünde, hedefin (piyasa üstü) altında
        late = stay_price_quote(self.room_type, 2, date(2027, 1, 1), date(2027, 1, 3), booked_on=date(2026, 12, 20),
                                as_of=date(2026, 11, 1))
        self.assertEqual((late["early_rate"], late["length_rate"], late["total"]), (D("0"), D("0"), D("1900")))

    def test_draft_decision_is_shown_in_calendar_but_not_applied_to_bookings(self):
        self.market_anchored()
        Event.objects.create(name="Taslak kampanya", kind="fiyat_karari", start_date=date(2027, 12, 15),
                             end_date=date(2027, 12, 15), index=D("0.10"), notes="Değerlendirmede.", published=False)
        cells = {cell["date"].day: cell for cell in price_calendar(2027, 12, as_of=date(2027, 12, 1))["types"][0]["cells"]}
        self.assertEqual(cells[15]["price"], D("100"))                     # takvim taslağı gösterir
        quote = stay_price_quote(self.room_type, 2, date(2027, 12, 15), date(2027, 12, 16),
                                 booked_on=date(2027, 12, 1), as_of=date(2027, 12, 1))
        self.assertEqual(quote["subtotal"], D("950"))                      # rezervasyona uygulanmaz (boş otel -%5)

    def test_reservation_overview_colors_the_real_sale_price_and_explains_it(self):
        # Tam maliyet ≈ 30.000 ÷ 310 ÷ %70 = 138 TL/gece, hedef ≈ 207 TL (değişken gider yok).
        cheap = Stay.objects.create(room=self.rooms[0], check_in=date(2027, 1, 10), check_out=date(2027, 1, 12),
                                    guests=2, nightly_rate=D("100"), booked_on=date(2026, 11, 1))
        dear = Stay.objects.create(room=self.rooms[1], check_in=date(2027, 1, 10), check_out=date(2027, 1, 13),
                                   guests=2, nightly_rate=D("300"), booked_on=date(2027, 1, 5))
        rows = {row["stay"].pk: row for row in reservation_overview(date(2027, 1, 1), date(2027, 2, 1),
                                                                     as_of=date(2026, 12, 1))}
        self.assertEqual(rows[cheap.pk]["status"], "serious")
        self.assertEqual(rows[dear.pk]["status"], "good")
        self.assertIn("erken rezervasyon (70 gün önce) -%15", rows[cheap.pk]["causes"])
        self.assertIn("3 gece -%5", rows[dear.pk]["causes"])
        self.assertAlmostEqual(float(rows[cheap.pk]["profit"]), 200 - 2 * 30000 / (10 * MONTH_DAYS) / 0.70, places=2)
        user = get_user_model().objects.create_user("rez", password="Parola-12345")
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("reservations")), "Rezervasyonlar")

    def test_pricing_rules_are_edited_in_the_database_and_change_prices(self):
        self.market_anchored()
        rules = PricingRules.current()
        self.assertEqual(rules.band_text(), "%0–50 -%5, %50–70 +%5, %70–90 +%15, %90–100 +%30")
        self.assertEqual(rules.stay_text(), "3+ gece %5, 6+ gece %8, 15+ gece %12")
        rules.low_factor, rules.early_discount, rules.stay_1_discount = D("0.90"), D("0.20"), D("0.10")
        rules.save()
        cells = {cell["date"].day: cell for cell in price_calendar(2027, 12, as_of=date(2027, 11, 1))["types"][0]["cells"]}
        self.assertEqual(cells[1]["price"], D("900"))                      # boş otel: artık %10 indirim (son dakika değil)
        rules.last_minute_discount = D("0.50")
        rules.save()
        late = {cell["date"].day: cell for cell in price_calendar(2027, 12, as_of=date(2027, 12, 1))["types"][0]["cells"]}
        self.assertEqual(late[1]["price"], D("450"))                       # aynı gün, otel boş: son dakika -%50 de eklenir
        quote = stay_price_quote(self.room_type, 2, date(2027, 12, 20), date(2027, 12, 23), booked_on=date(2027, 11, 1),
                                 as_of=date(2027, 11, 1))
        self.assertEqual((quote["early_rate"], quote["length_rate"]), (D("0.20"), D("0.10")))
        rules.mid_limit = D("0.40")                                        # düşük sınırın altında: geçersiz
        with self.assertRaises(ValidationError):
            rules.full_clean()
        admin_user = get_user_model().objects.create_superuser("kural", password="Parola-12345")
        self.client.force_login(admin_user)
        response = self.client.get(reverse("admin:dashboard_pricingrules_changelist"))
        self.assertRedirects(response, reverse("admin:dashboard_pricingrules_change", args=[rules.pk]))

    def test_channel_commission_is_deducted_before_judging_a_reservation(self):
        booking = SalesChannel.objects.get(name="Booking.com")             # %17 komisyon
        # Tam maliyet ≈ 138 TL/gece. 160 TL'lik satış brüt olarak kârlı, komisyon sonrası (132,80 TL) değil.
        stay = Stay.objects.create(room=self.rooms[0], check_in=date(2027, 1, 10), check_out=date(2027, 1, 11),
                                   guests=2, nightly_rate=D("160"), booked_on=date(2027, 1, 5), channel=booking)
        row = next(row for row in reservation_overview(date(2027, 1, 1), date(2027, 2, 1), as_of=date(2026, 12, 1))
                   if row["stay"].pk == stay.pk)
        self.assertEqual((row["commission"], row["net"]), (D("27.2"), D("132.8")))
        self.assertEqual(row["status"], "serious")
        self.assertIn("Booking.com komisyonu %17", row["causes"])
        quote = stay_price_quote(self.room_type, 2, date(2027, 12, 1), date(2027, 12, 2), booked_on=date(2027, 11, 20),
                                 as_of=date(2027, 11, 20), channel=booking)
        self.assertEqual(quote["net"], quote["total"] * D("0.83"))
        self.assertEqual(quote["profit"], quote["net"] - quote["full_cost"])

    def test_abnormal_idle_capacity_is_only_the_shortfall_below_normal(self):
        self.assertAlmostEqual(float(abnormal_idle_cost(D("1000"), D("0.45"), D("0.65"))), 1000 * (1 - 0.45 / 0.65), places=6)
        self.assertEqual(abnormal_idle_cost(D("1000"), D("0.90"), D("0.65")), D("0"))   # normalin üstü: yok
        self.assertIsNone(abnormal_idle_cost(D("1000"), None, D("0.65")))

    def test_weekday_index_competes_with_events_and_highest_wins(self):
        self.market_anchored()
        for weekday, index in ((4, D("1.10")), (6, D("0.95"))):                   # Cuma, Pazar
            Event.objects.create(name=f"Haftalık {weekday}", kind="haftalik", weekday=weekday, index=index,
                                 start_date=date(2025, 1, 1), end_date=date(2030, 12, 31))
        Event.objects.create(name="Küçük festival", kind="festival", start_date=date(2027, 1, 8),
                             end_date=date(2027, 1, 10), index=D("1.05"))
        cells = {cell["date"].day: cell for cell in price_calendar(2027, 1, as_of=date(2026, 12, 1))["types"][0]["cells"]}
        # Bu testte otel boş: her gecede doluluk etkisi -%5.
        self.assertEqual(cells[8]["price"], D("1045"))                            # Cuma 1,10 > festival 1,05
        self.assertEqual(cells[8]["weekday"].weekday, 4)
        self.assertEqual(cells[10]["price"], D("997.5"))                           # Pazar 0,95 < festival 1,05
        self.assertEqual(cells[17]["price"], D("902.5"))                            # festivalsiz Pazar
        self.assertEqual(cells[13]["price"], D("950"))                           # Çarşamba

    def test_guest_count_pricing_and_costs(self):
        self.room_type.single_discount, self.room_type.extra_guest_rate, self.room_type.max_guests = D("0.10"), D("300"), 4
        self.room_type.save()
        self.assertEqual(price_for_guests(D("1000"), 1, self.room_type), D("900"))
        self.assertEqual(price_for_guests(D("1000"), 2, self.room_type), D("1000"))
        self.assertEqual(price_for_guests(D("1000"), 4, self.room_type), D("1600"))
        item = price_calendar(2027, 1, as_of=date(2026, 12, 1), guests=3)["types"][0]
        self.assertEqual((item["guests"], item["base"]), (3, D("1300")))

    def test_taxes_are_dated_and_added_separately(self):
        TaxRate.objects.all().delete()
        TaxRate.objects.create(kind="kdv", valid_from=date(2026, 1, 1), rate=D("0.10"))
        TaxRate.objects.create(kind="konaklama", valid_from=date(2026, 1, 1), rate=D("0.02"))
        TaxRate.objects.create(kind="konaklama", valid_from=date(2026, 5, 1), rate=D("0.01"))
        self.assertEqual(tax_rates(date(2026, 3, 1)), (D("0.10"), D("0.02")))
        self.assertEqual(tax_rates(date(2026, 9, 1)), (D("0.10"), D("0.01")))
        self.assertEqual(guest_price(D("10000"), D("0.10"), D("0.02")), D("11200"))   # 10.000 + 1.000 KDV + 200

    def test_channel_commission_lowers_what_the_hotel_keeps(self):
        booking = SalesChannel.objects.get(name="Booking.com")
        self.assertEqual(booking.commission_rate, D("0.17"))                     # migration varsayımı
        item = price_calendar(2027, 1, as_of=date(2026, 12, 1))["types"][0]
        nets = {row["channel"].name: row["net"] for row in item["channels"]}
        self.assertEqual(nets["Booking.com"], D("830"))
        self.assertEqual(nets["Web sitesi (doğrudan)"], D("1000"))
        for room in self.rooms[:2]:
            Stay.objects.create(room=room, check_in=date(2026, 9, 1), check_out=date(2026, 9, 11), guests=2,
                                nightly_rate=D("1000"), channel=booking)
        self.assertEqual(month_sales(2026, 9)["commission"], D("3400"))           # 20 gece × 1.000 × %17
        period = close_month(2026, 9, as_of=date(2026, 10, 10))
        self.assertEqual(period.commission_total, D("3400"))
        SalesChannel.objects.filter(pk=booking.pk).update(commission_rate=D("0.25"))      # oran sonradan değişti
        september = pricing_overview(2026, as_of=date(2026, 10, 10))["months"][8]
        self.assertEqual(september["result"], D("20000") - september["variable"] - september["shared"] - D("3400"))

    def test_capacity_increase_adds_rows_to_closed_months(self):
        """Kapanıştan sonra kapasitesi artan oda tipinin yeni kişi sayısı kapanmış aylara eklenir; diğer satırlar değişmez."""
        period = close_month(2026, 9, as_of=date(2026, 10, 10))
        before = {(cost.guests, cost.variable, cost.shared) for cost in period.cost_rows()}
        self.room_type.max_guests = 3
        self.room_type.save()
        self.assertEqual(complete_closed_costs(date(2026, 10, 10)), 1)
        period.refresh_from_db()
        costs = {cost.guests: cost for cost in period.cost_rows()}
        self.assertEqual(sorted(costs), [1, 2, 3])
        self.assertEqual(costs[3].shared, costs[2].shared)          # sabit gider payı kişi sayısıyla değişmez
        self.assertTrue(before <= {(cost.guests, cost.variable, cost.shared) for cost in period.cost_rows()})
        self.assertEqual(complete_closed_costs(date(2026, 10, 10)), 0)   # ikinci çalıştırmada eklenecek satır yok

    def test_cost_report_shows_plain_summary(self):
        user = get_user_model().objects.create_user("maliyet", password="Parola-12345")
        self.client.force_login(user)
        response = self.client.get(reverse("cost_report") + "?month=2027-01")
        self.assertContains(response, "maliyet özeti")
        self.assertContains(response, "Otelin sabit gideri")

    def test_example_room_follows_selected_type(self):
        """Örnek oda kartları seçilen oda tipini gösterir; parçalar toplamı verir."""
        other = RoomType.objects.create(code="T41", name="Büyük", max_guests=2, standard_cost_factor=D("2"))
        Room.objects.create(room_type=other, room_number="4100")
        user = get_user_model().objects.create_user("maliyet3", password="Parola-12345")
        self.client.force_login(user)
        response = self.client.get(reverse("cost_report") + "?month=2027-01&oda=T41")
        example = response.context["example"]
        self.assertEqual(example["code"], "T41")
        self.assertEqual(example["variable"] + example["shared"], example["cost"])
        self.assertIn("T41", {t["code"] for t in response.context["example_types"]})
        self.assertContains(response, "Bir oda bir gece otele kaça mal oluyor?")

    def test_cost_table_uses_normal_occupancy(self):
        """Maliyet analizi tablosu ortak gideri ayın gerçek doluluğuna değil normal doluluğa böler (fiyat takvimiyle aynı)."""
        user = get_user_model().objects.create_user("maliyet2", password="Parola-12345")
        self.client.force_login(user)
        for room in self.rooms[:3]:                                   # Eylül'de 10 odanın 3'ü dolu: %30
            Stay.objects.create(room=room, check_in=date(2026, 9, 1), check_out=date(2026, 10, 1), guests=2)
        response = self.client.get(reverse("cost_report") + "?month=2026-09")
        normal = response.context["normal"]
        report = response.context["summary"]
        self.assertNotEqual(normal, report["occupancy"]["rate"])
        first = report["rows"][0]
        row = response.context["simple_rows"][0]
        self.assertEqual(row["shared"], (first["semi_fixed"] + first["fixed"]) / normal)


class RealisticStaysTests(TestCase):
    """Gerçeğe benzeyen örnek konaklama üretimi ve rezervasyon hızı."""
    databases = {"default", "sistem"}

    def setUp(self):
        call_command("seed_demo", stdout=StringIO())
        for season in Season.values:
            for room_type in RoomType.objects.all():
                set_rate(room_type, season, D("5000"))

    def generate(self):
        call_command("gercekci_konaklama_olustur", baslangic="2025-12-01", bitis="2027-01-31", stdout=StringIO())

    def test_real_room_types_and_views(self):
        names = set(RoomType.objects.values_list("name", flat=True))
        self.assertEqual({"Standart Oda", "Superior Oda", "Junior Suite", "Executive Oda", "Deluxe Oda"}, names)
        self.assertEqual(set(Room.objects.filter(room_type__code="DLX").values_list("view_type", flat=True)), {"deniz"})
        self.assertEqual(set(Room.objects.filter(room_type__code="STD").values_list("view_type", flat=True)), {"manzarasiz"})
        self.assertEqual(set(Room.objects.filter(room_type__code="JRS").values_list("view_type", flat=True)), {"sehir"})
        self.assertEqual(set(Room.objects.filter(room_type__code="SUP").values_list("view_type", flat=True)), {"kara"})
        # v90: ucuzdan pahalıya Standart < Superior < Junior Suite < Executive Oda < Deluxe
        self.assertEqual(list(RoomType.objects.order_by("standard_cost_factor").values_list("code", flat=True)),
                         ["STD", "SUP", "JRS", "EXR", "DLX"])

    def test_generated_stays_look_like_real_bookings(self):
        self.generate()
        stays = Stay.objects.all()
        self.assertTrue(stays.exists())
        self.assertFalse(stays.filter(channel__isnull=True).exists())
        self.assertFalse(stays.filter(booked_on__isnull=True).exists())
        self.assertFalse(stays.filter(nightly_rate__isnull=True).exists())
        self.assertTrue(stays.filter(status="iptal").exists())
        self.assertFalse(stays.exclude(booked_on__lte=date.today()).exists())            # gelecek rezervasyon yok
        # Onaylı konaklamalar aynı odada çakışmaz.
        for room in Room.objects.all()[:10]:
            nights = []
            for check_in, check_out in stays.filter(room=room, status="onaylandi").values_list("check_in", "check_out"):
                nights += [check_in + timedelta(days=n) for n in range((check_out - check_in).days)]
            self.assertEqual(len(nights), len(set(nights)))
        # Kanal komisyonu satış ve kârlılık hesabına girer.
        self.assertGreater(month_sales(2026, 1)["commission"], 0)

    def test_manual_stays_block_regeneration(self):
        Stay.objects.create(room=Room.objects.first(), check_in=date(2026, 1, 5), check_out=date(2026, 1, 6), notes="elle")
        with self.assertRaises(CommandError):
            self.generate()

    def test_booking_pace_compares_with_the_same_day_last_year(self):
        room = Room.objects.first()
        Stay.objects.create(room=room, check_in=date(2025, 12, 10), check_out=date(2025, 12, 14), booked_on=date(2025, 10, 1))
        Stay.objects.create(room=room, check_in=date(2025, 12, 20), check_out=date(2025, 12, 22), booked_on=date(2025, 11, 20))
        Stay.objects.create(room=room, check_in=date(2026, 12, 10), check_out=date(2026, 12, 13), booked_on=date(2026, 9, 1))
        pace = booking_pace(2026, 12, as_of=date(2026, 10, 13))
        self.assertEqual((pace["on_books"], pace["last_year_same_day"], pace["last_year_final"]), (3, 4, 6))
        self.assertEqual(pace["change_label"], "-%25")



class TourismCalendarTests(TestCase):
    """v77: turizm odaklı özel günler kayıtlı ve endeksleri talep etkisine göre sıralı."""
    databases = {"default", "sistem"}

    def index_of(self, name, first):
        return Event.objects.get(name=name, start_date=first).index

    def test_special_days_are_seeded_and_ranked_by_demand(self):
        new_year = self.index_of("Yılbaşı gecesi", date(2026, 12, 31))
        valentine = self.index_of("Sevgililer Günü", date(2026, 2, 13))
        sacrifice = self.index_of("Kurban Bayramı", date(2026, 5, 26))
        ramadan = self.index_of("Ramazan Bayramı", date(2026, 3, 19))
        national = self.index_of("19 Mayıs (köprü ile uzun hafta sonu)", date(2026, 5, 16))
        mothers = self.index_of("Anneler Günü", date(2026, 5, 9))
        self.assertTrue(new_year > valentine > sacrifice > ramadan > national > mothers > 1)
        self.assertTrue(Event.objects.filter(name="Sevgililer Günü", start_date=date(2025, 2, 14)).exists())
        # Fiyat motoru o gecenin endeksi olarak özel günü kullanır (hafta sonu endeksinden yüksek).
        night = night_factors(date(2026, 2, 14), date(2026, 2, 15), as_of=date(2026, 1, 1))[date(2026, 2, 14)]
        self.assertEqual((night["index"], night["event"].name), (valentine, "Sevgililer Günü"))


class SpecialDayNoDiscountTests(TestCase):
    """v79: özel gün gecelerinde hiçbir indirim uygulanmaz (son dakika, doluluk, kampanya, erken, süre)."""
    databases = {"default", "sistem"}

    def setUp(self):
        self.room_type = RoomType.objects.create(code="T79", name="Test", max_guests=2, target_markup=D("7"))
        for n in range(1, 11):
            Room.objects.create(room_type=self.room_type, room_number=str(7900 + n))
        MonthlyHotelExpense.objects.create(category=make_category("Kira"), expense_month=date(2026, 1, 1),
                                           amount=D("30000"), recurs_monthly="evet")
        for season in (Season.WINTER, Season.TRANSITION, Season.SUMMER):
            set_rate(self.room_type, season, D("1000"))
        Event.objects.all().delete()                                     # migration takvimi testi etkilemesin
        self.night = date(2027, 12, 20)                                  # Pazartesi, otel boş
        Event.objects.create(name="Özel gün", kind="ozel_gun", start_date=self.night, end_date=self.night, index=D("1.50"))

    def test_special_night_ignores_occupancy_last_minute_and_discount_decision(self):
        Event.objects.create(name="Kampanya", kind="fiyat_karari", start_date=self.night, end_date=self.night,
                             index=D("0.50"))
        late = FiyatMotoru(self.night, self.night + timedelta(days=1), as_of=date(2027, 12, 18)).night(self.room_type, 2, self.night)
        self.assertFalse(late["last_minute"])                            # 2 gün kala ama son dakika indirimi yok
        self.assertIsNone(late["decision"])                              # indirim kararı yok sayıldı
        self.assertEqual(late["skipped_decision"].name, "Kampanya")
        self.assertEqual(late["price"], D("1500"))                       # piyasa × 1,50; boş otel indirimi yok

    def test_stay_discounts_apply_only_to_ordinary_nights(self):
        # 7 gece, 3 ay önce: erken (%15) ve süre (%8) indirimi yalnız 6 sıradan geceye.
        quote = stay_price_quote(self.room_type, 2, date(2027, 12, 15), date(2027, 12, 22), booked_on=date(2027, 9, 1),
                                 as_of=date(2027, 9, 1))
        self.assertEqual(quote["special_nights"], 1)
        self.assertEqual(quote["special_subtotal"], D("1500"))
        ordinary = quote["subtotal"] - quote["special_subtotal"]
        expected = D("1500") + ordinary * (1 - quote["early_rate"]) * (1 - quote["length_rate"])
        self.assertAlmostEqual(float(quote["total"]), float(expected), places=6)
        only_special = stay_price_quote(self.room_type, 2, self.night, self.night + timedelta(days=1),
                                        booked_on=date(2027, 9, 1), as_of=date(2027, 9, 1))
        self.assertEqual((only_special["early_rate"], only_special["total"]), (D("0"), D("1500")))


class ReservationAvailabilityTests(TestCase):
    """v82: rezervasyon sayfası — müsaitlik, öneriler, form kuralları, oda tipi talebi, sabit ek kişi ücreti."""
    databases = {"default", "sistem"}

    def setUp(self):
        from django.utils import timezone
        self.today = timezone.localdate()
        Event.objects.all().delete()
        MonthlyHotelExpense.objects.create(category=make_category("Kira"), expense_month=date(2025, 1, 1),
                                           amount=D("30000"), recurs_monthly="evet")
        self.small = RoomType.objects.create(code="K2", name="Küçük", max_guests=2, target_markup=D("7"),
                                             standard_cost_factor=D("1"))
        self.big = RoomType.objects.create(code="B4", name="Büyük", max_guests=4, target_markup=D("7"),
                                           standard_cost_factor=D("1"), extra_guest_rate=D("300"))
        self.small_rooms = [Room.objects.create(room_type=self.small, room_number=f"K{n}") for n in range(1, 3)]
        self.big_rooms = [Room.objects.create(room_type=self.big, room_number=f"B{n}") for n in range(1, 9)]
        for room_type in (self.small, self.big):
            for season in (Season.WINTER, Season.TRANSITION, Season.SUMMER):
                set_rate(room_type, season, D("1000"))
        for guests in (1, 2, 3, 4):
            RoomPackageItem.objects.create(guest_count=guests, item=make_item(f"PKT-{guests}"), quantity=D("1"))
        self.check_in = self.today + timedelta(days=40)

    def stay(self, room, first, last):
        return Stay.objects.create(room=room, check_in=first, check_out=last, guests=2, booked_on=self.today)

    def test_availability_statuses(self):
        from .services import room_availability
        ci, co = self.check_in, self.check_in + timedelta(days=2)
        self.assertEqual(room_availability(self.small, ci, co)["status"], "available")
        self.stay(self.small_rooms[0], ci, ci + timedelta(days=1))                       # K1 1. gece dolu
        self.stay(self.small_rooms[1], ci + timedelta(days=1), co)                       # K2 2. gece dolu
        result = room_availability(self.small, ci, co)
        self.assertEqual((result["status"], result["min_free"]), ("room_change", 1))      # her gece 1 oda, aynı oda değil
        self.stay(self.small_rooms[1], ci, ci + timedelta(days=1))
        result = room_availability(self.small, ci, co)
        self.assertEqual((result["status"], result["full_nights"]), ("unavailable", [ci]))
        Room.objects.filter(room_type=self.small).update(status=Room.Status.MAINTENANCE)
        self.assertEqual(room_availability(self.small, ci, co)["status"], "no_rooms")

    def test_full_room_type_shows_info_price_sales_and_alternatives(self):
        ci, co = self.check_in, self.check_in + timedelta(days=2)
        for room in self.small_rooms:
            self.stay(room, ci, co)
        user = get_user_model().objects.create_user("rez", password="Parola-12345")
        self.client.force_login(user)
        response = self.client.get(reverse("reservation_cost"), {
            "room_type": self.small.pk, "guests": 2, "check_in": ci, "check_out": co,
            "channel": SalesChannel.objects.order_by("commission_rate").first().pk})
        self.assertContains(response, "Bu tarihlerde yeni rezervasyon alınamaz")
        # v85: personel kontrolü — dolu tarihte de fiyat ve kâr bilgi amaçlı, o gecelerin satış özetiyle birlikte gelir.
        self.assertContains(response, "bilgi amaçlı")
        self.assertIsNotNone(response.context["price"])
        self.assertEqual(response.context["sales"]["sold"], 4)                         # 2 oda × 2 gece satılmış
        alternatives = response.context["alternatives"]
        self.assertEqual([a["room_type"].code for a in alternatives["room_types"]], ["B4"])
        self.assertTrue(alternatives["dates"])
        self.assertNotIn(0, [a["shift"] for a in alternatives["dates"]])

    def test_form_rejects_past_dates_and_offers_channel_dropdown(self):
        from .forms import ReservationCostForm
        booking = SalesChannel.objects.get(name="Booking.com")
        base = {"room_type": self.small.pk, "guests": 2, "channel": booking.pk}
        past = ReservationCostForm({**base, "check_in": self.today - timedelta(days=1), "check_out": self.today})
        self.assertIn("check_in", past.errors)
        self.assertNotIn("booked_on", ReservationCostForm().fields)                    # formda ayrıca tarih sorulmaz
        ok = ReservationCostForm({**base, "check_in": self.check_in, "check_out": self.check_in + timedelta(days=1)})
        self.assertTrue(ok.is_valid(), ok.errors)
        self.assertEqual(ok.cleaned_data["booked_on"], self.today)
        self.assertIn("Booking.com (komisyon %", str(ok["channel"]))

    def test_room_type_occupancy_can_only_raise_the_price(self):
        night = self.check_in
        before = FiyatMotoru(night, night + timedelta(days=1), as_of=self.today).night(self.small, 2, night)
        self.stay(self.small_rooms[0], night, night + timedelta(days=1))
        self.stay(self.small_rooms[1], night, night + timedelta(days=1))                 # Küçük %100, otel %20
        small = FiyatMotoru(night, night + timedelta(days=1), as_of=self.today).night(self.small, 2, night)
        self.assertEqual((small["occupancy_basis"], small["type_occupancy"]), ("oda tipi", D("1")))
        self.assertGreater(small["price"], before["price"])
        big = FiyatMotoru(night, night + timedelta(days=1), as_of=self.today).night(self.big, 2, night)
        self.assertEqual(big["occupancy_basis"], "otel")                                 # boş tip: otel doluluğu, eskisi gibi

    def test_extra_guest_fee_is_not_multiplied_by_demand(self):
        night = self.check_in
        Event.objects.create(name="Karar", kind="fiyat_karari", start_date=night, end_date=night, index=D("2.00"))
        engine = FiyatMotoru(night, night + timedelta(days=1), as_of=self.today)
        two, four = engine.night(self.big, 2, night), engine.night(self.big, 4, night)
        self.assertEqual(two["price"], D("2000"))
        self.assertEqual(four["price"], D("2600"))                                       # 1000 × 2 + 2 × 300 (çarpılmaz)

    def test_deliberate_loss_sale_is_flagged_red_with_reason(self):
        """v88: notu "Zararına satış: ..." olan, tam maliyetin altında satılmış konaklama kırmızı ve gerekçeli görünür."""
        from .services import reservation_overview
        night = self.check_in
        Stay.objects.create(room=self.small_rooms[0], check_in=night, check_out=night + timedelta(days=1), guests=2,
                            booked_on=self.today, nightly_rate=D("50"), notes="Zararına satış: Kasım indirimi (talep azlığı)")
        Stay.objects.create(room=self.small_rooms[1], check_in=night, check_out=night + timedelta(days=1), guests=2,
                            booked_on=self.today, nightly_rate=D("50"))
        rows = {row["stay"].room.room_number: row for row in reservation_overview(night, night + timedelta(days=1), as_of=self.today)}
        flagged, plain = rows["K1"], rows["K2"]
        self.assertTrue(flagged["profit"] < 0)
        self.assertEqual((flagged["status"], flagged["status_label"]), ("critical", "Zararına satış"))
        self.assertIn("Kasım indirimi", flagged["short"])
        self.assertEqual(plain["status"], "serious")                                     # aynı fiyat, gerekçesiz: eski kural

    def test_reservations_page_groups_years_and_loads_month_on_demand(self):
        """v91: Rezervasyonlar sayfası yıl › ay iskeleti verir; ayın tablosu ?parca=ay ile ayrıca yüklenir."""
        user = get_user_model().objects.create_user("rezliste", password="Parola-12345")
        self.client.force_login(user)
        night = self.check_in
        Stay.objects.create(room=self.small_rooms[0], check_in=night, check_out=night + timedelta(days=1), guests=2,
                            booked_on=self.today, nightly_rate=D("50"), notes="Zararına satış: Kasım indirimi (talep azlığı)")
        page = self.client.get(reverse("reservations"))
        years = page.context["years"]
        self.assertEqual([m["value"] for y in years for m in y["months"]], [night.strftime("%Y-%m")])
        self.assertContains(page, 'data-month="%s"' % night.strftime("%Y-%m"))
        part = self.client.get(reverse("reservations"), {"parca": "ay", "ay": night.strftime("%Y-%m")})
        self.assertContains(part, "Zararına satış")
        self.assertNotContains(part, "<html")
        self.assertEqual(self.client.get(reverse("reservations"), {"parca": "ay", "ay": "x"}).status_code, 400)


class PriceOrderTests(TestCase):
    """v89: pahalı oda tipi hiçbir gece bir alttaki tipin %2 fazlasının altına inmez."""
    databases = {"default", "sistem"}

    def test_more_expensive_type_never_priced_below_cheaper_one(self):
        Event.objects.all().delete()
        MonthlyHotelExpense.objects.create(category=make_category("Kira"), expense_month=date(2025, 1, 1),
                                           amount=D("30000"), recurs_monthly="evet")
        cheap = RoomType.objects.create(code="A1", name="Ucuz", max_guests=2, target_markup=D("7"), standard_cost_factor=D("1"))
        dear = RoomType.objects.create(code="A2", name="Pahalı", max_guests=2, target_markup=D("7"), standard_cost_factor=D("1.5"))
        for room_type, price in ((cheap, "1000"), (dear, "900")):                      # yanlış girilmiş piyasa fiyatı
            Room.objects.create(room_type=room_type, room_number=f"{room_type.code}-1")
            for season in (Season.WINTER, Season.TRANSITION, Season.SUMMER):
                set_rate(room_type, season, D(price))
        night = date(2027, 3, 3)
        engine = FiyatMotoru(night, night + timedelta(days=1), as_of=date(2027, 1, 1))
        low, high = engine.night(cheap, 2, night), engine.night(dear, 2, night)
        self.assertTrue(high["order_applied"])
        self.assertEqual(high["order_below"], "Ucuz")
        self.assertAlmostEqual(float(high["price"]), float(low["price"]) * 1.02, places=6)
        self.assertEqual((high["type_rooms"], high["type_sold"]), (1, 0))
