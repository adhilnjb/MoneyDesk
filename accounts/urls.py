from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"
urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup, name="signup"),
    path("2fa/verify/", views.verify_2fa, name="verify_2fa"),
    path("security/", views.security_page, name="security"),
    path("2fa/setup/", views.setup_2fa, name="setup_2fa"),
    path("2fa/disable/", views.disable_2fa, name="disable_2fa"),
    path("2fa/recovery/", views.regenerate_codes, name="regenerate_codes"),
    path("password/", auth_views.PasswordChangeView.as_view(
        template_name="accounts/password_change.html", success_url=reverse_lazy("accounts:security")),
        name="password_change"),
]
