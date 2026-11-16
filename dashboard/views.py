from datetime import date, timedelta
from decimal import Decimal

from decimal import InvalidOperation

from django.contrib import messages
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.http import HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import ReservationCostForm
from .models import MonthlyHotelExpense, PurchaseOrder, Room, Stay, Supplier
from .services import (
    auto_close_months, calculate_monthly_room_cost, calculate_stay_quote, cancel_order, create_order, get_stock_summary, last_completed_month,
    average_month_days, calendar_weeks, home_summary, month_occupancy, normal_occupancy_for_month,
    type_normal_occupancy, monthly_overview, overview_totals, occupied_room_ids, order_form_rows, price_calendar,
    receive_order, reservation_overview, stay_price_quote, PRICE_STATUS, room_availability, availability_alternatives, night_sales_summary,
)

# Maliyet verisi işletmenin ticari sırrıdır: tüm ekranlar giriş yapmış kullanıcı ister.


def _close_finished_months(request):
    """Bekleme süresi dolan ayları kapatır ve kullanıcıya bildirir (komut çalıştırmaya gerek kalmaz)."""
    closed = auto_close_months()
    if closed:
        names = ", ".join(f"{period.month:%m.%Y}" for period in closed)
        messages.info(request, f"Biten {'ay' if len(closed) == 1 else 'aylar'} kapatıldı: {names}.")


@login_required
def home(request):
    """Genel özet: maliyet, fiyat ve satış, stok kartları; her kart ilgili ekrana götürür."""
    summary = None
    try:
        _close_finished_months(request)
        summary = home_summary()
    except DatabaseError:
        # Yalnızca veritabanı hazır değilken (migrate çalıştırılmamışken) sessizce geçilir;
        # diğer hatalar gizlenmez.
        pass
    return render(request, "dashboard/home.html", {"summary": summary, "database_ready": summary is not None})


def _plain_cost_rows(summary, normal, type_normals=None):
    """Maliyet analizinin sade tablosu (oda tipi × kişi sayısı).

    Ortak gider payı oda tipinin NORMAL doluluğuna göre verilir (fiyat takvimi, rezervasyon ve Ana Sayfa ile aynı esas;
    TMS 2 md. 13 mantığı): ayın düşük doluluğu oda maliyetini şişirmez, boş odaların bedeli ayrıca raporlanır.
    """
    type_normals = type_normals or {}
    rows, seen = [], set()
    for row in summary["rows"]:
        type_normal = type_normals.get(row["room_type_id"], normal)
        shared = row["semi_fixed"] + row["fixed"]
        if type_normal:
            shared = shared / type_normal
        cost = row["variable"] + shared
        rows.append({"room_type": row["room_type"], "first": row["room_type"] not in seen, "guests": row["guests"],
                     "normal": type_normal,
                     "variable": row["variable"], "shared": shared, "cost": cost,
                     "per_person": cost / Decimal(row["guests"])})
        seen.add(row["room_type"])
    return rows


def _example_room(summary, rows, normal, code=None):
    """Örnek oda kartları: seçilen oda tipinin (varsayılan en ucuz tip) 2 kişilik bir gecesi iki parçaya ayrılır.

    Misafir gelince harcanan (değişken) ve otelin sabit giderlerinden düşen pay. Değişken kısım taban fiyattır
    (altında her satış zarar), toplam başabaştır (üstünde bütün giderler karşılanır).
    """
    candidates = [row for row in summary["rows"] if row["guests"] == 2] or summary["rows"]
    if not candidates:
        return None, []
    source = next((row for row in candidates if row["room_type_code"] == code), candidates[0])
    plain = next(item for item in rows if item["room_type"] == source["room_type"] and item["guests"] == source["guests"])
    cost = plain["cost"]
    items = []
    if source["breakfast"] is not None:          # kapanmış ayda yalnız iki toplam saklanır; kalem kırılımı yok
        items = [{"name": name, "value": value} for name, value in (
            ("Kahvaltı", source["breakfast"]),
            ("Restoranda kullanılan peçete, deterjan…", source["restaurant"]),
            ("Buklet, minibar, oda temizliği", source["amenities"]),
            ("Çarşaf ve havlunun yıpranması", source["textile"]),
            ("Elektrik, su, doğalgaz ve bakım", source["variable_overhead"])) if value]
    example = {"room_type": source["room_type"], "code": source["room_type_code"], "guests": source["guests"],
               "cost": cost, "variable": plain["variable"], "shared": plain["shared"],
               "variable_share": plain["variable"] / cost if cost else None,
               "shared_share": plain["shared"] / cost if cost else None, "items": items}
    example["calc"] = _example_calc(summary, rows, source, normal)
    types = [{"code": row["room_type_code"], "name": row["room_type"]} for row in candidates]
    return example, types


