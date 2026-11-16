"""Önümüzdeki dönemin rezervasyonları: fiyat kararları, yeni rezervasyonlar ve kurallarla yeniden fiyatlama.

1. Otelin iki fiyat kararını ekler: Yılbaşı gala gecesi fiyatı (+%80) ve Aralık fırtına haftası kampanyası (−%85).
2. Aşağıdaki rezervasyonları, o tarihlerde boş olan bir odaya girer (oda tipi doluysa sıradaki tipe geçer).
3. Bugünden --bitis tarihine kadar giriş yapacak bütün onaylı rezervasyonların gecelik fiyatını fiyat kurallarıyla
   yeniden hesaplar: temel fiyat × gecenin etkisi × rezervasyon anındaki doluluk, sonra erken rezervasyon ve konaklama
   süresi indirimi (stay_price_quote). Taslak kararlar uygulanmaz.

Tekrar çalıştırılabilir: var olan karar ve rezervasyonlar yeniden eklenmez. --sil bu komutun eklediklerini kaldırır.
"""
from datetime import date, timedelta
from decimal import Decimal as D

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from dashboard.models import Event, Room, SalesChannel, Stay
from dashboard.services import normal_occupancy, stay_price_quote, type_normal_occupancy

DECISIONS = [
    ("Yılbaşı gala gecesi fiyatı", date(2026, 12, 31), date(2026, 12, 31), D("1.80"),
     "Yılbaşı gecesi talep her yıl çok güçlü; gala programıyla birlikte fiyat temel fiyatın %80 üstüne çekildi."),
    ("Fırtına haftası doluluk kampanyası", date(2026, 12, 7), date(2026, 12, 10), D("0.15"),
     "Aralık'ın ikinci haftası her yıl fırtına ve yoğun yağış nedeniyle iptallerin en yüksek olduğu hafta; pazarlama "
     "odaları önceden doldurmak için %85 indirimli kampanya açtı."),
]

WEB, PHONE, WALK_IN = "Web sitesi (doğrudan)", "Telefon / e-posta", "Kapıdan (walk-in)"
BOOKING, EXPEDIA, AGENCY = "Booking.com", "Expedia", "Seyahat acentası / tur operatörü"

# (oda tipi tercihi, kişi, giriş, çıkış, rezervasyon tarihi, kanal, açıklama)
RESERVATIONS = [
    (("STD", "SUP"), 2, date(2026, 10, 20), date(2026, 10, 22), date(2026, 10, 14), BOOKING, "Fashion Prime katılımcısı"),
    (("DLX", "LUX"), 2, date(2026, 10, 20), date(2026, 10, 23), date(2026, 10, 9), WEB, "Fuar firması; fatura şirkete"),
    (("LUX", "DLX"), 2, date(2026, 11, 4), date(2026, 11, 7), date(2026, 10, 10), EXPEDIA, ""),
    (("JRS", "LUX"), 2, date(2026, 12, 31), date(2027, 1, 1), date(2026, 10, 12), WEB, "Yılbaşı gala yemeği talebi"),
    (("EXS",), 2, date(2026, 12, 31), date(2027, 1, 1), date(2026, 9, 30), PHONE, "Yılbaşı; balayı çifti"),
    (("STD", "SUP"), 2, date(2026, 12, 31), date(2027, 1, 1), date(2026, 10, 5), BOOKING, ""),
    (("DLX", "EXR"), 2, date(2026, 12, 31), date(2027, 1, 1), date(2026, 10, 15), WEB, "Deniz manzarası istendi"),
    (("SUP", "STD"), 2, date(2026, 10, 17), date(2026, 10, 19), date(2026, 10, 16), WALK_IN, ""),
    (("STD", "SUP"), 1, date(2026, 10, 29), date(2026, 11, 1), date(2026, 10, 11), PHONE, "Cumhuriyet Bayramı tatili"),
    (("LUX", "JRS"), 2, date(2026, 11, 12), date(2026, 11, 15), date(2026, 10, 16), BOOKING, ""),
    (("JRS", "LUX"), 2, date(2026, 11, 20), date(2026, 11, 22), date(2026, 10, 13), EXPEDIA, ""),
    (("EXR", "DLX"), 2, date(2026, 11, 25), date(2026, 11, 27), date(2026, 10, 6), WEB, ""),
    (("DLX", "LUX"), 2, date(2026, 12, 18), date(2026, 12, 20), date(2026, 10, 16), WEB, ""),
    (("SUP", "STD"), 2, date(2027, 1, 15), date(2027, 1, 17), date(2026, 10, 8), AGENCY, "Tur grubu"),
    (("STD", "SUP"), 2, date(2027, 1, 22), date(2027, 1, 24), date(2026, 10, 16), BOOKING, ""),
    (("STD", "SUP"), 2, date(2026, 10, 26), date(2026, 10, 28), date(2026, 10, 15), BOOKING, ""),
    (("DLX", "LUX"), 2, date(2026, 11, 17), date(2026, 11, 19), date(2026, 10, 16), WEB, ""),
    (("STD", "SUP"), 2, date(2027, 1, 5), date(2027, 1, 21), date(2026, 9, 20), AGENCY, "Uzun konaklama; proje ekibi"),
    (("SUP", "STD"), 1, date(2026, 12, 14), date(2026, 12, 28), date(2026, 9, 25), WEB, "Uzun konaklama"),
    (("STD", "SUP"), 2, date(2026, 12, 7), date(2026, 12, 10), date(2026, 10, 14), WEB, ""),
    (("SUP", "STD"), 2, date(2026, 12, 8), date(2026, 12, 10), date(2026, 10, 16), BOOKING, ""),
]


