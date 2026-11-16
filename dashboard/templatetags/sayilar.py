"""Miktarları Türkçe biçimde ve gereksiz sıfırlar olmadan yazan şablon süzgeçleri.

floatformat 92.1'i "92,100" yazar; Türkçede bu doksan iki bin yüz gibi okunur. Bu süzgeçler 92,1 yazar.
"""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _plain(value):
    try:
        number = Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError, TypeError):
        return None
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@register.filter
def miktar(value):
    """Gösterim için: binlik ayırıcı nokta, ondalık ayırıcı virgül, gereksiz sıfır yok (1.250,5)."""
    text = _plain(value)
    if text is None:
        return value
    whole, _, fraction = text.partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("-")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return sign + ".".join(groups) + ("," + fraction if fraction else "")


@register.filter
def girdi(value):
    """Form kutusu için: binlik ayırıcı yok, ondalık virgül (23,5). Form hem virgülü hem noktayı kabul eder."""
    text = _plain(value)
    return value if text is None else text.replace(".", ",")


@register.filter
def yuzde(value, places=1):
    """0-1 arası oranı yüzde olarak yazar: 0.4554 -> %45,5. Değer yoksa uzun çizgi."""
    if value is None or value == "":
        return "—"
    try:
        text = tl(Decimal(str(value)) * 100, places)
        return "-%" + text[1:] if text.startswith("-") else "%" + text
    except (InvalidOperation, ValueError, TypeError):
        return value


@register.filter
def tl(value, places=0):
    """Tutarı Türkçe biçimde yazar (1.234.567 ya da 4.694,76); değer yoksa uzun çizgi."""
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(str(value)).quantize(Decimal(1).scaleb(-int(places)))
    except (InvalidOperation, ValueError, TypeError):
        return value
    text = miktar(number)
    if int(places) and "," not in text:
        text += "," + "0" * int(places)
    elif int(places):
        whole, fraction = text.split(",")
        text = whole + "," + fraction.ljust(int(places), "0")
    return text[1:] if text.startswith("-") and not text.strip("-0,") else text   # "-0" yazılmasın
