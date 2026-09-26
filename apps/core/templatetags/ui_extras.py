"""Presentation helpers — text shaping only, no business logic."""
import builtins as _builtins
from django import template

register = template.Library()

builtins_abs = _builtins.abs

_ACRONYMS = {"ecg": "ECG", "pm": "PM", "icu": "ICU", "er": "ER", "ot": "OT",
             "id": "ID", "qr": "QR", "amc": "AMC", "x-ray": "X-ray"}


@register.filter
def status_label(value):
    """Humanize machine statuses: 'under_maintenance' -> 'Under maintenance'."""
    out = []
    for tok in str(value or "").replace("_", " ").split():
        out.append(_ACRONYMS.get(tok.lower(), tok.title()))
    return " ".join(out)


@register.filter
def abs(value):
    """Absolute value: {{ -5|abs }} -> 5. Returns value unchanged on error."""
    try:
        return builtins_abs(value)
    except Exception:
        try:
            return builtins_abs(float(value))
        except Exception:
            return value
