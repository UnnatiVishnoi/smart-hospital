from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render


@login_required
def notification_list(request):
    qs = request.user.notifications.select_related("service_request", "equipment", "schedule").order_by("-created_at")
    f = {"type": request.GET.get("type", ""), "unread": request.GET.get("unread", "")}
    if f["type"]:
        qs = qs.filter(type=f["type"])
    if f["unread"]:
        qs = qs.filter(is_read=False)
    page = Paginator(qs, 15).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {
        "page_title": "Notifications", "page_sub": "Assignments, PM reminders, warranty and status updates",
        "active_nav": "notifications", "page": page, "f": f,
        "unread_n": request.user.notifications.filter(is_read=False).count(),
        "breadcrumbs": [{"label": "Home", "url": "/"}, {"label": "Notifications"}],
    })


@login_required
def notification_read(request, pk):
    from django.shortcuts import get_object_or_404

    n = get_object_or_404(request.user.notifications, pk=pk)
    if request.method == "POST":
        n.is_read = True
        n.save(update_fields=["is_read"])
        if n.service_request_id:
            return redirect("request_detail", pk=n.service_request_id)
        if n.schedule_id:
            return redirect("pm_detail", pk=n.schedule_id)
        if n.equipment_id:
            return redirect("equipment_detail", pk=n.equipment_id)
    return redirect("notification_list")


@login_required
def notification_read_all(request):
    if request.method == "POST":
        request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect("notification_list")
