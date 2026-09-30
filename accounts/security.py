"""Brute-force protection, TOTP and recovery code helpers."""
import hashlib
import hmac
import re
import secrets

import pyotp
from django.conf import settings
from django.core.cache import cache

from .models import get_profile


def _key(request, identity):
    return f"lock:{request.META.get('REMOTE_ADDR', '')}:{str(identity).lower()}"


def is_locked(request, identity):
    return cache.get(_key(request, identity), 0) >= settings.LOGIN_MAX_ATTEMPTS


def register_failure(request, identity):
    key = _key(request, identity)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, settings.LOGIN_LOCKOUT_SECONDS)


def clear_failures(request, identity):
    cache.delete(_key(request, identity))


def hash_code(code):
    return hmac.new(settings.SECRET_KEY.encode(), code.strip().lower().encode(), hashlib.sha256).hexdigest()


def new_recovery_codes(count=8):
    plain = [f"{secrets.token_hex(5)}-{secrets.token_hex(5)}" for _ in range(count)]
    return plain, [hash_code(c) for c in plain]


def check_second_factor(user, code):
    """True for a valid authenticator code or an unused recovery code (which is then consumed)."""
    profile = get_profile(user)
    code = (code or "").strip()
    digits = code.replace(" ", "")
    if re.fullmatch(r"\d{6}", digits):
        return pyotp.TOTP(profile.totp_secret).verify(digits, valid_window=1)
    digest = hash_code(code)
    for stored in profile.recovery_codes:
        if hmac.compare_digest(stored, digest):
            profile.recovery_codes = [c for c in profile.recovery_codes if c != stored]
            profile.save(update_fields=["recovery_codes"])
            return True
    return False
