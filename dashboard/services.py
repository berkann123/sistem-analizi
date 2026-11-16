"""Maliyet motoru: view'lar yalnızca bu dosyadaki fonksiyonları çağırır.

Tüm tutarlar TL ve KDV HARİÇTİR.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from . import fiyat_kurallari as kural
from .models import (
    BreakfastBuffetItem, ClosedPeriod, Event, InventoryItem,
    InventoryMovement, MonthlyExpenseCategory, MonthlyHotelExpense, PurchaseOrder, PurchaseOrderLine, Room,
    RoomPackageItem, RoomType, SalesChannel, Season, Stay, TaxRate, index_label, season_map, season_of,
)

ZERO = Decimal("0")
ONE = Decimal("1")
# Konaklama kaydı olmayan bir ayda "konaklama başına" giderleri geceye çevirmek için varsayılan süre.
DEFAULT_STAY_NIGHTS = Decimal("2")
BASIS_LABELS = {"oda_gecesi": "oda-gece", "kisi_gecesi": "kişi-gece", "konaklama": "konaklama"}


# --------------------------------------------------------------------------- aylık giderler

def closed_period(year, month):
    """Ay kapatılmışsa kapanış kaydı (o ayın fiyatlarıyla dondurulmuş değerler), değilse None."""
    return ClosedPeriod.objects.filter(month=date(year, month, 1)).first()


def effective_month_expenses(year, month, seasons=None):
    """Verilen ay için geçerli gider kayıtlarını döndürür.

    Kural (kategori bazında):
      1. O aya ait kayıt varsa yalnızca o kayıt(lar) geçerlidir.
      2. Yoksa, en son başlamış "her ay tekrarlar" kaydı o aya devreder
         (tekrar bitiş tarihi geçmemişse).
      Mevsimi seçili kayıtlar yalnızca o mevsimin aylarında hesaba katılır (her yıl).
    Eski sürümde 1 ve 2 birlikte toplanıyor, zamlı kira girildiğinde gider iki kez sayılıyordu.
    """
    month_start = date(year, month, 1)
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    still_recurring = Q(recurs_monthly=MonthlyHotelExpense.MonthlyRepeat.YES) & (
        Q(recurring_until__isnull=True) | Q(recurring_until__gte=month_start)
    )
    # Mevsim kaydı yalnızca kendi mevsiminin aylarında aday olur; mevsimsiz kayıt her ay adaydır.
    candidates = (
        MonthlyHotelExpense.objects
        .filter(expense_month__lt=next_month)
        .filter(Q(expense_month__gte=month_start) | still_recurring)
        .filter(Q(season="") | Q(season=(seasons or season_map()).get(month, "")))
        .select_related("category")
    )
    latest_by_category = {}
    for expense in candidates:
        period = (expense.expense_month.year, expense.expense_month.month)
        current = latest_by_category.get(expense.category_id)
        if current is None or period > current[0]:
            latest_by_category[expense.category_id] = (period, [expense])
        elif period == current[0]:
            current[1].append(expense)
    return [expense for _, rows in latest_by_category.values() for expense in rows]


def material_index(year):
    """Yılın hammadde fiyat endeksi (kahvaltı, oda paketi sarfı, tekstil); kaydı olmayan yıl 1 (v75)."""
    # v93: oranlar tablosunda tür "hammadde", geçerlilik o yılın 1 Ocak'ı
    factor = (TaxRate.objects.filter(kind=TaxRate.Kind.MATERIAL, valid_from__year=year)
              .order_by("-valid_from").values_list("rate", flat=True).first())
    return factor if factor is not None else ONE


def market_rates():
    """Piyasa (temel) fiyatları: {(oda tipi id, mevsim kodu): 2 kişilik fiyat} — oda tipindeki kış/geçiş/yaz alanları."""
    rates = {}
    for room_type in RoomType.objects.all():
        for season in RoomType.SEASON_FIELDS:
            price = room_type.market_rate(season)
            if price is not None:
                rates[(room_type.id, season)] = price
    return rates


def average_month_days(year):
    """Yılın ortalama ay uzunluğu (365 ÷ 12 = 30,42 gün; artık yılda 366 ÷ 12). Ortak gider gece payının paydası."""
    return Decimal(366 if calendar.isleap(year) else 365) / Decimal(12)


def _active_room_count():
    return Room.objects.filter(status=Room.Status.ACTIVE, room_type__active=True).count()


class _CostContext:
    """Bir hesaplama boyunca veritabanı sonuçlarını bellekte tutar.

    Eski sürüm her gece için aynı sorguları tekrar çalıştırıyordu (30 gecelik
    teklifte 196 sorgu). Burada her ayın giderleri bir kez okunur.
    """

    def __init__(self):
        self.seasons = season_map()                     # mevsim takvimi bir kez okunur (v93)
        # Her aktif odanın maliyet payı katsayısı (oda tipinden gelir).
        weights = list(Room.objects.filter(status=Room.Status.ACTIVE, room_type__active=True)
                       .values_list("room_type__standard_cost_factor", flat=True))
        self.active_rooms = len(weights)
        self.weight_total = sum(weights, ZERO)
        self.mean_weight = self.weight_total / self.active_rooms if self.active_rooms else ONE
        self._months = {}
        self._breakfast = None

    def room_factor(self, room_type):
        """Oda tipinin ORTALAMA odaya göre payı = katsayısı ÷ aktif odaların ortalama katsayısı.

        Ortak giderler önce müsait oda-geceye eşit bölünür (ortalama oda payı), sonra bu oranla
        çarpılır. Odaların oranlarının ortalaması 1 olduğu için dağıtılan toplam gider değişmez;
        yalnızca büyük oda daha çok, küçük oda daha az pay alır.
        """
        if room_type is None or not self.mean_weight:
            return ONE
        return Decimal(room_type.standard_cost_factor) / self.mean_weight

    def share(self, average_room_amount, room_type):
        """Ortalama oda için hesaplanmış tutarı oda tipine uyarlar: tutar × katsayı × oda sayısı ÷ katsayılar toplamı.

        room_factor ile çarpmakla aynıdır; önce çarpıp en son böldüğü için kuruş yuvarlama farkı bırakmaz.
        """
        if room_type is None or not self.weight_total:
            return average_room_amount
        return average_room_amount * Decimal(room_type.standard_cost_factor) * self.active_rooms / self.weight_total

    def month(self, year, month):
        key = (year, month)
        if key not in self._months:
            fixed_total = semi_fixed_total = variable_room = variable_guest = variable_stay = ZERO
            groups = {}
            Behavior = MonthlyExpenseCategory.CostBehavior
            Basis = MonthlyExpenseCategory.VariableBasis
            for expense in effective_month_expenses(year, month, self.seasons):
                category = expense.category
                group = groups.setdefault(category.group, {
                    "name": category.get_group_display(), "order": category.group_order,
                    "fixed": ZERO, "variable_room": ZERO, "variable_guest": ZERO, "variable_stay": ZERO, "lines": [],
                })
                # Aylık sabit tutar: sabit kalemde giderin tamamı, yarı değişken kalemde sabit taban.
                if category.cost_behavior == Behavior.FIXED:
                    fixed_total += expense.amount
                else:
                    semi_fixed_total += expense.amount
                group["fixed"] += expense.amount
                # Değişken kısım bölünmez; esasına göre satılan her oda-geceye, konaklayan her
                # kişi-geceye ya da her konaklamaya (gece sayısından bağımsız, bir kez) eklenir.
                if category.variable_basis == Basis.PER_GUEST_NIGHT:
                    variable_guest += expense.variable_rate
                    group["variable_guest"] += expense.variable_rate
                elif category.variable_basis == Basis.PER_STAY:
                    variable_stay += expense.variable_rate
                    group["variable_stay"] += expense.variable_rate
                else:
                    variable_room += expense.variable_rate
                    group["variable_room"] += expense.variable_rate
                group["lines"].append({
                    "name": category.name, "behavior": category.get_cost_behavior_display().split(" (")[0],
                    "fixed": expense.amount, "variable_rate": expense.variable_rate,
                    "basis": BASIS_LABELS[category.variable_basis],
                    # Tekrarlamayan kayıt: yalnız o aya ait tek seferlik gider (ör. tadilat). Raporda ayrıca işaretlenir.
                    "one_off": expense.recurs_monthly == MonthlyHotelExpense.MonthlyRepeat.NO and expense.amount > 0,
                    "description": expense.description,
                })
            days = calendar.monthrange(year, month)[1]
            available_room_nights = self.active_rooms * days
            # Gece başına pay YILLIK esasla: aylık tutar ÷ (oda × ortalama ay uzunluğu, 365 ÷ 12 gün). Ayın 28 ya da 31 gün
            # çekmesi bir gecenin maliyetini değiştirmez; Şubat gecesi sırf ay kısa diye pahalı görünmez. Ay içinde
            # dağıtılan toplam ayın tutarından biraz az ya da fazla olur, yıl boyunca (365 gün) tam tutar dağıtılır.
            nightly_base = self.active_rooms * average_month_days(year)
            for group in groups.values():
                group["fixed_per_night"] = group["fixed"] / nightly_base if nightly_base else ZERO
                group["lines"].sort(key=lambda line: line["name"])
            self._months[key] = {
                "days": days,
                "available_room_nights": available_room_nights,
                "fixed_total": fixed_total,
                "semi_fixed_total": semi_fixed_total,
                "fixed_per_night": fixed_total / nightly_base if nightly_base else ZERO,
                "semi_fixed_per_night": semi_fixed_total / nightly_base if nightly_base else ZERO,
                "variable_room": variable_room,      # TL / satılan oda-gece (ortalama oda)
                "variable_guest": variable_guest,    # TL / konaklayan kişi-gece
                "variable_stay": variable_stay,      # TL / konaklama (giriş-çıkış başına bir kez)
                "groups": sorted(groups.values(), key=lambda group: group["order"]),
            }
        return self._months[key]

    def breakfast(self):
        """Etkin büfenin (adı, kişi başı maliyeti). Tek kaynak: admin'deki Kahvaltı büfesi ekranı."""
        name, food, service = self.breakfast_parts()
        return name, food + service

    def breakfast_parts(self):
        """Kahvaltı büfesi: (adı, kişi başı GIDA maliyeti, kişi başı RESTORAN SARFI maliyeti).

        Büfe satırı, ürünün kategorisi mutfak/bar ise gıda; değilse restoranın servis sarfıdır
        (peçete, ıslak mendil, bulaşık deterjanı vb.). İkisi de kişi sayısıyla artar.
        """
        if self._breakfast is None:
            food = service = ZERO
            lines = list(BreakfastBuffetItem.objects.filter(active=True).select_related("item"))
            for line in lines:
                if line.is_service_supply:
                    service += line.line_cost
                else:
                    food += line.line_cost
            self._breakfast = ("Kahvaltı büfesi" if lines else None, food, service)
        return self._breakfast


def _room_package_cost(guests, room_type):
    """(sarf oda-gece, sarf kişi-gece, tekstil oda-gece, tekstil kişi-gece) maliyetleri."""
    room_based = guest_based = textile_room = textile_guest = ZERO
    if not room_type:
        return room_based, guest_based, textile_room, textile_guest
    # Oda paketi bütün oda tiplerinde aynıdır; misafir sayısına göre tutulur.
    for component in RoomPackageItem.objects.filter(guest_count=guests, active=True).select_related("item"):
        per_guest = component.basis == RoomPackageItem.Basis.PER_GUEST_NIGHT
        if component.is_textile:
            # Tekstil yıpranır: set maliyeti (hurda düşülmüş) × oda başı set ÷ ömür × miktar (kişi esasında × kişi)
            cost = component.item.textile_cost(guests if per_guest else 1) * component.quantity
            if per_guest:
                textile_guest += cost
            else:
                textile_room += cost
        else:
            waste_rate = max(component.waste_rate, component.item.wastage_rate)
            cost = component.quantity * (ONE + waste_rate) * component.item.average_unit_cost
            if per_guest:
                guest_based += cost * guests
            else:
                room_based += cost
    return room_based, guest_based, textile_room, textile_guest


# --------------------------------------------------------------------------- doluluk

def occupied_room_ids(day):
    """Verilen gece dolu olan odaların kimlikleri (giriş günü dahil, çıkış günü hariç)."""
    return set(Stay.objects.occupying().filter(check_in__lte=day, check_out__gt=day).values_list("room_id", flat=True))


def month_occupancy(year, month, as_of=None):
    """Ayın doluluğunu konaklama kayıtlarından hesaplar; ay için hiç konaklama yoksa None döner.

    Doluluk = dolu oda-gece ÷ müsait oda-gece.
    İçinde bulunulan ayda yalnızca bugüne kadar geçen günler sayılır (ay bitmeden ileri tarihli boş
    geceler doluluğu olduğundan düşük göstermesin diye). Geçmiş ve gelecek aylarda ayın tamamı sayılır;
    gelecek ay için sonuç, şimdiden girilmiş konaklamaların (rezervasyonların) doluluğudur.
    """
    as_of = as_of or timezone.localdate()
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)          # ayın bitişi, hariç
    if start <= as_of < end:
        end = as_of + timedelta(days=1)
    days_counted = (end - start).days

    occupied = guest_nights = 0
    for check_in, check_out, guests in Stay.objects.occupying().filter(check_in__lt=end, check_out__gt=start).values_list(
            "check_in", "check_out", "guests"):
        nights = (min(check_out, end) - max(check_in, start)).days   # konaklamanın bu döneme düşen geceleri
        occupied += nights
        guest_nights += nights * guests
    available = _active_room_count() * days_counted
    frozen = closed_period(year, month)
    if frozen:                                   # kapanmış ay: o ayın oda sayısı ve satışı
        occupied, available = frozen.occupied_room_nights, frozen.available_room_nights
    if not occupied or not available:
        return None
    return {
        "rate": Decimal(occupied) / Decimal(available),
        "occupied_room_nights": occupied,
        "available_room_nights": available,
        "guest_nights": guest_nights,
        "days_counted": days_counted,
    }


def average_stay_nights(year, month):
    """O ay giriş yapan konaklamaların ortalama gece sayısı; kayıt yoksa None."""
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    lengths = [(check_out - check_in).days for check_in, check_out in
               Stay.objects.occupying().filter(check_in__gte=start, check_in__lt=end).values_list("check_in", "check_out")]
    return Decimal(sum(lengths)) / Decimal(len(lengths)) if lengths else None


