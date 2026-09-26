"""Phase 11 — notification generation on assign/status change + read flow."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from apps.equipment.models import Category, Equipment
from apps.hospital.models import Department
from apps.maintenance.models import ServiceRequest
from apps.notifications.models import Notification

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


class NotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name="N ICU", code="NICU", location="F1")
        cls.cat = Category.objects.create(name="N Vent")
        cls.eq = Equipment.objects.create(
            asset_tag="N-NICU-001", name="N Vent", category=cls.cat, department=cls.dept,
            manufacturer="Philips", model_no="V1", serial_no="SN-N-1",
            purchase_date=date(2023, 1, 10))
        cls.staff = mkuser("n_staff", "staff", cls.dept)
        cls.mgr = mkuser("n_mgr", "manager")
        cls.tech = mkuser("n_tech", "technician")

    def test_assign_notifies_technician_and_requester(self):
        s = Client()
        s.login(username="n_staff", password=PW)
        s.post("/requests/report/", {"equipment": self.eq.pk, "priority": "high",
                                     "description": "Ventilator alarm keeps sounding for no reason."})
        sr = ServiceRequest.objects.get()
        m = Client()
        m.login(username="n_mgr", password=PW)
        from django.utils import timezone
        from datetime import timedelta
        dl = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        m.post(f"/requests/{sr.pk}/assign/", {"assigned_to": str(self.tech.pk), "deadline": dl})
        self.assertTrue(Notification.objects.filter(recipient=self.tech, service_request=sr).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.staff, service_request=sr).exists())

    def test_read_marks_and_redirects_to_request(self):
        n = Notification.objects.create(recipient=self.tech, title="Ping", message="Hello there.")
        c = Client()
        c.login(username="n_tech", password=PW)
        r = c.post(f"/notifications/{n.pk}/read/")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Notification.objects.get(pk=n.pk).is_read)

    def test_cannot_read_others_notification(self):
        n = Notification.objects.create(recipient=self.mgr, title="Private", message="Managers only.")
        c = Client()
        c.login(username="n_tech", password=PW)
        self.assertEqual(c.post(f"/notifications/{n.pk}/read/").status_code, 404)
