from django.urls import path
from . import pm_views, views

urlpatterns = [
    path("requests/", views.request_list, name="request_list"),
    path("requests/report/", views.request_create, name="request_create"),
    path("requests/<int:pk>/", views.request_detail, name="request_detail"),
    path("requests/<int:pk>/assign/", views.request_assign, name="request_assign"),
    path("requests/<int:pk>/transition/<str:target>/", views.request_transition, name="request_transition"),
    path("requests/<int:pk>/note/", views.request_note, name="request_note"),
    path("requests/<int:pk>/resolve/", views.request_resolve, name="request_resolve"),
    path("requests/<int:pk>/close/", views.request_close, name="request_close"),
    path("requests/<int:pk>/reopen/", views.request_reopen, name="request_reopen"),
    path("pm/", pm_views.pm_dashboard, name="pm_dashboard"),
    path("pm/schedules/", pm_views.pm_list, name="pm_list"),
    path("pm/schedules/new/", pm_views.pm_create, name="pm_create"),
    path("pm/schedules/<int:pk>/", pm_views.pm_detail, name="pm_detail"),
    path("pm/schedules/<int:pk>/edit/", pm_views.pm_edit, name="pm_edit"),
    path("pm/schedules/<int:pk>/toggle/", pm_views.pm_toggle, name="pm_toggle"),
    path("pm/schedules/<int:pk>/complete/", pm_views.pm_complete, name="pm_complete"),
]
