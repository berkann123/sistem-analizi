from django.contrib import admin
from django.utils import timezone

from .models import (
    BreakfastBuffetItem, Event, InventoryItem, InventoryMovement, MonthlyExpenseCategory, MonthlyHotelExpense,
    PurchaseOrder, PurchaseOrderLine, PricingRules, Room, RoomPackageItem, RoomType, SalesChannel, Stay, Supplier,
    TaxRate,
)
from .templatetags.sayilar import tl
from .services import BASIS_LABELS, effective_month_expenses, occupied_room_ids

admin.site.site_header = "Pasaport Pier · Maliyet yönetimi"
admin.site.site_title = "Pasaport Pier"
admin.site.index_title = "Admin paneli"


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    """Oda tipleri ve piyasa fiyatları (v93: kış / geçiş / yaz fiyatı oda tipinde, ayrı tablo yok)."""
    list_display = ("code", "name", "max_guests", "standard_cost_factor", "winter_rate", "transition_rate", "summer_rate",
                    "target_markup", "min_markup", "single_discount", "extra_guest_rate", "active")
    list_editable = ("winter_rate", "transition_rate", "summer_rate", "target_markup", "min_markup", "single_discount",
                     "extra_guest_rate")
    search_fields = ("code", "name")
    list_filter = ("active",)


@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    """Vergiler ve hammadde fiyat endeksi (v93). Oran değişince eski satır silinmez; yeni geçerlilik tarihiyle yeni satır
    eklenir (geçmiş hesaplar doğru kalır). Hammadde endeksi: geçerlilik o yılın 1 Ocak'ı, oran o yılın fiyat düzeyi."""
    list_display = ("kind", "valid_from", "rate", "notes")
    list_filter = ("kind",)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    """Etkinlikler ve haftalık kurallar (ör. 'Cuma geceleri +%10': tür 'Her hafta', hafta günü Cuma) aynı listede."""
    list_display = ("name", "kind", "weekday", "start_date", "end_date", "nights", "index", "change", "published", "estimated")
    list_editable = ("index",)
    list_filter = ("kind", "published", "estimated", "start_date")
    search_fields = ("name", "notes")
    date_hierarchy = "start_date"
    fields = ("name", "kind", "weekday", "start_date", "end_date", "estimated", "index", "published", "source", "notes")

    @admin.display(description="Gece")
    def nights(self, obj):
        return (obj.end_date - obj.start_date).days + 1

    @admin.display(description="Fiyata etkisi")
    def change(self, obj):
        percent = obj.percent
        return f"%{tl(percent)} fazla" if percent > 0 else (f"%{tl(-percent)} indirim" if percent < 0 else "etkisiz")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("room_number", "room_type", "view_type", "floor", "status", "occupied_today")
    search_fields = ("room_number",)
    list_filter = ("room_type", "status", "view_type", "floor")
    list_select_related = ("room_type",)

    def get_queryset(self, request):
        # Bugün dolu odalar, liste için tek sorguyla bulunur.
        self._occupied_ids = occupied_room_ids(timezone.localdate())
        return super().get_queryset(request)

    @admin.display(description="Bugün")
    def occupied_today(self, obj):
        """Odada saklanan bir alan değildir; konaklama kayıtlarından hesaplanır."""
        if obj.status != Room.Status.ACTIVE:
            return "Satışa kapalı"
        return "Dolu" if obj.pk in getattr(self, "_occupied_ids", set()) else "Boş"


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "item_count", "active")
    list_filter = ("active",)
    search_fields = ("name", "phone", "email")

    @admin.display(description="Ürün sayısı")
    def item_count(self, obj):
        return obj.items.count()


