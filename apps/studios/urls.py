from django.urls import path

from apps.studios.views import CreateSession, CreateStudio, ListStudiosAPI

urlpatterns = [
    path("create", CreateStudio.as_view(), name="create_studio"),
    path("list", ListStudiosAPI.as_view(), name="list_studios"),
    path("<int:studio_id>/session/create",
         CreateSession.as_view(), name="create_class_session"),
]
