from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def inr(value):
    """1234567.5 -> ₹12,34,567.50 (Indian digit grouping, decimals only when needed)."""
    try:
        v = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if v < 0 else ""
    whole, frac = str(abs(v).quantize(Decimal("0.01"))).split(".")
    if len(whole) > 3:
        head, tail, groups = whole[:-3], whole[-3:], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}" + ("" if frac == "00" else f".{frac}")


@register.filter
def pct(value):
    try:
        return f"{float(value):.0f}%"
    except (TypeError, ValueError):
        return "–"