def _example_calc(summary, rows, source, normal):
    """"Nasıl hesaplandı?" bölümlerinin adımları (örnek oda kartlarının altında açılır)."""
    same_type = {item["guests"]: item for item in rows if item["room_type"] == source["room_type"]}
    one = same_type.get(1)
    # Değişken: açık ayda oda / kişi / konaklama başı ayrımı saklıdır; kapanmış ayda yalnız toplam vardır.
    groups = source.get("cost_groups", {})
    by_basis = None
    if "room_night" in groups:
        guests = source["guests"]
        by_basis = {"room": groups["room_night"], "guest_total": groups["guest_night"],
                    "per_guest": groups["guest_night"] / Decimal(guests), "stay": groups["per_stay"]}
    # Sabit: aylık tutar → oda × ortalama ay uzunluğu (yıllık esas) → ortalama oda → oda tipi payı → tipin normal dolulu.
    frozen = summary["frozen"]
    rooms = frozen.available_room_nights // summary["days"] if frozen else summary["active_rooms"]
    month_days = average_month_days(summary["month"].year)
    available = rooms * month_days
    average = summary["shared_total"] / available if available else None
    room_share = source["fixed"] + source["semi_fixed"]
    same = next(item for item in rows if item["room_type"] == source["room_type"] and item["guests"] == source["guests"])
    return {
        "one_guest": one["variable"] if one else None,
        "extra_guest": source["variable"] - one["variable"] if one and source["guests"] == 2 else None,
        "by_basis": by_basis,
        "shared_total": summary["shared_total"], "rooms": rooms, "month_days": month_days,
        "available": available, "average": average, "room_share": room_share,
        "factor": room_share / average if average else None, "normal": same["normal"], "hotel_normal": normal,
    }


@login_required
def cost_report(request):
    _close_finished_months(request)
    # Ay seçilmezse son TAMAMLANMIŞ ay açılır: doluluk ve atıl kapasite ay bitince kesinleşir.
    default_month = last_completed_month().strftime("%Y-%m")
    month_value = request.GET.get("month", default_month)
    try:
        selected = date.fromisoformat(f"{month_value}-01")
    except ValueError:
        month_value = default_month
        selected = date.fromisoformat(f"{month_value}-01")
    summary = calculate_monthly_room_cost(selected.year, selected.month)
    normal, normal_source = normal_occupancy_for_month(selected.year, selected.month)
    month_end = date(selected.year + (selected.month == 12), selected.month % 12 + 1, 1)
    type_normals = type_normal_occupancy(min(month_end, timezone.localdate()))
    simple_rows = _plain_cost_rows(summary, normal, type_normals)
    overview = monthly_overview(selected.year)
    example, example_types = _example_room(summary, simple_rows, normal, request.GET.get("oda"))
    # Ortak gider kartı: oda satılsın satılmasın oluşan aylık tutarın gruplara dağılımı (personel, bina...).
    group_total = sum((group["fixed"] for group in summary["expense_groups"]), Decimal(0))
    shared_groups = sorted(({"name": group["name"], "amount": group["fixed"],
                             "share": group["fixed"] / group_total if group_total else None}
                            for group in summary["expense_groups"] if group["fixed"]),
                           key=lambda group: -group["amount"])
    # Ay sekmeleri: seçilen yılın 12 ayı; durum (kapandı / bitti / devam ediyor / gelecek) ve ayın sonucu.
    today = timezone.localdate()
    by_month = {row["month"]: row for row in overview}
    month_tabs = []
    for number in range(1, 13):
        first = date(selected.year, number, 1)
        row = by_month.get(first)
        state = ("future" if (first.year, first.month) > (today.year, today.month) else
                 "closed" if row and row["closed"] else "complete" if row and row["complete"] else
                 "current" if row else "empty")
        month_tabs.append({"month": first, "value": first.strftime("%Y-%m"), "state": state, "row": row,
                           "selected": first == selected})
    first_expense = MonthlyHotelExpense.objects.order_by("expense_month").values_list("expense_month", flat=True).first()
    first_year = first_expense.year if first_expense else today.year
    years = [{"year": year, "value": (f"{year}-12" if year < today.year else last_completed_month().strftime("%Y-%m")),
              "selected": year == selected.year} for year in range(first_year, today.year + 1)]
    return render(request, "dashboard/cost_report.html", {
        "month_tabs": month_tabs, "years": years, "room_param": request.GET.get("oda", ""),
        "summary": summary, "simple_rows": simple_rows, "example": example, "shared_groups": shared_groups,
        "normal": normal, "normal_source": normal_source, "example_types": example_types,
        "shared_total": summary["shared_total"],
        "month_value": month_value,
        "selected": selected,
        "overview": overview,
        "totals": overview_totals(overview),
        # Satışların toplam gideri karşılaması: seçilen ayın gerçek sonucu (aylık özet tablosundaki satır).
        "month_result": next((row for row in overview if row["month"] == selected), None),
    })


