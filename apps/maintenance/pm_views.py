"""Phase 7 — Preventive Maintenance Scheduling (ORM, server-enforced RBAC)."""
import calendar as calmod
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.permissions import role_required, visible_equipment_qs
from apps.equipment.models import Equipment
from apps.notifications.models import Notification
from .models import MaintenanceRecord, PreventiveSchedule
from .pm_forms import CompleteForm, ScheduleForm

PAGE_SIZE = 12


def _scoped_pm(request):
    base = PreventiveSchedule.objects.select_related("equipment", "equipment__department", "assigned_to")
    u = request.user
    if u.is_superuser or u.role in ("admin", "manager"):
        return base
    if u.role == "technician":
        return base.filter(assigned_to=u)
    if u.department_id:
        return base.filter(equipment__department_id=u.department_id)
    return base.none()


def _audit(request, action, sched, old=None, new=None):
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None, action=action,
        model_name="maintenance.PreventiveSchedule", object_id=str(sched.pk),
        old_values=old, new_values=new, ip_address=request.META.get("REMOTE_ADDR"),
    )


def _notify_managers(title, message, ntype, sched):
    from django.contrib.auth import get_user_model

    mgrs = get_user_model().objects.filter(role__in=["admin", "manager"], is_active=True)
    for m in mgrs:
        Notification.objects.create(recipient=m, title=title, message=message, type=ntype,
                                    equipment=sched.equipment, schedule=sched)


@login_required
def pm_dashboard(request):
    qs = _scoped_pm(request).filter(is_active=True)
    today = timezone.localdate()
    week = today + timedelta(days=7)
    due_today = qs.filter(next_due_date=today)
    upcoming = qs.filter(next_due_date__gt=today, next_due_date__lte=week)
    overdue = qs.filter(next_due_date__lt=today)
    total = qs.count()
    compliant = total - overdue.count()
    rate = round(compliant / total * 100, 1) if total else 100.0
    done30 = MaintenanceRecord.objects.filter(
        schedule__in=qs, completed_at__gte=timezone.now() - timedelta(days=30)).count()
    attention_eq = visible_equipment_qs(request.user, Equipment.objects.filter(
        is_active=True, status__in=["breakdown", "under_maintenance"])).select_related(
        "department")[:6]
    # calendar month
    try:
        ym = request.GET.get("month", today.strftime("%Y-%m"))
        y, m = map(int, ym.split("-"))
        cur = date(y, m, 1)
    except ValueError:
        cur = today.replace(day=1)
    month_sched = qs.filter(next_due_date__year=cur.year, next_due_date__month=cur.month)
    by_day = {}
    for s in month_sched:
        by_day.setdefault(s.next_due_date.day, []).append(s)
    weeks = []
    for wk in calmod.Calendar(firstweekday=0).monthdayscalendar(cur.year, cur.month):
        weeks.append([{"day": d, "items": by_day.get(d, [])} if d else None for d in wk])
    prev_m = (cur.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    next_m = (date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)).strftime("%Y-%m")
    kpis = [
        {"label": "Due today", "value": due_today.count(), "delta": cur.strftime("%b %d"), "tone": "warning", "icon": "bi-calendar-event"},
        {"label": "Upcoming (7 days)", "value": upcoming.count(), "delta": "Plan technicians", "tone": "info", "icon": "bi-calendar-check"},
        {"label": "Overdue", "value": overdue.count(), "delta": "Needs immediate action", "tone": "danger", "icon": "bi-exclamation-triangle"},
        {"label": "Completed (30 days)", "value": done30, "delta": "Executions logged", "tone": "success", "icon": "bi-check-circle"},
        {"label": "Compliance rate", "value": f"{rate}%", "delta": f"{compliant}/{total} on track", "tone": "success" if rate >= 90 else "warning", "icon": "bi-graph-up"},
        {"label": "Assets in attention", "value": visible_equipment_qs(request.user, Equipment.objects.filter(is_active=True, status__in=['breakdown', 'under_maintenance'])).count(), "delta": "Breakdown + maintenance", "tone": "danger", "icon": "bi-tools"},
    ]
    return render(request, "pm/dashboard.html", {
        "page_title": "Preventive maintenance", "page_sub": "Due work, compliance and service calendar",
        "active_nav": "pm", "kpis": kpis,
        "due_today": due_today[:8], "overdue": overdue.order_by("next_due_date")[:8],
        "upcoming_list": upcoming.order_by("next_due_date")[:8],
        "attention_eq": attention_eq, "weeks": weeks, "cur": cur, "prev_m": prev_m, "next_m": next_m,
        "today": today,
        "can_manage": request.user.is_superuser or request.user.role in ("admin", "manager"),
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Preventive care"}],
    })


