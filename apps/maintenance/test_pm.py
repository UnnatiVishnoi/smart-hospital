"""Phase 7 tests — run: python manage.py test apps.maintenance.test_pm (MySQL test DB)."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from apps.equipment.models import Category, Equipment
from apps.hospital.models import Department
from apps.maintenance.models import MaintenanceRecord, PreventiveSchedule
from apps.notifications.models import Notification

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


class PMTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name="PM ICU", code="PICU", location="F1")
        cls.cat = Category.objects.create(name="PM Vent")
        cls.eq = Equipment.objects.create(
            asset_tag="PM-PICU-001", name="PM Vent", category=cls.cat, department=cls.dept,
            manufacturer="Philips", model_no="T1", serial_no="SN-PM-1",
            purchase_date=date.today() - timedelta(days=200))
        cls.mgr = mkuser("pm_mgr", "manager")
        cls.tech = mkuser("pm_tech", "technician")
        cls.staff = mkuser("pm_staff", "staff", cls.dept)
        cls.sched = PreventiveSchedule.objects.create(
            equipment=cls.eq, title="Quarterly calibration", maintenance_type="calibration",
            schedule_type="recurring", frequency="quarterly", interval_days=90,
            next_due_date=date.today() + timedelta(days=2), assigned_to=cls.tech,
            checklist=[{"title": "Check filter", "required": True}],
            created_by=cls.mgr)

    def _login(self, u):
        c = Client()
        c.login(username=u, password=PW)
        return c

    def _complete(self, client, sched, when, tick=True):
        data = {"completion_date": when.isoformat(),
                "inspection_findings": "All parameters within tolerance on test bench.",
                "work_done": "Calibrated sensor, replaced filter, ran burn-in.",
                "cost": "800"}
        if tick:
            data["step_0"] = "on"
        return client.post(f"/pm/schedules/{sched.pk}/complete/", data)

    def test_on_time_completion_advances_by_interval(self):
        c = self._login("pm_tech")
        when = date.today()
        self.assertEqual(self._complete(c, self.sched, when).status_code, 302)
        self.sched.refresh_from_db()
        self.assertEqual((self.sched.last_done_date, self.sched.next_due_date),
                         (when, when + timedelta(days=90)))
        self.assertTrue(self.sched.is_active)
        rec = MaintenanceRecord.objects.get(schedule=self.sched)
        self.assertEqual(rec.checklist_results, [{"title": "Check filter", "done": True}])

    def test_late_completion_restarts_from_completion_date(self):
        self.sched.next_due_date = date.today() - timedelta(days=20)
        self.sched.save()
        c = self._login("pm_tech")
        when = date.today()
        self._complete(c, self.sched, when)
        self.sched.refresh_from_db()
        # NOT due+interval (would be +70d); must be completion+interval
        self.assertEqual(self.sched.next_due_date, when + timedelta(days=90))

    def test_one_time_deactivates(self):
        self.sched.schedule_type = "one_time"
        self.sched.save()
        self._complete(self._login("pm_tech"), self.sched, date.today())
        self.sched.refresh_from_db()
        self.assertFalse(self.sched.is_active)

    def test_checklist_required_enforced(self):
        c = self._login("pm_tech")
        r = self._complete(c, self.sched, date.today(), tick=False)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(MaintenanceRecord.objects.filter(schedule=self.sched).exists())

    def test_reminders_idempotent(self):
        self.sched.next_due_date = date.today() - timedelta(days=1)
        self.sched.save()
        call_command("send_pm_reminders")
        n1 = Notification.objects.filter(schedule=self.sched, type="pm_overdue").count()
        self.assertGreaterEqual(n1, 1)
        call_command("send_pm_reminders")
        n2 = Notification.objects.filter(schedule=self.sched, type="pm_overdue").count()
        self.assertEqual(n1, n2)

    def test_permissions(self):
        self.assertEqual(self._login("pm_tech").get("/pm/schedules/new/").status_code, 403)
        # staff in same dept can view but cannot complete
        c = self._login("pm_staff")
        self.assertEqual(c.get(f"/pm/schedules/{self.sched.pk}/").status_code, 200)
        self.assertEqual(c.get(f"/pm/schedules/{self.sched.pk}/complete/").status_code, 403)
        self.assertEqual(Client().get("/pm/").status_code, 302)
