"""Gerçeğe benzeyen örnek konaklama verisi: rezervasyon sürecinin simülasyonu.

Gerçek bir otelin rezervasyon kayıtlarına benzesin diye her konaklama şu adımlarla üretilir:
  1. Her gecenin hedef doluluğu: ayın mevsimsel doluluğu × hafta günü etkisi × o gecenin etkinlik etkisi.
  2. Doluluk hedefe ulaşana kadar o gece başlayan konaklamalar açılır: gece sayısı (1-7), oda tipi
     (tercih ağırlığı × boş oda), kişi sayısı, satış kanalı.
  3. Rezervasyon tarihi = giriş - kanala göre ne kadar önceden alındığı (acenta erken, kapıdan aynı gün;
     fuar ve bayramlarda daha erken).
  4. Fiyat: o gecelerin fiyat takvimindeki fiyatı (temel fiyat × endeks, kişi sayısına göre); web sitesinde
     doğrudan rezervasyon indirimi, erken ve son dakika rezervasyonlarında küçük indirimler.
  5. İptal ve gelmeme: kanala göre oranlarla AYRI kayıtlar (odayı tutmazlar, doluluğu bozmazlar).
  6. Bugünden sonraki konaklamalardan yalnızca bugüne kadar alınmış rezervasyonlar kalır ("eldeki
     rezervasyonlar"); gelecek aylar zamanla dolar.

Bütün kayıtların açıklaması NOTE'dur; gerçek veri geldiğinde örnek veri bu açıklamayla bulunup silinir.
"""
import calendar
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from dashboard.models import (
    ClosedPeriod, Event, InventoryMovement, Room, SalesChannel, Stay, season_map,
)
from dashboard.services import close_month, market_rates, months_to_close, price_for_guests
from dashboard.signals import refresh_item_totals

D = Decimal
NOTE = "Örnek veri (rezervasyon simülasyonu)"
OLD_NOTES = {"Örnek konaklama (model verisi)", NOTE}

# Mevsimsel doluluk varsayımı (%), 2026. 2025 üç puan düşük (büyüyen otel), 2027 bir puan yüksek.
MONTHLY_OCCUPANCY = {1: 45, 2: 48, 3: 55, 4: 62, 5: 70, 6: 76, 7: 84, 8: 80, 9: 88, 10: 68, 11: 56, 12: 50}
YEAR_SHIFT = {2025: -3, 2026: 0, 2027: 1}
# Hafta gününe göre talep (Pzt..Paz): hafta sonu kaçamağı Cuma ve Cumartesi geceleri.
WEEKDAY_DEMAND = [0.97, 0.95, 0.96, 1.0, 1.12, 1.14, 0.84]
STAY_LENGTHS = [(1, 25), (2, 30), (3, 20), (4, 11), (5, 7), (7, 7)]          # (gece, ağırlık); ortalama ≈ 2,8
TYPE_PREFERENCE = {"STD": 1.25, "SUP": 1.15, "JRS": 1.0, "EXR": 0.85, "DLX": 0.75}   # v90: 5 oda tipi
# Kanal: (pay, ortalama kaç gün önce, iptal oranı, gelmeme oranı, fiyat çarpanı)
CHANNELS = {
    "Booking.com": (42, 32, 0.18, 0.015, D("1.00")),
    "Web sitesi (doğrudan)": (20, 28, 0.07, 0.005, D("0.95")),      # doğrudan rezervasyon indirimi
    "Expedia": (10, 38, 0.15, 0.015, D("1.00")),
    "Telefon / e-posta": (10, 12, 0.05, 0.010, D("1.00")),
    "Seyahat acentası / tur operatörü": (12, 70, 0.08, 0.005, D("1.00")),
    "Kapıdan (walk-in)": (6, 0, 0.0, 0.0, D("1.00")),
}
PRICE_2025 = D("0.75")      # 2025 fiyatları 2026'nın %75'i (v76: giderler ve hammadde ile aynı oran)