def monthly_overview(year, as_of=None):
    """Yılın aylarının özeti (geçmiş aylar ve içinde bulunulan ay): doluluk ve ortak giderin karşılanma durumu.

    Bir ayın analizi ay bitince kesinleşir; içinde bulunulan ay "devam ediyor" olarak işaretlenir.
    """
    as_of = as_of or timezone.localdate()
    last_month = 12 if year < as_of.year else (as_of.month if year == as_of.year else 0)
    context = _CostContext()
    rows, cache = [], {}
    for month in range(1, last_month + 1):
        period = context.month(year, month)
        frozen = closed_period(year, month)
        start, end = month_bounds(year, month)
        complete = (year, month) < (as_of.year, as_of.month)
        # Devam eden ayda bütün sütunlar AYNI dönem için: ayın başından bugüne kadar geçen günler.
        counted_end = end if complete else min(end, as_of + timedelta(days=1))
        days_counted = (counted_end - start).days
        shared_month = frozen.shared_total if frozen else period["fixed_total"] + period["semi_fixed_total"]
        shared = shared_month * Decimal(days_counted) / Decimal(period["days"])
        occupancy = month_occupancy(year, month, as_of)
        rate = occupancy["rate"] if occupancy else None
        occupied = occupancy["occupied_room_nights"] if occupancy else 0
        normal, _ = normal_occupancy_for_month(year, month, as_of, cache)
        absorption = month_absorption(year, month, as_of, context, cache)
        # Ayın sonucu (kâr / zarar) = oda geliri − kanal komisyonu − değişken gider − sabit gider.
        if frozen:
            revenue, commission, variable = frozen.room_revenue, frozen.commission_total, frozen.variable_total
        else:
            sales = month_sales(year, month, end=counted_end)
            revenue, commission = sales["revenue"], sales["commission"]
            variable = variable_cost_of_sales(calculate_monthly_room_cost(year, month, as_of)["rows"], sales["combos"])
        one_off = [line for group in period["groups"] for line in group["lines"] if line["one_off"]]
        rows.append({
            "month": start,
            "complete": complete,
            "closed": frozen is not None,
            "days_counted": days_counted, "days": period["days"],
            "rate": rate,
            "percent": rate * 100 if rate is not None else None,
            "occupied_room_nights": occupied,
            "guest_nights": occupancy["guest_nights"] if occupancy else 0,
            "available_room_nights": occupancy["available_room_nights"] if occupancy else period["available_room_nights"],
            "shared_total": shared,
            "shared_per_sold_night": shared / occupied if occupied else None,
            "idle_cost": shared * (ONE - rate) if rate is not None else None,
            # Normal doluluğa göre fark: + yazın fazla karşılanan, − kışın eksik kalan (12 ayda dengelenir).
            "absorption": absorption["difference"] if absorption else None,
            "normal_rate": normal,
            "used_cost": shared * rate if rate is not None else None,
            "revenue": revenue, "commission": commission, "variable": variable,
            # Toplam gider = kanal komisyonu + misafir gelince harcanan + otelin sabit gideri; karşılama = gelir ÷ toplam gider.
            "total_cost": commission + variable + shared,
            "coverage": revenue / (commission + variable + shared) if commission + variable + shared else None,
            "result": revenue - commission - variable - shared,
            "one_off": one_off,
        })
    return rows


def overview_totals(rows):
    """Aylık özet tablosunun toplam satırı ve kâr / zarar yorumu (tablodaki aylardan hesaplanır, yıl değişince değişir)."""
    if not rows:
        return None
    total = lambda key: sum((row[key] for row in rows if row[key] is not None), ZERO)
    occupied = sum(row["occupied_room_nights"] for row in rows)
    available = sum(row["available_room_nights"] for row in rows)
    shared, result = total("shared_total"), total("result")
    return {
        "first": rows[0]["month"], "last": rows[-1]["month"], "count": len(rows),
        "partial": rows[-1] if not rows[-1]["complete"] else None,
        "rate": Decimal(occupied) / Decimal(available) if available else None,
        "occupied": occupied, "available": available,
        "shared_total": shared, "shared_per_sold_night": shared / occupied if occupied else None,
        "idle_cost": total("idle_cost"), "absorption": total("absorption"),
        "revenue": total("revenue"), "commission": total("commission"), "variable": total("variable"),
        "total_cost": total("total_cost"),
        "coverage": total("revenue") / total("total_cost") if total("total_cost") else None,
        "result": result, "profitable": result >= 0,
        "profit_months": sum(1 for row in rows if row["result"] >= 0),
        "loss_months": sum(1 for row in rows if row["result"] < 0),
        "best": max(rows, key=lambda row: row["result"]), "worst": min(rows, key=lambda row: row["result"]),
        "one_off": sum((line["fixed"] for row in rows for line in row["one_off"]), ZERO),
    }


def last_completed_month(as_of=None):
    as_of = as_of or timezone.localdate()
    first = as_of.replace(day=1)
    return first - timedelta(days=1)


def _occupancy_view(shared_per_available_night, rate):
    """Müsait oda-geceye dağıtılmış payı, satılan oda-geceye çevirir (pay ÷ doluluk)."""
    if not rate or rate <= 0:
        return None
    return shared_per_available_night / rate


# --------------------------------------------------------------------------- raporlar

def calculate_monthly_room_cost(year, month, as_of=None, live=False):
    """Bir oda-gecenin maliyetini oda tipi ve kişi sayısına göre verir.

    Dönem giderleri müsait oda-geceye dağıtılır ve oda tipinin maliyet payı katsayısıyla ağırlıklandırılır.
    Konaklama kaydı varsa satılan oda başına pay ve atıl kapasite maliyeti de hesaplanır.
    """
    context = _CostContext()
    period = context.month(year, month)
    days = period["days"]
    fixed_per_night, semi_fixed_per_night = period["fixed_per_night"], period["semi_fixed_per_night"]
    variable_room, variable_guest, variable_stay = period["variable_room"], period["variable_guest"], period["variable_stay"]
    _, breakfast_per_guest, restaurant_per_guest = context.breakfast_parts()
    material = material_index(year)                   # geçmiş yılın hammadde fiyat seviyesi (v75)
    breakfast_per_guest, restaurant_per_guest = breakfast_per_guest * material, restaurant_per_guest * material
    room_types = list(RoomType.objects.filter(active=True).order_by("standard_cost_factor", "code"))
    view_counts = {}
    for item in Room.objects.filter(status=Room.Status.ACTIVE).values("room_type_id", "view_type").annotate(count=Count("id")):
        view_counts.setdefault(item["room_type_id"], {})[item["view_type"]] = item["count"]
    view_labels = dict(Room.ViewType.choices)

    occupancy = month_occupancy(year, month, as_of)
    rate = occupancy["rate"] if occupancy else None

    # "Konaklama başına" giderler geceye çevrilirken ayın ortalama konaklama süresine bölünür.
    measured_stay_nights = average_stay_nights(year, month)
    stay_nights = measured_stay_nights or DEFAULT_STAY_NIGHTS
    overhead_stay = variable_stay / stay_nights

    distribution, rows = [], []
    for room_type in room_types:
        views = view_counts.get(room_type.id, {})
        sea = views.get(Room.ViewType.SEA, 0)
        total_rooms = sum(views.values())
        factor = context.room_factor(room_type)
        fixed, semi_fixed = context.share(fixed_per_night, room_type), context.share(semi_fixed_per_night, room_type)
        shared = fixed + semi_fixed
        shared_sold = _occupancy_view(shared, rate)
        distribution.append({
            "name": room_type.name, "code": room_type.code, "capacity": room_type.max_guests,
            "sea_count": sea, "count": total_rooms,
            "views": ", ".join(f"{view_labels.get(view, view)} {count}" for view, count in sorted(views.items())),
            "weight": room_type.standard_cost_factor, "factor": factor,
            "shared_per_night": shared, "shared_per_sold_night": shared_sold,
        })
        if not total_rooms:
            continue                                   # satışa açık odası olmayan tip tabloya girmez
        # Giderlerin oda başına değişken kısmı (elektrik, bakım vb.) da odanın büyüklüğüyle orantılıdır.
        overhead_room = context.share(variable_room, room_type)
        for guests in range(1, room_type.max_guests + 1):
            amenity_room, amenity_guest, textile_room, textile_guest = (
                cost * material for cost in _room_package_cost(guests, room_type))
            overhead_guest = variable_guest * guests
            variable_overhead = overhead_room + overhead_guest + overhead_stay
            breakfast = breakfast_per_guest * guests
            restaurant = restaurant_per_guest * guests
            variable = (breakfast + restaurant + amenity_room + amenity_guest + textile_room + textile_guest
                        + variable_overhead)
            total = variable + shared
            rows.append({
                "room_type": room_type.name, "room_type_code": room_type.code, "room_type_id": room_type.id,
                "guests": guests, "room_count": total_rooms, "breakfast": breakfast, "restaurant": restaurant,
                "amenities": amenity_room + amenity_guest, "textile": textile_room + textile_guest,
                "variable_overhead": variable_overhead,
                "semi_fixed": semi_fixed, "fixed": fixed,
                "variable": variable,
                "total": total, "per_person": total / Decimal(guests),
                # Gerçekleşen dolulukta, satılan bir oda-gecenin taşıması gereken tam maliyet.
                "total_at_occupancy": variable + shared_sold if shared_sold is not None else None,
                "cost_groups": {
                    "room_night": amenity_room + textile_room + overhead_room,
                    "guest_night": breakfast + restaurant + amenity_guest + textile_guest + overhead_guest,
                    "per_stay": overhead_stay,
                    "monthly_shared": shared,
                },
            })

    frozen = None if live else closed_period(year, month)          # live: kapanmış ayı güncel kayıtlarla hesapla
    shared_month = period["fixed_total"] + period["semi_fixed_total"]
    available_month = period["available_room_nights"]
    if frozen:
        rows = _frozen_rows(frozen, rows, rate)
        shared_month = frozen.shared_total
        available_month = frozen.available_room_nights

    if occupancy:
        normal_month, normal_month_source = normal_occupancy_for_month(year, month, as_of)
        # Gerçekleşen: ayın ortak gideri ayın gerçek müsait gecelerine, sonra satılan gecelere (devam eden ayda bugüne kadar).
        monthly_shared_per_sold_night = _occupancy_view(shared_month / available_month, rate) if available_month else None
        occupancy.update({
            "percent": rate * 100,
            "fixed_per_sold_night": monthly_shared_per_sold_night,
            "monthly_shared_per_sold_night": monthly_shared_per_sold_night,
            # Atıl kapasite maliyeti: boş kalan oda-gecelere düşen, satışla karşılanmayan sabit gider
            # (sabit kalemler + yarı değişken kalemlerin sabit tabanı). Değişken kısım girmez: oda
            # satılmadıysa o gider zaten oluşmamıştır.
            "idle_capacity_cost": shared_month * (ONE - rate),
            "shared_total": shared_month,
            # Olağan dışı boşluk ay ay değil, mevsimleri kapsayan 12 ayda değerlendirilir: absorption_window.
            "normal_rate": normal_month,
            "normal_source": normal_month_source,
            "complete": occupancy["days_counted"] >= days,
        })

    return {
        "month": date(year, month, 1),
        "frozen": frozen,
        "rows": rows, "days": days, "active_rooms": context.active_rooms,
        "shared_total": shared_month,
        "fixed_monthly_total": period["fixed_total"],
        "semi_fixed_monthly_total": period["semi_fixed_total"],
        "variable_room": variable_room,
        "variable_guest": variable_guest,
        "variable_stay": variable_stay,
        "stay_nights": stay_nights,
        "stay_nights_measured": measured_stay_nights is not None,
        "expense_groups": period["groups"],
        "fixed_per_night": fixed_per_night,
        "room_distribution": distribution,
        "sea_view_rooms": sum(item["sea_count"] for item in distribution),
        "occupancy": occupancy,
    }


def _frozen_rows(frozen, live_rows, rate):
    """Kapanmış ayın satırları: oda tipi × kişi maliyeti kapanıştaki (o ayın fiyatlarıyla) değerlerle değiştirilir.

    Kalem kırılımı (kahvaltı, sarf, tekstil...) saklanmaz; kapanmış ayda yalnızca değişken toplam ve ortak gider payı
    vardır. Kapanışta olmayan bir birleşim (sonradan eklenen oda tipi ya da kişi sayısı) tabloya alınmaz.
    """
    costs = {(cost.room_type_id, cost.guests): cost for cost in frozen.cost_rows()}
    rows = []
    for row in live_rows:
        cost = costs.get((row["room_type_id"], row["guests"]))
        if cost is None:
            continue
        shared_sold = _occupancy_view(cost.shared, rate)
        total = cost.variable + cost.shared
        rows.append(dict(row, breakfast=None, restaurant=None, amenities=None, textile=None, variable_overhead=None,
                         semi_fixed=ZERO, fixed=cost.shared, variable=cost.variable, total=total,
                         per_person=total / Decimal(row["guests"]),
                         total_at_occupancy=cost.variable + shared_sold if shared_sold is not None else None,
                         cost_groups={"monthly_shared": cost.shared}))
    return rows


