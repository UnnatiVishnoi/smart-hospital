"""Phase 4 dashboards — real ORM data, role-scoped on the server."""
import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.permissions import visible_equipment_qs, visible_requests_qs
from apps.equipment.models import Equipment
from apps.maintenance.models import PreventiveSchedule, ServiceRequest

OPEN_STATUSES = ["open", "acknowledged", "in_progress", "on_hold", "reopened"]

ROLE_SUBS = {
    "admin": "Full system overview — users, assets, work orders and compliance",
    "manager": "Maintenance operations — assignments, schedules and reports",
    "technician": "My work queue — assigned requests and due preventive tasks",
    "staff": "My department — equipment status and my requests",
}


def _scoped(request):
    eq = visible_equipment_qs(request.user, Equipment.objects.select_related("department", "category"))
    sr = visible_requests_qs(
        request.user, ServiceRequest.objects.select_related("equipment", "equipment__department", "assigned_to")
    )
    if request.user.role == "technician":
        pm = PreventiveSchedule.objects.filter(is_active=True, assigned_to=request.user).select_related("equipment")
    elif request.user.role == "staff" and request.user.department_id:
        pm = PreventiveSchedule.objects.filter(
            is_active=True, equipment__department_id=request.user.department_id
        ).select_related("equipment")
    else:
        pm = PreventiveSchedule.objects.filter(is_active=True).select_related("equipment")
    return eq, sr, pm


@login_required
def dashboard(request):
    eq, sr, pm = _scoped(request)
    today = timezone.localdate()
    week = today + timedelta(days=7)

    total = eq.count()
    operational = eq.filter(status="operational").count()
    under_maint = eq.filter(status__in=["under_maintenance", "breakdown"]).count()
    open_sr = sr.filter(status__in=OPEN_STATUSES).count()
    overdue = pm.filter(next_due_date__lt=today).count()
    upcoming = pm.filter(next_due_date__range=(today, week)).count()

    status_rows = eq.values("status").annotate(n=Count("id"))
    status_map = {r["status"]: r["n"] for r in status_rows}
    six_ago = (today.replace(day=1) - timedelta(days=150)).replace(day=1)
    from datetime import datetime as _dt, time as _tm
    six_ago_dt = timezone.make_aware(_dt.combine(six_ago, _tm.min))
    trend = (
        sr.filter(requested_at__gte=six_ago_dt)
        .annotate(m=TruncMonth("requested_at"))
        .values("m")
        .annotate(n=Count("id"))
        .order_by("m")[:6]
    )

    recent = sr.order_by("-requested_at")[:5]
    upcoming_pm = pm.order_by("next_due_date")[:5]
    if request.user.role in ("admin", "manager") or request.user.is_superuser:
        activity = AuditLog.objects.select_related("actor").order_by("-timestamp")[:4]
    else:
        activity = AuditLog.objects.filter(actor=request.user).order_by("-timestamp")[:4]

    # Time of day for greeting
    from datetime import datetime
    hour = timezone.localtime().hour if hasattr(timezone, 'localtime') else datetime.now().hour
    if hour < 12:
        time_of_day = "morning"
    elif hour < 17:
        time_of_day = "afternoon"
    elif hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    role_summary = ROLE_SUBS.get(request.user.role, "Hospital equipment health")

    kpis = [
        {"label": "Total equipment", "value": total, "delta": "Visible to your role", "tone": "neutral", "icon": "bi-cpu", "band": "neutral"},
        {"label": "Operational", "value": operational, "delta": f"{(operational / total * 100 if total else 0):.1f}% of fleet", "tone": "success", "icon": "bi-activity", "band": "success"},
        {"label": "Needs attention", "value": under_maint, "delta": "Breakdown + maintenance", "tone": "warning", "icon": "bi-tools", "band": "warning"},
        {"label": "Open service requests", "value": open_sr, "delta": "Awaiting resolution", "tone": "danger", "icon": "bi-ticket-detailed", "band": "danger"},
        {"label": "Overdue maintenance", "value": overdue, "delta": "Past due date", "tone": "danger", "icon": "bi-exclamation-triangle", "band": "danger"},
        {"label": "Upcoming (7 days)", "value": upcoming, "delta": "Due within a week", "tone": "info", "icon": "bi-calendar-check", "band": "info"},
    ]
    ctx = {
        "page_title": "Dashboard",
        "page_sub": role_summary,
        "active_nav": "dashboard",
        "is_demo": False,
        "kpis": kpis,
        "recent_requests": recent,
        "upcoming_pm": upcoming_pm,
        "activity": activity,
        "today": today,
        "total": total,
        "operational": operational,
        "under_maint": under_maint,
        "open_sr": open_sr,
        "overdue": overdue,
        "time_of_day": time_of_day,
        "role_summary": role_summary,
        "status_json": json.dumps({
            "labels": ["Operational", "Under maintenance", "Breakdown", "Standby", "Decommissioned"],
            "data": [
                status_map.get("operational", 0),
                status_map.get("under_maintenance", 0),
                status_map.get("breakdown", 0),
                status_map.get("standby", 0),
                status_map.get("decommissioned", 0),
            ],
        }),
        "trend_json": json.dumps({
            "labels": [r["m"].strftime("%b") if r["m"] else "—" for r in trend] or ["No data"],
            "data": [r["n"] for r in trend] or [0],
        }),
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Dashboard"}],
    }
    return render(request, "dashboard/index.html", ctx)


@login_required
def components_preview(request):
    return render(request, "dashboard/components.html", {
        "page_title": "Components", "page_sub": "Reusable UI kit — visual reference",
        "active_nav": "components",
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "UI kit"}],
    })