RESERVATION_MONTHS = 4      # Rezervasyonlar ekranı: içinde bulunulan ay + sonraki 3 ay


@login_required
def reservations(request):
    """Rezervasyonlar (v91): önümüzdeki ayların durum özeti + bütün rezervasyonlar yıl › ay olarak.

    Aylar kapalı gelir; bir ay açılınca tablosu ayrı istekle yüklenir (?parca=ay&ay=YYYY-MM), çünkü bütün yılların
    maliyet hesabı tek seferde ~14 sn sürer, bir ay ~1 sn.
    """
    today = timezone.localdate()
    selected_status = request.GET.get("durum", "")
    if request.GET.get("parca") == "ay":
        try:
            month = date.fromisoformat(request.GET.get("ay", "") + "-01")
        except ValueError:
            return HttpResponseBadRequest("ay biçimi: YYYY-MM")
        end = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        rows = reservation_overview(month, end, as_of=today)
        summary = _status_summary(rows)
        shown = [row for row in rows if not selected_status or row["status"] == selected_status]
        return render(request, "dashboard/reservations_month.html", {
            "rows": shown, "total_count": len(rows), "summary": summary, "month": month,
            "selected_status": selected_status})
    first = today.replace(day=1)
    months = []
    for step in range(RESERVATION_MONTHS):
        months.append(date(first.year + (first.month - 1 + step) // 12, (first.month - 1 + step) % 12 + 1, 1))
    end = date(months[-1].year + (months[-1].month == 12), months[-1].month % 12 + 1, 1)
    upcoming = reservation_overview(today, end, as_of=today)
    # Yıl › ay iskeleti: giriş ayına göre onaylı rezervasyon sayısı (hızlı sorgu; maliyet hesabı ay açılınca)
    counts = (Stay.objects.occupying().annotate(m=TruncMonth("check_in")).values("m").annotate(n=Count("id")).order_by("m"))
    years = {}
    for item in counts:
        m = item["m"].date() if hasattr(item["m"], "date") else item["m"]
        years.setdefault(m.year, {"year": m.year, "count": 0, "months": []})
        years[m.year]["count"] += item["n"]
        years[m.year]["months"].append({"month": m, "count": item["n"], "value": m.strftime("%Y-%m"),
                                        "state": "past" if m < first else ("current" if m == first else "future")})
    return render(request, "dashboard/reservations.html", {
        "summary": _status_summary(upcoming), "upcoming_count": len(upcoming), "months": months, "today": today,
        "end": end, "years": sorted(years.values(), key=lambda y: y["year"]), "selected_status": selected_status,
        "statuses": [(key, PRICE_STATUS[key]) for key in ("good", "warning", "serious", "critical")],
    })


def _status_summary(rows):
    summary = []
    for key in ("good", "warning", "serious", "critical"):
        items = [row for row in rows if row["status"] == key]
        label = PRICE_STATUS[key]
        if key == "critical" and any(row.get("deliberate_loss") for row in items):
            label = "Zarar / zararına satış"                  # bilinçli zararına satışlar da kırmızı grupta
        summary.append({"key": key, "label": label, "count": len(items),
                        "revenue": sum((row["total"] for row in items if row["total"] is not None), Decimal(0)),
                        "commission": sum((row["commission"] for row in items if row["commission"] is not None), Decimal(0)),
                        "profit": sum((row["profit"] for row in items if row["profit"] is not None), Decimal(0))})
    return summary


@login_required
def price_calendar_view(request):
    """Fiyat takvimi: her gece için önerilen fiyat, etkinlikler ve fiyatın maliyete göre durumu."""
    _close_finished_months(request)
    today = timezone.localdate()
    try:
        selected = date.fromisoformat(request.GET.get("ay", today.strftime("%Y-%m")) + "-01")
    except ValueError:
        selected = today.replace(day=1)
    try:
        guests = max(1, min(4, int(request.GET.get("kisi", 2))))
    except ValueError:
        guests = 2
    data = price_calendar(selected.year, selected.month, guests=guests)
    code = request.GET.get("oda")
    current = next((item for item in data["types"] if item["room_type"].code == code), None) or (
        data["types"][0] if data["types"] else None)
    previous_month = (selected - timedelta(days=1)).replace(day=1)
    next_month = (selected + timedelta(days=32)).replace(day=1)
    weeks = []
    if current:
        cells = {cell["date"]: cell for cell in current["cells"]}
        weeks = [[cells.get(day) if day else None for day in week] for week in calendar_weeks(data["days"])]
    return render(request, "dashboard/price_calendar.html", {
        "data": data, "current": current, "weeks": weeks, "selected": selected, "guests": guests,
        "guest_choices": range(1, (current["room_type"].max_guests if current else 2) + 1),
        "previous_month": previous_month, "next_month": next_month,
        "weekdays": ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"],
    })


@login_required
def stock_analysis(request):
    summary = get_stock_summary()
    return render(request, "dashboard/stock_analysis.html", {"summary": summary})


@login_required
def reservation_cost(request):
    form = ReservationCostForm(request.GET or None)
    quote = price = availability = alternatives = sales = None
    if form.is_bound and form.is_valid():
        data = form.cleaned_data
        # v82: önce müsaitlik. Oda tipinde boş oda yoksa aynı tarihte boş tipler ve yakın tarihler önerilir.
        availability = room_availability(data["room_type"], data["check_in"], data["check_out"])
        if not availability["available"]:
            alternatives = availability_alternatives(data["room_type"], data["guests"], data["check_in"],
                                                     data["check_out"], booked_on=data["booked_on"],
                                                     channel=data["channel"])
        # v85: bu ekran personel kontrol aracıdır. Oda dolu olsa da fiyat, maliyet ve kâr "bilgi amaçlı" hesaplanır;
        # o gecelerde zaten satılmış odaların satış özeti de gösterilir.
        sales = night_sales_summary(data["room_type"], data["check_in"], data["check_out"])
        quote = calculate_stay_quote(
            room_type=form.cleaned_data["room_type"],
            guests=form.cleaned_data["guests"],
            check_in=form.cleaned_data["check_in"],
            check_out=form.cleaned_data["check_out"],
        )
        price = stay_price_quote(
            room_type=form.cleaned_data["room_type"], guests=form.cleaned_data["guests"],
            check_in=form.cleaned_data["check_in"], check_out=form.cleaned_data["check_out"],
            booked_on=form.cleaned_data.get("booked_on"), channel=form.cleaned_data.get("channel"),
        )
        if price and not price.get("missing_rate"):
            # Maliyet ayrıntısı, tam maliyetle aynı esasta: ortak gider payı normal dolulukla.
            price["shared_cost"] = price["full_cost"] - price["variable_cost"]
    return render(request, "dashboard/reservation_cost.html", {"form": form, "quote": quote, "price": price,
                                                               "availability": availability, "alternatives": alternatives,
                                                               "sales": sales})


@login_required
def order_create(request, supplier_id):
    """Tedarikçiye sipariş: kritik ürünlerde önerilen miktar dolu gelir, kullanıcı değiştirebilir."""
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    focus = request.GET.get("urun")
    groups = order_form_rows(supplier, int(focus) if focus and focus.isdigit() else None)
    rows = groups["main"] + groups["others"]
    errors = []
    if request.method == "POST":
        lines = []
        for row in rows:
            item = row["item"]
            raw_quantity = request.POST.get(f"miktar_{item.pk}", "0").replace(",", ".").strip() or "0"
            raw_price = request.POST.get(f"fiyat_{item.pk}", "0").replace(",", ".").strip() or "0"
            try:
                quantity, price = Decimal(raw_quantity), Decimal(raw_price)
            except InvalidOperation:
                errors.append(f"{item.name}: miktar ve fiyat sayı olmalı.")
                continue
            if quantity < 0 or price < 0:
                errors.append(f"{item.name}: miktar ve fiyat eksi olamaz.")
                continue
            row["suggested"], row["price"] = quantity, price          # hata olursa form girilen değerlerle döner
            lines.append((item, quantity, price))
        if not errors:
            try:
                order = create_order(supplier, lines, notes=request.POST.get("aciklama", "")[:240])
            except ValidationError as exc:
                errors.extend(exc.messages)
            else:
                messages.success(request, f"Sipariş #{order.pk} oluşturuldu ({supplier.name}). "
                                          "Mal geldiğinde Siparişler sayfasından teslim alın.")
                return redirect("order_list")
    return render(request, "dashboard/order_form.html", {"supplier": supplier, "groups": groups, "errors": errors,
                                                         "has_rows": bool(rows)})


@login_required
def order_list(request):
    orders = (PurchaseOrder.objects.select_related("supplier").prefetch_related("lines__item")
              .order_by("status", "-ordered_at")[:100])
    return render(request, "dashboard/orders.html", {"orders": orders, "Status": PurchaseOrder.Status})


@login_required
@require_POST
def order_receive(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    try:
        receive_order(order)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"Sipariş #{order.pk} teslim alındı; ürünler stoğa girdi.")
    return redirect("order_list")


@login_required
@require_POST
def order_cancel(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk)
    try:
        cancel_order(order)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"Sipariş #{order.pk} iptal edildi.")
    return redirect("order_list")
