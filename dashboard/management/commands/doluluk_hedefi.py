"""Seçilen ayların doluluğunu hedef orana tamamlar (örnek veri, v58).

Varsayılan: 2026 yaz ayları, Mayıs %91, Haziran %95, Temmuz %93, Ağustos %97, Eylül %99 (kullanıcı kararı).

Yalnızca EKLER, mevcut konaklamalara dokunmaz. Eksik oda-geceler gerçekçi konaklamalarla doldurulur: oda tipi tercihi,
konaklama süresi, kişi sayısı, satış kanalı ve kaç gün önce rezervasyon yapıldığı örnek konaklama üreticisindeki
(gercekci_konaklama_olustur) dağılımlardan; gecelik fiyat temel fiyat (oda tipi × mevsim) × gecenin endeksi (etkinlik /
hafta günü / otel kararı) × kanal çarpanıdır (2025'te üreticideki gibi × %75). Konaklamalar ayın içinde kalır (sonraki ayın doluluğu değişmez).
Kapanmış aylar yeni satışlarla yeniden kapatılır. Gün sonu yapılmış gecelere eklenen konaklama stoktan düşülmez.

    python manage.py doluluk_hedefi                         # 2026 yaz ayları, varsayılan hedefler
    python manage.py doluluk_hedefi --hedef 5=91,6=95 --onizle
    python manage.py doluluk_hedefi --sil                   # bu komutun eklediklerini geri alır
    python manage.py doluluk_hedefi --aralik "2027-01-18:2027-01-22=85;2027-05-14:2027-05-20=95"
        # ÖN SATIŞ: gelecekteki tarih aralıklarını bugüne kadar alınmış rezervasyonlarla doldurur (rezervasyon tarihi
        # bugünden sonra olamaz). Fiyat teklifinde o gecelerin anlık doluluğu yükselir, fiyat motoru talebi görür.
    python manage.py doluluk_hedefi --yil 2025 --hedef izmir --azalt
        # AZALTMA (v71): hedefin üstündeki ayları hedefe indirir (örnek veri konaklamaları rastgele silinir; elle
        # girilmiş konaklamalara dokunulmaz), hedefin altındakileri tamamlar. "izmir" = IZMIR_TARGETS.
"""
import random
from datetime import date, timedelta
from decimal import Decimal as D, ROUND_HALF_UP

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from dashboard.management.commands.gercekci_konaklama_olustur import (CHANNELS, PRICE_2025, STAY_LENGTHS,
                                                                      TYPE_PREFERENCE)
from dashboard.models import ClosedPeriod, Room, SalesChannel, Stay, season_map
from dashboard.services import close_month, market_rates, month_bounds, night_factors, price_for_guests

DEFAULT_TARGETS = "5=91,6=95,7=93,8=97,9=99"
# v71: Kültür ve Turizm Bakanlığı konaklama istatistikleri, İzmir 2024 aylık doluluk (tüm belgeli tesisler, yatak doluluğu):
#   Oca 23,9 Şub 25,2 Mar 26,6 Nis 37,6 May 41,9 Haz 49,4 Tem 61,8 Ağu 70,9 Eyl 52,0 Eki 47,7 Kas 29,2 Ara 24,5 (yıl ~%41).
# Bakanlık bülteninde İzmir'de "otel" türü tesislerin doluluğu tüm tesis ortalamasından ~%21 yüksek (Ocak–Temmuz 2025:
# otel %61,04, genel %50,33). Pasaport Pier bir şehir oteli: aylık hedef = İzmir aylık × 1,21 (yıllık ~%49).
IZMIR_2024 = {1: "23.9", 2: "25.2", 3: "26.6", 4: "37.6", 5: "41.9", 6: "49.4", 7: "61.8", 8: "70.9", 9: "52.0",
              10: "47.7", 11: "29.2", 12: "24.5"}
HOTEL_FACTOR = D("1.21")
IZMIR_TARGETS = ",".join(f"{month}={(D(rate) * HOTEL_FACTOR).quantize(D('1'), rounding=ROUND_HALF_UP)}"
                         for month, rate in IZMIR_2024.items())
