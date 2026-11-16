"""Modüllerin ortak parçaları: doğrulayıcılar, mevsim seçenekleri, endeks yazımı."""
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

ZERO = Decimal("0")

# Ortak doğrulayıcılar: tutar ve miktarlar negatif olamaz, oranlar 0 ile 1 arasındadır.
NON_NEGATIVE = [MinValueValidator(ZERO)]
POSITIVE = [MinValueValidator(Decimal("0.0001"))]
RATE = [MinValueValidator(ZERO), MaxValueValidator(Decimal("0.9999"))]


class Season(models.TextChoices):
    """Üç mevsim. Hangi ayın hangi mevsimde olduğu fiyat kurallarındaki "mevsim ayları" alanındadır (v93)."""
    WINTER = "kis", "Kış"
    TRANSITION = "gecis", "Geçiş"
    SUMMER = "yaz", "Yaz"


def index_label(index):
    """Endeksin fiyata etkisi kısa yazımla: 1,40 -> +%40, 0,95 -> -%5."""
    percent = (index - 1) * 100
    text = f"{abs(percent):f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    text = text.replace(".", ",")
    return f"+%{text}" if percent >= 0 else f"-%{text}"


# v93: mevsim takvimi ayrı tablo değil; fiyat_kurallari.mevsim_aylari alanında 12 kod (Ocak'tan Aralık'a, virgülle).
DEFAULT_SEASON_MONTHS = "kis,kis,kis,gecis,gecis,yaz,yaz,yaz,yaz,gecis,gecis,kis"


def season_map():
    """{ay: mevsim kodu} — fiyat kurallarından (kayıt yoksa varsayılan takvim)."""
    from .satis import PricingRules                       # döngüsel içe aktarmayı önlemek için burada
    raw = PricingRules.objects.values_list("season_months", flat=True).first() or DEFAULT_SEASON_MONTHS
    codes = [code.strip() for code in raw.split(",")]
    return {month: codes[month - 1] for month in range(1, 13)}


def season_of(month):
    return season_map().get(month, "")


def months_of(season):
    return [month for month, code in season_map().items() if code == season]
