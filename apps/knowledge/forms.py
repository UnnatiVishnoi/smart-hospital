import hashlib

from django import forms
from .models import EquipmentManual

CTRL = {"class": "form-control"}
SEL = {"class": "form-select"}


class ManualUploadForm(forms.ModelForm):
    class Meta:
        model = EquipmentManual
        fields = ("title", "equipment", "category", "manufacturer", "model", "version", "file")
        widgets = {
            "title": forms.TextInput(attrs={**CTRL, "placeholder": "Ventilator service manual"}),
            "equipment": forms.Select(attrs=SEL),
            "category": forms.Select(attrs=SEL),
            "manufacturer": forms.TextInput(attrs=CTRL),
            "model": forms.TextInput(attrs=CTRL),
            "version": forms.TextInput(attrs=CTRL),
            "file": forms.ClearableFileInput(attrs=CTRL),
        }

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if not f:
            raise forms.ValidationError("A PDF file is required.")
        if f.size > 20 * 1024 * 1024:
            raise forms.ValidationError("PDF must be under 20 MB.")
        head = f.read(5)
        f.seek(0)
        if head != b"%PDF-":
            raise forms.ValidationError("File is not a valid PDF (bad header).")
        digest = hashlib.sha256()
        for chunk in f.chunks():
            digest.update(chunk)
        f.seek(0)
        file_hash = digest.hexdigest()
        qs = EquipmentManual.objects.filter(file_hash=file_hash)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This exact document was already uploaded.")
        self.cleaned_data["_file_hash"] = file_hash
        return f
