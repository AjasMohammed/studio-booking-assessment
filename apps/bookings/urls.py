from django.urls import path

from apps.bookings.views import BookClassAPI

urlpatterns = [
    path("classes/<int:class_id>/book", BookClassAPI.as_view(), name="book_class"),
]
