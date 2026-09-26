"""Phase 5 — Hospital Equipment Management (ORM only, server-enforced RBAC)."""
import csv
import io
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.permissions import RoleRequiredMixin, role_required, visible_equipment_qs, visible_requests_qs
from apps.equipment.models import Category, Equipment, EquipmentStatusLog
from apps.hospital.models import Department
from apps.inventory.models import Vendor
from .forms import EquipmentForm, suggest_asset_tag

PAGE_SIZE = 12
SORTABLE = {"asset_tag", "name", "purchase_date", "next_pm_date", "status", "criticality"}
OPEN_SR = ["open", "acknowledged", "in_progress", "on_hold", "reopened"]


def _audit(request, action, eq, old=None, new=None):
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        action=action,
        model_name="equipment.Equipment",
        object_id=str(eq.pk),
        old_values=old,
        new_values=new,
        ip_address=request.META.get("REMOTE_ADDR"),
    )


def _log_status(eq, old, new, user, reason=""):
    if (old or "") != (new or ""):
        EquipmentStatusLog.objects.create(
            equipment=eq, old_status=old or "", new_status=new, changed_by=user if user.is_authenticated else None,
            reason=reason[:255],
        )


def _filtered(request):
    base = visible_equipment_qs(
        request.user, Equipment.objects.select_related("category", "department", "vendor")
    )
    p = {
        "q": request.GET.get("q", "").strip(),
        "category": request.GET.get("category", ""),
        "department": request.GET.get("department", ""),
        "status": request.GET.get("status", ""),
        "criticality": request.GET.get("criticality", ""),
        "vendor": request.GET.get("vendor", ""),
        "expiring": request.GET.get("expiring", ""),
        "include_inactive": request.GET.get("inactive", ""),
        "sort": request.GET.get("sort", "asset_tag"),
        "dir": request.GET.get("dir", "asc"),
    }
    qs = base
    if not p["include_inactive"]:
        qs = qs.filter(is_active=True)
    if p["q"]:
        qs = qs.filter(
            Q(asset_tag__icontains=p["q"]) | Q(name__icontains=p["q"]) | Q(serial_no__icontains=p["q"])
            | Q(manufacturer__icontains=p["q"]) | Q(model_no__icontains=p["q"])
        )
    if p["category"]:
        qs = qs.filter(category_id=p["category"])
    if p["department"]:
        qs = qs.filter(department_id=p["department"])
    if p["status"]:
        qs = qs.filter(status=p["status"])
    if p["criticality"]:
        qs = qs.filter(criticality=p["criticality"])
    if p["vendor"]:
        qs = qs.filter(vendor_id=p["vendor"])
    if p["expiring"] in ("30", "90"):
        qs = qs.filter(
            warranty_expiry__gte=date.today(),
            warranty_expiry__lte=date.today() + timedelta(days=int(p["expiring"])),
        )
    sort = p["sort"] if p["sort"] in SORTABLE else "asset_tag"
    if p["dir"] == "desc":
        sort = "-" + sort
    return qs.order_by(sort, "asset_tag"), p


def _filter_options(request):
    cats = Category.objects.order_by("name")
    if request.user.role == "staff" and request.user.department_id:
        depts = Department.objects.filter(pk=request.user.department_id)
    else:
        depts = Department.objects.filter(is_active=True).order_by("name")
    vendors = Vendor.objects.filter(is_active=True).order_by("name")
    return cats, depts, vendors


@login_required
def overview(request):
    eq_all = visible_equipment_qs(request.user, Equipment.objects.all())
    active = eq_all.filter(is_active=True)
    total = active.count()
    operational = active.filter(status="operational").count()
    attention = active.filter(status__in=["breakdown", "under_maintenance"]).count()
    critical = active.filter(criticality="critical").count()
    exp90 = active.filter(
        warranty_expiry__gte=date.today(), warranty_expiry__lte=date.today() + timedelta(days=90)
    ).count()
    standby = active.filter(status__in=["standby", "decommissioned"]).count()
    rows = active.values("status").annotate(n=Count("id"))
    sm = {r["status"]: r["n"] for r in rows}
    dept_rows = (
        active.values("department__name", "department__code")
        .annotate(total=Count("id"), down=Count("id", filter=Q(status__in=["breakdown", "under_maintenance"])))
        .order_by("-total")[:8]
    )
    attention_list = active.filter(status__in=["breakdown", "under_maintenance"]).select_related(
        "category", "department"
    ).order_by("-criticality", "asset_tag")[:6]
    recent = active.select_related("category", "department").order_by("-created_at")[:5]
    kpis = [
        {"label": "Active assets", "value": total, "delta": "In scope for your role", "tone": "neutral", "icon": "bi-cpu"},
        {"label": "Operational", "value": operational, "delta": f"{(operational / total * 100 if total else 0):.1f}% ready", "tone": "success", "icon": "bi-activity"},
        {"label": "Needs attention", "value": attention, "delta": "Breakdown + maintenance", "tone": "danger", "icon": "bi-tools"},
        {"label": "Critical assets", "value": critical, "delta": "Criticality = critical", "tone": "warning", "icon": "bi-exclamation-triangle"},
        {"label": "Warranty ≤ 90 days", "value": exp90, "delta": "Renew / plan AMC", "tone": "info", "icon": "bi-shield-check"},
        {"label": "Standby / retired", "value": standby, "delta": "Not in service", "tone": "neutral", "icon": "bi-pause-circle"},
    ]
    import json
    return render(request, "equipment/overview.html", {
        "page_title": "Equipment overview", "page_sub": "Fleet health, department load and attention queue",
        "active_nav": "equipment", "kpis": kpis,
        "status_json": json.dumps({"labels": ["Operational", "Maintenance", "Breakdown", "Standby", "Retired"],
            "data": [sm.get("operational", 0), sm.get("under_maintenance", 0), sm.get("breakdown", 0),
                     sm.get("standby", 0), sm.get("decommissioned", 0)]}),
        "dept_rows": dept_rows, "attention_list": attention_list, "recent": recent,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Equipment"}],
    })


