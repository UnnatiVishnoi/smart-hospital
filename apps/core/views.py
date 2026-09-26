import time
from django.db import connection
from django.http import JsonResponse
from django.utils.timezone import now


def health_check(request):
    started = time.perf_counter()
    db_ok = False
    db_error = None
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        db_ok = True
    except Exception as exc:  # noqa: BLE001 — surfaced in payload
        db_error = str(exc)[:300]
    payload = {
        "status": "ok" if db_ok else "degraded",
        "db": "up" if db_ok else "down",
        "engine": connection.vendor,
        "time": now().isoformat(),
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if db_error:
        payload["db_error"] = db_error
    return JsonResponse(payload, status=200 if db_ok else 503)


def forbidden_view(request, exception=None):
    from django.shortcuts import render

    return render(request, "403.html", status=403)


def not_found_view(request, exception=None):
    from django.shortcuts import render

    return render(request, "404.html", status=404)


def server_error_view(request):
    from django.shortcuts import render

    return render(request, "500.html", status=500)
