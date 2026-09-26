"""Phase 11 — request validation, assignment auth, transitions, duplicates, notes, close."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from apps.equipment.models import Category, Equipment
from apps.hospital.models import Department
from apps.maintenance.models import ServiceRequest

PW = "T3stPass!!"
U = get_user_model()
DESC = "Ventilator shows error E4 and stops cooling the patient circuit."


def mkuser(u, role, dept=None):
    o, _ = U.objects.get_or_create(username=u, defaults={"email": f"{u}@t.local", "role": role})
    o.email = f"{u}@t.local"
    o.role = role
    o.is_active = True
    o.department = dept
    o.set_password(PW)
    o.save()
    return o


class RequestValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name="Q ICU", code="QICU", location="F1")
        cls.cat = Category.objects.create(name="Q Vent")
        cls.eq = Equipment.objects.create(
            asset_tag="Q-QICU-001", name="Q Vent", category=cls.cat, department=cls.dept,
            manufacturer="Philips", model_no="V1", serial_no="SN-Q-1",
            purchase_date=date(2023, 1, 10))
        cls.staff = mkuser("q_staff", "staff", cls.dept)
        cls.mgr = mkuser("q_mgr", "manager")
        cls.tech = mkuser("q_tech", "technician")

    def _login(self, u):
        c = Client()
        c.login(username=u, password=PW)
        return c

    def _report(self, client=None, **kw):
        c = client or self._login("q_staff")
        d = {"equipment": self.eq.pk, "priority": "high", "issue_type": "Fault",
             "description": DESC}
        d.update(kw)
        return c.post("/requests/report/", d)

    def test_short_description_rejected(self):
        r = self._report(description="Broken.")
        self.assertEqual(r.status_code, 200)
        self.assertIn("at least 20", r.content.decode())
        self.assertEqual(ServiceRequest.objects.count(), 0)

    def test_bad_attachment_rejected(self):
        bad = SimpleUploadedFile("evil.exe", b"MZ fake binary", "application/octet-stream")
        r = self._report(attachment=bad)
        self.assertEqual(r.status_code, 200)
        self.assertIn("valid image", r.content.decode())
        self.assertEqual(ServiceRequest.objects.count(), 0)

    def test_duplicate_within_window_blocked(self):
        c = self._login("q_staff")
        self.assertEqual(self._report(client=c).status_code, 302)
        r = self._report(client=c)
        self.assertEqual(r.status_code, 302)  # redirected to existing ticket
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_assign_manager_only(self):
        self._report()
        sr = ServiceRequest.objects.get()
        future = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        tech_client = self._login("q_tech")
        self.assertEqual(tech_client.post(
            f"/requests/{sr.pk}/assign/",
            {"assigned_to": str(self.tech.pk), "deadline": future}).status_code, 403)
        r = self._login("q_mgr").post(
            f"/requests/{sr.pk}/assign/",
            {"assigned_to": str(self.tech.pk), "deadline": future, "internal_remarks": "Urgent"})
        self.assertEqual(r.status_code, 302)
        sr.refresh_from_db()
        self.assertEqual((sr.status, sr.assigned_to), ("acknowledged", self.tech))

    def test_invalid_transition_blocked(self):
        self._report()
        sr = ServiceRequest.objects.get()
        # open -> resolved is not a legal jump
        self._login("q_mgr").post(f"/requests/{sr.pk}/transition/resolved/")
        sr.refresh_from_db()
        self.assertEqual(sr.status, "open")

    def test_note_by_outsider_blocked(self):
        self._report()
        sr = ServiceRequest.objects.get()
        other = mkuser("q_other", "staff")
        c = Client()
        c.login(username="q_other", password=PW)
        # Outsider cannot even see the request (scoped queryset -> 404), so no note lands.
        r = c.post(f"/requests/{sr.pk}/note/", {"note": "Trying to comment here."})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(sr.activities.filter(action="note").exists())
        _ = other

    def test_close_by_non_requester_blocked(self):
        self._report()
        sr = ServiceRequest.objects.get()
        mgr = self._login("q_mgr")
        mgr.post(f"/requests/{sr.pk}/assign/", {"assigned_to": str(self.tech.pk)})
        tech = self._login("q_tech")
        tech.post(f"/requests/{sr.pk}/transition/in_progress/")
        tech.post(f"/requests/{sr.pk}/resolve/", {
            "inspection_findings": "Findings recorded on the test bench unit.",
            "work_done": "Replaced the faulty sensor and tested fine.",
            "cost": "100"})
        sr.refresh_from_db()
        self.assertEqual(sr.status, "resolved")
        other = mkuser("q_other2", "staff")
        c = Client()
        c.login(username="q_other2", password=PW)
        c.post(f"/requests/{sr.pk}/close/", {})
        sr.refresh_from_db()
        self.assertEqual(sr.status, "resolved")  # unchanged
        _ = other
