"""Daily PM + warranty reminders. Idempotent: one unread notification per (schedule, type).

Run: python manage.py send_pm_reminders
Schedule (no Celery in this project) via cron, e.g. daily 07:00:
  0 7 * * * cd /path/to/smart-hospital && .venv/bin/python manage.py send_pm_reminders >> logs/reminders.log 2>&1
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.equipment.models import Equipment
from apps.maintenance.models import PreventiveSchedule
from apps.notifications.models import Notification

UPCOMING_DAYS = 3
WARRANTY_DAYS = 30


def _managers():
    from django.contrib.auth import get_user_model

    return list(get_user_model().objects.filter(role__in=["admin", "manager"], is_active=True))


def _needs(schedule, ntype):
    """True when no unread notification of this type exists for the schedule."""
    return not Notification.objects.filter(
        schedule=schedule, type=ntype, is_read=False).exists()


def _recipients(schedule):
    people = list(_managers())
    if schedule.assigned_to and schedule.assigned_to.is_active:
        people.append(schedule.assigned_to)
    seen, out = set(), []
    for u in people:
        if u.pk not in seen:
            seen.add(u.pk)
            out.append(u)
    return out


class Command(BaseCommand):
    help = "Send PM due/upcoming/overdue + warranty reminders (idempotent)."

    def handle(self, *args, **opts):
        today = timezone.localdate()
        counts = {"due": 0, "upcoming": 0, "overdue": 0, "warranty": 0}
        for s in PreventiveSchedule.objects.filter(is_active=True).select_related("equipment", "assigned_to"):
            if s.next_due_date < today:
                ntype, title = "pm_overdue", f"Overdue: {s.title}"
                msg = f"{s.equipment.asset_tag} was due {s.next_due_date} ({(today - s.next_due_date).days}d late)"
            elif s.next_due_date == today:
                ntype, title = "pm_due", f"Due today: {s.title}"
                msg = f"{s.equipment.asset_tag} · {s.equipment.department.code if hasattr(s.equipment, 'department') else ''}"
            elif today < s.next_due_date <= today + timedelta(days=UPCOMING_DAYS):
                ntype, title = "pm_upcoming", f"Upcoming: {s.title}"
                msg = f"{s.equipment.asset_tag} due {s.next_due_date}"
            else:
                continue
            if not _needs(s, ntype):
                continue
            for u in _recipients(s):
                Notification.objects.create(recipient=u, title=title, message=msg, type=ntype,
                                            equipment=s.equipment, schedule=s)
            counts[{"pm_due": "due", "pm_upcoming": "upcoming", "pm_overdue": "overdue"}[ntype]] += 1
        for eq in Equipment.objects.filter(
                is_active=True, warranty_expiry__gte=today,
                warranty_expiry__lte=today + timedelta(days=WARRANTY_DAYS)).select_related("department"):
            if Notification.objects.filter(equipment=eq, type="warranty", is_read=False).exists():
                continue
            for m in _managers():
                Notification.objects.create(
                    recipient=m, title=f"Warranty expiring: {eq.asset_tag}",
                    message=f"{eq.manufacturer} {eq.model_no} expires {eq.warranty_expiry}",
                    type="warranty", equipment=eq)
            counts["warranty"] += 1
        self.stdout.write(self.style.SUCCESS(
            f"Reminders: {counts['overdue']} overdue, {counts['due']} due, "
            f"{counts['upcoming']} upcoming, {counts['warranty']} warranty. "
            f"Re-runs create nothing new while unread reminders exist."))
