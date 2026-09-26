from django.urls import path
from . import views

urlpatterns = [
    path("manuals/", views.manual_list, name="manual_list"),
    path("manuals/upload/", views.manual_upload, name="manual_upload"),
    path("manuals/<int:pk>/", views.manual_detail, name="manual_detail"),
    path("manuals/<int:pk>/reindex/", views.manual_reindex, name="manual_reindex"),
    path("manuals/<int:pk>/delete/", views.manual_delete, name="manual_delete"),
]
