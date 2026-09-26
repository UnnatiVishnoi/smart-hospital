from django.db import models
from django.db.models import Q
from apps.core.models import TimeStampedModel


class Vendor(TimeStampedModel):
    name = models.CharField(max_length=150, unique=True)
    contact_person = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    specialization = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SparePart(TimeStampedModel):
    part_no = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=150, db_index=True)
    description = models.TextField(blank=True)
    quantity_in_stock = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=5)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vendor = models.ForeignKey(Vendor, on_delete=models.SET_NULL, null=True, blank=True, related_name="parts")
    compatible_categories = models.ManyToManyField("equipment.Category", blank=True, related_name="compatible_parts")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["part_no"]
        constraints = [models.CheckConstraint(check=Q(unit_price__gte=0), name="part_price_non_negative")]
        indexes = [models.Index(fields=["is_active", "quantity_in_stock"])]

    def __str__(self):
        return f"{self.part_no} — {self.name}"


class PartUsage(models.Model):
    maintenance_record = models.ForeignKey(
        "maintenance.MaintenanceRecord", on_delete=models.CASCADE, related_name="part_usages"
    )
    spare_part = models.ForeignKey(SparePart, on_delete=models.PROTECT, related_name="usages")
    quantity = models.PositiveIntegerField()
    unit_cost_at_use = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["maintenance_record", "spare_part"], name="uniq_usage_record_part"),
            models.CheckConstraint(check=Q(quantity__gt=0), name="usage_qty_positive"),
        ]
        indexes = [models.Index(fields=["spare_part", "created_at"])]

    def __str__(self):
        return f"{self.spare_part_id} x{self.quantity} on record {self.maintenance_record_id}"
