"""Reporting views — one filter set drives every number, chart and export."""
import csv
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.core.permissions import visible_equipment_qs
from apps.equipment.models import Category, Equipment
from apps.hospital.models import Department
from apps.inventory.models import PartUsage
from apps.maintenance.models import MaintenanceRecord
from .metrics import DONE_STATUSES, _day_gte, _day_lt, build_report, describe_insights, scoped_sets


def parse_filters(request):
    today = timezone.localdate()
    f = {"department": request.GET.get("department", ""), "category": request.GET.get("category", ""),
         "status": request.GET.get("status", "")}
    try:
        y, m, d = map(int, request.GET.get("from", "").split("-"))
        from datetime import date as dcls
        f["date_from"] = dcls(y, m, d)
    except ValueError:
        f["date_from"] = today - timedelta(days=90)
    try:
        y, m, d = map(int, request.GET.get("to", "").split("-"))
        from datetime import date as dcls
        f["date_to"] = dcls(y, m, d)
    except ValueError:
        f["date_to"] = today
    if f["date_from"] > f["date_to"]:
        f["date_from"], f["date_to"] = f["date_to"], f["date_from"]
    return f


def filter_options(user):
    if user.role == "staff" and user.department_id:
        depts = Department.objects.filter(pk=user.department_id)
    else:
        depts = Department.objects.filter(is_active=True).order_by("name")
    return depts, Category.objects.order_by("name")


@login_required
def overview(request):
    f = parse_filters(request)
    m = build_report(request.user, f)
    depts, cats = filter_options(request.user)
    import json
    sm = {r["status"]: r["n"] for r in m["status_rows"]}
    ctx = {
        "page_title": "Analytics & reports", "page_sub": "One filtered dataset behind every number",
        "active_nav": "reports", "f": f, "m": m, "departments": depts, "categories": cats,
        "insights": describe_insights(m),
        "status_json": json.dumps({"labels": ["Operational", "Maintenance", "Breakdown", "Standby", "Retired"],
            "data": [sm.get("operational", 0), sm.get("under_maintenance", 0), sm.get("breakdown", 0),
                     sm.get("standby", 0), sm.get("decommissioned", 0)]}),
        "trend_json": json.dumps({"labels": m["months"] or ["No data"], "sr": m["m_sr"] or [0],
                                          "done": m["m_done"] or [0]}),
        "cost_json": json.dumps({"labels": m["months"] or ["No data"], "cost": m["m_cost"] or [0]}),
        "dept_json": json.dumps({"labels": [d["equipment__department__code"] or "—" for d in m["by_dept"]] or ["No data"],
                                         "data": [d["n"] for d in m["by_dept"]] or [0]}),
        "kpis": [
            {"label": "Total equipment", "value": m["total"], "delta": f"{m['operational']} operational", "tone": "neutral", "icon": "bi-cpu"},
            {"label": "Open requests", "value": m["open_sr"], "delta": f"{m['resolved_sr']} resolved in range", "tone": "danger" if m["open_sr"] else "success", "icon": "bi-ticket-detailed"},
            {"label": "PM compliance", "value": f"{m['pm_rate']}%" if m["pm_rate"] is not None else "n/a",
             "delta": f"{m['overdue_pm']} overdue", "tone": "success" if (m["pm_rate"] or 0) >= 90 else "warning", "icon": "bi-calendar-check"},
            {"label": "Downtime", "value": f"{m['downtime']} h",
             "delta": f"Avg repair {m['avg_repair']} h" if m["avg_repair"] is not None else "No resolutions yet",
             "tone": "info", "icon": "bi-clock-history"},
            {"label": "Expenditure", "value": f"₹{m['expenditure']:,.0f}",
             "delta": f"Labour ₹{m['labor_cost']:,.0f} · parts ₹{m['parts_cost']:,.0f}", "tone": "neutral", "icon": "bi-cash-coin"},
            {"label": "Breakdowns", "value": m["breakdowns"], "delta": f"{len(m['months'])} month(s) in range", "tone": "warning", "icon": "bi-activity"},
        ],
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Reports"}],
    }
    return render(request, "reports/dashboard.html", ctx)


@login_required
def requests_csv(request):
    f = parse_filters(request)
    _, sr, _, _ = scoped_sets(request.user, f)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="service_requests.csv"'
    w = csv.writer(resp)
    w.writerow(["ticket", "asset", "department", "status", "priority", "requested", "resolved",
                "downtime_h", "assignee", "rating"])
    for r in sr.order_by("-requested_at").iterator(chunk_size=500):
        w.writerow([r.ticket_no, r.equipment.asset_tag, r.equipment.department.code, r.status,
                    r.priority, r.requested_at, r.resolved_at or "", r.downtime_hours or "",
                    r.assigned_to or "", r.satisfaction_rating or ""])
    return resp


@login_required
def costs_csv(request):
    f = parse_filters(request)
    eq, _, rec, _ = scoped_sets(request.user, f)
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="maintenance_costs.csv"'
    w = csv.writer(resp)
    w.writerow(["asset", "name", "department", "jobs", "labour", "parts", "total"])
    for row in _cost_by_equipment(eq, rec):
        w.writerow([row["asset_tag"], row["name"], row["dept"], row["jobs"],
                    row["labour"], row["parts"], row["total"]])
    return resp