def calculate_stay_quote(room_type, guests, check_in, check_out, expected_occupancy=None):
    """Rezervasyon tarihleri ve kişi sayısına göre yalnızca maliyet tahmini verir.

    expected_occupancy: 0-1 arası beklenen doluluk oranı (isteğe bağlı). Verilirse aylık
    ortak giderlerin satılan oda başına düşen payı da hesaplanır.
    """
    nights = (check_out - check_in).days
    context = _CostContext()
    buffet_name, breakfast_per_guest, restaurant_per_guest = context.breakfast_parts()
    totals = {key: ZERO for key in ("breakfast", "restaurant", "amenities", "textile", "variable_overhead", "per_stay",
                                    "semi_fixed", "fixed")}
    amenity_room, amenity_guest, textile_room, textile_guest = _room_package_cost(guests, room_type)
    variable_room_night = ZERO
    variable_guest_night = ZERO
    # Oda tipinin ortak giderlerden aldığı pay (ortalama oda = 1).
    factor = context.room_factor(room_type)
    # Konaklama başına giderler gece sayısından bağımsızdır; giriş ayının tutarıyla bir kez eklenir.
    if nights > 0:
        totals["per_stay"] = context.month(check_in.year, check_in.month)["variable_stay"]

    indexes = {}
    for offset in range(nights):
        night = check_in + timedelta(days=offset)
        period = context.month(night.year, night.month)
        if night.year not in indexes:
            indexes[night.year] = material_index(night.year)          # hammadde fiyat seviyesi (v75)
        m = indexes[night.year]
        overhead_room, overhead_guest = context.share(period["variable_room"], room_type), period["variable_guest"] * guests
        totals["amenities"] += (amenity_room + amenity_guest) * m
        totals["textile"] += (textile_room + textile_guest) * m
        totals["breakfast"] += breakfast_per_guest * guests * m
        totals["restaurant"] += restaurant_per_guest * guests * m
        variable_room_night += (amenity_room + textile_room) * m + overhead_room
        variable_guest_night += (((breakfast_per_guest + restaurant_per_guest) * guests + amenity_guest + textile_guest) * m
                                 + overhead_guest)
        totals["variable_overhead"] += overhead_room + overhead_guest
        totals["semi_fixed"] += context.share(period["semi_fixed_per_night"], room_type)
        totals["fixed"] += context.share(period["fixed_per_night"], room_type)

    total = sum(totals.values(), ZERO)
    variable_total = variable_room_night + variable_guest_night + totals["per_stay"]
    monthly_shared = totals["semi_fixed"] + totals["fixed"]

    at_occupancy = None
    if expected_occupancy and expected_occupancy > 0:
        shared_at_occupancy = monthly_shared / expected_occupancy
        at_occupancy = {
            "percent": expected_occupancy * 100,
            "monthly_shared": shared_at_occupancy,
            "grand_total": variable_total + shared_at_occupancy,
            "per_night": (variable_total + shared_at_occupancy) / Decimal(nights) if nights else ZERO,
        }

    return {
        "nights": nights,
        "check_in": check_in,
        "check_out": check_out,
        "room_type": room_type,
        "guests": guests,
        "totals": totals,
        "grand_total": total,
        "per_night": total / Decimal(nights) if nights else ZERO,
        "per_person": total / Decimal(guests) if guests else ZERO,
        "per_person_per_night": total / Decimal(guests * nights) if guests and nights else ZERO,
        # Değişken maliyet: oda satılmazsa oluşmayan maliyet. Kısa vadede fiyatın inebileceği taban.
        "variable_total": variable_total,
        "variable_per_night": variable_total / Decimal(nights) if nights else ZERO,
        "at_occupancy": at_occupancy,
        "cost_groups": {
            "room_night": variable_room_night,
            "guest_night": variable_guest_night,
            "per_stay": totals["per_stay"],
            "monthly_shared": monthly_shared,
        },
        "room_factor": factor,
        "unit_costs": {
            "breakfast_buffet": buffet_name,
            "breakfast_per_guest_night": breakfast_per_guest,
            "restaurant_per_guest_night": restaurant_per_guest,
            "room_package_per_night": amenity_room + amenity_guest + textile_room + textile_guest,
        },
    }


# --------------------------------------------------------------------------- satış ve dönem kapanışı

def month_bounds(year, month):
    start = date(year, month, 1)
    return start, date(year + (month == 12), month % 12 + 1, 1)


def month_sales(year, month, end=None):
    """Ayın satışları (onaylanan konaklamalar, ayın bütün geceleri): oda-gece, gelir, oda tipi ve kanal kırılımı.

    Gelir = gecelik fiyat × konaklamanın bu aya düşen gecesi. Fiyatı girilmemiş geceler gelire girmez,
    ayrıca sayılır (priced_room_nights < room_nights ise gelir eksiktir). end verilirse yalnız o güne kadarki geceler
    (devam eden ayın bugüne kadarki satışı).
    """
    start, month_end = month_bounds(year, month)
    end = min(end, month_end) if end else month_end
    result = {"room_nights": 0, "guest_nights": 0, "priced_room_nights": 0, "revenue": ZERO,
              "combos": {}, "room_types": {}, "channels": {}}
    for room_type_id, guests, rate, channel_id, check_in, check_out in (
            Stay.objects.occupying().filter(check_in__lt=end, check_out__gt=start)
            .values_list("room__room_type_id", "guests", "nightly_rate", "channel_id", "check_in", "check_out")):
        nights = (min(check_out, end) - max(check_in, start)).days
        revenue = rate * nights if rate is not None else ZERO
        result["room_nights"] += nights
        result["guest_nights"] += nights * guests
        result["revenue"] += revenue
        if rate is not None:
            result["priced_room_nights"] += nights
        result["combos"][(room_type_id, guests)] = result["combos"].get((room_type_id, guests), 0) + nights
        for key, bucket in ((room_type_id, result["room_types"]), (channel_id, result["channels"])):
            entry = bucket.setdefault(key, {"room_nights": 0, "priced_room_nights": 0, "revenue": ZERO})
            entry["room_nights"] += nights
            entry["revenue"] += revenue
            if rate is not None:
                entry["priced_room_nights"] += nights
    rates = dict(SalesChannel.objects.values_list("id", "commission_rate"))
    result["commission"] = sum((values["revenue"] * rates.get(channel_id, ZERO)
                                for channel_id, values in result["channels"].items()), ZERO)
    return result


def variable_cost_of_sales(rows, combos):
    """Satılan oda-gecelerin değişken maliyeti: Σ (oda tipi × kişi sayısı birim değişken maliyeti × gece)."""
    unit = {(row["room_type_id"], row["guests"]): row["variable"] for row in rows}
    return sum((unit.get(combo, ZERO) * nights for combo, nights in combos.items()), ZERO)


def close_month(year, month, as_of=None, reopen=False, notes=""):
    """Ayı kapatır: o ayın fiyatlarıyla doluluk, satış, giderler ve oda tipi × kişi birim maliyetleri dondurulur.

    İçinde bulunulan ay ve gelecek aylar kapatılamaz. reopen=True: eski kapanış silinip güncel kayıtlarla yeniden kapatılır
    (ör. ayın geç gelen bir faturası girildikten sonra).
    """
    as_of = as_of or timezone.localdate()
    if (year, month) >= (as_of.year, as_of.month):
        raise ValidationError(f"{month:02d}.{year} henüz bitmedi; yalnızca geçmiş aylar kapatılabilir.")
    start, end = month_bounds(year, month)
    cent = Decimal("0.01")
    with transaction.atomic():
        existing = ClosedPeriod.objects.filter(month=start).first()
        if existing:
            if not reopen:
                raise ValidationError(f"{month:02d}.{year} zaten kapatılmış ({existing.closed_at:%d.%m.%Y}).")
            existing.delete()
        summary = calculate_monthly_room_cost(year, month, as_of)       # kapanış yok: güncel kayıtlarla
        sales = month_sales(year, month)
        period = ClosedPeriod.objects.create(
            month=start,
            available_room_nights=summary["active_rooms"] * (end - start).days,
            occupied_room_nights=sales["room_nights"],
            room_revenue=sales["revenue"].quantize(cent),
            commission_total=sales["commission"].quantize(cent),
            variable_total=variable_cost_of_sales(summary["rows"], sales["combos"]).quantize(cent),
            shared_total=summary["shared_total"].quantize(cent),
            notes=notes[:240],
            costs_data=[{"room_type_id": row["room_type_id"], "guests": row["guests"],
                         "variable": str(row["variable"].quantize(cent)),
                         "shared": str((row["semi_fixed"] + row["fixed"]).quantize(cent))} for row in summary["rows"]],
        )
    return period


def auto_close_months(today=None):
    """Bekleme süresi dolmuş, kapatılmamış ayları kapatır; kapatılan ayları döndürür.

    Ekranlar açılırken çağrılır; komut gerekmez. Bekleme 5 gün ise Eylül, 6 Ekim'den itibaren ilk açılan ekranda kapanır
    (ayın geç gelen faturaları için süre). Aynı anda iki istek aynı ayı kapatmaya çalışırsa ikincisi atlanır.
    """
    from django.db import IntegrityError

    today = today or timezone.localdate()
    grace = getattr(settings, "PERIOD_CLOSE_GRACE_DAYS", 5)
    complete_closed_costs(today)
    closed = []
    for month in months_to_close(as_of=today - timedelta(days=grace)):
        try:
            closed.append(close_month(month.year, month.month, as_of=today, notes="Otomatik kapanış"))
        except (IntegrityError, ValidationError):
            continue
    return closed


def complete_closed_costs(as_of=None):
    """Kapanıştan sonra eklenen oda tipi × kişi birleşimlerini (ör. kapasitesi artan oda tipi) kapanmış aylara ekler.

    Kapanmış ayın diğer değerlerine dokunulmaz. Yeni satırın sabit gider payı, aynı oda tipinin o ayda dondurulmuş payıdır
    (kişi sayısıyla değişmez); değişken maliyet o ayın gider kayıtları ve güncel ürün maliyetleriyle hesaplanır.
    Eklenen satır sayısını döndürür.
    """
    as_of = as_of or timezone.localdate()
    room_counts = set(Room.objects.filter(status=Room.Status.ACTIVE, room_type__active=True)
                      .values_list("room_type_id", flat=True))
    combos = {(room_type.id, guests) for room_type in RoomType.objects.filter(id__in=room_counts)
              for guests in range(1, room_type.max_guests + 1)}
    cent, added = Decimal("0.01"), 0
    for period in ClosedPeriod.objects.all():
        costs = period.cost_rows()
        missing = combos - {(cost.room_type_id, cost.guests) for cost in costs}
        if not missing:
            continue
        shared_by_type = {cost.room_type_id: cost.shared for cost in costs}
        rows = calculate_monthly_room_cost(period.month.year, period.month.month, as_of, live=True)["rows"]
        new = [row for row in rows if (row["room_type_id"], row["guests"]) in missing]
        for row in new:
            period.set_cost(row["room_type_id"], row["guests"], row["variable"].quantize(cent),
                            shared_by_type.get(row["room_type_id"], (row["semi_fixed"] + row["fixed"]).quantize(cent)))
        period.save(update_fields=["costs_data"])
        added += len(new)
    return added


def months_to_close(as_of=None):
    """Kapatılabilecek ama henüz kapatılmamış aylar: ilk gider kaydının ayından geçen aya kadar.

    Gider kaydı olmayan aylar (sistem kurulmadan önceki konaklama geçmişi) kapatılmaz: maliyeti yoktur.
    """
    as_of = as_of or timezone.localdate()
    first = MonthlyHotelExpense.objects.order_by("expense_month").values_list("expense_month", flat=True).first()
    if not first:
        return []
    closed = set(ClosedPeriod.objects.values_list("month", flat=True))
    cursor, months = first.replace(day=1), []
    while (cursor.year, cursor.month) < (as_of.year, as_of.month):
        if cursor not in closed:
            months.append(cursor)
        cursor = month_bounds(cursor.year, cursor.month)[1]
    return months


# --------------------------------------------------------------------------- fiyatlandırma dashboard'u

