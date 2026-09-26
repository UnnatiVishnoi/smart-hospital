from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from .models import RoleChoices, User

INPUT = {"class": "form-control"}


class StyledLoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={**INPUT, "placeholder": "username or email", "autocomplete": "username"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={**INPUT, "placeholder": "Password", "autocomplete": "current-password"}))

    def confirm_login_allowed(self, user):
        if not user.is_active:
            raise forms.ValidationError("This account is deactivated. Contact your administrator.", code="inactive")
        super().confirm_login_allowed(user)


class AdminUserCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "role", "department", "phone", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("username", "email", "first_name", "last_name", "phone", "password1", "password2"):
            if name in self.fields:
                self.fields[name].widget.attrs.update(INPUT)
        self.fields["role"].widget.attrs.update({"class": "form-select"})
        self.fields["department"].widget.attrs.update({"class": "form-select"})
        if "is_active" in self.fields:
            self.fields["is_active"].widget.attrs.update({"class": "form-check-input"})
        self.fields["email"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email


class AdminUserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "role", "department", "phone", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email", "phone"):
            self.fields[name].widget.attrs.update(INPUT)
        self.fields["role"].widget.attrs.update({"class": "form-select"})
        self.fields["department"].widget.attrs.update({"class": "form-select"})
        self.fields["is_active"].widget.attrs.update({"class": "form-check-input"})

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone", "profile_image")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email", "phone"):
            self.fields[name].widget.attrs.update(INPUT)
        self.fields["profile_image"].widget.attrs.update({"class": "form-control"})


class StyledPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update(INPUT)


class SelfRegisterForm(UserCreationForm):
    """Public self-registration. Admin role excluded — must be granted by an existing admin."""

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "role", "department", "phone")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only non-admin roles can self-register
        self.fields["role"].choices = [
            (RoleChoices.STAFF, "Hospital Staff"),
            (RoleChoices.TECHNICIAN, "Biomedical Technician"),
            (RoleChoices.MANAGER, "Maintenance Manager"),
        ]
        self.fields["role"].initial = RoleChoices.STAFF
        for name in ("username", "email", "first_name", "last_name", "phone", "password1", "password2"):
            if name in self.fields:
                self.fields[name].widget.attrs.update(INPUT)
        self.fields["role"].widget.attrs.update({"class": "form-select"})
        self.fields["department"].widget.attrs.update({"class": "form-select"})
        self.fields["department"].required = False
        self.fields["email"].required = True
        self.fields["first_name"].required = True

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if role == RoleChoices.ADMIN:
            raise forms.ValidationError("Administrator access must be granted by an existing admin.")
        if role not in (RoleChoices.STAFF, RoleChoices.TECHNICIAN, RoleChoices.MANAGER):
            raise forms.ValidationError("Invalid role selected.")
        return role

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user
