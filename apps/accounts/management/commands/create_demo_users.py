"""Create demo users for evaluation. Idempotent.

Run: python manage.py create_demo_users
WARNING: public, well-known passwords — demo/staging only, never production.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.hospital.models import Department

U = get_user_model()

DEMO_USERS = [
    # (username, email, role, password)
    ("demo_admin", "admin@demo.local", "admin", "Demo@1234"),
    ("demo_manager", "manager@demo.local", "manager", "Demo@1234"),
    ("demo_tech", "tech@demo.local", "technician", "Demo@1234"),
    ("demo_staff", "staff@demo.local", "staff", "Demo@1234"),
]


class Command(BaseCommand):
    help = "Create demo users with documented passwords (demo only)."

    def handle(self, *args, **opts):
        dept = Department.objects.order_by("pk").first()
        if dept is None:
            dept = Department.objects.create(name="General Ward", code="GEN", location="Demo block")
        for username, email, role, password in DEMO_USERS:
            user, _ = U.objects.update_or_create(
                username=username,
                defaults={"email": email, "role": role, "is_active": True,
                          "is_staff": role == "admin", "is_superuser": False,
                          "department": dept if role == "staff" else None})
            user.set_password(password)
            user.save()
            self.stdout.write(f"{username:14s} {role:11s} {password}")
        self.stdout.write(self.style.WARNING(
            "Demo credentials are public — use only for evaluation, never production."))
