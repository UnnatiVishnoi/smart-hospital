from django.contrib import messages
from django.contrib.auth import login, views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic import FormView, ListView
from apps.audit.models import AuditLog
from apps.core.permissions import RoleRequiredMixin
from .forms import AdminUserCreateForm, AdminUserUpdateForm, ProfileForm, SelfRegisterForm, StyledLoginForm, StyledPasswordChangeForm
from .models import User


def _audit(request, action, user_obj, old=None, new=None):
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        model_name="accounts.User",
        object_id=str(user_obj.pk),
        old_values=old,
        new_values=new,
        ip_address=request.META.get("REMOTE_ADDR"),
    )


class CustomLoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = StyledLoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        messages.success(self.request, f"Welcome back, {form.get_user().get_full_name() or form.get_user().username}.")
        _audit(self.request, "login", form.get_user(), new={"username": form.get_user().username})
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Sign-in failed. Check your credentials and try again.")
        return super().form_invalid(form)


class CustomLogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("login")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            _audit(request, "logout", request.user)
            messages.info(request, "You have been signed out securely.")
        return super().dispatch(request, *args, **kwargs)


class RegisterView(FormView):
    """Public self-registration with role choice (admin excluded). Auto-logs in on success."""

    template_name = "registration/register.html"
    form_class = SelfRegisterForm
    success_url = reverse_lazy("dashboard")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    @method_decorator(sensitive_post_parameters("password1", "password2"))
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        _audit(self.request, "register", user, new={"username": user.username, "role": user.role})
        login(self.request, user)
        messages.success(
            self.request,
            f"Welcome, {user.first_name or user.username}! Signed in as {user.get_role_display()}.",
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Registration failed. Please fix the errors below.")
        return super().form_invalid(form)


class ProfileView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "accounts/profile.html", {
            "page_title": "My profile", "page_sub": "Your account and role",
            "active_nav": "profile", "form": ProfileForm(instance=request.user),
            "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Profile"}],
        })

    @method_decorator(sensitive_post_parameters("email"))
    def post(self, request):
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            _audit(request, "update", request.user, new={"email": request.user.email})
            messages.success(request, "Profile updated successfully.")
            return redirect("profile")
        messages.error(request, "Please fix the errors below.")
        return render(request, "accounts/profile.html", {
            "page_title": "My profile", "page_sub": "Your account and role",
            "active_nav": "profile", "form": form,
            "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Profile"}],
        })


class CustomPasswordChangeView(LoginRequiredMixin, auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("profile")

    def form_valid(self, form):
        messages.success(self.request, "Password changed successfully. Use it next sign-in.")
        _audit(self.request, "update", self.request.user, new={"password": "changed"})
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Password change failed. Review the requirements.")
        return super().form_invalid(form)


class UserListView(RoleRequiredMixin, ListView):
    allowed_roles = ["admin"]
    model = User
    template_name = "accounts/user_list.html"
    paginate_by = 15
    context_object_name = "users"

    def get_queryset(self):
        qs = User.objects.select_related("department").order_by("username")
        q = self.request.GET.get("q", "").strip()
        role = self.request.GET.get("role", "")
        status = self.request.GET.get("status", "")
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        if role:
            qs = qs.filter(role=role)
        if status == "active":
            qs = qs.filter(is_active=True)
        elif status == "inactive":
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            "page_title": "Users", "page_sub": "Administrators only — roles and access",
            "active_nav": "users", "q": self.request.GET.get("q", ""),
            "role_f": self.request.GET.get("role", ""), "status_f": self.request.GET.get("status", ""),
            "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Users"}],
        })
        return ctx


class UserCreateView(RoleRequiredMixin, View):
    allowed_roles = ["admin"]

    def get(self, request):
        return render(request, "accounts/user_form.html", {
            "form": AdminUserCreateForm(), "mode": "create",
            "page_title": "Add user", "page_sub": "Assign role and department",
            "active_nav": "users", "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Users", "url": "/users/"}, {"label": "Add"}],
        })

    def post(self, request):
        form = AdminUserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            _audit(request, "create", user, new={"username": user.username, "role": user.role})
            messages.success(request, f"User {user.username} created with role {user.get_role_display()}.")
            return redirect("user_list")
        messages.error(request, "Could not create user. Fix the errors below.")
        return render(request, "accounts/user_form.html", {
            "form": form, "mode": "create",
            "page_title": "Add user", "page_sub": "Assign role and department",
            "active_nav": "users", "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Users", "url": "/users/"}, {"label": "Add"}],
        })


class UserUpdateView(RoleRequiredMixin, View):
    allowed_roles = ["admin"]

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return render(request, "accounts/user_form.html", {
            "form": AdminUserUpdateForm(instance=user), "mode": "edit", "edited": user,
            "page_title": f"Edit {user.username}", "page_sub": "Role, department and status",
            "active_nav": "users", "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Users", "url": "/users/"}, {"label": user.username}],
        })

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        old = {"role": user.role, "is_active": user.is_active, "email": user.email}
        if user.pk == request.user.pk and request.POST.get("is_active") != "on":
            messages.error(request, "You cannot deactivate your own account.")
            return redirect("user_edit", pk=pk)
        form = AdminUserUpdateForm(request.POST, instance=user)
        if form.is_valid():
            if user.pk == request.user.pk and form.cleaned_data["role"] != request.user.role:
                messages.error(request, "You cannot change your own role.")
                return redirect("user_edit", pk=pk)
            user = form.save()
            _audit(request, "update", user, old=old, new={"role": user.role, "is_active": user.is_active})
            messages.success(request, f"User {user.username} updated.")
            return redirect("user_list")
        messages.error(request, "Could not update user. Fix the errors below.")
        return render(request, "accounts/user_form.html", {
            "form": form, "mode": "edit", "edited": user,
            "page_title": f"Edit {user.username}", "page_sub": "Role, department and status",
            "active_nav": "users", "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Users", "url": "/users/"}, {"label": user.username}],
        })


class UserToggleActiveView(RoleRequiredMixin, View):
    allowed_roles = ["admin"]

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user.pk == request.user.pk:
            messages.error(request, "You cannot deactivate your own account.")
            return redirect("user_list")
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        _audit(request, "status_change", user, new={"is_active": user.is_active})
        messages.success(request, f"User {user.username} {'activated' if user.is_active else 'deactivated'}.")
        return redirect("user_list")
