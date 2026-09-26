from django.contrib import admin
from .models import MaintenanceRecord, PreventiveSchedule, ServiceActivity, ServiceRequest


@admin.register(PreventiveSchedule)
class PreventiveScheduleAdmin(admin.ModelAdmin):
    list_display = ("equipment", "title", "maintenance_type", "schedule_type", "frequency", "next_due_date", "assigned_to", "priority", "is_active")
    list_filter = ("maintenance_type", "schedule_type", "frequency", "priority", "is_active")
    search_fields = ("title", "equipment__asset_tag", "equipment__name")
    autocomplete_fields = ("equipment", "assigned_to")
    date_hierarchy = "next_due_date"


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("ticket_no", "equipment", "priority", "status", "requested_by", "assigned_to", "deadline", "requested_at")
    list_filter = ("status", "priority", "requested_at")
    search_fields = ("ticket_no", "equipment__asset_tag", "equipment__name", "description")
    autocomplete_fields = ("equipment",)
    date_hierarchy = "requested_at"


@admin.register(ServiceActivity)
class ServiceActivityAdmin(admin.ModelAdmin):
    list_display = ("service_request", "action", "actor", "old_status", "new_status", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("service_request__ticket_no", "note")


@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "equipment", "maintenance_type", "technician", "started_at", "completed_at", "cost")
    list_filter = ("maintenance_type", "completed_at")
    search_fields = ("equipment__asset_tag", "work_done")
    autocomplete_fields = ("equipment", "service_request", "schedule")
