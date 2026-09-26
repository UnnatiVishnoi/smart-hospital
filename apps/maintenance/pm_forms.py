from datetime import date, timedelta

from django import forms
from .models import PreventiveSchedule

CTRL = {"class": "form-control"}
SEL = {"class": "form-select"}

FREQ_DAYS = {
    "daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90,
    "half_yearly": 182, "yearly": 365,
}


def parse_checklist(text):
    """One step per line. Prefix a line with '[optional]' to mark it non-required."""
    items = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("[optional]"):
            title = line[len("[optional]"):].strip()
            required = False
        else:
            title, required = line, True
        if title:
            items.append({"title": title[:200], "required": required})
    return items[:30]


def checklist_to_text(items):
    lines = []
    for it in items or []:
        prefix = "" if it.get("required", True) else "[optional] "
        lines.append(prefix + it.get("title", ""))
    return "\n".join(lines)


class ScheduleForm(forms.ModelForm):
    checklist_text = forms.CharField(
        required=False, widget=forms.Textarea(attrs={**CTRL, "rows": 4,
            "placeholder": "One step per line, e.g.\nCheck oil level\nCalibrate pressure sensor\n[optional] Clean exterior"}),
        label="Inspection checklist", help_text="One step per line. Prefix with [optional] for non-required steps.",
    )

    class Meta:
        model = PreventiveSchedule
        fields = ("equipment", "title", "maintenance_type", "schedule_type", "frequency",
                  "interval_days", "next_due_date", "assigned_to", "priority", "notes")
        widgets = {
            "equipment": forms.Select(attrs=SEL),
            "title": forms.TextInput(attrs={**CTRL, "placeholder": "Quarterly calibration"}),
            "maintenance_type": forms.Select(attrs=SEL),
            "schedule_type": forms.Select(attrs=SEL),
            "frequency": forms.Select(attrs=SEL),
            "interval_days": forms.NumberInput(attrs={**CTRL, "min": 1}),
            "next_due_date": forms.DateInput(attrs={**CTRL, "type": "date"}),
            "assigned_to": forms.Select(attrs=SEL),
            "priority": forms.Select(attrs=SEL),
            "notes": forms.Textarea(attrs={**CTRL, "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.checklist:
            self.fields["checklist_text"].initial = checklist_to_text(self.instance.checklist)
        tech_qs = self.fields["assigned_to"].queryset
        self.fields["assigned_to"].queryset = tech_qs.filter(role="technician", is_active=True).order_by("username")

    def clean(self):
        data = super().clean()
        freq, interval = data.get("frequency"), data.get("interval_days")
        if freq != "custom":
            expected = FREQ_DAYS.get(freq)
            if expected and interval != expected:
                data["interval_days"] = expected
        elif not interval or interval < 1:
            self.add_error("interval_days", "Custom frequency needs an interval of at least 1 day.")
        due = data.get("next_due_date")
        if due and due < date.today() - timedelta(days=365 * 5):
            self.add_error("next_due_date", "Due date looks wrong — more than 5 years in the past.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.checklist = parse_checklist(self.cleaned_data.get("checklist_text", ""))
        if commit:
            obj.save()
        return obj


class CompleteForm(forms.Form):
    completion_date = forms.DateField(
        widget=forms.DateInput(attrs={**CTRL, "type": "date"}), label="Completion date *")
    inspection_findings = forms.CharField(
        widget=forms.Textarea(attrs={**CTRL, "rows": 3}), min_length=10, label="Findings *")
    work_done = forms.CharField(
        widget=forms.Textarea(attrs={**CTRL, "rows": 3}), min_length=10, label="Work performed *")
    cost = forms.DecimalField(min_value=0, max_digits=10, decimal_places=2, initial=0,
                              widget=forms.NumberInput(attrs=CTRL))

    def __init__(self, *args, **kwargs):
        self.checklist = kwargs.pop("checklist", [])
        super().__init__(*args, **kwargs)
        self.fields["completion_date"].initial = date.today()
        for i, item in enumerate(self.checklist):
            self.fields[f"step_{i}"] = forms.BooleanField(
                required=item.get("required", True), label=item.get("title", f"Step {i+1}"))

    def clean_completion_date(self):
        d = self.cleaned_data["completion_date"]
        if d > date.today():
            raise forms.ValidationError("Completion date cannot be in the future.")
        if d < date.today() - timedelta(days=365 * 2):
            raise forms.ValidationError("Completion date is unrealistically old.")
        return d

    def checklist_results(self):
        return [{"title": it.get("title", ""), "done": bool(self.cleaned_data.get(f"step_{i}"))}
                for i, it in enumerate(self.checklist)]
