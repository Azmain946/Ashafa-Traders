from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_http_methods

from apps.core.models import AppSetting

from .forms import (
    AppSettingForm,
    LoginForm,
    PasswordChangeStyledForm,
    ProfileForm,
    StaffUserForm,
)
from .models import UserProfile


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        messages.success(request, "Welcome back!")
        next_url = request.GET.get("next") or reverse("dashboard:home")
        return HttpResponseRedirect(next_url)
    return render(request, "accounts/login.html", {"form": form})


def logout_view(request):
    logout(request)
    messages.info(request, "You have been signed out.")
    return redirect("accounts:login")


def _is_admin(user) -> bool:
    return user.is_authenticated and (user.is_superuser or getattr(user.profile, "is_admin", False))


@login_required
def settings_page(request):
    setting = AppSetting.load()
    profile = request.user.profile

    profile_form = ProfileForm(instance=profile)
    setting_form = AppSettingForm(instance=setting)
    password_form = PasswordChangeStyledForm(request.user)

    if request.method == "POST":
        section = request.POST.get("section")
        if section == "profile":
            profile_form = ProfileForm(request.POST, request.FILES, instance=profile)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated.")
                return redirect("accounts:settings")
        elif section == "business" and _is_admin(request.user):
            setting_form = AppSettingForm(request.POST, request.FILES, instance=setting)
            if setting_form.is_valid():
                setting_form.save()
                messages.success(request, "Business settings saved.")
                return redirect("accounts:settings")
        elif section == "password":
            password_form = PasswordChangeStyledForm(request.user, request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Password changed.")
                return redirect("accounts:settings")

    staff_users = User.objects.select_related("profile").order_by("username") if _is_admin(request.user) else None

    return render(
        request,
        "accounts/settings.html",
        {
            "profile_form": profile_form,
            "setting_form": setting_form,
            "password_form": password_form,
            "staff_users": staff_users,
            "is_admin_user": _is_admin(request.user),
        },
    )


@login_required
@user_passes_test(_is_admin, login_url=reverse_lazy("accounts:settings"))
@require_http_methods(["GET", "POST"])
def staff_user_form(request, user_id: int | None = None):
    user_obj = get_object_or_404(User, pk=user_id) if user_id else None
    form = StaffUserForm(request.POST or None, instance=user_obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "User saved.")
        return redirect("accounts:settings")
    return render(request, "accounts/staff_form.html", {"form": form, "user_obj": user_obj})


@login_required
@user_passes_test(_is_admin, login_url=reverse_lazy("accounts:settings"))
def staff_user_delete(request, user_id: int):
    user_obj = get_object_or_404(User, pk=user_id)
    if user_obj == request.user:
        messages.error(request, "You cannot delete yourself.")
    else:
        user_obj.delete()
        messages.success(request, "User removed.")
    return redirect("accounts:settings")
