from django.urls import path

from apps.bookings.views import (
    BookClassAPI,
    CancelBookingAPI,
    JoinWaitlistAPI,
    ListBookingsAPI,
    ListWaitlistEntriesAPI,
    WithdrawWaitlistEntryAPI,
)

urlpatterns = [
    path("me", ListBookingsAPI.as_view(), name="my_bookings"),
    path("waitlist/me", ListWaitlistEntriesAPI.as_view(), name="my_waitlist"),
    path("classes/<int:class_id>/book",
         BookClassAPI.as_view(), name="book_class"),
    path("<int:booking_id>/cancel",
         CancelBookingAPI.as_view(), name="cancel_booking"),
    path("classes/<int:class_id>/waitlist/join",
         JoinWaitlistAPI.as_view(), name="join_waitlist"),
    path("classes/<int:class_id>/waitlist/withdraw",
         WithdrawWaitlistEntryAPI.as_view(), name="withdraw_waitlist"),
]
