from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from apps.core.models import TimeStampedModel


class Frequency(models.TextChoices):
    DAILY = "daily", "Daily"
    WEEKLY = "weekly", "Weekly"
    MONTHLY = "monthly", "Monthly"
    QUARTERLY = "quarterly", "Quarterly"
    HALF_YEARLY = "half_yearly", "Half-yearly"
    YEARLY = "yearly", "Yearly"
    CUSTOM = "custom", "Custom"


class Priority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    EMERGENCY = "emergency", "Emergency"
    CRITICAL = "critical", "Critical"


class ServiceStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    IN_PROGRESS = "in_progress", "In progress"
    ON_HOLD = "on_hold", "On hold"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"
    REOPENED = "reopened", "Reopened"


class MaintenanceType(models.TextChoices):
    PREVENTIVE = "preventive", "Preventive"
    CORRECTIVE = "corrective", "Corrective"
    CALIBRATION = "calibration", "Calibration"
    INSPECTION = "inspection", "Inspection"


class ScheduleKind(models.TextChoices):
    RECURRING = "recurring", "Recurring"
    ONE_TIME = "one_time", "One-time"


class PreventiveSchedule(TimeStampedModel):
    equipment = models.ForeignKey("equipment.Equipment", on_delete=models.CASCADE, related_name="pm_schedules")
    title = models.CharField(max_length=150)
    maintenance_type = models.CharField(max_length=20, choices=MaintenanceType.choices, default=MaintenanceType.PREVENTIVE)
    schedule_type = models.CharField(max_length=20, choices=ScheduleKind.choices, default=ScheduleKind.RECURRING, db_index=True)
    frequency = models.CharField(max_length=20, choices=Frequency.choices, default=Frequency.QUARTERLY)
    interval_days = models.PositiveIntegerField(help_text="Derived from frequency; editable for custom.")
    last_done_date = models.DateField(null=True, blank=True)
    next_due_date = models.DateField(db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="pm_assignments"
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    checklist = models.JSONField(default=list, blank=True, help_text="[{title, required}] inspection steps.")
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="pm_created"
    )

    class Meta:
        ordering = ["next_due_date"]
        constraints = [models.CheckConstraint(check=Q(interval_days__gt=0), name="pm_interval_positive")]
        indexes = [
            models.Index(fields=["next_due_date", "is_active"]),
            models.Index(fields=["equipment", "is_active"]),
            models.Index(fields=["assigned_to", "next_due_date"]),
        ]

    def __str__(self):
        return f"{self.equipment_id} · {self.title} · due {self.next_due_date}"

    def next_after_completion(self, completion_date):
        """Next due = completion date + interval (late completion never creates catch-up backlog).

        One-time schedules return None (caller deactivates them).
        """
        from datetime import timedelta

        if self.schedule_type == ScheduleKind.ONE_TIME:
            return None
        return completion_date + timedelta(days=self.interval_days)


class ServiceRequest(TimeStampedModel):
    ticket_no = models.CharField(max_length=20, unique=True, help_text="e.g. SR-2026-0001")
    equipment = models.ForeignKey("equipment.Equipment", on_delete=models.PROTECT, related_name="service_requests")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="requested_tickets"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_tickets"
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM, db_index=True)
    issue_type = models.CharField(max_length=100, blank=True)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=ServiceStatus.choices, default=ServiceStatus.OPEN, db_index=True)
    requested_at = models.DateTimeField(default=timezone.now, db_index=True)
    deadline = models.DateTimeField(null=True, blank=True, db_index=True, help_text="Manager-set target resolution.")
    internal_remarks = models.TextField(blank=True, help_text="Manager-only internal notes.")
    attachment = models.ImageField(upload_to="requests/%Y/", null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    in_progress_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    downtime_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    satisfaction_rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            models.CheckConstraint(
                check=Q(satisfaction_rating__isnull=True)
                | (Q(satisfaction_rating__gte=1) & Q(satisfaction_rating__lte=5)),
                name="sr_rating_1_to_5",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["equipment", "requested_at"]),
            models.Index(fields=["deadline", "status"]),
        ]

    def __str__(self):
        return f"{self.ticket_no} ({self.get_status_display()})"

    @property
    def is_overdue(self):
        if self.deadline and self.status not in ("resolved", "closed"):
            return timezone.now() > self.deadline
        return False


class ServiceActivity(models.Model):
    """Append-only timeline: who did what and when on a request."""

    ACTION_CHOICES = [
        ("created", "Reported"),
        ("assigned", "Assigned"),
        ("status_change", "Status change"),
        ("note", "Progress note"),
        ("report", "Maintenance report"),
        ("edited", "Edited"),
    ]
    service_request = models.ForeignKey(ServiceRequest, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="sr_activities"
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, default="note", db_index=True)
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["service_request", "created_at"])]

    def __str__(self):
        return f"{self.service_request.ticket_no} · {self.action} · {self.created_at:%Y-%m-%d %H:%M}"


class MaintenanceRecord(TimeStampedModel):
    equipment = models.ForeignKey("equipment.Equipment", on_delete=models.PROTECT, related_name="maintenance_records")
    service_request = models.OneToOneField(
        ServiceRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name="record"
    )
    schedule = models.ForeignKey(
        PreventiveSchedule, on_delete=models.SET_NULL, null=True, blank=True, related_name="executions"
    )
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="work_records"
    )
    maintenance_type = models.CharField(max_length=20, choices=MaintenanceType.choices, default=MaintenanceType.CORRECTIVE, db_index=True)
    inspection_findings = models.TextField(blank=True, help_text="Technician inspection findings.")
    work_done = models.TextField(help_text="Repair actions performed.")
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField()
    downtime_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    next_action = models.TextField(blank=True)
    checklist_results = models.JSONField(null=True, blank=True, help_text="[{title, done}] for PM executions.")
    report_file = models.FileField(upload_to="reports/%Y/", null=True, blank=True)

    class Meta:
        ordering = ["-completed_at"]
        constraints = [
            models.CheckConstraint(check=Q(completed_at__gte=F("started_at")), name="record_completed_after_start"),
            models.CheckConstraint(check=Q(cost__gte=0), name="record_cost_non_negative"),
        ]
        indexes = [
            models.Index(fields=["equipment", "completed_at"]),
            models.Index(fields=["technician", "completed_at"]),
            models.Index(fields=["maintenance_type", "completed_at"]),
        ]

    def __str__(self):
        return f"Record #{self.pk} · {self.equipment_id} · {self.maintenance_type}"