def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def pricing_overview(year, as_of=None):
    """Fiyatlandırma dashboard'unun verisi: ay, oda tipi, kanal ve mevsim kırılımında satış ve maliyet.

    Kapanmış aylar kapanıştaki (o ayın fiyatlarıyla) değerlerden, diğer aylar güncel kayıtlardan hesaplanır. İçinde bulunulan ve gelecek aylarda satış, şimdiden girilmiş (onaylı) konaklamalardır.
    Tutarlar TL, KDV hariç. Tanımlar:
      ADR    = oda geliri ÷ fiyatı girilmiş satılan oda-gece (ortalama gecelik fiyat)
      RevPAR = oda geliri ÷ müsait oda-gece (müsait oda başına gelir)
      Başabaş doluluğu = ortak gider ÷ (müsait oda-gece × (ADR − oda-gece başına değişken maliyet))
    """
    as_of = as_of or timezone.localdate()
    months, room_types, channels = [], {}, {}
    labels = dict(Season.choices)
    season_of = {month: labels.get(code, "") for month, code in season_map().items()}
    type_rooms = dict(Room.objects.filter(status=Room.Status.ACTIVE, room_type__active=True)
                      .values("room_type_id").annotate(count=Count("id")).values_list("room_type_id", "count"))
    for month in range(1, 13):
        summary = calculate_monthly_room_cost(year, month, as_of)
        sales = month_sales(year, month)
        days = summary["days"]
        frozen = summary["frozen"]
        if frozen:
            room_nights, revenue = frozen.occupied_room_nights, frozen.room_revenue
            priced, available = frozen.occupied_room_nights, frozen.available_room_nights
            variable, shared, commission = frozen.variable_total, frozen.shared_total, frozen.commission_total
        else:
            room_nights, revenue, priced = sales["room_nights"], sales["revenue"], sales["priced_room_nights"]
            commission = sales["commission"]
            available = summary["active_rooms"] * days
            variable = variable_cost_of_sales(summary["rows"], sales["combos"])
            shared = summary["shared_total"]
        if frozen:
            status = "closed"
        elif (year, month) < (as_of.year, as_of.month):
            status = "ended"
        elif (year, month) == (as_of.year, as_of.month):
            status = "current"
        else:
            status = "future"
        adr = _ratio(revenue, priced)
        # Komisyon satışla birlikte oluşan bir giderdir: başabaş hesabında değişken maliyete eklenir.
        variable_per_night = _ratio(variable + commission, room_nights)
        margin_per_night = adr - variable_per_night if adr is not None and variable_per_night is not None else None
        result = revenue - variable - shared - commission
        months.append({
            "month": date(year, month, 1), "status": status, "season": season_of.get(month, ""),
            "available": available, "room_nights": room_nights, "priced": priced,
            "occupancy": _ratio(Decimal(room_nights), Decimal(available)),
            "revenue": revenue, "variable": variable, "shared": shared, "commission": commission,
            "total_cost": variable + shared,
            "adr": adr, "revpar": _ratio(revenue, Decimal(available)),
            "cost_per_night": _ratio(variable + shared, Decimal(room_nights)),
            "variable_per_night": variable_per_night,
            "result": result, "margin": _ratio(result, revenue),
            "breakeven": (shared / (available * margin_per_night)
                          if margin_per_night and margin_per_night > 0 and available else None),
        })
        # Oda tipi: değişken maliyet satılan gecelerden; ortak gider oda tipinin müsait gecelerine düşen pay.
        unit_variable = {(row["room_type_id"], row["guests"]): row["variable"] for row in summary["rows"]}
        unit_shared = {row["room_type_id"]: row["semi_fixed"] + row["fixed"] for row in summary["rows"]}
        for (room_type_id, guests), nights in sales["combos"].items():
            entry = room_types.setdefault(room_type_id, {"room_nights": 0, "priced": 0, "revenue": ZERO,
                                                         "variable": ZERO, "shared": ZERO})
            entry["variable"] += unit_variable.get((room_type_id, guests), ZERO) * nights
        for room_type_id, values in sales["room_types"].items():
            entry = room_types[room_type_id]
            entry["room_nights"] += values["room_nights"]
            entry["priced"] += values["priced_room_nights"]
            entry["revenue"] += values["revenue"]
        for room_type_id, per_night in unit_shared.items():
            entry = room_types.setdefault(room_type_id, {"room_nights": 0, "priced": 0, "revenue": ZERO,
                                                         "variable": ZERO, "shared": ZERO})
            entry["shared"] += per_night * type_rooms.get(room_type_id, 0) * days
        for channel_id, values in sales["channels"].items():
            entry = channels.setdefault(channel_id, {"room_nights": 0, "revenue": ZERO})
            entry["room_nights"] += values["room_nights"]
            entry["revenue"] += values["revenue"]

    def summarize(rows):
        available = sum(row["available"] for row in rows)
        room_nights = sum(row["room_nights"] for row in rows)
        priced = sum(row["priced"] for row in rows)
        revenue = sum((row["revenue"] for row in rows), ZERO)
        variable = sum((row["variable"] for row in rows), ZERO)
        shared = sum((row["shared"] for row in rows), ZERO)
        commission = sum((row["commission"] for row in rows), ZERO)
        result = revenue - variable - shared - commission
        adr = _ratio(revenue, priced)
        variable_per_night = _ratio(variable + commission, room_nights)
        unit_margin = adr - variable_per_night if adr is not None and variable_per_night is not None else None
        return {"available": available, "room_nights": room_nights, "revenue": revenue, "variable": variable,
                "commission": commission,
                "breakeven": shared / (available * unit_margin) if unit_margin and unit_margin > 0 and available else None,
                "variable_per_night": variable_per_night,
                "shared": shared, "total_cost": variable + shared, "result": result,
                "occupancy": _ratio(Decimal(room_nights), Decimal(available)), "adr": adr,
                "revpar": _ratio(revenue, Decimal(available)),
                "cost_per_night": _ratio(variable + shared, Decimal(room_nights)), "margin": _ratio(result, revenue)}

    seasons = []
    for name in dict.fromkeys(season_of.get(m) for m in range(1, 13) if season_of.get(m)):
        rows = [row for row in months if row["season"] == name]
        seasons.append(dict(summarize(rows), name=name,
                            months=", ".join(f"{row['month']:%m}" for row in rows)))

    type_rows = []
    for room_type in RoomType.objects.filter(id__in=room_types).order_by("standard_cost_factor", "code"):
        entry = room_types[room_type.id]
        cost = entry["variable"] + entry["shared"]
        adr, cost_per_night = _ratio(entry["revenue"], entry["priced"]), _ratio(cost, entry["room_nights"])
        type_rows.append({
            "gap": adr - cost_per_night if adr is not None and cost_per_night is not None else None,
            "name": room_type.name, "rooms": type_rooms.get(room_type.id, 0), "room_nights": entry["room_nights"],
            "revenue": entry["revenue"], "adr": adr,
            "variable_per_night": _ratio(entry["variable"], entry["room_nights"]),
            "cost_per_night": cost_per_night,
            "result": entry["revenue"] - cost, "margin": _ratio(entry["revenue"] - cost, entry["revenue"]),
        })

    names = dict(SalesChannel.objects.values_list("id", "name"))
    commissions = dict(SalesChannel.objects.values_list("id", "commission_rate"))
    total_nights = sum(entry["room_nights"] for entry in channels.values())
    channel_rows = sorted(({
        "name": names.get(channel_id, "Belirtilmemiş"), "room_nights": entry["room_nights"],
        "commission_rate": commissions.get(channel_id, ZERO),
        "commission": entry["revenue"] * commissions.get(channel_id, ZERO),
        "revenue": entry["revenue"], "share": _ratio(Decimal(entry["room_nights"]), Decimal(total_nights)),
        "adr": _ratio(entry["revenue"], entry["room_nights"]),
    } for channel_id, entry in channels.items()), key=lambda row: -row["room_nights"])

    return {
        "months": months, "year": summarize(months), "closed_count": sum(row["status"] == "closed" for row in months),
        "seasons": seasons, "room_types": type_rows, "channels": channel_rows,
        "unpriced": sum(row["room_nights"] - row["priced"] for row in months),
    }


# --------------------------------------------------------------------------- fiyat takvimi

PRICE_STATUS = {
    "good": "Hedefte",                       # önerilen fiyat ≥ hedef fiyat (tam maliyet + hedef marj)
    "warning": "Kârlı, hedefin altında",     # tam maliyet ≤ fiyat < hedef
    "serious": "Katkı sağlıyor",             # değişken maliyet ≤ fiyat < tam maliyet: oda giderini karşılar, ortak gidere
                                             # kısmen katkı yapar; boş kalmasından iyidir, zarar değildir
    "critical": "Zarar: satılmamalı",        # fiyat < değişken maliyet: her satış zararı büyütür
    "unknown": "Maliyet hesaplanamadı",
}


def price_status(price, variable, breakeven, target):
    if price is None:
        return "unknown"
    if variable is not None and price < variable:
        return "critical"
    if breakeven is None:
        return "unknown"
    if price < breakeven:
        return "serious"
    return "warning" if price < target else "good"


def _percent_text(value):
    return f"%{max(value, ZERO) * 100:.0f}"


def night_reason(status, night, base, variable, breakeven):
    """Gecenin durumunun sebebi: (kutuya yazılan kısa cümle, açıklama tablosundaki uzun cümle).

    night: night_factors() sonucundaki gece (event, weekday, doluluk ve çarpanı).
    Kârlı ama hedefin altındaki geceler otelin olağan durumudur; onlara gerekçe yazılmaz.
    """
    event, weekday = night.get("event"), night.get("weekday")
    note = f"{event.notes.rstrip('.')}. " if event is not None and event.notes else ""
    factor = night.get("occupancy_factor") or ONE
    if factor != ONE and night.get("occupancy") is not None:
        note += (f"Beklenen doluluk {_percent_text(night['occupancy'])} ({night['occupancy_label']}); fiyat "
                 f"{'artırıldı' if factor > ONE else 'indirildi'} ({night['occupancy_change']}). ")
    name = event.name if event is not None else (f"{weekday.get_weekday_display()} gecesi" if weekday else "")
    if status == "good":
        if not name and factor > ONE:
            short = "Yüksek doluluk: hedef kâr tutuyor"
        else:
            short = "Güçlü talep: hedef kâr tutuyor" if name else "Hedef kâr tutuyor"
        return (short,
                f"{note}Fiyat hedef fiyatın üstünde: oda kendi giderini ve ortak giderlerdeki payını karşılıyor, "
                f"üstüne hedeflenen kârı da bırakıyor.")
    if status == "serious":
        room = (base and breakeven is not None) and _percent_text(ONE - breakeven / base)
        return ("Ortak giderin bir kısmı karşılanmıyor; boş kalmasından iyi",
                f"{note}Bu fiyat odanın kendi giderini (kahvaltı, temizlik, buklet, enerji) karşılıyor ama personel ve "
                f"kira gibi ortak giderlerin bir kısmını karşılıksız bırakıyor; bu yüzden gece kâr ettirmiyor. Zarar "
                f"değildir: oda boş kalsaydı ortak giderin hiçbiri karşılanmazdı."
                + (f" Kâr için temel fiyattan indirim en fazla {room} olmalı." if room else ""))
    if status == "critical":
        room = (base and variable is not None) and _percent_text(ONE - variable / base)
        return ("Oda giderinin altında: satılmamalı",
                f"{note}Fiyat, odanın yalnızca satılınca oluşan giderinin (kahvaltı, temizlik, buklet, enerji) bile "
                f"altında: her satış zararı büyütür, oda boş kalsa otel daha az kaybeder. Bu fiyatla yayına "
                f"alınmamalı." + (f" Bu oda için indirim en fazla {room} olabilir; o da yalnızca odanın kendi "
                                  f"giderini kurtarır." if room else ""))
    return ("", "")


def explained_nights(cells):
    """Gerekçesi olan geceleri (hedefte, katkı, zarar) art arda aynı sebep ve durumdaysa tek satırda toplar."""
    rows = []
    for cell in cells:
        if not cell["detail"]:
            continue
        last = rows[-1] if rows else None
        if (last and last["status"] == cell["status"] and last["event"] == cell["event"]
                and last["change"] == cell["occupancy_change"] and last["to"] + timedelta(days=1) == cell["date"]):
            last["to"] = cell["date"]
            continue
        rows.append({"from": cell["date"], "to": cell["date"], "status": cell["status"],
                     "status_label": cell["status_label"], "event": cell["event"], "detail": cell["detail"],
                     "price": cell["price"], "change": cell["occupancy_change"]})
    return rows


def _booked_room_nights(year, month, booked_until):
    """Ayın gecelerinden, verilen güne kadar alınmış onaylı rezervasyonlara düşen oda-gece sayısı.

    Rezervasyon tarihi boş olan kayıt (eski veri) her zaman alınmış sayılır.
    """
    start, end = month_bounds(year, month)
    nights = 0
    for check_in, check_out in (Stay.objects.occupying().filter(check_in__lt=end, check_out__gt=start)
                                .filter(Q(booked_on__isnull=True) | Q(booked_on__lte=booked_until))
                                .values_list("check_in", "check_out")):
        nights += (min(check_out, end) - max(check_in, start)).days
    return nights


def booking_pace(year, month, as_of=None):
    """Rezervasyon hızı: bu ay için bugüne kadar satılan oda-gece, geçen yıl AYNI GÜNE kadar satılanla karşılaştırılır.

    Döner: {"on_books", "last_year_same_day", "last_year_final", "ratio", "available"} ya da geçen yıl verisi yoksa None.
    ratio > 1: bu yıl daha hızlı satılıyor (talep güçlü); < 1: geride (fiyat yüksek ya da talep zayıf).
    """
    as_of = as_of or timezone.localdate()
    try:
        last_year_day = as_of.replace(year=as_of.year - 1)
    except ValueError:                                       # 29 Şubat
        last_year_day = as_of.replace(year=as_of.year - 1, day=28)
    last_year_final = _booked_room_nights(year - 1, month, date(year, month, 1) + timedelta(days=400))
    if not last_year_final:
        return None
    on_books = _booked_room_nights(year, month, as_of)
    same_day = _booked_room_nights(year - 1, month, last_year_day)
    start, end = month_bounds(year, month)
    ratio = Decimal(on_books) / Decimal(same_day) if same_day else None
    return {
        "on_books": on_books, "last_year_same_day": same_day, "last_year_final": last_year_final,
        "ratio": ratio, "change_label": index_label(ratio.quantize(Decimal("0.01"))) if ratio is not None else None,
        "available": _active_room_count() * (end - start).days,
    }


PACE_LIMITS = (Decimal("0.75"), Decimal("1.25"))       # hız düzeltmesi en fazla ±%25


def pace_factor(year, month, as_of=None):
    """Rezervasyon hızı düzeltmesi (±%25 ile sınırlı); geçen yılın aynı gününde yeterli veri yoksa None."""
    pace = booking_pace(year, month, as_of)
    if pace and pace["ratio"] is not None and pace["last_year_same_day"] >= 20:
        return min(max(pace["ratio"], PACE_LIMITS[0]), PACE_LIMITS[1])
    return None


def _occupied_by_night(start, end, booked_until=None):
    """[start, end) aralığındaki her gece için dolu oda sayısı (onaylı konaklamalar).

    booked_until verilirse yalnızca o güne kadar alınmış rezervasyonlar sayılır (rezervasyon tarihi boş olan eski
    kayıtlar her zaman alınmış sayılır).
    """
    stays = Stay.objects.occupying().filter(check_in__lt=end, check_out__gt=start)
    if booked_until is not None:
        stays = stays.filter(Q(booked_on__isnull=True) | Q(booked_on__lte=booked_until))
    counts = {}
    for check_in, check_out in stays.values_list("check_in", "check_out"):
        day = max(check_in, start)
        while day < min(check_out, end):
            counts[day] = counts.get(day, 0) + 1
            day += timedelta(days=1)
    return counts


def nightly_occupancy(start, end, as_of=None):
    """Her gecenin ANLIK doluluğu: {gece: (oran, kaynak, satılan oda, aktif oda)}.

    Rezervasyon anında (as_of) o gece için satılmış oda sayısı ÷ aktif oda sayısı. Tahmin ya da geçmiş yıl verisi
    kullanılmaz: müşteri rezervasyon yaptığı anda otel o gece %30 doluysa %30 sayılır. Geçmiş gece için as_of
    geceden sonra olduğundan sonuç gerçekleşen doluluktur.
    """
    as_of = as_of or timezone.localdate()
    rooms = _active_room_count()
    if not rooms:
        return {}
    sold = _occupied_by_night(start, end, booked_until=as_of)
    result, day = {}, start
    while day < end:
        rate = min(Decimal(sold.get(day, 0)) / rooms, ONE)
        result[day] = (rate, "gerçekleşen doluluk" if day < as_of
                       else f"{as_of:%d.%m.%Y} itibarıyla satılan oda: {sold.get(day, 0)} / {rooms}",
                       sold.get(day, 0), rooms)
        day += timedelta(days=1)
    return result


# Özel gün türleri (v79): bu gecelerde hiçbir indirim uygulanmaz (fiyat yalnız artabilir).
SPECIAL_DAY_KINDS = (Event.Kind.NATIONAL, Event.Kind.RELIGIOUS, Event.Kind.SPECIAL)


