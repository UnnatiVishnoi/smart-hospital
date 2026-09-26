from django.db import models
from django.db.models import F, Q
from apps.core.models import TimeStampedModel


class EquipmentStatus(models.TextChoices):
    OPERATIONAL = "operational", "Operational"
    BREAKDOWN = "breakdown", "Breakdown"
    UNDER_MAINTENANCE = "under_maintenance", "Under maintenance"
    STANDBY = "standby", "Standby"
    DECOMMISSIONED = "decommissioned", "Decommissioned"


class Criticality(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class Category(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True, help_text="e.g. Ventilator, X-Ray, Infusion Pump")
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class Equipment(TimeStampedModel):
    asset_tag = models.CharField(max_length=50, unique=True, help_text="e.g. VEN-ICU-001")
    name = models.CharField(max_length=150, db_index=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="equipment")
    department = models.ForeignKey("hospital.Department", on_delete=models.PROTECT, related_name="equipment")
    manufacturer = models.CharField(max_length=100, db_index=True)
    model_no = models.CharField(max_length=100, blank=True)
    serial_no = models.CharField(max_length=100, unique=True)
    purchase_date = models.DateField()
    warranty_expiry = models.DateField(null=True, blank=True)
    installation_date = models.DateField(null=True, blank=True)
    location_detail = models.CharField(max_length=150, blank=True, help_text="Ward / room / bed.")
    status = models.CharField(max_length=20, choices=EquipmentStatus.choices, default=EquipmentStatus.OPERATIONAL, db_index=True)
    criticality = models.CharField(max_length=10, choices=Criticality.choices, default=Criticality.MEDIUM, db_index=True)
    last_service_date = models.DateField(null=True, blank=True)
    next_pm_date = models.DateField(null=True, blank=True, db_index=True)
    image = models.ImageField(upload_to="equipment/", null=True, blank=True)
    vendor = models.ForeignKey(
        "inventory.Vendor", on_delete=models.SET_NULL, null=True, blank=True, related_name="equipment"
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["asset_tag"]
        constraints = [
            models.CheckConstraint(
                check=Q(warranty_expiry__isnull=True) | Q(warranty_expiry__gt=F("purchase_date")),
                name="equipment_warranty_after_purchase",
            ),
        ]
        indexes = [
            models.Index(fields=["department", "status"]),
            models.Index(fields=["next_pm_date", "status"]),
            models.Index(fields=["category", "status"]),
        ]

    def __str__(self):
        return f"{self.asset_tag} — {self.name}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("equipment_detail", args=[self.pk])


class EquipmentStatusLog(models.Model):
    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, choices=EquipmentStatus.choices)
    changed_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="equipment_status_changes"
    )
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["equipment", "created_at"])]

    def __str__(self):
        return f"{self.equipment_id}: {self.old_status or '—'} → {self.new_status}"
