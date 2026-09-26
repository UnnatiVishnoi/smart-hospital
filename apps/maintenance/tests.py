"""Phase 6 workflow tests — run: python manage.py test apps.maintenance (uses MySQL test DB)."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from apps.equipment.models import Category, Equipment
from apps.hospital.models import Department
from apps.inventory.models import SparePart, Vendor
from apps.maintenance.models import MaintenanceRecord, ServiceActivity, ServiceRequest

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


class WorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name="Test ICU", code="TICU", location="F1")
        cls.cat = Category.objects.create(name="Test Vent")
        cls.vendor = Vendor.objects.create(name="Test Vendor")
        cls.eq = Equipment.objects.create(
            asset_tag="TV-TICU-001", name="Test Vent", category=cls.cat, department=cls.dept,
            manufacturer="Philips", model_no="T1", serial_no="SN-TEST-WF-1",
            purchase_date=date.today() - timedelta(days=100), status="operational",
            criticality="high", vendor=cls.vendor,
        )
        cls.part = SparePart.objects.create(part_no="P-TEST-1", name="Filter", quantity_in_stock=10,
                                            unit_price=250, vendor=cls.vendor)
        cls.staff = mkuser("wf_staff", "staff", cls.dept)
        cls.manager = mkuser("wf_manager", "manager")
        cls.tech = mkuser("wf_tech", "technician")
        cls.other_staff = mkuser("wf_other", "staff")

    def _login(self, u):
        c = Client()
        c.login(username=u, password=PW)
        return c

    def test_full_lifecycle_with_report_and_parts(self):
        staff, manager, tech = self._login("wf_staff"), self._login("wf_manager"), self._login("wf_tech")
        # create
        r = staff.post("/requests/report/", {"equipment": self.eq.pk, "priority": "high",
                                             "issue_type": "No cooling",
                                             "description": "Ventilator shows error E4 and stops cooling patients."})
        self.assertEqual(r.status_code, 302)
        sr = ServiceRequest.objects.get(equipment=self.eq)
        self.assertEqual(sr.status, "open")
        self.eq.refresh_from_db()
        self.assertEqual(self.eq.status, "breakdown")
        # duplicate blocked
        r2 = staff.post("/requests/report/", {"equipment": self.eq.pk, "priority": "high",
                                              "issue_type": "No cooling",
                                              "description": "Ventilator shows error E4 and stops cooling patients."})
        self.assertEqual(ServiceRequest.objects.filter(equipment=self.eq).count(), 1)
        # manager assigns
        future = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        r = manager.post(f"/requests/{sr.pk}/assign/", {"assigned_to": str(self.tech.pk),
                                                        "deadline": future, "internal_remarks": "Urgent"})
        sr.refresh_from_db()
        self.assertEqual(sr.status, "acknowledged")
        self.assertEqual(sr.assigned_to, self.tech)
        # tech starts
        self.assertEqual(tech.post(f"/requests/{sr.pk}/transition/in_progress/").status_code, 302)
        sr.refresh_from_db()
        self.assertEqual(sr.status, "in_progress")
        # invalid jump in_progress -> closed blocked
        self.assertEqual(tech.post(f"/requests/{sr.pk}/transition/closed/").status_code, 302)
        sr.refresh_from_db()
        self.assertEqual(sr.status, "in_progress")
        # resolve with report + part
        r = tech.post(f"/requests/{sr.pk}/resolve/", {
            "inspection_findings": "Clogged filter and sensor drift confirmed on bench test.",
            "work_done": "Replaced filter, recalibrated sensor, ran 2h burn-in test.",
            "cost": "1250.00", "downtime_hours": "6.5", "next_action": "Recheck in 30 days",
            "part_1": str(self.part.pk), "qty_1": "2",
        })
        sr.refresh_from_db()
        self.assertEqual(sr.status, "resolved")
        self.assertTrue(MaintenanceRecord.objects.filter(service_request=sr).exists())
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity_in_stock, 8)
        self.eq.refresh_from_db()
        self.assertEqual(self.eq.status, "operational")
        # requester closes with rating
        r = staff.post(f"/requests/{sr.pk}/close/", {"satisfaction_rating": "5"})
        sr.refresh_from_db()
        self.assertEqual((sr.status, sr.satisfaction_rating), ("closed", 5))
        # timeline complete
        self.assertGreaterEqual(ServiceActivity.objects.filter(service_request=sr).count(), 4)
        # unauthorized: other staff cannot see, tech cannot assign
        self.assertEqual(self._login("wf_other").get(f"/requests/{sr.pk}/").status_code, 404)
        self.assertEqual(tech.post(f"/requests/{sr.pk}/assign/",
                                   {"assigned_to": str(self.tech.pk)}).status_code, 403)

    def test_reopen_flow(self):
        c = self._login("wf_staff")
        eq2 = Equipment.objects.create(
            asset_tag="TV-TICU-002", name="Test Vent 2", category=self.cat, department=self.dept,
            manufacturer="Philips", model_no="T1", serial_no="SN-TEST-WF-2",
            purchase_date=date.today() - timedelta(days=50))
        c.post("/requests/report/", {"equipment": eq2.pk, "priority": "medium",
                                     "description": "Second unit rattling loudly during operation cycle."})
        sr = ServiceRequest.objects.get(equipment=eq2)
        m = self._login("wf_manager")
        m.post(f"/requests/{sr.pk}/assign/", {"assigned_to": str(self.tech.pk)})
        t = self._login("wf_tech")
        t.post(f"/requests/{sr.pk}/transition/in_progress/")
        t.post(f"/requests/{sr.pk}/resolve/", {"inspection_findings": "Loose fan mount found and verified.",
                                               "work_done": "Tightened mount, replaced damper, tested OK.",
                                               "cost": "0"})
        sr.refresh_from_db()
        self.assertEqual(sr.status, "resolved")
        c.post(f"/requests/{sr.pk}/reopen/")
        sr.refresh_from_db()
        self.assertEqual(sr.status, "reopened")
        eq2.refresh_from_db()
        self.assertEqual(eq2.status, "breakdown")
