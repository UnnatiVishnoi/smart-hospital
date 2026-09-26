from django.urls import path
from . import views

urlpatterns = [
    path("equipment/", views.overview, name="equipment_overview"),
    path("equipment/inventory/", views.inventory, name="equipment_list"),
    path("equipment/departments/", views.department_view, name="equipment_departments"),
    path("equipment/add/", views.add, name="equipment_add"),
    path("equipment/export.csv", views.export_csv, name="equipment_export"),
    path("equipment/suggest-id/", views.suggest_id, name="equipment_suggest_id"),
    path("equipment/<int:pk>/", views.detail, name="equipment_detail"),
    path("equipment/<int:pk>/edit/", views.edit, name="equipment_edit"),
    path("equipment/<int:pk>/archive/", views.archive, name="equipment_archive"),
    path("equipment/<int:pk>/restore/", views.restore, name="equipment_restore"),
    path("equipment/<int:pk>/qr.png", views.qr_png, name="equipment_qr"),
]