@login_required
def inventory(request):
    qs, p = _filtered(request)
    paginator = Paginator(qs, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    cats, depts, vendors = _filter_options(request)
    can_manage = request.user.is_superuser or request.user.role in ("admin", "manager")
    return render(request, "equipment/list.html", {
        "page_title": "Equipment inventory", "page_sub": "Live registry from MySQL — search, filter, sort, export",
        "active_nav": "equipment", "page": page, "p": p, "paginator": paginator,
        "categories": cats, "departments": depts, "vendors": vendors,
        "can_manage": can_manage,
        "can_export": can_manage,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Equipment", "url": "/equipment/"}, {"label": "Inventory"}],
    })


@login_required
def department_view(request):
    base = visible_equipment_qs(request.user, Equipment.objects.filter(is_active=True))
    if request.user.role == "staff" and request.user.department_id:
        depts = Department.objects.filter(pk=request.user.department_id)
    else:
        depts = Department.objects.filter(is_active=True).order_by("name")
    cards = []
    for d in depts:
        q = base.filter(department=d)
        cards.append({
            "dept": d,
            "total": q.count(),
            "operational": q.filter(status="operational").count(),
            "attention": q.filter(status__in=["breakdown", "under_maintenance"]).count(),
            "critical": q.filter(criticality="critical").count(),
            "items": q.select_related("category").order_by("asset_tag")[:6],
        })
    return render(request, "equipment/departments.html", {
        "page_title": "Department-wise equipment", "page_sub": "Distribution and ward-level readiness",
        "active_nav": "equipment", "cards": cards,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Equipment", "url": "/equipment/"}, {"label": "Departments"}],
    })


@login_required
def detail(request, pk):
    eq = get_object_or_404(
        visible_equipment_qs(request.user, Equipment.objects.select_related("category", "department", "vendor")),
        pk=pk,
    )
    sr_base = eq.service_requests.select_related("assigned_to", "requested_by").order_by("-requested_at")
    if not (request.user.is_superuser or request.user.role in ("admin", "manager")):
        sr_base = visible_requests_qs(request.user, sr_base)
    records = eq.maintenance_records.select_related("technician").order_by("-completed_at")[:10]
    history = eq.status_history.select_related("changed_by")[:15]
    blockers = {
        "open_sr": eq.service_requests.filter(status__in=OPEN_SR).count(),
        "active_pm": eq.pm_schedules.filter(is_active=True).count(),
    }
    can_manage = request.user.is_superuser or request.user.role in ("admin", "manager")
    can_archive = request.user.is_superuser or request.user.role == "admin"
    return render(request, "equipment/detail.html", {
        "page_title": eq.asset_tag, "page_sub": eq.name,
        "active_nav": "equipment", "eq": eq,
        "service_requests": sr_base[:10], "records": records, "history": history,
        "blockers": blockers, "can_manage": can_manage, "can_archive": can_archive,
        "today": date.today(),
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Equipment", "url": "/equipment/"}, {"label": eq.asset_tag}],
    })


@role_required(["admin", "manager"])
def add(request):
    initial = {}
    if request.GET.get("category") and request.GET.get("department"):
        try:
            from apps.equipment.models import Category as C
            from apps.hospital.models import Department as D
            initial["asset_tag"] = suggest_asset_tag(
                C.objects.get(pk=request.GET["category"]).name,
                D.objects.get(pk=request.GET["department"]).code,
            )
            initial["category"] = request.GET["category"]
            initial["department"] = request.GET["department"]
        except Exception:
            pass
    if request.method == "POST":
        form = EquipmentForm(request.POST, request.FILES)
        if form.is_valid():
            eq = form.save()
            _log_status(eq, "", eq.status, request.user, "Registered")
            _audit(request, "create", eq, new={"asset_tag": eq.asset_tag, "serial_no": eq.serial_no})
            messages.success(request, f"Equipment {eq.asset_tag} registered.")
            return redirect("equipment_detail", pk=eq.pk)
        messages.error(request, "Could not save equipment. Fix the errors below.")
    else:
        form = EquipmentForm(initial=initial)
    return render(request, "equipment/form.html", {
        "page_title": "Add equipment", "page_sub": "Asset ID must be unique; serial numbers cannot repeat",
        "active_nav": "equipment", "form": form, "mode": "add",
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Equipment", "url": "/equipment/"}, {"label": "Add"}],
    })


@role_required(["admin", "manager"])
def edit(request, pk):
    eq = get_object_or_404(Equipment.objects.select_related("category", "department"), pk=pk)
    if not eq.is_active:
        messages.error(request, "Archived equipment cannot be edited. Restore it first.")
        return redirect("equipment_detail", pk=pk)
    old_status = eq.status
    if request.method == "POST":
        form = EquipmentForm(request.POST, request.FILES, instance=eq)
        if form.is_valid():
            eq = form.save()
            _log_status(eq, old_status, eq.status, request.user, "Edited")
            _audit(request, "update", eq, old={"status": old_status}, new={"status": eq.status})
            messages.success(request, f"Equipment {eq.asset_tag} updated.")
            return redirect("equipment_detail", pk=pk)
        messages.error(request, "Could not update equipment. Fix the errors below.")
    else:
        form = EquipmentForm(instance=eq)
    return render(request, "equipment/form.html", {
        "page_title": f"Edit {eq.asset_tag}", "page_sub": eq.name,
        "active_nav": "equipment", "form": form, "mode": "edit", "eq": eq,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Equipment", "url": "/equipment/"}, {"label": eq.asset_tag}],
    })


@role_required(["admin"])
def archive(request, pk):
    eq = get_object_or_404(Equipment, pk=pk)
    open_sr = eq.service_requests.filter(status__in=OPEN_SR).count()
    active_pm = eq.pm_schedules.filter(is_active=True).count()
    if request.method == "POST":
        if open_sr or active_pm:
            messages.error(request, f"Cannot archive: {open_sr} open request(s), {active_pm} active schedule(s). Resolve them first.")
            return redirect("equipment_detail", pk=pk)
        eq.is_active = False
        old = eq.status
        eq.status = "decommissioned"
        eq.save(update_fields=["is_active", "status"])
        _log_status(eq, old, eq.status, request.user, "Archived")
        _audit(request, "status_change", eq, old={"is_active": True}, new={"is_active": False})
        messages.success(request, f"Equipment {eq.asset_tag} archived (soft delete — history retained).")
        return redirect("equipment_list")
    return render(request, "equipment/confirm_archive.html", {
        "page_title": f"Archive {eq.asset_tag}", "page_sub": "Soft delete — history is retained",
        "active_nav": "equipment", "eq": eq, "open_sr": open_sr, "active_pm": active_pm,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Equipment", "url": "/equipment/"}, {"label": eq.asset_tag}],
    })


@role_required(["admin"])
def restore(request, pk):
    eq = get_object_or_404(Equipment, pk=pk)
    if request.method == "POST":
        eq.is_active = True
        old = eq.status
        eq.status = "operational"
        eq.save(update_fields=["is_active", "status"])
        _log_status(eq, old, eq.status, request.user, "Restored")
        _audit(request, "status_change", eq, old={"is_active": False}, new={"is_active": True})
        messages.success(request, f"Equipment {eq.asset_tag} restored to service.")
        return redirect("equipment_detail", pk=pk)
    return redirect("equipment_detail", pk=pk)


@role_required(["admin", "manager"])
def export_csv(request):
    qs, p = _filtered(request)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["asset_tag", "name", "category", "department", "manufacturer", "model_no", "serial_no",
                "status", "criticality", "purchase_date", "warranty_expiry", "location",
                "vendor", "last_service", "next_pm", "is_active"])
    for e in qs.iterator(chunk_size=500):
        w.writerow([e.asset_tag, e.name, e.category.name, e.department.code, e.manufacturer, e.model_no,
                    e.serial_no, e.status, e.criticality, e.purchase_date, e.warranty_expiry or "",
                    e.location_detail, e.vendor.name if e.vendor else "", e.last_service_date or "",
                    e.next_pm_date or "", e.is_active])
    resp = HttpResponse(buf.getvalue(), content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="equipment_inventory.csv"'
    return resp


@login_required
def qr_png(request, pk):
    eq = get_object_or_404(visible_equipment_qs(request.user, Equipment.objects.all()), pk=pk)
    try:
        import qrcode
    except ImportError:
        return HttpResponse("QR unavailable — install qrcode.", status=503, content_type="text/plain")
    url = request.build_absolute_uri(eq.get_absolute_url() if hasattr(eq, "get_absolute_url") else f"/equipment/{eq.pk}/")
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


@login_required
def suggest_id(request):
    """JSON helper for the Add form: ?category=<id>&department=<id> -> {asset_tag}."""
    from django.http import JsonResponse
    try:
        cat = Category.objects.get(pk=request.GET.get("category"))
        from apps.hospital.models import Department as D
        dept = D.objects.get(pk=request.GET.get("department"))
        return JsonResponse({"asset_tag": suggest_asset_tag(cat.name, dept.code)})
    except Exception:
        return JsonResponse({"error": "Select category and department first."}, status=400)
