from django.contrib import admin
from .models import Category, Equipment, EquipmentStatusLog


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("asset_tag", "name", "category", "department", "status", "criticality", "vendor", "next_pm_date", "is_active")
    list_filter = ("status", "criticality", "category", "department", "vendor", "is_active")
    search_fields = ("asset_tag", "name", "serial_no", "manufacturer", "model_no")
    autocomplete_fields = ("category", "department", "vendor")
    date_hierarchy = "purchase_date"


@admin.register(EquipmentStatusLog)
class EquipmentStatusLogAdmin(admin.ModelAdmin):
    list_display = ("equipment", "old_status", "new_status", "changed_by", "created_at")
    list_filter = ("new_status", "created_at")
    search_fields = ("equipment__asset_tag", "reason")
