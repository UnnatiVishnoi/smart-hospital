"""Phase 11 — inventory constraints: uniqueness, non-negative pricing, positive usage."""
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.inventory.models import PartUsage, SparePart, Vendor
from apps.maintenance.models import MaintenanceRecord


class InventoryConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.vendor = Vendor.objects.create(name="Inv Vendor")
        cls.part = SparePart.objects.create(part_no="P-INV-1", name="Filter",
                                            quantity_in_stock=10, unit_price=100,
                                            vendor=cls.vendor)

    def test_vendor_and_part_no_unique(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vendor.objects.create(name="Inv Vendor")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SparePart.objects.create(part_no="P-INV-1", name="Dup", quantity_in_stock=1,
                                         unit_price=5)

    def test_negative_price_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SparePart.objects.create(part_no="P-INV-NEG", name="Bad", quantity_in_stock=1,
                                         unit_price=-5)

    def test_zero_quantity_usage_rejected(self):
        from datetime import date, timedelta
        from django.utils import timezone

        from apps.equipment.models import Category, Equipment
        from apps.hospital.models import Department
        dept = Department.objects.create(name="Inv Dept", code="INV", location="F1")
        cat = Category.objects.create(name="Inv Cat")
        eq = Equipment.objects.create(
            asset_tag="INV-001", name="Inv Device", category=cat, department=dept,
            manufacturer="M", model_no="M1", serial_no="SN-INV-1",
            purchase_date=date(2023, 1, 10))
        now = timezone.now()
        rec = MaintenanceRecord.objects.create(
            equipment=eq, technician=None, work_done="x", cost=0,
            started_at=now - timedelta(hours=1), completed_at=now)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PartUsage.objects.create(maintenance_record=rec, spare_part=self.part,
                                         quantity=0, unit_cost_at_use=100)