def night_factors(start, end, as_of=None, for_booking=False):
    """[start, end) gecelerinin fiyat çarpanları: gecenin endeksi × doluluk çarpanı.

    Gecenin endeksi: hafta günü endeksi ve etkinlik endekslerinden en yükseği. O gece otelin fiyat kararı
    varsa endeks kararınkidir ve doluluk çarpanı uygulanmaz (karar son sözdür).
    for_booking: rezervasyon fiyatı için; taslak (yayında olmayan) kararlar yok sayılır. Takvim taslakları da gösterir.
    """
    found = Event.objects.filter(start_date__lt=end, end_date__gte=start).order_by("start_date", "-index")
    if for_booking:
        found = found.exclude(kind=Event.Kind.DECISION, published=False)
    found = list(found)
    events = [event for event in found if event.weekday is None]
    weekly = [event for event in found if event.weekday is not None]
    occupancy = nightly_occupancy(start, end, as_of)
    rules = kural.current()
    result, day = {}, start
    while day < end:
        todays = [event for event in events if event.applies_on(day)]
        decision = next((event for event in todays if event.is_decision), None)
        outside = [event for event in todays if not event.is_decision]
        top = max(outside, key=lambda event: event.index) if outside else None
        # Özel gün (bayram, resmi tatil, özel gün) gecesinde hiçbir indirim uygulanmaz (v79): indirim kararı (endeks < 1)
        # yok sayılır, doluluk çarpanı fiyatı düşüremez; son dakika ve konaklama indirimleri de uygulanmaz.
        special = max((event for event in outside if event.kind in SPECIAL_DAY_KINDS), key=lambda event: event.index,
                      default=None)
        skipped = None
        if special is not None and decision is not None and decision.index < ONE:
            skipped, decision = decision, None
        weekday = max((event for event in weekly if event.applies_on(day)), key=lambda event: event.index, default=None)
        week_value = weekday.index if weekday else ONE
        if decision:
            index, event, weekday_used = decision.index, decision, None
        elif top and top.index >= week_value:
            index, event, weekday_used = top.index, top, None
        else:
            index, event, weekday_used = week_value, None, (weekday if week_value != ONE else None)
        rate, source, sold, rooms = occupancy.get(day, (None, "", 0, 0))
        factor, label = (ONE, "") if decision else kural.occupancy_band(rate, rules)
        if special is not None and factor < ONE:
            factor, label = ONE, ""                              # özel gecede boşluk indirimi yok
        result[day] = {
            "index": index, "event": event, "weekday": weekday_used, "events": todays,
            "special": special, "skipped_decision": skipped,
            "occupancy": rate, "occupancy_source": source, "occupancy_factor": factor, "occupancy_label": label,
            "rooms_sold": sold, "rooms_total": rooms,
            "occupancy_change": index_label(factor) if factor != ONE else "",
            "multiplier": index * factor,
        }
        day += timedelta(days=1)
    return result


def expected_occupancy(year, month, as_of=None):
    """Fiyatın dayandığı doluluk ve kaynağı: (oran ya da None, açıklama).

    Biten ay: gerçekleşen doluluk. İçinde bulunulan ya da gelecek ay: geçen yılın aynı ayının doluluğu,
    rezervasyon hızına göre düzeltilir (bu yıl bugüne kadar satılan ÷ geçen yıl aynı güne kadar satılan,
    ±%25 ile sınırlı). Geçen yıl verisi yoksa ay için şimdiden girilmiş onaylı konaklamalar.
    """
    as_of = as_of or timezone.localdate()
    if (year, month) < (as_of.year, as_of.month):
        occupancy = month_occupancy(year, month, as_of)
        return (occupancy["rate"], "gerçekleşen doluluk") if occupancy else (None, "konaklama kaydı yok")
    last_year = month_occupancy(year - 1, month, as_of)
    if last_year:
        rate, source = last_year["rate"], f"geçen yılın aynı ayı ({month:02d}.{year - 1})"
        factor = pace_factor(year, month, as_of)
        if factor is not None:
            rate = min(rate * factor, Decimal("0.98"))
            source += f", rezervasyon hızına göre düzeltildi ({'+' if factor >= 1 else '-'}%{abs(factor - 1) * 100:.0f})"
        return rate, source
    sales = month_sales(year, month)
    start, end = month_bounds(year, month)
    available = _active_room_count() * (end - start).days
    if sales["room_nights"] and available:
        return Decimal(sales["room_nights"]) / Decimal(available), "eldeki onaylı konaklamalar"
    return None, "doluluk verisi yok"


NORMAL_OCCUPANCY_MIN_MONTHS = 6


def normal_occupancy(as_of=None, cache=None):
    """Otelin normal doluluğu ve kaynağı: (oran, açıklama).

    Ortak giderler oda-gece maliyetine NORMAL kapasiteye göre yüklenir (TMS 2 md. 13). Ayın düşük doluluğu birim
    maliyeti şişirmez; boş kalan odaların payı atıl kapasite maliyetidir ve dönem gideri olarak raporlanır
    (Maliyet analizi). Böylece boş odaların bedeli dolu odaların fiyatına binmez.
    Normal doluluk = son 12 biten ayın dolu oda-gece toplamı ÷ müsait oda-gece toplamı; bu 12 ayın en az 6'sında
    veri yoksa ayarlardaki varsayım (NORMAL_DOLULUK, başlangıç %70).
    """
    as_of = as_of or timezone.localdate()
    year, month = as_of.year, as_of.month
    occupied = available = months = 0
    first = last = None
    for _ in range(12):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        if cache is not None and (year, month) in cache:
            occupancy = cache[(year, month)]
        else:
            occupancy = month_occupancy(year, month, as_of)
            if cache is not None and (year, month) < (as_of.year, as_of.month):
                cache[(year, month)] = occupancy              # biten ayın doluluğu değişmez; tekrar sorgulanmaz
        if occupancy:
            occupied += occupancy["occupied_room_nights"]
            available += occupancy["available_room_nights"]
            months += 1
            last = last or (year, month)
            first = (year, month)
    if months >= NORMAL_OCCUPANCY_MIN_MONTHS and available:
        return (Decimal(occupied) / Decimal(available),
                f"son {months} biten ayın ortalaması, {first[1]:02d}.{first[0]}–{last[1]:02d}.{last[0]}")
    default = Decimal(str(getattr(settings, "NORMAL_OCCUPANCY_DEFAULT", "0.70")))
    return default, "varsayım; yeterli geçmiş veri yok"


def normal_occupancy_for_month(year, month, as_of=None, cache=None):
    """Bir ayın normal doluluğu: o ayın sonu itibarıyla son 12 biten ayın ortalaması (bugünden ileri gidilmez)."""
    as_of = as_of or timezone.localdate()
    month_end = date(year + (month == 12), month % 12 + 1, 1)
    return normal_occupancy(min(month_end, as_of), cache)


def _type_room_nights(start, end, cache=None):
    """[start, end) aralığında oda tipine göre satılan (onaylı) oda-gece: {oda_tipi_id: gece}."""
    key = ("type_nights", start, end)
    if cache is not None and key in cache:
        return cache[key]
    result = {}
    for type_id, check_in, check_out in (Stay.objects.occupying().filter(check_in__lt=end, check_out__gt=start)
                                         .values_list("room__room_type_id", "check_in", "check_out")):
        result[type_id] = result.get(type_id, 0) + (min(check_out, end) - max(check_in, start)).days
    if cache is not None:
        cache[key] = result
    return result


def type_normal_occupancy(as_of=None, cache=None):
    """Her oda tipinin normal doluluğu: son 12 biten ayda tipin satılan oda-gecesi ÷ tipin müsait oda-gecesi.

    Ortak gider payı tipin KENDİ normal doluluğuna bölünür: Executive odalar Standart'tan az satılıyorsa boş gecelerinin
    payını kendi satılan geceleri taşır (otel ortalaması kullanılsaydı az satılan tipin maliyeti düşük görünürdü).
    Her tipin payı kendi doluluğuyla karşılandığı için yıl boyunca dağıtılan toplam değişmez. Yeterli geçmiş yoksa
    (en az 6 ay) ya da tip hiç satılmamışsa otelin normal doluluğu kullanılır. Dönüş: {oda_tipi_id: oran}.
    """
    as_of = as_of or timezone.localdate()
    hotel, _ = normal_occupancy(as_of, cache)
    rooms = dict(Room.objects.filter(status=Room.Status.ACTIVE, room_type__active=True).values("room_type_id")
                 .annotate(count=Count("id")).values_list("room_type_id", "count"))
    sold, available = {type_id: 0 for type_id in rooms}, {type_id: 0 for type_id in rooms}
    year, month, months = as_of.year, as_of.month, 0
    for _ in range(12):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        start, end = month_bounds(year, month)
        nights = _type_room_nights(start, end, cache)
        if not nights:
            continue                                   # verisiz ay ortalamaya girmez (otel normaliyle aynı kural)
        months += 1
        for type_id, count in rooms.items():
            sold[type_id] += nights.get(type_id, 0)
            available[type_id] += count * (end - start).days
    if months < NORMAL_OCCUPANCY_MIN_MONTHS:
        return {type_id: hotel for type_id in rooms}
    return {type_id: (Decimal(sold[type_id]) / Decimal(available[type_id]) if sold[type_id] and available[type_id]
                      else hotel) for type_id in rooms}


def month_absorption(year, month, as_of=None, context=None, cache=None):
    """Ayın ortak giderinin ne kadarını satılan odaların fiyatı karşıladı?

    Oda fiyatındaki ortak gider payı normal doluluğa göre hesaplanır. Bu yüzden normalden boş bir ayda giderin bir
    kısmı karşılanmaz (eksik), normalden dolu bir ayda fazlası karşılanır. Mevsimli bir otelde kışın eksik, yazın
    fazla karşılanması olağandır; olağan dışı boşluk bu farkların 12 aylık toplamına bakılarak söylenir.
      karşılanan = Σ oda tipi (satılan oda-gece × tipin gece payı ÷ tipin normal doluluğu)
      fark       = karşılanan − ayın ortak gideri (devam eden ayda bugüne kadar geçen günlerin payı)
    """
    as_of = as_of or timezone.localdate()
    context = context or _CostContext()
    period = context.month(year, month)
    start, end = month_bounds(year, month)
    frozen = closed_period(year, month)
    shared = frozen.shared_total if frozen else period["fixed_total"] + period["semi_fixed_total"]
    if not shared:
        return None
    if frozen:
        shares = {cost.room_type_id: cost.shared for cost in frozen.cost_rows()}
    else:
        per_night = period["fixed_per_night"] + period["semi_fixed_per_night"]
        shares = {room_type.id: context.share(per_night, room_type)
                  for room_type in RoomType.objects.filter(active=True)}
    counted_end = min(end, as_of + timedelta(days=1)) if start <= as_of < end else end
    if counted_end <= start:
        return None
    shared_counted = shared * Decimal((counted_end - start).days) / Decimal((end - start).days)
    normals = type_normal_occupancy(min(end, as_of), cache)
    hotel, _ = normal_occupancy(min(end, as_of), cache)
    sold = _type_room_nights(start, counted_end, cache)
    absorbed = sum((Decimal(nights) * shares.get(type_id, ZERO) / normals.get(type_id, hotel)
                    for type_id, nights in sold.items()), ZERO)
    return {"month": start, "shared": shared_counted, "absorbed": absorbed, "difference": absorbed - shared_counted,
            "complete": counted_end == end}


def absorption_window(year, month, as_of=None, cache=None):
    """Seçilen ayla biten 12 ayda (mevsimlerin tamamı) ortak giderin karşılanması.

    Kışın eksik, yazın fazla karşılanan tutarlar birbirini dengeler. Toplamda eksik kalırsa, otel normal kapasitesinin
    altında çalışmış demektir: OLAĞAN DIŞI BOŞLUK MALİYETİ (dönem gideri; oda fiyatına yüklenmez, TMS 2 md. 13 mantığı).
    Fazla kalırsa otel normalden verimli çalışmıştır.
    """
    as_of = as_of or timezone.localdate()
    cache = {} if cache is None else cache
    context = _CostContext()
    months, cursor = [], (year, month)
    for _ in range(12):
        result = month_absorption(cursor[0], cursor[1], as_of, context, cache)
        if result is not None:
            months.append(result)
        cursor = (cursor[0] - 1, 12) if cursor[1] == 1 else (cursor[0], cursor[1] - 1)
    if not months:
        return None
    months.reverse()
    short = sum((-item["difference"] for item in months if item["difference"] < 0), ZERO)
    over = sum((item["difference"] for item in months if item["difference"] > 0), ZERO)
    net = over - short
    return {"months": months, "first": months[0]["month"], "last": months[-1]["month"], "count": len(months),
            "short": short, "over": over, "net": net, "abnormal": -net if net < 0 else ZERO}


def abnormal_idle_cost(shared, rate, normal):
    """TMS 2 md. 13 mantığıyla olağan dışı atıl kapasite: normal kapasitenin altında kalan boşluğun ortak gider payı.

    = ortak gider × (1 − doluluk ÷ normal doluluk); doluluk normalin üstündeyse 0 (otel normalden verimli çalıştı).
    """
    if rate is None or not normal:
        return None
    return shared * max(ZERO, ONE - rate / normal)


def tax_rates(day):
    """O gün geçerli (KDV, konaklama vergisi) oranları; kayıt yoksa 0."""
    rates = {}
    for kind in (TaxRate.Kind.VAT, TaxRate.Kind.ACCOMMODATION):
        rates[kind] = (TaxRate.objects.filter(kind=kind, valid_from__lte=day).order_by("-valid_from")
                       .values_list("rate", flat=True).first() or ZERO)
    return rates[TaxRate.Kind.VAT], rates[TaxRate.Kind.ACCOMMODATION]


def guest_price(net_price, vat, accommodation_tax):
    """Misafirin ödeyeceği: iki vergi de KDV hariç bedel üzerinden ayrı hesaplanır (konaklama vergisi KDV matrahına girmez)."""
    return net_price * (ONE + vat + accommodation_tax) if net_price is not None else None


def price_for_guests(double_price, guests, room_type):
    """2 kişilik fiyattan kişi sayısına göre fiyat: tek kişide indirim, 2'den sonraki her kişiye ek kişi ücreti."""
    if double_price is None:
        return None
    if guests <= 1:
        return double_price * (ONE - room_type.single_discount)
    return double_price + room_type.extra_guest_rate * (guests - 2)