@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "unit", "average_unit_cost", "current_stock",
                    "reorder_level", "stock_status", "wastage_rate", "textile_life", "supplier", "active")
    search_fields = ("sku", "name")
    list_filter = ("category", "supplier", "active", "is_perishable")
    list_select_related = ("supplier",)
    fieldsets = (
        (None, {"fields": ("sku", "name", "category", "unit", "supplier", "active", "is_perishable")}),
        ("Stok", {"fields": ("current_stock", "average_unit_cost", "reorder_level", "wastage_rate")}),
        ("Tekstil yıpranması (yalnız tekstil ürünlerinde)", {
            "description": "Ömür girilirse ürün tekstil sayılır: tüketilmez, maliyeti ömrüne yayılır.",
            "fields": (("textile_life", "textile_salvage_value", "textile_sets_per_room"),)}),
    )
    autocomplete_fields = ("supplier",)
    # Stok ve maliyet elle yazılmaz; stok hareketlerinden hesaplanır.
    readonly_fields = ("current_stock", "average_unit_cost")

    @admin.display(description="Stok durumu")
    def stock_status(self, obj):
        return "Kritik" if obj.is_critical else "Yeterli"


@admin.register(SalesChannel)
class SalesChannelAdmin(admin.ModelAdmin):
    list_display = ("name", "commission_rate", "notes")
    list_editable = ("commission_rate",)
    search_fields = ("name",)


@admin.register(Stay)
class StayAdmin(admin.ModelAdmin):
    list_display = ("room", "room_type", "check_in", "check_out", "nights", "guests", "status", "channel",
                    "booked_on", "rate", "total", "notes")
    list_filter = ("status", "channel", "room__room_type", "check_in")
    search_fields = ("room__room_number", "notes")
    list_select_related = ("room__room_type", "channel")
    autocomplete_fields = ("room",)
    date_hierarchy = "check_in"
    fieldsets = (
        (None, {"fields": ("room", "check_in", "check_out", "guests")}),
        ("Satış", {"fields": ("status", "channel", "booked_on", "nightly_rate")}),
        (None, {"fields": ("notes",)}),
    )

    @admin.display(description="Gecelik fiyat (TL)", ordering="nightly_rate")
    def rate(self, obj):
        return tl(obj.nightly_rate, 2) if obj.nightly_rate is not None else "—"

    @admin.display(description="Toplam (TL)")
    def total(self, obj):
        return tl(obj.total_price, 2) if obj.total_price is not None else "—"

    @admin.display(description="Oda tipi", ordering="room__room_type__code")
    def room_type(self, obj):
        return obj.room.room_type.name

    @admin.display(description="Gece")
    def nights(self, obj):
        return obj.nights


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ("movement_at", "item_code", "item_name", "category_name", "movement_type",
                    "quantity", "unit_name", "unit_cost", "consumption_day")
    # Tarih süzgeci list_filter ile verilir. date_hierarchy, tarih-saat alanlarında MySQL'in
    # saat dilimi tablolarını ister; WampServer'da bunlar yüklü gelmediği için sayfa hata verir.
    list_filter = ("movement_type", "movement_at", "consumption_day", "item__category")
    search_fields = ("item__name", "item__sku", "notes")
    list_select_related = ("item",)
    autocomplete_fields = ("item",)
    readonly_fields = ("consumption_day", "created_at")
    fields = ("item", "movement_type", "quantity", "unit_cost", "movement_at", "consumption_day", "notes", "created_at")

    # Ürün bilgileri harekete kopyalanmaz; ilişkiden (JOIN ile) okunur.
    @admin.display(description="Ürün kodu", ordering="item__sku")
    def item_code(self, obj):
        return obj.item.sku

    @admin.display(description="Ürün adı", ordering="item__name")
    def item_name(self, obj):
        return obj.item.name

    @admin.display(description="Kategori", ordering="item__category")
    def category_name(self, obj):
        return obj.item.get_category_display()

    @admin.display(description="Birim")
    def unit_name(self, obj):
        return obj.item.get_unit_display()