def _cost_by_equipment(eq, rec):
    ids = list(rec.values_list("pk", flat=True))
    parts = {}
    if ids:
        for r in PartUsage.objects.filter(maintenance_record_id__in=ids).values(
                "maintenance_record__equipment_id").annotate(s=Sum(F("quantity") * F("unit_cost_at_use"))):
            parts[r["maintenance_record__equipment_id"]] = float(r["s"])
    labour = {r["equipment_id"]: float(r["s"]) for r in
              rec.values("equipment_id").annotate(s=Sum("cost"))}
    jobs = {r["equipment_id"]: r["n"] for r in rec.values("equipment_id").annotate(n=Count("pk"))}
    rows = []
    for e in eq.select_related("department"):
        lab, par = labour.get(e.pk, 0), parts.get(e.pk, 0)
        if lab or par or jobs.get(e.pk):
            rows.append({"asset_tag": e.asset_tag, "name": e.name, "dept": e.department.code,
                         "jobs": jobs.get(e.pk, 0), "labour": round(lab, 2), "parts": round(par, 2),
                         "total": round(lab + par, 2), "pk": e.pk})
    rows.sort(key=lambda r: r["total"], reverse=True)
    return rows


@login_required
def cost_report(request):
    f = parse_filters(request)
    eq, _, rec, _ = scoped_sets(request.user, f)
    depts, cats = filter_options(request.user)
    rows = _cost_by_equipment(eq, rec)
    cat_rows = [{"label": r["equipment__category__name"] or "—", "total": float(r["s"]), "n": r["n"]}
                for r in rec.values("equipment__category__name").annotate(
                    s=Sum("cost"), n=Count("pk")).order_by("-s")]
    return render(request, "reports/cost.html", {
        "page_title": "Maintenance cost report", "page_sub": "Labour + parts from completed jobs in range",
        "active_nav": "reports", "f": f, "rows": rows, "cat_rows": cat_rows,
        "total": round(sum(r["total"] for r in rows), 2),
        "departments": depts, "categories": cats,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Reports", "url": "/reports/"},
                        {"label": "Costs"}],
    })


@login_required
def workload(request):
    f = parse_filters(request)
    _, sr, rec, _ = scoped_sets(request.user, f)
    from django.contrib.auth import get_user_model

    techs = get_user_model().objects.filter(role="technician", is_active=True).order_by("username")
    rows = []
    for t in techs:
        assigned_open = sr.filter(assigned_to=t).exclude(status__in=DONE_STATUSES).count()
        mine = sr.filter(assigned_to=t, status__in=DONE_STATUSES, resolved_at__isnull=False)
        if f.get("date_from"):
            mine = mine.filter(resolved_at__gte=_day_gte(f["date_from"]))
        if f.get("date_to"):
            mine = mine.filter(resolved_at__lt=_day_lt(f["date_to"]))
        deltas = [(r["resolved_at"] - r["requested_at"]).total_seconds() / 3600 for r in
                  mine.values("requested_at", "resolved_at")]
        pm_done = rec.filter(technician=t, schedule__isnull=False).count()
        cost = rec.filter(technician=t).aggregate(s=Sum("cost"))["s"] or 0
        if assigned_open or mine.exists() or pm_done:
            rows.append({"tech": t, "open": assigned_open, "resolved": mine.count(),
                         "avg_h": round(sum(deltas) / len(deltas), 2) if deltas else None,
                         "pm_done": pm_done, "cost": float(cost)})
    depts, cats = filter_options(request.user)
    return render(request, "reports/workload.html", {
        "page_title": "Technician workload", "page_sub": "Assignments, resolutions and PM output in range",
        "active_nav": "reports", "f": f, "rows": rows, "departments": depts, "categories": cats,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Reports", "url": "/reports/"},
                        {"label": "Workload"}],
    })


@login_required
def equipment_history(request):
    eq_scope = visible_equipment_qs(request.user, Equipment.objects.filter(
        is_active=True)).order_by("asset_tag")
    sel = get_object_or_404(eq_scope, pk=request.GET.get("equipment")) if request.GET.get("equipment") else None
    ctx = {"page_title": "Service history", "page_sub": "Per-asset requests, jobs, downtime and spend",
           "active_nav": "reports", "equipment_list": eq_scope[:300], "sel": sel,
           "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Reports", "url": "/reports/"},
                           {"label": "History"}]}
    if sel:
        from apps.core.permissions import visible_requests_qs
        reqs = visible_requests_qs(request.user, sel.service_requests.all()).order_by("-requested_at")
        recs = sel.maintenance_records.select_related("technician").order_by("-completed_at")
        ids = list(recs.values_list("pk", flat=True))
        parts = float(PartUsage.objects.filter(maintenance_record_id__in=ids).aggregate(
            s=Sum(F("quantity") * F("unit_cost_at_use")))["s"] or 0) if ids else 0
        labour = float(recs.aggregate(s=Sum("cost"))["s"] or 0)
        down = float(reqs.filter(downtime_hours__isnull=False).aggregate(s=Sum("downtime_hours"))["s"] or 0)
        ctx.update({"reqs": reqs, "recs": recs, "jobs": recs.count(),
                    "labour": labour, "parts": parts, "total": round(labour + parts, 2), "downtime": down})
    return render(request, "reports/history.html", ctx)


@login_required
def print_view(request):
    f = parse_filters(request)
    return render(request, "reports/print.html", {
        "page_title": "Maintenance summary", "active_nav": "reports",
        "f": f, "m": build_report(request.user, f), "insights": describe_insights(build_report(request.user, f)),
        "printed_at": timezone.now(), "printed_by": request.user,
    })
