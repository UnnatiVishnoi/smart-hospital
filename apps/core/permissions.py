"""Server-side RBAC helpers. Frontend hiding is never sufficient — every view must enforce here."""
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied


def has_role(user, roles):
    if not user or not user.is_authenticated:
        return False
    if not user.is_active:
        return False
    if user.is_superuser:
        return True
    return user.role in roles


def is_admin(user):
    return has_role(user, ["admin"])


def is_manager(user):
    return has_role(user, ["admin", "manager"])


def is_technician(user):
    return has_role(user, ["admin", "manager", "technician"])


def role_required(roles):
    """Function-view guard. Raises 403 (uses custom 403.html)."""

    def check(user):
        if not user.is_authenticated:
            return False
        if has_role(user, roles):
            return True
        raise PermissionDenied

    return user_passes_test(check)


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    allowed_roles = []
    raise_exception = True  # -> 403 for authenticated, redirect for anonymous (see below)

    def test_func(self):
        return has_role(self.request.user, self.allowed_roles)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(
                self.request.get_full_path(),
                self.get_login_url(),
                self.get_redirect_field_name(),
            )
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied


def visible_equipment_qs(user, qs):
    """Role scoping for equipment registry."""
    if user.is_superuser or user.role in ("admin", "manager"):
        return qs
    if user.role == "technician":
        return qs.filter(is_active=True)
    # staff: own department only
    if user.department_id:
        return qs.filter(department_id=user.department_id, is_active=True)
    return qs.none()


def visible_requests_qs(user, qs):
    """Role scoping for service requests."""
    if user.is_superuser or user.role in ("admin", "manager"):
        return qs
    if user.role == "technician":
        return qs.filter(assigned_to=user)
    return qs.filter(requested_by=user)