def price_overview(cells, variable, full, target):
    """Fiyat takvimi özet kartı için ayın fiyatlarının sade özeti (v69).

    En düşük–en yüksek aralık (ör. 525–7.346 ₺) kampanya ve fuar kararları yüzünden yanıltıcı olur. Bunun yerine:
      normal: otel kararı olmayan gecelerin fiyat aralığı ve ortalaması (fiyat motorunun kendi verdiği fiyat),
      special: otel kararı olan geceler, karar adına göre art arda tarih aralıklarına gruplanmış,
      scale: maliyet eşiklerinin bir çubuk üzerindeki yeri (renk bölgeleri için yüzde genişlikler).
    """
    priced = [cell for cell in cells if cell["price"] is not None]
    if not priced:
        return None
    normal = [cell["price"] for cell in priced if not cell["engine"]["decision"]]
    special = []
    for cell in priced:
        decision = cell["engine"]["decision"]
        if not decision:
            continue
        last = special[-1] if special else None
        if last and last["name"] == decision.name and (cell["date"] - last["end"]).days == 1:
            last["end"] = cell["date"]
            last["nights"] += 1
            last["low"], last["high"] = min(last["low"], cell["price"]), max(last["high"], cell["price"])
            continue
        special.append({"name": decision.name, "start": cell["date"], "end": cell["date"], "nights": 1,
                        "low": cell["price"], "high": cell["price"], "status": cell["status"],
                        "status_label": cell["status_label"], "change": decision.change_label,
                        "draft": not decision.published})
    average = sum((cell["price"] for cell in priced), ZERO) / len(priced)
    scale = None
    if None not in (variable, full, target):
        top = max(max(cell["price"] for cell in priced), target) * Decimal("1.08")
        width = lambda low, high: float(max(ZERO, min(high, top) - low) / top * 100)
        scale = {"zones": [width(ZERO, variable), width(variable, full), width(full, target), width(target, top)],
                 "average": float(min(average, top) / top * 100)}
    return {
        "nights": len(priced), "average": average,
        "normal_low": min(normal) if normal else None, "normal_high": max(normal) if normal else None,
        "normal_average": sum(normal, ZERO) / len(normal) if normal else None, "normal_nights": len(normal),
        "special": special, "has_draft": any(item["draft"] for item in special), "scale": scale,
    }


def price_calendar(year, month, as_of=None, guests=2):
    """Ayın her gecesi ve her oda tipi için önerilen fiyat ve maliyet sınırları (TL, KDV hariç).

    Önerilen fiyat = mevsimin temel fiyatı (2 kişi) × o gecenin endeksi, sonra kişi sayısına göre düzeltilir.
    Gecenin endeksi: hafta günü endeksi ve o geceye denk gelen etkinlik endekslerinden EN YÜKSEĞİ. O gece için
    otelin bir fiyat kararı (artış, kampanya, indirim) varsa otomatik kural yerine o geçerlidir.
    Maliyet sınırları ayın maliyet hesabından, seçilen kişi sayısı için gelir:
      değişken maliyet  : oda satılınca oluşan maliyet (kahvaltı, sarf, tekstil, enerjinin değişken kısmı)
      tam maliyet       : değişken maliyet + ortak gider payı ÷ NORMAL doluluk (ayın beklenen doluluğu değil:
                          boş odaların payı fiyata yüklenmez, atıl kapasite maliyeti olarak ayrı raporlanır)
      hedef fiyat       : tam maliyet × (1 + oda tipinin hedef kâr marjı)
    Ayın beklenen doluluğu ve rezervasyon hızı talebi anlatmak ve atıl kapasiteyi göstermek için verilir.
    """
    as_of = as_of or timezone.localdate()
    start, end = month_bounds(year, month)
    days = [start + timedelta(days=offset) for offset in range((end - start).days)]
    season_code = season_of(month)
    season = {"code": season_code, "name": dict(Season.choices).get(season_code, "")} if season_code else None
    rates = ({room_type.id: room_type.market_rate(season_code) for room_type in RoomType.objects.all()
              if room_type.market_rate(season_code) is not None} if season_code else {})
    nightly = night_factors(start, end, as_of)
    rules = kural.current()
    events = list(dict.fromkeys(event for night in nightly.values() for event in night["events"]))
    weekly = list(Event.objects.filter(start_date__lt=end, end_date__gte=start, weekday__isnull=False))

    vat, accommodation_tax = tax_rates(start)
    channels = list(SalesChannel.objects.order_by("commission_rate", "id"))
    occupancy, occupancy_source = expected_occupancy(year, month, as_of)
    normal, normal_source = normal_occupancy(as_of)
    type_normals = type_normal_occupancy(as_of)
    pace = booking_pace(year, month, as_of) if (year, month) >= (as_of.year, as_of.month) else None
    summary = calculate_monthly_room_cost(year, month, as_of)
    from .fiyat_motoru import FiyatMotoru                     # döngüsel içe aktarmayı önlemek için burada
    engine = FiyatMotoru(start, end, as_of=as_of)
    engine._rows[(year, month)] = summary["rows"]               # ayın maliyeti zaten hesaplandı
    room_counts = dict(Room.objects.filter(status=Room.Status.ACTIVE).values("room_type_id")
                       .annotate(count=Count("id")).values_list("room_type_id", "count"))
    types = []
    for room_type in RoomType.objects.filter(active=True, id__in=room_counts).order_by("standard_cost_factor", "code"):
        type_guests = max(1, min(guests, room_type.max_guests))
        row = next((r for r in summary["rows"] if r["room_type_id"] == room_type.id and r["guests"] == type_guests), None)
        variable = row["variable"] if row else None
        type_normal = type_normals.get(room_type.id, normal)
        breakeven = (variable + (row["semi_fixed"] + row["fixed"]) / type_normal
                     if row and type_normal else None)
        target = breakeven * (ONE + room_type.target_markup) if breakeven is not None else None
        base = price_for_guests(rates.get(room_type.id), type_guests, room_type)
        cells = []
        for day in days:
            night = nightly[day]
            # Fiyat motoru: maliyetten hedef (piyasa tavanıyla) × talep, alt sınırla (fiyat_motoru.py).
            quote = engine.night(room_type, type_guests, day)
            price = quote["price"]
            status = price_status(price, variable, breakeven, target)
            short, detail = night_reason(status, night, base, variable, breakeven)
            early = price is not None and (day - as_of).days >= rules.early_days and night["special"] is None
            cells.append({**night, "date": day, "price": price, "status": status, "status_label": PRICE_STATUS[status],
                          "why": short, "detail": detail, "base": base,
                          "guest_price": guest_price(price, vat, accommodation_tax),
                          # Gecelik kâr = fiyat − tam maliyet; hedefe fark = fiyat − hedef fiyat.
                          "profit": price - breakeven if price is not None and breakeven is not None else None,
                          "to_target": price - target if price is not None and target is not None else None,
                          "contribution": price - variable if price is not None and variable is not None else None,
                          "early_price": price * (ONE - rules.early_discount) if early else None,
                          "past": day < as_of, "engine": quote,
                          "free_rooms": max(quote.get("type_rooms", 0) - quote.get("type_sold", 0), 0)})
        prices = [cell["price"] for cell in cells if cell["price"] is not None]
        counts = {key: sum(1 for cell in cells if cell["status"] == key) for key in PRICE_STATUS}
        count_text = ", ".join(f"{PRICE_STATUS[key].lower()} {counts[key]} gece"
                               for key in ("good", "warning", "serious", "critical") if counts[key])
        # Fiyat motoru özeti: her gecede fiyatı neyin belirlediği (maliyet / piyasa / otel kararı) ve alt sınır.
        engine_counts = {"target": 0, "market": 0, "decision": 0, "floor": 0}
        for cell in cells:
            quote = cell["engine"]
            if quote["price"] is None:
                continue
            engine_counts["decision" if quote["decision"] else quote["anchor_source"]] += 1
            engine_counts["floor"] += quote["floor_applied"]
        types.append({
            "engine_counts": engine_counts, "overview": price_overview(cells, variable, breakeven, target),
            # v89: ayın satılan oda-gecesi (bu oda tipi, bugüne kadar alınmış rezervasyonlar) ve kapasite
            "sold_nights": sum(cell["engine"].get("type_sold", 0) for cell in cells),
            "capacity_nights": room_counts.get(room_type.id, 0) * len(cells),
            # v90: oda tipinin manzarası (odalarında en sık görülen; hepsi aynıysa tek değer)
            "view": dict(Room.ViewType.choices).get(
                Room.objects.filter(room_type=room_type, status=Room.Status.ACTIVE).values("view_type")
                .annotate(n=Count("id")).order_by("-n").values_list("view_type", flat=True).first(), ""),
            "count_text": count_text, "explained": explained_nights(cells),
            "room_type": room_type, "rooms": room_counts.get(room_type.id, 0), "guests": type_guests,
            "type_normal": type_normal,
            "base": base, "variable": variable, "breakeven": breakeven, "target": target,
            "markup": room_type.target_markup, "cells": cells, "counts": counts,
            "protect_floor": breakeven * (ONE + room_type.min_markup) if breakeven is not None else None,
            "average": sum(prices, ZERO) / len(prices) if prices else None,
            "lowest": min(prices) if prices else None, "highest": max(prices) if prices else None,
            "base_status": price_status(base, variable, breakeven, target),
            "base_guest_price": guest_price(base, vat, accommodation_tax),
            # Temel fiyatla satışta, kanala göre otele kalan (KDV hariç, komisyon düşülmüş) ve bunun durumu.
            "channels": [{
                "channel": channel,
                "net": base * (ONE - channel.commission_rate) if base is not None else None,
                "status": PRICE_STATUS[price_status(base * (ONE - channel.commission_rate) if base is not None else None,
                                                    variable, breakeven, target)],
            } for channel in channels],
        })
    for item in types:
        item["base_status_label"] = PRICE_STATUS[item["base_status"]]
    return {
        "month": start, "season": season, "events": events, "days": days, "types": types,
        "occupancy": occupancy, "occupancy_source": occupancy_source,
        "normal_occupancy": normal, "normal_source": normal_source,
        "occupancy_gap": (occupancy - normal) if occupancy is not None else None, "frozen": summary["frozen"], "pace": pace,
        "event_nights": sum(1 for day in days if nightly[day]["event"] is not None),
        "occupancy_up": sum(1 for day in days if nightly[day]["occupancy_factor"] > ONE),
        "occupancy_down": sum(1 for day in days if nightly[day]["occupancy_factor"] < ONE),
        "weekday_indexes": [event for event in weekly if event.index != ONE],
        "guests": guests, "max_guests": max((item["room_type"].max_guests for item in types), default=2),
        "vat": vat, "accommodation_tax": accommodation_tax, "rules": rules,
    }


STAY_STATUS_TEXT = {
    "good": "Konaklama hedef kârın üstünde: indirimlerden sonra da oda kendi giderini, ortak giderlerdeki payını ve "
            "hedeflenen kârı karşılıyor.",
    "warning": "Konaklama kâr ediyor ama hedef kârın altında: indirimler kârın bir kısmını götürdü.",
    "serious": "İndirimlerden sonra fiyat odanın kendi giderini karşılıyor ama ortak giderlerin bir kısmını karşılamıyor; "
               "bu konaklama kâr ettirmez. Zarar değildir: oda boş kalmasından iyidir.",
    "critical": "İndirimlerden sonra fiyat odanın kendi giderinin bile altında: bu koşullarla satılmamalı.",
    "unknown": "Maliyet ya da fiyat hesaplanamadı.",
}


def room_availability(room_type, check_in, check_out):
    """Oda tipinin [giriş, çıkış) gecelerindeki müsaitliği (v82). Oda bazında bakılır, yalnız aktif odalar sayılır.

    status:
      "available"   : en az bir oda bütün geceler boyunca boş (misafir tek odada kalır)
      "room_change" : her gece boş oda var ama hiçbiri bütün geceler boş değil (konaklama ancak oda değişikliğiyle)
      "unavailable" : en az bir gece bu tipte hiç boş oda yok
      "no_rooms"    : bu tipte satışa açık (aktif) oda yok
    """
    rooms = list(Room.objects.filter(room_type=room_type, status=Room.Status.ACTIVE).order_by("room_number")
                 .values_list("id", "room_number"))
    nights = [check_in + timedelta(days=n) for n in range((check_out - check_in).days)]
    busy = {room_id: set() for room_id, _ in rooms}
    for room_id, first, last in (Stay.objects.occupying()
                                 .filter(room_id__in=busy, check_in__lt=check_out, check_out__gt=check_in)
                                 .values_list("room_id", "check_in", "check_out")):
        day = max(first, check_in)
        while day < min(last, check_out):
            busy[room_id].add(day)
            day += timedelta(days=1)
    per_night = [{"date": day, "free": sum(1 for room_id, _ in rooms if day not in busy[room_id]), "total": len(rooms)}
                 for day in nights]
    whole = [number for room_id, number in rooms if not busy[room_id]]
    full_nights = [night["date"] for night in per_night if night["free"] == 0]
    if not rooms:
        status = "no_rooms"
    elif whole:
        status = "available"
    elif full_nights:
        status = "unavailable"
    else:
        status = "room_change"
    return {
        "status": status, "available": status in ("available", "room_change"), "rooms_total": len(rooms),
        "free_rooms": whole, "free_count": len(whole), "per_night": per_night, "full_nights": full_nights,
        "min_free": min((night["free"] for night in per_night), default=0),
        "last_rooms": status == "available" and len(whole) <= 2,
    }


