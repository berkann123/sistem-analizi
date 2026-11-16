from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from dashboard.views import (
    cost_report, home, order_cancel, order_create, order_list, order_receive, price_calendar_view, reservation_cost,
    reservations, stock_analysis,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("giris/", auth_views.LoginView.as_view(), name="login"),
    path("cikis/", auth_views.LogoutView.as_view(), name="logout"),
    path("", home, name="home"),
    path("maliyet/", cost_report, name="cost_report"),
    path("rezervasyonlar/", reservations, name="reservations"),
    path("fiyat-takvimi/", price_calendar_view, name="price_calendar"),
    path("rezervasyon-maliyeti/", reservation_cost, name="reservation_cost"),
    path("stok/", stock_analysis, name="stock_analysis"),
    path("stok/siparis/<int:supplier_id>/", order_create, name="order_create"),
    path("stok/siparisler/", order_list, name="order_list"),
    path("stok/siparisler/<int:pk>/teslim/", order_receive, name="order_receive"),
    path("stok/siparisler/<int:pk>/iptal/", order_cancel, name="order_cancel"),
]