@admin.register(BreakfastBuffetItem)
class BreakfastBuffetItemAdmin(admin.ModelAdmin):
    """Kahvaltı büfesi: her satır bir ürünün kişi başı miktarı. Kişi başı kahvaltı maliyeti satırların toplamıdır."""
    list_display = ("item", "kind", "unit_name", "quantity", "waste_rate", "unit_cost", "line_cost",
                    "current_stock", "stock_status", "active")
    list_editable = ("quantity", "waste_rate", "active")
    list_filter = ("active", "item__category")
    search_fields = ("item__name", "item__sku")
    autocomplete_fields = ("item",)
    fields = ("item", "quantity", "waste_rate", "active", "notes")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("item")

    @admin.display(description="Tür")
    def kind(self, obj):
        """Gıda mı restoran sarfı mı: ürünün kategorisinden gelir (kategori mutfak/bar ise gıda)."""
        return obj.kind_label if obj.item_id else "—"

    @admin.display(description="Birim")
    def unit_name(self, obj):
        return obj.item.get_unit_display() if obj.item_id else "—"

    @admin.display(description="Mevcut stok")
    def current_stock(self, obj):
        return obj.item.current_stock if obj.item_id else "—"

    @admin.display(description="Stok durumu")
    def stock_status(self, obj):
        if not obj.item_id:
            return "—"
        return "Kritik" if obj.item.is_critical else "Yeterli"

    @admin.display(description="Ortalama birim maliyeti")
    def unit_cost(self, obj):
        return obj.item.average_unit_cost if obj.item_id else "—"

    @admin.display(description="Kişi başı maliyet (TL)")
    def line_cost(self, obj):
        return tl(obj.line_cost, 2) if obj.item_id and obj.quantity is not None else "—"


@admin.register(RoomPackageItem)
class RoomPackageItemAdmin(admin.ModelAdmin):
    """Oda paketi: misafir sayısına göre bir oda-gecede kullanılan ürünler ve tekstiller (bütün oda tiplerinde aynı).
    Tekstil ürününün yıpranma bilgileri envanter kartındadır (v93)."""
    list_display = ("guest_count", "source", "quantity", "basis", "waste_rate", "line_cost", "active")
    list_editable = ("quantity", "active")
    list_filter = ("guest_count", "basis", "active")
    search_fields = ("item__name",)
    list_select_related = ("item",)
    autocomplete_fields = ("item",)
    fields = ("guest_count", "item", "quantity", "basis", "waste_rate", "active", "notes")

    @admin.display(description="Ürün / tekstil")
    def source(self, obj):
        return f"{obj.item.name} (tekstil)" if obj.item.is_textile else obj.item.name

    @admin.display(description="Birim maliyet (TL)")
    def line_cost(self, obj):
        return tl(obj.line_cost, 2)

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "basis":
            kwargs["choices"] = [(k, v) for k, v in db_field.choices if k != "kahvalti"]
        return super().formfield_for_choice_field(db_field, request, **kwargs)


@admin.register(MonthlyExpenseCategory)
class MonthlyExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "group", "cost_behavior", "variable_basis", "active")
    list_filter = ("group", "cost_behavior", "active")
    search_fields = ("name",)
    fields = ("name", "group", "cost_behavior", "variable_basis", "notes", "active")