@login_required
def pm_list(request):
    qs = _scoped_pm(request)
    f = {"q": request.GET.get("q", "").strip(), "state": request.GET.get("state", ""),
         "tech": request.GET.get("tech", ""), "dept": request.GET.get("dept", ""),
         "mtype": request.GET.get("mtype", ""), "inactive": request.GET.get("inactive", "")}
    today = timezone.localdate()
    if not f["inactive"]:
        qs = qs.filter(is_active=True)
    if f["q"]:
        qs = qs.filter(Q(title__icontains=f["q"]) | Q(equipment__asset_tag__icontains=f["q"])
                       | Q(equipment__name__icontains=f["q"]))
    if f["state"] == "overdue":
        qs = qs.filter(next_due_date__lt=today, is_active=True)
    elif f["state"] == "today":
        qs = qs.filter(next_due_date=today)
    elif f["state"] == "upcoming":
        qs = qs.filter(next_due_date__gt=today, next_due_date__lte=today + timedelta(days=7))
    if f["tech"]:
        qs = qs.filter(assigned_to_id=f["tech"])
    if f["dept"]:
        qs = qs.filter(equipment__department_id=f["dept"])
    if f["mtype"]:
        qs = qs.filter(maintenance_type=f["mtype"])
    qs = qs.order_by("next_due_date")
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    from django.contrib.auth import get_user_model
    techs = get_user_model().objects.filter(role="technician", is_active=True).order_by("username")
    if request.user.role == "staff" and request.user.department_id:
        from apps.hospital.models import Department
        depts = Department.objects.filter(pk=request.user.department_id)
    else:
        from apps.hospital.models import Department
        depts = Department.objects.filter(is_active=True).order_by("name")
    return render(request, "pm/list.html", {
        "page_title": "Maintenance schedules", "page_sub": "Recurring and one-time plans",
        "active_nav": "pm", "page": page, "f": f, "techs": techs, "departments": depts, "today": today,
        "can_manage": request.user.is_superuser or request.user.role in ("admin", "manager"),
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Preventive care", "url": "/pm/"}, {"label": "Schedules"}],
    })


@login_required
def pm_detail(request, pk):
    sched = get_object_or_404(_scoped_pm(request), pk=pk)
    executions = sched.executions.select_related("technician").order_by("-completed_at")[:10]
    can_complete = (request.user.is_superuser or request.user.role in ("admin", "manager")
                    or (sched.assigned_to_id == request.user.pk))
    return render(request, "pm/detail.html", {
        "page_title": sched.title, "page_sub": f"{sched.equipment.asset_tag} · next due {sched.next_due_date}",
        "active_nav": "pm", "sched": sched, "executions": executions,
        "can_manage": request.user.is_superuser or request.user.role in ("admin", "manager"),
        "can_complete": can_complete and sched.is_active,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Preventive care", "url": "/pm/"},
                        {"label": sched.title}],
    })


@role_required(["admin", "manager"])
def pm_create(request):
    equip_qs = Equipment.objects.filter(is_active=True).order_by("asset_tag")
    if request.method == "POST":
        form = ScheduleForm(request.POST)
        form.fields["equipment"].queryset = equip_qs
        if form.is_valid():
            sched = form.save(commit=False)
            sched.created_by = request.user
            sched.save()
            _audit(request, "create", sched, new={"title": sched.title, "due": str(sched.next_due_date)})
            messages.success(request, f"Schedule “{sched.title}” created for {sched.equipment.asset_tag}.")
            return redirect("pm_detail", pk=sched.pk)
        messages.error(request, "Could not create schedule. Fix the errors below.")
    else:
        form = ScheduleForm()
        form.fields["equipment"].queryset = equip_qs
    return render(request, "pm/form.html", {
        "page_title": "New maintenance schedule", "page_sub": "Recurring or one-time, with checklist",
        "active_nav": "pm", "form": form, "mode": "create",
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Preventive care", "url": "/pm/"},
                        {"label": "New"}],
    })


