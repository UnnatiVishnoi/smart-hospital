from django.urls import path
from . import views

urlpatterns = [
    path("reports/", views.overview, name="reports"),
    path("reports/requests.csv", views.requests_csv, name="reports_requests_csv"),
    path("reports/costs.csv", views.costs_csv, name="reports_costs_csv"),
    path("reports/costs/", views.cost_report, name="reports_cost"),
    path("reports/workload/", views.workload, name="reports_workload"),
    path("reports/history/", views.equipment_history, name="reports_history"),
    path("reports/print/", views.print_view, name="reports_print"),
]
