from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.models import User

from apps.core.models import AppSetting

from .models import UserProfile


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Username", "autofocus": True}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Password"}))


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=60, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    last_name = forms.CharField(max_length=60, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    email = forms.EmailField(required=False, widget=forms.EmailInput(attrs={"class": "form-control"}))

    class Meta:
        model = UserProfile
        fields = ("phone", "avatar")
        widgets = {
            "phone": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user_id:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email

    def save(self, commit: bool = True) -> UserProfile:
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data.get("first_name", "")
        user.last_name = self.cleaned_data.get("last_name", "")
        user.email = self.cleaned_data.get("email", "")
        if commit:
            user.save()
            profile.save()
        return profile


class StaffUserForm(forms.ModelForm):
    role = forms.ChoiceField(choices=UserProfile.ROLE_CHOICES, widget=forms.Select(attrs={"class": "form-select"}))
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
        required=False,
        help_text="Leave blank to keep current password.",
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email")
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["role"].initial = self.instance.profile.role

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        elif not user.pk:
            user.set_unusable_password()
        if commit:
            user.save()
            profile = user.profile
            profile.role = self.cleaned_data["role"]
            profile.save()
        return user


class PasswordChangeStyledForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update({"class": "form-control"})


class AppSettingForm(forms.ModelForm):
    class Meta:
        model = AppSetting
        exclude = ()
        widgets = {
            "business_name": forms.TextInput(attrs={"class": "form-control"}),
            "business_phone": forms.TextInput(attrs={"class": "form-control"}),
            "business_email": forms.EmailInput(attrs={"class": "form-control"}),
            "business_address": forms.TextInput(attrs={"class": "form-control"}),
            "invoice_prefix": forms.TextInput(attrs={"class": "form-control"}),
            "invoice_footer_note": forms.TextInput(attrs={"class": "form-control"}),
            "low_stock_threshold": forms.NumberInput(attrs={"class": "form-control"}),
            "near_expiry_days": forms.NumberInput(attrs={"class": "form-control"}),
            "default_tax_percent": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "currency_symbol": forms.TextInput(attrs={"class": "form-control"}),
            "logo": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "show_logo_on_print": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
