"""Manual library: upload (managers), PyMuPDF indexing, scoped browsing."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.models import AuditLog
from apps.core.permissions import role_required, visible_equipment_qs
from apps.equipment.models import Equipment
from .forms import ManualUploadForm
from .models import EquipmentManual
from .rag import index_manual


def _visible_manuals(user):
    """Managers see everything; others see manuals for visible equipment + global manuals."""
    if user.is_superuser or user.role in ("admin", "manager"):
        return EquipmentManual.objects.all()
    from django.db.models import Q

    eq_ids = visible_equipment_qs(user, Equipment.objects.all()).values("pk")
    cat_ids = Equipment.objects.filter(pk__in=eq_ids).values("category_id")
    return EquipmentManual.objects.filter(
        Q(equipment_id__in=eq_ids) | Q(category_id__in=cat_ids)
        | Q(equipment__isnull=True, category__isnull=True))


@login_required
def manual_list(request):
    qs = _visible_manuals(request.user).select_related("equipment", "category").order_by("-created_at")
    q = request.GET.get("q", "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(title__icontains=q) | Q(manufacturer__icontains=q) | Q(model__icontains=q))
    page = Paginator(qs, 12).get_page(request.GET.get("page"))
    return render(request, "knowledge/list.html", {
        "page_title": "Manual library", "page_sub": "Approved equipment documentation for the assistant",
        "active_nav": "manuals", "page": page, "q": q,
        "can_manage": request.user.is_superuser or request.user.role in ("admin", "manager"),
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Manuals"}],
    })


@role_required(["admin", "manager"])
def manual_upload(request):
    if request.method == "POST":
        form = ManualUploadForm(request.POST, request.FILES)
        if form.is_valid():
            manual = form.save(commit=False)
            manual.file_hash = form.cleaned_data["_file_hash"]
            manual.uploaded_by = request.user
            manual.save()
            try:
                n = index_manual(manual)
                messages.success(request, f"“{manual.title}” indexed: {n} passages from {manual.page_count} pages.")
            except ValueError as e:
                manual.is_indexed = False
                manual.save(update_fields=["is_indexed"])
                messages.warning(request, f"Uploaded, but indexing failed: {e}")
            AuditLog.objects.create(actor=request.user, action="upload", model_name="knowledge.EquipmentManual",
                                    object_id=str(manual.pk), ip_address=request.META.get("REMOTE_ADDR"))
            return redirect("manual_detail", pk=manual.pk)
        messages.error(request, "Upload failed. Fix the errors below.")
    else:
        form = ManualUploadForm()
    return render(request, "knowledge/upload.html", {
        "page_title": "Upload manual", "page_sub": "PDF up to 20 MB — text is extracted with PyMuPDF",
        "active_nav": "manuals", "form": form,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Manuals", "url": "/manuals/"}, {"label": "Upload"}],
    })


@login_required
def manual_detail(request, pk):
    manual = get_object_or_404(_visible_manuals(request.user).select_related("equipment", "category"), pk=pk)
    chunks = manual.chunks.order_by("chunk_index")[:12]
    return render(request, "knowledge/detail.html", {
        "page_title": manual.title, "page_sub": f"{manual.chunks.count()} indexed passages",
        "active_nav": "manuals", "manual": manual, "chunks": chunks,
        "can_manage": request.user.is_superuser or request.user.role in ("admin", "manager"),
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Manuals", "url": "/manuals/"},
                        {"label": manual.title}],
    })


@role_required(["admin", "manager"])
def manual_reindex(request, pk):
    manual = get_object_or_404(EquipmentManual, pk=pk)
    if request.method == "POST":
        try:
            n = index_manual(manual)
            messages.success(request, f"Re-indexed: {n} passages from {manual.page_count} pages.")
        except ValueError as e:
            messages.error(request, f"Re-index failed: {e}")
    return redirect("manual_detail", pk=pk)


@role_required(["admin", "manager"])
def manual_delete(request, pk):
    manual = get_object_or_404(EquipmentManual, pk=pk)
    if request.method == "POST":
        title = manual.title
        manual.file.delete(save=False)
        manual.delete()
        messages.success(request, f"“{title}” and its indexed passages were deleted.")
        return redirect("manual_list")
    return render(request, "knowledge/confirm_delete.html", {
        "page_title": f"Delete {manual.title}", "active_nav": "manuals", "manual": manual,
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Manuals", "url": "/manuals/"},
                        {"label": "Delete"}],
    })
