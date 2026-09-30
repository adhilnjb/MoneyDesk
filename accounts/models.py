from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Two-factor settings for a user. Recovery codes are stored as keyed hashes, never in plain text."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    totp_secret = models.CharField(max_length=64, blank=True)
    totp_enabled = models.BooleanField(default=False)
    recovery_codes = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"Profile for {self.user}"


def get_profile(user):
    return Profile.objects.get_or_create(user=user)[0]