class Command(BaseCommand):
    help = "Önümüzdeki dönemin rezervasyonlarını ekler ve bütün rezervasyonları fiyat kurallarıyla yeniden fiyatlar."

    def add_arguments(self, parser):
        parser.add_argument("--bitis", default="2027-02-01", help="Bu tarihten önce giriş yapanlar fiyatlanır (hariç).")
        parser.add_argument("--onizle", action="store_true", help="Hiçbir şeyi kaydetmeden sonucu gösterir.")
        parser.add_argument("--sil", action="store_true", help="Bu komutun eklediği karar ve rezervasyonları kaldırır.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        end = date.fromisoformat(options["bitis"])
        if options["sil"]:
            removed = sum(self.find(item).delete()[0] for item in RESERVATIONS if self.find(item) is not None)
            events = Event.objects.filter(name__in=[name for name, *_ in DECISIONS], kind=Event.Kind.DECISION).delete()[0]
            self.stdout.write(f"Kaldırılan rezervasyon: {removed}, karar: {events}. Fiyatlar yeniden hesaplanmadı.")
            return
        with transaction.atomic():
            for name, start, last, index, notes in DECISIONS:
                Event.objects.get_or_create(name=name, start_date=start, defaults={
                    "kind": Event.Kind.DECISION, "end_date": last, "index": index, "notes": notes, "published": True})
            channels = dict(SalesChannel.objects.values_list("name", "pk"))
            added = 0
            for item in sorted(RESERVATIONS, key=lambda row: row[4]):
                if self.find(item) is not None:
                    continue
                types, guests, check_in, check_out, booked_on, channel, notes = item
                room = self.free_room(types, check_in, check_out)
                if room is None:
                    self.stdout.write(self.style.WARNING(f"Boş oda yok: {types} {check_in:%d.%m}–{check_out:%d.%m}"))
                    continue
                Stay.objects.create(room=room, check_in=check_in, check_out=check_out, guests=guests,
                                    booked_on=booked_on, channel_id=channels.get(channel), notes=notes,
                                    status=Stay.Status.CONFIRMED)
                added += 1
            normal = normal_occupancy(today)
            type_normals = type_normal_occupancy(today)
            changed = 0
            stays = Stay.objects.occupying().filter(check_in__gte=today, check_in__lt=end).select_related("room__room_type")
            for stay in stays.order_by("booked_on", "check_in"):
                quote = stay_price_quote(stay.room.room_type, stay.guests, stay.check_in, stay.check_out,
                                         booked_on=min(stay.booked_on or today, today), as_of=today, normal=normal,
                                         type_normals=type_normals)
                if quote.get("missing_rate"):
                    continue
                rate = (quote["total"] / quote["nights"]).quantize(D("0.01"))
                if rate != stay.nightly_rate:
                    Stay.objects.filter(pk=stay.pk).update(nightly_rate=rate)
                    changed += 1
            self.stdout.write(f"Eklenen rezervasyon: {added}. Kurallarla yeniden fiyatlanan: {changed} "
                              f"(giriş {today:%d.%m.%Y} – {end - timedelta(days=1):%d.%m.%Y}).")
            if options["onizle"]:
                transaction.set_rollback(True)
                self.stdout.write("Önizleme: hiçbir şey kaydedilmedi.")

    @staticmethod
    def find(item):
        types, guests, check_in, check_out, booked_on, *_ = item
        return Stay.objects.filter(room__room_type__code__in=types, guests=guests, check_in=check_in,
                                   check_out=check_out, booked_on=booked_on).first()

    @staticmethod
    def free_room(types, check_in, check_out):
        busy = set(Stay.objects.occupying().filter(check_in__lt=check_out, check_out__gt=check_in)
                   .values_list("room_id", flat=True))
        for code in types:
            room = (Room.objects.filter(room_type__code=code, status=Room.Status.ACTIVE).exclude(pk__in=busy)
                    .order_by("room_number").first())
            if room:
                return room
        return None
