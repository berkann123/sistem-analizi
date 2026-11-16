from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import RoomPackageItem, RoomType, SalesChannel


class ChannelChoiceField(forms.ModelChoiceField):
    """Açılır listede kanal adı ve komisyonu: "Booking.com (komisyon %17)"."""

    def label_from_instance(self, obj):
        rate = obj.commission_rate * 100
        return f"{obj.name} (komisyonsuz)" if not rate else f"{obj.name} (komisyon %{rate:.0f})"


class ReservationCostForm(forms.Form):
    room_type = forms.ModelChoiceField(
        label="Oda tipi",
        queryset=RoomType.objects.filter(active=True).order_by("standard_cost_factor"),
        empty_label="Oda tipi seçin",
    )
    guests = forms.IntegerField(label="Misafir sayısı", min_value=1, max_value=4, initial=1)
    check_in = forms.DateField(label="Giriş tarihi", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    check_out = forms.DateField(label="Çıkış tarihi", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    # v82: satış kanalı (komisyon otele kalanı düşürür). Rezervasyon günü formda sorulmaz (v84): her zaman bugün;
    # erken rezervasyon ve son dakika kuralları giriş tarihine kalan güne göre arka planda hesaplanır.
    channel = ChannelChoiceField(
        label="Satış kanalı", queryset=SalesChannel.objects.order_by("commission_rate", "name"), empty_label=None,
        widget=forms.Select(attrs={"class": "select-channel"}))

    def __init__(self, *args, **kwargs):
        today = timezone.localdate()
        direct = (SalesChannel.objects.filter(name__startswith="Web sitesi").first()
                  or SalesChannel.objects.filter(commission_rate=0).order_by("name").first())
        kwargs.setdefault("initial", {
            "guests": 1,
            "check_in": today + timedelta(days=1),
            "check_out": today + timedelta(days=2),
            "channel": direct.pk if direct else None,
        })
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        check_in, check_out = cleaned.get("check_in"), cleaned.get("check_out")
        room_type, guests = cleaned.get("room_type"), cleaned.get("guests")
        today = timezone.localdate()
        cleaned["booked_on"] = today                         # rezervasyon bugün alınıyor
        if check_in and check_in < today:
            self.add_error("check_in", f"Geçmiş bir tarihe rezervasyon yapılamaz (bugün {today:%d.%m.%Y}).")
        if check_in and check_out:
            nights = (check_out - check_in).days
            if nights <= 0:
                self.add_error("check_out", "Çıkış tarihi giriş tarihinden sonra olmalı.")
            elif nights > 180:
                self.add_error("check_out", "Maliyet hesabı en fazla 180 gece için yapılabilir.")
        if room_type and guests and guests > room_type.max_guests:
            self.add_error("guests", f"Bu oda tipi en fazla {room_type.max_guests} misafir alır.")
        elif room_type and guests and not RoomPackageItem.objects.filter(guest_count=guests, active=True).exists():
            self.add_error("guests", "Bu oda tipi ve kişi sayısı için etkin bir oda paketi tanımlanmamış.")
        return cleaned
