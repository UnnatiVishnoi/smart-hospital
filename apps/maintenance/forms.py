from django import forms
from django.utils import timezone
from apps.inventory.models import SparePart
from .models import Priority, ServiceRequest

CTRL = {"class": "form-control"}
SEL = {"class": "form-select"}


class ServiceRequestForm(forms.ModelForm):
    class Meta:
        model = ServiceRequest
        fields = ("equipment", "priority", "issue_type", "description", "attachment")
        widgets = {
            "equipment": forms.Select(attrs=SEL),
            "priority": forms.Select(attrs=SEL),
            "issue_type": forms.TextInput(attrs={**CTRL, "placeholder": "e.g. No cooling, error E4, power trip"}),
            "description": forms.Textarea(attrs={**CTRL, "rows": 4, "placeholder": "What failed, when, error codes, impact on patients…"}),
            "attachment": forms.ClearableFileInput(attrs=CTRL),
        }

    def clean_description(self):
        d = (self.cleaned_data.get("description") or "").strip()
        if len(d) < 20:
            raise forms.ValidationError("Describe the fault in at least 20 characters.")
        return d

    def clean_attachment(self):
        f = self.cleaned_data.get("attachment")
        if f and hasattr(f, "size"):
            if f.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Supporting image must be under 5 MB.")
            ext = (f.name.rsplit(".", 1)[-1] or "").lower()
            if ext not in ("jpg", "jpeg", "png", "webp"):
                raise forms.ValidationError("Attachment must be JPG, PNG or WEBP.")
        return f


class AssignForm(forms.Form):
    assigned_to = forms.ChoiceField(widget=forms.Select(attrs=SEL), label="Technician *")
    deadline = forms.DateTimeField(
        required=False, widget=forms.DateTimeInput(attrs={**CTRL, "type": "datetime-local"}),
        help_text="Target resolution time.",
    )
    internal_remarks = forms.CharField(required=False, widget=forms.Textarea(attrs={**CTRL, "rows": 2}))

    def __init__(self, *args, **kwargs):
        techs = kwargs.pop("technicians")
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].choices = [("", "— Select —")] + [
            (str(t.pk), f"{t.get_full_name() or t.username} ({t.username})") for t in techs
        ]

    def clean_deadline(self):
        dl = self.cleaned_data.get("deadline")
        if dl and timezone.is_naive(dl):
            dl = timezone.make_aware(dl, timezone.get_current_timezone())
        if dl and dl <= timezone.now():
            raise forms.ValidationError("Deadline must be in the future.")
        self.cleaned_data["deadline"] = dl
        return dl


class ProgressNoteForm(forms.Form):
    note = forms.CharField(
        widget=forms.Textarea(attrs={**CTRL, "rows": 3, "placeholder": "Inspection update, findings, ETA…"}),
        min_length=5, label="Progress note *",
    )


class ResolveReportForm(forms.Form):
    inspection_findings = forms.CharField(
        widget=forms.Textarea(attrs={**CTRL, "rows": 3}), min_length=10, label="Inspection findings *")
    work_done = forms.CharField(
        widget=forms.Textarea(attrs={**CTRL, "rows": 3}), min_length=10, label="Repair actions *")
    cost = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, initial=0, widget=forms.NumberInput(attrs=CTRL))
    downtime_hours = forms.DecimalField(
        min_value=0, max_digits=10, decimal_places=2, required=False, widget=forms.NumberInput(attrs=CTRL))
    next_action = forms.CharField(required=False, widget=forms.Textarea(attrs={**CTRL, "rows": 2}))
    part_1 = forms.ModelChoiceField(queryset=SparePart.objects.none(), required=False, widget=forms.Select(attrs=SEL))
    qty_1 = forms.IntegerField(min_value=1, required=False, initial=1, widget=forms.NumberInput(attrs=CTRL))
    part_2 = forms.ModelChoiceField(queryset=SparePart.objects.none(), required=False, widget=forms.Select(attrs=SEL))
    qty_2 = forms.IntegerField(min_value=1, required=False, initial=1, widget=forms.NumberInput(attrs=CTRL))
    part_3 = forms.ModelChoiceField(queryset=SparePart.objects.none(), required=False, widget=forms.Select(attrs=SEL))
    qty_3 = forms.IntegerField(min_value=1, required=False, initial=1, widget=forms.NumberInput(attrs=CTRL))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parts = SparePart.objects.filter(is_active=True).order_by("part_no")
        for i in (1, 2, 3):
            self.fields[f"part_{i}"].queryset = parts
            self.fields[f"part_{i}"].label = f"Part {i}"
            self.fields[f"qty_{i}"].label = f"Qty {i}"

    def clean(self):
        data = super().clean()
        for i in (1, 2, 3):
            part, qty = data.get(f"part_{i}"), data.get(f"qty_{i}")
            if part and not qty:
                self.add_error(f"qty_{i}", "Quantity required when a part is selected.")
            if qty and not part:
                self.add_error(f"part_{i}", "Select a part for this quantity.")
            if part and qty and part.quantity_in_stock < qty:
                self.add_error(f"qty_{i}", f"Only {part.quantity_in_stock} in stock.")
        seen = [str(data.get(f"part_{i}").pk) for i in (1, 2, 3) if data.get(f"part_{i}")]
        if len(seen) != len(set(seen)):
            raise forms.ValidationError("Each part may be listed only once.")
        return data

    def part_lines(self):
        lines = []
        for i in (1, 2, 3):
            part = self.cleaned_data.get(f"part_{i}")
            qty = self.cleaned_data.get(f"qty_{i}")
            if part and qty:
                lines.append((part, qty))
        return lines


class CloseForm(forms.Form):
    satisfaction_rating = forms.IntegerField(min_value=1, max_value=5, required=False,
        widget=forms.NumberInput(attrs={**CTRL, "placeholder": "1–5 (optional)"}))
