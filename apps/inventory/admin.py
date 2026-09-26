from django.contrib import admin
from .models import PartUsage, SparePart, Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_person", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_person", "email")


@admin.register(SparePart)
class SparePartAdmin(admin.ModelAdmin):
    list_display = ("part_no", "name", "quantity_in_stock", "reorder_level", "unit_price", "vendor", "is_active")
    list_filter = ("is_active", "vendor")
    search_fields = ("part_no", "name")
    filter_horizontal = ("compatible_categories",)


@admin.register(PartUsage)
class PartUsageAdmin(admin.ModelAdmin):
    list_display = ("maintenance_record", "spare_part", "quantity", "unit_cost_at_use", "created_at")
    search_fields = ("spare_part__part_no", "spare_part__name")
