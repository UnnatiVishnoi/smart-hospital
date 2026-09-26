"""Analytics engine — every number derives from one filtered dataset.

Filter dimensions (applied uniformly to KPIs, charts and tables):
  date_from/date_to — service-request requested_at, record completed_at, PM due window
  department / category / equipment status — via the equipment join

Precise metric definitions (also shown in the UI footnote):
- total_equipment: active equipment in scope
- operational / non_operational: status == operational vs anything else
- open_sr: requests with status in OPEN set; resolved_sr: status resolved/closed
- pm_rate: distinct schedules with an execution completed in range ÷ distinct
  schedules due in range (next due inside range, or overdue before range end)
- overdue_pm: active schedules with next due before range end
- downtime_hours: SUM(request.downtime_hours) for requests resolved in range
- avg_repair_hours: MEAN(resolved_at - requested_at) for requests resolved in range
- expenditure: SUM(record.cost) + SUM(part qty × unit cost) for records completed in range
- breakdowns: count of requests created in range
- warranty buckets: expired / expiring ≤90d / valid, measured at range end
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.utils import timezone

from apps.core.permissions import visible_equipment_qs, visible_requests_qs
from apps.equipment.models import Equipment
from apps.inventory.models import PartUsage
from apps.maintenance.models import MaintenanceRecord, PreventiveSchedule, ServiceRequest

OPEN_STATUSES = ["open", "acknowledged", "in_progress", "on_hold", "reopened"]
DONE_STATUSES = ["resolved", "closed"]


def _day_gte(d):
    """Aware start-of-day (avoids MySQL __date lookups, which need tz tables)."""
    return timezone.make_aware(datetime.combine(d, time.min))


def _day_lt(d):
    return _day_gte(d + timedelta(days=1))


def scoped_sets(user, f):
    """Return (equipment, requests, records, schedules) for one filtered dataset."""
    eq = visible_equipment_qs(user, Equipment.objects.filter(is_active=True).select_related(
        "department", "category"))
    if f.get("department"):
        eq = eq.filter(department_id=f["department"])
    if f.get("category"):
        eq = eq.filter(category_id=f["category"])
    if f.get("status"):
        eq = eq.filter(status=f["status"])
    eq_ids = eq.values("pk")

    sr = visible_requests_qs(user, ServiceRequest.objects.select_related(
        "equipment", "equipment__department", "assigned_to")).filter(equipment_id__in=eq_ids)
    if f.get("date_from"):
        sr = sr.filter(requested_at__gte=_day_gte(f["date_from"]))
    if f.get("date_to"):
        sr = sr.filter(requested_at__lt=_day_lt(f["date_to"]))

    rec = MaintenanceRecord.objects.select_related("equipment", "technician").filter(
        equipment_id__in=eq_ids)
    if f.get("date_from"):
        rec = rec.filter(completed_at__gte=_day_gte(f["date_from"]))
    if f.get("date_to"):
        rec = rec.filter(completed_at__lt=_day_lt(f["date_to"]))

    pm = PreventiveSchedule.objects.filter(is_active=True, equipment_id__in=eq_ids)
    if user.role == "technician" and not user.is_superuser:
        pm = pm.filter(assigned_to=user)
    return eq, sr, rec, pm


def _fnum(v):
    return float(v) if isinstance(v, Decimal) else (v or 0)


def build_report(user, f):
    eq, sr, rec, pm = scoped_sets(user, f)
    end = f.get("date_to")
    total = eq.count()
    operational = eq.filter(status="operational").count()
    open_sr = sr.filter(status__in=OPEN_STATUSES).count()
    resolved_sr = sr.filter(status__in=DONE_STATUSES).count()

    # PM compliance
    due_ids = set(pm.filter(next_due_date__range=(f["date_from"], f["date_to"])).values_list("pk", flat=True)) \
        if f.get("date_from") and f.get("date_to") else set()
    if end:
        due_ids |= set(pm.filter(next_due_date__lt=end).values_list("pk", flat=True))
    done_ids = set(rec.filter(schedule__isnull=False).values_list("schedule_id", flat=True))
    due_ids.discard(None)
    pm_rate = (len(due_ids & done_ids) / len(due_ids) * 100) if due_ids else None
    overdue_pm = pm.filter(next_due_date__lt=end).count() if end else 0

    # Downtime + repair time from requests resolved in range
    res_qs = sr.filter(status__in=DONE_STATUSES, resolved_at__isnull=False)
    if f.get("date_from"):
        res_qs = res_qs.filter(resolved_at__gte=_day_gte(f["date_from"]))
    if f.get("date_to"):
        res_qs = res_qs.filter(resolved_at__lt=_day_lt(f["date_to"]))
    downtime = _fnum(res_qs.aggregate(s=Sum("downtime_hours"))["s"])
    deltas = [(r["resolved_at"] - r["requested_at"]).total_seconds() / 3600
              for r in res_qs.values("requested_at", "resolved_at") if r["resolved_at"] and r["requested_at"]]
    avg_repair = round(sum(deltas) / len(deltas), 2) if deltas else None

    # Expenditure
    rec_ids = list(rec.values_list("pk", flat=True))
    parts_cost = _fnum(PartUsage.objects.filter(maintenance_record_id__in=rec_ids).aggregate(
        s=Sum(F("quantity") * F("unit_cost_at_use")))["s"]) if rec_ids else 0
    labor_cost = _fnum(rec.aggregate(s=Sum("cost"))["s"])
    expenditure = round(labor_cost + parts_cost, 2)

    # Breakdowns by equipment / department
    by_eq = list(sr.values("equipment__asset_tag", "equipment__name").annotate(
        n=Count("pk")).order_by("-n")[:8])
    by_dept = list(sr.values("equipment__department__code", "equipment__department__name").annotate(
        n=Count("pk")).order_by("-n"))
    dept_downtime = {r["equipment__department__code"]: _fnum(r["s"]) for r in
                     res_qs.values("equipment__department__code").annotate(s=Sum("downtime_hours"))}

    # Monthly trend across the range (cap 12 months)
    months, m_sr, m_done, m_cost = [], [], [], []
    if f.get("date_from") and f.get("date_to"):
        cur = f["date_from"].replace(day=1)
        while cur <= f["date_to"] and len(months) < 12:
            months.append(cur.strftime("%b %y"))
            nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
            m_sr.append(sr.filter(requested_at__gte=_day_gte(cur), requested_at__lt=_day_gte(nxt)).count())
            done_recs = rec.filter(completed_at__gte=_day_gte(cur), completed_at__lt=_day_gte(nxt))
            m_done.append(done_recs.count())
            ids = list(done_recs.values_list("pk", flat=True))
            pc = _fnum(PartUsage.objects.filter(maintenance_record_id__in=ids).aggregate(
                s=Sum(F("quantity") * F("unit_cost_at_use")))["s"]) if ids else 0
            m_cost.append(round(_fnum(done_recs.aggregate(s=Sum("cost"))["s"]) + pc, 2))
            cur = nxt

    # Warranty at range end
    wq = eq.filter(warranty_expiry__isnull=False)
    expired = wq.filter(warranty_expiry__lt=end).count() if end else 0
    expiring = wq.filter(warranty_expiry__gte=end, warranty_expiry__lte=end + timedelta(days=90)).count() if end else 0
    warranty_list = list(wq.filter(warranty_expiry__lte=end + timedelta(days=90)).order_by(
        "warranty_expiry").values("asset_tag", "name", "warranty_expiry",
                                  "department__code")[:10]) if end else []

    # Status mix for doughnut
    status_rows = list(eq.values("status").annotate(n=Count("pk")))

    return {
        "total": total, "operational": operational, "non_operational": total - operational,
        "open_sr": open_sr, "resolved_sr": resolved_sr,
        "pm_rate": round(pm_rate, 1) if pm_rate is not None else None,
        "pm_due_n": len(due_ids), "overdue_pm": overdue_pm,
        "downtime": round(downtime, 2), "avg_repair": avg_repair,
        "expenditure": expenditure, "labor_cost": round(labor_cost, 2), "parts_cost": round(parts_cost, 2),
        "breakdowns": sr.count(), "by_eq": by_eq, "by_dept": by_dept, "dept_downtime": dept_downtime,
        "months": months, "m_sr": m_sr, "m_done": m_done, "m_cost": m_cost,
        "expired": expired, "expiring": expiring, "warranty_list": warranty_list,
        "status_rows": status_rows,
    }


def describe_insights(m):
    """Descriptive historical patterns only — never predictions."""
    out = []
    if m["by_eq"]:
        top = m["by_eq"][0]
        out.append(f"Highest breakdown count: {top['equipment__asset_tag']} "
                   f"({top['equipment__name']}) with {top['n']} request(s) in range.")
        repeaters = [r for r in m["by_eq"] if r["n"] > 1]
        if repeaters:
            out.append(f"{len(repeaters)} asset(s) broke down more than once — candidates for root-cause review.")
    if m["by_dept"]:
        top = m["by_dept"][0]
        out.append(f"Most requests came from {top['equipment__department__code']} ({top['n']}).")
    if m["dept_downtime"]:
        code = max(m["dept_downtime"], key=m["dept_downtime"].get)
        out.append(f"Highest recorded downtime: {code} ({m['dept_downtime'][code]:.1f} h).")
    if m["pm_rate"] is not None:
        out.append(f"PM compliance was {m['pm_rate']}% for schedules due in range.")
    elif m["pm_due_n"] == 0:
        out.append("No preventive schedules were due in range — compliance not applicable.")
    if m["overdue_pm"]:
        out.append(f"{m['overdue_pm']} schedule(s) are overdue as of range end.")
    if m["expenditure"] and m["by_eq"]:
        out.append(f"Total maintenance spend in range: ₹{m['expenditure']:,.2f} "
                   f"(labour ₹{m['labor_cost']:,.2f}, parts ₹{m['parts_cost']:,.2f}).")
    if not out:
        out.append("No records in this filtered dataset yet — widen the date range or clear filters.")
    return out