class Command(BaseCommand):
    help = ("Gerçeğe benzeyen ÖRNEK konaklama verisi üretir (kanal, rezervasyon tarihi, iptal, takvim fiyatı). "
            "Önceki örnek konaklamaları siler; elle girilmiş konaklama varsa hiçbir şey yapmaz. Kapanmış aylar "
            "ve gün sonu stok tüketimi yeni veriyle yeniden hesaplanır.")

    def add_arguments(self, parser):
        parser.add_argument("--baslangic", default="2025-01-01", help="İlk gece (YYYY-AA-GG). Varsayılan 2025-01-01.")
        parser.add_argument("--bitis", default="2027-06-30", help="Son gece (YYYY-AA-GG). Varsayılan 2027-06-30.")
        parser.add_argument("--tohum", type=int, default=2026, help="Rastgelelik tohumu (aynı tohum = aynı veri).")
        parser.add_argument("--onizle", action="store_true", help="Üretir, özetler, kaydetmez.")

    def handle(self, *args, **options):
        try:
            self.start = date.fromisoformat(options["baslangic"])
            self.end = date.fromisoformat(options["bitis"])
        except ValueError as exc:
            raise CommandError("Tarih biçimi YYYY-AA-GG olmalı.") from exc
        if self.end < self.start:
            raise CommandError("--bitis --baslangic'tan önce olamaz.")
        manual = Stay.objects.exclude(notes__in=OLD_NOTES).count()
        if manual:
            raise CommandError(f"{manual} elle girilmiş konaklama var; gerçek veriyi silmemek için işlem yapılmadı.")
        self.today = timezone.localdate()
        self.random = random.Random(options["tohum"])
        self.load_reference_data()

        with transaction.atomic():
            ClosedPeriod.objects.all().delete()                 # yeni veriyle yeniden kapatılacak
            day_close_until = self.undo_day_close()
            deleted, _ = Stay.objects.filter(notes__in=OLD_NOTES).delete()
            records = self.simulate()
            Stay.objects.bulk_create(records, batch_size=1000)
            self.report(records, deleted)
            if options["onizle"]:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING("ÖNİZLEME: hiçbir şey kaydedilmedi."))
                return
            if day_close_until:
                call_command("gun_sonu", kadar=day_close_until.isoformat(), ikmal=True, stdout=self.stdout)
            for month in months_to_close(as_of=self.today):
                close_month(month.year, month.month, as_of=self.today, notes="Örnek veri yenilendikten sonra kapatıldı")
        self.stdout.write(self.style.SUCCESS("Bitti. Kapanmış aylar ve gün sonu yeni veriyle yeniden hesaplandı."))

    # ------------------------------------------------------------------------------------------ hazırlık
    def load_reference_data(self):
        self.rooms = list(Room.objects.filter(status=Room.Status.ACTIVE, room_type__active=True)
                          .select_related("room_type").order_by("room_number"))
        if not self.rooms:
            raise CommandError("Satışa açık oda yok.")
        self.rooms_by_type = {}
        for room in self.rooms:
            self.rooms_by_type.setdefault(room.room_type, []).append(room)
        season_of = season_map()
        rates = market_rates()
        if not rates:
            raise CommandError("Temel fiyat yok (Veri girişi › Temel fiyatlar).")
        self.base_rate = lambda room_type, day: rates.get((room_type.id, season_of.get(day.month)))
        # Otelin kendi fiyat kararları talep yaratmaz; talep tahmininde yalnızca dış etkinlikler kullanılır.
        found = list(Event.objects.filter(end_date__gte=self.start, start_date__lte=self.end)
                     .exclude(kind=Event.Kind.DECISION))
        events = [event for event in found if event.weekday is None]
        weekly = [event for event in found if event.weekday is not None]
        self.night_index, self.event_index = {}, {}
        day = self.start
        while day <= self.end:
            todays = [event.index for event in events if event.applies_on(day)]
            week_value = max((event.index for event in weekly if event.applies_on(day)), default=D("1"))
            self.event_index[day] = max(todays, default=D("1"))
            self.night_index[day] = max([week_value] + todays)
            day += timedelta(days=1)
        channels = {channel.name: channel for channel in SalesChannel.objects.all()}
        missing = set(CHANNELS) - set(channels)
        if missing:
            raise CommandError(f"Satış kanalı eksik: {', '.join(sorted(missing))}")
        self.channels = [(channels[name], *values) for name, values in CHANNELS.items()]

    def undo_day_close(self):
        """Gün sonu tüketimi eski konaklamalara göre yazılmıştı: silinir, yeni veriyle yeniden yazılacak."""
        movements = InventoryMovement.objects.filter(consumption_day__isnull=False)
        last = movements.order_by("-consumption_day").values_list("consumption_day", flat=True).first()
        items = set(movements.values_list("item_id", flat=True))
        movements.delete()
        for item_id in items:
            refresh_item_totals(item_id)
        return last

    # ------------------------------------------------------------------------------------------ simülasyon
    def target_rooms(self, day):
        base = MONTHLY_OCCUPANCY[day.month] + YEAR_SHIFT.get(day.year, 0)
        demand = base / 100 * WEEKDAY_DEMAND[day.weekday()]
        demand *= 1 + float(self.event_index[day] - 1) * 1.3           # etkinlik talebi fiyattan güçlü artırır
        demand *= self.random.uniform(0.92, 1.08)
        return min(len(self.rooms) - 1, round(len(self.rooms) * min(demand, 0.99)))

    def pick(self, pairs):
        total = sum(weight for _, weight in pairs)
        point = self.random.uniform(0, total)
        for value, weight in pairs:
            point -= weight
            if point <= 0:
                return value
        return pairs[-1][0]

    def simulate(self):
        days = (self.end - self.start).days + 1
        busy = {room.id: bytearray(days) for room in self.rooms}
        records = []
        for offset in range(days):
            day = self.start + timedelta(days=offset)
            occupied = sum(busy[room.id][offset] for room in self.rooms)
            for _ in range(self.target_rooms(day) - occupied):
                stay = self.book(day, offset, days, busy)
                if stay:
                    records.extend(stay)
        return records

    def book(self, day, offset, days, busy):
        free = {room_type: [room for room in rooms if not busy[room.id][offset]]
                for room_type, rooms in self.rooms_by_type.items()}
        choices = [(room_type, TYPE_PREFERENCE.get(room_type.code, 1.0) * len(rooms))
                   for room_type, rooms in free.items() if rooms]
        if not choices:
            return None
        room_type = self.pick(choices)
        nights = min(self.pick(STAY_LENGTHS), days - offset)
        room, length = None, 0
        for candidate in self.random.sample(free[room_type], len(free[room_type])):
            fits = 0
            while fits < nights and not busy[candidate.id][offset + fits]:
                fits += 1
            if fits > length:
                room, length = candidate, fits
            if length == nights:
                break
        for night in range(length):
            busy[room.id][offset + night] = 1
        check_out = day + timedelta(days=length)
        guests = self.guests(room_type)
        channel, _, lead_mean, cancel_rate, no_show_rate, price_factor = self.pick(
            [(values, values[1]) for values in self.channels])
        lead = self.lead_days(lead_mean, day)
        booked_on = day - timedelta(days=lead)
        rate = self.price(room_type, guests, day, length, lead, price_factor)
        records = []
        if check_in_is_known(day, booked_on, self.today):
            records.append(Stay(room=room, channel=channel, booked_on=booked_on, check_in=day, check_out=check_out,
                                status=Stay.Status.CONFIRMED, guests=guests, nightly_rate=rate, notes=NOTE))
        # İptal ve gelmeme: aynı dönem için başka bir misafirin rezervasyonu; odayı tutmaz.
        for status, probability in ((Stay.Status.CANCELLED, cancel_rate), (Stay.Status.NO_SHOW, no_show_rate)):
            if self.random.random() < probability:
                other_lead = self.lead_days(lead_mean, day)
                other_booked = day - timedelta(days=other_lead)
                if check_in_is_known(day, other_booked, self.today) and (status == Stay.Status.CANCELLED or day <= self.today):
                    records.append(Stay(
                        room=self.random.choice(self.rooms_by_type[room_type]), channel=channel, booked_on=other_booked,
                        check_in=day, check_out=check_out, status=status, guests=guests, notes=NOTE,
                        nightly_rate=self.price(room_type, guests, day, length, other_lead, price_factor)))
        return records

    def guests(self, room_type):
        if room_type.max_guests >= 3:
            return self.pick([(1, 10), (2, 70), (3, 20)])
        return self.pick([(1, 18), (2, 82)])

    def lead_days(self, mean, day):
        if not mean:
            return 0
        if self.event_index[day] >= D("1.3"):
            mean *= 1.5                                         # fuar ve bayramlarda daha erken rezervasyon
        return min(300, int(self.random.expovariate(1 / mean)))

    def price(self, room_type, guests, check_in, nights, lead, channel_factor):
        total = D("0")
        for night in range(nights):
            day = check_in + timedelta(days=night)
            base = self.base_rate(room_type, day)
            if base is None:
                return None
            total += price_for_guests(base * self.night_index[day], guests, room_type)
        rate = total / nights * channel_factor
        if lead >= 60:
            rate *= D("0.92")                                   # erken rezervasyon indirimi
        elif lead <= 2 and self.event_index[check_in] == 1:
            rate *= D("0.90")                                   # son dakika: boş kalacak odayı doldurma
        if check_in.year == 2025:
            rate *= PRICE_2025
        return (rate / 10).quantize(D("1"), rounding=ROUND_HALF_UP) * 10

    # ------------------------------------------------------------------------------------------ özet
    def report(self, records, deleted):
        confirmed = [stay for stay in records if stay.status == Stay.Status.CONFIRMED]
        self.stdout.write(f"Silinen eski örnek konaklama: {deleted}. Yeni kayıt: {len(records)} "
                          f"(onaylı {len(confirmed)}, iptal {sum(s.status == Stay.Status.CANCELLED for s in records)}, "
                          f"gelmedi {sum(s.status == Stay.Status.NO_SHOW for s in records)}).")
        rooms = len(self.rooms)
        for year in range(self.start.year, self.end.year + 1):
            line = []
            for month in range(1, 13):
                first = date(year, month, 1)
                if first < self.start.replace(day=1) or first > self.end:
                    continue
                last = date(year, month, calendar.monthrange(year, month)[1])
                nights = sum((min(stay.check_out, last + timedelta(days=1)) - max(stay.check_in, first)).days
                             for stay in confirmed if stay.check_in <= last and stay.check_out > first)
                line.append(f"{month:02d}:%{100 * nights / (rooms * last.day):.0f}")
            self.stdout.write(f"  {year} doluluk  " + "  ".join(line))


def check_in_is_known(check_in, booked_on, today):
    """Bugüne kadar alınmış rezervasyon mu? Bugünden sonra alınacak rezervasyonlar henüz yoktur."""
    return booked_on <= today
