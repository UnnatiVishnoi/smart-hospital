from django.contrib.auth.models import AbstractUser
from django.db import models


class RoleChoices(models.TextChoices):
    ADMIN = "admin", "Administrator"
    MANAGER = "manager", "Maintenance Manager"
    TECHNICIAN = "technician", "Biomedical Technician"
    STAFF = "staff", "Hospital Staff"


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=RoleChoices.choices, default=RoleChoices.STAFF, db_index=True)
    phone = models.CharField(max_length=20, blank=True)
    department = models.ForeignKey(
        "hospital.Department", on_delete=models.SET_NULL, null=True, blank=True, related_name="members"
    )
    profile_image = models.ImageField(upload_to="profiles/", null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["role"]),
            models.Index(fields=["department", "role"]),
        ]
        ordering = ["username"]

    def __str__(self):
        name = self.get_full_name() or self.username
        return f"{name} ({self.get_role_display()})"
