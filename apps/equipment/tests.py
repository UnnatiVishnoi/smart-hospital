"""Phase 11 — equipment CRUD, duplicates, validation, archive rules, QR, CSV, scoping."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from apps.equipment.models import Category, Equipment
from apps.hospital.models import Department
from apps.maintenance.models import ServiceRequest

PW = "T3stPass!!"
U = get_user_model()


def mkuser(u, role, dept=None):
    o, _ = U.objects.get_or_create(username=u, defaults={"email": f"{u}@t.local", "role": role})
    o.email = f"{u}@t.local"
    o.role = role
    o.is_active = True
    o.department = dept
    o.set_password(PW)
    o.save()
    return o


def mkeq(tag, serial, dept, cat, **kw):
    d = {"asset_tag": tag, "name": f"Device {tag}", "category": cat, "department": dept,
         "manufacturer": "Philips", "model_no": "M1", "serial_no": serial,
         "purchase_date": date(2023, 1, 10)}
    d.update(kw)
    return Equipment.objects.create(**d)


class EquipmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.icu = Department.objects.create(name="E ICU", code="EICU", location="F1")
        cls.rad = Department.objects.create(name="E Rad", code="ERAD", location="F2")
        cls.cat = Category.objects.create(name="E Vent")
        cls.mgr = mkuser("e_mgr", "manager")
        cls.tech = mkuser("e_tech", "technician")
        cls.staff = mkuser("e_staff", "staff", cls.icu)
        cls.eq = mkeq("E-EICU-001", "SN-E-1", cls.icu, cls.cat)

    def _login(self, u):
        c = Client()
        c.login(username=u, password=PW)
        return c

    def _payload(self, tag="E-EICU-900", serial="SN-E-900"):
        return {"asset_tag": tag, "name": "New Vent", "category": self.cat.pk,
                "department": self.icu.pk, "manufacturer": "Philips", "model_no": "T1",
                "serial_no": serial, "purchase_date": "2024-01-10",
                "installation_date": "2024-01-20", "warranty_expiry": "2026-01-10",
                "location_detail": "Bed 1", "criticality": "high", "status": "operational"}

    def test_add_manager_ok_tech_forbidden_anon_redirect(self):
        self.assertEqual(Client().get("/equipment/add/").status_code, 302)
        self.assertEqual(self._login("e_tech").post("/equipment/add/", self._payload()).status_code, 403)
        r = self._login("e_mgr").post("/equipment/add/", self._payload())
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Equipment.objects.filter(serial_no="SN-E-900").exists())

    def test_duplicate_serial_blocked(self):
        c = self._login("e_mgr")
        r = c.post("/equipment/add/", self._payload(tag="E-EICU-901", serial="SN-E-1"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("already registered", r.content.decode())
        r = c.post("/equipment/add/", self._payload(tag="E-EICU-001", serial="SN-E-901"))
        self.assertIn("already exists", r.content.decode())

    def test_invalid_dates_rejected(self):
        r = self._login("e_mgr").post("/equipment/add/", dict(
            self._payload(), purchase_date="2024-06-01", installation_date="2024-01-01"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("precede", r.content.decode())

    def test_edit_and_cross_dept_staff_404(self):
        other = mkeq("E-ERAD-002", "SN-E-2", self.rad, self.cat)
        self.assertEqual(self._login("e_staff").get(f"/equipment/{other.pk}/").status_code, 404)
        self.assertEqual(self._login("e_staff").get(f"/equipment/{self.eq.pk}/").status_code, 200)
        c = self._login("e_mgr")
        r = c.post(f"/equipment/{self.eq.pk}/edit/", dict(
            self._payload(tag=self.eq.asset_tag, serial=self.eq.serial_no), name="Renamed Vent"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Equipment.objects.get(pk=self.eq.pk).name, "Renamed Vent")

    def test_archive_blocked_with_open_request_then_allowed(self):
        admin = mkuser("e_admin", "admin")
        sr = ServiceRequest.objects.create(
            ticket_no="SR-E-9901", equipment=self.eq, requested_by=admin,
            description="Blocking fault report here.", status="open")
        c = Client()
        c.login(username="e_admin", password=PW)
        c.post(f"/equipment/{self.eq.pk}/archive/")
        self.assertTrue(Equipment.objects.get(pk=self.eq.pk).is_active)
        sr.delete()
        c.post(f"/equipment/{self.eq.pk}/archive/")
        eq = Equipment.objects.get(pk=self.eq.pk)
        self.assertFalse(eq.is_active)
        self.assertEqual(eq.status, "decommissioned")
        c.post(f"/equipment/{self.eq.pk}/restore/")
        self.assertTrue(Equipment.objects.get(pk=self.eq.pk).is_active)

    def test_qr_and_csv_permissions(self):
        self.assertEqual(Client().get(f"/equipment/{self.eq.pk}/qr.png").status_code, 302)
        r = self._login("e_mgr").get(f"/equipment/{self.eq.pk}/qr.png")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("image/png"))
        self.assertEqual(self._login("e_mgr").get("/equipment/export.csv").status_code, 200)
        self.assertEqual(self._login("e_tech").get("/equipment/export.csv").status_code, 403)
