def ui_defaults(request):
    ctx = {
        "DEMO_MODE": False,
        "PRODUCT_NAME": "MediServe",
        "PRODUCT_SUB": "Smart Hospital Servicing",
        "active_nav": getattr(request.resolver_match, "url_name", "") if request.resolver_match else "",
    }
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        qs = user.notifications.order_by("-created_at")
        ctx["notif_unread"] = qs.filter(is_read=False).count()
        ctx["notif_recent"] = list(qs[:4])
    else:
        ctx["notif_unread"] = 0
        ctx["notif_recent"] = []
    return ctx
