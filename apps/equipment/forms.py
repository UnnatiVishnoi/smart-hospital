from datetime import date

from django import forms
from django.core.exceptions import ValidationError
from .models import Equipment

CTRL = {"class": "form-control"}
SEL = {"class": "form-select"}

CATEGORY_PREFIX = {
    "ventilator": "VEN",
    "patient monitor": "PM",
    "infusion pump": "IP",
    "defibrillator": "DF",
    "x-ray": "XR",
    "xray": "XR",
    "ecg": "ECG",
    "ultrasound": "US",
    "autoclave": "AC",
}


def suggest_asset_tag(category_name, dept_code, exclude_pk=None):
    prefix = CATEGORY_PREFIX.get((category_name or "").strip().lower(), None)
    if not prefix:
        clean = "".join(ch for ch in (category_name or "GEN") if ch.isalnum()).upper()[:3] or "GEN"
        prefix = clean.ljust(3, "X")
    base = f"{prefix}-{dept_code or 'GEN'}"
    n = 1
    existing = set(
        Equipment.objects.filter(asset_tag__startswith=base + "-").values_list("asset_tag", flat=True)
    )
    if exclude_pk:
        existing = {t for t in existing}  # exclude handled by sequence scan anyway
    while f"{base}-{n:03d}" in existing:
        n += 1
    return f"{base}-{n:03d}"


class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = (
            "asset_tag", "name", "category", "department", "manufacturer", "model_no", "serial_no",
            "vendor", "purchase_date", "installation_date", "warranty_expiry",
            "location_detail", "criticality", "status",
            "last_service_date", "next_pm_date", "image", "notes",
        )
        widgets = {
            "asset_tag": forms.TextInput(attrs={**CTRL, "placeholder": "VEN-ICU-001"}),
            "name": forms.TextInput(attrs={**CTRL, "placeholder": "ICU Ventilator — Bed 4"}),
            "category": forms.Select(attrs=SEL),
            "department": forms.Select(attrs=SEL),
            "manufacturer": forms.TextInput(attrs={**CTRL, "placeholder": "Philips Healthcare"}),
            "model_no": forms.TextInput(attrs=CTRL),
            "serial_no": forms.TextInput(attrs=CTRL),
            "vendor": forms.Select(attrs=SEL),
            "purchase_date": forms.DateInput(attrs={**CTRL, "type": "date"}),
            "installation_date": forms.DateInput(attrs={**CTRL, "type": "date"}),
            "warranty_expiry": forms.DateInput(attrs={**CTRL, "type": "date"}),
            "location_detail": forms.TextInput(attrs={**CTRL, "placeholder": "ICU · Room 2 · Bed 4"}),
            "criticality": forms.Select(attrs=SEL),
            "status": forms.Select(attrs=SEL),
            "last_service_date": forms.DateInput(attrs={**CTRL, "type": "date"}),
            "next_pm_date": forms.DateInput(attrs={**CTRL, "type": "date"}),
            "image": forms.ClearableFileInput(attrs=CTRL),
            "notes": forms.Textarea(attrs={**CTRL, "rows": 3, "placeholder": "Service notes, accessories, cautions…"}),
        }

    def clean_asset_tag(self):
        tag = (self.cleaned_data.get("asset_tag") or "").strip().upper()
        if not tag:
            raise ValidationError("Asset ID is required.")
        qs = Equipment.objects.filter(asset_tag__iexact=tag)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("This asset ID already exists. Use Suggest next ID.")
        return tag

    def clean_serial_no(self):
        serial = (self.cleaned_data.get("serial_no") or "").strip()
        if not serial:
            raise ValidationError("Serial number is required.")
        qs = Equipment.objects.filter(serial_no__iexact=serial)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("This serial number is already registered.")
        return serial

    def clean_image(self):
        img = self.cleaned_data.get("image")
        if img and hasattr(img, "size"):
            if img.size > 5 * 1024 * 1024:
                raise ValidationError("Image must be under 5 MB.")
            ext = (img.name.rsplit(".", 1)[-1] or "").lower()
            if ext not in ("jpg", "jpeg", "png", "webp"):
                raise ValidationError("Image must be JPG, PNG or WEBP.")
        return img

    def clean(self):
        data = super().clean()
        today = date.today()
        purchase = data.get("purchase_date")
        install = data.get("installation_date")
        warranty = data.get("warranty_expiry")
        last_svc = data.get("last_service_date")
        next_pm = data.get("next_pm_date")
        if purchase and purchase > today:
            self.add_error("purchase_date", "Purchase date cannot be in the future.")
        if purchase and install and install < purchase:
            self.add_error("installation_date", "Installation cannot precede purchase.")
        if purchase and warranty and warranty <= purchase:
            self.add_error("warranty_expiry", "Warranty expiry must be after purchase date.")
        if last_svc and next_pm and next_pm < last_svc:
            self.add_error("next_pm_date", "Next maintenance cannot precede last maintenance.")
        return data
