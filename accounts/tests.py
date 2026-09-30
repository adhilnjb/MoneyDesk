import pyotp
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import get_profile
from . import security

User = get_user_model()
PW = "s3cure-pass-123"


class AuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("adhi", "a@example.com", PW)

    def test_lockout_after_repeated_failures_even_with_right_password(self):
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "adhi", "password": "wrong"})
        resp = self.client.post(reverse("accounts:login"), {"username": "adhi", "password": PW})
        self.assertContains(resp, "Too many attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_without_2fa(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "adhi", "password": PW})
        self.assertRedirects(resp, reverse("ledger:dashboard"), fetch_redirect_response=False)

    def test_2fa_login_and_recovery_code_is_single_use(self):
        secret = pyotp.random_base32()
        plain, hashed = security.new_recovery_codes(2)
        p = get_profile(self.user)
        p.totp_secret, p.totp_enabled, p.recovery_codes = secret, True, hashed
        p.save()

        resp = self.client.post(reverse("accounts:login"), {"username": "adhi", "password": PW})
        self.assertRedirects(resp, reverse("accounts:verify_2fa"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)  # password alone is not enough

        bad = self.client.post(reverse("accounts:verify_2fa"), {"code": "000000"})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(bad, "did not work")

        self.client.post(reverse("accounts:verify_2fa"), {"code": pyotp.TOTP(secret).now()})
        self.assertIn("_auth_user_id", self.client.session)

        self.client.logout()
        self.client.post(reverse("accounts:login"), {"username": "adhi", "password": PW})
        self.client.post(reverse("accounts:verify_2fa"), {"code": plain[0]})
        self.assertIn("_auth_user_id", self.client.session)
        self.client.logout()
        self.client.post(reverse("accounts:login"), {"username": "adhi", "password": PW})
        self.client.post(reverse("accounts:verify_2fa"), {"code": plain[0]})  # reuse
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_2fa_setup_flow(self):
        self.client.force_login(self.user)
        page = self.client.get(reverse("accounts:setup_2fa"))
        self.assertContains(page, "<svg")
        secret = self.client.session["setup_secret"]
        resp = self.client.post(reverse("accounts:setup_2fa"), {"code": pyotp.TOTP(secret).now()})
        self.assertContains(resp, "recovery codes")
        self.assertTrue(get_profile(self.user).totp_enabled)

    def test_open_redirect_blocked(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "adhi", "password": PW, "next": "https://evil.example/"})
        self.assertRedirects(resp, reverse("ledger:dashboard"), fetch_redirect_response=False)

    @override_settings(ALLOW_SIGNUP=False)
    def test_signup_can_be_disabled(self):
        self.assertEqual(self.client.get(reverse("accounts:signup")).status_code, 404)

    def test_signup_seeds_wallets(self):
        resp = self.client.post(reverse("accounts:signup"), {
            "username": "newbie", "email": "n@example.com", "password1": "long-enough-pw-77", "password2": "long-enough-pw-77"})
        self.assertRedirects(resp, reverse("ledger:dashboard"), fetch_redirect_response=False)
        self.assertEqual(User.objects.get(username="newbie").wallets.count(), 4)


DB_CACHE = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "moneydesk_cache", "TIMEOUT": 900}}


@override_settings(CACHES=DB_CACHE)
class DatabaseCacheLockoutTests(TestCase):
    """Production (serverless) keeps lockout counters in a database table."""

    def test_lockout_works_with_database_cache(self):
        from django.core.management import call_command
        call_command("createcachetable", verbosity=0)
        User.objects.create_user("adhi", "a@example.com", PW)
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": "adhi", "password": "wrong"})
        resp = self.client.post(reverse("accounts:login"), {"username": "adhi", "password": PW})
        self.assertContains(resp, "Too many attempts")