@role_required(["admin", "manager"])
def pm_edit(request, pk):
    sched = get_object_or_404(PreventiveSchedule.objects.all(), pk=pk)
    equip_qs = Equipment.objects.filter(is_active=True).order_by("asset_tag")
    if request.method == "POST":
        form = ScheduleForm(request.POST, instance=sched)
        form.fields["equipment"].queryset = equip_qs
        if form.is_valid():
            form.save()
            _audit(request, "update", sched, new={"title": sched.title})
            messages.success(request, "Schedule updated.")
            return redirect("pm_detail", pk=pk)
        messages.error(request, "Could not update. Fix the errors below.")
    else:
        form = ScheduleForm(instance=sched)
        form.fields["equipment"].queryset = equip_qs
    return render(request, "pm/form.html", {
        "page_title": f"Edit {sched.title}", "page_sub": sched.equipment.asset_tag,
        "active_nav": "pm", "form": form, "mode": "edit", "sched": sched,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Preventive care", "url": "/pm/"},
                        {"label": sched.title}],
    })


@role_required(["admin", "manager"])
def pm_toggle(request, pk):
    sched = get_object_or_404(PreventiveSchedule.objects.all(), pk=pk)
    if request.method == "POST":
        sched.is_active = not sched.is_active
        sched.save(update_fields=["is_active"])
        _audit(request, "status_change", sched, new={"is_active": sched.is_active})
        messages.success(request, f"Schedule {'activated' if sched.is_active else 'paused'}.")
    return redirect("pm_detail", pk=pk)


@login_required
def pm_complete(request, pk):
    sched = get_object_or_404(_scoped_pm(request), pk=pk)
    allowed = (request.user.is_superuser or request.user.role in ("admin", "manager")
               or sched.assigned_to_id == request.user.pk)
    if not allowed or not sched.is_active:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    if request.method == "POST":
        form = CompleteForm(request.POST, checklist=sched.checklist or [])
        if form.is_valid():
            from django.db import transaction
            with transaction.atomic():
                cd = form.cleaned_data["completion_date"]
                aware = timezone.make_aware(datetime(cd.year, cd.month, cd.day, 17, 0))
                started = timezone.make_aware(datetime(cd.year, cd.month, cd.day, 9, 0))
                record = MaintenanceRecord.objects.create(
                    equipment=sched.equipment, schedule=sched, technician=request.user,
                    maintenance_type=sched.maintenance_type,
                    inspection_findings=form.cleaned_data["inspection_findings"],
                    work_done=form.cleaned_data["work_done"],
                    cost=form.cleaned_data["cost"] or 0,
                    started_at=started, completed_at=aware,
                    checklist_results=form.checklist_results(),
                )
                sched.last_done_date = cd
                nxt = sched.next_after_completion(cd)
                if nxt is None:
                    sched.is_active = False
                else:
                    sched.next_due_date = nxt
                sched.save()
                eq = sched.equipment
                if not eq.last_service_date or eq.last_service_date < cd:
                    eq.last_service_date = cd
                    eq.save(update_fields=["last_service_date"])
                _notify_managers(f"PM completed: {sched.title}",
                                 f"{sched.equipment.asset_tag} done by {request.user.username}", "system", sched)
                _audit(request, "update", sched, new={"last_done": str(cd), "record": record.pk})
            if nxt is None:
                messages.success(request, "One-time task completed and closed.")
            else:
                messages.success(request, f"Completion recorded. Next due {nxt} (completion date + interval).")
            return redirect("pm_detail", pk=pk)
        messages.error(request, "Completion incomplete — all required checklist steps must be ticked.")
    else:
        form = CompleteForm(checklist=sched.checklist or [])
    return render(request, "pm/complete.html", {
        "page_title": f"Complete: {sched.title}", "page_sub": f"Late completion restarts the interval from today, no backlog",
        "active_nav": "pm", "form": form, "sched": sched,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Preventive care", "url": "/pm/"},
                        {"label": sched.title}, {"label": "Complete"}],
    })