@admin.register(MonthlyHotelExpense)
class MonthlyHotelExpenseAdmin(admin.ModelAdmin):
    list_display = ("category", "group", "behavior", "season", "expense_month", "amount", "variable", "recurs_monthly",
                    "recurring_until", "in_effect", "description")
    fields = ("category", "season", "expense_month", "amount", "variable_rate", "recurs_monthly", "recurring_until",
              "description")
    list_filter = ("category__group", "category__cost_behavior", "season", "category")
    list_select_related = ("category",)
    date_hierarchy = "expense_month"

    def get_queryset(self, request):
        # İçinde bulunulan ayda hangi kayıtların geçerli olduğu, liste için bir kez hesaplanır.
        today = timezone.localdate()
        self._in_effect_ids = {expense.pk for expense in effective_month_expenses(today.year, today.month)}
        return super().get_queryset(request)

    @admin.display(description="Bu ay geçerli", boolean=True)
    def in_effect(self, obj):
        """Bir kalemin birden çok kaydı varsa (tutar geçmişi) hesaba giren yalnızca işaretli olandır."""
        return obj.pk in getattr(self, "_in_effect_ids", set())

    @admin.display(description="Grup", ordering="category__group")
    def group(self, obj):
        return obj.category.get_group_display()

    @admin.display(description="Maliyet davranışı", ordering="category__cost_behavior")
    def behavior(self, obj):
        return obj.category.get_cost_behavior_display().split(" (")[0]

    @admin.display(description="Değişken birim tutar", ordering="variable_rate")
    def variable(self, obj):
        if not obj.variable_rate:
            return "—"
        return f"{obj.variable_rate} TL / {BASIS_LABELS[obj.category.variable_basis]}"


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    autocomplete_fields = ("item",)
    fields = ("item", "quantity", "unit_price", "line_total")
    readonly_fields = ("line_total",)

    @admin.display(description="Tutar (TL)")
    def line_total(self, obj):
        return tl(obj.total, 2) if obj.pk else "—"


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    """Siparişler normalde Stok analizi sayfasından verilir ve Siparişler sayfasından teslim alınır.

    Teslim alma stok hareketi ürettiği için burada durum elle 'teslim alındı' yapılmaz (salt okunur).
    """
    list_display = ("id", "supplier", "ordered_at", "status", "delivered_at", "order_total")
    list_filter = ("status", "supplier")
    list_select_related = ("supplier",)
    readonly_fields = ("status", "delivered_at")
    fields = ("supplier", "ordered_at", "status", "delivered_at", "notes")
    inlines = [PurchaseOrderLineInline]

    @admin.display(description="Toplam (TL, KDV hariç)")
    def order_total(self, obj):
        return tl(obj.total, 2)


@admin.register(PricingRules)
class PricingRulesAdmin(admin.ModelAdmin):
    """Tek satırlık ayar: listeye değil doğrudan düzenleme sayfasına gider; eklenemez, silinemez."""
    fieldsets = (
        ("Doluluğa göre fiyat (anlık doluluk: o gece için satılmış oda ÷ aktif oda)", {
            "description": "Çarpan 1'e göre yazılır: 0,95 = %5 indirim, 1,15 = %15 artış. Sınırlar 0–1 arası: 0,50 = %50.",
            "fields": (("low_limit", "low_factor"), ("mid_limit", "mid_factor"), ("high_limit", "high_factor"),
                       "full_factor"),
        }),
        ("Mevsim ayları", {
            "description": "Ocak'tan Aralık'a 12 ayın mevsimi, virgülle: kis, gecis ya da yaz.",
            "fields": ("season_months",)}),
        ("Erken rezervasyon", {"fields": (("early_days", "early_discount"),)}),
        ("Konaklama süresi indirimi (en uzun uyan uygulanır)", {
            "description": "İndirim 0–1 arası yazılır: 0,05 = %5. Erken rezervasyon indirimiyle sırayla uygulanır (çarpılır).",
            "fields": (("stay_1_nights", "stay_1_discount"), ("stay_2_nights", "stay_2_discount"),
                       ("stay_3_nights", "stay_3_discount")),
        }),
        ("Alt sınır: fiyat motorunun inebileceği en düşük fiyat", {
            "description": "Normal günlerde fiyat tam maliyetin altına inmez. Son dakikada (aşağıdaki gün ve doluluk "
                           "koşulunda) boş kalacak oda için değişken maliyet × (1 + pay) seviyesine kadar inebilir.",
            "fields": (("last_minute_days", "last_minute_occupancy"), ("last_minute_discount", "last_minute_markup")),
        }),
        ("Kayıt", {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not PricingRules.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.shortcuts import redirect
        return redirect("admin:dashboard_pricingrules_change", PricingRules.current().pk)
