from django.urls import path

from apps.bookings.views import (
    BookClassAPI,
    CancelBookingAPI,
    JoinWaitlistAPI,
    WithdrawWaitlistEntryAPI,
)

urlpatterns = [
    path("classes/<int:class_id>/book",
         BookClassAPI.as_view(), name="book_class"),
    path("<int:booking_id>/cancel",
         CancelBookingAPI.as_view(), name="cancel_booking"),
    path("classes/<int:class_id>/waitlist/join",
         JoinWaitlistAPI.as_view(), name="join_waitlist"),
    path("classes/<int:class_id>/waitlist/withdraw",
         WithdrawWaitlistEntryAPI.as_view(), name="withdraw_waitlist"),
]
