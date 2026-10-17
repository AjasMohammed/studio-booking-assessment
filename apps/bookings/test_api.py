from datetime import timedelta

from django.test import TestCase
from django.urls import URLResolver, get_resolver, reverse
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate
from rest_framework_simplejwt.tokens import RefreshToken

from apps.bookings.models import Booking, IdempotencyRecord
from apps.bookings.views import BookClassAPI
from apps.studios.models import CreditMovement
from apps.testing import DomainFixtures


class BookingAPITests(DomainFixtures, TestCase):
    def post(self, user=None, key="request-1", class_id=None, token=None):
        headers = {}
        if key is not None:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        if token is not None:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        request = APIRequestFactory().post("/booking", {}, format="json", **headers)
        if user is not None:
            force_authenticate(request, user=user)
        return BookClassAPI.as_view()(
            request, class_id=self.session.pk if class_id is None else class_id
        )

    def test_authenticated_request_and_retry_return_same_saved_response(self):
        self.make_pack()
        first = self.post(user=self.member)
        second = self.post(user=self.member)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.data, second.data)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(CreditMovement.objects.filter(kind="booking").count(), 1)

    def test_registered_booking_url_calls_view_with_class_id(self):
        self.make_pack()
        client = APIClient()
        client.force_authenticate(self.member)
        response = client.post(
            reverse("book_class", args=[self.session.pk]),
            {},
            format="json",
            HTTP_IDEMPOTENCY_KEY="routed-request",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["class_session_id"], self.session.pk)

    def test_jwt_authentication_passes_correct_member_to_service(self):
        self.make_pack()
        token = str(RefreshToken.for_user(self.member).access_token)
        response = self.post(token=token)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Booking.objects.get().member_id, self.member.pk)

    def test_anonymous_and_invalid_token_are_401(self):
        for token in [None, "not-a-valid-jwt"]:
            with self.subTest(token=token):
                self.assertEqual(self.post(token=token).status_code, 401)
        self.assertFalse(Booking.objects.exists())

    def test_expired_access_token_is_401(self):
        token = RefreshToken.for_user(self.member).access_token
        token.set_exp(lifetime=timedelta(seconds=-1))
        self.assertEqual(self.post(token=str(token)).status_code, 401)
        self.assertFalse(Booking.objects.exists())

    def test_inactive_member_cannot_book_with_previously_issued_token(self):
        token = str(RefreshToken.for_user(self.member).access_token)
        self.member.is_active = False
        self.member.save()
        self.assertEqual(self.post(token=token).status_code, 401)
        self.assertFalse(Booking.objects.exists())

    def test_request_cannot_spend_another_members_credits(self):
        self.make_pack(member=self.other_member)
        response = self.post(user=self.member)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Booking.objects.exists())

    def test_missing_key_is_400(self):
        self.assertEqual(self.post(user=self.member, key=None).status_code, 400)
        self.assertFalse(IdempotencyRecord.objects.exists())

    def test_key_reused_for_different_class_is_409(self):
        self.make_pack()
        self.assertEqual(self.post(user=self.member).status_code, 201)
        response = self.post(user=self.member, class_id=self.make_session().pk)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Booking.objects.count(), 1)

    def test_missing_class_is_404(self):
        self.assertEqual(self.post(user=self.member, class_id=999999).status_code, 404)

    def test_booking_view_is_registered_in_root_urls(self):
        def callbacks(patterns):
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    yield from callbacks(pattern.url_patterns)
                else:
                    yield getattr(pattern.callback, "view_class", None)

        self.assertIn(
            BookClassAPI,
            list(callbacks(get_resolver().url_patterns)),
            "BookClassAPI must have a route reachable through config.urls.",
        )
