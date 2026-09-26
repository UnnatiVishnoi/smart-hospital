from django.conf import settings
from django.db import models
from apps.core.models import TimeStampedModel


class EquipmentManual(TimeStampedModel):
    equipment = models.ForeignKey(
        "equipment.Equipment", on_delete=models.SET_NULL, null=True, blank=True, related_name="manuals"
    )
    category = models.ForeignKey(
        "equipment.Category", on_delete=models.SET_NULL, null=True, blank=True, related_name="manuals"
    )
    title = models.CharField(max_length=200)
    manufacturer = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    version = models.CharField(max_length=50, blank=True)
    file = models.FileField(upload_to="manuals/%Y/")
    file_hash = models.CharField(max_length=64, unique=True, help_text="SHA256 for dedup.")
    page_count = models.PositiveIntegerField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="uploaded_manuals"
    )
    is_indexed = models.BooleanField(default=False, db_index=True)
    indexed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["category", "is_indexed"])]

    def __str__(self):
        return self.title


class ManualChunk(models.Model):
    manual = models.ForeignKey(EquipmentManual, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField()
    page_no = models.PositiveIntegerField(null=True, blank=True)
    heading = models.CharField(max_length=255, blank=True)
    content = models.TextField(help_text="~800-1000 tokens with overlap.")
    token_count = models.PositiveIntegerField(default=0)
    embedding = models.JSONField(null=True, blank=True)
    embedding_model = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["manual", "chunk_index"]
        constraints = [
            models.UniqueConstraint(fields=["manual", "chunk_index"], name="uniq_chunk_manual_index"),
        ]
        indexes = [models.Index(fields=["manual", "chunk_index"])]

    def __str__(self):
        return f"Manual {self.manual_id} chunk {self.chunk_index}"
