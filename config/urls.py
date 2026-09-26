from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from apps.core.views import health_check

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health_check, name="health"),
    path("", include("apps.accounts.urls")),
    path("", include("apps.dashboard.urls")),
    path("", include("apps.equipment.urls")),
    path("", include("apps.maintenance.urls")),
    path("", include("apps.notifications.urls")),
    path("", include("apps.knowledge.urls")),
    path("", include("apps.chatbot.urls")),
    path("", include("apps.reports.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "apps.core.views.forbidden_view"
handler404 = "apps.core.views.not_found_view"
handler500 = "apps.core.views.server_error_view"
