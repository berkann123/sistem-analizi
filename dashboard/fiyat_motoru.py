"""Fiyat motoru: bir oda-gecenin satış fiyatını maliyet kalemlerinden ve talepten hesaplar (v64).

Karma çapa (kullanıcı kararı): hedef fiyat maliyetten gelir, piyasa fiyatı tavan olarak sınırlar.

    ① Maliyet tabanı   değişken maliyet (V), tam maliyet (F = V + sabit gider payı ÷ tipin normal doluluğu),
                        hedef fiyat (T = F × (1 + oda tipinin hedef marjı))
    ② Çapa             min(T, piyasa fiyatı M). M = temel fiyat (oda tipi × mevsim), kişi sayısına göre.
    ③ Talep ayarı      çapa × gecenin endeksi (etkinlik / hafta günü) × anlık doluluk çarpanı
                        × (1 − son dakika indirimi) son dakikada otel boşsa (oda boş kalmasın)
    ④ Alt sınır        normal günlerde F. Son dakikada (girişe ≤ N gün ve o gece doluluk < %X) V × (1 + pay):
                        oda boş kalmasın, giderini karşılayıp sabit gidere katkı versin. Fiyat bunun altına inmez.
    Otel fiyat kararı olan gecede karar son sözdür: fiyat = piyasa fiyatı × kararın endeksi; alt sınır uygulanmaz,
    fiyat değişken maliyetin altındaysa uyarı verilir.
    Kâr koruması (v70): oda tipinin asgari kâr marjı (min_markup) > 0 ise alt sınır her gün F × (1 + marj) olur;
    son dakika indirimi ve otel kararları da bunun altına indiremez (Deluxe, Executive Oda, Executive Suite: %5).
    Özel gün (v79): bayram, resmi tatil ve özel gün gecelerinde hiçbir indirim yok: son dakika indirimi, doluluk
    indirimi, indirim yönlü otel kararı, erken rezervasyon ve uzun konaklama indirimi uygulanmaz.
    Oda tipi doluluğu (v82): oda tipi otelden daha doluysa doluluk çarpanı tipin doluluğuyla ölçülür (yalnız artırır).
    Ek kişi ücreti (v82): 3. ve 4. kişinin ücreti sabittir; çarpanlar yalnız odanın 1–2 kişilik fiyatına uygulanır.
    Fiyat sırası (v89): Standart < Superior < Junior Suite < Luxury < Deluxe < Executive Oda < Executive Suite; her
    tip her gece bir alttakinin en az %2 üstündedir (oda tipi talebi ya da son dakika sırayı bozamaz).
    ⑤ Kanal ve vergi    kanal fiyatı = net fiyat ÷ (1 − komisyon); misafirin ödeyeceği = KDV ve konaklama vergisi eklenir.

Tutarlar TL, KDV hariç. Ayarlar `fiyat_kurallari` tablosunda (Admin › Fiyat kuralları).
"""
from datetime import timedelta
from decimal import Decimal as D

from django.utils import timezone

from . import fiyat_kurallari as kural
from django.db.models import Q

from .models import Room, RoomType, Stay, season_map
from .services import (
    ONE, calculate_monthly_room_cost, market_rates, night_factors, normal_occupancy, price_for_guests, price_status,
    type_normal_occupancy,
)

ANCHOR_LABELS = {"target": "maliyetten hedef fiyat", "market": "piyasa fiyatı (tavan)"}
ORDER_STEP = D("0.02")     # v89: pahalı oda tipi bir alttakinden en az %2 pahalı


