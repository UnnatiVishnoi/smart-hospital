"""Phase 6 — Service Request & Breakdown Management (ORM, server-enforced workflow)."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.permissions import role_required, visible_equipment_qs, visible_requests_qs
from apps.equipment.models import Equipment, EquipmentStatusLog
from apps.hospital.models import Department
from apps.inventory.models import PartUsage, SparePart
from apps.notifications.models import Notification
from .forms import AssignForm, CloseForm, ProgressNoteForm, ResolveReportForm, ServiceRequestForm
from .models import MaintenanceRecord, ServiceActivity, ServiceRequest
from .workflow import allowed_targets, can_transition, is_manager

PAGE_SIZE = 12


def _audit(request, action, sr, old=None, new=None):
    AuditLog.objects.create(
        actor=request.user if request.user.is_authenticated else None, action=action,
        model_name="maintenance.ServiceRequest", object_id=str(sr.pk),
        old_values=old, new_values=new, ip_address=request.META.get("REMOTE_ADDR"),
    )


def _notify(recipients, title, message, ntype, sr):
    seen = set()
    for u in recipients:
        if not u or not u.is_active or u.pk in seen:
            continue
        seen.add(u.pk)
        Notification.objects.create(
            recipient=u, title=title, message=message, type=ntype,
            service_request=sr, equipment=sr.equipment,
        )


def _managers():
    from django.contrib.auth import get_user_model

    return list(get_user_model().objects.filter(role__in=["admin", "manager"], is_active=True))


def _set_equipment_status(sr, new_status, user, reason=""):
    eq = sr.equipment
    if eq.status != new_status:
        old = eq.status
        eq.status = new_status
        eq.save(update_fields=["status"])
        EquipmentStatusLog.objects.create(
            equipment=eq, old_status=old, new_status=new_status,
            changed_by=user if user.is_authenticated else None, reason=reason[:255],
        )


def _next_ticket():
    year = timezone.now().year
    n = ServiceRequest.objects.filter(ticket_no__startswith=f"SR-{year}-").count() + 1
    while ServiceRequest.objects.filter(ticket_no=f"SR-{year}-{n:04d}").exists():
        n += 1
    return f"SR-{year}-{n:04d}"


def _scoped_sr(request):
    return visible_requests_qs(
        request.user,
        ServiceRequest.objects.select_related("equipment", "equipment__department", "requested_by", "assigned_to"),
    )


def _actions_for(user, sr):
    """Which POST actions the template may offer. Server re-checks everything."""
    acts = []
    for t in allowed_targets(sr.status):
        ok, _ = can_transition(user, sr, t)
        if ok:
            acts.append(t)
    return acts


@login_required
def request_list(request):
    qs = _scoped_sr(request)
    f = {
        "q": request.GET.get("q", "").strip(),
        "status": request.GET.get("status", ""),
        "priority": request.GET.get("priority", ""),
        "department": request.GET.get("department", ""),
        "date": request.GET.get("date", ""),
        "overdue": request.GET.get("overdue", ""),
        "mine": request.GET.get("mine", ""),
    }
    if f["q"]:
        qs = qs.filter(Q(ticket_no__icontains=f["q"]) | Q(equipment__asset_tag__icontains=f["q"])
                       | Q(equipment__name__icontains=f["q"]) | Q(description__icontains=f["q"]))
    if f["status"]:
        qs = qs.filter(status=f["status"])
    if f["priority"]:
        qs = qs.filter(priority=f["priority"])
    if f["department"]:
        qs = qs.filter(equipment__department_id=f["department"])
    if f["date"]:
        try:
            y, m, d = map(int, f["date"].split("-"))
            from datetime import date as dcls, datetime as _dt, time as _tm, timedelta as _td
            day = dcls(y, m, d)
            start = timezone.make_aware(_dt.combine(day, _tm.min))
            qs = qs.filter(requested_at__gte=start, requested_at__lt=start + _td(days=1))
        except ValueError:
            pass
    if f["overdue"]:
        qs = qs.filter(deadline__lt=timezone.now()).exclude(status__in=["resolved", "closed"])
    if f["mine"]:
        if request.user.role == "technician":
            qs = qs.filter(assigned_to=request.user)
        else:
            qs = qs.filter(requested_by=request.user)
    if request.user.role == "staff" and request.user.department_id:
        depts = Department.objects.filter(pk=request.user.department_id)
    else:
        depts = Department.objects.filter(is_active=True).order_by("name")
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    open_n = _scoped_sr(request).exclude(status__in=["resolved", "closed"]).count()
    overdue_n = _scoped_sr(request).filter(deadline__lt=timezone.now()).exclude(status__in=["resolved", "closed"]).count()
    return render(request, "maintenance/list.html", {
        "page_title": "Service requests", "page_sub": "Breakdowns and work orders in your scope",
        "active_nav": "requests", "page": page, "f": f, "departments": depts,
        "open_n": open_n, "overdue_n": overdue_n,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Service requests"}],
    })


@login_required
def request_create(request):
    equip_qs = visible_equipment_qs(
        request.user, Equipment.objects.filter(is_active=True).select_related("department", "category"))
    if request.method == "POST":
        form = ServiceRequestForm(request.POST, request.FILES)
        form.fields["equipment"].queryset = equip_qs.order_by("asset_tag")
        if form.is_valid():
            norm = " ".join(form.cleaned_data["description"].split()).lower()
            dup = ServiceRequest.objects.filter(
                requested_by=request.user, equipment=form.cleaned_data["equipment"],
                requested_at__gte=timezone.now() - timedelta(minutes=10),
            )
            for cand in dup:
                if " ".join(cand.description.split()).lower() == norm:
                    messages.warning(request, f"Duplicate blocked — this matches {cand.ticket_no} raised minutes ago.")
                    return redirect("request_detail", pk=cand.pk)
            with transaction.atomic():
                sr = form.save(commit=False)
                sr.ticket_no = _next_ticket()
                sr.requested_by = request.user
                sr.status = "open"
                sr.save()
                ServiceActivity.objects.create(service_request=sr, actor=request.user, action="created",
                                               new_status="open", note=f"Reported: {sr.equipment.asset_tag}")
                if sr.equipment.status in ("operational", "standby"):
                    _set_equipment_status(sr, "breakdown", request.user, f"{sr.ticket_no} reported")
                _notify(_managers(), f"New breakdown {sr.ticket_no}",
                        f"{sr.equipment.asset_tag} · {sr.get_priority_display()} · {sr.equipment.department.code}",
                        "breakdown", sr)
                _audit(request, "create", sr, new={"ticket": sr.ticket_no, "equipment": sr.equipment.asset_tag})
            messages.success(request, f"Fault reported as {sr.ticket_no}.")
            return redirect("request_detail", pk=sr.pk)
        messages.error(request, "Could not submit. Fix the errors below.")
    else:
        form = ServiceRequestForm()
        form.fields["equipment"].queryset = equip_qs.order_by("asset_tag")
    return render(request, "maintenance/create.html", {
        "page_title": "Report a fault", "page_sub": "Duplicates within 10 minutes are blocked automatically",
        "active_nav": "requests", "form": form,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Requests", "url": "/requests/"}, {"label": "Report"}],
    })


@login_required
def request_detail(request, pk):
    sr = get_object_or_404(_scoped_sr(request), pk=pk)
    activities = sr.activities.select_related("actor").order_by("created_at")
    record = getattr(sr, "record", None)
    parts = record.part_usages.select_related("spare_part") if record else []
    from django.contrib.auth import get_user_model

    techs = get_user_model().objects.filter(role="technician", is_active=True).order_by("username")
    assign_form = AssignForm(technicians=techs, initial={
        "assigned_to": str(sr.assigned_to_id or ""),
        "deadline": sr.deadline.strftime("%Y-%m-%dT%H:%M") if sr.deadline else "",
        "internal_remarks": sr.internal_remarks,
    })
    return render(request, "maintenance/detail.html", {
        "page_title": sr.ticket_no, "page_sub": f"{sr.equipment.asset_tag} · {sr.equipment.name}",
        "active_nav": "requests", "sr": sr, "activities": activities, "record": record, "parts": parts,
        "actions": _actions_for(request.user, sr),
        "assign_form": assign_form, "note_form": ProgressNoteForm(), "close_form": CloseForm(),
        "can_assign": is_manager(request.user),
        "show_remarks": is_manager(request.user),
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Requests", "url": "/requests/"}, {"label": sr.ticket_no}],
    })


@role_required(["admin", "manager"])
def request_assign(request, pk):
    sr = get_object_or_404(ServiceRequest.objects.select_related("equipment"), pk=pk)
    from django.contrib.auth import get_user_model

    techs = get_user_model().objects.filter(role="technician", is_active=True).order_by("username")
    if request.method != "POST":
        return redirect("request_detail", pk=pk)
    form = AssignForm(request.POST, technicians=techs)
    if not form.is_valid():
        messages.error(request, "Assignment failed — fix the highlighted fields.")
        return redirect("request_detail", pk=pk)
    tech = get_object_or_404(get_user_model(), pk=form.cleaned_data["assigned_to"])
    if tech.role != "technician" or not tech.is_active:
        messages.error(request, "Assignee must be an active technician.")
        return redirect("request_detail", pk=pk)
    with transaction.atomic():
        old_status, old_tech = sr.status, sr.assigned_to
        sr.assigned_to = tech
        sr.deadline = form.cleaned_data["deadline"]
        sr.internal_remarks = form.cleaned_data["internal_remarks"]
        if sr.status in ("open", "reopened", "on_hold"):
            sr.status = "acknowledged"
            sr.acknowledged_at = sr.acknowledged_at or timezone.now()
        sr.save()
        ServiceActivity.objects.create(service_request=sr, actor=request.user, action="assigned",
                                       old_status=old_status, new_status=sr.status,
                                       note=f"{old_tech or 'Unassigned'} → {tech.username}")
        _set_equipment_status(sr, "under_maintenance", request.user, f"{sr.ticket_no} assigned")
        _notify([tech], f"Assigned {sr.ticket_no}", f"{sr.equipment.asset_tag} · due {sr.deadline or 'no deadline'}",
                "assignment", sr)
        if sr.requested_by:
            _notify([sr.requested_by], f"{sr.ticket_no} assigned", f"Technician {tech.username} is on it.", "assignment", sr)
        _audit(request, "assign", sr, old={"status": old_status}, new={"status": sr.status, "tech": tech.username})
    messages.success(request, f"{sr.ticket_no} assigned to {tech.username}.")
    return redirect("request_detail", pk=pk)


@login_required
def request_transition(request, pk, target):
    sr = get_object_or_404(_scoped_sr(request), pk=pk)
    if request.method != "POST":
        return redirect("request_detail", pk=pk)
    if target == "resolved":
        return redirect("request_resolve", pk=pk)
    ok, reason = can_transition(request.user, sr, target)
    if not ok:
        messages.error(request, reason)
        return redirect("request_detail", pk=pk)
    with transaction.atomic():
        old = sr.status
        now = timezone.now()
        sr.status = target
        if target == "acknowledged" and not sr.acknowledged_at:
            sr.acknowledged_at = now
        if target == "in_progress" and not sr.in_progress_at:
            sr.in_progress_at = now
        if target == "open":  # unassign
            sr.assigned_to = None
        if target == "closed":
            sr.closed_at = now
        if target == "reopened":
            sr.resolved_at = None
            sr.closed_at = None
            _set_equipment_status(sr, "breakdown", request.user, f"{sr.ticket_no} reopened")
        if target == "in_progress":
            _set_equipment_status(sr, "under_maintenance", request.user, f"{sr.ticket_no} started")
        sr.save()
        ServiceActivity.objects.create(service_request=sr, actor=request.user, action="status_change",
                                       old_status=old, new_status=target)
        others = [u for u in [sr.requested_by, sr.assigned_to] if u and u != request.user]
        _notify(others, f"{sr.ticket_no}: {old} → {target}", sr.equipment.asset_tag, "system", sr)
        _audit(request, "status_change", sr, old={"status": old}, new={"status": target})
    messages.success(request, f"{sr.ticket_no} moved to {target.replace('_', ' ')}.")
    return redirect("request_detail", pk=pk)


@login_required
def request_note(request, pk):
    sr = get_object_or_404(_scoped_sr(request), pk=pk)
    allowed = (is_manager(request.user) or (sr.requested_by_id == request.user.pk)
               or (sr.assigned_to_id == request.user.pk))
    if request.method != "POST" or not allowed:
        messages.error(request, "You cannot comment on this request.")
        return redirect("request_detail", pk=pk)
    form = ProgressNoteForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Note needs at least 5 characters.")
        return redirect("request_detail", pk=pk)
    ServiceActivity.objects.create(service_request=sr, actor=request.user, action="note", note=form.cleaned_data["note"])
    others = [u for u in [sr.requested_by, sr.assigned_to] if u and u != request.user]
    _notify(others, f"Update on {sr.ticket_no}", form.cleaned_data["note"][:120], "system", sr)
    messages.success(request, "Progress note added to the timeline.")
    return redirect("request_detail", pk=pk)


@login_required
def request_resolve(request, pk):
    sr = get_object_or_404(_scoped_sr(request), pk=pk)
    ok, reason = can_transition(request.user, sr, "resolved")
    if not ok:
        messages.error(request, reason)
        return redirect("request_detail", pk=pk)
    if hasattr(sr, "record") and sr.record:
        messages.info(request, "A report already exists for this request.")
        return redirect("request_detail", pk=pk)
    if request.method == "POST":
        form = ResolveReportForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    now = timezone.now()
                    started = sr.in_progress_at or sr.acknowledged_at or sr.requested_at
                    tech = sr.assigned_to or request.user
                    record = MaintenanceRecord.objects.create(
                        equipment=sr.equipment, service_request=sr, technician=tech,
                        maintenance_type="corrective",
                        inspection_findings=form.cleaned_data["inspection_findings"],
                        work_done=form.cleaned_data["work_done"],
                        cost=form.cleaned_data["cost"] or 0,
                        started_at=started, completed_at=now,
                        downtime_hours=form.cleaned_data["downtime_hours"],
                        next_action=form.cleaned_data["next_action"],
                    )
                    for part, qty in form.part_lines():
                        locked = SparePart.objects.select_for_update().get(pk=part.pk)
                        if locked.quantity_in_stock < qty:
                            raise ValueError(f"Only {locked.quantity_in_stock} × {locked.part_no} in stock.")
                        locked.quantity_in_stock -= qty
                        locked.save(update_fields=["quantity_in_stock"])
                        PartUsage.objects.create(maintenance_record=record, spare_part=locked,
                                                 quantity=qty, unit_cost_at_use=locked.unit_price)
                    old = sr.status
                    sr.status = "resolved"
                    sr.resolved_at = now
                    if sr.requested_at:
                        sr.downtime_hours = round((now - sr.requested_at).total_seconds() / 3600, 2)
                    sr.save()
                    ServiceActivity.objects.create(
                        service_request=sr, actor=request.user, action="report",
                        old_status=old, new_status="resolved",
                        note=f"Report: {form.cleaned_data['work_done'][:200]}")
                    sr.equipment.last_service_date = now.date()
                    sr.equipment.save(update_fields=["last_service_date"])
                    _set_equipment_status(sr, "operational", request.user, f"{sr.ticket_no} resolved")
                    if sr.requested_by and sr.requested_by != request.user:
                        _notify([sr.requested_by], f"{sr.ticket_no} resolved",
                                f"{sr.equipment.asset_tag} is back in service.", "resolved", sr)
                    _audit(request, "status_change", sr, old={"status": old}, new={"status": "resolved"})
                messages.success(request, f"{sr.ticket_no} resolved and maintenance history recorded.")
                return redirect("request_detail", pk=pk)
            except ValueError as e:
                messages.error(request, str(e))
        else:
            messages.error(request, "Report incomplete — check findings, actions and parts.")
    else:
        form = ResolveReportForm()
    return render(request, "maintenance/resolve.html", {
        "page_title": f"Resolve {sr.ticket_no}", "page_sub": "Report is mandatory — findings, actions, parts, cost",
        "active_nav": "requests", "sr": sr, "form": form,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Requests", "url": "/requests/"},
                        {"label": sr.ticket_no, "url": f"/requests/{sr.pk}/"}, {"label": "Resolve"}],
    })


@login_required
def request_close(request, pk):
    sr = get_object_or_404(_scoped_sr(request), pk=pk)
    if request.method != "POST":
        return redirect("request_detail", pk=pk)
    ok, reason = can_transition(request.user, sr, "closed")
    if not ok:
        messages.error(request, reason)
        return redirect("request_detail", pk=pk)
    form = CloseForm(request.POST)
    rating = form.cleaned_data.get("satisfaction_rating") if form.is_valid() else None
    with transaction.atomic():
        old = sr.status
        sr.status = "closed"
        sr.closed_at = timezone.now()
        if rating:
            sr.satisfaction_rating = rating
        sr.save()
        ServiceActivity.objects.create(service_request=sr, actor=request.user, action="status_change",
                                       old_status=old, new_status="closed",
                                       note=f"Closed{f' · rating {rating}/5' if rating else ''}")
        _audit(request, "status_change", sr, old={"status": old}, new={"status": "closed"})
    messages.success(request, f"{sr.ticket_no} closed.")
    return redirect("request_detail", pk=pk)


@login_required
def request_reopen(request, pk):
    sr = get_object_or_404(_scoped_sr(request), pk=pk)
    if request.method != "POST":
        return redirect("request_detail", pk=pk)
    ok, reason = can_transition(request.user, sr, "reopened")
    if not ok:
        messages.error(request, reason)
        return redirect("request_detail", pk=pk)
    with transaction.atomic():
        old = sr.status
        sr.status = "reopened"
        sr.resolved_at = None
        sr.closed_at = None
        sr.save()
        ServiceActivity.objects.create(service_request=sr, actor=request.user, action="status_change",
                                       old_status=old, new_status="reopened", note="Reopened — needs attention")
        _set_equipment_status(sr, "breakdown", request.user, f"{sr.ticket_no} reopened")
        _notify(_managers(), f"{sr.ticket_no} reopened", sr.equipment.asset_tag, "breakdown", sr)
        _audit(request, "status_change", sr, old={"status": old}, new={"status": "reopened"})
    messages.success(request, f"{sr.ticket_no} reopened.")
    return redirect("request_detail", pk=pk)
