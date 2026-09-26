from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "get_full_name", "role", "department", "is_active", "is_staff")
    list_filter = ("role", "department", "is_active", "is_staff")
    search_fields = ("username", "email", "first_name", "last_name", "phone")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Hospital", {"fields": ("role", "phone", "department", "profile_image")}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Hospital", {"fields": ("role", "phone", "department")}),
    )
