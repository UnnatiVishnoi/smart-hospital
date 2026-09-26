from django.urls import path
from . import views

urlpatterns = [
    path("assistant/", views.workspace, name="assistant"),
    path("assistant/new/", views.new_conversation, name="assistant_new"),
    path("assistant/<int:pk>/", views.workspace, name="assistant_detail"),
    path("assistant/<int:pk>/ask/", views.ask, name="assistant_ask"),
    path("assistant/<int:pk>/archive/", views.archive_conversation, name="assistant_archive"),
    path("assistant/clear/", views.clear_chat, name="assistant_clear"),
]