def night_sales_summary(room_type, check_in, check_out, as_of=None):
    """Seçilen gecelerde ZATEN SATILMIŞ odaların satış ve kâr özeti (v85, personel kontrolü).

    Oda tipi için: satılan oda-gece, ortalama satış fiyatı, gelir, kanal komisyonu, otele kalan, tahmini tam maliyet
    (o gecenin maliyeti, kişi sayısına göre) ve kâr; kanallara göre dağılım. Otel geneli için: satılan oda-gece ve doluluk.
    """
    from .fiyat_motoru import FiyatMotoru                     # döngüsel içe aktarmayı önlemek için burada
    engine = FiyatMotoru(check_in, check_out, as_of=as_of)
    nights = [check_in + timedelta(days=n) for n in range((check_out - check_in).days)]
    type_rooms = Room.objects.filter(room_type=room_type, status=Room.Status.ACTIVE).count()
    hotel_rooms = _active_room_count()
    per_night = {day: {"date": day, "type_sold": 0, "hotel_sold": 0, "revenue": ZERO, "net": ZERO, "cost": ZERO,
                       "priced": 0} for day in nights}
    channels = {}
    stays = (Stay.objects.occupying().filter(check_in__lt=check_out, check_out__gt=check_in)
             .select_related("room__room_type", "channel"))
    for stay in stays:
        rate = stay.channel.commission_rate if stay.channel_id else ZERO
        day = max(stay.check_in, check_in)
        while day < min(stay.check_out, check_out):
            night = per_night[day]
            night["hotel_sold"] += 1
            if stay.room.room_type_id == room_type.id:
                night["type_sold"] += 1
                full = engine.costs(room_type, stay.guests, day)[1]
                night["cost"] += full or ZERO
                if stay.nightly_rate is not None:
                    night["priced"] += 1
                    night["revenue"] += stay.nightly_rate
                    night["net"] += stay.nightly_rate * (ONE - rate)
                name = stay.channel.name if stay.channel_id else "Kanal girilmemiş"
                channels[name] = channels.get(name, 0) + 1
            day += timedelta(days=1)
    rows = list(per_night.values())
    for night in rows:
        night["type_rate"] = Decimal(night["type_sold"]) / type_rooms if type_rooms else None
        night["hotel_rate"] = Decimal(night["hotel_sold"]) / hotel_rooms if hotel_rooms else None
        night["adr"] = night["revenue"] / night["priced"] if night["priced"] else None
        night["profit"] = night["net"] - night["cost"] if night["type_sold"] else None
    sold = sum(night["type_sold"] for night in rows)
    priced = sum(night["priced"] for night in rows)
    revenue = sum((night["revenue"] for night in rows), ZERO)
    net = sum((night["net"] for night in rows), ZERO)
    cost = sum((night["cost"] for night in rows), ZERO)
    capacity = type_rooms * len(nights)
    hotel_sold = sum(night["hotel_sold"] for night in rows)
    return {
        "rows": rows, "type_rooms": type_rooms, "hotel_rooms": hotel_rooms, "sold": sold, "capacity": capacity,
        "type_rate": Decimal(sold) / capacity if capacity else None,
        "hotel_sold": hotel_sold, "hotel_rate": Decimal(hotel_sold) / (hotel_rooms * len(nights)) if hotel_rooms and nights else None,
        "revenue": revenue, "commission": revenue - net, "net": net, "cost": cost, "profit": net - cost if sold else None,
        "adr": revenue / priced if priced else None, "margin": (net - cost) / net if net else None,
        "channels": sorted(channels.items(), key=lambda item: -item[1]),
    }


def availability_alternatives(room_type, guests, check_in, check_out, booked_on=None, channel=None, max_shift=14):
    """Seçilen oda tipi dolu ise öneriler (v82): aynı tarihlerde boş olan diğer oda tipleri (fiyatlarıyla) ve aynı oda
    tipinde en yakın boş tarihler (aynı gece sayısı, ±max_shift gün)."""
    nights = (check_out - check_in).days
    today = timezone.localdate()
    other_types = []
    for other in RoomType.objects.filter(active=True, max_guests__gte=guests).exclude(pk=room_type.pk).order_by(
            "standard_cost_factor", "code"):
        availability = room_availability(other, check_in, check_out)
        if availability["status"] != "available":
            continue
        quote = stay_price_quote(other, guests, check_in, check_out, booked_on=booked_on, channel=channel)
        if quote.get("missing_rate"):
            continue
        other_types.append({"room_type": other, "free_count": availability["free_count"], "total": quote["total"],
                            "net": quote["net"], "status": quote["status"], "status_label": quote["status_label"]})
    dates = []
    for shift in sorted((n for n in range(-max_shift, max_shift + 1) if n), key=lambda n: (abs(n), n)):
        first = check_in + timedelta(days=shift)
        if first < today or (booked_on and first < booked_on):
            continue
        availability = room_availability(room_type, first, first + timedelta(days=nights))
        if availability["status"] == "available":
            dates.append({"check_in": first, "check_out": first + timedelta(days=nights), "shift": shift,
                          "free_count": availability["free_count"]})
        if len(dates) == 3:
            break
    return {"room_types": other_types, "dates": dates}


def stay_price_quote(room_type, guests, check_in, check_out, booked_on=None, as_of=None, normal=None, channel=None,
                     type_normals=None):
    """Bir konaklamanın satış fiyatı (TL, KDV hariç) ve maliyete göre durumu.

    Gece fiyatı = mevsimin temel fiyatı × gecenin endeksi × doluluk çarpanı, sonra kişi sayısına göre (fiyat takvimiyle
    aynı kural). Doluluk, rezervasyon tarihinde o gece için satılmış odalardır (anlık doluluk). Konaklama indirimleri gece fiyatlarının toplamına sırayla uygulanır: erken rezervasyon (girişten en az
    30 gün önce, %15), sonra konaklama süresi (3+ gece %5, 6+ gece %8, 15+ gece %12). Oranlar: fiyat_kurallari.py.
    Tam maliyet fiyat takvimiyle aynı: değişken maliyet + ortak gider payı ÷ normal doluluk.
    Satış kanalı verilirse komisyonu düşülür; kâr ve renk otele KALAN tutara göre verilir (Satış ve kârlılık ile aynı).
    """
    as_of = as_of or timezone.localdate()
    booked_on = booked_on or as_of
    nights = (check_out - check_in).days
    seasons = season_map()
    # Gece fiyatı fiyat motorundan (takvimle aynı kural); doluluk ve son dakika rezervasyon anına göre.
    from .fiyat_motoru import FiyatMotoru                     # döngüsel içe aktarmayı önlemek için burada
    engine = FiyatMotoru(check_in, check_out, as_of=as_of, booked_on=booked_on, for_booking=True,
                         normal=normal, type_normals=type_normals)
    factors = engine.factors
    rows, subtotal, floor_total, missing = [], ZERO, ZERO, False
    special_subtotal = ZERO                                  # özel gecelerin toplamı: indirim uygulanmaz (v79)
    for offset in range(nights):
        day = check_in + timedelta(days=offset)
        night = factors[day]
        quote = engine.night(room_type, guests, day)
        if quote["price"] is None or quote["market"] is None:
            missing = True
            continue
        subtotal += quote["price"]
        if night["special"] is not None:
            special_subtotal += quote["price"]
        if quote["floor"] is not None and (not quote["decision"] or quote.get("protected")):
            floor_total += quote["floor"]
        rows.append({**night, "date": day, "base": quote["market"], "price": quote["price"], "engine": quote,
                     "season": dict(Season.choices).get(seasons.get(day.month), "")})
    if missing or not rows:
        return {"missing_rate": True}
    days_ahead = (check_in - booked_on).days
    rules = kural.current()
    early = kural.early_booking_discount(days_ahead, rules)
    length = kural.length_of_stay_discount(nights, rules)
    discountable = subtotal - special_subtotal               # indirimler yalnız özel olmayan gecelere
    if not discountable:
        early = length = ZERO
    after_early = special_subtotal + discountable * (ONE - early)
    total = special_subtotal + discountable * (ONE - early) * (ONE - length)
    commission_rate = channel.commission_rate if channel is not None else ZERO
    # Alt sınır konaklamanın tamamında da geçerli: indirimler toplamı gecelerin alt sınırları toplamının altına indiremez.
    # Kâr korumalı oda tipinde (v70) sınır otele KALAN tutara uygulanır: kanal komisyonu da kârı yiyemez.
    protected = room_type.min_markup > 0
    required = floor_total / (ONE - commission_rate) if protected and commission_rate < ONE else floor_total
    floor_lift = required - total if required > total else ZERO
    total += floor_lift
    vat, accommodation_tax = tax_rates(check_in)

    cost = calculate_stay_quote(room_type, guests, check_in, check_out)
    normal, normal_source = normal if normal is not None else normal_occupancy(as_of)
    type_normals = type_normals if type_normals is not None else type_normal_occupancy(as_of)
    normal = type_normals.get(room_type.id, normal)         # oda tipinin kendi normal doluluğu
    full_cost = cost["variable_total"] + cost["cost_groups"]["monthly_shared"] / normal
    target = full_cost * (ONE + room_type.target_markup)
    commission = total * commission_rate
    net = total - commission
    status = price_status(net, cost["variable_total"], full_cost, target)
    # İndirimler fiyatı alt sınıra (tam maliyete) indirdiyse konaklama başabaştır: kâr da zarar da yok. Konaklama maliyeti
    # ile gecelerin alt sınırı ayrı hesaplandığı için birkaç liralık farka (%1) izin verilir.
    break_even = bool(floor_lift) and not protected and abs(net - full_cost) <= full_cost * Decimal("0.01")
    if break_even:
        status = "warning"
    return {
        "channel": channel, "commission_rate": commission_rate, "commission": commission, "net": net,
        "nights": nights, "rows": rows, "subtotal": subtotal, "booked_on": booked_on, "days_ahead": days_ahead,
        "early_rate": early, "early_amount": subtotal - after_early, "early_days": rules.early_days, "rules": rules,
        "length_rate": length, "length_amount": after_early - total,
        "special_subtotal": special_subtotal, "special_nights": sum(1 for row in rows if row["special"] is not None),
        "discount_total": subtotal - total, "total": total, "per_night": total / nights,
        "floor_total": floor_total, "floor_lift": floor_lift, "protected": protected, "min_markup": room_type.min_markup,
        "vat": vat, "accommodation_tax": accommodation_tax, "guest_total": guest_price(total, vat, accommodation_tax),
        "variable_cost": cost["variable_total"], "full_cost": full_cost, "target": target,
        "normal_occupancy": normal, "normal_source": normal_source,
        "profit": net - full_cost, "contribution": net - cost["variable_total"],
        "status": status,
        # İndirimler fiyatı alt sınıra (tam maliyete) indirdiyse konaklama başabaştır: kâr da zarar da yok.
        "break_even": break_even,
        "status_label": "Başabaş: alt sınırda" if break_even else PRICE_STATUS[status],
        "status_text": ("İndirimler fiyatı tam maliyete kadar indirdi; alt sınır devreye girdi. Bu konaklama kâr ettirmez, "
                        "zarar da yazmaz." if break_even else STAY_STATUS_TEXT[status]),
    }


STAY_SHORT = {
    "good": "Hedef kârın üstünde",
    "warning": "Kâr ediyor, hedef kârın altında",
    "serious": "Ortak giderin bir kısmını karşılamıyor; zarar değil",
    "critical": "Oda giderinin altında: zarar",
    "unknown": "Fiyat girilmemiş",
}


# v88: otelin bilinçli zararına satışı (kampanya, talep azlığı indirimi) konaklama notunda bu önekle tutulur.
LOSS_SALE_PREFIX = "Zararına satış: "


def reservation_overview(start, end, as_of=None):
    """[start, end) arasında giriş yapacak onaylı rezervasyonlar: satış fiyatı, maliyeti, kârı, rengi ve sebebi.

    Maliyet fiyat takvimiyle aynı: her gece için oda tipi × kişi sayısının değişken maliyeti ve ortak gider payı ÷
    normal doluluk; hedef = tam maliyet × (1 + hedef marj). Durum konaklamanın GERÇEK satış fiyatına göre verilir.
    Sebep: gecelere denk gelen otel kararları ve etkinlikler, erken rezervasyon ve konaklama süresi indirimi.
    """
    as_of = as_of or timezone.localdate()
    stays = list(Stay.objects.occupying().filter(check_in__gte=start, check_in__lt=end)
                 .select_related("room__room_type", "channel").order_by("check_in", "room__room_number"))
    if not stays:
        return []
    last_night = max(stay.check_out for stay in stays)
    factors = night_factors(start, last_night, as_of, for_booking=True)
    normal, _ = normal_occupancy(as_of)
    type_normals = type_normal_occupancy(as_of)
    rules = kural.current()
    months, rows = {}, []
    for stay in stays:
        room_type, nights = stay.room.room_type, stay.nights
        variable_total = full_total = ZERO
        missing = False
        for offset in range(nights):
            day = stay.check_in + timedelta(days=offset)
            key = (day.year, day.month)
            if key not in months:
                months[key] = calculate_monthly_room_cost(day.year, day.month, as_of)["rows"]
            guests = max(1, min(stay.guests, room_type.max_guests))
            row = next((r for r in months[key] if r["room_type_id"] == room_type.id and r["guests"] == guests), None)
            if row is None:
                missing = True
                break
            variable_total += row["variable"]
            full_total += row["variable"] + (row["semi_fixed"] + row["fixed"]) / type_normals.get(room_type.id, normal)
        total = stay.total_price
        commission_rate = stay.channel.commission_rate if stay.channel_id else ZERO
        commission = total * commission_rate if total is not None else None
        net = total - commission if total is not None else None
        if missing or total is None:
            status = "unknown"
            target_total = None
        else:
            target_total = full_total * (ONE + room_type.target_markup)
            # Renk otele KALAN tutara göre: satış fiyatı − kanal komisyonu (Satış ve kârlılık ekranıyla aynı).
            status = price_status(net, variable_total, full_total, target_total)
        causes = []
        seen = set()
        for offset in range(nights):
            night = factors.get(stay.check_in + timedelta(days=offset))
            event = night and night["event"]
            if event is not None and event.pk not in seen:
                seen.add(event.pk)
                causes.append(f"{event.name} {event.change_label}")
        days_ahead = (stay.check_in - stay.booked_on).days if stay.booked_on else None
        early = kural.early_booking_discount(days_ahead, rules)
        length = kural.length_of_stay_discount(nights, rules)
        if early:
            causes.append(f"erken rezervasyon ({days_ahead} gün önce) -%{early * 100:.0f}")
        if length:
            causes.append(f"{nights} gece -%{length * 100:.0f}")
        if commission_rate:
            causes.append(f"{stay.channel.name} komisyonu %{commission_rate * 100:.0f}")
        status_label, short = PRICE_STATUS[status], STAY_SHORT[status]
        # v88: otelin bilerek zararına sattığı konaklama (notu "Zararına satış: ..."). Otele kalan tam maliyetin altındaysa
        # kırmızı "Zararına satış" olarak işaretlenir; gerekçe nottan gelir. Diğer konaklamaların durumu değişmez.
        deliberate = (stay.notes or "").startswith(LOSS_SALE_PREFIX)
        if deliberate and status in ("serious", "critical"):
            reason = stay.notes[len(LOSS_SALE_PREFIX):]
            status, status_label = "critical", "Zararına satış"
            short = f"Bilinçli zararına satış: {reason}"
            causes.insert(0, reason)
        rows.append({
            "stay": stay, "room_type": room_type, "nights": nights, "total": total,
            "nightly": stay.nightly_rate, "variable": variable_total, "full_cost": full_total, "target": target_total,
            "commission": commission, "commission_rate": commission_rate, "net": net,
            "profit": net - full_total if total is not None and not missing else None,
            "status": status, "status_label": status_label, "short": short, "deliberate_loss": deliberate,
            "causes": causes, "days_ahead": days_ahead, "month": stay.check_in.replace(day=1),
        })
    return rows