class FiyatMotoru:
    """[start, end) geceleri için fiyat hesaplar. Veritabanı sorguları bir kez yapılır, geceler bellekten hesaplanır.

    booked_on: fiyatın verildiği gün (rezervasyon anı). Anlık doluluk ve son dakika bu güne göre ölçülür.
    for_booking: rezervasyon fiyatında taslak (yayında olmayan) otel kararları yok sayılır.
    """

    def __init__(self, start, end, as_of=None, booked_on=None, for_booking=False, normal=None, type_normals=None):
        self.as_of = as_of or timezone.localdate()
        self.booked_on = booked_on or self.as_of
        self.factors = night_factors(start, end, self.booked_on, for_booking=for_booking)
        self.rules = kural.current()
        # normal / type_normals verilirse yeniden hesaplanmaz (çok sayıda teklif hesaplayan komutlar için).
        self.normal, self.normal_source = normal if normal is not None else normal_occupancy(self.as_of)
        self.type_normals = type_normals if type_normals is not None else type_normal_occupancy(self.as_of)
        self.seasons = season_map()
        self.rates = market_rates()
        self._rows = {}
        # v89: fiyat sırası — oda tipleri ucuzdan pahalıya (maliyet payı katsayısı). Pahalı tip hiçbir gece bir alttaki
        # tipin fiyatının ORDER_STEP fazlasının altına inmez (Standart en ucuz … Executive Suite en pahalı).
        self.order = list(RoomType.objects.filter(active=True).order_by("standard_cost_factor", "code"))
        self._cache = {}
        # v82: oda tipinin kendi anlık doluluğu (rezervasyon anına kadar satılan oda ÷ tipin aktif odası).
        self.type_rooms = {}
        for type_id in Room.objects.filter(status=Room.Status.ACTIVE).values_list("room_type_id", flat=True):
            self.type_rooms[type_id] = self.type_rooms.get(type_id, 0) + 1
        self.type_sold = {}
        stays = (Stay.objects.occupying().filter(check_in__lt=end, check_out__gt=start)
                 .filter(Q(booked_on__isnull=True) | Q(booked_on__lte=self.booked_on))
                 .values_list("room__room_type_id", "check_in", "check_out"))
        for type_id, first, last in stays:
            day = max(first, start)
            while day < min(last, end):
                self.type_sold[(type_id, day)] = self.type_sold.get((type_id, day), 0) + 1
                day += timedelta(days=1)

    def type_occupancy(self, room_type, day):
        rooms = self.type_rooms.get(room_type.id, 0)
        if not rooms:
            return None
        return min(D(self.type_sold.get((room_type.id, day), 0)) / rooms, ONE)

    def costs(self, room_type, guests, day):
        """(değişken maliyet, tam maliyet, hedef fiyat) ya da maliyet satırı yoksa (None, None, None)."""
        key = (day.year, day.month)
        if key not in self._rows:
            self._rows[key] = calculate_monthly_room_cost(day.year, day.month, self.as_of)["rows"]
        row = next((r for r in self._rows[key] if r["room_type_id"] == room_type.id and r["guests"] == guests), None)
        if row is None:
            return None, None, None
        normal = self.type_normals.get(room_type.id, self.normal)
        full = row["variable"] + (row["semi_fixed"] + row["fixed"]) / normal
        return row["variable"], full, full * (ONE + room_type.target_markup)

    def market(self, room_type, guests, day):
        base = self.rates.get((room_type.id, self.seasons.get(day.month)))
        return price_for_guests(base, guests, room_type)

    def night(self, room_type, guests, day):
        """Bir gecenin fiyatı ve adım adım gerekçesi; fiyat sırası koruması dahil (v89)."""
        guests = max(1, min(guests, room_type.max_guests))
        key = (room_type.id, guests, day)
        if key in self._cache:
            return self._cache[key]
        result = self._night(room_type, guests, day)
        result.update({"type_rooms": self.type_rooms.get(room_type.id, 0),
                       "type_sold": self.type_sold.get((room_type.id, day), 0), "order_applied": False})
        position = next((i for i, t in enumerate(self.order) if t.id == room_type.id), None)
        if position and result["price"] is not None:
            cheaper = self.order[position - 1]
            cheaper_guests = min(guests, cheaper.max_guests)
            lower = self.night(cheaper, cheaper_guests, day)
            if lower["price"] is not None:
                minimum = lower["price"] * (ONE + ORDER_STEP) + room_type.extra_guest_rate * (guests - cheaper_guests)
                if result["price"] < minimum:
                    result.update({"price": minimum, "order_applied": True, "order_below": cheaper.name,
                                   "order_floor": minimum,
                                   "status": price_status(minimum, result["variable"], result["full"], result["target"])})
        self._cache[key] = result
        return result

    def _night(self, room_type, guests, day):
        """Tek oda tipinin gece fiyatı (sıra koruması öncesi)."""
        night = self.factors[day]
        variable, full, target = self.costs(room_type, guests, day)
        market = self.market(room_type, guests, day)
        event = night["event"]
        decision = event if event is not None and event.is_decision else None
        days_ahead = (day - self.booked_on).days
        result = {"date": day, "guests": guests, "variable": variable, "full": full, "target": target,
                  "special": night.get("special"), "skipped_decision": night.get("skipped_decision"),
                  "market": market, "index": night["index"], "occupancy": night["occupancy"],
                  "occupancy_factor": night["occupancy_factor"], "days_ahead": days_ahead, "decision": decision,
                  "event": event, "floor": None, "floor_kind": "", "floor_applied": False, "warning": "",
                  "last_minute": False}
        if market is None and target is None:
            result.update({"anchor": None, "anchor_source": "", "demand": None, "raw": None, "price": None,
                           "status": "unknown"})
            return result
        # Ek kişi ücreti (v82): 2 kişiden sonraki her kişinin ücreti sabittir; talep, etkinlik ve indirim çarpanları
        # yalnız odanın 1–2 kişilik fiyatına uygulanır (model açıklaması ve örnek veri üreticisiyle aynı kural).
        extra = room_type.extra_guest_rate * (guests - 2) if guests > 2 else D("0")
        # Talep (v82): oda tipi otelden daha doluysa doluluk çarpanı tipin doluluğuyla ölçülür; yalnız fiyatı ARTIRABİLİR,
        # otelin doluluğuyla hesaplanan eski fiyatın altına inmez (sistemin geri kalanı değişmez).
        type_rate = self.type_occupancy(room_type, day)
        hotel_rate = night["occupancy"]
        factor, basis, used_rate, multiplier = night["occupancy_factor"], "otel", hotel_rate, night["multiplier"]
        if not decision and type_rate is not None and (hotel_rate is None or type_rate > hotel_rate):
            type_factor, _ = kural.occupancy_band(type_rate, self.rules)
            used_rate = type_rate                                   # son dakika kararı da daha dolu olana göre
            if type_factor > factor:
                factor, basis, multiplier = type_factor, "oda tipi", night["index"] * type_factor
        result.update({"type_occupancy": type_rate, "occupancy_used": used_rate, "occupancy_basis": basis,
                       "occupancy_factor": factor, "extra_guest": extra})
        # Kâr koruması (v70): asgari kâr marjı olan oda tipi hiçbir gün tam maliyet × (1 + marj) altına inmez.
        guard = full * (ONE + room_type.min_markup) if full is not None and room_type.min_markup > 0 else None
        result["protected"] = guard is not None
        if decision:
            # Otelin elle verdiği karar son sözdür: piyasa fiyatı × kararın endeksi; alt sınır uygulanmaz.
            # Kâr korumalı oda tipinde karar da asgari kâr sınırının altına indiremez.
            anchor, source = (market, "market") if market is not None else (target, "target")
            demand = decision.index
            raw = (anchor - extra) * demand + extra
            price = raw
            if guard is not None:
                result.update({"floor": guard, "floor_kind": "kâr koruması"})
                if price < guard:
                    price = guard
                    result["floor_applied"] = True
                    result["warning"] = ("Kâr koruması: otel kararı bu oda tipini kârsız satıyordu; fiyat tam maliyet + "
                                         f"%{room_type.min_markup * 100:.0f} seviyesine çekildi.")
            elif variable is not None and price < variable:
                result["warning"] = "Otel kararı fiyatı misafir gelince harcananın altına indiriyor: her satış zarar yazar."
        else:
            candidates = [(value, key) for value, key in ((target, "target"), (market, "market")) if value is not None]
            anchor, source = min(candidates, key=lambda pair: pair[0])
            rules = self.rules
            last_minute = (night.get("special") is None and 0 <= days_ahead <= rules.last_minute_days and
                           (used_rate is None or used_rate < rules.last_minute_occupancy))
            demand = multiplier
            if last_minute:
                demand *= ONE - rules.last_minute_discount          # boş kalacak oda için son dakika indirimi
            result["last_minute"] = last_minute
            raw = (anchor - extra) * demand + extra
            if guard is not None:
                floor, kind = guard, "kâr koruması"                # büyük / lüks oda: son dakikada da kârlı
            elif variable is not None and last_minute:
                floor, kind = variable * (ONE + rules.last_minute_markup), "son dakika"
            else:
                floor, kind = full, "tam maliyet"
            price = raw
            if floor is not None and raw < floor:
                price = floor
                result["floor_applied"] = True
            result.update({"floor": floor, "floor_kind": kind})
        result.update({"anchor": anchor, "anchor_source": source, "anchor_label": ANCHOR_LABELS[source],
                       "demand": demand, "raw": raw, "price": price,
                       "status": price_status(price, variable, full, target)})
        return result


def channel_price(net_price, commission_rate):
    """Kanalda satış fiyatı: komisyon düşüldükten sonra otele net fiyat kalacak şekilde brütleştirilir."""
    if net_price is None:
        return None
    return net_price / (ONE - commission_rate) if commission_rate < ONE else None


def nights(start, end):
    day = start
    while day < end:
        yield day
        day += timedelta(days=1)
