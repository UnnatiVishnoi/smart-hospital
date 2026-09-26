from django.contrib import admin
from .models import EquipmentManual, ManualChunk


@admin.register(EquipmentManual)
class EquipmentManualAdmin(admin.ModelAdmin):
    list_display = ("title", "manufacturer", "model", "is_indexed", "page_count", "created_at")
    list_filter = ("is_indexed", "manufacturer")
    search_fields = ("title", "manufacturer", "model", "file_hash")


@admin.register(ManualChunk)
class ManualChunkAdmin(admin.ModelAdmin):
    list_display = ("manual", "chunk_index", "page_no", "token_count", "created_at")
    search_fields = ("manual__title", "heading")