# Azaltmada silinebilecek konaklamalar: yalnız üretilmiş örnek veri (elle girilen konaklamalar korunur).
REMOVABLE_NOTES = ("Örnek veri (rezervasyon simülasyonu)", "Doluluk hedefi")
NOTE = "Doluluk hedefi"
PRESALE_NOTE = "Doluluk hedefi · ön satış"
MONTH_NAMES = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
               "Kasım", "Aralık"]


class Command(BaseCommand):
    help = "Seçilen ayların doluluğunu hedef orana tamamlar (yalnız ekler). Kapanmış aylar yeniden kapatılır."

    def add_arguments(self, parser):
        parser.add_argument("--yil", type=int, default=2026)
        parser.add_argument("--hedef", default=DEFAULT_TARGETS, help="ay=yüzde listesi, ör. 5=91,6=95")
        parser.add_argument("--tohum", type=int, default=58, help="Aynı veriyi yeniden üretmek için rastgelelik tohumu")
        parser.add_argument("--onizle", action="store_true", help="Kaydetmeden ne ekleneceğini gösterir")
        parser.add_argument("--sil", action="store_true", help="Bu komutun o yıl eklediği konaklamaları siler")
        parser.add_argument("--aralik", default="", help="Ön satış: BAŞ:BİT=YÜZDE;... (bitiş hariç), ör. 2027-07-01:2027-08-01=60")
        parser.add_argument("--bugun", default="", help="Ön satışta rezervasyon tarihlerinin üst sınırı (varsayılan bugün)")
        parser.add_argument("--azalt", action="store_true",
                            help="Hedefin üstündeki ayları örnek veri konaklamalarını silerek hedefe indirir")

    def handle(self, *args, **options):
        year = options["yil"]
        self.random = random.Random(options["tohum"])
        if options["sil"]:
            return self.remove(year)
        if options["aralik"]:
            return self.presale(options)
        if options["hedef"] == "izmir":
            options["hedef"] = IZMIR_TARGETS
        try:
            targets = {int(month): D(percent) / 100 for month, percent in
                       (pair.split("=") for pair in options["hedef"].split(","))}
        except ValueError:
            raise CommandError("--hedef biçimi: 5=91,6=95 (ay=yüzde).")
        if any(not 1 <= month <= 12 or not 0 < rate <= 1 for month, rate in targets.items()):
            raise CommandError("Ay 1–12, yüzde 1–100 olmalı.")
        self.load()
        with transaction.atomic():
            for month in sorted(targets):
                if options["azalt"]:
                    self.reduce(year, month, targets[month])
                self.fill(year, month, targets[month], options["onizle"])
            if options["onizle"]:
                transaction.set_rollback(True)
                self.stdout.write("Önizleme: hiçbir şey kaydedilmedi.")

    def load(self):
        self.rooms = list(Room.objects.filter(status=Room.Status.ACTIVE, room_type__active=True).select_related("room_type"))
        self.seasons = season_map()
        self.rates = market_rates()
        channels = {channel.name: channel for channel in SalesChannel.objects.all()}
        self.channels = [(channels[name], *values) for name, values in CHANNELS.items() if name in channels]

    def pick(self, pairs):
        total = sum(weight for _, weight in pairs)
        point = self.random.uniform(0, total)
        for value, weight in pairs:
            point -= weight
            if point <= 0:
                return value
        return pairs[-1][0]

    def presale(self, options):
        """Gelecek tarih aralıklarını bugüne kadar alınmış (ön satış) rezervasyonlarla hedef doluluğa tamamlar."""
        from django.utils import timezone
        self.presale_until = date.fromisoformat(options["bugun"]) if options["bugun"] else timezone.localdate()
        try:
            ranges = []
            for part in options["aralik"].split(";"):
                period, percent = part.strip().split("=")
                first, last = (date.fromisoformat(value) for value in period.split(":"))
                ranges.append((first, last, D(percent) / 100))
        except ValueError:
            raise CommandError("--aralik biçimi: 2027-07-01:2027-08-01=60;... (başlangıç:bitiş=yüzde, bitiş hariç)")
        self.load()
        with transaction.atomic():
            for first, last, target in ranges:
                if first <= self.presale_until:
                    raise CommandError(f"Ön satış aralığı bugünden ({self.presale_until:%d.%m.%Y}) sonra başlamalı.")
                self.fill_range(first, last, target, options["onizle"], f"{first:%d.%m.%Y}–{last:%d.%m.%Y}")
            if options["onizle"]:
                transaction.set_rollback(True)
                self.stdout.write("Önizleme: hiçbir şey kaydedilmedi.")

    def reduce(self, year, month, target, keep=frozenset()):
        """Ayın doluluğu hedefin üstündeyse örnek veri konaklamalarını rastgele siler (önce ayın içinde kalanlar).

        keep: dokunulmayacak geceler (ör. tam dolu tutulan özel günler); bu gecelerden birine değen konaklama silinmez.
        """
        start, end = month_bounds(year, month)
        rooms = len(self.rooms)
        capacity = rooms * (end - start).days
        goal = int((target * capacity).to_integral_value(ROUND_HALF_UP))

        def nights(stay):
            return (min(stay.check_out, end) - max(stay.check_in, start)).days

        stays = list(Stay.objects.occupying().filter(check_in__lt=end, check_out__gt=start))
        occupied = sum(nights(stay) for stay in stays)
        before = occupied
        def touches_keep(stay):
            day = stay.check_in
            while day < stay.check_out:
                if day in keep:
                    return True
                day += timedelta(days=1)
            return False

        candidates = [stay for stay in stays if stay.notes in REMOVABLE_NOTES and not (keep and touches_keep(stay))]
        self.random.shuffle(candidates)
        candidates.sort(key=lambda stay: not (stay.check_in >= start and stay.check_out <= end))   # ay içindekiler önce
        removed = []
        for stay in candidates:
            if occupied <= goal:
                break
            removed.append(stay.pk)
            occupied -= nights(stay)
        Stay.objects.filter(pk__in=removed).delete()
        self.stdout.write(f"{MONTH_NAMES[month]} {year}: %{100 * before / capacity:.1f} → %{100 * occupied / capacity:.1f} "
                          f"(hedef %{target * 100:.0f}); {len(removed)} konaklama silindi.")

    def fill(self, year, month, target, preview):
        start, end = month_bounds(year, month)
        self.fill_range(start, end, target, preview, f"{MONTH_NAMES[month]} {year}")
        if not preview and ClosedPeriod.objects.filter(month=start).exists():
            close_month(year, month, reopen=True, notes=f"Doluluk hedefi %{target * 100:.0f} ile yeniden kapatıldı")
            self.stdout.write(f"  {MONTH_NAMES[month]} {year} yeni satışlarla yeniden kapatıldı.")

    def fill_range(self, start, end, target, preview, label):
        days = [start + timedelta(days=n) for n in range((end - start).days)]
        busy = {room.id: set() for room in self.rooms}
        for room_id, check_in, check_out in (Stay.objects.occupying().filter(check_in__lt=end, check_out__gt=start)
                                             .values_list("room_id", "check_in", "check_out")):
            if room_id in busy:
                day = max(check_in, start)
                while day < min(check_out, end):
                    busy[room_id].add(day)
                    day += timedelta(days=1)
        occupied = {day: sum(day in nights for nights in busy.values()) for day in days}
        rooms = len(self.rooms)
        goal = int((target * rooms * len(days)).to_integral_value(ROUND_HALF_UP))
        before = sum(occupied.values())
        if before >= goal:
            self.stdout.write(f"{label}: doluluk zaten %{100 * before / (rooms * len(days)):.1f}; "
                              f"hedef %{target * 100:.0f}. Eklenmedi (mevcut kayıtlar silinmez).")
            return
        # Gece kotası: ay toplamı hedefe eşit; artan odalar önce Cuma ve Cumartesi gecelerine.
        base, extra = divmod(goal, len(days))
        order = sorted(days, key=lambda day: (day.weekday() not in (4, 5), day))
        quota = {day: min(rooms, base + (1 if order.index(day) < extra else 0)) for day in days}
        factors = night_factors(start, end, as_of=start)
        created, added = [], 0
        for allow_over in (False, True):              # ikinci tur: kotası dolmuş gecelerden dolayı kalan eksik
            for day in days:
                limit = rooms if allow_over else quota[day]
                while occupied[day] < limit and before + added < goal:
                    stay = self.book(day, end, busy, occupied, quota, allow_over, factors)
                    if stay is None:
                        break
                    created.append(stay)
                    added += (stay.check_out - stay.check_in).days
        after = before + added
        if not preview:
            Stay.objects.bulk_create(created)
        self.stdout.write(f"{label}: %{100 * before / (rooms * len(days)):.1f} → "
                          f"%{100 * after / (rooms * len(days)):.1f} (hedef %{target * 100:.0f}); "
                          f"{len(created)} konaklama, {after - before} oda-gece eklendi.")

    def book(self, day, end, busy, occupied, quota, allow_over, factors):
        free = [room for room in self.rooms if day not in busy[room.id]]
        if not free:
            return None
        room = self.pick([(room, TYPE_PREFERENCE.get(room.room_type.code, 1.0)) for room in free])
        wanted = self.pick(STAY_LENGTHS)
        length, night = 0, day
        while (length < wanted and night < end and night not in busy[room.id]
               and (allow_over or occupied[night] < quota[night])):
            length += 1
            night += timedelta(days=1)
        length = max(length, 1)
        for offset in range(length):
            busy[room.id].add(day + timedelta(days=offset))
            occupied[day + timedelta(days=offset)] += 1
        room_type = room.room_type
        guests = self.pick([(1, 10), (2, 70), (3, 15), (4, 5)] if room_type.max_guests >= 4 else
                           [(1, 10), (2, 70), (3, 20)] if room_type.max_guests == 3 else [(1, 18), (2, 82)])
        channel, _, lead_mean, _, _, channel_factor = self.pick([(values, values[1]) for values in self.channels])
        lead = min(300, int(self.random.expovariate(1 / lead_mean))) if lead_mean else 0
        booked_on = day - timedelta(days=lead)
        presale = getattr(self, "presale_until", None)
        if presale and booked_on > presale:                 # ön satış: rezervasyon bugüne kadar alınmış olmalı
            booked_on = presale - timedelta(days=self.random.randint(0, 60))
            lead = (day - booked_on).days
        check_out = day + timedelta(days=length)
        return Stay(room=room, channel=channel, booked_on=booked_on, check_in=day,
                    check_out=check_out, status=Stay.Status.CONFIRMED, guests=guests,
                    notes=PRESALE_NOTE if presale else NOTE,
                    nightly_rate=self.price(room_type, guests, day, length, lead, channel_factor, factors))

    def price(self, room_type, guests, check_in, nights, lead, channel_factor, factors):
        total = D("0")
        early = D("0.92") if lead >= 60 else D("1")              # erken rezervasyon indirimi (üreticiyle aynı)
        for offset in range(nights):
            day = check_in + timedelta(days=offset)
            base = self.rates.get((room_type.id, self.seasons.get(day.month)))
            if base is None:
                return None
            night = price_for_guests(base * factors[day]["index"], guests, room_type)
            # Özel gün gecesinde indirim yok (v79/v80): erken rezervasyon indirimi yalnız sıradan gecelere.
            total += night if factors[day].get("special") is not None else night * early
        rate = total / nights * channel_factor
        if check_in.year == 2025:
            rate *= PRICE_2025                                  # 2025 fiyatları %75 (giderlerle aynı oran, üreticiyle aynı)
        return (rate / 10).quantize(D("1"), rounding=ROUND_HALF_UP) * 10

    def remove(self, year):
        stays = Stay.objects.filter(notes__startswith=NOTE, check_in__year=year)
        months = sorted({date(year, month, 1) for month in stays.values_list("check_in__month", flat=True)})
        count = stays.count()
        with transaction.atomic():
            stays.delete()
            for month in months:
                if ClosedPeriod.objects.filter(month=month).exists():
                    close_month(month.year, month.month, reopen=True, notes="Doluluk hedefi geri alındı")
        self.stdout.write(f"{count} konaklama silindi; {len(months)} ay yeniden hesaplandı.")
