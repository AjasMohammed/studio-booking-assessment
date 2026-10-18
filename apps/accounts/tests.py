from django.urls import reverse
from rest_framework.response import Response
from rest_framework.test import APITestCase

from apps.accounts.models import Role, User
from apps.testing import DomainFixtures


class AccountAPITests(DomainFixtures, APITestCase):
    password = "R7!xQ9#vK2@mL8$z"  # noqa: S105 -- test-only credential

    def signup(self, **overrides: object) -> Response:
        data: dict[str, object] = {
            "username": "new-member",
            "email": "new@example.com",
            "password": self.password,
        }
        data.update(overrides)
        return self.client.post(reverse("signup"), data, format="json")

    def test_public_signup_creates_member_with_hashed_password(self) -> None:
        response = self.signup()
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="new-member")
        self.assertEqual(user.role, Role.MEMBER)
        self.assertNotEqual(user.password, self.password)
        self.assertTrue(user.check_password(self.password))
        self.assertNotIn("password", response.data)

    def test_public_signup_allows_staff_role_for_assessment_testing(self) -> None:
        response = self.signup(role=Role.STAFF)
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="new-member")
        self.assertEqual(user.role, Role.STAFF)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_public_signup_cannot_set_django_admin_flags(self) -> None:
        response = self.signup(is_staff=True, is_superuser=True)
        self.assertIn(response.status_code, [201, 400])
        if response.status_code == 201:
            user = User.objects.get(username="new-member")
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)

    def test_signup_rejects_missing_email_invalid_email_and_weak_password(self) -> None:
        for changes in [
            {"email": ""},
            {"email": "invalid-email"},
            {"password": "123"},
            {"username": ""},
        ]:
            with self.subTest(changes=changes):
                self.assertEqual(self.signup(**changes).status_code, 400)
        response = self.client.post(
            reverse("signup"),
            {
                "username": "new-member",
                "password": self.password,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username="new-member").exists())

    def test_duplicate_username_is_400(self) -> None:
        self.assertEqual(self.signup(username=self.member.username).status_code, 400)

    def test_signup_preserves_password_whitespace(self) -> None:
        password = f"  {self.password}  "
        self.assertEqual(self.signup(password=password).status_code, 201)
        self.assertTrue(
            User.objects.get(username="new-member").check_password(password)
        )

    def test_login_issues_tokens_only_for_correct_active_credentials(self) -> None:
        self.member.set_password(self.password)
        self.member.save()
        data = {"username": self.member.username, "password": self.password}
        response = self.client.post(reverse("token_obtain_pair"), data, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        data["password"] = "incorrect-password"  # noqa: S105 -- test-only credential
        self.assertEqual(
            self.client.post(
                reverse("token_obtain_pair"), data, format="json"
            ).status_code,
            401,
        )
        self.member.is_active = False
        self.member.save()
        data["password"] = self.password
        self.assertEqual(
            self.client.post(
                reverse("token_obtain_pair"), data, format="json"
            ).status_code,
            401,
        )

    def test_rotated_refresh_token_cannot_be_reused(self) -> None:
        self.member.set_password(self.password)
        self.member.save()
        login = self.client.post(
            reverse("token_obtain_pair"),
            {
                "username": self.member.username,
                "password": self.password,
            },
            format="json",
        )
        original = login.data["refresh"]
        response = self.client.post(
            reverse("token_refresh"),
            {
                "refresh": original,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.data["refresh"], original)
        self.assertEqual(
            self.client.post(
                reverse("token_refresh"),
                {
                    "refresh": original,
                },
                format="json",
            ).status_code,
            401,
        )

    def test_member_list_requires_staff_and_never_exposes_passwords(self) -> None:
        self.assertEqual(self.client.get(reverse("list_members")).status_code, 401)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get(reverse("list_members")).status_code, 403)
        self.client.force_authenticate(self.staff)
        response = self.client.get(reverse("list_members"))
        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            [row["id"] for row in response.data],
            [self.member.pk, self.other_member.pk],
        )
        self.assertTrue(all("password" not in row for row in response.data))