def calendar_weeks(days):
    """Takvim ızgarası: Pazartesi ile başlayan haftalar; ayın dışındaki kutular None."""
    weeks, week = [], [None] * days[0].weekday()
    for day in days:
        week.append(day)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        weeks.append(week + [None] * (7 - len(week)))
    return weeks


# --------------------------------------------------------------------------- konaklamadan stok tüketimi

def night_consumption(day):
    """Bir gecenin konaklamalarının teorik tüketimi (reçeteye göre).

    Döner: ({ürün_id: [net miktar, fire miktarı]}, dolu oda sayısı, kişi sayısı).
      - Kahvaltı: büfedeki kişi başı miktar × o gece konaklayan kişi sayısı.
      - Oda paketi: her konaklamanın oda tipi ve kişi sayısına uyan paketteki sarf ürünleri
        (buklet, minibar, temizlik); kişi başına olanlar kişi sayısıyla çarpılır.
      - Tekstil düşülmez: tüketilmez, yıpranır (maliyete yıpranma payıyla girer).
    Fire, maliyet hesabındaki oranla (satırdaki ve ürün kartındakinden büyük olanı) ayrıca hesaplanır.
    """
    totals = {}

    def add(item_id, quantity, waste_rate):
        entry = totals.setdefault(item_id, [ZERO, ZERO])
        entry[0] += quantity
        entry[1] += quantity * waste_rate

    combos = {}
    rooms = guests = 0
    for room_type_id, stay_guests in Stay.objects.occupying().filter(check_in__lte=day, check_out__gt=day).values_list(
            "room__room_type_id", "guests"):
        rooms += 1
        guests += stay_guests
        combos[(room_type_id, stay_guests)] = combos.get((room_type_id, stay_guests), 0) + 1
    if not rooms:
        return totals, 0, 0

    for line in BreakfastBuffetItem.objects.filter(active=True).select_related("item"):
        add(line.item_id, line.quantity * guests, line.effective_waste_rate)

    for (room_type_id, stay_guests), count in combos.items():
        # Tekstil tüketilmez (yıpranır): stoktan düşülmez.
        for component in RoomPackageItem.objects.filter(guest_count=stay_guests, active=True,
                                                        item__textile_life__isnull=True).select_related("item"):
            per_room = component.quantity
            if component.basis == RoomPackageItem.Basis.PER_GUEST_NIGHT:
                per_room *= stay_guests
            add(component.item_id, per_room * count, max(component.waste_rate, component.item.wastage_rate))
    return totals, rooms, guests


def last_closed_day():
    """Gün sonu işlenmiş son gece (yoksa None)."""
    return (InventoryMovement.objects.filter(consumption_day__isnull=False)
            .order_by("-consumption_day").values_list("consumption_day", flat=True).first())


# --------------------------------------------------------------------------- stok ve sipariş

# Önerilen sipariş, stoğu hedef seviyeye tamamlar: hedef = 3 × kritik stok (açılış stoku kuralıyla aynı).
TARGET_MULTIPLIER = Decimal("3")


def on_order_quantities():
    """Açık (teslim bekleyen) siparişlerdeki ürün miktarları: {ürün_id: miktar}."""
    totals = {}
    for item_id, quantity in PurchaseOrderLine.objects.filter(order__status=PurchaseOrder.Status.OPEN).values_list(
            "item_id", "quantity"):
        totals[item_id] = totals.get(item_id, ZERO) + quantity
    return totals


def suggested_order_quantity(item, on_order=ZERO):
    """Stoğu hedef seviyeye (3 × kritik) tamamlayan miktar; adet ve demet tam sayıya, diğerleri 0,5'e yuvarlanır."""
    need = item.reorder_level * TARGET_MULTIPLIER - item.current_stock - on_order
    if need <= 0:
        return ZERO
    step = ONE if item.unit in (InventoryItem.Unit.PIECE, InventoryItem.Unit.BUNCH) else Decimal("0.5")
    return (need / step).to_integral_value(rounding="ROUND_CEILING") * step


def last_purchase_price(item):
    price = (item.movements.filter(movement_type=InventoryMovement.MovementType.PURCHASE)
             .order_by("-movement_at").values_list("unit_cost", flat=True).first())
    return price if price is not None else item.average_unit_cost


# v94: stok analizi başlıkları — (anahtar, başlık, kategoriler, renk)
STOCK_GROUPS = (
    ("mutfak_bar", "Mutfak ve bar", ("yiyecek", "icecek", "restoran"), "#d4862c"),
    ("tekstil", "Tekstil", ("tekstil",), "#6b5ca5"),
    ("temizlik", "Temizlik malzemeleri", ("temizlik",), "#176c70"),
    ("buklet", "Buklet ve oda malzemeleri", ("buklet",), "#2f5f8a"),
)


def get_stock_summary():
    on_order = on_order_quantities()
    rows = []
    stock_value = ZERO
    for item in InventoryItem.objects.filter(active=True).select_related("supplier"):
        stock_value += item.stock_value
        ordered = on_order.get(item.id, ZERO)
        rows.append({
            "id": item.id, "sku": item.sku, "name": item.name, "category": item.get_category_display(),
            "category_code": item.category,
            "quantity": item.current_stock, "unit": item.unit, "critical_level": item.reorder_level,
            "average_unit_cost": item.average_unit_cost, "value": item.stock_value,
            "is_critical": item.is_critical, "on_order": ordered,
            # v95: durum — tükenmiş (kırmızı), kritik (turuncu), yeterli (yeşil)
            "is_out": item.current_stock <= 0,
            "status": "out" if item.current_stock <= 0 else ("low" if item.is_critical else "ok"),
            # Açık siparişle birlikte kritik seviyenin üstüne çıkacaksa yeniden sipariş gerekmez.
            "covered": item.current_stock + ordered > item.reorder_level,
            "supplier": item.supplier.name if item.supplier else None, "supplier_id": item.supplier_id,
        })
    rows.sort(key=lambda item: ({"out": 0, "low": 1}.get(item["status"], 2), item["name"].casefold()))   # tükenmiş, kritik, yeterli
    critical = [row for row in rows if row["is_critical"]]
    alerts = {}
    for row in critical:
        alerts.setdefault((row["supplier"] or "", row["supplier_id"]), []).append(row)
    # v94: stok analizi başlıkları (her biri açılır kart); kategoriye göre
    groups = []
    for key, title, codes, color in STOCK_GROUPS:
        items = [row for row in rows if row["category_code"] in codes]
        groups.append({"key": key, "title": title, "color": color, "items": items, "count": len(items),
                       "critical": sum(1 for row in items if row["status"] == "low"),
                       "out": sum(1 for row in items if row["status"] == "out"),
                       "value": sum((row["value"] for row in items), ZERO),
                       "categories": ", ".join(dict(InventoryItem.Category.choices)[code] for code in codes)})
    return {"rows": rows, "groups": groups, "product_count": len(rows), "stock_value": stock_value,
            "out_count": sum(1 for row in rows if row["status"] == "out"),
            "low_count": sum(1 for row in rows if row["status"] == "low"),
            "critical_count": len(critical), "last_closed_day": last_closed_day(),
            # Kritik ürünler tedarikçiye göre gruplanır: her tedarikçi için tek sipariş verilir.
            "alerts": [{"supplier": name or None, "supplier_id": supplier_id, "items": items,
                        "needs_order": any(not item["covered"] for item in items)}
                       for (name, supplier_id), items in sorted(alerts.items(), key=lambda pair: pair[0][0])],
            "open_orders": PurchaseOrder.objects.filter(status=PurchaseOrder.Status.OPEN).count()}


def order_form_rows(supplier, focus_item_id=None):
    """Sipariş formunun satırları: tedarikçinin aktif ürünleri.

    Sipariş tedarikçi başına verilir (bir sipariş = bir tedarikçi), bu yüzden formda tedarikçinin bütün ürünleri
    bulunur; ama yalnızca sipariş edilecek olanlar öne çıkar ("main"), diğerleri kapalı bir bölümde ("others")
    miktarı 0 olarak durur:
      - Belirli bir ürün için açıldıysa (stok tablosundaki satır butonu): yalnızca o ürün öne çıkar.
      - Tedarikçi için açıldıysa (uyarıdaki grup butonu): o tedarikçinin kritik ürünleri öne çıkar.
    """
    on_order = on_order_quantities()
    main, others = [], []
    for item in InventoryItem.objects.filter(supplier=supplier, active=True).order_by("name"):
        ordered = on_order.get(item.id, ZERO)
        suggested = suggested_order_quantity(item, ordered)
        is_focus = item.id == focus_item_id
        if is_focus and not suggested:
            # Stoğu yeterli bir ürün özellikle seçildiyse bir kritik seviye kadar önerilir.
            suggested = item.reorder_level
        selected = is_focus if focus_item_id else item.is_critical
        row = {"item": item, "on_order": ordered, "is_critical": item.is_critical,
               "suggested": suggested if selected else ZERO, "price": last_purchase_price(item)}
        (main if selected else others).append(row)
    return {"main": main, "others": others}


@transaction.atomic
def create_order(supplier, lines, notes=""):
    """lines: [(ürün, miktar, birim fiyat)]; miktarı 0 olan satırlar siparişe girmez."""
    lines = [(item, quantity, price) for item, quantity, price in lines if quantity > 0]
    if not lines:
        raise ValidationError("Siparişte en az bir ürünün miktarı sıfırdan büyük olmalı.")
    order = PurchaseOrder.objects.create(supplier=supplier, notes=notes)
    for item, quantity, price in lines:
        line = PurchaseOrderLine(order=order, item=item, quantity=quantity, unit_price=price)
        line.full_clean()
        line.save()
    return order


@transaction.atomic
def receive_order(order):
    """Teslim alınan siparişin her kalemi bir alım hareketi olur; stok ve ortalama maliyet buradan güncellenir."""
    order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
    if order.status != PurchaseOrder.Status.OPEN:
        raise ValidationError("Yalnızca açık sipariş teslim alınabilir.")
    now = timezone.now()
    for line in order.lines.select_related("item"):
        InventoryMovement.objects.create(
            item=line.item, movement_type=InventoryMovement.MovementType.PURCHASE, quantity=line.quantity,
            unit_cost=line.unit_price, movement_at=now,
            notes=f"Sipariş #{order.pk} teslim alındı · {order.supplier.name}")
    order.status, order.delivered_at = PurchaseOrder.Status.DELIVERED, now
    order.save(update_fields=["status", "delivered_at"])
    return order


def cancel_order(order):
    if order.status != PurchaseOrder.Status.OPEN:
        raise ValidationError("Yalnızca açık sipariş iptal edilebilir.")
    order.status = PurchaseOrder.Status.CANCELLED
    order.save(update_fields=["status"])
    return order


# --------------------------------------------------------------------------- ana sayfa özeti

def home_summary(as_of=None):
    """Ana sayfanın üç kartı: maliyet, fiyat ve satış, stok. Her kart ilgili ekranın en önemli rakamlarını özetler.

    Maliyet son TAMAMLANMIŞ aya göre verilir (doluluk ve atıl kapasite ay bitince kesinleşir); satış içinde bulunulan
    aya, stok bugüne göre. Oda-gece tam maliyeti fiyat takvimiyle aynı esastadır: değişken + ortak gider ÷ normal doluluk.
    """
    as_of = as_of or timezone.localdate()

    # Maliyet: son tamamlanmış ay
    last = last_completed_month(as_of)
    report = calculate_monthly_room_cost(last.year, last.month, as_of)
    normal, _ = normal_occupancy(as_of)
    type_normals = type_normal_occupancy(as_of)
    two_guests = [row for row in report["rows"] if row["guests"] == 2]
    full_costs = [row["variable"] + (row["semi_fixed"] + row["fixed"]) / type_normals.get(row["room_type_id"], normal)
                  for row in two_guests] if normal else []
    occupancy = report["occupancy"]
    cost = {
        "month": last.replace(day=1),
        "shared_total": report["shared_total"],
        "occupancy": occupancy["rate"] if occupancy else None,
        "normal": normal,
        "below_normal": bool(occupancy and normal and occupancy["rate"] < normal),
        "min_cost": min(full_costs) if full_costs else None,
        "max_cost": max(full_costs) if full_costs else None,
        "min_type": two_guests[full_costs.index(min(full_costs))]["room_type"] if full_costs else None,
        "max_type": two_guests[full_costs.index(max(full_costs))]["room_type"] if full_costs else None,
        "idle_cost": occupancy["idle_capacity_cost"] if occupancy else None,
    }

    # Fiyat ve satış: içinde bulunulan ay (gelir: ayın onaylı bütün geceleri) ve son kapanmış ayın sonucu
    month = month_occupancy(as_of.year, as_of.month, as_of)
    sales = month_sales(as_of.year, as_of.month)
    closed = ClosedPeriod.objects.order_by("-month").first()
    sales_card = {
        "month": as_of.replace(day=1),
        "occupancy": month["rate"] if month else None,
        "occupied_today": len(occupied_room_ids(as_of)),
        "rooms": _active_room_count(),
        "revenue": sales["revenue"],
        "commission": sales["commission"],
        "adr": sales["revenue"] / sales["priced_room_nights"] if sales["priced_room_nights"] else None,
        "closed_month": closed.month if closed else None,
        "closed_result": closed.result if closed else None,
    }

    # Stok: bugün
    stock = get_stock_summary()
    last_day = stock["last_closed_day"]
    stock_card = {
        "value": stock["stock_value"],
        "products": stock["product_count"],
        "critical": stock["critical_count"],
        "open_orders": stock["open_orders"],
        "last_closed_day": last_day,
        # Gün sonu dünkü geceyi işlemiş olmalı; daha eskiyse stok tüketimi geride kalmıştır.
        "days_behind": (as_of - timedelta(days=1) - last_day).days if last_day else None,
    }
    return {"cost": cost, "sales": sales_card, "stock": stock_card, "today": as_of}
