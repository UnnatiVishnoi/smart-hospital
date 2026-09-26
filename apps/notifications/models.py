from django.conf import settings
from django.db import models
from apps.core.models import TimeStampedModel


class NotificationType(models.TextChoices):
    BREAKDOWN = "breakdown", "Breakdown"
    ASSIGNMENT = "assignment", "Assignment"
    PM_DUE = "pm_due", "PM due"
    PM_UPCOMING = "pm_upcoming", "PM upcoming"
    PM_OVERDUE = "pm_overdue", "PM overdue"
    WARRANTY = "warranty", "Warranty expiry"
    RESOLVED = "resolved", "Resolved"
    SYSTEM = "system", "System"


class Notification(TimeStampedModel):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField()
    type = models.CharField(max_length=20, choices=NotificationType.choices, default=NotificationType.SYSTEM, db_index=True)
    service_request = models.ForeignKey(
        "maintenance.ServiceRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications"
    )
    equipment = models.ForeignKey(
        "equipment.Equipment", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications"
    )
    schedule = models.ForeignKey(
        "maintenance.PreventiveSchedule", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="notifications",
    )
    is_read = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read", "created_at"])]

    def __str__(self):
        return f"To {self.recipient_id}: {self.title}"
