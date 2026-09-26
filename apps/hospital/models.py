from django.db import models
from apps.core.models import TimeStampedModel


class Department(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True, help_text="Short code, e.g. ICU, RAD, ER.")
    location = models.CharField(max_length=150, blank=True, help_text="Floor / building.")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active", "name"])]

    def __str__(self):
        return f"{self.name} ({self.code})"
