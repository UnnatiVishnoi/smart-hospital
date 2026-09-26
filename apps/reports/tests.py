"""Phase 9 tests — run: python manage.py test apps.reports (MySQL test DB)."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from apps.equipment.models import Category, Equipment
from apps.hospital.models import Department
from apps.inventory.models import PartUsage, SparePart, Vendor
from apps.maintenance.models import MaintenanceRecord, PreventiveSchedule, ServiceRequest
from apps.reports.metrics import build_report

PW = "T3stPass!!"


def mkuser(u, role, dept=None):
    U = get_user_model()
    o, _ = U.objects.get_or_create(username=u, defaults={"email": f"{u}@t.local", "role": role})
    o.email = f"{u}@t.local"
    o.role = role
    o.is_active = True
    o.department = dept
    o.set_password(PW)
    o.save()
    return o


class MetricsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.d1 = Department.objects.create(name="R ICU", code="RICU", location="F1")
        cls.d2 = Department.objects.create(name="R Ward", code="RWARD", location="F2")
        cls.cat = Category.objects.create(name="R Vent")
        cls.vendor = Vendor.objects.create(name="R Vendor")
        cls.e1 = Equipment.objects.create(
            asset_tag="R-RICU-001", name="Vent A", category=cls.cat, department=cls.d1,
            manufacturer="Philips", model_no="V1", serial_no="SN-R-1",
            purchase_date=date(2022, 1, 10), warranty_expiry=date(2024, 1, 10),
            status="operational", criticality="high", vendor=cls.vendor)
        cls.e2 = Equipment.objects.create(
            asset_tag="R-RICU-002", name="Vent B", category=cls.cat, department=cls.d1,
            manufacturer="Philips", model_no="V1", serial_no="SN-R-2",
            purchase_date=date(2023, 6, 1), warranty_expiry=date.today() + timedelta(days=30),
            status="breakdown", criticality="critical", vendor=cls.vendor)
        cls.e3 = Equipment.objects.create(
            asset_tag="R-RWARD-003", name="Vent C", category=cls.cat, department=cls.d2,
            manufacturer="GE", model_no="G1", serial_no="SN-R-3",
            purchase_date=date(2023, 1, 1), warranty_expiry=date.today() + timedelta(days=400),
            status="operational", criticality="low", vendor=cls.vendor)
        cls.mgr = mkuser("r_mgr", "manager")
        cls.tech = mkuser("r_tech", "technician")
        cls.staff = mkuser("r_staff", "staff", cls.d1)
        now = timezone.now()
        # resolved SR on e1: 48h repair, 5h downtime
        cls.sr1 = ServiceRequest.objects.create(
            ticket_no="SR-R-0001", equipment=cls.e1, requested_by=cls.staff,
            assigned_to=cls.tech, priority="high", description="Fault one here.",
            status="resolved", requested_at=now - timedelta(days=10),
            resolved_at=now - timedelta(days=8), downtime_hours=5)
        ServiceRequest.objects.create(
            ticket_no="SR-R-0002", equipment=cls.e2, requested_by=cls.staff,
            assigned_to=cls.tech, priority="emergency", description="Fault two here.",
            status="open", requested_at=now - timedelta(days=2))
        cls.part = SparePart.objects.create(part_no="P-R-1", name="Filter", quantity_in_stock=50,
                                            unit_price=100, vendor=cls.vendor)
        cls.rec = MaintenanceRecord.objects.create(
            equipment=cls.e1, service_request=cls.sr1, technician=cls.tech,
            work_done="Replaced filter and calibrated.", cost=1000,
            started_at=now - timedelta(days=9), completed_at=now - timedelta(days=8))
        PartUsage.objects.create(maintenance_record=cls.rec, spare_part=cls.part,
                                 quantity=2, unit_cost_at_use=100)
        cls.sched = PreventiveSchedule.objects.create(
            equipment=cls.e1, title="Quarterly cal", frequency="quarterly", interval_days=90,
            next_due_date=date.today() - timedelta(days=3), assigned_to=cls.tech,
            created_by=cls.mgr)

    def _f(self):
        today = timezone.localdate()
        return {"date_from": today - timedelta(days=90), "date_to": today,
                "department": "", "category": "", "status": ""}

    def test_exact_numbers(self):
        m = build_report(self.mgr, self._f())
        self.assertEqual((m["total"], m["operational"], m["non_operational"]), (3, 2, 1))
        self.assertEqual((m["open_sr"], m["resolved_sr"]), (1, 1))
        self.assertEqual(m["downtime"], 5.0)
        self.assertEqual(m["avg_repair"], 48.0)
        self.assertEqual((m["labor_cost"], m["parts_cost"], m["expenditure"]), (1000.0, 200.0, 1200.0))
        self.assertEqual(m["overdue_pm"], 1)
        self.assertEqual((m["expired"], m["expiring"]), (1, 1))
        self.assertEqual(m["by_eq"][0]["equipment__asset_tag"], "R-RICU-001")
        self.assertEqual(m["by_dept"][0]["equipment__department__code"], "RICU")

    def test_pm_rate_with_execution(self):
        f = self._f()
        self.assertEqual(build_report(self.mgr, f)["pm_rate"], 0.0)  # due but not executed
        MaintenanceRecord.objects.create(
            equipment=self.e1, schedule=self.sched, technician=self.tech,
            work_done="PM done.", cost=0,
            started_at=timezone.now() - timedelta(days=4),
            completed_at=timezone.now() - timedelta(days=3))
        self.assertEqual(build_report(self.mgr, f)["pm_rate"], 100.0)

    def test_filters_narrow_everything(self):
        f = self._f()
        f["department"] = str(self.d2.pk)
        m = build_report(self.mgr, f)
        self.assertEqual((m["total"], m["breakdowns"], m["expenditure"]), (1, 0, 0.0))
        f2 = self._f()
        f2["status"] = "breakdown"
        self.assertEqual(build_report(self.mgr, f2)["total"], 1)

    def test_staff_scope_and_csv(self):
        c = Client()
        c.login(username="r_staff", password=PW)
        m = build_report(self.staff, self._f())
        self.assertEqual(m["total"], 2)  # own dept only
        r = c.get("/reports/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "R-RICU-001")
        r = c.get("/reports/requests.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("SR-R-0001", r.content.decode())
        self.assertNotIn("R-RWARD", r.content.decode())
        self.assertEqual(Client().get("/reports/").status_code, 302)
        for url in ["/reports/costs/", "/reports/workload/", "/reports/history/", "/reports/print/"]:
            self.assertEqual(c.get(url).status_code, 200)
