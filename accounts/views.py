import time

import pyotp
import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ledger.services import seed_defaults

from . import security
from .forms import SignupForm
from .models import get_profile

User = get_user_model()
LOCKED = "Too many attempts. Wait a few minutes and try again."


def _safe_next(request, value):
    ok = value and url_has_allowed_host_and_scheme(value, {request.get_host()}, request.is_secure())
    return value if ok else settings.LOGIN_REDIRECT_URL


def signup(request):
    if not settings.ALLOW_SIGNUP:
        raise Http404
    if request.user.is_authenticated:
        return redirect("ledger:dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        seed_defaults(user)
        login(request, user)
        return redirect("ledger:dashboard")
    return render(request, "accounts/signup.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("ledger:dashboard")
    next_url = request.POST.get("next") or request.GET.get("next", "")
    form = AuthenticationForm(request, data=request.POST or None)
    locked = False
    if request.method == "POST":
        username = request.POST.get("username", "")
        if security.is_locked(request, username):
            locked = True  # do not even try the password while locked
        elif form.is_valid():
            user = form.get_user()
            security.clear_failures(request, username)
            if get_profile(user).totp_enabled:
                request.session["pre2fa"] = {"uid": user.pk, "backend": user.backend, "ts": time.time(), "next": next_url}
                return redirect("accounts:verify_2fa")
            login(request, user)
            return redirect(_safe_next(request, next_url))
        else:
            security.register_failure(request, username)
    return render(request, "accounts/login.html", {
        "form": form, "next": next_url, "locked": locked, "lock_message": LOCKED, "can_signup": settings.ALLOW_SIGNUP})


def verify_2fa(request):
    pending = request.session.get("pre2fa")
    if not pending or time.time() - pending["ts"] > 300:
        request.session.pop("pre2fa", None)
        return redirect("accounts:login")
    user = get_object_or_404(User, pk=pending["uid"], is_active=True)
    identity, error = f"2fa:{user.pk}", None
    if request.method == "POST":
        if security.is_locked(request, identity):
            error = LOCKED
        elif security.check_second_factor(user, request.POST.get("code", "")):
            security.clear_failures(request, identity)
            request.session.pop("pre2fa", None)
            login(request, user, backend=pending["backend"])
            return redirect(_safe_next(request, pending.get("next", "")))
        else:
            security.register_failure(request, identity)
            error = "That code did not work. Try the next code from your app, or a recovery code."
    return render(request, "accounts/verify_2fa.html", {"error": error})


@login_required
def security_page(request):
    profile = get_profile(request.user)
    return render(request, "accounts/security.html", {"profile": profile, "codes_left": len(profile.recovery_codes)})


@login_required
def setup_2fa(request):
    profile = get_profile(request.user)
    if profile.totp_enabled:
        return redirect("accounts:security")
    secret = request.session.get("setup_secret") or pyotp.random_base32()
    request.session["setup_secret"] = secret
    error = None
    if request.method == "POST":
        if pyotp.TOTP(secret).verify(request.POST.get("code", "").replace(" ", ""), valid_window=1):
            plain, hashed = security.new_recovery_codes()
            profile.totp_secret, profile.totp_enabled, profile.recovery_codes = secret, True, hashed
            profile.save()
            request.session.pop("setup_secret", None)
            return render(request, "accounts/recovery_codes.html", {"codes": plain, "first": True})
        error = "That code did not match. Check the time on your phone and try again."
    uri = pyotp.TOTP(secret).provisioning_uri(name=request.user.username, issuer_name="MoneyDesk")
    svg = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).to_string(encoding="unicode")
    return render(request, "accounts/setup_2fa.html", {"qr": svg, "secret": secret, "error": error})


@login_required
@require_POST
def disable_2fa(request):
    if request.user.check_password(request.POST.get("password", "")):
        profile = get_profile(request.user)
        profile.totp_secret, profile.totp_enabled, profile.recovery_codes = "", False, []
        profile.save()
        messages.success(request, "Two-factor login is off.")
    else:
        messages.error(request, "Wrong password. Two-factor login is still on.")
    return redirect("accounts:security")


@login_required
@require_POST
def regenerate_codes(request):
    profile = get_profile(request.user)
    if profile.totp_enabled and request.user.check_password(request.POST.get("password", "")):
        plain, profile.recovery_codes = security.new_recovery_codes()
        profile.save()
        return render(request, "accounts/recovery_codes.html", {"codes": plain, "first": False})
    messages.error(request, "Wrong password. Recovery codes were not changed.")
    return redirect("accounts:security")
